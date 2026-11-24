"""Idempotencia do painel na base: a chave do PATCH dos produtos, por tenant (KAM-240).

A primeira linha e **sem acentos**, pela razao das revisoes anteriores: e a
mensagem que o `alembic history` imprime.

## Para que serve

A `Idempotency-Key` do `PATCH /painel/produtos/:id` (KAM-099, criterio 5) vivia
num mapa do processo do `onboarding-web`: um reinicio ou uma segunda replica
perdiam-na, e a repeticao da mesma chave chegava ao COM, que a recusava pela
versao (`409`) sobre um preco que tinha ficado gravado. Esta revisao da-lhe
onde viver, com o `kamba_app` e sob a RLS do tenant da sessao do painel.

| Objecto | Para que serve |
|---|---|
| `platform.painel_idempotencia` | a chave, a impressao do pedido e a resposta, por tenant |

## A linha e a tranca

A chave primaria e natural e composta, `(tenant_id, chave)`, como a
`order_intents`: um `uuid` gerado ao lado era uma chave que nao impede a segunda
reserva da mesma chave. O adaptador (`services/onboarding-web/src/painel/
idempotencia_sql.ts`) reserva a linha com `INSERT ... ON CONFLICT` numa
transaccao que fica aberta durante o PATCH ao COM, e grava a resposta na mesma
transaccao: um segundo pedido com a mesma chave **espera no indice** e le a
resposta confirmada, ou reserva ele se a primeira desfez. Por isso uma linha
confirmada tem sempre resposta, e o `estado` e o `corpo` so sao nulos dentro da
transaccao que reserva (`painel_idempotencia_resposta_ck`, que os quer juntos).
Se a ligacao de quem reservou cai com o processo vivo, a tranca solta-se e o
PATCH dele nao e cancelado: quem impede a segunda gravacao e a versao do pedido
no COM (ver a nota do adaptador).

A impressao e o SHA-256 do pedido (o `sku` e o corpo canonico), e nao o corpo:
o que a linha guarda e o estado HTTP e o corpo da resposta, que e a oferta do
COM (sku, nome, preco, versao) — **sem pessoa**. O corpo e `json` e nao `jsonb`:
a repeticao devolve o texto como saiu, com as chaves na mesma ordem, e nenhuma
consulta le dentro dele.

## A retencao (decisao da coordenacao do lote 19, 2026-11-22)

A chave vale 24 h (`VALIDADE_DA_CHAVE_MS`, a proposta do KAM-099). O `kamba_app`
nao apaga linhas (dicionario §2): uma chave vencida e ainda por purgar
reaproveita-se pelo `DO UPDATE ... WHERE expira_at <= now()`, que recomeca o
`criado_at`, e **quem apaga e o executor da retencao**, como `kamba_batch`, na
classe `idempotencia_do_painel` (25 h sobre o `criado_at`), pela forma dos
contadores da `0084`. Recusadas: 1 h (o dono que repete depois de uma hora sem
rede recebia um `409`) e fora da retencao (contradiz o criterio 1 do bloco).

## O `downgrade`

Larga a tabela, sem `CASCADE`.

## Numero

`0089`, sobre a `0088` do KAM-209: a vaga que a coordenacao do lote 19 deu ao
KAM-240 a 2026-11-22.
"""

from __future__ import annotations

from alembic import op

import rls

revision = "0089"
down_revision = "0088"
branch_labels = None
depends_on = None

IDEMPOTENCIA = "platform.painel_idempotencia"

#: A forma de uma chave. Igual ao `FORMA_DA_CHAVE` de
#: `services/onboarding-web/src/painel/idempotencia.ts`, que a rota valida.
FORMA_DA_CHAVE = "'^[A-Za-z0-9_.:-]{16,128}$'"

#: O que o `kamba_app` insere numa reserva.
INSERT_DA_IDEMPOTENCIA = ("tenant_id", "chave", "impressao", "criado_at", "expira_at")
#: O que muda: a resposta, e a reserva de uma chave vencida.
UPDATE_DA_IDEMPOTENCIA = ("impressao", "estado", "corpo", "criado_at", "expira_at")


def upgrade() -> None:
    op.execute(
        f"""
        CREATE TABLE {IDEMPOTENCIA} (
          tenant_id   uuid NOT NULL,
          chave       text NOT NULL
                      CONSTRAINT painel_idempotencia_chave_ck CHECK (chave ~ {FORMA_DA_CHAVE}),
          impressao   bytea NOT NULL
                      CONSTRAINT painel_idempotencia_impressao_ck CHECK (octet_length(impressao) = 32),
          estado      smallint
                      CONSTRAINT painel_idempotencia_estado_ck CHECK (estado BETWEEN 100 AND 499),
          corpo       json,
          criado_at   timestamptz NOT NULL DEFAULT now(),
          expira_at   timestamptz NOT NULL,
          CONSTRAINT painel_idempotencia_pkey PRIMARY KEY (tenant_id, chave),
          -- A resposta vai inteira ou nao vai.
          CONSTRAINT painel_idempotencia_resposta_ck CHECK ((estado IS NULL) = (corpo IS NULL)),
          CONSTRAINT painel_idempotencia_prazo_ck CHECK (expira_at > criado_at)
        )
        """
    )
    op.execute(
        f"CREATE INDEX painel_idempotencia_criado_idx ON {IDEMPOTENCIA} (criado_at)"
    )
    op.execute(
        f"COMMENT ON TABLE {IDEMPOTENCIA} IS "
        "'A Idempotency-Key do PATCH dos produtos do painel (KAM-240), por tenant: a impressao "
        "do pedido e a resposta. Sem DELETE para o kamba_app; a purga e da retencao.'"
    )
    rls.enable_tenant_rls("painel_idempotencia")
    op.execute(f"REVOKE ALL ON {IDEMPOTENCIA} FROM PUBLIC")
    op.execute(
        f"GRANT SELECT, INSERT ({', '.join(INSERT_DA_IDEMPOTENCIA)}), "
        f"UPDATE ({', '.join(UPDATE_DA_IDEMPOTENCIA)}) ON {IDEMPOTENCIA} TO kamba_app"
    )
    # A purga das chaves vencidas e do executor da retencao, que corre como lote.
    op.execute(f"GRANT SELECT, DELETE ON {IDEMPOTENCIA} TO kamba_batch")


def downgrade() -> None:
    rls.disable_tenant_rls("painel_idempotencia")
    op.execute(f"DROP TABLE {IDEMPOTENCIA}")
