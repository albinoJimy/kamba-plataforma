"""A porta `grafos` do processo (KAM-186): ligada, e cada ligacao com o seu vermelho.

O defeito que este ticket fecha nao vivia numa funcao: vivia na **ligacao**. O
`__main__` passava `grafos=sem_grafos` ao `ExecutorDeTurnos`, e todas as funcoes
envolvidas estavam certas e testadas. Por isso a primeira bateria aqui corre o
`main()` real e le o que ele passou a cada porta — e e ela que a mutacao
`grafos: o __main__ volta a passar o sem_grafos` tem de pôr vermelha.

As outras medem as duas direccoes de cada porta (criterios 2 a 8): ligada, o
comportamento; na omissao, o vermelho.

**Sem `IsolatedAsyncioTestCase`**, pela medicao do KAM-114: cada invocacao do
LangGraph cria dezenas de tarefas e aquela classe custa 47 vezes mais. Cada
ensaio corre o seu `asyncio.run`.
"""

from __future__ import annotations

import asyncio
import json
import os
import unittest
from pathlib import Path
from types import SimpleNamespace
from typing import Any
from unittest import mock

from apoio import CREDENCIAL, TrancaFalsa, como_json, invocacao_crua, pedir
from kamba_agr import __main__ as arranque
from kamba_agr import grafos as grafos_mod
from kamba_agr import registo
from kamba_agr.admissao import Admissao, Tectos
from kamba_agr.api_interna import CABECALHO, rotas
from kamba_agr.app import create_app
from kamba_agr.concierge.politica import PoliticaDeConcierge, SemPolitica
from kamba_agr.concierge.rascunho import ServicoDeRascunho
from kamba_agr.contexto import ler_invocacao
from kamba_agr.degradacao import DetectorDeDegradacao, SemDegradacao
from kamba_agr.estado import estado_inicial
from kamba_agr.handoff.servico import ServicoDeHandoff
from kamba_agr.metricas import DESFECHOS, METRICA_REGISTO_NEGADO, MetricasDoAgr
from kamba_agr.tls.camada import ToolLayer
from kamba_agr.tls import idx as tls_idx
from kamba_agr.tls.catalogo import catalogo_do_piloto
from kamba_agr.turno import (
    DESFECHO_SERVICO_INDISPONIVEL,
    ExecutorDeTurnos,
    Palavra,
    SaidaPorLigarError,
    sem_grafos,
)
from kamba_agr.verticais.vendedor import nos as nos_vendedor
from langgraph.checkpoint.base import empty_checkpoint
from langgraph.checkpoint.memory import InMemorySaver
from test_arranque import AMBIENTE_BASE, TestArranque
from test_vendedor import Saida, montar

RAIZ = Path(__file__).resolve().parents[3]
PASTA = RAIZ / "registry"


class _Entitlement(SimpleNamespace):
    pass


def _leitor(permitidos: set[str]):
    """Um leitor de entitlements de ensaio: `(tenant, modulo) -> permitido?`."""

    def ler(_tenant_id: str, modulo: str) -> _Entitlement:
        return _Entitlement(permitido=modulo in permitidos)

    return ler


def _agentes(permitidos: set[str], metricas: Any = None) -> registo.AgentRegistry:
    agentes = registo.AgentRegistry(_leitor(permitidos), metricas=metricas)
    agentes.load_all(
        registo.AmbienteDoRegisto.do_repositorio(
            RAIZ,
            {"KAMBA_FASE": "piloto"},
            catalogo=catalogo_do_piloto(),
            construir_grafo=grafos_mod.para_validar,
        ),
        PASTA,
    )
    return agentes


async def _nunca_bloqueado(_invocacao) -> bool:
    return False


async def _sempre_bloqueado(_invocacao) -> bool:
    return True


#: O backend de ensaio das ultimas portas montadas, para contar chamadas a tools.
_ULTIMO_BACKEND: list[Any] = [None]


def _portas_de_ensaio(**trocar: Any) -> tuple[dict[str, Any], Saida]:
    """As portas do processo, com os duplos das baterias do KAM-031."""
    _, deps, backend, saida, _ = montar()
    _ULTIMO_BACKEND[0] = backend
    portas: dict[str, Any] = {
        "tools": deps.tools,
        "saida": saida,
        "admitir": grafos_mod.admitir,
        "checkpointer": InMemorySaver(),
        "relogio": deps.relogio,
    }
    portas.update(trocar)
    return portas, saida


def _porta(
    permitidos: set[str] = frozenset({"vendedor", "servicos"}),
    bloqueado=_nunca_bloqueado,
    metricas: Any = None,
    **trocar: Any,
) -> tuple[grafos_mod.PortaDeGrafos, dict[str, Any], Saida]:
    agentes = _agentes(set(permitidos), metricas)
    portas, saida = _portas_de_ensaio(**trocar)
    compilados = grafos_mod.compilar(dict(agentes.verticais), portas)
    porta = grafos_mod.PortaDeGrafos(
        registo=agentes,
        grafos=compilados,
        checkpointer=portas["checkpointer"],
        contacto_bloqueado=bloqueado,
    )
    return porta, compilados, saida


def _nos_do_alvo(vertical: str) -> set[str]:
    """Os nos do grafo de uma vertical, compilado **daqui** e nao pelo `compilar`."""
    import importlib

    from kamba_agr.verticais.vendedor.nos import Dependencias

    modulo = importlib.import_module(f"kamba_agr.verticais.{vertical}")
    deps = Dependencias(tools=None, saida=grafos_mod.SaidaPorLigar())
    return set(modulo.build_graph(deps).nodes)


def _invocacao(**sobrepor: Any):
    return ler_invocacao(invocacao_crua(**sobrepor))


def _estado_com_texto(invocacao, texto: str) -> dict[str, Any]:
    estado = estado_inicial(invocacao)
    estado["messages"] = [{"role": "user", "content": texto}]
    return estado


def _config(invocacao) -> dict[str, Any]:
    return {"configurable": {"thread_id": invocacao.thread_id}}


# ------------------------------------------------------------- a ligacao


class TestLigacaoDoArranque(unittest.TestCase):
    """O `main()` real, com o `uvicorn.run` substituido: o que cada porta recebeu.

    E o ensaio que fica vermelho se o `__main__` voltar a passar o `sem_grafos`
    a qualquer das tres portas — que e o defeito do KAM-186, e nenhum ensaio de
    funcao o via.
    """

    def setUp(self) -> None:
        self._arranque = TestArranque("test_arranca_pelo_logger_e_cala_o_registo_proprio_do_uvicorn")
        self._arranque.setUp()
        self.addCleanup(self._arranque.doCleanups)
        self.capturado: dict[str, Any] = {}
        reais = {
            nome: getattr(arranque, nome)
            for nome in (
                "ExecutorDeTurnos",
                "Retomador",
                "Decisor",
                "compilar",
                "_fechar_as_tomadas",
            )
        }

        def espiar(nome: str):
            def construir(*args: Any, **kwargs: Any) -> Any:
                objecto = reais[nome](*args, **kwargs)
                self.capturado[nome] = (args, kwargs, objecto)
                return objecto

            return construir

        # **O leitor de entitlements e o contacto sao duplos que o ensaio
        # controla, e nao duplos que respondem sempre o mesmo.** A primeira
        # versao desta bateria punha os dois a admitir tudo, e a revisao
        # adversarial mediu o efeito: trocar no `__main__` o leitor do registo
        # por um `permitido=True` fixo, ou o contacto por um «nunca bloqueado»,
        # sobrevivia — a ligacao nao era medida, so a existencia do objecto.
        self.permitidos = {"vendedor", "servicos"}
        self.bloqueado = False
        self.contacto_ligado_a: list[Any] = []
        teste = self

        class _Leitor:
            def __init__(self, _abrir: Any) -> None:
                pass

            @staticmethod
            def ler(_tenant_id: str, modulo: str) -> _Entitlement:
                return _Entitlement(permitido=modulo in teste.permitidos)

        def _leitor_de_contacto(abrir: Any):
            teste.contacto_ligado_a.append(abrir)

            async def bloqueado(_invocacao) -> bool:
                return teste.bloqueado

            return bloqueado

        self.saver = InMemorySaver()
        remendos = [
            mock.patch.object(arranque, nome, espiar(nome)) for nome in reais
        ] + [
            mock.patch.object(arranque.evt, "LeitorDeEntitlements", _Leitor),
            mock.patch.object(arranque, "CheckpointerDoAgr", lambda *_a, **_k: self.saver),
            mock.patch.object(arranque, "leitor_de_contacto", _leitor_de_contacto),
        ]
        for remendo in remendos:
            remendo.start()
            self.addCleanup(remendo.stop)
        ambiente = dict(AMBIENTE_BASE, KAMBA_FASE="piloto", KAMBA_REGISTRY_DIR=str(PASTA))
        self.codigo, _ = self._arranque._correr(ambiente)

    def _porta_do_turno(self):
        return self.capturado["ExecutorDeTurnos"][1]["grafos"]

    def test_o_arranque_passa(self) -> None:
        self.assertEqual(self.codigo, 0, self._arranque.saida.getvalue())

    def test_a_porta_do_turno_resolve_cada_vertical_no_seu_grafo(self) -> None:
        compilados = self.capturado["compilar"][2]
        porta = self._porta_do_turno()
        self.assertIsNot(porta, sem_grafos)
        for vertical in ("vendedor", "servicos"):
            with self.subTest(vertical=vertical):
                grafo = asyncio.run(porta(_invocacao(vertical=vertical)))
                self.assertIs(grafo._grafo, compilados[vertical])
                # **Pelo conteudo, e nao so pela chave**: a identidade contra
                # o que o `compilar` devolveu passava com o `compilar` a
                # construir o grafo do Vendedor para as duas (achado 1 da
                # revisao adversarial). Os nos vem do alvo importado aqui.
                self.assertEqual(set(grafo._grafo.nodes), _nos_do_alvo(vertical))

    def test_o_entitlement_do_turno_e_o_do_registo_do_processo(self) -> None:
        """Criterio 3 pelo `main()`: sem o modulo, a porta recusa."""
        porta = self._porta_do_turno()
        self.permitidos = {"servicos"}
        with self.assertRaises(grafos_mod.VerticalRecusadaError) as capturado:
            asyncio.run(porta(_invocacao(vertical="vendedor")))
        self.assertEqual(capturado.exception.motivo, "sem_entitlement")
        asyncio.run(porta(_invocacao(vertical="servicos")))

    def test_a_politica_de_concierge_le_o_leitor_do_processo(self) -> None:
        portas = self.capturado["compilar"][0][1]
        tenant = _invocacao().tenant_id
        self.assertFalse(portas["concierge"].activa(tenant))
        self.permitidos = {"vendedor", "servicos", "concierge"}
        self.assertTrue(portas["concierge"].activa(tenant))

    def test_a_politica_chega_ao_turno_lida_antes_dele(self) -> None:
        """A `PoliticaDoTurno` da porta e a do `Dependencias` sao a mesma."""
        portas = self.capturado["compilar"][0][1]
        porta = self._porta_do_turno().__self__
        self.assertIs(porta._politica, portas["concierge"])
        self.permitidos = {"vendedor", "servicos", "concierge"}
        grafo = asyncio.run(porta.do_turno(_invocacao()))
        self.assertTrue(grafo._concierge[1])

    def test_o_contacto_le_se_pela_ligacao_de_leitura_e_decide_a_admissao(self) -> None:
        self.assertEqual(self.contacto_ligado_a, [arranque.ligar_para_leitura])
        porta = self._porta_do_turno()
        self.bloqueado = True
        grafo = asyncio.run(porta(_invocacao()))
        self.assertEqual(grafo._admissao, grafos_mod.CONTACTO_BLOQUEADO)

    def test_as_duas_portas_por_thread_sao_a_mesma_resolucao_e_nao_a_do_turno(self) -> None:
        do_turno = self._porta_do_turno()
        for nome in ("Retomador", "Decisor"):
            with self.subTest(porta=nome):
                da_thread = self.capturado[nome][1]["grafos"]
                self.assertEqual(da_thread.__func__, grafos_mod.PortaDeGrafos.da_thread)
                self.assertIs(da_thread.__self__, do_turno.__self__)

    def test_a_porta_por_thread_le_a_vertical_do_checkpoint(self) -> None:
        compilados = self.capturado["compilar"][2]
        da_thread = self.capturado["Retomador"][1]["grafos"]
        invocacao = _invocacao(vertical="servicos")
        # O *checkpoint* grava os canais por versao: sem `channel_versions` e
        # `new_versions`, o `channel_values` nao se guarda e a leitura ve-o vazio.
        ponto = empty_checkpoint()
        ponto["channel_values"] = {"vertical": "servicos"}
        ponto["channel_versions"] = {"vertical": 1}
        asyncio.run(
            self.saver.aput(
                {"configurable": {"thread_id": invocacao.thread_id, "checkpoint_ns": ""}},
                ponto,
                {},
                {"vertical": 1},
            )
        )
        self.assertIs(asyncio.run(da_thread(invocacao.thread_id)), compilados["servicos"])

    def test_cada_porta_do_dependencias_sai_da_omissao(self) -> None:
        """Criterio 5: porta a porta, o objecto real e nao o que nao faz nada."""
        portas = self.capturado["compilar"][0][1]
        self.assertIsInstance(portas["concierge"], grafos_mod.PoliticaDoTurno)
        self.assertIsInstance(portas["concierge"].politica, PoliticaDeConcierge)
        self.assertNotIsInstance(portas["concierge"].politica, SemPolitica)
        self.assertIsInstance(portas["degradacao"], DetectorDeDegradacao)
        self.assertNotIsInstance(portas["degradacao"], SemDegradacao)
        # KAM-061: o limiar do `retrieve` e o do pontuador real. Na omissao (o
        # `LIMIAR_IDX` do duplo, 0,5), toda a pesquisa real caia no
        # `unknown_reply`, porque o RRF normalizado de um candidato so do `fts`
        # vale 0,4.
        self.assertEqual(portas["limiar_idx"], tls_idx.LIMIAR_DO_RRF)
        self.assertNotEqual(portas["limiar_idx"], nos_vendedor.LIMIAR_IDX)
        self.assertIsInstance(portas["hnd"], ServicoDeHandoff)
        self.assertIsInstance(portas["rascunho"], ServicoDeRascunho)
        self.assertIsInstance(portas["tools"], ToolLayer)
        # A **mesma** camada que o arranque conta na `toollayer_pronta` e fecha
        # no encerramento: uma segunda, sem executores, sobrevivia ao
        # `isinstance` (achado 5 da revisao adversarial).
        self.assertIs(portas["tools"], self.capturado["_fechar_as_tomadas"][0][2])
        self.assertIs(portas["metricas"], arranque.METRICAS)
        self.assertIs(portas["rascunho"]._abrir, arranque.ligar_para_concierge)
        self.assertIs(portas["admitir"], grafos_mod.admitir)
        self.assertIsNot(portas["admitir"], nos_vendedor._admite_sempre)
        self.assertIs(portas["checkpointer"], self.saver)
        porta = self._porta_do_turno().__self__
        self.assertIs(porta._checkpointer, self.saver)

    def test_a_saida_por_ligar_avisa_no_registo_e_levanta(self) -> None:
        import io

        portas = self.capturado["compilar"][0][1]
        registo = io.StringIO()
        with mock.patch("sys.stdout", registo), self.assertRaises(SaidaPorLigarError):
            portas["saida"].enfileirar({}, "ola", chave="t:0")
        linhas = [json.loads(l) for l in registo.getvalue().splitlines() if l.startswith("{")]
        self.assertIn(
            ("saida", "saida_por_ligar"),
            [(l.get("outcome"), l.get("error_code")) for l in linhas],
        )

    def test_o_detector_de_degradacao_le_a_admissao_do_processo(self) -> None:
        """Sem a admissao, os dois sinais de carga do KAM-037 nunca disparam."""
        portas = self.capturado["compilar"][0][1]
        executor = self.capturado["ExecutorDeTurnos"][1]
        self.assertIs(portas["degradacao"]._admissao, executor["admissao"])

    def test_o_concierge_por_ligar_deixou_de_sair_e_as_portas_por_ligar_dizem_se(self) -> None:
        linhas = [json.loads(l) for l in self._arranque.saida.getvalue().splitlines() if l.startswith("{")]
        desfechos = [l.get("outcome") for l in linhas]
        self.assertNotIn("concierge_por_ligar", desfechos)
        self.assertIn("grafos_ligados", desfechos)
        por_ligar = sorted(
            l["error_code"] for l in linhas if l.get("outcome") == "grafo_porta_por_ligar"
        )
        self.assertEqual(
            por_ligar, ["classificador", "classificador_de_guarda", "modos", "saida", "stt"]
        )


# ------------------------------------------------------------- as tools ditas


class TestToolsNoArranque(unittest.TestCase):
    """Criterio 9: o `toollayer_pronta` com e sem `KAMBA_COM_URL`."""

    def _linha(self, **extra: str) -> str:
        arranque_ = TestArranque("test_arranca_pelo_logger_e_cala_o_registo_proprio_do_uvicorn")
        arranque_.setUp()
        self.addCleanup(arranque_.doCleanups)
        ambiente = dict(AMBIENTE_BASE, KAMBA_FASE="piloto", KAMBA_REGISTRY_DIR=str(PASTA), **extra)
        if "KAMBA_COM_URL" not in extra:
            os.environ.pop("KAMBA_COM_URL", None)
        with mock.patch.object(arranque, "CheckpointerDoAgr", lambda *_a, **_k: InMemorySaver()):
            codigo, _ = arranque_._correr(ambiente)
        self.assertEqual(codigo, 0, arranque_.saida.getvalue())
        for linha in arranque_.saida.getvalue().splitlines():
            if '"toollayer_pronta"' in linha:
                return json.loads(linha)["error_code"]
        self.fail("sem linha toollayer_pronta")

    def test_com_o_com_ligam_se_seis_de_onze(self) -> None:
        # Quatro do COM, a `get_store_info` e, desde o KAM-061, o
        # `search_catalog` do IDX.
        self.assertEqual(self._linha(KAMBA_COM_URL="http://com.interno:3000"), "ligadas_6_de_11")

    def test_sem_o_com_a_da_plataforma_e_a_do_indice(self) -> None:
        # O `search_catalog` liga-se sem `KAMBA_COM_URL`: o indice vive na base
        # da plataforma, e nao depende do COM (KAM-061).
        self.assertEqual(self._linha(), "ligadas_2_de_11")


class TestPesquisaSemExecutor(unittest.TestCase):
    """Criterio 9, a outra metade: o `search_catalog` continua `declarado`
    (credor KAM-061), e um turno de pesquisa acaba numa resposta estatica —
    nunca numa excepcao que devolva o *job* a fila."""

    def test_um_turno_de_pesquisa_acaba_sem_excepcao_e_com_uma_resposta(self) -> None:
        from test_tls import _Ligacao
        from test_vendedor import LOJA

        catalogo = catalogo_do_piloto({})
        self.assertNotIn("search_catalog", catalogo.ligadas())
        # E as cinco do Vendedor que falam com o COM ficam `declaradas` sem
        # `KAMBA_COM_URL`: so a da plataforma responde.
        vendedor = _agentes({"vendedor"}).verticais["vendedor"]
        declaradas = set(vendedor.tools) - {"get_store_info"}
        self.assertEqual(len(declaradas), 5)
        self.assertFalse(declaradas & set(catalogo.ligadas()))
        tools = ToolLayer(catalogo, abrir_ligacao=_Ligacao(outro=LOJA).nova_vaga)
        porta, _, saida = _porta(tools=tools)
        invocacao = _invocacao()
        grafo = asyncio.run(porta.do_turno(invocacao))
        estado = asyncio.run(
            grafo.ainvoke(_estado_com_texto(invocacao, "procuro sapatos"), _config(invocacao))
        )
        self.assertEqual(len(saida.enviadas), 1)
        self.assertIn(nos_vendedor.MSG_NAO_ENTENDI, saida.enviadas[0][0])
        self.assertIsNone(estado.get("handoff_motivo"))


# ------------------------------------------------------------- a porta do turno


def _app(porta_do_turno, metricas: Any = None) -> Any:
    admissao = Admissao(tectos=Tectos(coalescencia_ms=0))

    async def palavra(_invocacao) -> Palavra:
        return Palavra(modo="bot", handoff_a_espera=False)

    async def reencaminhar(_invocacoes) -> None:
        return None

    executor = ExecutorDeTurnos(
        trancas=TrancaFalsa(),
        ler_palavra=palavra,
        grafos=porta_do_turno,
        reencaminhar=reencaminhar,
        admissao=admissao,
    )
    return create_app(
        rotas_internas=rotas(
            credencial=lambda: CREDENCIAL,
            executar=executor.correr,
            admissao=admissao,
            trancas=TrancaFalsa(),
        )
    )


def _turno(app, invocacao_crua_: dict[str, Any]) -> tuple[int, dict[str, Any]]:
    estado, _, corpo = asyncio.run(
        pedir(
            app,
            "/internal/turn",
            "POST",
            como_json(invocacao_crua_),
            {CABECALHO: CREDENCIAL},
        )
    )
    return estado, json.loads(corpo)


class _Espiao:
    """Um grafo compilado que conta as invocacoes e delega o resto."""

    def __init__(self, grafo: Any) -> None:
        self._grafo = grafo
        self.invocacoes = 0

    async def ainvoke(self, estado, config):
        self.invocacoes += 1
        return await self._grafo.ainvoke(estado, config)

    def __getattr__(self, nome: str) -> Any:
        return getattr(self._grafo, nome)


class TestPortaDoTurno(unittest.TestCase):
    """Criterios 2 e 3, medidos pela API interna."""

    def test_um_turno_valido_responde_200_executado_e_nao_503(self) -> None:
        porta, _, saida = _porta()
        estado, corpo = _turno(_app(porta.do_turno), invocacao_crua())
        self.assertEqual((estado, corpo["outcome"]), (200, "executado"))
        self.assertEqual(len(saida.enviadas), 1)

    def test_com_o_sem_grafos_o_mesmo_pedido_volta_a_503(self) -> None:
        estado, corpo = _turno(_app(sem_grafos), invocacao_crua())
        self.assertEqual((estado, corpo["outcome"]), (503, "grafo_nao_registado"))

    def test_uma_invocacao_de_servicos_corre_o_grafo_de_servicos(self) -> None:
        porta, compilados, _ = _porta()
        espioes = {nome: _Espiao(grafo) for nome, grafo in compilados.items()}
        porta._grafos = espioes
        estado, corpo = _turno(_app(porta.do_turno), invocacao_crua(vertical="servicos"))
        self.assertEqual((estado, corpo["outcome"]), (200, "executado"))
        self.assertEqual(espioes["servicos"].invocacoes, 1)
        self.assertEqual(espioes["vendedor"].invocacoes, 0)

    def test_sem_entitlement_e_servico_indisponivel_com_200_e_uma_tentativa(self) -> None:
        metricas = MetricasDoAgr()
        porta, compilados, saida = _porta(permitidos={"servicos"}, metricas=metricas)
        espioes = {nome: _Espiao(grafo) for nome, grafo in compilados.items()}
        porta._grafos = espioes
        estado, corpo = _turno(_app(porta.do_turno), invocacao_crua(vertical="vendedor"))
        # 200 e o *job* completa: o *shim* decide pelo estado HTTP, e um 2xx nao
        # repete. Uma tentativa, e nao «um numero finito» — o 503 de hoje ja era
        # finito.
        self.assertEqual((estado, corpo["outcome"]), (200, DESFECHO_SERVICO_INDISPONIVEL))
        self.assertEqual(sum(e.invocacoes for e in espioes.values()), 0)
        self.assertEqual(saida.enviadas, [])
        self.assertIn(
            f'{METRICA_REGISTO_NEGADO}{{motivo="sem_entitlement"}} 1', metricas.exposicao()
        )

    def test_uma_vertical_desconhecida_e_recusada_pelo_resolve(self) -> None:
        """O contrato ja recusa uma vertical fora do dominio; a porta, chamada com
        uma que o registo nao tem, recusa-a pelo `resolve` e nao levanta outra
        coisa — que seria um 500 e seis tentativas."""
        porta, _, _ = _porta()
        estranha = SimpleNamespace(tenant_id=_invocacao().tenant_id, vertical="assistente")
        with self.assertRaises(grafos_mod.VerticalRecusadaError) as capturado:
            asyncio.run(porta.do_turno(estranha))
        self.assertEqual(capturado.exception.motivo, "vertical_desconhecida")

    def test_o_desfecho_novo_conta_na_metrica_dos_turnos(self) -> None:
        self.assertIn(DESFECHO_SERVICO_INDISPONIVEL, DESFECHOS)


# ------------------------------------------------------------- as portas por thread


class TestPortaDaThread(unittest.TestCase):
    """Criterio 4: a vertical da *thread* vem do *checkpoint*, antes do CAS."""

    def test_depois_de_um_turno_de_servicos_a_thread_resolve_servicos(self) -> None:
        porta, compilados, _ = _porta()
        invocacao = _invocacao(vertical="servicos")
        grafo = asyncio.run(porta.do_turno(invocacao))
        asyncio.run(grafo.ainvoke(_estado_com_texto(invocacao, "ola"), _config(invocacao)))
        self.assertIs(asyncio.run(porta.da_thread(invocacao.thread_id)), compilados["servicos"])

    def test_sem_checkpoint_levanta_grafo_nao_registado(self) -> None:
        from kamba_agr.turno import GrafoNaoRegistadoError

        porta, _, _ = _porta()
        with self.assertRaises(GrafoNaoRegistadoError):
            asyncio.run(porta.da_thread(_invocacao().thread_id))

    def test_a_retoma_sem_grafo_nao_abre_a_base(self) -> None:
        """A porta `async` continua a resolver **antes** do CAS: sem grafo, a
        excepcao sobe e a ligacao do CAS nunca se abre."""
        from kamba_agr.handoff.retoma import Retomador
        from kamba_agr.turno import GrafoNaoRegistadoError

        porta, _, _ = _porta()
        aberturas: list[int] = []
        retomador = Retomador(
            abrir_ligacao=lambda: aberturas.append(1), grafos=porta.da_thread
        )
        with self.assertRaises(GrafoNaoRegistadoError):
            asyncio.run(
                retomador.retomar(_invocacao().thread_id, "00000000-0000-4000-8000-000000000001", "resolved")
            )
        self.assertEqual(aberturas, [])


    def test_uma_passagem_em_waiting_retoma_o_grafo_pela_porta_do_processo(self) -> None:
        """Ponta a ponta: um turno real para em `handoff_wait`, e o `Retomador`
        com a porta do processo vence o CAS e retoma-o — o `next` fica vazio."""
        from kamba_agr.handoff.retoma import Retomador
        from test_handoff import BaseFalsa
        from test_vendedor import Handoff

        porta, compilados, _ = _porta(hnd=Handoff())
        invocacao = _invocacao()
        grafo = asyncio.run(porta.do_turno(invocacao))
        asyncio.run(
            grafo.ainvoke(
                _estado_com_texto(invocacao, "quero falar com um humano"), _config(invocacao)
            )
        )
        vendedor = compilados["vendedor"]
        self.assertEqual(asyncio.run(vendedor.aget_state(_config(invocacao))).next, ("handoff_wait",))
        base = BaseFalsa(
            {"h1": {"tenant": invocacao.tenant_id, "status": "waiting"}},
            {"h1": invocacao.contact_id},
        )
        retomador = Retomador(abrir_ligacao=lambda: base, grafos=porta.da_thread)
        self.assertEqual(
            asyncio.run(retomador.retomar(invocacao.thread_id, "h1", "resolved")), "retomado"
        )
        self.assertEqual(asyncio.run(vendedor.aget_state(_config(invocacao))).next, ())

    def test_a_decisao_de_rascunho_sem_grafo_nao_abre_a_base(self) -> None:
        from kamba_agr.concierge.servico import Decisor
        from kamba_agr.turno import GrafoNaoRegistadoError

        porta, _, _ = _porta()
        aberturas: list[int] = []
        decisor = Decisor(abrir_ligacao=lambda: aberturas.append(1), grafos=porta.da_thread)
        with self.assertRaises(GrafoNaoRegistadoError):
            asyncio.run(
                decisor.decidir_pelo_sistema(_invocacao().thread_id, "d1", "expirado")
            )
        self.assertEqual(aberturas, [])


# ------------------------------------------------------------- a admissao


class TestAdmissao(unittest.TestCase):
    """Criterio 6: contacto bloqueado e `turn_id` repetido acabam sem envio."""

    def _correr(self, porta, invocacao, texto: str = "quanto custa a camisa?") -> Any:
        grafo = asyncio.run(porta.do_turno(invocacao))
        return asyncio.run(grafo.ainvoke(_estado_com_texto(invocacao, texto), _config(invocacao)))

    def test_contacto_bloqueado_acaba_sem_envio_e_sem_tools(self) -> None:
        porta, _, saida = _porta(bloqueado=_sempre_bloqueado)
        estado = self._correr(porta, _invocacao())
        self.assertEqual(estado["admissao"], grafos_mod.CONTACTO_BLOQUEADO)
        self.assertEqual(saida.enviadas, [])
        self.assertEqual(_ULTIMO_BACKEND[0].chamadas, {})

    def test_contacto_bloqueado_com_a_porta_na_omissao_envia(self) -> None:
        porta, _, saida = _porta(
            bloqueado=_sempre_bloqueado, admitir=nos_vendedor._admite_sempre
        )
        self._correr(porta, _invocacao())
        self.assertEqual(len(saida.enviadas), 1)

    def test_o_mesmo_turn_id_depois_de_acabar_nao_envia_outra_vez(self) -> None:
        porta, _, saida = _porta()
        invocacao = _invocacao()
        self._correr(porta, invocacao)
        self.assertEqual(len(saida.enviadas), 1)
        estado = self._correr(porta, invocacao)
        self.assertEqual(estado["admissao"], grafos_mod.TURNO_REPETIDO)
        self.assertEqual(len(saida.enviadas), 1)

    def test_o_mesmo_turn_id_com_a_porta_na_omissao_envia_outra_vez(self) -> None:
        porta, _, saida = _porta(admitir=nos_vendedor._admite_sempre)
        invocacao = _invocacao()
        self._correr(porta, invocacao)
        self._correr(porta, invocacao)
        self.assertEqual(len(saida.enviadas), 2)

    def test_o_mesmo_turn_id_de_um_turno_que_parou_a_meio_nao_e_repetido(self) -> None:
        """Criterio 4 do KAM-025: um turno que nao acabou repete-se desde o
        inicio, e a chave `turn_id:seq` e que o torna seguro. Chamar-lhe
        repetido perdia a resposta. Aqui o turno para no `handoff_wait`, com o
        `next` por correr e o mesmo `turn_id` no *checkpoint*."""
        from test_vendedor import Handoff

        porta, compilados, _ = _porta(hnd=Handoff())
        invocacao = _invocacao()
        self._correr(porta, invocacao, "quero falar com um humano")
        foto = asyncio.run(compilados["vendedor"].aget_state(_config(invocacao)))
        self.assertEqual(foto.next, ("handoff_wait",))
        self.assertEqual(foto.values["turn_id"], invocacao.turn_id)
        self.assertIsNone(asyncio.run(porta._admissao(invocacao, compilados["vendedor"])))

    def test_um_turno_novo_na_mesma_thread_corre(self) -> None:
        porta, _, saida = _porta()
        primeira = invocacao_crua()
        segunda = dict(primeira, wamid=primeira["wamid"] + "x")
        self._correr(porta, ler_invocacao(primeira))
        estado = self._correr(porta, ler_invocacao(segunda))
        self.assertIsNone(estado["admissao"])
        self.assertEqual(len(saida.enviadas), 2)

    def test_fora_de_um_turno_a_porta_admite(self) -> None:
        self.assertIsNone(grafos_mod.admitir({}))


# ------------------------------------------------------------- o par do P3


class TestParDoConcierge(unittest.TestCase):
    """Criterio 8: a politica sem `ServicoDeRascunho` nao chega a compilar."""

    def test_a_politica_sem_servico_recusa(self) -> None:
        politica = PoliticaDeConcierge(_leitor({"concierge"}))
        with self.assertRaises(grafos_mod.PortasIncoerentesError):
            grafos_mod.exigir_portas_coerentes({"concierge": politica, "rascunho": None})

    def test_a_politica_com_servico_passa(self) -> None:
        politica = PoliticaDeConcierge(_leitor({"concierge"}))
        grafos_mod.exigir_portas_coerentes({"concierge": politica, "rascunho": object()})

    def test_o_arranque_com_a_politica_e_sem_servico_sai_com_2(self) -> None:
        """A recusa e do arranque e nao do primeiro turno: o par nunca chega a
        servir. Mede-se no `main()` real, com o `ServicoDeRascunho` a faltar."""
        arranque_ = TestArranque("test_arranca_pelo_logger_e_cala_o_registo_proprio_do_uvicorn")
        arranque_.setUp()
        self.addCleanup(arranque_.doCleanups)
        ambiente = dict(AMBIENTE_BASE, KAMBA_FASE="piloto", KAMBA_REGISTRY_DIR=str(PASTA))
        with (
            mock.patch.object(arranque, "CheckpointerDoAgr", lambda *_a, **_k: InMemorySaver()),
            mock.patch.object(arranque, "ServicoDeRascunho", lambda **_k: None),
        ):
            codigo, correr = arranque_._correr(ambiente)
        self.assertEqual(codigo, 2)
        correr.assert_not_called()
        self.assertIn("portas_incoerentes", arranque_.saida.getvalue())

    def test_sem_politica_nao_ha_par(self) -> None:
        grafos_mod.exigir_portas_coerentes({"concierge": SemPolitica(), "rascunho": None})
        grafos_mod.exigir_portas_coerentes({})


# ------------------------------------------------------------- a saida


class TestSaidaPorLigar(unittest.TestCase):
    """Sem Outbound, a resposta nao se perde: o turno nao acaba e a rota da 503."""

    def test_avisa_e_levanta_em_cada_envio(self) -> None:
        avisos: list[str] = []
        saida = grafos_mod.SaidaPorLigar(aviso=avisos.append)
        for chave in ("t:0", "t:1"):
            with self.assertRaises(SaidaPorLigarError):
                saida.enfileirar({}, "ola", chave=chave)
        self.assertEqual(avisos, ["saida_por_ligar", "saida_por_ligar"])

    def test_um_turno_sem_outbound_e_503_e_a_reentrega_nao_e_repetida(self) -> None:
        """O *job* volta a fila, e quando volta corre outra vez em vez de ser
        engolido pela desduplicacao — o `send` ficou por correr no *checkpoint*."""
        porta, compilados, _ = _porta(saida=grafos_mod.SaidaPorLigar())
        crua = invocacao_crua()
        estado, corpo = _turno(_app(porta.do_turno), crua)
        self.assertEqual((estado, corpo["outcome"]), (503, "saida_por_ligar"))
        invocacao = ler_invocacao(crua)
        foto = asyncio.run(compilados["vendedor"].aget_state(_config(invocacao)))
        self.assertTrue(foto.next)
        self.assertIsNone(asyncio.run(porta._admissao(invocacao, compilados["vendedor"])))


class TestCompilar(unittest.TestCase):
    """A `persona` e as `tools_permitidas` sao da vertical (achado 6)."""

    def test_cada_vertical_recebe_a_sua_persona_e_as_suas_tools(self) -> None:
        from kamba_agr.verticais.vendedor.nos import Dependencias

        recebidas: dict[tuple[str, ...], Any] = {}

        def espiar(**kwargs: Any) -> Any:
            recebidas[tuple(kwargs["tools_permitidas"])] = kwargs["persona"]
            return Dependencias(**kwargs)

        agentes = _agentes({"vendedor", "servicos"})
        portas, _ = _portas_de_ensaio()
        grafos_mod.compilar(dict(agentes.verticais), portas, dependencias=espiar)
        for vertical in agentes.verticais.values():
            with self.subTest(vertical=vertical.id):
                self.assertIn(tuple(vertical.tools), recebidas)
                self.assertEqual(
                    recebidas[tuple(vertical.tools)],
                    vertical.persona.model_dump(exclude_none=True),
                )
        self.assertEqual(len(recebidas), 2)


class TestFicaForaDaEventLoop(unittest.TestCase):
    """As leituras sincronas da resolucao correm num *executor* (achados 4 e 11)."""

    def test_o_resolve_e_a_politica_nao_correm_na_thread_da_loop(self) -> None:
        import threading

        vistas: dict[str, int] = {}

        class Registo:
            def __init__(self, real: Any) -> None:
                self._real = real

            def resolve(self, ctx: Any) -> Any:
                vistas["resolve"] = threading.get_ident()
                return self._real.resolve(ctx)

        class Politica:
            def activa(self, _tenant: str) -> bool:
                vistas["politica"] = threading.get_ident()
                return False

        porta, compilados, _ = _porta()
        porta = grafos_mod.PortaDeGrafos(
            registo=Registo(porta._registo),
            grafos=compilados,
            checkpointer=porta._checkpointer,
            contacto_bloqueado=_nunca_bloqueado,
            politica=grafos_mod.PoliticaDoTurno(Politica()),
        )

        async def correr() -> int:
            await porta.do_turno(_invocacao())
            return threading.get_ident()

        da_loop = asyncio.run(correr())
        self.assertNotEqual(vistas["resolve"], da_loop)
        self.assertNotEqual(vistas["politica"], da_loop)


if __name__ == "__main__":
    unittest.main()
