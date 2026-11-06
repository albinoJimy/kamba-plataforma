"""A recolha: ligações de CI, métrica de reaproveitamento e decisões externas (KAM-108).

Os «Detalhes Técnicos» do bloco encomendam «o *script* que reúne as ligações de CI
e métricas». São três recolhas, e cada uma tem uma regra que a torna mais do que
um `cat` de ficheiros.

## `ci` — e a regra é que um gate sem *job* não é um gate verde

O critério G0-4 pede «gates 1–13 de `01_Engineering_Standards_e_Handoff.md` §4
verdes no ramo principal (**os que existem na Fase 0**)». O parêntesis é o que
obriga a distinguir três coisas que uma lista de *jobs* verdes não distingue:

    verde          o job correu e passou
    vermelho       o job correu e falhou
    sem job        o gate do §4 não tem job nenhum neste `ci.yaml`

A terceira é a que se perde se alguém ler o painel: um painel todo verde com
três gates do §4 sem *job* parece cobertura que não existe. Esta recolha conta as
três.

## `reuso` — e a regra é a proveniência

O artefacto JSON do `reuse_metric` leva o *commit* e se a árvore estava suja. Um
número medido numa árvore suja não é o número do ramo, e um número medido noutra
ponta não é o número de hoje: as duas coisas fazem esta recolha **recusar** o
artefacto em vez de imprimir a percentagem. É a diferença entre reunir evidência
e reunir números.

## `decisoes` — e a regra é «nenhum estado sem evidência»

Lê o `decisoes.yaml` e verifica três invariantes que uma tabela escrita à mão não
garante: que cada ponteiro existe na árvore, que nenhuma linha diz `confirmada`
com a evidência vazia, e que nenhuma linha fica sem credor. É a regra desta casa
— «nenhuma caixa marcada sem evidência nomeada» — posta numa verificação em vez
de numa recomendação.

## O que esta recolha não faz

Não decide o veredicto do gate, não marca caixas e não vai à rede. A entrada do
`ci` é a saída de `gh run view <id> --json jobs,…`, guardada em ficheiro: assim a
recolha corre offline, é reproduzível, e a evidência fica com a execução que a
produziu em vez de com o estado do painel no instante em que alguém olhou.
"""

from __future__ import annotations

import dataclasses
import json
from pathlib import Path
from typing import Any, Mapping, Sequence

import kamba_yaml

#: Os gates do §4 que a Fase 0 alcança: 1 a 13, com os três sufixos que o §4
#: também numera. O 14 ao 18 são de publicação, *deploy* e *release*, e o G0-4
#: não os pede.
GATES_DO_PARAGRAFO_4: Sequence[str] = (
    "1", "2", "3", "3b", "3c", "4", "5", "6", "7", "8", "9", "10", "11", "12", "13",
)

#: O que cada número do §4 valida, para a saída não ser só números.
NOMES: Mapping[str, str] = {
    "1": "build",
    "2": "lint, format e tipos",
    "3": "lint de referências cruzadas",
    "3b": "lint de nomes canónicos",
    "3c": "lint de coerência do backlog",
    "4": "unit e cobertura",
    "5": "integração",
    "6": "isolamento de tenant e contacto",
    "7": "contratos",
    "8": "migrações",
    "9": "segredos",
    "10": "SAST",
    "11": "SCA e licenças",
    "12": "política de categorias",
    "13": "eval golden PT-AO",
}


class RecolhaInvalida(ValueError):
    """A entrada não é o que esta recolha precisa, e diz o que falta."""


@dataclasses.dataclass(frozen=True)
class EstadoDeGate:
    """O estado de um gate do §4 nesta execução de CI."""

    gate: str
    nome: str
    job: str | None
    conclusao: str | None
    bloqueia: bool

    @property
    def estado(self) -> str:
        if self.job is None:
            return "sem job"
        if self.conclusao == "success":
            return "verde"
        return f"vermelho ({self.conclusao})"


def _gate_do_job(nome_do_job: str) -> str | None:
    """O número do gate que este *job* corre, lido do nome.

    Lê-se do **nome** e não de uma tabela de nomes de *job*, porque o `ci.yaml`
    desta casa nomeia cada um `gate <n> — <assunto>` e é essa a convenção que o
    `docs/ci.md` documenta. Uma tabela à parte divergia no dia em que alguém
    renomeasse um *job*; o nome é a fonte.
    """
    limpo = nome_do_job.strip().lower()
    if not limpo.startswith("gate "):
        return None
    resto = limpo[len("gate ") :].lstrip()
    numero = ""
    for caractere in resto:
        if caractere.isdigit() or (caractere in {"b", "c"} and numero):
            numero += caractere
            continue
        break
    return numero or None


def ler_corrida(caminho: Path) -> tuple[list[EstadoDeGate], Mapping[str, Any]]:
    """Lê a saída de `gh run view <id> --json jobs,headSha,url,conclusion`.

    Um ficheiro sem `jobs` falha: a alternativa — devolver quinze linhas «sem
    job» — era dizer que o `ci.yaml` não tem gates quando o que não há é entrada.
    """
    documento = json.loads(caminho.read_text(encoding="utf-8"))
    if not isinstance(documento, dict) or "jobs" not in documento:
        raise RecolhaInvalida(
            f"{caminho.name}: falta a chave `jobs`. A entrada é a saída de "
            "`gh run view <id> --json jobs,headSha,url,conclusion`"
        )
    por_gate: dict[str, tuple[str, str | None]] = {}
    for job in documento["jobs"]:
        nome = str(job.get("name", ""))
        gate = _gate_do_job(nome)
        if gate is None:
            continue
        por_gate[gate] = (nome, job.get("conclusion"))
    estados: list[EstadoDeGate] = []
    for gate in GATES_DO_PARAGRAFO_4:
        job, conclusao = por_gate.get(gate, (None, None))
        estados.append(
            EstadoDeGate(
                gate=gate,
                nome=NOMES.get(gate, "—"),
                job=job,
                conclusao=conclusao,
                # Um *job* com `continue-on-error` não bloqueia o PR. O nome
                # di-lo nesta casa («não bloqueia»), e é a convenção que o
                # `ci.yaml` usa nos gates reservados e na vigia nocturna.
                bloqueia=bool(job) and "nao bloqueia" not in (job or "").lower()
                and "não bloqueia" not in (job or "").lower(),
            )
        )
    meta = {
        "headSha": documento.get("headSha"),
        "url": documento.get("url"),
        "conclusion": documento.get("conclusion"),
    }
    return estados, meta


def ler_reuso(caminho: Path, ponta: str | None = None) -> Mapping[str, Any]:
    """Lê o artefacto JSON do `reuse_metric`, e recusa-o se não for do ramo.

    Produz-se com `python -m reuse_metric --json <caminho> medir`. As duas
    recusas são de proveniência e não de valor: uma árvore suja e uma ponta
    diferente da que se declara medem outra coisa — e o número, lido sem elas,
    parece igualmente verdadeiro.
    """
    documento = json.loads(caminho.read_text(encoding="utf-8"))
    if not isinstance(documento, dict):
        raise RecolhaInvalida(f"{caminho.name}: não é um objecto JSON")
    proveniencia = documento.get("proveniencia") or {}
    if proveniencia.get("arvore_suja"):
        raise RecolhaInvalida(
            f"{caminho.name}: o artefacto foi medido numa árvore suja. O número "
            "não é o do ramo; volte a medir numa árvore limpa"
        )
    if "reuso_pct" not in documento:
        raise RecolhaInvalida(
            f"{caminho.name}: falta a chave `reuso_pct`. A entrada é a saída de "
            "`python -m reuse_metric --json <caminho> medir`"
        )
    commit = proveniencia.get("commit")
    if ponta and commit and not str(commit).startswith(ponta):
        raise RecolhaInvalida(
            f"{caminho.name}: o artefacto é de `{commit}` e esperava-se `{ponta}`"
        )
    return documento


@dataclasses.dataclass(frozen=True)
class LinhaDeDecisao:
    """Uma linha do critério G0-7, como o `decisoes.yaml` a declara."""

    id: str
    assunto: str
    tickets: tuple[str, ...]
    onde: str
    seccao: str
    estado: str
    plano_ou_pivo: str
    evidencia: str
    credor: str


#: Os três estados que o critério G0-7 admite. Lista fechada: um quarto estado
#: aqui era inventar um resultado que o critério não prevê, e esta casa já pagou
#: essa leitura em dois tickets (o `por enviar` do KAM-101 e o `por submeter` do
#: KAM-105), que a declararam como divergência em vez de a decidirem.
ESTADOS = ("confirmada", "inconclusiva", "refutada")

_CHAVES = {"version", "lida_em", "ponta", "linhas"}
_CHAVES_DE_LINHA = {
    "id", "assunto", "tickets", "onde", "seccao", "estado", "plano_ou_pivo",
    "evidencia", "credor",
}


def ler_decisoes(raiz: Path, manifesto: Path | None = None) -> tuple[list[LinhaDeDecisao], list[str]]:
    """Lê o manifesto e devolve as linhas mais os achados das três invariantes.

    Devolve os achados em vez de levantar: o chamador imprime-os e sai com
    código 1, e uma lista de achados diz **todos** os problemas e não o primeiro
    — que é a forma que o `exigir_handlers` do AGR e o `lint_backlog` já usam, e
    pela mesma razão: sete linhas erradas não são sete execuções.
    """
    caminho = manifesto or (Path(__file__).resolve().parent / "decisoes.yaml")
    documento = kamba_yaml.load_file(caminho)
    kamba_yaml.exigir_chaves(documento, _CHAVES, str(caminho), erro=RecolhaInvalida)
    # **O `exigir_chaves` recusa chaves a mais e não exige chaves presentes** —
    # medido ao escrever o ensaio, que esperava o contrário. Sem esta guarda, um
    # manifesto a que falte o `linhas` dá zero linhas em silêncio, e zero linhas
    # lê-se como «o G0-7 não tem decisões». `RecolhaInvalida` e não achado: é
    # configuração, logo código 2 (ver o `cli.py`).
    if not documento.get("linhas"):
        raise RecolhaInvalida(
            f"{caminho}: sem a chave `linhas` com pelo menos uma entrada. O "
            "critério G0-7 nomeia sete, e um manifesto vazio não é «zero "
            "decisões»: é um manifesto que não se consegue ler"
        )
    achados: list[str] = []
    linhas: list[LinhaDeDecisao] = []
    for indice, bruta in enumerate(documento["linhas"], start=1):
        kamba_yaml.exigir_chaves(
            bruta, _CHAVES_DE_LINHA, f"{caminho}: linha {indice}", erro=RecolhaInvalida
        )
        linha = LinhaDeDecisao(
            id=str(bruta["id"]),
            assunto=str(bruta["assunto"]),
            tickets=tuple(str(t) for t in bruta["tickets"]),
            onde=str(bruta["onde"]),
            seccao=str(bruta["seccao"]),
            estado=str(bruta["estado"]),
            plano_ou_pivo=str(bruta["plano_ou_pivo"]),
            evidencia=str(bruta["evidencia"]),
            credor=str(bruta["credor"]),
        )
        linhas.append(linha)
        if linha.estado not in ESTADOS:
            achados.append(
                f"{linha.id}: o estado `{linha.estado}` não é um dos três que o "
                f"critério G0-7 admite {ESTADOS}"
            )
        if not (raiz / linha.onde).is_file():
            achados.append(
                f"{linha.id}: o ponteiro `{linha.onde}` não existe na árvore"
            )
        if not linha.evidencia.strip():
            achados.append(f"{linha.id}: estado declarado e evidência vazia")
        if not linha.credor.strip():
            achados.append(f"{linha.id}: linha sem credor nomeado")
        if linha.estado != "confirmada" and not linha.plano_ou_pivo.strip():
            achados.append(
                f"{linha.id}: `{linha.estado}` sem plano nem pivô — o critério "
                "G0-7 exige «`inconclusiva` com plano» ou «`refutada` com pivô»"
            )
    return linhas, achados


def tabela_de_ci(estados: Sequence[EstadoDeGate], meta: Mapping[str, Any]) -> str:
    """A tabela do G0-4, com a execução que a produziu nomeada em cima."""
    cabeca = (
        f"Execução {meta.get('url') or '(sem url)'} em "
        f"`{(meta.get('headSha') or '?')[:7]}` — conclusão "
        f"`{meta.get('conclusion')}`"
    )
    linhas = [
        cabeca,
        "",
        "| Gate | O que valida | Job | Estado | Bloqueia |",
        "|---|---|---|---|---|",
    ]
    for estado in estados:
        linhas.append(
            f"| {estado.gate} | {estado.nome} | {estado.job or '—'} "
            f"| **{estado.estado}** | {'sim' if estado.bloqueia else 'não'} |"
        )
    verdes = sum(1 for e in estados if e.estado == "verde")
    sem_job = sum(1 for e in estados if e.job is None)
    vermelhos = len(estados) - verdes - sem_job
    linhas.append("")
    linhas.append(
        f"{verdes} verde(s), {vermelhos} vermelho(s) e {sem_job} sem job, "
        f"em {len(estados)} gates do §4."
    )
    return "\n".join(linhas)


#: O limiar do ADR-012, lido de `ci/regra-de-dois.yaml` e não escrito aqui: dois
#: sítios a declarar 70 divergiam no dia em que o ADR mudasse.
def limiar_do_reuso(raiz: Path) -> float:
    documento = kamba_yaml.load_file(raiz / "ci" / "regra-de-dois.yaml")
    limiar = (documento.get("caminho") or {}).get("limiar")
    if limiar is None:
        raise RecolhaInvalida(
            "`ci/regra-de-dois.yaml` não declara `caminho.limiar`; sem ele a "
            "recolha não sabe contra o que comparar"
        )
    return float(limiar)


def tabela_de_reuso(documento: Mapping[str, Any], limiar: float) -> str:
    """As duas metades do G0-2 numa tabela, com a ponta onde foram medidas."""
    proveniencia = documento.get("proveniencia") or {}
    pct = float(documento["reuso_pct"])
    return "\n".join(
        [
            "| Grandeza | Valor | Limiar | Medido em |",
            "|---|---|---|---|",
            f"| Reaproveitamento da vertical `{documento.get('vertical')}` "
            f"| **{pct:.2f}%** | >= {limiar:.2f}% "
            f"| `{str(proveniencia.get('commit') or '?')[:7]}` |",
            f"| LoC específico | {documento.get('loc_especifico')} | — | idem |",
            f"| LoC partilhado | {documento.get('loc_partilhado')} | — | idem |",
            f"| LoC total | {documento.get('loc_total')} | — | idem |",
            "",
            f"Passa o limiar: {'sim' if pct >= limiar else 'NÃO'}.",
        ]
    )


def tabela_de_decisoes(linhas: Sequence[LinhaDeDecisao], prefixo: str = "") -> str:
    """A tabela do G0-7, gerada do manifesto.

    `prefixo` é o que se põe antes de cada caminho para a ligação resolver de
    onde a tabela vai ser colada. Para um documento em
    `docs/tecnica/evidencia/validacao/` são **quatro** níveis — `../../../../` —,
    e não três: o *docstring* dizia três, o que resolveria para `docs/docs/…` e
    dava uma ligação quebrada. Achado da revisão adversarial, e o ensaio que o
    fixava estava a consagrar o valor errado.

    Existe para que a tabela do documento seja **esta** tabela e não uma cópia
    com os caminhos corrigidos à mão: duas cópias divergem, e a que alguém lê é a
    que não tem ensaio.
    """
    saida = [
        "| # | Assunto | Tickets | Estado | Plano ou pivô | Evidência | Credor |",
        "|---|---|---|---|---|---|---|",
    ]
    for linha in linhas:
        onde = f"[`{Path(linha.onde).name}`]({prefixo}{linha.onde}) {linha.seccao}"
        saida.append(
            f"| {linha.id} | {linha.assunto} | {', '.join(linha.tickets)} "
            f"| **{linha.estado}** | {linha.plano_ou_pivo.strip()} "
            f"| {linha.evidencia.strip()} — {onde} | {linha.credor} |"
        )
    return "\n".join(saida)
