"""Instrumentos do gate da Fase 0 (KAM-108).

Tres coisas, e nenhuma delas e um veredicto:

    cenario    o cenario *scriptado* do esqueleto andante, como dados
    traco      a cadeia mensagem -> pedido -> evento -> consumo, por identificadores
    recolha    as ligacoes de CI, a metrica de reaproveitamento e o estado das
               decisoes externas, reunidos para a checklist

**A demonstracao e o veredicto sao humanos** (bloco KAM-108, «Detalhes
Tecnicos»). Este pacote prepara; nao mede a conversa real, nao corre a
demonstracao e nao marca caixa nenhuma. O que ele impede e o contrario: que uma
linha da checklist fique com um estado sem evidencia nomeada ao lado.
"""

from __future__ import annotations

__all__ = ["cenario", "consulta", "recolha", "traco"]
