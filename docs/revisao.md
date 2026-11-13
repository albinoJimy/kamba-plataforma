# Fila de revisão por excepção — desenho e *runbook* do revisor

| Campo | Valor |
|---|---|
| Ticket | **KAM-089** — Fila de revisão por excepção para T&S/T2; **KAM-196** — a consola, a identidade da equipa e os avisos ao dono (`../specs/EPIC-09_Onboarding_Governanca.md`) |
| Código | [`../packages/core-ts/src/revisao/`](../packages/core-ts/src/revisao/index.ts), a revisão [`../db/migrations/versions/0048_fila_de_revisao.py`](../db/migrations/versions/0048_fila_de_revisao.py) e a consola [`../services/onboarding-web/src/equipa/`](../services/onboarding-web/src/equipa/rotas.ts) |
| Nomes | Dicionário §3.61 e §3.65 |
| Estado | **Proposta.** O serviço, as tabelas, as portas e a consola HTTP existem e estão medidos contra duplos; **a consola não está montada em processo nenhum**, porque o IdP da equipa não está escolhido (ver §4 e §5). Nenhum procedimento desta página foi ensaiado por um revisor |

---

## 1. O que a fila é

O único sítio onde um humano decide um onboarding (`tecnica/10_Onboarding_Governanca.md` §4.1).
Um caso chega com **motivo interno** (só para T&S), **motivo público** (um de quatro textos fixos,
que é o que o dono lê), **evidências por referência** e **recomendação automática**, e decide-se
em ≤ 1 dia útil de Luanda, p90.

| Quem abre | Tipo | Chave (`motivo_codigo`) |
|---|---|---|
| O KYC K1 (KAM-087), quando a decisão é fila | `kyc` | `kyc_k1` — um caso de K1 por onboarding |
| O screening (KAM-088), numa `condicional` | `categoria` (a declarada) ou `catalogo` (um produto) | `screening:<sha256 do conteúdo>` |
| O guia do Embedded Signup (KAM-093) | `es_falhado` | `es_falhado` |
| A amostragem de aprovações automáticas | `auditoria` | `amostra:<onboarding_id>` |
| A saga (KAM-091), o T&S (KAM-097) e o recurso de uma sanção | `saga`, `trust`, `recurso` | do chamador |

**O lixo não chega aqui.** Um onboarding sem OTP validado não abre caso (a porta recusa e a
entrada falha fechada); o documento ilegível e o duplicado exacto resolvem-se no KYC; uma origem
que abre mais de 20 casos num dia de Luanda (*proposta*) vê o excesso ficar
`em_triagem_automatica`, com alerta, e entrar no dia seguinte. Um caso **sem** onboarding (um
produto do catálogo) conta contra o seu tenant, com a mesma quota; só a amostragem fica fora.

**Um envio repetido reforça o caso pendente.** O KYC que volta a decidir depois de um
`pedir_info` cai no mesmo caso, que fica com o motivo, a recomendação e os documentos novos e
com a prioridade mais urgente das duas — nunca menos urgente.

## 2. O *runbook* do revisor

**Antes de abrir a fila.** Entra-se com conta de equipa com MFA e papel `ts_revisor` ou
`ts_lider`. Sem papel ou sem MFA, nada se lê — e a tentativa fica no `audit_log` como
`review.recusa`.

**1. Escolher.** A lista vem por prioridade (1 é a mais urgente) e por prazo, em páginas de 50, e
não mostra dados pessoais. **Não há exportação**, e não se pede: uma lista inteira de casos com
documentos é o canal de fuga que esta fila existe para não ser.

**2. Abrir o caso.** Abrir passa-o a `em_analise`, e a leitura fica no `audit_log`. O NIF, o BI e o telefone aparecem mascarados
(`*******261`). Se precisar do valor inteiro, **revele um campo de cada vez**: cada revelação
fica no `audit_log` com o seu nome, antes de o valor aparecer.

**3. Ver documentos.** Cada documento abre por uma URL assinada que dura **5 minutos** e que
deixa de abrir depois (403). Cada abertura fica no `audit_log`. Só se abrem os documentos que
são evidência **deste** caso. Não descarregue, não fotografe o ecrã, não reencaminhe.

**4. Decidir.**

| Decisão | Quando | O que acontece |
|---|---|---|
| `aprovar` | A evidência sustenta o pedido | Num caso de prioridade 1 ou 2 (risco alto) é preciso **outro** revisor a aprovar também; o seu voto fica registado e o caso espera. Fechado, o onboarding passa a `aprovado` se nenhum outro caso o bloquear — e o dono só recebe «aprovado» quando isso acontece |
| `rejeitar` | A evidência contradiz o pedido | O onboarding passa a `rejeitado` e o dono recebe por SMS o motivo público que escolher (um dos quatro), ou o do caso. Pode recorrer **uma vez** |
| `pedir_info` | Falta um documento ou um esclarecimento | Num caso `kyc`, o dono pode voltar a carregar documentos; **o caso continua aberto**, e o KYC não o fecha sozinho. Um `pedir_info` entre duas aprovações recomeça a contagem dos dois revisores |
| `escalar` | Dúvida jurídica, suspeita grave, ou é parte | O caso passa a `escalado`, e só o `ts_lider` o decide |

Escreva sempre a **regra** que invoca (um código curto, por exemplo `nif_divergente_confirmado`).
A **nota** é para a equipa: vai cifrada e nunca chega ao dono. **O dono só lê um de quatro textos
fixos** — não há campo para lhe escrever outra coisa, de propósito: um motivo que diga ao
falsificador qual foi a regra ensina-o a passar da próxima vez.

**5. Se for parte.** Se o caso é seu, de um familiar ou de um negócio em que tem interesse, **não
o abra**: escale. A fila recusa sozinha quem tem o mesmo NIF ou telefone do onboarding (num caso
sem onboarding, do onboarding do tenant), mas não sabe das outras relações.

**6. O recurso.** Uma **rejeição** pode ter **um** recurso, decidido por quem **não** decidiu a
primeira instância — e, se o caso foi escalado, por um `ts_lider`. Só aprova ou rejeita. Um
recurso aprovado só tira o onboarding de `rejeitado` se nada mais o rejeitou (os outros casos
aprovados, e um caso de KYC aprovado).

**7. A auditoria.** Um caso `auditoria` aponta o onboarding cuja aprovação automática foi
amostrada: mostra os dados dele mascarados e abre os documentos dele. Se o rejeitar, é um falso
aprovado, e entra na taxa.

**Prazos.** O prazo é 1 dia útil de Luanda a contar da entrada na fila (sábados, domingos e
feriados não contam). Aos 80% sai um alerta. A métrica é o p90 do tempo útil até à primeira
decisão.

## 3. A matriz de responsabilidade

A linha que esta fila acrescenta ao `tecnica/10_Onboarding_Governanca.md` §17:

| Processo | Dono PME | T2 / Ops | T&S | Resp. Produto | Resp. Segurança |
|---|---|---|---|---|---|
| Fila de revisão por excepção (decisão, recurso, amostragem) | I (recebe a decisão e recorre) | R (casos `es_falhado` e `saga`) | R (os outros), A | C (limiares) | C (acesso e auditoria) |

## 4. O que não está feito, e quem o faz

- **O IdP da equipa e as contas de staff.** A consola existe (§5) e só se monta com um IdP
  verdadeiro; a escolha dele e a criação das contas `ts_revisor` e `ts_lider` com MFA são do
  **fundador** (contraparte e conta, critério 1 do KAM-196), escritas com o subprocessador que
  acrescentam (KAM-069). O adaptador do IdP escolhido tem de ligar a prova ao navegador que começou
  a entrada (`state`/`nonce` de OIDC).
- **O `amostrar` sobre cada aprovação automática** é do **KAM-092**: o gancho existe no processo de
  lote (`aprovacaoAutomatica`, §6) e ninguém o chama ainda, porque quem conhece a aprovação
  automática é ele.
- **O aviso ao dono não sai do processo de lote.** Precisa do telefone registado em claro e de um
  agregador de SMS, e nenhum dos dois existe em produção: o agregador não está escolhido
  (fundador, KAM-116) e o telefone cifrado do `onboarding_case` não tem adaptador que o decifre. A
  fase e o screening aplicam-se, o aviso levanta, e o caso fica marcado e reaplicado a cada volta
  (§6) até haver via.
- **A via de e-mail do aviso.** Os textos existem e o adaptador sabe usá-la (`CorreioDoDono`), mas
  o serviço manda sempre por SMS e nenhum fornecedor de e-mail está escolhido (KAM-115).
- **O motivo escolhido na decisão.** O serviço sabe usar um motivo público diferente do do caso no
  aviso dessa decisão, mas não o guarda, e o recurso e a reaplicação voltavam ao do caso. Por isso
  a consola não o aceita: o motivo é o que a abertura fixou. Guardá-lo é uma coluna no
  `review_decision_log`.
- **Os feriados.** A tabela por omissão é **NÃO VERIFICADA** contra a lei em vigor; os móveis
  (Carnaval, Sexta-feira Santa) entram por configuração.
- **Os limiares** — a quota de 20, o risco alto em prioridade ≤ 2, o *score* 60, os 20% e as 8
  semanas da amostragem, as 8 h da sessão da equipa — são propostas que ninguém calibrou.
- **Uma origem partilhada.** Num prefixo de IP móvel partilhado por muitos (CGNAT), a quota é de
  todos, e a triagem drena por ordem de chegada: um atacante constante atrasa os legítimos do
  mesmo prefixo. **PLAUSÍVEL**, por medir: o tamanho real dos prefixos das operadoras.
- **As revogações da consola** perdem-se num reinício, como tudo o que o `onboarding-web` guarda em
  memória; uma sessão terminada volta a valer até ao fim das 8 h.

## 5. A consola `/equipa`

Nove rotas no `onboarding-web` (`../services/onboarding-web/src/equipa/rotas.ts`), JSON, sobre o
`ServicoDeRevisao`:

| Rota | O que faz |
|---|---|
| `GET /equipa/entrar?prova=…` | o regresso do IdP: troca a prova pela sessão `kamba_equipa`; 401 sem prova válida, 403 sem MFA ou sem papel |
| `POST /equipa/sair` | revoga a sessão verificada |
| `GET /equipa/casos?tipo=&estado=&pagina=` | uma página de 50, sem dados pessoais; não há exportação |
| `GET /equipa/casos/:id` | o caso, com NIF, BI e telefone mascarados; passa um `aberto` a `em_analise` |
| `POST /equipa/casos/:id/revelar` | um campo em claro, registado antes de sair |
| `GET /equipa/casos/:id/documentos/:verificacao` | `303` para a URL de ≤ 300 s, registado antes de existir |
| `POST /equipa/casos/:id/decisao` | `aprovar`, `rejeitar`, `pedir_info`, `escalar`, com `regra` e `nota` (cifrada) |
| `POST /equipa/casos/:id/recurso` | regista o recurso que o dono pediu por outro canal |
| `POST /equipa/casos/:id/recurso/decisao` | `aprovar` ou `rejeitar` o recurso, por outro revisor |

**A barreira vem antes do serviço:** sem sessão da equipa, 401; sessão sem MFA ou conta sem papel,
403 com `review.recusa` no `audit_log`. Os papéis lêem-se do IdP a cada pedido. A sessão do dono
não entra: tem outro cookie e outro separador de domínio. Todos os `POST` exigem
`application/json`. Uma decisão registada cujo efeito falhou (a fase, o screening, o aviso)
responde **202** e vai para o *job*.

**O aviso ao dono** sai pelo SMS ao telefone **registado** no onboarding, nunca pelo número da
loja, com um dos cinco modelos `revisao_*` e o texto fixo do motivo público; os e-mails têm os
mesmos cinco casos. O recurso aceite não diz «aprovado», porque o pedido pode esperar por outro
caso.

---

## 6. O processo de lote do onboarding

É o `onboarding-lote` do compose (KAM-198): a imagem do `onboarding-web` com outro `command:`
([`../services/onboarding-web/src/lote.ts`](../services/onboarding-web/src/lote.ts)). Corre o ciclo
da fila a cada minuto, como `kamba_batch`, e serve as quatro métricas em `/metrics` (porta 3014),
que o Prometheus raspa. **Arranca em `prod`**; sem a `KAMBA_LOTE_DB_URL` (o `kamba_batch`) ou a
`KAMBA_LOTE_APP_DB_URL` (o `kamba_app`, só para a decisão humana de screening), ou com uma delas de
outro papel, sai com código 1 antes de abrir a porta.

- **Uma volta**: drena a triagem até à quota do dia de cada origem, dá o alerta dos 80% uma vez
  por caso, reaplica os efeitos marcados e recalcula as métricas. Um passo que falha não pára os
  outros, e o registo diz quais falharam, pelo nome.
- **Os efeitos por reaplicar vivem na base**: a coluna `review_case.efeito_pendente_at` da revisão
  `0052`. Quem decide marca o caso **antes** dos efeitos e limpa-o quando correm todos; um processo
  que morra a meio deixa a marca, e a volta seguinte reaplica-a. Um caso marcado há muito tempo é o
  sinal de que um efeito não tem saída — hoje, o aviso ao dono (§4).
- **A quota vale entre processos**: a contagem e a escrita de uma abertura ou de uma drenagem correm
  na mesma transacção, sob um trinco consultivo da base sobre a chave da quota.
- **O gancho do KAM-092**: `aprovacaoAutomatica(onboarding, tenant)` amostra uma aprovação automática
  neste processo, a contar do dia em `ONBOARDING_LOTE_AMOSTRAGEM_DESDE`; sem esse dia, não amostra.
- A reconciliação da saga (KAM-091) vai correr no mesmo processo.

## Controlo de versões

| Versão | Data | Alteração | Autor |
|---|---|---|---|
| 1.0 | Novembro 2026 | **KAM-089**: criação — o que a fila é, o *runbook* do revisor, a linha da RACI e o que fica por fazer. | Equipa KAMBÁ |
| 1.1 | Novembro 2026 | **KAM-196**: a consola `/equipa` (§5, nova), a identidade da equipa e os avisos ao dono saem do §4; entram nele o IdP e as contas (fundador), o processo de lote (KAM-198), a via de e-mail e o motivo escolhido na decisão. | Equipa KAMBÁ |
| 1.2 | Novembro 2026 | **KAM-198**: o processo de lote do onboarding (§6, nova). Saem do §4 o processo de lote e a quota entre processos; entram nele o aviso ao dono, que não tem via no lote, e o `amostrar` do KAM-092 como item próprio. | Equipa KAMBÁ |
