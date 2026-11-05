"""As migracoes do caminho de execucao, pela cadeia do Alembic (KAM-039).

## Porque e que as migracoes precisam de regra propria

O §5.4 poe «migracoes» no caminho de execucao, e as migracoes sao o unico termo
dessa lista que **nao tem grafo de importacao**: ninguem importa uma migracao.
Derivar o caminho por `import`, como o `fecho.py` faz para o codigo, deixava-as
todas de fora.

A primeira versao deste ticket resolveu-o declarando as duas migracoes da
vertical nova como `especifico` e nao declarando nenhuma partilhada — e isso
media **mal**, de uma forma que vale a pena escrever porque passava
despercebida: as 387 linhas do esquema `servicos` entravam no numerador e as
~1 000 linhas de `platform` sobre as quais elas correm nao entravam no
denominador. O reuso descia por um erro de contagem, nao por codigo duplicado.
Uma assimetria assim, mesmo na direccao conservadora, e um defeito: o numero
move-se por uma razao que nao e a que ele afirma medir.

## A regra, e porque e mecanica

O Alembic ja tem a resposta. Cada revisao declara o `down_revision`, pelo que a
cadeia de que uma migracao **depende** le-se do disco e nao de uma opiniao:

```text
proprias     as migracoes da vertical nova (declaradas, com razao escrita)
partilhado   a cadeia de antepassados dessas, menos elas proprias
fora         tudo o que nao esta na cadeia — e, por construcao, o que vem
             DEPOIS: a `0027` a `0031` sao pagamentos e encomendas, e uma
             marcacao nao corre sobre elas
```

Neste repositorio a cadeia e linear (`0001` <- `0002` <- ... <- `0031`), pelo
que os antepassados da `0026` sao a `0001` a `0025`. A linearidade **nao** esta
assumida no codigo: a travessia segue o `down_revision` e aceita ramos, porque
uma cadeia que se bifurque e exactamente o dia em que uma suposicao escrita aqui
daria o numero errado em silencio.

## O que fica declarado, e nao pode nao ficar

Quais migracoes sao «da vertical» e um juizo, e por isso esta em
`ci/regra-de-dois.yaml` com a razao de cada uma — nao aqui. O caso de fronteira
e a `0026_codigos_de_agenda`, que altera uma tabela **partilhada**
(`platform.tool_audit`) para lhe acrescentar dois codigos de erro da agenda:
pelo esquema que toca era partilhada, pela razao de existir e da vertical.
Conta como da vertical, e a sensibilidade esta medida — sao **19** linhas, e a
classificacao oposta move o reuso em menos de 0,2 pontos. Dizer o numero vale
mais do que ganhar a discussao.
"""

from __future__ import annotations

import ast
from dataclasses import dataclass
from pathlib import Path


class CadeiaInvalidaError(ValueError):
    """A pasta de migracoes, ou a cadeia de revisoes, nao se consegue ler."""


@dataclass(frozen=True, slots=True)
class Revisao:
    """Uma migracao: o ficheiro, a sua revisao e a de que depende."""

    ficheiro: Path
    revisao: str
    anterior: str | None


def _literal(arvore: ast.Module, nome: str) -> object | None:
    """O valor de uma atribuicao de topo `nome = <literal>`, se existir.

    Por AST e nao por `import`: uma migracao do Alembic importa o `op` e o `sa`
    ao nivel do modulo, e importa-la para lhe ler duas cadeias era correr
    codigo de terceiros para responder a uma pergunta de contagem.
    """
    for instrucao in arvore.body:
        alvos: list[ast.expr] = []
        if isinstance(instrucao, ast.Assign):
            alvos = list(instrucao.targets)
        elif isinstance(instrucao, ast.AnnAssign):
            alvos = [instrucao.target]
        for alvo in alvos:
            if isinstance(alvo, ast.Name) and alvo.id == nome:
                try:
                    return ast.literal_eval(instrucao.value)  # type: ignore[arg-type]
                except (ValueError, TypeError):
                    return None
    return None


def ler_revisoes(pasta: Path) -> tuple[Revisao, ...]:
    """Todas as migracoes de uma pasta, com a sua cadeia."""
    if not pasta.is_dir():
        raise CadeiaInvalidaError(f"{pasta} nao e uma pasta de migracoes")
    revisoes: list[Revisao] = []
    for ficheiro in sorted(pasta.glob("*.py")):
        arvore = ast.parse(ficheiro.read_text(encoding="utf-8"))
        revisao = _literal(arvore, "revision")
        if not isinstance(revisao, str):
            raise CadeiaInvalidaError(
                f"{ficheiro}: nao tem uma `revision` literal ao nivel de topo"
            )
        anterior = _literal(arvore, "down_revision")
        revisoes.append(
            Revisao(
                ficheiro=ficheiro,
                revisao=revisao,
                anterior=anterior if isinstance(anterior, str) else None,
            )
        )
    if not revisoes:
        raise CadeiaInvalidaError(f"{pasta}: nenhuma migracao")
    return tuple(revisoes)


def antepassados(
    revisoes: tuple[Revisao, ...], sementes: tuple[str, ...]
) -> tuple[Revisao, ...]:
    """A cadeia de que as `sementes` dependem, sem as proprias sementes.

    `sementes` sao **nomes de ficheiro**, e nao identificadores de revisao: e o
    nome do ficheiro que uma pessoa escreve na declaracao e reconhece num
    `git log`. Um nome que nao exista levanta, porque uma semente que deixou de
    estar no disco e uma declaracao a apontar para o vazio — e a cadeia saia
    silenciosamente mais curta, com o denominador a encolher.
    """
    por_ficheiro = {r.ficheiro.name: r for r in revisoes}
    por_revisao = {r.revisao: r for r in revisoes}

    ausentes = [nome for nome in sementes if nome not in por_ficheiro]
    if ausentes:
        raise CadeiaInvalidaError(
            f"as migracoes declaradas {ausentes} nao estao em "
            f"{revisoes[0].ficheiro.parent}"
        )

    nomes_das_sementes = {por_ficheiro[nome].revisao for nome in sementes}
    vistos: set[str] = set()
    pilha = [por_ficheiro[nome].anterior for nome in sementes]
    while pilha:
        actual = pilha.pop()
        if actual is None or actual in vistos:
            continue
        if actual not in por_revisao:
            raise CadeiaInvalidaError(
                f"a revisao `{actual}` e referida por um `down_revision` e nao "
                "existe na pasta: a cadeia esta partida"
            )
        vistos.add(actual)
        pilha.append(por_revisao[actual].anterior)

    # Uma semente pode ser antepassada de outra — a `0025` e da `0026`. Nesse
    # caso ela e **da vertical** e nao partilhada: a classe de uma migracao
    # decide-se pela declaracao e nao por onde ela aparece na travessia.
    return tuple(
        por_revisao[r] for r in sorted(vistos - nomes_das_sementes)
    )


__all__ = ["CadeiaInvalidaError", "Revisao", "antepassados", "ler_revisoes"]
