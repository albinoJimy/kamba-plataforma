"""A exportacao do Piloto: forma, validacao e congelamento (KAM-109).

A exportacao e o JSON que o `db/piloto_export.py` escreve a partir da base, e e
a **unica** entrada das contas de H1, H8 e H9 e do relatorio semanal. A H6 le a
saida do `h6-export` (KAM-081), que e o instrumento que o bloco nomeia.

## A forma, `kamba-piloto-export/1`

    {
      "formato": "kamba-piloto-export/1",
      "sintetico": true | false,
      "ultimo_dia": "AAAA-MM-DD",        # o ultimo dia completo de Luanda lido
      "pmes": [
        {
          "pme": "P01",                  # o ordinal da coorte, e nunca o nome
          "tenant_id": "<uuid>",
          "na_coorte": true,             # false: saiu e foi substituida
          "saida": null | {"dia": "AAAA-MM-DD", "motivo": "sem_uso_semana_2" | ...},
          "activada_em": "AAAA-MM-DD" | null,
          "self_service": true | false | null,
          "dpa_aceite": true | false,
          "dias": {"AAAA-MM-DD": {"conversas": n, "accoes_dono": n,
                                   "actualizacoes_catalogo": n, "handoffs": n,
                                   "custo_llm_usd": "x", "custo_meta_usd": "y"}},
          "ciclos_pagos": [{"inicio": "AAAA-MM-DD", "valor_minor": n,
                             "moeda": "AOA", "via": "facilitador" | "ops"}]
        }
      ]
    }

Um dia sem actividade **nao aparece** em `dias`, e conta como zero: a base so
devolve dias com linhas, e preencher os outros era inventar a forma.

## Sem pessoas

A lista de campos e **fechada**, em cada nivel: um campo que nao conste dela
recusa a exportacao inteira, com codigo 2. E a mesma regra do `h6-export`, e
pela mesma razao — o sitio onde um `contact_id` ou um telefone entraria sem
ninguem reparar e o campo novo que alguem acrescenta ao SQL.

## Congelar

`congelar` escreve um manifesto com o `sha256` e o tamanho de cada ficheiro, e
`verificar` recalcula-os. O `medir` recusa uma exportacao cujo manifesto nao
bata, porque o bloco diz «nao declares nenhuma hipotese confirmada sem dados
exportados e congelados».
"""

from __future__ import annotations

import datetime as dt
import hashlib
import json
import re
from dataclasses import dataclass, field
from decimal import Decimal, InvalidOperation
from pathlib import Path
from typing import Any, Final

FORMATO: Final = "kamba-piloto-export/1"
FORMATO_MANIFESTO: Final = "kamba-piloto-congelado/1"

CAMPOS_DA_RAIZ: Final = frozenset({"formato", "sintetico", "ultimo_dia", "pmes"})
CAMPOS_DA_PME: Final = frozenset(
    {
        "pme",
        "tenant_id",
        "na_coorte",
        "saida",
        "activada_em",
        "self_service",
        "dpa_aceite",
        "dias",
        "ciclos_pagos",
    }
)
CAMPOS_DO_DIA: Final = frozenset(
    {
        "conversas",
        "accoes_dono",
        "actualizacoes_catalogo",
        "handoffs",
        "custo_llm_usd",
        "custo_meta_usd",
    }
)
CAMPOS_DO_CICLO: Final = frozenset({"inicio", "valor_minor", "moeda", "via"})
CAMPOS_DA_SAIDA: Final = frozenset({"dia", "motivo"})

#: Os motivos de saida da coorte. Lista fechada: um motivo em texto livre era
#: o sitio onde o nome do dono ou o telefone entravam.
MOTIVOS_DE_SAIDA: Final = frozenset({"sem_uso_semana_2", "desistiu", "excluida_protocolo"})

#: As vias de prova de pagamento que o protocolo aceita: o evento autenticado do
#: facilitador, ou a confirmacao de ops com dupla aprovacao (a conciliacao do
#: comprovativo bancario, `0055`).
VIAS_DE_PAGAMENTO: Final = frozenset({"facilitador", "ops"})

_PME: Final = re.compile(r"^P\d{2}$")
_UUID: Final = re.compile(r"^[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}$")


class ExportacaoInvalida(Exception):
    """A exportacao nao tem a forma `kamba-piloto-export/1`."""


@dataclass(frozen=True)
class Dia:
    conversas: int = 0
    accoes_dono: int = 0
    actualizacoes_catalogo: int = 0
    handoffs: int = 0
    custo_llm_usd: Decimal = Decimal(0)
    custo_meta_usd: Decimal = Decimal(0)


VAZIO: Final = Dia()


@dataclass(frozen=True)
class Ciclo:
    inicio: dt.date
    valor_minor: int
    moeda: str
    via: str


@dataclass(frozen=True)
class Saida:
    dia: dt.date
    motivo: str


@dataclass(frozen=True)
class Pme:
    pme: str
    tenant_id: str
    na_coorte: bool
    saida: Saida | None
    activada_em: dt.date | None
    self_service: bool | None
    dpa_aceite: bool
    dias: dict[dt.date, Dia] = field(default_factory=dict)
    ciclos_pagos: tuple[Ciclo, ...] = ()

    def dia(self, data: dt.date) -> Dia:
        return self.dias.get(data, VAZIO)

    def soma(self, inicio: dt.date, fim: dt.date, campo: str) -> Any:
        """A soma de `campo` nos dias `[inicio, fim]`, os dois inclusive."""
        total: Any = Decimal(0) if campo.startswith("custo_") else 0
        for data, dia in self.dias.items():
            if inicio <= data <= fim:
                total += getattr(dia, campo)
        return total


@dataclass(frozen=True)
class Exportacao:
    sintetico: bool
    ultimo_dia: dt.date
    pmes: tuple[Pme, ...]

    @property
    def coorte(self) -> tuple[Pme, ...]:
        return tuple(p for p in self.pmes if p.na_coorte)

    @property
    def substituidas(self) -> tuple[Pme, ...]:
        return tuple(p for p in self.pmes if not p.na_coorte)


# ------------------------------------------------------------------- leitura


def _campos(onde: str, objecto: Any, permitidos: frozenset[str]) -> dict[str, Any]:
    if not isinstance(objecto, dict):
        raise ExportacaoInvalida(f"{onde}: esperava um objecto")
    a_mais = sorted(set(objecto) - permitidos)
    if a_mais:
        raise ExportacaoInvalida(f"{onde}: campo(s) fora da lista fechada: {', '.join(a_mais)}")
    em_falta = sorted(permitidos - set(objecto))
    if em_falta:
        raise ExportacaoInvalida(f"{onde}: campo(s) em falta: {', '.join(em_falta)}")
    return objecto


def _data(onde: str, texto: Any) -> dt.date:
    if not isinstance(texto, str):
        raise ExportacaoInvalida(f"{onde}: esperava uma data AAAA-MM-DD")
    try:
        return dt.date.fromisoformat(texto)
    except ValueError:
        raise ExportacaoInvalida(f"{onde}: data invalida {texto!r}") from None


def _inteiro(onde: str, valor: Any) -> int:
    if isinstance(valor, bool) or not isinstance(valor, int) or valor < 0:
        raise ExportacaoInvalida(f"{onde}: esperava um inteiro nao negativo")
    return valor


def _dinheiro(onde: str, valor: Any) -> Decimal:
    """Um custo em USD, **em texto**: um `float` em JSON perde casas em silencio."""
    if not isinstance(valor, str):
        raise ExportacaoInvalida(f"{onde}: o custo vem em texto decimal, e nao como numero")
    try:
        decimal = Decimal(valor)
    except InvalidOperation:
        raise ExportacaoInvalida(f"{onde}: custo invalido {valor!r}") from None
    if not decimal.is_finite() or decimal < 0:
        raise ExportacaoInvalida(f"{onde}: custo invalido {valor!r}")
    return decimal


def _booleano(onde: str, valor: Any, nulo: bool = False) -> bool | None:
    if valor is None and nulo:
        return None
    if not isinstance(valor, bool):
        raise ExportacaoInvalida(f"{onde}: esperava verdadeiro ou falso")
    return valor


def _pme(indice: int, bruto: Any) -> Pme:
    onde = f"pmes[{indice}]"
    objecto = _campos(onde, bruto, CAMPOS_DA_PME)
    rotulo = objecto["pme"]
    if not isinstance(rotulo, str) or not _PME.match(rotulo):
        raise ExportacaoInvalida(f"{onde}: o ordinal e P01..P99, e nunca o nome da PME")
    onde = rotulo
    tenant_id = objecto["tenant_id"]
    if not isinstance(tenant_id, str) or not _UUID.match(tenant_id):
        raise ExportacaoInvalida(f"{onde}: tenant_id nao e um uuid")
    na_coorte = _booleano(f"{onde}.na_coorte", objecto["na_coorte"])
    saida = None
    if objecto["saida"] is not None:
        bruta = _campos(f"{onde}.saida", objecto["saida"], CAMPOS_DA_SAIDA)
        if bruta["motivo"] not in MOTIVOS_DE_SAIDA:
            raise ExportacaoInvalida(f"{onde}.saida: motivo fora da lista {sorted(MOTIVOS_DE_SAIDA)}")
        saida = Saida(_data(f"{onde}.saida.dia", bruta["dia"]), bruta["motivo"])
    if na_coorte == (saida is not None):
        raise ExportacaoInvalida(f"{onde}: uma PME fora da coorte tem saida, e uma na coorte nao")
    activada = objecto["activada_em"]
    dias: dict[dt.date, Dia] = {}
    if not isinstance(objecto["dias"], dict):
        raise ExportacaoInvalida(f"{onde}.dias: esperava um objecto")
    for texto, bruto_dia in objecto["dias"].items():
        local = f"{onde}.dias[{texto}]"
        data = _data(local, texto)
        dia = _campos(local, bruto_dia, CAMPOS_DO_DIA)
        dias[data] = Dia(
            conversas=_inteiro(f"{local}.conversas", dia["conversas"]),
            accoes_dono=_inteiro(f"{local}.accoes_dono", dia["accoes_dono"]),
            actualizacoes_catalogo=_inteiro(
                f"{local}.actualizacoes_catalogo", dia["actualizacoes_catalogo"]
            ),
            handoffs=_inteiro(f"{local}.handoffs", dia["handoffs"]),
            custo_llm_usd=_dinheiro(f"{local}.custo_llm_usd", dia["custo_llm_usd"]),
            custo_meta_usd=_dinheiro(f"{local}.custo_meta_usd", dia["custo_meta_usd"]),
        )
    if not isinstance(objecto["ciclos_pagos"], list):
        raise ExportacaoInvalida(f"{onde}.ciclos_pagos: esperava uma lista")
    ciclos = []
    for n, bruto_ciclo in enumerate(objecto["ciclos_pagos"]):
        local = f"{onde}.ciclos_pagos[{n}]"
        ciclo = _campos(local, bruto_ciclo, CAMPOS_DO_CICLO)
        if ciclo["via"] not in VIAS_DE_PAGAMENTO:
            raise ExportacaoInvalida(f"{local}: via fora da lista {sorted(VIAS_DE_PAGAMENTO)}")
        if ciclo["moeda"] != "AOA":
            raise ExportacaoInvalida(f"{local}: a mensalidade e em AOA")
        ciclos.append(
            Ciclo(
                _data(f"{local}.inicio", ciclo["inicio"]),
                _inteiro(f"{local}.valor_minor", ciclo["valor_minor"]),
                ciclo["moeda"],
                ciclo["via"],
            )
        )
    return Pme(
        pme=rotulo,
        tenant_id=tenant_id,
        na_coorte=bool(na_coorte),
        saida=saida,
        activada_em=None if activada is None else _data(f"{onde}.activada_em", activada),
        self_service=_booleano(f"{onde}.self_service", objecto["self_service"], nulo=True),
        dpa_aceite=bool(_booleano(f"{onde}.dpa_aceite", objecto["dpa_aceite"])),
        dias=dias,
        ciclos_pagos=tuple(sorted(ciclos, key=lambda c: c.inicio)),
    )


def de_objecto(bruto: Any) -> Exportacao:
    """A exportacao validada. Levanta `ExportacaoInvalida` a primeira falha."""
    raiz = _campos("raiz", bruto, CAMPOS_DA_RAIZ)
    if raiz["formato"] != FORMATO:
        raise ExportacaoInvalida(f"raiz: formato {raiz['formato']!r}, esperava {FORMATO!r}")
    if not isinstance(raiz["pmes"], list):
        raise ExportacaoInvalida("raiz.pmes: esperava uma lista")
    pmes = tuple(_pme(i, p) for i, p in enumerate(raiz["pmes"]))
    rotulos = [p.pme for p in pmes]
    if len(set(rotulos)) != len(rotulos):
        raise ExportacaoInvalida("raiz.pmes: ordinal repetido")
    tenants = [p.tenant_id for p in pmes]
    if len(set(tenants)) != len(tenants):
        raise ExportacaoInvalida("raiz.pmes: tenant repetido")
    return Exportacao(
        sintetico=bool(_booleano("raiz.sintetico", raiz["sintetico"])),
        ultimo_dia=_data("raiz.ultimo_dia", raiz["ultimo_dia"]),
        pmes=pmes,
    )


def ler(caminho: Path) -> Exportacao:
    try:
        bruto = json.loads(caminho.read_text(encoding="utf-8"))
    except json.JSONDecodeError as erro:
        raise ExportacaoInvalida(f"{caminho.name}: nao e JSON ({erro})") from None
    return de_objecto(bruto)


# --------------------------------------------------------------- congelar


def _sha256(caminho: Path) -> str:
    return hashlib.sha256(caminho.read_bytes()).hexdigest()


def congelar(ficheiros: list[Path], agora: dt.datetime) -> dict[str, Any]:
    """O manifesto: nome, tamanho e `sha256` de cada ficheiro, e o instante."""
    if not ficheiros:
        raise ExportacaoInvalida("nada para congelar")
    nomes = [f.name for f in ficheiros]
    if len(set(nomes)) != len(nomes):
        raise ExportacaoInvalida("dois ficheiros com o mesmo nome: o manifesto identifica-os pelo nome")
    return {
        "formato": FORMATO_MANIFESTO,
        "congelado_em": agora.astimezone(dt.timezone.utc).isoformat(timespec="seconds"),
        "ficheiros": [
            {"nome": f.name, "bytes": f.stat().st_size, "sha256": _sha256(f)}
            for f in sorted(ficheiros, key=lambda f: f.name)
        ],
    }


def verificar(manifesto: dict[str, Any], pasta: Path) -> list[str]:
    """Os ficheiros do manifesto que faltam ou mudaram. Vazio e conforme."""
    if not isinstance(manifesto, dict) or manifesto.get("formato") != FORMATO_MANIFESTO:
        return [f"manifesto sem o formato {FORMATO_MANIFESTO}"]
    achados = []
    entradas = manifesto.get("ficheiros")
    if not isinstance(entradas, list) or not entradas:
        return ["manifesto sem ficheiros"]
    for entrada in entradas:
        nome = entrada.get("nome") if isinstance(entrada, dict) else None
        if not isinstance(nome, str) or "/" in nome or "\\" in nome or nome in ("", ".", ".."):
            achados.append(f"entrada invalida no manifesto: {entrada!r}")
            continue
        caminho = pasta / nome
        if not caminho.is_file():
            achados.append(f"{nome}: em falta")
        elif _sha256(caminho) != entrada.get("sha256"):
            achados.append(f"{nome}: o sha256 nao bate — o ficheiro mudou depois de congelado")
    return achados


def congelado(manifesto_caminho: Path, ficheiro: Path) -> list[str]:
    """Achados se `ficheiro` nao esta congelado pelo manifesto em `manifesto_caminho`."""
    try:
        manifesto = json.loads(manifesto_caminho.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as erro:
        return [f"manifesto ilegivel: {erro}"]
    achados = verificar(manifesto, manifesto_caminho.parent)
    nomes = {
        e.get("nome") for e in manifesto.get("ficheiros", []) if isinstance(e, dict)
    } if isinstance(manifesto, dict) else set()
    if ficheiro.name not in nomes:
        achados.append(f"{ficheiro.name}: nao consta do manifesto")
    elif ficheiro.resolve().parent != manifesto_caminho.resolve().parent:
        achados.append(f"{ficheiro.name}: nao esta na pasta do manifesto")
    return achados
