"""O trigger por instrucao do order_state_log passa a cobrir o UPDATE (KAM-176).

A primeira linha e **sem acentos**, como as trinta revisoes anteriores: e a
mensagem que o `alembic history` imprime, e o
`test_no_processo_e_pela_linha_de_comandos_o_alembic_diz_o_mesmo` compara a
saida no processo com a do executavel. Com acentos, as duas divergem na
codificacao.

## O defeito, que e meia deducao e nao uma gralha

A `0030` (KAM-044) protege a `platform.order_state_log` com dois *triggers*
sobre a mesma `platform.deny_mutation()`:

    order_state_log_sem_mutacao    BEFORE UPDATE OR DELETE    FOR EACH ROW
    order_state_log_sem_truncate   BEFORE TRUNCATE OR DELETE  FOR EACH STATEMENT

Um *trigger* por linha **nao dispara quando nao ha linhas**. O `DELETE` sem
linhas esta fechado, porque o por instrucao inclui `DELETE`. O `UPDATE` nao:
`UPDATE platform.order_state_log SET ... WHERE <predicado que nao casa>` nao e
recusado por nenhum dos dois, devolve `UPDATE 0` e passa.

**E o argumento que fecha um esta escrito ao lado do outro.** O comentario
imediatamente acima daquele `CREATE TRIGGER`, no KAM-044, di-lo por extenso —
«um `BEFORE DELETE ... FOR EACH ROW` nao dispara quando nao ha linhas», «com o
`FOR EACH STATEMENT`, a recusa vem antes de haver linhas e e a mesma para o caso
que apaga e para o que nao apaga». O argumento nao tem nada de particular ao
`DELETE`: vale letra por letra para o `UPDATE`, que esta no por linha pela mesma
razao. O KAM-044 seguiu-o ate metade.

Nenhuma linha se perde: o que falha e a **propriedade**. Quem audita a tabela,
como o `docs/tecnica/08` secao 6 manda, corre a instrucao proibida e le
`UPDATE 0` sem erro — indistinguivel de «a tabela aceita `UPDATE` e nao havia
nada para actualizar». Num registo que e a prova de toda a transicao de estado
de uma encomenda, essa ressalva tacita e o pior que pode ficar sem estar escrito.

## Porque e uma revisao nova e nao uma edicao da `0030`

E a letra do criterio 5 do KAM-176, e segue-se. **Mas a razao que ele da e
falsa, e isso fica dito aqui em vez de ser corrigido em silencio.**

O criterio decide por «a `0030` fundiu na `main` a 2026-11-03 no `84f3169`, pelo
que qualquer clone que tenha corrido `alembic upgrade head` desde entao a tem».
Medido no KAM-175 e **a premissa nao se sustenta**, nem para a `0030` nem para a
`0029`:

* a `0029` **tambem** fundiu (`94bd634`, #104), antes da `0030` — pelo que a
  mesma regra aplicada a ela daria revisao nova, e o KAM-175 fez edicao no
  sitio;
* e nenhuma base pode ter corrido `alembic upgrade head`. O
  `db/migrations/README.md` di-lo no seu ultimo paragrafo — «nao ha ainda forma
  de aplicar as migracoes ao PostgreSQL do compose de desenvolvimento: a rede de
  dados e interna e nao publica portas» — e o
  `infra/compose/docker-compose.dev.yml` confirma-o: o servico `db` nao tem
  `ports:` e esta so na rede `data`, que e `internal: true`.

**A conclusao, porem, esta certa, e a razao suficiente e simples: uma revisao
nova e correcta com a premissa e sem ela; a edicao no sitio so e correcta com
ela.** Nao precisa de mais do que isto, e e por isso que esta revisao existe —
nao por o criterio o dizer.

**Uma razao a mais que se escreveu aqui primeiro, e que NAO se sustenta como
medicao**, fica registada porque e instrutiva: dizia-se que «a janela esta a
fechar-se», porque hoje e o dia em que o KAM-076 fundiu o compose de producao.
Medido pela revisao adversarial: o `infra/compose/docker-compose.prod.yml`
tambem poe o `postgres` **sem `ports:`** numa rede `internal: true`, e
`grep -i alembic -- infra/` da **zero** — isto e, o compose de producao reproduz
exactamente a propriedade que se estava a usar para provar o contrario. E o
credor do buraco de aplicacao e o **KAM-075**, que ja fundiu (#103) sem o fechar.
Logo «a janela esta a fechar-se» e uma **previsao** sobre o KAM-078, estado
**NAO VERIFICADO**, e nao uma medicao — e e o mesmo genero de afirmacao que esta
revisao recusa no criterio 5. Fica dito em vez de ficar a passar por medida.

A divergencia fica registada no bloco do KAM-176 e **devolvida a quem escreveu o
criterio**: emendar a letra de um criterio e de quem o escreveu, nao de quem o
executa.

## O que esta revisao NAO faz

* **Nao cria nem larga tabela nenhuma**, pelo que nao entra em nenhuma das
  tuplas `TABELAS_ATE_00NN` do `db/tests/base.py` nem nas seis listas fechadas
  que uma tabela nova obriga a tocar.
* **Nao muda o nome de nenhum *trigger***: o `order_state_log_sem_truncate`
  continua a chamar-se assim, que e o que mantem verdes os tres ensaios do
  `ENABLE ALWAYS` do `db/tests_encomendas/test_isolamento.py` — dois deles a
  correr em `session_replication_role = replica` — e o inventario de
  `db/tests/test_inventario.py`.
* **Nao cria funcao nenhuma**: a `deny_mutation` e da `0029` e serve os dois
  niveis, porque nao usa `OLD` nem `NEW` — levanta a excepcao com o `TG_OP` e o
  `TG_TABLE_NAME`, disponiveis nos dois. E por isso que a alteracao e a lista de
  eventos e nao a funcao, e e a mesma razao que o KAM-175 escreveu para a
  `payment_events`.
* **Nao toca nas tres tabelas irmas** da divida 176 (`platform.audit_log` da
  `0006`, `platform.tool_audit` da `0021`, `dat.llm_call_log` da `0023`): a
  barreira de uma tabela *append-only* decide-se em quem a tem, e a
  `llm_call_log` leva uma pergunta propria por ser particionada — a `0023` mediu
  que o por linha e o `BEFORE TRUNCATE ... FOR EACH STATEMENT` no pai sao aceites
  e que uma particao nova os herda, e nao diz nada sobre um `BEFORE DELETE`
  **nem** sobre um `BEFORE UPDATE ... FOR EACH STATEMENT` no pai. **Sao os dois
  verbos**, porque na `0023` as duas metades estao abertas; a divida 176 nomeava
  so o `DELETE` e a primeira versao deste cabecalho nomeava so o `UPDATE`, e as
  duas eram mais estreitas do que a pergunta (achado 13 da revisao adversarial).

## O `downgrade` repoe a forma antiga, e e reversivel no sentido que importa

Volta a `BEFORE TRUNCATE OR DELETE ... FOR EACH STATEMENT`, com o `ENABLE
ALWAYS` a seguir. Nenhuma linha se perde e a revisao nao larga a tabela: o que o
`downgrade` desfaz e so o alargamento da lista de eventos.
"""

from alembic import op

revision = "0031"
down_revision = "0030"
branch_labels = None
depends_on = None

REGISTO = "platform.order_state_log"

#: O *trigger* por instrucao, pelo nome. Fica o **mesmo** nome de proposito —
#: ver o cabecalho.
TRIGGER = "order_state_log_sem_truncate"


def _criar(eventos: str) -> None:
    """Recria o *trigger* por instrucao com a lista de eventos pedida.

    O `ENABLE ALWAYS` vem **sempre** a seguir, e nao e zelo: um *trigger*
    recriado nasce na omissao (`O`), e a omissao e saltada por
    `session_replication_role = replica`. Sem esta linha, um superutilizador que
    ponha a sessao em `replica` muta o registo e nada no catalogo diz que isso e
    possivel — e e a licao que a `0006` pagou e a `0030` herdou para os seus
    cinco *triggers*.

    Sem `CASCADE` no `DROP`, como todas as revisoes desde a `0001`: se o
    *trigger* nao estiver la, a revisao **falha** em vez de seguir em silencio.
    """
    op.execute(f"DROP TRIGGER {TRIGGER} ON {REGISTO}")
    op.execute(
        f"""
        CREATE TRIGGER {TRIGGER}
          BEFORE {eventos} ON {REGISTO}
          FOR EACH STATEMENT EXECUTE FUNCTION platform.deny_mutation()
        """
    )
    op.execute(f"ALTER TABLE {REGISTO} ENABLE ALWAYS TRIGGER {TRIGGER}")


def upgrade() -> None:
    _criar("TRUNCATE OR DELETE OR UPDATE")


def downgrade() -> None:
    _criar("TRUNCATE OR DELETE")
