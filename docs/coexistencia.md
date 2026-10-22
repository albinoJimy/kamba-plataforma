# Coexistência: histórico, sincronização, *echoes* e desligamento (KAM-017)

| Campo | Valor |
|---|---|
| Ticket | KAM-017 |
| Módulo | `packages/core-ts/src/coexistencia/` |
| Revisão | `0018_coexistencia` (descende da `0017`) |
| Depende de | KAM-016 (o Embedded Signup e a `channel_onboarding`), KAM-024 (as *fixtures* assinadas), KAM-013 (a entrada e o `kind`), KAM-014 (o CHR e o `ChannelContext`), KAM-008 (a identidade de contacto), KAM-015 (o `outbound_messages` e o *token bucket*), KAM-018 (o tratador de modos), `ext:KAM-100` (o *spike* de coexistência) |
| Bloqueia | KAM-018 (a detecção do *echo*), KAM-083, KAM-093, KAM-115 |
| Fonte do desenho | [`tecnica/01_Canais_WhatsApp_Fluxo_Dual.md`](tecnica/01_Canais_WhatsApp_Fluxo_Dual.md) §2, §10.1, §10.4, §10.5, §13, [`tecnica/evidencia/E1_Meta_WhatsApp.md`](tecnica/evidencia/E1_Meta_WhatsApp.md) §2, ADR-001, ADR-009, ADR-010, ADR-015 |
| Entregue | A lógica dos **dois** modos, inteira. O que fica por marcar é um valor por omissão. Ver §8 |

## 1. O que o módulo faz

A coexistência é o WhatsApp Business app do dono e a Cloud API **no mesmo
número** (`E1` §2, CONFIRMADO). Este módulo trata o que isso implica do nosso
lado, e são cinco coisas:

1. **Ingere o passado.** Os *webhooks* `history` e `smb_app_state_sync`
   alimentam `contacts` e as contagens, e **nunca** produzem resposta do bot.
2. **Corre a sincronização** com prazo duro de 24 h, passos que correm uma vez
   só, alerta às 12 h e `falhado` + *offboard* às 24 h.
3. **Trata o *echo***: compara o `wamid` com `outbound_messages`, e entrega o
   que é do dono ao tratador de modos do KAM-018.
4. **Trata o desligamento**: os seis motivos de `PARTNER_REMOVED` passam o canal
   a `desligado`, emitem `channel.updated` e contam.
5. **Avisa aos 10 dias** sem actividade do dono, antes de a Meta desligar aos
   ~14.

## 2. As funcionalidades que a PME perde, e é preciso dizer-lhe

É o que o `E1` §2 enumera como CONFIRMADO, e o bloco do ticket manda constar do
aviso de onboarding (o texto é KAM-093):

| O que | O que acontece |
|---|---|
| Grupos | Não suportados e **não sincronizados** |
| Mensagens temporárias | Desligadas nos chats 1:1 |
| *View once* | Desactivado |
| Localização em tempo real | Desactivada |
| Listas de difusão | Desactivadas; as existentes ficam **só de leitura** |
| Chamadas de voz e vídeo | Não suportadas na API |
| Catálogo, pedidos, saudação, ausência, respostas rápidas, etiquetas, perfil, *Channels* | «Não suportados na Cloud API» |
| Dispositivos associados | Ficam **todos desligados** no onboarding; o WhatsApp for Windows e o WearOS não voltam |

E duas que mudam sem se perder: **a Meta dá 20 mps fixos** a um número em
coexistência (nunca os 80 do `cloud_only` nem os 1.000), e a janela de
atendimento só abre quando o cliente escreve **depois** do onboarding — uma
conversa anterior só se responde por template.

**Os 20 mps são o tecto dela, e o nosso é 15.** O `MPS_POR_MODO` tem os dois
modos a 15, que é o que o critério 8 pede e o que o `MPS_POR_CANAL` do KAM-015
já valia — a folga de cinco é escolha nossa, e está escrita no `limites.ts`
desde aquele ticket. Onde este documento disser «20 mps» está a falar do que a
Meta impõe; onde disser «15» está a falar do que nós enviamos.

## 3. O corpo do histórico **não** se guarda, e a forma garante-o

O critério 2 é explícito: «o corpo das mensagens de histórico **não** é
persistido nem indexado no Piloto (apenas contactos e contagens); a base legal
para o usar (a confirmar por parecer, KAM-104) fica como critério de saída antes
de o alargar.»

A forma de garantir isso não é uma regra escrita: é **não haver onde**. A
`channel_coexistence` tem dezoito colunas e **nenhuma é texto livre** — as
quatro de texto são domínios fechados (`estado`, `motivo_desligamento`) ou um
*array* com `CHECK` de conteúdo (`passos_feitos`). O que o histórico deixa são
duas contagens, `contactos_vistos` e `mensagens_vistas`.

A `inbound_events` do KAM-013 também não guarda corpo — não tem coluna para
isso —, pelo que o texto de uma mensagem antiga passa pelo processo e não fica
em sítio nenhum. Há um teste que o afirma pela forma: percorre **todos** os
parâmetros de **todas** as instruções que uma ingestão emite, e exige que
nenhum seja um texto que pudesse ser conteúdo.

**E nada disto vai a um LLM.** É o «fora de âmbito» do bloco e o L15 dos Termos
da Meta §4.7: histórico no RAG é proibido sem base legal, e para treino é
proibido sempre.

## 4. A sincronização: 24 h, dois passos, e um relógio que entra por parâmetro

O `E1` §2 é a fonte: «24 horas após o onboarding para sincronizar contactos e
histórico (cada passo só pode ser executado uma vez); senão o cliente tem de ser
*offboarded* e refazer o fluxo.»

| O quê | Onde vive | Porquê ali |
|---|---|---|
| O prazo das 24 h | `channel_coexistence.prazo_em`, **coluna** | Um prazo derivado de `now()` na consulta não se acelera sem mexer no servidor, e o critério 3 pede «relógio acelerado nos testes» |
| O passo que corre uma vez | `passos_feitos text[]` + `NOT ($n = ANY (...))` no `UPDATE` | O *no-op* é do PostgreSQL e não de um `if`: entre um `SELECT` e um `UPDATE` cabe outro processo |
| O alerta das 12 h | `alertado_em IS NULL` no predicado | Idempotente: uma varredura de cinco em cinco minutos alertava doze vezes por hora |
| A falha das 24 h | `estado = 'falhado'`, e a mesma lista é o *offboard* | Um `falhado` **é** um *offboard* pedido; devolver duas listas sugeria que pode haver um sem o outro |

**Não há agendador**, e isso não é dívida deste ticket: não existe nenhum neste
repositório (nem `repeat:`, nem `delay:`, nem `cron`), e nasce com o
KAM-071/KAM-078. O que existe é o padrão que o `abandonarVencidas` do KAM-016 e
o `pausarPorInactividade` do KAM-018 escreveram — uma função idempotente por
predicado SQL, com o relógio por parâmetro, testável agora e chamável depois.
`varrerPrazos` e `varrerInactividade` são isso.

### O erro 2593109 é um caso normal, e é por isso que tem estado próprio

«Se o cliente não partilhar histórico, chega um *webhook* `history` com erro
2593109» (`E1` §2, CONFIRMADO). O estado é `sincronizado_sem_historico`, que é
**terminal e bem-sucedido**: o cliente escolheu não partilhar, o que é uma
escolha do titular e não uma avaria nossa. Tratá-lo como `falhado` disparava o
*offboard* — isto é, mandava o dono repetir o Embedded Signup — por ele ter
exercido uma escolha que o próprio *popup* da Meta lhe oferece.

**E o número não pode ser registado.** Tem sete dígitos, e a política de *logs*
da casa (`packages/core-ts/src/logger/politica.ts`) recusa mais de **seis** em
qualquer campo de texto — `DIGITOS_MAXIMOS`, a regra que apanha o telefone, o
NIF e o IBAN — nos **dois** campos onde ele caberia: no `outcome`, cuja
gramática são palavras de letras com até três dígitos no fim, e no `error_code`,
cujo `NUMERO` é `[0-9]{1,6}`. Mediu-se contra o espelho Python:
`validar("error_code", "2593109")` devolve `None`, e o `131049` de seis dígitos
do KAM-015 passa.

Consequência: o número vive na coluna `meta_error_code`, que é `integer` por
isto, e o registo leva o `outcome` simbólico `sincronizado_sem_historico`. **Quem
acrescentar outro código da Meta a este módulo tem de o confrontar com a
política primeiro** — os códigos dela têm seis **ou** sete dígitos, e os dois
casos comportam-se de forma diferente.

## 5. O *echo*, e a regra que é segura nos dois lados do L6

Um *echo* (`smb_message_echoes`) é o dono a escrever na app. Mas **não se sabe**
se as mensagens que **nós** enviamos por API também geram *echo*: é o L6, NÃO
VERIFICADO, e o `01` §10.3 di-lo.

A regra do critério 7 resolve os dois casos ao mesmo tempo: compara-se o `wamid`
do *echo* com `outbound_messages`.

* **Está lá** → fomos nós. Ignora-se, e **não se mexe no relógio de
  inactividade**: um bot a responder não prova que o dono abriu a app.
* **Não está** → foi o dono. Move-se o relógio, resolve-se o contacto pela porta
  do KAM-008 e dispara-se `echo_do_dono` no tratador do KAM-018.

Há um **terceiro** desfecho, e ele é honestidade: um *echo* do dono cujo
destinatário não resolve conversa nossa — o caso normal da coexistência, em que
o dono fala com gente que o bot nunca atendeu — **conta-se** como
`sem_conversa` em vez de se descartar em silêncio. É pela série `nosso` desse
contador que o L6 fica mensurável em produção: no dia em que a Meta passar a
gerar *echo* para envios por API, ela começa a subir sozinha.

### O campo do destinatário, que este ticket fixou

O `E1` §5 **não** descreve a forma interna de `smb_message_echoes`. O
`ARRAY_DOS_ECHOES` (`message_echoes`) já estava no canon como ***proposta***, e
o `entrada/explosao.ts` deixava o `interlocutor` de um *echo* a `null` com a
nota «fixar o campo é KAM-017».

Está fixado: `CAMPO_DO_DESTINATARIO = "to"`, no nome que o simulador do KAM-024
já emite, para que os dois lados da proposta digam o mesmo e o dia em que a Meta
a desminta mude **um** sítio. Continua ***proposta*, NÃO VERIFICADO**.

Sem ele, um *echo* não tem contacto, logo não tem conversa, logo a célula
`bot→dono` que o KAM-018 pôs na tabela ficava sem detector para sempre. O risco
de a proposta estar errada é um *echo* que não resolve conversa — e esse caso
conta-se.

**O `bsuid` de um *echo* continua `null`, e não se inventa**: o `from_user_id`
identifica quem *envia*, e quem envia um *echo* é o dono. Um BSUID do dono posto
no lugar do interlocutor fazia o KAM-008 resolver o contacto errado, e só se
descobria no dia em que a conversa do dono consigo próprio aparecesse no painel
de um cliente.

## 6. O desligamento: seis motivos, uma transição

| Motivo (`E1` §2) | O que significa |
|---|---|
| `primary_inactivity` | ~14 dias sem abrir a app |
| `companion_inactivity` | ~30 dias; dispositivo associado removido |
| `business_downgrade` | |
| `change_number` | |
| `user_re_registered` | |
| `account_disconnected` | O cliente desligou em Definições > Conta > Business Platform |

**Os seis vão em minúsculas, e a razão foi medida.** São também `outcome` de uma
linha de registo, e a gramática desse campo só aceita minúsculas — **em modo
estrito, que é o do CI, o `Logger` levanta**, e um desfecho perfeitamente normal
de um *webhook* passava a excepção não tratada. É a mesma classe de defeito que
o `sem_humano_24h` do KAM-018 pagou com um *gate* vermelho. A forma `MAIUSCULA`
da Meta converte-se na fronteira, pelo `MOTIVO_POR_EVENTO_META`, e o `CHECK` da
`0018` recusa-a — o que torna a tradução obrigatória em vez de opcional.

**Repetir o mesmo evento 2× produz 1 transição**, e quem o decide são dois
predicados na mesma transacção: o `desligado_em IS NULL` da coexistência e o
`estado <> 'desligado'` do canal. Se só um mordesse, as duas tabelas discordavam
sobre se o canal está desligado.

Um motivo que não se reconhece **não desliga nada**: desligar por um valor que
não se compreende era deixar a Meta decidir o estado dos nossos canais com uma
cadeia que ninguém leu.

**A API de *deregister* não funciona** neste caso (`E1` §2), pelo que a
reconexão é por Embedded Signup novo — o `falhado → iniciado` do KAM-016, sem
criar canal duplicado (§7).

## 7. A reconexão não duplica, e isso é a unicidade

O critério 9 pede «a reconexão `desligado → iniciado` reutiliza o ES de KAM-016
**sem criar canal duplicado**». Duas coisas o garantem, e nenhuma é um `if`:

1. a `channel_onboarding_tenant_waba_uq` do KAM-016, que faz um `ligar()`
   repetido devolver `novo: false` sem falar com a Meta nem com o cofre;
2. a `channel_coexistence_canal_uq (tenant_id, channel_id)` deste ticket, cujo
   `ON CONFLICT ... DO UPDATE` **repõe** a linha que lá está — passos vazios,
   relógios a nulo, contagens a zero.

Repor e não deixar: uma reconexão é uma sincronização **nova**, e o `E1` §2 é
explícito em que cada passo corre uma vez **por onboarding**. Deixar os
`passos_feitos` da ligação anterior fazia a sincronização nova nascer concluída
sem ter corrido, que é precisamente o modo de falhar que o prazo de 24 h existe
para apanhar.

## 8. O que fica de fora, e porquê

| O quê | Quem | Porquê não aqui |
|---|---|---|
| **O modo predefinido do produto** | `ext:KAM-100` | O relatório **não existe** — não há `docs/evidencia/KAM-100.md` — e a elegibilidade de Angola é **NÃO VERIFICADA** (risco R1). A lógica dos dois modos está cá inteira e é a mesma (`01` §10.1: «a lógica de saída é a mesma, só muda o §10.2»); o que falta é um valor por omissão, e inventá-lo era escolher pelo relatório |
| A sincronização num número +244 real | `ext:KAM-100` | A mesma dependência |
| A entrega do aviso ao dono | **KAM-115** | Este ticket emite o `channel.inactivity_warning` e pára aí; o critério 6 diz que «a entrega ao dono por canal alternativo depende de mecanismo ainda sem ticket» |
| «Sem acesso ao painel», a outra metade da heurística dos 10 dias | **KAM-093** | Não há painel, e inventar um sinal era inventar evidência. Mede-se a metade que existe, que é o *echo* |
| A base legal do uso do histórico | **KAM-104** | É parecer, e o critério 2 põe-no como critério de saída antes de alargar |
| O comando `/bot` | — | O `EventoDeEntrada` do KAM-013 não leva o corpo de uma mensagem, e fazê-lo levar punha texto de conversa no contrato de ingestão (contra o ADR-010) por uma transição que nenhum dos nove critérios deste ticket pede. A célula `dono + comando_bot` do KAM-018 fica sem detector |
| A métrica `echo_latency_ms` | **KAM-100** | Pede ≥ 30 *echoes* reais em *staging*; uma métrica sempre a zero diz que a latência é nula quando o que se passa é que ninguém a mede (a decisão é da emenda 1.29) |
| O débito de 80 mps em `cloud_only` | — | Nenhum documento deste repositório fixa o número, e pô-lo por dedução era arriscar o `130429` que o balde existe para evitar. O `MPS_POR_MODO` tem **os dois a 15**, e o dia em que houver medição sobe-se um |

## 9. Como se liga, e porque é que não se liga neste PR

O módulo entrega-se **construído e não montado**, e isso é o padrão da casa e
não uma lacuna: o `services/worker-canal/src/entrada.ts` tem quatro braços no
`Encaminhador`, e três deles continuam a contar e mais nada. O KAM-021
(`GestaoDeCanal`), o KAM-022 (`ConsentGate`) e o KAM-018 (a `MaquinaDeModos` e o
`PreSendGuard`) deixaram todos o mesmo — o `docs/consentimento.md` §7 escreve a
ordem por extenso —, e montar **um** braço enquanto os outros três ficam por
montar deixava o processo a tratar coexistência e a ignorar qualidade e
consentimento, que é pior do que não montar nenhum.

Quando se montar, a ordem é esta:

| Braço | O que recebe |
|---|---|
| `ingestao` (`history`, `smb_app_state_sync`) | `Coexistente.ingerirHistorico` / `ingerirStateSync`, dentro de um `comTenant` sobre a ligação de `kamba_app` |
| `gestaoDeCanal` (`account_update`) | `Coexistente.tratarAccountUpdate`, depois do `GestaoDeCanal` do KAM-021 — os dois lêem o mesmo `kind` e tratam campos diferentes do `value` |
| `dono` do CHR (o `echo`) | `Coexistente.tratarEcho`, com o `wamid` e o `interlocutor` que a `EntregaDoChr` já lhe passa |
| `transitar` | `MaquinaDeModos.disparar(..., "echo_do_dono")` do KAM-018 |
| `contacto` | `Identidade.resolveContact` do KAM-008, o mesmo que o CHR já liga |
| `conversa` | uma consulta por `(tenant_id, contact_id, channel_id)` em `conversations` — a `UNIQUE` de negócio do KAM-014 |
| `emitirCanalActualizado` e `emitirAviso` | as duas funções de `coexistencia/eventos.ts`, **com as cinco posições da porta `Emitir`** — a primeira versão desta tabela omitia-as, que eram exactamente as que não encaixavam |
| as varreduras | o agendador do KAM-071/KAM-078, quando existir, **com a ligação de `kamba_batch`**: as três são `UPDATE` sem `tenant_id` e só correm com `BYPASSRLS` |

## 10. Como se prova

| O quê | Onde |
|---|---|
| Os domínios, as decisões, os desfechos, as métricas | `tests/coexistencia.test.ts`, contra a `coexistencia.base_falsa.ts` |
| As *fixtures* assinadas do KAM-024 a atravessar a explosão e o tratador | `tests/coexistencia.fixtures.test.ts` |
| O predicado do passo sob concorrência, a unicidade, a reposição, a RLS, os privilégios | `tests_bd/coexistencia.bd.test.ts`, contra o PostgreSQL 18.6 do *gate* 8 |
| O DDL: os dois domínios nos dois sentidos, os `CHECK`, os índices, o `downgrade` | `db/tests/test_coexistencia_schema.py` |
| O isolamento X-03/X-05 | `db/tests_isolamento/`, pela receita de sementes |

A base falsa **impõe o que a base impõe** — o predicado do estado, o do passo
já feito, o do `desligado_em IS NULL` —, e isso é a lição que o KAM-016 escreveu
com o `23505` que ficava verde: «se o teu duplo de base não impõe o que a base
impõe, o que ele mede é o teu código a falar consigo».

## Controlo de versões

| Versão | Data | Alteração | Autor |
|---|---|---|---|
| 1.0 | Outubro 2026 | Emissão inicial (KAM-017): a revisão `0018`, o módulo `src/coexistencia/`, a fixação do campo do destinatário de um *echo*, e o `MPS_POR_MODO`. | Equipa KAMBÁ |
