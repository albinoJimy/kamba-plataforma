"""O `AgentRegistry` (KAM-027): as quatro naturezas que o bloco pede.

    TestEsquema            unidade — a forma do YAML, positivo e `extra="forbid"`
    TestSeisNegativos      unidade — **uma negativa dedicada por validacao do §5.2**
    TestContratoDoGrafo    contrato — grafo LangGraph compilado com e sem os nos
    TestResolve            integracao — com e sem entitlement activo
    TestFicheirosReais     integracao — `registry/` deste repositorio passa
    TestArquitectura       arquitectura — nenhum nome de vertical no codigo do registo

**Os seis negativos sao o critero 1** e cada um mede **uma** validacao: o §5.2
tem seis, e um ficheiro invalido que falhasse por duas razoes nao provaria qual
delas morde. Cada teste do `TestSeisNegativos` parte do YAML valido, estraga
exactamente uma coisa, e confere que o erro nomeia aquela validacao.
"""

from __future__ import annotations

import unittest
from pathlib import Path
from typing import TypedDict

from langgraph.graph import StateGraph

from kamba_agr import registo
from kamba_agr.tls.catalogo import ESPECIFICACOES_DO_PILOTO, catalogo_do_piloto
from kamba_agr.metricas import (
    ETIQUETA,
    METRICA_REGISTO_NEGADO,
    MOTIVOS_DE_NEGACAO,
    EtiquetaInvalida,
    MetricasDoAgr,
)
from kamba_agr.registo import esquema, validar

RAIZ = Path(__file__).resolve().parents[3]

VENDEDOR = """\
id: vendedor
version: 1.0.0
phase: P
persona:
  nome: "Vendedor"
  idioma: pt
  apresentacao: "Sou o assistente automatico de {loja}."
graph: kamba_agr.verticais.vendedor:build_graph
tools: [search_catalog, criar_pedido]
entitlements:
  modulo: vendedor
  limites: [msgs_ai_mes, valor_max_pedido_minor]
subscriptions:
  - { tipo: payment.confirmed, versao: 1 }
models: { router: kamba-router, chat: kamba-chat }
golden: { dataset: "golden/vendedor/v1" }
"""

GATES = """\
version: 1.0.0
gates:
  vendedor:
    golden: golden/vendedor/v1
    validacoes:
      tools: { modo: aviso, credor: KAM-028 }
      grafo: { modo: aviso, credor: KAM-031 }
      golden: { modo: aviso, credor: KAM-040 }
"""


class CatalogoFalso:
    """Um catalogo da ToolLayer, para a validacao (1). O KAM-028 traz o real."""

    def __init__(self, tools: dict[str, set[str]]) -> None:
        self._tools = tools

    def nomes(self) -> frozenset[str]:
        return frozenset(self._tools)

    def parametros_visiveis(self, tool: str) -> frozenset[str]:
        return frozenset(self._tools[tool])


class Estado(TypedDict):
    x: int


def grafo_com(*nos: str):
    """Um grafo LangGraph **compilado** com estes nos. Nao e um duplo."""
    construtor = StateGraph(Estado)
    for no in nos:
        construtor.add_node(no, lambda estado: estado)
    construtor.set_entry_point(nos[0])
    return construtor.compile()


def ambiente(**trocas) -> validar.AmbienteDoRegisto:
    """O ambiente com as tres fontes reais e as duas portas desligadas."""
    base = {
        "fase": "piloto",
        "chaves_de_limite": frozenset({"msgs_ai_mes", "valor_max_pedido_minor", "marcacoes_mes"}),
        "eventos": {"payment.confirmed": frozenset({1, 2})},
        "raiz": RAIZ,
    }
    return validar.AmbienteDoRegisto(**{**base, **trocas})


def escrever(pasta: Path, **ficheiros: str) -> Path:
    for nome, texto in ficheiros.items():
        (pasta / f"{nome}.yaml").write_text(texto, encoding="utf-8")
    return pasta


class TestEsquema(unittest.TestCase):
    """Unidade: a forma do §5.1, e o `extra="forbid"` dos Detalhes Tecnicos."""

    def ler(self, texto: str) -> esquema.VerticalDoRegisto:
        caminho = Path(self.enterContext(__import__("tempfile").TemporaryDirectory())) / "v.yaml"
        caminho.write_text(texto, encoding="utf-8")
        return esquema.ler_vertical(caminho)

    def test_o_ficheiro_valido_le_se(self) -> None:
        vertical = self.ler(VENDEDOR)
        self.assertEqual(vertical.id, "vendedor")
        self.assertEqual(vertical.phase, "P")
        self.assertEqual(vertical.tools, ("search_catalog", "criar_pedido"))
        self.assertEqual(vertical.entitlements.modulo, "vendedor")
        self.assertEqual(vertical.subscriptions[0].versao, 1)
        self.assertEqual(vertical.golden.dataset, "golden/vendedor/v1")

    def test_uma_chave_a_mais_falha_a_qualquer_profundidade(self) -> None:
        """`extra="forbid"` — um `subscricoes:` dava uma vertical sem subscricao
        nenhuma, e a validacao (4) passava por nao ter nada para rejeitar."""
        for troca in (
            (VENDEDOR + "subscricoes: []\n"),
            VENDEDOR.replace("  idioma: pt", "  idioma: pt\n  lingua: pt"),
            VENDEDOR.replace("  modulo: vendedor", "  modulo: vendedor\n  ativo: true"),
            VENDEDOR.replace("{ tipo: payment.confirmed, versao: 1 }", "{ tipo: payment.confirmed, v: 1 }"),
            VENDEDOR.replace('golden: { dataset: "golden/vendedor/v1" }', 'golden: { dataset: "g", gate: "x" }'),
        ):
            with self.subTest(troca=troca[:40]):
                with self.assertRaises(esquema.FicheiroIlegivelError):
                    self.ler(troca)

    def test_campo_em_falta_falha(self) -> None:
        for linha in ("version: 1.0.0\n", "phase: P\n", "models: { router: kamba-router, chat: kamba-chat }\n"):
            with self.subTest(linha=linha), self.assertRaises(esquema.FicheiroIlegivelError):
                self.ler(VENDEDOR.replace(linha, ""))

    def test_a_versao_e_semver_nas_duas_formas(self) -> None:
        """As **duas**: a vertical e os gates.

        O `registry/gates.yaml` é também um ficheiro de `registry/`, e a regra 1
        do `registry/README.md` impõe SemVer a todo o directório. Nada media o
        lado dos gates, e a primeira versão reaproveitava o validador da
        vertical por uma via obscura — se ela tivesse falhado em silêncio, um
        `version: ultima` naquele ficheiro passava.
        """
        for versao in ("1.0", "v1.0.0", "1.0.0-rc1", "ultima", "1.0.0.0"):
            with self.subTest(versao=versao, forma="vertical"):
                with self.assertRaises(esquema.FicheiroIlegivelError):
                    self.ler(VENDEDOR.replace("version: 1.0.0", f"version: {versao}"))
            with self.subTest(versao=versao, forma="gates"):
                caminho = Path(self.enterContext(__import__("tempfile").TemporaryDirectory())) / "g.yaml"
                caminho.write_text(
                    GATES.replace("version: 1.0.0", f"version: {versao}"), encoding="utf-8"
                )
                with self.assertRaises(esquema.FicheiroIlegivelError):
                    esquema.ler_gates(caminho)

    def test_a_fase_e_um_dos_tres_valores(self) -> None:
        self.assertEqual(self.ler(VENDEDOR.replace("phase: P", "phase: D")).phase, "D")
        with self.assertRaises(esquema.FicheiroIlegivelError):
            self.ler(VENDEDOR.replace("phase: P", "phase: piloto"))

    def test_o_alvo_do_grafo_tem_de_ser_modulo_e_funcao(self) -> None:
        for alvo in ("kamba_agr.verticais.vendedor", "build_graph", ":build_graph", "a b:c"):
            with self.subTest(alvo=alvo), self.assertRaises(esquema.FicheiroIlegivelError):
                self.ler(VENDEDOR.replace("graph: kamba_agr.verticais.vendedor:build_graph", f"graph: {alvo}"))

    def test_tools_repetidas_falham(self) -> None:
        with self.assertRaises(esquema.FicheiroIlegivelError):
            self.ler(VENDEDOR.replace("[search_catalog, criar_pedido]", "[search_catalog, search_catalog]"))

    def test_yaml_que_nao_se_le(self) -> None:
        for texto in ("- a\n- b\n", "id: [a\n", "id: !!python/object:os.system {}\n"):
            with self.subTest(texto=texto), self.assertRaises(esquema.FicheiroIlegivelError):
                self.ler(texto)

    def test_o_aviso_exige_credor_e_o_bloqueio_recusa_o(self) -> None:
        for troca, razao in (
            ("tools: { modo: aviso }", "aviso sem credor"),
            ("tools: { modo: bloqueio, credor: KAM-028 }", "bloqueio com credor"),
            ("tools: { modo: aviso, credor: KAM-28 }", "ticket mal formado"),
            ("tool: { modo: aviso, credor: KAM-028 }", "validacao fora das seis"),
        ):
            with self.subTest(razao=razao):
                caminho = Path(self.enterContext(__import__("tempfile").TemporaryDirectory())) / "g.yaml"
                caminho.write_text(
                    GATES.replace("tools: { modo: aviso, credor: KAM-028 }", troca), encoding="utf-8"
                )
                with self.assertRaises(esquema.FicheiroIlegivelError):
                    esquema.ler_gates(caminho)


class TestSeisNegativos(unittest.TestCase):
    """Unidade: **uma negativa dedicada por validacao** do §5.2 (critero 1).

    Cada teste corre o registo com a validacao em `bloqueio` — nao em `aviso` —
    para medir que ela **falha o arranque**, que e o que o critero pede. O modo
    `aviso` que o `registry/gates.yaml` do repositorio declara para tres delas
    mede-se no `TestFicheirosReais`.
    """

    def setUp(self) -> None:
        self.pasta = Path(self.enterContext(__import__("tempfile").TemporaryDirectory()))

    def carregar(self, vertical: str = VENDEDOR, gates: str | None = None, **env):
        escrever(self.pasta, vendedor=vertical)
        if gates is not None:
            escrever(self.pasta, gates=gates)
        return registo.carregar(ambiente(**env), self.pasta)

    def erro(self, **kwargs) -> str:
        with self.assertRaises(registo.RegistoInvalidoError) as capturado:
            self.carregar(**kwargs)
        return str(capturado.exception)

    # ---- (1) tools -------------------------------------------------------------

    def test_1_uma_tool_fora_do_catalogo_da_tls_reprova(self) -> None:
        catalogo = CatalogoFalso({"search_catalog": set()})
        mensagem = self.erro(catalogo=catalogo)
        self.assertIn("[tools/vendedor]", mensagem)
        self.assertIn("`criar_pedido` nao existe no catalogo", mensagem)

    def test_1_uma_tool_que_expoe_tenant_id_ao_modelo_reprova(self) -> None:
        for proibido in validar.PARAMETROS_PROIBIDOS:
            with self.subTest(parametro=proibido):
                tools = CatalogoFalso(
                    {"search_catalog": {"query", proibido}, "criar_pedido": {"cart_id"}}
                )
                mensagem = self.erro(catalogo=tools)
                self.assertIn("[tools/vendedor]", mensagem)
                self.assertIn(f"'{proibido}'", mensagem)
        # E com um catalogo limpo a validacao (1) cala-se. Confere-se por
        # ausencia de `[tools/...]` e nao por «zero problemas»: as validacoes
        # (3) e (6) continuam sem fonte, e misturar as duas coisas era um
        # teste que passava a verde no dia em que o KAM-028 chegasse.
        limpo = CatalogoFalso({"search_catalog": {"query"}, "criar_pedido": {"cart_id"}})
        self.assertNotIn("[tools/vendedor]", self.erro(catalogo=limpo))

    def test_1_sem_catalogo_a_validacao_bloqueia_em_vez_de_passar(self) -> None:
        """Uma fonte que falta **nao** e uma validacao verde."""
        self.assertIn("o catalogo da ToolLayer nao esta ligado", self.erro())

    # ---- (2) entitlements ------------------------------------------------------

    def test_2_uma_chave_de_limite_fora_do_ten_reprova(self) -> None:
        mau = VENDEDOR.replace("valor_max_pedido_minor]", "valor_max_pedido_kz]")
        mensagem = self.erro(vertical=mau)
        self.assertIn("[entitlements/vendedor]", mensagem)
        self.assertIn("valor_max_pedido_kz", mensagem)

    def test_2_as_chaves_vem_do_ten_e_nao_de_uma_copia(self) -> None:
        """A fonte e `kamba_core.ten.CHAVES_DE_LIMITE`, nao uma lista daqui."""
        from kamba_core.ten import CHAVES_DE_LIMITE

        real = validar.AmbienteDoRegisto.do_repositorio(RAIZ, {})
        self.assertEqual(real.chaves_de_limite, frozenset(CHAVES_DE_LIMITE))
        self.assertIn("valor_max_pedido_minor", real.chaves_de_limite)
        self.assertNotIn("valor_max_pedido_kz", real.chaves_de_limite)

    # ---- (3) grafo -------------------------------------------------------------

    def test_3_um_grafo_sem_no_obrigatorio_reprova(self) -> None:
        for em_falta in validar.NOS_OBRIGATORIOS:
            with self.subTest(no=em_falta):
                nos = [n for n in validar.NOS_OBRIGATORIOS if n != em_falta]
                mensagem = self.erro(construir_grafo=lambda _v, nos=nos: grafo_com(*nos))
                self.assertIn("[grafo/vendedor]", mensagem)
                self.assertIn(em_falta, mensagem)

    def test_3_sem_forma_de_compilar_a_validacao_bloqueia(self) -> None:
        self.assertIn("nao ha como compilar o grafo", self.erro())

    # ---- (4) subscriptions -----------------------------------------------------

    def test_4_um_tipo_de_evento_desconhecido_reprova(self) -> None:
        mau = VENDEDOR.replace("payment.confirmed", "payment.recebido")
        mensagem = self.erro(vertical=mau)
        self.assertIn("[subscriptions/vendedor]", mensagem)
        self.assertIn("nao tem contrato", mensagem)

    def test_4_uma_versao_desconhecida_reprova_em_vez_de_ser_ignorada(self) -> None:
        mau = VENDEDOR.replace("versao: 1 }", "versao: 9 }")
        mensagem = self.erro(vertical=mau)
        self.assertIn("[subscriptions/vendedor]", mensagem)
        self.assertIn("as versoes publicadas sao v1, v2", mensagem)

    def test_4_o_catalogo_vem_dos_contratos_e_nao_de_uma_copia(self) -> None:
        real = validar.AmbienteDoRegisto.do_repositorio(RAIZ, {})
        self.assertEqual(real.eventos["payment.manual_confirmed"], frozenset({1, 2}))
        self.assertEqual(len(real.eventos), len(list((RAIZ / "contratos/eventos").iterdir())))

    # ---- (5) fase --------------------------------------------------------------

    def test_5_phase_d_com_kamba_fase_piloto_reprova(self) -> None:
        diferida = VENDEDOR.replace("phase: P", "phase: D")
        mensagem = self.erro(vertical=diferida, fase="piloto")
        self.assertIn("[fase/vendedor]", mensagem)
        self.assertIn("ADR-011", mensagem)

    def test_5_a_variavel_ausente_trata_se_como_piloto(self) -> None:
        """O `fluxo_piloto` do KAM-003: `piloto` e o unico valor que o canon
        define, e ausente a guarda levanta — nao se desliga."""
        diferida = VENDEDOR.replace("phase: P", "phase: D")
        self.assertIn("ausente", self.erro(vertical=diferida, fase=None))
        self.assertIn("[fase/vendedor]", self.erro(vertical=diferida, fase=""))

    def test_5_nenhum_valor_de_kamba_fase_deixa_passar_uma_vertical_diferida(self) -> None:
        """**A correcção de um achado da revisão adversarial.**

        A primeira versão lia `env.fase != FASE_PILOTO` como «já não é Piloto,
        logo o Fluxo B pode correr», e com isso um `KAMBA_FASE=clusters` escrito
        por engano no *deploy* punha o `assistente` em produção — exactamente o
        que o ADR-011 difere até haver resposta escrita da Meta (D2). Inventar um
        valor de fase é inventar canon: o `fluxo_piloto` do KAM-003 diz que
        `piloto` é o **único** valor que o canon define.

        A lista `FASES_POSTERIORES` está vazia de propósito, e é por isso que
        este teste é sobre «nenhum valor» e não sobre «estes valores».
        """
        diferida = VENDEDOR.replace("phase: P", "phase: D")
        self.assertEqual(validar.FASES_POSTERIORES, ())
        for fase in ("piloto", "clusters", "producao", "C", "", None, "PILOTO"):
            with self.subTest(fase=fase):
                mensagem = self.erro(vertical=diferida, fase=fase)
                self.assertIn("[fase/vendedor]", mensagem)
                self.assertIn("ADR-011", mensagem)

    # ---- (6) golden ------------------------------------------------------------

    def test_6_o_dataset_golden_que_nao_existe_reprova(self) -> None:
        mensagem = self.erro(vertical=VENDEDOR.replace("golden/vendedor/v1", "golden/nao_existe/v1"))
        self.assertIn("[golden/vendedor]", mensagem)
        self.assertIn("nao existe", mensagem)

    def test_6_sem_eval_harness_a_validacao_tem_sempre_um_problema(self) -> None:
        """Enquanto o KAM-040 nao existir nao ha como dizer que o gate esta verde,
        e isso devolve-se como problema — nao como silencio."""
        self.assertIn("nao ha eval harness", self.erro())

    # ---- o modo, e a coerencia entre ficheiros ---------------------------------

    def test_o_modo_aviso_passa_o_problema_a_aviso_e_nomeia_o_credor(self) -> None:
        _, _, adiadas = self.carregar(gates=GATES)
        self.assertEqual(
            sorted((a.validacao, a.vertical, a.credor) for a in adiadas),
            [
                ("golden", "vendedor", "KAM-040"),
                ("grafo", "vendedor", "KAM-031"),
                ("tools", "vendedor", "KAM-028"),
            ],
        )

    def test_o_codigo_de_uma_adiada_cabe_no_error_code_da_allowlist(self) -> None:
        """O campo e um identificador de 96 caracteres, nao uma frase.

        A primeira versao punha a prosa do problema em `error_code` e a
        *allowlist* deixava-a cair **em silencio**: um arranque que dizia ter
        registado os avisos e nao registava nenhum. Mede-se contra o validador
        real de `kamba_core.logger.politica`, nao contra uma leitura dele.
        """
        from kamba_core.logger.politica import validar

        _, _, adiadas = self.carregar(gates=GATES)
        self.assertTrue(adiadas)
        for adiada in adiadas:
            self.assertEqual(validar("error_code", adiada.codigo()), adiada.codigo())
        self.assertEqual(
            sorted({a.codigo() for a in adiadas}),
            ["golden_kam_040", "grafo_kam_031", "tools_kam_028"],
        )
        # E a prosa que la estava **nao** passa — e a razao de ser deste teste.
        self.assertIsNone(validar("error_code", "[tools/vendedor] o catalogo nao esta ligado"))

    def test_uma_validacao_em_aviso_nao_tapa_as_outras(self) -> None:
        """O `aviso` e por validacao: um registo com um limite errado continua a
        reprovar, por muito que o `tools` esteja em `aviso`."""
        mau = VENDEDOR.replace("valor_max_pedido_minor]", "limite_inventado]")
        with self.assertRaises(registo.RegistoInvalidoError) as capturado:
            self.carregar(vertical=mau, gates=GATES)
        self.assertIn("[entitlements/vendedor]", str(capturado.exception))

    def test_o_aviso_cala_a_fonte_em_falta_e_nao_um_problema_real(self) -> None:
        """**A correcção do achado mais sério da revisão adversarial.**

        Com o `tools` em `aviso` e um catálogo **ligado** em que falta uma tool,
        o arranque tem de falhar: o `aviso` adia «não há catálogo», não «a tool
        não existe». Sem isto, no dia em que o KAM-028 ligasse o catálogo, a
        linha do `gates.yaml` sobrevivia e uma tool que exponha `tenant_id` ao
        modelo passava a aviso — o mecanismo de adiamento a engolir o defeito
        que a validação existe para apanhar.
        """
        parcial = CatalogoFalso({"search_catalog": set()})  # falta `criar_pedido`
        with self.assertRaises(registo.RegistoInvalidoError) as capturado:
            self.carregar(gates=GATES, catalogo=parcial)
        self.assertIn("`criar_pedido` nao existe no catalogo", str(capturado.exception))

        expoe = CatalogoFalso({"search_catalog": {"tenant_id"}, "criar_pedido": set()})
        with self.assertRaises(registo.RegistoInvalidoError) as capturado:
            self.carregar(gates=GATES, catalogo=expoe)
        self.assertIn("'tenant_id'", str(capturado.exception))

        # E o mesmo para o grafo: um nó em falta bloqueia, com o `grafo` em aviso.
        nos = [n for n in validar.NOS_OBRIGATORIOS if n != "send"]
        with self.assertRaises(registo.RegistoInvalidoError) as capturado:
            self.carregar(gates=GATES, construir_grafo=lambda _v: grafo_com(*nos))
        self.assertIn("faltam os nos obrigatorios ['send']", str(capturado.exception))

    def test_um_aviso_que_sobreviveu_ao_credor_e_erro(self) -> None:
        """«Fechar um aviso é apagar uma linha» tem de ser **imposto**.

        Com a fonte ligada e sem problema nenhum, a linha do `gates.yaml` está
        morta — e uma declaração que nenhuma superfície usa falha o gate, como no
        `canon/extensoes.yaml`. Sem este erro, a linha ficava a adiar o que já
        não é adiável, e era só uma questão de tempo até calar um defeito.
        """
        limpo = CatalogoFalso({"search_catalog": set(), "criar_pedido": set()})
        with self.assertRaises(registo.RegistoInvalidoError) as capturado:
            self.carregar(gates=GATES, catalogo=limpo)
        mensagem = str(capturado.exception)
        self.assertIn("sobreviveu ao credor", mensagem)
        self.assertIn("[tools/vendedor]", mensagem)
        self.assertIn("KAM-028", mensagem)
        # Com a linha apagada, o mesmo registo carrega.
        sem_tools = GATES.replace("      tools: { modo: aviso, credor: KAM-028 }\n", "")
        _, _, adiadas = self.carregar(gates=sem_tools, catalogo=limpo)
        self.assertEqual(sorted(a.validacao for a in adiadas), ["golden", "grafo"])

    def test_um_modo_bloqueio_escrito_por_extenso_bloqueia(self) -> None:
        """O `bloqueio` escrito nao e o mesmo que o `bloqueio` por omissao.

        **Uma mutacao sobreviveu por falta deste teste.** O `aviso` e um dos dois
        modos, e a condicao do `carregar` compara-o; trocada por «tem gate, logo
        avisa», tudo o que o `gates.yaml` nomeasse passava a aviso — e nenhum
        teste dava por isso, porque nenhum escrevia `modo: bloqueio`. Os outros
        dois casos de `bloqueio` que ja estavam medidos sao ambos por **omissao**
        (a linha apagada, e a validacao que o ficheiro nunca nomeia), e a
        omissao nao passa por esta comparacao.
        """
        bloqueante = GATES.replace(
            "tools: { modo: aviso, credor: KAM-028 }", "tools: { modo: bloqueio }"
        )
        with self.assertRaises(registo.RegistoInvalidoError) as capturado:
            self.carregar(gates=bloqueante)
        self.assertIn("[tools/vendedor]", str(capturado.exception))
        # E as outras duas continuam em aviso: o modo e **por validacao**.
        _, _, adiadas = self.carregar(
            catalogo=CatalogoFalso({"search_catalog": set(), "criar_pedido": set()}),
            gates=bloqueante,
        )
        self.assertEqual(sorted(a.validacao for a in adiadas), ["golden", "grafo"])

    def test_apagar_a_linha_do_gates_torna_cada_validacao_bloqueante(self) -> None:
        """`bloqueio` e a omissao, e e isso que faz do `gates.yaml` um registo e
        nao um interruptor: fechar um `aviso` e **apagar** uma linha.

        **As tres, uma a uma.** A primeira versao deste teste media so a linha do
        `tools`, e o critério 8 — que é sobre o `golden` — ficava provado pela
        linha errada. Achado da revisão adversarial.
        """
        linhas = {
            "tools": "      tools: { modo: aviso, credor: KAM-028 }\n",
            "grafo": "      grafo: { modo: aviso, credor: KAM-031 }\n",
            "golden": "      golden: { modo: aviso, credor: KAM-040 }\n",
        }
        for validacao, linha in linhas.items():
            with self.subTest(validacao=validacao):
                sem_ela = GATES.replace(linha, "")
                with self.assertRaises(registo.RegistoInvalidoError) as capturado:
                    self.carregar(gates=sem_ela)
                self.assertIn(f"[{validacao}/vendedor]", str(capturado.exception))

    def test_o_dataset_golden_tem_de_coincidir_nos_dois_ficheiros(self) -> None:
        divergente = GATES.replace("golden: golden/vendedor/v1", "golden: golden/outro/v1")
        with self.assertRaises(registo.RegistoInvalidoError) as capturado:
            self.carregar(gates=divergente)
        self.assertIn("nao coincide", str(capturado.exception))

    def test_um_gate_orfao_reprova(self) -> None:
        orfao = GATES.replace("  vendedor:", "  servicos:")
        with self.assertRaises(registo.RegistoInvalidoError) as capturado:
            self.carregar(gates=orfao)
        self.assertIn("gate orfao", str(capturado.exception))

    def test_um_registo_vazio_reprova(self) -> None:
        with self.assertRaises(registo.RegistoInvalidoError) as capturado:
            registo.carregar(ambiente(), self.pasta)
        self.assertIn("nao tem vertical nenhuma", str(capturado.exception))

    def test_um_directorio_que_nao_existe_reprova(self) -> None:
        with self.assertRaises(registo.RegistoInvalidoError) as capturado:
            registo.carregar(ambiente(), self.pasta / "nao_existe")
        self.assertIn("nao existe", str(capturado.exception))

    def test_a_forma_escolhe_se_pela_chave_de_topo_e_nao_pelo_nome(self) -> None:
        escrever(self.pasta, tarifas=GATES, qualquer_nome=VENDEDOR)
        _, _, adiadas = registo.carregar(ambiente(), self.pasta)
        self.assertTrue(adiadas, "o `gates` de um ficheiro chamado `tarifas.yaml` aplicou-se")

    def test_os_planos_do_kam_009_saltam_se(self) -> None:
        escrever(self.pasta, vendedor=VENDEDOR, gates=GATES, plans="version: 1.0.0\nplans: {}\n")
        registo.carregar(ambiente(), self.pasta)

    def test_a_mesma_vertical_duas_vezes_reprova(self) -> None:
        escrever(self.pasta, a=VENDEDOR, b=VENDEDOR, gates=GATES)
        with self.assertRaises(registo.RegistoInvalidoError) as capturado:
            registo.carregar(ambiente(), self.pasta)
        self.assertIn("mais do que uma vez", str(capturado.exception))


class TestContratoDoGrafo(unittest.TestCase):
    """Contrato: um grafo **LangGraph compilado**, com e sem os nos obrigatorios.

    Contra o `CompiledStateGraph` real e nao contra um duplo nosso: um duplo
    provaria que o `nos_do_grafo` le o nosso proprio objecto, e nao que le o
    grafo que o KAM-031 vai la pôr. E a razao pela qual o `langgraph` entrou no
    fecho neste ticket (`requirements/runtime.in`).
    """

    def test_os_seis_nos_sao_os_do_desenho(self) -> None:
        self.assertEqual(
            validar.NOS_OBRIGATORIOS,
            ("ingest", "guard_in", "validate", "guard_out", "send", "handoff_wait"),
        )

    def test_um_grafo_com_os_seis_passa(self) -> None:
        self.assertEqual(
            validar.nos_do_grafo(grafo_com(*validar.NOS_OBRIGATORIOS)),
            frozenset(validar.NOS_OBRIGATORIOS),
        )

    def test_os_sentinelas_do_langgraph_nao_contam_como_nos(self) -> None:
        """O `__start__` esta no `nodes` de qualquer grafo compilado, e nao e um
        no de desenho. Se contasse, um grafo vazio tinha um no."""
        compilado = grafo_com(*validar.NOS_OBRIGATORIOS)
        self.assertIn("__start__", compilado.nodes)
        self.assertNotIn("__start__", validar.nos_do_grafo(compilado))

    def test_um_grafo_com_mais_nos_passa(self) -> None:
        """A validacao e por inclusao: uma vertical acrescenta os nos dela
        (§5.4, «Regra de dois»)."""
        com_extras = grafo_com(*validar.NOS_OBRIGATORIOS, "retrieve", "cart_build")
        self.assertEqual(validar.nos_do_grafo(com_extras) & set(validar.NOS_OBRIGATORIOS), set(validar.NOS_OBRIGATORIOS))

    def test_falta_um_no_e_a_validacao_nomeia_qual(self) -> None:
        vertical = esquema.VerticalDoRegisto.model_validate(
            __import__("yaml").safe_load(VENDEDOR)
        )
        for em_falta in validar.NOS_OBRIGATORIOS:
            with self.subTest(no=em_falta):
                nos = [n for n in validar.NOS_OBRIGATORIOS if n != em_falta]
                problemas = validar.validar_grafo(
                    vertical, ambiente(construir_grafo=lambda _v, nos=nos: grafo_com(*nos))
                )
                self.assertEqual(len(problemas), 1)
                self.assertIn(em_falta, problemas[0])

    def test_um_grafo_que_nao_compila_e_um_registo_invalido(self) -> None:
        vertical = esquema.VerticalDoRegisto.model_validate(
            __import__("yaml").safe_load(VENDEDOR)
        )

        def rebenta(_v):
            raise RuntimeError("falta o checkpointer")

        problemas = validar.validar_grafo(vertical, ambiente(construir_grafo=rebenta))
        self.assertEqual(len(problemas), 1)
        self.assertIn("nao compila", problemas[0])
        self.assertIn("RuntimeError", problemas[0])


class EntitlementFalso:
    def __init__(self, permitido: bool) -> None:
        self.permitido = permitido


class MetricasEspia:
    def __init__(self) -> None:
        self.contadas: list[tuple[str, str | None]] = []

    def contar(self, metrica: str, etiqueta: str | None = None, quanto: int = 1) -> None:
        self.contadas.append((metrica, etiqueta))


class ContextoFalso:
    def __init__(self, tenant_id: str, vertical: str) -> None:
        self.tenant_id = tenant_id
        self.vertical = vertical


TENANT = "6f9a1a1e-1111-4b2c-8888-000000000001"


class TestResolve(unittest.TestCase):
    """Integracao: `resolve` com e sem entitlement activo (critero 6)."""

    def setUp(self) -> None:
        self.pasta = escrever(
            Path(self.enterContext(__import__("tempfile").TemporaryDirectory())),
            vendedor=VENDEDOR,
            gates=GATES,
        )
        self.pedidos: list[tuple[str, str]] = []
        self.metricas = MetricasEspia()

    def registo_com(self, permitido: bool) -> registo.AgentRegistry:
        def ler(tenant: str, modulo: str) -> EntitlementFalso:
            self.pedidos.append((tenant, modulo))
            return EntitlementFalso(permitido)

        reg = registo.AgentRegistry(ler_entitlement=ler, metricas=self.metricas)
        reg.load_all(ambiente(), self.pasta)
        return reg

    def test_com_entitlement_activo_devolve_a_vertical(self) -> None:
        resolucao = self.registo_com(True).resolve(ContextoFalso(TENANT, "vendedor"))
        self.assertIsNotNone(resolucao.vertical)
        self.assertEqual(resolucao.vertical.id, "vendedor")
        self.assertIsNone(resolucao.resposta)
        self.assertEqual(self.metricas.contadas, [])

    def test_sem_entitlement_activo_devolve_a_resposta_estatica_e_alerta(self) -> None:
        resolucao = self.registo_com(False).resolve(ContextoFalso(TENANT, "vendedor"))
        self.assertIsNone(resolucao.vertical)
        self.assertEqual(resolucao.resposta, registo.RESPOSTA_SEM_ENTITLEMENT)
        self.assertEqual(resolucao.motivo, "sem_entitlement")
        self.assertEqual(self.metricas.contadas, [(METRICA_REGISTO_NEGADO, "sem_entitlement")])

    def test_o_entitlement_le_se_com_o_tenant_do_contexto_e_o_modulo_da_vertical(self) -> None:
        """DoD: «`resolve` usa o `tenant_id` do contexto». Nao ha outra porta por
        onde um `tenant_id` possa entrar — o `ContextoFalso` e o unico argumento."""
        self.registo_com(True).resolve(ContextoFalso(TENANT, "vendedor"))
        self.assertEqual(self.pedidos, [(TENANT, "vendedor")])

    def test_uma_vertical_que_o_registo_nao_tem_devolve_a_mesma_resposta(self) -> None:
        resolucao = self.registo_com(True).resolve(ContextoFalso(TENANT, "servicos"))
        self.assertEqual(resolucao.resposta, registo.RESPOSTA_SEM_ENTITLEMENT)
        self.assertEqual(resolucao.motivo, "vertical_desconhecida")
        self.assertEqual(self.pedidos, [], "nao se le entitlement de uma vertical que nao existe")
        self.assertEqual(self.metricas.contadas, [(METRICA_REGISTO_NEGADO, "vertical_desconhecida")])

    def test_uma_so_vertical_principal_por_numero(self) -> None:
        """Piloto: o que decide e o `ctx.vertical`. Com duas verticais carregadas,
        um contexto de `vendedor` nunca devolve `servicos`."""
        servicos = (
            VENDEDOR.replace("id: vendedor", "id: servicos")
            .replace("modulo: vendedor", "modulo: servicos")
            .replace("valor_max_pedido_minor]", "marcacoes_mes]")
            .replace("golden/vendedor/v1", "golden/servicos/v1")
            .replace("kamba_agr.verticais.vendedor", "kamba_agr.verticais.servicos")
        )
        escrever(
            self.pasta,
            servicos=servicos,
            gates=GATES
            + "  servicos:\n    golden: golden/servicos/v1\n    validacoes:\n"
            "      tools: { modo: aviso, credor: KAM-028 }\n"
            "      grafo: { modo: aviso, credor: KAM-035 }\n"
            "      golden: { modo: aviso, credor: KAM-040 }\n",
        )
        reg = self.registo_com(True)
        self.assertEqual(sorted(reg.verticais), ["servicos", "vendedor"])
        self.assertEqual(reg.resolve(ContextoFalso(TENANT, "vendedor")).vertical.id, "vendedor")
        self.assertEqual(reg.resolve(ContextoFalso(TENANT, "servicos")).vertical.id, "servicos")

    def test_resolve_antes_de_load_all_levanta_em_vez_de_recusar(self) -> None:
        """«Nao ha vertical» e uma resposta; «ninguem carregou o registo» e um
        defeito, e os dois nao se confundem."""
        reg = registo.AgentRegistry(ler_entitlement=lambda t, m: EntitlementFalso(True))
        with self.assertRaises(registo.RegistoInvalidoError):
            reg.resolve(ContextoFalso(TENANT, "vendedor"))

    def test_o_alerta_conta_contra_as_metricas_reais_e_nao_so_contra_um_duplo(self) -> None:
        """**O teste que faltava, e que apanhou um defeito real.**

        Os outros desta classe usam o `MetricasEspia`, e com ele o critério 6
        passava: um duplo conta o que lhe derem. O `MetricasDoAgr` **nao**: um
        contador que o `metricas.py` nao conheca levanta `EtiquetaInvalida`
        («contador desconhecido»), e o `agr_registry_denied_total` nao estava la.
        Em producao o `resolve` rebentava no primeiro tenant sem plano — com a
        bateria toda verde.

        Mede-se contra uma instancia **propria** de `MetricasDoAgr` e nao contra
        o `METRICAS` do modulo: aquele e global, e um teste que lhe somasse
        deixava o numero sujo para os outros.
        """
        reais = MetricasDoAgr()
        reg = registo.AgentRegistry(
            ler_entitlement=lambda t, m: EntitlementFalso(False), metricas=reais
        )
        reg.load_all(ambiente(), self.pasta)
        self.assertEqual(
            reg.resolve(ContextoFalso(TENANT, "vendedor")).motivo, "sem_entitlement"
        )
        self.assertEqual(
            reg.resolve(ContextoFalso(TENANT, "nao_existe")).motivo, "vertical_desconhecida"
        )
        exposicao = reais.exposicao()
        for motivo in MOTIVOS_DE_NEGACAO:
            self.assertIn(f'{METRICA_REGISTO_NEGADO}{{motivo="{motivo}"}} 1', exposicao)

    def test_o_motivo_e_etiqueta_valida_e_nunca_leva_o_tenant(self) -> None:
        """`OBS-I`: nenhuma etiqueta leva identificadores. A gramatica de
        `metricas.py` recusa um `tenant_id` pela forma — aqui mede-se que os
        motivos que chegam a metrica sao **exactamente** a lista fechada que o
        `metricas.py` registou para ela, e que um motivo de fora e recusado."""
        self.registo_com(False).resolve(ContextoFalso(TENANT, "vendedor"))
        self.registo_com(True).resolve(ContextoFalso(TENANT, "nao_existe"))
        self.assertEqual(
            sorted(e for _, e in self.metricas.contadas), sorted(MOTIVOS_DE_NEGACAO)
        )
        for _, etiqueta in self.metricas.contadas:
            self.assertTrue(ETIQUETA.match(etiqueta))
            self.assertNotIn(TENANT, etiqueta)
        self.assertIsNone(ETIQUETA.match(TENANT), "um tenant_id nao casa a gramatica")
        with self.assertRaises(EtiquetaInvalida):
            MetricasDoAgr().contar(METRICA_REGISTO_NEGADO, "motivo_inventado")


class TestFicheirosReais(unittest.TestCase):
    """Integracao: o `registry/` **deste** repositorio carrega e valida."""

    def test_o_registo_do_repositorio_carrega_com_dois_avisos_por_vertical(self) -> None:
        """**Eram tres, e passaram a dois com o KAM-028.**

        A validacao (1) (`tools`) fechou: o catalogo da ToolLayer existe, o
        `registry/gates.yaml` deixou de ter a linha `tools: { modo: aviso }`, e
        ela corre em `bloqueio`. Sobram a (3) `grafo` (KAM-031/035) e a (6)
        `golden` (KAM-040).

        **E por isso que este teste passa o `catalogo`.** Sem ele a validacao
        devolve um `PorLigar` que, sem a linha no `gates.yaml`, nao e calado por
        nada — e o registo recusa-se a carregar. Isso **e** o mecanismo a
        funcionar: era o que ia acontecer em producao ao primeiro arranque se o
        `__main__` nao o passasse.
        """
        verticais, gates, adiadas = registo.carregar(
            validar.AmbienteDoRegisto.do_repositorio(
                RAIZ, {"KAMBA_FASE": "piloto"}, catalogo=catalogo_do_piloto()
            ),
            RAIZ / "registry",
        )
        self.assertEqual(sorted(verticais), ["servicos", "vendedor"])
        self.assertEqual(sorted(gates), ["servicos", "vendedor"])
        self.assertEqual(
            sorted((a.validacao, a.vertical, a.credor) for a in adiadas),
            [
                ("golden", "servicos", "KAM-040"),
                ("golden", "vendedor", "KAM-040"),
                ("grafo", "servicos", "KAM-035"),
                ("grafo", "vendedor", "KAM-031"),
            ],
        )

    def test_com_o_catalogo_ligado_a_validacao_das_tools_morde(self) -> None:
        """A prova de que fechar o `aviso` nao foi trocar um silencio por outro.

        Com o catalogo ligado, uma tool que ele **nao** conheca reprova o
        arranque — e nao vira aviso, porque a linha do `gates.yaml` ja nao
        existe. Sem este teste, «a validacao (1) corre em bloqueio» era uma
        afirmacao sobre um ficheiro e nao sobre o que acontece.
        """
        from kamba_agr.tls.especificacoes import Catalogo

        magro = Catalogo(
            tuple(
                e for e in ESPECIFICACOES_DO_PILOTO if e.nome != "search_catalog"
            )
        )
        with self.assertRaises(registo.RegistoInvalidoError) as capturado:
            registo.carregar(
                validar.AmbienteDoRegisto.do_repositorio(
                    RAIZ, {"KAMBA_FASE": "piloto"}, catalogo=magro
                ),
                RAIZ / "registry",
            )
        self.assertIn("search_catalog", str(capturado.exception))
        self.assertIn("nao existe no catalogo", str(capturado.exception))

    def test_as_duas_verticais_subscrevem_os_dois_eventos_de_pagamento(self) -> None:
        """Dicionario §3.5: quem nao distingue os dois caminhos subscreve os dois.
        E o gate da Fase 0 — o `payment.manual_confirmed` de um pedido do
        Vendedor e consumido pelo handler de Servicos (KAM-108)."""
        verticais, _, _ = registo.carregar(
            validar.AmbienteDoRegisto.do_repositorio(
                RAIZ, {"KAMBA_FASE": "piloto"}, catalogo=catalogo_do_piloto()
            ),
            RAIZ / "registry",
        )
        for vertical in verticais.values():
            tipos = {s.tipo for s in vertical.subscriptions}
            self.assertIn("payment.confirmed", tipos)
            self.assertIn("payment.manual_confirmed", tipos)

    def test_nenhuma_vertical_do_repositorio_esta_em_fase_diferida(self) -> None:
        """ADR-011: o `assistente` do Fluxo B nunca esta activo no Piloto, e a
        forma mais barata de o garantir e nao existir ficheiro nenhum dele."""
        verticais, _, _ = registo.carregar(
            validar.AmbienteDoRegisto.do_repositorio(
                RAIZ, {"KAMBA_FASE": "piloto"}, catalogo=catalogo_do_piloto()
            ),
            RAIZ / "registry",
        )
        self.assertEqual({v.phase for v in verticais.values()}, {"P"})
        self.assertFalse((RAIZ / "registry/assistente.yaml").exists())

    def test_cada_ficheiro_do_registo_le_se_pelos_tres_leitores(self) -> None:
        """**O teste que faltava, e sem o qual o *gate* 7 foi o primeiro a saber.**

        Há **três** leitores de YAML a tocar `registry/*.yaml`, e não um:

        | Leitor | Quem o usa | Mapas em estilo de fluxo |
        |---|---|---|
        | `tools/canon_lint/yamlreg.py` | *gate* 3b | aceita |
        | `yaml.safe_load` (PyYAML) | o `AgentRegistry`, em execução | aceita |
        | `tools/kamba_yaml.py` | *gates* 7, 9 e 11 | **recusa** |

        Os três ficheiros nasceram em estilo de fluxo — copiado à letra do
        exemplo de `docs/tecnica/02` §5.1 e do exemplo do bloco do KAM-027 —, os
        dois primeiros leitores leram-nos, as baterias passaram, e o *gate* 7
        rebentou com `mapa em estilo de fluxo nao suportado`. Um ficheiro que só
        um dos leitores entende é um ficheiro que funciona até ao CI.

        Quem escreve em `registry/` escreve para o **mais estrito dos três**, e é
        isto que o impõe antes de o CI o fazer.
        """
        import sys

        import yaml

        sys.path.insert(0, str(RAIZ / "tools"))
        try:
            import kamba_yaml
            from canon_lint import yamlreg
        finally:
            sys.path.remove(str(RAIZ / "tools"))

        ficheiros = sorted((RAIZ / "registry").glob("*.yaml"))
        self.assertGreaterEqual(len(ficheiros), 4, "nao ha ficheiros de registo para ler")
        for caminho in ficheiros:
            fonte = caminho.read_text(encoding="utf-8")
            with self.subTest(ficheiro=caminho.name):
                pelo_estrito = kamba_yaml.load_file(caminho)
                # E os três têm de dar o **mesmo** documento: um leitor que
                # aceite e leia outra coisa é pior do que um que recuse.
                self.assertEqual(pelo_estrito, yaml.safe_load(fonte), "kamba_yaml vs PyYAML")
                self.assertEqual(pelo_estrito, yamlreg.ler(fonte), "kamba_yaml vs yamlreg")

    def test_os_seis_nos_e_as_onze_tools_batem_com_o_dicionario(self) -> None:
        """**O teste que a isenção do *gate* 3b promete.**

        A entrada de `ci/canon-lint.yaml` que tira
        `services/agr/src/kamba_agr/registo/*` da superfície do registo
        justifica-se com «há um teste de arquitectura que prende os seis nós e as
        onze tools ao dicionário, lido como texto». A revisão adversarial notou
        que esse teste **não existia** — a isenção estava a invocar uma garantia
        que ninguém escrevera. É este.

        Lê o dicionário exportado (`canon/dicionario.yaml`), que é o que o *gate*
        3b lê, e não o Markdown: é a mesma fonte, e assim um `dict_export` por
        correr aparece aqui também.
        """
        import sys

        sys.path.insert(0, str(RAIZ / "tools"))
        try:
            from canon_lint.dicionario import Saber

            saber = Saber.ler(RAIZ)
        finally:
            sys.path.remove(str(RAIZ / "tools"))

        # As onze tools: cada nome do catálogo das duas verticais é tool do §3.
        do_registo: set[str] = set()
        for vertical in registo.carregar(
            validar.AmbienteDoRegisto.do_repositorio(
                RAIZ, {"KAMBA_FASE": "piloto"}, catalogo=catalogo_do_piloto()
            ),
            RAIZ / "registry",
        )[0].values():
            do_registo.update(vertical.tools)
        self.assertEqual(len(do_registo), 11, sorted(do_registo))
        for tool in sorted(do_registo):
            self.assertTrue(
                saber.conhecido(tool, "tool"),
                f"`{tool}` está em `registry/` e não é tool do dicionário §3",
            )

        # Os seis nós: estão no dicionário, e a lista do código é **igual** à
        # que a emenda 1.35 escreve — não um subconjunto dela.
        texto = (RAIZ / "specs/02_Dicionario_de_Dados_Canonico.md").read_text(encoding="utf-8")
        linha = next(
            l for l in texto.splitlines() if l.startswith("| Nós obrigatórios de um grafo |")
        )
        import re

        nomes = tuple(re.findall(r"`([a-z_]+)`", linha.split("|")[2]))
        self.assertEqual(nomes, validar.NOS_OBRIGATORIOS, f"a linha do §3.26 diz {nomes}")

        # E os quatro parâmetros proibidos, pela mesma razão.
        proibidos = next(
            l for l in texto.splitlines()
            if l.startswith("| Parâmetros proibidos no esquema visível ao modelo |")
        )
        self.assertEqual(
            tuple(re.findall(r"`([a-z_]+)`", proibidos.split("|")[2])),
            validar.PARAMETROS_PROIBIDOS,
        )

    def test_as_seis_validacoes_do_codigo_sao_as_que_o_gate_3b_aceita(self) -> None:
        """A lista fechada esta em dois sitios — aqui e em
        `tools/canon_lint/registo.py` — e tem de ser a mesma, senao um
        `registry/gates.yaml` passa o gate e nao se aplica, ou o contrario."""
        import sys

        sys.path.insert(0, str(RAIZ / "tools"))
        try:
            from canon_lint.registo import VALIDACOES_DO_ARRANQUE
        finally:
            sys.path.remove(str(RAIZ / "tools"))
        self.assertEqual(tuple(validar.VALIDACOES), VALIDACOES_DO_ARRANQUE)
        self.assertEqual(esquema.VALIDACOES, VALIDACOES_DO_ARRANQUE)


class TestArquitectura(unittest.TestCase):
    """Arquitectura: **nenhum nome de vertical no codigo do registo**.

    Le a fonte e nao corre codigo: um critero «0 ocorrencias» nao se prova
    exercitando caminhos. E tem o controlo que o padrao do EPIC-02 manda ter —
    exigir que haja ficheiros para ler, porque um `glob` sobre a pasta errada
    devolve lista vazia e o ciclo passa sempre.

    **O ambito e `registo/`, e nao o servico — e a diferenca importa.** O
    critero 4 do bloco diz «nenhuma referencia a nomes de vertical no codigo do
    registo (`core/`)», e e isso que se mede. O resto do AGR **tem** nomes de
    vertical: o `contexto.py` do KAM-025 valida `vertical` contra uma lista de
    permitidos `("vendedor", "servicos")`, de propósito e com a razao escrita
    (critero 5 do KAM-014, lista de permitidos e nao de proibidos).

    A consequencia tem dono e esta registada: a vertical `catalogo` do KAM-118 e
    **recusada a porta** do `/internal/turn` enquanto aquela lista nao a
    incluir, por muito que este registo a carregue sem problema. E divida
    documental 98, nao defeito deste ticket — achado da revisao adversarial.
    """

    #: Os valores de `id` do dicionario canonico §3.2, mais o `assistente` do
    #: Fluxo B, que nao e sequer um `id` canonico e e o que o ADR-011 difere.
    VERTICAIS = ("vendedor", "servicos", "catalogo", "social", "orcamento", "assistente")

    def modulos(self) -> list[Path]:
        pasta = RAIZ / "services/agr/src/kamba_agr/registo"
        ficheiros = sorted(pasta.glob("*.py"))
        self.assertGreaterEqual(len(ficheiros), 3, f"nao ha fonte para ler em {pasta}")
        return ficheiros

    def test_nenhum_literal_do_codigo_do_registo_e_um_nome_de_vertical(self) -> None:
        """Procura-se o nome **como literal**, que e a forma de o codigo decidir
        por ele: um `if ctx.vertical == "vendedor"`, um `{"servicos": ...}`, um
        `elif id in ("vendedor", "servicos")`.

        **As duas primeiras versoes deste teste estavam erradas, e pela mesma
        razao.** Procuravam a **subcadeia** `catalogo`, que e um `id` de vertical
        do §3.7 e tambem a palavra portuguesa para o catalogo da ToolLayer: a
        primeira falhou no nome da variavel `catalogo`, e a segunda na mensagem
        de erro «nao existe no catalogo da ToolLayer». Nenhuma das duas e uma
        decisao por vertical, e proibir uma palavra corrente e a receita do
        ADR-L001 §10 — «um gate que bloqueia o que ninguem escolheu e um gate
        que alguem acaba por desligar». A regra e **igualdade**: um literal que
        **e** o nome de uma vertical e a unica forma de o codigo decidir por ele.

        **O que este teste nao apanha**, e esta aqui escrito em vez de
        prometido: um nome montado em tempo de execucao (`"vend" + "edor"`), um
        literal que o contenha sem lhe ser igual (`"vendedor_v2"`), e um nome
        que chegue de fora. Os dois primeiros sao paranoia; o terceiro e
        precisamente o que se quer — e o `id` do ficheiro. A prova de que o
        registo **mesmo** nao conhece verticais e o teste seguinte, que carrega
        uma inventada.
        """
        import ast

        for ficheiro in self.modulos():
            arvore = ast.parse(ficheiro.read_text(encoding="utf-8"), filename=str(ficheiro))
            literais = {
                no.value
                for no in ast.walk(arvore)
                if isinstance(no, ast.Constant) and isinstance(no.value, str)
            }
            # As *docstrings* sao literais e citam `vendedor` para explicar o
            # desenho. Tiram-se: o que o critero proibe e o codigo **decidir**.
            for no in ast.walk(arvore):
                if isinstance(no, (ast.Module, ast.ClassDef, ast.FunctionDef)):
                    documentacao = ast.get_docstring(no, clean=False)
                    if documentacao is not None:
                        literais.discard(documentacao)
            for nome in self.VERTICAIS:
                self.assertNotIn(
                    nome,
                    literais,
                    f"`{nome}` e um literal de {ficheiro.name}: uma vertical e "
                    "configuracao (ADR-012), e o registo nao conhece nenhuma pelo nome",
                )

    def test_uma_vertical_com_um_id_inventado_carrega_e_resolve(self) -> None:
        """A prova de que o registo nao conhece verticais, por comportamento.

        O `grep` do teste acima mede a fonte; isto mede o que o codigo faz. Se
        houvesse em qualquer sitio uma lista de verticais conhecidas, um `id`
        que o dicionario nao tem nao passava daqui — e e exactamente o que a
        vertical `catalogo` dos modulos de entrada (KAM-118) vai precisar.

        Quem recusa um `id` fora do dicionario e o *gate* 3b, no CI, sobre o
        ficheiro. Nao e este codigo, e e essa a divisao que o ADR-012 pede.
        """
        import tempfile

        pasta = Path(self.enterContext(tempfile.TemporaryDirectory()))
        inventada = (
            VENDEDOR.replace("id: vendedor", "id: nome_que_ninguem_escreveu")
            .replace("modulo: vendedor", "modulo: nome_que_ninguem_escreveu")
            .replace("kamba_agr.verticais.vendedor", "kamba_agr.verticais.inventada")
        )
        escrever(
            pasta,
            inventada=inventada,
            gates=GATES.replace("  vendedor:", "  nome_que_ninguem_escreveu:"),
        )
        reg = registo.AgentRegistry(ler_entitlement=lambda t, m: EntitlementFalso(True))
        reg.load_all(ambiente(), pasta)
        self.assertEqual(sorted(reg.verticais), ["nome_que_ninguem_escreveu"])
        resolucao = reg.resolve(ContextoFalso(TENANT, "nome_que_ninguem_escreveu"))
        self.assertEqual(resolucao.vertical.id, "nome_que_ninguem_escreveu")

    def test_o_registo_nao_importa_nada_fora_da_lista_de_permitidos(self) -> None:
        """Escrito ao contrario, pela licao do EPIC-02: enumera o que o modulo
        importa e exige que cada um esteja numa lista com razao escrita. Uma
        lista de **bloqueio** passaria hoje por o modulo proibido ainda nao
        existir — e isso nao e garantia, e um acaso com data de validade."""
        import re

        permitidos = {
            # biblioteca padrao
            "__future__", "collections.abc", "dataclasses", "os", "pathlib", "re", "typing",
            # o fecho do AGR, ja pago pelo KAM-026
            "pydantic", "yaml",
            # o canon partilhado: as fontes das validacoes 2, 4 e 5
            "kamba_core.eventos.contratos", "kamba_core.ten", "kamba_core.fluxo_piloto",
            # dentro do proprio pacote
            ".esquema", ".validar",
            # o nome da metrica e os seus dois motivos, que `metricas.py` tem de
            # conhecer para os contar (o `contar` levanta para um contador que
            # nao esteja registado la). Nao traz mais nada: so biblioteca padrao.
            "..metricas",
        }
        for ficheiro in self.modulos():
            for linha in ficheiro.read_text(encoding="utf-8").splitlines():
                achado = re.match(r"\s*(?:from ([\w.]+) import|import ([\w.]+))", linha)
                if achado is None:
                    continue
                modulo = achado.group(1) or achado.group(2)
                self.assertIn(
                    modulo,
                    permitidos,
                    f"{ficheiro.name} importa `{modulo}`, que nao esta na lista de "
                    "permitidos deste teste. Se e legitimo, acrescente-o com a razao",
                )

    def test_o_registo_nao_depende_do_resto_do_agr(self) -> None:
        """O registo e configuracao: nao conhece turnos, trancas nem a API.
        Mede-se por importacao real, num interprete que nao os tenha carregado."""
        import subprocess
        import sys

        codigo = (
            "import sys;"
            "import kamba_agr.registo;"
            "proibidos=[m for m in ('kamba_agr.turno','kamba_agr.api_interna',"
            "'kamba_agr.trancas','kamba_agr.checkpointer','starlette','uvicorn')"
            " if m in sys.modules];"
            "print(proibidos)"
        )
        saida = subprocess.run(
            [sys.executable, "-c", codigo],
            capture_output=True,
            text=True,
            cwd=RAIZ,
            env={
                **__import__("os").environ,
                "PYTHONPATH": f"{RAIZ / 'libs/py-core/src'}{__import__('os').pathsep}{RAIZ / 'services/agr/src'}",
            },
        )
        self.assertEqual(saida.returncode, 0, saida.stderr)
        self.assertEqual(saida.stdout.strip(), "[]", saida.stdout)


if __name__ == "__main__":
    unittest.main()
