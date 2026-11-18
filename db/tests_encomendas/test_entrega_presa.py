"""A entrega presa ao actor e ao instante (KAM-204, revisao `0071`).

```text
papel      dono com cliente -> 23514; dono com dono -> entra; ops -> 23514;
           agente com cliente e a janela aberta -> entra; sem ela -> 23514
instante   o entregue_at que a aplicacao mande e ignorado: fica o now() da
           transaccao
imutavel   fora de uma entrega, mudar uma das duas colunas -> recusado, ao
           kamba_app (42501 no instante, 23514 no papel) e ao administrador
disputa    o fim de uma disputa mantem o instante e o papel da entrega
descida    a 0071 desce e sobe, e a base fica na anterior
```

Os ensaios escrevem pela ligacao **transaccional** e confirmam: e no `COMMIT`
que o `order_entrega_exige_papel` corre, como o `order_estado_exige_log`.
"""

from __future__ import annotations

import importlib.util
import unittest
from pathlib import Path

import bootstrap
import ligacao
import pg8000.dbapi
from tests.base import alembic_ok, em_head, exigir_base_descartavel, sqlstate
from tests_encomendas.base import ENTREGA_RECUSADA, ComEncomendas

#: O ficheiro da revisao, pelo *glob*: o numero e da integracao.
REVISAO = next(
    (Path(__file__).resolve().parents[1] / "migrations" / "versions").glob(
        "*_entrega_presa_ao_actor.py"
    )
)
SEM_PRIVILEGIO = "42501"


def _revisao():
    spec = importlib.util.spec_from_file_location("revisao_entrega_presa", REVISAO)
    assert spec is not None and spec.loader is not None
    modulo = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(modulo)
    return modulo


_MODULO = _revisao()
ESTA = str(_MODULO.revision)
ANTERIOR = str(_MODULO.down_revision)


class _ComPaga(ComEncomendas):
    def paga(self) -> tuple[str, str, int]:
        tenant = self.criar_tenant()
        encomenda = self.criar_encomenda(tenant)
        return tenant, encomenda, self.levar_a(tenant, encomenda, "paga")

    def ler(self, encomenda: str) -> tuple:
        self.semente.execute(
            "SELECT estado, entregue_at, entrega_confirmada_por "
            "  FROM platform.orders_mirror WHERE id = %s",
            (encomenda,),
        )
        return tuple(self.semente.fetchone())


class TestOPapelFicaPresoAoActor(_ComPaga):
    """Criterio 1: o `entrega_confirmada_por` e o que o actor pode declarar."""

    def test_um_dono_nao_declara_cliente(self) -> None:
        tenant, encomenda, versao = self.paga()
        self.assertEqual(
            self.tentar_transicao(
                tenant, encomenda, "paga", "entregue", versao, "levantamento",
                actor_kind="dono", actor_id="dono-1", papel="cliente",
            ),
            ENTREGA_RECUSADA,
            "um dono que marque `cliente` subia a confianca gradual com uma "
            "venda que ninguem confirmou",
        )
        self.assertEqual(self.ler(encomenda)[0], "paga")

    def test_um_dono_declara_dono(self) -> None:
        tenant, encomenda, versao = self.paga()
        self.transitar(
            tenant, encomenda, "paga", "entregue", versao, "levantamento",
            actor_kind="dono", actor_id="dono-1",
        )
        self.assertEqual(self.ler(encomenda)[0::2], ("entregue", "dono"))

    def test_ops_nao_declara_papel_nenhum(self) -> None:
        for papel in ("cliente", "dono", "estafeta"):
            with self.subTest(papel=papel):
                tenant, encomenda, versao = self.paga()
                self.assertEqual(
                    self.tentar_transicao(
                        tenant, encomenda, "paga", "entregue", versao, "levantamento",
                        actor_kind="ops", actor_id="ops-1", papel=papel,
                    ),
                    ENTREGA_RECUSADA,
                )

    def test_o_agente_declara_cliente_com_a_janela_aberta(self) -> None:
        tenant, encomenda, versao = self.paga()
        self.transitar(
            tenant, encomenda, "paga", "entregue", versao, "levantamento",
            actor_kind="agente", actor_id="grafo-vendedor",
        )
        self.assertEqual(self.ler(encomenda)[0::2], ("entregue", "cliente"))

    def test_o_agente_sem_a_janela_do_contacto_e_recusado(self) -> None:
        tenant, encomenda, versao = self.paga()
        self.assertEqual(
            self.tentar_transicao(
                tenant, encomenda, "paga", "entregue", versao, "levantamento",
                actor_kind="agente", actor_id="grafo-vendedor", janela=False,
            ),
            ENTREGA_RECUSADA,
        )

    def test_a_janela_de_outro_contacto_nao_serve(self) -> None:
        tenant, encomenda, versao = self.paga()
        outra = self.criar_encomenda(tenant)
        self.abrir_janela(tenant, outra)
        self.assertEqual(
            self.tentar_transicao(
                tenant, encomenda, "paga", "entregue", versao, "levantamento",
                actor_kind="agente", actor_id="grafo-vendedor", janela=False,
            ),
            ENTREGA_RECUSADA,
        )

    def test_a_janela_fechada_nao_serve(self) -> None:
        tenant, encomenda, versao = self.paga()
        self.abrir_janela(tenant, encomenda)
        self.semente.execute(
            "UPDATE platform.conversations "
            "   SET last_inbound_at = now() - interval '25 hours', "
            "       window_expires_at = now() - interval '1 hour' "
            " WHERE tenant_id = %s",
            (tenant,),
        )
        self.assertEqual(
            self.tentar_transicao(
                tenant, encomenda, "paga", "entregue", versao, "levantamento",
                actor_kind="agente", actor_id="grafo-vendedor", janela=False,
            ),
            ENTREGA_RECUSADA,
        )


class TestOInstanteEDaTransaccao(_ComPaga):
    """Criterio 2: o `entregue_at` e o `now()` da transaccao."""

    def test_um_instante_no_passado_vindo_da_aplicacao_e_ignorado(self) -> None:
        tenant, encomenda, versao = self.paga()
        self.ensaio.execute("SELECT now()")
        instante = self.ensaio.fetchone()[0]
        self.ensaio.execute(
            "UPDATE platform.orders_mirror "
            "   SET estado = 'entregue', version = version + 1, "
            "       entregue_at = '2020-01-01T00:00:00Z', "
            "       entrega_confirmada_por = 'dono' "
            " WHERE tenant_id = %s AND id = %s RETURNING version",
            (tenant, encomenda),
        )
        nova = int(self.ensaio.fetchone()[0])
        self.ensaio.execute(
            "INSERT INTO platform.order_state_log "
            "       (tenant_id, order_id, de, para, version, causa, actor_kind, actor_id) "
            "VALUES (%s, %s, 'paga', 'entregue', %s, 'levantamento', 'dono', 'dono-1')",
            (tenant, encomenda, nova),
        )
        self._ensaio.commit()
        self.assertEqual(self.ler(encomenda)[1], instante)

    def test_uma_encomenda_nao_nasce_com_entrega(self) -> None:
        tenant = self.criar_tenant()
        for coluna, valor in (("entregue_at", "2026-11-01T00:00:00Z"),
                              ("entrega_confirmada_por", "cliente")):
            with self.subTest(coluna=coluna):
                with self.assertRaises(pg8000.dbapi.DatabaseError) as erro:
                    self.criar_encomenda(tenant, **{coluna: valor})
                self.assertEqual(sqlstate(erro.exception), ENTREGA_RECUSADA)


class TestDepoisDeGravadosNaoSeMudam(_ComPaga):
    """Criterio 3: fora de uma entrega, as duas colunas nao mudam."""

    def entregue(self) -> tuple[str, str]:
        tenant, encomenda, versao = self.paga()
        self.transitar(
            tenant, encomenda, "paga", "entregue", versao, "levantamento",
            actor_kind="dono", actor_id="dono-1",
        )
        return tenant, encomenda

    def como_app(self, tenant: str, sql: str, parametros: tuple) -> str | None:
        conexao = ligacao.ligar("app")
        try:
            cursor = conexao.cursor()
            cursor.execute("SELECT set_config('app.tenant_id', %s, true)", (tenant,))
            cursor.fetchone()
            cursor.execute(sql, parametros)
            conexao.commit()
            return None
        except pg8000.dbapi.DatabaseError as erro:
            conexao.rollback()
            return sqlstate(erro)
        finally:
            conexao.close()

    def test_o_kamba_app_nao_escreve_o_instante(self) -> None:
        tenant, encomenda = self.entregue()
        self.assertEqual(
            self.como_app(
                tenant,
                "UPDATE platform.orders_mirror SET entregue_at = now() - interval '20 days' "
                " WHERE tenant_id = %s AND id = %s",
                (tenant, encomenda),
            ),
            SEM_PRIVILEGIO,
        )

    def test_o_kamba_app_nao_muda_o_papel(self) -> None:
        tenant, encomenda = self.entregue()
        self.assertEqual(
            self.como_app(
                tenant,
                "UPDATE platform.orders_mirror SET entrega_confirmada_por = 'cliente' "
                " WHERE tenant_id = %s AND id = %s",
                (tenant, encomenda),
            ),
            ENTREGA_RECUSADA,
        )
        self.assertEqual(self.ler(encomenda)[2], "dono")

    def test_nem_o_administrador_muda_qualquer_das_duas(self) -> None:
        tenant, encomenda = self.entregue()
        for sql in (
            "UPDATE platform.orders_mirror SET entregue_at = now() - interval '20 days' "
            " WHERE tenant_id = %s AND id = %s",
            "UPDATE platform.orders_mirror SET entrega_confirmada_por = 'cliente' "
            " WHERE tenant_id = %s AND id = %s",
        ):
            with self.subTest(sql=sql):
                self.assertEqual(self.tentar(sql, (tenant, encomenda)), ENTREGA_RECUSADA)

    def test_antes_da_entrega_tambem_nao(self) -> None:
        tenant, encomenda, _ = self.paga()
        self.assertEqual(
            self.tentar(
                "UPDATE platform.orders_mirror SET entrega_confirmada_por = 'cliente' "
                " WHERE tenant_id = %s AND id = %s",
                (tenant, encomenda),
            ),
            ENTREGA_RECUSADA,
        )


class TestOFimDeUmaDisputaMantemAEntrega(_ComPaga):
    """KAM-050: `em_disputa -> entregue` nao e uma entrega nova."""

    def test_o_instante_e_o_papel_ficam_os_da_entrega(self) -> None:
        tenant, encomenda, versao = self.paga()
        versao = self.transitar(
            tenant, encomenda, "paga", "entregue", versao, "levantamento",
            actor_kind="agente", actor_id="grafo-vendedor",
        )
        self.recuar_entrega(tenant, encomenda, "3 days")
        _, entrega, papel = self.ler(encomenda)
        versao = self.transitar(tenant, encomenda, "entregue", "em_disputa", versao, "reclamacao")
        # O ops decide, e manda outro papel e outro instante: os dois sao ignorados.
        self.ensaio.execute(
            "UPDATE platform.orders_mirror "
            "   SET estado = 'entregue', version = version + 1, "
            "       entregue_at = now(), entrega_confirmada_por = 'dono' "
            " WHERE tenant_id = %s AND id = %s RETURNING version",
            (tenant, encomenda),
        )
        nova = int(self.ensaio.fetchone()[0])
        self.ensaio.execute(
            "INSERT INTO platform.order_state_log "
            "       (tenant_id, order_id, de, para, version, causa, actor_kind, actor_id) "
            "VALUES (%s, %s, 'em_disputa', 'entregue', %s, 'disputa_recusada', 'ops', 'ops-1')",
            (tenant, encomenda, nova),
        )
        self._ensaio.commit()
        self.assertEqual(self.ler(encomenda), ("entregue", entrega, papel))
        self.assertEqual(papel, "cliente")


class TestDowngradeDaEntregaPresa(unittest.TestCase):
    """A descida tira as duas barreiras e devolve o privilegio; a subida repoe.

    Afirma a revisao em que a base fica, e nao a `head`: com outra revisao por
    cima, o alembic desce primeiro essa (licao do KAM-089).
    """

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

    def tearDown(self) -> None:
        try:
            if not em_head():
                alembic_ok("upgrade", "head")
        finally:
            self.conexao.close()

    def _um(self, sql: str) -> object:
        self.cursor.execute(sql)
        return self.cursor.fetchone()[0]

    def estado(self) -> dict[str, object]:
        return {
            "triggers": self._um(
                "SELECT count(*) FROM pg_trigger "
                " WHERE tgrelid = 'platform.orders_mirror'::regclass "
                "   AND tgname IN ('order_entrega_presa', 'order_entrega_exige_papel')"
            ),
            "funcoes": self._um(
                "SELECT count(*) FROM pg_proc p "
                "  JOIN pg_namespace n ON n.oid = p.pronamespace "
                " WHERE n.nspname = 'platform' "
                "   AND p.proname IN ('order_entrega_presa', 'order_entrega_exige_papel')"
            ),
            "app_escreve_o_instante": self._um(
                "SELECT has_column_privilege('kamba_app', 'platform.orders_mirror', "
                "       'entregue_at', 'UPDATE')"
            ),
        }

    def test_desce_e_sobe(self) -> None:
        self.assertEqual(
            self.estado(),
            {"triggers": 2, "funcoes": 2, "app_escreve_o_instante": False},
        )
        alembic_ok("downgrade", ANTERIOR)
        self.assertEqual(self._um("SELECT version_num FROM public.alembic_version"), ANTERIOR)
        self.assertEqual(
            self.estado(),
            {"triggers": 0, "funcoes": 0, "app_escreve_o_instante": True},
        )
        alembic_ok("upgrade", ESTA)
        self.assertEqual(
            self.estado(),
            {"triggers": 2, "funcoes": 2, "app_escreve_o_instante": False},
        )


if __name__ == "__main__":  # pragma: no cover
    unittest.main()
