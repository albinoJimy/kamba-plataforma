# A saída de canal — envio, janela de 24 h, templates e custo

> **Dono:** KAM-015 · **Consumidores:** KAM-018, KAM-019, KAM-022, KAM-023,
> KAM-031, KAM-048, KAM-054, KAM-058, KAM-084, KAM-118, KAM-122, KAM-123 ·
> **Versão deste documento:** 1.0

O `ChannelAdapter` de saída é o primeiro código da plataforma que fala para
fora. O que ele tem de resolver não é enviar — é **saber se pode**, porque o
WhatsApp não deixa escrever a um cliente quando se quer.

---

## 1. A regra que manda em tudo: a janela de 24 h

Se o cliente escreveu há menos de 24 horas, a janela está **aberta** e responde-se
livremente. Passadas 24 horas sem mensagem dele, a janela **fecha**: só sai um
**template** previamente aprovado pela Meta, e esse paga-se.

```
cliente escreve ──> janela aberta por 24 h ──> 24 h sem mensagem ──> fechada
                         (reinicia a cada mensagem dele)
```

A janela vive em **`conversations.window_expires_at`**, por `(tenant, contacto,
canal)`. O `docs/tecnica/01` §6.2 punha-a em `contacts`, e a divergência está
registada na emenda 1.20 e na linha 50 de `docs/dividas-documentais.md`: uma
janela **por contacto** não distingue dois canais do mesmo *tenant*, e a janela
da Meta é por par (número do negócio, número do cliente) — CONFIRMADO, `E1` §4.
**Não se reabre.**

A janela **FEP** de 7 dias (anúncios CTWA) **não é deste ticket**: o §3.13 do
dicionário atribuía-a ao KAM-015 e os *Detalhes Técnicos* do próprio KAM-015
atribuem-na a Clusters. Sobre o âmbito de um ticket prevalece o campo do próprio
ticket, e a emenda 1.21 corrigiu a linha do §3.13.

---

## 2. A decisão de envio, pela ordem em que acontece

A ordem não é arbitrária. Cada passo está onde está porque mudá-lo custa uma
mensagem, um envio duplicado ou um dado pessoal.

| # | Passo | Porque é aqui |
|---|---|---|
| 1 | **Forma** — botões ≤ 3, listas ≤ 10 | Critério 7: «falham **antes de qualquer chamada**». Verificar depois era gastar uma mensagem para descobrir o que se sabia antes |
| 2 | **Janela e template** | Uma leitura à base. Com janela fechada e conteúdo livre: `WINDOW_CLOSED` **sem chamada HTTP** |
| 3 | **`PreSendGuard`** (KAM-018) | Só para o bot, e **falha fechada** |
| 4 | **A linha, antes da rede** | É isto que faz a idempotência — ver §3 |
| 5 | **O destinatário** | Por porta. Só agora, porque não vale pedi-lo para um envio que vai ser recusado |
| 6 | **O *token bucket*** | Depois da linha: travar antes fazia o chamador repetir com chave nova e perder a idempotência |
| 7 | **A rede, com *backoff*** | Três **repetições** (quatro chamadas); `130429` e 5xx repetem, `131049` não |

A tabela de decisão é a do `docs/tecnica/01` §8.2:

| Situação | O que sai | Categoria |
|---|---|---|
| Janela **aberta**, resposta ou notificação | mensagem livre ou interactiva | `service` |
| Janela **fechada**, conteúdo livre | **`WINDOW_CLOSED`**, sem chamada | — |
| Janela **fechada**, template `approved` | o template | a do template |
| Template em `marketing` | **recusado** (critério 7) | — |

**Com a janela aberta sai mensagem livre e não template**, e isso é custo: a
`utility` dentro da janela **passou a ser paga** em 2026-10-01 (`E1` §1).
Notificar por template com a janela aberta é pagar 0,004 por nada.

---

## 3. A idempotência é da base, e a linha nasce antes da rede

```sql
INSERT INTO platform.outbound_messages (...) VALUES (...)
     ON CONFLICT (tenant_id, idempotency_key) DO NOTHING
  RETURNING id
```

Um `RETURNING` **vazio** significa «esta chave já passou», e nesse caso **não há
chamada HTTP nenhuma**. Não há `SELECT` antes do `INSERT`: entre os dois cabe
outro processo, e o critério 2 pede **uma** linha e **uma** chamada, não «quase
sempre uma».

**A unicidade é por *tenant*** — `UNIQUE (tenant_id, idempotency_key)` — e o
`docs/tecnica/01` §8.4 escreve `UNIQUE` sozinho. A divergência é a divergência 2
da emenda 1.21, e a razão é concreta: com unicidade global, duas chaves iguais de
*tenants* diferentes colidem, o segundo envio é deduplicado em silêncio, e o
`INSERT` falha sobre uma linha que o segundo *tenant* **não pode ver**. Um
*tenant* suprime mensagens de outro se adivinhar a chave. É a lição da emenda
1.18, que levou a chave do `usage_ledger` de global a composta.

O **`wamid` fica com unicidade global**, e a assimetria é deliberada: a chave é
nossa e uma colisão entre *tenants* é acidente de nomes; o `wamid` é da Meta e
globalmente único por construção, pelo que uma colisão ali é um defeito que vale
a pena fazer barulho.

---

## 4. Os estados são monótonos, e a base é que o garante

A Meta entrega os `statuses` **sem ordem garantida e com entrega concorrente**
(CONFIRMADO, `E1` §5). Logo a ordem de chegada não é a ordem dos
acontecimentos.

Três regras, e não uma comparação de números:

1. de um estado **terminal** não se sai — nem para outro terminal;
2. para um terminal vai-se de qualquer não-terminal;
3. entre os não-terminais, avança-se pela ordem e nunca para trás.

`failed` e `suppressed_by_human` **não são «depois de `read`»**, são saídas.
Comparar por índice daria «`failed` é depois de `read`», verdade por acidente, e
«`suppressed_by_human` é depois de `failed`», que não é verdade nenhuma.

A monotonia é imposta **pela base**, no predicado do `UPDATE`:

```sql
UPDATE platform.outbound_messages SET state = $3, ...
 WHERE tenant_id = $1 AND wamid = $2 AND state = ANY($4::text[])
```

Dois `statuses` concorrentes da mesma mensagem chegam em **dois processos**, e só
a base os serializa. O que o TypeScript decide é se **houve entrega** — que é o
que decide o custo.

---

## 5. O custo: micro-dólares inteiros, e na entrega

CONFIRMADO (`E1` §1, *Rest of Africa*, efectivas 2026-10-01): `service`,
`utility` e `authentication` a **4 000** micro-dólares; `marketing` a **22 500**.
Isto é, 0,004 e 0,0225 USD.

**A unidade é inteira porque o §2 do dicionário proíbe vírgula flutuante em
dinheiro**, e aqui não é formalidade: somar `0.004` mil vezes em `float64` **não
dá `4.00`**. Num acumulador de custo isso é deriva que ninguém reconcilia contra
uma factura. O centavo não serve — 0,004 USD são 0,4 centavos —, logo a unidade é
o micro-dólar (1e-6 USD). Divide-se por um milhão **uma vez**, no fim, para
apresentar.

O defeito foi apanhado pelo `tools/kamba_yaml.py`, que só converte inteiros e
recusou a primeira versão de `config/meta_rates.yaml`. Apanhou-o no sítio certo.

### A entrega conta-se ao **atravessar** o `delivered`

A cobrança é por mensagem **entregue** (CONFIRMADO, `E1` §1). Mas o `read` pode
chegar antes do `delivered`:

| Transição | Conta? | Porquê |
|---|---|---|
| `sent` → `delivered` | sim | a entrega |
| `sent` → `read` | **sim** | atravessa o `delivered` — ler implica ter sido entregue |
| `delivered` → `read` | **não** | é a mesma mensagem entregue |
| `read` → `delivered` | não | não avança |
| qualquer → `failed` | não | o contrário de uma entrega |

Com um `=== "delivered"` em vez do atravessamento, uma mensagem cujo `read`
chegasse primeiro **nunca somava custo**.

### O *free tier*

Grátis até 1.000 *service messages* por número e por mês. **Só `service`** — uma
`utility` dentro da janela é paga. Quem mantém o contador é o **KAM-023**; o
adapter recebe o estado por porta, e **sem saber conta**, que é a leitura
conservadora: subestimar o custo é pior do que sobrestimar.

### Porque é que a métrica não tem etiqueta de *tenant*

O DoD pede `meta_cost_usd_total{tenant}`. **Não é implementável, e a caixa fica
vazia:**

- as quatro bibliotecas de métricas deste repositório recusam **por gramática**
  uma etiqueta que não case `^[a-z][a-z0-9_]{1,62}$`, e um `tenant_id` é um UUID
  com hífenes. **A chamada levanta** — não é um aviso, é um erro;
- a razão é o `OBS-I` («identificadores em etiquetas explodem a cardinalidade e
  re-identificam») e o X-11 do gate 6, que varre registos por identificadores:
  uma etiqueta é tão legível como uma linha de registo;
- o `docs/tecnica/01` §16 já aponta o caminho certo — «custo monitorizado por
  *tenant* e por mensagem | mecanismo: `pricing` dos *status*».

O custo por *tenant* sai do `SQL_CUSTO_DO_TENANT`, por consulta, e não
re-identifica ninguém.

---

### O custo sai do estado que a base substituiu

**Quem decide o custo é a transição que de facto aconteceu, e só a base a sabe.**
O `SQL_AVANCAR_ESTADO` devolve `antes.state AS estado_antes`, lido sob
`FOR UPDATE`, e é dele que o `ingerir` calcula a entrega — nunca de uma leitura
feita antes do `UPDATE`.

A primeira versão calculava-o da leitura prévia, e duplicava dinheiro. Com
`delivered` e `read` a chegarem juntos em dois processos — que é o que a Meta
produz, porque não garante ordem nos `statuses` (`E1` §5) —, os dois liam `sent`,
os dois concluíam «houve entrega» e os dois somavam 4 000. O guarda «zero linhas»
não os apanhava: ambos os `UPDATE` casavam, porque `delivered` aceita sair de
`sent` e `read` aceita sair de `sent` **e** de `delivered`. Oito mil
micro-dólares para uma mensagem entregue uma vez, com o `SQL_CUSTO_DO_TENANT` a
dizer quatro mil.

E **não há recurso** a essa leitura prévia quando o `estado_antes` falta: em
série as duas fontes concordam sempre, e um recurso fazia o código passar os
testes sequenciais sem nunca usar a palavra da base. Era assim que o defeito
voltava a ficar invisível.

Um `statuses` cujo `wamid` não existe na tabela **faz barulho** em vez de
desaparecer. O caso real não é um `wamid` inventado: é a nossa própria escrita
do `wamid` ainda não ter comprometido quando o *webhook* chega noutro processo.
Em silêncio, a linha ficava em `sent` para sempre e o custo nunca era contado.

---

## 6. Débito: dois tectos, e nascem diferentes

| Tecto | Valor | Estado |
|---|---|---|
| Por `phone_number_id` | 15 mps | *proposta*, com folga sobre os **20 mps CONFIRMADOS** em coexistência |
| Por `(tenant, contacto)` | 1 mps e 30/min | *proposta* e **a calibrar**: o *pair rate limit* real é **NÃO VERIFICADO** |

**O balde do canal nasce vazio; o do par nasce cheio.** A assimetria é uma
correcção medida, e é o que cada um protege que a decide.

O do **canal** protege o débito da Meta, que conta numa janela deslizante. Com
ele a nascer cheio saem 15 mensagens em `t=0`, a primeira ficha nova chega a
`t=67ms`, e a janela que termina em 67 ms vê **dezasseis** — o critério 5 diz
«nunca excedem 15/s em **nenhuma** janela de 1 s». E a aritmética do próprio
critério confirma a leitura: «drenam em ≥ 6,6 s» são 100/15 = 6,67 s, que só se
obtém com o balde vazio (com ele cheio seriam 85/15 = 5,67 s). O custo é real e
fica dito: o primeiro envio de cada canal espera 67 ms.

O do **par** protege uma pessoa de uma rajada, e a primeira mensagem a alguém
não é rajada nenhuma. Com capacidade 1 e vazio à partida, **toda** a primeira
mensagem a cada contacto esperava um segundo — medido: 100 s para 100 contactos
diferentes, num caso que devia dar 6,7 s.

**O mapa por par tem tecto**: dez mil, com despejo do mais antigo a entrar, que
é o mesmo número e a mesma política da *cache* do CHR. Sem ele, um processo de
longa duração acumulava um balde **e** uma janela por cada par que já vira, e o
`esquecer` que existia para isso nunca era chamado em produção — uma limitação
declarada que nada impunha é um vazamento com documentação. Um par despejado
volta a nascer cheio, que é o que um contacto que não fala há muito merece.

**E uma espera acima de 5 s é recusada, não dormida.** O tecto por minuto do par
(30/min) pode pedir até 60 s, e dormir um minuto dentro de uma chamada de envio
prende o chamador, o *job* e a ligação à base por causa de um tecto nosso. Nesse
caso devolve-se `RATE_LIMITED` e marca-se a linha `failed` — o motivo já estava
na lista fechada de dez e **nada o devolvia**. Os 5 s são *proposta*: mais do que
qualquer espera do balde por segundo (67 ms no canal, 1 s no par) e menos do que
a do tecto por minuto.

### `130429`: ramifica pelo `error.code`, nunca pelo estado HTTP

Nenhuma fonte deste repositório dá o estado HTTP do `130429`, e há relato de a
Cloud API devolver `400` com o código no corpo. **Um cliente que ramifique por
`status === 429` passa os testes contra o servidor falso e nunca repete em
produção.** O `GraphFalso` do KAM-024 expõe o estado como parâmetro
precisamente para que o teste possa provar os dois.

O *backoff* é exponencial com *jitter* em `[base/2, base]` — e não `[0, base]`,
porque um atraso que possa ser zero não é atraso e o `130429` voltava no mesmo
instante. O `Retry-After` **manda** quando existe (`01` §16).

**«3 tentativas» são três *repetições*, logo quatro chamadas**, e a leitura não
é de gosto. O critério escreve «`130429` do servidor falso **3× seguida de
200** ... **3 tentativas**»: com três chamadas no total, os três `130429`
esgotam-nas e o `200` nunca chega — a frase contradiz-se. Com três repetições
depois da primeira chamada são quatro, e a sequência encaixa: 429, 429, 429,
200. Entre duas leituras de um critério, a que o torna possível de cumprir é a
pretendida. A primeira versão deste módulo tinha três chamadas, e isso deixava
a caixa por marcar com o código a dizer que estava feita.

**As duas travagens contam-se separadas.** A `outbound_rate_limited_total` leva
a etiqueta `origem`, de dois valores: `bucket` quando foi o nosso balde a travar
e `meta` quando foi um `130429` que o *backoff* repetiu. Somá-las num número só
era perder a única decisão que o contador informa — a primeira diz «o nosso
tecto está apertado, pode subir», a segunda diz «o tecto dela está à frente do
nosso, baixa».

O **`131049`** (limite de frequência por utilizador) **não se repete**: a Meta
não entregou de propósito, e insistir é gastar débito para ser recusado outra
vez.

---

## 7. Privacidade: o destinatário e o que vai aos registos

**Endereça-se por BSUID quando existe**, e por telefone só na falta dele
(critério 9, DoD «Privacidade»). O campo é `recipient` para BSUID e `to` para
telefone.

O destinatário vem por **porta** e não por ligação nova: só `kamba_identity` lê
`contact_endpoints` (dicionário §3.2) e o adapter corre como `kamba_app`. Dar-lhe
uma quarta ligação era alargar o privilégio de quem envia ao de quem decifra.

Nos registos:

| O que | Como vai |
|---|---|
| o `wamid` | **`msg_id: idOpaco(wamid)`** — `m_` + 32 hex do SHA-256 (§3.10). Em claro leva o número do interlocutor em base64 (`docs/logs.md` §2.1) |
| o telefone | **nunca** |
| o `contact_id` | **não vai**: não está na *allowlist* do `logger/politica.ts` |
| o motivo de uma recusa | no **`outcome`**, porque o motivo **é** o desfecho |

A *allowlist* do logger tem nove campos, e recusa por tipo o que não é dela. Foi
ela que apanhou quatro campos inventados na primeira versão deste módulo.

---

## 8. Templates

`PRIMARY KEY (tenant_id, name, lang)`, `pt_PT` como base (a variante `pt_AO`
**não existe como código** — NÃO VERIFICADO).

**O `status` e o `quality` ficam em minúsculas**, contra o `docs/tecnica/01` §8.3,
que os escreve em MAIÚSCULAS porque é o vocabulário da Meta. O §2 do dicionário
manda minúsculas e prevalece: a base é nossa, e a tradução faz-se **na
fronteira** — o mesmo desenho do `wa_type` do §3.12.

A **recategorização para `marketing` bloqueia o uso e alerta** (critério 9). O
`bloqueado_em` escreve-se na **mesma instrução** que a `category` nova: separar
deixava uma janela em que o template está em `marketing` e não está bloqueado, e
é nessa janela que um envio passaria. É idempotente (a Meta reenvia) e preserva o
**primeiro** instante, que é o que se audita.

Quem **submete** templates é o onboarding (**KAM-091**), e por isso `kamba_app`
tem `SELECT` e `UPDATE` nas colunas de ciclo de vida mas **não tem `INSERT`**: um
`INSERT` concedido aqui era a aplicação a poder inventar um template aprovado que
a Meta nunca viu. Quem **consome** os três webhooks de template é o
**KAM-016**/**KAM-021**.

---

## 9. Como correr

```bash
# Os testes unitários (gate 4): decisão, estados, custo, tectos, cliente, adapter
pnpm --filter @kamba/core-ts exec node --test tests/outbound.decisao.test.ts tests/outbound.estados.test.ts tests/outbound.limites.test.ts tests/outbound.adapter.test.ts

# A suite contra PostgreSQL e contra o servidor Graph falso (gate 8)
python db/gate_bd.py --suite tests_outbound
```

A divisão entre as duas não é arbitrária. No gate 4 ficam as **funções puras** —
a matriz de decisão, a monotonia célula a célula, a aritmética do custo, os
tectos: uma base real não acrescenta nada à prova. Na suite de base de dados fica
o que **não se simula**: a idempotência (é da base), a monotonia sob concorrência
real (só a base serializa duas sessões), o isolamento, e a contagem de chamadas
HTTP pelo `GraphFalso`.

O `tests/outbound.adapter.test.ts` é o terceiro caso, e não cabe em nenhum dos
dois: mede a **ordem** dos passos, com a base, a Meta, o relógio, o aleatório e
o `dormir` por porta. É ali que o critério 6 se prova por extenso — contra a
base as respostas vêm do `GraphFalso` e dizem `200`, logo o `130429` nunca
acontece — e é ali que os quatro «**sem** chamada à API» dos critérios 1, 2, 7 e
8 se afirmam com um contador a zero.

---

## 10. O que não está aqui, e tem dono

| O que | Ticket |
|---|---|
| O corpo do `PreSendGuard` e quem tem a palavra (`conversations.mode`) | KAM-018, **entregue**: o corpo está em `packages/core-ts/src/modos/guarda.ts` e corre sob `pg_advisory_xact_lock(hash(tenant_id, contact_id))`, que é a metade do critério 8 deste ticket que ficou por cumprir. Ver [`modos-conversa.md`](modos-conversa.md) §5 |
| O contador do *free tier* e o método de pagamento da PME | KAM-023 |
| Os consumidores dos três webhooks de template | KAM-016 / KAM-021 |
| O aviso ao dono quando uma mensagem expira | KAM-115 |
| A submissão do conjunto padrão de templates por *tenant* | KAM-091 |
| A janela FEP de 7 dias (anúncios CTWA) | Clusters |
| Um evento de barramento de entrega ou falha | nenhum critério o pede; o primeiro ticket a jusante que precise acrescenta-o |

---

## 11. Controlo de versões

| Versão | Data | Alteração |
|---|---|---|
| 1.0 | 2026-10-20 | Criado pelo KAM-015. |
| 1.1 | 2026-10-22 | **KAM-018: o passo 3 passa a ter corpo.** O `PreSendGuard` que este ticket deixou como porta e a falhar fechada tem agora implementação, em `packages/core-ts/src/modos/guarda.ts`, e corre sob `pg_advisory_xact_lock(hash(tenant_id, contact_id))` — a metade do critério 8 que ficou por cumprir («**não há *lock***»). O `Pedido` ganha um campo opcional, o `turnoIniciadoEm`, que é o `turn.started_at` do pseudocódigo do KAM-018: um envio do bot que o não traga é **recusado**. Nada mais deste módulo muda — a ordem dos sete passos é a mesma, e a linha `suppressed_by_human` é escrita pelo guarda e não pelo adapter, porque o guarda é o passo 3 e o `SQL_ENFILEIRAR` é o 4. |
