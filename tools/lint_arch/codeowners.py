"""Os caminhos do `CODEOWNERS` resolvem contra a arvore seguida pelo git.

**O defeito que isto fecha.** Uma regra de `CODEOWNERS` cujo padrao nao casa com
nada **nao e recusada pelo GitHub: e ignorada**. A pasta fica sem dono, em
silencio, e o efeito e o contrario do que o ficheiro existe para fazer. Foi o que
aconteceu entre o KAM-128 (que moveu o conjunto documental para `docs/`) e o
a correccao manual que se lhe seguiu: tres regras ficaram presas ao
prefixo `/tecnica/`, e `docs/tecnica/` caiu na regra geral `*` enquanto o
documento 08 de seguranca perdeu o dono de Seguranca que a regra especifica lhe
dava. Sobreviveu a dois tickets cujo objectivo era medir referencias, porque
nenhum dos tres mecanismos existentes olha para dentro deste ficheiro:
`structure.py` via que o ficheiro **existe** e nunca lia uma linha dele; o gate 3
valida *tokens* `KAM-NNN`, nao caminhos; e as buscas G1-G3 do KAM-128 varrem
`.md`, e o `CODEOWNERS` nao tem extensao.

**Porque nao chega o `[ -e ]`.** O comando com que o defeito foi medido a mao resolve
cada padrao com `test -e`, e ele proprio declara a ressalva (evidencia do
`fix/...-codeowners-no-prefixo-removido`, §1.1): um padrao de `CODEOWNERS` pode
casar sem ser um caminho literal.
`*.md`, `**/x` e `/a/*/b` casam com ficheiros reais e **nenhum deles existe como
caminho**, pelo que `[ -e ]` diria «pendurada» a uma regra sa. Ao contrario:
`/docs/*/inexistente` nao existe como caminho e tambem nao casa com nada, e ai os
dois concordam. Hoje nenhuma das 18 regras usa curingas no meio, pelo que a
equivalencia «padrao resolve <-> caminho existe» vale — e deixa de valer no dia em
que alguem escrever `*.md`. Este modulo implementa a semantica de *glob*, nao a
verificacao ingenua, **para que o gate nao de «conforme» sem ter verificado**.

**A arvore e a do git, nao a do disco.** Pela mesma razao do gate 3: os
`.claude/worktrees/*` sao copias completas do repositorio, ignoradas pelo git e
visiveis a qualquer `os.walk`. E porque e a arvore do git que o GitHub resolve:
uma pasta que existe no disco sem nenhum ficheiro seguido **nao atribui dono a
nada**, e o `[ -e ]` dava-a por boa.

**A sintaxe, como o GitHub a documenta** (CONFIRMADO, fonte primaria:
<https://docs.github.com/en/repositories/managing-your-repositorys-settings-and-features/customizing-your-repository/about-code-owners>,
lido a 2026-10-12). Um padrao «segue a maior parte das mesmas regras dos
ficheiros gitignore», com tres excepcoes que a propria pagina enumera: **`!` para
negar nao funciona**, **`[ ]` para definir um intervalo de caracteres nao
funciona** e **`\\` para escapar um `#` nao funciona**. O `?` do gitignore **nao e
mencionado** — NAO VERIFICADO. Dai `NAO_SUPORTADOS`: um padrao que use um destes
e recusado pelo nome, e nao resolvido como se fosse literal. Resolve-lo seria
inventar uma semantica que a fonte nao da, e um gate que adivinha e pior do que
um gate que nao existe.
"""

from __future__ import annotations

import re
import subprocess
from dataclasses import dataclass
from pathlib import Path

#: Caracteres que o GitHub documenta como nao suportados, e o `?`, que a
#: documentacao nao menciona. Um padrao que os use nao se resolve por adivinha:
#: fail-closed, como o leitor de manifestos faz a uma declaracao que nao
#: consegue classificar (`cli.py`, `name == "?"`).
#:
#: O `#` nao entra aqui: a cabeca da linha e comentario (tratado no parser) e no
#: meio de um padrao e literal — o que a documentacao diz e que **escapa-lo** com
#: `\\` nao funciona, e o `\\` ja esta recusado.
#:
#: **Recusa de mais, de proposito:** um `]` sozinho, num nome de ficheiro que o
#: contenha de verdade, e recusado como se fosse um intervalo. Sem escape nao ha
#: forma de distinguir os dois casos, e a direccao do erro e a que se quer — a
#: pessoa ve a linha e decide, em vez de o gate adivinhar e ficar calado.
NAO_SUPORTADOS = {
    "!": "`!` para negar um padrao nao funciona no CODEOWNERS",
    "[": "`[ ]` para definir um intervalo de caracteres nao funciona no CODEOWNERS",
    "]": "`[ ]` para definir um intervalo de caracteres nao funciona no CODEOWNERS",
    "\\": "`\\` para escapar um caracter nao funciona no CODEOWNERS",
    "?": (
        "o `?` do gitignore nao esta documentado para o CODEOWNERS; "
        "resolve-lo aqui seria inventar a semantica"
    ),
}


@dataclass(frozen=True)
class Regra:
    """Uma linha de regra do `CODEOWNERS`."""

    linha: int
    padrao: str
    #: Os donos nao sao validados aqui: quem pode ser dono e governacao
    #: (KAM-137 e a lacuna L-19), nao um caminho. Guardam-se para a mensagem.
    donos: tuple[str, ...]


def regras(texto: str) -> list[Regra]:
    """As regras de um `CODEOWNERS`, pela ordem do ficheiro.

    Comentarios e linhas vazias saem. **A ordem preserva-se** porque em
    `CODEOWNERS` vence a **ultima** regra que casa, e o numero de linha e o que
    torna uma mensagem accionavel.
    """
    encontradas: list[Regra] = []
    for numero, bruta in enumerate(texto.splitlines(), start=1):
        linha = bruta.strip()
        if not linha or linha.startswith("#"):
            continue
        campos = linha.split()
        encontradas.append(
            Regra(linha=numero, padrao=campos[0], donos=tuple(campos[1:]))
        )
    return encontradas


def _traduzir(padrao: str) -> tuple[re.Pattern[str], bool]:
    """Traduz um padrao de `CODEOWNERS` para uma expressao regular.

    Devolve `(expressao, so_directorios)`. A expressao casa com um caminho
    relativo a raiz, em forma posix e sem barra inicial.

    Tres regras do gitignore que importam, e que o `[ -e ]` nao tem:

    - Uma barra **inicial** ancora na raiz; uma barra **no meio** tambem
      (`a/b` nunca casa com `x/a/b`). Sem nenhuma das duas, o padrao casa **em
      qualquer nivel**: `/docs/` e `docs/tecnica/` ancoram, `docs/` e `*.md`
      **nao** — a barra final nao ancora, so exige directorio, pelo que `docs/`
      casa com um `docs` a qualquer profundidade.
    - `*` nao atravessa `/`; `**` atravessa. `**/x` casa com `x` e com `a/b/x`.
    - Uma barra **final** exige directorio.
    """
    so_directorios = padrao.endswith("/")
    nucleo = padrao[:-1] if so_directorios else padrao

    if nucleo.startswith("/"):
        ancorado, nucleo = True, nucleo[1:]
    else:
        # Barra no meio ancora tambem. Ja se tirou a final, pelo que qualquer
        # barra que sobre esta no meio.
        ancorado = "/" in nucleo

    partes: list[str] = []
    indice, fim = 0, len(nucleo)
    while indice < fim:
        caracter = nucleo[indice]
        if caracter == "*":
            seguinte = indice
            while seguinte < fim and nucleo[seguinte] == "*":
                seguinte += 1
            if seguinte - indice >= 2:
                if seguinte < fim and nucleo[seguinte] == "/":
                    # `**/` vale zero ou mais segmentos, para que `**/x` case
                    # com `x` na raiz e nao so com `a/x`.
                    partes.append("(?:[^/]+/)*")
                    indice = seguinte + 1
                else:
                    partes.append(".*")
                    indice = seguinte
            else:
                partes.append("[^/]*")
                indice += 1
        elif caracter == "/":
            partes.append("/")
            indice += 1
        else:
            partes.append(re.escape(caracter))
            indice += 1

    corpo = "".join(partes)
    if not ancorado:
        corpo = "(?:[^/]+/)*" + corpo
    return re.compile("^" + corpo + "$"), so_directorios


def arvore(caminhos: list[str]) -> tuple[frozenset[str], frozenset[str]]:
    """Separa uma lista de ficheiros em `(ficheiros, directorios)`.

    Os directorios derivam-se dos ficheiros, e e isso que se quer: o git nao
    segue directorios, e um directorio sem nenhum ficheiro seguido nao atribui
    dono a nada. Precisam de existir em separado porque uma barra final exige
    directorio — sem a distincao, um **ficheiro** chamado `tecnica` daria por
    resolvida a regra `/tecnica/`.
    """
    ficheiros = frozenset(caminhos)
    directorios: set[str] = set()
    for caminho in ficheiros:
        partes = caminho.split("/")
        for corte in range(1, len(partes)):
            directorios.add("/".join(partes[:corte]))
    return ficheiros, frozenset(directorios)


def resolve(padrao: str, ficheiros: frozenset[str], directorios: frozenset[str]) -> bool:
    """`True` se o padrao casar com algum ficheiro ou directorio da arvore.

    Levanta `ValueError` se o padrao usar uma construcao nao suportada — quem
    chama tem de decidir o que dizer, e `verificar` di-lo pelo nome.
    """
    for caracter, razao in NAO_SUPORTADOS.items():
        if caracter in padrao:
            raise ValueError(razao)
    expressao, so_directorios = _traduzir(padrao)
    alvos = directorios if so_directorios else (ficheiros | directorios)
    return any(expressao.match(alvo) for alvo in alvos)


def verificar(texto: str, caminhos: list[str]) -> list[str]:
    """Os desvios de um `CODEOWNERS` face a uma arvore. Lista vazia = conforme.

    `caminhos` sao os ficheiros da arvore, relativos a raiz e em forma posix.
    Recebe-se a lista em vez de a ir buscar para que as *fixtures* possam ser
    varridas como arvores independentes, sem terem de ser repositorios git —
    a mesma razao pela qual `check_dependencies` recebe o `blocklist_path`.

    O padrao `*` **nao e excepcao**: sob a semantica de *glob* casa com todos os
    ficheiros e resolve por si. Excepciona-lo era necessario ao `[ -e "*" ]`, que
    e sempre falso, e seria agora uma dispensa a procura de um problema — num
    repositorio vazio o `*` nao atribui dono a nada, e e verdade que nao atribui.
    """
    ficheiros, directorios = arvore(caminhos)
    problemas: list[str] = []
    for regra in regras(texto):
        try:
            casou = resolve(regra.padrao, ficheiros, directorios)
        except ValueError as excepcao:
            problemas.append(
                f"CODEOWNERS:{regra.linha}: {regra.padrao!r} usa uma construcao "
                f"que o GitHub nao suporta — {excepcao}.\n"
                "    Uma linha de sintaxe invalida e **ignorada** pelo GitHub, "
                "e a area fica sem dono em silencio."
            )
            continue
        if not casou:
            problemas.append(
                f"CODEOWNERS:{regra.linha}: {regra.padrao!r} nao casa com nenhum "
                "ficheiro seguido pelo git.\n"
                "    O GitHub **nao recusa** uma regra assim: ignora-a, e a area "
                "que ela devia cobrir fica sem dono, em silencio.\n"
                f"    Donos que a regra atribuia: {' '.join(regra.donos) or '(nenhum)'}"
            )
    return problemas


def ficheiros_do_git(raiz: Path) -> list[str]:
    """Os ficheiros seguidos pelo git, relativos a `raiz`.

    Levanta `OSError` se o git nao responder. **Nao ha recurso ao disco**: um
    `os.walk` em vez do git varreria os `.claude/worktrees/*` e, pior, daria por
    resolvida uma regra que aponta para uma pasta sem nada seguido. Um gate que
    cai para uma medicao diferente quando a primeira falha mede outra coisa sem o
    dizer.
    """
    try:
        resultado = subprocess.run(
            ["git", "ls-files", "-z"],
            cwd=raiz,
            capture_output=True,
            check=True,
        )
    except (OSError, subprocess.CalledProcessError) as excepcao:
        raise OSError(
            f"nao foi possivel listar os ficheiros do git em {raiz}: {excepcao}"
        ) from excepcao
    return sorted(
        bruto
        for bruto in resultado.stdout.decode("utf-8", errors="replace").split("\0")
        if bruto
    )


def check(raiz: Path, caminhos: list[str] | None = None) -> list[str]:
    """Verifica o `CODEOWNERS` de `raiz`. Lista vazia = conforme.

    Se o ficheiro nao existir, devolve lista vazia: a sua ausencia e ja acusada
    por `structure.REQUIRED_FILES`, e acusa-la duas vezes nao acrescenta nada.
    """
    ficheiro = raiz / "CODEOWNERS"
    if not ficheiro.is_file():
        return []
    if caminhos is None:
        caminhos = ficheiros_do_git(raiz)
    # `utf-8-sig`: com um BOM, a primeira linha deixava de comecar por `#`,
    # passava a contar como regra e dava um achado falso — um gate vermelho com
    # uma mensagem que ninguem decifrava.
    return verificar(ficheiro.read_text(encoding="utf-8-sig"), caminhos)
