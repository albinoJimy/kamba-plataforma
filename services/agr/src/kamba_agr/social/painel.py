"""A pagina Social do painel do dono, do lado do AGR (KAM-246).

O `onboarding-web` **nao** le o STO nem tem a chave da ligacao: pede ao AGR, por
duas rotas `/internal`, a lista e a abertura (decisao do fundador de
2026-11-23, Q2 = A, bloco do KAM-246). Com a credencial do painel
(`agr_painel_token`, KAM-223), e com o tenant **da sessao do painel**, que o
`onboarding-web` poe no corpo e o AGR trata como o `/internal/turn` do painel
trata o dele.

    POST /internal/social/itens      os itens `aprovado` e `entregue` com arte:
                                     a legenda, a nota do rotulo de IA, a imagem
                                     (um URL do STO de cinco minutos) e a ligacao
                                     de descarga de 24 h
    POST /internal/social/descarga   a ligacao, aberta: um URL do STO de cinco
                                     minutos, ou 404

## A ligacao de 24 h

E a primitiva do KAM-098 (`ligacao_assinada` e `abrir_ligacao`, dicionario
§3.77), com a chave `chave_da_ligacao_de_descarga` (Q3 = A): um *token*
HMAC-SHA256 com o tenant, a chave do objecto e a validade. **Nao e o URL do
STO**, que vale cinco minutos: cada abertura assina um novo. Assina com a chave
actual do anel e abre com qualquer das duas, para uma rotacao nao matar as
ligacoes vivas.

**Uma ligacao expirada, adulterada ou de outro tenant da o mesmo 404**, que nao
diz se o item existe: dizer qual das tres ensinava a quem forja o que mudar, e
um 403 a uma ligacao de outro tenant confirmava que ela e de alguem.

## O endpoint publico do STO (decisao do fundador de 2026-11-23, A)

A imagem e a descarga sao URLs do STO que o **navegador** abre, e o endpoint
com que o AGR fala com o STO (`KAMBA_STORAGE_ENDPOINT`) pode ser interno: com o
perfil `sto-proprio`, o `seaweedfs` vive na rede `data`, que nao sai. Por isso
os URLs assinam-se com um endpoint proprio, `KAMBA_STORAGE_ENDPOINT_PUBLICO`,
usado **so** para assinar (`assinador_publico`). Fora de `dev` tem de ser
`https`, e sem ele as duas rotas respondem 503 `painel_por_ligar`: **nunca**
caem para o endpoint interno. Em `dev`, sem ele, assina-se com o do AGR. Que o
STO tenha esse endpoint e da D6, e tem credor no bloco do KAM-246.

## O custo aceite

O painel depende de o AGR estar de pe: sem ele, a pagina responde 503 e nao
mostra nada. E o custo que o fundador aceitou para nao dar as credenciais do
STO ao servico exposto a Internet.
"""

from __future__ import annotations

import dataclasses
import datetime
import json
import os
from collections.abc import Callable, Mapping, Sequence
from typing import Any, Final

from kamba_core import tenant_guard
from kamba_core.offboarding.contrato import LigacaoRecusada
from kamba_core.offboarding.exportacao import abrir_ligacao, ligacao_assinada
from kamba_core.storage import criar_storage_s3, ler_config
from kamba_core.storage.config import VAR_ENDPOINT, StorageConfig
from kamba_core.storage.port import TTL_MAXIMO_S, Ctx, ObjectRef, StorageProvider
from starlette.concurrency import run_in_threadpool
from starlette.requests import Request
from starlette.responses import JSONResponse
from starlette.routing import Route

from . import regras
from .publicacao import NOTA_DO_ROTULO_DE_IA
from .repositorio import Item

#: As duas rotas. Dicionario §3.82.
ROTA_DOS_ITENS: Final = "/internal/social/itens"
ROTA_DA_DESCARGA: Final = "/internal/social/descarga"

#: O endpoint do STO com que se assinam os URLs que o navegador abre (decisao
#: do fundador de 2026-11-23, A). Nao e segredo. Ver a nota do modulo.
VAR_ENDPOINT_PUBLICO: Final = "KAMBA_STORAGE_ENDPOINT_PUBLICO"

#: O `id` do segredo da ligacao no inventario (Q3 = A).
SEGREDO_DA_LIGACAO: Final = "chave_da_ligacao_de_descarga"

#: O tamanho minimo da chave, em octetos: o da primitiva do KAM-098.
TAMANHO_MINIMO_DA_CHAVE: Final = 32

#: O tecto do corpo das duas rotas: um `tenant_id` e uma ligacao (que leva a
#: chave do objecto e a assinatura em base64) cabem em menos de 1 KiB.
CORPO_MAXIMO: Final = 2 * 1024

#: O tecto de uma ligacao, em caracteres. Um *token* do KAM-098 com uma chave do
#: STO tem cerca de 230.
MAXIMO_DA_LIGACAO: Final = 1024


class CorpoInvalidoError(ValueError):
    """O corpo nao tem a forma da rota."""


class PainelPorLigarError(RuntimeError):
    """Sem a chave da ligacao ou sem o assinador publico: as duas rotas respondem 503."""


def assinador_publico(
    *,
    armazenamento: StorageProvider,
    config: StorageConfig,
    segredos: Any,
    ambiente: str,
    env: Mapping[str, str] | None = None,
) -> StorageProvider | None:
    """O STO com o endpoint publico, **so para assinar**; `None` fecha o painel (503).

    O endpoint publico tem a forma do `KAMBA_STORAGE_ENDPOINT` (o `ler_config`
    confere-a) e, fora de `dev`, o esquema `https`: um `http` numa pagina `https`
    e conteudo misto, e um URL assinado em claro. Sem ele, ou fora da forma, fora
    de `dev` devolve `None` e **nao** o `armazenamento` do AGR, cujo endpoint pode
    ser interno. Em `dev`, sem ele, devolve o `armazenamento`.
    """
    if env is None:
        env = os.environ
    bruto = (env.get(VAR_ENDPOINT_PUBLICO) or "").strip()
    if not bruto:
        return armazenamento if ambiente == "dev" else None
    try:
        publico = ler_config(ambiente=ambiente, env={**env, VAR_ENDPOINT: bruto}).endpoint
    except Exception:  # noqa: BLE001 — um endpoint publico sem forma e o painel por ligar
        return None
    if ambiente != "dev" and not publico.startswith("https://"):
        return None
    return criar_storage_s3(config=dataclasses.replace(config, endpoint=publico), secrets=segredos)


def _agora() -> datetime.datetime:
    return datetime.datetime.now(datetime.UTC)


class PainelDoSocial:
    """A lista e a abertura. As portas sao funcoes, para se ensaiar sem base.

    * `itens(tenant_id)` le os itens do painel (`RepositorioSql.itens_do_painel`,
      numa ligacao `kamba_app`, sob a RLS do tenant);
    * `assinador` e o STO com o endpoint publico (`assinador_publico`), so para
      assinar; `None` e o painel por ligar (503);
    * `chaves()` devolve o anel da chave da ligacao, a actual primeiro, lido do
      cofre **a cada pedido**: o segredo roda.
    """

    __slots__ = ("_itens", "_assinador", "_chaves", "_relogio")

    def __init__(
        self,
        *,
        itens: Callable[[str], Sequence[Item]],
        assinador: StorageProvider | None,
        chaves: Callable[[], Sequence[bytes]],
        relogio: Callable[[], datetime.datetime] = _agora,
    ) -> None:
        self._itens = itens
        self._assinador = assinador
        self._chaves = chaves
        self._relogio = relogio

    def _anel(self) -> list[bytes]:
        """As chaves da ligacao, ou `PainelPorLigarError`: sem elas, o painel esta por ligar.

        Qualquer falha do cofre (um segredo ausente ou revogado) e a mesma coisa,
        e nao um 500 nem um 404: nao depende da ligacao que veio no pedido.
        """
        try:
            chaves = list(self._chaves())
        except Exception as erro:  # noqa: BLE001 — o cofre a falhar e o painel por ligar
            raise PainelPorLigarError("sem chave da ligacao") from erro
        if not chaves:
            raise PainelPorLigarError("sem chave da ligacao")
        return chaves

    def _assinador_ou_fechado(self) -> StorageProvider:
        """O assinador publico, ou `PainelPorLigarError`: nunca o endpoint interno."""
        if self._assinador is None:
            raise PainelPorLigarError("sem o endpoint publico do STO")
        return self._assinador

    def listar(self, tenant_id: str) -> list[dict[str, Any]]:
        """Os itens do tenant, com a imagem de cinco minutos e a ligacao de 24 h."""
        tenant = tenant_guard.normalizar_tenant(tenant_id)
        agora = self._relogio()
        actual = self._anel()[0]
        assinador = self._assinador_ou_fechado()
        vistos: list[dict[str, Any]] = []
        for item in self._itens(tenant):
            if item.arte_ref is None:
                continue
            ref = ObjectRef(item.arte_ref, 0)
            vistos.append(
                {
                    "referencia": regras.referencia_do_item(item.content_item_id),
                    "estado": item.estado,
                    "tema": item.tema,
                    "legenda": item.legenda or "",
                    "nota": NOTA_DO_ROTULO_DE_IA if item.is_ai_generated else None,
                    # A porta do STO recusa uma chave fora do tenant do contexto.
                    "imagem": assinador.sign_url(Ctx(tenant), ref, ttl_seconds=TTL_MAXIMO_S),
                    "ligacao": ligacao_assinada(actual, tenant, item.arte_ref, agora),
                }
            )
        return vistos

    def abrir(self, tenant_id: str, ligacao: str) -> str:
        """O URL do STO de cinco minutos, ou `LigacaoRecusada` — a mesma para tudo."""
        tenant = tenant_guard.normalizar_tenant(tenant_id)
        agora = self._relogio()
        assinador = self._assinador_ou_fechado()
        for chave in self._anel():
            try:
                return abrir_ligacao(chave, ligacao, tenant, agora, assinador)
            except LigacaoRecusada:
                continue
        raise LigacaoRecusada("ligacao recusada")


def itens_pela_base(abrir_ligacao: Callable[[], Any]) -> Callable[[str], Sequence[Item]]:
    """A porta `itens` sobre uma ligacao `kamba_app` por leitura, fechada no fim.

    A leitura e a da TLS (`RepositorioSql.itens_do_painel`), sob a RLS do tenant.
    """
    from ..tls.social import RepositorioSql  # noqa: PLC0415 — a TLS importa este pacote

    def itens(tenant_id: str) -> Sequence[Item]:
        ligacao = abrir_ligacao()
        try:
            return RepositorioSql(ligacao).itens_do_painel(tenant_id)
        finally:
            try:
                ligacao.close()
            except Exception:  # noqa: BLE001 — a leitura ja acabou
                pass

    return itens


def anel_da_ligacao(ler: Callable[[], Sequence[str]]) -> Callable[[], list[bytes]]:
    """O anel do cofre (`get_ring`) em bytes, a actual primeiro, sem vazios.

    Cada valor e texto UTF-8 com pelo menos 32 octetos: a primitiva do KAM-098
    recusa uma chave mais curta, e por isso uma chave curta e uma ligacao que
    nao se assina — fecha, nao abre.
    """

    def chaves() -> list[bytes]:
        valores = [b for b in (v.encode("utf-8") for v in ler() if v) if len(b) >= TAMANHO_MINIMO_DA_CHAVE]
        if not valores:
            raise PainelPorLigarError("sem chave da ligacao")
        return valores

    return chaves


def _ler(corpo_cru: bytes, campos: tuple[str, ...]) -> dict[str, str]:
    if len(corpo_cru) > CORPO_MAXIMO:
        raise CorpoInvalidoError("corpo_grande")
    try:
        corpo = json.loads(corpo_cru)
    except ValueError:
        raise CorpoInvalidoError("json") from None
    if not isinstance(corpo, dict) or set(corpo) != set(campos):
        raise CorpoInvalidoError("campos")
    if not all(isinstance(corpo[c], str) and corpo[c] for c in campos):
        raise CorpoInvalidoError("tipos")
    try:
        corpo["tenant_id"] = tenant_guard.normalizar_tenant(corpo["tenant_id"])
    except Exception:  # noqa: BLE001 — um tenant sem forma e um corpo invalido
        raise CorpoInvalidoError("tenant") from None
    if len(corpo.get("ligacao", "")) > MAXIMO_DA_LIGACAO:
        raise CorpoInvalidoError("ligacao")
    return corpo


def rotas(credencial: Callable[[], str] | None, painel: PainelDoSocial | None) -> list[Route]:
    """As duas rotas. `credencial` e o `agr_painel_token`; sem ela, 401.

    | Caso | Estado |
    |---|---|
    | sem credencial, credencial errada, ou por configurar | 401 |
    | corpo fora da forma | 400 `corpo_invalido` |
    | o painel por ligar (sem STO ou sem a chave da ligacao) | 503 `painel_por_ligar` |
    | a lista | 200 `{"itens": [...]}` |
    | a ligacao aberta | 200 `{"url": ...}` |
    | a ligacao expirada, adulterada ou de outro tenant | 404 `ligacao_recusada` |
    """
    # Dentro da funcao: o `api_interna` arrasta o grafo, que estas rotas nao precisam.
    from ..api_interna import _autenticado_ou_fechado, _nao_autorizado

    def _por_ligar() -> JSONResponse:
        return JSONResponse({"outcome": "painel_por_ligar"}, status_code=503)

    async def itens(pedido: Request) -> JSONResponse:
        if not _autenticado_ou_fechado(pedido, credencial):
            return _nao_autorizado()
        try:
            corpo = _ler(await pedido.body(), ("tenant_id",))
        except CorpoInvalidoError as erro:
            return JSONResponse({"outcome": "corpo_invalido", "error_code": str(erro)}, status_code=400)
        if painel is None:
            return _por_ligar()
        try:
            # Na *threadpool*: a leitura da base e a assinatura nao param a *event loop*.
            itens_do_tenant = await run_in_threadpool(painel.listar, corpo["tenant_id"])
            return JSONResponse({"itens": itens_do_tenant}, status_code=200)
        except PainelPorLigarError:
            return _por_ligar()

    async def descarga(pedido: Request) -> JSONResponse:
        if not _autenticado_ou_fechado(pedido, credencial):
            return _nao_autorizado()
        try:
            corpo = _ler(await pedido.body(), ("tenant_id", "ligacao"))
        except CorpoInvalidoError as erro:
            return JSONResponse({"outcome": "corpo_invalido", "error_code": str(erro)}, status_code=400)
        if painel is None:
            return _por_ligar()
        try:
            url = await run_in_threadpool(painel.abrir, corpo["tenant_id"], corpo["ligacao"])
        except PainelPorLigarError:
            return _por_ligar()
        except LigacaoRecusada:
            return JSONResponse({"outcome": "ligacao_recusada"}, status_code=404)
        return JSONResponse({"url": url}, status_code=200)

    return [
        Route(ROTA_DOS_ITENS, itens, methods=["POST"]),
        Route(ROTA_DA_DESCARGA, descarga, methods=["POST"]),
    ]


__all__ = [
    "CORPO_MAXIMO",
    "CorpoInvalidoError",
    "PainelDoSocial",
    "PainelPorLigarError",
    "VAR_ENDPOINT_PUBLICO",
    "ROTA_DA_DESCARGA",
    "ROTA_DOS_ITENS",
    "SEGREDO_DA_LIGACAO",
    "anel_da_ligacao",
    "assinador_publico",
    "itens_pela_base",
    "rotas",
]
