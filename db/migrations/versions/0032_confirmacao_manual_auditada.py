"""Confirmacao humana auditada: confirmadores, fases, reversao e sinais (KAM-054).

A primeira linha e **sem acentos**, como as trinta e uma revisoes anteriores: e
a mensagem que o `alembic history` imprime, e o
`test_no_processo_e_pela_linha_de_comandos_o_alembic_diz_o_mesmo` compara a
saida no processo com a do executavel. Com acentos, as duas divergem na
codificacao.

## O que esta revisao cria

As quatro tabelas do `docs/tecnica/04` §6.2–6.3 que faltavam, e as quatro portas
de escrita delas:

    payment_confirmers          quem pode confirmar. A **unica** resposta a
                                pergunta «quem confirma» (M-1)
    manual_confirmations        cada fase, com actor, `canal_msg_id`, valor
                                declarado e hora (M-6). Com
                                `UNIQUE (charge_id, canal_msg_id)`, que e a
                                idempotencia do criterio 9
    refund_cases                o caso de reembolso (M-8, ADR-004): registo de
                                um processo que corre **fora** da plataforma
    fraud_signals               os sinais. Este ticket escreve **duas** regras,
                                as do M-3; as de anomalia sao do KAM-060

    manual_declarar             a declaracao do cliente (criterio 3)
    manual_confirmar            o acto humano: M-1, M-4, M-3 e M-5 (criterios
                                2, 4, 5 e 6)
    manual_expirar_confirmacao  a omissao do dono, F-18 (criterio 7)
    manual_reverter             a reversao auditada, M-8 (criterio 8)
    manual_janela               o agregado das duas janelas do M-3, que o
                                KAM-009 nao sabia calcular

E acrescenta duas barreiras ao ledger da `0029`, as duas por razao escrita no
proprio ticket que o criou:

    next_state                  ganha a quinta aresta: `paga` +
                                `confirmacao_manual_revertida` ->
                                `reembolso_pendente`, por `CREATE OR REPLACE`
    payment_events_g8_humano    o **G8** do §5, como *trigger* `BEFORE INSERT`
                                sobre `payment_events`

## O G8 e a razao pela qual este ticket toca na porta do ledger

O §5 lista oito *gates*, e o oitavo e explicitamente deste caminho:

    G8  Limites (so humano): M-2..M-5 cumpridos  |  confirmacao_manual_rejeitada

Ate aqui o G8 **nao existia em sitio nenhum**: o `append_payment_event` impunha
o G1, o G2 e o G4 e nada mais, pelo que um `pagamento_confirmado` com
`authn_method='manual'` e um `actor_id` qualquer passava — isto e, o caminho
humano era o unico dos tres do G1 sem guarda, e e o mais atacavel dos tres.

A guarda que entra e estreita e verificavel: um `pagamento_confirmado` com
`authn_method='manual'` exige **na mesma transaccao** uma linha de
`manual_confirmations` desta cobranca, em fase `confirmacao` ou
`segunda_aprovacao`, com `valor_bate` verdadeiro e `actor_contact_id` igual ao
`actor_id` do evento. Nao e «o codigo chama a funcao certa»: e o facto auditado
a ter de existir antes do evento que o invoca.

**E e um *trigger* sobre a tabela, e nao um bloco dentro da
`append_payment_event`.** A primeira versao desta revisao fazia o segundo, e
esta errada por duas razoes que se medem. A primeira: um `CREATE OR REPLACE`
substitui o corpo **inteiro**, pelo que acrescentar oito linhas obrigava a
copiar as outras duzentas e cinquenta da `0029` para dentro desta revisao — e
uma copia de uma funcao de dinheiro que ninguem compara linha a linha e uma
divergencia a prazo, nao uma alteracao. A segunda, que e a que decide: um bloco
dentro da funcao vale para **aquela** funcao, e o `TRIGGER` vale para a tabela.
Se amanha houver uma segunda via de `INSERT` em `payment_events` — e o KAM-053
construiu a base inteira para que nao haja, mas a barreira nao deve depender
disso —, o bloco nao a ve e o *trigger* ve. O `ENABLE ALWAYS` fecha a ultima
fenda, que e a licao da `0006`: um *trigger* na omissao e saltado por
`session_replication_role = replica`.

**E e isso que fecha a porta que a `manual_confirmar` sozinha nao fechava.** O
`kamba_app` tem `EXECUTE` em `append_payment_event` — tem de ter, e o caminho do
facilitador. Sem o G8, bastava-lhe chamar a porta do ledger directamente com
`authn_method => 'manual'` para pagar uma cobranca sem passar por confirmador
nenhum, sem desafio de valor e sem limites. As regras M-1..M-5 ficavam a valer
**por um caminho de codigo** e nao por uma propriedade da base, que e exactamente
a distincao que o KAM-053 existiu para fazer no outro lado.

O preco esta dito: uma confirmacao de **ops** a partir de um extracto tambem
tem de escrever a sua fase. Nao e efeito colateral — e o §9 («Abuso interno:
Ops confirma indevidamente | Papeis separados; confirmacoes de ops exigem motivo
e dupla aprovacao; **tudo no ledger**») e o M-6 («Auditoria total: **cada** fase
em `manual_confirmations`»). O que o G8 nao permite e uma confirmacao humana sem
rasto humano.

## As quatro entradas novas no `ci/secdef_allowlist.yaml`, e porque sao quatro

O KAM-053 escreveu, com razao para o seu escopo, que a `append_payment_event`
era «a **unica** entrada que esta revisao acrescenta». Este ticket acrescenta
quatro, e a pergunta que o decide nao e de estilo: **onde pode viver a regra
M-1?**

Com as funcoes de fase a `SECURITY INVOKER`, o `kamba_app` precisava de `INSERT`
em `manual_confirmations` — e com esse privilegio escreve uma
`declaracao_cliente` com o `actor_contact_id` que quiser, o que desfaz a guarda
do cliente (M-1) por completo: a funcao descobre quem e o cliente **lendo** essa
fase, e quem a pode escrever escolhe quem o cliente e. Isto e, a excepcao nao
desaparecia com `INVOKER`: mudava de sitio, e no sitio novo era maior.

Sao **quatro** e nao uma porque cada fase tem uma regra diferente e um estado de
partida diferente, e uma funcao so com um parametro `p_fase` punha quatro
conjuntos de regras atras de um `CASE` com uma assinatura em que a maioria dos
argumentos e nulo em cada ramo — mais dificil de revisar, e e a revisao que faz
destas excepcoes excepcoes. A quinta funcao, a `manual_janela`, **nao** entra na
lista: le e nao escreve, e fica `STABLE SECURITY INVOKER`.

## O que esta revisao **nao** cria, e e deliberado

* **FK de `refund_cases.order_id` para `orders_mirror`.** A tabela existe desde
  a `0030`, mas a `payment_charges.order_id` continua **sem FK** por decisao
  escrita da `0029` («a FK e do KAM-055»), e pôr a FK so num dos dois lados
  deixava o par incoerente. Fica no KAM-055 com a outra, e o `CHECK` de
  exclusividade — exactamente um de `order_id`/`charge_id` — fica **aqui**,
  porque nao depende de tabela nenhuma.
* **As regras de anomalia de `fraud_signals`** (valor divergente, duplicados,
  padroes): KAM-060. A tabela e deste ticket porque o criterio 6 escreve nela;
  as regras que a enchem nao.
* **O agendador que corre as 24 h do F-18.** A `manual_expirar_confirmacao` e a
  decisao, e e pura no sentido que importa — recebe a janela por argumento e nao
  le relogio de configuracao nenhum. O varrimento e do KAM-071, como o
  `expirar_holds` do KAM-047, e o aviso ao dono e do KAM-115.
* **A transicao da encomenda e os eventos `payment.*` para o EVT:** KAM-055, e o
  bloco escreve-o por extenso.

## `authn_method` e `manual` e nao `humano_auditado`

O criterio 5 do bloco escreve `authn_method='humano_auditado'`. Esse valor **nao
existe**: o dominio e o de quatro valores do dicionario §3.4 e do §6.2, e o
`payment_events_authn_method_ck` desta base recusa-o — uma implementacao copiada
a letra do criterio nao corria. E o lado errado e o bloco: o §4.2 M-6, que e a
regra que o criterio 5 implementa, escreve `authn_method='manual'`. Fica
`manual`, e a divergencia esta na emenda 1.60 do dicionario e na divida
documental.
"""

from __future__ import annotations

import sys
from pathlib import Path

from alembic import op

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))

import rls  # noqa: E402

revision = "0032"
down_revision = "0031"
branch_labels = None
depends_on = None

#: Literais e nao f-strings sobre outras constantes, pela razao da `0025`: o
#: *gate* 3b le o AST da revisao sem a executar e resolve `f"..."` sobre
#: constantes de modulo, mas nao sobre constantes que sejam elas proprias
#: f-strings.
CONFIRMADORES = "platform.payment_confirmers"
CONFIRMACOES = "platform.manual_confirmations"
REEMBOLSOS = "platform.refund_cases"
SINAIS = "platform.fraud_signals"
COBRANCAS = "platform.payment_charges"

#: Os dois papeis do M-1. **Nao ha `cliente`**: o cliente nunca confirma, e o
#: que o garante nao e a falta de um valor de dominio (que so impediria de o
#: escrever na coluna) mas a guarda da `manual_confirmar`, que recusa um
#: `actor_contact_id` igual ao contacto que declarou o pagamento.
PAPEIS = ("'dono'", "'funcionario'")

#: As cinco fases do §6.3.
FASES = (
    "'declaracao_cliente'",
    "'confirmacao'",
    "'segunda_aprovacao'",
    "'rejeicao'",
    "'reversao'",
)

#: As duas fases que **concluem** uma confirmacao, e sao as que o G8 exige.
FASES_QUE_CONCLUEM = ("'confirmacao'", "'segunda_aprovacao'")

#: Os quatro estados de `refund_cases.estado` do §6.3.
ESTADOS_DE_REEMBOLSO = (
    "'aberto'",
    "'a_executar_pela_pme'",
    "'concluido'",
    "'recusado'",
)

#: As cinco accoes de `fraud_signals.accao` do §6.3.
ACCOES = (
    "'registar'",
    "'reter_confirmacao'",
    "'exigir_dupla'",
    "'bloquear_contacto'",
    "'suspender_manual'",
)

#: O rotulo obrigatorio de `evidencia_ref` (M-7). O `CHECK` impo-e: nao ha como
#: gravar um anexo do cliente sem dizer, no proprio registo, que ele nao prova
#: pagamento nenhum.
ROTULO_NAO_PROVA = "nao_prova:%"

#: As duas regras de `fraud_signals` que este ticket escreve, as do M-3.
REGRA_DIARIA = "manual_limite_diario"
REGRA_POR_CONTACTO = "manual_limite_por_contacto_24h"

#: *Proposta*: o §6.3 fixa a escala de 1 a 5 e **nao** fixa o valor de cada
#: regra. Calibra-se no KAM-060 com dados do Piloto.
SEVERIDADE_DO_M3 = 3

#: As duas chaves de janela do M-3. Sao `tecto_por_janela` no
#: `registry/entitlement_keys.schema.json`, e e por isso que o `exigirTecto` do
#: KAM-009 levanta para elas: o agregado nao esta na `platform.tenant_usage`,
#: que tem periodo mensal por `CHECK` e nao tem dimensao de contacto.
CHAVE_DIARIA = "manual_daily_max_minor"
CHAVE_POR_CONTACTO = "manual_max_por_contacto_24h"
CHAVE_DUPLA = "manual_dupla_acima_minor"

#: O fuso em que «o dia» e um dia. A convencao do conjunto e datas em UTC e
#: apresentacao em `Africa/Luanda`, e um tecto **diario** e uma regra de
#: negocio sobre o dia de quem vende — a mesma escolha da
#: `platform.ten_periodo` da `0007`, que conta o mes neste fuso.
FUSO = "Africa/Luanda"

PAPEL_DA_APP = "kamba_app"
PAPEL_DE_LOTE = "kamba_batch"
PAPEL_DE_AUDITORIA = "kamba_audit"

#: A assinatura de `next_state`, para o `COMMENT` e o `GRANT`. A mesma da
#: `0029`: o `CREATE OR REPLACE` nao a muda, e se a mudasse nao era um
#: `REPLACE`.
ARGUMENTOS_DE_NEXT_STATE = "text, text, text"

#: Os tipos de evento que **nunca** movem o estado. **A mesma lista da `0029`**,
#: letra por letra: o `confirmacao_manual_revertida` nunca esteve aqui — estava
#: nos dezassete tipos e sem aresta nenhuma, isto e, era recusado. O que esta
#: revisao faz e dar-lhe a aresta, e nao tirar-lhe nada desta lista.
EVENTOS_SEM_TRANSICAO = (
    "'cobranca_criada'",
    "'pagamento_recebido'",
    "'pagamento_orfao'",
    "'pagamento_duplicado'",
    "'confirmacao_manual_registada'",
    "'ajuste_reconciliacao'",
)


def upgrade() -> None:
    _confirmadores()
    _confirmacoes()
    _reembolsos()
    _sinais()
    _janela()
    _next_state()
    _g8_humano()
    _declarar()
    _confirmar()
    _expirar()
    _reverter()
    _rls()
    _privilegios()


def downgrade() -> None:
    op.execute("DROP FUNCTION platform.manual_reverter(uuid, uuid, text, text)")
    op.execute("DROP FUNCTION platform.manual_expirar_confirmacao(uuid, integer)")
    op.execute("DROP FUNCTION platform.manual_confirmar(uuid, uuid, text, bigint)")
    op.execute("DROP FUNCTION platform.manual_declarar(uuid, uuid, text, text)")
    # O G8 sai pelo *trigger* e pela funcao dele; a `next_state` volta ao corpo
    # da `0029` **pela mesma via** (`CREATE OR REPLACE`) e nao por `DROP`: ha
    # `GRANT`s e uma dependencia (a `append_payment_event` chama-a) penduradas
    # nela, e um `DROP` sem `CASCADE` falhava enquanto um com `CASCADE` levava
    # os `GRANT`s consigo — o que deixava a base a correr com privilegios
    # diferentes dos que a `0029` escreveu, e isso nao e um `downgrade`.
    op.execute("DROP TRIGGER payment_events_g8_humano ON platform.payment_events")
    op.execute("DROP FUNCTION platform.exigir_fase_manual()")
    _next_state_da_0029()
    op.execute("DROP FUNCTION platform.manual_janela(uuid, uuid, timestamptz)")
    # **A RLS desliga-se pelo inverso exacto, e nao pelo efeito do `DROP
    # TABLE`.** As politicas caiam de qualquer forma com as tabelas, pelo que
    # estas quatro linhas nao mudam o estado final — mudam o que a revisao
    # **diz**: o `downgrade` passa a ser o espelho do `upgrade`, linha a linha,
    # e e a forma que a `0029` e a `0030` usam nas suas.
    #
    # E ha uma segunda razao, que foi o CI a encontrar e nao a leitura. O
    # `canon_lint` segue o auxiliar `db/rls.py` por AST e atribui a cada achado
    # **por onde** chegou; o `test_auxiliar_que_deixa_de_se_seguir` deriva por
    # texto a lista das revisoes que o chamam e exige que todas, menos a `0006`,
    # o alcancem **directamente**. Sem estas linhas, o unico caminho desta
    # revisao ao auxiliar era o embrulho `_rls()`, como na `0006` — e a revisao
    # caia do lado errado de uma afirmacao que nao e sobre ela: a de que uma
    # chamada indirecta ao auxiliar e a excepcao de uma revisao so.
    rls.disable_tenant_rls("fraud_signals")
    rls.disable_tenant_rls("refund_cases")
    rls.disable_tenant_rls("manual_confirmations")
    rls.disable_tenant_rls("payment_confirmers")
    op.execute("DROP TABLE " + SINAIS)
    op.execute("DROP TABLE " + REEMBOLSOS)
    op.execute("DROP TABLE " + CONFIRMACOES)
    op.execute("DROP TABLE " + CONFIRMADORES)


# ------------------------------------------------------------------ tabelas


def _confirmadores() -> None:
    """`payment_confirmers`: a unica resposta a «quem confirma» (M-1).

    A chave primaria e `(tenant_id, contact_id)` e nao um `id` proprio, como o
    §6.2 a escreve: a pergunta que esta tabela responde e «este contacto deste
    tenant pode confirmar?», e uma chave composta torna a resposta um acesso
    unico em vez de uma procura que pode devolver duas linhas em desacordo.

    **A FK do contacto e para `platform.contacts(contact_id)`**, e e o que liga
    isto ao BSUID: o `contact_id` e a referencia opaca que o CHR resolve a
    partir do BSUID do canal (KAM-008, KAM-014). Nao ha coluna de telefone nem
    de nome nesta tabela, e nao e omissao — e a razao pela qual «sou o dono»
    escrito numa mensagem nao tem por onde entrar.
    """
    op.execute(
        f"""
        CREATE TABLE {CONFIRMADORES} (
          tenant_id              uuid NOT NULL,
          contact_id             uuid NOT NULL,
          papel                  text NOT NULL,
          pode_segunda_aprovacao boolean NOT NULL DEFAULT false,
          ativo                  boolean NOT NULL DEFAULT true,
          criado_at              timestamptz NOT NULL DEFAULT now(),
          CONSTRAINT payment_confirmers_pk PRIMARY KEY (tenant_id, contact_id),
          CONSTRAINT payment_confirmers_tenant_fk FOREIGN KEY (tenant_id)
            REFERENCES platform.tenants(id),
          CONSTRAINT payment_confirmers_contact_fk FOREIGN KEY (contact_id)
            REFERENCES platform.contacts(contact_id),
          CONSTRAINT payment_confirmers_papel_ck
            CHECK (papel IN ({", ".join(PAPEIS)}))
        )
        """
    )
    op.execute(
        f"COMMENT ON TABLE {CONFIRMADORES} IS "
        "'Quem pode confirmar um pagamento no ManualProvider (docs/tecnica/04 "
        "secao 4.2 M-1; KAM-054). O sender identifica-se pelo BSUID do canal do "
        "tenant, resolvido a contact_id, e nunca pelo texto da mensagem. O "
        "cliente nunca confirma, e o que o garante e a guarda da "
        "manual_confirmar e nao a falta de um papel.'"
    )
    op.execute(
        f"COMMENT ON COLUMN {CONFIRMADORES}.ativo IS "
        "'Um confirmador desactivado e indistinguivel de um que nao existe, "
        "para efeitos de M-1: as duas leituras dao confirmacao_manual_rejeitada. "
        "Retirar um funcionario e pôr isto a false, nao apagar a linha, e a "
        "linha fica para a auditoria.'"
    )
    op.execute(
        f"COMMENT ON COLUMN {CONFIRMADORES}.pode_segunda_aprovacao IS "
        "'A marca do M-5. Nao basta sozinha: acima de manual_dupla_acima_minor a "
        "conclusao exige outro confirmador com esta marca, e o mesmo contacto "
        "nao aprova duas vezes.'"
    )


def _confirmacoes() -> None:
    """`manual_confirmations`: a auditoria total do M-6, fase a fase.

    ## O `UNIQUE (charge_id, canal_msg_id)` e a idempotencia do criterio 9

    E *proposta* dos «Detalhes Tecnicos» do bloco («acrescenta-se
    `UNIQUE (charge_id, canal_msg_id)` como indice de idempotencia (proposta,
    regista-se no PR)»), e esta registada no PR como ele manda.

    **E o par e nao o `canal_msg_id` so.** O mesmo identificador de mensagem
    noutra cobranca e outro facto — e nada garante que os identificadores de
    mensagem de dois canais nao colidam, porque vem da Meta e nao de nos. Com a
    unicidade global, uma colisao fazia a segunda cobranca recusar uma
    confirmacao legitima e o dono via «ja confirmou» sobre um pedido que nunca
    tocou.

    ## Nenhum papel de aplicacao tem `UPDATE` nem `DELETE`

    Uma fase escrita nao se reescreve: o que corrige uma confirmacao e **outra
    fase** — a `reversao` —, que e o M-8 por extenso («sem retroacao
    silenciosa»). A barreira aqui e de privilegio e nao de *trigger*, e a
    diferenca face a `payment_events` e deliberada: o ledger e tambem a prova
    criptografica (cadeia de *hashes*) e por isso recusa a mutacao **ao
    superutilizador**; este registo e a prova documental, e o que ele precisa e
    de nao ter porta de escrita aberta a aplicacao. Pôr-lhe um `deny_mutation`
    com `ENABLE ALWAYS` tornava-o impossivel de limpar nas suites de isolamento,
    que e a razao escrita pela qual a `audit_log` e o `order_state_log` estao em
    `SEM_RECEITA_COM_RAZAO` — e perder a receita de sementes das duas tabelas
    deste ticket custava mais do que a barreira ganhava, porque e a receita que
    poe os casos cruzados do X-03/X-04 a correr sobre elas.
    """
    op.execute(
        f"""
        CREATE TABLE {CONFIRMACOES} (
          id                    uuid PRIMARY KEY DEFAULT gen_random_uuid(),
          tenant_id             uuid NOT NULL,
          charge_id             uuid NOT NULL,
          fase                  text NOT NULL,
          actor_contact_id      uuid NOT NULL,
          canal_msg_id          text NOT NULL,
          valor_declarado_minor bigint,
          valor_bate            boolean,
          evidencia_ref         text,
          motivo                text,
          criado_at             timestamptz NOT NULL DEFAULT now(),
          CONSTRAINT manual_confirmations_msg_uq UNIQUE (charge_id, canal_msg_id),
          CONSTRAINT manual_confirmations_tenant_fk FOREIGN KEY (tenant_id)
            REFERENCES platform.tenants(id),
          CONSTRAINT manual_confirmations_charge_fk FOREIGN KEY (charge_id)
            REFERENCES {COBRANCAS}(id),
          CONSTRAINT manual_confirmations_actor_fk FOREIGN KEY (actor_contact_id)
            REFERENCES platform.contacts(contact_id),
          CONSTRAINT manual_confirmations_fase_ck
            CHECK (fase IN ({", ".join(FASES)})),
          CONSTRAINT manual_confirmations_valor_ck
            CHECK (valor_declarado_minor IS NULL OR valor_declarado_minor >= 0),
          CONSTRAINT manual_confirmations_evidencia_ck
            CHECK (evidencia_ref IS NULL
                   OR evidencia_ref LIKE '{ROTULO_NAO_PROVA}')
        )
        """
    )
    op.execute(
        "CREATE INDEX manual_confirmations_charge_idx ON "
        + CONFIRMACOES
        + " (charge_id, criado_at)"
    )
    op.execute(
        "CREATE INDEX manual_confirmations_janela_idx ON "
        + CONFIRMACOES
        + " (tenant_id, fase, criado_at)"
    )
    op.execute(
        f"COMMENT ON TABLE {CONFIRMACOES} IS "
        "'Cada fase da confirmacao manual, com actor, canal_msg_id, valor "
        "declarado e hora (docs/tecnica/04 secao 4.2 M-6; KAM-054). Escrita so "
        "pelas quatro funcoes manual_*, que sao SECURITY DEFINER: nenhum papel "
        "de aplicacao tem INSERT, UPDATE ou DELETE. Uma fase escrita nao se "
        "reescreve — o que corrige uma confirmacao e a fase reversao.'"
    )
    op.execute(
        f"COMMENT ON COLUMN {CONFIRMACOES}.evidencia_ref IS "
        "'O anexo do cliente, com o rotulo nao_prova imposto por CHECK (M-7). O "
        "rotulo e o ponto e nao um detalhe de formato: um comprovativo enviado "
        "por WhatsApp nao prova pagamento nenhum (fraude CONFIRMADA em "
        "docs/tecnica/evidencia/E2 secao 4), e o sistema di-lo por escrito no "
        "proprio registo. Nenhum modulo do ManualProvider le o conteudo.'"
    )
    op.execute(
        f"COMMENT ON COLUMN {CONFIRMACOES}.valor_bate IS "
        "'O desafio do valor do M-4: valor_declarado_minor = "
        "payment_charges.amount_minor, sem tolerancia. Anulavel porque a fase "
        "declaracao_cliente nao tem valor declarado nenhum.'"
    )


def _reembolsos() -> None:
    """`refund_cases`: o registo de um processo que corre fora da plataforma.

    O ADR-004 e a G-6 do §10.4: a plataforma **nao detem fundos** e **nao
    reembolsa**. Esta tabela nao executa movimento nenhum — registra um caso,
    e quem o executa e a PME a partir da conta dela, que e o que o estado
    `a_executar_pela_pme` diz por extenso.

    O `CHECK` de exclusividade — exactamente um de `order_id`/`charge_id` —
    **nao** esta no §6.3, que faz as duas colunas anulaveis sem dizer nada. Entra
    porque um caso sem nenhum dos dois nao e um caso de nada: nao ha como saber
    o que reembolsar. As **FK** e que ficam para o KAM-055, pela razao escrita na
    `0029` para o par `order_id`/`billing_cycle_id` da `payment_charges`: pôr a
    FK de `order_id` so num dos dois lados deixava o par incoerente.
    """
    op.execute(
        f"""
        CREATE TABLE {REEMBOLSOS} (
          id          uuid PRIMARY KEY DEFAULT gen_random_uuid(),
          tenant_id   uuid NOT NULL,
          order_id    uuid,
          charge_id   uuid,
          motivo      text NOT NULL,
          valor_minor bigint NOT NULL,
          estado      text NOT NULL DEFAULT 'aberto',
          prova_ref   text,
          criado_at   timestamptz NOT NULL DEFAULT now(),
          fechado_at  timestamptz,
          CONSTRAINT refund_cases_tenant_fk FOREIGN KEY (tenant_id)
            REFERENCES platform.tenants(id),
          CONSTRAINT refund_cases_charge_fk FOREIGN KEY (charge_id)
            REFERENCES {COBRANCAS}(id),
          CONSTRAINT refund_cases_valor_ck CHECK (valor_minor > 0),
          CONSTRAINT refund_cases_estado_ck
            CHECK (estado IN ({", ".join(ESTADOS_DE_REEMBOLSO)})),
          CONSTRAINT refund_cases_um_sujeito
            CHECK (order_id IS NOT NULL OR charge_id IS NOT NULL),
          CONSTRAINT refund_cases_fechado
            CHECK ((estado IN ('concluido', 'recusado')) = (fechado_at IS NOT NULL))
        )
        """
    )
    op.execute(
        "CREATE INDEX refund_cases_tenant_idx ON "
        + REEMBOLSOS
        + " (tenant_id, estado, criado_at)"
    )
    op.execute(
        f"COMMENT ON TABLE {REEMBOLSOS} IS "
        "'Caso de reembolso (docs/tecnica/04 secao 6.3, M-8; ADR-004, G-6; "
        "KAM-054). Processo manual fora da plataforma: a KAMBA nao detem fundos "
        "e o refund() do adaptador devolve NOT_SUPPORTED por decisao e nao por "
        "estar por fazer. As FK de order_id ficam para o KAM-055, com a da "
        "payment_charges.'"
    )


def _sinais() -> None:
    """`fraud_signals`: o motor de sinais do §9, com as duas regras do M-3.

    Este ticket escreve **duas** regras — `manual_limite_diario` e
    `manual_limite_por_contacto_24h` —, e e por isso que a tabela nasce aqui: o
    criterio 6 escreve nela. As regras de **anomalia** (valor divergente,
    duplicados, padroes) sao do KAM-060, que nao acrescenta tabela.

    O `detalhe jsonb` leva a identificacao da confirmacao e o motivo, e **nao**
    leva telefone nem texto de mensagem: a caixa de privacidade do DoD. O
    contacto vai por `contact_id`.
    """
    op.execute(
        f"""
        CREATE TABLE {SINAIS} (
          id         bigint GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
          tenant_id  uuid NOT NULL,
          contact_id uuid,
          charge_id  uuid,
          regra      text NOT NULL,
          severidade smallint NOT NULL,
          accao      text NOT NULL,
          detalhe    jsonb NOT NULL DEFAULT '{{}}',
          criado_at  timestamptz NOT NULL DEFAULT now(),
          CONSTRAINT fraud_signals_tenant_fk FOREIGN KEY (tenant_id)
            REFERENCES platform.tenants(id),
          CONSTRAINT fraud_signals_contact_fk FOREIGN KEY (contact_id)
            REFERENCES platform.contacts(contact_id),
          CONSTRAINT fraud_signals_charge_fk FOREIGN KEY (charge_id)
            REFERENCES {COBRANCAS}(id),
          CONSTRAINT fraud_signals_severidade_ck
            CHECK (severidade BETWEEN 1 AND 5),
          CONSTRAINT fraud_signals_accao_ck
            CHECK (accao IN ({", ".join(ACCOES)}))
        )
        """
    )
    op.execute(
        "CREATE INDEX fraud_signals_tenant_idx ON "
        + SINAIS
        + " (tenant_id, criado_at)"
    )
    op.execute(
        f"COMMENT ON TABLE {SINAIS} IS "
        "'Sinais do motor determinista do docs/tecnica/04 secao 9. O KAM-054 "
        "escreve duas regras, as do M-3, com accao reter_confirmacao; as regras "
        "de anomalia sao do KAM-060. O detalhe nao leva telefone nem texto de "
        "mensagem: o contacto vai por contact_id.'"
    )


# ------------------------------------------------------------------ funcoes


def _janela() -> None:
    """`manual_janela`: o agregado que o KAM-009 nao sabia calcular.

    O `exigirTecto` do `ten` levanta para as duas chaves de janela e escreve
    porque: «o agregado da janela **nao esta em `platform.tenant_usage`** — a
    chave dessa tabela e `(tenant_id, chave_limite, periodo)` com `periodo`
    mensal por `CHECK`, sem dimensao de contacto e sem janela movel. Calcula-se
    de `manual_confirmations`, que este ticket nao constroi.» Constroi-o este.

    ## As duas janelas sao de formas diferentes, e e isso que as separa

        diario        **soma de dinheiro** por tenant, no dia de Africa/Luanda
        por contacto  **contagem** de cobrancas por contacto, nas ultimas 24 h
                      a contar para tras do instante dado

    Uma e um tecto de valor e a outra um tecto de frequencia, e por isso o
    `tecto_do_contacto` e uma contagem e nao um montante — o nome da chave di-lo
    (`manual_max_por_contacto_24h`, sem `_minor`).

    ## «O contacto» e quem **declarou** o pagamento, e nao quem confirma

    E a dimensao que o §9 nomeia («historico do contacto», na linha do COD
    abusivo e na da auto-compra): o risco e um comprador a juntar confirmacoes,
    nao um dono a confirmar as vendas dele — o dono confirma todas, por
    definicao, e um tecto por confirmador era um tecto de vendas.

    Le-se da fase `declaracao_cliente` da propria cobranca, o que torna isto
    auto-contido: nao depende da `orders_mirror` nem de uma FK que e do
    KAM-055, e a resposta a «quem e o cliente desta cobranca» passa a ter **uma**
    fonte, que e a mesma que a guarda do M-1 usa.

    ## Uma confirmacao revertida continua a contar

    Nao se subtrai a reversao da soma do dia, e e escolha e nao esquecimento: um
    tecto anti-fraude conta o que **aconteceu**, e uma confirmacao que foi
    revertida aconteceu — e, se houve reversao, ha mais razao para o dia estar
    perto do tecto e nao menos. Quem quiser a soma liquida tem-na pela juncao
    com a fase `reversao`, que esta la.

    `STABLE SECURITY INVOKER`: le tabelas e **nao** precisa de privilegio que o
    chamador nao tenha. E a razao pela qual nao entra no
    `ci/secdef_allowlist.yaml`.
    """
    op.execute(
        f"""
        CREATE FUNCTION platform.manual_janela(
          p_tenant_id uuid, p_contact_id uuid,
          p_agora timestamptz DEFAULT now())
        RETURNS TABLE (
          soma_do_dia_minor        bigint,
          tecto_diario_minor       bigint,
          confirmacoes_do_contacto bigint,
          tecto_do_contacto        bigint)
        LANGUAGE sql STABLE SECURITY INVOKER
        SET search_path = pg_catalog, platform AS $func$
          SELECT
            coalesce((
              SELECT sum(c.amount_minor) FROM {COBRANCAS} c
               WHERE c.id IN (
                 SELECT m.charge_id FROM {CONFIRMACOES} m
                  WHERE m.tenant_id = p_tenant_id
                    AND m.fase IN ({", ".join(FASES_QUE_CONCLUEM)})
                    AND m.valor_bate
                    AND (m.criado_at AT TIME ZONE '{FUSO}')::date
                        = (p_agora AT TIME ZONE '{FUSO}')::date)), 0)::bigint,
            platform.ten_tecto(p_tenant_id, '{CHAVE_DIARIA}'),
            (SELECT count(DISTINCT m.charge_id) FROM {CONFIRMACOES} m
              WHERE m.tenant_id = p_tenant_id
                AND m.fase IN ({", ".join(FASES_QUE_CONCLUEM)})
                AND m.valor_bate
                AND m.criado_at > p_agora - interval '24 hours'
                AND EXISTS (
                  SELECT 1 FROM {CONFIRMACOES} d
                   WHERE d.charge_id = m.charge_id
                     AND d.fase = 'declaracao_cliente'
                     AND d.actor_contact_id = p_contact_id))::bigint,
            platform.ten_tecto(p_tenant_id, '{CHAVE_POR_CONTACTO}')
        $func$
        """
    )
    op.execute(
        "COMMENT ON FUNCTION platform.manual_janela(uuid, uuid, timestamptz) IS "
        "'O agregado das duas janelas do M-3 (KAM-054): a soma de dinheiro "
        "confirmada no dia de Africa/Luanda por tenant, e a contagem de "
        "cobrancas confirmadas nas ultimas 24 h cujo pagamento foi declarado por "
        "este contacto. Os dois tectos vem da platform.ten_tecto, que e a mesma "
        "funcao que o checkCeiling do ten chama — e NULL nega, porque sem tecto "
        "nao quer dizer sem limite.'"
    )


def _next_state() -> None:
    """A quinta aresta do §7.1, e a `0029` escreveu quem a devia pôr.

    O comentario do `_next_state` da `0029` lista tres arestas que faltavam e da
    a razao de cada uma. A primeira:

        paga --> reembolso_pendente: disputa
            Nao ha tipo de evento para «disputa» nos dezassete do §6.2. Abrir um
            caso de disputa e `refund_cases` (§6.3), que e do KAM-054. Sem
            evento, nao ha aresta — e inventar um tipo era alargar o escopo.

    Com a `refund_cases` a existir, o evento que faltava **ja esta** nos
    dezassete: e o `confirmacao_manual_revertida` do M-8. A aresta entra, e
    nao se inventa tipo nenhum — que era a condicao que a `0029` pôs.

    **As outras duas continuam de fora**, e por `CREATE OR REPLACE` ser o
    contrario de uma reescrita oportunista: o §7.1 desenha a divergencia so a
    partir de `emitida`, as duas lacunas sao do documento e estao na divida
    documental, e fecha-las aqui era decidir por quem escreve o §7.1.

    `CREATE OR REPLACE` e nao `DROP` + `CREATE`: ha `GRANT`s e uma dependencia
    (a `append_payment_event` chama-a) penduradas nesta funcao. Um `DROP` sem
    `CASCADE` falhava; com `CASCADE` levava os `GRANT`s consigo, e a base ficava
    a correr com privilegios diferentes dos que a `0029` escreveu.
    """
    _escrever_next_state(
        extra=(
            "            -- paga: a reversao auditada do M-8 (KAM-054). A\n"
            "            -- `refund_cases` abre-se na mesma transaccao, pela\n"
            "            -- `manual_reverter`; nada se apaga.\n"
            "            WHEN p_estado = 'paga'\n"
            "                 AND p_tipo_evento = 'confirmacao_manual_revertida'\n"
            "              THEN 'reembolso_pendente'\n"
        ),
        comentario=(
            "A maquina de estados da cobranca (docs/tecnica/04 secao 7.1), pura "
            "(KAM-053, quinta aresta pelo KAM-054). Devolve o estado novo numa "
            "aresta, o mesmo estado num facto que nao move, e NULL numa "
            "transicao recusada. Para paga ha um caminho so: pagamento_confirmado "
            "com decisao aceite. De paga sai a reversao do M-8, por "
            "confirmacao_manual_revertida."
        ),
    )


def _next_state_da_0029() -> None:
    """A `next_state` como a `0029` a escreveu, para o `downgrade`."""
    _escrever_next_state(
        extra="",
        comentario=(
            "A maquina de estados da cobranca (docs/tecnica/04 secao 7.1), pura "
            "(KAM-053). Devolve o estado novo numa aresta, o mesmo estado num "
            "facto que nao move, e NULL numa transicao recusada. Para paga ha um "
            "caminho so: pagamento_confirmado com decisao aceite, que e o unico "
            "que passa pela restricao confirmar_exige_autenticacao."
        ),
    )


def _escrever_next_state(extra: str, comentario: str) -> None:
    """O corpo da `next_state`, com zero ou uma aresta a mais.

    Escrito **uma** vez e usado nos dois sentidos, pela razao da `0031`: um
    `downgrade` que reescrevesse o corpo a mao deixava duas versoes da mesma
    maquina no mesmo ficheiro, e a que vale depende de quem leu qual.
    """
    op.execute(
        f"""
        CREATE OR REPLACE FUNCTION platform.next_state(
          p_estado text, p_tipo_evento text, p_decisao text)
        RETURNS text LANGUAGE sql IMMUTABLE STRICT
        SET search_path = pg_catalog, platform AS $func$
          SELECT CASE
            WHEN p_tipo_evento IN ({", ".join(EVENTOS_SEM_TRANSICAO)})
              THEN p_estado

            WHEN p_estado = 'iniciada' AND p_tipo_evento = 'referencia_emitida'
              THEN 'emitida'
            WHEN p_estado = 'iniciada' AND p_tipo_evento = 'push_enviado'
              THEN 'aguarda_cliente'
            WHEN p_estado = 'iniciada' AND p_tipo_evento = 'pagamento_rejeitado_provider'
              THEN 'falhada'

            WHEN p_estado = 'emitida' AND p_tipo_evento = 'confirmacao_manual_pedida'
              THEN 'pendente_confirmacao'
            WHEN p_estado = 'emitida' AND p_tipo_evento = 'pagamento_confirmado'
                 AND p_decisao = 'aceite'
              THEN 'paga'
            WHEN p_estado = 'emitida' AND p_tipo_evento = 'pagamento_divergente'
              THEN 'falhada'
            WHEN p_estado = 'emitida' AND p_tipo_evento = 'cobranca_expirada'
              THEN 'expirada'
            WHEN p_estado = 'emitida' AND p_tipo_evento = 'cobranca_cancelada'
              THEN 'cancelada'

            WHEN p_estado = 'aguarda_cliente' AND p_tipo_evento = 'pagamento_confirmado'
                 AND p_decisao = 'aceite'
              THEN 'paga'
            WHEN p_estado = 'aguarda_cliente' AND p_tipo_evento = 'cobranca_expirada'
              THEN 'expirada'
            WHEN p_estado = 'aguarda_cliente'
                 AND p_tipo_evento = 'pagamento_rejeitado_provider'
              THEN 'falhada'

            WHEN p_estado = 'pendente_confirmacao'
                 AND p_tipo_evento = 'pagamento_confirmado' AND p_decisao = 'aceite'
              THEN 'paga'
            WHEN p_estado = 'pendente_confirmacao'
                 AND p_tipo_evento = 'confirmacao_manual_rejeitada'
              THEN 'emitida'

            WHEN p_estado = 'expirada' AND p_tipo_evento = 'pagamento_confirmado'
                 AND p_decisao = 'aceite'
              THEN 'paga'

            WHEN p_estado = 'falhada' AND p_tipo_evento = 'pagamento_confirmado'
                 AND p_decisao = 'aceite'
              THEN 'paga'

{extra}
            WHEN p_estado = 'reembolso_pendente'
                 AND p_tipo_evento = 'reembolso_manual_registado'
              THEN 'reembolsada'

            ELSE NULL
          END
        $func$
        """
    )
    op.execute(
        f"COMMENT ON FUNCTION platform.next_state({ARGUMENTOS_DE_NEXT_STATE}) IS "
        f"'{comentario}'"
    )


def _g8_humano() -> None:
    """O G8 do §5, como *trigger* `BEFORE INSERT` sobre `payment_events`.

    Ver o cabecalho desta revisao para a razao de ser um *trigger* e nao um
    bloco dentro da `append_payment_event`.

    **`ENABLE ALWAYS`**, pela licao da `0006` que a `0030` e a `0031` herdaram:
    um *trigger* nasce na omissao (`O`), e a omissao e saltada por
    `session_replication_role = replica`. Sem esta linha, um superutilizador que
    ponha a sessao em `replica` confirma um pagamento por via humana sem fase
    nenhuma, e nada no catalogo diz que isso e possivel.

    **Nao e `FOR EACH STATEMENT`**, ao contrario do `payment_events_sem_truncate`
    da `0029`, e a razao e a inversa da que lá esta escrita: aquele recusa uma
    instrucao **inteira** e por isso ganha em recusar antes de haver linhas;
    este tem de olhar para **cada** linha (o `tipo_evento`, o `authn_method` e o
    `actor_id` sao da linha), e um *trigger* por instrucao nao tem `NEW`. Um
    `INSERT` que nao escreve linha nenhuma nao confirma pagamento nenhum, pelo
    que aqui nao ha a lacuna que o KAM-175 e o KAM-176 fecharam.
    """
    op.execute(
        f"""
        CREATE FUNCTION platform.exigir_fase_manual() RETURNS trigger
        LANGUAGE plpgsql
        SET search_path = pg_catalog, platform AS $func$
        BEGIN
          IF NEW.tipo_evento <> 'pagamento_confirmado'
             OR NEW.authn_method <> 'manual' THEN
            RETURN NEW;
          END IF;
          -- O `actor_id` nao nulo ja e do `humano_exige_actor` da `0029`; o que
          -- se exige aqui e que ele **bate** com o actor da fase. Sem essa
          -- igualdade, uma confirmacao legitima do dono A deixava passar um
          -- evento com `actor_id` = B, e a atribuicao do acto humano no ledger
          -- deixava de ser verificavel — que e precisamente o que o M-6 existe
          -- para garantir.
          IF NOT EXISTS (
            SELECT 1 FROM {CONFIRMACOES} m
             WHERE m.charge_id = NEW.charge_id
               AND m.fase IN ({", ".join(FASES_QUE_CONCLUEM)})
               AND m.valor_bate
               AND m.actor_contact_id = NEW.actor_id) THEN
            RAISE EXCEPTION
              'G8: nao se confirma a cobranca % por via humana sem uma fase de '
              'manual_confirmations desta cobranca, com valor_bate e com o '
              'actor %, escrita pelas funcoes manual_* (docs/tecnica/04 secao 5)',
              NEW.charge_id, NEW.actor_id
              USING ERRCODE = 'check_violation';
          END IF;
          RETURN NEW;
        END $func$
        """
    )
    op.execute(
        "COMMENT ON FUNCTION platform.exigir_fase_manual() IS "
        "'O G8 do docs/tecnica/04 secao 5 para o caminho humano (KAM-054): um "
        "pagamento_confirmado com authn_method manual exige, na mesma "
        "transaccao, uma fase de manual_confirmations desta cobranca que conclua, "
        "com valor_bate e com o mesmo actor. SECURITY INVOKER: le a tabela sob a "
        "RLS de quem chama, e a fase e do mesmo tenant que a cobranca.'"
    )
    op.execute(
        """
        CREATE TRIGGER payment_events_g8_humano
          BEFORE INSERT ON platform.payment_events
          FOR EACH ROW EXECUTE FUNCTION platform.exigir_fase_manual()
        """
    )
    op.execute(
        "ALTER TABLE platform.payment_events "
        "ENABLE ALWAYS TRIGGER payment_events_g8_humano"
    )


def _declarar() -> None:
    """`manual_declarar`: a declaracao do cliente, e **so** registo (criterio 3).

    «A declaracao "paguei" (texto ou imagem) **so** cria
    `manual_confirmations.fase='declaracao_cliente'` e a cobranca
    `pendente_confirmacao`.» O «so» e o criterio inteiro, e esta funcao e onde
    ele se cumpre: nao ha por onde ela confirmar um pagamento, porque nao
    escreve `pagamento_confirmado` nenhum — a restricao
    `confirmar_exige_autenticacao` nem chega a ser avaliada.

    A imagem arquiva-se com o rotulo `nao_prova`, imposto pelo `CHECK` da
    coluna, e **o conteudo nunca se le**: esta funcao recebe uma referencia de
    anexo e nao tem como abrir nada. Do lado da aplicacao a mesma propriedade
    mede-se por varredura de importacoes (criterio 3), com passo de canario.

    ## A idempotencia e por `(charge_id, canal_msg_id)` e devolve o que existe

    A mesma mensagem processada duas vezes produz **uma** confirmacao (criterio
    9). A segunda chamada nao levanta e nao escreve: le a linha e devolve-a com
    `repetida = true`. Levantar era pior — quem reentrega uma mensagem (o CHR,
    por retentativa) teria de distinguir «ja estava» de «falhou», e a unica
    forma de o fazer era apanhar um `23505` pelo nome da restricao.

    O `ON CONFLICT` nao serve aqui: precisamos de saber **se** era repetida para
    nao escrever o evento, e um `ON CONFLICT DO NOTHING` nao distingue a linha
    inserida da nao inserida sem um segundo `SELECT`. Com o `FOR UPDATE` da
    cobranca a serializar, a leitura previa e suficiente e e mais clara.
    """
    op.execute(
        f"""
        CREATE FUNCTION platform.manual_declarar(
          p_charge_id uuid,
          p_actor_contact_id uuid,
          p_canal_msg_id text,
          p_evidencia_ref text DEFAULT NULL)
        RETURNS TABLE (
          confirmacao_id uuid, event_id bigint, estado_novo text,
          repetida boolean)
        LANGUAGE plpgsql SECURITY DEFINER
        SET search_path = pg_catalog, platform AS $func$
        DECLARE
          v_charge  platform.payment_charges;
          v_id      uuid;
          v_event   bigint;
          v_estado  text;
        BEGIN
          SELECT * INTO v_charge FROM {COBRANCAS}
            WHERE id = p_charge_id FOR UPDATE;
          IF NOT FOUND THEN
            RAISE EXCEPTION
              'manual_declarar: a cobranca % nao existe ou nao e visivel no '
              'contexto desta transaccao (RLS)', p_charge_id
              USING ERRCODE = 'check_violation';
          END IF;

          SELECT m.id INTO v_id FROM {CONFIRMACOES} m
            WHERE m.charge_id = p_charge_id AND m.canal_msg_id = p_canal_msg_id;
          IF v_id IS NOT NULL THEN
            RETURN QUERY SELECT v_id, NULL::bigint, v_charge.estado, true;
            RETURN;
          END IF;

          INSERT INTO {CONFIRMACOES} (
              tenant_id, charge_id, fase, actor_contact_id, canal_msg_id,
              evidencia_ref)
            VALUES (
              v_charge.tenant_id, p_charge_id, 'declaracao_cliente',
              p_actor_contact_id, p_canal_msg_id, p_evidencia_ref)
            RETURNING id INTO v_id;

          SELECT a.event_id, a.estado_novo INTO v_event, v_estado
            FROM platform.append_payment_event(
              p_charge_id => p_charge_id,
              p_tipo_evento => 'confirmacao_manual_pedida',
              p_account_id => v_charge.account_id,
              p_valor_minor => v_charge.amount_minor,
              p_authn_method => 'manual',
              p_authn_ok => false,
              p_decisao => 'informativo',
              p_motivo => 'declaracao_do_cliente_nao_e_prova',
              p_actor_kind => 'sistema',
              p_actor_id => p_actor_contact_id,
              p_payload => jsonb_build_object(
                'confirmacao_id', v_id, 'fase', 'declaracao_cliente',
                'evidencia_rotulada_nao_prova', p_evidencia_ref IS NOT NULL)) a;

          RETURN QUERY SELECT v_id, v_event, v_estado, false;
        END $func$
        """
    )
    op.execute(
        "COMMENT ON FUNCTION platform.manual_declarar(uuid, uuid, text, text) IS "
        "'A declaracao do cliente (KAM-054, criterio 3): cria a fase "
        "declaracao_cliente e poe a cobranca em pendente_confirmacao pelo "
        "confirmacao_manual_pedida, e mais nada. O authn_ok e false de proposito: "
        "uma declaracao do cliente nao e uma origem autenticada, e escrever true "
        "era afirmar o contrario do que o ADR-013 fixa. A imagem fica com o "
        "rotulo nao_prova e o conteudo nunca se le.'"
    )


def _confirmar() -> None:
    """`manual_confirmar`: o acto humano, M-1, M-4, M-3 e M-5 numa transaccao.

    ## A ordem das portas nao e arbitraria

    Cada porta fechada antes da seguinte decide o que um atacante aprende:

        1  o cliente        M-1, e vem **primeiro**. Nem a tabela de
                            confirmadores se consulta: se o contacto do cliente
                            estivesse, por erro de provisionamento, em
                            `payment_confirmers`, a ordem inversa deixava-o
                            confirmar o proprio pagamento — a fraude mais obvia
                            deste caminho e a mais facil de deixar aberta
        2  o confirmador    M-1. Um BSUID fora da tabela, ou `ativo = false`,
                            nao tem efeito nenhum
        3  o desafio        M-4, **antes** dos limites: o valor errado e uma
                            rejeicao e nao uma retencao, e um atacante que
                            recebesse «retido para analise» em vez de «o valor
                            nao bate» aprendia que acertou no valor
        4  os limites       M-3, e **antes** do M-5 porque reter e mais forte do
                            que pedir segunda assinatura: uma cobranca que
                            excede o tecto diario nao se resolve com outra
                            assinatura, resolve-se com ops a olhar para ela
        5  a dupla          M-5, por ultimo. Tudo o que sobra ate aqui e
                            legitimo; o que falta decidir e se **uma**
                            assinatura chega

    A mesma ordem esta no `avaliarConfirmacao` do
    `packages/core-ts/src/pagamentos/manual.ts`, que e o oraculo da suite de
    unidade e a mensagem que o agente mostra ao dono. **A que vale e esta**, e o
    `test_a_tabela_pura_concorda_com_a_base` mede caso a caso que as duas
    concordam contra um PostgreSQL real — nao por leitura.

    ## Quem e «o cliente» le-se da fase `declaracao_cliente`

    E a unica fonte, e torna a guarda do M-1 auto-contida: nao depende da
    `orders_mirror` nem de uma FK que e do KAM-055. Se nao houver declaracao, a
    funcao **recusa** em vez de seguir sem a guarda — que e a diferenca entre
    falhar fechado e ter um caminho em que a verificacao mais importante nao
    corre. E nao e hipotetico que exista sempre: a unica aresta que leva uma
    cobranca a `pendente_confirmacao` e o `confirmacao_manual_pedida`, que so a
    `manual_declarar` escreve.

    ## `null` nega, nos tres tectos

    E a leitura do criterio 2 do KAM-009: «sem tecto» nao quer dizer «sem
    limite». Sem `manual_daily_max_minor` declarado a confirmacao **retem**; sem
    `manual_dupla_acima_minor` declarado **exige** a segunda aprovacao. Nos dois
    casos a leitura fechada e a que nao paga nada por falta de configuracao.
    """
    op.execute(
        f"""
        CREATE FUNCTION platform.manual_confirmar(
          p_charge_id uuid,
          p_actor_contact_id uuid,
          p_canal_msg_id text,
          p_valor_declarado_minor bigint)
        RETURNS TABLE (
          confirmacao_id uuid, event_id bigint, estado_novo text,
          decisao text, motivo text, valor_bate boolean, sinal_id bigint,
          repetida boolean)
        LANGUAGE plpgsql SECURITY DEFINER
        SET search_path = pg_catalog, platform AS $func$
        DECLARE
          v_charge    platform.payment_charges;
          v_existente platform.manual_confirmations;
          v_conf      platform.payment_confirmers;
          v_cliente   uuid;
          v_primeira  uuid;
          v_bate      boolean;
          v_decisao   text;
          v_motivo    text;
          v_fase      text;
          v_regra     text;
          v_tecto     bigint;
          v_janela    record;
          v_id        uuid;
          v_sinal     bigint;
          v_event     bigint;
          v_estado    text;
          v_authn_ok  boolean;
        BEGIN
          SELECT * INTO v_charge FROM {COBRANCAS}
            WHERE id = p_charge_id FOR UPDATE;
          IF NOT FOUND THEN
            RAISE EXCEPTION
              'manual_confirmar: a cobranca % nao existe ou nao e visivel no '
              'contexto desta transaccao (RLS)', p_charge_id
              USING ERRCODE = 'check_violation';
          END IF;

          -- Idempotencia (criterio 9): a mesma mensagem da **uma** confirmacao.
          SELECT * INTO v_existente FROM {CONFIRMACOES}
            WHERE charge_id = p_charge_id AND canal_msg_id = p_canal_msg_id;
          IF FOUND THEN
            RETURN QUERY SELECT
              v_existente.id, NULL::bigint, v_charge.estado,
              CASE v_existente.fase
                WHEN 'rejeicao' THEN 'rejeita'
                WHEN 'segunda_aprovacao' THEN 'confirma'
                ELSE 'confirma' END,
              v_existente.motivo, v_existente.valor_bate, NULL::bigint, true;
            RETURN;
          END IF;

          -- A cobranca tem de estar **a espera de confirmacao**, e esta guarda
          -- fechou um defeito que a concorrencia encontrou.
          --
          -- Medido: duas confirmacoes simultaneas da mesma cobranca. A primeira
          -- paga-a; a segunda entra, ve a fase da primeira, decide
          -- `mesmo_confirmador` (certo) e tenta escrever o
          -- `confirmacao_manual_rejeitada` — que **nao tem aresta** a partir de
          -- `paga`. O resultado era um `23514` do `next_state` com uma mensagem
          -- sobre transicoes, onde a resposta certa e «esta cobranca ja nao
          -- espera confirmacao».
          --
          -- A guarda nao e so uma mensagem melhor: e um buraco a menos. Sem ela,
          -- uma confirmacao sobre uma cobranca `cancelada`, `expirada` ou
          -- `reembolso_pendente` **escrevia a fase** em `manual_confirmations`
          -- antes de o `append_payment_event` recusar — e a fase, com
          -- `valor_bate` verdadeiro, e exactamente o que o G8 exige. Isto e, a
          -- transaccao revertia, mas o desenho dependia de ela reverter.
          --
          -- **`pendente_confirmacao` e o unico estado, e nao uma lista.** E o
          -- unico de que o §7.1 tem aresta nos **dois** sentidos — para `paga`
          -- pelo `pagamento_confirmado` e de volta a `emitida` pelo
          -- `confirmacao_manual_rejeitada` —, pelo que e o unico em que uma
          -- confirmacao pode ser aceita **ou** recusada. As arestas
          -- `falhada -> paga` e `expirada -> paga` do §7.1 existem e continuam
          -- alcancaveis pela via do facilitador (`hmac`, que o G8 nao toca); uma
          -- confirmacao humana de ops a partir delas precisa de passar a
          -- cobranca por `pendente_confirmacao` primeiro, e isso e um fluxo de
          -- reconciliacao que este ticket nao desenha — nao se finge que
          -- desenha.
          IF v_charge.estado <> 'pendente_confirmacao' THEN
            RAISE EXCEPTION
              'manual_confirmar: a cobranca % esta em % e nao espera '
              'confirmacao; so se confirma (ou recusa) uma cobranca em '
              'pendente_confirmacao', p_charge_id, v_charge.estado
              USING ERRCODE = 'check_violation';
          END IF;

          SELECT m.actor_contact_id INTO v_cliente FROM {CONFIRMACOES} m
            WHERE m.charge_id = p_charge_id AND m.fase = 'declaracao_cliente'
            ORDER BY m.criado_at, m.id LIMIT 1;
          IF v_cliente IS NULL THEN
            RAISE EXCEPTION
              'manual_confirmar: a cobranca % nao tem fase declaracao_cliente, '
              'logo nao se sabe quem e o cliente e a guarda do M-1 nao pode '
              'correr; nao ha confirmacao sem declaracao', p_charge_id
              USING ERRCODE = 'check_violation';
          END IF;

          SELECT m.actor_contact_id INTO v_primeira FROM {CONFIRMACOES} m
            WHERE m.charge_id = p_charge_id AND m.fase = 'confirmacao'
              AND m.valor_bate
            ORDER BY m.criado_at, m.id LIMIT 1;

          v_bate := (p_valor_declarado_minor = v_charge.amount_minor);
          v_regra := NULL;

          IF p_actor_contact_id = v_cliente THEN
            v_decisao := 'rejeita'; v_motivo := 'cliente_nao_confirma';
          ELSE
            SELECT * INTO v_conf FROM {CONFIRMADORES}
              WHERE tenant_id = v_charge.tenant_id
                AND contact_id = p_actor_contact_id;
            IF NOT FOUND OR NOT v_conf.ativo THEN
              v_decisao := 'rejeita'; v_motivo := 'sem_confirmador';
            ELSIF v_primeira IS NOT NULL
                  AND v_primeira = p_actor_contact_id THEN
              v_decisao := 'rejeita'; v_motivo := 'mesmo_confirmador';
            ELSIF v_primeira IS NOT NULL
                  AND NOT v_conf.pode_segunda_aprovacao THEN
              v_decisao := 'rejeita'; v_motivo := 'sem_segunda_aprovacao';
            ELSIF NOT v_bate THEN
              v_decisao := 'rejeita'; v_motivo := 'valor_nao_bate';
            ELSE
              SELECT * INTO v_janela FROM platform.manual_janela(
                v_charge.tenant_id, v_cliente, now());
              IF v_janela.tecto_diario_minor IS NULL
                 OR v_janela.soma_do_dia_minor + v_charge.amount_minor
                    > v_janela.tecto_diario_minor THEN
                v_decisao := 'retem'; v_motivo := 'limite_diario';
                v_regra := '{REGRA_DIARIA}';
              ELSIF v_janela.tecto_do_contacto IS NULL
                 OR v_janela.confirmacoes_do_contacto + 1
                    > v_janela.tecto_do_contacto THEN
                v_decisao := 'retem'; v_motivo := 'limite_por_contacto';
                v_regra := '{REGRA_POR_CONTACTO}';
              ELSE
                v_tecto := platform.ten_tecto(
                  v_charge.tenant_id, '{CHAVE_DUPLA}');
                IF (v_tecto IS NULL OR v_charge.amount_minor > v_tecto)
                   AND v_primeira IS NULL THEN
                  v_decisao := 'exige_segunda';
                ELSE
                  v_decisao := 'confirma';
                END IF;
              END IF;
            END IF;
          END IF;

          v_fase := CASE
            WHEN v_decisao = 'rejeita' THEN 'rejeicao'
            WHEN v_decisao = 'confirma' AND v_primeira IS NOT NULL
              THEN 'segunda_aprovacao'
            ELSE 'confirmacao' END;

          INSERT INTO {CONFIRMACOES} (
              tenant_id, charge_id, fase, actor_contact_id, canal_msg_id,
              valor_declarado_minor, valor_bate, motivo)
            VALUES (
              v_charge.tenant_id, p_charge_id, v_fase, p_actor_contact_id,
              p_canal_msg_id, p_valor_declarado_minor, v_bate, v_motivo)
            RETURNING id INTO v_id;

          IF v_decisao = 'retem' THEN
            INSERT INTO {SINAIS} (
                tenant_id, contact_id, charge_id, regra, severidade, accao,
                detalhe)
              VALUES (
                v_charge.tenant_id, v_cliente, p_charge_id, v_regra,
                {SEVERIDADE_DO_M3}, 'reter_confirmacao',
                jsonb_build_object(
                  'confirmacao_id', v_id, 'motivo', v_motivo,
                  'soma_do_dia_minor', v_janela.soma_do_dia_minor,
                  'tecto_diario_minor', v_janela.tecto_diario_minor,
                  'confirmacoes_do_contacto', v_janela.confirmacoes_do_contacto,
                  'tecto_do_contacto', v_janela.tecto_do_contacto))
              RETURNING id INTO v_sinal;
          END IF;

          IF v_decisao = 'rejeita' THEN
            -- O `authn_ok` distingue **quem** falhou de **o que** falhou: um
            -- BSUID que nao esta na tabela nao e uma origem autenticada; um
            -- confirmador legitimo que escreve o valor errado e. Com os dois a
            -- `true`, o painel de ops nao conseguia separar uma tentativa de
            -- fraude de um engano de quem tem direito a confirmar.
            v_authn_ok := v_motivo NOT IN (
              'cliente_nao_confirma', 'sem_confirmador', 'sem_segunda_aprovacao');
            SELECT a.event_id, a.estado_novo INTO v_event, v_estado
              FROM platform.append_payment_event(
                p_charge_id => p_charge_id,
                p_tipo_evento => 'confirmacao_manual_rejeitada',
                p_account_id => v_charge.account_id,
                p_valor_minor => p_valor_declarado_minor,
                p_authn_method => 'manual',
                p_authn_ok => v_authn_ok,
                p_decisao => 'rejeitada',
                p_motivo => v_motivo,
                p_actor_kind => 'dono',
                p_actor_id => p_actor_contact_id,
                p_payload => jsonb_build_object(
                  'confirmacao_id', v_id, 'fase', v_fase,
                  'valor_bate', v_bate)) a;
          ELSE
            SELECT a.event_id, a.estado_novo INTO v_event, v_estado
              FROM platform.append_payment_event(
                p_charge_id => p_charge_id,
                p_tipo_evento => 'confirmacao_manual_registada',
                p_account_id => v_charge.account_id,
                p_valor_minor => p_valor_declarado_minor,
                p_authn_method => 'manual',
                p_authn_ok => true,
                p_decisao => 'informativo',
                p_motivo => coalesce(v_motivo, v_decisao),
                p_actor_kind => 'dono',
                p_actor_id => p_actor_contact_id,
                p_payload => jsonb_build_object(
                  'confirmacao_id', v_id, 'fase', v_fase,
                  'decisao', v_decisao)) a;
            IF v_decisao = 'confirma' THEN
              -- O `p_valor_minor` e o da **cobranca** e nao o declarado, e isso
              -- nao e uma folga: o G4 compara os dois e recusa a diferenca, e
              -- aqui ja se sabe que sao iguais (o M-4 passou). Passar o
              -- declarado era deixar o G4 a medir uma igualdade que esta funcao
              -- ja garantiu, e perder a barreira para quem chamasse a porta por
              -- fora — que e o que o G8 fecha do outro lado.
              SELECT a.event_id, a.estado_novo INTO v_event, v_estado
                FROM platform.append_payment_event(
                  p_charge_id => p_charge_id,
                  p_tipo_evento => 'pagamento_confirmado',
                  p_account_id => v_charge.account_id,
                  p_valor_minor => v_charge.amount_minor,
                  p_authn_method => 'manual',
                  p_authn_ok => true,
                  p_decisao => 'aceite',
                  p_motivo => NULL,
                  p_actor_kind => 'dono',
                  p_actor_id => p_actor_contact_id,
                  p_payload => jsonb_build_object(
                    'confirmacao_id', v_id, 'fase', v_fase)) a;
            END IF;
          END IF;

          RETURN QUERY SELECT
            v_id, v_event, v_estado, v_decisao, v_motivo, v_bate, v_sinal, false;
        END $func$
        """
    )
    op.execute(
        "COMMENT ON FUNCTION platform.manual_confirmar(uuid, uuid, text, bigint) IS "
        "'O acto humano do docs/tecnica/04 secao 4 (KAM-054): M-1 (quem, e nunca "
        "o cliente), M-4 (o desafio do valor, sem tolerancia), M-3 (as duas "
        "janelas, que retem) e M-5 (a dupla acima do limiar), nessa ordem e numa "
        "transaccao, e so sobre uma cobranca em pendente_confirmacao — que e o "
        "unico estado com aresta nos dois sentidos no secao 7.1. Nao recebe "
        "decisao por parametro: decide. SECURITY DEFINER "
        "porque e a unica porta de escrita de manual_confirmations — com "
        "INVOKER, o papel da aplicacao escrevia uma declaracao_cliente com o "
        "actor que quisesse, e escolhia quem o cliente e.'"
    )


def _expirar() -> None:
    """`manual_expirar_confirmacao`: a omissao do dono, F-18 (criterio 7).

    «Sem resposta do dono em 24 h (omissao, F-18) a cobranca volta a
    `pendente_confirmacao → emitida` com `confirmacao_manual_rejeitada` e **a
    reserva mantem-se ate `expira_at`**.»

    **O nome canonico e `expira_at` e nao `expires_at`**, que e como o criterio 7
    o escreve. O dicionario §3.3 fixa `expira_at` e o *gate* 3b recusa a
    variante — medido nesta revisao. A divergencia do bloco esta na divida
    documental.

    As duas metades sao independentes, e e a segunda que se mede com mais
    cuidado: expirar a **confirmacao** nao expira a **cobranca**. Esta funcao nao
    toca no `valid_until` nem escreve `cobranca_expirada`, e a reserva da
    encomenda — que vive no COM, com o seu `expira_at` — fica onde estava. A
    aresta do §7.1 di-lo: `pendente_confirmacao --> emitida`, e nao
    `--> expirada`. Uma implementacao que «limpasse» tudo de uma vez cancelava
    uma reserva valida por o dono nao ter respondido a tempo, que e punir o
    cliente por um silencio que nao e dele.

    **A janela vem por argumento**, e nao se le de configuracao nenhuma: e o que
    torna esta funcao mensuravel com relogio simulado, que e o que os «Testes
    Requeridos» pedem («TTL de 24 h com relogio simulado»). Quem a corre e o
    varrimento do KAM-071; o valor de 24 h e do §7.2 e vive no
    `JANELA_DE_SILENCIO_HORAS` do modulo de aplicacao.

    Devolve zero linhas quando nao ha nada a expirar — a cobranca nao esta em
    `pendente_confirmacao`, ou o pedido ainda esta dentro da janela. **Nao
    levanta**: um varrimento que corre de minuto a minuto sobre muitas cobrancas
    nao pode tratar «ainda nao» como erro.
    """
    op.execute(
        f"""
        CREATE FUNCTION platform.manual_expirar_confirmacao(
          p_charge_id uuid,
          p_janela_horas integer DEFAULT 24)
        RETURNS TABLE (
          confirmacao_id uuid, event_id bigint, estado_novo text)
        LANGUAGE plpgsql SECURITY DEFINER
        SET search_path = pg_catalog, platform AS $func$
        DECLARE
          v_charge  platform.payment_charges;
          v_pedido  timestamptz;
          v_cliente uuid;
          v_id      uuid;
          v_event   bigint;
          v_estado  text;
        BEGIN
          SELECT * INTO v_charge FROM {COBRANCAS}
            WHERE id = p_charge_id FOR UPDATE;
          IF NOT FOUND THEN
            RAISE EXCEPTION
              'manual_expirar_confirmacao: a cobranca % nao existe ou nao e '
              'visivel no contexto desta transaccao (RLS)', p_charge_id
              USING ERRCODE = 'check_violation';
          END IF;
          IF v_charge.estado <> 'pendente_confirmacao' THEN
            RETURN;
          END IF;

          SELECT m.criado_at, m.actor_contact_id INTO v_pedido, v_cliente
            FROM {CONFIRMACOES} m
            WHERE m.charge_id = p_charge_id AND m.fase = 'declaracao_cliente'
            ORDER BY m.criado_at DESC, m.id DESC LIMIT 1;
          IF v_pedido IS NULL
             OR now() < v_pedido + make_interval(hours => p_janela_horas) THEN
            RETURN;
          END IF;

          -- O `canal_msg_id` de uma omissao nao vem de mensagem nenhuma: nao
          -- houve mensagem. E sintetico e **deterministico** por cobranca e por
          -- declaracao, pelo que dois varrimentos sobre a mesma omissao batem na
          -- unicidade em vez de escreverem duas rejeicoes — a idempotencia do
          -- criterio 9 aplicada ao caminho que nao tem mensagem.
          INSERT INTO {CONFIRMACOES} (
              tenant_id, charge_id, fase, actor_contact_id, canal_msg_id,
              valor_bate, motivo)
            VALUES (
              v_charge.tenant_id, p_charge_id, 'rejeicao', v_cliente,
              'omissao:' || p_charge_id::text || ':'
                || extract(epoch FROM v_pedido)::bigint::text,
              false, 'silencio_do_dono')
            RETURNING id INTO v_id;

          SELECT a.event_id, a.estado_novo INTO v_event, v_estado
            FROM platform.append_payment_event(
              p_charge_id => p_charge_id,
              p_tipo_evento => 'confirmacao_manual_rejeitada',
              p_account_id => v_charge.account_id,
              p_valor_minor => v_charge.amount_minor,
              p_authn_method => 'manual',
              p_authn_ok => false,
              p_decisao => 'rejeitada',
              p_motivo => 'silencio_do_dono',
              p_actor_kind => 'sistema',
              p_actor_id => v_cliente,
              p_payload => jsonb_build_object(
                'confirmacao_id', v_id, 'fase', 'rejeicao',
                'janela_horas', p_janela_horas,
                'reserva_mantida_ate_expira_at', true)) a;

          RETURN QUERY SELECT v_id, v_event, v_estado;
        END $func$
        """
    )
    op.execute(
        "COMMENT ON FUNCTION platform.manual_expirar_confirmacao(uuid, integer) IS "
        "'A omissao do dono (F-18, KAM-054, criterio 7): a cobranca volta de "
        "pendente_confirmacao a emitida com confirmacao_manual_rejeitada, e a "
        "reserva mantem-se ate expira_at — esta funcao nao toca no valid_until e "
        "nao escreve cobranca_expirada. Devolve zero linhas quando nao ha nada a "
        "expirar, porque um varrimento nao pode tratar ainda-nao como erro.'"
    )


def _reverter() -> None:
    """`manual_reverter`: a reversao auditada do M-8 (criterio 8).

    «Reversao: `confirmacao_manual_revertida` + `refund_cases` aberto + cobranca
    `paga → reembolso_pendente`; **nenhuma linha e apagada** (a contagem do
    ledger so cresce).»

    A propriedade do criterio nao se cumpre por cuidado de quem escreve: hoje
    ela tem barreira na base. O `payment_events_imutavel` da `0029` recusa
    `UPDATE` e `DELETE` por linha, e o `payment_events_sem_truncate` recusa-os
    **tambem quando nao casam linha nenhuma**, pelo *trigger* por instrucao
    (KAM-175). Esta funcao, portanto, nao tem como desfazer nada — e nao e uma
    limitacao: e o desenho. O que ela faz e escrever o que aconteceu.

    O `actor_kind` e `ops` e nao `dono`: uma reversao e um acto de retaguarda
    («Abuso interno», §9: «confirmacoes de ops exigem motivo e dupla
    aprovacao»), e o `p_motivo` e **obrigatorio** por isso — nao ha reversao sem
    razao escrita.

    O caso de reembolso abre-se com o valor da **cobranca** e nao com um valor
    por argumento: reverter uma confirmacao e dizer que aquele pagamento nao se
    deu, e o montante disso e o da cobranca. Um valor a escolha de quem chama
    abria um caminho para um caso de reembolso de montante diferente do que foi
    confirmado, que e a «abuso de reembolso» da tabela do §9.
    """
    op.execute(
        f"""
        CREATE FUNCTION platform.manual_reverter(
          p_charge_id uuid,
          p_actor_contact_id uuid,
          p_canal_msg_id text,
          p_motivo text)
        RETURNS TABLE (
          confirmacao_id uuid, event_id bigint, estado_novo text,
          refund_case_id uuid)
        LANGUAGE plpgsql SECURITY DEFINER
        SET search_path = pg_catalog, platform AS $func$
        DECLARE
          v_charge platform.payment_charges;
          v_id     uuid;
          v_caso   uuid;
          v_event  bigint;
          v_estado text;
        BEGIN
          IF p_motivo IS NULL OR btrim(p_motivo) = '' THEN
            RAISE EXCEPTION
              'manual_reverter: uma reversao exige motivo escrito (M-8, '
              'docs/tecnica/04 secao 9: confirmacoes de ops exigem motivo)'
              USING ERRCODE = 'check_violation';
          END IF;

          SELECT * INTO v_charge FROM {COBRANCAS}
            WHERE id = p_charge_id FOR UPDATE;
          IF NOT FOUND THEN
            RAISE EXCEPTION
              'manual_reverter: a cobranca % nao existe ou nao e visivel no '
              'contexto desta transaccao (RLS)', p_charge_id
              USING ERRCODE = 'check_violation';
          END IF;

          SELECT m.id INTO v_id FROM {CONFIRMACOES} m
            WHERE m.charge_id = p_charge_id AND m.canal_msg_id = p_canal_msg_id;
          IF v_id IS NOT NULL THEN
            SELECT r.id INTO v_caso FROM {REEMBOLSOS} r
              WHERE r.charge_id = p_charge_id ORDER BY r.criado_at LIMIT 1;
            RETURN QUERY SELECT v_id, NULL::bigint, v_charge.estado, v_caso;
            RETURN;
          END IF;

          INSERT INTO {CONFIRMACOES} (
              tenant_id, charge_id, fase, actor_contact_id, canal_msg_id,
              valor_declarado_minor, valor_bate, motivo)
            VALUES (
              v_charge.tenant_id, p_charge_id, 'reversao', p_actor_contact_id,
              p_canal_msg_id, v_charge.amount_minor, false, p_motivo)
            RETURNING id INTO v_id;

          INSERT INTO {REEMBOLSOS} (
              tenant_id, order_id, charge_id, motivo, valor_minor, estado)
            VALUES (
              v_charge.tenant_id, v_charge.order_id, p_charge_id, p_motivo,
              v_charge.amount_minor, 'aberto')
            RETURNING id INTO v_caso;

          SELECT a.event_id, a.estado_novo INTO v_event, v_estado
            FROM platform.append_payment_event(
              p_charge_id => p_charge_id,
              p_tipo_evento => 'confirmacao_manual_revertida',
              p_account_id => v_charge.account_id,
              p_valor_minor => v_charge.amount_minor,
              p_authn_method => 'manual',
              p_authn_ok => true,
              p_decisao => 'rejeitada',
              p_motivo => p_motivo,
              p_actor_kind => 'ops',
              p_actor_id => p_actor_contact_id,
              p_payload => jsonb_build_object(
                'confirmacao_id', v_id, 'fase', 'reversao',
                'refund_case_id', v_caso)) a;

          RETURN QUERY SELECT v_id, v_event, v_estado, v_caso;
        END $func$
        """
    )
    op.execute(
        "COMMENT ON FUNCTION platform.manual_reverter(uuid, uuid, text, text) IS "
        "'A reversao auditada do M-8 (KAM-054, criterio 8): fase reversao, evento "
        "confirmacao_manual_revertida, refund_cases aberto e a cobranca de paga a "
        "reembolso_pendente, numa transaccao. Nenhuma linha e apagada — e nao por "
        "convencao: o payment_events recusa UPDATE e DELETE por trigger, incluindo "
        "ao superutilizador e incluindo quando nao casam linha nenhuma (KAM-175).'"
    )


# -------------------------------------------------------- RLS e privilegios


def _rls() -> None:
    """RLS `FORCE` nas quatro tabelas (ADR-015).

    As quatro tem `tenant_id`, pelo que o X-05 do *gate* 6 as descobre pelo
    catalogo e nao por lista — entram na verificacao sem ninguem as declarar, e
    e por isso que nao ha nada a acrescentar ao `ci/rls_exceptions.yaml`, que
    esta vazio e deve continuar vazio.

    O `FORCE` e o que faz as quatro funcoes `SECURITY DEFINER` desta revisao
    **nao** contornarem o isolamento: elas correm como o `kamba_migrator`, que e
    `NOBYPASSRLS`, e o `FORCE` vincula tambem o dono da tabela (`db/rls.py`). O
    `app.tenant_id` de quem chamou continua a ser o que a politica avalia — dao
    privilegio e nao dao isolamento, que e o mesmo desenho da
    `append_payment_event`.
    """
    rls.enable_tenant_rls("payment_confirmers")
    rls.enable_tenant_rls("manual_confirmations")
    rls.enable_tenant_rls("refund_cases")
    rls.enable_tenant_rls("fraud_signals")


def _privilegios() -> None:
    """A matriz: a aplicacao **le** as quatro e nao escreve nenhuma.

    E a mesma escolha da `payment_accounts` na `0027`, e pela mesma razao
    escrita: quem provisiona nao e um turno de conversa. Aqui vale duas vezes:

        payment_confirmers    com `INSERT`, um tenant acrescentava-se a si
                              proprio a lista de quem pode confirmar — isto e, a
                              guarda do M-1 era um `INSERT`. Quem a escreve e o
                              onboarding de retaguarda, pelo `kamba_batch`
        manual_confirmations  com `INSERT`, escrevia-se uma `declaracao_cliente`
                              com o `actor_contact_id` a escolha, e a funcao que
                              descobre quem e o cliente **lendo** essa fase
                              deixava de ter guarda nenhuma. Ver o cabecalho
        refund_cases          com `INSERT`, abria-se um caso de reembolso sem
                              reversao e sem evento no ledger
        fraud_signals         com `INSERT`, quem e vigiado escrevia no registo
                              de vigilancia

    O que a aplicacao precisa de escrever, escreve pelas quatro funcoes. O que o
    `kamba_batch` precisa e o ciclo de vida: a lista de confirmadores e o fecho
    de um caso de reembolso, que corre fora da plataforma e alguem tem de
    registar. **Nao** tem `UPDATE` em `manual_confirmations` nem em
    `fraud_signals`: os dois sao registos, e um registo que se corrige nao e um
    registo.
    """
    for tabela in (CONFIRMADORES, CONFIRMACOES, REEMBOLSOS, SINAIS):
        op.execute(f"REVOKE ALL ON {tabela} FROM PUBLIC")
        op.execute(f"GRANT SELECT ON {tabela} TO {PAPEL_DA_APP}")
        op.execute(f"GRANT SELECT ON {tabela} TO {PAPEL_DE_LOTE}")
        op.execute(f"GRANT SELECT ON {tabela} TO {PAPEL_DE_AUDITORIA}")

    op.execute(
        f"GRANT INSERT, DELETE ON {CONFIRMADORES} TO {PAPEL_DE_LOTE}"
    )
    op.execute(
        "GRANT UPDATE (papel, pode_segunda_aprovacao, ativo) ON "
        + CONFIRMADORES
        + " TO "
        + PAPEL_DE_LOTE
    )
    op.execute(
        "GRANT UPDATE (estado, prova_ref, fechado_at) ON "
        + REEMBOLSOS
        + " TO "
        + PAPEL_DE_LOTE
    )

    # As quatro funcoes de fase: `kamba_app` executa-as, e e so o que ele pode
    # fazer sobre estas tabelas. O `REVOKE ... FROM PUBLIC` primeiro, pela razao
    # da `0029`: uma funcao nasce com `EXECUTE` para `PUBLIC`, e sem este passo
    # a excepcao do `DEFINER` ficava aberta a qualquer papel.
    for assinatura in (
        "platform.manual_declarar(uuid, uuid, text, text)",
        "platform.manual_confirmar(uuid, uuid, text, bigint)",
        "platform.manual_expirar_confirmacao(uuid, integer)",
        "platform.manual_reverter(uuid, uuid, text, text)",
        "platform.manual_janela(uuid, uuid, timestamptz)",
    ):
        op.execute(f"REVOKE ALL ON FUNCTION {assinatura} FROM PUBLIC")
        op.execute(f"GRANT EXECUTE ON FUNCTION {assinatura} TO {PAPEL_DA_APP}")

    # O varrimento do F-18 e do KAM-071 e corre em lote, nao num turno de
    # conversa: e o `kamba_batch` que o executa. As outras tres **nao** lhe sao
    # concedidas — um lote nao confirma pagamentos.
    op.execute(
        "GRANT EXECUTE ON FUNCTION "
        "platform.manual_expirar_confirmacao(uuid, integer) TO "
        + PAPEL_DE_LOTE
    )
    op.execute(
        "GRANT EXECUTE ON FUNCTION platform.manual_janela(uuid, uuid, timestamptz) "
        "TO " + PAPEL_DE_LOTE
    )
