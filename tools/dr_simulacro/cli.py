"""Interface de linha de comandos do `dr_simulacro` (KAM-085).

    python -m dr_simulacro carimbar --folha F --cenario A --passo restauro inicio|fim
    python -m dr_simulacro carimbar --folha F --cenario A --passo dns nao_medido --nota "..."
    python -m dr_simulacro calcular --folha F --cenario A \
        [--confirmados C.csv --restaurados R.csv] [--json]
    python -m dr_simulacro extrapolar --bytes N --segundos S --para-gb 50 \
        [--rto-sem-restauro-min M] [--rede-mbps 100 --bytes-repositorio R] \
        [--bd-prevista-gb G] [--json]
    python -m dr_simulacro ensaio preparar|a|c|preparar-b|b1|b2|pid1|limpar --saida D

`carimbar` e o relogio comum do simulacro humano: quem executa carimba o
inicio e o fim de cada passo no mesmo terminal, em UTC, e o observador nao
precisa de acertar relogios. `calcular` e o que o *on-call* corre depois do simulacro humano: le a folha de
passos que ele preencheu, e os dois CSV de marcadores, e da o RTO por passo, o
composto e o RPO. `extrapolar` e a regra do criterio 6. `ensaio` corre o ensaio
local em Docker (ver `ensaio.py`).

Codigo de saida: 0 dentro dos alvos, 1 fora (RTO composto > 2 h, RPO > 5 min,
um buraco nos marcadores, ou replica necessaria), 2 folha ilegivel ou erro de
utilizacao. A distincao entre 1 e 2 e a dos outros *lints*: uma folha que nao se
le nao pode parecer um simulacro dentro do alvo.
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

from . import calculo, folha, marcadores

GB = 1_000_000_000


def _imprimir(carga: dict, como_json: bool) -> None:
    if como_json:
        print(json.dumps(carga, indent=2, ensure_ascii=False, default=str))
        return
    for chave, valor in carga.items():
        print(f"{chave}: {valor}")


def _comando_calcular(argumentos) -> int:
    lista = calculo.duracoes(folha.ler(argumentos.folha), argumentos.cenario)
    rto = calculo.rto(lista)
    carga = {
        "cenario": argumentos.cenario,
        "passos": {d.passo: (round(d.segundos, 1) if d.medido else f"nao_medido: {d.razao}")
                   for d in lista},
        "rto_medido_min": round(rto.medido_segundos / 60, 2),
        "rto_composto_min": round(rto.composto_segundos / 60, 2),
        "lacunas_entre_passos_min": round(rto.lacunas_segundos / 60, 2),
        "orcamento_no_composto": list(rto.orcamento_no_composto),
        "rto_dentro_do_alvo": rto.dentro_do_alvo,
        "repetir_cenario_a": rto.repetir_cenario_a,
    }
    dentro = rto.dentro_do_alvo
    if argumentos.confirmados and argumentos.restaurados:
        rpo = calculo.rpo(
            marcadores.ler_csv(argumentos.confirmados.read_text(encoding="utf-8")),
            marcadores.ler_csv(argumentos.restaurados.read_text(encoding="utf-8")),
        )
        carga.update({"rpo_segundos": round(rpo.segundos, 3), "marcadores_perdidos": rpo.perdidos,
                      "sem_confirmacao": rpo.sem_confirmacao, "buracos": list(rpo.buracos),
                      "rpo_dentro_do_alvo": rpo.dentro_do_alvo})
        dentro = dentro and rpo.dentro_do_alvo
    _imprimir(carga, argumentos.json)
    return 0 if dentro else 1


def _comando_carimbar(argumentos) -> int:
    f = folha.Folha(argumentos.folha, argumentos.cenario)
    if argumentos.evento == "nao_medido":
        carimbo = f.nao_medido(argumentos.passo, argumentos.nota)
    elif argumentos.evento == "inicio":
        carimbo = f.inicio(argumentos.passo, argumentos.nota)
    else:
        carimbo = f.fim(argumentos.passo, argumentos.nota)
    print(json.dumps(carimbo.como_dict(), ensure_ascii=False))
    return 0


def _comando_extrapolar(argumentos) -> int:
    """O restauro a outro tamanho: o maior entre o que o ensaio mediu e o que a rede impoe.

    O ensaio local le o repositorio do mesmo disco, e o debito que mede e de
    disco e CPU. Com `--rede-mbps` e `--bytes-repositorio`, acrescenta-se o
    termo de rede (os bytes do repositorio na mesma proporcao do tamanho), e o
    restauro e o **maior** dos dois — e isso, e nao o local, que o §8.2 orca.
    """
    alvo = int(argumentos.para_gb * GB)
    e = calculo.extrapolar(bytes_medidos=argumentos.bytes, segundos_medidos=argumentos.segundos,
                           bytes_alvo=alvo)
    restauro = e.segundos_extrapolados
    carga = {"debito_local_mbps": round(e.debito_mbps, 1),
             "restauro_local_extrapolado_min": round(restauro / 60, 2),
             "extrapolacao": "linear no tamanho"}
    if argumentos.rede_mbps is not None:
        if argumentos.bytes_repositorio is None:
            raise ValueError("--rede-mbps precisa de --bytes-repositorio")
        rede = calculo.restauro_em_rede_segundos(
            bytes_no_repositorio=int(argumentos.bytes_repositorio * alvo / argumentos.bytes),
            mbps=argumentos.rede_mbps)
        carga["restauro_rede_extrapolado_min"] = round(rede / 60, 2)
        restauro = max(restauro, rede)
    carga["restauro_extrapolado_min"] = round(restauro / 60, 2)
    necessaria = False
    if argumentos.rto_sem_restauro_min is not None:
        rto_extrapolado = argumentos.rto_sem_restauro_min * 60 + restauro
        decisao = calculo.decisao_replica(rto_extrapolado_segundos=rto_extrapolado,
                                          bd_prevista_gb=argumentos.bd_prevista_gb)
        carga.update({"rto_extrapolado_min": round(rto_extrapolado / 60, 2),
                      "replica_de_espera": decisao.estado, "razoes": list(decisao.razoes)})
        necessaria = decisao.estado == "necessaria"
    _imprimir(carga, argumentos.json)
    return 1 if necessaria else 0


def _comando_ensaio(argumentos) -> int:  # pragma: no cover — corre contra o Docker
    from . import ensaio

    raiz = Path(argumentos.root).resolve()
    e = ensaio.Ensaio(raiz, Path(argumentos.saida).resolve())
    fases = {
        "preparar": lambda: ensaio.preparar(e, argumentos.gib),
        "a": lambda: ensaio.cenario_a(e, argumentos.segundos),
        "c": lambda: ensaio.cenario_c(e),
        "preparar-b": lambda: ensaio.preparar_b(e),
        "b1": lambda: ensaio.cenario_b(e, "b1"),
        "b2": lambda: ensaio.cenario_b(e, "b2"),
        "pid1": lambda: ensaio.pid1(e),
        "limpar": lambda: ensaio.limpar(e),
    }
    resultado = fases[argumentos.fase]()
    if isinstance(resultado, dict):
        resumo = {k: v for k, v in resultado.items()
                  if k not in ("info", "contagens", "antes", "contencao")}
        print(json.dumps(resumo, indent=2, ensure_ascii=False, default=str))
    return 0


def construir_analisador() -> argparse.ArgumentParser:
    analisador = argparse.ArgumentParser(prog="dr_simulacro")
    analisador.add_argument("--root", default="..")
    sub = analisador.add_subparsers(dest="comando", required=True)

    k = sub.add_parser("carimbar", help="um carimbo na folha de passos, com o relogio local em UTC")
    k.add_argument("--folha", type=Path, required=True)
    k.add_argument("--cenario", required=True)
    k.add_argument("--passo", required=True)
    k.add_argument("evento", choices=folha.EVENTOS)
    k.add_argument("--nota", default="")

    c = sub.add_parser("calcular", help="RTO por passo e RPO de uma folha preenchida")
    c.add_argument("--folha", type=Path, required=True)
    c.add_argument("--cenario", required=True)
    c.add_argument("--confirmados", type=Path)
    c.add_argument("--restaurados", type=Path)
    c.add_argument("--json", action="store_true")

    x = sub.add_parser("extrapolar", help="o restauro a outro tamanho, e a regra da replica")
    x.add_argument("--bytes", type=int, required=True)
    x.add_argument("--segundos", type=float, required=True)
    x.add_argument("--para-gb", type=float, default=50)
    x.add_argument("--rto-sem-restauro-min", type=float,
                   help="o RTO composto sem a rubrica do restauro")
    x.add_argument("--rede-mbps", type=float)
    x.add_argument("--bytes-repositorio", type=int,
                   help="o que o repositorio ocupa para o tamanho medido")
    x.add_argument("--bd-prevista-gb", type=float)
    x.add_argument("--json", action="store_true")

    s = sub.add_parser("ensaio", help="o ensaio local em Docker")
    s.add_argument("fase", choices=("preparar", "a", "c", "preparar-b", "b1", "b2", "pid1",
                                          "limpar"))
    s.add_argument("--saida", required=True)
    s.add_argument("--gib", type=float, default=20)
    s.add_argument("--segundos", type=float, default=240)
    return analisador


def main(argv: list[str] | None = None) -> int:
    argumentos = construir_analisador().parse_args(argv)
    comandos = {"carimbar": _comando_carimbar, "calcular": _comando_calcular, "extrapolar": _comando_extrapolar,
                "ensaio": _comando_ensaio}
    try:
        return comandos[argumentos.comando](argumentos)
    except (folha.FolhaInvalida, ValueError, OSError) as erro:
        print(f"dr_simulacro: {erro}", file=sys.stderr)
        return 2
