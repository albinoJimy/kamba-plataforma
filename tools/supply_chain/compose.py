"""Ficheiros de compose: descoberta e servicos com a estrutura resolvida."""

from __future__ import annotations

import dataclasses
import re
from pathlib import Path

from . import arvore_yaml
from .arvore_yaml import Documento, No
from .base import ler_texto, percorrer, relativo

__all__ = ["Compose", "e_compose", "ler_todos", "INTERPOLACAO", "resolver_interpolacao"]

#: `${VAR}`, `${VAR:-omissao}`, `${VAR-omissao}`, `${VAR:?erro}`.
INTERPOLACAO = re.compile(
    r"\$\{(?P<nome>[A-Za-z_][A-Za-z0-9_]*)(?:(?P<operador>:?[-?+])(?P<resto>[^}]*))?\}"
    r"|\$(?P<simples>[A-Za-z_][A-Za-z0-9_]*)"
)


#: A chave `services`, em qualquer forma: em blocos, entre aspas, indentada,
#: em estilo de fluxo ou em JSON.
_MENCIONA_SERVICES = re.compile(r"""(?:^|[\s{,])["']?services["']?\s*:""")


def e_compose(caminho: Path) -> bool:
    """Um **candidato** a compose: pelo nome, ou por mencionar `services:`.

    A deteccao e larga de proposito, e a leitura e estreita. A primeira versao
    so reconhecia `^services:$`, e o mesmo ficheiro escrito com a chave entre
    aspas, indentado, em estilo de fluxo ou em JSON — tudo formas que o
    `docker compose` aceita — nao era lido por ninguem. Agora e candidato tudo
    o que fale de `services`, e um candidato que nao se le como compose em
    blocos e **achado**, nao silencio.

    Os workflows do GitHub tambem tem `services:`; ficam de fora pelo caminho e
    sao lidos pelo leitor proprio.
    """
    if caminho.suffix not in (".yml", ".yaml", ".json"):
        return False
    if ".github" in caminho.parts:
        return False
    if re.fullmatch(r"(docker-)?compose.*", caminho.stem.lower()):
        return True
    try:
        texto = ler_texto(caminho)
    except OSError:
        return False
    return _MENCIONA_SERVICES.search(texto) is not None


def resolver_interpolacao(valor: str) -> tuple[str | None, list[str]]:
    """Substitui `${VAR:-omissao}` pela omissao. Devolve (valor, variaveis).

    Devolve `None` quando alguma variavel nao tem omissao: o valor so se sabe
    na maquina de quem corre, e isso nao se verifica aqui.
    """
    variaveis: list[str] = []
    resolvido = True

    def trocar(correspondencia: re.Match) -> str:
        nonlocal resolvido
        nome = correspondencia.group("nome") or correspondencia.group("simples")
        variaveis.append(nome)
        operador = correspondencia.group("operador") or ""
        if operador in (":-", "-"):
            return correspondencia.group("resto") or ""
        resolvido = False
        return ""

    texto = INTERPOLACAO.sub(trocar, valor)
    if not resolvido or "$" in texto:
        return None, variaveis
    return texto, variaveis


@dataclasses.dataclass
class Compose:
    caminho: Path
    ficheiro: str
    documento: Documento
    #: nome do servico -> (no do servico, chaves efectivas)
    servicos: dict[str, tuple[No, dict[str, No]]]


def ler(caminho: Path, raiz: Path) -> Compose:
    if caminho.suffix == ".json":
        raise arvore_yaml.YamlIlegivel(
            "compose em JSON: este leitor so segue YAML em blocos; escreva-o em YAML"
        )
    documento = arvore_yaml.ler(ler_texto(caminho))
    servicos: dict[str, tuple[No, dict[str, No]]] = {}
    topo = documento.mapa(documento.raiz)
    if "include" in topo:
        raise arvore_yaml.YamlIlegivel(
            f"linha {topo['include'].linha}: `include:` nao e seguido; os servicos "
            "incluidos ficavam por verificar"
        )
    if "services" in topo:
        for nome, no in documento.mapa(topo["services"]).items():
            servicos[nome] = (no, documento.mapa(no))
    if not servicos:
        # Um candidato sem servicos lidos e um ficheiro que nao se leu: o gate
        # nao pode passar por ele sem ter visto nada.
        raise arvore_yaml.YamlIlegivel(
            "menciona `services` e nao se le como compose: a chave tem de estar no "
            "topo, sem aspas nem indentacao, em blocos, e com pelo menos um servico"
        )
    return Compose(caminho, relativo(caminho, raiz), documento, servicos)


def ler_todos(raiz: Path) -> tuple[list[Compose], list[tuple[str, str]]]:
    """Todos os compose sob `raiz`. Devolve (lidos, [(ficheiro, erro)])."""
    lidos: list[Compose] = []
    ilegiveis: list[tuple[str, str]] = []
    for caminho in percorrer(raiz):
        if not e_compose(caminho):
            continue
        try:
            lidos.append(ler(caminho, raiz))
        except arvore_yaml.YamlIlegivel as excepcao:
            ilegiveis.append((relativo(caminho, raiz), str(excepcao)))
    return lidos, ilegiveis
