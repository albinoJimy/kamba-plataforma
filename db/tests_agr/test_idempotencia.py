"""A idempotencia por `cart_id` contra um PostgreSQL real (KAM-029).

    TestCinquentaConcorrentes  critero 1: 50 em paralelo, **1** chamada ao backend
    TestFalhaAMeio             critero 4: falha entre o backend e o registo
    TestRegistoEmCurso         critero 5: espera com tecto, e nao executa
    TestConteudoDiferente      critero 3 contra a base, com o `args_hash` a serio
    TestRetencao               critero 7: a varredura, com relogio simulado
    TestPrivacidadeDaChave     critero 6: a `key` recusa um telefone **na base**
    TestIsolamento             a chave de A nunca devolve o resultado de B
    TestRestricoes             os `CHECK` da revisao `0022`, um a um

O que **so** aqui se prova, e nao se prova com uma base falsa:

| Propriedade | Porque precisa da base |
|---|---|
| os 50 concorrentes | o que serializa e o `INSERT … ON CONFLICT DO NOTHING` do servidor. Um dicionario em memoria serializa de graca, pelo GIL, e o teste passava sem o `ON CONFLICT` |
| a retoma de uma `falhada` | o que a torna atomica e o `WHERE estado = 'falhada'` **dentro** do `UPDATE`. Em memoria, dois leitores retomavam os dois e nada o mostrava |
| a forma da `key` | o `CHECK (key ~ '^[0-9a-f]{64}$')` e o criterio 6 imposto pelo servidor, e nao por nos lhe passarmos a coisa certa |
| o `UPDATE` por coluna | o `GRANT` e por coluna; um `UPDATE` do `args_hash` da `42501`, e nada disso se ve num duplo |
| a RLS | a politica e da base. O `WITH CHECK` e o que impede uma reserva no nome de outro tenant |
| os dois sentidos do `CHECK` do resultado | uma `concluida` sem `result` e um `result` numa `falhada` sao recusados pelo servidor |

**O oraculo de todos eles e o contador de chamadas ao backend, e nao o que o
`invoke` devolve.** Um teste de idempotencia que meca o resultado passa com a
idempotencia apagada: as 50 invocacoes devolvem o mesmo `ok=True` de qualquer
maneira, porque o executor de ensaio e determinista. Foi o defeito do X-02 do
KAM-028 — media onze **recusas** em vez de onze tools, com um oraculo que nao
podia falhar — e e a pergunta que cada bateria daqui tem de sobreviver: o que a
faria passar com o codigo apagado?

Por isso o executor de ensaio **e idempotente pela chave** e devolve um
`order_id` por chave distinta: assim o contador separa «quantas vezes o backend
correu» de «quantas encomendas existem», que sao as duas metades do criterio 4 e
nao sao a mesma coisa.
"""

from __future__ import annotations

import asyncio
import datetime as _dt
import threading
import unittest
import uuid

from pydantic import BaseModel, ConfigDict

import ligacao

from tests import factories
from tests.base import (
    PRIVILEGIO_INSUFICIENTE,
    TABELAS,
    TABELAS_ATE_0021,
    VIOLACAO_DE_CHECK,
    alembic_ok,
)
from tests_agr.base import ComAgr

from kamba_agr.tls import auditoria, idempotency  # noqa: E402
from kamba_agr.tls.camada import ToolLayer  # noqa: E402
from kamba_agr.tls.catalogo import ESPECIFICACOES_DO_PILOTO  # noqa: E402
from kamba_agr.tls.contexto import Confirmation, ToolContext  # noqa: E402
from kamba_agr.tls.especificacoes import (  # noqa: E402
    Catalogo,
    EspecificacaoDeTool,
    Resposta,
)

#: O intervalo ficticio da casa (`999` + nove algarismos, sem `+`). A nota do
#: KAM-025 manda usar este, e o *gate* 7 recusou cinco ficheiros do KAM-028 por
#: terem um movel angolano de forma real em prosa de exemplo.
TELEFONE = "999123456789"


class ArgumentosDoEnsaio(BaseModel):
    model_config = ConfigDict(extra="forbid")
    cart_id: str
    nota: str = ""


class _Backend:
    """Um backend `money` que conta e **e idempotente pela chave**.

    A idempotencia dele nao e conveniencia: e a premissa que o criterio 4
    escreve por extenso — «a repeticao nao duplica o efeito (o backend e
    idempotente pela chave)». Sem ela, o contador media a idempotencia da camada
    e a frase ficava sem nada a sustenta-la, que e o defeito mais caro desta
    linha.

    O `threading.Lock` existe porque os 50 concorrentes correm em *threads* a
    serio (`asyncio.to_thread`): sem ele, o `setdefault` e o `append` podiam
    entrelacar-se e o contador media o GIL.
    """

    def __init__(self, atraso: float = 0.0) -> None:
        self.chamadas: list[str | None] = []
        self.encomendas: dict[str | None, str] = {}
        self._atraso = atraso
        self._trinco = threading.Lock()

    def __call__(self, pedido):
        if self._atraso:
            import time

            time.sleep(self._atraso)
        with self._trinco:
            self.chamadas.append(pedido.chave)
            self.encomendas.setdefault(
                pedido.chave, f"ord-{len(self.encomendas) + 1}"
            )
            order_id = self.encomendas[pedido.chave]
        return Resposta(data={"order_id": order_id})


class _ComIdempotencia(ComAgr):
    """Uma conversa, um entitlement activo, e a camada com o backend que conta."""

    #: Quantas ligacoes a camada abre. **Uma por invocacao concorrente**, e nao
    #: e afinacao: o `tenant_guard` recusa duas transaccoes na mesma ligacao
    #: (`LigacaoEmUso`), pelo que 50 invocacoes sobre uma ligacao so estouravam
    #: antes de chegarem ao `ON CONFLICT`. Foi o que a `ANALISE-30` deixou
    #: escrito para quem viesse medir este criterio.
    LIGACOES = 4

    def especificacao(self, executor) -> EspecificacaoDeTool:
        return EspecificacaoDeTool(
            nome="criar_pedido",
            klass="money",
            backend="com",
            modelo=ArgumentosDoEnsaio,
            executor=executor,
            campo_de_confirmacao="cart_id",
        )

    def catalogo(self, executor) -> Catalogo:
        especificacao = self.especificacao(executor)
        return Catalogo(
            tuple(e for e in ESPECIFICACOES_DO_PILOTO if e.nome != especificacao.nome)
            + (especificacao,)
        )

    def setUp(self) -> None:
        super().setUp()
        self.conversa = self.criar_conversa()
        self.dar_entitlement(self.conversa)
        self.backend = _Backend()
        self._tomadas: list = []
        self.addCleanup(self._fechar_tomadas)
        self.addCleanup(self._apagar_reservas)

    def tomada(self):
        """Uma ligacao `app` **fora** do `_conexoes` do `ComBase`.

        O `tearDown` daquele faz `rollback()` e depois `close()`, e um
        `rollback` numa ligacao ja fechada levanta — o que aborta o laco e deixa
        as outras ligacoes abertas. A camada **fecha** a tomada quando o pipeline
        levanta (e esta certa: pode estar quebrada), pelo que uma tomada dela
        naquela lista rebentava o `tearDown` da bateria da falha injectada, que
        e exactamente a que percorre esse caminho.

        Fecham-se aqui, e com tolerancia a ja estarem fechadas.
        """
        conexao = ligacao.ligar("app")
        self._tomadas.append(conexao)
        return conexao

    def _fechar_tomadas(self) -> None:
        for conexao in self._tomadas:
            try:
                conexao.close()
            except Exception:  # noqa: BLE001 — a camada pode te-la fechado
                pass

    def montar(self, backend=None, *, ligacoes: int | None = None, **troca) -> ToolLayer:
        """A camada, com uma ligacao **nova** por tomada.

        Cada tomada tem a sua ligacao porque o `tenant_guard` recusa duas
        transaccoes na mesma — ver a nota da `LIGACOES`. As ligacoes fecham-se
        no `addCleanup` do `ligar`, que o `ComBase` ja faz.
        """
        self.backend = backend if backend is not None else self.backend
        return ToolLayer(
            self.catalogo(self.backend),
            abrir_ligacao=self.tomada,
            ligacoes=ligacoes if ligacoes is not None else self.LIGACOES,
            **troca,
        )

    def dar_entitlement(self, conversa, *, ativo: bool = True) -> None:
        """Um entitlement activo **e o tenant em `ativo`** — ver o KAM-028.

        Sem o `estado = 'ativo'`, o `SQL_ENTITLEMENT` do KAM-009 nega e **todas**
        as invocacoes davam `ENTITLEMENT_DENIED`: as baterias passavam com um
        passo 2 que nunca chegava ao passo 5, que e o «satisfeito pela razao
        errada» do lado contrario.
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

    def _apagar_reservas(self) -> None:
        self.semente.execute("DELETE FROM platform.tool_idempotency")

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

    def invocar(self, camada, args: dict, *, ctx=None, **troca):
        return asyncio.run(self._invocar(camada, args, ctx=ctx, **troca))

    async def _invocar(self, camada, args: dict, *, ctx=None, **troca):
        ctx = ctx or self.contexto()
        padrao: dict = {
            "allowed": sorted(self.catalogo(self.backend).nomes()),
            "confirmation": Confirmation(
                botao=f"confirm:{args.get('cart_id', '')}",
                contact_id=ctx.contact_id,
                turn_id=ctx.turn_id,
            ),
            "idempotency_key": f"k-{uuid.uuid4().hex}",
        }
        padrao.update(troca)
        return await camada.invoke(ctx, "criar_pedido", args, **padrao)

    def chave_de(self, cart_id: str, ctx=None) -> str:
        return idempotency.derivar(ctx or self.contexto(), "criar_pedido", cart_id)

    def impressao_de(self, cart_id: str, **extra) -> bytes:
        """O `args_hash` que a camada vai calcular, pelo **modelo validado**.

        Nao e `impressao({"cart_id": …})`: desde o achado 4 da revisao
        adversarial o hash e de `inv.args.model_dump()` e nao do `args_crus`, o
        que faz as omissoes do Pydantic entrarem (`nota=""`). Semear a mao com o
        dicionario cru dava `INTENT_REUSED_WITH_DIFFERENT_CONTENT` e a bateria
        media o criterio 3 enquanto dizia medir o 5 — que foi o que aconteceu.

        Deriva-se do mesmo modelo que a camada usa, e por isso nao se pode
        desfasar dele.
        """
        return auditoria.impressao(
            ArgumentosDoEnsaio(cart_id=cart_id, **extra).model_dump()
        )

    def cursor_de_app(self, tenant: str | None = None):
        """Um cursor do papel da aplicacao, com o `app.tenant_id` definido.

        A RLS desta tabela e `FORCE`, pelo que sem contexto **nenhuma** linha se
        ve nem se escreve — e um teste de privilegio sem contexto falhava por
        RLS e dizia que o privilegio nao existia, que e a confusao que o KAM-026
        pagou. O `assertErroSql` recebe cursores, e este e o cursor certo.
        """
        cursor = self.ligar("app").cursor()
        cursor.execute(
            "SELECT set_config('app.tenant_id', %s, true)",
            (tenant or self.conversa.tenant_id,),
        )
        cursor.fetchone()
        return cursor

    def reservas(self) -> list[tuple]:
        return self.consultar(
            "SELECT key, tenant_id::text, tool, estado, result::text "
            "  FROM platform.tool_idempotency ORDER BY key"
        )


class TestCinquentaConcorrentes(_ComIdempotencia):
    """O criterio 1, e e o que mede dinheiro: **1** chamada ao backend."""

    LIGACOES = 12

    def test_cinquenta_do_mesmo_cart_id_chamam_o_backend_uma_vez(self) -> None:
        """50 invocacoes concorrentes, 1 chamada, 49 com `idempotent_replay`.

        O `atraso` no backend nao e decoracao: sem ele a primeira invocacao
        fechava a reserva antes de as outras a lerem, e o teste media uma serie
        disfarcada de paralelo. Com 50 ms, as restantes **encontram** a linha
        `em_curso` e passam pelo caminho de espera, que e o que o criterio
        descreve.
        """
        camada = self.montar(_Backend(atraso=0.05))

        async def correr():
            return await asyncio.gather(
                *(self._invocar(camada, {"cart_id": "c-50"}) for _ in range(50))
            )

        resultados = asyncio.run(correr())
        self.addCleanup(lambda: asyncio.run(camada.fechar()))

        self.assertEqual(len(resultados), 50)
        self.assertEqual(
            len(self.backend.chamadas),
            1,
            f"o backend correu {len(self.backend.chamadas)} vezes, nao 1",
        )
        self.assertEqual(len(self.backend.encomendas), 1, "mais de uma encomenda")
        # Todas devolvem o mesmo resultado...
        self.assertEqual({r.ok for r in resultados}, {True})
        self.assertEqual({tuple(sorted(r.data.items())) for r in resultados}, {
            (("order_id", "ord-1"),)
        })
        # ... e exactamente 49 dizem que foram repeticao.
        self.assertEqual(sum(1 for r in resultados if r.idempotent_replay), 49)
        # E ha **uma** linha de reserva, fechada com o resultado.
        reservas = self.reservas()
        self.assertEqual(len(reservas), 1)
        self.assertEqual(reservas[0][3], "concluida")
        self.assertIn("ord-1", reservas[0][4])

    def test_cinquenta_cart_ids_diferentes_chamam_cinquenta_vezes(self) -> None:
        """O controlo: **a camada nao e um trinco que engole tudo**.

        Sem esta bateria, a de cima passava com uma idempotencia que
        desduplicasse por tenant, por contacto, ou por nada — bastava devolver
        sempre o primeiro resultado. E a pergunta «o que a faria passar com o
        codigo apagado?» aplicada ao criterio 1.
        """
        camada = self.montar(_Backend(atraso=0.01))

        async def correr():
            return await asyncio.gather(
                *(self._invocar(camada, {"cart_id": f"c-{i}"}) for i in range(50))
            )

        resultados = asyncio.run(correr())
        self.addCleanup(lambda: asyncio.run(camada.fechar()))

        self.assertEqual(len(self.backend.chamadas), 50)
        self.assertEqual(len(self.backend.encomendas), 50)
        self.assertEqual(sum(1 for r in resultados if r.idempotent_replay), 0)
        self.assertEqual(len(self.reservas()), 50)


class TestFalhaAMeio(_ComIdempotencia):
    """O criterio 4: falha **depois** do backend e **antes** de o resultado ser
    guardado.

    E a janela que a `ANALISE-30` (achado 12) deixou aberta e nomeou este ticket
    para fechar: o passo 7 levanta por desenho quando nao consegue escrever, o
    turno falha, o *job* volta a fila, e sem isto a repeticao corria o efeito
    outra vez.

    A falha injecta-se onde ela acontece de verdade — na escrita da linha de
    auditoria — e nao num sitio escolhido para o teste passar.
    """

    def test_a_repeticao_nao_duplica_o_efeito_e_fecha_o_registo(self) -> None:
        camada = self.montar(_Backend())
        self.addCleanup(lambda: asyncio.run(camada.fechar()))
        chave = self.chave_de("c-falha")

        original = auditoria.escrever
        falhas = {"quantas": 0}

        def escrever_que_falha(ligacao, linha):
            falhas["quantas"] += 1
            raise auditoria.AuditoriaIndisponivelError("falha injectada")

        auditoria.escrever = escrever_que_falha
        try:
            with self.assertRaises(auditoria.AuditoriaIndisponivelError):
                self.invocar(camada, {"cart_id": "c-falha"})
        finally:
            auditoria.escrever = original

        self.assertEqual(falhas["quantas"], 1)
        # O backend correu **e** o efeito existe; a linha fechou como `falhada`,
        # que e o estado que a retoma procura. Sem resultado: o `CHECK` da
        # revisao `0022` nao o deixaria la.
        self.assertEqual(len(self.backend.chamadas), 1)
        reservas = self.reservas()
        self.assertEqual([(r[0], r[3], r[4]) for r in reservas], [(chave, "falhada", None)])

        # A repeticao: retoma, volta a chamar o backend, e **nao duplica** —
        # porque o backend e idempotente pela chave, que e o que o criterio diz.
        resultado = self.invocar(camada, {"cart_id": "c-falha"})

        self.assertTrue(resultado.ok)
        self.assertEqual(len(self.backend.chamadas), 2, "a retoma nao reexecutou")
        self.assertEqual(
            len(self.backend.encomendas), 1, "o efeito duplicou: duas encomendas"
        )
        self.assertEqual(resultado.data, {"order_id": "ord-1"})
        reservas = self.reservas()
        self.assertEqual(len(reservas), 1)
        self.assertEqual(reservas[0][3], "concluida", "o registo nao fechou")
        self.assertIn("ord-1", reservas[0][4])

    def test_a_chave_chega_ao_backend(self) -> None:
        """A premissa do criterio 4, medida e nao suposta.

        «O backend e idempotente pela chave» exige que ele a **veja**. O `Pedido`
        do KAM-028 nao a levava, e foi este ticket que lha deu — esta bateria e
        o que impede alguem de a tirar outra vez.
        """
        camada = self.montar(_Backend())
        self.addCleanup(lambda: asyncio.run(camada.fechar()))
        self.invocar(camada, {"cart_id": "c-chave"})
        self.assertEqual(self.backend.chamadas, [self.chave_de("c-chave")])


class TestRegistoEmCurso(_ComIdempotencia):
    """O criterio 5: uma reserva `em_curso` de outro nao bloqueia para sempre."""

    def test_em_curso_espera_ate_tres_segundos_e_nao_executa(self) -> None:
        """Espera, desiste com `UPSTREAM_TIMEOUT`, e **nao chama o backend**.

        O relogio e o `dormir` sao dobragens para a espera nao custar 3 s de
        bateria — o que se mede e **quanto o relogio andou**, nao quanto a
        maquina demorou. A linha `em_curso` e semeada com `created_at` de ha dez
        minutos: e o «ha mais de 2 s» do criterio, com folga que nenhum relogio
        desacertado explica.
        """
        agora = [0.0]

        def dormir(segundos):
            agora[0] += segundos

        camada = self.montar(
            _Backend(), relogio=lambda: agora[0], dormir=dormir
        )
        self.addCleanup(lambda: asyncio.run(camada.fechar()))
        chave = self.chave_de("c-curso")
        self.semente.execute(
            "INSERT INTO platform.tool_idempotency "
            "(key, tenant_id, tool, args_hash, created_at) "
            "VALUES (%s, %s::uuid, 'criar_pedido', %s, now() - interval '10 seconds')",
            (chave, self.conversa.tenant_id, self.impressao_de("c-curso")),
        )

        resultado = self.invocar(camada, {"cart_id": "c-curso"})

        self.assertFalse(resultado.ok)
        self.assertEqual(resultado.error.codigo, "UPSTREAM_TIMEOUT")
        self.assertEqual(self.backend.chamadas, [], "esperou e executou na mesma")
        self.assertGreaterEqual(agora[0], 3.0, "desistiu antes dos 3 s do §6.3")
        self.assertLess(agora[0], 3.2, "esperou para alem do tecto")
        # A linha de outro nao se toca: continua `em_curso`.
        self.assertEqual(self.reservas()[0][3], "em_curso")

    def test_em_curso_que_fecha_entretanto_devolve_o_guardado(self) -> None:
        """O outro lado do criterio 5: quem espera e **servido** se o dono fechar.

        Sem esta bateria, a de cima passava com uma espera que nunca relesse a
        linha — e `UPSTREAM_TIMEOUT` em todos os casos e pior do que esperar.
        """
        agora = [0.0]
        chave = self.chave_de("c-fecha")
        args_hash = self.impressao_de("c-fecha")
        self.semente.execute(
            "INSERT INTO platform.tool_idempotency (key, tenant_id, tool, args_hash) "
            "VALUES (%s, %s::uuid, 'criar_pedido', %s)",
            (chave, self.conversa.tenant_id, args_hash),
        )

        def dormir(segundos):
            agora[0] += segundos
            # O dono fecha a reserva a meio da nossa espera.
            if agora[0] >= 0.1:
                self.semente.execute(
                    "UPDATE platform.tool_idempotency "
                    "SET estado = 'concluida', result = %s::jsonb WHERE key = %s",
                    ('{"order_id": "do-dono"}', chave),
                )

        camada = self.montar(_Backend(), relogio=lambda: agora[0], dormir=dormir)
        self.addCleanup(lambda: asyncio.run(camada.fechar()))

        resultado = self.invocar(camada, {"cart_id": "c-fecha"})

        self.assertTrue(resultado.ok)
        self.assertTrue(resultado.idempotent_replay)
        self.assertEqual(resultado.data, {"order_id": "do-dono"})
        self.assertEqual(self.backend.chamadas, [])
        self.assertLess(agora[0], 3.0, "esperou o tecto inteiro tendo resposta")


class TestRetomaPorIdade(_ComIdempotencia):
    """A linha `em_curso` abandonada retoma-se, e e o que fecha o caminho que
    deixava um `cart_id` envenenado com a encomenda ja feita.

    Achado 2 da revisao adversarial (`ANALISE-31`), e nao era o `SIGKILL`
    exotico: e o caminho que o `except` do `_correr` existe para tratar — o
    backend corre, a ligacao cai, o `fechar` levanta e e engolido ali. A linha
    ficava `em_curso`, a varredura recusa apagar `em_curso` por idade (e bem:
    pode ser uma invocacao a correr), e nada mais lhe chegava.

    O `docs/tecnica/03` §6.3 ponto 4 ja desenhava isto para o COM («intencoes
    `em_curso` > 2 min sao retomadas ou marcadas `falhada`»); a TLS nao o tinha.
    """

    def _semear_em_curso(self, cart_id: str, intervalo: str) -> str:
        chave = self.chave_de(cart_id)
        self.semente.execute(
            "INSERT INTO platform.tool_idempotency "
            "(key, tenant_id, tool, args_hash, created_at) "
            f"VALUES (%s, %s::uuid, 'criar_pedido', %s, now() - interval '{intervalo}')",
            (chave, self.conversa.tenant_id, self.impressao_de(cart_id)),
        )
        return chave

    def test_uma_em_curso_velha_retoma_se_e_corre_o_backend(self) -> None:
        camada = self.montar(_Backend())
        self.addCleanup(lambda: asyncio.run(camada.fechar()))
        chave = self._semear_em_curso("c-velha", "5 minutes")

        resultado = self.invocar(camada, {"cart_id": "c-velha"})

        self.assertTrue(resultado.ok, "nao retomou uma linha abandonada")
        self.assertEqual(len(self.backend.chamadas), 1)
        reservas = self.reservas()
        self.assertEqual(len(reservas), 1)
        self.assertEqual(reservas[0][3], "concluida")

    def test_uma_em_curso_nova_nao_se_retoma_e_estoura_o_tecto(self) -> None:
        """O par da de cima: a **unica** diferenca e a idade, e o desfecho e o
        oposto.

        Sem esta, a de cima passava com uma retoma que ignorasse a idade — e
        retomar por cima de um dono **vivo** e exactamente o que duplica o
        efeito, que e o oposto do que o ticket faz.
        """
        agora = [0.0]

        def dormir(segundos):
            agora[0] += segundos

        camada = self.montar(_Backend(), relogio=lambda: agora[0], dormir=dormir)
        self.addCleanup(lambda: asyncio.run(camada.fechar()))
        self._semear_em_curso("c-nova", "10 seconds")

        resultado = self.invocar(camada, {"cart_id": "c-nova"})

        self.assertFalse(resultado.ok)
        self.assertEqual(resultado.error.codigo, "UPSTREAM_TIMEOUT")
        self.assertEqual(self.backend.chamadas, [], "retomou um dono vivo")
        self.assertEqual(self.reservas()[0][3], "em_curso")

    def test_a_retoma_nao_reescreve_o_created_at(self) -> None:
        """Senao uma linha que falhasse a cada volta nunca chegava a retencao."""
        camada = self.montar(_Backend())
        self.addCleanup(lambda: asyncio.run(camada.fechar()))
        self._semear_em_curso("c-idade", "5 minutes")
        antes = self.consultar(
            "SELECT created_at FROM platform.tool_idempotency"
        )[0][0]

        self.invocar(camada, {"cart_id": "c-idade"})

        depois = self.consultar(
            "SELECT created_at FROM platform.tool_idempotency"
        )[0][0]
        self.assertEqual(antes, depois)

    def test_a_fronteira_e_a_do_minutos_para_retomar(self) -> None:
        """A fronteira e a constante, e nao um numero escondido no SQL.

        Semeia-se **um minuto de cada lado** do `MINUTOS_PARA_RETOMAR` e
        exige-se desfechos opostos. O minuto de folga nao e timidez: a sondagem
        do caminho que **nao** retoma dura 3 s de relogio simulado mas tambem
        tempo real, e a linha envelhece em tempo real — uma semente colada a
        fronteira atravessa-a durante o proprio teste, e foi o que a primeira
        versao desta bateria mediu (`1 minute 59 seconds` era retomada).

        **O relogio e o do servidor, e isso e estrutural e nao medido aqui:** a
        comparacao e entre dois `timestamptz`, e o relogio de processo que estas
        baterias injectam e um `float` — codigo que o usasse levantava
        `TypeError` em vez de decidir mal. E a razao escrita no `SQL_AGORA`.
        """
        minutos = idempotency.MINUTOS_PARA_RETOMAR
        for intervalo, retoma in (
            (f"{minutos + 1} minutes", True),
            (f"{minutos - 1} minutes", False),
        ):
            with self.subTest(intervalo=intervalo):
                self.semente.execute("DELETE FROM platform.tool_idempotency")
                agora = [0.0]
                camada = self.montar(
                    _Backend(),
                    relogio=lambda: agora[0],
                    dormir=lambda s: agora.__setitem__(0, agora[0] + s),
                )
                self._semear_em_curso("c-fronteira", intervalo)
                resultado = self.invocar(camada, {"cart_id": "c-fronteira"})
                asyncio.run(camada.fechar())
                self.assertEqual(
                    resultado.ok,
                    retoma,
                    f"com {intervalo} o desfecho devia ser ok={retoma}",
                )


class TestAtomicidadeDaRetoma(_ComIdempotencia):
    """O `WHERE` de cada retoma, medido directamente contra a base.

    **Esta classe existe porque uma mutação sobreviveu.** Tirar o
    `AND estado = 'falhada'` do `SQL_RETOMAR` não era apanhado por bateria
    nenhuma: o `_retomou` só é chamado no ramo em que a linha **já** é `falhada`,
    pelo que o desfecho era o mesmo com e sem a condição, e o que ela protege só
    aparece com dois leitores ou com uma linha noutro estado.

    E o que ela protege é o pior desfecho desta tabela: sem a condição, um
    `UPDATE … SET estado = 'em_curso', result = NULL` numa linha **`concluida`**
    **apaga o resultado guardado** e manda executar o backend outra vez — uma
    encomenda a dobrar a partir de um *replay* que estava correcto.

    Mede-se o SQL directamente, como o `test_tranca.py` faz com o
    `pg_advisory_lock`: é a única forma de pôr a linha no estado que o código
    nunca lhe dá.
    """

    def _semear(self, cart_id: str, estado: str, resultado: str | None) -> str:
        chave = self.chave_de(cart_id)
        self.semente.execute(
            "INSERT INTO platform.tool_idempotency "
            "(key, tenant_id, tool, args_hash, estado, result) "
            "VALUES (%s, %s::uuid, 'criar_pedido', %s, %s, %s::jsonb)",
            (
                chave,
                self.conversa.tenant_id,
                self.impressao_de(cart_id),
                estado,
                resultado,
            ),
        )
        return chave

    def test_a_retoma_de_uma_falhada_nao_toca_uma_concluida(self) -> None:
        chave = self._semear("c-concluida", "concluida", '{"order_id": "ord-7"}')
        ligacao = self.tomada()

        retomou = idempotency._retomou(ligacao, self.contexto(), chave)

        self.assertFalse(retomou, "retomou uma linha que ja estava concluida")
        linha = self.consultar(
            "SELECT estado, result::text FROM platform.tool_idempotency WHERE key = %s",
            (chave,),
        )
        self.assertEqual(linha[0][0], "concluida", "mudou o estado de uma concluida")
        self.assertIn("ord-7", linha[0][1], "apagou o resultado guardado")

    def test_a_retoma_de_uma_falhada_nao_toca_uma_em_curso(self) -> None:
        """Uma `em_curso` tem dono vivo, e retomá-la é correr o backend por cima dele."""
        chave = self._semear("c-curso-vivo", "em_curso", None)
        ligacao = self.tomada()

        self.assertFalse(idempotency._retomou(ligacao, self.contexto(), chave))
        self.assertEqual(
            self.consultar(
                "SELECT estado FROM platform.tool_idempotency WHERE key = %s", (chave,)
            ),
            [("em_curso",)],
        )

    def test_a_retoma_de_uma_falhada_passa_uma_vez_so(self) -> None:
        """O controlo: a condição **deixa passar** o que deve, e só uma vez.

        Sem esta, as duas de cima passavam com um `_retomou` que nunca
        actualizasse nada — e aí a retoma do critério 4 não existia.
        """
        chave = self._semear("c-falhada", "falhada", None)
        ligacao = self.tomada()

        self.assertTrue(idempotency._retomou(ligacao, self.contexto(), chave))
        self.assertEqual(
            self.consultar(
                "SELECT estado FROM platform.tool_idempotency WHERE key = %s", (chave,)
            ),
            [("em_curso",)],
        )
        # A segunda tentativa nao passa: a linha ja nao esta `falhada`. E isto que
        # faz de dois leitores concorrentes **um** executor.
        self.assertFalse(
            idempotency._retomou(ligacao, self.contexto(), chave),
            "dois leitores retomaram a mesma linha e correriam os dois o backend",
        )

    def test_a_retoma_por_idade_nao_toca_uma_concluida_velha(self) -> None:
        """A outra retoma tem a sua condição, e tem de morder pelo mesmo lado.

        Uma `concluida` de cinco minutos é velha e **não** é para retomar: o
        resultado dela é o que o *replay* devolve.
        """
        chave = self.chave_de("c-velha-ok")
        self.semente.execute(
            "INSERT INTO platform.tool_idempotency "
            "(key, tenant_id, tool, args_hash, estado, result, created_at) "
            "VALUES (%s, %s::uuid, 'criar_pedido', %s, 'concluida', %s::jsonb, "
            "        now() - interval '5 minutes')",
            (
                chave,
                self.conversa.tenant_id,
                self.impressao_de("c-velha-ok"),
                '{"order_id": "ord-8"}',
            ),
        )
        ligacao = self.tomada()
        nascida = self.consultar(
            "SELECT created_at FROM platform.tool_idempotency WHERE key = %s", (chave,)
        )[0][0]

        retomou = idempotency._retomou(
            ligacao, self.contexto(), chave, nascida_em=nascida
        )

        self.assertFalse(retomou, "retomou por idade uma linha concluida")
        linha = self.consultar(
            "SELECT estado, result::text FROM platform.tool_idempotency WHERE key = %s",
            (chave,),
        )
        self.assertEqual(linha[0][0], "concluida")
        self.assertIn("ord-8", linha[0][1], "apagou o resultado de um replay valido")


class TestConteudoDiferente(_ComIdempotencia):
    """O criterio 3 contra a base, com o `args_hash` a serio."""

    def test_o_mesmo_cart_id_com_outros_argumentos_recusa_sem_chamar(self) -> None:
        camada = self.montar(_Backend())
        self.addCleanup(lambda: asyncio.run(camada.fechar()))
        self.invocar(camada, {"cart_id": "c-1"})

        resultado = self.invocar(camada, {"cart_id": "c-1", "nota": "mudei o carrinho"})

        self.assertFalse(resultado.ok)
        self.assertEqual(
            resultado.error.codigo, "INTENT_REUSED_WITH_DIFFERENT_CONTENT"
        )
        self.assertEqual(len(self.backend.chamadas), 1, "recusou e chamou na mesma")

    def test_a_recusa_escreve_a_linha_de_auditoria_com_o_codigo_novo(self) -> None:
        """E a razao pela qual a revisao `0022` altera o `CHECK` da `0021`.

        O passo 7 escreve uma linha por invocacao, recusas incluidas. Sem o
        decimo primeiro codigo no `CHECK` fechado, o `INSERT` desta linha violava
        a restricao e a invocacao rebentava com um defeito de base em vez de
        devolver a recusa — e so a base o mostra.
        """
        camada = self.montar(_Backend())
        self.addCleanup(lambda: asyncio.run(camada.fechar()))
        self.invocar(camada, {"cart_id": "c-2"})
        self.invocar(camada, {"cart_id": "c-2", "nota": "outra coisa"})

        codigos = self.consultar(
            "SELECT status, error_code FROM platform.tool_audit "
            " WHERE tenant_id = %s ORDER BY id",
            (self.conversa.tenant_id,),
        )
        self.assertEqual(
            codigos,
            [("ok", None), ("erro", "INTENT_REUSED_WITH_DIFFERENT_CONTENT")],
        )


class TestRetencao(_ComIdempotencia):
    """O criterio 7: a varredura apaga o que esta fechado e velho, e so isso."""

    def _semear(self, sufixo: str, estado: str, dias: int) -> str:
        chave = idempotency.derivar(self.contexto(), "criar_pedido", sufixo)
        resultado = '{"order_id": "x"}' if estado == "concluida" else None
        self.semente.execute(
            "INSERT INTO platform.tool_idempotency "
            "(key, tenant_id, tool, args_hash, estado, result, created_at) "
            "VALUES (%s, %s::uuid, 'criar_pedido', %s, %s, %s::jsonb, "
            "        now() - make_interval(days => %s))",
            (
                chave,
                self.conversa.tenant_id,
                auditoria.impressao({"cart_id": sufixo}),
                estado,
                resultado,
                dias,
            ),
        )
        return chave

    def test_apaga_as_velhas_em_qualquer_estado_e_poupa_as_novas(self) -> None:
        """Relogio simulado, e **o `em_curso` velho tambem se apaga**.

        A primeira versao desta bateria exigia o contrario, e a revisao
        adversarial mostrou porque e que estava errada (`ANALISE-31`, achado 2):
        poupar uma `em_curso` «porque pode ser de uma invocacao a correr» vale por
        **minutos** e nao por um mes — o tecto da camada para uma escrita e de
        8,5 s, e uma `em_curso` com mais de `MINUTOS_PARA_RETOMAR` ja se retoma.
        O que a excepcao fazia era deixar a tabela crescer monotonicamente com
        orfas que ninguem torna a tocar, numa tabela de dinheiro.

        Apagar uma `em_curso` de 30 dias nao reabre janela nenhuma: quem voltar a
        tocar aquele `cart_id` reserva de novo e corre o backend, que e o mesmo
        que a retoma faria dois minutos depois de ela nascer.
        """
        velha_concluida = self._semear("v-concluida", "concluida", 40)
        velha_falhada = self._semear("v-falhada", "falhada", 40)
        velha_em_curso = self._semear("v-curso", "em_curso", 90)
        nova = self._semear("nova", "concluida", 2)
        na_fronteira = self._semear("fronteira", "concluida", 29)

        lote = self.ligar("batch")
        apagadas = idempotency.varrer(lote, _dt.datetime.now(_dt.UTC))

        self.assertEqual(apagadas, 3)
        restantes = {r[0] for r in self.reservas()}
        # **A fronteira e a idade e nao o estado**: as tres de 40 e 90 dias saem,
        # a de 29 dias fica. Sem a de 29 a bateria passava com uma varredura que
        # apagasse a tabela toda.
        self.assertEqual(restantes, {nova, na_fronteira})
        for chave in (velha_concluida, velha_falhada, velha_em_curso):
            self.assertNotIn(chave, restantes)

    def test_a_retencao_cobre_a_reserva_de_72h_com_folga(self) -> None:
        """O criterio pede «>= validade da reserva (72 h) + prazo de disputa».

        A validade esta fixada (`docs/tecnica/03` §6.4: tecto de 72 h); o prazo
        de disputa **nao esta fixado em documento nenhum**, e por isso o valor e
        *proposta*. O que esta bateria prende e a desigualdade que o criterio
        escreve, para que ninguem baixe a constante abaixo da reserva.
        """
        self.assertGreaterEqual(idempotency.DIAS_DE_RETENCAO * 24, 72)

    def test_o_papel_da_aplicacao_nao_apaga(self) -> None:
        """Uma reserva que o proprio turno pudesse apagar nao era uma barreira."""
        self._semear("nao-apaga", "concluida", 40)
        self.assertErroSql(
            PRIVILEGIO_INSUFICIENTE,
            self.cursor_de_app(),
            "DELETE FROM platform.tool_idempotency",
        )

    def test_dias_negativos_levantam(self) -> None:
        lote = self.ligar("batch")
        with self.assertRaises(ValueError):
            idempotency.varrer(lote, _dt.datetime.now(_dt.UTC), dias=-1)


class TestPrivacidadeDaChave(_ComIdempotencia):
    """O criterio 6, do lado que nao depende de nos: **a base recusa**."""

    def test_a_base_recusa_uma_chave_que_nao_seja_um_sha256(self) -> None:
        """«A coluna `key` nunca contem `+244`», imposto pelo `CHECK`.

        Nao e «nao lhe passamos telefones»: e nao caber la um, qualquer que seja
        o chamador e qualquer que seja o defeito dele (ADR-010).

        **O que o `CHECK` garante, com precisao**: nenhum caractere fora de
        `[0-9a-f]` e exactamente 64 deles. Isso fecha o `+244` do criterio — o
        `+` nao e hexadecimal — e fecha qualquer telefone, BSUID, nome ou morada,
        que tem letras fora de `a-f`, sinais ou comprimento diferente. O que ele
        **nao** garante, e nao e isso que o criterio pede, e a ausencia de uma
        sequencia de digitos: `000…0009991` sao 64 digitos hexadecimais validos e
        a base aceita-os, como aceita qualquer `sha256` que por acaso contenha
        quatro digitos de um telefone. Essa e a razao pela qual o criterio diz
        «nunca contem `+244`» e nao «nunca contem digitos».
        """
        cursor = self.ligar("admin").cursor()
        for chave in (
            TELEFONE,
            f"+244{TELEFONE[3:]}",
            "A" * 64,
            "0" * 63,
            "0" * 65,
            f"{'0' * 32}-{'0' * 31}",
        ):
            with self.subTest(chave=chave):
                self.assertErroSql(
                    VIOLACAO_DE_CHECK,
                    cursor,
                    "INSERT INTO platform.tool_idempotency "
                    "(key, tenant_id, tool, args_hash) "
                    "VALUES (%s, %s::uuid, 'criar_pedido', %s)",
                    (chave, self.conversa.tenant_id, b"0" * 32),
                )

    def test_nenhuma_coluna_guarda_o_telefone_que_passou_pelos_argumentos(self) -> None:
        """Varrimento por canario: o telefone entra pelo `cart_id` e nao sai.

        O controlo deste varrimento e o `test_o_varrimento_apanha_um_canario`
        logo abaixo — sem ele, um varrimento que procurasse na coluna errada dava
        zero e dizia que estava tudo bem, que e o defeito que o KAM-026 pagou
        (procurava texto num campo `msgpack`).
        """
        camada = self.montar(_Backend())
        self.addCleanup(lambda: asyncio.run(camada.fechar()))
        self.invocar(camada, {"cart_id": TELEFONE, "nota": TELEFONE})

        linhas = self.consultar(
            "SELECT key || ' ' || tool || ' ' || estado || ' ' "
            "       || coalesce(result::text, '') || ' ' || args_hash::text "
            "  FROM platform.tool_idempotency"
        )
        self.assertTrue(linhas, "nao semeei nada: o varrimento nao mediu nada")
        for (texto,) in linhas:
            self.assertNotIn(TELEFONE, texto)
            self.assertNotIn("+244", texto)

    def test_o_varrimento_apanha_um_canario(self) -> None:
        """O controlo: o varrimento de cima **pode** falhar.

        Semeia-se o telefone no `result`, que e a unica coluna de texto livre da
        tabela, e exige-se que o varrimento o encontre. Se nao encontrasse, o
        teste de cima nao estava a medir nada.
        """
        chave = self.chave_de("canario")
        self.semente.execute(
            "INSERT INTO platform.tool_idempotency "
            "(key, tenant_id, tool, args_hash, estado, result) "
            "VALUES (%s, %s::uuid, 'criar_pedido', %s, 'concluida', %s::jsonb)",
            (
                chave,
                self.conversa.tenant_id,
                auditoria.impressao({"cart_id": "canario"}),
                f'{{"nota": "{TELEFONE}"}}',
            ),
        )
        linhas = self.consultar(
            "SELECT coalesce(result::text, '') FROM platform.tool_idempotency"
        )
        self.assertTrue(any(TELEFONE in texto for (texto,) in linhas))


class TestIsolamento(_ComIdempotencia):
    """A chave do tenant A nunca devolve o resultado do tenant B.

    E o teste que os *Testes Requeridos* do bloco pedem por extenso, com o
    «mesmo `cart_id` forjado»: dois tenants, o mesmo `cart_id`, e a pergunta e se
    um ve a reserva do outro.
    """

    def test_o_mesmo_cart_id_em_dois_tenants_sao_duas_reservas(self) -> None:
        outra = self.criar_conversa()
        self.dar_entitlement(outra)
        camada = self.montar(_Backend())
        self.addCleanup(lambda: asyncio.run(camada.fechar()))

        primeiro = self.invocar(camada, {"cart_id": "c-forjado"})
        segundo = self.invocar(
            camada, {"cart_id": "c-forjado"}, ctx=self.contexto(outra)
        )

        self.assertFalse(primeiro.idempotent_replay)
        self.assertFalse(
            segundo.idempotent_replay, "o tenant B leu a reserva do tenant A"
        )
        self.assertEqual(len(self.backend.chamadas), 2)
        self.assertNotEqual(primeiro.data, segundo.data)
        self.assertEqual(len(self.reservas()), 2)

    def test_a_rls_recusa_reservar_no_nome_de_outro_tenant(self) -> None:
        """O `WITH CHECK` da politica, medido: e a metade que a RLS acrescenta.

        Reservar com o `app.tenant_id` de A e a coluna `tenant_id` de B seria
        desduplicar a encomenda de um cliente contra o carrinho de outro.
        """
        outra = self.criar_conversa()
        self.assertErroSql(
            PRIVILEGIO_INSUFICIENTE,
            self.cursor_de_app(),
            "INSERT INTO platform.tool_idempotency "
            "(key, tenant_id, tool, args_hash) "
            "VALUES (%s, %s::uuid, 'criar_pedido', %s)",
            ("f" * 64, outra.tenant_id, b"0" * 32),
        )


class TestRestricoes(_ComIdempotencia):
    """Os `CHECK` da revisao `0022`, um a um, e os dois sentidos do do resultado."""

    def _inserir(self, **troca):
        valores = {
            "key": "a" * 64,
            "tenant_id": self.conversa.tenant_id,
            "tool": "criar_pedido",
            "args_hash": b"0" * 32,
            "estado": "em_curso",
            "result": None,
        }
        valores.update(troca)
        return (
            "INSERT INTO platform.tool_idempotency "
            "(key, tenant_id, tool, args_hash, estado, result) "
            "VALUES (%s, %s::uuid, %s, %s, %s, %s::jsonb)",
            tuple(valores[c] for c in
                  ("key", "tenant_id", "tool", "args_hash", "estado", "result")),
        )

    def setUp(self) -> None:
        super().setUp()
        self.cursor_admin = self.ligar("admin").cursor()

    def test_um_estado_fora_dos_tres_e_recusado(self) -> None:
        sql, parametros = self._inserir(estado="pendente")
        self.assertErroSql(VIOLACAO_DE_CHECK, self.cursor_admin, sql, parametros)

    def test_um_args_hash_que_nao_tem_32_octetos_e_recusado(self) -> None:
        sql, parametros = self._inserir(args_hash=b"0" * 31)
        self.assertErroSql(VIOLACAO_DE_CHECK, self.cursor_admin, sql, parametros)

    def test_um_nome_de_tool_fora_da_gramatica_e_recusado(self) -> None:
        sql, parametros = self._inserir(tool="Criar Pedido")
        self.assertErroSql(VIOLACAO_DE_CHECK, self.cursor_admin, sql, parametros)

    def test_uma_concluida_sem_resultado_e_recusada(self) -> None:
        """O primeiro sentido: um *replay* vazio como se a tool nada devolvesse."""
        sql, parametros = self._inserir(estado="concluida", result=None)
        self.assertErroSql(VIOLACAO_DE_CHECK, self.cursor_admin, sql, parametros)

    def test_uma_falhada_com_resultado_e_recusada(self) -> None:
        """O segundo sentido, e e a licao da `0021`: um `CHECK` num sentido so
        deixava passar metade.

        Um resultado numa linha `falhada` era um resultado que a retoma do
        criterio 4 devolvia como *replay* de uma invocacao que ninguem confirmou.
        """
        sql, parametros = self._inserir(estado="falhada", result='{"order_id": "x"}')
        self.assertErroSql(VIOLACAO_DE_CHECK, self.cursor_admin, sql, parametros)

    def test_uma_em_curso_com_resultado_e_recusada(self) -> None:
        sql, parametros = self._inserir(estado="em_curso", result='{"order_id": "x"}')
        self.assertErroSql(VIOLACAO_DE_CHECK, self.cursor_admin, sql, parametros)

    def test_uma_concluida_com_resultado_passa(self) -> None:
        """O controlo dos quatro acima: a restricao **deixa passar** o que deve.

        Sem isto, um `CHECK` que recusasse tudo passava as cinco baterias de
        cima e a tabela era inutilizavel.
        """
        sql, parametros = self._inserir(estado="concluida", result='{"order_id": "x"}')
        self.semente.execute(sql, parametros)
        self.assertEqual(len(self.reservas()), 1)

    def test_a_aplicacao_nao_altera_o_args_hash(self) -> None:
        """A coluna que o criterio 3 compara nao e alteravel por quem a acciona.

        E a mesma razao medida no KAM-015 para a `outbound_messages`: um `GRANT
        UPDATE` de uma palavra derrubava a recusa inteira, e nenhuma matriz de
        privilegio de **tabela** o mostrava.
        """
        sql, parametros = self._inserir(estado="em_curso")
        self.semente.execute(sql, parametros)
        self.assertErroSql(
            PRIVILEGIO_INSUFICIENTE,
            self.cursor_de_app(),
            "UPDATE platform.tool_idempotency SET args_hash = %s WHERE key = %s",
            (b"1" * 32, "a" * 64),
        )


class TestCicloDaRevisao(ComAgr):
    """O `downgrade` da `0022` e o `upgrade` de volta (DoD: migrações reversíveis).

    Compara-se o conjunto de tabelas do `platform` com o `TABELAS_ATE_0021` do
    `db/tests/base.py`, que e a forma que as outras revisoes usam — e por isso
    que aquela constante existe.

    **O que o `downgrade` nao reverte esta escrito**: o decimo primeiro valor de
    `tool_audit.error_code` fica. A razao esta no `downgrade()` da revisao e na
    secçao de verificaçao do bloco, e esta bateria **mede-a** em vez de a deixar
    por afirmar — uma assimetria declarada que ninguem verifica e indistinguivel
    de um esquecimento.
    """

    def _tabelas(self) -> tuple[str, ...]:
        return tuple(
            sorted(
                nome
                for (nome,) in self.consultar(
                    "SELECT table_name FROM information_schema.tables "
                    " WHERE table_schema = 'platform' AND table_type = 'BASE TABLE'"
                )
            )
        )

    def _dominio_do_error_code(self) -> str:
        return self.consultar(
            "SELECT pg_get_constraintdef(oid) FROM pg_constraint "
            " WHERE conname = 'tool_audit_error_code'"
        )[0][0]

    def test_desce_para_a_0021_e_volta(self) -> None:
        self.assertEqual(self._tabelas(), TABELAS)
        self.assertIn("INTENT_REUSED_WITH_DIFFERENT_CONTENT", self._dominio_do_error_code())

        alembic_ok("downgrade", "0021")
        self.assertEqual(self._tabelas(), TABELAS_ATE_0021)
        # A assimetria declarada: o dominio **nao** volta a estreitar.
        self.assertIn(
            "INTENT_REUSED_WITH_DIFFERENT_CONTENT",
            self._dominio_do_error_code(),
            "o downgrade estreitou o dominio e o dicionario passa a discordar da base",
        )

        alembic_ok("upgrade", "head")
        self.assertEqual(self._tabelas(), TABELAS)
        # E a politica volta com a tabela: um `downgrade` que deixasse a tabela
        # sem RLS ao subir era pior do que nao descer, porque nada o dizia.
        self.assertEqual(
            self.consultar(
                "SELECT relrowsecurity, relforcerowsecurity FROM pg_class "
                " WHERE oid = 'platform.tool_idempotency'::regclass"
            ),
            [(True, True)],
        )
        # E os privilegios por coluna tambem: o `UPDATE` do `kamba_app` continua
        # a nao alcançar o `args_hash`, que e o que faz o criterio 3 valer.
        self.assertEqual(
            self.consultar(
                "SELECT column_name FROM information_schema.column_privileges "
                " WHERE table_name = 'tool_idempotency' AND grantee = 'kamba_app' "
                "   AND privilege_type = 'UPDATE' ORDER BY column_name"
            ),
            [("estado",), ("result",)],
        )


if __name__ == "__main__":
    unittest.main()
