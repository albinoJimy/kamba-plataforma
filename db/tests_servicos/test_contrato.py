"""O contrato entre o modulo TypeScript e a base: todas as consultas correm.

**Este ficheiro existe porque a revisao adversarial mostrou que faltava.** O
`db/tests_servicos/base.py` justificava o desenho da suite com um teste que nao
existia, e a tupla `EXERCITADAS` de `consultas.py` era codigo morto — nada
confrontava a lista de consultas do modulo com as que a suite corre. A
consequencia foi medida: o `SQL_GRELHA` tinha um defeito real (`generate_series`
sobre instantes perde um dia) e **nenhuma** bateria o tocava, porque a suite
nunca o corria com um intervalo de utilizador.

O que aqui se prova nao e comportamento: e que **cada cadeia de SQL do modulo
corre contra o PostgreSQL verdadeiro**. Uma base falsa compara-as por texto e
nunca as interpreta, pelo que um erro de sintaxe, um `::uuid` sobre uma coluna
`text` ou uma coluna que deixou de existir passam o *gate* 4 inteiro e falham na
primeira marcacao real. E a mesma razao que o KAM-115 escreveu para as onze
cadeias do `avisos/consultas.ts`.

## Tres propriedades, e nenhuma e redundante

- **Cobertura:** o conjunto de constantes `SQL_*` do ficheiro TypeScript e
  **exactamente** o `EXERCITADAS`. Uma consulta nova que ninguem acrescente aqui
  falha — e e assim que a lista deixa de apodrecer.
- **Execucao:** cada uma corre, com argumentos do tipo certo, contra o esquema
  real. As de escrita correm dentro de uma transaccao que se desfaz.
- **Ordem dos parametros:** o `exigir()` de `consultas.py` ja recusa um `$n` fora
  de ordem crescente; aqui prova-se que ele foi chamado para todas.
"""

from __future__ import annotations

import datetime

from tests_servicos import consultas
from tests_servicos.base import ComAgenda, intervalo, prazo_do_hold

#: O contacto de ensaio. Qualquer UUID serve: a `bookings.contact_id` nao tem
#: chave estrangeira, por desenho (ver a revisao `0025`).
CONTACTO = "11111111-1111-4111-8111-111111111111"


class TestOContratoComOModulo(ComAgenda):
    def setUp(self) -> None:
        super().setUp()
        self.tenant, self.servico, self.recurso = self.criar_agenda()
        self.inicio, self.fim = intervalo(60)

    def test_a_lista_de_exercitadas_e_a_do_modulo(self) -> None:
        """Uma consulta nova no modulo tem de entrar nesta suite.

        Sem isto, o `EXERCITADAS` era uma lista escrita a mao que envelhecia em
        silencio — «uma lista literal transforma uma invariante num numero», que
        e a licao que o `metricas.py` do KAM-027 ja pagou.
        """
        no_modulo = {
            nome for nome in consultas.CONSTANTES if nome.startswith("SQL_")
        }
        self.assertEqual(
            no_modulo,
            set(consultas.EXERCITADAS),
            "o conjunto de consultas do modulo mudou: acrescenta a nova ao "
            "EXERCITADAS de db/tests_servicos/consultas.py e corre-a no "
            "test_cada_consulta_do_modulo_corre_contra_a_base",
        )

    def test_cada_consulta_do_modulo_corre_contra_a_base(self) -> None:
        """As doze cadeias, com argumentos reais, numa transaccao que se desfaz.

        A ordem nao e arbitraria: as de escrita vem depois das de leitura, e o
        `SQL_CRIAR_HOLD` antes do `SQL_CONFIRMAR_HOLD`, porque a segunda precisa
        da linha que a primeira cria. O que se mede e que **todas correm**; o que
        elas fazem tem teste proprio nos outros ficheiros desta suite.
        """
        agora = datetime.datetime.now(datetime.timezone.utc)
        ate = agora + datetime.timedelta(days=14)
        cursor = self.cursor_app(self.tenant)

        corridas: list[str] = []

        def correr(nome: str, parametros: tuple) -> list:
            sql = getattr(consultas, nome)
            cursor.execute(sql, parametros)
            corridas.append(nome)
            # Nem todas devolvem linhas; o que importa e que a base as aceite.
            try:
                return list(cursor.fetchall())
            except Exception:  # noqa: BLE001 — uma instrucao sem resultado
                return []

        # ------------------------------------------------------- leituras
        correr("SQL_LISTAR_SERVICOS", ())
        correr("SQL_SERVICO", (self.servico,))
        correr("SQL_GRELHA", (agora, ate))
        correr("SQL_OCUPADO", (agora, ate))
        correr("SQL_SLOT_OFERECIVEL", (self.servico, self.recurso, self.inicio, self.fim))
        correr("SQL_TRANCAR_RECURSO", (self.tenant, self.recurso))

        # -------------------------------------------------------- escritas
        criada = correr(
            "SQL_CRIAR_HOLD",
            (
                self.tenant,
                CONTACTO,
                self.servico,
                self.recurso,
                "slot-de-contrato",
                self.inicio,
                self.fim,
                prazo_do_hold(),
            ),
        )
        self.assertEqual(len(criada), 1)
        colunas = [d[0] for d in cursor.description]
        marcacao = dict(zip(colunas, criada[0]))
        booking = str(marcacao["booking_id"])
        hold = str(marcacao["hold_id"])

        correr("SQL_MARCACAO_DO_SLOT", (CONTACTO, "slot-de-contrato"))
        correr("SQL_MARCACAO_POR_HOLD", (hold,))
        correr("SQL_MARCACAO", (booking,))
        confirmada = correr("SQL_CONFIRMAR_HOLD", (hold, CONTACTO))
        self.assertEqual(len(confirmada), 1, "o hold de ensaio tem de confirmar")

        # A remarcacao cria uma segunda linha, noutro intervalo.
        novo_inicio, novo_fim = intervalo(300)
        correr(
            "SQL_REMARCAR",
            (
                self.tenant,
                CONTACTO,
                self.servico,
                self.recurso,
                "slot-de-contrato-2",
                novo_inicio,
                novo_fim,
                "hold",
                prazo_do_hold(),
            ),
        )
        correr("SQL_CANCELAR", (booking, CONTACTO))
        correr("SQL_EXPIRAR_HOLDS", (10,))
        correr(
            "SQL_EMITIR_BOOKING_CREATED",
            (
                "booking.created",
                1,
                self.tenant,
                "booking",
                booking,
                (
                    '{"booking_id": "%s", "contact_id": "%s", "service_id": "%s", '
                    '"resource_id": "%s", "inicio_at": "%s", "fim_at": "%s"}'
                )
                % (
                    booking,
                    CONTACTO,
                    self.servico,
                    self.recurso,
                    self.inicio.isoformat(),
                    self.fim.isoformat(),
                ),
                "P1",
                ["transacao"],
            ),
        )

        # **Desfaz-se tudo**: este teste mede que as consultas correm, e deixar
        # linhas atras mudava o que os outros medem.
        cursor.connection.rollback()

        self.assertEqual(
            set(corridas),
            set(consultas.EXERCITADAS),
            "ficaram consultas do modulo por correr contra a base",
        )

    def test_o_slot_oferecivel_recusa_o_que_a_agenda_ja_nao_tem(self) -> None:
        """A terceira barreira do `holdSlot`, medida nos quatro casos.

        A assinatura do `slot_id` prova que o backend ofereceu o *slot*; nao
        prova que ainda o ofereceria. Estes quatro sao os caminhos pelos quais um
        *slot* legitimamente assinado deixa de ser oferecivel entre a lista e o
        botao — e sem esta consulta a marcacao entrava em todos.
        """
        # Sem regra de disponibilidade nenhuma, nada e oferecivel.
        cursor = self.cursor_app(self.tenant)
        cursor.execute(
            consultas.SQL_SLOT_OFERECIVEL,
            (self.servico, self.recurso, self.inicio, self.fim),
        )
        self.assertFalse(cursor.fetchone()[0], "sem grelha nao ha slot")
        cursor.connection.rollback()

        # Com uma regra que cubra o intervalo, passa a ser.
        dia = self.inicio.astimezone(datetime.timezone.utc)
        self.semente.execute(
            "INSERT INTO servicos.availability_rules "
            "(tenant_id, resource_id, dia_semana, inicio, fim, fuso) "
            "VALUES (%s, %s, EXTRACT(dow FROM %s::timestamptz AT TIME ZONE 'UTC')::smallint, "
            "        '00:00', '23:59', 'UTC')",
            (self.tenant, self.recurso, dia),
        )
        cursor = self.cursor_app(self.tenant)
        cursor.execute(
            consultas.SQL_SLOT_OFERECIVEL,
            (self.servico, self.recurso, self.inicio, self.fim),
        )
        self.assertTrue(cursor.fetchone()[0], "com grelha, o slot e oferecivel")
        cursor.connection.rollback()

        # Serviço desactivado: deixa de ser.
        self.semente.execute(
            "UPDATE servicos.services SET ativo = false WHERE service_id = %s",
            (self.servico,),
        )
        cursor = self.cursor_app(self.tenant)
        cursor.execute(
            consultas.SQL_SLOT_OFERECIVEL,
            (self.servico, self.recurso, self.inicio, self.fim),
        )
        self.assertFalse(cursor.fetchone()[0], "um servico desactivado nao se marca")
        cursor.connection.rollback()
        self.semente.execute(
            "UPDATE servicos.services SET ativo = true WHERE service_id = %s",
            (self.servico,),
        )

        # Recurso desactivado: idem.
        self.semente.execute(
            "UPDATE servicos.resources SET ativo = false WHERE resource_id = %s",
            (self.recurso,),
        )
        cursor = self.cursor_app(self.tenant)
        cursor.execute(
            consultas.SQL_SLOT_OFERECIVEL,
            (self.servico, self.recurso, self.inicio, self.fim),
        )
        self.assertFalse(cursor.fetchone()[0], "um recurso desactivado nao executa")
        cursor.connection.rollback()
        self.semente.execute(
            "UPDATE servicos.resources SET ativo = true WHERE resource_id = %s",
            (self.recurso,),
        )

        # Duracao que nao casa com a do servico: idem. E o caso que impede um
        # token de um servico de 30 min marcar 30 min de um servico que
        # entretanto passou a 60.
        cursor = self.cursor_app(self.tenant)
        cursor.execute(
            consultas.SQL_SLOT_OFERECIVEL,
            (
                self.servico,
                self.recurso,
                self.inicio,
                self.inicio + datetime.timedelta(minutes=45),
            ),
        )
        self.assertFalse(cursor.fetchone()[0], "a duracao tem de ser a do servico")
        cursor.connection.rollback()

    def test_a_grelha_nao_perde_um_dia_numa_janela_curta(self) -> None:
        """O defeito do `generate_series`, medido.

        `generate_series('02T20:00', '03T12:00', interval '1 day')` devolve
        **um** valor, porque o passo seguinte cai depois do fim: uma janela que
        atravesse a meia-noite sem chegar a 24 h perdia o segundo dia, e um
        cliente que pedisse «de hoje a noite ate amanha ao almoco» recebia lista
        vazia com o recurso aberto. Com o `::date` antes da serie, entram os
        dois.

        **Nenhum teste tocava nesta consulta** antes da revisao adversarial: a
        suite nunca a corria com um intervalo de utilizador. E por isso que o
        `test_a_lista_de_exercitadas_e_a_do_modulo` existe.
        """
        self.semente.execute(
            "INSERT INTO servicos.availability_rules "
            "(tenant_id, resource_id, dia_semana, inicio, fim, fuso) "
            "SELECT %s, %s, d, '09:00', '17:00', 'UTC' FROM generate_series(0, 6) AS d",
            (self.tenant, self.recurso),
        )
        de = datetime.datetime.now(datetime.timezone.utc).replace(
            hour=20, minute=0, second=0, microsecond=0
        )
        ate = de + datetime.timedelta(hours=16)

        cursor = self.cursor_app(self.tenant)
        cursor.execute(consultas.SQL_GRELHA, (de, ate))
        janelas = list(cursor.fetchall())
        cursor.connection.rollback()

        dias = {linha[1].date() for linha in janelas}
        self.assertEqual(
            len(dias),
            2,
            "a janela atravessa a meia-noite: os dois dias tem de entrar na "
            f"grelha (entraram {sorted(dias)})",
        )
