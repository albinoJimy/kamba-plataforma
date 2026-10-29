"""Esquema servicos: servicos, recursos, disponibilidade e marcacoes (KAM-047).

A primeira linha e **sem acentos**, como as vinte e quatro revisoes anteriores:
e a mensagem que o `alembic history` imprime, e o
`test_no_processo_e_pela_linha_de_comandos_o_alembic_diz_o_mesmo` compara a
saida no processo com a do executavel. Com acentos, as duas divergem na
codificacao.

Quatro tabelas num esquema proprio, pela proposta de `docs/tecnica/02` §8.3 que
este ticket ratifica em `docs/tecnica/03`:

    servicos.services            o que se marca: duracao e preco
    servicos.resources           quem ou o que executa (profissional, sala, mesa)
    servicos.availability_rules  a grelha semanal de cada recurso
    servicos.bookings            o hold e a marcacao

## A barreira do criterio 1 e uma restricao da base, e nao codigo

«1.000 tentativas concorrentes de reservar/marcar o mesmo recurso e intervalo
produzem **1** marcacao e as restantes `SLOT_TAKEN` (garantido por restricao de
exclusao na BD, nao por codigo aplicacional).» A letra importa: um
`SELECT ... FOR UPDATE` seguido de `INSERT` **nao** cumpre o criterio, e nao e
equivalente — entre os dois cabe outra transaccao, e o que o impediria era o
bloqueio e nao a restricao. O que esta aqui e:

    EXCLUDE USING gist (tenant_id WITH =, resource_id WITH =,
                        tstzrange(inicio_at, fim_at) WITH &&)
      WHERE (estado IN ('hold','confirmada'))

Tres propriedades, as tres medidas contra o PostgreSQL 18.6 da imagem fixada
(`docs/evidencia/KAM-047-servicos.md` §1):

- **`tenant_id WITH =` nao e enfeite.** Sem ele, o recurso de um tenant
  bloqueava o intervalo de outro — e, pior, a mensagem de conflito do PostgreSQL
  **cita a chave em conflito**, o que fazia da restricao um canal de leitura
  entre vizinhos. Com ele, dois tenants com o mesmo `resource_id` e o mesmo
  intervalo entram os dois (medido).
- **O predicado parcial e o que deixa cancelar e remarcar.** Uma marcacao
  `cancelada` ou `expirada` nao ocupa nada: sai do indice e o intervalo volta a
  estar livre **na mesma transaccao**, sem apagar linha nenhuma. Sem o
  predicado, cancelar obrigava a `DELETE` e o historico desaparecia.
- **`tstzrange` e `[)`.** Duas marcacoes adjacentes — a segunda a comecar no
  instante em que a primeira acaba — **nao** se sobrepoem (medido). Com `[]` nao
  havia grelha de horas possivel.

A restricao e **mais forte do que a RLS**, e isso e deliberado: uma restricao
de exclusao e verificada sobre **todas** as linhas da tabela, nao sobre as que a
politica deixa ver. Um `kamba_app` com contexto do tenant A nao ve as linhas de
B *e* continua impedido de criar um conflito dentro de A, mesmo com linhas que a
sua propria transaccao nao le.

## `btree_gist` existe na imagem fixada, e o `kamba_migrator` pode instala-la

O ticket manda **validar** em vez de assumir, e foi validado (gate 8 e
`docs/evidencia/KAM-047-servicos.md` §1):

    btree_gist 1.8 em PostgreSQL 18.6 (Debian 18.6-1.pgdg12+2),
    pgvector/pgvector:0.8.7-pg18@sha256:2358fcba...7e2bc11

O `tstzrange ... WITH &&` nao precisa de extensao nenhuma (`range_ops` e
nativo); o que precisa dela e o `uuid WITH =` dentro de um indice GiST, que vem
do `gist_uuid_ops` do `btree_gist`.

**Instala-se nesta revisao, e nao no `initdb`.** O
`infra/compose/postgres/initdb/01-bases-e-extensoes.sql` so corre no compose de
desenvolvimento, e o contentor do gate 8 **nao o monta**: uma extensao criada la
deixava a suite a falhar no CI com a revisao verde na maquina de quem a
escreveu. O `bootstrap.py` tambem nao serve — ele cria papeis, e uma extensao
criada fora da cadeia nao desaparece no `downgrade`.

E o `kamba_migrator` e `NOSUPERUSER`. Instala-a porque o
`btree_gist.control` da imagem diz `trusted = true`, o que desde o PostgreSQL 13
dispensa superutilizador a quem tenha `CREATE` no esquema de destino — e ele tem,
porque e ele que cria o `servicos` na linha acima. Medido com o papel verdadeiro
e `NOSUPERUSER` confirmado pelo `pg_roles`.

**Vai para dentro do `servicos` e nao para o `public`.** Duas razoes: o
`kamba_migrator` nao tem `CREATE` no `public` (a `0001` revoga-o), e no
`servicos` o `DROP EXTENSION` do `downgrade` cai junto com o resto do esquema em
vez de deixar uma extensao orfa numa base que desceu. O `search_path` da
transaccao e fixado antes do `CREATE TABLE` para que o `gist_uuid_ops` resolva
onde esta, e nao por sorte do `search_path` de quem corre a migracao.

## Os nomes sao os do dicionario, e dois diferem do DDL do bloco

O bloco do ticket escreve `id`, `inicio`, `fim` e `preco_modo`. Nenhum dos
quatro e canonico, e o dicionario esta acima do ticket na ordem de fontes:

    bloco KAM-047        dicionario §3.3 / contrato v1    o que esta aqui
    id                   bookings(booking_id, ...)        booking_id
    inicio / fim         inicio_at / fim_at               inicio_at / fim_at
    preco_modo           preco_tipo (`preco_modo` e        preco_tipo
                         variante substituida, 1.12)

As duas primeiras sao tambem o que o `contratos/eventos/booking.created/
v1.schema.json` **ja publicado** exige no payload (`booking_id`, `contact_id`,
`service_id`, `resource_id`, `inicio_at`, `fim_at`, `additionalProperties:
false`): escrever `inicio` na coluna obrigava a traduzir no caminho do evento, e
e nessa traducao que os nomes divergem. A divergencia fica registada na emenda
do dicionario e em `docs/dividas-documentais.md`.

## As FK nao saem do esquema, e nenhuma apaga em cascata

As duas FK de `bookings` apontam para `services` e `resources`, dentro do
`servicos`, e as duas sao **compostas com o `tenant_id`** — a forma que a `0009`
fixou e as revisoes seguintes repetiram. Nao ha FK para `platform.tenants` nem
para `platform.contacts`, e isso e uma regra do inventario (`test_catalogo`:
«sem FK para fora do esquema») antes de ser uma escolha: o `servicos` e acedido
so pela TLS e o `contact_id` entra como referencia opaca, do mesmo modo que o
`agregado_id` das tabelas de eventos.

Sem `ON DELETE CASCADE`, como todas: apagar um recurso nao pode apagar em
silencio as marcacoes que alguem tem com ele.

## O TTL do hold e *proposta*, e a libertacao e um varrimento

`hold_expires_at` guarda o instante; os 10 minutos sao **proposta a calibrar**
(ticket, criterio 3) e **nao estao aqui**: quem os escolhe e o modulo
(`TTL_DO_HOLD_MS` em `services/com/src/servicos/contrato.ts`), porque um numero
no DDL obrigava a uma revisao de base de dados para o calibrar — o argumento que
a `0023` escreveu para o `modelo`.

A libertacao e a funcao `servicos.expirar_holds`, `SECURITY INVOKER`: corre com
a RLS e os privilegios de quem chama, e e `kamba_app` quem a chama, com contexto
de tenant, porque e **ele** — e nao o `kamba_batch` — que tem `EXECUTE` em
`platform.evt_emitir` (`0004`). Emite `booking.cancelled` com
`motivo = 'hold_expirado'`, que e o tipo que o catalogo dos 38 do dicionario
§3.5 ja tem e cujo contrato v1 pede exactamente `{booking_id, motivo}` — e nao
um tipo novo, que seria escopo a mais por um evento que o conjunto ja nomeia.
"""

from __future__ import annotations

from alembic import op

import rls

revision = "0025"
down_revision = "0024"
branch_labels = None
depends_on = None

#: Literais e nao f-strings sobre outras constantes: o *gate* 3b le o AST da
#: revisao sem a executar e resolve `f"..."` sobre constantes de modulo, mas nao
#: sobre constantes que sejam elas proprias f-strings. A `0023` pagou nove
#: `op.execute` lidos como `[ilegivel]` para aprender isto.
ESQUEMA = "servicos"
SERVICES = "servicos.services"
RESOURCES = "servicos.resources"
AVAILABILITY = "servicos.availability_rules"
BOOKINGS = "servicos.bookings"

#: Os quatro estados de uma marcacao (dicionario §3.3, emenda desta revisao).
#: Ja entre apostrofos, pela razao da `0015`: e a unica forma que o *gate* 3b
#: resolve, porque segue `", ".join(<constante de modulo>)` dentro de uma
#: f-string.
ESTADOS = ("'hold'", "'confirmada'", "'cancelada'", "'expirada'")

#: Os dois estados que **ocupam** o intervalo, e por isso o predicado da
#: restricao de exclusao. Fora deles a linha fica no historico e nao bloqueia
#: ninguem.
ESTADOS_ACTIVOS = ("'hold'", "'confirmada'")

#: O dominio de `preco_tipo` do dicionario §3.3. **`preco_tipo` e nao
#: `preco_modo`**: ver a nota do modulo.
PRECO_TIPOS = ("'fixo'", "'a_partir_de'", "'sob_consulta'")

#: `currency` ∈ {`AOA`} (dicionario §3.4, emenda 1.13). Dominio de um valor: a
#: plataforma e de Angola, e alarga-lo e emenda e nao `ALTER`.
MOEDAS = ("'AOA'",)

PAPEL_DA_APP = "kamba_app"
PAPEL_DE_LOTE = "kamba_batch"

#: O que o `kamba_app` pode alterar em `bookings`, coluna a coluna. **Nao inclui
#: `tenant_id`, `contact_id`, `service_id`, `resource_id`, `slot_id` nem
#: `hold_id`**: mudar qualquer um deles era transformar a marcacao de um
#: contacto na marcacao de outro, ou reescrever a chave de idempotencia de uma
#: confirmacao alheia. O `inicio_at`/`fim_at` tambem nao: remarcar e cancelar
#: **e** inserir (ver `rescheduleBooking`), e um `UPDATE` do intervalo escapava
#: a restricao de exclusao da linha antiga para a nova sem passar pelo conflito.
UPDATE_DA_APP_EM_BOOKINGS = ("estado", "hold_expires_at", "version")


def upgrade() -> None:
    # Sem `IF NOT EXISTS`, como a `0001`, a `0020` e a `0023`: se o esquema ja
    # existir, alguem o criou fora da cadeia e isso e para saber, nao para
    # tolerar.
    op.execute(f"CREATE SCHEMA {ESQUEMA}")
    op.execute(
        f"COMMENT ON SCHEMA {ESQUEMA} IS "
        "'Agenda da vertical Servicos (KAM-047): servicos, recursos, "
        "disponibilidade e marcacoes. Acedido so pela TLS. RLS FORCE em todas "
        "as tabelas. Dicionario 3.3 e 3.6; docs/tecnica/03 secao 5.7.'"
    )

    # A extensao vai para dentro do esquema, e o `search_path` da transaccao
    # passa a inclui-lo: sem isto, o `gist_uuid_ops` da restricao de exclusao
    # resolvia-se pelo `search_path` de quem corre a migracao, que nao e desta
    # revisao e pode mudar. `SET LOCAL` e nao `SET`: morre com a transaccao, e o
    # `env.py` corre uma transaccao por revisao (`transaction_per_migration`).
    op.execute(f"CREATE EXTENSION btree_gist SCHEMA {ESQUEMA}")
    op.execute(f"SET LOCAL search_path = {ESQUEMA}, pg_catalog")

    _servicos()
    _recursos()
    _disponibilidade()
    _marcacoes()
    _expiracao()
    _rls()
    _privilegios()

    op.execute("RESET search_path")


def _servicos() -> None:
    """O que se marca. O preco segue o modo opaco de KAM-043."""
    op.execute(
        f"""
        CREATE TABLE {SERVICES} (
            service_id   uuid        NOT NULL DEFAULT gen_random_uuid(),
            tenant_id    uuid        NOT NULL,
            nome         text        NOT NULL,
            duracao_min  integer     NOT NULL,
            preco_tipo   text        NOT NULL,
            -- Nulo quando `sob_consulta`, e **so** nesse caso: ver o `CHECK`
            -- abaixo. Unidade menor inteira (dicionario secao 2), nunca
            -- virgula flutuante.
            preco_minor  bigint,
            currency     text        NOT NULL DEFAULT 'AOA',
            ativo        boolean     NOT NULL DEFAULT true,
            criado_at    timestamptz NOT NULL DEFAULT now(),
            CONSTRAINT services_pkey PRIMARY KEY (service_id),
            -- A FK composta de `bookings` precisa de um indice unico que
            -- comece pelo `tenant_id`; e a mesma forma da
            -- `tenant_channels_tenant_id_uq` que a `0009` acrescentou para
            -- isto. Serve tambem as consultas, que filtram sempre por tenant.
            CONSTRAINT services_tenant_uq UNIQUE (tenant_id, service_id),
            CONSTRAINT services_nome_ck CHECK (btrim(nome) <> ''),
            -- Uma duracao de zero minutos nao e um servico, e uma negativa
            -- inverteria o `fim_at` calculado a partir dela.
            CONSTRAINT services_duracao_ck CHECK (duracao_min > 0),
            CONSTRAINT services_preco_tipo_ck
                CHECK (preco_tipo IN ({", ".join(PRECO_TIPOS)})),
            CONSTRAINT services_currency_ck
                CHECK (currency IN ({", ".join(MOEDAS)})),
            -- **A equivalencia nos dois sentidos, e nao so num.** Um
            -- `sob_consulta` com preco afirmava um numero que ninguem cotou, e
            -- um `fixo` sem preco deixava o agente sem *fact* para citar — e e
            -- o segundo que faz falta mais vezes.
            CONSTRAINT services_preco_ck CHECK (
                (preco_tipo = 'sob_consulta') = (preco_minor IS NULL)
            ),
            CONSTRAINT services_preco_nao_negativo_ck
                CHECK (preco_minor IS NULL OR preco_minor >= 0)
        )
        """
    )
    op.execute(
        f"COMMENT ON TABLE {SERVICES} IS "
        "'Servicos marcaveis de um tenant (KAM-047). O preco segue o modo "
        "opaco de KAM-043: `preco_tipo` decide se ha numero para citar.'"
    )
    op.execute(f"CREATE INDEX services_tenant_ativo_idx ON {SERVICES} (tenant_id, ativo)")


def _recursos() -> None:
    """Quem ou o que executa o servico. E aqui que a sobreposicao se mede."""
    op.execute(
        f"""
        CREATE TABLE {RESOURCES} (
            resource_id  uuid        NOT NULL DEFAULT gen_random_uuid(),
            tenant_id    uuid        NOT NULL,
            -- Nome do recurso — um profissional, uma sala, uma mesa. Quando e
            -- uma pessoa, e o **nome de trabalho** que a PME escreve no
            -- onboarding e mostra ao cliente, nao um dado de identificacao:
            -- nao ha telefone, BI nem morada nesta tabela, e o
            -- `test_inventario` responde a pergunta coluna a coluna.
            nome         text        NOT NULL,
            ativo        boolean     NOT NULL DEFAULT true,
            criado_at    timestamptz NOT NULL DEFAULT now(),
            CONSTRAINT resources_pkey PRIMARY KEY (resource_id),
            CONSTRAINT resources_tenant_uq UNIQUE (tenant_id, resource_id),
            CONSTRAINT resources_nome_ck CHECK (btrim(nome) <> '')
        )
        """
    )
    op.execute(
        f"COMMENT ON TABLE {RESOURCES} IS "
        "'Recursos que executam servicos (KAM-047). A restricao de exclusao de "
        "servicos.bookings e por (tenant_id, resource_id, intervalo).'"
    )
    op.execute(
        f"CREATE INDEX resources_tenant_ativo_idx ON {RESOURCES} (tenant_id, ativo)"
    )


def _disponibilidade() -> None:
    """A grelha semanal. O modelo nunca calcula horas livres (ADR-007)."""
    op.execute(
        f"""
        CREATE TABLE {AVAILABILITY} (
            rule_id      uuid        NOT NULL DEFAULT gen_random_uuid(),
            tenant_id    uuid        NOT NULL,
            resource_id  uuid        NOT NULL,
            -- `0` = domingo, como o `EXTRACT(dow)` do PostgreSQL. A escolha e
            -- a do motor e nao a da ISO-8601 (que poe a semana a comecar na
            -- segunda e numera de 1 a 7) porque o calculo da disponibilidade e
            -- uma consulta: com a convencao da ISO, cada consulta levava uma
            -- conversao, e e nessas conversoes que um domingo se torna segunda.
            dia_semana   smallint    NOT NULL,
            -- `time` e nao `timestamptz`: uma regra e «as tercas, das 9 as 17»
            -- e nao um instante. O instante nasce da juncao da regra com um
            -- dia, no fuso da coluna abaixo.
            inicio       time        NOT NULL,
            fim          time        NOT NULL,
            -- O fuso em que a regra se le. Omissao `Africa/Luanda`
            -- (dicionario secao 2: armazenamento em UTC, apresentacao em
            -- Africa/Luanda). Validado contra o catalogo do servidor pelo
            -- *trigger* `availability_rules_fuso_valido`, e nao contra uma
            -- lista escrita a mao que envelhecia a cada actualizacao de
            -- `tzdata`. **Nao e um `CHECK`**, e a razao mediu-se: um
            -- `CHECK (EXISTS (SELECT 1 FROM pg_timezone_names ...))` e recusado
            -- pelo PostgreSQL com `0A000 cannot use subquery in check
            -- constraint`. Ver `_fuso_valido`.
            fuso         text        NOT NULL DEFAULT 'Africa/Luanda',
            criado_at    timestamptz NOT NULL DEFAULT now(),
            CONSTRAINT availability_rules_pkey PRIMARY KEY (rule_id),
            CONSTRAINT availability_rules_tenant_uq UNIQUE (tenant_id, rule_id),
            CONSTRAINT availability_rules_recurso_fk
                FOREIGN KEY (tenant_id, resource_id)
                REFERENCES servicos.resources (tenant_id, resource_id),
            CONSTRAINT availability_rules_dia_ck
                CHECK (dia_semana BETWEEN 0 AND 6),
            -- **Estrito, e nao `<=`.** Uma regra com `inicio = fim` e uma
            -- janela de zero minutos: nao produz slot nenhum e faz o dono
            -- pensar que marcou disponibilidade quando nao marcou.
            CONSTRAINT availability_rules_janela_ck CHECK (inicio < fim),
            CONSTRAINT availability_rules_fuso_ck CHECK (btrim(fuso) <> '')
        )
        """
    )
    _fuso_valido()
    op.execute(
        f"COMMENT ON TABLE {AVAILABILITY} IS "
        "'Grelha semanal de disponibilidade por recurso (KAM-047). "
        "Disponibilidade = estas regras menos as marcacoes activas; o modelo "
        "nunca calcula horas livres (ADR-007).'"
    )
    op.execute(
        f"CREATE INDEX availability_rules_recurso_idx ON {AVAILABILITY} "
        "(tenant_id, resource_id, dia_semana)"
    )


def _fuso_valido() -> None:
    """O fuso de uma regra existe no catalogo do servidor, por *trigger*.

    **E um *trigger* e nao um `CHECK` porque o PostgreSQL recusa o `CHECK`.** A
    primeira versao desta revisao escreveu
    `CHECK (EXISTS (SELECT 1 FROM pg_timezone_names WHERE name = fuso))` e o
    `upgrade` morreu com `0A000 cannot use subquery in check constraint` — um
    `CHECK` tem de ser uma expressao sobre a propria linha, e o catalogo de
    fusos e uma tabela. Medido, nao inferido.

    **E nao e uma lista escrita a mao**, que era a outra saida: `tzdata`
    actualiza-se, e uma lista literal transformava uma invariante num numero que
    envelhece. A pergunta «este fuso existe?» tem uma fonte, e e o servidor.

    O que isto impede: um `fuso` com uma gralha — `Africa/Luanda ` com espaco,
    `Africa/Luana`, `WAT` — nao falha na escrita; falha na **leitura**, quando o
    calculo da disponibilidade fizer `AT TIME ZONE fuso` e o PostgreSQL
    levantar. Um dono que escreve a agenda uma vez e descobre o erro no primeiro
    cliente que pede horas e o caso que este *trigger* fecha.

    `SECURITY INVOKER` (a omissao): nao precisa de privilegio nenhum para
    recusar.
    """
    op.execute(
        """
        CREATE FUNCTION servicos.validar_fuso() RETURNS trigger
        LANGUAGE plpgsql AS $func$
        BEGIN
          IF NOT EXISTS (
            SELECT 1 FROM pg_timezone_names WHERE name = NEW.fuso
          ) THEN
            RAISE EXCEPTION
              'servicos.availability_rules: fuso desconhecido no servidor: %',
              NEW.fuso
              USING ERRCODE = 'invalid_parameter_value';
          END IF;
          RETURN NEW;
        END $func$
        """
    )
    op.execute(
        "COMMENT ON FUNCTION servicos.validar_fuso() IS "
        "'Recusa um fuso que nao exista em pg_timezone_names (KAM-047). "
        "Trigger e nao CHECK: um CHECK nao aceita subconsulta (0A000).'"
    )
    op.execute(
        """
        CREATE TRIGGER availability_rules_fuso_valido
          BEFORE INSERT OR UPDATE OF fuso ON servicos.availability_rules
          FOR EACH ROW EXECUTE FUNCTION servicos.validar_fuso()
        """
    )
    # `ENABLE ALWAYS` pela razao da `0023`: um *trigger* que e barreira e nao
    # conveniencia tem de morder tambem quando a sessao e `replica`.
    op.execute(
        "ALTER TABLE servicos.availability_rules "
        "ENABLE ALWAYS TRIGGER availability_rules_fuso_valido"
    )
    op.execute("REVOKE ALL ON FUNCTION servicos.validar_fuso() FROM PUBLIC")


def _marcacoes() -> None:
    """O hold e a marcacao. A restricao de exclusao e o criterio 1."""
    op.execute(
        f"""
        CREATE TABLE {BOOKINGS} (
            booking_id       uuid        NOT NULL DEFAULT gen_random_uuid(),
            tenant_id        uuid        NOT NULL,
            -- Referencia opaca a `platform.contacts`, **sem FK**: ver a nota do
            -- modulo. Nunca um telefone (ADR-010).
            contact_id       uuid        NOT NULL,
            service_id       uuid        NOT NULL,
            resource_id      uuid        NOT NULL,
            -- O token opaco do *slot* que o `getAvailability` ofereceu. Entra
            -- aqui porque o criterio 4 pede idempotencia por
            -- `(contact_id, slot_id)`, e sem a coluna essa chave nao existia na
            -- base — ficava a ser uma inferencia do codigo sobre o intervalo.
            -- A forma e *proposta* e esta em `servicos/slots.ts`.
            slot_id          text        NOT NULL,
            -- O identificador que vai no botao `confirm:{{hold_id}}`
            -- (dicionario secao 3.3). Separado do `booking_id` de proposito: e
            -- ele que sai para o cliente, e o `booking_id` e interno.
            hold_id          uuid        NOT NULL DEFAULT gen_random_uuid(),
            inicio_at        timestamptz NOT NULL,
            fim_at           timestamptz NOT NULL,
            estado           text        NOT NULL,
            -- Nao nulo **se e so se** o estado e `hold`: ver o `CHECK`. Um hold
            -- sem prazo nunca expirava e ocupava o intervalo para sempre. A
            -- equivalencia nos dois sentidos — e nao so a metade que falta
            -- fazer — e o que torna «tem prazo» e «e um hold» o **mesmo
            -- facto**: nenhum codigo pode ler um e querer dizer o outro, e nao
            -- fica um prazo esquecido numa marcacao confirmada a sugerir que
            -- ela ainda e provisoria.
            hold_expires_at  timestamptz,
            version          integer     NOT NULL DEFAULT 1,
            criado_at        timestamptz NOT NULL DEFAULT now(),
            CONSTRAINT bookings_pkey PRIMARY KEY (booking_id),
            CONSTRAINT bookings_servico_fk
                FOREIGN KEY (tenant_id, service_id)
                REFERENCES servicos.services (tenant_id, service_id),
            CONSTRAINT bookings_recurso_fk
                FOREIGN KEY (tenant_id, resource_id)
                REFERENCES servicos.resources (tenant_id, resource_id),
            CONSTRAINT bookings_estado_ck
                CHECK (estado IN ({", ".join(ESTADOS)})),
            CONSTRAINT bookings_intervalo_ck CHECK (inicio_at < fim_at),
            CONSTRAINT bookings_hold_prazo_ck CHECK (
                (estado = 'hold') = (hold_expires_at IS NOT NULL)
            ),
            CONSTRAINT bookings_version_ck CHECK (version >= 1),
            CONSTRAINT bookings_slot_id_ck CHECK (btrim(slot_id) <> ''),
            -- O `hold_id` e unico por tenant: e por ele que o
            -- `confirmBooking` encontra a linha, e dois holds com o mesmo
            -- identificador faziam de «confirma o hold X» uma pergunta sem
            -- resposta unica.
            CONSTRAINT bookings_hold_id_uq UNIQUE (tenant_id, hold_id),
            -- **A restricao que e o criterio 1.** Ver a nota do modulo para as
            -- tres propriedades e o que cada parte impede.
            CONSTRAINT bookings_sem_sobreposicao
                EXCLUDE USING gist (
                    tenant_id WITH =,
                    resource_id WITH =,
                    tstzrange(inicio_at, fim_at) WITH &&
                ) WHERE (estado IN ({", ".join(ESTADOS_ACTIVOS)}))
        )
        """
    )
    op.execute(
        f"COMMENT ON TABLE {BOOKINGS} IS "
        "'Holds e marcacoes (KAM-047). A sobreposicao e impossivel por "
        "restricao de exclusao GiST sobre (tenant_id, resource_id, intervalo) "
        "nos estados hold e confirmada — nao por codigo aplicacional.'"
    )
    # A idempotencia de `confirmBooking` por `(contact_id, slot_id)`, no indice
    # e nao no codigo. **Parcial pelos mesmos dois estados da restricao de
    # exclusao**, e e isso que a torna correcta: depois de um hold expirar, o
    # mesmo contacto pode voltar a pedir o mesmo *slot* — e tem de poder, senao
    # o `HOLD_EXPIRED` do criterio 3 era um beco. Sem o indice, a leitura «ja
    # tenho marcacao para este slot?» podia devolver duas linhas e a resposta
    # idempotente dependia da ordem.
    op.execute(
        f"""
        CREATE UNIQUE INDEX bookings_contacto_slot_uq ON {BOOKINGS}
            (tenant_id, contact_id, slot_id)
            WHERE estado IN ({", ".join(ESTADOS_ACTIVOS)})
        """
    )
    # As duas consultas que isto serve: o calculo da disponibilidade («que
    # marcacoes activas tem este recurso nesta janela?») e o varrimento dos
    # holds vencidos. A primeira filtra por tenant, recurso e instante; o
    # `estado` entra no indice para o varrimento nao ler as confirmadas.
    op.execute(
        f"CREATE INDEX bookings_recurso_janela_idx ON {BOOKINGS} "
        "(tenant_id, resource_id, inicio_at) WHERE estado IN ('hold', 'confirmada')"
    )
    op.execute(
        f"CREATE INDEX bookings_hold_vencido_idx ON {BOOKINGS} "
        "(hold_expires_at) WHERE estado = 'hold'"
    )
    # O `getBooking` do contacto, e a leitura que o KAM-048 fara para o
    # lembrete. Filtra por tenant e contacto, e ordena pelo inicio.
    op.execute(
        f"CREATE INDEX bookings_contacto_idx ON {BOOKINGS} "
        "(tenant_id, contact_id, inicio_at)"
    )


def _expiracao() -> None:
    """`servicos.expirar_holds`: liberta o que venceu e emite o evento.

    `SECURITY INVOKER` — a omissao, e esta escrita por extenso porque importa:
    corre com a RLS **e** com os privilegios de quem chama. Chamada por
    `kamba_app` com contexto de tenant, so ve e so altera os holds desse
    tenant, e e ele quem tem `EXECUTE` em `platform.evt_emitir` (`0004`).

    Devolve o numero de holds libertados. Toma um tecto de linhas para que uma
    chamada nunca segure a transaccao de quem esta a marcar: o varrimento e
    oportunista e repete-se, nao e um `UPDATE` sobre a tabela inteira.

    **O `UPDATE` tem `estado = 'hold'` no `WHERE` e nao so o prazo.** Sem ele,
    uma linha ja expirada por outra chamada concorrente voltava a emitir o
    evento — e o criterio 2 do KAM-048 conta mensagens.

    **A selecao e uma CTE e nao um `IN (subconsulta)`, e isto foi medido.** A
    primeira versao escrevia
    `WHERE booking_id IN (SELECT ... LIMIT p_limite FOR UPDATE SKIP LOCKED)` e o
    tecto **nao era respeitado**: com cinco holds vencidos, `expirar_holds(2)`
    libertava os cinco. A razao e que um sublink nao correlacionado com `LIMIT` e
    `FOR UPDATE` nao e um valor calculado uma vez — o planeador pode reexecuta-lo
    por linha, e cada execucao devolve um conjunto diferente de dois. A CTE e
    avaliada **uma** vez, e o tecto volta a ser um tecto.

    Apanhado pelo `test_o_tecto_de_linhas_e_respeitado_e_o_varrimento_repete`, e
    nao por leitura: o SQL parecia certo.
    """
    op.execute(
        """
        CREATE FUNCTION servicos.expirar_holds(p_limite integer DEFAULT 100)
        RETURNS integer LANGUAGE plpgsql AS $func$
        DECLARE
          v_linha  record;
          v_total  integer := 0;
        BEGIN
          IF p_limite IS NULL OR p_limite < 1 THEN
            RAISE EXCEPTION 'servicos.expirar_holds: o tecto de linhas tem de '
              'ser um inteiro positivo (recebido: %)', p_limite
              USING ERRCODE = 'check_violation';
          END IF;
          FOR v_linha IN
            WITH vencidos AS (
              SELECT booking_id FROM servicos.bookings
               WHERE estado = 'hold' AND hold_expires_at <= now()
               ORDER BY hold_expires_at
               LIMIT p_limite
               FOR UPDATE SKIP LOCKED
            )
            UPDATE servicos.bookings AS b
               SET estado = 'expirada', hold_expires_at = NULL,
                   version = b.version + 1
              FROM vencidos AS v
             WHERE b.booking_id = v.booking_id AND b.estado = 'hold'
            RETURNING b.booking_id, b.tenant_id
          LOOP
            PERFORM platform.evt_emitir(
              'booking.cancelled', 1::smallint, v_linha.tenant_id,
              'booking', v_linha.booking_id::text,
              jsonb_build_object('booking_id', v_linha.booking_id,
                                 'motivo', 'hold_expirado'));
            v_total := v_total + 1;
          END LOOP;
          RETURN v_total;
        END $func$
        """
    )
    op.execute(
        "COMMENT ON FUNCTION servicos.expirar_holds(integer) IS "
        "'Liberta holds vencidos e emite booking.cancelled com motivo "
        "hold_expirado (KAM-047, criterio 3). SECURITY INVOKER: corre com a "
        "RLS e os privilegios de quem chama.'"
    )
    # `PUBLIC` nao executa nada: a omissao do PostgreSQL concede `EXECUTE` a
    # `PUBLIC` em cada funcao nova, e deixa-la assim dava a um papel sem
    # privilegio em `bookings` uma forma de a tentar alterar — recusada pela
    # RLS, mas o caminho nao tem de existir. E a licao que a `0004` e a `0023`
    # escreveram.
    op.execute("REVOKE ALL ON FUNCTION servicos.expirar_holds(integer) FROM PUBLIC")


def _rls() -> None:
    """Politica `tenant_iso` com `ENABLE` **e** `FORCE` nas quatro (ADR-015).

    `FORCE` vincula tambem o dono: sem ele, o `kamba_migrator` via tudo. O X-05
    do *gate* 6 descobre as tabelas pelo catalogo e nao por lista, pelo que
    estas quatro entram na verificacao sem ninguem as declarar — e uma que
    ficasse sem politica avermelhava o gate.
    """
    for tabela in ("services", "resources", "availability_rules", "bookings"):
        rls.enable_tenant_rls(tabela, schema=ESQUEMA)


def _privilegios() -> None:
    """`kamba_app` le e escreve a agenda; `kamba_batch` semeia e purga.

    **O `kamba_app` e quem escreve, e isso distingue este esquema do `dat`.**
    Ali o papel da aplicacao insere e nao le, porque quem produz um registo de
    custo nao e quem o audita. Aqui a agenda **e** o estado de negocio que a TLS
    le e escreve a cada turno: sem `SELECT` nao havia disponibilidade para
    calcular, e e a RLS que o limita as linhas do tenant — o que faz dela uma
    barreira exercida e nao decoracao.

    **O `UPDATE` de `bookings` e por coluna.** Ver `UPDATE_DA_APP_EM_BOOKINGS`
    para o que fica de fora e porque.

    **O `kamba_app` nao apaga nada.** Cancelar e um `UPDATE` do estado
    (a restricao de exclusao e parcial, pelo que a linha deixa de ocupar o
    intervalo sem ser apagada), e um `DELETE` concedido tornava a agenda
    reescrevivel sem deixar rasto. Quem apaga e o `kamba_batch`, que e o papel
    da retencao (KAM-071) e o semeador das baterias de isolamento.

    **O `kamba_resolver`, o `kamba_identity`, o `kamba_audit` e o `kamba_agr`
    nao ganham nada, nem `USAGE` no esquema.** O resolvedor resolve canais, a
    identidade guarda o cofre de contactos, a auditoria le a `audit_log`, e o
    `kamba_agr` guarda o estado das conversas — nenhum deles tem razao para
    chegar a agenda de ninguem. E a mesma escolha que o KAM-026 fez ao deixar o
    `kamba_agr` sem `USAGE` no `platform`.
    """
    op.execute(f"GRANT USAGE ON SCHEMA {ESQUEMA} TO {PAPEL_DA_APP}, {PAPEL_DE_LOTE}")

    # Catalogo: a aplicacao **le** servicos, recursos e regras, e nao os
    # escreve. Quem cria a agenda de uma PME e o onboarding de retaguarda
    # (KAM-091), pela mesma razao que a `0007` tirou `INSERT` em `entitlements`
    # a este papel: com `WITH CHECK (tenant_id = app.tenant_id)` um tenant
    # criava as proprias linhas, e aqui isso significava inventar recursos para
    # abrir intervalos que o dono nunca disponibilizou.
    for tabela in (SERVICES, RESOURCES, AVAILABILITY):
        op.execute(f"GRANT SELECT ON {tabela} TO {PAPEL_DA_APP}")
        op.execute(f"GRANT SELECT, INSERT, UPDATE, DELETE ON {tabela} TO {PAPEL_DE_LOTE}")

    op.execute(f"GRANT SELECT, INSERT ON {BOOKINGS} TO {PAPEL_DA_APP}")
    op.execute(
        f"GRANT UPDATE ({', '.join(UPDATE_DA_APP_EM_BOOKINGS)}) ON {BOOKINGS} "
        f"TO {PAPEL_DA_APP}"
    )
    op.execute(f"GRANT SELECT, INSERT, UPDATE, DELETE ON {BOOKINGS} TO {PAPEL_DE_LOTE}")

    op.execute(
        f"GRANT EXECUTE ON FUNCTION servicos.expirar_holds(integer) TO {PAPEL_DA_APP}"
    )


def downgrade() -> None:
    # Sem `CASCADE`, como todas as revisoes desde a `0001`: se houver um objecto
    # pendurado que esta revisao nao criou, o `downgrade` **falha** em vez de o
    # apagar em silencio.
    #
    # **E sem guarda de dados.** O que se perde sao marcacoes, que e estado de
    # negocio e nao prova — ao contrario do consentimento da `0015` e do registo
    # de custo da `0023`. Quem desce esta revisao com agenda viva perde-a, e o
    # `downgrade` existe para o ciclo do *gate* 8 e para reverter um deploy, nao
    # para operacao corrente.
    #
    # **A extensao cai antes do esquema**, e isso nao e cerimonia: ela vive
    # **dentro** do `servicos`, pelo que sem `CASCADE` o `DROP SCHEMA` falha
    # enquanto ela existir. Pela ordem inversa das FK: `bookings` referencia
    # `services` e `resources`, e `availability_rules` referencia `resources`.
    for tabela in ("bookings", "availability_rules", "resources", "services"):
        rls.disable_tenant_rls(tabela, schema=ESQUEMA)
    op.execute("DROP FUNCTION servicos.expirar_holds(integer)")
    op.execute(f"DROP TABLE {BOOKINGS}")
    # O *trigger* cai com a tabela; a funcao nao, e por isso vai a seguir.
    op.execute(f"DROP TABLE {AVAILABILITY}")
    op.execute("DROP FUNCTION servicos.validar_fuso()")
    op.execute(f"DROP TABLE {RESOURCES}")
    op.execute(f"DROP TABLE {SERVICES}")
    op.execute("DROP EXTENSION btree_gist")
    op.execute(f"DROP SCHEMA {ESQUEMA}")
