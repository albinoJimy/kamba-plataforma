# Identidade de contacto — duas camadas

| Campo | Valor |
|---|---|
| Documento | `docs/identidade.md` |
| Ticket | KAM-008 — Identidade de contacto em duas camadas (contacts, endpoints, HMAC rodado, cofre) |
| Estado | Revisão `0003` e módulo `@kamba/core-ts/identity` entregues; **nenhum serviço os usa ainda** (o CHR é do KAM-014) |
| Âmbito | As quatro tabelas de identidade, o papel `kamba_identity`, as chaves e as operações de resolver, fundir, rodar e apagar. Consentimento (KAM-022), direitos do titular (KAM-070), purga (KAM-071) e o *job* de rotação (KAM-072) são de outros tickets |
| Fontes | ADR-010; `specs/02` §3.1 e §3.2 (emenda 1.8); `docs/tecnica/01` §6, `03` §5.3, `06` §7.2 e §7.6, `08` §5 e §7.2; `docs/tecnica/evidencia/E1` §3 e `E3` |

| Aprovação | Nome | Data |
|---|---|---|
| Responsável de Segurança | | |
| Arquitecto de Plataforma | | |

Tudo o que aqui é forma — nomes de coluna, mensagem do HMAC, formato da cifra,
regras de fusão — é ***proposta*** até ser ratificado. O que é leitura da lei
leva **(a confirmar por parecer)**.

---

## 1. O que isto garante, e o que não garante

O ADR-010 manda: nas tabelas de negócio e nos eventos só entra um `contact_id`
aleatório; o BSUID e o telefone vivem cifrados numa tabela à parte; o telefone
nunca é chave.

**Garante**, e prova no gate 8 contra um PostgreSQL real:

- o BSUID e o telefone **nunca vão em claro para a base**: o que sai do processo
  é HMAC e cifra. Com 1 000 contactos canário, o `pg_dump` da base inteira e o
  registo do servidor com `log_statement = 'all'` têm zero ocorrências, em texto
  e em hexadecimal;
- `kamba_app` não lê `contact_endpoints` nem `contact_deks`, e de `contacts` lê
  só seis colunas — nenhuma delas o HMAC do telefone;
- com o contexto de um tenant, o módulo não lê, não funde e não apaga contactos
  de outro; o mesmo cliente em dois tenants é dois contactos **sem um octeto em
  comum** na base;
- depois de `eraseContact`, a cifra que sobreviva numa cópia não se abre com o
  que a base tem, e o mesmo BSUID resolve para um contacto novo;
- em `KAMBA_ENV=prod`, o serviço não arranca com chaves do ambiente do processo.

**Não garante**, e está dito em vez de escondido:

- **Um HMAC não é anonimização.** `bsuid_hmac` e `phone_hmac` continuam dados
  pessoais (`docs/tecnica/08` §7.2): com a chave de pesquisa, o espaço de
  números angolanos enumera-se em minutos, tenant a tenant. A defesa é a chave
  não estar na base, ter versão e rodar.
- **O apagamento não chega sozinho às cópias de segurança.** Ver §8, ponto 1.
- **Quem lê os endpoints não fica registado.** Há um contador, não uma linha de
  auditoria por leitura — o `audit_log` é do KAM-012. Ver §8, ponto 4.
- **O comprimento da cifra revela o comprimento do texto.** Um telefone tem
  entre 8 e 15 algarismos; não se disfarça.
- **Ninguém impede que um telefone seja escrito noutra coluna de texto.** Isso é
  do validador de entrada e do KAM-068, não deste schema.

---

## 2. As quatro tabelas

Revisão `0003` (`db/migrations/versions/0003_identidade_de_contacto.py`).

| Tabela | O que guarda | RLS |
|---|---|---|
| `platform.contacts` | A chave de negócio: `contact_id`, `tenant_id`, `criado_at`; o HMAC do telefone (`phone_hmac`) e a versão da chave (`hmac_kid`); `erased_at`; a lápide de fusão (`merged_into`, `merged_at`) | `tenant_iso` |
| `platform.contact_endpoints` | O cofre. Uma linha por BSUID (`bsuid_hmac`, `hmac_kid`, `bsuid_enc`) e uma por telefone guardado (`phone_enc`, `finalidade`, `expira_at`), cada uma com a sua `dek_id` | `tenant_iso` |
| `platform.contact_deks` | A chave de dados de cada contacto, embrulhada (`wrapped_dek`, `kek_id`); `destroyed_at` | `tenant_iso` |
| `platform.hmac_key_versions` | Metadados das versões da chave de pesquisa: `kid`, `estado` ∈ {`actual`, `anterior`, `retirada`}, `criado_at`. **Nunca o segredo** | Não tem `tenant_id`: é global |

Três escolhas de forma que não vinham de documento nenhum:

- **As FK são compostas com o `tenant_id`.** Um endpoint, uma DEK, a lápide de
  uma fusão e o dono de um tenant só podem apontar para um contacto **do mesmo
  tenant** — a base recusa o contrário, sem depender de o código acertar.
- **`contact_endpoints` tem chave primária** (`id`). No DDL do `docs/tecnica/03`
  §5.3 ficou sem nenhuma (linha 2 do KAM-140).
- **`finalidade` e `expira_at` são obrigatórias no telefone e não no BSUID.** No
  doc 03 aplicavam-se às duas (idem). O BSUID é o que identifica a conversa; o
  seu prazo de retenção é o do contacto, e é do KAM-071.

`tenants.owner_contact_id` passa a ter a FK que o KAM-003 deixou por criar:
composta (o dono é um contacto **do próprio tenant**) e `DEFERRABLE INITIALLY
DEFERRED`, porque o tenant e o seu primeiro contacto nascem na mesma transacção.

O `downgrade` da `0003` não apaga identidade em silêncio: com linhas em qualquer
das quatro tabelas, ou com algum tenant com dono, exige uma cópia lógica
(`KAMBA_DOWNGRADE_0003_COPIA`) — as quatro tabelas e os pares tenant–dono — e
anula os donos, para que o `upgrade` seguinte não encontre órfãos. Ver
`db/migrations/README.md`.

> **Um achado da execução, que vale para qualquer revisão futura.** Com `FORCE
> ROW LEVEL SECURITY`, o `ALTER TABLE … ADD CONSTRAINT … FOREIGN KEY` valida as
> linhas existentes com uma consulta feita pelo dono da tabela — e o dono, sem
> contexto de tenant, vê zero linhas. **A validação passa sem ter olhado para
> nada.** Medido contra o PostgreSQL 18.6: a primeira versão da `0003` aceitava
> um `owner_contact_id` órfão debaixo de uma FK. A revisão tira o `FORCE` a
> `tenants`, acrescenta a FK e repõe-o, na mesma transacção; há um teste e duas
> mutações para isso.

---

## 3. As chaves, e a forma do que se guarda

Nenhuma chave vive na base. O módulo pede-as a uma porta, `KeyProvider`, que tem
uma implementação sobre a porta de segredos do KAM-010 (`SecretsKeyProvider`).

| Chave | Referência no inventário | Forma do valor | Para quê |
|---|---|---|---|
| de pesquisa, por `kid` | `pepper_contact_hmac` (anel) | `<kid>:<base64 de 32 octetos>` | HMAC do BSUID e do telefone |
| KEK | `kek_contact_dek` (anel) | idem | Embrulhar a DEK de cada contacto |
| de época | `sujeito_epoch_key/<YYYYMM>` | `base64` de 32 octetos | `sujeito_ref` |

O `kid` vai **dentro** do valor: o anel `[actual, anterior]` do `SecretProvider`
chega para saber que versões há e qual é cada uma, sem uma segunda tabela que
pudesse divergir do cofre.

**O HMAC de pesquisa.** `HMAC-SHA256(K[kid], "kamba.identity.v1" ␀ tipo ␀ tenant_id ␀ valor)`.
O `docs/tecnica/06` §7.2 escreve só `HMAC(K, bsuid)`; aqui a mensagem leva o tipo
(`bsuid` ou `telefone`) e o tenant. Com o tenant dentro, o mesmo telefone em duas
lojas dá dois HMAC: quem leia a base inteira não liga o cliente de uma ao de
outra. **Consequência a aceitar ou a rejeitar:** deixa de ser possível comparar
HMAC entre tenants — uma lista de bloqueio de telefones comum a várias lojas,
por exemplo, teria de ser desenhada de outra forma.

**Normalização.** O telefone é E.164 sem o `+` (`+244…` e `244…` são o mesmo
número; o `wa_id` da Meta vem sem `+`), só algarismos, com indicativo. O BSUID
fica **tal como a Meta o manda**: nem caixa, nem espaços. Não se exige a forma
`PT.` + alfanuméricos do `E1` §3 — uma mudança de formato pela Meta não pode
tornar-se em mensagens recusadas — só que seja um identificador ASCII sem
espaços.

**A cifra.** AES-256-GCM, IV aleatório de 96 bits; guarda-se
`versão(1) ‖ IV(12) ‖ etiqueta(16) ‖ cifra`. O contexto autenticado é
`"kamba.identity.enc.v1" ␀ campo ␀ tenant_id ␀ dek_id`: uma cifra copiada para
outra coluna, para a linha de outro contacto ou para outro tenant não abre. A
DEK embrulha-se da mesma maneira, com o tenant e o `dek_id` no contexto.

**`sujeito_ref`.** `trunc16(HMAC-SHA256(K_época, contact_id))`, em que `trunc16`
são os primeiros **16 octetos** (o `docs/tecnica/06` §8 declara a coluna
`bytea`). A época é o mês em **UTC**. Uma época sem chave no cofre é uma época
cujo pseudónimo já não se calcula: o módulo dá erro, não inventa uma chave.

### Produção

`Identidade.arrancar` é a única forma de obter o serviço, e recusa:

1. `KAMBA_ENV` em falta ou fora de `dev`/`staging`/`prod` — uma variável
   esquecida não vale como «não é produção»;
2. `KAMBA_ENV` diferente do ambiente para que o provedor está configurado;
3. `KAMBA_ENV=prod` com um provedor de ambiente — o critério 9 do ticket.

**A terceira recusa é pelo que o provedor diz de si.** «De ambiente» é o
`SecretsKeyProvider` cujo provedor de segredos se chama `env`. Um provedor de
segredos que leia do ambiente com outro nome, ou o cofre de imitação dos testes
(`OpenBaoFakeProvider`), arranca em `prod` (reproduzido na revisão). O critério
cumpre-se à letra; não é uma garantia de que as chaves vêm de um cofre.

---

## 4. Resolver

`resolveContact(cliente, { tenantId, bsuid?, telefone?, guardarTelefone? })`, uma
transacção por chamada, com o contexto do tenant. A ordem é a do
`docs/tecnica/01` §6.3:

1. pelo **BSUID** — HMAC sob a versão actual e sob a anterior;
2. pelo **telefone** — idem;
3. nada encontrado: **cria**.

| O BSUID encontra | O telefone encontra | O que acontece | `desfecho` |
|---|---|---|---|
| A | — ou A | Usa A. Se trouxe telefone novo, A fica com ele | `existente` |
| — | P, sem BSUID | P é a mesma pessoa, vista primeiro só pelo número: ganha o endpoint do BSUID | `completado` |
| A | P ≠ A, sem BSUID | **Fundem-se.** Fica o mais antigo; o outro passa a lápide | `fundido` |
| A | P ≠ A, **com outro BSUID** | Duas pessoas: o número mudou de mãos. P perde o telefone, A fica com ele. **Não se fundem** | `existente` |
| — | P, com outro BSUID | Idem: P perde o telefone e nasce um contacto novo | `criado` |
| — | — | Nasce um contacto | `criado` |

**A regra do número que mudou de mãos não está em documento nenhum.** É
*proposta* deste ticket, e é uma das três decisões devolvidas (§8, ponto 10). A
razão: os números de telefone são reatribuídos pelas operadoras, e fundir por
telefone duas pessoas diferentes entregava o histórico de uma à outra.

**O limite dessa regra, que a revisão adversarial apontou.** O `E1` §3 confirma
que o BSUID é único por par **portfólio**–utilizador; **não** confirma que seja
estável no tempo, nem que um tenant tenha sempre um só portfólio. Se um tenant
tiver canais em dois portfólios, ou mudar de portfólio, a mesma pessoa aparece
com dois BSUID e o mesmo número — e esta regra trata-a como duas: ficam dois
contactos, o número salta de um para o outro a cada mensagem, e a cifra do
telefone guardada é apagada em cada salto (reproduzido). O webhook traz também
`parent_user_id` (`docs/tecnica/01` §6.1), que o módulo não recebe. No Piloto
cada PME tem um portfólio; fora dele, esta regra tem de ser revista antes de
ser usada.

**O BSUID e o telefone têm de vir de uma fonte autenticada** — o webhook da
Meta, com a assinatura conferida —, nunca de texto escrito por um utilizador. Um
telefone num pedido **tira-o** a quem o tinha: se fosse o que alguém escreveu
numa conversa, bastava escrever o número de outra pessoa para lho tirar.

**A fusão** é uma transacção: os endpoints e as DEK do absorvido passam para
quem fica, o absorvido fica como **lápide** (`merged_into`) para que quem ainda
tenha o `contact_id` antigo chegue ao novo, e os ganchos registados com
`onContactMerge` correm lá dentro — se um falhar, nada fica. A operação devolve
o evento `contact.merged` (`tenant_id`, `ocorrido_em`, e no `payload` o
`contact_id` que fica e o `merged_contact_id` absorvido); **quem emite é quem
chama** (KAM-014), e o resto do envelope é dele. `tenants.owner_contact_id` não
é reapontado pelo módulo: a lápide mantém a FK válida, e reapontá-lo é um gancho
de quem gere tenants.

**O telefone guarda-se só quando se pede.** Sem `guardarTelefone`, do número
fica o HMAC — que o reconhece e não o lê. Com `guardarTelefone: { finalidade,
expiraAt }`, fica também `phone_enc`. **Não há prazo por omissão**: as
finalidades (`pagamento_express`, `entrega`, `contacto_pedido`, de
`docs/tecnica/03` §5.3) e os prazos estão por confirmar por parecer. Um por
contacto e por finalidade; guardar outra vez renova. Um contacto que troca de
número perde o HMAC **e a cifra** do antigo.

**Corridas.** Dois pedidos pelo mesmo contacto novo colidem no índice único; o
que perde repete a transacção e encontra o que o outro criou (até 5 tentativas;
com muitos pedidos simultâneos de BSUID diferentes pelo mesmo telefone, algum
pode esgotá-las e devolver o erro da base — o estado fica coerente). Os
contactos envolvidos são trancados por ordem de `contact_id` e relidos depois da
tranca: um contacto apagado ou fundido entre a pesquisa e a tranca faz repetir.

**Uma resolução e uma rotação não se cruzam.** Os índices únicos levam a versão
da chave, pelo que **não** apanham o mesmo BSUID escrito sob duas versões. A
primeira versão do módulo lia as versões vivas sem tranca: um pedido que já
tinha lido «a actual é k1» escrevia sob k1 depois de outro, a seguir à rotação,
ter criado o mesmo contacto sob k2 — dois contactos para o mesmo BSUID, para
sempre, e a rotação desse tenant encravada (achado 1 das duas revisões,
reproduzido). Agora cada resolução segura as versões (`FOR SHARE`) até ao fim da
transacção, e `iniciarRotacao` espera por elas; um pedido que chegue durante a
rotação espera por ela e já escreve sob a versão nova. Há teste para os dois
sentidos e uma mutação.

---

## 5. Rodar a chave de pesquisa

| Passo | Função | Quem |
|---|---|---|
| 1. A chave nova entra no cofre, como `actual` do anel | — | operação |
| 2. Regista-se a versão nova; a que era actual passa a anterior | `iniciarRotacao(kid)` | *job* (KAM-072) |
| 3. Recalculam-se os HMAC, tenant a tenant | `rekeyLookup(tenant, kid)` | *job* |
| 4. Retira-se a anterior | `concluirRotacao()` | *job* |

Durante a janela — do passo 2 ao 4 — a pesquisa tenta as duas versões, e uma
linha encontrada sob a anterior sobe para a actual nessa mesma transacção.

`rekeyLookup` recalcula o HMAC do BSUID **a partir de `bsuid_enc`**: não precisa
da chave antiga. Trabalha por lotes, uma transacção por lote, e selecciona
sempre «o que ainda não está sob `kid`»: é **retomável** (uma interrupção perde,
no máximo, o lote em curso) e **idempotente**. Recusa uma versão que não seja a
actual, e `iniciarRotacao` recusa começar uma rotação com outra por concluir —
deixava linhas sob uma chave que a pesquisa já não tentava.

**O telefone sem cifra.** O HMAC de um telefone só se recalcula se houver
`phone_enc`. Sem ela, fica sob a versão antiga (`telefonesSemCifra: "manter"`, a
omissão): continua a ser encontrado enquanto essa versão for a anterior, e sobe
quando o número voltar a aparecer. Antes de retirar a versão antiga, o *job*
corre com `"largar"`, que apaga os HMAC que sobraram — esses contactos deixam de
ser reconhecidos por esse número.

**O que o módulo não confere, e o que custa errar.** `concluirRotacao` não
verifica que já não há linhas sob a versão antiga: `kamba_identity` não vê mais
do que um tenant de cada vez. É o *job* que percorre os tenants e só depois
conclui. **Concluir com um tenant por rodar não dá erro: estraga.** As linhas
desse tenant ficam sob uma versão que a pesquisa já não tenta; o BSUID seguinte
cria um contacto novo, e o `rekeyLookup` tardio falha por unicidade
(reproduzido na revisão). Não há reparação pelo módulo. É requisito duro do
KAM-072: nenhum tenant com `porRodar` diferente de zero quando se conclui.

**`largar` deixa contactos órfãos.** Um contacto só-telefone, sem cifra, a quem
se larga o HMAC fica sem nada que o encontre: o mesmo número cria outro
contacto. Com rotação anual, é o destino de todo o contacto só-telefone que não
foi revisto durante a janela.

**A chave antiga só sai do cofre depois do passo 4.** Enquanto
`hmac_key_versions` disser que uma versão é a anterior, cada resolução pede-a ao
cofre; se já lá não estiver, **todas as resoluções falham** — fechado, e
ruidoso, mas é uma paragem. A ordem é: concluir, e só depois destruir.

---

## 6. Apagar

`eraseContact(cliente, tenantId, contactId)`, numa transacção:

1. apaga as linhas de `contact_endpoints` do contacto — um `DELETE` verdadeiro;
2. destrói as DEK (`wrapped_dek` passa a nulo, `destroyed_at` é datado);
3. apaga o HMAC do telefone e data `erased_at`.

O `contact_id` fica: as encomendas e o *ledger* referem-no (`docs/tecnica/06`
§7.6). Mas deixa de ser alguém — nada o liga a um BSUID ou a um número — e o
mesmo BSUID resolve para um contacto **novo**. É idempotente, e apagar um
contacto absorvido numa fusão apaga quem o absorveu: o titular é a mesma pessoa.

O ticket pedia «substitui `lookup_hmac` por valor aleatório». Com o HMAC em
`contact_endpoints` (§7), a linha desaparece e não há valor a substituir: o
efeito é o mesmo, pelo caminho mais curto. A caixa desse critério fica por
marcar, com esta razão.

---

## 7. Onde vive o HMAC — a contradição do canon, e como ficou

O bloco do KAM-008 pedia `lookup_hmac`, `hmac_kid` e `UNIQUE (tenant_id,
hmac_kid, lookup_hmac)` **em `contacts`**, e o papel `kamba_identity`. O
dicionário §3.1 punha `bsuid_hmac` **em `contact_endpoints`** e não listava o
papel (linha 3 do KAM-141).

Ficou como o dicionário diz, porque o dicionário prevalece sobre o ticket na
ordem das fontes e foi essa a forma que a emenda D-01 do KAM-111 levou a
`docs/tecnica/`:

| O ticket pedia | Ficou | 
|---|---|
| `contacts.lookup_hmac` | `contact_endpoints.bsuid_hmac` |
| `UNIQUE (tenant_id, hmac_kid, lookup_hmac)` em `contacts` | `UNIQUE (tenant_id, hmac_kid, bsuid_hmac)` em `contact_endpoints` |
| `contacts.hmac_kid` | `contacts.hmac_kid` (do telefone) **e** `contact_endpoints.hmac_kid` (do BSUID) |
| `contacts.phone_hmac` opcional, `erased_at` | iguais |
| papel `kamba_identity` | criado, e acrescentado ao dicionário §3.2 |

A emenda 1.8 do dicionário regista isto como *proposta* e põe `lookup_hmac` na
coluna «Substitui»: o gate 3b passa a recusá-lo. **A decisão é de quem aprova
emendas** (dicionário §5; Carta §6 ponto 4) e fica por ratificar; se for
invertida, é uma revisão nova que move três colunas.

---

## 8. O que fica por decidir

| # | Questão | Estado |
|---|---|---|
| 1 | **O *crypto-shredding* não chega às cópias de segurança.** O `docs/tecnica/06` §7.6 diz que apagar a DEK torna os dados ilegíveis «incluindo nos *backups* e arquivos WAL». Com a DEK embrulhada **na base**, uma cópia anterior ao apagamento tem a cifra **e** a DEK embrulhada, e a KEK continua no cofre: quem tiver a cópia e a KEK lê. Só passa a ser verdade quando a KEK rodar (e a antiga for destruída) ou a cópia expirar | Sem ticket. Decide-se com a retenção das cópias (KAM-071, KAM-079) ou movendo as DEK para o cofre |
| 2 | **Não há `KeyProvider` de cofre para `prod`.** O critério 9 recusa o de ambiente em `prod`. Mas o `docs/adr/ADR-L002` diz que no Piloto o processo lê segredos **do ambiente**, que o lançador do cofre enche — ou seja, em `prod` a porta de segredos é a de ambiente. Os dois não se cumprem ao mesmo tempo: ou o módulo de identidade fala com o cofre directamente (o `DopplerSecretProvider` do KAM-010 serve), ou o critério muda | Contradição entre o ticket e o ADR-L002; devolvida |
| 3 | **Quem cria a chave de cada mês e quem a destrói** ao fim da retenção (12 meses, *proposta*, `docs/tecnica/06` §7.2) | Sem ticket |
| 4 | **Auditoria das leituras do cofre.** O `docs/tecnica/08` §7.2 pede que «o acesso à função HMAC» seja auditado. `lerEndpoints` incrementa um contador em memória e mais nada | KAM-012 (`audit_log`) |
| 5 | **A purga por `expira_at`** tem de apagar, com o endpoint de telefone, o `phone_hmac` do contacto — ou não, e aí o número continua a ser reconhecido depois de a cifra expirar. A coluna existe; nada a lê | KAM-071 |
| 6 | **Os privilégios de `kamba_batch` sobre o cofre.** Hoje nenhum. A purga e a rotação vão precisar de alguns, e dar `BYPASSRLS` sobre BSUID e telefones cifrados de todos os tenants é uma decisão, não um pormenor | KAM-071, KAM-072 |
| 7 | **Só há fusão quando um pedido traz BSUID e telefone.** Um contacto só-BSUID e um só-telefone da mesma pessoa não se ligam enquanto nenhuma mensagem trouxer os dois. O critério do KAM-014 («mensagem com apenas `wa_id` e mensagem com apenas BSUID do mesmo cliente convergem») não se cumpre com o que a Meta manda | KAM-014 |
| 8 | **Chaves em memória.** O `SecretsKeyProvider` pede a chave ao provedor de segredos em cada operação, sem janela de tolerância; com um cofre remoto é uma ida à rede por resolução | Decide-se com o ponto 2 |
| 9 | **A base legal de guardar `phone_hmac` sem finalidade declarada** — fica sempre que um telefone é visto, para reconhecer o contacto | (a confirmar por parecer) |
| 10 | **«Telefone com outro BSUID é outra pessoa».** A regra de não fundir (§4) é *proposta* e assenta numa premissa — um BSUID por pessoa e por tenant, estável — que a evidência não confirma fora de «um tenant, um portfólio» | Devolvida ao fundador; rever antes do Fluxo B (ADR-011) ou de qualquer mudança de portfólio |
| 11 | **Não há reembrulho das DEK quando a KEK roda.** O anel guarda duas versões da KEK; à segunda rotação sem reembrulhar, as DEK embrulhadas com a mais antiga deixam de abrir e os endpoints desses contactos ficam ilegíveis (reproduzido na revisão). O módulo não tem a função, e nenhum ticket a tem | Sem ticket; tem de existir antes da **primeira** rotação da KEK (365 dias, *proposta*) |
| 12 | **`hmac_key_versions` é global e `kamba_identity` escreve nela sem contexto.** Uma instrução (`estado = 'retirada'` na versão actual) pára as resoluções de todos os tenants. É disponibilidade, não fuga | Aceite; a alternativa é um papel próprio para a rotação (KAM-072) |
| 13 | **A cobertura conta todas as linhas físicas.** O LCOV do Node marca comentários e linhas em branco como cobertas: 90% por este método tolera mais código por cobrir do que o número sugere. Hoje `src/identity/` está a 99–100%. O mesmo vale para o gate 4 | Limitação da medição, não deste ticket |
| 14 | **A cópia lógica do `downgrade` junta num ficheiro a cifra e as DEK embrulhadas de todos os tenants**, e sobrevive a apagamentos posteriores: um titular apagado depois do `downgrade` continua na cópia | De quem opera: a cópia tem prazo e destrói-se |

### Divergências de `docs/tecnica/` registadas para correcção

O DDL de referência de `contacts` e `contact_endpoints` passa a ser o da revisão
`0003`. O que os documentos dizem de diferente, além das linhas 2 e 3 do
KAM-140:

| Documento | O que diz | O que ficou |
|---|---|---|
| `01` §6.2 | `contacts` com `username`, `display_name`, `last_inbound_at`, `window_expires_at`; `phone_hmac_kid smallint` | Nenhuma das quatro (a janela é do KAM-014); `hmac_kid text` |
| `01` §6.3 | O algoritmo não prevê um telefone que já pertence a outro BSUID | §4: não funde |
| `03` §5.3 | FK simples `tenants_owner_fk`; `contact_endpoints` sem chave primária e sem `hmac_kid` | FK composta; `id`; `hmac_kid` |
| `06` §7.2 | `bsuid_hmac = HMAC-SHA256(K_lookup[kid], bsuid)` | A mensagem leva o tipo e o tenant (§3) |
| `06` §7.6 | Apagar a DEK torna os dados ilegíveis nos *backups* e WAL | Não, enquanto a DEK embrulhada viver na base (ponto 1) |
| `08` §5 | Não tem linha para a KEK das DEK de contacto nem para as chaves de época | `kek_contact_dek`, `sujeito_epoch_key` no inventário |
| `08` §7.2 | `contact_hmac = HMAC-SHA256(pepper_kid, E.164)` | Idem `06` §7.2 |

---

## 9. Para quem usa o módulo

```ts
import { Identidade, SecretsKeyProvider } from "@kamba/core-ts/identity";

const identidade = await Identidade.arrancar({ chaves: new SecretsKeyProvider({ segredos }) });

// Uma ligação de `kamba_identity` — nunca um pool, nunca `kamba_app`.
const { contactId, evento } = await identidade.resolveContact(cliente, {
  tenantId, bsuid: mensagem.from_user_id, telefone: mensagem.from,
});
if (evento !== null) await emitir(evento);
```

- O que sai para o resto da plataforma é o `contactId`. `lerEndpoints` decifra
  **em memória**, para quem tem de enviar; o resultado não se guarda nem se
  regista. Um telefone cujo `expira_at` já passou não é devolvido, mesmo antes
  de a purga o apagar.
- Um erro da base (`code` 23505, por exemplo) sobe tal como o *driver* o dá, e
  o seu `detail` traz o **HMAC** da linha em hexadecimal. Não é o BSUID nem o
  telefone, mas é dado pseudonimizado: quem o apanhar regista o `code`, não o
  `detail`.
- Os erros do módulo **nunca** levam um BSUID nem um telefone. O módulo não
  regista nada; os contadores (`CONTADORES_DE_IDENTIDADE`) só têm números.
- Um gancho de `onContactMerge` só escreve pela ligação que recebe: a transacção
  pode repetir-se depois de uma corrida.
- A primeira versão da chave regista-se uma vez, com `iniciarRotacao(kid)`.

### Como se prova

| O quê | Onde |
|---|---|
| Schema, restrições, privilégios, `downgrade` | `db/tests/test_identidade_schema.py` (gate 8) |
| Isolamento das três tabelas, com o papel que as lê | `db/tests_isolamento/` (gate 6) |
| O módulo contra a base; canários; cobertura | `db/tests_identidade/` + `packages/core-ts/tests_bd/` (gate 8) |
| Chaves, cifra, `sujeito_ref`, política de repetição | `packages/core-ts/tests/identity.*.test.ts` (gate 4) |
| Que os testes mordem | `db/mutacoes.py`: 62 mutações deste ticket (prefixos `0003:`, `identidade:`, `canarios:` e `bootstrap: kamba_identity`) |

---

## 10. Controlo de versões

| Versão | Data | Alteração | Autor |
|---|---|---|---|
| 1.0 | Outubro 2026 | Emissão (KAM-008): as quatro tabelas, o papel `kamba_identity`, as chaves, resolver, rodar, apagar, e o que fica por decidir. | Equipa KAMBÁ |
