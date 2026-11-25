"""O resumo do piloto: a interface declarada com o KAM-109 e o KAM-106.

Os ficheiros de saída do KAM-109 ainda não existem na `main` quando este pacote
se escreve, e por isso a interface **declara-se aqui**, no bloco KAM-110 e no
`README.md` deste pacote, em vez de se adivinhar. É um JSON de **esquema
fechado**, e a razão de ser fechado é dupla:

1. **Não há texto livre.** Só números, booleanos, `null`, caminhos e um *hash*.
   Um campo de texto livre é por onde entra o conteúdo de uma conversa ou um
   telefone num pacote que se partilha com três papéis.
2. **Não há campo de pista.** Os meses de pista, o capital e o ponto de paragem
   são do fundador (bloco KAM-110, critério D) e escrevem-se à mão no memorando.
   Uma chave fora do esquema — `pista`, `meses_de_pista`, o que for — recusa a
   entrada inteira, em vez de ser ignorada em silêncio.

Todas as chaves são opcionais menos `forma` e `sintetico`. Uma chave que falta
dá «por medir» no pacote, e **nunca** uma conclusão positiva.
"""

from __future__ import annotations

import json
import re
from dataclasses import dataclass, field
from pathlib import Path

FORMA = 1

#: Os itens da Carta §5 que se declaram por evidência externa. Os que derivam das
#: hipóteses (P2, P3, F3) **não** estão aqui, e declará-los é recusado: um item
#: que o pacote calcula do Registo não se sobrepõe por um JSON.
ITENS_DECLARAVEIS = (
    "P1", "F1", "F2", "F4", "F5",
    "C1", "C2", "C3", "C4", "C5", "C6", "C7",
    "N1", "N2", "N3",
)

ESTADOS_DE_ITEM = ("satisfeito", "nao_satisfeito")

_CAMINHO = re.compile(r"[A-Za-z0-9_][A-Za-z0-9_./-]*")
_SHA256 = re.compile(r"[0-9a-f]{64}")
_MOEDA = re.compile(r"[A-Z]{3}")

_CHAVES = {
    "forma", "sintetico", "exportacao", "exportacao_sha256", "semana_do_gate",
    "pagantes_recorrentes",
    "canal_comercial_repetivel", "custo_por_pme_minor", "moeda", "carta5",
}


class EntradaInvalida(ValueError):
    """O resumo não serve. Sai com o código 2."""


@dataclass(frozen=True)
class Item:
    estado: str
    evidencia: str | None


@dataclass(frozen=True)
class Resumo:
    sintetico: bool
    exportacao: str | None = None
    exportacao_sha256: str | None = None
    semana_do_gate: int | None = None
    pagantes_recorrentes: int | None = None
    canal_comercial_repetivel: bool | None = None
    custo_por_pme_minor: int | None = None
    moeda: str | None = None
    carta5: dict[str, Item] = field(default_factory=dict)


VAZIO = Resumo(sintetico=False)


def _inteiro(dados: dict, chave: str) -> int | None:
    valor = dados.get(chave)
    if valor is None:
        return None
    # `bool` é subclasse de `int` em Python: `true` não é uma contagem.
    if isinstance(valor, bool) or not isinstance(valor, int) or valor < 0:
        raise EntradaInvalida(f"{chave}: {valor!r} não é um inteiro não negativo")
    return valor


def _caminho(valor: object, onde: str) -> str:
    if (
        not isinstance(valor, str)
        or not _CAMINHO.fullmatch(valor)
        or ".." in valor.split("/")
    ):
        raise EntradaInvalida(
            f"{onde}: {valor!r} não é um caminho relativo à raiz do repositório"
        )
    return valor


def validar(dados: object) -> Resumo:
    if not isinstance(dados, dict):
        raise EntradaInvalida("o resumo é um objecto JSON")
    estranhas = sorted(set(dados) - _CHAVES)
    if estranhas:
        raise EntradaInvalida(
            f"chaves fora do esquema: {', '.join(estranhas)}. O esquema é fechado; "
            "os números de pista escrevem-se à mão no memorando, pelo fundador"
        )
    if dados.get("forma") != FORMA:
        raise EntradaInvalida(f"forma: {dados.get('forma')!r}, e este gerador lê a {FORMA}")
    sintetico = dados.get("sintetico")
    if not isinstance(sintetico, bool):
        raise EntradaInvalida("sintetico: obrigatório, e verdadeiro ou falso")

    exportacao = dados.get("exportacao")
    if exportacao is not None:
        exportacao = _caminho(exportacao, "exportacao")
    sha = dados.get("exportacao_sha256")
    if sha is not None and (not isinstance(sha, str) or not _SHA256.fullmatch(sha)):
        raise EntradaInvalida("exportacao_sha256: 64 caracteres hexadecimais minúsculos")
    if (exportacao is None) != (sha is None):
        raise EntradaInvalida(
            "exportacao e exportacao_sha256 vêm juntos: uma exportação sem *hash* "
            "não está congelada, e um *hash* sem ficheiro não diz de quê"
        )

    canal = dados.get("canal_comercial_repetivel")
    if canal is not None and not isinstance(canal, bool):
        raise EntradaInvalida("canal_comercial_repetivel: verdadeiro, falso ou null")

    custo = _inteiro(dados, "custo_por_pme_minor")
    moeda = dados.get("moeda")
    if (custo is None) != (moeda is None):
        raise EntradaInvalida("custo_por_pme_minor e moeda vêm juntos")
    if moeda is not None and (not isinstance(moeda, str) or not _MOEDA.fullmatch(moeda)):
        raise EntradaInvalida(f"moeda: {moeda!r} não é um código ISO 4217")

    carta5: dict[str, Item] = {}
    # `is None`, e não `or {}`: uma lista vazia é falsa e passava por omissão.
    bruto = dados.get("carta5")
    if bruto is None:
        bruto = {}
    if not isinstance(bruto, dict):
        raise EntradaInvalida("carta5: um objecto por item")
    for chave, valor in bruto.items():
        if chave not in ITENS_DECLARAVEIS:
            raise EntradaInvalida(
                f"carta5.{chave}: não é declarável. Os itens que derivam das "
                f"hipóteses calculam-se do Registo; os declaráveis são "
                f"{', '.join(ITENS_DECLARAVEIS)}"
            )
        if not isinstance(valor, dict) or set(valor) - {"estado", "evidencia"}:
            raise EntradaInvalida(f"carta5.{chave}: só `estado` e `evidencia`")
        estado = valor.get("estado")
        if estado not in ESTADOS_DE_ITEM:
            raise EntradaInvalida(f"carta5.{chave}.estado: um de {ESTADOS_DE_ITEM}")
        evidencia = valor.get("evidencia")
        if evidencia is not None:
            evidencia = _caminho(evidencia, f"carta5.{chave}.evidencia")
        carta5[chave] = Item(estado, evidencia)

    return Resumo(
        sintetico=sintetico,
        exportacao=exportacao,
        exportacao_sha256=sha,
        semana_do_gate=_inteiro(dados, "semana_do_gate"),
        pagantes_recorrentes=_inteiro(dados, "pagantes_recorrentes"),
        canal_comercial_repetivel=canal,
        custo_por_pme_minor=custo,
        moeda=moeda,
        carta5=carta5,
    )


def ler(caminho: Path) -> Resumo:
    try:
        dados = json.loads(caminho.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as erro:
        raise EntradaInvalida(f"{caminho}: {erro}") from erro
    return validar(dados)
