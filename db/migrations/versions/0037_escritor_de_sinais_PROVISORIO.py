"""Escritor de sinais de anomalia: `platform.registar_sinal_de_anomalia` (KAM-060).

**O NUMERO DESTA REVISAO E PROVISORIO E O FICHEIRO NAO VAI EMPURRADO ASSIM.**
Ha duas `0037` abertas ao mesmo tempo (o PR #159 do KAM-051 e o #158 do
KAM-070), e quem funde em segundo renumera. O `0037` daqui existe por uma razao
mecanica e nao por reserva: o `down_revision` tem de nomear uma revisao que
exista **nesta** arvore, cuja cabeca e a `0036`, senao o *alembic* nao corre e o
*gate* 8 nao se consegue medir de todo. O numero final vem do fundador antes de
se empurrar, e renumerar isto sao tres linhas.

---

A tabela `platform.fraud_signals` existe desde a `0032` (KAM-054) e **nao se
toca**: nao ha tabela nova e nao ha coluna nova. O que esta revisao acrescenta e
a **porta de escrita** que faltava, mais um indice que a torna barata.

## Porque e que isto NAO contraria a decisao do KAM-054

A `0032` deu `SELECT` aos tres papeis e a mais ninguem, com a razao escrita por
extenso: «`fraud_signals` com `INSERT`, quem e vigiado escrevia no registo de
vigilancia». **Quem ela protegeu de escrever foi o vigiado** — o `kamba_app`,
que serve turnos de conversa e corre com o contacto do outro lado da linha a
decidir o que acontece a seguir.

O motor de anomalias corre **em lote**, nao num turno. O `GRANT EXECUTE` desta
funcao vai ao `kamba_batch` e **nao** ao `kamba_app`, e e isso que preserva a
decisao em vez de a desfazer: nenhum caminho de conversa ganha forma de escrever
no registo que o vigia. Se o grantee fosse o `kamba_app`, esta revisao estava a
desfazer o KAM-054 e nao a completa-lo.

**E isto nao e prosa: quebra.** O
`../tests_pagamentos/test_anomalias.py::TestPrivilegio::test_o_lote_escreve_e_a_aplicacao_nao`
afirma as duas metades — o lote escreve, a aplicacao leva `42501`. Acrescentar
`GRANT EXECUTE … TO kamba_app` faz a segunda metade falhar. Uma propriedade que
nao quebra com a mudanca que ela proibe nao e uma propriedade.

## A excepcao e estreita e nao cega

Tres barreiras dentro da funcao, e cada uma fecha um caminho que um
`GRANT INSERT` deixava aberto:

    regra     lista fechada das oito regras de anomalia. A coluna `regra` da
              `0032` e `text NOT NULL` **sem `CHECK`** — medido, e o
              `test_a_coluna_nao_tem_check_e_e_por_isso_que_a_funcao_tem`
              demonstra-o com um `INSERT` do superutilizador que **passa** —,
              pelo que esta funcao e o unico sitio onde o dominio dela se
              consegue fechar. E as duas regras do M-3 sao **recusadas aqui**:
              quem as escreve e a `manual_confirmar`, que as decide dentro da
              transaccao da confirmacao, e deixar um lote forjar uma retencao
              que o M-3 nao decidiu era abrir pela porta de servico a decisao
              que o KAM-054 fechou pela da frente.
    detalhe   sem chave de PII, **a qualquer profundidade**. O criterio 8 do
              bloco exige que o `detalhe` passe o *lint* de PII, e uma guarda
              **so** em TypeScript era uma convencao: o `semPii` do motor e o
              oraculo, e esta e a recusa que vale. E a mesma divisao de trabalho
              que o `avaliarConfirmacao` tem com a `manual_confirmar`.
    janela    um sinal igual dentro da janela nao escreve linha nova: devolve o
              `id` do que existe. Sem isto, o *job* periodico escrevia a mesma
              anomalia uma vez por corrida, e um registo de vigilancia com mil
              copias do mesmo facto e um registo que ninguem le.

## O que esta revisao NAO faz, e e deliberado

**Nao da `INSERT` a ninguem.** O `../tests/test_privilegios.py` afirma que a
`fraud_signals` nao tem `INSERT` para papel nenhum, e essa afirmacao continua
verdadeira depois desta revisao — `EXECUTE` numa funcao `DEFINER` nao e `INSERT`
na tabela, e a diferenca e exactamente a lista de barreiras acima. Ha ensaio que
o mede nos **dois** papeis.

**Nao escreve `refund_cases`.** O criterio 4 do KAM-060 pede um caso de
reembolso para um pagamento duplicado, e o `refund_cases` tem o mesmo regime
(escreve-o so a `manual_reverter`). Abri-lo e uma decisao sobre o fluxo de
reembolso — quem o fecha, com que prova — e nao sobre deteccao: um caso aberto
por um lote, sem reversao no ledger, e um caso que ninguem sabe fechar. Fica
devolvido com a razao, e o sinal da R-04 di-lo no `detalhe`
(`refund_case: "por_abrir"`) em vez de deixar supor que o caso existe.

**Nao acrescenta coluna de estado**, e e uma lacuna real que fica escrita: a
`fraud_signals` nao tem coluna de estado, pelo que «sinal aberto» **nao e
expressavel** — ops nao tem onde registar que fechou um. O `accaoEmVigor` e o
`decidirConfirmacao` do motor recebem os sinais da **janela** e nao os
«abertos», e as *docstrings* deles dizem-no. Acrescentar a coluna e uma decisao
sobre o ciclo de vida de um sinal, nao sobre a escrita dele.

## O indice, e porque e que ele e desta revisao e nao de outra

A guarda da janela faz uma leitura por sinal proposto. O
`fraud_signals_tenant_idx` da `0032` e `(tenant_id, criado_at)`, que serve o
painel e nao esta leitura: com um tenant com muitos sinais, a guarda varre todos
os do periodo para comparar a `regra`. O indice novo poe a `regra` a frente. Nao
e optimizacao prematura — e a diferenca entre a guarda ser barata e o *job*
periodico pagar um varrimento por regra e por corrida.
"""

from __future__ import annotations

from alembic import op

# PROVISORIO — ver o cabecalho. O numero final vem do fundador.
revision = "0037"
down_revision = "0036"
branch_labels = None
depends_on = None

SINAIS = "platform.fraud_signals"

PAPEL_DE_LOTE = "kamba_batch"

#: As oito regras de anomalia do KAM-060, e **so** elas.
#:
#: Repetidas aqui e nao derivadas, de proposito: esta funcao corre antes de
#: qualquer TypeScript existir, pelo que nao pode importar o `REGRAS` do motor, e
#: gerar o SQL do TypeScript acoplava uma revisao de base de dados a um *build*
#: de Node. E a mesma escolha que o `tools/obs_lint` faz com a gramatica das
#: etiquetas, que vive repetida em tres bibliotecas de metricas.
#:
#: **O que faz a repeticao valer alguma coisa e a terceira fonte**, e ela esta no
#: `../tests_pagamentos/test_anomalias.py`: o confronto nao e com uma copia
#: escrita a mao no ensaio nem com este literal, e sim entre o **texto do modulo
#: TypeScript** e o `pg_get_functiondef` da funcao **instalada**. Superficies que
#: concordam nao apanham erro comum; quem editasse duas copias no mesmo PR tinha
#: o ensaio verde.
#:
#: **As duas regras do M-3 nao estao aqui**, e e a barreira e nao uma omissao:
#: `manual_limite_diario` e `manual_limite_por_contacto_24h` sao escritas pela
#: `manual_confirmar`.
REGRAS_DE_ANOMALIA = (
    "'pagamento_divergente_repetido'",
    "'hmac_invalido_em_massa'",
    "'pagamento_orfao'",
    "'pagamento_duplicado'",
    "'auto_compra'",
    "'desvio_de_confirmacoes_manuais'",
    "'cod_sem_pagamento_repetido'",
    "'extracto_divergente'",
)

#: As chaves que um `detalhe` nao pode ter, em minusculas. O mesmo conjunto do
#: `CHAVES_PROIBIDAS_NO_DETALHE` do motor, pela razao do `REGRAS_DE_ANOMALIA`.
#:
#: O `contact_id` **nao** esta aqui: o criterio 8 escreve, a letra, que o sinal
#: leva «so `contact_id`, `charge_id`, regra e severidade». Um `contact_id` e um
#: identificador interno sem o numero atras dele, que e o desenho do ADR-010.
CHAVES_DE_PII = (
    "'telefone'",
    "'phone'",
    "'msisdn'",
    "'numero'",
    "'wa_id'",
    "'texto'",
    "'mensagem'",
    "'message'",
    "'body'",
    "'corpo'",
    "'nome'",
    "'name'",
    "'email'",
    "'bsuid'",
)

#: A assinatura, para o `COMMENT`, o `GRANT` e o `DROP`. Escrita **uma vez**: a
#: licao do `payment_events_sem_truncate` do KAM-175 e que um nome repetido em
#: tres instrucoes desvia-se numa delas sem ninguem ver.
ASSINATURA = (
    "platform.registar_sinal_de_anomalia(uuid, text, smallint, text, uuid, "
    "uuid, jsonb, interval)"
)

INDICE = "fraud_signals_regra_idx"


def upgrade() -> None:
    _porta()
    _indice()
    _privilegios()


def downgrade() -> None:
    # Pela ordem inversa, e o indice primeiro: um `DROP FUNCTION` nao depende
    # dele, mas deixar o indice de pe depois de a funcao sair punha na base um
    # indice cujo unico leitor nao existe.
    op.execute(f"DROP INDEX IF EXISTS platform.{INDICE}")
    op.execute(f"DROP FUNCTION IF EXISTS {ASSINATURA}")


def _porta() -> None:
    """A porta de escrita, com as tres barreiras do cabecalho.

    O `SET search_path = pg_catalog, platform` e **sem `public`**, pela razao da
    `0029`: um `search_path` que inclua um schema onde o chamador possa criar
    objectos deixa-o sombrear uma funcao que este corpo chama — e num
    `SECURITY DEFINER` isso corre como o dono.
    """
    regras = ", ".join(REGRAS_DE_ANOMALIA)
    pii = ", ".join(CHAVES_DE_PII)
    op.execute(
        f"""
        CREATE FUNCTION platform.registar_sinal_de_anomalia(
            p_tenant_id   uuid,
            p_regra       text,
            p_severidade  smallint,
            p_accao       text,
            p_contact_id  uuid DEFAULT NULL,
            p_charge_id   uuid DEFAULT NULL,
            p_detalhe     jsonb DEFAULT '{{}}'::jsonb,
            p_janela      interval DEFAULT interval '1 hour')
          RETURNS bigint
          LANGUAGE plpgsql
          SECURITY DEFINER
          SET search_path = pg_catalog, platform
        AS $$
        DECLARE
          v_id     bigint;
          v_existe bigint;
          v_chave  text;
          v_proibida text;
        BEGIN
          IF p_tenant_id IS NULL THEN
            RAISE EXCEPTION 'um sinal sem tenant nao se escreve'
              USING ERRCODE = '22023';
          END IF;

          -- (1) A regra, contra a lista fechada. **E aqui e nao na tabela**: a
          -- coluna `regra` e `text NOT NULL` sem `CHECK`, pelo que esta e a
          -- unica barreira que a fecha.
          IF p_regra IS NULL OR p_regra NOT IN ({regras}) THEN
            RAISE EXCEPTION
              'regra % nao e uma regra de anomalia do KAM-060; as duas do M-3 '
              'escreve-as a platform.manual_confirmar', p_regra
              USING ERRCODE = '22023';
          END IF;

          -- (2) O `detalhe` sem chave de PII, **a qualquer profundidade**.
          --
          -- O `jsonb_each_text` le so o topo, e um
          -- `{{"interno": {{"telefone": "..."}}}}` passava-o. O
          -- `jsonb_path_query` com `$.**` desce a arvore inteira; o `CASE`
          -- existe porque o `$.**` devolve tambem os nos que nao sao objecto, e
          -- o `jsonb_each_text` levanta nesses.
          FOR v_chave IN
            SELECT t.k
              FROM jsonb_path_query(p_detalhe, '$.**') AS n(no),
                   jsonb_each_text(
                     CASE WHEN jsonb_typeof(n.no) = 'object'
                          THEN n.no ELSE '{{}}'::jsonb END) AS t(k, v)
          LOOP
            FOREACH v_proibida IN ARRAY ARRAY[{pii}] LOOP
              IF position(v_proibida IN lower(v_chave)) > 0 THEN
                RAISE EXCEPTION
                  'a chave % nao entra num sinal: o criterio 8 do KAM-060 fecha '
                  'o detalhe em contact_id, charge_id, regra e severidade',
                  v_chave
                  USING ERRCODE = '22023';
              END IF;
            END LOOP;
          END LOOP;

          -- (3) A janela. **`IS NOT DISTINCT FROM` e nao `=`**, e e medido: um
          -- `charge_id = NULL` nunca e verdadeiro, pelo que com `=` os sinais
          -- sem cobranca — a R-02 e a R-06 — escapavam a guarda e escreviam
          -- linha nova a cada corrida do *job*.
          SELECT id INTO v_existe
            FROM platform.fraud_signals
           WHERE tenant_id = p_tenant_id
             AND regra = p_regra
             AND charge_id IS NOT DISTINCT FROM p_charge_id
             AND contact_id IS NOT DISTINCT FROM p_contact_id
             AND criado_at > now() - p_janela
           ORDER BY id DESC
           LIMIT 1;
          IF v_existe IS NOT NULL THEN
            RETURN v_existe;
          END IF;

          -- A `severidade` e a `accao` nao se validam aqui: a tabela ja as
          -- fecha (`fraud_signals_severidade_ck` e `fraud_signals_accao_ck` da
          -- `0032`), e repetir um `CHECK` que a base impoe era uma segunda
          -- fonte para um dominio que ja tem uma.
          INSERT INTO platform.fraud_signals (
              tenant_id, contact_id, charge_id, regra, severidade, accao,
              detalhe)
            VALUES (
              p_tenant_id, p_contact_id, p_charge_id, p_regra, p_severidade,
              p_accao, p_detalhe)
            RETURNING id INTO v_id;
          RETURN v_id;
        END;
        $$
        """
    )
    op.execute(
        f"COMMENT ON FUNCTION {ASSINATURA} IS "
        "'A porta de escrita dos sinais de anomalia do KAM-060. Nenhum papel "
        "tem INSERT em platform.fraud_signals, por decisao da revisao 0032: "
        "quem ela protegeu de escrever foi o kamba_app, que serve turnos de "
        "conversa. Esta funcao e EXECUTE do kamba_batch e nao do kamba_app, "
        "pelo que o motor de anomalias (que corre em lote) escreve sem que "
        "nenhum caminho de conversa ganhe essa forma. Tres barreiras: a regra "
        "contra lista fechada (a coluna nao tem CHECK), o detalhe sem chave de "
        "PII a qualquer profundidade, e a janela que nao repete o mesmo sinal a "
        "cada corrida. As duas regras do M-3 sao recusadas aqui: escreve-as a "
        "platform.manual_confirmar.'"
    )


def _indice() -> None:
    op.execute(
        f"CREATE INDEX {INDICE} ON {SINAIS} (tenant_id, regra, criado_at)"
    )
    op.execute(
        f"COMMENT ON INDEX platform.{INDICE} IS "
        "'Serve a guarda da janela da registar_sinal_de_anomalia. O "
        "fraud_signals_tenant_idx da 0032 e (tenant_id, criado_at) e serve o "
        "painel: com ele, a guarda varre todos os sinais do periodo para "
        "comparar a regra, uma vez por regra e por corrida do job.'"
    )


def _privilegios() -> None:
    """`EXECUTE` ao lote, e a mais ninguem.

    O `REVOKE ALL ... FROM PUBLIC` primeiro, pela razao da `0029` e da `0032`:
    uma funcao nasce com `EXECUTE` para `PUBLIC`, e sem este passo a excepcao do
    `DEFINER` ficava aberta a qualquer papel.

    **E ao `kamba_app` nao se concede**, que e a metade desta revisao que
    preserva a decisao do KAM-054. Nao e esquecimento: e a propriedade, e tem
    ensaio que quebra se ela mudar.
    """
    op.execute(f"REVOKE ALL ON FUNCTION {ASSINATURA} FROM PUBLIC")
    op.execute(f"GRANT EXECUTE ON FUNCTION {ASSINATURA} TO {PAPEL_DE_LOTE}")
