"""A sonda de RTT e o relatorio que so sai com numeros medidos (KAM-077, criterio 5)."""

from __future__ import annotations

import json
import socket
import tempfile
import unittest
from datetime import datetime, timedelta, timezone
from pathlib import Path

from borda import rtt

T0 = datetime(2026, 11, 25, 0, 0, tzinfo=timezone.utc)


def _linha(origem="luanda-1", alvo="host", segundos=0, rtt_ms=42.0, erro=None, intervalo=60, endereco="192.0.2.10:443"):
    return {
        "v": 1,
        "origem": origem,
        "alvo": alvo,
        "endereco": endereco,
        "instante": rtt._instante(T0 + timedelta(seconds=segundos)),
        "intervalo_s": intervalo,
        "rtt_ms": rtt_ms,
        "erro": erro,
    }


def _serie(alvo="host", horas=24, passo=60, valores=None, origem="luanda-1", endereco="192.0.2.10:443"):
    passos = horas * 3600 // passo + 1
    valores = valores or [10.0 + (i % 100) for i in range(passos)]
    return [
        _linha(origem=origem, alvo=alvo, segundos=i * passo, rtt_ms=valores[i % len(valores)], endereco=endereco)
        for i in range(passos)
    ]


def _da_meta(**kw):
    """A serie host -> graph.facebook.com que o criterio 5 tambem pede."""
    kw.setdefault("valores", [150.0, 160.0, 400.0])
    return _serie(alvo="graph", origem="host-staging", endereco="graph.facebook.com:443", **kw)


class _ComPasta(unittest.TestCase):
    def setUp(self) -> None:
        self._pasta = tempfile.TemporaryDirectory()
        self.pasta = Path(self._pasta.name)

    def tearDown(self) -> None:
        self._pasta.cleanup()

    def escrever(self, linhas, nome="amostras.jsonl") -> Path:
        caminho = self.pasta / nome
        caminho.write_text("".join(json.dumps(l) + "\n" for l in linhas), encoding="utf-8")
        return caminho


class TestAlvo(unittest.TestCase):
    def test_le_nome_endereco_porta(self) -> None:
        self.assertEqual(rtt.Alvo.ler("graph=graph.facebook.com:443"), rtt.Alvo("graph", "graph.facebook.com", 443))

    def test_recusa_formas_invalidas(self) -> None:
        for texto in ("graph.facebook.com:443", "Graph=x:443", "g=x:0", "g=x:70000", "g=x", "g|x=y:1"):
            with self.subTest(texto=texto), self.assertRaises(ValueError):
                rtt.Alvo.ler(texto)


class TestPercentil(unittest.TestCase):
    def test_posto_mais_proximo_sem_interpolar(self) -> None:
        valores = list(range(1, 21))  # 1..20
        self.assertEqual(rtt.percentil(valores, 50), 10)
        self.assertEqual(rtt.percentil(valores, 95), 19)
        self.assertEqual(rtt.percentil(valores, 100), 20)
        # Todo o percentil e um valor medido: nunca 10,5.
        self.assertIn(rtt.percentil([1.0, 2.0], 50), (1.0, 2.0))

    def test_um_so_valor(self) -> None:
        self.assertEqual(rtt.percentil([7.5], 95), 7.5)

    def test_lista_vazia_e_erro(self) -> None:
        with self.assertRaises(ValueError):
            rtt.percentil([], 50)


class TestAmostra(unittest.TestCase):
    def test_sucesso_guarda_o_rtt(self) -> None:
        linha = rtt.amostra("luanda-1", rtt.Alvo("host", "h", 443), 60, lambda e, p: 12.34567, lambda: T0)
        self.assertEqual(linha["rtt_ms"], 12.346)
        self.assertIsNone(linha["erro"])
        self.assertEqual(linha["endereco"], "h:443")
        self.assertEqual(linha["instante"], "2026-11-25T00:00:00.000000Z")

    def test_falha_e_amostra_e_nao_excepcao(self) -> None:
        def recusa(endereco, porta):
            raise ConnectionRefusedError()

        linha = rtt.amostra("luanda-1", rtt.Alvo("host", "h", 443), 60, recusa, lambda: T0)
        self.assertIsNone(linha["rtt_ms"])
        self.assertEqual(linha["erro"], "ConnectionRefusedError")

    def test_timeout_e_falha(self) -> None:
        def lento(endereco, porta):
            raise socket.timeout()

        linha = rtt.amostra("luanda-1", rtt.Alvo("host", "h", 443), 60, lento, lambda: T0)
        self.assertIsNotNone(linha["erro"])


class TestLigar(unittest.TestCase):
    def test_mede_um_handshake_local(self) -> None:
        servidor = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
        servidor.bind(("127.0.0.1", 0))
        servidor.listen(1)
        try:
            porta = servidor.getsockname()[1]
            self.assertGreater(rtt.ligar("127.0.0.1", porta, timeout=2.0), 0.0)
        finally:
            servidor.close()


class TestMedir(_ComPasta):
    def _medir(self, duracao, intervalo, alvos=("host", "graph")):
        relogio_falso = {"t": 0.0}

        def cronometro():
            return relogio_falso["t"]

        def dormir(segundos):
            relogio_falso["t"] += segundos

        saida = self.pasta / "s.jsonl"
        escritas = rtt.medir(
            "luanda-1",
            [rtt.Alvo(nome, "h", 443) for nome in alvos],
            saida,
            duracao_s=duracao,
            intervalo_s=intervalo,
            ligacao=lambda e, p: 5.0,
            relogio=lambda: T0 + timedelta(seconds=relogio_falso["t"]),
            dormir=dormir,
            cronometro=cronometro,
        )
        return escritas, rtt.ler(saida)

    def test_24h_dao_rondas_que_cobrem_a_janela_com_folga(self) -> None:
        escritas, amostras = self._medir(rtt.JANELA_MINIMA_S, 60)
        # 0, 60, ..., 86460: 1442 rondas, uma a mais do que a janela pede.
        self.assertEqual(escritas, 2 * 1442)
        series = rtt.resumir(amostras)
        self.assertEqual(len(series), 2)
        for serie in series:
            self.assertGreaterEqual(serie.cobertura_s, rtt.JANELA_MINIMA_S)
        self.assertEqual(rtt.recusas(series, rtt.JANELA_MINIMA_S, rtt.LACUNA_MAXIMA_S), [])

    def test_acrescenta_e_nao_apaga(self) -> None:
        self._medir(120, 60, alvos=("host",))
        _, amostras = self._medir(120, 60, alvos=("host",))
        self.assertEqual(len(amostras), 2 * 4)

    def test_sem_alvos_ou_origem_invalida(self) -> None:
        with self.assertRaises(ValueError):
            rtt.medir("luanda-1", [], self.pasta / "x")
        with self.assertRaises(ValueError):
            rtt.medir("Luanda 1", [rtt.Alvo("h", "h", 1)], self.pasta / "x")


class TestLer(_ComPasta):
    def test_le_e_ignora_linhas_vazias(self) -> None:
        caminho = self.escrever([_linha()])
        caminho.write_text(caminho.read_text() + "\n\n", encoding="utf-8")
        self.assertEqual(len(rtt.ler(caminho)), 1)

    def test_recusa_amostras_que_a_sonda_nao_escreveu(self) -> None:
        casos = {
            "sem-json": "nao e json\n",
            "campo-a-mais": json.dumps({**_linha(), "estimado": True}) + "\n",
            "versao": json.dumps({**_linha(), "v": 2}) + "\n",
            "rtt-e-erro": json.dumps({**_linha(), "erro": "X"}) + "\n",
            "nem-rtt-nem-erro": json.dumps({**_linha(), "rtt_ms": None}) + "\n",
            "rtt-zero": json.dumps({**_linha(), "rtt_ms": 0}) + "\n",
            "rtt-texto": json.dumps({**_linha(), "rtt_ms": "40"}) + "\n",
            "rtt-booleano": json.dumps({**_linha(), "rtt_ms": True}) + "\n",
            "rtt-nan": json.dumps({**_linha(), "rtt_ms": float("nan")}) + "\n",
            "instante": json.dumps({**_linha(), "instante": "ontem"}) + "\n",
            "alvo-com-barra": json.dumps({**_linha(), "alvo": "a|b"}) + "\n",
            "lista": "[1, 2]\n",
        }
        for nome, texto in casos.items():
            with self.subTest(caso=nome):
                caminho = self.pasta / f"{nome}.jsonl"
                caminho.write_text(texto, encoding="utf-8")
                with self.assertRaises(rtt.AmostraInvalida):
                    rtt.ler(caminho)


class TestRecusas(_ComPasta):
    def test_24h_com_sucesso_sustentam(self) -> None:
        series = rtt.resumir(rtt.ler(self.escrever(_serie())))
        self.assertEqual(rtt.recusas(series, rtt.JANELA_MINIMA_S, rtt.LACUNA_MAXIMA_S), [])

    def test_menos_de_24h_recusa(self) -> None:
        series = rtt.resumir(rtt.ler(self.escrever(_serie(horas=23))))
        razoes = rtt.recusas(series, rtt.JANELA_MINIMA_S, rtt.LACUNA_MAXIMA_S)
        self.assertTrue(any("janela pedida" in r for r in razoes), razoes)

    def test_lacuna_grande_recusa_mesmo_cobrindo_24h(self) -> None:
        linhas = [l for l in _serie() if not (3600 <= (rtt._ler_instante(l["instante"]) - T0).total_seconds() < 7200)]
        series = rtt.resumir(rtt.ler(self.escrever(linhas)))
        razoes = rtt.recusas(series, rtt.JANELA_MINIMA_S, rtt.LACUNA_MAXIMA_S)
        self.assertTrue(any("lacuna" in r for r in razoes), razoes)

    def test_so_falhas_recusa(self) -> None:
        linhas = [_linha(segundos=i * 60, rtt_ms=None, erro="TimeoutError") for i in range(1441)]
        razoes = rtt.recusas(rtt.resumir(rtt.ler(self.escrever(linhas))), rtt.JANELA_MINIMA_S, rtt.LACUNA_MAXIMA_S)
        self.assertTrue(any("nenhuma com sucesso" in r for r in razoes), razoes)

    def test_nada_recusa(self) -> None:
        self.assertEqual(rtt.recusas([], 1, 1), ["nenhuma amostra"])

    def test_um_sucesso_e_o_resto_falhas_recusa(self) -> None:
        linhas = [_linha(segundos=i * 60, rtt_ms=None, erro="TimeoutError") for i in range(1441)]
        linhas[0] = _linha(segundos=0, rtt_ms=12.0)
        razoes = rtt.recusas(rtt.resumir(rtt.ler(self.escrever(linhas))), rtt.JANELA_MINIMA_S, rtt.LACUNA_MAXIMA_S)
        self.assertTrue(any("janela pedida" in r for r in razoes), razoes)

    def test_falhas_seguidas_alem_da_lacuna_recusam(self) -> None:
        linhas = _serie()
        for i in range(100, 120):  # vinte minutos de *timeouts*
            linhas[i] = {**linhas[i], "rtt_ms": None, "erro": "TimeoutError"}
        razoes = rtt.recusas(rtt.resumir(rtt.ler(self.escrever(linhas))), rtt.JANELA_MINIMA_S, rtt.LACUNA_MAXIMA_S)
        self.assertTrue(any("medicoes com sucesso" in r for r in razoes), razoes)

    def test_falhas_contam_e_ficam_fora_dos_percentis(self) -> None:
        linhas = _serie(valores=[10.0])
        linhas[5] = {**linhas[5], "rtt_ms": None, "erro": "TimeoutError"}
        [serie] = rtt.resumir(rtt.ler(self.escrever(linhas)))
        self.assertEqual(serie.falhas, 1)
        self.assertEqual((serie.p50, serie.p95, serie.maximo), (10.0, 10.0, 10.0))


class TestRelatorioEVerificar(_ComPasta):
    def _ficheiros(self):
        return [
            self.escrever(_serie(alvo="host", origem="luanda-1"), "sonda.jsonl"),
            self.escrever(_da_meta(), "host.jsonl"),
        ]

    def test_o_relatorio_bate_com_as_amostras(self) -> None:
        ficheiros = self._ficheiros()
        texto = rtt.relatorio(ficheiros)
        self.assertIn("| host-staging | graph |", texto)
        self.assertIn("| luanda-1 | host |", texto)
        self.assertNotIn("192.0.2.10", texto, "o endereco do host nao vai para o relatorio publico")
        self.assertEqual(rtt.verificar(texto, ficheiros), [])

    def test_recusa_com_todas_as_razoes(self) -> None:
        curto = self.escrever(_serie(horas=1), "curto.jsonl")
        with self.assertRaises(rtt.Recusa) as contexto:
            rtt.relatorio([curto])
        self.assertIn("janela pedida", str(contexto.exception))

    def test_um_numero_mexido_a_mao_nao_sobrevive(self) -> None:
        ficheiros = self._ficheiros()
        texto = rtt.relatorio(ficheiros)
        [linha] = [l for l in texto.splitlines() if l.startswith("| host-staging | graph |")]
        celulas = linha.split(" | ")
        celulas[-2] = "52.0"  # o p95 «do doc 09 §5.2», escrito por cima do medido
        mexido = texto.replace(linha, " | ".join(celulas))
        self.assertIn("a tabela do relatorio nao e a que as amostras dao", rtt.verificar(mexido, ficheiros))

    def test_amostras_trocadas_ou_em_falta(self) -> None:
        ficheiros = self._ficheiros()
        texto = rtt.relatorio(ficheiros)
        problemas = rtt.verificar(texto, ficheiros[:1])
        self.assertTrue(any("nenhum ficheiro dado o tem" in p for p in problemas), problemas)
        outro = self.escrever(_serie(alvo="host", valores=[1.0]), "outro.jsonl")
        problemas = rtt.verificar(texto, ficheiros + [outro])
        self.assertTrue(any("nao esta declarado" in p for p in problemas), problemas)

    def test_metade_do_criterio_recusa(self) -> None:
        so_host = self.escrever(_serie(), "so-host.jsonl")
        with self.assertRaises(rtt.Recusa) as contexto:
            rtt.relatorio([so_host])
        self.assertIn("nenhuma serie mede graph.facebook.com", str(contexto.exception))
        so_meta = self.escrever(_da_meta(), "so-meta.jsonl")
        with self.assertRaises(rtt.Recusa) as contexto:
            rtt.relatorio([so_meta])
        self.assertIn("outro alvo", str(contexto.exception))

    def test_verificar_reaplica_a_janela_do_criterio(self) -> None:
        # Um relatorio feito com a janela baixada bate com as amostras e nao e o criterio 5.
        ficheiros = [self.escrever(_serie(horas=1), "h.jsonl"), self.escrever(_da_meta(horas=1), "m.jsonl")]
        texto = rtt.relatorio(ficheiros, janela_minima_s=3600)
        problemas = rtt.verificar(texto, ficheiros)
        self.assertNotIn("a tabela do relatorio nao e a que as amostras dao", problemas)
        self.assertTrue(any("janela pedida e 86400" in p for p in problemas), problemas)

    def test_verificar_recusa_amostras_vazias(self) -> None:
        vazio = self.pasta / "vazio.jsonl"
        vazio.write_text("", encoding="utf-8")
        texto = (
            f"{rtt.INICIO_TABELA}\n{rtt.tabela([])}\n{rtt.FIM_TABELA}\n"
            f"- `vazio.jsonl` — sha256 `{rtt._sha256(vazio)}`\n"
        )
        self.assertIn("nenhuma amostra", rtt.verificar(texto, [vazio]))

    def test_sem_marcadores(self) -> None:
        ficheiros = self._ficheiros()
        texto = rtt.relatorio(ficheiros).replace(rtt.INICIO_TABELA, "")
        self.assertIn("o relatorio nao tem a tabela entre os marcadores", rtt.verificar(texto, ficheiros))


if __name__ == "__main__":
    unittest.main()
