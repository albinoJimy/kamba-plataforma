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
import threading
import re
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
        elif sql is saida.SQL_INSERIR or sql is saida.SQL_INSERIR_COM_TEMPLATE or sql is saida.SQL_INSERIR_COM_MEDIA:
            # A do *template* (KAM-221) leva o nome e os valores no fim; o
            # resto da semantica e a mesma.
            tenant, chave, contacto, conversa, canal, texto, botoes, inicio = p[:8]
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
                    # KAM-246: a imagem so com a coluna no texto da instrucao.
                    "media": p[8] if "media_ref" in sql else None,
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

    def test_com_template_o_payload_fica_nas_cinco_chaves(self) -> None:
        """O *template* e os valores ficam na linha, e o evento nao muda (KAM-221).

        O ADR-010 e a decisao B do KAM-224: o `agent.replied` leva so
        identificadores, e os consumidores leem o resto por referencia.
        """
        reply_id = self.emitir(template="orcamento_pronto", parametros=("ORC-ABCDEFGH",))
        _tipo, _tenant, _agregado, payload = self.base.eventos[0]
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
        self.assertNotIn("ORC-ABCDEFGH", payload)

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


class TestIteraveisDeUmaPassagem(unittest.TestCase):
    """Achado 3 da revisao do KAM-226: a forma valida-se duas vezes, e um gerador so se le uma."""

    def test_um_gerador_de_botoes_grava_os_botoes(self) -> None:
        base = Base()
        saida.emitir_resposta(
            Ligacao(base), estado(), "ola", chave="k:0", botoes=(b for b in ["cancelar"])
        )
        self.assertEqual(json.loads(base.respostas[0]["botoes"]), [{"id": "cancelar", "titulo": "Cancelar"}])


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
            # KAM-226: o «Aceito» que a proposta leva, com a referencia dela.
            f"{vendedor.PREFIXO_DO_ACEITO_ORCAMENTO}ORC-ABCDEFGH",
            servicos.BOTAO_HUMANO,
            servicos.BOTAO_CANCELAR,
            f"{servicos.PREFIXO_DE_CONFIRMACAO}r1",
        ):
            with self.subTest(botao=identificador):
                self.assertTrue(saida.titulo_do_botao(identificador))

    def test_os_botoes_do_catalogo_tem_titulo_e_os_prefixos_sao_os_das_regras(self) -> None:
        # KAM-119: os quatro botoes da conversa do catalogo do dono.
        from kamba_agr.catalogo import regras
        from kamba_agr.social import regras as social_regras

        ingestao = "11111111-2222-3333-4444-555555555555"
        for identificador in (
            regras.botao_do_preco(ingestao, 4_500_000),
            regras.botao_de_corrigir_preco(ingestao),
            regras.botao_do_stock(ingestao, 12),
            regras.botao_de_corrigir_stock(ingestao),
            regras.botao_do_mesmo_produto(ingestao),
            regras.botao_de_outro_produto(ingestao),
            # KAM-244: a retoma de uma ingestao que o screening nao decidiu.
            regras.botao_de_retomar(ingestao),
        ):
            with self.subTest(botao=identificador):
                self.assertTrue(saida.titulo_do_botao(identificador))
                self.assertIsNone(re.search(r"\d", saida.titulo_do_botao(identificador)))
        self.assertEqual(
            set(saida.TITULOS_POR_PREFIXO),
            {
                regras.PREFIXO_DO_PRECO,
                regras.PREFIXO_DE_CORRIGIR_PRECO,
                regras.PREFIXO_DO_STOCK,
                regras.PREFIXO_DE_CORRIGIR_STOCK,
                regras.PREFIXO_DO_MESMO_PRODUTO,
                regras.PREFIXO_DE_OUTRO_PRODUTO,
                regras.PREFIXO_DE_RETOMAR,
                # KAM-121: a legenda de um item do social.
                social_regras.PREFIXO_DA_LEGENDA,
            },
        )
        # O prefixo sozinho nao e botao.
        with self.assertRaises(saida.RespostaInvalidaError):
            saida.titulo_do_botao(regras.PREFIXO_DO_PRECO)


class TestSaidaPorEvento(unittest.TestCase):
    def setUp(self) -> None:
        self.base = Base()
        self.avisos: list[str] = []
        self.porta = SaidaPorEvento(
            lambda: Ligacao(self.base),
            relogio=lambda: datetime.datetime(2026, 11, 19, 12, 0, tzinfo=datetime.UTC),
            aviso=self.avisos.append,
        )

    def enviar(self, porta: SaidaPorEvento | None = None, *, chave: str = "k:0") -> None:
        asyncio.run((porta or self.porta).enfileirar(estado(), "ola", chave=chave))

    def test_abre_e_fecha_uma_ligacao_por_envio(self) -> None:
        self.enviar(chave="k:0")
        self.enviar(chave="k:1")
        self.assertEqual(self.base.fechadas, 2)
        self.assertEqual(len(self.base.eventos), 2)

    def test_a_repeticao_avisa_e_nao_levanta(self) -> None:
        self.enviar()
        self.enviar()
        self.assertEqual(self.avisos, ["resposta_repetida"])
        self.assertEqual(len(self.base.eventos), 1)

    def test_fora_de_um_turno_o_inicio_e_o_instante_do_envio(self) -> None:
        self.enviar()
        self.assertEqual(
            self.base.respostas[0]["inicio"],
            datetime.datetime(2026, 11, 19, 12, 0, tzinfo=datetime.UTC),
        )

    def test_dentro_de_um_turno_o_inicio_e_o_do_turno(self) -> None:
        inicio = datetime.datetime(2026, 11, 19, 11, 59, 58, tzinfo=datetime.UTC)

        async def no() -> None:
            # Uma tarefa nova, como as do LangGraph: herda o contexto.
            await asyncio.create_task(asyncio.to_thread(lambda: None))
            await self.porta.enfileirar(estado(), "ola", chave="k:0")

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
        self.enviar(porta)
        self.assertEqual(self.base.respostas[0]["canal"], "painel")

    def test_por_omissao_o_canal_e_o_whatsapp(self) -> None:
        self.enviar()
        self.assertEqual(self.base.respostas[0]["canal"], "whatsapp")


class TestUmaBaseLenta(unittest.TestCase):
    """KAM-227: a ida a base do envio sai da *event loop*.

    **A base so responde quando o outro turno tiver andado.** O `INSERT` do
    duplo espera por um `threading.Event` que so o outro turno — uma corrotina
    na mesma *event loop* — pode soltar, depois de `PASSOS` voltas. Se o envio
    corresse na *event loop*, o outro turno nao andava, e a base so se soltava
    pelo prazo: o ensaio distingue «soltou-a o outro turno» de «soltou-a o
    relogio», e nao depende de quantas voltas cabem num intervalo.

    O controlo corre o mesmo corpo **na** *event loop* — a forma anterior ao
    KAM-227 — e mostra que ai o outro turno nao da volta nenhuma. Sem ele, um
    duplo que nunca esperasse deixava o primeiro ensaio verde por vacuidade.
    """

    PASSOS = 5

    def correr(self, enviar: Any, *, prazo: float) -> tuple[bool, int, Base]:
        base = Base()
        solta = threading.Event()
        visto: dict[str, bool] = {}

        class CursorLento(Cursor):
            def execute(self, sql: str, p: tuple = ()) -> None:
                if sql is saida.SQL_INSERIR:
                    visto["pelo_outro_turno"] = solta.wait(prazo)
                super().execute(sql, p)

        class LigacaoLenta(Ligacao):
            def cursor(self) -> Cursor:
                return CursorLento(self.base)

        passos = 0

        async def outro_turno() -> None:
            nonlocal passos
            while passos < self.PASSOS:
                await asyncio.sleep(0.01)
                passos += 1
            solta.set()

        async def principal() -> int:
            outro = asyncio.create_task(outro_turno())
            await asyncio.sleep(0)  # o outro turno arranca e fica no primeiro sleep
            await enviar(lambda: LigacaoLenta(base))
            durante = passos
            await outro
            return durante

        durante = asyncio.run(principal())
        return visto["pelo_outro_turno"], durante, base

    def test_uma_base_lenta_nao_para_os_outros_turnos(self) -> None:
        async def pela_porta(abrir: Any) -> None:
            await SaidaPorEvento(abrir).enfileirar(estado(), "ola", chave="k:0")

        pelo_outro_turno, durante, base = self.correr(pela_porta, prazo=5.0)
        self.assertTrue(pelo_outro_turno, "a base soltou-se pelo prazo: o outro turno parou")
        self.assertGreaterEqual(durante, self.PASSOS)
        self.assertEqual((len(base.respostas), len(base.eventos), base.fechadas), (1, 1, 1))

    def test_o_controlo_na_event_loop_para_os_outros_turnos(self) -> None:
        async def na_event_loop(abrir: Any) -> None:
            ligacao = abrir()
            try:
                emitir_resposta(ligacao, estado(), "ola", chave="k:0")
            finally:
                ligacao.close()

        pelo_outro_turno, durante, base = self.correr(na_event_loop, prazo=0.3)
        self.assertFalse(pelo_outro_turno)
        self.assertEqual(durante, 0)
        self.assertEqual(len(base.eventos), 1)


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


class TestAImagemDaResposta(unittest.TestCase):
    """A chave da arte na `agent_replies` (KAM-246): do tenant, da classe `arte`, sem *template*."""

    ARTE = f"t/{TENANT}/arte/2026/11/0b1c2d3e-4f50-4617-8a9b-0c1d2e3f4a5b"

    def setUp(self) -> None:
        self.base = Base()

    def emitir(self, **argumentos: Any) -> str | None:
        return emitir_resposta(Ligacao(self.base), estado(), "Pre-visualizacao.", chave="k:0", **argumentos)

    def test_a_imagem_grava_se_com_a_instrucao_dela_e_o_evento_nao_muda(self) -> None:
        reply_id = self.emitir(media=self.ARTE, botoes=("falar_com_humano",))
        ordem = [s for s in self.base.instrucoes if not s.startswith("SELECT set_config")]
        self.assertEqual(ordem, [saida.SQL_INSERIR_COM_MEDIA, saida.SQL_EMITIR])
        self.assertEqual(self.base.respostas[0]["media"], self.ARTE)
        payload = json.loads(self.base.eventos[0][3])
        self.assertEqual(set(payload), {"reply_id", "thread_id", "conversation_id", "contact_id", "canal"})
        self.assertEqual(payload["reply_id"], reply_id)
        self.assertNotIn(self.ARTE, self.base.eventos[0][3])

    def test_sem_imagem_a_instrucao_e_a_de_sempre(self) -> None:
        self.emitir()
        self.assertIn(saida.SQL_INSERIR, self.base.instrucoes)
        self.assertNotIn(saida.SQL_INSERIR_COM_MEDIA, self.base.instrucoes)
        self.assertIsNone(self.base.respostas[0]["media"])

    def test_recusa_antes_da_base_uma_chave_alheia_de_outra_classe_um_url_ou_um_template(self) -> None:
        for media in (
            f"t/{OUTRO}/arte/2026/11/0b1c2d3e-4f50-4617-8a9b-0c1d2e3f4a5b",
            f"t/{TENANT}/foto/2026/11/0b1c2d3e-4f50-4617-8a9b-0c1d2e3f4a5b",
            "https://exemplo.invalid/arte.jpg",
            f"{self.ARTE}/../x",
            "",
        ):
            with self.assertRaises(RespostaInvalidaError, msg=media):
                self.emitir(media=media)
        with self.assertRaises(RespostaInvalidaError):
            self.emitir(media=self.ARTE, template="orcamento_pronto", parametros=("ORC-ABCDEFGH",))
        self.assertEqual(self.base.instrucoes, [], "nada chegou a base")

    def test_a_porta_passa_a_imagem_a_linha(self) -> None:
        porta = SaidaPorEvento(lambda: Ligacao(self.base))
        asyncio.run(porta.enfileirar(estado(), "ola", chave="k:9", media=self.ARTE))
        self.assertEqual(self.base.respostas[0]["media"], self.ARTE)

    def test_a_classe_e_a_da_arte(self) -> None:
        self.assertEqual(saida.CLASSE_DA_MEDIA, "arte")
        self.assertEqual(saida.media_da_resposta(self.ARTE, TENANT.upper()), self.ARTE)
        self.assertIsNone(saida.media_da_resposta(None, TENANT))
