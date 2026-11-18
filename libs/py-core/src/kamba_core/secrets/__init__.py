"""`kamba_core.secrets` — a porta de segredos do lado Python (KAM-010).

    from kamba_core.secrets import EnvSecretProvider, Secrets

    secrets = Secrets.arrancar(
        servico="agr",
        provider=EnvSecretProvider(ambiente="dev"),
        obrigatorios=["llm_litellm_master_key"],
    )
    actual, anterior = secrets.get_ring("llm_litellm_master_key")

Trocar de implementacao e trocar a linha do `provider` — e esse o conteudo
verificavel de "trocar de implementacao e so configuracao", e a suite
`libs/py-core/tests/test_secrets_contrato.py` corre a mesma bateria sobre as
tres implementacoes.

Este subpacote **nao** e reexportado por `kamba_core`: quem nao usa segredos nao
paga o import.
"""

from .arranque import TTL_ULTIMO_VALOR_S, ArranqueAbortadoError, Secrets
from .doppler import (
    A_CONFIRMAR,
    DopplerSecretProvider,
    Interpretar,
    RespostaHttp,
    Transporte,
    interpretar_descarga_plana,
)
from .env import (
    PREFIXO,
    SUFIXO_ANTERIOR,
    VERSOES,
    EnvSecretProvider,
    nome_da_variavel,
)
from .kid import (
    ROTULOS_POSICIONAIS,
    KidRepetidoNoCofreError,
    kid_do_valor,
    kids_das_versoes,
    separar_kid,
)
from .openbao_fake import OpenBaoFakeProvider
from .port import (
    AMBIENTES,
    AmbienteErradoError,
    CofreInacessivelError,
    SecretAusenteError,
    SecretProvider,
    SecretRef,
    SecretRefInvalidaError,
    e_ambiente,
    familia_da_ref,
    validar_ref,
)

__all__ = [
    "AMBIENTES",
    "A_CONFIRMAR",
    "PREFIXO",
    "ROTULOS_POSICIONAIS",
    "SUFIXO_ANTERIOR",
    "TTL_ULTIMO_VALOR_S",
    "VERSOES",
    "AmbienteErradoError",
    "ArranqueAbortadoError",
    "CofreInacessivelError",
    "DopplerSecretProvider",
    "EnvSecretProvider",
    "Interpretar",
    "KidRepetidoNoCofreError",
    "OpenBaoFakeProvider",
    "RespostaHttp",
    "SecretAusenteError",
    "SecretProvider",
    "SecretRef",
    "SecretRefInvalidaError",
    "Secrets",
    "Transporte",
    "e_ambiente",
    "familia_da_ref",
    "interpretar_descarga_plana",
    "kid_do_valor",
    "kids_das_versoes",
    "nome_da_variavel",
    "separar_kid",
    "validar_ref",
]
