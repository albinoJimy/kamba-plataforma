"""A guarda de arranque do Piloto, sem base de dados.

A prova contra um PostgreSQL real esta no gate 8 (`db/tests`). Aqui verifica-se
a logica com uma ligacao falsa, para que a guarda esteja coberta no gate 4 e
para que os casos de configuracao — os que mais facilmente falham abertos —
nao dependam de haver uma base.
"""

from __future__ import annotations

import unittest

from kamba_core.fluxo_piloto import (
    CONSULTA_DE_VISIBILIDADE,
    VERIFICACOES,
    FaseNaoDefinida,
    FluxoBNoPiloto,
    GuardaCega,
    verificar_arranque,
)


class _Cursor:
    def __init__(self, contagens: dict[str, int], registo: list[str]) -> None:
        self._contagens = contagens
        self._registo = registo
        self._ultima = ""
        self.fechado = False

    def execute(self, consulta: str) -> None:
        self._registo.append(consulta)
        self._ultima = consulta

    def fetchone(self):
        if self._ultima == CONSULTA_DE_VISIBILIDADE:
            # Por omissao a ligacao falsa ve tudo; os testes de cegueira dizem
            # o contrario explicitamente.
            return (self._contagens.get(self._ultima, True),)
        return (self._contagens.get(self._ultima, 0),)

    def close(self) -> None:
        self.fechado = True


class _Conexao:
    """Ligacao DB-API minima. `contagens` mapeia consulta -> numero de linhas."""

    def __init__(self, contagens: dict[str, int] | None = None) -> None:
        self.contagens = contagens or {}
        self.consultas: list[str] = []
        self.cursores: list[_Cursor] = []

    def cursor(self) -> _Cursor:
        cursor = _Cursor(self.contagens, self.consultas)
        self.cursores.append(cursor)
        return cursor


PILOTO = {"KAMBA_FASE": "piloto"}


class TestFase(unittest.TestCase):
    """A variavel falha fechada: so `piloto` e aceite."""

    def test_ausente_vazia_ou_desconhecida_levanta(self) -> None:
        for ambiente in ({}, {"KAMBA_FASE": ""}, {"KAMBA_FASE": "clusters"},
                         {"KAMBA_FASE": "PILOTO"}, {"KAMBA_FASE": "prod"}):
            with self.subTest(ambiente=ambiente):
                conexao = _Conexao()
                with self.assertRaises(FaseNaoDefinida):
                    verificar_arranque(conexao, ambiente)
                self.assertEqual(
                    conexao.consultas, [], "consultou a base sem saber a fase"
                )

    def test_a_mensagem_nomeia_a_variavel(self) -> None:
        with self.assertRaises(FaseNaoDefinida) as capturado:
            verificar_arranque(_Conexao(), {})
        self.assertIn("KAMBA_FASE", str(capturado.exception))
        self.assertIn("ADR-011", str(capturado.exception))


class TestVerificacoes(unittest.TestCase):
    def test_base_limpa_arranca(self) -> None:
        conexao = _Conexao()
        self.assertIsNone(verificar_arranque(conexao, PILOTO))
        self.assertEqual(len(conexao.consultas), len(VERIFICACOES) + 1)
        self.assertEqual(conexao.consultas[0], CONSULTA_DE_VISIBILIDADE)

    def test_cada_condicao_recusa_o_arranque_sozinha(self) -> None:
        """Tres condicoes, e qualquer uma basta."""
        for descricao, consulta in VERIFICACOES:
            with self.subTest(condicao=descricao):
                with self.assertRaises(FluxoBNoPiloto) as capturado:
                    verificar_arranque(_Conexao({consulta: 1}), PILOTO)
                self.assertIn(descricao, str(capturado.exception))

    def test_reporta_todas_as_condicoes_e_nao_so_a_primeira(self) -> None:
        contagens = {consulta: 2 for _, consulta in VERIFICACOES}
        with self.assertRaises(FluxoBNoPiloto) as capturado:
            verificar_arranque(_Conexao(contagens), PILOTO)
        for descricao, _ in VERIFICACOES:
            self.assertIn(descricao, str(capturado.exception))

    def test_as_tres_condicoes_do_criterio_estao_la(self) -> None:
        """O criterio de aceitacao 7 nomeia tres; a lista nao pode encolher."""
        descricoes = " | ".join(d for d, _ in VERIFICACOES)
        self.assertIn("tenants.tipo = 'platform'", descricoes)
        self.assertIn("tenant_channels.origem = 'plataforma'", descricoes)
        self.assertIn("tenant_channels.vertical", descricoes)
        self.assertIn("'assistente'", descricoes)
        self.assertEqual(len(VERIFICACOES), 3)

    def test_a_vertical_e_lista_de_permitidas_e_nao_de_proibidas(self) -> None:
        """`= 'assistente'` nao via `assistente_v2`. O que nao se conhece nao arranca."""
        consulta = VERIFICACOES[2][1]
        self.assertIn("NOT IN ('vendedor', 'servicos')", consulta)
        self.assertNotIn("= 'assistente'", consulta)

    def test_so_le(self) -> None:
        for _, consulta in VERIFICACOES:
            self.assertTrue(consulta.startswith("SELECT count(*) FROM platform."))

    def test_fecha_o_cursor_mesmo_quando_recusa(self) -> None:
        conexao = _Conexao({VERIFICACOES[0][1]: 1})
        with self.assertRaises(FluxoBNoPiloto):
            verificar_arranque(conexao, PILOTO)
        self.assertTrue(all(c.fechado for c in conexao.cursores))


class TestVisibilidade(unittest.TestCase):
    """Uma contagem so vale se quem conta vir todas as linhas.

    Com a RLS do KAM-004, um papel sem `BYPASSRLS` e sem contexto de tenant ve
    zero linhas. A primeira versao da guarda contava na mesma, e devolvia «pode
    arrancar» sobre uma base cheia de Fluxo B — a falhar aberta, em silencio, no
    dia em que a RLS entrasse.
    """

    def test_sem_prova_de_visibilidade_levanta(self) -> None:
        conexao = _Conexao({CONSULTA_DE_VISIBILIDADE: False})
        with self.assertRaises(GuardaCega):
            verificar_arranque(conexao, PILOTO)

    def test_cega_nao_chega_a_contar(self) -> None:
        """Um zero contado as cegas e pior do que nao contar."""
        conexao = _Conexao({CONSULTA_DE_VISIBILIDADE: False})
        with self.assertRaises(GuardaCega):
            verificar_arranque(conexao, PILOTO)
        self.assertEqual(conexao.consultas, [CONSULTA_DE_VISIBILIDADE])

    def test_resposta_nula_conta_como_cega(self) -> None:
        """Se o papel nao estiver em `pg_roles`, a subconsulta da NULL."""
        conexao = _Conexao({CONSULTA_DE_VISIBILIDADE: None})
        with self.assertRaises(GuardaCega):
            verificar_arranque(conexao, PILOTO)

    def test_a_consulta_olha_para_o_papel_e_para_as_duas_tabelas(self) -> None:
        for fragmento in ("rolbypassrls", "current_user", "relrowsecurity",
                          "'tenants'", "'tenant_channels'", "pg_policies",
                          "qual = 'true'", "NOT p.polpermissive", "pg_has_role"):
            self.assertIn(fragmento, CONSULTA_DE_VISIBILIDADE)


if __name__ == "__main__":
    unittest.main()
