"""O passo a seco do *gate* 6: enumerar, cobrir, lintar, e correr o que nao pede nada.

    python -c "import sys; sys.path.insert(0, 'security'); \\
               from isolation.cli import main; sys.exit(main(['--root', '.']))"

Corre em segundos, sem PostgreSQL, sem `node` e sem rede — pela mesma razao por
que o *gate* 6 ja corria o X-11 antes de levantar o contentor: se uma superficie
enumerada nao tem caso, nao vale levantar um PostgreSQL para o descobrir.

Quatro passos, por ordem de custo, e o primeiro que falhar para:

```text
1 enumeracao   as quatro superficies, com o sentinela de tipo vazio
2 cobertura    todo o item tem caso ou dispensa; nenhuma dispensa esta morta
3 lints        nenhum `SET app.tenant_id` sobrevive a transaccao
4 casos        os que declaram `precisa="nada"`
```

O codigo de saida e `0` so quando os quatro passam. Qualquer achado da `1`, e um
ficheiro de politica malformado da `2` — a distincao e a mesma dos outros
leitores de `ci/*.yaml` desta casa.
"""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

RAIZ = Path(__file__).resolve().parents[2]


def main(argumentos: list[str] | None = None) -> int:
    analisador = argparse.ArgumentParser(
        prog="isolation",
        description="Enumeracao, cobertura e lints do isolamento cruzado (KAM-066).",
    )
    analisador.add_argument("--root", default=str(RAIZ), help="a raiz do repositorio")
    analisador.add_argument(
        "--listar",
        action="store_true",
        help="imprime os itens enumerados, um por linha, e sai",
    )
    opcoes = analisador.parse_args(argumentos)
    raiz = Path(opcoes.root).resolve()

    from . import casos as registo  # noqa: PLC0415
    from . import enumeracao, lints  # noqa: PLC0415
    from .contexto import Contexto  # noqa: PLC0415
    from .corredor import correr, relatorio  # noqa: PLC0415

    # 1. Enumeracao.
    try:
        itens = enumeracao.enumerar(raiz)
    except enumeracao.EnumeracaoInvalida as erro:
        print(f"isolamento: a enumeracao recusou a arvore: {erro}", file=sys.stderr)
        return 2

    if opcoes.listar:
        for item in itens:
            marca = " (indeciso)" if item.indeciso else ""
            print(f"{item.id}\t{item.tipo}\t{item.onde}{marca}")
        return 0

    agrupado = enumeracao.por_tipo(itens)
    print("==> isolamento cruzado (KAM-066): enumeracao")
    for tipo, lista in agrupado.items():
        indecisos = sum(1 for item in lista if item.indeciso)
        extra = f" ({indecisos} indeciso(s))" if indecisos else ""
        print(f"    {tipo}: {len(lista)}{extra}")

    # 2. Cobertura.
    try:
        problemas = registo.cobertura(itens)
    except registo.RegistoInvalido as erro:
        print(f"isolamento: registo ou dispensas invalidos: {erro}", file=sys.stderr)
        return 2
    if problemas:
        print(
            f"    ERRO: {len(problemas)} superficie(s) sem caso, ou caso/dispensa "
            "morta:",
            file=sys.stderr,
        )
        for problema in problemas:
            print(f"      - {problema}", file=sys.stderr)
        return 1
    print(f"    cobertura: {len(itens)} item(s), 0 sem caso")

    # 3. Lints.
    print("==> isolamento cruzado: lint do `SET LOCAL`")
    try:
        achados = lints.verificar(raiz)
    except lints.LintInvalido as erro:
        print(f"isolamento: lista de excepcoes invalida: {erro}", file=sys.stderr)
        return 2
    if achados:
        print(f"    ERRO: {len(achados)} achado(s):", file=sys.stderr)
        for achado in achados:
            print(f"      - {achado}", file=sys.stderr)
        return 1
    print("    contexto de tenant: nenhum sobrevive a transaccao")

    # 4. Os casos que nao precisam de nada.
    print("==> isolamento cruzado: casos sem dependencias")
    resultado = correr(Contexto(raiz=raiz), precisa={"nada"})
    if resultado.achados:
        print(f"    ERRO: {len(resultado.achados)} achado(s):", file=sys.stderr)
        for achado in resultado.achados:
            print(f"      - {achado}", file=sys.stderr)
        return 1
    for linha in relatorio(resultado).splitlines():
        print(f"    {linha}")

    print(registo.relatorio(itens))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
