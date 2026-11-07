"""O cenário e as consultas: o que impede os três artefactos de divergirem (KAM-108).

O cenário diz o que o operador faz, as consultas dão três dos quatro elos, e o
traço procura os quatro. São três ficheiros a falar da mesma cadeia, e o modo de
falha desta família é cada um ficar certo por si: o operador corre os passos
certos, o traço mede outra coisa, e ninguém repara. Estes ensaios amarram os três.
"""

from __future__ import annotations

import json
import unittest
from pathlib import Path
from tempfile import TemporaryDirectory

from gate_fase0 import cenario, consulta, traco
from gate_fase0.tests.test_traco import TENANT


class TestOCenarioConcordaComOTraco(unittest.TestCase):
    def test_o_cenario_produz_exactamente_os_elos_que_o_traco_procura(self) -> None:
        cenario.verificar()
        self.assertEqual(cenario.elos_produzidos(), cenario.ELOS)

    def test_os_elos_do_cenario_sao_os_nomes_que_o_traco_produz(self) -> None:
        """A amarra que importa, e **medida contra o que o traço produz**.

        **A primeira versão deste ensaio era um oráculo importado do alvo** —
        percorria `cenario.ELOS` e comparava-o consigo mesmo —, e a revisão
        adversarial mediu-o: renomear `"mensagem"` para `"msg"` dentro do
        `traco.encadear` deixava os ensaios todos verdes. O que o corrige é
        confrontar os nomes com **a saída do traço sobre uma cadeia vazia**, onde
        todos os elos estão em falta, e com literais escritos aqui.
        """
        with TemporaryDirectory() as pasta:
            caminho = Path(pasta) / "vazia.jsonl"
            caminho.write_bytes(
                (json.dumps({"tenant_id": TENANT}) + "\n").encode("utf-8")
            )
            cadeias, _ = traco.tracar([caminho])
        produzidos_pelo_traco = cadeias[0].em_falta
        self.assertEqual(produzidos_pelo_traco, cenario.ELOS)
        # E os literais, escritos aqui e não lidos de lá: sem eles, mudar os dois
        # lados ao mesmo tempo continuava a passar.
        self.assertEqual(
            produzidos_pelo_traco,
            ("mensagem", "pedido", "evento de pagamento", "consumo por `agr_servicos`"),
        )

    def test_o_consumidor_exigido_e_o_que_o_criterio_nomeia(self) -> None:
        """Literal aqui, e não importado: é o `events_consumed.consumer` da vertical."""
        self.assertEqual(traco.CONSUMIDOR_EXIGIDO, "agr_servicos")

    def test_cada_passo_tem_observavel_e_fonte(self) -> None:
        """Um passo sem observável é uma instrução, não um ensaio."""
        for passo in cenario.CENARIO:
            self.assertTrue(passo.observavel.strip(), passo.id)
            self.assertTrue(passo.fonte.strip(), passo.id)
            self.assertTrue(passo.acto.strip(), passo.id)

    def test_o_cenario_nao_leva_telefone_nem_texto_de_conversa(self) -> None:
        """Um guião versionado com frases de conversa é conteúdo no repositório.

        Mede-se pela **forma do valor** e não por leitura: é a mesma régua do
        `traco.py`, aplicada ao próprio cenário.
        """
        tudo = cenario.como_markdown()
        self.assertEqual(traco.detectar(tudo), [])

    def test_o_passo_zero_recusa_o_simulador(self) -> None:
        """O critério diz «nunca simulador», e é a diferença entre as duas demos.

        Com o `tools/meta-sim` a cadeia fecha e não prova nada sobre o canal, pelo
        que a ausência deste passo tornava a demonstração verde sem valer.
        """
        primeiro = cenario.CENARIO[0]
        self.assertEqual(primeiro.id, "P0")
        self.assertIn("simulador", primeiro.acto)

    def test_ids_repetidos_sao_incoerencia(self) -> None:
        original = cenario.CENARIO
        try:
            cenario.CENARIO = (original[0], original[0], *original[1:])  # type: ignore[misc]
            with self.assertRaises(cenario.CenarioIncoerente):
                cenario.verificar()
        finally:
            cenario.CENARIO = original  # type: ignore[misc]

    def test_um_elo_a_menos_e_incoerencia(self) -> None:
        """O canário da amarra: tirar um passo com elo tem de avermelhar."""
        original = cenario.CENARIO
        try:
            cenario.CENARIO = tuple(  # type: ignore[misc]
                passo for passo in original if passo.id != "P6"
            )
            with self.assertRaises(cenario.CenarioIncoerente):
                cenario.verificar()
        finally:
            cenario.CENARIO = original  # type: ignore[misc]

    def test_o_markdown_tem_uma_linha_por_passo(self) -> None:
        linhas = cenario.como_markdown().splitlines()
        self.assertEqual(len(linhas), len(cenario.CENARIO) + 2)


class TestAsConsultasProjectamSoIdentificadores(unittest.TestCase):
    def test_nenhuma_consulta_projecta_coluna_proibida(self) -> None:
        consulta.verificar()

    def test_a_projeccao_e_exactamente_a_tupla_declarada(self) -> None:
        """A declaração e o SQL são dois lados, e divergir é o defeito.

        E é uma **igualdade** e não uma inclusão: a primeira versão só verificava
        que cada coluna declarada estava no `SELECT`, pelo que uma coluna no
        `SELECT` e fora da tupla passava.
        """
        for cada in consulta.CONSULTAS:
            with self.subTest(consulta=cada.nome):
                self.assertEqual(
                    consulta.colunas_do_select(cada.sql, cada.nome), set(cada.colunas)
                )

    def test_o_select_estrela_e_recusado(self) -> None:
        """**O achado A10 da revisão adversarial.**

        A verificação era uma *denylist* de quinze nomes, e um `SELECT *` passava
        — trazendo com ele todas as colunas da tabela, `envelope` incluído.
        """
        original = consulta.CONSULTAS
        suja = consulta.Consulta(
            nome="estrela",
            elo=None,
            colunas=("tenant_id",),
            sql="SELECT *\n  FROM events_log\n WHERE tenant_id = :tenant_id",
            fonte="canário",
        )
        try:
            consulta.CONSULTAS = (*original, suja)  # type: ignore[misc]
            with self.assertRaises(consulta.ProjeccaoProibida) as apanhado:
                consulta.verificar()
            self.assertIn("não é um nome de coluna", str(apanhado.exception))
        finally:
            consulta.CONSULTAS = original  # type: ignore[misc]

    def test_uma_coluna_de_texto_livre_fora_da_denylist_e_recusada(self) -> None:
        """O segundo lado do A10: o `motivo` não estava na lista dos quinze.

        É coluna real de texto livre no dicionário, e a *allowlist* recusa-a por
        não estar declarada — que é a diferença entre as duas formas de guarda.
        """
        original = consulta.CONSULTAS
        suja = consulta.Consulta(
            nome="motivo",
            elo=None,
            colunas=("tenant_id",),
            sql="SELECT tenant_id, motivo\n  FROM events_log\n WHERE tenant_id = :tenant_id",
            fonte="canário",
        )
        try:
            consulta.CONSULTAS = (*original, suja)  # type: ignore[misc]
            with self.assertRaises(consulta.ProjeccaoProibida) as apanhado:
                consulta.verificar()
            self.assertIn("motivo", str(apanhado.exception))
            self.assertIn("não está na tupla", str(apanhado.exception))
        finally:
            consulta.CONSULTAS = original  # type: ignore[misc]

    def test_uma_declaracao_que_o_sql_nao_projecta_e_recusada(self) -> None:
        """O lado inverso: declarar e não projectar é a mesma divergência."""
        original = consulta.CONSULTAS
        suja = consulta.Consulta(
            nome="em_falta",
            elo=None,
            colunas=("tenant_id", "event_id"),
            sql="SELECT tenant_id\n  FROM events_log\n WHERE tenant_id = :tenant_id",
            fonte="canário",
        )
        try:
            consulta.CONSULTAS = (*original, suja)  # type: ignore[misc]
            with self.assertRaises(consulta.ProjeccaoProibida) as apanhado:
                consulta.verificar()
            self.assertIn("e o SQL não as projecta", str(apanhado.exception))
        finally:
            consulta.CONSULTAS = original  # type: ignore[misc]

    def test_uma_expressao_na_projeccao_e_recusada(self) -> None:
        """Uma expressão não se confronta com a tupla, e saltá-la era o defeito."""
        with self.assertRaises(consulta.ProjeccaoProibida):
            consulta.colunas_do_select(
                "SELECT lower(envelope::text) FROM events_log", "expr"
            )

    def test_um_sql_sem_select_from_e_recusado(self) -> None:
        with self.assertRaises(consulta.ProjeccaoProibida):
            consulta.colunas_do_select("UPDATE events_log SET tipo = 'x'", "nao_leitura")

    def test_todas_sao_select(self) -> None:
        """Nenhuma cria, altera ou apaga: a recolha é de leitura."""
        for cada in consulta.CONSULTAS:
            texto = cada.sql.upper()
            self.assertTrue(texto.lstrip().startswith("SELECT"), cada.nome)
            for proibido in ("INSERT", "UPDATE", "DELETE", "DROP", "ALTER", "CREATE"):
                self.assertNotIn(proibido, texto, f"{cada.nome}: {proibido}")

    def test_todas_filtram_por_tenant_e_por_janela(self) -> None:
        """Sem janela, a execução de hoje mistura-se com as de ontem.

        E uma cadeia montada com elos de execuções diferentes parece completa
        sem o ser, que é a conclusão errada mais cara possível aqui.
        """
        for cada in consulta.CONSULTAS:
            self.assertIn(":tenant_id", cada.sql, cada.nome)
            self.assertIn(":desde", cada.sql, cada.nome)

    def test_o_canario_da_projeccao_morde(self) -> None:
        """Injectar uma coluna proibida no SELECT tem de avermelhar.

        Sem este passo, um `verificar()` que não olhasse para o SQL devolvia
        conforme sobre uma consulta que trazia o `envelope` inteiro.
        """
        original = consulta.CONSULTAS
        suja = consulta.Consulta(
            nome="suja",
            elo=None,
            colunas=("tenant_id",),
            sql="SELECT tenant_id, envelope\n  FROM events_log\n WHERE tenant_id = :tenant_id",
            fonte="canário",
        )
        try:
            consulta.CONSULTAS = (*original, suja)  # type: ignore[misc]
            with self.assertRaises(consulta.ProjeccaoProibida) as apanhado:
                consulta.verificar()
            self.assertIn("envelope", str(apanhado.exception))
        finally:
            consulta.CONSULTAS = original  # type: ignore[misc]

    def test_o_canario_da_coluna_declarada_morde(self) -> None:
        original = consulta.CONSULTAS
        suja = consulta.Consulta(
            nome="suja",
            elo=None,
            colunas=("tenant_id", "phone_enc"),
            sql="SELECT tenant_id\n  FROM contacts\n WHERE tenant_id = :tenant_id",
            fonte="canário",
        )
        try:
            consulta.CONSULTAS = (*original, suja)  # type: ignore[misc]
            with self.assertRaises(consulta.ProjeccaoProibida) as apanhado:
                consulta.verificar()
            self.assertIn("phone_enc", str(apanhado.exception))
        finally:
            consulta.CONSULTAS = original  # type: ignore[misc]

    def test_uma_coluna_proibida_no_where_nao_e_achado(self) -> None:
        """Um filtro não sai no resultado, e proibi-lo tirava a janela.

        É o par positivo do canário: sem ele, a verificação podia ser «a palavra
        não aparece em sítio nenhum», que proibia o `tipo IN (…)` e o
        `criado_at >= :desde` que impedem a cadeia de misturar execuções.
        """
        self.assertFalse(
            consulta._no_select(
                "SELECT tenant_id FROM events_log WHERE envelope IS NOT NULL", "envelope"
            )
        )

    def test_as_consultas_cobrem_os_tres_elos_de_baixo(self) -> None:
        elos = {cada.elo for cada in consulta.CONSULTAS if cada.elo}
        self.assertEqual(elos, set(cenario.ELOS[1:]))

    def test_o_texto_para_o_operador_nomeia_a_fonte_de_cada_consulta(self) -> None:
        texto = consulta.como_texto()
        for cada in consulta.CONSULTAS:
            self.assertIn(cada.fonte, texto)


if __name__ == "__main__":
    unittest.main()
