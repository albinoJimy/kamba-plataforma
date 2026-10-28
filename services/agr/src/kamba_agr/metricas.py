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

import functools
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

#: As oito do gateway de LLM (KAM-030, DoD «custo e observabilidade», ADR-018).
#:
#: **O `tenant_id` nao e etiqueta de nenhuma delas, e isso resolve uma tensao do
#: bloco.** O ticket manda «metering por *tag* `tenant_id`, `vertical`, `papel`,
#: `graph_version`» (`docs/tecnica/02` §13.4), e a convencao do repositorio diz
#: que `tenant_id` **nunca** entra em etiqueta de metrica (`OBS-I`). As duas
#: conciliam-se porque sao dois sitios: as quatro etiquetas vao para os
#: metadados da chamada e para as **colunas** de `dat.llm_call_log`, que e de
#: onde o custo por tenant se le (ADR-018, e a `v_tenant_cost_daily` do
#: KAM-081); a metrica Prometheus leva so o `papel`, que e lista fechada de
#: quatro valores. O custo por tenant e uma consulta, nao uma serie temporal —
#: e tinha de ser, porque uma serie por tenant explode a cardinalidade e
#: re-identifica, que e o que o `OBS-I` diz.
#:
#: A etiqueta de `agr_llm_chamadas_total` e o **papel**, derivado dos aliases
#: pela mesma razao das tres da ToolLayer: uma lista literal transformava uma
#: invariante num numero.
METRICA_LLM_CHAMADAS: Final = "agr_llm_chamadas_total"
#: Erros do gateway, por desfecho de `dat.llm_call_log.resultado` **em
#: minusculas** — ja o sao, ao contrario dos codigos da TLS.
METRICA_LLM_ERROS: Final = "agr_llm_erros_total"
#: Duracao da **ultima** chamada, em milissegundos. `latency` e nao `latencia`,
#: para casar as outras tres do painel.
METRICA_LLM_LATENCIA: Final = "agr_llm_latency_ms"
#: Chamadas recusadas pelo *gate* de destino. **Sem etiqueta**, pela razao do
#: `agr_tool_tenant_mismatch_total`: o que um painel precisa de saber e que
#: houve uma transferencia recusada, e qual destino le-se na tabela. Em `prod`,
#: hoje, **todas** as chamadas caem aqui (KAM-069 nao existe).
METRICA_LLM_DESTINO_NEGADO: Final = "agr_llm_destino_negado_total"
#: Chamadas cujo modelo nao tem linha em `llm/precos.yaml`, e por isso ficaram
#: com `custo_usd` nulo. Hoje **todas**, porque o modelo e `por_decidir`
#: (KAM-040). Existe para que a ausencia de custo seja visivel em vez de
#: silenciosa — a licao que o `echo_latency_ms` do KAM-018 escreveu pelo outro
#: lado.
METRICA_LLM_SEM_PRECO: Final = "agr_llm_sem_preco_total"
#: Linhas de `dat.llm_call_log` que nao se conseguiram escrever. O registo nao
#: levanta (ver `llm/registo.py`), e sem este contador a perda era invisivel.
METRICA_LLM_REGISTO_FALHOU: Final = "agr_llm_registo_falhou_total"
#: Chamadas em que nao se conseguiu saber **que** fornecedor respondeu. Sem
#: isto, o registo dizia `ordem: 1` em silencio e um *fallback* aparecia como
#: tendo ido para o destino errado.
METRICA_LLM_SERVIDOR_DESCONHECIDO: Final = "agr_llm_servidor_desconhecido_total"
#: Chamadas em que o fornecedor reportou mais *tokens* de cache do que de
#: entrada. **E o sinal de que a premissa da contagem caiu**: o cliente supoe
#: que o cache vem **dentro** do `prompt_tokens` (esquema do OpenAI, que o proxy
#: normaliza) e subtrai-o; se algum fornecedor o reportar **ao lado**, a
#: subtraccao subavalia o custo em toda a linha. Cortar para zero em silencio
#: deixava isso invisivel. Divida 116.
METRICA_LLM_CONTAGEM_INCOERENTE: Final = "agr_llm_contagem_incoerente_total"

#: As cinco do validador de citacao (KAM-032, dicionario §3.30), com o
#: `vertical` por eixo.
#:
#: **Sao cinco contadores e o criterio 8 pede quatro metricas**, e a diferenca
#: resolve duas tensoes do bloco de uma vez.
#:
#: A primeira: o §9.2 do `docs/tecnica/02` nomeia `validate_fail_rate`,
#: `validate_retry_rate`, `handoff_by_citation` e `render_only_ratio`, e **tres
#: delas sao taxas**. Esta biblioteca tem contadores e medidas e nao tem
#: histogramas (ADR-018, observabilidade leve), e uma taxa guardada numa medida
#: perde o denominador — fica um numero que ninguem pode reagregar nem comparar
#: entre janelas. Exportam-se os termos e a taxa le-se no painel:
#:
#:     validate_fail_rate   falhas      / total
#:     validate_retry_rate  repeticoes  / total
#:     handoff_by_citation  handoff                 (e contagem, nao taxa)
#:     render_only_ratio    render_only / agr_turns_total{executado}
#:
#: **O `falhas` nao se soma ao `handoff`**, e a primeira versao desta nota
#: somava-os: o `falhas` conta **toda** a recusa e o `handoff` e um subconjunto
#: dela (a recusa que esgotou o tecto), pelo que a soma dava 2,0 numa recusa que
#: foi a *handoff*. Medido pela revisao adversarial com um espiao de metricas.
#:
#: **E o denominador do `render_only_ratio` e o turno e nao a validacao**, que e
#: o que o criterio 6 pede por extenso («medido por turno»): um turno com duas
#: repeticoes conta tres validacoes, pelo que `agr_validate_total` nao serve de
#: denominador para uma proporcao de **respostas**. O denominador por turno
#: existe e e o `agr_turns_total{outcome="executado"}` do KAM-025.
#:
#: A segunda: o criterio 8 pede-as «exportadas com `tenant_id` e `vertical`», e
#: **o `tenant_id` nao entra**. Nao por convencao — pela gramatica: um UUID tem
#: hifenes, nao casa `ETIQUETA`, e a chamada levanta `EtiquetaInvalida`. E a
#: mesma tensao que o KAM-030 resolveu para o §13.4 e que a divida 54 resolveu
#: para o `meta_cost_usd_total{tenant}` do KAM-015, com o mesmo desfecho: a
#: desagregacao por *tenant* faz-se onde tem significado (o `turn_id` do registo
#: do turno, de onde a amostragem do §9.2 le) e a caixa do criterio fica vazia.
METRICA_VALIDATE: Final = "agr_validate_total"
METRICA_VALIDATE_FALHAS: Final = "agr_validate_falhas_total"
METRICA_VALIDATE_REPETICOES: Final = "agr_validate_repeticoes_total"
METRICA_VALIDATE_HANDOFF: Final = "agr_validate_handoff_total"
METRICA_RENDER_ONLY: Final = "agr_render_only_total"

#: As quatro do *handoff* (KAM-034, dicionario §3.32).
#:
#: **O `tenant_id` nao e etiqueta de nenhuma delas, e o criterio 8 pede uma
#: metrica «por *tenant*».** A tensao resolve-se como no §3.14, no §3.29 e no
#: §3.30: a desagregacao por *tenant* faz-se onde tem significado — nas colunas
#: de `platform.handoffs` —, e o SLA de retoma < 15 min le-se do
#: `SQL_SLA_DE_RETOMA`, que e uma consulta e nao uma serie temporal. Uma serie
#: por *tenant* explode a cardinalidade e re-identifica (`OBS-I`), e a chamada
#: levantaria `EtiquetaInvalida` pela gramatica de qualquer maneira: um UUID tem
#: hifenes.
#:
#: **E porque e que sao quatro e nao duas.** O criterio 4 pede uma («`secret`
#: invalido devolve 401 e incrementa metrica») e o criterio 8 pede o SLA. As
#: outras duas existem porque sem elas duas propriedades deste ticket ficavam
#: invisiveis em producao: o `agr_resume_total` separa a retoma que **venceu** do
#: duplicado que nao fez nada (criterio 3 — um painel que os somasse nao
#: distinguia «uma retoma» de «duas»), e o `agr_handoff_degradado_total` conta a
#: degradacao do criterio 6, que de outra forma so aparecia como um turno
#: executado.
METRICA_HANDOFF: Final = "agr_handoff_total"
#: Retomas de `/internal/resume` e da varredura, por desfecho.
METRICA_RETOMA: Final = "agr_resume_total"
#: Retomas recusadas por credencial, por motivo. E a metrica do criterio 4.
METRICA_RETOMA_NAO_AUTORIZADA: Final = "agr_resume_nao_autorizado_total"
#: Passagens que o provedor nao aceitou abrir (criterio 6). **Sem etiqueta**: o
#: que um painel precisa de saber e que houve degradacao, e o estado da passagem
#: le-se no `agr_handoff_total{degraded}`.
#:
#: **Nao e o `agr_degraded_turns_total`** do `docs/tecnica/02` §14, que conta
#: turnos em modo deterministico por o LLM estar em baixo e que nasce com o
#: KAM-037 (ver a nota no cabecalho deste modulo). Sao duas degradacoes
#: diferentes, e dar-lhes o mesmo nome fazia um painel somar maças com laranjas.
METRICA_HANDOFF_DEGRADADO: Final = "agr_handoff_degradado_total"

#: As quatro do modo concierge (KAM-114, dicionario §3.34).
#:
#: **Nenhuma leva `tenant_id` nem `graph_version`, e o criterio 6 pede as
#: metricas «por tenant e `graph_version`».** A tensao e a mesma que as emendas
#: 1.38, 1.39 e 1.41 resolveram tres vezes, e resolve-se igual: a gramatica de
#: etiqueta recusa os dois pela **forma** — um UUID tem hifenes e `1.1.0` comeca
#: por digito e tem pontos, pelo que as duas chamadas levantariam
#: `EtiquetaInvalida` —, e uma serie por *tenant* explode a cardinalidade e
#: re-identifica (`OBS-I`).
#:
#: A desagregacao faz-se por isso nas **colunas** de `platform.draft_decisions`
#: e le-se na vista `platform.v_draft_metrics`, que e onde vivem as quatro
#: medidas que o criterio nomeia (`draft_approved_ratio`,
#: `draft_edit_ratio_p50`, `draft_decision_latency_s` e o custo por aprovado).
#: **E tem de ser assim tambem por uma segunda razao, independente da etiqueta:**
#: esta biblioteca nao implementa histogramas, pelo que um p50 e um p90 nao sao
#: exprimiveis nela — esta escrito no `medir`, e e o que faz da vista a unica
#: forma de os ter.
#:
#: O que fica aqui e o que um painel operacional precisa: quantas decisoes
#: entraram e como acabaram, quantas vezes o rascunho nao chegou ao operador, e
#: quantos estao a espera ha demasiado tempo.
#:
#: Desfechos de uma chamada a `/internal/draft-decision` (`decidido`, `repetido`,
#: `recusado`). Fica em `outcome` por omissao, e ai o nome esta certo — os tres
#: **sao** desfechos da chamada, como no `agr_resume_total`.
METRICA_DRAFT_DECISAO: Final = "agr_draft_decisao_total"
#: Como acabaram os rascunhos, pelos cinco valores de `decisao`. O eixo e
#: **estado** e nao `outcome`, pela razao do `agr_handoff_total`: o `substituido`
#: e o `expirado` nao sao desfechos de uma chamada, sao o estado em que o
#: rascunho ficou sem que ninguem chamasse nada.
METRICA_DRAFT_ESTADO: Final = "agr_draft_estado_total"
#: Rascunhos que o HND nao aceitou publicar (`RascunhoIndisponivel`). **Sem
#: etiqueta**, pela razao do `agr_handoff_degradado_total`: o que um painel
#: precisa de saber e que houve rascunhos que nenhum operador viu.
#:
#: **E conta-se precisamente porque nessas o cliente nao recebe nada** — ver a
#: nota do `concierge/portas.py`. Sem este contador, o unico sinal de uma
#: conversa que morreu em silencio era a linha `expirado` 24 h depois.
METRICA_DRAFT_INDISPONIVEL: Final = "agr_draft_indisponivel_total"
#: Quantos rascunhos estao `pendente` ha mais de `ALERTA_MINUTOS` — o alerta
#: (*proposta*) do criterio 6. **Medida e nao contador**: e um valor instantaneo
#: que a varredura repoe, e um contador monotono nao responde a «quantos estao a
#: espera agora».
METRICA_DRAFT_PENDENTES: Final = "agr_draft_pendentes"

#: As quatro da subscricao de eventos (KAM-038, dicionario §3.33).
#:
#: **Nenhuma leva `tenant_id`, `contact_id`, `conversation_id` nem `wamid`**, e
#: a razao e a mesma das quatro do *handoff*: a gramatica de etiqueta recusa-os
#: pela forma (`OBS-I`), e a desagregacao por *tenant* faz-se onde tem
#: significado — as colunas `tenant_id` de `platform.events_consumed` e de
#: `platform.events_dlq`, que as duas tem.
#:
#: **E o `agr_evt_lag_ms` e a primeira medida com etiqueta do repositorio.** O
#: DoD pede «*lag* de consumo **por consumidor**», e um valor sem eixo nao
#: responde a isso: com dois consumidores a escrever na mesma medida, o que se
#: le e o ultimo dos dois e nao o de nenhum. O eixo e o `consumer`, cujos
#: valores sao **derivados** das verticais (`agr_<id>`) pela razao das tres da
#: ToolLayer — uma lista literal transformava uma invariante num numero.
METRICA_EVT_CONSUMIDOS: Final = "agr_evt_consumidos_total"
#: Entradas abertas na DLQ, por motivo. **E o «alerta» do criterio 3**: uma
#: versao desconhecida conta aqui e escreve linha de registo, em vez de passar
#: em silencio.
METRICA_EVT_DLQ: Final = "agr_evt_dlq_total"
#: Notificacoes, por desfecho. O `sem_template` e o alerta do criterio 6.
METRICA_EVT_NOTIFICACOES: Final = "agr_evt_notificacoes_total"
#: *Lag* do ultimo evento consumido, em milissegundos, **por consumidor**.
#: Medido do `ocorrido_em` do envelope (dicionario §3.33), que e quando o facto
#: aconteceu — e nao do `registado_em`, que esconde o atraso entre o facto e a
#: transaccao que o gravou.
METRICA_EVT_LAG: Final = "agr_evt_lag_ms"

#: As cinco juntas, para quem precisa de as percorrer.
METRICAS_DO_VALIDADOR: Final = (
    METRICA_VALIDATE,
    METRICA_VALIDATE_FALHAS,
    METRICA_VALIDATE_REPETICOES,
    METRICA_VALIDATE_HANDOFF,
    METRICA_RENDER_ONLY,
)

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

#: As tres etiquetas da ToolLayer sao **derivadas** e nao escritas a mao: a
#: licao que o KAM-027 pagou no `test_gate11` — «uma lista literal transforma
#: uma invariante num numero» — e o KAM-031 e o KAM-035 acrescentam
#: especificacoes sem ter de vir aqui.
#:
#: **E derivam-se a primeira chamada e nao ao carregar, e isso nao e
#: optimizacao: era um ciclo de importacao.** A primeira versao chamava estas
#: funcoes no corpo do modulo, e o triangulo fechava — `metricas` importa
#: `tls.catalogo`, que importa `tls.get_store_info`, que importa
#: `tls.especificacoes`, e o `tls.camada` importa `metricas`. Funcionava **pela
#: ordem** em que alguem importasse primeiro: `import kamba_agr.tls.camada`
#: passava e `import kamba_agr.tls.especificacoes` dava
#: `ImportError: partially initialized module` — nos tres ficheiros que o
#: KAM-031 e o KAM-035 vao abrir primeiro. Medido pela revisao adversarial, e o
#: comentario que aqui estava afirmava o contrario.
#:
#: Com o `lru_cache`, nada se importa enquanto ninguem contar uma metrica de
#: tool, e nesse instante os modulos ja estao carregados. Ha um teste por
#: ficheiro a importa-lo **sozinho**, que e a unica forma de medir isto.
@functools.lru_cache(maxsize=None)
def _valores_derivados(metrica: str) -> tuple[str, ...]:
    if metrica == METRICA_TOOL_INVOCACOES:
        from .tls.catalogo import ESPECIFICACOES_DO_PILOTO

        return tuple(sorted(e.nome for e in ESPECIFICACOES_DO_PILOTO))
    if metrica == METRICA_TOOL_ERROS:
        from .tls.erros import CODIGOS

        return tuple(sorted(codigo.lower() for codigo in CODIGOS))
    if metrica == METRICA_TOOL_DISJUNTOR:
        from .tls.especificacoes import BACKENDS

        return tuple(sorted(BACKENDS))
    if metrica == METRICA_LLM_CHAMADAS:
        # Os papeis de `llm/aliases.yaml`, pela lista fechada do servico — o
        # `tools/llm_config` tem a mesma, e o teste de paridade confronta-as.
        from .llm.aliases import PAPEIS

        return tuple(sorted(PAPEIS))
    if metrica == METRICA_LLM_ERROS:
        from .llm.erros import RESULTADOS

        return tuple(sorted(RESULTADOS))
    if metrica in METRICAS_DO_VALIDADOR:
        # As verticais do `ToolContext`, e nao uma lista literal: o dia em que o
        # KAM-123 trouxer o `orcamento` ao contexto, a etiqueta segue sozinha.
        from .contexto import VERTICAIS

        return tuple(sorted(VERTICAIS))
    # As tres do *handoff* (KAM-034), e sao **derivadas por necessidade e nao por
    # estilo**: uma lista literal aqui fechava um ciclo de importacao. O
    # `handoff.maquina` nao importa este modulo, mas importa-lo executa o
    # `handoff/__init__.py`, que importa o `handoff.retoma`, que importa **este**
    # — e no corpo do modulo isso dava `partially initialized module`, que e o
    # defeito que as tres da ToolLayer pagaram antes. Com o `lru_cache`, nada
    # disto se importa enquanto ninguem contar uma metrica de *handoff*, e nesse
    # instante este modulo ja esta carregado.
    if metrica == METRICA_HANDOFF:
        from .handoff.maquina import ESTADOS

        return tuple(sorted(ESTADOS))
    if metrica == METRICA_RETOMA:
        from .handoff.retoma import DESFECHOS_DA_RETOMA

        return tuple(sorted(DESFECHOS_DA_RETOMA))
    if metrica == METRICA_RETOMA_NAO_AUTORIZADA:
        from .handoff.autenticacao import MOTIVOS_DE_RECUSA

        return tuple(sorted(MOTIVOS_DE_RECUSA))
    # As duas do concierge (KAM-114), e sao derivadas **por necessidade e nao
    # por estilo**, como as tres do *handoff*. O ciclo e este, e mediu-se em vez
    # de se supor — nao passa pelo `concierge/__init__.py`, que nao reexporta
    # nada de proposito, mas pelo validador:
    #
    #   metricas -> concierge.maquina -> validador.veredicto -> metricas
    #
    # O `concierge.maquina` importa o `validar` do KAM-032 porque o sinal
    # `edicao_numero_livre` do criterio 4 **e** o veredicto de citacao (uma
    # segunda implementacao divergia da primeira), e o `veredicto.py` importa
    # este modulo para contar as cinco metricas do validador. No corpo do modulo
    # isso da `partially initialized module`; com o `lru_cache`, nada disto se
    # importa enquanto ninguem contar uma metrica de rascunho, e nesse instante
    # este modulo ja esta carregado.
    if metrica == METRICA_DRAFT_DECISAO:
        from .concierge.maquina import DESFECHOS

        return tuple(sorted(DESFECHOS))
    if metrica == METRICA_DRAFT_ESTADO:
        from .concierge.maquina import DECISOES

        return tuple(sorted(DECISOES))
    # As tres de eventos com dominio proprio (KAM-038), e a quarta — o eixo do
    # `agr_evt_lag_ms` — derivada das verticais pela mesma razao das cinco do
    # validador: o dia em que uma vertical nascer, o eixo segue sozinho.
    if metrica == METRICA_EVT_CONSUMIDOS:
        from .eventos.desfechos import DESFECHOS_DO_EVENTO

        return tuple(sorted(DESFECHOS_DO_EVENTO))
    if metrica == METRICA_EVT_DLQ:
        from .eventos.desfechos import MOTIVOS_DA_DLQ

        return tuple(sorted(MOTIVOS_DA_DLQ))
    if metrica == METRICA_EVT_NOTIFICACOES:
        from .eventos.desfechos import DESFECHOS_DA_NOTIFICACAO

        return tuple(sorted(DESFECHOS_DA_NOTIFICACAO))
    if metrica == METRICA_EVT_LAG:
        from .contexto import VERTICAIS
        from .eventos.subscricoes import nome_do_consumidor

        return tuple(sorted(nome_do_consumidor(v) for v in VERTICAIS))
    raise EtiquetaInvalida(f"{metrica}: nao tem valores derivados")

#: A gramatica de uma etiqueta. A mesma de `ten/metricas.py`, e pela mesma
#: razao: um `tenant_id` tem hifenes e nao casa.
ETIQUETA: Final = re.compile(r"^[a-z][a-z0-9_]{1,62}$")

_VALORES_DA_ETIQUETA: Final = {
    METRICA_TURNOS: DESFECHOS,
    METRICA_RECUSADOS: MOTIVOS_DE_RECUSA,
    METRICA_REGISTO_NEGADO: MOTIVOS_DE_NEGACAO,
}

#: As que resolvem por `_valores_derivados`, a primeira chamada.
_DERIVADAS: Final = (
    METRICA_TOOL_INVOCACOES,
    METRICA_TOOL_ERROS,
    METRICA_TOOL_DISJUNTOR,
    METRICA_LLM_CHAMADAS,
    METRICA_LLM_ERROS,
    *METRICAS_DO_VALIDADOR,
    METRICA_HANDOFF,
    METRICA_RETOMA,
    METRICA_RETOMA_NAO_AUTORIZADA,
    METRICA_EVT_CONSUMIDOS,
    METRICA_EVT_DLQ,
    METRICA_EVT_NOTIFICACOES,
    METRICA_DRAFT_DECISAO,
    METRICA_DRAFT_ESTADO,
)

#: As **medidas** com etiqueta (KAM-038). Fora do `_DERIVADAS` de proposito:
#: aquele e consultado pelo `contar`, e uma medida que aparecesse la passava a
#: aceitar `contar(agr_evt_lag_ms, ...)` — um contador a somar milissegundos,
#: que e um numero sem significado nenhum.
_MEDIDAS_COM_ETIQUETA: Final = (METRICA_EVT_LAG,)


def _valores_de(metrica: str) -> tuple[str, ...]:
    """A lista fechada de uma metrica com etiqueta, derivada ou literal."""
    if metrica in _DERIVADAS or metrica in _MEDIDAS_COM_ETIQUETA:
        return _valores_derivados(metrica)
    return _VALORES_DA_ETIQUETA[metrica]

_CONTADORES_SEM_ETIQUETA: Final = (
    METRICA_COALESCIDAS,
    METRICA_CONTRAPRESSAO,
    METRICA_TOOL_TENANT_MISMATCH,
    METRICA_LLM_DESTINO_NEGADO,
    METRICA_LLM_SEM_PRECO,
    METRICA_LLM_REGISTO_FALHOU,
    METRICA_LLM_SERVIDOR_DESCONHECIDO,
    METRICA_LLM_CONTAGEM_INCOERENTE,
    METRICA_HANDOFF_DEGRADADO,
    METRICA_DRAFT_INDISPONIVEL,
)
_MEDIDAS: Final = (
    METRICA_DURACAO,
    METRICA_FILA,
    METRICA_LATENCIA_CHECKPOINT,
    METRICA_TAMANHO_DO_ESTADO,
    METRICA_TOOL_LATENCIA,
    METRICA_LLM_LATENCIA,
    METRICA_DRAFT_PENDENTES,
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
    METRICA_LLM_CHAMADAS: ("counter", "Chamadas ao gateway de LLM, por papel."),
    METRICA_LLM_ERROS: (
        "counter",
        "Chamadas ao gateway sem resposta, por desfecho de llm_call_log.resultado.",
    ),
    METRICA_LLM_LATENCIA: (
        "gauge",
        "Duracao da ultima chamada ao gateway, em milissegundos.",
    ),
    METRICA_LLM_DESTINO_NEGADO: (
        "counter",
        "Chamadas recusadas pelo gate de destino (ADR-008). Alerta de conformidade.",
    ),
    METRICA_LLM_SEM_PRECO: (
        "counter",
        "Chamadas cujo modelo nao tem linha em llm/precos.yaml: custo_usd nulo.",
    ),
    METRICA_LLM_REGISTO_FALHOU: (
        "counter",
        "Linhas de dat.llm_call_log que nao se conseguiram escrever.",
    ),
    METRICA_LLM_SERVIDOR_DESCONHECIDO: (
        "counter",
        "Chamadas em que nao se soube que fornecedor respondeu.",
    ),
    METRICA_LLM_CONTAGEM_INCOERENTE: (
        "counter",
        "Chamadas com mais tokens de cache do que de entrada: o custo esta subavaliado.",
    ),
    METRICA_VALIDATE: (
        "counter",
        "Validacoes de citacao, por vertical. E o denominador das taxas do §9.2.",
    ),
    METRICA_VALIDATE_FALHAS: (
        "counter",
        "Validacoes de citacao recusadas, por vertical.",
    ),
    METRICA_VALIDATE_REPETICOES: (
        "counter",
        "Recusas de citacao que geraram repeticao do modelo, por vertical.",
    ),
    METRICA_VALIDATE_HANDOFF: (
        "counter",
        "Recusas de citacao que esgotaram o tecto e foram a handoff, por vertical.",
    ),
    METRICA_RENDER_ONLY: (
        "counter",
        "Respostas sem prosa numerica livre, por vertical.",
    ),
    METRICA_HANDOFF: (
        "counter",
        "Passagens a humano, pelo estado de handoffs.status.",
    ),
    METRICA_RETOMA: (
        "counter",
        "Retomas de handoff, por desfecho: venceu o CAS, duplicado, recusada.",
    ),
    METRICA_RETOMA_NAO_AUTORIZADA: (
        "counter",
        "Retomas recusadas pelo secret do agent bot, por motivo.",
    ),
    METRICA_HANDOFF_DEGRADADO: (
        "counter",
        "Passagens que o provedor nao aceitou abrir: conversa degradada.",
    ),
    METRICA_EVT_CONSUMIDOS: (
        "counter",
        "Eventos entregues ao AGR, por desfecho do consumo.",
    ),
    METRICA_EVT_DLQ: (
        "counter",
        "Entradas abertas em events_dlq pelo AGR, por motivo. Alerta.",
    ),
    METRICA_EVT_NOTIFICACOES: (
        "counter",
        "Notificacoes por evento, por desfecho. O sem_template e alerta.",
    ),
    METRICA_EVT_LAG: (
        "gauge",
        "Lag do ultimo evento consumido, em milissegundos, por consumidor.",
    ),
    METRICA_DRAFT_DECISAO: (
        "counter",
        "Decisoes de rascunho pedidas por /internal/draft-decision, por desfecho.",
    ),
    METRICA_DRAFT_ESTADO: (
        "counter",
        "Rascunhos do concierge, pelo estado em que ficaram.",
    ),
    METRICA_DRAFT_INDISPONIVEL: (
        "counter",
        "Rascunhos que o HND nao aceitou publicar. Alerta: ninguem os viu.",
    ),
    METRICA_DRAFT_PENDENTES: (
        "gauge",
        "Rascunhos pendentes ha mais de 10 min na ultima varredura. Alerta.",
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
        elif metrica in _VALORES_DA_ETIQUETA or metrica in _DERIVADAS:
            nome = f"{metrica}:{self._validar(metrica, etiqueta)}"
        else:
            raise EtiquetaInvalida(f"{metrica}: contador desconhecido")
        with self._trinco:
            self._contadores[nome] = self._contadores.get(nome, 0) + quanto

    def medir(self, metrica: str, valor: float, etiqueta: str | None = None) -> None:
        """Guarda o **ultimo** valor de uma medida. `etiqueta` so onde a ha.

        Nao da percentis: esta biblioteca nao implementa histogramas (ADR-018,
        observabilidade leve no Piloto). E a mesma limitacao escrita no
        `chr_resolve_ms` e no `gwy_enqueue_ms`, e diz-se onde aparece: o p95 de
        latencia de turno que o criterio 5 pede mede-se na *suite* e no
        *staging*, com os valores todos, nao com este *gauge*. Vale igual para o
        p99 de *lag* do criterio 8 do KAM-038.

        **A etiqueta entrou com o KAM-038**, e entrou por necessidade: o DoD
        dele pede «*lag* de consumo **por consumidor**», e dois consumidores a
        escrever na mesma medida sem eixo davam um valor que e o do ultimo e nao
        o de nenhum. As regras sao as do `contar` — lista fechada e a mesma
        gramatica —, para que um `tenant_id` caia aqui pela forma, como la.
        """
        if metrica in _MEDIDAS_COM_ETIQUETA:
            nome = f"{metrica}:{self._validar(metrica, etiqueta)}"
        elif metrica in _MEDIDAS:
            if etiqueta is not None:
                raise EtiquetaInvalida(f"{metrica} nao leva etiqueta")
            nome = metrica
        else:
            raise EtiquetaInvalida(f"{metrica}: medida desconhecida")
        with self._trinco:
            self._medidas[nome] = float(valor)

    def _validar(self, metrica: str, etiqueta: str | None) -> str:
        if not isinstance(etiqueta, str) or not ETIQUETA.match(etiqueta):
            raise EtiquetaInvalida(
                f"{metrica}: etiqueta nao casa ^[a-z][a-z0-9_]{{1,62}}$. "
                "Identificadores (tenant_id, contact_id, conversation_id) nao "
                "entram em metricas (docs/seguranca/ameacas_stride.md, OBS-I)"
            )
        permitidos = _valores_de(metrica)
        if etiqueta not in permitidos:
            raise EtiquetaInvalida(
                f"{metrica}: {etiqueta!r} nao esta na lista fechada {permitidos}"
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
            # As medidas entram pelo mesmo criterio dos contadores — o nome
            # exacto **ou** o nome com etiqueta — desde que ha medidas com
            # etiqueta (KAM-038). Com so o nome exacto, o `agr_evt_lag_ms` de
            # cada consumidor ficava guardado e **nao aparecia na exposicao**:
            # medido e invisivel, que e pior do que nao medido.
            series.update(
                {
                    chave: valor
                    for chave, valor in medidas.items()
                    if chave == metrica or chave.startswith(f"{metrica}:")
                }
            )
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
#: O `agr_resume_nao_autorizado_total` entra pela mesma razao: conta **porque**
#: uma retoma nao aconteceu, e `sem_secret` nao e um desfecho.
_COM_MOTIVO: Final = (
    METRICA_RECUSADOS,
    METRICA_REGISTO_NEGADO,
    METRICA_RETOMA_NAO_AUTORIZADA,
    # O `agr_evt_dlq_total` conta **porque** um evento deixou de ser tentado, e
    # `tentativas_esgotadas` nao e um desfecho: e a razao de um.
    METRICA_EVT_DLQ,
)

#: O nome do eixo de cada metrica com etiqueta, quando nao e `outcome` nem
#: `motivo`. As tres da ToolLayer (KAM-028) tem eixos proprios, e chamar-lhes
#: `outcome` dizia que `get_store_info` e um desfecho.
_NOME_DO_EIXO: Final = {
    METRICA_TOOL_INVOCACOES: "tool",
    METRICA_TOOL_ERROS: "codigo",
    METRICA_TOOL_DISJUNTOR: "backend",
    # `papel` e `resultado` sao os nomes do dicionario §3.29 e das colunas de
    # `dat.llm_call_log`. Chamar `outcome` ao papel dizia que `chat` e um
    # desfecho, que e o mesmo defeito que o `_COM_MOTIVO` corrigiu.
    METRICA_LLM_CHAMADAS: "papel",
    METRICA_LLM_ERROS: "resultado",
    # O eixo das cinco do validador e o `vertical` (KAM-032, criterio 8). O
    # `tenant_id` nao e eixo de nenhuma, e a razao esta na nota delas acima.
    **{m: "vertical" for m in METRICAS_DO_VALIDADOR},
    # O eixo do `agr_handoff_total` e o **estado** de `handoffs.status` e nao um
    # desfecho: `waiting` e um estado de abertura, e chamar-lhe `outcome` dizia
    # que uma passagem que acabou de abrir ja tem desfecho. O
    # `agr_resume_total` fica em `outcome` por omissao, e ai o nome esta certo —
    # os tres valores dele **sao** desfechos da chamada.
    METRICA_HANDOFF: "estado",
    # O eixo do *lag* e o `consumer`, que e o nome da coluna de
    # `platform.events_consumed` e de `platform.events_dlq`: chamar-lhe
    # `outcome` dizia que `agr_vendedor` e um desfecho.
    METRICA_EVT_LAG: "consumer",
    # O eixo do `agr_draft_estado_total` e o **estado** em que o rascunho ficou,
    # pela razao do `agr_handoff_total`: o `substituido` e o `expirado` nao sao
    # desfechos de chamada nenhuma — ninguem os pediu —, e chamar-lhes `outcome`
    # dizia que houve uma chamada que nao houve. O `agr_draft_decisao_total`
    # fica em `outcome` por omissao, e ai o nome esta certo.
    METRICA_DRAFT_ESTADO: "estado",
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
