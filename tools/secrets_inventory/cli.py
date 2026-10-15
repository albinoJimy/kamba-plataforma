"""Linha de comandos do verificador do inventario de segredos (KAM-010).

    python -m secrets_inventory --root <raiz> all

Alvos: `esquema`, `cobertura`, `uso`, `all`. Todos falham fechados: codigo de
saida 1 com a lista de erros, 0 e um resumo quando passam.

Corre-se de dentro de `tools/` (como o `lint_arch`), para que o `python -m`
ponha o directorio actual no `sys.path` sem mexer no `PYTHONPATH` — que quebra
em Windows, onde o separador e `;`.
"""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

from .canon import CanonError
from .inventario import carregar, cobertura, orfas
from .uso import verificar

ALVOS = ("esquema", "cobertura", "uso", "all")


def _imprimir(erros: list[str]) -> None:
    for erro in erros:
        print(f"  ERRO {erro}", file=sys.stderr)


def correr(raiz: Path, alvo: str) -> int:
    """Corre um alvo. Devolve o codigo de saida."""
    try:
        inventario, erros_esquema = carregar(raiz)
    except CanonError as erro:
        print(f"  ERRO canon ilegivel: {erro}", file=sys.stderr)
        return 1

    falhou = False

    if alvo in ("esquema", "all"):
        print(f"==> esquema ({len(inventario.segredos)} segredos, estado {inventario.estado!r})")
        if erros_esquema:
            _imprimir(erros_esquema)
            falhou = True
        else:
            print(f"    {len(inventario.segredos)} entradas validas")

    if alvo in ("cobertura", "all"):
        if erros_esquema and alvo == "cobertura":
            _imprimir(erros_esquema)
            return 1
        try:
            cobertas, em_falta = cobertura(raiz, inventario)
            sem_linha = orfas(raiz, inventario)
        except CanonError as erro:
            print(f"  ERRO canon ilegivel: {erro}", file=sys.stderr)
            return 1
        total = len(cobertas) + len(em_falta)
        pct = 100.0 if total == 0 else 100.0 * len(cobertas) / total
        print(f"==> cobertura de docs/tecnica/08 §5: {len(cobertas)}/{total} ({pct:.0f}%)")
        for linha in em_falta:
            print(f"  ERRO linha do doc 08 §5 sem entrada no inventario: {linha}", file=sys.stderr)
            falhou = True
        for segredo in sem_linha:
            print(
                f"  ERRO {segredo.id}: `fonte_08_5` {segredo.fonte_08_5!r} nao e nenhuma "
                "linha do doc 08 §5 (gralha?)",
                file=sys.stderr,
            )
            falhou = True

    if alvo in ("uso", "all"):
        achados, erros_uso = verificar(raiz, inventario)
        print(
            f"==> uso: {len(achados)} pedidos de segredo em "
            f"{len({a.caminho for a in achados})} ficheiros"
        )
        if erros_uso:
            _imprimir(erros_uso)
            falhou = True

    return 1 if falhou else 0


def main(argv: list[str] | None = None) -> int:
    analisador = argparse.ArgumentParser(
        prog="secrets_inventory",
        description="Verifica ops/secrets-inventory.yaml (KAM-010).",
    )
    analisador.add_argument("--root", default=".", help="raiz do repositorio")
    analisador.add_argument("alvo", choices=ALVOS, nargs="?", default="all")
    argumentos = analisador.parse_args(argv)
    raiz = Path(argumentos.root).resolve()
    codigo = correr(raiz, argumentos.alvo)
    if codigo == 0:
        print("secrets_inventory: verde.")
    return codigo
