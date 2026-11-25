"""Gate 16 — aprovacao humana antes de `prod`.

O criterio do bloco: «um PR marcado dinheiro/seguranca/isolamento nao chega a
`prod` com menos de 2 aprovacoes (teste negativo com 1)». O §4 do `specs/01`:
«dois revisores para P0 de dinheiro/seguranca».

## O que conta como «marcado»

**Duas fontes, e basta uma.** A etiqueta do PR (`dinheiro`, `seguranca`,
`isolamento`) e a que o criterio nomeia — mas uma etiqueta e um acto de quem
abre o PR, e esquece-se: medido a 2026-11-25, o `albinoJimy/kamba-plataforma`
**nao tem nenhuma das tres** (`gh label list`). Um gate que dependesse so dela
falhava aberto desde o primeiro dia.

A segunda e **o caminho**: um PR que toque num ficheiro do estrato `critico` do
`ci/thresholds.yaml` (pagamentos, isolamento de tenant, identidade, validador)
e de dinheiro, seguranca ou isolamento por definicao — e a mesma fronteira que
pede 90% de cobertura no gate 4. Le-se de la pelo `coverage_gate`, e nao se
copia: a lista nao pode divergir da que o gate 4 aplica.

## O que conta como «aprovacao»

* o **ultimo** parecer de cada revisor; um `CHANGES_REQUESTED` depois de um
  `APPROVED` anula-o;
* sobre a **cabeca** do PR: uma aprovacao a um *commit* anterior nao aprovou o
  que vai para `prod`;
* de quem **nao e o autor** — o GitHub ja o impede, e aqui repete-se porque
  este modulo tambem le um JSON que nao veio do GitHub;
* de quem **tem escrita no repositorio** (`authorAssociation` `OWNER`, `MEMBER`
  ou `COLLABORATOR`) e **nao e um *bot***. O repositorio e publico: qualquer
  conta do GitHub pode submeter um «Approve», e sem este filtro duas contas
  descartaveis faziam passar um PR de dinheiro (achado da revisao adversarial).
  Sem o campo, a revisao nao conta.

**As etiquetas comparam-se sem acentos nem maiusculas**: `Segurança` e
`seguranca` sao a mesma marca. As tres ainda nao existem, e num repositorio em
portugues e provavel que nascam com acento.

**Uma release leva varios PRs.** `decidir_varios` exige que **cada** PR do
intervalo que vai para `prod` passe: um PR de dinheiro fundido antes do que se
avalia nao fica de fora por nao ser o ultimo.

A forma do JSON e a do `gh pr view --json author,headRefOid,labels,reviews,files`.
Os campos `author.login`, `headRefOid`, `labels[].name` e o `reviews: []` vazio
foram **lidos** de um PR real (o #275); a forma de uma revisao preenchida
(`state`, `author.login`, `commit.oid`) e **INDICIO** — nenhum PR do repositorio
tem revisoes, pela decisao do fundador de fundir sem revisao humana ate haver
producao.
"""

from __future__ import annotations

import dataclasses
import unicodedata
from pathlib import Path

#: As etiquetas que o criterio nomeia, sem acentos (nomes de etiqueta).
ETIQUETAS_SENSIVEIS = frozenset({"dinheiro", "seguranca", "isolamento"})

#: O estrato do `ci/thresholds.yaml` que torna um caminho sensivel.
ESTRATO_SENSIVEL = "critico"

#: Quem pode aprovar: as associacoes com escrita no repositorio. **INDICIO**: e
#: o campo `authorAssociation` da API do GitHub; nenhum PR deste repositorio tem
#: revisoes com que o confirmar.
ASSOCIACOES_QUE_APROVAM = frozenset({"OWNER", "MEMBER", "COLLABORATOR"})

MINIMO_SENSIVEL = 2
MINIMO_RESTANTE = 1


@dataclasses.dataclass(frozen=True)
class Decisao:
    sensivel: bool
    razoes: tuple[str, ...]
    exigidas: int
    aprovadores: tuple[str, ...]

    @property
    def passa(self) -> bool:
        return len(self.aprovadores) >= self.exigidas

    def __str__(self) -> str:
        estado = "PASSA" if self.passa else "RECUSADO"
        motivo = ", ".join(self.razoes) if self.razoes else "nenhuma marca"
        quem = ", ".join(self.aprovadores) if self.aprovadores else "ninguem"
        return (
            f"{estado}: {len(self.aprovadores)} de {self.exigidas} aprovacoes "
            f"({quem}); sensivel={self.sensivel} ({motivo})"
        )


def caminhos_sensiveis(caminhos: list[str], raiz: Path) -> list[str]:
    from coverage_gate import ler_limiares

    limiares = ler_limiares(raiz)
    saida = []
    for caminho in caminhos:
        estrato = limiares.classificar(caminho)
        if estrato is not None and estrato.nome == ESTRATO_SENSIVEL:
            saida.append(caminho)
    return saida


def _sem_acentos(texto: str) -> str:
    decomposto = unicodedata.normalize("NFKD", texto)
    return "".join(c for c in decomposto if not unicodedata.combining(c)).strip().lower()


def aprovadores(pr: dict) -> tuple[str, ...]:
    """Quem aprovou a cabeca do PR, pelo ultimo parecer de cada um."""
    autor = str((pr.get("author") or {}).get("login") or "")
    cabeca = str(pr.get("headRefOid") or "")
    ultimo: dict[str, dict] = {}
    for revisao in pr.get("reviews") or []:
        quem = str((revisao.get("author") or {}).get("login") or "")
        if not quem or quem == autor or quem.endswith("[bot]"):
            continue
        if (revisao.get("author") or {}).get("is_bot") is True:
            continue
        if revisao.get("authorAssociation") not in ASSOCIACOES_QUE_APROVAM:
            continue
        # COMMENTED nao muda o parecer de ninguem: so APPROVED, CHANGES_REQUESTED
        # e DISMISSED o fazem.
        if revisao.get("state") in ("APPROVED", "CHANGES_REQUESTED", "DISMISSED"):
            ultimo[quem] = revisao
    saida = []
    for quem, revisao in ultimo.items():
        oid = str((revisao.get("commit") or {}).get("oid") or "")
        if revisao.get("state") == "APPROVED" and cabeca and oid == cabeca:
            saida.append(quem)
    return tuple(sorted(saida))


def decidir(pr: dict, sensiveis_por_caminho: list[str]) -> Decisao:
    etiquetas = {_sem_acentos(str(e.get("name", ""))) for e in pr.get("labels") or []}
    razoes = [f"etiqueta {e}" for e in sorted(etiquetas & ETIQUETAS_SENSIVEIS)]
    razoes += [f"caminho {c}" for c in sorted(sensiveis_por_caminho)]
    sensivel = bool(razoes)
    return Decisao(
        sensivel=sensivel,
        razoes=tuple(razoes),
        exigidas=MINIMO_SENSIVEL if sensivel else MINIMO_RESTANTE,
        aprovadores=aprovadores(pr),
    )


def decidir_com_raiz(pr: dict, raiz: Path) -> Decisao:
    """Com os caminhos classificados pelo `ci/thresholds.yaml`.

    **Uma lista truncada conta como sensivel.** A lista `files` do `gh` vem de
    uma consulta paginada; se o `changedFiles` disser mais ficheiros do que a
    lista traz, o que faltou ver pode ser exactamente o de dinheiro. Na duvida,
    exigem-se dois.
    """
    ficheiros = [f for f in pr.get("files") or [] if isinstance(f, dict)]
    caminhos = [str(f.get("path", "")) for f in ficheiros]
    sensiveis = caminhos_sensiveis(caminhos, raiz)
    total = pr.get("changedFiles")
    if not isinstance(total, int) or total > len(ficheiros):
        sensiveis.append(f"<lista de ficheiros incompleta: {len(ficheiros)} de {total}>")
    return decidir(pr, sensiveis)


def decidir_varios(prs: list[dict], raiz: Path) -> list[Decisao]:
    """Uma decisao por PR da release; a release so passa se todas passarem."""
    if not prs:
        raise ValueError("uma release sem PR nenhum nao tem quem a aprove")
    return [decidir_com_raiz(pr, raiz) for pr in prs]
