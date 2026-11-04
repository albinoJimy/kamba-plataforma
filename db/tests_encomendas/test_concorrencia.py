"""Criterio 2: vinte transicoes concorrentes dao 1 vencedora e 19 conflitos.

O que so aqui se prova, e nenhum duplo de teste pode: que vinte transicoes sobre
a mesma versao deixam **uma** linha escrita, **uma** linha de registo e dezanove
a reler. Um `Promise.all` sobre um objecto em memoria nao tem transaccoes para
serializar; isto tem vinte ligacoes a um PostgreSQL real.

## O que o `version = $3` acrescenta, e o que ele **nao** e

Este ficheiro afirmava, na primeira versao, que era o `version = $3` que
serializava as vinte, e que sem ele mais do que uma escreveria. **Mediu-se, e
estava errado: sem o `version`, ganha uma.** Sob `READ COMMITTED` a segunda
transaccao espera pela primeira na tranca da linha e **reavalia** o `WHERE`
sobre a versao nova dela: o `estado = $4` sozinho ja chega para que as outras
dezanove escrevam zero linhas.

O que o `version` acrescenta e outra coisa, e tem o seu canario: apanha o
**ciclo**. Quando a encomenda vai `aguarda_pagamento -> expirada ->
aguarda_pagamento` entre a leitura de quem chama e a escrita dele — duas
transicoes do §6.2, e um caso corrente —, o estado volta ao mesmo valor e o
predicado do estado nao ve diferenca nenhuma. A versao viu. Os dois ensaios
estao abaixo, e o segundo passa **sem** o predicado e falha **com** ele, que e a
prova nos dois sentidos.

## «Nunca forcam» mede-se, e nao se afirma

O §6.2 acaba com «falha de CAS ⇒ reler e reavaliar (nunca forcar)». As dezanove
que perdem releem — e o que o ensaio verifica e o resultado dessa releitura: a
versao que elas veem e a **de depois** da vencedora, e nenhuma delas escreve.
Por isso o ensaio conta tres coisas: uma linha mudada, **uma** linha de
`order_state_log` e a versao final em 2. Se alguma das dezanove tivesse tentado
outra vez com a versao nova, a terceira contagem subia.
"""

from __future__ import annotations

import concurrent.futures

import ligacao
import pg8000.dbapi
from tests.base import sqlstate
from tests_encomendas.base import ComEncomendas
from tests_encomendas.consultas import SQL_LER, SQL_TRANSITAR

#: Vinte, como o criterio pede. Uma ligacao por transicao: e a unica forma de as
#: ter a disputar a mesma versao — na mesma ligacao a segunda via a primeira.
TRANSICOES = 20

#: O `SQL_TRANSITAR` sem o predicado da versao. **E a mutacao do canario**, e
#: escreve-se aqui por extenso em vez de se derivar do texto do modulo por
#: substituicao: uma substituicao que falhasse em silencio deixava o canario a
#: correr a consulta certa e a afirmar que a mutacao passa.
SQL_SEM_VERSAO = """
  UPDATE platform.orders_mirror
     SET estado = %s, version = version + 1, atualizado_at = now()
   WHERE tenant_id = %s AND id = %s AND estado = %s
     AND deleted_at IS NULL
  RETURNING version
"""


def _transitar_noutra_ligacao(tenant: str, encomenda: str, versao: int):
    """Uma transicao, numa ligacao propria, confirmada ou revertida.

    Devolve `("ok", versao_nova)`, `("conflito", versao_relida)` ou
    `("erro", sqlstate)`. Nao levanta: o que o ensaio quer e a **distribuicao**
    dos resultados, e uma excepcao a atravessar a piscina perdia as outras
    dezanove.

    **Depois do conflito nao ha segunda tentativa**, e e isso que o criterio
    chama «nunca forcam»: a funcao le o estado novo e devolve-o.
    """
    conexao = ligacao.ligar("app")
    try:
        cursor = conexao.cursor()
        cursor.execute("SELECT set_config('app.tenant_id', %s, true)", (tenant,))
        cursor.fetchone()
        cursor.execute(
            SQL_TRANSITAR.sql,
            SQL_TRANSITAR.args(
                tenant,
                encomenda,
                versao,
                "criada",
                "aguarda_pagamento",
                None,
                None,
                None,
                None,
                None,
            ),
        )
        linha = cursor.fetchone()
        if linha is None:
            conexao.rollback()
            cursor.execute("SELECT set_config('app.tenant_id', %s, true)", (tenant,))
            cursor.fetchone()
            cursor.execute(SQL_LER.sql, SQL_LER.args(tenant, encomenda))
            relida = cursor.fetchone()
            conexao.rollback()
            return "conflito", int(relida[3])
        nova = int(linha[3])
        cursor.execute(
            "INSERT INTO platform.order_state_log "
            "       (tenant_id, order_id, de, para, version, causa, actor_kind) "
            "VALUES (%s, %s, 'criada', 'aguarda_pagamento', %s, 'charge.issued', 'ops')",
            (tenant, encomenda, nova),
        )
        conexao.commit()
        return "ok", nova
    except pg8000.dbapi.DatabaseError as erro:
        conexao.rollback()
        return "erro", sqlstate(erro)
    finally:
        conexao.close()


def _transitar_sem_versao(
    tenant: str,
    encomenda: str,
    de: str = "criada",
    para: str = "aguarda_pagamento",
):
    """A mutacao do canario: o mesmo `UPDATE` sem `version = $3`.

    O par `(de, para)` entra por argumento porque os dois canarios o precisam
    diferente: o das vinte concorrentes sai de `criada`, e o do ciclo sai de
    `aguarda_pagamento` — e e **por** o estado ser o mesmo nos dois lados do
    ciclo que o predicado do estado o deixa passar.
    """
    conexao = ligacao.ligar("app")
    try:
        cursor = conexao.cursor()
        cursor.execute("SELECT set_config('app.tenant_id', %s, true)", (tenant,))
        cursor.fetchone()
        cursor.execute(SQL_SEM_VERSAO, (para, tenant, encomenda, de))
        linha = cursor.fetchone()
        if linha is None:
            conexao.rollback()
            return "conflito", 0
        nova = int(linha[0])
        cursor.execute(
            "INSERT INTO platform.order_state_log "
            "       (tenant_id, order_id, de, para, version, causa, actor_kind) "
            "VALUES (%s, %s, %s, %s, %s, 'canario', 'ops')",
            (tenant, encomenda, de, para, nova),
        )
        conexao.commit()
        return "ok", nova
    except pg8000.dbapi.DatabaseError as erro:
        conexao.rollback()
        return "erro", sqlstate(erro)
    finally:
        conexao.close()


class TestCasSobConcorrencia(ComEncomendas):
    """Criterio 2: uma vencedora, dezanove a reler, nenhuma a forcar."""

    def setUp(self) -> None:
        super().setUp()
        self.tenant = self.criar_tenant()
        self.encomenda = self.criar_encomenda(self.tenant)

    def test_vinte_na_mesma_versao_dao_uma_vencedora_e_dezanove_conflitos(self) -> None:
        with concurrent.futures.ThreadPoolExecutor(max_workers=TRANSICOES) as piscina:
            tarefas = [
                piscina.submit(
                    _transitar_noutra_ligacao, self.tenant, self.encomenda, 1
                )
                for _ in range(TRANSICOES)
            ]
            resultados = [t.result() for t in concurrent.futures.as_completed(tarefas)]

        vencedoras = [v for r, v in resultados if r == "ok"]
        conflitos = [v for r, v in resultados if r == "conflito"]
        erros = [v for r, v in resultados if r == "erro"]

        self.assertEqual(erros, [], "um conflito de CAS nao e um erro de SQL")
        self.assertEqual(
            len(vencedoras), 1, "o predicado `version = $3` deixa passar uma"
        )
        self.assertEqual(len(conflitos), TRANSICOES - 1)
        self.assertEqual(vencedoras, [2], "a vencedora leva a encomenda a versao 2")
        self.assertEqual(
            set(conflitos),
            {2},
            "as dezanove releem e veem a versao **de depois** da vencedora: e "
            "nisso que «reler e reavaliar» se distingue de «tentar outra vez»",
        )

        self.assertEqual(self.estado_de(self.encomenda), ("aguarda_pagamento", 2))
        self.assertEqual(
            self.consultar(
                "SELECT count(*) FROM platform.order_state_log WHERE order_id = %s",
                (self.encomenda,),
            ),
            [(1,)],
            "uma transicao, um registo: se alguma das dezanove tivesse forcado "
            "com a versao nova, esta contagem subia",
        )

    def test_o_predicado_do_estado_sozinho_tambem_da_uma_vencedora(self) -> None:
        """**A medicao que corrigiu este ficheiro**, e fica escrita.

        A primeira versao deste canario tirava o `version = $3` e afirmava que
        as vinte passariam a ganhar mais do que uma. **Nao passam: ganha uma.**
        Sob `READ COMMITTED`, a segunda transaccao espera pela primeira na
        tranca da linha e **reavalia** o `WHERE` sobre a versao nova dela — ve
        `estado = 'aguarda_pagamento'` onde o predicado pede `'criada'`, e
        escreve zero linhas. O predicado do estado, sozinho, serializa.

        O ensaio fica — invertido —, porque e ele que impede a conclusao errada
        de que o ensaio de cima mede o `version`: nao mede. O que o `version`
        acrescenta esta no ensaio seguinte.
        """
        with concurrent.futures.ThreadPoolExecutor(max_workers=TRANSICOES) as piscina:
            tarefas = [
                piscina.submit(_transitar_sem_versao, self.tenant, self.encomenda)
                for _ in range(TRANSICOES)
            ]
            resultados = [t.result() for t in concurrent.futures.as_completed(tarefas)]

        vencedoras = sorted(v for r, v in resultados if r == "ok")
        self.assertEqual(
            vencedoras,
            [2],
            "medido: o predicado do estado serializa por reavaliacao do WHERE "
            "sob READ COMMITTED",
        )

    def test_canario_o_que_o_version_acrescenta_e_apanhar_o_ciclo(self) -> None:
        """O que o `version = $3` faz e o `estado = $4` nao, medido nos dois sentidos.

        O caso e o **ciclo**: entre a leitura de quem chama e a escrita dele, a
        encomenda foi `aguarda_pagamento -> expirada -> aguarda_pagamento` (o
        §6.2 tem as duas transicoes, e e um caso corrente — a referencia expira e
        emite-se outra). O estado voltou ao mesmo valor, pelo que o predicado do
        estado **nao ve diferenca nenhuma**; a versao viu, e passou de 2 para 4.

        Com o CAS, a escrita de quem leu a versao 2 e recusada. Sem ele, passa —
        sobre uma encomenda que mudou duas vezes desde que ele a leu, e com a
        decisao dele tomada sobre a reserva antiga.
        """
        versao = self.levar_a(self.tenant, self.encomenda, "aguarda_pagamento")
        self.assertEqual(versao, 2)
        versao = self.transitar(
            self.tenant, self.encomenda, "aguarda_pagamento", "expirada", versao, "ttl"
        )
        versao = self.transitar(
            self.tenant,
            self.encomenda,
            "expirada",
            "aguarda_pagamento",
            versao,
            "nova_referencia",
        )
        self.assertEqual((self.estado_de(self.encomenda)), ("aguarda_pagamento", 4))

        # Com o CAS: quem leu a versao 2 e recusado.
        resultado, relida = _transitar_noutra_ligacao(self.tenant, self.encomenda, 2)
        self.assertEqual(
            (resultado, relida),
            ("conflito", 4),
            "o `version = $3` ve o ciclo que o `estado = $4` nao ve",
        )

        # Sem o CAS: a mesma escrita passa. **E o canario.**
        resultado, _ = _transitar_sem_versao(
            self.tenant, self.encomenda, "aguarda_pagamento", "expirada"
        )
        self.assertEqual(
            resultado,
            "ok",
            "sem o predicado da versao, a escrita de quem leu a versao 2 passa "
            "sobre a versao 4: se este canario deixasse de passar, o ensaio de "
            "cima deixava de medir o que o CAS acrescenta",
        )

    def test_uma_versao_antiga_e_conflito_e_nao_erro(self) -> None:
        """Sem concorrencia nenhuma: quem chega tarde le o estado novo."""
        versao = self.levar_a(self.tenant, self.encomenda, "aguarda_pagamento")
        self.assertEqual(versao, 2)
        resultado, relida = _transitar_noutra_ligacao(self.tenant, self.encomenda, 1)
        self.assertEqual((resultado, relida), ("conflito", 2))
