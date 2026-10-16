"""Outbox transaccional, sequencia por agregado, subscricoes e arquivo de eventos (KAM-005).

Revisao: 0004
Anterior: 0003

O ADR-009 manda: o evento escreve-se na **mesma transaccao** que o dado, e
publica-se depois. A entrega e *at-least-once*; o efeito exactamente-uma-vez sai
da idempotencia do consumidor (KAM-006). A verdade e o outbox, nao a fila: as
garantias de entrega do BullMQ estao **NAO VERIFICADO** (`evidencia/E4` §2.10) e
assume-se o pior caso.

Quatro tabelas e uma funcao, e a forma de cada uma vem de `docs/tecnica/06`:

    events_outbox     o outbox. Forma de `docs/tecnica/06` §6.1. O outbox do
                      documento exploratorio 11 (`id, tipo, payload,
                      publicado_at, criado_at`) nao chega: sem `tenant_id` nao
                      ha isolamento nem roteamento, sem `agregado_seq` nao ha
                      ordem causal, sem `tentativas`/`proxima_tentativa_at` o
                      publicador nao recua, e sem `event_id` unico nao ha
                      deduplicacao na fila.
    evt_agregado_seq  o contador por agregado. Forma de §6.1. O `UPDATE` do
                      `ON CONFLICT` bloqueia a linha ate ao `COMMIT`: duas
                      transaccoes do mesmo agregado serializam-se, e um
                      `ROLLBACK` devolve o `seq` — sem lacunas.
    evt_subscricoes   quem recebe o que, com que versao maxima e para que
                      finalidade. Forma de §6.1; o roteamento por finalidade e
                      o §7.3.
    events_log        o arquivo imutavel, particionado por mes. Forma de §6.5.
    evt_emitir        a funcao que o produtor chama. Corpo de §6.1, incluindo a
                      guarda de PII (padrao de telefone, `check_violation`).

**`uuidv7()` existe no PostgreSQL 18.6 fixado.** O `docs/tecnica/06` §4 marcava-o
INDICIO e o ticket permitia o desvio de o gerar na aplicacao. Mediu-se contra a
imagem do inventario (`pgvector/pgvector:0.8.7-pg18`, digest em
`ci/supply-chain/imagens.yaml`): `SELECT count(*) FROM pg_proc WHERE proname =
'uuidv7'` da 2 (duas sobrecargas). A funcao usa-o; o desvio nao foi necessario.
O teste `test_eventos_schema.TestUuidv7` repete a medicao em cada execucao do
gate 8, para que a afirmacao nao envelheca em silencio.

**A particao `events_log_default`, e porque nao ha particoes mensais aqui.** As
particoes mensais tem nome com data (`events_log_2026_11`). Uma revisao nao as
pode criar com nome calculado: o gate 3b le a revisao pela arvore sintactica e
um nome que ele nao consiga ler e achado `ilegivel`. Escreve-las a mao fixava o
calendario numa migracao — a mesma classe de defeito que o KAM-008 pagou nos
testes. Por isso a revisao cria **so a particao `DEFAULT`**, que nunca caduca, e
as mensais ficam para um *job* (M+2 no dia 1; falha = alerta Sev2). **Esse
*job* nao existe ainda** — nem o `db/eventos_particoes.py` que o havia de
conter: a revisao e o X-05 estao prontos para ele e o codigo nao foi escrito
(`docs/eventos.md` §7 e decisao aberta 4). A `DEFAULT` e tambem a rede: um `INSERT` cuja data
nao caiba em nenhuma particao mensal entra nela em vez de rebentar — e a sua
contagem e o sinal de que o *job* nao correu.

**Cada particao leva a sua RLS.** Mediu-se contra o PostgreSQL 18.6: a politica
do pai **nao** protege quem le a particao directamente (com o contexto do tenant
A, `SELECT` na particao devolveu as linhas dos dois tenants; sem contexto,
tambem). O catalogo confirma-o: `relrowsecurity` da particao fica `false`
quando se liga a RLS no pai. Por isso `rls.enable_tenant_rls` corre tambem na
`events_log_default`, e o *job* das particoes mensais tera de fazer o mesmo em
cada particao que criar. A verificacao esta no X-05 (`catalogo.verificar_particoes`).

O que esta revisao **nao** faz, e de quem e:

    events_consumed, events_dlq  KAM-006 (consumidores idempotentes e DLQ).
    contratos/eventos/*.json     KAM-007 (catalogo de schemas e compatibilidade).
    purga do outbox publicado    KAM-071/ops. Aqui ha o privilegio (`DELETE` ao
                                 `kamba_batch`) e mais nada.
    *lint* de nomes de campo     KAM-007 (`docs/tecnica/06` §7.3). A guarda de
                                 PII desta revisao apanha **so** telefones
                                 explicitos, e esta dito no comentario da funcao.

Tudo isto e SQL **proposto ate correr**: o gate 8 e o que o promove.
"""

from __future__ import annotations

import base64
import json
import os

from alembic import op

import rls

revision = "0004"
down_revision = "0003"
branch_labels = None
depends_on = None

#: As tabelas com `tenant_id` desta revisao, pela ordem em que se criam. A
#: particao entra na lista porque a politica do pai nao a cobre (ver docstring).
TABELAS_DE_TENANT = (
    "events_outbox",
    "evt_agregado_seq",
    "events_log",
    "events_log_default",
)

#: Tabelas desta revisao sem `tenant_id`, e porque.
#:
#:   evt_subscricoes    configuracao **global** de entrega (consumidor x tipo).
#:                      Nao e dado de tenant: diz quem recebe o que, e e igual
#:                      para todos. Fica fora da RLS, e `kamba_app` nao a le.
TABELAS_SEM_TENANT = ("evt_subscricoes",)

#: Assinatura da funcao, para o `GRANT` e para o `DROP`. Escrita uma vez: os
#: tipos tem de ser os mesmos nos dois sitios ou o `DROP` nao a encontra.
ARGUMENTOS_DE_EVT_EMITIR = (
    "text, smallint, uuid, text, text, jsonb, text, text[], uuid, uuid, text, text, timestamptz"
)

#: Colunas de `evt_agregado_seq` que `kamba_app` altera. So o contador: mudar
#: `agregado_tipo` ou `agregado_id` era reescrever a chave de outro agregado.
UPDATE_DA_APP = {"evt_agregado_seq": ("seq",)}

#: Variavel com o caminho do ficheiro de copia logica que o `downgrade` escreve.
VARIAVEL_DA_COPIA = "KAMBA_DOWNGRADE_0004_COPIA"

#: O que a copia logica do `downgrade` leva. O `events_log` le-se pelo pai: as
#: particoes vem com ele.
TABELAS_COPIADAS = (
    "events_outbox",
    "events_log",
    "evt_subscricoes",
    "evt_agregado_seq",
)


def upgrade() -> None:
    # ------------------------------------------------------------- events_outbox
    op.execute(
        """
        CREATE TABLE platform.events_outbox (
          id                   bigint GENERATED ALWAYS AS IDENTITY
                               CONSTRAINT events_outbox_pkey PRIMARY KEY,
          event_id             uuid NOT NULL
                               CONSTRAINT events_outbox_event_id_uq UNIQUE,
          tipo                 text NOT NULL,
          versao               smallint NOT NULL,
          tenant_id            uuid NOT NULL,
          agregado_tipo        text NOT NULL,
          agregado_id          text NOT NULL,
          agregado_seq         bigint NOT NULL,
          particao             smallint NOT NULL,
          envelope             jsonb NOT NULL,
          criado_at            timestamptz NOT NULL DEFAULT now(),
          publicado_at         timestamptz,
          tentativas           int NOT NULL DEFAULT 0,
          proxima_tentativa_at timestamptz NOT NULL DEFAULT now(),
          CONSTRAINT events_outbox_agregado_uq
            UNIQUE (tenant_id, agregado_tipo, agregado_id, agregado_seq)
        )
        """
    )
    op.execute(
        """
        COMMENT ON TABLE platform.events_outbox IS
          'Outbox transaccional (ADR-009): o evento e escrito na transaccao do produtor e publicado depois. A verdade e esta tabela, nao a fila.'
        """
    )
    op.execute(
        """
        COMMENT ON COLUMN platform.events_outbox.event_id IS
          'Chave de idempotencia global (UUIDv7). E o jobId na fila: republicar nao duplica o job.'
        """
    )
    op.execute(
        """
        COMMENT ON COLUMN platform.events_outbox.particao IS
          'hash(tenant_id || agregado_id) & 15. Escolhe a fila evt.<consumer>.p<0..15>; a ordem vale dentro da particao.'
        """
    )
    op.execute(
        """
        COMMENT ON COLUMN platform.events_outbox.envelope IS
          'Envelope v1 (docs/tecnica/06 §4). Sem PII P2: so contact_id por referencia (ADR-010).'
        """
    )
    # O indice que o publicador usa: parcial, so sobre o que falta publicar.
    # Depois de publicado, a linha sai do indice e o varrimento nao cresce com
    # o arquivo.
    op.execute(
        """
        CREATE INDEX events_outbox_pendentes
          ON platform.events_outbox (proxima_tentativa_at, id)
          WHERE publicado_at IS NULL
        """
    )
    # Acrescentado ao DDL do §6.1 (desvio aditivo, registado no PR): o
    # `tenant_id` tem de vir em primeiro lugar em **algum** indice, porque e o
    # predicado que a RLS acrescenta a toda a consulta — e e o indice que serve
    # o `SELECT` do produtor sobre os seus proprios eventos. O
    # `test_tenant_id_e_not_null_e_vem_primeiro_num_indice` do gate 8 exige-o.
    op.execute(
        """
        CREATE INDEX events_outbox_tenant_criado
          ON platform.events_outbox (tenant_id, criado_at DESC)
        """
    )

    # ----------------------------------------------------------- evt_agregado_seq
    # **Desvio ao DDL do §6.1, e o unico que nao e aditivo: o `tenant_id`.** A
    # forma do documento e `PRIMARY KEY (agregado_tipo, agregado_id)`, sem
    # tenant, e o contador fica global. Com `kamba_app` a precisar de
    # `UPDATE (seq)` para o `ON CONFLICT`, isso abre duas portas cruzadas, e a
    # revisao adversarial (ANALISE-20, achado 2) demonstrou as duas:
    #
    #   1. com o contexto do tenant A, `UPDATE evt_agregado_seq SET seq = 0
    #      WHERE agregado_id = '<agregado de B>'` passa — ha privilegio e nao ha
    #      politica — e a partir dai **B deixa de poder emitir** para aquele
    #      agregado: o proximo `seq` colide com a unicidade do triplo, e como
    #      `evt_emitir` corre na transaccao do produtor, a transaccao de negocio
    #      de B falha com ela. Negacao de servico cruzada, permanente e
    #      silenciosa, sobre o caminho do dinheiro;
    #   2. A pode emitir com o **seu** `tenant_id` e o `agregado_id` de B (passa
    #      o `WITH CHECK`) e **consumir o `seq` de B** — que e precisamente o que
    #      o criterio 1 promete nao acontecer, e invisivel para B porque a linha
    #      de A esta escondida pela politica do outbox.
    #
    # Com `tenant_id` na chave, na politica e na unicidade do triplo, as duas
    # fecham-se: a tabela entra sozinha no X-03, X-04 e X-05, o espaco de `seq`
    # passa a ser por tenant, e a decisao deixa de ter de ser devolvida.
    # Registado no PR e em `docs/eventos.md` §5.
    op.execute(
        """
        CREATE TABLE platform.evt_agregado_seq (
          tenant_id     uuid NOT NULL,
          agregado_tipo text NOT NULL,
          agregado_id   text NOT NULL,
          seq           bigint NOT NULL,
          CONSTRAINT evt_agregado_seq_pkey
            PRIMARY KEY (tenant_id, agregado_tipo, agregado_id)
        )
        """
    )
    op.execute(
        """
        COMMENT ON TABLE platform.evt_agregado_seq IS
          'Contador de seq por agregado e por tenant. O UPDATE do ON CONFLICT bloqueia a linha ate ao COMMIT: serializa o agregado e um ROLLBACK devolve o seq.'
        """
    )
    op.execute(
        """
        COMMENT ON COLUMN platform.evt_agregado_seq.tenant_id IS
          'Desvio ao docs/tecnica/06 §6.1 (KAM-005, ANALISE-20 achado 2): sem ele o contador e global e um tenant corta a emissao de outro.'
        """
    )

    # ------------------------------------------------------------ evt_subscricoes
    op.execute(
        """
        CREATE TABLE platform.evt_subscricoes (
          consumer    text NOT NULL,
          tipo        text NOT NULL,
          versao_max  smallint NOT NULL DEFAULT 1,
          finalidade  text NOT NULL,
          exige_ordem boolean NOT NULL DEFAULT false,
          activo      boolean NOT NULL DEFAULT true,
          CONSTRAINT evt_subscricoes_pkey PRIMARY KEY (consumer, tipo)
        )
        """
    )
    op.execute(
        """
        COMMENT ON TABLE platform.evt_subscricoes IS
          'Quem recebe o que. O publicador entrega a uma subscricao activa so se a sua finalidade estiver em envelope.finalidades (docs/tecnica/06 §7.3).'
        """
    )

    # ---------------------------------------------------------------- events_log
    op.execute(
        """
        CREATE TABLE platform.events_log (
          event_id      uuid NOT NULL,
          tipo          text NOT NULL,
          versao        smallint NOT NULL,
          tenant_id     uuid NOT NULL,
          agregado_tipo text NOT NULL,
          agregado_id   text NOT NULL,
          agregado_seq  bigint NOT NULL,
          ocorrido_em   timestamptz NOT NULL,
          registado_em  timestamptz NOT NULL,
          classe_pii    text NOT NULL,
          envelope      jsonb NOT NULL,
          CONSTRAINT events_log_pkey PRIMARY KEY (event_id, ocorrido_em)
        ) PARTITION BY RANGE (ocorrido_em)
        """
    )
    op.execute(
        """
        COMMENT ON TABLE platform.events_log IS
          'Arquivo imutavel de eventos publicados, particionado por mes (docs/tecnica/06 §6.5). Imutavel por privilegio: nenhum papel de servico tem UPDATE nem DELETE.'
        """
    )
    # A particao DEFAULT: ver a docstring. Nunca caduca, e a sua contagem e o
    # sinal de que o *job* das particoes mensais nao correu.
    op.execute(
        """
        CREATE TABLE platform.events_log_default
          PARTITION OF platform.events_log DEFAULT
        """
    )
    op.execute(
        """
        COMMENT ON TABLE platform.events_log_default IS
          'Particao DEFAULT de events_log. Rede de seguranca: so recebe linhas quando falta a particao mensal. Linhas aqui = alerta Sev2 (docs/eventos.md §7).'
        """
    )
    op.execute(
        """
        CREATE INDEX events_log_tenant_ocorrido
          ON platform.events_log (tenant_id, ocorrido_em DESC)
        """
    )
    # A chave primaria de `evt_agregado_seq` ja comeca pelo `tenant_id`, pelo que
    # o indice que a RLS precisa existe sem se criar nenhum.

    # ----------------------------------------------------------------- evt_emitir
    #
    # Corpo de `docs/tecnica/06` §6.1, sem desvios. Tres coisas que a forma
    # esconde e que sao a razao de ser da funcao:
    #
    #   * a guarda de PII corre **antes** de qualquer escrita, e levanta
    #     `check_violation`: o produtor ve um erro de restricao, nao um evento
    #     publicado com um telefone dentro. Apanha so telefones explicitos — a
    #     defesa principal e o schema fechado e o *lint* do §7.3 (KAM-007);
    #   * o `INSERT ... ON CONFLICT DO UPDATE ... RETURNING seq` e o que
    #     serializa o agregado: a segunda transaccao espera pelo `COMMIT` da
    #     primeira, e por isso a ordem de `seq` coincide com a ordem de
    #     `COMMIT`;
    #   * `SECURITY INVOKER` (a omissao): a funcao corre com os privilegios e o
    #     contexto de quem a chama, pelo que o `WITH CHECK` da politica
    #     `tenant_iso` continua a valer sobre o `INSERT` no outbox. Uma
    #     `SECURITY DEFINER` aqui seria um buraco de isolamento, e o X-05
    #     recusa-a (`ci/secdef_allowlist.yaml`).
    # Cadeia **crua** (`r"""`): os dois padroes do guarda de PII levam `\+`, e
    # numa cadeia normal escreviam-se `\\+` — o ficheiro deixava de se poder ler
    # contra o `docs/tecnica/06` §6.1 a olho, e o teste de paridade do gate 8
    # (`TestParidadeDoGuardaDePii`) confronta o texto deste ficheiro com o do
    # modulo TypeScript. O que o PostgreSQL recebe e o mesmo nos dois casos
    # (`standard_conforming_strings` esta `on`), mas o que se le nao.
    op.execute(
        r"""
        CREATE FUNCTION platform.evt_emitir(
          p_tipo text, p_versao smallint, p_tenant uuid, p_agg_tipo text, p_agg_id text,
          p_payload jsonb,
          p_classe_pii text DEFAULT 'P0', p_finalidades text[] DEFAULT '{transacao}',
          p_correlacao uuid DEFAULT NULL, p_causa uuid DEFAULT NULL, p_trace text DEFAULT NULL,
          p_produtor text DEFAULT current_setting('application_name'),
          p_ocorrido_em timestamptz DEFAULT now())
        RETURNS uuid LANGUAGE plpgsql AS $$
        DECLARE v_id uuid := uuidv7(); v_seq bigint; v_part smallint;
        BEGIN
          IF p_payload::text ~ '\+?244 ?9[0-9]{8}' OR p_payload::text ~ '"\+[0-9]{9,15}"' THEN
            RAISE EXCEPTION 'evento % contem padrao de telefone (PII P2)', p_tipo
              USING ERRCODE = 'check_violation';
          END IF;
          INSERT INTO platform.evt_agregado_seq (tenant_id, agregado_tipo, agregado_id, seq)
            VALUES (p_tenant, p_agg_tipo, p_agg_id, 1)
            ON CONFLICT (tenant_id, agregado_tipo, agregado_id)
            DO UPDATE SET seq = platform.evt_agregado_seq.seq + 1
            RETURNING seq INTO v_seq;
          v_part := (hashtextextended(p_tenant::text || p_agg_id, 0) & 15)::smallint;
          INSERT INTO platform.events_outbox (
              event_id, tipo, versao, tenant_id, agregado_tipo, agregado_id,
              agregado_seq, particao, envelope)
            VALUES (v_id, p_tipo, p_versao, p_tenant, p_agg_tipo, p_agg_id, v_seq, v_part,
              jsonb_build_object(
                'id', v_id, 'tipo', p_tipo, 'versao', p_versao, 'tenant_id', p_tenant,
                'ocorrido_em', p_ocorrido_em, 'registado_em', now(), 'produtor', p_produtor,
                'agregado', jsonb_build_object('tipo', p_agg_tipo, 'id', p_agg_id, 'seq', v_seq),
                'correlacao_id', p_correlacao, 'causa_id', p_causa, 'trace_id', p_trace,
                'classe_pii', p_classe_pii, 'finalidades', to_jsonb(p_finalidades),
                'payload', p_payload));
          RETURN v_id;
        END $$
        """
    )
    op.execute(
        f"""
        COMMENT ON FUNCTION platform.evt_emitir({ARGUMENTOS_DE_EVT_EMITIR}) IS
          'Emite um evento na transaccao do produtor (docs/tecnica/06 §6.1). SECURITY INVOKER: a RLS do outbox continua a valer. A guarda de PII apanha so telefones explicitos.'
        """
    )

    # ------------------------------------------------------------------ RLS
    for tabela in TABELAS_DE_TENANT:
        rls.enable_tenant_rls(tabela)

    # ---------------------------------------------------------- privilegios
    #
    # Tabela a tabela e coluna a coluna, como nas revisoes anteriores. Sem
    # `ALTER DEFAULT PRIVILEGES`: uma tabela nova nao nasce acessivel.
    #
    # `kamba_app` e o produtor. Chama `evt_emitir`, que corre como ele: precisa
    # de `INSERT` no outbox (sob `WITH CHECK`: o `tenant_id` tem de ser o do
    # contexto) e de `INSERT`/`SELECT`/`UPDATE (seq)` no contador. Tem `SELECT`
    # no outbox e no arquivo — **das suas linhas**, que e o que a politica deixa
    # ver — e e isso que faz da RLS destas duas tabelas uma barreira real e nao
    # decoracao: sem um papel sujeito a ela que as leia, a politica nunca seria
    # exercida. Nao tem `UPDATE` no outbox (o estado de publicacao e do
    # publicador) nem `DELETE` em nada.
    #
    # `kamba_batch` e o publicador e a retencao (*job* nomeado e auditado,
    # `docs/tecnica/08` §3.3). Tem `BYPASSRLS` por atributo, e e por isso que le
    # o outbox de todos os tenants; a auditoria do que ele faz e do KAM-012.
    #
    # `kamba_resolver` e `kamba_identity` nao tem nada: nao produzem nem
    # consomem eventos.
    op.execute("GRANT SELECT, INSERT ON platform.events_outbox TO kamba_app")
    op.execute("GRANT SELECT, INSERT ON platform.evt_agregado_seq TO kamba_app")
    for tabela, colunas in UPDATE_DA_APP.items():
        op.execute(
            f"GRANT UPDATE ({', '.join(colunas)}) ON platform.{tabela} TO kamba_app"
        )
    op.execute("GRANT SELECT ON platform.events_log TO kamba_app")
    op.execute(
        f"GRANT EXECUTE ON FUNCTION platform.evt_emitir({ARGUMENTOS_DE_EVT_EMITIR}) "
        "TO kamba_app"
    )
    op.execute(
        "GRANT SELECT, UPDATE, DELETE ON platform.events_outbox TO kamba_batch"
    )
    op.execute("GRANT SELECT ON platform.evt_subscricoes TO kamba_batch")
    op.execute("GRANT SELECT, INSERT ON platform.events_log TO kamba_batch")


# As tres funcoes abaixo nao recebem argumentos, e nao e por gosto: o gate 3b le
# esta revisao sem a correr, e so segue uma chamada cujos argumentos consiga
# resolver. O padrao e o da 0003.


def _contar() -> dict[str, int]:
    """Linhas em cada uma das quatro tabelas da revisao."""
    contagens = {}
    for tabela_a_contar in TABELAS_COPIADAS:
        contagens[tabela_a_contar] = (
            op.get_bind()
            .exec_driver_sql(f"SELECT count(*) FROM platform.{tabela_a_contar}")
            .scalar_one()
        )
    return contagens


def _celula(valor):
    """Um valor de coluna em JSON: os `bytea` em base64, o resto como texto."""
    if isinstance(valor, (bytes, bytearray, memoryview)):
        return {"b64": base64.b64encode(bytes(valor)).decode("ascii")}
    return None if valor is None else str(valor)


def _linhas():
    """Todas as linhas a copiar: (tabela, {coluna: valor em JSON})."""
    for tabela_copiada in TABELAS_COPIADAS:
        resultado = op.get_bind().exec_driver_sql(
            f"SELECT * FROM platform.{tabela_copiada}"
        )
        colunas = list(resultado.keys())
        for linha in resultado:
            yield tabela_copiada, {c: _celula(v) for c, v in zip(colunas, linha)}


def _copia_logica() -> None:
    """Escreve as linhas de eventos num ficheiro, ou recusa o `downgrade`.

    A revisao e **aditiva** — antes dela nao havia eventos, e por isso nenhum
    evento publicado se perde ao descer de versao. Mas o passo apaga o
    **arquivo**, e o arquivo nao se reconstroi: o `events_log` e a base da
    reconciliacao (`docs/tecnica/06` §11-§12) e o outbox pode ter eventos ainda
    por publicar. Uma perda dessas nao pode ser silenciosa. Com linhas em
    qualquer das quatro tabelas, o passo so avanca se `KAMBA_DOWNGRADE_0004_COPIA`
    apontar para um ficheiro **novo**, onde ficam todas as linhas, uma por linha
    de JSON.

    Corre **depois** de a RLS ser desligada: o dono das tabelas esta sujeito ao
    `FORCE`, e sem contexto de tenant leria zero linhas — a copia sairia vazia e
    o passo apagaria tudo com um ficheiro que parecia prova. (E a licao da 0003,
    e vale aqui porque `events_outbox` e `events_log` tambem tem `FORCE`.)
    """
    contagens = _contar()
    if not any(contagens.values()):
        return

    destino = os.environ.get(VARIAVEL_DA_COPIA, "")
    resumo = ", ".join(f"{tabela}: {n}" for tabela, n in contagens.items())
    if not destino:
        raise RuntimeError(
            f"downgrade da 0004 recusado: ha eventos nas tabelas ({resumo}) e o "
            f"passo apaga-os. Defina {VARIAVEL_DA_COPIA} com o caminho de um "
            "ficheiro novo para a copia logica, ou esvazie as tabelas de proposito."
        )

    # Modo `x`: nunca por cima de uma copia anterior. 0600: so quem a fez a le.
    descritor = os.open(destino, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
    escritas = dict.fromkeys(contagens, 0)
    with os.fdopen(descritor, "w", encoding="utf-8", newline="\n") as ficheiro:
        for origem, registo in _linhas():
            ficheiro.write(
                json.dumps({"tabela": origem, "linha": registo}, sort_keys=True) + "\n"
            )
            escritas[origem] += 1
        ficheiro.flush()
        os.fsync(ficheiro.fileno())
    if escritas != contagens:
        raise RuntimeError(
            f"downgrade da 0004 recusado: a copia tem {escritas} e as tabelas "
            f"tem {contagens}"
        )


def downgrade() -> None:
    # A RLS primeiro, por duas razoes: a ordem inversa do `upgrade`, e porque a
    # copia logica a seguir precisa de ver as linhas (ver `_copia_logica`).
    # Por extenso e pela ordem inversa do `upgrade`. Nao `reversed(...)`: o gate
    # 3b segue a chamada com os argumentos que consegue resolver sem correr a
    # revisao, e uma iteracao invertida nao e um deles.
    rls.disable_tenant_rls("events_log_default")
    rls.disable_tenant_rls("events_log")
    rls.disable_tenant_rls("evt_agregado_seq")
    rls.disable_tenant_rls("events_outbox")
    _copia_logica()
    op.execute(f"DROP FUNCTION platform.evt_emitir({ARGUMENTOS_DE_EVT_EMITIR})")
    # `events_log_default` sai com o pai (`DROP TABLE` de uma particionada leva
    # as particoes), mas apaga-se a mao para que a ordem inversa se leia e para
    # que uma particao mensal criada pelo *job* (quando existir) nao fique a
    # depender de uma cascata que ninguem escreveu.
    op.execute("DROP TABLE platform.events_log_default")
    op.execute("DROP TABLE platform.events_log CASCADE")
    op.execute("DROP TABLE platform.evt_subscricoes")
    op.execute("DROP TABLE platform.evt_agregado_seq")
    op.execute("DROP TABLE platform.events_outbox")
