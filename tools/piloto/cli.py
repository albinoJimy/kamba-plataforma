"""`python -m piloto` — os instrumentos da medicao do Piloto (KAM-109).

Seis subcomandos, e nenhum decide uma hipotese:

    sortear     a amostra de H8 de uma PME, com semente, e a folha de auditoria
    horas       valida o registo de horas do operador
    congelar    o manifesto `sha256` dos ficheiros de entrada da medicao
    verificar   recalcula o manifesto
    relatorio   o relatorio semanal de modelo fixo
    medir       H1, H6, H8 e H9 pelas regras pre-registadas, sobre entradas congeladas

## Os nomes dos ficheiros, que sao contrato com o KAM-110

    piloto_export.json        a exportacao (`db/piloto_export.py exportar`)
    h6_export.json            a saida do `h6-export exportar` (KAM-081)
    produtos_P01.csv ...      o catalogo de cada PME de onde o sorteio saiu (`piloto-export produtos`)
    auditoria_P01.csv ...     as folhas de H8 preenchidas, uma por PME
    piloto_congelado.json     o manifesto (`congelar`)
    piloto_resultados.json    a saida do `medir`, formato `kamba-piloto-resultados/1`

O `medir` le os nomes que lhe derem, mas recusa qualquer entrada que nao conste
do manifesto com o mesmo `sha256`.

## Codigos de saida

    0   feito
    1   achados (`verificar` com ficheiros mudados; `horas` com linhas recusadas)
    2   a entrada ou o pedido nao servem — inclui uma entrada nao congelada
"""

from __future__ import annotations

import argparse
import dataclasses
import datetime as dt
import hashlib
import json
import re
import sys
from pathlib import Path
from typing import Any

from . import exportacao as modulo_exportacao
from . import horas as modulo_horas
from . import regras
from . import relatorio as modulo_relatorio
from . import sorteio as modulo_sorteio

SAIDA_FEITO = 0
SAIDA_ACHADOS = 1
SAIDA_ERRO = 2

FORMATO_RESULTADOS = "kamba-piloto-resultados/1"
_FOLHA = re.compile(r"^auditoria_(P\d{2})\.csv$")


def _analisador() -> argparse.ArgumentParser:
    analisador = argparse.ArgumentParser(
        prog="python -m piloto",
        description="instrumentos da medicao do Piloto (KAM-109); a decisao e humana",
    )
    sub = analisador.add_subparsers(dest="comando", required=True)

    s = sub.add_parser("sortear", help="amostra de H8 e folha de auditoria")
    s.add_argument("--semente", required=True)
    s.add_argument("--pme", required=True)
    s.add_argument("--produtos", type=Path, required=True,
                   help="CSV produto_id,nome,preco_minor,disponivel")
    s.add_argument("--saida", type=Path)

    h = sub.add_parser("horas", help="valida o registo de horas do operador")
    h.add_argument("--registo", type=Path, required=True)

    c = sub.add_parser("congelar", help="manifesto sha256 dos ficheiros")
    c.add_argument("ficheiros", type=Path, nargs="+")
    c.add_argument("--saida", type=Path, required=True)

    v = sub.add_parser("verificar", help="recalcula o manifesto")
    v.add_argument("--manifesto", type=Path, required=True)

    r = sub.add_parser("relatorio", help="relatorio semanal")
    r.add_argument("--exportacao", type=Path, required=True)
    r.add_argument("--horas", type=Path, required=True)
    r.add_argument("--inicio", type=dt.date.fromisoformat, required=True,
                   help="o dia 1 do Piloto, do protocolo")
    r.add_argument("--semana", type=int, required=True)
    r.add_argument("--saida", type=Path)

    m = sub.add_parser("medir", help="H1, H6, H8 e H9 sobre entradas congeladas")
    m.add_argument("--exportacao", type=Path, required=True)
    m.add_argument("--manifesto", type=Path, required=True)
    m.add_argument("--mensalidade-minor", type=int, required=True,
                   help="a mensalidade do protocolo, em AOA minor")
    m.add_argument("--h6-export", type=Path)
    m.add_argument("--auditorias", type=Path, help="pasta com auditoria_PNN.csv")
    m.add_argument("--semente", help="a semente de H8 do protocolo; obrigatoria com --auditorias")
    m.add_argument("--saida", type=Path)
    return analisador


def _escrever(texto: str, saida: Path | None) -> None:
    if saida is None:
        sys.stdout.write(texto)
    else:
        saida.write_bytes(texto.encode("utf-8"))  # LF, sem o CRLF do modo texto


def _json(dados: Any) -> str:
    return json.dumps(dados, ensure_ascii=False, indent=2) + "\n"


def _sortear(a: argparse.Namespace) -> int:
    produtos = modulo_sorteio.ler_produtos(a.produtos)
    amostra = modulo_sorteio.sortear(a.semente, a.pme, produtos)
    _escrever(modulo_sorteio.folha(amostra), a.saida)
    print(f"{a.pme}: {len(amostra)} de {len(produtos)} produtos sorteados", file=sys.stderr)
    return SAIDA_FEITO


def _horas(a: argparse.Namespace) -> int:
    try:
        blocos = modulo_horas.ler(a.registo.read_text(encoding="utf-8"))
    except modulo_horas.RegistoInvalido as erro:
        print(f"piloto horas: {erro}", file=sys.stderr)
        return SAIDA_ACHADOS
    print(f"{len(blocos)} blocos, {sum(b.minutos for b in blocos)} minutos")
    return SAIDA_FEITO


def _congelar(a: argparse.Namespace) -> int:
    manifesto = modulo_exportacao.congelar(a.ficheiros, dt.datetime.now(dt.timezone.utc))
    _escrever(_json(manifesto), a.saida)
    return SAIDA_FEITO


def _verificar(a: argparse.Namespace) -> int:
    manifesto = json.loads(a.manifesto.read_text(encoding="utf-8"))
    achados = modulo_exportacao.verificar(manifesto, a.manifesto.parent)
    for achado in achados:
        print(achado)
    return SAIDA_ACHADOS if achados else SAIDA_FEITO


def _sha256(caminho: Path) -> str:
    return hashlib.sha256(caminho.read_bytes()).hexdigest()


def _relatorio(a: argparse.Namespace) -> int:
    exportacao = modulo_exportacao.ler(a.exportacao)
    blocos = modulo_horas.ler(a.horas.read_text(encoding="utf-8"))
    texto = modulo_relatorio.gerar(exportacao, blocos, a.inicio, a.semana, _sha256(a.exportacao))
    _escrever(texto, a.saida)
    return SAIDA_FEITO


def _exigir_congelado(manifesto: Path, ficheiro: Path) -> None:
    achados = modulo_exportacao.congelado(manifesto, ficheiro)
    if achados:
        raise modulo_exportacao.ExportacaoInvalida(
            "entrada nao congelada — nenhuma hipotese se mede sobre dados que podem mudar: "
            + "; ".join(achados)
        )


def _auditorias(pasta: Path, exportacao: modulo_exportacao.Exportacao, manifesto: Path,
                semente: str, fontes: dict[str, str]) -> list[regras.Auditoria]:
    """As folhas de H8, cada uma conferida contra o sorteio que a gerou.

    Para cada `auditoria_PNN.csv` tem de haver, na mesma pasta e no manifesto, o
    `produtos_PNN.csv` de onde o sorteio saiu. O sorteio refaz-se com a semente
    do protocolo, e a folha so conta se os produtos forem **exactamente** os
    sorteados, pela mesma ordem: uma folha com um item escolhido a mao, ou com
    menos itens do que a amostra, e recusada. Uma auditoria fora da 4.a semana
    conta, e sai marcada no detalhe — e um desvio a registar, nao um erro.
    """
    por_pme = {p.pme: p for p in exportacao.coorte}
    lidas = []
    for caminho in sorted(pasta.iterdir()):
        encontrado = _FOLHA.match(caminho.name)
        if not encontrado:
            continue
        pme = encontrado.group(1)
        lista = pasta / f"produtos_{pme}.csv"
        for ficheiro in (caminho, lista):
            _exigir_congelado(manifesto, ficheiro)
            fontes[ficheiro.name] = _sha256(ficheiro)
        sorteados = [p.produto_id for p in modulo_sorteio.sortear(
            semente, pme, modulo_sorteio.ler_produtos(lista))]
        dados = por_pme.get(pme)
        actualizacoes = None
        if dados is not None and dados.activada_em is not None:
            # As 4 semanas observadas: dias 0 a 27.
            actualizacoes = dados.soma(
                dados.activada_em, dados.activada_em + dt.timedelta(days=27),
                "actualizacoes_catalogo",
            )
        folha = modulo_sorteio.ler_folha(caminho.read_text(encoding="utf-8"), pme, actualizacoes)
        if list(folha.produtos) != sorteados:
            raise modulo_sorteio.FolhaInvalida(
                f"{caminho.name}: os produtos nao sao os do sorteio com esta semente "
                f"({len(folha.produtos)} na folha, {len(sorteados)} sorteados)"
            )
        auditoria = folha.auditoria
        if dados is not None and dados.activada_em is not None:
            semana = (auditoria.auditado_em - dados.activada_em).days // 7 + 1
            auditoria = dataclasses.replace(
                auditoria, fora_da_semana_4=semana != regras.H8_SEMANA_DA_AUDITORIA)
        lidas.append(auditoria)
    return lidas


def _medir(a: argparse.Namespace) -> int:
    _exigir_congelado(a.manifesto, a.exportacao)
    exportacao = modulo_exportacao.ler(a.exportacao)
    fontes = {a.exportacao.name: _sha256(a.exportacao)}

    h1 = regras.h1(exportacao, a.mensalidade_minor)
    if a.h6_export is None:
        h6: dict[str, Any] = {
            "limiar": f"custo <= 15% da mensalidade, em >= {regras.H6_AMOSTRA_MINIMA} conversas",
            "amostra_n": 0, "resultado": "NAO MEDIDO", "estado": regras.INCONCLUSIVA,
            "detalhe": {"motivo": "sem_h6_export"},
        }
    else:
        _exigir_congelado(a.manifesto, a.h6_export)
        fontes[a.h6_export.name] = _sha256(a.h6_export)
        bruto = json.loads(a.h6_export.read_text(encoding="utf-8"))
        h6 = regras.h6(exportacao, a.mensalidade_minor, bruto).como_dict()
    auditorias: list[regras.Auditoria] = []
    if a.auditorias is not None:
        if not a.semente:
            raise ValueError("--auditorias exige a --semente do protocolo: e com ela que as folhas se conferem")
        auditorias = _auditorias(a.auditorias, exportacao, a.manifesto, a.semente, fontes)
    h8 = regras.h8(exportacao, auditorias)
    h9 = regras.h9(exportacao)
    resultado = {
        "formato": FORMATO_RESULTADOS,
        "sintetico": exportacao.sintetico,
        "ultimo_dia": exportacao.ultimo_dia.isoformat(),
        "manifesto_sha256": _sha256(a.manifesto),
        "fontes": fontes,
        "aviso": "estados propostos pelas regras pre-registadas; a decisao e do fundador",
        "pre_condicoes": regras.pre_condicoes(exportacao),
        "hipoteses": {"H1": h1.como_dict(), "H6": h6, "H8": h8.como_dict(), "H9": h9.como_dict()},
    }
    _escrever(_json(resultado), a.saida)
    return SAIDA_FEITO


COMANDOS = {
    "sortear": _sortear,
    "horas": _horas,
    "congelar": _congelar,
    "verificar": _verificar,
    "relatorio": _relatorio,
    "medir": _medir,
}


def principal(argv: list[str] | None = None) -> int:
    for fluxo in (sys.stdout, sys.stderr):
        reconfigurar = getattr(fluxo, "reconfigure", None)
        if reconfigurar is not None:
            reconfigurar(encoding="utf-8", errors="replace")
    try:
        argumentos = _analisador().parse_args(argv)
    except SystemExit as saida:
        return SAIDA_ERRO if saida.code else SAIDA_FEITO
    try:
        return COMANDOS[argumentos.comando](argumentos)
    except (
        modulo_exportacao.ExportacaoInvalida,
        modulo_sorteio.FolhaInvalida,
        modulo_horas.RegistoInvalido,
        modulo_relatorio.RelatorioRecusado,
        ValueError,
        KeyError,
        OSError,
        json.JSONDecodeError,
    ) as erro:
        print(f"piloto {argumentos.comando}: {erro}", file=sys.stderr)
        return SAIDA_ERRO
