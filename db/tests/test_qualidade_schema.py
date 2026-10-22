"""A revisao 0014 contra a base: o registo de qualidade e o tecto do portfolio.

Duas coisas, e a segunda e a que o DoD pede pelo nome:

1. **O que o DDL promete.** O dominio fechado de `evento`, a unicidade
   `(tenant_id, event_key)` que da a idempotencia do criterio 6, as duas FK
   compostas, os `CHECK` de nao-vazio, o `valor_anterior` anulavel, e o
   privilegio: `kamba_app` tem `SELECT` e `INSERT` e **nao tem `UPDATE`** — uma
   linha deste registo e o facto de a Meta ter dito uma coisa a uma hora.

2. **O `downgrade`** — «Migracoes reversiveis: `downgrade` testado». Nao recusa
   com linhas, e e deliberado: o que se perde e o historico das transicoes, e o
   estado corrente vive em `tenant_channels.quality_rating`, que esta revisao
   nao cria nem apaga. O historico reconstroi-se do que chegar a seguir e nao e
   prova de nada perante terceiros. A diferenca face a `0010` — que recusa, por
   apagar o registo do que se enviou e cobrou — esta escrita na propria revisao.

A classe do `downgrade` nao herda de `ComBase`: controla ela propria a revisao
da base, e `ComBase` assume `head`.
"""

from __future__ import annotations

import pathlib
import re
import unittest

import bootstrap
import ligacao
from tests import factories
from tests.base import (
    TABELAS,
    TABELAS_ATE_0013,
    ComBase,
    alembic_ok,
    em_head,
    exigir_base_descartavel,
)

#: Os SQLSTATE que os casos negativos esperam.
CHECK_VIOLATION = "23514"
UNIQUE_VIOLATION = "23505"
FK_VIOLATION = "23503"
NOT_NULL_VIOLATION = "23502"

#: O dominio de `evento`, como a revisao o declara. Sao exactamente os quatro
#: `kind` que o `DESTINO_POR_KIND` do `entrada/contrato.ts` manda para
#: `gestao_de_canal` — e ha um teste no lado do TypeScript que o confronta.
EVENTOS = (
    "phone_number_quality_update",
    "business_capability_update",
    "account_alerts",
    "message_template_quality_update",
)


def _tabelas(cursor) -> tuple[str, ...]:
    cursor.execute(
        "SELECT tablename::text FROM pg_tables WHERE schemaname = 'platform' ORDER BY 1"
    )
    return tuple(linha[0] for linha in cursor.fetchall())


class TestRegistoDeQualidade(ComBase):
    """O que o DDL da `0014` promete.

    `ComBase` da uma ligacao que **nunca confirma**: cada teste desfaz o que
    escreveu, e e por isso que o canal se semeia em cada um.
    """

    def setUp(self) -> None:
        super().setUp()
        self.conexao = self.ligar("admin")
        self.cursor = self.conexao.cursor()
        self.tenant = factories.tenant(self.cursor)
        self.canal = factories.canal(self.cursor, self.tenant)

    def _inserir(self, **troca) -> None:
        campos = {
            "tenant_id": self.tenant,
            "channel_id": self.canal,
            "evento": "phone_number_quality_update",
            "valor_anterior": None,
            "valor_novo": "GREEN",
            "event_key": "chave-de-ensaio",
        }
        campos.update(troca)
        self.cursor.execute(
            "INSERT INTO platform.channel_quality_log "
            "(tenant_id, channel_id, evento, valor_anterior, valor_novo, event_key) "
            "VALUES (%s, %s, %s, %s, %s, %s)",
            (
                campos["tenant_id"],
                campos["channel_id"],
                campos["evento"],
                campos["valor_anterior"],
                campos["valor_novo"],
                campos["event_key"],
            ),
        )

    def test_os_quatro_eventos_do_dominio_passam(self) -> None:
        for indice, evento in enumerate(EVENTOS):
            with self.subTest(evento=evento):
                self._inserir(evento=evento, event_key=f"chave-{indice}")

    def test_um_evento_fora_do_dominio_e_recusado(self) -> None:
        """O `CHECK` e a ultima barreira; o `DESTINO_POR_KIND` e a primeira."""
        self.assertErroSql(
            CHECK_VIOLATION,
            self.cursor,
            "INSERT INTO platform.channel_quality_log "
            "(tenant_id, channel_id, evento, valor_novo, event_key) "
            "VALUES (%s, %s, 'messages', 'GREEN', 'x')",
            (self.tenant, self.canal),
        )

    def test_o_valor_anterior_nulo_e_aceite_e_e_a_primeira_linha(self) -> None:
        """O `NULL` tem significado: nao havia valor anterior."""
        self._inserir(valor_anterior=None)
        self.cursor.execute(
            "SELECT valor_anterior FROM platform.channel_quality_log "
            "WHERE tenant_id = %s",
            (self.tenant,),
        )
        self.assertIsNone(self.cursor.fetchone()[0])

    def test_um_valor_anterior_vazio_e_recusado(self) -> None:
        """Anulavel nao e o mesmo que vazio: `''` punha uma leitura a adivinhar."""
        self.assertErroSql(
            CHECK_VIOLATION,
            self.cursor,
            "INSERT INTO platform.channel_quality_log "
            "(tenant_id, channel_id, evento, valor_anterior, valor_novo, event_key) "
            "VALUES (%s, %s, 'phone_number_quality_update', '   ', 'RED', 'x')",
            (self.tenant, self.canal),
        )

    def test_um_valor_desconhecido_da_meta_e_aceite(self) -> None:
        """**O criterio 1 manda registar sem falhar.**

        A coluna guarda o que a Meta anunciou tal e qual, mesmo quando nao e um
        dos tres que conhecemos: e isso que permite descobrir depois o que ela
        passou a mandar. Um dominio fechado aqui transformava uma mudanca da
        Meta numa falha de insercao.
        """
        self._inserir(valor_novo="PURPLE")
        self.cursor.execute(
            "SELECT valor_novo FROM platform.channel_quality_log WHERE tenant_id = %s",
            (self.tenant,),
        )
        self.assertEqual(self.cursor.fetchone()[0], "PURPLE")

    def test_um_valor_novo_vazio_e_recusado(self) -> None:
        self.assertErroSql(
            CHECK_VIOLATION,
            self.cursor,
            "INSERT INTO platform.channel_quality_log "
            "(tenant_id, channel_id, evento, valor_novo, event_key) "
            "VALUES (%s, %s, 'phone_number_quality_update', '', 'x')",
            (self.tenant, self.canal),
        )

    def test_uma_chave_vazia_e_recusada(self) -> None:
        self.assertErroSql(
            CHECK_VIOLATION,
            self.cursor,
            "INSERT INTO platform.channel_quality_log "
            "(tenant_id, channel_id, evento, valor_novo, event_key) "
            "VALUES (%s, %s, 'phone_number_quality_update', 'GREEN', '  ')",
            (self.tenant, self.canal),
        )

    def test_um_valor_novo_nulo_e_recusado(self) -> None:
        self.assertErroSql(
            NOT_NULL_VIOLATION,
            self.cursor,
            "INSERT INTO platform.channel_quality_log "
            "(tenant_id, channel_id, evento, valor_novo, event_key) "
            "VALUES (%s, %s, 'phone_number_quality_update', NULL, 'x')",
            (self.tenant, self.canal),
        )

    def test_a_mesma_chave_duas_vezes_e_recusada(self) -> None:
        """**A idempotencia do criterio 6, e e da base.**"""
        self._inserir(event_key="repetida")
        self.assertErroSql(
            UNIQUE_VIOLATION,
            self.cursor,
            "INSERT INTO platform.channel_quality_log "
            "(tenant_id, channel_id, evento, valor_novo, event_key) "
            "VALUES (%s, %s, 'phone_number_quality_update', 'RED', 'repetida')",
            (self.tenant, self.canal),
        )

    def test_a_mesma_chave_em_dois_tenants_da_duas_linhas(self) -> None:
        """**A unicidade e por tenant, e e a razao da emenda 1.21.**

        Com unicidade global, um evento do *tenant* B que calhasse na mesma
        chave era deduplicado em silencio contra uma linha de A. A chave e
        derivada de dados da Meta que sao unicos na pratica; a composicao nao a
        torna mais fraca, torna impossivel que um *tenant* engula o evento de
        outro.
        """
        self._inserir(event_key="partilhada")
        outro = factories.tenant(self.cursor)
        canal_do_outro = factories.canal(self.cursor, outro)
        self._inserir(
            tenant_id=outro, channel_id=canal_do_outro, event_key="partilhada"
        )
        self.cursor.execute(
            "SELECT count(*) FROM platform.channel_quality_log "
            "WHERE event_key = 'partilhada'"
        )
        self.assertEqual(self.cursor.fetchone()[0], 2)

    def test_a_fk_do_canal_leva_o_tenant(self) -> None:
        """Um canal de outro tenant nao se aponta.

        Sem a FK composta, uma transicao de A podia apontar para um canal de B,
        e nem o *gate* 6 nem o 3b o veriam — e a razao que a `0009` fixou.
        """
        outro = factories.tenant(self.cursor)
        canal_do_outro = factories.canal(self.cursor, outro)
        self.assertErroSql(
            FK_VIOLATION,
            self.cursor,
            "INSERT INTO platform.channel_quality_log "
            "(tenant_id, channel_id, evento, valor_novo, event_key) "
            "VALUES (%s, %s, 'phone_number_quality_update', 'GREEN', 'x')",
            (self.tenant, canal_do_outro),
        )

    def test_a_app_insere_e_le_mas_nao_altera(self) -> None:
        """**O `UPDATE` nao existe, e e mais forte do que uma politica.**

        A verificacao e pelo catalogo e nao por uma escrita: o que se afirma e o
        **privilegio**, e uma escrita como administrador passava mesmo sem
        concessao nenhuma.
        """
        self.cursor.execute(
            """
            SELECT privilege_type::text
              FROM information_schema.table_privileges
             WHERE table_schema = 'platform'
               AND table_name = 'channel_quality_log'
               AND grantee = 'kamba_app'
             ORDER BY 1
            """
        )
        self.assertEqual(
            [linha[0] for linha in self.cursor.fetchall()], ["INSERT", "SELECT"]
        )
        self.cursor.execute(
            """
            SELECT count(*)
              FROM information_schema.column_privileges
             WHERE table_schema = 'platform'
               AND table_name = 'channel_quality_log'
               AND grantee = 'kamba_app'
               AND privilege_type = 'UPDATE'
            """
        )
        self.assertEqual(self.cursor.fetchone()[0], 0)


class TestTectoDoPortfolio(ComBase):
    """A coluna `max_phone_numbers_per_business` da `0014`."""

    def setUp(self) -> None:
        super().setUp()
        self.conexao = self.ligar("admin")
        self.cursor = self.conexao.cursor()
        self.tenant = factories.tenant(self.cursor)
        self.canal = factories.canal(self.cursor, self.tenant)

    def test_nasce_nulo(self) -> None:
        """O `NULL` e «a Meta ainda nao disse», nao «zero numeros»."""
        self.cursor.execute(
            "SELECT max_phone_numbers_per_business FROM platform.tenant_channels "
            "WHERE id = %s",
            (self.canal,),
        )
        self.assertIsNone(self.cursor.fetchone()[0])

    def test_um_tecto_positivo_passa(self) -> None:
        for valor in (2, 20, 100):
            with self.subTest(valor=valor):
                self.cursor.execute(
                    "UPDATE platform.tenant_channels "
                    "SET max_phone_numbers_per_business = %s WHERE id = %s",
                    (valor, self.canal),
                )

    def test_um_tecto_de_zero_ou_negativo_e_recusado(self) -> None:
        """Um portfolio com tecto zero nao existe: a conta tem o numero dela."""
        for valor in (0, -1):
            with self.subTest(valor=valor):
                self.assertErroSql(
                    CHECK_VIOLATION,
                    self.cursor,
                    "UPDATE platform.tenant_channels "
                    "SET max_phone_numbers_per_business = %s WHERE id = %s",
                    (valor, self.canal),
                )

    def test_nao_e_um_telefone_e_o_tipo_prova_o(self) -> None:
        """**O nome tem «phone» e a coluna nao guarda telefones.**

        A `COLUNAS_DE_TELEFONE_ACEITES` do `test_catalogo.py` declara-a, e a
        razao que a torna aceitavel e esta: e um `integer`, e num `integer` nao
        cabe um E.164. E uma garantia mais forte do que a do `phone_number_id`,
        que e `text`.
        """
        self.cursor.execute(
            "SELECT data_type FROM information_schema.columns "
            "WHERE table_schema = 'platform' AND table_name = 'tenant_channels' "
            "  AND column_name = 'max_phone_numbers_per_business'"
        )
        self.assertEqual(self.cursor.fetchone()[0], "integer")


class TestDowngradeDa0014(unittest.TestCase):
    """«Migracoes reversiveis — `downgrade` testado»."""

    @classmethod
    def setUpClass(cls) -> None:
        exigir_base_descartavel()
        bootstrap.aplicar()
        if not em_head():
            alembic_ok("upgrade", "head")

    def setUp(self) -> None:
        self.conexao = ligacao.ligar("admin")
        self.conexao.autocommit = True
        self.cursor = self.conexao.cursor()
        self.tenants: list[str] = []

    def tearDown(self) -> None:
        try:
            # Cada processo do Alembic custa segundos: so quando a base nao
            # esta em `head` (o teste desceu, ou falhou a meio de descer).
            if not em_head():
                alembic_ok("upgrade", "head")
            for tenant in self.tenants:
                self.cursor.execute(
                    "DELETE FROM platform.channel_quality_log WHERE tenant_id = %s",
                    (tenant,),
                )
                self.cursor.execute(
                    "DELETE FROM platform.tenant_channels WHERE tenant_id = %s",
                    (tenant,),
                )
                self.cursor.execute(
                    "DELETE FROM platform.tenants WHERE id = %s", (tenant,)
                )
        finally:
            self.conexao.close()

    def _tem_coluna(self) -> bool:
        self.cursor.execute(
            """
            SELECT count(*)
              FROM information_schema.columns
             WHERE table_schema = 'platform' AND table_name = 'tenant_channels'
               AND column_name = 'max_phone_numbers_per_business'
            """
        )
        return self.cursor.fetchone()[0] == 1

    def test_desce_com_linhas_e_sobe_outra_vez(self) -> None:
        """Desce **sem recusar**, e a razao esta no `docstring` da revisao.

        O que se perde e o historico das transicoes; o estado corrente vive em
        `tenant_channels.quality_rating`, que esta revisao nao cria nem apaga.
        """
        tenant = factories.tenant(self.cursor)
        self.tenants.append(tenant)
        canal = factories.canal(self.cursor, tenant)
        self.cursor.execute(
            "UPDATE platform.tenant_channels "
            "SET quality_rating = 'RED', max_phone_numbers_per_business = 20 "
            "WHERE id = %s",
            (canal,),
        )
        self.cursor.execute(
            "INSERT INTO platform.channel_quality_log "
            "(tenant_id, channel_id, evento, valor_anterior, valor_novo, event_key) "
            "VALUES (%s, %s, 'phone_number_quality_update', 'GREEN', 'RED', 'k1')",
            (tenant, canal),
        )
        self.assertEqual(_tabelas(self.cursor), TABELAS)
        self.assertTrue(self._tem_coluna())

        alembic_ok("downgrade", "0013")
        # A tabela e a coluna desapareceram, e a linha do canal **ficou**.
        self.assertEqual(_tabelas(self.cursor), TABELAS_ATE_0013)
        self.assertFalse(self._tem_coluna())
        self.cursor.execute(
            "SELECT quality_rating FROM platform.tenant_channels WHERE id = %s",
            (canal,),
        )
        # **O `quality_rating` sobrevive**, e e o ponto: o estado corrente nao e
        # desta revisao. O que o `downgrade` perde e o historico.
        self.assertEqual(self.cursor.fetchone()[0], "RED")

        alembic_ok("upgrade", "head")
        self.assertEqual(_tabelas(self.cursor), TABELAS)
        self.assertTrue(self._tem_coluna())
        # E o historico nao voltou: a tabela e nova.
        self.cursor.execute(
            "SELECT count(*) FROM platform.channel_quality_log WHERE tenant_id = %s",
            (tenant,),
        )
        self.assertEqual(self.cursor.fetchone()[0], 0)
        # E o tecto tambem nao: a coluna e nova e a omissao e a dela.
        self.cursor.execute(
            "SELECT max_phone_numbers_per_business FROM platform.tenant_channels "
            "WHERE id = %s",
            (canal,),
        )
        self.assertIsNone(self.cursor.fetchone()[0])


class TestParidadeDosDominios(unittest.TestCase):
    """As listas de TypeScript e os dominios do DDL dizem o mesmo.

    **Esta classe existe porque o `docstring` do modulo prometia um teste que
    nao havia.** O `qualidade/contrato.ts` diz «ha um teste que compara as tres
    listas» — o `DESTINO_POR_KIND` do KAM-013, o `CHECK` da `0014` e o
    `EVENTOS_DE_CANAL` do modulo —, e o que existia comparava **duas**: as duas
    de TypeScript. A terceira, que e o `CHECK`, nao era confrontada com
    nenhuma. Apanhado pela revisao adversarial do proprio ticket, e e a classe
    de defeito mais barata de deixar passar: a prosa afirma a garantia e
    ninguem vai ver.

    Compara como **texto**, que e a unica coisa que um teste em Python pode
    afirmar sobre uma constante de TypeScript. E a forma do `TestTarifas` do
    `db/tests_outbound/test_outbound.py`, e a razao de haver duas fontes e a
    mesma: nao ha leitor de TypeScript em Python e nao ha leitor de YAML em
    `packages/core-ts`.

    **Os dominios leem-se das revisoes e nao se copiam para aqui**, pela mesma
    razao que o `TestTarifas` le o YAML em vez de o transcrever: um valor
    copiado faz a comparacao passar por construcao no dia em que a revisao
    mudar. Le-se o ficheiro da revisao como **texto**, que e o que o
    `test_eventos_schema.py` ja faz.

    **O que uma divergencia custava, por lista:**

    * `evento` — o `CHECK` recusava com `23514` um evento que o modulo manda
      registar, e o *webhook* passava a falhar para sempre (a Meta reenvia);
    * `motivo` — o `contar` do `metricas.ts` **levanta** `SufixoInvalidoError`
      num sufixo fora da lista. Um motivo novo no `CHECK` da `0013` sem entrada
      no `MOTIVOS` fazia o caminho da restricao **rebentar**, e o que se perdia
      nao era a metrica: era a restricao;
    * `rating` — o `quality_rating` aceitaria um valor que a metrica recusa, e a
      serie do *gauge* ficava sem a linha dele.
    """

    #: `NOME = ("'a'", "'b'")` numa revisao -> `["a", "b"]`.
    PADRAO = r"^{nome} = \(([^)]*)\)"

    @classmethod
    def setUpClass(cls) -> None:
        raiz = pathlib.Path(__file__).resolve().parents[2]
        versoes = raiz / "db" / "migrations" / "versions"
        cls.rev = {
            "0010": (versoes / "0010_saida_de_canal.py").read_text(encoding="utf-8"),
            "0013": (versoes / "0013_restricao_de_canal.py").read_text(
                encoding="utf-8"
            ),
            "0014": (versoes / "0014_qualidade_de_canal.py").read_text(
                encoding="utf-8"
            ),
        }
        qualidade = raiz / "packages" / "core-ts" / "src" / "qualidade"
        cls.ts_contrato = (qualidade / "contrato.ts").read_text(encoding="utf-8")
        cls.ts_metricas = (qualidade / "metricas.ts").read_text(encoding="utf-8")

    def _dominio(self, revisao: str, nome: str) -> list[str]:
        """O dominio que uma revisao declara, sem as plicas do SQL."""
        achado = re.search(
            self.PADRAO.format(nome=nome), self.rev[revisao], re.M | re.S
        )
        self.assertIsNotNone(achado, f"{nome} nao esta na revisao {revisao}")
        assert achado is not None  # para o verificador de tipos
        bruto = achado.group(1)
        return [
            parte.strip().strip(",").strip().strip("'\"").strip("'")
            for parte in bruto.replace("\n", " ").split(",")
            if parte.strip()
        ]

    def test_os_quatro_eventos_do_check_estao_no_modulo(self) -> None:
        esperados = self._dominio("0014", "EVENTOS_DE_QUALIDADE")
        self.assertEqual(len(esperados), 4, esperados)
        # Compara-se o **bloco inteiro** e nao cada valor, para que um quinto na
        # lista de TypeScript tambem falhe: uma lista que cresce de um lado so e
        # tao divergente como uma que encolhe.
        bloco = "export const EVENTOS_DE_CANAL = [\n" + "".join(
            f'  "{e}",\n' for e in esperados
        )
        self.assertIn(
            bloco,
            self.ts_contrato,
            "o EVENTOS_DE_CANAL nao e exactamente o dominio do "
            "channel_quality_log_evento_ck",
        )

    def test_os_tres_motivos_do_check_da_0013_estao_na_etiqueta(self) -> None:
        motivos = self._dominio("0013", "MOTIVOS_DE_RESTRICAO")
        self.assertEqual(len(motivos), 3, motivos)
        esperado = (
            "export const MOTIVOS = ["
            + ", ".join(f'"{m}"' for m in motivos)
            + "] as const;"
        )
        self.assertIn(
            esperado,
            self.ts_metricas,
            "o MOTIVOS da etiqueta nao e o dominio de "
            "tenant_channels.motivo_restricao: um motivo em falta faz o "
            "`contar` levantar, e o que se perde e a restricao",
        )

    def test_as_tres_qualidades_do_check_da_0010_estao_no_modulo(self) -> None:
        qualidades = self._dominio("0010", "QUALIDADES")
        self.assertEqual(len(qualidades), 3, qualidades)
        esperado = (
            "export const QUALIDADES = ["
            + ", ".join(f'"{q}"' for q in qualidades)
            + "] as const;"
        )
        self.assertIn(esperado, self.ts_contrato)


if __name__ == "__main__":
    unittest.main()
