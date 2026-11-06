"""O cenário e as consultas: o que impede os três artefactos de divergirem (KAM-108).

O cenário diz o que o operador faz, as consultas dão três dos quatro elos, e o
traço procura os quatro. São três ficheiros a falar da mesma cadeia, e o modo de
falha desta família é cada um ficar certo por si: o operador corre os passos
certos, o traço mede outra coisa, e ninguém repara. Estes ensaios amarram os três.
"""

from __future__ import annotations

import unittest

from gate_fase0 import cenario, consulta, traco


class TestOCenarioConcordaComOTraco(unittest.TestCase):
    def test_o_cenario_produz_exactamente_os_elos_que_o_traco_procura(self) -> None:
        cenario.verificar()
        self.assertEqual(cenario.elos_produzidos(), cenario.ELOS)

    def test_os_elos_do_cenario_sao_os_nomes_que_o_traco_usa(self) -> None:
        """A amarra que importa: o `em_falta` do traço usa estes mesmos nomes.

        Sem este ensaio, renomear um elo num dos lados deixava o outro a
        procurar um nome que já não existe — e o sintoma era uma cadeia
        «completa» com um elo por medir.
        """
        caminho = []
        for elo in cenario.ELOS:
            if elo == "mensagem":
                caminho.append(elo)
            elif elo == "pedido":
                caminho.append(elo)
            elif elo == "evento de pagamento":
                caminho.append(elo)
            else:
                self.assertEqual(elo, f"consumo por `{traco.CONSUMIDOR_EXIGIDO}`")
                caminho.append(elo)
        self.assertEqual(tuple(caminho), cenario.ELOS)

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

    def test_as_colunas_declaradas_batem_com_as_do_select(self) -> None:
        """A declaração e o SQL são dois lados, e divergir é o defeito.

        A tupla `colunas` é o que o ensaio e a documentação leem; o `SELECT` é o
        que corre. Uma coluna num e não no outro é a divergência que uma
        declaração sozinha não apanha.
        """
        for cada in consulta.CONSULTAS:
            for coluna in cada.colunas:
                self.assertTrue(
                    consulta._no_select(cada.sql, coluna),
                    f"{cada.nome}: `{coluna}` está declarada e não está no SELECT",
                )

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
