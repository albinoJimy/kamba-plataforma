"""O varrimento, e a aplicacao de `ci/secrets-allow.yaml`."""

from __future__ import annotations

import dataclasses
import fnmatch
from pathlib import Path

from kamba_yaml import YamlSubsetError, exigir_chaves, load_file

#: As chaves de `ci/secrets-allow.yaml` que este leitor conhece (KAM-134).
_CHAVES = {"version", "placeholders_literais", "areas"}

from .patterns import CLASSES, PADROES, PADROES_DIGEST, entropia_de_shannon

#: Classes cujo **prefixo** e a prova: `ghp_`, `sk-ant-`, `-----BEGIN … KEY-----`.
#: Para estas, um placeholder nao dispensa nada — uma chave com forma real e
#: uma chave com forma real, chame-se o seu valor `example` ou nao.
_CLASSES_COM_PREFIXO = frozenset({"chave_api", "chave_privada"})


class ConfiguracaoInvalida(RuntimeError):
    """`ci/secrets-allow.yaml` esta em falta ou malformado.

    Levanta-se em vez de varrer sem permissoes: sem o ficheiro, **tudo** seria
    achado e o gate ficaria vermelho por configuracao, nao por segredo.
    """


@dataclasses.dataclass(frozen=True)
class Achado:
    ficheiro: str
    linha: int
    padrao: str
    classe: str
    razao: str
    #: Nunca o valor. Um relatorio de segredos que imprime o segredo copia-o
    #: para os logs do CI, que e exactamente onde ele nao pode estar.
    amostra: str

    def __str__(self) -> str:
        return (
            f"{self.ficheiro}:{self.linha}: possivel segredo ({self.padrao}, "
            f"classe {self.classe}): {self.amostra}\n    {self.razao}"
        )


def _ofuscar(valor: str) -> str:
    """Mostra o suficiente para localizar, nunca o suficiente para usar."""
    if len(valor) <= 8:
        return "*" * len(valor)
    return f"{valor[:4]}…{valor[-2:]} ({len(valor)} caracteres)"


@dataclasses.dataclass(frozen=True)
class Permissoes:
    placeholders: frozenset[str]
    areas: tuple[tuple[str, frozenset[str]], ...]

    @classmethod
    def ler(cls, raiz: Path) -> "Permissoes":
        caminho = raiz / "ci" / "secrets-allow.yaml"
        if not caminho.is_file():
            raise ConfiguracaoInvalida(f"ficheiro em falta: {caminho}")
        try:
            dados = load_file(caminho)
        except YamlSubsetError as excepcao:
            raise ConfiguracaoInvalida(str(excepcao)) from excepcao
        # KAM-134: este leitor ja recusava uma **classe** inventada (abaixo) e
        # ignorava em silencio uma **chave** inventada de topo. Eram o mesmo
        # defeito visto de dois lados.
        exigir_chaves(dados, _CHAVES, str(caminho), erro=ConfiguracaoInvalida)
        if dados.get("version") != 1:
            raise ConfiguracaoInvalida(f"{caminho}: 'version' tem de ser 1")

        areas = []
        for indice, area in enumerate(dados.get("areas") or [], start=1):
            exigir_chaves(
                area, {"caminho", "classes", "razao"}, f"{caminho}: area {indice}",
                erro=ConfiguracaoInvalida,
            )
            faltam = [c for c in ("caminho", "classes", "razao") if not area.get(c)]
            if faltam:
                raise ConfiguracaoInvalida(
                    f"{caminho}: area {indice} sem {', '.join(faltam)}"
                )
            if len(str(area["razao"])) < 30:
                raise ConfiguracaoInvalida(
                    f"{caminho}: area {indice} ({area['caminho']}) tem uma razao "
                    "demasiado curta para se compreender daqui a seis meses"
                )
            classes = frozenset(str(c) for c in area["classes"])
            # Uma classe que nenhum padrao produz permite **nada**, e a area
            # fica inoperante em silencio. Tres das quatro areas deste ficheiro
            # declaravam `placeholders` e `exemplos`, que nao sao classes de
            # padrao nenhum: o `docs/**/*.md` dizia permitir exemplos de chave e
            # nao permitia, e ninguem dava por isso porque nada o confrontava.
            desconhecidas = sorted(classes - set(CLASSES))
            if desconhecidas:
                raise ConfiguracaoInvalida(
                    f"{caminho}: area {indice} ({area['caminho']}) declara "
                    f"classe(s) que nenhum padrao produz: {', '.join(desconhecidas)}.\n"
                    f"    As classes sao: {', '.join(CLASSES)}.\n"
                    "    Uma classe inventada nao permite nada: a area fica a "
                    "nao fazer efeito e o gate falha onde o ficheiro diz que nao falha."
                )
            areas.append((str(area["caminho"]), classes))

        return cls(
            placeholders=frozenset(
                str(p).lower() for p in (dados.get("placeholders_literais") or [])
            ),
            areas=tuple(areas),
        )

    def classes_permitidas(self, ficheiro: str) -> frozenset[str]:
        """Uniao das classes permitidas pelas areas que batem no ficheiro."""
        permitidas: set[str] = set()
        for padrao, classes in self.areas:
            if fnmatch.fnmatch(ficheiro, padrao) or ficheiro == padrao:
                permitidas |= classes
        return frozenset(permitidas)

    def sem_areas(self) -> "Permissoes":
        """A mesma configuracao, sem area permitida nenhuma.

        Serve a passagem da historia (`historia.py`), que le o conteudo **uma
        vez por SHA de objecto** e so depois aplica as areas: o mesmo blob pode
        ter entrado em mais do que um caminho — na pasta do canario e fora dela
        — e a area permitida depende do caminho. Varre-se sem areas e filtra-se
        por caminho, para que a deduplicacao poupe a leitura sem dispensar
        nenhum dos caminhos.
        """
        return dataclasses.replace(self, areas=())

    def e_placeholder(self, valor: str) -> bool:
        """Verdadeiro quando o valor **e** um placeholder, nao quando o contem.

        A primeira versao usava `p in minusculas`. O cabecalho do
        `ci/secrets-allow.yaml` descreve estas cadeias como "placeholders e nao
        valores" — o que e igualdade. Com contencao, sete substrings de uso
        corrente desligavam o scanner para qualquer valor que as contivesse, em
        qualquer ficheiro: `sk-proj-…redacted` (prefixo publicado da OpenAI, 50
        caracteres) era dispensado por acabar em `redacted`, e `unknown` — que
        entrou por causa de `KAMBA_COMMIT_SHA=unknown` — dispensava qualquer
        segredo que o contivesse.

        Comparam-se os delimitadores de fora, para que `"SEU-SEGREDO-AQUI"` e
        `<example>` continuem a contar.
        """
        limpo = valor.lower().strip("\"'<>{}[]()$ ")
        return any(limpo == p.lower() for p in self.placeholders)


#: Comprimento acima do qual uma linha se varre em janelas, e nao de uma vez.
#: Linhas enormes existem (minificados, base64 de binarios, JSON de uma linha)
#: e as expressoes custam caro sobre elas.
LIMITE_DE_LINHA = 4096
#: Sobreposicao entre janelas. Tem de ser maior do que o segredo mais longo que
#: se procura, ou um valor partido ao meio pela fronteira escapa a ambas.
SOBREPOSICAO = 512


def _fragmentos(texto: str):
    """(numero de linha, fragmento) — linhas longas vem em janelas sobrepostas.

    A primeira versao fazia `if len(linha) > 4096: continue`, com um comentario
    a dizer "nao se varre, **e diz-se**". Nao se dizia nada: nem aviso, nem
    contador. Era a evasao mais barata que havia — acrescentar espacos antes do
    segredo punha-o fora do alcance do gate, em silencio. E nao era so
    adversarial: um ficheiro gerado ou um `.env` mal formatado chega aos 4096
    caracteres por acidente e deixava de ser varrido.
    """
    for numero, linha in enumerate(texto.split("\n"), start=1):
        if len(linha) <= LIMITE_DE_LINHA:
            yield numero, linha
            continue
        passo = LIMITE_DE_LINHA - SOBREPOSICAO
        for inicio in range(0, len(linha), passo):
            yield numero, linha[inicio : inicio + LIMITE_DE_LINHA]


def varrer_texto(
    texto: str, ficheiro: str, permissoes: Permissoes
) -> list[Achado]:
    """Varre um texto e devolve os achados que as permissoes nao cobrem."""
    permitidas = permissoes.classes_permitidas(ficheiro)
    achados: list[Achado] = []
    #: As janelas sobrepoem-se, pelo que o mesmo valor pode ser visto duas
    #: vezes. Reporta-se uma.
    vistos: set[tuple[int, str, str]] = set()

    for numero, linha in _fragmentos(texto):

        # Os digests reconhecem-se primeiro, e **nunca sao achado**.
        #
        # Um digest e publico por desenho: serve para verificar, nao para
        # autenticar. Nao ha modelo de ameaca em que submeter um `sha256:` seja
        # uma fuga. Reporta-los dava 11 falsos positivos so com o SHA ficticio
        # dos testes do KAM-001 — e um gate que grita por um SHA de commit num
        # teste e um gate que alguem desliga.
        #
        # O reconhecimento serve para **suprimir**: marca os intervalos para que
        # os padroes seguintes nao os voltem a ver e os classifiquem como
        # `atribuicao`. Um valor hexadecimal que seja de facto um segredo e
        # apanhado pelo `atribuicao` — `api_key = "0123…"` dispara, porque ai o
        # nome da variavel diz o que o valor e; um SHA solto em prosa nao.
        intervalos_de_digest: list[tuple[int, int]] = []
        for padrao in PADROES_DIGEST:
            for correspondencia in padrao.expressao.finditer(linha):
                intervalos_de_digest.append(correspondencia.span())

        def dentro_de_digest(inicio: int, fim: int) -> bool:
            return any(a <= inicio and fim <= b for a, b in intervalos_de_digest)

        for padrao in PADROES:
            for correspondencia in padrao.expressao.finditer(linha):
                if dentro_de_digest(*correspondencia.span()):
                    continue

                grupos = correspondencia.groupdict()
                valor = grupos.get("valor") or correspondencia.group(0)

                # O placeholder dispensa por **igualdade**, e nao para as
                # classes cujo prefixo e a prova. Ver `e_placeholder`.
                if padrao.classe not in _CLASSES_COM_PREFIXO:
                    if permissoes.e_placeholder(valor):
                        continue
                if padrao.entropia_minima is not None:
                    if entropia_de_shannon(valor) < padrao.entropia_minima:
                        continue
                if padrao.classe in permitidas:
                    continue

                chave = (numero, padrao.nome, valor)
                if chave in vistos:
                    continue
                vistos.add(chave)

                achados.append(
                    Achado(
                        ficheiro=ficheiro,
                        linha=numero,
                        padrao=padrao.nome,
                        classe=padrao.classe,
                        razao=padrao.razao,
                        amostra=_ofuscar(valor),
                    )
                )

    return achados


#: Extensoes e nomes que nao se varrem: binarios e artefactos.
BINARIOS = {
    ".png", ".jpg", ".jpeg", ".gif", ".webp", ".ico", ".pdf", ".zip", ".gz",
    ".tar", ".whl", ".woff", ".woff2", ".ttf", ".otf", ".mp4", ".mp3", ".pyc",
}


def varrer_ficheiros(caminhos: list[Path], raiz: Path, permissoes: Permissoes) -> list[Achado]:
    achados: list[Achado] = []
    for caminho in caminhos:
        if caminho.suffix.lower() in BINARIOS:
            continue
        try:
            texto = caminho.read_text(encoding="utf-8")
        except (OSError, UnicodeDecodeError):
            continue
        try:
            relativo = caminho.resolve().relative_to(raiz).as_posix()
        except ValueError:
            relativo = caminho.as_posix()
        achados += varrer_texto(texto, relativo, permissoes)
    return achados
