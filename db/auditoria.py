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

Tres coisas, e o verificador distingue-as porque a resposta operacional e
diferente:

    elo partido      o `prev_hash` de uma linha nao e o `row_hash` da anterior.
                     Alguem **apagou** ou **inseriu** uma linha no meio.
    hash errado      o `row_hash` nao bate com o que as colunas dao. Alguem
                     **alterou** uma coluna.
    cabeca errada    o `audit_heads` nao aponta para o ultimo elo. A cadeia
                     esta inteira e a cabeca nao: ou a cabeca foi mexida, ou
                     uma linha foi apagada **do fim**, que e o unico caso que
                     o elo partido nao apanha.

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


def row_hash(prev: bytes, tenant, actor_type, actor_id, action, entity,
             entity_id, turn_id, payload_hash: bytes) -> bytes:
    """A formula de um elo, em Python. Ver o docstring do modulo."""
    partes = (
        prev.hex(),
        "" if tenant is None else str(tenant),
        actor_type, actor_id, action, entity, entity_id,
        "" if turn_id is None else turn_id,
        payload_hash.hex(),
    )
    return hashlib.sha256(SEPARADOR.join(partes).encode("utf-8")).digest()


def _cursor():
    """Uma ligacao de auditoria. Le o registo e mais nada.

    `kamba_audit` nao tem `BYPASSRLS`, pelo que ve as cadeias dos tenants a
    que o contexto lhe der acesso — e **nao** ve a cadeia de plataforma. Quem
    verifica tudo e o `kamba_batch`, que e quem corre o *job* nocturno; o
    `--papel` existe para que uma verificacao pontual de um tenant possa
    correr com o papel estreito.
    """
    return ligacao.ligar(os.environ.get("KAMBA_AUDIT_PAPEL", "batch")).cursor()


def cadeias(cursor, tenant: str | None = None) -> dict:
    """As linhas de `audit_log` agrupadas por cadeia, por ordem de escrita."""
    sql = (
        "SELECT tenant_id, id, actor_type, actor_id, action, entity, entity_id, "
        "       turn_id, payload_hash, prev_hash, row_hash "
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


def cabecas(cursor) -> dict:
    """O `last_hash` declarado de cada cadeia."""
    cursor.execute("SELECT tenant_id, last_hash FROM platform.audit_heads")
    return {linha[0]: bytes(linha[1]) for linha in cursor.fetchall()}


def verificar(cursor, tenant: str | None = None) -> list[str]:
    """Todos os achados. Lista vazia e uma cadeia intacta."""
    achados: list[str] = []
    por_cadeia = cadeias(cursor, tenant)
    declaradas = cabecas(cursor)

    for dono, linhas in sorted(por_cadeia.items(), key=lambda par: str(par[0])):
        nome = str(dono) if dono is not None else "(plataforma)"
        anterior = GENESE
        for linha in linhas:
            (_, identificador, actor_type, actor_id, action, entity, entity_id,
             turn_id, payload_hash, prev_hash, guardado) = linha
            prev_hash, guardado = bytes(prev_hash), bytes(guardado)
            if prev_hash != anterior:
                achados.append(
                    f"{nome}: elo partido na linha {identificador}: o prev_hash e "
                    f"{prev_hash.hex()[:16]}… e o elo anterior deu {anterior.hex()[:16]}…; "
                    "alguem apagou ou inseriu uma linha"
                )
            calculado = row_hash(prev_hash, dono, actor_type, actor_id, action,
                                 entity, entity_id, turn_id, bytes(payload_hash))
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
    return achados


def ancorar(cursor, dia: datetime.date | None = None, destino: Path | None = None) -> Path:
    """Escreve a ancora do dia: o ultimo `row_hash` por cadeia.

    O ficheiro e **reproduzivel a partir da base**: as mesmas linhas dao o
    mesmo ficheiro, byte a byte (chaves ordenadas, sem espacos variaveis). E o
    que torna a ancora util — duas copias que divirjam dizem que uma das bases
    mudou.
    """
    dia = dia or datetime.datetime.now(datetime.timezone.utc).date()
    pasta = destino or Path(os.environ.get(VARIAVEL_DA_ANCORA, "")) or ANCORA_POR_OMISSAO
    pasta.mkdir(parents=True, exist_ok=True)

    cursor.execute(
        "SELECT a.tenant_id, max(a.id) FROM platform.audit_log a "
        " WHERE a.criado_at < (%s::date + 1) GROUP BY a.tenant_id",
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
    analisador.add_argument("--dia", default=None, help="AAAA-MM-DD; por omissao, hoje em UTC")
    analisador.add_argument("--destino", default=None, help="pasta da ancora")
    argumentos = analisador.parse_args(argv)

    cursor = _cursor()
    if argumentos.accao == "verificar":
        achados = verificar(cursor, argumentos.tenant)
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
