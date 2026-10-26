"""Gate 8: o que a revisao 0004 promete, contra um PostgreSQL 18.6 real (KAM-005).

Os criterios 1, 2 e 6 do KAM-005 sao propriedades de **transaccao** e de
**funcao**, e nao se provam com uma base falsa: provam-se aqui. Os criterios 3,
4, 5 e 8 precisam tambem de uma fila, e estao em `db/tests_eventos/`.

O que este ficheiro mede, e porque e aqui:

    TestUuidv7            `uuidv7()` existe na imagem fixada. O `docs/tecnica/06`
                          §4 marcava-o INDICIO e o ticket permitia gerar o UUID
                          na aplicacao; a medicao dispensou o desvio, e repete-se
                          a cada execucao para que a afirmacao nao envelheca.
    TestRollback          criterio 1: 1 000 transaccoes, umas confirmadas e
                          outras revertidas, e o `seq` sem lacunas.
    TestConcorrencia      criterio 2: duas transaccoes no mesmo agregado
                          serializam-se, e a ordem de `seq` e a de `COMMIT`.
    TestGuardaDePii       criterio 6: um `payload` com padrao de telefone faz
                          `evt_emitir` falhar com `check_violation`.
    TestParidadeDoGuardaDePii
                          os dois `~` do SQL e os dois `RegExp` do TypeScript
                          dizem o mesmo em todas as cadeias da *fixture*.
    TestParticao          a particao e determinista, esta em 0..15, e o mesmo
                          par `(tenant, agregado)` cai sempre na mesma.
    TestEnvelope          o `jsonb_build_object` escreve as treze chaves, e as
                          colunas de indexacao batem com o que esta dentro.
    TestIsolamentoDoOutbox
                          o `INSERT` do produtor esta sob `WITH CHECK`, e o
                          `evt_emitir` e `SECURITY INVOKER` — se fosse
                          `DEFINER`, a RLS do outbox nao valia nada.
    TestArquivoImutavel   ninguem tem `UPDATE` nem `DELETE` no `events_log`, e a
                          particao `DEFAULT` nao tem privilegio nenhum.
"""

from __future__ import annotations

import json
import random
import re
import threading
import time
import unittest
from pathlib import Path

import ligacao
from tests.base import (
    PRIVILEGIO_INSUFICIENTE,
    VIOLACAO_DE_CHECK,
    ComBase,
    ConsultaDoTypeScript,
)

RAIZ = Path(__file__).resolve().parents[2]
FIXTURE_DE_PII = (
    RAIZ / "packages" / "core-ts" / "tests" / "fixtures" / "eventos_pii.json"
)

#: Os dois padroes de `platform.evt_emitir`, escritos aqui para o teste de
#: paridade os poder correr isolados (`SELECT %s ~ %s`). Tem de ser **iguais**
#: aos da revisao; `TestParidadeDoGuardaDePii` confirma que a revisao os contem.
PADRAO_TELEFONE_AO = r"\+?244 ?9[0-9]{8}"
PADRAO_E164 = r'"\+[0-9]{9,15}"'

REVISAO = RAIZ / "db" / "migrations" / "versions" / "0004_outbox_e_eventos.py"

#: O espelho em TypeScript do guarda — a outra metade da paridade.
GUARDA_TS = RAIZ / "packages" / "core-ts" / "src" / "eventos" / "pii.ts"

#: O nome de cada `RegExp` do `pii.ts` e o padrao do SQL que ele tem de repetir.
#: A **ordem** e a do `evt_emitir`, e e a ordem em que
#: `PADROES_DE_TELEFONE` os tem de listar.
PADROES_DO_GUARDA_TS = (
    ("TELEFONE_AO", PADRAO_TELEFONE_AO),
    ("E164_ENTRE_ASPAS", PADRAO_E164),
)

#: O criterio 1 pede «1 000 *rollbacks* aleatorios». Mil **rollbacks**, e nao
#: mil transaccoes de que metade reverte: a primeira versao deste teste fazia
#: mil transaccoes e ~500 reversoes, e a revisao adversarial (ANALISE-20, achado
#: 9) apanhou-o. O laco corre ate ter mil reversoes, com confirmacoes pelo meio
#: ao acaso — e e a mistura que o criterio quer.
ROLLBACKS_DO_CRITERIO_1 = 1000

#: Quantas repeticoes o criterio 2 pede. «100 repeticoes.»
REPETICOES_DO_CRITERIO_2 = 100

#: As consultas do publicador, de onde se le o `SQL_MARCAR_PUBLICADO` para o
#: correr tal e qual — uma copia dele aqui provaria que a copia funciona.
CONSULTAS_DOS_EVENTOS = (
    RAIZ / "packages" / "core-ts" / "src" / "eventos" / "consultas.ts"
)

#: Quanto tempo tem de passar dentro da transaccao para que o relogio do seu
#: inicio fique mensuravelmente atras do da escrita. 50 ms chegam e sobram
#: para a resolucao de microssegundos do `timestamptz`.
ESPERA_DO_ATRASO = 0.05

#: Quantos agregados confrontam a mascara da particao com a conta do documento.
#: Um so dava 50% de deteccao a uma mascara errada por um bit — ver
#: `TestParticao.test_a_conta_e_a_do_documento`.
AGREGADOS_DA_PARIDADE = 24

SQL_EMITIR = (
    "SELECT platform.evt_emitir(%s, 1::smallint, %s, %s, %s, %s::jsonb)"
)


def _apagar_depois(sql: str) -> None:
    """Corre uma instrucao numa ligacao propria, depois do `tearDown`.

    Os `addCleanup` correm **depois** do `tearDown`, e o de `ComBase` fecha as
    ligacoes de `self.ligar`. Uma limpeza que use uma dessas rebenta com
    `connection is closed`.
    """
    conexao = ligacao.ligar("admin")
    conexao.autocommit = True
    try:
        conexao.cursor().execute(sql)
    finally:
        conexao.close()


def _emitir(cursor, tenant: str, agregado: str, payload: dict | None = None,
            tipo: str = "order.created") -> str:
    cursor.execute(
        SQL_EMITIR,
        (tipo, tenant, "order", agregado, json.dumps(payload or {"order_id": agregado})),
    )
    return str(cursor.fetchone()[0])


class ComEventos(ComBase):
    """Um tenant proprio por classe, e as linhas de eventos apagadas no fim.

    As tabelas de eventos nao tem FK para `tenants` (o `agregado_id` e uma
    referencia logica, por desenho), pelo que o tenant e so um UUID. Apaga-se
    com o administrador: o `kamba_batch` nao tem `DELETE` no arquivo.
    """

    @classmethod
    def setUpClass(cls) -> None:
        super().setUpClass()
        cls._limpeza = ligacao.ligar("admin")
        cls._limpeza.autocommit = True

    @classmethod
    def tearDownClass(cls) -> None:
        cls._limpeza.close()
        super().tearDownClass()

    def setUp(self) -> None:
        super().setUp()
        import uuid as _uuid

        self.tenant = str(_uuid.uuid4())
        self.agregado = f"agg-{_uuid.uuid4().hex}"
        self.addCleanup(self._apagar)

    def _apagar(self) -> None:
        """Apaga pelo prefixo do agregado, **nao** pelo tenant.

        Alguns destes testes emitem com tenants aleatorios de proposito (a
        distribuicao das particoes nao se ve com um tenant so), e esses nao
        estao em `self.tenant`. Pelo prefixo `agg-`, que todos os agregados
        desta suite levam, nao fica nada para tras — e nao ficar nada para tras
        nao e higiene: o `downgrade` da 0004 **recusa-se a correr** com linhas
        nas tabelas de eventos, e `test_migracao.TestCiclo`, que corre depois
        desta suite por ordem alfabetica, faz `downgrade base`.
        """
        cursor = self._limpeza.cursor()
        for tabela in ("events_outbox", "events_log", "evt_agregado_seq"):
            cursor.execute(
                f"DELETE FROM platform.{tabela} WHERE agregado_id LIKE 'agg-%'"
            )

    def admin(self):
        """Ligacao de administrador, sem `autocommit`: o teste controla a transaccao."""
        conexao = self.ligar("admin")
        return conexao, conexao.cursor()


class TestUuidv7(ComBase):
    """O INDICIO do `docs/tecnica/06` §4, medido.

    O ticket permitia o desvio «se `uuidv7()` nao existir no PG 18.6 fixado,
    gerar UUIDv7 na aplicacao e registar no PR». Nao foi necessario — e se um
    dia a imagem mudar, e este teste que o diz, em vez de a revisao rebentar com
    `function uuidv7() does not exist` a meio de um `upgrade`.
    """

    def test_a_funcao_existe_na_imagem_fixada(self) -> None:
        self.assertEqual(
            self.consultar("SELECT count(*) > 0 FROM pg_proc WHERE proname = 'uuidv7'"),
            [(True,)],
        )

    def test_produz_um_uuid_de_versao_7_e_ordenavel_no_tempo(self) -> None:
        linhas = self.consultar(
            "SELECT uuidv7()::text, uuidv7()::text FROM generate_series(1, 20)"
        )
        self.assertEqual(len(linhas), 20)
        for primeiro, segundo in linhas:
            # O digito da versao e o 13.o hexadecimal (`xxxxxxxx-xxxx-7xxx-...`).
            self.assertEqual(primeiro[14], "7", primeiro)
            self.assertEqual(segundo[14], "7", segundo)
        # Monotono dentro da mesma instrucao: e isso que faz do `event_id` uma
        # chave ordenavel no tempo (`docs/tecnica/06` §4).
        self.assertEqual(
            [p for p, _ in linhas], sorted(p for p, _ in linhas), "uuidv7 sem ordem"
        )

    def test_a_revisao_usa_o_uuidv7_nativo(self) -> None:
        """Se alguem trocar para geracao na aplicacao, o desvio tem de ser visivel."""
        self.assertIn("v_id uuid := uuidv7()", REVISAO.read_text(encoding="utf-8"))


class TestRollback(ComEventos):
    """Criterio 1: o evento esta na transaccao do produtor, e o `seq` nao tem lacunas."""

    def test_um_rollback_nao_deixa_linha_no_outbox_nem_consome_seq(self) -> None:
        conexao, cursor = self.admin()
        _emitir(cursor, self.tenant, self.agregado)
        conexao.rollback()
        self.assertEqual(
            self.consultar(
                "SELECT count(*) FROM platform.events_outbox WHERE tenant_id = %s",
                (self.tenant,),
            ),
            [(0,)],
        )
        self.assertEqual(
            self.consultar(
                "SELECT count(*) FROM platform.evt_agregado_seq WHERE agregado_id = %s",
                (self.agregado,),
            ),
            [(0,)],
        )

    def test_mil_transaccoes_aleatorias_deixam_sequencias_contiguas(self) -> None:
        """O criterio, a letra: 1 000 transaccoes, com *rollbacks* ao acaso.

        A semente e fixa: uma sequencia aleatoria diferente a cada execucao
        tornava uma falha irreproduzivel, e o que o criterio pede e que **toda**
        a mistura de confirmadas e revertidas deixe o `seq` contiguo — nao uma
        mistura em particular.
        """
        sorteio = random.Random(20261012)
        conexao, cursor = self.admin()
        confirmadas = 0
        revertidas = 0
        while revertidas < ROLLBACKS_DO_CRITERIO_1:
            _emitir(cursor, self.tenant, self.agregado)
            if sorteio.random() < 0.5:
                conexao.commit()
                confirmadas += 1
            else:
                conexao.rollback()
                revertidas += 1
        conexao.commit()

        self.assertEqual(revertidas, ROLLBACKS_DO_CRITERIO_1)
        self.assertGreater(confirmadas, 0)
        sequencias = [
            s
            for (s,) in self.consultar(
                "SELECT agregado_seq FROM platform.events_outbox "
                "WHERE agregado_id = %s ORDER BY agregado_seq",
                (self.agregado,),
            )
        ]
        self.assertEqual(
            sequencias,
            list(range(1, confirmadas + 1)),
            "ha lacunas ou repeticoes no `seq` do agregado",
        )
        self.assertEqual(
            self.consultar(
                "SELECT seq FROM platform.evt_agregado_seq WHERE agregado_id = %s",
                (self.agregado,),
            ),
            [(confirmadas,)],
            "o contador nao acompanhou as transaccoes confirmadas",
        )

    def test_o_seq_e_por_agregado_e_nao_global(self) -> None:
        conexao, cursor = self.admin()
        outro = f"{self.agregado}-b"
        for _ in range(3):
            _emitir(cursor, self.tenant, self.agregado)
        _emitir(cursor, self.tenant, outro)
        conexao.commit()
        self.assertEqual(
            self.consultar(
                "SELECT agregado_id, seq FROM platform.evt_agregado_seq "
                "WHERE agregado_id IN (%s, %s) ORDER BY 1",
                (self.agregado, outro),
            ),
            [(self.agregado, 3), (outro, 1)],
        )

    def test_a_unicidade_do_triplo_impede_duas_linhas_com_o_mesmo_seq(self) -> None:
        """`UNIQUE (agregado_tipo, agregado_id, agregado_seq)` nao e decoracao."""
        from tests.base import VIOLACAO_DE_UNICIDADE

        conexao, cursor = self.admin()
        _emitir(cursor, self.tenant, self.agregado)
        conexao.commit()
        cursor = self.ligar("admin").cursor()
        self.assertErroSql(
            VIOLACAO_DE_UNICIDADE,
            cursor,
            "INSERT INTO platform.events_outbox "
            "(event_id, tipo, versao, tenant_id, agregado_tipo, agregado_id, "
            " agregado_seq, particao, envelope) "
            "VALUES (gen_random_uuid(), 'order.created', 1, %s, 'order', %s, 1, 0, '{}')",
            (self.tenant, self.agregado),
        )


class TestConcorrencia(ComEventos):
    def esperar_bloqueio(self, cursor, limite: float = 10.0) -> bool:
        """Ha alguma sessao desta base a espera de uma tranca?

        E um **facto do servidor** (`pg_stat_activity.wait_event_type`), e nao
        uma inferencia de um `sleep`. A pergunta e feita por uma ligacao
        **propria e reutilizada**: as duas do teste estao ocupadas (uma com a
        transaccao aberta, a outra bloqueada), e abrir uma por pergunta num laco
        de 100 repeticoes esgotava as ligacoes do servidor — `sorry, too many
        clients already`, medido.
        """
        fim = time.monotonic() + limite
        while time.monotonic() < fim:
            cursor.execute(
                "SELECT count(*) FROM pg_stat_activity "
                " WHERE datname = current_database() AND wait_event_type = 'Lock'"
            )
            if int(cursor.fetchone()[0]) > 0:
                return True
            time.sleep(0.05)
        return False

    """Criterio 2: duas transaccoes no mesmo agregado serializam-se."""

    def test_a_segunda_transaccao_espera_pela_primeira(self) -> None:
        """E espera **mesmo**: nao basta que o resultado saia certo.

        Se o `ON CONFLICT DO UPDATE` nao trancasse a linha, as duas transaccoes
        liam o mesmo `seq` e uma delas rebentava na unicidade do triplo — ou,
        pior, as duas passavam com o mesmo `seq` se a unicidade nao existisse.
        O que se mede e o bloqueio: a segunda nao termina enquanto a primeira
        nao confirmar.
        """
        primeira, cursor_1 = self.admin()
        segunda, cursor_2 = self.admin()
        cursor_2.execute("SET lock_timeout = '15s'")

        _emitir(cursor_1, self.tenant, self.agregado)
        estado: dict[str, object] = {}

        def emitir_na_segunda() -> None:
            try:
                estado["id"] = _emitir(cursor_2, self.tenant, self.agregado)
            except Exception as erro:  # noqa: BLE001 — o teste reporta o que vier
                estado["erro"] = erro

        fio = threading.Thread(target=emitir_na_segunda)
        fio.start()
        time.sleep(0.5)
        self.assertTrue(fio.is_alive(), "a segunda transaccao nao esperou pela primeira")

        primeira.commit()
        fio.join(timeout=20)
        self.assertFalse(fio.is_alive(), "a segunda transaccao nao desbloqueou")
        self.assertNotIn("erro", estado, estado.get("erro"))
        segunda.commit()

        self.assertEqual(
            self.consultar(
                "SELECT agregado_seq FROM platform.events_outbox "
                "WHERE agregado_id = %s ORDER BY id",
                (self.agregado,),
            ),
            [(1,), (2,)],
        )

    def test_cem_repeticoes_dao_a_ordem_de_commit(self) -> None:
        """O criterio, a letra: 100 repeticoes, `seq` 1 e 2 sem lacuna.

        A ordem de `COMMIT` e escolhida pelo teste — primeira, depois segunda —
        e o que se verifica e que o `seq` 1 ficou com o evento da que confirmou
        primeiro. Se o `seq` saisse de uma sequencia (`nextval`) em vez da
        linha trancada, a segunda nao esperava e podia levar o `seq` 1.
        """
        primeira, cursor_1 = self.admin()
        segunda, cursor_2 = self.admin()
        cursor_2.execute("SET lock_timeout = '15s'")
        # Uma so ligacao para as cem perguntas ao `pg_stat_activity`.
        vigia = self.ligar("admin")
        vigia.autocommit = True
        cursor_vigia = vigia.cursor()
        esperado: list[tuple[int, str]] = []

        for repeticao in range(REPETICOES_DO_CRITERIO_2):
            agregado = f"{self.agregado}-{repeticao}"
            id_1 = _emitir(cursor_1, self.tenant, agregado)
            estado: dict[str, object] = {}
            partiu = threading.Event()

            def emitir_na_segunda(alvo: str = agregado) -> None:
                partiu.set()
                try:
                    estado["id"] = _emitir(cursor_2, self.tenant, alvo)
                except Exception as erro:  # noqa: BLE001
                    estado["erro"] = erro

            fio = threading.Thread(target=emitir_na_segunda)
            fio.start()
            # **A barreira**, e nao um `start()` seguido de `commit()`: sem ela,
            # na maioria das repeticoes a segunda transaccao nem chegava a pedir
            # o `seq` antes de a primeira confirmar, e as 100 repeticoes
            # exercitavam o caminho **sem contencao** — isto e, nao eram 100
            # repeticoes do que o criterio 2 pede. Achado da revisao adversarial
            # (ANALISE-20, achado 9). Espera-se que o fio tenha partido e que o
            # **servidor** confirme que ha uma sessao a espera de uma tranca.
            self.assertTrue(partiu.wait(timeout=10))
            self.assertTrue(
                self.esperar_bloqueio(cursor_vigia),
                f"a repeticao {repeticao} nao chegou a bloquear",
            )
            primeira.commit()
            fio.join(timeout=20)
            self.assertNotIn("erro", estado, estado.get("erro"))
            segunda.commit()
            esperado += [(1, id_1), (2, str(estado["id"]))]

        obtido = [
            (seq, str(event_id))
            for seq, event_id in self.consultar(
                "SELECT agregado_seq, event_id FROM platform.events_outbox "
                "WHERE agregado_id LIKE %s ORDER BY agregado_id, agregado_seq",
                (f"{self.agregado}-%",),
            )
        ]
        self.assertEqual(len(obtido), 2 * REPETICOES_DO_CRITERIO_2)
        self.assertEqual(sorted(obtido), sorted(esperado))
        self.assertEqual(
            {seq for seq, _ in obtido}, {1, 2}, "houve lacuna ou `seq` a mais"
        )


class TestGuardaDePii(ComEventos):
    """Criterio 6: um `payload` com padrao de telefone falha com `check_violation`."""

    def test_um_telefone_angolano_no_payload_falha(self) -> None:
        conexao, cursor = self.admin()
        self.assertErroSql(
            VIOLACAO_DE_CHECK,
            cursor,
            SQL_EMITIR,
            (
                "order.created",
                self.tenant,
                "order",
                self.agregado,
                json.dumps({"recipient": "+244912345678"}),
            ),
        )

    def test_um_e164_entre_aspas_tambem(self) -> None:
        conexao, cursor = self.admin()
        self.assertErroSql(
            VIOLACAO_DE_CHECK,
            cursor,
            SQL_EMITIR,
            (
                "order.created",
                self.tenant,
                "order",
                self.agregado,
                json.dumps({"referencia": "+351912345678"}),
            ),
        )

    def test_a_mensagem_nomeia_o_tipo_e_nao_o_numero(self) -> None:
        """O erro vai para o registo do servidor: nao pode levar o telefone."""
        import pg8000.dbapi

        conexao, cursor = self.admin()
        with self.assertRaises(pg8000.dbapi.DatabaseError) as capturado:
            _emitir(cursor, self.tenant, self.agregado, {"recipient": "+244912345678"})
        mensagem = str(capturado.exception)
        self.assertIn("order.created", mensagem)
        self.assertIn("padrao de telefone", mensagem)
        self.assertNotIn("244912345678", mensagem)
        conexao.rollback()

    def test_o_guarda_recusa_antes_de_escrever_nada(self) -> None:
        """Sem linha no outbox e sem `seq` consumido: a guarda e o primeiro passo."""
        import pg8000.dbapi

        conexao, cursor = self.admin()
        _emitir(cursor, self.tenant, self.agregado)
        with self.assertRaises(pg8000.dbapi.DatabaseError):
            _emitir(cursor, self.tenant, self.agregado, {"x": "+244912345678"})
        conexao.rollback()
        self.assertEqual(
            self.consultar(
                "SELECT count(*) FROM platform.evt_agregado_seq WHERE agregado_id = %s",
                (self.agregado,),
            ),
            [(0,)],
        )

    def test_a_guarda_tem_falsos_positivos_em_identificadores_opacos(self) -> None:
        """O `+` do padrao do §6.1 e **opcional**, e isso tem consequencia.

        `\\+?244 ?9[0-9]{8}` sem o `+` apanha qualquer corrida de doze digitos
        que comece por `2449`. Um identificador hexadecimal de 32 caracteres
        contem uma dessas de vez em quando — e foi assim que a medicao de carga
        deste ticket rebentou ao evento ~8 000 de 15 000, com
        `check_violation` sobre um `agg-<hex>` que nao tinha telefone nenhum.

        **A consequencia nao e um aviso: e a transaccao de negocio a falhar.**
        O `evt_emitir` corre na transacção do produtor, pelo que um falso
        positivo faz a encomenda — ou o pagamento — nao ser gravada.

        Este teste **fixa o comportamento** (nao o corrige): o padrao e o do
        documento e o criterio 6 exige-o. A decisao de o apertar — exigir o `+`,
        ou uma fronteira de palavra — muda o §6.1 e esta devolvida
        (`docs/eventos.md`, decisao aberta 11). Enquanto nao estiver tomada, quem
        emitir eventos tem de saber que isto acontece.
        """
        import pg8000.dbapi

        conexao, cursor = self.admin()
        # Doze digitos comecados por `2449`, dentro de um identificador opaco.
        opaco = "agg-7f2449123456780bc1"
        with self.assertRaises(pg8000.dbapi.DatabaseError) as capturado:
            _emitir(cursor, self.tenant, opaco, {"order_id": opaco})
        self.assertIn("padrao de telefone", str(capturado.exception))
        conexao.rollback()

        # E a prova de que e o `+` opcional: com o padrao a exigir o `+`, a
        # mesma cadeia passava. Mede-se o predicado directamente.
        self.assertEqual(
            self.consultar(
                "SELECT %s ~ %s, %s ~ %s",
                (opaco, PADRAO_TELEFONE_AO, opaco, r"\+244 ?9[0-9]{8}"),
            ),
            [(True, False)],
        )

    def test_um_payload_sem_telefone_passa(self) -> None:
        conexao, cursor = self.admin()
        identificador = _emitir(
            cursor,
            self.tenant,
            self.agregado,
            {"order_id": self.agregado, "valor_minor": 24500000, "currency": "AOA"},
        )
        conexao.commit()
        self.assertEqual(len(identificador), 36)


class TestParidadeDoGuardaDePii(ComBase):
    """Os dois `~` do SQL e os dois `RegExp` do TypeScript dizem o mesmo.

    A *fixture* e a mesma que `packages/core-ts/tests/eventos.pii.test.ts` le.
    Duas implementacoes do mesmo predicado so se mantem honestas se houver uma
    maquina a confronta-las — e a maquina e este teste.
    """

    @classmethod
    def setUpClass(cls) -> None:
        super().setUpClass()
        cls.fixture = json.loads(FIXTURE_DE_PII.read_text(encoding="utf-8"))

    def apanha(self, cadeia: str) -> bool:
        return self.consultar(
            "SELECT (%s ~ %s) OR (%s ~ %s)",
            (cadeia, PADRAO_TELEFONE_AO, cadeia, PADRAO_E164),
        )[0][0]

    def test_os_padroes_sao_os_da_revisao(self) -> None:
        """Se a revisao mudar um padrao, a paridade deixa de ser sobre ela."""
        corpo = REVISAO.read_text(encoding="utf-8")
        self.assertIn(r"p_payload::text ~ '\+?244 ?9[0-9]{8}'", corpo)
        self.assertIn(r"""p_payload::text ~ '"\+[0-9]{9,15}"'""", corpo)

    def test_cada_regexp_do_typescript_e_o_padrao_do_sql(self) -> None:
        """A outra metade da paridade: o `RegExp` e o `~` sao a mesma cadeia.

        A fixture corria so contra o PostgreSQL, e o docstring desta classe
        prometia os dois lados. O lado TypeScript nunca era lido aqui: a suite
        do gate 8 nao corre Node, e o `pii.ts` passava a valer pelo que a
        bateria *vitest* dissesse — que nao e esta prova.

        Le-se o modulo como texto, que e o padrao do
        `db/tests/test_consumo_contrato.py`: diz o que uma suite de execucao
        sem Node nao pode dizer.
        """
        corpo = GUARDA_TS.read_text(encoding="utf-8")
        for nome, padrao in PADROES_DO_GUARDA_TS:
            with self.subTest(padrao=nome):
                achado = re.search(
                    rf"^export const {nome} = /(?P<fonte>.*)/;$",
                    corpo,
                    re.MULTILINE,
                )
                self.assertIsNotNone(achado, f"`{nome}` nao esta no pii.ts")
                self.assertEqual(achado.group("fonte"), padrao)

    def test_o_guarda_do_typescript_usa_os_dois_padroes(self) -> None:
        """Um dos dois retirado da lista e meio guarda, e ninguem dava por ela.

        O canario e a propria lista: afirmar que os dois `RegExp` **existem**
        no ficheiro passava com qualquer um deles fora de
        `PADROES_DE_TELEFONE` — as constantes continuam declaradas, e e so a
        lista que o `padraoDeTelefoneEm` percorre. Por isso o que se compara e
        o conteudo da lista, e pela ordem do `evt_emitir`.
        """
        corpo = GUARDA_TS.read_text(encoding="utf-8")
        achado = re.search(
            r"^export const PADROES_DE_TELEFONE = \[(?P<lista>[^\]]*)\] as const;$",
            corpo,
            re.MULTILINE,
        )
        self.assertIsNotNone(achado, "`PADROES_DE_TELEFONE` nao esta no pii.ts")
        listados = [n.strip() for n in achado.group("lista").split(",") if n.strip()]
        self.assertEqual(listados, [nome for nome, _ in PADROES_DO_GUARDA_TS])

    def test_as_cadeias_apanhadas_sao_apanhadas_pelo_sql(self) -> None:
        self.assertTrue(self.fixture["apanhados"])
        for cadeia in self.fixture["apanhados"]:
            with self.subTest(cadeia=cadeia):
                self.assertTrue(self.apanha(cadeia))

    def test_as_cadeias_que_passam_passam_no_sql(self) -> None:
        self.assertTrue(self.fixture["passam"])
        for cadeia in self.fixture["passam"]:
            with self.subTest(cadeia=cadeia):
                self.assertFalse(self.apanha(cadeia))


class TestParticao(ComEventos):
    """Criterio 7, metade SQL: a particao e `hash(tenant_id || agregado_id) & 15`."""

    def test_a_particao_esta_sempre_em_0_15(self) -> None:
        import uuid as _uuid

        conexao, cursor = self.admin()
        for indice in range(64):
            _emitir(cursor, self.tenant, f"{self.agregado}-{indice}")
        for indice in range(16):
            _emitir(cursor, str(_uuid.uuid4()), f"{self.agregado}-t{indice}")
        conexao.commit()
        particoes = [
            p
            for (p,) in self.consultar(
                "SELECT DISTINCT particao FROM platform.events_outbox "
                "WHERE agregado_id LIKE %s ORDER BY 1",
                (f"{self.agregado}-%",),
            )
        ]
        self.assertTrue(particoes)
        self.assertTrue(all(0 <= p <= 15 for p in particoes), particoes)

    def test_oitenta_agregados_usam_mais_do_que_uma_particao(self) -> None:
        """Se a conta estivesse errada (um `%` em vez de um `&`, por exemplo),
        tudo cairia na mesma fila e a ordem valia para o sistema inteiro."""
        conexao, cursor = self.admin()
        for indice in range(80):
            _emitir(cursor, self.tenant, f"{self.agregado}-p{indice}")
        conexao.commit()
        distintas = self.consultar(
            "SELECT count(DISTINCT particao) FROM platform.events_outbox "
            "WHERE agregado_id LIKE %s",
            (f"{self.agregado}-p%",),
        )[0][0]
        self.assertGreater(distintas, 1, "80 agregados numa so particao")

    def test_o_mesmo_par_cai_sempre_na_mesma_particao(self) -> None:
        """E o que garante a ordem por agregado: dois eventos do mesmo agregado
        nao podem ir para filas diferentes."""
        conexao, cursor = self.admin()
        for _ in range(5):
            _emitir(cursor, self.tenant, self.agregado)
        conexao.commit()
        particoes = {
            p
            for (p,) in self.consultar(
                "SELECT particao FROM platform.events_outbox WHERE agregado_id = %s",
                (self.agregado,),
            )
        }
        self.assertEqual(len(particoes), 1, particoes)

    def test_a_conta_e_a_do_documento(self) -> None:
        """`hashtextextended(tenant || agregado_id, 0) & 15`, sem desvio.

        **Um agregado nao chega, e a prova por mutacao mostrou-o.** Com um so
        — e ele e um UUID novo por execucao (`setUp`) —, uma mascara errada por
        um bit (`& 7` em vez de `& 15`) so se ve quando o bit 3 do *hash* esta
        a 1: metade das execucoes. A mutacao `0004: a particao usa oito filas
        em vez de dezasseis` sobreviveu a noite de 2026-10-26 e foi apanhada na
        repeticao seguinte — o teste nao estava em falta, estava a matar **por
        sorte**.

        Com `AGREGADOS_DA_PARIDADE` agregados independentes, escapar exige que
        o bit 3 esteja a 0 em todos: 2 ** -24, da ordem de 1e-8. O custo e
        vinte e quatro `evt_emitir` numa transaccao.
        """
        conexao, cursor = self.admin()
        agregados = [f"{self.agregado}-c{i}" for i in range(AGREGADOS_DA_PARIDADE)]
        for agregado in agregados:
            _emitir(cursor, self.tenant, agregado)
        conexao.commit()
        linhas = self.consultar(
            "SELECT o.agregado_id, o.particao, "
            "       (hashtextextended(%s || o.agregado_id, 0) & 15)::smallint "
            "  FROM platform.events_outbox o WHERE o.agregado_id = ANY(%s) "
            " ORDER BY 1",
            (self.tenant, agregados),
        )
        self.assertEqual(len(linhas), AGREGADOS_DA_PARIDADE)
        for agregado, guardada, conta in linhas:
            with self.subTest(agregado=agregado):
                self.assertEqual(guardada, conta)


class TestMarcaDePublicado(ComEventos):
    """O `publicado_at` e o instante da **escrita**, nao o do inicio do ciclo.

    Corre o `SQL_MARCAR_PUBLICADO` lido do `consultas.ts`, pelo
    `ConsultaDoTypeScript` — o mesmo mecanismo do `test_accoes.py` e do
    `test_dlq_reabertura.py`. Uma copia da instrucao aqui provaria que a copia
    funciona.

    **Porque e que isto faltava.** Toda a bateria olhava para o `publicado_at`
    por `IS NULL` / `IS NOT NULL`, nunca pelo **valor**; e a unica que mede o
    atraso, a `tests_eventos_carga`, compara-o com um **tecto**. Trocar
    `clock_timestamp()` por `now()` baixa o atraso medido, pelo que faz esse
    teste passar com mais folga: a mutacao `eventos: o atraso e medido antes do
    trabalho` era imune por construcao, e sobreviveu a noite de 2026-10-26.
    """

    def test_o_publicado_at_e_posterior_ao_inicio_da_transaccao(self) -> None:
        """`now()` e `transaction_timestamp()`: o instante **antes** do trabalho.

        Com `now()` o `publicado_at` sai exactamente igual ao inicio da
        transaccao e o atraso do criterio 8 passa a excluir o enfileiramento do
        lote — o enviesamento cresce precisamente no regime em que o atraso real
        e maior (ANALISE-20, achado 7).
        """
        marcar = ConsultaDoTypeScript(
            "SQL_MARCAR_PUBLICADO", ficheiro=CONSULTAS_DOS_EVENTOS
        )
        conexao, cursor = self.admin()
        _emitir(cursor, self.tenant, self.agregado)
        conexao.commit()

        # Daqui para baixo e **uma** transaccao: o `transaction_timestamp()`
        # fica fixo no primeiro comando, e o `pg_sleep` afasta-o do relogio.
        cursor.execute(
            "SELECT id FROM platform.events_outbox WHERE agregado_id = %s",
            (self.agregado,),
        )
        ids = [linha[0] for linha in cursor.fetchall()]
        self.assertEqual(len(ids), 1, "o emitir nao deixou uma linha so")
        cursor.execute("SELECT pg_sleep(%s)", (ESPERA_DO_ATRASO,))
        cursor.execute(marcar.sql, marcar.args(ids))
        cursor.execute(
            "SELECT publicado_at, publicado_at - transaction_timestamp() "
            "  FROM platform.events_outbox WHERE id = ANY(%s)",
            (ids,),
        )
        publicado_at, atraso = cursor.fetchone()
        conexao.rollback()

        # O canario: sem esta linha, um `publicado_at` que ficasse NULL dava uma
        # subtraccao NULL e o teste rebentava — vermelho, mas pela razao errada.
        self.assertIsNotNone(publicado_at, "o SQL do modulo nao marcou a linha")
        self.assertGreaterEqual(
            atraso.total_seconds(),
            ESPERA_DO_ATRASO,
            "o `publicado_at` e o relogio do inicio da transaccao, nao o da escrita",
        )


class TestEnvelope(ComEventos):
    """O `jsonb_build_object` do §6.1: treze chaves, e coerente com as colunas."""

    CHAVES = (
        "id", "tipo", "versao", "tenant_id", "ocorrido_em", "registado_em",
        "produtor", "agregado", "correlacao_id", "causa_id", "trace_id",
        "classe_pii", "finalidades", "payload",
    )

    def test_as_chaves_de_topo_sao_as_catorze(self) -> None:
        conexao, cursor = self.admin()
        _emitir(cursor, self.tenant, self.agregado)
        conexao.commit()
        chaves = [
            k
            for (k,) in self.consultar(
                "SELECT jsonb_object_keys(envelope) FROM platform.events_outbox "
                "WHERE agregado_id = %s",
                (self.agregado,),
            )
        ]
        self.assertEqual(sorted(chaves), sorted(self.CHAVES))

    def test_o_envelope_e_coerente_com_as_colunas(self) -> None:
        """As colunas servem o indice e o roteamento; o envelope e o contrato.

        Divergirem era o defeito mais caro possivel aqui: o publicador escreve o
        `events_log` a partir das **colunas** e entrega o **envelope**, e o
        consumidor que se queixasse de ordem olhava para um `seq` que nao era o
        da coluna.
        """
        conexao, cursor = self.admin()
        identificador = _emitir(cursor, self.tenant, self.agregado)
        conexao.commit()
        self.assertEqual(
            self.consultar(
                "SELECT envelope->>'id' = event_id::text, "
                "       envelope->>'tipo' = tipo, "
                "       (envelope->>'versao')::smallint = versao, "
                "       envelope->>'tenant_id' = tenant_id::text, "
                "       envelope->'agregado'->>'tipo' = agregado_tipo, "
                "       envelope->'agregado'->>'id' = agregado_id, "
                "       (envelope->'agregado'->>'seq')::bigint = agregado_seq "
                "  FROM platform.events_outbox WHERE event_id = %s",
                (identificador,),
            ),
            [(True,) * 7],
        )

    def test_as_omissoes_sao_as_do_documento(self) -> None:
        conexao, cursor = self.admin()
        _emitir(cursor, self.tenant, self.agregado)
        conexao.commit()
        self.assertEqual(
            self.consultar(
                "SELECT envelope->>'classe_pii', envelope->'finalidades', "
                "       envelope->>'correlacao_id', envelope->>'causa_id', "
                "       envelope->>'trace_id' "
                "  FROM platform.events_outbox WHERE agregado_id = %s",
                (self.agregado,),
            ),
            [("P0", ["transacao"], None, None, None)],
        )

    def test_tentativas_e_proxima_tentativa_nascem_prontas_a_publicar(self) -> None:
        conexao, cursor = self.admin()
        _emitir(cursor, self.tenant, self.agregado)
        conexao.commit()
        self.assertEqual(
            self.consultar(
                "SELECT tentativas, publicado_at IS NULL, proxima_tentativa_at <= now() "
                "  FROM platform.events_outbox WHERE agregado_id = %s",
                (self.agregado,),
            ),
            [(0, True, True)],
        )


class TestIsolamentoDoOutbox(ComEventos):
    """O `INSERT` do produtor esta sob `WITH CHECK`, e a funcao nao o contorna."""

    def test_a_funcao_e_security_invoker(self) -> None:
        """`SECURITY DEFINER` aqui punha a RLS do outbox a valer zero.

        A funcao escreve no `events_outbox`, que tem `FORCE` e politica
        `tenant_iso`. Corrida como definidor, corria com os privilegios e o
        contexto do **dono** — e o dono, sem contexto, teria o `WITH CHECK` a
        avaliar `NULL`, isto e, a recusar tudo, ou a passar tudo se alguem
        «arranjasse» a politica. O X-05 tambem a recusaria
        (`ci/secdef_allowlist.yaml` esta vazio), e por isso isto e o segundo
        cadeado sobre a mesma porta.
        """
        self.assertEqual(
            self.consultar(
                "SELECT prosecdef FROM pg_proc p "
                "JOIN pg_namespace n ON n.oid = p.pronamespace "
                "WHERE n.nspname = 'platform' AND p.proname = 'evt_emitir'"
            ),
            [(False,)],
        )

    def test_o_produtor_nao_emite_com_o_tenant_de_outro(self) -> None:
        """Isolamento do caminho novo: A nao emite um evento de B."""
        import uuid as _uuid

        outro = str(_uuid.uuid4())
        cursor = self.ligar("app").cursor()
        cursor.execute("SELECT set_config('app.tenant_id', %s, true)", (self.tenant,))
        cursor.fetchone()
        self.assertErroSql(
            PRIVILEGIO_INSUFICIENTE,
            cursor,
            SQL_EMITIR,
            ("order.created", outro, "order", self.agregado, json.dumps({})),
        )

    def test_o_produtor_emite_com_o_seu_tenant(self) -> None:
        """A metade positiva: sem ela, o teste acima passava com a funcao quebrada."""
        cursor = self.ligar("app").cursor()
        cursor.execute("SELECT set_config('app.tenant_id', %s, true)", (self.tenant,))
        cursor.fetchone()
        identificador = _emitir(cursor, self.tenant, self.agregado)
        self.assertEqual(len(identificador), 36)
        cursor.execute(
            "SELECT count(*) FROM platform.events_outbox WHERE tenant_id = %s",
            (self.tenant,),
        )
        self.assertEqual(cursor.fetchone()[0], 1)

    def test_sem_contexto_o_produtor_nao_emite_nada(self) -> None:
        cursor = self.ligar("app").cursor()
        self.assertErroSql(
            PRIVILEGIO_INSUFICIENTE,
            cursor,
            SQL_EMITIR,
            ("order.created", self.tenant, "order", self.agregado, json.dumps({})),
        )

    def test_o_produtor_nao_executa_a_funcao_sem_privilegio(self) -> None:
        """`kamba_resolver` nao emite eventos: o `EXECUTE` e so do `kamba_app`."""
        cursor = self.ligar("resolver").cursor()
        self.assertErroSql(
            PRIVILEGIO_INSUFICIENTE,
            cursor,
            SQL_EMITIR,
            ("order.created", self.tenant, "order", self.agregado, json.dumps({})),
        )


class TestArquivoImutavel(ComBase):
    """`events_log` e imutavel por privilegio, e a particao nao e acessivel."""

    def test_nenhum_papel_de_servico_altera_nem_apaga_o_arquivo(self) -> None:
        for papel in ("kamba_app", "kamba_batch", "kamba_resolver", "kamba_identity"):
            for privilegio in ("UPDATE", "DELETE", "TRUNCATE"):
                with self.subTest(papel=papel, privilegio=privilegio):
                    self.assertEqual(
                        self.consultar(
                            "SELECT has_table_privilege(%s, 'platform.events_log', %s)",
                            (papel, privilegio),
                        ),
                        [(False,)],
                    )

    def test_a_particao_default_nao_tem_privilegio_concedido(self) -> None:
        """Quem acede, acede pelo pai. Uma concessao aqui abria um caminho sem RLS do pai."""
        for papel in ("kamba_app", "kamba_batch", "kamba_resolver", "kamba_identity", "public"):
            for privilegio in ("SELECT", "INSERT", "UPDATE", "DELETE"):
                with self.subTest(papel=papel, privilegio=privilegio):
                    self.assertEqual(
                        self.consultar(
                            "SELECT has_table_privilege(%s, "
                            "'platform.events_log_default', %s)",
                            (papel, privilegio),
                        ),
                        [(False,)],
                    )

    def test_o_publicador_arquiva_pelo_pai_sem_privilegio_na_particao(self) -> None:
        """O `INSERT` pelo pai encaminha para a particao e o privilegio e o do pai.

        E o que permite que a particao nao tenha concessao nenhuma — e tem de
        ser medido, porque se o PostgreSQL verificasse o privilegio na particao
        o publicador nao conseguia arquivar nada.
        """
        import uuid as _uuid

        tenant = str(_uuid.uuid4())
        conexao = self.ligar("batch")
        cursor = conexao.cursor()
        cursor.execute(
            "INSERT INTO platform.events_log "
            "(event_id, tipo, versao, tenant_id, agregado_tipo, agregado_id, "
            " agregado_seq, ocorrido_em, registado_em, classe_pii, envelope) "
            "VALUES (gen_random_uuid(), 'order.created', 1, %s, 'order', 'agg-a1', 1, "
            "now(), now(), 'P1', '{}'::jsonb)",
            (tenant,),
        )
        cursor.execute(
            "SELECT count(*) FROM platform.events_log WHERE tenant_id = %s", (tenant,)
        )
        self.assertEqual(cursor.fetchone()[0], 1)
        # A ligacao de `ComBase` nunca confirma: o `tearDown` reverte.

    def test_a_politica_da_mae_nao_cobre_a_particao_e_a_da_particao_cobre(self) -> None:
        """A medicao que sustenta a exigencia de RLS por particao (achado 10).

        Tres sitios afirmavam «mediu-se contra o PostgreSQL 18.6: a politica do
        pai nao protege quem le a particao directamente», e a medicao nao estava
        no repositorio — so a verificacao do catalogo (`relrowsecurity` e
        contagem de politicas). A revisao adversarial apanhou-o; isto e a
        medicao, com as duas metades.

        Faz-se numa tabela de **ensaio** e numa **so ligacao**, e nao sobre o
        `events_log`: mexer na politica da tabela real pede `ACCESS EXCLUSIVE`
        enquanto outra ligacao a le, e a primeira versao deste teste pendurou o
        gate nos 900 s. Numa transaccao, o DDL do PostgreSQL e transaccional e o
        `tearDown` desfaz tudo.

        Le-se como `kamba_migrator`, que e o dono: tem todos os privilegios e
        esta sujeito a politica pelo `FORCE`. E e o dono que importa, porque
        nenhum papel de servico tem privilegio nas particoes — o X-05 exige-o — e
        por isso o dono e o unico caminho por onde esta leitura e alcancavel.
        """
        import uuid as _uuid

        a, b = str(_uuid.uuid4()), str(_uuid.uuid4())
        cursor = self.ligar("migrator").cursor()
        cursor.execute(
            "CREATE TABLE platform.sonda_particao "
            "(tenant_id uuid NOT NULL, ocorrido_em timestamptz NOT NULL) "
            "PARTITION BY RANGE (ocorrido_em)"
        )
        cursor.execute(
            "CREATE TABLE platform.sonda_particao_p PARTITION OF "
            "platform.sonda_particao DEFAULT"
        )
        # Semeia antes de ligar a RLS: o dono tambem fica sujeito a ela.
        for tenant in (a, b):
            cursor.execute(
                "INSERT INTO platform.sonda_particao VALUES (%s, now())", (tenant,)
            )

        politica = (
            "USING (tenant_id = NULLIF(current_setting('app.tenant_id', true), '')::uuid) "
            "WITH CHECK (tenant_id = NULLIF(current_setting('app.tenant_id', true), '')::uuid)"
        )
        for alvo in ("sonda_particao",):
            cursor.execute(f"ALTER TABLE platform.{alvo} ENABLE ROW LEVEL SECURITY")
            cursor.execute(f"ALTER TABLE platform.{alvo} FORCE ROW LEVEL SECURITY")
            cursor.execute(f"CREATE POLICY tenant_iso ON platform.{alvo} {politica}")
        cursor.execute("SELECT set_config('app.tenant_id', %s, true)", (a,))
        cursor.fetchone()

        def contar(relacao: str) -> int:
            cursor.execute(f"SELECT count(*) FROM platform.{relacao}")
            return int(cursor.fetchone()[0])

        # **A medicao.** Pela mae, a politica filtra; pela particao, nao.
        self.assertEqual(contar("sonda_particao"), 1, "a mae nao filtrou")
        self.assertEqual(
            contar("sonda_particao_p"),
            2,
            "a politica da mae filtrou a leitura directa da particao — entao a "
            "exigencia do X-05 nao se justifica pela razao escrita na revisao",
        )
        # O catalogo diz o mesmo: a particao fica sem nada.
        cursor.execute(
            "SELECT c.relrowsecurity, c.relforcerowsecurity, "
            "(SELECT count(*) FROM pg_policy p WHERE p.polrelid = c.oid) "
            "FROM pg_class c WHERE c.oid = 'platform.sonda_particao_p'::regclass"
        )
        self.assertEqual(tuple(cursor.fetchone()), (False, False, 0))

        # E a outra metade: com a politica **da particao**, a leitura directa
        # passa a filtrar. E isto que `rls.enable_tenant_rls` faz na revisao.
        cursor.execute(
            "ALTER TABLE platform.sonda_particao_p ENABLE ROW LEVEL SECURITY"
        )
        cursor.execute("ALTER TABLE platform.sonda_particao_p FORCE ROW LEVEL SECURITY")
        cursor.execute(
            f"CREATE POLICY tenant_iso ON platform.sonda_particao_p {politica}"
        )
        self.assertEqual(contar("sonda_particao_p"), 1)

    def test_o_with_check_do_arquivo_nao_e_decoracao(self) -> None:
        """Achado 11: nenhum papel sob RLS escreve no arquivo, e o `WITH CHECK`
        ficava declarado e nunca avaliado.

        Quem o exercita e o dono (`kamba_migrator`), que tem privilegio e esta
        sujeito a politica pelo `FORCE`. Com o contexto de A, inserir uma linha
        de B e recusado; inserir uma de A passa. Sem a metade positiva, a
        primeira provava-se com uma politica que recusa tudo.
        """
        import uuid as _uuid

        a, b = str(_uuid.uuid4()), str(_uuid.uuid4())
        cursor = self.ligar("migrator").cursor()
        cursor.execute("SELECT set_config('app.tenant_id', %s, true)", (a,))
        cursor.fetchone()
        inserir = (
            "INSERT INTO platform.events_log "
            "(event_id, tipo, versao, tenant_id, agregado_tipo, agregado_id, "
            " agregado_seq, ocorrido_em, registado_em, classe_pii, envelope) "
            "VALUES (gen_random_uuid(), 'order.created', 1, %s, 'order', "
            "'agg-withcheck', 1, now(), now(), 'P1', '{}'::jsonb)"
        )
        self.assertErroSql(PRIVILEGIO_INSUFICIENTE, cursor, inserir, (b,))
        cursor.execute(inserir, (a,))
        cursor.execute(
            "SELECT count(*) FROM platform.events_log WHERE agregado_id = 'agg-withcheck'"
        )
        self.assertEqual(int(cursor.fetchone()[0]), 1)
        # A ligacao de `ComBase` nunca confirma: o `tearDown` reverte.

    def test_o_with_check_do_outbox_tambem_nao(self) -> None:
        """O mesmo para o `UPDATE` do outbox, que so o `kamba_batch` faz — e ele
        contorna a RLS. Com o dono, a politica e a ultima barreira."""
        import uuid as _uuid

        a, b = str(_uuid.uuid4()), str(_uuid.uuid4())
        semeador = self.ligar("admin")
        semeador.autocommit = True
        semeia = semeador.cursor()
        for tenant in (a, b):
            semeia.execute(
                "INSERT INTO platform.events_outbox "
                "(event_id, tipo, versao, tenant_id, agregado_tipo, agregado_id, "
                " agregado_seq, particao, envelope) "
                "VALUES (gen_random_uuid(), 'order.created', 1, %s, 'order', "
                "'agg-upd', 1, 0, '{}'::jsonb)",
                (tenant,),
            )
        # Ligacao **nova** na limpeza: o `tearDown` de `ComBase` fecha as de
        # `self.ligar` antes de os `addCleanup` correrem, e usar a do semeador
        # dava `connection is closed` (medido).
        self.addCleanup(
            _apagar_depois,
            "DELETE FROM platform.events_outbox WHERE agregado_id = 'agg-upd'",
        )
        cursor = self.ligar("migrator").cursor()
        cursor.execute("SELECT set_config('app.tenant_id', %s, true)", (a,))
        cursor.fetchone()
        # `USING`: o `UPDATE` sobre a linha de B nao encontra linha nenhuma.
        cursor.execute(
            "UPDATE platform.events_outbox SET tentativas = tentativas + 1 "
            " WHERE agregado_id = 'agg-upd' AND tenant_id = %s",
            (b,),
        )
        self.assertEqual(cursor.rowcount, 0, "o dono alterou a linha de B")
        # `WITH CHECK`: nao se oferece uma linha de A a B.
        self.assertErroSql(
            PRIVILEGIO_INSUFICIENTE,
            cursor,
            "UPDATE platform.events_outbox SET tenant_id = %s "
            " WHERE agregado_id = 'agg-upd'",
            (b,),
        )
        # A metade positiva: sobre as suas, o `UPDATE` passa.
        cursor.execute(
            "UPDATE platform.events_outbox SET tentativas = tentativas + 1 "
            " WHERE agregado_id = 'agg-upd'"
        )
        self.assertEqual(cursor.rowcount, 1)

    def test_a_particao_default_e_mesmo_a_default(self) -> None:
        """Sem `DEFAULT`, um `INSERT` com uma data fora das particoes mensais
        rebentava — e o arquivo e o unico sitio onde o evento nao se pode perder."""
        self.assertEqual(
            self.consultar(
                "SELECT pg_get_expr(c.relpartbound, c.oid) FROM pg_class c "
                "WHERE c.oid = 'platform.events_log_default'::regclass"
            ),
            [("DEFAULT",)],
        )


class TestDowngradeDa0004(ComBase):
    """DoD «migracoes reversiveis»: o `downgrade` desfaz, e nao apaga calado.

    A revisao e **aditiva** — antes dela nao havia eventos, pelo que descer nao
    perde nenhum evento que ja estivesse publicado. Mas descer apaga o
    **arquivo**, e o arquivo nao se reconstroi. Por isso o passo so avanca com a
    copia logica pedida, e e isso que se mede aqui.

    Esta classe controla ela propria o estado: faz `downgrade` e deixa a base em
    `head` no fim, seja o resultado qual for.
    """

    @classmethod
    def setUpClass(cls) -> None:
        super().setUpClass()
        cls._livre = ligacao.ligar("admin")
        cls._livre.autocommit = True

    @classmethod
    def tearDownClass(cls) -> None:
        cls._livre.close()
        super().tearDownClass()

    def setUp(self) -> None:
        super().setUp()
        import tempfile
        import uuid as _uuid

        self.tenant = str(_uuid.uuid4())
        self.agregado = f"agg-{_uuid.uuid4().hex}"
        pasta = Path(self.enterContext(tempfile.TemporaryDirectory()))
        self.copia = pasta / "copia.jsonl"
        self.addCleanup(self._repor)

    def _repor(self) -> None:
        import os as _os

        from tests.base import alembic_ok, em_head

        _os.environ.pop("KAMBA_DOWNGRADE_0004_COPIA", None)
        # Subir **e depois** apagar, nao uma coisa ou a outra. A versao
        # anterior so apagava se a base ja estivesse em `head`: um teste que a
        # deixasse noutra revisao era reposto sem limpeza, e as linhas semeadas
        # ficavam para tras. A subscricao `ensaio` sobrevivia, e o teste
        # seguinte rebentava com `duplicate key` — num ficheiro que nao era o
        # culpado. Apanhado ao acrescentar a revisao 0005 (KAM-006), que poe
        # mais um degrau entre a cabeca e a 0003.
        if not em_head():
            alembic_ok("upgrade", "head")
        cursor = self._livre.cursor()
        for tabela in ("events_outbox", "events_log", "evt_agregado_seq"):
            cursor.execute(
                f"DELETE FROM platform.{tabela} WHERE agregado_id LIKE 'agg-%'"
            )
        cursor.execute("DELETE FROM platform.evt_subscricoes WHERE consumer = 'ensaio'")

    def semear(self) -> int:
        cursor = self._livre.cursor()
        for _ in range(3):
            _emitir(cursor, self.tenant, self.agregado)
        cursor.execute(
            "INSERT INTO platform.events_log "
            "(event_id, tipo, versao, tenant_id, agregado_tipo, agregado_id, "
            " agregado_seq, ocorrido_em, registado_em, classe_pii, envelope) "
            "VALUES (gen_random_uuid(), 'order.created', 1, %s, 'order', %s, 1, "
            "now(), now(), 'P1', '{}'::jsonb)",
            (self.tenant, self.agregado),
        )
        cursor.execute(
            "INSERT INTO platform.evt_subscricoes (consumer, tipo, finalidade) "
            "VALUES ('ensaio', 'order.created', 'transacao')"
        )
        return 3

    def tabelas(self) -> tuple[str, ...]:
        cursor = self._livre.cursor()
        cursor.execute(
            "SELECT tablename FROM pg_tables WHERE schemaname = 'platform' ORDER BY 1"
        )
        return tuple(linha[0] for linha in cursor.fetchall())

    def test_com_as_tabelas_vazias_o_downgrade_desce_e_sobe(self) -> None:
        from tests.base import TABELAS, TABELAS_ATE_0003, alembic_ok

        self.assertEqual(self.tabelas(), TABELAS)
        alembic_ok("downgrade", "0003")
        self.assertEqual(self.tabelas(), TABELAS_ATE_0003)
        self.assertFalse(self.copia.exists(), "sem linhas nao se pede copia")
        alembic_ok("upgrade", "head")
        self.assertEqual(self.tabelas(), TABELAS)

    def test_a_funcao_e_as_politicas_desaparecem_e_voltam(self) -> None:
        from tests.base import alembic_ok

        cursor = self._livre.cursor()

        def estado() -> tuple:
            cursor.execute(
                "SELECT (SELECT count(*) FROM pg_proc p "
                "          JOIN pg_namespace n ON n.oid = p.pronamespace "
                "         WHERE n.nspname = 'platform' AND p.proname = 'evt_emitir'), "
                "       (SELECT count(*) FROM pg_policies "
                "         WHERE schemaname = 'platform' "
                "           AND tablename IN ('events_outbox','events_log','events_log_default'))"
            )
            return tuple(cursor.fetchone())

        self.assertEqual(estado(), (1, 3))
        alembic_ok("downgrade", "0003")
        self.assertEqual(estado(), (0, 0))
        alembic_ok("upgrade", "head")
        self.assertEqual(estado(), (1, 3))

    def test_com_linhas_e_sem_copia_o_downgrade_e_recusado(self) -> None:
        from tests.base import TABELAS_ATE_0004, alembic

        self.semear()
        resultado = alembic("downgrade", "0003")
        saida = resultado.stdout + resultado.stderr
        self.assertNotEqual(resultado.returncode, 0, "o passo apagou o arquivo calado")
        self.assertIn("KAMBA_DOWNGRADE_0004_COPIA", saida)
        self.assertIn("events_outbox: 3", saida)
        self.assertIn("events_log: 1", saida)
        # O DDL e transaccional: o que **este** passo ja tinha desfeito voltou.
        # A base fica em 0004 e nao na cabeca: o passo 0005 -> 0004 correu e
        # confirmou antes (uma transaccao por revisao), e por isso a comparacao
        # e com `TABELAS_ATE_0004` (KAM-006).
        self.assertEqual(self.tabelas(), TABELAS_ATE_0004)

    def test_com_copia_o_downgrade_avanca_e_a_copia_tem_tudo(self) -> None:
        import os as _os

        from tests.base import TABELAS_ATE_0003, alembic_ok

        self.semear()
        _os.environ["KAMBA_DOWNGRADE_0004_COPIA"] = str(self.copia)

        alembic_ok("downgrade", "0003")

        self.assertEqual(self.tabelas(), TABELAS_ATE_0003)
        registos = [
            json.loads(linha)
            for linha in self.copia.read_text(encoding="utf-8").splitlines()
        ]
        por_tabela: dict[str, int] = {}
        for registo in registos:
            por_tabela[registo["tabela"]] = por_tabela.get(registo["tabela"], 0) + 1
        self.assertEqual(
            por_tabela,
            {
                "events_outbox": 3,
                "events_log": 1,
                "evt_subscricoes": 1,
                "evt_agregado_seq": 1,
            },
        )

    def test_a_copia_nao_escreve_por_cima_de_uma_anterior(self) -> None:
        import os as _os

        from tests.base import TABELAS_ATE_0004, alembic

        self.semear()
        self.copia.write_text("copia anterior\n", encoding="utf-8")
        _os.environ["KAMBA_DOWNGRADE_0004_COPIA"] = str(self.copia)

        resultado = alembic("downgrade", "0003")

        self.assertNotEqual(resultado.returncode, 0)
        self.assertEqual(self.copia.read_text(encoding="utf-8"), "copia anterior\n")
        # Em 0004, pela razao do teste acima.
        self.assertEqual(self.tabelas(), TABELAS_ATE_0004)


if __name__ == "__main__":
    unittest.main()
