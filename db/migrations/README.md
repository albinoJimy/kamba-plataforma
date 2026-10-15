# Migrações

Directório reservado pelo **KAM-001**; o conteúdo é do **KAM-003**.

As migrações do schema `platform` correm por **Alembic**; as do Medusa são do
próprio Medusa (`docs/tecnica/09` §7). O padrão é **expand/contract**: acrescentar,
migrar dados, remover só numa versão posterior. Cada migração tem `down` ou é
marcada *expand-only*, e o teste de subir/descer é o *gate* 8 (`make ci-8`).

O que o KAM-001 cria e que já se aplica aqui: o compose de desenvolvimento
levanta o PostgreSQL 18.6 com `vector` e `pg_trgm` activos e as três bases
(`kamba_platform`, `kamba_medusa`, `kamba_chatwoot`) criadas vazias — ver
`infra/compose/postgres/initdb/`. Não há uma única tabela, de propósito.

## Como se usa

Tudo a partir de `db/`, com a ligação configurada **só pelo ambiente** — não há
URL no `alembic.ini`, porque conteria uma palavra-passe.

```bash
python bootstrap.py                                        # como admin: cria os cinco papéis
python -m alembic -c migrations/alembic.ini upgrade head   # como kamba_migrator
python -m alembic -c migrations/alembic.ini downgrade base
```

| Variável | Para quê |
|---|---|
| `KAMBA_DB_HOST`, `KAMBA_DB_PORT` | Onde está a base (omissão `127.0.0.1:5432`) |
| `KAMBA_DB_NAME` | **Sem omissão**, de propósito |
| `POSTGRES_USER`, `POSTGRES_PASSWORD` | O admin da instância; só o `bootstrap.py` o usa |
| `KAMBA_SECRET_DB_MIGRATOR_PASSWORD` | `kamba_migrator` — DDL, dono das tabelas |
| `KAMBA_SECRET_DB_APP_PASSWORD` | `kamba_app` — `NOBYPASSRLS`, sem DDL |
| `KAMBA_SECRET_DB_BATCH_PASSWORD` | `kamba_batch` — `BYPASSRLS`, auditado |
| `KAMBA_SECRET_DB_RESOLVER_PASSWORD` | `kamba_resolver` — leitura estreita, antes de haver contexto (KAM-004) |
| `KAMBA_SECRET_DB_IDENTITY_PASSWORD` | `kamba_identity` — o único que lê `contact_endpoints` e `contact_deks` (KAM-008) |
| `KAMBA_DOWNGRADE_0003_COPIA` | Só no `downgrade` da `0003` com linhas de identidade: o ficheiro **novo** onde fica a cópia lógica |

Os nomes das cinco palavras-passe dos papéis são os que o `EnvProvider` do KAM-010 lê
(`KAMBA_SECRET_` + `id` do `ops/secrets-inventory.yaml`).

**Os papéis não são uma revisão**, e o `downgrade base` não os remove: são
globais à instância e têm de existir antes de o Alembic correr como
`kamba_migrator`. Vivem em `bootstrap.py`, que é idempotente e repõe os
atributos se alguém os tiver alterado à mão.

**A tabela `alembic_version` vive em `public`**, não em `platform`: o
`downgrade base` apaga o schema, e o Alembic escreve a versão depois disso.

**Uma revisão por PR**, com `upgrade` e `downgrade`. Prova-se com
`make ci-8` — ver `docs/ci.md` §3, *gate* 8.

**Uma tabela com `tenant_id` chama `rls.enable_tenant_rls`** na revisão que a cria
(e `disable_tenant_rls` no `downgrade`). O gate 6 falha se alguma não o fizer —
ver `docs/isolamento.md` §6, que lista os três passos de quem acrescenta uma tabela.

**O `bootstrap.py` corre antes de cada `upgrade` que introduza um papel.** A
revisão `0002` concede privilégios a `kamba_resolver`; numa base que esteja em
`0001` com os três papéis do KAM-003, o `upgrade` falha com «role does not
exist» até o `bootstrap.py` ser corrido de novo. É idempotente: corre-se sempre.
A `0003` faz o mesmo com `kamba_identity`.

**O `downgrade` da `0003` não apaga identidade em silêncio.** Apaga
`contact_endpoints`, `contact_deks`, `contacts` e `hmac_key_versions` — BSUID e
telefone cifrados que não se voltam a obter — e anula `tenants.owner_contact_id`,
que sem `contacts` ficava a apontar para nada. Com linhas em qualquer das quatro
tabelas, ou com algum tenant com dono, recusa-se a correr até
`KAMBA_DOWNGRADE_0003_COPIA` apontar para um ficheiro que ainda não exista, onde
escreve todas as linhas e os pares tenant–dono (uma por linha de JSON, os
`bytea` em base64, pela ordem em que se repõem) antes de apagar. O ficheiro não tem nada em claro que a base não tivesse, mas é dado
pessoal: guarda-se como tal. Repor as linhas a partir dele é um `INSERT` por
linha, como administrador, depois de voltar a subir — o gate 8 fá-lo e compara
octeto a octeto; não há ferramenta de reposição.

**O `upgrade` da `0003` falha com um `owner_contact_id` órfão.** Até aqui a
coluna não tinha FK nem tabela para onde apontar: qualquer valor não nulo é
órfão, e a revisão recusa-o em vez de o deixar debaixo de uma FK. Limpe-se a
coluna (ou crie-se o contacto) antes de subir.

**Privilégios: tabela a tabela, e coluna a coluna onde importa.** `kamba_app`
tem `SELECT` e `INSERT`, `UPDATE` por coluna e **nenhum `DELETE`**. Uma revisão
que crie uma tabela diz o que concede — não há `ALTER DEFAULT PRIVILEGES`, e há
um teste que o confirma. Quem acrescentar uma coluna tem de a declarar em
`db/tests/test_inventario.py`, com a resposta a «guarda dados pessoais?», e de
decidir se `kamba_app` a pode alterar (`db/tests/test_privilegios.py`).

**Os papéis são globais à instância.** O `bootstrap.py` redefine as três
palavras-passe para as do ambiente, sempre. Corrê-lo contra uma instância que
outros serviços usam troca-lhes as credenciais.

> **O que falta, e de quem é.** Não há ainda forma de aplicar as migrações ao
> PostgreSQL do compose de desenvolvimento: a rede de dados é interna e não
> publica portas, pelo que o Alembic teria de correr num contentor dentro dela.
> É infra-estrutura de ambiente (KAM-075), e o KAM-003 não a entrega.

## Revisões

| Revisão | Ticket | O que faz |
|---|---|---|
| `0001` | KAM-003 | Schema `platform`: `tenants`, `tenant_channels`, `entitlements`, e os privilégios de `kamba_app` e `kamba_batch` |
| `0002` | KAM-004 | RLS `FORCE` e política `tenant_iso` nas três tabelas; política e colunas do `kamba_resolver` |

## O que vem a seguir

| Ticket | O que traz para aqui |
|---|---|
| KAM-003 | Schema `platform`: `tenants`, `entitlements`, `tenant_channels`, migrações reversíveis |
| KAM-004 | RLS `FORCE` por `app.tenant_id` e suite de isolamento SQL |
| KAM-005 | Outbox transaccional |
| KAM-012 | `audit_log` append-only |
