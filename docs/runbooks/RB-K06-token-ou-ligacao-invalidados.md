# Runbook RB-K06 — Token invalidado, ou a conta desligou-se

| Campo | Valor |
|---|---|
| ID | **RB-K06** |
| Versão | 1.0 |
| Cenário | Chega um `account_update` com `PARTNER_REMOVED` (`PRIMARY_INACTIVITY`, `ACCOUNT_DISCONNECTED`, `CHANGE_NUMBER`…), ou uma chamada à Graph API falha por token inválido |
| Severidade | **P2** |
| Alertas que o activam | **Nenhum, hoje.** A regra do §9.2 está por escrever: `channel_disconnected_total{motivo}` existe (`packages/core-ts/src/coexistencia/metricas.ts`) e nenhum serviço importa o módulo `coexistencia`. Credor: o ticket que ligar o módulo (`ops/metricas/catalogo.yaml`, `regras_por_escrever`) |
| Gatilho manual | A PME diz que o bot deixou de responder ou que mudou de telemóvel/número; a consulta do §2; aviso da Meta |
| Nível de degradação | **N3** para esse *tenant* — o canal não envia; o resto da plataforma não é afectado |
| Dono | Ops/Trust & Safety |
| Última revisão | 2026-11-09 (KAM-083) |
| Último ensaio | **Nunca.** Mesa-redonda, roteiro em [`folha-de-ensaio.md`](folha-de-ensaio.md) §3.3. Credor: o fundador |
| Linha canónica | [`../tecnica/09_Topologia_Operacao_Escala.md`](../tecnica/09_Topologia_Operacao_Escala.md) §13, linha RB-K06; [`../tecnica/01_Canais_WhatsApp_Fluxo_Dual.md`](../tecnica/01_Canais_WhatsApp_Fluxo_Dual.md) §10.5 (estados do canal) |
| Estado | **Proposta**, não ensaiada |

---

## 0. Antes de começar

- **Nada trata o `account_update` em produção.** O tratador
  (`Coexistente.tratarAccountUpdate`, `packages/core-ts/src/coexistencia/`) existe e não
  está ligado; e hoje nenhum consumidor lê a `wa-inbound` (KAM-187), pelo que **nem o
  registo em `platform.inbound_events` acontece**. A detecção é, por agora, a PME a dizer.
- **O token inválido não tem tratamento específico** (procurado: nenhum tratamento de
  `OAuthException` ou do código 190 da Graph API). Uma chamada com token inválido falharia
  como envio falhado genérico.
- **Não há transição automática do *tenant* para `suspenso`** — é o comando do
  [RB-K04](RB-K04-quality-rating-vermelho.md) §3, passo 5, por decisão registada.
- **O aviso automático ao dono por e-mail** (`avisos`, gatilho `canal_desligado`, KAM-115)
  existe e não está ligado; o fornecedor de e-mail está `pendente` no inventário de
  subprocessadores.

## 1. Cenário e gatilho

O que o módulo `coexistencia` faz quando ligado, e por isso o que este runbook assume:

| Motivo do `PARTNER_REMOVED` | Canal passa a | Quer dizer |
|---|---|---|
| `PRIMARY_INACTIVITY` | `desligado` | o telemóvel principal da PME esteve ~14 dias sem a aplicação aberta |
| `COMPANION_INACTIVITY` | `desligado` | um dispositivo associado ~30 dias inactivo |
| `CHANGE_NUMBER`, `USER_RE_REGISTERED` | `desligado` | a PME mudou ou registou de novo o número |
| `ACCOUNT_DISCONNECTED`, `BUSINESS_DOWNGRADE` | `desligado` | a PME desligou a ligação, ou a conta perdeu capacidade |
| outro valor | **nada muda** | um motivo desconhecido não desliga — regista-se e revê-se à mão |

Só desliga canais em `pendente`, `ativo` ou `restrito`; um canal já `suspenso` ou
`encerrado` fica como está.

**O passo que não se pode esquecer:** o aviso ao dono vai por **canal alternativo**. O
canal que falhou é o WhatsApp, e mandar por WhatsApp o aviso de que o WhatsApp caiu é uma
mensagem que nunca chega.

## 2. Diagnóstico

```bash
# Estado do canal e da coexistência do tenant
docker exec kamba-prod-postgres-1 \
  sh -c 'psql -U "$POSTGRES_USER" -d "$POSTGRES_DB" -c "
    SELECT c.phone_number_id, c.estado, c.last_account_update_at,
           x.motivo_desligamento, x.desligado_em, x.estado AS sincronizacao, x.passos_feitos, x.prazo_em
      FROM platform.tenant_channels c
      LEFT JOIN platform.channel_coexistence x ON x.channel_id = c.id
     WHERE c.tenant_id = '\''<tenant_id>'\''"'
```

```bash
# Os account_update recebidos nos últimos 7 dias (todos os tenants)
docker exec kamba-prod-postgres-1 \
  sh -c 'psql -U "$POSTGRES_USER" -d "$POSTGRES_DB" -c "
    SELECT kind, waba_id, phone_number_id, recebido_at, processado_at
      FROM platform.inbound_events
     WHERE kind = '\''account_update'\'' AND recebido_at > now() - interval '\''7 days'\''
     ORDER BY recebido_at DESC LIMIT 20"'
```
As duas `verificado` contra uma base com as migrações até à 0039, a 2026-11-09
([`../evidencia/KAM-083.md`](../evidencia/KAM-083.md) §2); `não verificado` contra
produção. O utilizador do contentor atravessa a RLS: só leitura. `processado_at` vazio
quer dizer que o evento foi registado e ninguém o tratou.

**Com a PME:** desligou de propósito? mudou de telemóvel ou de número? a aplicação
WhatsApp Business no telemóvel principal está instalada e aberta?

## 3. Mitigação

1. **Avisar o dono pelo canal alternativo** (§6) — por e-mail, enviado à mão a partir do
   canal operacional até o envio automático estar ligado.
2. **Reconexão:** a PME refaz a ligação pelo fluxo de *onboarding* (Embedded Signup), com
   o apoio de Ops/T&S. O token novo entra pelo fluxo; **não se copia token nenhum à mão**
   (o `meta_client_token` é por *tenant* e cifrado pela `kek_token_cliente`).
3. **Re-sincronização do histórico em coexistência: passo único, com prazo de 24 h** a
   contar do *onboarding* (CONFIRMADO, §7). Se se perder, o cliente tem de ser
   desligado e refazer o fluxo. Confirmar na consulta do §2 (`passos_feitos`, `prazo_em`).
4. **Suspender até repor**, como o doc 09 §13 manda: confirmada a desligação, *tenant* →
   `suspenso` pelo comando do [RB-K04](RB-K04-quality-rating-vermelho.md) §3, passo 5,
   por decisão do Responsável de Produto, registada; **repor** `ativo` quando a ligação
   voltar (§4). A suspensão não apaga nada: impede que outros caminhos do *tenant* actuem
   sobre um canal que não envia.
5. **Se a PME diz que não desligou nada:** pode ser acesso indevido à conta dela — abrir o
   [RB-K10](RB-K10-incidente-de-seguranca.md).

## 4. Critério de recuperação

- o canal volta a `ativo` na consulta do §2;
- a coexistência fica em `sincronizado` ou `sincronizado_sem_historico`, com
  `concluido_em` preenchido;
- se houve suspensão, o *tenant* volta a `ativo` por decisão registada;
- a PME confirma uma mensagem de teste recebida e respondida.

## 5. Escalamento

Ops/T&S → Plataforma/SRE (se a reconexão falhar) → Responsável de Produto (suspensão).
De fora: *Direct Support* da Meta, pelo Business Manager (o *Tech Provider* tem-no,
CONFIRMADO, `E1`).

## 6. Comunicação

**À PME — proposta, por aprovar pelo Responsável de Produto.** Por **e-mail**, nunca por
WhatsApp.

> **Assunto:** KAMBÁ — o seu WhatsApp desligou-se da KAMBÁ
>
> Caro parceiro,
>
> Desde as {hora} (hora de Luanda) o seu número de WhatsApp deixou de estar ligado à
> KAMBÁ. {Motivo, em linguagem simples: o telemóvel principal ficou vários dias sem
> abrir o WhatsApp Business | o número foi mudado | a ligação foi desligada na conta.}
>
> Enquanto não voltar a ligar, o assistente da KAMBÁ não consegue responder aos seus
> clientes. Os clientes que lhe escreverem continuam a conseguir falar consigo pelo
> telemóvel.
>
> Para voltar a ligar, {entre na KAMBÁ e siga o passo "Ligar WhatsApp" | responda a
> este e-mail e marcamos uma chamada}. Se não reconhece esta alteração, avise-nos de
> imediato.
>
> Equipa KAMBÁ

## 7. Factos de terceiros

| Facto | Estado | Fonte |
|---|---|---|
| `PARTNER_REMOVED` com `PRIMARY_INACTIVITY` (~14 dias), `COMPANION_INACTIVITY` (~30 dias), `BUSINESS_DOWNGRADE`, `CHANGE_NUMBER`, `USER_RE_REGISTERED`, `ACCOUNT_DISCONNECTED` | **CONFIRMADO** | `E1`, linha do desligamento por inactividade |
| A sincronização de contactos e histórico em coexistência tem prazo de 24 h após o *onboarding*, e cada passo só se executa uma vez | **CONFIRMADO** | `E1`, linha do prazo duro |
| O código de erro da Graph API para token inválido | **NÃO VERIFICADO** — não está no `E1` nem tratado no código | — |

---

## Controlo de versões

| Versão | Data | Alteração | Autor |
|---|---|---|---|
| 1.0 | Novembro 2026 | O *stub* do KAM-080 passa a runbook no modelo comum (**KAM-083**): o que o módulo `coexistencia` faz por motivo, as duas consultas à base verificadas, reconexão e re-sincronização com o prazo de 24 h, suspensão como acto humano, e o texto à PME por aprovar | KAM-083 |
