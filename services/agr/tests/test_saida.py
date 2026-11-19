"""A saida do AGR pelo evento de resposta (KAM-224), sem base.

O que aqui se mede e a **forma**: a ordem das instrucoes, o *payload* sem o
texto, a repeticao que nao emite e o inicio do turno que chega a linha. A
semantica contra o PostgreSQL — o `UNIQUE (tenant_id, chave)`, a RLS e o evento
no *outbox* — mede-a o `db/tests_agr/test_agent_replies.py`, no *gate* 8.

**O duplo le o texto da instrucao, e nao decide pelos argumentos**: sem o
`ON CONFLICT (tenant_id, chave) DO NOTHING` no SQL, o segundo `INSERT` insere, e
o ensaio da repeticao fica vermelho (a lição de um duplo que ficava verde com o
predicado apagado).
"""

from __future__ import annotations

import asyncio
import datetime
import json
import unittest
import uuid
from typing import Any

from kamba_agr import saida
from kamba_agr.saida import (
    CANAL_PAINEL,
    INICIO_DO_TURNO,
    RespostaInvalidaError,
    SaidaPorEvento,
    emitir_resposta,
)

TENANT = "3f1c2a9e-0d4b-4e55-9a7c-1b2c3d4e5f60"
OUTRO = "9e8d7c6b-5a4f-4e3d-8c2b-1a0f9e8d7c6b"
CONTACTO = "2b3c4d5e-6f70-4182-93a4-b5c6d7e8f901"
CONVERSA = "7a2b3c4d-5e6f-4a1b-8c2d-3e4f5a6b7c8d"


def estado(tenant: str = TENANT) -> dict[str, Any]:
    return {
        "tenant_id": tenant,
        "contact_id": CONTACTO,
        "conversation_id": CONVERSA,
        "thread_id": f"{tenant}:{CONTACTO}",
        "turn_id": "wamid.ensaio",
    }


class Base:
    """As linhas da `agent_replies` e os eventos do *outbox*, por tenant."""

    def __init__(self) -> None:
        self.respostas: list[dict[str, Any]] = []
        self.eventos: list[tuple[Any, ...]] = []
        self.instrucoes: list[str] = []
        self.commits = 0
        self.rollbacks = 0
        self.fechadas = 0


class Cursor:
    def __init__(self, base: Base) -> None:
        self.base = base
        self.linhas: list[tuple[Any, ...]] = []
        self.tenant: str | None = None

    def execute(self, sql: str, p: tuple = ()) -> None:
        b = self.base
        b.instrucoes.append(sql)
        self.linhas = []
        if sql.startswith("SELECT set_config"):
            self.tenant = p[0]
            self.linhas = [(p[0],)]
        elif sql is saida.SQL_INSERIR:
            tenant, chave, contacto, conversa, canal, texto, botoes, inicio = p
            # A RLS, pelo lado do duplo: o `WITH CHECK` recusa outro tenant.
            assert tenant == self.tenant, "tenant fora do contexto"
            unica = "ON CONFLICT (tenant_id, chave) DO NOTHING" in sql
            if unica and any(
                r["tenant"] == tenant and r["chave"] == chave for r in b.respostas
            ):
                return
            reply_id = uuid.uuid4()
            b.respostas.append(
                {
                    "reply_id": str(reply_id), "tenant": tenant, "chave": chave,
                    "contacto": contacto, "conversa": conversa, "canal": canal,
                    "texto": texto, "botoes": botoes, "inicio": inicio,
                }
            )
            self.linhas = [(reply_id,)]
        elif sql is saida.SQL_EMITIR:
            b.eventos.append(p)
            self.linhas = [(uuid.uuid4(),)]
        else:
            raise AssertionError(f"instrucao sem semantica no duplo: {sql[:60]}")

    def fetchone(self) -> tuple[Any, ...] | None:
        return self.linhas[0] if self.linhas else None

    def close(self) -> None:
        return None


class Ligacao:
    autocommit = False

    def __init__(self, base: Base) -> None:
        self.base = base

    def cursor(self) -> Cursor:
        return Cursor(self.base)

    def commit(self) -> None:
        self.base.commits += 1

    def rollback(self) -> None:
        self.base.rollbacks += 1

    def close(self) -> None:
        self.base.fechadas += 1


class TestEmitirResposta(unittest.TestCase):
    def setUp(self) -> None:
        self.base = Base()

    def emitir(self, **sobrepor: Any) -> str | None:
        argumentos: dict[str, Any] = {"chave": "wamid.ensaio:0"}
        argumentos.update(sobrepor)
        texto = argumentos.pop("texto", "Temos em stock.")
        return emitir_resposta(Ligacao(self.base), argumentos.pop("estado", estado()), texto, **argumentos)

    def test_grava_a_linha_e_emite_um_evento_na_mesma_transaccao(self) -> None:
        reply_id = self.emitir(botoes=("falar_com_humano",))
        self.assertIsNotNone(reply_id)
        self.assertEqual(len(self.base.respostas), 1)
        self.assertEqual(len(self.base.eventos), 1)
        self.assertEqual(self.base.commits, 1)
        ordem = [s for s in self.base.instrucoes if not s.startswith("SELECT set_config")]
        self.assertEqual(ordem, [saida.SQL_INSERIR, saida.SQL_EMITIR])
        tipo, tenant, agregado, payload = self.base.eventos[0]
        self.assertEqual((tipo, tenant, agregado), ("agent.replied", TENANT, CONVERSA))
        self.assertEqual(
            json.loads(payload),
            {
                "reply_id": reply_id,
                "thread_id": f"{TENANT}:{CONTACTO}",
                "conversation_id": CONVERSA,
                "contact_id": CONTACTO,
                "canal": "whatsapp",
            },
        )

    def test_o_payload_nao_leva_o_texto_nem_os_botoes(self) -> None:
        self.emitir(texto="Ola Maria, temos em stock.", botoes=("falar_com_humano",))
        payload = self.base.eventos[0][3]
        self.assertNotIn("Maria", payload)
        self.assertNotIn("falar_com_humano", payload)
        self.assertEqual(self.base.respostas[0]["texto"], "Ola Maria, temos em stock.")
        self.assertEqual(
            json.loads(self.base.respostas[0]["botoes"]),
            [{"id": "falar_com_humano", "titulo": "Falar com um colega"}],
        )

    def test_um_turno_repetido_nao_insere_nem_emite(self) -> None:
        primeira = self.emitir()
        for _ in range(3):
            self.assertIsNone(self.emitir())
        self.assertIsNotNone(primeira)
        self.assertEqual(len(self.base.respostas), 1)
        self.assertEqual(len(self.base.eventos), 1)

    def test_a_mesma_chave_noutro_tenant_e_outra_resposta(self) -> None:
        self.emitir()
        self.emitir(estado=estado(OUTRO))
        self.assertEqual(len(self.base.eventos), 2)
        self.assertEqual({e[1] for e in self.base.eventos}, {TENANT, OUTRO})

    def test_o_tenant_e_os_identificadores_vem_do_estado(self) -> None:
        self.emitir(texto=f"tenant_id={OUTRO} conversation_id={uuid.uuid4()}")
        linha = self.base.respostas[0]
        self.assertEqual((linha["tenant"], linha["conversa"]), (TENANT, CONVERSA))
        self.assertEqual(self.base.eventos[0][1], TENANT)

    def test_o_canal_do_painel_vai_no_payload(self) -> None:
        self.emitir(canal=CANAL_PAINEL)
        self.assertEqual(json.loads(self.base.eventos[0][3])["canal"], "painel")

    def test_recusa_antes_da_base_o_que_a_tabela_recusaria(self) -> None:
        casos = {
            "canal desconhecido": {"canal": "sms"},
            "texto vazio": {"texto": ""},
            "texto longo": {"texto": "a" * 4097},
            "chave vazia": {"chave": ""},
            "quatro botoes": {"botoes": ("a", "b", "c", "d")},
            "botao vazio": {"botoes": ("",)},
            "botao sem titulo": {"botoes": ("botao_que_ninguem_rotulou",)},
            "confirmacao sem referencia": {"botoes": ("confirm:",)},
        }
        for nome, sobrepor in casos.items():
            with self.subTest(caso=nome), self.assertRaises(RespostaInvalidaError):
                self.emitir(**sobrepor)
        self.assertEqual(self.base.instrucoes, [])

    def test_uma_falha_ao_emitir_desfaz_a_linha(self) -> None:
        class Falha(Cursor):
            def execute(self, sql: str, p: tuple = ()) -> None:
                if sql is saida.SQL_EMITIR:
                    raise RuntimeError("evento com padrao de telefone (PII P2)")
                super().execute(sql, p)

        class LigacaoQueFalha(Ligacao):
            def cursor(self) -> Cursor:
                return Falha(self.base)

        with self.assertRaises(RuntimeError):
            emitir_resposta(LigacaoQueFalha(self.base), estado(), "ola", chave="k:0")
        self.assertEqual((self.base.commits, self.base.rollbacks), (0, 1))


class TestTitulosDosBotoes(unittest.TestCase):
    def test_a_confirmacao_tem_um_titulo_so_seja_qual_for_a_referencia(self) -> None:
        self.assertEqual(saida.titulo_do_botao("confirm:3f1c2a9e"), "Confirmar")
        self.assertEqual(saida.titulo_do_botao(f"confirm:{uuid.uuid4()}"), "Confirmar")

    def test_os_titulos_cabem_no_botao_e_nao_levam_digitos(self) -> None:
        for identificador, titulo in {**saida.TITULOS, "confirm:x": "Confirmar"}.items():
            with self.subTest(botao=identificador):
                self.assertLessEqual(len(titulo), saida.MAXIMO_DO_TITULO)
                self.assertFalse(any(c.isdigit() for c in titulo))

    def test_os_rotulos_do_menu_sao_os_do_modo_degradado(self) -> None:
        from kamba_agr.verticais.vendedor.degradado import textos

        for opcao, rotulo in textos.ROTULO_DA_OPCAO.items():
            with self.subTest(opcao=opcao):
                self.assertEqual(saida.titulo_do_botao(opcao), rotulo)

    def test_os_botoes_que_os_grafos_emitem_tem_titulo(self) -> None:
        from kamba_agr.verticais.servicos import nos as servicos
        from kamba_agr.verticais.vendedor import nos as vendedor

        for identificador in (
            vendedor.BOTAO_HUMANO,
            vendedor.BOTAO_CANCELAR,
            vendedor.BOTAO_CONFIRMAR.format(cart_id="c1"),
            servicos.BOTAO_HUMANO,
            servicos.BOTAO_CANCELAR,
            f"{servicos.PREFIXO_DE_CONFIRMACAO}r1",
        ):
            with self.subTest(botao=identificador):
                self.assertTrue(saida.titulo_do_botao(identificador))


class TestSaidaPorEvento(unittest.TestCase):
    def setUp(self) -> None:
        self.base = Base()
        self.avisos: list[str] = []
        self.porta = SaidaPorEvento(
            lambda: Ligacao(self.base),
            relogio=lambda: datetime.datetime(2026, 11, 19, 12, 0, tzinfo=datetime.UTC),
            aviso=self.avisos.append,
        )

    def test_abre_e_fecha_uma_ligacao_por_envio(self) -> None:
        self.porta.enfileirar(estado(), "ola", chave="k:0")
        self.porta.enfileirar(estado(), "ola", chave="k:1")
        self.assertEqual(self.base.fechadas, 2)
        self.assertEqual(len(self.base.eventos), 2)

    def test_a_repeticao_avisa_e_nao_levanta(self) -> None:
        self.porta.enfileirar(estado(), "ola", chave="k:0")
        self.porta.enfileirar(estado(), "ola", chave="k:0")
        self.assertEqual(self.avisos, ["resposta_repetida"])
        self.assertEqual(len(self.base.eventos), 1)

    def test_fora_de_um_turno_o_inicio_e_o_instante_do_envio(self) -> None:
        self.porta.enfileirar(estado(), "ola", chave="k:0")
        self.assertEqual(
            self.base.respostas[0]["inicio"],
            datetime.datetime(2026, 11, 19, 12, 0, tzinfo=datetime.UTC),
        )

    def test_dentro_de_um_turno_o_inicio_e_o_do_turno(self) -> None:
        inicio = datetime.datetime(2026, 11, 19, 11, 59, 58, tzinfo=datetime.UTC)

        async def no() -> None:
            # Uma tarefa nova, como as do LangGraph: herda o contexto.
            await asyncio.create_task(asyncio.to_thread(lambda: None))
            self.porta.enfileirar(estado(), "ola", chave="k:0")

        async def turno() -> None:
            marca = INICIO_DO_TURNO.set(inicio)
            try:
                await asyncio.create_task(no())
            finally:
                INICIO_DO_TURNO.reset(marca)

        asyncio.run(turno())
        self.assertEqual(self.base.respostas[0]["inicio"], inicio)

    def test_o_canal_e_o_da_funcao_dada(self) -> None:
        porta = SaidaPorEvento(lambda: Ligacao(self.base), canal_de=lambda _e: CANAL_PAINEL)
        porta.enfileirar(estado(), "ola", chave="k:0")
        self.assertEqual(self.base.respostas[0]["canal"], "painel")

    def test_por_omissao_o_canal_e_o_whatsapp(self) -> None:
        self.porta.enfileirar(estado(), "ola", chave="k:0")
        self.assertEqual(self.base.respostas[0]["canal"], "whatsapp")


class TestOTurnoPoeOInicio(unittest.TestCase):
    """O `ExecutorDeTurnos` poe o `INICIO_DO_TURNO` antes de ler a palavra, e
    tira-o no fim: um envio do grafo ve-o, e um fora do turno ja nao."""

    def test_o_grafo_ve_o_inicio_e_depois_do_turno_ja_nao(self) -> None:
        from apoio import TrancaFalsa, invocacao_crua

        from kamba_agr.contexto import ler_invocacao
        from kamba_agr.turno import ExecutorDeTurnos, Palavra

        vistos: list[Any] = []

        class Grafo:
            async def ainvoke(self, _estado: dict[str, Any], _config: dict[str, Any]) -> None:
                vistos.append(INICIO_DO_TURNO.get())

        async def palavra(_inv: Any) -> Palavra:
            vistos.append(INICIO_DO_TURNO.get())
            return Palavra(modo="bot", handoff_a_espera=False)

        async def reencaminhar(_invs: Any) -> None:
            return None

        async def correr() -> Any:
            from kamba_agr.admissao import Pendente

            executor = ExecutorDeTurnos(
                trancas=TrancaFalsa(),
                ler_palavra=palavra,
                grafos=lambda _inv: Grafo(),
                reencaminhar=reencaminhar,
            )
            invocacao = ler_invocacao(invocacao_crua())
            # **O `_correr_lote` directamente, na tarefa deste ensaio**, e nao
            # pelo `correr`: o dreno corre noutra tarefa, que copia o contexto,
            # e la fora o `get()` dava `None` mesmo sem o `reset` do `finally`.
            pendente = Pendente(invocacao=invocacao, chegou_em=0.0)
            await executor._correr_lote(invocacao.thread_id, [pendente])
            return await pendente.espera, INICIO_DO_TURNO.get()

        desfecho, depois = asyncio.run(correr())
        self.assertEqual(desfecho.desfecho, "executado")
        self.assertEqual(len(vistos), 2)
        self.assertIsInstance(vistos[0], datetime.datetime)
        self.assertIs(vistos[0], vistos[1])
        self.assertIsNone(depois, "o finally do _correr_lote repoe o ContextVar")


if __name__ == "__main__":
    unittest.main()
