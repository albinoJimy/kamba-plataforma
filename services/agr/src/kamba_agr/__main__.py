"""Arranque do AGR.

Escuta em `127.0.0.1` por omissao. Dentro de um contentor e preciso escutar em
`0.0.0.0` para que a rede do compose chegue ao processo, e e por isso que o
`Dockerfile` define `HOST=0.0.0.0` — mas nunca o faz o codigo por si, para que
correr o servico a mao na maquina de alguem nao abra uma porta na rede local
(`specs/01` §6, principio 7, e o DoD do KAM-001). **No AGR isto vale duas
vezes**, porque as rotas `/internal/*` existem a partir do KAM-025: o criterio 1
pede que nao estejam publicadas fora da rede interna, e a primeira linha dessa
defesa e a porta de escuta.

E o espelho de `services/*/src/server.ts` do lado Python: a regra tem de ser a
mesma nas duas linguagens, ou o `.env` passa a significar coisas diferentes em
servicos diferentes.

Tudo o que este processo escreve sai pelo `kamba_core.logger` (KAM-068,
`docs/logs.md`): `instalar` liga tambem o `logging` da biblioteca padrao — que
e por onde o uvicorn escreve — e as excepcoes por tratar. O uvicorn arranca com
`log_config=None` para **nao** instalar os seus proprios manipuladores, que
escreveriam texto livre ao lado das linhas JSON.

## A ordem do arranque, e porque e esta

O *logger* instala-se primeiro — e so ele, porque `instalar` nao le
configuracao nem abre nada —, e as guardas do ADR-002 correm **imediatamente
depois**, antes de se ler uma variavel de ambiente e antes de abrir uma porta:

1. `egresso.exigir_biblioteca_mit()` — se `langgraph_api` estiver importavel, o
   processo sai com `3` e nao serve um unico pedido. E o criterio 8 do KAM-025.
2. `egresso.exigir_sbom_mit()` — se uma distribuicao da lista de bloqueio
   estiver **instalada**, o mesmo `3`. E a segunda metade do criterio 7 do
   KAM-027, e nao e a mesma pergunta da de cima: o
   `langgraph-checkpoint-postgres` instala `langgraph.checkpoint.postgres`, que
   nenhum nome de `MODULOS_PROIBIDOS` encontraria.
3. `egresso.desligar_telemetria()` — impoe `false`, nao verifica. E o criterio 7
   do KAM-025.

Sai com codigo **3** e nao com `2`: o `2` e o de configuracao invalida, que o
KAM-001 ja usa para a porta, e os dois distinguem-se no painel de arranques. Um
codigo so dizia «nao arrancou» e nada mais.

Depois disso, o arranque pode ser lento e pode falhar: le o segredo da API
interna do cofre (`Secrets.arrancar` aborta sem ele em `prod`) e abre as duas
ligacoes. Uma falha aqui e um `return`, nunca um `uvicorn.run` a meio.
"""

from __future__ import annotations

import os
from collections.abc import Awaitable, Callable
from pathlib import Path
from typing import Any

import uvicorn
from kamba_core import host, port
from kamba_core.logger import instalar
from kamba_core.secrets import AMBIENTES, EnvSecretProvider, Secrets

from . import egresso, eventos as evt, registo
from .admissao import Admissao, Tectos
from .api_interna import SEGREDO_DA_API, rotas
from .app import create_app
from .checkpointer import CheckpointerDoAgr
from .conversa import leitor
from .handoff.autenticacao import verificador
from .concierge.politica import PoliticaDeConcierge
from .concierge.servico import Decisor
from .concierge.substituicao import Substituidor
from .handoff.retoma import Retomador
from .metricas import METRICAS
from .ligacao import (
    ligar_para_checkpoint,
    ligar_para_concierge,
    ligar_para_eventos,
    ligar_para_handoff,
    ligar_para_leitura,
    ligar_para_llm,
    ligar_para_tools,
    ligar_para_tranca,
)
from .meta import DEFAULT_PORT, SERVICE
from .tls import auditoria as tls_auditoria
from .tls.camada import ToolLayer
from .llm import aliases as llm_aliases
from .llm import destinos as llm_destinos
from .llm import precos as llm_precos
from .llm import registo as llm_registo
from .llm.cliente import ClienteDeLlm, PROXY_POR_OMISSAO, REF_CHAVE_VIRTUAL, VARIAVEL_DO_PROXY
from .tls.catalogo import catalogo_do_piloto
from .trancas import TrancaDeConversas
from .turno import ExecutorDeTurnos, sem_grafos

#: A referencia do `secret` do *agent bot* no cofre (KAM-034, criterio 4).
#:
#: `instancias: conta` em `ops/secrets-inventory.yaml`, pelo que o nome leva a
#: instancia: `chatwoot_bot_secret/<tenant_id>`. A forma e a da
#: `litellm_virtual_key` do KAM-030, e nao a do `agr_internal_token` — que tem
#: `instancias: nenhuma` e e um valor so para o servico.
REF_SEGREDO_DO_BOT = "chatwoot_bot_secret"

#: Codigo de saida de uma guarda do ADR-002 violada. Distinto do `2` do KAM-001
#: (configuracao invalida), para que os dois se distingam num painel.
SAIDA_GUARDA_ADR002 = 3

#: Codigo de saida sem checkpointer (KAM-026, criterio 3).
#:
#: Proprio e nao o `2` da configuracao invalida, pela mesma razao que o `3` do
#: ADR-002: num painel, «o AGR nao arranca» sem dizer porque nao se diagnostica.
#: E o que distingue «falta a palavra-passe do `kamba_agr`» de «falta a porta».
SAIDA_SEM_CHECKPOINTER = 4

#: Codigo de saida com registo de verticais invalido (KAM-027, criterio 1).
#:
#: O quarto, pela mesma razao escrita acima: `2` configuracao, `3` guarda do
#: ADR-002, `4` sem checkpointer, `5` registo invalido. Sao as quatro maneiras
#: de este processo se recusar a arrancar, e cada uma manda olhar para um sitio
#: diferente — o `.env`, a imagem, o cofre da base, e `registry/`.
SAIDA_REGISTO_INVALIDO = 5

#: Codigo de saida sem auditoria de tools (KAM-028, critero 5).
#:
#: O quinto, pela mesma razao escrita acima: `2` configuracao, `3` guarda do
#: ADR-002, `4` sem checkpointer, `5` registo invalido, `6` sem auditoria. Um
#: AGR que arrancasse sem poder escrever `tool_audit` corria tools `money` sem
#: registo, que e o oposto do ADR-015 — e descobria-o no passo 7, **depois** de
#: o efeito ter acontecido.
SAIDA_SEM_AUDITORIA = 6

#: Codigo de saida sem gateway de LLM utilizavel (KAM-030).
#:
#: O **setimo**, pela mesma razao escrita acima: `2` configuracao, `3` guarda do
#: ADR-002, `4` sem checkpointer, `5` registo invalido, `6` sem auditoria de
#: tools, `7` sem gateway de LLM. Cada um manda olhar para um sitio diferente, e
#: este manda olhar para `llm/`.
#:
#: Cobre tres coisas, e as tres sao configuracao:
#:
#: * `llm/aliases.yaml` ou `llm/precos.yaml` que nao se leem;
#: * um alias com um fornecedor fora do inventario de subprocessadores — um
#:   destino de transferencia que ninguem registou (ADR-008);
#: * o papel desta ligacao sem `INSERT` nas catorze colunas de
#:   `dat.llm_call_log`.
#:
#: A guarda e a mesma ideia da do checkpointer e da da `tool_audit`, e pela mesma
#: razao: uma chamada a um modelo que corresse **sem** poder escrever a linha de
#: custo e de transferencia descobria-o depois de os dados terem saido de Angola.
#: O ADR-008 e o ADR-018 nao admitem isso, e um processo que aceita pedidos e so
#: depois descobre que nao registra perde a primeira chamada de cada reinicio em
#: silencio.
SAIDA_SEM_GATEWAY_LLM = 7

#: Codigo de saida com subscricoes por registar (KAM-038, criterio 1).
#:
#: O **oitavo**, pela mesma razao escrita acima: `2` configuracao, `3` guarda do
#: ADR-002, `4` sem checkpointer, `5` registo invalido, `6` sem auditoria de
#: tools, `7` sem gateway de LLM, `8` sem consumidores. Cada um manda olhar para
#: um sitio diferente, e este manda olhar para as `subscriptions` de
#: `registry/*.yaml`.
#:
#: Cobre as duas metades do criterio 1, que nao sao a mesma pergunta: um
#: `{tipo, versao}` **sem contrato publicado** (a validacao (4) do §5.2, que e a
#: do KAM-027 e nao uma segunda), e um tipo subscrito **sem handler** no AGR —
#: que seria um consumidor registado a marcar o evento como consumido sem
#: notificar ninguem.
SAIDA_SEM_CONSUMIDORES = 8

#: A variavel que diz o ambiente do cofre. A mesma do `entrada.ts` e do
#: `chaves.ts`; `dev` por omissao, e um valor fora dos tres **levanta** em vez
#: de cair em `dev` — um `KAMBA_ENV=producao` a servir segredos de `dev` e o
#: defeito que o `chaves.ts` do KAM-008 ja escreveu por extenso.
VARIAVEL_DE_AMBIENTE = "KAMBA_ENV"


def _ambiente(ambiente: dict[str, str] | None = None) -> str:
    valor = (ambiente if ambiente is not None else os.environ).get(
        VARIAVEL_DE_AMBIENTE, "dev"
    )
    if valor not in AMBIENTES:
        raise ValueError(f"{VARIAVEL_DE_AMBIENTE} fora de {AMBIENTES}")
    return valor


def _fechar_as_tomadas(
    trancas: Any,
    checkpointer: Any,
    tools: Any = None,
    retomador: Any = None,
    conversas_de_eventos: Any = None,
) -> Callable[[], Awaitable[None]]:
    """O que o `lifespan` corre no `SIGTERM`: fecha-as, pela ordem.

    O checkpointer depois das trancas: um turno a meio larga a tranca e **ja
    gravou** o que tinha a gravar, pelo que fechar a gravacao primeiro era
    tirar a tomada a quem ainda pode precisar dela.

    **Devolve uma corrotina, e isso nao e detalhe.** O `create_app` declara
    `ao_encerrar: Callable[[], Awaitable[None]]` e faz `await ao_encerrar()`, e
    o `TrancaDeConversas.fechar` e `async def`. A primeira versao desta funcao
    devolvia uma funcao sincrona que chamava o `fechar()` sem `await`: o
    `lifespan` emitia `lifespan.shutdown.failed`, a corrotina ficava por
    esperar, e a ligacao da tranca **nao fechava** — que e exactamente o modo
    de falha que esta funcao existe para evitar. Achado da revisao adversarial,
    e o `TestEncerramento` de `test_arranque.py` passou a liga-lo ao
    `create_app` real.
    """

    async def fechar() -> None:
        await trancas.fechar()
        # As tomadas da ToolLayer **antes** do checkpointer e depois das
        # trancas, pela mesma razao da ordem que ja estava: um turno a meio
        # larga a tranca, acaba as invocacoes que tinha em curso, e so depois
        # grava. A primeira versao do KAM-028 nao as fechava — eram as unicas
        # tomadas do processo que ficavam ao servidor para limpar. Apanhado pela
        # revisao adversarial.
        if tools is not None:
            await tools.fechar()
        # A tomada da retoma (KAM-034) fecha aqui e nao antes das trancas: uma
        # retoma a meio ainda tem de poder compensar o CAS se o grafo levantar,
        # e fechar-lhe a ligacao primeiro era deixar a passagem em `resumed` com
        # o grafo interrompido — o residuo que o `ReversaoFalhadaError` nomeia.
        if retomador is not None:
            await retomador.fechar()
        # A tomada da leitura de conversas do consumidor (KAM-038). As outras
        # duas que ele usa — a do consumo e a da DLQ — abrem e fecham por
        # entrega, pela razao escrita no `ligacao.py`; esta fica, como a da
        # leitura da palavra, e por isso e a unica que precisa de ser fechada
        # aqui. Sem isto, era a unica tomada do processo que ficava ao servidor
        # para limpar.
        if conversas_de_eventos is not None:
            await conversas_de_eventos.fechar()
        # **O gateway de LLM nao tem tomada para fechar**, e isso e o desenho
        # que a revisao adversarial obrigou: ele abre uma ligacao por chamada e
        # fecha-a no `finally`, porque o `tenant_guard.tx` e exclusivo por
        # ligacao e os turnos correm em paralelo. Uma tomada por processo perdia
        # a linha de `dat.llm_call_log` da segunda chamada concorrente.
        checkpointer.fechar()

    return fechar


def main() -> int:
    # O *logger* primeiro, e as guardas do ADR-002 **imediatamente** depois.
    #
    # A primeira versao fazia o contrario, com um `print` para o caso de a
    # guarda morder, e a razao escrita era que «uma guarda que so corresse
    # depois de haver registo era uma guarda que depende de o registo
    # arrancar». O *gate* 2 recusou o `print` (`log_policy lint`,
    # `print_directo`) e tinha razao em dois sentidos: o `instalar` nao le
    # configuracao nenhuma nem abre nada, e nao pode falhar por `langgraph_api`
    # estar importavel — logo a dependencia que a frase invocava nao existe —, e
    # uma recusa sem linha de registo e uma recusa que nao se audita. O que
    # importa e que as guardas correm **antes** de se ler uma variavel de
    # ambiente e antes de abrir uma porta, e isso mantem-se (ha um teste).
    log = instalar(SERVICE)
    try:
        egresso.exigir_biblioteca_mit()
        egresso.exigir_sbom_mit()
    except egresso.ModuloProibidoError as exc:
        # O nome do modulo e constante deste codigo e cabe em `error_code`; a
        # mensagem nao tem conteudo de ninguem.
        log.excepcao(exc, "biblioteca_proibida")
        return SAIDA_GUARDA_ADR002
    telemetria = egresso.desligar_telemetria()

    if telemetria:
        # So o **nome** da variavel, nunca o valor que lá estava: um
        # `LANGSMITH_TRACING` pode trazer uma chave colada por engano. O campo
        # `error_code` e o que a *allowlist* do `docs/tecnica/08` §7.3 tem para
        # um identificador deste tipo.
        for variavel in sorted(telemetria):
            log.info(outcome="telemetria_desligada", error_code=variavel.lower())

    try:
        listen_host, listen_port = host(), port(DEFAULT_PORT)
        tectos = Tectos.do_ambiente()
        ambiente = _ambiente()
    except ValueError as exc:
        # So o codigo e a classe. A mensagem de `port()` repete o valor de
        # `PORT`, e um valor de ambiente errado pode ser qualquer coisa.
        log.excepcao(exc, "arranque_invalido")
        return 2

    # **O registo das verticais valida-se aqui, e invalido falha o deploy**
    # (KAM-027, criterio 1; `docs/tecnica/02` §5.2). E a primeira coisa depois
    # da configuracao porque e a mais barata — le ficheiros do disco, nao abre
    # tomada nenhuma — e porque nao ha nada a ganhar em descobrir um
    # `registry/vendedor.yaml` errado **depois** de abrir tres ligacoes.
    #
    # Os caminhos sao relativos ao directorio de trabalho, que no contentor e
    # `/app`: e por isso que o `Dockerfile` passou a ter um `COPY registry`.
    #
    # A raiz contra a qual se resolve um *dataset* golden e a **pasta acima do
    # registo**, e nao o directorio de trabalho: assim um `KAMBA_REGISTRY_DIR`
    # absoluto move as duas coisas juntas. Duas raizes independentes eram um
    # registo lido de um sitio e um golden procurado noutro.
    #
    # **O catalogo da ToolLayer entra aqui, e e isso que fecha a validacao (1)**
    # (KAM-028). O `registry/gates.yaml` ja nao tem a linha `tools: { modo:
    # aviso }`: a validacao corre em `bloqueio`, confronta as onze tools que as
    # duas verticais declaram contra este catalogo, e recusa o arranque se
    # alguma nao existir ou se alguma expuser `tenant_id`, `merchant_id`,
    # `seller` ou `account` no esquema que o modelo ve.
    #
    # E a **mesma** instancia que a camada usa, mais abaixo. Duas instancias
    # eram duas listas de tools a poder divergir, com a validacao a conferir uma
    # e o `invoke` a executar a outra.
    pasta = registo.directorio_do_registo()
    catalogo = catalogo_do_piloto()
    ambiente_do_registo = registo.AmbienteDoRegisto.do_repositorio(
        pasta.parent, catalogo=catalogo
    )
    try:
        verticais, _, adiadas = registo.carregar(ambiente_do_registo, pasta)
    except (registo.RegistoInvalidoError, registo.FicheiroIlegivelError) as exc:
        log.excepcao(exc, "registo_invalido")
        return SAIDA_REGISTO_INVALIDO

    # **Um consumidor por cada `subscriptions`, e o arranque reprova se faltar
    # um** (KAM-038, criterio 1). Duas verificacoes e nao uma, porque nao sao a
    # mesma pergunta: a primeira e a validacao (4) do §5.2 — **a do KAM-027**,
    # partilhada e nao copiada — e prova que o par `{tipo, versao}` tem contrato
    # publicado; a segunda prova que ha **codigo** para ele. Uma subscricao com
    # contrato e sem *handler* era um consumidor registado a marcar o evento
    # como consumido e a nao notificar ninguem.
    #
    # Corre aqui, ao lado do registo, porque e da mesma natureza — le ficheiros
    # e nao abre tomada nenhuma — e porque nao ha nada a ganhar em descobrir uma
    # subscricao sem consumidor **depois** de abrir sete ligacoes.
    try:
        subscricoes = evt.consumidores(verticais, ambiente_do_registo)
        evt.exigir_handlers(tuple((c.vertical, c.tipo) for c in subscricoes))
    except (evt.SubscricoesInvalidasError, evt.SemHandlerError) as exc:
        log.excepcao(exc, "subscricoes_invalidas")
        return SAIDA_SEM_CONSUMIDORES
    log.info(
        outcome="consumidores_de_eventos",
        error_code=f"consumidores_{len(evt.nomes_dos_consumidores(subscricoes))}"
        f"_subscricoes_{len(subscricoes)}",
    )

    # As validacoes em modo `aviso` — as que esperam por KAM-031, KAM-035 e
    # KAM-040 (`registry/gates.yaml`). A do KAM-028 saiu: o catalogo existe. Um `aviso` que nao aparece no
    # registo de arranque e uma validacao adiada em silencio, que e o que o
    # critero 8 existe para fechar.
    #
    # Uma linha por par (validacao, credor) e nao por vertical: o `error_code`
    # e a `Adiada.codigo()`, que e o identificador que a *allowlist* de
    # `docs/tecnica/08` §7.3 aceita. A prosa do problema **nao** cabe ali — foi
    # a primeira versao disto e a *allowlist* deixava-a cair em silencio.
    for codigo in sorted({adiada.codigo() for adiada in adiadas}):
        log.warn(outcome="registo_validacao_adiada", error_code=codigo)

    try:
        segredos = Secrets.arrancar(
            servico=SERVICE,
            provider=EnvSecretProvider(ambiente),
            obrigatorios=[SEGREDO_DA_API],
        )
    except Exception as exc:  # noqa: BLE001 — qualquer falha de cofre aborta
        log.excepcao(exc, "cofre_indisponivel")
        return 2

    # **Sem checkpointer durável o AGR nao arranca** (KAM-026, criterio 3; o
    # `docs/tecnica/02` §11 regra 6 di-lo por extenso: «sem checkpointer
    # duravel o `interrupt()` perde-se»). A guarda e abrir a ligacao **aqui**,
    # no arranque, e nao a primeira vez que um turno precisar dela: um processo
    # que aceita pedidos e so depois descobre que nao consegue gravar estado
    # perde o primeiro handoff de cada reinicio, e perde-o em silencio.
    #
    # Abrir a ligacao prova as duas metades que importam — a palavra-passe do
    # `kamba_agr` existe, e o servidor responde. Nao prova que o esquema `lg`
    # esta na revisao certa: isso e do `gate` 8, e por-lo aqui era o servico a
    # correr migracoes, que a `0020` recusa pelo nome.
    try:
        checkpointer = CheckpointerDoAgr(ligar_para_checkpoint(), metricas=METRICAS)
    except Exception as exc:  # noqa: BLE001 — qualquer falha aborta o arranque
        log.excepcao(exc, "checkpointer_indisponivel")
        return SAIDA_SEM_CHECKPOINTER

    # **Sem auditoria de tools o AGR nao arranca** (KAM-028, critero 5). A
    # guarda e a mesma ideia da do checkpointer, pela mesma razao: o passo 7 do
    # `docs/tecnica/02` §6.1 corre **depois** da chamada ao backend, pelo que um
    # privilegio em falta so se descobre com um efeito de `money` ja feito e sem
    # registo. Confirma-se no arranque e **nao se escreve nada** — a tabela e
    # *append-only* e uma linha de ensaio ficava la a contar como invocacao numa
    # tabela cuja cobertura e critero de aceitacao.
    try:
        ligacao_das_tools = ligar_para_tools()
        tls_auditoria.confirmar(ligacao_das_tools)
        ligacao_das_tools.close()
    except Exception as exc:  # noqa: BLE001 — qualquer falha aborta o arranque
        log.excepcao(exc, "auditoria_de_tools_indisponivel")
        return SAIDA_SEM_AUDITORIA

    # A camada constroi-se **aqui** e nao no grafo, por duas razoes.
    #
    # Os tectos do §6.5 e os numeros do disjuntor lem-se do ambiente ao
    # construir, e levantam num valor que nao serve: construida no arranque, um
    # `KAMBA_TLS_TIMEOUT_READ_MS=dois` e codigo de saida `2` ao subir, e nao uma
    # excepcao a meio da primeira conversa. E o disjuntor conta falhas
    # **consecutivas por backend**, que e estado do processo: uma instancia por
    # grafo construido dava a cada vertical um contador proprio, e dois
    # contadores a metade do caminho nunca abrem.
    #
    # A tomada abre-se a primeira invocacao e nao agora: a do arranque fechou-se
    # acima, e uma ligacao guardada daqui ate ao primeiro turno e uma ligacao
    # que o servidor pode ter fechado entretanto.
    #
    # **Quem a invoca e o grafo, que e o KAM-031 e o KAM-035**: e esta instancia
    # que o `build_graph(deps)` do §5.2 recebe. Ate la nada a chama — o
    # `/internal/turn` responde 503 — e o que ela faz pelo arranque e o que esta
    # escrito acima.
    tools = ToolLayer(catalogo, abrir_ligacao=ligar_para_tools, metricas=METRICAS)
    # **O `error_code` tem forma, e esta linha nao a tinha.** A *allowlist* do
    # `docs/tecnica/08` §7.3 aceita uma sequencia de palavras com ate tres
    # digitos no fim de cada uma (`http_404`, `sha256`), e
    # `ligadas_1_de_11_read_2000ms` nao casa — o `2000ms` e digitos seguidos de
    # letras. Em modo normal a linha saia **sem** `error_code` e contava
    # `log_field_rejected_total`; com `KAMBA_LOG_ESTRITO=1` levantava
    # `CampoRejeitado` e o `main()` abortava. Apanhado pela revisao adversarial.
    #
    # Os tectos nao vao nesta linha: quem os quer le-os do ambiente, e o que
    # aqui importa e quantas tools respondem.
    log.info(
        outcome="toollayer_pronta",
        error_code=f"ligadas_{len(catalogo.ligadas())}_de_{len(catalogo.nomes())}",
    )

    # **Sem gateway de LLM utilizavel o AGR nao arranca** (KAM-030). Tres
    # verificacoes, pela ordem em que custam: os dois ficheiros de `llm/`, que
    # nao tocam na rede; e depois a ligacao que escreve `dat.llm_call_log`.
    #
    # A ligacao fica **aberta** e e a do cliente: ao contrario da guarda da
    # `tool_audit`, que abre, confirma e fecha, aqui a tomada e a mesma que vai
    # escrever — a camada de tools abre a sua a cada invocacao e esta e uma por
    # processo, fechada no `ao_encerrar`.
    pasta_do_llm = Path(os.environ.get(llm_aliases.VARIAVEL_DA_PASTA, "llm"))
    try:
        aliases = llm_aliases.ler(pasta_do_llm)
        precos = llm_precos.carregar(pasta_do_llm)
    except (llm_aliases.AliasesIndisponiveis, llm_precos.PrecoInvalido) as exc:
        log.excepcao(exc, "llm_configuracao_invalida")
        return SAIDA_SEM_GATEWAY_LLM
    try:
        llm_precos.sem_expirados(
            precos,
            # Os pares `(fornecedor, modelo)` que os aliases nomeiam. Hoje
            # nenhum tem linha de preco (o modelo e `por_decidir`), pelo que
            # isto nao recusa nada — e e o que se quer: a tabela e um catalogo
            # de candidatos e so o que se vai cobrar tem de estar valido.
            {
                (fornecedor, modelo)
                for alias in aliases.values()
                for fornecedor, modelo in zip(
                    alias.fornecedores, alias.modelos, strict=True
                )
            },
        )
    except llm_precos.PrecoInvalido as exc:
        log.excepcao(exc, "llm_tarifa_expirada")
        return SAIDA_SEM_GATEWAY_LLM
    # A guarda abre, confirma e **fecha**, como a da `tool_audit`: a ligacao de
    # execucao e uma **por chamada** (ver o `_escrever` do `cliente.py`), porque
    # o `tenant_guard.tx` e exclusivo por ligacao e o AGR corre turnos em
    # paralelo. Uma ligacao guardada daqui ate a primeira chamada era tambem uma
    # ligacao que o servidor pode ter fechado entretanto.
    try:
        ligacao_de_ensaio = ligar_para_llm()
        try:
            llm_registo.confirmar(ligacao_de_ensaio)
        finally:
            ligacao_de_ensaio.close()
    except Exception as exc:  # noqa: BLE001 — qualquer falha aborta o arranque
        log.excepcao(exc, "llm_call_log_indisponivel")
        return SAIDA_SEM_GATEWAY_LLM

    destinos = llm_destinos.arrancar(ambiente)
    # **O aviso em `staging` nao e enfeite.** O criterio 8 diz «ate KAM-069
    # existir, so dados sinteticos em `staging`», e nenhum codigo consegue
    # verificar que os dados sao sinteticos. Um aviso por arranque torna a
    # condicao visivel; o silencio lia-se como garantia. Em `prod` a porta nega
    # tudo, e tambem se diz.
    if ambiente == llm_destinos.AMBIENTE_PROD:
        log.warn(outcome="llm_destinos", error_code="nega_tudo_ate_kam069")
    else:
        log.warn(outcome="llm_destinos", error_code="so_dados_sinteticos")
    cliente_de_llm = ClienteDeLlm(
        aliases=aliases,
        tabela_de_precos=precos,
        porta_de_destinos=destinos,
        abrir_ligacao=ligar_para_llm,
        # A chave virtual do tenant vem do cofre, com a instancia no nome
        # (`litellm_virtual_key/<tenant_id>`, `ops/secrets-inventory.yaml`). Nao
        # e obrigatoria no arranque: ela existe por tenant e o arranque nao sabe
        # que tenants ha — o que se confirma aqui e que o **cofre** responde,
        # que o `Secrets.arrancar` acima ja fez.
        chave_virtual=lambda tenant_id: segredos.get(
            f"{REF_CHAVE_VIRTUAL}/{tenant_id}"
        ),
        url_do_proxy=os.environ.get(VARIAVEL_DO_PROXY, PROXY_POR_OMISSAO),
        metricas=METRICAS,
    )
    # **Quem o invoca e o grafo, que e o KAM-031 e o KAM-035**, como a ToolLayer:
    # e esta instancia que o `build_graph(deps)` recebe. Ate la nada o chama.
    log.info(
        outcome="llm_gateway_pronto",
        error_code=f"papeis_{len(cliente_de_llm.papeis())}",
    )

    # O *handoff* (KAM-034). Sao tres pecas e **so uma se constroi aqui**:
    #
    # * o `ServicoDeHandoff` e a porta `hnd` que o `build_graph` recebe, e
    #   constroi-o quem construir o `Dependencias` — isto e, quem ligar a porta
    #   `grafos`. **Nao se constroi aqui**, ao contrario do `cliente_de_llm`:
    #   aquele guarda uma tomada e e preciso fecha-la no encerramento, e este e
    #   um invólucro de tres portas sem estado nenhum. Um objecto construido que
    #   ninguem usa era a classe de defeito que a revisao `0011` nomeia pelo
    #   outro lado — uma coisa criada «para quando for preciso».
    # * o `Retomador` entra em `/internal/resume` e e usado **agora**;
    # * a varredura dos prazos nao se constroi aqui, porque **nao ha
    #   agendador** nesta fase (a mesma linha que o `retencao.py` do KAM-026
    #   escreveu): o corpo da varredura e o `Prazos.varrer`, o credor e o
    #   *scheduler* do EVT, e agendar sem agendador era escrever um que ninguem
    #   pediu.
    admissao = Admissao(tectos=tectos)
    trancas = TrancaDeConversas(ligar_para_tranca)
    # KAM-114. O `Decisor` entra em `/internal/draft-decision` e o
    # `Substituidor` entra no `ExecutorDeTurnos` (criterio 5): os dois sao
    # usados **agora**.
    #
    # A varredura dos rascunhos nao se constroi aqui, pela mesma linha do
    # `Prazos` do KAM-034 e do `retencao.py` do KAM-026: **nao ha agendador**
    # nesta fase, o corpo e o `Varredura.varrer`, e o credor e o *scheduler* do
    # EVT (KAM-071).
    decisor_de_rascunhos = Decisor(
        abrir_ligacao=ligar_para_concierge,
        grafos=_grafo_da_thread,
        metricas=METRICAS,
    )
    substituidor_de_rascunhos = Substituidor(
        abrir_ligacao=ligar_para_concierge,
        decidir_pelo_sistema=decisor_de_rascunhos.decidir_pelo_sistema,
    )
    # **As duas portas que o grafo precisa, e que ninguem lhe pode passar hoje.**
    # A `PoliticaDeConcierge` le-se da base em **cada turno**, sem *cache*, e e
    # isso que faz desactiva-la ter efeito no turno seguinte (criterio 8) em vez
    # de «ate 60 s depois»; o leitor e o do KAM-038, que corre em
    # `tenant_guard.tx` com o *tenant* de quem chama e **falha fechado**.
    #
    # Ficam aqui construidas e **nao ligadas**, porque o AGR nao constroi
    # `Dependencias` nenhuma nesta fase — o `grafos` e o `sem_grafos` e o
    # `/internal/turn` responde 503 ate o AgentRegistry existir (KAM-027). A
    # primeira versao deixava a politica numa variavel sem segundo uso, o que
    # era pior do que isto: nao dizia a ninguem o que falta ligar. **Quem ligar
    # o AgentRegistry passa estas duas ao `build_graph`**, como
    # `Dependencias(concierge=..., rascunho=...)` — e sem elas a
    # `Dependencias.concierge` fica `SemPolitica()`, o concierge nunca liga, e
    # ninguem o nota.
    portas_do_concierge = {
        "concierge": PoliticaDeConcierge(
            evt.LeitorDeEntitlements(ligar_para_eventos).ler
        ),
        # O provedor do HND e o KAM-019; ate la a porta por omissao levanta
        # `RascunhoIndisponivel`, que e a linha que o `docs/tecnica/01` §11.5
        # escreve para «Chatwoot indisponivel».
        "rascunho": None,
    }
    log.info(
        outcome="concierge_por_ligar",
        error_code=",".join(sorted(portas_do_concierge)),
    )
    retomador = Retomador(
        abrir_ligacao=ligar_para_handoff,
        # **A porta tem outra forma, e isso e a parte que importa.** O
        # `grafos` do executor recebe uma `InvocacaoDoAgente`; este recebe um
        # `thread_id`, porque a retoma **nao tem invocacao** — o corpo de
        # `/internal/resume` sao tres campos e nenhum e o `agent_invocation`
        # (§3.13). A vertical de uma *thread* que espera por um humano e a do
        # grafo que a interrompeu, e quem a sabe e o *checkpoint*.
        #
        # Hoje as duas acabam no mesmo `sem_grafos`, que levanta de qualquer
        # maneira; o adaptador existe para que quem ligar o AgentRegistry veja
        # que sao **duas** resolucoes a ligar e nao uma. Enquanto levantar, a
        # rota responde 503 com `Retry-After` **sem escrever nada** — o grafo
        # resolve-se antes do CAS (ver `handoff/retoma.py`).
        grafos=_grafo_da_thread,
        metricas=METRICAS,
    )
    # O consumidor de eventos (KAM-038). As portas que ainda nao existem ficam
    # por omissao e **nenhuma delas finge**: o Outbound devolve `sem_template`
    # (nao ha catalogo de templates aprovados, KAM-024), o HND nao faz nada
    # (KAM-019), e a resolucao do contacto a partir do agregado **levanta**
    # (KAM-041 e KAM-047) — pelo que um `payment.confirmed` esgota a escada e
    # abre entrada na DLQ, que e Sev1 e esta certo: sem contacto, e cliente que
    # pagou sem confirmacao.
    #
    # **O leitor de entitlements nao tem omissao**, e por isso constroi-se
    # aqui: e ele que decide **qual** das verticais consome o evento deste
    # *tenant*, e sem ele as duas consumiam os mesmos dois eventos de pagamento
    # — duas mensagens ao mesmo cliente sobre o mesmo pagamento.
    # **Sem subscricoes nao se liga a rota**, e nesse caso `/internal/event`
    # responde 503 com `Retry-After` — «o evento nao se consome agora e fica na
    # fila». Um consumidor sem consumidores devolvia 200 «tratado» sem escrever
    # linha nenhuma, e o evento desaparecia em silencio. Achado da revisao
    # adversarial.
    conversas_de_eventos = evt.LeitorDeConversas(ligar_para_eventos)
    consumidor_de_eventos = None if not subscricoes else evt.ConsumidorDeEventos(
        tabela=subscricoes,
        trancas=trancas,
        conversas=conversas_de_eventos,
        abrir_ligacao=ligar_para_eventos,
        fila_de_mortos=evt.FilaDeMortos(
            ligar_para_eventos,
            metricas=METRICAS,
            aviso=lambda onde, motivo: log.warn(outcome=onde, error_code=motivo),
        ),
        notificador=evt.Notificador(
            metricas=METRICAS,
            aviso=lambda onde, desfecho: log.warn(outcome=onde, error_code=desfecho),
        ),
        ler_entitlement=evt.LeitorDeEntitlements(ligar_para_eventos).ler,
        metricas=METRICAS,
        aviso=lambda onde, desfecho: log.warn(outcome=onde, error_code=desfecho),
    )

    executor = ExecutorDeTurnos(
        trancas=trancas,
        ler_palavra=leitor(ligar_para_leitura),
        # O AgentRegistry e o KAM-027. Ate la, `/internal/turn` com uma
        # invocacao valida responde 503 e a mensagem fica na fila.
        grafos=sem_grafos,
        # O reencaminhamento ao HND e o KAM-019; a porta e esta, e o criterio 6
        # mede a **decisao** de reencaminhar, nao a entrega.
        reencaminhar=_hnd_por_ligar,
        admissao=admissao,
        # KAM-114, criterio 5: o *echo* do dono ou o handoff fecham um rascunho
        # pendente. Esta ligado **agora** — nao depende do AgentRegistry, porque
        # o gatilho esta no `Palavra.do_humano` e nao no grafo.
        substituir_rascunhos=substituidor_de_rascunhos.substituir,
    )
    aplicacao = create_app(
        rotas_internas=rotas(
            credencial=lambda: segredos.get(SEGREDO_DA_API),
            executar=executor.correr,
            admissao=admissao,
            trancas=trancas,
            retomar=retomador.retomar,
            # O `secret` do *agent bot* do HND (KAM-034, criterio 4). E **por
            # *tenant*** — uma conta Chatwoot por PME, logo um bot e um segredo
            # por PME —, e por isso a referencia leva a instancia no nome, como
            # a `litellm_virtual_key` do KAM-030. Nao e obrigatoria no arranque
            # pela mesma razao: ela existe por *tenant* e o arranque nao sabe
            # que *tenants* ha. Uma referencia que nao existe faz o
            # `verificador` recusar com `secret_errado`, que e a falha fechada.
            verificar_bot=verificador(
                lambda tenant_id: segredos.get(f"{REF_SEGREDO_DO_BOT}/{tenant_id}")
            ),
            aviso=lambda motivo: log.warn(outcome="admissao", error_code=motivo),
            # A terceira rota (KAM-038). Sem ela, `/internal/event` responde 503
            # e o evento fica na fila — e o que a omissao de `rotas` faz.
            eventos=consumidor_de_eventos,
            # A quarta rota (KAM-114). Sem ela, `/internal/draft-decision`
            # levanta `DecisaoNaoImplementadaError` — e **nao** devolve 200 a
            # fingir que decidiu, que ali e o pior desfecho possivel: o HND
            # marcava o rascunho como tratado, nenhuma mensagem saia e nem um
            # `expirado` ficava registado.
            decidir=decisor_de_rascunhos.decidir,
        ),
        # As duas ligacoes fecham-se no encerramento do processo, e **havia aqui
        # uma lacuna**: o `TrancaDeConversas.fechar()` existia e nao tinha
        # chamador nenhum em producao (achado da revisao adversarial). Corre no
        # `lifespan`, que o uvicorn fecha em `SIGTERM` — o sinal com que um
        # orquestrador para um contentor. Fechar a tomada larga as trancas que
        # ela tivesse, o que importa: sem isto, as trancas de um processo que
        # para ficam ate o PostgreSQL notar a tomada fechada, e o *worker* que
        # recebe os *jobs* a seguir espera por elas sem razao.
        # As trancas **e** o checkpointer: sao as tres tomadas que este
        # processo abre, e nenhuma se fecha sozinha. Quem o passa ao
        # `compile(checkpointer=...)` e o **KAM-031** — e nao o KAM-027, como
        # esta linha dizia: aquele entregou o registo e nao um grafo, e nao ha
        # `compile` nenhum sem grafo. Aqui o checkpointer serve a guarda do
        # arranque e o encerramento, e nada mais.
        ao_encerrar=_fechar_as_tomadas(
            trancas, checkpointer, tools, retomador, conversas_de_eventos
        ),
    )

    # O anfitriao e a porta nao estao na *allowlist* de `docs/tecnica/08` §7.3.
    log.info(outcome="service_started")
    uvicorn.run(
        aplicacao,
        host=listen_host,
        port=listen_port,
        log_level="info",
        log_config=None,
        access_log=False,
    )
    return 0


def _grafo_da_thread(_thread_id: str):
    """A porta `grafos` da **retoma e da decisao de rascunho**, por ligar.

    Ver o comentario no `main`. **Serve as duas** (KAM-034 e KAM-114) porque as
    duas tem a mesma forma — recebem um `thread_id` — e resolvem a mesma
    pergunta: «qual e o grafo que interrompeu este *thread*?». Quem ligar o
    AgentRegistry substitui esta e a do executor.

    Chama o `sem_grafos` com `None` em vez de o passar directamente, e nao e
    cerimonia: as duas portas tem formas diferentes — aquela recebe uma
    `InvocacaoDoAgente` e esta um `thread_id` —, e passar a mesma funcao as duas
    escondia que sao duas resolucoes a ligar. Quem ligar o AgentRegistry
    substitui **as duas**.
    """
    return sem_grafos(None)  # type: ignore[arg-type]


async def _hnd_por_ligar(_invocacoes) -> None:
    """A porta do HND, por ligar. KAM-019 entrega o provedor.

    Nao levanta: o criterio 6 pede que a mensagem **nao entre no grafo** e seja
    reencaminhada, e a parte que este ticket entrega e a decisao. Levantar aqui
    fazia o turno falhar e o *job* repetir-se sobre uma conversa que
    continuaria em `pausada` — uma repeticao sem fim para dizer sempre o mesmo.
    O que isto deixa e um reencaminhamento que nao reencaminha, e e por isso que
    a caixa do criterio 6 se marca sobre a decisao e a secção de verificacao do
    bloco diz exactamente isso.
    """
    return None


if __name__ == "__main__":
    raise SystemExit(main())
