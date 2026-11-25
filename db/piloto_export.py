"""A exportacao do Piloto para a medicao de H1, H8 e H9 (KAM-109).

    python db/piloto_export.py exportar --coorte <csv> (--sintetico | --real) [--ate AAAA-MM-DD]
                                        [--saida <json>]
    python db/piloto_export.py produtos --coorte <csv> --pme P01 [--saida <csv>]

O nome do comando e `piloto-export`, e o *job* e `ops_piloto_export`. **Le, e
nao escreve nada.** As contas e as regras sao do `tools/piloto` (`python -m
piloto medir`), sobre a exportacao **congelada**; este comando so a produz.

## A coorte e um ficheiro, e nao uma tabela

    pme,tenant_id,saida_dia,motivo
    P01,<uuid>,,
    P02,<uuid>,2027-01-19,sem_uso_semana_2

O ordinal `P01`..`P99` e a unica forma como uma PME aparece fora da base. Uma
linha com `saida_dia` e uma PME que saiu da coorte (Regra 4: quem nao usa na
semana 2 sai e e substituida); fica na exportacao, com `na_coorte: false`,
porque as substituicoes tambem se reportam. Nao ha tabela de coorte porque o
KAM-109 prepara-se **sem esquema novo**.

## O que cada campo e, e de onde vem

| Campo | Fonte |
|---|---|
| `activada_em` | a primeira entrada em `ativo` no `tenant_state_log` — a mesma regra da `churn_dono_at` (`0063`) —, no dia do `fuso_horario` do tenant |
| `self_service` | o contrario do `intervencao_humana` da `v_onboarding_kpis` (KAM-092): nenhum `review_case` que nao seja de auditoria |
| `dpa_aceite` | um aceite de qualquer versao do documento `dpa` em `contract_acceptance` (`0040`) |
| `conversas` | as conversas **iniciadas** no dia, pela regra do `h6-export` (mesmo contacto, pausa > 24 h, nas mensagens de saida), sem as conversas de teste em producao (`conversations.is_test`, KAM-202) |
| `accoes_dono` | as linhas do `audit_log` com `actor_type = 'owner'` |
| `actualizacoes_catalogo` | as do dono sobre `offer_terms` com `price.update` ou `stock.adjust` |
| `handoffs` | os `handoffs` abertos no dia (`opened_at`) |
| `custo_llm_usd`, `custo_meta_usd` | a `v_tenant_cost_daily` (KAM-081): a rubrica `llm`, e a soma das `meta_*` |
| `ciclos_pagos` | os `billing_cycles` em `paga`, com o `pagamento_confirmado` aceite que os pagou: `facilitador` se autenticado (`hmac` ou `consulta`), `ops` se confirmado por ops com dupla aprovacao (`0055`) |

## Os limites, ditos

* **«Accao do dono» conta por baixo.** O *echo* da app do dono so guarda o
  ultimo instante por canal (`channel_coexistence.ultimo_echo_em`, `0018`), e o
  `owner_actions` nao se le pelo lote (`0086`). O que fica sao as linhas do
  `audit_log` do dono — painel e canal do dono. Uma PME que so responde na
  app conta zero accoes. Medir o *echo* por dia era esquema novo.
* **As conversas sao as da linha do tempo de saida**, como no `h6-export`: uma
  conversa em que ninguem respondeu nao aparece.
* **Nenhum dia sem linhas aparece**, e no `tools/piloto` conta como zero.

## Sem pessoas

O `contact_id` **nao sai da base** — a consulta devolve um `dense_rank`, como a
do `h6-export` —, e a exportacao tem lista fechada de campos, verificada pelo
`tools/piloto/exportacao.py` antes de ser escrita. O `produtos` devolve o
`sku`, o nome, o preco e a disponibilidade: dados do negocio, e nao de pessoas.

## Papel

`kamba_batch`, sob `tenant_guard.tx_batch` com o *job* nomeado — o caminho do
`h6_export.py`. `0` feito, `2` erro de uso ou da base.
"""

from __future__ import annotations

import argparse
import csv
import datetime as dt
import io
import json
import re
import sys
from decimal import Decimal
from pathlib import Path
from typing import Any, Final

_AQUI = Path(__file__).resolve().parent
sys.path.insert(0, str(_AQUI))
sys.path.insert(0, str(_AQUI.parent / "tools"))

import h6_export  # noqa: E402 — a regra da conversa e a do KAM-081, e nao uma copia
from piloto import exportacao as forma  # noqa: E402

SAIDA_OK: Final = 0
SAIDA_ERRO: Final = 2

JOB: Final = "ops_piloto_export"

COLUNAS_DA_COORTE: Final = ("pme", "tenant_id", "saida_dia", "motivo")
_PME: Final = re.compile(r"^P\d{2}$")

SQL_ULTIMO_DIA: Final = "SELECT ((now() AT TIME ZONE 'Africa/Luanda')::date - 1)"

SQL_ACTIVACAO: Final = """
  SELECT t.id::text,
         (min(l.em) AT TIME ZONE t.fuso_horario)::date
    FROM platform.tenants t
    LEFT JOIN platform.tenant_state_log l
           ON l.tenant_id = t.id AND l.para = 'ativo'
   WHERE t.id = ANY(%s::uuid[])
   GROUP BY t.id, t.fuso_horario
"""

SQL_SELF_SERVICE: Final = """
  SELECT k.tenant_id::text, NOT k.intervencao_humana
    FROM platform.v_onboarding_kpis k
   WHERE k.tenant_id = ANY(%s::uuid[])
"""

SQL_DPA: Final = """
  SELECT DISTINCT a.tenant_id::text
    FROM platform.contract_acceptance a
    JOIN platform.contract_document d ON d.document_id = a.document_id
   WHERE d.tipo = 'dpa' AND a.tenant_id = ANY(%s::uuid[])
"""

#: As mensagens de saida, com o contacto trocado por um ordinal **na base** — a
#: forma do `SQL_MENSAGENS` do `h6-export` —, sem as de conversas de teste.
SQL_MENSAGENS: Final = """
  SELECT o.tenant_id::text,
         dense_rank() OVER (ORDER BY o.tenant_id, o.contact_id) AS contacto,
         o.created_at,
         (o.created_at AT TIME ZONE t.fuso_horario)::date AS dia
    FROM platform.outbound_messages o
    JOIN platform.tenants t ON t.id = o.tenant_id
    LEFT JOIN platform.conversations c ON c.id = o.conversation_id
   WHERE o.tenant_id = ANY(%s::uuid[])
     AND o.created_at >= %s
     AND NOT coalesce(c.is_test, false)
   ORDER BY o.tenant_id, contacto, o.created_at
"""

SQL_ACCOES_DO_DONO: Final = """
  SELECT a.tenant_id::text,
         (a.criado_at AT TIME ZONE t.fuso_horario)::date AS dia,
         count(*),
         count(*) FILTER (WHERE a.entity = 'offer_terms'
                            AND a.action IN ('price.update', 'stock.adjust'))
    FROM platform.audit_log a
    JOIN platform.tenants t ON t.id = a.tenant_id
   WHERE a.actor_type = 'owner' AND a.tenant_id = ANY(%s::uuid[])
   GROUP BY a.tenant_id, 2
"""

SQL_HANDOFFS: Final = """
  SELECT h.tenant_id::text,
         (h.opened_at AT TIME ZONE t.fuso_horario)::date AS dia,
         count(*)
    FROM platform.handoffs h
    JOIN platform.tenants t ON t.id = h.tenant_id
   WHERE h.tenant_id = ANY(%s::uuid[])
   GROUP BY h.tenant_id, 2
"""

SQL_CUSTO: Final = """
  SELECT tenant_id::text, dia,
         coalesce(sum(custo_usd) FILTER (WHERE rubrica = 'llm'), 0),
         coalesce(sum(custo_usd) FILTER (WHERE rubrica LIKE 'meta\\_%%'), 0)
    FROM platform.v_tenant_cost_daily
   WHERE tenant_id = ANY(%s::uuid[])
   GROUP BY tenant_id, dia
"""

#: Um ciclo pago, com a via da prova. A regra do «autenticado pelo facilitador»
#: e a da `0055` (`hmac` ou `consulta`); a de ops e o caminho de dupla
#: aprovacao (`manual` e `ops`). Um ciclo pago por outra via nao conta.
SQL_CICLOS_PAGOS: Final = """
  SELECT b.tenant_id::text,
         lower(b.periodo),
         b.valor_minor,
         min(e.currency),
         bool_or(e.authn_method IN ('hmac', 'consulta')),
         bool_or(e.authn_method = 'manual' AND e.actor_kind = 'ops')
    FROM platform.billing_cycles b
    JOIN platform.payment_events e
      ON e.billing_cycle_id = b.id AND e.tenant_id = b.tenant_id
   WHERE b.estado = 'paga'
     AND e.tipo_evento = 'pagamento_confirmado'
     AND e.decisao = 'aceite'
     AND b.tenant_id = ANY(%s::uuid[])
   GROUP BY b.tenant_id, b.id, b.periodo, b.valor_minor
"""

#: O universo do sorteio de H8: o que a PME tem no catalogo, publicado ou
#: pausado. «Disponivel» no sistema e publicado e com stock, ou sem quantidade
#: declarada (*proposta*, do protocolo).
SQL_PRODUTOS: Final = """
  SELECT o.sku,
         o.nome,
         o.preco_minor,
         (o.estado = 'publicado'
          AND (o.stock_quantidade IS NULL
               OR o.stock_quantidade - o.stock_reservada > 0))
    FROM platform.offer_terms o
   WHERE o.tenant_id = %s::uuid
     AND o.deleted_at IS NULL
     AND o.estado IN ('publicado', 'pausado')
   ORDER BY o.sku
"""


class ErroDeUso(Exception):
    """O comando nao pode correr como foi pedido."""


# ------------------------------------------------------------------- coorte


def ler_coorte(texto: str) -> list[dict[str, Any]]:
    leitor = csv.reader(io.StringIO(texto))
    try:
        cabecalho = next(leitor)
    except StopIteration:
        raise ErroDeUso("coorte vazia") from None
    if tuple(cabecalho) != COLUNAS_DA_COORTE:
        raise ErroDeUso(f"coorte: colunas {cabecalho}, esperava {list(COLUNAS_DA_COORTE)}")
    linhas = []
    for numero, linha in enumerate(leitor, start=2):
        if not any(linha):
            continue
        if len(linha) != len(COLUNAS_DA_COORTE):
            raise ErroDeUso(f"coorte linha {numero}: {len(linha)} colunas")
        pme, tenant_id, saida_dia, motivo = (c.strip() for c in linha)
        if not _PME.match(pme):
            raise ErroDeUso(f"coorte linha {numero}: o ordinal e P01..P99")
        if bool(saida_dia) != bool(motivo):
            raise ErroDeUso(f"coorte linha {numero}: saida_dia e motivo vao juntos")
        if motivo and motivo not in forma.MOTIVOS_DE_SAIDA:
            raise ErroDeUso(f"coorte linha {numero}: motivo fora de {sorted(forma.MOTIVOS_DE_SAIDA)}")
        try:
            saida = dt.date.fromisoformat(saida_dia) if saida_dia else None
        except ValueError:
            raise ErroDeUso(f"coorte linha {numero}: saida_dia invalido") from None
        linhas.append({"pme": pme, "tenant_id": tenant_id.lower(), "saida": saida, "motivo": motivo})
    if not linhas:
        raise ErroDeUso("coorte sem PMEs")
    return linhas


# --------------------------------------------------------------- montagem


def conversas_por_dia(mensagens: list[h6_export.Mensagem]) -> dict[tuple[str, dt.date], int]:
    """As conversas **iniciadas** por tenant e dia, pela regra do `h6-export`."""
    contagem: dict[tuple[str, dt.date], int] = {}
    for conversa in h6_export.segmentar(mensagens):
        chave = (conversa.tenant_id, conversa.mensagens[0].dia)
        contagem[chave] = contagem.get(chave, 0) + 1
    return contagem


def _texto(valor: Decimal) -> str:
    return format(Decimal(valor), "f")


def montar(
    coorte: list[dict[str, Any]],
    sintetico: bool,
    ultimo_dia: dt.date,
    activacao: dict[str, dt.date | None],
    self_service: dict[str, bool],
    dpa: set[str],
    conversas: dict[tuple[str, dt.date], int],
    accoes: dict[tuple[str, dt.date], tuple[int, int]],
    handoffs: dict[tuple[str, dt.date], int],
    custo: dict[tuple[str, dt.date], tuple[Decimal, Decimal]],
    ciclos: list[tuple[str, dt.date, int, str, bool, bool]],
) -> dict[str, Any]:
    """A exportacao inteira, sem tocar na base. E o que o ensaio sem base mede."""
    pmes = []
    for linha in coorte:
        tenant = linha["tenant_id"]
        dias: dict[dt.date, dict[str, Any]] = {}

        def dia(data: dt.date) -> dict[str, Any]:
            return dias.setdefault(
                data,
                {"conversas": 0, "accoes_dono": 0, "actualizacoes_catalogo": 0,
                 "handoffs": 0, "custo_llm_usd": "0", "custo_meta_usd": "0"},
            )

        for (t, data), n in conversas.items():
            if t == tenant and data <= ultimo_dia:
                dia(data)["conversas"] = n
        for (t, data), (todas, catalogo) in accoes.items():
            if t == tenant and data <= ultimo_dia:
                dia(data)["accoes_dono"] = todas
                dia(data)["actualizacoes_catalogo"] = catalogo
        for (t, data), n in handoffs.items():
            if t == tenant and data <= ultimo_dia:
                dia(data)["handoffs"] = n
        for (t, data), (llm, meta) in custo.items():
            if t == tenant and data <= ultimo_dia:
                dia(data)["custo_llm_usd"] = _texto(llm)
                dia(data)["custo_meta_usd"] = _texto(meta)
        pagos = []
        for t, inicio, valor, moeda, facilitador, ops in ciclos:
            if t != tenant or inicio > ultimo_dia or not (facilitador or ops):
                continue
            pagos.append({"inicio": inicio.isoformat(), "valor_minor": int(valor),
                          "moeda": moeda.strip(), "via": "facilitador" if facilitador else "ops"})
        activada = activacao.get(tenant)
        pmes.append(
            {
                "pme": linha["pme"],
                "tenant_id": tenant,
                "na_coorte": linha["saida"] is None,
                "saida": None if linha["saida"] is None
                else {"dia": linha["saida"].isoformat(), "motivo": linha["motivo"]},
                "activada_em": None if activada is None or activada > ultimo_dia
                else activada.isoformat(),
                "self_service": self_service.get(tenant),
                "dpa_aceite": tenant in dpa,
                "dias": {d.isoformat(): v for d, v in sorted(dias.items())},
                "ciclos_pagos": sorted(pagos, key=lambda c: c["inicio"]),
            }
        )
    resultado = {
        "formato": forma.FORMATO,
        "sintetico": sintetico,
        "ultimo_dia": ultimo_dia.isoformat(),
        "pmes": pmes,
    }
    forma.de_objecto(resultado)  # a lista fechada, antes de sair daqui
    return resultado


# ----------------------------------------------------------------- leitura


def exportar(
    cursor: Any, coorte: list[dict[str, Any]], sintetico: bool, ate: dt.date | None = None
) -> dict[str, Any]:
    """A exportacao ate ao dia `ate`, inclusive; por omissao, ontem em Luanda.

    Um `ate` mais tarde do que ontem exporta um dia **incompleto**: o comando
    recusa-o, e so o ensaio contra a base o pede, porque o `audit_log` so se
    escreve com o instante de agora.
    """
    tenants = [linha["tenant_id"] for linha in coorte]
    if len(set(tenants)) != len(tenants):
        raise ErroDeUso("coorte: tenant repetido")
    cursor.execute(SQL_ULTIMO_DIA)
    (ontem,) = cursor.fetchone()
    ultimo_dia = ontem if ate is None else ate

    cursor.execute(SQL_ACTIVACAO, (tenants,))
    activacao = {t: d for t, d in cursor.fetchall()}
    desconhecidos = sorted(set(tenants) - set(activacao))
    if desconhecidos:
        raise ErroDeUso(f"coorte: tenant(s) que nao existem: {', '.join(desconhecidos)}")
    cursor.execute(SQL_SELF_SERVICE, (tenants,))
    self_service = {t: bool(s) for t, s in cursor.fetchall()}
    cursor.execute(SQL_DPA, (tenants,))
    dpa = {t for (t,) in cursor.fetchall()}

    datas = [d for d in activacao.values() if d is not None]
    desde = (min(datas) if datas else ultimo_dia) - dt.timedelta(days=1)
    cursor.execute(SQL_MENSAGENS, (tenants, dt.datetime.combine(desde, dt.time(), dt.timezone.utc)))
    mensagens = [
        h6_export.Mensagem(t, int(c), instante, dia, False, None)
        for t, c, instante, dia in cursor.fetchall()
    ]
    cursor.execute(SQL_ACCOES_DO_DONO, (tenants,))
    accoes = {(t, d): (int(n), int(c)) for t, d, n, c in cursor.fetchall()}
    cursor.execute(SQL_HANDOFFS, (tenants,))
    handoffs = {(t, d): int(n) for t, d, n in cursor.fetchall()}
    cursor.execute(SQL_CUSTO, (tenants,))
    custo = {(t, d): (Decimal(l), Decimal(m)) for t, d, l, m in cursor.fetchall()}
    cursor.execute(SQL_CICLOS_PAGOS, (tenants,))
    ciclos = [
        (t, inicio, int(v), str(moeda), bool(f), bool(o))
        for t, inicio, v, moeda, f, o in cursor.fetchall()
    ]
    return montar(
        coorte, sintetico, ultimo_dia, activacao, self_service, dpa,
        conversas_por_dia(mensagens), accoes, handoffs, custo, ciclos,
    )


def produtos(cursor: Any, coorte: list[dict[str, Any]], pme: str) -> str:
    linha = next((l for l in coorte if l["pme"] == pme), None)
    if linha is None:
        raise ErroDeUso(f"{pme} nao esta na coorte")
    cursor.execute(SQL_PRODUTOS, (linha["tenant_id"],))
    saida = io.StringIO()
    escritor = csv.writer(saida, lineterminator="\n")
    escritor.writerow(["produto_id", "nome", "preco_minor", "disponivel"])
    for sku, nome, preco, disponivel in cursor.fetchall():
        escritor.writerow([sku, nome, "" if preco is None else int(preco),
                           "sim" if disponivel else "nao"])
    return saida.getvalue()


# --------------------------------------------------------------------- CLI


def _analisador() -> argparse.ArgumentParser:
    analisador = argparse.ArgumentParser(prog="piloto-export", description=__doc__.split("\n")[0])
    comandos = analisador.add_subparsers(dest="comando", required=True)
    exporta = comandos.add_parser("exportar", help="a exportacao do Piloto, em JSON")
    exporta.add_argument("--coorte", type=Path, required=True)
    marca = exporta.add_mutually_exclusive_group(required=True)
    marca.add_argument("--sintetico", action="store_true",
                       help="dados de ensaio: a exportacao e o relatorio saem marcados")
    marca.add_argument("--real", action="store_true")
    exporta.add_argument("--ate", type=dt.date.fromisoformat, default=None,
                         help="ultimo dia exportado (omissao: ontem em Luanda)")
    exporta.add_argument("--saida", type=Path)
    prod = comandos.add_parser("produtos", help="o catalogo de uma PME, para o sorteio de H8")
    prod.add_argument("--coorte", type=Path, required=True)
    prod.add_argument("--pme", required=True)
    prod.add_argument("--saida", type=Path)
    return analisador


def main(argv: list[str] | None = None) -> int:
    argumentos = _analisador().parse_args(argv)
    try:
        coorte = ler_coorte(argumentos.coorte.read_text(encoding="utf-8"))
    except (ErroDeUso, OSError) as erro:
        print(f"piloto-export: {erro}", file=sys.stderr)
        return SAIDA_ERRO

    import ligacao
    import pg8000.dbapi
    from kamba_core import tenant_guard

    try:
        conexao = ligacao.ligar("batch")
    except ligacao.ConfiguracaoEmFalta as erro:
        print(f"piloto-export: {erro}", file=sys.stderr)
        return SAIDA_ERRO
    try:
        with tenant_guard.tx_batch(conexao, JOB) as cursor:
            if argumentos.comando == "exportar":
                cursor.execute(SQL_ULTIMO_DIA)
                (ontem,) = cursor.fetchone()
                if argumentos.ate is not None and argumentos.ate > ontem:
                    raise ErroDeUso(f"--ate {argumentos.ate}: o ultimo dia completo e {ontem}")
                texto = json.dumps(
                    exportar(cursor, coorte, argumentos.sintetico, argumentos.ate),
                    ensure_ascii=False, indent=2,
                ) + "\n"
            else:
                texto = produtos(cursor, coorte, argumentos.pme)
    except pg8000.dbapi.DatabaseError as erro:
        print(f"piloto-export: a base recusou: {erro}", file=sys.stderr)
        return SAIDA_ERRO
    except (ErroDeUso, forma.ExportacaoInvalida, ValueError) as erro:
        print(f"piloto-export: {erro}", file=sys.stderr)
        return SAIDA_ERRO
    finally:
        conexao.close()
    if argumentos.saida is None:
        sys.stdout.write(texto)
    else:
        argumentos.saida.write_bytes(texto.encode("utf-8"))
    return SAIDA_OK


if __name__ == "__main__":
    raise SystemExit(main())
