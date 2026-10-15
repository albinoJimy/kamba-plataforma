"""Copia congelada do `tools/canon_lint/yamlreg.py` **tal como estava antes do KAM-148**.

Nao e codigo de producao e nao se importa de fora dos testes. Existe por uma
razao so: o criterio de aceitacao do KAM-148 exige que os ficheiros reais que
este leitor le se leiam **igual, campo a campo, antes e depois** da correccao —
e exige-o por comparacao da estrutura lida, nao por «os gates continuam
verdes», porque os gates podiam estar verdes por causa do defeito.

Um retrato da estrutura lida (um JSON de referencia) envelheceria a cada edicao
do ficheiro lido e obrigaria a regenera-lo; **um algoritmo nao envelhece**. Por
isso o oraculo e o leitor antigo. O padrao e o do KAM-136
(`tools/lint_arch/tests/leitor_antes_do_kam136.py`).

O teste falhar **nao e um defeito do teste**: significa que a leitura de um
ficheiro real mudou de resultado, e o DoD do KAM-148 diz o que fazer nesse caso
— «2 revisores se a leitura do `ops/secrets-inventory.yaml` ou de uma fixture de
`registry` mudar de resultado».

O *docstring* original do modulo foi substituido por esta nota; o resto do
ficheiro e copia textual. Os defeitos que esta copia preserva, de proposito,
estao em `tools/canon_lint/tests/corpus_yamlreg.py` — e ha um teste que prova que ela **ainda** os tem: se os
perder, deixou de ser oraculo.
"""

from __future__ import annotations

import re


class YamlIlegivel(ValueError):
    """O ficheiro usa YAML que este leitor nao aceita."""


_CHAVE = re.compile(r"""^(?P<chave>"[^"]*"|'[^']*'|[^\s"'{}\[\],:#&*!|>][^:#]*?)\s*:(?:\s+(?P<resto>.*))?$""")


def _sem_comentario(linha: str) -> str:
    aspa = ""
    for indice, caractere in enumerate(linha):
        if aspa:
            if caractere == aspa:
                aspa = ""
        elif caractere in "\"'":
            aspa = caractere
        elif caractere == "#" and (indice == 0 or linha[indice - 1] in " \t"):
            return linha[:indice]
    return linha


def _escalar(texto: str, onde: str):
    texto = texto.strip()
    if len(texto) >= 2 and texto[0] == texto[-1] and texto[0] in "\"'":
        return texto[1:-1]
    if texto and texto[0] in "&*!|>%@`":
        raise YamlIlegivel(f"{onde}: {texto[0]!r} nao e suportado (ancora, alias, tag ou escalar de bloco)")
    if texto in ("", "~", "null"):
        return None
    if texto in ("true", "false"):
        return texto == "true"
    if re.fullmatch(r"-?\d+", texto):
        return int(texto)
    return texto


class _Fluxo:
    """Analisador descendente de uma expressao de fluxo numa linha."""

    def __init__(self, texto: str, onde: str) -> None:
        self.t, self.i, self.onde = texto, 0, onde

    def _espacos(self) -> None:
        while self.i < len(self.t) and self.t[self.i] in " \t":
            self.i += 1

    def _atomo(self, paragens: str) -> str:
        self._espacos()
        if self.i < len(self.t) and self.t[self.i] in "\"'":
            aspa = self.t[self.i]
            fim = self.t.find(aspa, self.i + 1)
            if fim == -1:
                raise YamlIlegivel(f"{self.onde}: aspas por fechar")
            bruto = self.t[self.i : fim + 1]
            self.i = fim + 1
            return bruto
        inicio = self.i
        while self.i < len(self.t) and self.t[self.i] not in paragens:
            self.i += 1
        return self.t[inicio : self.i].strip()

    def valor(self):
        self._espacos()
        if self.i >= len(self.t):
            raise YamlIlegivel(f"{self.onde}: fluxo que acaba a meio (fluxo em varias linhas nao e suportado)")
        c = self.t[self.i]
        if c == "[":
            self.i += 1
            itens = []
            while True:
                self._espacos()
                if self.i >= len(self.t):
                    raise YamlIlegivel(f"{self.onde}: `[` por fechar")
                if self.t[self.i] == "]":
                    self.i += 1
                    return itens
                itens.append(self.valor())
                self._espacos()
                if self.i < len(self.t) and self.t[self.i] == ",":
                    self.i += 1
                elif self.i < len(self.t) and self.t[self.i] != "]":
                    raise YamlIlegivel(f"{self.onde}: esperava `,` ou `]`")
        if c == "{":
            self.i += 1
            mapa: dict = {}
            while True:
                self._espacos()
                if self.i >= len(self.t):
                    raise YamlIlegivel(f"{self.onde}: `{{` por fechar")
                if self.t[self.i] == "}":
                    self.i += 1
                    return mapa
                chave = _escalar(self._chave_de_fluxo(), self.onde)
                self._espacos()
                if self.i >= len(self.t) or self.t[self.i] != ":":
                    raise YamlIlegivel(f"{self.onde}: esperava `:` depois de {chave!r}")
                self.i += 1
                if str(chave) in mapa:
                    raise YamlIlegivel(f"{self.onde}: chave repetida {chave!r}")
                mapa[str(chave)] = self.valor()
                self._espacos()
                if self.i < len(self.t) and self.t[self.i] == ",":
                    self.i += 1
                elif self.i < len(self.t) and self.t[self.i] != "}":
                    raise YamlIlegivel(f"{self.onde}: esperava `,` ou `}}`")
        return _escalar(self._atomo(",]}"), self.onde)

    def _chave_de_fluxo(self) -> str:
        self._espacos()
        if self.i < len(self.t) and self.t[self.i] in "\"'":
            return self._atomo("")
        inicio = self.i
        while self.i < len(self.t) and self.t[self.i] not in ":,{}[]":
            self.i += 1
        return self.t[inicio : self.i].strip()

    def tudo(self):
        resultado = self.valor()
        self._espacos()
        if self.i != len(self.t):
            raise YamlIlegivel(f"{self.onde}: texto a mais depois do fluxo: {self.t[self.i:]!r}")
        return resultado


def _valor(texto: str, onde: str):
    texto = texto.strip()
    if texto[:1] in ("{", "["):
        return _Fluxo(texto, onde).tudo()
    if texto in ("|", ">", "|-", ">-", "|+", ">+"):
        raise YamlIlegivel(f"{onde}: escalar de bloco nao suportado")
    return _escalar(texto, onde)


class _Leitor:
    def __init__(self, texto: str) -> None:
        self.linhas: list[tuple[int, int, str]] = []
        for numero, bruta in enumerate(texto.replace("\r\n", "\n").split("\n"), start=1):
            margem = bruta[: len(bruta) - len(bruta.lstrip())]
            if "\t" in margem:
                raise YamlIlegivel(f"linha {numero}: tabulacao na indentacao")
            limpa = _sem_comentario(bruta).rstrip()
            if not limpa.strip():
                continue
            if limpa.strip() in ("---", "..."):
                raise YamlIlegivel(f"linha {numero}: documentos multiplos nao suportados")
            self.linhas.append((numero, len(limpa) - len(limpa.lstrip(" ")), limpa.strip()))
        self.p = 0

    def olhar(self):
        return self.linhas[self.p] if self.p < len(self.linhas) else None

    def bloco(self, indentacao: int):
        item = self.olhar()
        numero, actual, conteudo = item
        if conteudo == "-" or conteudo.startswith("- "):
            return self.lista(actual)
        return self.mapa(actual)

    def _filho(self, indentacao: int, numero: int):
        """O valor de uma chave (ou item) sem nada na propria linha."""
        seguinte = self.olhar()
        if seguinte is None:
            return None
        _, proxima, conteudo = seguinte
        if proxima > indentacao:
            return self.bloco(proxima)
        if proxima == indentacao and (conteudo == "-" or conteudo.startswith("- ")):
            return self.lista(proxima)  # lista ao nivel da chave: YAML valido
        return None

    def mapa(self, indentacao: int) -> dict:
        resultado: dict = {}
        while True:
            item = self.olhar()
            if item is None:
                break
            numero, actual, conteudo = item
            if actual < indentacao:
                break
            if actual > indentacao:
                raise YamlIlegivel(f"linha {numero}: indentacao inesperada")
            if conteudo == "-" or conteudo.startswith("- "):
                break
            achado = _CHAVE.match(conteudo)
            if not achado:
                raise YamlIlegivel(f"linha {numero}: esperava `chave: valor` (lido {conteudo!r})")
            self.p += 1
            chave = str(_escalar(achado.group("chave"), f"linha {numero}"))
            if chave in resultado:
                raise YamlIlegivel(f"linha {numero}: chave repetida {chave!r}")
            resto = (achado.group("resto") or "").strip()
            if resto == "":
                resultado[chave] = self._filho(indentacao, numero)
            else:
                resultado[chave] = _valor(resto, f"linha {numero}")
        return resultado

    def lista(self, indentacao: int) -> list:
        resultado: list = []
        while True:
            item = self.olhar()
            if item is None:
                break
            numero, actual, conteudo = item
            if actual != indentacao or not (conteudo == "-" or conteudo.startswith("- ")):
                if actual > indentacao:
                    raise YamlIlegivel(f"linha {numero}: indentacao inesperada numa lista")
                break
            corpo = conteudo[1:].strip()
            if corpo == "":
                self.p += 1
                resultado.append(self._filho(indentacao, numero))
            elif corpo[:1] not in ("{", "[", '"', "'") and _CHAVE.match(corpo):
                # `- chave: valor`: o item e um mapa cuja primeira chave esta
                # nesta linha, a `indentacao + 2`.
                desvio = len(conteudo) - len(corpo)
                self.linhas[self.p] = (numero, indentacao + desvio, corpo)
                resultado.append(self.mapa(indentacao + desvio))
            else:
                self.p += 1
                resultado.append(_valor(corpo, f"linha {numero}"))
        return resultado


def ler(texto: str):
    """Le um documento. Devolve o que la estiver (mapa, lista) ou `None` se vazio."""
    leitor = _Leitor(texto)
    if leitor.olhar() is None:
        return None
    numero, indentacao, _ = leitor.olhar()
    if indentacao != 0:
        raise YamlIlegivel(f"linha {numero}: o documento tem de comecar sem indentacao")
    documento = leitor.bloco(0)
    sobra = leitor.olhar()
    if sobra is not None:
        raise YamlIlegivel(f"linha {sobra[0]}: conteudo que nao foi lido ({sobra[2]!r})")
    return documento
