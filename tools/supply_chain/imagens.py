"""Imagens por digest, e o inventario que as regista (KAM-067, criterios 1 e 2).

Tres perguntas, por esta ordem:

1. **Onde se referencia uma imagem?** Compose (`image:` e os `build.args` que
   alimentam um `FROM`), `Dockerfile` (`FROM`, `COPY --from`, `--mount=from`, a
   directiva `# syntax=`), workflows e accoes do GitHub (`image:`, `container:`,
   `uses: docker://`), ficheiros de ambiente que preenchem uma variavel de
   imagem do compose, e as constantes Python que o inventario declara.
2. **Esta fixada por digest?** `@sha256:` com 64 hexadecimais. Uma etiqueta e um
   nome que o registo pode voltar a apontar para outra coisa.
3. **Consta do inventario?** `ci/supply-chain/imagens.yaml` regista nome,
   etiqueta, digest, de onde e quando se leu, e o estado da assinatura cosign.
   Um digest que ninguem registou e um digest que ninguem leu da fonte.

O que **nao** se consegue ver daqui, e fica dito: um `docker build --build-arg`
ou um `KAMBA_QUEUE_IMAGE=...` escritos a mao na linha de comandos.
"""

from __future__ import annotations

import ast
import dataclasses
import datetime as _datetime
import re
from pathlib import Path

from kamba_yaml import YamlSubsetError, exigir_chaves, load_file

from . import arvore_yaml, compose as compose_mod, dockerfile
from .base import Achado, ConfiguracaoInvalida, ler_texto, percorrer, relativo

INVENTARIO = "ci/supply-chain/imagens.yaml"

COSIGN_VERIFICAR = "verificar"
COSIGN_NA = "n/a"
COSIGN_POR_APURAR = "por_apurar"
ESTADOS_COSIGN = (COSIGN_VERIFICAR, COSIGN_NA, COSIGN_POR_APURAR)

#: Imagens com assinatura cosign **publicada**: aqui `n/a` e `por_apurar` nao
#: sao estados aceitaveis. Vive no codigo e nao no YAML, para que apagar uma
#: linha de configuracao nao desligue a exigencia.
#:
#: nome do projecto, procurado no repositorio da imagem por fronteira -> fonte
ASSINATURA_PUBLICADA = {
    "litellm": (
        "docs/tecnica/evidencia/E4_Stack_Licencas.md §2.7 (CONFIRMADO): a partir "
        "da v1.83.0 as imagens sao assinadas com cosign"
    ),
}

_DIGEST = re.compile(r"^sha256:[0-9a-f]{64}$")
_NOME = re.compile(r"^[a-z0-9][a-z0-9._-]*(?::[0-9]+)?(?:/[a-z0-9][a-z0-9._-]*)*$")
_ETIQUETA = re.compile(r"^[A-Za-z0-9_][A-Za-z0-9_.-]{0,127}$")


@dataclasses.dataclass(frozen=True)
class Referencia:
    ficheiro: str
    linha: int
    #: De que construcao veio (`image:`, `FROM`, `ARG NODE_IMAGE`, ...).
    origem: str
    #: A referencia resolvida, ou `None` quando depende de algo que nao se le.
    valor: str | None
    #: O texto tal como esta escrito, para a mensagem.
    bruto: str


@dataclasses.dataclass(frozen=True)
class Partes:
    nome: str
    etiqueta: str | None
    digest: str | None


def decompor(referencia: str) -> Partes | None:
    """`registo/caminho:etiqueta@sha256:...` em partes. `None` se for ilegivel."""
    texto = referencia.strip()
    corpo, arroba, digest = texto.partition("@")
    if arroba and not _DIGEST.match(digest):
        return None
    ultimo = corpo.rsplit("/", 1)[-1]
    if ":" in ultimo:
        nome, etiqueta = corpo.rsplit(":", 1)
        if not _ETIQUETA.match(etiqueta):
            return None
    else:
        nome, etiqueta = corpo, None
    nome = nome.lower()
    if not _NOME.match(nome):
        return None
    return Partes(nome, etiqueta, digest or None)


def nome_canonico(nome: str) -> str:
    """`docker.io/library/node` e `node` sao a mesma imagem."""
    nome = nome.lower()
    for prefixo in ("docker.io/", "index.docker.io/", "registry-1.docker.io/"):
        if nome.startswith(prefixo):
            nome = nome[len(prefixo) :]
    if nome.startswith("library/"):
        nome = nome[len("library/") :]
    return nome


# ---------------------------------------------------------------- inventario


@dataclasses.dataclass(frozen=True)
class Entrada:
    nome: str
    etiqueta: str
    digest: str
    lido_em: str
    lido_de: str
    componentes: tuple[str, ...]
    cosign: str
    cosign_razao: str
    cosign_identidade: str
    cosign_emissor: str

    @property
    def referencia(self) -> str:
        return f"{self.nome}:{self.etiqueta}@{self.digest}"


@dataclasses.dataclass(frozen=True)
class Inventario:
    entradas: tuple[Entrada, ...]
    #: ficheiro -> nome da constante que guarda a referencia (ou `None` quando o
    #: ficheiro chama o Docker sem nomear imagem nenhuma).
    fontes: dict[str, str | None]

    def procurar(self, nome: str, digest: str) -> Entrada | None:
        for entrada in self.entradas:
            if nome_canonico(entrada.nome) == nome_canonico(nome) and entrada.digest == digest:
                return entrada
        return None


_CHAVES_ENTRADA = {
    "nome", "etiqueta", "digest", "lido_em", "lido_de", "componentes",
    "cosign", "cosign_razao", "cosign_identidade", "cosign_emissor",
}
_CHAVES_FONTE = {"ficheiro", "constante", "sem_imagem"}
_CHAVES_TOPO = {"version", "imagens", "fontes_adicionais"}


def _so_chaves(mapa: dict, aceites: set[str], onde: str) -> None:
    """A recusa de chaves desconhecidas, com a excepcao deste modulo.

    O corpo era local e passou a chamar o `exigir_chaves` partilhado no
    KAM-134. Eram **quatro** implementacoes da mesma ideia no repositorio — esta,
    a do `licencas.py` ao lado, a do `canon_lint` e a que o ticket mandava
    escrever de novo —, e a diferenca entre elas era a mensagem. A partilhada
    diz tambem o **conjunto aceite**, que nenhuma das locais dizia e que o
    criterio do ticket exige.
    """
    exigir_chaves(mapa, aceites, onde, erro=ConfiguracaoInvalida)


def ler_inventario(raiz: Path, hoje: _datetime.date | None = None) -> Inventario:
    caminho = raiz / INVENTARIO
    if not caminho.is_file():
        raise ConfiguracaoInvalida(f"ficheiro em falta: {INVENTARIO}")
    try:
        dados = load_file(caminho)
    except YamlSubsetError as excepcao:
        raise ConfiguracaoInvalida(str(excepcao)) from excepcao
    _so_chaves(dados, _CHAVES_TOPO, INVENTARIO)
    if dados.get("version") != 1:
        raise ConfiguracaoInvalida(f"{INVENTARIO}: 'version' tem de ser 1")
    brutas = dados.get("imagens")
    if not isinstance(brutas, list):
        raise ConfiguracaoInvalida(
            f"{INVENTARIO}: `imagens` tem de ser uma lista (use `[]` para nenhuma)"
        )
    hoje = hoje or _datetime.date.today()

    entradas: list[Entrada] = []
    vistas: set[tuple[str, str]] = set()
    for indice, bruta in enumerate(brutas, start=1):
        onde = f"{INVENTARIO}: imagem {indice}"
        if not isinstance(bruta, dict):
            raise ConfiguracaoInvalida(f"{onde}: esperava um mapa")
        _so_chaves(bruta, _CHAVES_ENTRADA, onde)
        faltam = [
            c for c in ("nome", "etiqueta", "digest", "lido_em", "lido_de", "componentes", "cosign")
            if bruta.get(c) in (None, "", [])
        ]
        if faltam:
            raise ConfiguracaoInvalida(f"{onde}: campos em falta: {', '.join(faltam)}")
        nome, etiqueta, digest = str(bruta["nome"]), str(bruta["etiqueta"]), str(bruta["digest"])
        onde = f"{INVENTARIO}: {nome}"
        if not _NOME.match(nome):
            raise ConfiguracaoInvalida(f"{onde}: nome de imagem invalido")
        if not _ETIQUETA.match(etiqueta):
            raise ConfiguracaoInvalida(f"{onde}: etiqueta invalida ({etiqueta!r})")
        if not _DIGEST.match(digest):
            raise ConfiguracaoInvalida(
                f"{onde}: `digest` tem de ser `sha256:` seguido de 64 hexadecimais"
            )
        try:
            lido_em = _datetime.date.fromisoformat(str(bruta["lido_em"]))
        except ValueError as excepcao:
            raise ConfiguracaoInvalida(f"{onde}: `lido_em` tem de ser uma data ISO") from excepcao
        if lido_em > hoje:
            raise ConfiguracaoInvalida(f"{onde}: `lido_em` esta no futuro ({lido_em})")
        componentes = bruta["componentes"]
        if not isinstance(componentes, list) or not all(isinstance(c, str) for c in componentes):
            raise ConfiguracaoInvalida(f"{onde}: `componentes` tem de ser uma lista de nomes")
        cosign = str(bruta["cosign"])
        if cosign not in ESTADOS_COSIGN:
            raise ConfiguracaoInvalida(
                f"{onde}: `cosign` tem de ser um de {', '.join(ESTADOS_COSIGN)} (lido {cosign!r})"
            )
        razao = str(bruta.get("cosign_razao") or "")
        identidade = str(bruta.get("cosign_identidade") or "")
        emissor = str(bruta.get("cosign_emissor") or "")
        if cosign == COSIGN_VERIFICAR:
            if not identidade or not emissor:
                raise ConfiguracaoInvalida(
                    f"{onde}: `cosign: verificar` exige `cosign_identidade` e "
                    "`cosign_emissor` — sem eles, qualquer assinatura valida de "
                    "qualquer pessoa passava"
                )
        elif len(razao) < 40:
            raise ConfiguracaoInvalida(
                f"{onde}: `cosign: {cosign}` exige `cosign_razao` com pelo menos 40 "
                "caracteres: a compensacao (digest, SBOM, varrimento) ou o que falta apurar"
            )
        chave = (nome_canonico(nome), digest)
        if chave in vistas:
            raise ConfiguracaoInvalida(f"{onde}: entrada repetida para o mesmo digest")
        vistas.add(chave)
        entradas.append(
            Entrada(
                nome=nome, etiqueta=etiqueta, digest=digest, lido_em=lido_em.isoformat(),
                lido_de=str(bruta["lido_de"]), componentes=tuple(componentes),
                cosign=cosign, cosign_razao=razao,
                cosign_identidade=identidade, cosign_emissor=emissor,
            )
        )

    fontes: dict[str, str | None] = {}
    for indice, bruta in enumerate(dados.get("fontes_adicionais") or [], start=1):
        onde = f"{INVENTARIO}: fonte adicional {indice}"
        if not isinstance(bruta, dict):
            raise ConfiguracaoInvalida(f"{onde}: esperava um mapa")
        _so_chaves(bruta, _CHAVES_FONTE, onde)
        ficheiro = str(bruta.get("ficheiro") or "")
        constante = bruta.get("constante")
        sem_imagem = bruta.get("sem_imagem")
        if not ficheiro or bool(constante) == bool(sem_imagem):
            raise ConfiguracaoInvalida(
                f"{onde}: exige `ficheiro` e **um** de `constante` (o nome da "
                "constante com a referencia) ou `sem_imagem` (a razao)"
            )
        if sem_imagem and len(str(sem_imagem)) < 40:
            raise ConfiguracaoInvalida(f"{onde}: `sem_imagem` exige uma razao de 40 caracteres")
        if ficheiro in fontes:
            raise ConfiguracaoInvalida(f"{onde}: ficheiro repetido ({ficheiro})")
        fontes[ficheiro] = str(constante) if constante else None
    return Inventario(tuple(entradas), fontes)


# ------------------------------------------------------------------- recolha


def _do_dockerfile(caminho: Path, raiz: Path) -> tuple[list[Referencia], set[str]]:
    """Referencias de um Dockerfile, e os nomes dos `ARG` que alimentam um `FROM`."""
    ficheiro = relativo(caminho, raiz)
    texto = ler_texto(caminho)
    referencias: list[Referencia] = []
    args: dict[str, tuple[str | None, int]] = {}
    args_de_from: set[str] = set()
    andares: set[str] = set()
    quantos_from = 0

    syntax = dockerfile.directiva_syntax(texto)
    if syntax:
        referencias.append(Referencia(ficheiro, syntax[1], "# syntax=", syntax[0], syntax[0]))

    def resolver(texto_imagem: str, linha: int, origem: str) -> None:
        usados: list[str] = []
        resolvido = True

        def trocar(correspondencia: re.Match) -> str:
            nonlocal resolvido
            nome = correspondencia.group("nome") or correspondencia.group("simples")
            usados.append(nome)
            operador = correspondencia.group("operador") or ""
            if nome in args and args[nome][0] is not None:
                return args[nome][0] or ""
            if operador in (":-", "-"):
                return correspondencia.group("resto") or ""
            resolvido = False
            return ""

        valor = compose_mod.INTERPOLACAO.sub(trocar, texto_imagem)
        args_de_from.update(usados)
        if not resolvido or "$" in valor or not valor:
            referencias.append(Referencia(ficheiro, linha, origem, None, texto_imagem))
            return
        if usados:
            # A linha que importa e a do `ARG`, que e onde se corrige.
            linha_do_arg = min((args[n][1] for n in usados if n in args), default=linha)
            referencias.append(
                Referencia(ficheiro, linha_do_arg, f"ARG {usados[0]} (usado em {origem})", valor, texto_imagem)
            )
            return
        referencias.append(Referencia(ficheiro, linha, origem, valor, texto_imagem))

    for instrucao in dockerfile.instrucoes(texto):
        if instrucao.nome == "ARG":
            for declaracao in instrucao.argumentos.split():
                nome, igual, valor = declaracao.partition("=")
                args[nome] = (valor.strip("\"'") if igual else None, instrucao.linha)
            continue

        if instrucao.nome == "FROM":
            partes = [p for p in instrucao.argumentos.split() if not p.startswith("--")]
            if len(partes) >= 3 and partes[-2].lower() == "as":
                andar = partes[-1].lower()
                partes = partes[:-2]
            else:
                andar = None
            if not partes:
                referencias.append(
                    Referencia(ficheiro, instrucao.linha, "FROM", None, instrucao.argumentos)
                )
            else:
                imagem = partes[0]
                if imagem.lower() != "scratch" and imagem.lower() not in andares:
                    resolver(imagem, instrucao.linha, "FROM")
            if andar:
                andares.add(andar)
            andares.add(str(quantos_from))
            quantos_from += 1
            continue

        if instrucao.nome in ("COPY", "RUN", "ADD"):
            padrao = r"--from=(\S+)" if instrucao.nome != "RUN" else r"--mount=\S*?\bfrom=([^,\s]+)"
            for origem_externa in re.findall(padrao, instrucao.argumentos):
                if origem_externa.lower() in andares:
                    continue
                resolver(origem_externa, instrucao.linha, f"{instrucao.nome} --from")
    return referencias, args_de_from


def _args_do_build(documento, no_build) -> dict[str, tuple[str, int]]:
    """`build.args`, em mapa ou em lista `- CHAVE=valor`."""
    args: dict[str, tuple[str, int]] = {}
    mapa = documento.mapa(no_build)
    if "args" not in mapa:
        return args
    no_args = documento.resolver(mapa["args"])
    if no_args.e_lista():
        for item in no_args.filhos:
            nome, igual, valor = documento.resolver(item).texto().partition("=")
            # `- NODE_IMAGE` sem valor herda o do ambiente de quem constroi.
            args[nome] = (valor if igual else "${" + nome + "}", item.linha)
    else:
        for nome, no in documento.mapa(no_args).items():
            args[nome] = (documento.resolver(no).texto(), no.linha)
    return args


def _do_compose(
    ficheiro_compose: compose_mod.Compose, raiz: Path, args_de_from: dict[str, set[str]]
) -> tuple[list[Referencia], set[str], list[Achado]]:
    referencias: list[Referencia] = []
    variaveis: set[str] = set()
    achados: list[Achado] = []
    documento = ficheiro_compose.documento
    ficheiro = ficheiro_compose.ficheiro

    def registar(texto: str, linha: int, origem: str) -> None:
        valor, usadas = compose_mod.resolver_interpolacao(texto)
        variaveis.update(usadas)
        referencias.append(Referencia(ficheiro, linha, origem, valor, texto))

    for nome, (_no, chaves) in ficheiro_compose.servicos.items():
        if "image" in chaves:
            no = documento.resolver(chaves["image"])
            registar(no.texto(), no.linha, f"services.{nome}.image")
        if "build" not in chaves:
            if "image" not in chaves:
                achados.append(
                    Achado(
                        "imagem-nao-resolvida", ficheiro, _no.linha,
                        f"o servico `{nome}` nao tem `image:` nem `build:`; nao se "
                        "consegue saber que imagem corre",
                    )
                )
            continue
        no_build = documento.resolver(chaves["build"])
        if not no_build.filhos:
            contexto, nome_dockerfile = no_build.texto() or ".", "Dockerfile"
        else:
            mapa_build = documento.mapa(no_build)
            for chave in ("dockerfile_inline", "additional_contexts"):
                if chave in mapa_build:
                    achados.append(
                        Achado(
                            "imagem-nao-resolvida", ficheiro, mapa_build[chave].linha,
                            f"o `build.{chave}` do servico `{nome}` nao e lido: traz "
                            "imagens de base que ficavam por verificar. Use um "
                            "Dockerfile em ficheiro.",
                        )
                    )
            contexto = documento.resolver(mapa_build["context"]).texto() if "context" in mapa_build else "."
            nome_dockerfile = (
                documento.resolver(mapa_build["dockerfile"]).texto()
                if "dockerfile" in mapa_build else "Dockerfile"
            )
        try:
            alvo = (ficheiro_compose.caminho.parent / contexto / nome_dockerfile).resolve()
            alvo_relativo = alvo.relative_to(raiz.resolve()).as_posix()
        except (OSError, ValueError):
            alvo_relativo = None
        if alvo_relativo is None or alvo_relativo not in args_de_from:
            achados.append(
                Achado(
                    "imagem-nao-resolvida", ficheiro, no_build.linha,
                    f"o `build:` do servico `{nome}` aponta para um Dockerfile que "
                    f"nao se encontra ({contexto}/{nome_dockerfile}); sem ele nao se "
                    "sabe que `args` trocam a imagem de base",
                )
            )
            continue
        if not no_build.filhos:
            continue
        for arg, (valor, linha) in _args_do_build(documento, no_build).items():
            if arg in args_de_from[alvo_relativo]:
                registar(valor, linha, f"services.{nome}.build.args.{arg}")
    return referencias, variaveis, achados


_FICHEIRO_ENV = re.compile(r"^(?:\.env(?:\..+)?|.+\.env)$")
_ATRIBUICAO_ENV = re.compile(r"^\s*(?:export\s+)?(?P<nome>[A-Za-z_][A-Za-z0-9_]*)=(?P<valor>.*)$")


def _dos_ficheiros_env(raiz: Path, variaveis: set[str]) -> list[Referencia]:
    """O `.env` **substitui** a omissao do compose: conta tanto como ela."""
    referencias: list[Referencia] = []
    if not variaveis:
        return referencias
    for caminho in percorrer(raiz):
        if not _FICHEIRO_ENV.match(caminho.name):
            continue
        for numero, linha in enumerate(ler_texto(caminho).split("\n"), start=1):
            if linha.lstrip().startswith("#"):
                continue
            atribuicao = _ATRIBUICAO_ENV.match(linha)
            if not atribuicao or atribuicao.group("nome") not in variaveis:
                continue
            valor = atribuicao.group("valor").strip().strip("\"'")
            if not valor:
                continue
            referencias.append(
                Referencia(
                    relativo(caminho, raiz), numero,
                    f"variavel {atribuicao.group('nome')}", valor, valor,
                )
            )
    return referencias


def _e_do_github(caminho: Path, raiz: Path) -> bool:
    partes = caminho.relative_to(raiz).parts
    return len(partes) >= 3 and partes[0] == ".github" and caminho.suffix in (".yml", ".yaml")


#: Uma chave `image` em qualquer YAML: manifestos de Kubernetes, valores de Helm,
#: definicoes de CI de outras plataformas.
_MENCIONA_IMAGE = re.compile(r"""(?:^|[\s{,-])["']?image["']?\s*:""")


def _do_yaml(caminho: Path, raiz: Path, do_github: bool) -> tuple[list[Referencia], list[Achado]]:
    """`image:` (e, no GitHub, `container:` e `uses: docker://`) em qualquer profundidade."""
    ficheiro = relativo(caminho, raiz)
    try:
        documento = arvore_yaml.ler(ler_texto(caminho))
    except arvore_yaml.YamlIlegivel as excepcao:
        return [], [Achado("ficheiro-ilegivel", ficheiro, 0, str(excepcao))]
    referencias: list[Referencia] = []
    for no in documento.todos():
        if no.chave is None or no.bloco:
            continue
        if no.filhos:
            continue
        texto = no.texto()
        if no.chave == "image" and texto.startswith("{"):
            # `image: {repository: x, tag: y}` (Helm): a referencia esta partida
            # em pedacos que nenhum digest fixa.
            referencias.append(Referencia(ficheiro, no.linha, "image:", None, texto))
            continue
        if not texto:
            continue
        if no.chave == "image" or (do_github and no.chave == "container"):
            valor = None if "${{" in texto or "{{" in texto else texto
        elif do_github and no.chave == "uses" and texto.startswith("docker://"):
            valor = None if "${{" in texto else texto[len("docker://") :]
        else:
            continue
        referencias.append(Referencia(ficheiro, no.linha, f"{no.chave}:", valor, texto))
    return referencias, []


def _da_constante(raiz: Path, ficheiro: str, constante: str) -> Referencia:
    caminho = raiz / ficheiro
    origem = f"constante {constante}"
    if not caminho.is_file():
        return Referencia(ficheiro, 0, origem, None, "(ficheiro em falta)")
    try:
        arvore = ast.parse(ler_texto(caminho))
    except SyntaxError:
        return Referencia(ficheiro, 0, origem, None, "(ficheiro que nao e Python valido)")
    for no in arvore.body:
        alvos = []
        if isinstance(no, ast.Assign):
            alvos, valor = no.targets, no.value
        elif isinstance(no, ast.AnnAssign) and no.value is not None:
            alvos, valor = [no.target], no.value
        if not any(isinstance(a, ast.Name) and a.id == constante for a in alvos):
            continue
        try:
            lido = ast.literal_eval(valor)
        except (ValueError, SyntaxError):
            lido = None
        if isinstance(lido, str):
            return Referencia(ficheiro, no.lineno, origem, lido, lido)
        return Referencia(ficheiro, no.lineno, origem, None, "(a constante nao e um literal de texto)")
    return Referencia(ficheiro, 0, origem, None, "(constante nao encontrada)")


#: Um ficheiro de codigo que chama um motor de contentores. Apanha
#: `["docker", ...]`, `docker run`, `docker container run`, `podman pull`...
_MOTOR = r"(?:docker|podman|nerdctl)"
_CHAMA_DOCKER = re.compile(
    rf"""["']{_MOTOR}["']|(?<![\w./-]){_MOTOR}\s+(?:container\s+|image\s+)?"""
    r"""(?:run|pull|create|compose|build|buildx)\b"""
)
_LANCA = re.compile(rf"\b{_MOTOR}\s+(?:container\s+|image\s+)?(?:run|pull|create)\b")
_SUFIXOS_DE_CODIGO = (".py", ".sh", ".bash", ".ts", ".js", ".mjs", ".cjs", ".mk")
_DIGEST_NA_LINHA = re.compile(r"@(sha256:[0-9a-f]{64})")


def _lancadores(raiz: Path, inventario: Inventario) -> list[Achado]:
    """Codigo que lanca contentores tem de dizer com que imagem.

    Um `subprocess.run(["docker", "run", imagem])` nao e um manifesto, e nenhum
    leitor estruturado o encontra. A regra e por declaracao: o ficheiro entra em
    `fontes_adicionais`, com a constante que guarda a referencia.
    """
    achados: list[Achado] = []
    digests = {entrada.digest for entrada in inventario.entradas}
    for caminho in percorrer(raiz):
        ficheiro = relativo(caminho, raiz)
        nome = caminho.name
        partes = caminho.relative_to(raiz).parts
        do_github = partes[0] == ".github" and nome.endswith((".yml", ".yaml"))
        if not (
            nome.endswith(_SUFIXOS_DE_CODIGO)
            or nome in ("Makefile", "makefile", "GNUmakefile")
            or do_github
        ):
            continue
        # So os testes em Python ficam de fora (constroem linhas de comando como
        # dados). Um `.sh` numa pasta `tests` e um script como outro qualquer.
        if nome.endswith(".py") and ("tests" in partes or ficheiro.startswith("tools/supply_chain/")):
            continue
        for numero, linha in enumerate(ler_texto(caminho).split("\n"), start=1):
            limpa = linha.strip()
            if limpa.startswith(("#", "//", "@#", "*", "- #")) or not _CHAMA_DOCKER.search(limpa):
                continue
            if re.match(r"^@?(?:echo|printf)\b", limpa):
                continue
            if nome.endswith(".py"):
                if ficheiro not in inventario.fontes:
                    achados.append(
                        Achado(
                            "lancador-nao-declarado", ficheiro, numero,
                            "este ficheiro chama o Docker e nao esta em "
                            f"`fontes_adicionais` de {INVENTARIO}; declare a constante "
                            "que guarda a imagem (ou `sem_imagem`, com a razao)",
                        )
                    )
                break
            # Fora de Python nao ha constante a declarar: a propria linha que
            # nomeia uma imagem tem de trazer um digest do inventario.
            if _LANCA.search(limpa):
                presentes = set(_DIGEST_NA_LINHA.findall(limpa))
                if not presentes or not presentes <= digests:
                    achados.append(
                        Achado(
                            "lancador-nao-declarado", ficheiro, numero,
                            "`docker run|pull|create` fora do compose: a linha tem de "
                            f"trazer a imagem com um digest registado em {INVENTARIO}",
                        )
                    )
    for ficheiro in inventario.fontes:
        if not (raiz / ficheiro).is_file():
            achados.append(
                Achado(
                    "inventario-entrada-morta", INVENTARIO, 0,
                    f"`fontes_adicionais` nomeia {ficheiro}, que nao existe",
                )
            )
    return achados


def recolher(raiz: Path, inventario: Inventario) -> tuple[list[Referencia], list[Achado]]:
    referencias: list[Referencia] = []
    achados: list[Achado] = []

    args_de_from: dict[str, set[str]] = {}
    for caminho in percorrer(raiz):
        if dockerfile.e_dockerfile(caminho):
            try:
                do_ficheiro, args = _do_dockerfile(caminho, raiz)
            except dockerfile.DockerfileIlegivel as excepcao:
                achados.append(Achado("ficheiro-ilegivel", relativo(caminho, raiz), 0, str(excepcao)))
                continue
            referencias += do_ficheiro
            args_de_from[relativo(caminho, raiz)] = args
        elif _e_do_github(caminho, raiz):
            do_ficheiro, problemas = _do_yaml(caminho, raiz, do_github=True)
            referencias += do_ficheiro
            achados += problemas
        elif (
            caminho.suffix in (".yml", ".yaml")
            and not compose_mod.e_compose(caminho)
            and _MENCIONA_IMAGE.search(ler_texto(caminho))
        ):
            # Nem compose nem GitHub, e fala de `image:`: um manifesto de
            # Kubernetes, por exemplo. Le-se pela mesma regra.
            do_ficheiro, problemas = _do_yaml(caminho, raiz, do_github=False)
            referencias += do_ficheiro
            achados += problemas

    lidos, ilegiveis = compose_mod.ler_todos(raiz)
    for ficheiro, erro in ilegiveis:
        achados.append(Achado("ficheiro-ilegivel", ficheiro, 0, erro))
    variaveis: set[str] = set()
    for ficheiro_compose in lidos:
        try:
            do_ficheiro, usadas, problemas = _do_compose(ficheiro_compose, raiz, args_de_from)
        except arvore_yaml.YamlIlegivel as excepcao:
            achados.append(Achado("ficheiro-ilegivel", ficheiro_compose.ficheiro, 0, str(excepcao)))
            continue
        referencias += do_ficheiro
        variaveis |= usadas
        achados += problemas
    referencias += _dos_ficheiros_env(raiz, variaveis)

    for ficheiro, constante in inventario.fontes.items():
        if constante and (raiz / ficheiro).is_file():
            referencias.append(_da_constante(raiz, ficheiro, constante))
    achados += _lancadores(raiz, inventario)

    # Um `ARG` que alimenta dois `FROM` e uma referencia, nao duas: o que se
    # corrige e uma linha, e conta-la duas vezes inflacionava o numero que o
    # gate imprime.
    unicas: dict[tuple, Referencia] = {}
    for referencia in referencias:
        unicas.setdefault((referencia.ficheiro, referencia.linha, referencia.valor, referencia.bruto), referencia)
    return list(unicas.values()), achados


# --------------------------------------------------------------- verificacao


def verificar(raiz: Path, hoje: _datetime.date | None = None) -> tuple[list[Achado], dict]:
    inventario = ler_inventario(raiz, hoje)
    referencias, achados = recolher(raiz, inventario)
    usadas: set[tuple[str, str]] = set()

    for referencia in referencias:
        onde = (referencia.ficheiro, referencia.linha)
        if referencia.valor is None:
            achados.append(
                Achado(
                    "imagem-nao-resolvida", *onde,
                    f"{referencia.origem}: `{referencia.bruto}` depende de um valor que "
                    "nao esta no repositorio. De-lhe uma omissao com digest "
                    "(`${VAR:-nome:etiqueta@sha256:...}`).",
                )
            )
            continue
        partes = decompor(referencia.valor)
        if partes is None:
            achados.append(
                Achado(
                    "imagem-sem-digest", *onde,
                    f"{referencia.origem}: `{referencia.valor}` nao e uma referencia "
                    "legivel com `@sha256:` de 64 hexadecimais.",
                )
            )
            continue
        if partes.digest is None:
            achados.append(
                Achado(
                    "imagem-sem-digest", *onde,
                    f"{referencia.origem}: `{referencia.valor}` usa etiqueta sem "
                    "`@sha256:`. Uma etiqueta pode passar a apontar para outra imagem; "
                    "leia o digest da fonte (`docker buildx imagetools inspect`) e "
                    f"registe-o em {INVENTARIO}.",
                )
            )
            continue
        entrada = inventario.procurar(partes.nome, partes.digest)
        if entrada is None:
            achados.append(
                Achado(
                    "imagem-fora-do-inventario", *onde,
                    f"{referencia.origem}: `{partes.nome}@{partes.digest[:19]}…` nao "
                    f"consta de {INVENTARIO}. Um digest que ninguem registou e um "
                    "digest que ninguem leu da fonte.",
                )
            )
            continue
        usadas.add((nome_canonico(entrada.nome), entrada.digest))
        if partes.etiqueta is not None and partes.etiqueta != entrada.etiqueta:
            achados.append(
                Achado(
                    "imagem-fora-do-inventario", *onde,
                    f"{referencia.origem}: a etiqueta `{partes.etiqueta}` nao e a que o "
                    f"inventario regista para este digest (`{entrada.etiqueta}`).",
                )
            )

    for entrada in inventario.entradas:
        if (nome_canonico(entrada.nome), entrada.digest) not in usadas:
            achados.append(
                Achado(
                    "inventario-entrada-morta", INVENTARIO, 0,
                    f"`{entrada.nome}:{entrada.etiqueta}` esta no inventario e nada o "
                    "referencia. Uma entrada morta e um digest aprovado a espera de uso.",
                )
            )
        # Por fronteira, como a lista de bloqueio, e nao por igualdade com o
        # ultimo segmento: `litellm-database` e `litellm-non_root` sao imagens
        # do mesmo projecto, e a primeira versao desta regra deixava-as passar.
        canonico = nome_canonico(entrada.nome)
        for publicada, fonte in ASSINATURA_PUBLICADA.items():
            if entrada.cosign == COSIGN_VERIFICAR:
                continue
            if re.search(rf"(?:^|[^a-z0-9]){re.escape(publicada)}(?:[^a-z0-9]|$)", canonico):
                achados.append(
                    Achado(
                        "cosign-obrigatorio", INVENTARIO, 0,
                        f"`{entrada.nome}` tem assinatura publicada ({fonte}); "
                        f"`cosign: {entrada.cosign}` nao e aceitavel — tem de ser `verificar`.",
                    )
                )

    resumo = {
        "referencias": len(referencias),
        "imagens": len(inventario.entradas),
        "cosign": {
            estado: sum(1 for e in inventario.entradas if e.cosign == estado)
            for estado in ESTADOS_COSIGN
        },
        "inventario": inventario,
    }
    return achados, resumo
