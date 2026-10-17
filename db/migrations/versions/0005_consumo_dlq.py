"""Consumo idempotente, DLQ, accoes externas e reposicao (KAM-006).

Revisao: 0005
Anterior: 0004

A entrega e *at-least-once* (ADR-009): a fila pode entregar o mesmo evento duas
vezes, e o publicador do KAM-005 republica o que nao tiver `publicado_at`. O
efeito **exactamente-uma-vez** nao sai da fila — sai daqui: um `INSERT ... ON
CONFLICT DO NOTHING` em `events_consumed` **na mesma transaccao** que o efeito
(`docs/tecnica/06` §6.3). Se o INSERT nao escreve linha, o evento ja foi
processado e a transaccao termina sem efeito.

Quatro tabelas, duas funcoes de retencao e uma restricao, e a forma de cada uma
vem de `docs/tecnica/06`:

    events_consumed       a janela de deduplicacao, 90 dias. Forma de §6.3.
    events_dlq            a fila de mortos, com estado e envelope. Forma de §6.4.
    evt_acoes             a tabela de accoes externas, para o `once(key, fn)`:
                          um efeito fora da base de dados (WhatsApp, HTTP) nao
                          entra na transaccao, e sem registo repetia-se a cada
                          re-entrega. Nome em **proposta** (o ticket di-lo).
    evt_dlq_aprovacoes    quem aprovou o descarte de uma entrada. **Desvio
                          declarado** ao §6.4, que tem so `resolvido_por text`:
                          «descartar um evento `payment.*` exige duas pessoas»
                          nao se escreve numa coluna de texto. Com uma tabela de
                          aprovacoes, a chave primaria `(dlq_id, aprovador)`
                          torna a mesma pessoa a aprovar duas vezes
                          **impossivel**, e nao apenas detectada.
    evt_limpar_*          as duas retencoes (90 dias e 30 dias apos resolucao).
                          A da DLQ apaga **primeiro** as aprovacoes da entrada e
                          so depois a entrada: a chave estrangeira nao tem
                          `ON DELETE CASCADE` de proposito, porque o gate 8 tem
                          uma regra fechada contra cascatas — e a regra esta
                          certa, uma cascata esconde perda de dados.
                          como funcoes. O *job* diario que as chama nasce com a
                          retencao (KAM-071) ou com o procedimento de *deploy*
                          (KAM-078) — a mesma decisao que o KAM-005 tomou para
                          as particoes mensais.

**Dois desvios aditivos ao DDL do documento, e a razao de cada um.**

1. `events_consumed` **ganha `tenant_id`**. O §6.3 nao o tem, e sem ele a tabela
   fica fora da RLS: guarda `agregado_id` e `event_id` de todos os tenants, e um
   papel que a leia ve quais os eventos que existem noutro tenant. E a mesma
   correccao que o KAM-005 fez ao `evt_agregado_seq` (ANALISE-20, achado 2), e o
   valor vem do envelope, que o tem sempre.

1b. `events_consumed.agregado_tipo`, `agregado_id` e `agregado_seq` passam a
   **NOT NULL**. No §6.3 sao anulaveis, e o `max(agregado_seq)` da verificacao de
   ordem **ignora NULL**: uma linha escrita sem `seq` fazia o maximo parecer mais
   antigo do que e, e com isso um evento atrasado passava por estar em ordem. O
   envelope traz sempre `agregado = {tipo, id, seq}` — o `lerEnvelope` recusa-o
   sem eles —, pelo que a coluna pode exigi-lo. Achado da revisao do espelho em
   Python.
2. `evt_subscricoes` ganha a restricao
   `evt_subscricoes_payment_exige_ordem`: `tipo LIKE 'payment.%'` obriga
   `exige_ordem`. O criterio 7 do ticket pede que **o arranque falhe** com uma
   subscricao mal configurada; a verificacao de arranque existe
   (`servicos/worker-canal`), e esta restricao e a outra metade — faz a
   configuracao errada ser recusada pela base de dados, em vez de detectada
   depois. Aplicar `paga` antes de `aguarda_pagamento` e uma transicao invalida,
   e uma subscricao de `payment.*` sem ordem permitia-a.

**O que esta revisao nao faz.** Nao cria particoes mensais de `events_consumed`
(a janela sao 90 dias e a retencao e por `DELETE`, nao por `DROP` de particao);
nao agenda nada (ver acima); e nao escreve conversores de versao — o catalogo de
schemas e o KAM-007.
"""

from __future__ import annotations

import base64
import json
import os
import sys

from alembic import op

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))))

import rls  # noqa: E402  (o auxiliar do KAM-004, lido de `db/`)

revision = "0005"
down_revision = "0004"
branch_labels = None
depends_on = None

#: As tabelas com `tenant_id` desta revisao, pela ordem em que se criam.
TABELAS_DE_TENANT = (
    "events_consumed",
    "events_dlq",
    "evt_acoes",
)

#: Tabelas desta revisao sem `tenant_id`, e porque.
#:
#:   evt_dlq_aprovacoes  cada linha aponta para uma entrada de `events_dlq`, que
#:                       tem `tenant_id` e RLS. A aprovacao e acto de operacao,
#:                       nao dado de tenant: quem aprova e da plataforma, e o
#:                       isolamento do que se aprova vem da linha referenciada.
#:                       `kamba_app` nao a le.
TABELAS_SEM_TENANT = ("evt_dlq_aprovacoes",)

#: Estados de uma entrada da DLQ (§6.4).
#:
#: O DDL escreve-os por extenso (o gate 3b le o SQL sem correr a revisao); esta
#: tupla e a fonte com que a suite do gate 8 confronta o `CHECK`. Um dominio
#: escrito em dois sitios que ninguem compara e um dominio que vai divergir.
ESTADOS_DA_DLQ = ("aberta", "reprocessada", "descartada")

#: Estados de uma accao externa. `em_curso` existe para o caso que importa: o
#: processo morreu entre o registo e a conclusao, e a re-entrega nao pode repetir
#: um efeito que **talvez** tenha acontecido — adia-se e decide-se por leitura.
ESTADOS_DE_ACCAO = ("em_curso", "feita", "falhada")

#: Variavel com o caminho do ficheiro de copia logica que o `downgrade` escreve.
VARIAVEL_DA_COPIA = "KAMBA_DOWNGRADE_0005_COPIA"

#: O que a copia logica do `downgrade` leva.
TABELAS_COPIADAS = (
    "events_consumed",
    "events_dlq",
    "evt_dlq_aprovacoes",
    "evt_acoes",
)


def upgrade() -> None:
    # ----------------------------------------------------------- events_consumed
    op.execute(
        """
        CREATE TABLE platform.events_consumed (
          consumer      text NOT NULL,
          event_id      uuid NOT NULL,
          tenant_id     uuid NOT NULL,
          agregado_tipo text NOT NULL,
          agregado_id   text NOT NULL,
          agregado_seq  bigint NOT NULL,
          processado_at  timestamptz NOT NULL DEFAULT now(),
          CONSTRAINT events_consumed_pkey PRIMARY KEY (consumer, event_id)
        )
        """
    )
    op.execute(
        """
        COMMENT ON TABLE platform.events_consumed IS
          'Janela de deduplicacao por (consumer, event_id), 90 dias (docs/tecnica/06 §6.3). O INSERT ON CONFLICT DO NOTHING na transaccao do efeito e o que torna a entrega at-least-once num efeito exactamente-uma-vez.'
        """
    )
    op.execute(
        """
        COMMENT ON COLUMN platform.events_consumed.tenant_id IS
          'Acrescentado ao DDL do §6.3 (desvio aditivo, KAM-006): sem ele a tabela fica fora da RLS e expoe que eventos existem noutro tenant. Vem do envelope.'
        """
    )
    op.execute(
        """
        COMMENT ON COLUMN platform.events_consumed.agregado_seq IS
          'Serve para detectar atrasos e auditar lacunas contra events_log, nao para esperar «o anterior»: o seq e contiguo por agregado e nao por consumidor (§6.3). NOT NULL, ao contrario do DDL do documento: o max() ignora NULL, e uma linha sem seq fazia a verificacao de ordem ver um maximo mais antigo do que o real.'
        """
    )
    # O indice do §6.3, para a leitura do maximo por agregado quando a
    # subscricao exige ordem.
    op.execute(
        """
        CREATE INDEX events_consumed_agg
          ON platform.events_consumed (consumer, agregado_tipo, agregado_id, agregado_seq DESC)
        """
    )
    # Acrescentado ao §6.3 (desvio aditivo): o `tenant_id` tem de vir primeiro
    # em **algum** indice, porque e o predicado que a RLS acrescenta a toda a
    # consulta. O `test_tenant_id_e_not_null_e_vem_primeiro_num_indice` do
    # gate 8 exige-o, e e tambem o indice que a retencao varre.
    op.execute(
        """
        CREATE INDEX events_consumed_tenant_processado
          ON platform.events_consumed (tenant_id, processado_at DESC)
        """
    )

    # ---------------------------------------------------------------- events_dlq
    # Os tres estados por extenso, e nao um `join` sobre `ESTADOS_DA_DLQ`: o
    # gate 3b le o SQL desta revisao **sem a correr**, e uma f-string deixa-o
    # cego ao dominio. A tupla fica como fonte para a suite, que confronta o
    # `CHECK` com ela.
    op.execute(
        """
        CREATE TABLE platform.events_dlq (
          id          bigint GENERATED ALWAYS AS IDENTITY
                      CONSTRAINT events_dlq_pkey PRIMARY KEY,
          consumer    text NOT NULL,
          event_id    uuid NOT NULL,
          tipo        text NOT NULL,
          versao      smallint NOT NULL,
          tenant_id   uuid NOT NULL,
          envelope    jsonb NOT NULL,
          erro        text NOT NULL,
          tentativas  int NOT NULL,
          estado      text NOT NULL DEFAULT 'aberta'
                      CONSTRAINT events_dlq_estado_ck
                      CHECK (estado IN ('aberta', 'reprocessada', 'descartada')),
          criado_at   timestamptz NOT NULL DEFAULT now(),
          resolvido_at  timestamptz,
          resolvido_por text,
          CONSTRAINT events_dlq_resolucao_ck
            CHECK ((estado = 'aberta') = (resolvido_at IS NULL))
        )
        """
    )
    op.execute(
        """
        COMMENT ON TABLE platform.events_dlq IS
          'Fila de mortos (docs/tecnica/06 §6.4). Uma entrada de payment.* ou order.paid e Sev1: e cliente que pagou sem confirmacao. Guarda o envelope (P0/P1 apenas); retencao de 30 dias apos resolucao.'
        """
    )
    op.execute(
        """
        COMMENT ON CONSTRAINT events_dlq_resolucao_ck ON platform.events_dlq IS
          'Acrescentado ao §6.4 (KAM-006): uma entrada aberta com resolvido_at, ou resolvida sem ele, e um estado que ninguem sabe ler. A retencao de 30 dias conta de resolvido_at.'
        """
    )
    # A unicidade e **parcial**, e isso e o desenho e nao uma optimizacao.
    #
    # Uma unicidade sobre `(consumer, event_id)` inteira dava reentrada
    # idempotente — e dava, ao mesmo tempo, isto: um evento falha seis vezes e
    # entra na DLQ; alguem reprocessa-o (`estado = 'reprocessada'`); o
    # reprocessamento volta a falhar seis vezes; e a segunda falha colide com a
    # linha **fechada** e nao escreve nada. Ficava uma DLQ com zero entradas
    # abertas sobre um efeito por aplicar — `evt_dlq_open` a zero, alerta
    # nenhum, e a retencao de 30 dias a apagar a unica evidencia. Num
    # `payment.*`, um Sev1 que se apaga a si proprio.
    #
    # Com a unicidade so sobre o que esta **aberto**, as duas propriedades
    # separam-se: duas falhas na mesma execucao continuam a dar uma entrada
    # (`ON CONFLICT ... WHERE estado = 'aberta' DO NOTHING`), e um ciclo novo
    # depois de uma resolucao abre uma entrada nova — com a anterior guardada,
    # que e o que uma auditoria quer ler.
    #
    # E e tambem a razao de **nao** se ter escolhido a alternativa: reabrir a
    # linha fechada com um `DO UPDATE` obrigava a dar `UPDATE (estado, ...)` a
    # `kamba_app`, e com isso quem consome passava a poder fechar uma entrada
    # sozinho — exactamente o que a regra dos dois aprovadores existe para
    # impedir.
    op.execute(
        """
        CREATE UNIQUE INDEX events_dlq_aberta_uq
          ON platform.events_dlq (consumer, event_id)
          WHERE estado = 'aberta'
        """
    )
    op.execute(
        """
        COMMENT ON INDEX platform.events_dlq_aberta_uq IS
          'Reentrada idempotente, so entre as abertas: o mesmo evento a falhar outra vez no mesmo consumidor nao abre uma segunda entrada aberta, mas um ciclo novo depois de uma resolucao abre a sua.'
        """
    )
    # O indice que a metrica `evt_dlq_open` e o alerta varrem: parcial, so sobre
    # o que esta aberto. Uma DLQ saudavel tem zero linhas aqui.
    op.execute(
        """
        CREATE INDEX events_dlq_abertas
          ON platform.events_dlq (tipo, criado_at)
          WHERE estado = 'aberta'
        """
    )
    op.execute(
        """
        CREATE INDEX events_dlq_tenant_criado
          ON platform.events_dlq (tenant_id, criado_at DESC)
        """
    )

    # --------------------------------------------------------- evt_dlq_aprovacoes
    op.execute(
        """
        CREATE TABLE platform.evt_dlq_aprovacoes (
          dlq_id    bigint NOT NULL
                    CONSTRAINT evt_dlq_aprovacoes_dlq_fk
                    REFERENCES platform.events_dlq (id),
          aprovador text NOT NULL,
          criado_at timestamptz NOT NULL DEFAULT now(),
          CONSTRAINT evt_dlq_aprovacoes_pkey PRIMARY KEY (dlq_id, aprovador),
          CONSTRAINT evt_dlq_aprovacoes_aprovador_ck CHECK (length(trim(aprovador)) > 0)
        )
        """
    )
    op.execute(
        """
        COMMENT ON TABLE platform.evt_dlq_aprovacoes IS
          'Quem aprovou o descarte de uma entrada da DLQ (KAM-006, desvio declarado ao §6.4). A chave (dlq_id, aprovador) torna a mesma pessoa a aprovar duas vezes impossivel; descartar um payment.* exige duas linhas distintas.'
        """
    )

    # ------------------------------------------------------------------ evt_acoes
    # Por extenso, pela mesma razao do `events_dlq`.
    op.execute(
        """
        CREATE TABLE platform.evt_acoes (
          idempotency_key text NOT NULL
                          CONSTRAINT evt_acoes_pkey PRIMARY KEY,
          consumer   text NOT NULL,
          event_id   uuid NOT NULL,
          accao      text NOT NULL,
          tenant_id  uuid NOT NULL,
          estado     text NOT NULL DEFAULT 'em_curso'
                     CONSTRAINT evt_acoes_estado_ck
                     CHECK (estado IN ('em_curso', 'feita', 'falhada')),
          resultado  jsonb,
          criado_at  timestamptz NOT NULL DEFAULT now(),
          concluido_at timestamptz,
          CONSTRAINT evt_acoes_conclusao_ck
            CHECK ((estado = 'em_curso') = (concluido_at IS NULL))
        )
        """
    )
    op.execute(
        """
        COMMENT ON TABLE platform.evt_acoes IS
          'Accoes com efeito fora da base de dados (WhatsApp, HTTP), para o once(key, fn) do §6.3. A chave e consumer:event_id:accao, que e o Idempotency-Key enviado ao terceiro.'
        """
    )
    op.execute(
        """
        COMMENT ON COLUMN platform.evt_acoes.estado IS
          'em_curso existe para o caso que importa: o processo morreu entre o registo e a conclusao. A re-entrega nao repete um efeito que TALVEZ tenha acontecido — adia e decide-se por leitura.'
        """
    )
    op.execute(
        """
        CREATE INDEX evt_acoes_tenant_criado
          ON platform.evt_acoes (tenant_id, criado_at DESC)
        """
    )

    # ---------------------------------- a subscricao de payment.* exige ordem
    #
    # O criterio 7 pede que o arranque falhe; isto faz a configuracao errada ser
    # **recusada** em vez de detectada. `NOT LIKE` em vez de `NOT (… LIKE …)`
    # para a leitura ser directa; com `tipo` NOT NULL, nao ha terceiro valor.
    op.execute(
        """
        ALTER TABLE platform.evt_subscricoes
          ADD CONSTRAINT evt_subscricoes_payment_exige_ordem
          CHECK (tipo NOT LIKE 'payment.%' OR exige_ordem)
        """
    )
    op.execute(
        """
        COMMENT ON CONSTRAINT evt_subscricoes_payment_exige_ordem ON platform.evt_subscricoes IS
          'KAM-006, criterio 7: os consumidores de payment.* sao sempre com ordem (§6.3). Aplicar paga antes de aguarda_pagamento e uma transicao invalida, e sem ordem era possivel.'
        """
    )

    # ------------------------------------------------------------- retencoes
    #
    # Funcoes e nao *jobs*: o agendador nasce com a retencao (KAM-071) ou com o
    # procedimento de deploy (KAM-078), a mesma decisao que o KAM-005 tomou
    # para as particoes mensais. Uma funcao e testavel agora e chamavel depois.
    #
    # `SECURITY INVOKER` (o omisso): quem chama tem de ter o `DELETE`, e isso e
    # `kamba_batch`. Uma funcao `SECURITY DEFINER` apagava linhas de qualquer
    # tenant sem a RLS do chamador — era um buraco por conveniencia.
    op.execute(
        """
        CREATE FUNCTION platform.evt_limpar_consumidos(p_dias int DEFAULT 90)
        RETURNS bigint LANGUAGE plpgsql AS $$
        DECLARE v_apagadas bigint;
        BEGIN
          IF p_dias < 7 THEN
            RAISE EXCEPTION 'retencao de events_consumed abaixo de 7 dias (%): a '
              'janela tem de exceder a re-entrega da Meta', p_dias;
          END IF;
          DELETE FROM platform.events_consumed
            WHERE processado_at < now() - make_interval(days => p_dias);
          GET DIAGNOSTICS v_apagadas = ROW_COUNT;
          RETURN v_apagadas;
        END $$
        """
    )
    op.execute(
        """
        COMMENT ON FUNCTION platform.evt_limpar_consumidos(int) IS
          'Retencao de 90 dias da janela de deduplicacao (§6.3). Recusa menos de 7 dias: a janela tem de exceder a re-entrega da Meta, ou um evento re-entregue volta a produzir efeito.'
        """
    )
    op.execute(
        """
        CREATE FUNCTION platform.evt_limpar_dlq(p_dias int DEFAULT 30)
        RETURNS bigint LANGUAGE plpgsql AS $$
        DECLARE v_apagadas bigint;
        BEGIN
          DELETE FROM platform.evt_dlq_aprovacoes a
            USING platform.events_dlq d
            WHERE a.dlq_id = d.id
              AND d.estado <> 'aberta'
              AND d.resolvido_at IS NOT NULL
              AND d.resolvido_at < now() - make_interval(days => p_dias);
          DELETE FROM platform.events_dlq
            WHERE estado <> 'aberta'
              AND resolvido_at IS NOT NULL
              AND resolvido_at < now() - make_interval(days => p_dias);
          GET DIAGNOSTICS v_apagadas = ROW_COUNT;
          RETURN v_apagadas;
        END $$
        """
    )
    op.execute(
        """
        COMMENT ON FUNCTION platform.evt_limpar_dlq(int) IS
          'Retencao de 30 dias APOS resolucao (§6.4). Uma entrada aberta nunca se apaga, por mais velha que seja: e um efeito de negocio que ninguem aplicou.'
        """
    )

    # ------------------------------------------------------------------ RLS
    for tabela in TABELAS_DE_TENANT:
        rls.enable_tenant_rls(tabela)

    # ---------------------------------------------------------- privilegios
    #
    # Tabela a tabela, como nas revisoes anteriores. Sem `ALTER DEFAULT
    # PRIVILEGES`: uma tabela nova nao nasce acessivel.
    #
    # `kamba_app` e quem consome: escreve a sua linha em `events_consumed` (sob
    # `WITH CHECK`, so no seu tenant), abre entradas na DLQ e registra accoes
    # externas. **Nao** tem `UPDATE` nem `DELETE` em `events_consumed`: apagar
    # uma linha de deduplicacao e permitir que o efeito se repita, e isso e da
    # retencao, que corre como `kamba_batch`.
    op.execute("GRANT SELECT, INSERT ON platform.events_consumed TO kamba_app")
    # So `INSERT`, e nao `SELECT` nem `UPDATE`: `kamba_app` abre a entrada e
    # nunca a le nem a fecha. E o que mantem o `id` sequencial fora do alcance
    # de um papel com RLS — sem isso, um tenant media pela sequencia quantas
    # falhas o vizinho teve (a regra do dicionario §2, e a razao dela) — e e
    # tambem o que faz a regra dos dois aprovadores valer: quem consome nao
    # pode resolver uma entrada sozinho, porque nao tem `UPDATE` nenhum aqui.
    #
    # A reentrada de um evento que volta a falhar depois de resolvido **nao**
    # precisa de `UPDATE`: a unicidade e parcial (`events_dlq_aberta_uq`, so
    # sobre as abertas), pelo que um ciclo novo abre uma entrada nova. Ver o
    # comentario desse indice.
    op.execute("GRANT INSERT ON platform.events_dlq TO kamba_app")
    op.execute("GRANT SELECT, INSERT ON platform.evt_acoes TO kamba_app")
    # Do `evt_acoes` muda-se o desfecho de uma accao que ele proprio registou.
    op.execute(
        "GRANT UPDATE (estado, resultado, concluido_at) ON platform.evt_acoes TO kamba_app"
    )
    # `kamba_app` **nao** le as subscricoes (continua a ser configuracao global,
    # KAM-005) e nao toca nas aprovacoes de descarte.
    #
    # `kamba_batch` e o reconciliador, o reprocessamento e a retencao — tudo
    # auditado. Tem `DELETE` nas duas tabelas de retencao e `UPDATE` do estado
    # da DLQ; nao tem `INSERT` em `events_consumed`, porque quem consome e a
    # aplicacao.
    op.execute("GRANT SELECT, DELETE ON platform.events_consumed TO kamba_batch")
    op.execute("GRANT SELECT, DELETE ON platform.events_dlq TO kamba_batch")
    op.execute(
        "GRANT UPDATE (estado, resolvido_at, resolvido_por) ON platform.events_dlq TO kamba_batch"
    )
    op.execute(
        "GRANT SELECT, INSERT, DELETE ON platform.evt_dlq_aprovacoes TO kamba_batch"
    )
    op.execute("GRANT SELECT ON platform.evt_acoes TO kamba_batch")
    op.execute(
        "GRANT EXECUTE ON FUNCTION platform.evt_limpar_consumidos(int) TO kamba_batch"
    )
    op.execute("GRANT EXECUTE ON FUNCTION platform.evt_limpar_dlq(int) TO kamba_batch")
    # `kamba_resolver` (o papel de leitura estreita do KAM-004) **nao** leva
    # nada. O painel de operacao que leria a DLQ nao existe, e dar acesso a
    # dados sem um chamador e alargar a superficie por antecipacao: quando o
    # painel nascer, o `GRANT` nasce com ele e com o teste que o exerce.


def _contar() -> dict[str, int]:
    """Quantas linhas ha em cada tabela a copiar."""
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
    """Escreve as linhas destas tabelas num ficheiro, ou recusa o `downgrade`.

    A revisao e **aditiva** — antes dela nao havia consumo nem DLQ. Mas o passo
    apaga **a DLQ**, e uma entrada aberta da DLQ e um efeito de negocio que
    ninguem aplicou: um `payment.*` ali e cliente que pagou sem confirmacao
    (§6.4). Apagar isso em silencio e perder dinheiro de alguem. A janela de
    deduplicacao tambem conta: sem ela, um evento re-entregue depois do
    `downgrade` volta a produzir efeito.

    Com linhas em qualquer das quatro tabelas, o passo so avanca se
    `KAMBA_DOWNGRADE_0005_COPIA` apontar para um ficheiro **novo**.

    Corre **depois** de a RLS ser desligada: o dono das tabelas esta sujeito ao
    `FORCE`, e sem contexto de tenant leria zero linhas — a copia sairia vazia e
    o passo apagaria tudo com um ficheiro que parecia prova. (E a licao da 0003,
    repetida na 0004.)
    """
    contagens = _contar()
    if not any(contagens.values()):
        return

    destino = os.environ.get(VARIAVEL_DA_COPIA, "")
    resumo = ", ".join(f"{tabela}: {n}" for tabela, n in contagens.items())
    if not destino:
        raise RuntimeError(
            f"downgrade da 0005 recusado: ha linhas de consumo e de DLQ ({resumo}) "
            f"e o passo apaga-as. Defina {VARIAVEL_DA_COPIA} com o caminho de um "
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
            f"downgrade da 0005 recusado: a copia tem {escritas} e as tabelas "
            f"tem {contagens}"
        )


def downgrade() -> None:
    # A RLS primeiro, por duas razoes: a ordem inversa do `upgrade`, e porque a
    # copia logica a seguir precisa de ver as linhas (ver `_copia_logica`).
    # Por extenso e pela ordem inversa do `upgrade`. Nao `reversed(...)`: o gate
    # 3b segue a chamada com os argumentos que consegue resolver sem correr a
    # revisao, e uma iteracao invertida nao e um deles.
    rls.disable_tenant_rls("evt_acoes")
    rls.disable_tenant_rls("events_dlq")
    rls.disable_tenant_rls("events_consumed")
    _copia_logica()
    op.execute("DROP FUNCTION platform.evt_limpar_dlq(int)")
    op.execute("DROP FUNCTION platform.evt_limpar_consumidos(int)")
    op.execute(
        "ALTER TABLE platform.evt_subscricoes "
        "DROP CONSTRAINT evt_subscricoes_payment_exige_ordem"
    )
    op.execute("DROP TABLE platform.evt_acoes")
    # As aprovacoes saem antes da DLQ: a chave estrangeira **nao** tem
    # `ON DELETE CASCADE` (o gate 8 recusa cascatas, e com razao: uma cascata
    # esconde perda de dados), pelo que esta ordem nao e so legibilidade.
    op.execute("DROP TABLE platform.evt_dlq_aprovacoes")
    op.execute("DROP TABLE platform.events_dlq")
    op.execute("DROP TABLE platform.events_consumed")
