"""Direitos do titular: dsar_requests e erasure_ledger (KAM-070).

A primeira linha e **sem acentos**, como as trinta e cinco revisoes anteriores:
e a mensagem que o `alembic history` imprime, e o
`test_no_processo_e_pela_linha_de_comandos_o_alembic_diz_o_mesmo` compara a saida
no processo com a do executavel. Com acentos, as duas divergem na codificacao.

## O que esta revisao cria

Duas tabelas, e sao os criterios 1 e 3 do KAM-070:

* a `platform.dsar_requests`, **um pedido do titular** — o tipo, o estado, o
  instante de recepcao, o prazo interno e o papel da KAMBA nesse pedido;
* a `platform.erasure_ledger`, **uma linha por escopo que aplicou** o
  apagamento. Nao e o registo do pedido outra vez: e o que permite ao criterio
  3 dizer «o pedido so passa a `concluido` quando todos aplicaram» sem perguntar
  a seis componentes se ja acabaram.

E alarga **um dominio fechado de outra revisao**: as accoes do
`platform.audit_log` (`0006`) passam de sete a nove, com
`privacy.dsar_recusado` e `privacy.dsar_rectificado`. Nao e escopo a mais: o
criterio 7 escreve «escreve no `audit_log`» e o criterio 1 «fica registado»,
e o dominio e fechado por `CHECK` — sem este passo os dois criterios nao se
podem cumprir. A extensao por migracao e o que o dicionario autoriza por
escrito na linha desse dominio.

## Porque e que o ledger e uma tabela e nao um campo do pedido

O criterio 3 nomeia **seis** consumidores do `privacy.erasure_requested` — o
cofre de contactos, o AGR, o STO, o DAT, o IDX e o Chatwoot — e cada um emite
`privacy.erasure_applied`. O contrato publicado desse evento
(`contratos/eventos/privacy.erasure_applied/v2.schema.json`) tem **um** campo de
`payload`, o `contact_id`: **nao diz quem aplicou**. Fechar o pedido a contar
eventos `applied` fechava-o ao sexto evento, viesse ele de seis componentes ou
seis vezes do mesmo.

Por isso quem conta e a tabela, pela unicidade `(tenant_id, dsar_id, escopo)`, e
nao o barramento. A alternativa era uma versao `v3` do contrato com o escopo
dentro — uma mudanca de contrato publicado, com o `contract_diff`, os esquemas
gerados e o catalogo atras dela, para passar a informacao que a tabela ja tem.

## O prazo interno nao e `CHECK`, e a razao e medida e nao preferencia

O criterio 1 escreve `prazo_interno_at = recebido_at + 30 d`. A forma obvia era
um `CHECK (prazo_interno_at = recebido_at + make_interval(days => prazo_dias))`,
e **nao se usa**: `timestamptz + interval` e `STABLE` e nao `IMMUTABLE` em
PostgreSQL, porque somar dias a um `timestamptz` le o `TimeZone` da sessao. Um
`CHECK` assim e satisfeito por quem insere e pode deixar de o ser para quem le
noutra sessao — uma restricao que depende de um GUC nao restringe, mente. (Pela
mesma razao nao e coluna gerada: essas **exigem** `IMMUTABLE` e o PostgreSQL
recusa a expressao.)

O que fica na base e o que a base pode garantir: o `prazo_dias` **como coluna**,
e nao como constante enterrada na aritmetica, e a ordenacao
`prazo_interno_at > recebido_at`. A aritmetica e de quem escreve, e esta
prendida pelo ensaio nomeado do modulo (`kamba_core.direitos`) — que e onde o
prazo e parametro, como o bloco pede: os 30 dias sao o interno do requisito 13 e
os 60 dias uteis da Lei 22/11 sao **INDICIO**.

## O `papel_kamba` nao tem omissao nesta tabela, e isso e deliberado

A D9 — quem executa o pedido, a PME responsavel ou a KAMBA subcontratada —
**esta aberta**. O bloco diz «omissao `subcontratada`, a confirmar por parecer»,
e essa omissao vive na configuracao do modulo e nao num `DEFAULT` da coluna: um
`DEFAULT` na DDL faz uma decisao aberta parecer decidida a quem le o esquema, e
e exactamente a leitura que o ADR-008 existe para impedir no caso dos destinos.
A coluna e `NOT NULL` sem omissao: quem escreve **diz** o papel.

## O que esta revisao nao cria

Nenhuma vista. O contrato que o `specs/EPIC-08_Topologia_Operacao.md` escreve
para o restauro e `erasure_ledger(subject_ref, erased_at)`, e os dois nomes
divergem dos desta tabela — o canonico e o `sujeito_ref` do dicionario §3 («Pseudonimo
para analytics»), e **nao serve de chave aqui**: e um HMAC de chave **mensal**,
pelo que o mesmo contacto tem refs diferentes em meses diferentes e um ledger
que lhe sobrevive meses nao se consegue reaplicar por ele. A chave e o
`contact_id`, que e o que a DoD do bloco autoriza por escrito («so
`contact_id`»). A reconciliacao dos dois nomes faz-se por funcao nomeada do
modulo, com ensaio, e a divergencia de prosa fica registada no bloco com credor
— o `EPIC-08` nao se toca neste ramo.
"""

from __future__ import annotations

from alembic import op

import rls

revision = "0038"
#: A `0037` e a `v_oferta_viva` do KAM-051 (PR #159), e o encaixe aqui nao e
#: escolha: a cadeia do Alembic e estritamente sequencial, pelo que **so pode
#: haver uma revisao nao fundida de cada vez** num lote de ramos paralelos — e o
#: numero vai a quem chega primeiro ao ponto de o usar.
#:
#: Este ramo escreveu `0037` e renumerou para `0038` na integracao, porque o
#: #159 ficou `MERGEABLE` primeiro. **Quem funde em segundo renumera**, e
#: faz-se **na integracao e nunca em antecipacao**: um ramo nao reserva a linha
#: de revisoes para outro.
down_revision = "0037"
branch_labels = None
depends_on = None

PEDIDOS = "platform.dsar_requests"
LEDGER = "platform.erasure_ledger"

#: Os quatro tipos de pedido, e sao os do **Objectivo** do bloco.
#:
#: O titulo do ticket diz «acesso, correccao, eliminacao e exportacao» e o
#: Objectivo diz «exportacao, rectificacao, eliminacao, oposicao» — quatro em
#: cada, cinco nomes distintos entre os dois. Segue-se o Objectivo, que e o que
#: os criterios de aceitacao implementam (o 2 e a exportacao, o 7 e a
#: rectificacao e a oposicao), e o **acesso** do Art. 26.o da Lei 22/11 e
#: servido pelo `exportacao`: o que o titular acede e o JSON portatil que o
#: criterio 2 define. Um quinto valor que nenhum caminho escreve era dominio
#: morto. A divergencia entre o titulo e o Objectivo fica devolvida a quem
#: escreveu o bloco.
TIPOS = ("exportacao", "rectificacao", "eliminacao", "oposicao")

#: Os tres estados, e nao ha `recusado`.
#:
#: Um pedido de **outro** BSUID sobre os dados de Y nao e um pedido de Y em
#: estado `recusado`: e uma tentativa contra Y, que nao pediu nada. Uma linha
#: aqui com o `contact_id` de Y punha no registo de pedidos do titular um pedido
#: que o titular nao fez — e tomava a chave de unicidade do criterio 8, pelo que
#: o pedido verdadeiro de Y a seguir colidia com a tentativa de quem o atacou.
#:
#: O criterio 1 pede «devolve 0 dados e fica registado», e o sitio do registo e
#: o `audit_log` (revisao `0006`), com o `contact_id` de **quem pediu**. E o que
#: o modulo faz, e tem ensaio proprio.
ESTADOS = ("recebido", "em_curso", "concluido")

#: Os seis escopos que o criterio 3 nomeia, por extenso e por esta ordem.
#:
#: Fechado de proposito: um escopo novo e um consumidor novo do
#: `privacy.erasure_requested`, e um consumidor que ninguem acrescentou a esta
#: lista nunca impedia o pedido de fechar — o pedido fechava **sem ele**, que e
#: a falha que o criterio 3 existe para tornar impossivel.
ESCOPOS = ("cofre", "agr", "sto", "dat", "idx", "chatwoot")

PAPEIS_DA_KAMBA = ("subcontratada", "responsavel")

#: Os quatro dominios, escritos por extenso para o `CHECK`.
#:
#: **Nao e duplicacao por descuido**, e a razao e a que a `0006` escreve: o
#: *gate* 3b le esta revisao **sem a correr** e so resolve cadeias, constantes
#: de modulo e *f-strings* sobre elas. Um `", ".join(...)` sobre a tupla deixa o
#: SQL ilegivel para ele, e um `CHECK` que o *gate* nao consegue ler e um
#: dominio que ele nao verifica — isto e, um dominio que pode divergir do
#: dicionario sem ninguem notar. Escrevem-se as duas formas, e o
#: `test_direitos_schema` confronta-as: um dominio escrito em dois sitios que
#: ninguem compara e um dominio que vai divergir.
LITERAIS_DE_TIPO = "'exportacao', 'rectificacao', 'eliminacao', 'oposicao'"
LITERAIS_DE_ESTADO = "'recebido', 'em_curso', 'concluido'"
LITERAIS_DE_ESCOPO = "'cofre', 'agr', 'sto', 'dat', 'idx', 'chatwoot'"
LITERAIS_DE_PAPEL = "'subcontratada', 'responsavel'"

#: As duas accoes de auditoria que esta revisao acrescenta ao dominio fechado do
#: `platform.audit_log` (revisao `0006`, restricao `audit_log_action`).
#:
#: **Sao duas e nao quatro, e cada uma e exigida por um criterio pelo nome:**
#:
#: * `privacy.dsar_recusado` — criterio 1, «um pedido de outro BSUID sobre os
#:   dados de Y devolve 0 dados e **fica registado**». Nao fica em
#:   `dsar_requests`: uma linha la com o `contact_id` de Y punha no registo de
#:   pedidos do titular um pedido que o titular nao fez, e tomava a chave de
#:   unicidade do criterio 8;
#: * `privacy.dsar_rectificado` — criterio 7, «rectificacao ... **escreve no
#:   `audit_log`**».
#:
#: A aceitacao de um pedido **nao** leva accao nova: a linha de `dsar_requests`
#: e o registo dela, e auditar o que uma tabela ja registra era escrever o mesmo
#: facto em dois sitios que podem divergir. A conclusao tambem nao: e o
#: `concluido_at` da mesma linha.
#:
#: O dicionario autoriza a extensao por escrito — a linha do dominio de `action`
#: diz «Estende-se por migracao» — e e por isso que isto e uma revisao e nao uma
#: emenda ao `CHECK` da `0006`.

#: O dominio de `audit_log.action` **depois** desta revisao: as sete da `0006`
#: mais as duas acima. Por extenso, pela razao dos outros quatro.
#:
#: **Nao ha uma tupla ao lado desta cadeia**, ao contrario dos outros dominios, e
#: isso e emenda: a primeira versao tinha um `ACCOES_NOVAS` que **nenhum caminho
#: de codigo lia** — o `CHECK` le esta cadeia — e um par escrito em dois sitios
#: sem quem os confronte e a definicao do defeito que esta revisao evita nos
#: outros quatro dominios. Quem confronta estas duas accoes com o resto do
#: repositorio e o `test_as_accoes_de_auditoria_entram_no_dominio_da_revisao`,
#: do `libs/py-core/tests/test_direitos.py`, e a bateria `ACCOES` do
#: `db/tests/test_auditoria.py`.
LITERAIS_DE_ACCAO_0038 = (
    "'price.update', 'stock.adjust', 'payment.manual_confirm', "
    "'access.conversation', 'batch.run', 'breakglass.open', 'audit.read', "
    "'privacy.dsar_recusado', 'privacy.dsar_rectificado'"
)

#: O dominio **antes** desta revisao, que o `downgrade` repoe. E literalmente o
#: `LITERAIS_DE_ACCAO` da `0006`, e esta aqui copiado em vez de importado: uma
#: revisao que importasse constantes de outra deixava de descrever o passo que
#: da e passava a descrever o estado de outra — e o `downgrade` da `0006`
#: apagaria a tabela debaixo desta copia.
LITERAIS_DE_ACCAO_0006 = (
    "'price.update', 'stock.adjust', 'payment.manual_confirm', "
    "'access.conversation', 'batch.run', 'breakglass.open', 'audit.read'"
)

AUDIT_LOG = "platform.audit_log"
RESTRICAO_DA_ACCAO = "audit_log_action"

#: Quem le e quem escreve, papel a papel. O que nao esta aqui nao tem nada.
#:
#: O `kamba_identity` e o unico que **le** o pedido sem o poder criar: aplica o
#: escopo `cofre` e precisa de saber de que pedido se trata, mas um pedido do
#: titular nasce no canal e nao no cofre.
PAPEL_DA_APP = "kamba_app"
PAPEL_DE_LOTE = "kamba_batch"
PAPEL_DE_AUDITORIA = "kamba_audit"
PAPEL_DE_IDENTIDADE = "kamba_identity"

#: **O `kamba_agr` nao aparece nesta revisao**, e nao e por o AGR nao ter escopo:
#: tem — o `agr` e o segundo dos seis do criterio 3. E porque
#: `PAPEIS_SEM_NADA_EM_PLATFORM = ("kamba_agr",)`, em
#: `db/tests/test_privilegios.py`, afirma «este papel **nao alcanca** o
#: `platform`» — e a nota dessa linha diz por extenso que isso **e** o criterio 4
#: do KAM-026.
#:
#: Uma primeira versao desta revisao dava-lhe `SELECT` nos pedidos e
#: `SELECT, INSERT` no ledger. Isso nao e um privilegio a mais: e **afrouxar o
#: criterio de outro ticket** a partir deste, e a decisao de o afrouxar nao e de
#: quem implementa os direitos do titular. Foi achado da revisao do lote.
#:
#: O consumidor de `privacy.erasure_requested` do AGR escreve a sua linha do
#: ledger pela ligacao de **aplicacao** (`kamba_app`, que tem `SELECT, INSERT`
#: nas duas tabelas), e nao pela do *checkpointer*. A fronteira do KAM-026 e que
#: o `kamba_agr` alcanca o `lg` e mais nada; aplicar um apagamento no `platform`
#: nao e trabalho de *checkpointer*.

#: As colunas de `dsar_requests` que se actualizam, e so estas.
#:
#: O `tipo`, o `contact_id` e o `recebido_at` **nao** estao: mudar o tipo de um
#: pedido em curso e um pedido novo, e mudar o titular de um pedido e dar os
#: dados de um a outro. O `prazo_interno_at` tambem nao — um prazo legal que se
#: pode empurrar nao e um prazo.
UPDATE_DO_PEDIDO = ("estado", "concluido_at")

#: Quem pode `INSERT` no ledger, por escopo. Um escopo nao se aplica a si
#: proprio: quem o aplica e o processo que detem a loja de dados.
ESCRITORES_DO_LEDGER = (
    PAPEL_DA_APP,
    PAPEL_DE_LOTE,
    PAPEL_DE_IDENTIDADE,
)


def upgrade() -> None:
    op.execute(
        f"""
        CREATE TABLE {PEDIDOS} (
          dsar_id           uuid CONSTRAINT dsar_requests_pkey PRIMARY KEY
                            DEFAULT gen_random_uuid(),
          tenant_id         uuid NOT NULL
                            CONSTRAINT dsar_requests_tenant_fk
                            REFERENCES platform.tenants (id),
          contact_id        uuid NOT NULL,
          tipo              text NOT NULL
                            CONSTRAINT dsar_requests_tipo_ck
                            CHECK (tipo IN ({LITERAIS_DE_TIPO})),
          estado            text NOT NULL
                            CONSTRAINT dsar_requests_estado_ck
                            CHECK (estado IN ({LITERAIS_DE_ESTADO})),
          papel_kamba       text NOT NULL
                            CONSTRAINT dsar_requests_papel_kamba_ck
                            CHECK (papel_kamba IN ({LITERAIS_DE_PAPEL})),
          recebido_at       timestamptz NOT NULL DEFAULT now(),
          prazo_dias        smallint NOT NULL
                            CONSTRAINT dsar_requests_prazo_dias_ck
                            CHECK (prazo_dias > 0 AND prazo_dias <= 365),
          prazo_interno_at  timestamptz NOT NULL,
          concluido_at      timestamptz,
          CONSTRAINT dsar_requests_tenant_dsar_uq UNIQUE (tenant_id, dsar_id),
          CONSTRAINT dsar_requests_contact_fk
            FOREIGN KEY (tenant_id, contact_id)
            REFERENCES platform.contacts (tenant_id, contact_id),
          CONSTRAINT dsar_requests_prazo_ordenado_ck
            CHECK (prazo_interno_at > recebido_at),
          CONSTRAINT dsar_requests_concluido_par_ck
            CHECK ((estado = 'concluido') = (concluido_at IS NOT NULL)),
          CONSTRAINT dsar_requests_concluido_ordenado_ck
            CHECK (concluido_at IS NULL OR concluido_at >= recebido_at)
        )
        """
    )
    op.execute(
        f"""
        COMMENT ON TABLE {PEDIDOS} IS
          'Pedidos do titular (Lei 22/11 Art. 25-28). Sem dado pessoal: so contact_id, que e aleatorio (KAM-070).'
        """
    )
    op.execute(
        f"""
        COMMENT ON COLUMN {PEDIDOS}.prazo_dias IS
          'Prazo interno em dias, parametro e nao constante: 30 pelo requisito 13 de E3. Os 60 dias uteis da Lei 22/11 sao INDICIO (a confirmar por parecer).'
        """
    )
    op.execute(
        f"""
        COMMENT ON COLUMN {PEDIDOS}.papel_kamba IS
          'Papel da KAMBA neste pedido. Sem DEFAULT: a D9 esta aberta e um DEFAULT fazia-a parecer decidida (KAM-070).'
        """
    )

    # A idempotencia do criterio 8, e **e um indice parcial e nao uma
    # unicidade**: dois pedidos do mesmo tipo pelo mesmo titular sao legitimos
    # ao longo do tempo — um apagamento em Marco e outro em Setembro, depois de
    # o BSUID voltar a escrever e criar contacto novo. O que nao e legitimo e
    # **dois ao mesmo tempo**, que e o que duplica *jobs*. Por isso o predicado
    # e o conjunto dos estados abertos, e nao a tabela toda.
    op.execute(
        f"""
        CREATE UNIQUE INDEX dsar_requests_aberto_uq
          ON {PEDIDOS} (tenant_id, contact_id, tipo)
          WHERE estado <> 'concluido'
        """
    )
    # O varrimento do prazo (criterio 8, o alerta aos 20 dias) le os abertos
    # ordenados pelo prazo. Parcial pela mesma razao: os concluidos nao tem
    # prazo a vencer.
    op.execute(
        f"""
        CREATE INDEX dsar_requests_prazo_idx
          ON {PEDIDOS} (tenant_id, prazo_interno_at)
          WHERE estado <> 'concluido'
        """
    )

    op.execute(
        f"""
        CREATE TABLE {LEDGER} (
          erasure_id   uuid CONSTRAINT erasure_ledger_pkey PRIMARY KEY
                       DEFAULT gen_random_uuid(),
          tenant_id    uuid NOT NULL
                       CONSTRAINT erasure_ledger_tenant_fk
                       REFERENCES platform.tenants (id),
          dsar_id      uuid NOT NULL,
          contact_id   uuid NOT NULL,
          escopo       text NOT NULL
                       CONSTRAINT erasure_ledger_escopo_ck
                       CHECK (escopo IN ({LITERAIS_DE_ESCOPO})),
          aplicado_at  timestamptz NOT NULL DEFAULT now(),
          CONSTRAINT erasure_ledger_dsar_fk
            FOREIGN KEY (tenant_id, dsar_id)
            REFERENCES {PEDIDOS} (tenant_id, dsar_id),
          CONSTRAINT erasure_ledger_contact_fk
            FOREIGN KEY (tenant_id, contact_id)
            REFERENCES platform.contacts (tenant_id, contact_id),
          CONSTRAINT erasure_ledger_escopo_uq UNIQUE (tenant_id, dsar_id, escopo)
        )
        """
    )
    op.execute(
        f"""
        COMMENT ON TABLE {LEDGER} IS
          'Uma linha por escopo que aplicou um apagamento. Append-only por privilegio: ninguem tem UPDATE nem DELETE (KAM-070).'
        """
    )
    op.execute(
        f"""
        COMMENT ON COLUMN {LEDGER}.contact_id IS
          'A chave do ledger. Nao e o sujeito_ref do dicionario §3: esse e HMAC de chave mensal e nao sobrevive aos meses que o ledger atravessa.'
        """
    )
    # A reaplicacao depois de um restauro (criterio 6) le o ledger por contacto
    # e pelo instante, e **le atraves dos tenants**: um restauro e da base e nao
    # de um tenant. Quem o corre e o `kamba_batch`, que tem contexto de tenant
    # como os outros — por isso o indice leva o `tenant_id` a frente, como todos
    # os outros desta base.
    op.execute(
        f"""
        CREATE INDEX erasure_ledger_contacto_idx
          ON {LEDGER} (tenant_id, contact_id, aplicado_at)
        """
    )

    rls.enable_tenant_rls("dsar_requests")
    rls.enable_tenant_rls("erasure_ledger")

    # Privilegios, tabela a tabela e coluna a coluna, como na `0003`.
    #
    # `kamba_app` cria o pedido (chega pelo canal) e fecha-o; `kamba_batch`
    # varre prazos e aplica o escopo `dat`; `kamba_identity` **le** o pedido
    # porque aplica o `cofre`, e nao o cria; `kamba_audit` le tudo e nao escreve
    # nada, que e o que faz dele auditoria. **O `kamba_agr` nao entra**, pela
    # razao escrita na constante dele acima: os cinco escopos que nao sao do
    # cofre escrevem pela ligacao de aplicacao.
    op.execute(f"GRANT SELECT, INSERT ON {PEDIDOS} TO {PAPEL_DA_APP}")
    op.execute(f"GRANT SELECT ON {PEDIDOS} TO {PAPEL_DE_LOTE}")
    op.execute(f"GRANT SELECT ON {PEDIDOS} TO {PAPEL_DE_IDENTIDADE}")
    op.execute(f"GRANT SELECT ON {PEDIDOS} TO {PAPEL_DE_AUDITORIA}")
    # Por extenso, e nao num `for` sobre dois papeis: o *gate* 3b recusou a
    # versao com ciclo — «`papel` e atribuido mais de uma vez, ou sombreado» —
    # porque esta revisao ja tem outro `for papel` abaixo, e ele le a revisao
    # **sem a correr**. Duas atribuicoes ao mesmo nome tornam o SQL irresoluvel
    # para ele, e um `GRANT` que o *gate* nao consegue ler e um privilegio que
    # ele nao verifica. O `', '.join` sobre a constante, esse, ele resolve.
    op.execute(
        f"GRANT UPDATE ({', '.join(UPDATE_DO_PEDIDO)}) ON {PEDIDOS} TO {PAPEL_DA_APP}"
    )
    op.execute(
        f"GRANT UPDATE ({', '.join(UPDATE_DO_PEDIDO)}) ON {PEDIDOS} TO {PAPEL_DE_LOTE}"
    )

    # O ledger e **append-only por privilegio**, e nao por *trigger*: nenhum
    # papel leva `UPDATE` nem `DELETE`, nem o `kamba_batch`. Uma linha que diz
    # «o STO apagou em T» nao se emenda — se o STO nao apagou, o que falta e a
    # linha, nao a correccao dela.
    #
    # Por extenso e nao num `for` sobre o `ESCRITORES_DO_LEDGER`, pela razao dos
    # `GRANT UPDATE` acima: o *gate* 3b recusou a versao com ciclo («`papel` nao
    # e uma constante de modulo»), e um `GRANT` que ele nao consegue ler e um
    # privilegio que ele nao verifica. A tupla fica, porque e ela que diz **quem**
    # sao os escritores e o `test_privilegios` le a matriz por tabela.
    op.execute(f"GRANT SELECT ON {LEDGER} TO {PAPEL_DE_AUDITORIA}")
    op.execute(f"GRANT SELECT, INSERT ON {LEDGER} TO {PAPEL_DA_APP}")
    op.execute(f"GRANT SELECT, INSERT ON {LEDGER} TO {PAPEL_DE_LOTE}")
    op.execute(f"GRANT SELECT, INSERT ON {LEDGER} TO {PAPEL_DE_IDENTIDADE}")

    _alargar_o_dominio_da_accao()


def _alargar_o_dominio_da_accao() -> None:
    """Poe as duas accoes de DSAR no `CHECK` fechado do `audit_log`.

    O criterio 7 escreve «escreve no `audit_log`» e o criterio 1 «fica
    registado». O dominio de `action` e **fechado por `CHECK`** desde a `0006`,
    pelo que sem este passo os dois criterios nao se podem cumprir: a escrita
    levantava `23514`.

    ## O `NO FORCE` a volta do `ADD CONSTRAINT` nao e cosmetica

    E a armadilha que a `0003` mediu contra o PostgreSQL 18.6, e vale igual
    aqui: o PostgreSQL valida as linhas existentes com uma consulta feita pelo
    **dono da tabela**, e o `audit_log` tem `FORCE ROW LEVEL SECURITY` — o dono,
    sem contexto de tenant, ve **zero linhas**. A validacao passava sem ter
    olhado para nada.

    No `upgrade` o dominio novo e um **superconjunto** do antigo, pelo que
    nenhuma linha o pode violar e a validacao e verdadeira ou vacua com o mesmo
    resultado. No `downgrade` nao: la o dominio **encolhe**, e e exactamente la
    que uma validacao vacua deixava linhas `privacy.dsar_*` debaixo de um
    `CHECK` que diz que elas nao existem. Faz-se nos dois pela mesma razao pela
    qual se escreve o mesmo codigo nos dois sentidos: a assimetria e que se
    esquece.

    O intervalo sem `FORCE` nao se ve de fora — e a mesma transaccao, com a
    tabela trancada pelo `ALTER`.
    """
    op.execute(f"ALTER TABLE {AUDIT_LOG} NO FORCE ROW LEVEL SECURITY")
    op.execute(f"ALTER TABLE {AUDIT_LOG} DROP CONSTRAINT {RESTRICAO_DA_ACCAO}")
    op.execute(
        f"""
        ALTER TABLE {AUDIT_LOG}
          ADD CONSTRAINT {RESTRICAO_DA_ACCAO}
          CHECK (action IN ({LITERAIS_DE_ACCAO_0038}))
        """
    )
    op.execute(f"ALTER TABLE {AUDIT_LOG} FORCE ROW LEVEL SECURITY")


def _encolher_o_dominio_da_accao() -> None:
    """Repoe o dominio de sete da `0006`, ou recusa o `downgrade`.

    **O `audit_log` e `append-only` e ninguem tem `DELETE`.** Logo, com linhas
    `privacy.dsar_*` escritas, nao ha forma de satisfazer o `CHECK` antigo — e o
    passo **recusa**, com a contagem na mensagem, em vez de deixar o
    `ADD CONSTRAINT` falhar com um texto que nao diz o que fazer.

    E conta **com o `FORCE` ja desligado**, pela razao do `_alargar`: com ele, o
    dono via zero linhas, a contagem saia zero, o passo seguia e o
    `ADD CONSTRAINT` validava tambem zero — duas medicoes vacuas a concordar.
    """
    linhas = (
        op.get_bind()
        .exec_driver_sql(
            "SELECT count(*) FROM platform.audit_log "
            "WHERE action IN ('privacy.dsar_recusado', 'privacy.dsar_rectificado')"
        )
        .scalar_one()
    )
    if linhas:
        raise RuntimeError(
            f"downgrade da 0038 recusado: ha {linhas} linha(s) de audit_log com "
            "accao privacy.dsar_* e o dominio da 0006 nao as aceita. O audit_log "
            "e append-only e nenhum papel tem DELETE, pelo que nao ha forma de as "
            "retirar: exporte a cadeia e decida o que fazer a essas linhas antes "
            "de descer."
        )
    op.execute(f"ALTER TABLE {AUDIT_LOG} DROP CONSTRAINT {RESTRICAO_DA_ACCAO}")
    op.execute(
        f"""
        ALTER TABLE {AUDIT_LOG}
          ADD CONSTRAINT {RESTRICAO_DA_ACCAO}
          CHECK (action IN ({LITERAIS_DE_ACCAO_0006}))
        """
    )


def downgrade() -> None:
    # Sem `CASCADE`, como todas as revisoes desde a `0001`: se houver um objecto
    # pendurado que esta revisao nao criou, o `downgrade` **falha** em vez de o
    # apagar em silencio.
    #
    # A ordem e a inversa do `upgrade`, e aqui importa: o ledger tem FK para os
    # pedidos, pelo que cai primeiro. A RLS cai **explicitamente** e nao por
    # efeito do `DROP TABLE`, pela razao do ensaio de mutacao do `canon_lint`.
    #
    # **Este `downgrade` apaga o ledger de apagamentos**, e isso tem consequencia
    # que nao e so de dados: sem ele, um restauro deixa de saber quem foi apagado
    # depois da copia (criterio 6) e os titulares voltam. Nao se escreve copia
    # logica como na `0003`, e a razao e que a copia **ja existe por desenho** —
    # o ledger e exportado para fora da base pelo *hook* do KAM-079,
    # precisamente porque uma cadeia de apagamentos que vive so dentro da base
    # que se restaura nao serve para reaplicar nada.
    # O dominio da accao primeiro, e **antes** de `FORCE` voltar: o passo conta
    # as linhas e precisa de as ver.
    op.execute(f"ALTER TABLE {AUDIT_LOG} NO FORCE ROW LEVEL SECURITY")
    _encolher_o_dominio_da_accao()
    op.execute(f"ALTER TABLE {AUDIT_LOG} FORCE ROW LEVEL SECURITY")

    rls.disable_tenant_rls("erasure_ledger")
    rls.disable_tenant_rls("dsar_requests")
    # Os `CHECK`, as unicidades, as chaves primarias e os tres indices caem com
    # as tabelas. Nenhuma funcao e nenhum *trigger* nascem nesta revisao.
    op.execute(f"DROP TABLE {LEDGER}")
    op.execute(f"DROP TABLE {PEDIDOS}")
