"""Interface de linha de comando do `ruleset_check` (KAM-137).

    python -m ruleset_check check    [--root .] [--transporte gh|http]
    python -m ruleset_check mostrar  [--root .] [--transporte gh|http]

`check` compara o ruleset efectivo com o espelho versionado. `mostrar` imprime o
ruleset efectivo normalizado, para quem quiser actualizar o espelho a mao depois
de uma alteracao deliberada.

Codigo de saida **0** = o GitHub aplica o que o ficheiro diz; **1** = divergem;
**2** = nao se conseguiu verificar (configuracao ilegivel, espelho ilegivel,
`gh` ausente, credencial sem autorizacao, API em baixo).

**A distincao entre 1 e 2 e o ticket inteiro.** Fail-closed inclui nao conseguir
verificar: um 2 nunca pode ser lido como «conforme». E a mesma regra que o gate
11 aplica a OSV — um gate de seguranca que passa quando nao consegue verificar e
um gate que mente.

**Esta verificacao nao e um gate de PR**, e nao corre no CI deste repositorio.
A razao esta em `docs/adr/ADR-L003-verificacao-do-ruleset.md`: a API dos
rulesets exige a permissao `administration`, que o `GITHUB_TOKEN` das Actions
nao tem, e qualquer outro token obrigaria a uma referencia `secrets.*` num
workflow — que e exactamente o que a regra `chave-estatica-no-ci` do gate 11
recusa.
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

from . import api, comparador, config

COMANDOS = ("check", "mostrar")


def _carregar(raiz: Path, transporte: str) -> tuple[config.Configuracao, dict, dict]:
    conf = config.ler(raiz)
    espelho = comparador.ler_espelho(raiz / conf.espelho)
    efectivo = api.obter(conf.caminho_da_api, transporte)
    return conf, espelho, efectivo


def main(argv: list[str] | None = None) -> int:
    analisador = argparse.ArgumentParser(prog="ruleset_check", description=__doc__)
    analisador.add_argument("comando", choices=COMANDOS)
    analisador.add_argument("--root", default=".", help="raiz do repositorio")
    analisador.add_argument(
        "--transporte", choices=api.TRANSPORTES, default="gh",
        help="`gh` (o token fica no porta-chaves do gh) ou `http` "
             f"(token em {api.NOME_DA_VARIAVEL})",
    )
    argumentos = analisador.parse_args(argv)
    raiz = Path(argumentos.root).resolve()

    try:
        conf, espelho, efectivo = _carregar(raiz, argumentos.transporte)
    except (config.ConfiguracaoInvalida, comparador.EspelhoInvalido) as erro:
        print(f"ruleset: {erro}", file=sys.stderr)
        return 2
    except api.ApiIndisponivel as erro:
        # Fail-closed inclui nao conseguir verificar.
        print(
            f"ruleset: {erro}\n"
            "    NAO SE CONSEGUIU LER O RULESET EFECTIVO — e isso e vermelho, nao verde.\n"
            "    Precisa de uma credencial com `administration: read` sobre o "
            f"repositorio ({conf_repositorio(raiz)}).\n"
            "    Ver docs/adr/ADR-L003-verificacao-do-ruleset.md.",
            file=sys.stderr,
        )
        return 2

    if argumentos.comando == "mostrar":
        normalizado = comparador.normalizar(efectivo)
        normalizado.pop("_desconhecidos", None)
        print(json.dumps(normalizado, ensure_ascii=False, indent=2, sort_keys=True, default=str))
        return 0

    try:
        divergencias = comparador.comparar(espelho, efectivo)
    except comparador.EspelhoInvalido as erro:
        print(f"ruleset: {erro}", file=sys.stderr)
        return 2

    cabecalho = (
        f"ruleset: {conf.repositorio} #{conf.ruleset_id} "
        f"contra {conf.espelho} (transporte `{argumentos.transporte}`)"
    )
    if not divergencias:
        contextos = _quantos_contextos(espelho)
        print(
            f"{cabecalho}\n"
            f"    conforme: {contextos} required check(s), bypass_actors vazio, "
            "enforcement activo."
        )
        return 0

    print(cabecalho, file=sys.stderr)
    print(
        f"ruleset: {len(divergencias)} divergencia(s) entre o que o GitHub aplica e o "
        f"que {conf.espelho} diz",
        file=sys.stderr,
    )
    for divergencia in divergencias:
        print(f"  - {divergencia}", file=sys.stderr)
    print(
        "\n    O espelho nao e aplicado por nada: so uma destas duas coisas repoe a "
        "coerencia —\n"
        "    repor o ruleset no GitHub, ou actualizar o ficheiro se a alteracao foi "
        "deliberada.\n"
        "    O procedimento esta em .github/rulesets/README.md.",
        file=sys.stderr,
    )
    return 1


def conf_repositorio(raiz: Path) -> str:
    """O repositorio, para a mensagem de erro — sem rebentar se a configuracao caiu."""
    try:
        return config.ler(raiz).repositorio
    except config.ConfiguracaoInvalida:  # pragma: no cover — defensivo
        return "?"


def _quantos_contextos(espelho: dict) -> int:
    for regra in espelho.get("rules", []):
        if isinstance(regra, dict) and regra.get("type") == "required_status_checks":
            return len((regra.get("parameters") or {}).get("required_status_checks") or [])
    return 0
