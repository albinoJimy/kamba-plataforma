"""Mede os dez criterios e escreve `resultados.json`. Chamado por `harness.py`.

Um registo por criterio, e tres estados que nunca se confundem:

    passa            mediu-se e o numero cumpre o limiar
    falha            mediu-se e o numero nao cumpre o limiar
    nao_verificado   **nao se mediu** (superficie em falta, Medusa em baixo)

O `nao_verificado` e o estado que faz este ficheiro valer a pena. Um spike que
devolvesse `passa` para um criterio que nao chegou a correr produzia uma licenca
de arquitectura assinada por um teste que nunca existiu — e o KAM-041 existe
precisamente porque metade do que rodeia o Medusa esta NAO VERIFICADO.
"""

from __future__ import annotations

import dataclasses
import json
import re
import time
from pathlib import Path

import sementes

PASSA = "passa"
FALHA = "falha"
NAO_VERIFICADO = "nao_verificado"

#: Quais dos dez criterios bloqueiam a decisao (§4.3).
BLOQUEANTES = ("AC-1", "AC-2", "AC-3", "AC-4", "AC-5", "AC-6", "AC-7")
ALVOS = ("AC-8", "AC-9", "AC-10")


@dataclasses.dataclass
class Resultado:
    id: str
    criterio: str
    limiar: str
    tipo: str
    estado: str
    medido: str
    evidencia: str
    detalhe: dict = dataclasses.field(default_factory=dict)

    def linha(self) -> str:
        marca = {PASSA: "VERDE", FALHA: "VERMELHO", NAO_VERIFICADO: "NAO VERIFICADO"}
        return f"  {self.id:<6} {marca[self.estado]:<15} {self.medido}"


def correr(ambiente: dict[str, str], saida: Path, contentor_pg: str,
           contentor_medusa: str | None, pacote_medusa: dict | None) -> int:
    import criterios
    import iso

    inicio = time.monotonic()
    print("==> sementes: 3 tenants ficticios")
    tenants = sementes.semear(ambiente)
    for rotulo, tenant in tenants.items():
        print(f"    {rotulo}: {tenant.tenant_id} ({tenant.merchant_id})")

    resultados: list[Resultado] = []

    print("==> matriz ISO (60 casos)")
    casos = iso.correr(ambiente, tenants, contentor_medusa is not None,
                       contentor_medusa)
    (saida / "iso.json").write_text(
        json.dumps([dataclasses.asdict(c) for c in casos], indent=2, ensure_ascii=False),
        encoding="utf-8",
    )
    resultados.append(criterios.ac1(casos))

    print("==> criterios")
    resultados.append(criterios.ac2(ambiente, contentor_pg, contentor_medusa, saida))
    resultados.append(criterios.ac3(ambiente, tenants, contentor_medusa))
    resultados.append(criterios.ac4(ambiente, tenants))
    resultados.append(criterios.ac5(ambiente, tenants))
    resultados.append(criterios.ac6(ambiente, tenants))
    resultados.append(criterios.ac7(pacote_medusa, saida, contentor_medusa))
    resultados.append(criterios.ac8(ambiente, tenants))
    resultados.append(criterios.ac9())
    resultados.append(criterios.ac10(ambiente, contentor_medusa, saida))

    duracao = time.monotonic() - inicio
    da_matriz = [c for c in casos if re.match(r"^ISO-\d{2}$", c.id)]
    documento = {
        "ticket": "KAM-041",
        "segundos": round(duracao, 1),
        "medusa": pacote_medusa,
        "tenants": {r: t.tenant_id for r, t in tenants.items()},
        "criterios": [dataclasses.asdict(r) for r in resultados],
        # **So os casos da matriz entram nas contagens.** As sondas extra
        # (`ISO-48b`, `RLS-CONTROLO`) medem-se e vao para o `iso.json`, mas
        # contar-las aqui dava «61 de 60» e punha a consola a dizer um total
        # que a matriz do §4.4 nao tem.
        "iso": {
            "total": len(da_matriz),
            "passa": sum(1 for c in da_matriz if c.estado == PASSA),
            "falha": sum(1 for c in da_matriz if c.estado == FALHA),
            "nao_verificado": sum(1 for c in da_matriz if c.estado == NAO_VERIFICADO),
            "sondas_fora_da_contagem": [c.id for c in casos if c not in da_matriz],
        },
    }
    (saida / "resultados.json").write_text(
        json.dumps(documento, indent=2, ensure_ascii=False), encoding="utf-8"
    )

    print(f"\n--- criterios ({duracao:.0f}s) ---")
    for resultado in resultados:
        print(resultado.linha())
    print(f"\n--- ISO: {documento['iso']['passa']} verdes, "
          f"{documento['iso']['falha']} vermelhos, "
          f"{documento['iso']['nao_verificado']} nao verificados "
          f"de {documento['iso']['total']} ---")
    print(f"\nResultados em {saida}")

    por_id = {r.id: r for r in resultados}
    if any(por_id[i].estado == FALHA for i in BLOQUEANTES):
        return 1
    if any(por_id[i].estado == NAO_VERIFICADO for i in BLOQUEANTES):
        return 2
    return 0
