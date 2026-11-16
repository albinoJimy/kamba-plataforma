"""O uso e o custo do mes de cada modulo de entrada, e o orcamento (KAM-124).

Tres coisas, e nenhuma escreve:

    gasto_do_mes(bd, tenant, modulo)   o custo do modulo no mes e o orcamento
    get_usage(bd, tenant)              a tool `get_usage` (read): uso, limite,
                                       custo e orcamento de cada modulo activo
    mensagem_orcamento_esgotado(uso)   o texto **estatico** ao dono, com os
                                       numeros do `get_usage`

## O mes e o do TEN

`platform.ten_periodo` (Africa/Luanda), o mesmo em que o `imagens_mes` e os
outros contadores fecham: o custo de um mes e o uso desse mes falam do mesmo
intervalo, e nao ha um segundo fuso escrito aqui.

## O custo da imagem le-se ao vivo

O ledger (`platform.module_cost_ledger`) e consolidado de 5 em 5 minutos pelo
`h12-export consolidar`. Uma guarda de orcamento que so o lesse deixava passar,
no intervalo, todos os trabalhos que cabem em 5 minutos. Por isso a rubrica
`imagem` le-se da `platform.image_jobs` (KAM-120) e **nao** do ledger — as
outras rubricas do modulo (o LLM de visao, as mensagens) leem-se do ledger. As
duas fontes nao se somam a mesma coisa: o `rubrica <> 'imagem'` exclui do
ledger o que a `image_jobs` ja conta.

## O orcamento e da linha do modulo, e a falta dele nega

`custo_max_mes_micro_usd` vive nos `limites` da linha de `entitlements` do
**proprio** modulo. Le-se ali e nao pelo `platform.ten_tecto`, que devolve o
minimo entre os modulos activos — com os quatro do `entrada_completo`, a foto
ficava com o orcamento do catalogo. **Sem a chave, ou com um valor que nao seja
um inteiro nao negativo, o orcamento esta esgotado**: «sem orcamento» nao quer
dizer «sem limite», a mesma regra da `0007`.

## O texto ao dono nao leva precos

A mensagem diz o uso, o limite, a percentagem do orcamento e o dia em que o mes
reabre. **Nunca** o preco de teste do modulo, que e hipotese e nao se mostra ao
cliente (`specs/EPIC-11`, KAM-124, criterio 3; o gate 3b recusa-o).
"""

from __future__ import annotations

import datetime as dt
from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from decimal import ROUND_FLOOR, Decimal, InvalidOperation
from typing import Final, Protocol

from ..tenant_guard import normalizar_tenant

#: Os quatro modulos de entrada (dicionario §3.7). Igual ao
#: `$defs.modulo_de_entrada` do registo, por ensaio.
MODULOS_DE_ENTRADA: Final = ("catalogo", "foto", "social", "orcamento")

#: O contador de uso de cada modulo. O `catalogo` nao tem contador proprio.
CHAVE_DE_USO: Final[Mapping[str, str]] = {
    "foto": "imagens_mes",
    "social": "posts_mes",
    "orcamento": "orcamentos_mes",
}

#: A chave de limite do orcamento mensal de custo (micro-dolares).
CHAVE_DO_ORCAMENTO: Final = "custo_max_mes_micro_usd"

#: Os motivos de uma recusa pela guarda de orcamento.
MOTIVO_ORCAMENTO_ESGOTADO: Final = "orcamento_esgotado"
MOTIVO_SEM_ORCAMENTO: Final = "sem_orcamento"

_MICRO_POR_USD: Final = Decimal(1_000_000)

#: O orcamento e o gasto do mes de um modulo, numa ida a base. Os parametros
#: sao `(tenant, modulo)` tres vezes, pela ordem do texto.
SQL_GASTO_DO_MES: Final = """
  SELECT (SELECT e.limites -> 'custo_max_mes_micro_usd'
            FROM platform.entitlements e
           WHERE e.tenant_id = %s::uuid AND e.modulo = %s AND e.ativo) AS orcamento,
         coalesce((SELECT sum(l.custo_usd)
                     FROM platform.module_cost_ledger l
                    WHERE l.tenant_id = %s::uuid AND l.modulo = %s
                      AND l.rubrica <> 'imagem'
                      AND platform.ten_periodo(l.ocorrido_em) = platform.ten_periodo(now())), 0)
       + coalesce((SELECT sum(j.custo_usd)
                     FROM platform.image_jobs j
                    WHERE j.tenant_id = %s::uuid AND %s = 'foto'
                      AND platform.ten_periodo(j.criado_at) = platform.ten_periodo(now())), 0)
           AS gasto_usd
"""

#: Os modulos de entrada activos, com os limites e o uso do contador no mes.
SQL_USO: Final = """
  SELECT e.modulo,
         e.limites,
         platform.ten_periodo(now()) AS periodo,
         (SELECT u.valor
            FROM platform.tenant_usage u
           WHERE u.tenant_id = e.tenant_id
             AND u.periodo = platform.ten_periodo(now())
             AND u.chave_limite = CASE e.modulo
                                      WHEN 'foto' THEN 'imagens_mes'
                                      WHEN 'social' THEN 'posts_mes'
                                      WHEN 'orcamento' THEN 'orcamentos_mes'
                                  END) AS usado
    FROM platform.entitlements e
   WHERE e.tenant_id = %s::uuid
     AND e.ativo
     AND e.modulo IN ('catalogo', 'foto', 'social', 'orcamento')
   ORDER BY e.modulo
"""


class _Resultado(Protocol):
    linhas: Sequence[Mapping[str, object]]


class ClienteSql(Protocol):
    """O `ClienteSql` do `kamba_core.ten`: uma ligacao, com o contexto do tenant."""

    def executar(self, sql: str, parametros: Sequence[object] = ()) -> _Resultado: ...


class ModuloDesconhecido(ValueError):
    """Um modulo que nao e um dos quatro de entrada."""


def _modulo(modulo: object) -> str:
    if modulo not in MODULOS_DE_ENTRADA:
        raise ModuloDesconhecido(f"modulo de entrada desconhecido: {modulo!r}")
    return str(modulo)


def _inteiro_nao_negativo(valor: object) -> int | None:
    """Um limite legivel, ou `None`. `True` nao e 1, e `7.0` nao e um inteiro."""
    if isinstance(valor, bool) or not isinstance(valor, int) or valor < 0:
        return None
    return valor


def _decimal(valor: object) -> Decimal:
    """Uma soma da base como `Decimal` finito e nao negativo; levanta se nao for."""
    try:
        numero = valor if isinstance(valor, Decimal) else Decimal(str(valor))
    except (InvalidOperation, ValueError) as erro:
        raise ValueError(f"custo ilegivel: {valor!r}") from erro
    if not numero.is_finite() or numero < 0:
        raise ValueError(f"custo ilegivel: {valor!r}")
    return numero


@dataclass(frozen=True)
class Gasto:
    """O orcamento e o gasto de um modulo num mes."""

    modulo: str
    #: `None` quando o modulo nao declara a chave, ou declara um valor ilegivel.
    orcamento_micro_usd: int | None
    gasto_usd: Decimal

    @property
    def esgotado(self) -> bool:
        """Sem orcamento esta esgotado; com ele, quando o gasto chega ao tecto."""
        if self.orcamento_micro_usd is None:
            return True
        return self.gasto_usd * _MICRO_POR_USD >= self.orcamento_micro_usd

    @property
    def motivo(self) -> str | None:
        if self.orcamento_micro_usd is None:
            return MOTIVO_SEM_ORCAMENTO
        return MOTIVO_ORCAMENTO_ESGOTADO if self.esgotado else None

    @property
    def percentagem(self) -> int | None:
        """A parte do orcamento gasta, em pontos inteiros (para baixo)."""
        if not self.orcamento_micro_usd:
            return None
        parte = self.gasto_usd * _MICRO_POR_USD * 100 / self.orcamento_micro_usd
        return int(parte.to_integral_value(rounding=ROUND_FLOOR))


def gasto_do_mes(bd: ClienteSql, tenant: object, modulo: object) -> Gasto:
    """O orcamento e o gasto do mes de um modulo. Uma ida a base, nada escrito."""
    canonico = normalizar_tenant(tenant)
    nome = _modulo(modulo)
    linhas = list(
        bd.executar(SQL_GASTO_DO_MES, (canonico, nome, canonico, nome, canonico, nome)).linhas
    )
    if not linhas:
        return Gasto(nome, None, Decimal(0))
    linha = linhas[0]
    return Gasto(
        modulo=nome,
        orcamento_micro_usd=_inteiro_nao_negativo(linha.get("orcamento")),
        gasto_usd=_decimal(linha.get("gasto_usd")),
    )


@dataclass(frozen=True)
class UsoDoModulo:
    """Uma linha do `get_usage`."""

    modulo: str
    #: O primeiro dia do mes corrente, em Africa/Luanda.
    periodo: dt.date
    #: O contador do modulo, ou `None` (o `catalogo` nao tem).
    chave: str | None
    #: O uso do contador no mes. Zero quando ainda nao ha linha de uso.
    usado: int | None
    #: O tecto do contador na linha do modulo, ou `None`.
    limite: int | None
    gasto: Gasto


def get_usage(bd: ClienteSql, tenant: object) -> tuple[UsoDoModulo, ...]:
    """A tool `get_usage` (read): os modulos de entrada activos do tenant.

    Corre com o contexto do tenant (`kamba_app`, RLS): a consulta filtra o
    tenant e a politica tambem. Um modulo inactivo ou sem linha nao aparece.
    """
    canonico = normalizar_tenant(tenant)
    usos: list[UsoDoModulo] = []
    for linha in bd.executar(SQL_USO, (canonico,)).linhas:
        modulo = _modulo(linha.get("modulo"))
        limites = linha.get("limites")
        limites = limites if isinstance(limites, Mapping) else {}
        chave = CHAVE_DE_USO.get(modulo)
        periodo = linha.get("periodo")
        if not isinstance(periodo, dt.date):
            raise ValueError(f"periodo ilegivel: {periodo!r}")
        bruto = linha.get("usado")
        usos.append(
            UsoDoModulo(
                modulo=modulo,
                periodo=periodo,
                chave=chave,
                usado=None if chave is None else (_inteiro_nao_negativo(bruto) or 0),
                limite=None if chave is None else _inteiro_nao_negativo(limites.get(chave)),
                gasto=gasto_do_mes(bd, canonico, modulo),
            )
        )
    return tuple(usos)


#: Como cada modulo se nomeia ao dono.
ROTULOS: Final[Mapping[str, str]] = {
    "catalogo": "Catálogo",
    "foto": "Foto de produtos",
    "social": "Redes sociais",
    "orcamento": "Orçamentos",
}

#: A unidade de cada contador, no plural.
UNIDADES: Final[Mapping[str, str]] = {
    "imagens_mes": "imagens",
    "posts_mes": "publicações",
    "orcamentos_mes": "orçamentos",
}

_MESES: Final = (
    "Janeiro", "Fevereiro", "Março", "Abril", "Maio", "Junho",
    "Julho", "Agosto", "Setembro", "Outubro", "Novembro", "Dezembro",
)


def _mes_seguinte(periodo: dt.date) -> str:
    return _MESES[periodo.month % 12]


def mensagem_orcamento_esgotado(uso: UsoDoModulo) -> str:
    """O texto **estatico** ao dono quando o orcamento do modulo acabou.

    Estatico quer dizer que nao passa por modelo nenhum: e este molde, com os
    numeros do `get_usage`. Sem precos.
    """
    rotulo = ROTULOS[uso.modulo]
    reabre = f"Novos pedidos voltam a ser aceites a 1 de {_mes_seguinte(uso.periodo)}."
    percentagem = uso.gasto.percentagem
    if percentagem is None:
        return f"O módulo {rotulo} não tem orçamento disponível este mês. {reabre}"
    partes = [f"O módulo {rotulo} chegou ao limite de custo deste mês ({percentagem}% usado)."]
    if uso.chave is not None and uso.limite is not None:
        partes.append(f"Uso do mês: {uso.usado} de {uso.limite} {UNIDADES[uso.chave]}.")
    partes.append(reabre)
    return " ".join(partes)


__all__ = [
    "CHAVE_DE_USO",
    "CHAVE_DO_ORCAMENTO",
    "MODULOS_DE_ENTRADA",
    "MOTIVO_ORCAMENTO_ESGOTADO",
    "MOTIVO_SEM_ORCAMENTO",
    "ROTULOS",
    "SQL_GASTO_DO_MES",
    "SQL_USO",
    "UNIDADES",
    "Gasto",
    "ModuloDesconhecido",
    "UsoDoModulo",
    "gasto_do_mes",
    "get_usage",
    "mensagem_orcamento_esgotado",
]
