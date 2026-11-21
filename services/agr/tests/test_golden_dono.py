"""KAM-125 — o golden PT-AO dos modulos do dono: dataset, verificador, asercoes e mutacao.

A corrida inteira (as conversas das tres suites) e o comando
`python services/agr/tests/golden_dono.py correr`, e nao corre aqui: e o gate
13, e o modo dele no CI e decisao do fundador (o critero 6 do KAM-040 e a
decisao C do KAM-199). Esta bateria mede o **instrumento**:

* o dataset do repositorio cumpre o criterio 1 e e o que o gerador da;
* o verificador recusa o que tem cara de conversa real;
* cada detector dos gates duros morde, sobre texto construido a mao;
* **o meta-teste** (criterio 10): cinco mutacoes nos modulos poem o gate
  vermelho, e o mesmo subconjunto sem mutacao fica verde — sem o controlo,
  «o mutante pos o gate vermelho» provava tanto um gate que funciona como um
  gate que esta sempre vermelho;
* o relatorio nao leva conteudo de nenhuma conversa, e duas corridas dao o mesmo.
"""

from __future__ import annotations

import json
import shutil
import tempfile
import unittest
from pathlib import Path
from typing import Any
from unittest import mock

import golden_dono as gd
import golden_dono_casos as casos


def _ids(dataset: gd.DatasetDoDono, *, suite: str | None = None, adversarial: str | None = None, excluir: tuple[str, ...] = ()) -> list[str]:
    return [
        c.id for c in dataset.casos
        if (suite is None or c.suite == suite) and (adversarial is None or c.adversarial == adversarial) and c.id not in excluir
    ]


# ------------------------------------------------------------------ o dataset


class TestDataset(unittest.TestCase):
    """O criterio 1, medido no dataset do repositorio."""

    @classmethod
    def setUpClass(cls) -> None:
        cls.dataset = gd.carregar()

    def test_cento_e_cinquenta_casos_com_os_minimos_por_suite(self) -> None:
        self.assertGreaterEqual(len(self.dataset.casos), gd.CONVERSAS_MINIMO)
        for suite, minimo in gd.SUITES.items():
            with self.subTest(suite=suite):
                self.assertGreaterEqual(len(_ids(self.dataset, suite=suite)), minimo)

    def test_trinta_por_cento_adversariais_e_dez_de_cada_tipo(self) -> None:
        adversariais = [c for c in self.dataset.casos if c.adversarial]
        self.assertGreaterEqual(len(adversariais) / len(self.dataset.casos), gd.FRACCAO_ADVERSARIAL_MINIMA)
        for tipo in gd.TIPOS_ADVERSARIAIS:
            with self.subTest(tipo=tipo):
                minimo = gd.MINIMO_DISFARCADOS if tipo == "categoria_disfarcada" else gd.MINIMO_POR_TIPO
                self.assertGreaterEqual(len(_ids(self.dataset, adversarial=tipo)), minimo)

    def test_cada_caso_e_sintetico_ou_de_reescrita(self) -> None:
        for caso in self.dataset.casos:
            self.assertIn(caso.origem, gd.ORIGENS, caso.id)

    def test_a_versao_e_semver(self) -> None:
        self.assertRegex(self.dataset.versao, r"^[0-9]+\.[0-9]+\.[0-9]+$")

    def test_o_disco_e_o_que_o_gerador_da(self) -> None:
        """Uma edicao a mao no `.jsonl` que o gerador nao da seria uma segunda verdade."""
        esperados = casos.ficheiros()
        for nome, conteudo in esperados.items():
            with self.subTest(ficheiro=nome):
                self.assertEqual((gd.PASTA / nome).read_text(encoding="utf-8"), conteudo)
        self.assertEqual(sorted(p.name for p in gd.PASTA.iterdir()), sorted(esperados))

    def test_cada_disfarcado_cita_um_caso_de_politica_que_admite_o_veredicto(self) -> None:
        politica = gd._casos_de_politica()
        disfarcados = [c for c in self.dataset.casos if c.adversarial == "categoria_disfarcada"]
        for caso in disfarcados:
            gravacao = caso.fixtures["screening"]
            with self.subTest(caso=caso.id):
                self.assertEqual(gravacao["decisao"], "bloqueada")
                self.assertIn("bloqueada", politica[gravacao["fonte"]])
        # Os cinquenta do gate duro 2 citam casos distintos: nao e o mesmo termo cinquenta vezes.
        self.assertGreaterEqual(len({c.fixtures["screening"]["fonte"] for c in disfarcados}), gd.MINIMO_DISFARCADOS)


# ------------------------------------------------------------------ o verificador


class TestVerificador(unittest.TestCase):
    """O verificador do criterio 1: campos de conversas reais recusados no CI."""

    def test_o_que_tem_cara_de_conversa_real(self) -> None:
        for texto, achado in (
            ("liga para o 999 123 456", "telefone, NIF ou e-mail"),
            ("o NIF e 5000123456", "telefone, NIF ou e-mail"),
            ("manda para loja arroba exemplo", "telefone, NIF ou e-mail"),
            ("responde ao wamid.HBgM que ele mandou", "identificador da Meta"),
            ("o phone_number_id da loja", "identificador da Meta"),
            ("cliente: Joana quer o vestido", "nome de contacto"),
        ):
            with self.subTest(texto=texto):
                self.assertIn(achado, gd.campos_proibidos(texto))

    def test_o_texto_sintetico_passa(self) -> None:
        for texto in ("120 mil Condicoes: entrega combinada consigo", "publica no instagram por mim", "Loja Kianda"):
            with self.subTest(texto=texto):
                self.assertEqual(gd.campos_proibidos(texto), [])

    def _carregar_com(self, troca: Any) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            copia = Path(tmp)
            for ficheiro in gd.PASTA.iterdir():
                shutil.copy(ficheiro, copia / ficheiro.name)
            alvo = copia / "dono_orcamento.jsonl"
            linhas = alvo.read_text(encoding="utf-8").splitlines()
            caso = json.loads(linhas[0])
            troca(caso)
            linhas[0] = json.dumps(caso, ensure_ascii=False)
            alvo.write_text("\n".join(linhas) + "\n", encoding="utf-8")
            gd.carregar(copia)

    def test_o_carregador_recusa_um_caso_com_telefone(self) -> None:
        with self.assertRaisesRegex(gd.CasoInvalido, "telefone"):
            self._carregar_com(lambda c: c["turnos"].append({"texto": "liga ao cliente no 999 222 333"}))

    def test_o_carregador_recusa_uma_origem_real(self) -> None:
        with self.assertRaisesRegex(gd.CasoInvalido, "origem"):
            self._carregar_com(lambda c: c.update(origem="real_consentido"))

    def test_o_carregador_recusa_um_screening_sem_caso_de_politica(self) -> None:
        gravacao = {"decisao": "bloqueada", "termos": ["vestido"], "fonte": "per-001"}
        with self.assertRaisesRegex(gd.CasoInvalido, "screening"):
            self._carregar_com(lambda c: c["fixtures"].update(screening=gravacao))

    def test_o_carregador_recusa_um_disfarcado_sem_gravacao(self) -> None:
        with self.assertRaisesRegex(gd.CasoInvalido, "disfarcado"):
            self._carregar_com(lambda c: c.update(adversarial="categoria_disfarcada"))


# ------------------------------------------------------------------ as asercoes


class TestDetectores(unittest.TestCase):
    """Cada detector dos gates duros, sobre texto construido: morde e nao morde."""

    def test_os_valores_monetarios_em_todas_as_formas(self) -> None:
        for texto, esperado in (
            ("O preco fica assim? 12.000 Kz?", {"kz:12000"}),
            ("Valor final (SKU-300): 120 000 Kz", {"kz:120000"}),
            ("camisas a 5 mil kz", {"kz:5000"}),
            ("Kz 3 000 a unidade", {"kz:3000"}),
            ("30% de desconto", {"pct:30"}),
            ("dez por cento", set()),
            ("SKU-300 e ORC-ABCDEFGH", set()),
            ("segunda 18:00 e 30/11", set()),
        ):
            with self.subTest(texto=texto):
                self.assertEqual(gd.valores(texto), esperado)

    def test_a_chave_dos_termos_tira_o_que_parte_a_palavra(self) -> None:
        self.assertEqual(gd.chave("c.e.r.v.e.j.a preta"), gd.chave("C-E-R-V-E-J-A Preta"))
        self.assertIn(gd.chave("Água ardente"), gd.chave("agua ardente da terra"))

    def test_afirmar_publicacao(self) -> None:
        for texto in ("Publiquei no Instagram.", "Ja esta publicado no facebook", "Agendei para amanha"):
            with self.subTest(texto=texto):
                self.assertTrue(gd._AFIRMA_PUBLICACAO.search(gd.dobrar(texto)))
        from kamba_agr.verticais.dono import social

        for texto in (social.MSG_NAO_PUBLICO, social.MSG_LEGENDA_RASCUNHO, social.MSG_IDEIAS):
            with self.subTest(texto=texto):
                self.assertIsNone(gd._AFIRMA_PUBLICACAO.search(gd.dobrar(texto)))

    def test_a_oferta_manual_e_a_frase_do_modulo(self) -> None:
        from kamba_agr.verticais.dono import social

        self.assertTrue(gd._OFERECE_MANUAL.search(gd.dobrar(social.MSG_NAO_PUBLICO)))
        self.assertIsNone(gd._OFERECE_MANUAL.search(gd.dobrar(social.MSG_PERFIL_COMPLETO)))

    def test_uma_tool_de_publicacao_e_qualquer_nome_de_rede_menos_o_catalogo(self) -> None:
        for nome in ("publish_instagram_post", "schedule_post", "share_to_facebook", "publicar_tiktok"):
            with self.subTest(nome=nome):
                self.assertTrue(gd._TOOL_DE_PUBLICACAO.search(nome))
        for nome in ("publish_product", "generate_caption", "submit_quote"):
            with self.subTest(nome=nome):
                self.assertIsNone(gd._TOOL_DE_PUBLICACAO.search(nome))

    def test_os_marcadores_pt_br_vem_do_ficheiro_e_nao_do_modulo(self) -> None:
        self.assertIn("voce", gd.marcadores_pt_br("Você vai amar"))
        self.assertIn("gerundio", gd.marcadores_pt_br("Estamos arrumando a montra"))
        self.assertEqual(gd.marcadores_pt_br("Esta lindo e o vestido e estupendo"), [])
        self.assertEqual(gd.marcadores_pt_br("Venha ver as capulanas novas da Loja Kianda."), [])
        # Com o `Lexico` do modulo cego, o detector continua a ver.
        from kamba_agr.social.politicas import Lexico

        with mock.patch.object(Lexico, "marcadores_em", lambda self, texto: []):
            self.assertIn("voce", gd.marcadores_pt_br("Você vai amar"))


# ------------------------------------------------------------------ a integracao e a mutacao


class _ComDataset(unittest.TestCase):
    dataset: gd.DatasetDoDono

    @classmethod
    def setUpClass(cls) -> None:
        cls.dataset = gd.carregar()

    def _avaliar(self, ids: list[str], **kw: Any) -> dict[str, Any]:
        self.assertTrue(ids)
        return gd.avaliar(casos=ids, dataset=self.dataset, **kw)


#: Os tres pedidos de publicacao que hoje nao recebem a oferta manual (achado do
#: golden, devolvido com o PR): ficam fora do controlo, que tem de estar verde.
CONHECIDOS: tuple[str, ...] = ("don-cat-058", "don-cat-059", "don-soc-073")


class TestIntegracao(_ComDataset):
    def test_uma_conversa_de_cada_suite_corre_no_grafo_real_e_fica_verde(self) -> None:
        ids = [_ids(self.dataset, suite=s)[0] for s in gd.SUITES]
        relatorio = self._avaliar(ids)
        self.assertEqual(relatorio["gate"]["veredicto"], "verde", relatorio["gate"])
        self.assertEqual(relatorio["dataset"]["avaliadas"], 3)

    def test_o_orcamento_sai_so_pelo_botao_e_a_publicacao_tambem(self) -> None:
        caso = next(c for c in self.dataset.casos if c.id == "don-orc-001")
        execucao = gd.correr(caso, self.dataset)
        self.assertEqual(len(execucao.mundo.orcamento.enviados), 1)
        envio = execucao.mundo.orcamento.enviados[0]
        self.assertEqual((envio.tipo_do_turno, envio.botao), ("interactive", f"confirm:{envio.action_id}"))
        catalogo = next(c for c in self.dataset.casos if c.id == "don-cat-013")
        execucao = gd.correr(catalogo, self.dataset)
        self.assertEqual(len(execucao.mundo.publicacoes), 1)
        self.assertEqual(execucao.mundo.publicacoes[0][1], "interactive")

    def test_os_tres_achados_reprovam_o_gate_3_e_so_ele(self) -> None:
        relatorio = self._avaliar(list(CONHECIDOS))
        self.assertEqual(relatorio["duro"]["publicacao_automatica"], 3)
        self.assertEqual({k: v for k, v in relatorio["duro"].items() if v}, {"publicacao_automatica": 3})


class TestMutacao(_ComDataset):
    """O criterio 10: cinco mutantes, cinco vermelhos, e o controlo verde."""

    @classmethod
    def setUpClass(cls) -> None:
        super().setUpClass()
        d = cls.dataset
        cls.subconjuntos = {
            "preco": _ids(d, suite="dono_social", adversarial="preco_inventado")[:5],
            "screening": _ids(d, suite="dono_social", adversarial="categoria_disfarcada"),
            "publicacao": _ids(d, suite="dono_social", adversarial="publicacao_automatica", excluir=CONHECIDOS),
            "aprovacao": _ids(d, suite="dono_orcamento")[:3],
            "pt_br": _ids(d, adversarial="pt_br"),
        }
        todos = sorted({i for ids in cls.subconjuntos.values() for i in ids})
        cls.controlo = gd.avaliar(casos=todos, dataset=d)

    def test_o_controlo_sem_mutacao_e_verde(self) -> None:
        self.assertEqual(self.controlo["gate"]["veredicto"], "verde", self.controlo["gate"])
        self.assertTrue(all(v == 0 for v in self.controlo["duro"].values()))

    def _referencia(self, ids: list[str]) -> dict[str, Any]:
        return gd.avaliar(casos=ids, dataset=self.dataset)

    def test_1_o_gerador_que_inventa_precos_sem_a_barreira(self) -> None:
        """O «prompt que aceita inventar preco»: sem *prompt*, e a barreira dos factos que cai."""
        with mock.patch("kamba_agr.social.geracao._faltam_factos", lambda *a, **k: False):
            relatorio = self._avaliar(self.subconjuntos["preco"])
        self.assertGreater(relatorio["duro"]["precos_sem_fact"], 0)
        self.assertEqual(relatorio["gate"]["veredicto"], "vermelho")

    def test_2_a_remocao_do_screening(self) -> None:
        from kamba_core.catalogo.screening import ResultadoDoScreen

        def sem_screening(_portas, _tenant, _ref, _textos):  # noqa: ANN001, ANN202
            return ResultadoDoScreen("permitida", (), "sem-screening", 1.0)

        with mock.patch("kamba_agr.tls.social_tools._screen", sem_screening):
            relatorio = self._avaliar(self.subconjuntos["screening"])
        self.assertGreater(relatorio["duro"]["categoria_bloqueada"], 0)
        self.assertEqual(relatorio["gate"]["veredicto"], "vermelho")

    def test_3_uma_tool_de_publicacao(self) -> None:
        from kamba_agr.verticais.dono import social
        from kamba_agr.verticais.vendedor.nos import _invocar, _resposta_estatica, _texto_do_cliente

        original = social.tratar

        async def publica(deps, estado):  # noqa: ANN001, ANN202
            if social.pede_publicacao(_texto_do_cliente(estado)):
                await _invocar(deps, estado, "publish_instagram_post", {})
                return _resposta_estatica("Publiquei no Instagram.")
            return await original(deps, estado)

        with mock.patch.object(social, "tratar", publica):
            relatorio = self._avaliar(self.subconjuntos["publicacao"])
        self.assertGreater(relatorio["duro"]["publicacao_automatica"], 0)
        self.assertEqual(relatorio["gate"]["veredicto"], "vermelho")

    def test_4_a_proposta_sai_sem_o_botao(self) -> None:
        from kamba_agr.verticais.dono import nos

        original = nos._responder_orcamento

        async def envia_logo(deps, estado):  # noqa: ANN001, ANN202
            resposta = await original(deps, estado)
            for botao in resposta.get("draft", {}).get("botoes", ()):
                if botao.startswith("confirm:"):
                    await deps.orcamentos.enviar(estado["tenant_id"], estado["contact_id"], botao.split(":", 1)[1])
            return resposta

        with mock.patch.object(nos, "_responder_orcamento", envia_logo):
            relatorio = self._avaliar(self.subconjuntos["aprovacao"])
        self.assertGreater(relatorio["duro"]["sem_aprovacao"], 0)
        self.assertEqual(relatorio["gate"]["veredicto"], "vermelho")

    def test_5_a_regressao_pt_br(self) -> None:
        """O lexicon desligado: os marcadores sobem face a referencia, e a regressao bloqueia."""
        from kamba_agr.social.politicas import Lexico

        ids = self.subconjuntos["pt_br"]
        referencia = self._referencia(ids)
        self.assertEqual(referencia["moles"]["pt_br_marcadores"]["com_marcador"], 0)
        with mock.patch.object(Lexico, "corrigir", lambda self, texto: texto), mock.patch.object(
            Lexico, "marcadores_em", lambda self, texto: []
        ):
            relatorio = self._avaliar(ids, referencia=referencia)
        self.assertGreater(relatorio["moles"]["pt_br_marcadores"]["com_marcador"], 0)
        self.assertEqual(relatorio["gate"]["veredicto"], "vermelho")
        self.assertTrue(any("pt-BR" in r for r in relatorio["gate"]["razoes"]))


# ------------------------------------------------------------------ o relatorio


class TestRelatorio(_ComDataset):
    def test_o_relatorio_nao_leva_conteudo_de_nenhuma_conversa(self) -> None:
        ids = [c.id for c in self.dataset.casos if c.adversarial in ("pt_br", "injeccao", "preco_inventado")]
        relatorio = json.dumps(self._avaliar(ids), ensure_ascii=False)
        for caso in self.dataset.casos:
            if caso.id not in ids:
                continue
            textos = [t.texto for t in caso.turnos] + list(caso.fixtures.get("gerador") or ())
            for texto in textos:
                if len(texto) > 12:
                    with self.subTest(caso=caso.id, texto=texto[:30]):
                        self.assertNotIn(texto, relatorio)
        self.assertNotIn(gd.CANARIO, relatorio)
        self.assertNotIn("Loja Kianda", relatorio)

    def test_duas_corridas_dao_o_mesmo_nos_gates_e_nas_metricas(self) -> None:
        ids = _ids(self.dataset)[::9]
        a, b = self._avaliar(ids), self._avaliar(ids)
        self.assertEqual(gd.comparar(a, b), [])

    def test_o_gate_mede_os_artefactos_do_criterio_9(self) -> None:
        medidos = set(gd.CODIGO_MEDIDO)
        for caminho in (
            "registry/dono.yaml",
            "registry/catalogo.yaml",
            "registry/social.yaml",
            "registry/orcamento.yaml",
            "policy/alegacoes",
            "templates/arte",
            "services/agr/src/kamba_agr/catalogo",  # o *parser* de precos do catalogo
            "services/agr/src/kamba_agr/orcamento",  # e o do orcamento
            "services/agr/src/kamba_agr/social",  # e a guarda de numeros das legendas
        ):
            with self.subTest(caminho=caminho):
                self.assertIn(caminho, medidos)
        artefactos = gd.artefactos(self.dataset, gd.ler_gate())
        self.assertIn("alias_social_text", artefactos)

    def test_um_artefacto_novo_caduca_a_impressao(self) -> None:
        antes = gd.impressao_do_codigo()
        with tempfile.TemporaryDirectory() as tmp:
            gate = Path(tmp) / "dono.yaml"
            gate.write_text(gd.GATE.read_text(encoding="utf-8") + "\n# outro\n", encoding="utf-8")
            self.assertNotEqual(gd.impressao_do_codigo(gate), antes)

    def test_o_tecto_de_tempo_e_lido_do_gate(self) -> None:
        gate = gd.ler_gate()
        relatorio = self._avaliar(_ids(self.dataset)[:2])
        relatorio["monitorizado"]["segundos"] = float(gate["tempo"]["segundos_maximo"]) + 1
        decisao = gd.decidir(relatorio, gate, None, parcial=False)
        self.assertTrue(any(r.startswith("tempo") for r in decisao["razoes"]))


if __name__ == "__main__":
    unittest.main()
