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
from typing import Any

import uvicorn
from kamba_core import host, port
from kamba_core.logger import instalar
from kamba_core.secrets import AMBIENTES, EnvSecretProvider, Secrets

from . import egresso, registo
from .admissao import Admissao, Tectos
from .api_interna import SEGREDO_DA_API, rotas
from .app import create_app
from .checkpointer import CheckpointerDoAgr
from .conversa import leitor
from .metricas import METRICAS
from .ligacao import (
    ligar_para_checkpoint,
    ligar_para_leitura,
    ligar_para_tranca,
)
from .meta import DEFAULT_PORT, SERVICE
from .trancas import TrancaDeConversas
from .turno import ExecutorDeTurnos, sem_grafos

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
    trancas: Any, checkpointer: Any
) -> Callable[[], Awaitable[None]]:
    """O que o `lifespan` corre no `SIGTERM`: fecha as duas, pela ordem.

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
    pasta = registo.directorio_do_registo()
    try:
        _, _, adiadas = registo.carregar(
            registo.AmbienteDoRegisto.do_repositorio(pasta.parent), pasta
        )
    except (registo.RegistoInvalidoError, registo.FicheiroIlegivelError) as exc:
        log.excepcao(exc, "registo_invalido")
        return SAIDA_REGISTO_INVALIDO

    # As validacoes em modo `aviso` — as que esperam por KAM-028, KAM-031,
    # KAM-035 e KAM-040 (`registry/gates.yaml`). Um `aviso` que nao aparece no
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

    admissao = Admissao(tectos=tectos)
    trancas = TrancaDeConversas(ligar_para_tranca)
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
    )
    aplicacao = create_app(
        rotas_internas=rotas(
            credencial=lambda: segredos.get(SEGREDO_DA_API),
            executar=executor.correr,
            admissao=admissao,
            trancas=trancas,
            aviso=lambda motivo: log.warn(outcome="admissao", error_code=motivo),
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
        ao_encerrar=_fechar_as_tomadas(trancas, checkpointer),
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
