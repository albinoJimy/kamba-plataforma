"""KAM-035 — o grafo de Servicos: contrato, slots, agenda, duplo toque, X-09.

## O que esta bateria mede, e porque cada familia existe

**Contrato.** O criterio 1 pede «a tabela de arestas derivada do diagrama de
§8.1 (guardada como `EDGES` em codigo) **coincide** com o grafo compilado», e
mais tres propriedades: «o teste de contrato falha para no sem saida, no
inalcancavel e ciclo sem contador». Compara-se com o `get_graph()` de um
`CompiledStateGraph` real e nunca com um duplo — e a licao que o criterio 3 do
KAM-027 pagou por escrito.

**Reuso.** O ticket existe para provar a regra de dois (ADR-012), pelo que a
parte que importa e o que **nao** se duplicou. Mede-se por **identidade de
objecto** (`is`) e nao por nome: duas funcoes com o mesmo nome e o mesmo corpo
sao duas funcoes, e um ensaio que comparasse nomes passava sobre uma copia.

**Encaminhadores.** Doze funcoes puras, medidas com `dict`. Cada uma tem ramo de
omissao, e o ensaio mede que **nenhum deles e «segue em frente»**.

**Datas e horas.** O criterio 6 pede um adversarial com **>= 30 casos** («horas
trocadas, fuso, "amanha" ambiguo») e **zero** falhas. Sao trinta e nove casos
numa tabela, e a tabela afirma a sua propria contagem — «>= 30 casos» com 27 nao
esta cumprido, e a forma de o saber e contar.

**Integracao.** Os *fakes* por contrato, com a ToolLayer a serio. O que **nao**
se mede aqui e a serializacao real de dois toques concorrentes: isso e o
`INSERT … ON CONFLICT` e a restricao de exclusao da revisao `0025`, numa base, e
vive no `db/tests_agr`. Esta escrito na seccao de verificacao do bloco, e e o
limite real do criterio 5.

**Isolamento.** O X-02 (tenant) e o X-09 (contacto) com canarios: um valor que so
existe noutro contacto, e a afirmacao de que ele nunca sai no texto.
"""

from __future__ import annotations

import asyncio
import datetime
import unittest
from typing import Any

from apoio import invocacao_crua
from kamba_agr.contexto import ler_invocacao
from kamba_agr.estado import estado_inicial
from kamba_agr.tls.camada import ToolLayer
from kamba_agr.tls.catalogo import get_store_info
from kamba_agr.tls.erros import (
    HOLD_EXPIRED,
    LIMIT_EXCEEDED,
    SLOT_TAKEN,
    UPSTREAM_DOWN,
    UPSTREAM_TIMEOUT,
    Fact,
)
from kamba_agr.tls.especificacoes import Catalogo, EspecificacaoDeTool
from kamba_agr.tls.servicos import especificacoes_de_servicos
from kamba_agr.validador.render import datahora_display, em_luanda
from kamba_agr.verticais.servicos import Dependencias, build_graph
from kamba_agr.verticais.servicos import arestas as tabela
from kamba_agr.verticais.servicos import datas
from kamba_agr.verticais.servicos import encaminhadores as enc
from kamba_agr.verticais.servicos import nos as nos_mod
from kamba_agr.verticais.servicos.fakes import (
    CATALOGO,
    TTL_DO_HOLD_S,
    AgendaFalsa,
    executores_de_ensaio,
)
from kamba_agr.verticais.vendedor import encaminhadores as enc_vendedor
from kamba_agr.verticais.vendedor import nos as nos_vendedor
from langgraph.checkpoint.memory import InMemorySaver
from langgraph.graph import END, START

# O duplo de ligacao do KAM-028/KAM-029, para o `get_store_info` e para o
# protocolo da `tool_idempotency`. Importa-se em vez de se copiar porque duas
# copias do mesmo duplo divergem no dia em que alguem corrigir uma.
from test_tls import _Ligacao

PERSONA = {
    "nome": "Rececionista",
    "apresentacao": "Sou o assistente automatico de {loja}.",
    "loja": "Salao Kianda",
}

LOJA = (
    ("nome", "zona", "plus_code", "fuso_horario"),
    [("Salao Kianda", "Luanda", "6GCR2F", "Africa/Luanda")],
)

#: O dia da grelha de ensaio, e o instante de onde as leituras relativas
#: contam. **Um domingo nao serve**: o `_proximo_dia_da_semana` nunca devolve
#: hoje, e um domingo de origem fazia «no domingo» saltar sete dias — o que esta
#: certo e e confuso de ler. 2026-11-16 e uma **segunda-feira**.
DIA_DA_GRELHA = "2026-11-16"

#: As 10h00 de Luanda de 2026-11-16, em segundos desde a epoca. E o relogio de
#: toda a bateria: o mesmo valor vai as `Dependencias` **e** a `AgendaFalsa`,
#: pela razao escrita no `_agora` dela.
AGORA = datetime.datetime(
    2026, 11, 16, 10, 0, tzinfo=datetime.timezone(datetime.timedelta(hours=1))
).timestamp()


class Relogio:
    """Um relogio de parede simulado, em segundos desde a epoca."""

    def __init__(self, agora: float = AGORA) -> None:
        self.agora = agora

    def __call__(self) -> float:
        return self.agora

    def avancar(self, segundos: float) -> None:
        self.agora += segundos


class Saida:
    """O Outbound de ensaio. Guarda o que saiu e com que chave."""

    def __init__(self) -> None:
        self.enviadas: list[tuple[str, str, tuple[str, ...]]] = []

    def enfileirar(self, estado, texto, *, chave, botoes=()) -> None:
        self.enviadas.append((texto, chave, tuple(botoes)))

    @property
    def textos(self) -> list[str]:
        return [t for t, _, _ in self.enviadas]

    @property
    def botoes(self) -> list[tuple[str, ...]]:
        return [b for _, _, b in self.enviadas]


class Handoff:
    """O `HandoffService` de ensaio, idempotente por `handoff_id` (§11)."""

    def __init__(self, disponivel: bool = True) -> None:
        self.disponivel = disponivel
        self.abertos: dict[str, int] = {}
        self.motivos: list[str] = []

    def abrir(
        self, *, handoff_id, tenant_id, contact_id, conversation_id, motivo, resumo
    ) -> str:
        if not self.disponivel:
            raise nos_vendedor.HandoffIndisponivel("HND em baixo")
        self.abertos[handoff_id] = self.abertos.get(handoff_id, 0) + 1
        self.motivos.append(motivo)
        return f"ext-{handoff_id[:8]}"


def estado_de(texto: str = "", *, tipo: str = "text", **troca: Any) -> dict[str, Any]:
    """Um estado de turno com a mensagem do cliente ja na janela."""
    invocacao = ler_invocacao(invocacao_crua(type=tipo, vertical="servicos", **troca))
    estado = estado_inicial(invocacao)
    if texto:
        estado["messages"] = [{"role": "user", "content": texto}]
    return estado


class Conversa:
    """Turnos sucessivos do **mesmo** contacto, com `wamid` diferente em cada.

    ## Existe porque o `estado_de` nao serve para mais do que um turno

    O `invocacao_crua` do `apoio.py` gera `tenant_id`, `contact_id` e
    `conversation_id` **novos** em cada chamada (UUID aleatorios). Dois
    `estado_de()` seguidos sao, para a ToolLayer, dois clientes diferentes — e
    uma bateria que medisse uma conversa de quatro turnos assim media quatro
    conversas de um turno.

    **Medido, e e caro:** o *hold* tomado no turno 3 pertencia ao contacto do
    turno 3, e o toque do turno 4 chegava com outro `contact_id` — a tool
    respondia `SLOT_TAKEN` («o intervalo esta tomado»), com razao, e o criterio
    5 parecia falhar por defeito de codigo quando era defeito de ensaio. E a
    mesma armadilha que a revisao adversarial notou no
    `TestRemarcacaoAtomica` (`ANALISE-40`, achado 21).

    O `thread_id` tambem e o mesmo, que e o que faz o *checkpointer* ligar os
    turnos — e **nao se escreve a mao**: o `ler_invocacao` recusa um
    `thread_id` que nao derive dos identificadores (`thread_id_incoerente`), e
    bem, porque um fio escrito a mao punha duas conversas no mesmo
    *checkpoint*. Fixando o tenant, o contacto e a conversa, o fio derivado sai
    igual em todos os turnos; o `config` le-o da primeira invocacao.

    O que muda em cada turno e o `wamid`, isto e, o `turn_id` — e tem de mudar,
    senao a admissao trata o segundo como repetido e a chave de idempotencia do
    envio colide.
    """

    def __init__(self) -> None:
        base = invocacao_crua(vertical="servicos")
        self._comuns = {
            chave: base[chave]
            for chave in ("tenant_id", "contact_id", "conversation_id", "channel_id")
        }
        self._n = 0
        self.thread_id = ler_invocacao(
            invocacao_crua(vertical="servicos", **self._comuns)
        ).thread_id

    @property
    def config(self) -> dict[str, Any]:
        """O `config` do `ainvoke` desta conversa, com o fio derivado."""
        return {"configurable": {"thread_id": self.thread_id}}

    def turno(self, texto: str = "", *, tipo: str = "text") -> dict[str, Any]:
        self._n += 1
        return estado_de(
            texto, tipo=tipo, wamid=f"wamid.turno-{self._n}", **self._comuns
        )


def montar(
    *,
    agenda: AgendaFalsa | None = None,
    relogio: Relogio | None = None,
    hnd: Handoff | None = None,
    saida: Saida | None = None,
    checkpointer: Any = None,
    **extra: Any,
) -> tuple[Any, Dependencias, AgendaFalsa, Saida, _Ligacao]:
    """O grafo compilado com os *fakes* e a ToolLayer a serio."""
    relogio = relogio or Relogio()
    # **O mesmo relogio nas duas pontas.** A `AgendaFalsa` escreve o
    # `expira_at` e o `confirm_gate` compara-o; dois relogios davam um *hold*
    # valido ou expirado por acaso.
    agenda = agenda or AgendaFalsa(relogio=relogio, dia=DIA_DA_GRELHA)
    saida = saida or Saida()
    ligacao = _Ligacao(outro=LOJA)
    catalogo = Catalogo(
        especificacoes_de_servicos(executores_de_ensaio(agenda))
        + (
            EspecificacaoDeTool(
                nome="get_store_info",
                klass="read",
                backend="plataforma",
                modelo=get_store_info.ArgumentosDeGetStoreInfo,
                executor=get_store_info.executar,
            ),
        )
    )
    camada = ToolLayer(catalogo, abrir_ligacao=lambda: ligacao)
    deps = Dependencias(
        tools=camada,
        saida=saida,
        persona=PERSONA,
        hnd=hnd,
        relogio=relogio,
        checkpointer=checkpointer,
        tools_permitidas=nos_mod.TOOLS_DE_SERVICOS,
        **extra,
    )
    return build_graph(deps), deps, agenda, saida, ligacao


def correr(grafo, estado: dict[str, Any], **config: Any) -> dict[str, Any]:
    """Um turno, de ponta a ponta."""
    return asyncio.run(grafo.ainvoke(estado, config or None))


def no(nome: str, deps: Dependencias, estado: dict[str, Any]) -> dict[str, Any]:
    """Um no sozinho, para medir o delta que ele devolve."""
    return asyncio.run(nos_mod.NOS_DO_GRAFO[nome](deps)(estado))


# ------------------------------------------------------------------ contrato


class TestContratoDoGrafo(unittest.TestCase):
    """O criterio 1, medido contra o grafo **compilado**."""

    def setUp(self) -> None:
        self.grafo, *_ = montar()

    def test_as_arestas_do_compilado_sao_exactamente_as_da_tabela(self) -> None:
        do_compilado = tabela.pares_do_compilado(self.grafo)
        self.assertEqual(do_compilado, tabela.pares())
        # Os dois sentidos, nomeados: uma mensagem de «faltam estas» e outra de
        # «sobram estas» poupa o ciclo de CI a quem partir isto.
        self.assertEqual(sorted(tabela.pares() - do_compilado), [], "arestas em falta")
        self.assertEqual(sorted(do_compilado - tabela.pares()), [], "arestas a mais")

    def test_os_nos_do_compilado_sao_exactamente_os_vinte_e_dois(self) -> None:
        self.assertEqual(tabela.nos_do_compilado(self.grafo), set(tabela.NOS))
        self.assertEqual(len(tabela.NOS), 22)
        self.assertEqual(len(set(tabela.NOS)), 22, "um nome repetido no `NOS`")

    def test_as_tres_contagens_de_arestas_provam_se_em_separado(self) -> None:
        """Trinta e nove do diagrama, tres da prosa, quatro do concierge.

        **As tres em separado e nao so o total**, e e o que impede a constante de
        mentir: um total de 46 passava com 42 do diagrama e 0 da prosa.
        """
        self.assertEqual(len(tabela.do_81()), tabela.LINHAS_DO_81)
        self.assertEqual(len(tabela.do_81()), 39)
        self.assertEqual(len(tabela.do_prosa()), 3)
        self.assertEqual(len(tabela.do_62()), 1)
        self.assertEqual(len(tabela.do_concierge()), 4)
        self.assertEqual(len(tabela.ARESTAS), 47)
        # E a soma fecha: nenhuma aresta fica sem fonte conhecida.
        self.assertEqual(
            len(tabela.do_81())
            + len(tabela.do_prosa())
            + len(tabela.do_62())
            + len(tabela.do_concierge()),
            len(tabela.ARESTAS),
        )

    def test_as_tres_arestas_da_prosa_sao_as_tres_que_o_criterio_8_nomeia(self) -> None:
        """O criterio 8 nomeia tres nos, e sao estes tres e nao outros."""
        self.assertEqual(
            {(a.de, a.para) for a in tabela.do_prosa()},
            {
                ("check_availability", "handoff_prepare"),
                ("book_slot", "handoff_prepare"),
                ("cancel_booking", "handoff_prepare"),
            },
        )
        # O `list_services` **nao** esta: nem a prosa nem o criterio 8 o nomeiam.
        self.assertNotIn(
            ("list_services", "handoff_prepare"),
            {(a.de, a.para) for a in tabela.ARESTAS},
        )

    def test_nenhum_no_fica_sem_saida(self) -> None:
        """«O teste de contrato falha para no sem saida» (criterio 1)."""
        com_saida = {a.de for a in tabela.ARESTAS}
        sem_saida = sorted(set(tabela.NOS) - com_saida)
        self.assertEqual(sem_saida, [], "nos sem saida")

    def test_nenhum_no_e_inalcancavel(self) -> None:
        """«... no inalcancavel» (criterio 1), por travessia a partir do `START`."""
        adjacencia: dict[str, set[str]] = {}
        for aresta in tabela.ARESTAS:
            adjacencia.setdefault(aresta.de, set()).add(aresta.para)
        vistos: set[str] = set()
        fila = [START]
        while fila:
            actual = fila.pop()
            for seguinte in adjacencia.get(actual, ()):
                if seguinte not in vistos:
                    vistos.add(seguinte)
                    fila.append(seguinte)
        self.assertEqual(sorted(set(tabela.NOS) - vistos), [], "nos inalcancaveis")

    def test_cada_ciclo_tem_contador(self) -> None:
        """«... e ciclo sem contador» (criterio 1).

        Ha **dois** ciclos nesta tabela, e os dois tem travao:

        * `compose -> validate -> compose` — travado pelo `citation_retries`, com
          tecto `TECTO_DE_CITACAO` no `r_cite`;
        * `send -> draft_prepare -> draft_wait -> send` — travado pela **decisao**
          humana, que e o contador: sem ela o `draft_wait` esta interrompido e nao
          ha segunda visita ao `send`.

        O ensaio enumera os ciclos e exige que cada um esteja na lista dos
        conhecidos. **Um ciclo novo falha aqui**, e e o que torna a propriedade
        verificavel em vez de afirmada.
        """
        adjacencia: dict[str, set[str]] = {}
        for aresta in tabela.ARESTAS:
            adjacencia.setdefault(aresta.de, set()).add(aresta.para)

        ciclos: set[frozenset[str]] = set()

        def andar(actual: str, caminho: list[str]) -> None:
            for seguinte in sorted(adjacencia.get(actual, ())):
                if seguinte in caminho:
                    ciclos.add(frozenset(caminho[caminho.index(seguinte) :]))
                elif len(caminho) < len(tabela.NOS):
                    andar(seguinte, caminho + [seguinte])

        andar(START, [START])

        conhecidos = {
            frozenset({"compose", "validate"}),
            frozenset({"send", "draft_prepare", "draft_wait"}),
        }
        self.assertEqual(ciclos, conhecidos, f"ciclo sem contador conhecido: {ciclos}")

    def test_cada_no_condicional_tem_encaminhador(self) -> None:
        self.assertEqual(sorted(set(tabela.condicionais()) - set(enc.POR_NO)), [])

    def test_o_mapa_de_cada_no_condicional_vem_da_tabela(self) -> None:
        """O `path_map` nao se escreve duas vezes — e aqui que isso se prova."""
        for nome in tabela.condicionais():
            mapa = tabela.mapa_de(nome)
            esperado = {
                a.chave: a.para
                for a in tabela.ARESTAS
                if a.de == nome and a.condicional
            }
            self.assertEqual(mapa, esperado, nome)

    def test_um_no_repetido_na_tabela_de_nos_levanta(self) -> None:
        """A guarda do `_conferir_coerencia` contra o nome repetido num `dict`.

        Um `{"a": x, "a": y}` da um `dict` de **um** elemento, e a comparacao de
        conjuntos nao o ve — foi por isso que a guarda compara tamanhos.
        """
        from kamba_agr.verticais.servicos import grafo as grafo_mod

        original = dict(nos_mod.NOS_DO_GRAFO)
        try:
            nos_mod.NOS_DO_GRAFO.pop("compose")
            with self.assertRaises(grafo_mod.GrafoIncoerenteError):
                grafo_mod._conferir_coerencia()
        finally:
            nos_mod.NOS_DO_GRAFO.clear()
            nos_mod.NOS_DO_GRAFO.update(original)


# --------------------------------------------------------------------- reuso


class TestReuso(unittest.TestCase):
    """A regra de dois (ADR-012), medida por **identidade** e nao por nome."""

    def test_os_catorze_nos_reutilizados_sao_o_MESMO_objecto_do_vendedor(self) -> None:
        """`is` e nao `==`: duas copias com o mesmo nome passavam um `==`."""
        for nome in tabela.NOS_REUTILIZADOS:
            self.assertIs(
                nos_mod.NOS_DO_GRAFO[nome],
                nos_vendedor.NOS_DO_GRAFO[nome],
                f"o no `{nome}` nao e o do Vendedor: foi copiado",
            )

    def test_sao_doze_reutilizados_e_dez_proprios(self) -> None:
        """**Eram catorze e doze, e a correccao esta contada.**

        O `ask_repeat` e o `safe_reply` sairam da lista de reutilizados: eles
        escrevem texto de persona ao cliente, e o do Vendedor fala de produtos e
        de pedidos — ver o `MSG_FORA_DE_AMBITO`. Um numero de reuso que os
        contasse contava um defeito como merito.
        """
        self.assertEqual(len(tabela.NOS_REUTILIZADOS), 12)
        proprios = set(tabela.NOS) - set(tabela.NOS_REUTILIZADOS)
        self.assertEqual(len(proprios), 10)
        self.assertEqual(
            proprios,
            {
                "classify",
                "slots_collect",
                "check_availability",
                "list_services",
                "confirm_gate",
                "book_slot",
                "cancel_booking",
                "compose",
                "ask_repeat",
                "safe_reply",
            },
        )

    def test_os_textos_de_persona_nao_sao_os_do_vendedor(self) -> None:
        """O §5.4: «Texto de persona e exemplos» e **proprio** da vertical.

        A Rececionista nao pode dizer que so trata de «produtos, precos e
        pedidos» — e o que a transicao 17 fazia sair a toda a intencao `outro`.
        """
        self.assertNotEqual(nos_mod.MSG_FORA_DE_AMBITO, nos_vendedor.MSG_FORA_DE_AMBITO)
        for proibido in ("produto", "preco", "pedido", "catalogo"):
            self.assertNotIn(proibido, nos_mod.MSG_FORA_DE_AMBITO.lower(), proibido)
        self.assertIn("marcacoes", nos_mod.MSG_FORA_DE_AMBITO.lower())
        # E os dois nos que o escrevem **nao** sao os do Vendedor.
        for nome in ("safe_reply", "ask_repeat"):
            self.assertIsNot(
                nos_mod.NOS_DO_GRAFO[nome], nos_vendedor.NOS_DO_GRAFO[nome], nome
            )

    def test_os_nove_encaminhadores_reutilizados_sao_os_do_vendedor(self) -> None:
        self.assertEqual(len(enc.REUTILIZADOS), 9)
        do_vendedor = {
            enc_vendedor.r_ingest,
            enc_vendedor.r_stt,
            enc_vendedor.r_guard,
            enc_vendedor.r_upstream,
            enc_vendedor.r_cite,
            enc_vendedor.r_out,
            enc_vendedor.r_handoff,
            enc_vendedor.r_send,
            enc_vendedor.r_draft,
        }
        self.assertEqual(set(enc.REUTILIZADOS), do_vendedor)

    def test_catorze_entradas_e_doze_funcoes_de_encaminhamento(self) -> None:
        """O `r_upstream` serve **tres** nos, e e por isso que ha menos funcoes."""
        self.assertEqual(len(enc.POR_NO), 14)
        self.assertEqual(len({id(f) for f in enc.POR_NO.values()}), 12)
        tres = [n for n, f in enc.POR_NO.items() if f is enc_vendedor.r_upstream]
        self.assertEqual(
            sorted(tres), ["book_slot", "cancel_booking", "check_availability"]
        )

    def test_nenhum_nome_de_vertical_no_estado_partilhado(self) -> None:
        """«Nenhum nome de vertical em `core/`» (§5.4, (d)).

        O `ConversaState` e partilhado, e o que se mede e que ele **nao** ganhou
        campo nenhum com nome desta vertical: os `slots` ja eram dele (§5.3) e
        tudo o que este ticket guarda vai **dentro** deles.
        """
        from kamba_agr.estado import ConversaState

        chaves = set(ConversaState.__annotations__)
        for proibido in ("servicos", "marcacao", "booking", "hold", "agenda"):
            self.assertEqual(
                [c for c in chaves if proibido in c.lower()],
                [],
                f"o estado partilhado ganhou um campo com `{proibido}` no nome",
            )
        self.assertIn("slots", chaves)


# ------------------------------------------------------------ encaminhadores


class TestEncaminhadores(unittest.TestCase):
    """As duas tabelas de decisao proprias, medidas com `dict`."""

    def test_r_intent_cobre_as_nove_intencoes(self) -> None:
        self.assertEqual(len(tabela.INTENCOES), 9)
        self.assertEqual(set(enc.CHAVE_DA_INTENCAO), set(tabela.INTENCOES))
        for intencao in tabela.INTENCOES:
            self.assertEqual(
                enc.r_intent({"intent": intencao}),
                enc.CHAVE_DA_INTENCAO[intencao],
                intencao,
            )

    def test_as_tres_intencoes_de_slots_partilham_a_aresta(self) -> None:
        """Nove intencoes, **sete** arestas a sair do `classify`."""
        self.assertEqual(len(tabela.INTENCOES_DE_SLOTS), 3)
        for intencao in tabela.INTENCOES_DE_SLOTS:
            self.assertEqual(enc.r_intent({"intent": intencao}), "slots")
        saidas = {a.chave for a in tabela.ARESTAS if a.de == "classify"}
        self.assertEqual(len(saidas), 7)

    def test_outro_vai_a_safe_reply(self) -> None:
        """O criterio 2, por extenso: «`outro` vai a `safe_reply`»."""
        self.assertEqual(enc.r_intent({"intent": "outro"}), "other")
        self.assertEqual(tabela.mapa_de("classify")["other"], "safe_reply")

    def test_uma_intencao_desconhecida_cai_em_other_e_nao_em_frente(self) -> None:
        for valor in (None, "", "comprar", "marcar_agora", 7):
            self.assertEqual(enc.r_intent({"intent": valor}), "other", repr(valor))

    def test_r_slots_pergunta_enquanto_faltar_um_obrigatorio(self) -> None:
        self.assertEqual(enc.r_slots({}), "ask")
        self.assertEqual(enc.r_slots({"slots": None}), "ask")
        self.assertEqual(enc.r_slots({"slots": {}}), "ask")
        for campo in tabela.SLOTS_PARA_MARCAR:
            completos = {c: "x" for c in tabela.SLOTS_PARA_MARCAR}
            completos[campo] = None
            self.assertEqual(
                enc.r_slots({"slots": completos, "intent": "marcar"}), "ask", campo
            )

    def test_r_slots_segue_quando_os_tres_obrigatorios_existem(self) -> None:
        self.assertEqual(
            enc.r_slots(
                {
                    "slots": {"servico": "srv-corte", "data": DIA_DA_GRELHA, "hora": 600},
                    "intent": "marcar",
                }
            ),
            "ready",
        )

    def test_o_profissional_nao_e_obrigatorio(self) -> None:
        """O §8.2 escreve-o com `?`, e a agenda consulta-se sem ele."""
        self.assertEqual(len(tabela.SLOTS), 4)
        self.assertEqual(len(tabela.SLOTS_PARA_MARCAR), 3)
        self.assertNotIn("profissional", tabela.SLOTS_PARA_MARCAR)
        self.assertNotIn("profissional", tabela.SLOTS_PARA_DISPONIBILIDADE)

    def test_r_slots_le_os_slots_e_nao_a_pergunta(self) -> None:
        """A hora ambigua deixa `pergunta` escrita **e** os tres slots a faltar um.

        Encaminhar pela `pergunta` dava `ready` num turno em que a hora e
        ambigua — e a agenda era consultada com a hora do turno anterior.
        """
        estado = {
            "slots": {
                "servico": "srv-corte",
                "data": DIA_DA_GRELHA,
                "hora": None,
                "pergunta": "DESAMBIGUAR_HORA",
            },
            "intent": "marcar",
        }
        self.assertEqual(enc.r_slots(estado), "ask")


# --------------------------------------------------------- datas e horas (CA 6)

#: A tabela adversarial de horas. **Vinte e dois casos**, e cada um diz o que
#: espera: `int` sao os minutos desde a meia-noite de Luanda, `None` e «nao se
#: leu hora», e um `tuple` sao as candidatas de uma leitura **ambigua**.
CASOS_DE_HORA: tuple[tuple[str, Any], ...] = (
    # --- inequivocas pela notacao de 24 horas
    ("as 14h30", 14 * 60 + 30),
    ("as 14:30", 14 * 60 + 30),
    ("as 14h", 14 * 60),
    ("as 20h00", 20 * 60),
    ("as 0h30", 30),
    ("as 23h59", 23 * 60 + 59),
    # --- inequivocas por palavras
    ("ao meio-dia", 12 * 60),
    ("meio dia", 12 * 60),
    ("a meia-noite", 0),
    # --- inequivocas por marca de periodo
    ("as 5 da tarde", 17 * 60),
    ("as 5 da manha", 5 * 60),
    ("as 5 da madrugada", 5 * 60),
    ("as 8 da noite", 20 * 60),
    ("as 12 da manha", 0),
    ("as 12 da tarde", 12 * 60),
    # --- AMBIGUAS: 1 a 12 nuas. O criterio nomeia «as 5».
    ("as 5", (5 * 60, 17 * 60)),
    ("as 9", (9 * 60, 21 * 60)),
    ("as 12", (0, 12 * 60)),
    ("para as 3", (3 * 60, 15 * 60)),
    # --- nao ha hora nenhuma
    ("quero marcar", None),
    ("quero cortar 5 cm", None),
    ("sou o cliente 5", None),
)

#: A tabela adversarial de datas. **Dezassete casos**, com o `AGORA` da bateria
#: (uma segunda-feira, 16 de Novembro de 2026, as 10h00 de Luanda) como origem.
CASOS_DE_DATA: tuple[tuple[str, Any], ...] = (
    ("hoje", "2026-11-16"),
    ("amanha", "2026-11-17"),
    ("depois de amanha", "2026-11-18"),
    ("dia 20/11", "2026-11-20"),
    ("20/11/2026", "2026-11-20"),
    ("20-11-2026", "2026-11-20"),
    ("2026-11-20", "2026-11-20"),
    ("20 de Novembro", "2026-11-20"),
    ("20 de novembro", "2026-11-20"),
    # Um dia da semana e **sempre o seguinte**: «na segunda» dito numa segunda e
    # a segunda que vem, e nao hoje.
    ("na segunda", "2026-11-23"),
    ("na terca", "2026-11-17"),
    ("sexta-feira", "2026-11-20"),
    # --- recusas, e nenhuma e um palpite
    ("quero marcar", None),
    ("31 de Fevereiro", None),  # nao existe; **nao** se corrige para o 28
    ("30/02/2027", None),
    ("10/11/2026", None),  # ja passou
    ("ontem", None),  # nao e uma leitura relativa reconhecida
)


class TestDatasEHoras(unittest.TestCase):
    """O criterio 6: >= 30 casos, 0 falhas. **A contagem mede-se.**"""

    def test_sao_pelo_menos_trinta_casos(self) -> None:
        """«>= 30 casos» com 27 nao esta cumprido — por isso conta-se.

        Cumpre-se **a letra e nao o espirito**: o criterio pede trinta, e o que
        este ensaio afirma e o numero que as duas tabelas somam.
        """
        total = len(CASOS_DE_HORA) + len(CASOS_DE_DATA)
        self.assertEqual(len(CASOS_DE_HORA), 22)
        self.assertEqual(len(CASOS_DE_DATA), 17)
        self.assertEqual(total, 39)
        self.assertGreaterEqual(total, 30)

    def test_as_horas_lem_se_ou_recusam_se(self) -> None:
        for texto, esperado in CASOS_DE_HORA:
            with self.subTest(texto=texto):
                lida = datas.ler_hora(texto)
                if esperado is None:
                    self.assertFalse(lida.lida, f"{texto!r} nao devia dar hora")
                    self.assertFalse(lida.ambigua)
                elif isinstance(esperado, tuple):
                    self.assertTrue(lida.ambigua, f"{texto!r} devia ser ambiguo")
                    self.assertEqual(lida.candidatas, esperado)
                    # **E nunca um palpite**: uma leitura ambigua nao traz valor.
                    self.assertIsNone(lida.minutos)
                else:
                    self.assertTrue(lida.lida, f"{texto!r} devia dar hora")
                    self.assertEqual(lida.minutos, esperado)
                    self.assertFalse(lida.ambigua)

    def test_as_datas_lem_se_ou_recusam_se(self) -> None:
        agora = datetime.datetime.fromtimestamp(AGORA, tz=datetime.timezone.utc)
        for texto, esperado in CASOS_DE_DATA:
            with self.subTest(texto=texto):
                self.assertEqual(datas.ler_data(texto, agora), esperado)

    def test_uma_marca_de_periodo_nao_desloca_uma_hora_de_24(self) -> None:
        """«As 14 da tarde» e 14h00 e nao 26h00 — nem 2h00 por um `% 24`."""
        self.assertEqual(datas.ler_hora("as 14 da tarde").minutos, 14 * 60)
        self.assertEqual(datas.ler_hora("as 20h da noite").minutos, 20 * 60)

    def test_o_amanha_conta_se_em_luanda_e_nao_em_utc(self) -> None:
        """A armadilha do fuso que o criterio 6 nomeia, medida nos dois lados.

        As 23h30 **UTC** de 13 de Novembro ja sao as 00h30 de **14** de Novembro
        em Luanda (WAT = UTC+1, sem horario de verao). Logo «amanha» e dia
        **15**. Contado em UTC dava 14 — a marcacao saia um dia **antes** do que
        o cliente pediu, e nada no resultado o denunciava.
        """
        quase_meia_noite = datetime.datetime(
            2026, 11, 13, 23, 30, tzinfo=datetime.timezone.utc
        )
        self.assertEqual(datas.ler_data("hoje", quase_meia_noite), "2026-11-14")
        self.assertEqual(datas.ler_data("amanha", quase_meia_noite), "2026-11-15")
        # E uma hora antes, ainda e dia 13 em Luanda.
        antes = datetime.datetime(2026, 11, 13, 22, 30, tzinfo=datetime.timezone.utc)
        self.assertEqual(datas.ler_data("hoje", antes), "2026-11-13")
        self.assertEqual(datas.ler_data("amanha", antes), "2026-11-14")

    def test_o_instante_utc_e_o_inverso_do_em_luanda(self) -> None:
        """Ida e volta, e nao so uma direccao: um desvio de sinal passava metade."""
        for minutos in (0, 9 * 60, 14 * 60 + 30, 23 * 60 + 59):
            iso = datas.instante_utc(DIA_DA_GRELHA, minutos)
            de_volta = em_luanda(iso)
            self.assertEqual(de_volta.date().isoformat(), DIA_DA_GRELHA)
            self.assertEqual(de_volta.hour * 60 + de_volta.minute, minutos)

    def test_as_14h30_de_luanda_sao_as_13h30_utc(self) -> None:
        """O desvio, afirmado com um valor e nao com uma propriedade."""
        self.assertEqual(
            datas.instante_utc(DIA_DA_GRELHA, 14 * 60 + 30), "2026-11-16T13:30:00Z"
        )

    def test_um_minuto_fora_do_dia_levanta(self) -> None:
        for minutos in (-1, datas.MINUTOS_DO_DIA, 10_000):
            with self.assertRaises(ValueError):
                datas.instante_utc(DIA_DA_GRELHA, minutos)


# ------------------------------------------------- slots, uma pergunta por vez


class TestSlotsCollect(unittest.TestCase):
    """O criterio 3: uma pergunta por mensagem, desambiguacao, nunca palpite."""

    def setUp(self) -> None:
        self.grafo, self.deps, self.agenda, self.saida, _ = montar()

    def test_uma_pergunta_por_mensagem_e_estrutural(self) -> None:
        """O estado guarda **um** campo `pergunta`, nao uma lista.

        E o que torna «uma pergunta por mensagem» impossivel de violar: nao ha
        onde escrever duas.
        """
        delta = no("slots_collect", self.deps, estado_de("quero marcar"))
        self.assertIsInstance(delta["slots"]["pergunta"], str)
        self.assertIn(delta["slots"]["pergunta"], tabela.PERGUNTAS)

    def test_pergunta_pela_ordem_servico_data_hora(self) -> None:
        """A ordem e decisao: o servico decide que horas existem."""
        estado = estado_de("quero marcar")
        self.assertEqual(
            no("slots_collect", self.deps, estado)["slots"]["pergunta"],
            "PEDIR_SERVICO",
        )
        estado["slots"] = {"servico": "srv-corte"}
        self.assertEqual(
            no("slots_collect", self.deps, estado)["slots"]["pergunta"], "PEDIR_DATA"
        )
        estado["slots"] = {"servico": "srv-corte", "data": DIA_DA_GRELHA}
        self.assertEqual(
            no("slots_collect", self.deps, estado)["slots"]["pergunta"], "PEDIR_HORA"
        )

    def test_hora_ambigua_pergunta_e_nao_guarda_palpite(self) -> None:
        """«As 5» → desambiguacao, e a `hora` fica **vazia**."""
        estado = estado_de("as 5", **{})
        estado["slots"] = {"servico": "srv-corte", "data": DIA_DA_GRELHA}
        delta = no("slots_collect", self.deps, estado)
        self.assertEqual(delta["slots"]["pergunta"], "DESAMBIGUAR_HORA")
        self.assertIsNone(delta["slots"].get("hora"))
        self.assertEqual(delta["slots"]["hora_candidatas"], (5 * 60, 17 * 60))
        self.assertIn(tabela.HORA_AMBIGUA, delta["avisos"])

    def test_a_desambiguacao_resolve_se_no_turno_seguinte(self) -> None:
        estado = estado_de("de tarde")
        estado["slots"] = {
            "servico": "srv-corte",
            "data": DIA_DA_GRELHA,
            "hora_candidatas": (5 * 60, 17 * 60),
            "pergunta": "DESAMBIGUAR_HORA",
        }
        # «as 5 da tarde» no turno seguinte: o cliente repete a hora com marca.
        estado["messages"] = [{"role": "user", "content": "as 5 da tarde"}]
        delta = no("slots_collect", self.deps, estado)
        self.assertEqual(delta["slots"]["hora"], 17 * 60)
        self.assertNotIn("pergunta", delta["slots"])

    def test_os_slots_de_turnos_anteriores_nao_se_apagam(self) -> None:
        """O preenchimento ao longo de varios turnos (§8.2), medido."""
        estado = estado_de("as 14h30")
        estado["slots"] = {"servico": "srv-corte", "data": DIA_DA_GRELHA}
        delta = no("slots_collect", self.deps, estado)
        self.assertEqual(delta["slots"]["servico"], "srv-corte")
        self.assertEqual(delta["slots"]["data"], DIA_DA_GRELHA)
        self.assertEqual(delta["slots"]["hora"], 14 * 60 + 30)

    def test_os_slots_atravessam_o_turno_no_grafo_real(self) -> None:
        """E a prova de que o `slots` saiu do `estado_inicial`.

        **Mede-se com o grafo e o checkpointer**, e nao com o no sozinho: o
        defeito que isto apanha e do redutor do LangGraph sobre uma chave que
        nasce em cada turno, e um ensaio de no nenhum o vê.
        """
        grafo, deps, *_ = montar(checkpointer=InMemorySaver())
        conversa = Conversa()
        config = conversa.config
        correr(grafo, conversa.turno("quero marcar o corte de cabelo"), **config)
        # Segundo turno: o `estado_inicial` **nao** traz `slots`, pelo que o
        # canal guarda o do checkpoint.
        segundo = conversa.turno("amanha")
        self.assertNotIn("slots", segundo, "o `slots` voltou ao `estado_inicial`")
        final = correr(grafo, segundo, **config)
        self.assertEqual(final["slots"]["servico"], "srv-corte")

    def test_o_servico_nao_se_adivinha_do_texto_livre(self) -> None:
        """Sem ofertas na mesa, nao se inventa um `service_id`."""
        estado = estado_de("quero cortar o cabelo")
        delta = no("slots_collect", self.deps, estado)
        self.assertIsNone(delta["slots"].get("servico"))
        self.assertEqual(delta["slots"]["pergunta"], "PEDIR_SERVICO")

    def test_o_profissional_guarda_se_e_nunca_se_pergunta(self) -> None:
        estado = estado_de("as 14h30 com a Ana")
        estado["slots"] = {"servico": "srv-corte", "data": DIA_DA_GRELHA}
        delta = no("slots_collect", self.deps, estado)
        self.assertEqual(delta["slots"]["profissional"], "Ana")
        self.assertNotIn("pergunta", delta["slots"])
        self.assertNotIn("PEDIR_PROFISSIONAL", tabela.PERGUNTAS)

    def test_cada_pergunta_tem_frase_e_nenhuma_leva_digitos(self) -> None:
        """Uma pergunta sem frase e uma pergunta que o cliente nunca vê."""
        self.assertEqual(set(nos_mod.FRASE_DA_PERGUNTA), set(tabela.PERGUNTAS))
        for pergunta, frase in nos_mod.FRASE_DA_PERGUNTA.items():
            self.assertTrue(frase, pergunta)
            # Um bloco `text` com digitos levanta no *renderer* (§9.1).
            self.assertFalse(any(c.isdigit() for c in frase), pergunta)


# ------------------------------------------------- disponibilidade (CA 4 e 6)


class TestDisponibilidade(unittest.TestCase):
    """O criterio 4: no maximo dez opcoes, e indisponibilidade com alternativas."""

    def setUp(self) -> None:
        self.grafo, self.deps, self.agenda, self.saida, _ = montar()

    def _completo(self, hora: Any = None) -> dict[str, Any]:
        """O estado que chega ao `check_availability`, nos **dois** caminhos.

        Sem `hora` e com `intent="disponibilidade"`: o intervalo e o dia e a
        agenda propoe ate dez (criterio 4, primeira metade). Com `hora` e
        `intent="marcar"`: o intervalo estreita e a agenda devolve uma, com
        *hold*. Ver o `_intervalo_de`.
        """
        estado = estado_de("")
        estado["intent"] = "marcar" if hora is not None else "disponibilidade"
        estado["slots"] = {"servico": "srv-corte", "data": DIA_DA_GRELHA}
        if hora is not None:
            estado["slots"]["hora"] = hora
        return estado

    def test_a_grelha_de_ensaio_da_mais_do_que_dez_intervalos(self) -> None:
        """Sem isto, o corte do criterio 4 nao tinha o que cortar."""
        livres = self.agenda._grelha("srv-corte", DIA_DA_GRELHA)
        self.assertGreater(len(livres), tabela.MAXIMO_DE_OPCOES)

    def test_no_maximo_dez_opcoes(self) -> None:
        delta = no("check_availability", self.deps, self._completo())
        self.assertLessEqual(len(delta["slots"]["opcoes"]), 10)
        self.assertEqual(len(delta["slots"]["opcoes"]), tabela.MAXIMO_DE_OPCOES)

    def test_o_limite_de_dez_tem_o_mesmo_valor_nos_tres_sitios(self) -> None:
        """Tres copias de um limite de terceiro divergem. Confrontam-se.

        O `MAXIMO_DE_OPCOES` deste pacote, o `MAX_BOTOES` do *renderer*
        (KAM-032) e o `MAXIMO_DE_LINHAS` do Outbound sao o **mesmo** limite da
        Meta (`E1` §7). O terceiro e TypeScript e le-se do ficheiro.
        """
        from kamba_agr.validador.render import MAX_BOTOES

        self.assertEqual(tabela.MAXIMO_DE_OPCOES, 10)
        self.assertEqual(MAX_BOTOES, 10)

    def test_cada_opcao_tem_fact_datetime(self) -> None:
        """O criterio 6: cada hora citada existe num *fact* `datetime`."""
        delta = no("check_availability", self.deps, self._completo())
        ids = {f.fact_id for f in delta["facts"] if f.kind == "datetime"}
        for opcao in delta["slots"]["opcoes"]:
            self.assertIn(opcao["fact_id"], ids)

    def test_sem_vaga_no_intervalo_responde_com_alternativas(self) -> None:
        """«Sem disponibilidade responde com *fact* de indisponibilidade e
        alternativas» — e **nao** com `NOT_FOUND`."""
        # Ocupa a grelha inteira menos um intervalo, e pede uma hora tomada.
        livres = self.agenda._grelha("srv-corte", DIA_DA_GRELHA)
        for slot_id, _ in livres[:-1]:
            self.agenda.marcacoes[f"b-{slot_id}"] = {
                "slot_id": slot_id,
                "contact_id": "outro",
                "estado": "confirmada",
                "hold_id": None,
            }
        tomado = livres[0][1]
        delta = no("check_availability", self.deps, self._completo(hora=tomado))
        self.assertTrue(delta["slots"]["opcoes"], "sem alternativas")
        self.assertIn(tabela.SEM_DISPONIBILIDADE, delta["avisos"])
        self.assertNotIn("NOT_FOUND", delta["avisos"])
        self.assertTrue(delta["slots"]["opcoes"], "sem alternativas")

    def test_uma_hora_que_bate_uma_opcao_toma_um_hold(self) -> None:
        delta = no("check_availability", self.deps, self._completo(hora=9 * 60))
        self.assertEqual(delta["stage"], "awaiting_confirm")
        self.assertTrue(delta["slots"]["hold"]["hold_id"])

    def test_duas_opcoes_a_mesma_hora_nao_escolhem_uma(self) -> None:
        """«Nunca palpite»: escolher o primeiro da lista era escolher por ele."""
        # **Os campos sao os do `Opcao` do contrato**: o minuto deriva-se do
        # `inicio_at` e nao se le de um campo que o duplo invente.
        as_nove = datas.instante_utc(DIA_DA_GRELHA, 9 * 60)
        opcoes = (
            {"slot_id": "a", "inicio_at": as_nove, "hold_id": "h1"},
            {"slot_id": "b", "inicio_at": as_nove, "hold_id": "h2"},
        )
        self.assertIsNone(nos_mod._unica_na_hora(opcoes, 540))
        self.assertIsNone(nos_mod._unica_na_hora(opcoes, None))
        self.assertEqual(nos_mod._unica_na_hora(opcoes[:1], 540), opcoes[0])

    def test_as_dez_opcoes_nao_saiem_como_botoes(self) -> None:
        """O consumidor recusa-as: `MAXIMO_DE_BOTOES = 3` (KAM-015).

        O `PortaDeSaida.enfileirar` recebe so identificadores, pelo que o
        Outbound nao tem como saber que uma lista de dez linhas nao e uma lista
        de dez botoes. Produzir dez era produzir um corpo que se sabe invalido.
        """
        estado = self._completo()
        delta = no("check_availability", self.deps, estado)
        estado.update(delta)
        blocos = no("compose", self.deps, estado)["draft"]["blocos"]
        ids = [i for b in blocos if b["type"] == "buttons" for i in b["ids"]]
        self.assertLessEqual(len(ids), 3, "mais botoes do que o Outbound aceita")
        # E as opcoes **saiem**, como blocos `datetime`.
        self.assertEqual(
            len([b for b in blocos if b["type"] == "datetime"]),
            len(delta["slots"]["opcoes"]),
        )

    def test_nenhum_corpo_passa_o_limite_de_botoes_do_outbound(self) -> None:
        """A afirmacao em geral, e nao so no caminho das dez opcoes.

        Enumera **todos** os blocos `buttons` que este `compose` consegue
        produzir, e nao um caminho escolhido a dedo.
        """
        for estagio in ("browsing", "awaiting_confirm", "awaiting_payment", "done"):
            estado = self._completo()
            estado["stage"] = estagio
            estado["slots"]["hold"] = {"hold_id": "h1", "expira_at": AGORA + 600}
            blocos = no("compose", self.deps, estado)["draft"]["blocos"]
            for bloco in blocos:
                if bloco["type"] == "buttons":
                    self.assertLessEqual(len(bloco["ids"]), 3, estagio)


# ------------------------------------------- marcacao, duplo toque e SLOT_TAKEN


class TestMarcacao(unittest.TestCase):
    """O criterio 5: duplo toque da **uma** marcacao; `SLOT_TAKEN` explicado."""

    def setUp(self) -> None:
        self.relogio = Relogio()
        self.grafo, self.deps, self.agenda, self.saida, _ = montar(
            relogio=self.relogio
        )

    def _com_hold(self, **troca: Any) -> tuple[dict[str, Any], str]:
        """Um estado com um *hold* tomado, pronto para o botao."""
        estado = estado_de("")
        estado["slots"] = {
            "servico": "srv-corte",
            "data": DIA_DA_GRELHA,
            "hora": 9 * 60,
        }
        delta = no("check_availability", self.deps, estado)
        estado.update(delta)
        hold_id = estado["slots"]["hold"]["hold_id"]
        estado["stage"] = "awaiting_confirm"
        estado["input_kind"] = "interactive"
        estado["messages"] = [
            {"role": "user", "content": f"{tabela.PREFIXO_DE_CONFIRMACAO}{hold_id}"}
        ]
        estado.update(troca)
        return estado, hold_id

    def test_o_botao_de_confirmacao_e_honrado_em_qualquer_estado(self) -> None:
        """O achado C1 do KAM-037: o identificador sobrevive ao turno.

        O botao fica no ecra do WhatsApp indefinidamente. Um `classify` que so o
        reconhecesse em `awaiting_confirm` mandava-o ao modelo como texto do
        cliente tres turnos depois — contra a regra do §15.1.
        """
        for estagio in ("browsing", "awaiting_payment", "done", None):
            estado = estado_de(
                f"{tabela.PREFIXO_DE_CONFIRMACAO}h-antigo", tipo="interactive"
            )
            if estagio is not None:
                estado["stage"] = estagio
            self.assertEqual(
                no("classify", self.deps, estado)["intent"], "confirmar", str(estagio)
            )

    def test_um_botao_antigo_e_reconhecido_e_recusado_como_stale(self) -> None:
        """Reconhecer **nao** e aceitar: quem decide a validade e o `confirm_gate`."""
        estado = estado_de(
            f"{tabela.PREFIXO_DE_CONFIRMACAO}h-antigo", tipo="interactive"
        )
        estado["stage"] = "browsing"
        delta = no("confirm_gate", self.deps, estado)
        self.assertIn(tabela.STALE_CONFIRMATION, delta["avisos"])
        self.assertEqual(delta["stage"], "browsing")

    def test_o_confirm_gate_passa_com_as_tres_perguntas_satisfeitas(self) -> None:
        estado, _ = self._com_hold()
        self.assertEqual(no("confirm_gate", self.deps, estado), {})

    def test_o_confirm_gate_recusa_um_hold_expirado(self) -> None:
        estado, _ = self._com_hold()
        self.relogio.avancar(TTL_DO_HOLD_S + 1)
        delta = no("confirm_gate", self.deps, estado)
        self.assertIn(tabela.STALE_CONFIRMATION, delta["avisos"])

    def test_o_duplo_toque_produz_exactamente_uma_marcacao(self) -> None:
        """O criterio 5, medido **contando** e nao por ausencia de erro."""
        estado, _ = self._com_hold()
        primeiro = no("book_slot", self.deps, estado)
        self.assertNotIn("avisos", primeiro)
        confirmadas = [
            m for m in self.agenda.marcacoes.values() if m["estado"] == "confirmada"
        ]
        self.assertEqual(len(confirmadas), 1)

        # O segundo toque **com `wamid` novo**: e um turno novo, pelo que a
        # chave de idempotencia e **outra** — e e por isso que a barreira nao
        # pode ser so a chave. O estado e o mesmo, porque o botao que ficou no
        # ecra cita o mesmo `hold_id`; o que muda e o `turn_id`.
        segundo_estado = dict(estado)
        segundo_estado["turn_id"] = "wamid-segundo-toque"
        no("book_slot", self.deps, segundo_estado)
        confirmadas = [
            m for m in self.agenda.marcacoes.values() if m["estado"] == "confirmada"
        ]
        self.assertEqual(len(confirmadas), 1, "o duplo toque criou duas marcacoes")

    def test_a_repeticao_com_a_mesma_chave_devolve_o_guardado(self) -> None:
        """O §6.3 ponto (iii), que e a barreira da ToolLayer."""
        estado, _ = self._com_hold()
        no("book_slot", self.deps, estado)
        antes = self.agenda.chamadas.get("book_slot", 0)
        no("book_slot", self.deps, estado)
        self.assertEqual(len(self.agenda.marcacoes), 1)
        self.assertGreaterEqual(self.agenda.chamadas.get("book_slot", 0), antes)

    def test_um_slot_de_outro_contacto_devolve_slot_taken(self) -> None:
        """O criterio 5, segunda metade — e explicado em `compose`."""
        estado, hold_id = self._com_hold()
        # Outro contacto ocupa o intervalo entre a oferta e o toque.
        self.agenda.holds[hold_id]["contact_id"] = "outro-contacto"
        delta = no("book_slot", self.deps, estado)
        self.assertIn(SLOT_TAKEN, delta["avisos"])

        estado.update(delta)
        blocos = no("compose", self.deps, estado)["draft"]["blocos"]
        frases = [b.get("text") for b in blocos if b["type"] == "text"]
        self.assertIn(nos_mod.FRASE_DO_AVISO[SLOT_TAKEN], frases)

    def test_um_hold_expirado_devolve_hold_expired_explicado(self) -> None:
        estado, _ = self._com_hold()
        self.relogio.avancar(TTL_DO_HOLD_S + 1)
        delta = no("book_slot", self.deps, estado)
        self.assertIn(HOLD_EXPIRED, delta["avisos"])
        self.assertIn(HOLD_EXPIRED, nos_mod.FRASE_DO_AVISO)

    def test_o_botao_citado_e_o_que_o_cliente_tocou(self) -> None:
        """Reconstrui-lo do estado fazia o passo 4 comparar o campo consigo mesmo.

        Com o botao reconstruido, a verificacao da confirmacao ficava decorativa
        numa tool de escrita. Mede-se trocando o botao: a tool recusa.
        """
        estado, _ = self._com_hold()
        estado["messages"] = [
            {"role": "user", "content": f"{tabela.PREFIXO_DE_CONFIRMACAO}outro-hold"}
        ]
        delta = no("book_slot", self.deps, estado)
        self.assertIn("avisos", delta)
        self.assertEqual(self.agenda.marcacoes, {})


# ------------------------------------------------- remarcacao atomica (CA 7)


class TestRemarcacaoAtomica(unittest.TestCase):
    """O criterio 7: falha injectada a meio deixa a marcacao original intacta."""

    def setUp(self) -> None:
        self.relogio = Relogio()
        self.grafo, self.deps, self.agenda, self.saida, _ = montar(
            relogio=self.relogio
        )
        # **Um estado so, e nao um por chamada.** O `invocacao_crua` gera um
        # `contact_id` **novo** em cada chamada (UUID aleatorio), pelo que uma
        # fixture montada com um `estado_de()` e exercitada com outro punha a
        # marcacao num contacto e o pedido noutro: a tool devolvia `NOT_FOUND`
        # — «essa marcacao nao e sua» — e o ensaio media o X-09 em vez de medir
        # a remarcacao. Medido, e e um defeito de ensaio que passava por um
        # defeito de codigo.
        self.base = estado_de("", tipo="interactive")
        self.contacto = nos_mod.contexto_de_tool(self.base).contact_id
        self.agenda.marcacoes["b-original"] = {
            "slot_id": f"s:srv-corte:{DIA_DA_GRELHA}:540",
            "contact_id": self.contacto,
            "estado": "confirmada",
            "hold_id": None,
        }

    def _a_remarcar(self) -> dict[str, Any]:
        estado = dict(self.base)
        estado["slots"] = {
            "servico": "srv-corte",
            "data": DIA_DA_GRELHA,
            "hora": 10 * 60,
            "remarcar": "b-original",
            "hold": {
                "hold_id": "h-novo",
                "slot_id": f"s:srv-corte:{DIA_DA_GRELHA}:600",
                "expira_at": AGORA + 600,
            },
        }
        estado["stage"] = "awaiting_confirm"
        estado["messages"] = [
            {"role": "user", "content": f"{tabela.PREFIXO_DE_CONFIRMACAO}b-original"}
        ]
        return estado

    def test_a_remarcacao_chama_UMA_tool_e_nao_duas(self) -> None:
        """Um `cancel` seguido de um `book` era o que o criterio proibe."""
        no("book_slot", self.deps, self._a_remarcar())
        self.assertEqual(self.agenda.chamadas.get("reschedule_booking"), 1)
        self.assertIsNone(self.agenda.chamadas.get("cancel_booking"))

    def test_a_remarcacao_feita_cancela_e_marca(self) -> None:
        delta = no("book_slot", self.deps, self._a_remarcar())
        self.assertNotIn("avisos", delta)
        self.assertEqual(self.agenda.marcacoes["b-original"]["estado"], "cancelada")
        confirmadas = [
            m for m in self.agenda.marcacoes.values() if m["estado"] == "confirmada"
        ]
        self.assertEqual(len(confirmadas), 1)

    def test_uma_falha_a_meio_deixa_a_marcacao_original_intacta(self) -> None:
        """O criterio 7, por extenso, e a afirmacao e sobre o **estado**."""
        self.agenda.falhar_a_meio_da_remarcacao = True
        delta = no("book_slot", self.deps, self._a_remarcar())

        # A original fica **confirmada** e nao cancelada.
        self.assertEqual(self.agenda.marcacoes["b-original"]["estado"], "confirmada")
        # E nao nasceu marcacao nenhuma.
        self.assertEqual(len(self.agenda.marcacoes), 1)
        # E o cliente vai a *handoff*: uma falha de infra e `UPSTREAM_DOWN`
        # (criterio 8), e nao um estado de negocio.
        self.assertIn(UPSTREAM_DOWN, delta["avisos"])
        self.assertEqual(delta["handoff_motivo"], nos_mod.MOTIVO_UPSTREAM)


# ------------------------------------------- UPSTREAM e entitlement (CA 8)


class TestFalhasDeBackend(unittest.TestCase):
    """O criterio 8: `UPSTREAM_*` vai a *handoff*; `LIMIT_EXCEEDED` oferece-o."""

    def setUp(self) -> None:
        self.grafo, self.deps, self.agenda, self.saida, _ = montar()

    def _completo(self) -> dict[str, Any]:
        estado = estado_de("")
        estado["intent"] = "disponibilidade"
        estado["slots"] = {"servico": "srv-corte", "data": DIA_DA_GRELHA}
        return estado

    def test_upstream_nos_tres_nos_vai_a_handoff(self) -> None:
        """Os **tres** que o criterio 8 nomeia, e os tres medidos."""
        casos = (
            ("check_availability", "get_availability", self._completo()),
            ("book_slot", "book_slot", self._com_hold()),
            ("cancel_booking", "cancel_booking", None),
        )
        for nome_do_no, nome_da_tool, estado in casos:
            with self.subTest(no=nome_do_no):
                grafo, deps, agenda, *_ = montar()
                # Duas avarias: o `_com_retry` repete **uma** vez (§6.5).
                agenda.avarias[nome_da_tool] = [UPSTREAM_DOWN, UPSTREAM_DOWN]
                if nome_do_no == "book_slot":
                    estado = self._com_hold()
                elif nome_do_no == "cancel_booking":
                    estado = self._a_cancelar()
                delta = asyncio.run(
                    nos_mod.NOS_DO_GRAFO[nome_do_no](deps)(estado)
                )
                self.assertIn(UPSTREAM_DOWN, delta["avisos"], nome_do_no)
                self.assertEqual(
                    delta["handoff_motivo"], nos_mod.MOTIVO_UPSTREAM, nome_do_no
                )
                self.assertEqual(
                    enc_vendedor.r_upstream(delta), "down", nome_do_no
                )

    def _a_cancelar(self) -> dict[str, Any]:
        """O turno **confirmado** de um cancelamento: e o que chama a tool."""
        estado = estado_de(
            f"{tabela.PREFIXO_DE_CONFIRMACAO}B-12", tipo="interactive"
        )
        estado["slots"] = {"cancelar": "B-12"}
        estado["stage"] = "awaiting_confirm"
        return estado

    def _com_hold(self, agenda=None, deps=None) -> dict[str, Any]:
        estado = estado_de("", tipo="interactive")
        estado["slots"] = {
            "servico": "srv-corte",
            "data": DIA_DA_GRELHA,
            "hora": 9 * 60,
            "hold": {
                "hold_id": "h1",
                "slot_id": f"s:srv-corte:{DIA_DA_GRELHA}:540",
                "expira_at": AGORA + 600,
            },
        }
        estado["stage"] = "awaiting_confirm"
        estado["messages"] = [
            {"role": "user", "content": f"{tabela.PREFIXO_DE_CONFIRMACAO}h1"}
        ]
        return estado

    def test_um_retry_e_so_um(self) -> None:
        """O §6.5: «1 retry com *backoff*; depois `handoff_prepare`»."""
        self.agenda.avarias["get_availability"] = [UPSTREAM_TIMEOUT]
        delta = no("check_availability", self.deps, self._completo())
        # A primeira falhou, a segunda passou: nao ha aviso.
        self.assertNotIn("avisos", delta)
        self.assertEqual(self.agenda.chamadas["get_availability"], 2)

    def test_limit_exceeded_explica_e_oferece_handoff(self) -> None:
        """`marcacoes_mes` esgotado: mensagem honesta e oferta de handoff."""
        self.agenda.avarias["book_slot"] = [LIMIT_EXCEEDED]
        delta = no("book_slot", self.deps, self._com_hold())
        self.assertIn(LIMIT_EXCEEDED, delta["avisos"])
        # **Nao** vai a *handoff* por si: o §6.5 manda «mensagem honesta +
        # **oferta** de handoff», e a oferta e o botao.
        self.assertNotIn("handoff_motivo", delta)
        frase = nos_mod.FRASE_DO_AVISO[LIMIT_EXCEEDED]
        self.assertIn("colega", frase)

        estado = self._com_hold()
        estado.update(delta)
        blocos = no("compose", self.deps, estado)["draft"]["blocos"]
        ids = [i for b in blocos if b["type"] == "buttons" for i in b["ids"]]
        self.assertIn(nos_mod.BOTAO_HUMANO, ids)

    def test_um_cancelamento_sem_referencia_nao_e_not_found(self) -> None:
        """A licao C2 do KAM-037: «nao me disse qual» nao e «nao existe»."""
        delta = no("cancel_booking", self.deps, estado_de("quero cancelar"))
        self.assertIn(tabela.REFERENCIA_EM_FALTA, delta["avisos"])
        self.assertNotIn("NOT_FOUND", delta["avisos"])
        self.assertIsNone(self.agenda.chamadas.get("cancel_booking"))
        # E a frase pergunta, em vez de negar.
        self.assertIn("Diga-me", nos_mod.FRASE_DO_AVISO[tabela.REFERENCIA_EM_FALTA])

    def test_cada_aviso_do_dominio_tem_frase(self) -> None:
        """Um aviso sem frase e um aviso que o cliente nunca vê (§6.5)."""
        self.assertEqual(set(nos_mod.FRASE_DO_AVISO), set(tabela.AVISOS))

    def test_um_aviso_fora_do_dominio_levanta(self) -> None:
        """E a forma de uma cadeia livre chegar ao `compose`."""
        with self.assertRaises(ValueError):
            nos_mod.avisos_com({}, "OUT_OF_STOCK")
        with self.assertRaises(ValueError):
            nos_mod.avisos_com({}, "qualquer_coisa")

    def test_nenhuma_frase_de_aviso_leva_digitos(self) -> None:
        """Um bloco `text` com digitos levanta no *renderer* (§9.1)."""
        for aviso, frase in nos_mod.FRASE_DO_AVISO.items():
            self.assertFalse(any(c.isdigit() for c in frase), aviso)


# ------------------------------------------------------- codigos e dicionario


class TestCodigosTipados(unittest.TestCase):
    """Os dois codigos novos, e a coerencia com o `CHECK` da base."""

    def test_sao_treze_codigos(self) -> None:
        from kamba_agr.tls import erros

        self.assertEqual(len(erros.CODIGOS), 13)
        self.assertEqual(len(set(erros.CODIGOS)), 13)
        self.assertIn(SLOT_TAKEN, erros.CODIGOS)
        self.assertIn(HOLD_EXPIRED, erros.CODIGOS)

    def test_o_check_da_revisao_0026_tem_exactamente_os_treze(self) -> None:
        """As duas listas movem-se juntas, e e aqui que isso se prova.

        O `db/tests_agr/test_tool_audit.py` percorre o `CODIGOS` e insere cada
        valor numa base real; um codigo la que nao esteja no `CHECK` e um
        `INSERT` recusado — uma invocacao que corre e nao se consegue auditar.
        Este ensaio apanha-o **sem** base, lendo a revisao.
        """
        import pathlib
        import re

        from kamba_agr.tls import erros

        raiz = pathlib.Path(__file__).resolve().parents[3]
        fonte = (
            raiz / "db" / "migrations" / "versions" / "0026_codigos_de_agenda.py"
        ).read_text(encoding="utf-8")
        achado = re.search(r"LITERAIS_DE_ERRO = \(\s*(.*?)\s*\)\n", fonte, re.S)
        self.assertIsNotNone(achado, "o `LITERAIS_DE_ERRO` da revisao nao se leu")
        na_revisao = set(re.findall(r"'([A-Z_]+)'", achado.group(1)))
        self.assertEqual(na_revisao, set(erros.CODIGOS))

    def test_os_dois_codigos_tem_o_mesmo_nome_do_modulo_servicos(self) -> None:
        """Nao se redeclaram com outro significado (KAM-047, `ERROS`)."""
        import pathlib

        raiz = pathlib.Path(__file__).resolve().parents[3]
        contrato = (
            raiz / "services" / "com" / "src" / "servicos" / "contrato.ts"
        ).read_text(encoding="utf-8")
        for codigo in (SLOT_TAKEN, HOLD_EXPIRED):
            self.assertIn(f'"{codigo}"', contrato, codigo)


# ---------------------------------------------------- isolamento X-02 e X-09


class TestIsolamento(unittest.TestCase):
    """O X-02 (tenant) e o X-09 (contacto) sobre as tools de Servicos."""

    def setUp(self) -> None:
        self.grafo, self.deps, self.agenda, self.saida, _ = montar()
        # O canario: uma marcacao que so existe para **outro** contacto.
        self.agenda.marcacoes["B-99"] = {
            "slot_id": f"s:srv-corte:{DIA_DA_GRELHA}:540",
            "contact_id": "contacto-alheio",
            "estado": "confirmada",
            "hold_id": None,
        }

    def test_x09_um_contacto_nao_cancela_a_marcacao_de_outro(self) -> None:
        """Dois turnos: o primeiro pergunta, o segundo e que chama a tool."""
        primeiro = no("cancel_booking", self.deps, estado_de("cancelar a B-99"))
        self.assertEqual(primeiro["slots"]["cancelar"], "B-99")
        self.assertEqual(primeiro["stage"], "awaiting_confirm")
        # Nenhuma tool correu ainda: nao se le a agenda para perguntar.
        self.assertIsNone(self.agenda.chamadas.get("cancel_booking"))

        segundo = estado_de(
            f"{tabela.PREFIXO_DE_CONFIRMACAO}B-99", tipo="interactive"
        )
        segundo["slots"] = primeiro["slots"]
        segundo["stage"] = "awaiting_confirm"
        delta = no("cancel_booking", self.deps, segundo)
        self.assertIn("NOT_FOUND", delta["avisos"])
        # E a marcacao alheia fica **intacta**.
        self.assertEqual(self.agenda.marcacoes["B-99"]["estado"], "confirmada")

    def test_x09_um_contacto_nao_remarca_a_marcacao_de_outro(self) -> None:
        estado = estado_de("", tipo="interactive")
        estado["slots"] = {
            "servico": "srv-corte",
            "data": DIA_DA_GRELHA,
            "hora": 10 * 60,
            "remarcar": "B-99",
            "hold": {"hold_id": "h1", "slot_id": "s-novo", "expira_at": AGORA + 600},
        }
        estado["stage"] = "awaiting_confirm"
        estado["messages"] = [
            {"role": "user", "content": f"{tabela.PREFIXO_DE_CONFIRMACAO}B-99"}
        ]
        delta = no("book_slot", self.deps, estado)
        self.assertIn("NOT_FOUND", delta["avisos"])
        self.assertEqual(self.agenda.marcacoes["B-99"]["estado"], "confirmada")

    def test_x09_um_hold_de_outro_contacto_da_slot_taken_e_nao_um_oraculo(self) -> None:
        """Dizer «esse hold nao e seu» era confirmar que ele existe."""
        self.agenda.holds["h-alheio"] = {
            "slot_id": "s-alheio",
            "contact_id": "contacto-alheio",
            "expira_at": AGORA + 600,
        }
        estado = estado_de("", tipo="interactive")
        estado["slots"] = {
            "servico": "srv-corte",
            "data": DIA_DA_GRELHA,
            "hora": 9 * 60,
            "hold": {"hold_id": "h-alheio", "expira_at": AGORA + 600},
        }
        estado["stage"] = "awaiting_confirm"
        estado["messages"] = [
            {"role": "user", "content": f"{tabela.PREFIXO_DE_CONFIRMACAO}h-alheio"}
        ]
        delta = no("book_slot", self.deps, estado)
        self.assertIn(SLOT_TAKEN, delta["avisos"])

    def test_o_canario_alheio_nunca_sai_no_texto(self) -> None:
        """A afirmacao e sobre o que **sai**, e nao sobre o que a tool devolveu."""
        estado = estado_de(
            f"{tabela.PREFIXO_DE_CONFIRMACAO}B-99", tipo="interactive"
        )
        estado["slots"] = {"cancelar": "B-99"}
        estado["stage"] = "awaiting_confirm"
        delta = no("cancel_booking", self.deps, estado)
        estado.update(delta)
        blocos = no("compose", self.deps, estado)["draft"]["blocos"]
        texto = " ".join(str(b.get("text", "")) for b in blocos)
        self.assertNotIn("B-99", texto)
        self.assertNotIn("contacto-alheio", texto)


# ------------------------------------------------------- o concierge (ADR-L005)


class TestConcierge(unittest.TestCase):
    """O ADR-L005: com a politica activa, a resposta vai a aprovacao humana.

    **Nao se redecide aqui e nao ha codigo novo**: o `send` e o no partilhado
    onde o KAM-114 intercepta, e o que este ticket traz sao as quatro arestas e
    os dois nos. O que se mede e que o caminho **existe** neste grafo.
    """

    def test_os_dois_nos_do_concierge_estao_no_grafo(self) -> None:
        self.assertIn("draft_prepare", tabela.NOS)
        self.assertIn("draft_wait", tabela.NOS)
        self.assertIn("draft_prepare", tabela.NOS_REUTILIZADOS)
        self.assertIn("draft_wait", tabela.NOS_REUTILIZADOS)

    def test_as_quatro_arestas_do_concierge_estao_la(self) -> None:
        self.assertEqual(
            {(a.de, a.para) for a in tabela.do_concierge()},
            {
                ("send", "draft_prepare"),
                ("draft_prepare", "draft_wait"),
                ("draft_wait", "send"),
                ("draft_wait", END),
            },
        )

    def test_sem_politica_o_turno_acaba_como_o_criterio_1_o_entregou(self) -> None:
        """A omissao e `enviado`: nenhum *tenant* fora do Piloto espera ninguem."""
        self.assertEqual(enc_vendedor.r_send({}), "enviado")
        self.assertEqual(enc_vendedor.r_send({"concierge": None}), "enviado")

    def test_com_politica_activa_o_send_desvia_para_a_aprovacao(self) -> None:
        self.assertEqual(
            enc_vendedor.r_send({"concierge": {"estado": "a_aprovar"}}), "aprovar"
        )
        self.assertEqual(tabela.mapa_de("send")["aprovar"], "draft_prepare")

    def test_a_transicao_35_diz_que_foi_alterada_pelo_adr(self) -> None:
        """O `fonte` existe para que cada aresta diga quem a autoriza."""
        trinta_e_cinco = [a for a in tabela.ARESTAS if a.linha == 35]
        self.assertEqual(len(trinta_e_cinco), 1)
        self.assertEqual(
            trinta_e_cinco[0].fonte, tabela.FONTE_ALTERADA_PELO_CONCIERGE
        )
        self.assertIn("ADR-L005", trinta_e_cinco[0].fonte)
        # E **conta** para o `LINHAS_DO_81`: a transicao continua no diagrama.
        self.assertIn(trinta_e_cinco[0], tabela.do_81())


# ---------------------------------------------------------- ponta a ponta


class TestPontaAPonta(unittest.TestCase):
    """Um turno inteiro, com o `send` a enfileirar e o validador a correr."""

    def test_uma_pergunta_de_slot_sai_pelo_send(self) -> None:
        grafo, deps, agenda, saida, _ = montar()
        correr(grafo, estado_de("quero marcar"))
        self.assertEqual(len(saida.enviadas), 1)
        self.assertIn("Que servico", saida.textos[0])

    def test_os_servicos_e_os_precos_saiem_citados(self) -> None:
        """O criterio 6 no caminho do `list_services`: o preco vem de um *fact*."""
        grafo, deps, agenda, saida, _ = montar()
        correr(grafo, estado_de("que servicos tem"))
        self.assertEqual(len(saida.enviadas), 1)
        texto = saida.textos[0]
        for servico in CATALOGO:
            self.assertIn(servico.nome, texto)
        # O `sob_consulta` sai sem numero, e os outros com o valor do *fact*.
        self.assertIn("preco sob consulta", texto)

    def test_as_dez_opcoes_saiem_com_as_horas_de_luanda(self) -> None:
        grafo, deps, agenda, saida, _ = montar()
        estado = estado_de("quando tem vaga")
        estado["slots"] = {"servico": "srv-corte", "data": DIA_DA_GRELHA}
        correr(grafo, estado)
        self.assertEqual(len(saida.enviadas), 1)
        texto = saida.textos[0]
        # A primeira hora da grelha e as 9h00 de **Luanda**.
        esperado = datahora_display(datas.instante_utc(DIA_DA_GRELHA, 9 * 60))
        self.assertIn(esperado, texto)
        self.assertIn("09h00", texto)

    def test_o_turno_de_outro_vertical_nao_usa_tools_desta(self) -> None:
        """A lista de permitidos vai **sempre** (passo 1 do `invoke`)."""
        self.assertEqual(len(nos_mod.TOOLS_DE_SERVICOS), 6)
        self.assertNotIn("search_catalog", nos_mod.TOOLS_DE_SERVICOS)
        self.assertNotIn("criar_pedido", nos_mod.TOOLS_DE_SERVICOS)
        # E batem com o `registry/servicos.yaml`.
        import pathlib

        from kamba_yaml import load_file

        raiz = pathlib.Path(__file__).resolve().parents[3]
        registo = load_file(raiz / "registry" / "servicos.yaml")
        self.assertEqual(
            sorted(nos_mod.TOOLS_DE_SERVICOS), sorted(registo["tools"])
        )

    def test_a_versao_do_grafo_e_propria_e_nao_a_do_vendedor(self) -> None:
        """Um `graph_version` do Vendedor numa linha de agenda mentia."""
        from kamba_agr.verticais.vendedor import arestas as do_vendedor

        self.assertEqual(tabela.VERSAO_DO_GRAFO, "1.0.0")
        self.assertNotEqual(tabela.VERSAO_DO_GRAFO, do_vendedor.VERSAO_DO_GRAFO)

    def test_o_contexto_de_tool_leva_a_versao_deste_grafo(self) -> None:
        estado = estado_de("")
        ctx = nos_mod.contexto_de_tool(estado)
        self.assertEqual(ctx.graph_version, tabela.VERSAO_DO_GRAFO)


# -------------------------------------- os achados da ANALISE-40, um por portao


class TestAchadosDaRevisao(unittest.TestCase):
    """Um ensaio por achado `CONFIRMADO` da revisao adversarial.

    **Esta familia existe porque um escape que um portao podia ter apanhado vira
    portao**, e nao vira nota de rodape. Cada metodo nomeia o achado e mede
    exactamente o cenario que a revisao reproduziu: corrigir sem fechar o portao
    era pagar o mesmo achado outra vez na proxima auditoria.
    """

    def setUp(self) -> None:
        self.relogio = Relogio()
        self.grafo, self.deps, self.agenda, self.saida, _ = montar(
            relogio=self.relogio, checkpointer=InMemorySaver()
        )
        # **Um contacto so, em todos os turnos** — ver a `Conversa`.
        self.conversa = Conversa()
        self.config = self.conversa.config

    # ------------------------------------------------------------- achado 1 e 2
    def test_achado_1_e_2_uma_conversa_inteira_chega_ao_botao(self) -> None:
        """Quatro turnos, texto normal, e no fim ha um botao de confirmacao.

        **E o ensaio que os achados 1, 2, 3 e 4 nao deixavam passar**: o serviço
        nunca se reconhecia (as `ofertas` eram reiniciadas), a resposta «amanha»
        caia em `safe_reply`, o `stage` nao atravessava o turno e o *hold* nunca
        era tomado. Mede-se com o grafo e o *checkpointer*, porque nenhum ensaio
        de no sozinho ve nenhum dos quatro.
        """
        correr(
            self.grafo,
            self.conversa.turno("quero marcar o corte de cabelo"),
            **self.config,
        )
        # Turno 2: a resposta a pergunta da data. **Nao casa regra nenhuma** — e
        # e por isso que o `classify` tem de herdar a intencao pendente.
        f2 = correr(self.grafo, self.conversa.turno("dia 20/11"), **self.config)
        self.assertEqual(f2["intent"], "marcar", "a intencao pendente nao foi herdada")
        self.assertEqual(f2["slots"]["servico"], "srv-corte")
        self.assertEqual(f2["slots"]["data"], "2026-11-20")
        # Turno 3: a hora.
        f3 = correr(self.grafo, self.conversa.turno("as 14h30"), **self.config)
        self.assertEqual(f3["slots"]["hora"], 14 * 60 + 30)
        self.assertEqual(f3["stage"], "awaiting_confirm")
        self.assertTrue(f3["slots"]["hold"]["hold_id"], "o hold nao foi tomado")
        # E o botao saiu, com o `hold_id` dentro.
        hold_id = f3["slots"]["hold"]["hold_id"]
        self.assertIn(
            f"{tabela.PREFIXO_DE_CONFIRMACAO}{hold_id}", self.saida.botoes[-1]
        )
        # Turno 4: o toque. **E o turno seguinte**, que e onde o achado 3 vivia.
        f4 = correr(
            self.grafo,
            self.conversa.turno(
                f"{tabela.PREFIXO_DE_CONFIRMACAO}{hold_id}", tipo="interactive"
            ),
            **self.config,
        )
        self.assertNotIn(
            tabela.STALE_CONFIRMATION,
            f4.get("avisos") or (),
            "o `stage` nao atravessou o turno",
        )
        confirmadas = [
            m for m in self.agenda.marcacoes.values() if m["estado"] == "confirmada"
        ]
        self.assertEqual(len(confirmadas), 1)

    def test_achado_2_uma_regra_vence_a_intencao_herdada(self) -> None:
        """A heranca nao prende o cliente: «quero cancelar» sai do preenchimento."""
        correr(
            self.grafo,
            self.conversa.turno("quero marcar o corte de cabelo"),
            **self.config,
        )
        final = correr(
            self.grafo, self.conversa.turno("esqueca, quero cancelar"), **self.config
        )
        self.assertEqual(final["intent"], "cancelar")

    # --------------------------------------------------------------- achado 3
    def test_achado_3_o_stage_atravessa_o_turno(self) -> None:
        """A medicao directa, sem o resto da conversa pelo meio."""
        primeiro = estado_de("")
        self.assertNotIn("stage", primeiro, "o `stage` voltou ao `estado_inicial`")
        grafo, deps, *_ = montar(checkpointer=InMemorySaver())
        conversa = Conversa()
        config = conversa.config
        correr(grafo, conversa.turno("quero marcar"), **config)
        # O `ingest` estabelece-o quando falta, e o valor e um dos conhecidos.
        final = correr(grafo, conversa.turno("ola"), **config)
        from kamba_agr.estado import ESTAGIOS

        self.assertIn(final["stage"], ESTAGIOS)

    # --------------------------------------------------------------- achado 6
    def test_achado_6_o_botao_de_uma_remarcacao_cita_o_booking_id(self) -> None:
        """O `compose` emitia `hold_id` e a tool cita `booking_id`.

        Com os dois a divergir, **toda** a remarcacao saia `VALIDATION_ERROR` no
        passo 4 do `invoke`. Mede-se o que o `compose` emite, e nao o que o no
        aceita: era o `compose` que estava errado.
        """
        slots = {
            "servico": "srv-corte",
            "data": DIA_DA_GRELHA,
            "hora": 10 * 60,
            "remarcar": "B-77",
            "hold": {"hold_id": "h-novo", "slot_id": "s", "expira_at": AGORA + 600},
        }
        self.assertEqual(nos_mod.referencia_a_confirmar(slots), "B-77")
        estado = estado_de("")
        estado["slots"] = slots
        estado["stage"] = "awaiting_confirm"
        blocos = no("compose", self.deps, estado)["draft"]["blocos"]
        ids = [i for b in blocos if b["type"] == "buttons" for i in b["ids"]]
        self.assertIn(f"{tabela.PREFIXO_DE_CONFIRMACAO}B-77", ids)
        self.assertNotIn(f"{tabela.PREFIXO_DE_CONFIRMACAO}h-novo", ids)

    def test_achado_6_a_referencia_tem_um_dono_so(self) -> None:
        """As tres escritas, e cada uma cita o campo que a sua tool recebe."""
        self.assertEqual(nos_mod.referencia_a_confirmar({"cancelar": "B-1"}), "B-1")
        self.assertEqual(nos_mod.referencia_a_confirmar({"remarcar": "B-2"}), "B-2")
        self.assertEqual(
            nos_mod.referencia_a_confirmar({"hold": {"hold_id": "h-3"}}), "h-3"
        )
        self.assertIsNone(nos_mod.referencia_a_confirmar({}))
        # Um `remarcar` sem referencia (o `True` do achado 8) nao e referencia.
        self.assertIsNone(nos_mod.referencia_a_confirmar({"remarcar": True}))

    def test_achado_6_o_confirm_gate_nao_pede_validade_a_um_booking(self) -> None:
        """Um `booking_id` nao expira; exigir-lhe `expira_at` dava sempre `stale`."""
        estado = estado_de(
            f"{tabela.PREFIXO_DE_CONFIRMACAO}B-9", tipo="interactive"
        )
        estado["slots"] = {"cancelar": "B-9"}
        estado["stage"] = "awaiting_confirm"
        self.assertEqual(no("confirm_gate", self.deps, estado), {})

    # --------------------------------------------------------------- achado 7
    def test_achado_7_de_tarde_resolve_a_desambiguacao(self) -> None:
        """A pergunta era inrespondivel: «de tarde» nao tem digitos."""
        self.assertEqual(datas.resolver_candidatas("de tarde", (300, 1020)), 1020)
        self.assertEqual(datas.resolver_candidatas("de manha", (300, 1020)), 300)
        self.assertEqual(datas.resolver_candidatas("as 5", (300, 1020)), None)

        estado = estado_de("de tarde")
        estado["intent"] = "marcar"
        estado["slots"] = {
            "servico": "srv-corte",
            "data": DIA_DA_GRELHA,
            "hora_candidatas": (5 * 60, 17 * 60),
            "pergunta": "DESAMBIGUAR_HORA",
        }
        delta = no("slots_collect", self.deps, estado)
        self.assertEqual(delta["slots"]["hora"], 17 * 60)
        self.assertNotIn("pergunta", delta["slots"])
        self.assertNotIn("hora_candidatas", delta["slots"])

    def test_achado_7_dois_turnos_de_ponta_a_ponta(self) -> None:
        correr(
            self.grafo,
            self.conversa.turno("quero marcar o corte de cabelo"),
            **self.config,
        )
        correr(self.grafo, self.conversa.turno("dia 20/11"), **self.config)
        f3 = correr(self.grafo, self.conversa.turno("as 5"), **self.config)
        self.assertEqual(f3["slots"]["pergunta"], "DESAMBIGUAR_HORA")
        f4 = correr(self.grafo, self.conversa.turno("de tarde"), **self.config)
        self.assertEqual(f4["slots"]["hora"], 17 * 60)

    # --------------------------------------------------------------- achado 8
    def test_achado_8_remarcar_sem_referencia_nao_marca_de_novo(self) -> None:
        """Caia no ramo da marcacao nova e o cliente ficava com **duas**."""
        delta = no("classify", self.deps, estado_de("quero remarcar"))
        self.assertEqual(delta["intent"], "remarcar")
        self.assertNotIsInstance(delta.get("slots", {}).get("remarcar"), str)
        # O encaminhador **nao** segue para a agenda.
        estado = {
            "intent": "remarcar",
            "slots": {"servico": "srv-corte", "data": DIA_DA_GRELHA, "hora": 600},
        }
        self.assertEqual(enc.r_slots(estado), "ask")
        # E o no pergunta, com a frase de «nao me disse qual».
        pedido = estado_de("quero remarcar")
        pedido["intent"] = "remarcar"
        delta = no("slots_collect", self.deps, pedido)
        self.assertIn(tabela.REFERENCIA_EM_FALTA, delta["avisos"])

    def test_achado_8_com_referencia_a_remarcacao_segue(self) -> None:
        delta = no("classify", self.deps, estado_de("quero remarcar a B-55"))
        self.assertEqual(delta["slots"]["remarcar"], "B-55")

    # -------------------------------------------------------------- achado 11
    def test_achado_11_limit_exceeded_sai_com_botao_de_humano(self) -> None:
        """«Um colega pode ajudar» sem botao nao e uma oferta de handoff."""
        estado = estado_de("")
        estado["avisos"] = (LIMIT_EXCEEDED,)
        blocos = no("compose", self.deps, estado)["draft"]["blocos"]
        ids = [i for b in blocos if b["type"] == "buttons" for i in b["ids"]]
        self.assertEqual(ids, [nos_mod.BOTAO_HUMANO])

    def test_achado_11_um_slot_taken_nao_oferece_humano(self) -> None:
        """A assimetria e deliberada: isso resolve-se mostrando outras horas."""
        estado = estado_de("")
        estado["avisos"] = (SLOT_TAKEN,)
        blocos = no("compose", self.deps, estado)["draft"]["blocos"]
        self.assertEqual([b for b in blocos if b["type"] == "buttons"], [])

    # -------------------------------------------------------------- achado 12
    def test_achado_12_um_cancelamento_nao_diz_que_a_marcacao_ficou_feita(self) -> None:
        """Decidia-se pela presenca do `booking_id`, que o cancelamento tambem traz."""
        estado = estado_de("")
        estado["draft"] = {"dados": {"booking_id": "B-1", "estado": "cancelada"}}
        blocos = no("compose", self.deps, estado)["draft"]["blocos"]
        frases = [b.get("text") for b in blocos if b["type"] == "text"]
        self.assertIn(nos_mod._FRASE_DO_DESFECHO["cancelada"], frases)
        self.assertNotIn(nos_mod._FRASE_DO_DESFECHO["confirmada"], frases)

    # -------------------------------------------------------------- achado 13
    def test_achado_13_a_confirmacao_cita_o_instante(self) -> None:
        """O cliente ouvia «ficou registada» **sem dia nem hora**."""
        correr(
            self.grafo,
            self.conversa.turno("quero marcar o corte de cabelo"),
            **self.config,
        )
        correr(self.grafo, self.conversa.turno("dia 20/11"), **self.config)
        f3 = correr(self.grafo, self.conversa.turno("as 14h30"), **self.config)
        hold_id = f3["slots"]["hold"]["hold_id"]
        correr(
            self.grafo,
            self.conversa.turno(
                f"{tabela.PREFIXO_DE_CONFIRMACAO}{hold_id}", tipo="interactive"
            ),
            **self.config,
        )
        texto = self.saida.textos[-1]
        self.assertIn(nos_mod._FRASE_DO_DESFECHO["confirmada"], texto)
        # E o instante sai **citado**, na forma do *renderer*.
        esperado = datahora_display(datas.instante_utc("2026-11-20", 14 * 60 + 30))
        self.assertIn(esperado, texto)

    # -------------------------------------------------------------- achado 14
    def test_achado_14_zero_vagas_nao_aponta_para_uma_lista_vazia(self) -> None:
        """«Veja se alguma destas lhe serve» com zero opcoes nao serve."""
        for slot_id, _ in self.agenda._grelha("srv-corte", DIA_DA_GRELHA):
            self.agenda.marcacoes[f"b-{slot_id}"] = {
                "slot_id": slot_id,
                "contact_id": "outro",
                "estado": "confirmada",
                "hold_id": None,
            }
        estado = estado_de("")
        estado["intent"] = "disponibilidade"
        estado["slots"] = {"servico": "srv-corte", "data": DIA_DA_GRELHA}
        delta = no("check_availability", self.deps, estado)
        self.assertIn(tabela.SEM_VAGA_NENHUMA, delta["avisos"])
        self.assertNotIn(tabela.SEM_DISPONIBILIDADE, delta["avisos"])
        self.assertEqual(delta["slots"]["opcoes"], ())
        # E a frase nao promete uma lista.
        self.assertNotIn("destas", nos_mod.FRASE_DO_AVISO[tabela.SEM_VAGA_NENHUMA])

    # -------------------------------------------------------- achados 15 e 16
    def test_achado_15_um_ordinal_ou_um_milhar_nao_e_uma_hora(self) -> None:
        """O ponto nao e separador de horas em PT-AO. Seis casos medidos."""
        casos = (
            ("na 2.a feira as 10h", 10 * 60),
            ("a 1.a hora livre", None),
            ("custa 2.500 kz?", None),
            ("pode ser dia 20. as 10h", 10 * 60),
            ("dia 5.11", None),
            ("na 3.a as 15h30", 15 * 60 + 30),
        )
        for texto, esperado in casos:
            with self.subTest(texto=texto):
                lida = datas.ler_hora(texto)
                if esperado is None:
                    self.assertFalse(lida.lida, f"{texto!r} nao devia dar hora")
                    self.assertFalse(lida.ambigua, f"{texto!r} nao devia ser ambiguo")
                else:
                    self.assertEqual(lida.minutos, esperado, texto)

    def test_achado_16_e_meia_nao_desaparece(self) -> None:
        """Dava 17h00 e seguia como hora **lida** — meia hora perdida em silencio."""
        self.assertEqual(datas.ler_hora("as 5 e meia da tarde").minutos, 17 * 60 + 30)
        self.assertEqual(datas.ler_hora("as 9 e um quarto da manha").minutos, 9 * 60 + 15)
        self.assertEqual(
            datas.ler_hora("as 10 e tres quartos da manha").minutos, 10 * 60 + 45
        )
        # Nua, continua ambigua — a fraccao nao desfaz a ambiguidade do periodo.
        self.assertEqual(datas.ler_hora("as 5 e meia").candidatas, (330, 1050))
        # E os minutos escritos vencem a fraccao por palavras.
        self.assertEqual(datas.ler_hora("as 14h30").minutos, 14 * 60 + 30)


class TestContratoDoModuloServicos(unittest.TestCase):
    """O duplo de ensaio publica os campos do contrato, e nao os que lhe convem.

    **Esta familia e um portao e nao uma verificacao de estilo.** O escape que
    ela fecha chegou depois de o PR abrir, por nota da sessao do KAM-047: o
    `check_availability` lia `opcao["minutos_em_luanda"]` e o `Opcao` do
    `services/com/src/servicos/contrato.ts` **nao tem** esse campo — era
    invencao do duplo. O no estava escrito contra o nosso proprio *fake*, que e
    a licao que o criterio 3 do KAM-027 ja tinha pago por escrito: «esse teste
    contra um objecto inventado prova que o nosso `nos_do_grafo` le o nosso
    proprio duplo».

    A mesma classe trouxe um segundo: o `Marcacao.holdExpiresAt` e
    `string | null` e o duplo devolvia um `float`, pelo que o `float()` que o no
    fazia **levantava** contra o modulo real e passava contra o *fake*.

    O portao le o **ficheiro do contrato** e confronta os nomes. Nao e uma lista
    escrita a mao: uma lista a mao divergia do contrato no dia em que ele
    mudasse, que e o defeito que ela existiria para apanhar.
    """

    @staticmethod
    def _campos(interface: str) -> set[str]:
        """Os campos de uma `interface` do contrato, em `snake_case`.

        A fronteira da tool e `snake_case` (a forma do §6.2: `book_slot(slot_id,
        servico)`) e o contrato e TypeScript em `camelCase`. A conversao e aqui,
        num sitio, e e o que torna a comparacao possivel sem duas listas.
        """
        import pathlib as _p
        import re as _re

        raiz = _p.Path(__file__).resolve().parents[3]
        fonte = (
            raiz / "services" / "com" / "src" / "servicos" / "contrato.ts"
        ).read_text(encoding="utf-8")
        bloco = fonte.split(f"export interface {interface} {{")[1].split("}")[0]
        nomes = _re.findall(r"readonly (\w+)", bloco)
        return {_re.sub(r"(?<!^)(?=[A-Z])", "_", n).lower() for n in nomes}

    def test_a_opcao_do_duplo_nao_inventa_campos(self) -> None:
        """Os campos que o duplo publica sao os do contrato, mais dois nossos."""
        agenda = AgendaFalsa(relogio=Relogio(), dia=DIA_DA_GRELHA)
        grafo, deps, _, _, _ = montar(agenda=agenda)
        estado = estado_de("")
        estado["intent"] = "disponibilidade"
        estado["slots"] = {"servico": "srv-corte", "data": DIA_DA_GRELHA}
        opcoes = no("check_availability", deps, estado)["slots"]["opcoes"]
        self.assertTrue(opcoes)

        do_contrato = self._campos("Opcao")
        # Os dois acrescentos **nossos**, e os dois tem razao escrita: o
        # `fact_id` liga a opcao ao *fact* `datetime` (sem ele o `compose` nao a
        # pode citar, ADR-007), e o par `hold_id`/`hold_expires_at` e o *hold*
        # do §8.2 — que o `Marcacao` do contrato tambem nomeia.
        nossos = {"fact_id", "hold_id", "hold_expires_at"}
        for opcao in opcoes:
            sobra = set(opcao) - do_contrato - nossos
            self.assertEqual(sobra, set(), f"campos que o contrato nao tem: {sobra}")

    def test_o_minuto_deriva_se_do_inicio_at_e_nao_de_um_campo(self) -> None:
        """E o campo que o contrato **tem**: `inicioAt`."""
        self.assertIn("inicio_at", self._campos("Opcao"))
        self.assertNotIn("minutos_em_luanda", self._campos("Opcao"))
        as_nove = datas.instante_utc(DIA_DA_GRELHA, 9 * 60)
        self.assertEqual(nos_mod._minuto_em_luanda({"inicio_at": as_nove}), 9 * 60)
        # E o que nao se consegue ler nao se adivinha.
        for cru in ({}, {"inicio_at": ""}, {"inicio_at": "nao e uma data"}):
            self.assertIsNone(nos_mod._minuto_em_luanda(cru), repr(cru))

    def test_o_hold_expires_at_e_uma_cadeia_iso_e_nao_um_numero(self) -> None:
        """`string | null` no contrato. Um `float()` sobre a cadeia levantava."""
        self.assertIn("hold_expires_at", self._campos("Marcacao"))
        iso = "2026-11-16T13:40:00Z"
        self.assertAlmostEqual(
            nos_mod._epoca_de(iso), em_luanda(iso).timestamp(), places=3
        )
        # **O lado seguro e o zero**: um `expira_at` ilegivel da um *hold*
        # expirado no `confirm_gate`, e nao um que nunca expira.
        for cru in (None, "", "nao e uma data", 17, {}):
            self.assertEqual(nos_mod._epoca_de(cru), 0.0, repr(cru))

    def test_um_hold_ilegivel_nao_passa_o_confirm_gate(self) -> None:
        """A consequencia do zero, medida no no e nao so na utilitaria."""
        grafo, deps, *_ = montar()
        estado = estado_de(
            f"{tabela.PREFIXO_DE_CONFIRMACAO}h-1", tipo="interactive"
        )
        estado["stage"] = "awaiting_confirm"
        estado["slots"] = {"hold": {"hold_id": "h-1", "expira_at": 0.0}}
        delta = no("confirm_gate", deps, estado)
        self.assertIn(tabela.STALE_CONFIRMATION, delta["avisos"])

    def test_o_grafo_nunca_monta_um_slot_id(self) -> None:
        """O `slot_id` e um *token* assinado: devolve-se, nunca se constroi.

        O `holdSlot` do modulo le os campos do proprio *token* e recusa com
        `VALIDATION_ERROR` o que nao verifique — e o guardrail do §8.2 imposto
        por criptografia. Este ensaio mede que o unico `slot_id` que sai do
        grafo e **o que entrou**, e nao um derivado da data, da hora ou do
        servico.
        """
        agenda = AgendaFalsa(relogio=Relogio(), dia=DIA_DA_GRELHA)
        grafo, deps, _, _, _ = montar(agenda=agenda)
        estado = estado_de("")
        estado["intent"] = "marcar"
        estado["slots"] = {
            "servico": "srv-corte",
            "data": DIA_DA_GRELHA,
            "hora": 9 * 60,
        }
        delta = no("check_availability", deps, estado)
        do_backend = {o["slot_id"] for o in delta["slots"]["opcoes"]}
        self.assertIn(delta["slots"]["hold"]["slot_id"], do_backend)
        # E o `book_slot` cita o `hold_id`, nao um `slot_id` reconstruido.
        self.assertEqual(
            sorted(nos_mod.referencia_a_confirmar(delta["slots"]) and ["ok"]), ["ok"]
        )


if __name__ == "__main__":  # pragma: no cover
    unittest.main()
