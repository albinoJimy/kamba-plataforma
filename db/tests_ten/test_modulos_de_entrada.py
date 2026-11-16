"""Os modulos de entrada no TEN (KAM-124, criterios 1 e 2).

O KAM-009 provou a regra com o `msgs_ai_mes`. O KAM-124 pede-a **para os
modulos de entrada**, e e isso que este ficheiro prova, contra a base e pelas
mesmas funcoes da biblioteca e da `0007`:

1. **A matriz 4 x 4** (criterio 1): um tenant so com `foto` e negado em
   `catalogo`, `social` e `orcamento`, com `403 ENTITLEMENT_DISABLED`; e o
   mesmo para cada um dos quatro modulos, um tenant por linha da matriz.
2. **Mil trabalhos paralelos contra `imagens_mes = 100` aceitam exactamente
   cem** (criterio 2), em ligacoes concorrentes, como no KAM-009.
3. **Dez repeticoes da mesma `idempotencyKey` consomem uma**, nos tres
   contadores (`imagens_mes`, `posts_mes`, `orcamentos_mes`).
4. **O mes fecha as 00:00 de Africa/Luanda**, nos tres contadores, com o
   instante que distingue Luanda de UTC.

Os modulos e os contadores estao **por extenso** e nao importados do
`kamba_core.modulos`: um oraculo importado do alvo muda com ele.
"""

from __future__ import annotations

import concurrent.futures
import unittest

import ligacao
from tests import factories
from tests.base import ComBase
from tests_ten.base import ComUso, consumir

MODULOS = ("catalogo", "foto", "social", "orcamento")
CONTADORES = ("imagens_mes", "posts_mes", "orcamentos_mes")

#: Os numeros do criterio 2. Nao sao folga.
CHAMADAS = 1000
LIMITE = 100
LIGACOES = 32

#: O instante que esta em Novembro em UTC e em Dezembro em Luanda.
VIRAGEM_EM_UTC = "2026-11-30T23:30:00+00:00"
ANTES_DA_VIRAGEM = "2026-11-30T22:59:59+00:00"


def _kamba_core():  # type: ignore[no-untyped-def]
    import sys
    from pathlib import Path

    nucleo = str(Path(__file__).resolve().parents[2] / "libs" / "py-core" / "src")
    if nucleo not in sys.path:
        sys.path.insert(0, nucleo)
    from kamba_core.ten import entitlements

    return entitlements


class _Bd:
    """O `ClienteSql` do `kamba_core.ten` sobre um cursor do pg8000."""

    def __init__(self, cursor) -> None:  # type: ignore[no-untyped-def]
        self.cursor = cursor

    def executar(self, sql: str, parametros=()):  # type: ignore[no-untyped-def]
        entitlements = _kamba_core()
        self.cursor.execute(sql, tuple(parametros))
        nomes = [d[0] for d in self.cursor.description]
        return entitlements.Resultado(linhas=[dict(zip(nomes, l)) for l in self.cursor.fetchall()])


class TestMatriz(ComBase):
    """A matriz numa transaccao de administrador que **nunca confirma**.

    O `SQL_ENTITLEMENT` nega um tenant `onboarding` (a omissao da `0001`) em
    qualquer modulo, e um tenant `ativo` exige o aceite dos quatro documentos
    (revisao `0040`) — que e so de acrescentar e nao se limpa. Por isso nada
    disto se confirma: o tenant, o aceite e o entitlement vivem na transaccao,
    e a aplicacao mede-se nela por `SET LOCAL ROLE kamba_app`.
    """

    def setUp(self) -> None:
        super().setUp()
        self.cursor = self.ligar("admin").cursor()

    def tenant_activo(self, modulo: str, limites: dict, ativo: bool = True) -> str:
        self.cursor.execute("RESET ROLE")
        tenant = factories.tenant(self.cursor)
        factories.aceitar_contratos_vigentes(self.cursor, tenant)
        self.cursor.execute("UPDATE platform.tenants SET estado = 'ativo' WHERE id = %s", (tenant,))
        factories.entitlement(self.cursor, tenant, modulo=modulo, limites=limites, ativo=ativo)
        self.cursor.execute("SET LOCAL ROLE kamba_app")
        factories.contexto(self.cursor, tenant)
        return tenant

    def test_a_matriz_quatro_por_quatro(self) -> None:
        """Criterio 1: um modulo activo por tenant, e os quatro perguntados a cada um."""
        entitlements = _kamba_core()
        for activo in MODULOS:
            tenant = self.tenant_activo(activo, {"custo_max_mes_micro_usd": 1})
            bd = _Bd(self.cursor)
            for pedido in MODULOS:
                with self.subTest(activo=activo, pedido=pedido):
                    decisao = entitlements.check_entitlement(bd, tenant, pedido)
                    self.assertEqual(decisao.permitido, pedido == activo)
                    if pedido != activo:
                        self.assertEqual(decisao.motivo, "sem_entitlement")
        self.assertEqual(
            (entitlements.HTTP_ENTITLEMENT, entitlements.CODIGO_ENTITLEMENT_HTTP),
            (403, "ENTITLEMENT_DISABLED"),
        )

    def test_so_com_foto_e_negado_em_social_e_orcamento(self) -> None:
        """A frase do criterio, a letra."""
        entitlements = _kamba_core()
        tenant = self.tenant_activo("foto", {"imagens_mes": 40})
        bd = _Bd(self.cursor)
        self.assertTrue(entitlements.check_entitlement(bd, tenant, "foto").permitido)
        for modulo in ("social", "orcamento"):
            with self.subTest(modulo=modulo):
                self.assertFalse(entitlements.check_entitlement(bd, tenant, modulo).permitido)

    def test_um_modulo_inactivo_e_negado(self) -> None:
        entitlements = _kamba_core()
        tenant = self.tenant_activo("foto", {"imagens_mes": 40}, ativo=False)
        decisao = entitlements.check_entitlement(_Bd(self.cursor), tenant, "foto")
        self.assertEqual((decisao.permitido, decisao.motivo), (False, "entitlement_inactivo"))


class TestIdempotenciaEMes(ComUso):
    def test_dez_repeticoes_consomem_uma_nos_tres_contadores(self) -> None:
        for chave in CONTADORES:
            with self.subTest(chave=chave):
                tenant = self.tenant_com_limite(10, chave=chave)
                resultados = [
                    self.consumir(tenant, chave=chave, quantidade=1, idempotency_key="mesma")
                    for _ in range(10)
                ]
                self.assertEqual([r.aceite for r in resultados], [True] * 10)
                self.assertEqual([r.repetido for r in resultados], [False] + [True] * 9)
                self.assertEqual({int(r.valor) for r in resultados}, {1})

    def test_o_mes_fecha_a_meia_noite_de_luanda_nos_tres_contadores(self) -> None:
        for chave in CONTADORES:
            with self.subTest(chave=chave):
                tenant = self.tenant_com_limite(1, chave=chave)
                antes = self.consumir(tenant, chave=chave, quantidade=1, idempotency_key="a",
                                      agora=ANTES_DA_VIRAGEM, papel="batch")
                depois = self.consumir(tenant, chave=chave, quantidade=1, idempotency_key="b",
                                       agora=VIRAGEM_EM_UTC, papel="batch")
                # Tecto 1 por mes: as duas cabem porque sao de meses diferentes.
                self.assertEqual((antes.aceite, depois.aceite), (True, True))
                self.semente.execute(
                    "SELECT periodo::text FROM platform.tenant_usage WHERE tenant_id = %s "
                    "AND chave_limite = %s ORDER BY periodo",
                    (tenant, chave),
                )
                self.assertEqual([l[0] for l in self.semente.fetchall()], ["2026-11-01", "2026-12-01"])


class TestMilImagensParalelas(ComBase):
    """Criterio 2: «1.000 trabalhos paralelos contra `imagens_mes=100` aceitam exactamente 100»."""

    @classmethod
    def setUpClass(cls) -> None:
        super().setUpClass()
        cls._admin = ligacao.ligar("admin")
        cls._admin.autocommit = True
        semente = cls._admin.cursor()
        cls.tenant = factories.tenant(semente)
        factories.entitlement(semente, cls.tenant, modulo="foto", limites={"imagens_mes": LIMITE})
        cls.resultados, cls.erros = [], []
        with concurrent.futures.ThreadPoolExecutor(max_workers=LIGACOES) as piscina:
            for tarefa in concurrent.futures.as_completed(
                [piscina.submit(cls._consumir, n) for n in range(CHAMADAS)]
            ):
                consumo, erro = tarefa.result()
                (cls.erros.append(erro) if erro else cls.resultados.append(consumo))

    @classmethod
    def _consumir(cls, n: int):  # type: ignore[no-untyped-def]
        conexao = ligacao.ligar("app")
        try:
            cursor = conexao.cursor()
            cursor.execute("SELECT set_config('app.tenant_id', %s, true)", (cls.tenant,))
            cursor.fetchone()
            consumo = consumir(cursor, cls.tenant, chave="imagens_mes", quantidade=1,
                               idempotency_key=f"foto:paralela-{n}")
            conexao.commit()
            return consumo, None
        except Exception as erro:  # noqa: BLE001
            return None, f"{type(erro).__name__}: {erro}"
        finally:
            conexao.close()

    @classmethod
    def tearDownClass(cls) -> None:
        cursor = cls._admin.cursor()
        for tabela in ("usage_ledger", "tenant_usage", "entitlements"):
            cursor.execute(f"DELETE FROM platform.{tabela} WHERE tenant_id = %s", (cls.tenant,))
        cursor.execute("DELETE FROM platform.tenants WHERE id = %s", (cls.tenant,))
        cls._admin.close()
        super().tearDownClass()

    def test_aceitam_exactamente_cem_e_nenhuma_falha(self) -> None:
        self.assertEqual(self.erros[:5], [], f"{len(self.erros)} falha(s)")
        self.assertEqual(sum(1 for r in self.resultados if r.aceite), LIMITE)
        self.assertEqual(sum(1 for r in self.resultados if not r.aceite), CHAMADAS - LIMITE)
        self.assertEqual(sorted(int(r.valor) for r in self.resultados if r.aceite), list(range(1, LIMITE + 1)))


if __name__ == "__main__":
    unittest.main()
