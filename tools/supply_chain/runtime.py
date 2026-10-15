"""Sem instalacao em runtime, e so a partir do lockfile (KAM-067, criterio 4).

Quatro regras:

* `instalacao-em-runtime` — um ponto de arranque (`CMD`, `ENTRYPOINT`,
  `HEALTHCHECK`, `command:`/`entrypoint:`/`test:` de um compose em qualquer
  profundidade, os `scripts` de arranque de um `package.json`, e os *scripts*
  que qualquer destes chame, em cadeia) nao instala nada. O que o contentor
  corre foi construido e revisto; um `pip install` no arranque traz codigo que
  ninguem viu, a hora a que ninguem esta a olhar.
* `arranque-nao-verificavel` — um ponto de arranque que executa um ficheiro que
  nao se encontra no repositorio. O silencio nao conta como conforme.
* `instalacao-fora-do-lockfile` — uma instalacao **de build** (num `RUN`, numa
  receita do `Makefile`, num passo de workflow) vem do lockfile: `pip` com
  `--require-hashes`, `pnpm install` com `--frozen-lockfile` e
  `--ignore-scripts`, `npm ci` com `--ignore-scripts`. `npm install`, `pnpm
  add` e `pnpm rebuild` resolvem de novo ou correm os *scripts*, e nao servem.
* `fs-so-de-leitura` — cada servico de um compose corre com `read_only: true`.

**Como se reconhece uma instalacao.** Nao por um padrao ancorado no inicio da
linha: a primeira versao fazia-o, e `pip --no-cache-dir install`, `/usr/bin/pip
install`, `python -u -m pip install`, `if x; then pip install; fi` e `timeout 60
pip install` passavam todas. O comando e partido em palavras, retiram-se os
involucros e as palavras de controlo, compara-se o **nome-base** do programa e
procura-se o subcomando em qualquer posicao.
"""

from __future__ import annotations

import json
import re
import shlex
from pathlib import Path

from . import arvore_yaml, compose as compose_mod, dockerfile
from .base import Achado, ler_texto, percorrer, relativo

_SEPARADORES = re.compile(r"&&|\|\||[;|&\n]|\$\(|`")
#: `sh -c`, `bash -lc`, `sh -e -c`, `/bin/sh -c`: quem corre o que vem a seguir.
_INVOLUCRO = re.compile(
    r"(?:^|(?<=[\s\"'(;&|]))(?:\S*/)?(?:ba|da|z|a|k)?sh"
    r"(?:\s+[-+][A-Za-z]+(?:\s+(?:pipefail|errexit|nounset|xtrace|posix))?)*?\s+-[A-Za-z]*c\s+"
)
_ATRIBUICAO = re.compile(r"^[A-Za-z_][A-Za-z0-9_]*=")

#: Palavras que vem antes do comando e nao sao o comando.
_ANTES_DO_COMANDO = frozenset(
    {
        "if", "then", "else", "elif", "fi", "do", "done", "while", "until", "!", "{", "}",
        "time", "exec", "command", "builtin", "nohup", "xargs", "sudo", "doas", "env",
        "corepack", "nice", "ionice", "setsid", "stdbuf", "timeout", "tini", "dumb-init",
        "--", "eval",
    }
)
#: Involucros que levam um argumento posicional antes do comando (`gosu node npm i`).
_COM_UM_ARGUMENTO = frozenset({"gosu", "su-exec", "setpriv", "chroot", "runuser"})
#: Opcoes dos involucros que levam valor (`sudo -u node`, `timeout -s KILL`).
_OPCOES_COM_VALOR_DE_INVOLUCRO = frozenset({"-u", "-g", "-s", "-k", "-n", "-I", "-P", "-L", "-c"})

#: Opcoes globais que levam valor, por ferramenta: o que vem a seguir nao e o subcomando.
_OPCOES_COM_VALOR = frozenset(
    {
        "--prefix", "-C", "--dir", "--cwd", "--cache", "--cache-dir", "--userconfig",
        "--registry", "-w", "--workspace", "--filter", "-F", "--python", "--proxy",
        "--index-url", "-i", "--log", "--config", "--config-file", "--directory",
    }
)

_SUBCOMANDOS = {
    "npm": frozenset(
        {
            "i", "in", "ins", "inst", "insta", "instal", "isnt", "isnta", "isntal", "isntall",
            "install", "add", "ci", "clean-install", "ic", "install-clean", "isntall-clean",
            "it", "install-test", "cit", "install-ci-test", "update", "up", "upgrade",
            "exec", "x", "rebuild", "rb", "link", "ln",
        }
    ),
    "pnpm": frozenset(
        {"i", "install", "add", "update", "up", "upgrade", "dlx", "rebuild", "rb", "import", "fetch", "link"}
    ),
    "yarn": frozenset({"install", "add", "up", "upgrade", "dlx", "link"}),
    "bun": frozenset({"i", "install", "add", "update", "x", "link"}),
    "poetry": frozenset({"install", "add", "update", "sync"}),
    "pipx": frozenset({"install", "run", "inject", "upgrade"}),
    "uv": frozenset({"sync", "add", "run", "tool", "pip"}),
}
_SEMPRE_INSTALAM = {"npx": "npm", "pnpx": "pnpm", "bunx": "bun", "uvx": "uv"}
_PIP = re.compile(r"^pip[0-9.]*$")
_PYTHON = re.compile(r"^(?:python[0-9.]*|pypy[0-9.]*)$")


def _forma_exec(argumentos: str) -> str:
    """`["sh", "-c", "a && b"]` -> `sh -c 'a && b'`. O resto fica como esta."""
    texto = argumentos.strip()
    if texto.startswith("["):
        try:
            partes = json.loads(texto)
        except json.JSONDecodeError:
            return texto
        if isinstance(partes, list):
            return shlex.join(str(p) for p in partes)
    return texto


def _palavras(segmento: str) -> list[str]:
    try:
        return shlex.split(segmento, posix=True)
    except ValueError:
        return segmento.replace('"', " ").replace("'", " ").split()


def _nome_base(palavra: str) -> str:
    """`/usr/local/bin/pip`, `$(VENV)/bin/pip` e `.venv/bin/pip` sao `pip`."""
    return re.split(r"[/\\]", palavra.strip("\"'"))[-1].lower()


def _sem_involucros(palavras: list[str]) -> list[str]:
    """Retira o que vem antes do comando: controlo, `sudo -H`, `timeout 300`, `A=1`."""
    palavras = list(palavras)
    while palavras:
        cabeca = palavras[0].lstrip("@+").lstrip("(")
        base = _nome_base(cabeca) if cabeca else ""
        if not cabeca or _ATRIBUICAO.match(cabeca):
            palavras.pop(0)
            continue
        if cabeca != palavras[0]:
            palavras[0] = cabeca
            continue
        if base in _ANTES_DO_COMANDO or base in _COM_UM_ARGUMENTO:
            palavras.pop(0)
            while palavras and palavras[0].startswith("-") and palavras[0] != "--":
                opcao = palavras.pop(0)
                if opcao in _OPCOES_COM_VALOR_DE_INVOLUCRO and palavras:
                    palavras.pop(0)
            if base == "timeout" and palavras and re.fullmatch(r"[0-9.]+[smhd]?", palavras[0]):
                palavras.pop(0)
            if base in _COM_UM_ARGUMENTO and palavras:
                palavras.pop(0)
            continue
        break
    return palavras


def _subcomando(argumentos: list[str]) -> str | None:
    """A primeira palavra que nao e opcao nem valor de opcao."""
    indice = 0
    while indice < len(argumentos):
        palavra = argumentos[indice]
        if palavra in _OPCOES_COM_VALOR:
            indice += 2
            continue
        if palavra.startswith("-"):
            indice += 1
            continue
        return palavra
    return None


def _classificar(palavras: list[str]) -> str | None:
    """A ferramenta que instala, se estas palavras forem uma instalacao."""
    palavras = _sem_involucros(palavras)
    if not palavras:
        return None
    base = _nome_base(palavras[0])
    argumentos = palavras[1:]

    if base in _SEMPRE_INSTALAM:
        return _SEMPRE_INSTALAM[base]
    if _PIP.match(base):
        return "pip" if any(a in ("install", "download") for a in argumentos) else None
    if _PYTHON.match(base) or "python" in base:
        for indice, palavra in enumerate(argumentos):
            modulo = None
            if palavra == "-m" and indice + 1 < len(argumentos):
                modulo = argumentos[indice + 1]
            elif palavra.startswith("-m") and len(palavra) > 2:
                modulo = palavra[2:]
            if modulo is not None:
                if _PIP.match(modulo) and any(a in ("install", "download") for a in argumentos[indice:]):
                    return "pip"
                if modulo in ("ensurepip", "uv", "pipx", "poetry"):
                    return "pip"
                break
        return None
    if base == "yarn" and _subcomando(argumentos) is None:
        return "yarn"
    if base in _SUBCOMANDOS:
        sub = _subcomando(argumentos)
        if sub in _SUBCOMANDOS[base]:
            return base
    return None


def _segmentos(comando: str) -> list[str]:
    """Parte um comando de shell nos comandos que ele encadeia."""
    # `sh -c "pip install x && ..."`: retira-se o involucro **antes** de partir,
    # senao o `&&` la dentro separava o comando das aspas que o fecham.
    comando = _INVOLUCRO.sub(" ", comando)
    resultado: list[str] = []
    for segmento in _SEPARADORES.split(comando):
        limpo = segmento.strip().strip("\"'(){}").strip()
        if limpo:
            resultado.append(limpo)
    return resultado


def instaladores_em(comando: str) -> list[tuple[str, str]]:
    """Os comandos de instalacao dentro de `comando`: [(ferramenta, segmento)]."""
    achados: list[tuple[str, str]] = []
    for segmento in _segmentos(comando):
        ferramenta = _classificar(_palavras(segmento))
        if ferramenta:
            achados.append((ferramenta, segmento))
    return achados


def _falha_de_lockfile(ferramenta: str, segmento: str) -> str | None:
    """Porque e que esta instalacao de build nao vem do lockfile, ou `None`."""
    palavras = _sem_involucros(_palavras(segmento))
    sub = _subcomando(palavras[1:]) or ""
    if ferramenta == "pip":
        if "--require-hashes" not in palavras:
            return "`pip install` sem `--require-hashes`"
        return None
    if ferramenta == "pnpm" and sub in ("i", "install"):
        faltam = [f for f in ("--frozen-lockfile", "--ignore-scripts") if f not in palavras]
        if faltam:
            return f"`pnpm install` sem {' nem '.join(f'`{f}`' for f in faltam)}"
        return None
    if ferramenta == "npm" and sub in ("ci", "clean-install"):
        if "--ignore-scripts" not in palavras:
            return "`npm ci` sem `--ignore-scripts`"
        return None
    if sub in ("rebuild", "rb"):
        return f"`{ferramenta} {sub}` corre os scripts de instalacao que `--ignore-scripts` proibe"
    return (
        f"`{(_nome_base(palavras[0]) + ' ' + sub).strip()}` nao e uma instalacao a "
        "partir de lockfile com hash"
    )


# ------------------------------------------------------ pontos de arranque

_NOME_DE_ARRANQUE = re.compile(
    r"^(?:docker-)?(?:entrypoint|arranque|start|startup|run|boot|init)[\w.-]*?(?:\.(?:sh|bash))?$"
)
_SCRIPTS_DE_ARRANQUE_NPM = ("start", "prestart", "poststart", "serve", "preserve")
_SHELL = (".sh", ".bash")
#: Pastas do sistema: um executavel daqui vem da imagem, nao do repositorio.
_DO_SISTEMA = ("/usr/", "/bin/", "/sbin/", "/lib/", "/etc/", "/proc/", "/dev/")
_CORRE_SCRIPT = frozenset({".", "source", "sh", "bash", "dash", "ash", "zsh", "ksh"})
_GESTORES = frozenset({"npm", "pnpm", "yarn", "bun"})


class _Contexto:
    """O que se partilha ao seguir pontos de arranque numa execucao."""

    def __init__(self, raiz: Path) -> None:
        self.raiz = raiz
        self.por_nome: dict[str, list[Path]] = {}
        self.scripts_npm: dict[str, list[tuple[Path, str]]] = {}
        self.vistos: set[Path] = set()
        self.npm_vistos: set[tuple[Path, str]] = set()
        for caminho in percorrer(raiz):
            self.por_nome.setdefault(caminho.name, []).append(caminho)
            if caminho.name == "package.json":
                try:
                    dados = json.loads(ler_texto(caminho))
                except json.JSONDecodeError:
                    continue
                scripts = dados.get("scripts") if isinstance(dados, dict) else None
                if isinstance(scripts, dict):
                    for nome, corpo in scripts.items():
                        if isinstance(corpo, str):
                            self.scripts_npm.setdefault(nome, []).append((caminho, corpo))


def _e_shell(caminho: Path) -> bool:
    if caminho.suffix in _SHELL:
        return True
    if caminho.suffix:
        return False
    try:
        primeira = ler_texto(caminho).split("\n", 1)[0]
    except OSError:
        return False
    return primeira.startswith("#!") and "sh" in primeira


def _linhas_de_script(texto: str) -> list[tuple[int, str]]:
    """Linhas logicas de um *script* de shell, sem comentarios."""
    linhas: list[tuple[int, str]] = []
    acumulado, inicio = "", 0
    for numero, linha in enumerate(texto.split("\n"), start=1):
        limpa = linha.strip()
        if not acumulado:
            if not limpa or limpa.startswith("#"):
                continue
            inicio = numero
        if limpa.endswith("\\"):
            acumulado += limpa[:-1] + " "
            continue
        linhas.append((inicio, acumulado + limpa))
        acumulado = ""
    if acumulado:
        linhas.append((inicio, acumulado))
    return linhas


def _verificar_script(caminho: Path, contexto: _Contexto, de_onde: str) -> list[Achado]:
    chave = caminho.resolve()
    if chave in contexto.vistos or not _e_shell(caminho):
        return []
    contexto.vistos.add(chave)
    achados: list[Achado] = []
    ficheiro = relativo(caminho, contexto.raiz)
    for numero, linha in _linhas_de_script(ler_texto(caminho)):
        achados += _arranque(linha, ficheiro, numero, f"script de arranque ({de_onde})", contexto, exigir=False)
    return achados


def _arranque(comando: str, ficheiro: str, linha: int, origem: str, contexto: _Contexto,
              exigir: bool = True) -> list[Achado]:
    """Verifica um comando de arranque, e segue o que ele executa.

    `exigir`: o executavel do comando, se for um ficheiro, tem de se encontrar.
    Dentro de um *script* nao se exige — as linhas de um *script* chamam
    programas do sistema —, excepto para o que e claramente outro *script*.
    """
    achados: list[Achado] = []
    for posicao, segmento in enumerate(_segmentos(comando)):
        palavras = _sem_involucros(_palavras(segmento))
        if not palavras:
            continue
        # So o primeiro comando e «o executavel» do ponto de arranque. Os
        # seguintes podem ser pedacos de outra linguagem (o JavaScript de um
        # `node -e`), e exigir-lhes um ficheiro dava falsos vermelhos.
        primeiro = posicao == 0
        ferramenta = _classificar(palavras)
        if ferramenta:
            achados.append(
                Achado(
                    "instalacao-em-runtime", ficheiro, linha,
                    f"{origem}: `{segmento[:70]}` instala no arranque. O que o contentor "
                    "corre foi construido e revisto: instale na construcao, a partir do lockfile.",
                )
            )
            continue

        base = _nome_base(palavras[0])
        # `pnpm run arranque`, `npm start`, `yarn arranque`: o comando esta no package.json.
        if base in _GESTORES:
            sub = _subcomando(palavras[1:])
            if sub in ("run", "run-script") and len(palavras) > 2:
                resto = palavras[palavras.index(sub) + 1 :]
                sub = _subcomando(resto)
            for manifesto, corpo in contexto.scripts_npm.get(sub or "", []):
                if (manifesto, sub) in contexto.npm_vistos:
                    continue
                contexto.npm_vistos.add((manifesto, sub))
                achados += _arranque(
                    corpo, relativo(manifesto, contexto.raiz), 0,
                    f"scripts.{sub} (chamado por {ficheiro}:{linha})", contexto, exigir=False,
                )
            continue

        # O executavel, e o que um interpretador de shell recebe para correr.
        candidatos: list[tuple[str, bool]] = []
        if "/" in palavras[0] or palavras[0].endswith(_SHELL):
            candidatos.append((palavras[0], primeiro and (exigir or palavras[0].endswith(_SHELL))))
        if base in _CORRE_SCRIPT:
            alvo = _subcomando(palavras[1:])
            if alvo:
                candidatos.append((alvo, primeiro and alvo.endswith(_SHELL)))
        for palavra in palavras[1:]:
            if palavra.endswith(_SHELL):
                candidatos.append((palavra, False))

        for palavra, obrigatorio in candidatos:
            if "$" in palavra:
                continue
            encontrados = contexto.por_nome.get(_nome_base(palavra) if palavra else "", [])
            encontrados = [c for c in encontrados if c.name == Path(palavra).name]
            if encontrados:
                for caminho in encontrados:
                    achados += _verificar_script(caminho, contexto, f"chamado por {ficheiro}:{linha}")
            elif obrigatorio and not palavra.startswith(_DO_SISTEMA):
                achados.append(
                    Achado(
                        "arranque-nao-verificavel", ficheiro, linha,
                        f"{origem}: `{palavra}` nao se encontra no repositorio. Um ponto de "
                        "arranque que executa um ficheiro que nao se consegue ler nao conta "
                        "como conforme.",
                    )
                )
    return achados


def _comando_do_compose(documento, no) -> str:
    no = documento.resolver(no)
    if no.filhos:
        return shlex.join(documento.itens(no))
    if no.bloco:
        return no.valor
    return _forma_exec(no.texto())


def _nos_de_comando(documento, no, _profundidade: int = 0):
    """Todos os `command:`, `entrypoint:` e `test:` sob um servico, a qualquer profundidade.

    Apanha o `healthcheck.test` e os ganchos `post_start`/`pre_stop`, e o que o
    compose vier a acrescentar com a mesma forma.
    """
    if _profundidade > 12:
        return
    no = documento.resolver(no)
    for filho in no.filhos:
        if filho.chave == "<<":
            for alvo in documento._alvos_de_merge(filho):
                yield from _nos_de_comando(documento, alvo, _profundidade + 1)
            continue
        if filho.chave in ("command", "entrypoint", "test"):
            yield filho
        elif filho.filhos or filho.valor.strip().startswith("*"):
            yield from _nos_de_comando(documento, filho, _profundidade + 1)


def _de_build(comando: str, ficheiro: str, linha: int, origem: str, contagem: dict) -> list[Achado]:
    achados: list[Achado] = []
    for ferramenta, segmento in instaladores_em(comando):
        contagem["instalacoes_de_build"] += 1
        falha = _falha_de_lockfile(ferramenta, segmento)
        if falha:
            achados.append(
                Achado(
                    "instalacao-fora-do-lockfile", ficheiro, linha,
                    f"{origem}: {falha}. Uma instalacao que resolve na construcao traz o "
                    "que estiver publicado nesse dia.",
                )
            )
    return achados


def verificar(raiz: Path) -> tuple[list[Achado], dict]:
    achados: list[Achado] = []
    contexto = _Contexto(raiz)
    contagem = {"dockerfiles": 0, "servicos": 0, "scripts": 0, "instalacoes_de_build": 0}

    for caminho in percorrer(raiz):
        ficheiro = relativo(caminho, raiz)
        nome = caminho.name

        if dockerfile.e_dockerfile(caminho):
            contagem["dockerfiles"] += 1
            try:
                instrucoes = dockerfile.instrucoes(ler_texto(caminho))
            except dockerfile.DockerfileIlegivel:
                continue  # ja e achado em `imagens`
            for instrucao in instrucoes:
                if instrucao.nome in ("CMD", "ENTRYPOINT", "HEALTHCHECK"):
                    comando = _forma_exec(re.sub(r"^(?:--\S+\s+)*(?:CMD\s+)?", "", instrucao.argumentos))
                    achados += _arranque(comando, ficheiro, instrucao.linha, instrucao.nome, contexto)
                elif instrucao.nome == "RUN":
                    comando = _forma_exec(re.sub(r"^(?:--\S+\s+)*", "", instrucao.argumentos))
                    achados += _de_build(comando, ficheiro, instrucao.linha, "RUN", contagem)
            continue

        if nome in ("Makefile", "makefile", "GNUmakefile") or nome.endswith(".mk"):
            for numero, linha in enumerate(ler_texto(caminho).split("\n"), start=1):
                if not linha.startswith("\t"):
                    continue
                receita = linha.strip().lstrip("@-+").strip()
                if receita.startswith(("#", "echo ", "printf ")):
                    continue
                achados += _de_build(receita.rstrip("\\").strip(), ficheiro, numero, "receita", contagem)
            continue

        if nome == "package.json":
            for chave in _SCRIPTS_DE_ARRANQUE_NPM:
                for manifesto, corpo in contexto.scripts_npm.get(chave, []):
                    if manifesto != caminho or (manifesto, chave) in contexto.npm_vistos:
                        continue
                    contexto.npm_vistos.add((manifesto, chave))
                    achados += _arranque(corpo, ficheiro, 0, f"scripts.{chave}", contexto, exigir=False)
            continue

        if (
            _NOME_DE_ARRANQUE.match(nome)
            and "tests" not in caminho.relative_to(raiz).parts
            and _e_shell(caminho)
        ):
            achados += _verificar_script(caminho, contexto, "nome de script de arranque")
            continue

        partes = caminho.relative_to(raiz).parts
        if len(partes) >= 3 and partes[0] == ".github" and caminho.suffix in (".yml", ".yaml"):
            try:
                documento = arvore_yaml.ler(ler_texto(caminho))
            except arvore_yaml.YamlIlegivel:
                continue  # ja e achado em `imagens`
            for no in documento.todos():
                if no.chave != "run":
                    continue
                for numero, linha in enumerate(no.valor.split("\n")):
                    achados += _de_build(linha.strip(), ficheiro, no.linha + numero, "run", contagem)

    lidos, _ilegiveis = compose_mod.ler_todos(raiz)
    for ficheiro_compose in lidos:
        documento = ficheiro_compose.documento
        for nome, (no, chaves) in ficheiro_compose.servicos.items():
            contagem["servicos"] += 1
            if "extends" in chaves:
                achados.append(
                    Achado(
                        "fs-so-de-leitura", ficheiro_compose.ficheiro, chaves["extends"].linha,
                        f"o servico `{nome}` usa `extends:`, que este leitor nao segue; "
                        "escreva as chaves no proprio ficheiro (ancoras e `<<:` servem).",
                    )
                )
            so_leitura = (
                documento.resolver(chaves["read_only"]).texto().lower()
                if "read_only" in chaves else ""
            )
            if so_leitura != "true":
                achados.append(
                    Achado(
                        "fs-so-de-leitura", ficheiro_compose.ficheiro, no.linha,
                        f"o servico `{nome}` nao tem `read_only: true`. O que precisa de "
                        "escrever declara-se em `volumes:` ou `tmpfs:`.",
                    )
                )
            try:
                nos = list(_nos_de_comando(documento, no))
            except arvore_yaml.YamlIlegivel:
                continue  # ja e achado em `imagens`
            for no_comando in nos:
                comando = _comando_do_compose(documento, no_comando)
                if no_comando.chave == "test":
                    comando = re.sub(r"^'?(?:CMD-SHELL|CMD|NONE)'?\s+", "", comando)
                achados += _arranque(
                    comando, ficheiro_compose.ficheiro, no_comando.linha,
                    f"services.{nome}.{no_comando.chave}", contexto,
                )
    contagem["scripts"] = len(contexto.vistos)
    return achados, contagem
