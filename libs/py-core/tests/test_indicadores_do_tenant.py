"""Os indicadores do catalogo **por tenant**, lidos da base (KAM-231, criterio 5).

O duplo le o **texto** da instrucao e o tenant do contexto (`set_config`): um
duplo que devolvesse as linhas pelo argumento ficava verde com o predicado do
tenant apagado. O canario no fim apaga-o e ve o ensaio cair.
"""

from __future__ import annotations

import json
import unittest
from datetime import UTC, datetime, timedelta
from decimal import Decimal
from typing import Any

from kamba_core.catalogo import indicadores
from kamba_core.catalogo.indicadores import (
    SQL_INSTANTES_DO_TENANT,
    SQL_PUBLICADAS_DO_TENANT,
    ler_do_tenant,
)

A = "11111111-1111-4111-8111-111111111111"
B = "22222222-2222-4222-8222-222222222222"
T0 = datetime(2026, 11, 20, 9, 0, tzinfo=UTC)


def _campo(valor: str, *, fonte: str = "ia_visao", corrigido: bool = False) -> dict[str, Any]:
    return {"valor": valor, "confianca": "0.9", "fonte": fonte, "confirmado": True, "corrigido": corrigido}


def _linha(
    tenant: str,
    n: int,
    *,
    estado: str = "publicada",
    criado: datetime,
    confirmado: datetime | None = None,
    custo: str = "0.004",
    corrigido: bool = False,
) -> dict[str, Any]:
    campos = {"nome": _campo("Sumo 999", corrigido=corrigido), "preco": _campo("1500", fonte="dono_texto")}
    return {
        "tenant_id": tenant,
        "estado": estado,
        "criado_at": criado,
        "confirmado_at": confirmado,
        "colunas": (
            f"{n:08d}-0000-4000-8000-000000000000", tenant, f"{tenant}/catalogo/{n}", f"999{n}", estado,
            None, json.dumps(campos), [], 1, None, f"PRD-{n}" if estado == "publicada" else None,
            Decimal(custo), confirmado, "dono" if confirmado else None, None, 1,
        ),
    }


class _Cursor:
    def __init__(self, base: _Base) -> None:
        self.base = base
        self._resultado: list[tuple[Any, ...]] = []

    def execute(self, sql: str, parametros: tuple[Any, ...] = ()) -> None:
        self._resultado = self.base.responder(sql, tuple(parametros))

    def fetchone(self) -> tuple[Any, ...] | None:
        return self._resultado[0] if self._resultado else None

    def fetchall(self) -> list[tuple[Any, ...]]:
        return list(self._resultado)

    def close(self) -> None:
        return None


class _Base:
    autocommit = False

    def __init__(self, linhas: list[dict[str, Any]], *, rls: bool = True) -> None:
        self.linhas = linhas
        self.rls = rls
        self.contexto: str | None = None

    def cursor(self) -> _Cursor:
        return _Cursor(self)

    def commit(self) -> None:
        return None

    def rollback(self) -> None:
        return None

    def responder(self, sql: str, p: tuple[Any, ...]) -> list[tuple[Any, ...]]:
        if "set_config" in sql:
            self.contexto = str(p[0])
            return [(self.contexto,)]
        # A RLS: so as linhas do tenant do contexto existem.
        visiveis = [l for l in self.linhas if not self.rls or l["tenant_id"] == self.contexto]
        # O predicado: so com `tenant_id = %s` no texto e que filtra pelo argumento.
        if "WHERE tenant_id = %s::uuid" in sql:
            visiveis = [l for l in visiveis if l["tenant_id"] == p[0]]
        if sql.startswith("SELECT id::text") and "FROM platform.catalog_ingestions" in sql:
            assert "estado = 'publicada'" in sql
            return [l["colunas"] for l in visiveis if l["estado"] == "publicada"]
        if sql.startswith("SELECT min(criado_at)"):
            assert "FILTER (WHERE estado = 'publicada')" in sql
            criados = [l["criado_at"] for l in visiveis]
            publicados = [l["confirmado_at"] for l in visiveis if l["estado"] == "publicada" and l["confirmado_at"]]
            return [(min(criados) if criados else None, min(publicados) if publicados else None)]
        raise AssertionError(f"instrucao inesperada: {sql}")


def _mundo() -> _Base:
    return _Base(
        [
            # A: tres fotos, duas publicadas, uma delas com o nome corrigido.
            _linha(A, 1, criado=T0, confirmado=T0 + timedelta(minutes=7)),
            _linha(A, 2, criado=T0 + timedelta(minutes=1), confirmado=T0 + timedelta(minutes=4), corrigido=True,
                   custo="0.03"),
            _linha(A, 3, estado="a_perguntar", criado=T0 - timedelta(minutes=2)),
            # B: o mesmo, noutro tenant, mais cedo e mais caro — nao pode contar em A.
            _linha(B, 4, criado=T0 - timedelta(hours=5), confirmado=T0 - timedelta(hours=4), custo="0.5"),
        ]
    )


class TestOsIndicadoresDoTenant(unittest.TestCase):
    def test_os_numeros_sao_os_do_tenant(self) -> None:
        r = ler_do_tenant(_mundo(), A)
        self.assertEqual(r.publicadas, 2)
        self.assertEqual(r.publicados_sem_correccao, Decimal("0.5"))
        self.assertEqual(r.custo_medio_usd, Decimal("0.017"))
        self.assertEqual(r.acima_do_tecto, 1)
        # Da primeira foto (a que ficou a perguntar, -2 min) a primeira publicacao (+4 min).
        self.assertEqual(r.primeira_foto_ate_primeiro_publicado, timedelta(minutes=6))

    def test_outro_tenant_ve_so_o_seu(self) -> None:
        r = ler_do_tenant(_mundo(), B)
        self.assertEqual(r.publicadas, 1)
        self.assertEqual(r.primeira_foto_ate_primeiro_publicado, timedelta(hours=1))

    def test_sem_publicacao_o_tempo_e_none(self) -> None:
        base = _Base([_linha(A, 1, estado="a_perguntar", criado=T0)])
        r = ler_do_tenant(base, A)
        self.assertEqual(r.publicadas, 0)
        self.assertIsNone(r.primeira_foto_ate_primeiro_publicado)
        self.assertIsNone(r.custo_medio_usd)

    def test_um_tenant_sem_fotos_da_zero_e_none(self) -> None:
        r = ler_do_tenant(_Base([]), A)
        self.assertEqual(r.publicadas, 0)
        self.assertIsNone(r.primeira_foto_ate_primeiro_publicado)

    def test_as_duas_consultas_levam_o_predicado_do_tenant(self) -> None:
        for sql in (SQL_PUBLICADAS_DO_TENANT, SQL_INSTANTES_DO_TENANT):
            self.assertIn("WHERE tenant_id = %s::uuid", sql)


class TestOCanario(unittest.TestCase):
    """O duplo mede o texto: sem RLS, o predicado basta; sem os dois, B entra."""

    def test_sem_rls_o_predicado_basta(self) -> None:
        base = _mundo()
        base.rls = False
        self.assertEqual(ler_do_tenant(base, A).publicadas, 2)

    def test_sem_rls_e_sem_predicado_outro_tenant_entra(self) -> None:
        original = (indicadores.SQL_PUBLICADAS_DO_TENANT, indicadores.SQL_INSTANTES_DO_TENANT)
        base = _mundo()
        base.rls = False
        try:
            indicadores.SQL_PUBLICADAS_DO_TENANT = original[0].replace("WHERE tenant_id = %s::uuid AND ", "WHERE ")  # type: ignore[misc]
            indicadores.SQL_INSTANTES_DO_TENANT = original[1].replace(" WHERE tenant_id = %s::uuid", "")  # type: ignore[misc]
            r = ler_do_tenant(base, A)
        finally:
            indicadores.SQL_PUBLICADAS_DO_TENANT, indicadores.SQL_INSTANTES_DO_TENANT = original  # type: ignore[misc]
        self.assertEqual(r.publicadas, 3)
        self.assertEqual(r.primeira_foto_ate_primeiro_publicado, timedelta(hours=1))  # o de B, e nao os 6 min de A


if __name__ == "__main__":
    unittest.main()
