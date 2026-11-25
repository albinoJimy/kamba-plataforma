"""Coortes sinteticas para os ensaios do `piloto` (KAM-109).

Tudo aqui e **sintetico e marcado como tal**: `sintetico: true`, tenants com
`uuid` gerado por indice, e nenhum telefone. Os numeros de forma telefonica que
os ensaios da guarda usam montam-se em execucao, e nao aparecem como literal.
"""

from __future__ import annotations

import datetime as dt
import json
from typing import Any

from piloto import exportacao

INICIO = dt.date(2027, 1, 4)
MENSALIDADE = 3_000_000  # 30 000 Kz em minor: a ponta baixa da hipotese do bloco, nao um preco


def tenant(n: int) -> str:
    return f"00000000-0000-4000-8000-{n:012d}"


def dias_activos(activada: dt.date, ate: dt.date) -> dict[str, dict[str, Any]]:
    """Um dia por dia com 1 conversa e 1 accao do dono: activa em qualquer janela."""
    dias = {}
    data = activada
    while data <= ate:
        dias[data.isoformat()] = {
            "conversas": 1, "accoes_dono": 1, "actualizacoes_catalogo": 0,
            "handoffs": 0, "custo_llm_usd": "0.010000", "custo_meta_usd": "0.004000",
        }
        data += dt.timedelta(days=1)
    return dias


def pme(
    n: int,
    activada: dt.date | None = INICIO,
    dias: dict[str, Any] | None = None,
    ciclos: list[dict[str, Any]] | None = None,
    na_coorte: bool = True,
    self_service: bool | None = True,
    dpa: bool = True,
) -> dict[str, Any]:
    return {
        "pme": f"P{n:02d}",
        "tenant_id": tenant(n),
        "na_coorte": na_coorte,
        "saida": None if na_coorte else {"dia": "2027-01-18", "motivo": "sem_uso_semana_2"},
        "activada_em": None if activada is None else activada.isoformat(),
        "self_service": self_service,
        "dpa_aceite": dpa,
        "dias": dias or {},
        "ciclos_pagos": ciclos or [],
    }


def ciclo_pago(activada: dt.date, dia: int = 30, valor: int = MENSALIDADE,
               via: str = "facilitador") -> dict[str, Any]:
    return {"inicio": (activada + dt.timedelta(days=dia)).isoformat(),
            "valor_minor": valor, "moeda": "AOA", "via": via}


def bruto(pmes: list[dict[str, Any]], ultimo_dia: dt.date) -> dict[str, Any]:
    return {"formato": exportacao.FORMATO, "sintetico": True,
            "ultimo_dia": ultimo_dia.isoformat(), "pmes": pmes}


def coorte(pmes: list[dict[str, Any]], ultimo_dia: dt.date) -> exportacao.Exportacao:
    return exportacao.de_objecto(json.loads(json.dumps(bruto(pmes, ultimo_dia))))


def h6_export(meses: list[tuple[str, str, int]], amostra: int = 500,
              mensalidade: int = MENSALIDADE) -> dict[str, Any]:
    """A forma do `h6-export exportar`, so com os campos que o `piloto` le."""
    return {
        "fx_aoa_per_usd": "913",
        "mensalidade_aoa_minor": mensalidade,
        "amostra": amostra,
        "percentis_custo_total_usd": {"p50": "0.01", "p90": "0.02", "p99": "0.05"},
        "racio_por_tenant_e_mes": [
            {
                "tenant_id": t, "mes": mes, "mes_completo": True, "conversas_na_amostra": 50,
                "custo_usd": "0", "custo_aoa_minor": custo,
                "racio_custo_mensalidade": format(custo / mensalidade, ".6f"),
            }
            for t, mes, custo in meses
        ],
    }
