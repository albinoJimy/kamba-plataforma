"""Criterio 1 do KAM-047: mil tentativas no mesmo recurso e intervalo dao UMA.

«1.000 tentativas concorrentes de reservar/marcar o mesmo recurso e intervalo
produzem **1** marcacao `hold`/`confirmada` e as restantes `SLOT_TAKEN`
(garantido por restricao de exclusao na BD, nao por codigo aplicacional).»

**Mil a serio, em ligacoes concorrentes.** Nao se simula concorrencia com um
laco: o que esta em prova e a serializacao no indice GiST da restricao
`bookings_sem_sobreposicao` — uma transaccao que insere um intervalo sobreposto
**espera** pela que ja o inseriu e, quando essa confirma, recebe `23P01`. Um laco
sequencial dava a mesma marcacao unica e nao provava nada disso: provava que a
segunda insercao ve a primeira, que e trivial.

**Trinta e duas ligacoes, e nao mil.** Mil ligacoes abertas ao mesmo tempo
estouram o `max_connections` por omissao (100) e o que se media passava a ser a
gestao do *pool*. Com 32 ha sempre dezenas de transaccoes a disputar o mesmo
intervalo, que e o que se quer. E a mesma escolha, pela mesma razao, do
`tests_ten` do KAM-009 e do `tests_auditoria_carga` do KAM-012.

## Porque e que nao ha `SELECT` antes do `INSERT`

O criterio diz «garantido por restricao de exclusao na BD, **nao** por codigo
aplicacional», e a letra importa. Esta suite insere directamente e **nao**
pergunta antes se o intervalo esta livre: se o `SQL_CRIAR_HOLD` do modulo
tivesse um `SELECT ... FOR UPDATE` a frente, estes mil ainda davam um — e o
criterio continuava por cumprir, porque o que o garantia era o bloqueio e nao a
restricao.

O teste que distingue as duas coisas e o
`test_sem_a_restricao_as_mil_dariam_mais_do_que_uma`: deixa cair a restricao,
repete uma fracao das tentativas, e afirma que **passam mais do que uma**. E a
prova de que a barreira e aquela e nao outra — o passo de canario desta suite.
"""

from __future__ import annotations

import concurrent.futures
import time

import pg8000.dbapi

import ligacao
from tests.base import ComBase, sqlstate
from tests_servicos.base import ComAgenda, intervalo, prazo_do_hold
from tests_servicos.consultas import (
    SQLSTATE_SOBREPOSICAO,
    SQL_CONFIRMAR_HOLD,
    SQL_CRIAR_HOLD,
    SQL_TRANCAR_RECURSO,
)

#: Os numeros do criterio. Nao sao folga: com cem tentativas a afirmacao era
#: outra, e «1.000 paralelas» com 900 nao esta cumprido.
TENTATIVAS = 1000
LIGACOES = 32

#: A fracao que o passo de canario repete sem a restricao. Chega para provar que
#: passam **mais do que uma** — que e a afirmacao — sem pagar outra vez o custo
#: das mil.
TENTATIVAS_DO_CANARIO = 64

#: O `SQLSTATE_SOBREPOSICAO` e o `SQL_CRIAR_HOLD` vem do **ficheiro do modulo**
#: (`tests_servicos/consultas.py`), nao de uma copia: o que estas mil tentativas
#: exercitam e a insercao que o `holdSlot` envia em producao. Se alguem lhe
#: acrescentar um `SELECT ... FOR UPDATE` a frente, e aqui que se ve.


class TestMilTentativasParalelas(ComAgenda):
    def setUp(self) -> None:
        super().setUp()
        self.tenant, self.servico, self.recurso = self.criar_agenda()
        self.inicio, self.fim = intervalo(60)

    def _tentar(self, n: int) -> tuple[bool, str | None]:
        """Uma tentativa, numa ligacao propria, com `commit`.

        **Cada tentativa tem o seu `contact_id` e o seu `slot_id`**, e isso e
        deliberado: o que se mede e a sobreposicao de **intervalo**, e mil
        tentativas do mesmo contacto com o mesmo slot mediam o indice unico
        `bookings_contacto_slot_uq`, que e outra coisa e tem teste proprio. Aqui
        sao mil clientes diferentes a tentar a mesma hora com o mesmo
        profissional — o caso que o criterio descreve.
        """
        conexao = ligacao.ligar("app")
        try:
            cursor = conexao.cursor()
            cursor.execute(
                "SELECT set_config('app.tenant_id', %s, true)", (self.tenant,)
            )
            cursor.fetchone()
            # A mesma tranca que o `holdSlot` toma, e pela mesma razao: sem ela
            # estas mil nao terminam — 486 `deadlock detected` medidos. Ver a
            # nota do `SQL_TRANCAR_RECURSO`.
            cursor.execute(SQL_TRANCAR_RECURSO, (self.tenant, self.recurso))
            cursor.fetchone()
            cursor.execute(
                SQL_CRIAR_HOLD,
                (
                    self.tenant,
                    f"00000000-0000-4000-8000-{n:012d}",
                    self.servico,
                    self.recurso,
                    f"slot-{n}",
                    self.inicio,
                    self.fim,
                    prazo_do_hold(),
                ),
            )
            cursor.fetchone()
            conexao.commit()
            return True, None
        except pg8000.dbapi.DatabaseError as erro:
            conexao.rollback()
            return False, sqlstate(erro)
        finally:
            conexao.close()

    def _deadlocks(self) -> int:
        self.semente.execute(
            "SELECT deadlocks FROM pg_stat_database WHERE datname = current_database()"
        )
        return int(self.semente.fetchone()[0])

    def test_mil_tentativas_dao_uma_marcacao_e_novecentas_e_noventa_e_nove_slot_taken(
        self,
    ) -> None:
        deadlocks_antes = self._deadlocks()
        comecou = time.monotonic()
        aceites = 0
        estados: dict[str | None, int] = {}
        with concurrent.futures.ThreadPoolExecutor(max_workers=LIGACOES) as piscina:
            tarefas = [piscina.submit(self._tentar, n) for n in range(TENTATIVAS)]
            for tarefa in concurrent.futures.as_completed(tarefas):
                aceite, estado = tarefa.result()
                if aceite:
                    aceites += 1
                else:
                    estados[estado] = estados.get(estado, 0) + 1
        segundos = time.monotonic() - comecou
        # O numero fica na saida do gate, como o p95 da carga de eventos: e o que
        # permite dizer no bloco do ticket quanto custou, em vez de o estimar.
        print(
            f"\nconcorrencia SERVICOS: {TENTATIVAS} tentativas no mesmo recurso e "
            f"intervalo, {LIGACOES} ligacoes, {segundos:.1f}s"
        )

        self.assertEqual(aceites, 1, "o criterio pede exactamente uma marcacao")
        self.assertEqual(
            estados,
            {SQLSTATE_SOBREPOSICAO: TENTATIVAS - 1},
            "as restantes tem de ser todas SLOT_TAKEN (23P01) e nao outro erro: "
            "uma falha por chave estrangeira ou por privilegio contava como "
            "«recusada» e deixava o criterio por provar",
        )
        # E na base, nao so nas respostas: uma marcacao activa, e nada mais.
        self.assertEqual(self.contar(self.tenant, "hold", "confirmada"), 1)
        self.assertEqual(len(self.marcacoes(self.tenant)), 1)

        # **Zero `deadlock detected`**, e esta asercao e a que paga o
        # `SQL_TRANCAR_RECURSO`. Sem a tranca, a mesma prova mediu **486**
        # *deadlocks* (a um por segundo, o `deadlock_timeout` por omissao) e nao
        # progrediu: a verificacao de uma restricao de exclusao espera pela
        # transaccao com que conflitua, e com trinta e duas insercoes da mesma
        # chave cada uma pode encontrar um conflito diferente — fechando um
        # ciclo de espera. Sem esta linha, uma remocao da tranca voltava a
        # pendurar o gate e a razao perdia-se.
        self.assertEqual(
            self._deadlocks() - deadlocks_antes,
            0,
            "um deadlock aqui significa que a tranca por recurso deixou de "
            "serializar as tentativas: as perdedoras voltam com 40P01 em vez de "
            "23P01, e «as restantes SLOT_TAKEN» passa a ser falso",
        )

    def test_sem_a_restricao_as_mil_dariam_mais_do_que_uma(self) -> None:
        """O passo de canario: prova que a barreira e a restricao e nao o codigo.

        Sem este teste, o de cima passava igual se o que impedisse a sobreposicao
        fosse um bloqueio no codigo da suite — e o criterio diz por extenso
        «nao por codigo aplicacional». Deixa-se cair a restricao, repete-se uma
        fracao das tentativas, e afirma-se que passam **mais do que uma**.

        A restricao volta no fim, pela mesma ligacao de administrador. **E isto
        nao e DDL de conveniencia numa limpeza**, que e um defeito que este
        repositorio ja pagou: a tabela fica com a restricao reposta e ha uma
        asercao a confirma-lo, pelo que nada do que corra depois mede um esquema
        reparado as escondidas. Se a reposicao falhar, o teste falha — e nao
        passa a esconder a falha nos seguintes.
        """
        self.semente.execute(
            "ALTER TABLE servicos.bookings DROP CONSTRAINT bookings_sem_sobreposicao"
        )
        try:
            aceites = 0
            with concurrent.futures.ThreadPoolExecutor(max_workers=LIGACOES) as piscina:
                tarefas = [
                    piscina.submit(self._tentar, 100000 + n)
                    for n in range(TENTATIVAS_DO_CANARIO)
                ]
                for tarefa in concurrent.futures.as_completed(tarefas):
                    if tarefa.result()[0]:
                        aceites += 1
            self.assertGreater(
                aceites,
                1,
                "sem a restricao de exclusao, varias tentativas tinham de passar; "
                "se so uma passou, alguma outra coisa esta a impedir a "
                "sobreposicao e o criterio 1 nao esta provado pela restricao",
            )
        finally:
            self.semente.execute(
                "DELETE FROM servicos.bookings WHERE tenant_id = %s", (self.tenant,)
            )
            self.semente.execute(
                "ALTER TABLE servicos.bookings ADD CONSTRAINT "
                "bookings_sem_sobreposicao EXCLUDE USING gist "
                "(tenant_id WITH =, resource_id WITH =, "
                " tstzrange(inicio_at, fim_at) WITH &&) "
                "WHERE (estado IN ('hold', 'confirmada'))"
            )
        self.semente.execute(
            "SELECT count(*) FROM pg_constraint WHERE contype = 'x' "
            " AND conname = 'bookings_sem_sobreposicao' "
            " AND connamespace = 'servicos'::regnamespace"
        )
        self.assertEqual(
            int(self.semente.fetchone()[0]),
            1,
            "a restricao tem de voltar: sem ela, tudo o que corra a seguir mede "
            "um esquema sem a barreira do criterio 1",
        )


class TestCinquentaConfirmacoesDoMesmoHold(ComAgenda):
    """Criterio 4: 50 confirmacoes concorrentes produzem 1 marcacao confirmada.

    O que serializa aqui nao e o indice GiST: e o bloqueio da **linha**. O
    `UPDATE ... WHERE hold_id = $1 AND estado = 'hold'` do modulo e o que faz
    com que a primeira das cinquenta altere a linha e as outras quarenta e nove
    nao encontrem nada para alterar — devolvem zero linhas, e quem chama vai ler
    o estado actual e devolve a **mesma** marcacao.

    A afirmacao e dupla, e a segunda metade e a que importa: uma alteracao, e a
    `version` a **dois** e nao a cinquenta e um. Se as cinquenta tivessem
    alterado a linha, o estado final era o mesmo (`confirmada`) e a contagem de
    marcacoes tambem — e so a `version` denunciava que a idempotencia nao era da
    base.
    """

    CONFIRMACOES = 50

    def setUp(self) -> None:
        super().setUp()
        self.tenant, self.servico, self.recurso = self.criar_agenda()
        self.contacto = "11111111-1111-4111-8111-111111111111"
        inicio, fim = intervalo(90)
        self.semente.execute(
            "INSERT INTO servicos.bookings "
            "(tenant_id, contact_id, service_id, resource_id, slot_id, "
            " inicio_at, fim_at, estado, hold_expires_at) "
            "VALUES (%s, %s, %s, %s, 'slot-unico', %s, %s, "
            "        'hold', now() + interval '10 minutes') "
            "RETURNING hold_id",
            (self.tenant, self.contacto, self.servico, self.recurso, inicio, fim),
        )
        self.hold = str(self.semente.fetchone()[0])

    def _confirmar(self) -> bool:
        conexao = ligacao.ligar("app")
        try:
            cursor = conexao.cursor()
            cursor.execute(
                "SELECT set_config('app.tenant_id', %s, true)", (self.tenant,)
            )
            cursor.fetchone()
            cursor.execute(SQL_CONFIRMAR_HOLD, (self.hold, self.contacto))
            alterou = cursor.fetchone() is not None
            conexao.commit()
            return alterou
        finally:
            conexao.close()

    def test_cinquenta_confirmacoes_alteram_uma_vez(self) -> None:
        alteracoes = 0
        with concurrent.futures.ThreadPoolExecutor(max_workers=16) as piscina:
            tarefas = [piscina.submit(self._confirmar) for _ in range(self.CONFIRMACOES)]
            for tarefa in concurrent.futures.as_completed(tarefas):
                if tarefa.result():
                    alteracoes += 1

        self.assertEqual(alteracoes, 1, "so uma das cinquenta pode alterar a linha")
        self.semente.execute(
            "SELECT estado, version, hold_expires_at FROM servicos.bookings "
            " WHERE hold_id = %s",
            (self.hold,),
        )
        estado, versao, prazo = self.semente.fetchone()
        self.assertEqual(str(estado), "confirmada")
        self.assertEqual(
            int(versao),
            2,
            "a version a mais do que dois significa que mais de uma chamada "
            "alterou a linha: a idempotencia nao era da base",
        )
        self.assertIsNone(
            prazo,
            "uma marcacao confirmada nao tem prazo de hold "
            "(bookings_hold_prazo_ck)",
        )
        self.assertEqual(self.contar(self.tenant, "confirmada"), 1)


class TestOTrincoDaSuite(ComBase):
    """A suite nao corre contra uma base que nao seja a do gate."""

    def test_a_base_e_a_do_gate(self) -> None:
        linhas = self.consultar("SELECT current_database()")
        self.assertTrue(
            str(linhas[0][0]).endswith("_gate8"),
            "esta suite faz DDL e apaga linhas: so corre contra a base do gate",
        )
