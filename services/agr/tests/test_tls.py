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
from kamba_agr.tls import auditoria, erros
from kamba_agr.tls.camada import (
    PASSOS,
    BoundTool,
    ToolLayer,
    nomes_dos_passos,
)
from kamba_agr.tls.catalogo import ESPECIFICACOES_DO_PILOTO, catalogo_do_piloto
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
        resposta = self._ligacao.respostas.get(_chave_do_sql(sql))
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


class ArgumentosSemForbid(BaseModel):
    cart_id: str


class ArgumentosComTenant(BaseModel):
    model_config = ConfigDict(extra="forbid")
    tenant_id: str


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
    def test_sao_dez_e_os_do_documento(self) -> None:
        self.assertEqual(len(erros.CODIGOS), 10)
        self.assertEqual(len(set(erros.CODIGOS)), 10)
        self.assertEqual(
            set(erros.CODIGOS),
            {
                "NOT_FOUND", "OUT_OF_STOCK", "PRICE_CHANGED", "LIMIT_EXCEEDED",
                "ENTITLEMENT_DENIED", "TOOL_NOT_ALLOWED", "TENANT_MISMATCH",
                "UPSTREAM_TIMEOUT", "UPSTREAM_DOWN", "VALIDATION_ERROR",
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
        self.assertEqual(
            {nome for nome, credor in declaradas.items() if credor == "KAM-031"},
            {
                "search_catalog", "get_price_stock", "propose_cart",
                "criar_pedido", "get_order_status",
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
        redigido = auditoria.redigir({"query": "sapatos do Joao", "limite": 5})
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
        self.assertEqual(importadores, ["__main__.py", "metricas.py"])


if __name__ == "__main__":
    unittest.main()
