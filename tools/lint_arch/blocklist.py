"""Carregamento e aplicacao de `tools/blocklist.yaml`."""

from __future__ import annotations

import dataclasses
import re
from pathlib import Path

from kamba_yaml import YamlSubsetError, load

from . import versions
from .names import canonical_pypi, image_parts

KINDS = ("npm", "pypi", "image", "any")
MATCHES = ("exact", "prefix", "boundary", "substring")
_REQUIRED = ("name", "kind", "match", "adr", "evidence", "reason")

#: Caracteres que contam como fronteira num nome de pacote ou de imagem.
_BOUNDARY = r"[^a-z0-9]"

__all__ = ["Entry", "load_entries", "image_parts"]


@dataclasses.dataclass(frozen=True)
class Entry:
    name: str
    kind: str
    match: str
    adr: str
    evidence: str
    reason: str
    forbidden_below: str | None = None

    def applies_to_kind(self, kind: str) -> bool:
        return self.kind in ("any", kind)

    def matches_name(self, candidate: str, kind: str = "any") -> bool:
        """O candidato cai nesta entrada?

        Para `pypi` normaliza os dois lados por PEP 503, porque `langgraph_api` e
        `langgraph-api` instalam o mesmo pacote.
        """
        candidate = candidate.strip().lower()
        name = self.name
        if kind == "pypi":
            candidate = canonical_pypi(candidate)
            name = canonical_pypi(name)

        if self.match == "exact":
            return candidate == name
        if self.match == "prefix":
            return candidate.startswith(name)
        if self.match == "boundary":
            # O nome aparece delimitado por algo que nao e letra nem digito.
            # Apanha `n8n`, `n8nio/n8n`, `n8n-nodes-base`, `langgenius/dify-api`;
            # **nao** apanha `modify-values`, `codify`, `minion`, `dominion` —
            # pacotes reais que um `substring` bloquearia sem razao, e que
            # deixariam `make check` vermelho no dia em que entrassem na arvore
            # como dependencia transitiva de outra coisa.
            pattern = rf"(?:^|{_BOUNDARY}){re.escape(name)}(?:{_BOUNDARY}|$)"
            return re.search(pattern, candidate) is not None
        return name in candidate


def load_entries(path: Path) -> list[Entry]:
    """Le o ficheiro de bloqueio e valida-o campo a campo.

    Um ficheiro de bloqueio malformado nao pode degradar em silencio para uma
    lista vazia: isso transformaria o controlo em decoracao.
    """
    try:
        data = load(path.read_text(encoding="utf-8"))
    except YamlSubsetError as exc:
        raise ValueError(f"{path}: {exc}") from exc

    if data.get("version") != 1:
        raise ValueError(f"{path}: 'version' tem de ser 1 (lido: {data.get('version')!r})")
    raw_entries = data.get("entries")
    if not isinstance(raw_entries, list) or not raw_entries:
        raise ValueError(f"{path}: 'entries' tem de ser uma lista nao vazia")

    entries: list[Entry] = []
    seen: set[tuple[str, str, str]] = set()
    for index, raw in enumerate(raw_entries, start=1):
        where = f"{path}: entrada {index}"
        missing = [field for field in _REQUIRED if not raw.get(field)]
        if missing:
            raise ValueError(f"{where}: campos obrigatorios em falta: {', '.join(missing)}")
        kind, match = str(raw["kind"]), str(raw["match"])
        if kind not in KINDS:
            raise ValueError(f"{where}: 'kind' invalido {kind!r} (aceita {KINDS})")
        if match not in MATCHES:
            raise ValueError(f"{where}: 'match' invalido {match!r} (aceita {MATCHES})")
        name = str(raw["name"]).strip().lower()
        if name != str(raw["name"]).strip():
            raise ValueError(f"{where}: 'name' tem de estar em minusculas")
        floor = raw.get("forbidden_below")
        floor = str(floor) if floor is not None else None
        if floor is not None and versions.parse(floor) is None:
            raise ValueError(f"{where}: 'forbidden_below' tem de ser numerico (lido {floor!r})")
        key = (name, kind, match)
        if key in seen:
            raise ValueError(f"{where}: entrada duplicada para {name!r}/{kind!r}/{match!r}")
        seen.add(key)
        entries.append(
            Entry(
                name=name,
                kind=kind,
                match=match,
                adr=str(raw["adr"]),
                evidence=str(raw["evidence"]),
                reason=str(raw["reason"]),
                forbidden_below=floor,
            )
        )
    return entries
