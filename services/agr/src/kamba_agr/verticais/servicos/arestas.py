"""Os nos e as arestas do grafo de Servicos (§8.1, e o concierge do ADR-L005).

## Porque e que a tabela vive em codigo, e nao so no diagrama

O criterio 1 do bloco do KAM-035 pede «a tabela de arestas **derivada** do
diagrama de §8.1 (guardada como `EDGES` em codigo) coincide com o grafo
compilado». O §8.1 da um `stateDiagram-v2` e **nao** da tabela — ao contrario do
§7.3, que da a do Vendedor por extenso. Derivar e o trabalho deste ticket, e o
que o torna verificavel e cada aresta levar a linha do diagrama que a autoriza.

## Trinta e nove linhas, trinta e nove arestas — e aqui as duas contagens batem

No Vendedor nao batiam: a tabela do §7.3 tem trinta e nove **linhas** e quarenta
e duas **arestas**, porque duas linhas carregam mais do que uma. O diagrama do
§8.1 nao tem esse problema — cada transicao de um `stateDiagram-v2` tem **uma**
origem e **um** destino, pelo que as trinta e nove transicoes sao trinta e nove
arestas dirigidas.

**O que nao bate e outra coisa, e e por isso que isto fica escrito:** as nove
intencoes do §8.2 saem do `classify` por **sete** arestas. A transicao
`classify --> slots_collect` carrega `marcar` e `remarcar` no rotulo, e a
`disponibilidade` — que o diagrama **nao** desenha — encaminha-se para o mesmo
no. Tres intencoes, uma aresta. Contar intencoes a pensar que se contam arestas
dava quarenta e uma onde ha trinta e nove, e a lista do §8.2 e a prova de que a
contagem a fazer e das transicoes.

## As tres arestas que o diagrama nao desenha, e que o texto ao lado manda

O paragrafo imediatamente depois do diagrama escreve: «Falhas de backend em
`check_availability`/`book_slot`/`cancel_booking` seguem `handoff_prepare` como
no Vendedor (**omitido do diagrama por legibilidade**; a tabela de arestas segue
a mesma regra `UPSTREAM_*`)». Sao autorizacao escrita, nao inferencia nossa —
mas **nao sao linhas do diagrama**, e por isso levam `fonte` propria
(`FONTE_DA_PROSA_DO_81`) e nao contam para o `LINHAS_DO_81`. E a licao do
`FONTE_DO_CONCIERGE` do Vendedor, aplicada antes de custar: inflacionar a
constante era faze-la mentir sobre um diagrama que este ticket nao altera.

## O concierge entra sem decisao nova, e cita-se em vez de se redecidir

O `docs/adr/ADR-L005-degradacao-e-concierge.md` (2026-10-29) decide que, com a
politica `concierge` activa, **a resposta do modo deterministico tambem vai a
aprovacao humana** — os dois mecanismos somam-se. O `send` e o no partilhado
onde o KAM-114 intercepta, pelo que a decisao aplica-se a este grafo pela mesma
construcao: nao ha codigo novo, ha quatro arestas e dois nos reutilizados.

**E nao e opcional.** Sem elas, o `send` deste grafo poe `concierge.estado` a
`a_aprovar` e nao enfileira — e o turno acabava com o cliente sem resposta e
sem ninguem a quem aprovar. Um no partilhado traz as arestas de que depende.

## O que `chave` e, e porque nao e decoracao

Numa aresta condicional o LangGraph nao liga `de` a `para`: liga `de` a um
encaminhador, e o encaminhador devolve uma **chave** que o `path_map` traduz num
no. A `chave` aqui e a desse mapa, e e ela que torna o teste de contrato capaz
de apanhar a troca mais facil de fazer e mais dificil de ver — dois destinos
trocados no mapa de um encaminhador, que no grafo compilado da o mesmo
**conjunto** de arestas.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Final

from langgraph.graph import END, START

from ...tls.contexto import PREFIXO_DE_CONFIRMACAO as _PREFIXO_PARTILHADO

#: A versao do grafo de Servicos, SemVer. Vai na coluna `graph_version` da
#: `tool_audit` (§6.4) e do `llm_call_log` (KAM-030), e e metade do que o DoD
#: pede por «Eval-gate: SemVer do grafo e de `servicos.yaml`».
#:
#: **Nasce em 1.0.0 e nao herda o 1.2.0 do Vendedor.** Sao dois grafos e duas
#: linhas de versao: o `VERSAO_DO_GRAFO` do Vendedor esta em 1.2.0 porque o
#: KAM-114 e o KAM-037 lhe acrescentaram nos, e nenhum desses nos e historia
#: deste grafo. Partilhar a constante punha uma vertical a subir a versao da
#: outra — e o `graph_version` de uma linha de auditoria deixava de dizer que
#: grafo correu.
#:
#: A regra de subida e a do Vendedor: *minor* quando um no entra ou sai,
#: *major* quando o estado deixa de ser compativel com um `interrupt` pendente
#: (§12, linha do versionamento).
#:
#: **A outra metade do «Eval-gate» nao se entrega, e mede-se:** o gate 13 nao
#: existe (`grep -n "ci-13" Makefile` sai com 1 e zero linhas; os alvos sao
#: `ci-1` a `ci-11`) e nasce com o KAM-040, que o proprio bloco nomeia. A caixa
#: fica vazia, com a razao escrita na seccao de verificacao do bloco.
VERSAO_DO_GRAFO: Final = "1.0.0"

#: O numero de transicoes do diagrama de §8.1. Afirma-se para que a derivacao
#: do criterio 1 continue verificavel depois de alguem acrescentar uma aresta
#: que o diagrama nao tem.
LINHAS_DO_81: Final = 39

#: O valor de `Aresta.fonte` das tres arestas que o paragrafo depois do diagrama
#: autoriza e o diagrama omite «por legibilidade». **Nao contam para o
#: `LINHAS_DO_81`** — ver a nota do modulo.
FONTE_DA_PROSA_DO_81: Final = "02 §8.1, prosa (UPSTREAM_*)"

#: O valor de `Aresta.fonte` das quatro arestas do concierge. O ticket e o
#: KAM-114, que escreveu os nos; o que as traz para **este** grafo e o
#: ADR-L005, e por isso o valor nomeia os dois.
FONTE_DO_CONCIERGE: Final = "KAM-114 (ADR-L005)"

#: O valor de `Aresta.fonte` da aresta que a tabela de tools do §6.2 obriga e o
#: diagrama de §8.1 nao desenha: o portao de confirmacao do cancelamento. **Nao
#: conta para o `LINHAS_DO_81`**, pela razao do `FONTE_DA_PROSA_DO_81` — ver a
#: nota dela na tabela.
FONTE_DO_62: Final = "02 §6.2 (classe write exige botao)"

#: As fontes que **nao** sao o diagrama de §8.1. E por esta lista que o `do_81`
#: filtra, e nao por uma comparacao com um valor: o Vendedor pagou a licao de
#: um filtro escrito como `a.fonte != FONTE_DO_CONCIERGE`, que contava como
#: sendo do documento **toda** a fonte futura que nao fosse aquela. Um filtro
#: por negacao de um valor nao e um filtro: e uma lista de proibidos com um
#: elemento.
FONTES_FORA_DO_81: Final = (FONTE_DA_PROSA_DO_81, FONTE_DO_CONCIERGE, FONTE_DO_62)

#: A `fonte` da **unica** transicao do §8.1 que o concierge altera: a 35, que
#: passou de incondicional (`send --> [*]`) a condicional. Nao fica com a
#: omissao, pela razao do mecanismo: o `fonte` existe para que cada aresta diga
#: quem a autoriza, e deixa-la a apontar para um diagrama que a desenha sem
#: condicao era usa-lo para mentir na primeira aresta a que ele se aplica com
#: proveito. **Conta para o `LINHAS_DO_81`**: a transicao continua a existir no
#: diagrama, e o que mudou foi a forma e nao a autoria.
FONTE_ALTERADA_PELO_CONCIERGE: Final = "02 §8.1, alterada por ADR-L005"

#: Os **vinte e dois** nos, pela ordem do diagrama e depois pela do concierge.
#:
#: **Doze dos vinte e dois sao reutilizados sem uma linha nova**, e e isso que
#: este ticket existe para provar (ADR-012): o `ingest`, o `stt`, o `guard_in`,
#: o `tools_info`, o `validate`, o `guard_out`, o `send`, os tres `handoff_*` e
#: os dois do concierge vem do `verticais/vendedor/nos.py` tal como estao. **A
#: medida e o KAM-039, nao este ticket** — o que aqui fica e a lista de onde ela
#: se le.
#:
#: **Eram catorze e passaram a doze, e a diferenca e uma correccao medida.** O
#: `ask_repeat` e o `safe_reply` estavam na lista e sairam: eles escrevem
#: **texto de persona** ao cliente, e o do Vendedor diz «so posso ajudar com os
#: produtos, os precos e os pedidos desta loja» — que a transicao 17 fazia sair
#: da Rececionista a toda a intencao `outro`, isto e, no caminho mais comum que
#: ha. Apanhado pela revisao adversarial (`ANALISE-40`, achado 10). O §5.4 poe
#: «Texto de persona e exemplos» na coluna do que e **proprio**, e um numero de
#: reuso que contasse estes dois contava um defeito como merito.
#:
#: Os dez proprios, e **tres deles sao uma correccao ao §5.4, nao uma escolha**:
#:
#: * o `classify`, o `slots_collect`, o `check_availability`, o `book_slot`, o
#:   `cancel_booking` e o `list_services` sao os que o §5.4 poe na coluna
#:   «Especifico da vertical», e sao os que o §8.1 nomeia depois do diagrama;
#: * o **`compose`** esta na coluna «Partilhado (core)» do §5.4 e **nao se
#:   consegue reutilizar tal como esta**: o do Vendedor explica cada aviso por um
#:   `FRASE_DO_AVISO` indexado pelo dominio **dele**, e um `SLOT_TAKEN` levantava
#:   `KeyError`. O que e partilhado e a *estrutura* — blocos por referencia, zero
#:   numeros em prosa —, e o §5.4 diz exactamente isso na linha «Persona /
#:   prompts»: «Estrutura de prompt e *compose* com placeholders» partilhada,
#:   «Texto de persona e exemplos» proprio. Fica registado nas dividas: a tabela
#:   do §5.4 poe o `compose` em «core» sem a ressalva que a linha de personas faz;
#: * o **`ask_repeat`** e o **`safe_reply`** pelo texto de persona, acima;
#: * o **`confirm_gate`** idem. O §8.1 escreve «a mesma logica, `cart_id` <->
#:   `slot_hold_id`», e e a mesma logica — as tres perguntas por `and` — sobre
#:   **outro campo do estado**: o do Vendedor le `cart["cart_id"]` e este le
#:   `slots["hold"]["hold_id"]`. Generalizar o do Vendedor por parametro era
#:   abrir um ficheiro com 1 161 ensaios por cima para poupar quinze linhas, e a
#:   extraccao do que e comum e o **KAM-039**, que mede o reuso.
#:
#: **Nao ha `unknown_reply` e nao e esquecimento:** o diagrama do §8.1 nao o tem,
#: porque nao ha pesquisa de catalogo nesta vertical — nao existe o par
#: `retrieve`/limiar que no Vendedor produz o «nao encontrei». Uma intencao que
#: nao se sirva vai a `safe_reply` pela transicao 17.
#:
#: Lista **fechada**: e por ela que o teste de contrato mede «nenhum no a mais,
#: nenhum a menos».
NOS: Final = (
    "ingest",
    "stt",
    "guard_in",
    "classify",
    "slots_collect",
    "check_availability",
    "cancel_booking",
    "list_services",
    "tools_info",
    "confirm_gate",
    "book_slot",
    "compose",
    "validate",
    "guard_out",
    "ask_repeat",
    "safe_reply",
    "send",
    "handoff_prepare",
    "handoff_wait",
    "handoff_close",
    # ADR-L005: os dois do concierge, reutilizados do KAM-114.
    "draft_prepare",
    "draft_wait",
)

#: Os nos que vem do pacote do Vendedor **sem uma linha nova**. Afirma-se para
#: que o reuso seja uma lista que alguem possa contar, e nao uma frase: ha
#: ensaio a confrontar isto com a tabela de nos do `nos.py` deste pacote.
NOS_REUTILIZADOS: Final = (
    "ingest",
    "stt",
    "guard_in",
    "tools_info",
    "validate",
    "guard_out",
    "send",
    "handoff_prepare",
    "handoff_wait",
    "handoff_close",
    "draft_prepare",
    "draft_wait",
)

#: As nove intencoes de Servicos (§8.2, primeira linha; dicionario §3.36).
#: **Nove intencoes e sete arestas** a sair do `classify` — ver a nota do
#: modulo.
INTENCOES: Final = (
    "marcar",
    "remarcar",
    "cancelar",
    "disponibilidade",
    "servicos_precos",
    "info_loja",
    "confirmar",
    "humano",
    "outro",
)

#: As intencoes que o `slots_collect` serve. **A `disponibilidade` esta aqui e o
#: diagrama nao a encaminha**, e isso e uma lacuna do §8.1 e nao uma escolha
#: nossa: o §8.2 fixa as nove intencoes e o diagrama desenha saida para oito. A
#: derivacao e a unica que o grafo admite — perguntar «quando tem vaga?» precisa
#: de servico e de data antes de se poder consultar a agenda, que e exactamente
#: o que o `slots_collect` recolhe. Fica em `docs/dividas-documentais.md`, numa
#: linha, com o §8.1 como credor.
#:
#: **Nao abre aresta nova.** As tres tomam a transicao 11 com a mesma chave, e
#: duplicar o destino com chave propria dava duas arestas para o mesmo par
#: `(de, para)` — isto e, uma aresta a mais na tabela que o grafo compilado nao
#: pode desmentir, porque o conjunto que o teste compara e o mesmo. E a licao
#: que o KAM-037 escreveu na tabela do Vendedor.
INTENCOES_DE_SLOTS: Final = ("marcar", "remarcar", "disponibilidade")

#: Os quatro slots do §8.2, **pela ordem em que se perguntam**. A ordem e
#: decisao e nao arrumacao: o `servico` decide a duracao e por isso decide que
#: horas existem, pelo que perguntar a hora antes do servico era perguntar sobre
#: uma grelha que ainda nao se conhece.
#:
#: O `profissional` leva `?` no §8.2 — e **opcional**, e o `slots_collect` nunca
#: o pergunta: pergunta-se o que falta para consultar a agenda, e a agenda
#: consulta-se sem ele. Esta na lista porque o estado o guarda quando o cliente
#: o disser por iniciativa propria.
SLOTS: Final = ("servico", "data", "hora", "profissional")

#: Os slots **obrigatorios**, e sao dois conjuntos e nao um — **por intencao**.
#:
#: **Medido, e nao previsto:** com `hora` obrigatoria para as tres intencoes, o
#: `check_availability` so era alcancavel com uma hora exacta, pelo que
#: devolvia sempre **uma** opcao e as «ate 10» do criterio 4 eram inalcancaveis
#: — codigo morto onde o criterio pede uma proposta. E, do lado do cliente,
#: «quando tem vaga?» recebia «a que horas lhe da jeito?», que e a pergunta
#: trocada: quem pergunta pela agenda e porque **nao** sabe a hora.
#:
#: Logo: `marcar` e `remarcar` precisam de hora, porque marcam um instante;
#: `disponibilidade` precisa do servico e do dia, porque pergunta **quais** sao
#: os instantes. O `profissional` nunca entra, pela nota do `SLOTS`.
SLOTS_PARA_MARCAR: Final = ("servico", "data", "hora")
SLOTS_PARA_DISPONIBILIDADE: Final = ("servico", "data")

#: A uniao dos dois, para quem precise de saber o universo. **Nao e o que o
#: `r_slots` consulta** — ele escolhe o conjunto pela intencao.
SLOTS_OBRIGATORIOS: Final = SLOTS_PARA_MARCAR


def obrigatorios_de(intencao: str | None) -> tuple[str, ...]:
    """Os slots que uma intencao exige antes de se consultar a agenda.

    A omissao e o conjunto **maior** (`SLOTS_PARA_MARCAR`), e isso e o lado
    seguro: uma intencao desconhecida nao chega aqui — o `r_intent` manda-a a
    `safe_reply` —, e se chegasse, pedir mais do que o necessario faz uma
    pergunta a mais, enquanto pedir menos consulta a agenda com um campo vazio.
    """
    if intencao == "disponibilidade":
        return SLOTS_PARA_DISPONIBILIDADE
    return SLOTS_PARA_MARCAR

#: A confirmacao antiga ou invalida. **O mesmo valor do Vendedor**, e de
#: proposito: nasce no `confirm_gate`, que e o **mesmo no** nas duas verticais
#: (§8.1: «`confirm_gate` (a mesma logica, `cart_id` <-> `slot_hold_id`)»), e
#: dois valores diferentes para o aviso que um no partilhado escreve era pedir
#: ao no para saber em que vertical esta.
STALE_CONFIRMATION: Final = "STALE_CONFIRMATION"

#: O cancelamento pedido sem o cliente dizer **qual** marcacao. Nao e
#: `NOT_FOUND`, e a distincao e a licao que o KAM-037 pagou (achado C2 da
#: `ANALISE-39`): «nao me disse qual» nao e «nao existe», e confundir os dois
#: dizia «nao encontrei essa marcacao» a quem nunca deu referencia nenhuma. O
#: cliente ouve a pergunta em vez de uma negativa.
#:
#: **O mesmo valor do Vendedor**, pela razao do `STALE_CONFIRMATION`: e o mesmo
#: aviso com o mesmo significado, e nasce num no nosso.
REFERENCIA_EM_FALTA: Final = "REFERENCIA_EM_FALTA"

#: A agenda nao tem vaga no intervalo pedido (criterio 4, segunda metade).
#: Nasce no `check_availability` e nao e um erro da tool: a tool respondeu, e a
#: resposta foi «zero opcoes». Tratar isso como `NOT_FOUND` dizia «esse servico
#: nao existe» a quem perguntou por uma terca-feira cheia.
SEM_DISPONIBILIDADE: Final = "SEM_DISPONIBILIDADE"

#: A agenda nao tem vaga nenhuma no dia pedido — **nem alternativas**. E um
#: aviso proprio e nao o `SEM_DISPONIBILIDADE`, e a distincao foi medida pela
#: revisao adversarial (`ANALISE-40`, achado 14): a frase daquele diz «veja se
#: alguma destas lhe serve» e, com zero opcoes, apontava para uma lista **vazia**
#: — o cliente ouvia «veja estas» e nao via nenhuma. Sao dois estados
#: diferentes («nao a essa hora, mas ha outras» e «nao nesse dia»), e o §6.5
#: manda o `compose` explicar: duas explicacoes diferentes precisam de dois
#: valores.
SEM_VAGA_NENHUMA: Final = "SEM_VAGA_NENHUMA"

#: A hora que o cliente escreveu admite mais do que uma leitura (criterio 3,
#: «as 5»). Nasce no `slots_collect`, e o que ele faz com ela e **perguntar**:
#: o criterio escreve «gera pergunta de desambiguacao, **nunca palpite**».
HORA_AMBIGUA: Final = "HORA_AMBIGUA"

#: O dominio fechado de `state.avisos` nesta vertical (dicionario §3.36).
#:
#: Os cinco primeiros sao erros tipados que o §6.5 manda o `compose` explicar;
#: o `SLOT_TAKEN` e o `HOLD_EXPIRED` sao os dois codigos novos do modulo
#: `servicos` (KAM-047), que a revisao `0026` poe no `CHECK` da
#: `tool_audit.error_code`; os quatro ultimos nascem em nos nossos.
#:
#: **Nao ha `OUT_OF_STOCK` nem `PRICE_CHANGED`**: sao estados de negocio do
#: catalogo e nao da agenda, e uma entrada sem caminho para a produzir e uma
#: frase que ninguem ve. **Nem as tres violacoes** (`ENTITLEMENT_DENIED`,
#: `TOOL_NOT_ALLOWED`, `TENANT_MISMATCH`): o §6.5 manda bloquear e alertar, e
#: explicar ao cliente que o `tenant_id` nao bateu era dizer-lhe que a fronteira
#: existe e onde ela esta.
#:
#: **Fechado** porque o `compose` decide por valor conhecido: um aviso que ele
#: nao conheca nao tem frase, e ha ensaio a exigir uma frase por valor.
AVISOS: Final = (
    "NOT_FOUND",
    "LIMIT_EXCEEDED",
    "VALIDATION_ERROR",
    "UPSTREAM_TIMEOUT",
    "UPSTREAM_DOWN",
    "SLOT_TAKEN",
    "HOLD_EXPIRED",
    STALE_CONFIRMATION,
    REFERENCIA_EM_FALTA,
    SEM_DISPONIBILIDADE,
    SEM_VAGA_NENHUMA,
    HORA_AMBIGUA,
)

#: As perguntas que o `slots_collect` pode fazer, uma por slot em falta.
#:
#: **Dominio fechado, e e isso que torna «uma pergunta por mensagem»
#: estrutural.** O estado guarda **uma** destas em `slots["pergunta"]` — um
#: campo, nao uma lista —, pelo que duas perguntas no mesmo turno nao sao uma
#: regra que alguem tenha de respeitar: nao ha onde as escrever. O criterio 3
#: pede «pergunta **uma** coisa por mensagem», e um campo singular cumpre-o por
#: construcao enquanto uma lista cumpria-o por disciplina.
PERGUNTAS: Final = (
    "PEDIR_SERVICO",
    "PEDIR_DATA",
    "PEDIR_HORA",
    "DESAMBIGUAR_HORA",
)

#: A pergunta que corresponde a cada slot obrigatorio em falta.
PERGUNTA_DO_SLOT: Final = {
    "servico": "PEDIR_SERVICO",
    "data": "PEDIR_DATA",
    "hora": "PEDIR_HORA",
}

#: Os desfechos da transicao 4 — porque e que um turno nao corre. **Os mesmos
#: tres do Vendedor**: a admissao e do `ingest`, que e partilhado.
RECUSAS: Final = ("turno_repetido", "contacto_bloqueado", "ritmo")

#: Os seis veredictos da guarda de entrada (§8.4). **Os mesmos do Vendedor**: o
#: `guard_in` e o mesmo no.
VEREDICTOS_DE_GUARDA: Final = (
    "ok",
    "injection",
    "abuse",
    "out_of_domain",
    "card_data",
    "sensitive",
)

#: O prefixo do botao de confirmacao desta vertical.
#:
#: **`hold_id` e nao `cart_id`, e e uma normalizacao com decisao escrita.** O
#: `docs/tecnica/02` §6.2 escreve `confirm:{cart_id}` na tabela de tools e o
#: §8.2 escreve `confirm:{hold_id}` na linha «Confirmacao»; os *Detalhes
#: Tecnicos* do bloco mandam «normalizar para `hold_id`». O §6.3 do mesmo
#: documento ja escrevia as duas formas lado a lado — «`confirm:{cart_id}`
#: (Vendedor) | `confirm:{hold_id}` (Servicos)» —, pelo que a tabela do §6.2 e
#: que esta em atraso. Entra no dicionario como nome canonico (emenda 1.47) e a
#: linha do §6.2 fica em `docs/dividas-documentais.md`.
#:
#: **Nao se redeclara o prefixo: importa-se.** O `tls/contexto.py` ja o fixa, e a
#: *docstring* do `Confirmation.referencia` ja escreve «o `cart_id` **ou** o
#: `hold_id`» — a normalizacao estava antecipada no codigo partilhado, e o que
#: faltava era o lado da vertical. Uma segunda constante com o mesmo literal era
#: a forma de as duas divergirem no dia em que o prefixo mudasse.
PREFIXO_DE_CONFIRMACAO: Final = _PREFIXO_PARTILHADO

#: O maximo de opcoes de disponibilidade que se propoem (criterio 4).
#:
#: **Dez, CONFIRMADO e nao *proposta*:** e o limite de linhas de uma lista
#: interactiva da Meta (`docs/tecnica/evidencia/E1_Meta_WhatsApp.md` §7), e
#: muda-lo nao e uma calibracao nossa — e mudar o que a Meta aceita. O mesmo
#: valor esta no `MAXIMO_DE_OPCOES` do modulo `servicos` (KAM-047) e no
#: `MAX_BOTOES` do *renderer* (KAM-032); **le-se daqui para este grafo** e ha
#: ensaio a confrontar os tres, porque tres copias de um limite de terceiro
#: divergem no dia em que alguem corrigir uma.
MAXIMO_DE_OPCOES: Final = 10


@dataclass(frozen=True, slots=True)
class Aresta:
    """Uma aresta do grafo, com a linha do diagrama que a autoriza.

    A `chave` e `None` numa aresta directa (`add_edge`) e e a chave do `path_map`
    numa condicional (`add_conditional_edges`). A `condicao` e o rotulo da
    transicao do §8.1, encurtado: esta aqui para que quem le o codigo nao tenha
    de abrir o documento para saber **quando** a aresta e tomada.
    """

    linha: int
    de: str
    para: str
    chave: str | None
    condicao: str
    #: De onde vem a autorizacao desta aresta. Por omissao o diagrama de §8.1,
    #: que e a fonte das trinta e nove.
    fonte: str = "02 §8.1"

    @property
    def condicional(self) -> bool:
        return self.chave is not None


#: As arestas do grafo: as trinta e nove do diagrama de §8.1, as tres da prosa
#: ao lado dele e as quatro do concierge (ADR-L005), pela ordem das transicoes.
#: O `fonte` de cada uma diz quem a autoriza, e e por ele que as tres contagens
#: se provam em separado.
ARESTAS: Final = (
    Aresta(1, START, "ingest", None, "sempre"),
    Aresta(2, "ingest", "stt", "stt", "entrada de audio"),
    Aresta(3, "ingest", "guard_in", "guard_in", "texto ou botao"),
    Aresta(4, "ingest", END, "end", "duplicado ou excesso de ritmo"),
    Aresta(5, "stt", "guard_in", "ok", "confianca alta"),
    Aresta(6, "stt", "ask_repeat", "repeat", "confianca media"),
    Aresta(7, "stt", "handoff_prepare", "human", "confianca baixa"),
    Aresta(8, "guard_in", "classify", "ok", "ok"),
    Aresta(9, "guard_in", "safe_reply", "safe", "nao ok"),
    Aresta(10, "guard_in", "handoff_prepare", "human", "assunto sensivel"),
    # **Uma aresta para tres intencoes**: `marcar`, `remarcar` e, pela lacuna
    # do §8.1 que o `INTENCOES_DE_SLOTS` documenta, `disponibilidade`.
    Aresta(11, "classify", "slots_collect", "slots", "marcar, remarcar ou disponibilidade"),
    Aresta(12, "classify", "cancel_booking", "cancel", "cancelar"),
    Aresta(13, "classify", "confirm_gate", "confirm", "confirmar (botao confirm:*)"),
    Aresta(14, "classify", "list_services", "services", "servicos e precos"),
    Aresta(15, "classify", "tools_info", "info", "horario e morada"),
    Aresta(16, "classify", "handoff_prepare", "human", "pedir humano"),
    Aresta(17, "classify", "safe_reply", "other", "outro"),
    Aresta(18, "slots_collect", "check_availability", "ready", "slots completos"),
    Aresta(19, "slots_collect", "compose", "ask", "falta informacao, pergunta ao cliente"),
    Aresta(
        20,
        "check_availability",
        "compose",
        "ok",
        "propoe ate 10 opcoes ou indisponivel",
    ),
    Aresta(21, "list_services", "compose", None, "sempre"),
    Aresta(22, "tools_info", "compose", None, "sempre"),
    Aresta(23, "cancel_booking", "compose", "ok", "sempre, ou recusa por regra"),
    Aresta(24, "confirm_gate", "book_slot", "go", "confirm id e slot batem"),
    Aresta(25, "confirm_gate", "compose", "stale", "confirmacao antiga"),
    Aresta(26, "book_slot", "compose", "ok", "marcacao feita ou recusada"),
    Aresta(27, "compose", "validate", None, "sempre"),
    Aresta(28, "validate", "guard_out", "ok", "datas horas e precos conferem"),
    Aresta(29, "validate", "compose", "retry", "falha e retries abaixo de 1"),
    Aresta(30, "validate", "handoff_prepare", "human", "falha repetida"),
    Aresta(31, "guard_out", "send", "ok", "ok"),
    Aresta(32, "guard_out", "safe_reply", "safe", "violacao"),
    # **Duas transicoes e nao uma**, ao contrario da linha 34 do §7.3: aqui nao
    # ha `unknown_reply`, pelo que o diagrama escreve `ask_repeat --> send` e
    # `safe_reply --> send` em linhas separadas.
    Aresta(33, "ask_repeat", "send", None, "sempre (texto estatico)"),
    Aresta(34, "safe_reply", "send", None, "sempre (texto estatico)"),
    # **A transicao 35 passou a condicional com o ADR-L005.** O diagrama escreve
    # `send --> [*]`, e e o que ela faz quando a politica `concierge` esta
    # desligada — o caso de todos os *tenants* fora do Piloto concierge.
    Aresta(
        35,
        "send",
        END,
        "enviado",
        "enviado, ou politica concierge desligada",
        fonte=FONTE_ALTERADA_PELO_CONCIERGE,
    ),
    Aresta(36, "handoff_prepare", "handoff_wait", "wait", "aberto"),
    Aresta(37, "handoff_prepare", "send", "degraded", "HND indisponivel"),
    Aresta(38, "handoff_wait", "handoff_close", None, "retoma"),
    Aresta(39, "handoff_close", END, None, "sempre"),
    # ------------------------------------- §8.1, prosa: as tres do `UPSTREAM_*`
    #
    # «Omitido do diagrama por legibilidade; a tabela de arestas segue a mesma
    # regra `UPSTREAM_*`» — o paragrafo depois do diagrama. Sao as linhas 22 e
    # 26 do §7.3 aplicadas aos tres nos de escrita e leitura da agenda, e o
    # criterio 8 do bloco escreve-as por extenso: «Falhas `UPSTREAM_*` em
    # `check_availability`/`book_slot`/`cancel_booking` vao a `handoff_prepare`».
    #
    # **O `list_services` nao esta aqui, e nao e esquecimento.** Nem a prosa nem
    # o criterio 8 o nomeiam: os tres sao os que tocam a agenda de um recurso, e
    # uma lista de precos que nao chegue explica-se em `compose` como o
    # `tools_info` ja faz no Vendedor. Acrescenta-lo era alargar o criterio.
    Aresta(
        40,
        "check_availability",
        "handoff_prepare",
        "down",
        "UPSTREAM_* apos retry",
        fonte=FONTE_DA_PROSA_DO_81,
    ),
    Aresta(
        41,
        "book_slot",
        "handoff_prepare",
        "down",
        "UPSTREAM_* apos retry",
        fonte=FONTE_DA_PROSA_DO_81,
    ),
    Aresta(
        42,
        "cancel_booking",
        "handoff_prepare",
        "down",
        "UPSTREAM_* apos retry",
        fonte=FONTE_DA_PROSA_DO_81,
    ),
    # ------------------------------- §6.2, a confirmacao do cancelamento
    #
    # **O diagrama nao desenha portao para o cancelamento, e o §6.2 exige-o.**
    # Aquela tabela poe o `cancel_booking` e o `reschedule_booking` em classe
    # `write` com «botao» na coluna da confirmacao, e o passo 4 do `invoke`
    # recusa uma tool de escrita sem botao. Mas o §8.1 liga o `classify`
    # directamente ao `cancel_booking` e nao ha caminho do botao de volta a ele.
    #
    # **Medido, e nao previsto:** com a tabela como o diagrama a desenha, um
    # «quero cancelar a B-12» chegava ao `cancel_booking`, a tool corria sem
    # botao e devolvia `VALIDATION_ERROR` — o cliente ouvia «nao consegui tratar
    # esse pedido» a um pedido perfeitamente legivel, e **nenhum** cancelamento
    # era possivel nesta vertical.
    #
    # A derivacao e esta aresta: o `cancel_booking` **pergunta** no primeiro
    # turno (e e por isso que ele tem caminho desde o `classify`) e **executa**
    # quando o `confirm_gate` lhe manda o turno do botao. E a mesma forma do
    # fluxo de dois turnos do Vendedor, aplicada a tool que o §6.2 manda
    # confirmar.
    #
    # A lacuna do §8.1 fica em `docs/dividas-documentais.md`, com o §8.1 como
    # credor — como a da `disponibilidade`.
    Aresta(
        43,
        "confirm_gate",
        "cancel_booking",
        "cancel",
        "o botao confirma um cancelamento pendente",
        fonte=FONTE_DO_62,
    ),
    # ---------------------------------------------- ADR-L005, o concierge
    #
    # Quatro arestas e dois nos, reutilizados do KAM-114 sem uma linha nova. O
    # ciclo `send -> draft_prepare -> draft_wait -> send` **e** um ciclo, e e
    # limitado por construcao: a segunda visita ao `send` traz a decisao no
    # estado, pelo que sai pela `enviado`. Sem a decisao nao ha segunda visita —
    # o `draft_wait` esta interrompido. E o que o criterio 1 chama «ciclo com
    # contador»: o contador aqui e a decisao, e nao um numero.
    Aresta(
        44,
        "send",
        "draft_prepare",
        "aprovar",
        "politica concierge ligada e sem decisao humana",
        fonte=FONTE_DO_CONCIERGE,
    ),
    Aresta(
        45,
        "draft_prepare",
        "draft_wait",
        None,
        "sempre; mesmo com o HND em baixo (nada sai sem decisao)",
        fonte=FONTE_DO_CONCIERGE,
    ),
    Aresta(
        46,
        "draft_wait",
        "send",
        "enviar",
        "decisao aprovado ou editado",
        fonte=FONTE_DO_CONCIERGE,
    ),
    Aresta(
        47,
        "draft_wait",
        END,
        "end",
        "decisao rejeitado, expirado ou substituido",
        fonte=FONTE_DO_CONCIERGE,
    ),
)


def do_81() -> tuple["Aresta", ...]:
    """So as arestas que o diagrama de §8.1 desenha. E o universo do `LINHAS_DO_81`.

    O filtro e por **lista de fontes de fora** e nao por negacao de uma — ver o
    `FONTES_FORA_DO_81`.
    """
    return tuple(a for a in ARESTAS if a.fonte not in FONTES_FORA_DO_81)


def do_prosa() -> tuple["Aresta", ...]:
    """So as tres que o paragrafo depois do diagrama autoriza."""
    return tuple(a for a in ARESTAS if a.fonte == FONTE_DA_PROSA_DO_81)


def do_62() -> tuple["Aresta", ...]:
    """So a aresta que a tabela de tools do §6.2 obriga."""
    return tuple(a for a in ARESTAS if a.fonte == FONTE_DO_62)


def do_concierge() -> tuple["Aresta", ...]:
    """So as quatro que o ADR-L005 traz para este grafo."""
    return tuple(a for a in ARESTAS if a.fonte == FONTE_DO_CONCIERGE)


def pares() -> frozenset[tuple[str, str]]:
    """As arestas como pares `(de, para)` — o que se compara com o compilado."""
    return frozenset((a.de, a.para) for a in ARESTAS)


def mapa_de(no: str) -> dict[str, str]:
    """O `path_map` de um no condicional, derivado da tabela.

    **O mapa nao se escreve duas vezes.** Escrito a mao no `grafo.py`, o teste de
    contrato comparava a tabela com um mapa que alguem podia ter divergido dela —
    e passava, porque o conjunto de arestas e o mesmo com dois destinos trocados.
    Derivando-o daqui, a tabela e a unica fonte e a troca deixa de ser possivel.
    """
    saidas = {a.chave: a.para for a in ARESTAS if a.de == no and a.condicional}
    if not saidas:
        raise KeyError(f"{no!r} nao tem arestas condicionais na tabela de §8.1")
    return saidas


def directas() -> tuple[tuple[str, str], ...]:
    """As arestas sem encaminhador, para o `add_edge`."""
    return tuple((a.de, a.para) for a in ARESTAS if not a.condicional)


def condicionais() -> tuple[str, ...]:
    """Os nos com encaminhador, pela ordem da tabela e sem repetir."""
    vistos: list[str] = []
    for aresta in ARESTAS:
        if aresta.condicional and aresta.de not in vistos:
            vistos.append(aresta.de)
    return tuple(vistos)


def pares_do_compilado(compilado: Any) -> frozenset[tuple[str, str]]:
    """As arestas do grafo **compilado**, lidas do LangGraph.

    E o `get_graph()` do `CompiledStateGraph` e nao a nossa tabela: um teste que
    comparasse a tabela consigo mesma nao prova nada sobre o grafo que vai
    correr. E a licao que o criterio 3 do KAM-027 pagou.
    """
    desenho = compilado.get_graph()
    return frozenset((a.source, a.target) for a in desenho.edges)


def nos_do_compilado(compilado: Any) -> frozenset[str]:
    """Os nos do grafo compilado, **sem** os sentinelas do LangGraph.

    O `__start__` e o `__end__` que o `get_graph()` devolve nao sao nos nossos:
    conta-los dava vinte e quatro onde esta tabela fixa vinte e dois.
    """
    return frozenset(compilado.get_graph().nodes) - {START, END}
