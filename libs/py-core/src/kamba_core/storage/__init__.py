"""`kamba_core.storage` — a porta de armazenamento de objectos (KAM-011, ADR-014).

    from kamba_core.storage import Ctx, ObjectMeta, criar_storage_s3, ler_config, nova_chave

    storage = criar_storage_s3(config=ler_config(ambiente=ambiente), secrets=secrets)

    ctx = Ctx(tenant_id)
    key = nova_chave(ctx, "audio")
    ref = storage.put(ctx, key, dados, ObjectMeta("audio/ogg", "audio", retain_until))
    url = storage.sign_url(ctx, ref, ttl_seconds=60)

Trocar de servidor — SeaweedFS, S3 gerido — e trocar variaveis de ambiente
(`config.py`); a decisao D6 nao esta neste codigo. Nos testes,
`criar_storage_fake()` da a mesma porta sobre memoria.

**Os motores nao sao exportados daqui.** `MotorS3` e `MotorEmMemoria` nao tem
nocao de tenant; quem os usa directamente saltou o isolamento. As fabricas
devolvem a porta ja com a guarda.

Este subpacote **nao** e reexportado por `kamba_core`: quem nao usa
armazenamento nao paga o import.
"""

from .chave import PartesDaChave, nova_chave, partes_da_chave, prefixo_do_tenant
from .config import (
    PAIS_SEM_TRANSFERENCIA,
    VARIAVEIS,
    CofreLeitor,
    ConfigDeArmazenamentoError,
    DestinoDeArmazenamento,
    DestinoSemApdRefError,
    StorageConfig,
    criar_storage_s3,
    ler_config,
)
from .fake import RespostaFake, StorageFake, criar_storage_fake
from .port import (
    LIMITE_DE_LISTAGEM,
    TTL_MAXIMO_S,
    ArmazenamentoIndisponivelError,
    ChaveForaDoTenantError,
    ChaveInvalidaError,
    Corpo,
    Ctx,
    CtxEmFaltaError,
    ListagemTruncadaError,
    MetaInvalidaError,
    ObjectInfo,
    ObjectKey,
    ObjectMeta,
    ObjectoInexistenteError,
    ObjectRef,
    RespostaDoMotorInvalidaError,
    StorageProvider,
    TenantInvalidoError,
    TtlInvalidoError,
)

__all__ = [
    "LIMITE_DE_LISTAGEM",
    "PAIS_SEM_TRANSFERENCIA",
    "TTL_MAXIMO_S",
    "VARIAVEIS",
    "ArmazenamentoIndisponivelError",
    "ChaveForaDoTenantError",
    "ChaveInvalidaError",
    "CofreLeitor",
    "ConfigDeArmazenamentoError",
    "Corpo",
    "Ctx",
    "CtxEmFaltaError",
    "DestinoDeArmazenamento",
    "DestinoSemApdRefError",
    "ListagemTruncadaError",
    "MetaInvalidaError",
    "ObjectInfo",
    "ObjectKey",
    "ObjectMeta",
    "ObjectRef",
    "ObjectoInexistenteError",
    "PartesDaChave",
    "RespostaDoMotorInvalidaError",
    "RespostaFake",
    "StorageConfig",
    "StorageFake",
    "StorageProvider",
    "TenantInvalidoError",
    "TtlInvalidoError",
    "criar_storage_fake",
    "criar_storage_s3",
    "ler_config",
    "nova_chave",
    "partes_da_chave",
    "prefixo_do_tenant",
]
