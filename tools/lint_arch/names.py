"""Normalizacao de nomes de pacotes e de imagens.

Existe porque cada ecossistema tem a sua nocao de "o mesmo nome", e comparar
cadeias literais deixa passar o bypass mais trivial que ha: um `_` em vez de `-`.

    pip install langgraph_api   ==   pip install langgraph-api   (PEP 503)
    ghcr.io/berriai/litellm     e    litellm                     (mesma imagem)
    "storage": "npm:minio@8"    instala    minio                 (alias npm)

Um linter que nao soubesse isto satisfaria as *fixtures* e nao o requisito.
"""

from __future__ import annotations

import re

_PEP503 = re.compile(r"[-_.]+")

#: `registo[:porta]/caminho[:tag][@digest]`
_IMAGE_REF = re.compile(
    r"^(?:(?P<registry>[a-z0-9][a-z0-9.-]*(?::[0-9]+)?)/)?"
    r"(?P<repo>[a-z0-9][a-z0-9._/-]*?)"
    r"(?::(?P<tag>[\w][\w.-]*))?"
    r"(?:@(?P<digest>sha256:[0-9a-f]{64}))?$"
)

#: `npm:pacote@versao` ou `npm:@ambito/pacote@versao`
_NPM_ALIAS = re.compile(r"^npm:(?P<name>(?:@[^/@\s]+/)?[^@\s]+)(?:@(?P<version>.+))?$")

#: `git+...#egg=nome`, usado por `-e` em ficheiros de requirements
_EGG = re.compile(r"[#&]egg=(?P<name>[A-Za-z0-9][A-Za-z0-9._-]*)")

#: Nome do pacote dentro do nome de ficheiro de uma wheel ou sdist
_DIST_FILE = re.compile(
    r"/(?P<name>[A-Za-z0-9][A-Za-z0-9._-]*?)-[0-9][^/]*\.(?:whl|tar\.gz|zip)$"
)


def canonical_pypi(name: str) -> str:
    """PEP 503: `-`, `_` e `.` sao equivalentes e o nome compara-se em minusculas."""
    return _PEP503.sub("-", name.strip()).lower()


def image_parts(reference: str) -> tuple[str, str | None]:
    """Separa `pgvector/pgvector:0.8.7-pg18` em ("pgvector/pgvector", "0.8.7-pg18")."""
    match = _IMAGE_REF.match(reference.strip().lower())
    if not match:
        return reference.strip().lower(), None
    return match.group("repo"), match.group("tag")


def image_candidates(reference: str) -> list[str]:
    """Todos os nomes pelos quais uma imagem pode ser reconhecida.

    `ghcr.io/berriai/litellm:main-v1.82.7` da
    `["ghcr.io/berriai/litellm:main-v1.82.7", "berriai/litellm", "litellm"]`.

    Os sufixos do caminho sao essenciais: sem eles, **escrever o registo faz o
    bloqueio desaparecer**, e a referencia oficial do LiteLLM — o pacote que
    originou o ADR-005 — e precisamente `ghcr.io/berriai/litellm`.
    """
    raw = reference.strip().lower()
    repository, _ = image_parts(raw)
    candidates = [raw, repository]
    segments = repository.split("/")
    for index in range(1, len(segments)):
        candidates.append("/".join(segments[index:]))
    # Sem a tag, para que `litellm:1.82.7` bata numa entrada `exact` de `litellm`.
    if ":" in raw:
        candidates.append(raw.split(":", 1)[0])
    return list(dict.fromkeys(c for c in candidates if c))


def npm_alias_target(spec: str) -> tuple[str, str] | None:
    """Se `spec` e um alias `npm:`, devolve (nome_real, versao).

    `"storage": "npm:minio@8.0.0"` instala o MinIO e importa-se como `storage`.
    O nome declarado nao diz nada; o pacote esta no especificador.
    """
    match = _NPM_ALIAS.match((spec or "").strip())
    if not match:
        return None
    return match.group("name"), (match.group("version") or "")


def requirement_from_url(line: str) -> str | None:
    """Nome do pacote numa linha de requirements que e um URL ou um `-e git+…`.

    `-e git+https://…/langgraph-api@main#egg=langgraph-api` instala o pacote
    proibido sem o nomear como requisito.
    """
    text = (line or "").strip()
    egg = _EGG.search(text)
    if egg:
        return egg.group("name")
    dist = _DIST_FILE.search(text.split("#", 1)[0].split("?", 1)[0])
    if dist:
        return dist.group("name")
    return None


#: Versao numerica dentro de uma tag de imagem: `1.104.2`, `v1.104.2`,
#: `main-v1.104.2`, `1.104.2-stable`. Ancorada em fronteira para nao apanhar
#: numeros a esmo.
_TAG_VERSION = re.compile(r"(?:^|[^0-9a-z])v?(?P<version>[0-9]+(?:\.[0-9]+){1,3})(?:$|[^0-9])")


def version_in_tag(tag: str | None) -> str | None:
    """Versao numerica declarada numa tag de imagem, se houver uma so.

    `main-v1.104.2` da `1.104.2`. Se a tag tiver mais do que uma versao possivel,
    devolve None: na duvida nao se adivinha, e quem chama trata isso como "nao
    provado" (fail-closed).
    """
    if not tag:
        return None
    encontradas = {m.group("version") for m in _TAG_VERSION.finditer(tag.lower())}
    if len(encontradas) != 1:
        return None
    return encontradas.pop()


def image_digest(reference: str) -> str | None:
    """O digest `sha256:...` da referencia, se estiver fixado."""
    match = _IMAGE_REF.match(reference.strip().lower())
    return match.group("digest") if match else None
