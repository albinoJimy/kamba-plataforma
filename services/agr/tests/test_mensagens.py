"""A mensagem de texto do turno pelo `message_id` (KAM-223), sem base.

O que aqui se mede e a **forma** e a **ligacao**: o campo no contrato, a
instrucao que le a linha, a janela redigida antes do `ainvoke`, a recusa de um
`message_id` alheio, o canal da resposta e a credencial do painel. A semantica
contra o PostgreSQL — a RLS da `platform.agent_messages`, os `CHECK` — e da
*suite* do *gate* 8, quando a revisao da tabela existir.

**O duplo de ligacao le o texto da instrucao, e nao decide por argumento**: os
filtros que aplica sao as colunas que a clausula `WHERE` nomeia, casadas com os
parametros pela ordem dos `%s`, e a condicao da persona e o `EXISTS` sobre
`platform.contacts` avaliam-se pelas condicoes que o texto escreve. Com o
`AND m.conversation_id = %s` apagado, a linha de outra conversa passa a
encontrar-se; com a condicao da persona apagada (ou o `c.papel = 'dono'`), a de
um contacto que nao e o dono — e os ensaios ficam vermelhos (a licao de um duplo
que ficava verde com o predicado apagado). O canario `TestODuploMorde` prova-o.
"""

from __future__ import annotations

import asyncio
import json
import re
import unittest
import uuid
from pathlib import Path
from typing import Any
from unittest import mock

from apoio import CREDENCIAL, TrancaFalsa, como_json, invocacao_crua, pedir
from test_saida import Base as BaseDeRespostas
from test_saida import Ligacao as LigacaoDeRespostas

from kamba_agr import mensagens
from kamba_agr.admissao import Admissao, Pendente, Tectos
from kamba_agr.api_interna import (
    CABECALHO,
    SEGREDO_DO_PAINEL,
    invocacao_do_painel_admitida,
    rotas,
)
from kamba_agr.app import create_app
from kamba_agr.contexto import InvocacaoInvalidaError, ler_invocacao
from kamba_agr.guardas import regras
from kamba_agr.mensagens import (
    CODIGO_NAO_ENCONTRADA,
    LeitorDeMensagens,
    LeituraDeMensagensPorLigarError,
    MensagemNaoEncontradaError,
    ler_mensagem_sincrono,
)
from kamba_agr.metricas import METRICAS
from kamba_agr.saida import CANAL_DO_TURNO, SaidaPorEvento, canal_do_turno
from kamba_agr.turno import DesfechoDoTurno, ExecutorDeTurnos, Palavra
from langgraph.checkpoint.memory import InMemorySaver
from test_vendedor import montar as montar_vendedor

#: A credencial do painel nas baterias. **Nao e um segredo**, pela razao da
#: `CREDENCIAL` do `apoio.py`: tem espacos, e o *gate* 9 recusa cadeias com
#: forma de segredo.
CREDENCIAL_DO_PAINEL = "credencial de teste do painel"

#: Um PAN de teste (Luhn valido), o do `test_guardas.py`.
PAN = "4111111111111111"


# ---------------------------------------------------------------------------
# O duplo da base: a `platform.agent_messages`, lida pelo texto da instrucao


class BaseDeMensagens:
    """As linhas da `platform.agent_messages`, e o que se fez a cada ligacao."""

    def __init__(self) -> None:
        self.linhas: list[dict[str, str]] = []
        #: A `platform.contacts`, so as colunas que a instrucao le.
        self.contactos: list[dict[str, Any]] = []
        self.instrucoes: list[str] = []
        self.abertas = 0
        self.fechadas = 0
        self.commits = 0

    def contacto(self, tenant_id: str, contact_id: str, papel: str, **mais: Any) -> None:
        self.contactos.append(
            {
                "tenant_id": tenant_id,
                "contact_id": contact_id,
                "papel": papel,
                "erased_at": mais.get("erased_at"),
                "merged_into": mais.get("merged_into"),
            }
        )

    def gravar(
        self,
        invocacao: Any,
        texto: str,
        canal: str = "painel",
        papel: str | None = "dono",
        **sobrepor: str,
    ) -> str:
        """Uma linha para a invocacao (ou para outra conversa, com `sobrepor`).

        Com `papel`, o contacto da linha entra tambem na `contacts` com esse
        papel — por omissao `dono`, que e quem escreve no painel.
        """
        linha = {
            "message_id": sobrepor.get("message_id", invocacao.message_id),
            "tenant_id": sobrepor.get("tenant_id", invocacao.tenant_id),
            "contact_id": sobrepor.get("contact_id", invocacao.contact_id),
            "conversation_id": sobrepor.get("conversation_id", invocacao.conversation_id),
            "canal": canal,
            "texto": texto,
        }
        self.linhas.append(linha)
        if papel is not None:
            self.contacto(linha["tenant_id"], linha["contact_id"], papel)
        return linha["message_id"]


_WHERE = re.compile(r"\bWHERE\b(.*)$", re.IGNORECASE | re.DOTALL)
#: `m.coluna = %s`: um filtro da linha, com o parametro na posicao do `%s`.
_CONDICAO = re.compile(r"\bm\.([a-z_]+)\s*=\s*%s")
#: `(%s <> 'dono' OR EXISTS (SELECT 1 FROM platform.contacts c WHERE ...))`.
_PERSONA = re.compile(
    r"\(\s*%s\s*<>\s*'([a-z]+)'\s+OR\s+EXISTS\s*\(\s*SELECT 1 FROM platform\.contacts c"
    r"\s+WHERE\s+(.*?)\s*\)\s*\)",
    re.DOTALL,
)
_COM_A_LINHA = re.compile(r"\Ac\.([a-z_]+)\s*=\s*m\.([a-z_]+)\Z")
_COM_LITERAL = re.compile(r"\Ac\.([a-z_]+)\s*=\s*'([^']*)'\Z")
_E_NULO = re.compile(r"\Ac\.([a-z_]+)\s+IS\s+NULL\Z")


def _condicao_do_contacto(texto: str):
    """Uma condicao do `EXISTS`, como funcao `(contacto, linha) -> bool`."""
    texto = texto.strip()
    if achado := _COM_A_LINHA.match(texto):
        c, m = achado.groups()
        return lambda contacto, linha: contacto[c] == linha[m]
    if achado := _COM_LITERAL.match(texto):
        c, valor = achado.groups()
        return lambda contacto, _linha: contacto[c] == valor
    if achado := _E_NULO.match(texto):
        c = achado.group(1)
        return lambda contacto, _linha: contacto[c] is None
    raise AssertionError(f"condicao do EXISTS sem semantica no duplo: {texto}")


class CursorDeMensagens:
    def __init__(self, base: BaseDeMensagens) -> None:
        self.base = base
        self.tenant: str | None = None
        self.resultado: list[tuple[Any, ...]] = []

    def execute(self, sql: str, p: tuple = ()) -> None:
        self.base.instrucoes.append(sql)
        self.resultado = []
        if sql.startswith("SELECT set_config('app.tenant_id'"):
            self.tenant = p[0]
            self.resultado = [(p[0],)]
            return
        plano = " ".join(sql.split())
        if not plano.startswith("SELECT m.texto, m.canal FROM platform.agent_messages m "):
            raise AssertionError(f"instrucao sem semantica no duplo: {plano[:80]}")
        # Os parametros casam com os `%s` pela ordem em que aparecem no texto; um
        # numero diferente e o que o controlador real recusaria.
        if plano.count("%s") != len(p):
            raise AssertionError("parametros e marcadores em numero diferente")
        achado = _WHERE.search(plano)
        onde = achado.group(1) if achado else ""
        marcadores = sorted(
            [(a.start(), ("coluna", a.group(1))) for a in _CONDICAO.finditer(onde)]
            + [(a.start(), ("persona", a)) for a in _PERSONA.finditer(onde)],
            key=lambda par: par[0],
        )
        if len(marcadores) != len(p):
            raise AssertionError("um %s que o duplo nao sabe ler")
        filtros: dict[str, Any] = {}
        personas: list[tuple[Any, str, list[Any]]] = []
        for (_pos, (tipo, valor)), parametro in zip(marcadores, p, strict=True):
            if tipo == "coluna":
                filtros[valor] = parametro
            else:
                condicoes = [
                    _condicao_do_contacto(parte)
                    for parte in re.split(r"\s+AND\s+", valor.group(2))
                ]
                personas.append((parametro, valor.group(1), condicoes))
        for linha in self.base.linhas:
            # A RLS, pelo lado do duplo: so as linhas do tenant do contexto.
            if linha["tenant_id"] != self.tenant:
                continue
            if not all(linha[coluna] == v for coluna, v in filtros.items()):
                continue
            if not all(self._persona_admite(linha, *persona) for persona in personas):
                continue
            self.resultado.append((linha["texto"], linha["canal"]))

    def _persona_admite(
        self, linha: dict[str, str], persona: Any, restrita: str, condicoes: list[Any]
    ) -> bool:
        """`%s <> '<restrita>' OR EXISTS (...)`, com a RLS tambem na `contacts`."""
        if persona != restrita:
            return True
        return any(
            contacto["tenant_id"] == self.tenant
            and all(condicao(contacto, linha) for condicao in condicoes)
            for contacto in self.base.contactos
        )

    def fetchone(self) -> tuple[Any, ...] | None:
        return self.resultado[0] if self.resultado else None

    def close(self) -> None:
        return None


class LigacaoDeMensagens:
    autocommit = False

    def __init__(self, base: BaseDeMensagens) -> None:
        self.base = base
        base.abertas += 1

    def cursor(self) -> CursorDeMensagens:
        return CursorDeMensagens(self.base)

    def commit(self) -> None:
        self.base.commits += 1

    def rollback(self) -> None:
        return None

    def close(self) -> None:
        self.base.fechadas += 1


def invocacao_do_painel(**sobrepor: Any):
    """A invocacao de um turno do painel: persona `dono`, `message_id`, e o
    `wamid` `painel.{message_id}` (o esquema nao aceita `:` no `wamid`)."""
    message_id = sobrepor.pop("message_id", str(uuid.uuid4()))
    campos: dict[str, Any] = {
        "persona": "dono",
        "message_id": message_id,
        "wamid": f"painel.{message_id}",
    }
    campos.update(sobrepor)
    return invocacao_crua(**campos)


# ---------------------------------------------------------------------------
# O campo no contrato


class TestOCampoNoContrato(unittest.TestCase):
    def test_um_uuid_canonico_entra(self) -> None:
        message_id = str(uuid.uuid4())
        invocacao = ler_invocacao(invocacao_crua(message_id=message_id))
        self.assertEqual(invocacao.message_id, message_id)

    def test_sem_o_campo_e_none(self) -> None:
        self.assertIsNone(ler_invocacao(invocacao_crua()).message_id)

    def test_o_wamid_do_painel_tem_a_forma_do_contrato(self) -> None:
        invocacao = ler_invocacao(invocacao_do_painel())
        self.assertEqual(invocacao.turn_id, f"painel.{invocacao.message_id}")
        self.assertEqual(invocacao.persona, "dono")

    def test_um_valor_com_outra_forma_e_recusado_sem_o_repetir(self) -> None:
        canonico = str(uuid.uuid4())
        for valor in (
            None,
            "",
            canonico.upper(),
            "{" + canonico + "}",
            canonico.replace("-", ""),
            canonico + " ",
            "923456789",
            7,
            [canonico],
        ):
            with self.subTest(valor=valor):
                with self.assertRaises(InvocacaoInvalidaError) as capturado:
                    ler_invocacao(invocacao_crua(message_id=valor))
                self.assertEqual(capturado.exception.codigo, "campo_invalido_message_id")
                if isinstance(valor, str) and valor:
                    self.assertNotIn(valor, str(capturado.exception))


# ---------------------------------------------------------------------------
# A instrucao e a leitura


class TestLeitura(unittest.TestCase):
    def setUp(self) -> None:
        self.base = BaseDeMensagens()

    def ler(self, invocacao: Any):
        return ler_mensagem_sincrono(LigacaoDeMensagens(self.base), invocacao)

    def test_a_instrucao_filtra_pelos_quatro_identificadores(self) -> None:
        plano = " ".join(mensagens.SQL_LER_MENSAGEM.split())
        onde = _WHERE.search(plano).group(1)
        condicoes = _CONDICAO.findall(onde)
        self.assertEqual(
            condicoes, ["message_id", "tenant_id", "contact_id", "conversation_id"]
        )
        self.assertIn("FROM platform.agent_messages m", plano)
        [persona] = _PERSONA.findall(onde)
        self.assertEqual(persona[0], "dono")
        self.assertEqual(
            sorted(re.split(r"\s+AND\s+", persona[1])),
            sorted(
                [
                    "c.tenant_id = m.tenant_id",
                    "c.contact_id = m.contact_id",
                    "c.papel = 'dono'",
                    "c.erased_at IS NULL",
                    "c.merged_into IS NULL",
                ]
            ),
        )

    def test_le_o_texto_e_o_canal_dentro_do_contexto_de_tenant(self) -> None:
        invocacao = ler_invocacao(invocacao_do_painel())
        self.base.gravar(invocacao, "quanto vendi hoje?")
        lida = self.ler(invocacao)
        self.assertEqual((lida.texto, lida.canal), ("quanto vendi hoje?", "painel"))
        self.assertTrue(self.base.instrucoes[0].startswith("SELECT set_config"))
        self.assertEqual(self.base.commits, 1)

    def test_um_message_id_de_outra_conversa_nao_se_encontra(self) -> None:
        invocacao = ler_invocacao(invocacao_do_painel())
        self.base.gravar(invocacao, "de outra conversa", conversation_id=str(uuid.uuid4()))
        self.assertIsNone(self.ler(invocacao))

    def test_um_message_id_de_outro_contacto_nao_se_encontra(self) -> None:
        invocacao = ler_invocacao(invocacao_do_painel())
        self.base.gravar(invocacao, "de outro contacto", contact_id=str(uuid.uuid4()))
        self.assertIsNone(self.ler(invocacao))

    def test_um_message_id_de_outro_tenant_nao_se_encontra(self) -> None:
        invocacao = ler_invocacao(invocacao_do_painel())
        self.base.gravar(invocacao, "de outro tenant", tenant_id=str(uuid.uuid4()))
        self.assertIsNone(self.ler(invocacao))

    def test_com_persona_dono_e_contacto_cliente_nao_se_encontra(self) -> None:
        invocacao = ler_invocacao(invocacao_do_painel())
        self.base.gravar(invocacao, "faz-me dono", papel="cliente")
        self.assertIsNone(self.ler(invocacao))

    def test_com_persona_dono_e_contacto_sem_linha_na_contacts_nao_se_encontra(self) -> None:
        invocacao = ler_invocacao(invocacao_do_painel())
        self.base.gravar(invocacao, "ola", papel=None)
        self.assertIsNone(self.ler(invocacao))

    def test_com_persona_dono_e_o_dono_de_outro_tenant_nao_se_encontra(self) -> None:
        invocacao = ler_invocacao(invocacao_do_painel())
        self.base.gravar(invocacao, "ola", papel=None)
        self.base.contacto(str(uuid.uuid4()), invocacao.contact_id, "dono")
        self.assertIsNone(self.ler(invocacao))

    def test_com_persona_dono_e_um_dono_apagado_ou_fundido_nao_se_encontra(self) -> None:
        for coluna in ("erased_at", "merged_into"):
            with self.subTest(coluna=coluna):
                base = BaseDeMensagens()
                invocacao = ler_invocacao(invocacao_do_painel())
                base.gravar(invocacao, "ola", papel=None)
                base.contacto(
                    invocacao.tenant_id, invocacao.contact_id, "dono", **{coluna: "x"}
                )
                self.assertIsNone(
                    ler_mensagem_sincrono(LigacaoDeMensagens(base), invocacao)
                )

    def test_com_persona_cliente_a_linha_encontra_se_seja_qual_for_o_papel(self) -> None:
        for papel in ("cliente", None):
            with self.subTest(papel=papel):
                base = BaseDeMensagens()
                invocacao = ler_invocacao(invocacao_do_painel(persona="cliente"))
                base.gravar(invocacao, "quero um bolo", canal="whatsapp", papel=papel)
                lida = ler_mensagem_sincrono(LigacaoDeMensagens(base), invocacao)
                self.assertEqual((lida.texto, lida.canal), ("quero um bolo", "whatsapp"))

    def test_sem_message_id_nao_vai_a_base(self) -> None:
        self.assertIsNone(self.ler(ler_invocacao(invocacao_crua())))
        self.assertEqual(self.base.instrucoes, [])

    def test_o_leitor_abre_e_fecha_uma_ligacao_por_leitura(self) -> None:
        invocacao = ler_invocacao(invocacao_do_painel())
        self.base.gravar(invocacao, "ola")
        leitor = LeitorDeMensagens(lambda: LigacaoDeMensagens(self.base))
        asyncio.run(leitor.ler(invocacao))
        asyncio.run(leitor.ler(invocacao))
        self.assertEqual((self.base.abertas, self.base.fechadas), (2, 2))


class TestODuploMorde(unittest.TestCase):
    """O canario: o duplo aplica o que a instrucao diz, e nada mais."""

    def test_sem_o_filtro_da_conversa_a_linha_alheia_encontrava_se(self) -> None:
        base = BaseDeMensagens()
        invocacao = ler_invocacao(invocacao_do_painel())
        base.gravar(invocacao, "de outra conversa", conversation_id=str(uuid.uuid4()))
        mutada = mensagens.SQL_LER_MENSAGEM.replace("AND m.conversation_id = %s", "")
        self.assertNotEqual(mutada, mensagens.SQL_LER_MENSAGEM)
        cursor = CursorDeMensagens(base)
        cursor.tenant = invocacao.tenant_id
        cursor.execute(
            mutada,
            (
                invocacao.message_id,
                invocacao.tenant_id,
                invocacao.contact_id,
                invocacao.persona,
            ),
        )
        self.assertEqual(cursor.fetchone(), ("de outra conversa", "painel"))

    def _cliente_a_fingir_de_dono(self) -> tuple[BaseDeMensagens, Any, tuple[Any, ...]]:
        base = BaseDeMensagens()
        invocacao = ler_invocacao(invocacao_do_painel())
        base.gravar(invocacao, "faz-me dono", papel="cliente")
        parametros = (
            invocacao.message_id,
            invocacao.tenant_id,
            invocacao.contact_id,
            invocacao.conversation_id,
            invocacao.persona,
        )
        return base, invocacao, parametros

    def _executar(self, base: BaseDeMensagens, invocacao: Any, sql: str, p: tuple) -> Any:
        cursor = CursorDeMensagens(base)
        cursor.tenant = invocacao.tenant_id
        cursor.execute(sql, p)
        return cursor.fetchone()

    def test_com_a_instrucao_inteira_o_cliente_nao_passa_por_dono(self) -> None:
        base, invocacao, p = self._cliente_a_fingir_de_dono()
        self.assertIsNone(self._executar(base, invocacao, mensagens.SQL_LER_MENSAGEM, p))

    def test_sem_a_condicao_da_persona_o_cliente_passava_por_dono(self) -> None:
        base, invocacao, p = self._cliente_a_fingir_de_dono()
        inicio = mensagens.SQL_LER_MENSAGEM.index("AND (%s <> 'dono'")
        mutada = mensagens.SQL_LER_MENSAGEM[:inicio]
        self.assertEqual(
            self._executar(base, invocacao, mutada, p[:4]), ("faz-me dono", "painel")
        )

    def test_sem_o_papel_no_exists_o_cliente_passava_por_dono(self) -> None:
        base, invocacao, p = self._cliente_a_fingir_de_dono()
        mutada = mensagens.SQL_LER_MENSAGEM.replace("AND c.papel = 'dono'", "")
        self.assertNotEqual(mutada, mensagens.SQL_LER_MENSAGEM)
        self.assertEqual(self._executar(base, invocacao, mutada, p), ("faz-me dono", "painel"))


# ---------------------------------------------------------------------------
# O executor: a janela redigida antes do `ainvoke`, a recusa e o canal


class GrafoQueRegista:
    """Regista o estado **de entrada** de cada `ainvoke`, e o canal que ve."""

    def __init__(self, ao_correr=None) -> None:
        self.entradas: list[dict[str, Any]] = []
        self.canais: list[str | None] = []
        self._ao_correr = ao_correr

    async def ainvoke(self, estado: dict[str, Any], config: dict[str, Any]) -> None:
        self.entradas.append(json.loads(json.dumps(estado)))
        self.canais.append(CANAL_DO_TURNO.get())
        if self._ao_correr is not None:
            # Uma tarefa nova e uma *thread*, como os nos do LangGraph.
            await asyncio.create_task(asyncio.to_thread(self._ao_correr, estado))


#: «Nao ha conversa» — distinto de passar uma `Palavra`.
_SEM_CONVERSA = object()


def executor_com(
    base: BaseDeMensagens,
    grafo: GrafoQueRegista,
    ler: bool = True,
    palavra: Any = Palavra(modo="bot", handoff_a_espera=False),
    reencaminhados: list[Any] | None = None,
):
    async def ler_palavra(_inv: Any) -> Palavra | None:
        return None if palavra is _SEM_CONVERSA else palavra

    async def reencaminhar(invs: Any) -> None:
        if reencaminhados is not None:
            reencaminhados.extend(invs)

    return ExecutorDeTurnos(
        trancas=TrancaFalsa(),
        ler_palavra=ler_palavra,
        grafos=lambda _inv: grafo,
        reencaminhar=reencaminhar,
        admissao=Admissao(tectos=Tectos(coalescencia_ms=0)),
        ler_mensagem=(
            LeitorDeMensagens(lambda: LigacaoDeMensagens(base)).ler if ler else None
        ),
    )


async def correr_lote(executor: ExecutorDeTurnos, invocacoes: list[Any]):
    """O `_correr_lote` na tarefa do ensaio, para ver o `ContextVar` depois."""
    pendentes = [Pendente(invocacao=i, chegou_em=0.0) for i in invocacoes]
    await executor._correr_lote(invocacoes[0].thread_id, pendentes)
    resultados = []
    for pendente in pendentes:
        try:
            resultados.append(await pendente.espera)
        except BaseException as erro:  # noqa: BLE001 — o ensaio quer o erro
            resultados.append(erro)
    return resultados


class TestExecutor(unittest.TestCase):
    def setUp(self) -> None:
        METRICAS.repor()
        self.base = BaseDeMensagens()
        self.grafo = GrafoQueRegista()

    def test_o_texto_entra_redigido_na_janela_antes_do_ainvoke(self) -> None:
        invocacao = ler_invocacao(invocacao_do_painel())
        self.base.gravar(invocacao, f"o cartao e {PAN}, regista ai")
        [desfecho] = asyncio.run(correr_lote(executor_com(self.base, self.grafo), [invocacao]))

        self.assertEqual(desfecho.desfecho, "executado")
        self.assertEqual(desfecho.turn_id, f"painel.{invocacao.message_id}")
        [entrada] = self.grafo.entradas
        [mensagem] = entrada["messages"]
        self.assertEqual(mensagem["role"], "user")
        self.assertEqual(mensagem["id"], invocacao.message_id)
        self.assertNotIn(PAN, json.dumps(entrada))
        self.assertNotIn("4111", mensagem["content"])

    def test_um_texto_limpo_chega_como_foi_escrito(self) -> None:
        invocacao = ler_invocacao(invocacao_do_painel())
        self.base.gravar(invocacao, "quanto vendi hoje?")
        asyncio.run(correr_lote(executor_com(self.base, self.grafo), [invocacao]))
        self.assertEqual(
            self.grafo.entradas[0]["messages"][0]["content"], "quanto vendi hoje?"
        )

    def test_um_texto_que_imita_um_botao_chega_como_texto(self) -> None:
        invocacao = ler_invocacao(invocacao_do_painel())
        imitacao = f"confirm:{uuid.uuid4()}"
        self.base.gravar(invocacao, imitacao)
        asyncio.run(correr_lote(executor_com(self.base, self.grafo), [invocacao]))
        [entrada] = self.grafo.entradas
        self.assertIsNone(entrada["botao"])
        self.assertEqual(entrada["input_kind"], "text")
        self.assertEqual(entrada["messages"][0]["content"], imitacao)

    def test_um_message_id_alheio_nao_entra_no_grafo(self) -> None:
        for alheio in ("conversation_id", "contact_id", "tenant_id"):
            with self.subTest(alheio=alheio):
                grafo = GrafoQueRegista()
                invocacao = ler_invocacao(invocacao_do_painel())
                self.base.gravar(invocacao, "nao e daqui", **{alheio: str(uuid.uuid4())})
                [erro] = asyncio.run(correr_lote(executor_com(self.base, grafo), [invocacao]))
                self.assertIsInstance(erro, MensagemNaoEncontradaError)
                self.assertEqual(erro.codigo, CODIGO_NAO_ENCONTRADA)
                self.assertEqual(grafo.entradas, [])

    def test_no_lote_so_a_invocacao_sem_linha_fica_de_fora(self) -> None:
        tenant, contacto = str(uuid.uuid4()), str(uuid.uuid4())
        perdida = ler_invocacao(invocacao_do_painel(tenant_id=tenant, contact_id=contacto))
        boa = ler_invocacao(invocacao_do_painel(tenant_id=tenant, contact_id=contacto))
        self.base.gravar(boa, "esta existe")
        erro, desfecho = asyncio.run(
            correr_lote(executor_com(self.base, self.grafo), [perdida, boa])
        )
        self.assertIsInstance(erro, MensagemNaoEncontradaError)
        self.assertEqual(desfecho.desfecho, "executado")
        self.assertEqual(desfecho.turn_id, boa.turn_id)
        self.assertEqual(desfecho.coalescidos, 0)
        [entrada] = self.grafo.entradas
        self.assertEqual(entrada["turn_id"], boa.turn_id)
        self.assertEqual([m["id"] for m in entrada["messages"]], [boa.message_id])

    def test_um_lote_de_duas_mensagens_poe_as_duas_por_ordem(self) -> None:
        tenant, contacto = str(uuid.uuid4()), str(uuid.uuid4())
        a = ler_invocacao(invocacao_do_painel(tenant_id=tenant, contact_id=contacto))
        b = ler_invocacao(invocacao_do_painel(tenant_id=tenant, contact_id=contacto))
        self.base.gravar(a, "primeira")
        self.base.gravar(b, f"segunda {PAN}")
        asyncio.run(correr_lote(executor_com(self.base, self.grafo), [a, b]))
        [entrada] = self.grafo.entradas
        self.assertEqual([m["id"] for m in entrada["messages"]], [a.message_id, b.message_id])
        self.assertNotIn(PAN, json.dumps(entrada))

    def test_sem_message_id_a_janela_nasce_vazia_e_nao_vai_a_base(self) -> None:
        invocacao = ler_invocacao(invocacao_crua())
        asyncio.run(correr_lote(executor_com(self.base, self.grafo), [invocacao]))
        self.assertEqual(self.grafo.entradas[0]["messages"], [])
        self.assertEqual(self.base.abertas, 0)

    def test_com_message_id_e_sem_porta_levanta_e_nao_corre(self) -> None:
        invocacao = ler_invocacao(invocacao_do_painel())
        self.base.gravar(invocacao, "ola")
        [erro] = asyncio.run(
            correr_lote(executor_com(self.base, self.grafo, ler=False), [invocacao])
        )
        self.assertIsInstance(erro, LeituraDeMensagensPorLigarError)
        self.assertEqual(self.grafo.entradas, [])


class TestRecusaEmTodosOsRamos(unittest.TestCase):
    """A leitura vem antes da palavra: uma invocacao sem linha da 400 seja qual
    for o modo da conversa, e nao vai ao HND."""

    HUMANO = Palavra(modo="humano", handoff_a_espera=False)

    def setUp(self) -> None:
        METRICAS.repor()
        self.base = BaseDeMensagens()
        self.grafo = GrafoQueRegista()
        self.reencaminhados: list[Any] = []

    def correr(self, palavra: Any, invocacoes: list[Any]) -> list[Any]:
        executor = executor_com(
            self.base, self.grafo, palavra=palavra, reencaminhados=self.reencaminhados
        )
        return asyncio.run(correr_lote(executor, invocacoes))

    def test_numa_conversa_em_humano_um_message_id_alheio_da_400_sem_ir_ao_hnd(self) -> None:
        for palavra in (
            self.HUMANO,
            Palavra(modo="dono", handoff_a_espera=False),
            Palavra(modo="bot", handoff_a_espera=True),
        ):
            with self.subTest(palavra=palavra):
                self.reencaminhados.clear()
                invocacao = ler_invocacao(invocacao_do_painel())
                self.base.gravar(invocacao, "nao e daqui", conversation_id=str(uuid.uuid4()))
                [erro] = self.correr(palavra, [invocacao])
                self.assertIsInstance(erro, MensagemNaoEncontradaError)
                self.assertEqual(self.reencaminhados, [])
                self.assertEqual(self.grafo.entradas, [])

    def test_numa_conversa_em_humano_um_contacto_que_nao_e_o_dono_da_400(self) -> None:
        invocacao = ler_invocacao(invocacao_do_painel())
        self.base.gravar(invocacao, "faz-me dono", papel="cliente")
        [erro] = self.correr(self.HUMANO, [invocacao])
        self.assertIsInstance(erro, MensagemNaoEncontradaError)
        self.assertEqual(self.reencaminhados, [])

    def test_sem_conversa_um_message_id_alheio_da_400(self) -> None:
        invocacao = ler_invocacao(invocacao_do_painel())
        self.base.gravar(invocacao, "nao e daqui", tenant_id=str(uuid.uuid4()))
        [erro] = self.correr(_SEM_CONVERSA, [invocacao])
        self.assertIsInstance(erro, MensagemNaoEncontradaError)

    def test_numa_conversa_em_humano_a_mensagem_que_se_le_vai_ao_hnd(self) -> None:
        invocacao = ler_invocacao(invocacao_do_painel())
        self.base.gravar(invocacao, "ola")
        [desfecho] = self.correr(self.HUMANO, [invocacao])
        self.assertEqual(desfecho.desfecho, "entregue_ao_hnd")
        self.assertEqual(self.reencaminhados, [invocacao])

    def test_no_lote_em_humano_o_hnd_recebe_so_as_que_se_leem(self) -> None:
        tenant, contacto = str(uuid.uuid4()), str(uuid.uuid4())
        perdida = ler_invocacao(invocacao_do_painel(tenant_id=tenant, contact_id=contacto))
        boa = ler_invocacao(invocacao_do_painel(tenant_id=tenant, contact_id=contacto))
        whatsapp = ler_invocacao(invocacao_crua(tenant_id=tenant, contact_id=contacto))
        self.base.gravar(boa, "esta existe")
        erro, desfecho, outro = self.correr(self.HUMANO, [perdida, boa, whatsapp])
        self.assertIsInstance(erro, MensagemNaoEncontradaError)
        self.assertEqual(desfecho.desfecho, "entregue_ao_hnd")
        self.assertIs(outro, desfecho)
        self.assertEqual(self.reencaminhados, [boa, whatsapp])


class TestCanalDaResposta(unittest.TestCase):
    """O canal da mensagem lida chega a `SaidaPorEvento` pelo `CANAL_DO_TURNO`."""

    def correr(self, canal: str | None) -> tuple[BaseDeRespostas, list[str | None], Any]:
        base = BaseDeMensagens()
        respostas = BaseDeRespostas()
        porta = SaidaPorEvento(lambda: LigacaoDeRespostas(respostas), canal_de=canal_do_turno)

        def responder(estado: dict[str, Any]) -> None:
            porta.enfileirar(estado, "Hoje vendeu tres.", chave=f"{estado['turn_id']}:0")

        grafo = GrafoQueRegista(ao_correr=responder)
        if canal is None:
            invocacao = ler_invocacao(invocacao_crua())
        else:
            invocacao = ler_invocacao(invocacao_do_painel())
            base.gravar(invocacao, "quanto vendi hoje?", canal=canal)

        async def turno() -> Any:
            await correr_lote(executor_com(base, grafo), [invocacao])
            return CANAL_DO_TURNO.get()

        depois = asyncio.run(turno())
        return respostas, grafo.canais, depois

    def test_o_turno_do_painel_responde_pelo_painel(self) -> None:
        respostas, canais, depois = self.correr("painel")
        self.assertEqual(canais, ["painel"])
        self.assertEqual(respostas.respostas[0]["canal"], "painel")
        self.assertIsNone(depois, "o finally do _correr_lote repoe o ContextVar")

    def test_uma_mensagem_do_whatsapp_responde_pelo_whatsapp(self) -> None:
        respostas, canais, _ = self.correr("whatsapp")
        self.assertEqual(canais, ["whatsapp"])
        self.assertEqual(respostas.respostas[0]["canal"], "whatsapp")

    def test_sem_mensagem_lida_e_o_whatsapp(self) -> None:
        respostas, canais, _ = self.correr(None)
        self.assertEqual(canais, [None])
        self.assertEqual(respostas.respostas[0]["canal"], "whatsapp")

    def test_fora_de_um_turno_e_o_whatsapp(self) -> None:
        self.assertEqual(canal_do_turno({}), "whatsapp")

    def test_um_valor_fora_dos_canais_cai_no_whatsapp(self) -> None:
        marca = CANAL_DO_TURNO.set("sms")
        try:
            self.assertEqual(canal_do_turno({}), "whatsapp")
        finally:
            CANAL_DO_TURNO.reset(marca)


# ---------------------------------------------------------------------------
# A rota: as duas credenciais, e a recusa que chega como 400


def aplicacao(executar, credencial_do_painel=lambda: CREDENCIAL_DO_PAINEL):
    return create_app(
        rotas_internas=rotas(
            credencial=lambda: CREDENCIAL,
            executar=executar,
            admissao=Admissao(tectos=Tectos()),
            trancas=TrancaFalsa(),
            credencial_do_painel=credencial_do_painel,
        )
    )


class TestCredencialDoPainel(unittest.IsolatedAsyncioTestCase):
    async def asyncSetUp(self) -> None:
        METRICAS.repor()
        self.corridas: list[Any] = []

        async def executar(invocacao):
            self.corridas.append(invocacao)
            return DesfechoDoTurno(desfecho="executado", turn_id=invocacao.turn_id)

        self.executar = executar

    async def pedir(self, corpo: dict[str, Any], credencial: str | None, **kw: Any):
        cabecalhos = {} if credencial is None else {CABECALHO: credencial}
        return await pedir(
            aplicacao(self.executar, **kw),
            "/internal/turn",
            "POST",
            como_json(corpo),
            cabecalhos,
        )

    def test_o_nome_do_segredo(self) -> None:
        self.assertEqual(SEGREDO_DO_PAINEL, "agr_painel_token")

    async def test_o_shim_passa_como_ate_aqui(self) -> None:
        estado, _, _ = await self.pedir(invocacao_crua(), CREDENCIAL)
        self.assertEqual(estado, 200)
        self.assertEqual(len(self.corridas), 1)

    async def test_o_painel_passa_com_o_turno_do_dono_com_mensagem(self) -> None:
        estado, _, corpo = await self.pedir(invocacao_do_painel(), CREDENCIAL_DO_PAINEL)
        self.assertEqual(estado, 200)
        self.assertEqual(json.loads(corpo)["outcome"], "executado")
        self.assertEqual(len(self.corridas), 1)

    async def test_o_painel_sem_dono_ou_sem_mensagem_e_a_mesma_401(self) -> None:
        sem_mensagem = invocacao_crua(persona="dono")
        sem_persona = invocacao_do_painel()
        del sem_persona["persona"]
        casos = {
            "persona cliente": invocacao_do_painel(persona="cliente"),
            "sem persona": sem_persona,
            "sem message_id": sem_mensagem,
        }
        _, _, referencia = await self.pedir(invocacao_crua(), None)
        for nome, corpo_do_pedido in casos.items():
            with self.subTest(nome):
                estado, _, corpo = await self.pedir(corpo_do_pedido, CREDENCIAL_DO_PAINEL)
                self.assertEqual(estado, 401)
                self.assertEqual(corpo, referencia)
        self.assertEqual(self.corridas, [])

    async def test_o_painel_com_botao_outro_type_ou_outro_wamid_e_a_mesma_401(self) -> None:
        message_id = str(uuid.uuid4())
        casos = {
            "botao de confirmacao": invocacao_do_painel(
                type="interactive", botao=f"confirm:{uuid.uuid4()}"
            ),
            "type interactive sem botao": invocacao_do_painel(type="interactive"),
            "type audio": invocacao_do_painel(type="audio"),
            "wamid de outro message_id": invocacao_do_painel(wamid=f"painel.{uuid.uuid4()}"),
            "wamid do whatsapp": invocacao_do_painel(
                wamid="wamid.HBgMMjQ0OTAwMDAwMDAwFQIAEhgg" + uuid.uuid4().hex[:8]
            ),
            "wamid com dois pontos": invocacao_do_painel(
                message_id=message_id, wamid=f"painel:{message_id}"
            ),
        }
        _, _, referencia = await self.pedir(invocacao_crua(), None)
        for nome, corpo_do_pedido in casos.items():
            with self.subTest(nome):
                # O corpo e um `agent_invocation` valido: a recusa e da
                # credencial, e nao do contrato.
                ler_invocacao(corpo_do_pedido)
                estado, _, corpo = await self.pedir(corpo_do_pedido, CREDENCIAL_DO_PAINEL)
                self.assertEqual(estado, 401)
                self.assertEqual(corpo, referencia)
        self.assertEqual(self.corridas, [])

    async def test_o_shim_continua_a_poder_mandar_um_botao(self) -> None:
        corpo = invocacao_crua(type="interactive", botao=f"confirm:{uuid.uuid4()}")
        estado, _, _ = await self.pedir(corpo, CREDENCIAL)
        self.assertEqual(estado, 200)

    async def test_sem_credencial_ou_com_a_errada_e_401(self) -> None:
        for credencial in (None, "outra credencial qualquer"):
            with self.subTest(credencial=credencial):
                estado, _, _ = await self.pedir(invocacao_do_painel(), credencial)
                self.assertEqual(estado, 401)
        self.assertEqual(self.corridas, [])

    async def test_sem_a_credencial_no_cofre_o_painel_fecha_e_o_shim_continua(self) -> None:
        def em_falta() -> str:
            raise KeyError("agr_painel_token")

        estado, _, _ = await self.pedir(
            invocacao_do_painel(), CREDENCIAL_DO_PAINEL, credencial_do_painel=em_falta
        )
        self.assertEqual(estado, 401)
        estado, _, _ = await self.pedir(
            invocacao_crua(), CREDENCIAL, credencial_do_painel=em_falta
        )
        self.assertEqual(estado, 200)

    async def test_sem_a_porta_do_painel_a_credencial_dele_e_401(self) -> None:
        estado, _, _ = await self.pedir(
            invocacao_do_painel(), CREDENCIAL_DO_PAINEL, credencial_do_painel=None
        )
        self.assertEqual(estado, 401)

    def test_a_regra_do_painel(self) -> None:
        self.assertTrue(invocacao_do_painel_admitida(ler_invocacao(invocacao_do_painel())))
        self.assertFalse(
            invocacao_do_painel_admitida(ler_invocacao(invocacao_do_painel(persona="cliente")))
        )
        self.assertFalse(
            invocacao_do_painel_admitida(ler_invocacao(invocacao_crua(persona="dono")))
        )
        self.assertFalse(
            invocacao_do_painel_admitida(
                ler_invocacao(invocacao_do_painel(type="interactive", botao="falar_com_humano"))
            )
        )
        self.assertFalse(
            invocacao_do_painel_admitida(
                ler_invocacao(invocacao_do_painel(wamid=f"painel.{uuid.uuid4()}"))
            )
        )


class TestARecusaChegaComo400(unittest.IsolatedAsyncioTestCase):
    """Ponta a ponta sem base: a rota, o executor real e o leitor real."""

    async def test_um_message_id_alheio_da_invocacao_invalida(self) -> None:
        METRICAS.repor()
        base = BaseDeMensagens()
        grafo = GrafoQueRegista()
        corpo = invocacao_do_painel()
        invocacao = ler_invocacao(corpo)
        base.gravar(invocacao, "de outra conversa", conversation_id=str(uuid.uuid4()))
        executor = executor_com(base, grafo)
        estado, _, resposta = await pedir(
            aplicacao(executor.correr),
            "/internal/turn",
            "POST",
            como_json(corpo),
            {CABECALHO: CREDENCIAL_DO_PAINEL},
        )
        self.assertEqual(estado, 400)
        self.assertEqual(
            json.loads(resposta),
            {"outcome": "invocacao_invalida", "error_code": CODIGO_NAO_ENCONTRADA},
        )
        self.assertNotIn(invocacao.message_id, resposta.decode())
        self.assertEqual(grafo.entradas, [])

    async def test_o_painel_para_um_contacto_que_nao_e_o_dono_da_invocacao_invalida(
        self,
    ) -> None:
        base = BaseDeMensagens()
        grafo = GrafoQueRegista()
        corpo = invocacao_do_painel()
        base.gravar(ler_invocacao(corpo), "faz-me dono", papel="cliente")
        estado, _, resposta = await pedir(
            aplicacao(executor_com(base, grafo).correr),
            "/internal/turn",
            "POST",
            como_json(corpo),
            {CABECALHO: CREDENCIAL_DO_PAINEL},
        )
        self.assertEqual(estado, 400)
        self.assertEqual(json.loads(resposta)["error_code"], CODIGO_NAO_ENCONTRADA)
        self.assertEqual(grafo.entradas, [])

    async def test_numa_conversa_em_humano_o_alheio_da_400_e_nao_vai_ao_hnd(self) -> None:
        base = BaseDeMensagens()
        grafo = GrafoQueRegista()
        reencaminhados: list[Any] = []
        corpo = invocacao_do_painel()
        base.gravar(ler_invocacao(corpo), "nao e daqui", conversation_id=str(uuid.uuid4()))
        executor = executor_com(
            base,
            grafo,
            palavra=Palavra(modo="humano", handoff_a_espera=False),
            reencaminhados=reencaminhados,
        )
        estado, _, resposta = await pedir(
            aplicacao(executor.correr),
            "/internal/turn",
            "POST",
            como_json(corpo),
            {CABECALHO: CREDENCIAL_DO_PAINEL},
        )
        self.assertEqual(estado, 400)
        self.assertEqual(json.loads(resposta)["outcome"], "invocacao_invalida")
        self.assertEqual(reencaminhados, [])

    async def test_a_mensagem_encontrada_corre_o_turno(self) -> None:
        base = BaseDeMensagens()
        grafo = GrafoQueRegista()
        corpo = invocacao_do_painel()
        base.gravar(ler_invocacao(corpo), "ola")
        estado, _, resposta = await pedir(
            aplicacao(executor_com(base, grafo).correr),
            "/internal/turn",
            "POST",
            como_json(corpo),
            {CABECALHO: CREDENCIAL_DO_PAINEL},
        )
        self.assertEqual(estado, 200)
        self.assertEqual(json.loads(resposta)["outcome"], "executado")
        self.assertEqual(len(grafo.entradas), 1)


class TestDoWhatsAppAoCheckpoint(unittest.TestCase):
    """KAM-232, criterio 2: o texto do WhatsApp chega a janela redigido, e um PAN
    escrito pelo cliente nao fica em claro em nenhum *checkpoint*.

    A invocacao e a de `packages/core-ts/tests/fixtures/invocacao_do_whatsapp.json`,
    que o `chr.mensagem.test.ts` prova ser **exactamente** o que o CHR entrega
    para essa mensagem — a ponte entre as duas linguagens, como a do botao do
    KAM-211. O grafo e o do Vendedor a serio (`test_vendedor.montar`), com um
    `InMemorySaver`: o que se varre e o que o LangGraph gravou, entrada incluida.
    """

    def setUp(self) -> None:
        METRICAS.repor()
        caminho = (
            Path(__file__).resolve().parents[3]
            / "packages" / "core-ts" / "tests" / "fixtures" / "invocacao_do_whatsapp.json"
        )
        fixture = json.loads(caminho.read_text(encoding="utf-8"))
        self.texto: str = fixture["texto"]
        self.corpo: dict[str, Any] = fixture["corpo"]

    def _turno(self, saver: InMemorySaver) -> tuple[Any, Any, list[str | None]]:
        base = BaseDeMensagens()
        invocacao = ler_invocacao(self.corpo)
        base.gravar(invocacao, self.texto, canal="whatsapp", papel="cliente")
        grafo, _deps, _backend, saida, _ = montar_vendedor(checkpointer=saver)
        canais: list[str | None] = []

        class ComCanal:
            async def ainvoke(self, estado: dict[str, Any], config: dict[str, Any]) -> Any:
                canais.append(CANAL_DO_TURNO.get())
                return await grafo.ainvoke(estado, config)

        [desfecho] = asyncio.run(correr_lote(executor_com(base, ComCanal()), [invocacao]))
        return desfecho, saida, canais

    @staticmethod
    def _guardado(saver: InMemorySaver) -> str:
        return repr(saver.storage) + repr(saver.writes) + repr(getattr(saver, "blobs", {}))

    def test_a_fixture_e_um_turno_do_cliente_com_mensagem_e_sem_o_texto(self) -> None:
        invocacao = ler_invocacao(self.corpo)
        self.assertEqual(invocacao.persona, "cliente")
        self.assertIsNotNone(invocacao.message_id)
        self.assertFalse(invocacao.wamid.startswith("painel."))
        # A credencial do painel nao corre um turno do WhatsApp.
        self.assertFalse(invocacao_do_painel_admitida(invocacao))
        self.assertIn(PAN, self.texto)
        self.assertNotIn(PAN, json.dumps(self.corpo))

    def test_o_pan_do_cliente_nao_fica_em_nenhum_checkpoint(self) -> None:
        saver = InMemorySaver()
        desfecho, saida, canais = self._turno(saver)
        self.assertEqual(desfecho.desfecho, "executado")
        self.assertEqual(canais, ["whatsapp"])
        guardado = self._guardado(saver)
        self.assertTrue(saver.storage, "o turno nao gravou checkpoint nenhum")
        self.assertNotIn(PAN, guardado)
        self.assertNotIn(PAN[:8], guardado)
        # A mensagem entrou, redigida: a marca esta no que se guardou.
        self.assertIn(regras.MARCA_CARTAO, guardado)
        self.assertTrue(saida.textos)
        self.assertFalse(any(PAN in texto for texto in saida.textos))

    def test_o_canario_sem_a_via_unica_o_pan_ficava_no_checkpoint(self) -> None:
        """Muta a **ligacao**, e nao a funcao: o executor a por o texto cru na
        janela. Se isto ficasse verde, o ensaio de cima nao media nada."""
        saver = InMemorySaver()
        crua = lambda texto, id_: {"role": "user", "content": texto, "id": id_}  # noqa: E731
        with mock.patch("kamba_agr.turno.mensagem_do_cliente", crua):
            self._turno(saver)
        self.assertIn(PAN, self._guardado(saver))


if __name__ == "__main__":
    unittest.main()
