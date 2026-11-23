"""A aprovacao do dono (KAM-122, criterio 5): o `hash` e a `ref` da accao.

    hash_da_aprovacao(legenda, arte_sha256, versao)  -> 64 hexadecimais
    ref_da_accao(content_item_id, hash, tentativa)   -> "{id}/{hash}[/reforcada][/{n}]"
    ler_ref(ref)                                     -> RefLida | None

Pela decisao do fundador de 2026-11-21 (D4, opcao A, precedente do KAM-119 e do
KAM-123), o botao Aprovar e o `confirm:{action_id}` de uma accao
`aprovar_conteudo` da `owner_actions` (KAM-118), e a `ref` dela e
`{content_item_id}/{hash}`. A barra separa-a da `ref` do catalogo
(`{ingestao}:{versao_texto}`): o `_ler_ref` de um nao le a do outro, e um botao
de um modulo nunca executa o outro.

## O `hash` liga a aprovacao ao que o dono viu

E o SHA-256 de `[legenda, sha256 da arte, versao]` em JSON canonico, gravado no
item quando a aprovacao se pede. **Qualquer edicao muda-o**: uma legenda nova
ou uma arte nova dao outro `hash`, logo outra `ref`, logo outro botao — e o
botao antigo, confirmado depois, recusa com `aprovacao_invalidada`. A base
recusa a mesma coisa por baixo: um item `aprovado` nao muda a legenda nem a
arte sem voltar a `pendente_aprovacao` (gatilho da `0085`).

## A revisao reforcada pede uma confirmacao a mais

Um item que o screening marcou `condicional` (KAM-121, criterio 5: «exige
confirmacao extra») nao se aprova com um botao so. O primeiro Aprovar nao
aprova: propoe uma **segunda** accao do mesmo `hash`, com o sufixo
`/reforcada` na `ref`, e e o botao dessa que aprova. A segunda e outra linha da
`owner_actions`, com a sua validade e o seu *compare-and-set*.
"""

from __future__ import annotations

import hashlib
import json
import re
from typing import Final, NamedTuple

_UUID: Final = r"[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}"
_REF: Final = re.compile(rf"({_UUID})/([0-9a-f]{{64}})(/reforcada)?(?:/[0-9]{{1,3}})?")
SUFIXO_REFORCADO: Final = "reforcada"


class RefLida(NamedTuple):
    content_item_id: str
    hash: str
    reforcada: bool


def hash_da_aprovacao(legenda: str, arte_sha256: str, versao: int) -> str:
    corpo = json.dumps([legenda, arte_sha256, int(versao)], ensure_ascii=False, separators=(",", ":"))
    return hashlib.sha256(corpo.encode("utf-8")).hexdigest()


def ref_da_accao(content_item_id: str, hash_: str, tentativa: int = 1, *, reforcada: bool = False) -> str:
    """`{id}/{hash}`, `/reforcada` na confirmacao a mais, e `/{n}` a partir da segunda accao."""
    base = f"{content_item_id.lower()}/{hash_}"
    if reforcada:
        base = f"{base}/{SUFIXO_REFORCADO}"
    return base if tentativa == 1 else f"{base}/{tentativa}"


def ler_ref(ref: str) -> RefLida | None:
    casado = _REF.fullmatch(ref)
    return RefLida(casado.group(1), casado.group(2), casado.group(3) is not None) if casado else None
