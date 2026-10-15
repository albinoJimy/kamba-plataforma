"""Gate 8: a guarda de arranque do Piloto contra dados reais, com RLS activa.

Criterio de aceitacao 7 do KAM-003: «Com `KAMBA_FASE=piloto` o arranque do
CHR/AGR falha se existir linha com `tenants.tipo='platform'`,
`tenant_channels.origem='plataforma'` ou `vertical='assistente'`.»

Desde o KAM-004 as tabelas tem RLS `FORCE`, e isso decide com que papel a
guarda corre:

    kamba_resolver   **e o papel da guarda.** Tem uma politica de leitura
                     propria e ve todas as linhas, so nas colunas de que precisa.
    kamba_app        sem contexto de tenant ve zero linhas. A guarda **recusa
                     correr** (`GuardaCega`) em vez de contar zero e arrancar.
    kamba_batch      contorna a RLS e tambem pode, mas os servicos nao recebem
                     as suas credenciais para arrancar.

Os dados semeiam-se como `kamba_batch` e **confirmam-se**: a guarda le noutra
ligacao, com outro papel, e nao veria linhas por confirmar. Cada teste apaga o
que semeou.

O que isto prova e o que **nao** prova: prova que a guarda recusa cada condicao
e que nao se deixa cegar; **nao** prova que um servico a chama. O CHR nasce no
KAM-014 e o AGR ainda nao abre ligacao a base.
"""

from __future__ import annotations

import contextlib
import sys
from pathlib import Path

import ligacao
from tests import factories
from tests.base import ComBase

sys.path.insert(0, str(Path(__file__).resolve().parents[2] / "libs" / "py-core" / "src"))

from kamba_core.fluxo_piloto import (  # noqa: E402
    FaseNaoDefinida,
    FluxoBNoPiloto,
    GuardaCega,
    verificar_arranque,
)

PILOTO = {"KAMBA_FASE": "piloto"}


class _ComSementes(ComBase):
    """Semeia como `kamba_batch`, confirmado; apaga tudo no fim."""

    def setUp(self) -> None:
        super().setUp()
        self._batch = ligacao.ligar("batch")
        self._batch.autocommit = True
        self._cursor_batch = self._batch.cursor()
        self._cursor_batch.execute("SET lock_timeout = '15s'")
        self._semeados: list[str] = []

    def tearDown(self) -> None:
        # Primeiro fecham-se as ligacoes do teste, e so depois se limpa: uma
        # ligacao com a transaccao aberta segura a tabela, e foi essa ordem
        # trocada que pendurou o gate dez minutos na revisao do KAM-003.
        super().tearDown()
        self._conexoes = []
        for tenant in self._semeados:
            self._cursor_batch.execute(
                "DELETE FROM platform.entitlements WHERE tenant_id = %s", (tenant,)
            )
            self._cursor_batch.execute(
                "DELETE FROM platform.tenant_channels WHERE tenant_id = %s", (tenant,)
            )
            self._cursor_batch.execute(
                "DELETE FROM platform.tenants WHERE id = %s", (tenant,)
            )
        self._batch.close()

    def semear_tenant(self, **campos) -> str:
        tenant = factories.tenant(self._cursor_batch, **campos)
        self._semeados.append(tenant)
        return tenant

    def semear_canal(self, tenant: str, **campos) -> str:
        return factories.canal(self._cursor_batch, tenant, **campos)

    def guarda(self, identidade: str = "resolver", ambiente=None) -> None:
        return verificar_arranque(
            self.ligar(identidade), PILOTO if ambiente is None else ambiente
        )


class TestGuardaDeArranque(_ComSementes):
    def test_base_so_com_fluxo_a_arranca(self) -> None:
        tenant = self.semear_tenant(tipo="pme")
        self.semear_canal(tenant, origem="pme", vertical="vendedor")
        self.semear_canal(tenant, origem="pme", vertical="servicos")
        self.assertIsNone(self.guarda())

    def test_tenant_de_tipo_platform_recusa_o_arranque(self) -> None:
        self.semear_tenant(tipo="platform")
        with self.assertRaises(FluxoBNoPiloto) as capturado:
            self.guarda()
        self.assertIn("tenants.tipo = 'platform'", str(capturado.exception))

    def test_canal_de_origem_plataforma_recusa_o_arranque(self) -> None:
        tenant = self.semear_tenant()
        self.semear_canal(tenant, origem="plataforma")
        with self.assertRaises(FluxoBNoPiloto) as capturado:
            self.guarda()
        self.assertIn("origem = 'plataforma'", str(capturado.exception))

    def test_vertical_assistente_recusa_o_arranque(self) -> None:
        tenant = self.semear_tenant()
        self.semear_canal(tenant, vertical="assistente")
        with self.assertRaises(FluxoBNoPiloto) as capturado:
            self.guarda()
        self.assertIn("'assistente'", str(capturado.exception))

    def test_qualquer_vertical_fora_das_de_atendimento_recusa(self) -> None:
        """Lista de permitidas: uma igualdade com `assistente` nao via estas."""
        for vertical in ("assistente_v2", "assistente2", "catalogo", "social", "x"):
            with self.subTest(vertical=vertical):
                tenant = self.semear_tenant()
                canal = self.semear_canal(tenant, vertical=vertical)
                with self.assertRaises(FluxoBNoPiloto):
                    self.guarda()
                self._cursor_batch.execute(
                    "UPDATE platform.tenant_channels SET vertical = 'vendedor' "
                    "WHERE id = %s",
                    (canal,),
                )

    def test_um_tenant_platform_encerrado_tambem_conta(self) -> None:
        """O criterio diz «se existir linha»: o estado nao a torna aceitavel."""
        self.semear_tenant(tipo="platform", estado="encerrado")
        with self.assertRaises(FluxoBNoPiloto):
            self.guarda()

    def test_sem_a_variavel_nao_arranca_mesmo_com_a_base_limpa(self) -> None:
        for ambiente in ({}, {"KAMBA_FASE": "clusters"}):
            with self.subTest(ambiente=ambiente):
                with self.assertRaises(FaseNaoDefinida):
                    self.guarda(ambiente=ambiente)


class TestGuardaComRls(_ComSementes):
    """A guarda nao se deixa cegar pela RLS — agora com a RLS real, nao ensaiada.

    Na revisao adversarial do KAM-003 isto era um ensaio: ligava-se a RLS a mao
    numa tabela para mostrar que a guarda ficaria cega. Com a revisao 0002 e o
    estado normal da base.
    """

    def setUp(self) -> None:
        super().setUp()
        self.tenant = self.semear_tenant(tipo="platform")
        self.semear_canal(self.tenant, origem="plataforma", vertical="assistente")

    def test_a_premissa_kamba_app_sem_contexto_ve_zero_linhas(self) -> None:
        """Sem isto os testes seguintes nao provavam nada."""
        cursor = self.ligar("app").cursor()
        for tabela in ("tenants", "tenant_channels"):
            with self.subTest(tabela=tabela):
                cursor.execute(f"SELECT count(*) FROM platform.{tabela}")
                self.assertEqual(cursor.fetchone()[0], 0)

    def test_como_kamba_app_a_guarda_recusa_correr(self) -> None:
        with self.assertRaises(GuardaCega):
            self.guarda("app")

    def test_como_kamba_app_com_contexto_de_um_tenant_tambem_recusa(self) -> None:
        """Um contexto mostra um tenant, nao todos: continua a nao ver tudo."""
        conexao = self.ligar("app")
        factories.contexto(conexao.cursor(), self.tenant)
        with self.assertRaises(GuardaCega):
            verificar_arranque(conexao, PILOTO)

    def test_como_kamba_resolver_a_guarda_ve_e_recusa_o_arranque(self) -> None:
        with self.assertRaises(FluxoBNoPiloto) as capturado:
            self.guarda("resolver")
        mensagem = str(capturado.exception)
        self.assertIn("tipo = 'platform'", mensagem)
        self.assertIn("origem = 'plataforma'", mensagem)
        self.assertIn("'assistente'", mensagem)

    def test_como_kamba_batch_tambem_ve(self) -> None:
        with self.assertRaises(FluxoBNoPiloto):
            self.guarda("batch")

    @contextlib.contextmanager
    def _com_ddl(self, fazer: tuple[str, ...], desfazer: tuple[str, ...]):
        """Altera as politicas a serio (confirmado) e repoe-nas no fim.

        O `desfazer` corre depois de as ligacoes do teste largarem a tabela: uma
        transaccao aberta segura-a, e foi essa ordem trocada que pendurou o gate.
        """
        admin = ligacao.ligar("admin")
        admin.autocommit = True
        cursor = admin.cursor()
        cursor.execute("SET lock_timeout = '15s'")
        feitas = 0
        try:
            for instrucao in fazer:
                cursor.execute(instrucao)
                feitas += 1
            yield
        finally:
            for conexao in self._conexoes:
                conexao.rollback()
            if feitas == len(fazer):
                for instrucao in desfazer:
                    cursor.execute(instrucao)
            admin.close()

    RESOLVER_LEITURA = (
        "CREATE POLICY resolver_leitura ON platform.{tabela} "
        "FOR SELECT TO kamba_resolver USING (true)"
    )

    def test_uma_restritiva_de_leitura_para_o_resolvedor_cega_a_guarda(self) -> None:
        """A terceira via exige que nada estreite a leitura — em **cada** tabela.

        Uma politica `RESTRICTIVE` soma-se por E a permissiva do resolvedor: ele
        deixaria de ver tudo, e a guarda tem de dar por isso. Nas duas tabelas:
        a mutacao que so olhava para `tenant_channels` sobreviveu a revisao.
        """
        for tabela, coluna in (("tenant_channels", "origem"), ("tenants", "tipo")):
            with self.subTest(tabela=tabela):
                with self._com_ddl(
                    (
                        f"CREATE POLICY ensaio_restritiva ON platform.{tabela} "
                        f"AS RESTRICTIVE FOR SELECT TO kamba_resolver USING ({coluna} = 'pme')",
                    ),
                    (f"DROP POLICY ensaio_restritiva ON platform.{tabela}",),
                ):
                    with self.assertRaises(GuardaCega):
                        self.guarda("resolver")

    def test_uma_restritiva_para_public_ou_para_todos_os_comandos_tambem_cega(self) -> None:
        for alvo in ("FOR SELECT TO PUBLIC", "FOR ALL TO kamba_resolver", "FOR ALL TO PUBLIC"):
            with self.subTest(alvo=alvo):
                with self._com_ddl(
                    (
                        "CREATE POLICY ensaio_restritiva ON platform.tenants "
                        f"AS RESTRICTIVE {alvo} USING (tipo = 'pme')",
                    ),
                    ("DROP POLICY ensaio_restritiva ON platform.tenants",),
                ):
                    with self.assertRaises(GuardaCega):
                        self.guarda("resolver")

    def test_uma_restritiva_que_nao_toca_na_leitura_do_resolvedor_nao_cega(self) -> None:
        """De escrita, ou para outro papel: nao tira linhas ao resolvedor.

        Se cegasse, uma restritiva legitima sobre o `INSERT` de `kamba_app`
        impedia todos os servicos de arrancar — e o remedio a mao seria desligar
        a guarda.
        """
        for tabela, alvo in (
            ("tenant_channels", "FOR INSERT TO kamba_app WITH CHECK (origem = 'pme')"),
            ("tenants", "FOR UPDATE TO PUBLIC USING (tipo = 'pme')"),
            ("tenants", "FOR SELECT TO kamba_app USING (tipo = 'pme')"),
            ("tenant_channels", "FOR ALL TO kamba_batch USING (origem = 'pme')"),
        ):
            with self.subTest(tabela=tabela, alvo=alvo):
                with self._com_ddl(
                    (
                        f"CREATE POLICY ensaio_restritiva ON platform.{tabela} "
                        f"AS RESTRICTIVE {alvo}",
                    ),
                    (f"DROP POLICY ensaio_restritiva ON platform.{tabela}",),
                ):
                    # Ve tudo, e por isso chega as linhas de Fluxo B semeadas.
                    with self.assertRaises(FluxoBNoPiloto):
                        self.guarda("resolver")

    def test_sem_politica_de_leitura_numa_das_tabelas_a_guarda_e_cega(self) -> None:
        """Tem de a ter nas **duas**: com uma so, metade das condicoes contava zero."""
        for tabela in ("tenants", "tenant_channels"):
            with self.subTest(tabela=tabela):
                with self._com_ddl(
                    (f"DROP POLICY resolver_leitura ON platform.{tabela}",),
                    (self.RESOLVER_LEITURA.format(tabela=tabela),),
                ):
                    with self.assertRaises(GuardaCega):
                        self.guarda("resolver")

    def test_uma_politica_total_que_nao_e_de_leitura_nao_conta(self) -> None:
        """`USING (true)` para `UPDATE` nao deixa ler linha nenhuma."""
        for comando in ("UPDATE", "DELETE"):
            with self.subTest(comando=comando):
                with self._com_ddl(
                    (
                        "DROP POLICY resolver_leitura ON platform.tenants",
                        "CREATE POLICY ensaio_escrita ON platform.tenants "
                        f"FOR {comando} TO kamba_resolver USING (true)",
                    ),
                    (
                        "DROP POLICY ensaio_escrita ON platform.tenants",
                        self.RESOLVER_LEITURA.format(tabela="tenants"),
                    ),
                ):
                    with self.assertRaises(GuardaCega):
                        self.guarda("resolver")

    def test_uma_politica_de_leitura_parcial_nao_conta(self) -> None:
        """So `USING (true)` e leitura total; um predicado qualquer nao e."""
        with self._com_ddl(
            (
                "DROP POLICY resolver_leitura ON platform.tenants",
                "CREATE POLICY ensaio_parcial ON platform.tenants "
                "FOR SELECT TO kamba_resolver USING (tipo = 'pme')",
            ),
            (
                "DROP POLICY ensaio_parcial ON platform.tenants",
                self.RESOLVER_LEITURA.format(tabela="tenants"),
            ),
        ):
            with self.assertRaises(GuardaCega):
                self.guarda("resolver")
