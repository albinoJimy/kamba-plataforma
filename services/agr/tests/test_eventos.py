"""A subscricao de eventos: os oito criterios do KAM-038, um a um.

A bateria corre **sem** PostgreSQL, sem Redis e sem Outbound, pela razao que o
`consumo.py` do KAM-006 escreve: com os clientes injectados, a transaccao e a
decisao testam-se inteiras, e o que a *suite* do *gate* 8 prova e o que so a
base pode provar — que o SQL corre, que o indice parcial existe e que a RLS
recusa.

A base falsa esta em `base_de_eventos.py`, e a *docstring* dela diz o que ela
nao modela. Vale ler antes de ler isto.
"""

from __future__ import annotations

import asyncio
import functools
import json
import re
import unittest
from pathlib import Path

from kamba_agr import metricas as m
from kamba_agr.eventos import (
    consumo,
    desfechos,
    dlq,
    envelope as env,
    handlers,
    notificacao as notif,
    subscricoes,
    turnos,
)
from kamba_agr.eventos.consumo import ConsumidorDeEventos, EntregaPorRepetir
from kamba_agr.registo import carregar
from kamba_agr.registo.validar import AmbienteDoRegisto
from kamba_core.eventos import TENTATIVAS

from base_de_eventos import (
    ContactoFixo,
    HndEspiao,
    LinhaDaConversa,
    OutboundEspiao,
    Servidor,
    TrancaFalsa,
)

RAIZ = Path(__file__).resolve().parents[3]
REGISTO = RAIZ / "registry"
ENVELOPE_TS = RAIZ / "packages" / "core-ts" / "src" / "eventos" / "envelope.ts"

TENANT = "3f1c2a9e-0d4b-4e55-9a7c-1b2c3d4e5f60"
OUTRO_TENANT = "11111111-2222-4333-8444-555555555555"
CONTACTO = "9b2f6c1a-7e3d-4c80-b5a1-2d9e8f7a6b50"
CONVERSA = "aaaaaaaa-bbbb-4ccc-8ddd-eeeeeeeeeeee"
EVENTO = "0192f1c4-7b1e-7d2a-9c3e-5a1f0b6e2d44"


def envelope_cru(**mudancas) -> dict:
    """Um envelope v1 valido de `payment.confirmed`, com os catorze campos."""
    base = {
        "id": EVENTO,
        "tipo": "payment.confirmed",
        "versao": 1,
        "tenant_id": TENANT,
        "ocorrido_em": "2026-11-02T14:03:11.482+00:00",
        "registado_em": "2026-11-02T14:03:11.610+00:00",
        "produtor": "pay-core@1.4.2",
        "agregado": {"tipo": "order", "id": CONTACTO, "seq": 3},
        "correlacao_id": None,
        "causa_id": None,
        "trace_id": "4bf92f3577b34da6a3ce929d0e0e4736",
        "classe_pii": "P0",
        "finalidades": ["transacao"],
        "payload": {
            "order_id": CONTACTO,
            "provider": "facilitador_x",
            "referencia": "102345678",
            "valor_minor": 24500000,
            "currency": "AOA",
            "autenticacao": {"authn_ok": True},
        },
    }
    base.update(mudancas)
    return base


def corpo(envelope: dict | str | None = None, tentativas: int = 1, **mudancas) -> dict:
    bruto = envelope_cru() if envelope is None else envelope
    pedido = {
        "event_id": EVENTO,
        "tenant_id": TENANT,
        "envelope": bruto,
        "tentativas": tentativas,
    }
    pedido.update(mudancas)
    return pedido


def ambiente_do_registo() -> AmbienteDoRegisto:
    """O ambiente real, com o catalogo da ToolLayer ligado.

    Sem o catalogo, a validacao (1) do §5.2 devolve `PorLigar` e o `carregar`
    reprova — a mesma linha que o `__main__.py` do KAM-028 escreve. Nao se
    desliga a validacao: liga-se o catalogo, que e o que corre em producao.
    """
    from kamba_agr.tls.catalogo import catalogo_do_piloto

    return AmbienteDoRegisto.do_repositorio(
        REGISTO.parent, catalogo=catalogo_do_piloto()
    )


@functools.lru_cache(maxsize=1)
def tabela_do_registo() -> tuple[subscricoes.Consumidor, ...]:
    """A tabela de consumidores dos `registry/*.yaml` **reais**.

    De proposito contra os ficheiros do repositorio e nao contra um duplo: o
    criterio 1 fala das `subscriptions` que la estao, e um duplo media um
    registo inventado. Em cache porque a leitura do registo abre quatro
    ficheiros e corre seis validacoes, e esta bateria chama-a por teste.
    """
    ambiente = ambiente_do_registo()
    verticais, _, _ = carregar(ambiente, REGISTO)
    return subscricoes.consumidores(verticais, ambiente)


# ===========================================================================
# Criterio 1 — um consumidor por cada `subscriptions`; desconhecidos reprovam
# ===========================================================================


class TestCriterio1Subscricoes(unittest.TestCase):
    def setUp(self) -> None:
        self.tabela = tabela_do_registo()

    def test_ha_um_consumidor_por_cada_subscricao_do_registo(self) -> None:
        ambiente = ambiente_do_registo()
        verticais, _, _ = carregar(ambiente, REGISTO)
        esperadas = {
            (vertical.id, s.tipo, s.versao)
            for vertical in verticais.values()
            for s in vertical.subscriptions
        }
        registados = {(c.vertical, c.tipo, c.versao) for c in self.tabela}
        self.assertEqual(registados, esperadas)
        self.assertTrue(esperadas, "o registo tem de ter subscricoes")

    def test_o_consumer_e_um_por_vertical_e_derivado_do_id(self) -> None:
        """Um por vertical, e nao um por `(vertical, tipo)`: §3.33."""
        self.assertEqual(
            set(subscricoes.nomes(self.tabela)), {"agr_vendedor", "agr_servicos"}
        )
        for consumidor in self.tabela:
            self.assertEqual(consumidor.nome, f"agr_{consumidor.vertical}")

    def test_o_nome_do_consumidor_casa_a_gramatica_de_etiqueta(self) -> None:
        """E eixo de `agr_evt_lag_ms`: um nome que nao case levanta."""
        for nome in subscricoes.nomes(self.tabela):
            self.assertRegex(nome, m.ETIQUETA)

    def test_os_dois_eventos_de_pagamento_estao_nas_duas_verticais(self) -> None:
        """Criterio 9: `payment.manual_confirmed` v1 em ambas."""
        for tipo in ("payment.confirmed", "payment.manual_confirmed"):
            verticais = {c.vertical for c in self.tabela if c.tipo == tipo}
            self.assertEqual(verticais, {"vendedor", "servicos"}, tipo)

    def test_os_de_pagamento_exigem_ordem_e_tem_prioridade(self) -> None:
        for consumidor in self.tabela:
            de_pagamento = consumidor.tipo.startswith("payment.")
            self.assertEqual(consumidor.exige_ordem, de_pagamento, consumidor.tipo)
            self.assertEqual(consumidor.prioritario, de_pagamento, consumidor.tipo)

    def test_um_tipo_sem_contrato_reprova(self) -> None:
        ambiente = ambiente_do_registo()
        verticais, _, _ = carregar(ambiente, REGISTO)
        vendedor = verticais["vendedor"]
        inventado = vendedor.model_copy(
            update={
                "subscriptions": (
                    *vendedor.subscriptions,
                    type(vendedor.subscriptions[0])(tipo="nada.disto", versao=1),
                )
            }
        )
        with self.assertRaises(subscricoes.SubscricoesInvalidasError) as erro:
            subscricoes.consumidores({"vendedor": inventado}, ambiente)
        self.assertIn("nada.disto", str(erro.exception))

    def test_uma_versao_sem_contrato_reprova(self) -> None:
        ambiente = ambiente_do_registo()
        verticais, _, _ = carregar(ambiente, REGISTO)
        vendedor = verticais["vendedor"]
        inventado = vendedor.model_copy(
            update={
                "subscriptions": (
                    type(vendedor.subscriptions[0])(tipo="payment.confirmed", versao=9),
                )
            }
        )
        with self.assertRaises(subscricoes.SubscricoesInvalidasError) as erro:
            subscricoes.consumidores({"vendedor": inventado}, ambiente)
        self.assertIn("v9", str(erro.exception))

    def test_a_validacao_e_a_do_kam_027_e_nao_uma_segunda(self) -> None:
        """O modulo chama `validar_subscriptions`; nao reimplementa o catalogo."""
        fonte = Path(subscricoes.__file__).read_text(encoding="utf-8")
        self.assertIn("validar_subscriptions", fonte)
        # **Nao importa o catalogo.** A frase «partilha a validacao de KAM-027»
        # mede-se assim e nao pela palavra `CATALOGO`, que aparece na prosa a
        # explicar de onde ela vem: o que torna a validacao **a mesma** e nao
        # haver aqui um segundo caminho ate ao catalogo.
        # Linhas de importacao **em qualquer indentacao**: as do `metricas.py`
        # vivem dentro de funcoes, e um filtro por `startswith` sem `strip`
        # deixava passar exactamente essa forma.
        importacoes = [
            linha
            for linha in fonte.splitlines()
            if linha.strip().startswith(("from ", "import "))
        ]
        self.assertFalse([l for l in importacoes if "contratos" in l], importacoes)

    def test_todas_as_subscricoes_do_registo_tem_handler(self) -> None:
        """A outra metade do criterio 1: contrato **e** codigo, por vertical."""
        handlers.exigir_handlers(tuple((c.vertical, c.tipo) for c in self.tabela))

    def test_um_par_sem_handler_reprova_o_arranque(self) -> None:
        with self.assertRaises(handlers.SemHandlerError) as erro:
            handlers.exigir_handlers(
                (("vendedor", "payment.confirmed"), ("vendedor", "tenant.approved"))
            )
        self.assertIn("tenant.approved", str(erro.exception))

    def test_o_mesmo_tipo_noutra_vertical_e_outro_handler(self) -> None:
        """**E a correccao do defeito que a revisao adversarial encontrou.**

        Com a chave no tipo, um *tenant* com as duas verticais activas recebia a
        **mesma** mensagem duas vezes sobre o mesmo pagamento.
        """
        self.assertTrue(handlers.fala_com_o_cliente("vendedor", "payment.confirmed"))
        self.assertFalse(handlers.fala_com_o_cliente("servicos", "payment.confirmed"))
        self.assertEqual(
            handlers.accao_por_ligar("servicos", "payment.confirmed"), "KAM-047"
        )
        self.assertIsNone(handlers.accao_por_ligar("vendedor", "payment.confirmed"))

    def test_uma_vertical_sem_subscricoes_nao_e_problema(self) -> None:
        ambiente = ambiente_do_registo()
        verticais, _, _ = carregar(ambiente, REGISTO)
        muda = verticais["vendedor"].model_copy(update={"subscriptions": ()})
        self.assertEqual(subscricoes.consumidores({"vendedor": muda}, ambiente), ())


# ===========================================================================
# O envelope (`docs/tecnica/06` §4)
# ===========================================================================


class TestEnvelope(unittest.TestCase):
    def test_os_catorze_campos_e_a_ordem_sao_os_do_typescript(self) -> None:
        """Paridade com `envelope.ts`, lida como texto. Duas listas da mesma
        forma so se mantem honestas se houver uma maquina a confronta-las."""
        fonte = ENVELOPE_TS.read_text(encoding="utf-8")
        achado = re.search(r"CAMPOS_DO_ENVELOPE = \[(.*?)\] as const;", fonte, re.S)
        self.assertIsNotNone(achado)
        do_ts = tuple(re.findall(r'"([a-z_]+)"', achado.group(1)))
        self.assertEqual(do_ts, env.CAMPOS_DO_ENVELOPE)
        self.assertEqual(len(env.CAMPOS_DO_ENVELOPE), 14)

    def test_le_um_envelope_valido(self) -> None:
        envelope = env.ler_envelope(envelope_cru())
        self.assertEqual(envelope.id, EVENTO)
        self.assertEqual(envelope.agregado.seq, 3)
        self.assertEqual(envelope.finalidades, ("transacao",))

    def test_le_tambem_o_texto_json(self) -> None:
        envelope = env.ler_envelope(json.dumps(envelope_cru()))
        self.assertEqual(envelope.tipo, "payment.confirmed")

    def test_recusa_campo_de_topo_desconhecido(self) -> None:
        with self.assertRaises(env.EnvelopeInvalidoError) as erro:
            env.ler_envelope(envelope_cru(extra=1))
        self.assertIn("desconhecido", str(erro.exception))

    def test_recusa_campo_de_topo_em_falta(self) -> None:
        bruto = envelope_cru()
        del bruto["trace_id"]
        with self.assertRaises(env.EnvelopeInvalidoError) as erro:
            env.ler_envelope(bruto)
        self.assertIn("em falta", str(erro.exception))

    def test_recusa_classe_pii_p2(self) -> None:
        with self.assertRaises(env.EnvelopeInvalidoError) as erro:
            env.ler_envelope(envelope_cru(classe_pii="P2"))
        self.assertIn("P2", str(erro.exception))

    def test_recusa_classe_pii_desconhecida(self) -> None:
        with self.assertRaises(env.EnvelopeInvalidoError):
            env.ler_envelope(envelope_cru(classe_pii="P9"))

    def test_recusa_finalidades_vazias(self) -> None:
        with self.assertRaises(env.EnvelopeInvalidoError):
            env.ler_envelope(envelope_cru(finalidades=[]))

    def test_recusa_tipo_fora_da_gramatica(self) -> None:
        for tipo in ("Payment.Confirmed", "payment", "payment.", "1.x"):
            with self.subTest(tipo=tipo), self.assertRaises(env.EnvelopeInvalidoError):
                env.ler_envelope(envelope_cru(tipo=tipo))

    def test_recusa_uuid_que_nao_e_uuid(self) -> None:
        with self.assertRaises(env.EnvelopeInvalidoError):
            env.ler_envelope(envelope_cru(tenant_id="nao-e-uuid"))

    def test_recusa_seq_booleano(self) -> None:
        """`True` e um `int` em Python: um `seq` que valha `True` nao e um seq."""
        with self.assertRaises(env.EnvelopeInvalidoError):
            env.ler_envelope(
                envelope_cru(agregado={"tipo": "order", "id": CONTACTO, "seq": True})
            )

    def test_recusa_seq_zero(self) -> None:
        with self.assertRaises(env.EnvelopeInvalidoError):
            env.ler_envelope(
                envelope_cru(agregado={"tipo": "order", "id": CONTACTO, "seq": 0})
            )

    def test_recusa_campo_desconhecido_no_agregado(self) -> None:
        with self.assertRaises(env.EnvelopeInvalidoError) as erro:
            env.ler_envelope(
                envelope_cru(
                    agregado={"tipo": "order", "id": CONTACTO, "seq": 1, "x": 1}
                )
            )
        self.assertIn("agregado", str(erro.exception))

    def test_recusa_o_que_nao_e_json(self) -> None:
        with self.assertRaises(env.EnvelopeInvalidoError):
            env.ler_envelope("{isto nao e json")

    def test_a_mensagem_nunca_repete_um_valor_recusado(self) -> None:
        """Um envelope invalido pode trazer um telefone no sitio de um UUID."""
        with self.assertRaises(env.EnvelopeInvalidoError) as erro:
            env.ler_envelope(envelope_cru(tenant_id="+244923000000"))
        self.assertNotIn("244923000000", str(erro.exception))

    def test_como_mapa_devolve_a_forma_que_o_consumir_le(self) -> None:
        mapa = env.ler_envelope(envelope_cru()).como_mapa()
        self.assertEqual(set(mapa), set(env.CAMPOS_DO_ENVELOPE))
        self.assertEqual(mapa["agregado"]["seq"], 3)


# ===========================================================================
# Criterio 2 — idempotencia por `evento.id`, inclusive em paralelo; DLQ
# ===========================================================================


def monta(
    servidor: Servidor,
    *,
    outbound: OutboundEspiao | None = None,
    hnd: HndEspiao | None = None,
    tranca: TrancaFalsa | None = None,
    contactos=None,
    tabela: tuple[subscricoes.Consumidor, ...] | None = None,
    relogio=None,
    aviso_da_dlq=None,
) -> ConsumidorDeEventos:
    """Um consumidor sobre a base falsa, com so o Vendedor activo.

    So o Vendedor por omissao porque e o que o §5.2 descreve — «uma so vertical
    principal por numero no Piloto» — e porque com as duas o mesmo pagamento
    tem dois consumidores, que e o caso que a sua propria bateria mede.
    """
    if tabela is None:
        tabela = tuple(c for c in tabela_do_registo() if c.vertical == "vendedor")
    return ConsumidorDeEventos(
        tabela=tabela,
        trancas=tranca or TrancaFalsa(),
        conversas=turnos.LeitorDeConversas(servidor.abrir),
        abrir_ligacao=servidor.abrir,
        fila_de_mortos=dlq.FilaDeMortos(
            servidor.abrir, metricas=m.METRICAS, aviso=aviso_da_dlq
        ),
        notificador=notif.Notificador(
            cliente=outbound or OutboundEspiao(),
            dono=hnd or HndEspiao(),
            metricas=m.METRICAS,
        ),
        ler_entitlement=_entitlement(servidor),
        contactos=contactos or ContactoFixo(CONTACTO),
        metricas=m.METRICAS,
        relogio=relogio or (lambda: 1_793_000_000.0),
    )


def _entitlement(servidor: Servidor):
    from kamba_agr.eventos.entitlement import LeitorDeEntitlements

    return LeitorDeEntitlements(servidor.abrir).ler


def com_conversa(**mudancas) -> Servidor:
    servidor = Servidor()
    servidor.conversas.append(
        LinhaDaConversa(
            id=CONVERSA,
            tenant_id=TENANT,
            contact_id=CONTACTO,
            last_inbound_at=10.0,
            **mudancas,
        )
    )
    return servidor


class TestCriterio2Idempotencia(unittest.TestCase):
    def setUp(self) -> None:
        m.METRICAS.repor()

    def test_cinco_entregas_em_serie_dao_um_efeito_e_uma_linha(self) -> None:
        servidor = com_conversa()
        outbound = OutboundEspiao()
        consumidor = monta(servidor, outbound=outbound)
        desfechos_vistos = [
            asyncio.run(consumidor.entregar(corpo())).desfecho for _ in range(5)
        ]
        self.assertEqual(
            desfechos_vistos,
            ["aplicado", "duplicado", "duplicado", "duplicado", "duplicado"],
        )
        self.assertEqual(len(outbound.chamadas), 1)
        self.assertEqual(len(servidor.consumidos), 1)

    def test_cinco_entregas_em_paralelo_dao_um_efeito_e_uma_linha(self) -> None:
        servidor = com_conversa()
        outbound = OutboundEspiao()
        consumidor = monta(servidor, outbound=outbound)

        async def todas():
            return await asyncio.gather(
                *(consumidor.entregar(corpo()) for _ in range(5))
            )

        resultados = asyncio.run(todas())
        self.assertEqual(
            sorted(r.desfecho for r in resultados),
            ["aplicado", "duplicado", "duplicado", "duplicado", "duplicado"],
        )
        self.assertEqual(len(outbound.chamadas), 1)
        self.assertEqual(len(servidor.consumidos), 1)

    def test_a_chave_de_idempotencia_e_a_do_paragrafo_6_3(self) -> None:
        servidor = com_conversa()
        outbound = OutboundEspiao()
        asyncio.run(monta(servidor, outbound=outbound).entregar(corpo()))
        self.assertEqual(
            outbound.chamadas[0]["chave"], f"agr_vendedor:{EVENTO}:notificar_cliente"
        )

    def test_a_chave_nao_muda_com_a_tentativa(self) -> None:
        """Uma chave com a tentativa dentro dava mensagem nova em cada volta."""
        self.assertEqual(
            notif.chave_da_accao("agr_vendedor", EVENTO, notif.ACCAO_AO_CLIENTE),
            f"agr_vendedor:{EVENTO}:notificar_cliente",
        )

    def test_uma_notificacao_que_levanta_nao_deixa_marca(self) -> None:
        """O efeito e a marca na mesma transaccao: sem efeito, sem marca."""

        class Rebenta:
            def notificar(self, **_argumentos):
                raise RuntimeError("o outbound caiu")

        servidor = com_conversa()
        consumidor = monta(servidor, outbound=Rebenta())
        with self.assertRaises(EntregaPorRepetir):
            asyncio.run(consumidor.entregar(corpo()))
        self.assertEqual(servidor.consumidos, {})

    def test_depois_de_falhar_a_entrega_seguinte_aplica(self) -> None:
        servidor = com_conversa()

        class Instavel:
            def __init__(self) -> None:
                self.vezes = 0

            def notificar(self, **_argumentos):
                self.vezes += 1
                if self.vezes == 1:
                    raise RuntimeError("o outbound caiu")
                return "livre"

        outbound = Instavel()
        consumidor = monta(servidor, outbound=outbound)
        with self.assertRaises(EntregaPorRepetir):
            asyncio.run(consumidor.entregar(corpo()))
        self.assertEqual(
            asyncio.run(consumidor.entregar(corpo(tentativas=2))).desfecho, "aplicado"
        )
        self.assertEqual(outbound.vezes, 2)

    def test_dlq_depois_das_seis_tentativas(self) -> None:
        class Rebenta:
            def notificar(self, **_argumentos):
                raise RuntimeError("o outbound caiu")

        servidor = com_conversa()
        consumidor = monta(servidor, outbound=Rebenta())
        for tentativa in range(1, TENTATIVAS):
            with self.assertRaises(EntregaPorRepetir):
                asyncio.run(consumidor.entregar(corpo(tentativas=tentativa)))
            self.assertEqual(servidor.dlq, [])
        desfecho = asyncio.run(consumidor.entregar(corpo(tentativas=TENTATIVAS)))
        self.assertEqual(desfecho.desfecho, "para_dlq")
        self.assertEqual(len(servidor.dlq), 1)
        self.assertEqual(servidor.dlq[0]["erro"], "tentativas_esgotadas")
        self.assertEqual(servidor.dlq[0]["consumer"], "agr_vendedor")

    def test_as_seis_tentativas_sao_as_do_kam_006(self) -> None:
        """1 + 5 (§6.4). O numero nao se escreve aqui: deriva-se da escada."""
        self.assertEqual(TENTATIVAS, 6)

    def test_o_atraso_da_retentativa_vem_da_escada_do_paragrafo_6_4(self) -> None:
        from kamba_core.eventos import ESCADA_DO_CONSUMIDOR

        class Rebenta:
            def notificar(self, **_argumentos):
                raise RuntimeError("caiu")

        consumidor = monta(com_conversa(), outbound=Rebenta())
        with self.assertRaises(EntregaPorRepetir) as erro:
            asyncio.run(consumidor.entregar(corpo(tentativas=2)))
        self.assertEqual(erro.exception.atraso_ms, ESCADA_DO_CONSUMIDOR[1])

    def test_a_reentrada_na_dlq_nao_abre_segunda_entrada(self) -> None:
        class Rebenta:
            def notificar(self, **_argumentos):
                raise RuntimeError("caiu")

        servidor = com_conversa()
        consumidor = monta(servidor, outbound=Rebenta())
        for _ in range(3):
            asyncio.run(consumidor.entregar(corpo(tentativas=TENTATIVAS)))
        self.assertEqual(len(servidor.dlq), 1)


class TestCriterio2SemTranca(unittest.TestCase):
    """O caminho que **nao** toma tranca, em paralelo.

    O ensaio de cinco entregas concorrentes de `payment.confirmed` serializa na
    tranca da conversa, pelo que so uma esta na secção critica de cada vez —
    mede a tranca e nao a marca. Um aviso ao dono nao toma tranca nenhuma, e por
    isso e aqui que as cinco chegam **juntas** ao `ON CONFLICT`. Achado da
    revisao adversarial.
    """

    def setUp(self) -> None:
        m.METRICAS.repor()

    def _stock_baixo(self) -> dict:
        return envelope_cru(
            tipo="stock.low",
            payload={"sku": "ABC", "qty": 2},
            agregado={"tipo": "product", "id": "ABC", "seq": 1},
        )

    def test_cinco_avisos_ao_dono_em_paralelo_sem_tranca_dao_um_efeito(self) -> None:
        servidor = com_conversa()
        tranca = TrancaFalsa()
        hnd = HndEspiao()
        consumidor = monta(servidor, hnd=hnd, tranca=tranca)
        envelope = self._stock_baixo()

        async def todas():
            return await asyncio.gather(
                *(consumidor.entregar(corpo(envelope)) for _ in range(5))
            )

        resultados = asyncio.run(todas())
        self.assertEqual(tranca.tomadas, [])
        self.assertEqual(
            sorted(r.desfecho for r in resultados),
            ["aplicado", "duplicado", "duplicado", "duplicado", "duplicado"],
        )
        self.assertEqual(len(hnd.chamadas), 1)
        self.assertEqual(len(servidor.consumidos), 1)


# ===========================================================================
# Criterio 3 — versao desconhecida falha visivel, DLQ e alerta
# ===========================================================================


class TestCriterio3VersaoDesconhecida(unittest.TestCase):
    def setUp(self) -> None:
        m.METRICAS.repor()
        self.avisos: list[tuple[str, str]] = []

    def _consumidor(self, servidor: Servidor) -> ConsumidorDeEventos:
        return monta(
            servidor,
            aviso_da_dlq=lambda onde, motivo: self.avisos.append((onde, motivo)),
        )

    def test_versao_desconhecida_vai_para_a_dlq_com_alerta(self) -> None:
        servidor = com_conversa()
        consumidor = self._consumidor(servidor)
        desfecho = asyncio.run(
            consumidor.entregar(corpo(envelope_cru(versao=2)))
        )
        self.assertEqual(desfecho.desfecho, "para_dlq")
        self.assertEqual(servidor.dlq[0]["erro"], "versao_desconhecida")
        self.assertIn(("evt_dlq", "versao_desconhecida"), self.avisos)
        self.assertEqual(m.METRICAS.ler()["agr_evt_dlq_total:versao_desconhecida"], 1)

    def test_versao_desconhecida_nao_notifica_ninguem(self) -> None:
        servidor = com_conversa()
        outbound = OutboundEspiao()
        consumidor = monta(servidor, outbound=outbound)
        asyncio.run(consumidor.entregar(corpo(envelope_cru(versao=2))))
        self.assertEqual(outbound.chamadas, [])

    def test_versao_desconhecida_nao_e_silencio_nem_sucesso(self) -> None:
        """O que o criterio proibe e o `aplicado` e o nada."""
        servidor = com_conversa()
        desfecho = asyncio.run(monta(servidor).entregar(corpo(envelope_cru(versao=2))))
        self.assertNotEqual(desfecho.desfecho, "aplicado")
        self.assertEqual(len(servidor.dlq), 1)

    def test_tipo_sem_subscricao_e_outro_motivo(self) -> None:
        """Dois motivos porque mandam olhar para sitios diferentes."""
        servidor = com_conversa()
        consumidor = self._consumidor(servidor)
        asyncio.run(
            consumidor.entregar(
                corpo(
                    envelope_cru(
                        tipo="tenant.approved", payload={"plano": "x"}, versao=1
                    )
                )
            )
        )
        self.assertEqual(servidor.dlq[0]["erro"], "tipo_desconhecido")

    def test_a_dlq_guarda_o_envelope_inteiro_quando_ele_se_leu(self) -> None:
        servidor = com_conversa()
        asyncio.run(monta(servidor).entregar(corpo(envelope_cru(versao=2))))
        guardado = json.loads(servidor.dlq[0]["envelope"])
        self.assertEqual(set(guardado), set(env.CAMPOS_DO_ENVELOPE))

    def test_so_um_motivo_vem_depois_das_retentativas(self) -> None:
        """A propriedade e **estrutural** e nao uma funcao que ninguem consulta.

        A primeira versao tinha um `MOTIVOS_SEM_RETENTATIVA` e um
        `e_definitivo()` que **nenhum codigo de producao chamava**; a revisao
        adversarial mediu-o, e a mutacao que os apagava nao mudava comportamento
        nenhum. O que se mede agora e a estrutura: os quatro deterministicos
        aparecem nos caminhos que **nao** contam tentativas, e o
        `tentativas_esgotadas` so nos dois que as contam.
        """
        fonte = Path(consumo.__file__).read_text(encoding="utf-8")
        for motivo in (
            "MOTIVO_ENVELOPE_INVALIDO",
            "MOTIVO_TIPO_DESCONHECIDO",
            "MOTIVO_VERSAO_DESCONHECIDA",
            "MOTIVO_SEM_TEMPLATE",
        ):
            with self.subTest(motivo=motivo):
                self.assertIn(motivo, fonte)
        self.assertEqual(fonte.count("TENTATIVAS_ESGOTADAS"), 3)
        self.assertEqual(fonte.count("if entrega.tentativas >= TENTATIVAS:"), 2)

    def test_um_motivo_fora_da_lista_fechada_levanta(self) -> None:
        servidor = Servidor()
        fila = dlq.FilaDeMortos(servidor.abrir)
        with self.assertRaises(dlq.MotivoDesconhecidoError):
            asyncio.run(
                fila.abrir(
                    consumidor="agr_vendedor",
                    envelope=env.ler_envelope(envelope_cru()),
                    motivo="inventado",
                    tentativas=1,
                )
            )
        self.assertEqual(servidor.dlq, [])

    def test_o_conjunto_de_motivos_por_nome_e_a_lista_fechada(self) -> None:
        self.assertEqual(
            set(desfechos.MOTIVOS_DA_DLQ),
            {
                desfechos.MOTIVO_ENVELOPE_INVALIDO,
                desfechos.MOTIVO_TIPO_DESCONHECIDO,
                desfechos.MOTIVO_VERSAO_DESCONHECIDA,
                desfechos.MOTIVO_SEM_TEMPLATE,
                desfechos.MOTIVO_COM_RETENTATIVA,
            },
        )

    def test_o_fora_de_ordem_do_kam_006_nao_e_motivo_deste_consumidor(self) -> None:
        """Ele nasce na pre-condicao de estado, que este consumidor nao corre.

        Declara-lo era uma etiqueta sempre a zero — a licao do `echo_latency_ms`
        do KAM-018, que o `metricas.py` deste servico repete.
        """
        from kamba_core.eventos import ForaDeOrdem

        self.assertNotIn(ForaDeOrdem.CODIGO, desfechos.MOTIVOS_DA_DLQ)
        fonte = Path(consumo.__file__).read_text(encoding="utf-8")
        self.assertNotIn("except ForaDeOrdem", fonte)


# ===========================================================================
# Criterio 4 — envelope com `tenant_id` forjado e recusado
# ===========================================================================


class TestCriterio4TenantForjado(unittest.TestCase):
    def setUp(self) -> None:
        m.METRICAS.repor()

    def test_o_envelope_de_outro_tenant_nao_encontra_a_conversa(self) -> None:
        """O `SET LOCAL` sai do envelope **validado**, e a RLS faz o resto."""
        servidor = com_conversa()
        outbound = OutboundEspiao()
        consumidor = monta(servidor, outbound=outbound)
        with self.assertRaises(EntregaPorRepetir):
            asyncio.run(
                consumidor.entregar(
                    corpo(envelope_cru(tenant_id=OUTRO_TENANT), tenant_id=OUTRO_TENANT)
                )
            )
        self.assertEqual(outbound.chamadas, [])
        self.assertEqual(servidor.consumidos, {})

    def test_o_ponteiro_da_fila_tem_de_bater_com_o_envelope(self) -> None:
        """Divergir e recusa, e a DLQ fica no *tenant* que a fila declarou."""
        servidor = com_conversa()
        desfecho = asyncio.run(
            monta(servidor).entregar(
                corpo(envelope_cru(tenant_id=OUTRO_TENANT), tenant_id=TENANT)
            )
        )
        self.assertEqual(desfecho.desfecho, "para_dlq")
        self.assertEqual(servidor.dlq[0]["tenant_id"], TENANT)
        self.assertEqual(servidor.dlq[0]["erro"], "envelope_invalido")

    def test_a_dlq_de_um_envelope_recusado_nao_guarda_o_que_recusou(self) -> None:
        """Senao punha o envelope de A dentro do *tenant* de B, por 30 dias."""
        servidor = com_conversa()
        asyncio.run(
            monta(servidor).entregar(
                corpo(envelope_cru(tenant_id=OUTRO_TENANT), tenant_id=TENANT)
            )
        )
        guardado = json.loads(servidor.dlq[0]["envelope"])
        self.assertNotIn(OUTRO_TENANT, json.dumps(guardado))
        self.assertEqual(servidor.dlq[0]["tipo"], dlq.TIPO_ILEGIVEL)
        self.assertEqual(servidor.dlq[0]["versao"], dlq.VERSAO_ILEGIVEL)

    def test_o_contexto_de_tenant_e_o_do_envelope_e_nao_o_do_corpo(self) -> None:
        servidor = com_conversa()
        asyncio.run(monta(servidor).entregar(corpo()))
        linha = servidor.consumidos[("agr_vendedor", EVENTO)]
        self.assertEqual(linha["tenant_id"], TENANT)

    def test_um_tenant_id_no_payload_e_recusado_pelo_contrato(self) -> None:
        """O contrato de cada tipo e fechado: um campo a mais reprova."""
        servidor = com_conversa()
        envelope = envelope_cru()
        envelope["payload"]["tenant_id"] = OUTRO_TENANT
        desfecho = asyncio.run(monta(servidor).entregar(corpo(envelope)))
        self.assertEqual(desfecho.desfecho, "para_dlq")
        self.assertEqual(servidor.dlq[0]["erro"], "envelope_invalido")

    def test_o_aviso_ao_dono_de_um_tenant_forjado_nao_le_conversa_nenhuma(self) -> None:
        """**O limite do criterio 4, medido e dito.**

        Um evento que so avisa o dono nao le conversa — logo a RLS nao tem onde
        morder —, e a unica barreira que resta e o **entitlement** do *tenant*
        que o envelope declara. Com um *tenant* sem entitlement activo, nada
        acontece; com um *tenant* real e activo, o aviso sai para ele. A ligacao
        entre o **agregado** e o *tenant* precisa do COM (KAM-041), e nao existe:
        esta aqui para que o limite nao fique por dizer. Achado da revisao
        adversarial.
        """
        servidor = Servidor()
        servidor.entitlements[(OUTRO_TENANT, "vendedor")] = False
        hnd = HndEspiao()
        envelope = envelope_cru(
            tenant_id=OUTRO_TENANT,
            tipo="stock.low",
            payload={"sku": "ABC", "qty": 2},
            agregado={"tipo": "product", "id": "ABC", "seq": 1},
        )
        desfecho = asyncio.run(
            monta(servidor, hnd=hnd).entregar(
                corpo(envelope, tenant_id=OUTRO_TENANT)
            )
        )
        self.assertEqual(desfecho.desfecho, "sem_entitlement")
        self.assertEqual(hnd.chamadas, [])

    def test_a_conversa_de_outro_tenant_nunca_e_lida(self) -> None:
        """ISO-43..46: um consumidor de A nao ve nada de B."""
        servidor = Servidor()
        servidor.conversas.append(
            LinhaDaConversa(
                id=CONVERSA, tenant_id=OUTRO_TENANT, contact_id=CONTACTO,
                last_inbound_at=1.0,
            )
        )
        ligacao = servidor.abrir()
        self.assertIsNone(turnos.ler_conversa_sincrono(ligacao, TENANT, CONTACTO))


# ===========================================================================
# Criterio 5 — turno por evento: `turn_id = event_id`, tranca, humano
# ===========================================================================


class TestCriterio5TurnoPorEvento(unittest.TestCase):
    def setUp(self) -> None:
        m.METRICAS.repor()

    def test_o_turn_id_e_o_event_id(self) -> None:
        servidor = com_conversa()
        outbound = OutboundEspiao()
        asyncio.run(monta(servidor, outbound=outbound).entregar(corpo()))
        self.assertTrue(outbound.chamadas[0]["chave"].startswith(f"agr_vendedor:{EVENTO}:"))

    def test_corre_sob_a_tranca_da_conversa(self) -> None:
        tranca = TrancaFalsa()
        asyncio.run(monta(com_conversa(), tranca=tranca).entregar(corpo()))
        self.assertEqual(tranca.tomadas, [f"{TENANT}:{CONTACTO}"])

    def test_a_chave_da_tranca_e_a_do_turno_de_conversa(self) -> None:
        from kamba_agr.contexto import thread_id_de

        self.assertEqual(
            turnos.thread_do_evento(TENANT, CONTACTO), thread_id_de(TENANT, CONTACTO)
        )

    def test_entregas_concorrentes_nao_se_sobrepoem_na_tranca(self) -> None:
        tranca = TrancaFalsa()
        consumidor = monta(com_conversa(), tranca=tranca)

        async def todas():
            await asyncio.gather(*(consumidor.entregar(corpo()) for _ in range(5)))

        asyncio.run(todas())
        self.assertEqual(tranca.sobrepostas, 0)

    def test_nao_corre_com_a_conversa_pausada_e_notifica_o_hnd(self) -> None:
        servidor = com_conversa(modo="pausada")
        outbound, hnd = OutboundEspiao(), HndEspiao()
        desfecho = asyncio.run(
            monta(servidor, outbound=outbound, hnd=hnd).entregar(corpo())
        )
        self.assertEqual(desfecho.desfecho, "entregue_ao_hnd")
        self.assertEqual(outbound.chamadas, [])
        self.assertEqual(len(hnd.chamadas), 1)
        self.assertEqual(hnd.chamadas[0]["motivo"], "payment.confirmed")

    def test_nao_corre_com_handoff_em_waiting_e_notifica_o_hnd(self) -> None:
        servidor = com_conversa(handoff_a_espera=True)
        outbound, hnd = OutboundEspiao(), HndEspiao()
        desfecho = asyncio.run(
            monta(servidor, outbound=outbound, hnd=hnd).entregar(corpo())
        )
        self.assertEqual(desfecho.desfecho, "entregue_ao_hnd")
        self.assertEqual(outbound.chamadas, [])
        self.assertEqual(len(hnd.chamadas), 1)

    def test_um_modo_novo_fecha_a_porta_por_omissao(self) -> None:
        """Lista de permitidos e nao de proibidos (KAM-014, criterio 5)."""
        conversa = turnos.Conversa(id=CONVERSA, modo="inventado", handoff_a_espera=False)
        self.assertTrue(conversa.do_humano)

    def test_a_conversa_em_bot_nao_e_do_humano(self) -> None:
        conversa = turnos.Conversa(id=CONVERSA, modo="bot", handoff_a_espera=False)
        self.assertFalse(conversa.do_humano)

    def test_o_evento_com_humano_consome_se_e_nao_se_repete(self) -> None:
        """Repetir seis vezes para dizer sempre o mesmo nao e tentar outra vez."""
        servidor = com_conversa(modo="pausada")
        consumidor = monta(servidor)
        asyncio.run(consumidor.entregar(corpo()))
        self.assertEqual(len(servidor.consumidos), 1)
        self.assertEqual(
            asyncio.run(consumidor.entregar(corpo())).desfecho, "duplicado"
        )

    def test_o_aviso_ao_dono_nao_toma_tranca(self) -> None:
        """Um `stock.low` nao fala com cliente nenhum: nao ha o que serializar."""
        tranca = TrancaFalsa()
        servidor = com_conversa()
        envelope = envelope_cru(
            tipo="stock.low",
            payload={"sku": "ABC", "qty": 2},
            agregado={"tipo": "product", "id": "ABC", "seq": 1},
        )
        desfecho = asyncio.run(
            monta(servidor, tranca=tranca).entregar(corpo(envelope))
        )
        self.assertEqual(desfecho.desfecho, "aplicado")
        self.assertEqual(tranca.tomadas, [])

    def test_sem_conversa_nao_se_notifica_ninguem(self) -> None:
        servidor = Servidor()
        outbound = OutboundEspiao()
        with self.assertRaises(EntregaPorRepetir):
            asyncio.run(monta(servidor, outbound=outbound).entregar(corpo()))
        self.assertEqual(outbound.chamadas, [])

    def test_a_conversa_escolhida_e_a_de_entrada_mais_recente(self) -> None:
        servidor = Servidor()
        servidor.conversas.append(
            LinhaDaConversa(id="11111111-1111-4111-8111-111111111111",
                            tenant_id=TENANT, contact_id=CONTACTO, last_inbound_at=1.0)
        )
        servidor.conversas.append(
            LinhaDaConversa(id=CONVERSA, tenant_id=TENANT, contact_id=CONTACTO,
                            last_inbound_at=99.0)
        )
        outbound = OutboundEspiao()
        asyncio.run(monta(servidor, outbound=outbound).entregar(corpo()))
        self.assertEqual(
            outbound.chamadas[0]["notificacao"].conversation_id, CONVERSA
        )


# ===========================================================================
# Criterio 6 — janela aberta/fechada e *template* aprovado
# ===========================================================================


class TestCriterio6Notificacao(unittest.TestCase):
    def setUp(self) -> None:
        m.METRICAS.repor()

    def test_a_decisao_e_do_outbound_e_os_tres_desfechos_contam(self) -> None:
        for desfecho in ("livre", "template", "sem_template"):
            with self.subTest(desfecho=desfecho):
                m.METRICAS.repor()
                servidor = com_conversa()
                asyncio.run(
                    monta(servidor, outbound=OutboundEspiao(desfecho)).entregar(corpo())
                )
                self.assertEqual(
                    m.METRICAS.ler()[f"agr_evt_notificacoes_total:{desfecho}"], 1
                )

    def test_sem_template_vai_para_a_dlq_e_nao_deixa_marca(self) -> None:
        """**A correccao do defeito mais grave que a revisao encontrou.**

        A primeira versao contava o `sem_template` e seguia: uma linha em
        `events_consumed` e zero mensagens. No dia em que o KAM-024 aprovasse os
        *templates*, a re-entrega dava `duplicado` e o cliente **nunca** era
        avisado — e era o unico caminho que hoje corre.
        """
        servidor = com_conversa()
        desfecho = asyncio.run(
            monta(servidor, outbound=OutboundEspiao("sem_template")).entregar(corpo())
        )
        self.assertEqual(desfecho.desfecho, "para_dlq")
        self.assertEqual(servidor.consumidos, {})
        self.assertEqual(len(servidor.dlq), 1)
        self.assertEqual(servidor.dlq[0]["erro"], "sem_template")

    def test_sem_template_nao_gasta_a_escada(self) -> None:
        """Um *template* que nao esta aprovado nao passa a estar por esperar."""
        servidor = com_conversa()
        desfecho = asyncio.run(
            monta(servidor, outbound=OutboundEspiao("sem_template")).entregar(
                corpo(tentativas=1)
            )
        )
        self.assertEqual(desfecho.desfecho, "para_dlq")

    def test_sem_template_fica_reprocessavel(self) -> None:
        """O envelope inteiro fica na DLQ: e isso que o torna reprocessavel."""
        servidor = com_conversa()
        asyncio.run(
            monta(servidor, outbound=OutboundEspiao("sem_template")).entregar(corpo())
        )
        guardado = json.loads(servidor.dlq[0]["envelope"])
        self.assertEqual(set(guardado), set(env.CAMPOS_DO_ENVELOPE))

    def test_sem_template_aprovado_conta_alerta_e_levanta(self) -> None:
        avisos: list[tuple[str, str]] = []
        m.METRICAS.repor()
        notificador = notif.Notificador(
            cliente=OutboundEspiao("sem_template"),
            dono=HndEspiao(),
            metricas=m.METRICAS,
            aviso=lambda onde, desfecho: avisos.append((onde, desfecho)),
        )
        with self.assertRaises(notif.NotificacaoNaoEntregue):
            notificador.ao_cliente(
                consumidor="agr_vendedor",
                event_id=EVENTO,
                tenant_id=TENANT,
                notificacao=notif.Notificacao(
                    contact_id=CONTACTO,
                    conversation_id=CONVERSA,
                    texto="x",
                    template="payment.confirmed",
                ),
            )
        # Conta, alerta, e **so depois** levanta: o contador e o alerta sao o
        # que o criterio 6 pede, e medem-se mesmo que ninguem apanhe a excepcao.
        self.assertEqual(avisos, [("evt_notificacao", "sem_template")])
        self.assertEqual(m.METRICAS.ler()["agr_evt_notificacoes_total:sem_template"], 1)

    def test_livre_e_template_nao_alertam(self) -> None:
        for desfecho in ("livre", "template"):
            with self.subTest(desfecho=desfecho):
                avisos: list[tuple[str, str]] = []
                notif.Notificador(
                    cliente=OutboundEspiao(desfecho),
                    dono=HndEspiao(),
                    aviso=lambda onde, d: avisos.append((onde, d)),
                ).ao_cliente(
                    consumidor="agr_vendedor",
                    event_id=EVENTO,
                    tenant_id=TENANT,
                    notificacao=notif.Notificacao(
                        contact_id=CONTACTO, conversation_id=CONVERSA,
                        texto="x", template="t",
                    ),
                )
                self.assertEqual(avisos, [])

    def test_uma_notificacao_sem_template_nomeado_nao_se_constroi(self) -> None:
        with self.assertRaises(notif.NotificacaoSemTemplateError):
            notif.Notificacao(
                contact_id=CONTACTO, conversation_id=CONVERSA, texto="x", template=""
            )

    def test_a_porta_por_omissao_devolve_sem_template(self) -> None:
        """Nao ha catalogo de templates aprovados (KAM-024): e o estado honesto."""
        self.assertEqual(
            notif.OutboundPorLigar().notificar(
                tenant_id=TENANT,
                notificacao=notif.Notificacao(
                    contact_id=CONTACTO, conversation_id=CONVERSA,
                    texto="x", template="t",
                ),
                chave="k",
            ),
            "sem_template",
        )

    def test_as_portas_por_omissao_dao_dlq_e_nao_um_aplicado(self) -> None:
        """O estado do sistema hoje, dito com todas as letras.

        Com o Outbound por ligar nao ha *template* aprovado nenhum, pelo que
        **nenhuma** notificacao ao cliente sai — e o que fica e uma entrada na
        DLQ, visivel e reprocessavel, e nao um `aplicado` sobre uma mensagem
        que ninguem recebeu. A primeira versao deste ensaio afirmava o
        contrario.
        """
        servidor = com_conversa()
        consumidor = ConsumidorDeEventos(
            tabela=tuple(c for c in tabela_do_registo() if c.vertical == "vendedor"),
            trancas=TrancaFalsa(),
            conversas=turnos.LeitorDeConversas(servidor.abrir),
            abrir_ligacao=servidor.abrir,
            fila_de_mortos=dlq.FilaDeMortos(servidor.abrir),
            notificador=notif.Notificador(),
            ler_entitlement=_entitlement(servidor),
            contactos=ContactoFixo(CONTACTO),
            metricas=m.METRICAS,
        )
        self.assertEqual(asyncio.run(consumidor.entregar(corpo())).desfecho, "para_dlq")
        self.assertEqual(servidor.dlq[0]["erro"], "sem_template")

    def test_um_desfecho_que_nao_e_de_cliente_e_recusado(self) -> None:
        notificador = notif.Notificador(cliente=OutboundEspiao("dono"))
        with self.assertRaises(notif.NotificacaoIndisponivel):
            notificador.ao_cliente(
                consumidor="agr_vendedor", event_id=EVENTO, tenant_id=TENANT,
                notificacao=notif.Notificacao(
                    contact_id=CONTACTO, conversation_id=CONVERSA,
                    texto="x", template="t",
                ),
            )

    def test_o_template_pedido_e_o_tipo_do_evento(self) -> None:
        """O nome Meta e por *tenant* (§3.14): quem o resolve e o Outbound."""
        servidor = com_conversa()
        outbound = OutboundEspiao()
        asyncio.run(monta(servidor, outbound=outbound).entregar(corpo()))
        self.assertEqual(
            outbound.chamadas[0]["notificacao"].template, "payment.confirmed"
        )

    def test_nenhum_texto_de_notificacao_leva_numeros(self) -> None:
        """Sem numeros nao ha citacao a validar (ADR-007), e nao ha numero errado."""
        for par, texto in handlers.TEXTOS.items():
            with self.subTest(par=par):
                self.assertNotRegex(texto, r"[0-9]")

    def test_a_notificacao_leva_contact_id_e_nunca_um_numero(self) -> None:
        """«Os payloads trazem `contact_id`, nunca telefone» (ADR-010).

        O que se mede e o que **sai** do AGR: os campos da `Notificacao` sao
        cinco, nenhum e um numero de telefone, e a resolucao do destinatario e
        do Outbound (Detalhes Tecnicos do bloco).
        """
        servidor = com_conversa()
        outbound = OutboundEspiao()
        asyncio.run(monta(servidor, outbound=outbound).entregar(corpo()))
        notificacao = outbound.chamadas[0]["notificacao"]
        self.assertEqual(notificacao.contact_id, CONTACTO)
        self.assertEqual(
            set(notif.Notificacao.__slots__),
            {"contact_id", "conversation_id", "texto", "template"},
        )


# ===========================================================================
# Criterio 7 — o dono nunca pelo numero da propria loja
# ===========================================================================


class TestCriterio7AvisoAoDono(unittest.TestCase):
    def setUp(self) -> None:
        m.METRICAS.repor()

    def test_o_pagamento_avisa_o_cliente_e_o_dono(self) -> None:
        servidor = com_conversa()
        outbound, hnd = OutboundEspiao(), HndEspiao()
        asyncio.run(monta(servidor, outbound=outbound, hnd=hnd).entregar(corpo()))
        self.assertEqual(len(outbound.chamadas), 1)
        self.assertEqual(len(hnd.chamadas), 1)

    def test_o_stock_baixo_avisa_so_o_dono(self) -> None:
        servidor = com_conversa()
        outbound, hnd = OutboundEspiao(), HndEspiao()
        envelope = envelope_cru(
            tipo="stock.low",
            payload={"sku": "ABC", "qty": 2},
            agregado={"tipo": "product", "id": "ABC", "seq": 1},
        )
        asyncio.run(
            monta(servidor, outbound=outbound, hnd=hnd).entregar(corpo(envelope))
        )
        self.assertEqual(outbound.chamadas, [])
        self.assertEqual(len(hnd.chamadas), 1)

    def test_o_aviso_ao_dono_tem_chave_propria(self) -> None:
        servidor = com_conversa()
        hnd = HndEspiao()
        asyncio.run(monta(servidor, hnd=hnd).entregar(corpo()))
        self.assertEqual(
            hnd.chamadas[0]["chave"], f"agr_vendedor:{EVENTO}:notificar_dono"
        )

    def test_o_aviso_ao_dono_nunca_passa_pela_porta_do_cliente(self) -> None:
        outbound, hnd = OutboundEspiao(), HndEspiao()
        notif.Notificador(cliente=outbound, dono=hnd).ao_dono(
            consumidor="agr_vendedor", event_id=EVENTO, tenant_id=TENANT,
            motivo="stock.low",
        )
        self.assertEqual(outbound.chamadas, [])
        self.assertEqual(len(hnd.chamadas), 1)

    def test_a_porta_do_dono_nao_tem_campos_de_conversa(self) -> None:
        """Sem `contact_id` nem `conversation_id`, nao ha por onde cair no canal
        do cliente."""
        import inspect

        assinatura = inspect.signature(notif.PortaDeAvisoAoDono.avisar)
        self.assertEqual(
            set(assinatura.parameters) - {"self"}, {"tenant_id", "motivo", "chave"}
        )

    def test_o_modulo_de_notificacao_tem_duas_portas_distintas(self) -> None:
        self.assertIsNot(notif.PortaDeNotificacao, notif.PortaDeAvisoAoDono)
        self.assertNotEqual(notif.ACCAO_AO_CLIENTE, notif.ACCAO_AO_DONO)

    def test_uma_accao_desconhecida_nao_tem_chave(self) -> None:
        with self.assertRaises(ValueError):
            notif.chave_da_accao("agr_vendedor", EVENTO, "enviar_sms")


# ===========================================================================
# Criterio 8 — prioridade dos eventos de pagamento, e o *lag*
# ===========================================================================


class TestCriterio8Prioridade(unittest.TestCase):
    def setUp(self) -> None:
        m.METRICAS.repor()

    def test_os_eventos_de_pagamento_sao_prioritarios(self) -> None:
        consumidor = monta(com_conversa())
        self.assertTrue(consumidor.e_prioritario("payment.confirmed"))
        self.assertTrue(consumidor.e_prioritario("payment.manual_confirmed"))
        self.assertFalse(consumidor.e_prioritario("order.expired"))
        self.assertFalse(consumidor.e_prioritario("stock.low"))

    def test_um_tipo_desconhecido_nao_e_prioritario(self) -> None:
        self.assertFalse(monta(com_conversa()).e_prioritario("nada.disto"))

    def test_o_pagamento_entra_com_o_tecto_do_tenant_cheio(self) -> None:
        """A reserva e **acima** do tecto: a conversa continua com 3."""
        from kamba_agr.admissao import Admissao, TectoDoTenantCheioError, Tectos

        admissao = Admissao(tectos=Tectos(tecto_por_tenant=1, reserva_de_pagamento=1))

        async def correr():
            async with admissao.vaga_de(TENANT):
                with self.assertRaises(TectoDoTenantCheioError):
                    async with admissao.vaga_de(TENANT):
                        pass
                async with admissao.vaga_de(TENANT, prioritario=True):
                    self.assertEqual(admissao.em_curso(TENANT), 2)

        asyncio.run(correr())

    def test_a_reserva_esgota_se_tambem(self) -> None:
        from kamba_agr.admissao import Admissao, TectoDoTenantCheioError, Tectos

        admissao = Admissao(tectos=Tectos(tecto_por_tenant=1, reserva_de_pagamento=1))

        async def correr():
            async with admissao.vaga_de(TENANT, prioritario=True):
                async with admissao.vaga_de(TENANT, prioritario=True):
                    with self.assertRaises(TectoDoTenantCheioError):
                        async with admissao.vaga_de(TENANT, prioritario=True):
                            pass

        asyncio.run(correr())

    def test_o_tecto_por_tenant_da_conversa_nao_muda(self) -> None:
        """O criterio 5 do KAM-025 foi medido com 3, e continua com 3."""
        from kamba_agr.admissao import TECTO_POR_TENANT, Tectos

        self.assertEqual(Tectos().tecto_por_tenant, TECTO_POR_TENANT)
        self.assertEqual(TECTO_POR_TENANT, 3)

    def test_o_lag_mede_se_do_ocorrido_em(self) -> None:
        instante = "2026-11-02T14:03:11.000+00:00"
        import datetime

        agora = datetime.datetime.fromisoformat(instante).timestamp() + 2.5
        self.assertEqual(consumo.lag_ms(instante, agora), 2_500)

    def test_o_lag_nunca_e_negativo(self) -> None:
        """O `ocorrido_em` e o relogio do produtor, e pode vir a frente."""
        instante = "2026-11-02T14:03:11.000+00:00"
        import datetime

        agora = datetime.datetime.fromisoformat(instante).timestamp() - 60
        self.assertEqual(consumo.lag_ms(instante, agora), 0)

    def test_o_lag_sem_fuso_nao_se_inventa(self) -> None:
        self.assertIsNone(consumo.lag_ms("2026-11-02T14:03:11", 0.0))

    def test_o_lag_ilegivel_nao_se_inventa(self) -> None:
        self.assertIsNone(consumo.lag_ms("ontem", 0.0))

    def test_o_lag_fica_na_metrica_com_o_consumidor_por_eixo(self) -> None:
        import datetime

        ocorrido = "2026-11-02T14:03:11.482+00:00"
        agora = datetime.datetime.fromisoformat(ocorrido).timestamp() + 1.0
        servidor = com_conversa()
        asyncio.run(
            monta(servidor, relogio=lambda: agora).entregar(
                corpo(envelope_cru(ocorrido_em=ocorrido))
            )
        )
        self.assertEqual(m.METRICAS.ler()["agr_evt_lag_ms:agr_vendedor"], 1_000)

    def test_o_lag_so_se_mede_no_aplicado(self) -> None:
        servidor = com_conversa()
        consumidor = monta(servidor)
        asyncio.run(consumidor.entregar(corpo()))
        antes = m.METRICAS.ler()["agr_evt_lag_ms:agr_vendedor"]
        m.METRICAS.repor()
        asyncio.run(consumidor.entregar(corpo()))
        self.assertNotIn("agr_evt_lag_ms:agr_vendedor", m.METRICAS.ler())
        self.assertGreaterEqual(antes, 0)

    def test_p99_de_lag_em_carga_leve(self) -> None:
        """Carga leve: 200 pagamentos, p99 do *lag* medido <= 10 s.

        **Nao mede a fila nem a rede** — nao ha nenhuma aqui —, e isso fica
        dito: o que esta bateria prova e que o caminho de decisao do consumidor
        nao e, ele proprio, a fonte do atraso. O alvo do `../docs/tecnica/06`
        mede-se em *staging*, com o BullMQ e a base reais.
        """
        import datetime
        import time as _time

        ocorrido = "2026-11-02T14:03:11.000+00:00"
        base = datetime.datetime.fromisoformat(ocorrido).timestamp()
        servidor = com_conversa()
        comeco = _time.monotonic()
        consumidor = monta(
            servidor, relogio=lambda: base + (_time.monotonic() - comeco)
        )

        async def carga():
            medidas: list[int] = []
            for numero in range(200):
                identificador = f"0192f1c4-7b1e-7d2a-9c3e-{numero:012d}"
                await consumidor.entregar(
                    corpo(envelope_cru(id=identificador, ocorrido_em=ocorrido),
                          event_id=identificador)
                )
                medidas.append(int(m.METRICAS.ler()["agr_evt_lag_ms:agr_vendedor"]))
            return medidas

        medidas = asyncio.run(carga())
        medidas.sort()
        # O p99 de 200 amostras e a 198.ª **inclusive** pelo metodo do percentil
        # mais proximo: `ceil(0.99 * 200) = 198`, indice 197. O
        # `int(len * 0.99) - 1` da 197 por coincidencia de arredondamento e nao
        # pela definicao — e com 150 amostras dava a 148.ª em vez da 149.ª.
        # Achado da revisao adversarial.
        import math

        p99 = medidas[math.ceil(len(medidas) * 0.99) - 1]
        self.assertLessEqual(p99, 10_000, f"p99 = {p99} ms")


# ===========================================================================
# O corpo da entrega, as metricas e o roteamento por entitlement
# ===========================================================================


class TestCorpoDaEntrega(unittest.TestCase):
    def test_le_um_corpo_valido(self) -> None:
        entrega = consumo.ler_entrega(corpo())
        self.assertEqual(entrega.event_id, EVENTO)
        self.assertEqual(entrega.tentativas, 1)

    def test_recusa_campo_a_mais(self) -> None:
        with self.assertRaises(consumo.EntregaInvalidaError) as erro:
            consumo.ler_entrega(corpo(extra=1))
        self.assertEqual(erro.exception.codigo, "campo_desconhecido")

    def test_recusa_campo_em_falta(self) -> None:
        pedido = corpo()
        del pedido["tentativas"]
        with self.assertRaises(consumo.EntregaInvalidaError) as erro:
            consumo.ler_entrega(pedido)
        self.assertEqual(erro.exception.codigo, "campo_em_falta")

    def test_recusa_tentativas_zero(self) -> None:
        with self.assertRaises(consumo.EntregaInvalidaError):
            consumo.ler_entrega(corpo(tentativas=0))

    def test_recusa_tentativas_booleanas(self) -> None:
        with self.assertRaises(consumo.EntregaInvalidaError):
            consumo.ler_entrega(corpo(tentativas=True))

    def test_recusa_o_que_nao_e_objecto(self) -> None:
        with self.assertRaises(consumo.EntregaInvalidaError):
            consumo.ler_entrega([1, 2])

    def test_o_envelope_pode_vir_como_texto_json(self) -> None:
        """O `ler_envelope` aceita texto; a entrega inteira tambem tem de aceitar."""
        servidor = com_conversa()
        outbound = OutboundEspiao()
        desfecho = asyncio.run(
            monta(servidor, outbound=outbound).entregar(
                corpo(json.dumps(envelope_cru()))
            )
        )
        self.assertEqual(desfecho.desfecho, "aplicado")
        self.assertEqual(len(outbound.chamadas), 1)

    def test_uma_tabela_de_consumidores_vazia_e_recusada(self) -> None:
        """200 «tratado» sem linha nenhuma perdia o evento em silencio."""
        servidor = com_conversa()
        with self.assertRaises(ValueError):
            monta(servidor, tabela=())

    def test_os_quatro_campos_sao_lista_fechada(self) -> None:
        self.assertEqual(
            consumo.CAMPOS_DA_ENTREGA,
            ("event_id", "tenant_id", "envelope", "tentativas"),
        )


class TestRoteamentoPorEntitlement(unittest.TestCase):
    def setUp(self) -> None:
        m.METRICAS.repor()

    def test_so_a_vertical_activa_consome(self) -> None:
        """Senao o mesmo pagamento dava duas mensagens ao mesmo cliente."""
        servidor = com_conversa()
        servidor.entitlements[(TENANT, "servicos")] = False
        outbound = OutboundEspiao()
        desfecho = asyncio.run(
            monta(servidor, outbound=outbound, tabela=tabela_do_registo()).entregar(
                corpo()
            )
        )
        self.assertEqual(desfecho.desfecho, "aplicado")
        self.assertEqual(len(outbound.chamadas), 1)
        self.assertEqual([n for n, _ in desfecho.por_consumidor], ["agr_vendedor"])

    def test_sem_vertical_activa_nao_se_consome_nem_se_abre_dlq(self) -> None:
        servidor = com_conversa()
        servidor.entitlements[(TENANT, "vendedor")] = False
        servidor.entitlements[(TENANT, "servicos")] = False
        outbound = OutboundEspiao()
        desfecho = asyncio.run(
            monta(servidor, outbound=outbound, tabela=tabela_do_registo()).entregar(
                corpo()
            )
        )
        self.assertEqual(desfecho.desfecho, "sem_entitlement")
        self.assertEqual(outbound.chamadas, [])
        self.assertEqual(servidor.dlq, [])
        # **Marca-se, uma linha por candidato.** Sem linha em `events_consumed`
        # nem em `events_dlq`, o reconciliador do §6.5 reenfileirava o evento de
        # cinco em cinco minutos durante 24 h — um ciclo silencioso por cada
        # evento de um *tenant* sem entitlement. Achado da revisao adversarial.
        self.assertEqual(len(servidor.consumidos), 2)
        self.assertEqual(
            {c for c, _ in servidor.consumidos}, {"agr_vendedor", "agr_servicos"}
        )

    def test_duas_verticais_activas_dao_uma_so_mensagem(self) -> None:
        """**O defeito que a revisao adversarial encontrou, medido.**

        Um *tenant* com as duas verticais activas — o do *gate* da Fase 0
        (ADR-012, KAM-108) — tem dois consumidores, e isso esta certo. O que
        estava errado era os dois mandarem a **mesma** mensagem: com o *handler*
        por `(vertical, tipo)`, o pagamento fala com o cliente pelo Vendedor e
        nos Servicos da `sem_accao`, com o credor nomeado.
        """
        servidor = com_conversa()
        outbound, hnd = OutboundEspiao(), HndEspiao()
        desfecho = asyncio.run(
            monta(
                servidor, outbound=outbound, hnd=hnd, tabela=tabela_do_registo()
            ).entregar(corpo())
        )
        self.assertEqual(
            sorted(desfecho.por_consumidor),
            [("agr_servicos", "sem_accao"), ("agr_vendedor", "aplicado")],
        )
        self.assertEqual(len(outbound.chamadas), 1)
        self.assertEqual(len(hnd.chamadas), 1)
        self.assertEqual(len(servidor.consumidos), 2)

    def test_o_agregado_de_duas_verticais_manda_olhar(self) -> None:
        """`sem_accao` e mais grave do que `aplicado`: e o que o painel tem de ver."""
        servidor = com_conversa()
        desfecho = asyncio.run(
            monta(servidor, tabela=tabela_do_registo()).entregar(corpo())
        )
        self.assertEqual(desfecho.desfecho, "sem_accao")


class TestMetricas(unittest.TestCase):
    def setUp(self) -> None:
        m.METRICAS.repor()

    def test_o_lag_recusa_um_tenant_id_como_etiqueta(self) -> None:
        with self.assertRaises(m.EtiquetaInvalida):
            m.METRICAS.medir(m.METRICA_EVT_LAG, 1, TENANT)

    def test_o_lag_recusa_um_consumidor_fora_da_lista_fechada(self) -> None:
        with self.assertRaises(m.EtiquetaInvalida):
            m.METRICAS.medir(m.METRICA_EVT_LAG, 1, "agr_inventado")

    def test_o_lag_exige_etiqueta(self) -> None:
        with self.assertRaises(m.EtiquetaInvalida):
            m.METRICAS.medir(m.METRICA_EVT_LAG, 1)

    def test_uma_medida_sem_etiqueta_recusa_etiqueta(self) -> None:
        with self.assertRaises(m.EtiquetaInvalida):
            m.METRICAS.medir(m.METRICA_DURACAO, 1, "agr_vendedor")

    def test_o_lag_nao_e_um_contador(self) -> None:
        """Somar milissegundos da um numero sem significado nenhum."""
        with self.assertRaises(m.EtiquetaInvalida):
            m.METRICAS.contar(m.METRICA_EVT_LAG, "agr_vendedor")

    def test_a_medida_com_etiqueta_aparece_na_exposicao(self) -> None:
        m.METRICAS.medir(m.METRICA_EVT_LAG, 1_234, "agr_vendedor")
        exposicao = m.METRICAS.exposicao()
        self.assertIn('agr_evt_lag_ms{consumer="agr_vendedor"} 1234', exposicao)
        self.assertIn("# TYPE agr_evt_lag_ms gauge", exposicao)

    def test_dois_consumidores_dao_duas_series(self) -> None:
        m.METRICAS.medir(m.METRICA_EVT_LAG, 1, "agr_vendedor")
        m.METRICAS.medir(m.METRICA_EVT_LAG, 2, "agr_servicos")
        exposicao = m.METRICAS.exposicao()
        self.assertIn('agr_evt_lag_ms{consumer="agr_servicos"} 2', exposicao)
        self.assertIn('agr_evt_lag_ms{consumer="agr_vendedor"} 1', exposicao)

    def test_as_medidas_sem_etiqueta_continuam_a_aparecer(self) -> None:
        m.METRICAS.medir(m.METRICA_DURACAO, 7)
        self.assertIn("agr_turn_latency_ms 7", m.METRICAS.exposicao())

    def test_os_desfechos_sao_lista_fechada(self) -> None:
        with self.assertRaises(m.EtiquetaInvalida):
            m.METRICAS.contar(m.METRICA_EVT_CONSUMIDOS, "inventado")

    def test_o_eixo_da_dlq_chama_se_motivo(self) -> None:
        m.METRICAS.contar(m.METRICA_EVT_DLQ, "versao_desconhecida")
        self.assertIn('agr_evt_dlq_total{motivo=', m.METRICAS.exposicao())

    def test_o_eixo_do_lag_chama_se_consumer(self) -> None:
        m.METRICAS.medir(m.METRICA_EVT_LAG, 1, "agr_vendedor")
        self.assertIn('agr_evt_lag_ms{consumer=', m.METRICAS.exposicao())


class TestLigacaoDoConsumo(unittest.TestCase):
    """O adaptador que traduz `BEGIN`/`COMMIT`/`ROLLBACK` para o condutor."""

    def test_o_commit_vai_a_api_do_condutor(self) -> None:
        servidor = Servidor()
        ligacao = servidor.abrir()
        cliente = consumo.LigacaoDoConsumo(ligacao)
        cliente.executar("BEGIN")
        cliente.executar("COMMIT")
        self.assertEqual(ligacao.commits, 1)
        self.assertEqual(ligacao.sql, [])

    def test_o_rollback_vai_a_api_do_condutor(self) -> None:
        servidor = Servidor()
        ligacao = servidor.abrir()
        consumo.LigacaoDoConsumo(ligacao).executar("ROLLBACK")
        self.assertEqual(ligacao.rollbacks, 1)

    def test_uma_instrucao_de_transaccao_nao_traduzida_levanta(self) -> None:
        servidor = Servidor()
        cliente = consumo.LigacaoDoConsumo(servidor.abrir())
        for sql in ("SAVEPOINT a", "START TRANSACTION", "END"):
            with self.subTest(sql=sql), self.assertRaises(RuntimeError):
                cliente.executar(sql)

    def test_uma_leitura_devolve_linhas_com_nomes(self) -> None:
        servidor = com_conversa()
        cliente = consumo.LigacaoDoConsumo(servidor.abrir())
        from kamba_agr.eventos.consultas import SQL_CONVERSA_DO_CONTACTO

        cliente.executar("SELECT set_config('app.tenant_id', %s, %s)", (TENANT, True))
        resultado = cliente.executar(SQL_CONVERSA_DO_CONTACTO, (TENANT, CONTACTO))
        self.assertEqual(resultado.linhas[0]["conversa"], CONVERSA)


class TestAgregacaoDeDesfechos(unittest.TestCase):
    def test_o_agregado_e_o_pior(self) -> None:
        self.assertEqual(consumo._agregar(("aplicado", "para_dlq")), "para_dlq")
        self.assertEqual(consumo._agregar(("duplicado", "aplicado")), "aplicado")
        self.assertEqual(consumo._agregar(("duplicado",)), "duplicado")

    def test_um_desfecho_desconhecido_levanta(self) -> None:
        with self.assertRaises(ValueError):
            consumo._agregar(("inventado",))

    def test_a_gravidade_cobre_a_lista_fechada(self) -> None:
        self.assertEqual(set(consumo._GRAVIDADE), set(desfechos.DESFECHOS_DO_EVENTO))


class TestHandlers(unittest.TestCase):
    def test_todos_os_pares_com_texto_falam_com_o_cliente(self) -> None:
        self.assertEqual(set(handlers.AO_CLIENTE), set(handlers.TEXTOS))

    def test_os_pares_com_handler_sao_a_uniao_dos_tres(self) -> None:
        self.assertEqual(
            set(handlers.PARES_COM_HANDLER),
            set(handlers.AO_CLIENTE)
            | set(handlers.AO_DONO)
            | set(handlers.ACCOES_POR_LIGAR),
        )

    def test_nenhum_par_e_handler_e_accao_por_ligar_ao_mesmo_tempo(self) -> None:
        """Senao `fala_com_o_cliente` e `accao_por_ligar` diziam coisas opostas."""
        self.assertEqual(
            set(handlers.ACCOES_POR_LIGAR)
            & (set(handlers.AO_CLIENTE) | set(handlers.AO_DONO)),
            set(),
        )

    def test_o_contacto_do_payload_tem_precedencia(self) -> None:
        porta = ContactoFixo("outro")
        envelope = env.ler_envelope(
            envelope_cru(
                tipo="booking.created",
                payload={
                    "booking_id": "b1", "contact_id": CONTACTO,
                    "fim_at": "x", "inicio_at": "y", "service_id": "s",
                },
                agregado={"tipo": "booking", "id": "b1", "seq": 1},
            )
        )
        self.assertEqual(handlers.contacto_do_evento(envelope, porta), CONTACTO)
        self.assertEqual(porta.pedidos, [])

    def test_sem_contacto_no_payload_vai_a_porta(self) -> None:
        porta = ContactoFixo(CONTACTO)
        envelope = env.ler_envelope(envelope_cru())
        self.assertEqual(handlers.contacto_do_evento(envelope, porta), CONTACTO)
        self.assertEqual(porta.pedidos, [("order", CONTACTO)])

    def test_a_porta_por_omissao_levanta(self) -> None:
        with self.assertRaises(handlers.ContactoPorResolver):
            handlers.ContactoPorLigar().contacto_de("order", "x")

    def test_sem_conversa_as_accoes_levantam(self) -> None:
        envelope = env.ler_envelope(envelope_cru())
        with self.assertRaises(handlers.ContactoPorResolver):
            handlers.accoes_de(
                envelope,
                vertical="vendedor",
                contact_id=CONTACTO,
                conversation_id=None,
            )

    def test_o_pagamento_leva_cliente_e_dono_no_vendedor(self) -> None:
        accoes = handlers.accoes_de(
            env.ler_envelope(envelope_cru()),
            vertical="vendedor",
            contact_id=CONTACTO,
            conversation_id=CONVERSA,
        )
        self.assertIsNotNone(accoes.cliente)
        self.assertEqual(accoes.dono_por, "payment.confirmed")

    def test_o_mesmo_pagamento_nao_leva_nada_nos_servicos(self) -> None:
        """A accao dos Servicos para um pagamento e do KAM-047, e nao esta escrita."""
        accoes = handlers.accoes_de(
            env.ler_envelope(envelope_cru()),
            vertical="servicos",
            contact_id=CONTACTO,
            conversation_id=CONVERSA,
        )
        self.assertIsNone(accoes.cliente)
        self.assertIsNone(accoes.dono_por)

    def test_o_order_expired_leva_so_o_cliente(self) -> None:
        accoes = handlers.accoes_de(
            env.ler_envelope(
                envelope_cru(
                    tipo="order.expired",
                    payload={"order_id": CONTACTO, "expira_at": "x"},
                )
            ),
            vertical="vendedor",
            contact_id=CONTACTO,
            conversation_id=CONVERSA,
        )
        self.assertIsNotNone(accoes.cliente)
        self.assertIsNone(accoes.dono_por)


class TestCancelamento(unittest.IsolatedAsyncioTestCase):
    """O `to_thread` **nao** cancela a *thread*: largar a exclusiva deixava-a
    a meio do protocolo do `pg8000` na mesma tomada, e a entrega seguinte
    usava-a em paralelo. E o defeito que o `checkpointer.py` do KAM-026 ja
    pagou, e o modulo novo copiou a forma errada — achado da revisao
    adversarial."""

    async def asyncSetUp(self) -> None:
        m.METRICAS.repor()

    async def test_o_leitor_espera_pela_thread_antes_de_largar_a_exclusiva(self) -> None:
        import threading

        servidor = com_conversa()
        a_meio = threading.Event()
        pode_seguir = threading.Event()
        acabou = threading.Event()

        class Lenta:
            """Uma ligacao que para a *thread* a meio da leitura."""

            autocommit = False

            def __init__(self, interna) -> None:
                self._interna = interna

            def cursor(self):
                a_meio.set()
                pode_seguir.wait(timeout=10)
                return self._interna.cursor()

            def __getattr__(self, nome):
                return getattr(self._interna, nome)

        def abrir():
            return Lenta(servidor.abrir())

        leitor = turnos.LeitorDeConversas(abrir)

        async def ler():
            try:
                await leitor.ler(TENANT, CONTACTO)
            finally:
                acabou.set()

        tarefa = asyncio.create_task(ler())
        await asyncio.to_thread(a_meio.wait, 10)
        tarefa.cancel()
        # **O cancelamento NAO conclui enquanto a *thread* nao acabar**, e e
        # isso que se mede: um `TimeoutError` aqui e a propriedade a funcionar.
        # Sem o `await asyncio.wait([tarefa])` do `ler`, a corrotina saia de
        # imediato e largava a exclusiva com a *thread* dentro do `pg8000`.
        with self.assertRaises(asyncio.TimeoutError):
            await asyncio.wait_for(asyncio.shield(tarefa), timeout=0.3)
        self.assertFalse(acabou.is_set(), "a corrotina saiu com a thread a meio")
        pode_seguir.set()
        with self.assertRaises(asyncio.CancelledError):
            await tarefa
        self.assertTrue(acabou.is_set())

    async def test_o_leitor_continua_utilizavel_depois_de_um_cancelamento(self) -> None:
        servidor = com_conversa()
        leitor = turnos.LeitorDeConversas(servidor.abrir)
        tarefa = asyncio.create_task(leitor.ler(TENANT, CONTACTO))
        tarefa.cancel()
        with self.assertRaises(asyncio.CancelledError):
            await tarefa
        conversa = await leitor.ler(TENANT, CONTACTO)
        self.assertIsNotNone(conversa)
        await leitor.fechar()

    async def test_os_tres_sitios_que_vao_a_base_tratam_o_cancelamento(self) -> None:
        """Lido como texto: a forma e a do `checkpointer.py`, nos tres.

        Le-se assim e nao por execucao porque o que se mede e a **forma** — o
        `shield` com o `wait` a seguir —, e um `shield` sem o `wait` passa
        qualquer ensaio de caminho feliz e deixa o defeito inteiro.
        """
        for modulo in (turnos, consumo, dlq):
            with self.subTest(modulo=modulo.__name__):
                fonte = Path(modulo.__file__).read_text(encoding="utf-8")
                self.assertIn("asyncio.shield(tarefa)", fonte)
                self.assertIn("await asyncio.wait([tarefa])", fonte)


class TestTomadas(unittest.TestCase):
    """As ligacoes abrem e fecham. Uma diferenca que cresce e uma fuga."""

    def test_a_entrega_nao_deixa_tomadas_abertas(self) -> None:
        servidor = com_conversa()
        consumidor = monta(servidor)
        asyncio.run(consumidor.entregar(corpo()))
        asyncio.run(consumidor.conversas.fechar())
        self.assertEqual(servidor.abertas, servidor.fechadas)

    def test_a_dlq_fecha_a_sua(self) -> None:
        servidor = Servidor()
        asyncio.run(
            dlq.FilaDeMortos(servidor.abrir).abrir(
                consumidor="agr_vendedor",
                envelope=env.ler_envelope(envelope_cru()),
                motivo="versao_desconhecida",
                tentativas=1,
            )
        )
        self.assertEqual(servidor.abertas, servidor.fechadas)



# ===========================================================================
# A rota `/internal/event`
# ===========================================================================


class TestRotaDoEvento(unittest.IsolatedAsyncioTestCase):
    """A casca HTTP: tres codigos, e cada um diz a fila o que fazer."""

    async def asyncSetUp(self) -> None:
        from kamba_agr.api_interna import CABECALHO, rotas
        from kamba_agr.app import create_app
        from kamba_agr.admissao import Admissao, Tectos
        from apoio import pedir

        m.METRICAS.repor()
        self.pedir = pedir
        self.cabecalhos = {CABECALHO: "um-segredo-de-ensaio"}
        self.servidor = com_conversa()
        self.outbound = OutboundEspiao()
        self.consumidor = monta(self.servidor, outbound=self.outbound)
        self.admissao = Admissao(tectos=Tectos())

        async def executar(_invocacao):  # pragma: no cover — nao se usa aqui
            raise AssertionError("esta bateria nao passa pelo /internal/turn")

        self.app = create_app(
            rotas_internas=rotas(
                credencial=lambda: "um-segredo-de-ensaio",
                executar=executar,
                admissao=self.admissao,
                trancas=TrancaFalsa(),
                eventos=self.consumidor,
            )
        )
        self.sem_consumidor = create_app(
            rotas_internas=rotas(
                credencial=lambda: "um-segredo-de-ensaio",
                executar=executar,
                admissao=self.admissao,
                trancas=TrancaFalsa(),
            )
        )

    async def _entregar(self, pedido: dict, app=None):
        return await self.pedir(
            app or self.app,
            "/internal/event",
            "POST",
            json.dumps(pedido).encode(),
            self.cabecalhos,
        )

    async def test_sem_credencial_e_401(self) -> None:
        estado, _, _ = await self.pedir(
            self.app, "/internal/event", "POST", json.dumps(corpo()).encode()
        )
        self.assertEqual(estado, 401)

    async def test_uma_entrega_valida_e_200_com_o_desfecho(self) -> None:
        estado, _, resposta = await self._entregar(corpo())
        self.assertEqual(estado, 200)
        self.assertEqual(json.loads(resposta)["outcome"], "aplicado")
        self.assertEqual(len(self.outbound.chamadas), 1)

    async def test_a_resposta_diz_o_desfecho_de_cada_consumidor(self) -> None:
        _, _, resposta = await self._entregar(corpo())
        self.assertEqual(
            json.loads(resposta)["por_consumidor"],
            [{"consumer": "agr_vendedor", "outcome": "aplicado"}],
        )

    async def test_um_corpo_que_nao_e_entrega_e_400(self) -> None:
        estado, _, resposta = await self._entregar({"nada": 1})
        self.assertEqual(estado, 400)
        self.assertEqual(json.loads(resposta)["error_code"], "campo_desconhecido")

    async def test_um_corpo_que_nao_e_json_e_400(self) -> None:
        estado, _, _ = await self.pedir(
            self.app, "/internal/event", "POST", b"{isto nao", self.cabecalhos
        )
        self.assertEqual(estado, 400)

    async def test_sem_consumidor_e_503_e_o_evento_fica_na_fila(self) -> None:
        estado, cabecalhos, resposta = await self._entregar(
            corpo(), app=self.sem_consumidor
        )
        self.assertEqual(estado, 503)
        self.assertIn("retry-after", cabecalhos)
        self.assertEqual(json.loads(resposta)["outcome"], "consumidor_por_ligar")

    async def test_uma_versao_desconhecida_e_200_porque_foi_tratada(self) -> None:
        """Foi para a DLQ: repetir era abrir a mesma entrada seis vezes."""
        estado, _, resposta = await self._entregar(corpo(envelope_cru(versao=2)))
        self.assertEqual(estado, 200)
        self.assertEqual(json.loads(resposta)["outcome"], "para_dlq")

    async def test_uma_falha_do_outbound_e_503_com_retry_after(self) -> None:
        class Rebenta:
            def notificar(self, **_argumentos):
                raise RuntimeError("caiu")

        app_que_rebenta = await self._app_com(Rebenta())
        estado, cabecalhos, _ = await self._entregar(corpo(), app=app_que_rebenta)
        self.assertEqual(estado, 503)
        self.assertEqual(cabecalhos["retry-after"], "1")

    async def test_o_tecto_do_tenant_cheio_da_503_com_retry_after(self) -> None:
        """O `except TectoDoTenantCheioError` da rota, exercitado.

        **A primeira versao deste ensaio nao media nada**: trocava o
        `self.admissao` **depois** de a app estar montada, e o `rotas(...)` ja
        tinha fechado sobre o objecto anterior — o pedido corria com o tecto por
        omissao e um unico pedido em voo, pelo que 200 era inevitavel e a
        asserção passava com o ramo apagado. Achado da revisao adversarial.

        Agora o tecto entra na app **antes** de ela ser montada, e enche-se a
        mao: o que se mede e o ramo da rota e nao a aritmetica da admissao, que
        tem bateria propria.
        """
        from kamba_agr.admissao import Admissao, Tectos
        from kamba_agr.api_interna import rotas
        from kamba_agr.app import create_app

        admissao = Admissao(tectos=Tectos(tecto_por_tenant=1))
        servidor = com_conversa()

        async def executar(_invocacao):  # pragma: no cover
            raise AssertionError("nao se usa")

        app = create_app(
            rotas_internas=rotas(
                credencial=lambda: "um-segredo-de-ensaio",
                executar=executar,
                admissao=admissao,
                trancas=TrancaFalsa(),
                eventos=monta(servidor),
            )
        )
        # Um evento de pagamento e **prioritario**, e por isso entra acima do
        # tecto: para medir a recusa enche-se o tecto **e** a reserva.
        async with admissao.vaga_de(TENANT):
            async with admissao.vaga_de(TENANT, prioritario=True):
                estado, cabecalhos, resposta = await self._entregar(corpo(), app=app)
        self.assertEqual(estado, 503)
        self.assertIn("retry-after", cabecalhos)
        self.assertEqual(json.loads(resposta)["outcome"], "tecto_do_tenant")

    async def _app_com(self, outbound):
        from kamba_agr.api_interna import rotas
        from kamba_agr.app import create_app

        servidor = com_conversa()

        async def executar(_invocacao):  # pragma: no cover
            raise AssertionError("nao se usa")

        return create_app(
            rotas_internas=rotas(
                credencial=lambda: "um-segredo-de-ensaio",
                executar=executar,
                admissao=self.admissao,
                trancas=TrancaFalsa(),
                eventos=monta(servidor, outbound=outbound),
            )
        )



if __name__ == "__main__":  # pragma: no cover
    unittest.main()
