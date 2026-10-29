"""A ToolLayer (KAM-028): unidade e arquitectura.

    TestContexto           o `ToolContext` constroi-se do estado e nao de texto
    TestConfirmation       as tres perguntas do critero 4, uma a uma
    TestErros              os dez codigos, e um codigo inventado levanta
    TestEspecificacoes     as negativas de uma especificacao, uma por regra
    TestCatalogo           as onze tools, e as duas ausencias que sao critero
    TestOitoPassos         **a ordem**, e um teste por passo: o seguinte nao corre
    TestClassesEErros      classes, timeouts e o mapeamento de erros do §6.5
    TestDisjuntor          abre por falhas consecutivas, e `UPSTREAM_DOWN` sem chamar
    TestAuditoria          a linha: forma canonica, redaccao, e o que nao vai la
    TestArquitectura       a TLS e a unica via de escrita; o *lint* e a camada concordam

**O `TestOitoPassos` e o critero 1**, e a forma dele e a do `TestSeisNegativos`
do KAM-027: por cada passo, parte-se de uma invocacao que passaria, estraga-se
**exactamente** o que aquele passo verifica, e confere-se que nenhum passo
seguinte correu. Os passos seguintes substituem-se por espioes — o que o
`PASSOS` da camada torna possivel, e e a razao de ele existir.

As *suites* contra um PostgreSQL real estao em `db/tests_agr/`: o *append-only*
da `tool_audit`, o `SET LOCAL app.tenant_id`, a `get_store_info` a serio e o
X-02 nao se provam com uma base falsa.
"""

from __future__ import annotations

import datetime as _dt
import json
import re
import time
import unittest
from pathlib import Path
from typing import Any

from pydantic import BaseModel, ConfigDict

from kamba_agr.metricas import (
    METRICA_TOOL_DISJUNTOR,
    METRICA_TOOL_ERROS,
    METRICA_TOOL_INVOCACOES,
    METRICA_TOOL_TENANT_MISMATCH,
    MetricasDoAgr,
)
from kamba_agr.registo.validar import PARAMETROS_PROIBIDOS
from kamba_agr.tls import auditoria, erros, idempotency
from kamba_agr.tls.camada import (
    PASSOS,
    BoundTool,
    ToolLayer,
    nomes_dos_passos,
)
from kamba_agr.tls.catalogo import ESPECIFICACOES_DO_PILOTO, catalogo_do_piloto
from kamba_agr.tls.vendedor import MODELOS
from kamba_agr.tls.contexto import (
    Confirmation,
    ContextoInvalidoError,
    ToolContext,
)
from kamba_agr.tls.disjuntor import ConfiguracaoDoDisjuntorError, Disjuntor
from kamba_agr.tls.especificacoes import (
    BACKENDS,
    CLASSES,
    Catalogo,
    ErroDeBackend,
    EspecificacaoDeTool,
    EspecificacaoInvalidaError,
    Pedido,
    Resposta,
)

_RAIZ = Path(__file__).resolve().parents[3]

TENANT = "11111111-1111-4111-8111-111111111111"
OUTRO_TENANT = "22222222-2222-4222-8222-222222222222"
CONTACTO = "33333333-3333-4333-8333-333333333333"
OUTRO_CONTACTO = "44444444-4444-4444-8444-444444444444"


def estado_valido(**troca: Any) -> dict[str, Any]:
    base = {
        "tenant_id": TENANT,
        "channel_id": "55555555-5555-4555-8555-555555555555",
        "contact_id": CONTACTO,
        "conversation_id": "66666666-6666-4666-8666-666666666666",
        "turn_id": "t-1",
        "vertical": "vendedor",
    }
    base.update(troca)
    return base


def contexto(**troca: Any) -> ToolContext:
    return ToolContext.de_estado(
        estado_valido(**troca), run_id="r-1", graph_version="1.0.0"
    )


# ------------------------------------------------------------------ dobragens
#
# KAM-029: `platform.tool_idempotency` em memoria. Cada entrada e
# `[estado, args_hash, result]`, e as quatro funcoes fazem o que o SQL faz —
# inclusive o `ON CONFLICT DO NOTHING` e o `WHERE estado = 'falhada'` da retoma,
# que e o que torna a reserva e a retoma **atomicas**. Sem isto, uma bateria de
# unidade sobre a camada tinha de enlatar a resposta e deixava de medir o
# protocolo; o que vai a base a serio esta em `db/tests_agr/test_idempotencia.py`.
def _idem_reservar(ligacao: "_Ligacao", p: tuple) -> list[tuple[Any, ...]]:
    chave, _tenant, _tool, args_hash = p
    if chave in ligacao.idempotencia:
        return []
    ligacao.idempotencia[chave] = ["em_curso", bytes(args_hash), None, ligacao.agora]
    return [(chave,)]


def _idem_ler(ligacao: "_Ligacao", p: tuple) -> list[tuple[Any, ...]]:
    linha = ligacao.idempotencia.get(p[0])
    return [] if linha is None else [tuple(linha)]


def _idem_retomar(ligacao: "_Ligacao", p: tuple) -> list[tuple[Any, ...]]:
    linha = ligacao.idempotencia.get(p[0])
    if linha is None or linha[0] != "falhada":
        return []
    linha[0], linha[2] = "em_curso", None
    return [(p[0],)]


def _idem_retomar_abandonada(ligacao: "_Ligacao", p: tuple) -> list[tuple[Any, ...]]:
    """O `UPDATE … WHERE estado = 'em_curso' AND created_at < %s`.

    A condicao esta aqui dentro, como no SQL: e o que torna a retoma atomica, e
    um duplo que a verificasse fora deixava dois leitores retomarem a mesma
    linha e correrem os dois o backend — que e o defeito que ela existe para
    fechar.
    """
    chave, limite = p
    linha = ligacao.idempotencia.get(chave)
    if linha is None or linha[0] != "em_curso" or not linha[3] < limite:
        return []
    linha[0], linha[2] = "em_curso", None
    return [(chave,)]


def _idem_agora(ligacao: "_Ligacao", _p: tuple) -> list[tuple[Any, ...]]:
    """O `SELECT now()` do servidor. No duplo, o relogio que o teste controla."""
    return [(ligacao.agora,)]


def _idem_fechar(ligacao: "_Ligacao", p: tuple) -> list[tuple[Any, ...]]:
    estado, carga, chave = p
    linha = ligacao.idempotencia.get(chave)
    if linha is not None:
        linha[0] = estado
        linha[2] = json.loads(carga) if carga is not None else None
    return []


_IDEMPOTENCIA = {
    "reservar": _idem_reservar,
    "ler_idempotencia": _idem_ler,
    "retomar": _idem_retomar,
    "retomar_abandonada": _idem_retomar_abandonada,
    "agora_do_servidor": _idem_agora,
    "fechar_idempotencia": _idem_fechar,
}


class _Cursor:
    """O minimo de um cursor DB-API, com as respostas que o teste lhe der."""

    def __init__(self, ligacao: "_Ligacao") -> None:
        self._ligacao = ligacao
        self.description: list[tuple[str, ...]] | None = None
        self._linhas: list[tuple[Any, ...]] = []
        self.rowcount = 0

    def execute(self, sql: str, parametros: Any = ()) -> None:
        self._ligacao.sql.append((sql, tuple(parametros)))
        if self._ligacao.levantar_em is not None and self._ligacao.levantar_em in sql:
            raise RuntimeError("a base recusou")
        chave = _chave_do_sql(sql)
        if chave in _IDEMPOTENCIA:
            self.description, self._linhas = None, _IDEMPOTENCIA[chave](
                self._ligacao, tuple(parametros)
            )
            return
        resposta = self._ligacao.respostas.get(chave)
        if resposta is None:
            self.description, self._linhas = None, []
            return
        self.description = [(nome,) for nome in resposta[0]]
        self._linhas = list(resposta[1])

    def fetchone(self) -> tuple[Any, ...] | None:
        return self._linhas[0] if self._linhas else None

    def fetchall(self) -> list[tuple[Any, ...]]:
        return list(self._linhas)

    def close(self) -> None:
        return None


def _chave_do_sql(sql: str) -> str:
    texto = sql.strip().upper()
    if texto.startswith("SELECT SET_CONFIG"):
        return "contexto"
    if "TEN_ENTITLEMENT" in texto or "ENTITLEMENTS" in texto:
        return "entitlement"
    if texto.startswith("INSERT INTO PLATFORM.TOOL_AUDIT"):
        return "auditoria"
    if "HAS_COLUMN_PRIVILEGE" in texto:
        return "privilegio"
    # KAM-029: as quatro instrucoes de `tool_idempotency`. Sao quatro chaves e
    # nao uma porque o `_Cursor` as **executa** contra um dicionario em memoria
    # (ver `_Ligacao.idempotencia`): com respostas enlatadas, uma bateria de
    # unidade nao podia distinguir «reservou» de «leu uma linha concluida», que
    # e precisamente a diferenca entre cobrar e nao cobrar.
    if texto == "SELECT NOW()":
        return "agora_do_servidor"
    if "PLATFORM.TOOL_IDEMPOTENCY" in texto:
        if texto.startswith("INSERT"):
            return "reservar"
        if texto.startswith("SELECT"):
            return "ler_idempotencia"
        # **Tres `UPDATE` e nao dois**, e distinguem-se pelo `WHERE`: a retoma
        # por idade leva o `created_at`, a de uma `falhada` leva o estado, e o
        # fecho nao leva nenhum dos dois.
        if "CREATED_AT <" in texto:
            return "retomar_abandonada"
        return "retomar" if "'FALHADA'" in texto else "fechar_idempotencia"
    return "outro"


class _Ligacao:
    """Uma ligacao falsa, transaccional, que grava o SQL que recebeu.

    **Grava o SQL de proposito**: e assim que o teste do passo 6 prova que o
    `SET LOCAL app.tenant_id` saiu com o tenant do contexto, e o do passo 1
    prova que **nenhuma** instrucao foi para a base.
    """

    def __init__(self, **respostas: tuple[tuple[str, ...], list[tuple[Any, ...]]]) -> None:
        self.autocommit = False
        self.sql: list[tuple[str, tuple[Any, ...]]] = []
        self.respostas = {
            "entitlement": (("permitido", "modulo"), [(True, "vendedor")]),
            **respostas,
        }
        self.levantar_em: str | None = None
        self.commits = 0
        self.fechada = False
        #: `platform.tool_idempotency` desta ligacao (KAM-029). Partilha-se
        #: entre invocacoes porque a tabela e partilhada: e o que faz uma
        #: segunda invocacao da mesma chave encontrar a primeira.
        self.idempotencia: dict[str, list[Any]] = {}
        #: O `now()` do **servidor**, que o duplo serve ao `SELECT now()`. E um
        #: relogio proprio e nao o do processo, pela razao escrita no `SQL_AGORA`
        #: do `idempotency.py`: a decisao de retomar compara-se com o
        #: `created_at`, que o servidor escreve, e um teste que usasse dois
        #: relogios media a deriva entre eles.
        self.agora = _dt.datetime(2026, 10, 25, 12, 0, tzinfo=_dt.UTC)

    def cursor(self) -> _Cursor:
        return _Cursor(self)

    def commit(self) -> None:
        self.commits += 1

    def rollback(self) -> None:
        return None

    def close(self) -> None:
        self.fechada = True

    # ------------------------------------------------------------- leituras
    def instrucoes(self) -> list[str]:
        return [_chave_do_sql(sql) for sql, _ in self.sql]

    def linhas_de_auditoria(self) -> list[tuple[Any, ...]]:
        return [p for sql, p in self.sql if _chave_do_sql(sql) == "auditoria"]


class ArgumentosDeEnsaio(BaseModel):
    model_config = ConfigDict(extra="forbid")
    cart_id: str


class ArgumentosComNota(BaseModel):
    """Dois campos, para o criterio 3 do KAM-029.

    O `ArgumentosDeEnsaio` tem **so** o `cart_id` e `extra="forbid"`: com ele,
    um segundo argumento era recusado no passo **3** e a bateria do criterio 3
    media a validacao de argumentos em vez da reutilizacao do `cart_id`. Para
    dois `args_hash` diferirem com o mesmo `cart_id` tem de haver um campo onde
    eles possam diferir.
    """

    model_config = ConfigDict(extra="forbid")
    cart_id: str
    nota: str = ""


class ArgumentosSemForbid(BaseModel):
    cart_id: str


class ArgumentosComTenant(BaseModel):
    model_config = ConfigDict(extra="forbid")
    tenant_id: str


class ArgumentosSemCampos(BaseModel):
    model_config = ConfigDict(extra="forbid")


def _executor_ok(pedido: Pedido) -> Resposta:
    return Resposta(
        data={"ok": True},
        facts=(
            erros.Fact(
                fact_id="f-1", kind="total", value=1200, retrieved_at="2026-10-25T00:00:00Z"
            ),
        ),
    )


def _espiao(nome: str, corridos: list[str]):
    def passo(_inv) -> None:
        corridos.append(nome)
        return None

    passo.__name__ = f"passo_0_{nome}"
    return passo


class _Base(unittest.TestCase):
    def camada(
        self,
        *,
        especificacoes: tuple[EspecificacaoDeTool, ...] | None = None,
        ligacao: _Ligacao | None = None,
        espioes_a_partir_de: int | None = None,
        metricas: MetricasDoAgr | None = None,
        disjuntor: Disjuntor | None = None,
        relogio: Any = time.monotonic,
        dormir: Any = None,
    ) -> tuple[ToolLayer, _Ligacao, list[str]]:
        """A camada, a ligacao falsa, e a lista dos passos espiados que correram."""
        if especificacoes is None:
            especificacoes = (
                EspecificacaoDeTool(
                    nome="criar_pedido",
                    klass="money",
                    backend="com",
                    modelo=ArgumentosDeEnsaio,
                    executor=_executor_ok,
                    campo_de_confirmacao="cart_id",
                ),
            )
        ligacao = ligacao if ligacao is not None else _Ligacao()
        corridos: list[str] = []
        passos: Any = PASSOS
        if espioes_a_partir_de is not None:
            passos = list(PASSOS[:espioes_a_partir_de])
            for passo in PASSOS[espioes_a_partir_de:]:
                passos.append(_espiao(passo.__name__, corridos))
        camada = ToolLayer(
            Catalogo(especificacoes),
            abrir_ligacao=lambda: ligacao,
            disjuntor=disjuntor,
            metricas=metricas,
            passos=passos,
            relogio=relogio,
            **({} if dormir is None else {"dormir": dormir}),
        )
        return camada, ligacao, corridos

    def invocar(self, camada: ToolLayer, **argumentos: Any):
        import asyncio

        padrao: dict[str, Any] = {
            "ctx": contexto(),
            "name": "criar_pedido",
            "args": {"cart_id": "c-1"},
            "allowed": ("criar_pedido",),
            "confirmation": Confirmation(
                botao="confirm:c-1", contact_id=CONTACTO, turn_id="t-1"
            ),
            "idempotency_key": "k-1",
        }
        padrao.update(argumentos)
        ctx = padrao.pop("ctx")
        nome = padrao.pop("name")
        args = padrao.pop("args")
        return asyncio.run(camada.invoke(ctx, nome, args, **padrao))


# ---------------------------------------------------------------- o contexto
class TestContexto(_Base):
    def test_constroi_se_do_estado_e_normaliza_o_tenant(self) -> None:
        ctx = contexto(tenant_id=TENANT.upper())
        self.assertEqual(ctx.tenant_id, TENANT)
        self.assertEqual(ctx.contact_id, CONTACTO)
        self.assertEqual(ctx.run_id, "r-1")
        self.assertEqual(ctx.graph_version, "1.0.0")

    def test_e_imutavel(self) -> None:
        with self.assertRaises(Exception):
            contexto().tenant_id = OUTRO_TENANT  # type: ignore[misc]

    def test_uma_chave_em_falta_levanta_e_nomeia_a_chave(self) -> None:
        for chave in (
            "tenant_id", "channel_id", "contact_id", "conversation_id",
            "turn_id", "vertical",
        ):
            with self.subTest(chave=chave):
                estado = estado_valido()
                del estado[chave]
                with self.assertRaises(ContextoInvalidoError) as capturado:
                    ToolContext.de_estado(estado, run_id="r", graph_version="1")
                self.assertIn(chave, str(capturado.exception))

    def test_uma_chave_vazia_conta_como_em_falta(self) -> None:
        with self.assertRaises(ContextoInvalidoError):
            ToolContext.de_estado(
                estado_valido(turn_id=""), run_id="r", graph_version="1"
            )

    def test_tenant_que_nao_e_uuid_levanta(self) -> None:
        with self.assertRaises(ContextoInvalidoError):
            ToolContext.de_estado(
                estado_valido(tenant_id="nao-sou-um-tenant"),
                run_id="r",
                graph_version="1",
            )

    def test_run_id_e_graph_version_nao_podem_ser_vazios(self) -> None:
        for troca in ({"run_id": ""}, {"graph_version": ""}):
            with self.subTest(**troca):
                argumentos = {"run_id": "r", "graph_version": "1", **troca}
                with self.assertRaises(ContextoInvalidoError):
                    ToolContext.de_estado(estado_valido(), **argumentos)

    def test_o_estado_nao_tem_run_id_nem_graph_version(self) -> None:
        """O §5.3 fecha em dezenove chaves, e estas duas nao estao la."""
        from kamba_agr.contexto import InvocacaoDoAgente
        from kamba_agr.estado import estado_inicial

        invocacao = InvocacaoDoAgente(
            tenant_id=TENANT,
            contact_id=CONTACTO,
            conversation_id="66666666-6666-4666-8666-666666666666",
            channel_id="55555555-5555-4555-8555-555555555555",
            wamid="w-1",
            type="text",
            modo="bot",
            thread_id=f"{TENANT}:{CONTACTO}",
            vertical="vendedor",
        )
        chaves = set(estado_inicial(invocacao))
        self.assertNotIn("run_id", chaves)
        self.assertNotIn("graph_version", chaves)


# ----------------------------------------------------------- a confirmacao
class TestConfirmation(_Base):
    def confirmacao(self, **troca: Any) -> Confirmation:
        base = {"botao": "confirm:c-1", "contact_id": CONTACTO, "turn_id": "t-1"}
        base.update(troca)
        return Confirmation(**base)

    def test_a_valida_autoriza(self) -> None:
        self.assertTrue(self.confirmacao().autoriza(contexto(), "c-1"))

    def test_referencia_de_outro_carrinho_nao_autoriza(self) -> None:
        self.assertFalse(self.confirmacao().autoriza(contexto(), "c-2"))

    def test_de_outro_contacto_nao_autoriza(self) -> None:
        confirmacao = self.confirmacao(contact_id=OUTRO_CONTACTO)
        self.assertFalse(confirmacao.autoriza(contexto(), "c-1"))

    def test_de_outro_turno_nao_autoriza(self) -> None:
        self.assertFalse(self.confirmacao(turn_id="t-0").autoriza(contexto(), "c-1"))

    def test_botao_sem_prefixo_nao_autoriza_e_a_referencia_e_vazia(self) -> None:
        confirmacao = self.confirmacao(botao="c-1")
        self.assertEqual(confirmacao.referencia, "")
        self.assertFalse(confirmacao.autoriza(contexto(), "c-1"))

    def test_referencia_esperada_vazia_nunca_autoriza(self) -> None:
        """Senao um `confirm:` sem referencia batia com um argumento vazio."""
        self.assertFalse(self.confirmacao(botao="confirm:").autoriza(contexto(), ""))


# ---------------------------------------------------------------- os erros
class TestErros(_Base):
    def test_sao_os_do_documento(self) -> None:
        """Os dez do §6.5 mais o `INTENT_REUSED_WITH_DIFFERENT_CONTENT` do §6.3.

        **O nome deste teste deixou de levar o numero** (era
        `..._sao_dez_e_os_do_documento`), pela licao que o KAM-027 escreveu para
        as listas literais e que o `test_catalogo.py` do `db/` repete: a
        invariante e «sao os do documento», e um numero no nome transformava-a em
        «sao dez» — que foi o que este ticket teve de vir mudar.
        """
        self.assertEqual(len(set(erros.CODIGOS)), len(erros.CODIGOS))
        self.assertEqual(
            set(erros.CODIGOS),
            {
                "NOT_FOUND", "OUT_OF_STOCK", "PRICE_CHANGED", "LIMIT_EXCEEDED",
                "ENTITLEMENT_DENIED", "TOOL_NOT_ALLOWED", "TENANT_MISMATCH",
                "UPSTREAM_TIMEOUT", "UPSTREAM_DOWN", "VALIDATION_ERROR",
                "INTENT_REUSED_WITH_DIFFERENT_CONTENT",
            },
        )

    def test_os_dois_do_ten_vem_do_ten(self) -> None:
        """Nao se redeclaram: uma segunda copia divergia em silencio."""
        from kamba_core.ten.entitlements import CODIGO_ENTITLEMENT_TOOL, CODIGO_LIMITE

        self.assertEqual(erros.ENTITLEMENT_DENIED, CODIGO_ENTITLEMENT_TOOL)
        self.assertEqual(erros.LIMIT_EXCEEDED, CODIGO_LIMITE)

    def test_um_codigo_inventado_levanta(self) -> None:
        with self.assertRaises(erros.CodigoDesconhecidoError):
            erros.ErroDeTool(codigo="PAGAMENTO_RECUSADO")

    def test_as_violacoes_sao_as_tres_do_documento(self) -> None:
        self.assertEqual(
            set(erros.VIOLACOES),
            {"ENTITLEMENT_DENIED", "TOOL_NOT_ALLOWED", "TENANT_MISMATCH"},
        )
        self.assertTrue(erros.ErroDeTool(codigo=erros.TENANT_MISMATCH).e_violacao)
        self.assertFalse(erros.ErroDeTool(codigo=erros.NOT_FOUND).e_violacao)

    def test_um_resultado_nao_pode_ser_ok_e_ter_erro(self) -> None:
        with self.assertRaises(ValueError):
            erros.ToolResult(ok=True, error=erros.ErroDeTool(codigo=erros.NOT_FOUND))
        with self.assertRaises(ValueError):
            erros.ToolResult(ok=False)

    def test_um_fact_tem_de_ter_kind_do_documento_e_fact_id(self) -> None:
        with self.assertRaises(ValueError):
            erros.Fact(fact_id="f", kind="preco", value=1, retrieved_at="z")
        with self.assertRaises(ValueError):
            erros.Fact(fact_id="", kind="price", value=1, retrieved_at="z")

    def test_o_idempotent_replay_nasce_falso(self) -> None:
        """Quem o poe a `True` e o KAM-029."""
        self.assertFalse(erros.ToolResult(ok=True).idempotent_replay)


# -------------------------------------------------------- as especificacoes
class TestEspecificacoes(_Base):
    def test_uma_ligada_valida_passa(self) -> None:
        especificacao = EspecificacaoDeTool(
            nome="criar_pedido",
            klass="money",
            backend="com",
            modelo=ArgumentosDeEnsaio,
            executor=_executor_ok,
            campo_de_confirmacao="cart_id",
        )
        self.assertTrue(especificacao.ligada)
        self.assertEqual(especificacao.parametros_visiveis(), frozenset({"cart_id"}))

    def test_sem_extra_forbid_e_recusada(self) -> None:
        with self.assertRaises(EspecificacaoInvalidaError) as capturado:
            EspecificacaoDeTool(
                nome="get_store_info",
                klass="read",
                backend="com",
                modelo=ArgumentosSemForbid,
                executor=_executor_ok,
            )
        self.assertIn("forbid", str(capturado.exception))

    def test_um_parametro_proibido_e_recusado(self) -> None:
        with self.assertRaises(EspecificacaoInvalidaError) as capturado:
            EspecificacaoDeTool(
                nome="search_catalog",
                klass="read",
                backend="idx",
                modelo=ArgumentosComTenant,
                executor=_executor_ok,
            )
        self.assertIn("tenant_id", str(capturado.exception))

    def test_write_sem_campo_de_confirmacao_e_recusada(self) -> None:
        with self.assertRaises(EspecificacaoInvalidaError):
            EspecificacaoDeTool(
                nome="book_slot",
                klass="write",
                backend="com",
                modelo=ArgumentosDeEnsaio,
                executor=_executor_ok,
            )

    def test_campo_de_confirmacao_que_nao_e_argumento_e_recusado(self) -> None:
        with self.assertRaises(EspecificacaoInvalidaError):
            EspecificacaoDeTool(
                nome="book_slot",
                klass="write",
                backend="com",
                modelo=ArgumentosDeEnsaio,
                executor=_executor_ok,
                campo_de_confirmacao="hold_id",
            )

    def test_read_com_campo_de_confirmacao_e_recusada(self) -> None:
        with self.assertRaises(EspecificacaoInvalidaError):
            EspecificacaoDeTool(
                nome="get_price_stock",
                klass="read",
                backend="com",
                modelo=ArgumentosDeEnsaio,
                executor=_executor_ok,
                campo_de_confirmacao="cart_id",
            )

    def test_declarada_sem_credor_e_recusada(self) -> None:
        with self.assertRaises(EspecificacaoInvalidaError) as capturado:
            EspecificacaoDeTool(nome="search_catalog", klass="read", backend="idx")
        self.assertIn("credor", str(capturado.exception))

    def test_credor_fora_da_forma_kam_nnn_e_recusado(self) -> None:
        for credor in ("KAM-31", "kam-031", "mais tarde", "KAM-0311"):
            with self.subTest(credor=credor):
                with self.assertRaises(EspecificacaoInvalidaError):
                    EspecificacaoDeTool(
                        nome="search_catalog",
                        klass="read",
                        backend="idx",
                        credor=credor,
                    )

    def test_ligada_com_credor_e_recusada(self) -> None:
        with self.assertRaises(EspecificacaoInvalidaError):
            EspecificacaoDeTool(
                nome="get_store_info",
                klass="read",
                backend="plataforma",
                modelo=ArgumentosDeEnsaio,
                executor=_executor_ok,
                credor="KAM-031",
            )

    def test_modelo_sem_executor_e_executor_sem_modelo_sao_recusados(self) -> None:
        with self.assertRaises(EspecificacaoInvalidaError):
            EspecificacaoDeTool(
                nome="get_store_info",
                klass="read",
                backend="com",
                modelo=ArgumentosDeEnsaio,
                credor="KAM-031",
            )
        with self.assertRaises(EspecificacaoInvalidaError):
            EspecificacaoDeTool(
                nome="get_store_info",
                klass="read",
                backend="com",
                executor=_executor_ok,
                credor="KAM-031",
            )

    def test_klass_e_backend_fora_da_lista_fechada_sao_recusados(self) -> None:
        with self.assertRaises(EspecificacaoInvalidaError):
            EspecificacaoDeTool(
                nome="x_tool", klass="admin", backend="com", credor="KAM-031"
            )
        with self.assertRaises(EspecificacaoInvalidaError):
            EspecificacaoDeTool(
                nome="x_tool", klass="read", backend="medusa", credor="KAM-031"
            )

    def test_nome_fora_da_gramatica_de_etiqueta_e_recusado(self) -> None:
        for nome in ("CriarPedido", "criar-pedido", "1tool", "a"):
            with self.subTest(nome=nome):
                with self.assertRaises(EspecificacaoInvalidaError):
                    EspecificacaoDeTool(
                        nome=nome, klass="read", backend="com", credor="KAM-031"
                    )

    def test_declarada_nao_expoe_parametro_nenhum(self) -> None:
        especificacao = EspecificacaoDeTool(
            nome="search_catalog", klass="read", backend="idx", credor="KAM-031"
        )
        self.assertFalse(especificacao.ligada)
        self.assertEqual(especificacao.parametros_visiveis(), frozenset())
        self.assertEqual(especificacao.esquema(), {})

    def test_o_catalogo_recusa_um_nome_repetido(self) -> None:
        uma = EspecificacaoDeTool(
            nome="search_catalog", klass="read", backend="idx", credor="KAM-031"
        )
        with self.assertRaises(EspecificacaoInvalidaError):
            Catalogo((uma, uma))

    def test_as_tres_classes_e_os_quatro_backends_sao_os_do_canon(self) -> None:
        self.assertEqual(CLASSES, ("read", "write", "money"))
        self.assertEqual(set(BACKENDS), {"com", "pay", "idx", "plataforma"})


# ---------------------------------------------------------------- o catalogo
class TestCatalogo(_Base):
    def setUp(self) -> None:
        self.catalogo = catalogo_do_piloto()

    def test_tem_as_onze_tools_do_catalogo_do_piloto(self) -> None:
        self.assertEqual(len(self.catalogo.nomes()), 11)
        self.assertEqual(
            self.catalogo.nomes(),
            frozenset(
                {
                    "search_catalog", "get_price_stock", "propose_cart",
                    "criar_pedido", "get_order_status", "get_store_info",
                    "list_services", "get_availability", "book_slot",
                    "cancel_booking", "reschedule_booking",
                }
            ),
        )

    def test_uma_esta_ligada_e_dez_estao_declaradas_com_credor(self) -> None:
        self.assertEqual(self.catalogo.ligadas(), ("get_store_info",))
        declaradas = self.catalogo.declaradas()
        self.assertEqual(len(declaradas), 10)
        # **Os credores das cinco do Vendedor sao os tickets que ligam o
        # backend, e nao o KAM-031.** Eram `KAM-031` e o proprio KAM-031
        # corrigiu-os: o credor de uma entrada `declarada` e «o ticket que a
        # liga», e os Detalhes Tecnicos do bloco dele dizem que «a ligacao real
        # a COM/IDX e por KAM-043, KAM-046 e KAM-061». Ele escreve os modelos e
        # os executores de ensaio; ligar o COM e o IDX nao esta no alcance dele,
        # e cinco entradas a nomear um ticket fechado nao sao atalho nenhum.
        #
        # Sao **quatro** tickets e nao tres: o `get_order_status` le o
        # `orders_mirror`, que e o KAM-044 — dependencia do proprio KAM-046.
        self.assertEqual(
            {nome: credor for nome, credor in declaradas.items() if nome in MODELOS},
            {
                "search_catalog": "KAM-061",
                "get_price_stock": "KAM-043",
                "propose_cart": "KAM-046",
                "criar_pedido": "KAM-046",
                "get_order_status": "KAM-044",
            },
        )
        self.assertEqual(
            {nome for nome, credor in declaradas.items() if credor == "KAM-035"},
            {
                "list_services", "get_availability", "book_slot",
                "cancel_booking", "reschedule_booking",
            },
        )

    def test_as_classes_sao_as_do_catalogo_do_documento(self) -> None:
        por_nome = {e.nome: e.klass for e in ESPECIFICACOES_DO_PILOTO}
        self.assertEqual(por_nome["criar_pedido"], "money")
        self.assertEqual(
            {
                nome
                for nome, klass in por_nome.items()
                if klass == "write"
            },
            {"book_slot", "cancel_booking", "reschedule_booking"},
        )
        # As restantes sete sao `read`.
        self.assertEqual(sum(1 for k in por_nome.values() if k == "read"), 7)

    def test_nenhum_esquema_do_catalogo_expoe_parametro_proibido(self) -> None:
        for nome in sorted(self.catalogo.nomes()):
            with self.subTest(tool=nome):
                self.assertEqual(
                    self.catalogo.parametros_visiveis(nome) & set(PARAMETROS_PROIBIDOS),
                    set(),
                )

    def test_nao_existe_tool_de_envio_de_mensagem(self) -> None:
        """§6.2: «o unico caminho para o cliente e o no `send` -> Outbound».

        Enumera-se o catalogo **e** as listas do registo, e procura-se o verbo:
        a ausencia de uma coisa nao se ve a ler a lista do que ha.
        """
        suspeitos = ("send", "enviar", "message", "mensagem", "reply", "notify", "sms")
        for nome in sorted(self.catalogo.nomes() | self._tools_do_registo()):
            with self.subTest(tool=nome):
                for suspeito in suspeitos:
                    self.assertNotIn(suspeito, nome)

    def test_nenhuma_tool_do_cliente_altera_preco_stock_ou_pagamento(self) -> None:
        """ADR-013 e §6.2: nem preco, nem stock, nem estado de pagamento.

        O `criar_pedido` **reserva** stock e cria uma cobranca, e isso nao e
        alterar preco nem confirmar pagamento: o estado de pagamento muda so por
        evento autenticado. O que este teste recusa e uma tool nova com um verbo
        de alteracao sobre um desses tres substantivos.
        """
        verbos = ("set_", "update_", "alterar_", "mudar_", "ajustar_", "confirmar_")
        substantivos = ("price", "preco", "stock", "payment", "pagamento")
        for nome in sorted(self.catalogo.nomes() | self._tools_do_registo()):
            with self.subTest(tool=nome):
                if any(nome.startswith(verbo) for verbo in verbos):
                    for substantivo in substantivos:
                        self.assertNotIn(substantivo, nome)

    def test_cada_tool_do_registo_existe_no_catalogo(self) -> None:
        """A validacao (1) do §5.2, medida de fora do arranque."""
        fora = sorted(self._tools_do_registo() - self.catalogo.nomes())
        self.assertEqual(fora, [])

    def _tools_do_registo(self) -> set[str]:
        import sys

        sys.path.insert(0, str(_RAIZ / "tools"))
        import kamba_yaml

        nomes: set[str] = set()
        for caminho in sorted((_RAIZ / "registry").glob("*.yaml")):
            documento = kamba_yaml.load_file(caminho)
            if "tools" in documento:
                nomes.update(documento["tools"])
        return nomes


# ------------------------------------------------------------- os oito passos
class TestOitoPassos(_Base):
    def test_a_ordem_e_a_dos_oito_passos_do_documento(self) -> None:
        self.assertEqual(
            nomes_dos_passos(),
            (
                "allowlist",
                "entitlement",
                "argumentos",
                "confirmacao",
                "idempotencia",
                "backend",
                "auditoria",
                "facts",
            ),
        )
        self.assertEqual(len(PASSOS), 8)

    # -- passo 1 ------------------------------------------------------------
    def test_passo_1_tool_fora_do_allowed_devolve_tool_not_allowed(self) -> None:
        camada, ligacao, corridos = self.camada(espioes_a_partir_de=1)
        resultado = self.invocar(camada, allowed=("get_store_info",))
        self.assertFalse(resultado.ok)
        self.assertEqual(resultado.error.codigo, erros.TOOL_NOT_ALLOWED)
        self.assertEqual(corridos, [], "o passo 2 correu depois de o 1 recusar")
        self.assertNotIn("entitlement", ligacao.instrucoes())

    def test_passo_1_tool_fora_do_catalogo_nao_deixa_linha_de_auditoria(self) -> None:
        """Sem `klass` nao ha linha possivel: o `klass` e `NOT NULL`."""
        camada, ligacao, corridos = self.camada(espioes_a_partir_de=1)
        resultado = self.invocar(
            camada, name="tool_inventada", allowed=("tool_inventada",)
        )
        self.assertEqual(resultado.error.codigo, erros.TOOL_NOT_ALLOWED)
        self.assertEqual(ligacao.linhas_de_auditoria(), [])
        self.assertEqual(corridos, [])

    def test_passo_1_tool_declarada_e_recusada_e_registada(self) -> None:
        camada, ligacao, corridos = self.camada(
            especificacoes=(
                EspecificacaoDeTool(
                    nome="criar_pedido", klass="money", backend="com", credor="KAM-031"
                ),
            ),
            espioes_a_partir_de=1,
        )
        resultado = self.invocar(camada)
        self.assertEqual(resultado.error.codigo, erros.TOOL_NOT_ALLOWED)
        self.assertEqual(corridos, [])
        # A linha existe: e uma invocacao `money` recusada, e o critero 5 pede
        # cobertura de **todas** as invocacoes `write`/`money`.
        self.assertEqual(len(ligacao.linhas_de_auditoria()), 1)

    # -- passo 2 ------------------------------------------------------------
    def test_passo_2_sem_entitlement_devolve_entitlement_denied(self) -> None:
        ligacao = _Ligacao(entitlement=(("permitido", "modulo"), [(False, "vendedor")]))
        camada, ligacao, corridos = self.camada(
            ligacao=ligacao, espioes_a_partir_de=2
        )
        resultado = self.invocar(camada)
        self.assertEqual(resultado.error.codigo, erros.ENTITLEMENT_DENIED)
        self.assertEqual(corridos, [], "o passo 3 correu depois de o 2 recusar")

    def test_passo_2_corre_com_o_contexto_de_tenant_definido(self) -> None:
        camada, ligacao, _ = self.camada()
        self.invocar(camada)
        contexto_definido = [
            parametros
            for sql, parametros in ligacao.sql
            if _chave_do_sql(sql) == "contexto"
        ]
        self.assertTrue(contexto_definido)
        for parametros in contexto_definido:
            self.assertEqual(parametros, (TENANT,))

    # -- passo 3 ------------------------------------------------------------
    def test_passo_3_argumento_extra_devolve_validation_error(self) -> None:
        camada, _, corridos = self.camada(espioes_a_partir_de=3)
        resultado = self.invocar(camada, args={"cart_id": "c-1", "desconto": 50})
        self.assertEqual(resultado.error.codigo, erros.VALIDATION_ERROR)
        self.assertEqual(corridos, [], "o passo 4 correu depois de o 3 recusar")

    def test_passo_3_argumento_em_falta_devolve_validation_error(self) -> None:
        camada, _, corridos = self.camada(espioes_a_partir_de=3)
        resultado = self.invocar(camada, args={})
        self.assertEqual(resultado.error.codigo, erros.VALIDATION_ERROR)
        self.assertEqual(corridos, [])

    def test_passo_3_nao_repete_o_valor_do_argumento_no_detalhe(self) -> None:
        """O `input` do Pydantic e texto que o modelo tirou da mensagem."""
        camada, _, _ = self.camada()
        resultado = self.invocar(
            camada, args={"cart_id": "c-1", "nota": "o telefone do Joao"}
        )
        self.assertNotIn("Joao", resultado.error.detalhe)
        self.assertNotIn("telefone", resultado.error.detalhe)

    # -- passo 4 ------------------------------------------------------------
    def test_passo_4_sem_confirmacao_devolve_erro_e_nao_chama_o_backend(self) -> None:
        camada, _, corridos = self.camada(espioes_a_partir_de=4)
        resultado = self.invocar(camada, confirmation=None)
        self.assertEqual(resultado.error.codigo, erros.VALIDATION_ERROR)
        self.assertEqual(corridos, [], "o passo 5 correu depois de o 4 recusar")

    def test_passo_4_confirmacao_de_outro_carrinho_e_recusada(self) -> None:
        camada, _, corridos = self.camada(espioes_a_partir_de=4)
        resultado = self.invocar(
            camada,
            confirmation=Confirmation(
                botao="confirm:c-OUTRO", contact_id=CONTACTO, turn_id="t-1"
            ),
        )
        self.assertEqual(resultado.error.codigo, erros.VALIDATION_ERROR)
        self.assertEqual(corridos, [])

    def test_passo_4_confirmacao_de_outro_turno_e_recusada(self) -> None:
        camada, _, corridos = self.camada(espioes_a_partir_de=4)
        resultado = self.invocar(
            camada,
            confirmation=Confirmation(
                botao="confirm:c-1", contact_id=CONTACTO, turn_id="t-0"
            ),
        )
        self.assertEqual(resultado.error.codigo, erros.VALIDATION_ERROR)
        self.assertEqual(corridos, [])

    def test_passo_4_confirmacao_de_outro_contacto_e_tenant_mismatch(self) -> None:
        metricas = MetricasDoAgr()
        camada, _, corridos = self.camada(
            espioes_a_partir_de=4, metricas=metricas
        )
        resultado = self.invocar(
            camada,
            confirmation=Confirmation(
                botao="confirm:c-1", contact_id=OUTRO_CONTACTO, turn_id="t-1"
            ),
        )
        self.assertEqual(resultado.error.codigo, erros.TENANT_MISMATCH)
        self.assertTrue(resultado.error.e_violacao)
        self.assertEqual(corridos, [])
        self.assertEqual(metricas.ler().get(METRICA_TOOL_TENANT_MISMATCH), 1)

    def test_passo_4_nao_se_aplica_a_read(self) -> None:
        camada, _, _ = self.camada(
            especificacoes=(
                EspecificacaoDeTool(
                    nome="get_store_info",
                    klass="read",
                    backend="com",
                    modelo=ArgumentosDeEnsaio,
                    executor=_executor_ok,
                ),
            )
        )
        resultado = self.invocar(
            camada,
            name="get_store_info",
            allowed=("get_store_info",),
            confirmation=None,
            idempotency_key=None,
        )
        self.assertTrue(resultado.ok)

    # -- passo 5 ------------------------------------------------------------
    def test_passo_5_money_sem_chave_nao_corre(self) -> None:
        camada, ligacao, corridos = self.camada(espioes_a_partir_de=5)
        for chave in (None, "", "   "):
            with self.subTest(chave=chave):
                resultado = self.invocar(camada, idempotency_key=chave)
                self.assertEqual(resultado.error.codigo, erros.VALIDATION_ERROR)
                self.assertIn("idempot", resultado.error.detalhe.lower())
        self.assertEqual(corridos, [], "o passo 6 correu depois de o 5 recusar")

    def test_passo_5_a_chave_vai_para_a_linha_de_auditoria(self) -> None:
        """O ponto de extensao do KAM-029: a coluna existe e recebe a chave."""
        camada, ligacao, _ = self.camada()
        self.invocar(camada, idempotency_key="k-abc")
        linha = ligacao.linhas_de_auditoria()[0]
        self.assertIn("k-abc", linha)

    # -- passo 6 ------------------------------------------------------------
    def test_passo_6_erro_de_negocio_vem_com_o_codigo_do_backend(self) -> None:
        def executor(_pedido: Pedido) -> Resposta:
            raise ErroDeBackend(erros.OUT_OF_STOCK, "sem stock")

        camada, _, corridos = self.camada(
            especificacoes=(
                EspecificacaoDeTool(
                    nome="criar_pedido",
                    klass="money",
                    backend="com",
                    modelo=ArgumentosDeEnsaio,
                    executor=executor,
                    campo_de_confirmacao="cart_id",
                ),
            ),
            espioes_a_partir_de=6,
        )
        resultado = self.invocar(camada)
        self.assertEqual(resultado.error.codigo, erros.OUT_OF_STOCK)
        self.assertEqual(corridos, [], "o passo 7 correu depois de o 6 recusar")

    def test_passo_6_timeout_e_upstream_timeout_e_qualquer_outra_e_down(self) -> None:
        for excepcao, esperado in (
            (TimeoutError("tarde"), erros.UPSTREAM_TIMEOUT),
            (ValueError("qualquer"), erros.UPSTREAM_DOWN),
        ):
            with self.subTest(excepcao=type(excepcao).__name__):
                def executor(_pedido: Pedido, _e=excepcao) -> Resposta:
                    raise _e

                camada, _, _ = self.camada(
                    especificacoes=(
                        EspecificacaoDeTool(
                            nome="criar_pedido",
                            klass="money",
                            backend="com",
                            modelo=ArgumentosDeEnsaio,
                            executor=executor,
                            campo_de_confirmacao="cart_id",
                        ),
                    )
                )
                resultado = self.invocar(camada)
                self.assertEqual(resultado.error.codigo, esperado)

    def test_passo_6_o_executor_recebe_o_contexto_e_os_args_validados(self) -> None:
        visto: dict[str, Any] = {}

        def executor(pedido: Pedido) -> Resposta:
            visto["ctx"] = pedido.ctx
            visto["args"] = pedido.args
            visto["timeout"] = pedido.timeout_ms
            return Resposta(data={})

        camada, _, _ = self.camada(
            especificacoes=(
                EspecificacaoDeTool(
                    nome="criar_pedido",
                    klass="money",
                    backend="com",
                    modelo=ArgumentosDeEnsaio,
                    executor=executor,
                    campo_de_confirmacao="cart_id",
                ),
            )
        )
        self.invocar(camada)
        self.assertEqual(visto["ctx"].tenant_id, TENANT)
        self.assertIsInstance(visto["args"], ArgumentosDeEnsaio)
        self.assertEqual(visto["timeout"], 8_000)

    # -- passo 7 e 8 --------------------------------------------------------
    def test_passo_7_escreve_uma_linha_por_invocacao(self) -> None:
        camada, ligacao, _ = self.camada()
        self.invocar(camada)
        self.assertEqual(len(ligacao.linhas_de_auditoria()), 1)

    def test_passo_8_devolve_os_facts(self) -> None:
        camada, _, _ = self.camada()
        resultado = self.invocar(camada)
        self.assertTrue(resultado.ok)
        self.assertEqual([f.fact_id for f in resultado.facts], ["f-1"])
        self.assertEqual(resultado.data, {"ok": True})

    def test_uma_auditoria_que_falha_levanta_e_nao_devolve_ok(self) -> None:
        ligacao = _Ligacao()
        ligacao.levantar_em = "INSERT INTO platform.tool_audit"
        camada, _, _ = self.camada(ligacao=ligacao)
        with self.assertRaises(auditoria.AuditoriaIndisponivelError):
            self.invocar(camada)
        self.assertTrue(ligacao.fechada, "a ligacao quebrada tem de ser largada")


# -------------------------------------------------- for_context, classes, etc.
class TestClassesEErros(_Base):
    def test_for_context_so_devolve_as_ligadas_do_allowed(self) -> None:
        camada, _, _ = self.camada(especificacoes=ESPECIFICACOES_DO_PILOTO)
        ligadas = camada.for_context(
            contexto(), ["search_catalog", "get_store_info", "criar_pedido"]
        )
        self.assertEqual([t.nome for t in ligadas], ["get_store_info"])
        self.assertIsInstance(ligadas[0], BoundTool)

    def test_o_esquema_que_vai_ao_modelo_nao_tem_o_contexto(self) -> None:
        """Mais estrito do que o critero 3, e por uma razao medida.

        O critero 3 diz «nenhum **parametro**». Este teste olha para o esquema
        **inteiro**, descricao incluida, porque foi assim que se descobriu que a
        *docstring* de uma classe de argumentos entra no `model_json_schema()` e
        vai no prompt: a primeira versao do `ArgumentosDeGetStoreInfo`
        explicava-se com uma frase que dizia `tenant_id`. Um parametro o modelo
        preenche; uma descricao o modelo **le** — e nenhum dos dois tem de lhe
        ensinar o nome que o §6.1 diz que ele nunca ve.
        """
        camada, _, _ = self.camada(especificacoes=ESPECIFICACOES_DO_PILOTO)
        ligada = camada.for_context(contexto(), ["get_store_info"])[0]
        texto = repr(ligada.esquema)
        for proibido in PARAMETROS_PROIBIDOS:
            self.assertNotIn(proibido, texto)
        self.assertNotIn(TENANT, texto)
        self.assertNotIn(CONTACTO, texto)

    def test_os_timeouts_sao_os_do_documento(self) -> None:
        camada, _, _ = self.camada()
        self.assertEqual(camada.timeout_de("read"), 2_000)
        self.assertEqual(camada.timeout_de("write"), 8_000)
        self.assertEqual(camada.timeout_de("money"), 8_000)

    def test_o_tecto_sai_para_o_servidor_com_o_numero_da_classe(self) -> None:
        """O tecto do §6.5 nao fica no cliente: vai num `SET LOCAL`.

        Um tecto que so existisse do lado de ca deixava a consulta a correr na
        base depois de o turno desistir dela — e a base nao sabe que ninguem
        espera pela resposta. Mede-se pelo SQL que sai, e o numero e o da
        classe: 2000 ms para `read`.
        """
        from kamba_agr.tls.get_store_info import (
            VARIAVEL_DE_TECTO,
            ArgumentosDeGetStoreInfo,
            executar,
        )

        camada, ligacao, _ = self.camada(
            especificacoes=(
                EspecificacaoDeTool(
                    nome="get_store_info",
                    klass="read",
                    backend="plataforma",
                    modelo=ArgumentosDeGetStoreInfo,
                    executor=executar,
                ),
            ),
            ligacao=_Ligacao(
                **{"outro": (("nome", "zona", "plus_code", "fuso_horario"),
                             [("Loja", "Maianga", "6H5F+2X", "Africa/Luanda")])}
            ),
        )
        resultado = self.invocar(
            camada,
            name="get_store_info",
            allowed=("get_store_info",),
            args={},
            confirmation=None,
            idempotency_key=None,
        )
        self.assertTrue(resultado.ok, resultado.error)
        tectos = [
            sql for sql, _ in ligacao.sql if f"SET LOCAL {VARIAVEL_DE_TECTO}" in sql
        ]
        self.assertEqual(tectos, [f"SET LOCAL {VARIAVEL_DE_TECTO} = 2000"])

    def test_um_cancelamento_do_servidor_e_upstream_timeout(self) -> None:
        """O `57014` do PostgreSQL volta como `UPSTREAM_TIMEOUT`, nao como `DOWN`.

        O `camada.py` so reconhece `TimeoutError`, e o `pg8000` levanta
        `DatabaseError` com o SQLSTATE no corpo. Sem a traducao do
        `get_store_info`, uma consulta que passasse do tecto voltava como
        «o backend esta em baixo» — e um painel mandava olhar para o sitio
        errado. Le-se o **SQLSTATE** e nao o texto, que e localizavel.
        """
        from kamba_agr.tls.get_store_info import SQLSTATE_CANCELADA, _e_cancelamento

        class _Cancelada(Exception):
            pass

        cancelada = _Cancelada({"S": "ERROR", "C": SQLSTATE_CANCELADA, "M": "cancelada"})
        self.assertTrue(_e_cancelamento(cancelada))
        self.assertFalse(_e_cancelamento(_Cancelada({"C": "42501"})))
        self.assertFalse(_e_cancelamento(ValueError("statement timeout")))

        def executor(_pedido: Pedido) -> Resposta:
            raise TimeoutError("passou do tecto")

        camada, _, _ = self.camada(
            especificacoes=(
                EspecificacaoDeTool(
                    nome="criar_pedido",
                    klass="money",
                    backend="com",
                    modelo=ArgumentosDeEnsaio,
                    executor=executor,
                    campo_de_confirmacao="cart_id",
                ),
            )
        )
        self.assertEqual(
            self.invocar(camada).error.codigo, erros.UPSTREAM_TIMEOUT
        )

    def test_as_metricas_contam_a_invocacao_e_o_codigo(self) -> None:
        metricas = MetricasDoAgr()
        camada, _, _ = self.camada(metricas=metricas)
        self.invocar(camada)
        self.invocar(camada, allowed=("get_store_info",))
        lido = metricas.ler()
        self.assertEqual(lido[f"{METRICA_TOOL_INVOCACOES}:criar_pedido"], 2)
        self.assertEqual(lido[f"{METRICA_TOOL_ERROS}:tool_not_allowed"], 1)

    def test_nenhuma_metrica_aceita_um_identificador_como_etiqueta(self) -> None:
        from kamba_agr.metricas import EtiquetaInvalida

        metricas = MetricasDoAgr()
        for metrica in (METRICA_TOOL_INVOCACOES, METRICA_TOOL_ERROS,
                        METRICA_TOOL_DISJUNTOR):
            with self.subTest(metrica=metrica):
                with self.assertRaises(EtiquetaInvalida):
                    metricas.contar(metrica, TENANT)


# ------------------------------------------------------------- o disjuntor
class TestDisjuntor(_Base):
    def relogio(self) -> Any:
        agora = {"t": 0.0}
        return agora, lambda: agora["t"]

    def test_abre_apos_as_falhas_consecutivas_configuradas(self) -> None:
        agora, relogio = self.relogio()
        disjuntor = Disjuntor(falhas=3, pausa_ms=1_000, relogio=relogio)
        self.assertFalse(disjuntor.registar_falha("com"))
        self.assertFalse(disjuntor.registar_falha("com"))
        self.assertTrue(disjuntor.registar_falha("com"))
        self.assertTrue(disjuntor.aberto("com"))
        self.assertFalse(disjuntor.permite("com"))

    def test_um_sucesso_poe_o_contador_a_zero(self) -> None:
        agora, relogio = self.relogio()
        disjuntor = Disjuntor(falhas=2, pausa_ms=1_000, relogio=relogio)
        disjuntor.registar_falha("com")
        disjuntor.registar_sucesso("com")
        self.assertFalse(disjuntor.registar_falha("com"))
        self.assertTrue(disjuntor.permite("com"))

    def test_e_por_backend_e_nao_global(self) -> None:
        agora, relogio = self.relogio()
        disjuntor = Disjuntor(falhas=1, pausa_ms=1_000, relogio=relogio)
        disjuntor.registar_falha("com")
        self.assertFalse(disjuntor.permite("com"))
        self.assertTrue(disjuntor.permite("idx"))

    def test_passada_a_pausa_deixa_passar_uma_e_so_uma(self) -> None:
        agora, relogio = self.relogio()
        disjuntor = Disjuntor(falhas=1, pausa_ms=1_000, relogio=relogio)
        disjuntor.registar_falha("com")
        agora["t"] = 2.0
        self.assertTrue(disjuntor.permite("com"), "a tentativa de meio-aberto")
        self.assertFalse(disjuntor.permite("com"), "a segunda abria a porta toda")

    def test_aberto_nao_consome_a_tentativa_de_meio_aberto(self) -> None:
        agora, relogio = self.relogio()
        disjuntor = Disjuntor(falhas=1, pausa_ms=1_000, relogio=relogio)
        disjuntor.registar_falha("com")
        agora["t"] = 2.0
        self.assertFalse(disjuntor.aberto("com"))
        self.assertTrue(disjuntor.permite("com"), "o `aberto` consumiu a tentativa")

    def test_aberto_devolve_upstream_down_sem_chamar_o_backend(self) -> None:
        chamadas: list[int] = []

        def executor(_pedido: Pedido) -> Resposta:
            chamadas.append(1)
            raise ValueError("em baixo")

        especificacoes = (
            EspecificacaoDeTool(
                nome="criar_pedido",
                klass="money",
                backend="com",
                modelo=ArgumentosDeEnsaio,
                executor=executor,
                campo_de_confirmacao="cart_id",
            ),
        )
        metricas = MetricasDoAgr()
        agora, relogio = self.relogio()
        disjuntor = Disjuntor(falhas=2, pausa_ms=10_000, relogio=relogio)
        camada, _, _ = self.camada(
            especificacoes=especificacoes, disjuntor=disjuntor, metricas=metricas
        )
        for _ in range(2):
            self.assertEqual(self.invocar(camada).error.codigo, erros.UPSTREAM_DOWN)
        self.assertEqual(len(chamadas), 2)
        resultado = self.invocar(camada)
        self.assertEqual(resultado.error.codigo, erros.UPSTREAM_DOWN)
        self.assertEqual(len(chamadas), 2, "o backend foi chamado com o disjuntor aberto")
        self.assertEqual(metricas.ler()[f"{METRICA_TOOL_DISJUNTOR}:com"], 1)

    def test_um_erro_de_negocio_nao_conta_para_o_disjuntor(self) -> None:
        def executor(_pedido: Pedido) -> Resposta:
            raise ErroDeBackend(erros.NOT_FOUND, "nao ha")

        agora, relogio = self.relogio()
        disjuntor = Disjuntor(falhas=1, pausa_ms=10_000, relogio=relogio)
        camada, _, _ = self.camada(
            especificacoes=(
                EspecificacaoDeTool(
                    nome="criar_pedido",
                    klass="money",
                    backend="com",
                    modelo=ArgumentosDeEnsaio,
                    executor=executor,
                    campo_de_confirmacao="cart_id",
                ),
            ),
            disjuntor=disjuntor,
        )
        self.invocar(camada)
        self.assertFalse(disjuntor.aberto("com"))

    def test_configuracao_que_nao_serve_levanta(self) -> None:
        with self.assertRaises(ConfiguracaoDoDisjuntorError):
            Disjuntor(falhas=0)


# ------------------------------------------------------------- a auditoria
class TestAuditoria(_Base):
    def test_a_impressao_nao_depende_da_ordem_das_chaves(self) -> None:
        self.assertEqual(
            auditoria.impressao({"a": 1, "b": 2}),
            auditoria.impressao({"b": 2, "a": 1}),
        )
        self.assertNotEqual(
            auditoria.impressao({"a": 1}), auditoria.impressao({"a": 2})
        )
        self.assertEqual(len(auditoria.impressao({})), 32)

    def test_a_redaccao_guarda_o_tipo_e_nunca_o_valor(self) -> None:
        redigido = auditoria.redigir(
            {"query": "sapatos do Joao", "limite": 5}, ["query", "limite"]
        )
        self.assertEqual(redigido, {"limite": "int", "query": "str"})
        self.assertNotIn("sapatos", repr(redigido))
        self.assertNotIn("Joao", repr(redigido))

    def test_a_linha_tem_dezoito_valores_pela_ordem_das_colunas(self) -> None:
        self.assertEqual(len(auditoria.COLUNAS), 18)
        linha = auditoria.LinhaDeAuditoria(
            ctx=contexto(),
            tool="criar_pedido",
            tool_version="1",
            klass="money",
            args={"cart_id": "c-1"},
            status=auditoria.STATUS_OK,
            latency_ms=12,
            data={"order_id": "o-1"},
            facts=(
                erros.Fact(
                    fact_id="f-1", kind="total", value=1, retrieved_at="2026-10-25"
                ),
            ),
            idempotency_key="k-1",
        )
        parametros = linha.parametros()
        self.assertEqual(len(parametros), len(auditoria.COLUNAS))
        por_nome = dict(zip(auditoria.COLUNAS, parametros, strict=True))
        self.assertEqual(por_nome["tenant_id"], TENANT)
        self.assertEqual(por_nome["klass"], "money")
        self.assertEqual(por_nome["status"], "ok")
        self.assertIsNone(por_nome["error_code"])
        self.assertEqual(len(por_nome["args_hash"]), 32)
        self.assertEqual(len(por_nome["result_hash"]), 32)
        self.assertEqual(por_nome["fact_ids"], ["f-1"])
        self.assertEqual(por_nome["latency_ms"], 12)

    def test_uma_linha_de_erro_nao_leva_result_hash(self) -> None:
        linha = auditoria.LinhaDeAuditoria(
            ctx=contexto(),
            tool="criar_pedido",
            tool_version="1",
            klass="money",
            args={},
            status=auditoria.STATUS_ERRO,
            latency_ms=1,
            error=erros.ErroDeTool(codigo=erros.OUT_OF_STOCK),
            data={"parcial": True},
        )
        por_nome = dict(zip(auditoria.COLUNAS, linha.parametros(), strict=True))
        self.assertIsNone(por_nome["result_hash"])
        self.assertEqual(por_nome["error_code"], erros.OUT_OF_STOCK)

    def test_a_linha_nao_leva_valores_de_argumento(self) -> None:
        """O critero 5: nem texto de mensagem, nem telefone, nem valores."""
        canario = "CANARIO-999123456789"
        linha = auditoria.LinhaDeAuditoria(
            ctx=contexto(),
            tool="criar_pedido",
            tool_version="1",
            klass="money",
            args={"cart_id": canario, "nota": canario},
            status=auditoria.STATUS_OK,
            latency_ms=1,
            data={"eco": canario},
        )
        self.assertNotIn(canario, repr(linha.parametros()))

    def test_as_colunas_sao_as_que_a_migracao_concede(self) -> None:
        """Se divergirem, o `INSERT` rebenta por privilegio e nao em silencio."""
        import re

        fonte = (
            _RAIZ / "db" / "migrations" / "versions" / "0021_tool_audit.py"
        ).read_text(encoding="utf-8")
        bloco = re.search(
            r"COLUNAS_ESCRITAS_PELO_CHAMADOR = \(\s*(.*?)\s*\)\n", fonte, re.S
        )
        assert bloco is not None
        texto = "".join(re.findall(r'"([^"]*)"', bloco.group(1)))
        self.assertEqual(
            tuple(parte.strip() for parte in texto.split(",")), auditoria.COLUNAS
        )


# ------------------------------------------------- os achados da revisao
class TestImportacaoIsolada(unittest.TestCase):
    """Cada um dos oito ficheiros da TLS importa-se **sozinho**.

    O `metricas.py` deriva as etiquetas do `catalogo.py` e o `camada.py` importa
    o `metricas.py`: o triangulo existe. A primeira versao derivava-as no corpo
    do modulo e fechava-o — `import kamba_agr.tls.especificacoes`,
    `.get_store_info` e `.catalogo` davam
    `ImportError: partially initialized module`, e sao os tres ficheiros que o
    KAM-031 e o KAM-035 vao abrir primeiro.

    **Funcionava pela ordem**, e a bateria importava sempre o `camada` antes. E
    por isso que este teste corre em **subprocesso**, um por ficheiro: dentro
    deste processo os modulos ja estao em `sys.modules` e o ciclo nao se ve.
    """

    FICHEIROS = (
        "auditoria", "camada", "catalogo", "contexto", "disjuntor", "erros",
        "especificacoes", "get_store_info",
    )

    def test_cada_ficheiro_importa_se_sozinho(self) -> None:
        import os
        import subprocess
        import sys

        ambiente = dict(
            os.environ,
            PYTHONPATH=os.pathsep.join(
                str(_RAIZ / caminho)
                for caminho in ("libs/py-core/src", "services/agr/src")
            ),
        )
        for ficheiro in self.FICHEIROS:
            with self.subTest(ficheiro=ficheiro):
                r = subprocess.run(
                    [sys.executable, "-c", f"import kamba_agr.tls.{ficheiro}"],
                    capture_output=True, text=True, env=ambiente,
                    encoding="utf-8", errors="replace",
                )
                self.assertEqual(r.returncode, 0, r.stderr[-800:])

    def test_as_etiquetas_derivadas_continuam_derivadas(self) -> None:
        """A correccao nao podia ser escrever a lista a mao (KAM-027)."""
        from kamba_agr.metricas import (
            METRICA_TOOL_DISJUNTOR,
            METRICA_TOOL_ERROS,
            METRICA_TOOL_INVOCACOES,
            _valores_derivados,
        )

        self.assertEqual(len(_valores_derivados(METRICA_TOOL_INVOCACOES)), 11)
        # Onze desde o KAM-029, e derivados: confronta-se com `CODIGOS` e nao
        # com um numero, que e o que «continuam derivadas» quer dizer.
        self.assertEqual(
            _valores_derivados(METRICA_TOOL_ERROS),
            tuple(sorted(codigo.lower() for codigo in erros.CODIGOS)),
        )
        self.assertEqual(len(_valores_derivados(METRICA_TOOL_DISJUNTOR)), 4)
        fonte = (_RAIZ / "services/agr/src/kamba_agr/metricas.py").read_text(
            encoding="utf-8"
        )
        self.assertNotIn('"get_store_info"', fonte)
        self.assertNotIn('"criar_pedido"', fonte)


class TestIsolamentoEntreTenants(_Base):
    """As tomadas sao uma fila, e uma invocacao lenta nao prende as outras."""

    def camada_lenta(self, *, segundos: float, ligacoes: int):
        import threading

        abertas: list[int] = []
        trinco = threading.Lock()

        def executor(_pedido: Pedido) -> Resposta:
            time.sleep(segundos)
            return Resposta(data={})

        def abrir():
            with trinco:
                abertas.append(1)
            return _Ligacao()

        camada = ToolLayer(
            Catalogo((
                EspecificacaoDeTool(
                    nome="get_store_info", klass="read", backend="com",
                    modelo=ArgumentosSemCampos, executor=executor,
                ),
            )),
            abrir_ligacao=abrir,
            ligacoes=ligacoes,
        )
        return camada, abertas

    def correr(self, camada, quantos: int):
        import asyncio

        async def tudo():
            return await asyncio.gather(*[
                camada.invoke(
                    contexto(tenant_id=f"{i:08d}-1111-4111-8111-111111111111"),
                    "get_store_info", {}, allowed=("get_store_info",),
                )
                for i in range(quantos)
            ])

        comecou = time.monotonic()
        resultados = asyncio.run(tudo())
        return resultados, time.monotonic() - comecou

    def test_dez_tenants_nao_correm_em_serie(self) -> None:
        """O defeito mais caro do KAM-025, medido nesta camada.

        Com **uma** tomada e um `asyncio.Lock`, dez invocacoes de dez tenants
        com um backend de 200 ms levavam 2,02 s — bloqueio de cabeca de fila a
        atravessar tenants. Com a fila de quatro, o tecto e
        `ceil(10/4) * 200 ms`, e o que este teste afirma e a **folga**: menos de
        metade do tempo em serie.
        """
        camada, _ = self.camada_lenta(segundos=0.2, ligacoes=4)
        resultados, duracao = self.correr(camada, 10)
        self.assertTrue(all(r.ok for r in resultados), [r.error for r in resultados])
        self.assertLess(
            duracao, 10 * 0.2 / 2,
            f"dez invocacoes de dez tenants em {duracao:.2f}s: estao em serie",
        )

    def test_a_fila_e_o_tecto_de_tomadas(self) -> None:
        """Mais invocacoes do que vagas nao abre mais ligacoes do que o tecto."""
        camada, abertas = self.camada_lenta(segundos=0.05, ligacoes=2)
        self.correr(camada, 8)
        self.assertLessEqual(len(abertas), 2, f"abriu {len(abertas)} tomadas")

    def test_uma_tool_pendurada_custa_uma_vaga_e_nao_o_processo(self) -> None:
        """O tecto da camada sobre um executor que ignora o dele (critero 7).

        Sem a espera, um executor de 5 s contra um tecto de 2 s devolvia
        `ok=True` em 5 s — medido. Com ela, o cliente leva `UPSTREAM_TIMEOUT` no
        tecto da classe mais a folga, e a *thread* continua: leva a sua vaga
        consigo, e as outras continuam a servir.
        """
        import asyncio

        def pendurado(_pedido: Pedido) -> Resposta:
            time.sleep(3.0)
            return Resposta(data={})

        def rapido(_pedido: Pedido) -> Resposta:
            return Resposta(data={"ok": True})

        camada = ToolLayer(
            Catalogo((
                EspecificacaoDeTool(
                    nome="get_store_info", klass="read", backend="com",
                    modelo=ArgumentosSemCampos, executor=pendurado,
                ),
                EspecificacaoDeTool(
                    nome="list_services", klass="read", backend="com",
                    modelo=ArgumentosSemCampos, executor=rapido,
                ),
            )),
            abrir_ligacao=_Ligacao,
            ligacoes=2,
        )

        async def tudo():
            comecou = time.monotonic()
            lento = asyncio.create_task(
                camada.invoke(
                    contexto(), "get_store_info", {},
                    allowed=("get_store_info", "list_services"),
                )
            )
            await asyncio.sleep(0.05)
            outro = await camada.invoke(
                contexto(), "list_services", {},
                allowed=("get_store_info", "list_services"),
            )
            return await lento, outro, time.monotonic() - comecou

        # **O tempo mede-se dentro do laco**, e nao em volta do `asyncio.run`: o
        # `run` fecha o executor no fim e **espera pelas *threads***, pelo que
        # medi-lo por fora dava sempre os 3 s do executor pendurado e nao o que
        # este teste afirma. Ao encerrar, esperar por ela e o que se quer — o que
        # nao se quer e esperar por ela **a servir**.
        pendurada, outra, duracao = asyncio.run(tudo())
        self.assertTrue(outra.ok, "a invocacao rapida ficou presa atras da lenta")
        self.assertFalse(pendurada.ok)
        self.assertEqual(pendurada.error.codigo, erros.UPSTREAM_TIMEOUT)
        self.assertLess(duracao, 3.0, f"esperou pela thread: {duracao:.2f}s")


    def test_cancelar_o_invoke_nao_poe_uma_vaga_a_mais_na_fila(self) -> None:
        """Quem cancela nao tem a tomada: a *thread* e que a tem.

        Um `CancelledError` e uma `BaseException`, e a primeira versao do
        tratamento devolvia a vaga **ali** — punha na fila uma vaga a mais e
        deixava uma ligacao a correr fora dela. Mede-se pela conta: depois do
        cancelamento e de a *thread* acabar, a fila tem as vagas que tinha.
        """
        import asyncio

        def lento(_pedido: Pedido) -> Resposta:
            time.sleep(0.4)
            return Resposta(data={})

        camada = ToolLayer(
            Catalogo((
                EspecificacaoDeTool(
                    nome="get_store_info", klass="read", backend="com",
                    modelo=ArgumentosSemCampos, executor=lento,
                ),
            )),
            abrir_ligacao=_Ligacao,
            ligacoes=2,
        )

        async def tudo():
            tarefa = asyncio.create_task(
                camada.invoke(
                    contexto(), "get_store_info", {}, allowed=("get_store_info",)
                )
            )
            await asyncio.sleep(0.05)
            tarefa.cancel()
            try:
                await tarefa
            except asyncio.CancelledError:
                pass
            # Deixa a *thread* acabar e o `done_callback` correr.
            await asyncio.sleep(0.6)
            return camada._tomadas.qsize()

        self.assertEqual(asyncio.run(tudo()), 2)


class TestRedaccaoDosNomes(_Base):
    """Os **nomes** dos argumentos tambem vem do modelo (critero 5)."""

    def test_um_nome_que_o_esquema_nao_declara_nao_entra_na_linha(self) -> None:
        canario = "contacto 999123456789"
        redigido = auditoria.redigir({canario: "x", "cart_id": "c-1"}, ["cart_id"])
        self.assertEqual(
            redigido, {"cart_id": "str", auditoria.NAO_DECLARADOS: 1}
        )
        self.assertNotIn(canario, repr(redigido))

    def test_sem_campos_declarados_nenhum_nome_passa(self) -> None:
        """Falha fechada: nao se confia num nome por nao se saber de onde veio."""
        self.assertEqual(
            auditoria.redigir({"cart_id": "c-1"}),
            {auditoria.NAO_DECLARADOS: 1},
        )

    def test_a_linha_de_um_argumento_inventado_nao_leva_o_nome(self) -> None:
        """E o caminho `VALIDATION_ERROR`, que e onde um nome inventado chega."""
        canario = "telefone 999123456789"
        camada, ligacao, _ = self.camada()
        resultado = self.invocar(camada, args={"cart_id": "c-1", canario: 1})
        self.assertEqual(resultado.error.codigo, erros.VALIDATION_ERROR)
        self.assertEqual(len(ligacao.linhas_de_auditoria()), 1)
        self.assertNotIn(canario, repr(ligacao.linhas_de_auditoria()[0]))


class TestDisjuntorDepoisDaRevisao(_Base):
    def relogio(self):
        agora = {"t": 0.0}
        return agora, lambda: agora["t"]

    def test_um_erro_de_negocio_nao_apaga_a_contagem(self) -> None:
        """Um backend a alternar negocio/falha tem de acabar por abrir.

        A primeira versao chamava `registar_sucesso` no caminho do
        `ErroDeBackend`, e isso **apaga** o estado: a contagem voltava a zero a
        cada resposta de negocio e o disjuntor nunca abria.
        """
        agora, relogio = self.relogio()
        disjuntor = Disjuntor(falhas=2, pausa_ms=1_000, relogio=relogio)
        disjuntor.registar_falha("com")
        disjuntor.absolver("com")
        self.assertTrue(
            disjuntor.registar_falha("com"),
            "o `absolver` apagou a contagem; o disjuntor nunca abriria",
        )

    def test_na_camada_um_erro_de_negocio_nao_apaga_a_contagem(self) -> None:
        """A mesma propriedade, medida **na camada** e nao no disjuntor.

        **Isto saiu de uma mutacao sobrevivente**, e a licao e a que este
        repositorio ja tinha escrita: um teste pode passar pela razao errada. O
        `test_um_erro_de_negocio_nao_apaga_a_contagem` chama o
        `disjuntor.absolver` **directamente**, pelo que prova o que o `absolver`
        faz — e nao que a camada o chama. A mutacao que repoe o
        `registar_sucesso` no `chamar_backend` passava por ele sem o acordar.
        Corre-se pelo `invoke`, com um backend a alternar.

        A sequencia e o que importa: com `falhas=2`, uma falha, uma resposta de
        negocio, outra falha. Com `absolver`, a contagem chega a dois e o
        disjuntor abre; com `registar_sucesso`, a resposta de negocio poe-a a
        zero e ele **nunca** abre.
        """
        respostas = iter([
            ValueError("em baixo"),
            ErroDeBackend(erros.NOT_FOUND, "nao ha"),
            ValueError("em baixo"),
        ])

        def executor(_pedido: Pedido) -> Resposta:
            raise next(respostas)

        agora, relogio = self.relogio()
        disjuntor = Disjuntor(falhas=2, pausa_ms=10_000, relogio=relogio)
        camada, _, _ = self.camada(
            especificacoes=(
                EspecificacaoDeTool(
                    nome="criar_pedido",
                    klass="money",
                    backend="com",
                    modelo=ArgumentosDeEnsaio,
                    executor=executor,
                    campo_de_confirmacao="cart_id",
                ),
            ),
            disjuntor=disjuntor,
        )
        codigos = [self.invocar(camada).error.codigo for _ in range(3)]
        self.assertEqual(
            codigos,
            [erros.UPSTREAM_DOWN, erros.NOT_FOUND, erros.UPSTREAM_DOWN],
        )
        self.assertTrue(
            disjuntor.aberto("com"),
            "a resposta de negocio apagou a contagem: um backend a alternar "
            "entre negocio e falha nunca abre o disjuntor",
        )

    def test_a_tentativa_de_meio_aberto_caduca(self) -> None:
        """Senao uma `BaseException` deixa o backend em disjuntor permanente."""
        agora, relogio = self.relogio()
        disjuntor = Disjuntor(falhas=1, pausa_ms=1_000, relogio=relogio)
        disjuntor.registar_falha("com")
        agora["t"] = 2.0
        self.assertTrue(disjuntor.permite("com"), "a tentativa de meio-aberto")
        self.assertFalse(disjuntor.permite("com"), "a segunda, dentro do prazo")
        agora["t"] = 4.0
        self.assertTrue(
            disjuntor.permite("com"),
            "quem levou a tentativa nunca respondeu e a porta ficou fechada "
            "para sempre",
        )


class TestMetricasNoFinally(_Base):
    def test_uma_auditoria_que_levanta_nao_perde_o_contador(self) -> None:
        ligacao = _Ligacao()
        ligacao.levantar_em = "INSERT INTO platform.tool_audit"
        metricas = MetricasDoAgr()
        camada, _, _ = self.camada(ligacao=ligacao, metricas=metricas)
        with self.assertRaises(auditoria.AuditoriaIndisponivelError):
            self.invocar(camada)
        self.assertEqual(
            metricas.ler().get(f"{METRICA_TOOL_INVOCACOES}:criar_pedido"), 1
        )


class TestFactIdOpaco(_Base):
    """«Um `fact_id` e opaco» passou de regra escrita a regra imposta.

    Era uma frase para o KAM-031 e o KAM-032, e uma frase nao e imposta por
    ninguem — a revisao adversarial notou-o. A camada nao sabe o que e opaco
    para cada tool, mas sabe **isto**: um `fact_id` que contenha um valor de
    argumento deriva de texto do cliente, e a coluna `fact_ids` passava a levar
    o que o critero 5 fecha para as outras. Foi o defeito que o varrimento com
    canarios apanhou no executor de ensaio (`fact_id=f"f-{cart_id}"`).
    """

    def linha(self, fact_id: str, args: dict) -> None:
        auditoria.LinhaDeAuditoria(
            ctx=contexto(),
            tool="criar_pedido",
            tool_version="1",
            klass="money",
            args=args,
            status=auditoria.STATUS_OK,
            latency_ms=1,
            facts=(
                erros.Fact(
                    fact_id=fact_id, kind="total", value=1, retrieved_at="z"
                ),
            ),
        )

    def test_um_fact_id_que_leva_um_argumento_e_recusado(self) -> None:
        with self.assertRaises(auditoria.FactIdDerivadoError):
            self.linha("f-999123456789", {"cart_id": "999123456789"})

    def test_um_fact_id_opaco_passa(self) -> None:
        self.linha("f-000001", {"cart_id": "999123456789"})

    def test_levanta_e_nao_redige(self) -> None:
        """Um `fact_id` redigido deixava de resolver a citacao que ele resolve.

        E por isso que e excepcao e nao um dos dez codigos do §6.5: nenhum deles
        descreve isto, e nao e uma resposta de negocio — e a tool a cunhar mal um
        identificador.
        """
        self.assertTrue(issubclass(auditoria.FactIdDerivadoError, ValueError))
        self.assertNotIn("FactIdDerivado", erros.CODIGOS)


class TestFactParaOKam032(_Base):
    def test_o_sku_existe_e_e_anulavel(self) -> None:
        """O KAM-032 declara `Fact(kind, …, sku, fact_id, retrieved_at)`."""
        com = erros.Fact(
            fact_id="f-1", kind="price", value=1200, retrieved_at="z", sku="SKU-1"
        )
        self.assertEqual(com.sku, "SKU-1")
        sem = erros.Fact(fact_id="f-2", kind="total", value=1, retrieved_at="z")
        self.assertIsNone(sem.sku, "um total de carrinho nao tem sku")

    def test_os_kinds_que_faltam_ao_kam032_estao_registados(self) -> None:
        """Nao se acrescentam por antecipacao, mas a divida fica escrita."""
        self.assertEqual(erros.KINDS, ("price", "stock", "total", "datetime"))
        dividas = (_RAIZ / "docs/dividas-documentais.md").read_text(encoding="utf-8")
        for kind in ("`name`", "`qty`", "`discount`"):
            self.assertIn(kind, dividas)
        self.assertIn("KAM-032", dividas)


# ----------------------------------------------------------- a arquitectura
class TestArquitectura(_Base):
    def test_a_tls_e_a_unica_via_de_escrita_no_platform(self) -> None:
        import sys

        sys.path.insert(0, str(_RAIZ / "tools"))
        from lint_arch import tool_schema

        self.assertEqual(tool_schema.check(_RAIZ), [])

    def test_o_lint_e_a_camada_proibem_os_mesmos_parametros(self) -> None:
        """Duas copias da lista, e uma maquina a impedi-las de divergir."""
        import sys

        sys.path.insert(0, str(_RAIZ / "tools"))
        from lint_arch import tool_schema

        self.assertEqual(
            tuple(tool_schema.PARAMETROS_PROIBIDOS), tuple(PARAMETROS_PROIBIDOS)
        )

    def test_quem_importa_a_tls_e_uma_lista_fechada_de_dois(self) -> None:
        """Dois modulos do AGR importam a camada, e cada um tem a sua razao.

        `__main__.py` constroi-a e injecta-a — e o unico sitio onde o catalogo e
        a instancia nascem. `metricas.py` importa o catalogo (e so o catalogo)
        para **derivar** as etiquetas, que e a licao que o KAM-027 pagou no
        `test_gate11`: uma lista literal de nomes de tool transformava «as tools
        sao as do catalogo» numa lista de onze.

        O teste e de lista fechada e nao de proibicao porque e isso que importa
        aqui: o acoplamento `metricas -> tls` fecha-se em triangulo com
        `camada -> metricas`, e o que impede o ciclo e o `tls/__init__.py` nao
        importar nada. Um terceiro importador e a altura de reler isso.

        **E houve um terceiro, e releu-se: o `degradacao.py` (KAM-037).** Importa
        **so** o `tls/disjuntor.py`, que nao importa nada do pacote — nem o
        `metricas.py`, nem a `camada.py` —, pelo que nao acrescenta aresta
        nenhuma ao triangulo. O ciclo que haveria era outro e esta cortado pelo
        mesmo remedio do `metricas.py`: o `degradacao.py` importa o `metricas.py`
        no topo e o `metricas.py` importa o `degradacao.py` **dentro** do
        `_valores_derivados`, com `lru_cache`. Ha ensaio que importa os tres
        ficheiros sozinhos.
        """
        import re

        raiz = _RAIZ / "services" / "agr" / "src" / "kamba_agr"
        padrao = re.compile(r"^\s*(?:from|import)\s+\.?tls|from \.tls", re.M)
        importadores = sorted(
            caminho.relative_to(raiz).as_posix()
            for caminho in raiz.glob("**/*.py")
            if "tls" not in caminho.parts
            and padrao.search(caminho.read_text(encoding="utf-8"))
        )
        self.assertEqual(
            importadores, ["__main__.py", "degradacao.py", "metricas.py"]
        )

    def test_o_degradacao_so_importa_o_disjuntor_da_tls(self) -> None:
        """O terceiro importador nao alarga o acoplamento: e **um** modulo.

        E a condicao sob a qual a lista fechada acima passou a ter tres nomes em
        vez de dois: se o `degradacao.py` importasse a `camada.py` ou o
        `catalogo.py`, o triangulo que a *docstring* descreve ganhava um lado.
        """
        import re

        caminho = (
            _RAIZ / "services" / "agr" / "src" / "kamba_agr" / "degradacao.py"
        )
        corpo = caminho.read_text(encoding="utf-8")
        importados = sorted(
            set(re.findall(r"^from \.tls\.(\w+) import", corpo, re.M))
        )
        self.assertEqual(importados, ["disjuntor"])

    def test_os_tres_ficheiros_importam_se_sozinhos(self) -> None:
        """O ciclo `metricas <-> degradacao` esta cortado, e mede-se a correr.

        A forma de o medir e a do KAM-027: um subprocesso por ficheiro, a
        importa-lo **sozinho**. Um ciclo de importacao funciona ou falha **pela
        ordem** em que alguem importa primeiro, pelo que importar os tres no
        mesmo processo nao o apanha.
        """
        import subprocess
        import sys

        for modulo in (
            "kamba_agr.degradacao",
            "kamba_agr.metricas",
            "kamba_agr.verticais.vendedor.degradado.intencoes",
        ):
            with self.subTest(modulo=modulo):
                acabado = subprocess.run(
                    [sys.executable, "-c", f"import {modulo}"],
                    capture_output=True,
                    text=True,
                    check=False,
                )
                self.assertEqual(
                    acabado.returncode, 0, acabado.stderr[-800:]
                )


# ------------------------------------------------------------ idempotencia
class TestDerivacaoDaChave(_Base):
    """O criterio 6 do KAM-029: a chave nao depende de telefone, BSUID nem tempo.

    **O teste de propriedade mede a independencia contra as colunas que
    existem**, e nao contra uma ideia de tempo. As quatro partes do §6.3 sao
    `(tenant_id, contact_id, tool, cart_id)`; tudo o mais que o `ToolContext`
    tem — `turn_id`, `run_id`, `conversation_id`, `channel_id`, `graph_version`
    — e exactamente o que **nao** pode entrar, e e por ai que um relogio
    entraria: um `turn_id` ou um `run_id` muda a cada turno, e uma chave que os
    levasse dentro desduplicava uma intencao por turno em vez de por carrinho.

    O `TestOControlDaDerivacao` logo abaixo prova que este oraculo apanha isso.
    """

    #: O intervalo ficticio da casa (`999` + nove algarismos, sem `+`), que e o
    #: que a nota do KAM-025 manda usar. Um exemplo de fuga escrito com um
    #: numero de forma real **e** a fuga, e o *gate* 7 recusou cinco ficheiros
    #: do KAM-028 por isso.
    TELEFONE = "999123456789"

    def _mil_combinacoes(self):
        for i in range(1000):
            yield (
                f"{i:08d}-1111-4111-8111-111111111111",
                f"{i:08d}-3333-4333-8333-333333333333",
                f"tool_{i % 7}",
                f"cart-{i}",
            )

    def test_mil_combinacoes_nao_dependem_do_turno_nem_do_relogio(self) -> None:
        """Mil chaves, cada uma derivada duas vezes com turno e execucao novos."""
        instaveis = []
        for tenant, contacto, tool, cart in self._mil_combinacoes():
            primeira = idempotency.derivar(
                contexto(tenant_id=tenant, contact_id=contacto, turn_id="t-1"), tool, cart
            )
            # Tudo o que muda entre dois toques do mesmo carrinho: turno novo,
            # execucao nova, conversa nova, canal novo, versao de grafo nova.
            segunda = idempotency.derivar(
                ToolContext.de_estado(
                    estado_valido(
                        tenant_id=tenant,
                        contact_id=contacto,
                        turn_id="t-2",
                        conversation_id="77777777-7777-4777-8777-777777777777",
                        channel_id="88888888-8888-4888-8888-888888888888",
                    ),
                    run_id="r-2",
                    graph_version="9.9.9",
                ),
                tool,
                cart,
            )
            if primeira != segunda:
                instaveis.append((tenant, tool, cart))
        self.assertEqual(instaveis, [], "entradas dependentes de turno/relogio")

    def test_mil_chaves_tem_a_forma_de_um_sha256_e_nenhuma_leva_telefone(self) -> None:
        """O criterio 6: «a coluna `key` nunca contem `+244`».

        Prova-se de duas maneiras e as duas fazem falta. Aqui mede-se que a
        chave sai hexadecimal **mesmo com um telefone em todas as partes de
        onde ela se deriva**; na base, o `CHECK tool_idempotency_key_sha256`
        recusa qualquer outra forma, qualquer que seja o chamador — e essa e a
        que nao depende deste teste estar certo
        (`db/tests_agr/test_idempotencia.py`).
        """
        forma = re.compile(r"^[0-9a-f]{64}$")
        # A revisao adversarial notou que a docstring dizia «em todas as partes
        # de onde ela se deriva» e ele entra so numa. Corrigido acima.
        for i in range(1000):
            # O telefone entra **so pelo `cart_id`**, e e o que a docstring
            # devia ter dito: e o unico campo opaco e de texto livre das quatro
            # partes, e portanto o unico por onde um defeito do `propose_cart` o
            # poderia trazer. O `tenant_id` e o `contact_id` sao UUID e o `tool`
            # tem gramatica de identificador.
            chave = idempotency.derivar(
                contexto(), f"tool_{i % 7}", f"{self.TELEFONE}-{i}"
            )
            self.assertRegex(chave, forma)
            self.assertNotIn("+244", chave)
            self.assertNotIn(self.TELEFONE, chave)

    def test_o_comprimento_a_prefixar_desfaz_a_ambiguidade(self) -> None:
        """Duas particoes diferentes das mesmas partes dao chaves diferentes.

        E a razao escrita na nota do `idempotency.py`: com um separador literal,
        um `cart_id` que o contivesse punha a encomenda de um cliente a responder
        pela de outro. O `cart_id` e **opaco** e nenhum caractere e seguro.
        """
        ctx = contexto()
        self.assertNotEqual(
            idempotency.derivar(ctx, "criar_pedido", "a|b"),
            idempotency.derivar(ctx, "criar_pedido|a", "b"),
        )
        # E o separador nao e o `|`: experimenta-se o que um `cart_id` opaco
        # pode ter dentro.
        for sufixo in ("|", ":", "\x1f", "0:", " "):
            self.assertNotEqual(
                idempotency.derivar(ctx, "criar_pedido", f"c-1{sufixo}"),
                idempotency.derivar(ctx, "criar_pedido", "c-1"),
            )

    def test_as_quatro_partes_entram_todas(self) -> None:
        """Mudar qualquer uma das quatro muda a chave — senao nao servia."""
        base = idempotency.derivar(contexto(), "criar_pedido", "c-1")
        self.assertNotEqual(
            base, idempotency.derivar(contexto(tenant_id=CONTACTO), "criar_pedido", "c-1")
        )
        self.assertNotEqual(
            base, idempotency.derivar(contexto(contact_id=TENANT), "criar_pedido", "c-1")
        )
        self.assertNotEqual(base, idempotency.derivar(contexto(), "book_slot", "c-1"))
        self.assertNotEqual(base, idempotency.derivar(contexto(), "criar_pedido", "c-2"))

    def test_os_tres_estados_sao_os_da_revisao_0022(self) -> None:
        """A lista fechada do codigo e a do `CHECK` da base nao divergem.

        Compara-se o **conjunto declarado** na revisao e nao uma contagem de
        ocorrencias no ficheiro: uma contagem passa a dizer outra coisa no dia em
        que alguem escrever `em_curso` num comentario, e foi o que a primeira
        versao deste teste fez. E a forma do confronto que o KAM-027 pos entre as
        duas listas de nomes de validacao.
        """
        fonte = (
            _RAIZ / "db/migrations/versions/0022_tool_idempotency.py"
        ).read_text(encoding="utf-8")
        declarada = re.search(r'LITERAIS_DE_ESTADO = "([^"]+)"', fonte)
        self.assertIsNotNone(declarada, "a revisao deixou de declarar os estados")
        self.assertEqual(
            tuple(parte.strip().strip("'") for parte in declarada.group(1).split(",")),
            idempotency.ESTADOS,
        )


class TestOControlDaDerivacao(_Base):
    """O controlo do criterio 6: **o oraculo acima pode falhar**.

    Sem isto, `test_mil_combinacoes_nao_dependem_do_turno_nem_do_relogio`
    passava com a derivacao a levar o `turn_id` dentro, ou a nao levar nada —
    e passava tambem se `derivar` devolvesse sempre a mesma cadeia. Sao os dois
    unicos modos de falha de um teste de estabilidade, e os dois tem canario.

    E a disciplina que o KAM-026, o KAM-027 e o KAM-028 pagaram tres vezes: um
    criterio pode estar satisfeito pela razao errada, e por cada caixa pergunta-se
    o que a faria passar com o codigo apagado.
    """

    def test_uma_derivacao_que_leve_o_turno_e_apanhada(self) -> None:
        import hashlib

        def com_turno(ctx, tool, referencia):
            partes = (ctx.tenant_id, ctx.contact_id, tool, referencia, ctx.turn_id)
            crua = b"".join(
                f"{len(p.encode('utf-8'))}:".encode("ascii") + p.encode("utf-8")
                for p in partes
            )
            return hashlib.sha256(crua).hexdigest()

        primeira = com_turno(contexto(turn_id="t-1"), "criar_pedido", "c-1")
        segunda = com_turno(contexto(turn_id="t-2"), "criar_pedido", "c-1")
        self.assertNotEqual(
            primeira, segunda, "o canario tem de ser instavel, senao nao e canario"
        )

    def test_uma_derivacao_constante_e_apanhada(self) -> None:
        """O outro modo de falha: estavel por nao olhar para nada."""
        self.assertNotEqual(
            idempotency.derivar(contexto(), "criar_pedido", "c-1"),
            idempotency.derivar(contexto(), "criar_pedido", "c-2"),
        )


class TestProtocoloDeIdempotencia(_Base):
    """Os criterios 2, 3 e 8 contra a `tool_idempotency` em memoria.

    O que **nao** se mede aqui esta em `db/tests_agr/test_idempotencia.py`: os
    50 concorrentes (criterio 1), a falha injectada (4), o registo `em_curso` que
    nao bloqueia (5) e a retencao (7) sao-no contra um PostgreSQL a serio, porque
    e o `INSERT … ON CONFLICT` e a RLS que os provam e nao um dicionario.

    **O oraculo de todos eles e o contador de chamadas ao backend**, e nao o que
    o `invoke` devolve: um teste de idempotencia que meca o resultado passa com a
    idempotencia apagada — as duas invocacoes devolvem o mesmo `ok=True` de
    qualquer maneira. Foi o defeito do X-02 do KAM-028, que media onze recusas
    em vez de onze tools.
    """

    def camada_que_conta(self, **troca):
        """Uma camada de ensaio com um backend que conta e que e idempotente.

        O backend **e idempotente pela chave** (devolve o mesmo `order_id` para
        a mesma chave), que e o que o criterio 4 supoe por extenso. Sem isso, o
        contador media a idempotencia da camada e mais nada, e a frase «o backend
        e idempotente pela chave» ficava sem nada a sustenta-la.
        """
        chamadas: list[str | None] = []
        encomendas: dict[str | None, str] = {}

        def executor(pedido):
            chamadas.append(pedido.chave)
            encomendas.setdefault(pedido.chave, f"ord-{len(encomendas) + 1}")
            return Resposta(data={"order_id": encomendas[pedido.chave]})

        especificacao = EspecificacaoDeTool(
            nome="criar_pedido",
            klass="money",
            backend="com",
            modelo=ArgumentosComNota,
            executor=executor,
            campo_de_confirmacao="cart_id",
        )
        troca.setdefault("dormir", self.dormir_com_guarda())
        camada, ligacao, _ = self.camada(especificacoes=(especificacao,), **troca)
        return camada, ligacao, chamadas, encomendas

    #: Quantas vezes o laco da espera pode dormir antes de a bateria desistir.
    #: O tecto de 3 s com intervalos de 50 ms dá 60; 200 é folga larga e continua
    #: a ser um numero finito.
    SESTAS_NO_MAXIMO = 200

    def dormir_com_guarda(self, relogio=None):
        """Um `dormir` que **levanta** em vez de deixar o laco girar para sempre.

        Uma bateria de unidade nunca deve pendurar, e esta familia pode: o laco
        do `reservar` espera por uma linha de outro, e uma mutacao que lhe tire o
        tecto transforma a espera num ciclo infinito. Sem esta guarda, o corredor
        de mutacoes nao distingue isso de a suite rebentar — reporta
        `PROVA INVALIDA`, que conta como **sobrevivente** e nao como apanhada.
        Foi o que aconteceu a primeira corrida de `idem:`.

        Com ela, a mutacao vira um `AssertionError` com nome, que e uma medicao.
        No codigo certo o tecto dispara aos 60 e a guarda nunca e tocada.
        """
        sestas = [0]

        def dormir(segundos):
            sestas[0] += 1
            if sestas[0] > self.SESTAS_NO_MAXIMO:
                raise AssertionError(
                    f"a espera dormiu {sestas[0]} vezes sem tecto: o laco do "
                    "`reservar` nao esta a medir o `TECTO_DE_ESPERA_MS`"
                )
            if relogio is not None:
                relogio[0] += segundos

        return dormir

    def test_o_segundo_toque_devolve_o_guardado_sem_chamar_o_backend(self) -> None:
        """O criterio 8, do lado da TLS: um `wamid` novo e um **turno novo**.

        O que o grafo faz com o `stage` e do KAM-031 (o `confirm_gate` manda a
        confirmacao antiga para o `compose` com o fact `STALE_CONFIRMATION`) e o
        `ToolContext` nem tem `stage` — nao ha daqui como o ver. O que esta
        metade prova e que, **se** o toque antigo chegar a camada, ele nao toca
        no backend: mesmo carrinho, turno novo, chave de turno nova.
        """
        camada, _, chamadas, _ = self.camada_que_conta()
        primeiro = self.invocar(camada)
        segundo = self.invocar(
            camada,
            ctx=contexto(turn_id="t-2"),
            confirmation=Confirmation(
                botao="confirm:c-1", contact_id=CONTACTO, turn_id="t-2"
            ),
            idempotency_key="k-2",
        )

        self.assertEqual(len(chamadas), 1, "o backend correu mais do que uma vez")
        self.assertFalse(primeiro.idempotent_replay)
        self.assertTrue(segundo.idempotent_replay)
        self.assertEqual(primeiro.data, segundo.data)

    def test_um_replay_escreve_uma_linha_de_auditoria_e_com_a_chave_do_turno(self) -> None:
        """O criterio 5 do **KAM-028** («uma linha por invocacao») num caminho novo.

        Num *replay* o passo 5 devolve um `ToolResult` e os passos 6 e 7 **nao
        correm**: quem escreve a linha e o `finally` do pipeline. Se ela nao se
        escrevesse, duas invocacoes `money` davam **uma** linha e o registo
        passava a contar menos invocacoes de dinheiro do que houve — sem nada a
        dize-lo, porque o resultado devolvido e o mesmo.

        E a linha leva a chave **do turno** e nao a do carrinho, que e a decisao
        do dicionario §3.28: sao duas chaves, e a coluna e da de cima.
        """
        camada, ligacao, chamadas, _ = self.camada_que_conta()
        self.invocar(camada)
        self.invocar(
            camada,
            ctx=contexto(turn_id="t-2"),
            confirmation=Confirmation(
                botao="confirm:c-1", contact_id=CONTACTO, turn_id="t-2"
            ),
            idempotency_key="k-2",
        )

        linhas = ligacao.linhas_de_auditoria()
        self.assertEqual(len(chamadas), 1)
        self.assertEqual(len(linhas), 2, "o replay nao escreveu linha de auditoria")
        # `status` e `idempotency_key` pela ordem das `COLUNAS` do `auditoria.py`.
        indice_chave = auditoria.COLUNAS.index("idempotency_key")
        indice_status = auditoria.COLUNAS.index("status")
        self.assertEqual([linha[indice_status] for linha in linhas], ["ok", "ok"])
        self.assertEqual([linha[indice_chave] for linha in linhas], ["k-1", "k-2"])

    def test_a_fronteira_da_janela_da_um_pedido_e_a_recompra_da_dois(self) -> None:
        """O criterio 2, com relogio simulado.

        A chave nao tem tempo dentro, pelo que a fronteira dos cinco minutos
        **nao existe** — e e isso que se mede: um relogio que salta de 4:59 para
        5:01 nao faz diferenca nenhuma, e um `cart_id` novo faz toda.
        """
        agora = [0.0]
        camada, _, chamadas, encomendas = self.camada_que_conta(
            relogio=lambda: agora[0]
        )

        agora[0] = 4 * 60 + 59
        self.invocar(camada)
        agora[0] = 5 * 60 + 1
        self.invocar(camada)
        self.assertEqual(len(chamadas), 1, "a fronteira da janela duplicou o pedido")

        # A recompra, imediatamente a seguir: `cart_id` novo, pedido novo.
        self.invocar(
            camada,
            args={"cart_id": "c-2"},
            confirmation=Confirmation(
                botao="confirm:c-2", contact_id=CONTACTO, turn_id="t-1"
            ),
        )
        self.assertEqual(len(chamadas), 2, "a recompra nao criou pedido novo")
        self.assertEqual(len(encomendas), 2)

    def test_o_mesmo_cart_id_com_outros_argumentos_recusa_sem_chamar(self) -> None:
        """O criterio 3: `INTENT_REUSED_WITH_DIFFERENT_CONTENT`."""
        camada, _, chamadas, _ = self.camada_que_conta()
        self.invocar(camada)
        resultado = self.invocar(camada, args={"cart_id": "c-1", "nota": "mudei"})

        self.assertFalse(resultado.ok)
        self.assertEqual(resultado.error.codigo, "INTENT_REUSED_WITH_DIFFERENT_CONTENT")
        self.assertEqual(len(chamadas), 1, "recusou e chamou o backend na mesma")

    def test_uma_linha_em_curso_de_outro_nao_executa_e_estoura_o_tecto(self) -> None:
        """O criterio 5, em memoria: a espera tem tecto e nao chama o backend.

        O relogio e o `dormir` sao dobragens: o tecto mede-se por **quanto o
        relogio andou**, nao por quanto o teste demorou. Um teste que esperasse
        3 s a serio media a maquina.
        """
        agora = [0.0]
        camada, ligacao, chamadas, _ = self.camada_que_conta(
            relogio=lambda: agora[0], dormir=self.dormir_com_guarda(agora)
        )
        # Uma reserva de outro, ja em curso, com **dez segundos**: mais do que os
        # 2 s que o criterio nomeia, e muito menos do que os 2 min ao fim dos
        # quais ela se considera abandonada. E a janela em que o dono esta vivo.
        chave = idempotency.derivar(contexto(), "criar_pedido", "c-1")
        ligacao.idempotencia[chave] = [
            "em_curso",
            auditoria.impressao({"cart_id": "c-1", "nota": ""}),
            None,
            ligacao.agora - _dt.timedelta(seconds=10),
        ]

        resultado = self.invocar(camada)

        self.assertFalse(resultado.ok)
        self.assertEqual(resultado.error.codigo, "UPSTREAM_TIMEOUT")
        self.assertEqual(chamadas, [], "esperou e executou na mesma")
        self.assertGreaterEqual(agora[0], 3.0, "desistiu antes dos 3 s do §6.3")
        self.assertLess(agora[0], 3.2, "esperou para alem do tecto")

    def test_uma_em_curso_abandonada_retoma_se_em_vez_de_esperar(self) -> None:
        """A **idade** decide, e sem isto o `created_at` era decoração.

        Esta bateria e o par da de cima, e e ela que torna o «há mais de 2 s» do
        critério 5 uma medição em vez de uma afirmação: a **única** diferença
        entre as duas é a idade da linha, e o desfecho é o oposto. Sem ela, o
        teste de cima passava igual com a idade apagada — foi o achado 3 da
        revisão adversarial, e é a mesma forma do varrimento do KAM-026 que dava
        sempre zero.

        O que fecha é um caminho que deixava dinheiro em risco: uma linha
        `em_curso` cujo `fechar` não passou (a ligação caiu entre o backend e o
        registo) não era retomada por ninguém, a varredura recusa apagar
        `em_curso` por idade, e aquele `cart_id` respondia `UPSTREAM_TIMEOUT`
        para sempre — com a encomenda já feita. O cliente saía por um carrinho
        novo, que tem `cart_id` novo, logo chave nova: **segunda encomenda**.
        """
        camada, ligacao, chamadas, encomendas = self.camada_que_conta()
        chave = idempotency.derivar(contexto(), "criar_pedido", "c-1")
        ligacao.idempotencia[chave] = [
            "em_curso",
            auditoria.impressao({"cart_id": "c-1", "nota": ""}),
            None,
            ligacao.agora - _dt.timedelta(minutes=5),
        ]

        resultado = self.invocar(camada)

        self.assertTrue(resultado.ok, "nao retomou uma linha abandonada")
        self.assertEqual(len(chamadas), 1, "retomou e nao chamou o backend")
        self.assertEqual(len(encomendas), 1)
        self.assertEqual(ligacao.idempotencia[chave][0], "concluida")
        # E a retoma **nao** reescreve o `created_at`: se o fizesse, uma linha
        # que falhasse a cada volta ganhava idade nova e a retencao nunca lhe
        # chegava.
        self.assertEqual(
            ligacao.idempotencia[chave][3], ligacao.agora - _dt.timedelta(minutes=5)
        )

    def test_uma_linha_falhada_retoma_se_e_o_backend_devolve_o_mesmo(self) -> None:
        """O criterio 4 em memoria; o que o mede a serio e a falha injectada."""
        camada, ligacao, chamadas, encomendas = self.camada_que_conta()
        self.invocar(camada)
        chave = idempotency.derivar(contexto(), "criar_pedido", "c-1")
        # O desfecho que uma falha a meio deixa: linha fechada como `falhada`,
        # sem resultado, com o efeito ja feito no backend.
        ligacao.idempotencia[chave][0] = "falhada"
        ligacao.idempotencia[chave][2] = None

        resultado = self.invocar(camada)

        self.assertTrue(resultado.ok)
        self.assertEqual(len(chamadas), 2, "a retoma nao voltou a chamar o backend")
        self.assertEqual(
            len(encomendas), 1, "o backend nao foi idempotente pela chave"
        )
        self.assertEqual(ligacao.idempotencia[chave][0], "concluida")

    def test_um_fecho_que_falha_nao_mascara_a_excepcao_original(self) -> None:
        """O que sobe tem de ser a falha que travou o turno, e nao o sintoma.

        O fecho da reserva corre em **dois** caminhos: no `except`, antes de a
        tomada cair, e no `finally`. Se a marca de posse só se limpasse **depois**
        de a escrita passar, uma ligação já quebrada dava isto: a tentativa do
        `except` levanta (e é engolida ali, de propósito), a marca fica de pé, e
        a tentativa do `finally` levanta **de dentro do `finally`** —
        substituindo a excepção original. Quem lesse o log de uma tool `money`
        via o `InterfaceError` do driver e não a causa.

        Encontrado a raciocinar sobre o caminho, não a correr: a bateria do
        critério 4 não o apanha porque ali o fecho **passa**.
        """
        camada, ligacao, _, _ = self.camada_que_conta()

        class _FalhaDoFecho(RuntimeError):
            pass

        original = idempotency.fechar

        def fechar_que_falha(*argumentos, **nomeados):
            raise _FalhaDoFecho("a ligacao ja estava quebrada")

        idempotency.fechar = fechar_que_falha
        ligacao.levantar_em = "INSERT INTO platform.tool_audit"
        try:
            with self.assertRaises(auditoria.AuditoriaIndisponivelError):
                self.invocar(camada)
        finally:
            idempotency.fechar = original

    def test_uma_read_nao_reserva_nada(self) -> None:
        """Repetir uma leitura nao tem efeito, e por isso nao leva chave."""
        _, ligacao, _ = self.camada()
        camada, ligacao, _ = self.camada(
            especificacoes=(
                EspecificacaoDeTool(
                    nome="get_store_info",
                    klass="read",
                    backend="plataforma",
                    modelo=ArgumentosDeEnsaio,
                    executor=_executor_ok,
                ),
            )
        )
        self.invocar(
            camada,
            name="get_store_info",
            allowed=("get_store_info",),
            confirmation=None,
            idempotency_key=None,
        )
        self.assertEqual(ligacao.idempotencia, {})


if __name__ == "__main__":
    unittest.main()
