"""A saida de canal (TypeScript) contra o PostgreSQL do gate — KAM-015.

O codigo vive em `packages/core-ts/src/outbound/` e os seus testes de base de
dados em `packages/core-ts/tests_bd/outbound.bd.test.ts`. Esta suite e o que os
poe a correr contra a base descartavel, com as migracoes em `head`, e e ela que
le o que eles deixam: a saida, os numeros que eles medem e a cobertura de
`src/outbound/`.

Porque e suite propria, e nao mais um ficheiro em `tests`: e **TypeScript**
contra a base, como a de identidade, a de eventos e a do CHR, e nenhuma das
baterias de `db/tests/` corre Node. E porque metade do criterio 2 — «1 chamada a
API (servidor falso conta)» — exige o `GraphFalso` do KAM-024 a contar as
chamadas, que nenhuma base consegue fazer.

Desde o KAM-023 ela corre tambem o contador do *free tier* (`src/metering/`) e,
desde o KAM-021, a gestao de canal (`src/qualidade/`). As razoes de cada um
estarem aqui e nao em suite propria estao nos comentarios do `FICHEIROS`; a que
vale para os dois e que usam as mesmas tabelas, o mesmo `apoio.ts` e os mesmos
papeis, e a que vale so para o KAM-021 e que o criterio 9 dele se prova **de
ponta a ponta** — a `Saida` deste ticket a recusar um template num canal que a
bateria da qualidade acabou de restringir — e isso precisa do `GraphFalso`, que
so esta suite monta.

**O que esta suite nao mede**, e onde se mede: a matriz de decisao, a monotonia
celula a celula, a aritmetica do custo, os tectos do *token bucket* e o cliente
HTTP vivem nas baterias do gate 4, em
`packages/core-ts/tests/outbound.*.test.ts` — sao funcoes puras, e uma base real
nao acrescenta nada a prova. O que **so** aqui se prova esta na docstring do
ficheiro TypeScript, e e disso que os `GRUPOS` abaixo sao a lista.
"""

from __future__ import annotations

import re
import shutil
import sys
import tempfile
import unittest
from pathlib import Path

from tests.base import ComBase
from tests_outbound import node

sys.path.insert(0, str(node.RAIZ / "tools"))

from kamba_yaml import load_file  # noqa: E402

#: Os ficheiros de teste, pela ordem em que correm. Os de cima nao precisam de
#: base (correm tambem no gate 4) e estao aqui pela cobertura: sem eles, a
#: medida de `src/outbound/` nao incluiria o que eles exercitam, e o limiar nao
#: se podia aplicar por ficheiro.
FICHEIROS = (
    "tests/outbound.decisao.test.ts",
    "tests/outbound.estados.test.ts",
    "tests/outbound.limites.test.ts",
    "tests/outbound.adapter.test.ts",
    "tests_bd/outbound.bd.test.ts",
    # KAM-023. O contador do *free tier* vive em `src/metering/`, mas escreve
    # `tenant_channels` e le `outbound_messages`, e as tres propriedades que
    # so uma base prova — a fronteira de mes no fuso de `Africa/Luanda` (que
    # vive dentro de `platform.ten_periodo`), o flanco do aviso sob
    # concorrencia, e o isolamento — nao tem onde correr fora desta suite.
    # Entra aqui e nao numa suite nova porque usa as mesmas tabelas, o mesmo
    # `apoio.ts` e os mesmos papeis; uma suite propria custava um ficheiro de
    # arranque, um alvo no Makefile e uma entrada em `db/gate_bd.py` para
    # levantar o mesmo PostgreSQL.
    #
    # A metade de unidade entra **pela prova por mutacao**, que e a mesma razao
    # pela qual os quatro ficheiros de unidade do KAM-015 tambem estao nesta
    # lista. O `db/mutacoes.py` corre uma suite inteira contra a copia mutada e
    # exige que ela falhe; uma mutacao em `custo.ts` ou em `metricas.ts` — o
    # racio limitado a 1, o guarda do denominador zero, a etiqueta de tenant
    # aceite — so e apanhada pelo ficheiro de unidade. Deixa-lo de fora dava
    # mutacoes que **nenhum teste pode matar**, e uma mutacao sobrevivente por
    # desenho e pior do que nenhuma: conta como prova. Custa cerca de 1 s.
    "tests/metering.test.ts",
    "tests_bd/metering.bd.test.ts",
    # KAM-021. A gestao de canal vive em `src/qualidade/`, e entra nesta suite
    # pelas mesmas tres razoes que o contador do KAM-023: escreve
    # `tenant_channels`, le `outbound_messages` e usa o mesmo `apoio.ts` e os
    # mesmos papeis. Mas ha uma quarta que so vale para ela, e e decisiva: o
    # criterio 9 prova-se de ponta a ponta — a `Saida` do KAM-015, com a porta
    # de estado ligada a uma consulta real, recusa um template num canal que a
    # propria bateria acabou de restringir. Isso precisa do `GraphFalso` do
    # KAM-024, e **esta e a unica suite do gate 8 que monta o `tools/meta-sim`**
    # (ver as `PASTAS_DE_MODULOS` do `node.py`, e a nota do `tests_media/node.py`
    # que explica porque la sao duas e aqui tres).
    #
    # A metade de unidade entra pela **prova por mutacao**, pela razao escrita
    # acima para o `metering.test.ts`: uma mutacao em `qualidade/decisao.ts` ou
    # em `qualidade/metricas.ts` — a fraccao de aviso, o tecto do escalao, o
    # guarda do `NaN`, a etiqueta recusada — so e apanhada pelo ficheiro de
    # unidade, e uma mutacao que nenhum teste pode matar conta como prova.
    "tests/qualidade.test.ts",
    "tests_bd/qualidade.bd.test.ts",
    # KAM-022. A barreira de consentimento vive em `src/consentimento/`, e
    # entra nesta suite por **uma** razao que nao e a das outras duas: a
    # contagem de avisos do criterio 3 sai do prefixo da `idempotency_key` de
    # `outbound_messages`, que e a tabela deste ticket. Nao ha coluna de
    # contagem em sitio nenhum do esquema, e a chave que impede o aviso de sair
    # duas vezes e a que diz quantas vezes saiu — o que a liga a esta suite nao
    # e conveniencia, e a tabela.
    #
    # O resto do que **so** a base prova — a unicidade da prova sob
    # concorrencia, a vista `consent_actual` a respeitar a RLS de quem a
    # consulta (a primeira vista do esquema, com `security_invoker = true`), a
    # FK composta, e o `42501` de um `UPDATE` que nao existe — podia correr numa
    # suite propria; o que a juntaria a esta de qualquer forma e que a `0015`
    # vive na mesma base e nao precisa de fila nem de Meta falsa.
    #
    # A metade de unidade entra pela **prova por mutacao**, pela razao escrita
    # acima para o `metering.test.ts`: as mutacoes na matriz de dezoito celulas,
    # na deteccao do «PARAR» e no `evidence_hash` so por ela sao apanhadas.
    "tests/consentimento.test.ts",
    "tests_bd/consentimento.bd.test.ts",
    # KAM-016. O onboarding de canal vive em `src/onboarding/`, e entra nesta
    # suite por **duas** razoes, e a segunda e a que nao tinha alternativa.
    #
    # A primeira e a dos tres tickets acima: escreve `tenant_channels` — o
    # criterio 4 e a `tenant_channels_phone_number_id_uq` **global** a morder, e
    # a compensacao do criterio 7 **apaga** a linha que o passo anterior criou —,
    # usa o mesmo `apoio.ts` e os mesmos papeis, e a `0016` vive na mesma base.
    #
    # A segunda e o `GraphFalso` do KAM-024, e **esta continua a ser a unica
    # suite do gate 8 que monta o `tools/meta-sim`** (ver as `PASTAS_DE_MODULOS`
    # do `node.py`). O criterio 5 pede «a leitura de confirmacao devolve esse
    # conjunto (igualdade de conjuntos)» e o criterio 7 pede uma falha injectada
    # no passo 4 **com 0 recursos orfaos** — e «0 subscricoes no WABA» le-se no
    # servidor falso e em mais sitio nenhum. Uma suite propria custava um
    # ficheiro de arranque, um alvo no Makefile, uma entrada em `db/gate_bd.py` e
    # uma quarta pasta de modulos, para levantar o mesmo PostgreSQL e montar o
    # mesmo simulador.
    #
    # Os dois ficheiros de unidade entram pela **prova por mutacao**, pela razao
    # escrita acima para o `metering.test.ts`: as mutacoes na matriz de
    # dezesseis arestas, na forma de v4, na cifra do token e na comparacao de
    # conjuntos so por eles sao apanhadas, e uma mutacao que nenhum teste pode
    # matar conta como prova.
    "tests/onboarding.test.ts",
    "tests/onboarding.graph.test.ts",
    "tests_bd/onboarding.bd.test.ts",
)

#: Os grupos que **tem** de aparecer na saida, um por propriedade que a suite
#: prova. Se um desaparecer, a suite deixa de provar essa propriedade — e isso
#: tem de falhar aqui, nao passar por haver menos testes.
#:
#: Os quatro primeiros sao do `tests/outbound.adapter.test.ts` (sem base: a
#: ordem dos passos, o backoff e o registo); os cinco ultimos sao do
#: `tests_bd/outbound.bd.test.ts` e sao os que **so** uma base real prova.
GRUPOS = (
    "o backoff do 130429, de ponta a ponta (criterio 6)",
    "a ordem dos passos: onde nao ha chamada HTTP",
    "o guarda do KAM-018 falha fechada (criterio 8)",
    "o registo nao leva o wamid em claro (DoD «Privacidade»)",
    "idempotencia (criterio 2)",
    "monotonia contra concorrencia (criterio 3)",
    "isolamento (Testes Requeridos: X-03 sobre outbound_messages)",
    "o custo por tenant sai da tabela (DoD «Custo e observabilidade»)",
    "o bloqueio de template (criterio 9)",
    # KAM-023, do `tests_bd/metering.bd.test.ts`.
    "a contagem (criterio 1)",
    "a fronteira de mes e a de Africa/Luanda (criterio 3)",
    "o flanco do aviso sob concorrencia (criterio 3)",
    "idempotencia por wamid (criterio 2)",
    "isolamento (Testes Requeridos: contadores de A nao afectam B)",
    "a janela de falhas e a reconciliacao (criterios 5 e 7)",
    "a marca de restricao (criterios 5 e 6)",
    # KAM-021, do `tests_bd/qualidade.bd.test.ts`.
    "o registo da transicao (criterio 1)",
    "idempotencia da transicao (criterio 6)",
    "a restricao e a reposicao (criterio 2)",
    "o registo nao se corrige: o privilegio nem existe",
    "o dominio e as chaves mordem atraves do modulo",
    "isolamento (Testes Requeridos: X-03 sobre channel_quality_log)",
    "a medicao do escalao (criterio 7)",
    "os limites e os templates (criterios 5 e 8)",
    "o criterio 9 de ponta a ponta: a saida honra o restrito",
    # KAM-021, de `tests/outbound.adapter.test.ts` (sem base): a porta 5.
    "a porta de estado do KAM-021 (criterio 9)",
    # KAM-022, do `tests_bd/consentimento.bd.test.ts` e do
    # `tests/consentimento.test.ts`.
    "a matriz do aviso: 6 entradas x 3 estados",
    "a deteccao do PARAR (criterio 5)",
    "a prova reproduzivel (criterio 7)",
    "a propriedade: 1.000 mensagens x 50 contactos (criterio 4)",
    "o primeiro contacto (criterio 1)",
    "o «Continuar» e o ciclo inteiro (criterio 2)",
    "o «PARAR» (criterio 5)",
    "a versao vigente do texto (criterio 7)",
    "isolamento (Testes Requeridos: X-03 sobre consent_event)",
    "o append-only: o privilegio nem existe (criterio 6)",
    # KAM-016, dos tres ficheiros do onboarding. Os cinco primeiros sao de
    # unidade (a forma de v4, a matriz nos 81 pares, os onze campos, a cifra e a
    # saga); os restantes sao os que **so** uma base real prova, e o do cliente
    # da Graph e o unico que abre socket.
    "a forma de v4, e so v4 (criterio 1)",
    "a matriz de transicoes: os 81 pares ordenados (criterio 6)",
    "os onze campos e a igualdade de conjuntos (criterio 5)",
    "a cifra do token: AES-256-GCM, DEK por tenant, kid versionado (criterio 3)",
    "a saga: ordem dos passos e idempotencia (criterios 2, 4, 7, 8)",
    "as metricas do onboarding",
    "o cliente da Graph contra o servidor falso do KAM-024",
    "a porta de escrita no cofre (ADR-L002 §6, a lacuna que este ticket fecha)",
    "idempotencia (criterio 2)",
    "o 409 do phone_number_id (criterio 4)",
    "a maquina de estados contra a base (criterio 6)",
    "a compensacao: 0 recursos orfaos (criterio 7)",
    "o token e o PIN: o dump grep nao os encontra (criterio 3)",
    "o contador es_onboardings_7d (criterio 8)",
    "isolamento (Testes Requeridos: X-03 sobre channel_onboarding)",
)

#: Testes que **tem** de ter corrido e passado, pelo nome. Lista curta, com os
#: que dao a letra de cada criterio.
#:
#: Os primeiros quatro sao do `tests/outbound.adapter.test.ts`, que corre sem
#: base: o criterio 6 («backoff exponencial com jitter, 3 tentativas; o 130429
#: repete, o 131049 nao») **nao se prova contra a base**, porque la as respostas
#: vem do `GraphFalso` e dizem 200. Sem estas quatro linhas, o criterio 6 estava
#: provado so ao nivel das funcoes `vaiRepetir` e `atrasoMs` — isto e, provado
#: que a regra existe, nao que o adapter a usa.
TESTES_OBRIGATORIOS = (
    "**tres 130429 e depois um 200: 1 entregue, 0 duplicados** — a letra",
    "o 130429 sem fim desiste: quatro chamadas, nunca cinco",
    "**o 131049 nao repete: uma chamada e so uma**",
    "o Retry-After manda sobre o backoff calculado",
    "**sem guarda, em CI, levanta** — e nao envia",
    "o msg_id e o idOpaco do §3.10, e o wamid nao aparece em sitio nenhum",
    "**duas chamadas com a mesma chave: 1 linha e 1 chamada HTTP**",
    "**a mesma chave em dois tenants da duas linhas**",
    "dois statuses em paralelo: o estado final e o maior, e o custo conta uma vez",
    "um failed depois de delivered fica failed, e nao conta custo",
    "com o contexto de A, as linhas de B nao aparecem",
    "com o contexto de A, uma escrita na linha de B nao acontece",
    "os templates de A nao se veem com o contexto de B",
    "o SQL_CUSTO_DO_TENANT soma o pricing das entregues",
    "o custo de A nao inclui o de B — a RLS tambem protege a consulta",
    "recategorizar para marketing bloqueia, e e idempotente",
    # KAM-023. Cada uma da a letra de um criterio, e as duas primeiras sao as
    # que **so** uma base prova: o fuso vive dentro de `platform.ten_periodo` e
    # o flanco depende do `FOR UPDATE`.
    "**00:30 em Luanda ja e Novembro, e o contador reinicia**",
    "**o mes vem em texto e nao num `Date`** — e isto foi um defeito medido",
    "**com o mes a `NULL` e o contador em 500, o reinicio repoe e nao soma**",
    "**o `reiniciou` normaliza mesmo quando o salto e grande**",
    "**a reconciliacao desiste, e nao reporta o tecto como medicao**",
    # KAM-023, revisao 0013: a marca, o evento e o isolamento.
    "**marca, guarda o codigo, e o `channel.updated` cai no outbox**",
    "**uma segunda marca nao emite outro evento**",
    "**um motivo diferente nao sobrepoe o primeiro**",
    "**um statuses sem codigo nao mete `NULL` no conjunto**",
    "**duas marcas em paralelo: um evento e nao dois**",
    "**levantar exige o motivo certo**, e emite",
    "**com o contexto de A, o canal de B nao se marca** (X-03)",
    "**o `event_id` ausente nao se cala**",
    "**dois incrementos em paralelo na travessia: +2 e UM aviso**",
    "**1.200 entregas dao contador 1.200** — contra a coluna, nao contra um Map",
    "**tres `delivered` do mesmo wamid: contador +1**",
    "**o mes virado le `0` sem escrever nada** — o defeito que custava dinheiro",
    "**com o contexto de A, o contador de B nao se le**",
    "**com o contexto de A, o contador de B nao se escreve**",
    "**a janela ignora o que ainda nao tem destino**",
    "**a reconciliacao le o `pricing` jsonb e mede as duas divergencias**",
    "**uma entrega de outro mes nao entra, e a fronteira e a de Luanda**",
    # KAM-021. As duas primeiras sao as que **so** uma base prova — a corrida
    # pela chave unica e a unicidade composta com o `tenant_id` —, e as duas do
    # privilegio sao a forma mais forte de prova que esta suite tem: nao
    # afirmam o que o codigo faz, afirmam o que nenhum codigo pode fazer.
    "**dois eventos iguais em paralelo: uma linha e um evento**",
    "**a mesma chave em dois tenants da duas linhas**",
    "**o kamba_app nao tem UPDATE em channel_quality_log**",
    "**nem DELETE**, e e a mesma razao",
    "**o SELECT e o INSERT, esses, existem**",
    "**um canal restrito por payment_method nao se repoe com GREEN**",
    "**o bruto fica no registo e o canonico no canal**",
    "**um valor que a Meta inventar fica registado e nao falha**",
    "**o RED restringe e escreve o motivo na mesma instrucao**",
    "**um RED repetido com chave nova nao e uma transicao nova**",
    "**o YELLOW nao restringe, e marca os templates aprovados**",
    "**um evento fora dos quatro e recusado pela base**",
    "**um channel_id que nao e do tenant nao casa a FK composta**",
    "com o contexto de A, as transicoes de B nao aparecem",
    "com o contexto de A, o canal de B nao se restringe",
    "**as 24 h sao moveis e nao a meia-noite de Luanda**",
    "**uma queued nao conta**: a nossa fila ainda a tem em mao",
    "**200 unicos com TIER_250 dao 0,8 e avisam** — a letra do criterio",
    "**o tecto de numeros tem de ser positivo, e a base morde**",
    "**o template pausa pelo idioma exacto, e nao por prefixo**",
    "**um account_alerts registra o texto e nao muda o estado**",
    "**dois RED com chaves diferentes em paralelo: uma transicao e um evento**",
    "**um canal ativo ja marcado por payment_method mantem a marca ao restringir**",
    "**com o tenant e o canal ativos, o template sai**: o controlo",
    "**com o canal restrito por qualidade, um template recusa com STATE_REFUSED**",
    "**e uma service dentro da janela continua a sair**: a matriz nao e um corte",
    # KAM-021, a porta 5 do adapter. A primeira entrou porque a prova por
    # mutacao mostrou que **nenhum** teste ligava a porta a responder `null`: a
    # recusa estava escrita e nada a prendia.
    "**um canal que a porta nao encontra nao envia**, e nao chama nada",
    "**sem a porta ligada, envia como antes do KAM-021**",
    "**um par de estados que a matriz recusa nao envia**",
    # KAM-022. As que **so** uma base prova: a corrida pela unicidade da prova,
    # a vista a respeitar a RLS de quem a consulta, a FK composta, e o `42501`
    # de um `UPDATE` que nao existe — com a metade positiva, sem a qual as
    # negativas passavam por uma concessao em falta por inteiro.
    "**sem consentimento: 1 aviso, 0 AGR, e a linha fica em outbound_messages**",
    "**a contagem de avisos vem da base, pelo prefixo da chave**",
    "**ao terceiro, passa a uma pessoa e nao envia aviso** (criterio 3)",
    "**grava a prova, autoriza o AGR, e a mensagem seguinte segue sem escrever**",
    "**o mesmo botao duas vezes: uma linha** (a prova e a mesma)",
    "**dois cliques em paralelo: uma linha e um evento**",
    "**a prova guardada e a que se recalcula**: reprodutivel (criterio 7)",
    "**grava a revogacao de marketing e pausa, sem tocar na transacao**",
    "**uma versao com data futura nao vigora**",
    "**subir a versao obriga a re-avisar quem ja tinha consentido**",
    "**duas provas do mesmo trio: o estado e o da ultima**",
    "**sem versao vigente nao envia nada e nao autoriza**",
    "**a vista nao mostra o estado de B com o contexto de A**",
    "**uma prova de A nao pode apontar para um contacto de B** (FK composta)",
    "**o kamba_app nao tem UPDATE em consent_event**",
    "**nem DELETE**, e e a mesma razao",
    "**nem escreve o texto do aviso**: quem publica uma versao e operacao",
    "**o SELECT e o INSERT na prova, esses, existem**",
    # KAM-022, de `tests/consentimento.test.ts` (sem base): a matriz e a
    # propriedade do criterio 4, que e a asserção central do ticket.
    "**0 invocacoes do AGR sem consentimento valido anterior**",
    "**as dezoito celulas**, uma a uma",
    "**as oito variantes dos Testes Requeridos**",
    "**duas accoes das seis, e so duas**",
    "**o separador impede a colisao por deslocamento**",
    # KAM-016. Cada uma da a letra de um criterio, e as cinco primeiras sao as
    # que **so** uma base prova: a corrida pelas duas chaves unicas, a reversao
    # da transaccao do 409, os 81 pares contra o `CHECK` do dominio, os tres
    # sitios onde se leem os «0 recursos orfaos», e a contagem a atravessar
    # tenants.
    "duas abertas concorrentes do mesmo par dao 1 linha",
    "a unicidade global morde, e a transaccao nao deixa nada atras",
    "os dezesseis pares escrevem, e um compare-and-set desactualizado nao",
    "a falha injectada no passo 4 nao deixa canal, token nem subscricao",
    "atravessa tenants, que e o que o limite da Meta mede",
    "o token em claro nao esta em coluna nenhuma da base",
    "o kamba_app nao insere nem altera: o privilegio nem existe",
    "sem conclusao no prazo passa a abandonado, e so o iniciado passa",
    # E as de unidade que dao a letra do criterio 1 e do 6: a procura de v2/v3
    # no proprio codigo, e a matriz inteira.
    "o codigo nao referencia v2 nem v3 do Embedded Signup",
    "exactamente dezesseis pares passam, e os outros 65 nao",
    "um criptograma copiado para outro tenant nao abre",
    "a rotacao da KEK nao perde os tokens antigos",
    # E a do cliente da Graph que fixa a exposicao declarada do `graph.ts`.
    "o code e o client_secret vao na consulta, como a Meta documenta",
)

#: Os ficheiros do modulo. A cobertura mede-se em **cada um**.
#:
#: O `cliente.ts` **nao** esta aqui, e nao e esquecimento: a parte dele que
#: pode errar em silencio — a forma do corpo, a leitura do `error.code`, o
#: `Retry-After` — tem bateria propria no gate 4, com o `fetch` por porta; o que
#: resta e a chamada de rede em si, e esta suite usa o `GraphFalso` por porta e
#: nao passa por ela. Medi-lo aqui dava-lhe uma cobertura que diria so que o
#: ensaio nao abre socket. E o mesmo caso do `chr/fila.ts` (KAM-014).
FICHEIROS_DO_MODULO = (
    "adapter.ts",
    "consultas.ts",
    "contrato.ts",
    "decisao.ts",
    "estados.ts",
    "limites.ts",
    "metricas.ts",
    "tarifas.ts",
    "index.ts",
)

#: As quatro tarifas, em micro-dolares, como `config/meta_rates.yaml` as declara.
#:
#: Esta suite compara o YAML com as constantes de `src/outbound/tarifas.ts`
#: **como texto**, e e o unico sitio onde as duas fontes se confrontam. A razao
#: de serem duas esta no modulo: o YAML e o que uma pessoa le e o que o KAM-023
#: vai ler em Python, e nao ha leitor de YAML em `packages/core-ts`.
TARIFAS_ESPERADAS = {
    "service": 4000,
    "utility": 4000,
    "authentication": 4000,
    "marketing": 22500,
}


def _cobertura(lcov: str) -> dict[str, tuple[int, int]]:
    """ficheiro de `src/outbound/` -> (linhas cobertas, linhas encontradas)."""
    medidas: dict[str, tuple[int, int]] = {}
    actual = None
    cobertas = encontradas = 0
    for linha in lcov.splitlines():
        if linha.startswith("SF:"):
            actual = linha[3:].replace("\\", "/")
            cobertas = encontradas = 0
        elif linha.startswith("DA:") and actual is not None:
            _, execucoes = linha[3:].split(",")[:2]
            encontradas += 1
            cobertas += int(execucoes) > 0
        elif linha == "end_of_record" and actual is not None:
            if "/src/outbound/" in f"/{actual}":
                medidas[actual.rsplit("/", 1)[-1]] = (cobertas, encontradas)
            actual = None
    return medidas


class TestTarifas(unittest.TestCase):
    """O `config/meta_rates.yaml` e as constantes dizem o mesmo.

    Nao precisa de base. Esta aqui e nao no gate 4 porque o ficheiro de tarifas
    e YAML e o unico leitor de YAML do repositorio e Python — e a paridade entre
    as duas fontes e exactamente o que impede que divirjam em silencio.
    """

    @classmethod
    def setUpClass(cls) -> None:
        cls.yaml = load_file(node.RAIZ / "config" / "meta_rates.yaml")
        cls.ts = (
            node.RAIZ / "packages" / "core-ts" / "src" / "outbound" / "tarifas.ts"
        ).read_text(encoding="utf-8")

    def test_o_yaml_declara_as_quatro_tarifas_em_micro_dolares_inteiros(self) -> None:
        por_categoria = {t["categoria"]: t["usd_micro"] for t in self.yaml["tarifas"]}
        self.assertEqual(por_categoria, TARIFAS_ESPERADAS)
        for categoria, valor in por_categoria.items():
            with self.subTest(categoria=categoria):
                self.assertIsInstance(valor, int, "o §2 proibe virgula flutuante")

    def test_as_constantes_de_typescript_dizem_o_mesmo(self) -> None:
        """Compara como **texto**: e o que um teste de paridade pode afirmar.

        Sem isto, as duas fontes divergiam na primeira vez que a Meta mudasse
        uma tarifa e alguem tocasse so numa.
        """
        for categoria, valor in TARIFAS_ESPERADAS.items():
            with self.subTest(categoria=categoria):
                # `4_000` com separador, que e como o TypeScript as escreve.
                esperado = f"{categoria}: {valor:_}".replace("_", "_")
                self.assertIn(
                    esperado,
                    self.ts,
                    f"{categoria} nao aparece como {esperado} em tarifas.ts",
                )

    def test_a_zona_e_a_data_batem(self) -> None:
        self.assertEqual(self.yaml["zona"], "rest_of_africa")
        self.assertIn('ZONA = "rest_of_africa"', self.ts)
        self.assertEqual(self.yaml["efectivas_em"], "2026-10-01")
        self.assertIn('EFECTIVAS_EM = "2026-10-01"', self.ts)

    def test_a_cadencia_de_revisao_e_declarada_como_proposta(self) -> None:
        """E **proposta** e nao CONFIRMADO, e o ficheiro tem de o dizer.

        O `docs/tecnica/01` §8.4 diz de si mesmo «calendario a confirmar» e o
        `E1` §1 diz que o «1.o dia do trimestre» vem de resumo de pesquisa. As
        tarifas sao CONFIRMADO; a frequencia com que mudam nao e, e marcar as
        duas da mesma maneira era promover um INDICIO a facto — o defeito mais
        comum deste repositorio.
        """
        self.assertEqual(self.yaml["estado_das_tarifas"], "CONFIRMADO")
        self.assertEqual(self.yaml["revisao"]["estado"], "proposta")

    def test_a_unidade_esta_declarada_e_o_factor_e_um_milhao(self) -> None:
        self.assertEqual(self.yaml["unidade"], "micro_usd")
        self.assertEqual(self.yaml["micro_usd_por_usd"], 1_000_000)
        self.assertIn("MICRO_USD_POR_USD = 1_000_000", self.ts)


class TestModuloDaSaida(ComBase):
    """Corre os testes em Node **uma vez**, e depois olha para o que ficou."""

    @classmethod
    def setUpClass(cls) -> None:
        super().setUpClass()
        cls.saida = Path(tempfile.mkdtemp(prefix="kamba-outbound-"))
        cls.execucao = node.correr(
            [
                "--test",
                # Um ficheiro de cada vez: o ensaio de base conta linhas de
                # `outbound_messages` do tenant inteiro e o `GraphFalso` conta
                # chamadas num contador unico — dois ficheiros em paralelo
                # veriam as contagens um do outro.
                "--test-concurrency=1",
                "--experimental-test-coverage",
                "--test-reporter=tap",
                "--test-reporter-destination=stdout",
                "--test-reporter=lcov",
                "--test-reporter-destination={saida}",
                *FICHEIROS,
            ],
            cls.saida / "outbound.lcov",
        )
        cls.tap = cls.execucao.stdout
        cls.escrito = cls.execucao.stdout + cls.execucao.stderr

    @classmethod
    def tearDownClass(cls) -> None:
        shutil.rmtree(cls.saida, ignore_errors=True)
        super().tearDownClass()

    @classmethod
    def _falhas_do_tap(cls) -> str:
        """As linhas `not ok` e o que vem com cada uma, so.

        A mesma funcao do `tests_chr`, e pela mesma razao medida la: o relatorio
        de cobertura ocupa milhares de linhas no fim da saida, e um
        `escrito[-6000:]` na mensagem de falha mostrava **so** isso — o
        diagnostico ficava de fora.
        """
        linhas = cls.escrito.splitlines()
        partes: list[str] = []
        for indice, linha in enumerate(linhas):
            if re.match(r"^\s*not ok \d+ - ", linha):
                partes.append("\n".join(linhas[indice : indice + 30]))
        resumo = [l for l in linhas if re.match(r"^# (tests|pass|fail) \d+$", l)]
        return "\n\n".join([*partes, " | ".join(resumo)]) or cls.escrito[-4000:]

    def test_os_testes_da_saida_passam(self) -> None:
        """As falhas do TAP entram na mensagem: e o que se vai ler."""
        self.assertEqual(
            self.execucao.returncode,
            0,
            f"node --test saiu com {self.execucao.returncode}:\n"
            f"{self._falhas_do_tap()}",
        )

    def test_nenhum_teste_foi_saltado(self) -> None:
        """Num gate, saltar e falhar — a mesma regra do `correr_suite.py`."""
        saltados = re.findall(r"^# skip (\d+)$", self.tap, re.M)
        self.assertEqual(
            [int(n) for n in saltados] or [0], [0], f"TAP:\n{self.tap[-3000:]}"
        )

    def test_os_grupos_de_base_de_dados_correram_todos(self) -> None:
        """Um grupo que desapareca e uma propriedade que deixou de se provar."""
        for grupo in GRUPOS:
            with self.subTest(grupo=grupo):
                self.assertIn(grupo, self.tap)

    def test_os_testes_obrigatorios_passaram(self) -> None:
        """Pelo nome, e com `ok` a frente: a letra de cada criterio."""
        for nome in TESTES_OBRIGATORIOS:
            with self.subTest(teste=nome):
                self.assertRegex(self.tap, rf"(?m)^\s*ok \d+ - {re.escape(nome)}$")

    def test_a_cobertura_do_modulo_e_pelo_menos_a_do_estrato(self) -> None:
        """O gate 4 nao tem base de dados; a cobertura de `src/outbound/` mede-se aqui.

        O limiar e **lido** de `ci/thresholds.yaml`, do estrato `restante`, e
        nao escrito aqui: dois numeros em dois sitios divergem.

        **E `restante` e nao `critico`, e isso e uma decisao escrita.** Os quatro
        padroes que entraram no estrato `critico` (`logger`, `eventos/consumo`,
        `ten`, `chr`) entraram porque o DoD do ticket respectivo exigia >= 90% e
        aquele estrato e o unico mecanismo que o impoe. O DoD do KAM-015 diz
        «cobertura >= limiar», sem numero — e alterar `ci/thresholds.yaml` pede
        **dois revisores** (o proprio ficheiro o diz, e o DoD do KAM-002
        tambem). Nao se alarga um ficheiro de limiares para marcar uma caixa que
        nao pede o numero.
        """
        lcov = self.saida / "outbound.lcov"
        self.assertTrue(lcov.is_file(), f"nao houve LCOV:\n{self.escrito[-3000:]}")
        medidas = _cobertura(lcov.read_text(encoding="utf-8"))
        limiares = load_file(node.RAIZ / "ci" / "thresholds.yaml")
        minimo = next(
            int(e["minimo_linhas"])
            for e in limiares["estratos"]
            if e["nome"] == "restante"
        )
        em_falta = [f for f in FICHEIROS_DO_MODULO if f not in medidas]
        self.assertEqual(
            em_falta, [], f"sem medida: {em_falta}; medidos: {sorted(medidas)}"
        )
        for ficheiro in FICHEIROS_DO_MODULO:
            cobertas, encontradas = medidas[ficheiro]
            with self.subTest(ficheiro=ficheiro):
                if encontradas == 0:
                    continue
                percentagem = cobertas * 100 // encontradas
                print(f"    cobertura {ficheiro}: {percentagem}% ({cobertas}/{encontradas})")
                self.assertGreaterEqual(
                    percentagem,
                    minimo,
                    f"{ficheiro}: {percentagem}% < {minimo}% "
                    f"({cobertas}/{encontradas} linhas)",
                )
