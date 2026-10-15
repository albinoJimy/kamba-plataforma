"""`DopplerSecretProvider` — o adaptador do cofre do Piloto (KAM-010).

Espelho de `packages/core-ts/src/secrets/doppler.ts`.

## Estado desta implementacao, dito em voz alta

Esta **escrita e testada contra um transporte falso, sem credenciais e sem nunca
ter falado com a Doppler**. Nao existe conta Doppler neste ticket, pelo que:

- O caminho, os parametros e a **forma exacta da resposta** da API sao
  **NAO VERIFICADO**. Confirmam-se na referencia da API em `docs.doppler.com`
  antes do primeiro uso real; o sitio exacto de cada um esta em `A_CONFIRMAR`.
- Tudo o que depende da forma da resposta esta atras de **uma so funcao**
  (`interpretar`), injectavel.
- O que **nao** e suposicao e o modelo de autenticacao e de isolamento que o
  `E4` §2.14 confirma em resumo: projectos separados e *service tokens* por
  configuracao. E sobre isso que a guarda de ambiente assenta.

O preco (Developer gratis ate 3 utilizadores, $8/utilizador acima; 10 projectos,
50 *service tokens*, logs de 3 dias) e CONFIRMADO **em resumo** no `E4` §2.14 e
herda esse estado.

O transporte e injectado — uma funcao `(url, cabecalhos) -> (status, corpo)` —
para que `libs/py-core` continue sem dependencias (decisao do KAM-001) e para que
os testes corram sem rede.
"""

from __future__ import annotations

import json
import time
from collections.abc import Callable, Mapping
from typing import NamedTuple
from urllib.parse import quote

from .env import PREFIXO, SUFIXO_ANTERIOR, nome_da_variavel
from .port import (
    AmbienteErradoError,
    CofreInacessivelError,
    SecretAusenteError,
    SecretRef,
    validar_ref,
)

#: O que falta confirmar, e onde.
#:
#: Fica no codigo e nao so num documento de proposito: quem for ligar isto a uma
#: conta real tropeca nesta constante antes de tropecar numa resposta 404.
A_CONFIRMAR = {
    "caminho": (
        "caminho e parametros do pedido de leitura de segredos — docs.doppler.com, "
        "referencia da API (secrets / download)"
    ),
    "resposta": (
        "forma do JSON de resposta; `interpretar_descarga_plana` assume um objecto "
        "plano NOME->valor — docs.doppler.com, referencia da API"
    ),
    "cabecalho_auth": (
        "forma do cabecalho de autenticacao com um service token (Bearer vs Basic) — "
        "docs.doppler.com, referencia de autenticacao"
    ),
    "identificacao_da_config": (
        "se a resposta identifica o projecto/config servidos; se identificar, ligar "
        "`config_da_resposta` e a guarda deixa de ser so do lado do cliente"
    ),
}


class RespostaHttp(NamedTuple):
    """Resposta HTTP, reduzida ao que este adaptador usa."""

    status: int
    corpo: str


#: Transporte injectado: recebe url e cabecalhos, devolve `RespostaHttp`.
Transporte = Callable[[str, Mapping[str, str]], RespostaHttp]

#: Interpreta o corpo da resposta num mapa NOME->valor.
Interpretar = Callable[[str], Mapping[str, str]]


def interpretar_descarga_plana(corpo: str) -> Mapping[str, str]:
    """Interpretacao por omissao: objecto JSON plano, `NOME -> valor`.

    **NAO VERIFICADO** (`A_CONFIRMAR["resposta"]`). E a forma que uma descarga em
    JSON tipicamente tem, e e a que mantem este adaptador legivel enquanto nao ha
    conta; nao e a forma confirmada da API.
    """
    try:
        cru = json.loads(corpo)
    except ValueError:
        # Sem o corpo na mensagem: um corpo de 200 contem segredos.
        raise CofreInacessivelError("doppler", "resposta nao e JSON") from None
    if not isinstance(cru, dict):
        raise CofreInacessivelError("doppler", "resposta nao e um objecto JSON")
    return {k: v for k, v in cru.items() if isinstance(k, str) and isinstance(v, str)}


class DopplerSecretProvider:
    """Adaptador Doppler.

    Le a configuracao inteira de uma vez e serve os segredos a partir dela. Nao
    e optimizacao: o modelo do Doppler e "uma configuracao = um conjunto de
    variaveis", e um pedido por segredo multiplicaria por vinte os acessos a um
    SaaS que o `E4` §5 marca como risco de dependencia.

    O nome de cada variavel e o mesmo que o `EnvSecretProvider` usa
    (`KAMBA_SECRET_...`), e isto e deliberado: e o que faz `doppler run -- ...`
    (ADR-L002) e este adaptador servirem os mesmos nomes.
    """

    def __init__(
        self,
        ambiente: str,
        projecto: str,
        config: str,
        token_servico: str,
        transporte: Transporte,
        base_url: str = "https://api.doppler.com",
        interpretar: Interpretar = interpretar_descarga_plana,
        config_da_resposta: Callable[[str], str | None] | None = None,
        ttl_descarga_s: float = 60.0,
        agora: Callable[[], float] = time.monotonic,
    ) -> None:
        # A guarda que o critério de aceitação do KAM-010 pede do lado do
        # servidor (um token de `staging` recusado contra `prod`) **nao se pode
        # provar sem conta**. Esta e a metade que se tem sem conta, e vale por
        # si: um processo de `prod` configurado com a configuracao de `staging`
        # recusa-se a existir, em vez de servir pedidos reais com chaves de teste.
        if config != ambiente:
            raise AmbienteErradoError("doppler", ambiente, config)
        if token_servico.strip() == "":
            raise CofreInacessivelError("doppler", "service token nao configurado")

        self.nome = "doppler"
        self.ambiente = ambiente
        self.projecto = projecto
        self.config = config
        self._token = token_servico
        self._transporte = transporte
        self._base_url = base_url
        self._interpretar = interpretar
        self._config_da_resposta = config_da_resposta
        self._ttl = ttl_descarga_s
        self._agora = agora
        self._cache: tuple[Mapping[str, str], float] | None = None

    def health(self) -> None:
        self._descarregar()

    def get(self, ref: SecretRef) -> str:
        mapa = self._descarregar()
        valor = mapa.get(nome_da_variavel(ref), "")
        if valor.strip() == "":
            raise SecretAusenteError(validar_ref(ref), self.nome)
        return valor

    def get_ring(self, ref: SecretRef) -> tuple[str, str | None]:
        mapa = self._descarregar()
        nome = nome_da_variavel(ref)
        actual = mapa.get(nome, "")
        if actual.strip() == "":
            raise SecretAusenteError(validar_ref(ref), self.nome)
        anterior = mapa.get(nome + SUFIXO_ANTERIOR, "")
        return actual, (None if anterior.strip() == "" else anterior)

    def versions(self, ref: SecretRef) -> tuple[str, ...]:
        _, anterior = self.get_ring(ref)
        return ("actual",) if anterior is None else ("actual", "anterior")

    def _descarregar(self) -> Mapping[str, str]:
        if self._cache is not None:
            mapa, em = self._cache
            if self._agora() - em < self._ttl:
                return mapa

        # `A_CONFIRMAR["caminho"]` e `A_CONFIRMAR["cabecalho_auth"]`.
        url = (
            f"{self._base_url}/v3/configs/config/secrets/download"
            f"?project={quote(self.projecto, safe='')}"
            f"&config={quote(self.config, safe='')}&format=json"
        )
        cabecalhos = {
            "authorization": f"Bearer {self._token}",
            "accept": "application/json",
        }

        try:
            resposta = self._transporte(url, cabecalhos)
        except Exception as erro:  # noqa: BLE001 - ver a razao abaixo
            # So o **nome** da classe do erro atravessa: a mensagem de uma
            # biblioteca de rede pode trazer URL, cabecalhos ou credenciais.
            raise CofreInacessivelError(
                self.nome, f"transporte falhou: {type(erro).__name__}"
            ) from None

        if resposta.status in (401, 403):
            # Credencial recusada. Nao se sabe se foi o token errado, o projecto
            # errado ou a configuracao errada — e nao se adivinha.
            raise CofreInacessivelError(
                self.nome,
                f"credencial recusada (HTTP {resposta.status}) para "
                f"{self.projecto}/{self.config}",
            )
        if resposta.status != 200:
            # Sem o corpo: pode conter segredos num 200 e detalhes de conta nos
            # outros.
            raise CofreInacessivelError(self.nome, f"HTTP {resposta.status}")

        servida = (
            self._config_da_resposta(resposta.corpo)
            if self._config_da_resposta is not None
            else None
        )
        if servida is not None and servida != self.config:
            raise AmbienteErradoError(self.nome, self.ambiente, servida)

        mapa = self._interpretar(resposta.corpo)
        self._cache = (mapa, self._agora())
        return mapa


__all__ = [
    "A_CONFIRMAR",
    "PREFIXO",
    "DopplerSecretProvider",
    "Interpretar",
    "RespostaHttp",
    "Transporte",
    "interpretar_descarga_plana",
]
