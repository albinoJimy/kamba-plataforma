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
"""

from __future__ import annotations

import re
from collections import Counter

#: Uma revisao do alembic. O numero e o nome do ficheiro; o `revision = "..."`
#: de dentro e o que o alembic le — os dois tem de concordar, e medem-se os dois.
FICHEIRO_DE_REVISAO = re.compile(r"^db/migrations/versions/(\d{4})_[^/]+\.py$")
REVISAO = re.compile(r'^revision\s*(?::\s*str\s*)?=\s*"([^"]+)"', re.MULTILINE)
PAI = re.compile(r'^down_revision\s*(?::[^=]+)?=\s*(None|"([^"]+)")', re.MULTILINE)

#: A tabela de «Controlo de versoes» comeca nesta linha; o cabecalho do documento
#: e a linha `| Versao | N.M ...` que aparece antes dela.
INICIO_DA_TABELA = re.compile(r"^\| Versão \| Data \|")
LINHA_DA_TABELA = re.compile(r"^\| (\d+\.\d+) \|")
CABECALHO = re.compile(r"^\| Versão \| (\d+\.\d+)\b")

#: O dicionario e o unico documento cujo cabecalho um ensaio exige igual a ultima
#: emenda (`dict_export`, `test_a_versao_do_cabecalho_e_a_da_ultima_emenda`). Nos
#: outros a divergencia e INDICIO e nao vermelho.
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

def versoes(texto: str) -> list[str]:
    """Os numeros da coluna «Versao» de todas as tabelas de controlo, por ordem.

    So conta linhas **dentro** de uma tabela que comece em `| Versao | Data |`: um
    `| 1.6 |` solto noutro sitio (a linha 1.6 da *checklist* do `Gate_Fase0.md`, por
    exemplo) nao e uma emenda.
    """
    resultado: list[str] = []
    dentro = False
    for linha in texto.splitlines():
        if INICIO_DA_TABELA.match(linha):
            dentro = True
            continue
        if dentro:
            if not linha.startswith("|"):
                dentro = False
                continue
            achado = LINHA_DA_TABELA.match(linha)
            if achado:
                resultado.append(achado.group(1))
    return resultado


def cabecalho(texto: str) -> str | None:
    for linha in texto.splitlines():
        if INICIO_DA_TABELA.match(linha):
            return None
        achado = CABECALHO.match(linha)
        if achado:
            return achado.group(1)
    return None


def maximo(numeros: list[str]) -> str | None:
    """O **maximo** da coluna, e nao a ultima linha: ha tabelas fora de ordem.

    Medido: a do `docs/agr.md` acaba em 1.12, 1.15, 1.14, 1.13 — ler a ultima
    linha da 1.13 e tomar a 1.14 duplica uma emenda (KAM-069).
    """
    return max(numeros, key=chave) if numeros else None


def problemas_de_versoes(caminho: str, texto: str) -> list[str]:
    """Duplicados na coluna, e o cabecalho atras do maximo."""
    problemas: list[str] = []
    numeros = versoes(texto)
    for numero, vezes in sorted(Counter(numeros).items(), key=lambda par: chave(par[0])):
        if vezes > 1:
            problemas.append(f"{caminho}: a versao {numero} aparece {vezes} vezes na tabela")
    topo = maximo(numeros)
    topo_do_cabecalho = cabecalho(texto)
    if topo and topo_do_cabecalho and topo_do_cabecalho != topo:
        grau = "VERMELHO no dict_export" if caminho == DICIONARIO else "INDICIO"
        problemas.append(f"{caminho}: cabecalho {topo_do_cabecalho} e a emenda mais alta e "
                         f"{topo} ({grau})")
    return problemas


def acrescentadas(antes: str | None, depois: str | None) -> list[str]:
    """As versoes que `depois` tem e `antes` nao — as emendas que um ramo escreveu."""
    ja = Counter(versoes(antes or ""))
    novas: list[str] = []
    for numero in versoes(depois or ""):
        if ja[numero] > 0:
            ja[numero] -= 1
        else:
            novas.append(numero)
    return novas


# --- piso do lint_bloco -----------------------------------------------------

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
