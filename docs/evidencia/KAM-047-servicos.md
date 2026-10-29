# KAM-047 — Evidência do módulo `servicos`

| Campo | Valor |
|---|---|
| Ticket | KAM-047 — Módulo `servicos`: serviços, recursos, disponibilidade, marcações e holds |
| Âmbito | Medições feitas por execução contra o PostgreSQL da imagem fixada, e o que delas se concluiu |
| Estado | As medições são **CONFIRMADAS** (execução própria, com o comando e a data); as leituras que delas se tiram estão marcadas uma a uma |
| Data | 28 de Outubro de 2026 |

Este anexo existe porque as afirmações mais fortes do ticket — «a sobreposição é
impossível por construção», «`btree_gist` existe na versão fixada», «1.000
tentativas dão uma marcação» — não se verificam por leitura. Cada uma tem aqui o
comando, a saída e a data.

---

## 1. `btree_gist` na imagem fixada, e quem a pode instalar

**Afirmação:** a extensão `btree_gist` existe no PostgreSQL 18 fixado por
*digest*, e o `kamba_migrator` — que é `NOSUPERUSER` — pode instalá-la.

**Como se mediu.** A imagem é a constante `IMAGEM` de `db/gate_bd.py`,
`pgvector/pgvector:0.8.7-pg18@sha256:2358fcba…7e2bc11`.

```
docker run --rm <imagem> sh -c 'ls /usr/share/postgresql/*/extension/btree_gist*.control; postgres --version'
  /usr/share/postgresql/18/extension/btree_gist.control
  postgres (PostgreSQL) 18.6 (Debian 18.6-1.pgdg12+2)

docker run --rm <imagem> cat /usr/share/postgresql/18/extension/btree_gist.control
  default_version = '1.8'
  relocatable = true
  trusted = true
```

Depois, com o papel verdadeiro (`CREATE ROLE kamba_migrator LOGIN NOSUPERUSER …`):

```
SELECT current_user, rolsuper  ->  kamba_migrator | f
CREATE SCHEMA servicos;              ->  CREATE SCHEMA
CREATE EXTENSION btree_gist SCHEMA servicos;  ->  CREATE EXTENSION
```

**CONFIRMADO.** `btree_gist` 1.8, PostgreSQL 18.6, instalável por um papel sem
superutilizador porque o `.control` diz `trusted = true` — o que desde o
PostgreSQL 13 dispensa superutilizador a quem tenha `CREATE` no esquema de
destino. O `kamba_migrator` tem-no, porque é ele que cria o `servicos`.

**O que isto decidiu:** a extensão é criada **pela revisão** `0025` e não pelo
`initdb`. O `infra/compose/postgres/initdb/01-bases-e-extensoes.sql` só corre no
compose de desenvolvimento e o contentor do *gate* 8 **não o monta** — uma
extensão criada lá deixava a suite a falhar no CI com a revisão verde na máquina
de quem a escreveu. E vai para dentro do `servicos` e não para o `public`,
porque o `kamba_migrator` não tem `CREATE` no `public` e porque assim o
`DROP EXTENSION` do `downgrade` cai com o resto do esquema.

---

## 2. A restrição de exclusão, parte a parte

**Afirmação:** a restrição `bookings_sem_sobreposicao` recusa a sobreposição,
não recusa entre tenants, não recusa adjacentes, e não recusa o que está
cancelado.

**Como se mediu.** Quatro inserções contra a tabela real, com o `kamba_migrator`:

| Inserção | Esperado | Medido |
|---|---|---|
| 09:00–10:00 `hold` | entra | `INSERT 0 1` |
| 09:30–10:30 `confirmada`, mesmo tenant e recurso | recusa | `ERROR: conflicting key value violates exclusion constraint "bookings_sem_sobreposicao"` |
| 09:30–10:30 `cancelada`, mesmo tenant e recurso | entra | `INSERT 0 1` |
| 09:00–10:00 `hold`, **outro** tenant, mesmo `resource_id` | entra | `INSERT 0 1` |
| 10:00–11:00 `hold`, adjacente | entra | `INSERT 0 1` |

**CONFIRMADO**, as cinco. A definição guardada pelo catálogo é confrontada por
extenso em `db/tests/test_inventario.py::test_a_restricao_de_exclusao_e_a_do_criterio_1`.

**Uma leitura que não é medição, e diz-se:** o `tenant_id WITH =` **não é
exercitável hoje**. A `resources_pkey` é `PRIMARY KEY (resource_id)` sem o
`tenant_id`, pelo que um `resource_id` é globalmente único e dois tenants nunca
partilham um recurso — a tentativa de os criar falha com
`23505 duplicate key value violates unique constraint "resources_pkey"`, medido.
A quarta linha da tabela acima mediu-se com a restrição isolada, antes das
chaves estrangeiras. A coluna fica como defesa em profundidade, e o
`test_o_tenant_id_da_restricao_de_exclusao_e_defesa_em_profundidade` prende a
chave primária para que o dia em que ela passar a composta seja um dia em que
alguém tem de escrever o caso cruzado.

---

## 3. As 1.000 tentativas concorrentes, e os 486 *deadlocks* que elas revelaram

**Afirmação do critério 1:** 1.000 tentativas concorrentes de marcar o mesmo
recurso e intervalo produzem **1** marcação e as restantes `SLOT_TAKEN`.

**Primeira medição — sem a tranca por recurso.** 32 ligações, 1.000 tentativas.
A prova **não terminou**. O estado, lido do servidor enquanto corria:

```
SELECT count(*) FILTER (WHERE wait_event_type='Lock') FROM pg_stat_activity  ->  32
SELECT deadlocks FROM pg_stat_database WHERE datname='kamba_gate8'            ->  486
docker logs …  ->  ERROR: deadlock detected   (um por segundo)
```

**CONFIRMADO, e é o achado mais consequente deste ticket.** A verificação de uma
restrição de exclusão **espera** pela transacção com que conflitua; com N
inserções concorrentes da mesma chave, cada uma pode encontrar um conflito
**diferente**, e isso fecha um ciclo de espera. O PostgreSQL resolve-o ao fim do
`deadlock_timeout` (1 s por omissão), uma de cada vez.

E o efeito no critério era pior do que a lentidão: as tentativas perdedoras
voltavam com `40P01` e não com `23P01`, pelo que «as restantes `SLOT_TAKEN`» era
**falso** — o cliente recebia um erro de base de dados em vez de «esse horário
acabou de ficar ocupado».

**O que isso decidiu:** um `pg_advisory_xact_lock` por `(tenant, recurso)` antes
da inserção, com o prefixo `servicos:` para ficar fora do espaço de chaves do
KAM-018. **Não substitui a restrição** — uma tranca serializa tentativas e não
recusa nenhuma —, e quem o prova é o passo de canário
`test_sem_a_restricao_as_mil_dariam_mais_do_que_uma`: com a restrição removida e
a tranca no lugar, passam várias.

**Segunda medição — com a tranca.**

```
.venv/Scripts/python.exe db/gate_bd.py --suite tests_servicos
  concorrencia SERVICOS: 1000 tentativas no mesmo recurso e intervalo, 32 ligacoes, 56.6s
  aceites = 1;  recusas = {23P01: 999};  deadlocks = 0
  OK
```

**CONFIRMADO.** Uma marcação, 999 `SLOT_TAKEN`, zero *deadlocks*, exit 0. O
delta de `pg_stat_database.deadlocks` é uma asserção do próprio teste, para que
uma remoção da tranca volte a pendurar o *gate* com a razão escrita em vez de em
silêncio.

---

## 4. Dois defeitos que só a execução revelou

Ficam aqui porque são a classe de coisa que parece certa a ler.

**O `CHECK` com subconsulta.** A primeira versão da revisão validava o `fuso` com
`CHECK (EXISTS (SELECT 1 FROM pg_timezone_names WHERE name = fuso))`. O
`upgrade` morreu com `0A000 cannot use subquery in check constraint`: um `CHECK`
é uma expressão sobre a própria linha, e o catálogo de fusos é uma tabela. A
validação passou a *trigger* — e **não** a uma lista literal de fusos, porque o
`tzdata` actualiza-se e uma lista transformava uma invariante num número que
envelhece.

**O `LIMIT` que não era um tecto.** O `servicos.expirar_holds` selecionava com
`WHERE booking_id IN (SELECT … ORDER BY … LIMIT p_limite FOR UPDATE SKIP LOCKED)`
e `expirar_holds(2)` libertava **cinco** de cinco holds vencidos. Um sublink não
correlacionado com `LIMIT` e `FOR UPDATE` não é um valor calculado uma vez: o
planeador pode reexecutá-lo por linha, e cada execução devolve um conjunto
diferente de dois. A selecção passou a CTE, que é avaliada uma vez. Apanhado pelo
`test_o_tecto_de_linhas_e_respeitado_e_o_varrimento_repete`.

---

## 5. O comprimento do `slot_id`, e o limite que não se confirmou

**Medido:** `derivarSlotId` devolve **190 caracteres** para UUID canónicos e
instantes ISO com milissegundos.

**NÃO VERIFICADO:** qual é o limite de comprimento do `id` de uma linha de lista
interactiva da Meta. O `evidencia/E1` §7 confirma as **10 linhas** — que é o que
o critério 2 cita — e não diz nada sobre o `id`. O dicionário §3.4 regista a
mesma lacuna para o `cart_id`: «que ele caiba nos 256 caracteres do `id` de um
*reply button* é NÃO VERIFICADO».

**O que se fez com isso:** fixou-se `MAXIMO_DO_SLOT_ID = 256`, que é o número que
o dicionário já cita, e o `derivarSlotId` **lança** se o ultrapassar. Não é uma
afirmação sobre a Meta — é uma guarda para que um campo novo no corpo, ou uma
versão de dois dígitos, não passe despercebido até a Meta recusar o envio. A
margem actual são 66 caracteres. **Como se obtém o facto:** ler a página de
`interactive-list-messages` na documentação da Meta, que é o que o `E1` §7 já
cita como fonte, e registar lá o limite do `id`.

---

## 6. O que **não** está medido

- **O `p99 ≤ 60 s` do critério 3.** O mecanismo de libertação está medido (a
  função liberta, emite o evento, é idempotente e respeita o tecto); a
  **cadência** de quem a chama não está, porque não há agendador neste
  repositório — é o KAM-071. O varrimento oportunista de cada `getAvailability`
  e `holdSlot` garante que o intervalo está livre para o próximo que pergunte,
  o que é uma propriedade diferente e mais fraca: num tenant sem tráfego, o
  intervalo fica ocupado até ao pedido seguinte.
- **A ligação entre serviço e recurso.** Não existe no esquema — nem o DDL
  *proposta* do bloco nem o `tecnica/02` §8.3 a nomeiam —, pelo que
  `getAvailability(servico)` oferece horas de **todos** os recursos activos do
  tenant. Numa PME com dois serviços e dois recursos distintos, isso oferece o
  recurso errado. Está em `../dividas-documentais.md` com credor.
- **A rotação do segredo dos `slot_id`.** `lerSlotId` aceita um segredo e uma
  versão; no instante em que o segredo rodar, os *token* em voo deixam de
  verificar. A versão está no corpo para que um anel seja possível, e o anel é
  do KAM-010.
