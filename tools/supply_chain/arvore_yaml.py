"""Leitor estrutural de YAML para ficheiros de compose e workflows.

O `kamba_yaml` recusa ancoras e *merge keys*, de proposito, e o compose de
desenvolvimento vive delas (`<<: *service-defaults`). Este leitor existe para
responder a perguntas que dependem da **estrutura resolvida**: «este servico
corre com `read_only: true`?» nao se responde com uma expressao regular quando
a chave vem de uma ancora.

Nao e um parser de YAML. Le a forma em blocos, resolve ancoras, aliases e
*merge keys*, e guarda os escalares em bruto. O que nao consegue seguir levanta
`YamlIlegivel` — e quem chama transforma isso em achado: fail-closed, porque um
ficheiro que nao se le pode dizer qualquer coisa.
"""

from __future__ import annotations

import dataclasses
import re

__all__ = ["YamlIlegivel", "No", "Documento", "ler"]


class YamlIlegivel(ValueError):
    """O ficheiro usa uma forma que este leitor nao segue."""


@dataclasses.dataclass
class No:
    #: `None` num item de lista.
    chave: str | None
    #: Escalar em bruto (com aspas, se as tiver). Vazio quando o valor e um bloco.
    valor: str
    linha: int
    indentacao: int
    filhos: list["No"] = dataclasses.field(default_factory=list)
    ancora: str | None = None
    #: Escalar de bloco (`|` ou `>`): o texto esta em `valor`.
    bloco: bool = False

    def texto(self) -> str:
        """O escalar sem aspas."""
        valor = self.valor.strip()
        if len(valor) >= 2 and valor[0] == valor[-1] and valor[0] in "\"'":
            return valor[1:-1]
        return valor

    def e_lista(self) -> bool:
        return bool(self.filhos) and all(f.chave is None for f in self.filhos)


_CHAVE_ASPAS = re.compile(r"""^(?P<chave>"[^"]*"|'[^']*')\s*:(?:\s+(?P<resto>.*))?$""")
_CHAVE = re.compile(r"""^(?P<chave>[^\s:"'\[\]{}#&*!|>-][^:]*?|<<|-[^\s:][^:]*?)\s*:(?:\s+(?P<resto>.*))?$""")
_ANCORA = re.compile(r"^&(?P<nome>[A-Za-z0-9_.-]+)(?:\s+(?P<resto>.*))?$")
_BLOCO = re.compile(r"^[|>][+-]?[0-9]*$")
_ALIAS = re.compile(r"^\*(?P<nome>[A-Za-z0-9_.-]+)$")


def _sem_comentario(linha: str) -> str:
    """Remove o comentario de fim de linha, respeitando aspas."""
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


def _casar_chave(conteudo: str):
    if conteudo[:1] in "\"'":
        return _CHAVE_ASPAS.match(conteudo)
    return _CHAVE.match(conteudo)


def _fluxo_aberto(texto: str) -> bool:
    """`[a,` ou `{a:` que continua na linha seguinte."""
    profundidade = 0
    aspa = ""
    for caractere in texto:
        if aspa:
            if caractere == aspa:
                aspa = ""
        elif caractere in "\"'":
            aspa = caractere
        elif caractere in "[{":
            profundidade += 1
        elif caractere in "]}":
            profundidade -= 1
    return profundidade > 0


class Documento:
    def __init__(self, raiz: No, ancoras: dict[str, No]) -> None:
        self.raiz = raiz
        self.ancoras = ancoras

    # ------------------------------------------------------------ resolucao

    def resolver(self, no: No) -> No:
        """Segue um alias ate ao no que a ancora nomeia."""
        vistos: set[str] = set()
        while True:
            alias = _ALIAS.match(no.valor.strip()) if not no.filhos else None
            if not alias:
                return no
            nome = alias.group("nome")
            if nome in vistos or nome not in self.ancoras:
                raise YamlIlegivel(f"linha {no.linha}: alias `*{nome}` sem ancora")
            vistos.add(nome)
            no = self.ancoras[nome]

    def _alvos_de_merge(self, no: No) -> list[No]:
        valor = no.valor.strip()
        if no.filhos:
            candidatos = [filho.valor.strip() for filho in no.filhos]
        elif valor.startswith("[") and valor.endswith("]"):
            candidatos = [parte.strip() for parte in valor[1:-1].split(",") if parte.strip()]
        else:
            candidatos = [valor]
        alvos: list[No] = []
        for candidato in candidatos:
            alias = _ALIAS.match(candidato)
            if not alias or alias.group("nome") not in self.ancoras:
                raise YamlIlegivel(
                    f"linha {no.linha}: *merge key* que nao se consegue seguir ({candidato!r})"
                )
            alvos.append(self.ancoras[alias.group("nome")])
        return alvos

    def mapa(self, no: No, _profundidade: int = 0) -> dict[str, No]:
        """As chaves efectivas de um mapa, com *merge keys* resolvidas.

        Semantica do YAML: as chaves do proprio mapa ganham as fundidas, e entre
        varias fontes fundidas ganha a primeira.
        """
        if _profundidade > 20:
            raise YamlIlegivel(f"linha {no.linha}: *merge keys* em ciclo")
        no = self.resolver(no)
        if no.valor.strip().startswith("{"):
            raise YamlIlegivel(
                f"linha {no.linha}: mapa em estilo de fluxo; escreva-o em blocos"
            )
        efectivo: dict[str, No] = {}
        for filho in no.filhos:
            if filho.chave == "<<":
                for alvo in self._alvos_de_merge(filho):
                    for chave, valor in self.mapa(alvo, _profundidade + 1).items():
                        efectivo.setdefault(chave, valor)
        for filho in no.filhos:
            if filho.chave not in (None, "<<"):
                efectivo[filho.chave] = filho
        return efectivo

    def itens(self, no: No) -> list[str]:
        """Os escalares de uma lista, em blocos ou em estilo de fluxo."""
        no = self.resolver(no)
        if no.filhos:
            return [self.resolver(filho).texto() for filho in no.filhos if filho.chave is None]
        valor = no.valor.strip()
        if valor.startswith("[") and valor.endswith("]"):
            return [
                parte.strip().strip("\"'")
                for parte in valor[1:-1].split(",")
                if parte.strip()
            ]
        return [no.texto()] if valor else []

    def todos(self):
        """Todos os nos, em profundidade."""
        pendentes = list(reversed(self.raiz.filhos))
        while pendentes:
            no = pendentes.pop()
            yield no
            pendentes.extend(reversed(no.filhos))


def ler(texto: str) -> Documento:
    linhas = texto.replace("\r\n", "\n").split("\n")
    raiz = No(None, "", 0, -1)
    ancoras: dict[str, No] = {}
    pilha: list[No] = [raiz]
    documentos = 0
    indice = 0

    def consumir_bloco(indentacao_pai: int) -> str:
        nonlocal indice
        partes: list[str] = []
        while indice < len(linhas):
            bruta = linhas[indice]
            if bruta.strip() and len(bruta) - len(bruta.lstrip(" ")) <= indentacao_pai:
                break
            partes.append(bruta.strip())
            indice += 1
        return "\n".join(partes).strip()

    def valor_de(resto: str, no: No, indentacao: int) -> None:
        """Preenche `no` a partir do que vem depois de `chave:` ou de `- `."""
        nonlocal indice
        resto = (resto or "").strip()
        ancora = _ANCORA.match(resto)
        if ancora:
            no.ancora = ancora.group("nome")
            if no.ancora in ancoras:
                raise YamlIlegivel(f"linha {no.linha}: ancora `&{no.ancora}` repetida")
            ancoras[no.ancora] = no
            resto = (ancora.group("resto") or "").strip()
        if _BLOCO.match(resto):
            no.bloco = True
            no.valor = consumir_bloco(indentacao)
            return
        while _fluxo_aberto(resto):
            if indice >= len(linhas):
                raise YamlIlegivel(f"linha {no.linha}: estilo de fluxo por fechar")
            resto += " " + _sem_comentario(linhas[indice]).strip()
            indice += 1
        no.valor = resto

    while indice < len(linhas):
        bruta = linhas[indice]
        numero = indice + 1
        indice += 1
        avanco = bruta[: len(bruta) - len(bruta.lstrip())]
        if "\t" in avanco:
            raise YamlIlegivel(f"linha {numero}: tabulacao na indentacao")
        conteudo = _sem_comentario(bruta).strip()
        if not conteudo:
            continue
        if conteudo == "---":
            documentos += 1
            if documentos > 1 or raiz.filhos:
                raise YamlIlegivel(f"linha {numero}: documentos multiplos")
            continue
        indentacao = len(bruta) - len(bruta.lstrip(" "))
        e_item = conteudo == "-" or conteudo.startswith("- ")

        # Sobe ate ao pai. Uma lista pode estar a mesma indentacao da chave que
        # a abre (`needs:` seguido de `- a` sem recuo), e nesse caso a chave
        # fica na pilha.
        while len(pilha) > 1:
            topo = pilha[-1]
            if topo.indentacao < indentacao:
                break
            if (
                e_item
                and topo.indentacao == indentacao
                and topo.chave is not None
                and not topo.valor
                and not topo.bloco
                and all(f.chave is None for f in topo.filhos)
            ):
                break
            pilha.pop()
        pai = pilha[-1]

        if e_item:
            resto = conteudo[1:].strip()
            item = No(None, "", numero, indentacao)
            pai.filhos.append(item)
            pilha.append(item)
            chave = _casar_chave(resto) if resto else None
            if chave:
                # Item que e um mapa: a primeira chave vem na linha do `-`.
                recuo = indentacao + (len(conteudo) - len(resto))
                filho = No(chave.group("chave").strip("\"'"), "", numero, recuo)
                item.filhos.append(filho)
                pilha.append(filho)
                valor_de(chave.group("resto") or "", filho, recuo)
            else:
                valor_de(resto, item, indentacao)
            continue

        chave = _casar_chave(conteudo)
        if not chave:
            raise YamlIlegivel(
                f"linha {numero}: nem `chave: valor` nem item de lista ({conteudo!r})"
            )
        if pai.chave is not None and pai.valor and not pai.bloco:
            raise YamlIlegivel(
                f"linha {numero}: bloco indentado sob um escalar (linha {pai.linha})"
            )
        no = No(chave.group("chave").strip("\"'"), "", numero, indentacao)
        pai.filhos.append(no)
        pilha.append(no)
        valor_de(chave.group("resto") or "", no, indentacao)

    return Documento(raiz, ancoras)
