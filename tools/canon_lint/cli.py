"""Interface de linha de comando do `canon_lint` (gate 3b).

    python -m canon_lint check    [--root .]   verifica as quatro superficies
    python -m canon_lint canario  [--root .]   prova que o lint morde (fixtures)
    python -m canon_lint ficheiro <superficie> <caminho>   um ficheiro, para depurar

Codigo de saida 0 = conforme, 1 = achados, 2 = erro de configuracao. A distincao
importa: um dicionario em falta nao pode parecer um repositorio limpo.

O `check` imprime **quanto** leu em cada superficie. Nao e cosmetica: uma
superficie com zero ficheiros passa sempre, e a unica defesa contra ler isso
como «esta tudo bem» e a saida dize-lo por extenso.
"""

from __future__ import annotations

import argparse
import datetime
import re
import sys
from pathlib import Path

from kamba_yaml import YamlSubsetError, load_file

from . import ddl, documentos, eventos, registo, superficies
from .achados import REGRA, Achado
from .dicionario import EXTENSOES, ConfiguracaoInvalida, Saber, _exigir_chaves, _lista
from .yamlreg import YamlIlegivel

FIXTURES = "tools/canon_lint/tests/fixtures"
MANIFESTO = f"{FIXTURES}/manifesto.yaml"
SUPERFICIES_DE_FICHEIRO = ("migracoes", "eventos", "registo")

# --------------------------------------------------------------------- canario
#
# O que o canario tem de provar esta AQUI, no codigo, e nao no manifesto. O
# manifesto diz onde estao os ficheiros e que mensagem cada um da; nao decide
# quantos sao, nem quais podem faltar. A primeira versao deixava essa decisao no
# YAML, e um manifesto com `casos: []` dava «0 negativas vermelhas» e saida 0 —
# o passo que existe para provar que as superficies vazias mordem desaparecia
# com uma edicao a um ficheiro de fixtures (ANALISE-05, B1).

#: As doze divergencias do KAM-111.
DIVERGENCIAS = tuple(f"D-{n:02d}" for n in range(1, 13))
#: As que nao tem forma de nome em nenhuma superficie, e por isso nao tem
#: fixture. Acrescentar uma aqui e uma alteracao de codigo, com revisao.
SEM_FORMA_DE_NOME = frozenset({"D-07", "D-09"})
#: Cada superficie de ficheiro tem de ter pelo menos uma negativa: e a unica
#: prova de que `eventos` e `registo` mordem enquanto estao vazias no repositorio.
MINIMO_POR_SUPERFICIE = {"migracoes": 1, "eventos": 1, "registo": 1}
#: A forma que o criterio de aceitacao pede: «<variante> → <canonico>, dicionario §3.x».
FORMA_DA_MENSAGEM = re.compile(r"^`[^`]+`.* → `.+`, dicionário §3\.\d+$")


def _utf8() -> None:
    """A mensagem do criterio de aceitacao tem `→`, que a consola cp1252 nao tem.

    Sem isto, o primeiro achado em Windows era um `UnicodeEncodeError` — o gate
    rebentava em vez de dizer o que encontrou.
    """
    for fluxo in (sys.stdout, sys.stderr):
        reconfigurar = getattr(fluxo, "reconfigure", None)
        if reconfigurar is not None:
            reconfigurar(encoding="utf-8", errors="replace")


def _ler(raiz: Path, relativo: str) -> str | None:
    try:
        return (raiz / relativo).read_text(encoding="utf-8")
    except (OSError, UnicodeDecodeError):
        return None


def substituicoes_por_revisao(
    relativos: list[str], fontes: dict[str, str], saber: Saber
) -> dict[str, frozenset[tuple[str, str]]]:
    """Por revisao, os dominios fechados que uma revisao **posterior** redeclara.

    Um dominio fechado pode crescer, e cresce por `DROP CONSTRAINT` +
    `ADD CONSTRAINT` numa revisao posterior; a revisao antiga continua a declarar
    o dominio antigo, que e historia e nao defeito. A razao inteira esta na nota
    do `ddl._nivel2`.

    **A ordem e a do nome do ficheiro**, e aqui isso e a ordem das revisoes: a
    cadeia e linear (`down_revision` de cada uma e a anterior) e o nome comeca
    pelo numero da revisao (`0021_tool_audit.py`). Se a cadeia deixar de ser
    linear, isto passa a precisar do grafo em vez do nome.
    """
    ordenados = sorted(relativos)
    declaradas = {
        relativo: ddl.declaracoes_fechadas(relativo, fontes[relativo], saber)
        for relativo in ordenados
        if fontes.get(relativo) is not None
    }
    resultado: dict[str, frozenset[tuple[str, str]]] = {}
    for indice, relativo in enumerate(ordenados):
        posteriores: set[tuple[str, str]] = set()
        for seguinte in ordenados[indice + 1 :]:
            posteriores |= declaradas.get(seguinte, set())
        resultado[relativo] = frozenset(posteriores)
    return resultado


def verificar_ficheiro(
    superficie: str,
    relativo: str,
    fonte: str,
    saber: Saber,
    substituidos: frozenset[tuple[str, str]] = frozenset(),
):
    """Um ficheiro de uma das tres superficies de ficheiro. Devolve (achados, contagem)."""
    if superficie == "migracoes":
        return ddl.verificar(relativo, fonte, saber, substituidos)
    if superficie == "eventos":
        return eventos.verificar(relativo, fonte, saber), None
    if superficie == "registo":
        return registo.verificar(relativo, fonte, saber), None
    raise ConfiguracaoInvalida(f"superficie desconhecida: {superficie!r}")


def verificar(raiz: Path, hoje: datetime.date | None = None) -> tuple[list[Achado], dict]:
    """Verifica o repositorio inteiro. Devolve (achados, estatisticas)."""
    hoje = hoje or datetime.date.today()
    saber = Saber.ler(raiz, hoje)
    permitidas = documentos.Permitidas.ler(raiz, saber, hoje)
    ficheiros = superficies.ficheiros_do_git(raiz)
    por_superficie, achados = superficies.repartir(ficheiros, saber.politica)

    contagem = ddl.Contagem()
    # A pre-passagem das migracoes: le-se cada revisao uma vez para saber quem
    # declara que dominio fechado, antes de cobrar `falta` a alguma delas.
    fontes_de_migracao = {
        relativo: _ler(raiz, relativo) for relativo in por_superficie["migracoes"]
    }
    substituicoes = substituicoes_por_revisao(
        list(por_superficie["migracoes"]),
        {k: v for k, v in fontes_de_migracao.items() if v is not None},
        saber,
    )
    for superficie in SUPERFICIES_DE_FICHEIRO:
        for relativo in por_superficie[superficie]:
            fonte = _ler(raiz, relativo)
            if fonte is None:
                achados.append(Achado(relativo, 0, "ilegivel", "nao se consegue ler como UTF-8"))
                continue
            novos, parcial = verificar_ficheiro(
                superficie, relativo, fonte, saber,
                substituicoes.get(relativo, frozenset()),
            )
            achados += novos
            if parcial is not None:
                contagem.juntar(parcial)

    textos = {}
    for relativo in por_superficie["documentos"]:
        fonte = _ler(raiz, relativo)
        if fonte is None:
            achados.append(Achado(relativo, 0, "ilegivel", "nao se consegue ler como UTF-8"))
        else:
            textos[relativo] = fonte
    novos, estatisticas_docs = documentos.verificar(textos, saber, permitidas, hoje)
    achados += novos

    # Uma extensao que nada usa e uma autorizacao a espera de ser aproveitada.
    por_usar = [e for e in saber.extensoes.entradas if (e.tipo, e.nome) not in saber.extensoes.usadas]
    for extensao in por_usar:
        achados.append(
            Achado(
                EXTENSOES,
                0,
                REGRA,
                f"a extensao `{extensao.nome}` (tipo `{extensao.tipo}`, {extensao.ticket}) nao e "
                "usada por nenhuma superficie: retire-a",
            )
        )

    return achados, {
        "saber": saber,
        "ficheiros": {nome: len(lista) for nome, lista in por_superficie.items()},
        "ddl": contagem,
        "documentos": estatisticas_docs,
        "dividas": [e for e in permitidas.entradas if e.classe == "divida"],
    }


def _resumo(estatisticas: dict) -> list[str]:
    saber: Saber = estatisticas["saber"]
    n = estatisticas["ficheiros"]
    c: ddl.Contagem = estatisticas["ddl"]
    d = estatisticas["documentos"]
    linhas = [
        f"  dicionario v{saber.dicionario.versao}: {len(saber.dicionario.entradas)} entradas, "
        f"{len(saber.dicionario.variantes)} variantes; {len(saber.extensoes.entradas)} extensoes",
        f"  migracoes:  {n['migracoes']} ficheiro(s) — {c.instrucoes} instrucoes, {c.tabelas} tabelas, "
        f"{c.colunas} colunas, {c.valores} valores de CHECK"
        + (f"; {c.opacos} bloco(s) $$ so com nivel 1" if c.opacos else ""),
    ]
    for nome in ("eventos", "registo"):
        if n[nome]:
            linhas.append(f"  {nome + ':':<11} {n[nome]} ficheiro(s)")
        else:
            linhas.append(
                f"  {nome + ':':<11} 0 ficheiros — A SUPERFICIE AINDA NAO EXISTE; nada foi verificado aqui"
            )
    linhas.append(
        f"  documentos: {n['documentos']} ficheiro(s) — {d['ocorrencias']} ocorrencia(s) de variantes, "
        f"contra {d['historicas']} historicas e {d['dividas']} dividas declaradas"
    )
    dividas = estatisticas["dividas"]
    if dividas:
        primeira = min(e.expira_em for e in dividas)
        linhas.append(
            f"  ATENCAO: {len(dividas)} divida(s) em ci/canon-allow.yaml; a primeira vence a "
            f"{primeira} e a partir dai o gate falha"
        )
    for contradicao in saber.dicionario.contradicoes:
        linhas.append(
            f"  aviso: contradicao no dicionario §{contradicao['seccao']} ({contradicao['conceito']}): "
            f"`{contradicao['nome']}` {contradicao['razao']}"
        )
    return linhas


def canario(raiz: Path) -> tuple[list[str], dict]:
    """Corre as fixtures. Devolve (falhas, estatisticas).

    Cada negativa tem de dar **exactamente um** achado, e a mensagem dele tem de
    **comecar** pelo `espera` do manifesto, que por sua vez tem de ter a forma
    «variante → canonico, dicionario §3.x». Cada positiva tem de passar sem
    achado nenhum. E o conjunto de casos tem de ser o que o codigo exige.
    """
    saber = Saber.ler(raiz)
    caminho = raiz / MANIFESTO
    if not caminho.is_file():
        raise ConfiguracaoInvalida(f"{MANIFESTO} nao existe")
    dados = load_file(caminho)
    _exigir_chaves(dados, {"version", "casos", "sem_forma_de_nome"}, MANIFESTO)
    falhas: list[str] = []
    negativas = positivas = 0
    por_superficie = {nome: 0 for nome in MINIMO_POR_SUPERFICIE}
    vistas: list[str] = []
    for indice, caso in enumerate(_lista(dados, "casos", MANIFESTO), start=1):
        onde = f"{MANIFESTO}: caso {indice}"
        _exigir_chaves(caso, {"divergencia", "superficie", "negativa", "positiva", "espera"}, onde)
        for chave in ("divergencia", "superficie", "negativa", "positiva", "espera"):
            if not caso.get(chave):
                raise ConfiguracaoInvalida(f"{onde}: falta `{chave}`")
        divergencia, superficie, espera = str(caso["divergencia"]), str(caso["superficie"]), str(caso["espera"])
        if superficie not in por_superficie:
            raise ConfiguracaoInvalida(f"{onde}: superficie {superficie!r} desconhecida")
        vistas.append(divergencia)
        if not FORMA_DA_MENSAGEM.match(espera):
            falhas.append(
                f"{divergencia}: o `espera` do manifesto nao tem a forma «`variante` → `canonico`, "
                f"dicionário §3.x» ({espera!r}); um `espera` curto aceitava qualquer achado"
            )
        for papel in ("negativa", "positiva"):
            relativo = f"{FIXTURES}/{caso[papel]}"
            fonte = _ler(raiz, relativo)
            if fonte is None:
                raise ConfiguracaoInvalida(f"{onde}: nao consigo ler {relativo}")
            achados, _ = verificar_ficheiro(superficie, relativo, fonte, saber)
            if papel == "negativa":
                negativas += 1
                por_superficie[superficie] += 1
                if len(achados) != 1 or not achados[0].mensagem.startswith(espera):
                    lido = "; ".join(a.mensagem for a in achados) or "nenhum achado"
                    falhas.append(
                        f"{divergencia}: a negativa {caso['negativa']} devia dar um unico achado, a "
                        f"comecar por «{espera}», e deu {len(achados)}: {lido}"
                    )
            else:
                positivas += 1
                if achados:
                    falhas.append(
                        f"{divergencia}: a positiva {caso['positiva']} devia passar e deu: "
                        + "; ".join(str(a) for a in achados)
                    )

    sem_forma: list[str] = []
    for indice, item in enumerate(_lista(dados, "sem_forma_de_nome", MANIFESTO), start=1):
        onde = f"{MANIFESTO}: sem_forma_de_nome {indice}"
        _exigir_chaves(item, {"divergencia", "razao"}, onde)
        if len(str(item.get("razao") or "")) < 40:
            raise ConfiguracaoInvalida(f"{onde}: precisa de uma razao a serio")
        sem_forma.append(str(item.get("divergencia")))

    # O conjunto e o que o codigo exige — nem mais, nem menos, nem repetido.
    esperadas = [d for d in DIVERGENCIAS if d not in SEM_FORMA_DE_NOME]
    if sorted(vistas) != sorted(esperadas):
        falhas.append(
            f"o manifesto tem fixtures para {sorted(vistas)} e o gate exige exactamente "
            f"{esperadas}: uma fixture nao se retira (nem se duplica) no manifesto"
        )
    if sorted(sem_forma) != sorted(SEM_FORMA_DE_NOME):
        falhas.append(
            f"o manifesto declara {sorted(sem_forma)} sem forma de nome; o gate so admite "
            f"{sorted(SEM_FORMA_DE_NOME)} (tools/canon_lint/cli.py)"
        )
    for superficie, minimo in MINIMO_POR_SUPERFICIE.items():
        if por_superficie[superficie] < minimo:
            falhas.append(
                f"a superficie `{superficie}` tem {por_superficie[superficie]} negativa(s) e precisa de "
                f"pelo menos {minimo}: sem ela nada prova que essa verificacao morde"
            )
    return falhas, {
        "negativas": negativas,
        "positivas": positivas,
        "sem_forma": len(sem_forma),
        "por_superficie": por_superficie,
    }


def main(argv: list[str] | None = None) -> int:
    _utf8()
    analisador = argparse.ArgumentParser(
        prog="canon_lint", description="Gate 3b: lint de nomes canonicos"
    )
    analisador.add_argument("--root", type=Path, default=None)
    sub = analisador.add_subparsers(dest="comando", required=True)
    sub.add_parser("check", help="verifica as quatro superficies")
    sub.add_parser("canario", help="prova que o lint morde, com as fixtures")
    um = sub.add_parser("ficheiro", help="verifica um ficheiro (para depurar)")
    um.add_argument("superficie", choices=SUPERFICIES_DE_FICHEIRO)
    um.add_argument("caminho", type=Path)

    argumentos = analisador.parse_args(argv)
    raiz = (argumentos.root or Path(__file__).resolve().parents[2]).resolve()

    try:
        if argumentos.comando == "ficheiro":
            saber = Saber.ler(raiz)
            try:
                fonte = argumentos.caminho.read_text(encoding="utf-8")
            except UnicodeDecodeError as excepcao:
                # A mensagem do `UnicodeDecodeError` nao diz qual e o ficheiro,
                # e esta e a unica leitura que nao passa pelo `_ler` (KAM-148).
                raise ConfiguracaoInvalida(
                    f"{argumentos.caminho.as_posix()}: nao se consegue ler como UTF-8 ({excepcao})"
                ) from excepcao
            achados, _ = verificar_ficheiro(
                argumentos.superficie, argumentos.caminho.as_posix(), fonte, saber
            )
            for achado in achados:
                print(f"  - {achado}")
            print(f"canon_lint: {len(achados)} achado(s)")
            return 1 if achados else 0

        if argumentos.comando == "canario":
            falhas, numeros = canario(raiz)
            if falhas:
                print(f"canon_lint: o canario falhou em {len(falhas)} ponto(s):", file=sys.stderr)
                for falha in falhas:
                    print(f"  - {falha}", file=sys.stderr)
                print(
                    "  O lint deixou de detectar o que existe para detectar, passou a recusar o "
                    "que e canonico, ou o manifesto deixou de pedir a prova.",
                    file=sys.stderr,
                )
                return 1
            por = numeros["por_superficie"]
            print(
                f"canon_lint: canario — {numeros['negativas']} negativas vermelhas com a mensagem "
                f"esperada ({por['migracoes']} de migracoes, {por['eventos']} de eventos, "
                f"{por['registo']} de registo), {numeros['positivas']} positivas verdes; "
                f"{numeros['sem_forma']} divergencia(s) sem forma de nome, fixadas no codigo"
            )
            return 0

        achados, estatisticas = verificar(raiz)
        if achados:
            print(f"canon_lint: {len(achados)} achado(s)", file=sys.stderr)
            for achado in achados:
                print(f"  - {achado}", file=sys.stderr)
            for linha in _resumo(estatisticas):
                print(linha, file=sys.stderr)
            return 1
        print("canon_lint: conforme")
        for linha in _resumo(estatisticas):
            print(linha)
        return 0

    # O `UnicodeDecodeError` entra pela razao do KAM-136: nao e `OSError`, e sem
    # ele o `ficheiro` (que le o caminho directamente, sem passar pelo `_ler`)
    # morria com *traceback* e codigo 1 em vez de erro de configuracao. O
    # `YamlIlegivel` e a rede do leitor de `registry/*.yaml`: hoje o
    # `registo.verificar` apanha-o e devolve-o como achado, e esta linha garante
    # que um caminho novo nao passa a dar *traceback* (KAM-148).
    except (
        ConfiguracaoInvalida,
        YamlSubsetError,
        YamlIlegivel,
        UnicodeDecodeError,
        OSError,
    ) as excepcao:
        print(f"canon_lint: erro de configuracao: {excepcao}", file=sys.stderr)
        return 2


if __name__ == "__main__":
    raise SystemExit(main())
