"""A rota de entrega do IDX e o seu processo, sem base nem fila (KAM-194).

O comportamento contra o PostgreSQL mede-se no *gate* 8 e no ensaio de pilha;
aqui fica a decisao: os tres codigos que dizem a casca o que fazer, a DLQ com e
sem envelope, o arquivo para o *job* do reconciliador, a escada, a credencial e
o ciclo da reindexacao.
"""

from __future__ import annotations

import http.client
import json
import threading
import unittest
import uuid
from typing import Any

from kamba_core.eventos import entrega as contrato
from kamba_core.eventos.consumo import TENTATIVAS, Adiar
from kamba_core.eventos.ligacao import ClienteDaLigacao
from kamba_core.idx import consumidor, processo
from kamba_core.idx.entrega import (
    MOTIVO_ENVELOPE_INVALIDO,
    MOTIVO_TENTATIVAS_ESGOTADAS,
    MOTIVO_TIPO_DESCONHECIDO,
    SQL_ABRIR_DLQ,
    TIPO_ILEGIVEL,
    EntregaAoIdx,
    Resposta,
)
from kamba_core.idx.metricas import METRICA_REINDEXADOS, MetricasDoIdx

TENANT = "3f1c2a9e-0d4b-4e55-9a7c-1b2c3d4e5f60"
OUTRO = "5a6b7c8d-1e2f-4a3b-8c9d-0e1f2a3b4c5d"
EVENTO = "0192f1c4-7b1e-7d2a-9c3e-5a1f0b6e2d44"


def envelope(**mudar: Any) -> dict[str, Any]:
    base = {
        "id": EVENTO,
        "tipo": "catalog.product_changed",
        "versao": 1,
        "tenant_id": TENANT,
        "agregado": {"tipo": "product", "id": "p-1", "seq": 1},
        "finalidades": ["transacao"],
        "payload": {"sku": "SKU-1", "estado": "publicado"},
    }
    base.update(mudar)
    return base


def corpo(**mudar: Any) -> dict[str, Any]:
    base: dict[str, Any] = {
        "event_id": EVENTO,
        "tenant_id": TENANT,
        "envelope": envelope(),
        "tentativas": 1,
    }
    base.update(mudar)
    return base


class _Cursor:
    def __init__(self, ligacao: "Ligacao") -> None:
        self._ligacao = ligacao
        self.description: Any = None
        self.rowcount = -1
        self._linhas: list[tuple[Any, ...]] = []

    def execute(self, sql: str, parametros: tuple[Any, ...] = ()) -> None:
        self._ligacao.instrucoes.append((sql, tuple(parametros)))
        colunas, linhas, contagem = self._ligacao.responder(sql, tuple(parametros))
        self.description = [(c,) for c in colunas] if colunas else None
        self._linhas = list(linhas)
        self.rowcount = contagem

    def fetchone(self) -> Any:
        return self._linhas[0] if self._linhas else None

    def fetchall(self) -> list[Any]:
        return list(self._linhas)

    def close(self) -> None:
        pass


class Ligacao:
    """Uma ligacao DB-API falsa: regista as instrucoes e responde por texto.

    **Decide pelo texto da instrucao**, e nao por argumento: um fake que
    respondesse pela posicao da chamada ficava verde com o `WHERE` apagado.
    """

    def __init__(self, arquivo: dict[str, Any] | None = None, falhar_efeito: BaseException | None = None) -> None:
        self.autocommit = False
        self.instrucoes: list[tuple[str, tuple[Any, ...]]] = []
        self.commits = 0
        self.rollbacks = 0
        self.fechada = False
        self.arquivo = arquivo or {}
        self.falhar_efeito = falhar_efeito
        self.marcados: set[tuple[str, str]] = set()

    def cursor(self) -> _Cursor:
        return _Cursor(self)

    def commit(self) -> None:
        self.commits += 1

    def rollback(self) -> None:
        self.rollbacks += 1

    def close(self) -> None:
        self.fechada = True

    def responder(self, sql: str, p: tuple[Any, ...]):
        texto = " ".join(sql.split())
        if "set_config" in texto:
            return (["set_config"], [(p[0],)], 1)
        if "FROM platform.events_log" in texto:
            achado = self.arquivo.get(p[0])
            return (["envelope"], [(achado,)] if achado is not None else [], 1 if achado else 0)
        if texto.startswith("INSERT INTO platform.events_consumed"):
            chave = (p[0], p[1])
            if chave in self.marcados:
                return ([], [], 0)
            self.marcados.add(chave)
            return ([], [], 1)
        if "FROM platform.v_oferta_viva" in texto:
            if self.falhar_efeito is not None:
                raise self.falhar_efeito
            return (["nome", "publicado"], [{"nome": "Arroz", "publicado": True}], 1)
        if "idx.norm_versao" in texto or "idx.termo_canonico" in texto or "idx.lexico" in texto:
            return ([], [], 0)
        return ([], [], 1)

    def dlq(self) -> list[tuple[Any, ...]]:
        return [p for s, p in self.instrucoes if s == SQL_ABRIR_DLQ]


class _Metricas:
    def __init__(self) -> None:
        self.contados: list[tuple[str, str | None]] = []

    def contar(self, metrica: str, sufixo: str | None = None, quanto: int = 1) -> None:
        self.contados.append((metrica, sufixo))


def ao_idx(ligacao: Ligacao) -> EntregaAoIdx:
    return EntregaAoIdx(lambda: ligacao)


class _ComEfeitoFalso(unittest.TestCase):
    """O efeito do KAM-061 trocado por um que nao le lexico: decide-se aqui a entrega."""

    def setUp(self) -> None:
        self._original = consumidor.efeito
        self.efeitos: list[str] = []
        self.falhar: BaseException | None = None

        def efeito(bd, env) -> None:
            if self.falhar is not None:
                raise self.falhar
            self.efeitos.append(env["tipo"])

        consumidor.efeito = efeito  # type: ignore[assignment]

    def tearDown(self) -> None:
        consumidor.efeito = self._original  # type: ignore[assignment]


class TestCorpo(unittest.TestCase):
    """Corpo invalido: 400, sem abrir ligacao nenhuma."""

    def test_os_quatro_campos_sao_a_lista_fechada(self) -> None:
        self.assertEqual(
            contrato.CAMPOS_DA_ENTREGA, ("event_id", "tenant_id", "envelope", "tentativas")
        )

    def test_corpos_invalidos_dao_400_e_nao_abrem_a_base(self) -> None:
        aberturas: list[int] = []

        def abrir() -> Ligacao:
            aberturas.append(1)
            return Ligacao()

        casos = {
            "corpo_nao_e_objecto": [1, 2],
            "campo_desconhecido": corpo(extra=1),
            "campo_em_falta": {k: v for k, v in corpo().items() if k != "envelope"},
            "campo_invalido_tentativas": corpo(tentativas=0),
            "campo_invalido_event_id": corpo(event_id="nao-e-uuid"),
            "campo_invalido_tenant_id": corpo(tenant_id=TENANT.upper()),
        }
        for codigo, dado in casos.items():
            with self.subTest(codigo=codigo):
                resposta = EntregaAoIdx(abrir).entregar(dado)
                self.assertEqual(resposta, Resposta(400, "corpo_invalido", error_code=codigo))
        self.assertEqual(aberturas, [], "um corpo invalido nao abre ligacao")

    def test_tentativas_booleana_recusa(self) -> None:
        with self.assertRaises(contrato.EntregaInvalidaError):
            contrato.ler_entrega(corpo(tentativas=True))

    def test_o_envelope_nulo_e_aceite(self) -> None:
        self.assertIsNone(contrato.ler_entrega(corpo(envelope=None)).envelope)


class TestDlqSemConsumo(_ComEfeitoFalso):
    def test_ponteiros_divergentes_vao_a_dlq_sem_envelope(self) -> None:
        for mudar in ({"tenant_id": OUTRO}, {"id": str(uuid.uuid4())}):
            with self.subTest(mudar=mudar):
                ligacao = Ligacao()
                resposta = ao_idx(ligacao).entregar(corpo(envelope=envelope(**mudar)))
                self.assertEqual(resposta, Resposta(200, "para_dlq"))
                [linha] = ligacao.dlq()
                self.assertEqual(linha[0], "idx")
                self.assertEqual(linha[1], EVENTO)
                self.assertEqual(linha[2], TIPO_ILEGIVEL)
                self.assertEqual(linha[4], TENANT, "a linha fica no tenant da fila")
                self.assertNotIn(OUTRO, linha[5], "o envelope recusado nao se guarda")
                self.assertEqual(linha[6], MOTIVO_ENVELOPE_INVALIDO)
                self.assertEqual(self.efeitos, [])
                self.assertFalse(
                    any("events_consumed" in s for s, _ in ligacao.instrucoes),
                    "nada se marca",
                )

    def test_envelope_ilegivel_vai_a_dlq_sem_envelope(self) -> None:
        for mau in ("texto", envelope(agregado={"tipo": "p", "id": "x", "seq": "1"}), envelope(versao=True)):
            with self.subTest(mau=mau):
                ligacao = Ligacao()
                self.assertEqual(ao_idx(ligacao).entregar(corpo(envelope=mau)), Resposta(200, "para_dlq"))
                self.assertEqual(ligacao.dlq()[0][6], MOTIVO_ENVELOPE_INVALIDO)

    def test_tipo_nao_subscrito_vai_a_dlq_com_o_envelope(self) -> None:
        ligacao = Ligacao()
        resposta = ao_idx(ligacao).entregar(corpo(envelope=envelope(tipo="order.created")))
        self.assertEqual(resposta, Resposta(200, "para_dlq"))
        [linha] = ligacao.dlq()
        self.assertEqual(linha[2], "order.created")
        self.assertEqual(linha[6], MOTIVO_TIPO_DESCONHECIDO)
        self.assertEqual(json.loads(linha[5])["id"], EVENTO, "o envelope inteiro fica")
        self.assertEqual(self.efeitos, [])

    def test_a_dlq_corre_com_o_contexto_do_tenant(self) -> None:
        ligacao = Ligacao()
        ao_idx(ligacao).entregar(corpo(envelope=envelope(tipo="order.created")))
        indice = [s for s, _ in ligacao.instrucoes].index(SQL_ABRIR_DLQ)
        anterior_sql, anterior_p = ligacao.instrucoes[indice - 1]
        self.assertIn("set_config", anterior_sql)
        self.assertEqual(anterior_p, (TENANT,))
        self.assertTrue(ligacao.fechada)


class TestConsumo(_ComEfeitoFalso):
    def test_aplicado_e_depois_duplicado(self) -> None:
        ligacao = Ligacao()
        idx = ao_idx(ligacao)
        self.assertEqual(idx.entregar(corpo()), Resposta(200, "aplicado"))
        self.assertEqual(idx.entregar(corpo(tentativas=2)), Resposta(200, "duplicado"))
        self.assertEqual(self.efeitos, ["catalog.product_changed"], "o efeito corre uma vez")
        self.assertEqual(ligacao.dlq(), [])

    def test_os_quatro_eventos_do_tenant_sao_aceites(self) -> None:
        for tipo in consumidor.EVENTOS_DO_TENANT:
            with self.subTest(tipo=tipo):
                ligacao = Ligacao()
                env = envelope(tipo=tipo, payload={})
                self.assertEqual(ao_idx(ligacao).entregar(corpo(envelope=env)), Resposta(200, "aplicado"))

    def test_falha_do_efeito_repete_pela_escada(self) -> None:
        self.falhar = RuntimeError("base em baixo")
        esperado = {1: 1, 2: 5, 3: 30, 4: 120, 5: 600}
        for tentativa, segundos in esperado.items():
            with self.subTest(tentativa=tentativa):
                ligacao = Ligacao()
                resposta = ao_idx(ligacao).entregar(corpo(tentativas=tentativa))
                self.assertEqual(resposta, Resposta(503, "adiado", retry_after=segundos))
                self.assertEqual(ligacao.dlq(), [])
                self.assertGreaterEqual(ligacao.rollbacks, 1, "o consumir desfez a marca")

    def test_na_sexta_tentativa_abre_a_dlq_e_responde_200(self) -> None:
        self.falhar = RuntimeError("base em baixo")
        ligacao = Ligacao()
        resposta = ao_idx(ligacao).entregar(corpo(tentativas=TENTATIVAS))
        self.assertEqual(resposta, Resposta(200, "para_dlq"))
        [linha] = ligacao.dlq()
        self.assertEqual(linha[6], MOTIVO_TENTATIVAS_ESGOTADAS)
        self.assertNotIn("base em baixo", json.dumps(linha), "a mensagem do erro nao se escreve")

    def test_adiar_usa_o_atraso_dele_arredondado_para_cima(self) -> None:
        self.falhar = Adiar(segundos=2)
        ligacao = Ligacao()
        self.assertEqual(ao_idx(ligacao).entregar(corpo()), Resposta(503, "adiado", retry_after=2))


class TestArquivo(_ComEfeitoFalso):
    """O *job* do reconciliador traz `envelope: null`: le-se do arquivo."""

    def test_le_o_envelope_do_arquivo_com_o_contexto_da_fila(self) -> None:
        ligacao = Ligacao(arquivo={EVENTO: envelope()})
        self.assertEqual(ao_idx(ligacao).entregar(corpo(envelope=None)), Resposta(200, "aplicado"))
        primeira, segunda = ligacao.instrucoes[0], ligacao.instrucoes[1]
        self.assertIn("set_config", primeira[0])
        self.assertEqual(primeira[1], (TENANT,))
        self.assertIn("platform.events_log", segunda[0])
        self.assertEqual(segunda[1], (EVENTO,))

    def test_o_arquivo_em_texto_tambem_se_le(self) -> None:
        ligacao = Ligacao(arquivo={EVENTO: json.dumps(envelope())})
        self.assertEqual(ao_idx(ligacao).entregar(corpo(envelope=None)), Resposta(200, "aplicado"))

    def test_sem_linha_no_arquivo_repete_e_na_sexta_abre_a_dlq(self) -> None:
        ligacao = Ligacao()
        self.assertEqual(
            ao_idx(ligacao).entregar(corpo(envelope=None)), Resposta(503, "adiado", retry_after=5)
        )
        self.assertEqual(ligacao.dlq(), [])
        ligacao = Ligacao()
        self.assertEqual(
            ao_idx(ligacao).entregar(corpo(envelope=None, tentativas=TENTATIVAS)),
            Resposta(200, "para_dlq"),
        )
        self.assertEqual(ligacao.dlq()[0][6], MOTIVO_TENTATIVAS_ESGOTADAS)
        self.assertEqual(ligacao.dlq()[0][2], TIPO_ILEGIVEL)

    def test_o_arquivo_de_outro_tenant_nao_passa(self) -> None:
        """A RLS ja o esconderia; se o arquivo o devolver, os ponteiros recusam."""
        ligacao = Ligacao(arquivo={EVENTO: envelope(tenant_id=OUTRO)})
        self.assertEqual(ao_idx(ligacao).entregar(corpo(envelope=None)), Resposta(200, "para_dlq"))
        self.assertEqual(self.efeitos, [])


class TestClienteDaLigacao(unittest.TestCase):
    def test_begin_nao_passa_e_commit_e_rollback_traduzem(self) -> None:
        ligacao = Ligacao()
        cliente = ClienteDaLigacao(ligacao)
        cliente.executar("BEGIN")
        cliente.executar("COMMIT")
        cliente.executar("ROLLBACK")
        self.assertEqual(ligacao.instrucoes, [])
        self.assertEqual((ligacao.commits, ligacao.rollbacks), (1, 1))

    def test_controlo_desconhecido_levanta(self) -> None:
        for sql in ("SAVEPOINT a", "START TRANSACTION", "RELEASE a", "END", "ABORT"):
            with self.subTest(sql=sql), self.assertRaises(RuntimeError):
                ClienteDaLigacao(Ligacao()).executar(sql)

    def test_linhas_por_nome_de_coluna(self) -> None:
        resultado = ClienteDaLigacao(Ligacao()).executar("SELECT set_config('x', %s, true)", ("v",))
        self.assertEqual(list(resultado.linhas), [{"set_config": "v"}])


# ----------------------------------------------------------------- o processo


class _Pedido:
    def __init__(self, servidor) -> None:
        self.porta = servidor.server_address[1]

    def __call__(self, metodo: str, caminho: str, corpo_: Any = None, cabecalhos: dict[str, str] | None = None):
        ligacao = http.client.HTTPConnection("127.0.0.1", self.porta, timeout=5)
        dados = None if corpo_ is None else (corpo_ if isinstance(corpo_, bytes) else json.dumps(corpo_).encode())
        ligacao.request(metodo, caminho, body=dados, headers=cabecalhos or {})
        resposta = ligacao.getresponse()
        texto = resposta.read()
        ligacao.close()
        return resposta.status, dict(resposta.getheaders()), texto


class TestRota(_ComEfeitoFalso):
    def setUp(self) -> None:
        super().setUp()
        self.segredo = "s3gredo"
        self.ligacao = Ligacao()
        self.respostas: list[tuple[str, int]] = []
        self.metricas = MetricasDoIdx()
        self.servidor = processo.servidor(
            0,
            ao_idx(self.ligacao),
            lambda: self.segredo,
            metricas=self.metricas,
            ao_responder=lambda o, e: self.respostas.append((o, e)),
        )
        threading.Thread(target=self.servidor.serve_forever, daemon=True).start()
        self.pedir = _Pedido(self.servidor)
        self.com_credencial = {processo.CABECALHO_INTERNO: self.segredo}

    def tearDown(self) -> None:
        self.servidor.shutdown()
        self.servidor.server_close()
        super().tearDown()

    def test_healthz(self) -> None:
        estado, _, texto = self.pedir("GET", "/healthz")
        self.assertEqual(estado, 200)
        self.assertEqual(json.loads(texto)["service"], "idx")

    def test_metrics_de_um_processo_fresco_e_depois_de_uma_volta(self) -> None:
        estado, _, texto = self.pedir("GET", "/metrics")
        self.assertEqual((estado, texto), (200, b""))
        self.metricas.registar_reindexacao(0)
        _, _, texto = self.pedir("GET", "/metrics")
        self.assertIn(f"{METRICA_REINDEXADOS} 0", texto.decode())

    def test_sem_credencial_ou_errada_e_401_e_nao_entrega(self) -> None:
        for cabecalhos in ({}, {processo.CABECALHO_INTERNO: "outra"}):
            with self.subTest(cabecalhos=cabecalhos):
                estado, _, texto = self.pedir("POST", processo.CAMINHO_DO_EVENTO, corpo(), cabecalhos)
                self.assertEqual((estado, json.loads(texto)), (401, {"outcome": "nao_autorizado"}))
        self.assertEqual(self.efeitos, [])

    def test_a_credencial_le_se_a_cada_pedido(self) -> None:
        self.segredo = "rodado"
        estado, _, _ = self.pedir(
            "POST", processo.CAMINHO_DO_EVENTO, corpo(), {processo.CABECALHO_INTERNO: "rodado"}
        )
        self.assertEqual(estado, 200)

    def test_entrega_e_503_com_retry_after(self) -> None:
        estado, _, texto = self.pedir("POST", processo.CAMINHO_DO_EVENTO, corpo(), self.com_credencial)
        self.assertEqual((estado, json.loads(texto)), (200, {"outcome": "aplicado"}))
        self.falhar = RuntimeError("x")
        estado, cabecalhos, _ = self.pedir(
            "POST", processo.CAMINHO_DO_EVENTO, corpo(event_id=str(uuid.uuid4()),
                                                     envelope=None), self.com_credencial
        )
        self.assertEqual((estado, cabecalhos.get("Retry-After")), (503, "5"))
        self.assertEqual(self.respostas[-1], ("adiado", 503))

    def test_json_invalido_e_400(self) -> None:
        estado, _, texto = self.pedir("POST", processo.CAMINHO_DO_EVENTO, b"{nao", self.com_credencial)
        self.assertEqual(estado, 400)
        self.assertEqual(json.loads(texto)["error_code"], "corpo_nao_e_json")

    def test_a_base_que_nao_abre_e_503(self) -> None:
        def abrir():
            raise OSError("recusada")

        servidor = processo.servidor(0, EntregaAoIdx(abrir), lambda: self.segredo)
        threading.Thread(target=servidor.serve_forever, daemon=True).start()
        try:
            estado, cabecalhos, _ = _Pedido(servidor)(
                "POST", processo.CAMINHO_DO_EVENTO, corpo(), self.com_credencial
            )
        finally:
            servidor.shutdown()
            servidor.server_close()
        self.assertEqual((estado, cabecalhos.get("Retry-After")), (503, "5"))

    def test_rota_desconhecida_e_404(self) -> None:
        self.assertEqual(self.pedir("POST", "/internal/turn", corpo(), self.com_credencial)[0], 404)
        self.assertEqual(self.pedir("GET", "/internal/event")[0], 404)


class TestReindexacao(unittest.TestCase):
    def setUp(self) -> None:
        self._original = consumidor.reindexar
        self.chamadas: list[tuple[str, int]] = []
        self.restantes: dict[str, int] = {}

        def reindexar(bd, tenant_id, lote) -> int:
            self.chamadas.append((tenant_id, lote))
            feitos = min(lote, self.restantes.get(tenant_id, 0))
            self.restantes[tenant_id] = self.restantes.get(tenant_id, 0) - feitos
            return feitos

        consumidor.reindexar = reindexar  # type: ignore[assignment]
        self.batch = Ligacao()
        self.batch.responder = lambda sql, p: (["id"], [(TENANT,), (OUTRO,)], 2)  # type: ignore[method-assign]
        self.app = Ligacao()

    def tearDown(self) -> None:
        consumidor.reindexar = self._original  # type: ignore[assignment]

    def ciclo(self, lote: int = 200) -> tuple[processo.Reindexacao, MetricasDoIdx]:
        metricas = MetricasDoIdx()
        return processo.Reindexacao(lambda: self.app, lambda: self.batch, lote, metricas), metricas

    def test_corre_cada_tenant_ate_um_lote_incompleto(self) -> None:
        self.restantes = {TENANT: 450, OUTRO: 0}
        reindexacao, metricas = self.ciclo()
        self.assertEqual(reindexacao.volta(), 450)
        self.assertEqual(
            self.chamadas, [(TENANT, 200), (TENANT, 200), (TENANT, 200), (OUTRO, 200)]
        )
        self.assertEqual(metricas.ler()[METRICA_REINDEXADOS], 450)

    def test_a_lista_de_tenants_e_do_kamba_batch_com_o_nome_do_job(self) -> None:
        reindexacao, _ = self.ciclo()
        self.assertEqual(reindexacao.tenants(), [TENANT, OUTRO])
        self.assertEqual(len(self.batch.instrucoes), 1)
        self.assertIn("estado = 'ativo'", self.batch.instrucoes[0][0])
        self.assertTrue(self.batch.fechada)

    def test_cada_lote_e_uma_transaccao_com_o_contexto_do_tenant(self) -> None:
        self.restantes = {TENANT: 250, OUTRO: 0}
        reindexacao, _ = self.ciclo()
        reindexacao.volta()
        contextos = [p for s, p in self.app.instrucoes if "set_config" in s]
        self.assertEqual(contextos, [(TENANT,), (TENANT,), (OUTRO,)])
        self.assertEqual(self.app.commits, 3)

    def test_uma_volta_em_dia_conta_zero(self) -> None:
        reindexacao, metricas = self.ciclo()
        self.assertEqual(reindexacao.volta(), 0)
        self.assertEqual(metricas.ler()[METRICA_REINDEXADOS], 0)

    def test_o_tecto_de_lotes_por_volta(self) -> None:
        self.restantes = {TENANT: 10**9, OUTRO: 0}
        reindexacao, _ = self.ciclo(lote=1)
        self.assertEqual(reindexacao.do_tenant(TENANT), processo.LOTES_POR_VOLTA)

    def test_o_ciclo_sobrevive_a_uma_volta_que_falha(self) -> None:
        parar = threading.Event()
        falhas: list[BaseException] = []
        voltas: list[int] = []
        class Falha(processo.Reindexacao):
            __slots__ = ()

            def volta(self, ao_falhar=None) -> int:  # noqa: ARG002
                voltas.append(1)
                if len(voltas) == 1:
                    raise OSError("base em baixo")
                parar.set()
                return 0

        Falha(lambda: self.app, lambda: self.batch).correr(parar, 0, falhas.append)
        self.assertEqual(len(voltas), 2)
        self.assertEqual(len(falhas), 1)

    def test_lote_invalido_recusa(self) -> None:
        for lote in (0, -1, True, "200"):
            with self.subTest(lote=lote), self.assertRaises(ValueError):
                processo.Reindexacao(lambda: self.app, lambda: self.batch, lote)  # type: ignore[arg-type]


class TestUmTenantQueFalha(TestReindexacao):
    def test_os_seguintes_correm_e_a_falha_vai_ao_ao_falhar(self) -> None:
        self.restantes = {TENANT: 0, OUTRO: 30}
        original = consumidor.reindexar

        def reindexar(bd, tenant_id, lote) -> int:
            if tenant_id == TENANT:
                raise RuntimeError("lexico ilegivel")
            return original(bd, tenant_id, lote)

        consumidor.reindexar = reindexar  # type: ignore[assignment]
        falhas: list[BaseException] = []
        reindexacao, metricas = self.ciclo()
        self.assertEqual(reindexacao.volta(falhas.append), 30)
        self.assertEqual(len(falhas), 1)
        self.assertEqual(metricas.ler()[METRICA_REINDEXADOS], 30)


class TestLigadores(unittest.TestCase):
    """O papel de cada ligacao do processo: as entregas nao correm sem RLS."""

    def test_entrega_e_kamba_app_e_a_lista_e_kamba_batch(self) -> None:
        import sys
        import types

        from kamba_core.idx import __main__ as entrada

        chamadas: list[dict] = []

        class _Ligacao:
            autocommit = True

        falso = types.ModuleType("pg8000.dbapi")
        falso.connect = lambda **k: (chamadas.append(k), _Ligacao())[1]  # type: ignore[attr-defined]
        pacote = types.ModuleType("pg8000")
        pacote.dbapi = falso  # type: ignore[attr-defined]
        antes = {n: sys.modules.get(n) for n in ("pg8000", "pg8000.dbapi")}
        sys.modules.update({"pg8000": pacote, "pg8000.dbapi": falso})
        try:
            ambiente = {
                entrada.VAR_BASE: "kamba_platform",
                entrada.VAR_SENHA_APP: "a",
                entrada.VAR_SENHA_BATCH: "b",
            }
            abrir_app, abrir_batch = entrada.ligadores(ambiente)
            self.assertFalse(abrir_app().autocommit, "o tenant_guard exige transaccao")
            abrir_batch()
        finally:
            for nome, modulo in antes.items():
                if modulo is None:
                    sys.modules.pop(nome, None)
                else:
                    sys.modules[nome] = modulo
        self.assertEqual([(c["user"], c["password"]) for c in chamadas],
                         [("kamba_app", "a"), ("kamba_batch", "b")])

    def test_a_dlq_vai_a_registo_e_o_caminho_feliz_nao(self) -> None:
        from kamba_core.idx.__main__ import deve_registar

        self.assertTrue(deve_registar("para_dlq", 200))
        self.assertTrue(deve_registar("adiado", 503))
        self.assertFalse(deve_registar("aplicado", 200))
        self.assertFalse(deve_registar("duplicado", 200))


class TestCicloDeEmbeddings(unittest.TestCase):
    """O *worker* do KAM-063 em ciclo: o cursor, o documento envenenado e a porta.

    O `embeber_catalogo` troca-se por um falso sobre uma lista de `doc_id`s, que
    respeita o cursor e o lote como o SQL dele e falha quando o lote contem um
    documento envenenado — e assim que uma chamada ao fornecedor falha.
    """

    def setUp(self) -> None:
        from kamba_core.idx import embeddings

        self.embeddings = embeddings
        self._original = embeddings.embeber_catalogo
        self.docs = [f"d{i:03d}" for i in range(10)]
        self.envenenados: set[str] = set()
        self.negado = False
        self.gravados: list[str] = []
        self.chamadas: list[tuple[str | None, int]] = []

        def falso(bd, tenant_id, cliente, modelo, *, depois_de=None, lote=64, tecto_s=20.0):
            self.chamadas.append((depois_de, lote))
            resto = [d for d in self.docs if depois_de is None or d > depois_de][:lote]
            if not resto:
                return embeddings.VoltaDoCatalogo(0, 0, 0, None)
            if self.negado:
                return embeddings.VoltaDoCatalogo(len(resto), 0, 0, resto[-1], embeddings.QUEDA_DESTINO)
            if self.envenenados & set(resto):
                return embeddings.VoltaDoCatalogo(len(resto), 0, 0, resto[-1], embeddings.QUEDA_FALHA)
            self.gravados.extend(resto)
            return embeddings.VoltaDoCatalogo(len(resto), len(resto), 0, resto[-1])

        embeddings.embeber_catalogo = falso  # type: ignore[assignment]
        self.app = Ligacao()

    def tearDown(self) -> None:
        self.embeddings.embeber_catalogo = self._original  # type: ignore[assignment]

    def ciclo(self, lote: int = 4, isolados: list | None = None) -> processo.CicloDeEmbeddings:
        return processo.CicloDeEmbeddings(
            lambda: self.app, cliente=object(), modelo="m", lote=lote,
            ao_isolar=None if isolados is None else isolados.append,
        )

    def test_segue_o_cursor_ate_ao_fim(self) -> None:
        self.assertEqual(self.ciclo().do_tenant(TENANT), (10, 0))
        self.assertEqual(self.gravados, self.docs)
        contextos = [p for s, p in self.app.instrucoes if "set_config" in s]
        self.assertTrue(contextos and all(c == (TENANT,) for c in contextos))
        self.assertTrue(self.app.fechada)

    def test_um_envenenado_isola_se_e_o_resto_do_lote_grava(self) -> None:
        self.envenenados = {"d005"}
        isolados: list = []
        self.assertEqual(self.ciclo(isolados=isolados).do_tenant(TENANT), (9, 1))
        self.assertEqual(sorted(self.gravados), [d for d in self.docs if d != "d005"])
        self.assertEqual(isolados, ["falha"])

    def test_a_porta_negada_para_o_tenant_sem_isolar_nada(self) -> None:
        self.negado = True
        isolados: list = []
        self.assertEqual(self.ciclo(isolados=isolados).do_tenant(TENANT), (0, 0))
        self.assertEqual(len(self.chamadas), 1, "nao insiste num tenant sem destino")
        self.assertEqual(isolados, [])

    def test_com_lote_de_um_o_envenenado_salta_se(self) -> None:
        self.envenenados = {"d000"}
        self.assertEqual(self.ciclo(lote=1).do_tenant(TENANT), (9, 1))

    def test_a_reindexacao_chama_os_embeddings_de_cada_tenant(self) -> None:
        vistos: list[str] = []

        class Espiao:
            def do_tenant(self, tenant_id: str) -> tuple[int, int]:
                vistos.append(tenant_id)
                return (0, 0)

        original = consumidor.reindexar
        consumidor.reindexar = lambda bd, t, lote: 0  # type: ignore[assignment]
        try:
            batch = Ligacao()
            batch.responder = lambda sql, p: (["id"], [(TENANT,), (OUTRO,)], 2)  # type: ignore[method-assign]
            processo.Reindexacao(
                lambda: Ligacao(), lambda: batch, embeddings=Espiao()  # type: ignore[arg-type]
            ).volta()
        finally:
            consumidor.reindexar = original  # type: ignore[assignment]
        self.assertEqual(vistos, [TENANT, OUTRO])


class TestConfiguracao(unittest.TestCase):
    def test_omissao_valor_e_recusa(self) -> None:
        self.assertEqual(processo.configuracao_inteira({}, "X", 60), 60)
        self.assertEqual(processo.configuracao_inteira({"X": " 30 "}, "X", 60), 30)
        for mau in ("0", "-1", "dez", "1.5"):
            with self.subTest(mau=mau), self.assertRaises(ValueError):
                processo.configuracao_inteira({"X": mau}, "X", 60)


class TestMetricaDaReindexacao(unittest.TestCase):
    def test_soma_e_nao_aceita_negativo(self) -> None:
        metricas = MetricasDoIdx()
        self.assertNotIn(METRICA_REINDEXADOS, metricas.ler())
        metricas.registar_reindexacao(3)
        metricas.registar_reindexacao(4)
        self.assertEqual(metricas.ler()[METRICA_REINDEXADOS], 7)
        for mau in (-1, True, 1.0):
            with self.subTest(mau=mau), self.assertRaises(ValueError):
                metricas.registar_reindexacao(mau)  # type: ignore[arg-type]
        self.assertIn("# TYPE idx_reindexed_total counter", metricas.exposicao())
        metricas.repor()
        self.assertEqual(metricas.exposicao(), "")


if __name__ == "__main__":
    unittest.main()
