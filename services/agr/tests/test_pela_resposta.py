"""A notificacao ao cliente pela resposta do AGR (KAM-221, sobre o KAM-224), sem base.

O que aqui se mede e a **escolha**: a janela com a margem de cinco minutos, o
modo da conversa, a repeticao e as falhas. A linha e o evento contra o
PostgreSQL mede-os o `db/tests_agr/test_quote_requests.py`, no *gate* 8.

O duplo e o do `test_saida.py` (que le o texto das instrucoes), com a janela de
cada conversa: uma instrucao que ele nao conheca levanta.
"""

from __future__ import annotations

import datetime
import unittest
from typing import Any

import test_saida
from test_saida import CONTACTO, CONVERSA, TENANT

from kamba_agr import saida
from kamba_agr.eventos import pela_resposta
from kamba_agr.eventos.notificacao import Notificacao, NotificacaoIndisponivel
from kamba_agr.eventos.pela_resposta import (
    LIVRE,
    MARGEM_DA_JANELA,
    SEM_TEMPLATE,
    TEMPLATE,
    NotificacaoPelaResposta,
    janela_aberta,
)

AGORA = datetime.datetime(2026, 11, 19, 12, 0, tzinfo=datetime.UTC)
CHAVE = "orcamento:q1:1700000000000000"


class Base(test_saida.Base):
    def __init__(self, expira: datetime.datetime | None, modo: str = "bot") -> None:
        super().__init__()
        self.conversas = {(TENANT, CONVERSA): (expira, modo)}


class Cursor(test_saida.Cursor):
    def execute(self, sql: str, p: tuple = ()) -> None:
        if sql is pela_resposta.SQL_JANELA_DA_CONVERSA:
            self.base.instrucoes.append(sql)
            tenant, conversa = p
            assert tenant == self.tenant, "tenant fora do contexto"
            assert "WHERE tenant_id = %s AND id = %s" in sql
            linha = self.base.conversas.get((tenant, conversa))
            self.linhas = [] if linha is None else [linha]
            return
        if sql is saida.SQL_INSERIR_COM_TEMPLATE:
            # A mesma semantica do `SQL_INSERIR`, com as duas colunas a mais.
            *linha, nome, parametros = p
            antes = len(self.base.respostas)
            super().execute(saida.SQL_INSERIR, tuple(linha))
            self.base.instrucoes[-1] = sql
            if len(self.base.respostas) > antes:
                self.base.respostas[-1].update(template=nome, parametros=list(parametros))
            return
        super().execute(sql, p)


class Ligacao(test_saida.Ligacao):
    def cursor(self) -> Cursor:
        return Cursor(self.base)


PARAMETROS = ("ORC-ABCDEFGH",)


def notificacao(
    texto: str = "Orcamento - nao e factura", parametros: tuple[str, ...] = PARAMETROS
) -> Notificacao:
    return Notificacao(
        contact_id=CONTACTO,
        conversation_id=CONVERSA,
        texto=texto,
        template="orcamento_pronto",
        parametros=parametros,
    )


class TestEscolhaDaJanela(unittest.TestCase):
    def porta(self, base: Base) -> NotificacaoPelaResposta:
        return NotificacaoPelaResposta(lambda: Ligacao(base), relogio=lambda: AGORA)

    def notificar(self, base: Base, chave: str = CHAVE) -> str:
        return self.porta(base).notificar(tenant_id=TENANT, notificacao=notificacao(), chave=chave)

    def test_com_a_janela_aberta_grava_a_resposta_e_emite(self) -> None:
        base = Base(AGORA + datetime.timedelta(hours=3))
        self.assertEqual(self.notificar(base), LIVRE)
        self.assertEqual(len(base.respostas), 1)
        self.assertEqual(len(base.eventos), 1)
        resposta = base.respostas[0]
        self.assertEqual(
            (resposta["chave"], resposta["conversa"], resposta["contacto"], resposta["canal"]),
            (CHAVE, CONVERSA, CONTACTO, "whatsapp"),
        )
        self.assertEqual(resposta["texto"], "Orcamento - nao e factura")
        # Texto livre: a linha sai pelo `SQL_INSERIR` do turno, sem *template*.
        self.assertNotIn("template", resposta)
        self.assertIn(saida.SQL_INSERIR, base.instrucoes)
        # O inicio do envio vai para o `PreSendGuard` do KAM-018 como inicio do turno.
        self.assertEqual(resposta["inicio"], AGORA)
        self.assertEqual(base.fechadas, 1)

    def test_a_janela_dentro_da_margem_conta_como_fechada(self) -> None:
        """Quatro minutos de janela: o `worker-canal` podia ja a ver fechada."""
        base = Base(AGORA + datetime.timedelta(minutes=4))
        self.assertEqual(self.notificar(base), TEMPLATE)
        self.assertEqual(base.respostas[0]["template"], "orcamento_pronto")

    def test_a_janela_logo_depois_da_margem_conta_como_aberta(self) -> None:
        base = Base(AGORA + MARGEM_DA_JANELA + datetime.timedelta(seconds=1))
        self.assertEqual(self.notificar(base), LIVRE)
        self.assertNotIn("template", base.respostas[0])

    def test_a_janela_fechada_ou_nunca_aberta_grava_o_template_com_os_valores(self) -> None:
        for expira in (AGORA - datetime.timedelta(minutes=1), None):
            with self.subTest(expira=expira):
                base = Base(expira)
                self.assertEqual(self.notificar(base), TEMPLATE)
                self.assertEqual((len(base.respostas), len(base.eventos)), (1, 1))
                resposta = base.respostas[0]
                self.assertEqual(
                    (resposta["template"], resposta["parametros"], resposta["chave"]),
                    ("orcamento_pronto", list(PARAMETROS), CHAVE),
                )
                # O texto vai na mesma linha: o que sairia com a janela aberta.
                self.assertEqual(resposta["texto"], "Orcamento - nao e factura")
                self.assertIn(saida.SQL_INSERIR_COM_TEMPLATE, base.instrucoes)

    def test_o_template_repetido_nao_grava_nem_emite_outra_vez(self) -> None:
        base = Base(AGORA - datetime.timedelta(hours=1))
        self.assertEqual([self.notificar(base) for _ in range(3)], [TEMPLATE] * 3)
        self.assertEqual((len(base.respostas), len(base.eventos)), (1, 1))

    def test_uma_conversa_fora_do_modo_bot_nao_envia(self) -> None:
        """O `PreSendGuard` recusava; a proposta ficava `enviado` sem ter saido."""
        for modo in ("dono", "humano", "pausada"):
            for expira in (AGORA + datetime.timedelta(hours=3), AGORA - datetime.timedelta(hours=3)):
                with self.subTest(modo=modo, expira=expira):
                    base = Base(expira, modo=modo)
                    self.assertEqual(self.notificar(base), SEM_TEMPLATE)
                    self.assertEqual(base.respostas, [])

    def test_uma_conversa_de_outro_tenant_nao_se_ve_e_nao_envia(self) -> None:
        base = Base(AGORA + datetime.timedelta(hours=3))
        base.conversas = {("outro", CONVERSA): (AGORA + datetime.timedelta(hours=3), "bot")}
        self.assertEqual(self.notificar(base), SEM_TEMPLATE)
        self.assertEqual(base.respostas, [])

    def test_a_mesma_chave_nao_grava_nem_emite_outra_vez(self) -> None:
        base = Base(AGORA + datetime.timedelta(hours=3))
        self.assertEqual([self.notificar(base) for _ in range(3)], [LIVRE] * 3)
        self.assertEqual((len(base.respostas), len(base.eventos)), (1, 1))

    def test_chaves_diferentes_dao_respostas_diferentes(self) -> None:
        base = Base(AGORA + datetime.timedelta(hours=3))
        self.notificar(base, CHAVE)
        self.notificar(base, CHAVE + ":janela")
        self.assertEqual([r["chave"] for r in base.respostas], [CHAVE, CHAVE + ":janela"])


class TestFalhas(unittest.TestCase):
    def test_sem_ligacao_e_indisponivel(self) -> None:
        def abrir() -> Any:
            raise OSError("base em baixo")

        porta = NotificacaoPelaResposta(abrir, relogio=lambda: AGORA)
        with self.assertRaises(NotificacaoIndisponivel):
            porta.notificar(tenant_id=TENANT, notificacao=notificacao(), chave=CHAVE)

    def test_uma_falha_da_base_e_indisponivel_e_fecha_a_ligacao(self) -> None:
        base = Base(AGORA + datetime.timedelta(hours=3))

        class Partida(Ligacao):
            def cursor(self) -> Any:
                raise RuntimeError("ligacao partida")

        porta = NotificacaoPelaResposta(lambda: Partida(base), relogio=lambda: AGORA)
        with self.assertRaises(NotificacaoIndisponivel):
            porta.notificar(tenant_id=TENANT, notificacao=notificacao(), chave=CHAVE)
        self.assertEqual(base.fechadas, 1)

    def test_um_parametro_sem_a_forma_da_meta_e_defeito(self) -> None:
        base = Base(AGORA - datetime.timedelta(hours=1))
        porta = NotificacaoPelaResposta(lambda: Ligacao(base), relogio=lambda: AGORA)
        for parametros in (("",), ("ORC\nX",), ("ORC\tX",), ("x",) * 11):
            with self.subTest(parametros=parametros):
                with self.assertRaises(saida.RespostaInvalidaError):
                    porta.notificar(
                        tenant_id=TENANT, notificacao=notificacao(parametros=parametros), chave=CHAVE
                    )
        self.assertEqual(base.respostas, [])

    def test_um_texto_sem_a_forma_da_tabela_e_defeito_e_nao_indisponibilidade(self) -> None:
        base = Base(AGORA + datetime.timedelta(hours=3))
        porta = NotificacaoPelaResposta(lambda: Ligacao(base), relogio=lambda: AGORA)
        with self.assertRaises(saida.RespostaInvalidaError):
            porta.notificar(tenant_id=TENANT, notificacao=notificacao("x" * 5000), chave=CHAVE)
        self.assertEqual(base.respostas, [])


class TestJanelaAberta(unittest.TestCase):
    def test_sem_conversa_nao_ha_janela(self) -> None:
        self.assertFalse(janela_aberta(None, AGORA))

    def test_a_margem_e_de_cinco_minutos(self) -> None:
        self.assertEqual(MARGEM_DA_JANELA, datetime.timedelta(minutes=5))
        self.assertFalse(janela_aberta((AGORA + MARGEM_DA_JANELA, "bot"), AGORA))


class TestLigacaoNoArranque(unittest.TestCase):
    """O `main()` real liga a porta `orcamentos` a resposta do KAM-224.

    Sem esta linha no `__main__`, o adaptador estava certo e a proposta
    continuava no `OutboundPorLigar` — o defeito do KAM-186, noutra porta.
    """

    def test_a_porta_dos_orcamentos_sai_pela_resposta(self) -> None:
        import test_grafos

        arranque = test_grafos.TestLigacaoDoArranque("test_o_arranque_passa")
        arranque.setUp()
        self.addCleanup(arranque.doCleanups)
        self.assertEqual(arranque.codigo, 0)
        portas = arranque.capturado["compilar"][0][1]
        self.assertIsInstance(portas["orcamentos"]._saida, NotificacaoPelaResposta)


if __name__ == "__main__":
    unittest.main()
