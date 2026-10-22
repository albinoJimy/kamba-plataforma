"""Modos da conversa: o privilegio que a 0009 deixou por conceder (KAM-018).

**A primeira linha e ASCII de proposito, e segue a forma das outras quinze.**
O `alembic history` imprime-a, e a suite compara a saida no processo com a do
executavel: um travessao aqui faz as duas divergirem na descodificacao e poe
`test_no_processo_e_pela_linha_de_comandos_o_alembic_diz_o_mesmo` vermelho.

Revisao: 0016
Anterior: 0015

**Esta revisao nao cria nada.** Nao ha tabela nova, nao ha coluna nova, nao ha
`CHECK` novo e nao ha politica nova — e por isso o inventario de colunas
(`db/tests/test_inventario.py`), a lista de restricoes e o X-05 do *gate* 6
ficam exactamente como estavam. O que ela faz sao **dois `GRANT UPDATE` por
coluna**, e isso e o centro do KAM-018.

## O que a 0009 escreveu, e o que mudou desde entao

A `0009` criou `platform.conversations` com a coluna `mode` e o seu `CHECK` de
quatro valores, e concedeu a `kamba_app` `UPDATE` em **duas** colunas —
`last_inbound_at` e `window_expires_at`. A razao esta escrita la, por extenso:

> **Nao da `UPDATE (mode)` a `kamba_app`.** O KAM-014 escreve o valor de
> omissao (`bot`, no `INSERT`) e **le** os outros para decidir se a mensagem vai
> ao AGR; as transicoes de modo sao KAM-018, e e esse ticket que pede o
> privilegio. Um `UPDATE (mode)` concedido aqui era a aplicacao a poder
> silenciar ou dessilenciar uma conversa sem o protocolo que o KAM-018 define.

A objeccao era «sem o protocolo». O protocolo existe agora
(`packages/core-ts/src/modos/`, e `docs/modos-conversa.md`), e e este ticket que
pede o privilegio — que e o que a frase da `0009` manda fazer. As duas colunas
que o ganham:

* **`mode`** — e o que o protocolo escreve. Sem ele, nenhum papel de aplicacao
  consegue mudar quem tem a palavra: a `0011` (KAM-019) ja o registou ao deixar
  o `setBotMuted` a levantar `SemPrivilegioError`, e a `0015` (KAM-022) ao
  deixar a porta `MudarModo` do `ConsentGate` por ligar.
* **`last_human_activity_at`** — a `0009` deixou-a de fora pela mesma razao
  («e KAM-018/KAM-019»). E a coluna que o `PreSendGuard` **le** para decidir se
  houve actividade humana depois do inicio do turno, e que a maquina de modos
  **escreve** quando uma pessoa passa a ter a palavra. Sem `UPDATE` nela, o
  relogio das 24 h nunca avancava e o guarda comparava-se sempre com `NULL`.

## O que este `GRANT` **nao** garante, e fica dito em vez de escondido

Um `GRANT UPDATE (mode)` a `kamba_app` da a **toda** a aplicacao a capacidade de
escrever a coluna, incluindo por fora da maquina de estados. A contencao nao e
de privilegio, e vale a pena dizer o que ela e:

1. o `UPDATE` que a maquina corre leva o predicado da tabela de transicoes no
   proprio `WHERE` (`AND mode = ANY($4)`), que e o padrao que o
   `SQL_AVANCAR_ESTADO` da `0010` ja fixou — «a monotonia e imposta pela base e
   nao por este codigo»;
2. o `CHECK` de quatro valores da `0009` continua a ser a ultima barreira: um
   modo que nao exista nao entra, venha de onde vier;
3. o `pg_advisory_xact_lock(hash(tenant_id, contact_id))` serializa a transicao
   e a verificacao pre-envio da **mesma** conversa.

**A alternativa era um papel novo** — um `kamba_modo` com `SELECT` e
`UPDATE (mode, last_human_activity_at)` e mais nada — e nao se tomou por duas
razoes. A primeira e que um papel nao se cria numa migracao: o Alembic corre
como `kamba_migrator` e `db/bootstrap.py` e quem cria os seis papeis, pelo que
um setimo era alterar o arranque de toda a instancia dentro deste ticket. A
segunda e que um papel so move a fronteira: quem o detiver continua a poder
escrever qualquer modo, porque **um `SECURITY DEFINER` esta vedado** — o X-05 do
*gate* 6 recusa-o (`ci/secdef_allowlist.yaml`), e a `0004`, a `0005` e a `0007`
escreveram tres vezes porque: «passaria por cima da RLS e punha todo o
isolamento de tenant a depender dos argumentos». Uma funcao `SECURITY INVOKER`
exigiria o mesmo `UPDATE` ao chamador e nao conteria nada.

A decisao sobre o papel devolve-se a quem desenhar a topologia de ligacoes
(KAM-078); esta revisao concede o minimo que o protocolo precisa, e a lista de
colunas abaixo e a sua propria documentacao.

**O que esta revisao NAO faz, e e escopo e nao esquecimento:**

* **Nao acrescenta `suppressed_by_human` a `outbound_messages.state`.** Os
  *Detalhes Tecnicos* do KAM-018 dizem «adiciona se ainda nao existir», e ele
  **existe**: nasceu na `0010`, que o escreveu por antecipacao pela mecanica do
  *gate* 3b (o AST de cada revisao e lido isoladamente, e alargar o dominio numa
  revisao nova deixava a `0010` vermelha por lhe faltar um valor). Nada a fazer.
* **Nao cria tabela de *echoes*.** A `smb_message_echoes` e a coexistencia, e e
  KAM-017.
* **Nao cria coluna de controlo para o *job* das 24 h.** Ele e idempotente pelo
  predicado — `WHERE mode = 'humano' AND ... < $2` deixa de casar depois da
  primeira passagem — e nao por uma marca escrita. Uma coluna «pausada_em» que
  ninguem lesse era peso morto; ver `SQL_PAUSAR_POR_INACTIVIDADE`.
* **Nao impoe retencao.** Como as quinze anteriores: o agendador nasce com
  KAM-071.
* **Nao da privilegio ao `kamba_identity` nem ao `kamba_resolver`.** O primeiro
  ja tem `UPDATE (last_human_activity_at)` desde a `0009`, e **so** porque a
  fusao de contactos dobra os tempos dentro da transacao dela; o segundo nao
  toca em conversas.
"""

from __future__ import annotations

from alembic import op

revision = "0016"
down_revision = "0015"
branch_labels = None
depends_on = None

#: As colunas de uma conversa que o `kamba_app` passa a poder alterar.
#:
#: **Quatro, e eram duas.** As duas da `0009` (`last_inbound_at`,
#: `window_expires_at`) repetem-se aqui de proposito: um `GRANT UPDATE (a, b)`
#: nao substitui um `GRANT UPDATE (c, d)` — os privilegios por coluna somam-se —,
#: mas quem ler esta constante tem de poder responder «o que e que a aplicacao
#: pode escrever numa conversa?» sem abrir a `0009`. O `downgrade` so revoga as
#: **duas novas**, e e por isso que elas tem constante propria.
#:
#: As quatro que **continuam de fora**: `id`, `tenant_id`, `contact_id` e
#: `channel_id`. Alterar qualquer uma por esta via e reescrever a identidade da
#: conversa — mover uma conversa de contacto e de canal —, e quem a reaponta
#: numa fusao e o `kamba_identity`, dentro da transacao da fusao (`0009`).
COLUNAS_DA_APLICACAO = (
    "mode",
    "last_human_activity_at",
    "last_inbound_at",
    "window_expires_at",
)

#: As duas que **esta** revisao concede, e as unicas que o `downgrade` revoga.
#:
#: Separadas das quatro acima porque um `REVOKE UPDATE (last_inbound_at)` aqui
#: tirava a `kamba_app` um privilegio da `0009` que esta revisao nunca lhe deu —
#: e o `downgrade` passava a deixar a base **pior** do que a encontrou, com o
#: CHR do KAM-014 sem conseguir empurrar a janela de 24 h. Medido em
#: `db/tests/test_modos_privilegios.py`.
COLUNAS_NOVAS = ("mode", "last_human_activity_at")


def upgrade() -> None:
    # Coluna a coluna, sem `ALTER DEFAULT PRIVILEGES`: a mesma regra das quinze
    # anteriores (`db/migrations/README.md`).
    #
    # **Nao ha `GRANT SELECT` a acrescentar.** A `0009` ja deu
    # `GRANT SELECT, INSERT ON platform.conversations TO kamba_app`, e e dele
    # que vem a leitura do `mode` e do `last_human_activity_at` que o guarda
    # faz. Um `GRANT SELECT (mode, ...)` aqui era redundante e, pior, fazia
    # parecer que a leitura nasce neste ticket.
    op.execute(
        f"GRANT UPDATE ({', '.join(COLUNAS_NOVAS)}) "
        "ON platform.conversations TO kamba_app"
    )

    op.execute(
        "COMMENT ON COLUMN platform.conversations.last_human_activity_at IS "
        "'Instante da ultima actividade humana nesta conversa. Escrita pela "
        "maquina de modos (KAM-018) quando uma pessoa passa a ter a palavra; "
        "lida pelo PreSendGuard para comparar com o inicio do turno.'"
    )


def downgrade() -> None:
    """Reverter devolve a base ao estado da `0009`: ninguem muda o modo.

    **Nao ha perda de dados e por isso nao ha copia logica.** Ao contrario da
    `0009` — que apaga a tabela e exige `KAMBA_DOWNGRADE_0009_COPIA` — esta
    revisao nao escreve linha nenhuma: o que ela da e o que ela tira e um
    privilegio. Uma conversa que esteja em `humano` continua em `humano` depois
    do `downgrade`; o que deixa de haver e quem a possa tirar de la.

    **E isso tem uma consequencia que fica dita:** com esta revisao revertida, o
    *job* das 24 h e o `onOptOut` deixam de funcionar (`permission denied for
    table conversations`) e uma conversa passada a `humano` fica la ate alguem
    correr um `UPDATE` como `kamba_batch`. E o estado em que o repositorio esteve
    entre a `0009` e esta revisao, e nao e um estado novo.
    """
    op.execute(
        "COMMENT ON COLUMN platform.conversations.last_human_activity_at IS NULL"
    )
    # So as duas desta revisao. Ver a nota de `COLUNAS_NOVAS`: revogar as quatro
    # deixava a base pior do que a `0009` a tinha.
    op.execute(
        f"REVOKE UPDATE ({', '.join(COLUNAS_NOVAS)}) "
        "ON platform.conversations FROM kamba_app"
    )
