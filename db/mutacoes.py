"""Prova por mutacao dos gates verificados por suite, uma alteracao por execucao.

    python db/mutacoes.py [python] [filtro] [--fatia i/n]

Comecou nos gates de base de dados (6 e 8) e e ainda ai que esta a maior parte
da lista; desde o KAM-131 corre tambem as duas baterias do **gate 9**, que nao
levantam base de dados nenhuma (`SUITES_DE_TOOLS`).

O primeiro argumento e o Python que tem as dependencias das migracoes (por
omissao, o que corre este ficheiro). O segundo filtra: o nome de uma suite
(`tests`, `tests_identidade`, `tests_isolamento`, `tests_eventos_consumo`,
`tests_ten`, `gate9`, `gate9_ci`), o nome exacto de uma mutacao, ou um
**excerto** do nome (`guarda:`, `resolvedor`, `downgrade da 0002`,
`identidade:`, `revisao 0007:`, `KAM-131`), sensivel a maiusculas.

As mutacoes de `tests_identidade` (KAM-008) alteram o modulo TypeScript de
`packages/core-ts`, que a copia passa a levar. Os `node_modules` **nao** vao na
copia: a suite vai busca-los a este repositorio (`KAMBA_RAIZ_NODE_MODULES`), pelo
que e preciso te-los instalados aqui (`pnpm install --frozen-lockfile`).

**Quando basta o filtro, e quando nao.** Quem so **acrescenta** mutacoes e
testes corre as novas. A lista inteira corre-se sempre que o diff toque num
teste que ja la estava **ou num ficheiro que alguma mutacao altera** (as
revisoes, `rls.py`, `bootstrap.py`, `fluxo_piloto.py`, os *helpers*, o
catalogo): uma mutacao antiga deixa de valer quando o codigo mutado muda.

    python db/mutacoes.py --aplicaveis

confirma, sem Docker e em segundos, que o texto de **todas** as mutacoes ainda
existe exactamente uma vez no ficheiro alvo. Corre-se sempre, mesmo quando se
filtra: e o que apanha uma mutacao antiga que deixou de se aplicar.

As mutacoes correm **em paralelo** — cada uma levanta o seu proprio PostgreSQL
descartavel, numa porta escolhida pelo Docker, pelo que nao se pisam. O numero
de execucoes simultaneas vem de `KAMBA_MUTACOES_PARALELO` (por omissao 8; `1`
repoe a execucao em serie). A ordem do relatorio e a da lista, nao a de chegada.

Paralelismo tem um preco, e esta pago: com a maquina a esgotar ligacoes ou a
esperar por um trinco, a suite falha por **carga** e nao por a mutacao ter sido
apanhada. Uma falha dessas contava como «apanhada» e dava a prova por feita sem
nenhum teste ter mordido. `SINAIS_DE_CARGA` nomeia-as, e cada uma conta como
`PROVA INVALIDA` — que faz o corredor sair diferente de zero, como uma
sobrevivente. Subir o paralelismo nunca pode tornar a prova mais facil.

`--fatia i/n` corre so a i-esima de n fatias da lista escolhida. E o que torna a
prova completa viavel fora desta maquina: a tarefa nocturna do GitHub
(`.github/workflows/mutacoes.yaml`) reparte a lista por varios *runners*, cada
um com a sua fatia, em vez de uma execucao de horas num so. Uma fatia vazia e
erro, nao uma fatia limpa.

Um teste que passa nao prova que morde. Isto prova: copia `db/` e
`libs/py-core/` para um directorio temporario, aplica **uma** alteracao
deliberadamente errada, corre o gate 8 nessa copia e exige que ele falhe. O
repositorio nao e tocado.

Nao faz parte do gate: e uma execucao da suite por mutacao. Corre-se
quando se mexe nos testes do gate 8 ou na revisao, e o resultado regista-se no
bloco do ticket. Uma mutacao que **sobreviva** e um teste em falta — e foi
assim que esta lista nasceu: a revisao adversarial do KAM-003 mostrou cinco
alteracoes que deixavam os 75 testes de entao verdes (`GRANT kamba_batch TO
kamba_app`, `ON DELETE CASCADE`, `NOT NULL` retirado, privilegios por omissao,
uma coluna de contacto em claro). Estao todas aqui, e sao todas apanhadas.

Uma mutacao cujo texto ja nao exista no ficheiro reporta `MUTACAO NAO
APLICAVEL` e conta como falha: uma lista de mutacoes que deixou de se aplicar e
uma prova que deixou de provar.
"""
import concurrent.futures
import os
import re
import shutil
import subprocess
import sys
import tempfile
from pathlib import Path

RAIZ = Path(__file__).resolve().parents[1]
#: O Python que corre o gate na copia. `main()` substitui-o pelo do argumento.
PY = sys.executable
REV = "db/migrations/versions/0001_schema_platform.py"
GUARDA = "libs/py-core/src/kamba_core/fluxo_piloto.py"
BOOT = "db/bootstrap.py"
RLS = "db/rls.py"
REV2 = "db/migrations/versions/0002_rls_por_tenant.py"
GUARD_PY = "libs/py-core/src/kamba_core/tenant_guard/__init__.py"
CATALOGO = "db/tests_isolamento/catalogo.py"
ISOLAMENTO = "tests_isolamento"
REV3 = "db/migrations/versions/0003_identidade_de_contacto.py"
IDENTIDADE = "tests_identidade"
ID_CHAVES = "packages/core-ts/src/identity/chaves.ts"
ID_CRIPTO = "packages/core-ts/src/identity/cripto.ts"
ID_SQL = "packages/core-ts/src/identity/consultas.ts"
ID_SERVICO = "packages/core-ts/src/identity/contactos.ts"
ID_SUITE = "db/tests_identidade/test_modulo_de_identidade.py"
# ------------------------------------------------------------------- KAM-131
HIST = "tools/scan_secrets/historia.py"
SEC_CLI = "tools/scan_secrets/cli.py"
CI_YAML = ".github/workflows/ci.yaml"
MAKEFILE = "Makefile"
GATE9 = "gate9"
GATE9_CI = "gate9_ci"
#: KAM-028: a bateria do *lint* dos esquemas de tool, no mesmo pacote que o
#: `GATE9_CI` e noutro ficheiro — as duas medem coisas diferentes do `lint_arch`.
TOOL_SCHEMA = "lint_tool_schema"
#: KAM-158: o varredor das contagens em prosa. Corre-se `test_scan.py` e nao a
#: bateria inteira: o `test_cli.py` tem um caso que afirma sobre o repositorio.
CONTAGENS = "contagens"
#: KAM-030.
LLM_CONFIG = "llm_config"
PIP_NA_BUILD = "lint_pip_na_build"
COSIGN = "cosign"

#: As baterias de `tools/` que esta prova sabe correr: `(pacote, padrao)`.
#: Nao levantam base de dados nenhuma — o gate 9 nao tem base de dados — e por
#: isso correm em segundos.
#:
#: Corre-se o ficheiro de testes do ticket e nao a bateria inteira do pacote: as
#: outras baterias de `tools/` afirmam coisas sobre o **repositorio** (a arvore
#: seguida pelo git, a estrutura de pastas) que a copia nao e, e uma linha de
#: base vermelha nao prova nada.
#: KAM-007: o gate 7 dos contratos de evento. Corre a bateria **inteira** — ao
#: contrario das outras tres — porque nenhum dos seus ficheiros afirma coisas
#: sobre a arvore seguida pelo git: o `test_catalogo_e_cli.py` le
#: `contratos/eventos/`, que a copia leva.
CONTRATOS = "contratos"

SUITES_DE_TOOLS = {
    GATE9: ("scan_secrets", "test_historia.py"),
    GATE9_CI: ("lint_arch", "test_ci_gate9.py"),
    # KAM-028: a bateria do *lint* dos esquemas de tool. Entrada propria e nao
    # a do `GATE9_CI` porque essa corre **um** ficheiro, e as duas medem coisas
    # diferentes do mesmo pacote.
    TOOL_SCHEMA: ("lint_arch", "test_tool_schema.py"),
    CONTAGENS: ("lint_contagens", "test_scan.py"),
    CONTRATOS: ("contract_diff", "test_*.py"),
    # KAM-030: o gerador da configuracao do proxy, o leitor de `RUN pip install`
    # dos Dockerfiles e a escolha da forma do `cosign verify`. Entradas proprias
    # e nao a do `GATE9_CI`, pela razao que o KAM-028 escreveu para o
    # `TOOL_SCHEMA`: essa corre **um** ficheiro, e estas medem coisas diferentes
    # de pacotes diferentes.
    LLM_CONFIG: ("llm_config", "test_llm_config.py"),
    PIP_NA_BUILD: ("lint_arch", "test_pip_na_build.py"),
    COSIGN: ("supply_chain", "test_cosign.py"),
}
#: O leitor de YAML (KAM-136). As duas suites leem por ele as listas de
#: excepcoes de `ci/` e o limiar do estrato `critico`.
CONT_SCAN = "tools/lint_contagens/scan.py"
#: KAM-007: os modulos do gate 7 e um dos contratos, para as mutacoes morderem
#: tanto no classificador como no que ele le.
CD_DIFF = "tools/contract_diff/diff.py"
CD_PII = "tools/contract_diff/pii.py"
CD_GERAR = "tools/contract_diff/gerar.py"
CD_EXEMPLOS = "tools/contract_diff/exemplos.py"
CONTRATO_PAY_MANUAL = "contratos/eventos/payment.manual_confirmed/v1.schema.json"
CONTRATO_ORDER_PAID = "contratos/eventos/order.paid/v1.schema.json"
KYAML = "tools/kamba_yaml.py"
#: KAM-005: a revisao do outbox e os modulos de eventos em TypeScript.
REV4 = "db/migrations/versions/0004_outbox_e_eventos.py"
EVENTOS = "tests_eventos"
EV_ENVELOPE = "packages/core-ts/src/eventos/envelope.ts"
EV_PII = "packages/core-ts/src/eventos/pii.ts"
EV_PARTICAO = "packages/core-ts/src/eventos/particao.ts"
EV_CONSULTAS = "packages/core-ts/src/eventos/consultas.ts"
EV_PUBLICADOR = "packages/core-ts/src/eventos/publicador.ts"
EV_FILAS = "packages/core-ts/src/eventos/filas_bullmq.ts"
#: KAM-006: a revisao do consumo e da DLQ, e os modulos do consumidor.
REV5 = "db/migrations/versions/0005_consumo_dlq.py"
CONSUMO = "tests_eventos_consumo"
EV_CONSUMO = "packages/core-ts/src/eventos/consumo.ts"
EV_TRABALHO = "packages/core-ts/src/eventos/trabalho.ts"
EV_DLQ = "packages/core-ts/src/eventos/dlq.ts"
EV_RECON = "packages/core-ts/src/eventos/reconciliador.ts"
EV_TRABALHADOR = "packages/core-ts/src/eventos/trabalhador_bullmq.ts"
EV_ACCOES = "packages/core-ts/src/eventos/accoes.ts"
#: KAM-012: a revisao do registo de auditoria e o verificador da cadeia.
#:
#: As mutacoes da cadeia correm contra a suite `tests`, e **nao** contra a de
#: carga: as mil insercoes concorrentes custam meio minuto cada, e uma mutacao
#: que a cadeia partida ja faz falhar em `tests` nao precisa de as pagar. A de
#: carga existe para provar a concorrencia uma vez, no gate.
REV6 = "db/migrations/versions/0006_audit_log.py"
AUDITORIA = "db/auditoria.py"
#: KAM-009: a revisao do consumo de limites e a suite que a prova.
REV7 = "db/migrations/versions/0007_ten_uso_e_limites.py"
TEN = "tests_ten"

#: KAM-014: o CHR. A revisao das conversas, os ficheiros do modulo que podem
#: errar em silencio, e a suite que os prova.
#:
#: **A `0008` entra aqui e nao no KAM-013**, que nao deixou mutacao nenhuma: o
#: dominio de `unrouted_events.motivo` passou a ter os dois motivos do
#: encaminhamento, e o `CHECK` e o que impede o CHR de escrever um motivo que
#: ninguem declarou. Retirar um valor da tupla faz a quarentena falhar **na
#: insercao** — isto e, o evento deixa de deixar linha — e sem mutacao isso so
#: se via no dia em que acontecesse.
REV8 = "db/migrations/versions/0008_entrada_de_canal.py"
REV9 = "db/migrations/versions/0009_conversas.py"
REV10 = "db/migrations/versions/0010_saida_de_canal.py"
#: A suite da saida (KAM-015). E a mais **estreita** que apanha o que a `0010` e
#: o modulo `src/outbound/` prometem: a unicidade por tenant, a monotonia contra
#: concorrencia e o custo que sai do `pricing`.
SAIDA = "tests_outbound"
SAIDA_SQL = "packages/core-ts/src/outbound/consultas.ts"
SAIDA_ESTADOS = "packages/core-ts/src/outbound/estados.ts"
SAIDA_LIMITES = "packages/core-ts/src/outbound/limites.ts"
SAIDA_TARIFAS = "packages/core-ts/src/outbound/tarifas.ts"
SAIDA_DECISAO = "packages/core-ts/src/outbound/decisao.ts"
SAIDA_ADAPTER = "packages/core-ts/src/outbound/adapter.ts"
#: A suite do handoff (KAM-019). E a mais **estreita** que apanha o que a
#: `0011` e o modulo `src/hnd/` prometem: a idempotencia da chave derivada, a
#: unicidade da conta no provedor e a RLS das duas tabelas.
HANDOFF = "tests_handoff"
REV11 = "db/migrations/versions/0011_handoff.py"
HND_ASSINATURA = "packages/core-ts/src/hnd/assinatura.ts"
HND_EVENTOS = "packages/core-ts/src/hnd/eventos.ts"
HND_ESTADOS = "packages/core-ts/src/hnd/estados.ts"
HND_SQL = "packages/core-ts/src/hnd/consultas.ts"
HND_CHATWOOT = "packages/core-ts/src/hnd/chatwoot.ts"
HND_RESPOSTA = "packages/core-ts/src/hnd/resposta.ts"
HND_PROVEDOR = "packages/core-ts/src/hnd/provedor.ts"
MEDIA = "tests_media"
REV12 = "db/migrations/versions/0012_media.py"
MED_CLASSES = "packages/core-ts/src/med/classes.ts"
MED_SQL = "packages/core-ts/src/med/consultas.ts"
MED_PIPELINE = "packages/core-ts/src/med/pipeline.ts"
CHR = "tests_chr"
CHR_CANAL = "packages/core-ts/src/chr/canal.ts"
CHR_SQL = "packages/core-ts/src/chr/consultas.ts"
CHR_FLUXO_B = "packages/core-ts/src/chr/fluxo_b.ts"
CHR_MODULO = "packages/core-ts/src/chr/chr.ts"
CHR_CONVERSAS = "packages/core-ts/src/chr/conversas.ts"
CHR_INVOCACAO = "packages/core-ts/src/chr/invocacao.ts"
# -------------------------------------------------------------- KAM-023
#: **`FT_` e nao `MED_`, e a razao e um defeito que o merge produziu.** A
#: primeira versao destas constantes chamava-se `MED_*`, e o KAM-020 — que
#: fundiu entretanto — ja tinha `MED_SQL` para `src/med/consultas.ts`. O
#: `git merge` juntou as duas listas sem conflito e a minha, por vir depois,
#: **sombreou** a dele: duas mutacoes da midia passaram a apontar para o
#: ficheiro do free tier. Nenhum teste o via; o `--aplicaveis` apanhou-o em
#: segundos, que e exactamente para isso que ele corre em cada PR.
#: O contador do *free tier*. A suite e a `tests_outbound`: o modulo escreve
#: `tenant_channels`, le `outbound_messages` e depende de
#: `platform.ten_periodo`, e as tres coisas vivem na base que ela levanta.
FT_SQL = "packages/core-ts/src/metering/consultas.ts"
FT_CUSTO = "packages/core-ts/src/metering/custo.ts"
FT_METRICAS = "packages/core-ts/src/metering/metricas.ts"
FT_MODULO = "packages/core-ts/src/metering/metering.ts"
REV13 = "db/migrations/versions/0013_restricao_de_canal.py"

# -------------------------------------------------------------- KAM-021
#: A gestao de canal. A suite e a `tests_outbound` pela mesma razao que o
#: contador do KAM-023 — escreve `tenant_channels`, le `outbound_messages` — e
#: por uma quarta que so vale para ela: o criterio 9 prova-se de ponta a ponta,
#: com a `Saida` do KAM-015 a recusar um template num canal que a bateria da
#: qualidade acabou de restringir, e isso precisa do `GraphFalso`.
#:
#: **`QL_` e nao `MED_` nem `FT_`**, e o prefixo escolheu-se depois de procurar:
#: nenhuma outra constante deste ficheiro comeca por `QL_`. A razao e a licao
#: que o `MED_SQL`/`FT_SQL` deixou — um prefixo que colida com o de outro ticket
#: sombreia entradas sem conflito de merge, e nenhum teste o ve.
QL_SQL = "packages/core-ts/src/qualidade/consultas.ts"
QL_DECISAO = "packages/core-ts/src/qualidade/decisao.ts"
QL_CONTRATO = "packages/core-ts/src/qualidade/contrato.ts"
QL_METRICAS = "packages/core-ts/src/qualidade/metricas.ts"
QL_MODULO = "packages/core-ts/src/qualidade/qualidade.ts"
REV14 = "db/migrations/versions/0014_qualidade_de_canal.py"

# -------------------------------------------------------------- KAM-022
#: O consentimento no 1.o contacto. A suite e a `tests_outbound` por uma razao
#: que nao e a dos dois tickets anteriores: a contagem de avisos do criterio 3
#: sai do prefixo da `idempotency_key` de `outbound_messages`, que e a tabela do
#: KAM-015. O resto do que a base prova vive na mesma base e nao precisa de fila
#: nem de Meta falsa.
#:
#: **`CS_` e nao `C_`**, e o prefixo escolheu-se depois de procurar: nenhuma
#: outra constante deste ficheiro comeca por `CS_`. E a licao que o
#: `MED_SQL`/`FT_SQL` deixou — um prefixo que colida com o de outro ticket
#: sombreia entradas sem conflito de merge, e nenhum teste o ve.
CS_SQL = "packages/core-ts/src/consentimento/consultas.ts"
CS_DECISAO = "packages/core-ts/src/consentimento/decisao.ts"
CS_CONTRATO = "packages/core-ts/src/consentimento/contrato.ts"
CS_PARAR = "packages/core-ts/src/consentimento/parar.ts"
CS_PROVA = "packages/core-ts/src/consentimento/prova.ts"
CS_METRICAS = "packages/core-ts/src/consentimento/metricas.ts"
CS_MODULO = "packages/core-ts/src/consentimento/consentimento.ts"
REV15 = "db/migrations/versions/0015_consentimento.py"

# -------------------------------------------------------------- KAM-018
#: Os modos da conversa. A suite e a `tests_modos`, e e **suite propria** e nao a
#: `tests_outbound` dos tres tickets anteriores: a prova destas mutacoes esta no
#: *lock*, na tabela de transicoes e no privilegio da revisao `0016`, e quem as
#: exercita e `db/tests_modos/`, que mede a cobertura de `src/modos/` e tem a
#: lista de testes obrigatorios deste ticket.
#:
#: **`MO_` e nao `M_` nem `MD_`**, e o prefixo escolheu-se depois de procurar:
#: nenhuma outra constante deste ficheiro comeca por `MO_` (o `MED_` da midia e
#: o mais parecido). E a licao que o `MED_SQL`/`FT_SQL` deixou — um prefixo que
#: colida com o de outro ticket sombreia entradas sem conflito de merge, e
#: nenhum teste o ve.
MO_SQL = "packages/core-ts/src/modos/consultas.ts"
MO_TRANSICOES = "packages/core-ts/src/modos/transicoes.ts"
MO_CONTRATO = "packages/core-ts/src/modos/contrato.ts"
MO_GUARDA = "packages/core-ts/src/modos/guarda.ts"
MO_EVENTOS = "packages/core-ts/src/modos/eventos.ts"
MO_MODULO = "packages/core-ts/src/modos/modos.ts"
REV16 = "db/migrations/versions/0016_modos_de_conversa.py"
# -------------------------------------------------------------- KAM-016
#: O onboarding de canal (Embedded Signup v4). A suite e a `tests_outbound`,
#: pela razao que o `FICHEIROS` dela escreve: e a unica do *gate* 8 que monta o
#: `tools/meta-sim`, e tres criterios deste ticket leem-se no servidor falso.
#:
#: **`ON_` e nao `O_`**, e o prefixo escolheu-se depois de procurar: nenhuma
#: outra constante deste ficheiro comeca por `ON_`. E a licao que o
#: `MED_SQL`/`FT_SQL` deixou e que a nota do `CS_SQL` repetiu — um prefixo que
#: colida com o de outro ticket **sombreia** entradas sem conflito de merge, e
#: nenhum teste o ve. Quem integrar o `main` depois disto corre
#: `python db/mutacoes.py --aplicaveis`, que e o unico que apanha.
ON_SQL = "packages/core-ts/src/onboarding/consultas.ts"
ON_CONTRATO = "packages/core-ts/src/onboarding/contrato.ts"
ON_CIFRA = "packages/core-ts/src/onboarding/cifra.ts"
ON_GRAPH = "packages/core-ts/src/onboarding/graph.ts"
ON_MODULO = "packages/core-ts/src/onboarding/onboarding.ts"
ON_METRICAS = "packages/core-ts/src/onboarding/metricas.ts"
ON_ESCRITA = "packages/core-ts/src/secrets/escrita.ts"
REV17 = "db/migrations/versions/0017_onboarding_de_canal.py"

# -------------------------------------------------------------- KAM-017
#: A coexistencia. A suite e a `tests_outbound`, e a razao que so vale para
#: este ticket esta no `FICHEIROS` dela: a regra do criterio 7 — «um echo cujo
#: wamid consta de `outbound_messages` e ignorado» — le a tabela **daquela**
#: suite, e nao ha onde provar isso sem as duas tabelas na mesma base.
#:
#: **`CX_` e nao `CO_` nem `C_`**, e o prefixo escolheu-se depois de procurar:
#: nenhuma outra constante deste ficheiro comeca por `CX_` (o `CS_` do
#: consentimento e o mais parecido, e um `CO_` confundia-se com ele a olho). E a
#: licao que o `MED_SQL`/`FT_SQL` deixou e que as notas do `CS_SQL`, do `MO_SQL`
#: e do `ON_SQL` repetiram — um prefixo que colida com o de outro ticket
#: **sombreia** entradas sem conflito de merge, e nenhum teste o ve. Quem
#: integrar o `main` depois disto corre `python db/mutacoes.py --aplicaveis`,
#: que e o unico que apanha.
CX_SQL = "packages/core-ts/src/coexistencia/consultas.ts"
CX_CONTRATO = "packages/core-ts/src/coexistencia/contrato.ts"
CX_MODULO = "packages/core-ts/src/coexistencia/coexistencia.ts"
CX_METRICAS = "packages/core-ts/src/coexistencia/metricas.ts"
CX_EXPLOSAO = "packages/core-ts/src/entrada/explosao.ts"
REV18 = "db/migrations/versions/0018_coexistencia.py"

# -------------------------------------------------------------- KAM-115
#: O aviso ao dono por canal alternativo. A suite e a **`tests_avisos`**, a
#: propria do ticket, e nao uma emprestada: ela corre as duas baterias — as
#: regras (`tests/avisos.test.ts`) e o ensaio contra a base
#: (`tests_bd/avisos.bd.test.ts`) —, pelo que uma mutacao de regra e uma de SQL
#: provam-se as duas no mesmo corredor. E a primeira suite deste ficheiro em que
#: isso acontece: a `tests_outbound` do KAM-017 teve de ser emprestada porque a
#: regra do `echo` le a tabela daquele ticket.
#:
#: **`AV_` e nao `A_` nem `AD_`**, e o prefixo escolheu-se depois de procurar:
#: nenhuma outra constante deste ficheiro comeca por `AV_`. E a licao que o
#: `MED_SQL`/`FT_SQL` deixou e que as notas do `CS_SQL`, do `MO_SQL`, do
#: `ON_SQL` e do `CX_SQL` repetiram — um prefixo que colida com o de outro
#: ticket **sombreia** entradas sem conflito de merge, e nenhum teste o ve.
AVISOS = "tests_avisos"
AV_SQL = "packages/core-ts/src/avisos/consultas.ts"
AV_CONTRATO = "packages/core-ts/src/avisos/contrato.ts"

#: O AGR (KAM-025). A suite e a **`tests_agr`**, a propria do ticket: e a
#: unica que corre o `pg_advisory_lock` contra um PostgreSQL real, e sem isso
#: metade destas mutacoes nao tem quem as mate.
#:
#: **`AG_` e nao `A_` nem `AGR_`**, e o prefixo escolheu-se depois de procurar:
#: nenhuma outra constante deste ficheiro comeca por `AG_`. E a licao que o
#: `MED_SQL`/`FT_SQL` deixou e que as notas do `CS_SQL`, do `MO_SQL`, do
#: `ON_SQL`, do `CX_SQL` e do `AV_SQL` repetiram — um prefixo que colida com o
#: de outro ticket **sombreia** entradas sem conflito de merge, e nenhum teste
#: o ve.
#:
#: **Sao Python e nao TypeScript**, as primeiras deste ficheiro a mutar codigo
#: de um servico Python. O mecanismo e o mesmo: substitui-se texto no ficheiro
#: e corre-se a suite. O que muda e que a `tests_agr` importa estes modulos
#: directamente (`sys.path` para `services/agr/src`), pelo que a mutacao chega
#: ao que corre sem passar por uma compilacao.
AGR = "tests_agr"
AG_SQL = "services/agr/src/kamba_agr/consultas.py"
AG_TURNO = "services/agr/src/kamba_agr/turno.py"
AG_TRANCAS = "services/agr/src/kamba_agr/trancas.py"
AG_CONTEXTO = "services/agr/src/kamba_agr/contexto.py"
#: KAM-026. O checkpointer e a varredura de retencao.
AG_CHECKPOINTER = "services/agr/src/kamba_agr/checkpointer.py"
AG_RETENCAO = "services/agr/src/kamba_agr/retencao.py"
#: O AgentRegistry (KAM-027). A suite e a **`agr_unit`** — `services/agr/tests`,
#: sem base de dados — e nao a `tests_agr`: nada do que estas mutacoes alteram
#: toca o PostgreSQL, e correr a suite de BD para as provar pagava um contentor
#: por mutacao sem medir nada a mais.
AGR_UNIT = "agr_unit"
AG_REGISTO = "services/agr/src/kamba_agr/registo/__init__.py"
AG_VALIDAR = "services/agr/src/kamba_agr/registo/validar.py"
AG_ESQUEMA = "services/agr/src/kamba_agr/registo/esquema.py"
AG_EGRESSO = "services/agr/src/kamba_agr/egresso.py"
#: A ToolLayer (KAM-028). As que mudam **logica** correm na `agr_unit`
#: (`services/agr/tests`, sem base de dados); as que mudam o que vai para a
#: `tool_audit` correm na `tests_agr`, porque o que as mata e um varrimento
#: contra os dados e nao uma asercao sobre um duplo.
AG_TLS_CAMADA = "services/agr/src/kamba_agr/tls/camada.py"
AG_TLS_CONTEXTO = "services/agr/src/kamba_agr/tls/contexto.py"
AG_TLS_ESPECIFICACOES = "services/agr/src/kamba_agr/tls/especificacoes.py"
AG_TLS_DISJUNTOR = "services/agr/src/kamba_agr/tls/disjuntor.py"
AG_TLS_AUDITORIA = "services/agr/src/kamba_agr/tls/auditoria.py"
AG_TLS_IDEMPOTENCY = "services/agr/src/kamba_agr/tls/idempotency.py"
#: O *lint* do critero 3, que corre no *gate* 2. A suite (`TOOL_SCHEMA`) esta
#: declarada junto das outras de `tools/`, acima.
LA_TOOL_SCHEMA = "tools/lint_arch/tool_schema.py"
#: O gateway de LLM (KAM-030). As que mudam **logica** correm na `agr_unit`
#: (`services/agr/tests`, sem base de dados); as que mudam o DDL ou o que vai
#: para a `dat.llm_call_log` correm na `tests_agr`, porque o que as mata e um
#: `CHECK` do servidor ou a RLS — e nao uma asercao sobre um duplo.
AG_LLM_CLIENTE = "services/agr/src/kamba_agr/llm/cliente.py"
AG_LLM_DESTINOS = "services/agr/src/kamba_agr/llm/destinos.py"
AG_LLM_ERROS = "services/agr/src/kamba_agr/llm/erros.py"
AG_LLM_PRECOS = "services/agr/src/kamba_agr/llm/precos.py"
AG_LLM_REGISTO = "services/agr/src/kamba_agr/llm/registo.py"
#: O validador de citacao (KAM-032). As mutacoes correm na `agr_unit`
#: (`services/agr/tests`, sem base de dados): nada do que elas alteram toca a
#: base, e levantar um contentor por mutacao nao mediria nada a mais.
AG_VAL_NORM = "services/agr/src/kamba_agr/validador/normalizacao.py"
AG_VAL_EXTR = "services/agr/src/kamba_agr/validador/extraccao.py"
AG_VAL_REND = "services/agr/src/kamba_agr/validador/render.py"
AG_VAL_VER = "services/agr/src/kamba_agr/validador/veredicto.py"
REV23 = "db/migrations/versions/0023_llm_call_log.py"
#: O gerador da configuracao do proxy, o leitor de manifestos e o verificador de
#: assinaturas, que o KAM-030 estendeu. As suites estao declaradas junto das
#: outras de `tools/`, acima.
TO_LLM_CONFIG = "tools/llm_config/__init__.py"
LA_MANIFESTS = "tools/lint_arch/manifests.py"
SC_COSIGN = "tools/supply_chain/cosign.py"
AV_DECISAO = "packages/core-ts/src/avisos/decisao.ts"
AV_MODELOS = "packages/core-ts/src/avisos/modelos.ts"
AV_MODULO = "packages/core-ts/src/avisos/avisos.ts"
AV_METRICAS = "packages/core-ts/src/avisos/metricas.ts"
AV_FORNECEDOR = "packages/core-ts/src/avisos/fornecedor.ts"
REV19 = "db/migrations/versions/0019_aviso_ao_dono.py"

#: O corpo da subtransaccao da `ten_consumir`, como a revisao 0007 o escreve:
#: **a chave primeiro, a contagem depois**. A mutacao da ordem precisa do
#: texto inteiro, incluindo o comentario pelo meio, porque nao ha alteracao
#: mais curta que leve uma instrucao de um lado do bloco para o outro — e as
#: posicoes intermedias **nao** sao a mutacao: com o registo da chave entre a
#: contagem e o `IF v_valor IS NULL`, a repeticao continua a bater na
#: unicidade antes de bater no tecto, e a funcao responde o mesmo.
_TEN_ORDEM = """  BEGIN
    INSERT INTO platform.usage_ledger
                (tenant_id, idempotency_key, chave_limite, periodo, quantidade)
         VALUES (p_tenant, p_idempotency_key, p_chave, v_periodo, p_quantidade);

    IF p_quantidade > v_limite THEN
      RAISE EXCEPTION 'tecto' USING ERRCODE = 'KA001';
    END IF;

    INSERT INTO platform.tenant_usage
                (tenant_id, chave_limite, periodo, valor)
         VALUES (p_tenant, p_chave, v_periodo, p_quantidade)
    ON CONFLICT (tenant_id, chave_limite, periodo) DO UPDATE
       SET valor = platform.tenant_usage.valor + p_quantidade,
           actualizado_at = now()
     WHERE platform.tenant_usage.valor + p_quantidade <= v_limite
    RETURNING platform.tenant_usage.valor INTO v_valor;

    -- E aqui que a atomicidade mora: duas transaccoes em conflito na mesma
    -- chave serializam no lock da linha, e a segunda reavalia o `WHERE`
    -- sobre o valor **ja actualizado** pela primeira. Sem linha devolvida, o
    -- tecto recusou.
    IF v_valor IS NULL THEN
      RAISE EXCEPTION 'tecto' USING ERRCODE = 'KA001';
    END IF;
  EXCEPTION"""

#: O mesmo bloco com as duas insercoes trocadas: contar primeiro, registar a
#: chave depois. E o que a docstring da revisao diz que esta errado.
_TEN_ORDEM_TROCADA = """  BEGIN
    IF p_quantidade > v_limite THEN
      RAISE EXCEPTION 'tecto' USING ERRCODE = 'KA001';
    END IF;

    INSERT INTO platform.tenant_usage
                (tenant_id, chave_limite, periodo, valor)
         VALUES (p_tenant, p_chave, v_periodo, p_quantidade)
    ON CONFLICT (tenant_id, chave_limite, periodo) DO UPDATE
       SET valor = platform.tenant_usage.valor + p_quantidade,
           actualizado_at = now()
     WHERE platform.tenant_usage.valor + p_quantidade <= v_limite
    RETURNING platform.tenant_usage.valor INTO v_valor;

    IF v_valor IS NULL THEN
      RAISE EXCEPTION 'tecto' USING ERRCODE = 'KA001';
    END IF;

    INSERT INTO platform.usage_ledger
                (tenant_id, idempotency_key, chave_limite, periodo, quantidade)
         VALUES (p_tenant, p_idempotency_key, p_chave, v_periodo, p_quantidade);
  EXCEPTION"""

#: O registo da chave **fora** da subtransaccao: fica escrito mesmo quando o
#: tecto recusa, e uma segunda tentativa com a mesma chave le-se como
#: repeticao de um consumo que nunca aconteceu.
_TEN_CHAVE_FORA = """  INSERT INTO platform.usage_ledger
              (tenant_id, idempotency_key, chave_limite, periodo, quantidade)
       VALUES (p_tenant, p_idempotency_key, p_chave, v_periodo, p_quantidade);

  BEGIN
    IF p_quantidade > v_limite THEN"""

#: A comparacao da quantidade numa repeticao, que a revisao adversarial
#: obrigou a acrescentar (C1). Sem ela, repetir a chave de um consumo de 1
#: autorizava um pedido de 99 999 999: a funcao respondia «repetido» e quem
#: chama lia «podes».
_TEN_QUANTIDADE = """    IF v_antes IS DISTINCT FROM p_quantidade THEN
      RAISE EXCEPTION
        'ten_consumir: a chave de idempotencia % ja foi usada em % com quantidade % e veio %',
        p_idempotency_key, p_chave, v_antes, p_quantidade
        USING ERRCODE = 'KA002';
    END IF;"""

#: A guarda do relogio (M1): `p_agora` so aponta para outro periodo quando
#: quem chama e `kamba_batch`.
_TEN_RELOGIO = """  IF v_periodo <> platform.ten_periodo(now())
     AND NOT pg_has_role(current_user, 'kamba_batch', 'USAGE') THEN
    RAISE EXCEPTION
      'ten_consumir: p_agora aponta para o periodo % e o corrente e %; so o kamba_batch fixa o relogio',
      v_periodo, platform.ten_periodo(now())
      USING ERRCODE = 'invalid_parameter_value';
  END IF;"""

#: A guarda da chave de idempotencia vazia (m4).
_TEN_CHAVE_VAZIA = """  IF p_idempotency_key IS NULL OR p_idempotency_key ~ '^[[:space:]]*$' THEN
    RAISE EXCEPTION 'ten_consumir: p_idempotency_key nula ou vazia'
      USING ERRCODE = 'check_violation';
  END IF;"""

#: O trigger que torna o contador *append-only* (C3). Em aspas simples
#: triplas porque o texto que ele procura **tem** aspas duplas triplas: e
#: uma instrucao de uma migracao, e as migracoes escrevem SQL assim.
_TEN_TRIGGER = '''    op.execute(
        """
        CREATE TRIGGER tenant_usage_so_sobe
          BEFORE UPDATE ON platform.tenant_usage
          FOR EACH ROW EXECUTE FUNCTION platform.ten_usage_so_sobe()
        """
    )
'''

MUTACOES = [
    ("estado a mais no CHECK de tenants", REV,
     "('onboarding','ativo','restrito','suspenso','encerrado')",
     "('onboarding','ativo','restrito','suspenso','encerrado','pausado')"),
    ("UNIQUE de phone_number_id retirado", REV,
     "CONSTRAINT tenant_channels_phone_number_id_uq UNIQUE\n", "\n"),
    ("ordem do indice trocada", REV,
     "ON platform.tenant_channels (tenant_id, estado)",
     "ON platform.tenant_channels (estado, tenant_id)"),
    ("coluna _enc em text", REV,
     "contacto_negocio_enc     bytea", "contacto_negocio_enc     text"),
    ("timestamp sem fuso", REV,
     "verificado_at            timestamptz,", "verificado_at            timestamp,"),
    ("NOT NULL retirado de origem", REV,
     "origem                  text NOT NULL DEFAULT 'pme'",
     "origem                  text DEFAULT 'pme'"),
    ("omissao de origem = plataforma", REV,
     "origem                  text NOT NULL DEFAULT 'pme'",
     "origem                  text NOT NULL DEFAULT 'plataforma'"),
    ("ON DELETE CASCADE na FK do canal", REV,
     "REFERENCES platform.tenants (id),\n          waba_id",
     "REFERENCES platform.tenants (id) ON DELETE CASCADE,\n          waba_id"),
    ("coluna de contacto em claro acrescentada", REV,
     "          zona                     text,",
     "          zona                     text,\n          contacto_dono            text,"),
    ("CHECK de forma da vertical retirado", REV,
     "CHECK (vertical ~ '^[a-z][a-z0-9_]*$'),", "CHECK (true),"),
    ("DELETE em tenants dado a kamba_app", REV,
     '    op.execute("GRANT UPDATE (limites, ativo) ON platform.entitlements TO kamba_app")',
     '    op.execute("GRANT UPDATE (limites, ativo) ON platform.entitlements TO kamba_app")\n'
     '    op.execute("GRANT DELETE ON platform.tenants TO kamba_app")'),
    ("UPDATE de tipo dado a kamba_app", REV,
     '    op.execute("GRANT UPDATE (limites, ativo) ON platform.entitlements TO kamba_app")',
     '    op.execute("GRANT UPDATE (limites, ativo) ON platform.entitlements TO kamba_app")\n'
     '    op.execute("GRANT UPDATE (tipo) ON platform.tenants TO kamba_app")'),
    ("privilegios por omissao", REV,
     '    op.execute("GRANT UPDATE (limites, ativo) ON platform.entitlements TO kamba_app")',
     '    op.execute("GRANT UPDATE (limites, ativo) ON platform.entitlements TO kamba_app")\n'
     '    op.execute("ALTER DEFAULT PRIVILEGES IN SCHEMA platform GRANT ALL ON TABLES TO kamba_app")'),
    ("SELECT em tenants dado a PUBLIC", REV,
     '    op.execute("GRANT UPDATE (limites, ativo) ON platform.entitlements TO kamba_app")',
     '    op.execute("GRANT UPDATE (limites, ativo) ON platform.entitlements TO kamba_app")\n'
     '    op.execute("GRANT SELECT ON platform.tenants TO PUBLIC")'),
    ("bootstrap: kamba_app membro de kamba_batch", BOOT,
     "        _revogar_pertencas(cursor, feito)\n",
     '        cursor.execute("GRANT kamba_batch TO kamba_app")\n'),
    ("bootstrap: TEMPORARY deixado ao PUBLIC", BOOT,
     '"REVOKE TEMPORARY, CONNECT ON DATABASE %I FROM PUBLIC"',
     '"REVOKE CONNECT ON DATABASE %I FROM PUBLIC"'),
    ("bootstrap: kamba_app com BYPASSRLS", BOOT,
     '"kamba_app": "LOGIN NOSUPERUSER NOCREATEDB NOCREATEROLE NOREPLICATION NOBYPASSRLS"',
     '"kamba_app": "LOGIN NOSUPERUSER NOCREATEDB NOCREATEROLE NOREPLICATION BYPASSRLS"'),
    ("guarda: vertical por igualdade com assistente", GUARDA,
     "\"WHERE vertical NOT IN ('vendedor', 'servicos')\"",
     "\"WHERE vertical = 'assistente'\""),
    ("guarda: sem prova de visibilidade", GUARDA,
     "        if not cursor.fetchone()[0]:", "        if cursor.fetchone() is None:"),
    ("guarda: condicao da origem retirada", GUARDA,
     "\"SELECT count(*) FROM platform.tenant_channels WHERE origem = 'plataforma'\"",
     "\"SELECT count(*) FROM platform.tenant_channels WHERE origem = 'nunca'\""),
    # ---------------------------------------------------------------- KAM-004
    # Cada uma tem de ser apanhada pela suite de isolamento (gate 6).
    ("RLS: politica sem WITH CHECK", RLS,
     'f"USING ({predicado(coluna)}) WITH CHECK ({predicado(coluna)})"',
     'f"USING ({predicado(coluna)})"', ISOLAMENTO),
    ("RLS: ENABLE sem FORCE", RLS,
     '    op.execute(f"ALTER TABLE {alvo} FORCE ROW LEVEL SECURITY")\n    op.execute(\n        f"CREATE POLICY',
     '    op.execute(\n        f"CREATE POLICY', ISOLAMENTO),
    ("RLS: predicado com OR true", RLS,
     """return f"{coluna} = NULLIF(current_setting('{VARIAVEL}', true), '')::uuid\"""",
     """return f"({coluna} = NULLIF(current_setting('{VARIAVEL}', true), '')::uuid OR true)\"""",
     ISOLAMENTO),
    ("RLS: sem contexto ve tudo (COALESCE)", RLS,
     """return f"{coluna} = NULLIF(current_setting('{VARIAVEL}', true), '')::uuid\"""",
     """return f"{coluna} = COALESCE(NULLIF(current_setting('{VARIAVEL}', true), '')::uuid, {coluna})\"""",
     ISOLAMENTO),
    ("RLS: tenants fica de fora", REV2,
     '    rls.enable_tenant_rls("tenants", coluna="id")\n', "", ISOLAMENTO),
    ("resolvedor: politica FOR ALL em vez de FOR SELECT", REV2,
     '"FOR SELECT TO kamba_resolver USING (true)"',
     '"FOR ALL TO kamba_resolver USING (true)"', ISOLAMENTO),
    ("resolvedor: mais uma coluna (token_ref)", REV2,
     '"id", "tenant_id", "phone_number_id", "vertical", "origem", "estado",\n        "channel_mode",',
     '"id", "tenant_id", "phone_number_id", "vertical", "origem", "estado",\n        "channel_mode", "token_ref",',
     ISOLAMENTO),
    ("resolvedor: politica TO PUBLIC", REV2,
     '"FOR SELECT TO kamba_resolver USING (true)"',
     '"FOR SELECT TO PUBLIC USING (true)"', ISOLAMENTO),
    ("helper: set_config de sessao (false)", GUARD_PY,
     """SQL_DEFINIR_CONTEXTO = "SELECT set_config('app.tenant_id', %s, true)\"""",
     """SQL_DEFINIR_CONTEXTO = "SELECT set_config('app.tenant_id', %s, false)\"""",
     ISOLAMENTO),
    ("catalogo: a descoberta ignora o schema platform", CATALOGO,
     'SCHEMAS_DE_SISTEMA = ("pg_catalog", "information_schema", "pg_toast")',
     'SCHEMAS_DE_SISTEMA = ("pg_catalog", "information_schema", "pg_toast", "platform")',
     ISOLAMENTO),
    # ------------------------------------------- KAM-004, revisao adversarial
    # As nove que **sobreviveram** a primeira versao dos testes (ANALISE-07).
    ("resolvedor: GRANT INSERT em tenants e tenant_channels (gate 6)", REV2,
     '    op.execute("GRANT USAGE ON SCHEMA platform TO kamba_resolver")\n',
     '    op.execute("GRANT USAGE ON SCHEMA platform TO kamba_resolver")\n'
     '    op.execute("GRANT INSERT ON platform.tenants, platform.tenant_channels TO kamba_resolver")\n',
     ISOLAMENTO),
    ("resolvedor: GRANT INSERT em tenants e tenant_channels (gate 8)", REV2,
     '    op.execute("GRANT USAGE ON SCHEMA platform TO kamba_resolver")\n',
     '    op.execute("GRANT USAGE ON SCHEMA platform TO kamba_resolver")\n'
     '    op.execute("GRANT INSERT ON platform.tenants, platform.tenant_channels TO kamba_resolver")\n'),
    ("resolvedor: GRANT INSERT so em tenant_channels (gate 6)", REV2,
     '    op.execute("GRANT USAGE ON SCHEMA platform TO kamba_resolver")\n',
     '    op.execute("GRANT USAGE ON SCHEMA platform TO kamba_resolver")\n'
     '    op.execute("GRANT INSERT ON platform.tenant_channels TO kamba_resolver")\n',
     ISOLAMENTO),
    ("resolvedor: GRANT UPDATE (estado) sem politica (gate 6)", REV2,
     '    op.execute("GRANT USAGE ON SCHEMA platform TO kamba_resolver")\n',
     '    op.execute("GRANT USAGE ON SCHEMA platform TO kamba_resolver")\n'
     '    op.execute("GRANT UPDATE (estado) ON platform.tenant_channels TO kamba_resolver")\n',
     ISOLAMENTO),
    # O texto mudou com o KAM-005 (`AND NOT c.relispartition`, que tirou as
    # particoes da descoberta e as passou para `verificar_particoes`). A mutacao
    # continua a ser a mesma: tirar as tabelas particionadas (`'p'`) da
    # descoberta, e a apanha e a contagem do X-05 — o `events_log` e uma delas.
    ("catalogo: a descoberta ignora tabelas particionadas", CATALOGO,
     "WHERE c.relkind IN ('r', 'p') AND NOT c.relispartition ",
     "WHERE c.relkind IN ('r') AND NOT c.relispartition ", ISOLAMENTO),
    # KAM-005: a descoberta de particoes deixa de excluir indices. O
    # `pg_inherits` liga tambem um indice particionado aos seus filhos, e o
    # `pg_attribute` tem linhas para as colunas de um indice: sem o filtro, o
    # X-05 pedia uma politica de RLS **num indice** (medido, e corrigido).
    ("catalogo: a descoberta de particoes apanha indices", CATALOGO,
     "WHERE c.relispartition AND c.relkind IN ('r', 'p') ",
     "WHERE c.relispartition ", ISOLAMENTO),
    ("catalogo: vistas materializadas fora da verificacao", CATALOGO,
     "WHERE c.relkind IN ('v', 'm')", "WHERE c.relkind IN ('v')", ISOLAMENTO),
    ("catalogo: public volta a ficar de fora", CATALOGO,
     'SCHEMAS_DE_SISTEMA = ("pg_catalog", "information_schema", "pg_toast")',
     'SCHEMAS_DE_SISTEMA = ("pg_catalog", "information_schema", "pg_toast", "public")',
     ISOLAMENTO),
    ("catalogo: so um nome de coluna alternativo conta", CATALOGO,
     "lower(a.attname) LIKE '%%tenant%%'", "a.attname = 'tenant'", ISOLAMENTO),
    ("guarda: basta politica de leitura numa das tabelas", GUARDA,
     "AND qual = 'true' AND current_user = ANY(roles)) = 2 ",
     "AND qual = 'true' AND current_user = ANY(roles)) >= 1 "),
    ("guarda: qualquer comando conta como leitura", GUARDA,
     "AND permissive = 'PERMISSIVE' AND cmd IN ('SELECT', 'ALL') ",
     "AND permissive = 'PERMISSIVE' "),
    ("guarda: qualquer predicado conta como leitura total", GUARDA,
     "AND qual = 'true' AND current_user = ANY(roles)) = 2 ",
     "AND current_user = ANY(roles)) = 2 "),
    ("guarda: restritiva so procurada em tenant_channels", GUARDA,
     '"' + " " * 27 + "AND c.relname IN ('tenants', 'tenant_channels')",
     '"' + " " * 27 + "AND c.relname IN ('tenant_channels')"),
    ("guarda: restritiva para PUBLIC nao conta", GUARDA,
     "AND (0 = ANY(p.polroles) ", "AND (false "),
    ("guarda: restritiva FOR ALL nao conta", GUARDA,
     "AND p.polcmd IN ('r', '*') ", "AND p.polcmd IN ('r') "),
    ("guarda: restritiva de escrita volta a cegar", GUARDA,
     "AND p.polcmd IN ('r', '*') ", "AND true "),
    ("downgrade da 0002: nao revoga os GRANT do resolvedor", REV2,
     '"FROM kamba_resolver"', '"FROM kamba_batch"'),
    ("downgrade da 0002: nao revoga o USAGE do resolvedor", REV2,
     'op.execute("REVOKE USAGE ON SCHEMA platform FROM kamba_resolver")', "pass"),
    ("downgrade da 0002: disable_tenant_rls deixa o FORCE", RLS,
     'op.execute(f"ALTER TABLE {alvo} NO FORCE ROW LEVEL SECURITY")', "pass"),
    # ---------------------------------------------------------------- KAM-008
    # A revisao 0003 e o papel `kamba_identity`: o que o **schema** garante.
    ("0003: SELECT em contact_endpoints dado a kamba_app", REV3,
     '    op.execute("GRANT DELETE ON platform.contact_endpoints TO kamba_identity")\n',
     '    op.execute("GRANT DELETE ON platform.contact_endpoints TO kamba_identity")\n'
     '    op.execute("GRANT SELECT ON platform.contact_endpoints TO kamba_app")\n'),
    ("0003: phone_hmac legivel por kamba_app", REV3,
     '"contact_id", "tenant_id", "criado_at", "erased_at", "merged_into", "merged_at",\n)',
     '"contact_id", "tenant_id", "criado_at", "erased_at", "merged_into", "merged_at",\n'
     '    "phone_hmac",\n)'),
    ("0003: kamba_batch le o cofre", REV3,
     '    op.execute("GRANT DELETE ON platform.contact_endpoints TO kamba_identity")\n',
     '    op.execute("GRANT DELETE ON platform.contact_endpoints TO kamba_identity")\n'
     '    op.execute("GRANT SELECT ON platform.contact_endpoints, platform.contact_deks TO kamba_batch")\n'),
    ("0003: UPDATE de tenant_id dado a kamba_identity", REV3,
     '"contacts": ("phone_hmac", "hmac_kid", "erased_at", "merged_into", "merged_at"),',
     '"contacts": ("phone_hmac", "hmac_kid", "erased_at", "merged_into", "merged_at", "tenant_id"),'),
    ("0003: DELETE em contacts dado a kamba_identity", REV3,
     '"GRANT DELETE ON platform.contact_endpoints TO kamba_identity"',
     '"GRANT DELETE ON platform.contact_endpoints, platform.contacts TO kamba_identity"'),
    ("0003: UNIQUE do bsuid sem tenant", REV3,
     "CONSTRAINT contact_endpoints_bsuid_uq UNIQUE (tenant_id, hmac_kid, bsuid_hmac),",
     "CONSTRAINT contact_endpoints_bsuid_uq UNIQUE (hmac_kid, bsuid_hmac),"),
    ("0003: coluna de BSUID em claro acrescentada", REV3,
     "          bsuid_enc     bytea,\n", "          bsuid_enc     bytea,\n          bsuid         text,\n"),
    ("0003: phone_enc em text", REV3,
     "          phone_enc     bytea,", "          phone_enc     text,"),
    ("0003: FK do dono sem o tenant", REV3,
     "          FOREIGN KEY (id, owner_contact_id)\n"
     "          REFERENCES platform.contacts (tenant_id, contact_id)\n",
     "          FOREIGN KEY (owner_contact_id)\n"
     "          REFERENCES platform.contacts (contact_id)\n"),
    ("0003: FK do dono nao diferida", REV3,
     "          REFERENCES platform.contacts (tenant_id, contact_id)\n"
     "          DEFERRABLE INITIALLY DEFERRED\n",
     "          REFERENCES platform.contacts (tenant_id, contact_id)\n"),
    ("0003: FK do dono validada com o FORCE ligado", REV3,
     '    op.execute("ALTER TABLE platform.tenants NO FORCE ROW LEVEL SECURITY")\n', ""),
    ("0003: FORCE de tenants nao reposto (gate 8)", REV3,
     '    op.execute("ALTER TABLE platform.tenants FORCE ROW LEVEL SECURITY")\n', ""),
    ("0003: FORCE de tenants nao reposto (gate 6)", REV3,
     '    op.execute("ALTER TABLE platform.tenants FORCE ROW LEVEL SECURITY")\n', "",
     ISOLAMENTO),
    ("0003: contact_endpoints fica sem RLS", REV3,
     "    for tabela in TABELAS_DE_TENANT:\n        rls.enable_tenant_rls(tabela)\n",
     "    for tabela in TABELAS_DE_TENANT[:2]:\n        rls.enable_tenant_rls(tabela)\n",
     ISOLAMENTO),
    ("0003: downgrade sem copia logica", REV3,
     '    rls.disable_tenant_rls("contacts")\n\n    _copia_logica()\n',
     '    rls.disable_tenant_rls("contacts")\n'),
    ("0003: copia logica feita com a RLS ligada", REV3,
     '    rls.disable_tenant_rls("contact_endpoints")\n'
     '    rls.disable_tenant_rls("contact_deks")\n'
     '    rls.disable_tenant_rls("contacts")\n\n    _copia_logica()\n',
     '    _copia_logica()\n\n    rls.disable_tenant_rls("contact_endpoints")\n'
     '    rls.disable_tenant_rls("contact_deks")\n'
     '    rls.disable_tenant_rls("contacts")\n'),
    ("0003: copia logica escreve por cima", REV3,
     "os.O_WRONLY | os.O_CREAT | os.O_EXCL", "os.O_WRONLY | os.O_CREAT | os.O_TRUNC"),
    ("0003: downgrade nao revoga o USAGE de kamba_identity", REV3,
     'op.execute("REVOKE USAGE ON SCHEMA platform FROM kamba_identity")', "pass"),
    ("0003: contacto apagado pode guardar o HMAC do telefone", REV3,
     "CHECK ((erased_at IS NULL AND merged_into IS NULL) OR phone_hmac IS NULL)",
     "CHECK (true)"),
    ("0003: telefone guardado sem finalidade nem prazo", REV3,
     "               AND finalidade IS NOT NULL AND expira_at IS NOT NULL)", "               )"),
    ("0003: duas versoes de chave actuais", REV3,
     "ON platform.hmac_key_versions (estado) WHERE estado = 'actual'",
     "ON platform.hmac_key_versions (kid) WHERE estado = 'actual'"),
    ("0003: DEK destruida que guarda o embrulho", REV3,
     "CHECK ((wrapped_dek IS NULL) = (destroyed_at IS NOT NULL))", "CHECK (true)"),
    ("0003: endpoint pode apontar para o contacto de outro tenant", REV3,
     "            FOREIGN KEY (tenant_id, contact_id)\n"
     "            REFERENCES platform.contacts (tenant_id, contact_id),\n"
     "          CONSTRAINT contact_endpoints_dek_fk",
     "            FOREIGN KEY (contact_id)\n"
     "            REFERENCES platform.contacts (contact_id),\n"
     "          CONSTRAINT contact_endpoints_dek_fk"),
    ("bootstrap: kamba_identity com BYPASSRLS (gate 8)", BOOT,
     '"kamba_identity": "LOGIN NOSUPERUSER NOCREATEDB NOCREATEROLE NOREPLICATION NOBYPASSRLS"',
     '"kamba_identity": "LOGIN NOSUPERUSER NOCREATEDB NOCREATEROLE NOREPLICATION BYPASSRLS"'),
    ("bootstrap: kamba_identity com BYPASSRLS (gate 6)", BOOT,
     '"kamba_identity": "LOGIN NOSUPERUSER NOCREATEDB NOCREATEROLE NOREPLICATION NOBYPASSRLS"',
     '"kamba_identity": "LOGIN NOSUPERUSER NOCREATEDB NOCREATEROLE NOREPLICATION BYPASSRLS"',
     ISOLAMENTO),
    # O modulo de identidade (TypeScript), contra a base: suite `tests_identidade`.
    ("identidade: HMAC de pesquisa sem o tenant", ID_CRIPTO,
     ".update(`${DOMINIO_DE_PESQUISA}\\0${tipo}\\0${tenant}\\0`, \"utf8\")",
     ".update(`${DOMINIO_DE_PESQUISA}\\0${tipo}\\0`, \"utf8\")", IDENTIDADE),
    ("identidade: contexto da cifra sem a DEK", ID_CRIPTO,
     "`${DOMINIO_DE_CIFRA}\\0${campo}\\0${tenant}\\0${dekId}`",
     "`${DOMINIO_DE_CIFRA}\\0${campo}\\0${tenant}`", IDENTIDADE),
    ("identidade: sujeito_ref com a mesma chave em todos os meses", ID_CHAVES,
     "const ref = `${REF_CHAVE_DE_EPOCA}/${epoca}`;",
     "const ref = `${REF_CHAVE_DE_EPOCA}/202610`;", IDENTIDADE),
    ("identidade: prod aceita o KeyProvider de ambiente", ID_CHAVES,
     'if (declarado === "prod" && chaves.deAmbiente) {', "if (false) {", IDENTIDADE),
    ("identidade: provedor de dev arranca em prod", ID_CHAVES,
     "if (chaves.ambiente !== declarado) {", "if (false) {", IDENTIDADE),
    ("identidade: pesquisa do BSUID so com a chave actual", ID_SERVICO,
     '        kids.anterior,\n'
     '        chaveAnterior === null ? null : hmacDePesquisa(chaveAnterior, tenant, "bsuid", bsuid),',
     "        null,\n        null,", IDENTIDADE),
    ("identidade: pesquisa do telefone so com a chave actual", ID_SERVICO,
     "        kids.anterior,\n        hmacAnteriorDoTelefone,\n      ]);",
     "        null,\n        null,\n      ]);", IDENTIDADE),
    ("identidade: eraseContact nao destroi a DEK", ID_SERVICO,
     "const deksDestruidas = await executar(cliente, SQL.DESTRUIR_DEKS, [tenant, alvo.id]);",
     "const deksDestruidas = 1;", IDENTIDADE),
    ("identidade: eraseContact nao apaga os endpoints", ID_SERVICO,
     "const endpointsApagados = await executar(cliente, SQL.APAGAR_ENDPOINTS, [tenant, alvo.id]);",
     "const endpointsApagados = 2;", IDENTIDADE),
    ("identidade: apagar um absorvido nao chega a quem o absorveu", ID_SERVICO,
     "      if (estado.mergedInto === null) return estado;\n      procurado = estado.mergedInto;",
     "      return estado;", IDENTIDADE),
    ("identidade: a fusao fica com o mais novo", ID_SERVICO,
     "if (diferenca !== 0) return diferenca < 0 ? [a, b] : [b, a];",
     "if (diferenca !== 0) return diferenca < 0 ? [b, a] : [a, b];", IDENTIDADE),
    ("identidade: numero reatribuido funde duas pessoas", ID_SERVICO,
     "      if (outraPessoa) {", "      if (outraPessoa && false) {", IDENTIDADE),
    ("identidade: a fusao nao chama os ganchos", ID_SERVICO,
     "    for (const gancho of this.#ganchos) {\n"
     "      await gancho({ cliente, tenantId: tenant, de: sai.id, para: fica.id });\n    }\n",
     "", IDENTIDADE),
    ("identidade: a fusao deixa as DEK no absorvido", ID_SERVICO,
     "    await executar(cliente, SQL.MOVER_DEKS, [tenant, sai.id, fica.id]);\n", "",
     IDENTIDADE),
    ("identidade: corridas nao se repetem", ID_SERVICO,
     "        if (!repetivel(erro)) throw erro;", "        throw erro;", IDENTIDADE),
    ("identidade: rekeyLookup marca a versao sem recalcular o HMAC", ID_SERVICO,
     '              hmacDePesquisa(chave, tenant, "bsuid", bsuid),\n              kid,',
     '              hmacDePesquisa(chave, tenant, "telefone", bsuid),\n              kid,',
     IDENTIDADE),
    ("identidade: rekeyLookup aceita uma versao que nao e a actual", ID_SERVICO,
     '    if (linha === undefined || linha.estado !== "actual") throw new KidNaoActualError(kid);',
     "    if (linha === undefined) throw new KidNaoActualError(kid);", IDENTIDADE),
    ("identidade: iniciarRotacao por cima de outra", ID_SERVICO,
     '        if (anterior !== undefined) throw new RotacaoEmCursoError(texto(anterior, "kid"));\n',
     "", IDENTIDADE),
    ("identidade: telefone guardado em claro", ID_SERVICO,
     '            cifrar(dek, telefone, contextoDaCifra(tenant, dekId, "phone_enc")),',
     '            Buffer.from(telefone, "utf8"),', IDENTIDADE),
    ("identidade: BSUID guardado em claro", ID_SERVICO,
     '            cifrar(dek, bsuid, contextoDaCifra(tenant, dekId, "bsuid_enc")),',
     '            Buffer.from(bsuid, "utf8"),', IDENTIDADE),
    ("identidade: trocar de numero deixa a cifra do antigo", ID_SERVICO,
     "        if (telefoneDoContacto !== null && !eOMesmoNumero) {\n"
     "          await executar(cliente, SQL.APAGAR_TELEFONES, [tenant, contacto]);\n        }\n",
     "", IDENTIDADE),
    # ----------------------------------- KAM-008, revisao adversarial (ANALISE-08)
    # As que **sobreviveram** a primeira versao dos testes, mais as dos defeitos
    # que as duas revisoes encontraram.
    ("identidade: versoes de chave lidas sem tranca (corrida com a rotacao)", ID_SQL,
     "export const KIDS_VIVOS = `${VERSOES_VIVAS} FOR SHARE`;",
     "export const KIDS_VIVOS = VERSOES_VIVAS;", IDENTIDADE),
    ("identidade: eraseContact destroi as DEK do tenant inteiro", ID_SQL,
     '"WHERE tenant_id = $1 AND contact_id = $2 AND destroyed_at IS NULL";',
     '"WHERE tenant_id = $1 AND $2::uuid IS NOT NULL AND destroyed_at IS NULL";', IDENTIDADE),
    ("identidade: eraseContact apaga os endpoints do tenant inteiro", ID_SQL,
     '"DELETE FROM platform.contact_endpoints WHERE tenant_id = $1 AND contact_id = $2";',
     '"DELETE FROM platform.contact_endpoints WHERE tenant_id = $1 AND $2::uuid IS NOT NULL";',
     IDENTIDADE),
    ("identidade: a fusao move os endpoints do tenant inteiro", ID_SQL,
     '"UPDATE platform.contact_endpoints SET contact_id = $3 " +\n'
     '  "WHERE tenant_id = $1 AND contact_id = $2";',
     '"UPDATE platform.contact_endpoints SET contact_id = $3 " +\n'
     '  "WHERE tenant_id = $1 AND $2::uuid IS NOT NULL";', IDENTIDADE),
    ("identidade: a fusao nao larga o numero antigo de quem tem o BSUID", ID_SERVICO,
     "    if (a.phoneHmac !== null) await this.#tirarTelefone(cliente, tenant, a.id);\n", "",
     IDENTIDADE),
    ("identidade: rever o mesmo numero na janela apaga a cifra", ID_SERVICO,
     "        if (telefoneDoContacto !== null && !eOMesmoNumero) {",
     "        if (telefoneDoContacto !== null) {", IDENTIDADE),
    ("identidade: lerEndpoints serve telefones fora do prazo", ID_SQL,
     '  "AND (e.expira_at IS NULL OR e.expira_at > now()) " +\n', "", IDENTIDADE),
    ("canarios: a procura deixa de ver a forma hexadecimal do bytea", ID_SUITE,
     'canario.encode("ascii").hex().encode("ascii")',
     'canario.encode("ascii").hex().upper().encode("ascii")', IDENTIDADE),
    ("canarios: a procura deixa de ver a forma em texto", ID_SUITE,
     'return canario.encode("ascii"), canario.encode("ascii").hex().encode("ascii")',
     'return canario.encode("ascii").hex().encode("ascii"), canario.encode("ascii").hex().encode("ascii")',
     IDENTIDADE),
    ("0003: politica a mais que abre contacts a kamba_app (gate 6)", REV3,
     '    op.execute("GRANT USAGE ON SCHEMA platform TO kamba_identity")\n',
     '    op.execute("GRANT USAGE ON SCHEMA platform TO kamba_identity")\n'
     '    op.execute("CREATE POLICY app_le_tudo ON platform.contacts FOR SELECT TO kamba_app USING (true)")\n',
     ISOLAMENTO),
    ("0003: downgrade deixa os donos de tenant a apontar para nada", REV3,
     '    op.execute(\n        "UPDATE platform.tenants SET owner_contact_id = NULL "\n'
     '        "WHERE owner_contact_id IS NOT NULL"\n    )\n', ""),
    ("0003: copia logica sem as versoes de chave", REV3,
     'TABELAS_COPIADAS = ("hmac_key_versions", "contacts", "contact_deks", "contact_endpoints")',
     'TABELAS_COPIADAS = ("contacts", "contact_deks", "contact_endpoints")'),
    ("0003: copia logica sem os donos de tenant", REV3,
     '    for identificador, dono in op.get_bind().exec_driver_sql(SQL_DONOS):\n'
     '        yield "tenants", {"id": _celula(identificador), "owner_contact_id": _celula(dono)}\n',
     ""),
    ("0003: downgrade le os donos com o FORCE ligado", REV3,
     '    op.execute(\n        "ALTER TABLE platform.tenants NO FORCE ROW LEVEL SECURITY"\n    )\n',
     ""),
    ("0003: downgrade deixa tenants sem FORCE", REV3,
     '    op.execute(\n        "ALTER TABLE platform.tenants FORCE ROW LEVEL SECURITY"\n    )\n',
     ""),
    ("identidade: instrucao sem filtro de tenant", ID_SQL,
     '"DELETE FROM platform.contact_endpoints WHERE tenant_id = $1 AND contact_id = $2";',
     '"DELETE FROM platform.contact_endpoints WHERE contact_id = $2 AND $1::uuid IS NOT NULL";',
     IDENTIDADE),
    # ---------------------------------------------------------------- KAM-131
    # A segunda passagem do gate 9: os blobs que o intervalo do PR acrescenta.
    # Cada uma tem de ser apanhada por `tools/scan_secrets/tests/test_historia.py`
    # (suite `gate9`) ou, as do `ci.yaml` e do `Makefile`, por
    # `tools/lint_arch/tests/test_ci_gate9.py` (suite `gate9_ci`) — que existe
    # porque **nao ha lint de workflows** neste repositorio e o gate 9 passou a
    # depender de tres linhas de YAML e de um `fetch-depth`.
    ("KAM-131 historia: varre a historia toda e nao o intervalo", HIST,
     '"--objects", f"{base}..{head}")', '"--objects", f"{head}")', GATE9),
    # Nao ha mutacao a `candidatos = set(pares) | set(atribuicao)`: depois do
    # `-c`, o conjunto da travessia por objectos e um subconjunto do da
    # atribuicao, pelo que a mutacao que o reduz a um dos dois **sobrevive** —
    # e por equivalencia, nao por falta de teste. Fica a uniao como ultima
    # linha, e `Resultado.sem_atribuicao` conta o que so um dos lados alcance.
    # Ver a ANALISE-14 §3.3.
    #
    # As duas evasoes que a revisao adversarial construiu (ANALISE-14, A1 e A2)
    # passavam ambas pelo `-c`: sem ele o `git log --raw` nao imprime sequer o
    # cabecalho de um merge.
    ("KAM-131 historia: o `git log` deixa de ver o que um merge introduz", HIST,
     '        "-c",\n        "--no-abbrev",', '        "--no-abbrev",', GATE9),
    ("KAM-131 historia: a deteccao de mudancas de nome volta a ligar", HIST,
     '        "--no-renames",\n', "", GATE9),
    # O criterio 6 tem de valer nos dois sentidos da ordem alfabetica: a
    # primeira versao desta lista so tinha `[-1:]`, e `[:1]` sobrevivia.
    ("KAM-131 historia: so o ultimo caminho do blob e confrontado", HIST,
     "for caminho, commit in sorted(de_texto[sha].items()):",
     "for caminho, commit in sorted(de_texto[sha].items())[-1:]:", GATE9),
    ("KAM-131 historia: so o primeiro caminho do blob e confrontado", HIST,
     "        for caminho, commit in sorted(de_texto[sha].items()):",
     "        for caminho, commit in sorted(de_texto[sha].items())[:1]:", GATE9),
    ("KAM-131 historia: clone raso deixa de ser recusado", HIST,
     '"--is-shallow-repository").strip() == "true":',
     '"--is-shallow-repository").strip() == "nunca":', GATE9),
    ("KAM-131 historia: um PR sem base passa a varrer so a arvore", HIST,
     '    "pull_request": None,\n',
     '    "pull_request": "sem base: varre-se so a arvore",\n', GATE9),
    ("KAM-131 historia: um SHA a zeros deixa de contar como ausente", HIST,
     'return not limpo or set(limpo) == {"0"}', "return not limpo", GATE9),
    ("KAM-131 historia: os binarios passam a ser os unicos varridos", HIST,
     "if Path(caminho).suffix.lower() not in BINARIOS",
     "if Path(caminho).suffix.lower() in BINARIOS", GATE9),
    ("KAM-131 historia: o relatorio deixa de dizer o commit", HIST,
     'return f"{curto} {self.achado}\\n    blob {self.blob[:12]}"',
     'return f"{self.achado}"', GATE9),
    ("KAM-131 historia: um commit que nao e SHA volta a ser truncado", HIST,
     'curto = self.commit[:12] if _SHA.fullmatch(self.commit) else self.commit',
     "curto = self.commit[:12]", GATE9),
    # A contabilidade do relatorio: afirmar cobertura que nao houve e o defeito
    # que o proprio `scanner.py` conta ter tido em `_fragmentos`.
    ("KAM-131 historia: um blob que nao e UTF-8 conta como varrido", HIST,
     "            nao_decifraveis += 1\n            continue\n",
     "            varridos += 1\n            continue\n", GATE9),
    ("KAM-131 historia: os binarios saltados deixam de se contar", HIST,
     "saltados_por_extensao=len(blobs) - len(a_ler),",
     "saltados_por_extensao=0,", GATE9),
    # O intervalo invertido: a evasao do YAML trocado (A3).
    ("KAM-131 historia: um intervalo de zero commits deixa de ser erro", HIST,
     "    if nome not in EXIGEM_COMMITS:\n        return\n", "    return\n", GATE9),
    ("KAM-131 cli: um achado na historia deixa de reprovar", SEC_CLI,
     '        return 1\n\n    print(f"scan_secrets: limpo — {resultado.onde}")',
     '        return 0\n\n    print(f"scan_secrets: limpo — {resultado.onde}")',
     GATE9),
    ("KAM-131 cli: um intervalo irresoluvel passa a dar passagem", SEC_CLI,
     "        return 2\n\n    if resultado.achados:",
     "        return 0\n\n    if resultado.achados:", GATE9),
    ("KAM-131 cli: o modo so-arvore passa a dizer-se satisfeito", SEC_CLI,
     "NAO CORRIDA", "satisfeita", GATE9),
    ("KAM-131 cli: o modo so-arvore deixa de avisar no resumo do job", SEC_CLI,
     '"::warning title=gate 9::a passagem da historia NAO CORREU "',
     '"a passagem da historia nao correu "', GATE9),
    ("KAM-131 cli: o intervalo vazio deixa de ser confrontado", SEC_CLI,
     "        exigir_commits(argumentos.evento, resultado.commits)\n", "", GATE9),
    # A ancora leva o comentario de cima: o KAM-007 pos um segundo
    # `fetch-depth: 0` no `ci.yaml` (o do gate 7 compara com o ramo principal),
    # e a linha sozinha deixou de identificar um sitio so.
    ("KAM-131 ci: o checkout do gate 9 deixa de trazer a historia", CI_YAML,
     "          # nao verde em silencio (`historia.py:_resolver`).\n"
     "          fetch-depth: 0",
     "          # nao verde em silencio (`historia.py:_resolver`).\n"
     "          fetch-depth: 1", GATE9_CI),
    ("KAM-131 ci: a base do PR deixa de chegar ao gate 9", CI_YAML,
     "GATE9_BASE: ${{ github.event.pull_request.base.sha || github.event.merge_group.base_sha || github.event.before }}",
     'GATE9_BASE: ""', GATE9_CI),
    # A troca que a revisao adversarial fez: as quatro assercoes de texto da
    # primeira versao continuavam todas a bater, e o gate passava a varrer um
    # intervalo invertido.
    ("KAM-131 ci: a base e a cabeca vao trocadas", CI_YAML,
     "          GATE9_BASE: ${{ github.event.pull_request.base.sha || github.event.merge_group.base_sha || github.event.before }}\n"
     "          GATE9_HEAD: ${{ github.sha }}\n",
     "          GATE9_BASE: ${{ github.sha }}\n"
     "          GATE9_HEAD: ${{ github.event.pull_request.base.sha || github.event.merge_group.base_sha || github.event.before }}\n",
     GATE9_CI),
    ("KAM-131 ci: o merge_group fica fail-closed sem chave de base", CI_YAML,
     " || github.event.merge_group.base_sha", "", GATE9_CI),
    ("KAM-131 make: o alvo ci-9 deixa de correr a segunda passagem", MAKEFILE,
     "'history', '--evento'", "'tree', '--evento'", GATE9_CI),
    # KAM-136 — o leitor de YAML. Nao e codigo de `db/`, mas as duas suites leem
    # dele `ci/rls_exceptions.yaml`, `ci/secdef_allowlist.yaml` e
    # `ci/thresholds.yaml`, e a copia leva-o (ver `_copiar`). Em `1fbe738` a
    # copia **nao** o levava e ninguem dava por isso (ANALISE-07 §…): estas
    # mutacoes tambem provam que a copia continua a leva-lo.
    #
    # So entram aqui as que estas suites **apanham**. O caso 1 do KAM-136 (`>-`
    # como primeira chave de um item) nao tem forma de ser apanhado por aqui:
    # nenhum ficheiro que estas suites leem usa essa forma. Esse prova-se na
    # suite do `lint_arch`, e a prova esta em `docs/evidencia/KAM-136.md`.
    ("kam136 isolamento: inteiro deixa de se converter", KYAML,
     '_INTEIRO = re.compile(r"^[-+]?(0|[1-9][0-9]*)$")',
     '_INTEIRO = re.compile(r"^(?!x)x$")',
     ISOLAMENTO),
    ("kam136 isolamento: lista vazia em fluxo deixa de ser lista", KYAML,
     '    if texto.strip("[] ") == "" and texto.startswith("["):\n        return []\n',
     '    if texto.strip("[] ") == "" and texto.startswith("["):\n        return texto\n',
     ISOLAMENTO),
    ("kam136 isolamento: comentarios deixam de ser removidos", KYAML,
     "            limpa, cortou = _sem_comentario(bruta, onde)",
     "            limpa, cortou = bruta, False",
     ISOLAMENTO),
    # A mesma familia do caso 1: as chaves seguintes do item desaparecem. Esta
    # morde pela suite de identidade, que le `minimo_linhas` do estrato
    # `critico` de `ci/thresholds.yaml` — e esse e a segunda chave do item.
    ("kam136 identidade: as chaves seguintes do item deixam de entrar", KYAML,
     "            primeiro.update(seguintes)\n",
     "",
     IDENTIDADE),
    # ------------------------------------------------------------------- KAM-005
    # Outbox, envelope e publicador. As da revisao correm no gate 8 (suite
    # `tests`); as que tiram RLS correm no gate 6 (`ISOLAMENTO`).
    ("0004: guarda de PII sem o padrao angolano", REV4,
     "IF p_payload::text ~ '\\+?244 ?9[0-9]{8}' OR p_payload::text ~ '\"\\+[0-9]{9,15}\"' THEN",
     "IF p_payload::text ~ '\"\\+[0-9]{9,15}\"' THEN"),
    ("0004: guarda de PII sem o padrao E.164", REV4,
     "IF p_payload::text ~ '\\+?244 ?9[0-9]{8}' OR p_payload::text ~ '\"\\+[0-9]{9,15}\"' THEN",
     "IF p_payload::text ~ '\\+?244 ?9[0-9]{8}' THEN"),
    ("0004: guarda de PII depois de escrever no outbox", REV4,
     "        BEGIN\n          IF p_payload::text ~",
     "        BEGIN\n          IF false AND p_payload::text ~"),
    ("0004: o contador nao incrementa (seq de uma sequencia)", REV4,
     "            DO UPDATE SET seq = platform.evt_agregado_seq.seq + 1\n"
     "            RETURNING seq INTO v_seq;",
     "            DO UPDATE SET seq = platform.evt_agregado_seq.seq\n"
     "            RETURNING seq + 1 INTO v_seq;"),
    ("0004: a particao usa oito filas em vez de dezasseis", REV4,
     "v_part := (hashtextextended(p_tenant::text || p_agg_id, 0) & 15)::smallint;",
     "v_part := (hashtextextended(p_tenant::text || p_agg_id, 0) & 7)::smallint;"),
    ("0004: a particao ignora o tenant", REV4,
     "v_part := (hashtextextended(p_tenant::text || p_agg_id, 0) & 15)::smallint;",
     "v_part := (hashtextextended(p_agg_id, 0) & 15)::smallint;"),
    ("0004: o envelope perde o seq do agregado", REV4,
     "'agregado', jsonb_build_object('tipo', p_agg_tipo, 'id', p_agg_id, 'seq', v_seq),",
     "'agregado', jsonb_build_object('tipo', p_agg_tipo, 'id', p_agg_id),"),
    ("0004: o envelope leva outro tenant que a coluna", REV4,
     "'tenant_id', p_tenant,\n                'ocorrido_em', p_ocorrido_em,",
     "'tenant_id', gen_random_uuid(),\n                'ocorrido_em', p_ocorrido_em,"),
    ("0004: evt_emitir passa a SECURITY DEFINER", REV4,
     "        RETURNS uuid LANGUAGE plpgsql AS $$",
     "        RETURNS uuid LANGUAGE plpgsql SECURITY DEFINER AS $$"),
    ("0004: o arquivo ganha UPDATE para o publicador", REV4,
     'op.execute("GRANT SELECT, INSERT ON platform.events_log TO kamba_batch")',
     'op.execute("GRANT SELECT, INSERT, UPDATE ON platform.events_log TO kamba_batch")'),
    ("0004: o produtor ganha UPDATE no outbox", REV4,
     'op.execute("GRANT SELECT, INSERT ON platform.events_outbox TO kamba_app")',
     'op.execute("GRANT SELECT, INSERT, UPDATE ON platform.events_outbox TO kamba_app")'),
    ("0004: a particao DEFAULT passa a mensal", REV4,
     "          PARTITION OF platform.events_log DEFAULT",
     "          PARTITION OF platform.events_log\n"
     "          FOR VALUES FROM ('2026-11-01') TO ('2026-12-01')"),
    ("0004: o indice de pendentes deixa de ser parcial", REV4,
     "          ON platform.events_outbox (proxima_tentativa_at, id)\n"
     "          WHERE publicado_at IS NULL",
     "          ON platform.events_outbox (proxima_tentativa_at, id)"),
    ("0004: o outbox perde a unicidade do event_id", REV4,
     "          event_id             uuid NOT NULL\n"
     "                               CONSTRAINT events_outbox_event_id_uq UNIQUE,",
     "          event_id             uuid NOT NULL,"),
    ("0004: o outbox perde a unicidade do triplo do agregado", REV4,
     "          CONSTRAINT events_outbox_agregado_uq\n"
     "            UNIQUE (tenant_id, agregado_tipo, agregado_id, agregado_seq)\n",
     ""),
    # As duas que provam o desvio do achado 2: sem o `tenant_id` na unicidade e
    # no `ON CONFLICT`, o espaco de `seq` volta a ser global e um tenant corta a
    # emissao de outro.
    ("0004: a unicidade do triplo ignora o tenant", REV4,
     "            UNIQUE (tenant_id, agregado_tipo, agregado_id, agregado_seq)",
     "            UNIQUE (agregado_tipo, agregado_id, agregado_seq)"),
    ("0004: o contador do agregado ignora o tenant", REV4,
     "            ON CONFLICT (tenant_id, agregado_tipo, agregado_id)",
     "            ON CONFLICT (agregado_tipo, agregado_id)"),
    ("0004: o downgrade apaga os eventos sem pedir copia", REV4,
     "    contagens = _contar()\n    if not any(contagens.values()):\n        return\n",
     "    contagens = _contar()\n    return\n"),
    ("0004: a copia logica escreve por cima de uma anterior", REV4,
     "os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600",
     "os.O_WRONLY | os.O_CREAT | os.O_TRUNC, 0o600"),
    ("0004: o downgrade copia antes de desligar a RLS (le zero linhas)", REV4,
     '    rls.disable_tenant_rls("events_log_default")\n'
     '    rls.disable_tenant_rls("events_log")\n'
     '    rls.disable_tenant_rls("evt_agregado_seq")\n'
     '    rls.disable_tenant_rls("events_outbox")\n'
     "    _copia_logica()\n",
     "    _copia_logica()\n"
     '    rls.disable_tenant_rls("events_log_default")\n'
     '    rls.disable_tenant_rls("events_log")\n'
     '    rls.disable_tenant_rls("evt_agregado_seq")\n'
     '    rls.disable_tenant_rls("events_outbox")\n'),
    ("0004: o outbox fica sem RLS", REV4,
     '    "events_outbox",\n    "evt_agregado_seq",\n',
     '    "evt_agregado_seq",\n', ISOLAMENTO),
    ("0004: o contador do agregado fica sem RLS", REV4,
     '    "events_outbox",\n    "evt_agregado_seq",\n',
     '    "events_outbox",\n', ISOLAMENTO),
    ("0004: a particao do arquivo fica sem RLS propria", REV4,
     '    "events_log",\n    "events_log_default",\n)',
     '    "events_log",\n)', ISOLAMENTO),
    ("0004: o arquivo fica sem RLS", REV4,
     '    "events_log",\n    "events_log_default",\n)',
     '    "events_log_default",\n)', ISOLAMENTO),
    ("0004: o produtor ganha DELETE no outbox", REV4,
     'op.execute(\n        "GRANT SELECT, UPDATE, DELETE ON platform.events_outbox TO kamba_batch"\n    )',
     'op.execute(\n        "GRANT SELECT, UPDATE, DELETE ON platform.events_outbox TO kamba_app"\n    )'),
    # --------------------------------------------------- KAM-005, o publicador
    # Correm contra `tests_eventos` — PostgreSQL **e** fila reais. A medicao de
    # carga esta em `tests_eventos_carga`, a parte, para que cada uma destas
    # custe tres minutos e nao oito (ver o comentario dessa suite).
    # A mutacao central: trocar a ordem `add` -> `COMMIT` por `COMMIT` -> `add`.
    # E o modo de falha que o outbox existe para nao ter — um `kill -9` logo
    # depois do `COMMIT` deixava a linha publicada e o *job* por criar — e e o
    # criterio 3 que a apanha.
    ("eventos: o publicador confirma antes de por na fila", EV_PUBLICADOR,
     "      const ids = boas.map((p) => p.linha.id);\n"
     "      if (ids.length > 0) {\n"
     "        await this.#bd.query(SQL_ARQUIVAR, [ids]);\n"
     "        await this.#bd.query(SQL_MARCAR_PUBLICADO, [ids]);\n"
     "      }\n"
     '      await this.#bd.query("COMMIT");\n',
     '      await this.#bd.query("COMMIT");\n'
     "      const ids = boas.map((p) => p.linha.id);\n"
     "      if (ids.length > 0) {\n"
     "        await this.#bd.query(SQL_ARQUIVAR, [ids]);\n"
     "        await this.#bd.query(SQL_MARCAR_PUBLICADO, [ids]);\n"
     "      }\n",
     EVENTOS),
    # Achado 1: a fase 1 deixa de cortar por agregado e passa a derrubar o lote.
    # A mutacao poe de volta o defeito que o achado 1 descreve.
    ("eventos: uma linha invalida volta a derrubar o lote", EV_PUBLICADOR,
     "      } catch (erro) {\n"
     "        const motivo = motivoDoErro(erro);\n"
     "        this.#metricas.contar(METRICA_ERROS, motivo);\n"
     '        this.#log?.warn({ outcome: "evt_bloqueado", error_code: motivo });\n'
     "        agregadosBloqueados.add(agregado);\n"
     "        adiadas.push(linha);\n"
     "      }\n",
     "      } catch (erro) {\n"
     "        const motivo = motivoDoErro(erro);\n"
     "        this.#metricas.contar(METRICA_ERROS, motivo);\n"
     '        this.#log?.warn({ outcome: "evt_bloqueado", error_code: motivo });\n'
     "        throw erro;\n"
     "      }\n",
     EVENTOS),
    # Achado 1, segunda metade: o corte deixa de ser por agregado e passa a ser
    # so da linha ma — o que perde a ordem causal do agregado dela.
    ("eventos: o corte deixa de arrastar o resto do agregado", EV_PUBLICADOR,
     "      if (agregadosBloqueados.has(agregado)) {\n"
     "        adiadas.push(linha);\n"
     "        continue;\n"
     "      }\n",
     ""),
    # Achado 13: o erro do laco volta a nao largar o lock consultivo.
    ("eventos: um erro transitorio deixa o lock preso", EV_PUBLICADOR,
     "        await this.largar();\n"
     "      }\n"
     "      await esperar(this.#intervalo, sinal);",
     "        this.#lider = false;\n"
     "      }\n"
     "      await esperar(this.#intervalo, sinal);",
     EVENTOS),
    # Achado 7: o atraso do criterio 8 volta a ser medido pelo relogio do
    # inicio da transaccao, que exclui o enfileiramento do lote.
    ("eventos: o atraso e medido antes do trabalho", EV_CONSULTAS,
     "     SET publicado_at = clock_timestamp()",
     "     SET publicado_at = now()"),
    # Achado 5: o cliente da fila volta a esconder a indisponibilidade.
    ("eventos: a fila em baixo deixa de falhar o add", EV_FILAS,
     "  enableOfflineQueue: false,",
     "  enableOfflineQueue: true,",
     EVENTOS),
    # A que mais importa das tres: sem limite no `add`, o publicador fica
    # pendurado com a fila em baixo e o recuo do criterio 4 nunca acontece.
    ("eventos: o add espera indefinidamente pela fila", EV_FILAS,
     "export const TEMPO_MAXIMO_DO_ADD = 5_000;",
     "export const TEMPO_MAXIMO_DO_ADD = 3_600_000;",
     EVENTOS),
    ("eventos: o envelope deixa de recusar campos desconhecidos", EV_ENVELOPE,
     "  if (demais.length > 0) {\n"
     "    throw new EnvelopeInvalidoError(\n"
     "      `campo(s) de topo desconhecido(s): ${demais.sort().join(\", \")}`,\n"
     "    );\n"
     "  }\n",
     ""),
    ("eventos: o envelope aceita classe_pii P2", EV_ENVELOPE,
     '  if (classe === "P2") {',
     '  if (classe === "P9") {'),
    ("eventos: o guarda de PII perde o padrao angolano", EV_PII,
     "export const PADROES_DE_TELEFONE = [TELEFONE_AO, E164_ENTRE_ASPAS] as const;",
     "export const PADROES_DE_TELEFONE = [E164_ENTRE_ASPAS] as const;"),
    ("eventos: o guarda de PII perde o padrao E.164", EV_PII,
     "export const PADROES_DE_TELEFONE = [TELEFONE_AO, E164_ENTRE_ASPAS] as const;",
     "export const PADROES_DE_TELEFONE = [TELEFONE_AO] as const;"),
    ("eventos: o recuo do outbox perde o tecto de 30 s", EV_PUBLICADOR,
     "export const ESCADA_DE_RECUO = [1_000, 2_000, 5_000, 15_000, 30_000] as const;",
     "export const ESCADA_DE_RECUO = [1_000, 5_000, 30_000, 120_000, 600_000] as const;",
     EVENTOS),
    ("eventos: o arquivo deixa de absorver a republicacao", EV_CONSULTAS,
     "  ON CONFLICT DO NOTHING",
     "  ON CONFLICT (event_id, ocorrido_em) DO UPDATE SET registado_em = now()",
     EVENTOS),
    ("eventos: o jobId deixa de ser o event_id", EV_PUBLICADOR,
     "        jobId: envelope.id,",
     "        jobId: `${envelope.id}:${alvo.consumer}`,",
     EVENTOS),
    ("eventos: a entrega ignora a finalidade do envelope", EV_PUBLICADOR,
     "  return subscricoes.filter(\n"
     "    (s) => s.tipo === envelope.tipo && finalidades.has(s.finalidade),\n"
     "  );",
     "  return subscricoes.filter((s) => s.tipo === envelope.tipo);",
     EVENTOS),
    ("eventos: a entrega ignora o tipo do envelope", EV_PUBLICADOR,
     "  return subscricoes.filter(\n"
     "    (s) => s.tipo === envelope.tipo && finalidades.has(s.finalidade),\n"
     "  );",
     "  return subscricoes.filter((s) => finalidades.has(s.finalidade));",
     EVENTOS),
    ("eventos: o recuo nao adia nada", EV_CONSULTAS,
     "         proxima_tentativa_at = now() + make_interval(secs => $2::double precision / 1000)",
     "         proxima_tentativa_at = now() + make_interval(secs => $2::double precision * 0)",
     EVENTOS),
    ("eventos: o publicador varre por ordem inversa de escrita", EV_CONSULTAS,
     "   ORDER BY id\n   LIMIT $1",
     "   ORDER BY id DESC\n   LIMIT $1",
     EVENTOS),
    ("eventos: o publicador le as subscricoes inactivas", EV_CONSULTAS,
     "    FROM platform.evt_subscricoes\n   WHERE activo",
     "    FROM platform.evt_subscricoes\n   WHERE activo IS NOT NULL",
     EVENTOS),
    ("eventos: a lideranca deixa de ser exclusiva", EV_CONSULTAS,
     'export const SQL_ELEGER = "SELECT pg_try_advisory_lock($1) AS lider";',
     'export const SQL_ELEGER = "SELECT ($1 IS NOT NULL) AS lider";',
     EVENTOS),
    ("eventos: a particao dobra por modulo em vez de falhar", EV_PARTICAO,
     "  return `${PREFIXO_DA_FILA}.${consumer}.p${exigirParticao(particao)}`;",
     "  return `${PREFIXO_DA_FILA}.${consumer}.p${particao % PARTICOES}`;",
     EVENTOS),
    ("eventos: o publicador nao repete o guarda de PII", EV_PUBLICADOR,
     '    exigirSemTelefone(envelope.payload, "payload do evento");\n',
     "",
     EVENTOS),
    # ---------------------------------------------------------------- KAM-158
    # O varredor das contagens em prosa. Cada uma tem de ser apanhada por
    # `tools/lint_contagens/tests/test_scan.py` (suite `contagens`).
    #
    # Nao ha mutacao aos tres guardas da CLI (grandeza sem ocorrencias, minimo
    # da populacao, declaracao que nao casa nada): a bateria que os exercita e o
    # `test_cli.py`, que afirma sobre o repositorio real, e a copia da prova nao
    # e o repositorio. Ficam cobertos por teste de unidade, e o bloco do ticket
    # di-lo.
    ("KAM-158 contagens: o comparador passa a dizer sempre que bate", CONT_SCAN,
     "        return self.escrito in self.aceitaveis",
     "        return True", CONTAGENS),
    ("KAM-158 contagens: a linha de controlo de versoes deixa de ser historia", CONT_SCAN,
     "        if em_verificacao or VERSAO.match(linha):",
     "        if em_verificacao:", CONTAGENS),
    ("KAM-158 contagens: o numero de um identificador volta a contar", CONT_SCAN,
     "    'tickets': re.compile(r'(?<![\\w.-])(\\d{1,4})\\s+tickets?\\b', re.I),",
     "    'tickets': re.compile(r'(?<![\\w.])(\\d{1,4})\\s+tickets?\\b', re.I),", CONTAGENS),
    ("KAM-158 contagens: a leitura por epic desaparece", CONT_SCAN,
     "        epic = epic_do_ficheiro(rel)\n"
     "        if epic and epic in fontes.por_epic:\n"
     "            valores.append(fontes.por_epic[epic])\n",
     "", CONTAGENS),
    # A exclusao do corpus volta ao caminho absoluto, que e o defeito que o
    # KAM-158 tinha: uma arvore dentro de uma pasta `.claude` — qualquer
    # worktree do Claude Code — ficava com o corpus vazio, e o gate media
    # zero contagens numa arvore cheia delas.
    ("KAM-158 contagens: a exclusao do corpus volta ao caminho absoluto", CONT_SCAN,
     "            if '.claude' in rel.parts or 'node_modules' in rel.parts:",
     "            if '.claude' in f.parts or 'node_modules' in f.parts:", CONTAGENS),

    # ------------------------------------------------------------- KAM-006
    #
    # Quinze, e doze delas apontadas a suite com fila: o que so ela ve e a
    # transaccao unica, a contagem de tentativas, a classificacao do erro e a
    # reposicao. Cada uma e um defeito que existiu, ou que a revisao do espelho
    # em Python ou a revisao adversarial encontraram — nenhuma e inventada para
    # encher a lista.
    #
    # As outras tres apontam a suite `tests`, e a razao e sempre a mesma: sao
    # acoplamentos entre ficheiros, ou guardas, que **nenhuma execucao
    # distingue de uma coincidencia**. Vivem no
    # `db/tests/test_consumo_contrato.py` e no `test_dlq_reabertura.py`.
    ("consumo: a marca de consumo deixa de ser do tenant do envelope", EV_CONSUMO,
     "    await bd.query(SQL_DEFINIR_TENANT, [envelope.tenant_id, true]);\n",
     "", CONSUMO),
    ("consumo: um duplicado volta a aplicar o efeito", EV_CONSUMO,
     "    if ((marca.rowCount ?? 0) === 0) {",
     "    if ((marca.rowCount ?? 0) === -1) {", CONSUMO),
    ("consumo: «atrasado» passa a ser «adiantado»", EV_CONSUMO,
     "        const atrasado = ultimoSeq !== null && agregado.seq < ultimoSeq;",
     "        const atrasado = ultimoSeq !== null && agregado.seq > ultimoSeq;",
     CONSUMO),
    ("consumo: o agregado que nao existe passa a poder transitar", EV_CONSUMO,
     "      if (estado === null) {",
     "      if (estado === undefined) {", CONSUMO),
    ("trabalho: a ultima tentativa deixa de abrir a DLQ", EV_TRABALHO,
     "  const ultima = tentativa >= tentativasMaximas;",
     "  const ultima = tentativa > tentativasMaximas;", CONSUMO),
    ("trabalho: um fora_de_ordem passa a recuar pela escada", EV_TRABALHO,
     "    if (erro instanceof ForaDeOrdem) {",
     "    if (erro instanceof RangeError) {", CONSUMO),
    ("dlq: a entrada deixa de ter contexto de tenant", EV_DLQ,
     "    await bd.query(SQL_DEFINIR_TENANT, [tenantId, true]);\n",
     "", CONSUMO),
    ("trabalhador: um evento ilegivel deixa de abrir a DLQ", EV_TRABALHADOR,
     "            await paraDlqSemEnvelope({",
     "            await Promise.resolve({", CONSUMO),
    ("trabalhador: o evento que o arquivo nao tem deixa de ser adiado", EV_TRABALHADOR,
     "            if (!ultima) throw new Adiar(ADIAMENTO_POR_OMISSAO, erro.message);",
     "", CONSUMO),
    # ------------------------------------------------------------- KAM-012
    #
    # Cada uma desfaz uma propriedade que o ticket nomeia, e a que sobreviver
    # diz que essa propriedade nao tem teste.
    ("revisao 0006: a cadeia parte da genese errada", REV6,
     r'GENESE = "\\x0000000000000000000000000000000000000000000000000000000000000000"',
     r'GENESE = "\\x0000000000000000000000000000000000000000000000000000000000000001"'),
    ("revisao 0006: o separador do hash desaparece", REV6,
     '"|| chr(31) || p_tenant_id || chr(31) || "',
     '"|| p_tenant_id || "'),
    ("revisao 0006: o payload_hash sai do row_hash", REV6,
     '"encode(p_payload_hash, \'hex\')"',
     '"\'\'"'),
    ("revisao 0006: o trigger deixa de ser ALWAYS", REV6,
     '        "ALTER TABLE platform.audit_log "\n'
     '        "ENABLE ALWAYS TRIGGER audit_log_sem_update_nem_delete"',
     '        "ALTER TABLE platform.audit_log "\n'
     '        "ENABLE TRIGGER audit_log_sem_update_nem_delete"'),
    ("revisao 0006: o audit_log deixa de ter trigger de UPDATE", REV6,
     "          BEFORE UPDATE OR DELETE ON platform.audit_log",
     "          BEFORE DELETE ON platform.audit_log"),
    ("revisao 0006: a aplicacao passa a ler o registo", REV6,
     'op.execute("GRANT SELECT ON platform.audit_log TO kamba_batch")',
     'op.execute("GRANT SELECT ON platform.audit_log TO kamba_batch, kamba_app")'),
    ("revisao 0006: o dominio de action ganha um valor", REV6,
     '"\'access.conversation\', \'batch.run\', \'breakglass.open\', \'audit.read\'"',
     '"\'access.conversation\', \'batch.run\', \'breakglass.open\', \'audit.read\', \'tudo\'"'),
    ("revisao 0006: o row_hash deixa de ser unico", REV6,
     "          CONSTRAINT audit_log_row_hash_uq UNIQUE (tenant_id, row_hash),",
     ""),
    # Esta substitui uma que **nao mudava comportamento nenhum**: a obvia
    # sobre o `criado_at` seria `NEW.criado_at := coalesce(NEW.criado_at,
    # now())`, e a coluna tem `DEFAULT now()`, pelo que o `NEW.criado_at`
    # nunca chega nulo. Era apanhada por qualquer teste e nao provava nada.
    # Esta alarga o `GRANT` a um papel que nao tem nada que escrever
    # auditoria, e e a matriz de privilegios que a tem de apanhar.
    ("revisao 0006: o resolvedor passa a escrever auditoria", REV6,
     '"ON platform.audit_log TO kamba_app"',
     '"ON platform.audit_log TO kamba_app, kamba_resolver"'),
    ("revisao 0006: o chamador volta a escolher os hashes", REV6,
     "          NEW.prev_hash := v_prev;",
     "          NEW.prev_hash := coalesce(NEW.prev_hash, v_prev);"),
    ("revisao 0006: o texto deixa de ter tecto", REV6,
     "            length(actor_id) <= {TECTO_DE_TEXTO}",
     "            length(actor_id) <= 1000000"),
    ("auditoria: o verificador deixa de ver o elo partido", AUDITORIA,
     "            if prev_hash != anterior:",
     "            if False:"),
    ("auditoria: o verificador deixa de recalcular o hash", AUDITORIA,
     "            if calculado != guardado:",
     "            if False:"),
    ("auditoria: o verificador deixa de olhar para a cabeca", AUDITORIA,
     "        elif declarada != anterior:",
     "        elif False:"),
    ("auditoria: a ancora volta a depender do fuso da sessao", AUDITORIA,
     '" WHERE a.criado_at < ((%s::date + 1)::timestamp AT TIME ZONE \'UTC\') "',
     '" WHERE a.criado_at < (%s::date + 1) "'),
    ("auditoria: o criado_at sai do hash", AUDITORIA,
     "        iso_utc(criado_at),",
     "        '',"),
    ("auditoria: o verificador deixa de comparar com a ancora", AUDITORIA,
     "    achados.extend(_contra_a_ancora(por_cadeia, ancora))",
     "    achados.extend([])"),
    ("revisao 0005: a unicidade da DLQ deixa de ser parcial", REV5,
     "        CREATE UNIQUE INDEX events_dlq_aberta_uq\n          ON platform.events_dlq (consumer, event_id)\n          WHERE estado = 'aberta'\n",
     "        CREATE UNIQUE INDEX events_dlq_aberta_uq\n          ON platform.events_dlq (consumer, event_id)\n"),
    ("filas: o worker volta a usar a ligacao que desiste", EV_TRABALHADOR,
     "  const ligacao = new Redis({ ...opcoesDaUrl(url), ...LIGACAO_QUE_ESPERA });",
     "  const ligacao = new Redis({ ...opcoesDaUrl(url), ...LIGACAO_QUE_FALHA_DEPRESSA });"),
    ("accoes: o once deixa de recusar a transaccao de quem o chama", EV_ACCOES,
     "  await exigirForaDeTransaccao(bd, chave);\n",
     ""),
    ("reconciliador: o evento reposto perde o tenant", EV_RECON,
     "        tenant_id: linha.tenant_id,\n",
     "", CONSUMO),
    ("revisao 0005: a retencao aceita uma janela menor que a re-entrega", REV5,
     "          IF p_dias < 7 THEN",
     "          IF p_dias < 1 THEN", CONSUMO),
    ("revisao 0005: a retencao da DLQ apaga entradas abertas", REV5,
     "          DELETE FROM platform.events_dlq\n"
     "            WHERE estado <> 'aberta'\n",
     "          DELETE FROM platform.events_dlq\n"
     "            WHERE true\n", CONSUMO),
    # Esta e das tres que a suite com fila **nao** apanha, e e por isso que o
    # `db/tests/test_consumo_contrato.py` existe: com o relogio acelerado a
    # escada do publicador e a do worker dao tempos parecidos, e com a escada
    # real o teste custava 756 s. O acoplamento le-se como texto.
    # ------------------------------------------------------------- KAM-007
    #
    # O gate 7. As quatro primeiras mordem no classificador de diferencas, que
    # e o que impede um contrato de partir sem versao nova; as duas seguintes
    # no lint de PII; a ultima no proprio contrato, para a bateria nao estar a
    # provar so a logica.
    ("contratos: o que o classificador nao le passa a ser aprovado", CD_DIFF,
     "    for chave in sorted(desconhecidas):",
     "    for chave in sorted(set()):", CONTRATOS),
    ("contratos: alargar um enum deixa de quebrar", CD_DIFF,
     "        if d - a:",
     "        if False:", CONTRATOS),
    ("contratos: tornar um campo obrigatorio deixa de quebrar", CD_DIFF,
     "    for nome in sorted(obrig_actual - obrig_base):",
     "    for nome in sorted(set()):", CONTRATOS),
    ("contratos: abrir o payload deixa de quebrar", CD_DIFF,
     '    if base.get("additionalProperties") != actual.get("additionalProperties"):',
     "    if False:", CONTRATOS),
    ("contratos: o lint de PII perde o nome mais obvio", CD_PII,
     'PROIBIDOS = ("telefone", "msisdn", "bsuid", "nome", "morada", "texto", "email")',
     'PROIBIDOS = ("msisdn", "bsuid", "nome", "morada", "texto", "email")', CONTRATOS),
    ("contratos: o lint de PII volta a procurar por subcadeia", CD_PII,
     "    partes = set(segmentos(nome))",
     "    partes = {nome.lower()}", CONTRATOS),
    ("contratos: o gerador aceita o que nao sabe traduzir", CD_GERAR,
     "    if desconhecidas:",
     "    if False:", CONTRATOS),
    # As dez que seguem nasceram da revisao adversarial do KAM-007. Cada uma
    # desfaz exactamente um achado, e so passa a lista se o teste que o fechou
    # a apanhar — e a forma de saber que a correccao tem prova e nao so codigo.
    ("contratos: o lint de PII volta a deixar passar o plural", CD_PII,
     '        if raiz in partes or raiz + "s" in partes:',
     "        if raiz in partes:", CONTRATOS),
    ("contratos: o lint de PII volta a saber so os sete do 7.3", CD_PII,
     "RAIZES = PROIBIDOS + TAMBEM_PROIBIDOS",
     "RAIZES = PROIBIDOS", CONTRATOS),
    ("contratos: o lint de PII deixa de descer pelo que nao conhece", CD_PII,
     "        for chave, filho in no.items():",
     "        for chave, filho in {}.items():", CONTRATOS),
    ("contratos: o classificador volta a rebentar em vez de falhar fechado", CD_DIFF,
     "    except (TypeError, AttributeError, ValueError, RecursionError) as erro:",
     "    except KeyboardInterrupt as erro:", CONTRATOS),
    ("contratos: um required sobre campo nao declarado volta ao silencio", CD_DIFF,
     '            porque = ("passou a obrigatorio e nao esta em `properties`: o schema e "',
     '            continue  # mutacao\n            porque = ("", ', CONTRATOS),
    ("contratos: um exemplo com PII P2 deixa de ser achado", CD_EXEMPLOS,
     '        if exemplo.get("classe_pii") == "P2":',
     "        if False:", CONTRATOS),
    ("contratos: o gerador volta a declarar tudo opcional em Python", CD_GERAR,
     '                anotacao = f"NotRequired[{anotacao}]"',
     "                pass", CONTRATOS),
    ("contratos: o validador Python deixa de ver o campo a mais", CD_GERAR,
     "    se_sobra = sorted(set(payload) - permitidos)",
     "    se_sobra = []", CONTRATOS),
    ("contratos: um contrato volta a admitir PII P2", CONTRATO_PAY_MANUAL,
     '"classe_pii": {' + chr(10) + '      "type": "string",' + chr(10) + '      "enum": [' + chr(10) + '        "P0"' + chr(10) + '      ]',
     '"classe_pii": {' + chr(10) + '      "type": "string",' + chr(10) + '      "enum": [' + chr(10) + '        "P0",' + chr(10) + '        "P2"' + chr(10) + '      ]',
     CONTRATOS),
    ("contratos: os dois pagamentos voltam a ser indistinguiveis", CONTRATO_PAY_MANUAL,
     '"enum": [' + chr(10) + '                "manual"' + chr(10) + '              ]',
     '"enum": [' + chr(10) + '                "manual",' + chr(10) + '                "hmac"' + chr(10) + '              ]',
     CONTRATOS),
    ("contratos: um payload deixa de ser fechado", CONTRATO_ORDER_PAID,
     '"payload": {' + chr(10) + '      "type": "object",' + chr(10) + '      "additionalProperties": false,',
     '"payload": {' + chr(10) + '      "type": "object",' + chr(10) + '      "additionalProperties": true,',
     CONTRATOS),
    ("filas: o job deixa de pedir a escada do consumidor", EV_FILAS,
     'backoff: { type: "custom" },',
     'backoff: { type: "exponential", delay: REPETICAO.atraso },'),
    # ------------------------------------------------------------- KAM-009
    #
    # A regra de consumo de limites (`platform.ten_consumir`, revisao 0007).
    # Quase todas correm contra `tests_ten`, que e a suite que prova a
    # **funcao**. Uma corre contra `tests_isolamento`: as duas tabelas tem
    # `tenant_id` e o catalogo do gate 6 descobre-as sozinho, e a mutacao que
    # tira a RLS a uma delas e a prova de que esse catalogo morde nas tabelas
    # novas. A gemea — a RLS do contador — fica em `tests_ten`, para que a
    # suite da funcao tambem a apanhe: ela le o contador de outro tenant.
    #
    # Cada uma desfaz uma propriedade que a revisao escreve por extenso na
    # sua docstring. Uma que sobreviva diz que essa propriedade nao tem teste.
    #
    # **As onze ultimas sao da revisao adversarial**, e cada uma repoe
    # exactamente o defeito que ela mediu. Sao a resposta a pergunta que a
    # reprovacao deixou: «porque e que 47 testes e 15 mutacoes nao apanharam
    # tres criticos?» — porque nenhuma mutacao os escrevia.
    ("revisao 0007: a ordem das duas insercoes trocada", REV7,
     _TEN_ORDEM, _TEN_ORDEM_TROCADA, TEN),
    ("revisao 0007: o registo da chave sai da subtransaccao", REV7,
     "  BEGIN\n"
     "    INSERT INTO platform.usage_ledger\n"
     "                (tenant_id, idempotency_key, chave_limite, periodo, quantidade)\n"
     "         VALUES (p_tenant, p_idempotency_key, p_chave, v_periodo, p_quantidade);\n"
     "\n"
     "    IF p_quantidade > v_limite THEN",
     _TEN_CHAVE_FORA, TEN),
    ("revisao 0007: o ultimo que cabe no tecto passa a ser recusado", REV7,
     "     WHERE platform.tenant_usage.valor + p_quantidade <= v_limite",
     "     WHERE platform.tenant_usage.valor + p_quantidade < v_limite", TEN),
    ("revisao 0007: o tecto de quem chama passa a subir", REV7,
     "    v_limite := least(v_limite, p_limite);",
     "    v_limite := greatest(v_limite, p_limite);", TEN),
    ("revisao 0007: o tecto passa a ser o maximo entre modulos", REV7,
     "  SELECT min(CASE WHEN d.legivel THEN d.texto::bigint END),",
     "  SELECT max(CASE WHEN d.legivel THEN d.texto::bigint END),", TEN),
    ("revisao 0007: sem entitlement passa a aceitar", REV7,
     "    RETURN QUERY SELECT false, 0::bigint, false, NULL::bigint;",
     "    RETURN QUERY SELECT true, 0::bigint, false, NULL::bigint;", TEN),
    ("revisao 0007: um entitlement inactivo passa a contar", REV7,
     "         AND e.ativo\n", "", TEN),
    ("revisao 0007: a quantidade nao positiva deixa de levantar", REV7,
     "  IF p_quantidade IS NULL OR p_quantidade <= 0 THEN",
     "  IF false THEN", TEN),
    ("revisao 0007: o periodo passa a ser em UTC", REV7,
     "SELECT date_trunc('month', p_agora AT TIME ZONE 'Africa/Luanda')::date",
     "SELECT date_trunc('month', p_agora AT TIME ZONE 'UTC')::date", TEN),
    ("revisao 0007: a funcao passa por cima da RLS", REV7,
     "RETURNS TABLE (aceite boolean, valor bigint, repetido boolean, limite bigint)\n"
     "LANGUAGE plpgsql\nSECURITY INVOKER",
     "RETURNS TABLE (aceite boolean, valor bigint, repetido boolean, limite bigint)\n"
     "LANGUAGE plpgsql\nSECURITY DEFINER", TEN),
    ("revisao 0007: o contador fica sem RLS", REV7,
     '    rls.enable_tenant_rls("tenant_usage")\n', "", TEN),
    ("revisao 0007: o livro fica sem RLS (gate 6)", REV7,
     '    rls.enable_tenant_rls("usage_ledger")\n', "", ISOLAMENTO),
    ("revisao 0007: o downgrade nao repoe o UPDATE em entitlements", REV7,
     '    op.execute("GRANT UPDATE (limites, ativo) ON platform.entitlements TO kamba_app")\n',
     "", TEN),
    ("revisao 0007: o downgrade repoe a lista de colunas sem o plano", REV7,
     "COLUNAS_DA_0001 = (\n"
     '    "nome, nif, contacto_negocio_enc, owner_contact_id, zona, plus_code, "\n'
     '    "plano, estado, medusa_sales_channel_id, medusa_merchant_id, "\n',
     "COLUNAS_DA_0001 = (\n"
     '    "nome, nif, contacto_negocio_enc, owner_contact_id, zona, plus_code, "\n'
     '    "estado, medusa_sales_channel_id, medusa_merchant_id, "\n',
     TEN),
    # ------------------------------------- KAM-009, revisao adversarial
    #
    # C1: a chave de idempotencia solta do pedido que identifica. Duas
    # mutacoes porque sao duas propriedades independentes — o ambito da chave
    # e a quantidade — e cada uma sozinha deixava passar metade do ataque.
    ("revisao 0007: a chave de idempotencia atravessa chaves de limite", REV7,
     "          PRIMARY KEY (tenant_id, chave_limite, idempotency_key)",
     "          PRIMARY KEY (tenant_id, idempotency_key)", TEN),
    ("revisao 0007: a repeticao deixa de comparar a quantidade", REV7,
     _TEN_QUANTIDADE, "", TEN),
    ("revisao 0007: a chave de idempotencia passa a ser global", REV7,
     "          PRIMARY KEY (tenant_id, chave_limite, idempotency_key)\n",
     "          PRIMARY KEY (chave_limite, idempotency_key)\n", TEN),
    # C2: `kamba_app` volta a poder criar o proprio entitlement.
    ("revisao 0007: a aplicacao volta a inserir entitlements", REV7,
     'op.execute("REVOKE INSERT, UPDATE ON platform.entitlements FROM kamba_app")',
     'op.execute("REVOKE UPDATE ON platform.entitlements FROM kamba_app")', TEN),
    # C3: o contador volta a poder descer. Tres caminhos: sem trigger, com o
    # trigger a nao verificar nada, e com o trigger a nao disparar fora da
    # sessao normal.
    ("revisao 0007: o contador deixa de ter trigger", REV7, _TEN_TRIGGER, "", TEN),
    ("revisao 0007: o contador volta a poder descer", REV7,
     "  IF NEW.valor < OLD.valor THEN", "  IF false THEN", TEN),
    ("revisao 0007: o trigger do contador deixa de ser ALWAYS", REV7,
     '"ALTER TABLE platform.tenant_usage ENABLE ALWAYS TRIGGER tenant_usage_so_sobe"',
     '"ALTER TABLE platform.tenant_usage ENABLE TRIGGER tenant_usage_so_sobe"', TEN),
    ("revisao 0007: a chave de uma linha de uso passa a poder mudar", REV7,
     "  IF NEW.tenant_id IS DISTINCT FROM OLD.tenant_id", "  IF false", TEN),
    # M1: o relogio nas maos de quem corre como a aplicacao.
    ("revisao 0007: a aplicacao volta a poder fixar o relogio", REV7,
     _TEN_RELOGIO, "", TEN),
    # M6: o tenant volta a poder retirar a condicao do criterio 2.
    ("revisao 0007: a aplicacao volta a alterar o proprio estado", REV7,
     '    "medusa_sales_channel_id, medusa_merchant_id, chatwoot_account_id, "\n'
     '    "litellm_key_id, fuso_horario, verificado_at, deleted_at"\n'
     ")",
     '    "estado, medusa_sales_channel_id, medusa_merchant_id, chatwoot_account_id, "\n'
     '    "litellm_key_id, fuso_horario, verificado_at, deleted_at"\n'
     ")",
     TEN),
    # m1/m2: um tecto que nao se sabe ler, e a soma que transborda.
    ("revisao 0007: um limite ilegivel volta a abortar a transaccao", REV7,
     "  SELECT min(CASE WHEN d.legivel THEN d.texto::bigint END),",
     "  SELECT min(d.texto::bigint),", TEN),
    ("revisao 0007: o tecto ilegivel deixa de ser nomeado", REV7,
     "  IF coalesce(v_ilegivel, false) THEN", "  IF false THEN", TEN),
    # **Esta substitui uma que sobreviveu.** A primeira versao punha a soma
    # do contador em `numeric` contra o transbordo, e a mutacao que a
    # devolvia a `bigint` **nao morreu**: com o tecto limitado a dezoito
    # algarismos, `valor + quantidade` nunca passa de 2 x 10^18 e o `bigint`
    # vai ate 9,2 x 10^18. O cast era defesa sobre uma porta ja fechada,
    # saiu, e a mutacao passou a morder na guarda que fecha mesmo: o tecto
    # de algarismos de um limite.
    ("revisao 0007: o tecto deixa de ter limite de algarismos", REV7,
     "              AND length(e.limites ->> p_chave) <= 18) AS legivel",
     "              AND length(e.limites ->> p_chave) <= 30) AS legivel", TEN),
    # m3: o aviso da ordem das chaves, que so existe no `COMMENT`.
    ("revisao 0007: o aviso da ordem das chaves desaparece", REV7,
     "    op.execute(_COMENTARIO_DA_CONSUMIR)\n", "", TEN),
    # m4: a chave de idempotencia vazia.
    ("revisao 0007: a chave de idempotencia vazia deixa de levantar", REV7,
     _TEN_CHAVE_VAZIA, "", TEN),
    # ----------------------------------------------------------- KAM-014
    #
    # O CHR e o sitio onde o `tenant_id` nasce, e por isso as mutacoes mordem
    # nas duas metades da pergunta: o que a **base** impede (a RLS, as FK
    # compostas, os privilegios por coluna, o dominio do motivo, a unicidade da
    # conversa) e o que o **codigo** impede (a cache que nao serve uma entrada
    # expirada, o estado que nao se adivinha, a ordem dos passos, o `wamid` que
    # nao sai em claro).
    #
    # Cada uma escolhe a suite mais **estreita** que a apanha: a `tests_chr`
    # corre o modulo contra os tres papeis e e onde quase todas caem; a
    # `tests_isolamento` apanha a que tira a politica, porque e o X-05 que
    # nomeia a tabela; a `tests` apanha as que mexem nas FK e nas restricoes,
    # que o inventario fechado enumera; a `tests_entrada` apanha o dominio do
    # motivo, porque e la que as tres fontes se comparam.
    #
    # A forma `if (x && false)` em vez de `if (false)`: tem o mesmo efeito e
    # nao e codigo inalcancavel declarado, que o `tsc` recusaria se alguem
    # corresse o `typecheck` sobre a copia.
    #
    # **A primeira e a mutacao de um defeito que existiu.** Com a politica de
    # pe, o dono da tabela conta zero linhas sobre uma tabela cheia, e o
    # `downgrade` apaga as conversas em silencio em vez de pedir a copia logica.
    # Era o que a primeira versao da revisao fazia, e foi o
    # `test_conversas_schema.py` que o apanhou — a mesma armadilha que o
    # `docs/isolamento.md` §6 escreve para a validacao de uma FK nova.
    # ------------------------------------------------- KAM-015, revisao 0010
    #
    # Cada uma nomeia a propriedade que se perde. As quatro primeiras sao as
    # divergencias que a emenda 1.21 assumiu: se uma mutacao que as desfaz
    # sobrevive, a divergencia estava escrita e nao estava protegida.
    ('revisao 0010: a chave de idempotencia passa a ser global', REV10,
     '            CONSTRAINT outbound_messages_idempotency_uq\n                UNIQUE (tenant_id, idempotency_key),',
     '            CONSTRAINT outbound_messages_idempotency_uq\n                UNIQUE (idempotency_key),', SAIDA),
    ('revisao 0010: a FK da conversa deixa de levar o tenant', REV10,
     '            CONSTRAINT outbound_messages_conversation_fk\n                FOREIGN KEY (tenant_id, conversation_id)\n                REFERENCES platform.conversations (tenant_id, id),',
     '            CONSTRAINT outbound_messages_conversation_fk\n                FOREIGN KEY (conversation_id)\n                REFERENCES platform.conversations (id),', "tests"),
    ('revisao 0010: a FK do canal deixa de levar o tenant', REV10,
     '            CONSTRAINT outbound_messages_channel_fk\n                FOREIGN KEY (tenant_id, channel_id)\n                REFERENCES platform.tenant_channels (tenant_id, id),',
     '            CONSTRAINT outbound_messages_channel_fk\n                FOREIGN KEY (channel_id)\n                REFERENCES platform.tenant_channels (id),', "tests"),
    ('revisao 0010: a mensagem de saida fica sem RLS (gate 6)', REV10,
     '    rls.enable_tenant_rls("outbound_messages")\n',
     '', ISOLAMENTO),
    ('revisao 0010: o template fica sem RLS (gate 6)', REV10,
     '    rls.enable_tenant_rls("message_templates")\n',
     '', ISOLAMENTO),
    # O defeito que a `0009` pagou, repetido aqui de proposito: com `FORCE`, o
    # dono esta sujeito a politica e uma migracao corre sem contexto, logo
    # contar antes de desligar ve zero linhas e apaga em silencio.
    ('revisao 0010: o downgrade conta os envios com a politica de pe', REV10,
     '    rls.disable_tenant_rls("outbound_messages")\n    rls.disable_tenant_rls("message_templates")\n\n    envios = _contar_envios()',
     '    envios = _contar_envios()\n    rls.disable_tenant_rls("outbound_messages")\n    rls.disable_tenant_rls("message_templates")\n', "tests"),
    # **Suite `tests` e nao `tests_outbound`**, e a diferenca foi medida: quem
    # apanha um privilegio de coluna a mais e a matriz do `test_privilegios.py`,
    # que vive na suite das migracoes. Declarada na suite da saida, esta mutacao
    # **sobreviveu** — corria os testes do modulo, que nao olham para `GRANT`
    # nenhum, e a prova dizia «nao apanhada» sem que faltasse teste nenhum.
    ('revisao 0010: a aplicacao passa a poder reescrever a chave de idempotencia', REV10,
     'COLUNAS_DA_APLICACAO = (\n    "state",',
     'COLUNAS_DA_APLICACAO = (\n    "idempotency_key",\n    "state",', "tests"),
    ('revisao 0010: a aplicacao passa a poder inserir templates', REV10,
     'op.execute("GRANT SELECT ON platform.message_templates TO kamba_app")',
     'op.execute("GRANT SELECT, INSERT ON platform.message_templates TO kamba_app")', ISOLAMENTO),
    ('revisao 0010: o estado de saida perde o suppressed_by_human', REV10,
     '    "\'failed\'",\n    "\'suppressed_by_human\'",\n)',
     '    "\'failed\'",\n)', "tests"),
    ('revisao 0010: um instante de entrega passa a caber em qualquer estado', REV10,
     '            CONSTRAINT outbound_messages_entrega_ck',
     '            CONSTRAINT outbound_messages_entrega_sem_regra_ck', "tests"),
    ('revisao 0010: uma utility passa a poder ir sem template', REV10,
     '            CONSTRAINT outbound_messages_template_ck',
     '            CONSTRAINT outbound_messages_template_sem_regra_ck', "tests"),
    ('revisao 0010: a conversa perde a unicidade que a FK precisa', REV10,
     '        "ADD CONSTRAINT conversations_tenant_id_uq UNIQUE (tenant_id, id)"',
     '        "ADD CONSTRAINT conversations_tenant_id_uq UNIQUE (id)"', "tests"),
    # ------------------------------------------- KAM-015, o modulo de saida
    ('saida: a monotonia deixa de proteger os terminais', SAIDA_ESTADOS,
     '  if (terminal(actual)) {\n    return { estado: actual, avancou: false, entregou: false };\n  }',
     '  if (false) {\n    return { estado: actual, avancou: false, entregou: false };\n  }', SAIDA),
    ('saida: a entrega passa a contar-se ao chegar e nao ao atravessar', SAIDA_ESTADOS,
     '  const entregou = de < ordemDoDelivered && para >= ordemDoDelivered;',
     '  const entregou = para === ordemDoDelivered;', SAIDA),
    ('saida: o ON CONFLICT da idempotencia desaparece', SAIDA_SQL,
     '      ON CONFLICT (tenant_id, idempotency_key) DO NOTHING',
     '', SAIDA),
    ('saida: o avanco de estado deixa de ter a monotonia no predicado', SAIDA_SQL,
     '     AND antes.state = ANY($4::text[])',
     '', SAIDA),
    ('saida: o bloqueio de template deixa de preservar o primeiro instante', SAIDA_SQL,
     '   WHERE tenant_id = $1 AND name = $2 AND lang = $3 AND bloqueado_em IS NULL',
     '   WHERE tenant_id = $1 AND name = $2 AND lang = $3', SAIDA),
    # KAM-017 tocou nesta linha: o `this.#mps` passou a `debito`, que e o
    # `mpsDoModo(modo)` quando o modo vem, e o `#mps` do construtor quando nao
    # vem. **A mutacao e a mesma** — o balde a nascer cheio — e so o texto
    # mudou; reescreve-se em vez de se apagar, porque o que ela mata continua a
    # fazer falta (um balde cheio a nascer deixa passar uma rajada no primeiro
    # instante, e e o criterio 5 do KAM-015 que isso quebra).
    ('saida: o balde do canal volta a nascer cheio', SAIDA_LIMITES,
     'const canal = this.#balde(this.#porCanal, phoneNumberId, debito, agoraMs, false);',
     'const canal = this.#balde(this.#porCanal, phoneNumberId, debito, agoraMs, true);',
     SAIDA),
    ('saida: o 131049 passa a repetir-se', SAIDA_LIMITES,
     'export const CODIGOS_QUE_SE_REPETEM: readonly number[] = [',
     'export const CODIGOS_QUE_SE_REPETEM: readonly number[] = [\n  131049,',
     SAIDA),
    ('saida: o jitter passa a poder dar zero', SAIDA_LIMITES,
     '  return Math.round(base / 2 + (base / 2) * aleatorio);',
     '  return Math.round(base * aleatorio);', SAIDA),
    ('saida: a tarifa de marketing passa a ser a de utility', SAIDA_TARIFAS,
     '  marketing: 22_500,',
     '  marketing: 4_000,', SAIDA),
    ('saida: uma categoria desconhecida passa a custar o de service', SAIDA_TARIFAS,
     '  return tarifa === undefined ? 0 : tarifa;',
     '  return tarifa === undefined ? 4_000 : tarifa;', SAIDA),
    ('saida: a forma deixa de se verificar antes da janela', SAIDA_DECISAO,
     '  const forma = formaInvalida(corpo);\n  if (forma !== null) return { enviar: false, motivo: forma };',
     '', SAIDA),
    ('saida: um template bloqueado passa a poder ser usado', SAIDA_DECISAO,
     '  if (template.bloqueadoEm !== null) return { enviar: false, motivo: "TEMPLATE_BLOCKED" };',
     '', SAIDA),
    # As tres abaixo sao das correccoes que o ensaio do adapter (gate 4) e o do
    # esquema (suite `tests`) apanharam: cada uma volta o codigo ao defeito
    # medido, para que deixar de o apanhar seja uma sobrevivente e nao silencio.
    ('saida: o token bucket deixa de pedir em ciclo', SAIDA_ADAPTER,
     '      if (espera === 0) break;',
     '      if (espera === 0) break;\n      if (true) { await this.#dormir(espera); break; }', SAIDA),
    ('saida: as repeticoes do 130429 passam a ser duas', SAIDA_LIMITES,
     'export const REPETICOES = 3;', 'export const REPETICOES = 2;', SAIDA),
    ('revisao 0010: o instante de entrega deixa de caber nos terminais', REV10,
     "                       OR state IN ('delivered', 'read', 'failed',\n                                    'suppressed_by_human')),",
     "                       OR state IN ('delivered', 'read')),", "tests"),
    # As quatro abaixo sao da revisao adversarial do ticket, e cada uma volta o
    # codigo ao defeito que ela apanhou. As duas primeiras sao dinheiro.
    ('saida: o custo volta a sair da leitura previa e nao da base', SAIDA_ADAPTER,
     '    const anterior = linhas.rows[0]?.estado_antes as Estado | undefined;',
     '    const anterior = actual.state as Estado | undefined;', SAIDA),
    ('saida: o paraMostrar volta a perder o transporte', SAIDA_TARIFAS,
     '  const centavos = Math.round(microUsd / 10_000);\n  const dolares = Math.floor(centavos / 100);\n  return `${dolares}.${String(centavos % 100).padStart(2, "0")}`;',
     '  const dolares = Math.trunc(microUsd / MICRO_USD_POR_USD);\n  const resto = microUsd % MICRO_USD_POR_USD;\n  return `${dolares}.${String(Math.round(resto / 10_000)).padStart(2, "0")}`;', SAIDA),
    ('saida: o error_code volta a levar o sinal para o registo', SAIDA_ADAPTER,
     '  return Number.isInteger(codigo) && codigo >= 0 ? String(codigo) : SEM_CODIGO_NO_REGISTO;',
     '  return String(codigo);', SAIDA),
    ('saida: uma espera longa volta a ser dormida em vez de recusada', SAIDA_ADAPTER,
     '      if (espera > ESPERA_MAXIMA_DE_DEBITO_MS) {',
     '      if (false) {', SAIDA),
    # ------------------------------------------------- KAM-019 (0011 e hnd)
    ('revisao 0011: a passagem perde um estado do dominio', REV11,
     'ESTADOS_DE_HANDOFF = (\n    "\'waiting\'",\n    "\'resumed\'",',
     'ESTADOS_DE_HANDOFF = (\n    "\'waiting\'",', "tests"),
    ('revisao 0011: a FK da conversa deixa de levar o tenant', REV11,
     '                FOREIGN KEY (tenant_id, conversation_id)\n                REFERENCES platform.conversations (tenant_id, id),',
     '                FOREIGN KEY (conversation_id)\n                REFERENCES platform.conversations (id),', "tests"),
    ('revisao 0011: a passagem fica sem RLS (gate 6)', REV11,
     '    rls.enable_tenant_rls("handoffs")',
     '    pass  # rls.enable_tenant_rls("handoffs")', "tests_isolamento"),
    ('revisao 0011: a conta de atendimento fica sem RLS (gate 6)', REV11,
     '    rls.enable_tenant_rls("handoff_accounts")',
     '    pass  # rls.enable_tenant_rls("handoff_accounts")', "tests_isolamento"),
    # **Declarada em `tests` e nao em `tests_handoff`**, e a prova por mutacao foi
    # o que o mostrou. Em `tests_handoff` ela sobrevivia: apagada a restricao, a
    # `handoff_accounts_utilizador_uq` apanhava o mesmo caso e a assercao do
    # ensaio de base aceitava qualquer «duplicate key». O teste do ensaio foi
    # apertado (assercao pelo **nome** da restricao, e o utilizador deliberadamente
    # diferente), e a mutacao passou para a suite onde a `test_handoff_schema`
    # afirma as tres restricoes uma a uma. Uma mutacao na suite errada e pior do
    # que nenhuma.
    ('revisao 0011: a conta do provedor deixa de ser unica', REV11,
     '            CONSTRAINT handoff_accounts_conta_uq UNIQUE (provedor, account_id),',
     '', "tests"),
    ('revisao 0011: o downgrade conta as passagens com a politica de pe', REV11,
     '    rls.disable_tenant_rls("handoffs")\n    rls.disable_tenant_rls("handoff_accounts")',
     '    pass  # as politicas ficam de pe', "tests"),
    ('revisao 0011: a aplicacao passa a poder reescrever o handoff_id', REV11,
     'COLUNAS_DA_APLICACAO = (\n    "status",',
     'COLUNAS_DA_APLICACAO = (\n    "handoff_id",\n    "status",', "tests"),
    # **A inversa da anterior**: a primeira versao desta mutacao punha o
    # `account_id` na lista de colunas alteraveis, e a lista deixou de
    # existir — a `0011` ja nao concede `UPDATE` em `handoff_accounts`. O que
    # se vigia agora e o caminho de volta: alguem a reconceder.
    ('revisao 0011: a aplicacao volta a poder escrever na conta', REV11,
     '    # Sem `GRANT UPDATE` em `handoff_accounts`. Ver a nota de',
     '    op.execute("GRANT UPDATE (token_ref) ON platform.handoff_accounts "\n               "TO kamba_app")\n    # Sem `GRANT UPDATE` em `handoff_accounts`. Ver a nota de',
     "tests"),
    ('revisao 0011: o utilizador do provedor deixa de ser unico', REV11,
     '            CONSTRAINT handoff_accounts_utilizador_uq\n                UNIQUE (provedor, provider_user_id),',
     '', "tests"),
    # **Esta era imortal por redundancia**, e a prova por mutacao foi o que o
    # mostrou: apagar o `if (esperado.length === 0) return false;` nao muda
    # comportamento nenhum, porque a verificacao de comprimento tres linhas
    # abaixo ja recusa um esperado vazio (os comprimentos diferem, salvo se o
    # recebido tambem for vazio — e esse cai na linha do meio). A linha fica,
    # porque diz a intencao; o que muda e a mutacao, que passa a inverter o
    # **sentido** em vez de apagar a linha. Essa morre.
    ('handoff: um segredo esperado vazio passa a aceitar tudo', HND_ASSINATURA,
     '  if (esperado.length === 0) return false;',
     '  if (esperado.length === 0) return true;', HANDOFF),
    # **E aqui estava a segunda imortal, e sai sem substituta.** A mutacao
    # trocava `timingSafeEqual(a, b)` por `recebido === esperado`, e nesse ponto
    # do codigo os dois buffers ja tem o mesmo comprimento: as duas expressoes
    # dao **o mesmo resultado** para toda a entrada. A diferenca e o tempo, e o
    # tempo nao e observavel num teste unitario — medi-lo pediria uma bateria
    # estatistica que esta maquina nao consegue correr sem falsos vermelhos.
    #
    # Fica dito em vez de fingido: **a propriedade de tempo constante nao tem
    # teste**. O que a sustenta e a leitura, e e por isso que a razao esta
    # escrita no `assinatura.ts` e no `docs/hnd.md`. Uma mutacao que nenhum
    # teste pode matar contaria como prova de uma garantia que nao temos, que e
    # pior do que nao a ter.
    ('handoff: o comprimento deixa de ser tratado antes de comparar', HND_ASSINATURA,
     '  if (a.length !== b.length) return false;',
     '', HANDOFF),
    ('handoff: a conta desconhecida deixa de recusar o callback', HND_ASSINATURA,
     '  if (!contaConhecida) {',
     '  if (false) {', HANDOFF),
    ('handoff: o eco do proprio espelho volta a contar como resposta', HND_EVENTOS,
     '    if (texto(corpo["message_type"]) !== "outgoing") return null;',
     '', HANDOFF),
    ('handoff: o nome do agente passa a entrar no resolver', HND_EVENTOS,
     '  const id = remetente["id"];',
     '  const id = remetente["name"] ?? remetente["id"];', HANDOFF),
    ('handoff: o resolved deixa de dar resumed', HND_ESTADOS,
     '  resolved: "resumed",',
     '  resolved: "timeout",', HANDOFF),
    ('handoff: o snoozed do provedor passa a fechar a passagem', HND_ESTADOS,
     '  return estado === "resolved" ? "resolved" : null;',
     '  return "resolved";', HANDOFF),
    ('handoff: o ON CONFLICT da abertura desaparece', HND_SQL,
     '      ON CONFLICT (handoff_id) DO NOTHING',
     '', HANDOFF),
    ('handoff: o ON CONFLICT da conta desaparece', HND_SQL,
     '      ON CONFLICT (tenant_id, provedor) DO NOTHING',
     '', HANDOFF),
    ('handoff: o fecho deixa de ter a monotonia no predicado', HND_SQL,
     '     AND status = ANY($3::text[])',
     '', HANDOFF),
    # **Esta era imortal e agora nao e.** A primeira versao trocava o
    # `WHERE tenant_id = ...` por `WHERE true`, e nenhum teste a podia
    # matar: a base falsa impoe o tenant em JavaScript, pelo que o texto do
    # SQL nunca e lido, e sob RLS, para `kamba_app`, `WHERE true` e
    # semanticamente **igual** ao predicado. Uma mutacao que nenhum teste
    # pode matar e pior do que nenhuma, porque conta como prova.
    #
    # O que se vigia agora e o que **se ve**: a forma estrita do
    # `current_setting`. Com o segundo argumento ele devolve NULL em vez de
    # levantar, e um `close` sem contexto de sessao volta a nao casar nada em
    # silencio. O ensaio de base tem um teste que o chama sem contexto e
    # exige a excepcao.
    ('handoff: o fecho volta a aceitar a falta de contexto', HND_SQL,
     "current_setting('app.tenant_id')",
     "current_setting('app.tenant_id', true)", HANDOFF),
    ('handoff: o account_id do bot volta a poder ir nulo', HND_CHATWOOT,
     '        account_id: conta.id,',
     '        account_id: null,', HANDOFF),
    ('handoff: o inbox volta a poder ser de WhatsApp', HND_CHATWOOT,
     'export const TIPO_DE_INBOX = "api";',
     'export const TIPO_DE_INBOX = "whatsapp";', HANDOFF),
    ('handoff: um 4xx volta a degradar como se fosse 5xx', HND_CHATWOOT,
     '      if (resposta.status >= 500) {',
     '      if (!resposta.ok) {', HANDOFF),
    # O `resposta.ts` nasceu depois deste bloco e ficou sem nenhuma mutacao,
    # que e a mesma classe de esquecimento que deixou a bateria dele fora da
    # lista do gate. Sao quatro, uma por decisao que o criterio 6 pede.
    # As oito que prendem o que o spike mediu e a revisao adversarial apanhou.
    # Cada uma e um defeito que **estava** no codigo e passou por baterias
    # verdes: sao o registo de que a correccao nao se desfaz sem alguem notar.
    ('handoff: o inbox volta a ser criado com o token da plataforma', HND_CHATWOOT,
     '      `/api/v1/accounts/${conta.id}/inboxes`,\n      utilizador.access_token,',
     '      `/api/v1/accounts/${conta.id}/inboxes`,\n      this.#tokenDaPlataforma,',
     HANDOFF),
    ('handoff: o bot deixa de ser ligado ao inbox', HND_CHATWOOT,
     '    await this.#chamador.vazio(\n      "POST",\n      `/api/v1/accounts/${conta.id}/inboxes/${caixa.id}/set_agent_bot`,',
     '    await Promise.resolve(\n      "POST",\n      `/api/v1/accounts/${conta.id}/inboxes/${caixa.id}/set_agent_bot`,',
     HANDOFF),
    ('handoff: a conversa volta a levar a chave do contacto no source_id', HND_CHATWOOT,
     '        source_id: origem,',
     '        source_id: abertura.chaveDoContacto,', HANDOFF),
    ('handoff: o contacto le payload em vez de payload.contact', HND_CHATWOOT,
     'const origem = contacto.payload?.contact?.contact_inboxes?.[0]?.source_id;',
     'const origem = (contacto.payload as { contact_inboxes?: { source_id?: string }[] })?.contact_inboxes?.[0]?.source_id;',
     HANDOFF),
    ('handoff: o espelho volta a por o wamid no URL', HND_CHATWOOT,
     '`/api/v1/accounts/${conta.accountId}/conversations/${externalId}/messages`',
     '`/api/v1/accounts/${conta.accountId}/conversations/${m.wamid}/messages`',
     HANDOFF),
    ('handoff: o resolver do callback volta a ser perdido', HND_PROVEDOR,
     'await this.#fechar(acontecimento.handoffId, outcome, acontecimento.resolver);',
     'await this.#fechar(acontecimento.handoffId, outcome, null);', HANDOFF),
    ('handoff: o marcar_aberta volta a descartar o resultado', HND_PROVEDOR,
     '    if (marcada.rows.length === 0) {',
     '    if (false) {', HANDOFF),
    ('handoff: o callback sem segredo volta a consultar primeiro', HND_PROVEDOR,
     '    if (segredoRecebido === null || segredoRecebido.length === 0) {',
     '    if (false) {', HANDOFF),
    # ------------------------------------------- KAM-020 (0012 e med)
    #
    # A divisao por suite nao e arbitraria: o que a base impoe vai a `tests`
    # (que corre a `test_media_schema`), o que a RLS impoe vai a
    # `tests_isolamento`, e o que o modulo decide vai a `tests_media` — que e a
    # unica que **le o texto do SQL**, porque corre contra um PostgreSQL. Uma
    # mutacao de SQL declarada numa suite com base falsa e imortal, e foi o que
    # o KAM-019 pagou.
    ('revisao 0012: a midia perde um estado do dominio', REV12,
     'ESTADOS_DE_MIDIA = (\n    "\'pendente\'",',
     'ESTADOS_DE_MIDIA = (', "tests"),
    ('revisao 0012: a midia perde uma classe do dominio', REV12,
     'CLASSES_DE_MIDIA = ("\'media_audio\'", "\'media_imagem\'", "\'media_documento\'")',
     'CLASSES_DE_MIDIA = ("\'media_audio\'", "\'media_imagem\'")', "tests"),
    ('revisao 0012: a origem deixa de ser unica', REV12,
     '            CONSTRAINT media_assets_origem_uq UNIQUE (tenant_id, wamid, media_id),',
     '', "tests"),
    ('revisao 0012: a unicidade da origem perde o tenant', REV12,
     'media_assets_origem_uq UNIQUE (tenant_id, wamid, media_id)',
     'media_assets_origem_uq UNIQUE (wamid, media_id)', MEDIA),
    # **A ancora leva o inicio da restricao inteira**, e nao uma linha dentro
    # dela. A primeira versao ancorava em `storage_ref IS NOT NULL` e apaga-la
    # deixava `OR (` seguido de `AND ...` — **SQL que nao analisa**: o `alembic
    # upgrade` falhava, a suite inteira ficava vermelha, e a mutacao contava
    # como apanhada sem nunca ter criado a tabela. Uma mutacao que morre por
    # sintaxe mede o PostgreSQL e nao o teste. Apanhada pela revisao
    # adversarial.
    ('revisao 0012: o armazenado deixa de exigir a chave', REV12,
     "            CONSTRAINT media_assets_armazenado_ck\n                CHECK (\n                    estado <> 'armazenado'",
     "            CONSTRAINT media_assets_armazenado_ck\n                CHECK (\n                    estado = estado\n                    OR estado <> 'armazenado'", "tests"),
    ('revisao 0012: a FK do contacto deixa de levar o tenant', REV12,
     '                FOREIGN KEY (tenant_id, contact_id)\n                REFERENCES platform.contacts (tenant_id, contact_id),',
     '                FOREIGN KEY (contact_id)\n                REFERENCES platform.contacts (contact_id),',
     "tests"),
    ('revisao 0012: a midia fica sem RLS (gate 6)', REV12,
     '    rls.enable_tenant_rls("media_assets")',
     '    pass  # rls.enable_tenant_rls("media_assets")', "tests_isolamento"),
    ('revisao 0012: o downgrade conta a midia com a politica de pe', REV12,
     '    rls.disable_tenant_rls("media_assets")',
     '    pass  # a politica fica de pe', "tests"),
    ('revisao 0012: a aplicacao passa a poder reescrever o wamid', REV12,
     'COLUNAS_DA_APLICACAO = (\n    "content_type",',
     'COLUNAS_DA_APLICACAO = (\n    "wamid",\n    "content_type",', "tests"),
    # **E a `classe`, que a revisao adversarial tirou da lista.** Reconceder-a
    # permite reclassificar um objecto, que muda a coluna de que depende a
    # politica de retencao do KAM-071 — um audio reclassificado como imagem
    # deixa de ter prazo e fica para sempre.
    ('revisao 0012: a aplicacao volta a poder reclassificar', REV12,
     'COLUNAS_DA_APLICACAO = (\n    "content_type",',
     'COLUNAS_DA_APLICACAO = (\n    "classe",\n    "content_type",', "tests"),
    ('revisao 0012: o sha256 deixa de ter forma', REV12,
     "                CHECK (sha256 IS NULL OR sha256 ~ '^[0-9a-f]{{64}}$')",
     '                CHECK (sha256 IS NULL)', "tests"),
    # O modulo: o que ele decide, e cada uma morre numa bateria do gate 4 ou no
    # ensaio de base.
    ('media: o sticker deixa de ser imagem', MED_CLASSES,
     '  sticker: "media_imagem",',
     '', MEDIA),
    ('media: a allowlist de documentos abre-se', MED_CLASSES,
     '    tipos: ["application/pdf"],',
     '    tipos: ["application/pdf", "application/zip"],', MEDIA),
    ('media: o tamanho passa a ser verificado antes do tipo', MED_CLASSES,
     '  if (!permitido) return "tipo_nao_permitido";\n  if (tamanho > limite.bytesMaximos) return "tamanho_excedido";',
     '  if (tamanho > limite.bytesMaximos) return "tamanho_excedido";\n  if (!permitido) return "tipo_nao_permitido";',
     MEDIA),
    ('media: o limite de tamanho passa a recusar no limite', MED_CLASSES,
     '  if (tamanho > limite.bytesMaximos) return "tamanho_excedido";',
     '  if (tamanho >= limite.bytesMaximos) return "tamanho_excedido";', MEDIA),
    ('media: a resposta ao cliente passa a citar o tipo', MED_CLASSES,
     '    "Esse ficheiro e grande demais para mim. Pode enviar um mais pequeno?",',
     '    "Esse ficheiro e grande demais (mais de 5242880 bytes).",', MEDIA),
    ('media: o ON CONFLICT da reserva desaparece', MED_SQL,
     '      ON CONFLICT (tenant_id, wamid, media_id) DO NOTHING',
     '', MEDIA),
    ('media: a marcacao deixa de ter a monotonia no predicado', MED_SQL,
     "     AND estado = 'pendente'\n   RETURNING asset_id, estado\n`;\n\n/**\n * Marca a linha como rejeitada ou falhada.",
     "   RETURNING asset_id, estado\n`;\n\n/**\n * Marca a linha como rejeitada ou falhada.",
     MEDIA),
    # **Aqui estava a mutacao do `SQL_POR_ASSET`, e sai sem substituta.**
    #
    # Ela tirava o `tenant_id = $1` do predicado, e a revisao adversarial
    # mostrou que morria **por acidente**: a base falsa despacha por
    # `texto.includes("AND asset_id = $2")`, e sem o predicado o texto deixava
    # de casar o despacho — o `urlInterna` passava a devolver sempre `null` e
    # os testes caiam por isso, nao pela propriedade.
    #
    # **E pela propriedade ela e inobservavel:** na base verdadeira a RLS
    # esconde a linha do outro tenant, e na base falsa o `#porAsset` impoe o
    # tenant em JavaScript. Uma mutacao que nenhum teste pode matar pela razao
    # certa conta como prova de uma garantia que nao temos — e o que sustenta o
    # isolamento aqui e a politica `tenant_iso`, cuja mutacao esta declarada em
    # `tests_isolamento` e essa morre.
    ('media: a allowlist volta a correr no tipo anunciado', MED_PIPELINE,
     '    const motivo = recusar(classe, contentType, bytes.byteLength, this.#limites);',
     '    const motivo = recusar(classe, pedido.contentTypeAnunciado ?? contentType, bytes.byteLength, this.#limites);',
     MEDIA),
    # **A ordem dos passos nao se muta por troca de linhas** — isso daria um
    # ficheiro que nem compila, e a prova por mutacao mediria o `tsc` e nao os
    # testes. O que se muta e o **efeito** da reserva vir primeiro: faz-se a
    # leitura antes dela, que e o que um codigo que a puxasse para depois da
    # descarga faria. A idempotencia deixa de ser da base e passa a ser de uma
    # verificacao que duas chamadas concorrentes atravessam as duas.
    # **A ordem dos passos nao se muta por troca de linhas** — isso daria um
    # ficheiro que nem compila, e a prova mediria o `tsc` e nao os testes. O
    # que se muta e o **efeito** de a reserva vir primeiro: faz-se a leitura
    # antes dela, que e o que um codigo que a puxasse para depois da descarga
    # faria. A idempotencia deixa de ser da base e passa a ser de uma
    # verificacao que duas chamadas concorrentes atravessam as duas — e e o
    # ensaio de base, com duas ligacoes, que o apanha.
    ('media: a reserva passa a ser precedida de uma leitura', MED_PIPELINE,
     '    // **Passo 2: a reserva, e é aqui que a idempotência acontece.**\n    const reserva = await this.#bd.query<{ asset_id: string }>(SQL_RESERVAR, [',
     '    const antes = await this.#bd.query<{ asset_id: string }>(SQL_POR_ORIGEM, [\n      pedido.tenantId,\n      pedido.wamid,\n      pedido.mediaId,\n    ]);\n    if (antes.rows.length > 0) return this.#comoEsta(pedido, classe);\n    const reserva = await this.#bd.query<{ asset_id: string }>(SQL_RESERVAR, [', MEDIA),
    ('media: as tentativas passam de tres para uma', MED_PIPELINE,
     'export const TENTATIVAS = 3;',
     'export const TENTATIVAS = 1;', MEDIA),
    ('media: o AGR deixa de ser avisado', MED_PIPELINE,
     '    await this.#avisarAgr({',
     '    await Promise.resolve({', MEDIA),
    ('media: a retencao do audio passa a valer para tudo', MED_PIPELINE,
     '      classe === "media_audio"\n        ? new Date(agora.getTime() + RETENCAO_DE_AUDIO_MS)\n        : null;',
     '      new Date(agora.getTime() + RETENCAO_DE_AUDIO_MS);', MEDIA),
    ('media: a retencao do audio deixa de existir', MED_PIPELINE,
     'export const RETENCAO_DE_AUDIO_MS = 24 * 60 * 60 * 1000;',
     'export const RETENCAO_DE_AUDIO_MS = 100 * 365 * 24 * 60 * 60 * 1000;', MEDIA),
    ('media: o TTL da url interna passa a ser escrito a mao', MED_PIPELINE,
     'export const TTL_DA_URL_INTERNA_S = TTL_MAXIMO_S;',
     'export const TTL_DA_URL_INTERNA_S = 600;', MEDIA),
    # A ancora leva a linha de cima porque ha agora **tres** verificacoes de
    # `rows.length === 0` no ficheiro: a revisao adversarial apanhou que os
    # dois caminhos de desfecho descartavam o resultado, e eles passaram a
    # le-lo. Esta e a do `armazenado`.
    ('media: o resultado da marcacao volta a ser descartado', MED_PIPELINE,
     '      retainUntil,\n    ]);\n    if (marcada.rows.length === 0) {',
     '      retainUntil,\n    ]);\n    if (false) {', MEDIA),
    # E as duas que a correccao criou, uma por caminho de desfecho.
    ('media: a rejeicao volta a descartar o resultado', MED_PIPELINE,
     '      "rejeitado",\n    ]);\n    if (marcada.rows.length === 0) {',
     '      "rejeitado",\n    ]);\n    if (false) {', MEDIA),
    ('media: a falha volta a descartar o resultado', MED_PIPELINE,
     '      "falhou",\n    ]);\n    if (marcada.rows.length === 0) {',
     '      "falhou",\n    ]);\n    if (false) {', MEDIA),
    ('media: um wa_type desconhecido passa a reservar linha', MED_PIPELINE,
     '    if (classe === null) {',
     '    if (false as boolean) {', MEDIA),
    ('handoff: a chave de idempotencia passa a derivar do texto', HND_RESPOSTA,
     'idempotencyKey: `hnd:${acontecimento.handoffId}:${acontecimento.mensagemId}`,',
     'idempotencyKey: `hnd:${acontecimento.handoffId}:${texto}`,', HANDOFF),
    ('handoff: a resposta humana passa a pedir licenca ao guarda', HND_RESPOSTA,
     '    doBot: false,',
     '    doBot: true,', HANDOFF),
    ('handoff: envia-se sem identificador do provedor', HND_RESPOSTA,
     '  if (acontecimento.mensagemId === null) {',
     '  if (false) {', HANDOFF),
    ('handoff: a janela fechada deixa de avisar o painel', HND_RESPOSTA,
     '    await avisarPainel({',
     '    await Promise.resolve({', HANDOFF),
    ('saida: a janela fechada deixa de recusar o envio livre', SAIDA_DECISAO,
     '      return { enviar: false, motivo: WINDOW_CLOSED };',
     '      return { enviar: true, kind: "service", templateName: null };', SAIDA),
    ('revisao 0009: o downgrade conta as conversas com a politica de pe', REV9,
     '    rls.disable_tenant_rls("conversations")\n    quantas = _contar()',
     '    quantas = _contar()\n    rls.disable_tenant_rls("conversations")',
     "tests"),
    ('revisao 0009: a conversa fica sem RLS (gate 6)', REV9,
     '    rls.enable_tenant_rls("conversations")\n',
     '', ISOLAMENTO),
    ('revisao 0009: a FK do canal deixa de levar o tenant', REV9,
     '                FOREIGN KEY (tenant_id, channel_id)\n                REFERENCES platform.tenant_channels (tenant_id, id),',
     '                FOREIGN KEY (channel_id)\n                REFERENCES platform.tenant_channels (id),', "tests"),
    ('revisao 0009: a FK do contacto deixa de levar o tenant', REV9,
     '                FOREIGN KEY (tenant_id, contact_id)\n                REFERENCES platform.contacts (tenant_id, contact_id),',
     '                FOREIGN KEY (contact_id)\n                REFERENCES platform.contacts (contact_id),', "tests"),
    ('revisao 0009: a unicidade da conversa perde o canal', REV9,
     '                UNIQUE (tenant_id, contact_id, channel_id)',
     '                UNIQUE (tenant_id, contact_id)', CHR),
    ('revisao 0009: a aplicacao passa a poder mudar o modo', REV9,
     'COLUNAS_DA_APLICACAO = ("last_inbound_at", "window_expires_at")',
     'COLUNAS_DA_APLICACAO = ("last_inbound_at", "window_expires_at", "mode")', CHR),
    ('revisao 0009: a janela deixa de ter de ser coerente', REV9,
     '            CONSTRAINT conversations_janela_ck',
     '            CONSTRAINT conversations_janela_sem_regra_ck', "tests"),
    # Os dois motivos do encaminhamento escolhem a `tests_chr` e **nao** a
    # `tests_entrada`, que seria o sitio onde as tres fontes do dominio se
    # comparam: a suite de entrada lanca os processos de producao do GWY e do
    # *worker*, e a copia da prova por mutacao nao leva `services/` nem o
    # `package.json` da raiz — nenhuma mutacao a pode escolher hoje (divida
    # registada). A `tests_chr` apanha-as de forma mais directa: sem o valor no
    # `CHECK`, a insercao da quarentena do CHR falha e o criterio 2 fica
    # vermelho contra o `CHECK` verdadeiro.
    ('revisao 0008: o motivo do canal desconhecido sai do dominio', REV8,
     '    "\'canal_desconhecido\'",\n',
     '', CHR),
    ('revisao 0008: o motivo da mensagem sem identidade sai do dominio', REV8,
     '    "\'mensagem_sem_identidade\'",\n',
     '', CHR),
    ('chr: a entrada expirada fica a servir de resposta', CHR_CANAL,
     '      // Expirou: sai antes de se ir à base, para que uma falha da base não\n      // deixe uma entrada velha a servir de resposta.\n      this.#esquecer(phoneNumberId);',
     '      // Expirou.', CHR),
    ('chr: um estado de canal desconhecido passa a ser aceite', CHR_CANAL,
     '  if (!ESTADOS_DE_CANAL.includes(estadoCanal)) {\n    throw new CanalIlegivelError("estado_canal");\n  }\n',
     '', CHR),
    ('chr: a guarda do Fluxo B deixa de ver a vertical', CHR_FLUXO_B,
     '  if (!permitidas.includes(contexto.vertical)) {',
     '  if (permitidas.includes(contexto.vertical)) {', CHR),
    ('chr: a guarda de arranque deixa de provar que ve tudo', CHR_FLUXO_B,
     '  const visivel = await cliente.query(SQL_VISIBILIDADE, []);\n  if (visivel.rows[0]?.ve_tudo !== true) throw new GuardaCegaError();\n',
     '', CHR),
    ('chr: o Fluxo B deixa de recusar e segue para a matriz', CHR_MODULO,
     '    if (recusa !== null) {',
     '    if (recusa === null && false) {', CHR),
    ('chr: uma conversa fora do modo bot volta a ir ao AGR', CHR_MODULO,
     '    if (conversa.mode !== MODO_POR_OMISSAO) {',
     '    if (conversa.mode === MODO_POR_OMISSAO && false) {', CHR),
    ('chr: a matriz deixa de poder negar o registo da conversa', CHR_MODULO,
     '    if (!registar.permitido) {',
     '    if (registar.permitido && false) {', CHR),
    ('chr: a matriz deixa de poder negar o processamento', CHR_MODULO,
     '    if (!processar.permitido) {',
     '    if (processar.permitido && false) {', CHR),
    ('chr: a mensagem sem identidade volta a fazer o job repetir', CHR_MODULO,
     '    if (\n      interlocutor === null ||\n      (interlocutor.bsuid === null && interlocutor.telefone === null)\n    ) {',
     '    if (interlocutor === null) {', CHR),
    ('chr: o echo volta a poder ir ao AGR', CHR_MODULO,
     '    if (evento.kind === "echo") {',
     '    if (evento.kind === "echo" && false) {', CHR),
    ('chr: o modo desconhecido passa a ser tratado como conhecido', CHR_CONVERSAS,
     '  if (typeof mode !== "string" || !MODOS_CONHECIDOS.includes(mode)) {',
     '  if (typeof mode !== "string" && !MODOS_CONHECIDOS.includes(mode)) {', CHR),
    ('chr: a fusao reaponta sempre, e nunca dobra os tempos', CHR_CONVERSAS,
     '    if (typeof idPara !== "string") {',
     '    if (true) {', CHR),
    ('chr: o jobId passa a levar o wamid em claro', CHR_INVOCACAO,
     '  return createHash("sha256").update(`${tenantId}:${wamid}`, "utf8").digest("hex");',
     '  return `${tenantId}:${wamid}`;', CHR),
    ('chr: o SQL do canal deixa de filtrar pelo phone_number_id', CHR_SQL,
     '   WHERE c.phone_number_id = $1\n',
     '   WHERE $1 IS NOT NULL\n', CHR),
    ('chr: o SQL da conversa deixa de empurrar a janela', CHR_SQL,
     '     SET last_inbound_at   = EXCLUDED.last_inbound_at,\n         window_expires_at = EXCLUDED.window_expires_at\n',
     '     SET last_inbound_at   = platform.conversations.last_inbound_at,\n         window_expires_at = platform.conversations.window_expires_at\n', CHR),
    # ----------------------------------------------- KAM-023 (free tier)
    #
    # Cada uma volta o codigo a um defeito **real**, e a maior parte a um
    # defeito que custa dinheiro a uma PME ou um aviso a quem opera.
    #
    # **Nenhuma toca no predicado `tenant_id` das consultas**, e isso e
    # deliberado: com a RLS ligada, tirar o predicado explicito nao muda nada
    # — a politica `tenant_iso` filtra igual —, pelo que seria uma mutacao que
    # nenhum teste pode matar. Uma sobrevivente por desenho e pior do que
    # nenhuma, porque conta como prova. Essa defesa em profundidade fica dita
    # na seccao de verificacao do ticket, como o que e.
    ('free tier: o mes volta a sair como `date` e nao em texto', FT_SQL,
     "to_char(c.free_tier_month, 'YYYY-MM-DD') AS mes",
     "c.free_tier_month AS mes", SAIDA),
    ('free tier: a leitura ignora o mes guardado e devolve o contador velho', FT_SQL,
     "  SELECT CASE\n             WHEN c.free_tier_month\n                  IS DISTINCT FROM platform.ten_periodo(coalesce($3, now()))\n             THEN 0\n             ELSE c.free_tier_used\n         END AS usadas,",
     "  SELECT c.free_tier_used AS usadas,", SAIDA),
    ('free tier: o reinicio volta a ser `<>` e o NULL deixa de contar', FT_SQL,
     "             WHEN antes.free_tier_month\n                  IS DISTINCT FROM platform.ten_periodo(coalesce($3, now()))",
     "             WHEN antes.free_tier_month\n                  <> platform.ten_periodo(coalesce($3, now()))", SAIDA),
    ('free tier: o mes novo comeca em 0 e perde a primeira entrega', FT_SQL,
     "             THEN 1\n             ELSE antes.free_tier_used + 1",
     "             THEN 0\n             ELSE antes.free_tier_used + 1", SAIDA),
    ('free tier: o incremento perde o FOR UPDATE e o `antes` deixa de valer', FT_SQL,
     "      SELECT id, free_tier_used, free_tier_month\n        FROM platform.tenant_channels\n       WHERE tenant_id = $1 AND phone_number_id = $2\n         FOR UPDATE",
     "      SELECT id, free_tier_used, free_tier_month\n        FROM platform.tenant_channels\n       WHERE tenant_id = $1 AND phone_number_id = $2", SAIDA),
    ('free tier: a janela de falhas passa a contar o que nao tem destino', FT_SQL,
     "         AND m.state IN ('delivered', 'read', 'failed')",
     "         AND m.state IN ('queued', 'sent', 'delivered', 'read', 'failed')", SAIDA),
    ('free tier: o aviso volta a ser o valor e nao a travessia', FT_CUSTO,
     "  if (de < AVISO_EM && para >= AVISO_EM) return \"aviso\";",
     "  if (para >= AVISO_EM) return \"aviso\";", SAIDA),
    ('free tier: o reinicio deixa de normalizar o `antes`', FT_CUSTO,
     "  const de = reiniciou ? 0 : Math.trunc(antes);",
     "  const de = Math.trunc(antes);", SAIDA),
    ('free tier: o racio volta a ser limitado a 1', FT_CUSTO,
     "  return Math.trunc(usadas) / FREE_TIER_DE_SERVICE;",
     "  return Math.min(1, Math.trunc(usadas) / FREE_TIER_DE_SERVICE);", SAIDA),
    ('free tier: a estimativa perde o `max(0, ...)` e fica negativa', FT_CUSTO,
     "  const acima = Math.max(0, Math.trunc(usadas) - FREE_TIER_DE_SERVICE);",
     "  const acima = Math.trunc(usadas) - FREE_TIER_DE_SERVICE;", SAIDA),
    ('free tier: a suspeita deixa de exigir o tecto esgotado', FT_CUSTO,
     "  if (Math.trunc(usadas) < FREE_TIER_DE_SERVICE) return false;\n  if (janela.total < JANELA_DE_FALHAS) return false;",
     "  if (janela.total < JANELA_DE_FALHAS) return false;", SAIDA),
    ('free tier: a divergencia perde o guarda do denominador zero', FT_CUSTO,
     "  if (medido === 0) return null;",
     "  if (false) return null;", SAIDA),
    ('free tier: a metrica volta a aceitar um tenant_id como etiqueta', FT_METRICAS,
     "        throw new SufixoInvalidoError(metrica, sufixo);",
     "        void sufixo;", SAIDA),
    ('free tier: a reconciliacao volta a comparar meses em UTC', FT_SQL,
     "     AND platform.ten_periodo(m.delivered_at)\n         = platform.ten_periodo(coalesce($3, now()))",
     "     AND m.delivered_at >= platform.ten_periodo(coalesce($3, now()))", SAIDA),
    # ------------------------------------- KAM-023, revisao 0013 (restricao)
    #
    # As quatro primeiras sao da revisao e correm na suite `tests`; as sete
    # seguintes sao do codigo e correm na `tests_outbound`.
    #
    # **Uma foi descartada, e vale dizer qual:** apagar o `REVOKE`/`GRANT`
    # que o `downgrade` fazia antes do `DROP COLUMN`. Nenhum teste a podia
    # matar — o PostgreSQL remove a concessao com a coluna, pelo que os
    # grants da `0001` sobrevivem ao `DROP` por si sos e o resultado e o
    # mesmo. Uma mutacao imortal nao e um teste em falta, e um sinal de que
    # o codigo nao faz nada: aquelas duas instrucoes sairam da revisao.
    ('restricao 0013: o dominio do motivo perde um valor', REV13,
     "MOTIVOS_DE_RESTRICAO = (\"'payment_method'\", \"'quality'\", \"'policy'\")",
     "MOTIVOS_DE_RESTRICAO = (\"'payment_method'\", \"'quality'\")", "tests"),
    ('restricao 0013: o conjunto de codigos perde o tecto', REV13,
     "OR array_length(meta_error_codes_seen, 1) <= {TECTO_DE_CODIGOS}",
     "OR true", "tests"),
    ('restricao 0013: a app deixa de poder escrever o motivo', REV13,
     "                      last_account_update_at, motivo_restricao,",
     "                      last_account_update_at,", "tests"),
    ('restricao 0013: o conjunto de codigos passa a ser anulavel', REV13,
     "ADD COLUMN meta_error_codes_seen integer[] NOT NULL DEFAULT '{{}}'",
     "ADD COLUMN meta_error_codes_seen integer[] DEFAULT '{{}}'", "tests"),
    ('restricao: a marca deixa de preservar a primeira', FT_SQL,
     "     SET motivo_restricao = COALESCE(antes.motivo_restricao, $3),",
     "     SET motivo_restricao = $3,", SAIDA),
    ('restricao: o `marcado` volta a sair do valor novo', FT_SQL,
     "             (antes.motivo_restricao IS NULL) AS marcado,",
     "             (c.motivo_restricao IS NOT NULL) AS marcado,", SAIDA),
    ('restricao: a marca perde o FOR UPDATE e o evento sai duas vezes', FT_SQL,
     "      SELECT id, motivo_restricao, meta_error_codes_seen\n        FROM platform.tenant_channels\n       WHERE tenant_id = $1 AND phone_number_id = $2\n         FOR UPDATE",
     "      SELECT id, motivo_restricao, meta_error_codes_seen\n        FROM platform.tenant_channels\n       WHERE tenant_id = $1 AND phone_number_id = $2", SAIDA),
    ('restricao: o conjunto de codigos passa a aceitar repetidos', FT_SQL,
     "             WHEN $4::integer = ANY(antes.meta_error_codes_seen)\n                  THEN antes.meta_error_codes_seen",
     "             WHEN false THEN antes.meta_error_codes_seen", SAIDA),
    ('restricao: um statuses sem codigo passa a guardar NULL no conjunto', FT_SQL,
     "             WHEN $4::integer IS NULL THEN antes.meta_error_codes_seen",
     "             WHEN false THEN antes.meta_error_codes_seen", SAIDA),
    ('restricao: levantar deixa de olhar para o motivo que lhe dao', FT_SQL,
     "     AND c.motivo_restricao = $3\n   RETURNING c.id",
     "     AND c.motivo_restricao IS NOT NULL\n   RETURNING c.id", SAIDA),
    ('restricao: o event_id ausente passa a ser calado', FT_MODULO,
     "    if (typeof eventoId !== \"string\") {",
     "    if (false) {", SAIDA),
    ('free tier: um canal desconhecido volta a ganhar mil mensagens gratis', FT_MODULO,
     "const DESCONHECIDO = {\n  usadas: FREE_TIER_DE_SERVICE,",
     "const DESCONHECIDO = {\n  usadas: 0,", SAIDA),
    # ------------------------------------ KAM-021, revisao 0014 (qualidade)
    #
    # As sete primeiras sao da revisao: seis correm na suite `tests`, onde vive
    # o `test_qualidade_schema.py`, e uma na `tests_isolamento`, porque quem ve
    # a politica desaparecer e o X-05. As dezoito seguintes sao do codigo e
    # correm na `tests_outbound`.
    #
    # **Duas foram descartadas, e vale dizer quais e porque.** A primeira era
    # trocar a FK composta do canal por uma simples (`REFERENCES
    # tenant_channels (id)`): a `tenant_channels` nao tem unicidade em `id`
    # sozinho, pelo que a migracao **nao corre** — e uma mutacao que rebenta na
    # criacao e apanhada por qualquer teste, o que nao prova nada sobre a FK. A
    # segunda era retirar o `ocorrido_em` do `ORDER BY` do registo: a ordem das
    # linhas nao e afirmada por teste nenhum — e nao devia ser, porque os
    # webhooks chegam fora de ordem —, pelo que a mutacao seria imortal.
    ('qualidade 0014: o dominio dos eventos perde o do template', REV14,
     "    \"'account_alerts'\",\n    \"'message_template_quality_update'\",",
     "    \"'account_alerts'\",", "tests"),
    ('qualidade 0014: a chave passa a ser unica globalmente', REV14,
     "                UNIQUE (tenant_id, event_key),",
     "                UNIQUE (event_key),", "tests"),
    ('qualidade 0014: a primeira linha de um canal deixa de caber', REV14,
     "            valor_anterior text,",
     "            valor_anterior text NOT NULL,", "tests"),
    ('qualidade 0014: um valor vazio passa a ser um valor', REV14,
     "                CHECK (btrim(valor_novo) <> ''),",
     "                CHECK (true),", "tests"),
    ('qualidade 0014: o tecto de numeros passa a aceitar zero', REV14,
     "                OR max_phone_numbers_per_business > 0",
     "                OR max_phone_numbers_per_business >= 0", "tests"),
    ('qualidade 0014: a app ganha UPDATE no registo que nao se corrige', REV14,
     "\"GRANT SELECT, INSERT ON platform.channel_quality_log TO kamba_app\"",
     "\"GRANT SELECT, INSERT, UPDATE ON platform.channel_quality_log TO kamba_app\"",
     "tests"),
    ('qualidade 0014: o registo nasce sem politica de tenant', REV14,
     '    rls.enable_tenant_rls("channel_quality_log")',
     '    pass  # rls.enable_tenant_rls("channel_quality_log")', "tests_isolamento"),
    ('qualidade: o registo passa a reescrever a linha que ja existia', QL_SQL,
     "      ON CONFLICT (tenant_id, event_key) DO NOTHING",
     "      ON CONFLICT (tenant_id, event_key) DO UPDATE\n            SET valor_novo = EXCLUDED.valor_novo",
     SAIDA),
    ('qualidade: restringir deixa de exigir que haja transicao', QL_SQL,
     "     AND estado <> 'restrito'\n   RETURNING id",
     "   RETURNING id", SAIDA),
    ('qualidade: restringir passa a sobrepor a marca de outro ticket', QL_SQL,
     "         motivo_restricao = COALESCE(motivo_restricao, 'quality')",
     "         motivo_restricao = 'quality'", SAIDA),
    ('qualidade: repor deixa de olhar para o motivo que la esta', QL_SQL,
     "     AND motivo_restricao = 'quality'\n   RETURNING id",
     "   RETURNING id", SAIDA),
    ('qualidade: a medicao passa a contar envios e nao pessoas', QL_SQL,
     "  SELECT count(DISTINCT m.contact_id)::bigint AS unicos",
     "  SELECT count(m.contact_id)::bigint AS unicos", SAIDA),
    ('qualidade: a resposta dentro da janela passa a consumir escalao', QL_SQL,
     "     AND m.kind <> 'service'",
     "     AND m.kind IS NOT NULL", SAIDA),
    ('qualidade: o que a fila ainda tem em mao passa a contar', QL_SQL,
     "     AND m.state <> 'queued'",
     "     AND m.state IS NOT NULL", SAIDA),
    ('qualidade: a janela movel passa a ser de 48 h', QL_SQL,
     "     AND m.created_at >= coalesce($3, now()) - interval '24 hours'",
     "     AND m.created_at >= coalesce($3, now()) - interval '48 hours'", SAIDA),
    ('qualidade: a pausa do template passa a casar por prefixo de idioma', QL_SQL,
     "   WHERE tenant_id = $1 AND name = $2 AND lang = $3\n   RETURNING name, status, quality",
     "   WHERE tenant_id = $1 AND name = $2 AND lang LIKE left($3, 2) || '%'\n   RETURNING name, status, quality",
     SAIDA),
    ('qualidade: a marca de revisao passa a mexer nos nao aprovados', QL_SQL,
     "     AND status = 'approved'\n   RETURNING name",
     "   RETURNING name", SAIDA),
    ('qualidade: um corpo sem tecto passa a apagar o tecto que se sabia', QL_SQL,
     "         max_phone_numbers_per_business =\n             COALESCE($4::integer, max_phone_numbers_per_business)",
     "         max_phone_numbers_per_business = $4::integer", SAIDA),
    ('qualidade: o aviso de amarelo volta a sair em cada webhook', QL_DECISAO,
     '  return qualidade === "yellow" && anterior !== "yellow";',
     '  return qualidade === "yellow";', SAIDA),
    ('qualidade: o aviso do escalao passa a exigir ultrapassar os 80%', QL_DECISAO,
     "  return { unicos, escalao, racio, avisa: racio >= FRACCAO_DE_AVISO };",
     "  return { unicos, escalao, racio, avisa: racio > FRACCAO_DE_AVISO };", SAIDA),
    ('qualidade: um valor desconhecido passa a decidir o estado', QL_DECISAO,
     '  if (qualidade === null) return "nada";',
     '  if (false) return "nada";', SAIDA),
    ('qualidade: o estado de reposicao deixa de ser o activo', QL_DECISAO,
     '  if (accao === "repor") return ESTADO_ACTIVO;',
     '  if (accao === "repor") return ESTADO_RESTRITO;', SAIDA),
    ('qualidade: um red repetido volta a ser uma transicao', QL_DECISAO,
     '    return estado === ESTADO_RESTRITO ? "nada" : "restringir";',
     '    return "restringir";', SAIDA),
    ('qualidade: o tecto do primeiro escalao passa a ser dez vezes maior', QL_CONTRATO,
     "  TIER_250: 250,",
     "  TIER_250: 2_500,", SAIDA),
    ('qualidade: a traducao volta a aceitar qualquer cadeia', QL_CONTRATO,
     "  return CANONICO_DA_META[bruto] ?? null;",
     "  return CANONICO_DA_META[bruto] ?? (bruto.toLowerCase() as Qualidade);", SAIDA),
    ('qualidade: a fraccao de aviso deixa de ser a do free tier', QL_CONTRATO,
     "export const FRACCAO_DE_AVISO = 0.8;",
     "export const FRACCAO_DE_AVISO = 0.95;", SAIDA),
    ('qualidade: o racio sem observacao passa a dizer que esta folgado', QL_METRICAS,
     "    if (this.#racioPorCanal.size === 0) return -1;",
     "    if (this.#racioPorCanal.size === 0) return 0;", SAIDA),
    ('qualidade: um evento repetido volta a escrever e a restringir', QL_MODULO,
     "    if (!registou) {\n      // Evento repetido: nada mudou e nada se anuncia.",
     "    if (false) {\n      // Evento repetido: nada mudou e nada se anuncia.", SAIDA),
    ('qualidade: o channel.updated passa a sair sem transicao', QL_MODULO,
     "    if (restringiu || reposto) {",
     "    if (true) {", SAIDA),
    ('qualidade: um valor desconhecido passa a apagar a qualidade do canal', QL_MODULO,
     "    if (qualidade === null) {",
     "    if (false && qualidade === null) {", SAIDA),
    ('qualidade: o evento passa a sair depois de a cache esquecer', QL_MODULO,
     "      await this.#emitir?.(\n        canal.tenantId,\n        canal.channelId,\n        canal.phoneNumberId,\n        MOTIVO_DE_QUALIDADE,\n      );\n      this.#invalidar?.(canal.channelId);",
     "      this.#invalidar?.(canal.channelId);\n      await this.#emitir?.(\n        canal.tenantId,\n        canal.channelId,\n        canal.phoneNumberId,\n        MOTIVO_DE_QUALIDADE,\n      );", SAIDA),
    ('criterio 9: a matriz deixa de ser consultada quando ha par de estados', SAIDA_DECISAO,
     "  if (estado === null) return true;\n  return tenantGate(",
     "  if (estado === null || true) return true;\n  return tenantGate(", SAIDA),
    ('criterio 9: a mensagem de sessao passa a pedir a accao de template', SAIDA_DECISAO,
     '  service: "responder_sessao",',
     '  service: "enviar_template_utilidade",', SAIDA),
    ('criterio 9: um canal que a porta nao encontra volta a enviar', SAIDA_ADAPTER,
     '      if (estado === null) return this.#recusar(pedido, "STATE_REFUSED");',
     '      if (false) return this.#recusar(pedido, "STATE_REFUSED");', SAIDA),
    # -------------------------------- KAM-022, revisao 0015 (consentimento)
    #
    # As oito primeiras sao da revisao: sete correm na suite `tests`, onde vive
    # o `test_consentimento_schema.py`, e uma na `tests_isolamento`, porque quem
    # ve a politica desaparecer e o X-05. As vinte seguintes sao do codigo e
    # correm na `tests_outbound`.
    #
    # **A mutacao mais importante desta lista e a do `security_invoker`**, e ela
    # nao e uma mutacao de logica: tira uma opcao de uma vista. Sem ela, a vista
    # corre com os privilegios do dono e a RLS passa a depender do `FORCE` — e o
    # que a mata e o `verificar_vistas` do catalogo, que existe desde o KAM-004
    # e que esta revisao foi a primeira a por a prova.
    #
    # **Duas foram escritas e descartadas.** A primeira trocava o `DISTINCT ON`
    # da vista por um `GROUP BY`: nao ha forma de o escrever que devolva as
    # mesmas colunas, pelo que a migracao nao corre — e uma mutacao que rebenta
    # na criacao e apanhada por qualquer teste, o que nao prova nada sobre a
    # vista. A segunda apagava o `DROP VIEW` do `downgrade`: sem `CASCADE`, o
    # `DROP TABLE` **falha** enquanto a vista existir, pelo que o `downgrade`
    # rebenta — e o teste que o apanha nao diz nada sobre a ordem, diz que o
    # Alembic falhou.
    ('consentimento 0015: o dominio das finalidades perde a ultima', REV15,
     "    \"'partilha_estafeta'\",\n    \"'notificacao_dono'\",",
     "    \"'partilha_estafeta'\",", "tests"),
    ('consentimento 0015: a vista deixa de correr como quem a consulta', REV15,
     "          WITH (security_invoker = true) AS",
     "          AS", "tests_isolamento"),
    # **A mutacao de um defeito que o CI apanhou e eu tinha afirmado como
    # impossivel duas vezes** (na revisao e no dicionario): sem o
    # `registado_em` na ordem, duas provas do mesmo trio com o mesmo
    # `ocorrido_em` — a hora da Meta tem resolucao de segundos — faziam a vista
    # escolher pelo `uuid`, arbitrariamente.
    ('consentimento 0015: a vista perde o desempate do registado_em', REV15,
     "                  ocorrido_em DESC, registado_em DESC, id DESC",
     "                  ocorrido_em DESC, id DESC", "tests"),
    ('consentimento 0015: a prova perde a unicidade que da a idempotencia', REV15,
     "            CONSTRAINT consent_event_prova_uq\n                UNIQUE (tenant_id, contact_id, purpose, evidence_hash),",
     "", "tests"),
    ('consentimento 0015: a unicidade da prova passa a ser global', REV15,
     "                UNIQUE (tenant_id, contact_id, purpose, evidence_hash),",
     "                UNIQUE (contact_id, purpose, evidence_hash),", "tests"),
    ('consentimento 0015: o resumo da prova passa a aceitar qualquer tamanho', REV15,
     "            CONSTRAINT consent_event_evidence_ck\n                CHECK (octet_length(evidence_hash) = {BYTES_DO_SHA256})",
     "            CONSTRAINT consent_event_evidence_ck\n                CHECK (octet_length(evidence_hash) >= 1)", "tests"),
    ('consentimento 0015: a app ganha UPDATE na prova que nao se corrige', REV15,
     '"GRANT SELECT, INSERT ON platform.consent_event TO kamba_app"',
     '"GRANT SELECT, INSERT, UPDATE ON platform.consent_event TO kamba_app"',
     "tests"),
    ('consentimento 0015: a app ganha INSERT no texto juridico', REV15,
     '"GRANT SELECT ON platform.consent_texts TO kamba_app"',
     '"GRANT SELECT, INSERT ON platform.consent_texts TO kamba_app"', "tests"),
    ('consentimento 0015: a prova nasce sem politica de tenant', REV15,
     '    rls.enable_tenant_rls("consent_event")',
     '    pass  # rls.enable_tenant_rls("consent_event")', "tests_isolamento"),
    ('consentimento: a versao vigente passa a incluir as futuras', CS_SQL,
     "     AND vigente_desde <= coalesce($2, now())",
     "     AND vigente_desde IS NOT NULL", SAIDA),
    ('consentimento: a versao vigente passa a ser a mais antiga', CS_SQL,
     "   ORDER BY vigente_desde DESC\n   LIMIT 1",
     "   ORDER BY vigente_desde ASC\n   LIMIT 1", SAIDA),
    ('consentimento: o estado passa a ler a tabela em vez da vista', CS_SQL,
     "    FROM platform.consent_actual\n   WHERE tenant_id = $1 AND contact_id = $2 AND purpose = $3",
     "    FROM platform.consent_event\n   WHERE tenant_id = $1 AND contact_id = $2 AND purpose = $3",
     SAIDA),
    ('consentimento: o registo passa a reescrever a prova que ja existia', CS_SQL,
     "      ON CONFLICT (tenant_id, contact_id, purpose, evidence_hash) DO NOTHING",
     "      ON CONFLICT (tenant_id, contact_id, purpose, evidence_hash) DO UPDATE\n            SET accepted = EXCLUDED.accepted",
     SAIDA),
    ('consentimento: a contagem de avisos passa a contar a conversa toda', CS_SQL,
     "     AND idempotency_key LIKE $3",
     "     AND idempotency_key IS NOT NULL", SAIDA),
    ('consentimento: a contagem de avisos deixa de filtrar a conversa', CS_SQL,
     "   WHERE tenant_id = $1\n     AND conversation_id = $2\n     AND idempotency_key LIKE $3",
     "   WHERE tenant_id = $1\n     AND idempotency_key LIKE $3", SAIDA),
    ('consentimento: o PARAR passa a disparar dentro de uma frase', CS_PARAR,
     "  return (PALAVRAS_DE_PARAR as readonly string[]).includes(limpo);",
     "  return PALAVRAS_DE_PARAR.some((p) => limpo.includes(p));", SAIDA),
    ('consentimento: a normalizacao deixa de tirar os acentos', CS_PARAR,
     '    .replace(/[\u0300-\u036f]/g, "")',
     '    .replace(/[\u0300-\u036f]/g, "\u0301")', SAIDA),
    ('consentimento: a normalizacao deixa de ignorar a caixa', CS_PARAR,
     "    .toLowerCase()\n    .replace(/[^\\p{L}\\p{N}\\s]/gu, \" \")",
     "    .replace(/[^\\p{L}\\p{N}\\s]/gu, \" \")", SAIDA),
    ('consentimento: a lista de opt-out perde o PARAR do criterio', CS_PARAR,
     'export const PALAVRAS_DE_PARAR = ["parar", "stop", "sair", "cancelar"] as const;',
     'export const PALAVRAS_DE_PARAR = ["stop", "sair", "cancelar"] as const;', SAIDA),
    ('consentimento: o texto livre passa a autorizar o agente', CS_DECISAO,
     '  texto: {\n    ausente: "enviar_aviso",\n    desactualizado: "enviar_aviso",\n    valido: "seguir",\n  },',
     '  texto: {\n    ausente: "seguir",\n    desactualizado: "seguir",\n    valido: "seguir",\n  },',
     SAIDA),
    ('consentimento: uma versao desactualizada passa a valer', CS_DECISAO,
     '  return linha.text_version === versaoVigente ? "valido" : "desactualizado";',
     '  return "valido";', SAIDA),
    ('consentimento: uma recusa passa a contar como consentimento', CS_DECISAO,
     '  if (linha === null || !linha.accepted) return "ausente";',
     '  if (linha === null) return "ausente";', SAIDA),
    ('consentimento: o `enviar_politica` passa a autorizar o agente', CS_DECISAO,
     '  return accao === "seguir" || accao === "registar_e_seguir";',
     '  return accao !== "enviar_aviso";', SAIDA),
    ('consentimento: o aviso passa a repetir-se para sempre', CS_DECISAO,
     '  if (accao === "enviar_aviso" && avisosEnviados >= AVISOS_ANTES_DO_HUMANO) {',
     "  if (false) {", SAIDA),
    ('consentimento: o PARAR deixa de ser lido antes do texto livre', CS_DECISAO,
     '    return eParar(entrada.texto) ? "parar" : "texto";',
     '    return "texto";', SAIDA),
    ('consentimento: um botao desconhecido passa a ser o continuar', CS_DECISAO,
     '      ? (entrada.id as Linha)\n      : "outro";',
     '      ? (entrada.id as Linha)\n      : "continuar";', SAIDA),
    ('consentimento: o tecto de avisos passa de dois a dez', CS_CONTRATO,
     "export const AVISOS_ANTES_DO_HUMANO = 2;",
     "export const AVISOS_ANTES_DO_HUMANO = 10;", SAIDA),
    ('consentimento: o separador da prova desaparece', CS_PROVA,
     'export const SEPARADOR = "\\u0000";',
     'export const SEPARADOR = "";', SAIDA),
    ('consentimento: a prova deixa de cobrir a hora', CS_PROVA,
     "    [campos.textoMostrado, campos.contactId, campos.wamid, campos.hora].join(",
     "    [campos.textoMostrado, campos.contactId, campos.wamid].join(", SAIDA),
    ('consentimento: o texto do aviso sai com o marcador em claro', CS_PROVA,
     "  return texto.split(MARCADOR_DA_LOJA).join(nomeDaLoja);",
     "  return texto;", SAIDA),
    ('consentimento: o racio sem aviso passa a dizer que ninguem aceitou', CS_METRICAS,
     "    if (avisos === 0) return -1;",
     "    if (avisos === 0) return 0;", SAIDA),
    # **Esta e a mutacao de um defeito que eu proprio escrevi**, e o que a mata
    # e o ensaio contra a base: o `registar_e_seguir` nao envia mensagem, pelo
    # que uma condicao feita so com o `enviaMensagem` deixava a prova do
    # «Continuar» ser calculada sobre uma cadeia **vazia**.
    ('consentimento: o texto deixa de entrar na prova do continuar', CS_DECISAO,
     '    accao === "registar_e_seguir" ||\n    accao === "registar_revogacao" ||',
     '    accao === "registar_revogacao" ||', SAIDA),
    ('consentimento: a prova passa a escrever-se depois de autorizar', CS_MODULO,
     '    if (accao === "registar_e_seguir") {',
     "    if (false) {", SAIDA),
    ('consentimento: sem texto vigente passa a autorizar o agente', CS_MODULO,
     "    if (vigente === null) {",
     "    if (false && vigente === null) {", SAIDA),
    ('consentimento: a revogacao passa a escrever marketing aceite', CS_MODULO,
     "        FINALIDADE_DE_MARKETING,\n        vigente.version,\n        false,",
     "        FINALIDADE_DE_MARKETING,\n        vigente.version,\n        true,", SAIDA),
    ('consentimento: a contagem de avisos deixa de se ler', CS_MODULO,
     "    const precisaDaContagem =\n      (linha === \"texto\" || linha === \"outro\") && estado !== \"valido\";",
     "    const precisaDaContagem = false;", SAIDA),
    # ------------------------------- KAM-018, revisao 0016 (modos da conversa)
    #
    # Duas da revisao, que correm na suite `tests` — e onde vive o
    # `test_privilegios.py`, que e quem ve um `GRANT` desaparecer ou crescer. As
    # restantes sao do codigo e correm na `tests_modos`.
    #
    # **A mutacao mais importante desta lista e a do `FOR UPDATE`**, e ela nao e
    # de logica: tira duas palavras de uma subconsulta. Sem elas, o par
    # «verificar o predicado, escrever» deixa de ser atomico ao nivel da linha e
    # a exclusao mutua passa a depender **so** do *advisory lock* — o que
    # continua a funcionar para quem passa pela maquina e deixa de funcionar
    # para quem corra a consulta sem o *lock*. Quem a mata e o ensaio das duas
    # transicoes concorrentes.
    #
    # **Duas foram escritas e descartadas.** A primeira apagava o
    # `pg_advisory_xact_lock` do `SQL_TRANCAR_CONVERSA`: a consulta deixa de
    # devolver coluna nenhuma, o `pg` levanta, e **todos** os testes rebentam —
    # uma mutacao que mata a suite inteira nao diz nada sobre o *lock*. A
    # segunda trocava `hashtextextended` por `hashtext`: o PostgreSQL recusa o
    # `pg_advisory_xact_lock(integer)` com um argumento so, pelo que a mutacao
    # nao corre.
    ('modos 0016: a app perde o UPDATE do mode', REV16,
     'COLUNAS_NOVAS = ("mode", "last_human_activity_at")',
     'COLUNAS_NOVAS = ("last_human_activity_at",)', "tests"),
    ('modos 0016: o downgrade revoga tambem a janela da 0009', REV16,
     "        f\"REVOKE UPDATE ({', '.join(COLUNAS_NOVAS)}) \"",
     "        f\"REVOKE UPDATE ({', '.join(COLUNAS_DA_APLICACAO)}) \"", "tests"),
    # ---------------------------------------------------------------- o SQL
    ('modos: a transicao deixa de ser atomica ao nivel da linha', MO_SQL,
     "       WHERE tenant_id = $1 AND id = $2\n         FOR UPDATE",
     "       WHERE tenant_id = $1 AND id = $2", "tests_modos"),
    ('modos: o UPDATE do modo perde o predicado da tabela', MO_SQL,
     "     AND antes.mode = ANY($4::text[])\n",
     "", "tests_modos"),
    ('modos: a actividade humana deixa de ser monotona no UPDATE', MO_SQL,
     "         last_human_activity_at = GREATEST(c.last_human_activity_at, $5)",
     "         last_human_activity_at = $5", "tests_modos"),
    ('modos: a actividade humana deixa de ser monotona no registo', MO_SQL,
     "     SET last_human_activity_at = GREATEST(last_human_activity_at, $3)",
     "     SET last_human_activity_at = $3", "tests_modos"),
    ('modos: o lock deixa de separar o tenant do contacto', MO_SQL,
     "hashtextextended($1::text || ':' || $2::text, 0)",
     "hashtextextended($1::text || $2::text, 0)", "tests_modos"),
    ('modos: o job das 24 h deixa de olhar para o handoff', MO_SQL,
     "           c.last_human_activity_at,\n           (SELECT max(h.opened_at) FROM platform.handoffs AS h\n             WHERE h.tenant_id = c.tenant_id AND h.conversation_id = c.id)\n         ) < $2",
     "           c.last_human_activity_at,\n           NULL::timestamptz\n         ) < $2", "tests_modos"),
    ('modos: o job das 24 h conta do handoff mais antigo', MO_SQL,
     "(SELECT max(h.opened_at) FROM platform.handoffs AS h",
     "(SELECT min(h.opened_at) FROM platform.handoffs AS h", "tests_modos"),
    ('modos: o job das 24 h pausa qualquer modo', MO_SQL,
     "     AND c.mode = ANY($3::text[])\n",
     "", "tests_modos"),
    ('modos: a supressao passa a nascer em queued', MO_SQL,
     "  VALUES ($1, $2, $3, $4, $5, $6, $7, 'suppressed_by_human')",
     "  VALUES ($1, $2, $3, $4, $5, $6, $7, 'queued')", "tests_modos"),
    ('modos: a supressao repetida passa a reescrever a linha', MO_SQL,
     "      ON CONFLICT (tenant_id, idempotency_key) DO NOTHING",
     "      ON CONFLICT (tenant_id, idempotency_key) DO UPDATE\n            SET state = 'suppressed_by_human'", "tests_modos"),
    ('modos: a leitura do modo deixa de filtrar o tenant', MO_SQL,
     "  SELECT mode, last_human_activity_at\n    FROM platform.conversations\n   WHERE tenant_id = $1 AND id = $2",
     "  SELECT mode, last_human_activity_at\n    FROM platform.conversations\n   WHERE id = $2 AND $1 IS NOT NULL", "tests_modos"),
    # --------------------------------------------------- a tabela de transicoes
    # O `comando_bot` aparece como celula rejeitada em **dois** modos (`humano` e
    # `pausada`) com exactamente o mesmo texto, pelo que a ancora leva a linha
    # seguinte: e o `handoff_resolvido` que separa os dois sitios.
    ('modos: o comando /bot passa a funcionar em modo humano', MO_TRANSICOES,
     '    comando_bot: { para: null, rejeitada: true, fonte: "invariante" },\n'
     '    // Já está em atendimento humano. Pedir outra vez não é defeito.',
     '    comando_bot: { para: "bot", rejeitada: false, fonte: "invariante" },\n'
     '    // Já está em atendimento humano. Pedir outra vez não é defeito.',
     "tests_modos"),
    ('modos: o silencio do dono deixa de ser condicao', MO_TRANSICOES,
     '  if (celula.condicao === "silencio_do_dono" && !silencioExpirou(estado, agora)) {',
     "  if (false) {", "tests_modos"),
    ('modos: as origens do predicado passam a ser todos os modos', MO_TRANSICOES,
     "  return MODOS.filter((de) => TABELA[de][gatilho].para === para);",
     "  return [...MODOS].filter((de) => de !== para);", "tests_modos"),
    ('modos: o silencio sem actividade registada passa a nao expirar', MO_TRANSICOES,
     "  if (estado.ultimaActividadeHumana === null) return true;",
     "  if (estado.ultimaActividadeHumana === null) return false;", "tests_modos"),
    ('modos: o limite do silencio deixa de ser inclusivo', MO_TRANSICOES,
     "  return agora.getTime() - estado.ultimaActividadeHumana.getTime() >= SILENCIO_DO_DONO_MS;",
     "  return agora.getTime() - estado.ultimaActividadeHumana.getTime() > SILENCIO_DO_DONO_MS;",
     "tests_modos"),
    ('modos: um gatilho rejeitado passa a ser sem efeito', MO_TRANSICOES,
     '  if (celula.rejeitada) return { tipo: "rejeitada" };',
     '  if (false) return { tipo: "rejeitada" };', "tests_modos"),
    # ----------------------------------------------------------- o vocabulario
    ('modos: o silencio do dono passa de 30 minutos a 30 segundos', MO_CONTRATO,
     "export const SILENCIO_DO_DONO_MS = 30 * 60 * 1_000;",
     "export const SILENCIO_DO_DONO_MS = 30 * 1_000;", "tests_modos"),
    ('modos: as 24 h sem humano passam a 24 minutos', MO_CONTRATO,
     "export const SEM_HUMANO_MS = 24 * 60 * 60 * 1_000;",
     "export const SEM_HUMANO_MS = 24 * 60 * 1_000;", "tests_modos"),
    ('modos: o modo `dono` passa a sair como desligado no evento', MO_CONTRATO,
     '  dono: "humano",\n  humano: "humano",',
     '  dono: "desligado",\n  humano: "humano",', "tests_modos"),
    # **Tres mutacoes foram escritas, corridas e removidas, e as tres sobreviveram
    # pela mesma razao: o que elas apagam nao e alcancavel.**
    #
    # As duas primeiras tiravam guardas do `transicoes.ts` — o
    # `if (celula.para === estado.mode)` do `transitar` e o `de !== para` do
    # `origensDe` — e sobreviveram porque **nenhuma celula da tabela aponta para
    # o proprio modo**: o «nao acontece nada» escreve-se `para: null`. A resposta
    # nao foi inventar um teste para codigo morto: foi **apagar as duas guardas**
    # e afirmar o invariante em `tests/modos.transicoes.test.ts` («nenhuma celula
    # aponta para o proprio modo»), que e o teste que impede uma celula assim de
    # entrar. Uma guarda inalcancavel da a ilusao de proteger e nao protege nada.
    #
    # A terceira apagava o `validarPayload` do `emitirModoMudado`. Sobreviveu
    # porque o `payloadDoModo` e tipado e nao consegue produzir um payload
    # invalido **hoje** — o que a validacao protege e uma divergencia futura
    # entre o que montamos e o que o contrato exige, e essa mede-se comparando as
    # duas listas (o teste «o payload que se monta e exactamente o que o contrato
    # exige, nos dois sentidos»). A chamada **fica**, porque e a regra do KAM-007
    # («validar depois e descobrir o defeito com o evento ja publicado») e custa
    # uma linha; a mutacao sai, porque mata-la exigia inventar um caminho que
    # nenhum codigo percorre, e inventa-lo era pior do que declarar o limite.
    # ------------------------------------------------------------------ a guarda
    ('modos: a guarda deixa de olhar para o modo', MO_GUARDA,
     "    if (modo !== MODO_POR_OMISSAO) {",
     "    if (false) {", "tests_modos"),
    ('modos: a guarda deixa de olhar para a actividade humana', MO_GUARDA,
     "    if (instante !== null && instante.getTime() > pedido.turnoIniciadoEm.getTime()) {",
     "    if (false) {", "tests_modos"),
    ('modos: a guarda passa a deixar passar um envio sem turno', MO_GUARDA,
     "    if (pedido.turnoIniciadoEm === undefined) {",
     "    if (false) {", "tests_modos"),
    ('modos: a guarda passa a suprimir no mesmo instante do turno', MO_GUARDA,
     "instante.getTime() > pedido.turnoIniciadoEm.getTime()",
     "instante.getTime() >= pedido.turnoIniciadoEm.getTime()", "tests_modos"),
    ('modos: a guarda passa a ler antes de trancar', MO_GUARDA,
     "    await cliente.query(SQL_TRANCAR_CONVERSA, [pedido.tenantId, pedido.contactId]);\n    const lido = await cliente.query(SQL_CONVERSA_PARA_MODO, [",
     "    const lido = await cliente.query(SQL_CONVERSA_PARA_MODO, [", "tests_modos"),
    # **Esta e a mutacao de um fail-open de um caracter**, e a revisao
    # adversarial deste PR foi quem o apanhou: um `new Date("lixo")` da um `Date`
    # cujo `getTime()` e `NaN`, e **qualquer** comparacao com `NaN` e falsa — um
    # `last_human_activity_at` ilegivel deixava passar o envio em vez de o
    # suprimir. Quem a mata e «um instante ilegivel suprime».
    ('modos: um instante ilegivel passa a deixar passar o envio', MO_GUARDA,
     "  if (typeof valor === \"string\") {\n"
     "    const data = new Date(valor);\n"
     "    return Number.isNaN(data.getTime()) ? ILEGIVEL : data;\n"
     "  }\n"
     "  return ILEGIVEL;",
     "  if (typeof valor === \"string\") return new Date(valor);\n"
     "  return null;", "tests_modos"),
    ('modos: um template suprimido passa a registar-se como service', MO_GUARDA,
     '  if (pedido.corpo.tipo !== "template") return { kind: "service", templateName: null };\n  return { kind: "utility", templateName: pedido.corpo.nome };',
     '  return { kind: "service", templateName: null };', "tests_modos"),
    # ------------------------------------------------------------------ o evento
    ('modos: o evento passa a sair com a versao 1 do contrato', MO_CONTRATO,
     "export const VERSAO_MODE_CHANGED = 2;",
     "export const VERSAO_MODE_CHANGED = 1;", "tests_modos"),
    # ------------------------------------------------------------------ a maquina
    ('modos: a maquina decide com a leitura de antes do lock', MO_MODULO,
     "      await this.#trancar(cliente, alvo.tenantId, contactId);",
     "      void contactId;", "tests_modos"),
    # **Duas mutacoes de dois achados da revisao adversarial deste PR**, e as
    # duas sao de uma linha fora do lugar.
    #
    # A primeira poe o gatilho de volta no `outcome`. Um dos oito —
    # `sem_humano_24h` — nao cabe na gramatica do campo (um segmento e letras com
    # ate tres digitos **no fim**, ou um numero, e `24h` nao e nenhum dos dois),
    # pelo que em modo estrito, que e o do CI, o `Logger` **levanta** — e uma
    # transicao rejeitada, que e um resultado normal, passava a excepcao nao
    # tratada no caminho de um *webhook*. Quem a mata e «um gatilho rejeitado em
    # modo ESTRITO nao levanta».
    #
    # A segunda devolve a contagem para antes da emissao. As duas escritas vivem
    # na mesma transaccao: com a emissao a levantar, o `UPDATE` e desfeito e um
    # contador em memoria **nao** e desfeito com ele. Quem a mata e «se a emissao
    # levantar, `conv_mode_transitions_total` nao sobe».
    ('modos: o gatilho volta ao outcome do registo', MO_MODULO,
     '      this.#log?.warn({ outcome: "modo_rejeitado", tenant_id: tenantId });',
     "      this.#log?.warn({ outcome: `modo_rejeitado_${gatilho}`, tenant_id: tenantId });",
     "tests_modos"),
    ('modos: a transicao conta-se antes de a emissao suceder', MO_MODULO,
     "    const eventoId = await this.#emitirSeHouverPorta(\n"
     "      cliente,\n"
     "      tenantId,\n"
     "      conversationId,\n"
     "      contactId,\n"
     "      modoDepois,\n"
     "    );",
     "    this.#metricas.contar(METRICA_TRANSICOES, gatilho);\n"
     "    const eventoId = await this.#emitirSeHouverPorta(\n"
     "      cliente,\n"
     "      tenantId,\n"
     "      conversationId,\n"
     "      contactId,\n"
     "      modoDepois,\n"
     "    );",
     "tests_modos"),
    ('modos: a porta do ConsentGate deixa subir a conversa que nao existe', MO_MODULO,
     "        if (!(erro instanceof ConversaDesconhecidaError)) throw erro;",
     "        throw erro;", "tests_modos"),
    ('modos: uma corrida perdida passa a contar como transicao', MO_MODULO,
     "    const linha = escrito.rows[0];\n    if (linha === undefined) {",
     "    const linha = escrito.rows[0];\n    if (false) {", "tests_modos"),
    ('modos: o handoff pedido passa a contar como actividade humana', MO_MODULO,
     '  "echo_do_dono",\n  "comando_bot",\n  "handoff_resolvido",\n];',
     '  "echo_do_dono",\n  "comando_bot",\n  "handoff_resolvido",\n  "handoff_pedido",\n];',
     "tests_modos"),
    ('modos: o echo deixa de contar como actividade humana', MO_MODULO,
     '  "echo_do_dono",\n  "comando_bot",\n  "handoff_resolvido",\n];',
     '  "comando_bot",\n  "handoff_resolvido",\n];', "tests_modos"),
    ('modos: um gatilho rejeitado passa a escrever actividade humana', MO_MODULO,
     "      return this.#semMudanca(resposta, estado.mode);\n    }\n\n    if (resposta.tipo === \"sem_efeito\") {",
     "      return this.#aplicar(cliente, tenantId, conversationId, contactId, estado, \"echo_do_dono\");\n    }\n\n    if (resposta.tipo === \"sem_efeito\") {",
     "tests_modos"),
    # O ciclo sobre `resultado.rows` aparece **duas** vezes no modulo — no
    # `onOptOut` e no *job* das 24 h —, pelo que a ancora leva a linha anterior:
    # e a declaracao do acumulador que separa os dois.
    ('modos: o opt-out passa a tratar so a primeira conversa do contacto', MO_MODULO,
     "      const saida: ResultadoDaMudanca[] = [];\n"
     "      for (const linha of resultado.rows) {",
     "      const saida: ResultadoDaMudanca[] = [];\n"
     "      for (const linha of resultado.rows.slice(0, 1)) {", "tests_modos"),
    ('modos: a porta do ConsentGate troca os dois gatilhos', MO_MODULO,
     'const gatilho: Gatilho = modo === "humano" ? "handoff_pedido" : "opt_out";',
     'const gatilho: Gatilho = modo === "humano" ? "opt_out" : "handoff_pedido";',
     "tests_modos"),
    ('modos: o job das 24 h deixa de emitir evento', MO_MODULO,
     "        const eventoId = await this.#emitirSeHouverPorta(\n          cliente,\n          tenantId,\n          id,\n          contactId,\n          \"pausada\",\n        );",
     "        const eventoId: string | null = null;", "tests_modos"),
    ('modos: o limite das 24 h passa a ser o instante actual', MO_MODULO,
     "    const limite = new Date(this.#agora().getTime() - SEM_HUMANO_MS);",
     "    const limite = this.#agora();", "tests_modos"),
    # ------------------------------------------------------------- KAM-016
    #
    # Vinte e seis mutacoes, e cada uma tira uma afirmacao de um criterio. As
    # cinco primeiras sao da revisao e correm na suite que exercita a base; as
    # restantes sao de codigo e correm na `tests_outbound`.
    ('onboarding 0017: a unicidade do code desaparece', REV17,
     "            CONSTRAINT channel_onboarding_code_uq UNIQUE (tenant_id, code_hash),\n",
     "\n", "tests"),
    ('onboarding 0017: a unicidade do par (tenant, waba) desaparece', REV17,
     "            CONSTRAINT channel_onboarding_tenant_waba_uq UNIQUE (tenant_id, waba_id),\n",
     "\n", "tests"),
    ('onboarding 0017: a FK do canal deixa de levar o tenant', REV17,
     "                FOREIGN KEY (tenant_id, channel_id)\n                REFERENCES platform.tenant_channels (tenant_id, id),",
     "                FOREIGN KEY (channel_id)\n                REFERENCES platform.tenant_channels (id),",
     "tests"),
    ('onboarding 0017: a app ganha UPDATE na tentativa', REV17,
     '    op.execute("GRANT SELECT ON platform.channel_onboarding TO kamba_app")',
     '    op.execute("GRANT SELECT, UPDATE ON platform.channel_onboarding TO kamba_app")',
     "tests"),
    ('onboarding 0017: a tentativa nasce sem politica de tenant', REV17,
     '    rls.enable_tenant_rls("channel_onboarding")',
     '    pass  # rls.enable_tenant_rls("channel_onboarding")', "tests_isolamento"),
    # A idempotencia do criterio 2, do lado do SQL.
    ('onboarding: o ON CONFLICT passa a nomear uma chave so', ON_SQL,
     "  ON CONFLICT DO NOTHING\n    RETURNING id::text            AS id,",
     "  ON CONFLICT (tenant_id, waba_id) DO NOTHING\n    RETURNING id::text            AS id,",
     SAIDA),
    ('onboarding: a abertura passa a reescrever a tentativa que ja existia', ON_SQL,
     "  ON CONFLICT DO NOTHING\n    RETURNING id::text            AS id,",
     "  ON CONFLICT (tenant_id, waba_id) DO UPDATE SET fase = 'iniciado'\n    RETURNING id::text            AS id,",
     SAIDA),
    # A transicao do criterio 6: sem o compare-and-set, duas transicoes
    # concorrentes ganham as duas.
    ('onboarding: a transicao deixa de olhar para a fase de partida', ON_SQL,
     "     AND fase = $3\n     RETURNING fase, actualizado_at",
     "     RETURNING fase, actualizado_at", SAIDA),
    ('onboarding: a transicao deixa de filtrar o tenant', ON_SQL,
     "   WHERE id = $1::uuid\n     AND tenant_id = $2::uuid\n     AND fase = $3",
     "   WHERE id = $1::uuid\n     AND fase = $3", SAIDA),
    # O registo de recursos: um `SET` em vez do `||` perde o que outro passo
    # escreveu, e um recurso perdido da lista e um recurso orfao.
    ('onboarding: o registo de recurso passa a reescrever a lista', ON_SQL,
     "     SET recursos_criados = recursos_criados || $3::jsonb,",
     "     SET recursos_criados = $3::jsonb,", SAIDA),
    # A varredura dos 30 minutos.
    ('onboarding: o abandono passa a apanhar qualquer fase', ON_SQL,
     "   WHERE fase = 'iniciado'\n     AND actualizado_at < now()",
     "   WHERE actualizado_at < now()", SAIDA),
    ('onboarding: o abandono deixa de olhar para o prazo', ON_SQL,
     "     AND actualizado_at < now() - ($1::integer * interval '1 minute')",
     "     AND actualizado_at IS NOT NULL", SAIDA),
    # O contador do criterio 8.
    ('onboarding: a contagem passa a filtrar por tenant', ON_SQL,
     "   WHERE criado_at > now() - ($1::integer * interval '1 day')",
     "   WHERE criado_at > now() - ($1::integer * interval '1 day')\n     AND tenant_id = tenant_id",
     SAIDA),
    ('onboarding: a contagem passa a ignorar o abandonado', ON_SQL,
     "   WHERE criado_at > now() - ($1::integer * interval '1 day')",
     "   WHERE criado_at > now() - ($1::integer * interval '1 day')\n     AND fase <> 'abandonado'",
     SAIDA),
    # A compensacao: apagar um canal activo era apagar um canal a funcionar.
    ('onboarding: a compensacao passa a apagar canais activos', ON_SQL,
     "          AND estado = 'pendente'\n      RETURNING id::text AS id",
     "      RETURNING id::text AS id", SAIDA),
    # A instrucao que larga o canal: sem ela, a FK recusa o `DELETE`. **Esta
    # mutacao substituiu a que tirava o `channel_id = NULL` do
    # `SQL_LIMPAR_RECURSOS`**, que deixou de ser aplicavel quando a revisao
    # adversarial separou as duas instrucoes — e o `--aplicaveis` apanhou-a.
    ('onboarding: largar o canal deixa de largar o canal', ON_SQL,
     "     SET channel_id = NULL,\n         pin_ref = NULL,",
     "     SET pin_ref = NULL,", SAIDA),
    # A matriz do criterio 6.
    ('onboarding: a matriz ganha a aresta que o ativo nao tem', ON_CONTRATO,
     "  ativo: [],", '  ativo: ["iniciado"],', SAIDA),
    ('onboarding: o abandonado passa a sair de qualquer fase', ON_CONTRATO,
     '  es_concluido: ["subscrito", "falhado"],',
     '  es_concluido: ["subscrito", "falhado", "abandonado"],', SAIDA),
    ('onboarding: a aresta que o criterio 7 precisa desaparece', ON_CONTRATO,
     '  es_concluido: ["subscrito", "falhado"],',
     '  es_concluido: ["subscrito"],', SAIDA),
    ('onboarding: a transicao passa a aceitar uma fase para si mesma', ON_CONTRATO,
     "  return TRANSICOES[de].includes(para);",
     "  return de === para || TRANSICOES[de].includes(para);", SAIDA),
    # Os onze campos do criterio 5.
    ('onboarding: a subscricao perde o smb_message_echoes', ON_CONTRATO,
     '  "smb_message_echoes",\n  "history",', '  "history",', SAIDA),
    ('onboarding: a versao da Graph passa a cair para a omissao', ON_CONTRATO,
     "  if (!VERSAO.test(bruto)) throw new VersaoDaGraphInvalidaError(bruto);",
     "  if (!VERSAO.test(bruto)) return VERSAO_DA_GRAPH_POR_OMISSAO;", SAIDA),
    # A forma de v4 do criterio 1.
    ('onboarding: o sessionInfoVersion deixa de ser verificado', ON_MODULO,
     "  if (normalizada !== SESSION_INFO_VERSION) {",
     "  if (false) {", SAIDA),
    ('onboarding: a ausencia do featureType passa a ser coexistencia', ON_MODULO,
     '  if (featureType === undefined) {',
     '  if (false) {', SAIDA),
    # A ordem dos passos: o tecto antes de abrir, e a repeticao sem Meta.
    ('onboarding: o tecto passa a admitir o decimo primeiro cliente', ON_MODULO,
     "    if (janela >= LIMITE_DE_ONBOARDINGS) {",
     "    if (janela > LIMITE_DE_ONBOARDINGS) {", SAIDA),
    # **A mutacao da revisao adversarial**, e a mais importante das trinta e
    # oito: sem o ponto de salvaguarda, o `23505` aborta a transaccao e a
    # compensacao nao consegue revogar o *token* — o cofre nao e transaccional,
    # pelo que o `ROLLBACK` da rota apaga a linha do canal e **deixa o segredo
    # la**. Quem a mata e a assercao de que o cofre fica vazio depois do 409.
    # **As duas da cadeia de tres restricoes da base**, que foi o quarto achado
    # da revisao adversarial. A FK nao tem `ON DELETE CASCADE`: apagar o canal
    # com a linha a aponta-lo levanta `23503`, e largar o `channel_id` exige a
    # fase em `falhado` pelo `channel_onboarding_canal_ck`.
    ('onboarding: a compensacao passa a apagar o canal sem o largar', ON_MODULO,
     '      await this.#d.sql.query(SQL_SOLTAR_CANAL, [id, tenantId]);',
     '      // sem largar o canal', SAIDA),
    ('onboarding: a compensacao larga o canal sem transitar primeiro', ON_MODULO,
     '      await this.#transitarParaFalhado(id, tenantId, motivo);\n'
     '      await this.#d.sql.query(SQL_SOLTAR_CANAL, [id, tenantId]);',
     '      await this.#d.sql.query(SQL_SOLTAR_CANAL, [id, tenantId]);', SAIDA),
    ('onboarding: o conflito do numero passa a abortar a transaccao', ON_MODULO,
     "    await this.#d.sql.query(SQL_PONTO_DE_SALVAGUARDA);",
     "    // sem ponto de salvaguarda", SAIDA),
    # A ordem da compensacao: a fase vai a `falhado` **antes** de o
    # `channel_id` ir a `NULL`, porque o `channel_onboarding_canal_ck` o recusa
    # nas seis fases do meio. A mutacao troca as duas, e quem a mata e o teste
    # que afirma a ordem no registo de chamadas.
    # A ordem do fim da compensacao: a fase vai a `falhado` antes de a lista se
    # esvaziar. A mutacao tira a transicao final, e a tentativa fica com a
    # lista vazia e a fase do passo onde falhou — um estado que diz que nao
    # ha nada pendurado e que a saga ainda esta a correr.
    ('onboarding: a compensacao deixa de transitar no fim', ON_MODULO,
     '    await this.#transitarParaFalhado(id, tenantId, motivo);\n'
     '    await this.#d.sql.query(SQL_LIMPAR_RECURSOS, [id, tenantId]);\n  }',
     '    await this.#d.sql.query(SQL_LIMPAR_RECURSOS, [id, tenantId]);\n  }', SAIDA),
    ('onboarding: o 409 passa a ser qualquer violacao de unicidade', ON_MODULO,
     "        restricaoDoErro(erro) === RESTRICAO_DO_NUMERO\n      ) {",
     "        true\n      ) {", SAIDA),
    # A igualdade de conjuntos do criterio 5.
    ('onboarding: a confirmacao passa a aceitar campos em falta', ON_GRAPH,
     "    falta: pedidos.filter((c) => !temObtido.has(c)),",
     "    falta: [],", SAIDA),
    ('onboarding: a confirmacao passa a comparar so o tamanho', ON_MODULO,
     "    if (falta.length > 0 || aMais.length > 0) {",
     "    if (obtidos.length !== CAMPOS_DE_WEBHOOK.length) {", SAIDA),
    # A cifra do criterio 3.
    ('onboarding: a DEK deixa de levar o tenant', ON_CIFRA,
     '  const info = Buffer.from(`${DOMINIO_DA_DEK}\\0${tenant}`, "utf8");',
     '  const info = Buffer.from(DOMINIO_DA_DEK, "utf8");', SAIDA),
    ('onboarding: o contexto autenticado deixa de levar o tenant', ON_CIFRA,
     '  return Buffer.from(`${DOMINIO_DA_CIFRA}\\0${exigirTenant(tenantId)}\\0${kid}`, "utf8");',
     '  return Buffer.from(`${DOMINIO_DA_CIFRA}\\0${kid}`, "utf8");', SAIDA),
    ('onboarding: o kid sai do criptograma', ON_CIFRA,
     "    Buffer.from([VERSAO_DO_FORMATO, octetosDoKid.byteLength]),\n    octetosDoKid,",
     "    Buffer.from([VERSAO_DO_FORMATO, 0]),", SAIDA),
    ('onboarding: a KEK deixa de ter o tamanho conferido', ON_CIFRA,
     "  if (octetos.byteLength !== OCTETOS_DE_CHAVE) {",
     "  if (false) {", SAIDA),
    ('onboarding: o IV passa a ser fixo', ON_CIFRA,
     "  const iv = randomBytes(OCTETOS_DE_IV);",
     "  const iv = Buffer.alloc(OCTETOS_DE_IV);", SAIDA),
    # A porta de escrita no cofre.
    ('onboarding: o sufixo da referencia passa a ser previsivel', ON_ESCRITA,
     '  const sufixo = randomBytes(OCTETOS_DO_SUFIXO).toString("hex");',
     '  const sufixo = "0".repeat(OCTETOS_DO_SUFIXO * 2);', SAIDA),
    ('onboarding: a familia deixa de ter a forma conferida', ON_ESCRITA,
     "  if (typeof familia !== \"string\" || !FAMILIA.test(familia)) {",
     "  if (false) {", SAIDA),
    # As metricas.
    ('onboarding: o gauge da janela passa a dizer zero antes de medir', ON_METRICAS,
     "    return this.#valores.get(chave) ?? -1;",
     "    return this.#valores.get(chave) ?? 0;", SAIDA),
    ('onboarding: a etiqueta deixa de ser conferida', ON_METRICAS,
     "    if (!definicao.valores.includes(etiqueta)) {",
     "    if (false) {", SAIDA),
    # ------------------------------- KAM-017, revisao 0018 (coexistencia)
    #
    # Quatro da revisao, que correm na suite `tests` — e onde vive o
    # `test_coexistencia_schema.py`. As restantes sao de codigo e correm na
    # `tests_outbound`, pela razao que o `FICHEIROS` dela escreve.
    ('coexistencia 0018: a unicidade por canal desaparece', REV18,
     "            CONSTRAINT channel_coexistence_canal_uq UNIQUE (tenant_id, channel_id),\n",
     "\n", "tests"),
    ('coexistencia 0018: o desligamento passa a implicacao', REV18,
     "CHECK ((motivo_desligamento IS NULL) = (desligado_em IS NULL))",
     "CHECK (motivo_desligamento IS NULL OR desligado_em IS NOT NULL)", "tests"),
    ('coexistencia 0018: o prazo passa a poder nascer vencido', REV18,
     "                CHECK (prazo_em > iniciado_em),",
     "                CHECK (prazo_em IS NOT NULL),", "tests"),
    # Da revisao adversarial, e sao tres onde era uma. O `GRANT` do `kamba_app`
    # passou a ser **por coluna** (sem isso o teste de matriz era vacuo, porque
    # um `UPDATE` de tabela curto-circuita o `or` que ele avalia), e o
    # `kamba_batch` ganhou o `UPDATE` sem o qual as tres varreduras respondiam
    # `42501`.
    ('coexistencia 0018: o kamba_app ganha DELETE', REV18,
     '"GRANT SELECT, INSERT ON platform.channel_coexistence TO kamba_app"',
     '"GRANT SELECT, INSERT, DELETE ON platform.channel_coexistence TO kamba_app"',
     "tests"),
    ('coexistencia 0018: o kamba_app passa a poder mover a coexistencia de canal', REV18,
     '    "estado, passos_feitos, iniciado_em, prazo_em, alertado_em,\\n"',
     '    "channel_id, estado, passos_feitos, iniciado_em, prazo_em, alertado_em,\\n"',
     "tests"),
    ('coexistencia 0018: o kamba_batch perde o UPDATE das varreduras', REV18,
     '"GRANT SELECT, UPDATE, DELETE ON platform.channel_coexistence TO kamba_batch"',
     '"GRANT SELECT, DELETE ON platform.channel_coexistence TO kamba_batch"',
     "tests"),

    # O passo que corre uma vez (criterio 3).
    ('coexistencia: o passo deixa de filtrar por ja ter corrido', CX_SQL,
     "     AND NOT ($3::text = ANY (passos_feitos))",
     "     AND TRUE", SAIDA),
    ('coexistencia: o passo passa a aceitar uma sincronizacao falhada', CX_SQL,
     "     AND estado = 'a_sincronizar'\n     AND prazo_em > $6",
     "     AND prazo_em > $6", SAIDA),
    # Da revisao adversarial: o prazo passou a estar **na instrucao** e nao so
    # na varredura, e esta mutacao e a que o prende. Sem ela, um `history`
    # reentregue as 30 h fechava a sincronizacao depois do prazo enquanto
    # ninguem chamasse o `varrerPrazos` — e nao ha agendador.
    ('coexistencia: o prazo deixa de morder na marcacao do passo', CX_SQL,
     "     AND estado = 'a_sincronizar'\n     AND prazo_em > $6\n",
     "     AND estado = 'a_sincronizar'\n", SAIDA),
    ('coexistencia: o prazo deixa de morder ao concluir', CX_SQL,
     "     AND estado = 'a_sincronizar'\n     AND prazo_em > $3\n",
     "     AND estado = 'a_sincronizar'\n", SAIDA),
    ('coexistencia: concluir deixa de exigir os dois passos', CX_SQL,
     "     AND passos_feitos @> ARRAY['contactos','historico']::text[]",
     "     AND TRUE", SAIDA),

    # O alerta e o prazo (criterio 3).
    ('coexistencia: o alerta das 12 h deixa de ser idempotente', CX_SQL,
     "     AND alertado_em IS NULL\n     AND iniciado_em <= $1",
     "     AND iniciado_em <= $1", SAIDA),
    ('coexistencia: o prazo passa a ler o arranque e nao a coluna', CX_SQL,
     "     AND prazo_em <= $1",
     "     AND iniciado_em <= $1", SAIDA),
    ('coexistencia: o prazo das 24 h passa a 12 h', CX_CONTRATO,
     "export const PRAZO_DE_SINCRONIZACAO_MS = 24 * 60 * 60 * 1_000;",
     "export const PRAZO_DE_SINCRONIZACAO_MS = 12 * 60 * 60 * 1_000;", SAIDA),
    ('coexistencia: o alerta das 12 h passa a 24 h', CX_CONTRATO,
     "export const ALERTA_DE_SINCRONIZACAO_MS = 12 * 60 * 60 * 1_000;",
     "export const ALERTA_DE_SINCRONIZACAO_MS = 24 * 60 * 60 * 1_000;", SAIDA),

    # O 2593109 (criterio 4).
    ('coexistencia: o 2593109 passa a ser tratado como falha', CX_MODULO,
     "    if (lote.erros.includes(CODIGO_SEM_HISTORICO)) {",
     "    if (false) {", SAIDA),
    ('coexistencia: o codigo sem historico muda de numero', CX_CONTRATO,
     "export const CODIGO_SEM_HISTORICO = 2_593_109;",
     "export const CODIGO_SEM_HISTORICO = 2_593_110;", SAIDA),
    ('coexistencia: o sem historico passa a fechar como sincronizado', CX_SQL,
     "     SET estado          = 'sincronizado_sem_historico',",
     "     SET estado          = 'sincronizado',", SAIDA),

    # Os seis motivos (criterio 5).
    ('coexistencia: a traducao do motivo passa a toLowerCase', CX_CONTRATO,
     "  return CANONICO_DA_META[bruto] ?? null;",
     "  return bruto.toLowerCase() as MotivoDeDesligamento;", SAIDA),
    ('coexistencia: o desligamento deixa de ser idempotente', CX_SQL,
     "     AND desligado_em IS NULL\n  RETURNING id::text AS id",
     "  RETURNING id::text AS id", SAIDA),
    ('coexistencia: um canal desligado volta a poder desligar-se', CX_SQL,
     "     AND estado IN ('pendente', 'ativo', 'restrito')",
     "     AND estado IS NOT NULL", SAIDA),

    # O aviso dos 10 dias (criterio 6).
    ('coexistencia: o aviso deixa de ser idempotente', CX_SQL,
     "     AND avisado_em IS NULL\n     AND COALESCE(ultimo_echo_em, iniciado_em) <= $1",
     "     AND COALESCE(ultimo_echo_em, iniciado_em) <= $1", SAIDA),
    ('coexistencia: o canal que nunca teve echo deixa de ser avisado', CX_SQL,
     "     AND COALESCE(ultimo_echo_em, iniciado_em) <= $1",
     "     AND ultimo_echo_em <= $1", SAIDA),
    ('coexistencia: o echo do dono deixa de reabrir a janela do aviso', CX_SQL,
     "         avisado_em     = NULL,\n         actualizado_at = now()\n   WHERE tenant_id = $1 AND channel_id = $2",
     "         actualizado_at = now()\n   WHERE tenant_id = $1 AND channel_id = $2", SAIDA),
    ('coexistencia: o aviso passa a apanhar canais a sincronizar', CX_SQL,
     "   WHERE estado IN ('sincronizado', 'sincronizado_sem_historico')",
     "   WHERE estado IS NOT NULL", SAIDA),
    ('coexistencia: os 10 dias passam a 14', CX_CONTRATO,
     "export const INACTIVIDADE_DO_DONO_MS = 10 * 24 * 60 * 60 * 1_000;",
     "export const INACTIVIDADE_DO_DONO_MS = 14 * 24 * 60 * 60 * 1_000;", SAIDA),

    # O echo (criterio 7).
    ('coexistencia: o echo nosso passa a contar como actividade humana', CX_MODULO,
     "    if (rows.length > 0) {",
     "    if (false) {", SAIDA),
    ('coexistencia: o GREATEST do relogio do echo desaparece', CX_SQL,
     "     SET ultimo_echo_em = GREATEST(COALESCE(ultimo_echo_em, $3), $3),",
     "     SET ultimo_echo_em = $3,", SAIDA),
    ('coexistencia: o echo sem destinatario passa a resolver contacto', CX_MODULO,
     "    if (echo.destinatario.bsuid === null && echo.destinatario.telefone === null) {",
     "    if (false) {", SAIDA),
    ('coexistencia: o destinatario de um echo deixa de ser lido', CX_EXPLOSAO,
     "            telefone: texto(dentro[CAMPO_DO_DESTINATARIO], ID_META_MAXIMO),",
     "            telefone: null,", SAIDA),

    # O modo do canal (criterio 8).
    ('coexistencia: o debito da coexistencia passa a 80 mps', SAIDA_LIMITES,
     "export const MPS_POR_MODO: Readonly<Record<string, number>> = {\n  coexistencia: 15,",
     "export const MPS_POR_MODO: Readonly<Record<string, number>> = {\n  coexistencia: 80,",
     SAIDA),
    ('coexistencia: o modo desconhecido passa a levantar em vez de degradar', SAIDA_LIMITES,
     "  if (typeof modo !== \"string\") return MPS_POR_CANAL;\n  return MPS_POR_MODO[modo] ?? MPS_POR_CANAL;",
     "  if (typeof modo !== \"string\") return MPS_POR_CANAL;\n  return MPS_POR_MODO[modo] ?? 0;",
     SAIDA),

    # A reconexao (criterio 9).
    ('coexistencia: a reconexao deixa de limpar os passos', CX_SQL,
     "         passos_feitos       = '{}'::text[],",
     "         passos_feitos       = channel_coexistence.passos_feitos,", SAIDA),
    ('coexistencia: a reconexao deixa de limpar o desligamento', CX_SQL,
     "         motivo_desligamento = NULL,\n         desligado_em        = NULL,",
     "         alertado_em         = NULL,", SAIDA),

    # Da revisao adversarial: a ordem do desligamento, a guarda de modo, a
    # guarda do evento e o echo que nao fica mudo.
    ('coexistencia: o desligamento volta a registar antes de transitar', CX_MODULO,
     "    const { rows } = await cliente.query<{ phone_number_id?: unknown }>(\n"
     "      SQL_DESLIGAR_CANAL,\n      [tenantId, canal.channelId, agora],\n    );",
     "    const { rows } = await cliente.query<{ phone_number_id?: unknown }>(\n"
     "      SQL_DESLIGAR_CANAL,\n      [tenantId, canal.channelId, new Date(0)],\n    );",
     SAIDA),
    ('coexistencia: o aviso de desalinhamento volta a disparar em cloud_only', CX_MODULO,
     '    if (registo.rows.length === 0 && canal.channelMode === "coexistencia") {',
     "    if (registo.rows.length === 0) {", SAIDA),
    ('coexistencia: o evento do account_update deixa de ser conferido', CX_MODULO,
     "    if (bruto.evento !== EVENTO_PARTNER_REMOVED) {",
     "    if (false) {", SAIDA),
    ('coexistencia: o echo sem linha de coexistencia volta a ficar mudo', CX_MODULO,
     "    if (relogio.rows.length === 0) {",
     "    if (false) {", SAIDA),

    # As metricas.
    ('coexistencia: a etiqueta deixa de ser conferida', CX_METRICAS,
     "      if (permitidos === undefined || !permitidos.includes(sufixo)) {",
     "      if (false) {", SAIDA),
    ('coexistencia: uma duracao negativa passa a entrar no histograma', CX_METRICAS,
     "    if (!Number.isFinite(segundos) || segundos < 0) {",
     "    if (false) {", SAIDA),

    # ------------------------------ KAM-115, revisao 0019 (aviso ao dono)
    #
    # Seis da revisao, e correm na suite `tests` — e onde vive o
    # `test_avisos_schema.py`. As de codigo correm na `tests_avisos`, que e a
    # propria do ticket e leva as duas baterias.
    ('aviso 0019: a idempotencia perde o lembrete da unicidade', REV19,
     "                UNIQUE (tenant_id, chave, lembrete, canal),",
     "                UNIQUE (tenant_id, chave, canal),", "tests"),
    ('aviso 0019: a idempotencia perde o canal da unicidade', REV19,
     "                UNIQUE (tenant_id, chave, lembrete, canal),",
     "                UNIQUE (tenant_id, chave, lembrete),", "tests"),
    ('aviso 0019: o tecto dos lembretes desaparece', REV19,
     "                CHECK (lembrete BETWEEN 0 AND {LEMBRETE_MAXIMO}),",
     "                CHECK (lembrete >= 0),", "tests"),
    ('aviso 0019: a entrega passa a implicacao', REV19,
     "                CHECK ((estado = 'entregue') = (entregue_at IS NOT NULL)),",
     "                CHECK (estado <> 'entregue' OR entregue_at IS NOT NULL),", "tests"),
    ('aviso 0019: o episodio passa a poder ser vazio', REV19,
     "                CHECK (length(episodio) > 0),",
     "                CHECK (episodio IS NOT NULL),", "tests"),
    # O dominio da invalidez tem **dois** valores e nao quatro: um fornecedor em
    # baixo nao diz nada sobre o endereco, e marcar o contacto por isso era
    # deixar o dono sem canal por uma avaria nossa.
    ('aviso 0019: a invalidez do contacto passa a aceitar os quatro motivos', REV19,
     'CHECK (motivo_invalido IN ({", ".join(MOTIVOS_DE_INVALIDEZ)})),',
     'CHECK (motivo_invalido IN ({", ".join(MOTIVOS_DE_FALHA)})),', "tests"),
    # Da revisao adversarial da `0018`, aplicada aqui antes de custar: o `GRANT`
    # do `kamba_app` e **por coluna** (sem isso a matriz era vacua) e o
    # `kamba_batch` tem o `INSERT` sem o qual os lembretes nao tinham caminho.
    ('aviso 0019: o kamba_app passa a poder mover um aviso de episodio', REV19,
     '    "estado, entregue_at, falha_motivo, tentativas, actualizado_at"',
     '    "episodio, estado, entregue_at, falha_motivo, tentativas, actualizado_at"',
     "tests"),
    ('aviso 0019: o kamba_batch perde o INSERT dos lembretes', REV19,
     '"GRANT SELECT, INSERT, UPDATE, DELETE ON platform.owner_notices TO kamba_batch"',
     '"GRANT SELECT, UPDATE, DELETE ON platform.owner_notices TO kamba_batch"',
     "tests"),
    ('aviso 0019: o kamba_batch ganha o INSERT dos contactos', REV19,
     '"GRANT SELECT, UPDATE, DELETE ON platform.owner_contacts TO kamba_batch"',
     '"GRANT SELECT, INSERT, UPDATE, DELETE ON platform.owner_contacts TO kamba_batch"',
     "tests"),
    ('aviso 0019: o kamba_app ganha DELETE nos avisos', REV19,
     '"GRANT SELECT, INSERT ON platform.owner_notices TO kamba_app"',
     '"GRANT SELECT, INSERT, DELETE ON platform.owner_notices TO kamba_app"',
     "tests"),

    # A idempotencia e a ordem das recusas (criterios 1, 2 e 4).
    ('aviso: o gatilho desconhecido passa a enviar', AV_DECISAO,
     '  if (!gatilhoConhecido(gatilho)) return nao("gatilho_desconhecido");',
     "  if (false) return nao(\"gatilho_desconhecido\");", AVISOS),
    ('aviso: o mesmo episodio deixa de ser recusado', AV_DECISAO,
     "    if (anterior.gatilho === gatilho && anterior.episodio === episodio) {",
     "    if (false) {", AVISOS),
    ('aviso: a repeticao deixa de distinguir o lembrete', AV_DECISAO,
     "    if (anterior.lembrete !== lembrete) continue;\n",
     "", AVISOS),
    # **A que paga a ordem das recusas.** Sem o `lembrete === 0`, a janela do
    # gatilho recusa os lembretes — que sao, por definicao, um segundo aviso do
    # mesmo gatilho dentro das 24 h — e o criterio 4 deixava de ter caminho.
    ('aviso: a janela do gatilho passa a morder nos lembretes', AV_DECISAO,
     "  if (lembrete === 0) {",
     "  if (true) {", AVISOS),
    ('aviso: a janela de 24 h por gatilho desaparece', AV_DECISAO,
     '        return nao("janela_do_gatilho");',
     "        continue;", AVISOS),
    ('aviso: a janela deixa de filtrar pelo gatilho', AV_DECISAO,
     "      if (anterior.gatilho !== gatilho) continue;\n",
     "", AVISOS),
    ('aviso: o tecto diario passa a contar linhas e nao avisos', AV_DECISAO,
     '    distintos.add(`${anterior.gatilho}${SEPARADOR}${anterior.episodio}${SEPARADOR}${anterior.lembrete}`);',
     "    distintos.add(anterior.id);", AVISOS),
    ('aviso: o tecto diario desaparece', AV_DECISAO,
     '  if (distintos.size >= TECTO_DIARIO) return nao("tecto_diario");',
     "  if (false) return nao(\"tecto_diario\");", AVISOS),
    ('aviso: o tecto diario deixa de recortar a janela', AV_DECISAO,
     "    if (instante - anterior.criadoAt.getTime() >= JANELA_DIARIA_MS) continue;\n",
     "", AVISOS),
    ('aviso: o lembrete acima do maximo deixa de ser recusado', AV_DECISAO,
     '  if (lembrete < 0 || lembrete > LEMBRETE_MAXIMO) return nao("lembretes_esgotados");',
     "  if (false) return nao(\"lembretes_esgotados\");", AVISOS),

    # Os lembretes e o relogio (criterio 4).
    ('aviso: o lembrete devido passa a ser o primeiro e nao o mais alto', AV_DECISAO,
     "    if (decorrido >= atraso) devido = indice + 1;",
     "    if (decorrido >= atraso && devido === null) devido = indice + 1;", AVISOS),
    ('aviso: o lembrete passa a ser devido antes da hora', AV_DECISAO,
     "    if (decorrido >= atraso) devido = indice + 1;",
     "    if (decorrido >= 0) devido = indice + 1;", AVISOS),
    ('aviso: os lembretes passam a esgotar-se antes do ultimo', AV_DECISAO,
     "  if (ultimoEnviado < LEMBRETE_MAXIMO) return false;",
     "  if (false) return false;", AVISOS),
    ('aviso: o lembrete das 24 h passa a 1 h', AV_CONTRATO,
     "  24 * 60 * 60 * 1_000,\n  72 * 60 * 60 * 1_000,",
     "  1 * 60 * 60 * 1_000,\n  72 * 60 * 60 * 1_000,", AVISOS),
    ('aviso: a janela do gatilho passa a 1 h', AV_CONTRATO,
     "export const JANELA_DO_GATILHO_MS = 24 * 60 * 60 * 1_000;",
     "export const JANELA_DO_GATILHO_MS = 1 * 60 * 60 * 1_000;", AVISOS),
    ('aviso: o tecto diario passa de 3 para 30', AV_CONTRATO,
     "export const TECTO_DIARIO = 3;",
     "export const TECTO_DIARIO = 30;", AVISOS),
    ('aviso: a confirmacao passa a valer no instante em que expira', AV_DECISAO,
     "  return agora.getTime() < expiraEm.getTime();",
     "  return agora.getTime() <= expiraEm.getTime();", AVISOS),
    ('aviso: a chave do episodio deixa de levar o tenant', AV_DECISAO,
     "  resumo.update([DOMINIO, tenantId, gatilho, episodio].join(SEPARADOR), \"utf8\");",
     "  resumo.update([DOMINIO, gatilho, episodio].join(SEPARADOR), \"utf8\");", AVISOS),
    ('aviso: o separador da chave passa a ser um ponto', AV_DECISAO,
     'const SEPARADOR = "\\u0000";',
     'const SEPARADOR = ".";', AVISOS),

    # O contacto e a invalidacao (criterios 6 e 7).
    ('aviso: um contacto nao verificado passa a receber avisos', AV_DECISAO,
     "  return contacto.verificadoAt !== null && contacto.invalidoAt === null;",
     "  return contacto.invalidoAt === null;", AVISOS),
    ('aviso: um contacto invalido volta a receber avisos', AV_DECISAO,
     "  return contacto.verificadoAt !== null && contacto.invalidoAt === null;",
     "  return contacto.verificadoAt !== null;", AVISOS),
    ('aviso: um fornecedor em baixo passa a condenar o endereco', AV_DECISAO,
     "  return MOTIVOS_DE_INVALIDEZ.includes(motivo);",
     "  return true;", AVISOS),
    ('aviso: o painel passa a exigir endereco', AV_DECISAO,
     "  return CANAIS_COM_ENDERECO.includes(canal);",
     "  return true;", AVISOS),

    # A lista branca de modelos (criterio 5).
    ('aviso: o parametro fora da lista deixa de ser recusado na construcao', AV_MODELOS,
     "    if (!(PARAMETROS as readonly string[]).includes(nome)) {\n      throw new ParametroInvalidoError(nome);\n    }\n  }\n  const loja",
     "    if (false) {\n      throw new ParametroInvalidoError(nome);\n    }\n  }\n  const loja",
     AVISOS),
    ('aviso: o nome da loja deixa de ser mascarado', AV_MODELOS,
     "  const limpo = mascarar(nome.trim().replace(/\\s+/g, \" \"));",
     "  const limpo = nome.trim().replace(/\\s+/g, \" \");", AVISOS),
    ('aviso: a mascara passa a aceitar dez digitos seguidos', AV_MODELOS,
     "  return texto.replace(/(?:\\d[ .\\-/]*){7,}/g, MASCARA);",
     "  return texto.replace(/(?:\\d[ .\\-/]*){11,}/g, MASCARA);", AVISOS),
    ('aviso: a mascara deixa de apanhar os separadores', AV_MODELOS,
     "  return texto.replace(/(?:\\d[ .\\-/]*){7,}/g, MASCARA);",
     "  return texto.replace(/\\d{7,}/g, MASCARA);", AVISOS),
    ('aviso: o nome da loja deixa de ser truncado', AV_MODELOS,
     "  return limpo.length > MAXIMO_DA_LOJA ? `${limpo.slice(0, MAXIMO_DA_LOJA - 1)}…` : limpo;",
     "  return limpo;", AVISOS),
    # A mutacao «um marcador sem valor deixa de levantar» esteve aqui, e saiu
    # com a guarda: o `Parametros` e um `Record` **total** dos quatro nomes,
    # pelo que o `valor === undefined` nunca podia ser verdade. A prova por
    # mutacao mostrou-a a sobreviver, e a resposta foi apagar a guarda — e nao
    # escrever um teste para um ramo inalcancavel. E a mesma resposta que o
    # KAM-018 deu as duas guardas do `transicoes.ts`. O invariante que ela
    # pretendia proteger — nenhum modelo leva um marcador fora da lista — tem
    # agora teste proprio, sobre os cinco modelos, pelo `marcadoresDosModelos`.

    # A instrucao: a idempotencia, a entrega e a invalidacao.
    ('aviso: o registo deixa de ser idempotente', AV_SQL,
     "      ON CONFLICT (tenant_id, chave, lembrete, canal) DO NOTHING",
     "", AVISOS),
    ('aviso: o criado_at volta a ser o relogio do servidor', AV_SQL,
     "          criado_at, actualizado_at)\n  VALUES ($1, $2, $3, $4, $5, $6, $7, $7)",
     "          criado_at, actualizado_at)\n  VALUES ($1, $2, $3, $4, $5, $6, now(), now())",
     AVISOS),
    ('aviso: a entrega passa a poder mover o instante duas vezes', AV_SQL,
     "     AND estado = 'pendente'\n   RETURNING id, tenant_id, gatilho, episodio, lembrete, canal, estado,\n             tentativas, falha_motivo, criado_at, entregue_at\n`;\n\n/**\n * Marca um aviso como falhado.",
     "     AND estado <> 'x'\n   RETURNING id, tenant_id, gatilho, episodio, lembrete, canal, estado,\n             tentativas, falha_motivo, criado_at, entregue_at\n`;\n\n/**\n * Marca um aviso como falhado.",
     AVISOS),
    ('aviso: um aviso entregue passa a poder ficar falhado', AV_SQL,
     "     AND estado <> 'entregue'",
     "     AND estado <> 'x'", AVISOS),
    ('aviso: a invalidacao passa a reescrever o primeiro motivo', AV_SQL,
     "     AND invalido_at IS NULL\n   RETURNING id, tenant_id, canal, endereco_enc, verificado_at,",
     "     AND TRUE\n   RETURNING id, tenant_id, canal, endereco_enc, verificado_at,", AVISOS),
    ('aviso: emitir confirmacao deixa de repor o verificado_at', AV_SQL,
     "         verificado_at = NULL,\n         invalido_at = NULL,",
     "         invalido_at = NULL,", AVISOS),
    ('aviso: a confirmacao deixa de conferir o prazo', AV_SQL,
     "     AND confirmacao_expira_em > $4",
     "     AND TRUE", AVISOS),
    ('aviso: a confirmacao deixa de conferir o resumo', AV_SQL,
     "     AND confirmacao_hash = $3\n",
     "", AVISOS),
    ('aviso: o historico deixa de ser por tenant', AV_SQL,
     "   WHERE tenant_id = $1\n     AND criado_at > $2",
     "   WHERE criado_at > $2", AVISOS),
    ('aviso: a varredura dos tenants passa a reclamar dos que estao em onboarding', AV_SQL,
     "   WHERE t.estado = 'ativo'\n     AND c.id IS NULL",
     "   WHERE c.id IS NULL", AVISOS),
    ('aviso: a varredura passa a contar os contactos nao verificados', AV_SQL,
     "          AND c.verificado_at IS NOT NULL\n          AND c.invalido_at IS NULL",
     "          AND TRUE", AVISOS),
    ('aviso: o denominador passa a contar todos os tenants', AV_SQL,
     "    FROM platform.tenants\n   WHERE estado = 'ativo'",
     "    FROM platform.tenants", AVISOS),

    # O modulo: a ordem, o painel e a tarefa a T2.
    ('aviso: o painel passa a aceitar um token no URL', AV_MODULO,
     "  if (/[?#=]/.test(limpo)) {",
     "  if (false) {", AVISOS),
    ('aviso: o painel passa a aceitar http', AV_MODULO,
     '  if (!/^https:\\/\\//.test(limpo)) throw new PainelInvalidoError("nao e https");',
     "  if (false) throw new PainelInvalidoError(\"nao e https\");", AVISOS),
    ('aviso: o canal desconhecido deixa de ser recusado', AV_MODULO,
     "      if (!(CANAIS as readonly string[]).includes(notificador.canal)) {",
     "      if (false) {", AVISOS),
    ('aviso: dois notificadores do mesmo canal deixam de ser recusados', AV_MODULO,
     "      if (this.#porCanal.has(notificador.canal)) {",
     "      if (false) {", AVISOS),
    ('aviso: o estado do texto deixa de vir de uma lista fechada', AV_MODULO,
     "    if (!(ESTADOS_NO_TEXTO as readonly string[]).includes(estado)) {",
     "    if (false) {", AVISOS),
    ('aviso: a falta de contacto deixa de abrir tarefa a T2', AV_MODULO,
     '          assunto: "tenant sem contacto alternativo verificado",\n        });\n        tarefaAberta = true;',
     '          assunto: "tenant sem contacto alternativo verificado",\n        });',
     AVISOS),
    ('aviso: a falha de entrega deixa de condenar o endereco', AV_MODULO,
     "      if (condenaOEndereco(motivo)) {",
     "      if (false) {", AVISOS),
    ('aviso: a linha deduplicada passa a ser entregue outra vez', AV_MODULO,
     "      if (registado === null) {",
     "      if (false) {", AVISOS),

    # Os quatro achados da revisao adversarial, cada um com a sua mutacao.
    ('aviso: o episodio esgotado volta a desaparecer da varredura', AV_SQL,
     "  HAVING max(lembrete) <= $2",
     "  HAVING max(lembrete) < $2", AVISOS),
    ('aviso: a varredura deixa de reconhecer o esgotamento', AV_MODULO,
     "      if (lembretesEsgotados(agora, linha.primeiro_em, enviado)) {",
     "      if (false) {", AVISOS),
    ('aviso: a linha do sem_contacto volta a ser descartada', AV_MODULO,
     "        if (semContacto !== null) escritos.push(semContacto);\n",
     "", AVISOS),
    ('aviso: a hora do aviso volta a sair em UTC', AV_MODULO,
     '    timeZone: FUSO,',
     '    timeZone: "UTC",', AVISOS),
    # **Duas**, e cada uma morre por um teste diferente: a `medium` pelo
    # varrimento do criterio 5 (`09/11/2026` sao oito digitos e a regua apanha-a)
    # e a `short` pela legibilidade (`09/11/26` da o ano em dois digitos). A
    # primeira versao so tinha a `short` e dizia, na razao, que ela trazia oito
    # digitos — mediu-se as tres formas e e a `medium` que os traz.
    ('aviso: a hora do aviso volta a forma media', AV_MODULO,
     '    dateStyle: "long",',
     '    dateStyle: "medium",', AVISOS),
    ('aviso: a hora do aviso volta a forma curta', AV_MODULO,
     '    dateStyle: "long",',
     '    dateStyle: "short",', AVISOS),

    # As metricas.
    ('aviso: a etiqueta deixa de ser conferida', AV_METRICAS,
     "      if (!definicao.valores[indice]?.includes(valor)) {",
     "      if (false) {", AVISOS),
    ('aviso: o numero de etiquetas deixa de ser conferido', AV_METRICAS,
     "    if (etiquetas.length !== definicao.nomes.length) {",
     "    if (false) {", AVISOS),
    ('aviso: uma latencia negativa passa a entrar no histograma', AV_METRICAS,
     "    if (!Number.isFinite(segundos) || segundos < 0) return;",
     "    if (false) return;", AVISOS),
    ('aviso: as contagens de contacto deixam de ser conferidas', AV_METRICAS,
     "    if (!Number.isInteger(semContacto) || semContacto < 0) return;",
     "    if (false) return;", AVISOS),
    # O subprocessador e o gate de `prod` (criterio 8).
    ('aviso: o gate de prod deixa de bloquear', AV_FORNECEDOR,
     '    if (limpar(env[VARIAVEIS.ambiente]).toLowerCase() === AMBIENTE_BLOQUEANTE) {',
     "    if (false) {", AVISOS),
    ('aviso: o gate passa a bloquear fora de prod tambem', AV_FORNECEDOR,
     '    if (limpar(env[VARIAVEIS.ambiente]).toLowerCase() === AMBIENTE_BLOQUEANTE) {',
     "    if (true) {", AVISOS),
    # **A que paga o caso de fronteira**: com o predicado so no pais, um
    # ambiente sem nada declarado tem `country` `AO` por omissao e passava — e
    # nao tem fornecedor nenhum.
    ('aviso: o pendente em Angola deixa de bloquear', AV_FORNECEDOR,
     "  const transfere = country !== PAIS_SEM_TRANSFERENCIA || provider === FORNECEDOR_PENDENTE;",
     "  const transfere = country !== PAIS_SEM_TRANSFERENCIA;", AVISOS),
    ('aviso: a transferencia passa a ser sempre verdadeira', AV_FORNECEDOR,
     "  const transfere = country !== PAIS_SEM_TRANSFERENCIA || provider === FORNECEDOR_PENDENTE;",
     "  const transfere = true;", AVISOS),
    ('aviso: o apd_ref deixa de ser conferido', AV_FORNECEDOR,
     "  if (transfere && apdRef === null) {",
     "  if (false) {", AVISOS),
    ('aviso: a forma do pais deixa de ser conferida', AV_FORNECEDOR,
     "  if (!PAIS.test(country)) {",
     "  if (false) {", AVISOS),
    ('aviso: a forma do fornecedor deixa de ser conferida', AV_FORNECEDOR,
     "  if (!FORNECEDOR.test(provider)) {",
     "  if (false) {", AVISOS),
    ('aviso: a forma da referencia da APD deixa de ser conferida', AV_FORNECEDOR,
     '  if (apdBruto !== "" && !APD_REF.test(apdBruto)) {',
     "  if (false) {", AVISOS),
    ('aviso: a declaracao invalida deixa de levantar', AV_FORNECEDOR,
     "  if (problemas.length > 0) throw new DeclaracaoInvalidaError(problemas);",
     "  if (false) throw new DeclaracaoInvalidaError(problemas);", AVISOS),
    # O texto vai num literal **cru** (`r'...'`): no ficheiro TypeScript
    # esta `\t` — barra invertida e t —, e num literal normal do Python isso
    # virava uma tabulacao. O `--aplicaveis` recusou as duas primeiras
    # tentativas, e e exactamente para isso que esse modo existe.
    ('aviso: as pontas do valor deixam de ser limpas', AV_FORNECEDOR,
     r'  return (valor ?? "").replace(/^[ \t\r\n]+|[ \t\r\n]+$/g, "");',
     '  return valor ?? "";', AVISOS),
    ('aviso: o corte dos 300 s sai dos baldes', AV_METRICAS,
     "export const CORTES_DA_LATENCIA: readonly number[] = [1, 5, 15, 30, 60, 120, 300, 600, 1_800];",
     "export const CORTES_DA_LATENCIA: readonly number[] = [1, 5, 15, 30, 60, 120, 600, 1_800];",
     AVISOS),
    # ------------------------------------------------- KAM-028, a ToolLayer
    #
    # Vinte e seis mutacoes — vinte do ticket e **seis das correccoes da
    # revisao adversarial** —, e cada uma apaga **uma** propriedade que um
    # criterio de aceitacao nomeia. A escolha segue os oito passos do `docs/tecnica/02`
    # §6.1: ha pelo menos uma por passo que tem logica propria, mais as do
    # disjuntor (critero 7), da auditoria (critero 5) e do *lint* (critero 3).
    #
    # **Duas nao sao de logica e sao as mais importantes**: a que faz a redaccao
    # guardar o valor do argumento e a que tira a ordenacao da forma canonica.
    # As duas deixam o codigo a funcionar e quebram o que o critero 5 protege.
    # Delas, **uma** corre na `tests_agr` (a redaccao, que so um varrimento com
    # canarios contra a base apanha) e a outra na `agr_unit`.
    ('tls: o passo 1 deixa de confrontar a lista allowed', AG_TLS_CAMADA,
     "    if inv.nome not in inv.allowed:",
     "    if not inv.allowed:",
     AGR_UNIT),
    # A lista `allowed` da vertical deixa de ser lista fechada: passa a recusar
    # so quando esta vazia. E o passo 1 do §6.1 e o critero 2 do bloco.
    ('tls: o passo 1 passa a aceitar uma tool declarada', AG_TLS_CAMADA,
     "    if not especificacao.ligada:",
     "    if not especificacao.ligada and especificacao.credor is None:",
     AGR_UNIT),
    # Todas as declaradas tem `credor` — e obrigatorio —, pelo que a condicao
    # nunca e verdadeira e uma tool sem executor passa a ser oferecida ao
    # pipeline. E a metade do mecanismo que fecha a validacao (1) do §5.2.
    ('tls: o passo 3 deixa de recusar argumento a mais', AG_TLS_ESPECIFICACOES,
     '        if self.modelo.model_config.get("extra") != "forbid":',
     '        if self.modelo.model_config.get("extra") == "allow":',
     AGR_UNIT),
    # Um modelo que simplesmente **nao declare** `extra` passa a ser aceite, e
    # a omissao do Pydantic e `ignore`: o argumento a mais entra em silencio em
    # vez de dar `VALIDATION_ERROR` (critero 2).
    ('tls: o esquema deixa de recusar o tenant_id', AG_TLS_ESPECIFICACOES,
     "        expostos = sorted(self.parametros_visiveis() & set(PARAMETROS_PROIBIDOS))",
     "        expostos = sorted(self.parametros_visiveis() & set(PARAMETROS_PROIBIDOS[1:]))",
     AGR_UNIT),
    # Fica a recusar `merchant_id`, `seller` e `account` e deixa passar o
    # `tenant_id`, que e o unico dos quatro que e nome canonico e o unico que o
    # ADR-015 nomeia. Uma mutacao que tirasse os quatro era mais facil de matar.
    ('tls: o passo 4 deixa de confrontar o contacto', AG_TLS_CAMADA,
     "    if inv.confirmation.contact_id != inv.ctx.contact_id:",
     "    if inv.confirmation.contact_id is None:",
     AGR_UNIT),
    # Uma confirmacao de **outro contacto** da mesma conversa passa a autorizar
    # a escrita. E a exfiltracao entre contactos do `docs/tecnica/08` §4.4, e o
    # critero 4 pede «do **mesmo** `contact_id`».
    ('tls: o passo 4 deixa de confrontar o turno', AG_TLS_CONTEXTO,
     """            and self.contact_id == ctx.contact_id
            and self.turn_id == ctx.turn_id""",
     """            and self.contact_id == ctx.contact_id""",
     AGR_UNIT),
    # Um botao de um turno anterior passa a valer. E a re-entrega de webhook do
    # §6.3, e o critero 4 pede «no turno actual».
    ('tls: o passo 4 deixa de confrontar a referencia', AG_TLS_CONTEXTO,
     "            and self.referencia == referencia_esperada",
     "            and bool(self.referencia)",
     AGR_UNIT),
    # Um `confirm:{outro_carrinho}` passa a autorizar este. O critero 4 pede
    # `confirm:{cart_id}` e nao «algum botao de confirmacao».
    ('tls: o passo 5 deixa de exigir chave a write e money', AG_TLS_CAMADA,
     "    if not isinstance(inv.idempotency_key, str) or not inv.idempotency_key.strip():",
     "    if inv.idempotency_key is not None and not inv.idempotency_key.strip():",
     AGR_UNIT),
    # Uma chave **ausente** passa; uma chave vazia continua a ser recusada. E a
    # caixa do DoD que diz «`write`/`money` nunca correm sem chave», e e a
    # forma mais provavel de a quebrar sem notar.
    ('tls: o disjuntor passa a valer so para leituras', AG_TLS_CAMADA,
     "        if not self.disjuntor.permite(backend):",
     '        if not self.disjuntor.permite(backend) and especificacao.klass == "read":',
     AGR_UNIT),
    # O critero 7 nao distingue classes, e as tools que mais precisam do
    # disjuntor sao as de escrita: uma `money` contra um PAY em baixo repete-se
    # oito segundos de cada vez.
    ('tls: o disjuntor deixa de repor o contador ao sucesso', AG_TLS_DISJUNTOR,
     "            self._por_backend.pop(backend, None)",
     "            self._por_backend.setdefault(backend, _Estado())",
     AGR_UNIT),
    # Passa a contar falhas **acumuladas** em vez de consecutivas, e com isso
    # abre o disjuntor de um backend que esta de pe.
    ('tls: a meia-abertura deixa passar tudo', AG_TLS_DISJUNTOR,
     "            estado.a_experimentar = True",
     "            estado.a_experimentar = False",
     AGR_UNIT),
    # Passada a pausa, **todas** as chamadas acumuladas passam ao mesmo tempo —
    # que e o oposto do que um disjuntor serve para fazer.
    ('tls: o tecto de escrita passa a ser o de leitura', AG_TLS_CAMADA,
     '        return self._timeout_read if klass == "read" else self._timeout_escrita',
     "        return self._timeout_read",
     AGR_UNIT),
    # Os dois numeros do §6.5 passam a ser um. Uma `money` com 2 s de tecto
    # desiste de uma cobranca que ia completar.
    ('tls: uma entrada declarada deixa de exigir credor', AG_TLS_ESPECIFICACOES,
     "        if self.credor is None or not CREDOR.match(self.credor):",
     "        if self.credor is not None and not CREDOR.match(self.credor):",
     AGR_UNIT),
    # Um `aviso` sem dono com ar de temporario, outra vez: e a disciplina que o
    # KAM-027 impôs ao `registry/gates.yaml`, aqui aplicada ao catalogo.
    ('tls: o catalogo deixa de nomear as declaradas', AG_TLS_ESPECIFICACOES,
     "        return frozenset(self._por_nome)",
     "        return frozenset(self.ligadas())",
     AGR_UNIT),
    # A validacao (1) do §5.2 passa a recusar as duas verticais do Piloto, por
    # causa de dez tools que o KAM-031 e o KAM-035 ainda nao ligaram. E a
    # mutacao que prova que incluir as declaradas nos `nomes()` e deliberado.
    ('tls: o ToolContext passa a aceitar uma chave vazia', AG_TLS_CONTEXTO,
     "            if not isinstance(estado.get(chave), str) or not estado[chave]",
     "            if not isinstance(estado.get(chave), str)",
     AGR_UNIT),
    # Um `contact_id` vazio passa a construir contexto, e uma tool de ambito
    # «tenant **e** contacto» (o `get_order_status` do §6.2) deixa de ter o que
    # confrontar.
    ('tls: a auditoria deixa de escrever quando um passo recusa', AG_TLS_CAMADA,
     "        if inv.registada:\n            return",
     "        if inv.registada or resultado is not None:\n            return",
     AGR_UNIT),
    # A cobertura do critero 5 cai para as invocacoes que **correram**: uma
    # tool `money` recusada no passo 1 — que e a que mais interessa auditar —
    # deixa de ter linha.
    # --- A que nao e de logica, e morre contra a base ------------------------
    ('tls: a redaccao passa a guardar o valor do argumento', AG_TLS_AUDITORIA,
     "            redigido[nome] = type(valor).__name__",
     "            redigido[nome] = str(valor)",
     AGR),
    # O `args_redacted` passa a levar o texto que o cliente escreveu. O codigo
    # continua a funcionar, a coluna continua a ser `jsonb`, e o critero 5
    # («nao contem texto de mensagem nem telefone») fica falso. Quem a mata e o
    # varrimento com canarios, e nao uma asercao sobre o tipo.
    ('tls: a impressao deixa de ordenar as chaves', AG_TLS_AUDITORIA,
     "        valor, sort_keys=True, separators=(\",\", \":\"), ensure_ascii=False, default=str",
     "        valor, sort_keys=False, separators=(\",\", \":\"), ensure_ascii=False, default=str",
     AGR_UNIT),
    # O `args_hash` passa a depender da ordem em que o dicionario foi montado:
    # a mesma chamada da dois hashes, e «foi a mesma chamada» deixa de se poder
    # perguntar — que e a unica coisa que esta coluna serve para responder.
    # --- E o *lint* do critero 3 --------------------------------------------
    ('tls: o lint deixa de exigir o extra=forbid', LA_TOOL_SCHEMA,
     "            if not _proibe_extra(no, _POR_NOME.get(onde, {})):",
     "            if not _proibe_extra(no, _POR_NOME.get(onde, {})) and not _campos(no):",
     TOOL_SCHEMA),
    # Passa a exigir `extra="forbid"` so a modelos **sem** campos, que e o
    # contrario do que importa: um modelo sem campos nao tem argumento a mais
    # para aceitar.
    ('tls: o lint deixa de varrer a escrita fora da TLS', LA_TOOL_SCHEMA,
     "        if not _dentro_da_tls(caminho):",
     "        if _dentro_da_tls(caminho):",
     TOOL_SCHEMA),
    # Inverte o lado: varre escritas **dentro** da TLS (onde sao legitimas) e
    # deixa de varrer fora. A segunda metade do `docs/tecnica/08` §3.2 passa a
    # nao verificar nada.
    # --- As seis das correccoes da revisao adversarial ----------------------
    #
    # Seis propriedades que o codigo **nao tinha** quando a prova por mutacao
    # correu pela primeira vez: todas elas passaram as vinte primeiras mutacoes
    # e nenhuma estava protegida. Uma mutacao por cada, e cada uma repoe
    # exactamente o defeito que a revisao mediu.
    ('tls: as tomadas voltam a ser uma', AG_TLS_CAMADA,
     "        for _ in range(self._quantas):",
     "        for _ in range(1):",
     AGR_UNIT),
    # Repoe o bloqueio de cabeca de fila entre tenants: dez invocacoes de dez
    # tenants com um backend de 200 ms voltam a 2,02 s.
    ('tls: a camada deixa de impor o tecto', AG_TLS_CAMADA,
     """            resultado, ligacao = await asyncio.wait_for(
                asyncio.shield(tarefa), self._espera_de(name) / 1000
            )""",
     """            resultado, ligacao = await tarefa""",
     AGR_UNIT),
    # O `timeout_ms` volta a ser um numero que se passa e ninguem impoe: um
    # executor de 5 s contra o tecto de 2 s devolve `ok=True` em 5 s.
    ('tls: a redaccao volta a deixar passar qualquer nome', AG_TLS_AUDITORIA,
     "        if nome in permitidos:",
     "        if nome not in (None,):",
     AGR_UNIT),
    # Os **nomes** dos argumentos — que vem do modelo — voltam a entrar em claro
    # na `tool_audit`, pelo caminho `VALIDATION_ERROR`.
    ('tls: o erro de negocio volta a apagar a contagem', AG_TLS_CAMADA,
     "            self.disjuntor.absolver(backend)",
     "            self.disjuntor.registar_sucesso(backend)",
     AGR_UNIT),
    # Um backend a alternar entre erro de negocio e falha nunca abre o
    # disjuntor, porque cada resposta de negocio poe a contagem a zero.
    ('tls: a tentativa de meio-aberto deixa de caducar', AG_TLS_DISJUNTOR,
     "            if estado.a_experimentar and self._relogio() < estado.experimenta_ate:",
     "            if estado.a_experimentar:",
     AGR_UNIT),
    # Quem levar a tentativa e nunca responder deixa o backend em disjuntor
    # permanente.
    ('tls: o lint volta a ver so a heranca directa', LA_TOOL_SCHEMA,
     "                if etiqueta == \"BaseModel\" or etiqueta in modelos:",
     "                if etiqueta == \"BaseModel\":",
     TOOL_SCHEMA),
    # Uma `class Args(Base)` com `tenant_id` volta a passar o critero 3.
    # ------------------------------------------ KAM-029, a idempotencia por carrinho
    #
    # Dez mutacoes, com prefixo `idem:` — o `tls:` ja tem vinte e seis e um
    # prefixo e o filtro do `db/mutacoes.py <python> <excerto>`, pelo que
    # misturar as duas series obrigava a correr as duas por cada volta.
    #
    # Cada uma apaga **uma** propriedade que um criterio nomeia, e as cinco
    # primeiras sao as que custam dinheiro: todas elas deixam a encomenda sair a
    # dobrar sem erro nenhum. **Sete morrem na unidade** (`test_tls`) e tres so
    # contra a base — a reserva atomica, a retoma atomica e o fecho no caminho
    # de excepcao nao se medem contra um dicionario, porque o que as faz valer e
    # o `ON CONFLICT`, o `WHERE` e o estado da linha depois de a tomada cair.
    ('idem: a chave passa a levar o turno dentro', AG_TLS_IDEMPOTENCY,
     "    partes = (ctx.tenant_id, ctx.contact_id, tool, referencia)",
     "    partes = (ctx.tenant_id, ctx.contact_id, tool, referencia, ctx.turn_id)",
     AGR_UNIT),
    # E a mutacao central do criterio 6, e a que o `TestOControlDaDerivacao`
    # existe para garantir que o oraculo apanha: com o turno dentro, um segundo
    # toque com `wamid` novo deriva chave nova, nao encontra nada guardado, e
    # cobra outra vez. E exactamente a encomenda a dobrar do criterio 8.
    ('idem: o comprimento deixa de prefixar as partes', AG_TLS_IDEMPOTENCY,
     "    crua = b\"\".join(f\"{len(p.encode('utf-8'))}:\".encode(\"ascii\") + p.encode(\"utf-8\") for p in partes)",
     "    crua = b\"|\".join(p.encode(\"utf-8\") for p in partes)",
     AGR_UNIT),
    # Com um separador literal, um `cart_id` opaco que contenha `|` faz duas
    # particoes diferentes darem a mesma chave: a encomenda de um cliente a
    # responder pela de outro.
    ('idem: o args_hash deixa de ser confrontado', AG_TLS_IDEMPOTENCY,
     "            if bytes(guardado_hash) != args_hash:",
     "            if False:",
     AGR_UNIT),
    # O criterio 3 desaparece: o mesmo `cart_id` com outro conteudo devolve o
    # resultado do conteudo antigo como se fosse o do novo.
    ('idem: o replay deixa de se marcar', AG_TLS_CAMADA,
     "            ok=True, data=reserva.guardado or {}, idempotent_replay=True",
     "            ok=True, data=reserva.guardado or {}, idempotent_replay=False",
     AGR_UNIT),
    # O grafo deixa de poder distinguir um pedido novo de uma repeticao, e o
    # painel diz que a idempotencia nunca actua.
    # **Duas, e os excertos levam a linha seguinte de proposito.** O fecho
    # chama-se em **dois** caminhos — no `except`, antes de a tomada cair, e no
    # `finally` — e sem a linha seguinte o texto aparece duas vezes e nenhuma
    # das duas mutacoes era aplicavel. Foi o que o `--aplicaveis` apanhou depois
    # de a bateria do criterio 4 obrigar a acrescentar o segundo caminho.
    ('idem: a reserva deixa de fechar no fim do pipeline', AG_TLS_CAMADA,
     "                self.fechar_idempotencia(inv, resultado)\n            finally:",
     "                pass\n            finally:",
     AGR_UNIT),
    # A linha fica `em_curso` para sempre: a repeticao espera 3 s e devolve
    # `UPSTREAM_TIMEOUT`, e o carrinho fica inutilizavel. E a janela do achado
    # 12 da `ANALISE-30` a reabrir.
    ('idem: a reserva deixa de fechar no caminho de excepcao', AG_TLS_CAMADA,
     "                self.fechar_idempotencia(inv, resultado)\n            except Exception:",
     "                pass\n            except Exception:",
     AGR),
    # E o **criterio 4**: o `except` fecha a tomada e o `finally` corre depois
    # dele, pelo que sem este caminho a reserva fica aberta precisamente quando
    # o backend ja correu e o registo falhou. Morre contra a base, porque o que
    # a mata e o estado da linha depois de a ligacao ter sido fechada.
    ('idem: a espera deixa de ter tecto', AG_TLS_IDEMPOTENCY,
     "        if relogio() >= limite:\n            return Reserva(codigo=\"UPSTREAM_TIMEOUT\")",
     "        if False:\n            return Reserva(codigo=\"UPSTREAM_TIMEOUT\")",
     AGR_UNIT),
    # O criterio 5 desaparece e com ele a tomada da camada: uma linha
    # `em_curso` de um processo morto prende uma ligacao para sempre. E o ciclo
    # sem tecto que esta bateria apanhou a correr, antes de haver mutacao.
    ('idem: a chave deixa de chegar ao backend', AG_TLS_CAMADA,
     "            chave=inv.chave,",
     "            chave=None,",
     AGR_UNIT),
    # O criterio 4 deixa de poder valer: a frase «o backend e idempotente pela
    # chave» fica sem nada que a sustente, e a retoma de uma linha `falhada`
    # duplica o efeito em vez de o reencontrar.
    ('idem: a reserva deixa de ser atomica', AG_TLS_IDEMPOTENCY,
     "  ON CONFLICT (key) DO NOTHING\n  RETURNING key",
     "  RETURNING key",
     AGR),
    # Sem o `ON CONFLICT`, o segundo dos 50 concorrentes levanta violacao de
    # chave primaria em vez de ler o resultado guardado — e o turno falha, o
    # *job* volta a fila, e a repeticao tenta outra vez. So a base o mostra.
    ('idem: a retoma deixa de ser atomica', AG_TLS_IDEMPOTENCY,
     "  WHERE key = %s AND estado = 'falhada'\n  RETURNING key",
     "  WHERE key = %s\n  RETURNING key",
     AGR),
    # Dois leitores concorrentes de uma linha `falhada` retomam-na os dois e
    # correm os dois o backend; e tambem retoma uma linha `concluida`, que e
    # pior — apaga o resultado guardado e manda executar outra vez. So a base o
    # mostra, porque o que o impede e o `WHERE`.
    # ----------------------------------------------------------- KAM-025, AGR
    #
    # Oito mutacoes, e a escolha nao e arbitraria: cada uma apaga **uma**
    # propriedade que um criterio de aceitacao nomeia. Quatro so morrem contra
    # a base (a tranca, as duas leituras e a RLS), e e isso que justifica a
    # suite propria.
    ('agr: a tranca passa a ser de transaccao', AG_SQL,
     "SELECT pg_try_advisory_lock(hashtextextended(%s::text, 0)) AS consegui",
     "SELECT pg_try_advisory_xact_lock(hashtextextended(%s::text, 0)) AS consegui",
     AGR),
    # Em `autocommit`, um *lock* de transaccao larga no fim da instrucao: a
    # exclusao mutua desaparece sem erro nenhum. E a Decisao 2 do ADR-L004 a
    # ser verificada em vez de afirmada.
    ('agr: a semente do hash deixa de ser fixa', AG_SQL,
     "SELECT pg_try_advisory_lock(hashtextextended(%s::text, 0)) AS consegui",
     "SELECT pg_try_advisory_lock(hashtextextended(%s::text, 1)) AS consegui",
     AGR),
    # Uma semente diferente da chaves diferentes para a mesma conversa, e a
    # colisao com o *lock* dos modos (KAM-018) desaparece.
    # --- O checkpointer (KAM-026) -------------------------------------------
    #
    # Todas morrem na `tests_agr`, e isso foi medido e nao suposto. A licao do
    # KAM-017 esta aqui: uma mutacao que vive no **sitio onde o modulo chama**
    # a instrucao nao morre com um ensaio que chama a instrucao directamente —
    # por isso as do `adelete_thread`, do `aput` e da janela visam o modulo, e
    # a bateria exercita o modulo.
    ('checkpointer: o mais recente passa a ser o mais antigo', AG_SQL,
     "   ORDER BY checkpoint_id DESC\n   LIMIT 1",
     "   ORDER BY checkpoint_id ASC\n   LIMIT 1",
     AGR),
    # O `Checkpoint` do LangGraph diz que o `checkpoint_id` e monotonico e que
    # ordena. Invertido, a retoma de um `interrupt` voltava ao primeiro passo
    # da conversa em vez do ultimo.
    ('checkpointer: as escritas pendentes perdem o task_path na ordem', AG_SQL,
     "   ORDER BY task_path, task_id, idx",
     "   ORDER BY task_id, idx",
     AGR),
    # O `writes_sort_key` da interface e `(task_path, task_id, idx)`, e ela
    # avisa que «an order-sensitive reducer rebuilds a different value than the
    # run produced» se a ordem for outra.
    ('checkpointer: a retencao passa a olhar o checkpoint mais antigo', AG_SQL,
     "  HAVING max(criado_at) < %s",
     "  HAVING min(criado_at) < %s",
     AGR),
    # Com o minimo, uma conversa viva com um checkpoint de ha um ano era
    # apagada inteira: retencao a fazer o trabalho da poda.
    ('checkpointer: a fronteira da retencao passa a incluir o dia do prazo', AG_SQL,
     "  HAVING max(criado_at) < %s",
     "  HAVING max(criado_at) <= %s",
     AGR),
    ('checkpointer: apagar a thread deixa as escritas para tras', AG_CHECKPOINTER,
     "                (consultas.SQL_APAGAR_ESCRITAS_DA_THREAD, (thread_id,)),\n",
     "",
     AGR),
    ('checkpointer: a varredura apaga mesmo o que acordou', AG_RETENCAO,
     "                consultas.SQL_APAGAR_THREAD_PARADA, (thread_id, thread_id, limite)",
     "                consultas.SQL_APAGAR_CHECKPOINTS_DA_THREAD, (thread_id,)",
     AGR),
    # Sem o predicado de tempo no `DELETE`, uma conversa que acorde entre o
    # `SELECT` da lista e o apagamento perde o estado a meio do turno — e a
    # varredura devolve-a como apagada, com razao. Achado da revisao
    # adversarial.
    # Escritas orfas de um checkpoint que ja nao existe: o apagamento a pedido
    # do titular (KAM-070) deixava texto de cliente na base.
    ('checkpointer: o checkpoint novo deixa de ter pai', AG_CHECKPOINTER,
     "                pai,\n                tipo,",
     "                None,\n                tipo,",
     AGR),
    # A cadeia de `parent_checkpoint_id` e a viagem no tempo. Sem ela cada
    # checkpoint fica orfao e o historico nao se anda para tras.
    ('checkpointer: a janela passa a admitir mais uma mensagem', AG_CHECKPOINTER,
     "    if isinstance(mensagens, list) and len(mensagens) > JANELA_MAXIMA:",
     "    if isinstance(mensagens, list) and len(mensagens) > JANELA_MAXIMA + 1:",
     AGR),
    ('checkpointer: a retencao passa a contar para a frente', AG_RETENCAO,
     "    limite = agora - _dt.timedelta(days=dias)",
     "    limite = agora + _dt.timedelta(days=dias)",
     AGR),
    # Com o sinal trocado a varredura apaga **tudo**: nenhuma thread tem
    # escrita depois de daqui a trinta dias.
    ('agr: o unlock deixa de dizer se a tranca era nossa', AG_SQL,
     "SELECT pg_advisory_unlock(hashtextextended(%s::text, 0)) AS largou",
     "SELECT pg_advisory_unlock(hashtextextended(%s::text, 0)) IS NOT NULL AS largou",
     AGR),
    ('agr: o EXISTS do handoff deixa de filtrar a conversa', AG_SQL,
     "              AND h.conversation_id = %s\n              AND h.status = 'waiting'",
     "              AND h.status = 'waiting'", AGR),
    # Com isto, um *handoff* aberto numa conversa fecha a porta a **todas** as
    # conversas da loja — e a resposta continua plausivel.
    ('agr: o waiting deixa de ser o unico estado que fecha', AG_SQL,
     "AND h.status = 'waiting'", "AND h.status <> 'resumed'", AGR),
    # **Muda o caminho e nao a etiqueta.** A primeira versao trocava so a cadeia
    # `"sem_conversa"` por `"executado"`, e com isso o grafo **continuava** a nao
    # correr: modelava uma etiqueta mal posta e nao o furo `or 'bot'` que o nome
    # lhe atribui. Agora a condicao desaparece, e e o grafo que corre sobre uma
    # conversa que o AGR nao conseguiu ler — o furo de isolamento mais barato
    # que este ticket podia ter. Achado da revisao adversarial.
    ('agr: zero linhas passa a ler-se como bot', AG_TURNO,
     '                if palavra is None:', '                if False:', AGR),
    ('agr: o modo deixa de ser lista de permitidos', AG_TURNO,
     "        return self.modo != MODO_DO_BOT or self.handoff_a_espera",
     '        return self.modo in ("dono", "humano", "pausada") or self.handoff_a_espera',
     AGR),
    # Equivalente hoje, e **nao** amanha: um modo novo no dominio passa a abrir
    # a porta por omissao, que e o lado errado de errar.
    ('agr: o seq da chave de envio deixa de entrar', AG_CONTEXTO,
     'return f"{self.turn_id}:{seq}"', 'return self.turn_id', AGR),
    # A nona, e a unica que muda um bloco inteiro: e a reposicao do defeito C2
    # que a revisao adversarial encontrou. A espera pela tranca volta a correr
    # **dentro** do `asyncio.Lock` que serializa a unica ligacao de tranca do
    # processo — que e o que acontece com `pg_advisory_lock` a bloquear no
    # servidor. Quem a mata e o
    # `test_repeticao.py::TestDoisExecutoresNaMesmaConversa::test_a_espera_de_uma_conversa_nao_prende_outra`,
    # e sem essa bateria o defeito nao tinha quem o apanhasse: nenhum dos
    # outros testes punha dois `TrancaDeConversas` sobre a mesma chave.
    #
    # E a razao de o `AG_TRANCAS` existir: a revisao notou que a constante
    # estava declarada e **nao usada** — isto e, nao havia mutacao nenhuma
    # sobre o ficheiro onde vive a propriedade mais delicada do ticket.
    ('agr: a espera pela tranca volta a ser exclusiva', AG_TRANCAS,
     '''        espera = ESPERA_INICIAL_S
        limite = self._agora() + ESPERA_TOTAL_MAXIMA_S
        while True:
            if await self._executar(SQL_TRANCAR_THREAD, thread_id) is True:
                return
            if self._agora() >= limite:
                raise TrancaNaoObtidaError("tranca_nao_obtida")
            await asyncio.sleep(espera)
            espera = min(espera * 2, ESPERA_MAXIMA_S)''',
     '''        espera = ESPERA_INICIAL_S
        limite = self._agora() + ESPERA_TOTAL_MAXIMA_S
        async with self._exclusiva:
            while True:
                linha = await asyncio.to_thread(
                    self._sincrono, SQL_TRANCAR_THREAD, thread_id
                )
                if linha is True:
                    return
                if self._agora() >= limite:
                    raise TrancaNaoObtidaError("tranca_nao_obtida")
                await asyncio.sleep(espera)
                espera = min(espera * 2, ESPERA_MAXIMA_S)''', AGR),
    # --- KAM-027: o AgentRegistry e a guarda do SBOM ---------------------------
    #
    # Suite `agr_unit` (`services/agr/tests`), sem base de dados: nada do que
    # estas mutacoes alteram toca o PostgreSQL. Cada uma repoe um defeito que
    # faria **uma** das seis validacoes do §5.2, ou a guarda do critero 7,
    # passar pela razao errada.
    ('registo: a fase volta a ler «nao e piloto» como «ja se pode»', AG_VALIDAR,
     "    if env.fase in FASES_POSTERIORES:",
     "    if env.fase and env.fase != FASE_PILOTO:",
     AGR_UNIT),
    # **A reposicao de um defeito que a revisao adversarial encontrou.** O canon
    # define **um** valor para o `KAMBA_FASE`; ler qualquer outro como «ja nao e
    # Piloto» punha o `assistente` do Fluxo B em producao com um
    # `KAMBA_FASE=clusters` escrito por engano no *deploy* — o que o ADR-011
    # difere ate haver resposta escrita da Meta (D2). Mata-a o
    # `test_5_nenhum_valor_de_kamba_fase_deixa_passar_uma_vertical_diferida`.
    ('registo: a validacao dos nos passa a ser por igualdade', AG_VALIDAR,
     "    em_falta = sorted(set(NOS_OBRIGATORIOS) - nos_do_grafo(grafo))",
     "    em_falta = sorted(nos_do_grafo(grafo) - set(NOS_OBRIGATORIOS))",
     AGR_UNIT),
    # Invertida, a validacao (3) passa a exigir que o grafo **nao** tenha mais
    # nada do que os seis — e deixa passar um grafo a que falte qualquer deles.
    ('registo: os sentinelas do LangGraph passam a contar como nos', AG_VALIDAR,
     '    return frozenset(nome for nome in grafo.nodes if not nome.startswith("__"))',
     "    return frozenset(grafo.nodes)",
     AGR_UNIT),
    # O `__start__` esta em qualquer grafo compilado. A contar, um grafo vazio
    # tem um no — e a validacao (3) mede o LangGraph em vez do desenho.
    ('registo: a tool deixa de ser confrontada com os parametros proibidos', AG_VALIDAR,
     "        expostos = sorted(env.catalogo.parametros_visiveis(tool) & set(PARAMETROS_PROIBIDOS))",
     "        expostos = sorted(env.catalogo.parametros_visiveis(tool) - set(PARAMETROS_PROIBIDOS))",
     AGR_UNIT),
    # Com `-` em vez de `&`, a lista fica com os parametros **permitidos** e o
    # `tenant_id` chega ao modelo. E a metade do critero 2 que o ADR-015 paga.
    ('registo: o catalogo em falta passa a validacao verde', AG_VALIDAR,
     """    if env.catalogo is None:
        return (
            PorLigar(
                "o catalogo da ToolLayer nao esta ligado, pelo que nao se confirma que as "
                f"{len(vertical.tools)} tools de `{vertical.id}` existem nem que nenhuma expoe "
                f"{list(PARAMETROS_PROIBIDOS)} ao modelo"
            ),
        )""",
     "    if env.catalogo is None:\n        return ()",
     AGR_UNIT),
    # **A mutacao que importa mais**, porque e o defeito que o bloco avisa: uma
    # fonte que falta devolvida como validacao verde. Com ela, o registo carrega
    # sem nunca ter confrontado tool nenhuma — e o `registry/gates.yaml` deixa de
    # significar o que diz. Mata-a o `test_1_sem_catalogo_a_validacao_bloqueia`.
    ('registo: o modo aviso passa a valer para todas as validacoes', AG_REGISTO,
     '            em_aviso = modo is not None and modo.modo == "aviso"',
     "            em_aviso = modo is not None",
     AGR_UNIT),
    # Com isto, declarar **uma** validacao em `registry/gates.yaml` punha as
    # seis em aviso para aquela vertical: nada bloqueava o arranque.
    ('registo: o dataset golden deixa de ser confrontado nos dois ficheiros', AG_REGISTO,
     "        elif gate.golden != vertical.golden.dataset:",
     "        elif False:",
     AGR_UNIT),
    ('registo: a vertical repetida passa a ser a ultima por ordem alfabetica', AG_REGISTO,
     "        if vertical.id in verticais:",
     "        if False:",
     AGR_UNIT),
    ('registo: resolve deixa de exigir entitlement activo', AG_REGISTO,
     "        if not entitlement.permitido:",
     "        if False:",
     AGR_UNIT),
    # O critero 6 ao contrario: um tenant sem plano passa a ter a vertical.
    ('registo: o codigo de um aviso deixa de caber no error_code', AG_REGISTO,
     "        return f\"{self.validacao}_{self.credor.lower().replace('-', '_')}\"",
     '        return f"{self.validacao}_{self.credor}"',
     AGR_UNIT),
    # O `-` de `KAM-028` nao casa o `_CODIGO` da *allowlist* de logs: o campo
    # cai **em silencio** e as linhas de arranque saem sem o que as identifica.
    # Foi o defeito real da primeira versao deste codigo, e e a mutacao que o
    # prende. Mata-a o `test_o_codigo_de_uma_adiada_cabe_no_error_code`.
    ('registo: a guarda do SBOM passa a comparar por subcadeia', AG_EGRESSO,
     """    elif not re.search(
        r"(?<![a-z0-9])" + re.escape(entrada.nome) + r"(?![a-z0-9])", nome
    ):
        return False""",
     "    elif entrada.nome not in nome:\n        return False",
     AGR_UNIT),
    # O `minion` e o `dominion` passam a ser bloqueados — e um gate que bloqueia
    # o que ninguem escolheu e um gate que alguem acaba por desligar (ADR-L001
    # §10). Mata-a o `test_a_fronteira_de_palavra_nao_apanha_quem_ninguem_escolheu`
    # e o teste de paridade com o `lint_arch`.
    ('registo: o limiar do SBOM passa a incluir a versao que ja e permitida', AG_EGRESSO,
     "    return esquerda < direita",
     "    return esquerda <= direita",
     AGR_UNIT),
    ('registo: uma versao ilegivel passa a contar como acima do limiar', AG_EGRESSO,
     "    if partes is None:\n        return True",
     "    if partes is None:\n        return False",
     AGR_UNIT),
    # Para um pacote que ja foi vector de ataque, «nao provado» trata-se como
    # «nao permitido» — a regra que o ADR-L001 §10 escreveu para as imagens sem
    # versao na tag. Com o `9999`, um `litellm` de versao ilegivel passa.
    ('registo: o esquema do registo deixa de fechar as chaves', AG_ESQUEMA,
     '    model_config = ConfigDict(extra="forbid", frozen=True)',
     '    model_config = ConfigDict(extra="ignore", frozen=True)',
     AGR_UNIT),
    # Um `subscricoes:` escrito em vez de `subscriptions:` dava uma vertical sem
    # subscricao nenhuma, **validada com sucesso**: a validacao (4) passava por
    # nao ter nada para rejeitar. E o `extra="forbid"` dos Detalhes Tecnicos.
    ('registo: o aviso deixa de distinguir a fonte em falta do problema real', AG_REGISTO,
     "            reais = [p for p in problemas if not isinstance(p, PorLigar)]",
     "            reais = []",
     AGR_UNIT),
    # **A reposicao do achado mais serio da revisao adversarial.** Com isto, no
    # dia em que o KAM-028 ligasse o catalogo, uma tool inexistente — ou uma que
    # exponha `tenant_id` ao modelo — passava a **aviso**, porque a linha
    # `tools: { modo: aviso }` sobreviveria ao credor: o mecanismo de adiamento
    # a engolir o defeito que a validacao existe para apanhar. Mata-a o
    # `test_o_aviso_cala_a_fonte_em_falta_e_nao_um_problema_real`.
    ('registo: um aviso que sobreviveu ao credor deixa de ser erro', AG_REGISTO,
     "            if not por_ligar:",
     "            if False:",
     AGR_UNIT),
    # Sem este erro, a frase «fechar um aviso e apagar uma linha» passa a ser
    # intencao e nao regra: a linha fica a adiar o que ja nao e adiavel, e e so
    # uma questao de tempo ate calar um defeito. E a disciplina do
    # `canon/extensoes.yaml`, onde uma declaracao que nenhuma superficie usa
    # falha o gate. Mata-a o `test_um_aviso_que_sobreviveu_ao_credor_e_erro`.
    ('registo: a largura das versoes do SBOM deixa de se igualar', AG_EGRESSO,
     "    largura = max(len(partes), len(entrada.limiar))",
     "    largura = min(len(partes), len(entrada.limiar))",
     AGR_UNIT),
    # A outra divergencia que a revisao mediu, no sentido contrario ao da
    # versao ilegivel: sem igualar as larguras **para cima**, um `litellm==1.83`
    # e bloqueado pela guarda e permitido pelo `lint_arch`. Mata-a o teste de
    # paridade, que chama o `versions.satisfies_floor` verdadeiro.
    #
    # **O `min` e nao o `len(entrada.limiar)`, e a diferenca ensina algo.** A
    # primeira versao desta mutacao punha `largura = len(entrada.limiar)` e
    # **sobreviveu** — nao por falta de teste, mas por ser *equivalente*: com o
    # limiar sempre mais longo ou igual, a conta da sobra fica negativa, o
    # `(0,) * -1` e vazio, e a comparacao de tuplos de comprimentos diferentes
    # da o mesmo resultado. Uma mutacao que nao pode mudar comportamento nao
    # prova nada; o `min` trunca mesmo.
    ('registo: o aviso deixa de exigir credor', AG_ESQUEMA,
     '''        if self.modo == "aviso" and self.credor is None:
            raise ValueError(
                "`modo: aviso` sem `credor`: a validacao fica desligada e ninguem a volta a ligar"
            )''',
     "        pass",
     AGR_UNIT),
    # Um atalho sem o ticket que o fecha nao e atalho: e uma validacao desligada
    # para sempre com ar de temporaria.
    # ---------------------------------------------------------------- KAM-030
    #
    # Vinte mutacoes, com prefixo `llm:` — o `tls:` tem vinte e seis e o
    # `idem:` dez, e um prefixo e o filtro do `db/mutacoes.py <python>
    # <excerto>`: misturar as series obrigava a correr as tres por cada volta.
    #
    # Cada uma apaga **uma** propriedade que um criterio nomeia. As quatro
    # primeiras custam mais do que dinheiro: todas elas deixam dados pessoais
    # sair de Angola, ou o custo de os mandar ficar por registar. **Dez morrem
    # na unidade** (`test_llm_*`), **cinco contra a base** — os dois `CHECK`, a
    # RLS da particao, o *trigger* e o `GRANT` por coluna nao se medem contra um
    # dicionario — e **cinco** nas suites de `tools/`.
    ('llm: o gate de destino autoriza em prod', AG_LLM_DESTINOS,
     "        if self.ambiente != AMBIENTE_PROD:\n            return\n",
     "        if True:\n            return\n",
     AGR_UNIT),
    # A mutacao central do criterio 8: sem o KAM-069 nao ha destino autorizado
    # nenhum, pelo que autorizar em `prod` e mandar conteudo de conversa para
    # fora de Angola sem notificacao da APD (ADR-008).
    ('llm: o gate so consulta o primeiro fornecedor', AG_LLM_CLIENTE,
     "            for fornecedor in alias.fornecedores:",
     "            for fornecedor in alias.fornecedores[:1]:",
     AGR_UNIT),
    # O *fallback* e do router do proxy e o cliente nao sabe qual fornecedor vai
    # servir. Autorizar so o de `ordem: 1` deixava o segundo receber os dados
    # **sem** o gate ter sido consultado por ele.
    ('llm: a recusa de destino deixa de escrever linha', AG_LLM_CLIENTE,
     "            self._metricas.contar(metricas_mod.METRICA_LLM_DESTINO_NEGADO)\n            self._falhou(alias, ctx, erro, inicio)",
     "            self._metricas.contar(metricas_mod.METRICA_LLM_DESTINO_NEGADO)",
     AGR_UNIT),
    # Uma transferencia recusada que nao deixa rasto e uma tentativa que a
    # `v_transfer_audit` do KAM-069 nunca vera, e o criterio 5 diz «cada chamada
    # grava 1 linha».
    ('llm: o orcamento reconhece-se pelo estado 400', AG_LLM_ERROS,
     "    if tipo == TIPO_ORCAMENTO:",
     "    if estado == 400:",
     AGR_UNIT),
    # E o que o bloco do ticket manda a letra, e **esta errado**: a versao
    # fixada responde 422 com `type: budget_exceeded`, e usa o 400 para «alias
    # repetido». Mapear pelo estado nunca disparava no orcamento e disparava num
    # erro de provisionamento (`docs/evidencia/KAM-030-litellm.md` §4).
    ('llm: o cache passa a tarifa de entrada', AG_LLM_PRECOS,
     "        + Decimal(tokens_cache) * preco.cache",
     "        + Decimal(tokens_cache) * preco.entrada",
     AGR_UNIT),
    ('llm: o custo perde o termo de saida', AG_LLM_PRECOS,
     "        + Decimal(tokens_out) * preco.saida",
     "        + Decimal(0) * preco.saida",
     AGR_UNIT),
    # As duas acima matam o numero do criterio 5 (0,00045) por caminhos
    # diferentes: a primeira cobra o cache dez vezes a mais, a segunda esquece a
    # saida. Uma formula testada num ponto so nao distinguia nenhuma delas.
    ('llm: sem preco o custo passa a zero', AG_LLM_PRECOS,
     "    if preco is None:\n        return None",
     "    if preco is None:\n        return Decimal(0)",
     AGR_UNIT),
    # Zero afirma que a chamada foi gratuita. Hoje **todas** as chamadas caem
    # aqui (o modelo e `por_decidir` ate o KAM-040 escolher), pelo que esta
    # mutacao poe o custo por tenant a zero e a parecer medido.
    ('llm: o fornecedor que serviu assume-se o primeiro', AG_LLM_CLIENTE,
     "        if prefixo in prefixos:",
     "        if False:",
     AGR_UNIT),
    # Um registo de transferencia a apontar para o destino errado e pior do que
    # nao ter registo: diz que os dados foram para onde nao foram.
    ('llm: o registo que falha passa a levantar', AG_LLM_REGISTO,
     "    except Exception:  # noqa: BLE001 \u2014 ver o ponto 2 da nota do modulo\n        return False",
     "    except Exception:  # noqa: BLE001\n        raise",
     AGR_UNIT),
    # Levantar faz o turno falhar e o *job* voltar a fila, o que **repete a
    # chamada ao modelo**: segunda transferencia, segundo custo, e o mesmo
    # registo a falhar. A perda de uma linha e mais barata.
    ('llm: o tecto do cliente passa a ser o do alias', AG_LLM_CLIENTE,
     "TENTATIVAS_DO_PROXY: Final = 3",
     "TENTATIVAS_DO_PROXY: Final = 1",
     AGR_UNIT),
    # O cliente tem de esperar mais do que o proxy: com o tecto do alias, o
    # cliente desiste antes de o router poder comutar e o *fallback* do criterio
    # 6 nunca acontece.
    ('llm: o hash dos aliases passa a incluir os comentarios', TO_LLM_CONFIG,
     '        if not linha.lstrip().startswith("#")',
     '        if True',
     LLM_CONFIG),
    # O cabecalho gerado nomeia a `versao`: com os comentarios dentro do hash, a
    # versao entra, e «mudou o conteudo e nao a versao» deixa de se distinguir
    # de «mudou a versao» — o criterio 7 fica a nao verificar nada. Foi o
    # defeito da primeira versao deste mecanismo.
    ('llm: o nome do grupo ignora a ordem', TO_LLM_CONFIG,
     '    return alias if ordem == 1 else f"{alias}-fallback{ordem}"',
     '    return alias',
     LLM_CONFIG),
    # Com o mesmo nome nos dois, volta-se ao grupo unico com `simple-shuffle`
    # que **mediu 3 falhas em 20** (`docs/evidencia/KAM-030-litellm.md` §4).
    ('llm: o google passa a prefixo do proxy', TO_LLM_CONFIG,
     '    "google": "gemini",',
     '    "google": "google",',
     LLM_CONFIG),
    # Medido: `google/` da `BadRequestError` e o proxy recusa a configuracao no
    # arranque. O nome do subprocessador nao e o prefixo do LiteLLM.
    ('llm: o pip install dos Dockerfiles deixa de se ler', LA_MANIFESTS,
     "        for segmento in _SEPARADOR_DE_SHELL.split(corpo):",
     "        for segmento in []:",
     PIP_NA_BUILD),
    # Era o estado antes do KAM-030, e e a quarta clausula do criterio 1: um
    # `RUN pip install litellm==1.82.7` passava limpo.
    ('llm: o cosign volta a assumir sempre keyless', SC_COSIGN,
     "    if entrada.cosign_chave_publica:",
     "    if False:",
     COSIGN),
    # A assinatura do LiteLLM nao tem certificado: `--certificate-identity`
    # ficava com a cadeia vazia e `cosign verify` nao verificava identidade
    # nenhuma.
    ('llm: a confirmacao do arranque olha para a tabela e nao para as colunas', AG_LLM_REGISTO,
     "    f\"has_column_privilege('{TABELA}', '{coluna}', 'INSERT')\" for coluna in COLUNAS",
     "    f\"has_table_privilege('{TABELA}', 'INSERT') OR '{coluna}' IS NOT NULL\" for coluna in COLUNAS",
     AGR),
    # O `GRANT` da revisao `0023` e **por coluna**, e o
    # `has_table_privilege(..., 'INSERT')` devolve falso com privilegios de
    # coluna concedidos — pelo que esta mutacao faz o arranque recusar um papel
    # que tem tudo. Mata-se contra a base porque e o servidor que responde.
    ('llm: o CHECK do resultado deixa de ser fechado', REV23,
     "                CHECK (resultado IN ({RESULTADOS_SQL})),",
     "                CHECK (resultado IS NOT NULL),",
     AGR),
    ('llm: uma recusa de destino passa a poder levar custo', REV23,
     "                resultado <> 'destino_negado'\n                OR (tokens_in IS NULL",
     "                resultado IS NOT NULL\n                OR (tokens_in IS NULL",
     AGR),
    # Uma linha `destino_negado` com custo afirma que se pagou por uma chamada
    # que nunca saiu de Angola, e o somatorio por tenant passa a contar o que
    # nao houve.
    ('llm: a particao perde a RLS', REV23,
     '    rls.enable_tenant_rls("llm_call_log_default", schema=ESQUEMA)\n',
     '',
     AGR),
    # Para o *gate* 6 uma particao e uma tabela: sem `FORCE` na particao, um
    # `SELECT` dirigido a ela escapa a politica do pai.
    ('llm: o trigger de imutabilidade so prende o DELETE', REV23,
     "          BEFORE UPDATE OR DELETE ON {TABELA}",
     "          BEFORE DELETE ON {TABELA}",
     AGR),
    # Um `UPDATE` e precisamente o que faria desaparecer uma transferencia que
    # ja aconteceu.
    ('llm: o trigger volta para a particao e deixa de ser herdado', REV23,
     "          BEFORE UPDATE OR DELETE ON {TABELA}\n          FOR EACH ROW",
     "          BEFORE UPDATE OR DELETE ON {PARTICAO}\n          FOR EACH ROW",
     AGR),
    # Era a forma da primeira versao, e a revisao adversarial mostrou o que ela
    # custava: uma particao **nova** nascia sem *trigger*, e e isso que o *job*
    # da retencao (KAM-071) ia criar — um `UPDATE` do dono sobre a particao de
    # 2027 reescrevia registo de custo e fazia desaparecer transferencias.
    # Medido: no pai, uma particao nova **herda-o**.
    ('llm: o TRUNCATE deixa de ser recusado', REV23,
     "    op.execute(f\"ALTER TABLE {TABELA} ENABLE ALWAYS TRIGGER llm_call_log_sem_truncate\")",
     "    pass  # o trigger de TRUNCATE fica sem ENABLE ALWAYS",
     AGR),
    # O *trigger* de linha nao cobre o `TRUNCATE`, e a primeira versao desta
    # revisao nao tinha o de instrucao — por afirmar que uma tabela particionada
    # nao o aceita. Aceita, e mediu-se.
    # ---------------------------------------------------------------- KAM-032
    #
    # Dezenove mutacoes, com prefixo `cit:`. Cada uma apaga **uma** propriedade
    # que um criterio nomeia, e tres delas repoem defeitos que os testes deste
    # ticket apanharam — a quantidade sem vinculo ao `sku`, o intervalo do nome
    # nao reservado, e a comparacao em Kz em vez de centimos (o achado C1 do
    # KAM-139). Correm todas na `agr_unit`.
    ('cit: o dinheiro deixa de exigir vinculo ao sku', AG_VAL_VER,
     "        ligados = [f for f in casam if f.sku and f.sku in linha.skus]",
     "        ligados = list(casam)",
     AGR_UNIT),
    # E o «produto errado com preco certo» que o ADR-007 assinala por extenso e
    # que o criterio 2 poe em segundo lugar na lista de falsos aceites.
    ('cit: a quantidade deixa de exigir vinculo ao sku', AG_VAL_VER,
     "                    _inteiro(f.value) == numero.valor\n                    and f.sku\n                    and f.sku in linha.skus\n",
     "                    _inteiro(f.value) == numero.valor\n",
     AGR_UNIT),
    # O defeito que o `test_qty_unbacked` apanhou: 7 unidades do SKU-100 eram
    # aceites porque 7 era o stock do SKU-500.
    ('cit: sob_consulta deixa de recusar qualquer numero', AG_VAL_VER,
     "        if sob_consulta:",
     "        if False:",
     AGR_UNIT),
    ('cit: a_partir_de passa a poder citar-se como preco fixo', AG_VAL_VER,
     "                and not linha.tem_a_partir_de",
     "                and False",
     AGR_UNIT),
    # As duas acima sao o criterio 4, e cada uma por um lado: um preco publicado
    # como minimo apresentado como final, e um produto sem preco a receber um.
    ('cit: a percentagem passa a aceitar-se', AG_VAL_VER,
     '                erros.append(Erro("discount_unbacked", valor=numero.valor))',
     "                pass",
     AGR_UNIT),
    ('cit: o numero solto passa a aceitar-se', AG_VAL_VER,
     "                if numero.valor is None or numero.valor not in policy.allowed_literals:",
     "                if False:",
     AGR_UNIT),
    # O `outro` e o saco *fail-closed* do extractor: sem esta regra, tudo o que
    # ele nao reconhece passa — e e exactamente o que ele nao reconhece que
    # ninguem olhou.
    ('cit: um valor que coincide com um total dispensa o vinculo sempre', AG_VAL_VER,
     '        if any(f.kind == "total" for f in casam):',
     "        if casam:",
     AGR_UNIT),
    # O criterio 3: um total somado pelo modelo falha porque nao e *fact*. Com
    # esta mutacao qualquer valor que exista em qualquer *fact* passa.
    ('cit: a data compara-se so pela forma completa', AG_VAL_REND,
     '        datahora_display(iso_utc),\n        f"{quando:%d/%m/%Y}",',
     "        datahora_display(iso_utc),",
     AGR_UNIT),
    # O extractor parte «14/11/2026 as 14h30» em dois achados: sem as formas
    # parciais, o texto do proprio *renderer* da `datetime_unbacked` duas vezes.
    ('cit: a virgula de tres digitos passa a decimal', AG_VAL_NORM,
     '        inteiro, _, cauda = texto.rpartition(",")\n        # Regras 2 e 3.\n        if len(cauda) == 3 and cauda.isdigit():',
     '        inteiro, _, cauda = texto.rpartition(",")\n        # Regras 2 e 3.\n        if False:',
     AGR_UNIT),
    # `12,500` passava a valer 12,5 Kz: o formato 4 do criterio 1, lido com um
    # factor de mil de diferenca.
    ('cit: o valor compara-se em Kz e nao em centimos', AG_VAL_NORM,
     "        total = (inteiro * CENTIMOS_POR_KZ + centimos) * escala",
     "        total = (inteiro + centimos) * escala",
     AGR_UNIT),
    # **E o achado C1 do KAM-139 reposto**: o *fact* vem do `search_catalog` em
    # `preco_minor`, e comparar a fala em Kz com centimos falha sempre, por um
    # factor de cem. Esteve errado no desenho ate alguem o medir.
    ('cit: a moeda estrangeira passa a aceitar-se', AG_VAL_NORM,
     "            raise MoedaEstrangeiraError(",
     "            pass\n        elif False:\n            raise MoedaEstrangeiraError(",
     AGR_UNIT),
    ('cit: um bloco text passa a levar digitos', AG_VAL_REND,
     "            if _DIGITO.search(texto):",
     "            if False:",
     AGR_UNIT),
    # A camada 1 deixa de ser camada: o modelo volta a escrever numeros em
    # prosa, e a garantia passa a depender so da rede de seguranca.
    ('cit: um nome com preco dentro passa a renderizar', AG_VAL_REND,
     "        if _PRECO_NO_NOME.search(self.nome):",
     "        if False:",
     AGR_UNIT),
    # O que a reserva do intervalo do nome abre, e que esta guarda fecha: um
    # nome escrito pela PME como «Camisa 99 999 Kz» citava um preco sem *fact*.
    ('cit: o item deixa de levar o sku', AG_VAL_REND,
     "    partes = [sku]",
     "    partes = []",
     AGR_UNIT),
    # O §6.3 do `docs/tecnica/05`: «resposta com `sku` ausente e rejeitada».
    ('cit: os botoes passam a entrar no corpo da mensagem', AG_VAL_REND,
     "    return Renderizacao(texto=\"\\n\".join(linhas), botoes=tuple(botoes))",
     "    return Renderizacao(texto=\"\\n\".join(linhas + botoes), botoes=tuple(botoes))",
     AGR_UNIT),
    # Um `confirm:c_77` no corpo da mensagem da `number_unbacked`: o *renderer*
    # a falhar o seu proprio validador.
    ('cit: a apresentacao passa a ser em UTC', AG_VAL_REND,
     'LUANDA: Final = datetime.timezone(datetime.timedelta(hours=1), "WAT")',
     'LUANDA: Final = datetime.timezone(datetime.timedelta(hours=0), "WAT")',
     AGR_UNIT),
    # Datas e horas em UTC na apresentacao: uma marcacao das 14h30 mostrada como
    # 13h30 ao cliente.
    ('cit: o intervalo de um nome deixa de ser reservado', AG_VAL_EXTR,
     "        for achado in re.finditer(re.escape(nome), texto, re.IGNORECASE):",
     "        for achado in re.finditer(r'(?!x)x', texto, re.IGNORECASE):",
     AGR_UNIT),
    # O outro lado do defeito do nome: «Vestido 2 pecas» volta a dar
    # `qty_unbacked` em todas as respostas sobre esse produto.
    ('cit: o intervalo de um sku deixa de ser reservado', AG_VAL_EXTR,
     "        for achado in re.finditer(re.escape(sku), texto):",
     "        for achado in re.finditer(r'(?!x)x', texto):",
     AGR_UNIT),
    # Os digitos de `SKU-123` passam a ser um numero citado, e nenhuma linha com
    # `sku` passa — o validador a bloquear a loja em vez de a proteger.
    ('cit: o artigo um passa a contar como numero', AG_VAL_EXTR,
     "    if palavras[0] in _ARTIGOS:",
     "    if False:",
     AGR_UNIT),
    # «Encontrei um produto para si» passa a ter o numero 1 e da
    # `number_unbacked`: metade das respostas legitimas recusadas.
]


#: O que a copia leva. `tools/kamba_yaml.py` e `ci/` nao sao codigo de `db/`,
#: mas a suite de isolamento le deles as listas de excepcoes.
def _recusar_importacao_por_pacote() -> None:
    """Recusa se um teste de `core-ts` importar o pacote por especificador.

    A copia leva o `dist` do `core-ts` (sem ele, o `meta-sim` nao carrega), e um
    `dist` na copia e uma segunda fonte do mesmo codigo: um teste que importasse
    `@kamba/core-ts/<modulo>` lia a construcao e nao a fonte mutada, e a prova
    dava «apanhada» sem nada ter sido apanhado. Esta guarda e o que torna a
    razao escrita em `_copiar` verificavel em vez de uma intencao.

    A convencao da casa ja e importar por caminho relativo nos testes, e e esta
    a razao — a mesma que fez a cobertura de `src/outbound/` cair em `dist/` na
    primeira versao do KAM-015.
    """
    achados: list[str] = []
    for pasta in ("tests", "tests_bd"):
        raiz = RAIZ / "packages" / "core-ts" / pasta
        if not raiz.is_dir():
            continue
        for ficheiro in sorted(raiz.rglob("*.ts")):
            texto = ficheiro.read_text(encoding="utf-8")
            if '"@kamba/core-ts' in texto or "'@kamba/core-ts" in texto:
                achados.append(str(ficheiro.relative_to(RAIZ)).replace("\\", "/"))
    if achados:
        raise SystemExit(
            "a prova por mutacao nao pode correr: estes testes importam "
            "`@kamba/core-ts` por especificador, e a copia leva o `dist` — a "
            "mutacao aplicar-se-ia a fonte e o teste leria a construcao:\n  "
            + "\n  ".join(achados)
            + "\nImporte por caminho relativo (`../src/<modulo>/index.ts`)."
        )


def _copiar(destino: Path, suite: str = "tests") -> None:
    ignorar = shutil.ignore_patterns("__pycache__")
    if suite in SUITES_DE_TOOLS:
        # As baterias de `tools/` nao abrem `db/`, `libs/py-core` nem
        # `packages/core-ts`: cada mutacao do gate 9 pagava megabytes de copia
        # para nada, e sao 25 mutacoes.
        #
        # Cada suite de `tools/` leva o **seu** minimo, e nao o de outra: levar
        # a copia do gate 9 para a suite das contagens dava a linha de base
        # vermelha, e uma mutacao «apanhada» sobre isso nao significa nada.
        COPIA_DE_TOOLS[suite](destino, ignorar)
        return
    shutil.copytree(RAIZ / "db", destino / "db", ignore=ignorar)
    shutil.copytree(RAIZ / "libs" / "py-core", destino / "libs" / "py-core", ignore=ignorar)
    # KAM-025: o servico AGR. **E a regra escrita no fim desta funcao a ser
    # cumprida a primeira vez por quem a leu**: as oito mutacoes `agr:` mudam
    # ficheiros de `services/agr/src/kamba_agr/`, a `tests_agr` importa-os pelo
    # `sys.path` relativo a raiz da copia, e sem esta linha a linha de base da
    # suite ficava vermelha com `ModuleNotFoundError: No module named
    # 'kamba_agr'` — e uma mutacao «apanhada» sobre isso nao significa nada.
    # Encontrado pelo proprio corredor, na primeira execucao das oito.
    shutil.copytree(
        RAIZ / "services" / "agr", destino / "services" / "agr", ignore=ignorar
    )
    shutil.copytree(RAIZ / "ci", destino / "ci", ignore=shutil.ignore_patterns("coverage", "sbom"))
    # KAM-028: **um** ficheiro de `docs/`, e nao a pasta. O
    # `test_os_kinds_que_faltam_ao_kam032_estao_registados` le a lista de
    # dividas para confirmar que os tres `kind` que o KAM-032 precisa estao
    # registados com credor — uma afirmacao sobre o **repositorio**, e nao sobre
    # o codigo. Sem o ficheiro, a linha de base da `agr_unit` fica vermelha com
    # `FileNotFoundError` e nenhuma mutacao se pode provar: e a regra do fim
    # desta funcao a valer para um teste que le um documento.
    (destino / "docs").mkdir(parents=True, exist_ok=True)
    shutil.copy(
        RAIZ / "docs" / "dividas-documentais.md",
        destino / "docs" / "dividas-documentais.md",
    )
    # KAM-032: o dicionario, pela mesma razao do ficheiro acima. O `TestCanon`
    # do `test_validador.py` confronta os sete veredictos, os cinco blocos e as
    # cinco metricas com o §3.30 — uma afirmacao sobre o **repositorio**, que a
    # copia tem de levar para a linha de base nao ficar vermelha.
    (destino / "specs").mkdir(parents=True, exist_ok=True)
    shutil.copy(
        RAIZ / "specs" / "02_Dicionario_de_Dados_Canonico.md",
        destino / "specs" / "02_Dicionario_de_Dados_Canonico.md",
    )
    # KAM-030: a pasta `llm/` e o `infra/llm/`, e as duas por baterias que leem
    # **o repositorio** e nao um duplo.
    #
    # O `test_llm_precos` e o `test_llm_aliases` abrem o `llm/aliases.yaml` e o
    # `llm/precos.yaml` reais — de proposito: assim uma tarifa trocada ou um
    # fornecedor fora do inventario sao apanhados pela bateria e nao so pelo
    # lint. O `test_llm_chaves` carrega o `infra/llm/chaves.py` pelo caminho,
    # porque ele vive fora de qualquer pacote instalado (corre a mao na Fase 0).
    # Sem estas duas copias a linha de base da `agr_unit` fica vermelha com
    # `FileNotFoundError`, e e a regra do fim desta funcao outra vez.
    shutil.copytree(RAIZ / "llm", destino / "llm", ignore=ignorar)
    shutil.copytree(RAIZ / "infra" / "llm", destino / "infra" / "llm", ignore=ignorar)
    (destino / "tools").mkdir()
    shutil.copy(RAIZ / "tools" / "kamba_yaml.py", destino / "tools" / "kamba_yaml.py")
    # KAM-030: o gerador, para o `TestParidadeComOLlmConfig` do
    # `test_llm_aliases` o carregar pelo caminho. E a maquina que impede a copia
    # de quatro superficies em `kamba_agr/llm/aliases.py` de divergir dele; sem
    # ele, aquela bateria mede «nao ha ficheiro».
    shutil.copytree(
        RAIZ / "tools" / "llm_config", destino / "tools" / "llm_config", ignore=ignorar
    )
    # O modulo de identidade (KAM-008): a fonte e os testes, sem `node_modules`
    # nem `dist` — a suite vai buscar os modulos a `KAMBA_RAIZ_NODE_MODULES`.
    shutil.copytree(
        RAIZ / "packages" / "core-ts", destino / "packages" / "core-ts",
        ignore=shutil.ignore_patterns("node_modules", "dist"),
    )
    # **E o `packages/contracts`, com o `dist` (KAM-014).** Os `node_modules`
    # chegam por `--volume` da arvore real, e a ligacao de *workspace* do pnpm e
    # relativa: `packages/core-ts/node_modules/@kamba/contracts` aponta para
    # `../../contracts`, que se resolve **dentro da copia**. Sem esta pasta,
    # qualquer teste que importe `@kamba/contracts` rebenta com
    # `ERR_MODULE_NOT_FOUND` — e e isso que a linha de base da suite `tests_chr`
    # dizia, porque o `chr/eventos.ts` valida o payload pelo catalogo de
    # contratos antes de o emitir.
    #
    # Leva o `dist` e nao so a fonte: e importado como **pacote**, pelo
    # `exports` do seu `package.json`, e nao por caminho relativo.
    shutil.copytree(
        RAIZ / "packages" / "contracts", destino / "packages" / "contracts",
        ignore=shutil.ignore_patterns("node_modules"),
    )
    # O dicionario exportado: a suite de entrada compara o dominio de `kind` e
    # de `motivo` com **tres** fontes, e uma delas e este ficheiro.
    shutil.copytree(RAIZ / "canon", destino / "canon", ignore=ignorar)
    # **O `tools/meta-sim` e o `config/` (KAM-015)**, e os dois pela regra
    # escrita mais abaixo: uma mutacao nova sobre uma suite que os abre obriga a
    # acrescenta-los aqui.
    #
    # O simulador vai sem `dist`, ao contrario do `packages/contracts`: o seu
    # `exports` aponta para `./src/index.ts` e nao para uma pasta construida. Os
    # `node_modules` chegam por `--volume` da arvore real, como os dos outros.
    # Sem esta pasta, o `import { GraphFalso } from "@kamba/meta-sim"` do ensaio
    # da saida rebenta com `ERR_MODULE_NOT_FOUND` — a ligacao de *workspace* e
    # relativa e resolve-se **dentro da copia**.
    #
    # O `config/meta_rates.yaml` e a outra fonte das tarifas, e a suite
    # `tests_outbound` compara-a com as constantes de `tarifas.ts`: sem ele, o
    # `setUpClass` do `TestTarifas` levanta e a linha de base fica vermelha —
    # isto e, nenhuma mutacao da suite se pode provar. Medido ao correr a
    # primeira.
    shutil.copytree(
        RAIZ / "tools" / "meta-sim", destino / "tools" / "meta-sim",
        ignore=shutil.ignore_patterns("node_modules", "dist", "__pycache__"),
    )
    # **E o `dist/entrada` do `core-ts`, e so ele.** O `meta-sim` importa
    # `@kamba/core-ts/entrada` como **pacote** (tres ficheiros seus leem de la os
    # nomes de campo e os `wa_type`, em vez de os reescrever), e o `exports` do
    # `core-ts` aponta esse subcaminho para `dist/entrada/index.js`. Sem esta
    # pasta, o `import { GraphFalso }` morre com `ERR_MODULE_NOT_FOUND` —
    # medido, e e o que a linha de base da suite `tests_outbound` dizia.
    #
    # **O `dist` inteiro e nao so o `dist/entrada`**: o `dist/entrada/registo.js`
    # importa o `dist/logger/index.js`, e uma construcao e um grafo — recortar
    # uma pasta dele da `ERR_MODULE_NOT_FOUND` na seguinte (medido, nesta ordem).
    #
    # **E um `dist` na copia podia mascarar uma mutacao**: se um teste importasse
    # `@kamba/core-ts/<modulo>` em vez de `../src/<modulo>/index.ts`, a mutacao
    # aplicava-se a fonte, o teste lia a construcao antiga, e a prova dizia
    # «apanhada» sem nada ter sido apanhado. Por isso **confere-se**, em vez de
    # se confiar: a guarda abaixo recusa a copia se algum teste de `core-ts`
    # importar o pacote por especificador. Hoje nenhum o faz — todos importam
    # por caminho relativo, que e a convencao da casa precisamente por isto.
    _recusar_importacao_por_pacote()
    dist = RAIZ / "packages" / "core-ts" / "dist"
    if dist.is_dir():
        shutil.copytree(dist, destino / "packages" / "core-ts" / "dist")
    shutil.copytree(RAIZ / "config", destino / "config", ignore=ignorar)
    # E o que a **lista inteira** precisa de encontrar, mesmo que esta suite nao
    # o corra: o `tests/test_mutacoes.py` corre `--aplicaveis` sobre a lista real
    # **de dentro da copia**, e um ficheiro que falte conta como mutacao nao
    # aplicavel. Sem isto, as 24 entradas do KAM-131 (`tools/scan_secrets`, o
    # `ci.yaml` e o `Makefile`) davam a linha de base vermelha em **todas** as
    # mutacoes da suite `tests` — isto e, nenhuma se podia correr. Encontrado
    # ao correr as do KAM-005; sao poucos kilobytes.
    shutil.copytree(
        RAIZ / "tools" / "scan_secrets", destino / "tools" / "scan_secrets",
        ignore=ignorar,
    )
    # **E aconteceu outra vez, duas vezes.** O KAM-158 acrescentou quatro
    # mutacoes sobre `tools/lint_contagens` e o KAM-007 dezassete sobre
    # `tools/contract_diff` e `contratos/`, e nenhum dos dois estendeu esta
    # copia. Resultado: `aplicaveis()` dava **22** nao aplicaveis de dentro da
    # copia, a linha de base da suite `tests` ficava vermelha, e com ela
    # **nenhuma mutacao desta suite se podia provar** — a prova dizia «a copia
    # sem mutacao nao corre verde» e parava. Descoberto ao correr as do
    # KAM-012.
    #
    # A regra, escrita para a proxima vez: **uma mutacao nova sobre um ficheiro
    # que esta copia nao leva obriga a acrescenta-lo aqui**, mesmo que a suite
    # dela seja outra.
    shutil.copytree(
        RAIZ / "tools" / "lint_contagens", destino / "tools" / "lint_contagens",
        ignore=ignorar,
    )
    shutil.copytree(
        RAIZ / "tools" / "contract_diff", destino / "tools" / "contract_diff",
        ignore=ignorar,
    )
    shutil.copytree(RAIZ / "contratos", destino / "contratos", ignore=ignorar)
    # **E outra vez, pela regra escrita acima** (KAM-027). As mutacoes `registo:`
    # correm na suite `agr_unit`, que le quatro coisas que esta copia nao levava:
    # os ficheiros do registo, o `tools/lint_arch` (o teste de paridade da guarda
    # do SBOM le a lista de bloqueio pelo `load_entries`, que e quem a valida), a
    # lista em si, e o `tools/canon_lint` (o teste que confronta a lista fechada
    # das seis validacoes nos dois lados). Sem elas a linha de base daquela suite
    # fica vermelha e nenhuma mutacao dela se pode provar.
    shutil.copytree(RAIZ / "registry", destino / "registry", ignore=ignorar)
    shutil.copytree(
        RAIZ / "tools" / "lint_arch", destino / "tools" / "lint_arch", ignore=ignorar
    )
    shutil.copytree(
        RAIZ / "tools" / "canon_lint", destino / "tools" / "canon_lint", ignore=ignorar
    )
    shutil.copy(RAIZ / "tools" / "blocklist.yaml", destino / "tools" / "blocklist.yaml")
    # **E o dicionario canonico em Markdown**, e nao so o `canon/` exportado. O
    # teste que a isencao do *gate* 3b promete — o que prende os seis nos
    # obrigatorios e os quatro parametros proibidos ao §3.26 — le a **linha da
    # tabela**, que e o que um leitor humano emenda; o export nao preserva a
    # ordem dentro de uma linha. Sem este ficheiro a linha de base da `agr_unit`
    # ficava vermelha com `FileNotFoundError`, e nenhuma mutacao dela se podia
    # provar. Medido, ao correr as tres novas do KAM-027.
    (destino / "specs").mkdir(exist_ok=True)
    shutil.copy(
        RAIZ / "specs" / "02_Dicionario_de_Dados_Canonico.md",
        destino / "specs" / "02_Dicionario_de_Dados_Canonico.md",
    )
    (destino / ".github" / "workflows").mkdir(parents=True)
    shutil.copy(
        RAIZ / ".github" / "workflows" / "ci.yaml",
        destino / ".github" / "workflows" / "ci.yaml",
    )
    shutil.copy(RAIZ / "Makefile", destino / "Makefile")


def _copiar_para_o_gate_9(destino: Path, ignorar) -> None:
    """O que as mutacoes do gate 9 precisam, e **so** isso (KAM-131).

    O gate 9 nao tem base de dados nenhuma: a copia leva o `scan_secrets`, o
    `ci/secrets-allow.yaml` que ele le, o `tools/kamba_yaml.py` que o le, e os
    dois ficheiros de registo que o `test_ci_gate9.py` confronta.
    """
    shutil.copytree(
        RAIZ / "tools" / "scan_secrets", destino / "tools" / "scan_secrets",
        ignore=ignorar,
    )
    (destino / "tools" / "kamba_yaml.py").parent.mkdir(parents=True, exist_ok=True)
    shutil.copy(RAIZ / "tools" / "kamba_yaml.py", destino / "tools" / "kamba_yaml.py")
    (destino / "ci").mkdir(parents=True, exist_ok=True)
    shutil.copy(
        RAIZ / "ci" / "secrets-allow.yaml", destino / "ci" / "secrets-allow.yaml"
    )
    # O unico ficheiro de `tools/lint_arch/tests` que a copia precisa: o que
    # confronta o job do gate 9 e o alvo `ci-9`.
    testes = destino / "tools" / "lint_arch" / "tests"
    testes.mkdir(parents=True)
    (testes / "__init__.py").write_text("", encoding="utf-8")
    shutil.copy(
        RAIZ / "tools" / "lint_arch" / "tests" / "test_ci_gate9.py",
        testes / "test_ci_gate9.py",
    )
    shutil.copy(RAIZ / "Makefile", destino / "Makefile")
    (destino / ".github" / "workflows").mkdir(parents=True)
    shutil.copy(
        RAIZ / ".github" / "workflows" / "ci.yaml",
        destino / ".github" / "workflows" / "ci.yaml",
    )


def _copiar_para_os_contratos(destino: Path, ignorar) -> None:
    """O que as mutacoes do gate 7 precisam, e so isso (KAM-007).

    Leva o pacote, o `tools/kamba_yaml.py` (o `pii` le a lista aprovada por
    ele), a lista aprovada, e **os contratos**: o `test_catalogo_e_cli.py`
    corre sobre os trinta e oito ficheiros reais, e nao sobre schemas
    inventados — uma logica certa com um catalogo que nao carrega nao serve.
    Leva tambem o `docs/tecnica/06` e o `canon/dicionario.yaml`, que sao as
    duas fontes contra as quais o catalogo e os `enum` se verificam.
    """
    shutil.copytree(
        RAIZ / "tools" / "contract_diff", destino / "tools" / "contract_diff",
        ignore=ignorar,
    )
    shutil.copy(RAIZ / "tools" / "kamba_yaml.py", destino / "tools" / "kamba_yaml.py")
    shutil.copytree(RAIZ / "contratos", destino / "contratos", ignore=ignorar)
    # **E o `registry/`** — a quinta vez, e descoberta pela primeira noite que
    # chegou a correr. O `subscricoes.py` le `registry/*.yaml` por caminho
    # relativo, e o seu docstring ainda diz que a pasta «tem so um README.md»:
    # quatro YAML entraram depois, e o `test_catalogo_e_cli.py` passou a exigir
    # «8 subscricao(oes) lida(s)». Sem a pasta, a copia lia zero.
    shutil.copytree(RAIZ / "registry", destino / "registry", ignore=ignorar)
    (destino / "ci").mkdir(parents=True, exist_ok=True)
    shutil.copy(RAIZ / "ci" / "contratos-allow.yaml", destino / "ci" / "contratos-allow.yaml")
    # E o `docs/tecnica/06`, que e a **fonte** do criterio 1: desde a revisao
    # adversarial (achado M4) o catalogo e verificado contra a tabela do §5 e
    # nao contra o numero 38. Sem o documento, essa bateria nem carrega.
    (destino / "docs" / "tecnica").mkdir(parents=True, exist_ok=True)
    shutil.copy(
        RAIZ / "docs" / "tecnica" / "06_Dados_Eventos_Analytics.md",
        destino / "docs" / "tecnica" / "06_Dados_Eventos_Analytics.md",
    )
    # **E o `canon/dicionario.yaml`** — a quarta vez que a copia fica atras do
    # que a suite abre. O KAM-159 acrescentou o `dominios.py`, que compara os
    # `enum` dos contratos com os dominios do dicionario: o `test_dominios.py`
    # copia-o da raiz real e o canario do `cli.py` (a quinta verificacao) faz o
    # mesmo. A copia do KAM-007 nao o levava, e por isso a linha de base desta
    # suite corria vermelha — em 116 testes, doze `ERROR:` no `test_dominios.py`
    # (nove a copiar o dicionario que nao esta la, tres com `DicionarioAusente`)
    # e os dois `FAIL:` do canario. Com a linha de base vermelha, **nenhuma das
    # dezoito mutacoes de `contratos` se podia provar**: o corredor parava antes
    # de aplicar a primeira. Encontrado ao correr um filtro largo no KAM-015.
    (destino / "canon").mkdir(parents=True, exist_ok=True)
    shutil.copy(RAIZ / "canon" / "dicionario.yaml", destino / "canon" / "dicionario.yaml")


def _copiar_para_as_contagens(destino: Path, ignorar) -> None:
    """O que as mutacoes do `lint_contagens` precisam, e so isso (KAM-158).

    A bateria `test_scan.py` constroi as suas proprias arvores de prova em
    `TemporaryDirectory`, pelo que nao precisa do conjunto documental: leva o
    pacote e o `tools/kamba_yaml.py`, que o `cli` importa ao ser carregado.
    """
    shutil.copytree(
        RAIZ / "tools" / "lint_contagens", destino / "tools" / "lint_contagens",
        ignore=ignorar,
    )
    shutil.copy(RAIZ / "tools" / "kamba_yaml.py", destino / "tools" / "kamba_yaml.py")


def _copiar_para_o_tool_schema(destino: Path, ignorar) -> None:
    """O que as mutacoes do *lint* dos esquemas de tool precisam (KAM-028).

    Duas arvores, e as duas contam:

    * `tools/lint_arch` — o *lint* que se muta e a bateria que o mede;
    * `services/agr` — **a fonte que ele varre**. Sem ela, o
      `test_o_repositorio_esta_conforme` corria sobre uma arvore sem servicos,
      devolvia `[]` por nao haver nada para ver, e a mutacao que inverte o lado
      do `_dentro_da_tls` sobrevivia: e com a arvore que ela se mata, porque a
      `tls/auditoria.py` **tem** um `INSERT INTO platform.tool_audit` legitimo
      que a versao invertida acusa.

    E tambem o que o `test_a_lista_e_a_mesma_que_o_agr_aplica_em_execucao` le
    (`registo/validar.py`), que e o que impede as duas copias dos quatro
    parametros proibidos de divergirem.
    """
    shutil.copytree(
        RAIZ / "tools" / "lint_arch", destino / "tools" / "lint_arch", ignore=ignorar
    )
    # O `lint_arch/__init__.py` importa o `cli`, que importa o `blocklist`, que
    # importa o `kamba_yaml`. Sem ele a **importacao do pacote** falha e a linha
    # de base fica vermelha antes de correr teste nenhum.
    shutil.copy(RAIZ / "tools" / "kamba_yaml.py", destino / "tools" / "kamba_yaml.py")
    shutil.copytree(
        RAIZ / "services" / "agr", destino / "services" / "agr", ignore=ignorar
    )


def _copiar_para_os_aliases(destino: Path, ignorar) -> None:
    """O que as mutacoes do gerador de configuracao do proxy precisam (KAM-030).

    Tres coisas, e as tres contam:

    * `tools/llm_config` — o gerador que se muta e a bateria que o mede;
    * `tools/kamba_yaml.py` — o leitor por onde ele le o `aliases.yaml`;
    * **`llm/`** — a fonte. A bateria copia o `llm/aliases.yaml` e o
      `llm/precos.yaml` do repositorio para uma arvore temporaria e gera a
      configuracao a partir deles; sem a pasta, o `setUp` falha a copiar e a
      linha de base fica vermelha antes de correr teste nenhum.

    O `libs/py-core` entra porque o `nome_da_chave` deriva o nome da variavel
    por `kamba_core.secrets.env.nome_da_variavel` — sem ele o gerador cai no
    caminho de reserva e as duas mutacoes do nome da chave nunca se mediriam
    contra a regra a serio.
    """
    shutil.copytree(
        RAIZ / "tools" / "llm_config", destino / "tools" / "llm_config", ignore=ignorar
    )
    shutil.copy(RAIZ / "tools" / "kamba_yaml.py", destino / "tools" / "kamba_yaml.py")
    shutil.copytree(RAIZ / "llm", destino / "llm", ignore=ignorar)
    shutil.copytree(
        RAIZ / "libs" / "py-core", destino / "libs" / "py-core", ignore=ignorar
    )
    # **E o `services/agr/src`**, que faltava: o `cli.py` le o custo pelo
    # `kamba_agr.llm.precos` — a mesma implementacao que o AGR usa, de proposito
    # — e po-e ele mesmo no `sys.path`, a partir da raiz que recebe. Sem a pasta
    # na copia, tres baterias do `llm_config` davam «nao se conseguiu ler o
    # calculo de precos» e a linha de base ficava vermelha. Nesta maquina
    # passavam pelo `kamba.pth` do `.venv`, que aponta o `services/agr/src`
    # **real**.
    shutil.copytree(
        RAIZ / "services" / "agr" / "src",
        destino / "services" / "agr" / "src",
        ignore=ignorar,
    )
    # E o `pyproject.toml` do AGR: o `kamba_agr/meta.py` le a versao de
    # `parents[2]/pyproject.toml` quando a metadata instalada nao existe, e numa
    # copia nao existe.
    shutil.copy(
        RAIZ / "services" / "agr" / "pyproject.toml",
        destino / "services" / "agr" / "pyproject.toml",
    )


def _copiar_para_o_pip_na_build(destino: Path, ignorar) -> None:
    """O que as mutacoes do leitor de `RUN pip install` precisam (KAM-030).

    O `lint_arch`, o `kamba_yaml` (que o `blocklist` importa) e o
    **`tools/blocklist.yaml`**: a bateria aplica a lista de bloqueio real a
    Dockerfiles de ensaio que ela escreve num temporario, pelo que e a lista que
    decide se o achado aparece. Sem ela o `load_entries` falha e a linha de base
    fica vermelha.
    """
    shutil.copytree(
        RAIZ / "tools" / "lint_arch", destino / "tools" / "lint_arch", ignore=ignorar
    )
    shutil.copy(RAIZ / "tools" / "kamba_yaml.py", destino / "tools" / "kamba_yaml.py")
    shutil.copy(
        RAIZ / "tools" / "blocklist.yaml", destino / "tools" / "blocklist.yaml"
    )


def _copiar_para_o_cosign(destino: Path, ignorar) -> None:
    """O que as mutacoes do verificador de assinaturas precisam (KAM-030).

    O `supply_chain`, o `kamba_yaml`, e **o `ci/supply-chain/` inteiro**: o
    `TestOInventarioRealDoRepositorio` le o inventario de imagens de verdade e
    confere que a entrada do LiteLLM verifica **por chave** e que o ficheiro da
    chave existe. Sem o `ci/`, aquelas duas baterias ficavam a medir «nao ha
    inventario» em vez do que dizem medir.

    **E o `lint_arch`, o `sbom` e o `ci_waivers`**, que a primeira versao desta
    receita nao levava: o `supply_chain/licencas.py` importa os dois primeiros
    no topo do modulo, e o `sbom/cli.py` importa o terceiro, pelo que sem eles
    nem `import supply_chain` corre. A primeira versao parecia funcionar porque
    o `.venv` desta maquina tinha um `kamba.pth` — feito a mao, que nenhum
    ficheiro do projecto cria — a por o `tools/` **real** no `sys.path`: a copia
    ficava a importar os pacotes que lhe faltavam da arvore verdadeira, e a
    linha de base nunca podia ficar vermelha por falta de copia. No *runner*,
    que nao tem esse ficheiro, a suite `cosign` morria em `ModuleNotFoundError`.
    O `TestAsCopiasDeToolsImportamSozinhas` de `db/tests/test_mutacoes.py` passa
    a medir isto sem o `.pth` pelo meio.
    """
    for pacote in ("supply_chain", "lint_arch", "sbom"):
        shutil.copytree(
            RAIZ / "tools" / pacote, destino / "tools" / pacote, ignore=ignorar
        )
    for modulo in ("kamba_yaml.py", "ci_waivers.py"):
        shutil.copy(RAIZ / "tools" / modulo, destino / "tools" / modulo)
    shutil.copytree(
        RAIZ / "ci" / "supply-chain", destino / "ci" / "supply-chain", ignore=ignorar
    )


#: Que copia cada suite de `tools/` leva. Uma suite nova sem entrada aqui falha
#: a dizer que falta — em vez de correr sobre a copia de outra.
COPIA_DE_TOOLS = {
    GATE9: _copiar_para_o_gate_9,
    GATE9_CI: _copiar_para_o_gate_9,
    CONTAGENS: _copiar_para_as_contagens,
    CONTRATOS: _copiar_para_os_contratos,
    TOOL_SCHEMA: _copiar_para_o_tool_schema,
    LLM_CONFIG: _copiar_para_os_aliases,
    PIP_NA_BUILD: _copiar_para_o_pip_na_build,
    COSIGN: _copiar_para_o_cosign,
}


def _gate_de_tools(copia: Path, pacote: str, padrao: str) -> tuple[int, str]:
    """A bateria `tools/<pacote>/tests/<padrao>` na copia (KAM-131).

    Sem Docker e sem PostgreSQL: o gate 9 nao tem base de dados. O `-t tools` e
    o mesmo que o `make test-py` usa, para que os nomes dos modulos sejam os que
    as baterias esperam.
    """
    r = subprocess.run(
        [
            PY, "-m", "unittest", "discover",
            "-s", f"tools/{pacote}/tests", "-t", "tools", "-p", padrao,
        ],
        cwd=copia,
        capture_output=True,
        text=True,
        encoding="utf-8",
        errors="replace",
    )
    return r.returncode, r.stdout + r.stderr


#: Os modulos de `services/agr/tests` que a suite `agr_unit` corre.
#:
#: **Tres, e nao a bateria inteira**, pela mesma razao que as suites de `tools/`
#: correm um ficheiro: as outras baterias do AGR afirmam coisas sobre o
#: **repositorio** que a copia nao e — o `test_api_interna.py` le
#: `ops/secrets-inventory.yaml` e o `test_estado.py` le
#: `docs/tecnica/02_Agent_Runtime_Verticais.md`. Medido: com a bateria inteira a
#: linha de base ficava vermelha nesses dois, e **nenhuma** mutacao se podia
#: provar. O corredor recusou-se a continuar, que e o que ele existe para fazer.
#:
#: **O `test_tls` entrou com o KAM-028, e sem ele as dezessete mutacoes `tls:`
#: dessa suite sobreviviam todas** — nao por falta de teste, mas porque o
#: corredor nao corria o ficheiro que as mata. E a mesma classe de defeito que
#: a nota do KAM-025 descreve para o `_copiar`: quem acrescenta uma bateria que
#: uma mutacao precisa tem de a acrescentar aqui.
#: Os modulos de `services/agr/tests` que a suite `agr_unit` corre.
#:
#: **Esta lista literal custou dez sobreviventes ao KAM-030**, e vale a pena
#: dizer como: as dez mutacoes de unidade dele correram, a suite passou, e o
#: corredor deu-as por **nao apanhadas** — porque os quatro modulos que as
#: matam nao estavam aqui e nunca correram. A suite nao falhou; nao mediu.
#:
#: E a mesma classe de defeito que o `metricas.py` do KAM-027 ja nomeou («uma
#: lista literal transforma uma invariante num numero»), e nao se derivou agora
#: por uma razao: nem todo o modulo de `services/agr/tests` corre sem base de
#: dados, e derivar punha a linha de base vermelha num sitio que nada tem a ver
#: com a mutacao. **Quem acrescentar baterias de unidade ao AGR acrescenta-as
#: aqui**, e o sinal de que se esqueceu e uma mutacao sua a sobreviver com a
#: suite verde.
MODULOS_DO_AGR_UNIT = (
    "test_registo",
    "test_egresso",
    "test_tls",
    # KAM-030.
    "test_llm_precos",
    "test_llm_aliases",
    "test_llm_cliente",
    "test_llm_chaves",
    # KAM-032. **Sem esta linha as mutacoes `cit:` sobreviviam todas**, com a
    # suite verde: e a lista literal de que fala a nota acima, e o KAM-030
    # pagou-a com dez sobreviventes.
    "test_validador",
)


def _gate_do_agr(copia: Path) -> tuple[int, str]:
    """As baterias de unidade do `AgentRegistry` e do egresso, sem Docker.

    Correm sem base de dados — ao contrario da `tests_agr`, que e a suite de
    PostgreSQL do mesmo servico. Nada do que as mutacoes `registo:` alteram toca
    a base, e levantar um contentor por mutacao nao mediria nada a mais.

    O `PYTHONPATH` tem de ser explicito, com o `os.pathsep` da plataforma: o
    `make test-py` herda-o do `Makefile` (que o exporta) e este corredor nao
    corre por `make`. Leva tambem `services/agr/tests`, para que os modulos se
    importem pelo nome como o `-t` do `discover` faria.
    """
    env = dict(
        os.environ,
        PYTHONPATH=os.pathsep.join(
            str(copia / caminho)
            for caminho in (
                "tools", "libs/py-core/src", "services/agr/src", "services/agr/tests",
            )
        ),
    )
    r = subprocess.run(
        [PY, "-m", "unittest", *MODULOS_DO_AGR_UNIT],
        cwd=copia,
        capture_output=True,
        text=True,
        encoding="utf-8",
        errors="replace",
        env=env,
    )
    return r.returncode, r.stdout + r.stderr


def _gate(copia: Path, suite: str) -> tuple[int, str]:
    if suite == AGR_UNIT:
        return _gate_do_agr(copia)
    if suite in SUITES_DE_TOOLS:
        return _gate_de_tools(copia, *SUITES_DE_TOOLS[suite])
    r = subprocess.run(
        [PY, str(copia / "db" / "gate_bd.py"), "--suite", suite],
        capture_output=True,
        text=True,
        encoding="utf-8",
        errors="replace",
        env=dict(os.environ, KAMBA_RAIZ_NODE_MODULES=str(RAIZ)),
    )
    return r.returncode, r.stdout + r.stderr


#: Linhas da saida que dizem **porque** a suite falhou. O resto — o arranque do
#: PostgreSQL, que o `gate_bd.py` tambem captura — e ruido, e as doze ultimas
#: linhas da saida eram quase sempre so isso: a revisao do KAM-143 viu uma
#: linha de base vermelha cujo `ModuleNotFoundError` nao aparecia em parte
#: nenhuma do diagnostico. De noite, isto e tudo o que fica no artefacto.
_PORQUE = ("FAIL:", "ERROR:", "Traceback", "File \"", "gate de BD:", "FATAL:")
#: A ultima linha de um *traceback* nao tem prefixo fixo: e o nome da excepcao.
_EXCEPCAO = re.compile(r"^[A-Za-z_][\w.]*(Error|Exception|Exit|Interrupt|Warning)\b")


def _porque_falhou(saida: str, maximo: int = 20) -> str:
    linhas = [
        l for l in saida.splitlines()
        if l.strip().startswith(_PORQUE) or _EXCEPCAO.match(l.strip())
    ]
    if not linhas:
        # Sem nenhuma linha reconhecivel, as ultimas sao melhor do que nada —
        # e dizer que nao se reconheceu e melhor do que as dar por explicacao.
        return "(nenhuma linha de falha reconhecida; as ultimas da saida)\n" + "\n".join(
            saida.strip().splitlines()[-maximo:]
        )
    return "\n".join(linhas[:maximo])


def linha_de_base(suite: str) -> None:
    """A copia **sem mutacao** tem de correr verde. Sem isto, a prova nao prova nada.

    A primeira versao deste ficheiro nao o verificava, e a prova do KAM-004 deu
    dez mutacoes apanhadas em dez — todas com exactamente quatro falhas. A copia
    nao levava `tools/` nem `ci/`, a suite de isolamento nem sequer importava, e
    **qualquer coisa** contava como «apanhada»: a prova por mutacao estava a
    passar pela razao errada, que e o defeito que ela existe para apanhar.
    """
    with tempfile.TemporaryDirectory() as tmp:
        copia = Path(tmp)
        _copiar(copia, suite)
        codigo, saida = _gate(copia, suite)
    if codigo != 0:
        print(
            f"A copia sem mutacao NAO corre verde na suite `{suite}`. Uma mutacao "
            f"«apanhada» sobre isto nao significa nada.\n{_porque_falhou(saida)}",
            file=sys.stderr,
        )
        sys.exit(2)
    print(f"linha de base verde: `{suite}` sem mutacao", flush=True)


#: Sinais de que a suite falhou por **carga da maquina**, e nao por a mutacao
#: ter sido apanhada. Com mutacoes em paralelo cada uma levanta o seu
#: PostgreSQL, e uma maquina a esgotar ligacoes ou a esperar por um trinco
#: produz `ERROR:` nos testes — que contaria como «apanhada» e dava a prova por
#: feita sem nenhum teste ter mordido. O sinal mais forte do que a contagem:
#: perante um destes, a prova dessa mutacao nao vale.
SINAIS_DE_CARGA = (
    "sorry, too many clients already",
    "canceling statement due to lock timeout",
    "canceling statement due to statement timeout",
    "canceling statement due to user request",
    "deadlock detected",
    "could not obtain lock",
    "server closed the connection unexpectedly",
    "connection refused",
    "the database system is",
)


def classificar(codigo: int, saida: str) -> tuple[str, str]:
    """O que a saida do gate diz sobre esta mutacao. Funcao pura, testavel."""
    falhas = [l for l in saida.splitlines() if l.startswith(("FAIL:", "ERROR:"))]
    if codigo == 0:
        return "SOBREVIVEU", ""
    # Um erro de carregamento (`_FailedTest`) e a suite a nao importar, nao
    # um teste a apanhar a mutacao: conta como prova invalida, nao como apanhada.
    if any("_FailedTest" in l for l in falhas):
        return "PROVA INVALIDA", "a suite nao carregou: " + falhas[0][:90]
    minusculas = saida.lower()
    for sinal in SINAIS_DE_CARGA:
        if sinal in minusculas:
            return (
                "PROVA INVALIDA",
                f"a base cedeu a carga ({sinal}): baixe KAMBA_MUTACOES_PARALELO",
            )
    if not falhas:
        return "PROVA INVALIDA", saida.strip().splitlines()[-1][:110]
    return f"apanhada ({len(falhas)})", falhas[0][:110]


def correr(nome, ficheiro, velho, novo, suite="tests"):
    with tempfile.TemporaryDirectory() as tmp:
        copia = Path(tmp)
        _copiar(copia, suite)
        alvo = copia / ficheiro
        texto = alvo.read_text(encoding="utf-8")
        if texto.count(velho) != 1:
            return "MUTACAO NAO APLICAVEL", ""
        alvo.write_text(texto.replace(velho, novo), encoding="utf-8", newline="\n")
        return classificar(*_gate(copia, suite))


def _suite(mutacao) -> str:
    return mutacao[4] if len(mutacao) > 4 else "tests"


def escolhidas(filtro: str) -> list:
    """As mutacoes que o filtro escolhe: a suite, o nome exacto, ou um excerto."""
    return [
        m for m in MUTACOES
        if not filtro or filtro == _suite(m) or filtro in m[0]
    ]


def _paralelo() -> int:
    valor = os.environ.get("KAMBA_MUTACOES_PARALELO", "8")
    # `isdigit` aceita o que `int` recusa (algarismos em expoente, por exemplo).
    if not (valor.isascii() and valor.isdigit()) or int(valor) < 1:
        print(
            f"KAMBA_MUTACOES_PARALELO tem de ser um inteiro >= 1 (encontrado: {valor!r})",
            file=sys.stderr,
        )
        sys.exit(2)
    return int(valor)


def aplicaveis() -> int:
    """Cada mutacao ainda encontra o seu texto, exactamente uma vez. Sem Docker."""
    falhas = 0
    for mutacao in MUTACOES:
        nome, ficheiro, velho = mutacao[0], mutacao[1], mutacao[2]
        alvo = RAIZ / ficheiro
        vezes = alvo.read_text(encoding="utf-8").count(velho) if alvo.is_file() else -1
        if vezes != 1:
            falhas += 1
            motivo = "ficheiro em falta" if vezes < 0 else f"o texto aparece {vezes} vez(es)"
            print(f"MUTACAO NAO APLICAVEL  {nome}  ({ficheiro}: {motivo})")
    print(f"{len(MUTACOES)} mutacao(oes) conferida(s), {falhas} nao aplicavel(is)")
    return 1 if falhas else 0


def fatiar(lista: list, fatia: str) -> list:
    """`i/n`: a i-esima de n fatias, alternadamente (`1/6` leva a 1.ª, a 7.ª, …).

    Alternadamente e nao em blocos de propósito: as mutacoes de um ticket estao
    juntas na lista e nao custam todas o mesmo — as de identidade semeiam mil
    contactos. Em blocos, uma fatia levava todas as caras e as outras esperavam
    por ela. O preco e cada fatia tocar nas duas suites, e por isso correr as
    duas linhas de base.
    """
    numero, _, total = fatia.partition("/")
    if not (numero.isascii() and numero.isdigit() and total.isascii() and total.isdigit()):
        raise ValueError(f"--fatia tem de ser `i/n` com inteiros (recebido: {fatia!r})")
    i, n = int(numero), int(total)
    if not 1 <= i <= n or n < 1:
        raise ValueError(f"--fatia tem de cumprir 1 <= i <= n (recebido: {fatia!r})")
    return lista[i - 1 :: n]


def _opcao(argumentos: list[str], nome: str) -> tuple[list[str], str | None]:
    """Tira `--nome valor` (ou `--nome=valor`) da lista. Sem valor, levanta."""
    for indice, argumento in enumerate(argumentos):
        if argumento == nome:
            if indice + 1 >= len(argumentos):
                raise ValueError(f"{nome} sem valor")
            return argumentos[:indice] + argumentos[indice + 2 :], argumentos[indice + 1]
        if argumento.startswith(f"{nome}="):
            return argumentos[:indice] + argumentos[indice + 1 :], argumentos[indice].split("=", 1)[1]
    return argumentos, None


def main(argumentos: list[str]) -> int:
    global PY

    # `--aplicaveis` so vale como **primeiro** argumento, e sozinho. Era uma
    # pesquisa de pertenca em toda a linha de comandos, e a revisao do KAM-143
    # mostrou o que isso abria: `--aplicaveis` como **filtro** — que e o que a
    # tarefa nocturna passa na entrada do `workflow_dispatch` — fazia as seis
    # fatias correrem a conferencia de segundos e sairem verdes, com zero
    # mutacoes e zero linhas de base. A prova dava-se por feita.
    if argumentos[:1] == ["--aplicaveis"]:
        if len(argumentos) > 1:
            print(
                "--aplicaveis nao se combina com mais nada: confere a lista inteira "
                f"e sai (recebido tambem: {argumentos[1:]})",
                file=sys.stderr,
            )
            return 2
        return aplicaveis()
    try:
        argumentos, fatia = _opcao(argumentos, "--fatia")
    except ValueError as erro:
        print(erro, file=sys.stderr)
        return 2
    # Nenhum posicional pode parecer uma opcao: um `--qualquer-coisa` aqui e
    # quem chama a enganar-se, nao um filtro.
    for posicional in argumentos[:2]:
        if posicional.startswith("--"):
            print(
                f"{posicional!r} nao e um filtro nem um Python: as opcoes desta "
                "prova sao `--aplicaveis` (sozinha) e `--fatia i/n`",
                file=sys.stderr,
            )
            return 2
    if argumentos:
        # Absoluto, sempre: `_gate_de_tools` corre com o directorio de trabalho
        # **dentro da copia**, e um caminho relativo como `.venv/bin/python` nao
        # existe la. A tarefa nocturna passava-o relativo e as seis fatias
        # morriam todas com FileNotFoundError, sem uma mutacao corrida.
        PY = argumentos[0]
        if ("/" in PY or "\\" in PY) and not Path(PY).is_absolute():
            PY = str(Path(PY).resolve())
    filtro = argumentos[1] if len(argumentos) > 1 else ""

    lista = escolhidas(filtro)
    if not lista:
        # Um filtro que nao escolhe nada nao pode parecer uma prova limpa.
        print(f"o filtro {filtro!r} nao escolhe nenhuma mutacao", file=sys.stderr)
        return 2
    if fatia is not None:
        try:
            lista = fatiar(lista, fatia)
        except ValueError as erro:
            print(erro, file=sys.stderr)
            return 2
        if not lista:
            # Uma fatia vazia saia com 0 e parecia uma fatia limpa. Com mais
            # fatias do que mutacoes, o erro esta em quem fatiou.
            print(
                f"a fatia {fatia} nao tem mutacao nenhuma (o filtro escolheu "
                f"{len(escolhidas(filtro))})",
                file=sys.stderr,
            )
            return 2
        print(f"fatia {fatia}: {len(lista)} mutacao(oes)", flush=True)
    paralelo = _paralelo()
    for suite_usada in sorted({_suite(m) for m in lista}):
        linha_de_base(suite_usada)

    nao_apanhadas = 0
    with concurrent.futures.ThreadPoolExecutor(max_workers=paralelo) as executor:
        futuros = [
            executor.submit(correr, m[0], m[1], m[2], m[3], _suite(m)) for m in lista
        ]
        for mutacao, futuro in zip(lista, futuros):
            try:
                estado, detalhe = futuro.result()
            except Exception as erro:  # noqa: BLE001 - o relatorio tem de chegar ao fim
                # Uma excepcao numa execucao nao pode levar o relatorio das outras.
                estado, detalhe = "PROVA INVALIDA", f"{type(erro).__name__}: {erro}"[:110]
            if not estado.startswith("apanhada"):
                nao_apanhadas += 1
            print(f"{estado:<22} {mutacao[0]}", flush=True)
            if detalhe:
                print(f"{'':<22}   {detalhe}", flush=True)
    print(f"\n{len(lista)} mutacao(oes) corrida(s), {nao_apanhadas} nao apanhada(s)")
    return 1 if nao_apanhadas else 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
