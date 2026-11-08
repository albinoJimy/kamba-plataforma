"""Os contadores por contacto (criterio 5): injeccao por hora e abuso por dia.

    contar_veredicto(contadores, veredicto, agora) -> (novos, accao)

`accao` e `None`, `"handoff"` (a terceira tentativa de injeccao na hora) ou
`"pausar"` (a N-esima ocorrencia de abuso, que poe o contador a zero). Funcoes puras sobre um `dict`: o
`guard_in` e quem as chama e quem age.

## Vivem no estado do grafo, e o `thread_id` e por contacto

O `thread_id` e `{tenant_id}:{contact_id}` (`turno.py`, dicionario §3.1): o
*checkpoint* de um *thread* **e** o estado de um contacto, e o «mesmo contacto»
do criterio e exactamente essa chave. Por isso o `guard_contadores` fica no
`ConversaState`, com a retencao do *checkpointer*, e **nenhuma migracao** entra
com este ticket — a licao do KAM-160 («um terceiro sitio para o mesmo facto
seria uma terceira verdade») que o `pii_map` do KAM-112 ja seguiu.

E fica **fora de duas tabelas**, pela razao mecanica do `turn_seq` (KAM-114) e
do `pii_map`: fora do `CAMPOS_DO_TURNO` (que o `ingest` reinicia) e fora do
`estado_inicial` (que o `turno.py` passa ao `ainvoke` em **cada** turno,
sobrescrevendo o que o *checkpoint* tinha). Uma chave que nascesse la era
apagada a cada turno e o contador nunca passava de um.

## O que fica escrito como limite

Os contadores sao **por *thread***, e um contacto que a loja apague
(`adelete_thread`) recomeca do zero. Tambem nao atravessam *tenants*: o mesmo
numero a atacar duas lojas sao dois contactos — e isso e o isolamento, nao um
defeito. A contagem distribuida entre lojas seria do T&S (KAM-073).
"""

from __future__ import annotations

from collections.abc import Mapping
from typing import Any, Final

from . import politica

#: A chave do `ConversaState`. Dicionario, emenda deste ticket.
CHAVE: Final = "guard_contadores"

#: As accoes que um registo pode pedir. Lista fechada.
ACCAO_HANDOFF: Final = "handoff"
ACCAO_PAUSAR: Final = "pausar"


def _vazio() -> dict[str, Any]:
    return {"injection": [], "abuse": [], "cooldown_ate": 0.0}


def ler(estado: Mapping[str, Any]) -> dict[str, Any]:
    """Os contadores de um estado, ou os de um contacto novo.

    Um valor que nao tenha a forma conta como vazio em vez de levantar: um
    *checkpoint* escrito a mao nao deve parar uma conversa. **O lado para onde
    isto erra e o permissivo**, e e escolha: o contrario era uma conversa morta
    por um campo corrompido, e as regras continuam a decidir turno a turno.
    """
    cru = estado.get(CHAVE)
    novo = _vazio()
    if not isinstance(cru, Mapping):
        return novo
    for chave in ("injection", "abuse"):
        tempos = cru.get(chave)
        if isinstance(tempos, (list, tuple)):
            novo[chave] = [
                float(t) for t in tempos if isinstance(t, (int, float)) and not isinstance(t, bool)
            ]
    ate = cru.get("cooldown_ate")
    if isinstance(ate, (int, float)):
        novo["cooldown_ate"] = float(ate)
    return novo


def em_cooldown(contadores: Mapping[str, Any], agora: float) -> bool:
    """Se o contacto esta no *cool-down* que a terceira tentativa abriu."""
    return float(contadores.get("cooldown_ate") or 0.0) > agora


def contar_veredicto(
    contadores: Mapping[str, Any], veredicto: str, agora: float
) -> tuple[dict[str, Any], str | None]:
    """Conta o veredicto deste turno e diz se e preciso agir.

    **A accao dispara uma vez por limiar**, e nao a cada turno acima dele: a
    terceira tentativa abre o *handoff* e o *cool-down*; a quarta, dentro do
    *cool-down*, ja nao abre outro. Um *handoff* por tentativa era o atacante a
    escolher quantas vezes chamamos uma pessoa.
    """
    novos = {
        "injection": list(contadores.get("injection") or ()),
        "abuse": list(contadores.get("abuse") or ()),
        "cooldown_ate": float(contadores.get("cooldown_ate") or 0.0),
    }
    if veredicto == "injection":
        janela = [t for t in novos["injection"] if agora - t < politica.JANELA_DE_INJECCAO_S]
        janela.append(agora)
        # So as ultimas que contam para o limiar: a lista e limitada pelo
        # limiar e nao pelo ritmo do atacante, que era o tamanho do estado
        # escolhido por quem ataca.
        novos["injection"] = janela[-politica.TENTATIVAS_DE_INJECCAO :]
        if len(janela) >= politica.TENTATIVAS_DE_INJECCAO and not em_cooldown(novos, agora):
            novos["cooldown_ate"] = agora + politica.COOLDOWN_S
            return novos, ACCAO_HANDOFF
    elif veredicto == "abuse":
        # **Decai**, pela janela, e a revisao adversarial mediu porque (achado
        # 10): o *thread* e por contacto e atravessa canais, pelo que um contador
        # sem janela juntava dois insultos num canal a um de meses depois noutro
        # e pausava a segunda conversa.
        janela = [t for t in novos["abuse"] if agora - t < politica.JANELA_DE_ABUSO_S]
        janela.append(agora)
        novos["abuse"] = janela[-politica.OCORRENCIAS_DE_ABUSO :]
        if len(janela) >= politica.OCORRENCIAS_DE_ABUSO:
            # **O contador volta a zero, e nao fica uma marca de «pausada» no
            # estado.** Quem diz se a conversa esta pausada e o modo
            # (`conversations.mode`, KAM-018), e com ela pausada o grafo nem
            # corre (`turno.py`). Uma marca aqui sobrevivia ao dono voltar a
            # pôr a conversa em `bot` e deixava o bot a recusar para sempre.
            novos["abuse"] = []
            return novos, ACCAO_PAUSAR
    return novos, None
