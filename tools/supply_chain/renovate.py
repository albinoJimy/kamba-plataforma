"""A quarentena de versoes novas nao foi desligada (KAM-067, criterio 8).

O `renovate.json5` ja traz, desde o KAM-001, `minimumReleaseAge: "7 days"` e
`automerge: false`. O que nao havia era **nada que falhasse** se alguem os
retirasse — e uma politica de quarentena que se apaga com um *diff* de uma linha
sem nenhum gate dar por isso protege enquanto ninguem lhe tocar.

O que isto **nao** prova: que o Renovate esta instalado no repositorio e a
aplicar o ficheiro. Isso so se observa num PR aberto por ele.
"""

from __future__ import annotations

import json
import re
from pathlib import Path

from .base import Achado, ConfiguracaoInvalida, ler_texto

FICHEIRO = "renovate.json5"

#: Os outros sitios onde o Renovate procura configuracao. A documentacao dele
#: (configuration-options, lida a 2026-10-12 pela revisao adversarial) da
#: precedencia a `renovate.json` sobre `renovate.json5` e para no primeiro: um
#: ficheiro destes ao lado **substitui** o que aqui se verifica. INDICIO quanto
#: a ordem exacta; a regra nao depende dela — qualquer segundo ficheiro falha.
SOMBRAS = (
    "renovate.json", "renovate.jsonc", ".renovaterc", ".renovaterc.json", ".renovaterc.json5",
    ".github/renovate.json", ".github/renovate.json5", ".gitlab/renovate.json",
    ".gitlab/renovate.json5",
)
#: Outros actualizadores de dependencias, que nao tem quarentena nenhuma.
OUTROS_ACTUALIZADORES = (".github/dependabot.yml", ".github/dependabot.yaml")

#: *Proposta* do ticket e de `docs/tecnica/08` §4.8 («p. ex. >= 7 dias»).
QUARENTENA_MINIMA_DIAS = 7

_UNIDADES = {"day": 1, "days": 1, "d": 1, "week": 7, "weeks": 7, "w": 7}


def json5_para_json(texto: str) -> str:
    """Converte o subconjunto de JSON5 que o ficheiro usa em JSON.

    Comentarios `//` e `/* */`, chaves sem aspas e virgulas finais. Cadeias so
    com aspas duplas — o que este repositorio escreve.
    """
    saida: list[str] = []
    indice, tamanho = 0, len(texto)
    while indice < tamanho:
        caractere = texto[indice]
        if caractere == '"':
            fim = indice + 1
            while fim < tamanho and texto[fim] != '"':
                fim += 2 if texto[fim] == "\\" else 1
            saida.append(texto[indice : fim + 1])
            indice = fim + 1
        elif texto.startswith("//", indice):
            fim = texto.find("\n", indice)
            indice = tamanho if fim == -1 else fim
        elif texto.startswith("/*", indice):
            fim = texto.find("*/", indice + 2)
            if fim == -1:
                raise ValueError("comentario `/*` por fechar")
            indice = fim + 2
        elif caractere == "'":
            raise ValueError("cadeias com aspas simples nao sao suportadas; use aspas duplas")
        else:
            saida.append(caractere)
            indice += 1
    sem_comentarios = "".join(saida)

    # Protege as cadeias antes de mexer no resto.
    cadeias: list[str] = []

    def guardar(correspondencia: re.Match) -> str:
        cadeias.append(correspondencia.group(0))
        return f"\x00{len(cadeias) - 1}\x00"

    protegido = re.sub(r'"(?:\\.|[^"\\])*"', guardar, sem_comentarios)
    protegido = re.sub(r"([{,]\s*)([A-Za-z_$][A-Za-z0-9_$]*)(\s*:)", r'\1"\2"\3', protegido)
    protegido = re.sub(r",(\s*[}\]])", r"\1", protegido)
    return re.sub(r"\x00(\d+)\x00", lambda m: cadeias[int(m.group(1))], protegido)


def dias(valor) -> int | None:
    """`"7 days"` -> 7. `None` quando nao e um prazo legivel (ou e `null`)."""
    if not isinstance(valor, str):
        return None
    correspondencia = re.fullmatch(r"\s*(\d+)\s*([a-z]+)\s*", valor.lower())
    if not correspondencia or correspondencia.group(2) not in _UNIDADES:
        return None
    return int(correspondencia.group(1)) * _UNIDADES[correspondencia.group(2)]


def ler(raiz: Path) -> dict:
    caminho = raiz / FICHEIRO
    if not caminho.is_file():
        raise ConfiguracaoInvalida(f"ficheiro em falta: {FICHEIRO}")
    try:
        dados = json.loads(json5_para_json(ler_texto(caminho)))
    except (ValueError, json.JSONDecodeError) as excepcao:
        raise ConfiguracaoInvalida(f"{FICHEIRO}: {excepcao}") from excepcao
    if not isinstance(dados, dict):
        raise ConfiguracaoInvalida(f"{FICHEIRO}: esperava um objecto no topo")
    return dados


def verificar(raiz: Path) -> tuple[list[Achado], dict]:
    dados = ler(raiz)
    achados: list[Achado] = []

    def achado(regra: str, mensagem: str) -> None:
        achados.append(Achado(regra, FICHEIRO, 0, mensagem))

    quarentena = dias(dados.get("minimumReleaseAge"))
    if quarentena is None or quarentena < QUARENTENA_MINIMA_DIAS:
        achado(
            "quarentena-desligada",
            f"`minimumReleaseAge` de topo tem de ser >= {QUARENTENA_MINIMA_DIAS} dias "
            f"(lido {dados.get('minimumReleaseAge')!r}). Uma versao que espera sete "
            "dias para entrar e uma versao que outras pessoas ja viram.",
        )
    if dados.get("automerge") is not False:
        achado(
            "automerge-ligado",
            "`automerge` de topo tem de ser `false`: uma dependencia que entra sem "
            "um humano a ver e uma dependencia que ninguem reviu.",
        )
    if dados.get("internalChecksFilter") == "none":
        achado(
            "quarentena-desligada",
            '`internalChecksFilter: "none"` faz o Renovate propor versoes que ainda '
            "nao cumpriram a quarentena.",
        )
    if dados.get("enabled") is False:
        achado("quarentena-desligada", "`enabled: false` desliga o Renovate inteiro.")

    for sombra in SOMBRAS:
        if (raiz / sombra).is_file():
            achado(
                "configuracao-sombra",
                f"existe `{sombra}`. O Renovate le um so ficheiro de configuracao, e "
                f"este pode ser o que ele le em vez de `{FICHEIRO}`. Fica um so.",
            )
    manifesto = raiz / "package.json"
    if manifesto.is_file():
        try:
            if "renovate" in json.loads(ler_texto(manifesto)):
                achado(
                    "configuracao-sombra",
                    f"`package.json` tem uma chave `renovate`; a configuracao vive em `{FICHEIRO}`.",
                )
        except json.JSONDecodeError:
            pass
    for outro in OUTROS_ACTUALIZADORES:
        if (raiz / outro).is_file():
            achado(
                "configuracao-sombra",
                f"existe `{outro}`: um segundo actualizador de dependencias, sem "
                "quarentena. As actualizacoes passam todas pelo Renovate.",
            )

    for preset in dados.get("extends") or []:
        if isinstance(preset, str) and "automerge" in preset.lower():
            achado("automerge-ligado", f"`extends` inclui o preset `{preset}`.")

    # Em qualquer profundidade, e nao so em `packageRules`: `patch: {...}`,
    # `npm: {...}`, `lockFileMaintenance: {...}` e os blocos por gestor aceitam
    # as mesmas duas chaves. A unica excepcao a quarentena e
    # `vulnerabilityAlerts`, tratada a seguir.
    def percorrer(no, caminho: str) -> None:
        if isinstance(no, list):
            for indice, item in enumerate(no, start=1):
                percorrer(item, f"{caminho}[{indice}]")
            return
        if not isinstance(no, dict):
            return
        for chave, valor in no.items():
            onde = f"{caminho}.{chave}" if caminho else chave
            if not caminho and chave in ("minimumReleaseAge", "automerge", "vulnerabilityAlerts"):
                continue
            if chave == "minimumReleaseAge":
                prazo = dias(valor)
                if prazo is None or prazo < QUARENTENA_MINIMA_DIAS:
                    achado(
                        "quarentena-desligada",
                        f"`{onde}` baixa a quarentena para {valor!r}. A unica excepcao "
                        "e `vulnerabilityAlerts`, que e marcada e revista.",
                    )
            elif chave in ("automerge", "platformAutomerge") and valor is True:
                achado("automerge-ligado", f"`{onde}` liga o automerge.")
            elif chave == "extends" and isinstance(valor, list) and caminho:
                for preset in valor:
                    if isinstance(preset, str) and "automerge" in preset.lower():
                        achado("automerge-ligado", f"`{onde}` inclui o preset `{preset}`.")
            else:
                percorrer(valor, onde)

    percorrer(dados, "")

    # A excepcao que `docs/tecnica/08` §4.8 preve: correccoes de seguranca
    # dispensam a quarentena, mas **marcadas e revistas**.
    alertas = dados.get("vulnerabilityAlerts")
    if isinstance(alertas, dict) and alertas.get("automerge") is True:
        achado("automerge-ligado", "`vulnerabilityAlerts.automerge` liga o automerge.")
    if isinstance(alertas, dict) and alertas.get("enabled", True) is not False:
        prazo = dias(alertas.get("minimumReleaseAge")) if "minimumReleaseAge" in alertas else quarentena
        if prazo is None or prazo < QUARENTENA_MINIMA_DIAS:
            if alertas.get("automerge") is None:
                achado(
                    "excepcao-de-seguranca-sem-revisao",
                    "`vulnerabilityAlerts` dispensa a quarentena e nao fixa "
                    "`automerge: false`.",
                )
            if not alertas.get("reviewers"):
                achado(
                    "excepcao-de-seguranca-sem-revisao",
                    "`vulnerabilityAlerts` dispensa a quarentena sem `reviewers`: a "
                    "excepcao e para correccoes **revistas**.",
                )
            if not alertas.get("labels"):
                achado(
                    "excepcao-de-seguranca-sem-revisao",
                    "`vulnerabilityAlerts` dispensa a quarentena sem `labels`: a "
                    "excepcao e para correccoes **marcadas**.",
                )

    return achados, {"quarentena_dias": quarentena}
