"""O checkpointer contra um PostgreSQL de verdade (KAM-026).

E aqui que o SQL de `kamba_agr/consultas.py` se prova. A bateria de unidade em
`services/agr/tests/test_checkpointer.py` cobre as guardas e a leitura do
`config`, que sao Python; o que depende de a base avaliar — a ordem das
escritas, o `ON CONFLICT`, o que o papel ve e nao ve — so se mede aqui.

**A suite corre estas cadeias e nao copias delas**, que e a regra que o
`outbound/consultas.ts` escreveu e que o KAM-017 pagou duas vezes para
reaprender.
"""

from __future__ import annotations

import asyncio
import datetime as dt
import re
import unittest

import ligacao
from tests_agr.base import ComAgr, thread_id_de

from kamba_agr import retencao
from kamba_agr.checkpointer import CheckpointerDoAgr

#: O que o criterio 2 manda procurar: um numero angolano em qualquer forma.
TELEFONE = re.compile(r"\+?244\d{9}")

AGORA = dt.datetime(2026, 10, 25, 12, 0, tzinfo=dt.timezone.utc)


def checkpoint(ident: str, **canais: object) -> dict:
    return {
        "v": 1,
        "id": ident,
        "ts": AGORA.isoformat(),
        "channel_values": dict({"messages": []}, **canais),
        "channel_versions": {"messages": 1},
        "versions_seen": {},
        "updated_channels": None,
    }


def config(thread_id: str, checkpoint_id: str | None = None) -> dict:
    configuravel: dict = {"thread_id": thread_id, "checkpoint_ns": ""}
    if checkpoint_id is not None:
        configuravel["checkpoint_id"] = checkpoint_id
    return {"configurable": configuravel}


class ComCheckpointer(ComAgr):
    """Abre o papel `kamba_agr` e limpa o `lg` das *threads* que tocou."""

    def setUp(self) -> None:
        super().setUp()
        self._threads: list[str] = []
        self.saver = self.novo_saver()

    def novo_saver(self) -> CheckpointerDoAgr:
        """Um checkpointer numa ligacao **nova**.

        E assim que se simula um reinicio sem reiniciar nada: o criterio 1 pede
        que o estado sobreviva ao processo, e um saver novo numa tomada nova
        nao tem nada em memoria do anterior.
        """
        conexao = ligacao.ligar("agr")
        self.addCleanup(conexao.close)
        return CheckpointerDoAgr(conexao)

    def thread(self, conversa=None) -> str:
        conversa = conversa or self.criar_conversa()
        identificador = thread_id_de(conversa.tenant_id, conversa.contact_id)
        self._threads.append(identificador)
        self.addCleanup(self._apagar, identificador)
        return identificador

    def _apagar(self, thread_id: str) -> None:
        for tabela in ("checkpoint_writes", "checkpoints"):
            self.semente.execute(
                f"DELETE FROM lg.{tabela} WHERE thread_id = %s", (thread_id,)
            )


class TestVoltaDaBase(ComCheckpointer):
    def test_o_que_se_grava_volta_igual(self) -> None:
        thread = self.thread()
        gravado = checkpoint("cp-1", stage="cart", cart={"itens": 2})
        asyncio.run(self.saver.aput(config(thread), gravado, {"step": 3}, {}))

        lido = asyncio.run(self.saver.aget_tuple(config(thread)))
        assert lido is not None
        self.assertEqual(lido.checkpoint["id"], "cp-1")
        self.assertEqual(lido.checkpoint["channel_values"]["stage"], "cart")
        self.assertEqual(lido.metadata["step"], 3)

    def test_sobrevive_ao_reinicio_do_processo(self) -> None:
        # **O criterio 1.** `stage`, `cart` e `handoff` pelo nome, porque e o
        # que ele enumera. O saver novo nao partilha nada com o anterior.
        thread = self.thread()
        asyncio.run(
            self.saver.aput(
                config(thread),
                checkpoint("cp-1", stage="awaiting_confirm", cart={"total_minor": 1500},
                           handoff={"estado": "waiting"}),
                {},
                {},
            )
        )
        depois_do_reinicio = self.novo_saver()
        lido = asyncio.run(depois_do_reinicio.aget_tuple(config(thread)))
        assert lido is not None
        valores = lido.checkpoint["channel_values"]
        self.assertEqual(valores["stage"], "awaiting_confirm")
        self.assertEqual(valores["cart"], {"total_minor": 1500})
        self.assertEqual(valores["handoff"], {"estado": "waiting"})

    def test_sem_checkpoint_devolve_none(self) -> None:
        self.assertIsNone(asyncio.run(self.saver.aget_tuple(config(self.thread()))))

    def test_o_mais_recente_e_o_do_maior_checkpoint_id(self) -> None:
        # O `Checkpoint` do LangGraph di-lo: «unique and monotonically
        # increasing, so can be used for sorting». Gravam-se fora de ordem de
        # proposito — se a consulta ordenasse pelo `criado_at`, dois do mesmo
        # microssegundo empatavam e o desempate era a ordem do disco.
        thread = self.thread()
        for ident in ("cp-2", "cp-1", "cp-3"):
            asyncio.run(self.saver.aput(config(thread), checkpoint(ident), {}, {}))
        lido = asyncio.run(self.saver.aget_tuple(config(thread)))
        assert lido is not None
        self.assertEqual(lido.checkpoint["id"], "cp-3")

    def test_um_checkpoint_nomeado_le_esse_e_nao_o_ultimo(self) -> None:
        thread = self.thread()
        for ident in ("cp-1", "cp-2"):
            asyncio.run(self.saver.aput(config(thread), checkpoint(ident), {}, {}))
        lido = asyncio.run(self.saver.aget_tuple(config(thread, "cp-1")))
        assert lido is not None
        self.assertEqual(lido.checkpoint["id"], "cp-1")

    def test_o_pai_volta_no_parent_config(self) -> None:
        thread = self.thread()
        asyncio.run(self.saver.aput(config(thread), checkpoint("cp-1"), {}, {}))
        asyncio.run(
            self.saver.aput(config(thread, "cp-1"), checkpoint("cp-2"), {}, {})
        )
        lido = asyncio.run(self.saver.aget_tuple(config(thread, "cp-2")))
        assert lido is not None
        assert lido.parent_config is not None
        self.assertEqual(lido.parent_config["configurable"]["checkpoint_id"], "cp-1")
        # E o primeiro nao tem pai: um `parent_config` apontando para nada
        # mandava a viagem no tempo procurar um checkpoint que nunca existiu.
        primeiro = asyncio.run(self.saver.aget_tuple(config(thread, "cp-1")))
        assert primeiro is not None
        self.assertIsNone(primeiro.parent_config)


class TestEscritasPendentes(ComCheckpointer):
    def test_voltam_na_ordem_do_writes_sort_key(self) -> None:
        # `(task_path, task_id, idx)`. Gravam-se ao contrario: com um `ORDER BY`
        # pelo `task_id` so, ou sem ordem nenhuma, esta ordem saia do disco — e
        # a interface avisa que «an order-sensitive reducer rebuilds a different
        # value than the run produced».
        thread = self.thread()
        asyncio.run(self.saver.aput(config(thread), checkpoint("cp-1"), {}, {}))
        alvo = config(thread, "cp-1")
        # **O `task_path` e o `task_id` ordenam em sentidos opostos**, e e isso
        # que torna o ensaio capaz de ver a diferenca. Com os dois a ordenar
        # para o mesmo lado, tirar o `task_path` do `ORDER BY` dava o mesmo
        # resultado e a mutacao sobrevivia — foi o que aconteceu a primeira
        # versao deste ensaio, e a prova por mutacao apanhou-o.
        asyncio.run(self.saver.aput_writes(alvo, [("c", 3)], "tarefa-a", "caminho-z"))
        asyncio.run(self.saver.aput_writes(alvo, [("a", 1), ("b", 2)], "tarefa-b", "caminho-a"))

        lido = asyncio.run(self.saver.aget_tuple(alvo))
        assert lido is not None
        self.assertEqual(
            [(t, c) for t, c, _v in lido.pending_writes or []],
            # Por `caminho-a` primeiro, que e a `tarefa-b`. Por `task_id`
            # primeiro seria a `tarefa-a`, e e essa a diferenca.
            [("tarefa-b", "a"), ("tarefa-b", "b"), ("tarefa-a", "c")],
        )

    def test_repetir_a_mesma_escrita_nao_duplica(self) -> None:
        # **O criterio 5 visto da tabela.** Um turno que repete depois de uma
        # falha reescreve a mesma `(tarefa, idx)` em vez de criar outra linha:
        # e isso que faz a repeticao nao duplicar o efeito.
        thread = self.thread()
        asyncio.run(self.saver.aput(config(thread), checkpoint("cp-1"), {}, {}))
        alvo = config(thread, "cp-1")
        for _ in range(3):
            asyncio.run(self.saver.aput_writes(alvo, [("canal", 7)], "tarefa"))
        lido = asyncio.run(self.saver.aget_tuple(alvo))
        assert lido is not None
        self.assertEqual(len(lido.pending_writes or []), 1)
        self.assertEqual((lido.pending_writes or [])[0][2], 7)

    def test_regravar_o_mesmo_checkpoint_nao_duplica(self) -> None:
        thread = self.thread()
        for _ in range(2):
            asyncio.run(self.saver.aput(config(thread), checkpoint("cp-1"), {}, {}))
        self.semente.execute(
            "SELECT count(*) FROM lg.checkpoints WHERE thread_id = %s", (thread,)
        )
        self.assertEqual(self.semente.fetchone()[0], 1)


class TestJanelaContraABase(ComCheckpointer):
    def test_acima_da_janela_nao_chega_a_base(self) -> None:
        # A guarda tambem se mede aqui, e nao so na bateria de unidade: sem um
        # ensaio nesta *suite* uma mutacao no `>` do `_exigir_janela`
        # sobrevivia por desenho, porque todos os outros ensaios gravam
        # estados de zero ou uma mensagem.
        from kamba_agr.checkpointer import JANELA_MAXIMA, JanelaExcedidaError

        thread = self.thread()
        grande = checkpoint("cp-1", messages=[f"m{i}" for i in range(JANELA_MAXIMA + 1)])
        with self.assertRaises(JanelaExcedidaError):
            asyncio.run(self.saver.aput(config(thread), grande, {}, {}))
        self.semente.execute(
            "SELECT count(*) FROM lg.checkpoints WHERE thread_id = %s", (thread,)
        )
        self.assertEqual(self.semente.fetchone()[0], 0)

    def test_no_maximo_exacto_grava(self) -> None:
        from kamba_agr.checkpointer import JANELA_MAXIMA

        thread = self.thread()
        cheio = checkpoint("cp-1", messages=[f"m{i}" for i in range(JANELA_MAXIMA)])
        asyncio.run(self.saver.aput(config(thread), cheio, {}, {}))
        lido = asyncio.run(self.saver.aget_tuple(config(thread)))
        assert lido is not None
        self.assertEqual(len(lido.checkpoint["channel_values"]["messages"]), JANELA_MAXIMA)


class TestApagar(ComCheckpointer):
    def test_adelete_thread_leva_as_duas_tabelas(self) -> None:
        thread = self.thread()
        asyncio.run(self.saver.aput(config(thread), checkpoint("cp-1"), {}, {}))
        asyncio.run(
            self.saver.aput_writes(config(thread, "cp-1"), [("c", 1)], "tarefa")
        )
        asyncio.run(self.saver.adelete_thread(thread))
        for tabela in ("checkpoints", "checkpoint_writes"):
            with self.subTest(tabela=tabela):
                self.semente.execute(
                    f"SELECT count(*) FROM lg.{tabela} WHERE thread_id = %s", (thread,)
                )
                self.assertEqual(self.semente.fetchone()[0], 0)

    def test_nao_leva_as_outras_threads(self) -> None:
        a, b = self.thread(), self.thread()
        for thread in (a, b):
            asyncio.run(self.saver.aput(config(thread), checkpoint("cp-1"), {}, {}))
        asyncio.run(self.saver.adelete_thread(a))
        self.semente.execute(
            "SELECT count(*) FROM lg.checkpoints WHERE thread_id = %s", (b,)
        )
        self.assertEqual(self.semente.fetchone()[0], 1)


class TestRetencao(ComCheckpointer):
    """O criterio 8, primeira metade, com relogio simulado."""

    def _envelhecer(self, thread_id: str, dias: int) -> None:
        self.semente.execute(
            "UPDATE lg.checkpoints SET criado_at = %s WHERE thread_id = %s",
            (AGORA - dt.timedelta(days=dias), thread_id),
        )

    def test_apaga_a_parada_e_deixa_a_viva(self) -> None:
        parada, viva = self.thread(), self.thread()
        for thread in (parada, viva):
            asyncio.run(self.saver.aput(config(thread), checkpoint("cp-1"), {}, {}))
        self._envelhecer(parada, 31)
        self._envelhecer(viva, 29)

        lote = ligacao.ligar("batch")
        self.addCleanup(lote.close)
        apagadas = asyncio.run(retencao.varrer(self.saver, lote, AGORA))
        self.assertEqual(apagadas, [parada])

    def test_a_fronteira_e_pelo_valor(self) -> None:
        # Exactamente 30 dias **nao** apaga: o predicado e `<`, e uma *thread*
        # no dia do prazo ainda esta dentro dele.
        thread = self.thread()
        asyncio.run(self.saver.aput(config(thread), checkpoint("cp-1"), {}, {}))
        self._envelhecer(thread, 30)
        lote = ligacao.ligar("batch")
        self.addCleanup(lote.close)
        self.assertEqual(asyncio.run(retencao.varrer(self.saver, lote, AGORA)), [])

    def test_o_maximo_da_thread_manda_e_nao_cada_linha(self) -> None:
        # Uma *thread* com um checkpoint velho **e** um recente esta viva.
        # Apagar-lhe o velho era poda, e a poda nao se faz aqui.
        thread = self.thread()
        for ident in ("cp-1", "cp-2"):
            asyncio.run(self.saver.aput(config(thread), checkpoint(ident), {}, {}))
        self.semente.execute(
            "UPDATE lg.checkpoints SET criado_at = %s "
            "WHERE thread_id = %s AND checkpoint_id = 'cp-1'",
            (AGORA - dt.timedelta(days=200), thread),
        )
        lote = ligacao.ligar("batch")
        self.addCleanup(lote.close)
        self.assertEqual(asyncio.run(retencao.varrer(self.saver, lote, AGORA)), [])


class TestIsolamento(ComCheckpointer):
    """O X-02 do DoD, visto do `lg`."""

    def test_a_thread_de_a_nao_volta_no_pedido_de_b(self) -> None:
        # O isolamento aqui nao e RLS — estas tabelas nao tem `tenant_id`. E o
        # prefixo do `thread_id`, e e isso que este ensaio mede.
        a, b = self.thread(), self.thread()
        asyncio.run(self.saver.aput(config(a), checkpoint("cp-1", stage="cart"), {}, {}))
        self.assertIsNone(asyncio.run(self.saver.aget_tuple(config(b))))

    def test_o_papel_do_checkpointer_nao_ve_o_platform(self) -> None:
        # **O criterio 4.** Sem `USAGE` no esquema, nao chega as tabelas mesmo
        # que tivesse privilegio nelas — e nao tem.
        conexao = ligacao.ligar("agr")
        self.addCleanup(conexao.close)
        cursor = conexao.cursor()
        for tabela in ("tenants", "contacts", "conversations"):
            with self.subTest(tabela=tabela):
                self.assertErroSql(
                    "42501", cursor, f"SELECT 1 FROM platform.{tabela} LIMIT 1", ()
                )

    def test_o_papel_nao_alcanca_mais_bases_do_que_o_kamba_app(self) -> None:
        # A outra metade do criterio 4: «sem acesso a `platform` **nem a
        # `medusa`**». O Medusa e uma **base** separada (`kamba_medusa`), nao
        # um esquema, pelo que o mecanismo nao e o `USAGE` — e o `CONNECT`.
        #
        # **A primeira versao deste ensaio exigia o conjunto vazio e falhou,
        # a dizer uma verdade:** o `kamba_agr` liga-se a base `postgres`,
        # porque o PostgreSQL da `CONNECT` ao `PUBLIC` em todas as bases por
        # omissao. Isso vale para os **sete** papeis e e anterior a este
        # ticket; exigir o vazio aqui era este bloco a pagar uma conta que nao
        # e dele. Fica em `docs/dividas-documentais.md`.
        #
        # O que **e** deste ticket e que o papel novo nao alcance mais do que o
        # que ja existia. E isso que se mede.
        def bases(papel: str) -> set[str]:
            self.semente.execute(
                "SELECT datname FROM pg_database "
                " WHERE NOT datistemplate "
                "   AND has_database_privilege(%s, datname, 'CONNECT')",
                (papel,),
            )
            return {linha[0] for linha in self.semente.fetchall()}

        self.assertEqual(bases("kamba_agr"), bases("kamba_app"))

    def test_o_papel_do_checkpointer_nao_cria_nada_no_lg(self) -> None:
        # Tem os quatro de dados e nao o DDL: um checkpointer que pudesse criar
        # tabelas no seu esquema podia tambem apagar as que la estao.
        conexao = ligacao.ligar("agr")
        self.addCleanup(conexao.close)
        self.assertErroSql(
            "42501", conexao.cursor(), "CREATE TABLE lg.nao_devia (x int)", ()
        )


class TestPrivacidade(ComCheckpointer):
    """O criterio 2, e a armadilha que ele tem."""

    def test_o_varrimento_desserializa_em_vez_de_procurar_texto(self) -> None:
        # **A armadilha.** O estado vai em `msgpack` para uma coluna `bytea`.
        # Uma busca por texto sobre a coluna passa vazia **mesmo com um
        # telefone la dentro** — o criterio satisfeito pela razao errada. Este
        # ensaio prova que o varrimento ve o que la esta: semeia um numero de
        # proposito e exige que o varrimento o encontre.
        thread = self.thread()
        asyncio.run(
            self.saver.aput(
                config(thread),
                checkpoint("cp-1", messages=["ligue para +244923456789"]),
                {},
                {},
            )
        )
        self.assertEqual(self._numeros_em(thread), ["+244923456789"])

    def test_o_estado_de_um_turno_normal_nao_leva_numeros(self) -> None:
        # O criterio, agora que o varrimento esta provado a encontrar.
        thread = self.thread()
        asyncio.run(
            self.saver.aput(
                config(thread),
                checkpoint("cp-1", stage="cart", messages=["quero dois sabao"]),
                {"step": 1},
                {},
            )
        )
        self.assertEqual(self._numeros_em(thread), [])

    def _numeros_em(self, thread_id: str) -> list[str]:
        """Desserializa tudo o que a *thread* tem no `lg` e procura numeros."""
        achados: list[str] = []
        self.semente.execute(
            "SELECT type, checkpoint, metadata_type, metadata FROM lg.checkpoints "
            "WHERE thread_id = %s",
            (thread_id,),
        )
        for tipo, octetos, tipo_meta, octetos_meta in self.semente.fetchall():
            for par in ((tipo, bytes(octetos)), (tipo_meta, bytes(octetos_meta))):
                achados += TELEFONE.findall(repr(self.saver.serde.loads_typed(par)))
        self.semente.execute(
            "SELECT type, blob FROM lg.checkpoint_writes WHERE thread_id = %s",
            (thread_id,),
        )
        for tipo, octetos in self.semente.fetchall():
            achados += TELEFONE.findall(
                repr(self.saver.serde.loads_typed((tipo, bytes(octetos))))
            )
        return achados


class TestHistorico(ComCheckpointer):
    def test_alist_volta_do_mais_recente_para_o_mais_antigo(self) -> None:
        thread = self.thread()
        for ident in ("cp-1", "cp-2", "cp-3"):
            asyncio.run(self.saver.aput(config(thread), checkpoint(ident), {}, {}))

        async def listar(**kwargs):
            return [t.checkpoint["id"] async for t in self.saver.alist(config(thread), **kwargs)]

        self.assertEqual(asyncio.run(listar()), ["cp-3", "cp-2", "cp-1"])

    def test_o_before_corta_no_checkpoint_dado(self) -> None:
        thread = self.thread()
        for ident in ("cp-1", "cp-2", "cp-3"):
            asyncio.run(self.saver.aput(config(thread), checkpoint(ident), {}, {}))

        async def listar():
            return [
                t.checkpoint["id"]
                async for t in self.saver.alist(
                    config(thread), before=config(thread, "cp-3")
                )
            ]

        self.assertEqual(asyncio.run(listar()), ["cp-2", "cp-1"])


if __name__ == "__main__":
    unittest.main()
