"""Ritmo, coalescencia, tecto por *tenant* e contrapressao (criterios 3 e 5).

Com relogio fixo, nao com `sleep`: o teste mede a regra, nao a paciencia de
quem o corre. E a mesma escolha do `tests_eventos_consumo` com a escada de
recuo.
"""

from __future__ import annotations

import asyncio
import unittest
import uuid

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

    def _mensagens(self, quantas: int, **par):
        """`quantas` mensagens **diferentes** do mesmo contacto.

        Diferentes de proposito: o ritmo conta **mensagens** e nao entregas da
        mesma mensagem, e usar a mesma invocacao varias vezes media a
        idempotencia e nao o tecto (ver `TestRitmoEIdempotencia`).
        """
        primeira = inv(**par)
        saida = [primeira]
        for _ in range(quantas - 1):
            saida.append(
                inv(tenant_id=primeira.tenant_id, contact_id=primeira.contact_id)
            )
        return saida

    def test_passa_ate_ao_limite_e_recusa_a_seguir(self) -> None:
        mensagens = self._mensagens(4)
        for mensagem in mensagens[:3]:
            self.assertTrue(self.admissao.aceita_o_ritmo(mensagem))
        self.assertFalse(self.admissao.aceita_o_ritmo(mensagens[3]))
        self.assertEqual(METRICAS.ler()[f"{METRICA_RECUSADOS}:ritmo"], 1)

    def test_a_janela_desliza_e_liberta_quota(self) -> None:
        mensagens = self._mensagens(5)
        for mensagem in mensagens[:3]:
            self.admissao.aceita_o_ritmo(mensagem)
        self.assertFalse(self.admissao.aceita_o_ritmo(mensagens[3]))
        self.relogio.avancar(JANELA_DO_RITMO_S + 0.1)
        self.assertTrue(self.admissao.aceita_o_ritmo(mensagens[4]))

    def test_a_quota_e_por_contacto_e_nao_do_processo(self) -> None:
        de_a = self._mensagens(4)
        de_b = inv()
        for mensagem in de_a[:3]:
            self.admissao.aceita_o_ritmo(mensagem)
        self.assertFalse(self.admissao.aceita_o_ritmo(de_a[3]))
        self.assertTrue(self.admissao.aceita_o_ritmo(de_b))

    def test_dois_canais_do_mesmo_contacto_partilham_a_quota(self) -> None:
        # A chave e o `thread_id`, que e `(tenant, contacto)` e nao a conversa:
        # e o que «por contacto» quer dizer. As conversas sao diferentes.
        mensagens = self._mensagens(3)
        for mensagem in mensagens:
            self.assertTrue(self.admissao.aceita_o_ritmo(mensagem))
        noutro_canal = inv(
            tenant_id=mensagens[0].tenant_id,
            contact_id=mensagens[0].contact_id,
            conversation_id=str(uuid.uuid4()),
        )
        self.assertNotEqual(
            noutro_canal.conversation_id, mensagens[0].conversation_id
        )
        self.assertFalse(self.admissao.aceita_o_ritmo(noutro_canal))

    def test_zero_e_sem_limite(self) -> None:
        admissao = Admissao(tectos=Tectos(ritmo_por_contacto=0), relogio=self.relogio)
        for mensagem in self._mensagens(50):
            self.assertTrue(admissao.aceita_o_ritmo(mensagem))

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


class TestRitmoEIdempotencia(unittest.TestCase):
    """A re-entrega do mesmo *job* nao gasta quota nova.

    O cenario que isto fecha, e que a revisao adversarial mediu: com o tecto do
    *tenant* cheio, vinte 503 do **mesmo** `wamid` consumiam os vinte lugares
    do minuto, e a mensagem seguinte — legitima — era descartada em silencio. E
    o efeito duplicado que o DoD da idempotencia diz nao existir.
    """

    def setUp(self) -> None:
        METRICAS.repor()
        self.relogio = Relogio()
        self.admissao = Admissao(
            tectos=Tectos(ritmo_por_contacto=3), relogio=self.relogio
        )

    def test_vinte_entregas_do_mesmo_turno_gastam_uma_quota(self) -> None:
        mensagem = inv()
        for _ in range(20):
            self.assertTrue(self.admissao.aceita_o_ritmo(mensagem))
        # Gastou **uma**: sobram duas das tres para mensagens novas.
        outras = [
            inv(tenant_id=mensagem.tenant_id, contact_id=mensagem.contact_id)
            for _ in range(3)
        ]
        self.assertTrue(self.admissao.aceita_o_ritmo(outras[0]))
        self.assertTrue(self.admissao.aceita_o_ritmo(outras[1]))
        self.assertFalse(self.admissao.aceita_o_ritmo(outras[2]))

    def test_passada_a_janela_a_mesma_mensagem_volta_a_contar(self) -> None:
        # O `turn_id` memorizado expira com a janela: senao o dicionario
        # crescia com um `wamid` por mensagem, para sempre.
        mensagem = inv()
        self.assertTrue(self.admissao.aceita_o_ritmo(mensagem))
        self.relogio.avancar(JANELA_DO_RITMO_S + 0.1)
        self.assertTrue(self.admissao.aceita_o_ritmo(mensagem))
        self.assertEqual(self.admissao.chaves_guardadas[0], 1)


class TestOsDicionariosEncolhem(unittest.TestCase):
    """Nenhum dos tres cresce com uma chave por contacto para sempre.

    O `_em_curso` ja o fazia e tinha teste; o `_chegadas` e o `_avisado` **nao**,
    e cresciam sem fim — a mesma classe de defeito que o modulo nomeia, a passar
    ao lado no proprio ficheiro. Achado da revisao adversarial.
    """

    def setUp(self) -> None:
        METRICAS.repor()
        self.relogio = Relogio()
        self.admissao = Admissao(
            tectos=Tectos(ritmo_por_contacto=3), relogio=self.relogio
        )

    def test_as_chegadas_desaparecem_quando_a_janela_esvazia(self) -> None:
        for _ in range(200):
            self.admissao.aceita_o_ritmo(inv())
        self.assertEqual(self.admissao.chaves_guardadas[0], 200)
        self.relogio.avancar(JANELA_DO_RITMO_S + 0.1)
        # Uma passagem nova por **um** contacto limpa a janela dele; os outros
        # limpam-se quando voltarem. O que importa e que a chave **sai**.
        uma = inv()
        self.admissao.aceita_o_ritmo(uma)
        for _ in range(3):
            self.admissao.aceita_o_ritmo(
                inv(tenant_id=uma.tenant_id, contact_id=uma.contact_id)
            )
        self.relogio.avancar(JANELA_DO_RITMO_S + 0.1)
        self.admissao.aceita_o_ritmo(uma)
        self.assertEqual(self.admissao.chaves_guardadas[0], 201)
        self.assertEqual(
            len(self.admissao._chegadas[uma.thread_id]), 1, "a janela nao limpou"
        )

    def test_os_avisados_expirados_desaparecem(self) -> None:
        for _ in range(200):
            self.admissao.deve_avisar(inv())
        self.assertEqual(self.admissao.chaves_guardadas[1], 200)
        self.relogio.avancar(JANELA_DO_RITMO_S + 0.1)
        self.admissao.deve_avisar(inv())
        self.assertEqual(
            self.admissao.chaves_guardadas[1], 1, "os avisos antigos nao sairam"
        )

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
