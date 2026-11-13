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
from kamba_core.logger import Logger, instalar
from kamba_core.secrets import AMBIENTES, EnvSecretProvider, Secrets

from . import egresso, eventos as evt, registo
from .admissao import Admissao, Tectos
from .api_interna import SEGREDO_DA_API, rotas
from .app import create_app
from .checkpointer import CheckpointerDoAgr
from .conversa import leitor, leitor_de_contacto
from .handoff.autenticacao import verificador
from .concierge.politica import PoliticaDeConcierge
from .concierge.portas import ProvedorDeRascunhoPorLigar
from .concierge.rascunho import ServicoDeRascunho
from .concierge.servico import Decisor
from .degradacao import DetectorDeDegradacao
from .grafos import (
    PoliticaDoTurno,
    PortaDeGrafos,
    PortasIncoerentesError,
    SaidaPorLigar,
    admitir,
    compilar,
    para_validar,
)
from .handoff.servico import ServicoDeHandoff
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
from .tls.embeddings import consulta_vectorial
from .tls.idx import LIMIAR_DO_RRF, LigacaoVectorial, executores_do_idx
from .tls.com import (
    SEGREDO_DO_COM,
    VARIAVEL_DA_BASE as VARIAVEL_DO_COM,
    ClienteDoCom,
    executores_do_com,
)
from .trancas import TrancaDeConversas
from .turno import ExecutorDeTurnos

#: A referencia do `secret` do *agent bot* no cofre (KAM-034, criterio 4).
#:
#: `instancias: conta` em `ops/secrets-inventory.yaml`, pelo que o nome leva a
#: instancia: `chatwoot_bot_secret/<tenant_id>`. A forma e a da
#: `litellm_virtual_key` do KAM-030, e nao a do `agr_internal_token` — que tem
#: `instancias: nenhuma` e e um valor so para o servico.
REF_SEGREDO_DO_BOT = "chatwoot_bot_secret"


class CredencialDoCom:
    """A credencial da API interna do COM, lida do cofre **quando for usada**.

    ## Porque e que isto existe, em vez de uma cadeia

    O catalogo da ToolLayer constroi-se **antes** do `Secrets.arrancar`, e nao
    por descuido: ele e a fonte da validacao (1) do §5.2, que corre com o registo
    — e o registo le-se primeiro de proposito, porque «nao ha nada a ganhar em
    descobrir uma subscricao sem consumidor **depois** de abrir sete ligacoes».
    Trocar a ordem mudava os codigos de saida que o dicionario §3.26 fixa.

    Logo os executores do COM nascem sem a credencial, e esta classe e o fio que
    a liga quando ela existir. Chamada antes disso, **levanta** — o que e um
    defeito de montagem e nao uma recusa: nenhuma tool corre antes de o arranque
    acabar, porque nenhum turno chega antes de o `uvicorn` escutar.

    E a leitura e **a cada chamada**, como no `api_interna.py`: uma rotacao do
    cofre chega sem reinicio.
    """

    __slots__ = ("_ler",)

    def __init__(self) -> None:
        self._ler: Callable[[], str] | None = None

    def ligar(self, ler: Callable[[], str]) -> None:
        self._ler = ler

    def __call__(self) -> str:
        if self._ler is None:
            raise RuntimeError(
                "a credencial do COM foi pedida antes de o arranque ler o cofre: "
                "e defeito de montagem do __main__ e nao uma recusa (KAM-178)"
            )
        return self._ler()


def _executores_do_comercio(
    log: Logger, credencial: CredencialDoCom
) -> dict[str, Any]:
    """Os executores das tools de comercio, se houver COM com quem falar.

    **Sem `KAMBA_COM_URL` nao se liga nada**, e isso nao e uma falha: as cinco
    entradas do Vendedor ficam `declaradas` com o credor que ja tinham, e o
    `log` de arranque di-lo na linha `toollayer_pronta` (`ligadas_N_de_11`). Um
    endereco por omissao era um AGR a tentar falar com um COM que ninguem
    configurou — e a falhar no primeiro turno de um cliente em vez de no
    arranque.
    """
    base = os.environ.get(VARIAVEL_DO_COM, "").strip()
    if not base:
        log.warn(outcome="com_sem_endereco")
        return {}
    return executores_do_com(ClienteDoCom(base=base, credencial=credencial))

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
    # A credencial do COM e lida do cofre mais abaixo e liga-se a este objecto
    # quando o for: ver a `CredencialDoCom`.
    credencial_do_com = CredencialDoCom()
    # O `search_catalog` liga-se **sempre** (KAM-061): o indice vive na base da
    # plataforma, a que o AGR ja tem tomada, e nao depende de variavel nenhuma.
    # O vector da pergunta (KAM-063) liga-se mais abaixo, com o cliente do
    # gateway; ate la, e sem modelo escolhido, a pesquisa e lexical.
    ligacao_vectorial = LigacaoVectorial()
    catalogo = catalogo_do_piloto(
        {
            **_executores_do_comercio(log, credencial_do_com),
            **executores_do_idx(ligacao_vectorial),
        }
    )
    # **A validacao (3) corre a serio desde o KAM-186**: o `construir_grafo`
    # compila o alvo `graph` de cada `registry/<id>.yaml` e confere os seis nos
    # obrigatorios, e as duas linhas `grafo: { modo: aviso }` sairam do
    # `registry/gates.yaml`. Um alvo que nao importa e codigo de saida 5.
    ambiente_do_registo = registo.AmbienteDoRegisto.do_repositorio(
        pasta.parent, catalogo=catalogo, construir_grafo=para_validar
    )
    # **O `AgentRegistry` e o que resolve cada turno** (KAM-027, criterio 6):
    # vertical por contexto e entitlement activo. O leitor de entitlements e o
    # do KAM-038, uma ligacao por leitura em `tenant_guard.tx`, e nao abre nada
    # aqui — a primeira leitura e a do primeiro turno.
    agentes = registo.AgentRegistry(
        evt.LeitorDeEntitlements(ligar_para_eventos).ler, metricas=METRICAS
    )
    try:
        adiadas = agentes.load_all(ambiente_do_registo, pasta)
    except (registo.RegistoInvalidoError, registo.FicheiroIlegivelError) as exc:
        log.excepcao(exc, "registo_invalido")
        return SAIDA_REGISTO_INVALIDO
    verticais = dict(agentes.verticais)

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
        evt.exigir_handlers(subscricoes)
    except (evt.SubscricoesInvalidasError, evt.SemHandlerError) as exc:
        log.excepcao(exc, "subscricoes_invalidas")
        return SAIDA_SEM_CONSUMIDORES
    log.info(
        outcome="consumidores_de_eventos",
        error_code=f"consumidores_{len(evt.nomes_dos_consumidores(subscricoes))}"
        f"_subscricoes_{len(subscricoes)}",
    )

    # As validacoes em modo `aviso` — hoje so a do golden, que espera pelo
    # KAM-040 (`registry/gates.yaml`). A do KAM-028 saiu com o catalogo, e as do
    # grafo sairam com o KAM-186. Um `aviso` que nao aparece no
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
            obrigatorios=[SEGREDO_DA_API, SEGREDO_DO_COM],
        )
    except Exception as exc:  # noqa: BLE001 — qualquer falha de cofre aborta
        log.excepcao(exc, "cofre_indisponivel")
        return 2
    # A partir daqui os executores do COM tem credencial. Antes disto nenhum
    # corre: nenhum turno chega antes de o `uvicorn` escutar.
    credencial_do_com.ligar(lambda: segredos.get(SEGREDO_DO_COM))

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
    # que o `build_graph(deps)` do §5.2 recebe, ligada mais abaixo (KAM-186) —
    # a mesma nas duas verticais, pela razao do disjuntor escrita acima.
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

    # **A porta real, sobre `platform.tenant_destinations` (KAM-069).** A
    # ligacao e a mesma do registo de chamadas — uma por chamada, aberta dentro
    # de `tenant_guard.tx` e fechada —, e a *cache* de 60 s da porta faz com que
    # so se abra quando a decisao nao esta la.
    #
    # O `confirmar` acima ja provou que esta ligacao responde; se nao
    # respondesse, o arranque tinha abortado com `SAIDA_SEM_GATEWAY_LLM`. Sem
    # ligacao a porta devolvida seria a `NegaTudoAteKam069`, que e a **mais**
    # restritiva — a ausencia de base nunca afrouxa o *gate*.
    destinos = llm_destinos.arrancar(ambiente, ligar_para_llm)
    # **O aviso em `staging` nao e enfeite.** O criterio 8 do KAM-030 diz «so
    # dados sinteticos em `staging`», e nenhum codigo consegue verificar que os
    # dados sao sinteticos. Um aviso por arranque torna a condicao visivel; o
    # silencio lia-se como garantia.
    #
    # **Em `prod` o que se diz mudou com o KAM-069**, e e a diferenca que
    # importa: ja nao e «nega tudo», e «nega o que nao esta autorizado». Hoje
    # isso e tudo na pratica — o `ext:KAM-105` fechou com 0 de 14 destinos com
    # `apd_ref` —, mas por falta de autorizacao e nao por falta de barreira, e
    # as duas coisas resolvem-se de maneiras diferentes.
    if ambiente == llm_destinos.AMBIENTE_PROD:
        log.warn(outcome="llm_destinos", error_code="so_destino_autorizado")
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
    # **O grafo nao o recebe, e fica dito**: o `Dependencias` nao tem campo de
    # LLM, e as duas portas que o usariam — o `classificador` do §15.1 e o
    # `classificador_de_guarda` do KAM-033 — ficam por ligar (ver a linha
    # `grafo_porta_por_ligar` mais abaixo). Hoje o que ele serve no arranque e
    # a guarda do `dat.llm_call_log` acima.
    log.info(
        outcome="llm_gateway_pronto",
        error_code=f"papeis_{len(cliente_de_llm.papeis())}",
    )
    # **O vector da pergunta (KAM-063)**, pela mesma porta de destinos que o
    # gateway. Sem modelo no `kamba-embed` fica por ligar e a pesquisa e lexical
    # — e diz-se no arranque, que o silencio lia-se como modo hibrido.
    vectorial = consulta_vectorial(cliente_de_llm, destinos)
    ligacao_vectorial.ligar(vectorial)
    log.info(
        outcome="idx_embeddings",
        error_code="hibrido_ligado" if vectorial is not None else "so_lexical_sem_modelo",
    )

    # O *handoff* (KAM-034). Sao tres pecas:
    #
    # * o `ServicoDeHandoff` e a porta `hnd` que o `build_graph` recebe, e
    #   constroi-se com as outras portas do grafo, mais abaixo (KAM-186). O
    #   provedor HTTP do HND nao existe no AGR: a omissao e o `ProvedorPorLigar`,
    #   que **levanta** `HandoffIndisponivel` — a degradacao do
    #   `docs/tecnica/01` §11.5 e nao uma omissao silenciosa;
    # * o `Retomador` entra em `/internal/resume`;
    # * a varredura dos prazos nao se constroi aqui, porque **nao ha
    #   agendador** nesta fase (a mesma linha que o `retencao.py` do KAM-026
    #   escreveu): o corpo da varredura e o `Prazos.varrer`, o credor e o
    #   *scheduler* do EVT, e agendar sem agendador era escrever um que ninguem
    #   pediu.
    admissao = Admissao(tectos=tectos)
    trancas = TrancaDeConversas(ligar_para_tranca)

    # **As portas do grafo** (KAM-186, criterio 5). Cada uma tinha uma omissao
    # nas `Dependencias` que **nao faz nada** — `SemPolitica`, `SemDegradacao`,
    # `hnd=None`, `_admite_sempre`, `checkpointer=None` —, e um arranque com a
    # porta esquecida e verde. Por isso estao todas aqui, num so dicionario que
    # a bateria le, e cada uma tem ensaio que fica vermelho com ela na omissao.
    #
    # A `PoliticaDeConcierge` le-se da base em **cada turno**, sem *cache*, e e
    # isso que faz desactiva-la ter efeito no turno seguinte (criterio 8 do
    # KAM-114); o leitor e o do KAM-038, que corre em `tenant_guard.tx` com o
    # *tenant* de quem chama e **falha fechado**. O `ServicoDeRascunho` vai com
    # ela, sempre: a politica sem servico e o `P3` do `ADR-L005`, e o
    # `compilar` recusa o par (criterio 8). Vai embrulhada na `PoliticaDoTurno`,
    # que a le **fora** da *event loop*, na resolucao do turno: o `send` e
    # `async` e a leitura e sincrona (ver `grafos.py`).
    portas_do_grafo = {
        "tools": tools,
        "saida": SaidaPorLigar(
            aviso=lambda motivo: log.warn(outcome="saida", error_code=motivo)
        ),
        "hnd": ServicoDeHandoff(metricas=METRICAS),
        "metricas": METRICAS,
        "admitir": admitir,
        "checkpointer": checkpointer,
        "concierge": PoliticaDoTurno(
            PoliticaDeConcierge(evt.LeitorDeEntitlements(ligar_para_eventos).ler)
        ),
        "rascunho": ServicoDeRascunho(
            abrir_ligacao=ligar_para_concierge,
            provedor=ProvedorDeRascunhoPorLigar(),
            metricas=METRICAS,
        ),
        "degradacao": DetectorDeDegradacao(admissao=admissao, metricas=METRICAS),
        # O limiar do `retrieve` e o do pontuador que o `search_catalog` usa.
        # Ligado o indice real (KAM-061), e o `LIMIAR_DO_RRF` de `tls/idx.py`, e
        # nao o `LIMIAR_IDX` do duplo — que comparado com um RRF mandava toda a
        # pesquisa para o `unknown_reply`.
        "limiar_idx": LIMIAR_DO_RRF,
    }
    try:
        grafos_do_processo = compilar(verticais, portas_do_grafo)
    except PortasIncoerentesError as exc:
        log.excepcao(exc, "portas_incoerentes")
        return 2
    porta_de_grafos = PortaDeGrafos(
        registo=agentes,
        grafos=grafos_do_processo,
        checkpointer=checkpointer,
        contacto_bloqueado=leitor_de_contacto(ligar_para_leitura),
        politica=portas_do_grafo["concierge"],
    )
    log.info(outcome="grafos_ligados", error_code=f"verticais_{len(grafos_do_processo)}")
    # **O que fica por ligar diz-se, porta a porta.** Nenhuma destas finge: a
    # `saida` avisa e levanta em cada envio, e a rota responde 503 (nao ha
    # Outbound a que o AGR fale, e o achado esta no `grafos.py`), o `stt` sem porta da `ask_repeat` (KAM-036), os
    # dois classificadores sem porta deixam decidir as regras, e os `modos` sao
    # o KAM-018. Uma porta por ligar que nao aparece no registo de arranque e
    # uma omissao silenciosa, que e o que o DoD do KAM-186 proibe.
    for porta in ("classificador", "classificador_de_guarda", "modos", "saida", "stt"):
        log.warn(outcome="grafo_porta_por_ligar", error_code=porta)

    # KAM-114. O `Decisor` entra em `/internal/draft-decision` e o
    # `Substituidor` entra no `ExecutorDeTurnos` (criterio 5).
    #
    # A varredura dos rascunhos nao se constroi aqui, pela mesma linha do
    # `Prazos` do KAM-034 e do `retencao.py` do KAM-026: **nao ha agendador**
    # nesta fase, o corpo e o `Varredura.varrer`, e o credor e o *scheduler* do
    # EVT (KAM-071).
    #
    # **A retoma e a decisao recebem a porta por `thread_id`, e o turno a da
    # invocacao** (KAM-186, criterio 4). Sao duas resolucoes e nao uma: a
    # retoma nao tem invocacao — o corpo de `/internal/resume` sao tres campos
    # —, e a vertical de uma *thread* que espera e a do grafo que a
    # interrompeu, que quem sabe e o *checkpoint*. As duas resolvem-se **antes**
    # do CAS, e sem grafo a rota responde 503 sem escrever nada.
    decisor_de_rascunhos = Decisor(
        abrir_ligacao=ligar_para_concierge,
        grafos=porta_de_grafos.da_thread,
        metricas=METRICAS,
    )
    substituidor_de_rascunhos = Substituidor(
        abrir_ligacao=ligar_para_concierge,
        decidir_pelo_sistema=decisor_de_rascunhos.decidir_pelo_sistema,
    )
    retomador = Retomador(
        abrir_ligacao=ligar_para_handoff,
        grafos=porta_de_grafos.da_thread,
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
        # A porta do turno (KAM-186): resolve a vertical pelo registo e pelo
        # entitlement, le a admissao, e devolve o grafo dela. Uma vertical
        # recusada acaba em `servico_indisponivel`, com 200 — nao volta a fila.
        grafos=porta_de_grafos.do_turno,
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
        # processo abre, e nenhuma se fecha sozinha. O checkpointer e o que os
        # dois grafos recebem no `compile(checkpointer=...)` (KAM-186), e e o
        # mesmo que a porta por `thread_id` le — um so objecto, uma so tomada.
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
