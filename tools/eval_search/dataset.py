"""O *dataset* `golden_search` (KAM-064, `docs/tecnica/05` §14.1): ficheiros, divisao e PII.

    python -m eval_search.dataset escrever   # gera os ficheiros a partir da curadoria
    python -m eval_search.dataset check      # 0 se os ficheiros sao os da curadoria

A fonte e a curadoria em Python (`catalogos.py` e `consultas.py`); os ficheiros
em `eval/search/data/` sao o que o executor le, e o `check` recusa um ficheiro
editado a mao que a curadoria ja nao gera — pela razao do `dict_export --check`.

## Os ficheiros

* `eval/search/data/catalogos/<snapshot>.jsonl` — um produto por linha;
* `eval/search/data/golden_search/<snapshot>.jsonl` — uma consulta por linha, no
  formato do §14.1: `{qid, tenant, origem, texto, tags, restricoes, relevantes,
  nao_resolvivel}`, mais a `divisao`;
* `eval/search/data/golden_search/manifesto.json` — a versao, a origem, o
  consentimento, as contagens e a impressao de cada ficheiro.

## A divisao e fixa, e a afinacao nao le o teste

`dev` 70% / `teste` 30% pelo *hash* do `qid` (`divisao_de`): nao depende da
ordem do ficheiro, nem de quantas consultas ha, nem de uma semente. Dentro de
`afinacao()`, ler a divisao `teste` — ou o *dataset* inteiro — levanta
`LeituraDoTesteProibida` (criterio 3). Quem afina corre dentro do `with`.

## O *scanner* de PII

`pii_em(texto)` procura telefone, NIF, e-mail e nomes proprios. Um lance de 9
ou mais algarismos (com separadores) e a forma do telefone angolano sem
indicativo e e tambem a do NIF e do BI — o repositorio nao tem padrao canonico
de NIF (`PADRAO_DE_NIF = None` no detector do AGR) —, pelo que o *scanner* o
recusa sem distinguir. Os nomes sao uma lista de nomes proprios comuns em
Angola e em Portugal, sem os que sao tambem palavras de catalogo («rosa»,
«luz»): **nao e exaustiva**, e e por isso que o *dataset* e sintetico e nao
reescrito — o *scanner* e a segunda barreira, nao a primeira.
"""

from __future__ import annotations

import base64
import contextlib
import hashlib
import json
import re
import sys
import threading
import unicodedata
from collections.abc import Iterator, Sequence
from dataclasses import dataclass
from pathlib import Path
from typing import Final

from . import catalogos as catalogos_mod
from . import consultas as consultas_mod

RAIZ: Final = Path(__file__).resolve().parents[2]
DADOS: Final = RAIZ / "eval" / "search" / "data"
PASTA_DAS_CONSULTAS: Final = DADOS / "golden_search"
PASTA_DOS_CATALOGOS: Final = DADOS / "catalogos"
MANIFESTO: Final = PASTA_DAS_CONSULTAS / "manifesto.json"

#: A versao do *dataset* (SemVer). Sobe o *minor* quando entram consultas, o
#: *major* quando um grau muda de sentido.
VERSAO_DO_DATASET: Final = "1.0.0"

DEV: Final = "dev"
TESTE: Final = "teste"
#: A fraccao `dev`, em pontos percentuais (criterio 3).
PERCENTAGEM_DEV: Final = 70

ORIGENS: Final = frozenset({"texto", "voz"})

#: O consentimento usado. **Nenhum**, porque nenhuma consulta e de origem real:
#: e o que o criterio 4 pede que o ficheiro diga.
ORIGEM_DOS_DADOS: Final = {
    "origem": "sintetica",
    "fonte": "consultas e catalogos escritos por ops (KAM-064), §14.1 fonte 2",
    "conversas_reais": 0,
    "consentimento_especifico": "nenhum usado: nenhuma consulta de origem real",
    "nota": (
        "As conversas do concierge/H7 so entram depois de reescrita sintetica, "
        "remocao de identificadores e com consentimento especifico para "
        "avaliacao (ADR-018; E3, a confirmar por parecer). Enquanto o concierge "
        "nao gerar volume (KAM-109), o dataset e 100% sintetico."
    ),
    "uso": "so avaliacao e curadoria de dicionario; nunca treinar nem afinar modelos (ADR-018)",
}


class LeituraDoTesteProibida(RuntimeError):
    """A afinacao tentou ler a divisao `teste` (criterio 3)."""


class PiiNoDataset(ValueError):
    """O *scanner* encontrou um identificador num ficheiro do *dataset*."""


# ------------------------------------------------------------------ divisao


def divisao_de(qid: str) -> str:
    """`dev` ou `teste`, pelo *hash* do `qid`. Fixa: so depende do `qid`."""
    balde = int(hashlib.sha256(qid.encode("utf-8")).hexdigest()[:8], 16) % 100
    return DEV if balde < PERCENTAGEM_DEV else TESTE


_ESTADO = threading.local()


@contextlib.contextmanager
def afinacao() -> Iterator[None]:
    """Dentro deste bloco, ler o `teste` levanta. E onde a afinacao corre."""
    anterior = getattr(_ESTADO, "afinar", False)
    _ESTADO.afinar = True
    try:
        yield
    finally:
        _ESTADO.afinar = anterior


def em_afinacao() -> bool:
    return bool(getattr(_ESTADO, "afinar", False))


# ------------------------------------------------------------------ PII

#: Nove ou mais algarismos num lance, com ate tres separadores entre dois: o
#: telefone (`923 456 789`, `+244 923...`), o NIF e o BI. E o padrao do
#: `services/agr/tests/golden.py` (KAM-040), que ja guarda o outro *dataset*.
_LANCE_DE_ALGARISMOS: Final = re.compile(r"(?<![0-9])(?:[0-9][^\w\n]{0,3}){8,}[0-9](?![0-9])")
_EMAIL: Final = re.compile(r"[\w.+-]+@[\w-]+\.[\w.]+")
_NIF: Final = re.compile(r"\bnif\b")

#: Nomes proprios comuns, sem acentos e em minusculas. Ficam de fora os que sao
#: tambem palavras do catalogo ou da consulta («rosa», «luz», «gloria»).
NOMES_PROPRIOS: Final = frozenset(
    """
    joao maria manuel antonio jose francisco pedro paulo domingos isabel teresa
    joana ana fernando carlos miguel mariana beatriz sofia ines rui nuno tiago
    ricardo helena filomena adelaide eduardo augusto lourenco afonso albino
    armando celestino avelino graciano florinda josefa madalena feliciana
    esperanca kiala nzinga mbala ndombele lukeny kapinga nsimba tchissola
    nkosi mussa adao abel bernardo cristina daniel elsa fatima henrique ivone
    """.split()
)

_PALAVRA: Final = re.compile(r"[a-z]+")


def _sem_acentos(texto: str) -> str:
    decomposto = unicodedata.normalize("NFKD", texto.lower())
    return "".join(c for c in decomposto if not unicodedata.combining(c))


def pii_em(texto: str) -> list[str]:
    """Os achados de PII em `texto`, com o tipo e o excerto. Vazio = limpo."""
    achados: list[str] = []
    for lance in _LANCE_DE_ALGARISMOS.finditer(texto):
        achados.append(f"telefone_ou_nif:{lance.group(0)}")
    for email in _EMAIL.finditer(texto):
        achados.append(f"email:{email.group(0)}")
    simples = _sem_acentos(texto)
    if _NIF.search(simples):
        achados.append("nif:menciona")
    for palavra in _PALAVRA.findall(simples):
        if palavra in NOMES_PROPRIOS:
            achados.append(f"nome:{palavra}")
    return achados


def varrer(textos: Sequence[str]) -> list[str]:
    """Todos os achados de uma lista de textos (um ficheiro, linha a linha)."""
    return [achado for texto in textos for achado in pii_em(texto)]


# ------------------------------------------------------------------ geracao


def _qid(catalogo: str, posicao: int) -> str:
    return f"{catalogo}-q{posicao + 1:03d}"


def graus(consulta: consultas_mod.Consulta, produtos: Sequence[catalogos_mod.Produto]) -> dict[str, int]:
    """Os graus da anotacao A, pela regra escrita em `consultas.py`."""
    if consulta.nao_resolvivel:
        return {}
    saida: dict[str, int] = {}
    pedidos = set(consulta.atributos)
    for produto in produtos:
        if consulta.max_kz is not None and produto.preco_kz > consulta.max_kz:
            continue
        if consulta.min_kz is not None and produto.preco_kz < consulta.min_kz:
            continue
        if produto.tipo == consulta.tipo:
            saida[produto.sku] = 3 if pedidos <= produto.atributos else 2
        elif produto.tipo in consulta.substitutos:
            saida[produto.sku] = 1
    return saida


def registo(catalogo: str, posicao: int, consulta: consultas_mod.Consulta) -> dict[str, object]:
    """A linha do §14.1 de uma consulta."""
    produtos = catalogos_mod.CATALOGOS[catalogo]
    anotados = graus(consulta, produtos)
    if not consulta.nao_resolvivel:
        if not any(g >= 2 for g in anotados.values()):
            raise ValueError(f"{catalogo} #{posicao + 1}: nenhum produto de grau >= 2 para «{consulta.texto}»")
        if len(anotados) > 10:
            raise ValueError(f"{catalogo} #{posicao + 1}: {len(anotados)} relevantes nao cabem no recall@10")
    qid = _qid(catalogo, posicao)
    return {
        "qid": qid,
        "tenant": catalogos_mod.tenant_sintetico(catalogo),
        "catalogo": catalogos_mod.snapshot(catalogo),
        "origem": consulta.origem,
        "texto": consulta.texto,
        "tags": list(consulta.tags),
        "restricoes": {
            "max_preco_minor": None if consulta.max_kz is None else consulta.max_kz * 100,
            "min_preco_minor": None if consulta.min_kz is None else consulta.min_kz * 100,
        },
        "relevantes": [
            {"product_ref": ref, "grau": g}
            for ref, g in sorted(anotados.items(), key=lambda par: (-par[1], par[0]))
        ],
        "nao_resolvivel": consulta.nao_resolvivel,
        "divisao": divisao_de(qid),
    }


def impressao(texto: str) -> str:
    """O `sha256` de um texto em **base32**, e nao em hexadecimal.

    Um *hex* de 64 caracteres tem lances de nove algarismos com frequencia, e o
    *scanner* deste modulo e o `meta-sim` do *gate* 7 leem-nos como telefone.
    """
    return base64.b32encode(hashlib.sha256(texto.encode("utf-8")).digest()).decode("ascii").rstrip("=").lower()


def _linha(dados: dict[str, object]) -> str:
    return json.dumps(dados, ensure_ascii=False, sort_keys=False)


def gerar() -> dict[Path, str]:
    """Todos os ficheiros do *dataset*, com o conteudo. Nao escreve nada."""
    ficheiros: dict[Path, str] = {}
    impressoes: dict[str, str] = {}
    contagens: dict[str, dict[str, int]] = {}
    for catalogo, produtos in catalogos_mod.CATALOGOS.items():
        nome = catalogos_mod.snapshot(catalogo)
        skus = [p.sku for p in produtos]
        if len(set(skus)) != len(skus):
            raise ValueError(f"{catalogo}: sku repetido")
        texto_cat = "".join(
            _linha({"product_ref": p.sku, "sku": p.sku, "nome": p.nome,
                    "preco_minor": p.preco_minor, "preco_tipo": "fixo"}) + "\n"
            for p in produtos
        )
        linhas = [registo(catalogo, i, c) for i, c in enumerate(consultas_mod.CONSULTAS[catalogo])]
        texto_q = "".join(_linha(r) + "\n" for r in linhas)
        caminho_cat = PASTA_DOS_CATALOGOS / f"{nome}.jsonl"
        caminho_q = PASTA_DAS_CONSULTAS / f"{nome}.jsonl"
        ficheiros[caminho_cat] = texto_cat
        ficheiros[caminho_q] = texto_q
        for caminho, texto in ((caminho_cat, texto_cat), (caminho_q, texto_q)):
            impressoes[caminho.relative_to(RAIZ).as_posix()] = impressao(texto)
        contagens[nome] = {
            "produtos": len(produtos),
            "consultas": len(linhas),
            "dev": sum(r["divisao"] == DEV for r in linhas),
            "teste": sum(r["divisao"] == TESTE for r in linhas),
        }
    manifesto = {
        "dataset": "golden_search",
        "versao": VERSAO_DO_DATASET,
        "catalogos": catalogos_mod.VERSAO,
        **ORIGEM_DOS_DADOS,
        "divisao": f"{DEV} {PERCENTAGEM_DEV}% / {TESTE} {100 - PERCENTAGEM_DEV}% por sha256(qid)",
        "anotacao": {
            "a": "regra escrita (consultas.py), por ops",
            "b": None,
            "kappa": None,
            "nota": "a segunda anotacao (criterio 2) nao existe: kappa por medir",
        },
        "contagens": contagens,
        "ficheiros": impressoes,
    }
    ficheiros[MANIFESTO] = json.dumps(manifesto, ensure_ascii=False, indent=2) + "\n"
    achados = varrer(list(ficheiros.values()))
    if achados:
        raise PiiNoDataset(f"PII no dataset gerado: {achados[:5]}")
    return ficheiros


# ------------------------------------------------------------------ leitura


@dataclass(frozen=True)
class Registo:
    """Uma consulta lida do ficheiro."""

    qid: str
    tenant: str
    catalogo: str
    origem: str
    texto: str
    tags: frozenset[str]
    restricoes: dict[str, int | None]
    graus: dict[str, int]
    nao_resolvivel: bool
    divisao: str


def _ler_linhas(caminho: Path) -> list[dict[str, object]]:
    return [json.loads(linha) for linha in caminho.read_text(encoding="utf-8").splitlines() if linha.strip()]


def ler(divisao: str | None = None, *, pasta: Path = PASTA_DAS_CONSULTAS) -> list[Registo]:
    """As consultas, todas ou so de uma divisao.

    Dentro de `afinacao()`, so `dev` se pode ler: `teste` e `None` (que inclui
    o teste) levantam **antes** de abrir qualquer ficheiro.
    """
    if divisao not in (None, DEV, TESTE):
        raise ValueError(f"divisao desconhecida: {divisao!r}")
    if em_afinacao() and divisao != DEV:
        raise LeituraDoTesteProibida(
            "a afinacao so le a divisao dev (KAM-064, criterio 3)"
        )
    saida: list[Registo] = []
    for caminho in sorted(pasta.glob("*.jsonl")):
        for dados in _ler_linhas(caminho):
            qid = str(dados["qid"])
            # A divisao **recalcula-se** do qid e confere-se com a do ficheiro:
            # um ficheiro editado que pusesse uma consulta de teste em dev nao
            # passava a afinacao por isso.
            calculada = divisao_de(qid)
            if dados.get("divisao") != calculada:
                raise ValueError(f"{qid}: divisao {dados.get('divisao')!r} != {calculada!r}")
            if divisao is not None and calculada != divisao:
                continue
            if em_afinacao() and calculada != DEV:
                raise LeituraDoTesteProibida(f"{qid} e do teste")
            restricoes = dict(dados.get("restricoes") or {})
            saida.append(
                Registo(
                    qid=qid,
                    tenant=str(dados["tenant"]),
                    catalogo=str(dados["catalogo"]),
                    origem=str(dados["origem"]),
                    texto=str(dados["texto"]),
                    tags=frozenset(dados.get("tags") or ()),
                    restricoes=restricoes,
                    graus={str(r["product_ref"]): int(r["grau"]) for r in dados["relevantes"]},
                    nao_resolvivel=bool(dados["nao_resolvivel"]),
                    divisao=calculada,
                )
            )
    return saida


def ler_catalogo(snapshot: str, *, pasta: Path = PASTA_DOS_CATALOGOS) -> list[dict[str, object]]:
    """Os produtos de um *snapshot*, como o executor os semeia."""
    return _ler_linhas(pasta / f"{snapshot}.jsonl")


# ------------------------------------------------------------------ CLI


def verificar(base: Path = DADOS) -> list[str]:
    """As divergencias entre a curadoria e os ficheiros em `base`. Vazio = conforme."""
    problemas: list[str] = []
    esperados = {caminho.relative_to(DADOS): texto for caminho, texto in gerar().items()}
    for relativo, esperado in esperados.items():
        caminho = base / relativo
        if not caminho.is_file():
            problemas.append(f"falta {relativo.as_posix()}")
        elif caminho.read_text(encoding="utf-8") != esperado:
            problemas.append(f"difere da curadoria: {relativo.as_posix()}")
    for caminho in sorted(base.rglob("*")):
        if not caminho.is_file():
            continue
        relativo = caminho.relative_to(base)
        if relativo not in esperados:
            problemas.append(f"a curadoria nao gera {relativo.as_posix()}")
        achados = pii_em(caminho.read_text(encoding="utf-8"))
        if achados:
            problemas.append(f"PII em {relativo.as_posix()}: {achados[:3]}")
    return problemas


def main(argv: Sequence[str]) -> int:
    if list(argv) == ["escrever"]:
        for caminho, texto in gerar().items():
            caminho.parent.mkdir(parents=True, exist_ok=True)
            caminho.write_text(texto, encoding="utf-8", newline="\n")
        print(f"golden_search {VERSAO_DO_DATASET}: escrito")
        return 0
    if list(argv) == ["check"]:
        problemas = verificar()
        for problema in problemas:
            print(problema, file=sys.stderr)
        print(f"golden_search: {'conforme' if not problemas else f'{len(problemas)} problema(s)'}")
        return 0 if not problemas else 1
    print(__doc__, file=sys.stderr)
    return 2


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
