"""O repositorio real passa; o canario morde, e nao se deixa esvaziar; a CLI."""

from __future__ import annotations

import contextlib
import io
import unittest

from supply_chain import canario
from supply_chain.canario import Copia, Mutacao, NaoSeAplica
from supply_chain.cli import VERIFICACOES, executar, executar_todas, main

from .base import ROOT, ComArvore


def _silencioso(argumentos: list[str]) -> tuple[int, str, str]:
    saida, erro = io.StringIO(), io.StringIO()
    with contextlib.redirect_stdout(saida), contextlib.redirect_stderr(erro):
        codigo = main(argumentos)
    return codigo, saida.getvalue(), erro.getvalue()


class TestRepositorioReal(unittest.TestCase):
    def test_o_repositorio_passa_todas_as_verificacoes(self) -> None:
        achados = executar_todas(ROOT)
        self.assertEqual([str(a) for a in achados], [])

    def test_o_que_o_repositorio_tem_hoje(self) -> None:
        """Numeros fixos de proposito: quem os mexer tem de saber que mexeu."""
        from supply_chain import egress, imagens, licencas, runtime

        _, resumo = imagens.verificar(ROOT)
        # 5 Dockerfile (um `ARG` cada), 2 imagens no compose, a variavel do
        # `.env.example` e a constante de `db/gate_bd.py`; desde o KAM-011, a
        # imagem de teste do SeaweedFS (compose de armazenamento) e as duas
        # constantes de `infra/storage/`.
        #
        # **KAM-019: a sexta imagem e o Chatwoot**, do compose do spike do
        # criterio 8. As referencias sobem mais do que as imagens porque esse
        # compose tem quatro servicos e so tres imagens distintas: o `chatwoot`
        # e o `chatwoot-worker` partilham a mesma, e reutiliza os digests do
        # pgvector e do Valkey que ja ca estavam.
        self.assertGreaterEqual(resumo["referencias"], 12)
        self.assertEqual(resumo["imagens"], 6)
        self.assertEqual(resumo["cosign"]["verificar"], 0)
        self.assertEqual(resumo["cosign"]["por_apurar"], 6)

        _, resumo = runtime.verificar(ROOT)
        self.assertEqual(resumo["dockerfiles"], 5)
        # KAM-019: oito mais os quatro do compose do spike, todos `read_only`.
        self.assertEqual(resumo["servicos"], 12)

        _, resumo = egress.verificar(ROOT)
        # Idem: as quatro listas de saidas sao **vazias** com `por_omissao:
        # negar`, e a lista vazia e a afirmacao — o Chatwoot e espelho e nao
        # canal, pelo que uma rota de saida dali so serviria um inbox de
        # WhatsApp a falar com a Graph, o correio de notificacao a levar
        # conversa de clientes para fora, ou telemetria.
        self.assertEqual(resumo["servicos"], 12)

        _, resumo = licencas.verificar(ROOT)
        self.assertEqual(resumo["estados"]["pendente_de_decisao"], 2)  # redis e valkey: D12
        self.assertEqual(resumo["estados"]["excepcao"], 0)

    def test_redis_e_valkey_estao_pendentes_e_nao_aprovados(self) -> None:
        """«A lista de licencas marca-o como pendente de decisao e nao como aprovado.»"""
        from supply_chain import licencas

        registos = {r.componente: r for r in licencas.ler_registo(ROOT)}
        for nome in ("redis", "valkey"):
            with self.subTest(nome=nome):
                self.assertEqual(registos[nome].estado, licencas.PENDENTE)
                self.assertEqual(registos[nome].decisao, "D12")

    def test_cada_linha_do_registo_tem_os_quatro_campos_do_criterio(self) -> None:
        from supply_chain import licencas

        for registo in licencas.ler_registo(ROOT):
            with self.subTest(componente=registo.componente):
                self.assertTrue(registo.versao)
                self.assertTrue(registo.licenca)
                self.assertRegex(registo.data_verificacao, r"^2026-\d{2}-\d{2}$")
                self.assertTrue(registo.fonte)


class TestCanario(unittest.TestCase):
    def test_o_canario_passa_sobre_o_repositorio(self) -> None:
        relatorio, falhas = canario.correr(ROOT)
        self.assertEqual(falhas, [])
        self.assertEqual(len(relatorio), len(canario.MUTACOES))

    def test_ha_pelo_menos_trinta_mutacoes_e_todas_com_regras(self) -> None:
        self.assertGreaterEqual(len(canario.MUTACOES), 30)
        nomes = [m.nome for m in canario.MUTACOES]
        self.assertEqual(len(nomes), len(set(nomes)))
        for mutacao in canario.MUTACOES:
            self.assertTrue(mutacao.regras, mutacao.nome)

    def test_o_caso_semeado_do_ticket_esta_na_lista(self) -> None:
        self.assertIn("imagem-litellm-latest", {m.nome for m in canario.MUTACOES})


class TestCanarioNaoSeDeixaEnganar(ComArvore):
    """O canario sobre uma arvore minima, com listas de mutacoes de proposito erradas."""

    def setUp(self) -> None:
        super().setUp()
        self._minimo = canario.MINIMO_POR_REGRA
        canario.MINIMO_POR_REGRA = {}
        self.addCleanup(setattr, canario, "MINIMO_POR_REGRA", self._minimo)

    def test_mutacao_apanhada(self) -> None:
        relatorio, falhas = canario.correr(
            self.raiz,
            (Mutacao("a", "automerge", frozenset({"automerge-ligado"}),
                     lambda c: c.trocar("renovate.json5", r"^  automerge: false,$", "  automerge: true,")),),
        )
        self.assertEqual(falhas, [])
        self.assertEqual(len(relatorio), 1)

    def test_mutacao_que_sobrevive_falha_o_canario(self) -> None:
        _, falhas = canario.correr(
            self.raiz,
            (Mutacao("inofensiva", "um comentario a mais", frozenset({"automerge-ligado"}),
                     lambda c: c.acrescentar("Makefile", "# nada")),),
        )
        self.assertEqual(len(falhas), 1)
        self.assertIn("sobreviveu", falhas[0])

    def test_mutacao_apanhada_pela_regra_errada_falha_o_canario(self) -> None:
        _, falhas = canario.correr(
            self.raiz,
            (Mutacao("a", "automerge", frozenset({"quarentena-desligada"}),
                     lambda c: c.trocar("renovate.json5", r"^  automerge: false,$", "  automerge: true,")),),
        )
        self.assertEqual(len(falhas), 1)
        self.assertIn("esperava [quarentena-desligada] e obteve [automerge-ligado]", falhas[0])

    def test_mutacao_apanhada_por_mais_regras_do_que_as_esperadas_falha(self) -> None:
        def duas(copia: Copia) -> None:
            copia.trocar("renovate.json5", r"^  automerge: false,$", "  automerge: true,")
            copia.apagar("services/gwy/egress.yaml")

        _, falhas = canario.correr(
            self.raiz, (Mutacao("duas", "duas coisas", frozenset({"automerge-ligado"}), duas),)
        )
        self.assertEqual(len(falhas), 1)

    def test_mutacao_que_ja_nao_se_aplica_falha_o_canario(self) -> None:
        _, falhas = canario.correr(
            self.raiz,
            (Mutacao("velha", "texto que ja nao existe", frozenset({"automerge-ligado"}),
                     lambda c: c.trocar("renovate.json5", r"^  autoMerge: false,$", "x")),),
        )
        self.assertEqual(len(falhas), 1)
        self.assertIn("ja nao se aplica", falhas[0])

    def test_linha_de_base_vermelha_falha_o_canario(self) -> None:
        self.trocar("renovate.json5", "  automerge: false,\n  packageRules", "  automerge: true,\n  packageRules")
        relatorio, falhas = canario.correr(
            self.raiz,
            (Mutacao("a", "qualquer", frozenset({"egress-em-falta"}),
                     lambda c: c.apagar("services/gwy/egress.yaml")),),
        )
        self.assertEqual(relatorio, [])
        self.assertIn("linha de base vermelha", falhas[0])

    def test_lista_vazia_nao_passa_com_o_minimo_verdadeiro(self) -> None:
        canario.MINIMO_POR_REGRA = self._minimo
        _, falhas = canario.correr(self.raiz, ())
        self.assertEqual(len(falhas), len(self._minimo))

    def test_erro_de_configuracao_durante_uma_mutacao_nao_conta_como_vermelho(self) -> None:
        _, falhas = canario.correr(
            self.raiz,
            (Mutacao("parte", "estraga o inventario", frozenset({"imagem-sem-digest"}),
                     lambda c: c.escrever("ci/supply-chain/imagens.yaml", "version: 9\n")),),
        )
        self.assertEqual(len(falhas), 1)
        self.assertIn("erro: ConfiguracaoInvalida", falhas[0])

    def test_as_mutacoes_sao_repostas(self) -> None:
        antes = self.ler("renovate.json5")
        canario.correr(
            self.raiz,
            (Mutacao("a", "automerge", frozenset({"automerge-ligado"}),
                     lambda c: c.trocar("renovate.json5", r"^  automerge: false,$", "  automerge: true,")),),
        )
        self.assertEqual(self.ler("renovate.json5"), antes)

    def test_copia_repor_desfaz_escrita_troca_e_apagamento(self) -> None:
        copia = Copia(self.raiz)
        original = self.ler("Makefile")
        copia.acrescentar("Makefile", "# x")
        copia.escrever("novo/ficheiro.txt", "x")
        copia.apagar("services/gwy/egress.yaml")
        copia.repor()
        self.assertEqual(self.ler("Makefile"), original)
        self.assertFalse((self.raiz / "novo/ficheiro.txt").exists())
        self.assertTrue((self.raiz / "services/gwy/egress.yaml").is_file())
        with self.assertRaises(NaoSeAplica):
            copia.apagar("nao/existe")
        with self.assertRaises(NaoSeAplica):
            copia.ler("nao/existe")


class TestCLI(ComArvore):
    def test_check_conforme(self) -> None:
        codigo, saida, erro = _silencioso(["--root", str(self.raiz), "check"])
        self.assertEqual((codigo, erro), (0, ""))
        for nome in VERIFICACOES:
            self.assertIn(f"supply_chain: {nome}: conforme", saida)
        # O que nao se verificou diz-se em cada execucao, e nao so na documentacao.
        self.assertIn("POR APURAR", saida)
        self.assertIn("nao se ve daqui", saida)

    def test_cada_subcomando_isolado(self) -> None:
        for nome in VERIFICACOES:
            with self.subTest(nome=nome):
                codigo, saida, _ = _silencioso(["--root", str(self.raiz), nome])
                self.assertEqual(codigo, 0)
                self.assertEqual(saida.count("supply_chain:"), 1)
                self.assertEqual(executar(nome, self.raiz)[0], [])

    def test_achado_da_saida_1_com_a_regra_o_ficheiro_e_a_linha(self) -> None:
        self.trocar("infra/compose/docker-compose.dev.yml", "    read_only: true\n    networks:\n      - data\n", "    networks:\n      - data\n")
        codigo, _saida, erro = _silencioso(["--root", str(self.raiz), "check"])
        self.assertEqual(codigo, 1)
        self.assertIn("[fs-so-de-leitura] infra/compose/docker-compose.dev.yml:", erro)

    def test_erro_de_configuracao_da_saida_2_e_nao_parece_conforme(self) -> None:
        (self.raiz / "ci/supply-chain/imagens.yaml").unlink()
        codigo, _saida, erro = _silencioso(["--root", str(self.raiz), "check"])
        self.assertEqual(codigo, 2)
        self.assertIn("erro de configuracao", erro)

    def test_canario_pela_cli_falha_numa_arvore_que_nao_e_o_repositorio(self) -> None:
        """As mutacoes sao do repositorio real: noutra arvore deixam de se aplicar, e isso e falha."""
        codigo, _saida, erro = _silencioso(["--root", str(self.raiz), "canario"])
        self.assertEqual(codigo, 1)
        self.assertIn("ja nao se aplica", erro)

    def test_verificacao_desconhecida(self) -> None:
        with self.assertRaises(ValueError):
            executar("nada", self.raiz)


class TestCLISobreORepositorio(unittest.TestCase):
    def test_canario_pela_cli(self) -> None:
        codigo, saida, erro = _silencioso(["--root", str(ROOT), "canario"])
        self.assertEqual((codigo, erro), (0, ""))
        self.assertIn("0 sobreviventes", saida)


if __name__ == "__main__":
    unittest.main()
