"""Verificacao da cadeia de auditoria e ancora diaria (KAM-012).

    python db/auditoria.py verificar          # a cadeia inteira, por tenant
    python db/auditoria.py ancorar            # a ancora do dia, por tenant
    python db/auditoria.py verificar --tenant <uuid>

O `docs/tecnica/08` §6 pede, proporcional ao Piloto, «verificacao nocturna da
cadeia e **ancora diaria** do ultimo `row_hash` exportada para o repo de
backup fora do host». Este ficheiro e as duas primeiras partes; o repositorio
fora do host e o KAM-079, e ate la a ancora fica em ficheiro local.

## Porque e que o verificador reimplementa o hash

Chamar `platform.audit_row_hash` daria sempre certo: verificar uma cadeia com
a funcao que a escreveu nao verifica nada, porque um defeito **nela** aparece
dos dois lados. A formula esta aqui outra vez, em Python, e e a divergencia
entre as duas que tem valor. A mesma razao pela qual o `test_auditoria.py` a
recalcula.

## O que conta como adulteracao

Quatro coisas, e o verificador distingue-as porque a resposta operacional e
diferente:

    fora da cadeia   o `prev_hash` de uma linha nao e o `row_hash` de nenhuma
                     outra, e ela nao parte da genese. Alguem **apagou** uma
                     linha do meio, ou **inseriu** uma forjada.
    elo partido      o `prev_hash` de uma linha **e** o `row_hash` de outra,
                     mas essa outra ja tem quem a siga: a cadeia **bifurca**.
                     Alguem inseriu uma linha a meio sem refazer o resto.
    hash errado      o `row_hash` nao bate com o que as colunas dao. Alguem
                     **alterou** uma coluna.
    cabeca errada    o `audit_heads` nao aponta para o ultimo elo. A cadeia
                     esta inteira e a cabeca nao: ou a cabeca foi mexida, ou
                     uma linha foi apagada **do fim**, que e o unico caso que
                     os dois primeiros nao apanham.

**Eram tres, e a quarta nasceu de um defeito** (KAM-161): a bifurcacao existia
e caia no balde «fora da cadeia», cuja mensagem afirma que o `prev_hash` nao e
o `row_hash` de nenhuma outra — o contrario do que se passa numa bifurcacao. O
verificador reportava a adulteracao, mas dizia a causa errada, e quem fosse
investigar procurava uma linha apagada onde havia uma inserida. Havia uma guarda
escrita para este caso, no laco da travessia, e era **inalcancavel**.

O terceiro e o que justifica a tabela de cabecas existir para alem do
desempenho: sem ela, apagar as ultimas N linhas de uma cadeia deixava-a
consistente consigo propria.

## Sev1, e o que isso quer dizer aqui

O ticket pede «alerta Sev1». Nao ha ainda encaminhamento de alertas (KAM-078),
pelo que o que existe e o que se pode verificar: **codigo de saida 2** e uma
linha por achado no `stderr`, para quem corre o *job* saber. A metrica
`audit_chain_verify_failed_total` nasce com o encaminhamento, e esta decisao
fica dita aqui em vez de fingida.
"""

from __future__ import annotations

import argparse
import datetime
import hashlib
import json
import os
import sys
from pathlib import Path

import ligacao

#: A genese de uma cadeia: trinta e dois zeros. Tem de ser igual a da revisao
#: 0006 — e nao se importa de la: um verificador que leia a constante do
#: codigo que verifica tem menos valor do que um que a repita.
GENESE = bytes(32)

#: O separador dos campos no hash (unit separator). Idem.
SEPARADOR = "\x1f"

#: Onde fica a ancora, quando nao se diz outra coisa. O repositorio fora do
#: host e o KAM-079; ate la, local e reproduzivel a partir da base.
ANCORA_POR_OMISSAO = Path("ci") / "ancoras"

#: A variavel que muda o destino da ancora.
VARIAVEL_DA_ANCORA = "KAMBA_AUDIT_ANCORA_DIR"


def iso_utc(momento) -> str:
    """A forma canonica de um instante no hash: ISO 8601 em UTC, microssegundos.

    Tem de dar exactamente o mesmo texto que o
    `to_char(... AT TIME ZONE 'UTC', 'YYYY-MM-DD"T"HH24:MI:SS.US')` da revisao
    0006. Um `timestamptz` renderizado no fuso da sessao daria hashes
    diferentes conforme quem verifica — que e o defeito que a ancora tinha.
    """
    return momento.astimezone(datetime.timezone.utc).strftime("%Y-%m-%dT%H:%M:%S.%f")


def row_hash(prev: bytes, criado_at, tenant, actor_type, actor_id, action, entity,
             entity_id, turn_id, payload_hash: bytes) -> bytes:
    """A formula de um elo, em Python. Ver o docstring do modulo.

    O `criado_at` entra desde a revisao adversarial: sem ele, apagar a ultima
    linha e reinseri-la com o mesmo conteudo e outra data deixava a cadeia
    «intacta», e o valor probatorio de um registo e «quem fez o que **e
    quando**».
    """
    partes = (
        prev.hex(),
        iso_utc(criado_at),
        "" if tenant is None else str(tenant),
        actor_type, actor_id, action, entity, entity_id,
        "" if turn_id is None else turn_id,
        payload_hash.hex(),
    )
    return hashlib.sha256(SEPARADOR.join(partes).encode("utf-8")).digest()


def _cursor(papel: str | None = None):
    """Uma ligacao de auditoria. Le o registo e mais nada.

    `kamba_audit` nao tem `BYPASSRLS`, pelo que ve as cadeias dos tenants a
    que o contexto lhe der acesso — e **nao** ve a cadeia de plataforma. Quem
    verifica tudo e o `kamba_batch`, que e quem corre o *job* nocturno; o
    `--papel` existe para que uma verificacao pontual de um tenant possa
    correr com o papel estreito.
    """
    return ligacao.ligar(papel or os.environ.get("KAMBA_AUDIT_PAPEL", "batch")).cursor()


def cadeias(cursor, tenant: str | None = None) -> dict:
    """As linhas de `audit_log` agrupadas por cadeia, por ordem de escrita."""
    sql = (
        "SELECT tenant_id, id, criado_at, actor_type, actor_id, action, entity, "
        "       entity_id, turn_id, payload_hash, prev_hash, row_hash "
        "  FROM platform.audit_log "
    )
    parametros: tuple = ()
    if tenant is not None:
        sql += " WHERE tenant_id = %s"
        parametros = (tenant,)
    sql += " ORDER BY tenant_id NULLS FIRST, id"
    cursor.execute(sql, parametros)
    por_cadeia: dict = {}
    for linha in cursor.fetchall():
        por_cadeia.setdefault(linha[0], []).append(tuple(linha))
    return por_cadeia


def _por_ordem_da_cadeia(linhas: list) -> tuple[list, list]:
    """As linhas pela ordem do **encadeamento**, e as que ficaram de fora.

    **A ordem do `id` nao e a ordem da cadeia**, e isso foi medido: o `id` sai
    da sequencia quando a instrucao comeca, e o lugar na cadeia decide-se
    depois, quando o trigger bloqueia a cabeca. Com mil insercoes concorrentes
    a transaccao que apanha o `id` 5 pode encadear **depois** da que apanhou o
    6, e um verificador que percorra por `id` ve elos partidos que nao
    existem. Percorre-se seguindo o `prev_hash`, que e a cadeia a dizer a sua
    propria ordem.

    O que sobra sao linhas cujo `prev_hash` nao e o `row_hash` de nenhuma
    outra e que nao partem da genese — e essas **sao** achado: e o que fica
    quando alguem apaga uma linha do meio ou insere uma forjada.
    """
    por_prev: dict = {}
    for linha in linhas:
        por_prev.setdefault(bytes(linha[10]), []).append(linha)
    ordenadas: list = []
    actual = GENESE
    vistos: set = set()
    while actual in por_prev:
        linha = por_prev[actual].pop(0)
        if not por_prev[actual]:
            del por_prev[actual]
        ordenadas.append(linha)
        proximo = bytes(linha[11])
        if proximo in vistos:  # defesa contra um ciclo forjado
            break
        vistos.add(proximo)
        actual = proximo
    soltas = [linha for restantes in por_prev.values() for linha in restantes]
    return ordenadas, sorted(soltas, key=lambda linha: linha[1])


def cabecas(cursor) -> dict:
    """O `last_hash` declarado de cada cadeia."""
    cursor.execute("SELECT tenant_id, last_hash FROM platform.audit_heads")
    return {linha[0]: bytes(linha[1]) for linha in cursor.fetchall()}


def verificar(cursor, tenant: str | None = None, ancora: dict | None = None) -> list[str]:
    """Todos os achados. Lista vazia e uma cadeia intacta.

    Com `ancora` — o conteudo de um ficheiro escrito por `ancorar` —, compara
    tambem o **conjunto** de cadeias e o `row_hash` ancorado de cada uma. Sem
    ela, apagar as linhas de um tenant **e** a sua cabeca nao produzia achado
    nenhum: o verificador percorre o que existe, e o que deixou de existir nao
    esta em lado nenhum para ser percorrido. Apanhado pela revisao adversarial.
    """
    achados: list[str] = []
    por_cadeia = cadeias(cursor, tenant)
    declaradas = cabecas(cursor)

    for dono, linhas_por_id in sorted(por_cadeia.items(), key=lambda par: str(par[0])):
        nome = str(dono) if dono is not None else "(plataforma)"
        linhas, soltas = _por_ordem_da_cadeia(linhas_por_id)
        # **As `soltas` sao de duas especies, e dizer-lhes o mesmo era mentir
        # numa delas** (KAM-161). Uma linha fica fora da travessia por o seu
        # `prev_hash` nao ser o `row_hash` de ninguem — orfa —, **ou** por ele
        # ser o de uma linha que ja tem quem a siga: a cadeia bifurca, e o
        # `pop(0)` leva uma das duas e deixa a outra. As duas saiam com a
        # mensagem da orfa, que numa bifurcacao afirma o contrario do que se
        # mede. `todos_os_elos` e o que as separa.
        todos_os_elos = {bytes(outra[11]) for outra in linhas_por_id}
        for linha in soltas:
            prev = bytes(linha[10])
            if prev in todos_os_elos:
                achados.append(
                    f"{nome}: elo partido na linha {linha[1]}: o seu prev_hash "
                    f"({prev.hex()[:16]}…) e o row_hash de uma linha que **ja tem** "
                    "quem a siga; a cadeia bifurca, e uma das duas foi inserida"
                )
            else:
                achados.append(
                    f"{nome}: a linha {linha[1]} nao esta na cadeia: o seu prev_hash "
                    f"({prev.hex()[:16]}…) nao e o row_hash de nenhuma outra, "
                    "e ela nao parte da genese"
                )
        anterior = GENESE
        for linha in linhas:
            (_, identificador, criado_at, actor_type, actor_id, action, entity,
             entity_id, turn_id, payload_hash, prev_hash, guardado) = linha
            prev_hash, guardado = bytes(prev_hash), bytes(guardado)
            # **Nao se confronta aqui o `prev_hash` com o elo anterior**, e a
            # razao e que nao pode falhar: o `_por_ordem_da_cadeia` constroi
            # `linhas` **seguindo** o `prev_hash`, pelo que toda a linha que ele
            # devolve o tem igual ao `anterior` por construcao. A guarda que
            # aqui estava era inalcancavel — codigo morto que dava a ilusao de
            # proteger —, e a prova por mutacao mostrou-o: troca-la por
            # `if False:` nao quebrava teste nenhum (KAM-161). O caso que ela
            # dizia apanhar e a bifurcacao, e essa e agora dita acima, de onde
            # ela de facto sai.
            calculado = row_hash(prev_hash, criado_at, dono, actor_type, actor_id,
                                 action, entity, entity_id, turn_id,
                                 bytes(payload_hash))
            if calculado != guardado:
                achados.append(
                    f"{nome}: hash errado na linha {identificador}: guardado "
                    f"{guardado.hex()[:16]}…, recalculado {calculado.hex()[:16]}…; "
                    "alguem alterou uma coluna"
                )
            anterior = guardado
        declarada = declaradas.get(dono)
        if declarada is None:
            achados.append(f"{nome}: ha {len(linhas)} linha(s) e nao ha cabeca")
        elif declarada != anterior:
            achados.append(
                f"{nome}: cabeca errada: declara {declarada.hex()[:16]}… e o ultimo elo "
                f"e {anterior.hex()[:16]}…; alguem apagou linhas do fim da cadeia"
            )

    for dono in declaradas:
        if dono not in por_cadeia and (tenant is None or str(dono) == tenant):
            achados.append(
                f"{str(dono) if dono else '(plataforma)'}: ha cabeca e nao ha linha nenhuma"
            )

    achados.extend(_contra_a_ancora(por_cadeia, ancora))
    return achados


def _contra_a_ancora(por_cadeia: dict, ancora: dict | None) -> list[str]:
    """O que so a ancora de ontem apanha: uma cadeia que desapareceu inteira."""
    if not ancora:
        return []
    achados: list[str] = []
    # **Pelo nome, e nao pelo `tenant_id`** (KAM-161). O `por_cadeia` vem da base
    # e e indexado pelo `tenant_id` tal como o driver o devolve — um `UUID` —, e
    # o `nome` vem do JSON da ancora, que so tem texto. O `dono` reconstruido a
    # partir do `nome` nunca era chave do `por_cadeia`, e o segundo ramo desta
    # funcao rebentava com `KeyError` em vez de dar o achado. Nao era
    # inalcancavel por logica, como o do laco da travessia: era inalcancavel por
    # **avariar** — e ninguem dava por isso porque exige uma cadeia viva **e**
    # o elo ancorado em falta, que teste nenhum construia.
    por_nome = {
        ("" if dono is None else str(dono)): linhas
        for dono, linhas in por_cadeia.items()
    }
    for nome, registo in sorted((ancora.get("cadeias") or {}).items()):
        legivel = nome or "(plataforma)"
        if nome not in por_nome:
            achados.append(
                f"{legivel}: a ancora de {ancora.get('dia')} tem esta cadeia e ela "
                "desapareceu inteira — linhas e cabeca"
            )
            continue
        ancorado = registo.get("row_hash")
        if ancorado and not any(
            bytes(linha[11]).hex() == ancorado for linha in por_nome[nome]
        ):
            achados.append(
                f"{legivel}: o row_hash ancorado em {ancora.get('dia')} "
                f"({ancorado[:16]}…) ja nao existe na cadeia"
            )
    return achados


def ancorar(cursor, dia: datetime.date | None = None, destino: Path | None = None) -> Path:
    """Escreve a ancora do dia: o ultimo `row_hash` por cadeia.

    O ficheiro e **reproduzivel a partir da base**: as mesmas linhas dao o
    mesmo ficheiro, byte a byte (chaves ordenadas, sem espacos variaveis). E o
    que torna a ancora util — duas copias que divirjam dizem que uma das bases
    mudou.
    """
    dia = dia or datetime.datetime.now(datetime.timezone.utc).date()
    # `Path("")` e `WindowsPath('.')` e e **verdadeiro**: a forma anterior
    # (`destino or Path(os.environ.get(..., "")) or ANCORA_POR_OMISSAO`) nunca
    # chegava ao ultimo ramo, e sem `--destino` a ancora caia no directorio de
    # trabalho de quem corre o job. Nenhum teste chamava `ancorar` sem destino,
    # por isso ninguem o via. Apanhado pela revisao adversarial.
    if destino is not None:
        pasta = destino
    elif os.environ.get(VARIAVEL_DA_ANCORA):
        pasta = Path(os.environ[VARIAVEL_DA_ANCORA])
    else:
        pasta = ANCORA_POR_OMISSAO
    pasta.mkdir(parents=True, exist_ok=True)

    cursor.execute(
        "SELECT a.tenant_id, max(a.id) FROM platform.audit_log a "
        # A fronteira do dia em **UTC**, e nao no fuso da sessao: um
        # `timestamptz < date` promove o `date` com o `TimeZone` da sessao, e
        # com `Africa/Luanda` a mesma base no mesmo dia dava outra ancora. A
        # afirmacao «reproduzivel a partir da base» era falsa fora de uma
        # sessao de fuso fixo. Apanhado pela revisao adversarial.
        " WHERE a.criado_at < ((%s::date + 1)::timestamp AT TIME ZONE 'UTC') "
        " GROUP BY a.tenant_id",
        (dia.isoformat(),),
    )
    ultimos = {linha[0]: linha[1] for linha in cursor.fetchall()}
    conteudo: dict = {}
    for dono, identificador in ultimos.items():
        cursor.execute(
            "SELECT row_hash FROM platform.audit_log WHERE id = %s", (identificador,)
        )
        conteudo[str(dono) if dono is not None else ""] = {
            "ultimo_id": int(identificador),
            "row_hash": bytes(cursor.fetchone()[0]).hex(),
        }

    caminho = pasta / f"audit-{dia.isoformat()}.json"
    caminho.write_text(
        json.dumps({"dia": dia.isoformat(), "cadeias": conteudo},
                   indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )
    return caminho


def main(argv: list[str] | None = None) -> int:
    analisador = argparse.ArgumentParser(
        prog="auditoria", description=__doc__.split("\n")[0]
    )
    analisador.add_argument("accao", choices=("verificar", "ancorar"))
    analisador.add_argument("--tenant", default=None, help="so esta cadeia")
    analisador.add_argument(
        "--ancora", default=None,
        help="ficheiro de ancora de um dia anterior; sem ele, uma cadeia que "
             "desapareca inteira passa despercebida",
    )
    analisador.add_argument("--dia", default=None, help="AAAA-MM-DD; por omissao, hoje em UTC")
    analisador.add_argument("--destino", default=None, help="pasta da ancora")
    analisador.add_argument(
        "--papel", default=None,
        help="identidade de base de dados: `batch` (omissao, ve tudo) ou `audit`",
    )
    argumentos = analisador.parse_args(argv)

    cursor = _cursor(argumentos.papel)
    if argumentos.papel == "audit" and argumentos.tenant:
        # O `kamba_audit` e `NOBYPASSRLS`: sem contexto ve zero linhas, e o
        # verificador respondia «cadeia intacta» sobre nada. A primeira versao
        # prometia este `--papel` no docstring e nao o tinha no `argparse`.
        cursor.execute("SELECT set_config('app.tenant_id', %s, false)", (argumentos.tenant,))
    if argumentos.accao == "verificar":
        ancora = None
        if argumentos.ancora:
            ancora = json.loads(Path(argumentos.ancora).read_text(encoding="utf-8"))
        achados = verificar(cursor, argumentos.tenant, ancora)
        if achados:
            print(
                f"SEV1 auditoria: {len(achados)} achado(s) na cadeia de auditoria. "
                "A cadeia e prova; um achado aqui e um incidente, nao um aviso.",
                file=sys.stderr,
            )
            for achado in achados:
                print(f"  {achado}", file=sys.stderr)
            return 2
        print("auditoria: cadeia intacta")
        return 0

    dia = datetime.date.fromisoformat(argumentos.dia) if argumentos.dia else None
    destino = Path(argumentos.destino) if argumentos.destino else None
    caminho = ancorar(cursor, dia, destino)
    print(f"auditoria: ancora escrita em {caminho}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
