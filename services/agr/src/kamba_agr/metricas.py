"""As metricas do AGR (KAM-025, DoD «Custo e observabilidade», ADR-018).

    agr_turns_total{outcome}         counter  turnos, por desfecho
    agr_turn_latency_ms              gauge    duracao do ultimo turno, em ms
    agr_queue_depth                  gauge    turnos a espera na admissao
    agr_admitted_rejected_total{motivo}  counter  turnos recusados na admissao
    agr_coalesced_total              counter  mensagens coalescidas
    agr_backpressure_total           counter  vezes que a fila passou o limiar

A forma e a do `ten/metricas.py`, que e a do `tenant_guard.Contadores`: um
dicionario de numeros, em memoria, com um trinco, sem dependencias. Esta
biblioteca nao abre portas — quem expoe `/metrics` e o servico (e no AGR ainda
nao expoe: o KAM-001 nao criou a rota e este ticket nao a reclama; a leitura
faz-se por `METRICAS.exposicao()`, que e o que a *suite* le).

## O `tenant_id` nao entra em etiqueta nenhuma, e a regra e de gramatica

`docs/seguranca/ameacas_stride.md` (`OBS-I`): identificadores em etiquetas
explodem a cardinalidade e re-identificam. Como em `ten/metricas.py`, a regra
impoe-se pela **forma** e nao por uma lista de nomes proibidos: uma etiqueta
tem de casar `^[a-z][a-z0-9_]{1,62}$`, e um UUID canonico tem hifenes — nao
casa, e a chamada levanta. Uma lista de proibidos protegia contra os nomes de
que alguem se lembrou; a gramatica protege contra a forma. Ha um teste que lhe
passa um `tenant_id` a serio.

**E aqui as etiquetas sao lista fechada**, ao contrario das do TEN: os desfechos
e os motivos sao deste codigo e nao crescem com o registo nem com o trafego. A
gramatica fica de qualquer forma, porque e ela que apanha um identificador que
alguem passe por engano.

## O `agr_degraded_turns_total` **nao** esta aqui, e nao e esquecimento

O DoD deste ticket pede «metricas de fila, latencia de turno e
`degraded_turns`». As duas primeiras estao; a terceira nao, e a razao e a que o
`modos/metricas.ts` do KAM-018 escreveu para o `echo_latency_ms`: **uma metrica
declarada e sempre a zero e pior do que uma metrica ausente** — um painel que a
mostre a zero diz «nao houve turnos degradados» quando o que se passa e que
ninguem os mede.

O `degraded_turns` do `docs/tecnica/02` §14 conta turnos que correram em **modo
deterministico** por o LLM estar indisponivel, lento ou sem orcamento. O modo
deterministico e o KAM-037 e nao existe; nao ha, neste ticket, caminho nenhum
por onde um turno possa ficar degradado. Nasce com o ticket que o consegue
medir, e fica declarada no dicionario §3.24 como pertencendo ao AGR.

O que **existe** aqui, e e o que o DoD quer ver, e o `agr_backpressure_total`: as
vezes que a fila de admissao passou o limiar que, com o KAM-037 feito, passa a
ser o gatilho do modo deterministico. Conta de verdade, e a *suite* mede-o.
"""

from __future__ import annotations

import re
import threading
from typing import Final

#: Turnos, por desfecho.
METRICA_TURNOS: Final = "agr_turns_total"
#: Duracao do ultimo turno, em ms.
METRICA_DURACAO: Final = "agr_turn_latency_ms"
#: Turnos a espera na admissao, agora.
METRICA_FILA: Final = "agr_queue_depth"
#: Turnos que nao chegaram a correr, por motivo.
METRICA_RECUSADOS: Final = "agr_admitted_rejected_total"
#: Mensagens que se juntaram a um turno em curso (criterio 3).
METRICA_COALESCIDAS: Final = "agr_coalesced_total"
#: Vezes que a fila de admissao passou o limiar de contrapressao.
METRICA_CONTRAPRESSAO: Final = "agr_backpressure_total"

#: Quanto demorou a **ultima** gravacao de checkpoint, em milissegundos
#: (KAM-026). O alvo do `docs/tecnica/02` §15.1 e 0,05-0,15 s «Postgres local»,
#: e e **a medir**, nao um limiar: nada falha por o exceder.
METRICA_LATENCIA_CHECKPOINT: Final = "agr_checkpoint_latency_ms"
#: O tamanho do **ultimo** estado serializado, em octetos (KAM-026).
#:
#: E o numero que diz se a janela recortada esta a fazer o seu trabalho: um
#: estado que cresce sem parar quer dizer que o `ingest` nao esta a recortar,
#: e o `JANELA_MAXIMA` so levanta quando ja e tarde.
METRICA_TAMANHO_DO_ESTADO: Final = "agr_checkpoint_state_bytes"

#: O que aconteceu a um turno. Lista **fechada**: e etiqueta.
#:
#: `executado`        correu o grafo
#: `entregue_ao_hnd`  o humano tinha a palavra: reencaminhado (criterio 6)
#: `sem_conversa`     a conversa nao se conseguiu ler — nao existe, foi
#:                    apagada, ou o contexto de RLS e de outro *tenant*. As
#:                    tres dao a mesma decisao (nao entra no grafo) e por isso
#:                    dao o mesmo desfecho: o que um painel precisa de saber e
#:                    que houve turnos que nao encontraram a conversa, e a
#:                    razao exacta nao esta ao alcance de quem le zero linhas
#: `falhou`           levantou dentro do turno; o *job* volta a fila
DESFECHOS: Final = ("executado", "entregue_ao_hnd", "sem_conversa", "falhou")

#: Porque e que um turno nao foi admitido. Lista **fechada**: e etiqueta.
#:
#: `ritmo`             o contacto passou o limite de mensagens/minuto
#:                     (criterio 5, descarte silencioso)
#: `tecto_do_tenant`   o tecto de concorrencia do *tenant* estava cheio; o
#:                     chamador leva 503 e o *shim* devolve o *job* a fila
#: `invocacao_invalida`  o corpo nao e um `agent_invocation`
MOTIVOS_DE_RECUSA: Final = ("ritmo", "tecto_do_tenant", "invocacao_invalida")

#: A gramatica de uma etiqueta. A mesma de `ten/metricas.py`, e pela mesma
#: razao: um `tenant_id` tem hifenes e nao casa.
ETIQUETA: Final = re.compile(r"^[a-z][a-z0-9_]{1,62}$")

_VALORES_DA_ETIQUETA: Final = {
    METRICA_TURNOS: DESFECHOS,
    METRICA_RECUSADOS: MOTIVOS_DE_RECUSA,
}

_CONTADORES_SEM_ETIQUETA: Final = (METRICA_COALESCIDAS, METRICA_CONTRAPRESSAO)
_MEDIDAS: Final = (
    METRICA_DURACAO,
    METRICA_FILA,
    METRICA_LATENCIA_CHECKPOINT,
    METRICA_TAMANHO_DO_ESTADO,
)

_AJUDA: Final = {
    METRICA_TURNOS: ("counter", "Turnos do AGR, por desfecho."),
    METRICA_DURACAO: ("gauge", "Duracao do ultimo turno, em milissegundos."),
    METRICA_FILA: ("gauge", "Turnos a espera na admissao do AGR."),
    METRICA_RECUSADOS: ("counter", "Turnos recusados na admissao, por motivo."),
    METRICA_COALESCIDAS: ("counter", "Mensagens coalescidas num turno em curso."),
    METRICA_CONTRAPRESSAO: ("counter", "Vezes que a fila passou o limiar."),
    METRICA_LATENCIA_CHECKPOINT: (
        "gauge",
        "Duracao da ultima gravacao de checkpoint, em milissegundos.",
    ),
    METRICA_TAMANHO_DO_ESTADO: (
        "gauge",
        "Tamanho do ultimo estado serializado, em octetos.",
    ),
}


class EtiquetaInvalida(ValueError):
    """Uma etiqueta que nao casa a gramatica ou nao esta na lista fechada.

    Um `tenant_id` cai sempre aqui, pela gramatica.
    """


class MetricasDoAgr:
    """Contadores e medidas em memoria, seguros entre *threads*. So numeros."""

    def __init__(self) -> None:
        self._trinco = threading.Lock()
        self._contadores: dict[str, int] = {}
        self._medidas: dict[str, float] = {}

    def contar(self, metrica: str, etiqueta: str | None = None, quanto: int = 1) -> None:
        """Soma `quanto` ao contador. `etiqueta` so onde a metrica a tem."""
        if metrica in _CONTADORES_SEM_ETIQUETA:
            if etiqueta is not None:
                raise EtiquetaInvalida(f"{metrica} nao leva etiqueta")
            nome = metrica
        elif metrica in _VALORES_DA_ETIQUETA:
            nome = f"{metrica}:{self._validar(metrica, etiqueta)}"
        else:
            raise EtiquetaInvalida(f"{metrica}: contador desconhecido")
        with self._trinco:
            self._contadores[nome] = self._contadores.get(nome, 0) + quanto

    def medir(self, metrica: str, valor: float) -> None:
        """Guarda o **ultimo** valor de uma medida.

        Nao da percentis: esta biblioteca nao implementa histogramas (ADR-018,
        observabilidade leve no Piloto). E a mesma limitacao escrita no
        `chr_resolve_ms` e no `gwy_enqueue_ms`, e diz-se onde aparece: o p95 de
        latencia de turno que o criterio 5 pede mede-se na *suite* e no
        *staging*, com os valores todos, nao com este *gauge*.
        """
        if metrica not in _MEDIDAS:
            raise EtiquetaInvalida(f"{metrica}: medida desconhecida")
        with self._trinco:
            self._medidas[metrica] = float(valor)

    def _validar(self, metrica: str, etiqueta: str | None) -> str:
        if not isinstance(etiqueta, str) or not ETIQUETA.match(etiqueta):
            raise EtiquetaInvalida(
                f"{metrica}: etiqueta nao casa ^[a-z][a-z0-9_]{{1,62}}$. "
                "Identificadores (tenant_id, contact_id, conversation_id) nao "
                "entram em metricas (docs/seguranca/ameacas_stride.md, OBS-I)"
            )
        if etiqueta not in _VALORES_DA_ETIQUETA[metrica]:
            raise EtiquetaInvalida(
                f"{metrica}: {etiqueta!r} nao esta na lista fechada "
                f"{_VALORES_DA_ETIQUETA[metrica]}"
            )
        return etiqueta

    def ler(self) -> dict[str, float]:
        with self._trinco:
            return {**self._contadores, **self._medidas}

    def repor(self) -> None:
        with self._trinco:
            self._contadores.clear()
            self._medidas.clear()

    def exposicao(self) -> str:
        """O texto no formato do Prometheus, com `# TYPE` e `# HELP`."""
        with self._trinco:
            contadores = dict(self._contadores)
            medidas = dict(self._medidas)
        linhas: list[str] = []
        for metrica, (tipo, ajuda) in _AJUDA.items():
            series = {
                chave: valor
                for chave, valor in contadores.items()
                if chave == metrica or chave.startswith(f"{metrica}:")
            }
            if metrica in medidas:
                series[metrica] = medidas[metrica]
            if not series:
                continue
            linhas.append(f"# HELP {metrica} {ajuda}")
            linhas.append(f"# TYPE {metrica} {tipo}")
            for chave in sorted(series):
                etiqueta = chave[len(metrica) + 1 :] if ":" in chave else ""
                rotulo = f'{{{_etiqueta_de(metrica)}="{etiqueta}"}}' if etiqueta else ""
                linhas.append(f"{metrica}{rotulo} {_numero(series[chave])}")
        return "\n".join(linhas) + ("\n" if linhas else "")


def _etiqueta_de(metrica: str) -> str:
    return "motivo" if metrica == METRICA_RECUSADOS else "outcome"


def _numero(valor: float) -> str:
    return str(int(valor)) if float(valor).is_integer() else repr(float(valor))


#: O registo do processo. Um modulo por dominio e nao um registo central, pelo
#: precedente que o KAM-009 abriu.
METRICAS: Final = MetricasDoAgr()
