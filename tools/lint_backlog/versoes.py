"""O «Controlo de versoes» de cada documento: sequencia e cabecalho.

Duas verificacoes sobre a tabela que quase todos os documentos de `specs/` e de
`docs/` tem no fim:

(a) **as linhas formam uma sequencia continua.** Um numero saltado e um ramo que
    tomou um numero que outro ramo ja tinha tomado, e a emenda ficou sem linha.
(b) **onde o cabecalho tem campo de versao, ele iguala a ultima linha.**

**Porque e que isto e do gate e nao de quem escreve.** O buraco do `1.13` do
`specs/EPIC-01` nasceu de dois ramos tomarem o mesmo numero em paralelo, e a
emenda do CA 4 do KAM-136 renumerou **quatro** vezes em poucas horas pela mesma
razao. Com varios tickets a fundir no mesmo dia, a linha de versao e ponto de
contencao garantido, e nenhuma revisao humana a apanha de forma fiavel.

**O corpus exclui `docs/analises/` e `docs/evidencia/`**, pela razao que o
`lint_contagens` (KAM-158) ja escreveu para o seu: sao **registos datados**. Uma
analise adversarial mede o que era verdade no dia em que correu, e a evidencia
de um ticket registra o que se mediu no PR que o entregou.

**A tabela reconhece-se pela tabela, e nao pelo titulo da seccao.** O conjunto
usa cinco titulos diferentes para a mesma coisa — «Controlo de versoes»,
«6. Controlo de versoes», «7. Controlo de versoes e emendas», «7. Aprovacao,
versionamento e manutencao», «9. Aprovacao e controlo de versoes» — e ancorar no
titulo deixava de fora o `specs/INDICE.md` e o `specs/01`, que sao os dois
documentos em que isto mais custa.
"""

from __future__ import annotations

import re
from dataclasses import dataclass
from pathlib import Path

#: O cabecalho da tabela de historico. A terceira coluna varia («Descricao»,
#: «Alteracao») e a quarta tambem («Autor», «Aprovacao»): ancora-se nas duas
#: primeiras, que nao variam.
CABECALHO_DE_TABELA = re.compile(r'^\|\s*Versão\s*\|\s*Data\s*\|', re.M)
#: Uma linha de historico: `| 1.14 | Outubro 2026 | … |`.
LINHA_DE_VERSAO = re.compile(r'^\|\s*(\d+)\.(\d+)\s*\|', re.M)
#: Campo de versao numa tabela de campos (os epics, `specs/01`, `specs/02`).
CAMPO_EM_TABELA = re.compile(r'^\|\s*Versão\s*\|\s*(\d+\.\d+)\s*\|', re.M)
#: Campo de versao em texto corrido (`specs/INDICE.md`).
CAMPO_EM_TEXTO = re.compile(r'^\*\*Versão do conjunto:\*\*\s*(\d+\.\d+)', re.M)

#: Onde se procura.
PADROES = ('specs/**/*.md', 'docs/**/*.md', 'README.md')
#: Registos datados: ficam de fora por inteiro (ver o *docstring*).
PASTAS_DE_REGISTO = ('docs/analises/', 'docs/evidencia/')


class ControloIlegivel(RuntimeError):
    """A tabela existe e nao se consegue ler."""


@dataclass(frozen=True)
class Controlo:
    """O controlo de versoes de um documento."""

    ficheiro: str
    #: `(maior, menor)` de cada linha, por ordem de leitura.
    versoes: tuple[tuple[int, int], ...]
    #: O que o cabecalho diz, ou `None` se o documento nao tem campo de versao.
    cabecalho: str | None
    #: Como o cabecalho esta escrito: `'tabela'`, `'texto'` ou `None`.
    forma: str | None

    @property
    def ultima(self) -> str:
        maior, menor = max(self.versoes)
        return f'{maior}.{menor}'

    @property
    def buracos(self) -> tuple[str, ...]:
        """Os numeros que faltam para a sequencia ser continua.

        Conta-se por **maior**, e sobre o conjunto e nao sobre a ordem de
        leitura: o `specs/INDICE.md` tem o 1.2 escrito antes do 1.1, e isso e
        desarrumacao, nao buraco. O que o gate recusa e um numero que ninguem
        escreveu entre dois que alguem escreveu.
        """
        por_maior: dict[int, set[int]] = {}
        for maior, menor in self.versoes:
            por_maior.setdefault(maior, set()).add(menor)
        falta: list[str] = []
        for maior, menores in sorted(por_maior.items()):
            ordenados = sorted(menores)
            falta += [f'{maior}.{x}'
                      for x in range(ordenados[0], ordenados[-1] + 1)
                      if x not in menores]
        return tuple(falta)

    @property
    def atrasado(self) -> bool:
        return self.cabecalho is not None and self.cabecalho != self.ultima


def _corpo_da_tabela(texto: str, inicio: int) -> str:
    """Da linha do cabecalho ate a primeira linha que nao comeca por `|`."""
    linhas = texto[inicio:].split('\n')
    corpo: list[str] = []
    for linha in linhas[1:]:
        if not linha.startswith('|'):
            break
        corpo.append(linha)
    return '\n'.join(corpo)


def ler_documento(caminho: Path, raiz: Path) -> Controlo | None:
    """O controlo de versoes de um documento, ou `None` se nao tiver tabela.

    A **ausencia** de tabela nao e defeito e o gate nao a inventa: ha ficheiros
    de `docs/` que sao notas e nao documentos do conjunto. A ausencia do **campo
    de versao no cabecalho** tambem nao: 16 dos documentos com tabela nao o tem,
    e para esses so vale a verificacao da sequencia.
    """
    rel = caminho.relative_to(raiz).as_posix()
    texto = caminho.read_text(encoding='utf-8')
    achado = CABECALHO_DE_TABELA.search(texto)
    if achado is None:
        return None
    corpo = _corpo_da_tabela(texto, achado.start())
    versoes = tuple((int(a), int(b)) for a, b in LINHA_DE_VERSAO.findall(corpo))
    if not versoes:
        raise ControloIlegivel(
            f'{rel}: tem cabecalho de tabela de controlo de versoes e nenhuma '
            'linha `| N.M | …`. Uma tabela vazia da «sequencia continua» de '
            'graca, e isso e dizer conforme sobre o que nao se leu.')
    em_tabela = CAMPO_EM_TABELA.search(texto)
    em_texto = CAMPO_EM_TEXTO.search(texto)
    if em_tabela is not None and em_texto is not None:
        raise ControloIlegivel(
            f'{rel}: tem as duas formas de cabecalho de versao '
            f'(`| Versão | {em_tabela.group(1)} |` e `**Versão do conjunto:** '
            f'{em_texto.group(1)}`); nao se adivinha qual manda')
    campo = em_tabela or em_texto
    return Controlo(
        ficheiro=rel, versoes=versoes,
        cabecalho=campo.group(1) if campo else None,
        forma=('tabela' if em_tabela else 'texto' if em_texto else None))


def ficheiros(raiz: Path, padroes=PADROES) -> list[Path]:
    """Os documentos do corpus, sem repetidos e por ordem de nome.

    O filtro e sobre o caminho **relativo a raiz**, e nao sobre
    `Path.parts`: este repositorio tem copias completas de si proprio em
    `.claude/worktrees/*`, e um filtro posicional sobre o caminho absoluto
    esvazia o corpus inteiro quando o gate corre de dentro de uma delas.
    """
    vistos: dict[Path, None] = {}
    for padrao in padroes:
        for caminho in raiz.glob(padrao):
            if not caminho.is_file():
                continue
            rel = caminho.relative_to(raiz).as_posix()
            if rel.startswith(PASTAS_DE_REGISTO):
                continue
            vistos[caminho] = None
    return sorted(vistos, key=lambda f: f.relative_to(raiz).as_posix())


def varrer(raiz: Path, padroes=PADROES) -> list[Controlo]:
    saida: list[Controlo] = []
    for caminho in ficheiros(raiz, padroes):
        controlo = ler_documento(caminho, raiz)
        if controlo is not None:
            saida.append(controlo)
    return saida
