# CHR — ChannelResolver: onde o `tenant_id` nasce

| Campo | Valor |
|---|---|
| Documento | `docs/chr.md` |
| Ticket | KAM-014 — CHR: ChannelResolver por `phone_number_id` com BSUID |
| Estado | Revisão `0009` e módulo `@kamba/core-ts/chr` entregues; ligados ao braço `chr` do `services/worker-canal/src/entrada.ts`. **Os dois destinos do CHR são costuras**: o AGR é KAM-025 e o dono/HND é KAM-018/KAM-019 |
| Âmbito | A resolução de canal e a sua *cache*, a guarda do Fluxo B, a matriz de estados aplicada, a resolução de contacto, a tabela `conversations` e o contrato do *job* do AGR. Transições de modo (KAM-018), espelho no Chatwoot (KAM-019), envio (KAM-015), consentimento (KAM-022) e subscrição de campos (KAM-016) são de outros tickets |
| Fontes | ADR-001, ADR-002, ADR-010, ADR-011, ADR-012, ADR-015; `specs/02` §3.13 (emenda 1.20); `docs/tecnica/01` §6.3, §7, §10.2; `docs/tecnica/08` §3.1 e §3.3; `docs/tecnica/evidencia/E1` §3, §4 e §5 |

| Aprovação | Nome | Data |
|---|---|---|
| Engenheiro de Canais | | |
| Arquitecto de Plataforma | | |

Tudo o que aqui é forma — nomes de coluna, a ordem dos passos, a precedência de
estados, os tectos — é ***proposta*** até ser ratificado. O que é leitura da lei
leva **(a confirmar por parecer)**.

---

## 1. O que isto garante, e o que não garante

O ADR-002 e o ADR-012 mandam: todo o efeito de negócio atravessa a ToolLayer com
o `tenant_id` **do estado**. O CHR é o único sítio onde esse `tenant_id` nasce
(`docs/tecnica/01` §7.2), e por isso é também o único sítio onde se pode
enganar.

**Garante**, e prova contra um PostgreSQL real em `db/tests_chr/`:

- o `phone_number_id` de um tenant **nunca** devolve o contexto de outro — e a
  propriedade não é do código: vem da `tenant_channels_phone_number_id_uq`
  (revisão `0001`), que torna a chave única em toda a plataforma. Não há duas
  linhas onde escolher;
- `kamba_app` **não consegue** responder à pergunta. Sem contexto de tenant, a
  política `tenant_iso` dá-lhe zero linhas — e o CHR leria isso como «canal
  desconhecido». É o que torna o `kamba_resolver` necessário e não conveniente;
- nenhum passo depois da resolução recebe um `tenant_id` de fora: todos o tiram
  do `ChannelContext`;
- uma conversa de um tenant não se lê com o contexto de outro (RLS `FORCE`,
  política `tenant_iso`, revisão `0009`);
- o *job* que vai ao AGR não leva telefone, BSUID nem `display_name` — e não
  leva porque **os argumentos não têm por onde os passar**, não porque alguém se
  lembrou;
- a guarda do ADR-011 recusa o arranque com uma linha de Fluxo B, e **recusa-se
  a correr** com um papel que não prove que vê todas as linhas;
- a repetição do mesmo `wamid` não cria uma segunda conversa.

**Não garante**, e está dito em vez de escondido:

- **A invalidação por `channel.updated` não existe como consumidor.** O que
  existe é a porta (`invalidarCanal`), medida em 0,672 ms do pedido à releitura.
  Quem emite o evento é KAM-016/KAM-021 e quem o consome tem de o subscrever;
  até lá vale o TTL de 60 s, que é o que o próprio critério admite.
- **A mensagem estática do estado `suspenso` não é limitada por frequência.** A
  matriz diz «pode»; «uma vez por contacto/24 h» é de quem envia (KAM-015), e o
  `ten/estados.ts` já o escreve. O que o CHR devolve é a acção autorizada.
- **A convergência de identidade exige uma mensagem com os dois
  identificadores.** Ver §5: não é limitação da implementação, é o algoritmo do
  `docs/tecnica/01` §6.3.
- **O `wamid` vai no *job*, e o `wamid` leva o número do interlocutor em
  base64** (INDÍCIO, `docs/logs.md` §2.1). Vai porque o critério 6 o exige pelo
  nome. Não vai para *log* nenhum, não é etiqueta de métrica e não é a chave da
  fila — ver §7.
- **Um `echo` não resolve contacto nenhum.** O nome do campo que traz o
  destinatário dentro de `smb_message_echoes` é NÃO VERIFICADO (`E1` §5), e
  inventá-lo era resolver identidade a partir de um campo que ninguém leu.
- **Nada aqui mede latência de produção.** Os números do §8 são de um
  PostgreSQL em `tmpfs`, no mesmo anfitrião. Servem para detectar uma resolução
  que passou a ser de outra ordem de grandeza; a medição que conta é KAM-085.

---

## 2. Os seis passos, e cada um é uma porta

```text
evento `message`/`echo` do KAM-013
  │
  1. resolver o canal          kamba_resolver, sem contexto
  │     └─ desconhecido ──────► quarentena `canal_desconhecido`, 0 jobs, alerta
  2. guarda do Fluxo B         em memória, sobre o que o passo 1 trouxe
  │     └─ recusado ──────────► 0 jobs, alerta (sem quarentena: é a letra)
  3. matriz de estados         tenantGate(estado_tenant, estado_canal, acção)
  │     └─ não registar ──────► nada; nem conversa
  4. resolver o contacto       kamba_identity, com contexto
  │     └─ sem identidade ────► quarentena `mensagem_sem_identidade`
  5. abrir a conversa          kamba_app, com contexto; a janela de 24 h abre
  6. entregar
        ├─ mode = bot ────────► AGR (fila `agr-inbound`)
        └─ qualquer outro, e todo o `echo` ──► dono/HND
```

**Três ligações, três papéis, e nenhuma faz o trabalho de outra.** Dar uma
ligação só — a de `kamba_batch`, que vê tudo — resolvia os três passos, e era
exactamente o que o ADR-015 recusa.

| Passo | Papel | Porque não outro |
|---|---|---|
| 1 e a guarda de arranque | `kamba_resolver` | É a única pergunta que se faz **antes** de haver contexto. `kamba_app` vê zero linhas; `kamba_batch` tem `BYPASSRLS` e os serviços não recebem essas credenciais para arrancar |
| 4 | `kamba_identity` | O único papel de serviço com `SELECT` em `contact_endpoints` e `contact_deks` (KAM-008). É também o papel da transacção da fusão, e por isso o papel do gancho que reaponta conversas |
| 5 | `kamba_app` | Escreve `conversations` sob RLS, dentro de `comTenant`. Não tem `UPDATE (mode)`: as transições são KAM-018 |

**Nada do corpo faz este módulo lançar.** Um canal desconhecido, uma mensagem
sem identidade, um Fluxo B, um estado que recusa: nenhum é erro. O que lança é o
que vier da base — e é assim que o `registo.ts` do KAM-013 distingue «já
tratado» de «repetir»: se o braço `chr` lançar, o `processado_at` não é escrito
e o *job* volta à fila.

---

## 3. A *cache* de 60 s

A chave é o `phone_number_id`, porque é essa a pergunta: o CHR recebe-o do corpo
do webhook e não conhece o `channel_id` antes de resolver. A entrada é o
`ChannelContext` inteiro mais o `tipo` do tenant, que é o que a guarda do
ADR-011 precisa.

Três propriedades, e as três são decisões:

- **Um `phone_number_id` desconhecido não entra.** A chave vem de fora — é um
  corpo assinado —, e guardar negativas era deixar quem consiga assinar corpos
  encher a memória com chaves que nunca resolvem. O custo é uma ida à base por
  mensagem de um canal desconhecido, que é precisamente o caso que o critério 2
  manda alertar.
- **Tem tecto** (`MAXIMO_DE_CANAIS`, 1 000, *proposta*), pela mesma razão do
  `PAYLOAD_MAXIMO` da `0008`: uma *cache* sem tecto é memória ilimitada à custa
  de outrem. A expulsão é FIFO e não LRU — com TTL de 60 s a diferença não se
  mede.
- **Uma falha da base não deixa a entrada expirada a servir de resposta.** A
  entrada sai da *cache* **antes** de se ir à base.

A invalidação por evento entra por `invalidarCanal(channel_id)`, porque é o
`channel_id` que um `channel.updated` traz e não o `phone_number_id`. O índice
inverso é mantido em cada escrita, e só esquece o que tinha guardado: um canal
que este processo nunca resolveu não está em *cache* nenhuma, e a invalidação
devolve `false` — que o consumidor idempotente trata como sucesso.

---

## 4. A matriz de estados, e o que «registar» quer dizer aqui

A matriz é a do `docs/tecnica/01` §7.2 e **já existia**: é o `tenantGate` do
`ten/estados.ts` (KAM-009), com a regra de precedência que esse ticket propôs e
devolveu ao dono do documento (`desligado > encerrado > suspenso > pendente >
restrito > ativo`). O CHR não a reimplementa: pergunta-lhe.

O que é deste ticket é o que se **faz** com cada resposta:

| Regime | `registar_entrada` | `processar_entrada` | O CHR faz |
|---|---|---|---|
| `desligado` | não | não | nada: não abre conversa e não entrega |
| `encerrado` | sim | não | abre a conversa e descarta |
| `suspenso` | sim | não | abre a conversa; devolve `mensagem_estatica` como saída autorizada |
| `pendente` | sim | não | abre a conversa; devolve `mensagem_de_teste` |
| `restrito` | sim | sim | normal — a restrição é de quem envia |
| `ativo` | sim | sim | normal |

> **«Registar» aqui é a conversa, e não o registo de entrada.** A linha de
> `inbound_events` deste evento **já existe** quando o CHR corre: foi escrita
> pelo *worker* do KAM-013, antes de se saber de quem era o
> `phone_number_id` — é a própria razão por que essa tabela não tem
> `tenant_id`. Um canal `desligado` não desfaz essa linha; o que ele nega é
> abrir uma conversa e responder.

A verificação do **modo** é **antes** da matriz, e isso é deliberado: uma
conversa em `humano` não vai ao AGR mesmo num tenant perfeitamente `ativo`
(«o bot nunca interrompe uma conversa em modo dono/humano», §10.2), e um canal
`suspenso` não muda quem tem a palavra.

---

## 5. A identidade do contacto, e o limite do critério 4

O CHR não resolve contactos: chama o `resolveContact` do KAM-008
(`docs/identidade.md` §4), com o BSUID e o telefone que vieram **neste** corpo.
É por isso que o `EventoDeEntrada` do KAM-013 passou a levar um `interlocutor`:
`inbound_events` não guarda identidade nenhuma, e relê-la implicava guardar o
corpo ou voltar a pedi-lo à Meta.

**O critério 4 não se cumpre à letra, e a medição está em `db/tests_chr/`.** A
letra diz «mensagem com apenas `wa_id` e mensagem com apenas BSUID do mesmo
cliente convergem no mesmo `contact_id`». Com o algoritmo do §6.3 isso é
impossível: uma mensagem só com BSUID procura por BSUID, não acha, não tem
telefone por onde procurar — e **cria**. O que se mediu:

| Passo | O que chega | O que acontece |
|---|---|---|
| 1 | só telefone | nasce o contacto P |
| 2 | só BSUID | nasce o contacto A — **nada liga os dois** |
| 3 | os dois | funde no mais antigo (P); `contact.merged` **uma** vez em dez repetições |
| 4 | só telefone, ou só BSUID | devolve P, nos dois sentidos |
| 5 | quem tem o `contact_id` de A | chega a P pela lápide (`merged_into`) |

A convergência existe — acontece na primeira mensagem que traz os dois. A caixa
do critério fica **vazia** com esta razão, e a decisão devolve-se a quem o
escreveu (`docs/dividas-documentais.md`, linha 49).

**A fusão reaponta conversas, e a colisão dobra os tempos.** O gancho
`onContactMerge` corre **dentro** da transacção da fusão, com a ligação e o
contexto do módulo de identidade — fazê-lo por fora quebrava a atomicidade que o
KAM-008 garante («se um gancho falhar, nada fica»; há teste). Quando o contacto
que fica já tem conversa no canal do absorvido, a
`conversations_tenant_contact_channel_uq` recusa juntá-las numa linha: dobram-se
os tempos na que fica (`GREATEST`, que em PostgreSQL ignora os nulos) e a do
absorvido fica pendurada na lápide, que continua a existir. Fica uma linha a
apontar para um contacto que já não é ninguém — e fica dito: não se apaga porque
o dicionário §2 diz «soft delete: estado, nunca `DELETE`», e porque
`kamba_identity` não tem `DELETE` nesta tabela. Quem apaga é o `kamba_batch`, na
retenção (KAM-071).

**O evento `contact.merged` é emitido depois do `COMMIT` da fusão**, por quem
chama — que é o que o KAM-008 fixa. Há uma janela: um `kill -9` entre o `COMMIT`
e a emissão perde o evento. Pagar a atomicidade exigia dar ao `kamba_identity` o
`EXECUTE` do `evt_emitir`, isto é, deixar a identidade emitir qualquer evento.

---

## 6. `platform.conversations`

Revisão `0009` (`db/migrations/versions/0009_conversas.py`). Oito colunas, e
**nenhuma guarda dado pessoal**: o contacto entra por `contact_id`, que é um
UUID aleatório (ADR-010), e não há aqui texto livre nenhum.

| O que | Porque assim |
|---|---|
| `UNIQUE (tenant_id, contact_id, channel_id)` | É a unicidade de negócio **e** o índice que a RLS precisa (`tenant_id` em primeiro lugar). É também o que torna o `ON CONFLICT DO UPDATE` do CHR idempotente |
| Três FK, duas compostas com o `tenant_id` | O padrão que a `0003` fixou: uma conversa não aponta para um contacto nem para um canal de **outro** tenant, e é a base que o recusa. A do canal obrigou a acrescentar `UNIQUE (tenant_id, id)` a `tenant_channels` — sem ela, não havia chave sobre que assentar, e uma conversa de A podia apontar para um canal de B sem que nenhum dos dois gates o visse |
| `conversations_janela_ck` | Os dois tempos da janela andam juntos, e o fim é depois do início. Uma janela sem entrada não existe |
| `mode` com omissão `bot` | O CHR escreve só a omissão, no `INSERT`, e **lê** os quatro. `kamba_app` não tem `UPDATE (mode)`: as transições são KAM-018 |
| A janela de 24 h aqui, e não em `contacts` | Diverge de `docs/tecnica/01` §6.2, e a razão é de desenho: a janela da Meta é por par (número do negócio, número do cliente) (`E1` §4, CONFIRMADO), e uma janela por contacto não distingue dois canais do mesmo tenant. `docs/dividas-documentais.md`, linha 50 |

O `downgrade` não apaga conversas em silêncio: com linhas, exige
`KAMBA_DOWNGRADE_0009_COPIA` com o caminho de um ficheiro, e escreve a tabela
inteira em JSON antes de a deitar. O que se perde a reverter não é um registo de
passagem — é a janela e o **modo** de cada conversa, e uma conversa que estava em
`humano` volta a `bot` no `upgrade` seguinte.

**Um valor novo entrou na revisão `0008` e não na `0009`**, e isso é uma
propriedade do *gate* 3b: ele lê o AST de **cada** revisão isoladamente e
compara cada `CHECK` fechado com o domínio do dicionário. Alargar
`unrouted_events.motivo` numa `0009` deixava a `0008` vermelha por lhe faltarem
valores — medido. O custo está declarado no DoD do ticket: uma base que já esteja
na `0008` não ganha os dois motivos novos sem voltar a aplicar as migrações. Não
há nada em produção, e o *gate* 8 aplica sempre de `base`.

---

## 7. O *job* do AGR

Contrato `packages/contracts/schemas/agent_invocation.v1.json`, nove campos,
`additionalProperties: false`. O que ele garante é tanto o que está lá como o
que **não** está: sem telefone, sem BSUID, sem `display_name`.

O caminho **não** é o do critério 6, que escreve
`packages/contracts/agent_invocation.schema.json`, e as duas razões estão
medidas: os esquemas deste pacote vivem em `schemas/` com a versão no nome
(`specs/01` §5), e um ficheiro `*.schema.json` bate numa sentinela do *gate* 3b
que o exige dentro de `contratos/eventos/` — e isto não é um contrato de evento.
A caixa fica **vazia** (`docs/dividas-documentais.md`, linha 48).

**O `jobId` é um resumo de `{tenant_id}:{wamid}`, e não o `wamid`.** O `wamid`
leva o número do interlocutor codificado em base64 (INDÍCIO, `docs/logs.md`
§2.1), e uma chave de *job* é lida por quem opera a fila, aparece em painéis e
numa listagem de Redis. O `tenant_id` entra no resumo para que dois tenants não
possam adivinhar a chave um do outro. A janela da deduplicação é
`removeOnComplete` (10 000, *proposta*) e não um prazo: a dedup **que conta** é a
da base, já escrita antes do CHR correr.

---

## 8. O que se mediu

Contra o PostgreSQL 18.6 descartável do *gate* 8, em `tmpfs`
(`db/gate_bd.py --suite tests_chr`):

| Medida | Limiar (critério 8, *proposta*) | Medido |
|---|---|---|
| p95 de `resolve` **sem** *cache*, 40 execuções | ≤ 50 ms | **0,626 ms** |
| p95 de `resolve` **com** *cache*, 40 execuções | ≤ 5 ms | **0,0106 ms** |
| `invalidarCanal` + releitura | ≤ 1 s (critério 1) | **0,672 ms** |

**O que estes números valem:** um PostgreSQL no mesmo anfitrião, em `tmpfs`, sem
tráfego concorrente. Servem para detectar uma resolução que passou a ser de outra
ordem de grandeza — uma consulta que deixou de usar o índice, uma *cache* que
deixou de acertar. Não servem para orçamentar latências de produção, que é
KAM-085. É a mesma ressalva que o `docs/isolamento.md` §5 escreve para o custo da
política, e pela mesma razão.

---

## 9. As métricas

| Nome | Tipo | O que diz |
|---|---|---|
| `chr_resolve_total{desfecho}` | counter | O desfecho de cada evento. Cinco valores, lista fechada |
| `chr_unrouted_total{motivo}` | counter | As linhas de quarentena que o CHR escreve. Dois valores |
| `chr_resolve_ms` | gauge | A duração da **última** resolução. Não é percentil |
| `chr_cache_hit_ratio` | gauge | Acertos sobre resoluções, entre 0 e 1. `-1` quando ainda não houve nenhuma |

São **quatro** e o DoD nomeia três. A quarta é `chr_resolve_total`, e é o único
sítio onde duas recusas ficam visíveis: a do Fluxo B (o critério 5 pede alerta e
não quarentena) e a da matriz de estados. Recusar sem contar é recusar em
silêncio — a mesma razão do `gwy_shed_total` da emenda 1.19.

Nenhuma leva `tenant_id`, `phone_number_id`, `channel_id` nem `event_key`
(`docs/seguranca/ameacas_stride.md`, OBS-I). É também por isso que
`chr_resolve_ms` não é por tenant: seria cardinalidade sem tecto e, pior, um
painel que diz com quem a plataforma fala.

---

## 10. O que fica por decidir

Quatro decisões que este ticket tomou para poder avançar e que **não são dele**.
Estão implementadas como *proposta*; inverter qualquer uma é uma revisão nova.

1. **O `persona` sai do `ChannelContext`.** O `docs/tecnica/01` §7.2 põe-no lá e
   o dicionário §3.2 diz que vem de `contacts.papel` — uma coluna que **nenhuma
   revisão criou**. Os oito campos do critério 1 não a incluem. Quem decide onde
   vive o papel de um contacto é o ticket que criar a coluna
   (`docs/dividas-documentais.md`, linha 47).
2. **A recusa do Fluxo B não deixa linha de quarentena.** O critério 5 pede «0
   *jobs*, alerta», e um valor de domínio que nenhum caminho escreve é peso
   morto. O alerta é a métrica e a linha de registo. Quem quiser rastreio
   persistente de cada recusa pede um motivo novo.
3. **Um `echo` vai ao dono sem contacto nem conversa.** Resolver identidade a
   partir de um campo NÃO VERIFICADO era inventar. Fixar o campo é KAM-017; o
   que o dono recebe é KAM-019.
4. **A mensagem estática do `suspenso` não é limitada aqui.** A coluna que
   contaria «uma vez por contacto/24 h» não existe no DDL do ticket, e quem
   envia é KAM-015. O CHR devolve a acção autorizada.

---

## 11. Controlo de versões

| Versão | Data | Descrição | Autor |
|---|---|---|---|
| 1.0 | Outubro 2026 | Emissão inicial (KAM-014): os seis passos, os três papéis, a *cache* de 60 s, a matriz aplicada, `platform.conversations` (revisão `0009`), o contrato `agent_invocation`, as quatro métricas, os números medidos e as quatro decisões devolvidas. | Equipa KAMBÁ |
