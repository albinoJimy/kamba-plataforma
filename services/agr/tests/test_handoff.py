"""O *handoff* idempotente e a retoma por *compare-and-set* (KAM-034).

Oito criterios, e cada classe desta bateria mede um. O que **nao** esta aqui
esta em `db/tests_agr/test_handoff_retoma.py`: o SQL contra PostgreSQL a serio —
a atomicidade do CAS, a RLS a esconder a passagem de outro *tenant*, o vinculo
ao *thread* pelo `contact_id`, e a varredura dos prazos sobre `timestamptz`.

**A `BaseFalsa` deste ficheiro compara SQL por identidade e nao o interpreta**, e
isso e uma limitacao declarada e nao um descuido: e a mesma que o
`consultas.py` escreve no seu cabecalho («uma base falsa compara SQL por texto e
nunca o interpreta — um erro de sintaxe passava o *gate* 4 inteiro»). O que ela
prova e a **orquestracao** — a ordem das escritas, a compensacao, a
classificacao do zero linhas, a concorrencia — e nao o SQL. Por isso compara as
cadeias com as constantes do `consultas.py` por `is`: uma copia no teste
divergia da constante sem ninguem notar, e o ensaio passava a medir a copia.
"""

from __future__ import annotations

import asyncio
import unittest
import uuid

from kamba_agr import consultas
from kamba_agr.admissao import Admissao
from kamba_agr.contexto import thread_id_de
from kamba_agr.handoff import maquina
from kamba_agr.handoff.autenticacao import (
    CABECALHO_DO_BOT,
    MOTIVOS_DE_RECUSA,
    avaliar,
    tenant_do_thread,
    verificador,
)
from kamba_agr.handoff.portas import HandoffIndisponivel
from kamba_agr.handoff.prazos import PRAZO_SEGUNDOS, Prazos
from kamba_agr.handoff.retoma import (
    DESFECHOS_DA_RETOMA,
    GrafoDaRetomaError,
    Retomador,
    ReversaoFalhadaError,
    ThreadInvalidoError,
)
from kamba_agr.handoff.servico import (
    MOTIVO_DA_PAUSA,
    ProvedorPorLigar,
    ServicoDeHandoff,
)
from kamba_agr.metricas import (
    METRICA_HANDOFF,
    METRICA_HANDOFF_DEGRADADO,
    METRICA_RETOMA,
    METRICAS,
    MetricasDoAgr,
)
from kamba_agr.turno import ExecutorDeTurnos, GrafoNaoRegistadoError, Palavra
from kamba_agr.verticais.vendedor import nos as nos_mod

from apoio import CREDENCIAL, Relogio, TrancaFalsa, invocacao_crua

TENANT = str(uuid.UUID(int=1))
CONTACTO = str(uuid.UUID(int=2))
CONVERSA = str(uuid.UUID(int=3))
THREAD = thread_id_de(TENANT, CONTACTO)
#: Um UUID **com letras**, para os casos que medem a forma canonica. Os de
#: `uuid.UUID(int=N)` so tem digitos e hifenes, pelo que `.upper()` neles e uma
#: operacao vazia — e um ensaio de maiusculas sobre um deles media o caminho
#: feliz a dizer que media o malformado.
_COM_LETRAS = str(uuid.UUID(int=0xABCDEF0123456789ABCDEF0123456789))

#: Um instante de parede plausivel (2023-11-14), e **nao** o `1000.0` por
#: omissao do `Relogio`: menos de 24 h depois da epoca da-lo negativo, e o
#: `datetime.fromtimestamp` de um negativo levanta `OSError` no Windows. Um
#: ensaio de prazos tem de correr num relogio que exista.
_AGORA = 1_700_000_000.0


# --------------------------------------------------------------- a maquina


class TestMaquina(unittest.TestCase):
    """Criterio 8: `waiting -> resumed | timeout | cancelled | degraded`."""

    def test_os_cinco_estados_sao_os_do_check_da_revisao_0011(self) -> None:
        """Le a **migracao** e nao uma copia: o `CHECK` e a fonte.

        Sem isto, as duas listas divergiam e o codigo escrevia um `status` que a
        base recusa com `23514` — um 500 em producao e nenhum teste vermelho.
        """
        import ast
        from pathlib import Path

        raiz = Path(__file__).resolve().parents[3]
        fonte = (
            raiz / "db" / "migrations" / "versions" / "0011_handoff.py"
        ).read_text(encoding="utf-8")
        arvore = ast.parse(fonte)
        encontrados: tuple[str, ...] | None = None
        for no in ast.walk(arvore):
            if (
                isinstance(no, ast.Assign)
                and any(
                    isinstance(alvo, ast.Name) and alvo.id == "ESTADOS_DE_HANDOFF"
                    for alvo in no.targets
                )
                and isinstance(no.value, ast.Tuple)
            ):
                encontrados = tuple(
                    item.value.strip("'")
                    for item in no.value.elts
                    if isinstance(item, ast.Constant)
                )
        self.assertIsNotNone(encontrados, "o `ESTADOS_DE_HANDOFF` da 0011 mudou de forma")
        self.assertEqual(set(encontrados), set(maquina.ESTADOS))

    def test_o_mapa_de_desfechos_bate_nos_dois_sentidos(self) -> None:
        self.assertEqual(set(maquina.ESTADO_DO_DESFECHO), set(maquina.DESFECHOS))
        self.assertLessEqual(
            set(maquina.ESTADO_DO_DESFECHO.values()), set(maquina.ESTADOS)
        )

    def test_os_tres_desfechos_sao_os_do_dicionario(self) -> None:
        self.assertEqual(maquina.DESFECHOS, ("resolved", "timeout", "cancelled"))
        self.assertEqual(maquina.estado_do_desfecho("resolved"), "resumed")
        self.assertEqual(maquina.estado_do_desfecho("timeout"), "timeout")
        self.assertEqual(maquina.estado_do_desfecho("cancelled"), "cancelled")

    def test_um_desfecho_desconhecido_levanta_em_vez_de_cair_num_estado(self) -> None:
        for mau in ("resumed", "degraded", "waiting", "", "RESOLVED", "resolvido"):
            with self.subTest(desfecho=mau):
                with self.assertRaises(maquina.DesfechoInvalidoError):
                    maquina.estado_do_desfecho(mau)

    def test_so_se_retoma_de_waiting(self) -> None:
        self.assertTrue(maquina.pode_retomar("waiting"))
        for estado in ("resumed", "timeout", "cancelled", "degraded"):
            with self.subTest(estado=estado):
                self.assertFalse(maquina.pode_retomar(estado))


# ------------------------------------------------------- o servico e o grafo


class ProvedorFalso:
    """Conta as aberturas por `handoff_id`, como o `ON CONFLICT` do HND.

    **Conta chaves distintas e nao chamadas**, que e o que «1 conversa no HND»
    quer dizer: o `SQL_ABRIR_HANDOFF` com `ON CONFLICT (handoff_id) DO NOTHING`
    aceita a quinta chamada e nao cria a quinta linha.
    """

    def __init__(self, falha: bool = False) -> None:
        self.chamadas: list[dict] = []
        self.conversas: dict[str, str] = {}
        self.falha = falha

    def abrir(self, **argumentos) -> str:
        self.chamadas.append(argumentos)
        if self.falha:
            raise HandoffIndisponivel("provedor_em_baixo")
        hid = argumentos["handoff_id"]
        self.conversas.setdefault(hid, f"cw-{len(self.conversas) + 1}")
        return self.conversas[hid]


class ModosFalsos:
    def __init__(self, levanta: bool = False) -> None:
        self.pausadas: list[tuple[str, str, str]] = []
        self.levanta = levanta

    def pausar(self, *, tenant_id: str, conversation_id: str, motivo: str) -> None:
        if self.levanta:
            raise RuntimeError("modos_em_baixo")
        self.pausadas.append((tenant_id, conversation_id, motivo))


class SaidaFalsa:
    """O Outbound, com a de-duplicacao **por chave** que a base dele tem.

    Modela a `UNIQUE (tenant_id, idempotency_key)` de `outbound_messages`
    (revisao `0010`). Sem isso o duplo nao modelava o que substitui, e «1
    mensagem ao cliente» ficava a depender de o no ser chamado uma vez — que e
    exactamente o contrario do que o criterio 1 pede.

    Guarda tambem **todas** as chaves pedidas, em `chaves`: a asserção forte do
    criterio 1 nao e «o Outbound tem uma mensagem» (isso o duplo garantia
    sozinho) e sim «o no pediu sempre a **mesma** chave».
    """

    def __init__(self, falhar_na: int | None = None) -> None:
        self.por_chave: dict[str, str] = {}
        self.chaves: list[str] = []
        self.falhar_na = falhar_na
        self.chamadas = 0

    def enfileirar(self, estado, texto, *, chave, botoes=()) -> None:
        self.chamadas += 1
        if self.falhar_na is not None and self.chamadas == self.falhar_na:
            # **A falha injectada «entre o `openHandoff` e o enfileiramento»**
            # do criterio 1: o provedor ja foi chamado, a mensagem nao foi
            # enfileirada, e o *worker* morre. Levanta-se **antes** de guardar a
            # chave, que e o que o torna uma perda a serio.
            raise RuntimeError("worker_caiu_antes_de_enfileirar")
        self.chaves.append(chave)
        self.por_chave.setdefault(chave, texto)


def estado_de_handoff(**sobrepor):
    base = {
        "thread_id": THREAD,
        "tenant_id": TENANT,
        "contact_id": CONTACTO,
        "conversation_id": CONVERSA,
        "handoff_seq": 0,
        "handoff_motivo": nos_mod.MOTIVO_PEDIDO,
        "intent": "humano",
        "stage": "browsing",
        "messages": [],
    }
    base.update(sobrepor)
    return base


class TestServico(unittest.TestCase):
    def setUp(self) -> None:
        self.metricas = MetricasDoAgr()

    def test_abre_no_provedor_e_devolve_a_referencia(self) -> None:
        provedor = ProvedorFalso()
        servico = ServicoDeHandoff(provedor, metricas=self.metricas)
        referencia = servico.abrir(
            handoff_id="h1",
            tenant_id=TENANT,
            contact_id=CONTACTO,
            conversation_id=CONVERSA,
            motivo=nos_mod.MOTIVO_PEDIDO,
            resumo="motivo=pedido",
        )
        self.assertEqual(referencia, "cw-1")
        self.assertEqual(len(provedor.chamadas), 1)
        self.assertEqual(
            self.metricas.ler().get(f"{METRICA_HANDOFF}:waiting"), 1
        )

    def test_o_provedor_por_ligar_levanta_handoff_indisponivel(self) -> None:
        """E a omissao do servico, e e o estado honesto do sistema hoje."""
        with self.assertRaises(HandoffIndisponivel):
            ServicoDeHandoff(metricas=self.metricas).abrir(
                handoff_id="h1",
                tenant_id=TENANT,
                contact_id=CONTACTO,
                conversation_id=CONVERSA,
                motivo=nos_mod.MOTIVO_PEDIDO,
                resumo="",
            )
        self.assertIsInstance(ProvedorPorLigar(), ProvedorPorLigar)

    def test_com_o_provedor_em_baixo_pausa_a_conversa_e_levanta(self) -> None:
        """Criterio 6, as tres metades do §14 que sao deste lado."""
        modos = ModosFalsos()
        servico = ServicoDeHandoff(
            ProvedorFalso(falha=True), modos=modos, metricas=self.metricas
        )
        with self.assertRaises(HandoffIndisponivel):
            servico.abrir(
                handoff_id="h1",
                tenant_id=TENANT,
                contact_id=CONTACTO,
                conversation_id=CONVERSA,
                motivo=nos_mod.MOTIVO_PEDIDO,
                resumo="",
            )
        self.assertEqual(modos.pausadas, [(TENANT, CONVERSA, MOTIVO_DA_PAUSA)])
        exposicao = self.metricas.ler()
        self.assertEqual(exposicao.get(METRICA_HANDOFF_DEGRADADO), 1)
        self.assertEqual(exposicao.get(f"{METRICA_HANDOFF}:degraded"), 1)
        self.assertIsNone(exposicao.get(f"{METRICA_HANDOFF}:waiting"))

    def test_sem_porta_de_modos_conta_a_degradacao_de_qualquer_maneira(self) -> None:
        """Um `None` silencioso era pior do que a porta nao existir."""
        servico = ServicoDeHandoff(ProvedorFalso(falha=True), metricas=self.metricas)
        with self.assertRaises(HandoffIndisponivel):
            servico.abrir(
                handoff_id="h1",
                tenant_id=TENANT,
                contact_id=CONTACTO,
                conversation_id=CONVERSA,
                motivo=nos_mod.MOTIVO_PEDIDO,
                resumo="",
            )
        self.assertEqual(self.metricas.ler().get(METRICA_HANDOFF_DEGRADADO), 1)

    def test_uma_pausa_que_levanta_substitui_a_excepcao_e_conta_mesmo_assim(
        self,
    ) -> None:
        """Se a pausa levantasse por baixo, o no via `HandoffIndisponivel`.

        E a conversa ficava em `bot` com uma passagem degradada — isto e, o bot
        a responder a uma conversa que pediu um humano. A falha da pausa
        **substitui** a original em vez de ser engolida, e a degradacao conta-se
        antes de se pausar, porque o provedor falhou de qualquer maneira.
        """
        servico = ServicoDeHandoff(
            ProvedorFalso(falha=True),
            modos=ModosFalsos(levanta=True),
            metricas=self.metricas,
        )
        with self.assertRaises(RuntimeError) as capturado:
            servico.abrir(
                handoff_id="h1",
                tenant_id=TENANT,
                contact_id=CONTACTO,
                conversation_id=CONVERSA,
                motivo=nos_mod.MOTIVO_PEDIDO,
                resumo="",
            )
        self.assertNotIsInstance(capturado.exception, HandoffIndisponivel)
        self.assertEqual(self.metricas.ler().get(METRICA_HANDOFF_DEGRADADO), 1)


class TestOServicoSatisfazOGrafo(unittest.IsolatedAsyncioTestCase):
    """O `Protocol` `PortaDeHandoff` do KAM-031, pelo no real e nao por tipos."""

    async def test_o_no_abre_pelo_servico_e_fica_em_waiting(self) -> None:
        provedor = ProvedorFalso()
        saida = SaidaFalsa()
        deps = nos_mod.Dependencias(
            tools=None,
            saida=saida,
            hnd=ServicoDeHandoff(provedor, metricas=MetricasDoAgr()),
        )
        delta = await nos_mod.handoff_prepare(deps)(estado_de_handoff())
        self.assertEqual(delta["handoff"]["status"], "waiting")
        self.assertEqual(delta["handoff"]["external_id"], "cw-1")
        self.assertEqual(delta["handoff_seq"], 1)
        self.assertEqual(len(saida.por_chave), 1)

    async def test_o_provedor_em_baixo_acaba_em_degraded_sem_excepcao(self) -> None:
        """Criterio 6, fim a fim: `HandoffIndisponivel` -> `degraded`.

        Mede-se pelo no real porque e ele que apanha a excepcao, e isso so
        funciona se a classe for a **mesma** — o que a mudanca de casa da
        `HandoffIndisponivel` para o `handoff/portas.py` tinha de preservar.
        """
        modos = ModosFalsos()
        deps = nos_mod.Dependencias(
            tools=None,
            saida=SaidaFalsa(),
            hnd=ServicoDeHandoff(
                ProvedorFalso(falha=True), modos=modos, metricas=MetricasDoAgr()
            ),
        )
        delta = await nos_mod.handoff_prepare(deps)(estado_de_handoff())
        self.assertEqual(delta["handoff"]["status"], "degraded")
        self.assertEqual(delta["draft"]["texto"], nos_mod.MSG_DEGRADADO)
        self.assertEqual(modos.pausadas, [(TENANT, CONVERSA, MOTIVO_DA_PAUSA)])

    async def test_a_classe_apanhada_pelo_no_e_a_do_pacote_handoff(self) -> None:
        from kamba_agr.handoff.portas import HandoffIndisponivel as DoPacote

        self.assertIs(nos_mod.HandoffIndisponivel, DoPacote)


class TestIdempotenciaDoPrepare(unittest.IsolatedAsyncioTestCase):
    """Criterio 1: cinco execucoes, 1 conversa e 1 mensagem."""

    async def test_cinco_execucoes_com_falha_injectada_dao_uma_de_cada(self) -> None:
        provedor = ProvedorFalso()
        # A falha na **segunda** execucao, depois de o provedor ter sido
        # chamado e antes de a mensagem ser enfileirada.
        saida = SaidaFalsa(falhar_na=2)
        deps = nos_mod.Dependencias(
            tools=None,
            saida=saida,
            hnd=ServicoDeHandoff(provedor, metricas=MetricasDoAgr()),
        )
        no = nos_mod.handoff_prepare(deps)
        # **O mesmo estado de entrada nas cinco**, que e o que um *worker* que
        # cai e repete o *job* ve: o `handoff_seq` so sobe no estado que o grafo
        # **aceitou**, e o que falhou nao foi aceite.
        entrada = estado_de_handoff()
        falhas = 0
        for _ in range(5):
            try:
                delta = await no(dict(entrada))
            except RuntimeError as erro:
                self.assertIn("worker_caiu", str(erro))
                falhas += 1
                continue
            self.assertEqual(delta["handoff"]["status"], "waiting")

        self.assertEqual(falhas, 1)
        self.assertEqual(len(provedor.chamadas), 5, "o no foi corrido cinco vezes")
        self.assertEqual(len(provedor.conversas), 1, "1 conversa no HND")
        self.assertEqual(len(saida.por_chave), 1, "1 mensagem ao cliente")

    async def test_as_cinco_execucoes_pedem_sempre_a_mesma_chave(self) -> None:
        """**A asserção que nao depende do duplo.**

        «1 mensagem» com um Outbound que de-duplica por chave passava mesmo que
        o no calculasse chaves diferentes — nao, passava a dar cinco. Mas a
        assercao directa e esta: as chaves pedidas sao todas a mesma, e e dela
        que a idempotencia depende.
        """
        provedor = ProvedorFalso()
        saida = SaidaFalsa()
        deps = nos_mod.Dependencias(
            tools=None,
            saida=saida,
            hnd=ServicoDeHandoff(provedor, metricas=MetricasDoAgr()),
        )
        no = nos_mod.handoff_prepare(deps)
        entrada = estado_de_handoff()
        for _ in range(5):
            await no(dict(entrada))
        self.assertEqual(len(set(saida.chaves)), 1)
        self.assertEqual(len({c["handoff_id"] for c in provedor.chamadas}), 1)
        self.assertTrue(saida.chaves[0].endswith(":msg"))

    async def test_o_handoff_seguinte_tem_outro_identificador_mesmo_depois_de_degradar(
        self,
    ) -> None:
        """**O ramo degradado tambem sobe o `handoff_seq`** (achado 9).

        O `openHandoff` do §11.4 escreve a linha **antes** de falar com o
        provedor, pelo que uma falha do Chatwoot deixa a passagem la com este
        `hid` e a excepcao sobe. Sem o `seq` a subir, o *handoff* seguinte da
        mesma conversa recalculava o **mesmo** identificador e batia nessa
        linha — e a idempotencia por `handoff_id`, que existe para proteger a
        repeticao do mesmo *handoff*, passava a engolir um *handoff* diferente:
        o cliente pedia ajuda outra vez e ninguem era chamado.
        """
        deps_em_baixo = nos_mod.Dependencias(
            tools=None,
            saida=SaidaFalsa(),
            hnd=ServicoDeHandoff(ProvedorFalso(falha=True), metricas=MetricasDoAgr()),
        )
        degradado = await nos_mod.handoff_prepare(deps_em_baixo)(
            estado_de_handoff(handoff_seq=0)
        )
        self.assertEqual(degradado["handoff"]["status"], "degraded")
        self.assertEqual(degradado["handoff_seq"], 1)

        # O provedor volta, e o *handoff* seguinte **nao** reusa a chave.
        provedor = ProvedorFalso()
        deps_de_pe = nos_mod.Dependencias(
            tools=None,
            saida=SaidaFalsa(),
            hnd=ServicoDeHandoff(provedor, metricas=MetricasDoAgr()),
        )
        seguinte = await nos_mod.handoff_prepare(deps_de_pe)(
            estado_de_handoff(handoff_seq=degradado["handoff_seq"])
        )
        self.assertNotEqual(degradado["handoff"]["id"], seguinte["handoff"]["id"])

    async def test_o_hid_do_ramo_degradado_e_estavel_na_repeticao(self) -> None:
        """O outro lado da mesma moeda: **dentro** da repeticao o `hid` nao muda.

        O delta de um no que levanta nao e aceite, e o ramo degradado nao
        levanta — devolve delta. Logo a repeticao do *job* parte do **mesmo**
        estado de entrada e recalcula o mesmo identificador, que e o que o
        criterio 1 pede.
        """
        deps = nos_mod.Dependencias(
            tools=None,
            saida=SaidaFalsa(),
            hnd=ServicoDeHandoff(ProvedorFalso(falha=True), metricas=MetricasDoAgr()),
        )
        no = nos_mod.handoff_prepare(deps)
        entrada = estado_de_handoff(handoff_seq=0)
        vistos = {(await no(dict(entrada)))["handoff"]["id"] for _ in range(5)}
        self.assertEqual(len(vistos), 1)

    async def test_o_handoff_seguinte_da_conversa_tem_outro_identificador(self) -> None:
        """Senao, dois *handoffs* seguidos partilhavam a chave e o segundo era
        engolido pela idempotencia do primeiro."""
        provedor = ProvedorFalso()
        saida = SaidaFalsa()
        deps = nos_mod.Dependencias(
            tools=None,
            saida=saida,
            hnd=ServicoDeHandoff(provedor, metricas=MetricasDoAgr()),
        )
        no = nos_mod.handoff_prepare(deps)
        primeiro = await no(estado_de_handoff(handoff_seq=0))
        segundo = await no(estado_de_handoff(handoff_seq=primeiro["handoff_seq"]))
        self.assertNotEqual(primeiro["handoff"]["id"], segundo["handoff"]["id"])
        self.assertEqual(len(provedor.conversas), 2)
        self.assertEqual(len(saida.por_chave), 2)


# ------------------------------------------------------------------ a retoma


class CursorFalso:
    def __init__(self, base: BaseFalsa) -> None:
        self._base = base
        self._linha = None

    def execute(self, sql, parametros=()) -> None:
        self._linha = self._base.executar(sql, parametros)

    def fetchone(self):
        return self._linha

    def fetchall(self):
        return self._linha or []

    def close(self) -> None:
        pass


class BaseFalsa:
    """As tres instrucoes da retoma, em memoria. Ver o cabecalho do modulo.

    Compara o SQL com as constantes do `consultas.py` por **identidade**: uma
    cadeia que nao seja uma delas levanta, em vez de devolver zero linhas em
    silencio — que e o que tornava um erro de ligacao indistinguivel de um
    *no-op*.
    """

    autocommit = False

    def __init__(self, passagens=None, contactos=None) -> None:
        #: `handoff_id -> {"tenant": ..., "status": ...}`
        self.passagens = dict(passagens or {})
        #: `handoff_id -> contact_id` (o vinculo que o `EXISTS` faz pela conversa)
        self.contactos = dict(contactos or {})
        self.tenant: str | None = None
        self.instrucoes: list = []
        self.confirmadas = 0

    # -- a interface DB-API que o `tenant_guard` usa
    def cursor(self) -> CursorFalso:
        return CursorFalso(self)

    def commit(self) -> None:
        self.confirmadas += 1

    def rollback(self) -> None:
        pass

    def close(self) -> None:
        pass

    def executar(self, sql, parametros):
        from kamba_core.tenant_guard import SQL_DEFINIR_CONTEXTO

        if sql is SQL_DEFINIR_CONTEXTO:
            self.tenant = parametros[0]
            return ("",)
        self.instrucoes.append((sql, parametros))
        if sql is consultas.SQL_RETOMAR_HANDOFF:
            estado_novo, tenant, hid, contacto = parametros
            linha = self.passagens.get(hid)
            if (
                linha is None
                or linha["tenant"] != tenant
                or self.tenant != tenant
                or self.contactos.get(hid) != contacto
                or linha["status"] != "waiting"
            ):
                return None
            linha["status"] = estado_novo
            return (1,)
        if sql is consultas.SQL_HANDOFF_PARA_RETOMA:
            tenant, hid, contacto = parametros
            linha = self.passagens.get(hid)
            if (
                linha is None
                or linha["tenant"] != tenant
                or self.tenant != tenant
                or self.contactos.get(hid) != contacto
            ):
                return None
            return (linha["status"],)
        if sql is consultas.SQL_REVERTER_RETOMA:
            tenant, hid, status = parametros
            linha = self.passagens.get(hid)
            if linha is None or linha["tenant"] != tenant or linha["status"] != status:
                return None
            linha["status"] = "waiting"
            return (1,)
        raise AssertionError(f"instrucao inesperada: {sql[:60]!r}")


class GrafoFalso:
    def __init__(self, levanta=None) -> None:
        self.invocacoes: list = []
        self.levanta = levanta

    async def ainvoke(self, comando, config):
        self.invocacoes.append((comando, config))
        if self.levanta is not None:
            raise self.levanta
        return {}


def retomador(base, grafo=None, metricas=None):
    alvo = GrafoFalso() if grafo is None else grafo
    return (
        Retomador(
            abrir_ligacao=lambda: base,
            grafos=lambda _thread_id: alvo,
            metricas=metricas,
        ),
        alvo,
    )


def uma_passagem(status="waiting"):
    return (
        {"h1": {"tenant": TENANT, "status": status}},
        {"h1": CONTACTO},
    )


class TestRetoma(unittest.IsolatedAsyncioTestCase):
    """Criterio 3: o CAS, o *no-op* do duplicado, e a recusa."""

    async def test_a_retoma_vence_o_cas_e_entrega_o_command_ao_grafo(self) -> None:
        passagens, contactos = uma_passagem()
        base = BaseFalsa(passagens, contactos)
        metricas = MetricasDoAgr()
        alvo, grafo = retomador(base, metricas=metricas)
        self.assertEqual(await alvo.retomar(THREAD, "h1", "resolved"), "retomado")
        self.assertEqual(base.passagens["h1"]["status"], "resumed")
        self.assertEqual(len(grafo.invocacoes), 1)
        comando, config = grafo.invocacoes[0]
        # **O desfecho atravessa sem traducao.** O `handoff_close` do KAM-031
        # compara `outcome == "timeout"`; traduzir antes de entrar fazia o
        # `resolved` chegar la como `resumed`, que nao bate com nada.
        self.assertEqual(comando.resume, {"outcome": "resolved"})
        self.assertEqual(config, {"configurable": {"thread_id": THREAD}})
        exposicao = metricas.ler()
        self.assertEqual(exposicao.get(f"{METRICA_RETOMA}:retomado"), 1)
        self.assertEqual(exposicao.get(f"{METRICA_HANDOFF}:resumed"), 1)

    async def test_o_segundo_pedido_com_o_mesmo_handoff_e_um_no_op(self) -> None:
        passagens, contactos = uma_passagem()
        base = BaseFalsa(passagens, contactos)
        alvo, grafo = retomador(base)
        self.assertEqual(await alvo.retomar(THREAD, "h1", "resolved"), "retomado")
        self.assertEqual(await alvo.retomar(THREAD, "h1", "resolved"), "repetido")
        self.assertEqual(len(grafo.invocacoes), 1, "uma retoma, nao duas")

    async def test_dois_pedidos_concorrentes_dao_uma_retoma(self) -> None:
        """Criterio 3, por extenso: «dois pedidos concorrentes ... 1 retoma».

        Correm **sob a tranca**, como em producao: e ela que serializa, e o CAS
        que decide qual dos dois vence. Sem a tranca, o `asyncio.Lock` da
        ligacao ja serializava o acesso a base — o que tornava o ensaio uma
        medida do duplo e nao do desenho.
        """
        passagens, contactos = uma_passagem()
        base = BaseFalsa(passagens, contactos)
        alvo, grafo = retomador(base)
        tranca = TrancaFalsa()

        async def um_pedido():
            async with tranca.tomar(THREAD):
                return await alvo.retomar(THREAD, "h1", "resolved")

        desfechos = await asyncio.gather(um_pedido(), um_pedido())
        self.assertEqual(sorted(desfechos), ["repetido", "retomado"])
        self.assertEqual(len(grafo.invocacoes), 1)
        self.assertEqual(tranca.sobrepostas, 0)

    async def test_uma_passagem_que_nao_e_deste_thread_e_recusada(self) -> None:
        """Isolamento (ADR-015): e `recusado`, nao um 200 a fingir.

        Tres casos e a mesma recusa — nao existe, e de outro *tenant*, e de
        outro contacto do mesmo *tenant*. O terceiro e o que a chave `handoff_id
        = sha256(thread_id:seq)` **nao** consegue impedir sozinha: ela e
        irreversivel, pelo que do identificador nao se le o *thread* de volta.
        """
        outro_tenant = str(uuid.UUID(int=9))
        outro_contacto = str(uuid.UUID(int=8))
        casos = {
            "nao_existe": BaseFalsa({}, {}),
            "outro_tenant": BaseFalsa(
                {"h1": {"tenant": outro_tenant, "status": "waiting"}},
                {"h1": CONTACTO},
            ),
            "outro_contacto": BaseFalsa(
                {"h1": {"tenant": TENANT, "status": "waiting"}},
                {"h1": outro_contacto},
            ),
        }
        for nome, base in casos.items():
            with self.subTest(caso=nome):
                alvo, grafo = retomador(base)
                self.assertEqual(await alvo.retomar(THREAD, "h1", "resolved"), "recusado")
                self.assertEqual(grafo.invocacoes, [])

    async def test_um_thread_id_malformado_levanta_em_vez_de_recusar(self) -> None:
        """400 e nao 404: o corpo esta mal, a passagem nao esta em causa.

        **As duas metades tem de ter forma de UUID**, e a primeira versao so
        exigia que existissem (achado 7): um `contact_id` que nao e UUID chegava
        a base, o PostgreSQL respondia `22P02`, o `_executar` largava a ligacao e
        subia 500 — e o HND **repete**, com uma tomada nova por volta. Um corpo
        malformado passava a ser uma tempestade de repeticoes em vez de um 400
        que o chamador descarta.
        """
        base = BaseFalsa(*uma_passagem())
        alvo, _ = retomador(base)
        maus = (
            "",
            ":",
            "sem-dois-pontos",
            ":contacto",
            f"{TENANT}:",
            "a:b:c",
            f"{TENANT}:nao-e-um-uuid",
            f"nao-e-um-uuid:{CONTACTO}",
            f"{TENANT}:{CONTACTO}:a-mais",
            # **A forma nao canonica**, que o `uuid.UUID` aceita e o
            # `normalizar_tenant` do `kamba_core` recusa: «duas escritas do
            # mesmo tenant sao duas chaves de cache e dois valores de log
            # diferentes mais adiante».
            f"{TENANT.replace('-', '')}:{CONTACTO}",
            f"{{{TENANT}}}:{CONTACTO}",
            f"urn:uuid:{TENANT}:{CONTACTO}",
            # **Maiusculas, e o UUID tem de ter letras para o caso existir.** O
            # `TENANT` desta bateria e `uuid.UUID(int=1)`, que so tem digitos e
            # hifenes: `TENANT.upper()` e o proprio `TENANT`, e o caso media o
            # caminho feliz a dizer que media o malformado. Apanhado a correr.
            f"{_COM_LETRAS.upper()}:{CONTACTO}",
        )
        for mau in maus:
            with self.subTest(thread_id=mau):
                with self.assertRaises(ThreadInvalidoError):
                    await alvo.retomar(mau, "h1", "resolved")
        self.assertEqual(base.instrucoes, [], "nao se toca na base")

    async def test_o_thread_id_canonico_passa(self) -> None:
        """O controlo positivo: sem ele, um `partes` que recusasse tudo passava
        o ensaio de cima — e a rota respondia 400 a toda a retoma."""
        base = BaseFalsa(*uma_passagem())
        alvo, _ = retomador(base)
        self.assertEqual(await alvo.retomar(THREAD, "h1", "resolved"), "retomado")

    async def test_um_desfecho_invalido_levanta_antes_de_tocar_na_base(self) -> None:
        base = BaseFalsa(*uma_passagem())
        alvo, _ = retomador(base)
        with self.assertRaises(maquina.DesfechoInvalidoError):
            await alvo.retomar(THREAD, "h1", "resumed")
        self.assertEqual(base.instrucoes, [])

    async def test_sem_grafo_nada_e_escrito(self) -> None:
        """O grafo resolve-se **antes** do CAS.

        Com a ordem inversa, o CAS escrevia `resumed`, a compensacao devolvia-o
        a `waiting`, e havia uma janela em que a passagem aparecia retomada —
        duas escritas para nada.
        """
        passagens, contactos = uma_passagem()
        base = BaseFalsa(passagens, contactos)

        def sem_grafo(_thread_id):
            raise GrafoNaoRegistadoError("grafo_nao_registado")

        alvo = Retomador(abrir_ligacao=lambda: base, grafos=sem_grafo)
        with self.assertRaises(GrafoNaoRegistadoError):
            await alvo.retomar(THREAD, "h1", "resolved")
        self.assertEqual(base.instrucoes, [])
        self.assertEqual(base.passagens["h1"]["status"], "waiting")

    async def test_um_command_que_levanta_devolve_a_passagem_a_waiting(self) -> None:
        """A compensacao, sem a qual a passagem ficava presa para sempre.

        Em `resumed` com o grafo interrompido: o *webhook* repetido via zero
        linhas, respondia 200, e a varredura dos prazos nao a encontrava —
        porque so olha para `waiting`.
        """
        passagens, contactos = uma_passagem()
        base = BaseFalsa(passagens, contactos)
        alvo, _ = retomador(base, grafo=GrafoFalso(levanta=RuntimeError("rebentou")))
        with self.assertRaises(GrafoDaRetomaError):
            await alvo.retomar(THREAD, "h1", "resolved")
        self.assertEqual(base.passagens["h1"]["status"], "waiting")

        # E a tentativa seguinte volta a vencer o CAS.
        alvo_bom, grafo = retomador(base)
        self.assertEqual(await alvo_bom.retomar(THREAD, "h1", "resolved"), "retomado")
        self.assertEqual(len(grafo.invocacoes), 1)

    async def test_uma_reversao_que_falha_nomeia_o_residuo(self) -> None:
        """O unico caso em que a passagem fica presa, e ele tem nome.

        `ReversaoFalhadaError`, com a falha original encadeada: e a unica
        informacao com que alguem consegue ir desencravar a passagem a mao.
        """
        passagens, contactos = uma_passagem()
        base = BaseFalsa(passagens, contactos)
        original = RuntimeError("o grafo rebentou")
        alvo, _ = retomador(base, grafo=GrafoFalso(levanta=original))

        # A reversao nao casa: alguem mudou o estado por fora entre as duas.
        def sabotar(sql, parametros):
            if sql is consultas.SQL_REVERTER_RETOMA:
                return None
            return BaseFalsa.executar(base, sql, parametros)

        base.executar = sabotar  # type: ignore[method-assign]
        with self.assertRaises(ReversaoFalhadaError) as capturado:
            await alvo.retomar(THREAD, "h1", "resolved")
        self.assertIs(capturado.exception.original, original)

    async def test_os_tres_desfechos_da_retoma_sao_etiqueta_fechada(self) -> None:
        self.assertEqual(
            sorted(DESFECHOS_DA_RETOMA), ["recusado", "repetido", "retomado"]
        )
        metricas = MetricasDoAgr()
        for desfecho in DESFECHOS_DA_RETOMA:
            metricas.contar(METRICA_RETOMA, desfecho)
        self.assertEqual(len(metricas.ler()), len(DESFECHOS_DA_RETOMA))


class TestATomadaDaRetoma(unittest.IsolatedAsyncioTestCase):
    """A ligacao: largar a quebrada, e fechar no encerramento.

    E a propriedade que o `trancas.py` e o `conversa.py` escreveram por extenso
    e que custou o mesmo defeito duas vezes: uma ligacao quebrada que fique
    guardada faz **todas** as retomas deste processo falharem ate alguem
    reiniciar o servico — e nao da erro de arranque nenhum.
    """

    async def test_uma_ligacao_quebrada_larga_se_e_a_seguinte_abre_outra(self) -> None:
        passagens, contactos = uma_passagem()
        abertas: list = []

        class Quebrada(BaseFalsa):
            def cursor(self):
                raise RuntimeError("a tomada morreu")

        def abrir():
            base = Quebrada(passagens, contactos) if not abertas else BaseFalsa(
                passagens, contactos
            )
            abertas.append(base)
            return base

        alvo = Retomador(abrir_ligacao=abrir, grafos=lambda _t: GrafoFalso())
        with self.assertRaises(RuntimeError):
            await alvo.retomar(THREAD, "h1", "resolved")
        self.assertEqual(len(abertas), 1)
        # A tentativa seguinte abre **outra** e vence.
        self.assertEqual(await alvo.retomar(THREAD, "h1", "resolved"), "retomado")
        self.assertEqual(len(abertas), 2)

    async def test_o_fechar_larga_a_tomada_e_e_idempotente(self) -> None:
        base = BaseFalsa(*uma_passagem())
        fechadas: list = []
        base.close = lambda: fechadas.append(True)  # type: ignore[method-assign]
        alvo, _ = retomador(base)
        await alvo.retomar(THREAD, "h1", "resolved")
        await alvo.fechar()
        self.assertEqual(fechadas, [True])
        # Duas vezes nao levanta: o encerramento corre no `lifespan` e um
        # `fechar` que levantasse deixava o resto do `ao_encerrar` sem correr.
        await alvo.fechar()
        self.assertEqual(fechadas, [True])

    async def test_um_close_que_levanta_nao_impede_o_encerramento(self) -> None:
        base = BaseFalsa(*uma_passagem())

        def rebentar():
            raise RuntimeError("a tomada ja estava quebrada")

        base.close = rebentar  # type: ignore[method-assign]
        alvo, _ = retomador(base)
        await alvo.retomar(THREAD, "h1", "resolved")
        await alvo.fechar()  # nao levanta


class TestATrancaExcluiDentroDoProcesso(unittest.IsolatedAsyncioTestCase):
    """A `TrancaDeConversas` **real**, com a base a modelar o que ela faz.

    **E o ensaio que faltava, e o que faltava era o duplo.** A `TrancaFalsa` da
    bateria tem um `asyncio.Lock` por chave e afirma `sobrepostas == 0`; a
    `TrancaDeConversas` a serio tem **uma** ligacao por processo, e os *advisory
    locks* de sessao do PostgreSQL sao **contados** — a segunda tomada da mesma
    chave na mesma sessao devolve `true`. Dentro de um processo, a tranca da base
    nao excluia nada, e o `pg_advisory_unlock` devolvia `true` nas duas, pelo que
    o `TrancaNaoLargadaError` nunca levantava.

    Para o turno isso estava coberto pelo dreno do `turno.py`; a rota de retoma e
    a varredura dos prazos **nao passam pelo dreno**, e para elas a tranca era a
    unica barreira. Achado 2 da revisao adversarial, medido contra PostgreSQL 18.

    **A ligacao falsa aqui conta como o PostgreSQL conta**, de proposito: um
    duplo que devolvesse `false` a segunda tomada modelava a propriedade que a
    base nao tem, e o ensaio voltava a medir o duplo.
    """

    class LigacaoQueConta:
        """`pg_try_advisory_lock` de **sessao**: re-entrante e contado."""

        autocommit = True

        def __init__(self) -> None:
            self.contagem: dict[str, int] = {}

        def cursor(self):
            return self

        def execute(self, sql, parametros=()) -> None:
            from kamba_agr.consultas import (
                SQL_DESTRANCAR_THREAD,
                SQL_TRANCAR_THREAD,
            )

            chave = parametros[0]
            if sql is SQL_TRANCAR_THREAD:
                # **Sempre `True` na mesma sessao**, que e o que a base faz.
                self.contagem[chave] = self.contagem.get(chave, 0) + 1
                self._linha = (True,)
            elif sql is SQL_DESTRANCAR_THREAD:
                self.contagem[chave] = max(0, self.contagem.get(chave, 0) - 1)
                self._linha = (True,)
            else:
                raise AssertionError(f"instrucao inesperada: {sql[:40]!r}")

        def fetchone(self):
            return self._linha

        def close(self) -> None:
            pass

    async def test_duas_corrotinas_nao_entram_na_mesma_conversa(self) -> None:
        from kamba_agr.trancas import TrancaDeConversas

        ligacao = self.LigacaoQueConta()
        trancas = TrancaDeConversas(lambda: ligacao)
        dentro = {"agora": 0, "maximo": 0}
        ordem: list[str] = []

        async def seccao(nome: str):
            async with trancas.tomar(THREAD):
                ordem.append(f"entra:{nome}")
                dentro["agora"] += 1
                dentro["maximo"] = max(dentro["maximo"], dentro["agora"])
                await asyncio.sleep(0.01)
                dentro["agora"] -= 1
                ordem.append(f"sai:{nome}")

        await asyncio.gather(seccao("A"), seccao("B"))
        self.assertEqual(dentro["maximo"], 1, ordem)
        self.assertEqual(ordem, ["entra:A", "sai:A", "entra:B", "sai:B"])

    async def test_conversas_diferentes_nao_esperam_uma_pela_outra(self) -> None:
        """O controlo positivo: sem ele, um trinco global passava o de cima.

        Um trinco por processo em vez de por `thread_id` era bloqueio de cabeca
        de fila a atravessar *tenants*, que e exactamente o que o criterio 5 do
        KAM-025 proibe — e o que a primeira versao do `trancas.py` pagou.
        """
        from kamba_agr.trancas import TrancaDeConversas

        trancas = TrancaDeConversas(lambda: self.LigacaoQueConta())
        dentro = {"agora": 0, "maximo": 0}

        async def seccao(chave: str):
            async with trancas.tomar(chave):
                dentro["agora"] += 1
                dentro["maximo"] = max(dentro["maximo"], dentro["agora"])
                await asyncio.sleep(0.01)
                dentro["agora"] -= 1

        await asyncio.gather(seccao("t:um"), seccao("t:dois"))
        self.assertEqual(dentro["maximo"], 2, "duas conversas serializaram")

    async def test_o_dicionario_de_trincos_nao_cresce(self) -> None:
        """Um `dict` de trincos sem limpeza e uma fuga proporcional ao numero de
        conversas distintas que o processo viu."""
        from kamba_agr.trancas import TrancaDeConversas

        trancas = TrancaDeConversas(lambda: self.LigacaoQueConta())
        for i in range(20):
            async with trancas.tomar(f"t:{i}"):
                pass
        self.assertEqual(trancas._por_thread, {})

    async def test_uma_retoma_concorrente_com_a_varredura_nao_se_perde(self) -> None:
        """**O caminho que o achado 2 mediu, agora com a tranca a excluir.**

        Uma passagem expirada: a varredura vence o CAS e o `Command` **falha**
        (o *checkpointer* a reiniciar), pelo que ela compensa e devolve a linha a
        `waiting`. Cinquenta milissegundos depois chega o `resolved` do colega.

        Com exclusao a serio, o *webhook* **espera**, encontra a linha outra vez
        em `waiting`, vence o CAS e o grafo retoma. Sem ela, o `resolved` do
        colega levava 200 `repetido`, o Chatwoot parava de reenviar, e o cliente
        — cuja pergunta um humano ja respondeu — recebia a mensagem de
        alternativas.
        """
        from kamba_agr.trancas import TrancaDeConversas

        passagens, contactos = uma_passagem()
        base = BaseFalsa(passagens, contactos)
        trancas = TrancaDeConversas(lambda: self.LigacaoQueConta())

        da_varredura, _ = retomador(
            base, grafo=GrafoFalso(levanta=RuntimeError("checkpointer a reiniciar"))
        )
        do_webhook, grafo_do_webhook = retomador(base)

        async def varredura():
            async with trancas.tomar(THREAD):
                with self.assertRaises(GrafoDaRetomaError):
                    await da_varredura.retomar(THREAD, "h1", "timeout")

        async def webhook():
            await asyncio.sleep(0.005)
            async with trancas.tomar(THREAD):
                return await do_webhook.retomar(THREAD, "h1", "resolved")

        _, desfecho = await asyncio.gather(varredura(), webhook())
        self.assertEqual(desfecho, "retomado")
        self.assertEqual(base.passagens["h1"]["status"], "resumed")
        self.assertEqual(len(grafo_do_webhook.invocacoes), 1)


class TestOsDoisResiduos(unittest.IsolatedAsyncioTestCase):
    """Os dois caminhos que ninguem quer e que tem de ter nome."""

    async def test_uma_reversao_que_rebenta_encadeia_as_duas_falhas(self) -> None:
        """A falha original **e** a da reversao, as duas no mesmo registo.

        Um `raise ... from erro` deixava o registo a dizer que a base caiu e
        calava **qual** retoma ficou presa — a unica informacao com que alguem
        consegue ir desencravar a passagem a mao.
        """
        passagens, contactos = uma_passagem()
        base = BaseFalsa(passagens, contactos)
        original = RuntimeError("o grafo rebentou")
        da_base = RuntimeError("a base caiu a meio da reversao")
        alvo, _ = retomador(base, grafo=GrafoFalso(levanta=original))

        def sabotar(sql, parametros):
            if sql is consultas.SQL_REVERTER_RETOMA:
                raise da_base
            return BaseFalsa.executar(base, sql, parametros)

        base.executar = sabotar  # type: ignore[method-assign]
        with self.assertRaises(ReversaoFalhadaError) as capturado:
            await alvo.retomar(THREAD, "h1", "resolved")
        # **O atributo e nao os *dunders*.** O `raise ... from` escreve o
        # `__cause__` e o `__context__` por sua conta, e nao na mesma ordem em
        # 3.12 e em 3.13: a primeira versao deste ensaio passava nesta maquina e
        # **falhava no runner**. O que se quer guardar guarda-se num campo.
        self.assertIs(capturado.exception.original, original)
        self.assertIs(capturado.exception.__cause__, da_base)
        # E a passagem fica presa, que e o residuo que o nome declara.
        self.assertEqual(base.passagens["h1"]["status"], "resumed")

    async def test_um_cas_que_recusa_uma_passagem_retomavel_e_recusa_e_nao_duplicado(
        self,
    ) -> None:
        """**As duas leituras do dominio divergiram, e isso e um defeito.**

        O `pode_retomar` e `False` por construcao no caminho da classificacao —
        o CAS acabou de nao casar —, e confronta-se de qualquer maneira. Se um
        dia ele disser `True` sobre uma passagem que o CAS recusou, chamar-lhe
        duplicado era responder 200 «tratado» sobre uma passagem que continua a
        espera de um humano. Responde `recusado`, que da 404 e aparece.
        """
        passagens, contactos = uma_passagem()
        base = BaseFalsa(passagens, contactos)

        def sabotar(sql, parametros):
            if sql is consultas.SQL_RETOMAR_HANDOFF:
                return None  # o CAS recusa...
            return BaseFalsa.executar(base, sql, parametros)  # ...e a linha diz `waiting`

        base.executar = sabotar  # type: ignore[method-assign]
        alvo, grafo = retomador(base)
        self.assertEqual(await alvo.retomar(THREAD, "h1", "resolved"), "recusado")
        self.assertEqual(grafo.invocacoes, [])


# ----------------------------------------------------------- a nao-reentrada


class TestNaoReentrada(unittest.IsolatedAsyncioTestCase):
    """Criterio 5: 0 invocacoes de grafo com *input* novo."""

    async def test_uma_mensagem_num_thread_em_waiting_nao_invoca_o_grafo(self) -> None:
        invocacoes: list = []
        ao_hnd: list = []

        class GrafoEspiao:
            async def ainvoke(self, estado, config):
                invocacoes.append((estado, config))

        async def ler_palavra(_invocacao):
            return Palavra(modo="bot", handoff_a_espera=True)

        async def reencaminhar(lote):
            ao_hnd.append(lote)

        executor = ExecutorDeTurnos(
            trancas=TrancaFalsa(),
            ler_palavra=ler_palavra,
            grafos=lambda _i: GrafoEspiao(),
            reencaminhar=reencaminhar,
            admissao=Admissao(),
        )
        desfecho = await executor.correr(_invocacao(TENANT, CONTACTO))
        self.assertEqual(desfecho.desfecho, "entregue_ao_hnd")
        self.assertEqual(invocacoes, [], "0 invocacoes de grafo com input novo")
        self.assertEqual(len(ao_hnd), 1)

    async def test_em_modo_bot_e_sem_handoff_a_espera_o_grafo_corre(self) -> None:
        """O controlo positivo: sem ele, um `do_humano` sempre `True` passava."""
        invocacoes: list = []

        class GrafoEspiao:
            async def ainvoke(self, estado, config):
                invocacoes.append((estado, config))

        async def ler_palavra(_invocacao):
            return Palavra(modo="bot", handoff_a_espera=False)

        executor = ExecutorDeTurnos(
            trancas=TrancaFalsa(),
            ler_palavra=ler_palavra,
            grafos=lambda _i: GrafoEspiao(),
            reencaminhar=lambda _lote: asyncio.sleep(0),
            admissao=Admissao(),
        )
        desfecho = await executor.correr(_invocacao(TENANT, CONTACTO))
        self.assertEqual(desfecho.desfecho, "executado")
        self.assertEqual(len(invocacoes), 1)


def _invocacao(tenant_id, contact_id):
    from kamba_agr.contexto import ler_invocacao

    return ler_invocacao(invocacao_crua(tenant_id=tenant_id, contact_id=contact_id))


# ------------------------------------------------------------- a autenticacao


class TestAutenticacaoDoBot(unittest.TestCase):
    """Criterio 4: o `secret` do *agent bot*."""

    def test_o_segredo_certo_passa_e_os_outros_nao(self) -> None:
        self.assertIsNone(avaliar(CREDENCIAL, CREDENCIAL))
        self.assertEqual(avaliar(None, CREDENCIAL), "sem_secret")
        self.assertEqual(avaliar("", CREDENCIAL), "sem_secret")
        for mau in (CREDENCIAL + "x", CREDENCIAL[:-1], CREDENCIAL.upper(), " "):
            with self.subTest(valor=mau[:8]):
                self.assertEqual(avaliar(mau, CREDENCIAL), "secret_errado")

    def test_o_esperado_vazio_recusa_sempre(self) -> None:
        """Uma configuracao sem segredo nao se torna uma porta aberta."""
        self.assertEqual(avaliar(CREDENCIAL, ""), "secret_errado")
        self.assertEqual(avaliar("", ""), "sem_secret")

    def test_o_tenant_sai_do_prefixo_do_thread(self) -> None:
        self.assertEqual(tenant_do_thread(THREAD), TENANT)
        for mau in ("", ":", ":contacto", "sem-dois-pontos"):
            with self.subTest(thread_id=mau):
                self.assertIsNone(tenant_do_thread(mau))

    def test_o_verificador_pede_o_segredo_do_tenant_do_thread(self) -> None:
        pedidos: list[str] = []

        def cofre(tenant_id: str) -> str:
            pedidos.append(tenant_id)
            return CREDENCIAL

        verificar = verificador(cofre)
        self.assertIsNone(verificar(CREDENCIAL, THREAD))
        self.assertEqual(pedidos, [TENANT])

    def test_um_cofre_que_levanta_recusa_em_vez_de_dar_500(self) -> None:
        """Um 500 punha o *webhook* a repetir contra um *tenant* sem segredo."""

        def cofre(_tenant_id: str) -> str:
            raise KeyError("referencia_inexistente")

        self.assertEqual(verificador(cofre)(CREDENCIAL, THREAD), "secret_errado")

    def test_sem_segredo_nao_se_vai_ao_cofre(self) -> None:
        """A ordem e a do custo: um pedido sem cabecalho nao gera consulta."""
        pedidos: list[str] = []
        verificar = verificador(lambda t: pedidos.append(t) or CREDENCIAL)
        self.assertEqual(verificar(None, THREAD), "sem_secret")
        self.assertEqual(pedidos, [])

    def test_os_motivos_sao_os_dois_primeiros_do_hnd(self) -> None:
        """A paridade com o `hnd/assinatura.ts`, lida do ficheiro do outro lado.

        Os quatro de la sao `sem_secret`, `secret_errado`, `tipo_desconhecido` e
        `conta_desconhecida`; os dois ultimos nao tem caminho nesta rota (o
        `tipo` e do *callback* do Chatwoot e a conta e resolvida pelo HND antes
        de ele nos chamar), e declara-los era etiqueta sempre a zero.
        """
        import re
        from pathlib import Path

        raiz = Path(__file__).resolve().parents[3]
        fonte = (
            raiz / "packages" / "core-ts" / "src" / "hnd" / "assinatura.ts"
        ).read_text(encoding="utf-8")
        bloco = re.search(
            r"MOTIVOS_DE_RECUSA\s*=\s*\[(.*?)\]", fonte, re.DOTALL
        )
        self.assertIsNotNone(bloco, "o `MOTIVOS_DE_RECUSA` do HND mudou de forma")
        de_la = tuple(re.findall(r'"([a-z_]+)"', bloco.group(1)))
        self.assertEqual(MOTIVOS_DE_RECUSA, de_la[:2])

    def test_o_cabecalho_nao_e_o_da_credencial_de_rede(self) -> None:
        from kamba_agr.api_interna import CABECALHO

        self.assertNotEqual(CABECALHO_DO_BOT, CABECALHO)


# ------------------------------------------------------------------ os prazos


class TestPrazos(unittest.IsolatedAsyncioTestCase):
    """Criterio 7: as 24 h, com relogio simulado."""

    def test_o_prazo_e_de_24_horas(self) -> None:
        self.assertEqual(PRAZO_SEGUNDOS, 24 * 60 * 60)

    def test_a_mensagem_de_alternativas_nomeia_os_tres_canais(self) -> None:
        """**A unica substancia nova do criterio 7, e nao tinha ensaio nenhum.**

        Achado 8 da revisao adversarial: uma mutacao que revertesse a
        `MSG_ALTERNATIVAS` ao texto anterior («Pode escrever outra vez, ou tentar
        mais tarde») sobrevivia a bateria inteira e aos dez *gates* — o ensaio
        do `handoff_close` compara a mensagem com a **constante**, pelo que
        mudar a constante muda os dois lados.

        O que o `01` §11.4 regra 4 exige e que o cliente receba **alternativas**,
        e o que a Messaging Policy nomeia sao tres: telefone, e-mail e loja. Esta
        asserção e sobre o **conteudo** e nao sobre a constante, que e a unica
        forma de nao ser circular.
        """
        texto = nos_mod.MSG_ALTERNATIVAS.lower()
        for canal, palavras in (
            ("telefone", ("ligar",)),
            ("e-mail", ("e-mail", "email")),
            ("loja", ("loja", "passar por la")),
        ):
            with self.subTest(canal=canal):
                self.assertTrue(
                    any(palavra in texto for palavra in palavras),
                    f"a mensagem de alternativas nao nomeia o canal {canal}: {texto!r}",
                )

    def test_a_mensagem_de_alternativas_continua_sem_digitos(self) -> None:
        """E o outro lado: **nomear** os canais e nao trazer os valores.

        Um numero de telefone ou um e-mail com digitos nao cabe num bloco
        `text` — o `renderizar` levanta, de proposito, porque e a regra que
        impede prosa numerica (ADR-007). **Nao se alarga a proibicao de
        digitos**, que e uma regra de seguranca; o que fecha a divida 124 e um
        sexto bloco cuja cadeia venha de um *fact* com proveniencia.
        """
        import re

        self.assertIsNone(re.search(r"\d", nos_mod.MSG_ALTERNATIVAS))
        self.assertIsNone(nos_mod.violacao_de_saida(nos_mod.MSG_ALTERNATIVAS))

    def test_o_limite_e_o_agora_menos_vinte_e_quatro_horas_em_utc(self) -> None:
        """**O `86_400` e literal e nao `PRAZO_SEGUNDOS`, de proposito.**

        Com a constante dos dois lados, a asserção era circular: uma mutacao que
        pusesse o prazo em doze horas mudava o valor **e** o esperado, e passava.
        A unica outra coisa que a apanhava era o
        `test_o_prazo_e_de_24_horas`, que afirma um numero — e o repositorio ja
        pagou essa licao (o KAM-027: «uma lista literal transforma uma
        invariante num numero»). Aqui o numero e o canon: 24 h sao a exigencia
        da Messaging Policy que o `01` §11.4 cita, e nao um parametro.

        O fuso tambem se afirma: a coluna e `timestamptz`, e um `datetime` sem
        fuso comparado com ela e interpretado no `TimeZone` da sessao — a
        varredura passava a depender de uma configuracao do servidor.
        """
        import datetime as dt

        relogio = Relogio(inicio=_AGORA)
        limite = Prazos(
            abrir_ligacao=lambda: None,
            trancas=TrancaFalsa(),
            retomar=None,
            relogio=relogio,
        ).limite()
        self.assertEqual(limite.tzinfo, dt.timezone.utc)
        self.assertAlmostEqual(limite.timestamp(), _AGORA - 86_400)

    async def test_a_varredura_retoma_com_timeout_e_uma_so_vez(self) -> None:
        chamadas: list = []
        passagens, contactos = uma_passagem()
        base = BaseFalsa(passagens, contactos)
        alvo, grafo = retomador(base)

        async def retomar(thread_id, handoff_id, desfecho):
            chamadas.append((thread_id, handoff_id, desfecho))
            return await alvo.retomar(thread_id, handoff_id, desfecho)

        prazos = Prazos(
            abrir_ligacao=lambda: _LigacaoDeLote([("h1", TENANT, CONTACTO)]),
            trancas=TrancaFalsa(),
            retomar=retomar,
            relogio=Relogio(inicio=_AGORA),
        )
        self.assertEqual(await prazos.varrer(), _contagem(retomado=1))
        self.assertEqual(chamadas, [(THREAD, "h1", "timeout")])
        self.assertEqual(base.passagens["h1"]["status"], "timeout")
        self.assertEqual(grafo.invocacoes[0][0].resume, {"outcome": "timeout"})

        # **Uma segunda varredura nao retoma outra vez**, e nao e por este
        # modulo guardar nada: e o CAS que a para.
        self.assertEqual(await prazos.varrer(), _contagem(repetido=1))
        self.assertEqual(len(grafo.invocacoes), 1)

    async def test_uma_falha_numa_passagem_nao_para_as_outras(self) -> None:
        tratadas: list = []

        async def retomar(_thread_id, handoff_id, _desfecho):
            if handoff_id == "mau":
                raise RuntimeError("rebentou")
            tratadas.append(handoff_id)
            return "retomado"

        prazos = Prazos(
            abrir_ligacao=lambda: _LigacaoDeLote(
                [("mau", TENANT, CONTACTO), ("bom", TENANT, CONTACTO)]
            ),
            trancas=TrancaFalsa(),
            retomar=retomar,
            relogio=Relogio(inicio=_AGORA),
        )
        self.assertEqual(await prazos.varrer(), _contagem(retomado=1, falhou=1))
        self.assertEqual(tratadas, ["bom"])

    async def test_a_varredura_corre_sob_a_tranca_de_cada_conversa(self) -> None:
        tranca = TrancaFalsa()
        dentro: list = []

        async def retomar(thread_id, _handoff_id, _desfecho):
            dentro.append((thread_id, tranca.dentro))
            return "retomado"

        prazos = Prazos(
            abrir_ligacao=lambda: _LigacaoDeLote([("h1", TENANT, CONTACTO)]),
            trancas=tranca,
            retomar=retomar,
            relogio=Relogio(inicio=_AGORA),
        )
        await prazos.varrer()
        self.assertEqual(dentro, [(THREAD, 1)])
        self.assertEqual(tranca.dentro, 0)

    def test_o_instrumento_do_drain_conta_as_passagens_a_espera(self) -> None:
        """O *drain* dos Detalhes Tecnicos: «mudanca incompativel de grafo
        exige *drain* dos handoffs `waiting`».

        Uma passagem em `waiting` e um `interrupt()` pendente num *checkpoint*,
        e o no que o retoma e o da **versao nova** do grafo: se ele deixou de
        existir, a retoma rebenta com a conversa a meio — num caminho que nenhum
        teste de unidade ve, porque o estado que a quebra foi escrito por outra
        versao.
        """
        ligacao = _LigacaoDeLote([(3,)], consulta=consultas.SQL_PASSAGENS_A_ESPERA)
        prazos = Prazos(
            abrir_ligacao=lambda: ligacao,
            trancas=TrancaFalsa(),
            retomar=None,
            relogio=Relogio(inicio=_AGORA),
        )
        self.assertEqual(prazos.a_espera(ligacao), 3)

    async def test_a_ligacao_de_lote_fecha_mesmo_sem_passagens(self) -> None:
        ligacao = _LigacaoDeLote([])
        prazos = Prazos(
            abrir_ligacao=lambda: ligacao,
            trancas=TrancaFalsa(),
            retomar=None,
            relogio=Relogio(inicio=_AGORA),
        )
        self.assertEqual(await prazos.varrer(), _contagem())
        self.assertTrue(ligacao.fechada)


def _contagem(**sobrepor):
    base = {"retomado": 0, "repetido": 0, "recusado": 0, "falhou": 0}
    base.update(sobrepor)
    return base


class _LigacaoDeLote:
    """A ligacao `kamba_batch` da varredura: devolve as linhas que lhe deram."""

    autocommit = False

    def __init__(self, linhas, consulta=None) -> None:
        self.linhas = linhas
        self.fechada = False
        self.instrucoes: list = []
        #: Qual das duas cadeias de lote se espera. **Compara-se por
        #: identidade e levanta se nao bater**, em vez de devolver as linhas
        #: para qualquer SQL: um duplo que responde a tudo nao distingue a
        #: varredura da contagem do *drain*, e o ensaio passava com a consulta
        #: errada.
        self.consulta = consulta or consultas.SQL_HANDOFFS_EXPIRADOS

    def cursor(self):
        return self

    def execute(self, sql, parametros=()) -> None:
        assert sql is self.consulta, sql[:60]
        self.instrucoes.append(parametros)

    def fetchall(self):
        return self.linhas

    def fetchone(self):
        return self.linhas[0] if self.linhas else None

    def commit(self) -> None:
        pass

    def rollback(self) -> None:
        pass

    def close(self) -> None:
        self.fechada = True


class TestMetricasRegistadas(unittest.TestCase):
    """As quatro metricas novas contam, e o `tenant_id` nao e etiqueta."""

    def setUp(self) -> None:
        METRICAS.repor()

    def test_as_quatro_estao_declaradas_e_contam(self) -> None:
        for estado in maquina.ESTADOS:
            METRICAS.contar(METRICA_HANDOFF, estado)
        for desfecho in DESFECHOS_DA_RETOMA:
            METRICAS.contar(METRICA_RETOMA, desfecho)
        for motivo in MOTIVOS_DE_RECUSA:
            METRICAS.contar("agr_resume_nao_autorizado_total", motivo)
        METRICAS.contar(METRICA_HANDOFF_DEGRADADO)
        exposicao = METRICAS.ler()
        self.assertEqual(exposicao[f"{METRICA_HANDOFF}:waiting"], 1)
        self.assertEqual(exposicao[METRICA_HANDOFF_DEGRADADO], 1)

    def test_um_tenant_id_como_etiqueta_levanta(self) -> None:
        """OBS-I: a gramatica recusa-o, porque um UUID tem hifenes."""
        from kamba_agr.metricas import EtiquetaInvalida

        for metrica in (METRICA_HANDOFF, METRICA_RETOMA):
            with self.subTest(metrica=metrica):
                with self.assertRaises(EtiquetaInvalida):
                    METRICAS.contar(metrica, TENANT)

    def test_o_degradado_nao_leva_etiqueta(self) -> None:
        from kamba_agr.metricas import EtiquetaInvalida

        with self.assertRaises(EtiquetaInvalida):
            METRICAS.contar(METRICA_HANDOFF_DEGRADADO, "waiting")


# ------------------------------------------------- a fronteira com o HND (1.42)


class TestFronteiraComOHnd(unittest.TestCase):
    """A fronteira da emenda 1.42, lida do **outro** lado (credor: KAM-019).

    **Esta classe existe por causa de uma medicao, e e a mais importante das
    duas.** A revisao adversarial do KAM-034 (`docs/analises/ANALISE-35`, achado
    1) encontrou que a `platform.handoffs` tinha dois escritores para a saida de
    `waiting` e que o do HND corria primeiro — e a prova de que ninguem olhara
    para isso foi um `grep`:

        $ grep -rn "ESTADOS_QUE_FECHAM" --include=*.py .
        (nada)

    O segundo escritor foi lido pela coluna de que divergia (`resumed_at`) e
    nunca pelo `status` que escrevia. O que estes ensaios fazem e **por o outro
    lado dentro desta bateria**: quatro cadeias de texto e uma lista vivem em
    dois idiomas, e a unica coisa que impede os dois lados de divergirem e
    alguem medir que nao divergiram.

    Le os ficheiros TypeScript como **texto**, e isso e deliberado: a travessia
    nao existe (nao se importa TypeScript de Python), e a alternativa — copiar os
    valores para ca — era criar a terceira copia do que ja estava em duas. E a
    mesma tecnica do `test_os_motivos_sao_os_dois_primeiros_do_hnd`, acima.
    """

    @classmethod
    def setUpClass(cls) -> None:
        super().setUpClass()
        from pathlib import Path

        raiz = Path(__file__).resolve().parents[3]
        hnd = raiz / "packages" / "core-ts" / "src" / "hnd"
        cls.retoma_ts = (hnd / "retoma.ts").read_text(encoding="utf-8")
        cls.estados_ts = (hnd / "estados.ts").read_text(encoding="utf-8")
        cls.consultas_ts = (hnd / "consultas.ts").read_text(encoding="utf-8")

    def test_o_hnd_nao_sai_de_waiting(self) -> None:
        """**A fronteira inteira, numa assercao.**

        O `ESTADOS_QUE_FECHAM` e o predicado do `SQL_FECHAR` do HND, e com
        `waiting` dentro dele o `#fechar` escrevia `resumed` antes de o
        *compare-and-set* desta rota poder vencer: zero linhas, 200 `repetido`
        ao pedido legitimo, e o `interrupt()` do `handoff_wait` pendente para
        sempre. Nao era uma intercalacao rara — era o caminho feliz.

        A emenda 1.42 (dicionario §3.32) poe-no a `["degraded"]`, e a particao
        passa a ser enunciavel: o HND nunca tira uma passagem de `waiting`; o AGR
        nunca tira uma de `degraded`.
        """
        import re

        bloco = re.search(
            r"ESTADOS_QUE_FECHAM:\s*readonly EstadoDeHandoff\[\]\s*=\s*\[(.*?)\]",
            self.estados_ts,
            re.DOTALL,
        )
        self.assertIsNotNone(bloco, "o `ESTADOS_QUE_FECHAM` do HND mudou de forma")
        de_la = tuple(re.findall(r'"([a-z_]+)"', bloco.group(1)))
        self.assertEqual(de_la, ("degraded",))
        self.assertNotIn(
            "waiting",
            de_la,
            "sair de waiting e desta rota, nos tres desfechos: dicionario §3.32",
        )

    def test_os_tres_estados_que_o_cas_escreve_nao_estao_na_lista_do_hnd(self) -> None:
        """E o controlo positivo da assercao de cima, pelo lado dos valores.

        Sem ele, `ESTADOS_QUE_FECHAM = []` passava o teste anterior e dizia
        outra coisa: que o HND nao fecha nada. O que se afirma e a **particao**,
        e para isso ela tem de ter os dois lados.
        """
        import re

        bloco = re.search(
            r"ESTADOS_QUE_FECHAM:\s*readonly EstadoDeHandoff\[\]\s*=\s*\[(.*?)\]",
            self.estados_ts,
            re.DOTALL,
        )
        de_la = set(re.findall(r'"([a-z_]+)"', bloco.group(1)))
        escritos_pelo_cas = set(maquina.ESTADO_DO_DESFECHO.values())
        self.assertEqual(de_la & escritos_pelo_cas, set())
        self.assertTrue(de_la, "e o HND tem de continuar a fechar alguma coisa")

    def test_o_caminho_da_rota_e_o_mesmo_nos_dois_lados(self) -> None:
        from kamba_agr.api_interna import rotas

        caminhos = {
            rota.path
            for rota in rotas(
                credencial=lambda: CREDENCIAL,
                executar=None,  # type: ignore[arg-type]
                admissao=None,  # type: ignore[arg-type]
                trancas=None,
            )
        }
        self.assertIn("/internal/resume", caminhos)
        self.assertIn(
            'CAMINHO_DA_RETOMA = "/internal/resume"',
            self.retoma_ts,
            "o cliente do HND tem de apontar para a rota que existe",
        )

    def test_o_cabecalho_do_bot_e_o_mesmo_nos_dois_lados(self) -> None:
        """Uma cadeia de texto em dois idiomas: o unico laco e este ensaio."""
        self.assertIn(
            f'CABECALHO_DO_BOT = "{CABECALHO_DO_BOT}"',
            self.retoma_ts,
        )

    def test_a_credencial_de_rede_tambem_vai_no_pedido_do_hnd(self) -> None:
        """**As duas credenciais, e nao uma.**

        A rota pede ambas e a ordem e a do custo (§3.32). Um cliente que levasse
        so o `secret` do bot levava 401 em **todas** as retomas, e o sintoma
        eram conversas mortas — o mesmo sintoma do defeito que a emenda 1.42
        corrige, com outra causa.
        """
        from kamba_agr.api_interna import CABECALHO

        self.assertIn("CABECALHO_INTERNO", self.retoma_ts)
        self.assertIn(f'[CABECALHO_DO_BOT]: segredo', self.retoma_ts)
        self.assertEqual(CABECALHO, "x-kamba-interno")

    def test_o_corpo_que_o_hnd_envia_sao_os_tres_campos_da_rota(self) -> None:
        """A forma fechada do §3.32, confrontada com o que o cliente escreve.

        A rota recusa com 400 um corpo cujo conjunto de chaves nao seja
        **exactamente** o dela (`set(corpo) != set(CAMPOS_DA_RETOMA)`), pelo que
        um campo a mais ou a menos do outro lado era 400 em producao e nenhum
        ensaio a apanha-lo.
        """
        import re

        from kamba_agr.api_interna import CAMPOS_DA_RETOMA

        corpo = re.search(
            r"body: JSON\.stringify\(\{(.*?)\}\)", self.retoma_ts, re.DOTALL
        )
        self.assertIsNotNone(corpo, "o corpo do cliente do HND mudou de forma")
        campos = tuple(re.findall(r"^\s*([a-z_]+):", corpo.group(1), re.M))
        self.assertEqual(sorted(campos), sorted(CAMPOS_DA_RETOMA))
        # E **nenhum** deles e o `tenant_id` ou o `resolver`: o primeiro sai do
        # prefixo do `thread_id` e o segundo nunca entra no AGR (ADR-010).
        self.assertNotIn("tenant_id", campos)
        self.assertNotIn("resolver", campos)

    def test_os_desfechos_que_o_hnd_le_sao_os_que_esta_rota_devolve(self) -> None:
        import re

        bloco = re.search(
            r"DESFECHOS_DA_RETOMA = \[(.*?)\] as const", self.retoma_ts, re.DOTALL
        )
        self.assertIsNotNone(bloco, "o `DESFECHOS_DA_RETOMA` do HND mudou de forma")
        de_la = tuple(re.findall(r'"([a-z_]+)"', bloco.group(1)))
        self.assertEqual(de_la, DESFECHOS_DA_RETOMA)

    def test_os_outcomes_que_o_hnd_envia_sao_os_tres_do_1101(self) -> None:
        """O `outcome` atravessa o `interrupt()` sem traducao, e sao tres."""
        self.assertEqual(maquina.DESFECHOS, ("resolved", "timeout", "cancelled"))
        self.assertEqual(len(maquina.ESTADO_DO_DESFECHO), 3)

    def test_o_resolver_tem_instrucao_propria_e_sai_do_fecho(self) -> None:
        """A outra metade da emenda 1.42, e e a que o ADR-010 obriga.

        O `resolver` nao entra no corpo da retoma — o AGR nunca aprende a
        identidade do agente —, pelo que tem de ser o HND a escreve-lo. E tem de
        ser numa instrucao **separada** do `status`, porque a que o escrevia
        deixou de correr: com ele ainda no `SQL_FECHAR`, a coluna ficava por
        escrever em caminho nenhum, que e o defeito que o KAM-019 ja pagou uma
        vez (achado 9 do bloco dele).
        """
        self.assertIn("SQL_MARCAR_RESOLVER", self.consultas_ts)
        self.assertIn("SET resolver = $3", self.consultas_ts)
        self.assertIn("AND status = 'waiting'", self.consultas_ts)
        # E o `SQL_FECHAR` ja nao o leva: um `COALESCE($4, resolver)` que recebe
        # `null` em todas as chamadas e um caminho inexistente a parecer um
        # caminho.
        fecho = self.consultas_ts.split("export const SQL_FECHAR = `")[1].split("`")[0]
        self.assertNotIn("resolver", fecho)
        self.assertIn("status = ANY($3::text[])", fecho)


if __name__ == "__main__":
    unittest.main()
