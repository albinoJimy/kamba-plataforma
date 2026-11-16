"""A revisao da lista de espera contra a base: waitlist_entry e onboarding_capacity (KAM-095).

O que so uma base prova, e por isso este ficheiro existe:

1. **Os dominios sao os do codigo**: o `estado` e a `origem` contra o
   `packages/core-ts/src/capacidade/contrato.ts`.
2. **O criterio 1 e da base**: o *trigger* recusa um caso fora de
   `aprovado`/`aguarda_es`, e mil casos de bot dao zero entradas pelo SQL do
   modulo (adversarial a).
3. **A chave FIFO nao se escolhe**: quem insere com um `aprovado_em` antigo leva o
   `fase_at` do caso (adversarial c).
4. **As restricoes**: o convite so em `convidado`, o `concluido_em` so em
   `concluido`, as expiracoes ate duas, o limite acima de 10 so `confirmado`, uma
   linha so de limite.
5. **O SQL do modulo de TypeScript**, executado tal como esta escrito: a
   transicao que deriva o convite do estado, a vaga, a posicao, a cabeca, os
   vencidos e o abandono do caso.
6. **A concorrencia**: vinte trabalhadores a pedir uma vaga dao um convite, com
   a tranca do modulo — e sem ela, mais do que um, que e o que prova que a tranca
   e o que faz a diferenca.
7. **Privilegios e RLS**: o `kamba_app` nao le nada, o lote nao reescreve a
   chave FIFO, ninguem apaga.
8. **O `downgrade`.**
"""

from __future__ import annotations

import hashlib
import re
import threading
import time
import unittest
import uuid
from datetime import datetime, timedelta, timezone
from pathlib import Path

import ligacao
from tests import factories
from tests.base import (
    PRIVILEGIO_INSUFICIENTE,
    VIOLACAO_DE_CHECK,
    VIOLACAO_DE_UNICIDADE,
    ComBase,
    ConsultaDoTypeScript,
    alembic_ok,
    em_head,
    exigir_base_descartavel,
)

RAIZ = Path(__file__).resolve().parents[2]
CONTRATO = RAIZ / "packages" / "core-ts" / "src" / "capacidade" / "contrato.ts"
SQL_TS = RAIZ / "packages" / "core-ts" / "src" / "capacidade" / "sql.ts"
#: Por *glob* e nao pelo numero: o numero e *provisorio* e da-se na integracao.
REVISAO = next((RAIZ / "db" / "migrations" / "versions").glob("*_lista_de_espera.py"))

ENTRADA = "platform.waitlist_entry"
LIMITE = "platform.onboarding_capacity"
CASO = "platform.onboarding_case"

AGORA = datetime(2026, 11, 16, 8, 0, tzinfo=timezone.utc)


def _anterior() -> str:
    """O `down_revision` da revisao, lido dela: muda na integracao, e o ensaio segue-o."""
    achado = re.search(r'^down_revision = "(\d{4})"$', REVISAO.read_text(encoding="utf-8"), re.M)
    assert achado is not None
    return achado.group(1)


def _lista_ts(nome: str) -> tuple[str, ...]:
    texto = CONTRATO.read_text(encoding="utf-8")
    achado = re.search(rf"export const {nome} = \[(.*?)\] as const;", texto, re.S)
    if achado is None:
        raise AssertionError(f"{nome} nao encontrado em {CONTRATO.name}")
    return tuple(re.findall(r'"([a-z0-9_]+)"', achado.group(1)))


def _dominio(cursor, restricao: str) -> tuple[str, ...]:
    cursor.execute("SELECT pg_get_constraintdef(oid) FROM pg_constraint WHERE conname = %s", (restricao,))
    return tuple(sorted(re.findall(r"'([a-z0-9_]+)'", cursor.fetchone()[0])))


def caso(cursor, fase: str = "aguarda_es") -> tuple[str, str]:
    """Um caso minimo na `fase`. Devolve `(id, tenant_id)`."""
    cursor.execute(
        f"INSERT INTO {CASO} (fase, origem, nome_negocio, categoria_declarada, nif_enc, nif_hmac, "
        "phone_enc, phone_hmac) VALUES (%s, 'convite', 'negocio de ensaio', 'moda', '\\x01', %s, '\\x02', %s) "
        "RETURNING id::text, tenant_id::text",
        (fase, hashlib.sha256(uuid.uuid4().bytes).digest(), hashlib.sha256(uuid.uuid4().bytes).digest()),
    )
    linha = cursor.fetchone()
    return linha[0], linha[1]


def inserir(cursor, onboarding_id: str) -> list:
    q = ConsultaDoTypeScript("SQL_INSERIR", SQL_TS)
    cursor.execute(q.sql, q.args(onboarding_id))
    return cursor.fetchall()


def transitar(cursor, onboarding_id: str, de: str, para: str, *, na_fila_desde=None, convidado_em=None,
              tentativas=None, convite_hash=None, convite_expira_em=None, concluido_em=None) -> int:
    q = ConsultaDoTypeScript("SQL_TRANSITAR", SQL_TS)
    cursor.execute(q.sql, q.args(onboarding_id, de, para, na_fila_desde, convidado_em, tentativas,
                                 convite_hash, convite_expira_em, concluido_em))
    return cursor.rowcount


def apagar(*ids: str) -> None:
    """Apaga, com `commit`, as entradas e os casos que um ensaio deixou escritos."""
    conexao = ligacao.ligar("admin")
    try:
        c = conexao.cursor()
        c.execute(f"DELETE FROM {ENTRADA} WHERE onboarding_id = ANY(%s::uuid[])", (list(ids),))
        c.execute(f"DELETE FROM {CASO} WHERE id = ANY(%s::uuid[])", (list(ids),))
        conexao.commit()
    finally:
        conexao.close()


def contar(cursor, nome: str, *valores) -> int:
    q = ConsultaDoTypeScript(nome, SQL_TS)
    cursor.execute(q.sql, q.args(*valores))
    return int(cursor.fetchone()[0])


class TestDominios(ComBase):
    def test_as_duas_tabelas_existem_em_head(self) -> None:
        linhas = self.consultar(
            "SELECT tablename::text FROM pg_tables WHERE schemaname = 'platform' "
            "AND tablename IN ('waitlist_entry', 'onboarding_capacity') ORDER BY 1"
        )
        self.assertEqual(linhas, [("onboarding_capacity",), ("waitlist_entry",)])

    def test_os_dominios_sao_os_do_contrato(self) -> None:
        cursor = self.ligar("admin").cursor()
        self.assertEqual(_dominio(cursor, "waitlist_entry_estado_ck"), tuple(sorted(_lista_ts("ESTADOS_DA_ENTRADA"))))
        self.assertEqual(_dominio(cursor, "onboarding_capacity_origem_ck"), tuple(sorted(_lista_ts("ORIGENS_DO_LIMITE"))))

    def test_o_limite_nasce_com_o_10_confirmado(self) -> None:
        self.assertEqual(
            [tuple(l[:2]) for l in self.consultar(f"SELECT es_max_por_7d, origem, fundamento FROM {LIMITE}")],
            [(10, "confirmado")],
        )


class TestEntrada(ComBase):
    def setUp(self) -> None:
        super().setUp()
        self.cursor = self.ligar("admin").cursor()

    def test_so_casos_aprovados_entram_pelo_sql_do_modulo(self) -> None:
        for fase in ("aprovado", "aguarda_es"):
            with self.subTest(fase=fase):
                onb, _ = caso(self.cursor, fase)
                self.assertEqual(len(inserir(self.cursor, onb)), 1)
                self.assertEqual(len(inserir(self.cursor, onb)), 0, "a repeticao nao cria segunda linha")

    def test_adversarial_a_mil_registos_de_bot_dao_zero_entradas(self) -> None:
        fases = ("registo", "otp_pendente", "kyc_pendente", "em_revisao", "rejeitado")
        ids = [caso(self.cursor, fases[i % len(fases)])[0] for i in range(1000)]
        for onb in ids:
            self.assertEqual(list(inserir(self.cursor, onb)), [])
        self.cursor.execute(f"SELECT count(*) FROM {ENTRADA} WHERE onboarding_id = ANY(%s::uuid[])", (ids,))
        self.assertEqual(self.cursor.fetchone()[0], 0)

    def test_o_trigger_recusa_uma_insercao_directa_de_caso_nao_aprovado(self) -> None:
        onb, tenant = caso(self.cursor, "kyc_pendente")
        self.assertErroSql(VIOLACAO_DE_CHECK, self.cursor,
                           f"INSERT INTO {ENTRADA} (onboarding_id, tenant_id, aprovado_em, na_fila_desde) "
                           "VALUES (%s, %s, now(), now())", (onb, tenant))

    def test_adversarial_c_a_chave_fifo_e_o_fase_at_do_caso_e_nao_a_de_quem_insere(self) -> None:
        onb, tenant = caso(self.cursor)
        self.cursor.execute(
            f"INSERT INTO {ENTRADA} (onboarding_id, tenant_id, aprovado_em, na_fila_desde, estado, tentativas) "
            "VALUES (%s, %s, '2000-01-01', '2000-01-01', 'concluido', 2)", (onb, tenant))
        self.cursor.execute(
            f"SELECT e.aprovado_em = c.fase_at, e.na_fila_desde = c.fase_at, e.estado, e.tentativas "
            f"FROM {ENTRADA} e JOIN {CASO} c ON c.id = e.onboarding_id WHERE e.onboarding_id = %s", (onb,))
        self.assertEqual(tuple(self.cursor.fetchone()), (True, True, "aguardando", 0))

    def test_fifo_pelo_aprovado_em_quem_foi_aprovado_antes_fica_a_frente_mesmo_entrando_depois(self) -> None:
        """O duplo em memoria usa o instante de entrada; a base usa o `fase_at`. Mede-se aqui.

        O `fase_at` e o `now()` da transaccao que insere o caso, pelo que os dois
        casos nascem em transaccoes separadas: o antigo primeiro, o recente depois.
        """
        ids = []
        for _ in range(2):
            conexao = ligacao.ligar("admin")
            try:
                ids.append(caso(conexao.cursor())[0])
                conexao.commit()
            finally:
                conexao.close()
        self.addCleanup(apagar, *ids)
        antigo, recente = ids
        lote = self.ligar("batch").cursor()
        inserir(lote, recente)
        inserir(lote, antigo)
        self.assertEqual(contar(lote, "SQL_A_FRENTE", recente) - contar(lote, "SQL_A_FRENTE", antigo), 1,
                         "o aprovado antes fica a frente, embora tenha entrado na fila depois")

    def test_o_caso_de_um_com_o_tenant_de_outro_e_recusado(self) -> None:
        onb, _ = caso(self.cursor)
        _, outro = caso(self.cursor)
        self.assertErroSql("23503", self.cursor,
                           f"INSERT INTO {ENTRADA} (onboarding_id, tenant_id) VALUES (%s, %s)", (onb, outro))


class TestRestricoes(ComBase):
    def setUp(self) -> None:
        super().setUp()
        self.cursor = self.ligar("admin").cursor()
        self.onb, _ = caso(self.cursor)
        inserir(self.cursor, self.onb)

    def test_o_convite_so_existe_em_convidado_e_e_unico(self) -> None:
        self.assertErroSql(VIOLACAO_DE_CHECK, self.cursor,
                           f"UPDATE {ENTRADA} SET convite_hash = %s WHERE onboarding_id = %s",
                           (b"\x01" * 32, self.onb))
        self.assertErroSql(VIOLACAO_DE_CHECK, self.cursor,
                           f"UPDATE {ENTRADA} SET estado = 'convidado', convidado_em = now() WHERE onboarding_id = %s",
                           (self.onb,))
        self.assertErroSql(VIOLACAO_DE_CHECK, self.cursor,
                           f"UPDATE {ENTRADA} SET estado = 'convidado', convite_hash = %s, convidado_em = now(), "
                           "convite_expira_em = now() - interval '1 hour' WHERE onboarding_id = %s",
                           (b"\x01" * 32, self.onb))
        self.assertErroSql(VIOLACAO_DE_CHECK, self.cursor,
                           f"UPDATE {ENTRADA} SET estado = 'convidado', convite_hash = %s, convidado_em = now(), "
                           "convite_expira_em = now() + interval '1 hour' WHERE onboarding_id = %s",
                           (b"\x01" * 31, self.onb))
        h = hashlib.sha256(b"convite").digest()
        self.assertEqual(transitar(self.cursor, self.onb, "aguardando", "convidado", convite_hash=h,
                                   convidado_em=AGORA, convite_expira_em=AGORA + timedelta(hours=48)), 1)
        outro, _ = caso(self.cursor)
        inserir(self.cursor, outro)
        self.assertErroSql(VIOLACAO_DE_UNICIDADE, self.cursor,
                           f"UPDATE {ENTRADA} SET estado = 'convidado', convite_hash = %s, convidado_em = now(), "
                           "convite_expira_em = now() + interval '1 hour' WHERE onboarding_id = %s", (h, outro))

    def test_o_concluido_em_so_em_concluido_e_as_tentativas_ate_duas(self) -> None:
        self.assertErroSql(VIOLACAO_DE_CHECK, self.cursor,
                           f"UPDATE {ENTRADA} SET concluido_em = now() WHERE onboarding_id = %s", (self.onb,))
        self.assertErroSql(VIOLACAO_DE_CHECK, self.cursor,
                           f"UPDATE {ENTRADA} SET estado = 'concluido' WHERE onboarding_id = %s", (self.onb,))
        self.assertErroSql(VIOLACAO_DE_CHECK, self.cursor,
                           f"UPDATE {ENTRADA} SET tentativas = 3 WHERE onboarding_id = %s", (self.onb,))
        self.assertErroSql(VIOLACAO_DE_CHECK, self.cursor,
                           f"UPDATE {ENTRADA} SET estado = 'pronto' WHERE onboarding_id = %s", (self.onb,))

    def test_acima_de_10_o_limite_exige_confirmado_e_ha_uma_linha_so(self) -> None:
        self.assertErroSql(VIOLACAO_DE_CHECK, self.cursor,
                           f"UPDATE {LIMITE} SET es_max_por_7d = 200, origem = 'nao_verificado'")
        self.assertErroSql(VIOLACAO_DE_CHECK, self.cursor, f"UPDATE {LIMITE} SET es_max_por_7d = -1")
        self.assertErroSql(VIOLACAO_DE_CHECK, self.cursor, f"UPDATE {LIMITE} SET fundamento = ''")
        self.cursor.execute(f"UPDATE {LIMITE} SET es_max_por_7d = 5, origem = 'nao_verificado', fundamento = 'ensaio'")
        self.cursor.execute(f"UPDATE {LIMITE} SET es_max_por_7d = 200, origem = 'confirmado', fundamento = 'ensaio'")
        self.assertErroSql(VIOLACAO_DE_CHECK, self.cursor,
                           f"INSERT INTO {LIMITE} (unica, es_max_por_7d, origem, fundamento) VALUES (false, 1, 'confirmado', 'x')")
        self.assertErroSql(VIOLACAO_DE_UNICIDADE, self.cursor,
                           f"INSERT INTO {LIMITE} (es_max_por_7d, origem, fundamento) VALUES (1, 'confirmado', 'x')")


class TestConsultas(ComBase):
    """O SQL do `capacidade/sql.ts`, tal como esta escrito."""

    def setUp(self) -> None:
        super().setUp()
        self.cursor = self.ligar("batch").cursor()

    def _entrar(self) -> str:
        admin = self.ligar("admin")
        onb, _ = caso(admin.cursor())
        admin.commit()
        self.addCleanup(apagar, onb)
        self.assertEqual(len(inserir(self.cursor, onb)), 1)
        return onb

    def test_a_transicao_deriva_o_convite_e_o_concluido_do_estado(self) -> None:
        onb = self._entrar()
        h = hashlib.sha256(b"x").digest()
        self.assertEqual(transitar(self.cursor, onb, "aguardando", "convidado", convite_hash=h,
                                   convidado_em=AGORA, convite_expira_em=AGORA + timedelta(hours=48)), 1)
        self.assertEqual(transitar(self.cursor, onb, "aguardando", "concluido", concluido_em=AGORA), 0,
                         "compare-and-set: de um estado que ja nao e o actual, nada")
        # O convite apaga-se ao sair de convidado, sem quem chama o dizer.
        self.assertEqual(transitar(self.cursor, onb, "convidado", "concluido", concluido_em=AGORA), 1)
        self.cursor.execute(f"SELECT convite_hash, convite_expira_em, convidado_em = %s, concluido_em = %s "
                            f"FROM {ENTRADA} WHERE onboarding_id = %s", (AGORA, AGORA, onb))
        self.assertEqual(tuple(self.cursor.fetchone()), (None, None, True, True))
        self.assertEqual(transitar(self.cursor, onb, "concluido", "aguardando"), 1)
        self.cursor.execute(f"SELECT concluido_em FROM {ENTRADA} WHERE onboarding_id = %s", (onb,))
        self.assertIsNone(self.cursor.fetchone()[0])

    def test_vaga_posicao_cabeca_e_vencidos(self) -> None:
        a, b, c = self._entrar(), self._entrar(), self._entrar()
        # A ordem e (na_fila_desde, onboarding_id): fixa-se a do ensaio, na
        # mesma transaccao (as entradas ainda nao tem `commit`).
        for i, onb in enumerate((a, b, c)):
            self.cursor.execute(f"UPDATE {ENTRADA} SET na_fila_desde = %s WHERE onboarding_id = %s",
                                (AGORA - timedelta(days=10) + timedelta(seconds=i), onb))
        self.assertEqual(contar(self.cursor, "SQL_A_FRENTE", c) - contar(self.cursor, "SQL_A_FRENTE", a), 2)
        q = ConsultaDoTypeScript("SQL_CABECA", SQL_TS)
        self.cursor.execute(q.sql, q.args())
        cabeca = self.cursor.fetchone()[0]
        self.cursor.execute(f"SELECT onboarding_id::text FROM {ENTRADA} WHERE estado = 'aguardando' "
                            "ORDER BY na_fila_desde, onboarding_id LIMIT 1")
        self.assertEqual(str(cabeca), self.cursor.fetchone()[0])
        antes = contar(self.cursor, "SQL_OCUPADAS", AGORA - timedelta(days=7), AGORA)
        transitar(self.cursor, a, "aguardando", "concluido", concluido_em=AGORA - timedelta(days=1))
        transitar(self.cursor, b, "aguardando", "convidado", convite_hash=hashlib.sha256(b"b").digest(),
                  convidado_em=AGORA - timedelta(days=3), convite_expira_em=AGORA - timedelta(hours=1))
        self.assertEqual(contar(self.cursor, "SQL_OCUPADAS", AGORA - timedelta(days=7), AGORA), antes + 1,
                         "o concluido na janela conta; o convite vencido nao")
        self.assertEqual(contar(self.cursor, "SQL_A_FRENTE", c), contar(self.cursor, "SQL_A_FRENTE", a),
                         "so os aguardando contam a frente")
        q = ConsultaDoTypeScript("SQL_VENCIDOS", SQL_TS)
        self.cursor.execute(q.sql, q.args(AGORA))
        self.assertIn(b, {str(l[0]) for l in self.cursor.fetchall()})

    def test_o_abandono_so_mexe_num_caso_da_fila(self) -> None:
        onb = self._entrar()
        q = ConsultaDoTypeScript("SQL_ABANDONAR_CASO", SQL_TS)
        self.cursor.execute(q.sql, q.args(onb))
        self.cursor.execute(f"SELECT fase FROM {CASO} WHERE id = %s", (onb,))
        self.assertEqual(self.cursor.fetchone()[0], "abandonado")
        admin = self.ligar("admin").cursor()
        activo, _ = caso(admin, "activo")
        admin.execute(q.sql, q.args(activo))
        admin.execute(f"SELECT fase FROM {CASO} WHERE id = %s", (activo,))
        self.assertEqual(admin.fetchone()[0], "activo")

    def test_o_limite_le_se_pelo_lote(self) -> None:
        q = ConsultaDoTypeScript("SQL_LIMITE", SQL_TS)
        self.cursor.execute(q.sql, q.args())
        self.assertEqual(self.cursor.fetchone()[1], "confirmado")


class TestConcorrencia(ComBase):
    """Vinte trabalhadores e uma vaga (criterio 9, e o «20 a pedir 1 vaga» dos testes).

    Duas corridas, cada uma com o que o modulo faz numa transaccao, e uma pausa
    entre ler e escrever para que as vinte leituras caiam na mesma janela:

    * **promover** — vinte a convidar a cabeca de uma fila de vinte e um: um
      convite;
    * **reservar** — vinte casos novos a entrar e a pedir a vaga ao mesmo tempo:
      uma vaga. **E corre outra vez sem o `SQL_TRANCAR`**, e entao da mais do que
      uma: cada transaccao nao ve a insercao das outras, todas se julgam a cabeca.
      E esse controlo que prova que o resultado vem da tranca e nao do acaso — na
      corrida do promover, o *compare-and-set* sobre a mesma cabeca ja bastava, e
      um controlo ali nao mediria nada.
    """

    def _casos(self, n: int, *, na_fila: bool) -> list[str]:
        conexao = ligacao.ligar("admin")
        ids: list[str] = []
        try:
            c = conexao.cursor()
            c.execute(f"DELETE FROM {ENTRADA}")
            for i in range(n):
                onb, _ = caso(c)
                ids.append(onb)
                if na_fila:
                    inserir(c, onb)
                    c.execute(f"UPDATE {ENTRADA} SET na_fila_desde = %s WHERE onboarding_id = %s",
                              (AGORA - timedelta(days=1) + timedelta(seconds=i), onb))
            c.execute(f"UPDATE {LIMITE} SET es_max_por_7d = 1")
            conexao.commit()
        finally:
            conexao.close()
        self.addCleanup(apagar, *ids)
        self.addCleanup(self._repor_limite)
        return ids

    def _repor_limite(self) -> None:
        conexao = ligacao.ligar("admin")
        try:
            conexao.cursor().execute(f"UPDATE {LIMITE} SET es_max_por_7d = 10")
            conexao.commit()
        finally:
            conexao.close()

    def _correr(self, trabalho, n: int = 20) -> None:
        erros: list[BaseException] = []

        def fio(i: int) -> None:
            conexao = ligacao.ligar("batch")
            try:
                trabalho(conexao.cursor(), i)
                conexao.commit()
            except BaseException as erro:  # noqa: BLE001 - devolvido ao ensaio
                erros.append(erro)
                conexao.rollback()
            finally:
                conexao.close()

        fios = [threading.Thread(target=fio, args=(i,)) for i in range(n)]
        for f in fios:
            f.start()
        for f in fios:
            f.join(timeout=120)
        self.assertEqual(erros, [])

    def _contar(self, estado: str) -> int:
        conexao = ligacao.ligar("admin")
        try:
            c = conexao.cursor()
            c.execute(f"SELECT count(*) FROM {ENTRADA} WHERE estado = %s", (estado,))
            return int(c.fetchone()[0])
        finally:
            conexao.close()

    @staticmethod
    def _vaga(c) -> int:
        limite = ConsultaDoTypeScript("SQL_LIMITE", SQL_TS)
        c.execute(limite.sql, limite.args())
        maximo = int(c.fetchone()[0])
        return maximo - contar(c, "SQL_OCUPADAS", AGORA - timedelta(days=7), AGORA)

    def test_promover_vinte_trabalhadores_uma_vaga_um_convite(self) -> None:
        self._casos(21, na_fila=True)
        tranca = ConsultaDoTypeScript("SQL_TRANCAR", SQL_TS)
        cabeca = ConsultaDoTypeScript("SQL_CABECA", SQL_TS)

        def promover(c, i: int) -> None:
            c.execute(tranca.sql, tranca.args())
            vaga = self._vaga(c)
            c.execute(cabeca.sql, cabeca.args())
            linha = c.fetchone()
            time.sleep(0.05)
            if vaga > 0 and linha is not None:
                transitar(c, str(linha[0]), "aguardando", "convidado", convidado_em=AGORA,
                          convite_hash=hashlib.sha256(f"convite-{i}".encode()).digest(),
                          convite_expira_em=AGORA + timedelta(hours=48))

        self._correr(promover)
        self.assertEqual(self._contar("convidado"), 1)

    def _reservar(self, trancar: bool) -> int:
        ids = self._casos(20, na_fila=False)
        tranca = ConsultaDoTypeScript("SQL_TRANCAR", SQL_TS)

        def reservar(c, i: int) -> None:
            if trancar:
                c.execute(tranca.sql, tranca.args())
            inserir(c, ids[i])
            vaga = self._vaga(c)
            frente = contar(c, "SQL_A_FRENTE", ids[i])
            time.sleep(0.2)
            if vaga > 0 and frente == 0:
                transitar(c, ids[i], "aguardando", "concluido", concluido_em=AGORA)

        self._correr(reservar)
        return self._contar("concluido")

    def test_reservar_vinte_casos_novos_uma_vaga_uma_concedida(self) -> None:
        self.assertEqual(self._reservar(trancar=True), 1)

    def test_sem_a_tranca_a_mesma_reserva_concede_mais_do_que_uma(self) -> None:
        self.assertGreater(self._reservar(trancar=False), 1)


class TestPrivilegios(ComBase):
    def test_a_aplicacao_nao_le_nem_a_fila_nem_o_limite(self) -> None:
        app = self.ligar("app").cursor()
        factories.contexto(app, str(uuid.uuid4()))
        for alvo in (ENTRADA, LIMITE):
            with self.subTest(alvo=alvo):
                self.assertErroSql(PRIVILEGIO_INSUFICIENTE, app, f"SELECT 1 FROM {alvo}")

    def test_o_lote_nao_reescreve_a_chave_fifo_nem_apaga_nem_muda_o_limite(self) -> None:
        admin = self.ligar("admin").cursor()
        onb, _ = caso(admin)
        inserir(admin, onb)
        lote = self.ligar("batch").cursor()
        for coluna, valor in (("aprovado_em", "now()"), ("tenant_id", "gen_random_uuid()"),
                              ("criado_em", "now()")):
            with self.subTest(coluna=coluna):
                self.assertErroSql(PRIVILEGIO_INSUFICIENTE, lote,
                                   f"UPDATE {ENTRADA} SET {coluna} = {valor} WHERE onboarding_id = %s", (onb,))
        self.assertErroSql(PRIVILEGIO_INSUFICIENTE, lote, f"DELETE FROM {ENTRADA} WHERE onboarding_id = %s", (onb,))
        self.assertErroSql(PRIVILEGIO_INSUFICIENTE, lote, f"UPDATE {LIMITE} SET es_max_por_7d = 11")

    def test_a_rls_esta_forcada_na_fila(self) -> None:
        [(ligada, forcada)] = self.consultar(
            "SELECT relrowsecurity, relforcerowsecurity FROM pg_class WHERE oid = %s::regclass", (ENTRADA,))
        self.assertEqual((ligada, forcada), (True, True))

    def test_a_auditoria_le_o_seu_tenant_e_nao_o_dos_outros(self) -> None:
        conexao = ligacao.ligar("admin")
        try:
            c = conexao.cursor()
            onb, tenant = caso(c)
            inserir(c, onb)
            conexao.commit()
        finally:
            conexao.close()
        self.addCleanup(apagar, onb)
        auditoria = self.ligar("audit").cursor()
        for contexto, esperado in ((tenant, 1), (str(uuid.uuid4()), 0), (None, 0)):
            with self.subTest(contexto=contexto):
                factories.contexto(auditoria, contexto)
                auditoria.execute(f"SELECT count(*) FROM {ENTRADA} WHERE onboarding_id = %s", (onb,))
                self.assertEqual(auditoria.fetchone()[0], esperado)


class TestDowngradeDaListaDeEspera(unittest.TestCase):
    """Desce pelo numero da revisao anterior, lido da revisao, e volta.

    **Nao exige `em_head()` no meio**, pela licao do KAM-089: com outra revisao
    por cima, o Alembic desce-a primeiro.
    """

    @classmethod
    def setUpClass(cls) -> None:
        exigir_base_descartavel()
        if not em_head():
            alembic_ok("upgrade", "head")

    @classmethod
    def tearDownClass(cls) -> None:
        if not em_head():
            alembic_ok("upgrade", "head")

    def _tabelas(self) -> int:
        conexao = ligacao.ligar("admin")
        try:
            c = conexao.cursor()
            c.execute("SELECT count(*) FROM pg_tables WHERE schemaname = 'platform' "
                      "AND tablename IN ('waitlist_entry', 'onboarding_capacity')")
            n = int(c.fetchone()[0])
            c.execute("SELECT count(*) FROM pg_proc WHERE proname = 'waitlist_entry_do_caso'")
            return n + int(c.fetchone()[0])
        finally:
            conexao.close()

    def test_desce_e_volta(self) -> None:
        alembic_ok("downgrade", _anterior())
        try:
            self.assertEqual(self._tabelas(), 0)
        finally:
            alembic_ok("upgrade", "head")
        self.assertEqual(self._tabelas(), 3)


if __name__ == "__main__":
    unittest.main()
