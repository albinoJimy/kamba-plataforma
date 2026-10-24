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
   processo sai com `3` e nao serve um unico pedido. E o criterio 8.
2. `egresso.desligar_telemetria()` — impoe `false`, nao verifica. E o criterio 7.

Sai com codigo **3** e nao com `2`: o `2` e o de configuracao invalida, que o
KAM-001 ja usa para a porta, e os dois distinguem-se no painel de arranques. Um
codigo so dizia «nao arrancou» e nada mais.

Depois disso, o arranque pode ser lento e pode falhar: le o segredo da API
interna do cofre (`Secrets.arrancar` aborta sem ele em `prod`) e abre as duas
ligacoes. Uma falha aqui e um `return`, nunca um `uvicorn.run` a meio.
"""

from __future__ import annotations

import os

import uvicorn
from kamba_core import host, port
from kamba_core.logger import instalar
from kamba_core.secrets import AMBIENTES, EnvSecretProvider, Secrets

from . import egresso
from .admissao import Admissao, Tectos
from .api_interna import SEGREDO_DA_API, rotas
from .app import create_app
from .conversa import leitor
from .ligacao import ligar_para_leitura, ligar_para_tranca
from .meta import DEFAULT_PORT, SERVICE
from .trancas import TrancaDeConversas
from .turno import ExecutorDeTurnos, sem_grafos

#: Codigo de saida de uma guarda do ADR-002 violada. Distinto do `2` do KAM-001
#: (configuracao invalida), para que os dois se distingam num painel.
SAIDA_GUARDA_ADR002 = 3

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

    try:
        segredos = Secrets.arrancar(
            servico=SERVICE,
            provider=EnvSecretProvider(ambiente),
            obrigatorios=[SEGREDO_DA_API],
        )
    except Exception as exc:  # noqa: BLE001 — qualquer falha de cofre aborta
        log.excepcao(exc, "cofre_indisponivel")
        return 2

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
        ao_encerrar=trancas.fechar,
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
