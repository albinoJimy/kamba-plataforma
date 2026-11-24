"""A escrita numa referencia fixa do cofre (KAM-250, `ADR-L002` §6 e §7).

## Porque nao e o `cunhar` do KAM-016

O `packages/core-ts/src/secrets/escrita.ts` tem a `SecretWriter`, com um
`cunhar(familia, valor)` que inventa um sufixo **aleatorio** e devolve a
referencia, que a base guarda. As chaves virtuais do LiteLLM sao o contrario:

* a referencia e **conhecida de antemao** — `litellm_virtual_key/<tenant_id>` e
  `litellm_screening_key`, como o `ops/secrets-inventory.yaml` as declara —,
  porque quem as le (o AGR) so sabe o tenant, e nao tem onde ir buscar um
  sufixo;
* o KAM-250 proibe guardar o que quer que seja na base da plataforma.

Por isso a operacao e outra: `gravar(ref, valor)`, que escreve (ou reescreve) o
valor **naquela** referencia. Nao devolve nada, e repetir com o mesmo valor deixa
o cofre igual.

## Onde escreve: um projecto Doppler proprio

Decisao do fundador de 2026-11-24 (bloco do KAM-250, opcao 1): as chaves
virtuais vivem num projecto Doppler **so delas**, e quem escreve tem um *token*
de escrita limitado a esse projecto (`doppler_llm_chaves_escrita`). Um *service
token* do Doppler vale para uma configuracao inteira (`E4` §2.14, em resumo): um
*token* de escrita na configuracao `prod` reescrevia a *master key*, os *peppers*
e as KEK. Aqui o pior que um *token* roubado faz e reescrever chaves de LLM.

Este modulo acrescenta uma segunda barreira, do lado do cliente: o
`DopplerGravador` **recusa** qualquer referencia fora das familias que lhe dao
(`FAMILIAS_DAS_CHAVES_DO_LLM` por omissao). Nao substitui o limite do *token*,
que e do servidor; impede que um erro de programacao use este gravador para
outra coisa.

## O que e NAO VERIFICADO

A forma da API de escrita do Doppler, como a de leitura do KAM-010: nao ha conta.
O que falta confirmar, e onde, esta em `A_CONFIRMAR_ESCRITA`, e tudo o que depende
da forma do pedido esta em `_corpo_do_pedido` e no URL de `gravar`.
"""

from __future__ import annotations

import json
import urllib.error
import urllib.request
from collections.abc import Callable, Mapping
from typing import Protocol, runtime_checkable

from .doppler import RespostaHttp
from .env import nome_da_variavel
from .port import (
    AmbienteErradoError,
    CofreInacessivelError,
    SecretRef,
    familia_da_ref,
    validar_ref,
)

#: As familias que vivem no projecto das chaves virtuais. As duas do inventario
#: com `fonte_08_5` «LiteLLM master/virtuais» que o proxy emite — a *master key*
#: **nao** esta aqui: emite-a quem instala o proxy, e vive no projecto do ambiente.
FAMILIAS_DAS_CHAVES_DO_LLM: tuple[str, ...] = (
    "litellm_virtual_key",
    "litellm_screening_key",
)

#: O nome do projecto Doppler das chaves virtuais, quando o ambiente nao o diz.
#: ***Proposta***: o projecto cria-se na conta, e o nome confirma-se la.
PROJECTO_DAS_CHAVES_POR_OMISSAO = "kamba-llm-chaves"

#: A variavel que nomeia o projecto. Nao e segredo: e configuracao.
VARIAVEL_DO_PROJECTO = "KAMBA_LLM_CHAVES_PROJECTO"

#: O que falta confirmar na escrita, e onde.
A_CONFIRMAR_ESCRITA = {
    "caminho": (
        "caminho e metodo do pedido que cria ou actualiza segredos de uma "
        "configuracao — docs.doppler.com, referencia da API (secrets / update)"
    ),
    "corpo": (
        "forma do corpo; `_corpo_do_pedido` assume "
        "{project, config, secrets: {NOME: valor}} — docs.doppler.com"
    ),
    "resposta": (
        "o codigo de sucesso; este adaptador aceita so 200 — docs.doppler.com"
    ),
    "limite_do_token": (
        "que um service token de escrita fica limitado ao projecto e a "
        "configuracao para que foi emitido — E4 §2.14 diz-o em resumo"
    ),
}


class FamiliaNaoGravavelError(ValueError):
    """A referencia pedida nao e de uma familia que este gravador escreve."""

    def __init__(self, familia: str) -> None:
        self.familia = familia
        super().__init__(
            f"o gravador nao escreve a familia {familia!r}: so as chaves virtuais "
            "do LiteLLM vivem no projecto dele (decisao do fundador, KAM-250)"
        )


@runtime_checkable
class GravadorDeSegredo(Protocol):
    """A porta de escrita numa referencia fixa.

    Separada da `SecretProvider` pela razao do `escrita.ts`: o
    `EnvSecretProvider` nao pode escrever, e quem le e quem escreve nao sao o
    mesmo papel.
    """

    nome: str
    ambiente: str

    def gravar(self, ref: SecretRef, valor: str) -> None:
        """Escreve `valor` em `ref`. **Nunca** poe o valor numa mensagem de erro.

        Levanta `SecretRefInvalidaError`, `FamiliaNaoGravavelError` ou
        `CofreInacessivelError`.
        """
        ...


#: Transporte de escrita: `(url, cabecalhos, corpo) -> RespostaHttp`.
TransporteDeEscrita = Callable[[str, Mapping[str, str], bytes], RespostaHttp]


def _corpo_do_pedido(projecto: str, config: str, nome: str, valor: str) -> bytes:
    """O corpo do pedido. **NAO VERIFICADO** (`A_CONFIRMAR_ESCRITA["corpo"]`)."""
    return json.dumps(
        {"project": projecto, "config": config, "secrets": {nome: valor}}
    ).encode("utf-8")


class DopplerGravador:
    """Escreve numa configuracao de um projecto Doppler, so nas familias dadas."""

    def __init__(
        self,
        ambiente: str,
        projecto: str,
        config: str,
        token_servico: str,
        transporte: TransporteDeEscrita,
        familias: tuple[str, ...] = FAMILIAS_DAS_CHAVES_DO_LLM,
        base_url: str = "https://api.doppler.com",
    ) -> None:
        # A mesma guarda do `DopplerSecretProvider`: um processo de `prod` com a
        # configuracao de `staging` recusa-se a existir.
        if config != ambiente:
            raise AmbienteErradoError("doppler", ambiente, config)
        if token_servico.strip() == "":
            raise CofreInacessivelError("doppler", "service token de escrita nao configurado")
        if not familias:
            raise ValueError("um gravador sem familias nao escreve nada")
        self.nome = "doppler"
        self.ambiente = ambiente
        self.projecto = projecto
        self.config = config
        self._token = token_servico
        self._transporte = transporte
        self._familias = frozenset(familias)
        self._base_url = base_url.rstrip("/")

    def gravar(self, ref: SecretRef, valor: str) -> None:
        ref = validar_ref(ref)
        familia = familia_da_ref(ref)
        if familia not in self._familias:
            raise FamiliaNaoGravavelError(familia)
        if not isinstance(valor, str) or valor.strip() == "":
            # Sem o valor na mensagem, mesmo vazio: a regra e uma so.
            raise ValueError(f"valor vazio para {ref}: o gravador nao apaga segredos")
        # `A_CONFIRMAR_ESCRITA["caminho"]`.
        url = f"{self._base_url}/v3/configs/config/secrets"
        cabecalhos = {
            "authorization": f"Bearer {self._token}",
            "accept": "application/json",
            "content-type": "application/json",
        }
        corpo = _corpo_do_pedido(self.projecto, self.config, nome_da_variavel(ref), valor)
        try:
            resposta = self._transporte(url, cabecalhos, corpo)
        except Exception as erro:  # noqa: BLE001 - so o nome da classe atravessa
            # A mensagem de uma biblioteca de rede pode trazer o URL, os
            # cabecalhos ou, num erro de serializacao, o corpo — que leva o valor.
            raise CofreInacessivelError(
                self.nome, f"transporte falhou: {type(erro).__name__}"
            ) from None
        if resposta.status in (401, 403):
            raise CofreInacessivelError(
                self.nome,
                f"credencial de escrita recusada (HTTP {resposta.status}) para "
                f"{self.projecto}/{self.config}",
            )
        if resposta.status != 200:
            # Sem o corpo: uma resposta de erro pode ecoar o pedido.
            raise CofreInacessivelError(self.nome, f"escrita falhou: HTTP {resposta.status}")


def _pedir(pedido: urllib.request.Request) -> RespostaHttp:
    try:
        with urllib.request.urlopen(pedido, timeout=15) as resposta:  # noqa: S310
            return RespostaHttp(resposta.status, resposta.read().decode("utf-8", "replace"))
    except urllib.error.HTTPError as erro:
        # O corpo de um erro nao se le: nao entra em mensagem nenhuma.
        return RespostaHttp(erro.code, "")


def transporte_http_de_leitura(url: str, cabecalhos: Mapping[str, str]) -> RespostaHttp:
    """`Transporte` do `DopplerSecretProvider` sobre `urllib`.

    Respeita o `HTTPS_PROXY` e o `NO_PROXY` do ambiente, que e por onde o AGR
    chega a `api.doppler.com` (o `proxy-saida`). Uma falha de rede levanta, e o
    adaptador converte-a em `CofreInacessivelError` so com o nome da classe.
    """
    return _pedir(urllib.request.Request(url, headers=dict(cabecalhos), method="GET"))


def transporte_http_de_escrita(
    url: str, cabecalhos: Mapping[str, str], corpo: bytes
) -> RespostaHttp:
    """`TransporteDeEscrita` do `DopplerGravador` sobre `urllib`."""
    return _pedir(
        urllib.request.Request(url, data=corpo, headers=dict(cabecalhos), method="POST")
    )


__all__ = [
    "A_CONFIRMAR_ESCRITA",
    "FAMILIAS_DAS_CHAVES_DO_LLM",
    "PROJECTO_DAS_CHAVES_POR_OMISSAO",
    "VARIAVEL_DO_PROJECTO",
    "DopplerGravador",
    "FamiliaNaoGravavelError",
    "GravadorDeSegredo",
    "TransporteDeEscrita",
    "transporte_http_de_escrita",
    "transporte_http_de_leitura",
]
