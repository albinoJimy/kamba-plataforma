"""A revisao 0036 contra a base: os destinos de transferencia (KAM-069).

Seis coisas, e cinco delas sao criterios do bloco pela letra:

1. **A unicidade trata os nulos como iguais, e sem isso nao restringia nada.**
   O `NULLS NOT DISTINCT` e de PostgreSQL 15 e e o que faz `23505` acontecer no
   **segundo** destino global para o mesmo `(provider, country, purpose)`. Sem
   ele os dois passavam — um `pendente` e um `autorizado` — e a porta lia o que
   lhe calhasse primeiro. Criterio 1.

2. **O `autorizado` exige `apd_ref` e exige a *checklist* completa, e sao dois
   `CHECK` distintos.** O criterio 1 pede o primeiro e o criterio 6 pede o
   segundo; com uma restricao so, a mensagem nao dizia qual das duas metades
   faltou. As duas provam-se contra a base, com `23514`, e a separacao
   prova-se tambem — satisfazer uma e falhar a outra tem de dar erro.

3. **A janela de validade nao se contradiz.** Quatro `CHECK`: um `autorizado`
   tem a janela aberta, um `revogado` tem as duas pontas, nenhuma se fecha
   antes de abrir, e nem `pendente` nem `negado` tem janela. O ultimo e o que
   impede a vista do criterio 7 de ler as chamadas de um `pendente` como
   conformes.

4. **A vista do criterio 7 responde «no momento da chamada» e nao «hoje».**
   Prova-se com tres chamadas e uma janela: a de antes do `autorizado_em` e
   violacao, a de dentro da janela nao, e a de depois do `revogado_em` volta a
   ser. E prova-se que o `destino_negado` **nao** aparece — uma recusa e uma
   chamada que nao aconteceu.

5. **As linhas globais sao legiveis por um tenant e nao escritas por ele.** As
   duas politicas permissivas, e a segunda e `FOR SELECT`: o `kamba_app` ve o
   destino global e nao tem `INSERT` nenhum nesta tabela.

6. **O `downgrade`** — «Migracao reversivel». Desce com linhas e **nao
   recusa**: o que se perde e configuracao de conformidade que se repoe, e nao
   prova juridica como o consentimento da `0015`. A vista cai antes da tabela.

E ha um setimo teste que nao e da revisao: a **paridade** do dominio de
`purpose` e de `status` com as listas de `kamba_core.destinos`. E a forma desta
casa para duas copias que tem de dizer o mesmo, e aqui a copia e inevitavel — a
base impoe o dominio e o codigo decide com ele.

A classe do `downgrade` nao herda de `ComBase`: controla ela propria a revisao
da base, e por isso nao pode partilhar a ligacao que nunca confirma.
"""

from __future__ import annotations

import sys
import unittest
import uuid
from pathlib import Path

# **O `kamba_core` nao esta no caminho de quem corre esta suite a mao.** O
# `db/gate_bd.py` acrescenta `db/` ao `sys.path` e mais nada; o resto vem do
# `PYTHONPATH` que o `Makefile` exporta — e esse separa com `:`, que nesta
# maquina nao separa nada (o `os.pathsep` do Windows e `;`). Uma suite que
# dependesse disso falhava com `ModuleNotFoundError` fora do CI, e o diagnostico
# lia-se como defeito do ticket. Resolve-se aqui, pelo caminho do proprio
# ficheiro, que e deterministico.
_RAIZ = Path(__file__).resolve().parents[2]
_NUCLEO = str(_RAIZ / "libs" / "py-core" / "src")
if _NUCLEO not in sys.path:
    sys.path.insert(0, _NUCLEO)

import ligacao
from tests import factories
from tests.base import (
    TABELAS,
    TABELAS_ATE_0035,
    VIOLACAO_DE_CHECK,
    VIOLACAO_DE_UNICIDADE,
    ComBase,
    alembic_ok,
    em_head,
    exigir_base_descartavel,
)

DESTINOS = "platform.tenant_destinations"
VISTA = "platform.v_transfer_audit"

#: Os **quatro** estados do dominio da `0036`.
ESTADOS = ("pendente", "autorizado", "revogado", "negado")

#: As **treze** finalidades do dominio da `0036`.
FINALIDADES = (
    "alojamento",
    "canal",
    "conversa",
    "copias_de_seguranca",
    "embeddings",
    "entrega_de_conteudo",
    "facturacao",
    "observabilidade",
    "otp_e_avisos_de_servico",
    "pagamentos",
    "segredos",
    "transcricao",
    "visao",
)

#: Uma referencia de procedimento com a forma que o `CHECK` aceita. **Nao e um
#: numero de protocolo real** e nao podia ser: nenhuma submissao foi feita (0 de
#: 14, folha de seguimento do KAM-105).
APD_REF = "APD/2026/000-TESTE"
CONTRATO_REF = "contratos/2026/teste"


def _inserir(cursor, tenant_id, **campos) -> None:
    """Um destino, com a *checklist* a `false` e sem janela por omissao."""
    valores = {
        "tenant_id": tenant_id,
        "provider": "fornecedor_de_teste",
        "country": "US",
        "purpose": "conversa",
        "status": "pendente",
        "retencao_zero": False,
        "sem_treino": False,
    }
    valores.update(campos)
    colunas = ", ".join(valores)
    marcas = ", ".join(["%s"] * len(valores))
    cursor.execute(
        f"INSERT INTO {DESTINOS} ({colunas}) VALUES ({marcas})",
        tuple(valores.values()),
    )


class TestDestinosDeTransferencia(ComBase):
    """O que o DDL da `0036` promete.

    `ComBase` da uma ligacao que **nunca confirma**: cada teste desfaz o que
    escreveu, e e por isso que o tenant se semeia em cada um.
    """

    def setUp(self) -> None:
        super().setUp()
        self.conexao = self.ligar("admin")
        self.cursor = self.conexao.cursor()
        self.tenant = factories.tenant(self.cursor)

    def test_a_tabela_e_a_vista_existem_em_head(self) -> None:
        self.assertIn("tenant_destinations", TABELAS)
        self.assertEqual(
            self.consultar(
                "SELECT count(*) FROM pg_views "
                "WHERE schemaname = 'platform' AND viewname = 'v_transfer_audit'"
            ),
            [(1,)],
        )

    def test_a_unicidade_trata_os_nulos_como_iguais(self) -> None:
        """Criterio 1, e a metade que `UNIQUE` sozinha nao dava.

        **Dois destinos globais** para o mesmo `(provider, country, purpose)`.
        Com `UNIQUE` normal os dois passavam — em PostgreSQL um nulo e distinto
        de outro nulo —, e ficavam duas verdades sobre o mesmo destino.
        """
        _inserir(self.cursor, None)
        # **A segunda linha e valida em tudo menos na unicidade**, e isso nao e
        # zelo: um `CHECK` e avaliado **antes** da insercao no indice unico, pelo
        # que uma segunda linha com `status = 'autorizado'` e sem `apd_ref` dava
        # `23514` e este teste passava a medir o `CHECK` do criterio 1 em vez da
        # unicidade do criterio 1. Medido.
        self.assertErroSql(
            VIOLACAO_DE_UNICIDADE,
            self.cursor,
            f"INSERT INTO {DESTINOS} "
            "(tenant_id, provider, country, purpose, status, retencao_zero, "
            " sem_treino) "
            "VALUES (NULL, 'fornecedor_de_teste', 'US', 'conversa', "
            " 'pendente', false, false)",
        )

    def test_o_mesmo_trio_passa_em_tenants_diferentes(self) -> None:
        """A outra metade: a unicidade e **por tenant**, e tem de ser.

        Sem este caso, a prova de cima passava com uma unicidade sobre
        `(provider, country, purpose)` sem o tenant — que recusava a
        configuracao propria de um segundo tenant para o mesmo fornecedor, e e
        exactamente o que a tabela existe para permitir.
        """
        outro = factories.tenant(self.cursor)
        _inserir(self.cursor, self.tenant)
        _inserir(self.cursor, outro)
        # **Na mesma ligacao.** O `self.consultar` do `ComBase` abre uma ligacao
        # nova, e a desta classe nunca confirma — pelo que a leitura de outra
        # ligacao nao ve o que este teste escreveu e a contagem dava zero.
        self.cursor.execute(
            f"SELECT count(*) FROM {DESTINOS} WHERE provider = %s",
            ("fornecedor_de_teste",),
        )
        self.assertEqual(self.cursor.fetchone()[0], 2)

    def test_autorizado_sem_apd_ref_e_recusado(self) -> None:
        """Criterio 1: «`status='autorizado'` exige `apd_ref` nao nulo»."""
        self.assertErroSql(
            VIOLACAO_DE_CHECK,
            self.cursor,
            f"INSERT INTO {DESTINOS} "
            "(tenant_id, provider, country, purpose, status, retencao_zero, "
            " sem_treino, contrato_ref, autorizado_em) "
            "VALUES (%s, 'fornecedor_de_teste', 'US', 'conversa', 'autorizado', "
            " true, true, %s, now())",
            (self.tenant, CONTRATO_REF),
        )

    def test_autorizado_sem_checklist_completa_e_recusado(self) -> None:
        """Criterio 6, e **com o `apd_ref` presente**.

        E essa a prova de que os dois `CHECK` sao distintos: esta linha satisfaz
        o do criterio 1 e falha o do criterio 6. Com uma restricao so, nao havia
        como distinguir «sem referencia da APD» de «sem evidencia arquivada».
        """
        for falta in ("contrato_ref", "retencao_zero", "sem_treino"):
            with self.subTest(falta=falta):
                campos = {
                    "status": "autorizado",
                    "apd_ref": APD_REF,
                    "contrato_ref": CONTRATO_REF,
                    "retencao_zero": True,
                    "sem_treino": True,
                    "autorizado_em": "2026-01-01T00:00:00+00:00",
                }
                campos[falta] = None if falta == "contrato_ref" else False
                colunas = ["tenant_id", "provider", "country", "purpose"] + list(campos)
                valores = [self.tenant, "fornecedor_de_teste", "US", "conversa"]
                valores += list(campos.values())
                self.assertErroSql(
                    VIOLACAO_DE_CHECK,
                    self.cursor,
                    f"INSERT INTO {DESTINOS} ({', '.join(colunas)}) "
                    f"VALUES ({', '.join(['%s'] * len(colunas))})",
                    tuple(valores),
                )

    def test_um_destino_autorizado_completo_passa(self) -> None:
        """O canario das duas provas acima.

        Sem ele, um `CHECK` que recusasse **tudo** passava os dois casos
        negativos e o criterio ficava satisfeito por nada — a classe de defeito
        mais cara deste repositorio.
        """
        _inserir(
            self.cursor,
            self.tenant,
            status="autorizado",
            apd_ref=APD_REF,
            contrato_ref=CONTRATO_REF,
            retencao_zero=True,
            sem_treino=True,
            autorizado_em="2026-01-01T00:00:00+00:00",
        )
        # Na mesma ligacao, pela razao do
        # `test_o_mesmo_trio_passa_em_tenants_diferentes`.
        self.cursor.execute(
            f"SELECT status FROM {DESTINOS} WHERE tenant_id = %s", (self.tenant,)
        )
        self.assertEqual([tuple(l) for l in self.cursor.fetchall()], [("autorizado",)])

    def test_a_janela_nao_se_contradiz(self) -> None:
        """Os quatro `CHECK` da janela de validade, um caso cada."""
        casos = {
            "autorizado com a janela fechada": {
                "status": "autorizado",
                "apd_ref": APD_REF,
                "contrato_ref": CONTRATO_REF,
                "retencao_zero": True,
                "sem_treino": True,
                "autorizado_em": "2026-01-01T00:00:00+00:00",
                "revogado_em": "2026-02-01T00:00:00+00:00",
            },
            "revogado sem a ponta de abertura": {
                "status": "revogado",
                "revogado_em": "2026-02-01T00:00:00+00:00",
            },
            "janela fechada antes de abrir": {
                "status": "revogado",
                "autorizado_em": "2026-02-01T00:00:00+00:00",
                "revogado_em": "2026-01-01T00:00:00+00:00",
            },
            "pendente com janela": {
                "status": "pendente",
                "autorizado_em": "2026-01-01T00:00:00+00:00",
            },
        }
        for nome, campos in casos.items():
            with self.subTest(caso=nome):
                linha: dict[str, object] = {
                    "tenant_id": self.tenant,
                    "provider": "fornecedor_de_teste",
                    "country": "US",
                    "purpose": "conversa",
                    "retencao_zero": False,
                    "sem_treino": False,
                }
                # Os `campos` do caso **sobrepoem-se** a omissao: dois deles
                # trazem os booleanos da *checklist* a `true`, e uma lista que
                # os acumulasse dava um `INSERT` com a coluna repetida.
                linha.update(campos)
                self.assertErroSql(
                    VIOLACAO_DE_CHECK,
                    self.cursor,
                    f"INSERT INTO {DESTINOS} ({', '.join(linha)}) "
                    f"VALUES ({', '.join(['%s'] * len(linha))})",
                    tuple(linha.values()),
                )

    def test_uma_janela_de_duracao_zero_e_recusada(self) -> None:
        """O `>` e nao `>=`, e a razao esta na revisao.

        Uma janela que abre e fecha no mesmo instante nao autorizou chamada
        nenhuma, e escreve-la como `negado` diz a verdade. Sem esta prova, o
        `CHECK` podia ser `>=` e a vista do criterio 7 tratava como conforme uma
        chamada no instante exacto de uma janela vazia.
        """
        instante = "2026-01-01T00:00:00+00:00"
        self.assertErroSql(
            VIOLACAO_DE_CHECK,
            self.cursor,
            f"INSERT INTO {DESTINOS} "
            "(tenant_id, provider, country, purpose, status, retencao_zero, "
            " sem_treino, autorizado_em, revogado_em) "
            "VALUES (%s, 'fornecedor_de_teste', 'US', 'conversa', 'revogado', "
            " false, false, %s, %s)",
            (self.tenant, instante, instante),
        )

    def test_os_dominios_fechados_sao_os_do_codigo(self) -> None:
        """Paridade entre o `CHECK` da base e as listas de `kamba_core.destinos`.

        **Le-se do catalogo e nao da revisao**, pela licao que a `0008` e a
        `0009` pagaram: comparar com o texto do ficheiro prova que o ficheiro
        diz o que diz, e nao que a base aceita o que o codigo espera.
        """
        from kamba_core.destinos import ESTADOS as ESTADOS_DO_NUCLEO
        from kamba_core.destinos import FINALIDADES as FINALIDADES_DO_NUCLEO

        self.assertEqual(set(ESTADOS), set(ESTADOS_DO_NUCLEO))
        self.assertEqual(set(FINALIDADES), set(FINALIDADES_DO_NUCLEO))
        for restricao, valores in (
            ("tenant_destinations_status_ck", ESTADOS),
            ("tenant_destinations_purpose_ck", FINALIDADES),
        ):
            with self.subTest(restricao=restricao):
                definicao = self.consultar(
                    "SELECT pg_get_constraintdef(oid) FROM pg_constraint "
                    "WHERE conname = %s",
                    (restricao,),
                )[0][0]
                for valor in valores:
                    self.assertIn(f"'{valor}'", definicao)
                # Nos dois sentidos: um valor a mais no `CHECK` e tao defeito
                # como um a menos. Conta-se, porque uma asercao de pertenca so
                # apanha o que falta.
                self.assertEqual(definicao.count("'::text"), len(valores))


class TestLinhasGlobais(unittest.TestCase):
    """Criterio 1, segunda metade: «RLS `FORCE` com linhas globais legiveis».

    **Classe propria, e com ligacao em `autocommit`.** A pergunta e o que o
    `kamba_app` ve **noutra ligacao**, e uma ligacao que nunca confirma nao
    torna a linha visivel a nenhuma outra — pelo que o `ComBase` nao serve
    aqui. E a mesma forma do `TestDowngradeDa0016` de
    `db/tests/test_modos_privilegios.py`, e a limpeza e explicita no `tearDown`.
    """

    @classmethod
    def setUpClass(cls) -> None:
        exigir_base_descartavel()
        if not em_head():
            alembic_ok("upgrade", "head")

    def setUp(self) -> None:
        self.conexao = ligacao.ligar("admin")
        self.conexao.autocommit = True
        self.cursor = self.conexao.cursor()
        self.provider = f"global_{uuid.uuid4().hex[:8]}"
        self.tenant = factories.tenant(self.cursor)

    def tearDown(self) -> None:
        try:
            self.cursor.execute(
                f"DELETE FROM {DESTINOS} WHERE provider = %s", (self.provider,)
            )
            self.cursor.execute(
                "DELETE FROM platform.tenants WHERE id = %s", (self.tenant,)
            )
        finally:
            self.conexao.close()

    def _o_que_a_app_ve(self) -> list[tuple]:
        app = ligacao.ligar("app")
        try:
            cursor = app.cursor()
            factories.contexto(cursor, self.tenant)
            cursor.execute(
                f"SELECT provider FROM {DESTINOS} WHERE provider = %s",
                (self.provider,),
            )
            return [tuple(linha) for linha in cursor.fetchall()]
        finally:
            app.rollback()
            app.close()

    def test_um_tenant_ve_a_linha_global(self) -> None:
        _inserir(self.cursor, None, provider=self.provider)
        self.assertEqual(self._o_que_a_app_ve(), [(self.provider,)])

    def test_um_tenant_nao_ve_a_linha_de_outro(self) -> None:
        """O canario do teste acima.

        Sem ele, uma politica `USING (true)` passava o primeiro teste e a
        asercao «linhas globais legiveis» ficava satisfeita por uma politica que
        tornava **tudo** legivel.
        """
        outro = factories.tenant(self.cursor)
        try:
            _inserir(self.cursor, outro, provider=self.provider)
            self.assertEqual(self._o_que_a_app_ve(), [])
        finally:
            self.cursor.execute(
                f"DELETE FROM {DESTINOS} WHERE tenant_id = %s", (outro,)
            )
            self.cursor.execute(
                "DELETE FROM platform.tenants WHERE id = %s", (outro,)
            )

    def test_a_aplicacao_nao_escreve_nesta_tabela(self) -> None:
        """O privilegio **nem existe**, que e mais forte do que a politica recusar.

        Autorizar um destino e um acto humano com papelada arquivada — contrato,
        retencao zero, nao-treino, numero de procedimento da APD — e nao uma
        escrita de um processo que serve conversas. Com `INSERT`, um defeito no
        servico que serve o turno podia abrir um destino a si proprio.
        """
        for privilegio in ("INSERT", "UPDATE", "DELETE"):
            with self.subTest(privilegio=privilegio):
                self.cursor.execute(
                    "SELECT has_table_privilege('kamba_app', %s, %s)",
                    (DESTINOS, privilegio),
                )
                self.assertFalse(self.cursor.fetchone()[0])

    def test_a_politica_das_globais_e_so_de_leitura(self) -> None:
        """`FOR SELECT`, e e ai que a barreira vive.

        Com `ALL`, um tenant **escrevia** uma linha global — autorizar um
        destino de infra-estrutura para a plataforma toda a partir do contexto
        de um tenant. O `kamba_app` nao tem `INSERT` (teste acima), mas o
        `kamba_batch` tem: a politica e a barreira para quem vier depois com
        privilegio e sem `BYPASSRLS`.
        """
        self.cursor.execute(
            "SELECT cmd, qual, with_check FROM pg_policies "
            "WHERE schemaname = 'platform' AND tablename = 'tenant_destinations' "
            "AND policyname = 'destinos_globais'"
        )
        linha = self.cursor.fetchone()
        self.assertIsNotNone(linha, "a politica `destinos_globais` nao existe")
        cmd, qual, com_check = linha
        self.assertEqual(cmd, "SELECT")
        self.assertIn("tenant_id IS NULL", qual)
        self.assertIsNone(com_check)


class TestVistaDeAuditoriaDeTransferencias(ComBase):
    """A `v_transfer_audit`: o criterio 7, e o «no momento da chamada».

    Esta classe escreve em `dat.llm_call_log`, que e *append-only* nas tres
    camadas da `0006` — pelo que **nao se apaga com `DELETE`** e a ligacao que
    nunca confirma e a unica forma de limpar. E por isso que tudo corre numa
    transaccao so, como `admin`.
    """

    def setUp(self) -> None:
        super().setUp()
        self.conexao = self.ligar("admin")
        self.cursor = self.conexao.cursor()
        self.tenant = factories.tenant(self.cursor)
        self.fornecedor = f"forn_{uuid.uuid4().hex[:8]}"

    def _chamada(self, instante: str, resultado: str = "ok") -> None:
        """Uma linha de `dat.llm_call_log`, pelo caminho que a `0023` aceita.

        **Os quatro contadores sao nulos quando o desfecho e `destino_negado`**,
        e nao e uma escolha deste teste: o `llm_call_log_negado_sem_consumo` da
        `0023` exige-o, porque «uma recusa de destino nao tem custo nem tokens».
        Com zeros, a linha levava `23514` e o teste da recusa media o `CHECK` de
        outra revisao em vez da vista desta.
        """
        negado = resultado == "destino_negado"
        self.cursor.execute(
            "INSERT INTO dat.llm_call_log "
            "(ts, tenant_id, trace_id, vertical, no_grafo, papel, graph_version, "
            " modelo, fornecedor, tokens_in, tokens_out, tokens_cache, "
            " custo_usd, latencia_ms, resultado) "
            "VALUES (%s, %s, %s, 'vendedor', 'no_de_teste', 'chat', '1.0.0', "
            " 'modelo-de-teste', %s, %s, %s, %s, NULL, 1, %s)",
            (
                instante,
                self.tenant,
                str(uuid.uuid4()),
                self.fornecedor,
                None if negado else 0,
                None if negado else 0,
                None if negado else 0,
                resultado,
            ),
        )

    def _violacoes(self) -> int:
        self.cursor.execute(
            f"SELECT count(*) FROM {VISTA} WHERE fornecedor = %s", (self.fornecedor,)
        )
        return self.cursor.fetchone()[0]

    def test_sem_destino_a_chamada_e_violacao(self) -> None:
        self._chamada("2026-06-01T12:00:00+00:00")
        self.assertEqual(self._violacoes(), 1)

    def test_a_recusa_do_gate_nao_e_violacao(self) -> None:
        """`destino_negado` e uma chamada que **nao aconteceu**.

        O *gate* corre antes de haver pedido e o
        `llm_call_log_negado_sem_consumo` da `0023` recusa a linha se levar
        *tokens* ou custo. Inclui-la punha a vista a crescer com o numero de
        recusas, e em `prod` — onde hoje nada esta autorizado — o alvo zero do
        criterio 7 era inalcancavel por construcao.
        """
        self._chamada("2026-06-01T12:00:00+00:00", resultado="destino_negado")
        self.assertEqual(self._violacoes(), 0)

    def test_a_janela_decide_e_nao_o_estado_de_hoje(self) -> None:
        """Criterio 7: «sem `autorizado` com `apd_ref` **no momento da chamada**».

        Tres chamadas e uma janela de Fevereiro a Abril, com o destino **hoje**
        `revogado`. Sem as colunas da janela, a leitura do estado actual dava
        tres violacoes — e as duas de fora da janela sao as unicas que o sao.
        """
        _inserir(
            self.cursor,
            self.tenant,
            provider=self.fornecedor,
            purpose="conversa",
            status="revogado",
            apd_ref=APD_REF,
            contrato_ref=CONTRATO_REF,
            retencao_zero=True,
            sem_treino=True,
            autorizado_em="2026-02-01T00:00:00+00:00",
            revogado_em="2026-04-01T00:00:00+00:00",
        )
        self._chamada("2026-01-15T12:00:00+00:00")  # antes de abrir
        self._chamada("2026-03-15T12:00:00+00:00")  # dentro
        self._chamada("2026-05-15T12:00:00+00:00")  # depois de fechar
        self.assertEqual(self._violacoes(), 2)
        self.cursor.execute(
            f"SELECT ts FROM {VISTA} WHERE fornecedor = %s ORDER BY ts",
            (self.fornecedor,),
        )
        meses = [linha[0].month for linha in self.cursor.fetchall()]
        self.assertEqual(meses, [1, 5])

    def test_um_destino_global_cobre_a_chamada_de_um_tenant(self) -> None:
        """A juncao aceita `d.tenant_id IS NULL`, que e o destino de infra.

        Sem este caso, a vista podia exigir linha **do tenant** e dava violacao
        para toda a chamada coberta por um destino global — que e como o
        alojamento, o CDN e a observabilidade se autorizam.
        """
        _inserir(
            self.cursor,
            None,
            provider=self.fornecedor,
            status="autorizado",
            apd_ref=APD_REF,
            contrato_ref=CONTRATO_REF,
            retencao_zero=True,
            sem_treino=True,
            autorizado_em="2026-01-01T00:00:00+00:00",
        )
        self._chamada("2026-06-01T12:00:00+00:00")
        self.assertEqual(self._violacoes(), 0)

    def test_um_destino_de_outra_finalidade_nao_cobre_a_chamada(self) -> None:
        """A vista nao pode ser mais permissiva do que o *gate* que audita.

        Um destino autorizado **so para `segredos`** — o Doppler, por exemplo —
        nao cobre uma chamada a um modelo. Sem o `d.purpose IN (...)` na juncao,
        a vista dizia conforme uma transferencia que o *gate* teria recusado, e
        uma superficie de auditoria mais frouxa do que a barreira e pior do que
        nenhuma.
        """
        _inserir(
            self.cursor,
            self.tenant,
            provider=self.fornecedor,
            purpose="segredos",
            status="autorizado",
            apd_ref=APD_REF,
            contrato_ref=CONTRATO_REF,
            retencao_zero=True,
            sem_treino=True,
            autorizado_em="2026-01-01T00:00:00+00:00",
        )
        self._chamada("2026-06-01T12:00:00+00:00")
        self.assertEqual(self._violacoes(), 1)

    def test_as_tres_finalidades_de_modelo_cobrem(self) -> None:
        """O canario do teste acima, e nas **tres**.

        Uma juncao que exigisse `conversa` sozinha passava o caso negativo e
        deixava uma chamada de `embed` ou de `vision` eternamente em violacao —
        o inverso do defeito, e igualmente errado. As tres sao as do
        `FINALIDADES` do AGR, e a asercao de que sao essas tres esta em
        `services/agr/tests/test_llm_destinos.py`.
        """
        from kamba_core.destinos import (
            FINALIDADE_CONVERSA,
            FINALIDADE_EMBEDDINGS,
            FINALIDADE_VISAO,
        )

        for finalidade in (FINALIDADE_CONVERSA, FINALIDADE_EMBEDDINGS, FINALIDADE_VISAO):
            with self.subTest(finalidade=finalidade):
                fornecedor = f"forn_{uuid.uuid4().hex[:8]}"
                _inserir(
                    self.cursor,
                    self.tenant,
                    provider=fornecedor,
                    purpose=finalidade,
                    status="autorizado",
                    apd_ref=APD_REF,
                    contrato_ref=CONTRATO_REF,
                    retencao_zero=True,
                    sem_treino=True,
                    autorizado_em="2026-01-01T00:00:00+00:00",
                )
                guardado, self.fornecedor = self.fornecedor, fornecedor
                try:
                    self._chamada("2026-06-01T12:00:00+00:00")
                    self.assertEqual(self._violacoes(), 0)
                finally:
                    self.fornecedor = guardado

    def test_a_linha_do_tenant_tapa_a_global_tambem_na_vista(self) -> None:
        """Achado 1 da revisao adversarial: a precedencia do `porta.py`.

        Uma linha **do tenant** a dizer `negado` tapa a global `autorizado` — e
        a porta nega (`aplicaveis = especificas or globais`). A primeira versao
        da vista era um anti-*join* e dizia **conforme**, porque a global
        satisfazia a juncao: uma segunda medicao mais frouxa do que a primeira
        nao mede nada de novo.
        """
        _inserir(
            self.cursor,
            None,
            provider=self.fornecedor,
            status="autorizado",
            apd_ref=APD_REF,
            contrato_ref=CONTRATO_REF,
            retencao_zero=True,
            sem_treino=True,
            autorizado_em="2026-01-01T00:00:00+00:00",
        )
        _inserir(
            self.cursor, self.tenant, provider=self.fornecedor, status="negado"
        )
        self._chamada("2026-06-01T12:00:00+00:00")
        self.assertEqual(self._violacoes(), 1)

    def test_uma_aplicavel_que_nao_autoriza_e_violacao_na_vista(self) -> None:
        """Achado 1, segunda metade: a conjuncao do passo 4 do `porta.py`.

        O mesmo fornecedor e a mesma finalidade em **dois paises** — `ZA`
        autorizado e `US` `pendente`. A chamada nao escolhe o pais, pelo que a
        porta falha fechada sobre a **uniao**; a primeira versao da vista
        bastava-lhe uma linha que casasse e dizia conforme.
        """
        _inserir(
            self.cursor,
            self.tenant,
            provider=self.fornecedor,
            country="ZA",
            status="autorizado",
            apd_ref=APD_REF,
            contrato_ref=CONTRATO_REF,
            retencao_zero=True,
            sem_treino=True,
            autorizado_em="2026-01-01T00:00:00+00:00",
        )
        _inserir(
            self.cursor, self.tenant, provider=self.fornecedor, country="US"
        )
        self._chamada("2026-06-01T12:00:00+00:00")
        self.assertEqual(self._violacoes(), 1)

    def test_duas_aplicaveis_autorizadas_nao_sao_violacao(self) -> None:
        """O canario dos dois testes acima.

        Sem ele, uma vista que declarasse **tudo** violacao passava os dois — e
        a correccao do achado 1 podia ter sido escrita a mais, o que torna o
        alvo zero do criterio 7 inalcancavel e a vista inutil pelo outro lado.
        """
        for pais in ("ZA", "US"):
            _inserir(
                self.cursor,
                self.tenant,
                provider=self.fornecedor,
                country=pais,
                status="autorizado",
                apd_ref=APD_REF,
                contrato_ref=CONTRATO_REF,
                retencao_zero=True,
                sem_treino=True,
                autorizado_em="2026-01-01T00:00:00+00:00",
            )
        self._chamada("2026-06-01T12:00:00+00:00")
        self.assertEqual(self._violacoes(), 0)

    def test_uma_global_que_nao_autoriza_tambem_e_violacao(self) -> None:
        """A conjuncao vale igual no ambito global, e isso prova-se.

        Sem este caso, uma correccao que aplicasse a conjuncao **so** as linhas
        do tenant passava o teste de cima e deixava as globais — que sao as da
        infra-estrutura, e as que mais tenants partilham — com a regra frouxa.
        """
        _inserir(
            self.cursor,
            None,
            provider=self.fornecedor,
            country="ZA",
            status="autorizado",
            apd_ref=APD_REF,
            contrato_ref=CONTRATO_REF,
            retencao_zero=True,
            sem_treino=True,
            autorizado_em="2026-01-01T00:00:00+00:00",
        )
        _inserir(self.cursor, None, provider=self.fornecedor, country="US")
        self._chamada("2026-06-01T12:00:00+00:00")
        self.assertEqual(self._violacoes(), 1)

    def test_um_destino_de_outro_tenant_nao_cobre_a_chamada(self) -> None:
        """O canario do caso acima: a juncao nao e sobre o fornecedor sozinho."""
        outro = factories.tenant(self.cursor)
        _inserir(
            self.cursor,
            outro,
            provider=self.fornecedor,
            status="autorizado",
            apd_ref=APD_REF,
            contrato_ref=CONTRATO_REF,
            retencao_zero=True,
            sem_treino=True,
            autorizado_em="2026-01-01T00:00:00+00:00",
        )
        self._chamada("2026-06-01T12:00:00+00:00")
        self.assertEqual(self._violacoes(), 1)


class TestDowngradeDa0036(unittest.TestCase):
    """«Migracao reversivel»: desce com linhas e volta a subir.

    Nao herda de `ComBase`: controla a revisao da base, pelo que nao pode
    partilhar a ligacao que nunca confirma.
    """

    @classmethod
    def setUpClass(cls) -> None:
        exigir_base_descartavel()
        if not em_head():
            alembic_ok("upgrade", "head")

    @classmethod
    def tearDownClass(cls) -> None:
        if not em_head():
            alembic_ok("upgrade", "head")

    def _tabelas(self) -> tuple[str, ...]:
        conexao = ligacao.ligar("admin")
        try:
            cursor = conexao.cursor()
            cursor.execute(
                "SELECT tablename::text FROM pg_tables "
                "WHERE schemaname = 'platform' ORDER BY 1"
            )
            return tuple(linha[0] for linha in cursor.fetchall())
        finally:
            conexao.close()

    def test_desce_com_linhas_e_volta_a_subir(self) -> None:
        conexao = ligacao.ligar("admin")
        try:
            cursor = conexao.cursor()
            tenant = factories.tenant(cursor)
            _inserir(cursor, tenant, provider="destino_de_downgrade")
            _inserir(cursor, None, provider="destino_de_downgrade")
            conexao.commit()
        finally:
            conexao.close()

        alembic_ok("downgrade", "0035")
        self.assertEqual(self._tabelas(), TABELAS_ATE_0035)
        # A vista cai antes da tabela, e o `downgrade` nao leva `CASCADE`: se
        # ficasse pendurada, o `DROP TABLE` falhava com `2BP01`.
        conexao = ligacao.ligar("admin")
        try:
            cursor = conexao.cursor()
            cursor.execute(
                "SELECT count(*) FROM pg_views "
                "WHERE schemaname = 'platform' AND viewname = 'v_transfer_audit'"
            )
            self.assertEqual(cursor.fetchone()[0], 0)
        finally:
            conexao.close()

        alembic_ok("upgrade", "head")
        self.assertEqual(self._tabelas(), TABELAS)


if __name__ == "__main__":
    unittest.main()
