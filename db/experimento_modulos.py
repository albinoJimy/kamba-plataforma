"""O experimento dos modulos de entrada: leitura, reproducao, decisao e coorte (KAM-127).

    python db/experimento_modulos.py ler        [--agora ISO] [--limiares <yaml>]
    python db/experimento_modulos.py reproduzir [--agora ISO] [--amostra 5]
    python db/experimento_modulos.py decidir    --incidentes <json> [--agora ISO] [--data AAAA-MM-DD]
                                                [--registar --modulo M [--decisao D] --responsavel STAFF
                                                 --justificacao TEXTO [--revisao-em AAAA-MM-DD]]
    python db/experimento_modulos.py excluir    --tenant UUID --motivo equipa|teste --por STAFF

`STAFF` e a identidade de quem da equipa decide ou exclui (a do IdP, §3.65 do
dicionario), como o `revisor_id` da revisao humana: nunca um cliente.

O nome do comando no canon e `experimento-modulos`, e o *job* e
`ops_experimento_modulos`. **Nenhum limiar vive aqui**: sao os do
`config/experimento_modulos.yaml`, ratificados pelo fundador a 2026-11-24 e pre-registadas em
`docs/tecnica/evidencia/validacao/H10_H12_Modulos_Entrada.md`. E **nenhuma
decisao fica registada sem um humano**: o `decidir` so escreve em
`platform.module_decisions` com `--registar` e o nome de quem responde.

## O que cada subcomando faz

* **`ler`** — as tres hipoteses com n/N e o intervalo de Wilson 95%: a H10 (e o
  uso de cada modulo), a H11, e a H12 (as PMEs que pagam por um modulo isolado,
  e o racio custo / preco de cada modulo por semana). Os censurados contam-se a
  parte e **nao** entram no N.
* **`reproduzir`** — o criterio 3: a metrica recalculada **em Python**, a partir
  das linhas cruas, para uma amostra de tenants da coorte, e confrontada com as
  funcoes da base. Codigo `1` com qualquer diferenca.
* **`decidir`** — a regra pre-registada (`kamba_core.modulos.experimento`) sobre
  a leitura e os incidentes de conteudo, que se contam **a mao** a partir do
  golden e da auditoria do KAM-125 (nao ha tabela de incidentes) e entram por um
  JSON `{"modulo": {"alta": n, "media": n}}`. A regra **propoe** para os quatro;
  o `--registar` grava **um** modulo, com a decisao de quem decide (`--decisao`,
  por omissao a proposta), e a proposta fica nas `metricas` ao lado.
* **`excluir`** — um tenant da equipa ou de teste fora da coorte, so de
  acrescentar.

## A semana do custo (criterio de abate (b)) e uma leitura

O preco de teste e mensal e o criterio e semanal. O racio de uma semana e o
custo do modulo nessa semana sobre o preco **semanal** — o mensal vezes 12/52 —
somados sobre os tenants da coorte cujo plano tem preco de teste para o modulo.
A semana e a ISO de `Africa/Luanda`, e **so as semanas completas** contam: a
semana de `agora` fica de fora (uma segunda-feira de manha escondia duas semanas
acima do limiar), e uma semana sem custo conta como zero, e nao desaparece (duas
semanas acima separadas por uma vazia nao sao «seguidas»). E uma leitura do
criterio, e esta escrita.

## O que a reproducao reproduz

A **agregacao**, e nao as definicoes: o Python le as linhas cruas e faz as
contas da janela, da censura, da entrada e da activacao por outro caminho, mas
a coorte, o dono (`owner_contact_id`) e o canal e a vertical **actuais** sao os
mesmos predicados das funcoes. Um erro de definicao comum a ambos da diferenca 0.

## Papel

`kamba_batch`, sob `tenant_guard.tx_batch` com o *job* nomeado — o caminho do
`h12_export.py`.

## Codigos de saida

`0` sem achados, `1` com diferencas (`reproduzir`), `2` erro de uso ou da base.
"""

from __future__ import annotations

import argparse
import datetime as dt
import json
import sys
import uuid
from collections import defaultdict
from collections.abc import Iterable, Mapping
from dataclasses import asdict, dataclass
from fractions import Fraction
from pathlib import Path
from typing import Any, Final

sys.path.insert(0, str(Path(__file__).resolve().parent))
_RAIZ = Path(__file__).resolve().parents[1]

JOB: Final = "ops_experimento_modulos"
SAIDA_OK: Final = 0
SAIDA_DIFERENCAS: Final = 1
SAIDA_ERRO: Final = 2

MODULOS: Final = ("catalogo", "foto", "social", "orcamento")
#: Angola nao tem hora de verao: UTC+1 fixo, como o `Africa/Luanda` da base.
LUANDA: Final = dt.timezone(dt.timedelta(hours=1))
LIMIARES: Final = _RAIZ / "config" / "experimento_modulos.yaml"


class ErroDeUso(ValueError):
    """Argumentos que nao servem: codigo 2, sem tocar na base."""


# ------------------------------------------------------------------ SQL lido

SQL_H10 = "SELECT * FROM platform.experimento_h10(%s, %s) ORDER BY tenant_id"
SQL_H11 = "SELECT * FROM platform.experimento_h11(%s, %s) ORDER BY tenant_id"

#: As PMEs da coorte de `agora` que pagam por um modulo isolado, por modulo
#: (`v_h12_pagantes`, que ja so tem a coorte de `now()`).
SQL_PAGANTES = """
SELECT p.modulo, count(DISTINCT p.tenant_id)
  FROM platform.v_h12_pagantes p
  JOIN platform.experimento_coorte(%s) c ON c.tenant_id = p.tenant_id
 GROUP BY p.modulo
"""

#: A margem do mes de `agora` por modulo, somada sobre os tenants da coorte
#: (`v_h12`, KAM-124). Negativa e o criterio (b).
SQL_MARGEM = """
SELECT h.modulo, sum(h.margem_minor)
  FROM platform.v_h12 h
  JOIN platform.experimento_coorte(%s) c ON c.tenant_id = h.tenant_id
 WHERE h.mes = platform.ten_periodo(%s)
   AND h.margem_minor IS NOT NULL
 GROUP BY h.modulo
"""

#: O custo de cada semana ISO (Luanda) e o preco semanal, por modulo, sobre os
#: tenants da coorte cujo plano tem preco de teste para o modulo.
SQL_CUSTO_SEMANAL = """
WITH c AS (SELECT tenant_id FROM platform.experimento_coorte(%s)),
     precos AS (
       SELECT t.id AS tenant_id, p.modulo, p.preco_teste_minor
         FROM platform.tenants t
         JOIN c ON c.tenant_id = t.id
         JOIN platform.module_test_prices p ON p.plano = t.plano
     ),
     custo AS (
       SELECT l.modulo,
              to_char(l.ocorrido_em AT TIME ZONE 'Africa/Luanda', 'IYYY-"W"IW') AS semana,
              sum(l.custo_minor) AS custo_minor
         FROM platform.module_cost_ledger l
         JOIN precos p ON p.tenant_id = l.tenant_id AND p.modulo = l.modulo
        WHERE date_trunc('week', l.ocorrido_em AT TIME ZONE 'Africa/Luanda')
              < date_trunc('week', %s AT TIME ZONE 'Africa/Luanda')
        GROUP BY 1, 2
     )
SELECT custo.modulo, custo.semana, custo.custo_minor,
       (SELECT sum(p.preco_teste_minor) FROM precos p WHERE p.modulo = custo.modulo)
  FROM custo
 ORDER BY custo.modulo, custo.semana
"""

SQL_REGISTAR_DECISAO = """
INSERT INTO platform.module_decisions
  (modulo, data_decisao, metricas, criterio, decisao, responsavel, justificacao, revisao_em)
VALUES (%s, %s, %s::jsonb, %s, %s, %s, %s, %s)
"""

SQL_EXCLUIR = """
INSERT INTO platform.module_experiment_exclusions (tenant_id, motivo, registado_por)
VALUES (%s::uuid, %s, %s)
"""

# --- as linhas cruas da reproducao ----------------------------------------------

SQL_CRU_COORTE = """
SELECT l.tenant_id, min(l.ocorrido_em)
  FROM platform.events_log l
  JOIN platform.tenants t ON t.id = l.tenant_id
 WHERE l.tipo = 'tenant.provisioned' AND l.ocorrido_em <= %s AND t.tipo = 'pme'
   AND l.tenant_id NOT IN (SELECT tenant_id FROM platform.module_experiment_exclusions)
 GROUP BY l.tenant_id
"""
SQL_CRU_CATALOGO = """
SELECT tenant_id, confirmado_at FROM platform.catalog_ingestions
 WHERE tenant_id = ANY(%s::uuid[]) AND estado = 'publicada' AND confirmado_at IS NOT NULL
"""
SQL_CRU_FOTO = """
SELECT tenant_id, atualizado_at FROM platform.image_jobs
 WHERE tenant_id = ANY(%s::uuid[]) AND escolhida AND NOT sintetica
"""
SQL_CRU_EVENTOS = """
SELECT tenant_id, tipo, ocorrido_em, envelope->'payload'->>'contact_id',
       envelope->'payload'->>'conversation_id', envelope->'payload'->>'canal'
  FROM platform.events_log
 WHERE tenant_id = ANY(%s::uuid[])
   AND tipo IN ('content.approved', 'quote.sent', 'agent.replied')
"""
SQL_CRU_DONOS = """
SELECT id, owner_contact_id FROM platform.tenants WHERE id = ANY(%s::uuid[])
"""
SQL_CRU_CONVERSAS = """
SELECT tenant_id, id, is_test FROM platform.conversations
 WHERE tenant_id = ANY(%s::uuid[])
"""
SQL_CRU_ATENDIMENTO = """
SELECT t.id,
       EXISTS (SELECT 1 FROM platform.tenant_channels ch WHERE ch.tenant_id = t.id
                AND ch.estado = 'ativo' AND ch.vertical IN ('vendedor', 'servicos')),
       EXISTS (SELECT 1 FROM platform.entitlements e WHERE e.tenant_id = t.id
                AND e.ativo AND e.modulo IN ('vendedor', 'servicos'))
  FROM platform.tenants t WHERE t.id = ANY(%s::uuid[])
"""


# ------------------------------------------------------- a reproducao, em Python


@dataclass(frozen=True)
class LinhaH10:
    tenant_id: str
    provisionado_em: dt.datetime
    censurado: bool
    catalogo: bool
    foto: bool
    social: bool
    orcamento: bool
    algum: bool


@dataclass(frozen=True)
class LinhaH11:
    tenant_id: str
    primeiro_valor_em: dt.datetime | None
    primeiro_modulo: str | None
    primeira_conversa_em: dt.datetime | None
    entrou_por_modulo: bool
    censurado: bool
    activou: bool


@dataclass(frozen=True)
class Cru:
    """As linhas cruas de uma amostra de tenants, sem nenhuma conta feita."""

    agora: dt.datetime
    provisionados: Mapping[str, dt.datetime]
    #: `(tenant, modulo) -> instantes` de cada resultado de valor.
    valores: Mapping[tuple[str, str], list[dt.datetime]]
    #: `tenant -> instantes` de cada resposta do bot a um cliente, no WhatsApp,
    #: fora de conversa de teste.
    atendidas: Mapping[str, list[dt.datetime]]
    #: `tenant -> (canal ligado, vertical de atendimento activa)`.
    atendimento: Mapping[str, tuple[bool, bool]]


def h10_em_python(cru: Cru, janela_dias: int) -> list[LinhaH10]:
    janela = dt.timedelta(days=janela_dias)
    linhas = []
    for tenant, provisionado in sorted(cru.provisionados.items()):
        usou = {
            m: any(v < provisionado + janela for v in cru.valores.get((tenant, m), []) if v <= cru.agora)
            for m in MODULOS
        }
        linhas.append(
            LinhaH10(
                tenant_id=tenant,
                provisionado_em=provisionado,
                censurado=provisionado > cru.agora - janela,
                algum=any(usou.values()),
                **usou,
            )
        )
    return linhas


def h11_em_python(cru: Cru, janela_dias: int) -> list[LinhaH11]:
    janela = dt.timedelta(days=janela_dias)
    linhas = []
    for tenant in sorted(cru.provisionados):
        primeiros = sorted(
            (min(v), m)
            for m in MODULOS
            if (v := [x for x in cru.valores.get((tenant, m), []) if x <= cru.agora])
        )
        atendidas = sorted(x for x in cru.atendidas.get(tenant, []) if x <= cru.agora)
        primeiro_em, primeiro_modulo = primeiros[0] if primeiros else (None, None)
        conversa_em = atendidas[0] if atendidas else None
        entrou = primeiro_em is not None and (conversa_em is None or primeiro_em < conversa_em)
        canal, vertical = cru.atendimento.get(tenant, (False, False))
        activou = (
            entrou
            and canal
            and vertical
            and any(x < primeiro_em + janela for x in atendidas)  # type: ignore[operator]
        )
        linhas.append(
            LinhaH11(
                tenant_id=tenant,
                primeiro_valor_em=primeiro_em,
                primeiro_modulo=primeiro_modulo,
                primeira_conversa_em=conversa_em,
                entrou_por_modulo=entrou,
                censurado=entrou and primeiro_em > cru.agora - janela,  # type: ignore[operator]
                activou=bool(activou),
            )
        )
    return linhas


def diferencas(da_base: Iterable[Any], em_python: Iterable[Any]) -> list[dict[str, Any]]:
    """As linhas em que a base e o Python discordam, campo a campo."""
    base = {str(linha.tenant_id): asdict(linha) for linha in da_base}
    calc = {str(linha.tenant_id): asdict(linha) for linha in em_python}
    achados = []
    for tenant in sorted(set(base) | set(calc)):
        a, b = base.get(tenant), calc.get(tenant)
        if a is None or b is None:
            achados.append({"tenant_id": tenant, "base": a is not None, "python": b is not None})
            continue
        campos = sorted(k for k in a if a[k] != b[k])
        if campos:
            achados.append({"tenant_id": tenant, "campos": campos})
    return achados


# --------------------------------------------------------------- as leituras


def ler_hipoteses(
    h10: list[LinhaH10],
    h11: list[LinhaH11],
    pagantes: Mapping[str, int],
    limiares: Any,
) -> dict[str, Any]:
    """As tres hipoteses com n/N e Wilson. Os censurados nao entram no N."""
    from kamba_core.modulos import experimento as ex

    observados = [l for l in h10 if not l.censurado]
    h11_n = [l for l in h11 if l.entrou_por_modulo and not l.censurado]
    leitura_h10 = ex.ler_hipotese("H10", sum(l.algum for l in observados), len(observados), limiares.h10_limiar_pct)
    leitura_h11 = ex.ler_hipotese("H11", sum(l.activou for l in h11_n), len(h11_n), limiares.h11_limiar_pct)
    return {
        "H10": {
            **_dict(leitura_h10),
            "censurados": len(h10) - len(observados),
            "por_modulo": {
                m: asdict(ex.Proporcao.de(sum(getattr(l, m) for l in observados), len(observados)))
                for m in MODULOS
            },
        },
        "H11": {
            **_dict(leitura_h11),
            "censurados": sum(1 for l in h11 if l.entrou_por_modulo and l.censurado),
            "nao_entraram_por_modulo": sum(1 for l in h11 if not l.entrou_por_modulo),
        },
        "H12": {
            "pagantes_por_modulo": {m: int(pagantes.get(m, 0)) for m in MODULOS},
            "limiar_pagantes": limiares.h12_pagantes,
            "cumpre_pagantes": {m: int(pagantes.get(m, 0)) >= limiares.h12_pagantes for m in MODULOS},
            "limiar_custo_pct": limiares.h12_custo_pct,
        },
    }


def _dict(leitura: Any) -> dict[str, Any]:
    dados = asdict(leitura)
    medida = dados.pop("medida")
    return {**dados, **medida}


def _semana(texto: str) -> dt.date:
    """A segunda-feira de uma semana ISO escrita `AAAA-WNN`."""
    ano, numero = texto.split("-W")
    return dt.date.fromisocalendar(int(ano), int(numero), 1)


def _rotulo(segunda: dt.date) -> str:
    ano, numero, _ = segunda.isocalendar()
    return f"{ano}-W{numero:02d}"


def racios_semanais(
    linhas: Iterable[tuple[str, str, Any, Any]], ultima: dt.date | None = None
) -> dict[str, list[tuple[str, float | None]]]:
    """`modulo -> [(semana, racio)]`: o custo da semana sobre o preco semanal (x 12/52).

    So as semanas completas chegam aqui (o SQL corta a de `agora`). Uma semana
    sem custo entre a primeira e a `ultima` (a segunda-feira da ultima semana
    completa) **conta como zero**: sem isso, duas semanas acima separadas por uma
    vazia liam-se «seguidas».
    """
    custos: dict[str, dict[dt.date, int]] = defaultdict(dict)
    precos: dict[str, Any] = {}
    for modulo, semana, custo, preco_mensal in linhas:
        custos[str(modulo)][_semana(str(semana))] = int(custo)
        precos[str(modulo)] = preco_mensal
    saida: dict[str, list[tuple[str, float | None]]] = {}
    for modulo, por_semana in custos.items():
        preco = precos[modulo]
        semana = min(por_semana)
        fim = max(max(por_semana), ultima) if ultima is not None else max(por_semana)
        serie: list[tuple[str, float | None]] = []
        while semana <= fim:
            custo = por_semana.get(semana, 0)
            if not preco:
                serie.append((_rotulo(semana), None))
            else:
                semanal = Fraction(int(preco)) * 12 / 52
                serie.append((_rotulo(semana), round(float(Fraction(custo) / semanal), 6)))
            semana += dt.timedelta(days=7)
        saida[modulo] = serie
    return saida


def incidentes_de(caminho: Path) -> dict[str, tuple[int, int]]:
    """O JSON dos incidentes contados a mao: `{"modulo": {"alta": n, "media": n}}`."""
    dados = json.loads(caminho.read_text(encoding="utf-8"))
    if not isinstance(dados, dict):
        raise ErroDeUso("os incidentes sao um objecto modulo -> {alta, media}")
    saida: dict[str, tuple[int, int]] = {}
    for modulo, valor in dados.items():
        if modulo not in MODULOS:
            raise ErroDeUso(f"modulo desconhecido nos incidentes: {modulo!r}")
        if not isinstance(valor, dict) or set(valor) != {"alta", "media"}:
            raise ErroDeUso(f"`{modulo}`: os incidentes sao {{alta, media}}")
        alta, media = valor["alta"], valor["media"]
        if any(isinstance(n, bool) or not isinstance(n, int) or n < 0 for n in (alta, media)):
            raise ErroDeUso(f"`{modulo}`: incidentes sao inteiros nao negativos")
        saida[modulo] = (alta, media)
    faltam = [m for m in MODULOS if m not in saida]
    if faltam:
        # Um modulo sem contagem nao e «zero incidentes»: e uma contagem por fazer.
        raise ErroDeUso(f"faltam os incidentes de: {', '.join(faltam)}")
    return saida


# -------------------------------------------------------------- a base


def _h10_da_base(cursor: Any, agora: dt.datetime, janela: int) -> list[LinhaH10]:
    cursor.execute(SQL_H10, (agora, janela))
    return [LinhaH10(str(r[0]), *r[1:]) for r in cursor.fetchall()]


def _h11_da_base(cursor: Any, agora: dt.datetime, janela: int) -> list[LinhaH11]:
    cursor.execute(SQL_H11, (agora, janela))
    return [LinhaH11(str(r[0]), *r[1:]) for r in cursor.fetchall()]


def _cru(cursor: Any, agora: dt.datetime, amostra: int) -> Cru:
    cursor.execute(SQL_CRU_COORTE, (agora,))
    provisionados = {str(t): em for t, em in sorted(cursor.fetchall(), key=lambda r: str(r[0]))[:amostra]}
    tenants = list(provisionados)
    valores: dict[tuple[str, str], list[dt.datetime]] = defaultdict(list)
    cursor.execute(SQL_CRU_CATALOGO, (tenants,))
    for t, em in cursor.fetchall():
        valores[(str(t), "catalogo")].append(em)
    cursor.execute(SQL_CRU_FOTO, (tenants,))
    for t, em in cursor.fetchall():
        valores[(str(t), "foto")].append(em)
    cursor.execute(SQL_CRU_DONOS, (tenants,))
    donos = {str(t): (str(c) if c is not None else None) for t, c in cursor.fetchall()}
    cursor.execute(SQL_CRU_CONVERSAS, (tenants,))
    # So as conversas que existem e nao sao de teste: o off-boarding apaga as
    # conversas e deixa o evento no `events_log`, e o evento sem conversa nao conta.
    reais = {(str(t), str(c)) for t, c, teste in cursor.fetchall() if not teste}
    atendidas: dict[str, list[dt.datetime]] = defaultdict(list)
    cursor.execute(SQL_CRU_EVENTOS, (tenants,))
    for t, tipo, em, contacto, conversa, canal in cursor.fetchall():
        t = str(t)
        if tipo == "content.approved":
            valores[(t, "social")].append(em)
        elif tipo == "quote.sent":
            valores[(t, "orcamento")].append(em)
        elif canal == "whatsapp" and contacto != donos.get(t) and (t, conversa) in reais:
            atendidas[t].append(em)
    cursor.execute(SQL_CRU_ATENDIMENTO, (tenants,))
    atendimento = {str(t): (bool(c), bool(v)) for t, c, v in cursor.fetchall()}
    return Cru(agora, provisionados, dict(valores), dict(atendidas), atendimento)


def _medir(cursor: Any, agora: dt.datetime, limiares: Any) -> dict[str, Any]:
    h10 = _h10_da_base(cursor, agora, limiares.janela_de_uso_dias)
    h11 = _h11_da_base(cursor, agora, limiares.janela_de_activacao_dias)
    cursor.execute(SQL_PAGANTES, (agora,))
    pagantes = {str(m): int(n) for m, n in cursor.fetchall()}
    cursor.execute(SQL_CUSTO_SEMANAL, (agora, agora))
    hoje = agora.astimezone(LUANDA).date()
    ultima_completa = hoje - dt.timedelta(days=hoje.weekday() + 7)
    racios = racios_semanais(cursor.fetchall(), ultima_completa)
    cursor.execute(SQL_MARGEM, (agora, agora))
    margens = {str(m): int(v) for m, v in cursor.fetchall()}
    leitura = ler_hipoteses(h10, h11, pagantes, limiares)
    leitura["H12"]["custo_racios_semanais"] = racios
    leitura["H12"]["margem_do_mes_minor"] = margens
    leitura["agora"] = agora.isoformat()
    return {"leitura": leitura, "h10": h10}


def correr(argumentos: argparse.Namespace, cursor: Any) -> tuple[Any, int]:
    """Um subcomando sobre um cursor ja aberto. Separado do `main` para os ensaios."""
    from kamba_core.modulos import experimento as ex

    limiares = ex.ler(argumentos.limiares)
    agora = argumentos.agora or dt.datetime.now(dt.UTC)
    if argumentos.comando == "ler":
        return _medir(cursor, agora, limiares)["leitura"], SAIDA_OK
    if argumentos.comando == "reproduzir":
        cru = _cru(cursor, agora, argumentos.amostra)
        base10 = [l for l in _h10_da_base(cursor, agora, limiares.janela_de_uso_dias) if l.tenant_id in cru.provisionados]
        base11 = [l for l in _h11_da_base(cursor, agora, limiares.janela_de_activacao_dias) if l.tenant_id in cru.provisionados]
        achados = {
            "H10": diferencas(base10, h10_em_python(cru, limiares.janela_de_uso_dias)),
            "H11": diferencas(base11, h11_em_python(cru, limiares.janela_de_activacao_dias)),
        }
        dados = {"amostra": len(cru.provisionados), "diferencas": achados}
        return dados, SAIDA_DIFERENCAS if any(achados.values()) else SAIDA_OK
    if argumentos.comando == "decidir":
        incidentes = incidentes_de(argumentos.incidentes)
        medido = _medir(cursor, agora, limiares)
        observados = [l for l in medido["h10"] if not l.censurado]
        racios = medido["leitura"]["H12"]["custo_racios_semanais"]
        margens = medido["leitura"]["H12"]["margem_do_mes_minor"]
        decisoes = []
        for modulo in MODULOS:
            alta, media = incidentes[modulo]
            decisao = ex.decidir(
                ex.MedicaoDoModulo(
                    modulo=modulo,
                    usaram=sum(getattr(l, modulo) for l in observados),
                    coorte=len(observados),
                    custo_racios_semanais=tuple(r for _, r in racios.get(modulo, [])),
                    margem_negativa=margens.get(modulo, 0) < 0,
                    incidentes_alta=alta,
                    incidentes_media=media,
                ),
                limiares,
            )
            decisoes.append(decisao)
        if argumentos.registar:
            _registar(cursor, argumentos, decisoes)
        return {
            "agora": agora.isoformat(),
            "registadas": bool(argumentos.registar),
            "decisoes": [
                {"modulo": d.modulo, "decisao": d.decisao, "criterio": d.criterio,
                 "motivo": d.motivo, "metricas": d.metricas()}
                for d in decisoes
            ],
        }, SAIDA_OK
    if argumentos.comando == "excluir":
        cursor.execute(SQL_EXCLUIR, (str(argumentos.tenant), argumentos.motivo, argumentos.por))
        return {"excluido": str(argumentos.tenant), "motivo": argumentos.motivo}, SAIDA_OK
    raise ErroDeUso(f"comando desconhecido: {argumentos.comando}")


def _registar(cursor: Any, argumentos: argparse.Namespace, decisoes: list[Any]) -> None:
    """Grava **um** modulo, com a decisao de quem decide; a proposta fica ao lado."""
    if not argumentos.responsavel or not argumentos.justificacao:
        raise ErroDeUso("--registar exige --responsavel e --justificacao: a decisao e de uma pessoa")
    if argumentos.modulo is None:
        raise ErroDeUso("--registar exige --modulo: cada modulo decide-se e regista-se a parte")
    proposta = next(d for d in decisoes if d.modulo == argumentos.modulo)
    decisao = argumentos.decisao or proposta.decisao
    if decisao is None:
        raise ErroDeUso(
            f"sem coorte para decidir `{proposta.modulo}`: regista-se a justificacao de dados "
            "insuficientes no relatorio, ou uma --decisao explicita de quem decide"
        )
    if decisao == "ajustar" and argumentos.revisao_em is None:
        raise ErroDeUso("uma decisao «ajustar» exige --revisao-em: o plano tem data")
    metricas = {**proposta.metricas(), "decisao_proposta": proposta.decisao, "motivo_da_proposta": proposta.motivo}
    cursor.execute(
        SQL_REGISTAR_DECISAO,
        (proposta.modulo, argumentos.data or dt.date.today(), json.dumps(metricas, ensure_ascii=False),
         proposta.criterio, decisao, argumentos.responsavel, argumentos.justificacao, argumentos.revisao_em),
    )


# --------------------------------------------------------------- linha de comando


def _instante(texto: str) -> dt.datetime:
    try:
        valor = dt.datetime.fromisoformat(texto)
    except ValueError:
        raise argparse.ArgumentTypeError(f"instante invalido, use ISO 8601: {texto!r}") from None
    if valor.tzinfo is None:
        raise argparse.ArgumentTypeError("o instante leva fuso (UTC: ...Z ou +00:00)")
    return valor


def _data(texto: str) -> dt.date:
    try:
        return dt.date.fromisoformat(texto)
    except ValueError:
        raise argparse.ArgumentTypeError(f"data invalida, use AAAA-MM-DD: {texto!r}") from None


def _analisador() -> argparse.ArgumentParser:
    analisador = argparse.ArgumentParser(prog="experimento-modulos", description=__doc__.split("\n")[0])
    comandos = analisador.add_subparsers(dest="comando", required=True)

    def comum(sub: argparse.ArgumentParser) -> None:
        sub.add_argument("--agora", type=_instante, default=None)
        sub.add_argument("--limiares", type=Path, default=LIMIARES)

    comum(comandos.add_parser("ler", help="as tres hipoteses com n/N e Wilson"))
    reproduz = comandos.add_parser("reproduzir", help="a metrica em Python contra a base")
    comum(reproduz)
    reproduz.add_argument("--amostra", type=int, default=5)
    decide = comandos.add_parser("decidir", help="a regra pre-registada, e o registo")
    comum(decide)
    decide.add_argument("--incidentes", type=Path, required=True)
    decide.add_argument("--data", type=_data, default=None)
    decide.add_argument("--registar", action="store_true")
    decide.add_argument("--modulo", choices=MODULOS, default=None)
    decide.add_argument("--decisao", choices=("manter", "ajustar", "abater"), default=None)
    decide.add_argument("--responsavel", default=None)
    decide.add_argument("--justificacao", default=None)
    decide.add_argument("--revisao-em", type=_data, default=None)
    exclui = comandos.add_parser("excluir", help="um tenant da equipa ou de teste fora da coorte")
    comum(exclui)
    exclui.add_argument("--tenant", type=uuid.UUID, required=True)
    exclui.add_argument("--motivo", choices=("equipa", "teste"), required=True)
    exclui.add_argument("--por", required=True)
    return analisador


def main(argv: list[str] | None = None) -> int:
    for fluxo in (sys.stdout, sys.stderr):
        reconfigurar = getattr(fluxo, "reconfigure", None)
        if reconfigurar is not None:
            reconfigurar(encoding="utf-8", errors="replace")
    argumentos = _analisador().parse_args(argv)
    if getattr(argumentos, "amostra", 1) < 1:
        print("experimento-modulos: --amostra >= 1", file=sys.stderr)
        return SAIDA_ERRO

    import ligacao
    import pg8000.dbapi
    from kamba_core import tenant_guard

    try:
        conexao = ligacao.ligar("batch")
    except ligacao.ConfiguracaoEmFalta as erro:
        print(f"experimento-modulos: {erro}", file=sys.stderr)
        return SAIDA_ERRO
    try:
        try:
            with tenant_guard.tx_batch(conexao, JOB) as cursor:
                dados, codigo = correr(argumentos, cursor)
        except pg8000.dbapi.DatabaseError as erro:
            conexao.rollback()
            print(f"experimento-modulos: a base recusou: {erro}", file=sys.stderr)
            return SAIDA_ERRO
        except (ErroDeUso, ValueError, OSError, KeyError) as erro:
            print(f"experimento-modulos: {erro}", file=sys.stderr)
            return SAIDA_ERRO
    finally:
        conexao.close()
    sys.stdout.write(json.dumps(dados, ensure_ascii=False, indent=2, default=str) + "\n")
    return codigo


if __name__ == "__main__":
    raise SystemExit(main())
