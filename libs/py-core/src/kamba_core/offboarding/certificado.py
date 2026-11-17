"""A fase `certificado` do off-boarding (KAM-098, criterio 8).

O certificado de eliminacao, no D30, depois da purga: o que saiu (por tabela,
com as linhas, lido do `purge_log` da execucao) e o que ficou (por classe ou
tabela, **com o fundamento**), o prazo de expiracao das copias de seguranca, o
`sha256` do documento e a assinatura.

## O que o certificado nao afirma

**Nao afirma que as copias de seguranca foram apagadas**, porque nao foram: as
copias nao se reescrevem, expiram pelo ciclo do repositorio (35 dias, o
`retencao_dias` do `infra/backup/cobertura.yaml`, KAM-079), e o que as protege
depois de um restauro e a reaplicacao da purga. O certificado diz a data ate a
qual uma copia ainda pode ter os dados, e mais nada. O prazo entra por
argumento, sem omissao: um numero escrito aqui era uma segunda leitora do
ciclo, e um ensaio confronta o que se passa com o do ficheiro.

## A assinatura e HMAC, e diz-se

O bloco diz «assinado digitalmente». Nao ha assinatura assimetrica nesta
plataforma (o `keyring` do KAM-072 e HMAC-SHA256, por versao de chave): o
certificado leva `alg = HMAC-SHA256` e o `kid`, e verifica-o quem tem a chave —
a KAMBA, perante uma auditoria ou a APD. Um titular nao o verifica sozinho, e
isso e uma leitura que diverge da letra: fica escrita no bloco, e nao se marca
como cumprida.
"""

from __future__ import annotations

import hashlib
import hmac
import json
from collections.abc import Callable
from datetime import datetime, timedelta
from typing import Any, Final

from .. import tenant_guard
from ..direitos.exportacao import documento, resumo
from ..retencao import politica
from .contrato import FaseForaDeOrdem, auditar, exigir_pedido_vivo, ler_fases, marcar

#: A versao do formato do certificado, em SemVer.
VERSAO_DO_CERTIFICADO: Final = "1.0.0"

ALGORITMO: Final = "HMAC-SHA256"

#: Os fundamentos do que fica, por tabela sem caminho. Cada um e o que o
#: titular le, e por isso e prosa e nao codigo.
FUNDAMENTO_FISCAL: Final = (
    "registo fiscal: fica pelo prazo do Codigo Geral Tributario, que esta NAO VERIFICADO "
    "(sem fiscal_retention_years definido, nada fiscal se apaga)"
)
FUNDAMENTO_SEM_CAMINHO: Final = (
    "sem caminho de eliminacao automatica nesta versao da plataforma; fica ate ser apagado "
    "por um caminho que o registe"
)
FUNDAMENTO_REFERENCIADA: Final = (
    "referenciada pelos registos fiscais, que ficam; sai com eles"
)

#: As tabelas que ficam por serem referenciadas pelo que e fiscal.
REFERENCIADAS_PELO_FISCAL: Final = frozenset({"platform.tenants", "platform.payment_accounts"})

#: Quem entrega o certificado ao titular pelo canal disponivel. Devolve se entregou.
EntregarAoTitular = Callable[[str, bytes], bool]
AbrirLigacao = Callable[[], Any]

SQL_REGISTOS_DA_EXECUCAO: Final = """
  SELECT tabela, resultado, motivo, linhas
    FROM platform.purge_log
   WHERE execucao_id = %s::uuid AND tenant_id = %s::uuid
   ORDER BY tabela, resultado
"""


def _em_batch(abrir: AbrirLigacao, job: str, trabalho: Callable[[Any], Any]) -> Any:
    ligacao = abrir()
    try:
        with tenant_guard.tx_batch(ligacao, job) as cursor:
            return trabalho(cursor)
    finally:
        ligacao.close()


def montar(
    tenant_id: str,
    emitido_at: datetime,
    registos: list[tuple[str, str, str | None, int]],
    *,
    copias_expiram_em_dias: int,
    anos_fiscais: int | None,
) -> dict[str, Any]:
    """O documento, sem a assinatura. Puro."""
    if type(copias_expiram_em_dias) is not int or copias_expiram_em_dias < 1:
        raise ValueError("o ciclo das copias e um numero de dias positivo")
    apagadas: dict[str, int] = {}
    retidas: dict[str, str] = {}
    for tabela, resultado, _motivo, linhas in registos:
        if resultado == "ok":
            apagadas[tabela] = apagadas.get(tabela, 0) + int(linhas)
        elif tabela in REFERENCIADAS_PELO_FISCAL:
            retidas[tabela] = FUNDAMENTO_REFERENCIADA
        else:
            retidas[tabela] = FUNDAMENTO_SEM_CAMINHO
    fiscais = [c for c in politica.POLITICA if c.fiscal]
    return {
        "versao": VERSAO_DO_CERTIFICADO,
        "tenant_id": tenant_id,
        "emitido_at": emitido_at.isoformat(),
        "apagadas": [{"tabela": t, "linhas": n} for t, n in sorted(apagadas.items())],
        "retidas": [
            *({"classe": c.nome, "fundamento": FUNDAMENTO_FISCAL} for c in fiscais),
            *({"tabela": t, "fundamento": f} for t, f in sorted(retidas.items())),
        ],
        "prazo_fiscal": {"fiscal_retention_years": anos_fiscais, "estado": "NAO VERIFICADO"},
        "copias_de_seguranca": {
            "apagamento_afirmado": False,
            "podem_conter_dados_ate": (emitido_at + timedelta(days=copias_expiram_em_dias)).isoformat(),
            "nota": (
                "as copias de seguranca nao se reescrevem: expiram pelo ciclo, e a purga "
                "volta a correr depois de qualquer restauro"
            ),
        },
    }


def assinar(doc: dict[str, Any], chave: bytes, kid: str) -> dict[str, Any]:
    """O documento com o `sha256` e a assinatura sobre os bytes canonicos dele."""
    if len(chave) < 32:
        raise ValueError("a chave do certificado tem pelo menos 32 bytes")
    corpo = documento(doc)
    return {
        **doc,
        "sha256": resumo(corpo),
        "assinatura": {"alg": ALGORITMO, "kid": kid,
                       "valor": hmac.new(chave, corpo, hashlib.sha256).hexdigest()},
    }


def verificar_certificado(certificado: dict[str, Any], chave: bytes) -> bool:
    """Se o certificado nao foi mexido desde que foi assinado."""
    doc = {k: v for k, v in certificado.items() if k not in ("sha256", "assinatura")}
    corpo = documento(doc)
    valor = hmac.new(chave, corpo, hashlib.sha256).hexdigest()
    return (
        certificado.get("sha256") == resumo(corpo)
        and certificado.get("assinatura", {}).get("alg") == ALGORITMO
        and hmac.compare_digest(str(certificado["assinatura"].get("valor", "")), valor)
    )


def emitir_certificado(
    abrir_batch: AbrirLigacao,
    tenant_id: str,
    agora: datetime,
    *,
    chave: bytes,
    kid: str,
    copias_expiram_em_dias: int,
    entregar: EntregarAoTitular,
    anos_fiscais: int | None = None,
) -> dict[str, Any]:
    """Emite, entrega e conclui a fase `certificado`. Repetir devolve o que ja foi emitido.

    So depois da purga concluida: uma purga suspensa por disputa nao tem
    certificado, porque nao acabou. Se a entrega falhar, a fase fica `em_curso`
    com o `sha256` e a proxima chamada volta a entregar o mesmo documento (a
    data de emissao e a da primeira).
    """
    tenant_id = tenant_guard.normalizar_tenant(tenant_id)

    def ler(cursor: Any) -> tuple[dict[str, Any], list[tuple[str, str, str | None, int]]]:
        fases = ler_fases(cursor, tenant_id)
        exigir_pedido_vivo(fases, "certificado")
        purga = fases["purga"]
        if purga.estado != "concluida":
            raise FaseForaDeOrdem("a fase certificado nao pode correr: a purga nao foi concluida")
        cursor.execute(SQL_REGISTOS_DA_EXECUCAO, (purga.resultado["execucao_id"], tenant_id))
        return dict(fases["certificado"].resultado), [tuple(r) for r in cursor.fetchall()]

    anterior, registos = _em_batch(abrir_batch, "offboarding_certificado", ler)
    if anterior.get("entregue"):
        return anterior
    emitido_at = datetime.fromisoformat(anterior["emitido_at"]) if "emitido_at" in anterior else agora
    certificado = assinar(
        montar(tenant_id, emitido_at, registos,
               copias_expiram_em_dias=copias_expiram_em_dias, anos_fiscais=anos_fiscais),
        chave, kid,
    )
    corpo = json.dumps(certificado, sort_keys=True, ensure_ascii=False, indent=2).encode("utf-8")
    entregue = bool(entregar(tenant_id, corpo))
    resultado = {
        "sha256": certificado["sha256"],
        "kid": kid,
        "versao": VERSAO_DO_CERTIFICADO,
        "emitido_at": emitido_at.isoformat(),
        "entregue": entregue,
    }

    def gravar(cursor: Any) -> None:
        marcar(cursor, tenant_id, "certificado", "concluida" if entregue else "em_curso", resultado)
        auditar(cursor, tenant_id, "certificado", f"{certificado['sha256']}:{entregue}")

    _em_batch(abrir_batch, "offboarding_certificado", gravar)
    return {**resultado, "certificado": certificado}


__all__ = [
    "ALGORITMO",
    "VERSAO_DO_CERTIFICADO",
    "assinar",
    "emitir_certificado",
    "montar",
    "verificar_certificado",
]
