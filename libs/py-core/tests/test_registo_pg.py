"""O recolector do registo do PostgreSQL (KAM-225): o predicado, a leitura e a rota.

As linhas de `UPDATE_DO_APP` e `SELECT_DO_MOTIVO` sao as que o PostgreSQL 18.6 da
imagem do compose escreveu, com o `jsonlog` ligado, quando uma ligacao directa
do `kamba_app` tentou mudar o tecto e ler o motivo (`docs/evidencia/KAM-225.md`;
so se encurtou o `statement`). O ensaio contra a pilha esta em
`db/ensaio_registo_pg.py`; aqui fica o contrato do processo, sem rede nem base.
"""

from __future__ import annotations

import json
import tempfile
import threading
import unittest
import urllib.request
from pathlib import Path

from kamba_core.registo_pg import leitor as lt
from kamba_core.registo_pg import processo as pr
from kamba_core.registo_pg.metricas import METRICA_TECTO_RECUSADO, MetricasDoRegistoPg

UPDATE_DO_APP = (
    b'{"timestamp":"2026-11-22 08:55:36.019 UTC","user":"kamba_app","dbname":"postgres","pid":89,'
    b'"remote_host":"127.0.0.1","remote_port":54442,"session_id":"6b02ae08.59","line_num":1,'
    b'"ps":"UPDATE","session_start":"2026-11-22 08:55:36 UTC","vxid":"2/2","txid":0,'
    b'"error_severity":"ERROR","state_code":"42501","message":"permission denied for table trust_level",'
    b'"statement":"update platform.trust_level set nivel = 3","application_name":"psql",'
    b'"backend_type":"client backend","query_id":0}'
)
SELECT_DO_MOTIVO = UPDATE_DO_APP.replace(b'"ps":"UPDATE"', b'"ps":"SELECT"').replace(
    b"update platform.trust_level set nivel = 3", b"select motivo from platform.trust_level"
)
PRONTO = (
    b'{"timestamp":"2026-11-22 08:55:34.004 UTC","pid":1,"session_id":"6b02ae05.1","line_num":6,'
    b'"session_start":"2026-11-22 08:55:33 UTC","txid":0,"error_severity":"LOG",'
    b'"message":"database system is ready to accept connections","backend_type":"postmaster","query_id":0}'
)


def _com(linha: bytes, **trocas: str) -> bytes:
    registo = json.loads(linha)
    registo.update(trocas)
    return json.dumps(registo, separators=(",", ":")).encode("utf-8")


class TestPredicado(unittest.TestCase):
    def _conta(self, linha: bytes, truncada: bool = False) -> bool:
        return lt.e_recusa_no_tecto(lt.campos(linha, truncada))

    def test_a_escrita_e_a_leitura_do_kamba_app_contam(self) -> None:
        self.assertTrue(self._conta(UPDATE_DO_APP))
        self.assertTrue(self._conta(SELECT_DO_MOTIVO))

    def test_le_so_os_tres_campos(self) -> None:
        """O `statement` tem o texto da consulta, e nao sai da leitura."""
        self.assertEqual(
            lt.campos(UPDATE_DO_APP),
            {"user": "kamba_app", "state_code": "42501", "message": "permission denied for table trust_level"},
        )

    def test_qualquer_papel_que_nao_seja_o_lote_conta(self) -> None:
        for papel in ("kamba_identity", "kamba_agr", "kamba", "kamba_batch_falso"):
            with self.subTest(papel=papel):
                self.assertTrue(self._conta(_com(UPDATE_DO_APP, user=papel)))

    def test_o_controlo_nao_conta(self) -> None:
        casos = {
            "o lote": _com(UPDATE_DO_APP, user="kamba_batch"),
            "outro sqlstate": _com(UPDATE_DO_APP, state_code="23505"),
            "42501 noutra tabela": _com(UPDATE_DO_APP, message="permission denied for table audit_log"),
            "o nome dentro de outro": _com(UPDATE_DO_APP, message="permission denied for table trust_levels"),
            "linha sem sqlstate": PRONTO,
            "nao e json": b"permission denied for table trust_level 42501",
            "json que nao e objecto": b'["42501", "trust_level"]',
        }
        for nome, linha in casos.items():
            with self.subTest(caso=nome):
                self.assertFalse(self._conta(linha))

    def test_a_mensagem_traduzida_conta_pelo_nome_da_tabela(self) -> None:
        self.assertTrue(self._conta(_com(UPDATE_DO_APP, message="permissao negada para tabela trust_level")))

    def test_a_cabeca_de_uma_linha_comprida_le_se_por_expressao(self) -> None:
        """O `statement` e de quem tem a credencial, e nao pode esconder a recusa."""
        enorme = UPDATE_DO_APP.replace(b"set nivel = 3", b"set nivel = 3 -- " + b"x" * (3 * lt.LINHA_MAXIMA))
        cabeca = enorme[: lt.LINHA_MAXIMA]
        self.assertEqual(lt.campos(cabeca), {})  # nao e JSON
        self.assertTrue(self._conta(cabeca, truncada=True))
        self.assertFalse(self._conta(_com(enorme, user="kamba_batch")[: lt.LINHA_MAXIMA], truncada=True))

    def test_uma_chave_dentro_de_um_valor_nao_casa(self) -> None:
        """As aspas num valor vem escapadas: o texto de uma consulta nao forja campos."""
        forjada = (
            b'{"user":"kamba_batch","statement":"select \\"state_code\\":\\"42501\\", '
            b'\\"message\\":\\"trust_level\\""'
        )
        self.assertEqual(lt.campos(forjada, truncada=True), {"user": "kamba_batch"})
        self.assertFalse(lt.e_recusa_no_tecto(lt.campos(forjada, truncada=True)))

    def test_um_valor_escapado_le_se_inteiro(self) -> None:
        linha = b'{"user":"kamba\\u005fapp","state_code":"42501","message":"permission denied for table trust_level"'
        self.assertEqual(lt.campos(linha, truncada=True)["user"], "kamba_app")


class ComPasta(unittest.TestCase):
    def setUp(self) -> None:
        self._tmp = tempfile.TemporaryDirectory()
        self.pasta = Path(self._tmp.name)
        self.addCleanup(self._tmp.cleanup)

    def escrever(self, nome: str, dados: bytes, modo: str = "ab") -> None:
        with open(self.pasta / nome, modo) as f:
            f.write(dados)

    def lidas(self, seguidor: lt.Seguidor) -> list[tuple[bytes, bool]]:
        return list(seguidor.linhas())


class TestSeguidor(ComPasta):
    def test_comeca_no_fim_e_le_so_o_que_vem_depois(self) -> None:
        self.escrever("postgresql-08.json", UPDATE_DO_APP + b"\n")
        seguidor = lt.Seguidor(self.pasta)
        self.assertEqual(self.lidas(seguidor), [])
        self.escrever("postgresql-08.json", SELECT_DO_MOTIVO + b"\n")
        self.assertEqual(self.lidas(seguidor), [(SELECT_DO_MOTIVO, False)])
        self.assertEqual(self.lidas(seguidor), [])

    def test_uma_linha_a_meio_espera_pelo_fim(self) -> None:
        self.escrever("postgresql-08.json", PRONTO + b"\n")
        seguidor = lt.Seguidor(self.pasta)
        self.escrever("postgresql-08.json", UPDATE_DO_APP[:50])
        self.assertEqual(self.lidas(seguidor), [])
        self.escrever("postgresql-08.json", UPDATE_DO_APP[50:] + b"\n")
        self.assertEqual(self.lidas(seguidor), [(UPDATE_DO_APP, False)])

    def test_no_arranque_a_meio_de_uma_linha_o_fim_dela_descarta_se(self) -> None:
        self.escrever("postgresql-08.json", PRONTO + b"\n" + UPDATE_DO_APP[:50])
        seguidor = lt.Seguidor(self.pasta)
        self.escrever("postgresql-08.json", UPDATE_DO_APP[50:] + b"\n" + SELECT_DO_MOTIVO + b"\n")
        self.assertEqual(self.lidas(seguidor), [(SELECT_DO_MOTIVO, False)])

    def test_um_ficheiro_novo_le_se_desde_o_inicio(self) -> None:
        self.escrever("postgresql-08.json", PRONTO + b"\n")
        seguidor = lt.Seguidor(self.pasta)
        self.escrever("postgresql-09.json", UPDATE_DO_APP + b"\n")
        self.assertEqual(self.lidas(seguidor), [(UPDATE_DO_APP, False)])

    def test_o_stderr_do_arranque_nao_se_le(self) -> None:
        self.escrever("postgresql-08.json", PRONTO + b"\n")
        seguidor = lt.Seguidor(self.pasta)
        self.escrever("postgresql-08.log", UPDATE_DO_APP + b"\n")
        self.assertEqual(self.lidas(seguidor), [])

    def test_a_rotacao_que_trunca_e_reescreve_le_se_do_zero(self) -> None:
        """24 h depois o mesmo nome volta, truncado, com uma cabeca nova e maior."""
        self.escrever("postgresql-08.json", PRONTO + b"\n")
        seguidor = lt.Seguidor(self.pasta)
        self.escrever("postgresql-08.json", _com(PRONTO, timestamp="2026-11-23 08:00:00.001 UTC") + b"\n"
                      + UPDATE_DO_APP + b"\n", modo="wb")
        self.assertEqual([l for l, _ in self.lidas(seguidor)][-1], UPDATE_DO_APP)

    def test_um_ficheiro_que_encolheu_le_se_do_zero(self) -> None:
        self.escrever("postgresql-08.json", PRONTO + b"\n" + PRONTO + b"\n")
        seguidor = lt.Seguidor(self.pasta)
        self.escrever("postgresql-08.json", PRONTO[:10], modo="wb")
        self.assertEqual(self.lidas(seguidor), [])
        self.escrever("postgresql-08.json", PRONTO[10:] + b"\n")
        self.assertEqual(self.lidas(seguidor), [(PRONTO, False)])

    def test_uma_linha_acima_do_tecto_da_a_cabeca_uma_vez_e_descarta_o_resto(self) -> None:
        self.escrever("postgresql-08.json", b"")
        seguidor = lt.Seguidor(self.pasta)
        enorme = UPDATE_DO_APP.replace(b"set nivel = 3", b"set nivel = 3 -- " + b"x" * (5 * lt.BLOCO))
        self.escrever("postgresql-08.json", enorme + b"\n" + SELECT_DO_MOTIVO + b"\n")
        lidas = self.lidas(seguidor)
        self.assertEqual(lidas, [(enorme[: lt.LINHA_MAXIMA], True), (SELECT_DO_MOTIVO, False)])

    def test_uma_linha_acima_do_tecto_por_escrever_nao_cresce_em_memoria(self) -> None:
        self.escrever("postgresql-08.json", b"")
        seguidor = lt.Seguidor(self.pasta)
        self.escrever("postgresql-08.json", UPDATE_DO_APP[:200] + b"x" * (3 * lt.LINHA_MAXIMA))
        self.assertEqual(len(self.lidas(seguidor)), 1)
        self.assertEqual(seguidor._ficheiros["postgresql-08.json"].resto, b"")
        self.escrever("postgresql-08.json", b"x" * lt.LINHA_MAXIMA + b"\n" + PRONTO + b"\n")
        self.assertEqual(self.lidas(seguidor), [(PRONTO, False)])

    def test_um_ficheiro_que_desaparece_sai_sem_erro(self) -> None:
        self.escrever("postgresql-08.json", PRONTO + b"\n")
        seguidor = lt.Seguidor(self.pasta)
        (self.pasta / "postgresql-08.json").unlink()
        self.assertEqual(self.lidas(seguidor), [])

    def test_uma_pasta_que_nao_existe_levanta(self) -> None:
        with self.assertRaises(FileNotFoundError):
            lt.Seguidor(self.pasta / "nao-existe")


class TestRecolha(ComPasta):
    def test_conta_cada_recusa_nova_e_nao_o_controlo(self) -> None:
        self.escrever("postgresql-08.json", UPDATE_DO_APP + b"\n")
        metricas = MetricasDoRegistoPg()
        recolha = pr.Recolha(self.pasta, metricas)
        self.assertEqual(recolha.volta(), 0, "o que ja estava escrito nao reconta")
        self.escrever("postgresql-08.json", UPDATE_DO_APP + b"\n" + _com(UPDATE_DO_APP, user="kamba_batch")
                      + b"\n" + PRONTO + b"\n" + SELECT_DO_MOTIVO + b"\n")
        self.assertEqual(recolha.volta(), 2)
        self.assertEqual(metricas.recusas(), 2)

    def test_sem_jsonlog_nao_arranca(self) -> None:
        self.escrever("postgresql-08.log", b"so stderr\n")
        with self.assertRaisesRegex(pr.RegistoIlegivel, "jsonlog"):
            pr.Recolha(self.pasta)

    def test_pasta_que_nao_se_le_nao_arranca(self) -> None:
        with self.assertRaisesRegex(pr.RegistoIlegivel, "FileNotFoundError"):
            pr.Recolha(self.pasta / "nao-existe")

    def test_correr_para_a_pedido_e_sai_com_3_se_a_leitura_falhar(self) -> None:
        self.escrever("postgresql-08.json", PRONTO + b"\n")
        recolha = pr.Recolha(self.pasta, MetricasDoRegistoPg())
        parar = threading.Event()
        parar.set()
        self.assertEqual(pr.correr_ate(parar, recolha, self.fail), 0)

        falhas: list[Exception] = []
        recolha._seguidor._pasta = self.pasta / "nao-existe"
        self.assertEqual(pr.correr_ate(threading.Event(), recolha, falhas.append), 3)
        self.assertIsInstance(falhas[0], FileNotFoundError)

    def test_a_volta_corre_ate_parar(self) -> None:
        self.escrever("postgresql-08.json", b"")
        metricas = MetricasDoRegistoPg()
        recolha = pr.Recolha(self.pasta, metricas)
        parar = threading.Event()
        fio = threading.Thread(target=recolha.correr, args=(parar, 0.01))
        fio.start()
        self.escrever("postgresql-08.json", UPDATE_DO_APP + b"\n")
        for _ in range(500):
            if metricas.recusas():
                break
            parar.wait(0.01)
        parar.set()
        fio.join(5)
        self.assertEqual(metricas.recusas(), 1)


class TestPorta(unittest.TestCase):
    def test_omissao_valor_e_recusa_sem_repetir_o_valor(self) -> None:
        self.assertEqual(pr.porta({}), pr.PORTA_POR_OMISSAO)
        self.assertEqual(pr.porta({pr.VARIAVEL_DA_PORTA: " 9100 "}), 9100)
        for cru in ("abc", "0", "70000", "-1"):
            with self.subTest(cru=cru), self.assertRaises(ValueError) as erro:
                pr.porta({pr.VARIAVEL_DA_PORTA: cru})
            self.assertNotIn(cru, str(erro.exception).replace(pr.VARIAVEL_DA_PORTA, ""))


class TestMetricasERota(unittest.TestCase):
    def test_nasce_a_zero_sem_etiquetas(self) -> None:
        metricas = MetricasDoRegistoPg()
        texto = metricas.exposicao()
        self.assertIn(f"# TYPE {METRICA_TECTO_RECUSADO} counter", texto)
        self.assertIn(f"\n{METRICA_TECTO_RECUSADO} 0\n", texto)
        self.assertNotIn("{", texto)
        metricas.contar()
        self.assertIn(f"\n{METRICA_TECTO_RECUSADO} 1\n", metricas.exposicao())

    def test_a_rota_serve_a_serie_e_o_healthz(self) -> None:
        metricas = MetricasDoRegistoPg()
        metricas.contar()
        http = pr.servidor(0, metricas=metricas)
        fio = threading.Thread(target=http.serve_forever, daemon=True)
        fio.start()
        self.addCleanup(http.server_close)
        self.addCleanup(http.shutdown)
        base = f"http://127.0.0.1:{http.server_address[1]}"
        with urllib.request.urlopen(f"{base}/metrics", timeout=5) as r:
            self.assertIn(f"{METRICA_TECTO_RECUSADO} 1", r.read().decode())
        with urllib.request.urlopen(f"{base}/healthz", timeout=5) as r:
            self.assertEqual(json.loads(r.read())["service"], pr.SERVICO)
        with self.assertRaises(urllib.error.HTTPError) as erro:
            urllib.request.urlopen(f"{base}/outra", timeout=5)
        self.assertEqual(erro.exception.code, 404)


if __name__ == "__main__":
    unittest.main()
