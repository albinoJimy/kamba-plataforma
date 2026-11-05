"""Estado da saga de provisioning: a tabela provisioning_step (KAM-091).

A primeira linha e **sem acentos**, como as trinta e tres revisoes anteriores: e
a mensagem que o `alembic history` imprime, e o
`test_no_processo_e_pela_linha_de_comandos_o_alembic_diz_o_mesmo` compara a saida
no processo com a do executavel. Com acentos, as duas divergem na codificacao.

## O que esta revisao cria, e porque chega depois do codigo

A `platform.provisioning_step`, o armazem de estado da saga de oito passos do
KAM-091. **O codigo dela ja esta fundido** (`8b6edc3`) e esta tabela ficou de
fora de proposito: a cadeia Alembic e linear, e a `0033` do KAM-045 — onde esta
revisao encaixa — ainda nao tinha fundido. A caixa da DoD ficou com a razao
escrita e o credor nomeado; isto paga-a.

**O contrato da forma esta no codigo e nao no bloco do ticket**, e por uma razao
que se mede: as portas de `packages/core-ts/src/provisioning/contrato.ts` ja
estao em `main`, e sao elas que dizem o que a tabela tem de aceitar. O bloco do
ticket escreve uma vez `provisioning_step(case_id, ...)` e a chave e o
`onboarding_id` — a mencao foi corrigida no bloco por este PR, porque era uma
inconsistencia de canon que ninguem tinha medido.

## A chave e natural e composta, e nao ha `id` gerado

`PRIMARY KEY (onboarding_id, step)`. E a `UNIQUE(onboarding_id, step)` que a
linha 377 do contrato declara, promovida a chave primaria em vez de ficar ao
lado de um `uuid` aleatorio — como a `payment_outbox_map` da `0029` e as duas
tabelas de uso da `0009`, e pela mesma razao que o inventario de
`db/tests/test_catalogo.py` escreve para aquelas: a identidade desta linha **e**
o par, e um `id` gerado ao lado seria um identificador que nenhuma consulta
citaria.

E nao e so economia. **Nenhuma porta do contrato recebe um `id` de linha:** o
`marcarConcluido`, o `marcarFalhado`, o `marcarEscalado`, o `marcarCompensado` e
o `marcarEspera` recebem todos `(onboardingId, passo)`, e o `abrir` reabre o
mesmo par. Uma unicidade que levasse o `tenant_id` a frente — a escolha que a
`0033` fez para a reserva de stock, com a razao dela — tornava estas portas
**impossiveis de implementar**: o `ON CONFLICT (onboarding_id, step)` que o
`abrir` precisa nao casa uma restricao sobre o terno, e nenhum dos cinco
`marcar*` recebe um `tenant_id` para o completar.

## Sem chave estrangeira para `tenants`, e isso e desenho

O passo 1 da saga chama-se `tenant_e_caso` e e **ele** que escreve a linha de
`platform.tenants`. Uma FK daqui para la tornava o passo 1 impossivel: a linha
de `provisioning_step` do proprio passo 1 nasce antes do tenant existir.

O `tenant_id` fica como coluna `NOT NULL` e sem FK. E **pre-alocado** — o
dicionario secao 3.2 ja o escreve para o `onboarding_case` («criado no
registo») — e e por ele que a RLS e o X-05 do *gate* 6 agarram a tabela. A
integridade referencial que a FK dava fica a cargo do passo 1, e o que a
substitui como barreira e a politica `tenant_iso`.

## O indice que comeca pelo `tenant_id`, e a pergunta que ele serve

A chave primaria **nao** comeca pelo `tenant_id`, pelo que esta tabela e da
classe das que nao satisfazem a convencao de graca e levam indice proprio — como
a `handoffs`, a `channel_onboarding` e outras seis que `test_catalogo.py`
enumera. O indice e `(tenant_id, status)`, e a segunda coluna nao e enfeite: e a
pergunta do `EsperadoDoTenant` da reconciliacao («as referencias externas que o
`provisioning_step` tem como `concluido`», `reconciliacao.ts` linha 57), que e a
unica leitura desta tabela que atravessa casos em vez de ir a um.

**Nao e parcial no `concluido`**, e isso e deliberado: a RLS acrescenta
`tenant_id = ...` a **toda** a consulta, e um indice parcial nao serve as que
nao sao da reconciliacao.

## Os tres dominios fechados saem do codigo, nome por nome

O `step` sao os **oito** valores de `PASSOS` (contrato linha 87), **pela ordem**,
que e a que a compensacao inverte. O `status` sao os **cinco** de
`ESTADOS_DE_PASSO` (linha 111) — e o `compensado` existe como estado proprio por
uma razao de reconciliacao que esta escrita la: um passo desfeito e um passo que
nunca correu produzem ambos «nada la fora», e quem le a tabela tem de poder
distingui-los. O `status_de_espera` sao os **tres** de `ESPERAS` (linha 135),
que e o dominio do `marcarEspera`.

**O `aguarda_teste` nao esta no `onboarding_case.fase` do canon, e isso esta
medido e escrito no contrato**: aqueles seis valores sao da fase do caso, e
estes tres sao de uma coluna desta tabela. O credor dessa falta e o KAM-086/087,
e nao esta revisao.

## O `CHECK` de forma no `error_code`, que e a licao mais cara deste ticket

`error_code ~ '^[A-Za-z][A-Za-z0-9_]{2,63}$'`, que e **a mesma forma fechada que
o codigo ja impoe** no `codigoDoErro`. A revisao adversarial do KAM-091 mediu
que a caixa dos segredos estava marcada sobre prova que nao cobria o caminho que
vazava: o `erro.name` e escrevivel por quem lanca, e punha a chave inteira nesta
coluna. O codigo foi corrigido — o que nao casar a forma sai `erro_opaco` —, mas
a nota dessa caixa diz, com estas palavras, que «a coluna nao tem validador
nenhum». Agora tem.

E e satisfazivel pelo escritor que existe, que e a condicao para uma restricao
nao inutilizar uma operacao: o `codigoDoErro` devolve ou um identificador nesta
forma ou `erro_opaco`, e os dois passam.

## As duas implicacoes de estado, e as que **nao** estao aqui

- `falhado` ou `escalado` **exige** `error_code`: os dois `marcar*` recebem
  sempre o codigo, e um estado terminal de falha sem razao escrita era uma falha
  que ninguem diagnostica — e o `escalado` e o que abre o caso de revisao.
- `concluido` **exige** `error_code` e `status_de_espera` nulos: o
  `marcarConcluido` limpa os dois, e um passo concluido que ainda declara um erro
  ou uma espera contradiz-se — e e precisamente a linha que a reconciliacao le
  como «existe la fora».

**O que nao esta aqui, e nao e esquecimento:** `concluido` **nao** exige
`external_id`. O `marcarConcluido(onboardingId, passo, externalId: string |
null)` aceita o nulo na assinatura, e um passo que nao produz referencia externa
(o `entitlements`, o `teste_ponta_a_ponta`) conclui sem ela. Um `CHECK` a
exigi-la inutilizava cinco dos oito passos.

E o `compensado` **nao** limpa nada: o `marcarCompensado` so muda o estado, de
proposito — a referencia externa do recurso que foi desfeito e o que a
reconciliacao precisa para o reconhecer. Logo nenhuma implicacao o nomeia.

## O `attempt` nasce a zero e o `abrir` incrementa

`NOT NULL DEFAULT 0` com `CHECK (attempt >= 0)`. O `abrir` incrementa e devolve
a linha **depois** do incremento — e esse valor que o tecto de tres tentativas
do criterio 5 le —, e o `marcarEspera` **repoe a zero**, porque uma espera nao
e uma falha e tres passagens com o dono por agir escalavam o caso.

## O `downgrade` e o espelho do `upgrade`

Chama `rls.disable_tenant_rls` **explicitamente**, e nao deixa a politica cair
por efeito do `DROP TABLE`. As politicas caem de qualquer forma com a tabela; o
que nao cai e o ensaio de mutacao
`canon_lint...TestMutacoes.test_auxiliar_que_deixa_de_se_seguir`, que quebra o
`db/rls.py` de proposito e exige que **todas** as revisoes com RLS alcancem o
auxiliar directamente. Uma revisao que o alcancasse so no `upgrade` ficava do
lado errado do *gate* 4, que e o que avermelhou o KAM-054.

Os `CHECK`, a chave primaria e o indice caem com a tabela, pelo que nao se
apagam um a um. **Nenhuma funcao e nenhum *trigger* nascem nesta revisao**: a
`atualizado_at` e escrita pelo modulo em cada `UPDATE`, como na `0028`, na
`0030` e na `0033`.
"""

from __future__ import annotations

from alembic import op

import rls

revision = "0034"
#: **Encaixa na `0033`, e confirmou-se na integracao.**
#:
#: Quando o KAM-091 fundiu (`8b6edc3`), a `0033` do KAM-045 ainda estava num PR
#: aberto e esta revisao nao existia: a caixa da DoD ficou vazia com a razao
#: escrita. A `0033` fundiu depois (`27d5182`) e e a cabeca da cadeia, medido
#: com `git ls-tree --name-only refs/remotes/publico/main
#: db/migrations/versions/` no dia desta revisao, e nenhum PR aberto
#: acrescentava migracao.
#:
#: Renumerar **na integracao** e nao antes e a regra da casa: um ramo verde nao
#: reserva um numero para outro, e apontar para uma revisao que ainda nao esta
#: em `main` deixa a cadeia irresoluvel ate ela fundir — e deixar a
#: `down_revision` numa revisao que outra ja ocupa da **duas cabecas**, que o
#: `test_ha_uma_so_cabeca` de `db/tests/test_migracao.py` recusa.
down_revision = "0033"
branch_labels = None
depends_on = None

#: Literais e nao f-strings sobre outras constantes: o *gate* 3b le o AST da
#: revisao sem a executar e resolve `f"..."` sobre constantes de modulo, mas nao
#: sobre constantes que sejam elas proprias f-strings. A `0023` pagou nove
#: `op.execute` lidos como `[ilegivel]` para aprender isto.
PASSOS = "platform.provisioning_step"

#: Os **oito** passos da saga, pela ordem de `PASSOS` do contrato (linha 87) —
#: que e a ordem que a compensacao inverte. Ja entre apostrofos, pela razao da
#: `0015`: e a unica forma que o *gate* 3b resolve, porque segue
#: `", ".join(<constante de modulo>)` dentro de uma f-string.
PASSOS_DA_SAGA = (
    "'tenant_e_caso'",
    "'chave_llm'",
    "'canal_comercio'",
    "'conta_atendimento'",
    "'entitlements'",
    "'espera_es'",
    "'inbox_e_rota'",
    "'teste_ponta_a_ponta'",
)

#: Os **cinco** estados de um passo, do `ESTADOS_DE_PASSO` do contrato (linha
#: 111). O `escalado` e terminal ate alguem intervir; o `compensado` distingue
#: «foi desfeito» de «nunca correu», que e o que a reconciliacao nocturna le.
ESTADOS_DE_PASSO = (
    "'em_curso'",
    "'concluido'",
    "'falhado'",
    "'escalado'",
    "'compensado'",
)

#: As **tres** esperas dos passos 6-8, do `ESPERAS` do contrato (linha 135).
ESPERAS = ("'aguarda_es'", "'aguarda_catalogo'", "'aguarda_teste'")

#: A forma fechada do `error_code`, **a mesma que o `codigoDoErro` impoe**. Ver
#: a nota do modulo: e a correccao da fuga que a revisao adversarial do KAM-091
#: mediu, e e satisfazivel pelo unico escritor que existe.
FORMA_DO_ERRO = "^[A-Za-z][A-Za-z0-9_]{2,63}$"

PAPEL_DA_APP = "kamba_app"
PAPEL_DE_LOTE = "kamba_batch"

#: As colunas que o `kamba_app` pode actualizar, uma a uma. **Sem o
#: `onboarding_id`, o `tenant_id` e o `step`**, que sao a identidade da linha e o
#: tenant: o `abrir` reabre o par que ja existe, nunca o muda.
UPDATE_DA_APP = (
    "status",
    "attempt",
    "external_id",
    "error_code",
    "status_de_espera",
    "atualizado_at",
)


def upgrade() -> None:
    _provisioning_step()
    _rls()
    _privilegios()


def _provisioning_step() -> None:
    """O armazem de estado da saga, com a chave natural do contrato."""
    op.execute(
        f"""
        CREATE TABLE {PASSOS} (
            -- A chave da saga, `uuid` e **pre-existente ao passo 1**: o caso
            -- nasce no registo (KAM-086/087) e a saga chaveia por ele. Sem FK
            -- para `onboarding_case`, que e tabela que ainda nao existe.
            onboarding_id    uuid        NOT NULL,
            -- **Pre-alocado e sem FK para `platform.tenants`**, e isso e
            -- desenho: o passo 1 (`tenant_e_caso`) e que escreve a linha de
            -- `tenants`, pelo que uma FK tornava o proprio passo 1 impossivel.
            -- E por esta coluna que a RLS e o X-05 do *gate* 6 agarram a
            -- tabela.
            tenant_id        uuid        NOT NULL,
            step             text        NOT NULL,
            status           text        NOT NULL,
            -- O `abrir` incrementa e devolve a linha **depois** do incremento;
            -- e este valor que o tecto de tres tentativas do criterio 5 le. O
            -- `marcarEspera` repoe a zero, porque uma espera nao e falha.
            attempt          integer     NOT NULL DEFAULT 0,
            -- A referencia do recurso criado la fora. Anulavel: dois dos oito
            -- passos nao produzem recurso externo nenhum.
            external_id      text,
            -- A **classe** do erro ou um identificador curto, nunca a
            -- mensagem. A forma e imposta por `CHECK` e nao so pelo modulo —
            -- ver a nota do modulo.
            error_code       text,
            -- A espera dos passos 6-8 (criterio 6). Anulavel, e o nulo e o
            -- estado normal: um passo que nao espera por ninguem.
            status_de_espera text,
            criado_at        timestamptz NOT NULL DEFAULT now(),
            -- Escrito pelo modulo em cada `UPDATE`, nao por *trigger* — a
            -- mesma escolha da `0028`, da `0030` e da `0033`.
            atualizado_at    timestamptz NOT NULL DEFAULT now(),
            -- A `UNIQUE(onboarding_id, step)` da linha 377 do contrato,
            -- **promovida a chave primaria**. Ver a nota do modulo: nenhuma
            -- porta recebe um `id` de linha, e um terno com o `tenant_id` a
            -- frente nao casava o `ON CONFLICT` do `abrir`.
            CONSTRAINT provisioning_step_pkey PRIMARY KEY (onboarding_id, step),
            CONSTRAINT provisioning_step_step_ck
                CHECK (step IN ({", ".join(PASSOS_DA_SAGA)})),
            CONSTRAINT provisioning_step_status_ck
                CHECK (status IN ({", ".join(ESTADOS_DE_PASSO)})),
            -- **Sem `IS NULL OR`, e a coluna continua anulavel.** Um `CHECK`
            -- passa quando a expressao e verdadeira **ou nula**, e
            -- `NULL IN (...)` e nulo: a guarda explicita era redundante, e o
            -- *gate* 3b nao a le como dominio fechado (medido na `0030`).
            CONSTRAINT provisioning_step_espera_ck
                CHECK (status_de_espera IN ({", ".join(ESPERAS)})),
            CONSTRAINT provisioning_step_attempt_ck CHECK (attempt >= 0),
            -- A forma fechada do `codigoDoErro`, agora tambem no catalogo.
            CONSTRAINT provisioning_step_error_code_ck
                CHECK (error_code ~ '{FORMA_DO_ERRO}'),
            -- Vazio nao e uma referencia. Pela razao do `sku` da `0033`: um
            -- `external_id` vazio gravava «ha um recurso la fora» sem dizer
            -- qual, e a reconciliacao comparava-o contra nada.
            CONSTRAINT provisioning_step_external_id_ck
                CHECK (btrim(external_id) <> ''),
            -- Uma falha terminal sem razao escrita era uma falha que ninguem
            -- diagnostica, e o `escalado` e o que abre o caso de revisao. Os
            -- dois `marcar*` recebem sempre o codigo.
            CONSTRAINT provisioning_step_falha_exige_codigo_ck
                CHECK (status NOT IN ('falhado', 'escalado')
                       OR error_code IS NOT NULL),
            -- Um passo concluido que ainda declara um erro ou uma espera
            -- contradiz-se, e e esta a linha que a reconciliacao le como
            -- «existe la fora». O `marcarConcluido` limpa os dois.
            CONSTRAINT provisioning_step_concluido_limpo_ck
                CHECK (status <> 'concluido'
                       OR (error_code IS NULL AND status_de_espera IS NULL))
        )
        """
    )
    op.execute(
        f"COMMENT ON TABLE {PASSOS} IS "
        "'Estado da saga de provisioning de oito passos (KAM-091): uma linha "
        "por passo de cada caso, chaveada por (onboarding_id, step). O "
        "tenant_id e pre-alocado e nao tem FK para platform.tenants, porque e "
        "o passo tenant_e_caso que escreve essa linha. O contrato da forma "
        "esta em packages/core-ts/src/provisioning/contrato.ts; o estado "
        "compensado distingue um passo desfeito de um que nunca correu, que e "
        "o que a reconciliacao nocturna le.'"
    )
    # A chave primaria **nao** comeca pelo `tenant_id`, logo indice proprio a
    # comecar por ele. A segunda coluna e a pergunta do `EsperadoDoTenant` da
    # reconciliacao: «os passos `concluido` deste tenant». Nao parcial — ver a
    # nota do modulo.
    op.execute(
        f"CREATE INDEX provisioning_step_tenant_idx ON {PASSOS} "
        "(tenant_id, status)"
    )


def _rls() -> None:
    """RLS `FORCE` e politica `tenant_iso` na unica tabela da revisao.

    Chamado **directamente** e nao por iteracao sobre uma lista: o *gate* 3b le
    o AST da revisao sem a executar e resolve a chamada com os argumentos que
    consegue ler, e um `for` sobre uma lista de nomes deixava-o sem os ver.
    """
    rls.enable_tenant_rls("provisioning_step")


def _privilegios() -> None:
    """Tabela a tabela e coluna a coluna, como a `0028`, a `0030` e a `0033`."""
    op.execute(f"GRANT SELECT, INSERT ON {PASSOS} TO {PAPEL_DA_APP}")
    op.execute(
        f"GRANT UPDATE ({', '.join(UPDATE_DA_APP)}) ON {PASSOS} "
        f"TO {PAPEL_DA_APP}"
    )
    # **Sem `DELETE` para o `kamba_app`**, e e o criterio 3 por construcao: um
    # passo nao se apaga, compensa-se. Apagar a linha era perder a distincao
    # entre «foi desfeito» e «nunca correu», que e a razao pela qual o
    # `compensado` existe como estado proprio — e sem ela a reconciliacao
    # nocturna classificava um recurso compensado como `externo_em_falta` e
    # voltava a cria-lo.
    #
    # O `SELECT` e o `UPDATE` por coluna sao o que a saga precisa: ela corre sob
    # o `app.tenant_id` do caso (criterio 6 dos *Testes Requeridos*), pelo que e
    # um papel sujeito a RLS que escreve aqui.
    op.execute(
        f"GRANT SELECT, INSERT, UPDATE, DELETE ON {PASSOS} TO {PAPEL_DE_LOTE}"
    )


def downgrade() -> None:
    # Sem `CASCADE`, como todas as revisoes desde a `0001`: se houver um objecto
    # pendurado que esta revisao nao criou, o `downgrade` **falha** em vez de o
    # apagar em silencio.
    #
    # A RLS primeiro, que e a ordem inversa do `upgrade`. **Explicitamente**, e
    # nao por efeito do `DROP TABLE`: ver a nota do modulo e o ensaio de mutacao
    # do `canon_lint`.
    rls.disable_tenant_rls("provisioning_step")
    # Os oito `CHECK`, a chave primaria e o indice caem com a tabela. Nenhuma
    # funcao e nenhum *trigger* nascem nesta revisao, pelo que nao ha nada a
    # apagar depois.
    op.execute(f"DROP TABLE {PASSOS}")
