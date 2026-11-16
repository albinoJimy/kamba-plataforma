"""Custo por modulo de entrada: consolidacao, precos, H12, alertas e reconciliacao (KAM-124).

    python db/h12_export.py consolidar      [--cambio X] [--templates <yaml>]
    python db/h12_export.py carregar-precos [--planos <yaml>]
    python db/h12_export.py exportar        --mes AAAA-MM [--cambio X | --modo M] [--saida <csv>]
    python db/h12_export.py alertas         [--mes AAAA-MM] [--cambio X | --modo M]
    python db/h12_export.py reconciliar     --mes AAAA-MM [--litellm <json>]
                                            [--painel-imagem <json>] [--meta <json>]

O nome do comando no canon e `h12-export`: e o instrumento que alimenta a H12
(«custo <= 15% do preco do modulo») e o experimento do KAM-127. A decisao da
H12 nao e daqui, e **nenhum preco aqui e decisao**: os precos de teste sao
`hipotese_nao_validada`, e o `carregar-precos` recusa outro estado.

## O que cada subcomando faz

* **`consolidar`** — escreve no `platform.module_cost_ledger`, pela
  `platform.module_cost_gravar`, o custo das tres fontes (`db/modulos_custo.py`).
  Idempotente: correr duas vezes nao duplica. Corre de 5 em 5 minutos (*job*
  `ops_h12_export`), e e esse periodo que poe o consumo de uma PME no painel.
* **`carregar-precos`** — le os `preco_teste_minor` do `registry/plans.yaml` para
  `platform.module_test_prices`, **sem deploy**: substitui o que la estava e
  apaga o que o ficheiro deixou de ter.
* **`exportar`** — o CSV do KAM-127: `tenant` (pseudonimo), `mes`, `modulo`,
  `custo_usd`, `custo_aoa_minor`, `fx_aoa_per_usd`, `uso`, `preco_teste_minor`,
  `estado_do_preco` e `racio`. **Sem nome, sem `tenant_id`, sem contacto**: o
  tenant sai como um HMAC do `tenant_id` com a chave do ambiente
  `KAMBA_H12_PSEUDONIMO_CHAVE`, em base32 (o hexadecimal casa a guarda de
  telefone, licao do `evt_emitir`). Sem chave, recusa: um pseudonimo sem chave
  e um `sha256` que qualquer um reverte enumerando os tenants.
* **`alertas`** — os tres do criterio 8, em JSON: o custo do modulo acima de
  15% (aviso) e de 30% (critico) do preco de teste no mes; o custo de um dia
  acima de 3 vezes a mediana do tenant; e o fornecedor de imagem com trabalhos
  concluidos sem custo registado. Os limiares sao *propostas*.
* **`reconciliar`** — o ledger contra as fontes de que foi consolidado (deve dar
  zero) e, quando dados, contra o LiteLLM (<= 2%), o painel do fornecedor de
  imagem (<= 5%) e a factura da Meta (<= 5%), por modulo. Os limiares sao
  *propostas* do criterio 5; **a medicao em staging com 7 dias de trafego
  sintetico nao e deste comando**, que so a torna possivel.

## Papel

`kamba_batch`, sob `tenant_guard.tx_batch` com o *job* nomeado — o caminho do
`h6_export.py`.

## Codigos de saida

`0` sem achados, `1` com achados (alertas ou desvios), `2` erro de uso ou da base.
"""

from __future__ import annotations

import argparse
import base64
import csv
import datetime as dt
import hashlib
import hmac
import io
import json
import os
import statistics
import sys
from collections.abc import Iterable, Mapping
from dataclasses import asdict, dataclass
from decimal import Decimal
from pathlib import Path
from typing import Any, Final

sys.path.insert(0, str(Path(__file__).resolve().parent))
_RAIZ = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(_RAIZ / "tools"))

import custo  # noqa: E402 — depois do `sys.path`, como o `h6_export.py`
import modulos_custo  # noqa: E402

JOB: Final = "ops_h12_export"

SAIDA_OK: Final = 0
SAIDA_ACHADOS: Final = 1
SAIDA_ERRO: Final = 2

#: A variavel de ambiente com a chave do pseudonimo.
VARIAVEL_DA_CHAVE: Final = "KAMBA_H12_PSEUDONIMO_CHAVE"

#: O unico estado de um preco de teste (dicionario §4; `ESTADOS_DE_PLANO` do
#: gate 3b).
ESTADO_DO_PRECO: Final = "hipotese_nao_validada"

#: *Propostas* do criterio 8.
LIMIAR_AVISO: Final = Decimal("0.15")
LIMIAR_CRITICO: Final = Decimal("0.30")
MULTIPLO_DA_MEDIANA: Final = Decimal(3)
#: Quantos dias com custo o tenant precisa antes de a mediana valer alguma
#: coisa. *Proposta*: com dois dias, o terceiro dispara so por existir.
DIAS_PARA_A_MEDIANA: Final = 7
#: A janela da mediana, em dias antes do dia medido.
JANELA_DA_MEDIANA: Final = 28

#: *Propostas* do criterio 5, por rubrica.
TOLERANCIA: Final[Mapping[str, Decimal]] = {
    "llm": Decimal("0.02"),
    "imagem": Decimal("0.05"),
    "mensagem": Decimal("0.05"),
}

#: As colunas do CSV, pela ordem. **Lista fechada**: o ensaio confronta-a com
#: os identificadores proibidos.
CAMPOS_DO_CSV: Final = (
    "tenant",
    "mes",
    "modulo",
    "custo_usd",
    "custo_aoa_minor",
    "fx_aoa_per_usd",
    "uso",
    "preco_teste_minor",
    "estado_do_preco",
    "racio",
)


class ErroDeUso(Exception):
    """O pedido nao se pode cumprir como foi feito (codigo 2)."""


# ------------------------------------------------------------------ pseudonimo


def pseudonimo(chave: bytes, tenant_id: str) -> str:
    """O tenant sem nome: HMAC-SHA256 do `tenant_id`, 20 caracteres de base32.

    Estavel entre exportacoes com a mesma chave (o KAM-127 cruza meses), e
    irreversivel sem ela. Base32 e nao hexadecimal: uma corrida de algarismos
    num identificador casa a guarda de telefone (licao do `evt_emitir`).
    """
    if not chave:
        raise ErroDeUso(f"{VARIAVEL_DA_CHAVE} vazia: sem chave o pseudonimo reverte-se")
    resumo = hmac.new(chave, str(tenant_id).encode("utf-8"), hashlib.sha256).digest()
    return base64.b32encode(resumo).decode("ascii")[:20].lower()


def chave_do_ambiente(ambiente: Mapping[str, str] | None = None) -> bytes:
    valor = (os.environ if ambiente is None else ambiente).get(VARIAVEL_DA_CHAVE, "")
    if not valor.strip():
        raise ErroDeUso(f"{VARIAVEL_DA_CHAVE} nao definida: o exportar recusa sem ela")
    return valor.encode("utf-8")


# ---------------------------------------------------------------------- precos


@dataclass(frozen=True)
class PrecoDeTeste:
    plano: str
    modulo: str
    preco_teste_minor: int
    estado: str


def precos_do_registo(documento: Mapping[str, Any]) -> list[PrecoDeTeste]:
    """Os `preco_teste_minor` de um `plans.yaml`, validados.

    O gate 3b ja os valida no CI; isto valida-os **outra vez** no caminho que
    escreve na base, porque e esse o caminho que o ficheiro percorre sem deploy.
    """
    planos = documento.get("plans")
    if not isinstance(planos, Mapping):
        raise ErroDeUso("o ficheiro de planos nao tem `plans`")
    precos: list[PrecoDeTeste] = []
    for plano, corpo in planos.items():
        if not isinstance(corpo, Mapping):
            raise ErroDeUso(f"o plano {plano!r} nao e um mapa")
        for item in corpo.get("entitlements") or []:
            if not isinstance(item, Mapping) or "preco_teste_minor" not in item:
                continue
            estado = corpo.get("estado")
            if estado != ESTADO_DO_PRECO:
                raise ErroDeUso(
                    f"o plano {plano!r} tem preco de teste e estado {estado!r}: "
                    f"um preco de teste so existe como {ESTADO_DO_PRECO}"
                )
            modulo = item.get("modulo")
            if modulo not in modulos_custo.MODULOS:
                raise ErroDeUso(f"preco de teste no modulo {modulo!r}, que nao e de entrada")
            valor = item["preco_teste_minor"]
            if isinstance(valor, bool) or not isinstance(valor, int) or valor < 0:
                raise ErroDeUso(f"preco_teste_minor ilegivel em {plano}/{modulo}: {valor!r}")
            precos.append(PrecoDeTeste(str(plano), str(modulo), valor, estado))
    return precos


SQL_APAGAR_PRECOS: Final = "DELETE FROM platform.module_test_prices"
SQL_INSERIR_PRECO: Final = """
INSERT INTO platform.module_test_prices (plano, modulo, preco_teste_minor, estado)
VALUES (%s, %s, %s, %s)
"""


# ----------------------------------------------------------------- consolidar


def mapa_de_templates(documento: Mapping[str, Any]) -> tuple[list[str], list[str]]:
    """O `config/templates_por_modulo.yaml` como os dois *arrays* do SQL."""
    entradas = documento.get("templates")
    if not isinstance(entradas, list):
        raise ErroDeUso("o mapa de templates nao tem a lista `templates`")
    templates: list[str] = []
    modulos: list[str] = []
    for entrada in entradas:
        if not isinstance(entrada, Mapping):
            raise ErroDeUso(f"entrada do mapa de templates ilegivel: {entrada!r}")
        template, modulo = entrada.get("template"), entrada.get("modulo")
        if not isinstance(template, str) or not template:
            raise ErroDeUso(f"template sem nome: {entrada!r}")
        if modulo not in modulos_custo.MODULOS:
            raise ErroDeUso(f"o template {template!r} aponta para {modulo!r}, que nao e de entrada")
        if template in templates:
            raise ErroDeUso(f"o template {template!r} aparece duas vezes no mapa")
        templates.append(template)
        modulos.append(str(modulo))
    return templates, modulos


# ------------------------------------------------------------------- exportar


def linhas_do_csv(
    h12: Iterable[Mapping[str, Any]],
    uso: Mapping[tuple[str, str], int],
    chave: bytes,
) -> list[dict[str, str]]:
    """As linhas do CSV, a partir da `v_h12` de um mes e do uso desse mes.

    `uso` e `{(tenant_id, chave_limite): valor}`. O `catalogo` nao tem contador
    e sai com `uso` vazio; um modulo com contador e sem linha de uso sai a `0`.
    """
    linhas: list[dict[str, str]] = []
    for linha in h12:
        tenant_id = str(linha["tenant_id"])
        modulo = str(linha["modulo"])
        chave_de_uso = modulos_custo.CHAVE_DE_USO.get(modulo)
        preco = linha.get("preco_teste_minor")
        racio = linha.get("racio")
        linhas.append(
            {
                "tenant": pseudonimo(chave, tenant_id),
                "mes": str(linha["mes"])[:7],
                "modulo": modulo,
                "custo_usd": str(linha["custo_usd"]),
                "custo_aoa_minor": str(linha["custo_aoa_minor"]),
                "fx_aoa_per_usd": str(linha["fx_aoa_per_usd"]),
                "uso": "" if chave_de_uso is None else str(uso.get((tenant_id, chave_de_uso), 0)),
                "preco_teste_minor": "" if preco is None else str(preco),
                "estado_do_preco": "" if preco is None else ESTADO_DO_PRECO,
                "racio": "" if racio is None else str(racio),
            }
        )
    linhas.sort(key=lambda l: (l["mes"], l["tenant"], l["modulo"]))
    return linhas


def csv_de(linhas: list[dict[str, str]]) -> str:
    saida = io.StringIO()
    escritor = csv.DictWriter(saida, fieldnames=CAMPOS_DO_CSV, lineterminator="\n")
    escritor.writeheader()
    escritor.writerows(linhas)
    return saida.getvalue()


# -------------------------------------------------------------------- alertas


@dataclass(frozen=True)
class Alerta:
    tipo: str
    severidade: str
    tenant_id: str | None
    modulo: str | None
    valor: str
    limiar: str


def alertas_de_preco(h12: Iterable[Mapping[str, Any]]) -> list[Alerta]:
    """Custo do modulo no mes acima de 15% (aviso) ou 30% (critico) do preco de teste."""
    alertas: list[Alerta] = []
    for linha in h12:
        racio = linha.get("racio")
        if racio is None:
            continue
        racio = Decimal(str(racio))
        if racio > LIMIAR_CRITICO:
            severidade, limiar = "critico", LIMIAR_CRITICO
        elif racio > LIMIAR_AVISO:
            severidade, limiar = "aviso", LIMIAR_AVISO
        else:
            continue
        alertas.append(
            Alerta("custo_acima_do_preco", severidade, str(linha["tenant_id"]),
                   str(linha["modulo"]), str(racio), str(limiar))
        )
    return alertas


def alertas_diarios(
    custos: Iterable[tuple[str, dt.date, Decimal]], hoje: dt.date
) -> list[Alerta]:
    """O custo de `hoje` acima de 3 vezes a mediana dos dias anteriores do tenant.

    A mediana e dos dias **com custo** na janela de 28 dias antes de hoje, e so
    vale com 7 ou mais. Um tenant novo nao dispara so por ter comecado.
    """
    por_tenant: dict[str, dict[dt.date, Decimal]] = {}
    for tenant_id, dia, valor in custos:
        dias = por_tenant.setdefault(str(tenant_id), {})
        dias[dia] = dias.get(dia, Decimal(0)) + Decimal(str(valor))
    inicio = hoje - dt.timedelta(days=JANELA_DA_MEDIANA)
    alertas: list[Alerta] = []
    for tenant_id, dias in sorted(por_tenant.items()):
        hoje_custo = dias.get(hoje)
        anteriores = [v for d, v in dias.items() if inicio <= d < hoje and v > 0]
        if hoje_custo is None or len(anteriores) < DIAS_PARA_A_MEDIANA:
            continue
        mediana = Decimal(str(statistics.median(anteriores)))
        if hoje_custo > MULTIPLO_DA_MEDIANA * mediana:
            alertas.append(
                Alerta("custo_diario_anomalo", "aviso", tenant_id, None,
                       str(hoje_custo), str(MULTIPLO_DA_MEDIANA * mediana))
            )
    return alertas


def alertas_de_fornecedor(
    linhas: Iterable[tuple[str, int, int]], sem_tarifa: int = 0
) -> list[Alerta]:
    """Trabalhos de imagem concluidos sem custo registado, por fornecedor.

    Um `concluido` a zero e um fornecedor pago que nao disse quanto, ou um
    adaptador que perdeu o custo: as duas sao custo por medir. Tambem conta as
    mensagens cobraveis de categoria sem tarifa (`sem_tarifa`).
    """
    alertas = [
        Alerta("imagem_sem_custo", "aviso", None, "foto", f"{provider}:{sem_custo}/{total}", "0")
        for provider, sem_custo, total in linhas
        if sem_custo > 0
    ]
    if sem_tarifa > 0:
        alertas.append(Alerta("mensagem_sem_tarifa", "aviso", None, None, str(sem_tarifa), "0"))
    return alertas


# ---------------------------------------------------------------- reconciliar


def desvio(medido: Decimal, referencia: Decimal) -> Decimal | None:
    """`|medido - referencia| / referencia`; `None` quando a referencia e zero."""
    if referencia == 0:
        return None if medido == 0 else Decimal("Infinity")
    return abs(medido - referencia) / referencia


def reconciliar(
    ledger: Mapping[Any, Decimal],
    referencia: Mapping[Any, Decimal],
    tolerancia: Decimal,
    fonte: str,
) -> list[dict[str, str]]:
    """Os achados de uma comparacao chave a chave, acima da tolerancia."""
    achados: list[dict[str, str]] = []
    for chave in sorted(set(ledger) | set(referencia), key=str):
        medido = ledger.get(chave, Decimal(0))
        esperado = referencia.get(chave, Decimal(0))
        d = desvio(medido, esperado)
        if d is not None and d > tolerancia:
            achados.append(
                {"fonte": fonte, "chave": str(chave), "ledger": str(medido),
                 "referencia": str(esperado), "desvio": str(d), "tolerancia": str(tolerancia)}
            )
    return achados


def _ler_externo(caminho: Path) -> dict[str, Decimal]:
    """`[{"modulo": ..., "spend_usd": ...}, ...]`, somado por modulo."""
    soma: dict[str, Decimal] = {}
    for linha in json.loads(caminho.read_text(encoding="utf-8")):
        modulo = str(linha["modulo"])
        soma[modulo] = soma.get(modulo, Decimal(0)) + Decimal(str(linha["spend_usd"]))
    return soma


# ------------------------------------------------------------------------ SQL

SQL_FIXAR_CAMBIO: Final = "SELECT set_config('app.fx_aoa_per_usd', %s, true)"
SQL_H12_DO_MES: Final = """
SELECT tenant_id::text AS tenant_id, mes, modulo, custo_usd, custo_aoa_minor,
       fx_aoa_per_usd, preco_teste_minor, racio, margem_minor
  FROM platform.v_h12
 WHERE mes = %s
"""
SQL_USO_DO_MES: Final = """
SELECT tenant_id::text, chave_limite, valor
  FROM platform.tenant_usage
 WHERE periodo = %s
   AND chave_limite IN ('imagens_mes', 'posts_mes', 'orcamentos_mes')
"""
SQL_MES_CORRENTE: Final = "SELECT platform.ten_periodo(now()), (now() AT TIME ZONE 'Africa/Luanda')::date"
SQL_CUSTO_DIARIO: Final = """
SELECT tenant_id::text, (ocorrido_em AT TIME ZONE 'Africa/Luanda')::date AS dia, sum(custo_usd)
  FROM platform.module_cost_ledger
 WHERE ocorrido_em >= now() - interval '30 days'
 GROUP BY 1, 2
"""
SQL_FORNECEDOR_SEM_CUSTO: Final = """
SELECT provider, count(*) FILTER (WHERE custo_usd = 0), count(*)
  FROM platform.image_jobs
 WHERE estado = 'concluido'
   AND criado_at >= now() - interval '1 day'
 GROUP BY provider
 ORDER BY provider
"""
SQL_LEDGER_DO_MES: Final = """
SELECT tenant_id::text, modulo, rubrica, sum(custo_usd)
  FROM platform.module_cost_ledger
 WHERE platform.ten_periodo(ocorrido_em) = %s
 GROUP BY 1, 2, 3
"""
SQL_FONTE_LLM_DO_MES: Final = """
SELECT tenant_id::text, vertical, 'llm', sum(custo_usd)
  FROM dat.llm_call_log
 WHERE vertical IN ('catalogo', 'foto', 'social', 'orcamento')
   AND resultado <> 'destino_negado'
   AND custo_usd > 0
   AND platform.ten_periodo(ts) = %s
 GROUP BY 1, 2
"""
SQL_FONTE_IMAGEM_DO_MES: Final = """
SELECT tenant_id::text, 'foto', 'imagem', sum(custo_usd)
  FROM platform.image_jobs
 WHERE estado IN ('concluido', 'falhado')
   AND custo_usd > 0
   AND platform.ten_periodo(criado_at) = %s
 GROUP BY 1
"""


def _somas(linhas: Iterable[tuple[Any, ...]]) -> dict[tuple[str, str, str], Decimal]:
    return {(str(t), str(m), str(r)): Decimal(str(v)) for t, m, r, v in linhas}


def _por_modulo(somas: Mapping[tuple[str, str, str], Decimal], rubrica: str) -> dict[str, Decimal]:
    total: dict[str, Decimal] = {}
    for (_, modulo, r), valor in somas.items():
        if r == rubrica:
            total[modulo] = total.get(modulo, Decimal(0)) + valor
    return total


# --------------------------------------------------------------- linha de comando


def _mes(texto: str) -> dt.date:
    try:
        return dt.datetime.strptime(texto, "%Y-%m").date()
    except ValueError:
        raise argparse.ArgumentTypeError(f"mes invalido, use AAAA-MM: {texto!r}") from None


def _analisador() -> argparse.ArgumentParser:
    analisador = argparse.ArgumentParser(prog="h12-export", description=__doc__.split("\n")[0])
    comandos = analisador.add_subparsers(dest="comando", required=True)

    def cambio(sub: argparse.ArgumentParser) -> None:
        grupo = sub.add_mutually_exclusive_group()
        grupo.add_argument("--cambio", type=Decimal, default=None)
        grupo.add_argument("--modo", choices=sorted(custo.MODOS_DE_CAMBIO), default=None)

    consolida = comandos.add_parser("consolidar", help="as tres fontes para o ledger")
    consolida.add_argument("--cambio", type=Decimal, default=None)
    consolida.add_argument("--templates", type=Path, default=_RAIZ / "config" / "templates_por_modulo.yaml")
    precos = comandos.add_parser("carregar-precos", help="registry/plans.yaml para a base")
    precos.add_argument("--planos", type=Path, default=_RAIZ / "registry" / "plans.yaml")
    exporta = comandos.add_parser("exportar", help="o CSV pseudonimizado da H12")
    exporta.add_argument("--mes", type=_mes, required=True)
    exporta.add_argument("--saida", type=Path, default=None)
    cambio(exporta)
    alerta = comandos.add_parser("alertas", help="os alertas do criterio 8")
    alerta.add_argument("--mes", type=_mes, default=None)
    alerta.add_argument("--templates", type=Path, default=_RAIZ / "config" / "templates_por_modulo.yaml")
    cambio(alerta)
    reconcilia = comandos.add_parser("reconciliar", help="o ledger contra as fontes")
    reconcilia.add_argument("--mes", type=_mes, required=True)
    reconcilia.add_argument("--litellm", type=Path, default=None)
    reconcilia.add_argument("--painel-imagem", type=Path, default=None)
    reconcilia.add_argument("--meta", type=Path, default=None)
    return analisador


def _yaml(caminho: Path) -> dict:
    import kamba_yaml

    return kamba_yaml.load(caminho.read_text(encoding="utf-8"))


def correr(argumentos: argparse.Namespace, cursor: Any, ambiente: Mapping[str, str] | None = None) -> tuple[Any, int]:
    """Um subcomando sobre um cursor ja aberto. Separado do `main` para os ensaios."""
    comando = argumentos.comando
    if comando == "consolidar":
        fx = str(custo.cambio(None, argumentos.cambio))
        templates, modulos = mapa_de_templates(_yaml(argumentos.templates))
        gravadas = {}
        cursor.execute(modulos_custo.SQL_CONSOLIDAR_IMAGEM, (fx,))
        gravadas["imagem"] = int(cursor.fetchone()[0])
        cursor.execute(modulos_custo.SQL_CONSOLIDAR_LLM, (fx,))
        gravadas["llm"] = int(cursor.fetchone()[0])
        cursor.execute(modulos_custo.SQL_CONSOLIDAR_MENSAGEM, (templates, modulos, fx))
        gravadas["mensagem"] = int(cursor.fetchone()[0])
        return {"gravadas": gravadas, "fx_aoa_per_usd": fx}, SAIDA_OK
    if comando == "carregar-precos":
        precos = precos_do_registo(_yaml(argumentos.planos))
        cursor.execute(SQL_APAGAR_PRECOS)
        for p in precos:
            cursor.execute(SQL_INSERIR_PRECO, (p.plano, p.modulo, p.preco_teste_minor, p.estado))
        return {"precos": [asdict(p) for p in precos]}, SAIDA_OK
    if comando == "exportar":
        chave = chave_do_ambiente(ambiente)
        cursor.execute(SQL_FIXAR_CAMBIO, (str(custo.cambio(argumentos.modo, argumentos.cambio)),))
        cursor.fetchall()
        cursor.execute(SQL_H12_DO_MES, (argumentos.mes,))
        nomes = [d[0] for d in cursor.description]
        h12 = [dict(zip(nomes, linha)) for linha in cursor.fetchall()]
        cursor.execute(SQL_USO_DO_MES, (argumentos.mes,))
        uso = {(t, k): int(v) for t, k, v in cursor.fetchall()}
        return csv_de(linhas_do_csv(h12, uso, chave)), SAIDA_OK
    if comando == "alertas":
        cursor.execute(SQL_FIXAR_CAMBIO, (str(custo.cambio(argumentos.modo, argumentos.cambio)),))
        cursor.fetchall()
        cursor.execute(SQL_MES_CORRENTE)
        mes_corrente, hoje = cursor.fetchone()
        cursor.execute(SQL_H12_DO_MES, (argumentos.mes or mes_corrente,))
        nomes = [d[0] for d in cursor.description]
        h12 = [dict(zip(nomes, linha)) for linha in cursor.fetchall()]
        cursor.execute(SQL_CUSTO_DIARIO)
        diarios = [(t, d, Decimal(str(v))) for t, d, v in cursor.fetchall()]
        cursor.execute(SQL_FORNECEDOR_SEM_CUSTO)
        fornecedores = [(str(p), int(s), int(n)) for p, s, n in cursor.fetchall()]
        templates, _ = mapa_de_templates(_yaml(argumentos.templates))
        cursor.execute(modulos_custo.SQL_MENSAGENS_SEM_TARIFA, (templates,))
        sem_tarifa = int(cursor.fetchone()[0])
        alertas = (
            alertas_de_preco(h12)
            + alertas_diarios(diarios, hoje)
            + alertas_de_fornecedor(fornecedores, sem_tarifa)
        )
        return {"alertas": [asdict(a) for a in alertas]}, SAIDA_ACHADOS if alertas else SAIDA_OK
    # reconciliar
    cursor.execute(SQL_LEDGER_DO_MES, (argumentos.mes,))
    ledger = _somas(cursor.fetchall())
    cursor.execute(SQL_FONTE_LLM_DO_MES, (argumentos.mes,))
    fontes = _somas(cursor.fetchall())
    cursor.execute(SQL_FONTE_IMAGEM_DO_MES, (argumentos.mes,))
    fontes.update(_somas(cursor.fetchall()))
    internas = {k: v for k, v in ledger.items() if k[2] in ("llm", "imagem")}
    achados = reconciliar(internas, fontes, Decimal(0), "fontes")
    for opcao, rubrica in (("litellm", "llm"), ("painel_imagem", "imagem"), ("meta", "mensagem")):
        caminho = getattr(argumentos, opcao)
        if caminho is not None:
            achados += reconciliar(
                _por_modulo(ledger, rubrica), _ler_externo(caminho), TOLERANCIA[rubrica], opcao
            )
    return {"mes": str(argumentos.mes)[:7], "achados": achados}, SAIDA_ACHADOS if achados else SAIDA_OK


def _utf8() -> None:
    for fluxo in (sys.stdout, sys.stderr):
        reconfigurar = getattr(fluxo, "reconfigure", None)
        if reconfigurar is not None:
            reconfigurar(encoding="utf-8", errors="replace")


def _escrever(dados: Any, saida: Path | None) -> None:
    texto = dados if isinstance(dados, str) else json.dumps(dados, ensure_ascii=False, indent=2, default=str) + "\n"
    if saida is None:
        sys.stdout.write(texto)
    else:
        saida.write_bytes(texto.encode("utf-8"))  # LF explicito


def main(argv: list[str] | None = None) -> int:
    _utf8()
    argumentos = _analisador().parse_args(argv)

    import ligacao
    import pg8000.dbapi
    from kamba_core import tenant_guard

    try:
        conexao = ligacao.ligar("batch")
    except ligacao.ConfiguracaoEmFalta as erro:
        print(f"h12-export: {erro}", file=sys.stderr)
        return SAIDA_ERRO
    try:
        try:
            with tenant_guard.tx_batch(conexao, JOB) as cursor:
                dados, codigo = correr(argumentos, cursor)
        except pg8000.dbapi.DatabaseError as erro:
            conexao.rollback()
            print(f"h12-export: a base recusou: {erro}", file=sys.stderr)
            return SAIDA_ERRO
        except (ErroDeUso, ValueError, ArithmeticError, OSError, KeyError) as erro:
            print(f"h12-export: {erro}", file=sys.stderr)
            return SAIDA_ERRO
    finally:
        conexao.close()
    _escrever(dados, getattr(argumentos, "saida", None))
    return codigo


if __name__ == "__main__":
    raise SystemExit(main())
