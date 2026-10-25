"""O checkpointer, na parte que **nao** e SQL (KAM-026).

## Porque e que nao ha aqui um `aput` seguido de um `aget_tuple`

Porque isso prova o SQL, e o SQL nao se prova contra um duplo. Um espiao que
guardasse as linhas e as devolvesse interpretava as cadeias de `consultas.py`
em Python — e e exactamente a armadilha que o `coexistencia.base_falsa.ts`
pagou duas vezes no KAM-017: a mutacao muda a cadeia, o duplo reconhece-a pela
constante importada, e o teste continua verde com o predicado apagado.

O que esta aqui sao as guardas e a leitura do `config`, que sao Python e nao
tem base de dados nenhuma. O resto esta em `db/tests_agr/test_checkpointer.py`,
que corre contra um PostgreSQL de verdade no *gate* 8.

O duplo abaixo **regista** o que recebeu e nao o interpreta: nao ha nele um
`if` sobre o texto do SQL.
"""

from __future__ import annotations

import asyncio
import time
import unittest

from kamba_agr.checkpointer import (
    JANELA_MAXIMA,
    CheckpointerDoAgr,
    JanelaExcedidaError,
    _coordenadas,
)

TENANT = "11111111-1111-4111-8111-111111111111"
CONTACTO = "22222222-2222-4222-8222-222222222222"
THREAD = f"{TENANT}:{CONTACTO}"


def config(thread_id: str | None = THREAD, **extra: object) -> dict:
    configuravel: dict = {}
    if thread_id is not None:
        configuravel["thread_id"] = thread_id
    configuravel.update(extra)
    return {"configurable": configuravel}


def checkpoint(mensagens: int = 0, ident: str = "cp-1") -> dict:
    return {
        "v": 1,
        "id": ident,
        "ts": "2026-10-25T00:00:00+00:00",
        "channel_values": {"messages": list(range(mensagens))},
        "channel_versions": {},
        "versions_seen": {},
        "updated_channels": None,
    }


class LigacaoEspia:
    """Regista `(sql, parametros)` e devolve o que lhe mandarem devolver.

    Nao le o SQL: devolve `self.respostas.pop(0)` pela ordem das chamadas. Um
    duplo que escolhesse a resposta pelo texto da cadeia era uma base falsa, e
    esta casa ja mediu o que isso esconde.
    """

    def __init__(self, respostas: list[list[list]] | None = None) -> None:
        self.chamadas: list[tuple[str, tuple]] = []
        self.respostas = list(respostas or [])
        self.commits = 0
        self.fechada = False

    def cursor(self) -> "LigacaoEspia":
        return self

    #: Quanto a espia demora em cada instrucao, em segundos. Zero por omissao;
    #: o ensaio da latencia poe um valor para que a medida tenha o que medir —
    #: `assertGreaterEqual(..., 0)` sobre uma diferenca de `monotonic` e sempre
    #: verdade, e uma mutacao que devolvesse `0` sobrevivia.
    demora: float = 0.0

    def execute(self, sql: str, parametros: tuple) -> None:
        if self.demora:
            time.sleep(self.demora)
        self.chamadas.append((sql, parametros))

    def fetchall(self) -> list[list]:
        return self.respostas.pop(0) if self.respostas else []

    @property
    def description(self) -> object:
        return [("coluna",)] if self.respostas else None

    def close(self) -> None:
        pass

    def commit(self) -> None:
        self.commits += 1


class TestCoordenadas(unittest.TestCase):
    def test_sem_thread_id_levanta(self) -> None:
        # O proprio `BaseCheckpointSaver` di-lo: «Without it, the checkpointer
        # cannot save state». Aceitar a ausencia gravava o estado de uma
        # conversa debaixo do de outra.
        for mau in (None, {}, {"configurable": {}}, {"configurable": {"thread_id": ""}}):
            with self.subTest(mau=mau), self.assertRaises(ValueError):
                _coordenadas(mau)

    def test_um_thread_id_que_nao_e_cadeia_levanta(self) -> None:
        with self.assertRaises(ValueError):
            _coordenadas({"configurable": {"thread_id": 7}})

    def test_o_namespace_por_omissao_e_a_cadeia_vazia(self) -> None:
        # O LangGraph passa cadeia vazia no grafo de topo, e a coluna tem
        # `DEFAULT ''` por isso. Um `None` aqui entrava na chave primaria.
        self.assertEqual(_coordenadas(config())[1], "")
        self.assertEqual(_coordenadas(config(checkpoint_ns=None))[1], "")

    def test_um_thread_id_fora_da_forma_levanta(self) -> None:
        # O dominio e `<uuid>:<uuid>` (dicionario §3.1). A revisao `0020`
        # declinou o `CHECK` na coluna dizendo que a forma se impoe a entrada —
        # e impoe, para quem entra pelo `contexto.py`. O `compile(...)` do
        # KAM-027 e o `ingest` do KAM-031 constroem o `config` eles proprios.
        maus = (
            "sem-dois-pontos",
            "nao-e-uuid:nao-e-uuid",
            f"{TENANT}:{CONTACTO}:a-mais",
            # Maiusculas: o `UUID` que o PostgreSQL devolve e minusculo, e
            # aceitar as duas formas dava duas *threads* para a mesma conversa.
            # O `TENANT` deste ficheiro e so digitos, pelo que `.upper()` nao
            # lhe mexe — e preciso um com letras.
            "AAAAAAAA-1111-4111-8111-111111111111:" + CONTACTO,
            f" {TENANT}:{CONTACTO}",
        )
        for mau in maus:
            with self.subTest(mau=mau), self.assertRaises(ValueError):
                _coordenadas(config(mau))

    def test_a_forma_boa_passa(self) -> None:
        self.assertEqual(_coordenadas(config())[0], THREAD)

    def test_o_checkpoint_id_e_opcional(self) -> None:
        self.assertIsNone(_coordenadas(config())[2])
        self.assertEqual(_coordenadas(config(checkpoint_id="cp-9"))[2], "cp-9")


class TestJanela(unittest.TestCase):
    def test_no_maximo_exacto_grava(self) -> None:
        saver = CheckpointerDoAgr(LigacaoEspia())
        asyncio.run(saver.aput(config(), checkpoint(JANELA_MAXIMA), {}, {}))

    def test_acima_do_maximo_levanta(self) -> None:
        # Levanta em vez de recortar: recortar aqui punha o estado em memoria do
        # grafo a divergir do que esta na base, sem erro nenhum. Quem recorta e
        # o `ingest` (KAM-031), com o `estado.recortar_janela`.
        saver = CheckpointerDoAgr(LigacaoEspia())
        with self.assertRaises(JanelaExcedidaError):
            asyncio.run(saver.aput(config(), checkpoint(JANELA_MAXIMA + 1), {}, {}))

    def test_a_guarda_corre_antes_de_tocar_na_base(self) -> None:
        # Senao ficava um checkpoint meio escrito por uma janela que nao cabia.
        ligacao = LigacaoEspia()
        saver = CheckpointerDoAgr(ligacao)
        with self.assertRaises(JanelaExcedidaError):
            asyncio.run(saver.aput(config(), checkpoint(JANELA_MAXIMA + 1), {}, {}))
        self.assertEqual(ligacao.chamadas, [])


class TestEscrita(unittest.TestCase):
    def test_aput_devolve_o_config_do_checkpoint_novo(self) -> None:
        saver = CheckpointerDoAgr(LigacaoEspia())
        devolvido = asyncio.run(saver.aput(config(), checkpoint(ident="cp-7"), {}, {}))
        self.assertEqual(
            devolvido["configurable"],
            {"thread_id": THREAD, "checkpoint_ns": "", "checkpoint_id": "cp-7"},
        )

    def test_o_checkpoint_do_config_de_entrada_e_o_pai(self) -> None:
        # A cadeia de `parent_checkpoint_id` e o que o `parent_config` devolve:
        # trocar isto partia a viagem no tempo sem dar erro.
        ligacao = LigacaoEspia()
        saver = CheckpointerDoAgr(ligacao)
        asyncio.run(
            saver.aput(config(checkpoint_id="cp-6"), checkpoint(ident="cp-7"), {}, {})
        )
        _sql, parametros = ligacao.chamadas[0]
        self.assertEqual(parametros[2], "cp-7")
        self.assertEqual(parametros[3], "cp-6")

    def test_o_tipo_do_checkpoint_e_o_dos_metadados_sao_gravados_a_parte(self) -> None:
        # Duas colunas e nao uma: os dois objectos passam pelo mesmo
        # serializador mas o tipo que ele devolve para um nao e garantidamente
        # o do outro.
        ligacao = LigacaoEspia()
        saver = CheckpointerDoAgr(ligacao)
        asyncio.run(saver.aput(config(), checkpoint(), {"step": 1}, {}))
        _sql, parametros = ligacao.chamadas[0]
        self.assertEqual(len(parametros), 8)
        self.assertIsInstance(parametros[4], str)   # type do checkpoint
        self.assertIsInstance(parametros[5], bytes)
        self.assertIsInstance(parametros[6], str)   # metadata_type
        self.assertIsInstance(parametros[7], bytes)

    def test_aput_writes_sem_checkpoint_id_levanta(self) -> None:
        saver = CheckpointerDoAgr(LigacaoEspia())
        with self.assertRaises(ValueError):
            asyncio.run(saver.aput_writes(config(), [("canal", 1)], "tarefa"))

    def test_aput_writes_numera_as_escritas_pela_ordem(self) -> None:
        # O `idx` entra no `writes_sort_key` da interface, e e a ordem em que a
        # execucao as produziu. Numerar por outra coisa reconstruia outro valor
        # num redutor sensivel a ordem.
        ligacao = LigacaoEspia()
        saver = CheckpointerDoAgr(ligacao)
        asyncio.run(
            saver.aput_writes(
                config(checkpoint_id="cp-1"),
                [("a", 1), ("b", 2), ("c", 3)],
                "tarefa",
                "caminho",
            )
        )
        self.assertEqual([p[5] for _s, p in ligacao.chamadas], [0, 1, 2])
        self.assertEqual([p[6] for _s, p in ligacao.chamadas], ["a", "b", "c"])
        self.assertEqual({p[4] for _s, p in ligacao.chamadas}, {"caminho"})


class TestListagem(unittest.IsolatedAsyncioTestCase):
    async def test_um_filtro_de_metadados_levanta(self) -> None:
        # Ignorar o filtro devolvia o historico inteiro a quem pediu um pedaco:
        # a resposta errada sem erro, que e pior do que a excepcao.
        saver = CheckpointerDoAgr(LigacaoEspia())
        with self.assertRaises(NotImplementedError):
            async for _ in saver.alist(config(), filter={"step": 1}):
                pass

    async def test_sem_config_levanta_nao_implementado(self) -> None:
        # O contrato admite `config=None` (listar todas as *threads*). Nao se
        # implementa, e levanta a dizer isso em vez de se disfarcar de erro de
        # argumento. Achado da revisao adversarial.
        saver = CheckpointerDoAgr(LigacaoEspia())
        with self.assertRaises(NotImplementedError):
            async for _ in saver.alist(None):
                pass

    async def test_o_before_pode_nao_trazer_thread_id(self) -> None:
        # A biblioteca passa `{"configurable": {"checkpoint_id": ...}}`. A
        # primeira versao lia-o pelo `_coordenadas`, que **exige** `thread_id`,
        # e levantava num `before` legitimo.
        saver = CheckpointerDoAgr(LigacaoEspia())
        antes = {"configurable": {"checkpoint_id": "cp-3"}}
        self.assertEqual([t async for t in saver.alist(config(), before=antes)], [])

    async def test_sem_limite_nao_corta_em_cem(self) -> None:
        # `limit=None` e «sem maximo»; vai como `LIMIT NULL`, que em Postgres e
        # sem limite. A primeira versao punha 100 em silencio.
        ligacao = LigacaoEspia()
        saver = CheckpointerDoAgr(ligacao)
        [t async for t in saver.alist(config())]
        _sql, parametros = ligacao.chamadas[0]
        self.assertIsNone(parametros[-1])

    async def test_sem_filtro_nao_levanta(self) -> None:
        saver = CheckpointerDoAgr(LigacaoEspia())
        self.assertEqual([t async for t in saver.alist(config(), filter={})], [])


class TestOQueNaoSeImplementa(unittest.IsolatedAsyncioTestCase):
    """Os metodos que a interface deixa a levantar, e porque isso e certo."""

    async def test_a_poda_levanta_em_vez_de_cortar_a_cadeia(self) -> None:
        # O `prune` da propria interface avisa que um `keep_latest` ingenuo
        # corta a cadeia de um canal `DeltaChannel` e que o valor «would
        # silently reconstruct as empty (no error raised)». Nao ha grafo nenhum
        # ainda; quem decide se algum usa canais delta e o KAM-031.
        saver = CheckpointerDoAgr(LigacaoEspia())
        with self.assertRaises(NotImplementedError):
            await saver.aprune([THREAD])

    async def test_a_copia_de_thread_levanta(self) -> None:
        # A fusao de contactos migra o *thread* (`docs/tecnica/02` §12), e quem
        # funde contactos e outro processo. Nenhum criterio deste bloco o pede.
        saver = CheckpointerDoAgr(LigacaoEspia())
        with self.assertRaises(NotImplementedError):
            await saver.acopy_thread(THREAD, "outro")

    def test_os_metodos_sincronos_levantam(self) -> None:
        # O AGR so chama os assincronos. Um grafo sincrono levanta, e levanta a
        # dizer o que falta.
        saver = CheckpointerDoAgr(LigacaoEspia())
        with self.assertRaises(NotImplementedError):
            saver.get_tuple(config())


class TestVersoes(unittest.TestCase):
    def test_as_versoes_de_canal_sao_inteiras(self) -> None:
        # `BaseCheckpointSaver[int]` e nao `[str]`: a implementacao por omissao
        # do `get_next_version` incrementa inteiros e **levanta** com cadeias.
        # Em inteiros nao se sobrepoe nada.
        saver = CheckpointerDoAgr(LigacaoEspia())
        self.assertEqual(saver.get_next_version(None, None), 1)
        self.assertEqual(saver.get_next_version(4, None), 5)


class TestMedidas(unittest.TestCase):
    """As duas medidas do DoD: latencia da gravacao e tamanho do estado."""

    def test_aput_mede_a_latencia_e_o_tamanho(self) -> None:
        from kamba_agr.metricas import (
            METRICA_LATENCIA_CHECKPOINT,
            METRICA_TAMANHO_DO_ESTADO,
            MetricasDoAgr,
        )

        medidor = MetricasDoAgr()
        ligacao = LigacaoEspia()
        ligacao.demora = 0.02
        saver = CheckpointerDoAgr(ligacao, metricas=medidor)
        asyncio.run(saver.aput(config(), checkpoint(3), {"step": 1}, {}))
        lido = medidor.ler()
        self.assertGreater(lido[METRICA_TAMANHO_DO_ESTADO], 0)
        # **Pelo menos a demora da escrita**, e nao `>= 0`: uma diferenca de
        # `monotonic` e sempre nao-negativa, pelo que a assercao antiga passava
        # com a medida substituida por zero.
        self.assertGreaterEqual(lido[METRICA_LATENCIA_CHECKPOINT], 20)

    def test_sem_metricas_nao_levanta(self) -> None:
        # O parametro e opcional: as baterias que nao medem nao montam duplo.
        saver = CheckpointerDoAgr(LigacaoEspia())
        asyncio.run(saver.aput(config(), checkpoint(), {}, {}))

    def test_um_tenant_id_nao_entra_como_etiqueta(self) -> None:
        # O `OBS-I`. A versao anterior deste ensaio chamava `medir` com tres
        # argumentos e esperava `TypeError` — o que prova que uma funcao de
        # dois parametros recusa tres, e passaria com qualquer funcao do
        # interpretador. Quem faz cumprir o `OBS-I` e o `_validar`/`ETIQUETA`
        # do `metricas.py`, e e esse que se exercita. Achado da revisao
        # adversarial.
        from kamba_agr.metricas import (
            METRICA_TURNOS,
            EtiquetaInvalida,
            MetricasDoAgr,
        )

        medidor = MetricasDoAgr()
        with self.assertRaises(EtiquetaInvalida):
            medidor.contar(METRICA_TURNOS, "11111111-1111-4111-8111-111111111111")

    def test_as_duas_medidas_do_checkpointer_nao_tem_etiqueta(self) -> None:
        # E a outra metade: as duas sao **medidas** e nao contadores, e o
        # `medir` nao tem por onde receber uma etiqueta. Afirma-se pela
        # declaracao, nao pela aridade da funcao.
        from kamba_agr import metricas as m

        for nome in (m.METRICA_LATENCIA_CHECKPOINT, m.METRICA_TAMANHO_DO_ESTADO):
            with self.subTest(nome=nome):
                self.assertIn(nome, m._MEDIDAS)
                self.assertNotIn(nome, m._VALORES_DA_ETIQUETA)


class TestEncerramento(unittest.TestCase):
    def test_fechar_larga_a_ligacao(self) -> None:
        class Tomada(LigacaoEspia):
            def close(self) -> None:
                self.fechada = True

        tomada = Tomada()
        CheckpointerDoAgr(tomada).fechar()
        self.assertTrue(tomada.fechada)


if __name__ == "__main__":
    unittest.main()
