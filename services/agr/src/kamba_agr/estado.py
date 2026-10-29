"""O `ConversaState` base e o estado inicial de um turno (`docs/tecnica/02` §5.3).

O bloco do KAM-025 propoe-o em `kamba/core/state.py`; fica em
`services/agr/src/kamba_agr/estado.py` porque o AGR e o unico processo que o
constroi e o unico que o le, e porque `libs/py-core` e o que **todos** os
servicos Python precisam de fazer da mesma maneira (`index.ts` do `core-ts`
diz a mesma regra do lado Node). Quando o KAM-026 puser o `AsyncPostgresSaver` a
persistir isto, continua a ser o AGR a ler e a escrever.

## As chaves sao as do §5.3, e nenhuma e nova

O §5.3 e um bloco de canon citado: as chaves do `ConversaState` sao as dele, com
os mesmos nomes. **Nao se acrescenta nenhuma** — e o §3 do dicionario a valer: um
nome novo entra no dicionario antes de entrar em codigo.

**O `estado_inicial` tem MENOS chaves do que o `ConversaState`, e isso e
desenho.** Tres — o `turn_seq` (KAM-114), o `slots` e o `stage` (KAM-035) — nao
nascem aqui, porque esta funcao corre em **cada** turno e o que ela devolve
sobrescreve o *checkpoint*: uma chave que tenha de atravessar turnos nao pode
estar nesta tabela. A razao de cada uma esta escrita no sitio onde ela saiu.

O que se faz e deixar as sub-estruturas por tipar, como `dict` ou `list`:

| Chave | Quem lhe da forma |
|---|---|
| `stt` | KAM-036 (pipeline de voz) |
| `guard` | KAM-033 (guardrails) |
| `facts` | KAM-028 (ToolLayer) |
| `cart` | KAM-031 (grafo do Vendedor) |
| `slots` | KAM-035 (grafo de Servicos) |
| `draft`, `citation_retries` | KAM-032 (validador de citacao) |
| `handoff`, `handoff_seq` | KAM-034 (handoff em dois nos) |
| `messages`, `summary` | KAM-026 (recorte da janela) |

Tipar aqui qualquer uma delas era decidir por esses tickets, e o bloco deste
diz «nao expandas escopo» pelo nome. O que este ticket entrega e a **chave** com
o nome certo e o valor vazio certo, para que o grafo que vier a seguir nao tenha
de inventar a chave nem o AGR de migrar o estado por causa dela.

## O `schema_version` e o unico campo que este ticket decide

Nasce a `1`. O §5.3 pede-o e o §12 diz o que ele serve: «`ingest` migra estados
antigos». O `ingest` e do KAM-031; o que aqui esta e o numero e a funcao que o
le de um estado que veio da base, para que o dia em que ele subir nao comece com
uma arqueologia. Uma versao **a frente** da que este codigo conhece nao se
migra: levanta, porque degradar um estado futuro e perder o que ele traz.
"""

from __future__ import annotations

from typing import Annotated, Any, Final, TypedDict

from langgraph.graph.message import add_messages

from .contexto import InvocacaoDoAgente

#: A versao do estado que este codigo escreve (`docs/tecnica/02` §5.3).
SCHEMA_VERSION: Final = 1

#: Os valores de `stage` (§5.3). Lista **fechada**: e etiqueta de metrica.
ESTAGIOS: Final = ("browsing", "awaiting_confirm", "awaiting_payment", "done")

#: O `stage` com que um turno comeca.
ESTAGIO_INICIAL: Final = "browsing"

#: Os valores de `input_kind` (§5.3). Nao e o `wa_type` do dicionario §3.12 —
#: sao cinco e os `wa_type` sao doze: e a **classe** de entrada que o grafo
#: distingue, e o mapeamento de um para o outro e do `ingest` (KAM-031).
TIPOS_DE_ENTRADA: Final = ("text", "audio", "interactive", "location", "image")

#: Com que `input_kind` nasce um turno cujo `type` nao casa nenhum dos cinco.
#: O `ingest` do KAM-031 refina; aqui so nao se perde o turno por causa disso.
TIPO_DE_ENTRADA_POR_OMISSAO: Final = "text"


class VersaoDeEstadoAFrenteError(RuntimeError):
    """O estado lido tem `schema_version` maior do que o que este codigo escreve.

    Nao se degrada e nao se ignora. Um estado da versao N+1 traz chaves que
    este codigo nao sabe preservar, e correr um turno sobre ele reescreve-o
    **sem** elas — o que e perder dados de uma conversa a meio. A resposta e
    levantar: o turno nao corre, a mensagem fica na fila, e o alerta diz que ha
    uma replica velha a receber trafego de uma nova (`docs/tecnica/02` §14,
    linha do checkpointer indisponivel).
    """


def estado_inicial(invocacao: InvocacaoDoAgente) -> dict[str, Any]:
    """O estado com que um turno entra no grafo.

    E o `initial_state(ctx)` do esqueleto de codigo do bloco do ticket. Os
    cinco identificadores vem **todos** da invocacao e nenhum do texto: e aqui
    que o «`tenant_id` injectado pelo CHR; imutavel; nunca vem do texto» do
    §5.3 se cumpre, e nao ha outro caminho para dentro do estado.

    `facts` nasce vazio **e e reiniciado em cada turno**, nao acumulado: o §5.3
    di-lo («so deste turno; reiniciado em `ingest`») e a razao e o validador de
    citacao — um *fact* de um turno anterior e um numero sem prova neste. Os
    `ofertas` e `avisos` da emenda 1.40 seguem a mesma regra, e o `reiniciar`
    deste modulo e quem a aplica no `ingest`.
    """
    return {
        "schema_version": SCHEMA_VERSION,
        "tenant_id": invocacao.tenant_id,
        "channel_id": invocacao.channel_id,
        "contact_id": invocacao.contact_id,
        "conversation_id": invocacao.conversation_id,
        "vertical": invocacao.vertical,
        "turn_id": invocacao.turn_id,
        "thread_id": invocacao.thread_id,
        "input_kind": tipo_de_entrada(invocacao.type),
        "messages": [],
        "summary": None,
        "stt": None,
        "guard": None,
        "intent": None,
        "admissao": None,
        "facts": [],
        # Os tres da emenda 1.40, e os tres sao **do turno**, como os `facts`:
        # uma oferta de um turno anterior e uma designacao sem prova neste, e um
        # aviso de um turno anterior e uma explicacao que ja se deu.
        "ofertas": [],
        "avisos": [],
        "handoff_motivo": None,
        "cart": None,
        # KAM-035. **O `stage` sai desta tabela, pela mesma razao dos `slots` — e
        # sem ele nenhum fluxo de dois turnos funciona em vertical nenhuma.**
        #
        # O `confirm_gate` (as duas verticais) pergunta
        # `estado.get("stage") == "awaiting_confirm"`, e o botao de confirmacao
        # chega **sempre** no turno seguinte — foi enviado no fim do anterior.
        # Com `stage: ESTAGIO_INICIAL` nesta tabela, o turno do botao nascia em
        # `browsing`, a primeira das tres perguntas do portao era sempre falsa, e
        # **toda** a confirmacao saia `STALE_CONFIRMATION`: zero marcacoes e zero
        # encomendas, em vez de uma.
        #
        # **Medido pela revisao adversarial** (`ANALISE-40`, achado 3): dois
        # turnos sobre o mesmo `thread_id` dao `stage='awaiting_confirm'` no
        # *checkpoint* e `browsing` a entrada do turno seguinte. A bateria nao o
        # via porque os ensaios de no poem o `stage` a mao.
        #
        # **Toca no Vendedor e e tecnicamente necessario**: o `confirm_gate` e a
        # mesma logica nas duas (§8.1), o defeito e o mesmo, e deixar metade
        # corrigida era deixar a vertical que fundiu primeiro sem fluxo de dois
        # turnos. Corre a suite inteira, e esta registado no relatorio.
        #
        # A ausencia no primeiro turno e tratada: todos os leitores fazem
        # `estado.get("stage")` e o `ESTAGIO_INICIAL` continua a ser o valor que
        # o `ingest` escreve — ver o `reiniciar`.
        # KAM-035. **Os `slots` saem desta tabela, e e o que torna o criterio 3
        # possivel.** O §8.2 pede slots «preenchidos ao longo de varios turnos»,
        # e esta funcao e chamada em **cada** turno pelo `turno.py` (linha 352),
        # cujo resultado vai ao `ainvoke`: toda a chave que nasca aqui
        # sobrescreve a do *checkpoint*. Com `slots: None` nesta tabela, o
        # servico que o cliente deu no turno 1 desaparecia no turno 2 e o
        # `slots_collect` voltava a perguntar a mesma coisa para sempre.
        #
        # **Medido, nao deduzido** (`docs/analises/ANALISE-40-grafo-de-servicos.md`,
        # secção da sonda): dois turnos sobre o mesmo `thread_id`, com um
        # `MemorySaver`, dao `slots=None` no segundo quando a chave vem no input
        # e dao o valor do *checkpoint* quando nao vem. E a mesma medicao que o
        # KAM-114 fez para o `turn_seq`, e a razao por extenso esta na nota dele
        # mais abaixo.
        #
        # O `total=False` do `ConversaState` trata a ausencia no primeiro turno,
        # e quem le faz `estado.get("slots") or {}` — nunca `estado["slots"]`.
        "draft": None,
        "citation_retries": 0,
        "handoff_seq": 0,
        "handoff": None,
        # KAM-037. **Entra aqui**, como o `concierge` e ao contrario do
        # `turn_seq`: e do turno, e e esta reposicao que faz o modo degradado de
        # um turno nao valer no seguinte (criterio 7).
        "degradado": None,
        # KAM-114. **O `concierge` entra aqui e o `turn_seq` NÃO**, e a
        # assimetria e o remedio de um defeito medido.
        #
        # O `turno.py` chama `estado_inicial` em **cada** turno e passa o
        # resultado ao `ainvoke` (linha 315), pelo que **toda** a chave que
        # nasca aqui sobrescreve a do *checkpoint*. Com o `turn_seq` nesta
        # tabela, ele valia 0 a entrada de cada turno, o `ingest` punha-o a 1
        # **sempre**, e o `draft_id = sha256(thread_id:turn_seq)` era o **mesmo**
        # em todos os turnos da conversa: o rascunho do 2.o turno era engolido
        # pelo `ON CONFLICT (draft_id) DO NOTHING`, o operador nunca o via, e a
        # conversa ficava **muda** a partir do segundo turno. Medido contra o
        # grafo real, e e exactamente o defeito que a nota do campo diz que ele
        # existe para evitar — so que quem o limpava nao era o `reiniciar`, era
        # esta funcao.
        #
        # Fora daqui, a chave **nao vem no input** e o canal do LangGraph guarda
        # o valor do *checkpoint*; o `ingest` le-o e sobe-o. O `total=False` do
        # `ConversaState` e o `estado.get("turn_seq") or 0` do `ingest` tratam a
        # ausencia no primeiro turno.
        #
        # O `concierge` fica, e o reinicio por turno e **a propriedade que
        # importa**: sem ele, a `decisao` de um turno sobrevivia ao turno
        # seguinte, o `send` lia-a como aprovacao e a mensagem saia **sem
        # ninguem a ter aprovado** — a barreira do criterio 1 furada no caminho
        # mais comum que ha, o da conversa com mais de um turno.
        "concierge": None,
    }


def tipo_de_entrada(wa_type: str) -> str:
    """A classe de entrada de um `wa_type` (§3.12 -> §5.3).

    Mapeamento **minimo**: os `wa_type` cujo nome e o proprio `input_kind`
    passam, e o resto cai em `text`. Nao se escreve aqui a tabela dos doze
    valores — isso e `ingest` (KAM-031), que tem o corpo da mensagem para
    decidir; o que aqui esta e o que impede o estado de nascer com um
    `input_kind` que nao esta nos cinco.
    """
    return wa_type if wa_type in TIPOS_DE_ENTRADA else TIPO_DE_ENTRADA_POR_OMISSAO


def versao_lida(estado: dict[str, Any]) -> int:
    """A `schema_version` de um estado que veio da base.

    Um estado sem a chave conta como `1`: e o que os *threads* escritos antes de
    o campo existir sao, e tratar a ausencia como «desconhecido» obrigava a
    migrar o que nao mudou. Um valor que nao seja inteiro **e** desconhecido, e
    levanta — porque um `schema_version` de texto e um estado que alguem
    escreveu a mao.
    """
    valor = estado.get("schema_version", 1)
    if not isinstance(valor, int) or isinstance(valor, bool) or valor < 1:
        raise VersaoDeEstadoAFrenteError("schema_version_invalida")
    if valor > SCHEMA_VERSION:
        raise VersaoDeEstadoAFrenteError("schema_version_a_frente")
    return valor


def recortar_janela(estado: dict[str, Any], maximo: int) -> dict[str, Any]:
    """Deixa no estado as ultimas `maximo` mensagens, e mais nada muda.

    E o «estado minimo» do `docs/tecnica/02` §12: «janela de mensagens recortada
    (ultimas K, K a calibrar) + `summary`». O `maximo` vem de quem chama — o
    `JANELA_MAXIMA` do `checkpointer.py` — e nao esta aqui para que a constante
    tenha **um** dono.

    **Quem chama isto e o `ingest` (KAM-031), e e por isso que o checkpointer
    nao o faz.** Recortar na gravacao punha o estado em memoria do grafo a
    divergir do que esta na base sem erro nenhum: a leitura seguinte devolvia
    menos mensagens do que a execucao escreveu. O `aput` **levanta** em vez de
    recortar, e esta funcao e a que faz o estado caber antes de la chegar.

    Devolve um `dict` novo: o estado do LangGraph passa por redutores que
    comparam identidade, e mutar a lista no sitio escondia a alteracao de quem
    guardasse a referencia anterior.
    """
    if maximo < 0:
        raise ValueError("a janela nao pode ser negativa")
    mensagens = estado.get("messages")
    if not isinstance(mensagens, list) or len(mensagens) <= maximo:
        return estado
    # As **ultimas**, nao as primeiras: o que uma conversa perde primeiro e o
    # principio, que o `summary` ja resume. `maximo` zero e lista vazia, e nao
    # a lista inteira — que e o que um `[-0:]` daria.
    return dict(estado, messages=mensagens[len(mensagens) - maximo :])


#: As chaves que o `reiniciar` limpa no `ingest`, e o valor com que cada uma
#: nasce. O §5.3 manda-o para os `facts` («so deste turno; reiniciado em
#: `ingest`») e a emenda 1.40 estende-o aos outros tres pela mesma razao.
#:
#: O `citation_retries` entra aqui e nao e obvio: sem o reiniciar, uma resposta
#: que falhasse a citacao num turno gastava a unica repeticao do turno seguinte,
#: e o tecto de §7.3 linha 30 deixava de valer por turno — passava a valer por
#: *thread*. Medido no ensaio `test_o_tecto_de_citacao_e_por_turno`.
CAMPOS_DO_TURNO: Final = {
    "facts": (),
    "ofertas": (),
    "avisos": (),
    "handoff_motivo": None,
    "admissao": None,
    "draft": None,
    "citation_retries": 0,
    # **O `guard`, o `intent` e o `stt` tambem**, e a primeira versao disto
    # esquecia-os. Sao do turno tanto quanto os `facts`: um turno que chegue por
    # nota de voz e saia por `ask_repeat` nao classifica nada, e sem o reinicio
    # o estado continuava a dizer `intent="comprar"` do turno anterior — que e
    # exactamente o que o `_resumo` do *handoff* escreve ao colega. Apanhado
    # pela revisao adversarial (achado 15 da `ANALISE-34`).
    "guard": None,
    "intent": None,
    "stt": None,
    # KAM-037. **E do turno, e isso e metade do criterio 7.** «Ao recuperar o
    # LLM, o proximo turno volta ao modo normal»: com o `degradado` reiniciado
    # aqui, voltar ao modo normal **nao e uma transicao** que alguem tenha de
    # escrever — e a ausencia de estado. Um campo que sobrevivesse ao turno
    # obrigava a um caminho de saida do modo degradado, e um caminho de saida
    # que falhe deixa a conversa degradada para sempre.
    "degradado": None,
}


def reiniciar() -> dict[str, Any]:
    """O que o `ingest` devolve para limpar o que e so do turno anterior.

    Devolve um `dict` novo a cada chamada, e as colecoes sao tuplos: uma
    constante de modulo com uma lista dentro era a mesma lista em todos os
    turnos de todos os *threads*, e o primeiro no que lhe fizesse `append`
    escrevia no estado de outra conversa.
    """
    return dict(CAMPOS_DO_TURNO)


class ConversaState(TypedDict, total=False):
    """O esquema de estado do grafo (`docs/tecnica/02` §5.3).

    **Vive aqui e nao na vertical**, pela «regra de dois» do §5.4: o estado base
    e **partilhado** e so o `cart` (Vendedor) e os `slots` (Servicos) sao
    especificos. Duas copias deste `TypedDict`, uma por vertical, divergiam no
    dia em que uma delas ganhasse um campo.

    `total=False` porque um no devolve **o delta** e nao o estado inteiro: um
    `TypedDict` total obrigava cada retorno a trazer as vinte e sete chaves.

    O unico redutor e o do `messages`, e e o `add_messages` que o §5.3 escreve.
    Os outros campos sao de ultima escrita — que e o que um turno faz com eles.
    """

    schema_version: int
    tenant_id: str
    channel_id: str
    contact_id: str
    conversation_id: str
    vertical: str
    turn_id: str
    thread_id: str
    input_kind: str
    messages: Annotated[list[Any], add_messages]
    summary: str | None
    stt: dict[str, Any] | None
    guard: dict[str, Any] | None
    intent: str | None
    admissao: str | None
    facts: tuple[Any, ...]
    ofertas: tuple[Any, ...]
    avisos: tuple[str, ...]
    handoff_motivo: str | None
    cart: dict[str, Any] | None
    stage: str
    slots: dict[str, Any] | None
    draft: dict[str, Any] | None
    citation_retries: int
    handoff_seq: int
    handoff: dict[str, Any] | None
    #: KAM-114. O ordinal do turno na conversa, e a segunda metade do
    #: `draft_id = sha256(thread_id:turn_seq)`.
    #:
    #: **Persiste entre turnos**, e para isso tem de estar fora de **duas**
    #: tabelas e nao de uma: fora do `CAMPOS_DO_TURNO` (que o `reiniciar`
    #: devolve) e fora do `estado_inicial` (que o `turno.py` passa ao `ainvoke`
    #: em **cada** turno, sobrescrevendo o que o *checkpoint* tinha). A segunda
    #: foi medida e nao deduzida: com a chave no `estado_inicial`, o `turn_seq`
    #: valia 1 em todos os turnos e o `draft_id` era o mesmo em toda a conversa.
    #: A razao por extenso esta no `estado_inicial`.
    #:
    #: Sobe no `ingest`, uma vez por turno. Uma repeticao do *job* que reexecute
    #: o `ingest` recalcula o **mesmo** valor, porque parte do mesmo
    #: *checkpoint*.
    turn_seq: int
    #: KAM-114. O que o concierge sabe sobre o rascunho **deste** turno:
    #: `draft_id`, `estado`, `publicado`, `decisao` e `numero_livre`.
    #:
    #: **Reinicia-se em cada turno**, e ao contrario do `turn_seq` isso e o que
    #: se quer: e o `estado_inicial` que o poe a `None`, e e essa reposicao que
    #: impede a `decisao` de um turno de valer como aprovacao no turno seguinte.
    #: Dentro do turno ela sobrevive ao `interrupt()`, porque a retoma entra por
    #: `Command(resume=...)` e essa **nao** traz estado inicial nenhum — o canal
    #: guarda o que o *checkpoint* tem.
    concierge: dict[str, Any] | None
    #: KAM-037. O motivo por que **este** turno corre em modo deterministico, ou
    #: `None`. A forma e `{"motivo": <um dos cinco de `degradacao.MOTIVOS`>}`.
    #:
    #: **Reinicia-se em cada turno** (`CAMPOS_DO_TURNO` e `estado_inicial`), e e
    #: por isso que a recuperacao do criterio 7 nao precisa de codigo: o turno
    #: seguinte nasce sem ele e o `ingest` volta a perguntar ao detector.
    #:
    #: E um `dict` e nao uma cadeia porque o `r_intent` so precisa de saber **se**
    #: ha degradacao e o no do menu nao precisa do motivo nenhum — mas o
    #: *checkpoint* fica com ele, e e por ai que se sabe, ao ler um turno antigo,
    #: porque e que o cliente recebeu um menu.
    degradado: dict[str, Any] | None
    #: KAM-112. O mapa `token -> valor original` da minimizacao de PII, que e o
    #: que permite a re-identificacao do criterio 6.
    #:
    #: **Persiste entre turnos**, e por isso fica fora de **duas** tabelas, como
    #: o `turn_seq` do KAM-114 e ao contrario do `degradado`: fora do
    #: `CAMPOS_DO_TURNO` (que o `reiniciar` devolve) e fora do `estado_inicial`
    #: (que o `turno.py` passa ao `ainvoke` em **cada** turno, sobrescrevendo o
    #: que o *checkpoint* tinha).
    #:
    #: A razao de ter de atravessar turnos e a janela de mensagens: o
    #: `recortar_janela` leva as mensagens **minimizadas** dos turnos anteriores,
    #: pelo que um `TELEFONE_1` escrito no turno 1 reaparece no *prompt* do turno
    #: 3. Com um mapa por turno, o turno 3 nao sabia o que ele era e a
    #: `reidentificar` **removia-o** — isto e, a resposta ao cliente perdia o
    #: telefone que ele proprio tinha dado. A numeracao estavel vem da mesma
    #: propriedade: o mesmo valor da o mesmo token na conversa inteira.
    #:
    #: **A retencao e a do *checkpointer* e nao uma nossa**, e nenhuma migracao
    #: entra com este ticket: o `adelete_thread` apaga o *thread* e leva o mapa,
    #: e a purga por classe de dados e o KAM-071. E a licao do KAM-160 — «um
    #: terceiro sitio para o mesmo facto seria uma terceira verdade».
    #:
    #: **Nunca sai do AGR** (criterio 6): nao entra em `dat.llm_call_log` (que
    #: nao tem coluna de texto), nao entra em metrica (as duas levam o **tipo**),
    #: nao entra em log nem em evento. O `Mapa.__repr__` mostra contagens por
    #: tipo para que um `f"{mapa}"` num log nao leve valores.
    #:
    #: O `total=False` trata a ausencia no primeiro turno, e quem le faz
    #: `estado.get("pii_map") or {}` — nunca `estado["pii_map"]`.
    pii_map: dict[str, str] | None
