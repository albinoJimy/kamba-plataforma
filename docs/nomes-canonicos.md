# Nomes canónicos — como o gate 3b funciona e como acrescentar uma extensão

| Campo | Valor |
|---|---|
| Ticket | KAM-111 — Dicionário de dados canónico e reconciliação de `docs/tecnica/` |
| Fonte normativa | [`specs/02_Dicionario_de_Dados_Canonico.md`](../specs/02_Dicionario_de_Dados_Canonico.md) §3 (nomes), §5 (manutenção); [`specs/01_Engineering_Standards_e_Handoff.md`](../specs/01_Engineering_Standards_e_Handoff.md) §4, gate 3b |
| Alvo | `make ci-3b` (ou `make canon-lint`) |
| Revisão adversarial | [`ANALISE-05`](analises/ANALISE-05-KAM-111-dicionario-canonico-e-lint.md) |
| Estado | **Proposta.** As regras de exportação, a quarta superfície, o que conta como nome «conhecido» e a regra da `versao` são decisões deste ticket, por ratificar |

> **Não se inventam nomes: o dicionário manda.** Este documento explica o
> mecanismo. Não acrescenta nome nenhum, e nada do que aqui está prevalece sobre
> o dicionário.

---

## 1. O que o gate verifica

O dicionário fixa **um nome por conceito**. O gate 3b falha o *build* quando um
nome fora dele chega a um sítio onde passa a ser contrato.

| Nível | O que é | Como se resolve |
|---|---|---|
| **1 — variante** | um nome da coluna «Substitui» do §3: `valor_kz`, `sig_ok`, `consent_log`, `llm_calls`, `kamba_ops`… | usar o nome canónico. **Não há extensão que a salve** |
| **2 — fora do dicionário** | um nome que o §3 não cobre | emenda ao dicionário, ou entrada em [`canon/extensoes.yaml`](../canon/extensoes.yaml) (§4) |

A mensagem tem sempre a mesma forma, que é a que o critério de aceitação pede:

```text
db/migrations/versions/0002_x.py:14: [variante] `valor_kz` → `valor_minor`, dicionário §3.4
```

### As quatro superfícies

| Superfície | Ficheiros | O que se lê |
|---|---|---|
| migrações | `db/migrations/versions/*.py` | esquemas, tabelas, colunas, valores de `CHECK`, tipos, papéis, unicidades |
| eventos | `contratos/eventos/**/*.schema.json` | nome do ficheiro, `tipo`, `versao`, campos do envelope e do *payload* |
| registo | `registry/*.yaml` | chaves, `id`, módulo, limites, subscrições, *tools* e parâmetros |
| documentos | `docs/tecnica/**/*.md` | **só** as variantes (nível 1) |

**A quarta não está no critério de aceitação**, que enumera três. Existe porque a
parte (a) do mesmo ticket tirou as variantes de `docs/tecnica/`, e sem uma
verificação por máquina a edição seguinte repunha-as — foi exactamente assim que
dez documentos divergiram.

**`eventos` e `registo` estão hoje vazias.** `contratos/eventos/` nasce com o
KAM-007 e os ficheiros do registo com o EPIC-03. O `check` di-lo na saída
(«A SUPERFÍCIE AINDA NÃO EXISTE; nada foi verificado aqui») em vez de as dar por
conformes, e o passo `canario` do gate corre as *fixtures* para provar que as
duas verificações mordem enquanto não houver ficheiros reais (§5).

### O nível 1 vê variantes em qualquer texto

Não só em identificadores. `valor_max_pedido_kz` é uma chave de `limites jsonb`:
numa migração só existe **dentro de uma cadeia** (`'{"valor_max_pedido_kz": 5}'`),
e num *schema* pode estar em `required` sem estar em `properties`. Por isso:

- nas migrações, procura-se em identificadores (com ou sem aspas), **em cadeias**
  e no corpo dos blocos `$$`;
- nos *schemas* e no registo, em **todas as chaves e todos os textos** do
  documento, debaixo de qualquer palavra-chave.

Sempre com fronteira de palavra: `max_preco_kz` não contém `preco_kz`. A
consequência assumida é que um comentário de coluna a dizer «substitui
`consent_log`» falha — um `COMMENT ON` é texto que alguém vai ler como contrato.

### O nível 2 e o que é um nome «conhecido»

O §3 é prosa com nomes entre crases, e nem tudo o que está entre crases é um nome
de dados. Um *token* só é conhecido se for todo em minúsculas, não for uma
palavra de tipo SQL (`boolean`, `uuid`, `jsonb`…), e tiver três ou mais
caracteres ou for ele próprio um *span* inteiro (`id`, `lg`). Quatro tipos têm
**conjunto próprio**: tipos de evento (21), *tools* (1: `enhance_image`), papéis
(3) e esquemas (4).

> **Limite medido, e não resolvido.** Tabelas, colunas, valores, campos e
> parâmetros partilham um conjunto de 219 nomes: o §3 não diz o **tipo** de cada
> um. `estado` é aceite como coluna de qualquer tabela, e um valor de estado é
> aceite como nome de coluna. A revisão adversarial mediu-o com 77 nomes
> plausivelmente errados: **51 (66%) passavam** em qualquer posição. Depois da
> correcção passam **37 (48%) como coluna** e **0 como evento, *tool* ou
> papel**. Fechar o resto pede que o dicionário diga o tipo de cada nome — é a
> linha 9 do KAM-141, e não uma heurística a acrescentar aqui.

### O que o gate **não** vê

Dito por extenso, porque um gate vale o que valer a lista do que lhe escapa:

1. **Semântica.** Que o gatilho do *provisioning* é `tenant.approved` e não
   `tenant.activated` — os dois são nomes canónicos. Que a retenção de
   `assistant_queries` é de 12 meses e não de 13. Das doze divergências do
   ticket, **duas (D-07 e D-09) não têm forma de nome** em nenhuma das
   superfícies, e por isso não têm *fixture* (§5).
2. **O tipo de um nome** (acima).
3. **As colunas de uma vista** (`CREATE VIEW … AS SELECT … AS x`) e os **nomes de
   índices, de restrições e de políticas**. O critério pede «colunas, tabelas e
   valores de `CHECK`».
4. **Unicidades escritas de outra maneira.** A do D-06 é apanhada como
   `UNIQUE (…)`, como restrição e como índice único; `UNIQUE … WHERE true`,
   `(provider, lower(referencia))` e `EXCLUDE USING btree` não.
5. **Um `CHECK` composto que restringe um domínio.** `estado IN ('a','b') AND
   true` é lido como comparação solta, e só se exige que cada valor pertença ao
   domínio. É a mesma leitura que deixa passar as restrições condicionais
   legítimas de `docs/tecnica/04` §6.2.
6. **Um ENUM usado por uma coluna de outra revisão.** A ligação ENUM → coluna
   faz-se dentro do mesmo ficheiro.
7. **`$ref` externos** nos *schemas* de evento, e um *schema* de evento cujo
   ficheiro não acabe em `.schema.json` nem esteja numa pasta `eventos/` ou
   `events/`.
8. **Expressões da coluna «Substitui»** (`p.stock>0`, `msisdn_hash+tenant`) e o
   que ela diz sem crases («replay ±5 min», «persona»). Só um identificador
   entre crases é uma variante.
9. **Formas partidas nos documentos**: `valor\_kz`, `Valor_KZ`, `valor_**kz**`.
   E os nomes que contêm uma variante sem a serem — `max_preco_kz`,
   `alvo_preco_kz`, `receita_paga_kz` existem hoje em `05` e `06`.
10. **Coerência dentro de um ficheiro do registo**: um `id: servicos` com
    `modulo: vendedor` passa. O dicionário não escreve essa regra.
11. **Código.** TypeScript e Python fora das migrações não são superfície. Um
    `valor_kz` numa variável de um serviço passa.
12. **Indirecção deliberada numa revisão** (um dicionário de funções, um
    decorador que executa SQL). O leitor segue chamadas directas; ver §2.

---

## 2. Como uma migração é lida

As revisões são Python que passa SQL a `op.execute(…)`. O gate tem de saber **que
SQL é esse**, sem correr a revisão e sem instalar o Alembic. Lê a árvore
sintáctica e **segue** o que é determinável
([`tools/canon_lint/revisao.py`](../tools/canon_lint/revisao.py)):

| Segue | Exemplo |
|---|---|
| cadeias literais, concatenação, `text("…")` | `op.execute("CREATE TABLE …")` |
| constantes de módulo atribuídas **uma única vez** | `SQL = "…"` no topo |
| *f-strings* sobre nomes resolvidos e `", ".join(x)` | `f"GRANT SELECT ({', '.join(colunas)}) ON platform.{tabela} …"` |
| ciclos `for` sobre uma constante | `for tabela, colunas in MAPA.items():` |
| funções do próprio módulo, com argumentos literais | `criar("tenants")` |
| **módulos auxiliares declarados** na política | `rls.enable_tenant_rls("tenants", coluna="id")` |

**Um módulo auxiliar declarado não é dispensado de leitura.** Quando uma revisão
chama `rls.enable_tenant_rls("tenants", coluna="id")`, o lint abre `db/rls.py`,
segue o corpo da função com os argumentos da chamada, e verifica o SQL que daí
sai — o mesmo que a revisão executaria. É assim que a revisão `0002` do KAM-004
(RLS por tenant) é lida: 28 instruções, 18 delas vindas do auxiliar, zero
achados e zero ilegíveis — é o que o gate faz hoje sobre `main`, e está fixado
num teste.

**Tudo o resto falha, com a linha:** um argumento que não se resolve, a API de
operações do Alembic (`op.create_table`, por qualquer *alias*), `sa.Table` e
`MetaData`, um `import` de um módulo que não esteja declarado, `exec` e `eval`,
o objecto `op` usado de outra forma que não `op.<método>(…)` (um
`corre = op.execute`, um `getattr(op, …)`), uma constante reatribuída ou
sombreada por uma variável local, e uma revisão de que não se leu instrução
nenhuma.

No SQL, uma instrução de forma desconhecida falha; e um bloco `$$ … $$` só passa
se não tiver `CREATE` nem `ALTER` lá dentro — `DO $$ BEGIN CREATE ROLE … END $$`
é a forma idempotente habitual de criar papéis, e por isso mesmo não pode ser
opaca.

### Os domínios fechados

Uma coluna cujo domínio o dicionário fixa (`tenants.estado`, `tenant_channels.origem`,
`authn_method`…) é verificada de três maneiras:

- a restrição **inteira** é `coluna IN (…)`, `= ANY (ARRAY[…])` ou
  `c = 'a' OR c = 'b'` — incluindo as formas com `::text` e parênteses que o
  `pg_dump` escreve: compara-se **por igualdade**, e um estado a mais ou a menos
  falha;
- um **ENUM** é o domínio da coluna que o usa;
- a coluna aparece num `CHECK` que não se consegue ler (`SIMILAR TO`, `~`), ou é
  criada **sem `CHECK` nenhum**: falha. O domínio do §3 não se cumpre por omissão.

---

## 3. De onde vêm os nomes

```text
specs/02_Dicionario_de_Dados_Canonico.md §3     ← fonte da verdade (Markdown)
        │  python -m dict_export
        ▼
canon/dicionario.yaml                            ← GERADO; não se edita
        │
        ├── canon/extensoes.yaml                 ← nomes que o §3 não cobre
        ├── ci/canon-lint.yaml                   ← superfícies, sentinelas, ponteiros para o §3
        └── ci/canon-allow.yaml                  ← variantes que ficam em docs/tecnica, e porquê
        ▼
python -m canon_lint check
```

**`canon/dicionario.yaml` não se edita à mão.** O gate regenera-o e compara: um
YAML alterado sem o Markdown, ou um Markdown alterado sem regenerar, falha.

### As regras da exportação

As tabelas do §3 são prosa com nomes entre crases. A exportação é mecânica; as
regras estão em [`tools/dict_export/exportar.py`](../tools/dict_export/exportar.py)
e resumem-se assim:

| Regra | Exemplo |
|---|---|
| Uma entrada por linha de tabela do §3 | 66 entradas no dicionário 1.5 |
| Só conta o que está entre crases; o que tem `/` ou `§` é referência | `` `../docs/tecnica/03` `` não é nome |
| Colunas «Conceito» e «Nome» → nomes canónicos | `contacts(contact_id, …)` dá `contacts`, `contact_id` |
| `nome(a, b, …)` em minúsculas → tabela com colunas | `platform.tenants(id uuid)` |
| `` `x` ∈ {`a`, `b`} `` → domínio fechado de `x` | `tenants.tipo` ∈ {`pme`, …} |
| Coluna «Substitui», identificador que **não** é canónico em lado nenhum → **variante** | `valor_kz`, `'exato'` |
| Coluna «Nota» → nomes conhecidos, que **nunca** salvam uma variante | os campos de `consent_event` |
| Um *span* todo em maiúsculas na coluna «Substitui» é palavra-chave SQL, não variante | «`SET` de sessão» (emenda 1.5) |

Três consequências que vale saber antes de editar o dicionário:

- **Um nome na coluna «Substitui» passa a falhar em todo o lado**, incluindo em
  `docs/tecnica/`. Acrescentar uma variante ao dicionário é uma alteração com
  alcance: o `git diff` de `canon/dicionario.yaml` mostra-a.
- **Um nome canónico numa lista pura de variantes é uma contradição.** A
  exportação não escolhe: mantém-no canónico e imprime um aviso em cada
  execução. Há uma hoje — ver §7.
- **O conjunto das 14 variantes está fixado num teste**, conferido à mão contra
  a coluna «Substitui». Citar uma variante entre crases na coluna «Nome» de
  outra linha retirava-a do conjunto sem aviso; agora falha um teste, e quem
  emendar o dicionário actualiza a lista de propósito.

O que a exportação **não** vê, e não tem como ver: uma variante escrita sem
crases, ou numa frase fora de uma tabela. Uma tabela indentada, um cabeçalho de
coluna desconhecido ou um número errado de células são erro.

---

## 4. Correr

```bash
make ci-3b            # o gate: exportação em dia + as quatro superfícies + canário
make dict-export      # regenera canon/dicionario.yaml depois de emendar o dicionário
```

Sem `make` (Windows, Git Bash), a partir de `tools/`:

```bash
python -m dict_export --root .. --check
python -m canon_lint --root .. check
python -m canon_lint --root .. canario
python -m canon_lint --root .. ficheiro migracoes ../db/migrations/versions/0001_schema_platform.py
```

Códigos de saída: `0` conforme, `1` achados, `2` erro de configuração (um
ficheiro do gate em falta ou mal formado **não** é «conforme»).

---

## 5. Como acrescentar uma extensão

Uma extensão é a declaração de que um nome **novo** — que o §3 não cobre e que
não substitui nenhum nome existente — pode existir.

**Antes de a escrever, a pergunta é se o nome devia estar no dicionário.** Um
conceito que mais de um ticket vai usar (uma tabela, um evento, um estado)
entra no §3 por emenda (dicionário §5–§6), marcado *proposta*. A extensão é para
o pormenor que só um ticket conhece: as colunas restantes de uma tabela cujo
nome já é canónico, um parâmetro de uma *tool*.

1. Correr o gate e ler o achado. Ele diz o tipo e o nome exactos a declarar:

   ```text
   [fora-do-dicionario] `tenants.cor_favorita` → `platform.tenants(id uuid)`, dicionário §3.2
   (coluna fora do dicionário; se for um nome novo, declare-o em canon/extensoes.yaml com tipo `coluna`, ticket e data)
   ```

2. Acrescentar a entrada a [`canon/extensoes.yaml`](../canon/extensoes.yaml):

   ```yaml
     - nome: tenants.cor_favorita
       tipo: coluna
       ticket: KAM-NNN        # o ticket que introduz o nome
       data: 2026-10-11       # o dia em que a extensão entra — nunca futuro
   ```

3. Pedir a revisão do **Arquitecto de Plataforma**. O critério de aceitação do
   KAM-111 exige-a, e o `CODEOWNERS` atribui-lhe a pasta `canon/`. **Não é
   imposta por máquina**: o *ruleset* de `main` tem hoje zero aprovações
   exigidas (`docs/ci.md` §7, lacuna 16).

| `tipo` | `nome` | Onde se usa |
|---|---|---|
| `esquema` | `analitica` | `CREATE SCHEMA` |
| `tabela` | `image_jobs` | `CREATE TABLE`, `CREATE VIEW` |
| `coluna` | `tenants.nif` | colunas — **sempre qualificada pela tabela** |
| `valor` | `tenants.plano=free` | valores de `CHECK` sem domínio no dicionário |
| `papel` | `kamba_identity` | `CREATE ROLE` |
| `tipo_sql` | `estado_t` | `CREATE TYPE`, `CREATE DOMAIN` |
| `evento` | `order.paid` | `tipo` de um *schema*; `subscriptions` do registo |
| `campo` | `envelope.registado_em`, `payment.confirmed.charge_id` | campos de um *schema* de evento |
| `vertical`, `modulo`, `limite` | `assistente`, … | `id`, `entitlements.modulo`, `entitlements.limites` |
| `tool`, `parametro` | `book_slot`, `book_slot.slot_id` | `tools` do registo |

O que o ficheiro **recusa**, com erro de configuração:

- uma **variante** (`tenants.valor_kz`): o nível 1 não tem excepções;
- um nome que o dicionário **já cobre**: a extensão seria ruído;
- uma extensão que **nenhuma superfície usa**: a lista não apodrece;
- uma **data futura**, tipo desconhecido, ticket que não é `KAM-NNN`, chave a
  mais, entrada repetida. (Que o `KAM-NNN` existe é verificado pelo gate 3,
  que lê este ficheiro como qualquer outro.)

> **O primeiro ficheiro real do registo vai precisar de extensões para as suas
> *tools*.** O dicionário só nomeia uma (`enhance_image`); o `vendedor.yaml` de
> `docs/tecnica/02` §5.1 tem seis (`search_catalog`, `get_price_stock`,
> `propose_cart`, `criar_pedido`, `get_order_status`, `get_store_info`). É por
> desenho — ou entram no §3 por emenda, ou em `canon/extensoes.yaml` — e fica
> dito para o executor do EPIC-03 não o descobrir no CI.

---

## 6. As *fixtures* e as duas divergências que não têm uma

O critério de aceitação pede «12 negativas (uma por divergência) e 12
positivas». Estão **10 + 10**, em
[`tools/canon_lint/tests/fixtures/`](../tools/canon_lint/tests/fixtures/):

| | Superfície | A negativa falha com |
|---|---|---|
| D-01 | migrações | `` `contacts.bsuid` → `contacts(contact_id, tenant_id, criado_at, …)`, dicionário §3.1 `` |
| D-02 | migrações | `` `consent_log` → `consent_event (append-only)`, dicionário §3.1 `` |
| D-03 | eventos | `` `valor_kz` → `valor_minor`, dicionário §3.4 `` |
| D-04 | migrações | `` `callback_hmac_ok` → `payment_events.authn_ok boolean + authn_method ∈ {…}`, dicionário §3.4 `` |
| D-05 | registo | `` `payment.confirmed` sem `payment.manual_confirmed` → …, dicionário §3.4 `` |
| D-06 | migrações | `` `UNIQUE(provider, referencia)` em `payment_events` → …, dicionário §3.4 `` |
| D-08 | migrações | `` `tenants.estado` com {onboarding, ativo, suspenso, encerrado} → …, dicionário §3.2 `` |
| D-10 | migrações | `` `llm_calls` → `llm_call_log`, dicionário §3.6 `` |
| D-11 | registo | `` `confirm:{cart_id}` em `servicos` → `confirm:{hold_id}`, dicionário §3.3 `` |
| D-12 | eventos | `` `versao` livre em `v1.schema.json` → `versao` com `const: 1`, dicionário §3.5 `` |

**D-07 e D-09 não têm *fixture*, e não se inventou uma para a conta dar doze.**
O D-07 é sobre *quem* reage a `tenant.activated` — os dois eventos são
canónicos; o D-09 é um número numa tabela de retenção. Nenhum dos dois tem
forma de nome numa migração, num *schema* ou num contrato de *tool*. **A caixa
do critério fica por marcar**; a decisão é de quem o escreveu (KAM-141, linha 8).

**A positiva do D-03 não tem `currency`.** O D-03 do ticket dá `valor_minor` +
`currency` como forma canónica «(§3.4)», mas o §3 não lista `currency` — só o
§2 — e o gate recusa-o. A positiva passa por não o ter. É um defeito do canon
(KAM-141, linha 2), e não se contornou com uma extensão.

### O que o canário prova está no código, não no manifesto

O manifesto diz onde estão os ficheiros e que mensagem cada um dá. **Não decide
quantos são.** Em [`tools/canon_lint/cli.py`](../tools/canon_lint/cli.py) estão
fixados: as doze divergências, as duas que podem não ter *fixture*
(`SEM_FORMA_DE_NOME`), e o mínimo de uma negativa por superfície. Cada negativa
tem de dar **exactamente um** achado, cuja mensagem **começa** pelo `espera` do
manifesto — que por sua vez tem de ter a forma «`variante` → `canónico`,
dicionário §3.x».

A primeira versão deixava tudo isso no YAML: um manifesto com `casos: []` dava
«0 negativas vermelhas» e saída 0, e o passo que existe para provar que as
superfícies vazias mordem desaparecia com uma edição a um ficheiro de
*fixtures* (ANALISE-05, B1).

Quatro das dez (D-05, D-06, D-11, D-12) não são variantes de nome: são
**regras** que o §3 escreve em prosa. Cada uma tem um ponteiro em
[`ci/canon-lint.yaml`](../ci/canon-lint.yaml) para a linha do dicionário de onde
vem, e o lint **confirma o ponteiro ao arrancar** — a política não pode proibir
o que o dicionário não proíbe.

> **A regra do D-12 é *proposta*, e é a mais discutível das quatro.** O
> dicionário diz que versões desconhecidas «falham de forma visível». A forma
> mecânica disso num *schema* é a `versao` ser `const`: um consumidor que valide
> um evento `versao: 2` contra o *schema* `v1` falha, em vez de o aceitar. Quem
> entender que a regra pertence só ao publicador (`docs/tecnica/06` §6.6)
> retira-a de `tools/canon_lint/eventos.py`.

---

## 7. O que este ticket encontrou e não corrigiu

O ticket diz «as 12 e só essas», e o seu critério 2 manda que «qualquer outra
divergência encontrada vira ticket `fix`». São três tickets.

### No dicionário — KAM-141

| # | Achado |
|---|---|
| 1 | **`manual_max_minor` está nas duas colunas** da linha «Entitlement (chaves)» (§3.2). O gate trata-o como canónico e avisa em cada execução |
| 2 | **`currency` não está no §3**, só no §2. O D-03 dá-o como forma canónica «(§3.4)» |
| 3 | **O dicionário e o KAM-008 discordam sobre `contacts`.** O §3.1 põe `bsuid_hmac` em `contact_endpoints`; o KAM-008 pede `lookup_hmac` e `hmac_kid` em `contacts`, e o papel `kamba_identity`, que o §3.2 não lista. A emenda D-01 seguiu o dicionário, que prevalece. **Decidido como *proposta* pela emenda 1.8 (KAM-008):** o HMAC do BSUID vive em `contact_endpoints.bsuid_hmac`, `lookup_hmac` passa a variante e `kamba_identity` entra no §3.2 — ver `identidade.md` §7. Por ratificar |
| 4 | **`authn_method`** ∈ {`hmac`, `manual`, `consulta`} no §3.4; `docs/tecnica/04` §6.2 escreve `('hmac_sha256','status_pull','humano_auditado','sistema')` |
| 5 | **O envelope** do §3.5 tem nove campos; o de `docs/tecnica/06` §4 tem mais seis e põe `seq` dentro de `agregado` |
| 6 | **`modulo`**: domínio fechado no §3.7, `CHECK` de forma no §3.2, e `modulo: vendedor` em `docs/tecnica/02`. A política declara que o domínio só vale no registo |
| 7 | O cabeçalho do dicionário diz «Versão 1.0» e o §6 vai na 1.5 |
| 8 | O critério das 12 + 12 *fixtures* (§6) |
| 9 | O tipo de cada nome (§1) |

### Em `docs/tecnica/` — dívidas com prazo — KAM-139

Estão em [`ci/canon-allow.yaml`](../ci/canon-allow.yaml), secção `dividas`, e
**vencem a 2026-11-10**: a partir do dia seguinte o gate fica vermelho em `main`
e em todos os PR, se não tiverem sido corrigidas. O prazo é *proposta* (30 dias,
como os *waivers*).

| Variante | Onde | Ocorrências | Canónico |
|---|---|---|---|
| `kamba_ops` | `03` §5.5; `04` §6.2 | 1 + 2 | `kamba_batch` |
| `valor_max_pedido_kz` | `02` §5.1, §6.1, §6.2 | 3 | `valor_max_pedido_minor` |
| `preco_kz` | `05` §6.1, §12; `06` §10.2 | 5 + 3 | `preco_minor` (muda a unidade) |
| `'exato'` | `05` §6.1; `06` §10.2 | 1 + 1 | `'fixo'` |
| `total_kz` | `06` §6.1, §12 | 2 | `total_minor` |
| `tenant_isolamento` | `03` §5.5 | 1 | `tenant_iso` |

As duas primeiras são as que o KAM-003 registou na emenda E-01 da Carta. As
três seguintes são novas: o §3.3 lista-as como variantes e nenhuma das doze do
ticket as cobre. A última passou a variante com a emenda 1.5 do dicionário
(KAM-004), que fixa `tenant_iso` e regista esta divergência.

As 12 ocorrências **históricas** (a variante é citada para dizer que foi
substituída) não têm prazo e por isso têm **âncora**: o excerto da linha que
mostra que é citação. Trocar a citação por um uso vivo, com a mesma contagem,
falha.

### Em `docs/tecnica/` — o que o lint de nomes não apanha — KAM-140

| Achado | Porque escapa |
|---|---|
| O DDL de `tenant_channels` de `03` §5.2 (três estados, coluna `persona`, `canal`, `coexistencia`) contra o de `01` §7.1, que é o implementado na revisão `0001` | os documentos só têm nível 1. **Numa migração** seria recusado — há um teste que o prova |
| `contacts` e `contact_endpoints` com formas diferentes em `01` §6.2 e `03` §5.3; em `03`, `contact_endpoints` ficou sem chave primária e a nota (c) refere uma unicidade que já não está no DDL | a emenda D-01 pôs os nomes do dicionário; não desenhou o DDL, que é do KAM-008 |
| `contacts.consentimento jsonb` em `03` §5.3: uma quarta forma de guardar consentimento | não é uma das três tabelas do D-02 |
| Campos e finalidades de `consent_event` diferentes em `01` §6.2, `06` §7.3 e `08` §8.1, e diferentes dos do dicionário §3.1 | o D-02 é a troca do nome da tabela |
| `registry/servicos.yaml` em `02` §5.1 subscreve só `payment.confirmed`; o dicionário §3.5 diz que subscreve os dois | o exemplo está num documento, não em `registry/` |
| `payment.confirmed` como único evento que faz avançar a encomenda em `03` §2 e §6.2 e em `04` §2 e §7 | o D-05 lista `04` §4.1, `06` §5 e `03` §12 |
| Estados do tenant sem `restrito` em `07` | o D-08 não lista o `07` |
| A tabela de `10` §15.1 sem linhas próprias para `restrito → ativo` e `restrito → suspenso`; o diagrama Mermaid nunca passou por um *parser* | — |

---

## 8. Controlo de versões

| Versão | Data | Alteração | Autor |
|---|---|---|---|
| 1.0 | Outubro 2026 | Emissão (KAM-111): mecanismo do gate 3b, regras da exportação, como acrescentar uma extensão, *fixtures*, e o que ficou por corrigir. | Equipa KAMBÁ |
| 1.1 | Outubro 2026 | Depois da revisão adversarial ([`ANALISE-05`](analises/ANALISE-05-KAM-111-dicionario-canonico-e-lint.md)): como uma migração é lida (§2, incluindo os auxiliares do KAM-004), domínios fechados, variantes em cadeias, nomes «conhecidos» por tipo com o limite medido, canário fixado no código, âncoras das históricas, e os três tickets `fix` (KAM-139 a KAM-141). | Equipa KAMBÁ |
| 1.2 | Outubro 2026 | KAM-008: a linha 3 do §7 (dicionário contra o bloco do KAM-008) fica decidida, como *proposta*, pela emenda 1.8 do dicionário — a favor do dicionário, com `lookup_hmac` registado como variante. Fica por ratificar no KAM-141. | Equipa KAMBÁ |
