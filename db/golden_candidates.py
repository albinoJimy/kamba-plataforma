"""Candidatos ao *golden* a partir das decisoes do concierge (KAM-114, criterio 7).

    python db/golden_candidates.py exportar [--tecto 1000] [--saida <ficheiro>]
    python db/golden_candidates.py esquema

**O que isto exporta, e o que nao exporta.** De cada rascunho `editado` ou
`rejeitado` saem **cinco** campos — a decisao, o motivo, o sinal do numero
livre, a versao do grafo e a razao de edicao arredondada a uma casa. Nada mais.
Nenhum identificador (`draft_id`, `tenant_id`, `thread_id`, `turn_id`), nenhum
instante, e **nenhum texto** — nem o do rascunho, nem o da edicao, nem o da
conversa. O texto nao esta nesta tabela de proposito: vive no checkpointer
(`lg`) e no HND.

**Porque e que isto nao e um *export* de conversas, e nao pode ser.** Os Termos
da Meta §4.7 proibem usar dados da plataforma para criar, desenvolver, treinar ou
melhorar sistemas de ML/IA (`docs/tecnica/evidencia/E1` §4, **NAO VERIFICADO** na
integra; ADR-018), e o `docs/tecnica/10` §11.3 tira a conclusao: o *golden* leva
**reescritas sinteticas**, nunca copias. Daqui sai o **rotulo** — «nesta
categoria, com este motivo, a IA errou» — e quem escreve o caso escreve-o de
novo, a mao, com dados inventados. O caso entra em KAM-040 com
`origem=sintetico`.

Por isso o comando se chama `golden-candidates` e nao `golden-export`: o que sai
e uma lista de **candidatos a escrever**, nao casos prontos.

**A razao de edicao sai arredondada a uma casa**, e isso e minimizacao e nao
estetica: tres casas (a escala da coluna) sobre um universo pequeno de rascunhos
e quase um identificador — duas edicoes com `0,418` sao provavelmente a mesma
conversa vista duas vezes. Uma casa da dez classes, que e o que um rotulo
precisa.

**O esquema e uma lista literal e a classificacao das colunas tambem**, e as
duas sao confrontadas com o `CREATE TABLE` da revisao `0024` pelo
`db/tests/test_golden_candidates.py`. E assim que o criterio 7 («um teste de
esquema prova 0 campos de texto livre ou de identificador») se cumpre contra a
tabela real e nao contra a memoria de quem escreveu isto: uma coluna nova na
`0024` que ninguem classifique **falha** o teste, em vez de entrar na exportacao
em silencio.

**Papel: `kamba_batch`, e a primeira versao escolheu `kamba_audit` e devolvia
zero linhas sempre.** A exportacao e, por natureza, **cross-tenant** — o
*golden* e um artefacto da plataforma —, e o `kamba_audit` e `NOBYPASSRLS`
(`db/bootstrap.py`): sem `app.tenant_id` definido, a politica `tenant_iso` da
`0024` reduz a `tenant_id = NULL` e a consulta devolve **zero**. Pior, falhava
em **silencio**: zero candidatos e indistinguivel de «ainda nao houve edicoes
nem rejeicoes», e e essa a leitura que quem corre o comando faria. Medido contra
um PostgreSQL 18 pela revisao adversarial.

O `kamba_batch` e o unico papel que a `0024` deixa atravessar *tenants*, e corre
sob `tenant_guard.tx_batch` com o *job* nomeado — a mesma via da varredura dos
prazos, e exige nome para que nao haja «uso sem nome nem sem contagem».

**E a separacao que a primeira versao invocava continua de pe**, so que o
argumento estava mal dirigido: quem produz as decisoes e o `kamba_app` (e esse
tem `SELECT` so para o CAS poder classificar o seu proprio rascunho), e o
`kamba_batch` nao e o produtor. A separacao do KAM-030 e entre **produtor e
leitor**, e ela mantem-se.
"""

from __future__ import annotations

import argparse
import json
import re
import sys
from pathlib import Path
from typing import Any, Final

sys.path.insert(0, str(Path(__file__).resolve().parent))

import ligacao  # noqa: E402 — depois do `sys.path`, como o `dlq.py`

SAIDA_OK: Final = 0
SAIDA_ACHADOS: Final = 1
SAIDA_ERRO: Final = 2

#: O tecto de linhas por exportacao. Tecto e nao «todas», pela razao do
#: `TECTO_POR_VARREDURA`: quem exporta quer um lote para rever a mao.
TECTO_POR_OMISSAO: Final = 1000

#: A revisao que cria a tabela. Lida para o teste de esquema.
REVISAO: Final = "db/migrations/versions/0024_draft_decisions.py"

#: O nome do *job* para o `tx_batch`. Snake_case, que e o que ele exige.
JOB: Final = "agr_golden_candidates"

#: Os **cinco** campos que saem. Lista fechada, e e o esquema da exportacao.
CAMPOS_DA_EXPORTACAO: Final = (
    "decisao",
    "motivo",
    "edicao_numero_livre",
    "graph_version",
    "razao_edicao",
)

#: Cada coluna de `platform.draft_decisions` por **classe**. O teste de esquema
#: exige que esta tabela cubra todas as colunas do `CREATE TABLE` da `0024`:
#: uma coluna nova sem classe falha, em vez de entrar na exportacao por omissao.
#:
#: As classes, e o que cada uma autoriza:
#:
#: * `identificador` — aponta para uma pessoa, uma conversa ou um turno.
#:   **Nunca** sai. E a metade «0 campos de identificador» do criterio 7;
#: * `instante` — diz **quando**. Nao sai: um instante com precisao de
#:   microssegundo sobre um universo pequeno re-identifica a conversa tao bem
#:   como um identificador, e o rotulo nao precisa dele;
#: * `rotulo` — dominio fechado ou booleano. Sai;
#: * `medida` — numero. Sai, e a `razao_edicao` sai **arredondada**.
#:
#: **Nao ha classe `texto`, e isso passou a ser verdade com uma alteracao a
#: `0024`.** A afirmacao original era falsa: o `graph_version` era `text` **sem
#: `CHECK` de forma** — a propria migracao o dizia, porque era onde o canario do
#: X-03 ia — e sai nesta exportacao. Isto e, havia um campo livre a atravessar
#: para fora, e a prova de esquema assentava numa classificacao a mao.
#: Apanhado pela revisao adversarial. A `0024` passou a impor SemVer naquela
#: coluna e o canario mudou-se para o `turn_id`, que nunca sai.
#:
#: Se alguem acrescentar uma coluna, ela nao cabe em nenhuma classe e o teste
#: falha — que e o comportamento certo.
CLASSES_DAS_COLUNAS: Final = {
    "draft_id": "identificador",
    "tenant_id": "identificador",
    "thread_id": "identificador",
    "turn_id": "identificador",
    "turn_seq": "identificador",
    "criado_at": "instante",
    "decidido_at": "instante",
    "decisao": "rotulo",
    "motivo": "rotulo",
    "edicao_numero_livre": "rotulo",
    "graph_version": "rotulo",
    "razao_edicao": "medida",
    "latencia_ms": "medida",
}

#: As classes que podem sair. **`medida` inclui-se e o `latencia_ms` nao sai de
#: qualquer maneira**, porque nao esta no `CAMPOS_DA_EXPORTACAO`: a latencia de
#: uma decisao e informacao sobre o **operador** e nao sobre o caso, e um
#: *golden* nao se escreve melhor por saber que alguem demorou nove minutos.
CLASSES_QUE_SAEM: Final = ("rotulo", "medida")

#: A consulta. Vive aqui e nao no `kamba_agr/concierge/consultas.py` porque o
#: papel e outro (`kamba_audit`) e o *lint* de arquitectura varre
#: `services/*/src/**` — e esta e uma leitura, nao uma escrita no `platform`.
SQL_CANDIDATOS: Final = """
  SELECT d.decisao,
         d.motivo,
         d.edicao_numero_livre,
         d.graph_version,
         round(d.razao_edicao, 1) AS razao_edicao
    FROM platform.draft_decisions d
   WHERE d.decisao IN ('editado', 'rejeitado')
   ORDER BY d.criado_at
   LIMIT %s
"""


class ErroDeUso(Exception):
    """O comando nao pode correr como foi pedido."""


def colunas_da_revisao(raiz: Path) -> tuple[str, ...]:
    """As colunas do `CREATE TABLE` da revisao `0024`, lidas do ficheiro.

    **Do ficheiro e nao de uma lista a mao**, que e o ponto do criterio 7: o
    teste de esquema tem de falhar quando a tabela ganhar uma coluna, e uma
    segunda copia da lista aqui nunca falharia.

    Le a primeira instrucao `CREATE TABLE ... ( ... )` e tira o primeiro
    identificador de cada linha que comece por um nome seguido de um tipo. As
    linhas de `CONSTRAINT`, os comentarios `--` e as linhas de continuacao nao
    contam.
    """
    fonte = (raiz / REVISAO).read_text(encoding="utf-8")
    inicio = fonte.index("CREATE TABLE")
    corpo = fonte[inicio : fonte.index("PRIMARY KEY (draft_id)", inicio)]
    nomes: list[str] = []
    for linha in corpo.splitlines():
        nua = linha.strip()
        if not nua or nua.startswith("--") or nua.startswith("CONSTRAINT"):
            continue
        achado = re.match(
            r"^([a-z_][a-z0-9_]*)\s+"
            r"(text|uuid|integer|boolean|timestamptz|numeric)\b",
            nua,
        )
        if achado:
            nomes.append(achado.group(1))
    return tuple(nomes)


def achados_do_esquema(raiz: Path) -> list[str]:
    """As divergencias entre a exportacao, a classificacao e a tabela real.

    Devolve uma lista vazia quando esta tudo conforme. E o corpo do comando
    `esquema` **e** do teste do criterio 7: uma so implementacao, para que o
    comando que o operador corre seja o mesmo que o teste mede.
    """
    achados: list[str] = []
    colunas = colunas_da_revisao(raiz)
    if not colunas:
        return [f"nao se leu coluna nenhuma de {REVISAO}"]

    sem_classe = [c for c in colunas if c not in CLASSES_DAS_COLUNAS]
    if sem_classe:
        achados.append(
            f"{len(sem_classe)} coluna(s) de platform.draft_decisions sem classe "
            f"em CLASSES_DAS_COLUNAS: {sorted(sem_classe)}. Classifique-as — uma "
            "coluna nao classificada escapa ao criterio 7 em silencio."
        )
    mortas = [c for c in CLASSES_DAS_COLUNAS if c not in colunas]
    if mortas:
        achados.append(
            f"{len(mortas)} coluna(s) classificada(s) que a revisao nao tem: "
            f"{sorted(mortas)}. Uma classificacao morta e pior do que nenhuma."
        )

    for campo in CAMPOS_DA_EXPORTACAO:
        classe = CLASSES_DAS_COLUNAS.get(campo)
        if classe is None:
            achados.append(f"o campo exportado `{campo}` nao esta classificado")
        elif classe not in CLASSES_QUE_SAEM:
            achados.append(
                f"o campo exportado `{campo}` e da classe `{classe}`, que nao "
                f"pode sair (so {list(CLASSES_QUE_SAEM)}) — criterio 7"
            )
    return achados


def exportar(cursor: Any, tecto: int = TECTO_POR_OMISSAO) -> list[dict[str, Any]]:
    """Os candidatos, como `dict` com exactamente os `CAMPOS_DA_EXPORTACAO`."""
    cursor.execute(SQL_CANDIDATOS, (int(tecto),))
    saida: list[dict[str, Any]] = []
    for linha in cursor.fetchall():
        registo = dict(zip(CAMPOS_DA_EXPORTACAO, linha, strict=True))
        razao = registo.get("razao_edicao")
        registo["razao_edicao"] = None if razao is None else float(razao)
        registo["edicao_numero_livre"] = bool(registo["edicao_numero_livre"])
        # **A origem vai no registo e nao no cabecalho do ficheiro.** Um ficheiro
        # com cem casos e um cabecalho a dizer `sintetico` perde a marca no dia
        # em que alguem partir a lista em duas; no registo, ela viaja com o caso
        # para o KAM-040.
        registo["origem"] = "sintetico"
        saida.append(registo)
    return saida


def _analisador() -> argparse.ArgumentParser:
    analisador = argparse.ArgumentParser(
        prog="golden_candidates", description=__doc__.split("\n")[0]
    )
    analisador.add_argument(
        "--root", type=Path, default=None, help="raiz do repositorio"
    )
    comandos = analisador.add_subparsers(dest="comando", required=True)

    exporta = comandos.add_parser(
        "exportar", help="os candidatos em JSON, so com metadados"
    )
    exporta.add_argument("--tecto", type=int, default=TECTO_POR_OMISSAO)
    exporta.add_argument(
        "--saida", type=Path, default=None, help="ficheiro (omissao: stdout)"
    )

    comandos.add_parser(
        "esquema",
        help="confronta a exportacao com as colunas da revisao 0024 (criterio 7)",
    )
    return analisador


def _utf8() -> None:
    """Sem isto, o primeiro achado em Windows e um `UnicodeEncodeError`."""
    for fluxo in (sys.stdout, sys.stderr):
        reconfigurar = getattr(fluxo, "reconfigure", None)
        if reconfigurar is not None:
            reconfigurar(encoding="utf-8", errors="replace")


def main(argv: list[str] | None = None) -> int:
    _utf8()
    argumentos = _analisador().parse_args(argv)
    raiz = (argumentos.root or Path(__file__).resolve().parents[1]).resolve()

    if argumentos.comando == "esquema":
        try:
            achados = achados_do_esquema(raiz)
        except OSError as erro:
            print(f"golden_candidates: erro de ficheiro: {erro}", file=sys.stderr)
            return SAIDA_ERRO
        if not achados:
            print(
                "golden_candidates: esquema conforme — "
                f"{len(CAMPOS_DA_EXPORTACAO)} campo(s) exportado(s), "
                f"{len(CLASSES_DAS_COLUNAS)} coluna(s) classificada(s), "
                "0 de texto livre ou de identificador."
            )
            return SAIDA_OK
        print(
            f"golden_candidates: {len(achados)} achado(s) de esquema",
            file=sys.stderr,
        )
        for achado in achados:
            print(f"  - {achado}", file=sys.stderr)
        return SAIDA_ACHADOS

    # **O esquema confere-se antes de exportar, e nao e cerimonia.** Se uma
    # coluna nova nao estiver classificada, a exportacao **nao corre**: e mais
    # barato recusar do que descobrir depois que um lote de candidatos levou
    # consigo um campo que o criterio 7 proibe.
    achados = achados_do_esquema(raiz)
    if achados:
        print(
            "golden_candidates: o esquema divergiu da revisao; corra "
            "`esquema` para ver os achados. Nao se exporta.",
            file=sys.stderr,
        )
        return SAIDA_ACHADOS

    import pg8000.dbapi
    from kamba_core import tenant_guard

    try:
        conexao = ligacao.ligar("batch")
    except ligacao.ConfiguracaoEmFalta as erro:
        print(f"golden_candidates: {erro}", file=sys.stderr)
        return SAIDA_ERRO

    try:
        try:
            # `tx_batch` e nao `tx`: a exportacao atravessa *tenants* e o *job*
            # tem de ter nome. Ver a nota do modulo.
            with tenant_guard.tx_batch(conexao, JOB) as cursor:
                candidatos = exportar(cursor, argumentos.tecto)
        except pg8000.dbapi.DatabaseError as erro:
            conexao.rollback()
            print(f"golden_candidates: a base recusou: {erro}", file=sys.stderr)
            return SAIDA_ERRO
    finally:
        conexao.close()

    texto = json.dumps(candidatos, ensure_ascii=False, indent=2) + "\n"
    if argumentos.saida is None:
        sys.stdout.write(texto)
    else:
        # LF explicito: o `pathlib.write_text` poe CRLF em Windows.
        argumentos.saida.write_bytes(texto.encode("utf-8"))
    print(
        f"golden_candidates: {len(candidatos)} candidato(s), "
        "so metadados, origem=sintetico.",
        file=sys.stderr,
    )
    return SAIDA_OK


if __name__ == "__main__":
    raise SystemExit(main())
