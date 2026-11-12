# Fila de revisão por excepção — desenho e *runbook* do revisor

| Campo | Valor |
|---|---|
| Ticket | **KAM-089** — Fila de revisão por excepção para T&S/T2 (`../specs/EPIC-09_Onboarding_Governanca.md`) |
| Código | [`../packages/core-ts/src/revisao/`](../packages/core-ts/src/revisao/index.ts) e a revisão [`../db/migrations/versions/0048_fila_de_revisao.py`](../db/migrations/versions/0048_fila_de_revisao.py) |
| Nomes | Dicionário §3.60 |
| Estado | **Proposta.** O serviço, as tabelas e as portas existem e estão medidos; **a consola HTTP não existe**, porque a identidade da equipa com MFA não existe (ver §4). Nenhum procedimento desta página foi ensaiado por um revisor |

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

- **A consola HTTP e a identidade da equipa.** O serviço expõe tudo o que a consola precisa
  (`listar`, `ver`, `revelar`, `urlDoDocumento`, `decidir`, `abrirRecurso`, `decidirRecurso`), mas
  não há IdP, contas de staff nem MFA neste repositório, e uma rota `/equipa` sem eles era uma
  porta aberta para os dados de todos os onboardings. Credor: o seguimento nomeado no bloco do
  KAM-089.
- **O texto do SMS e do e-mail ao dono.** A porta `AvisoAoDono` é chamada com o motivo público e a
  via (`sms` ou `email`, nunca o número da loja); o `packages/core-ts/src/sms/` só tem o modelo
  do OTP. Mesmo credor.
- **Os feriados.** A tabela por omissão é **NÃO VERIFICADA** contra a lei em vigor; os móveis
  (Carnaval, Sexta-feira Santa) entram por configuração.
- **Os limiares** — a quota de 20, o risco alto em prioridade ≤ 2, o *score* 60, os 20% e as 8
  semanas da amostragem — são propostas que ninguém calibrou.
- **O *job* da fila.** `drenarTriagem`, `alertarSla`, `amostrar` (sobre cada aprovação
  automática) e `reaplicarEfeitos` (para uma decisão cujo aviso ou screening falhou) existem e
  ninguém os chama. Credor: KAM-196.
- **A quota entre processos.** As aberturas da mesma origem correm em série **num** processo;
  entre processos a quota pode exceder-se pelo número deles.
- **Uma origem partilhada.** Num prefixo de IP móvel partilhado por muitos (CGNAT), a quota é de
  todos, e a triagem drena por ordem de chegada: um atacante constante atrasa os legítimos do
  mesmo prefixo. **PLAUSÍVEL**, por medir: o tamanho real dos prefixos das operadoras.

---

## Controlo de versões

| Versão | Data | Alteração | Autor |
|---|---|---|---|
| 1.0 | Novembro 2026 | **KAM-089**: criação — o que a fila é, o *runbook* do revisor, a linha da RACI e o que fica por fazer. | Equipa KAMBÁ |
