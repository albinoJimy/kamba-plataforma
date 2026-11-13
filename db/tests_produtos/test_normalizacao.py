"""A normalizacao PT-AO contra um PostgreSQL real (KAM-062, revisao `0049`).

O que a suite unitaria (`libs/py-core/tests/test_idx_normalizacao.py`) nao pode
medir, porque precisa da base:

* **criterio 4** — a versao do `idx.norm_versao` sobe com qualquer alteracao do
  lexico, e so a de marca ou unidade marca documentos; o *worker* reindexa-os, e
  2 000 produtos cabem em 10 min;
* **criterio 5** — o vocabulario do tenant, e o «>= 1 candidato apos correccao»:
  a palavra corrigida encontra o produto pelo `idx.candidatos`; e a semelhanca
  de `semelhanca()` e a do `pg_trgm`;
* **criterio 6** — o termo do tenant prevalece, e um termo de B nunca chega ao
  lexico de A — pela RLS, lido como `kamba_app` com o contexto de A;
* **criterio 7** — `aprovado_por` obrigatorio, e nenhuma entrada de *dataset*
  activa.

O lexico destes ensaios e o **ilustrativo** do §5.1 (NAO VERIFICADO), e so
existe durante cada ensaio.
"""

from __future__ import annotations

import sys
import time
import uuid
from pathlib import Path

from tests_produtos.test_indice import ComIndice, _Cliente, _envelope

_RAIZ = Path(__file__).resolve().parents[2]
if str(_RAIZ / "libs" / "py-core" / "src") not in sys.path:
    sys.path.insert(0, str(_RAIZ / "libs" / "py-core" / "src"))

from kamba_core.idx import consumidor, lexico, normalizacao, pesquisa  # noqa: E402

#: O alvo do criterio 4: um tenant de 2 000 produtos reindexado em <= 10 min.
PRODUTOS_DO_ALVO = 2_000
ALVO_DE_REINDEXACAO_S = 600.0


class ComLexico(ComIndice):
    """Termos semeados pelo administrador, apagados no fim de cada ensaio."""

    def setUp(self) -> None:
        super().setUp()
        self._termos: list[int] = []
        self.addCleanup(self._apagar_termos)
        cliente = self.ligar("app")
        cliente.autocommit = True
        self.bd = _Cliente(cliente)

    def _apagar_termos(self) -> None:
        for termo_id in self._termos:
            self.semente.execute("DELETE FROM idx.termo_canonico WHERE id = %s", (termo_id,))

    def termo(
        self,
        tipo: str,
        termo: str,
        canonico: str,
        *,
        tenant: str | None = None,
        origem: str = "ops",
    ) -> int:
        self.semente.execute(
            "INSERT INTO idx.termo_canonico "
            "(tenant_id, tipo, termo, canonico, origem, aprovado_por) "
            "VALUES (%s, %s, %s, %s, %s, 'ensaio-kam-062') RETURNING id",
            (tenant, tipo, termo, canonico, origem),
        )
        termo_id = int(self.semente.fetchone()[0])
        self._termos.append(termo_id)
        return termo_id

    def versoes(self) -> lexico.Versoes:
        cursor = self.cursor_app(None)
        versoes = lexico.ler_versoes(cursor)
        self.desfazer(None)
        return versoes

    def indexar(self, tenant: str, sku: str) -> None:
        consumidor.consumir_evento(
            self.bd,
            _envelope(tenant, "catalog.product_changed", {"sku": sku, "estado": "publicado"}),
        )

    def documento_de(self, tenant: str, sku: str) -> tuple:
        self.semente.execute(
            "SELECT nome_norm, marca_canon, norm_versao FROM idx.search_doc "
            " WHERE tenant_id = %s AND product_ref = %s",
            (tenant, sku),
        )
        return tuple(self.semente.fetchone())

    def reindexar(self, tenant: str, lote: int = consumidor.LOTE_DE_REINDEXACAO) -> int:
        """Uma volta do *worker*, numa transaccao com o contexto do tenant."""
        self.bd.executar("BEGIN")
        try:
            self.bd.executar("SELECT set_config('app.tenant_id', %s, true)", (tenant,))
            escritos = consumidor.reindexar(self.bd, tenant, lote)
            self.bd.executar("COMMIT")
        except BaseException:
            self.bd.executar("ROLLBACK")
            raise
        return escritos


class TestVersao(ComLexico):
    """Criterio 4: o que sobe a versao e o que marca documentos."""

    def test_sinonimo_sobe_a_versao_e_nao_marca_documentos(self) -> None:
        antes = self.versoes()
        self.termo("sinonimo", f"geleira{uuid.uuid4().hex[:6]}", "frigorifico")
        depois = self.versoes()
        self.assertGreater(depois.versao, antes.versao)
        self.assertEqual(depois.versao_do_indice, antes.versao_do_indice)

    def test_marca_sobe_as_duas(self) -> None:
        antes = self.versoes()
        self.termo("marca", f"ifone{uuid.uuid4().hex[:6]}", "iphone")
        depois = self.versoes()
        self.assertGreater(depois.versao_do_indice, antes.versao_do_indice)
        self.assertEqual(depois.versao, depois.versao_do_indice)

    def test_desactivar_e_apagar_uma_unidade_activa_marcam(self) -> None:
        termo_id = self.termo("unidade", f"litr{uuid.uuid4().hex[:6]}", "l")
        antes = self.versoes()
        self.semente.execute(
            "UPDATE idx.termo_canonico SET activo = false WHERE id = %s", (termo_id,)
        )
        self.assertGreater(self.versoes().versao_do_indice, antes.versao_do_indice)
        outro = self.termo("unidade", f"gig{uuid.uuid4().hex[:6]}", "gb")
        meio = self.versoes()
        self.semente.execute("DELETE FROM idx.termo_canonico WHERE id = %s", (outro,))
        self.assertGreater(self.versoes().versao_do_indice, meio.versao_do_indice)

    def test_uma_entrada_inactiva_nao_marca_o_indice(self) -> None:
        """Achado 14: uma marca inactiva (a de *dataset*) nao escreve no `nome_norm`.

        Sobe a versao — o lexico mudou —, e a do indice fica: inserir, apagar.
        """
        antes = self.versoes()
        self.semente.execute(
            "INSERT INTO idx.termo_canonico "
            "(tenant_id, tipo, termo, canonico, origem, activo, aprovado_por) "
            "VALUES (NULL, 'marca', %s, 'nike', 'dataset', false, 'ensaio') RETURNING id",
            (f"naik{uuid.uuid4().hex[:6]}",),
        )
        termo_id = int(self.semente.fetchone()[0])
        self.semente.execute("DELETE FROM idx.termo_canonico WHERE id = %s", (termo_id,))
        depois = self.versoes()
        self.assertGreater(depois.versao, antes.versao)
        self.assertEqual(depois.versao_do_indice, antes.versao_do_indice)

    def test_a_versao_so_se_acrescenta(self) -> None:
        """Nem o dono reescreve nem apaga uma versao: o maximo nunca desce."""
        self.termo("sinonimo", f"bina{uuid.uuid4().hex[:6]}", "bicicleta")
        admin = self.ligar("admin").cursor()
        for instrucao in (
            "UPDATE idx.norm_versao SET afecta_indice = NOT afecta_indice",
            "DELETE FROM idx.norm_versao",
        ):
            with self.subTest(instrucao=instrucao):
                self.assertErroSql("P0001", admin, instrucao)

    def test_o_kamba_app_le_a_versao_e_nao_a_escreve(self) -> None:
        cursor = self.cursor_app(None)
        self.assertErroSql(
            "42501", cursor, "INSERT INTO idx.norm_versao (afecta_indice) VALUES (true)"
        )
        self.desfazer(None)


class TestReindexacao(ComLexico):
    """Criterio 4: o *worker* reescreve so os marcados, e cabe no alvo."""

    def test_sinonimo_nao_reindexa_e_marca_reindexa(self) -> None:
        tenant = self.tenant_em("ativo")
        self.criar_oferta(tenant, sku="tel", nome="I Phone 13 128 GB")
        self.indexar(tenant, "tel")
        self.assertEqual(self.documento_de(tenant, "tel")[:2], ("i phone 13 128 gb", None))
        # Um sinonimo: a versao sobe, o documento nao fica marcado.
        self.termo("sinonimo", "celular", "telemovel")
        self.assertEqual(self.reindexar(tenant), 0)
        # Uma marca: o documento fica marcado, e o *worker* reescreve-o.
        self.termo("marca", "i phone", "iphone")
        self.assertEqual(self.reindexar(tenant), 1)
        nome, marca, versao = self.documento_de(tenant, "tel")
        self.assertEqual((nome, marca), ("iphone 13 128 gb", "iphone"))
        self.assertEqual(versao, self.versoes().versao)
        self.assertEqual(self.reindexar(tenant), 0, "em dia depois de uma volta")

    def test_a_marca_de_b_nao_reescreve_o_documento_de_a(self) -> None:
        a, b = self.tenant_em("ativo"), self.tenant_em("ativo")
        self.criar_oferta(a, sku="t", nome="Naiki Air")
        self.criar_oferta(b, sku="t", nome="Naiki Air")
        self.indexar(a, "t")
        self.indexar(b, "t")
        self.termo("marca", "naiki", "nike", tenant=b)
        self.reindexar(a)
        self.reindexar(b)
        self.assertEqual(self.documento_de(a, "t")[:2], ("naiki air", None))
        self.assertEqual(self.documento_de(b, "t")[:2], ("nike air", "nike"))

    def test_um_invisivel_desactualizado_nao_e_marcado_e_a_volta_acaba(self) -> None:
        """O `AND visivel` do `SQL_DESACTUALIZADOS` (achado 8 da revisao).

        Um documento escondido cuja oferta desapareceu nao sobe de versao (o
        `SQL_ESCONDER_DOCUMENTO` nao a toca). Sem o filtro, era marcado em todas
        as voltas e o ciclo «ate dar zero» nao acabava.
        """
        tenant = self.tenant_em("ativo")
        self.documento(tenant, "fantasma", "geleira velha", visivel=False)
        self.termo("unidade", f"lt{uuid.uuid4().hex[:6]}", "l")
        self.assertEqual(self.reindexar(tenant), 0)

    def test_2000_produtos_em_menos_de_10_minutos(self) -> None:
        """O alvo do criterio 4, medido aqui: a medicao e da maquina do *gate*."""
        tenant = self.tenant_em("ativo")
        self.semente.execute(
            "INSERT INTO platform.offer_terms "
            "(tenant_id, sku, nome, preco_tipo, preco_minor, stock_modo, estado) "
            "SELECT %s, 'p' || g, 'Geleira ' || g || ' litros', 'fixo', 100, 'garantido', "
            "       'publicado' FROM generate_series(1, %s) g",
            (tenant, PRODUTOS_DO_ALVO),
        )
        self.semente.execute(
            "INSERT INTO idx.search_doc (tenant_id, product_ref, norm_versao, nome_norm) "
            "SELECT %s, 'p' || g, 1, 'geleira ' || g || ' litros' "
            "  FROM generate_series(1, %s) g",
            (tenant, PRODUTOS_DO_ALVO),
        )
        self.termo("unidade", "litros", "l")
        inicio = time.monotonic()
        total = 0
        while (escritos := self.reindexar(tenant)) > 0:
            total += escritos
        decorrido = time.monotonic() - inicio
        self.assertEqual(total, PRODUTOS_DO_ALVO)
        self.assertLessEqual(decorrido, ALVO_DE_REINDEXACAO_S, f"{decorrido:.1f} s")
        self.assertEqual(self.documento_de(tenant, "p7")[0], "geleira 7 l")
        print(f"\n[KAM-062] reindexacao de {total} documentos: {decorrido:.1f} s", file=sys.stderr)


class TestTypo(ComLexico):
    """Criterio 5: vocabulario do tenant e a correccao que encontra candidato."""

    def test_a_semelhanca_e_a_do_pg_trgm(self) -> None:
        pares = (("niker", "nike"), ("frigorifco", "frigorifico"), ("xyzq", "nike"), ("tv", "tv"))
        for a, b in pares:
            with self.subTest(par=(a, b)):
                linha = self.consultar("SELECT similarity(%s, %s)", (a, b))
                self.assertAlmostEqual(float(linha[0][0]), normalizacao.semelhanca(a, b), places=5)

    def test_a_correccao_encontra_o_produto_e_o_xyzq_nao_se_resolve(self) -> None:
        tenant = self.tenant_em("ativo")
        self.criar_oferta(tenant, sku="g1", nome="Frigorifico LG 250 L")
        self.indexar(tenant, "g1")
        conexao = self.ligar("app")
        procura = pesquisa.procurar(conexao, tenant, "frigorifco lg", cache=lexico.Cache())
        self.assertEqual(procura.normalizacao.correccoes, (("frigorifco", "frigorifico"),))
        self.assertEqual([l["sku"] for l, _ in procura.linhas], ["g1"])
        procura = pesquisa.procurar(conexao, tenant, "xyzq", cache=lexico.Cache())
        self.assertEqual(procura.normalizacao.tokens_nao_resolvidos, ("xyzq",))

    def test_a_frase_corrigida_inteira_encontra_o_produto(self) -> None:
        """O criterio 5 pede a consulta corrigida, e nao so a palavra (achado 9)."""
        tenant = self.tenant_em("ativo")
        self.criar_oferta(tenant, sku="g1", nome="Frigorifico LG 250 L")
        self.indexar(tenant, "g1")
        procura = pesquisa.procurar(
            self.ligar("app"), tenant, "quero um frigorifco xyzq barato", cache=lexico.Cache()
        )
        self.assertIn(("frigorifco", "frigorifico"), procura.normalizacao.correccoes)
        self.assertIn("xyzq", procura.normalizacao.tokens_nao_resolvidos)
        self.assertEqual([l["sku"] for l, _ in procura.linhas], ["g1"])

    def test_niker_pela_tabela_de_erros_comuns(self) -> None:
        tenant = self.tenant_em("ativo")
        self.criar_oferta(tenant, sku="n1", nome="Nike Air Force 1")
        self.indexar(tenant, "n1")
        self.termo("erro_comum", "niker", "nike")
        procura = pesquisa.procurar(self.ligar("app"), tenant, "niker", cache=lexico.Cache())
        self.assertEqual(procura.normalizacao.q_norm, "nike")
        self.assertEqual([l["sku"] for l, _ in procura.linhas], ["n1"])

    def test_cada_palavra_do_vocabulario_encontra_um_candidato(self) -> None:
        """A garantia por construcao: palavra do vocabulario => >= 1 pelo `fts`."""
        tenant = self.tenant_em("ativo")
        self.criar_oferta(tenant, sku="a", nome="Geleira de 250 litros para casa")
        self.criar_oferta(tenant, sku="b", nome="Telemóvel Samsung A52")
        self.indexar(tenant, "a")
        self.indexar(tenant, "b")
        cursor = self.cursor_app(tenant)
        vocabulario = lexico.ler_vocabulario(cursor)
        self.desfazer(tenant)
        self.assertNotIn("de", vocabulario.frequencias, "palavra vazia do portuguese")
        self.assertIn("telemovel", vocabulario.frequencias)
        for palavra in vocabulario.frequencias:
            with self.subTest(palavra=palavra):
                linhas = self.candidatos(tenant, tenant, palavra, palavra)
                self.assertGreaterEqual(len(linhas), 1)

    def test_o_vocabulario_e_so_do_tenant_do_contexto(self) -> None:
        a, b = self.tenant_em("ativo"), self.tenant_em("ativo")
        self.criar_oferta(b, sku="z", nome="Zungueira exclusiva")
        self.indexar(b, "z")
        cursor = self.cursor_app(a)
        self.assertNotIn("zungueira", lexico.ler_vocabulario(cursor).frequencias)
        self.desfazer(a)


class TestRestricoesNaOfertaViva(ComLexico):
    """As restricoes ditas filtram a oferta viva, e nunca o indice (achado 8).

    O ensaio puro so via a posicao dos parametros; este ve o efeito no
    PostgreSQL, com o `>=` do minimo e o `<=` do maximo a morder.
    """

    def setUp(self) -> None:
        super().setUp()
        self.tenant = self.tenant_em("ativo")
        for sku, kz in (("g-barata", 90_000), ("g-media", 120_000), ("g-cara", 200_000)):
            self.criar_oferta(self.tenant, sku=sku, nome=f"Geleira {sku}", preco_minor=kz * 100)
            self.indexar(self.tenant, sku)
        self.conexao = self.ligar("app")

    def skus(self, texto: str) -> set[str]:
        procura = pesquisa.procurar(self.conexao, self.tenant, texto, cache=lexico.Cache())
        return {l["sku"] for l, _ in procura.linhas}

    def test_entre_filtra_pelos_dois_lados(self) -> None:
        self.assertEqual(self.skus("geleira entre 100 e 150 mil"), {"g-media"})

    def test_o_minimo_sozinho(self) -> None:
        self.assertEqual(self.skus("geleira acima de 100 mil kz"), {"g-media", "g-cara"})

    def test_o_maximo_sozinho(self) -> None:
        self.assertEqual(self.skus("geleira ate 150 mil"), {"g-barata", "g-media"})

    def test_o_alvo_nao_filtra(self) -> None:
        self.assertEqual(self.skus("geleira 120 mil"), {"g-barata", "g-media", "g-cara"})


class TestPrecedencia(ComLexico):
    """Criterio 6: tenant > global, e B nunca em A (RLS, como `kamba_app`)."""

    def test_o_termo_do_tenant_prevalece_sobre_o_global(self) -> None:
        a = self.tenant_em("ativo")
        termo = f"bina{uuid.uuid4().hex[:6]}"
        self.termo("sinonimo", termo, "bicicleta")
        self.termo("sinonimo", termo, "motorizada", tenant=a)
        cursor = self.cursor_app(a)
        lex = lexico.ler_lexico(cursor, a, 1)
        self.desfazer(a)
        self.assertEqual(
            normalizacao.normalizar(termo, a, "texto", lexico=lex).q_or,
            f"{termo} or motorizada",
        )

    def test_um_termo_de_b_nunca_chega_ao_lexico_de_a(self) -> None:
        a, b = self.tenant_em("ativo"), self.tenant_em("ativo")
        termo = f"naiki{uuid.uuid4().hex[:6]}"
        self.termo("marca", termo, "nike", tenant=b)
        cursor = self.cursor_app(a)
        linhas = lexico.consultar(cursor, lexico.SQL_LER_LEXICO)
        self.desfazer(a)
        self.assertNotIn(termo, {l["termo"] for l in linhas})
        # Controlo: com o contexto de B, o mesmo termo le-se.
        cursor = self.cursor_app(b)
        linhas = lexico.consultar(cursor, lexico.SQL_LER_LEXICO)
        self.desfazer(b)
        self.assertIn(termo, {l["termo"] for l in linhas})


class TestRegrasDoLexico(ComLexico):
    """Criterio 7: `aprovado_por` obrigatorio; *dataset* nunca activo.

    Numa ligacao de administrador **com** transaccao, e nao na `semente` (que e
    `autocommit`): o `assertErroSql` precisa de um `SAVEPOINT`, e o que se
    escreve desfaz-se no fim.
    """

    def setUp(self) -> None:
        super().setUp()
        self.admin = self.ligar("admin").cursor()

    def test_sem_aprovado_por_recusa(self) -> None:
        for valor in (None, "", "   "):
            with self.subTest(aprovado_por=valor):
                self.assertErroSql(
                    "23514",
                    self.admin,
                    "INSERT INTO idx.termo_canonico "
                    "(tenant_id, tipo, termo, canonico, origem, aprovado_por) "
                    "VALUES (NULL, 'sinonimo', 'x', 'y', 'ops', %s)",
                    (valor,),
                )

    def test_dataset_so_entra_inactivo(self) -> None:
        self.assertErroSql(
            "23514",
            self.admin,
            "INSERT INTO idx.termo_canonico "
            "(tenant_id, tipo, termo, canonico, origem, aprovado_por) "
            "VALUES (NULL, 'sinonimo', 'x', 'y', 'dataset', 'ops')",
        )
        self.admin.execute(
            "INSERT INTO idx.termo_canonico "
            "(tenant_id, tipo, termo, canonico, origem, activo, aprovado_por) "
            "VALUES (NULL, 'sinonimo', %s, 'y', 'dataset', false, 'ops') RETURNING id",
            (f"ds{uuid.uuid4().hex[:6]}",),
        )
        termo_id = int(self.admin.fetchone()[0])
        self.assertErroSql(
            "23514",
            self.admin,
            "UPDATE idx.termo_canonico SET activo = true WHERE id = %s",
            (termo_id,),
        )
