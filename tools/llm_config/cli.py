"""CLI do gerador de configuracao do proxy (KAM-030).

    python -m llm_config --root . escrever    gera llm/litellm.config.yaml e o lock
    python -m llm_config --root . check       confirma que os dois estao em dia

O `check` e o que corre no *lint*: o passo `aliases` do `lint_arch` chama-o. O
`escrever` e o que uma pessoa corre depois de mexer nos aliases — e, por desenho,
**nao** sobe a versao sozinho: subir a versao e a decisao que o criterio 7
protege, e uma ferramenta que a tomasse tornava o *gate* um enfeite.
"""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

from . import (
    ALIASES,
    CONFIG,
    LOCK,
    AliasesInvalidos,
    impressao,
    ler,
    render,
)


def _escrever_lf(caminho: Path, texto: str) -> None:
    """Escreve com LF. O `pathlib.write_text` poe CRLF em Windows."""
    caminho.parent.mkdir(parents=True, exist_ok=True)
    caminho.write_bytes(texto.encode("utf-8").replace(b"\r\n", b"\n"))


def _texto_do_lock(versao: str, hash_: str) -> str:
    return (
        "# GERADO por `python -m llm_config --root . escrever`. NAO EDITAR A MAO.\n"
        "#\n"
        f"# Fixa o par (versao, hash do conteudo) de {ALIASES}. O hash **nao**\n"
        "# inclui a `versao`: e isso que torna «mudou o conteudo e nao a versao»\n"
        "# detectavel, que e o criterio 7 do KAM-030.\n"
        "#\n"
        "# Mudar o modelo atras de um alias e um *release*: sobe-se a `versao` em\n"
        f"# {ALIASES}, corre-se `escrever`, e os dois ficheiros gerados entram no\n"
        "# mesmo *commit*. O Gate 13 (eval golden PT-AO) e a outra metade do\n"
        "# criterio e nasce com o KAM-040.\n"
        "\n"
        "version: 1\n"
        f'versao: "{versao}"\n'
        f'sha256: "{hash_}"\n'
    )


def escrever(raiz: Path) -> int:
    dados = ler(raiz)
    _escrever_lf(raiz / CONFIG, render(dados))
    _escrever_lf(raiz / LOCK, _texto_do_lock(str(dados["versao"]), impressao(dados)))
    print(f"llm_config: {CONFIG} e {LOCK} escritos (versao {dados['versao']})")
    return 0


def check(raiz: Path) -> list[str]:
    """Os achados. Lista vazia significa conforme."""
    from kamba_yaml import YamlSubsetError, load_file

    achados: list[str] = []
    dados = ler(raiz)
    versao = str(dados["versao"])

    caminho_config = raiz / CONFIG
    esperado = render(dados)
    if not caminho_config.is_file():
        achados.append(
            f"{CONFIG} nao existe. Corra `python -m llm_config --root . escrever`"
        )
    elif caminho_config.read_text(encoding="utf-8") != esperado:
        achados.append(
            f"{CONFIG} nao corresponde a {ALIASES}: o proxy serviria um modelo que o "
            "artefacto versionado nao nomeia. Corra "
            "`python -m llm_config --root . escrever`"
        )

    caminho_lock = raiz / LOCK
    if not caminho_lock.is_file():
        achados.append(f"{LOCK} nao existe. Corra `python -m llm_config --root . escrever`")
        return achados
    try:
        lock = load_file(caminho_lock)
    except YamlSubsetError as excepcao:
        achados.append(f"{LOCK}: ilegivel: {excepcao}")
        return achados

    agora = impressao(dados)
    guardado = str(lock.get("sha256", ""))
    versao_guardada = str(lock.get("versao", ""))
    if guardado != agora:
        if versao_guardada == versao:
            achados.append(
                f"o conteudo de {ALIASES} mudou e a `versao` continua em {versao}. "
                "Um alias e um artefacto comportamental: mudar o modelo atras dele "
                "exige *bump* SemVer (criterio 7 do KAM-030). Suba a versao e corra "
                "`python -m llm_config --root . escrever`"
            )
        else:
            achados.append(
                f"{LOCK} fixa a versao {versao_guardada} e {ALIASES} diz {versao}: "
                "o *lock* ficou atras. Corra `python -m llm_config --root . escrever`"
            )
    elif versao_guardada != versao:
        achados.append(
            f"{LOCK} e {ALIASES} discordam na versao ({versao_guardada} contra "
            f"{versao}) com o mesmo conteudo: uma das duas foi editada a mao"
        )
    return achados


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        prog="llm_config", description="Gerador da configuracao do proxy LiteLLM"
    )
    parser.add_argument("--root", type=Path, default=Path("."), help="raiz do repositorio")
    parser.add_argument("comando", choices=("escrever", "check"))
    args = parser.parse_args(argv)
    raiz = args.root.resolve()

    try:
        if args.comando == "escrever":
            return escrever(raiz)
        achados = check(raiz)
    except AliasesInvalidos as excepcao:
        print(f"llm_config: {ALIASES} invalido: {excepcao}", file=sys.stderr)
        return 2
    except OSError as excepcao:
        print(f"llm_config: erro de ficheiro: {excepcao}", file=sys.stderr)
        return 2

    if not achados:
        print("llm_config: aliases: conforme")
        return 0
    print(f"llm_config: aliases: {len(achados)} achado(s)", file=sys.stderr)
    for achado in achados:
        print(f"  - {achado}", file=sys.stderr)
    return 1


if __name__ == "__main__":
    raise SystemExit(main())
