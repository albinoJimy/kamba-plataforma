"""Superficie 4 — `docs/tecnica/**/*.md`: so o nivel 1.

A parte (a) do KAM-111 retirou de `docs/tecnica/` as variantes que o dicionario
substitui. Sem uma verificacao por maquina, a edicao seguinte repunha-as e
ninguem dava por isso: e exactamente assim que os dez documentos divergiram.

O que **fica** nos documentos, e porque, esta em `ci/canon-allow.yaml`:

* `historicas` — a variante e citada para dizer que foi substituida (tabelas
  «correccao ao doc 11», notas «corrige X»). Sem prazo.
* `dividas` — divergencia real que as doze do KAM-111 nao enumeram e que este
  ticket nao pode corrigir («as 12 e so essas»). Com `origem`, `criado_em` e
  `expira_em`: **uma divida vencida falha o gate**.

As duas sao por ficheiro, variante e **numero exacto de ocorrencias**. Uma
excepcao sem contagem deixava entrar a decima ocorrencia atras da primeira; com
ela, acrescentar uma ou retirar uma obriga a tocar no ficheiro de excepcoes — e
uma excepcao que ja nao corresponde a nada tambem falha, para a lista nao
apodrecer.
"""

from __future__ import annotations

import datetime
import re
from dataclasses import dataclass
from pathlib import Path

from kamba_yaml import YamlSubsetError, load_file

from .achados import REGRA, VARIANTE, Achado
from .dicionario import ConfiguracaoInvalida, Saber, _exigir_chaves, _lista, data_iso

PERMITIDAS = "ci/canon-allow.yaml"

#: Prazo maximo de uma divida, em dias. *Proposta*, igual a dos waivers
#: (`docs/ci.md` §5): uma divida sem tecto renova-se para sempre.
PRAZO_MAXIMO_DIAS = 30

_TICKET = re.compile(r"^KAM-\d{3}$")


@dataclass(frozen=True)
class Excepcao:
    ficheiro: str
    variante: str
    ocorrencias: int
    classe: str  # "historica" | "divida"
    expira_em: datetime.date | None = None
    origem: str = ""
    #: Historicas: excertos que provam que a ocorrencia e uma citacao. Cada
    #: linha onde a variante aparece tem de conter pelo menos um.
    ancoras: tuple[str, ...] = ()


class Permitidas:
    def __init__(self, entradas: list[Excepcao]) -> None:
        self.entradas = entradas
        self.por_par = {(e.ficheiro, e.variante): e for e in entradas}

    @classmethod
    def ler(cls, raiz: Path, saber: Saber, hoje: datetime.date) -> "Permitidas":
        caminho = raiz / PERMITIDAS
        if not caminho.is_file():
            raise ConfiguracaoInvalida(f"{PERMITIDAS} nao existe")
        try:
            dados = load_file(caminho)
        except YamlSubsetError as excepcao:
            raise ConfiguracaoInvalida(str(excepcao)) from excepcao
        _exigir_chaves(dados, {"version", "historicas", "dividas"}, PERMITIDAS)
        if dados.get("version") != 1:
            raise ConfiguracaoInvalida(f"{PERMITIDAS}: `version` tem de ser 1")

        conhecidas = set(saber.dicionario.variantes_nome) | set(saber.dicionario.variantes_valor)
        entradas: list[Excepcao] = []
        vistos: set[tuple[str, str]] = set()

        def comum(bruto, onde: str, chaves: set[str]) -> tuple[str, str, int]:
            if not isinstance(bruto, dict):
                raise ConfiguracaoInvalida(f"{onde}: tem de ser um mapa")
            _exigir_chaves(bruto, chaves, onde)
            for chave in ("ficheiro", "variante", "ocorrencias", "razao"):
                if bruto.get(chave) in (None, ""):
                    raise ConfiguracaoInvalida(f"{onde}: falta `{chave}`")
            ficheiro, nome = str(bruto["ficheiro"]), str(bruto["variante"])
            if nome not in conhecidas:
                raise ConfiguracaoInvalida(
                    f"{onde}: {nome!r} nao e uma variante do dicionario; a excepcao nao dispensa nada"
                )
            if not isinstance(bruto["ocorrencias"], int) or isinstance(bruto["ocorrencias"], bool) or bruto["ocorrencias"] < 1:
                raise ConfiguracaoInvalida(f"{onde}: `ocorrencias` tem de ser um inteiro >= 1")
            if len(str(bruto["razao"])) < 40:
                raise ConfiguracaoInvalida(
                    f"{onde}: a razao tem de sobreviver a saida de quem a escreveu (>= 40 caracteres)"
                )
            if (ficheiro, nome) in vistos:
                raise ConfiguracaoInvalida(
                    f"{onde}: o par ({ficheiro}, {nome}) esta declarado duas vezes"
                )
            vistos.add((ficheiro, nome))
            return ficheiro, nome, bruto["ocorrencias"]

        for indice, bruto in enumerate(_lista(dados, "historicas", PERMITIDAS), start=1):
            onde = f"{PERMITIDAS}: historica {indice}"
            ficheiro, nome, quantas = comum(
                bruto, onde, {"ficheiro", "variante", "ocorrencias", "razao", "ancoras"}
            )
            # Uma historica nao tem prazo, pelo que tem de provar que e citacao:
            # sem ancora, trocar a citacao por um uso vivo mantinha a contagem e
            # passava (ANALISE-05, M9).
            ancoras = bruto.get("ancoras")
            if not isinstance(ancoras, list) or not ancoras:
                raise ConfiguracaoInvalida(
                    f"{onde}: uma historica precisa de `ancoras` — os excertos do documento que "
                    "mostram que a variante esta a ser citada como substituida"
                )
            for ancora in ancoras:
                if not isinstance(ancora, str) or len(ancora) < 12 or nome in ancora:
                    raise ConfiguracaoInvalida(
                        f"{onde}: cada ancora e um excerto de >= 12 caracteres da linha, e nao "
                        f"pode conter a propria variante (lido {ancora!r})"
                    )
            entradas.append(Excepcao(ficheiro, nome, quantas, "historica", ancoras=tuple(ancoras)))

        for indice, bruto in enumerate(_lista(dados, "dividas", PERMITIDAS), start=1):
            onde = f"{PERMITIDAS}: divida {indice}"
            ficheiro, nome, quantas = comum(
                bruto,
                onde,
                {"ficheiro", "variante", "ocorrencias", "razao", "origem", "criado_em", "expira_em"},
            )
            for chave in ("origem", "criado_em", "expira_em"):
                if not bruto.get(chave):
                    raise ConfiguracaoInvalida(f"{onde}: uma divida precisa de `{chave}`")
            if not _TICKET.match(str(bruto["origem"])):
                raise ConfiguracaoInvalida(f"{onde}: `origem` {bruto['origem']!r} nao e um KAM-NNN")
            criado = data_iso(str(bruto["criado_em"]), onde)
            expira = data_iso(str(bruto["expira_em"]), onde)
            if criado > hoje:
                raise ConfiguracaoInvalida(
                    f"{onde}: `criado_em` {criado} e futuro. O prazo conta-se do dia em que a "
                    "divida foi registada; uma data futura adiava-o sem limite"
                )
            if expira < criado or (expira - criado).days > PRAZO_MAXIMO_DIAS:
                raise ConfiguracaoInvalida(
                    f"{onde}: o prazo vai de {criado} a {expira}; o maximo sao "
                    f"{PRAZO_MAXIMO_DIAS} dias contados de `criado_em`"
                )
            entradas.append(Excepcao(ficheiro, nome, quantas, "divida", expira, str(bruto["origem"])))
        return cls(entradas)


def _padrao_nome(nome: str) -> re.Pattern:
    return re.compile(r"(?<![A-Za-z0-9_])" + re.escape(nome) + r"(?![A-Za-z0-9_])")


def _padrao_valor(valor: str) -> re.Pattern:
    return re.compile(r"""(['"])""" + re.escape(valor) + r"\1")


def ocorrencias(texto: str, saber: Saber) -> dict[str, list[int]]:
    """Para cada variante presente, as linhas onde aparece (uma por ocorrencia)."""
    padroes = {n: _padrao_nome(n) for n in saber.dicionario.variantes_nome}
    padroes.update({v: _padrao_valor(v) for v in saber.dicionario.variantes_valor})
    resultado: dict[str, list[int]] = {}
    for nome, padrao in padroes.items():
        # Sobre o texto inteiro, e nao linha a linha: sao 14 padroes por
        # ficheiro em vez de 14 por linha, e nenhum deles atravessa linhas.
        # O `in` primeiro: a regex com *lookbehind* e lenta, e a maior parte
        # das variantes nao esta na maior parte dos documentos.
        if nome not in texto:
            continue
        linhas =[texto.count("\n", 0, achado.start()) + 1 for achado in padrao.finditer(texto)]
        if linhas:
            resultado[nome] = linhas
    return resultado


def verificar(
    textos: dict[str, str],
    saber: Saber,
    permitidas: Permitidas,
    hoje: datetime.date,
) -> tuple[list[Achado], dict]:
    """Verifica os documentos. `textos` e {caminho relativo: conteudo}."""
    achados: list[Achado] = []
    todas = dict(saber.dicionario.variantes_nome)
    todas.update(saber.dicionario.variantes_valor)
    usadas: set[tuple[str, str]] = set()
    total = 0

    for ficheiro in sorted(textos):
        for nome, linhas in sorted(ocorrencias(textos[ficheiro], saber).items()):
            total += len(linhas)
            excepcao = permitidas.por_par.get((ficheiro, nome))
            if excepcao is None:
                for linha in linhas:
                    achados.append(Achado(ficheiro, linha, VARIANTE, todas[nome].mensagem()))
                continue
            usadas.add((ficheiro, nome))
            if excepcao.classe == "historica":
                texto_das_linhas = textos[ficheiro].split("\n")
                for linha in dict.fromkeys(linhas):
                    if not any(ancora in texto_das_linhas[linha - 1] for ancora in excepcao.ancoras):
                        achados.append(
                            Achado(
                                ficheiro,
                                linha,
                                VARIANTE,
                                f"{todas[nome].mensagem()} — a ocorrencia desta linha nao tem "
                                f"nenhuma das ancoras que {PERMITIDAS} declara para a citacao "
                                "historica: ou e um uso vivo, ou a ancora tem de ser actualizada",
                            )
                        )
            if len(linhas) != excepcao.ocorrencias:
                achados.append(
                    Achado(
                        ficheiro,
                        linhas[0],
                        VARIANTE,
                        f"{todas[nome].mensagem()} — {len(linhas)} ocorrencia(s) nas linhas "
                        f"{', '.join(str(l) for l in linhas)}, e {PERMITIDAS} declara "
                        f"{excepcao.ocorrencias}. Corrija o documento ou actualize a excepcao",
                    )
                )

    for excepcao in permitidas.entradas:
        par = (excepcao.ficheiro, excepcao.variante)
        if par not in usadas:
            achados.append(
                Achado(
                    excepcao.ficheiro,
                    0,
                    REGRA,
                    f"{PERMITIDAS} declara `{excepcao.variante}` neste ficheiro e ja nao ha "
                    "nenhuma ocorrencia: retire a excepcao",
                )
            )
        if excepcao.classe == "divida" and excepcao.expira_em and hoje > excepcao.expira_em:
            achados.append(
                Achado(
                    excepcao.ficheiro,
                    0,
                    REGRA,
                    f"a divida de `{excepcao.variante}` ({excepcao.origem}) venceu a "
                    f"{excepcao.expira_em}: {todas[excepcao.variante].mensagem()}. "
                    "Uma divida vencida falha o gate; corrija o documento",
                )
            )

    historicas = sum(e.ocorrencias for e in permitidas.entradas if e.classe == "historica")
    dividas = sum(e.ocorrencias for e in permitidas.entradas if e.classe == "divida")
    return achados, {"ocorrencias": total, "historicas": historicas, "dividas": dividas}
