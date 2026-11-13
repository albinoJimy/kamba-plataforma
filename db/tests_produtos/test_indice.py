"""O indice de pesquisa por tenant contra um PostgreSQL real (KAM-061, `0045`).

O que esta suite prova, criterio a criterio do bloco KAM-061:

* **1** — os ensaios T1-T4 do `docs/tecnica/05` §6.4, cada um no seu caso, com a
  asercao do documento e mais uma: **qual** produto veio, e nao so quantos;
* **2** — isolamento entre tres tenants, e os estados `suspenso` e `onboarding`;
* **3** — RLS `FORCE` nas duas tabelas, e zero linhas sem contexto;
* **4** — nenhuma coluna do esquema com preco, stock ou quantidade no nome;
* **5** — zero indices ANN no esquema;
* **6** — `p_qvec` nulo, ranking lexical igual, e o desempate por `doc_id`;
* **7** — o defeito D7;
* **8** — a camada de resposta, pela funcao que a aplicacao chama
  (`kamba_core.idx.pesquisa.pesquisar`), com o filtro de preco na oferta viva;
* o consumidor, idempotente com dez duplicados;
* **KAM-063** (`TestEmbeddings`): o *worker* dos embeddings do catalogo, o
  vector anulado por mudar o nome e nao o preco, a escrita que confere o texto,
  um modelo por coluna, e a pesquisa hibrida com o lexical como chao.

## O isolamento mede-se pela ligacao, e nao pelo parametro

O `idx.candidatos` recebe `p_tenant`, e um ensaio que so passasse o tenant certo
no parametro e no contexto **nao distinguia** «a funcao isola» de «o chamador
pediu bem». Por isso os casos de isolamento poem o contexto **num** tenant e o
parametro **noutro**, e exigem zero linhas: o que isola e a RLS de quem chama,
e o parametro nao a contorna. E a camada de resposta nem tem parametro de
tenant — mede-se chamando-a com o tenant A sobre dados em que B tem o mesmo
`sku`, o mesmo nome e um preco diferente.

## Porque esta suite e nao uma propria

Pela razao do `tests_produtos` no KAM-051 (`db/mutacoes.py`, nota do
`PRODUTOS`): e a suite que ja tem a `offer_terms` semeada e confirmada, as
ligacoes de `kamba_app` por tenant e a vista da oferta viva — que e metade do
que a camada de resposta junta.
"""

from __future__ import annotations

import asyncio
import re
import sys
import unittest
import uuid
import zlib
from pathlib import Path
from types import SimpleNamespace

import indice
from tests import factories
from tests_produtos.base import PRECO, SKU_PARTILHADO, ComOfertas

_RAIZ = Path(__file__).resolve().parents[2]
if str(_RAIZ / "libs" / "py-core" / "src") not in sys.path:
    sys.path.insert(0, str(_RAIZ / "libs" / "py-core" / "src"))

import ligacao  # noqa: E402
from kamba_core.destinos import PortaSobreDestinos  # noqa: E402
from kamba_core.destinos import dbapi as destinos_dbapi  # noqa: E402
from kamba_core.eventos.consumo import Resultado  # noqa: E402
from kamba_core.idx import consumidor, embeddings, pesquisa  # noqa: E402
from kamba_core.idx import metricas as metricas_mod  # noqa: E402
from kamba_core.idx import texto as texto_mod  # noqa: E402

#: O documento que declara o contrato de saida da camada de resposta.
DOC_INDICE = _RAIZ / "docs" / "tecnica" / "05_Indice_Pesquisa_Motor_Atencao.md"

#: A dimensao da coluna de embedding (`halfvec(1024)`, §4.2).
DIMENSAO = 1024


def _vector(*primeiros: float) -> str:
    """Um `halfvec(1024)` em texto, com os primeiros valores dados e zeros."""
    valores = list(primeiros) + [0.0] * (DIMENSAO - len(primeiros))
    return "[" + ",".join(str(v) for v in valores) + "]"


class ComIndice(ComOfertas):
    """Tenants com estado escolhido, documentos semeados e limpeza do `idx`."""

    def setUp(self) -> None:
        super().setUp()
        # LIFO: corre **antes** da limpeza da `ComOfertas`, que apaga os
        # tenants — e as duas tabelas do `idx` tem FK para eles.
        self.addCleanup(self._limpar_indice)

    def _limpar_indice(self) -> None:
        for tenant in self._tenants:
            for tabela in ("idx.search_doc", "idx.termo_canonico"):
                self.semente.execute(f"DELETE FROM {tabela} WHERE tenant_id = %s", (tenant,))
            self.semente.execute(
                "DELETE FROM platform.events_consumed WHERE tenant_id = %s", (tenant,)
            )

    def tenant_em(self, estado: str) -> str:
        """Um tenant no estado pedido. `ativo` passa pelo aceite do KAM-090."""
        tenant = self.criar_tenant()
        if estado == "onboarding":
            return tenant
        factories.aceitar_contratos_vigentes(self.semente, tenant)
        self.semente.execute(
            "UPDATE platform.tenants SET estado = 'ativo' WHERE id = %s", (tenant,)
        )
        if estado != "ativo":
            self.semente.execute(
                "UPDATE platform.tenants SET estado = %s WHERE id = %s", (estado, tenant)
            )
        return tenant

    def documento(
        self,
        tenant: str,
        ref: str,
        nome_norm: str,
        *,
        marca: str | None = None,
        descr: str = "",
        visivel: bool = True,
        embedding: str | None = None,
    ) -> str:
        self.semente.execute(
            "INSERT INTO idx.search_doc "
            "(tenant_id, product_ref, norm_versao, nome_norm, marca_canon, descr_norm, "
            " visivel, embedding) "
            "VALUES (%s, %s, 1, %s, %s, %s, %s, %s::halfvec) RETURNING doc_id",
            (tenant, ref, nome_norm, marca, descr, visivel, embedding),
        )
        return str(self.semente.fetchone()[0])

    def candidatos(
        self,
        contexto: str | None,
        p_tenant: str,
        q_norm: str,
        q_or: str,
        *,
        qvec: str | None = None,
        k: int | None = None,
    ) -> list[tuple]:
        """`(product_ref, score, rk_sem, rk_tri, rk_fts, doc_id)` como `kamba_app`.

        O limiar e o do chamador do §6.2 (nota i), na mesma transaccao, e a
        transaccao desfaz-se no fim: o `SET LOCAL` nao passa ao caso seguinte.
        """
        cursor = self.cursor_app(contexto)
        cursor.execute(pesquisa.SQL_LIMIAR, (str(indice.LIMIAR_DE_PALAVRA),))
        argumentos = [p_tenant, q_norm, q_or, qvec]
        extra = ""
        if k is not None:
            extra = ", %s"
            argumentos.append(k)
        cursor.execute(
            "SELECT o_product_ref, o_score, o_rk_sem, o_rk_tri, o_rk_fts, o_doc_id::text "
            f"  FROM idx.candidatos(%s, %s, %s, %s::halfvec{extra})",
            tuple(argumentos),
        )
        linhas = [tuple(linha) for linha in cursor.fetchall()]
        self.desfazer(contexto)
        return linhas

    def desfazer(self, contexto: str | None) -> None:
        """Desfaz a transaccao da ligacao de `kamba_app` desse contexto."""
        self._app[f"app:{contexto or ''}"].rollback()  # type: ignore[attr-defined]


class TestEsquema(ComIndice):
    """Criterios 3, 4 e 5, e quem pode o que no esquema."""

    def test_as_duas_tabelas_tem_rls_force(self) -> None:
        """Criterio 3: `ENABLE` e `FORCE`, nas duas."""
        linhas = self.consultar(
            "SELECT c.relname::text, c.relrowsecurity, c.relforcerowsecurity "
            "  FROM pg_class c JOIN pg_namespace n ON n.oid = c.relnamespace "
            " WHERE n.nspname = 'idx' AND c.relkind = 'r' ORDER BY 1"
        )
        # A `norm_versao` (KAM-062, `0049`) nao tem `tenant_id` nem RLS: a versao
        # e global (§4.4), e o *gate* 6 pergunta por RLS a quem tem a coluna.
        self.assertEqual(
            [tuple(linha) for linha in linhas],
            [
                ("norm_versao", False, False),
                ("search_doc", True, True),
                ("termo_canonico", True, True),
            ],
        )

    def test_nenhuma_coluna_do_idx_fala_de_preco_nem_de_stock(self) -> None:
        """Criterio 4, a metade do esquema: zero colunas com os quatro nomes."""
        linhas = self.consultar(
            "SELECT table_name, column_name FROM information_schema.columns "
            " WHERE table_schema = 'idx' AND column_name ~* %s",
            (indice.COLUNAS_PROIBIDAS,),
        )
        self.assertEqual(list(linhas), [])
        # A expressao morde: o mesmo filtro sobre o `platform` encontra o
        # `preco_minor` da oferta. Sem isto, um padrao que nunca casa dava o
        # mesmo zero.
        controlo = self.consultar(
            "SELECT count(*) FROM information_schema.columns "
            " WHERE table_schema = 'platform' AND table_name = 'offer_terms' "
            "   AND column_name ~* %s",
            (indice.COLUNAS_PROIBIDAS,),
        )
        self.assertGreater(controlo[0][0], 0)

    def test_zero_indices_ann_no_esquema(self) -> None:
        """Criterio 5, a consulta do bloco, a letra."""
        linhas = self.consultar(
            "SELECT count(*) FROM pg_indexes "
            " WHERE schemaname = 'idx' AND indexdef ~* '(hnsw|ivfflat)'"
        )
        self.assertEqual(linhas[0][0], 0)
        # E os tres do §4.2 existem: o zero de cima nao vem de um esquema vazio.
        nomes = self.consultar(
            "SELECT indexname::text FROM pg_indexes "
            " WHERE schemaname = 'idx' AND tablename = 'search_doc' ORDER BY 1"
        )
        self.assertLessEqual(
            {"search_doc_fts_gin", "search_doc_nome_trgm", "search_doc_tenant"},
            {str(n[0]) for n in nomes},
        )

    def test_a_funcao_corre_com_os_privilegios_de_quem_chama(self) -> None:
        """Criterio 3: `SECURITY INVOKER`, e so o `kamba_app` a executa."""
        linhas = self.consultar(
            "SELECT p.prosecdef, p.provolatile, "
            "       has_function_privilege('kamba_app', p.oid, 'EXECUTE'), "
            "       has_function_privilege('kamba_batch', p.oid, 'EXECUTE') "
            "  FROM pg_proc p JOIN pg_namespace n ON n.oid = p.pronamespace "
            " WHERE n.nspname = 'idx' AND p.proname = 'candidatos'"
        )
        self.assertEqual([tuple(linha) for linha in linhas], [(False, "s", True, False)])

    def test_o_kamba_app_le_e_escreve_o_indice_e_nao_apaga(self) -> None:
        """O consumidor escreve, a purga e da retencao, e o lexico so se le."""
        esperado = {
            ("search_doc", "SELECT"): True,
            ("search_doc", "INSERT"): True,
            ("search_doc", "UPDATE"): True,
            ("search_doc", "DELETE"): False,
            ("termo_canonico", "SELECT"): True,
            ("termo_canonico", "INSERT"): False,
            ("termo_canonico", "UPDATE"): False,
            ("termo_canonico", "DELETE"): False,
            # KAM-062: a versao le-se e nunca se escreve pela aplicacao.
            ("norm_versao", "SELECT"): True,
            ("norm_versao", "INSERT"): False,
            ("norm_versao", "UPDATE"): False,
            ("norm_versao", "DELETE"): False,
        }
        for (tabela, privilegio), tem in esperado.items():
            with self.subTest(tabela=tabela, privilegio=privilegio):
                linha = self.consultar(
                    "SELECT has_table_privilege('kamba_app', %s, %s)",
                    (f"idx.{tabela}", privilegio),
                )
                self.assertEqual(linha[0][0], tem)
        # Nenhum outro papel da aplicacao toca no esquema.
        for papel in ("kamba_batch", "kamba_resolver", "kamba_agr", "kamba_identity"):
            with self.subTest(papel=papel):
                linha = self.consultar(
                    "SELECT has_schema_privilege(%s, 'idx', 'USAGE')", (papel,)
                )
                self.assertFalse(linha[0][0])

    def test_as_entradas_globais_do_lexico_leem_se_e_nao_se_escrevem(self) -> None:
        """Criterio 3: «entradas globais com `tenant_id` nulo legiveis»."""
        tenant = self.tenant_em("ativo")
        termo = f"global_{uuid.uuid4().hex[:8]}"
        self.semente.execute(
            "INSERT INTO idx.termo_canonico "
            "(tenant_id, tipo, termo, canonico, origem, aprovado_por) "
            "VALUES (NULL, 'sinonimo', %s, 'frigorifico', 'ops', 'ensaio')",
            (termo,),
        )
        self.addCleanup(
            self.semente.execute,
            "DELETE FROM idx.termo_canonico WHERE termo = %s",
            (termo,),
        )
        cursor = self.cursor_app(tenant)
        cursor.execute("SELECT canonico FROM idx.termo_canonico WHERE termo = %s", (termo,))
        self.assertEqual([tuple(l) for l in cursor.fetchall()], [("frigorifico",)])
        self.desfazer(tenant)
        # Sem contexto, a global continua legivel: e global.
        cursor = self.cursor_app(None)
        cursor.execute("SELECT count(*) FROM idx.termo_canonico WHERE termo = %s", (termo,))
        self.assertEqual(cursor.fetchone()[0], 1)
        self.desfazer(None)


class TestCandidatos(ComIndice):
    """Criterios 1, 2, 3, 6 e 7 sobre o `idx.candidatos`."""

    def setUp(self) -> None:
        super().setUp()
        # Os quatro produtos do §6.4, e o tenant `onboarding` que o criterio 2
        # acrescenta. Os `product_ref` sao os do documento.
        self.ta = self.tenant_em("ativo")
        self.tb = self.tenant_em("ativo")
        self.ts = self.tenant_em("suspenso")
        self.to = self.tenant_em("onboarding")
        self.p1 = self.documento(
            self.ta, "p1", "nike air force 1 branco", marca="nike", descr="tenis"
        )
        self.p2 = self.documento(
            self.ta, "p2", "frigorifico lg 250 l", marca="lg", descr="geleira combinada"
        )
        self.documento(self.tb, "p3", "nike air max", marca="nike", descr="tenis")
        self.documento(self.ts, "p4", "nike air force 1", marca="nike", descr="tenis")
        self.documento(self.to, "p5", "nike air force 1", marca="nike", descr="tenis")

    @staticmethod
    def refs(linhas: list[tuple]) -> list[str]:
        return [str(linha[0]) for linha in linhas]

    # ------------------------------------------------------------- T1 a T4
    def test_t1_typo_encontra_o_produto_de_a_e_so_de_a(self) -> None:
        """T1: «niker» encontra o produto de A, so de A."""
        linhas = self.candidatos(self.ta, self.ta, "niker", "niker")
        self.assertEqual(self.refs(linhas), ["p1"])

    def test_t2_nenhum_resultado_de_b_ou_s_ao_pesquisar_em_a(self) -> None:
        """T2, com o *join* do documento: zero linhas com `tenant_id <> A`.

        O *join* corre como administrador, que ve tudo: e ele que diz de que
        tenant e cada `doc_id` devolvido, sem depender da RLS que se mede.
        """
        linhas = self.candidatos(self.ta, self.ta, "nike", "nike")
        self.assertEqual(self.refs(linhas), ["p1"])
        doc_ids = [linha[5] for linha in linhas]
        self.semente.execute(
            "SELECT count(*) FROM idx.search_doc "
            " WHERE doc_id = ANY(%s::uuid[]) AND tenant_id <> %s",
            (doc_ids, self.ta),
        )
        self.assertEqual(self.semente.fetchone()[0], 0)

    def test_t3_tenant_suspenso_zero_resultados(self) -> None:
        """T3, e com `visivel = true`: e a porta `tn` que fecha."""
        self.assertEqual(self.candidatos(self.ts, self.ts, "nike", "nike"), [])

    def test_t4_sinonimo_so_na_descricao_bate_pela_expansao(self) -> None:
        """T4: «geleira» so existe no `descr_norm`, e bate pelo FTS com o `or`."""
        linhas = self.candidatos(self.ta, self.ta, "geleira", "geleira or frigorifico")
        self.assertEqual(self.refs(linhas), ["p2"])
        self.assertIsNone(linhas[0][3], "o trigrama nao devia bater no nome")
        self.assertEqual(linhas[0][4], 1)

    # ---------------------------------------------------------- criterio 2
    def test_tenant_em_onboarding_zero_resultados_com_visivel(self) -> None:
        """Criterio 2: `onboarding` e outra omissao do dominio, e tambem fecha."""
        self.assertEqual(self.candidatos(self.to, self.to, "nike", "nike"), [])

    def test_os_estados_que_nao_sao_ativo_fecham_todos(self) -> None:
        """Criterio 2, o dominio inteiro e nao so os dois que a prosa nomeia.

        A licao do KAM-051: com um predicado sobre um dominio fechado, o caso
        negativo tem de cobrir a omissao e os outros valores. Trocar a porta
        para `estado <> 'suspenso'` deixava o T3 verde.
        """
        for estado in ("restrito", "encerrado"):
            with self.subTest(estado=estado):
                tenant = self.tenant_em(estado)
                self.documento(tenant, "p9", "nike air force 1", marca="nike")
                self.assertEqual(self.candidatos(tenant, tenant, "nike", "nike"), [])

    def test_homonimos_em_tres_tenants_nao_atravessam(self) -> None:
        """Criterio 2: A pesquisa «nike» com homonimos em B e S ve so o seu."""
        for tenant, esperado in ((self.ta, ["p1"]), (self.tb, ["p3"])):
            with self.subTest(tenant=tenant):
                self.assertEqual(
                    self.refs(self.candidatos(tenant, tenant, "nike", "nike")), esperado
                )

    # ---------------------------------------------------------- criterio 3
    def test_o_parametro_de_outro_tenant_nao_contorna_o_contexto(self) -> None:
        """O isolamento e da ligacao: contexto A, `p_tenant = B` → zero linhas.

        B esta `ativo` e tem um homonimo visivel. Se a funcao confiasse no
        parametro, devolvia-o; quem a fecha e a RLS de `platform.tenants` (a
        porta `tn` le zero tenants) e de `idx.search_doc`.
        """
        self.assertEqual(self.candidatos(self.ta, self.tb, "nike", "nike"), [])
        # O controlo: com o contexto de B, o mesmo parametro devolve o de B.
        self.assertEqual(self.refs(self.candidatos(self.tb, self.tb, "nike", "nike")), ["p3"])

    def test_sem_contexto_zero_linhas(self) -> None:
        """Criterio 3: sem `app.tenant_id` a funcao devolve zero linhas."""
        self.assertEqual(self.candidatos(None, self.ta, "nike", "nike"), [])

    def test_invisivel_nao_sai_mesmo_no_proprio_tenant(self) -> None:
        """A primeira defesa: `visivel = false` nao entra em nenhum ramo."""
        self.documento(self.ta, "p6", "nike air zoom", marca="nike", visivel=False)
        self.assertEqual(self.refs(self.candidatos(self.ta, self.ta, "nike", "nike")), ["p1"])

    # ---------------------------------------------------------- criterio 6
    def test_qvec_nulo_e_modo_lexical_com_o_mesmo_ranking(self) -> None:
        """Criterio 6: sem vector, `o_rk_sem` nulo e o ranking lexical intacto.

        Com vector, o ramo `sem` entra e os postos `tri` e `fts` de cada
        documento sao **os mesmos** — o modo lexical e o hibrido sem o ramo
        semantico, e nao outra pesquisa.
        """
        self.semente.execute(
            "UPDATE idx.search_doc SET embedding = %s::halfvec WHERE doc_id = %s",
            (_vector(1.0), self.p1),
        )
        lexical = self.candidatos(self.ta, self.ta, "nike", "nike or tenis")
        hibrido = self.candidatos(self.ta, self.ta, "nike", "nike or tenis", qvec=_vector(1.0))
        self.assertTrue(lexical)
        self.assertTrue(all(linha[2] is None for linha in lexical))
        self.assertEqual(
            {linha[0]: (linha[3], linha[4]) for linha in lexical},
            {linha[0]: (linha[3], linha[4]) for linha in hibrido if linha[0] in self.refs(lexical)},
        )
        self.assertEqual([linha[2] for linha in hibrido if linha[0] == "p1"], [1])

    def test_vinte_execucoes_devolvem_a_mesma_lista(self) -> None:
        """Criterio 6, a letra: 20 execucoes, a mesma lista ordenada."""
        for i in range(6):
            self.documento(self.ta, f"igual{i}", "nike air force 1 branco", marca="nike")
        primeira = self.candidatos(self.ta, self.ta, "nike", "nike")
        for _ in range(19):
            self.assertEqual(self.candidatos(self.ta, self.ta, "nike", "nike"), primeira)

    def test_o_empate_no_limite_decide_se_pelo_doc_id(self) -> None:
        """Criterio 6: com empates **no limite**, passam os de `doc_id` menor.

        Sete documentos com o mesmo nome e `p_k = 3`, num tenant so deles: todos
        empatam nos dois ramos. O §6.2 so desempatava depois do `LIMIT`, e quais
        tres passavam era a ordem fisica; a adaptacao 3 do `db/indice.py` poe o
        `doc_id` antes. **Os `doc_id` entram por ordem decrescente**, e e isso
        que torna a mutacao do desempate mortal sempre e nao em probabilidade: sem
        ele, a ordem fisica da os tres **maiores** (achado 8 da revisao).
        """
        tenant = self.tenant_em("ativo")
        doc_ids = sorted((str(uuid.uuid4()) for _ in range(7)), reverse=True)
        for i, doc_id in enumerate(doc_ids):
            self.semente.execute(
                "INSERT INTO idx.search_doc (doc_id, tenant_id, product_ref, norm_versao, "
                " nome_norm, marca_canon, descr_norm) "
                "VALUES (%s, %s, %s, 1, 'nike air force 1 branco', 'nike', 'tenis')",
                (doc_id, tenant, f"igual{i}"),
            )
        linhas = self.candidatos(tenant, tenant, "nike", "nike", k=3)
        self.assertEqual([linha[5] for linha in linhas], sorted(doc_ids)[:3])
        # **E por um ramo de cada vez.** Com «nike» os sete empatam nos dois
        # ramos, e os de `doc_id` menor ganham pelo `tri` mesmo com o desempate
        # do `fts` sorteado — a mutacao desse desempate sobreviveu assim,
        # medido. «tenis» so existe no `descr_norm`: so o `fts` responde.
        linhas = self.candidatos(tenant, tenant, "tenis", "tenis", k=3)
        self.assertTrue(all(linha[3] is None for linha in linhas), "o tri nao devia bater")
        self.assertEqual([linha[5] for linha in linhas], sorted(doc_ids)[:3])

    def test_o_tenant_pequeno_obtem_resultados_ao_lado_de_um_grande(self) -> None:
        """DoD: o modo de falha do §7.1, que sem ANN nao pode acontecer.

        Um tenant com 300 documentos, todos com o **mesmo** vector da pergunta,
        e um tenant com um so documento, mais longe. Com um ANN de filtro
        posterior, os vizinhos seriam todos do grande e o pequeno ficava vazio
        sem erro; com a busca exacta por tenant, o pequeno ve o seu.
        """
        grande = self.tenant_em("ativo")
        self.semente.execute(
            "INSERT INTO idx.search_doc (tenant_id, product_ref, norm_versao, nome_norm, embedding) "
            "SELECT %s, 'g' || g, 1, 'nike air force 1', %s::halfvec FROM generate_series(1, 300) g",
            (grande, _vector(1.0)),
        )
        self.semente.execute(
            "UPDATE idx.search_doc SET embedding = %s::halfvec WHERE doc_id = %s",
            (_vector(0.5, 0.5), self.p1),
        )
        linhas = self.candidatos(self.ta, self.ta, "zzz", "zzz", qvec=_vector(1.0))
        self.assertEqual([(linha[0], linha[2]) for linha in linhas], [("p1", 1)])

    # ---------------------------------------------------------- criterio 7
    def test_um_termo_inexistente_nao_anula_os_outros(self) -> None:
        """Criterio 7, defeito D7: tres termos, um sem correspondencia."""
        linhas = self.candidatos(
            self.ta, self.ta, "nike xyzzy branco", "nike or xyzzy or branco"
        )
        self.assertEqual(self.refs(linhas), ["p1"])
        self.assertIsNotNone(linhas[0][4], "e o FTS que o devolve, com o `or`")


class _Cliente:
    """O `ClienteSql` do KAM-006 sobre uma ligacao `pg8000` em `autocommit`.

    Em `autocommit` para que o `BEGIN`/`COMMIT` do `consumir` sejam os que
    delimitam a transaccao, e nao uma implicita do condutor.
    """

    def __init__(self, conexao) -> None:
        self.conexao = conexao
        self.cursor = conexao.cursor()

    def executar(self, sql: str, parametros=()) -> Resultado:
        self.cursor.execute(sql, tuple(parametros))
        linhas = ()
        if self.cursor.description:
            nomes = [d[0] for d in self.cursor.description]
            linhas = tuple(dict(zip(nomes, linha)) for linha in self.cursor.fetchall())
        contagem = self.cursor.rowcount
        return Resultado(linhas=linhas, contagem=None if contagem < 0 else contagem)


def _envelope(tenant: str, tipo: str, payload: dict, seq: int = 1) -> dict:
    return {
        "id": str(uuid.uuid4()),
        "tipo": tipo,
        "versao": 2 if tipo == "catalog.product_changed" else 1,
        "tenant_id": tenant,
        "agregado": {
            "tipo": "product" if tipo.startswith("catalog.") else "tenant",
            "id": str(uuid.uuid4()),
            "seq": seq,
        },
        "payload": payload,
    }


class TestConsumidor(ComIndice):
    """O consumidor do `idx`: produto e estado do tenant, idempotente."""

    def setUp(self) -> None:
        super().setUp()
        conexao = self.ligar("app")
        conexao.autocommit = True
        self.bd = _Cliente(conexao)

    def documentos(self, tenant: str) -> list[tuple]:
        self.semente.execute(
            "SELECT product_ref, nome_norm, visivel FROM idx.search_doc "
            " WHERE tenant_id = %s ORDER BY product_ref",
            (tenant,),
        )
        return [tuple(linha) for linha in self.semente.fetchall()]

    def test_o_produto_publicado_entra_normalizado_e_visivel(self) -> None:
        tenant = self.tenant_em("ativo")
        self.criar_oferta(tenant, sku="geleira-1", nome="Frigorífico LG, 250 L")
        envelope = _envelope(tenant, "catalog.product_changed", {"sku": "geleira-1", "estado": "publicado"})
        self.assertEqual(consumidor.consumir_evento(self.bd, envelope).desfecho, "aplicado")
        self.assertEqual(self.documentos(tenant), [("geleira-1", "frigorifico lg 250 l", True)])

    def test_dez_duplicados_escrevem_uma_vez(self) -> None:
        """DoD: idempotencia, com o mesmo evento entregue dez vezes."""
        tenant = self.tenant_em("ativo")
        self.criar_oferta(tenant, sku="arroz")
        envelope = _envelope(tenant, "catalog.product_changed", {"sku": "arroz", "estado": "publicado"})
        desfechos = [consumidor.consumir_evento(self.bd, envelope).desfecho for _ in range(10)]
        self.assertEqual(desfechos, ["aplicado"] + ["duplicado"] * 9)
        self.semente.execute(
            "SELECT count(*), max(atualizado_at) = min(atualizado_at) "
            "  FROM idx.search_doc WHERE tenant_id = %s",
            (tenant,),
        )
        self.assertEqual(tuple(self.semente.fetchone()), (1, True))

    def test_o_efeito_le_o_estado_presente_e_nao_o_payload(self) -> None:
        """Um evento atrasado escreve o estado de agora, e a ordem nao importa."""
        tenant = self.tenant_em("ativo")
        self.criar_oferta(tenant, sku="arroz", estado="pausado")
        # O `payload` diz `publicado`, a oferta diz `pausado`: ganha a oferta.
        envelope = _envelope(tenant, "catalog.product_changed", {"sku": "arroz", "estado": "publicado"})
        consumidor.consumir_evento(self.bd, envelope)
        self.assertEqual(self.documentos(tenant), [("arroz", "produto arroz", False)])

    def test_cada_forma_de_nao_ser_publicavel_fica_invisivel(self) -> None:
        """A omissao `rascunho` incluida (licao do KAM-051)."""
        casos = {
            "rascunho": {"estado": "rascunho"},
            "pausado": {"estado": "pausado"},
            "arquivado": {"estado": "arquivado"},
            "restrito": {"categoria_restrita": "farmacia"},
        }
        tenant = self.tenant_em("ativo")
        for nome, campos in casos.items():
            with self.subTest(caso=nome):
                self.criar_oferta(tenant, sku=nome, **campos)
                consumidor.consumir_evento(
                    self.bd, _envelope(tenant, "catalog.product_changed", {"sku": nome, "estado": "rascunho"})
                )
        # Os quatro documentos existem **e** estao invisiveis: um conjunto de
        # booleanos sozinho ficava `{False}` tambem com zero documentos.
        self.assertEqual(
            [(linha[0], linha[2]) for linha in self.documentos(tenant)],
            [(nome, False) for nome in sorted(casos)],
        )

    def test_a_oferta_que_desaparece_esconde_o_documento(self) -> None:
        tenant = self.tenant_em("ativo")
        self.criar_oferta(tenant, sku="arroz")
        consumidor.consumir_evento(
            self.bd, _envelope(tenant, "catalog.product_changed", {"sku": "arroz", "estado": "publicado"})
        )
        self.semente.execute("DELETE FROM platform.offer_terms WHERE tenant_id = %s", (tenant,))
        consumidor.consumir_evento(
            self.bd, _envelope(tenant, "catalog.product_changed", {"sku": "arroz", "estado": "arquivado"})
        )
        self.assertEqual(self.documentos(tenant), [("arroz", "produto arroz", False)])

    def test_suspender_e_reactivar_o_tenant(self) -> None:
        """Criterio 9, a metade do efeito: `tenant.suspended` poe `visivel=false`."""
        tenant = self.tenant_em("ativo")
        self.criar_oferta(tenant, sku="arroz")
        self.criar_oferta(tenant, sku="feijao", estado="pausado")
        for sku in ("arroz", "feijao"):
            consumidor.consumir_evento(
                self.bd, _envelope(tenant, "catalog.product_changed", {"sku": sku, "estado": "publicado"})
            )
        self.semente.execute("UPDATE platform.tenants SET estado = 'suspenso' WHERE id = %s", (tenant,))
        consumidor.consumir_evento(self.bd, _envelope(tenant, "tenant.suspended", {"motivo": "ensaio"}))
        self.assertEqual([linha[2] for linha in self.documentos(tenant)], [False, False])
        self.semente.execute("UPDATE platform.tenants SET estado = 'ativo' WHERE id = %s", (tenant,))
        consumidor.consumir_evento(self.bd, _envelope(tenant, "tenant.reactivated", {}))
        # Volta so o publicado: a reactivacao nao publica o que estava pausado.
        self.assertEqual([linha[2] for linha in self.documentos(tenant)], [True, False])

    def test_o_produto_de_um_tenant_suspenso_entra_invisivel(self) -> None:
        tenant = self.tenant_em("suspenso")
        self.criar_oferta(tenant, sku="arroz")
        consumidor.consumir_evento(
            self.bd, _envelope(tenant, "catalog.product_changed", {"sku": "arroz", "estado": "publicado"})
        )
        self.assertEqual(self.documentos(tenant), [("arroz", "produto arroz", False)])

    def test_o_evento_escreve_so_no_tenant_do_envelope(self) -> None:
        """O mesmo `sku` em dois tenants: o evento de A nao toca no de B."""
        ta, tb = self.tenant_em("ativo"), self.tenant_em("ativo")
        self.criar_oferta(ta, sku=SKU_PARTILHADO, nome="Arroz A")
        self.criar_oferta(tb, sku=SKU_PARTILHADO, nome="Arroz B")
        consumidor.consumir_evento(
            self.bd, _envelope(ta, "catalog.product_changed", {"sku": SKU_PARTILHADO, "estado": "publicado"})
        )
        self.assertEqual(self.documentos(ta), [(SKU_PARTILHADO, "arroz a", True)])
        self.assertEqual(self.documentos(tb), [])


class TestResposta(ComIndice):
    """Criterio 8: a camada de resposta, pela funcao que a aplicacao chama."""

    def setUp(self) -> None:
        super().setUp()
        self.conexao = self.ligar("app")
        cliente = self.ligar("app")
        cliente.autocommit = True
        self.bd = _Cliente(cliente)

    def indexar(self, tenant: str, sku: str) -> None:
        consumidor.consumir_evento(
            self.bd, _envelope(tenant, "catalog.product_changed", {"sku": sku, "estado": "publicado"})
        )

    def test_o_contrato_e_o_da_secao_6_3_lido_do_documento(self) -> None:
        texto = DOC_INDICE.read_text(encoding="utf-8")
        achado = re.search(r"Contrato de sa[ií]da da tool:\s*`\[\{([^}]*)\}", texto)
        self.assertIsNotNone(achado)
        assert achado is not None
        campos = tuple(c.strip().split(":")[0].split(" ")[0] for c in achado.group(1).split(","))
        self.assertEqual(campos, pesquisa.CAMPOS_DO_CONTRATO)
        tenant = self.tenant_em("ativo")
        self.criar_oferta(tenant, sku="arroz", nome="Arroz agulha 5 kg")
        self.indexar(tenant, "arroz")
        linhas = pesquisa.pesquisar(self.conexao, tenant, "arroz")
        self.assertEqual(len(linhas), 1)
        self.assertEqual(tuple(linhas[0]), pesquisa.CAMPOS_DO_CONTRATO)
        self.assertEqual(linhas[0]["sku"], "arroz")
        self.assertEqual(linhas[0]["preco_minor"], PRECO)
        self.assertEqual(linhas[0]["fonte"], "registo")
        self.assertIsNone(linhas[0]["disponivel"], "sem nivel de stock: desconhecido")

    def test_so_sai_o_publicado(self) -> None:
        tenant = self.tenant_em("ativo")
        self.criar_oferta(tenant, sku="arroz", nome="Arroz agulha")
        self.criar_oferta(tenant, sku="arroz-2", nome="Arroz carolino")
        self.indexar(tenant, "arroz")
        self.indexar(tenant, "arroz-2")
        # Despublicado **depois** de indexado, e sem evento: o indice ainda o
        # tem visivel, e e a oferta viva que o tira.
        self.semente.execute(
            "UPDATE platform.offer_terms SET estado = 'pausado' WHERE tenant_id = %s AND sku = 'arroz-2'",
            (tenant,),
        )
        self.assertEqual([l["sku"] for l in pesquisa.pesquisar(self.conexao, tenant, "arroz")], ["arroz"])

    def test_o_filtro_de_preco_e_na_oferta_viva_e_nunca_no_indice(self) -> None:
        """O preco muda depois de indexado, sem evento: o filtro ve o de agora."""
        tenant = self.tenant_em("ativo")
        self.criar_oferta(tenant, sku="arroz", nome="Arroz agulha", preco_minor=PRECO)
        self.indexar(tenant, "arroz")
        self.assertEqual(len(pesquisa.pesquisar(self.conexao, tenant, "arroz", max_preco_minor=PRECO)), 1)
        self.semente.execute(
            "UPDATE platform.offer_terms SET preco_minor = %s WHERE tenant_id = %s AND sku = 'arroz'",
            (PRECO + 1, tenant),
        )
        self.assertEqual(pesquisa.pesquisar(self.conexao, tenant, "arroz", max_preco_minor=PRECO), ())
        linhas = pesquisa.pesquisar(self.conexao, tenant, "arroz")
        self.assertEqual([l["preco_minor"] for l in linhas], [PRECO + 1])

    def test_o_tenant_vem_do_contexto_e_nao_de_um_parametro(self) -> None:
        """O isolamento da camada: o mesmo `sku` e nome em B, com outro preco.

        A consulta nao tem parametro de tenant. Chamada com A, devolve a linha
        de A com o preco de A; chamada com B, a de B — e em nenhuma das duas a
        do outro, apesar de o `product_ref` ser o mesmo nas duas.
        """
        ta, tb = self.tenant_em("ativo"), self.tenant_em("ativo")
        self.criar_oferta(ta, sku=SKU_PARTILHADO, nome="Arroz 5 kg", preco_minor=PRECO)
        self.criar_oferta(tb, sku=SKU_PARTILHADO, nome="Arroz 5 kg", preco_minor=PRECO * 2)
        self.indexar(ta, SKU_PARTILHADO)
        self.indexar(tb, SKU_PARTILHADO)
        self.assertEqual([l["preco_minor"] for l in pesquisa.pesquisar(self.conexao, ta, "arroz")], [PRECO])
        self.assertEqual([l["preco_minor"] for l in pesquisa.pesquisar(self.conexao, tb, "arroz")], [PRECO * 2])
        self.assertNotIn("%s::uuid", pesquisa.SQL_RESPOSTA)

    def test_tenant_suspenso_responde_vazio_mesmo_com_o_indice_por_actualizar(self) -> None:
        """Criterio 9, a segunda defesa: o consumidor atrasou, a porta `tn` nao."""
        tenant = self.tenant_em("ativo")
        self.criar_oferta(tenant, sku="arroz", nome="Arroz agulha")
        self.indexar(tenant, "arroz")
        self.semente.execute("UPDATE platform.tenants SET estado = 'suspenso' WHERE id = %s", (tenant,))
        self.assertEqual(pesquisa.pesquisar(self.conexao, tenant, "arroz"), ())

    def test_no_maximo_tres_e_pela_ordem_do_indice(self) -> None:
        tenant = self.tenant_em("ativo")
        for i in range(5):
            self.criar_oferta(tenant, sku=f"arroz-{i}", nome=f"Arroz {i}")
            self.indexar(tenant, f"arroz-{i}")
        self.assertEqual(len(pesquisa.pesquisar(self.conexao, tenant, "arroz")), 3)


def _agr():
    """O executor e o `retrieve` do AGR, importados do servico (KAM-061)."""
    caminho = str(_RAIZ / "services" / "agr" / "src")
    if caminho not in sys.path:
        sys.path.insert(0, caminho)
    import importlib

    return SimpleNamespace(
        idx=importlib.import_module("kamba_agr.tls.idx"),
        nos=importlib.import_module("kamba_agr.verticais.vendedor.nos"),
        esp=importlib.import_module("kamba_agr.tls.especificacoes"),
        erros=importlib.import_module("kamba_agr.tls.erros"),
        vendedor=importlib.import_module("kamba_agr.tls.vendedor"),
        grafos=importlib.import_module("kamba_agr.grafos"),
    )


class _CamadaDoIndice:
    """Uma ToolLayer reduzida ao passo 6: o executor real, com a tomada real.

    Os passos 1 a 5 (allowlist, entitlement, validacao, auditoria) sao do
    KAM-028 e tem bateria propria; o que este ensaio mede e o par
    (pontuador, limiar) **ligado**, e por isso o executor corre com a ligacao de
    `kamba_app` e o contexto que o grafo constroi do estado.
    """

    def __init__(self, agr, conexao) -> None:
        self.agr = agr
        self.conexao = conexao
        self.contextos: list[object] = []

    async def invoke(self, ctx, nome, argumentos, **_):
        assert nome == "search_catalog", nome
        self.contextos.append(ctx)
        pedido = self.agr.esp.Pedido(
            ctx=ctx,
            args=self.agr.vendedor.ArgumentosDeSearchCatalog(**argumentos),
            timeout_ms=2_000,
            ligacao=self.conexao,
        )
        resposta = self.agr.idx.executar(pedido)
        return self.agr.erros.ToolResult(ok=True, data=resposta.data, facts=resposta.facts)


class TestLigacaoDoAgr(ComIndice):
    """O `search_catalog` ligado: o `retrieve` do grafo sobre o indice real.

    O defeito que isto mata e o da **escala**: o `LIMIAR_IDX = 0.5` do grafo e o
    limiar do pontuador do duplo, e o RRF tem maximo de cerca de 0,016. Ligar o
    indice sem normalizar mandava toda a pesquisa para o `unknown_reply`.
    """

    def setUp(self) -> None:
        super().setUp()
        self.agr = _agr()
        cliente = self.ligar("app")
        cliente.autocommit = True
        self.bd = _Cliente(cliente)
        self.tenant = self.tenant_em("ativo")
        self.criar_oferta(self.tenant, sku="arroz", nome="Arroz agulha 5 kg")
        consumidor.consumir_evento(
            self.bd,
            _envelope(self.tenant, "catalog.product_changed", {"sku": "arroz", "estado": "publicado"}),
        )

    def retrieve(self, texto: str, limiar: float) -> tuple:
        camada = _CamadaDoIndice(self.agr, self.ligar("app"))
        deps = self.agr.nos.Dependencias(
            tools=camada, saida=self.agr.grafos.SaidaPorLigar(), limiar_idx=limiar
        )
        estado = {
            "tenant_id": self.tenant,
            "channel_id": str(uuid.uuid4()),
            "contact_id": str(uuid.uuid4()),
            "conversation_id": str(uuid.uuid4()),
            "thread_id": str(uuid.uuid4()),
            "turn_id": str(uuid.uuid4()),
            "vertical": "vendedor",
            "messages": [{"role": "user", "content": texto}],
        }
        delta = asyncio.run(self.agr.nos.retrieve(deps)(estado))
        self.assertEqual([c.tenant_id for c in camada.contextos], [self.tenant])
        return tuple(delta.get("ofertas") or ())

    def test_a_frase_tipica_passa_o_limiar_e_nao_cai_no_unknown_reply(self) -> None:
        """«quero comprar arroz»: o trigrama da frase nao bate, o `fts` sim (0,4)."""
        ofertas = self.retrieve("quero comprar arroz", self.agr.idx.LIMIAR_DO_RRF)
        self.assertEqual(
            ofertas, ({"sku": "arroz", "nome": "Arroz agulha 5 kg", "preco_tipo": "fixo"},)
        )

    def test_o_nome_do_produto_vale_um_e_a_frase_vale_o_fts(self) -> None:
        """A escala, medida no executor: 1,0 nos dois ramos, 0,4 so no `fts`."""
        def score(texto: str) -> list[float]:
            pedido = SimpleNamespace(
                ctx=SimpleNamespace(tenant_id=self.tenant),
                args=self.agr.vendedor.ArgumentosDeSearchCatalog(query=texto),
                timeout_ms=2_000,
                ligacao=self.ligar("app"),
            )
            return [c["score"] for c in self.agr.idx.executar(pedido).data["candidatos"]]

        self.assertEqual(score("arroz agulha"), [1.0])
        self.assertEqual(score("quero comprar arroz"), [0.4])

    def test_o_nao_resolvivel_cai(self) -> None:
        """Sem sobreposicao lexical nenhuma, a resposta e vazia.

        **Nao e o limiar que o decide**: no modo lexical, todo o candidato que o
        indice devolve no topo passa os 0,3 (`tls/idx.py`). «Nao resolvivel» e
        a resposta vazia, e este caso ficava verde com o limiar a zero — esta
        aqui pelo comportamento, nao como prova do par (achado 3 da revisao).
        """
        self.assertEqual(self.retrieve("tem bicicletas de montanha?", self.agr.idx.LIMIAR_DO_RRF), ())

    def test_um_numero_da_pergunta_nao_encontra_o_produto_errado(self) -> None:
        """«quero 2 bicicletas» contra «Arroz 2 kg»: o `2` nao e termo do indice.

        Medido antes da correccao: o `portuguese` guarda o `2` como lexema, o
        `fts` casava pelo `or`, o score dava 0,4 e o `cart_build` propunha o
        arroz. O numero e restricao (§5.1, passo 3) e sai da expansao.
        """
        self.criar_oferta(self.tenant, sku="arroz-2kg", nome="Arroz 2 kg")
        consumidor.consumir_evento(
            self.bd,
            _envelope(self.tenant, "catalog.product_changed", {"sku": "arroz-2kg", "estado": "publicado"}),
        )
        self.assertEqual(self.retrieve("quero 2 bicicletas", self.agr.idx.LIMIAR_DO_RRF), ())

    def test_com_o_limiar_do_duplo_a_frase_tipica_caia(self) -> None:
        """O defeito da escala, fixado: o limiar do duplo contra o RRF normalizado.

        Nao e o comportamento que se quer — e o que acontecia se o `__main__`
        nao passasse o `LIMIAR_DO_RRF`. O `test_grafos` mede que passa.
        """
        self.assertEqual(self.retrieve("quero comprar arroz", self.agr.nos.LIMIAR_IDX), ())

    def test_outro_tenant_com_o_mesmo_produto_nao_entra(self) -> None:
        outro = self.tenant_em("ativo")
        self.criar_oferta(outro, sku="arroz-b", nome="Arroz agulha 5 kg")
        consumidor.consumir_evento(
            self.bd,
            _envelope(outro, "catalog.product_changed", {"sku": "arroz-b", "estado": "publicado"}),
        )
        skus = [o["sku"] for o in self.retrieve("arroz agulha", self.agr.idx.LIMIAR_DO_RRF)]
        self.assertEqual(skus, ["arroz"])


# --------------------------------------------------------------- KAM-063


def _por_palavras(texto: str) -> tuple[float, ...]:
    """Um vector deterministico: um eixo por palavra normalizada.

    Nao e um modelo, e nao pretende ser: e o bastante para que a pergunta
    «frigorifico» fique mais perto do documento que tem essa palavra do que dos
    outros, e para que o ramo `sem` do `idx.candidatos` tenha um vencedor
    conhecido. Nunca e o vector nulo — o `<=>` de um vector nulo e `NaN`.
    """
    valores = [0.0] * DIMENSAO
    for palavra in texto_mod.normalizar(texto).split() or ["vazio"]:
        valores[zlib.crc32(palavra.encode()) % DIMENSAO] += 1.0
    return tuple(valores)


class _FornecedorDeEnsaio:
    """O `FakeEmbeddingProvider` do bloco: conta chamadas e guarda os textos."""

    fornecedores = ("fornecedor_de_teste",)

    def __init__(self, modelo: str = "modelo-de-ensaio", durante=None) -> None:
        self.modelo = modelo
        self.durante = durante
        self.chamadas: list[tuple[str, ...]] = []

    def __call__(self, tenant_id: str, textos, tecto_s: float) -> embeddings.Vectores:
        self.chamadas.append(tuple(textos))
        if self.durante is not None:
            self.durante()
        return embeddings.Vectores(self.modelo, tuple(_por_palavras(t) for t in textos))


class _Porta:
    """Uma porta que autoriza ou nega tudo. A real, sobre a base, e a do caso
    `test_sem_destino_na_base_zero_chamadas` — e o caso que o criterio nomeia."""

    def __init__(self, autoriza: bool = True) -> None:
        self.autoriza = autoriza

    def autorizar(self, tenant_id: str, fornecedor: str, finalidade: str) -> None:
        if not self.autoriza:
            raise RuntimeError("destino nao autorizado (ensaio)")


class TestEmbeddings(ComIndice):
    """KAM-063 contra um PostgreSQL: o *worker*, o reembedding e o modo hibrido.

    A porta de destinos e a do KAM-069 nos ensaios unitarios
    (`libs/py-core/tests/test_idx_embeddings.py`); aqui a pergunta e o SQL — o
    que o vector anula, o que a escrita confere e o que a pesquisa usa.
    """

    def setUp(self) -> None:
        super().setUp()
        cliente = self.ligar("app")
        cliente.autocommit = True
        self.bd = _Cliente(cliente)
        self.registo = metricas_mod.MetricasDoIdx()
        self.tenant = self.tenant_em("ativo")

    def no_tenant(self, tenant: str | None = None) -> None:
        """O contexto da sessao, como o processo do *worker* o poe."""
        self.bd.executar(
            "SELECT set_config('app.tenant_id', %s, false)", (tenant or self.tenant,)
        )

    def indexar(self, sku: str, tenant: str | None = None) -> None:
        consumidor.consumir_evento(
            self.bd,
            _envelope(tenant or self.tenant, "catalog.product_changed",
                      {"sku": sku, "estado": "publicado"}),
        )

    def cliente(self, fornecedor: _FornecedorDeEnsaio, porta=None) -> embeddings.ClienteDeEmbeddings:
        return embeddings.ClienteDeEmbeddings(
            porta or _Porta(), fornecedor, metricas=self.registo
        )

    def embeber(self, fornecedor: _FornecedorDeEnsaio, porta=None) -> embeddings.VoltaDoCatalogo:
        self.no_tenant()
        return embeddings.embeber_catalogo(
            self.bd, self.tenant, self.cliente(fornecedor, porta), fornecedor.modelo
        )

    def vectores(self, tenant: str | None = None) -> dict[str, tuple[bool, str | None]]:
        self.semente.execute(
            "SELECT product_ref, embedding IS NOT NULL, embedding_modelo "
            "  FROM idx.search_doc WHERE tenant_id = %s ORDER BY product_ref",
            (tenant or self.tenant,),
        )
        return {linha[0]: (linha[1], linha[2]) for linha in self.semente.fetchall()}

    def test_o_worker_grava_o_vector_e_o_modelo_e_recusa_o_contacto(self) -> None:
        """Criterios 5 e 6: o texto passa o *lint*, e o modelo fica por linha."""
        self.criar_oferta(self.tenant, sku="geleira", nome="Frigorífico LG 250 L")
        self.criar_oferta(self.tenant, sku="bolo", nome="Bolo de anos, ligue 923 456 789")
        self.indexar("geleira")
        self.indexar("bolo")
        fornecedor = _FornecedorDeEnsaio()
        volta = self.embeber(fornecedor)
        self.assertEqual((volta.lidos, volta.gravados, volta.recusados, volta.motivo), (2, 1, 1, None))
        # O texto que saiu e o nome da oferta viva, com o acento e sem preco.
        self.assertEqual(fornecedor.chamadas, [("Frigorífico LG 250 L",)])
        self.assertEqual(
            self.vectores(),
            {"bolo": (False, None), "geleira": (True, "modelo-de-ensaio")},
        )
        # A volta seguinte, do cursor, ja nao tem nada; o recusado volta do
        # inicio, sem chamada: o *lint* e local.
        self.no_tenant()
        seguinte = embeddings.embeber_catalogo(
            self.bd, self.tenant, self.cliente(fornecedor), fornecedor.modelo,
            depois_de=volta.ultimo,
        )
        self.assertEqual(seguinte, embeddings.VoltaDoCatalogo(0, 0, 0, None))
        self.assertEqual(len(fornecedor.chamadas), 1)

    def test_o_preco_nao_reembebe_e_o_nome_sim(self) -> None:
        """Criterio 5: mudar o preco deixa o vector; mudar o nome anula-o."""
        self.criar_oferta(self.tenant, sku="arroz", nome="Arroz agulha 5 kg")
        self.indexar("arroz")
        self.embeber(_FornecedorDeEnsaio())
        self.assertEqual(self.vectores(), {"arroz": (True, "modelo-de-ensaio")})
        self.semente.execute(
            "UPDATE platform.offer_terms SET preco_minor = preco_minor + 10000 "
            " WHERE tenant_id = %s AND sku = 'arroz'",
            (self.tenant,),
        )
        self.indexar("arroz")
        self.assertEqual(self.vectores(), {"arroz": (True, "modelo-de-ensaio")})
        self.semente.execute(
            "UPDATE platform.offer_terms SET nome = 'Arroz carolino 5 kg' "
            " WHERE tenant_id = %s AND sku = 'arroz'",
            (self.tenant,),
        )
        self.indexar("arroz")
        self.assertEqual(self.vectores(), {"arroz": (False, None)})
        # E o *worker* volta a embebe-lo, com o nome novo.
        fornecedor = _FornecedorDeEnsaio()
        self.assertEqual(self.embeber(fornecedor).gravados, 1)
        self.assertEqual(fornecedor.chamadas, [("Arroz carolino 5 kg",)])

    def test_a_escrita_nao_grava_o_vector_de_um_nome_que_mudou(self) -> None:
        """A chamada fica entre a leitura e a escrita: o nome pode mudar no meio."""
        self.criar_oferta(self.tenant, sku="arroz", nome="Arroz agulha 5 kg")
        self.indexar("arroz")

        def renomear() -> None:
            self.semente.execute(
                "UPDATE platform.offer_terms SET nome = 'Feijao manteiga' "
                " WHERE tenant_id = %s AND sku = 'arroz'",
                (self.tenant,),
            )
            self.indexar("arroz")

        volta = self.embeber(_FornecedorDeEnsaio(durante=renomear))
        self.assertEqual((volta.lidos, volta.gravados), (1, 0))
        self.assertEqual(self.vectores(), {"arroz": (False, None)})

    def test_sem_destino_na_base_zero_chamadas(self) -> None:
        """Criterios 1 e 9: a porta real, sem linha em `tenant_destinations`."""
        self.criar_oferta(self.tenant, sku="arroz", nome="Arroz agulha 5 kg")
        self.indexar("arroz")
        porta = PortaSobreDestinos(destinos_dbapi.leitor(lambda: ligacao.ligar("app")))
        fornecedor = _FornecedorDeEnsaio()
        volta = self.embeber(fornecedor, porta)
        self.assertEqual(volta.motivo, "destino_negado")
        self.assertEqual(fornecedor.chamadas, [])
        self.assertEqual(self.vectores(), {"arroz": (False, None)})

    def test_nunca_dois_modelos_na_coluna_do_tenant(self) -> None:
        """Criterio 6, a metade sem DDL: o segundo modelo nao escreve nem chama."""
        self.criar_oferta(self.tenant, sku="arroz", nome="Arroz agulha 5 kg")
        self.indexar("arroz")
        self.embeber(_FornecedorDeEnsaio("modelo-a"))
        self.criar_oferta(self.tenant, sku="feijao", nome="Feijao manteiga 1 kg")
        self.indexar("feijao")
        outro = _FornecedorDeEnsaio("modelo-b")
        volta = self.embeber(outro)
        self.assertEqual(volta.motivo, "modelo_divergente")
        self.assertEqual(outro.chamadas, [])
        # E a instrucao de escrita recusa-o sozinha, sem a verificacao de antes.
        self.no_tenant()
        (linha,) = self.bd.executar(embeddings.SQL_POR_EMBEBER, (None, None, 10)).linhas
        parametros = [
            "modelo-b", linha["doc_id"], embeddings.em_texto(_por_palavras("x")),
            linha["nome_norm"], linha["marca_canon"], linha["categoria_canon"],
            linha["descr_norm"], "modelo-b",
        ]
        self.assertEqual(
            self.bd.executar(embeddings.sql_gravar_embeddings(1), parametros).contagem, 0
        )
        self.assertEqual(
            self.vectores(), {"arroz": (True, "modelo-a"), "feijao": (False, None)}
        )

    def test_a_pesquisa_hibrida_e_o_chao_lexical(self) -> None:
        """Criterio 1 na pesquisa: com destino, uma chamada e `hibrido`; sem ele,
        zero chamadas e o mesmo resultado do lexical."""
        for sku, nome in (("geleira", "Frigorífico LG 250 L"), ("arroz", "Arroz agulha 5 kg")):
            self.criar_oferta(self.tenant, sku=sku, nome=nome)
            self.indexar(sku)
        self.embeber(_FornecedorDeEnsaio())
        conexao = self.ligar("app")
        lexical = pesquisa.procurar(conexao, self.tenant, "frigorifico")
        self.assertEqual(lexical.modo, "lexical")

        fornecedor = _FornecedorDeEnsaio()
        vectorial = embeddings.ConsultaVectorial(
            self.cliente(fornecedor), lambda _t: False, metricas=self.registo
        )
        hibrida = pesquisa.procurar(conexao, self.tenant, "frigorifico", vectorial=vectorial)
        self.assertEqual(hibrida.modo, "hibrido")
        self.assertEqual(fornecedor.chamadas, [("frigorifico",)])
        self.assertEqual(hibrida.linhas[0][0]["sku"], "geleira")

        negada = embeddings.ConsultaVectorial(
            self.cliente(fornecedor, _Porta(autoriza=False)), lambda _t: False,
            metricas=self.registo,
        )
        caida = pesquisa.procurar(conexao, self.tenant, "frigorifico", vectorial=negada)
        self.assertEqual(caida.modo, "lexical")
        self.assertEqual(len(fornecedor.chamadas), 1)
        # O mesmo resultado do lexical, linha a linha e com o mesmo `o_score`;
        # so o `lido_em` muda, porque e o instante da leitura.
        def sem_instante(procura):
            return [({**l, "lido_em": None}, s) for l, s in procura.linhas]

        self.assertEqual(sem_instante(caida), sem_instante(lexical))
        self.assertEqual(
            self.registo.ler()["embedding_fallback_total:destino_negado"], 1
        )

    def test_dois_modelos_no_indice_sao_lexical_sem_chamada(self) -> None:
        for sku, nome in (("geleira", "Frigorífico LG 250 L"), ("arroz", "Arroz agulha 5 kg")):
            self.criar_oferta(self.tenant, sku=sku, nome=nome)
            self.indexar(sku)
        self.embeber(_FornecedorDeEnsaio())
        self.semente.execute(
            "UPDATE idx.search_doc SET embedding_modelo = 'outro' "
            " WHERE tenant_id = %s AND product_ref = 'arroz'",
            (self.tenant,),
        )
        fornecedor = _FornecedorDeEnsaio()
        vectorial = embeddings.ConsultaVectorial(
            self.cliente(fornecedor), lambda _t: False, metricas=self.registo
        )
        procura = pesquisa.procurar(self.ligar("app"), self.tenant, "frigorifico",
                                    vectorial=vectorial)
        self.assertEqual(procura.modo, "lexical")
        self.assertEqual(fornecedor.chamadas, [])
        self.assertEqual(
            self.registo.ler()["embedding_fallback_total:modelo_divergente"], 1
        )

    def test_o_executor_do_agr_sem_destino_responde_lexical_e_conta(self) -> None:
        """Criterio 1 de ponta a ponta: a *tool* do AGR, a porta real sobre a
        base (sem linha em `tenant_destinations`), zero chamadas, resposta em
        lexical e `idx_mode{lexical}` mais um."""
        for sku, nome in (("geleira", "Frigorífico LG 250 L"), ("arroz", "Arroz agulha 5 kg")):
            self.criar_oferta(self.tenant, sku=sku, nome=nome)
            self.indexar(sku)
        self.embeber(_FornecedorDeEnsaio())  # o indice tem vectores: ha com que ir
        agr = _agr()
        fornecedor = _FornecedorDeEnsaio()
        porta = PortaSobreDestinos(destinos_dbapi.leitor(lambda: ligacao.ligar("app")))
        ligacao_vectorial = agr.idx.LigacaoVectorial()
        ligacao_vectorial.ligar(
            embeddings.ConsultaVectorial(
                self.cliente(fornecedor, porta), lambda _t: False, metricas=self.registo
            )
        )
        global_ = metricas_mod.METRICAS
        global_.repor()
        self.addCleanup(global_.repor)
        pedido = agr.esp.Pedido(
            ctx=SimpleNamespace(tenant_id=self.tenant),
            args=agr.vendedor.ArgumentosDeSearchCatalog(query="frigorifico", filtros={}),
            timeout_ms=2_000,
            ligacao=self.ligar("app"),
        )
        resposta = agr.idx.executar(pedido, ligacao_vectorial)
        self.assertEqual(fornecedor.chamadas, [])
        self.assertEqual([c["sku"] for c in resposta.data["candidatos"]], ["geleira"])
        self.assertEqual(global_.ler().get("idx_mode:lexical"), 1)
        self.assertNotIn("idx_mode:hibrido", global_.ler())
        self.assertEqual(self.registo.ler()["embedding_fallback_total:destino_negado"], 1)

    def test_tenant_sem_vectores_nao_chama_o_fornecedor(self) -> None:
        self.criar_oferta(self.tenant, sku="arroz", nome="Arroz agulha 5 kg")
        self.indexar("arroz")
        fornecedor = _FornecedorDeEnsaio()
        vectorial = embeddings.ConsultaVectorial(
            self.cliente(fornecedor), lambda _t: False, metricas=self.registo
        )
        procura = pesquisa.procurar(self.ligar("app"), self.tenant, "arroz", vectorial=vectorial)
        self.assertEqual(procura.modo, "lexical")
        self.assertEqual(fornecedor.chamadas, [])
        self.assertEqual([l["sku"] for l, _ in procura.linhas], ["arroz"])

    def test_os_vectores_de_outro_tenant_nao_contam(self) -> None:
        """O modelo do indice le-se com o contexto do tenant, e so dele."""
        outro = self.tenant_em("ativo")
        self.criar_oferta(outro, sku="arroz", nome="Arroz agulha 5 kg")
        self.indexar("arroz", outro)
        self.no_tenant(outro)
        fornecedor = _FornecedorDeEnsaio()
        embeddings.embeber_catalogo(
            self.bd, outro, self.cliente(fornecedor), fornecedor.modelo
        )
        self.assertEqual(self.vectores(outro), {"arroz": (True, "modelo-de-ensaio")})
        self.criar_oferta(self.tenant, sku="arroz", nome="Arroz agulha 5 kg")
        self.indexar("arroz")
        vectorial = embeddings.ConsultaVectorial(
            self.cliente(fornecedor), lambda _t: False, metricas=self.registo
        )
        procura = pesquisa.procurar(self.ligar("app"), self.tenant, "arroz", vectorial=vectorial)
        self.assertEqual(procura.modo, "lexical")
        self.assertEqual(len(fornecedor.chamadas), 1)


if __name__ == "__main__":
    unittest.main()
