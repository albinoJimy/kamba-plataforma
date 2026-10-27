"""Gera as tabelas do relatorio a partir de `resultados/resultados.json`.

    python spikes/medusa-d3/relatar.py                      # imprime
    python spikes/medusa-d3/relatar.py --escrever           # preenche o relatorio

Existe por uma razao de metodo e nao de conveniencia: **o relatorio nao deve ter
numeros escritos a mao**. Entre a medicao e o documento ha uma transcricao, e e
nessa transcricao que um p99 de 19,7 s vira «cerca de 20 s» e um «38 de 60 casos
medidos» vira «60 casos». As tabelas do §5 e do §6 saem daqui, dos ficheiros que
o harness escreveu, e quem quiser conferir corre isto outra vez.

Os marcadores no `docs/spikes/KAM-041-medusa.md` sao comentarios HTML
(`<!-- TABELA-DOS-CRITERIOS -->`); o conteudo gerado fica entre o marcador e o
marcador de fecho, e reescrever e idempotente.
"""

from __future__ import annotations

import argparse
import json
import re
import sys
from pathlib import Path

AQUI = Path(__file__).resolve().parent
RAIZ = AQUI.parents[1]
RESULTADOS = AQUI / "resultados" / "resultados.json"
ISO = AQUI / "resultados" / "iso.json"
RELATORIO = RAIZ / "docs" / "spikes" / "KAM-041-medusa.md"

MARCA = {
    "passa": "**verde**",
    "falha": "**VERMELHO**",
    "nao_verificado": "**NÃO VERIFICADO**",
}


def tabela_dos_criterios(dados: dict) -> str:
    linhas = [
        "| ID | Critério | Limiar | Tipo | Resultado | O que se mediu |",
        "|---|---|---|---|---|---|",
    ]
    for criterio in dados["criterios"]:
        medido = criterio["medido"].replace("|", "\\|")
        linhas.append(
            f"| {criterio['id']} | {criterio['criterio']} | {criterio['limiar']} "
            f"| {criterio['tipo']} | {MARCA[criterio['estado']]} | {medido} |"
        )
    return "\n".join(linhas)


def tabela_iso(casos: list[dict]) -> str:
    """Resumo por superficie, e a lista dos que nao passaram."""
    import collections
    import re

    da_matriz = [c for c in casos if re.match(r"^ISO-\d{2}$", c["id"])]
    por_superficie: dict[str, collections.Counter] = {}
    for caso in da_matriz:
        por_superficie.setdefault(caso["superficie"], collections.Counter())[
            caso["estado"]
        ] += 1

    linhas = [
        "| Superfície | Casos | Verdes | Vermelhos | Não verificados |",
        "|---|---|---|---|---|",
    ]
    for superficie, contagem in por_superficie.items():
        total = sum(contagem.values())
        linhas.append(
            f"| {superficie} | {total} | {contagem['passa']} "
            f"| {contagem['falha']} | {contagem['nao_verificado']} |"
        )
    total_geral = collections.Counter(c["estado"] for c in da_matriz)
    linhas.append(
        f"| **Total** | **{len(da_matriz)}** | **{total_geral['passa']}** "
        f"| **{total_geral['falha']}** | **{total_geral['nao_verificado']}** |"
    )

    extras = [c for c in casos if not re.match(r"^ISO-\d{2}$", c["id"])]
    corpo = ["\n".join(linhas)]
    if extras:
        corpo.append(
            "\nSondas **fora da contagem** (medem-se, mas não são linhas da "
            "matriz do §4.4 e por isso não contam para os 60 casos do AC-1):\n"
        )
        for caso in extras:
            corpo.append(
                f"- `{caso['id']}` — {caso['cenario']}: {MARCA[caso['estado']]}, "
                f"{caso['observado']}"
            )

    nao_passaram = [c for c in da_matriz if c["estado"] != "passa"]
    if nao_passaram:
        corpo.append("\n### Os casos que não passaram\n")
        for caso in nao_passaram:
            corpo.append(
                f"**`{caso['id']}` — {MARCA[caso['estado']]}** "
                f"({caso['superficie']})\n\n"
                f"- Cenário: {caso['cenario']}\n"
                f"- Esperado: {caso['esperado']}\n"
                f"- Observado: {caso['observado']}\n"
                f"- Evidência: {caso['evidencia']}\n"
            )
    return "\n".join(corpo)


def substituir(texto: str, marcador: str, conteudo: str) -> str:
    """Poe `conteudo` depois do marcador, substituindo o que lá estava."""
    abre = f"<!-- {marcador} -->"
    fecha = f"<!-- /{marcador} -->"
    if abre not in texto:
        raise SystemExit(f"o relatorio nao tem o marcador {abre}")
    antes, resto = texto.split(abre, 1)
    depois = resto.split(fecha, 1)[1] if fecha in resto else resto
    return f"{antes}{abre}\n\n{conteudo}\n\n{fecha}{depois}"


def main(argv: list[str] | None = None) -> int:
    analisador = argparse.ArgumentParser(prog="relatar")
    analisador.add_argument("--escrever", action="store_true",
                            help="preenche os marcadores do relatorio")
    argumentos = analisador.parse_args(argv)

    if not RESULTADOS.is_file():
        print(f"nao ha {RESULTADOS}. Corre o harness primeiro.", file=sys.stderr)
        return 2
    dados = json.loads(RESULTADOS.read_text(encoding="utf-8"))
    casos = json.loads(ISO.read_text(encoding="utf-8")) if ISO.is_file() else []

    criterios = tabela_dos_criterios(dados)
    matriz = tabela_iso(casos)
    passo3 = resposta_do_passo3(dados)

    if not argumentos.escrever:
        print(criterios)
        print()
        print(matriz)
        print()
        print(passo3)
        return 0

    texto = RELATORIO.read_text(encoding="utf-8")
    # **Todos os marcadores do relatorio, e a lista e conferida.** A primeira
    # versao preenchia dois e deixava o terceiro — o nó que decide a D3 — em
    # branco, sem erro nenhum. Um marcador por preencher e um erro.
    marcadores = {
        "TABELA-DOS-CRITERIOS": criterios,
        "MATRIZ-ISO": matriz,
        "DECISAO-PASSO3": passo3,
    }
    presentes = {m for m in re.findall(r"<!-- ([A-Z0-9-]+) -->", texto)
                 if not m.startswith("/")}
    em_falta = presentes - set(marcadores)
    if em_falta:
        raise SystemExit(
            f"o relatorio tem marcador(es) que este guiao nao preenche: "
            f"{', '.join(sorted(em_falta))}. Um marcador por preencher deixa o "
            "relatorio com uma lacuna silenciosa."
        )
    for marcador, conteudo in marcadores.items():
        texto = substituir(texto, marcador, conteudo)
    RELATORIO.write_text(texto, encoding="utf-8")
    print(f"{RELATORIO} actualizado a partir de {RESULTADOS}")
    return 0


def resposta_do_passo3(dados: dict) -> str:
    """O nó `AC-1..AC-7 todos verdes?` da árvore do §4.5, respondido pelos números.

    Este texto é gerado e não escrito à mão de propósito: é a resposta que
    decide a D3, e é a que mais tentação há de arredondar.
    """
    import collections

    bloqueantes = [c for c in dados["criterios"]
                   if c["id"] in ("AC-1", "AC-2", "AC-3", "AC-4", "AC-5", "AC-6", "AC-7")]
    contagem = collections.Counter(c["estado"] for c in bloqueantes)
    vermelhos = [c for c in bloqueantes if c["estado"] == "falha"]
    nao_medidos = [c for c in bloqueantes if c["estado"] == "nao_verificado"]

    if not vermelhos and not nao_medidos:
        return (
            "**Sim.** Os sete critérios bloqueantes foram medidos e estão verdes "
            f"({contagem['passa']} de 7). A árvore segue para o passo 4."
        )

    def lista(criterios: list) -> str:
        nomes = [f"`{c['id']}`" for c in criterios]
        if len(nomes) == 1:
            return nomes[0]
        return ", ".join(nomes[:-1]) + " e " + nomes[-1]

    linhas = ["**Não.** Dos sete bloqueantes: "
              f"{contagem['passa']} medido(s) e verde(s), "
              f"{len(vermelhos)} vermelho(s), {len(nao_medidos)} não "
              "verificado(s)."]
    if vermelhos:
        verbo = "ficou" if len(vermelhos) == 1 else "ficaram"
        linhas.append(
            f"- **Vermelho:** {lista(vermelhos)} {verbo} vermelho depois da "
            "repetição autorizada no passo 2."
        )
    if nao_medidos:
        verbo = "ficou" if len(nao_medidos) == 1 else "ficaram"
        linhas.append(
            f"- **Não medido:** {lista(nao_medidos)} {verbo} sem medição — que "
            "não é verde nem é uma falha."
        )
    linhas.append("Os números de cada um:")
    for criterio in vermelhos + nao_medidos:
        linhas.append(f"- `{criterio['id']}`: {criterio['medido']}")
    # A leitura do que isto significa para a árvore está na prosa que segue este
    # bloco, e não aqui: o que é gerado são os números, não a interpretação.
    return "\n\n".join(linhas)


if __name__ == "__main__":
    sys.exit(main())
