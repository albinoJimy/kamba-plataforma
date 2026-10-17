"""O gate 7, por linha de comando.

    python -m contract_diff --root . check          as quatro verificacoes
    python -m contract_diff --root . diff           so a compatibilidade
    python -m contract_diff --root . pii            so o lint de PII
    python -m contract_diff --root . exemplos       so os exemplos
    python -m contract_diff --root . subscricoes    so a versao_max
    python -m contract_diff --root . canario        prova que as quatro mordem

Codigos de saida, com a distincao que o `db/dlq.py` e o `tools/lint_handoff`
ja usam:

    0   conforme
    1   ha achados (o gate falha)
    2   erro de uso ou de ambiente (o ramo base nao existe, YAML invalido)

O `canario` e o que impede este gate de ser decorativo: constroi em memoria os
casos que **tem** de falhar e verifica que falham com a mensagem esperada. Sem
ele, um `return []` em qualquer das quatro verificacoes passava o CI inteiro a
verde e ninguem dava por isso.
"""

from __future__ import annotations

import argparse
import copy
import json
import sys
from pathlib import Path

from contract_diff import base as base_mod
from contract_diff import catalogo, diff, exemplos, pii, subscricoes

SAIDA_OK = 0
SAIDA_ACHADOS = 1
SAIDA_ERRO = 2


def _escrever(linhas: list[str]) -> None:
    for linha in linhas:
        print(linha)


def correr_diff(raiz: Path, ref: str, sem_base: bool) -> tuple[int, list[str]]:
    """Compara cada contrato com o do ramo base e classifica as diferencas."""
    actuais = {(c.tipo, c.versao): c for c in catalogo.todos(raiz)}
    if sem_base:
        return SAIDA_OK, [
            f"contract_diff diff: **nao correu** (--sem-base). {len(actuais)} contrato(s) "
            "na copia de trabalho; a compatibilidade com o ramo principal nao foi verificada"
        ]
    try:
        anteriores = base_mod.contratos(raiz, ref)
    except base_mod.BaseIndisponivelError as erro:
        return SAIDA_ERRO, [f"contract_diff diff: {erro}"]

    linhas: list[str] = []
    quebras = 0
    novos = sorted(set(actuais) - set(anteriores))
    apagados = sorted(set(anteriores) - set(actuais))

    for tipo, versao in apagados:
        quebras += 1
        linhas.append(
            f"  QUEBRANTE  {tipo} v{versao}: o contrato desapareceu. Um consumidor que o "
            "declare deixa de ter contra o que validar; uma versao retira-se depois de o "
            "ultimo consumidor migrar (§6.6: >= 90 dias)"
        )

    for chave in sorted(set(actuais) & set(anteriores)):
        tipo, versao = chave
        diferencas = diff.comparar(anteriores[chave].documento, actuais[chave].documento)
        for d in diferencas:
            if d.quebra:
                quebras += 1
                linhas.append(f"  QUEBRANTE  {tipo} v{versao} {d.caminho}: {d.porque}")
            else:
                linhas.append(f"  aditivo    {tipo} v{versao} {d.caminho}: {d.porque}")

    cabecalho = (
        f"contract_diff diff: {len(actuais)} contrato(s), {len(anteriores)} em {ref}; "
        f"{len(novos)} novo(s), {len(apagados)} apagado(s), {quebras} quebrante(s)"
    )
    if quebras:
        return SAIDA_ACHADOS, [cabecalho, *linhas, (
            "  Uma diferenca quebrante no mesmo v<N> nao passa. Quem quer quebrar escreve "
            "v<N+1> e deixa o v<N> como estava (docs/tecnica/06 §6.6)."
        )]
    return SAIDA_OK, [cabecalho, *linhas]


def correr_pii(raiz: Path) -> tuple[int, list[str]]:
    nomes = pii.nomes(raiz)
    fixtures = pii.fixtures(raiz)
    aprovados = pii.ler_allowlist(raiz)
    total = len(catalogo.todos(raiz))
    cabecalho = (
        f"contract_diff pii: {total} contrato(s) lido(s); {len(nomes)} nome(s) de campo "
        f"proibido(s), {len(fixtures)} ficheiro(s) com padrao de telefone; "
        f"{len(aprovados)} excepcao(oes) declarada(s)"
    )
    achados = [f"  {a}" for a in (*nomes, *fixtures)]
    return (SAIDA_ACHADOS if achados else SAIDA_OK), [cabecalho, *achados]


def correr_exemplos(raiz: Path) -> tuple[int, list[str]]:
    invalidos = exemplos.validar(raiz)
    incoerentes = exemplos.coerencia(raiz)
    total = len(catalogo.todos(raiz))
    cabecalho = (
        f"contract_diff exemplos: {total} contrato(s); {len(invalidos)} sem exemplo ou "
        f"com exemplo invalido, {len(incoerentes)} incoerente(s) com o catalogo"
    )
    achados = [f"  {a}" for a in (*invalidos, *incoerentes)]
    return (SAIDA_ACHADOS if achados else SAIDA_OK), [cabecalho, *achados]


def correr_subscricoes(raiz: Path) -> tuple[int, list[str]]:
    lidas = subscricoes.ler(raiz)
    achados = subscricoes.verificar(raiz, lidas)
    if not lidas:
        cabecalho = (
            "contract_diff subscricoes: **0 subscricoes declaradas** em "
            f"{subscricoes.PASTA_DO_REGISTO.as_posix()}/ — a verificacao passou sobre um "
            "conjunto vazio. Os ficheiros nascem com o KAM-038; o canario prova que ela "
            "morde quando houver"
        )
    else:
        cabecalho = (
            f"contract_diff subscricoes: {len(lidas)} subscricao(oes) lida(s); "
            f"{len(achados)} com versao_max sem contrato"
        )
    return (SAIDA_ACHADOS if achados else SAIDA_OK), [cabecalho, *[f"  {a}" for a in achados]]


# --------------------------------------------------------------------- canario

def _negativas(raiz: Path) -> list[tuple[str, bool, str]]:
    """(nome, mordeu?, o que se esperava). Cada caso **tem** de falhar."""
    casos: list[tuple[str, bool, str]] = []
    contratos = catalogo.todos(raiz)
    if not contratos:
        return [("sem contratos para morder", False, "ha pelo menos um contrato")]
    exemplar = contratos[0].documento

    def com(alteracao) -> list[diff.Diferenca]:
        copia = copy.deepcopy(exemplar)
        alteracao(copia)
        return diff.quebra(diff.comparar(exemplar, copia))

    def apagar_campo(d):
        del d["properties"]["payload"]["properties"][
            sorted(d["properties"]["payload"]["properties"])[0]
        ]

    def mudar_tipo(d):
        nome = sorted(d["properties"]["payload"]["properties"])[0]
        d["properties"]["payload"]["properties"][nome] = {"type": "boolean"}

    def tornar_obrigatorio(d):
        payload = d["properties"]["payload"]
        opcionais = sorted(set(payload["properties"]) - set(payload.get("required") or []))
        if opcionais:
            payload.setdefault("required", []).append(opcionais[0])
        else:  # todos ja sao obrigatorios: acrescenta-se um campo novo obrigatorio
            payload["properties"]["campo_novo"] = {"type": "string"}
            payload.setdefault("required", []).append("campo_novo")

    def abrir_objecto(d):
        d["properties"]["payload"]["additionalProperties"] = True

    casos.append(("remover um campo", bool(com(apagar_campo)), "quebrante"))
    casos.append(("mudar o tipo de um campo", bool(com(mudar_tipo)), "quebrante"))
    casos.append(("tornar um campo obrigatorio", bool(com(tornar_obrigatorio)), "quebrante"))
    casos.append(("abrir o payload", bool(com(abrir_objecto)), "quebrante"))

    nome_mau = pii.proibido_em("telefone_do_cliente")
    casos.append(("nome de campo com PII", nome_mau == "telefone", "o lint rejeita «telefone»"))
    casos.append(
        ("fixture com telefone angolano",
         pii.TELEFONE_AO.search('{"ref": "+244 912345678"}') is not None,
         "o padrao do evt_emitir casa"),
    )

    inventada = [subscricoes.Subscricao("(canario)", "ensaio", "order.created", 99)]
    casos.append(
        ("subscricao com versao_max inexistente",
         bool(subscricoes.verificar(raiz, inventada)),
         "nao ha v99 de order.created"),
    )
    inexistente = [subscricoes.Subscricao("(canario)", "ensaio", "nao.existe", 1)]
    casos.append(
        ("subscricao de um tipo sem contrato",
         bool(subscricoes.verificar(raiz, inexistente)),
         "nao ha contrato de nao.existe"),
    )
    return casos


def _positivas(raiz: Path) -> list[tuple[str, bool, str]]:
    """(nome, ficou verde?, o que se esperava). Cada caso **nao** pode falhar."""
    casos: list[tuple[str, bool, str]] = []
    contratos = catalogo.todos(raiz)
    if not contratos:
        return []
    exemplar = contratos[0].documento

    copia = copy.deepcopy(exemplar)
    copia["properties"]["payload"]["properties"]["campo_novo"] = {"type": "string"}
    casos.append(
        ("acrescentar campo opcional", not diff.quebra(diff.comparar(exemplar, copia)),
         "aditivo-opcional passa"),
    )

    copia = copy.deepcopy(exemplar)
    copia["description"] = "prosa nova"
    casos.append(
        ("mudar a prosa", not diff.quebra(diff.comparar(exemplar, copia)),
         "description nao e contrato"),
    )

    casos.append(
        ("nome de campo sem PII", pii.proibido_em("numero_publico") is None,
         "«numero_publico» contem «numero», nao «nome»"),
    )
    casos.append(
        ("contact_id e pseudonimo, nao PII", pii.proibido_em("contact_id") is None,
         "o §7.1 manda usar contact_id"),
    )
    return casos


def correr_canario(raiz: Path) -> tuple[int, list[str]]:
    negativas = _negativas(raiz)
    positivas = _positivas(raiz)
    falhas = [(n, e) for n, ok, e in negativas if not ok]
    falhas += [(n, e) for n, ok, e in positivas if not ok]
    linhas = [
        f"contract_diff canario: {len(negativas)} negativas e {len(positivas)} positivas; "
        f"{len(falhas)} falha(s)"
    ]
    for nome, esperado in falhas:
        linhas.append(f"  o caso «{nome}» nao se comportou como devia: esperava-se {esperado}")
    return (SAIDA_ACHADOS if falhas else SAIDA_OK), linhas


def main(argv: list[str] | None = None) -> int:
    analisador = argparse.ArgumentParser(prog="contract_diff", description=__doc__)
    analisador.add_argument("--root", type=Path, default=Path("."))
    analisador.add_argument("--base", default=base_mod.BASE_POR_OMISSAO)
    analisador.add_argument(
        "--sem-base", action="store_true",
        help="nao comparar com o ramo principal; fica registado na saida",
    )
    analisador.add_argument(
        "comando",
        choices=["check", "diff", "pii", "exemplos", "subscricoes", "canario"],
        nargs="?", default="check",
    )
    argumentos = analisador.parse_args(argv)
    raiz = argumentos.root.resolve()

    if not (raiz / catalogo.PASTA).is_dir():
        print(
            f"contract_diff: {catalogo.PASTA.as_posix()}/ nao existe. O gate 7 verifica "
            "contratos, e sem contratos nao ha nada a verificar — se isto e esperado, o "
            "alvo do Makefile nao devia estar activo",
            file=sys.stderr,
        )
        return SAIDA_ERRO

    try:
        contratos = catalogo.todos(raiz)
    except catalogo.ContratoInvalidoError as erro:
        print(f"contract_diff: {erro}", file=sys.stderr)
        return SAIDA_ERRO

    partes = {
        "diff": lambda: correr_diff(raiz, argumentos.base, argumentos.sem_base),
        "pii": lambda: correr_pii(raiz),
        "exemplos": lambda: correr_exemplos(raiz),
        "subscricoes": lambda: correr_subscricoes(raiz),
        "canario": lambda: correr_canario(raiz),
    }
    if argumentos.comando != "check":
        codigo, linhas = partes[argumentos.comando]()
        _escrever(linhas)
        return codigo

    pior = SAIDA_OK
    for nome in ("diff", "pii", "exemplos", "subscricoes", "canario"):
        codigo, linhas = partes[nome]()
        _escrever(linhas)
        pior = max(pior, codigo)
    if pior == SAIDA_OK:
        print(f"contract_diff: conforme — {len(contratos)} contrato(s)")
    return pior


if __name__ == "__main__":
    raise SystemExit(main())
