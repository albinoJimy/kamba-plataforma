"""As superficies que so admitem um escritor por fusao, medidas sobre texto.

Tres superficies desta casa serializam qualquer lote, seja qual for o epic de cada
ticket, e o lote de 2026-11-08 colidiu nas tres ao mesmo tempo (KAM-185):

```text
cadeia do alembic        duas 0037 em dois PRs abertos (#158, #159)
tabela de versoes        tres PRs escreveram todos a 1.68 do dicionario
piso do lint_bloco       cada seccao de verificacao sobe-o, de duas em duas
```

Aqui so ha funcoes sobre texto, sem `git` nem disco, para que os ensaios as possam
medir com o defeito plantado. Quem le as arvores e o `fonte.py`.

**As tabelas de versoes leem-se com o parser do gate 3c**, e nao com um meu: a
primeira versao deste modulo tinha regras proprias e enganou-se em duas — nao lia o
cabecalho `**Versao do conjunto:** N.M` do `specs/INDICE.md`, e nao media buracos —,
pelo que dava PRONTO a uma arvore que o `lint_backlog` recusava (achado da revisao
adversarial). O que a fila tem de prever e o veredicto **daquele** portao.
"""

from __future__ import annotations

import re
import sys
from pathlib import Path

_TOOLS = Path(__file__).resolve().parents[4] / "tools"
if str(_TOOLS) not in sys.path:
    sys.path.insert(0, str(_TOOLS))

from lint_backlog import versoes as _gate  # noqa: E402

#: Uma revisao do alembic. O numero e o nome do ficheiro; o `revision = "..."`
#: de dentro e o que o alembic le — os dois tem de concordar, e medem-se os dois.
FICHEIRO_DE_REVISAO = re.compile(r"^db/migrations/versions/(\d{4})_[^/]+\.py$")
REVISAO = re.compile(r'^revision\s*(?::\s*str\s*)?=\s*"([^"]+)"', re.MULTILINE)
PAI = re.compile(r'^down_revision\s*(?::[^=]+)?=\s*(None|"([^"]+)")', re.MULTILINE)

#: O unico documento cujo cabecalho tambem um ensaio de outra suite exige igual a
#: ultima emenda (`dict_export`, `test_a_versao_do_cabecalho_e_a_da_ultima_emenda`).
DICIONARIO = "specs/02_Dicionario_de_Dados_Canonico.md"


def chave(versao: str) -> tuple[int, ...]:
    """`1.9 < 1.10`: as versoes comparam-se por numero, nunca por texto."""
    return tuple(int(parte) for parte in versao.split("."))


def seguinte(versao: str) -> str:
    principal, menor = versao.split(".")
    return f"{principal}.{int(menor) + 1}"


# --- cadeia do alembic ------------------------------------------------------

def numero_de_revisao(caminho: str) -> str | None:
    achado = FICHEIRO_DE_REVISAO.match(caminho)
    return achado.group(1) if achado else None


def revisao_e_pai(texto: str) -> tuple[str | None, str | None]:
    """`(revision, down_revision)` do texto de uma revisao; o pai `None` e a raiz."""
    revisao = REVISAO.search(texto)
    pai = PAI.search(texto)
    return (revisao.group(1) if revisao else None,
            pai.group(2) if pai and pai.group(2) else None)


def problemas_da_cadeia(revisoes: dict[str, str]) -> list[str]:
    """O que parte o `alembic upgrade head`, dado `{caminho: texto}` de cada revisao.

    Quatro defeitos, e cada um ja custou um vermelho: dois ficheiros com o mesmo
    numero, um pai que nao existe (o buraco do #158 enquanto a 0037 nao estava na
    `main`), mais do que uma cabeca, e o nome do ficheiro a dizer outro numero que
    o `revision` de dentro (a renumeracao feita a meio).
    """
    problemas: list[str] = []
    por_numero: dict[str, list[str]] = {}
    pais: dict[str, str | None] = {}
    for caminho, texto in sorted(revisoes.items()):
        numero = numero_de_revisao(caminho)
        revisao, pai = revisao_e_pai(texto)
        if revisao is None:
            problemas.append(f"{caminho}: sem `revision = \"...\"`")
            continue
        if numero is not None and numero != revisao:
            problemas.append(f"{caminho}: o ficheiro diz {numero} e o `revision` diz {revisao}")
        por_numero.setdefault(revisao, []).append(caminho)
        pais[revisao] = pai
    for revisao, caminhos in sorted(por_numero.items()):
        if len(caminhos) > 1:
            problemas.append(f"revisao {revisao} em {len(caminhos)} ficheiros: {', '.join(caminhos)}")
    for revisao, pai in sorted(pais.items()):
        if pai is not None and pai not in pais:
            problemas.append(f"revisao {revisao} aponta para {pai}, que nao existe nesta arvore")
    filhos = {pai for pai in pais.values() if pai is not None}
    cabecas = sorted(set(pais) - filhos)
    if len(cabecas) > 1:
        problemas.append(f"{len(cabecas)} cabecas na cadeia: {', '.join(cabecas)}")
    return problemas


def cabeca(revisoes: dict[str, str]) -> str | None:
    """A revisao mais alta, por numero. So tem sentido numa cadeia sem problemas."""
    numeros = [revisao_e_pai(texto)[0] for texto in revisoes.values()]
    numeros = [n for n in numeros if n is not None and n.isdigit()]
    return max(numeros, key=int) if numeros else None


# --- tabelas de versoes -----------------------------------------------------

def medido_pelo_gate(caminho: str) -> bool:
    """O que o `lint_backlog` varre: `specs/**/*.md`, `docs/**/*.md` e o README,
    menos as pastas de registo datado. Uma declaracao em `ci/backlog-allow.yaml`
    pode ainda dispensar um documento, e isso este modulo nao le."""
    if caminho.startswith(_gate.PASTAS_DE_REGISTO):
        return False
    return caminho == "README.md" or (caminho.startswith(("specs/", "docs/"))
                                      and caminho.endswith(".md"))


def controlo(caminho: str, texto: str) -> _gate.Controlo | None:
    """O `Controlo` que o gate 3c faria deste texto: **a primeira** tabela de
    controlo, as duas formas de cabecalho, `buracos`, `repetidas` e `atrasado`."""
    achado = _gate.CABECALHO_DE_TABELA.search(texto)
    if achado is None:
        return None
    corpo = _gate._corpo_da_tabela(texto, achado.start())
    lidas = tuple((int(a), int(b)) for a, b in _gate.LINHA_DE_VERSAO.findall(corpo))
    if not lidas:
        return None
    em_tabela = _gate.CAMPO_EM_TABELA.search(texto)
    em_texto = _gate.CAMPO_EM_TEXTO.search(texto)
    campo = em_tabela or em_texto
    return _gate.Controlo(ficheiro=caminho, versoes=lidas,
                          cabecalho=campo.group(1) if campo else None,
                          forma="tabela" if em_tabela else "texto" if em_texto else None)


def versoes(texto: str) -> list[str]:
    """Os numeros da coluna «Versao» da tabela de controlo, pela ordem de leitura."""
    lido = controlo("", texto)
    return [f"{a}.{b}" for a, b in lido.versoes] if lido else []


def cabecalho(texto: str) -> str | None:
    lido = controlo("", texto)
    return lido.cabecalho if lido else None


def maximo(numeros: list[str]) -> str | None:
    """O **maximo** da coluna, e nao a ultima linha: ha tabelas fora de ordem.

    Medido: a do `docs/agr.md` acaba em 1.12, 1.15, 1.14, 1.13 — ler a ultima
    linha da 1.13 e tomar a 1.14 duplica uma emenda (KAM-069).
    """
    return max(numeros, key=chave) if numeros else None


def problemas_de_versoes(caminho: str, texto: str) -> list[str]:
    """O que o gate 3c recusa: repetidas, buracos e o cabecalho atras da emenda."""
    lido = controlo(caminho, texto)
    if lido is None:
        return []
    grau = "VERMELHO no gate 3c" if medido_pelo_gate(caminho) else "fora do gate 3c"
    problemas = [f"{caminho}: a versao {v} aparece mais de uma vez ({grau})"
                 for v in lido.repetidas]
    problemas += [f"{caminho}: falta a versao {v} na sequencia ({grau})"
                  for v in lido.buracos]
    if lido.atrasado:
        extra = ", e no dict_export" if caminho == DICIONARIO else ""
        problemas.append(f"{caminho}: cabecalho {lido.cabecalho} e a emenda mais alta e "
                         f"{lido.ultima} ({grau}{extra})")
    return problemas


def acrescentadas(antes: str | None, depois: str | None) -> list[str]:
    """As versoes que `depois` tem e `antes` nao — as emendas que um ramo escreveu."""
    ja: dict[str, int] = {}
    for numero in versoes(antes or ""):
        ja[numero] = ja.get(numero, 0) + 1
    novas: list[str] = []
    for numero in versoes(depois or ""):
        if ja.get(numero, 0) > 0:
            ja[numero] -= 1
        else:
            novas.append(numero)
    return novas


# --- piso do lint_bloco -----------------------------------------------------

#: A constante, e o literal par dela no arreio de mutacao do `lint_bloco`: subir uma
#: sem a outra deixa a mutacao inaplicavel em silencio (KAM-060: quatro vezes em
#: quatro epics, e so o `--aplicaveis` o apanha).
PISO = re.compile(r"^MINIMO_DE_BLOCOS_MEDIDOS\s*=\s*(\d+)", re.MULTILINE)
PAR_DO_PISO = "tools/lint_bloco/mutacao.py"


def piso_exigido(medidos: int) -> int:
    """O que os dois ensaios do `lint_bloco` exigem: `medidos // 2 <= piso <= medidos`."""
    return medidos // 2


def problema_do_piso(medidos: int, piso: int) -> str | None:
    if piso < piso_exigido(medidos):
        return (f"piso {piso} abaixo de metade de {medidos} medidos: sobe "
                f"`MINIMO_DE_BLOCOS_MEDIDOS` para {piso_exigido(medidos)}")
    if piso > medidos:
        return f"piso {piso} acima dos {medidos} medidos"
    return None
