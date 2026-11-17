"""As metricas dos KPIs de onboarding, churn e dormentes (KAM-117).

    onboarding_activation_minutes   gauge  mediana dos minutos de actividade do
                                           dono ate a activacao, acumulada
    churn_signal{sinal}             gauge  episodios de sinal de churn abertos
    tenants_dormentes               gauge  tenants com a marca de dormente

Os tres nomes sao os dos Detalhes Tecnicos do bloco. **Nenhum tem etiqueta de
tenant**: o `OBS-I` recusa identificadores em etiquetas, e as emendas 1.21 e
1.25 do dicionario ja decidiram que o por-tenant sai de consulta SQL — aqui, da
`platform.v_churn_signals` e da `platform.v_tenant_dormente`. O `sinal` tem
dominio **fechado em cinco**, o vocabulario do criterio 2.

================================================================================
NENHUM PROCESSO SERVE ESTAS TRES METRICAS, E ISSO NAO E UM ESQUECIMENTO
================================================================================

Os valores saem do *job* `churn-daily` (`kamba_core.kpis.churn`), que corre em
lote, uma vez por dia, como `kamba_batch` — e um lote nao tem `/metrics` que o
Prometheus raspe. E a mesma lacuna que o `ops/metricas/catalogo.yaml` regista
para o motor de anomalias do KAM-060 e para o backup do KAM-079: quem ligar o
*job* a um publicador (ou a um agendador com processo vivo) fecha a regra de
alerta agregada e o painel ao mesmo tempo. Ate la, os alertas por tenant sao as
linhas abertas da `v_churn_signals`, que e o que a T2 le (`docs/runbooks/churn.md`).

Sao *gauges* e nao contadores porque o *job* **le um estado** — quantos
episodios estao abertos agora — e nao conta acontecimentos: repetir o *job* no
mesmo dia nao pode mudar o numero, e um contador somava-o.
"""

from __future__ import annotations

import math
import re
import threading

#: Mediana, em minutos, da actividade do dono entre a entrada e a activacao,
#: sobre os casos activos (acumulado). Alvo *proposta*: <= 60.
METRICA_ACTIVACAO_MINUTOS = "onboarding_activation_minutes"

#: Episodios de sinal de churn abertos, por `sinal`.
METRICA_SINAL_DE_CHURN = "churn_signal"

#: Tenants com a marca de dormente (nao e um estado do tenant).
METRICA_DORMENTES = "tenants_dormentes"

#: Os cinco sinais do criterio 2, pela ordem do `docs/tecnica/10` §13. Igual ao
#: dominio da coluna `churn_signal_episode.sinal`, por ensaio.
SINAIS = (
    "dono_inactivo",
    "sem_pedidos",
    "canal_desligado",
    "pagamento_em_atraso",
    "catalogo_desactualizado",
)

#: A gramatica de uma etiqueta. A mesma do `ten/metricas.py` e do `obs_lint`.
ETIQUETA = re.compile(r"^[a-z][a-z0-9_]{1,62}$")

_AJUDA = {
    METRICA_ACTIVACAO_MINUTOS: (
        "gauge",
        "Mediana dos minutos de actividade do dono ate a activacao (acumulado).",
    ),
    METRICA_SINAL_DE_CHURN: (
        "gauge",
        "Episodios de sinal de churn abertos, por sinal.",
    ),
    METRICA_DORMENTES: (
        "gauge",
        "Tenants com a marca de dormente.",
    ),
}


class ValorInvalido(ValueError):
    """Um sinal fora dos cinco, um valor negativo ou um NaN."""


class MetricasDeKpis:
    """Os tres numeros, em memoria, com trinco, sem dependencias."""

    def __init__(self) -> None:
        self._trinco = threading.Lock()
        self._sinais: dict[str, int] = {}
        self._activacao: float | None = None
        self._dormentes: int | None = None

    def definir_sinais(self, abertos: dict[str, int]) -> None:
        """Poe os cinco *gauges* do `churn_signal` de uma vez.

        Um sinal em falta conta **zero**, e um sinal desconhecido levanta: a
        lista e fechada porque e o vocabulario do criterio 2.
        """
        novos: dict[str, int] = {}
        for sinal, valor in abertos.items():
            if sinal not in SINAIS:
                raise ValorInvalido(f"sinal {sinal!r} fora de {SINAIS}")
            novos[sinal] = _contagem(valor)
        with self._trinco:
            self._sinais = {s: novos.get(s, 0) for s in SINAIS}

    def definir_activacao(self, minutos: float | None) -> None:
        """A mediana; `None` quando ainda nao ha caso activo.

        Recusa `NaN` e negativos: uma comparacao com `NaN` e sempre falsa, e um
        alerta `> 60` deixaria de disparar em silencio.
        """
        if minutos is not None and (math.isnan(minutos) or minutos < 0):
            raise ValorInvalido(f"{METRICA_ACTIVACAO_MINUTOS}: {minutos!r}")
        with self._trinco:
            self._activacao = None if minutos is None else float(minutos)

    def definir_dormentes(self, quantos: int) -> None:
        with self._trinco:
            self._dormentes = _contagem(quantos)

    def ler(self) -> dict[str, object]:
        with self._trinco:
            return {
                "sinais": dict(self._sinais),
                "activacao": self._activacao,
                "dormentes": self._dormentes,
            }

    def exposicao(self) -> str:
        """Formato de exposicao do Prometheus.

        Os *gauges* aparecem **so depois de o *job* os ter definido**: um
        `tenants_dormentes 0` sem corrida nenhuma le-se como «ninguem esta
        dormente», que e a leitura errada. Ausente, o `absent()` do PromQL ve-o.
        Depois de definidos, os cinco sinais aparecem todos, a zero os que nao
        tem episodio aberto.
        """
        estado = self.ler()
        sinais: dict[str, int] = estado["sinais"]  # type: ignore[assignment]
        linhas: list[str] = []
        for nome, (tipo, ajuda) in _AJUDA.items():
            linhas.append(f"# HELP {nome} {ajuda}")
            linhas.append(f"# TYPE {nome} {tipo}")
            if nome == METRICA_SINAL_DE_CHURN:
                for sinal in SINAIS if sinais else ():
                    linhas.append(f'{nome}{{sinal="{sinal}"}} {sinais[sinal]}')
            elif nome == METRICA_ACTIVACAO_MINUTOS:
                if estado["activacao"] is not None:
                    linhas.append(f"{nome} {_numero(estado['activacao'])}")  # type: ignore[arg-type]
            elif estado["dormentes"] is not None:
                linhas.append(f"{nome} {estado['dormentes']}")
        return "\n".join(linhas) + "\n"


def _contagem(valor: int) -> int:
    if isinstance(valor, bool) or not isinstance(valor, int) or valor < 0:
        raise ValorInvalido(f"uma contagem e um inteiro nao negativo: {valor!r}")
    return valor


def _numero(valor: float) -> str:
    if valor == int(valor):
        return str(int(valor))
    return repr(round(valor, 6))


#: As metricas do processo do *job*. Existe para quem ligar a porta.
METRICAS = MetricasDeKpis()
