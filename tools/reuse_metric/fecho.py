"""O fecho de importacao a partir dos pontos de entrada de um turno (KAM-039).

## Porque e que o caminho de execucao se deriva e nao se lista

O §5.4 manda medir o reuso «sobre o caminho de execucao da vertical». Uma lista
de ficheiros escrita a mao e a parte contestavel de qualquer metrica: quem a
escreve escolhe o resultado, e ninguem consegue distinguir uma omissao de uma
decisao. Medido neste ticket: a primeira lista, feita a mao com cuidado, deixava
de fora o `tls/com.py`, o `tls/vendedor.py` e o `tls/catalogo.py` — e os tres
sao alcancados a partir do grafo de Servicos, o que **e** um achado sobre o
acoplamento das duas verticais e nao um detalhe de contagem.

Por isso o caminho deriva-se: parte-se dos pontos de entrada declarados em
`ci/regra-de-dois.yaml` e segue-se cada `import` por AST, dentro das raizes de
pacote declaradas. O que fica a mao e so o que nenhum `import` alcanca — o
catalogo de tools, que e injectado por quem monta o servico — e isso esta
escrito na declaracao, com a razao.

## Fecho de importacao **nao** e caminho de execucao, e a diferenca e por cima

Um modulo importado pode ter codigo que nunca corre num turno de Servicos. O
fecho e portanto um **majorante** do caminho partilhado, e isso empurra o reuso
para **cima** — e a direccao desfavoravel a honestidade do numero, pelo que se
diz: a regra 7 do `docs/reuse-metric.md` escreve-o e o relatorio da o numero com
e sem os modulos que so a outra vertical executa.

O contrario — medir por execucao — exigia instrumentar um turno e media **um**
turno, nao a vertical: um caminho de execucao depende da intencao do cliente, e
nenhuma conversa atravessa os vinte e dois nos.

## Nao se importa nada para medir

Todo este modulo e analise estatica. Importar o `kamba_agr` daqui obrigava a
`langgraph` instalada no ambiente das suites de `tools/`, e punha o resultado da
metrica a depender de um `import` que corre codigo — que e a classe de defeito
que o `politica_ast.py` deste repositorio ja recusou uma vez.
"""

from __future__ import annotations

import ast
from dataclasses import dataclass
from pathlib import Path


class ModuloForaDosPacotesError(ValueError):
    """Pediu-se o nome de modulo de um ficheiro fora das raizes declaradas."""


@dataclass(frozen=True, slots=True)
class Importacao:
    """Um `import` resolvido: o modulo alvo e os nomes trazidos de la.

    `nomes` e vazio num `import x` simples — nao se traz simbolo nenhum, so o
    modulo. Num `from x import a, b` traz `{"a", "b"}`, e e dai que sai a lista
    de simbolos de um ficheiro `misto` (ver `caminho.py`).
    """

    modulo: str
    nomes: frozenset[str]


class Resolvedor:
    """Converte nomes de modulo em ficheiros, dentro das raizes declaradas."""

    def __init__(self, pacotes: dict[str, Path]) -> None:
        self._pacotes = dict(pacotes)

    @property
    def pacotes(self) -> dict[str, Path]:
        return dict(self._pacotes)

    def ficheiro_de(self, modulo: str) -> Path | None:
        """O ficheiro de um modulo, ou `None` se for externo ou nao existir.

        `None` cobre tres casos que nao se distinguem aqui de proposito: a
        biblioteca padrao, uma dependencia de terceiros, e um `from x import y`
        em que o `y` e um simbolo e nao um submodulo. Nos tres a resposta e a
        mesma — nao ha ficheiro nosso para seguir.
        """
        partes = modulo.split(".")
        base = self._pacotes.get(partes[0])
        if base is None:
            return None
        alvo = base.joinpath(*partes[1:])
        modulo_simples = alvo.with_suffix(".py")
        if modulo_simples.is_file():
            return modulo_simples
        inicializador = alvo / "__init__.py"
        if inicializador.is_file():
            return inicializador
        return None

    def modulo_de(self, caminho: Path) -> str:
        """O nome de modulo de um ficheiro dentro de uma raiz declarada."""
        for nome, base in self._pacotes.items():
            try:
                relativo = caminho.resolve().relative_to(base.resolve())
            except ValueError:
                continue
            partes = list(relativo.parts)
            if partes[-1] == "__init__.py":
                partes = partes[:-1]
            else:
                partes[-1] = partes[-1].removesuffix(".py")
            return ".".join([nome, *partes])
        raise ModuloForaDosPacotesError(
            f"{caminho} nao esta em nenhuma das raizes {sorted(self._pacotes)}"
        )

    def importacoes(self, caminho: Path) -> tuple[Importacao, ...]:
        """Os `import` de um ficheiro, com os relativos ja resolvidos."""
        meu = self.modulo_de(caminho)
        # O **pacote** de onde um `import` relativo conta. Para um
        # `__init__.py` e o proprio modulo; para os outros e o pai. Enganar-se
        # aqui desloca todos os relativos de um nivel, e o fecho passava a
        # alcancar o pacote irmao em vez do alvo.
        pacote = meu if caminho.name == "__init__.py" else meu.rpartition(".")[0]

        encontradas: list[Importacao] = []
        arvore = ast.parse(caminho.read_text(encoding="utf-8"))
        for no in ast.walk(arvore):
            if isinstance(no, ast.Import):
                for apelido in no.names:
                    encontradas.append(
                        Importacao(modulo=apelido.name, nomes=frozenset())
                    )
            elif isinstance(no, ast.ImportFrom):
                alvo = self._alvo_de(no, pacote)
                encontradas.append(
                    Importacao(
                        modulo=alvo,
                        nomes=frozenset(a.name for a in no.names if a.name != "*"),
                    )
                )
        return tuple(encontradas)

    @staticmethod
    def _alvo_de(no: ast.ImportFrom, pacote: str) -> str:
        if not no.level:
            return no.module or ""
        partes = pacote.split(".")
        # `level=1` e o proprio pacote; cada nivel a mais sobe um.
        acima = no.level - 1
        base = partes[: len(partes) - acima] if acima else partes
        return ".".join([*base, *([no.module] if no.module else [])])


def fecho(resolvedor: Resolvedor, entradas: tuple[Path, ...]) -> frozenset[Path]:
    """Todos os ficheiros nossos alcancaveis por `import` desde as entradas.

    Inclui as proprias entradas. A travessia e por largura com pilha e nao
    recursiva, porque o grafo de importacao deste repositorio tem ciclos — o
    `handoff/portas.py` e o `handoff/maquina.py`, por exemplo — e uma recursao
    ingenua rebentava neles.
    """
    vistos: set[Path] = set()
    pilha = [e.resolve() for e in entradas]
    while pilha:
        ficheiro = pilha.pop()
        if ficheiro in vistos:
            continue
        vistos.add(ficheiro)
        for importacao in resolvedor.importacoes(ficheiro):
            for candidato in _candidatos(importacao):
                alvo = resolvedor.ficheiro_de(candidato)
                if alvo is not None and alvo.resolve() not in vistos:
                    pilha.append(alvo.resolve())
    return frozenset(vistos)


def _candidatos(importacao: Importacao) -> tuple[str, ...]:
    """O modulo, e cada nome como submodulo possivel.

    Um `from . import nos` traz o `nos` como **nome**, e o modulo alvo e o
    pacote: sem esta expansao o fecho parava no `__init__.py`. Um nome que nao
    seja submodulo nao resolve e nao custa nada.
    """
    return (importacao.modulo, *(f"{importacao.modulo}.{n}" for n in importacao.nomes))
