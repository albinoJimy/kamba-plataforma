"""Interface de linha de comando do `ruleset_check` (KAM-137).

    python -m ruleset_check check    [--root .] [--transporte gh|http]
    python -m ruleset_check mostrar  --repositorio <dono/repo> [--root .] [...]

`check` compara, **para cada alvo de `ci/ruleset.yaml`**, o ruleset efectivo
com o espelho versionado. Verde so quando todos os alvos estao conformes.

`mostrar` imprime o ruleset efectivo de um alvo **no formato exacto do
espelho** — os seis campos de politica, chaves ordenadas, dois espacos de
indentacao. A saida escreve-se directamente por cima do ficheiro de espelho
quando uma alteracao no GitHub foi deliberada, e o resultado e byte a byte o
que o comando de exportacao do `.github/rulesets/README.md` produz.

Codigo de saida **0** = todos os alvos aplicam o que o ficheiro diz; **1** =
pelo menos um diverge; **2** = nao se conseguiu verificar (configuracao
ilegivel, espelho ilegivel, `gh` ausente, credencial sem autorizacao, API em
baixo).

**A distincao entre 1 e 2 e o ticket inteiro.** Fail-closed inclui nao
conseguir verificar: um 2 nunca pode ser lido como «conforme». E a mesma regra
que o gate 11 aplica a OSV — um gate de seguranca que passa quando nao consegue
verificar e um gate que mente. E um repositorio **sem ruleset nenhum** nao e um
2: a leitura correu, e a resposta foi que a politica nao esta aplicada ali.
Isso e **1**.

**Esta verificacao nao e um gate de PR**, e nao corre no CI deste repositorio.
A razao esta em `docs/adr/ADR-L003-verificacao-do-ruleset.md`: a API dos
rulesets exige a permissao `administration`, que o `GITHUB_TOKEN` das Actions
nao tem, e qualquer outro token obrigaria a uma referencia ao cofre num
workflow — que e exactamente o que a regra `chave-estatica-no-ci` do gate 11
recusa.
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

from . import api, comparador, config, verificacao

COMANDOS = ("check", "mostrar")


def main(argv: list[str] | None = None) -> int:
    analisador = argparse.ArgumentParser(prog="ruleset_check", description=__doc__)
    analisador.add_argument("comando", choices=COMANDOS)
    analisador.add_argument("--root", default=".", help="raiz do repositorio")
    analisador.add_argument(
        "--transporte", choices=api.TRANSPORTES, default="gh",
        help="`gh` (o token fica no porta-chaves do gh) ou `http` "
             f"(token em {api.NOME_DA_VARIAVEL})",
    )
    analisador.add_argument(
        "--repositorio", default=None,
        help="para `mostrar`: qual dos alvos de ci/ruleset.yaml",
    )
    argumentos = analisador.parse_args(argv)
    raiz = Path(argumentos.root).resolve()

    try:
        alvos = config.ler(raiz)
    except config.ConfiguracaoInvalida as erro:
        print(f"ruleset: {erro}", file=sys.stderr)
        return 2

    if argumentos.comando == "mostrar":
        return _mostrar(raiz, alvos, argumentos)
    return _check(raiz, alvos, argumentos)


def _check(raiz: Path, alvos: list[config.Alvo], argumentos) -> int:
    print(
        f"ruleset: {len(alvos)} alvo(s) de {config.CAMINHO}, "
        f"transporte `{argumentos.transporte}`"
    )
    resultados: list[verificacao.Resultado] = []
    for alvo in alvos:
        try:
            resultados.append(verificacao.verificar(raiz, alvo, argumentos.transporte))
        except comparador.EspelhoInvalido as erro:
            print(f"ruleset: {alvo.repositorio}: {erro}", file=sys.stderr)
            return 2
        except api.ApiIndisponivel as erro:
            print(
                f"ruleset: {alvo.repositorio}: {erro}\n"
                "    NAO SE CONSEGUIU LER O RULESET EFECTIVO — e isso e vermelho, "
                "nao verde.\n"
                "    Precisa de uma credencial com `administration: read` sobre o "
                f"repositorio ({alvo.repositorio}).\n"
                "    Ver docs/adr/ADR-L003-verificacao-do-ruleset.md.",
                file=sys.stderr,
            )
            return 2

    codigo = 0
    for resultado in resultados:
        if resultado.conforme:
            print(
                f"  [ok]  {resultado.alvo.repositorio} #{resultado.ruleset_id} contra "
                f"{resultado.alvo.espelho}: {resultado.contextos_no_espelho} required "
                "check(s), bypass_actors vazio, enforcement activo."
            )
            continue
        codigo = 1
        print(
            f"  [--]  {resultado.alvo.repositorio} contra {resultado.alvo.espelho}: "
            f"{len(resultado.divergencias)} divergencia(s)",
            file=sys.stderr,
        )
        if resultado.alvo.razao:
            print(f"        porque esta na lista: {resultado.alvo.razao}", file=sys.stderr)
        for divergencia in resultado.divergencias:
            print(f"    - {divergencia}", file=sys.stderr)
        if resultado.ruleset_id is not None and resultado.alvo.ruleset_id is None:
            print(
                f"        (o `id` deste ruleset e {resultado.ruleset_id}; escreva-o em "
                f"{config.CAMINHO})",
                file=sys.stderr,
            )

    if codigo == 0:
        print(f"ruleset: conforme — {len(alvos)} alvo(s), 0 divergencias.")
        return 0

    print(
        "\n    O espelho nao e aplicado por nada: so uma destas duas coisas repoe a "
        "coerencia —\n"
        "    repor o ruleset no GitHub, ou actualizar o ficheiro se a alteracao foi "
        "deliberada.\n"
        "    O procedimento esta em .github/rulesets/README.md.",
        file=sys.stderr,
    )
    return 1


def _mostrar(raiz: Path, alvos: list[config.Alvo], argumentos) -> int:
    """O ruleset efectivo de um alvo, no formato exacto do espelho."""
    escolhidos = [a for a in alvos if a.repositorio == argumentos.repositorio]
    if not escolhidos:
        print(
            f"ruleset: `mostrar` precisa de --repositorio, um de "
            f"{[a.repositorio for a in alvos]}",
            file=sys.stderr,
        )
        return 2
    alvo = escolhidos[0]
    try:
        espelho = comparador.ler_espelho(raiz / alvo.espelho)
        resultado = verificacao.verificar(raiz, alvo, argumentos.transporte)
    except (comparador.EspelhoInvalido, api.ApiIndisponivel) as erro:
        print(f"ruleset: {alvo.repositorio}: {erro}", file=sys.stderr)
        return 2
    if resultado.efectivo is None:
        print(
            f"ruleset: {alvo.repositorio} nao tem um ruleset chamado "
            f"{espelho.get('name')!r}; nao ha o que mostrar",
            file=sys.stderr,
        )
        return 2
    print(formato_do_espelho(resultado.efectivo))
    return 0


def formato_do_espelho(bruto: dict) -> str:
    """Os seis campos de politica, como o ficheiro de espelho os guarda.

    E o mesmo que o comando de exportacao do `.github/rulesets/README.md`
    produz depois de reformatado, e ha um teste que o confronta byte a byte com
    o ficheiro real. Sem isto, a docstring convidava a usar o `mostrar` para
    actualizar o espelho e a saida nao servia para isso.
    """
    politica = {campo: bruto[campo] for campo in comparador.CAMPOS_DE_TOPO if campo in bruto}
    return json.dumps(politica, indent=2, ensure_ascii=False, sort_keys=True)
