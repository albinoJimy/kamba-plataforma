"""Gate 18 — o *lint* do *pipeline*: nenhum gate se salta sem registo.

O criterio: «`skip` ou `allow_failure` num gate exige referencia a ADR/aprovacao
(*lint* do *pipeline*)». A regra transversal do §4: «nenhum gate pode ser
marcado *skip* sem ADR ou aprovacao registada».

## O que e «saltar um gate» num *workflow* do GitHub

Duas formas, e as duas tornam o gate incapaz de bloquear:

* `continue-on-error: true` (ou uma expressao) — no *job* ou num passo. E a
  forma do GitHub do `allow_failure` do GitLab, que tambem se procura;
* `if: false` (ou `${{ false }}`) — o *job* nunca corre.

**So nos *jobs* que sao gates**: os que se chamam `gate <id> ...`, que e a
convencao do `ci.yaml` desde o KAM-002. A vigia da prova nocturna nao e gate, e
o seu `continue-on-error` nao e um gate saltado.

## O que conta como registo

Qualquer um destes, nos comentarios por cima do *job* ou dentro dele:

* `ADR-NNN` que exista em `docs/tecnica/00_Arquitectura_Solucao.md`;
* `ADR-LNNN` com ficheiro em `docs/adr/`;
* `aprovacao:<quem>@<AAAA-MM-DD>`, a forma do `ci/waivers.yaml`, com data nao
  futura;
* ou um *waiver* valido em `ci/waivers.yaml` com `gate` igual ao do *job* e
  `alvo` igual a chave do *job* — que ja tem prazo, autor e razao validados.

Uma mencao a `ci/waivers.yaml` em prosa **nao** conta: e uma promessa de
registo, nao um registo.

## Leitor

Por linhas, e nao por YAML. Os tres leitores de YAML do repositorio sao
subconjuntos, e os *workflows* usam formas que nenhum le (`${{ }}`, listas em
fluxo). O que se precisa e pouco e tem forma fixa: a chave `jobs:` na coluna 0,
cada *job* a dois espacos, e o `name:` a quatro.
"""

from __future__ import annotations

import dataclasses
import datetime as _datetime
import re
from pathlib import Path

_JOB = re.compile(r"^  (?P<chave>[A-Za-z0-9_-]+):\s*(?:#.*)?$")
_NOME = re.compile(r"""^    name:\s*["']?(?P<nome>[^"'#]*)""")
_GATE = re.compile(r"^gate\s+(?P<id>\d+[a-z]?)\b", re.IGNORECASE)
_SALTO = re.compile(
    r"^\s*-?\s*(?P<chave>continue-on-error|allow_failure)\s*:\s*(?P<valor>[^#]*?)\s*(?:#.*)?$"
)
_IF_FALSO = re.compile(r"^\s*-?\s*if\s*:\s*(?:false|\$\{\{\s*false\s*\}\})\s*(?:#.*)?$")
_ADR = re.compile(r"\bADR-(?P<n>\d{3})\b")
_ADR_L = re.compile(r"\bADR-L(?P<n>\d{3})\b")
_APROVACAO = re.compile(r"\baprovacao:[^\s@]+@(?P<data>\d{4}-\d{2}-\d{2})\b")


@dataclasses.dataclass(frozen=True)
class Achado:
    ficheiro: str
    linha: int
    job: str
    gate: str
    forma: str

    def __str__(self) -> str:
        return (
            f"{self.ficheiro}:{self.linha}: o gate {self.gate} (job `{self.job}`) tem "
            f"`{self.forma}` sem ADR, aprovacao nem waiver registado"
        )


@dataclasses.dataclass
class _Job:
    chave: str
    linha: int
    comentarios: list[str]
    corpo: list[tuple[int, str]]

    @property
    def nome(self) -> str:
        for _, linha in self.corpo:
            casou = _NOME.match(linha)
            if casou:
                return casou["nome"].strip()
        return ""


def _jobs(texto: str) -> list[_Job]:
    linhas = texto.splitlines()
    try:
        inicio = next(i for i, l in enumerate(linhas) if l.rstrip() == "jobs:")
    except StopIteration:
        return []
    jobs: list[_Job] = []
    pendentes: list[str] = []
    actual: _Job | None = None
    for indice in range(inicio + 1, len(linhas)):
        linha = linhas[indice]
        if linha and not linha.startswith((" ", "#")):
            break
        casou = _JOB.match(linha)
        if casou:
            actual = _Job(casou["chave"], indice + 1, pendentes, [])
            jobs.append(actual)
            pendentes = []
            continue
        if linha.strip().startswith("#") and len(linha) - len(linha.lstrip()) <= 2:
            # Comentario na coluna do *job*: e o preambulo do seguinte.
            pendentes.append(linha)
            continue
        if not linha.strip():
            continue
        if actual is not None:
            actual.corpo.append((indice + 1, linha))
    return jobs


def _referencias_validas(texto: str, raiz: Path, hoje: _datetime.date) -> bool:
    adr_canon = (raiz / "docs" / "tecnica" / "00_Arquitectura_Solucao.md")
    canon = adr_canon.read_text(encoding="utf-8") if adr_canon.is_file() else ""
    for casou in _ADR.finditer(texto):
        if f"ADR-{casou['n']}" in canon:
            return True
    for casou in _ADR_L.finditer(texto):
        if any((raiz / "docs" / "adr").glob(f"ADR-L{casou['n']}-*.md")):
            return True
    for casou in _APROVACAO.finditer(texto):
        try:
            if _datetime.date.fromisoformat(casou["data"]) <= hoje:
                return True
        except ValueError:
            continue
    return False


def verificar_texto(
    texto: str,
    ficheiro: str,
    raiz: Path,
    waivers: set[tuple[str, str]],
    hoje: _datetime.date,
) -> list[Achado]:
    """`waivers` e o conjunto de `(gate, alvo)` validos do `ci/waivers.yaml`."""
    achados: list[Achado] = []
    for job in _jobs(texto):
        gate = _GATE.match(job.nome)
        if not gate:
            continue
        saltos: list[tuple[int, str]] = []
        for numero, linha in job.corpo:
            casou = _SALTO.match(linha)
            if casou and casou["valor"].strip().lower() not in ("false", "'false'", '"false"'):
                saltos.append((numero, f"{casou['chave']}: {casou['valor'].strip()}"))
            elif _IF_FALSO.match(linha):
                saltos.append((numero, linha.strip()))
        if not saltos:
            continue
        registo = "\n".join(job.comentarios + [l for _, l in job.corpo if "#" in l])
        if (gate["id"], job.chave) in waivers or _referencias_validas(registo, raiz, hoje):
            continue
        for numero, forma in saltos:
            achados.append(Achado(ficheiro, numero, job.chave, gate["id"], forma))
    return achados


def waivers_de_jobs(raiz: Path) -> set[tuple[str, str]]:
    from ci_waivers import ler

    return {(str(w["gate"]), str(w["alvo"])) for w in ler(raiz)}


def verificar(raiz: Path, hoje: _datetime.date | None = None) -> list[Achado]:
    hoje = hoje or _datetime.date.today()
    waivers = waivers_de_jobs(raiz)
    achados: list[Achado] = []
    pasta = raiz / ".github" / "workflows"
    for caminho in sorted(list(pasta.glob("*.yaml")) + list(pasta.glob("*.yml"))):
        relativo = caminho.relative_to(raiz).as_posix()
        achados += verificar_texto(caminho.read_text(encoding="utf-8"), relativo, raiz, waivers, hoje)
    return achados
