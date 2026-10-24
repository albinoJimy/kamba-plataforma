"""Ritmo, coalescencia, tecto por *tenant* e contrapressao (criterios 3 e 5).

Com relogio fixo, nao com `sleep`: o teste mede a regra, nao a paciencia de
quem o corre. E a mesma escolha do `tests_eventos_consumo` com a escada de
recuo.
"""

from __future__ import annotations

import asyncio
import unittest

from apoio import Relogio, invocacao_crua
from kamba_agr.admissao import (
    JANELA_DO_RITMO_S,
    Admissao,
    Pendente,
    TectoDoTenantCheioError,
    Tectos,
    _inteiro,
)
from kamba_agr.contexto import ler_invocacao
from kamba_agr.metricas import (
    METRICA_COALESCIDAS,
    METRICA_CONTRAPRESSAO,
    METRICA_RECUSADOS,
    METRICAS,
)


def inv(**sobrepor):
    return ler_invocacao(invocacao_crua(**sobrepor))


class TestRitmo(unittest.TestCase):
    def setUp(self) -> None:
        METRICAS.repor()
        self.relogio = Relogio()
        self.admissao = Admissao(
            tectos=Tectos(ritmo_por_contacto=3), relogio=self.relogio
        )

    def test_passa_ate_ao_limite_e_recusa_a_seguir(self) -> None:
        invocacao = inv()
        for _ in range(3):
            self.assertTrue(self.admissao.aceita_o_ritmo(invocacao))
        self.assertFalse(self.admissao.aceita_o_ritmo(invocacao))
        self.assertEqual(
            METRICAS.ler()[f"{METRICA_RECUSADOS}:ritmo"], 1
        )

    def test_a_janela_desliza_e_liberta_quota(self) -> None:
        invocacao = inv()
        for _ in range(3):
            self.admissao.aceita_o_ritmo(invocacao)
        self.assertFalse(self.admissao.aceita_o_ritmo(invocacao))
        self.relogio.avancar(JANELA_DO_RITMO_S + 0.1)
        self.assertTrue(self.admissao.aceita_o_ritmo(invocacao))

    def test_a_quota_e_por_contacto_e_nao_do_processo(self) -> None:
        a, b = inv(), inv()
        for _ in range(3):
            self.admissao.aceita_o_ritmo(a)
        self.assertFalse(self.admissao.aceita_o_ritmo(a))
        self.assertTrue(self.admissao.aceita_o_ritmo(b))

    def test_dois_canais_do_mesmo_contacto_partilham_a_quota(self) -> None:
        # A chave e o `thread_id`, que e `(tenant, contacto)` e nao a conversa:
        # e o que «por contacto» quer dizer.
        primeira = inv()
        segunda = inv(
            tenant_id=primeira.tenant_id,
            contact_id=primeira.contact_id,
        )
        for _ in range(3):
            self.admissao.aceita_o_ritmo(primeira)
        self.assertFalse(self.admissao.aceita_o_ritmo(segunda))

    def test_zero_e_sem_limite(self) -> None:
        admissao = Admissao(tectos=Tectos(ritmo_por_contacto=0), relogio=self.relogio)
        invocacao = inv()
        for _ in range(50):
            self.assertTrue(admissao.aceita_o_ritmo(invocacao))

    def test_o_aviso_e_um_por_contacto_por_janela(self) -> None:
        # «descarte silencioso com aviso unico» (criterio 5). Um aviso por
        # mensagem descartada era o atacante a escolher quantas linhas de
        # registo escrevemos.
        invocacao = inv()
        self.assertTrue(self.admissao.deve_avisar(invocacao))
        for _ in range(10):
            self.assertFalse(self.admissao.deve_avisar(invocacao))
        self.relogio.avancar(JANELA_DO_RITMO_S + 0.1)
        self.assertTrue(self.admissao.deve_avisar(invocacao))


class TestTectoPorTenant(unittest.IsolatedAsyncioTestCase):
    async def asyncSetUp(self) -> None:
        METRICAS.repor()

    async def test_o_tecto_recusa_a_quarta_e_liberta_no_fim(self) -> None:
        admissao = Admissao(tectos=Tectos(tecto_por_tenant=3))
        invocacao = inv()
        abertos = []
        for _ in range(3):
            vaga = admissao.vaga(invocacao)
            await vaga.__aenter__()
            abertos.append(vaga)
        self.assertEqual(admissao.em_curso(invocacao.tenant_id), 3)
        with self.assertRaises(TectoDoTenantCheioError):
            async with admissao.vaga(invocacao):
                pass
        self.assertEqual(METRICAS.ler()[f"{METRICA_RECUSADOS}:tecto_do_tenant"], 1)
        for vaga in abertos:
            await vaga.__aexit__(None, None, None)
        self.assertEqual(admissao.em_curso(invocacao.tenant_id), 0)

    async def test_o_tecto_de_um_tenant_nao_trava_outro(self) -> None:
        admissao = Admissao(tectos=Tectos(tecto_por_tenant=1))
        a, b = inv(), inv()
        async with admissao.vaga(a):
            with self.assertRaises(TectoDoTenantCheioError):
                async with admissao.vaga(a):
                    pass
            async with admissao.vaga(b):
                pass

    async def test_o_dicionario_nao_cresce_com_um_tenant_por_chave(self) -> None:
        # Memoria ilimitada a custa de outrem e a razao do `MAXIMO_DE_CANAIS`
        # do `chr/contrato.ts`; aqui fecha-se apagando a chave a zero.
        admissao = Admissao()
        for _ in range(200):
            async with admissao.vaga(inv()):
                pass
        self.assertEqual(len(admissao._em_curso), 0)

    async def test_zero_e_sem_tecto(self) -> None:
        # E o modo em que o criterio 2 se mede: com o tecto a 3, vinte
        # mensagens concorrentes davam dezessete recusas.
        admissao = Admissao(tectos=Tectos(tecto_por_tenant=0))
        invocacao = inv()
        abertos = []
        for _ in range(20):
            vaga = admissao.vaga(invocacao)
            await vaga.__aenter__()
            abertos.append(vaga)
        for vaga in abertos:
            await vaga.__aexit__(None, None, None)


class TestContrapressao(unittest.TestCase):
    def setUp(self) -> None:
        METRICAS.repor()

    def test_conta_a_passagem_do_limiar_e_nao_cada_turno_acima_dele(self) -> None:
        admissao = Admissao(tectos=Tectos(limiar_de_contrapressao=3))
        abertos = [admissao.na_fila() for _ in range(5)]
        for gestor in abertos:
            gestor.__enter__()
        self.assertEqual(admissao.a_espera, 5)
        self.assertEqual(METRICAS.ler()[METRICA_CONTRAPRESSAO], 1)
        for gestor in abertos:
            gestor.__exit__(None, None, None)
        self.assertEqual(admissao.a_espera, 0)


class TestCoalescencia(unittest.IsolatedAsyncioTestCase):
    async def asyncSetUp(self) -> None:
        METRICAS.repor()

    def _pendentes(self, instantes: list[float]) -> list[Pendente]:
        futuro = asyncio.get_running_loop().create_future
        saida = []
        for instante in instantes:
            pendente = Pendente(invocacao=inv(), chegou_em=instante)
            pendente.espera = futuro()
            saida.append(pendente)
        return saida

    async def test_junta_as_que_distam_menos_de_um_e_meio(self) -> None:
        admissao = Admissao(tectos=Tectos(coalescencia_ms=1_500))
        lote, resto = admissao.coalescer(self._pendentes([0.0, 0.5, 1.0, 5.0]))
        self.assertEqual(len(lote), 3)
        self.assertEqual(len(resto), 1)
        self.assertEqual(METRICAS.ler()[METRICA_COALESCIDAS], 2)

    async def test_a_distancia_e_ao_anterior_admitido_e_nao_ao_primeiro(self) -> None:
        # Dez mensagens a 1,4 s de intervalo: com a distancia ao primeiro davam
        # dois lotes; «distarem < 1,5 s» fala de duas consecutivas.
        admissao = Admissao(tectos=Tectos(coalescencia_ms=1_500))
        instantes = [i * 1.4 for i in range(10)]
        lote, resto = admissao.coalescer(self._pendentes(instantes))
        self.assertEqual(len(lote), 10)
        self.assertEqual(resto, [])

    async def test_na_fronteira_exacta_nao_junta(self) -> None:
        # «< 1,5 s» e estrito. 1,5 s exactos ficam fora.
        admissao = Admissao(tectos=Tectos(coalescencia_ms=1_500))
        lote, resto = admissao.coalescer(self._pendentes([0.0, 1.5]))
        self.assertEqual(len(lote), 1)
        self.assertEqual(len(resto), 1)

    async def test_com_a_janela_a_zero_cada_mensagem_e_um_turno(self) -> None:
        # E o modo do criterio 2: sem isto, um defeito na tranca ficava
        # invisivel — um turno a correr sozinho passa o teste da serializacao
        # por nao haver segundo turno nenhum.
        admissao = Admissao(tectos=Tectos(coalescencia_ms=0))
        lote, resto = admissao.coalescer(self._pendentes([0.0] * 20))
        self.assertEqual(len(lote), 1)
        self.assertEqual(len(resto), 19)
        self.assertNotIn(METRICA_COALESCIDAS, METRICAS.ler())

    async def test_uma_lista_vazia_nao_rebenta(self) -> None:
        self.assertEqual(Admissao().coalescer([]), ([], []))


class TestTectosDoAmbiente(unittest.TestCase):
    def test_le_os_quatro_numeros(self) -> None:
        tectos = Tectos.do_ambiente(
            {
                "AGR_RITMO_POR_CONTACTO": "7",
                "AGR_TECTO_POR_TENANT": "9",
                "AGR_COALESCENCIA_MS": "0",
                "AGR_LIMIAR_DE_CONTRAPRESSAO": "11",
            }
        )
        self.assertEqual(
            (
                tectos.ritmo_por_contacto,
                tectos.tecto_por_tenant,
                tectos.coalescencia_ms,
                tectos.limiar_de_contrapressao,
            ),
            (7, 9, 0, 11),
        )

    def test_sem_variaveis_ficam_as_omissoes(self) -> None:
        tectos = Tectos.do_ambiente({})
        self.assertEqual(tectos, Tectos())

    def test_um_valor_que_nao_e_inteiro_levanta_em_vez_de_cair_na_omissao(self) -> None:
        # Um tecto mal escrito que caia em silencio na omissao e um tecto que
        # ninguem configurou a parecer configurado.
        for valor in ("tres", "3.5", "-1", "0x3"):
            with self.subTest(valor=valor), self.assertRaises(ValueError) as apanhado:
                _inteiro("AGR_TECTO_POR_TENANT", 3, {"AGR_TECTO_POR_TENANT": valor})
            self.assertNotIn(valor, str(apanhado.exception))

    def test_um_valor_vazio_e_a_omissao(self) -> None:
        self.assertEqual(_inteiro("X", 5, {"X": "  "}), 5)


if __name__ == "__main__":
    unittest.main()
