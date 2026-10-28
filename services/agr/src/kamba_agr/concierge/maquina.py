"""A maquina do rascunho: dominios, identificador, distancia e numero livre.

Funcoes puras, como o `handoff/maquina.py` do KAM-034: nada aqui fala com a base
nem com o HND, e e isso que as torna testaveis sem levantar nada.

## `pendente` nao e um valor de `decisao`

O criterio 2 pede um *compare-and-set* `pendente -> decidido` e o criterio 6
fixa `decisao` em cinco valores, entre os quais o `pendente` **nao esta**. A
leitura adoptada, que a revisao `0024` implementa, e a unica que faz os dois
valerem ao mesmo tempo: **`pendente` e a ausencia de decisao** (`decisao IS
NULL`), e `decidido` e qualquer um dos cinco. Ver a nota da revisao.
"""

from __future__ import annotations

import difflib
import hashlib
from collections.abc import Sequence
from typing import Any, Final

from ..validador.veredicto import validar

#: Os cinco valores de `decisao` do criterio 6. Lista **fechada**, e a mesma do
#: `CHECK` da revisao `0024` — ha teste que confronta as duas
#: (`test_as_cinco_decisoes_sao_as_do_check_da_revisao_0024`), pela razao que o
#: KAM-034 escreveu para os estados do `handoffs`: sem isso as duas listas
#: divergiam e o codigo escrevia um valor que a base recusa com `23514` — um 500
#: em producao e nenhum teste vermelho.
DECISOES: Final = (
    "aprovado",
    "editado",
    "rejeitado",
    "expirado",
    "substituido",
)

#: As duas decisoes que **deixam sair a mensagem**. E o criterio 1, e esta aqui
#: em vez de espalhado por `if`s porque e a barreira do ticket: «sem decisao
#: humana registada nao sai mensagem».
#:
#: As outras tres nao enviam nada: `rejeitado` e o operador a recusar,
#: `expirado` e o prazo, e `substituido` e o dono ou o handoff a tomar a palavra.
DECISOES_QUE_ENVIAM: Final = ("aprovado", "editado")

#: As duas que um humano pode pedir pela rota. O `expirado` e da varredura e o
#: `substituido` e do *echo* ou do handoff: nenhum dos dois chega por um clique,
#: e aceita-los na rota dava a um operador a possibilidade de escrever um
#: desfecho que o sistema reserva para si.
DECISOES_DO_OPERADOR: Final = ("aprovado", "editado", "rejeitado")

#: Os motivos de lista fechada do criterio 4. **Proposta**: o bloco diz «a
#: definir com o operador do Piloto», e calibra-se no KAM-109. A mesma lista do
#: `CHECK` da `0024`, com teste de paridade.
MOTIVOS: Final = (
    "tom",
    "preco_errado",
    "stock_errado",
    "fora_de_ambito",
    "deveria_ir_a_humano",
    "outro",
)

#: Os desfechos de uma chamada a `/internal/draft-decision`. Lista fechada; e o
#: eixo de `agr_draft_decisao_total`.
#:
#: E a forma dos tres do `/internal/resume` (KAM-034, dicionario §3.32), e pela
#: mesma razao: um painel que somasse os tres nao distinguia «uma decisao» de
#: «duas». `decidido` venceu o CAS; `repetido` e o duplo clique, que responde 200
#: sem efeito; `recusado` e o rascunho que **nao e deste *thread*** e responde
#: 404 — e e 404 e nao 403 porque «existe mas nao e teu» confirma a existencia
#: do rascunho de outro *tenant* (ADR-015).
DESFECHOS: Final = ("decidido", "repetido", "recusado")

#: O prazo sem decisao humana, em horas (criterio 1). **Nao e parametro de
#: calibracao:** e o mesmo prazo do handoff (dicionario §3.32), que vem da
#: Messaging Policy que o `docs/tecnica/01` §11.4 cita — passadas 24 h a janela
#: de servico fechou e a mensagem nao pode sair de qualquer maneira.
PRAZO_HORAS: Final = 24

#: O limiar do alerta de rascunho a espera, em minutos. **Proposta** (criterio
#: 6), calibra-se no KAM-109 com o operador do Piloto.
ALERTA_MINUTOS: Final = 10


class DecisaoInvalidaError(ValueError):
    """Uma `decisao` ou um `motivo` fora do dominio fechado."""


def draft_id(thread_id: str, turn_seq: int) -> str:
    """`sha256(thread_id:turn_seq)` — o criterio 2.

    **Estavel entre re-execucoes do no**, que e o que faz «re-executar 5x cria 1
    rascunho» ser uma propriedade da chave e nao de um contador. A forma e a do
    `_handoff_id` do KAM-031, e o separador e o mesmo `:`.
    """
    return hashlib.sha256(f"{thread_id}:{int(turn_seq)}".encode()).hexdigest()


def exigir_decisao(decisao: object, *, do_operador: bool = False) -> str:
    """Valida a `decisao` contra o dominio fechado, ou levanta.

    O `do_operador` estreita para as tres que um clique pode pedir: sem ele, a
    rota aceitava `expirado` e `substituido`, que sao desfechos que o sistema se
    reserva (ver `DECISOES_DO_OPERADOR`).
    """
    permitidas = DECISOES_DO_OPERADOR if do_operador else DECISOES
    if not isinstance(decisao, str) or decisao not in permitidas:
        raise DecisaoInvalidaError(
            f"decisao tem de ser uma de {permitidas} (recebido: {decisao!r})"
        )
    return decisao


def exigir_motivo(motivo: object, decisao: str) -> str | None:
    """Valida o `motivo`, que e obrigatorio no `rejeitado` e no `editado`.

    **E obrigatorio nos dois e nao so no `rejeitado`**, porque e o motivo que
    alimenta o `golden-candidates` do criterio 7: uma edicao sem motivo exporta
    um caso sem rotulo, e um caso sem rotulo nao serve para reescrita sintetica
    nenhuma. No `aprovado` nao ha motivo a dar — o rascunho estava bem.
    """
    if decisao == "aprovado":
        if motivo is not None:
            raise DecisaoInvalidaError("um rascunho aprovado nao leva motivo")
        return None
    if not isinstance(motivo, str) or motivo not in MOTIVOS:
        raise DecisaoInvalidaError(
            f"motivo tem de ser um de {MOTIVOS} (recebido: {motivo!r})"
        )
    return motivo


def distancia_normalizada(antes: str, depois: str) -> float:
    """A «razao de edicao» do criterio 6: distancia normalizada em [0, 1].

    `0` e «o operador nao mexeu»; `1` e «reescreveu tudo». Arredonda-se a tres
    casas, que e a escala da coluna `numeric(4, 3)` da revisao `0024`.

    **Proposta na medida, nao no intervalo.** O intervalo e o que o criterio
    fixa; a medida e o complemento do `difflib.SequenceMatcher.ratio()`, da
    biblioteca padrao, e calibra-se no KAM-109 contra as edicoes reais do
    Piloto. Uma Levenshtein propria dava outro numero na mesma escala e obrigava
    a manter codigo que a biblioteca padrao ja tem.

    **Nao guarda nem devolve texto.** Recebe os dois, devolve um numero: e o que
    permite ao servico calcular a razao sem que o texto chegue a tabela.
    """
    if antes == depois:
        return 0.0
    if not antes and not depois:
        return 0.0
    return round(1.0 - difflib.SequenceMatcher(None, antes, depois).ratio(), 3)


def numero_livre(texto: str, facts: Sequence[Any] = ()) -> bool:
    """O sinal do criterio 4: a edicao traz um numero que nao e *fact* do turno.

    **Corre o validador de citacao do KAM-032 e nao uma regra propria**, e e a
    unica forma de a resposta ser a mesma que o grafo daria: o `validar` do
    `validador/veredicto.py` e exactamente «este texto cita numeros que as tools
    nao devolveram?». Uma segunda implementacao aqui divergia da primeira no dia
    em que uma delas aprendesse um formato novo — e ja ha dois formatos que so
    ele conhece (o extenso e o `a partir de`).

    Devolve `True` quando o veredicto **nao** e `ok`. O criterio manda
    **sinalizar e contar**, nao bloquear: «bloquear em vez de sinalizar fica para
    decisao do Responsavel de Produto».
    """
    return not validar(texto, tuple(facts)).ok


__all__ = [
    "ALERTA_MINUTOS",
    "DECISOES",
    "DECISOES_DO_OPERADOR",
    "DECISOES_QUE_ENVIAM",
    "DESFECHOS",
    "MOTIVOS",
    "PRAZO_HORAS",
    "DecisaoInvalidaError",
    "distancia_normalizada",
    "draft_id",
    "exigir_decisao",
    "exigir_motivo",
    "numero_livre",
]
