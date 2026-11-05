"""Expiracao, idempotencia e prolongamento das reservas (KAM-045, 3 a 7).

O que so aqui se prova, e nenhum duplo de teste pode:

```text
criterio 3   o `charge.issued` fixa o prazo **uma vez**, e a segunda entrega nao faz nada
criterio 4   dois varredores veem conjuntos DISJUNTOS (`FOR UPDATE SKIP LOCKED`)
criterio 4   libertar duas vezes devolve stock uma vez, e o CAS recusa a versao velha
criterio 6   consumir e libertar sao terminais, e a base recusa quem os forcar
criterio 7   o tecto de 72 h mede-se contra o `criado_at` e nao contra `now()`
DoD 5        as reservas activas por tenant e o atraso de cada libertacao
```

O `SKIP LOCKED` e a razao desta suite existir em vez de a decisao viver toda em
funcoes puras: duas transaccoes a trancar a mesma tabela nao se simulam com um
laco, e o que os *Testes Requeridos* do bloco pedem — «dois *workers* a varrer em
simultaneo» — e precisamente a propriedade que so um PostgreSQL tem.

## As doze consultas do modulo correm todas aqui ou no `test_reservas.py`

E a regra que o `db/tests_produtos/consultas.py` escreve e que esta suite
herda: «uma consulta do modulo que ninguem exercite entra sem ser provada, e um
nome nesta lista que o modulo nao tenha e uma declaracao morta». O
`TestCoberturaDasReservas`, no fim deste ficheiro, confronta as duas listas nos
**dois sentidos** — e foi a escrever este ficheiro que a primeira versao do
`EXERCITADAS_DAS_RESERVAS` se mostrou mortalmente optimista: declarava doze e a
suite corria **uma**.
"""

from __future__ import annotations

import concurrent.futures
import re
import threading

import ligacao
from tests_encomendas.consultas import (
    EXERCITADAS_DAS_RESERVAS,
    SQL_ACTIVAS_POR_TENANT,
    SQL_ATRASO_DA_LIBERTACAO,
    SQL_CONFIRMAR,
    SQL_CONSUMIR,
    SQL_DEVOLVER_STOCK,
    SQL_ESTENDER,
    SQL_LER_OFERTA,
    SQL_LER_RESERVAS,
    SQL_LIBERTAR,
    SQL_LIBERTAR_UMA,
    SQL_VENCIDAS,
)
from tests_encomendas.test_reservas import (
    ESTADO_TERMINAL,
    STOCK,
    VERSAO_NAO_SUBIU,
    ComReservas,
)

#: O tecto do criterio 7 **com a folga do criterio 2**, na forma que o
#: `SQL_ESTENDER` e o `SQL_CONFIRMAR` recebem por `$4`.
#:
#: E o **mesmo** nos dois, e e o que o `tectoComoIntervalo` do modulo produz:
#: 72 h + 15 min = 4335 min. Eram numeros diferentes, e a revisao adversarial
#: mediu o efeito: com `72 hours` secas no `SQL_ESTENDER`, uma reserva criada
#: com TTL de 72 h tinha `expira_at = criado_at + 72 h 15 min`, isto e, **acima**
#: do proprio tecto — e nunca se podia prolongar.
#:
#: **Em minutos e numa unidade so**, pela razao daquela funcao: uma unidade nao
#: tem como ser lida por metades.
TECTO = "4335 minutes"

#: Quantos varredores disputam no ensaio do `SKIP LOCKED`.
VARREDORES = 2

#: Quantas reservas vencidas o ensaio do `SKIP LOCKED` semeia. Par, para que a
#: reparticao entre dois varredores seja verificavel sem arredondar.
VENCIDAS = 6

#: Segundos que uma barreira espera antes de desistir. Ver a nota no ensaio dos
#: dois varredores: sem prazo, um varredor que falhe pendura o outro, e a suite
#: **para** em vez de falhar. Generoso — o que ele corta e a espera infinita,
#: nao uma corrida lenta.
PRAZO_DA_BARREIRA = 60


class ComUmaReserva(ComReservas):
    """Um tenant com oferta, encomenda e reservas semeadas."""

    def setUp(self) -> None:
        super().setUp()
        self.tenant = self.criar_tenant()
        self.sku = self.criar_oferta(self.tenant)
        self.encomenda = self.criar_encomenda(self.tenant)

    def criar_reserva(
        self,
        *,
        encomenda: str | None = None,
        linha: int = 0,
        qty: int = 1,
        vencida: bool = False,
        confirmada: bool = True,
        sku: str | None = None,
    ) -> str:
        """Insere uma reserva e **move o contador** da oferta, como o modulo faz.

        O contador move-se a mao e nao pelo `SQL_RESERVAR`: o que estes ensaios
        medem e a libertacao e o prolongamento, e semear pelo caminho da reserva
        fazia cada caso depender do predicado aritmetico que o
        `test_reservas.py` ja mede. O que **nao** se faz e deixar o contador
        quieto — uma reserva sem o contador a condizer era uma base em estado
        impossivel, e os ensaios da devolucao mediam a aritmetica errada.
        """
        alvo = self.encomenda if encomenda is None else encomenda
        esse_sku = self.sku if sku is None else sku
        prazo = (
            "now() - interval '1 minute'" if vencida else "now() + interval '48 hours'"
        )
        confirmacao = "now()" if confirmada else "NULL"
        self.semente.execute(
            "INSERT INTO platform.stock_reservations "
            "       (tenant_id, order_id, line_no, sku, qty, expira_at, "
            "        confirmada_at) "
            f"VALUES (%s, %s, %s, %s, %s, {prazo}, {confirmacao}) RETURNING id",
            (self.tenant, alvo, linha, esse_sku, qty),
        )
        reserva = str(self.semente.fetchone()[0])
        self.semente.execute(
            "UPDATE platform.offer_terms SET stock_reservada = stock_reservada + %s "
            " WHERE tenant_id = %s AND sku = %s",
            (qty, self.tenant, esse_sku),
        )
        return reserva

    def instante_da_reserva(self, reserva: str, intervalo: str) -> str:
        """`criado_at + <intervalo>` da reserva, em texto ISO.

        **Medido contra o `criado_at` da reserva e nao contra `now()`**, que e o
        ponto do criterio 7: o tecto de 72 h e sobre a vida da reserva, pelo que
        um ensaio que somasse ao relogio media outra coisa — e passava, porque
        `now() + 60 h` tambem cabe em `criado_at + 72 h` quando a reserva
        acabou de nascer. Com o `criado_at`, o caso das 73 h e mesmo o caso que
        excede.
        """
        self.semente.execute(
            f"SELECT (criado_at + interval '{intervalo}')::text "
            "  FROM platform.stock_reservations WHERE id = %s",
            (reserva,),
        )
        return str(self.semente.fetchone()[0])

    def instante_como_data(self, reserva: str, intervalo: str):
        """O mesmo que o `instante_da_reserva`, como `datetime` e nao texto.

        Serve as comparacoes com o que a base devolve: o `pg8000` devolve um
        `datetime` e comparar com a forma textual dava falso por formatacao, nao
        por valor.
        """
        self.semente.execute(
            f"SELECT criado_at + interval '{intervalo}' "
            "  FROM platform.stock_reservations WHERE id = %s",
            (reserva,),
        )
        return self.semente.fetchone()[0]

    def estado_da_reserva(self, reserva: str) -> tuple[str, str | None, int]:
        self.semente.execute(
            "SELECT estado, motivo, version FROM platform.stock_reservations "
            " WHERE id = %s",
            (reserva,),
        )
        estado, motivo, versao = self.semente.fetchone()
        return str(estado), (None if motivo is None else str(motivo)), int(versao)

    def no_app(self, consulta, *argumentos):
        """Corre uma consulta como `kamba_app`, com contexto, e **confirma**.

        ## O `commit` nao e arrumacao: sem ele a suite **pendura**

        Medido nesta sessao, e custou uma corrida do *gate* 8 morta a meio. A
        primeira versao destes ensaios fazia `_, cursor = self.ligar_app(...)`,
        escrevia pelo cursor e **nunca confirmava** — a ligacao ficava com a
        tranca da linha. O passo seguinte do mesmo ensaio lia ou escrevia a
        mesma linha pela ligacao de administrador, e o PostgreSQL fazia o que
        tem de fazer: **esperava**. Sem `statement_timeout`, para sempre.

        O sintoma e o pior possivel — a suite nao falha, **para** —, e um ensaio
        pendurado nao diz qual e a linha trancada. Por isso a escrita e a
        confirmacao ficam no mesmo auxiliar, onde nao ha como esquecer uma.

        O contexto vai por `set_config(..., true)`, que e **local a
        transaccao**: depois do `commit` ele desaparece, e e por isso que cada
        chamada abre a sua ligacao em vez de reutilizar uma.
        """
        conexao, cursor = self.ligar_app(self.tenant)
        cursor.execute(consulta.sql, consulta.args(*argumentos))
        # **`list(...)` e nao o que o `fetchall` devolver**, e nao e arrumacao:
        # o `pg8000` devolve uma **tupla vazia** quando nao ha linhas e uma
        # lista quando ha, pelo que `assertEqual(resultado, [])` falhava com
        # `() != []` — sete ensaios desta suite, todos a medir a coisa certa e a
        # falhar na forma do recipiente. Normaliza-se aqui, uma vez.
        linhas = list(cursor.fetchall())
        conexao.commit()
        return linhas

    def no_batch(self, consulta, *argumentos):
        """Corre uma consulta sem filtro de tenant, como o *job* faz.

        O `kamba_batch` tem `BYPASSRLS` por atributo, e e por isso que o
        varrimento ve a base toda. Pelo `kamba_app` o `SQL_VENCIDAS` devolvia
        **as linhas do tenant do contexto** — e sem contexto, zero: um ensaio do
        varrimento que corresse como a aplicacao ficava verde a ler nada.
        """
        conexao = ligacao.ligar("batch")
        try:
            cursor = conexao.cursor()
            cursor.execute(consulta.sql, consulta.args(*argumentos))
            # `list(...)` pela razao do `no_app`: o `pg8000` devolve tupla vazia.
            linhas = list(cursor.fetchall())
            conexao.commit()
            return linhas
        finally:
            conexao.close()


class TestOChargeIssuedFixaOPrazo(ComUmaReserva):
    """Criterio 3: o `charge.issued` fixa o `expira_at`, e **uma vez**."""

    def test_o_charge_issued_fixa_o_prazo_das_provisorias(self) -> None:
        reserva = self.criar_reserva(confirmada=False)
        self.semente.execute(
            "SELECT confirmada_at FROM platform.stock_reservations WHERE id = %s",
            (reserva,),
        )
        self.assertIsNone(self.semente.fetchone()[0], "nasce provisoria")

        # **Relativo ao `criado_at` e nao uma data fixa.** Uma data fixa a ~72 h
        # de distancia fica dentro ou fora do tecto conforme a hora a que a
        # suite corre — e um ensaio que muda de resultado com o relogio da
        # maquina nao mede nada de forma repetivel.
        prazo_pedido = self.instante_da_reserva(reserva, "40 hours")
        linhas = self.no_app(
            SQL_CONFIRMAR, self.tenant, self.encomenda, prazo_pedido, TECTO
        )
        self.assertEqual(len(linhas), 1, "fixou o prazo de uma reserva")

        self.semente.execute(
            "SELECT confirmada_at, expira_at FROM platform.stock_reservations "
            " WHERE id = %s",
            (reserva,),
        )
        confirmada, prazo = self.semente.fetchone()
        self.assertIsNotNone(confirmada, "deixou de ser provisoria")
        self.assertEqual(
            prazo,
            self.instante_como_data(reserva, "40 hours"),
            "e o prazo e exactamente o que o evento pediu",
        )

    def test_a_segunda_entrega_do_mesmo_evento_nao_estende_outra_vez(self) -> None:
        """A idempotencia do `confirmada_at IS NULL`, e porque ela importa.

        O EVT entrega «pelo menos uma vez», pelo que o mesmo `charge.issued`
        chega duas vezes com normalidade. Sem o predicado, cada entrega estendia
        o prazo outra vez — e uma reserva de 48 h entregue tres vezes durava
        144 h, **acima do tecto de 72 h do criterio 7**, por um caminho que nao
        passa pelo `extendReservation`.
        """
        reserva = self.criar_reserva(confirmada=False)
        # **As duas datas cabem no tecto, e isso e deliberado.** A primeira
        # versao deste caso punha a segunda em `2026-11-30`, muito acima de
        # `criado_at + 72 h 15 min` — e entao a segunda entrega era recusada por
        # **duas** razoes (o `confirmada_at` e o tecto), pelo que o ensaio
        # deixava de isolar a que diz medir. E a mesma armadilha que a revisao
        # adversarial apanhou no CAS: uma asercao que passa por duas razoes nao
        # prova nenhuma delas.
        primeira = self.instante_da_reserva(reserva, "40 hours")
        segunda = self.instante_da_reserva(reserva, "70 hours")
        self.assertEqual(
            len(
                self.no_app(
                    SQL_CONFIRMAR, self.tenant, self.encomenda, primeira, TECTO
                )
            ),
            1,
        )
        self.assertEqual(
            self.no_app(SQL_CONFIRMAR, self.tenant, self.encomenda, segunda, TECTO),
            [],
            "a segunda entrega casa zero linhas, e **so** pelo "
            "`confirmada_at IS NULL`: as 70 h cabem no tecto, pelo que nao ha "
            "outra condicao a recusa-la",
        )
        self.semente.execute(
            "SELECT expira_at FROM platform.stock_reservations "
            " WHERE tenant_id = %s AND order_id = %s",
            (self.tenant, self.encomenda),
        )
        self.assertEqual(
            self.semente.fetchone()[0],
            self.instante_como_data(reserva, "40 hours"),
            "o prazo e o da primeira entrega, nao o da segunda",
        )


class TestOTectoDeSetentaEDuasHoras(ComUmaReserva):
    """Criterio 7: o tecto nao se contorna, e os dois predicados concordam."""

    def test_um_charge_issued_tardio_nao_da_setenta_e_duas_horas_novas(self) -> None:
        """**O buraco que a revisao adversarial encontrou**, agora fechado.

        O `confirmada_at IS NULL` fecha a entrega **repetida** e nao fecha a
        **primeira entrega tardia**: sem agendador (KAM-071) uma reserva
        provisoria fica `ativa` indefinidamente, e um `charge.issued` que
        chegasse `T` horas depois dava-lhe 72 h **a contar de entao** — vida
        total `T + 72 h + 15 min`.

        O `prazoDoEvento` do modulo nao o podia fechar: ele ancora o tecto em
        `agora`, porque o `criado_at` da reserva esta na base e nao no evento.
        Por isso o tecto e do predicado, e e este ensaio que o mede: um prazo
        acima de `criado_at + 72 h 15 min` casa **zero linhas**.
        """
        reserva = self.criar_reserva(vencida=True, confirmada=False)
        fora = self.instante_da_reserva(reserva, "80 hours")
        self.assertEqual(
            self.no_app(SQL_CONFIRMAR, self.tenant, self.encomenda, fora, TECTO),
            [],
            "80 h a contar do `criado_at` nao cabe no tecto, e o `charge.issued` "
            "tardio nao o contorna",
        )
        self.semente.execute(
            "SELECT confirmada_at FROM platform.stock_reservations WHERE id = %s",
            (reserva,),
        )
        self.assertIsNone(
            self.semente.fetchone()[0],
            "e nao marcou a confirmacao: um prazo recusado nao e meia "
            "confirmacao",
        )

        dentro = self.instante_da_reserva(reserva, "70 hours")
        self.assertEqual(
            len(self.no_app(SQL_CONFIRMAR, self.tenant, self.encomenda, dentro, TECTO)),
            1,
            "70 h cabe, que e a prova no outro sentido",
        )

    def test_os_dois_tectos_concordam_na_folga_de_quinze_minutos(self) -> None:
        """**Os dois predicados usavam numeros diferentes**, e isso tinha efeito.

        O `SQL_ESTENDER` exigia `criado_at + '72 hours'` secas e o caminho de
        criacao escreve `fim_validade + 15 min`, isto e, ate
        `criado_at + 72 h 15 min`. Consequencia medida pela revisao adversarial:
        uma reserva criada com TTL de 72 h tinha `expira_at` **acima** do
        proprio tecto, pelo que `$3 > expira_at` e `$3 <= criado_at + 72 h`
        eram incompativeis e ela **nunca** se podia prolongar.

        Com o tecto a incluir a folga (o `tectoComoIntervalo` do modulo), os
        dois lados falam do mesmo numero. Este ensaio mede o caso exacto em que
        eles discordavam.
        """
        reserva = self.criar_reserva()
        # O prazo que a criacao escreveria para um TTL de 72 h.
        no_limite = self.instante_da_reserva(reserva, "72 hours 15 minutes")
        self.semente.execute(
            "UPDATE platform.stock_reservations "
            "   SET expira_at = criado_at + interval '48 hours' WHERE id = %s",
            (reserva,),
        )
        self.assertEqual(
            len(
                self.no_app(
                    SQL_ESTENDER, self.tenant, self.encomenda, no_limite, TECTO
                )
            ),
            1,
            "o instante que a criacao escreveria para 72 h **cabe** no tecto do "
            "prolongamento: com `72 hours` secas, nao cabia",
        )


class TestOVarrimento(ComUmaReserva):
    """Criterio 4: o `FOR UPDATE SKIP LOCKED` reparte em vez de serializar."""

    def test_o_varrimento_ve_so_as_vencidas_e_so_as_activas(self) -> None:
        vencida = self.criar_reserva(linha=0, vencida=True)
        self.criar_reserva(linha=1, vencida=False)
        linhas = self.no_batch(SQL_VENCIDAS, "2026-12-01T00:00:00+00:00", 100)
        ids = {str(l[0]) for l in linhas}
        self.assertIn(vencida, ids)

        # Uma libertada deixa de ser vista, e e o indice parcial a dizer o
        # mesmo que o predicado: `WHERE estado = 'ativa'`.
        self.no_app(SQL_LIBERTAR, self.tenant, self.encomenda, "expirada")
        linhas = self.no_batch(SQL_VENCIDAS, "2026-12-01T00:00:00+00:00", 100)
        self.assertNotIn(
            vencida,
            {str(l[0]) for l in linhas},
            "uma reserva libertada nao volta a ser varrida",
        )

    def test_dois_varredores_em_simultaneo_veem_conjuntos_disjuntos(self) -> None:
        """Os «dois *workers* a varrer em simultaneo» dos *Testes Requeridos*.

        **O `SKIP LOCKED` e o que torna isto reparticao e nao espera.** Sem ele,
        o segundo varredor bloqueava na primeira linha trancada pelo primeiro e
        o varrimento era serial — correcto, e com metade da taxa. Com ele, cada
        um leva um conjunto e **nenhuma linha vai aos dois**, que e a propriedade
        que impede a dupla libertacao antes mesmo de o CAS ser consultado.

        Cada varredor abre a sua ligacao, espera na barreira e **nao confirma**
        enquanto o outro nao tiver lido: sem isso, o primeiro largava as trancas
        antes de o segundo chegar e os dois viam tudo — verde, e sobre nada.
        """
        for linha in range(VENCIDAS):
            self.criar_reserva(linha=linha, vencida=True)

        # **As barreiras levam prazo**, e nao e zelo: um `Barrier.wait()` sem
        # `timeout` espera para sempre, e se um dos varredores falhar antes de
        # chegar a barreira o outro fica pendurado — a suite **para** em vez de
        # falhar, e um ensaio pendurado nao diz qual e a linha trancada.
        # Aprendido nesta sessao, por outra via: ver a nota do `no_app`.
        barreira = threading.Barrier(VARREDORES, timeout=PRAZO_DA_BARREIRA)
        leu = threading.Barrier(VARREDORES, timeout=PRAZO_DA_BARREIRA)

        def varredor() -> list[str]:
            conexao = ligacao.ligar("batch")
            try:
                cursor = conexao.cursor()
                barreira.wait()
                cursor.execute(
                    SQL_VENCIDAS.sql,
                    SQL_VENCIDAS.args("2026-12-01T00:00:00+00:00", VENCIDAS // 2),
                )
                meu = [str(l[0]) for l in cursor.fetchall()]
                # So depois de os dois terem lido e que se largam as trancas.
                leu.wait()
                conexao.rollback()
                return meu
            finally:
                conexao.close()

        with concurrent.futures.ThreadPoolExecutor(max_workers=VARREDORES) as piscina:
            conjuntos = [t.result() for t in [piscina.submit(varredor) for _ in range(VARREDORES)]]

        primeiro, segundo = set(conjuntos[0]), set(conjuntos[1])
        self.assertEqual(
            primeiro & segundo,
            set(),
            "nenhuma reserva foi aos dois varredores: e o SKIP LOCKED",
        )
        self.assertEqual(
            len(primeiro) + len(segundo),
            VENCIDAS,
            "e entre os dois levaram as seis: o SKIP LOCKED reparte, nao perde",
        )


class TestAIdempotenciaDaLibertacao(ComUmaReserva):
    """Criterio 4 e 6: execucao dupla = 1 libertacao."""

    def test_libertar_duas_vezes_devolve_stock_uma_vez(self) -> None:
        self.criar_reserva(qty=2, vencida=True)
        self.assertEqual(self.stock_de(self.tenant, self.sku), (STOCK, 2))

        primeiras = self.no_app(
            SQL_LIBERTAR, self.tenant, self.encomenda, "expirada"
        )
        self.assertEqual(len(primeiras), 1)
        self.assertEqual(
            len(self.no_app(SQL_DEVOLVER_STOCK, self.tenant, self.sku, 2)),
            1,
            "devolveu o stock",
        )

        self.assertEqual(
            self.no_app(SQL_LIBERTAR, self.tenant, self.encomenda, "expirada"),
            [],
            "a segunda libertacao casa zero linhas, pelo que nao ha `(sku, qty)` "
            "nenhum para devolver — e e ai que a dupla devolucao nao acontece",
        )
        self.assertEqual(
            self.stock_de(self.tenant, self.sku),
            (STOCK, 0),
            "o contador voltou a zero **uma** vez",
        )

    def test_o_cas_do_varrimento_recusa_a_versao_velha(self) -> None:
        """O *delayed job* que acorda depois de o repetivel ja ter tratado."""
        reserva = self.criar_reserva(vencida=True)
        self.assertEqual(
            len(self.no_app(SQL_LIBERTAR_UMA, self.tenant, reserva, "expirada", 1)),
            1,
            "a versao 1 ganha",
        )
        self.assertEqual(
            self.no_app(SQL_LIBERTAR_UMA, self.tenant, reserva, "expirada", 1),
            [],
            "quem chega com a versao 1 outra vez nao casa: o estado ja nao e "
            "`ativa` **e** a versao ja nao e 1",
        )
        self.assertEqual(self.estado_da_reserva(reserva), ("libertada", "expirada", 2))

    def test_o_cas_recusa_a_versao_velha_com_a_reserva_ainda_ativa(self) -> None:
        """**O ensaio que isola o `AND version = $4`**, e faltava.

        O caso de cima (`..._recusa_a_versao_velha`) liberta primeiro e repete
        com a versao velha — mas ai o `estado = 'ativa'` do predicado ja chega
        para recusar, pelo que o `version` nao e exercitado. A revisao
        adversarial mediu-o: trocar `AND version = $4` por `AND version >= $4`
        deixava a suite inteira verde.

        O caso que **falsifica** e este: a reserva continua `ativa` e a `version`
        ja subiu. Produz-se pelo caminho real — o `SQL_CONFIRMAR` sobe a versao
        e **nao** muda o estado —, que e exactamente o que um *delayed job*
        agendado antes da confirmacao encontra quando dispara.
        """
        reserva = self.criar_reserva(vencida=True, confirmada=False)
        self.no_app(
            SQL_CONFIRMAR,
            self.tenant,
            self.encomenda,
            self.instante_da_reserva(reserva, "1 minute"),
            TECTO,
        )
        estado, _, versao = self.estado_da_reserva(reserva)
        self.assertEqual(
            (estado, versao),
            ("ativa", 2),
            "pre-condicao: ainda `ativa` e ja na versao 2 — e o estado que so o "
            "`version` distingue",
        )

        self.assertEqual(
            self.no_app(SQL_LIBERTAR_UMA, self.tenant, reserva, "expirada", 1),
            [],
            "quem chega com a versao 1 e recusado **pelo `version`**: o "
            "`estado = 'ativa'` esta verdadeiro, pelo que so o CAS o pode "
            "recusar. E com `version >= $4` esta linha passava",
        )
        self.assertEqual(
            len(self.no_app(SQL_LIBERTAR_UMA, self.tenant, reserva, "expirada", 2)),
            1,
            "e com a versao certa passa, que e a prova no outro sentido",
        )

    def test_a_base_recusa_reanimar_uma_reserva_terminal(self) -> None:
        """`KA009`: `consumida` e `libertada` sao terminais.

        E a barreira para quem **forcar** — um `UPDATE` a mao de quem tem o
        privilegio. O predicado do modulo ja impede o caminho normal; isto
        impede o outro, que e o que faz da idempotencia uma restricao e nao uma
        convencao.
        """
        reserva = self.criar_reserva(vencida=True)
        self.no_app(SQL_LIBERTAR_UMA, self.tenant, reserva, "expirada", 1)

        estado = self.tentar(
            "UPDATE platform.stock_reservations "
            "   SET estado = 'ativa', motivo = NULL, libertada_at = NULL, "
            "       version = version + 1 "
            " WHERE id = %s",
            (reserva,),
        )
        self.assertEqual(
            estado, ESTADO_TERMINAL, "libertada nao volta a ativa, nem a mao"
        )

    def test_a_base_exige_que_a_version_suba_de_um_na_mudanca(self) -> None:
        """`KA008`, e **so** na mudanca de estado.

        A segunda metade e a que importa para o *gate* 6: um `UPDATE` que **nao**
        mude o estado nao pede nada, e e isso que deixa a
        `stock_reservations` ter receita de semente — ver a nota da funcao na
        revisao `0033`.
        """
        reserva = self.criar_reserva()
        estado = self.tentar(
            "UPDATE platform.stock_reservations SET estado = 'consumida', "
            "       consumida_at = now() WHERE id = %s",
            (reserva,),
        )
        self.assertEqual(
            estado, VERSAO_NAO_SUBIU, "mudou de estado sem subir a version"
        )

        self.assertIsNone(
            self.tentar(
                "UPDATE platform.stock_reservations SET expira_at = expira_at "
                " WHERE id = %s",
                (reserva,),
            ),
            "e um toque que nao muda o estado passa sem pedir version nenhuma",
        )


class TestOConsumo(ComUmaReserva):
    """Criterio 6, lado `consumida`: marca, e **nao** devolve stock."""

    def test_consumir_marca_e_nao_devolve_stock(self) -> None:
        self.criar_reserva(qty=3)
        self.assertEqual(self.stock_de(self.tenant, self.sku), (STOCK, 3))

        linhas = self.no_app(SQL_CONSUMIR, self.tenant, self.encomenda)
        self.assertEqual(len(linhas), 1)
        self.assertEqual(
            self.stock_de(self.tenant, self.sku),
            (STOCK, 3),
            "uma reserva consumida e stock que saiu: devolve-lo era po-lo outra "
            "vez a venda depois de o cliente o ter pago",
        )

        self.assertEqual(
            self.no_app(SQL_CONSUMIR, self.tenant, self.encomenda),
            [],
            "consumir duas vezes e um nao-evento",
        )


class TestOProlongamento(ComUmaReserva):
    """Criterio 7: so com cobranca, so para a frente, e so ate as 72 h."""

    def test_estende_dentro_do_tecto(self) -> None:
        reserva = self.criar_reserva()
        dentro = self.instante_da_reserva(reserva, "60 hours")
        self.assertEqual(
            len(self.no_app(SQL_ESTENDER, self.tenant, self.encomenda, dentro, TECTO)),
            1,
            "60 h cabe nas 72 h",
        )

    def test_recusa_acima_do_tecto_de_setenta_e_duas_horas(self) -> None:
        """E o tecto mede-se contra o `criado_at`, nao contra `now()`.

        Dois `extendReservation` de 36 h cada passavam a validacao do modulo um
        a um e somavam 72 h sobre uma reserva que ja tinha 48. Contra o
        `criado_at`, a soma e a que conta.
        """
        reserva = self.criar_reserva()
        fora = self.instante_da_reserva(reserva, "73 hours")
        self.assertEqual(
            self.no_app(SQL_ESTENDER, self.tenant, self.encomenda, fora, TECTO),
            [],
            "73 h nao cabe nas 72 h",
        )

    def test_recusa_uma_reserva_provisoria(self) -> None:
        """«Exige cobranca com validade correspondente», a letra do criterio."""
        reserva = self.criar_reserva(confirmada=False)
        dentro = self.instante_da_reserva(reserva, "60 hours")
        self.assertEqual(
            self.no_app(SQL_ESTENDER, self.tenant, self.encomenda, dentro, TECTO),
            [],
            "sem cobranca emitida nao se estende: espera-se pelo charge.issued",
        )

    def test_recusa_um_prazo_para_tras(self) -> None:
        self.criar_reserva()
        self.assertEqual(
            self.no_app(
                SQL_ESTENDER,
                self.tenant,
                self.encomenda,
                "2020-01-01T00:00:00+00:00",
                TECTO,
            ),
            [],
            "prolongar para tras nao e prolongar",
        )


class TestAsMedidasDaDoD(ComUmaReserva):
    """Caixa 5 da DoD: reservas activas por tenant, e o atraso da libertacao."""

    def test_as_reservas_activas_contam_se_por_tenant(self) -> None:
        self.criar_reserva(linha=0)
        self.criar_reserva(linha=1)
        linhas = self.no_batch(SQL_ACTIVAS_POR_TENANT)
        por_tenant = {str(l[0]): int(l[1]) for l in linhas}
        self.assertEqual(
            por_tenant.get(self.tenant), 2, "duas activas neste tenant"
        )

    def test_o_atraso_da_libertacao_mede_se_sobre_a_base(self) -> None:
        """O `reservation_release_lag`, e porque se le da base.

        O criterio pede «p99 <= 60 s» sobre o intervalo entre o instante em que
        a reserva venceu e o instante em que foi libertada — e o processo que a
        libertou so sabe do segundo. Um *job* que arrancasse atrasado media zero
        e dizia-se dentro do prazo.
        """
        reserva = self.criar_reserva(vencida=True)
        self.no_app(SQL_LIBERTAR_UMA, self.tenant, reserva, "expirada", 1)

        linhas = self.no_batch(SQL_ATRASO_DA_LIBERTACAO, "2020-01-01T00:00:00+00:00")
        atrasos = [float(l[0]) for l in linhas]
        self.assertTrue(atrasos, "ha pelo menos uma libertacao medida")
        self.assertGreater(
            max(atrasos),
            0,
            "a reserva venceu ha um minuto e foi libertada agora: o atraso e "
            "positivo, e e isso que o `libertada_at - expira_at` mede",
        )

    def test_as_leituras_da_oferta_e_das_reservas_correm(self) -> None:
        """O `SQL_LER_OFERTA` e o `SQL_LER_RESERVAS`, contra a base."""
        self.criar_reserva(linha=0, qty=2)
        oferta = self.no_app(SQL_LER_OFERTA, self.tenant, self.sku)[0]
        self.assertEqual(str(oferta[0]), self.sku)
        self.assertEqual(int(oferta[3]), STOCK, "a quantidade declarada")
        self.assertEqual(int(oferta[4]), 2, "e o que esta prometido")

        reservas = self.no_app(SQL_LER_RESERVAS, self.tenant, self.encomenda)
        self.assertEqual(len(reservas), 1)
        self.assertEqual(str(reservas[0][5]), "ativa")


class TestCoberturaDasReservas(ComUmaReserva):
    """As consultas das reservas sao exercitadas, e nos dois sentidos."""

    def test_as_consultas_declaradas_existem_no_modulo(self) -> None:
        from tests_encomendas import consultas

        for nome in EXERCITADAS_DAS_RESERVAS:
            with self.subTest(consulta=nome):
                self.assertTrue(hasattr(consultas, nome))

    def test_o_modulo_nao_tem_consulta_que_a_suite_nao_exercite(self) -> None:
        """O outro sentido: uma consulta nova entra sem ser provada.

        **Este ensaio apanhou um defeito deste proprio ticket**: a primeira
        versao do `EXERCITADAS_DAS_RESERVAS` declarava as doze consultas e a
        suite corria **uma** (o `SQL_RESERVAR`, no `test_reservas.py`). As outras
        onze entravam sem nunca terem tocado um PostgreSQL — que e exactamente a
        condicao em que o `SQL_GRELHA` do KAM-047 chegou com um defeito que
        nenhuma bateria tocava.
        """
        from tests_encomendas.consultas import MODULO_DAS_RESERVAS

        texto = MODULO_DAS_RESERVAS.read_text(encoding="utf-8")
        declaradas = set(re.findall(r"export const (SQL_[A-Z_]+) = `", texto))
        self.assertEqual(
            declaradas,
            set(EXERCITADAS_DAS_RESERVAS),
            "uma cadeia SQL nova no modulo das reservas tem de entrar no "
            "`EXERCITADAS_DAS_RESERVAS` e ser corrida contra a base",
        )

    def test_a_lista_do_typescript_e_a_da_suite_sao_a_mesma(self) -> None:
        """O terceiro sentido: o `CONSULTAS_DAS_RESERVAS` do modulo.

        O modulo declara ele proprio a lista das suas consultas, para o seu
        ensaio de contrato em TypeScript. Se as duas listas divergirem, uma das
        duas esta a medir menos do que diz — e a que fica a mentir e sempre a
        que ninguem corre.
        """
        from tests_encomendas.consultas import MODULO_DAS_RESERVAS

        texto = MODULO_DAS_RESERVAS.read_text(encoding="utf-8")
        bloco = re.search(
            r"CONSULTAS_DAS_RESERVAS = \[(.*?)\] as const;", texto, re.S
        )
        self.assertIsNotNone(bloco, "o modulo declara a sua lista")
        do_modulo = set(re.findall(r'"(SQL_[A-Z_]+)"', bloco.group(1)))
        self.assertEqual(do_modulo, set(EXERCITADAS_DAS_RESERVAS))
