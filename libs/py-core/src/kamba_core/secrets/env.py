"""`EnvSecretProvider` — a implementacao de ambiente (KAM-010).

Espelho de `packages/core-ts/src/secrets/env.ts`. Nao e um brinquedo de `dev`:
o `ADR-L002` escolhe **variaveis de ambiente injectadas no arranque do
contentor** como mecanismo de injeccao em todos os ambientes do Piloto, pelo que
esta classe e tambem o caminho de producao. Em `staging` e `prod` quem enche o
ambiente e o lancador do cofre (`doppler run -- ...`); o processo continua a ler
daqui.

Nao le ficheiros, nao vai a rede e nao tem cache: o ambiente de um processo nao
muda depois do `exec`.
"""

from __future__ import annotations

import os
import re
from collections.abc import Mapping

from .port import (
    CofreInacessivelError,
    SecretAusenteError,
    SecretRef,
    SecretRefInvalidaError,
    validar_ref,
)

#: Prefixo de todas as variaveis que este provedor le.
PREFIXO = "KAMBA_SECRET_"

#: Sufixo da variavel que guarda a versao anterior de um segredo.
SUFIXO_ANTERIOR = "_ANTERIOR"

#: Rotulos de versao que este provedor sabe produzir, do mais recente ao mais antigo.
VERSOES = ("actual", "anterior")

_NAO_ALFANUMERICO = re.compile(r"[^A-Za-z0-9]")


def nome_da_variavel(ref: SecretRef) -> str:
    """Nome da variavel de ambiente que guarda uma referencia.

    A familia (a parte antes de `/`) sobe a maiusculas, porque e `snake_case`
    conhecido e le-se melhor num `.env`. A instancia (a parte depois de `/`)
    **mantem a caixa**, com os caracteres fora de `[A-Za-z0-9]` trocados por
    `_`: se subisse a maiusculas, duas referencias que diferem so na caixa
    passariam a designar a mesma variavel, e um tenant leria o token de outro. O
    separador `__` marca a fronteira entre familia e instancia.

        meta_app_secret            -> KAMBA_SECRET_META_APP_SECRET
        meta_client_token/7f3cAb   -> KAMBA_SECRET_META_CLIENT_TOKEN__7f3cAb

    **Limite conhecido:** em Windows as variaveis de ambiente nao distinguem
    maiusculas de minusculas, pelo que a garantia de unicidade acima vale em
    Linux (onde os servicos correm, `docs/tecnica/09` §3.1).
    """
    limpo = validar_ref(ref)
    familia, _, instancia = limpo.partition("/")
    if instancia == "":
        return PREFIXO + familia.upper()
    return f"{PREFIXO}{familia.upper()}__{_NAO_ALFANUMERICO.sub('_', instancia)}"


class EnvSecretProvider:
    """Provedor que le o ambiente do processo."""

    def __init__(self, ambiente: str, env: Mapping[str, str] | None = None) -> None:
        self.nome = "env"
        self.ambiente = ambiente
        self._env: Mapping[str, str] = os.environ if env is None else env

    def health(self) -> None:
        """O ambiente esta sempre acessivel.

        Se o processo arrancou, o seu ambiente existe. Um ambiente **vazio** nao
        e um cofre em baixo — e um segredo ausente, e quem o descobre e `get`,
        com o nome do segredo na mensagem.
        """
        if not isinstance(self._env, Mapping):  # pragma: no cover - defesa
            raise CofreInacessivelError(self.nome, "ambiente do processo indisponivel")

    def get(self, ref: SecretRef) -> str:
        valor = self._ler(nome_da_variavel(ref))
        if valor is None:
            raise SecretAusenteError(validar_ref(ref), self.nome)
        return valor

    def get_ring(self, ref: SecretRef) -> tuple[str, str | None]:
        base = nome_da_variavel(ref)
        actual = self._ler(base)
        if actual is None:
            raise SecretAusenteError(validar_ref(ref), self.nome)
        return actual, self._ler(base + SUFIXO_ANTERIOR)

    def versions(self, ref: SecretRef) -> tuple[str, ...]:
        base = nome_da_variavel(ref)
        if self._ler(base) is None:
            raise SecretAusenteError(validar_ref(ref), self.nome)
        if self._ler(base + SUFIXO_ANTERIOR) is None:
            return ("actual",)
        return VERSOES

    def _ler(self, nome: str) -> str | None:
        """Le uma variavel, tratando o vazio como ausencia.

        `KAMBA_SECRET_X=` e um erro de configuracao que se parece com um segredo
        definido. Tratar o vazio como ausente faz o servico falhar no arranque
        com o nome do segredo — em vez de assinar pedidos com a chave vazia e
        descobri-lo quando a Meta devolver 401.
        """
        bruto = self._env.get(nome)
        if bruto is None:
            return None
        valor = bruto.strip()
        return None if valor == "" else valor


__all__ = [
    "PREFIXO",
    "SUFIXO_ANTERIOR",
    "VERSOES",
    "EnvSecretProvider",
    "SecretRefInvalidaError",
    "nome_da_variavel",
]
