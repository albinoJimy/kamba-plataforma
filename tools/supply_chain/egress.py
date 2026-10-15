"""Cada servico declara a sua lista de saidas (KAM-067, criterio 9).

A declaracao e o contrato; **a aplicacao na rede e do KAM-076** (proxy de saida
com allowlist de FQDN). O que este verificador garante e que o contrato existe
para todos os servicos, que nega por omissao, e que nao tem buracos do tamanho
da Internet (`*`, um endereco IP, um CIDR).

Onde vive a declaracao:

* `services/<nome>/egress.yaml` para os servicos do monorepo;
* `infra/egress/<nome>.yaml` para os servicos de terceiros que so existem num
  compose (`postgres`, `queue`).

Uma declaracao para um servico que ja nao existe tambem falha: uma lista de
saidas aprovada a espera de dono e o contrario de negar por omissao.
"""

from __future__ import annotations

import re
from pathlib import Path

from kamba_yaml import YamlSubsetError, load_file

from . import compose as compose_mod, dockerfile
from .base import Achado, ConfiguracaoInvalida, percorrer

POR_OMISSAO = "negar"
PROTOCOLOS = ("https", "tcp", "udp", "smtps", "dns")

_CHAVES = {"version", "servico", "por_omissao", "destinos"}
_CHAVES_DESTINO = {"fqdn", "porta", "protocolo", "razao", "ticket"}
_FQDN = re.compile(r"^(?=.{4,253}$)(?:[a-z0-9](?:[a-z0-9-]{0,61}[a-z0-9])?\.)+[a-z][a-z0-9-]{1,62}$")
_TICKET = re.compile(r"^KAM-[0-9]{3}$")


def servicos_esperados(raiz: Path) -> dict[str, str]:
    """nome do servico -> caminho onde a sua declaracao tem de estar."""
    esperados: dict[str, str] = {}
    base = raiz / "services"
    proprios = (
        sorted(p.name for p in base.iterdir() if p.is_dir()) if base.is_dir() else []
    )
    for nome in proprios:
        esperados[nome] = f"services/{nome}/egress.yaml"
    # Um servico fora de `services/` tambem e um servico: o que o identifica e
    # ter um Dockerfile. `apps/novo/Dockerfile` pede `apps/novo/egress.yaml`.
    for caminho in percorrer(raiz):
        if not dockerfile.e_dockerfile(caminho):
            continue
        pasta = caminho.parent.relative_to(raiz)
        if len(pasta.parts) >= 2 and pasta.parts[0] == "services":
            continue
        if not pasta.parts or "tests" in pasta.parts:
            continue
        esperados.setdefault(pasta.as_posix(), f"{pasta.as_posix()}/egress.yaml")
    lidos, _ = compose_mod.ler_todos(raiz)
    for ficheiro_compose in lidos:
        for nome in ficheiro_compose.servicos:
            esperados.setdefault(nome, f"infra/egress/{nome}.yaml")
    return esperados


def _verificar_ficheiro(raiz: Path, nome: str, caminho: str) -> list[Achado]:
    def achado(mensagem: str) -> Achado:
        return Achado("egress-invalido", caminho, 0, mensagem)

    try:
        dados = load_file(raiz / caminho)
    except YamlSubsetError as excepcao:
        # Codigo 2 e nao 1, como as `imagens` e as `licencas` ao lado (KAM-136):
        # um achado e dispensavel por *waiver*, um erro de configuracao nao. Uma
        # lista de saidas que nao se le nao produziu achado nenhum — e e isso que
        # o `base.ConfiguracaoInvalida` diz: «um ficheiro de politica ilegivel
        # nao pode parecer um repositorio limpo».
        raise ConfiguracaoInvalida(f"{caminho}: ilegivel: {excepcao}") from excepcao

    achados: list[Achado] = []
    estranhas = sorted(set(dados) - _CHAVES)
    if estranhas:
        achados.append(achado(f"chave(s) que nenhum codigo le: {', '.join(estranhas)}"))
    if dados.get("version") != 1:
        achados.append(achado("'version' tem de ser 1"))
    if dados.get("servico") != nome.rsplit("/", 1)[-1]:
        achados.append(
            achado(
                f"`servico` tem de ser `{nome.rsplit('/', 1)[-1]}` (lido {dados.get('servico')!r})"
            )
        )
    if dados.get("por_omissao") != POR_OMISSAO:
        achados.append(
            achado(
                f"`por_omissao` tem de ser `{POR_OMISSAO}` (lido "
                f"{dados.get('por_omissao')!r}): o que nao esta na lista nao sai"
            )
        )
    destinos = dados.get("destinos")
    if not isinstance(destinos, list):
        achados.append(
            achado("falta `destinos` — use `destinos: []` para dizer «nao sai para lado nenhum»")
        )
        return achados

    vistos: set[tuple[str, int]] = set()
    for indice, destino in enumerate(destinos, start=1):
        onde = f"destino {indice}"
        if not isinstance(destino, dict):
            achados.append(achado(f"{onde}: esperava um mapa com fqdn, porta, protocolo, razao e ticket"))
            continue
        estranhas = sorted(set(destino) - _CHAVES_DESTINO)
        if estranhas:
            achados.append(achado(f"{onde}: chave(s) desconhecida(s): {', '.join(estranhas)}"))
        faltam = sorted(c for c in _CHAVES_DESTINO if destino.get(c) in (None, ""))
        if faltam:
            achados.append(achado(f"{onde}: campos em falta: {', '.join(faltam)}"))
            continue
        fqdn = str(destino["fqdn"])
        if not _FQDN.match(fqdn):
            achados.append(
                achado(
                    f"{onde}: `{fqdn}` nao e um FQDN em minusculas. Sem `*`, sem "
                    "endereco IP e sem CIDR: uma saida aprovada tem nome."
                )
            )
        porta = destino["porta"]
        if not isinstance(porta, int) or isinstance(porta, bool) or not 1 <= porta <= 65535:
            achados.append(achado(f"{onde}: `porta` tem de ser um inteiro entre 1 e 65535"))
            porta = 0
        if str(destino["protocolo"]) not in PROTOCOLOS:
            achados.append(
                achado(f"{onde}: `protocolo` tem de ser um de {', '.join(PROTOCOLOS)}")
            )
        if len(str(destino["razao"])) < 20:
            achados.append(achado(f"{onde}: `razao` com menos de 20 caracteres"))
        if not _TICKET.match(str(destino["ticket"])):
            achados.append(achado(f"{onde}: `ticket` tem de ser `KAM-NNN`"))
        if (fqdn, porta) in vistos:
            achados.append(achado(f"{onde}: destino repetido ({fqdn}:{porta})"))
        vistos.add((fqdn, porta))
    return achados


def verificar(raiz: Path) -> tuple[list[Achado], dict]:
    achados: list[Achado] = []
    esperados = servicos_esperados(raiz)
    destinos = 0

    for nome, caminho in sorted(esperados.items()):
        if not (raiz / caminho).is_file():
            achados.append(
                Achado(
                    "egress-em-falta", caminho, 0,
                    f"o servico `{nome}` nao declara a sua lista de saidas. Crie o "
                    "ficheiro com `por_omissao: negar` e `destinos: []` se nao sai "
                    "para lado nenhum.",
                )
            )
            continue
        do_ficheiro = _verificar_ficheiro(raiz, nome, caminho)
        achados += do_ficheiro
        if not do_ficheiro:
            destinos += len(load_file(raiz / caminho).get("destinos") or [])

    # Qualquer ficheiro `egress.*` do repositorio, e tudo o que esta em
    # `infra/egress/`, tem de ser a declaracao de um servico esperado. Um
    # `egress.yml` ao lado do `.yaml`, com outra politica, nao e lido por este
    # verificador — e seria lido por quem aplicar a rede.
    declarados = set(esperados.values())
    for caminho in percorrer(raiz):
        relativo = caminho.relative_to(raiz).as_posix()
        e_declaracao = caminho.stem == "egress" or relativo.startswith("infra/egress/")
        if not e_declaracao or "tests" in caminho.relative_to(raiz).parts:
            continue
        if caminho.suffix not in (".yaml", ".yml", ".json"):
            continue
        if relativo not in declarados:
            achados.append(
                Achado(
                    "egress-orfao", relativo, 0,
                    "declaracao de saidas que nao e a de nenhum servico (nome, pasta "
                    "ou extensao errados). Uma lista aprovada sem dono apaga-se.",
                )
            )
    return achados, {"servicos": len(esperados), "destinos": destinos}
