"""`ci/waivers.yaml`: o unico mecanismo de excepcao, e o que ele recusa.

O caso que importa mais e o do waiver **expirado**: falha o pipeline, nao avisa.
A alternativa — avisar e seguir — produz excepcoes que ninguem revisita, porque
nada obriga a isso.
"""

from __future__ import annotations

import datetime
import tempfile
import unittest
from pathlib import Path

import ci_waivers
from ci_waivers import GATES_COM_WAIVER, PRAZO_MAXIMO_DIAS, WaiverInvalido, ler

ROOT = Path(__file__).resolve().parents[3]
HOJE = datetime.date(2026, 10, 11)


def _escrever(corpo: str) -> Path:
    pasta = Path(tempfile.mkdtemp())
    (pasta / "ci").mkdir()
    (pasta / "ci" / "waivers.yaml").write_text(corpo, encoding="utf-8")
    return pasta


BASE = """version: 1
waivers:
  - gate: 11
    alvo: "pkg:npm/exemplo@1.0.0"
    adr_ou_aprovacao: ADR-014
    autor: nome.sobrenome
    razao: >-
      Uma razao suficientemente longa para sobreviver a saida do autor e dizer
      quando rever.
    criado_em: {criado}
    expira_em: {expira}
"""


def base(expira: str, criado: str = "2026-10-11") -> str:
    """O corpo de um waiver valido. O `criado_em` e obrigatorio desde o
    KAM-135, e por omissao e o `HOJE` das *fixtures*."""
    return BASE.format(expira=expira, criado=criado)


class TestFicheiroDoRepositorio(unittest.TestCase):
    def test_le_e_esta_vazio(self) -> None:
        """O estado inicial e sem excepcoes, de proposito.

        Le-se com o dia de **hoje**, e nao com o `HOJE` fixo das *fixtures*: um
        waiver verdadeiro escrito depois desse dia fixo tem prazo que o leitor
        acha longe demais, e o teste ficava vermelho por causa da data do
        codigo e nao do ficheiro.
        """
        self.assertEqual(ler(ROOT, datetime.date.today()), [])

    def test_a_chave_waivers_existe(self) -> None:
        """`waivers: []` diz «nenhuma»; a ausencia da chave e ambigua."""
        texto = (ROOT / "ci" / "waivers.yaml").read_text(encoding="utf-8")
        self.assertIn("waivers: []", texto)


class TestAceita(unittest.TestCase):
    def test_waiver_completo_e_dentro_do_prazo(self) -> None:
        pasta = _escrever(base("2026-10-20"))
        waivers = ler(pasta, HOJE)
        self.assertEqual(len(waivers), 1)
        self.assertEqual(waivers[0]["gate"], "11")

    def test_aceita_adr_local(self) -> None:
        corpo = base("2026-10-20").replace("ADR-014", "ADR-L001")
        self.assertEqual(len(ler(_escrever(corpo), HOJE)), 1)

    def test_aceita_aprovacao_humana_datada(self) -> None:
        corpo = base("2026-10-20").replace(
            "ADR-014", "aprovacao:fundador@2026-10-10"
        )
        self.assertEqual(len(ler(_escrever(corpo), HOJE)), 1)


class TestRecusa(unittest.TestCase):
    def recusa(self, corpo: str, trecho: str) -> None:
        with self.assertRaises(WaiverInvalido) as capturado:
            ler(_escrever(corpo), HOJE)
        self.assertIn(trecho, str(capturado.exception))

    def test_expirado_falha_o_pipeline(self) -> None:
        """O caso central. Nao avisa: falha.

        O `criado_em` e anterior: um waiver expirado foi criado **antes** de
        expirar, e sem isso a recusa vinha pela ordem das datas e o teste
        deixava de provar o que diz (KAM-135).
        """
        self.recusa(base("2026-10-01", criado="2026-09-15"), "expirou")

    def test_expirado_ontem_tambem_falha(self) -> None:
        self.recusa(base("2026-10-10", criado="2026-09-20"), "expirou")

    def test_prazo_longo_demais(self) -> None:
        longe = (HOJE + datetime.timedelta(days=PRAZO_MAXIMO_DIAS + 1)).isoformat()
        self.recusa(base(longe), f"maximo\ne {PRAZO_MAXIMO_DIAS}".replace("\n", " "))

    def test_sem_data(self) -> None:
        corpo = base("2026-10-20").replace("    expira_em: 2026-10-20\n", "")
        self.recusa(corpo, "expira_em")

    def test_data_malformada(self) -> None:
        self.recusa(base("20-10-2026"), "data ISO")

    def test_sem_referencia(self) -> None:
        corpo = base("2026-10-20").replace(
            "    adr_ou_aprovacao: ADR-014\n", ""
        )
        self.recusa(corpo, "adr_ou_aprovacao")

    def test_referencia_que_nao_e_adr_nem_aprovacao(self) -> None:
        for mau in ("porque sim", "ADR-21", "aprovacao:alguem", "ticket KAM-002"):
            with self.subTest(referencia=mau):
                corpo = base("2026-10-20").replace("ADR-014", mau)
                self.recusa(corpo, "adr_ou_aprovacao")

    def test_sem_alvo(self) -> None:
        corpo = base("2026-10-20").replace(
            '    alvo: "pkg:npm/exemplo@1.0.0"\n', ""
        )
        self.recusa(corpo, "alvo")

    def test_razao_curta(self) -> None:
        corpo = base("2026-10-20").replace(
            """    razao: >-
      Uma razao suficientemente longa para sobreviver a saida do autor e dizer
      quando rever.
""",
            "    razao: porque sim\n",
        )
        self.recusa(corpo, "nao sobrevive")

    def test_gate_que_nao_aceita_waiver(self) -> None:
        """Os gates 1 e 2 nao se dispensam.

        Um build que nao compila ou um tipo que nao verifica corrige-se.
        """
        for gate in ("1", "2"):
            with self.subTest(gate=gate):
                corpo = base("2026-10-20").replace("gate: 11", f"gate: {gate}")
                self.recusa(corpo, "nao aceita waiver")

    def test_sem_a_chave_waivers(self) -> None:
        self.recusa("version: 1\n", "falta a chave")

    def test_versao_errada(self) -> None:
        corpo = base("2026-10-20").replace("version: 1", "version: 2")
        self.recusa(corpo, "version")

    def test_sem_ficheiro(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            with self.assertRaises(WaiverInvalido):
                ler(Path(tmp), HOJE)


class TestGatesQueAceitamWaiver(unittest.TestCase):
    def test_os_gates_1_e_2_estao_de_fora(self) -> None:
        self.assertNotIn("1", GATES_COM_WAIVER)
        self.assertNotIn("2", GATES_COM_WAIVER)

    def test_os_gates_em_ambito_do_kam_002_aceitam(self) -> None:
        for gate in ("3", "4", "9", "11"):
            self.assertIn(gate, GATES_COM_WAIVER)

    def test_os_gates_adiados_aceitam(self) -> None:
        """Os 5-8 ficam fail-closed; o waiver e a valvula enquanto nao existirem."""
        for gate in ("5", "6", "7", "8"):
            self.assertIn(gate, GATES_COM_WAIVER)


if __name__ == "__main__":
    unittest.main()


class TestOPrazoContaDaCriacao(unittest.TestCase):
    """O defeito central do KAM-135: «um waiver renova-se para sempre com um
    diff de um caractere».

    Era o inverso exacto da propriedade que o `docs/ci.md` §5 diz entregar —
    «a alternativa e uma excepcao que fica para sempre porque ninguem reparou
    que caducou».
    """

    def recusa(self, corpo: str, trecho: str) -> None:
        with self.assertRaises(WaiverInvalido) as capturado:
            ler(_escrever(corpo), HOJE)
        self.assertIn(trecho, str(capturado.exception))

    def test_sem_criado_em_falha_e_diz_o_que_acrescentar(self) -> None:
        corpo = base("2026-10-20").replace("    criado_em: 2026-10-11\n", "")
        self.recusa(corpo, "criado_em")

    def test_trinta_dias_da_criacao_passa(self) -> None:
        criado = datetime.date(2026, 10, 11)
        expira = criado + datetime.timedelta(days=PRAZO_MAXIMO_DIAS)
        waivers = ler(_escrever(base(expira.isoformat(), criado=criado.isoformat())), HOJE)
        self.assertEqual(len(waivers), 1)

    def test_trinta_e_um_dias_da_criacao_falha(self) -> None:
        criado = datetime.date(2026, 10, 11)
        expira = criado + datetime.timedelta(days=PRAZO_MAXIMO_DIAS + 1)
        self.recusa(
            base(expira.isoformat(), criado=criado.isoformat()),
            "contados de `criado_em`",
        )

    def test_empurrar_o_expira_em_sem_mexer_no_criado_em_falha(self) -> None:
        """A prova de que renovar deixou de ser um diff de um caractere.

        O mesmo `criado_em` de um waiver que ja existia, com o `expira_em`
        empurrado trinta dias — que e o gesto exacto que o ticket descreve.
        Com o prazo contado de hoje, isto passava.
        """
        criado = HOJE - datetime.timedelta(days=25)
        empurrado = HOJE + datetime.timedelta(days=30)
        self.recusa(
            base(empurrado.isoformat(), criado=criado.isoformat()),
            "Para prolongar, crie-o de novo",
        )

    def test_renovar_a_serio_passa(self) -> None:
        """E o outro lado: com `criado_em` novo, o mesmo prazo e legitimo.

        Sem este teste, o anterior provava so que a verificacao recusa — nao
        que recusa **a coisa certa**.
        """
        waivers = ler(
            _escrever(base((HOJE + datetime.timedelta(days=30)).isoformat(),
                           criado=HOJE.isoformat())),
            HOJE,
        )
        self.assertEqual(len(waivers), 1)

    def test_criado_no_futuro_falha(self) -> None:
        """A forma mais simples de esticar o prazo sem parecer que se esticou."""
        self.recusa(
            base("2026-11-20", criado=(HOJE + datetime.timedelta(days=1)).isoformat()),
            "nao se cria no futuro",
        )

    def test_expira_antes_de_criar_falha(self) -> None:
        # As duas datas no passado: com um `criado_em` futuro, a recusa vinha
        # por essa verificacao e o teste deixava de provar o que diz.
        self.recusa(base("2026-10-01", criado="2026-10-05"), "anterior a `criado_em`")


class TestADataDaAprovacaoELida(unittest.TestCase):
    """«A presenca do campo era verificada; o conteudo nao.»"""

    def recusa(self, referencia: str, trecho: str) -> None:
        corpo = base("2026-10-20").replace("ADR-014", referencia)
        with self.assertRaises(WaiverInvalido) as capturado:
            ler(_escrever(corpo), HOJE)
        self.assertIn(trecho, str(capturado.exception))

    def test_data_impossivel_falha(self) -> None:
        """`@9999-99-99` satisfazia a exigencia de «aprovacao registada» do
        `specs/01` §4 sem registar nada."""
        self.recusa("aprovacao:alguem@9999-99-99", "nao e uma data")

    def test_trinta_e_dois_de_janeiro_falha(self) -> None:
        self.recusa("aprovacao:alguem@2026-01-32", "nao e uma data")

    def test_data_futura_falha(self) -> None:
        amanha = (HOJE + datetime.timedelta(days=1)).isoformat()
        self.recusa(f"aprovacao:alguem@{amanha}", "Ninguem aprovou isto ainda")

    def test_data_de_hoje_passa(self) -> None:
        corpo = base("2026-10-20").replace("ADR-014", f"aprovacao:alguem@{HOJE.isoformat()}")
        self.assertEqual(len(ler(_escrever(corpo), HOJE)), 1)

    def test_data_passada_passa(self) -> None:
        corpo = base("2026-10-20").replace("ADR-014", "aprovacao:alguem@2026-10-01")
        self.assertEqual(len(ler(_escrever(corpo), HOJE)), 1)

    def test_um_adr_continua_a_nao_precisar_de_data(self) -> None:
        self.assertEqual(len(ler(_escrever(base("2026-10-20")), HOJE)), 1)


class TestOsGatesQueOCanonNomeia(unittest.TestCase):
    """«O conjunto de gates deixa de poder divergir do canon em silencio.»"""

    def test_os_gates_14_e_18_sao_aceites(self) -> None:
        """O `docs/ci.md` §5 diz que o KAM-067 e o KAM-078 consomem este
        esquema, e o validador **recusava-os**: o KAM-067 ia encontrar o
        mecanismo fechado, e inventar o seu e o que o §5 existe para evitar."""
        for gate in ("14", "18"):
            with self.subTest(gate=gate):
                corpo = base("2026-10-20").replace("gate: 11", f"gate: {gate}")
                self.assertEqual(len(ler(_escrever(corpo), HOJE)), 1)

    def test_os_gates_1_e_2_continuam_recusados(self) -> None:
        """«Um build que nao compila corrige-se.» A abertura aos 14 e 18 nao
        pode ter alargado o conjunto por descuido."""
        for gate in ("1", "2"):
            with self.subTest(gate=gate):
                corpo = base("2026-10-20").replace("gate: 11", f"gate: {gate}")
                with self.assertRaises(WaiverInvalido) as capturado:
                    ler(_escrever(corpo), HOJE)
                self.assertIn("nao aceita waiver", str(capturado.exception))

    def test_cada_gate_do_canon_esta_classificado(self) -> None:
        """Nenhum gate do `specs/01` §4 fica sem posicao — nem aceita, nem
        «nao aceita, e eis porque». E a derivacao que faz a diferenca: uma
        lista a mao envelhecia em silencio."""
        ci_waivers.verificar_cobertura_dos_gates(ROOT)
        descobertos = ci_waivers.gates_do_canon(ROOT)
        # **Sem numero a mao.** A primeira versao escrevia `18`, que era o
        # numero errado — o `3b` nao era visto pelo *regex* —, e com isso o
        # teste que devia detectar a divergencia cimentava-a. Contam-se as
        # linhas da tabela do canon e compara-se com o que a funcao devolve:
        # se uma forma nova de identificador aparecer e o *regex* nao a vir,
        # os dois numeros divergem e isto fica vermelho.
        linhas = len([
            l for l in (ROOT / ci_waivers.CANON_DOS_GATES)
            .read_text(encoding="utf-8").splitlines()
            if l.startswith("| ") and "| **" in l and l.rstrip().endswith("|")
            and l.split("|")[1].strip()[:1].isdigit()
        ])
        self.assertEqual(
            len(descobertos), linhas,
            "o `gates_do_canon` nao ve todas as linhas da tabela do §4 — foi "
            "assim que o `3b` ficou invisivel",
        )
        self.assertIn("3b", descobertos, "o `3b` esta na tabela desde o KAM-111")
        self.assertEqual(
            descobertos,
            set(GATES_COM_WAIVER) | set(ci_waivers.GATES_SEM_WAIVER_COM_RAZAO),
        )

    def test_cada_recusa_tem_razao_escrita_e_nao_vazia(self) -> None:
        """Estar na lista dos que nao aceitam e uma **decisao**. Sem razao
        escrita, e indistinguivel de um esquecimento."""
        for gate, razao in ci_waivers.GATES_SEM_WAIVER_COM_RAZAO.items():
            with self.subTest(gate=gate):
                self.assertGreater(len(razao), 30, gate)

    def test_os_dois_conjuntos_nao_se_cruzam(self) -> None:
        self.assertEqual(
            set(GATES_COM_WAIVER) & set(ci_waivers.GATES_SEM_WAIVER_COM_RAZAO), set()
        )


class TestOQueARevisaoEncontrou(unittest.TestCase):
    """Os achados da revisao adversarial do KAM-135."""

    def recusa(self, corpo: str, trecho: str) -> None:
        with self.assertRaises(WaiverInvalido) as capturado:
            ler(_escrever(corpo), HOJE)
        self.assertIn(trecho, str(capturado.exception))

    # --- MAIOR 1: o gate 3b era invisivel ao regex
    def test_o_gate_3b_aceita_waiver(self) -> None:
        """Esta na tabela do canon desde o KAM-111, com *job* proprio.

        O *regex* exigia digitos, pelo que o `3b` nem aparecia no conjunto
        descoberto: nao era aceite nem tinha razao escrita, e a recusa
        respondia-lhe com a frase dos gates 1 e 2.
        """
        corpo = base("2026-10-20").replace("gate: 11", "gate: 3b")
        self.assertEqual(len(ler(_escrever(corpo), HOJE)), 1)

    def test_a_ordem_dos_gates_na_mensagem_e_numerica(self) -> None:
        """`3b` e `3c` depois de `3`, e `11` depois de `9`.

        Nao e cosmetica: a mensagem lista os gates aceites, e por ordem
        alfabetica o `11` vinha primeiro. Quem a le fica sem saber se o
        conjunto esta certo.
        """
        corpo = base("2026-10-20").replace("gate: 11", "gate: 1")
        with self.assertRaises(WaiverInvalido) as capturado:
            ler(_escrever(corpo), HOJE)
        aceites = str(capturado.exception).split("Aceitam: ")[1]
        self.assertTrue(aceites.startswith("3, 3b, 3c, 4,"), aceites)

    # --- MAIOR 2: a razao nunca chegava a quem batia a porta
    def test_a_recusa_diz_a_razao_daquele_gate(self) -> None:
        for gate, trecho in (
            ("16", "aprovacao a dispensar-se a si propria"),
            ("10", "SAST nao tem ticket"),
            ("13", "o limiar e a baseline"),
            ("17", "nao e uma verificacao, e um acto"),
        ):
            with self.subTest(gate=gate):
                corpo = base("2026-10-20").replace("gate: 11", f"gate: {gate}")
                self.recusa(corpo, trecho)

    # --- MAIOR 3: uma aprovacao antiga fundava uma excepcao nova
    def test_aprovacao_antiga_nao_funda_um_waiver_novo(self) -> None:
        """Vinte e quatro renovacoes de trinta dias passavam com a mesma
        aprovacao de 2001. O `criado_em` mudava, a aprovacao ficava."""
        corpo = base("2026-10-20").replace("ADR-014", "aprovacao:alguem@2001-01-01")
        self.recusa(corpo, "Uma aprovacao antiga nao funda uma excepcao nova")

    def test_aprovacao_contemporanea_passa(self) -> None:
        corpo = base("2026-10-20").replace("ADR-014", "aprovacao:alguem@2026-10-01")
        self.assertEqual(len(ler(_escrever(corpo), HOJE)), 1)

    def test_um_adr_nao_precisa_de_ser_contemporaneo(self) -> None:
        """E o limite que fica **dito** e nao fingido: um ADR e uma decisao de
        arquitectura e nao caduca. Exigir um ADR novo de trinta em trinta dias
        seria pedir arquitectura nova."""
        self.assertEqual(len(ler(_escrever(base("2026-10-20")), HOJE)), 1)

    # --- MENOR 3: a mensagem dizia `expira_em` mesmo a validar o `criado_em`
    def test_a_mensagem_nomeia_o_campo_certo(self) -> None:
        corpo = base("2026-10-20").replace("criado_em: 2026-10-11", "criado_em: nao-e-data")
        with self.assertRaises(WaiverInvalido) as capturado:
            ler(_escrever(corpo), HOJE)
        mensagem = str(capturado.exception)
        self.assertIn("`criado_em`", mensagem)
        self.assertNotIn("`expira_em`", mensagem)

    # --- MENOR 8: a forma aceite era mais larga do que a documentada
    def test_so_a_forma_aaaa_mm_dd(self) -> None:
        """O `fromisoformat` do 3.11+ aceita `20261018` e `2026-W42-7`. Nao sao
        explorarveis, mas a documentacao promete `AAAA-MM-DD` — e um leitor que
        aceita mais do que o que se promete e a classe que o KAM-134 fechou."""
        for forma in ("20261018", "2026-W42-7"):
            with self.subTest(forma=forma):
                corpo = base("2026-10-20").replace("criado_em: 2026-10-11", f"criado_em: {forma}")
                self.recusa(corpo, "data ISO (AAAA-MM-DD)")

    # --- MENOR 6: o caso (e) dos Testes Requeridos
    def test_um_adr_inexistente_nao_e_deste_validador(self) -> None:
        """«Um `ADR-NNN` fora do conjunto canonico falha» — e falha, **mas noutro
        gate**. Aqui verifica-se a **forma**; a existencia e do gate 3.

        E isso ficou provado por acidente ao escrever este teste: a primeira
        versao escrevia o numero inexistente a letra, e o `lint_refs` apanhou-o
        **neste ficheiro**. O numero monta-se em tempo de execucao para o gate
        3 nao ter de o ler — o que e, ele proprio, a demonstracao de que o
        gate 3 le isto.
        """
        inexistente = "ADR-" + "9" * 3
        corpo = base("2026-10-20").replace("ADR-014", inexistente)
        self.assertEqual(len(ler(_escrever(corpo), HOJE)), 1)
