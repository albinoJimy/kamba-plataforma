# Off-boarding de um tenant — o pedido, a exportação, a revogação, a purga e o certificado

| Campo | Valor |
|---|---|
| Documento | `docs/offboarding.md` |
| Ticket | KAM-098 — Off-boarding: exportação, revogação, purga e certificado |
| Estado | **Proposta.** As fases estão na revisão do off-boarding e medidas em `db/tests/test_offboarding.py` e em `packages/core-ts/tests_bd/offboarding.bd.test.ts`; o processo de lote corre as fases do lado TypeScript desde o KAM-210, e as de dados e as portas para fora ainda não correm em produção (§6). Todos os prazos são *proposta* |
| Âmbito | O que acontece, e em que ordem, quando uma PME pede para sair ou quando T&S encerra um tenant suspenso; o que se apaga, o que fica e porquê; e o que fazer quando uma fase pára |
| Fontes | `docs/tecnica/10` §15.2; `docs/tecnica/08` §8.4, §8.8 e §11; `specs/02` §3.55 e §3.77; ADR-010, ADR-014; E1, E3 §6 |

| Aprovação | Nome | Data |
|---|---|---|
| Fundador | *(por ratificar)* | — |

## 1. As sete fases

Uma linha por fase em `platform.offboarding_run`, escritas todas pelo pedido com o prazo de cada
uma. Cada fase lê o seu estado antes de agir e é idempotente: correr outra vez não repete nada, e
uma fase que parou a meio retoma no passo seguinte.

| Fase | Prazo (*proposta*) | Quem a corre | O que faz |
|---|---|---|---|
| `verificacao` | D0 | `abrirPedido` (TS) | Exige as **duas** confirmações do titular — o OTP ao telefone provado e a ligação ao e-mail registado —, ou, por T&S, um tenant `suspenso` e a referência da decisão. Escreve as sete fases |
| `canal` | D1 | `desligarCanal` (TS) | Cancela a subscrição de *webhooks* de cada WABA e põe o canal `desligado`: o CHR deixa de encaminhar, e é isso que bloqueia encomendas novas. **O WABA e o número ficam do cliente** |
| `pendentes` | D7 | `verificarPendentes` (TS) | Conta encomendas em curso, reservas activas e reembolsos abertos. Sem pendentes, conclui; uma encomenda em disputa não impede, e fica escrita para a purga |
| `exportacao` | D7 | `exportar` (Python) | O pacote ao titular: clientes, encomendas, conversas, consentimentos e a lista de ficheiros, em JSON e CSV, com manifesto e `sha256`. Uma geração nova a cada pedido, cada uma auditada |
| `revogacao` | D7 | `revogar` (TS) | Só no D7 e com a exportação concluída: a chave LiteLLM, o canal Medusa, a *inbox* do Chatwoot, os entitlements a `false`, os canais `encerrado` e o tenant `encerrado`, com o evento do encerramento |
| `purga` | D30 | `purgar` (Python) | Apaga os dados operacionais pelos caminhos medidos, com o `purge_log`. Uma disputa ou um *hold* legal suspendem-na |
| `certificado` | D30 | `emitir_certificado` (Python) | O que saiu e o que ficou, com fundamento, assinado; entregue ao titular |

## 2. Cancelar

O titular cancela até ao D7 — **só o pedido dele**: um encerramento por T&S não o cancela o dono, e um
pedido de T&S sobre um pedido vivo do titular toma-o. O canal volta ao estado de antes (a subscrição
refaz-se), as fases por fazer ficam `cancelada`, e nada se apaga. Um pedido novo, verificado de novo,
**reabre** um cancelado, e o calendário recomeça do novo D0.

## 3. O que fica, e porquê

* **Os registos fiscais** (encomendas, pagamentos e o que os aponta, incluindo a linha do tenant e
  as contas de pagamento): ficam pelo prazo do CGT, que está **NÃO VERIFICADO**. Sem
  `fiscal_retention_years` definido, nada fiscal se apaga. O `payment_events` não tem
  identificadores directos de ninguém (o inventário do *gate* 8 di-lo coluna a coluna).
* **O que está em disputa**: com um *hold* legal no tenant ou num contacto dele, ou uma encomenda
  `em_disputa`, a purga fica `suspensa_disputa` e nada sai. Levantado o *hold*, a purga corre.
* **O que ainda não tem caminho**: os contactos (só o cofre lhes toca), os casos de onboarding e o
  que deles depende, as ingestões do catálogo e os trabalhos de foto. Ficam `recusada` /
  `sem_caminho` no `purge_log` e no certificado, nunca como apagados.
* **O que vive fora da base**: o Chatwoot, os *traces*, as *caches* e os fornecedores de LLM e STT.
  Não têm caminho de eliminação nesta versão, e o certificado lista-os como retidos, com o fundamento.
  Os objectos do STO (as fotos, os bytes da mídia cujas linhas saíram, os pacotes de exportação) saem
  desde o KAM-210 quando a purga recebe o armazenamento, e o certificado diz quantos; sem ele, ficam
  retidos como os outros.
* **O contacto do dono** fica até o certificado lhe ser entregue, e sai logo a seguir.

## 4. As cópias de segurança

Não se reescrevem: expiram pelo ciclo do repositório (35 dias, KAM-079). O certificado **não diz**
que foram apagadas; diz até quando podem ter os dados. Depois de qualquer restauro corre-se
`reaplicar_apos_restauro` com a lista dos tenants purgados e os *holds* **de fora da cópia** (a
exportação do KAM-079): um tenant purgado depois da cópia volta a ser apagado.

## 5. Quando uma fase pára

| Sintoma | O que fazer |
|---|---|
| `pendentes` em `em_curso` | O resultado tem as contagens. Fechar as encomendas, libertar as reservas e registar os reembolsos pelos caminhos de cada um, e correr a fase outra vez |
| `revogacao` a meio | O resultado tem os passos já feitos. Corrigir a porta que falhou e correr outra vez: os feitos não se repetem |
| `purga` em `falhada` | O resultado tem as tabelas que falharam, e o `purge_log` a linha `falhou` (Sev2). Corrigir e correr outra vez |
| `purga` em `suspensa_disputa` | Esperar o fecho da disputa, levantar o *hold*, correr outra vez |
| `certificado` em `em_curso` | A entrega falhou. Correr outra vez: entrega o mesmo documento, com a mesma data |

## 6. O processo, e o que falta para correr em produção

**Desde o KAM-210**, o processo de lote do onboarding (`onboarding-lote`) corre o canal, os
pendentes e a revogação num ciclo agendado (`LOTE_OFFBOARDING_INTERVALO_MS`, 15 min por omissão,
*proposta*) e serve as métricas das **sete** fases; a regra `offboarding_fase_parada` dispara sobre
uma fase `falhada`, ou por acabar 24 h depois do prazo, e o *runbook* é o
[`runbooks/offboarding.md`](runbooks/offboarding.md). As três fases de dados correm pelo
`correr_volta` do `kamba_core.offboarding`, cada uma no seu `try`; uma purga `falhada` ou suspensa
não se repete sozinha. A exportação leva os bytes do STO (até um tecto, *proposta*), e a purga apaga
os objectos do tenant no STO, com a sua linha no `purge_log`.

**O que falta** (credor **KAM-218**): o processo que chama o `correr_volta` em produção; as portas
sem adaptador, que o processo monta como tal e que fazem a fase falhar em vez de fingir — o OTP e a
ligação ao e-mail do dono, o *token* de cada WABA para a Meta (o adaptador existe, falta o leitor do
cofre), o LiteLLM, o Chatwoot (sem método para arquivar a conta), a Medusa, o cofre para os contactos
e os telefones, e a entrega do certificado; o caminho de eliminação das tabelas `sem_caminho`, que é
esquema; e o simulacro em *staging*. O catálogo não entra no pacote enquanto viver só na Medusa. A
assinatura do certificado é HMAC, e não assimétrica.

## 7. Controlo de versões

| Versão | Data | Alteração | Autor |
|---|---|---|---|
| 1.0 | Novembro 2026 | KAM-098: emissão inicial — as sete fases, o cancelamento e a reabertura, o que fica (incluindo o que vive fora da base), as cópias de segurança e o que fazer quando uma fase pára. Um tenant `restrito` não se encerra: o grafo da `0058` não tem a aresta. | Equipa KAMBÁ |
| 1.1 | Novembro 2026 | KAM-210: o §6 passa a dizer o processo que corre as fases, as métricas e o alerta da fase parada (com o *runbook* próprio), e o STO na exportação e na purga; o que falta tem credor, o KAM-218. | Equipa KAMBÁ |
