"""Os instrumentos que correm no condutor, e o que o ensaio le de `infra/backup/`.

    TestMarcadores   so confirma depois do commit; um erro repete o MESMO numero
    TestEventos      o consumidor externo produz o efeito antes de marcar
    TestArquivo      o `postgres-arquivo.conf` de git chega ao `postgres` inteiro
    TestDocker       um passo que falha, falha alto
    TestCli          os codigos de saida do `calcular` e do `extrapolar`
"""

from __future__ import annotations

import io
import json
import subprocess
import tempfile
import unittest
from contextlib import redirect_stderr, redirect_stdout
from datetime import datetime, timedelta, timezone
from pathlib import Path

from dr_simulacro import cli, ensaio, eventos, folha, marcadores

RAIZ = Path(__file__).resolve().parents[3]
T0 = datetime(2026, 11, 8, 10, 0, 0, tzinfo=timezone.utc)


class LigacaoFalsa:
    """Uma base em memoria para o `dr_simulacro.marcador`, que pode cair a pedido.

    `cair_em` sao os numeros de chamada (a contar de 1) que levantam. Com
    `commit_antes_de_cair`, a chamada que cai **guarda** a linha antes de
    levantar: e a confirmacao perdida, que o escritor tem de resolver sem buraco.
    """

    def __init__(self, cair_em=(), commit_antes_de_cair=False):
        self.linhas: dict[int, datetime] = {}
        self.chamadas = 0
        self.cair_em = set(cair_em)
        self.commit_antes_de_cair = commit_antes_de_cair

    def run(self, sql, **parametros):
        self.chamadas += 1
        seq = parametros["seq"]
        if sql == marcadores.SQL_INSERIR:
            if self.chamadas in self.cair_em:
                if self.commit_antes_de_cair:
                    self.linhas.setdefault(seq, T0 + timedelta(seconds=seq))
                raise ConnectionError("o primario morreu")
            if seq in self.linhas:
                return []
            self.linhas[seq] = T0 + timedelta(seconds=seq)
            return [[seq, self.linhas[seq]]]
        if sql == marcadores.SQL_LER:
            return [[seq, self.linhas[seq]]] if seq in self.linhas else []
        raise AssertionError(sql)


def _escrever(base: LigacaoFalsa, voltas: int, pasta: Path) -> dict:
    contador = iter(range(voltas + 1))
    relogio = iter(float(n) for n in range(10_000))
    return marcadores.escrever(
        lambda: base, pasta / "c.csv", parar=lambda: next(contador) >= voltas,
        relogio=lambda: next(relogio), dormir=lambda _s: None, erros=pasta / "e.csv")


class TestMarcadores(unittest.TestCase):
    def test_cada_linha_confirmada_leva_o_instante_da_base(self):
        with tempfile.TemporaryDirectory() as pasta:
            base = LigacaoFalsa()
            resumo = _escrever(base, 5, Path(pasta))
            lidos = marcadores.ler_csv((Path(pasta) / "c.csv").read_text())
        self.assertEqual(resumo["confirmados"], 5)
        self.assertEqual(lidos, [(n, T0 + timedelta(seconds=n)) for n in range(1, 6)])

    def test_um_erro_repete_o_mesmo_numero_e_nao_deixa_buraco(self):
        with tempfile.TemporaryDirectory() as pasta:
            base = LigacaoFalsa(cair_em={3})
            resumo = _escrever(base, 6, Path(pasta))
            lidos = [n for n, _ in marcadores.ler_csv((Path(pasta) / "c.csv").read_text())]
            erros = (Path(pasta) / "e.csv").read_text()
        self.assertEqual(lidos, [1, 2, 3, 4, 5])
        self.assertEqual(resumo["falhas"], 1)
        self.assertIn("3,ConnectionError", erros)

    def test_commit_sem_confirmacao_confirma_o_guardado_e_nao_duplica(self):
        with tempfile.TemporaryDirectory() as pasta:
            base = LigacaoFalsa(cair_em={3}, commit_antes_de_cair=True)
            _escrever(base, 6, Path(pasta))
            lidos = marcadores.ler_csv((Path(pasta) / "c.csv").read_text())
        self.assertEqual([n for n, _ in lidos], [1, 2, 3, 4, 5])
        self.assertEqual(lidos[2][1], T0 + timedelta(seconds=3))

    def test_um_numero_falhado_nao_aparece_como_confirmado(self):
        with tempfile.TemporaryDirectory() as pasta:
            base = LigacaoFalsa(cair_em={2, 3, 4, 5})
            _escrever(base, 5, Path(pasta))
            lidos = [n for n, _ in marcadores.ler_csv((Path(pasta) / "c.csv").read_text())]
        self.assertEqual(lidos, [1])

    def test_a_cadencia_dorme_o_que_falta_e_nao_acumula_atraso(self):
        # 1.a volta: acaba aos 0,25 s e dorme 0,75. 2.a volta: acaba aos 2,5 s,
        # ja atrasada para o tique dos 2 s, e nao dorme nem tenta recuperar.
        sonos = []
        relogio = iter([0.0, 0.25, 2.5, 3.0])
        contador = iter(range(10))
        with tempfile.TemporaryDirectory() as pasta:
            marcadores.escrever(lambda: LigacaoFalsa(), Path(pasta) / "c.csv",
                                parar=lambda: next(contador) >= 2,
                                relogio=lambda: next(relogio), dormir=sonos.append)
        self.assertEqual(sonos, [0.75])

    def test_ler_csv_ignora_linhas_vazias(self):
        self.assertEqual(marcadores.ler_csv("\n1,2026-11-08T10:00:01.000000Z\n\n"),
                         [(1, T0 + timedelta(seconds=1))])


class BaseDeEventos:
    """Regista a ordem das chamadas; `ja_consumido` diz o que a marca devolve."""

    def __init__(self, marca_nova=True, ja_consumido=False):
        self.sql: list[str] = []
        self.marca_nova = marca_nova
        self.ja_consumido = ja_consumido

    def run(self, sql, **_):
        self.sql.append(sql)
        if sql == eventos.SQL_MARCAR:
            return [["e"]] if self.marca_nova else []
        if sql == eventos.SQL_JA_CONSUMIDO:
            return [[1]] if self.ja_consumido else []
        return []


EVENTO = (7, "0190f0a0-0000-7000-8000-000000000001", "t", "encomenda", "7", 1)


class TestEventos(unittest.TestCase):
    def test_o_interno_so_produz_efeito_se_a_marca_entrou(self):
        base = BaseDeEventos(marca_nova=False)
        self.assertFalse(eventos.consumir_interno(base, EVENTO))
        self.assertFalse(any("dr_simulacro.efeito" in s for s in base.sql))
        base = BaseDeEventos(marca_nova=True)
        self.assertTrue(eventos.consumir_interno(base, EVENTO))
        self.assertEqual(base.sql[0], "BEGIN")
        self.assertEqual(base.sql[-1], "COMMIT")
        self.assertIn("dr_simulacro.efeito", base.sql[2])

    def test_o_externo_escreve_o_efeito_antes_da_marca(self):
        with tempfile.TemporaryDirectory() as pasta:
            externos = Path(pasta) / "x.log"
            base = BaseDeEventos()
            ordem = []
            original = base.run

            def run(sql, **p):
                if sql == eventos.SQL_MARCAR:
                    ordem.append(("marca", externos.exists()))
                return original(sql, **p)

            base.run = run
            self.assertTrue(eventos.consumir_externo(base, EVENTO, externos, lambda: T0))
            self.assertEqual(ordem, [("marca", True)])
            self.assertTrue(externos.read_text().startswith(EVENTO[1]))

    def test_o_externo_ja_consumido_nao_repete_o_efeito(self):
        with tempfile.TemporaryDirectory() as pasta:
            externos = Path(pasta) / "x.log"
            self.assertFalse(eventos.consumir_externo(BaseDeEventos(ja_consumido=True), EVENTO,
                                                      externos, lambda: T0))
            self.assertFalse(externos.exists())

    def test_uma_falha_no_interno_desfaz_a_transaccao(self):
        class Cai(BaseDeEventos):
            def run(self, sql, **p):
                if sql == eventos.SQL_MARCAR:
                    self.sql.append(sql)
                    raise ConnectionError
                return super().run(sql, **p)

        base = Cai()
        with self.assertRaises(ConnectionError):
            eventos.consumir_interno(base, EVENTO)
        self.assertEqual(base.sql[-1], "ROLLBACK")


class TestArquivo(unittest.TestCase):
    def test_o_ficheiro_de_git_chega_inteiro_e_sem_aspas(self):
        texto = (RAIZ / "infra" / "backup" / "postgres-arquivo.conf").read_text(encoding="utf-8")
        opcoes = ensaio.opcoes_do_arquivo(texto)
        pares = dict(o.split("=", 1) for o in opcoes[1::2])
        self.assertEqual(opcoes[0::2], ["-c"] * len(pares))
        self.assertEqual(pares["archive_mode"], "on")
        self.assertEqual(pares["archive_timeout"], "60s")
        self.assertEqual(pares["archive_command"], "pgbackrest --stanza=kamba archive-push %p")
        self.assertEqual(set(pares), {"archive_mode", "archive_timeout", "archive_command",
                                      "wal_level", "max_wal_senders", "wal_compression"})

    def test_sem_tira_a_chave_pedida(self):
        opcoes = ensaio.opcoes_do_arquivo("archive_mode = on\n# x = y\nwal_level = replica\n",
                                          sem=("archive_mode",))
        self.assertEqual(opcoes, ["-c", "wal_level=replica"])

    def test_tamanho_do_du(self):
        self.assertEqual(ensaio.tamanho_em_bytes("123456\t/var/lib/x\n"), 123456)


class TestDocker(unittest.TestCase):
    def test_cpu_do_docker_stats(self):
        self.assertEqual(ensaio.cpu_em_pct("12.5%"), 12.5)
        self.assertEqual(ensaio.cpu_em_pct("--"), 0.0)

    def test_o_sossego_pede_amostras_seguidas_e_desiste_no_prazo(self):
        cpus = iter(["50%", "1%", "30%", "1%", "2%", "0%"])

        def falso(argv, **_):
            return subprocess.CompletedProcess(argv, 0, f"outro\t{next(cpus)}\t1GiB\n", "")

        with tempfile.TemporaryDirectory() as pasta:
            e = ensaio.Ensaio(RAIZ, Path(pasta), docker=ensaio.Docker({}, correr=falso),
                              dormir=lambda _s: None)
            r = e.esperar_sossego(limite_pct=10, seguidas=3)
            self.assertTrue(r["sossegado"])
            self.assertEqual(r["amostras"], [50.0, 1.0, 30.0, 1.0, 2.0, 0.0])
            r = e.esperar_sossego(ate_segundos=0)
            self.assertFalse(r["sossegado"])

    def test_codigo_nao_zero_levanta_com_a_mensagem(self):
        def falso(argv, **_):
            return subprocess.CompletedProcess(argv, 3, "", "sem espaco")

        docker = ensaio.Docker({}, correr=falso)
        with self.assertRaisesRegex(ensaio.EnsaioFalhou, "saiu com 3: sem espaco"):
            docker("exec", "x", "true")
        self.assertEqual(docker("exec", "x", "true", verificar=False).returncode, 3)

    def test_a_contencao_lista_so_os_contentores_alheios(self):
        def falso(argv, **_):
            return subprocess.CompletedProcess(
                argv, 0, "kam085-primario\t90%\t1GiB / 8GiB\noutro\t250%\t2GiB / 8GiB\n", "")

        with tempfile.TemporaryDirectory() as pasta:
            e = ensaio.Ensaio(RAIZ, Path(pasta), docker=ensaio.Docker({}, correr=falso))
            self.assertEqual(e.contencao(), [{"nome": "outro", "cpu": "250%",
                                              "memoria": "2GiB / 8GiB"}])
            segredos = json.loads((Path(pasta) / "segredos.json").read_text())
            self.assertEqual(len(segredos["PGBACKREST_REPO1_CIPHER_PASS"]), 43)
            # Os mesmos segredos na segunda execucao: o repositorio cifrado
            # do `preparar` so se le com a mesma passphrase.
            outra = ensaio.Ensaio(RAIZ, Path(pasta), docker=ensaio.Docker({}, correr=falso))
            self.assertEqual(outra.segredos, segredos)


def _cli(argv: list[str]) -> tuple[int, str, str]:
    saida, erro = io.StringIO(), io.StringIO()
    with redirect_stdout(saida), redirect_stderr(erro):
        codigo = cli.main(argv)
    return codigo, saida.getvalue(), erro.getvalue()


class TestCli(unittest.TestCase):
    def _folha(self, pasta: Path, restauro_s: float) -> Path:
        caminho = pasta / "f.jsonl"
        relogio = iter([T0, T0 + timedelta(seconds=restauro_s)])
        f = folha.Folha(caminho, "A", relogio=lambda: next(relogio))
        for passo in ("deteccao", "decisao", "iac", "replay", "verificacao", "dns"):
            f.nao_medido(passo, "por medir")
        f.inicio("restauro")
        f.fim("restauro")
        return caminho

    def test_calcular_dentro_e_fora_do_alvo(self):
        with tempfile.TemporaryDirectory() as pasta:
            pasta = Path(pasta)
            codigo, saida, _ = _cli(["calcular", "--folha", str(self._folha(pasta, 600)),
                                     "--cenario", "A", "--json"])
            self.assertEqual(codigo, 0)
            self.assertEqual(json.loads(saida)["rto_composto_min"], 10 + 75)
            (pasta / "f.jsonl").unlink()
            codigo, _, _ = _cli(["calcular", "--folha", str(self._folha(pasta, 7200)),
                                 "--cenario", "A"])
            self.assertEqual(codigo, 1)

    def test_calcular_com_marcadores_e_um_buraco_da_um(self):
        with tempfile.TemporaryDirectory() as pasta:
            pasta = Path(pasta)
            c, r = pasta / "c.csv", pasta / "r.csv"
            c.write_text("1,2026-11-08T10:00:01Z\n2,2026-11-08T10:00:02Z\n3,2026-11-08T10:00:03Z\n")
            r.write_text("1,2026-11-08T10:00:01Z\n3,2026-11-08T10:00:03Z\n")
            codigo, saida, _ = _cli(["calcular", "--folha", str(self._folha(pasta, 60)),
                                     "--cenario", "A", "--confirmados", str(c),
                                     "--restaurados", str(r), "--json"])
        self.assertEqual(codigo, 1)
        self.assertEqual(json.loads(saida)["buracos"], [2])

    def test_carimbar_escreve_a_folha_que_o_calcular_le(self):
        with tempfile.TemporaryDirectory() as pasta:
            caminho = Path(pasta) / "f.jsonl"
            for passo in ("deteccao", "decisao", "iac", "replay", "verificacao", "dns"):
                self.assertEqual(_cli(["carimbar", "--folha", str(caminho), "--cenario", "A",
                                       "--passo", passo, "nao_medido", "--nota", "x"])[0], 0)
            _cli(["carimbar", "--folha", str(caminho), "--cenario", "A", "--passo", "restauro",
                  "inicio"])
            _cli(["carimbar", "--folha", str(caminho), "--cenario", "A", "--passo", "restauro",
                  "fim"])
            codigo, saida, _ = _cli(["calcular", "--folha", str(caminho), "--cenario", "A",
                                     "--json"])
            self.assertEqual(codigo, 0)
            self.assertIsInstance(json.loads(saida)["passos"]["restauro"], float)
            codigo, _, erro = _cli(["carimbar", "--folha", str(caminho), "--cenario", "A",
                                    "--passo", "dns", "nao_medido"])
            self.assertEqual(codigo, 2)
            self.assertIn("porque", erro)

    def test_folha_ilegivel_da_dois(self):
        with tempfile.TemporaryDirectory() as pasta:
            caminho = Path(pasta) / "f.jsonl"
            caminho.write_text("isto nao e json\n")
            codigo, _, erro = _cli(["calcular", "--folha", str(caminho), "--cenario", "A"])
        self.assertEqual(codigo, 2)
        self.assertIn("JSON ilegivel", erro)

    def test_extrapolar_e_a_regra_da_replica(self):
        codigo, saida, _ = _cli(["extrapolar", "--bytes", str(20 * 10 ** 9), "--segundos", "600",
                                 "--para-gb", "50", "--rto-composto-min", "60", "--json"])
        carga = json.loads(saida)
        self.assertEqual(carga["restauro_extrapolado_min"], 25)
        self.assertEqual(carga["rto_extrapolado_min"], 75)
        self.assertEqual(carga["replica_de_espera"], "por_decidir")
        self.assertEqual(codigo, 0)
        codigo, saida, _ = _cli(["extrapolar", "--bytes", str(20 * 10 ** 9), "--segundos", "600",
                                 "--rto-composto-min", "60", "--bd-prevista-gb", "45"])
        self.assertEqual(codigo, 1)
        self.assertIn("necessaria", saida)
        codigo, _, _ = _cli(["extrapolar", "--bytes", "1", "--segundos", "0"])
        self.assertEqual(codigo, 2)


if __name__ == "__main__":
    unittest.main()
