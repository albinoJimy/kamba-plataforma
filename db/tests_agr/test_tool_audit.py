"""A ToolLayer contra um PostgreSQL real (KAM-028): integracao e isolamento.

    TestAppendOnly        o que o privilegio **nao** mostra: o *trigger* morde
    TestGuardaDeArranque  o `confirmar()` que da o codigo de saida 6
    TestPipelineReal      os oito passos contra a base: entitlement, RLS, registo
    TestCobertura         critero 5: **uma** linha por invocacao `write`/`money`
    TestPrivacidade       critero 5: a linha nao leva texto nem telefone
    TestIsolamento        X-02 e X-04, com canarios
    TestRestricoes        os `CHECK` da revisao `0021`, um a um

O que **so** aqui se prova, e nao se prova com uma base falsa:

| Propriedade | Porque precisa da base |
|---|---|
| *append-only* | o `REVOKE` sozinho nao prende o dono, e o `ENABLE ALWAYS` nao prende quem nao pode `session_replication_role`. Sao tres camadas e cada uma mede-se contra o servidor |
| o `INSERT` por coluna | o `GRANT` e por coluna; uma coluna a mais no `INSERT` do codigo da `42501` e nada disso se ve num duplo |
| o SQL do `hook_de_tool` | uma base falsa compara SQL por texto e nunca o interpreta — e a licao do `tests_ten/base.py` |
| a RLS da `tool_audit` | a politica e da base. O `WITH CHECK` e o que impede uma linha de auditoria no nome de outro tenant |
| a `get_store_info` | le a `platform.tenants` a serio, sob RLS. E a razao pela qual o X-02 se consegue medir neste ticket |
| os `CHECK` | um `status` fora do dominio ou um `args_hash` de 31 octetos sao recusados pelo servidor, nao pelo codigo |

**Os canarios sao o oraculo do X-02** (`docs/tecnica/08` §3.7): semeia-se o
tenant B com uma marca unica e procura-se essa marca na resposta, no erro e na
linha de auditoria de uma invocacao feita com o estado de A. Zero ocorrencias e
o unico resultado aceitavel, e procura-se no **texto dos dados** e nao no nome
das colunas — que foi o defeito que o KAM-026 pagou (o varrimento dava zero por
procurar texto num campo `msgpack`).
"""

from __future__ import annotations

import asyncio
import unittest
import uuid

from pydantic import BaseModel, ConfigDict

from tests import factories
from tests.base import PRIVILEGIO_INSUFICIENTE
from tests_agr.base import ComAgr

from kamba_agr.tls import auditoria, erros  # noqa: E402
from kamba_agr.tls.camada import ToolLayer  # noqa: E402
from kamba_agr.tls.catalogo import ESPECIFICACOES_DO_PILOTO  # noqa: E402
from kamba_agr.tls.contexto import Confirmation, ToolContext  # noqa: E402
from kamba_agr.tls.especificacoes import (  # noqa: E402
    Catalogo,
    EspecificacaoDeTool,
    Pedido,
    Resposta,
)
from kamba_agr.tls.get_store_info import ArgumentosDeGetStoreInfo, executar  # noqa: E402

#: O SQLSTATE que o *trigger* de imutabilidade levanta.
VIOLACAO_DE_INTEGRIDADE = "23000"


class ArgumentosDoEnsaio(BaseModel):
    model_config = ConfigDict(extra="forbid")
    cart_id: str
    nota: str = ""


def _executor_de_ensaio(pedido: Pedido) -> Resposta:
    """Um backend que nao escreve nada, com um `order_id` e um *fact* **opacos**.

    Existe para exercitar o caminho `money` inteiro — confirmacao, chave,
    registo — sem precisar do COM nem do PAY, que e o que os *Detalhes
    Tecnicos* do bloco autorizam («*fakes* para os backends ainda
    inexistentes»). O que **nao** e *fake* e tudo o resto: o entitlement, a
    RLS, a linha de auditoria e os `CHECK`.

    **Os identificadores sao opacos e nao derivados do argumento**, e isto saiu
    de uma medicao e nao de estilo. A primeira versao devolvia
    `fact_id=f"f-{cart_id}"`, e o varrimento de privacidade encontrou o canario
    dentro da `tool_audit`: o `fact_id` vai para a coluna `fact_ids`, que e
    `text[]`, e um `fact_id` derivado de um argumento **poe texto do cliente no
    registo de auditoria** — pelo caminho que o critero 5 fecha para o
    `args_redacted` e que ninguem tinha olhado para os *facts*.

    A regra fica escrita para o KAM-031 e o KAM-032, que sao quem vai cunhar
    `fact_id` a serio: **um `fact_id` e opaco**. O que liga o *fact* ao que o
    produziu e a linha de `tool_audit`, nao o nome dele.

    O `_CONTADOR` existe para que dois *facts* do mesmo turno sejam distintos
    sem usar o argumento.
    """
    _CONTADOR.append(1)
    sufixo = f"{len(_CONTADOR):06d}"
    return Resposta(
        data={"order_id": f"o-{sufixo}"},
        facts=(
            erros.Fact(
                fact_id=f"f-{sufixo}",
                kind="total",
                value=1200,
                retrieved_at="2026-10-25T00:00:00Z",
            ),
        ),
    )


#: O contador de identificadores opacos do executor de ensaio.
_CONTADOR: list[int] = []


ESPECIFICACAO_DE_MONEY = EspecificacaoDeTool(
    nome="criar_pedido",
    klass="money",
    backend="com",
    modelo=ArgumentosDoEnsaio,
    executor=_executor_de_ensaio,
    campo_de_confirmacao="cart_id",
)

ESPECIFICACAO_DA_LOJA = EspecificacaoDeTool(
    nome="get_store_info",
    klass="read",
    backend="plataforma",
    modelo=ArgumentosDeGetStoreInfo,
    executor=executar,
)


class _ComTls(ComAgr):
    """Uma conversa, um entitlement activo, e a camada sobre uma ligacao `app`."""

    #: As declaradas do catalogo real **mais** as duas ligadas de ensaio. O
    #: catalogo e o verdadeiro no que importa ao X-02: as onze tools estao la.
    def catalogo(self) -> Catalogo:
        ligadas = {ESPECIFICACAO_DE_MONEY.nome, ESPECIFICACAO_DA_LOJA.nome}
        return Catalogo(
            tuple(e for e in ESPECIFICACOES_DO_PILOTO if e.nome not in ligadas)
            + (ESPECIFICACAO_DE_MONEY, ESPECIFICACAO_DA_LOJA)
        )

    def setUp(self) -> None:
        super().setUp()
        self.conversa = self.criar_conversa()
        self.dar_entitlement(self.conversa)
        self.ligacao_app = self.ligar("app")
        self.camada = ToolLayer(
            self.catalogo(), abrir_ligacao=lambda: self.ligacao_app
        )

    def dar_entitlement(self, conversa, *, ativo: bool = True) -> None:
        """Um entitlement activo **e o tenant em `ativo`**, que e metade disto.

        O `SQL_ENTITLEMENT` do KAM-009 nega `onboarding`, `suspenso` e
        `encerrado`, e e por isso que o `estado` entra aqui: o
        `factories.tenant` cria o tenant em `onboarding` (a omissao da `0001`),
        e sem esta linha **todas** as invocacoes davam `ENTITLEMENT_DENIED` —
        com os testes do pipeline a passar por um passo 2 que nunca chegava a
        ver um entitlement. E a armadilha do «satisfeito pela razao errada» do
        lado contrario: aqui falhava, mas pela razao errada.

        A limpeza e propria porque o `_limpar` do `ComAgr` nao apaga
        `entitlements`, e a FK `entitlements_tenant_fk` impede o `DELETE` do
        tenant. Registada **depois** do `super().setUp()`, pelo que corre
        **antes** daquele — o `addCleanup` e LIFO.
        """
        self.semente.execute(
            "UPDATE platform.tenants SET estado = 'ativo' WHERE id = %s",
            (conversa.tenant_id,),
        )
        factories.entitlement(
            self.semente, conversa.tenant_id, modulo="vendedor", ativo=ativo
        )
        factories.contexto(self.semente, None)
        self.addCleanup(self._apagar_entitlements, conversa.tenant_id)

    def _apagar_entitlements(self, tenant: str) -> None:
        self.semente.execute(
            "DELETE FROM platform.entitlements WHERE tenant_id = %s", (tenant,)
        )

    def contexto(self, conversa=None, **troca) -> ToolContext:
        conversa = conversa if conversa is not None else self.conversa
        estado = {
            "tenant_id": conversa.tenant_id,
            "channel_id": conversa.canal_id,
            "contact_id": conversa.contact_id,
            "conversation_id": conversa.conversation_id,
            "turn_id": "t-1",
            "vertical": "vendedor",
        }
        estado.update(troca)
        return ToolContext.de_estado(estado, run_id="r-1", graph_version="1.0.0")

    def invocar(self, nome: str, args: dict, *, ctx=None, **troca):
        padrao: dict = {
            "allowed": sorted(self.catalogo().nomes()),
            "confirmation": Confirmation(
                botao=f"confirm:{args.get('cart_id', '')}",
                contact_id=(ctx or self.contexto()).contact_id,
                turn_id="t-1",
            ),
            "idempotency_key": f"k-{uuid.uuid4().hex}",
        }
        padrao.update(troca)
        return asyncio.run(
            self.camada.invoke(ctx or self.contexto(), nome, args, **padrao)
        )

    def linhas(self, tenant: str | None = None) -> list[tuple]:
        """As linhas de `tool_audit`, lidas pelo administrador."""
        return self.consultar(
            "SELECT tool, klass, status, error_code, args_hash, args_redacted::text, "
            "       idempotency_key, result_hash, fact_ids::text, latency_ms, "
            "       tenant_id::text, contact_id::text, turn_id, run_id "
            "  FROM platform.tool_audit "
            " WHERE tenant_id = %s ORDER BY id",
            (tenant or self.conversa.tenant_id,),
        )


# -------------------------------------------------------------- append-only
class TestAppendOnly(_ComTls):
    def inserir_uma(self) -> None:
        self.invocar("criar_pedido", {"cart_id": "c-1"})
        self.ligacao_app.commit()

    def test_o_papel_da_aplicacao_nao_consegue_update_nem_delete(self) -> None:
        """Critero 6, e o privilegio **nao** e o que o impede."""
        self.inserir_uma()
        conexao = self.ligar("app")
        cursor = conexao.cursor()
        cursor.execute("SELECT set_config('app.tenant_id', %s, true)",
                       (self.conversa.tenant_id,))
        for sql in (
            "UPDATE platform.tool_audit SET status = 'ok'",
            "DELETE FROM platform.tool_audit",
        ):
            with self.subTest(sql=sql.split()[0]):
                self.assertErroSql(PRIVILEGIO_INSUFICIENTE, cursor, sql)

    def test_nem_o_dono_das_tabelas_consegue(self) -> None:
        """O `REVOKE` nao prende o dono: quem o prende e o *trigger*.

        E a razao pela qual o `test_privilegios` ve o `kamba_migrator` com tudo
        e a tabela continua *append-only*. Sem este teste, a matriz de
        privilegios parecia dizer o contrario do que a tabela faz.
        """
        self.inserir_uma()
        conexao = self.ligar("admin")
        cursor = conexao.cursor()
        for sql in (
            "UPDATE platform.tool_audit SET status = 'erro'",
            "DELETE FROM platform.tool_audit",
            "TRUNCATE platform.tool_audit",
        ):
            with self.subTest(sql=sql.split()[0]):
                self.assertErroSql(VIOLACAO_DE_INTEGRIDADE, cursor, sql)

    def test_o_trigger_resiste_ao_session_replication_role(self) -> None:
        """A terceira camada: `ENABLE ALWAYS`, e um *trigger* normal nao a tem."""
        self.inserir_uma()
        conexao = self.ligar("admin")
        cursor = conexao.cursor()
        cursor.execute("SET session_replication_role = replica")
        self.assertErroSql(
            VIOLACAO_DE_INTEGRIDADE, cursor, "DELETE FROM platform.tool_audit"
        )

    def test_os_dois_triggers_estao_enable_always(self) -> None:
        estados = self.consultar(
            "SELECT tgname::text, tgenabled::text FROM pg_trigger "
            " WHERE tgrelid = 'platform.tool_audit'::regclass AND NOT tgisinternal "
            " ORDER BY 1"
        )
        self.assertEqual(
            estados,
            [
                ("tool_audit_sem_truncate", "A"),
                ("tool_audit_sem_update_nem_delete", "A"),
            ],
        )


# ---------------------------------------------------------- guarda de arranque
class TestGuardaDeArranque(_ComTls):
    def test_o_papel_da_aplicacao_passa_a_guarda(self) -> None:
        auditoria.confirmar(self.ligar("app"))

    def test_um_papel_sem_o_grant_reprova_e_nomeia_as_colunas(self) -> None:
        """E o codigo de saida 6: sem isto, descobria-se no passo 7."""
        with self.assertRaises(auditoria.AuditoriaIndisponivelError) as capturado:
            auditoria.confirmar(self.ligar("resolver"))
        mensagem = str(capturado.exception)
        self.assertIn("INSERT", mensagem)
        for coluna in ("tenant_id", "tool", "klass"):
            self.assertIn(coluna, mensagem)

    def test_a_guarda_nao_escreve_nada(self) -> None:
        """A tabela e *append-only*: uma linha de ensaio ficava la para sempre."""
        antes = self.consultar("SELECT count(*) FROM platform.tool_audit")
        auditoria.confirmar(self.ligar("app"))
        self.assertEqual(
            self.consultar("SELECT count(*) FROM platform.tool_audit"), antes
        )


# ------------------------------------------------------------ pipeline real
class TestPipelineReal(_ComTls):
    def test_a_invocacao_money_corre_e_deixa_uma_linha(self) -> None:
        resultado = self.invocar("criar_pedido", {"cart_id": "c-1"})
        self.assertTrue(resultado.ok, resultado.error)
        self.assertTrue(resultado.data["order_id"].startswith("o-"))
        self.assertEqual(len(resultado.facts), 1)
        self.assertTrue(resultado.facts[0].fact_id.startswith("f-"))
        self.ligacao_app.commit()
        linhas = self.linhas()
        self.assertEqual(len(linhas), 1)
        (tool, klass, status, codigo, args_hash, redigido, chave, result_hash,
         fact_ids, latencia, tenant, contacto, turno, corrida) = linhas[0]
        self.assertEqual((tool, klass, status), ("criar_pedido", "money", "ok"))
        self.assertIsNone(codigo)
        self.assertEqual(len(args_hash), 32)
        self.assertEqual(len(result_hash), 32)
        self.assertIn(resultado.facts[0].fact_id, fact_ids)
        self.assertGreaterEqual(latencia, 0)
        self.assertEqual(tenant, self.conversa.tenant_id)
        self.assertEqual(contacto, self.conversa.contact_id)
        self.assertEqual((turno, corrida), ("t-1", "r-1"))
        self.assertTrue(chave)

    def test_sem_entitlement_activo_devolve_entitlement_denied(self) -> None:
        """O passo 2 contra a `platform.entitlements` a serio."""
        outra = self.criar_conversa()
        # Sem entitlement nenhum: o tenant fica em `ativo` para que o que nega
        # seja a **ausencia de linha** e nao o estado do tenant.
        self.semente.execute(
            "UPDATE platform.tenants SET estado = 'ativo' WHERE id = %s",
            (outra.tenant_id,),
        )
        factories.contexto(self.semente, None)
        camada = ToolLayer(self.catalogo(), abrir_ligacao=lambda: self.ligar("app"))
        resultado = asyncio.run(
            camada.invoke(
                self.contexto(outra),
                "criar_pedido",
                {"cart_id": "c-1"},
                allowed=["criar_pedido"],
                confirmation=Confirmation(
                    botao="confirm:c-1", contact_id=outra.contact_id, turn_id="t-1"
                ),
                idempotency_key="k-1",
            )
        )
        self.assertFalse(resultado.ok)
        self.assertEqual(resultado.error.codigo, erros.ENTITLEMENT_DENIED)

    def test_o_entitlement_desactivado_tambem_nega(self) -> None:
        outra = self.criar_conversa()
        self.dar_entitlement(outra, ativo=False)
        camada = ToolLayer(self.catalogo(), abrir_ligacao=lambda: self.ligar("app"))
        resultado = asyncio.run(
            camada.invoke(
                self.contexto(outra),
                "criar_pedido",
                {"cart_id": "c-1"},
                allowed=["criar_pedido"],
                confirmation=Confirmation(
                    botao="confirm:c-1", contact_id=outra.contact_id, turn_id="t-1"
                ),
                idempotency_key="k-1",
            )
        )
        self.assertEqual(resultado.error.codigo, erros.ENTITLEMENT_DENIED)

    def test_o_tecto_por_pedido_do_passo_2_nega_e_nao_consome(self) -> None:
        """O `tecto` do passo 2 contra o `platform.ten_tecto` a serio (critero 2).

        O §6.1 passo 2 nomeia dois limites: o `msgs_ai_mes` e o
        `valor_max_pedido_kz` — hoje `valor_max_pedido_minor` (dicionario
        §3.26). Este e o segundo: um valor que nao cabe no tecto por pedido e
        recusado com `LIMIT_EXCEEDED`, **sem consumir nada**.

        **Sem este teste o parametro `tecto` nao tinha chamador nenhum senao a
        propria camada** — e um caminho que nenhum teste percorre e um caminho
        que ninguem mediu. Apanhado pela revisao adversarial. Quem o passa a
        serio e o `criar_pedido` do **KAM-031**, que e quem tem o valor do
        carrinho.

        **O `msgs_ai_mes` nao se consome aqui, e isso e deliberado.** Ele conta
        **mensagens** e e consumido no envio (o no `send`), nao por invocacao de
        tool: consumi-lo a cada `search_catalog` queimava o balde mensal de um
        tenant numa conversa. E por isso que a camada nao passa `chave` ao
        `hook_de_tool` — o `consume_limit` nao corre — e a verificacao que ela
        faz no passo 2 e a do entitlement e a do tecto por pedido.
        """
        self.semente.execute(
            "UPDATE platform.entitlements SET limites = %s::jsonb "
            " WHERE tenant_id = %s AND modulo = 'vendedor'",
            ('{"valor_max_pedido_minor": 500000}', self.conversa.tenant_id),
        )
        factories.contexto(self.semente, None)
        camada = ToolLayer(self.catalogo(), abrir_ligacao=lambda: self.ligar("app"))

        def invocar(valor: int):
            return asyncio.run(
                camada.invoke(
                    self.contexto(),
                    "criar_pedido",
                    {"cart_id": "c-1"},
                    allowed=["criar_pedido"],
                    confirmation=Confirmation(
                        botao="confirm:c-1",
                        contact_id=self.conversa.contact_id,
                        turn_id="t-1",
                    ),
                    idempotency_key=f"k-{uuid.uuid4().hex}",
                    tecto=("valor_max_pedido_minor", valor),
                )
            )

        cabe = invocar(400_000)
        self.assertTrue(cabe.ok, cabe.error)
        nao_cabe = invocar(900_000)
        self.assertFalse(nao_cabe.ok)
        self.assertEqual(nao_cabe.error.codigo, erros.LIMIT_EXCEEDED)
        self.assertIn("500000", nao_cabe.error.detalhe)
        # E **nao consumiu**: a verificacao do tecto nao escreve.
        self.assertEqual(
            self.consultar(
                "SELECT count(*) FROM platform.usage_ledger WHERE tenant_id = %s",
                (self.conversa.tenant_id,),
            )[0][0],
            0,
        )

    def test_a_get_store_info_le_a_loja_do_contexto(self) -> None:
        """A primeira tool real, contra a `platform.tenants` sob RLS."""
        self.semente.execute(
            "UPDATE platform.tenants SET zona = %s, plus_code = %s WHERE id = %s",
            ("Maianga", "6H5F+2X", self.conversa.tenant_id),
        )
        resultado = self.invocar(
            "get_store_info", {}, confirmation=None, idempotency_key=None
        )
        self.assertTrue(resultado.ok, resultado.error)
        self.assertEqual(resultado.data["zona"], "Maianga")
        self.assertEqual(resultado.data["plus_code"], "6H5F+2X")
        self.assertEqual(resultado.data["fuso_horario"], "Africa/Luanda")
        self.assertEqual(resultado.facts, ())

    def test_uma_loja_apagada_e_recusada_no_passo_2_e_nao_no_6(self) -> None:
        """Uma medicao que corrigiu o que este teste afirmava.

        Escrevi-o a espera de `NOT_FOUND` — a `get_store_info` filtra
        `deleted_at IS NULL` — e a base respondeu `ENTITLEMENT_DENIED`. A razao
        e o `SQL_ENTITLEMENT` do KAM-009: a subconsulta dele sobre
        `platform.tenants` nao ve um tenant apagado, pelo que o passo **2** nega
        antes de o 6 correr.

        Fica assim, e a ordem e que esta certa: um tenant apagado nao tem
        entitlement activo, e o §6.5 manda **nunca** repetir um
        `ENTITLEMENT_DENIED`. O `NOT_FOUND` do executor passa a ser defesa em
        profundidade — inalcancavel pelo pipeline, e medido directamente no
        `test_o_not_found_do_executor_e_defesa_em_profundidade`.
        """
        self.semente.execute(
            "UPDATE platform.tenants SET deleted_at = now() WHERE id = %s",
            (self.conversa.tenant_id,),
        )
        resultado = self.invocar(
            "get_store_info", {}, confirmation=None, idempotency_key=None
        )
        self.assertEqual(resultado.error.codigo, erros.ENTITLEMENT_DENIED)

    def test_o_not_found_do_executor_e_defesa_em_profundidade(self) -> None:
        """O ramo que o pipeline nao alcanca, medido onde ele vive.

        Um ramo inalcancavel pelo caminho normal nao e um ramo a apagar: e a
        segunda linha de defesa se um dia o passo 2 passar a aceitar um tenant
        que a `tenants` nao tem. Mas tem de ser medido onde ele esta, senao a
        cobertura conta-o sem o exercitar.
        """
        from kamba_agr.tls.especificacoes import ErroDeBackend

        apagada = self.criar_conversa()
        self.semente.execute(
            "UPDATE platform.tenants SET deleted_at = now() WHERE id = %s",
            (apagada.tenant_id,),
        )
        pedido = Pedido(
            ctx=self.contexto(apagada),
            args=ArgumentosDeGetStoreInfo(),
            timeout_ms=2_000,
            ligacao=self.ligar("app"),
        )
        with self.assertRaises(ErroDeBackend) as capturado:
            executar(pedido)
        self.assertEqual(capturado.exception.codigo, erros.NOT_FOUND)

    def test_o_set_local_sai_com_o_tenant_do_contexto(self) -> None:
        """Passo 6: «`tenant_id` no cabecalho **e** `SET LOCAL app.tenant_id`».

        Mede-se pelo efeito e nao pelo texto: a consulta da tool corre dentro de
        `tenant_guard.tx`, e sem o contexto certo a RLS da `tenants` devolvia
        zero linhas e a tool dava `NOT_FOUND`. Que ela devolva **esta** loja e a
        prova de que o contexto saiu com este tenant.
        """
        self.semente.execute(
            "UPDATE platform.tenants SET nome = %s WHERE id = %s",
            ("Loja do contexto", self.conversa.tenant_id),
        )
        resultado = self.invocar(
            "get_store_info", {}, confirmation=None, idempotency_key=None
        )
        self.assertEqual(resultado.data["nome"], "Loja do contexto")

    def test_o_servidor_honra_o_statement_timeout(self) -> None:
        """A metade do tecto que **so** a base pode dizer (critero 7).

        O `SET LOCAL statement_timeout` que a `get_store_info` emite nao vale
        nada se o servidor o ignorar, e isso nao se prova com um duplo. Prova-se
        com uma consulta que demora de proposito: `pg_sleep(1)` contra um tecto
        de 50 ms tem de ser **cancelada** pelo servidor, com o SQLSTATE `57014`.

        Nao se usa a consulta da tool para isto: ela e rapida, e um teste que
        dependesse de ela passar de 2 s era um teste que falha quando a maquina
        esta folgada. O que aqui se mede e o mecanismo; que a tool o usa com o
        numero certo mede-se na bateria de unidade
        (`test_o_tecto_sai_para_o_servidor_com_o_numero_da_classe`).
        """
        from kamba_agr.tls.get_store_info import (
            SQLSTATE_CANCELADA,
            VARIAVEL_DE_TECTO,
            _e_cancelamento,
        )

        cursor = self.ligar("app").cursor()
        cursor.execute(f"SET LOCAL {VARIAVEL_DE_TECTO} = 50")
        with self.assertRaises(Exception) as capturado:
            cursor.execute("SELECT pg_sleep(1)")
        self.assertTrue(
            _e_cancelamento(capturado.exception),
            f"esperava o SQLSTATE {SQLSTATE_CANCELADA}: {capturado.exception}",
        )

    def test_as_declaradas_nao_correm(self) -> None:
        """Uma entrada `declarada` esta no catalogo e o `invoke` recusa-a.

        **Nove e nao dez**, e a diferenca e o catalogo de ensaio: ele liga a
        `criar_pedido` (para exercitar o caminho `money` sem o COM) alem da
        `get_store_info`, pelo que das onze sobram nove declaradas. No catalogo
        real sao dez, e isso mede-se na bateria de unidade.
        """
        declaradas = sorted(self.catalogo().declaradas())
        self.assertEqual(len(declaradas), 9)
        for nome in declaradas:
            with self.subTest(tool=nome):
                resultado = self.invocar(nome, {})
                self.assertFalse(resultado.ok)
                self.assertEqual(resultado.error.codigo, erros.TOOL_NOT_ALLOWED)
                self.assertEqual(resultado.data, {})
                self.assertEqual(resultado.facts, ())

    def test_for_context_so_oferece_as_ligadas(self) -> None:
        oferecidas = self.camada.for_context(
            self.contexto(), sorted(self.catalogo().nomes())
        )
        self.assertEqual(
            sorted(t.nome for t in oferecidas), ["criar_pedido", "get_store_info"]
        )


# ----------------------------------------------------------------- cobertura
class TestCobertura(_ComTls):
    def test_cada_invocacao_money_deixa_exactamente_uma_linha(self) -> None:
        """Critero 5: cobertura 100%, e **uma** e nao duas."""
        for indice in range(5):
            self.invocar("criar_pedido", {"cart_id": f"c-{indice}"})
        self.ligacao_app.commit()
        linhas = self.linhas()
        self.assertEqual(len(linhas), 5)
        self.assertEqual({l[0] for l in linhas}, {"criar_pedido"})
        self.assertEqual({l[2] for l in linhas}, {"ok"})

    def test_uma_recusa_tambem_deixa_linha(self) -> None:
        """Uma invocacao recusada e uma invocacao: o critero diz **cada**."""
        casos = (
            ({"cart_id": "c-1"}, {"confirmation": None}, erros.VALIDATION_ERROR),
            ({"cart_id": "c-1"}, {"idempotency_key": None}, erros.VALIDATION_ERROR),
            ({"cart_id": "c-1", "x": 1}, {}, erros.VALIDATION_ERROR),
            ({"cart_id": "c-1"}, {"allowed": ["get_store_info"]},
             erros.TOOL_NOT_ALLOWED),
        )
        for args, troca, esperado in casos:
            with self.subTest(esperado=esperado, troca=sorted(troca)):
                resultado = self.invocar("criar_pedido", args, **troca)
                self.assertEqual(resultado.error.codigo, esperado)
        self.ligacao_app.commit()
        linhas = self.linhas()
        self.assertEqual(len(linhas), len(casos))
        self.assertEqual({l[2] for l in linhas}, {"erro"})
        self.assertEqual(
            {l[3] for l in linhas},
            {erros.VALIDATION_ERROR, erros.TOOL_NOT_ALLOWED},
        )

    def test_uma_tool_fora_do_catalogo_nao_deixa_linha_e_diz_se_porque(self) -> None:
        """Sem `klass` nao ha linha: o `klass` e `NOT NULL`.

        **E a unica excepcao a cobertura**, e esta nomeada na *docstring* do
        `camada.py`: uma tool que o catalogo nao conhece nao e de classe
        `write` nem `money`, porque nao e de classe nenhuma.
        """
        resultado = self.invocar(
            "tool_que_nao_existe", {}, allowed=["tool_que_nao_existe"]
        )
        self.assertEqual(resultado.error.codigo, erros.TOOL_NOT_ALLOWED)
        self.ligacao_app.commit()
        self.assertEqual(self.linhas(), [])


# ---------------------------------------------------------------- privacidade
class TestPrivacidade(_ComTls):
    #: Um telefone de forma angolana, do intervalo ficticio da casa, e um nome.
    #: Se qualquer um deles aparecer na tabela, o critero 5 nao esta cumprido.
    CANARIO_TELEFONE = "999123456789"
    CANARIO_TEXTO = "sapatos-para-o-Joao-CANARIO"

    def test_a_linha_nao_guarda_o_texto_nem_o_telefone_dos_argumentos(self) -> None:
        self.invocar(
            "criar_pedido",
            {"cart_id": self.CANARIO_TELEFONE, "nota": self.CANARIO_TEXTO},
        )
        self.ligacao_app.commit()
        self.assertCanariosAusentes()

    def test_o_varrimento_procura_nos_dados_e_nao_no_nome_das_colunas(self) -> None:
        """A licao do KAM-026: um varrimento que procura no sitio errado da zero.

        Este teste e o **controlo** do de cima: semeia o canario numa coluna de
        texto da propria tabela, pelo caminho legitimo, e confirma que o
        varrimento o **encontra**. Sem ele, um varrimento que procurasse no vazio
        dava zero e o critero passava pela razao errada.

        **O caminho legitimo mudou, e e por isso que este teste vale.** A
        primeira versao semeava-o num **nome de argumento**, e chamava-lhe
        legitimo; a revisao adversarial mostrou que nao era — os nomes vem do
        modelo e podiam levar um telefone —, e a redaccao passou a deixar passar
        so os nomes que o esquema declara. Com isso, **este controlo deixou de
        encontrar o canario**: o teste falhou, que e exactamente o que um
        controlo serve para fazer quando o caminho que ele usa se fecha.

        O caminho que fica e a `idempotency_key`, que e uma coluna que o chamador
        enche por inteiro. Nao e um buraco de privacidade: a chave do §6.3 e um
        `sha256`, e quem a deriva e o KAM-029. E aqui serve de controlo
        precisamente por ser texto do chamador numa coluna de texto.
        """
        self.invocar(
            "criar_pedido", {"cart_id": "c-1"}, idempotency_key=self.CANARIO_TEXTO
        )
        self.ligacao_app.commit()
        self.assertEqual(self._ocorrencias(self.CANARIO_TEXTO), 1)

    def test_um_nome_de_argumento_inventado_nao_chega_a_tabela(self) -> None:
        """O achado da revisao, medido contra a base.

        As chaves de `args` vem do modelo de linguagem. Um nome com um telefone
        la dentro chegava a coluna `args_redacted` em claro — e chegava pelo
        caminho `VALIDATION_ERROR`, que e onde um argumento inventado cai.
        """
        canario = f"contacto {self.CANARIO_TELEFONE}"
        resultado = self.invocar("criar_pedido", {"cart_id": "c-1", canario: 1})
        self.assertEqual(resultado.error.codigo, erros.VALIDATION_ERROR)
        self.ligacao_app.commit()
        self.assertEqual(self._ocorrencias(canario), 0)
        self.assertEqual(self._ocorrencias(self.CANARIO_TELEFONE), 0)
        # A linha existe — a cobertura do critero 5 nao se perde — e diz que
        # houve argumentos a mais, sem dizer quais.
        linhas = self.linhas()
        self.assertEqual(len(linhas), 1)
        self.assertIn("nao_declarados", linhas[0][5])

    def test_nenhuma_coluna_da_tabela_tem_nome_de_dado_pessoal(self) -> None:
        """Os sete nomes que o *lint* de PII do `docs/tecnica/08` §7.3 proibe."""
        proibidos = ("telefone", "nome", "morada", "texto", "email", "msisdn", "bsuid")
        colunas = {
            c for (c,) in self.consultar(
                "SELECT column_name FROM information_schema.columns "
                " WHERE table_schema = 'platform' AND table_name = 'tool_audit'"
            )
        }
        for coluna in sorted(colunas):
            for proibido in proibidos:
                with self.subTest(coluna=coluna, proibido=proibido):
                    self.assertNotIn(proibido, coluna)

    def _ocorrencias(self, canario: str) -> int:
        """Quantas linhas de `tool_audit` tem o canario em **alguma** coluna.

        Serializa-se a linha inteira (`to_jsonb`) e procura-se no texto: uma
        lista de colunas a mao esquecia a coluna que viesse a seguir, e e isso
        que um varrimento de privacidade nunca pode fazer.
        """
        return self.consultar(
            "SELECT count(*) FROM platform.tool_audit "
            " WHERE to_jsonb(tool_audit)::text LIKE %s",
            (f"%{canario}%",),
        )[0][0]

    def assertCanariosAusentes(self) -> None:
        for canario in (self.CANARIO_TELEFONE, self.CANARIO_TEXTO):
            with self.subTest(canario=canario):
                self.assertEqual(self._ocorrencias(canario), 0)


# ----------------------------------------------------------------- isolamento
class TestIsolamento(_ComTls):
    def setUp(self) -> None:
        super().setUp()
        self.b = self.criar_conversa()
        self.canario = f"CANARIO-B-{uuid.uuid4().hex}"
        self.semente.execute(
            "UPDATE platform.tenants SET nome = %s, zona = %s, plus_code = %s "
            " WHERE id = %s",
            (self.canario, self.canario, self.canario, self.b.tenant_id),
        )
        self.dar_entitlement(self.b)

    def test_x02_cada_tool_com_estado_de_a_e_referencia_a_b_da_zero_canarios(
        self,
    ) -> None:
        """X-02 (`docs/tecnica/08` §3.7), sobre as tools do catalogo.

        Para cada tool, invoca-se com o estado de **A** e argumentos que referem
        entidades de **B** — o `tenant_id`, o `contact_id` e o `conversation_id`
        de B. O oraculo e o canario de B, que esta **semeado nas colunas da
        `tenants` de B** e nunca e passado como argumento: nao pode aparecer na
        resposta, no erro, nem na linha de auditoria.

        **O canario nao vai nos argumentos de proposito, e isso e uma correccao
        a primeira versao deste teste.** Passa-lo como argumento media a coisa
        errada: uma tool que **devolva o que recebeu** nao vazou nada — o valor
        era de quem chamou —, e o teste falhava sobre um eco. O que o X-02
        pergunta e se uma tool **le** dados de outro tenant, e a unica forma de
        o distinguir de um eco e o canario so existir do lado de B.

        **E os argumentos sao os de cada tool, e nao os mesmos para todas.** A
        segunda versao deste teste passava `cart_id`/`nota` a todas, e com isso a
        `get_store_info` — cujo modelo nao tem campos — recusava no **passo 3**;
        com as declaradas a recusar no passo 1, nenhuma invocacao chegava ao
        backend e o `assertNotIn` nao podia falhar. Um critero satisfeito pela
        razao errada, que e precisamente o que este ticket avisa. Hoje ha
        controlo positivo: as tools **ligadas** tem de chegar ao passo 6.
        """
        catalogo = self.catalogo()
        referencias_de_b = [
            self.b.tenant_id, self.b.contact_id, self.b.conversation_id,
        ]
        chegaram_ao_backend: set[str] = set()
        for nome in sorted(catalogo.nomes()):
            especificacao = catalogo[nome]
            for referencia in referencias_de_b:
                with self.subTest(tool=nome, referencia=referencia[:12]):
                    resultado = self.invocar(
                        nome,
                        self.argumentos_para(especificacao, referencia),
                        allowed=sorted(catalogo.nomes()),
                    )
                    texto = f"{resultado.data}{resultado.error}"
                    self.assertNotIn(self.canario, texto)
                    if especificacao.ligada:
                        # **O controlo positivo do X-02.** Sem isto o teste
                        # media recusas: a primeira versao passava `cart_id` e
                        # `nota` a **todas** as tools, e a `get_store_info` — a
                        # unica ligada do catalogo real — recusava no passo 3
                        # por ter um modelo sem campos. Com as dez declaradas a
                        # recusar no passo 1, **nenhuma** invocacao chegava ao
                        # backend e o oraculo nao podia falhar.
                        self.assertNotEqual(
                            resultado.error.codigo if resultado.error else None,
                            erros.VALIDATION_ERROR,
                            f"a `{nome}` nem chegou ao passo 4: o laco deu-lhe "
                            "argumentos que o esquema dela nao aceita, e o X-02 "
                            "passava a medir o passo 3",
                        )
                        chegaram_ao_backend.add(nome)
        # E a prova de que o oraculo **podia** falhar: as ligadas do catalogo de
        # ensaio correram o passo 6 com o estado de A.
        self.assertEqual(
            chegaram_ao_backend, set(catalogo.ligadas()),
            "alguma tool ligada nao chegou ao backend; o X-02 nao mediu nada",
        )
        self.ligacao_app.commit()
        self.assertEqual(
            self.consultar(
                "SELECT count(*) FROM platform.tool_audit "
                " WHERE to_jsonb(tool_audit)::text LIKE %s",
                (f"%{self.canario}%",),
            )[0][0],
            0,
        )

    def argumentos_para(self, especificacao, referencia: str) -> dict:
        """Argumentos que **aquela** tool aceita, com a referencia de B onde cabe.

        Uma entrada `declarada` nao tem modelo: nao ha campos onde pôr a
        referencia, e o passo 1 recusa-a antes de chegar ao passo 3 — o que a
        referencia fosse era indiferente. Uma `ligada` leva a referencia em
        **todos** os campos de texto que declara, que e o que «argumentos que
        referem entidades de B» quer dizer.
        """
        if not especificacao.ligada:
            return {}
        return {campo: referencia for campo in especificacao.parametros_visiveis()}

    def test_a_get_store_info_com_o_contexto_de_a_nunca_devolve_a_loja_de_b(
        self,
    ) -> None:
        resultado = self.invocar(
            "get_store_info", {}, confirmation=None, idempotency_key=None
        )
        self.assertTrue(resultado.ok, resultado.error)
        self.assertNotIn(self.canario, str(resultado.data))

    def test_a_linha_de_auditoria_fica_no_tenant_do_contexto(self) -> None:
        """O `WITH CHECK` da politica `tenant_iso`, medido pelo efeito."""
        self.invocar("criar_pedido", {"cart_id": "c-1"})
        self.ligacao_app.commit()
        self.assertEqual(len(self.linhas(self.conversa.tenant_id)), 1)
        self.assertEqual(self.linhas(self.b.tenant_id), [])

    def test_x04_uma_sessao_sem_contexto_le_zero_linhas(self) -> None:
        """X-04: RLS *fail-closed*. Le-se com o papel que tem `SELECT`."""
        self.invocar("criar_pedido", {"cart_id": "c-1"})
        self.ligacao_app.commit()
        cursor = self.ligar("audit").cursor()
        cursor.execute("SELECT count(*) FROM platform.tool_audit")
        self.assertEqual(cursor.fetchone()[0], 0)

    def test_escrever_no_nome_de_outro_tenant_e_recusado(self) -> None:
        """A politica nao e redundante com o *append-only*.

        O unico tipo de escrita que esta tabela aceita e um `INSERT`, e e o
        `WITH CHECK` que impede que ele leve o `tenant_id` de outro.
        """
        conexao = self.ligar("app")
        cursor = conexao.cursor()
        cursor.execute(
            "SELECT set_config('app.tenant_id', %s, true)", (self.conversa.tenant_id,)
        )
        self.assertErroSql(
            PRIVILEGIO_INSUFICIENTE,
            cursor,
            "INSERT INTO platform.tool_audit "
            "(tenant_id, tool, klass, args_hash, status) "
            "VALUES (%s, 'criar_pedido', 'money', %s, 'ok')",
            (self.b.tenant_id, b"\x00" * 32),
        )


# ----------------------------------------------------------------- restricoes
class TestRestricoes(_ComTls):
    def inserir(self, cursor, **troca):
        valores = {
            "tenant_id": self.conversa.tenant_id,
            "tool": "criar_pedido",
            "klass": "money",
            "args_hash": b"\x00" * 32,
            "status": "ok",
            "error_code": None,
            "result_hash": None,
            "fact_ids": None,
            "latency_ms": 1,
            "vertical": "vendedor",
        }
        valores.update(troca)
        nomes = list(valores)
        cursor.execute(
            f"INSERT INTO platform.tool_audit ({', '.join(nomes)}) "
            f"VALUES ({', '.join(['%s'] * len(nomes))})",
            tuple(valores[nome] for nome in nomes),
        )

    def cursor_app(self):
        conexao = self.ligar("app")
        cursor = conexao.cursor()
        cursor.execute(
            "SELECT set_config('app.tenant_id', %s, true)", (self.conversa.tenant_id,)
        )
        return cursor

    def test_a_forma_valida_passa(self) -> None:
        self.inserir(self.cursor_app())

    def test_um_klass_fora_das_tres_e_recusado(self) -> None:
        self.assertRecusa(klass="admin")

    def test_um_status_fora_dos_dois_e_recusado(self) -> None:
        self.assertRecusa(status="pendente")

    def test_um_ok_com_codigo_de_erro_e_recusado(self) -> None:
        self.assertRecusa(status="ok", error_code=erros.NOT_FOUND)

    def test_um_erro_sem_codigo_e_recusado(self) -> None:
        self.assertRecusa(status="erro", error_code=None)

    def test_um_codigo_fora_dos_dez_e_recusado(self) -> None:
        self.assertRecusa(status="erro", error_code="PAGAMENTO_RECUSADO")

    def test_os_dez_codigos_do_documento_passam(self) -> None:
        cursor = self.cursor_app()
        for codigo in erros.CODIGOS:
            with self.subTest(codigo=codigo):
                self.inserir(cursor, status="erro", error_code=codigo)

    def test_um_result_hash_numa_linha_de_erro_e_recusado(self) -> None:
        self.assertRecusa(
            status="erro", error_code=erros.NOT_FOUND, result_hash=b"\x00" * 32
        )

    def test_um_hash_que_nao_tem_32_octetos_e_recusado(self) -> None:
        self.assertRecusa(args_hash=b"\x00" * 31)
        self.assertRecusa(result_hash=b"\x00" * 33)

    def test_uma_latencia_negativa_e_recusada(self) -> None:
        self.assertRecusa(latency_ms=-1)

    def test_um_nulo_dentro_dos_fact_ids_e_recusado(self) -> None:
        self.assertRecusa(fact_ids=["f-1", None])

    def test_um_nome_de_tool_fora_da_gramatica_e_recusado(self) -> None:
        for nome in ("CriarPedido", "criar-pedido", "1tool", ""):
            with self.subTest(nome=nome):
                self.assertRecusa(tool=nome)

    def test_um_identificador_de_quatro_mil_caracteres_e_recusado(self) -> None:
        """O tecto nao e contra um nome comprido: e contra conteudo na coluna."""
        self.assertRecusa(turn_id="x" * 4000)

    def test_o_ts_nao_e_de_quem_insere(self) -> None:
        """Nao esta no `GRANT` por coluna: o instante da linha nao e do chamador."""
        self.assertErroSql(
            PRIVILEGIO_INSUFICIENTE,
            self.cursor_app(),
            "INSERT INTO platform.tool_audit "
            "(tenant_id, tool, klass, args_hash, status, ts) "
            "VALUES (%s, 'criar_pedido', 'money', %s, 'ok', %s)",
            (self.conversa.tenant_id, b"\x00" * 32, "2000-01-01"),
        )

    def test_o_id_nao_se_escreve_nem_com_privilegio(self) -> None:
        """Recusa de outra natureza, e por isso teste proprio.

        O `ts` falha por **privilegio** (`42501`): nao esta no `GRANT` por
        coluna. O `id` falha por ser `GENERATED ALWAYS` (`428C9`), que e uma
        recusa do proprio esquema e vale para todos os papeis, dono incluido.
        Juntar os dois num `subTest` dizia que a mesma regra os protege.
        """
        self.assertErroSql(
            "428C9",
            self.cursor_app(),
            "INSERT INTO platform.tool_audit "
            "(tenant_id, tool, klass, args_hash, status, id) "
            "VALUES (%s, 'criar_pedido', 'money', %s, 'ok', %s)",
            (self.conversa.tenant_id, b"\x00" * 32, 1),
        )

    def assertRecusa(self, **troca) -> None:
        cursor = self.cursor_app()
        cursor.execute("SAVEPOINT antes")
        try:
            with self.assertRaises(Exception):
                self.inserir(cursor, **troca)
        finally:
            cursor.execute("ROLLBACK TO SAVEPOINT antes")


if __name__ == "__main__":
    unittest.main()
