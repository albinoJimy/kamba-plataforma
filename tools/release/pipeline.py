"""Gate 18 — o *lint* do *pipeline*: nenhum gate se salta sem registo.

O criterio: «`skip` ou `allow_failure` num gate exige referencia a ADR/aprovacao
(*lint* do *pipeline*)». A regra transversal do §4: «nenhum gate pode ser
marcado *skip* sem ADR ou aprovacao registada».

## O que e «saltar um gate» num *workflow* do GitHub

Tudo o que torna o gate incapaz de bloquear, no *job* ou num passo:

* `continue-on-error` com qualquer valor que nao seja `false` (uma expressao
  conta: pode valer `true`). E a forma do GitHub do `allow_failure` do GitLab,
  que tambem se procura;
* um `if:` que nao seja um dos que **correm sempre** — `always()`,
  `!cancelled()`, `success()`. Uma condicao nao se avalia aqui: `if: 'false'`,
  `${{ false && true }}` ou `github.event_name == 'nunca'` desligam o gate tao
  bem como `if: false`, e por isso qualquer outra conta como salto;
* uma forma que este leitor nao le — um *job* em fluxo (`{...}`), um `name:` em
  bloco, uma destas chaves dentro de um mapa em fluxo. **Ilegivel conta como
  achado**: um *lint* que passa no que nao leu e o defeito que existe para
  apanhar.

**So nos *jobs* que sao gates**: os que tem `gate <id>` no `name:`, ou uma chave
`gate-<id>`, que e a convencao do `ci.yaml` desde o KAM-002. A vigia da prova
nocturna nao e gate, e o seu `continue-on-error` nao e um gate saltado.

## O que conta como registo

Um destes, e so estes:

* `ADR-NNN` que exista em `docs/tecnica/00_Arquitectura_Solucao.md`, ou
  `ADR-LNNN` com ficheiro em `docs/adr/`, num **comentario de linha inteira** por
  cima do *job* ou dentro dele — um `#` dentro de um `run:` nao e comentario;
* um *waiver* valido em `ci/waivers.yaml` com `gate` igual ao do *job* e `alvo`
  igual a chave do *job*. O `ci_waivers` ja lhe exige prazo de 30 dias, autor,
  razao e aprovacao contemporanea, e recusa-o para os gates que nao admitem
  dispensa (15, 16, 17, ...).

**Uma `aprovacao:<quem>@<data>` solta num comentario nao conta.** A primeira
versao aceitava-a, e a revisao adversarial mostrou porque nao pode: sem prazo,
sem autor validado e para qualquer gate, e estritamente mais fraca do que o
*waiver* que a regra transversal ja tem. Uma aprovacao regista-se no
`ci/waivers.yaml`. Uma mencao a esse ficheiro em prosa tambem nao conta.

## Leitor, e o que nao ve

Por linhas, e nao por YAML: os tres leitores de YAML do repositorio sao
subconjuntos, e os *workflows* usam formas que nenhum le. A indentacao dos *jobs*
le-se da primeira chave debaixo de `jobs:`. **Nao ve** o que vive fora dos
*workflows*: um `continue-on-error` dentro de uma accao composta
(`.github/actions/*/action.yml`) ou de um *workflow* reutilizavel chamado por
`uses:`.
"""

from __future__ import annotations

import dataclasses
import datetime as _datetime
import re
from pathlib import Path

_JOBS = re.compile(r"""^["']?jobs["']?\s*:\s*(?P<resto>[^#]*?)\s*(?:#.*)?$""")
_CHAVE = re.compile(r"""^\s*["']?(?P<chave>[^"':#\s{}\[\]]+)["']?\s*:(?:\s+(?P<resto>.*))?$""")
_NOME = re.compile(r"""^\s*["']?name["']?\s*:\s*(?P<valor>.*?)\s*$""")
_GATE_NO_NOME = re.compile(r"\bgate\s+(?P<id>\d+[a-z]?)\b", re.IGNORECASE)
_GATE_NA_CHAVE = re.compile(r"^gate-(?P<id>\d+[a-z]?)(?:-|$)", re.IGNORECASE)
_SALTO = re.compile(
    r"""^\s*(?:-\s+)?["']?(?P<chave>continue-on-error|allow_failure|if)["']?\s*:\s*(?P<valor>.*?)\s*$"""
)
_EM_FLUXO = re.compile(r"""(continue-on-error|allow_failure|\bif)\s*["']?\s*:""")
_IFS_QUE_CORREM_SEMPRE = {"always()", "!cancelled()", "success()"}
_ADR = re.compile(r"(?<![\w-])ADR-(?P<n>\d{3})(?![\w-])")
_ADR_L = re.compile(r"(?<![\w-])ADR-L(?P<n>\d{3})(?![\w-])")


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
            f"`{self.forma}` sem ADR nem waiver registado"
        )


def _sem_comentario(texto: str) -> str:
    """Corta um ` #` final fora de aspas. Aproximado, e chega para escalares."""
    aspa = None
    for i, c in enumerate(texto):
        if c in "\"'" and aspa is None:
            aspa = c
        elif c == aspa:
            aspa = None
        elif c == "#" and aspa is None and (i == 0 or texto[i - 1].isspace()):
            return texto[:i].rstrip()
    return texto.strip()


def _indentacao(linha: str) -> int:
    return len(linha) - len(linha.lstrip())


def _e_comentario(linha: str) -> bool:
    return linha.lstrip().startswith("#")


@dataclasses.dataclass
class _Job:
    chave: str
    linha: int
    resto: str
    comentarios: list[str]
    corpo: list[tuple[int, str]]

    def nome(self) -> str | None:
        """O `name:` do *job*; `None` se nao se le como escalar de uma linha."""
        if not self.corpo:
            return ""
        nivel = min(_indentacao(l) for _, l in self.corpo)
        for _, linha in self.corpo:
            if _indentacao(linha) != nivel:
                continue
            casou = _NOME.match(linha)
            if casou:
                valor = _sem_comentario(casou["valor"])
                if not valor or valor[0] in ">|&*{[":
                    return None
                return valor.strip("\"'")
        return ""


def _jobs(texto: str) -> tuple[list[_Job], list[int]]:
    """Os *jobs*, e as linhas de um `jobs:` que nao se le."""
    linhas = texto.splitlines()
    inicio = None
    for i, linha in enumerate(linhas):
        casou = _JOBS.match(linha)
        if casou:
            if casou["resto"]:
                return [], [i + 1]
            inicio = i
            break
    if inicio is None:
        return [], []
    nivel = None
    jobs: list[_Job] = []
    pendentes: list[str] = []
    actual: _Job | None = None
    for indice in range(inicio + 1, len(linhas)):
        linha = linhas[indice]
        if not linha.strip():
            continue
        if _e_comentario(linha):
            if nivel is not None and _indentacao(linha) > nivel and actual is not None:
                actual.comentarios.append(linha)
            else:
                pendentes.append(linha)
            continue
        recuo = _indentacao(linha)
        if recuo == 0:
            break
        if nivel is None:
            nivel = recuo
        if recuo < nivel:
            break
        if recuo == nivel:
            casou = _CHAVE.match(linha)
            chave = casou["chave"] if casou else linha.strip()
            resto = _sem_comentario(casou["resto"] or "") if casou else linha.strip()
            actual = _Job(chave, indice + 1, resto, pendentes, [])
            jobs.append(actual)
            pendentes = []
            continue
        if actual is not None:
            # Um comentario na coluna dos *jobs* seguido de mais corpo e do *job*
            # de cima, e nao preambulo do seguinte (achado da revisao).
            actual.comentarios.extend(pendentes)
            pendentes = []
            actual.corpo.append((indice + 1, linha))
    return jobs, []


def _gate(job: _Job) -> str | None:
    nome = job.nome()
    if nome:
        casou = _GATE_NO_NOME.search(nome)
        if casou:
            return casou["id"].lower()
    casou = _GATE_NA_CHAVE.match(job.chave)
    return casou["id"].lower() if casou else None


def _saltos(job: _Job) -> list[tuple[int, str]]:
    saltos: list[tuple[int, str]] = []
    for numero, linha in job.corpo:
        casou = _SALTO.match(linha)
        if casou:
            valor = _sem_comentario(casou["valor"]).strip("\"'").strip()
            if valor.startswith("${{") and valor.endswith("}}"):
                valor = valor[3:-2].strip()
            normal = valor.replace(" ", "").lower()
            if casou["chave"] == "if":
                if normal not in _IFS_QUE_CORREM_SEMPRE:
                    saltos.append((numero, f"if: {valor}"))
            elif normal != "false":
                saltos.append((numero, f"{casou['chave']}: {valor}"))
            continue
        codigo = _sem_comentario(linha)
        if "{" in codigo and _EM_FLUXO.search(codigo):
            saltos.append((numero, f"ilegivel: {codigo.strip()}"))
    return saltos


def _registo_valido(job: _Job, raiz: Path) -> bool:
    texto = "\n".join(job.comentarios)
    canon = raiz / "docs" / "tecnica" / "00_Arquitectura_Solucao.md"
    adrs = canon.read_text(encoding="utf-8") if canon.is_file() else ""
    for casou in _ADR.finditer(texto):
        if re.search(rf"(?<![\w-])ADR-{casou['n']}(?![\w-])", adrs):
            return True
    for casou in _ADR_L.finditer(texto):
        if any((raiz / "docs" / "adr").glob(f"ADR-L{casou['n']}-*.md")):
            return True
    return False


def verificar_texto(
    texto: str,
    ficheiro: str,
    raiz: Path,
    waivers: set[tuple[str, str]],
) -> list[Achado]:
    """`waivers` e o conjunto de `(gate, alvo)` validos do `ci/waivers.yaml`."""
    jobs, ilegiveis = _jobs(texto)
    achados = [Achado(ficheiro, n, "jobs", "?", "jobs: em fluxo, ilegivel") for n in ilegiveis]
    for job in jobs:
        if job.resto:
            achados.append(Achado(ficheiro, job.linha, job.chave, "?", f"job em fluxo, ilegivel: {job.resto}"))
            continue
        if job.nome() is None:
            achados.append(Achado(ficheiro, job.linha, job.chave, "?", "name: que nao se le numa linha"))
            continue
        gate = _gate(job)
        if gate is None:
            continue
        saltos = _saltos(job)
        if not saltos:
            continue
        if (gate, job.chave) in waivers or _registo_valido(job, raiz):
            continue
        for numero, forma in saltos:
            achados.append(Achado(ficheiro, numero, job.chave, gate, forma))
    return achados


def verificar(raiz: Path, hoje: _datetime.date | None = None) -> list[Achado]:
    """`hoje` so chega ao `ci_waivers`, que e quem decide se um waiver caducou."""
    from ci_waivers import ler

    waivers = {(str(w["gate"]).lower(), str(w["alvo"])) for w in ler(raiz, hoje)}
    achados: list[Achado] = []
    pasta = raiz / ".github" / "workflows"
    for caminho in sorted(list(pasta.glob("*.yaml")) + list(pasta.glob("*.yml"))):
        relativo = caminho.relative_to(raiz).as_posix()
        achados += verificar_texto(caminho.read_text(encoding="utf-8"), relativo, raiz, waivers)
    return achados
