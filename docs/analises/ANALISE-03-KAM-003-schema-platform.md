# ANÁLISE-03 — Revisão adversarial do KAM-003 (schema `platform`)

| Campo | Valor |
|---|---|
| Ticket | KAM-003 — Schema `platform`: tenants, entitlements, tenant_channels e migrações reversíveis |
| Ramo | `feature/KAM-003-schema-platform` (PR `albinoJimy/kamba#15`) |
| *Baseline* revista | `aa42a44` |
| Data | Outubro 2026 |
| Método | Execução contra o PostgreSQL 18.6 do *gate* 8; mutações em cópia fora do repositório |
| Veredicto da revisão | **Não aprovado** — 7 maiores, 6 menores, 3 notas; critérios 5 e 7 não cumpridos à letra, critério 6 a passar com a propriedade falsa |
| Estado | 6 maiores corrigidos e 1 devolvido como decisão; 6 menores corrigidos ou registados; **20 mutações, 20 apanhadas** |

A revisão foi conduzida por um agente independente, que recebeu os requisitos e
o código e **não** as justificações de quem o escreveu. O *gate* 8 estava verde —
75 testes, na máquina e no *runner* — e a revisão não aprovou na mesma.

> **A lição desta revisão é sobre testes verdes.** Os 75 testes passaram à
> primeira, e a prova por mutação feita antes da revisão (seis alterações) deu
> confiança a mais: as mutações eram as que **eu** me lembrei de fazer, e
> mediam o que **eu** me tinha lembrado de testar. A revisão fez outras cinco —
> `GRANT kamba_batch TO kamba_app`, `ON DELETE CASCADE`, treze `NOT NULL`
> retirados, privilégios por omissão, uma coluna de contacto em claro — e
> **as cinco deixavam a *suite* verde**. Uma prova por mutação vale o que
> valerem as mutações, e quem escreveu os testes é o pior autor possível delas.

---

## 1. Maiores

### M1 — A guarda do Fluxo B ficava cega com a RLS do KAM-004

`libs/py-core/src/kamba_core/fluxo_piloto.py`

A guarda conta linhas com a ligação que lhe derem. Com `FORCE ROW LEVEL
SECURITY` e a política por `app.tenant_id` — a que o KAM-004 vai aplicar —
`kamba_app` sem contexto de tenant vê **zero** linhas, e a guarda devolvia «pode
arrancar» sobre uma base com tenant `platform`, canal `plataforma` e vertical
`assistente`. Reproduzido: recusa antes da RLS, arranca depois.

O controlo do ADR-011 passava a falhar aberto, em silêncio, **no dia em que o
ticket seguinte entrasse** — e havia um teste a afirmar que a guarda corre como
`kamba_app`.

**Corrigido.** A guarda prova primeiro que vê tudo — ou o papel contorna a RLS,
ou nenhuma das duas tabelas a tem activa — e levanta `GuardaCega` se não
conseguir. Ensaiado no *gate* 8 com uma política igual à do KAM-004: `kamba_app`
é recusado, `kamba_batch` vê e recusa o arranque. A dependência ficou escrita no
bloco do KAM-004, que tem de decidir com que papel a guarda corre.

### M2 — A guarda não via variantes de `vertical`

A coluna não tinha `CHECK` e a guarda comparava por igualdade. `'Assistente'`,
`' assistente'`, `'assistente_v2'` e `''` eram todos aceites na coluna e
invisíveis para a guarda.

**Corrigido, dos dois lados.** A coluna ganha um `CHECK` **de forma** —
minúsculas e `snake_case`, como o dicionário §2 manda — que não fecha o domínio,
porque as verticais são configuração (ADR-012). E a guarda passa a **lista de
permitidas**: no Piloto só `vendedor` e `servicos` (dicionário §3.2). É mais
largo do que o critério de aceitação, que nomeia só `assistente`, e é de
propósito: o que não se conhece não arranca.

### M3 — Critério 7: nenhum serviço chama a guarda

O critério diz «o arranque do CHR/AGR falha». O que existe é uma função de
biblioteca, testada; nenhum arranque falha. O CHR nasce no KAM-014 e o AGR não
abre ligação à base.

**Não corrigido — devolvido.** A caixa fica vazia. A saída certa é uma emenda ao
critério («a guarda existe e recusa as três condições; a chamada no arranque é
critério do KAM-014 e do ticket que der base de dados ao AGR»), e isso é de quem
escreveu o critério.

### M4 — Critério 5: o teste só olhava para nomes

A detecção procurava `msisdn`, `telefone` e `phone` no nome da coluna. Um
mutante com `contacto_dono text`, `whatsapp_cliente text` e `numero_movel
varchar(16)` passou os 75 testes.

**Corrigido.** Uma lista de fragmentos proibidos nunca fecha; uma lista de
colunas permitidas fecha. Entra um inventário de todas as colunas de `platform`
— tipo, nulidade, omissão e a resposta a «guarda dados pessoais?» — e uma coluna
nova falha até ser declarada.

O que nenhum schema garante, e fica dito: que ninguém grave um telefone em
`nome` ou em `zona`. Isso é do validador de entrada e do KAM-068.

**A contradição do ticket mantém-se, e a caixa fica vazia.** O critério 5 dá uma
lista fechada de **duas** colunas com `phone` no nome; o critério 3 **exige**
`tenant_channels.phone_number_id`. A implementação tem três entradas, com a
razão — é o identificador opaco que a Meta atribui ao número do negócio, não um
telefone — mas o critério diz duas.

### M5 — Critério 6: os testes mediam atributos, não o que `kamba_app` consegue

Nada verificava `pg_auth_members`, as ACL das tabelas nem os privilégios por
omissão. Dois mutantes passaram a *suite* inteira:

- o `bootstrap` com `GRANT kamba_batch TO kamba_app` — a aplicação a um
  `SET ROLE` de contornar a RLS;
- a revisão com `TRUNCATE … WITH GRANT OPTION`, `GRANT SELECT … TO PUBLIC` e
  `ALTER DEFAULT PRIVILEGES … GRANT ALL`.

E, à letra: `CREATE TEMP TABLE` sob `kamba_app` **sucedia**, porque o `PUBLIC`
tem `TEMPORARY` em cada base.

**Corrigido.** Testes sobre o efeito: pertenças vazias, a matriz exacta de
privilégios por tabela e por coluna, `pg_default_acl` vazio, o `PUBLIC` sem
nada. O `bootstrap` revoga pertenças nos dois sentidos, faz `RESET ALL` e tira
`TEMPORARY` e `CONNECT` ao `PUBLIC`. O critério 6 cumpre-se agora sem excepção
para as temporárias.

### M6 — `kamba_app` podia apagar tenants e mudar-lhes o tipo

`SELECT/INSERT/UPDATE/DELETE` nas três tabelas, igual para `app` e `batch`. Como
`kamba_app`: `DELETE FROM platform.tenants` aceite; `UPDATE … SET tipo = 'pme'`
aceite — **o tenant `platform` saía da vista da guarda**; `UPDATE
tenant_channels SET tenant_id = <outro>` aceite.

**Corrigido em parte, e a outra parte devolvida.** `kamba_app` deixa de ter
`DELETE` em qualquer tabela (dicionário §2: «soft delete: estado, nunca
DELETE») e passa a `UPDATE` por coluna, sem `tenants.tipo`,
`tenant_channels.origem` nem `tenant_channels.tenant_id`.

**Fica por decidir quem altera `tenants.plano`, `estado` e `verificado_at`.**
`kamba_app` continua a poder — e com a política `id = app.tenant_id`, um
contexto de tenant altera o **próprio** plano. Nenhum documento do desenho diz
quem o deve fazer. Não foi decidido aqui para não ser decidido em silêncio; está
escrito no bloco do KAM-004.

### M7 — `--bd-existente` trocava as palavras-passe dos papéis da instância

O trinco protegia a base (`*_gate8`); os papéis são globais à instância. O
*gate* gerava palavras-passe aleatórias e o `bootstrap` aplicava-as: uma base
`kamba_gate8` criada na instância de desenvolvimento derrubava todos os serviços
dela, com credenciais que ninguém conhece.

**Corrigido.** O modo exige as três palavras-passe **dadas** no ambiente, e o
*docstring* diz o que o trinco protege e o que não protege. O trinco passou a
igualdade (`kamba_gate8`) em vez de sufixo: `producao_gate8` passava.

---

## 2. Menores e notas

| Achado | Estado |
|---|---|
| `NOT NULL`, `ON DELETE` e omissões sem teste (treze `NOT NULL` retirados, *suite* verde) | **Corrigido** — o inventário cobre nulidade e omissão; `confdeltype` das FK testado |
| «Seis mutações, nove falhas» não se reproduzia: o método não estava escrito | **Corrigido** — `db/mutacoes.py`, vinte mutações uma a uma, no repositório |
| O DDL aceitava valores vazios e incoerentes: dois tenants com `nif = ''` colidiam no único; o mesmo NIF com um espaço criava segundo tenant; `limites` aceitava `[]` | **Corrigido** — `CHECK` de forma em NIF, nome, identificadores do canal, `free_tier_used`, `limites` e `modulo` |
| `deleted_at` preenchido com `estado = 'ativo'`; tenant `encerrado` com canal `ativo` | **Registado, não corrigido** — é uma regra de coerência entre colunas que nenhum documento define |
| O comentário dizia que a palavra-passe não aparece no `docker inspect`; aparece | **Corrigido** o comentário |
| Matar o *gate* deixava o contentor a correr | **Corrigido em parte** — SIGINT e SIGTERM limpam; SIGKILL não, e está dito |
| A palavra-passe ia em claro para o registo do servidor com `log_statement=ddl` | **Corrigido** — verificador SCRAM-SHA-256 calculado do lado do cliente |
| «Idempotente e repõe os atributos» dizia mais do que fazia | **Corrigido** — faz o que diz, e a saída reporta a redefinição das palavras-passe |
| A dependência `KAM-111` sobrevivia na tabela-resumo do epic: vive em **três** sítios e foram corrigidos dois | **Corrigido** |
| Três registos prometidos em comentários e inexistentes no bloco do ticket | **Corrigido** — secção de verificação do KAM-003 |
| `canal` e `criado_at` do canal desaparecem do DDL sem registo | **Registado** — estão no doc 03 e não no doc 01, que é o que o ticket manda seguir |
| A *suite* directa, com base de nome errado, saía com 0 | **Corrigido antes da revisão** — `db/correr_suite.py`: num *gate*, saltar é falhar |

---

## 3. Um defeito que a correcção introduziu

Os testes novos da guarda sob RLS **penduraram o *gate* dez minutos**. O
`tearDown` fazia `ALTER TABLE` — que pede `ACCESS EXCLUSIVE` — enquanto as
ligações do próprio teste ainda tinham a transacção aberta e seguravam um
`ACCESS SHARE`. Esperavam um pelo outro para sempre.

Corrigida a ordem, e duas defesas que não dependem de acertar a ordem na próxima
vez: `lock_timeout` na ligação que faz DDL, e um limite de tempo na *suite*. Um
*gate* pendurado é pior do que um *gate* vermelho — ocupa o *runner* até ao
limite do *job* e não diz porquê.

---

## 4. A prova por mutação, refeita

Vinte alterações deliberadamente erradas, **uma de cada vez**, em cópia fora do
repositório; o *gate* 8 tem de falhar em cada uma. `python db/mutacoes.py`.

| Onde | Mutações | Apanhadas |
|---|---|---|
| Revisão `0001` — estrutura (estado a mais, `UNIQUE`, ordem do índice, `_enc` em `text`, `timestamp` sem fuso, `NOT NULL`, omissão de `origem`, `CASCADE`, coluna de contacto, `CHECK` da vertical) | 10 | 10 |
| Revisão `0001` — privilégios (`DELETE` e `UPDATE (tipo)` à aplicação, privilégios por omissão, `SELECT` ao `PUBLIC`) | 4 | 4 |
| `bootstrap` (pertença a `kamba_batch`, `TEMPORARY` ao `PUBLIC`, `BYPASSRLS` na aplicação) | 3 | 3 |
| Guarda (vertical por igualdade, sem prova de visibilidade, condição da origem retirada) | 3 | 3 |
| **Total** | **20** | **20** |

As cinco que a revisão mostrou sobreviverem à primeira *suite* estão na lista.

**O limite desta prova é o mesmo da anterior**: são as mutações de que alguém se
lembrou. A diferença é que agora metade vem de quem não escreveu os testes.

---

## 5. Categorias sem achados

- **Critério 1 e a contagem de objectos** — sólida. O `DROP SCHEMA` sem
  `CASCADE` e a asserção de que o schema não existe tornam a contagem em
  `pg_class`/`pg_proc`/`pg_type` redundante, mas correcta.
- **Colunas contra o canon, por script** — `tenants` 18/18 com o doc 03 §5.2,
  `tenant_channels` 16/16 com o doc 01 §7.1, `entitlements` 4/4.
- **Dependências** — fecho completo para Python 3.12 e 3.13; as dez licenças
  conferem com o PyPI; a reentrada de `MIT-0` está justificada.
- **Fuga de URL ou segredo em erros** — nenhuma: palavra-passe errada, base
  inexistente e porta errada, no Alembic e no `bootstrap`, com zero ocorrências
  do segredo na saída.
- **A guarda quanto à variável** — falha fechada confirmada.
- **Escopo** — nada de outro ticket além do *gate* 8, que entrou por decisão.

---

## 6. Controlo de versões

| Versão | Data | Alteração | Autor |
|---|---|---|---|
| 1.0 | Outubro 2026 | Emissão: 16 achados da revisão adversarial do KAM-003, com a disposição de cada um e a prova por mutação refeita. | Equipa KAMBÁ |
