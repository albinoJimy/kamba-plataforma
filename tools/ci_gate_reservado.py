#!/usr/bin/env python3
"""Gates reservados (5-8): falham por desenho, ate o seu ticket os ligar.

Os gates 5 a 8 existem no §4 do Engineering Standards — integracao, isolamento,
contratos e migracoes — e sao implementados pelos tickets que criam o que eles
testam. O KAM-002 reserva-lhes um *job* com nome, e esse job **falha**.

Nao e teimosia. A alternativa — um job que passa porque ainda nao ha nada para
testar — faz o pipeline parecer que cobre o que nao cobre, e nada obriga ninguem
a ligar o gate. Um job vermelho com o ticket no nome e um lembrete que nao se
perde.

A valvula e `ci/waivers.yaml`, com prazo de 30 dias e referencia a ADR ou
aprovacao: dispensa-se o gate enquanto o ticket nao chega, mas tem de se
revisitar a decisao dentro de um mes.
"""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))

from ci_waivers import ConfiguracaoIlegivel, WaiverInvalido, ler  # noqa: E402


def main(argv: list[str] | None = None) -> int:
    analisador = argparse.ArgumentParser(prog="ci_gate_reservado")
    analisador.add_argument("--root", type=Path, required=True)
    analisador.add_argument("--gate", required=True)
    analisador.add_argument("--nome", required=True)
    analisador.add_argument("--ticket", required=True)
    argumentos = analisador.parse_args(argv)

    try:
        waivers = ler(argumentos.root)
    except ConfiguracaoIlegivel as excepcao:
        # Codigo 2, e nao 1 (KAM-134). O `ConfiguracaoIlegivel` e **subclasse**
        # de `WaiverInvalido`, pelo que o `except` largo abaixo o apanhava
        # primeiro e devolvia 1 — e com isso o trabalho do KAM-136, que separou
        # «erro de configuracao» de «achado» precisamente para um ficheiro
        # ilegivel nao parecer um repositorio limpo, perdia-se neste leitor.
        print(f"ci_gate_reservado: erro de configuracao: {excepcao}", file=sys.stderr)
        return 2
    except WaiverInvalido as excepcao:
        print(f"ci_gate_reservado: {excepcao}", file=sys.stderr)
        return 1

    for waiver in waivers:
        # O `alvo` conta. Antes comparava-se so o `gate`, pelo que um waiver
        # cujo alvo era um pacote npm — `pkg:npm/coisa@1.0.0` — dispensava o
        # gate 5 inteiro. O `ci/waivers.yaml` diz que `alvo` e "o que
        # exactamente e dispensado" e que nunca e "tudo"; para um gate que
        # ainda nao existe, o unico alvo coerente e o proprio pipeline.
        alvo = str(waiver.get("alvo") or "").strip()
        if waiver["gate"] == str(argumentos.gate) and alvo not in (
            "pipeline",
            f"gate {argumentos.gate}",
            argumentos.nome,
        ):
            print(
                f"ci_gate_reservado: waiver do gate {argumentos.gate} tem "
                f"`alvo: {alvo or '(vazio)'}`, que nao dispensa o gate.\n"
                f"    Para dispensar um gate reservado, `alvo: pipeline`.",
                file=sys.stderr,
            )
            continue
        if waiver["gate"] == str(argumentos.gate):
            print(
                f"gate {argumentos.gate} ({argumentos.nome}): dispensado por "
                f"{waiver['adr_ou_aprovacao']} ate {waiver['expira_em']} "
                f"({waiver['autor']})"
            )
            return 0

    print(
        f"gate {argumentos.gate} NAO IMPLEMENTADO: {argumentos.nome}.\n"
        f"\n"
        f"  Este gate esta reservado e falha de proposito. E o **{argumentos.ticket}**\n"
        f"  que o implementa, porque e esse ticket que cria o que o gate testa.\n"
        f"\n"
        f"  Um job reservado que passasse em silencio fazia o pipeline parecer que\n"
        f"  cobre o que nao cobre, e nada obrigaria ninguem a liga-lo.\n"
        f"\n"
        f"  Para dispensar enquanto o ticket nao chega, acrescente a ci/waivers.yaml:\n"
        f"\n"
        f"      - gate: {argumentos.gate}\n"
        f"        alvo: pipeline\n"
        f"        adr_ou_aprovacao: aprovacao:<quem>@<AAAA-MM-DD>\n"
        f"        autor: <quem>\n"
        f"        razao: >-\n"
        f"          O {argumentos.ticket} ainda nao foi executado; o gate fica\n"
        f"          dispensado ate la e e revisto no fim do prazo.\n"
        f"        criado_em: <AAAA-MM-DD, hoje>\n"
        f"        expira_em: <AAAA-MM-DD, no maximo 30 dias depois do criado_em>\n",
        file=sys.stderr,
    )
    return 1


if __name__ == "__main__":
    raise SystemExit(main())
