"""O AGR contra o COM a correr, com a base e um classificador falso (KAM-230, criterio 3).

Os ensaios do KAM-228 mediam o AGR contra um COM de ensaio, e o `screen` real do
COM estava medido do lado dele (KAM-222). Aqui juntam-se os dois processos, e
**so o transporte para o proxy LiteLLM e duplo**:

```text
executor do submit_quote (este processo, ligacao kamba_app)
  -> POST /internal/screen do COM      (services/com/src/server.ts, Node, a base do gate)
       -> screen do KAM-088            (a politica, as regras, a gravacao em screening_decision)
       -> POST /internal/screening     (a rota do AGR, servida por este processo)
            -> gate de destino         (PortaSobreDestinos sobre tenant_destinations, kamba_app)
            -> transporte do proxy     (o duplo: um veredicto `permitida`)
```

E o que o criterio 3 pede, e o que a decisao do fundador de 2026-11-20 (opcao B)
precisa de provar de ponta a ponta: a finalidade das condicoes sai do AGR, o
COM confere-a com o sujeito, e o *gate* consulta-a contra a base — um tenant so
com o destino do catalogo recusa as condicoes.

## Porque vive nesta suite

E a que ja sabe lancar um processo de producao em Node contra a base do gate
(`node.lancar`), com `node` no `PATH` (o CI) ou em contentor na rede do gate
(uma maquina sem `node`). Em contentor, o COM chega a rota do AGR deste
processo por `host.docker.internal`, que o Docker Desktop resolve; num Linux sem
`node` no `PATH` faltaria o `--add-host`, e o caso diz-se em vez de se medir.
"""

from __future__ import annotations

import base64
import secrets
import threading
import time
import uuid
from decimal import Decimal
from typing import Any

import ligacao
from tests_agr.test_quote_requests import ComOrcamento
from tests_entrada import node
from tests_entrada.test_entrada import ARRANQUE, _sonda, esperar_por, porta_livre

import uvicorn  # noqa: E402
from kamba_agr import metricas as metricas_mod  # noqa: E402
from kamba_agr.app import create_app  # noqa: E402
from kamba_agr.llm import aliases as aliases_mod  # noqa: E402
from kamba_agr.llm import destinos as llm_destinos  # noqa: E402
from kamba_agr.llm import precos as precos_mod  # noqa: E402
from kamba_agr.llm import screening as llm_screening  # noqa: E402
from kamba_agr.llm.cliente import ClienteDeLlm  # noqa: E402
from kamba_agr.orcamento import regras  # noqa: E402
from kamba_agr.tls import orcamento_tools  # noqa: E402
from kamba_agr.tls.com import ClienteDoCom  # noqa: E402
from kamba_agr.tls.contexto import ToolContext  # noqa: E402
from kamba_agr.tls.erros import VALIDATION_ERROR  # noqa: E402
from kamba_agr.tls.especificacoes import ErroDeBackend, Pedido  # noqa: E402
from kamba_core.destinos import FINALIDADE_CLASSIFICACAO, FINALIDADE_CONDICOES  # noqa: E402

REAIS = aliases_mod.ler(node.RAIZ / "llm")

#: As credenciais das duas rotas, geradas por corrida. Nunca um segredo real.
CREDENCIAL_DO_COM = f"ensaio-com-{secrets.token_hex(8)}"
CREDENCIAL_DO_SCREENING = f"ensaio-screening-{secrets.token_hex(8)}"
SEGREDO_DE_INTENTS = f"v1:{base64.b64encode(secrets.token_bytes(32)).decode()}"

#: Os de `db/tests_agr/test_screening_pelo_gate.py`: um destino `autorizado`
#: exige-os.
APD_REF = "APD/2026/000-TESTE"
CONTRATO_REF = "contratos/2026/teste"

PRECOS = {
    ("anthropic", "por_decidir"): precos_mod.Preco(
        "anthropic", "por_decidir",
        Decimal("0.10"), Decimal("0.01"), Decimal("0.50"), "CONFIRMADO", "ensaio",
    ),
}

LIMPAS = "entrega combinada consigo"
VERSAO_DA_CATEGORIA = "1.0.0+m.2"


class _Proxy:
    """O proxy LiteLLM, em duplo: conta as chamadas e responde `permitida`."""

    def __init__(self) -> None:
        self.chamadas = 0
        self._trinco = threading.Lock()

    def __call__(self, _url, _cabecalhos, _corpo, _timeout):  # noqa: ANN001, ANN204
        with self._trinco:
            self.chamadas += 1
        return (
            200,
            {
                "model": "anthropic/por_decidir",
                "choices": [{"message": {"content": '{"decisao":"permitida","confianca":0.9}'}}],
                "usage": {"prompt_tokens": 120, "completion_tokens": 8},
            },
            {},
        )


class TestOAgrContraOComACorrer(ComOrcamento):
    """Criterio 3 do KAM-230, e o criterio 1 do KAM-228 de ponta a ponta.

    Canario: `test_condicoes_limpas_seguem_e_a_decisao_grava_se`. Sem ele, uma
    montagem que recusasse tudo — o COM sem classificador, a rota sem
    credencial, o *gate* sem base — passava os outros dois.
    """

    @classmethod
    def setUpClass(cls) -> None:
        super().setUpClass()
        cls.proxy = _Proxy()
        cls._servidor, cls._fio, porta_do_agr = cls._servir_o_agr()
        anfitriao = "host.docker.internal" if node.na_rede() else "127.0.0.1"
        cls.porta_do_com = porta_livre()
        cls.com = node.lancar(
            "services/com",
            "src/server.ts",
            {
                "KAMBA_COM_DB_URL": node.url_da_base("app"),
                "KAMBA_SECRET_SEGREDO_INTENTS": SEGREDO_DE_INTENTS,
                "KAMBA_SECRET_COM_INTERNAL_TOKEN": CREDENCIAL_DO_COM,
                "KAMBA_AGR_URL": f"http://{anfitriao}:{porta_do_agr}",
                "KAMBA_SECRET_AGR_SCREENING_TOKEN": CREDENCIAL_DO_SCREENING,
                "KAMBA_ENV": "dev",
                "PORT": str(cls.porta_do_com),
                "HOST": "127.0.0.1",
            },
            "com",
            porta=cls.porta_do_com,
        )
        if not esperar_por(lambda: _sonda(cls.porta_do_com), ARRANQUE):
            cls.com.parar()
            cls._parar_o_agr()
            raise AssertionError(f"o com nao comecou a responder{cls.com.diagnostico()}")

    @classmethod
    def tearDownClass(cls) -> None:
        cls.com.parar()
        cls._parar_o_agr()
        super().tearDownClass()

    @classmethod
    def _servir_o_agr(cls) -> tuple[uvicorn.Server, threading.Thread, int]:
        """A rota do classificador do AGR, com o *gate* real, num *uvicorn* deste processo."""
        cliente = ClienteDeLlm(
            aliases={"screening": REAIS["screening"]},
            tabela_de_precos=PRECOS,
            porta_de_destinos=llm_destinos.arrancar(
                llm_destinos.AMBIENTE_PROD, lambda: ligacao.ligar("app")
            ),
            abrir_ligacao=lambda: ligacao.ligar("app"),
            chave_virtual=lambda _t: "chave-de-ensaio-do-screening",
            metricas=metricas_mod.MetricasDoAgr(),
            transporte=cls.proxy,
        )
        alias = REAIS["screening"]
        app = create_app(
            rotas_internas=llm_screening.rotas(
                credencial=lambda: CREDENCIAL_DO_SCREENING,
                classificar=llm_screening.ClassificadorDeScreening(cliente, alias),
                folga_s=llm_screening.folga_de_fila_s(alias),
                minimo_s=llm_screening.minimo_s(alias),
            )
        )
        porta = porta_livre()
        # Em contentor o COM chega aqui por `host.docker.internal`; sem
        # contentor, por `127.0.0.1`. Nos dois casos so na interface local.
        servidor = uvicorn.Server(uvicorn.Config(app, host="127.0.0.1", port=porta, log_level="warning"))
        fio = threading.Thread(target=servidor.run, daemon=True)
        fio.start()
        if not esperar_por(lambda: servidor.started, 30.0):
            raise AssertionError("a rota do classificador do AGR nao arrancou")
        return servidor, fio, porta

    @classmethod
    def _parar_o_agr(cls) -> None:
        cls._servidor.should_exit = True
        cls._fio.join(timeout=10)

    # ------------------------------------------------------------ o caso

    def setUp(self) -> None:
        super().setUp()
        self.proxy.chamadas = 0
        self.addCleanup(self._limpar_destinos)

    def _limpar_destinos(self) -> None:
        # Uma linha da finalidade nova deixada para tras fazia a descida da
        # `0078` recusar-se noutro ensaio da mesma base.
        self.semente.execute(
            "DELETE FROM platform.tenant_destinations WHERE tenant_id = %s", (self.tenant,)
        )
        self.semente.execute("DELETE FROM dat.llm_call_log WHERE tenant_id = %s", (self.tenant,))

    def _categoria(self, categoria: str) -> None:
        """A categoria declarada do tenant: a decisao `categoria` mais recente (KAM-222)."""
        self.semente.execute(
            "INSERT INTO platform.screening_decision (tenant_id, sujeito_tipo, sujeito_ref, decisao, "
            "regras, versao_politica, origem, conteudo_sha256) "
            "VALUES (%s, 'categoria', %s, 'permitida', ARRAY[%s], %s, 'regra', %s)",
            (self.tenant, categoria, categoria, VERSAO_DA_CATEGORIA, uuid.uuid4().bytes * 2),
        )

    def _destino(self, finalidade: str) -> None:
        self.semente.execute(
            "INSERT INTO platform.tenant_destinations "
            "(tenant_id, provider, country, purpose, status, apd_ref, contrato_ref, "
            " retencao_zero, sem_treino, autorizado_em) "
            "VALUES (%s, 'anthropic', 'US', %s, 'autorizado', %s, %s, true, true, "
            " now() - interval '1 day')",
            (self.tenant, finalidade, APD_REF, CONTRATO_REF),
        )

    def _submeter(self, condicoes: str) -> Any:
        """O executor do `submit_quote` de producao, sobre o COM a correr."""
        pedido_do_cliente = self._pedir()
        executor = orcamento_tools.executores(
            cliente_do_com=ClienteDoCom(
                base=f"http://127.0.0.1:{self.porta_do_com}", credencial=lambda: CREDENCIAL_DO_COM
            )
        )["submit_quote"]
        ctx = ToolContext(
            tenant_id=self.tenant,
            channel_id=str(uuid.uuid4()),
            contact_id=self.dono,
            conversation_id=self.conversa.conversation_id,
            turn_id=uuid.uuid4().hex,
            vertical="dono",
            run_id=uuid.uuid4().hex,
            graph_version="ensaio",
        )
        args = orcamento_tools.ArgumentosDeSubmitQuote(
            referencia=regras.referencia_interna(pedido_do_cliente.quote_id),
            valor="120 mil",
            condicoes=condicoes,
        )
        self.quote_id = pedido_do_cliente.quote_id
        return executor(
            Pedido(ctx=ctx, args=args, timeout_ms=8_000, ligacao=self.app, prazo=time.monotonic() + 8.0)
        )

    def _decisoes(self) -> list[tuple[str, str]]:
        self.semente.execute(
            "SELECT decisao, array_to_string(regras, ',') FROM platform.screening_decision "
            "WHERE tenant_id = %s AND sujeito_tipo = 'condicoes' AND sujeito_ref = %s",
            (self.tenant, self.quote_id),
        )
        return [tuple(linha) for linha in self.semente.fetchall()]

    def _chamadas_ao_modelo(self) -> list[str]:
        self.semente.execute(
            "SELECT resultado FROM dat.llm_call_log WHERE tenant_id = %s AND papel = 'screening'",
            (self.tenant,),
        )
        return [linha[0] for linha in self.semente.fetchall()]

    def _assert_recusa(self, chamar) -> None:  # noqa: ANN001
        with self.assertRaises(ErroDeBackend) as caso:
            chamar()
        self.assertEqual((caso.exception.codigo, caso.exception.detalhe), (VALIDATION_ERROR, regras.CONDICOES_RECUSADAS))
        # Nada se gravou na resposta: o pedido continua a espera do valor.
        self.assertEqual([linha[1] for linha in self._linhas()], [regras.PEDIDO])

    # ------------------------------------------------------------ os casos

    def test_condicoes_limpas_seguem_e_a_decisao_grava_se(self) -> None:
        self._categoria("moda")
        self._destino(FINALIDADE_CONDICOES)
        resposta = self._submeter(LIMPAS)
        self.assertIn(LIMPAS, resposta.data["previsao"])
        # A decisao do COM, com o sujeito das condicoes e o `quote_id`.
        self.assertEqual(self._decisoes(), [("permitida", "moda")])
        # O modelo foi chamado uma vez, pelo gate, com a linha `ok`.
        self.assertEqual(self.proxy.chamadas, 1)
        self.assertEqual(self._chamadas_ao_modelo(), ["ok"])

    def test_so_o_destino_do_catalogo_recusa_as_condicoes(self) -> None:
        """A decisao B do fundador: a `classificacao_de_catalogo` nunca as cobre."""
        self._categoria("moda")
        self._destino(FINALIDADE_CLASSIFICACAO)
        self._assert_recusa(lambda: self._submeter(LIMPAS))
        # O COM gravou a `condicional` (o classificador nao respondeu), e o
        # texto nao saiu: zero chamadas ao proxy, uma linha `destino_negado`.
        ((decisao, regras_da_decisao),) = self._decisoes()
        self.assertEqual(decisao, "condicional")
        self.assertIn("classificador_indisponivel", regras_da_decisao)
        self.assertEqual(self.proxy.chamadas, 0)
        self.assertEqual(self._chamadas_ao_modelo(), ["destino_negado"])

    def test_uma_categoria_restrita_recusa_sem_ir_ao_modelo(self) -> None:
        self._categoria("tabaco")
        self._destino(FINALIDADE_CONDICOES)
        self._assert_recusa(lambda: self._submeter(LIMPAS))
        ((decisao, regras_da_decisao),) = self._decisoes()
        self.assertEqual(decisao, "bloqueada")
        self.assertIn("tabaco", regras_da_decisao)
        # Uma `bloqueada` das regras e final: o classificador nao e chamado.
        self.assertEqual(self.proxy.chamadas, 0)
        self.assertEqual(self._chamadas_ao_modelo(), [])

    def test_um_numero_nas_condicoes_nao_sai_do_agr(self) -> None:
        """A guarda local recusa antes do COM: nenhuma decisao, nenhuma chamada."""
        self._categoria("moda")
        self._destino(FINALIDADE_CONDICOES)
        with self.assertRaises(ErroDeBackend) as caso:
            self._submeter("entrega em tres dias")
        self.assertEqual(caso.exception.detalhe, regras.CONDICOES_COM_NUMEROS)
        self.assertEqual(self._decisoes(), [])
        self.assertEqual(self.proxy.chamadas, 0)

