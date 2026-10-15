"""Configuracao do armazenamento, e o destino dos dados (KAM-011).

Espelho de `packages/core-ts/src/storage/config.ts`: as mesmas variaveis, as
mesmas recusas, as mesmas mensagens.

Dois assuntos num ficheiro, porque sao a mesma pergunta feita no arranque:
**"para onde e que isto vai escrever?"**

1. Onde esta o servidor — `endpoint`, `bucket`, `regiao`. E isto que deixa a
   decisao D6 aberta: trocar de SeaweedFS para um S3 gerido e trocar variaveis,
   nao codigo.
2. Em que **pais** e com que **fornecedor** ficam os bytes — `destino.country` e
   `destino.provider`. O ADR-008 diz que nenhum dado pessoal de producao sai de
   Angola sem o procedimento da APD, e o armazenamento guarda audio, fotos e
   documentos de identificacao. Um processo que nao sabe dizer em que pais
   escreve nao arranca.

O que este modulo **nao** faz: nao decide se um pais e "adequado". Nao ha lista
publica (`docs/tecnica/08` §8.3.1, NAO VERIFICADO), e o codigo nunca infere
adequacao a partir do pais. A regra e so a que o ticket escreve: em `prod`, fora
de `AO`, sem `apd_ref`, nao arranca. O *gate* de transferencia por tenant
(`tenant_destinations`) e do KAM-069, que le o `destino` daqui.

As credenciais **nao** sao configuracao: vem do `SecretProvider` (KAM-010),
pelas referencias `storage_access_key_id` e `storage_secret_access_key` do
inventario (`ops/secrets-inventory.yaml`).
"""

from __future__ import annotations

import os
import re
from collections.abc import Callable, Mapping
from dataclasses import dataclass
from datetime import datetime
from typing import Protocol

from ..secrets.port import AMBIENTES
from .guarda import ArmazenamentoPorTenant
from .port import StorageProvider
from .s3 import PARTE_POR_OMISSAO, MotorS3, Transporte
from .sigv4 import Credenciais

#: Nomes das variaveis de ambiente. Nenhuma delas e um segredo.
VAR_ENDPOINT = "KAMBA_STORAGE_ENDPOINT"
VAR_BUCKET = "KAMBA_STORAGE_BUCKET"
VAR_REGIAO = "KAMBA_STORAGE_REGION"
VAR_COUNTRY = "KAMBA_STORAGE_DESTINO_COUNTRY"
VAR_PROVIDER = "KAMBA_STORAGE_DESTINO_PROVIDER"
VAR_APD_REF = "KAMBA_STORAGE_DESTINO_APD_REF"

VARIAVEIS = (VAR_ENDPOINT, VAR_BUCKET, VAR_REGIAO, VAR_COUNTRY, VAR_PROVIDER, VAR_APD_REF)

#: O pais em que os dados podem ficar sem `apd_ref` (ADR-008).
PAIS_SEM_TRANSFERENCIA = "AO"

_PAIS = re.compile(r"[A-Z]{2}")
_FORNECEDOR = re.compile(r"[a-z][a-z0-9_-]{1,62}")
_BUCKET = re.compile(r"[a-z0-9][a-z0-9.-]{1,61}[a-z0-9]")
_REGIAO = re.compile(r"[a-z0-9][a-z0-9-]{0,62}")
_APD_REF = re.compile(r"[A-Za-z0-9][A-Za-z0-9._/:-]{0,127}")
#: O endpoint inteiro, numa so expressao e **sem** analisador de URL: os dois
#: analisadores (o do Node e o `urlsplit`) discordam em dezenas de casos de
#: fronteira, e uma expressao igual dos dois lados nao discorda em nenhum.
#: Esquema, anfitriao em minusculas (nome, IPv4 ou IPv6 entre parenteses
#: rectos), porta opcional, barra final opcional — e mais nada.
_ENDPOINT = re.compile(
    r"(https?)://([a-z0-9](?:[a-z0-9.-]{0,251}[a-z0-9])?|\[[0-9a-f:]{2,39}\])(?::([0-9]{1,5}))?/?"
)

#: O que se tira das pontas de um valor: espaco, tabulacao e mudancas de linha,
#: e so isso. O `strip()` do Python e o `trim()` do JavaScript nao tiram os
#: mesmos caracteres.
_BRANCOS = " \t\r\n"


@dataclass(frozen=True)
class DestinoDeArmazenamento:
    """Para onde vao os dados.

    Os tres campos tem os nomes de `tenant_destinations(provider, country,
    apd_ref)` (`docs/tecnica/08` §8.3.1) porque e essa a tabela que o KAM-069
    vai confrontar com isto.
    """

    #: ISO 3166-1 alfa-2, em maiusculas: `AO`, `ZA`.
    country: str
    #: Identificador do fornecedor, em minusculas.
    provider: str
    #: Referencia do procedimento na APD; `None` se nao ha.
    apd_ref: str | None


@dataclass(frozen=True)
class StorageConfig:
    endpoint: str
    bucket: str
    regiao: str
    destino: DestinoDeArmazenamento
    #: Avisos que nao impedem o arranque. Fora de `prod`, um destino fora de
    #: Angola sem `apd_ref` aparece aqui; este modulo nao regista nada.
    avisos: tuple[str, ...] = ()


class ConfigDeArmazenamentoError(ValueError):
    """A configuracao nao serve. A mensagem nomeia as variaveis, nunca os valores."""

    def __init__(self, problemas: list[str]) -> None:
        self.problemas = tuple(problemas)
        super().__init__(
            "configuracao de armazenamento invalida: " + "; ".join(problemas)
        )


class DestinoSemApdRefError(RuntimeError):
    """Em `prod`, o destino esta fora de Angola e nao ha `apd_ref`.

    E o "aviso bloqueante no arranque" do criterio de aceitacao 7: levanta, e
    quem arranca o servico nao tem como continuar sem o resolver.
    """

    def __init__(self, country: str, provider: str) -> None:
        self.country = country
        self.provider = provider
        super().__init__(
            f"armazenamento em prod com destino {country} (fornecedor {provider}) e "
            f"sem {VAR_APD_REF}: nenhum dado pessoal sai de Angola sem referencia da "
            "APD (ADR-008); o servico nao arranca"
        )


def _ler(env: Mapping[str, str], nome: str) -> str | None:
    valor = (env.get(nome) or "").strip(_BRANCOS)
    return valor or None


def ler_config(*, ambiente: str, env: Mapping[str, str] | None = None) -> StorageConfig:
    """Le e valida a configuracao. Falha com **todos** os problemas de uma vez.

    Levanta `ConfigDeArmazenamentoError` (variavel obrigatoria ausente ou mal
    formada) ou `DestinoSemApdRefError` (em `prod`, fora de `AO`, sem `apd_ref`).
    """
    if env is None:
        env = os.environ
    # Um ambiente fora do dominio nao e «nao e prod»: e nao saber onde se
    # esta. A regra do destino so bloqueia em `prod`, pelo que `PROD`,
    # `production` ou um valor vazio a desligavam em silencio (`ANALISE-09`, A1).
    if type(ambiente) is not str or ambiente not in AMBIENTES:
        raise ConfigDeArmazenamentoError(
            ["ambiente desconhecido (esperava " + ", ".join(AMBIENTES) + ")"]
        )
    problemas: list[str] = []

    def exigir(nome: str, forma: re.Pattern[str], descricao: str) -> str:
        valor = _ler(env, nome)
        if valor is None:
            problemas.append(f"{nome} em falta")
            return ""
        if forma.fullmatch(valor) is None:
            problemas.append(f"{nome} mal formada ({descricao})")
            return ""
        return valor

    endpoint = _ler(env, VAR_ENDPOINT) or ""
    if not endpoint:
        problemas.append(f"{VAR_ENDPOINT} em falta")
    else:
        m = _ENDPOINT.fullmatch(endpoint)
        porta = None if m is None or m.group(3) is None else int(m.group(3))
        if m is None or (porta is not None and not 0 < porta < 65536):
            # Sem repetir o valor: um endpoint com credenciais embutidas e
            # precisamente um dos casos recusados.
            problemas.append(
                f"{VAR_ENDPOINT} mal formada (esperava http(s)://anfitriao[:porta], "
                "sem caminho nem credenciais)"
            )
            endpoint = ""
        else:
            # A porta por omissao do esquema nao fica: e a forma que o cabecalho
            # `Host` leva, e a que e assinada.
            omissa = porta is None or (m.group(1), porta) in (("http", 80), ("https", 443))
            endpoint = f"{m.group(1)}://{m.group(2)}" + ("" if omissa else f":{porta}")

    bucket = exigir(VAR_BUCKET, _BUCKET, "nome de bucket S3, em minusculas")
    regiao = exigir(VAR_REGIAO, _REGIAO, "identificador de regiao, em minusculas")
    country = exigir(VAR_COUNTRY, _PAIS, "ISO 3166-1 alfa-2, em maiusculas")
    provider = exigir(VAR_PROVIDER, _FORNECEDOR, "identificador em minusculas")

    apd_ref = _ler(env, VAR_APD_REF)
    if apd_ref is not None and _APD_REF.fullmatch(apd_ref) is None:
        problemas.append(f"{VAR_APD_REF} mal formada (ate 128 caracteres, sem espacos)")
        apd_ref = None

    if problemas:
        raise ConfigDeArmazenamentoError(problemas)

    avisos: list[str] = []
    if country != PAIS_SEM_TRANSFERENCIA and apd_ref is None:
        if ambiente == "prod":
            raise DestinoSemApdRefError(country, provider)
        avisos.append(
            f"destino de armazenamento {country} sem {VAR_APD_REF}: "
            "em prod isto impede o arranque"
        )

    return StorageConfig(
        endpoint=endpoint,
        bucket=bucket,
        regiao=regiao,
        destino=DestinoDeArmazenamento(country=country, provider=provider, apd_ref=apd_ref),
        avisos=tuple(avisos),
    )


class CofreLeitor(Protocol):
    """O minimo da porta de segredos de que o armazenamento precisa."""

    def get(self, ref: str) -> str: ...


def criar_storage_s3(
    *,
    config: StorageConfig,
    secrets: CofreLeitor,
    transporte: Transporte | None = None,
    agora: Callable[[], datetime] | None = None,
    tamanho_da_parte: int = PARTE_POR_OMISSAO,
) -> StorageProvider:
    """Cria o armazenamento S3, ja com a guarda de isolamento.

    As credenciais sao pedidas ao `secrets` **em cada pedido** e nunca guardadas
    aqui: a cache, a janela de indisponibilidade e a rotacao sao do `Secrets` do
    KAM-010, e duplica-las aqui criava um segundo sitio onde uma chave revogada
    continuava viva.
    """

    def credenciais() -> Credenciais:
        return Credenciais(
            secrets.get("storage_access_key_id"),
            secrets.get("storage_secret_access_key"),
        )

    return ArmazenamentoPorTenant(
        MotorS3(
            endpoint=config.endpoint,
            bucket=config.bucket,
            regiao=config.regiao,
            credenciais=credenciais,
            transporte=transporte,
            agora=agora,
            tamanho_da_parte=tamanho_da_parte,
        )
    )
