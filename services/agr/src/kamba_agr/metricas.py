"""As metricas do AGR (KAM-025, DoD «Custo e observabilidade», ADR-018).

    agr_turns_total{outcome}         counter  turnos, por desfecho
    agr_turn_latency_ms              gauge    duracao do ultimo turno, em ms
    agr_queue_depth                  gauge    turnos a espera na admissao
    agr_admitted_rejected_total{motivo}  counter  turnos recusados na admissao
    agr_coalesced_total              counter  mensagens coalescidas
    agr_backpressure_total           counter  vezes que a fila passou o limiar
    agr_registry_denied_total{motivo}    counter  resolucoes do registo negadas (KAM-027)

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

#: Resolucoes do AgentRegistry negadas, por motivo (KAM-027, criterio 6).
#:
#: E o «emite alerta» do critero 6: sem entitlement activo, o `resolve` devolve
#: a resposta estatica e conta aqui. Vive neste modulo e nao no `registo/`
#: porque e aqui que vivem as outras oito — e porque um contador que este
#: ficheiro nao conheca **levanta** `EtiquetaInvalida` («contador
#: desconhecido»), que foi como se descobriu que faltava: o `resolve` contava
#: contra um duplo nos testes e teria rebentado em producao.
METRICA_REGISTO_NEGADO: Final = "agr_registry_denied_total"

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

#: As cinco da ToolLayer (KAM-028, DoD «metricas de latencia e erro por tool»).
#:
#: A etiqueta de `agr_tool_invocacoes_total` e o **nome da tool**, e isso e
#: seguro por construcao: os nomes sao os onze do catalogo (dicionario §3.26),
#: lista fechada, e um nome de tool casa a gramatica de etiqueta porque a
#: especificacao o exige com a mesma expressao.
METRICA_TOOL_INVOCACOES: Final = "agr_tool_invocacoes_total"
#: Erros de tool, por codigo do §6.5 **em minusculas**: a gramatica de etiqueta
#: exige-as e o codigo canonico e maiusculo.
METRICA_TOOL_ERROS: Final = "agr_tool_erros_total"
#: Duracao da **ultima** invocacao, em milissegundos. O nome tem `latency` e nao
#: `latencia` para casar o `agr_turn_latency_ms` e o `agr_checkpoint_latency_ms`,
#: que e o que um painel agrupa.
METRICA_TOOL_LATENCIA: Final = "agr_tool_latency_ms"
#: Vezes que o disjuntor de um backend abriu (critero 7).
METRICA_TOOL_DISJUNTOR: Final = "agr_tls_disjuntor_aberto_total"
#: O «gera alerta de seguranca» do critero 8. **Sem etiqueta**: o que um painel
#: precisa de saber e que houve um `TENANT_MISMATCH`, e qual tool foi le-se na
#: `tool_audit`. Uma etiqueta por tool aqui convidava a tratar o alerta como uma
#: estatistica por tool, e um destes nao e estatistica.
METRICA_TOOL_TENANT_MISMATCH: Final = "agr_tool_tenant_mismatch_total"

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

#: Porque e que o `AgentRegistry.resolve` nao devolveu vertical. Lista
#: **fechada**: e etiqueta, e e a do dicionario §3.26.
#:
#: `sem_entitlement`        o tenant nao tem o modulo da vertical activo
#: `vertical_desconhecida`  o `ctx.vertical` nao esta no registo carregado
MOTIVOS_DE_NEGACAO: Final = ("sem_entitlement", "vertical_desconhecida")

#: Os nomes de tool que podem ser etiqueta. **Derivados do catalogo, nao
#: escritos a mao**: a licao que o KAM-027 pagou no `test_gate11` — «uma lista
#: literal transforma uma invariante num numero» — e o KAM-031 e o KAM-035
#: acrescentam especificacoes sem ter de vir aqui.
#:
#: O `import` e local a este modulo e feito ao carregar, nao dentro da funcao:
#: o `tls.catalogo` importa o `tls.especificacoes`, que importa o
#: `registo.validar`, e nenhum dos tres importa este ficheiro — nao ha ciclo.
def _nomes_de_tool() -> tuple[str, ...]:
    from .tls.catalogo import ESPECIFICACOES_DO_PILOTO

    return tuple(sorted(e.nome for e in ESPECIFICACOES_DO_PILOTO))


#: Os dez codigos do §6.5 em minusculas. Derivados, pela mesma razao.
def _codigos_de_erro() -> tuple[str, ...]:
    from .tls.erros import CODIGOS

    return tuple(sorted(codigo.lower() for codigo in CODIGOS))


#: Os backends do §6.5, que sao a unidade do disjuntor. Derivados.
def _backends() -> tuple[str, ...]:
    from .tls.especificacoes import BACKENDS

    return tuple(sorted(BACKENDS))

#: A gramatica de uma etiqueta. A mesma de `ten/metricas.py`, e pela mesma
#: razao: um `tenant_id` tem hifenes e nao casa.
ETIQUETA: Final = re.compile(r"^[a-z][a-z0-9_]{1,62}$")

_VALORES_DA_ETIQUETA: Final = {
    METRICA_TURNOS: DESFECHOS,
    METRICA_RECUSADOS: MOTIVOS_DE_RECUSA,
    METRICA_REGISTO_NEGADO: MOTIVOS_DE_NEGACAO,
    METRICA_TOOL_INVOCACOES: _nomes_de_tool(),
    METRICA_TOOL_ERROS: _codigos_de_erro(),
    METRICA_TOOL_DISJUNTOR: _backends(),
}

_CONTADORES_SEM_ETIQUETA: Final = (
    METRICA_COALESCIDAS,
    METRICA_CONTRAPRESSAO,
    METRICA_TOOL_TENANT_MISMATCH,
)
_MEDIDAS: Final = (
    METRICA_DURACAO,
    METRICA_FILA,
    METRICA_LATENCIA_CHECKPOINT,
    METRICA_TAMANHO_DO_ESTADO,
    METRICA_TOOL_LATENCIA,
)

_AJUDA: Final = {
    METRICA_TURNOS: ("counter", "Turnos do AGR, por desfecho."),
    METRICA_DURACAO: ("gauge", "Duracao do ultimo turno, em milissegundos."),
    METRICA_FILA: ("gauge", "Turnos a espera na admissao do AGR."),
    METRICA_RECUSADOS: ("counter", "Turnos recusados na admissao, por motivo."),
    METRICA_COALESCIDAS: ("counter", "Mensagens coalescidas num turno em curso."),
    METRICA_CONTRAPRESSAO: ("counter", "Vezes que a fila passou o limiar."),
    METRICA_REGISTO_NEGADO: (
        "counter",
        "Resolucoes do AgentRegistry negadas, por motivo.",
    ),
    METRICA_LATENCIA_CHECKPOINT: (
        "gauge",
        "Duracao da ultima gravacao de checkpoint, em milissegundos.",
    ),
    METRICA_TAMANHO_DO_ESTADO: (
        "gauge",
        "Tamanho do ultimo estado serializado, em octetos.",
    ),
    METRICA_TOOL_INVOCACOES: ("counter", "Invocacoes da ToolLayer, por tool."),
    METRICA_TOOL_ERROS: ("counter", "Erros da ToolLayer, por codigo do §6.5."),
    METRICA_TOOL_LATENCIA: (
        "gauge",
        "Duracao da ultima invocacao de tool, em milissegundos.",
    ),
    METRICA_TOOL_DISJUNTOR: ("counter", "Aberturas do disjuntor, por backend."),
    METRICA_TOOL_TENANT_MISMATCH: (
        "counter",
        "Invocacoes recusadas por TENANT_MISMATCH. Alerta de seguranca.",
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


#: As metricas cuja etiqueta se chama `motivo` e nao `outcome`. As duas contam
#: **porque** algo nao aconteceu, e `outcome` ali era o nome errado do eixo —
#: o dicionario §3.26 escreve `motivo` para o `agr_registry_denied_total`, e
#: sem esta linha a exposicao dizia `outcome` e contradizia o canon. Medido.
_COM_MOTIVO: Final = (METRICA_RECUSADOS, METRICA_REGISTO_NEGADO)

#: O nome do eixo de cada metrica com etiqueta, quando nao e `outcome` nem
#: `motivo`. As tres da ToolLayer (KAM-028) tem eixos proprios, e chamar-lhes
#: `outcome` dizia que `get_store_info` e um desfecho.
_NOME_DO_EIXO: Final = {
    METRICA_TOOL_INVOCACOES: "tool",
    METRICA_TOOL_ERROS: "codigo",
    METRICA_TOOL_DISJUNTOR: "backend",
}


def _etiqueta_de(metrica: str) -> str:
    if metrica in _NOME_DO_EIXO:
        return _NOME_DO_EIXO[metrica]
    return "motivo" if metrica in _COM_MOTIVO else "outcome"


def _numero(valor: float) -> str:
    return str(int(valor)) if float(valor).is_integer() else repr(float(valor))


#: O registo do processo. Um modulo por dominio e nao um registo central, pelo
#: precedente que o KAM-009 abriu.
METRICAS: Final = MetricasDoAgr()
