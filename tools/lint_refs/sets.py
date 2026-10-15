"""Os conjuntos validos de referencias, lidos das fontes canonicas.

Nada aqui e constante escrita a mao. Se os conjuntos fossem fixados no codigo,
o gate 3 passaria a verificar o codigo contra si mesmo e nao contra o canon —
e o dia em que o backlog crescesse, o gate ficaria a mentir em vez de falhar.
"""

from __future__ import annotations

import dataclasses
import re
from pathlib import Path

#: Linha do backlog mestre: `| KAM-003 | Schema platform… |`
_LINHA_BACKLOG = re.compile(r"^\|\s*(?P<id>KAM-[0-9]{3})\s*\|")

#: Linha da tabela de ADRs do §8, que pode ter o ID em negrito: `| **ADR-013** |`
_LINHA_ADR = re.compile(r"^\|\s*\*{0,2}(?P<id>ADR-[0-9]{3})\*{0,2}\s*\|")

#: Linha da tabela de decisoes abertas do §13.3: `| D12 | CDN/WAF… |`
_LINHA_D = re.compile(r"^\|\s*(?P<id>D[0-9]{1,2})\s*\|")


class FonteCanonicaAusente(RuntimeError):
    """Uma das fontes dos conjuntos validos nao existe ou esta vazia.

    Levanta-se em vez de devolver um conjunto vazio: um conjunto vazio faria o
    gate reprovar **todas** as referencias, o que parece um ataque de pânico, ou
    — pior, se alguem invertesse a logica — aprovar todas.
    """


@dataclasses.dataclass(frozen=True)
class Conjuntos:
    """Os conjuntos validos, com a origem de cada um."""

    kam: frozenset[str]
    adr: frozenset[str]
    d: frozenset[str]
    origens: dict[str, str]

    def resumo(self) -> str:
        return (
            f"KAM: {len(self.kam)} ({_intervalo(self.kam, 'KAM-')}), "
            f"ADR: {len(self.adr)} ({_intervalo(self.adr, 'ADR-')}), "
            f"D: {len(self.d)} ({_intervalo_d(self.d)})"
        )

    def contem(self, serie: str, identificador: str) -> bool:
        return identificador in {"KAM": self.kam, "ADR": self.adr, "D": self.d}[serie]


def _intervalo(conjunto: frozenset[str], prefixo: str) -> str:
    if not conjunto:
        return "vazio"
    numeros = sorted(int(x[len(prefixo) :]) for x in conjunto)
    return f"{prefixo}{numeros[0]:03d}–{prefixo}{numeros[-1]:03d}"


def _intervalo_d(conjunto: frozenset[str]) -> str:
    if not conjunto:
        return "vazio"
    numeros = sorted(int(x[1:]) for x in conjunto)
    return f"D{numeros[0]}–D{numeros[-1]}"


def _secao(texto: str, inicio: str, fim: str | None = None) -> str:
    """Extrai uma seccao pelo cabecalho, ate ao cabecalho seguinte do mesmo nivel."""
    indice = texto.find(inicio)
    if indice < 0:
        raise FonteCanonicaAusente(f"seccao {inicio!r} nao encontrada")
    resto = texto[indice + len(inicio) :]
    if fim:
        corte = resto.find(fim)
        if corte >= 0:
            resto = resto[:corte]
    return resto


def ler(raiz: Path) -> Conjuntos:
    """Le os tres conjuntos das fontes canonicas."""
    backlog = raiz / "specs" / "INDICE.md"
    arquitectura = raiz / "docs" / "tecnica" / "00_Arquitectura_Solucao.md"

    for caminho in (backlog, arquitectura):
        if not caminho.is_file():
            raise FonteCanonicaAusente(f"fonte canonica em falta: {caminho}")

    # --- KAM: §4, backlog mestre.
    texto_backlog = backlog.read_text(encoding="utf-8")
    secao_backlog = _secao(texto_backlog, "## 4. Backlog mestre", "\n## 5.")
    kam = frozenset(
        m.group("id")
        for linha in secao_backlog.split("\n")
        if (m := _LINHA_BACKLOG.match(linha))
    )
    if not kam:
        raise FonteCanonicaAusente(f"{backlog}: §4 sem linhas de ticket")

    # --- ADR: §8 da arquitectura.
    texto_arq = arquitectura.read_text(encoding="utf-8")
    secao_adr = _secao(texto_arq, "## 8. Decisões de arquitectura", "\n## 9.")
    adr = frozenset(
        m.group("id") for linha in secao_adr.split("\n") if (m := _LINHA_ADR.match(linha))
    )
    if not adr:
        raise FonteCanonicaAusente(f"{arquitectura}: §8 sem linhas de ADR")

    # --- D: §13.3 da arquitectura.
    secao_d = _secao(texto_arq, "### 13.3", "\n## 14.")
    d = frozenset(
        m.group("id") for linha in secao_d.split("\n") if (m := _LINHA_D.match(linha))
    )
    if not d:
        raise FonteCanonicaAusente(f"{arquitectura}: §13.3 sem linhas de decisão")

    return Conjuntos(
        kam=kam,
        adr=adr,
        d=d,
        origens={
            "KAM": f"{backlog.relative_to(raiz).as_posix()} §4",
            "ADR": f"{arquitectura.relative_to(raiz).as_posix()} §8",
            "D": f"{arquitectura.relative_to(raiz).as_posix()} §13.3",
        },
    )
