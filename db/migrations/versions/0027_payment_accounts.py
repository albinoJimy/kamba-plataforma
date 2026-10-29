"""A conta de pagamento e o beneficiario explicito (KAM-052).

A primeira linha e **sem acentos**, como as vinte e seis revisoes anteriores: e a
mensagem que o `alembic history` imprime, e o
`test_no_processo_e_pela_linha_de_comandos_o_alembic_diz_o_mesmo` compara a
saida no processo com a do executavel. Com acentos, as duas divergem na
codificacao.

## O que esta revisao cria, e o que **nao** cria

Cria a `platform.payment_accounts` do `docs/tecnica/04` §6.2, o indice
`payment_accounts_um_ativo` e a funcao `platform.assert_beneficiary`, que e a
guarda G-1 do §10.4.

**Nao** cria a `payment_charges` nem a `payment_events`. A ordem do §6 e
`orders_mirror -> payment_accounts -> payment_charges -> payment_events`, e esta
revisao entrega **a segunda**: a `payment_charges` e o KAM-055 (com as FK para
`orders_mirror`), o ledger e o KAM-053, e a FK de `billing_cycles` e o KAM-059. A
`payment_accounts` so referencia `tenants`, e e por isso que pode vir antes das
outras tres.

## `beneficiary_kind` e `pme`, e o §6.2 escreve `tenant`

E a unica divergencia desta revisao face ao DDL que o criterio 4 manda seguir, e
resolve-se pela ordem das fontes e nao por gosto:

* `specs/02_Dicionario_de_Dados_Canonico.md` §3.4 — fonte 4 — fixa
  `beneficiary_kind ∈ {pme, plataforma_receita_propria}`;
* `docs/tecnica/04` §6.2 — fonte 9 — escreve
  `('tenant','plataforma_receita_propria')`, e o §10.4 e o criterio 6 do bloco
  repetem o `tenant`.

O dicionario prevalece, e **nao e so pela ordem**: o dominio esta fechado em
`canon/dicionario.yaml` e o `canon_lint` do *gate* 3b recusa um `CHECK` com um
valor fora dele. Uma revisao copiada a letra do §6.2 fica **vermelha** — medido,
nao inferido. Divida documental 149.

## O `tenant_id` e anulavel, e isso e uma excepcao decidida

O §6.2 escreve `tenant_id uuid REFERENCES platform.tenants(id)` **sem**
`NOT NULL`, porque a conta de receita propria da KAMBA nao tem tenant: o §11.2
diz que `beneficiary_kind='plataforma_receita_propria'` existe precisamente para
«evitar criar um `tenant` de tipo `platform`», que esta bloqueado em producao
por D2.

Isso contraria a convencao do dicionario §2 — «toda a tabela de negocio tem
`tenant_id uuid NOT NULL` + RLS `FORCE`» —, cujas excepcoes se declaram. E
contraria, concretamente, uma **lista fechada**: o `ANULAVEIS` de
`db/tests/test_catalogo.py` tinha duas entradas, as duas da auditoria (KAM-012),
com um comentario a dizer que eram «as **unicas** com `tenant_id` anulavel em
todo o schema». Esta tabela e a terceira, e a primeira que **guarda dados de
tenant**.

A decisao e do fundador e foi tomada por escrito para este ticket: segue-se o
§6.2, a tabela entra no `ANULAVEIS` com a razao, e o teste **nao** se afrouxa.

O que a nulidade nao e: um buraco. A equivalencia
`(beneficiary_kind = 'pme') = (tenant_id IS NOT NULL)` esta no `CHECK`, pelo que
uma conta de PME **nunca** tem `tenant_id` nulo — a nulidade e condicional e a
condicao e verificada pela base.

## A consequencia da nulidade sob RLS, dita por extenso

Com `FORCE` e a politica `tenant_iso`, o predicado
`tenant_id = NULLIF(current_setting('app.tenant_id', true), '')::uuid` **nao e
verdadeiro para uma linha com `tenant_id` nulo** — `coluna = NULL` nao e
verdadeiro para linha nenhuma. Logo a conta de receita propria da KAMBA e
**invisivel a todos os papeis sujeitos a RLS**, incluindo o `kamba_app`, e e
lida so pelo `kamba_batch`, que tem `BYPASSRLS`.

E o mesmo efeito que a `0006` documentou para a `audit_heads`, e ali resolveu-se
com uma dispensa de RLS em `ci/rls_exceptions.yaml` — **que aqui nao se faz**,
porque esta tabela guarda dados de tenant e a dispensa valia para uma tabela que
nao guarda nenhum.

O §6.2 diz «acessivel so ao papel de billing». **Esse papel nao existe**: os sete
de `db/ligacao.py` nao incluem nenhum de billing, e quem o vai precisar e o
KAM-059 (billing da plataforma via `PaymentProvider`), que este ticket bloqueia.
Criar um papel aqui era alargar o escopo para uma tabela que ainda nao tem quem a
leia. Fica, portanto, **fail closed**: a conta propria existe, e por agora so o
papel de lote a alcanca. Nao e uma lacuna escondida — e a leitura escrita, com o
credor nomeado.

## `credenciais_ref` tem a forma do cofre no `CHECK`, e nao so no codigo

O criterio 7 pede que a coluna «so aceite caminho do cofre». A expressao do
`CHECK` e **a mesma** do `SecretRef` do KAM-010
(`packages/core-ts/src/secrets/port.ts`), e nao uma segunda escrita a mao: o
`token_ref` do §3.15 e o mesmo tipo de coluna, e duas expressoes para a mesma
forma divergem.

O que ela impede, em concreto: um segredo copiado de um painel traz maiusculas,
espacos, `=` de enchimento ou `-----BEGIN`, e o tecto de 200 caracteres e, por
escrito no `port.ts`, «o que impede que alguem passe um **valor** de segredo onde
devia passar uma referencia».

## O `assert_beneficiary` e criado aqui e ligado pelo KAM-055

A funcao e completa e final: le `NEW.tenant_id`, `NEW.account_id`, `NEW.order_id`
e `NEW.billing_cycle_id`, que sao as colunas que a `payment_charges` do §6.2 tem.
O `CREATE TRIGGER` sobre ela **nao esta aqui**, porque a tabela nao esta — e do
KAM-055.

Isso nao deixa o criterio 5 por medir: o
`db/tests/test_pagamentos_schema.py` cria uma tabela de ensaio com a forma da
`payment_charges`, liga-lhe este *trigger* e mede os tres casos contra um
PostgreSQL real. O que corre e a funcao que vai para producao, com contas reais e
recusas reais do servidor; o que falta e a tabela a que ela se vai ligar. E o
mesmo recurso que o `test_x05_catalogo.py` usa para provar que a descoberta de
tabelas morde.
"""

from alembic import op

import rls

revision = "0027"
down_revision = "0026"
branch_labels = None
depends_on = None

#: Literais e nao f-strings sobre outras constantes, pela razao da `0025`: o
#: *gate* 3b le o AST da revisao sem a executar e resolve `f"..."` sobre
#: constantes de modulo, mas nao sobre constantes que sejam elas proprias
#: f-strings.
CONTAS = "platform.payment_accounts"

#: `beneficiary_kind ∈ {pme, plataforma_receita_propria}` (dicionario §3.4).
#: **`pme` e nao `tenant`** — ver o cabecalho. Ja entre apostrofos, pela razao da
#: `0015`: e a unica forma que o *gate* 3b resolve, porque segue
#: `", ".join(<constante de modulo>)` dentro de uma f-string.
BENEFICIARIOS = ("'pme'", "'plataforma_receita_propria'")

#: Os nove estados do §6.2, pela ordem do diagrama do §10.2. O espelho em
#: TypeScript e o `ESTADOS_DA_CONTA` de
#: `packages/core-ts/src/pagamentos/estados.ts`, e as duas listas movem-se
#: juntas: o `test_os_nove_estados_sao_os_do_modulo` percorre uma e insere na
#: outra, pelo que um estado la que nao esteja aqui e um `INSERT` recusado.
ESTADOS = (
    "'nao_iniciado'",
    "'docs_recolhidos'",
    "'banco_em_curso'",
    "'facilitador_em_curso'",
    "'credenciais_recebidas'",
    "'teste_sandbox_ok'",
    "'ativo'",
    "'suspenso'",
    "'revogado'",
)

#: Os dois estados que **ocupam** o par `(tenant_id, provider)` no indice unico
#: parcial. Nao e o mesmo conjunto que «pode cobrar», que e so o `ativo`: uma
#: conta em sandbox ja reserva o par, para que ninguem comece uma segunda
#: integracao do mesmo facilitador enquanto a primeira esta a ser testada.
ESTADOS_QUE_OCUPAM = ("'ativo'", "'teste_sandbox_ok'")

#: O dominio de `liquidacao_destino` do §6.2.
DESTINOS = ("'conta_banco'", "'carteira_unitel_money'", "'conta_pme_fora_plataforma'")

#: A forma de uma referencia do cofre. **E a mesma expressao** do `REF` de
#: `packages/core-ts/src/secrets/port.ts` (KAM-010), e o
#: `test_a_forma_do_credenciais_ref_e_a_do_secretref` compara-as como texto.
FORMA_DO_COFRE = "^[a-z][a-z0-9_]{2,63}(/[A-Za-z0-9._:-]{1,128})?$"

PAPEL_DA_APP = "kamba_app"
PAPEL_DE_LOTE = "kamba_batch"
PAPEL_DE_AUDITORIA = "kamba_audit"


def upgrade() -> None:
    _contas()
    _beneficiario()
    _rls()
    _privilegios()


def _contas() -> None:
    """A tabela do §6.2, com a equivalencia do beneficiario no `CHECK`."""
    op.execute(
        f"""
        CREATE TABLE {CONTAS} (
            id                 uuid        NOT NULL DEFAULT gen_random_uuid(),
            -- `pme` ou `plataforma_receita_propria` (dicionario §3.4). O segundo
            -- existe para a KAMBA cobrar a propria assinatura (§11.2) sem
            -- activar o tenant `platform`, que esta vedado por D2.
            beneficiary_kind   text        NOT NULL,
            -- **Anulavel, e a nulidade e condicional**: nula se e so se o
            -- beneficiario e a plataforma. Ver o cabecalho para a decisao e para
            -- o efeito que isto tem sob RLS.
            tenant_id          uuid,
            provider           text        NOT NULL,
            -- Identificadores EMIS da PME (ou da KAMBA). O prazo e os requisitos
            -- bancarios para os obter sao **NAO VERIFICADO** (D4, KAM-103) e nao
            -- bloqueiam este ticket. A G-4 confere que nenhum deles, numa conta
            -- de `pme`, e da KAMBA (`config/kamba_emis.yaml`).
            entidade           text,
            pos_id             text,
            iec                text,
            -- Caminho no cofre, **nunca o segredo** (criterio 7). A forma e a do
            -- `SecretRef` do KAM-010 — ver `FORMA_DO_COFRE`.
            credenciais_ref    text,
            -- Gerado na aplicacao, opaco, 32 octetos aleatorios em `base64url`
            -- (`gerarWebhookToken`). E o segmento de URL do callback: nao leva o
            -- `tenant_id`, o `id` nem o `provider`, porque um URL de webhook
            -- aparece em paineis de terceiros e em registos de proxy.
            webhook_token      text        NOT NULL,
            liquidacao_destino text,
            -- Dados de pagamento da PME para o `ManualProvider` (§4). Texto que
            -- o dono escreve e que o cliente ve; o KAM-054 e quem o usa.
            manual_instrucoes  text,
            estado             text        NOT NULL DEFAULT 'nao_iniciado',
            checklist          jsonb       NOT NULL DEFAULT '{{}}',
            criado_at          timestamptz NOT NULL DEFAULT now(),
            CONSTRAINT payment_accounts_pkey PRIMARY KEY (id),
            CONSTRAINT payment_accounts_tenant_fk
                FOREIGN KEY (tenant_id) REFERENCES platform.tenants (id),
            CONSTRAINT payment_accounts_webhook_token_uq UNIQUE (webhook_token),
            CONSTRAINT payment_accounts_beneficiary_kind_ck
                CHECK (beneficiary_kind IN ({", ".join(BENEFICIARIOS)})),
            CONSTRAINT payment_accounts_estado_ck
                CHECK (estado IN ({", ".join(ESTADOS)})),
            CONSTRAINT payment_accounts_liquidacao_destino_ck
                CHECK (liquidacao_destino IS NULL
                       OR liquidacao_destino IN ({", ".join(DESTINOS)})),
            -- **A equivalencia nos dois sentidos, e nao so num.** E ela que faz
            -- de «e de uma PME» e «tem tenant» o mesmo facto: uma conta de `pme`
            -- sem tenant nao tem beneficiario, e uma de
            -- `plataforma_receita_propria` com tenant diz que a receita da KAMBA
            -- e de uma loja. E a linha do §6.2, e e o que torna o `tenant_id`
            -- anulavel seguro em vez de frouxo.
            CONSTRAINT payment_accounts_beneficiario_ck CHECK (
                (beneficiary_kind = 'pme') = (tenant_id IS NOT NULL)
            ),
            -- O criterio 7 na base, e nao so no codigo.
            CONSTRAINT payment_accounts_credenciais_ref_ck
                CHECK (credenciais_ref IS NULL
                       OR credenciais_ref ~ '{FORMA_DO_COFRE}'),
            CONSTRAINT payment_accounts_webhook_token_ck
                CHECK (btrim(webhook_token) <> ''),
            CONSTRAINT payment_accounts_provider_ck CHECK (btrim(provider) <> '')
        )
        """
    )
    op.execute(
        f"COMMENT ON TABLE {CONTAS} IS "
        "'Contas de pagamento com beneficiario explicito (KAM-052). O "
        "beneficiary_kind torna o ADR-004 verificavel: uma venda liquida na "
        "conta da PME, e a assinatura da KAMBA numa conta de "
        "plataforma_receita_propria. docs/tecnica/04 secao 6.2; dicionario 3.4.'"
    )
    op.execute(
        f"COMMENT ON COLUMN {CONTAS}.credenciais_ref IS "
        "'Caminho no cofre (SecretRef do KAM-010), NUNCA o segredo. O CHECK "
        "impoe a forma; o varrimento do criterio 7 confere que nenhuma coluna "
        "guarda um valor com forma de segredo.'"
    )
    op.execute(
        f"COMMENT ON COLUMN {CONTAS}.tenant_id IS "
        "'Nulo se e so se beneficiary_kind = plataforma_receita_propria "
        "(payment_accounts_beneficiario_ck). Excepcao declarada a convencao do "
        "dicionario secao 2, no ANULAVEIS de db/tests/test_catalogo.py. Sob RLS "
        "FORCE a linha de tenant nulo e visivel so a kamba_batch (BYPASSRLS).'"
    )
    # **O indice do criterio 4.** Parcial pelos dois estados que ocupam: depois
    # de uma conta ser revogada, o par `(tenant_id, provider)` fica livre — e
    # tem de ficar, senao uma PME que trocou de facilitador e quer voltar nao
    # podia.
    #
    # Nota sobre o `tenant_id` nulo: no PostgreSQL um indice unico **nao**
    # considera duas linhas com `NULL` iguais, pelo que isto nao limita a KAMBA
    # a uma conta activa por `provider`. E o comportamento certo — a KAMBA pode
    # ter mais do que uma conta propria — e fica dito para nao parecer descuido.
    op.execute(
        f"CREATE UNIQUE INDEX payment_accounts_um_ativo ON {CONTAS} "
        f"(tenant_id, provider) WHERE estado IN ({', '.join(ESTADOS_QUE_OCUPAM)})"
    )
    # A consulta que isto serve: «as contas deste tenant», que e o que o
    # onboarding e o PAY leem. O `tenant_id` vem primeiro porque e o filtro de
    # toda a leitura (e o `test_tenant_id_e_not_null_e_vem_primeiro_num_indice`
    # exige-o).
    op.execute(f"CREATE INDEX payment_accounts_tenant_idx ON {CONTAS} (tenant_id, estado)")
    # O callback entra por `webhook_token`: e a unica leitura que **nao** tem
    # `tenant_id`, porque quem chega nao o sabe. Servida pelo indice unico.


def _beneficiario() -> None:
    """`platform.assert_beneficiary`: a guarda G-1 do §10.4.

    As tres frases do §10.4 sao tres asserções diferentes:

    1. «para cobrancas de encomenda, `payment_accounts.tenant_id =
       payment_charges.tenant_id` e `beneficiary_kind='pme'`»;
    2. «cobrancas de billing so com `plataforma_receita_propria`»;
    3. «Uma conta nunca e partilhada entre tenants.»

    A terceira nao e uma quarta verificacao: e a primeira vista de fora. Com um
    `tenant_id` por linha, «partilhada» quer dizer dois tenants a cobrar contra o
    mesmo `account_id`, e cada uma dessas cobrancas e, uma a uma, o caso 1.

    `SECURITY DEFINER` e **nao** `INVOKER`, e a razao e a RLS: a funcao tem de
    poder ler a `payment_accounts` para comparar o `tenant_id`, e uma cobranca de
    billing aponta para uma conta de `tenant_id` **nulo**, que a politica
    `tenant_iso` esconde de quem chama. Com `INVOKER`, o `SELECT` devolvia zero
    linhas e a guarda recusava **toda** a cobranca de billing — isto e, a guarda
    que existe para permitir o billing da plataforma impedia-o.

    O `search_path` fica fixo na funcao, que e a defesa obrigatoria de um
    `SECURITY DEFINER`: sem ele, quem chama escolhe o que `payment_accounts`
    significa.
    """
    op.execute(
        """
        CREATE FUNCTION platform.assert_beneficiary() RETURNS trigger
        LANGUAGE plpgsql SECURITY DEFINER SET search_path = platform, pg_catalog
        AS $func$
        DECLARE
          v_kind   text;
          v_tenant uuid;
        BEGIN
          SELECT beneficiary_kind, tenant_id INTO v_kind, v_tenant
            FROM platform.payment_accounts WHERE id = NEW.account_id;
          IF NOT FOUND THEN
            RAISE EXCEPTION
              'assert_beneficiary: conta de pagamento inexistente: %',
              NEW.account_id
              USING ERRCODE = 'foreign_key_violation';
          END IF;

          -- Uma cobranca e de encomenda ou de billing, e exactamente uma
          -- (`docs/tecnica/04` §6.1). O `CHECK` que o impoe e da
          -- `payment_charges` e e do KAM-055; aqui le-se o que houver, e um
          -- registo com os dois ou com nenhum e recusado em vez de adivinhado.
          IF (NEW.order_id IS NOT NULL) = (NEW.billing_cycle_id IS NOT NULL) THEN
            RAISE EXCEPTION
              'assert_beneficiary: uma cobranca tem order_id ou '
              'billing_cycle_id, exactamente um (order_id=%, billing_cycle_id=%)',
              NEW.order_id, NEW.billing_cycle_id
              USING ERRCODE = 'check_violation';
          END IF;

          IF NEW.order_id IS NOT NULL THEN
            -- Encomenda: o beneficiario e a PME que vendeu.
            IF v_kind <> 'pme' THEN
              RAISE EXCEPTION
                'assert_beneficiary: a conta % e % e nao pode receber uma '
                'cobranca de encomenda; isso poria a plataforma a receber o '
                'dinheiro de uma venda da PME (ADR-004, G-1)',
                NEW.account_id, v_kind
                USING ERRCODE = 'check_violation';
            END IF;
            IF v_tenant <> NEW.tenant_id THEN
              RAISE EXCEPTION
                'assert_beneficiary: a conta % e do tenant % e a cobranca e do '
                'tenant %; uma conta nunca e partilhada entre tenants (G-1)',
                NEW.account_id, v_tenant, NEW.tenant_id
                USING ERRCODE = 'check_violation';
            END IF;
          ELSE
            -- Billing: a receita e da KAMBA (§11.2).
            IF v_kind <> 'plataforma_receita_propria' THEN
              RAISE EXCEPTION
                'assert_beneficiary: a conta % e % e nao pode receber uma '
                'cobranca de billing; a assinatura cobra-se numa conta de '
                'plataforma_receita_propria (secao 11.2)',
                NEW.account_id, v_kind
                USING ERRCODE = 'check_violation';
            END IF;
          END IF;
          RETURN NEW;
        END $func$
        """
    )
    op.execute(
        "COMMENT ON FUNCTION platform.assert_beneficiary() IS "
        "'Guarda G-1 do docs/tecnica/04 secao 10.4 (KAM-052): o beneficiario de "
        "uma cobranca de encomenda e a PME que vendeu, e o de uma de billing e a "
        "KAMBA. O CREATE TRIGGER sobre payment_charges e do KAM-055. SECURITY "
        "DEFINER porque tem de ler uma conta de tenant_id nulo, que a RLS "
        "esconde de quem chama.'"
    )
    # `PUBLIC` nao executa nada: a omissao do PostgreSQL concede `EXECUTE` a
    # `PUBLIC` em cada funcao nova, e numa `SECURITY DEFINER` isso e uma porta
    # para ler a tabela com os privilegios do dono. E a licao que a `0004`, a
    # `0023` e a `0025` escreveram — e aqui e mais grave do que la, porque esta
    # corre como o dono.
    op.execute("REVOKE ALL ON FUNCTION platform.assert_beneficiary() FROM PUBLIC")


def _rls() -> None:
    """Politica `tenant_iso` com `ENABLE` **e** `FORCE` (ADR-015, criterio do DoD).

    `FORCE` vincula tambem o dono: sem ele, o `kamba_migrator` via tudo. O X-05
    do *gate* 6 descobre as tabelas pelo catalogo e nao por lista, pelo que esta
    entra na verificacao sem ninguem a declarar.

    **Uma politica so, e nao duas.** O §6.2 diz que a conta da KAMBA e
    «acessivel so ao papel de billing», e a tentacao era acrescentar uma segunda
    politica para esse papel — como a `resolver_leitura` da `tenant_channels`.
    Nao se faz, por duas razoes: o papel de billing nao existe (ver o cabecalho),
    e «politicas permissivas somam-se por OU», pelo que uma a mais abre o que a
    `tenant_iso` fecha. Uma politica para um papel que ainda nao tem leitor seria
    uma porta aberta sem ninguem a usar.
    """
    rls.enable_tenant_rls("payment_accounts")


def _privilegios() -> None:
    """`kamba_app` le; `kamba_batch` escreve; `kamba_audit` le.

    **O `kamba_app` nao escreve, e isto distingue esta tabela da `bookings`.**
    Quem cria e altera uma conta de pagamento e o onboarding de retaguarda
    (KAM-091) e o fluxo de activacao do §10.2, nao um turno de conversa. Com
    `INSERT` concedido e `WITH CHECK (tenant_id = app.tenant_id)`, um tenant
    criava as proprias contas — isto e, declarava para onde vai o dinheiro das
    suas vendas sem ninguem verificar os documentos que o §10.2 recolhe. E a
    mesma escolha que a `0007` fez ao tirar `INSERT` em `entitlements` a este
    papel, e que a `0025` fez para o catalogo da agenda.

    **E nao apaga nada.** Encerrar uma conta e `estado = 'revogado'` (§10.2), e um
    `DELETE` concedido tornava o historico de beneficiarios reescrivel — o que e
    exactamente o que a G-1 existe para poder auditar.

    **O `kamba_audit` le.** Entra porque «para onde foi o dinheiro desta venda» e
    uma pergunta de auditoria, e a resposta vive nesta tabela. Mas o `GRANT` nao
    o põe acima da RLS: o `kamba_audit` **nao** tem `BYPASSRLS` (so o
    `kamba_batch` tem, `db/bootstrap.py`), pelo que ve as contas do tenant cujo
    contexto tiver e **nao** ve a de `tenant_id` nulo. Quem a alcanca hoje e so o
    papel de lote — ver o cabecalho.

    **O `kamba_resolver`, o `kamba_identity` e o `kamba_agr` nao ganham nada.** O
    resolvedor resolve canais, a identidade guarda o cofre de contactos e o
    `kamba_agr` guarda o estado das conversas — nenhum deles tem razao para
    chegar as contas de pagamento de ninguem.
    """
    op.execute(f"GRANT SELECT ON {CONTAS} TO {PAPEL_DA_APP}")
    op.execute(f"GRANT SELECT ON {CONTAS} TO {PAPEL_DE_AUDITORIA}")
    op.execute(f"GRANT SELECT, INSERT, UPDATE ON {CONTAS} TO {PAPEL_DE_LOTE}")


def downgrade() -> None:
    # Sem `CASCADE`, como todas as revisoes desde a `0001`: se houver um objecto
    # pendurado que esta revisao nao criou — o *trigger* que o KAM-055 vai ligar,
    # por exemplo —, o `downgrade` **falha** em vez de o apagar em silencio.
    #
    # **E sem guarda de dados.** O que se perde sao contas de pagamento, que e
    # configuracao e nao prova: os factos de dinheiro vivem no ledger
    # (`payment_events`, KAM-053), que nao esta nesta revisao. Quem desce esta
    # revisao com contas activas perde-as, e o `downgrade` existe para o ciclo do
    # *gate* 8 e para reverter um *deploy*, nao para operacao corrente.
    #
    # A funcao cai **antes** da tabela: ela le a `payment_accounts`, e deixa-la
    # para depois era deixar uma `SECURITY DEFINER` a apontar para uma tabela que
    # nao existe.
    op.execute("DROP FUNCTION platform.assert_beneficiary()")
    rls.disable_tenant_rls("payment_accounts")
    # Os dois indices caem com a tabela.
    op.execute(f"DROP TABLE {CONTAS}")
