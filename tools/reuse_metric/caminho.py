"""A classificacao do caminho de execucao e a conta do reuso (KAM-039).

`reuso = 1 - LoC_especifico / LoC_total`, sobre o caminho de execucao da
vertical nova. As regras de contagem — o que cada classe quer dizer, o que
entra, o que sai e o que a metrica **nao** mede — estao em
`docs/reuse-metric.md`, e nao se repetem aqui: a mesma regra escrita em dois
sitios diverge no dia em que uma muda.

O que este modulo acrescenta ao que a declaracao diz:

* resolve o `misto` — o ficheiro de que a vertical nova importa **alguns**
  simbolos — lendo os `import` reais em vez de uma lista. Copiar um no em vez de
  o importar faz o simbolo sair do partilhado **e** o ficheiro especifico
  crescer: o numero desce nas duas pontas, e e isso que faz disto uma medida;
* recusa um ficheiro que bata em duas classes, em vez de deixar a ordem das
  linhas decidir;
* devolve a medicao **por entrada**, para que o numero se possa contestar linha
  a linha. Um reuso de 89% sem a lista de onde ele vem nao se pode defender nem
  atacar — e uma afirmacao, que e o que esta casa nao aceita.
"""

from __future__ import annotations

import fnmatch
from dataclasses import dataclass, field
from pathlib import Path
from typing import Final, Literal

from .fecho import Importacao, Resolvedor, fecho
from .migracoes import CadeiaInvalidaError, antepassados, ler_revisoes
from .sloc import SimboloAusenteError, sloc_de_ficheiro, sloc_de_simbolo

Classe = Literal["especifico", "partilhado", "misto", "outra_vertical", "excluido"]

#: As classes que a declaracao pode nomear. O `partilhado` nao esta: e o
#: **resto** — o que o fecho alcanca e nenhuma lista reclama. Escrever uma lista
#: de partilhados era escrever a resposta: o denominador passava a ser uma
#: escolha, e e precisamente o que a derivacao por fecho existe para evitar.
CLASSES_DECLARAVEIS: Final = ("especifico", "misto", "outra_vertical", "excluido")


class DeclaracaoInvalidaError(ValueError):
    """O `ci/regra-de-dois.yaml` esta malformado, ou classifica em duas classes."""


@dataclass(frozen=True, slots=True)
class Declaracao:
    """O `caminho:` de `ci/regra-de-dois.yaml`, validado."""

    vertical: str
    entradas: tuple[str, ...]
    pacotes: dict[str, str]
    padroes: dict[str, tuple[str, ...]]
    limiar: float
    #: A pasta das migracoes e as que sao da vertical. Ver `migracoes.py`.
    pasta_das_migracoes: str
    migracoes_proprias: tuple[str, ...]

    @classmethod
    def de_mapa(cls, bruto: dict, *, onde: str) -> Declaracao:
        caminho = bruto.get("caminho")
        if not isinstance(caminho, dict):
            raise DeclaracaoInvalidaError(f"{onde}: falta o mapa `caminho`")
        for chave in ("vertical", "entradas", "pacotes", "limiar"):
            if chave not in caminho:
                raise DeclaracaoInvalidaError(f"{onde}: falta `caminho.{chave}`")
        pacotes = caminho["pacotes"]
        if not isinstance(pacotes, dict) or not pacotes:
            raise DeclaracaoInvalidaError(f"{onde}: `caminho.pacotes` tem de ser um mapa")
        entradas = caminho["entradas"]
        if not isinstance(entradas, list) or not entradas:
            raise DeclaracaoInvalidaError(f"{onde}: `caminho.entradas` esta vazio")
        try:
            limiar = float(caminho["limiar"])
        except (TypeError, ValueError) as erro:
            raise DeclaracaoInvalidaError(
                f"{onde}: `caminho.limiar` tem de ser um numero"
            ) from erro
        migracoes = caminho.get("migracoes")
        if not isinstance(migracoes, dict):
            raise DeclaracaoInvalidaError(f"{onde}: falta o mapa `caminho.migracoes`")
        proprias = migracoes.get("proprias")
        if not isinstance(proprias, list) or not proprias:
            raise DeclaracaoInvalidaError(
                f"{onde}: `caminho.migracoes.proprias` tem de ser uma lista nao vazia"
            )
        if not migracoes.get("pasta"):
            raise DeclaracaoInvalidaError(f"{onde}: falta `caminho.migracoes.pasta`")
        return cls(
            vertical=str(caminho["vertical"]),
            entradas=tuple(str(e) for e in entradas),
            pacotes={str(k): str(v) for k, v in pacotes.items()},
            padroes={
                classe: tuple(str(p) for p in caminho.get(classe, ()) or ())
                for classe in CLASSES_DECLARAVEIS
            },
            limiar=limiar,
            pasta_das_migracoes=str(migracoes["pasta"]),
            migracoes_proprias=tuple(str(m) for m in proprias),
        )


@dataclass(frozen=True, slots=True)
class Entrada:
    """Uma linha da medicao: um ficheiro, ou um simbolo de um ficheiro misto."""

    caminho: str
    classe: Classe
    sloc: int
    simbolo: str | None = None
    #: Porque e que esta entrada tem esta classe. Vai no JSON, para que o
    #: numero se leia sem abrir a declaracao.
    razao: str = ""

    def como_mapa(self) -> dict:
        mapa = {
            "caminho": self.caminho,
            "classe": self.classe,
            "sloc": self.sloc,
            "razao": self.razao,
        }
        if self.simbolo is not None:
            mapa["simbolo"] = self.simbolo
        return mapa


@dataclass(frozen=True, slots=True)
class Medicao:
    """O resultado, com tudo o que a conta usou."""

    vertical: str
    especifico: int
    partilhado: int
    entradas: tuple[Entrada, ...]
    fora: tuple[Entrada, ...] = field(default_factory=tuple)

    @property
    def total(self) -> int:
        return self.especifico + self.partilhado

    @property
    def reuso(self) -> float:
        """Em percentagem. **Zero linhas nao e 100% de reuso**, e levanta."""
        if self.total == 0:
            raise DeclaracaoInvalidaError(
                "o caminho de execucao mediu 0 linhas: a declaracao nao alcanca "
                "nada, e um reuso calculado sobre zero nao quer dizer nada"
            )
        return 100.0 * (1.0 - self.especifico / self.total)

    def como_mapa(self) -> dict:
        """O artefacto JSON. Leva a conta **e** as parcelas."""
        return {
            "vertical": self.vertical,
            "formula": "reuso = 1 - LoC_especifico / LoC_total",
            "unidade": "linhas com codigo (SLOC); ver docs/reuse-metric.md",
            "loc_especifico": self.especifico,
            "loc_partilhado": self.partilhado,
            "loc_total": self.total,
            "reuso_pct": round(self.reuso, 2),
            "entradas": [e.como_mapa() for e in sorted(self.entradas, key=_ordem)],
            "fora_da_conta": [e.como_mapa() for e in sorted(self.fora, key=_ordem)],
        }


def _ordem(entrada: Entrada) -> tuple:
    return (entrada.classe, entrada.caminho, entrada.simbolo or "")


def classificar(relativo: str, declaracao: Declaracao) -> tuple[Classe, str]:
    """A classe de um ficheiro, e o padrao que a decidiu.

    **O `excluido` decide-se primeiro, e nao e um empate.** Ele nao e uma
    classe do caminho: e um filtro sobre o universo, como os `excluidos` de
    `ci/thresholds.yaml`. Um `fakes.py` dentro de `verticais/servicos/` bate
    nos dois — e a resposta certa e «fora da conta», nao «ambiguo»: ele e
    codigo de ensaio, e o §5.4 manda excluir testes seja onde for que vivam.

    **Entre as outras tres, uma dupla classificacao levanta.** O
    `ci/thresholds.yaml` resolve o empate pela ordem das linhas; aqui isso
    seria pior, porque a ordem decidia se um ficheiro vai ao numerador ou fica
    fora dele — e a diferenca entre as duas e o resultado. Quem escreve a
    declaracao e quem tem de desempatar.
    """
    for padrao in declaracao.padroes["excluido"]:
        if fnmatch.fnmatch(relativo, padrao):
            return "excluido", f"excluido por `{padrao}` (filtro, nao classe)"

    batidas = [
        (classe, padrao)
        for classe in CLASSES_DECLARAVEIS
        if classe != "excluido"
        for padrao in declaracao.padroes[classe]
        if fnmatch.fnmatch(relativo, padrao)
    ]
    distintas = {classe for classe, _ in batidas}
    if len(distintas) > 1:
        detalhe = "; ".join(f"{c} por `{p}`" for c, p in batidas)
        raise DeclaracaoInvalidaError(
            f"ci/regra-de-dois.yaml: `{relativo}` cai em mais de uma classe ({detalhe})"
        )
    if batidas:
        classe, padrao = batidas[0]
        return classe, f"padrao `{padrao}`"
    return "partilhado", "alcancado pelo fecho e nao reclamado por nenhum padrao"


def medir(raiz: Path, bruto: dict, *, onde: str = "ci/regra-de-dois.yaml") -> Medicao:
    """A medicao inteira, a partir da raiz do repositorio e da declaracao.

    **A raiz resolve-se aqui.** O `fecho` resolve os ficheiros que alcanca, e
    uma raiz nao resolvida deixava de ser prefixo deles: em Windows o
    `tempfile` devolve o caminho curto (`C:\\Users\\ARMAND~1\\...`) e o
    `resolve()` expande-o, pelo que o `relative_to` rebentava sobre a mesma
    pasta escrita de duas maneiras.
    """
    raiz = raiz.resolve()
    declaracao = Declaracao.de_mapa(bruto, onde=onde)
    resolvedor = Resolvedor(
        {nome: raiz / sub for nome, sub in declaracao.pacotes.items()}
    )

    entradas_do_fecho = []
    for relativo in declaracao.entradas:
        ficheiro = raiz / relativo
        if not ficheiro.is_file():
            raise DeclaracaoInvalidaError(
                f"{onde}: a entrada `{relativo}` nao existe no disco"
            )
        entradas_do_fecho.append(ficheiro)

    alcancados = fecho(resolvedor, tuple(entradas_do_fecho))

    # Os ficheiros `especifico` que a declaracao nomeia e o fecho **nao**
    # alcanca — o catalogo de tools e as migracoes. Juntam-se aos alcancados
    # antes de classificar, para que uma unica passagem decida tudo.
    declarados = _declarados_no_disco(raiz, declaracao)

    por_classe: dict[Classe, list[Entrada]] = {}
    especificos_no_disco: list[Path] = []
    mistos_no_disco: list[Path] = []

    for ficheiro in sorted(alcancados | declarados):
        relativo = ficheiro.relative_to(raiz).as_posix()
        classe, razao = classificar(relativo, declaracao)
        if classe == "misto":
            mistos_no_disco.append(ficheiro)
            continue
        if classe == "especifico":
            especificos_no_disco.append(ficheiro)
        por_classe.setdefault(classe, []).append(
            Entrada(
                caminho=relativo,
                classe=classe,
                sloc=sloc_de_ficheiro(ficheiro),
                razao=razao,
            )
        )

    simbolos = _simbolos_importados(
        resolvedor, especificos_no_disco, frozenset(mistos_no_disco)
    )
    for ficheiro in sorted(mistos_no_disco):
        relativo = ficheiro.relative_to(raiz).as_posix()
        nomes = sorted(simbolos.get(ficheiro, frozenset()))
        if not nomes:
            # Um misto de que nada se importa conta **zero**, e aparece no
            # relatorio a dizer isso. Nao se cala: um ficheiro no fecho sem
            # contribuicao e informacao sobre o acoplamento.
            por_classe.setdefault("misto", []).append(
                Entrada(
                    caminho=relativo,
                    classe="misto",
                    sloc=0,
                    razao="misto, e a vertical nova nao importa nenhum simbolo dele",
                )
            )
            continue
        for nome in nomes:
            por_classe.setdefault("partilhado", []).append(
                Entrada(
                    caminho=relativo,
                    classe="partilhado",
                    sloc=sloc_de_simbolo(ficheiro, nome),
                    simbolo=nome,
                    razao="simbolo importado de um ficheiro misto",
                )
            )

    for entrada in _entradas_das_migracoes(raiz, declaracao):
        por_classe.setdefault(entrada.classe, []).append(entrada)

    dentro = tuple(por_classe.get("especifico", ())) + tuple(
        por_classe.get("partilhado", ())
    )
    fora = (
        tuple(por_classe.get("outra_vertical", ()))
        + tuple(por_classe.get("excluido", ()))
        + tuple(por_classe.get("misto", ()))
    )
    return Medicao(
        vertical=declaracao.vertical,
        especifico=sum(e.sloc for e in por_classe.get("especifico", ())),
        partilhado=sum(e.sloc for e in por_classe.get("partilhado", ())),
        entradas=dentro,
        fora=fora,
    )


def _entradas_das_migracoes(raiz: Path, declaracao: Declaracao) -> tuple[Entrada, ...]:
    """As migracoes da vertical e a cadeia de que elas dependem.

    As duas pontas entram **juntas**, e e o ponto todo deste bloco: declarar so
    as da vertical punha 387 linhas no numerador e nenhuma no denominador. A
    razao por extenso esta em `migracoes.py`.
    """
    pasta = raiz / declaracao.pasta_das_migracoes
    revisoes = ler_revisoes(pasta)
    proprias = {nome: True for nome in declaracao.migracoes_proprias}
    entradas: list[Entrada] = []
    for revisao in revisoes:
        if revisao.ficheiro.name in proprias:
            entradas.append(
                Entrada(
                    caminho=revisao.ficheiro.relative_to(raiz).as_posix(),
                    classe="especifico",
                    sloc=sloc_de_ficheiro(revisao.ficheiro),
                    razao="migracao declarada como da vertical",
                )
            )
    for revisao in antepassados(revisoes, declaracao.migracoes_proprias):
        entradas.append(
            Entrada(
                caminho=revisao.ficheiro.relative_to(raiz).as_posix(),
                classe="partilhado",
                sloc=sloc_de_ficheiro(revisao.ficheiro),
                razao=f"antepassada da cadeia (revisao `{revisao.revisao}`)",
            )
        )
    return tuple(entradas)


def _declarados_no_disco(raiz: Path, declaracao: Declaracao) -> frozenset[Path]:
    """Os ficheiros que os padroes `especifico` nomeiam e existem no disco.

    Alarga-se a `especifico` e so a ele de proposito: um padrao `excluido` ou
    `outra_vertical` serve para **retirar** do que o fecho trouxe, e ir
    procura-lo ao disco trazia ficheiros que nao estao no caminho nenhum.
    """
    encontrados: set[Path] = set()
    # **Uma passagem pelo disco, nao uma por padrao.** `rglob("*.py")` e nao
    # `rglob("*")` porque a arvore tem `node_modules`; e o laco dos padroes esta
    # por dentro porque, estando por fora, cada padrao declarado custava uma
    # travessia inteira do repositorio.
    padroes = declaracao.padroes["especifico"]
    for ficheiro in raiz.rglob("*.py"):
        if not ficheiro.is_file():
            continue
        relativo = ficheiro.relative_to(raiz).as_posix()
        if any(fnmatch.fnmatch(relativo, padrao) for padrao in padroes):
            encontrados.add(ficheiro.resolve())
    return frozenset(encontrados)


def _simbolos_importados(
    resolvedor: Resolvedor,
    especificos: list[Path],
    mistos: frozenset[Path],
) -> dict[Path, frozenset[str]]:
    """Que simbolos e que os ficheiros da vertical nova trazem de cada misto.

    Le os `import` reais. Um nome que seja um **submodulo** e nao um simbolo
    salta-se: um `from ..vendedor import arestas` traz um modulo, que ja e uma
    entrada por direito proprio e nao um simbolo a contar duas vezes.

    Um nome que nao exista no ficheiro **levanta** (`SimboloAusenteError`, em
    `sloc_de_simbolo`): a declaracao e o codigo deixaram de bater, e um nome
    saltado em silencio era reuso a desaparecer da conta sem aviso.
    """
    recolhidos: dict[Path, set[str]] = {}
    for ficheiro in especificos:
        # Um `especifico` fora das raizes de pacote nao tem `import` que este
        # resolvedor saiba seguir — e o caso das migracoes, que sao Alembic e
        # vivem em `db/`. Saltam-se aqui e continuam a contar como ficheiro:
        # perguntar-lhes os `import` era pedir um nome de modulo que nao
        # existe, e foi o que rebentou na primeira corrida.
        if not _dentro_dos_pacotes(resolvedor, ficheiro):
            continue
        for importacao in resolvedor.importacoes(ficheiro):
            alvo = resolvedor.ficheiro_de(importacao.modulo)
            if alvo is None or alvo.resolve() not in mistos:
                continue
            for nome in _nomes_de_simbolo(resolvedor, importacao):
                recolhidos.setdefault(alvo.resolve(), set()).add(nome)
    return {k: frozenset(v) for k, v in recolhidos.items()}


def _dentro_dos_pacotes(resolvedor: Resolvedor, ficheiro: Path) -> bool:
    """O ficheiro esta debaixo de alguma raiz de pacote declarada?"""
    alvo = ficheiro.resolve()
    for base in resolvedor.pacotes.values():
        try:
            alvo.relative_to(base.resolve())
        except ValueError:
            continue
        return True
    return False


def _nomes_de_simbolo(resolvedor: Resolvedor, importacao: Importacao) -> tuple[str, ...]:
    return tuple(
        nome
        for nome in sorted(importacao.nomes)
        if resolvedor.ficheiro_de(f"{importacao.modulo}.{nome}") is None
    )


__all__ = [
    "Classe",
    "Declaracao",
    "DeclaracaoInvalidaError",
    "Entrada",
    "Medicao",
    "SimboloAusenteError",
    "classificar",
    "medir",
]
