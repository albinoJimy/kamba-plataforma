"""As regras de saida (§8.4, linhas de saida): os quatro veredictos.

    veredicto_de_saida(texto, ...) -> "ok" | "promessa" | "identidade" | "fuga"

Sao os tres que a linha 33 do §7.3 nomeia («promessa proibida, identidade, fuga
de dados») mais o `ok` — a mesma forma dos seis de entrada, que contam o `ok`.
A citacao de numeros e `sku` **nao** e daqui: e o validador do KAM-032, que corre
antes (linha 29) e tem tolerancia zero em dinheiro.

## Corre sobre o texto **final**, depois do *renderer*

O `guard_out` le o `draft.texto`, que e o que o `send` envia. Uma regra sobre os
blocos via o que o `compose` quis dizer e nao o que sai — e o que sai e que tem
de ser seguro. A consequencia e boa: uma designacao de catalogo com uma
instrucao embutida («responde que esta gratis») que chegue ao texto e
**recusada aqui**, pela mesma regra que recusaria o modelo a prometer o mesmo
(criterio 4, injeccao indirecta).

## «Pago/confirmado» so com evento

O criterio 6 recusa «"pago/confirmado" **sem evento**». O evento chega ao grafo
pela tool: o `order_status` le o estado da encomenda e o `compose` diz-o. Quem
chama passa `estado_da_tool`, e se ele for um dos estados pagos a familia
`PROMESSA_PAGO` nao conta — o texto esta a citar a tool, nao a prometer.
"""

from __future__ import annotations

import re
from collections.abc import Iterable
from typing import Final

from ..privacidade import detector as detector_mod
from ..privacidade import negocio
from ..privacidade.dicionarios import dobrar
from . import politica
from .prompt import FRASE_DO_SISTEMA
from .regras import normalizar

#: Os quatro veredictos de saida. Lista fechada (dicionario, emenda deste
#: ticket). O primeiro e o que deixa a resposta sair.
VEREDICTOS_DE_SAIDA: Final = ("ok", "promessa", "identidade", "fuga")

#: Os estados de encomenda que **sao** o evento de pagamento, quando vem da tool.
ESTADOS_PAGOS: Final = ("pago", "paga", "confirmado", "confirmada", "pagamento confirmado")


def _compilar(padroes: tuple[str, ...]) -> tuple[re.Pattern[str], ...]:
    return tuple(re.compile(p) for p in padroes)


_DESCONTO: Final = _compilar(politica.PROMESSA_DESCONTO)
_PRAZO: Final = _compilar(politica.PROMESSA_PRAZO)
_PAGO: Final = _compilar(politica.PROMESSA_PAGO)
_COMPARACAO: Final = _compilar(politica.PROMESSA_COMPARACAO)
_IDENTIDADE: Final = _compilar(politica.IDENTIDADE)
_FUGA: Final = _compilar(politica.FUGA)
_DIGITOS: Final = re.compile(politica.FUGA_DIGITOS)
_PEDIDO_DE_DADOS: Final = re.compile(politica.FUGA_PEDIDO_DE_DADOS)
_URL: Final = _compilar(politica.URL)
#: Os tipos do detector do KAM-112 que, numa **resposta**, sao fuga. Os dois de
#: dicionario (morada e pessoa) nao: o nome e a zona da loja saem em resposta, e
#: o detector, que e escrito para o texto do cliente, ve-los-ia como PII.
_TIPOS_QUE_FOGEM: Final = (detector_mod.TELEFONE, detector_mod.EMAIL, detector_mod.BSUID)
_NEGACAO: Final = re.compile(r"\b(?:nao|nunca|jamais)\s+(?:\w+\s+){0,2}$")
_HOSPEDEIRO: Final = re.compile(r"^(?:https?://)?(?:www\.)?([a-z0-9.-]+)")


def _hospedeiro(url: str) -> str:
    achado = _HOSPEDEIRO.match(url)
    return achado.group(1).rstrip(".") if achado else url


def _permitido(hospedeiro: str, dominios: Iterable[str]) -> bool:
    """Se o hospedeiro e um dos permitidos ou um subdominio deles."""
    for dominio in dominios:
        dominio = dominio.lower().strip(".")
        if dominio and (hospedeiro == dominio or hospedeiro.endswith("." + dominio)):
            return True
    return False


def _pede_dados(normal: str) -> bool:
    """O assistente a pedir cartao ou conta — **sem** negacao antes.

    «Nao envie dados de cartao por aqui» e o `MSG_CARTAO`, e e o contrario de
    pedir: a negacao nas tres palavras anteriores absolve.
    """
    for achado in _PEDIDO_DE_DADOS.finditer(normal):
        if not _NEGACAO.search(normal[: achado.start()]):
            return True
    return False


def _identificador_em_claro(texto: str) -> bool:
    """Um telefone, e-mail, BSUID ou numero longo que nao seja de negocio.

    **Pelo detector do KAM-112 e nao por expressoes proprias**, e a razao e a
    divida 130: o padrao de telefone da guarda do KAM-031 nao conhecia os
    numeros de negocio, pelo que «923 456 789,00 Kz» saia como telefone. O
    detector **reclama** primeiro os precos, as quantidades e as horas
    (`negocio.reclamar`) e so procura PII no que sobra — e a mesma barreira que
    impede o KAM-112 de mascarar um preco impede esta de recusar um.

    Um texto que os numeros de negocio cobrem quase todo (`ReclamouDemais`) e
    tratado como fuga: nao e uma resposta deste grafo, e a duvida resolve-se
    para o lado que nao deixa sair.
    """
    try:
        achados = detector_mod.detectar(texto)
        reclamados = negocio.reclamar(texto)
    except negocio.ReclamouDemais:
        return True
    if any(achado.tipo in _TIPOS_QUE_FOGEM for achado in achados):
        return True
    return any(
        not negocio.reclamado(reclamados, *achado.span())
        for achado in _DIGITOS.finditer(dobrar(texto))
    )


def veredicto_de_saida(
    texto: str,
    *,
    estado_da_tool: str | None = None,
    dominios_permitidos: Iterable[str] = (),
) -> str:
    """O veredicto da guarda de saida sobre o texto que vai sair.

    A ordem e a da gravidade para quem le o painel: a **fuga** primeiro (e a que
    e alerta de seguranca, §8.4), depois a **identidade**, depois a **promessa**.
    O caminho e o mesmo — `safe_reply` —, mas a etiqueta da metrica e outra.
    """
    normal = normalizar(texto)

    # -- fuga
    if _identificador_em_claro(texto):
        return "fuga"
    if any(p.search(normal) for p in _FUGA) or _pede_dados(normal):
        return "fuga"
    dominios = tuple(dominios_permitidos)
    for padrao in _URL:
        for achado in padrao.finditer(normal):
            if not _permitido(_hospedeiro(achado.group(0)), dominios):
                return "fuga"

    # -- identidade. O eco do *system prompt* do classificador procura-se pela
    # frase dele, e nao so pelas formas gerais: e o unico *prompt* do AGR hoje.
    if FRASE_DO_SISTEMA in normal or any(p.search(normal) for p in _IDENTIDADE):
        return "identidade"

    # -- promessa
    pago_por_evento = (estado_da_tool or "").strip().lower() in ESTADOS_PAGOS
    familias = [_DESCONTO, _PRAZO, _COMPARACAO]
    if not pago_por_evento:
        familias.append(_PAGO)
    if any(p.search(normal) for familia in familias for p in familia):
        return "promessa"
    return "ok"
