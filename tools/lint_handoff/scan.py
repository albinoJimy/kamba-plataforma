"""Varre os blocos de handoff e classifica cada caminho que contem."""

from __future__ import annotations

import posixpath
import re
from dataclasses import dataclass
from pathlib import Path

#: O titulo que abre um bloco de *handoff*.
TITULO = '### Handoff para Claude Code'

#: Directorios de primeiro nivel do repositorio que um caminho pode citar.
#: Mantem-se explicito: uma lista fechada nao confunde prosa com caminho. A
#: lista e a arvore real, e nao a que se usa mais: a revisao adversarial do
#: KAM-145 mostrou que `infra`, `packages`, `.github` e `.claude` estavam de
#: fora, e que um `../` para qualquer deles passava o gate sem ser visto.
RAIZES = ('docs', 'specs', 'tools', 'ci', 'db', 'ops', 'canon', 'libs', 'services',
          'registry', 'infra', 'packages', '.github', '.claude')

_RAIZ_ALT = '|'.join(re.escape(r) for r in RAIZES)

#: Um caminho que cite uma das raizes, com ou sem `../` a frente, e com ou sem
#: `./`. O prefixo e capturado para se poder normalizar e decidir a classe.
#:
#: O *lookbehind* recusa `[\w.-]` mas **nao** a barra: `./../docs/x` tem de ser
#: visto, e um *lookbehind* que recusasse `/` deixava-o invisivel. Em troca, um
#: `a/docs/x` passa a ser lido como caminho — e e preferivel um falso positivo
#: declarado a um defeito que escapa em silencio.
#: A barra depois da raiz e OBRIGATORIA: sem ela, a palavra «docs» numa frase
#: contava como caminho.
_CAMINHO = re.compile(
    r'(?<![\w.-])((?:\.{1,2}/)*)(' + _RAIZ_ALT + r')(/[A-Za-z0-9_./-]*)'
)

#: Um ficheiro da biblioteca exploratoria citado sem directorio nenhum: nao
#: resolve de posicao nenhuma. A lista e dos nomes que o conjunto cita.
_NU = re.compile(
    r'(?<![/\w.-])(14-tese-minima-e-plano-de-validacao|01-modelo-negocios-angola-ai-first)\.md'
)

#: As classes de defeito que esta varredura reconhece.
DEFEITOS = ('acima-da-raiz', 'sem-directorio')


@dataclass(frozen=True)
class Achado:
    """Uma ocorrencia classificada, com onde e o que."""

    ficheiro: str
    linha: int
    classe: str
    texto: str

    @property
    def defeito(self) -> bool:
        return self.classe in DEFEITOS


def _blocos(linhas: list[str]) -> list[tuple[int, int]]:
    """Os intervalos [inicio, fim) das cercas de cada bloco de *handoff*.

    Um bloco e o titulo, seguido de uma cerca que abre, ate a cerca que fecha.
    Um titulo de nivel igual ou superior antes da cerca fecha o bloco: um
    ficheiro truncado nao faz a varredura engolir o resto do documento.

    Reconhece as duas cercas do Markdown — ``` e ~~~ — e exige que a cerca que
    fecha seja a mesma que abriu: uma cerca aninhada de marca diferente deixa
    de fechar o bloco a meio.
    """
    out: list[tuple[int, int]] = []
    i = 0
    n = len(linhas)
    while i < n:
        if ' '.join(linhas[i].split()) != TITULO:
            i += 1
            continue
        j = i + 1
        while j < n and not re.match(r'\s*(```|~~~)', linhas[j]):
            if re.match(r'^#{1,3} ', linhas[j]):
                break
            j += 1
        m = re.match(r'\s*(```|~~~)', linhas[j]) if j < n else None
        if m is None:
            i = j + 1
            continue
        marca = m.group(1)
        k = j + 1
        while k < n and linhas[k].strip() != marca:
            k += 1
        out.append((j + 1, min(k, n)))
        i = k + 1
    return out


def _classificar(prefixo: str, resto: str) -> str:
    """A classe de um caminho, decidida pela normalizacao e nao pela forma.

    Normaliza-se antes de julgar porque a forma engana: `docs/../../docs/x`
    comeca por uma raiz valida e sai da arvore a mesma, e `./../docs/x` esconde
    o `..` atras de um `./`.
    """
    normal = posixpath.normpath(prefixo + resto)
    if normal.startswith('..'):
        return 'acima-da-raiz'
    return 'relativo-a-raiz'


def varrer_ficheiro(caminho: Path, raiz: Path, excepcoes: tuple[str, ...] = ()) -> list[Achado]:
    """Classifica cada caminho dentro dos blocos de *handoff* de um ficheiro.

    `excepcoes` sao excertos de linha declarados: uma linha que contenha um
    deles nao se le. Serve para a linha cujo assunto **e** uma forma de caminho
    — um literal a produzir, e nao um ficheiro a abrir.
    """
    rel = caminho.relative_to(raiz).as_posix()
    linhas = caminho.read_text(encoding='utf-8').split('\n')
    out: list[Achado] = []
    for inicio, fim in _blocos(linhas):
        for idx in range(inicio, fim):
            linha = linhas[idx]
            if any(e in linha for e in excepcoes):
                continue
            for m in _CAMINHO.finditer(linha):
                prefixo, base, resto = m.group(1), m.group(2), m.group(3)
                out.append(Achado(rel, idx + 1, _classificar(prefixo, base + resto), m.group(0)))
            for m in _NU.finditer(linha):
                out.append(Achado(rel, idx + 1, 'sem-directorio', m.group(0)))
    return out


def varrer_arvore(raiz: Path, padrao: str = 'specs/EPIC-*.md',
                  excepcoes: tuple[str, ...] = ()) -> list[Achado]:
    """Varre os ficheiros que casam com `padrao`, por ordem de nome."""
    out: list[Achado] = []
    for f in sorted(raiz.glob(padrao)):
        out.extend(varrer_ficheiro(f, raiz, excepcoes))
    return out


def contar_blocos(raiz: Path, padrao: str = 'specs/EPIC-*.md') -> tuple[int, int]:
    """(blocos de *handoff* encontrados, titulos `## KAM-NNN` encontrados).

    Os dois numeros tem de bater. Sem isto, o `check` imprime «conforme» tanto
    sobre a populacao inteira como sobre zero blocos que o delimitador deixou
    de reconhecer — e e a segunda que mente.
    """
    blocos = titulos = 0
    for f in sorted(raiz.glob(padrao)):
        linhas = f.read_text(encoding='utf-8').split('\n')
        blocos += len(_blocos(linhas))
        titulos += sum(1 for l in linhas if re.match(r'^## KAM-\d+ ', l))
    return blocos, titulos
