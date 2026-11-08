"""Os direitos do titular (KAM-070, criterios 1, 2, 3, 6, 7 e 8).

Sem base de dados: as decisoes sao puras e o que as liga a base e um **cursor**
injectado. O que corre contra um PostgreSQL real e o esquema, em
`db/tests/test_direitos_schema.py`.

## O duplo de base le o TEXTO da instrucao, e e isso que faz destes ensaios prova

Esta casa mediu o defeito: **um duplo que decide pelo argumento nao mede o
predicado.** Um `CursorFalso` que devolvesse «as linhas do `contact_id` que me
passaram» ficava verde com o `AND contact_id = %s` **apagado** da consulta,
porque continuava a receber o `contact_id` na tupla de parametros — e a
exportacao de um titular passava a trazer as conversas de todos os clientes
daquele tenant sem nenhum ensaio mudar de cor.

O `BaseQueLeAInstrucao` filtra **so se o texto da instrucao tiver o filtro**.
Com o predicado, devolve a linha do titular; sem ele, devolve tambem a do
canario de outro contacto. Logo:

    apagar o filtro da consulta  ->  `test_a_exportacao_nao_traz_outro_contacto`
                                     falha, porque o canario aparece

E ha um **canario do proprio duplo** — `test_canario_a_base_falsa_morde` —, que
apaga o predicado de uma copia da consulta e exige que a fuga aconteca. Sem ele,
um duplo que filtrasse sempre deixava o ensaio de cima verde para sempre e
ninguem saberia que ele nao media nada.

## E o fecho le o ledger, nao conta eventos

O `test_seis_entregas_do_mesmo_escopo_nao_fecham_o_pedido` e o ensaio que morre
se alguem trocar a leitura do `erasure_ledger` por uma contagem de eventos
`privacy.erasure_applied`. Nao e hipotetico: o contrato publicado desse evento
tem **um** campo de `payload` — o `contact_id` — e nao diz quem aplicou, pelo que
uma contagem fecharia o pedido a sexta reentrega do mesmo consumidor.
"""

from __future__ import annotations

import json
import unittest
from datetime import datetime, timedelta, timezone

from kamba_core.direitos import (
    ALERTA_AOS_DIAS,
    ESCOPOS,
    ESTADO_CONCLUIDO,
    ESTADO_RECEBIDO,
    EVENTO_CONSENT_WITHDRAWN,
    EVENTO_ERASURE_APPLIED,
    EVENTO_ERASURE_REQUESTED,
    FINALIDADE_DA_OPOSICAO,
    PAPEL_POR_OMISSAO,
    PRAZO_INTERNO_DIAS,
    TIPO_ELIMINACAO,
    TIPO_EXPORTACAO,
    TIPO_OPOSICAO,
    TIPO_RECTIFICACAO,
    TTL_DA_EXPORTACAO_S,
    ApagamentoIncompleto,
    Pedido,
    PedidoDeOutroTitular,
    PortaDeDireitos,
    SujeitoApagado,
    apagamento_completo,
    escopos_em_falta,
    exigir_apagamento_completo,
    exportar,
    opor,
    pedir_apagamento,
    prazo_interno,
    registar_aplicacao,
    sujeitos_a_reaplicar,
)
from kamba_core.direitos.consultas import EXPORTACAO, PREDICADO_DO_CONTACTO
from kamba_core.direitos.exportacao import documento, entregar, resumo

TENANT = "3f1c2a9e-0d4b-4e55-9a7c-1b2c3d4e5f60"
TITULAR = "7c1d5e3a-2b4f-4a6c-8d0e-1f2a3b4c5d6e"
OUTRO = "9b2f6c1a-7e3d-4c80-b5a1-2d9e8f7a6b50"
RECEBIDO = datetime(2026, 11, 8, 10, 0, tzinfo=timezone.utc)

#: O valor que nao pode aparecer numa exportacao do `TITULAR`. Se aparecer, a
#: consulta perdeu o filtro do contacto.
CANARIO_DE_OUTRO = "canario-do-outro-contacto"


class RelogioParado:
    """Um relogio que conta as leituras. E o que prova «uma leitura por decisao».

    Nao e um relogio fixo: cada chamada avanca um segundo. Com um relogio
    constante, dois `agora()` dentro do mesmo `receber` eram indistinguiveis de
    um — e o ensaio da aritmetica do prazo passava com a leitura dupla, que e
    exactamente o defeito que a *cache* do KAM-069 teve.
    """

    def __init__(self, inicio: datetime = RECEBIDO) -> None:
        self._inicio = inicio
        self.leituras = 0

    def agora(self) -> datetime:
        agora = self._inicio + timedelta(seconds=self.leituras)
        self.leituras += 1
        return agora


class AuditoriaFalsa:
    def __init__(self) -> None:
        self.registos: list[dict[str, object]] = []

    def registar(self, *, tenant_id, accao, contact_id, detalhe) -> None:
        self.registos.append(
            {
                "tenant_id": tenant_id,
                "accao": accao,
                "contact_id": contact_id,
                "detalhe": dict(detalhe),
            }
        )


class InstrucaoSemFiltroDoContacto(AssertionError):
    """O duplo recusou responder a uma consulta de exportacao sem o filtro."""


class BaseQueLeAInstrucao:
    """Um cursor que decide pelo **texto** da instrucao, nao pelos argumentos.

    E a unica forma de um duplo medir um predicado SQL. Guarda duas linhas em
    cada tabela da exportacao — a do titular e a de um canario de outro contacto
    — e **filtra so se o texto contiver o `PREDICADO_DO_CONTACTO`**.
    """

    #: As colunas que cada coleccao devolve. Nao precisam de ser as reais: o que
    #: importa e haver `contact_id` para filtrar e um campo onde o canario se ve.
    COLUNAS = ("contact_id", "marca")

    def __init__(self) -> None:
        self.executadas: list[tuple[str, tuple]] = []
        self.ledger: list[tuple[str, str]] = []
        self.eventos: list[tuple[str, dict]] = []
        self.oposicoes: list[tuple] = []
        self.description: tuple | None = None
        self._resultado: list[tuple] = []
        self._contador = 0

    # -- o protocolo de cursor que os modulos usam -------------------------

    def execute(self, sql: str, params: tuple = ()) -> None:
        self.executadas.append((sql, tuple(params)))
        self.description = None
        self._resultado = self._responder(sql, tuple(params))

    def fetchone(self):
        return self._resultado[0] if self._resultado else None

    def fetchall(self):
        return list(self._resultado)

    # -- as respostas, lidas do texto -------------------------------------

    #: As tabelas e vistas que as consultas da exportacao leem.
    #:
    #: O despacho e **pela tabela** e nao por igualdade com o `EXPORTACAO`, e e
    #: preciso que seja: o canario do proprio duplo passa uma **copia alterada**
    #: da consulta, e um despacho por igualdade nao a reconhecia — recusava-a
    #: como «instrucao nao prevista» e o canario dava verde pela razao errada,
    #: que e o modo de falha que ele existe para apanhar nos outros.
    FONTES_DA_EXPORTACAO = (
        "platform.contacts",
        "platform.conversations",
        "platform.orders_mirror",
        "platform.consent_actual",
    )

    def _responder(self, sql: str, params: tuple) -> list[tuple]:
        if any(fonte in sql for fonte in self.FONTES_DA_EXPORTACAO):
            return self._exportar(sql, params)
        if "platform.evt_emitir" in sql:
            return self._emitir(sql, params)
        if "INSERT INTO platform.erasure_ledger" in sql:
            return self._registar(params)
        if "FROM platform.erasure_ledger" in sql:
            return self._escopos(params)
        if "INSERT INTO platform.consent_event" in sql:
            return self._opor(sql, params)
        raise AssertionError(f"instrucao nao prevista pelo duplo: {sql[:80]!r}")

    def _exportar(self, sql: str, params: tuple) -> list[tuple]:
        self.description = tuple((coluna,) for coluna in self.COLUNAS)
        linhas = [(TITULAR, "a-do-titular"), (OUTRO, CANARIO_DE_OUTRO)]
        if PREDICADO_DO_CONTACTO not in sql:
            # **Nao filtra**, de proposito: e o unico comportamento que faz o
            # ensaio notar a falta do predicado. Um duplo que filtrasse pelo
            # argumento ficava verde com a consulta estragada.
            return linhas
        if not params:
            raise InstrucaoSemFiltroDoContacto(
                "a consulta tem o filtro e nao recebeu o contacto"
            )
        return [linha for linha in linhas if linha[0] == params[0]]

    def _emitir(self, sql: str, params: tuple) -> list[tuple]:
        (
            tipo,
            _versao,
            _tenant,
            _agregado,
            payload,
            _classe,
            _finalidades,
            correlacao,
        ) = params
        self.eventos.append((tipo, json.loads(payload), correlacao))
        self._contador += 1
        return [(f"evento-{self._contador}",)]

    def _registar(self, params: tuple) -> list[tuple]:
        tenant, dsar_id, contacto, escopo, aplicado = params
        if (dsar_id, escopo) in self.ledger:
            # E a unicidade `(tenant_id, dsar_id, escopo)` da revisao `0037`,
            # imitada: `ON CONFLICT DO NOTHING` nao devolve linha.
            return []
        self.ledger.append((dsar_id, escopo))
        self._contador += 1
        return [(f"ledger-{self._contador}", tenant, dsar_id, contacto, escopo, aplicado)]

    def _escopos(self, params: tuple) -> list[tuple]:
        dsar_id = params[0]
        return [
            (escopo,)
            for dsar, escopo in sorted(self.ledger)
            if dsar == dsar_id
        ]

    def _opor(self, sql: str, params: tuple) -> list[tuple]:
        if "false" not in sql:
            raise AssertionError(
                "a oposicao tem de escrever `accepted = false` por literal"
            )
        prova = params[5]
        if any(anterior[5] == prova for anterior in self.oposicoes):
            return []
        self.oposicoes.append(params)
        self._contador += 1
        return [(f"consent-{self._contador}",)]


def pedido(tipo: str, *, contacto: str = TITULAR, dsar_id: str = "d-1") -> Pedido:
    return Pedido(
        dsar_id=dsar_id,
        tenant_id=TENANT,
        contact_id=contacto,
        tipo=tipo,
        estado=ESTADO_RECEBIDO,
        papel_kamba=PAPEL_POR_OMISSAO,
        recebido_at=RECEBIDO,
        prazo_dias=PRAZO_INTERNO_DIAS,
        prazo_interno_at=prazo_interno(RECEBIDO),
    )


class TestOFiltroDoContacto(unittest.TestCase):
    """Criterio 2: «nenhum dado de outro contacto ou tenant aparece»."""

    def test_toda_a_consulta_da_exportacao_filtra_pelo_contacto(self) -> None:
        """Itera o mapa e nao uma lista escrita aqui: uma consulta nova e medida.

        Uma lista a mao no ensaio provava as coleccoes de que alguem se lembrou.
        """
        self.assertTrue(EXPORTACAO, "o mapa da exportacao nao pode estar vazio")
        for nome, sql in EXPORTACAO.items():
            with self.subTest(coleccao=nome):
                self.assertIn(
                    PREDICADO_DO_CONTACTO,
                    sql,
                    "sem o filtro do contacto, a exportacao de um titular traz "
                    "as linhas de todos os clientes do tenant",
                )

    def test_a_exportacao_nao_traz_outro_contacto(self) -> None:
        cursor = BaseQueLeAInstrucao()
        saida = exportar(cursor, pedido(TIPO_EXPORTACAO))
        for nome, linhas in saida["coleccoes"].items():
            with self.subTest(coleccao=nome):
                marcas = [linha["marca"] for linha in linhas]
                self.assertNotIn(CANARIO_DE_OUTRO, marcas)
                self.assertEqual(marcas, ["a-do-titular"])

    def test_canario_a_base_falsa_morde(self) -> None:
        """Sem o predicado, o duplo **deixa** passar o canario.

        E a prova de que o ensaio de cima mede algo. Sem este, um duplo que
        filtrasse sempre deixava-o verde para sempre.
        """
        cursor = BaseQueLeAInstrucao()
        sem_filtro = EXPORTACAO["conversas"].replace(PREDICADO_DO_CONTACTO, "true")
        cursor.execute(sem_filtro, (TITULAR,))
        marcas = [linha[1] for linha in cursor.fetchall()]
        self.assertIn(CANARIO_DE_OUTRO, marcas)

    def test_as_quatro_coleccoes_do_criterio_estao_na_saida(self) -> None:
        saida = exportar(BaseQueLeAInstrucao(), pedido(TIPO_EXPORTACAO))
        self.assertEqual(
            set(saida["coleccoes"]),
            {"contacto", "conversas", "encomendas", "consentimentos"},
        )


class TestOPedidoSoDoTitular(unittest.TestCase):
    """Criterio 1: «aceite so do mesmo BSUID do contacto»."""

    def porta(self):
        self.relogio = RelogioParado()
        self.auditoria = AuditoriaFalsa()
        return PortaDeDireitos(relogio=self.relogio, auditoria=self.auditoria)

    def test_o_alvo_por_omissao_e_o_proprio_requerente(self) -> None:
        """O caso certo e o que sai de uma chamada sem pensar no assunto."""
        porta = self.porta()
        cursor = CursorDoPedido()
        criado = porta.receber(
            cursor, tenant_id=TENANT, requerente=TITULAR, tipo=TIPO_EXPORTACAO
        )
        self.assertEqual(criado.contact_id, TITULAR)

    def test_um_pedido_sobre_outro_titular_devolve_zero_dados(self) -> None:
        porta = self.porta()
        cursor = CursorDoPedido()
        with self.assertRaises(PedidoDeOutroTitular):
            porta.receber(
                cursor,
                tenant_id=TENANT,
                requerente=TITULAR,
                tipo=TIPO_EXPORTACAO,
                alvo=OUTRO,
            )
        self.assertEqual(
            cursor.executadas,
            [],
            "a recusa nao pode ter escrito linha nenhuma de dsar_requests",
        )

    def test_a_recusa_fica_registada_e_antes_de_levantar(self) -> None:
        """«devolve 0 dados **e fica registado**», e a ordem importa.

        Com a excepcao primeiro, o registo ficava dependente de quem a apanha —
        e um registo que depende disso nao e um registo.
        """
        porta = self.porta()
        with self.assertRaises(PedidoDeOutroTitular):
            porta.receber(
                CursorDoPedido(),
                tenant_id=TENANT,
                requerente=TITULAR,
                tipo=TIPO_EXPORTACAO,
                alvo=OUTRO,
            )
        self.assertEqual(len(self.auditoria.registos), 1)
        registo = self.auditoria.registos[0]
        self.assertEqual(registo["accao"], "privacy.dsar_recusado")
        self.assertEqual(registo["contact_id"], TITULAR)

    def test_a_mensagem_da_recusa_nao_nomeia_contacto_nenhum(self) -> None:
        """A excepcao chega a *logs* comuns, que nao tem a autorizacao do `audit_log`."""
        texto = str(PedidoDeOutroTitular())
        self.assertNotIn(TITULAR, texto)
        self.assertNotIn(OUTRO, texto)

    def test_o_prazo_interno_e_recebido_mais_trinta_dias(self) -> None:
        porta = self.porta()
        criado = porta.receber(
            CursorDoPedido(), tenant_id=TENANT, requerente=TITULAR, tipo=TIPO_EXPORTACAO
        )
        self.assertEqual(
            criado.prazo_interno_at - criado.recebido_at,
            timedelta(days=PRAZO_INTERNO_DIAS),
        )

    def test_o_relogio_le_se_uma_vez_por_pedido(self) -> None:
        """Com duas leituras, a igualdade do criterio 1 falhava por um segundo."""
        porta = self.porta()
        porta.receber(
            CursorDoPedido(), tenant_id=TENANT, requerente=TITULAR, tipo=TIPO_EXPORTACAO
        )
        self.assertEqual(self.relogio.leituras, 1)

    def test_o_papel_da_kamba_tem_omissao_e_vai_na_linha(self) -> None:
        """A D9 esta aberta: a omissao e `subcontratada` e e visivel."""
        porta = self.porta()
        criado = porta.receber(
            CursorDoPedido(), tenant_id=TENANT, requerente=TITULAR, tipo=TIPO_EXPORTACAO
        )
        self.assertEqual(criado.papel_kamba, "subcontratada")


class CursorDoPedido:
    """Um cursor que devolve a linha do `dsar_requests` que lhe pedem criar.

    Le o texto: so responde a um `INSERT INTO platform.dsar_requests`, e devolve
    **os valores que a instrucao escreveu**, pela ordem do `COLUNAS_DO_PEDIDO`.
    Um duplo que devolvesse uma linha inventada deixava de medir que o
    `prazo_interno_at` e o `papel_kamba` chegam a base.
    """

    def __init__(self) -> None:
        self.executadas: list[tuple[str, tuple]] = []
        self._resultado: list[tuple] = []

    def execute(self, sql: str, params: tuple = ()) -> None:
        if "INSERT INTO platform.dsar_requests" not in sql:
            raise AssertionError(f"instrucao nao prevista: {sql[:60]!r}")
        self.executadas.append((sql, tuple(params)))
        tenant, contacto, tipo, estado, papel, recebido, dias, prazo = params
        self._resultado = [
            ("d-1", tenant, contacto, tipo, estado, papel, recebido, dias, prazo, None)
        ]

    def fetchone(self):
        return self._resultado[0] if self._resultado else None

    def fetchall(self):
        return list(self._resultado)


class TestOFechoLeOLedger(unittest.TestCase):
    """Criterio 3: «so passa a `concluido` quando **todos** aplicaram»."""

    def setUp(self) -> None:
        self.cursor = BaseQueLeAInstrucao()
        self.relogio = RelogioParado()
        self.pedido = pedido(TIPO_ELIMINACAO)

    def aplicar(self, *escopos: str) -> None:
        for escopo in escopos:
            registar_aplicacao(
                self.cursor,
                pedido=self.pedido,
                escopo=escopo,
                relogio=self.relogio,
            )

    def test_com_cinco_escopos_o_pedido_nao_fecha(self) -> None:
        self.aplicar(*ESCOPOS[:5])
        self.assertFalse(apagamento_completo(self.cursor, self.pedido.dsar_id))
        self.assertEqual(escopos_em_falta(self.cursor, self.pedido.dsar_id), (ESCOPOS[5],))

    def test_com_os_seis_o_pedido_fecha(self) -> None:
        self.aplicar(*ESCOPOS)
        self.assertTrue(apagamento_completo(self.cursor, self.pedido.dsar_id))
        exigir_apagamento_completo(self.cursor, self.pedido.dsar_id)

    def test_seis_entregas_do_mesmo_escopo_nao_fecham_o_pedido(self) -> None:
        """**O ensaio que morre se alguem contar eventos em vez de ler o ledger.**

        O contrato do `privacy.erasure_applied` nao diz quem aplicou: uma
        contagem de seis fechava o pedido a sexta reentrega do mesmo consumidor.
        """
        self.aplicar(*([ESCOPOS[0]] * 6))
        self.assertFalse(apagamento_completo(self.cursor, self.pedido.dsar_id))
        self.assertEqual(len(self.cursor.ledger), 1)

    def test_a_repeticao_do_mesmo_escopo_e_idempotente(self) -> None:
        """Criterio 8: a segunda chamada nao escreve, e nao e erro."""
        primeira = registar_aplicacao(
            self.cursor, pedido=self.pedido, escopo=ESCOPOS[0], relogio=self.relogio
        )
        segunda = registar_aplicacao(
            self.cursor, pedido=self.pedido, escopo=ESCOPOS[0], relogio=self.relogio
        )
        self.assertIsNotNone(primeira)
        self.assertIsNone(segunda)

    def test_o_que_falta_vem_nomeado_e_nao_contado(self) -> None:
        self.aplicar(*ESCOPOS[:4])
        with self.assertRaises(ApagamentoIncompleto) as apanhado:
            exigir_apagamento_completo(self.cursor, self.pedido.dsar_id)
        self.assertEqual(apanhado.exception.faltam, ESCOPOS[4:])
        for escopo in ESCOPOS[4:]:
            self.assertIn(escopo, str(apanhado.exception))

    def test_os_escopos_em_falta_vem_pela_ordem_do_criterio(self) -> None:
        """Nao alfabetica: a lista do criterio 3 tem uma ordem escrita."""
        self.assertEqual(escopos_em_falta(self.cursor, self.pedido.dsar_id), ESCOPOS)


class TestOsEventos(unittest.TestCase):
    def test_o_pedido_de_apagamento_anuncia_o_evento_do_contrato(self) -> None:
        cursor = BaseQueLeAInstrucao()
        pedir_apagamento(cursor, pedido(TIPO_ELIMINACAO))
        self.assertEqual(len(cursor.eventos), 1)
        tipo, payload, _ = cursor.eventos[0]
        self.assertEqual(tipo, EVENTO_ERASURE_REQUESTED)
        self.assertEqual(
            payload,
            {"contact_id": TITULAR},
            "o esquema publicado tem additionalProperties: false — um campo a "
            "mais faz o envelope violar o contrato do proprio evento",
        )

    def test_o_evento_leva_o_dsar_id_no_correlacao_id(self) -> None:
        """O ensaio que morre se o `correlacao_id` se desligar do pedido.

        O `payload` dos tres contratos tem `additionalProperties: false` e so o
        `contact_id` dentro, pelo que **nao ha sitio no `payload`** para dizer
        de que pedido se trata. Sem o `correlacao_id`, o consumidor que apaga
        tinha de procurar o pedido aberto daquele contacto — unico pelo indice,
        mas uma suposicao em vez de um dado. Este ensaio nao mede o `evt_emitir`:
        mede que o `dsar_id` **chega** ao envelope.
        """
        cursor = BaseQueLeAInstrucao()
        p = pedido(TIPO_ELIMINACAO, dsar_id="d-correlacao")
        pedir_apagamento(cursor, p)
        _tipo, _payload, correlacao = cursor.eventos[0]
        self.assertEqual(correlacao, "d-correlacao")
        self.assertNotIn(
            "dsar_id",
            _payload,
            "o dsar_id vai no envelope e nao no payload: o esquema publicado "
            "tem additionalProperties: false",
        )

    def test_a_oposicao_tambem_correlaciona_pelo_pedido(self) -> None:
        cursor = BaseQueLeAInstrucao()
        opor(cursor, pedido(TIPO_OPOSICAO, dsar_id="d-oposicao"))
        self.assertEqual(cursor.eventos[0][2], "d-oposicao")

    def test_o_tipo_do_pedido_e_que_autoriza_o_apagamento(self) -> None:
        """Um pedido de exportacao nao autoriza um evento de apagamento."""
        with self.assertRaises(ValueError):
            pedir_apagamento(BaseQueLeAInstrucao(), pedido(TIPO_EXPORTACAO))

    def test_o_anuncio_da_aplicacao_usa_o_segundo_tipo(self) -> None:
        from kamba_core.direitos import anunciar_aplicacao

        cursor = BaseQueLeAInstrucao()
        anunciar_aplicacao(cursor, pedido(TIPO_ELIMINACAO))
        self.assertEqual(cursor.eventos[0][0], EVENTO_ERASURE_APPLIED)


class TestAOposicao(unittest.TestCase):
    """Criterio 7: «oposicao registra `consent.withdrawn` e entra na lista PARAR»."""

    def test_entra_na_lista_do_kam_022_e_nao_numa_nova(self) -> None:
        cursor = BaseQueLeAInstrucao()
        escreveu, _ = opor(cursor, pedido(TIPO_OPOSICAO))
        self.assertTrue(escreveu)
        sql, params = next(
            (s, p) for s, p in cursor.executadas if "consent_event" in s
        )
        self.assertIn("platform.consent_event", sql)
        self.assertEqual(params[2], FINALIDADE_DA_OPOSICAO)
        self.assertIn(
            "false",
            sql,
            "a lista de supressao do KAM-022 e purpose='marketing' com "
            "accepted=false: e nessa que o titular entra, nao numa segunda",
        )

    def test_anuncia_o_consent_withdrawn(self) -> None:
        cursor = BaseQueLeAInstrucao()
        opor(cursor, pedido(TIPO_OPOSICAO))
        tipo, payload, _ = cursor.eventos[0]
        self.assertEqual(tipo, EVENTO_CONSENT_WITHDRAWN)
        self.assertEqual(
            payload, {"contact_id": TITULAR, "finalidade": FINALIDADE_DA_OPOSICAO}
        )

    def test_opor_se_duas_vezes_pelo_mesmo_pedido_escreve_uma(self) -> None:
        """Criterio 8, e a chave e a da `0015`: o resumo e determinista."""
        cursor = BaseQueLeAInstrucao()
        primeira, _ = opor(cursor, pedido(TIPO_OPOSICAO))
        segunda, _ = opor(cursor, pedido(TIPO_OPOSICAO))
        self.assertTrue(primeira)
        self.assertFalse(segunda)
        self.assertEqual(len(cursor.oposicoes), 1)

    def test_o_anuncio_sai_mesmo_quando_a_linha_ja_existia(self) -> None:
        """Calar o anuncio deixava um consumidor que falhou sem o voltar a ouvir."""
        cursor = BaseQueLeAInstrucao()
        opor(cursor, pedido(TIPO_OPOSICAO))
        opor(cursor, pedido(TIPO_OPOSICAO))
        self.assertEqual(len(cursor.eventos), 2)

    def test_pedidos_diferentes_dao_provas_diferentes(self) -> None:
        cursor = BaseQueLeAInstrucao()
        opor(cursor, pedido(TIPO_OPOSICAO, dsar_id="d-1"))
        opor(cursor, pedido(TIPO_OPOSICAO, dsar_id="d-2"))
        self.assertEqual(len(cursor.oposicoes), 2)

    def test_o_tipo_do_pedido_e_que_autoriza_a_oposicao(self) -> None:
        with self.assertRaises(ValueError):
            opor(BaseQueLeAInstrucao(), pedido(TIPO_RECTIFICACAO))


class TestOTectoDoTtl(unittest.TestCase):
    """Criterio 2: «URL assinada com TTL <= 5 min», e **uma** leitora do limite."""

    def test_o_tecto_e_o_do_storage_e_nao_um_segundo(self) -> None:
        """O ensaio que morre se alguem voltar a declarar o tecto aqui.

        Duas constantes com o mesmo significado em modulos diferentes nao sao
        comparadas por portao nenhum deste repositorio: no dia em que uma
        subisse, a outra continuava a dizer que o criterio estava cumprido.
        """
        from kamba_core.storage.port import TTL_MAXIMO_S

        self.assertIs(TTL_DA_EXPORTACAO_S, TTL_MAXIMO_S)
        self.assertEqual(TTL_DA_EXPORTACAO_S, 300)

    def test_entregar_delega_a_validacao_em_quem_a_tem(self) -> None:
        pedidos_ao_assinador: list[int] = []

        class AssinadorQueValida:
            def sign_url(self, ctx, ref, *, ttl_seconds):
                pedidos_ao_assinador.append(ttl_seconds)
                if not 1 <= ttl_seconds <= TTL_DA_EXPORTACAO_S:
                    raise ValueError("ttl fora do intervalo")
                return "https://exemplo/assinado"

        assinador = AssinadorQueValida()
        self.assertEqual(
            entregar(assinador, "ctx", "ref"), "https://exemplo/assinado"
        )
        self.assertEqual(pedidos_ao_assinador, [TTL_DA_EXPORTACAO_S])
        with self.assertRaises(ValueError):
            entregar(assinador, "ctx", "ref", ttl_s=TTL_DA_EXPORTACAO_S + 1)


class TestODocumento(unittest.TestCase):
    def test_o_resumo_nao_depende_de_quem_serializou(self) -> None:
        um = exportar(BaseQueLeAInstrucao(), pedido(TIPO_EXPORTACAO))
        outro = exportar(BaseQueLeAInstrucao(), pedido(TIPO_EXPORTACAO))
        self.assertEqual(resumo(documento(um)), resumo(documento(outro)))

    def test_o_documento_declara_o_formato_por_dentro(self) -> None:
        texto = documento(
            exportar(BaseQueLeAInstrucao(), pedido(TIPO_EXPORTACAO))
        ).decode("utf-8")
        self.assertIn('"formato":1', texto)


class TestOsPrazos(unittest.TestCase):
    """Criterio 8: «o prazo interno gera alerta aos 20 dias»."""

    def pedido_aberto(self) -> Pedido:
        return pedido(TIPO_ELIMINACAO)

    def test_antes_dos_vinte_dias_nao_ha_alerta(self) -> None:
        p = self.pedido_aberto()
        self.assertFalse(p.alerta_devido(RECEBIDO + timedelta(days=ALERTA_AOS_DIAS - 1)))

    def test_ao_vigesimo_dia_o_alerta_e_devido(self) -> None:
        p = self.pedido_aberto()
        self.assertTrue(p.alerta_devido(RECEBIDO + timedelta(days=ALERTA_AOS_DIAS)))

    def test_depois_do_prazo_o_alerta_continua_devido(self) -> None:
        """Um alerta que se calasse ao passar o prazo calava-se quando mais faz falta."""
        p = self.pedido_aberto()
        self.assertTrue(p.alerta_devido(RECEBIDO + timedelta(days=90)))
        self.assertTrue(p.em_atraso(RECEBIDO + timedelta(days=90)))

    def test_um_pedido_concluido_nunca_esta_em_atraso(self) -> None:
        concluido = Pedido(
            dsar_id="d-1",
            tenant_id=TENANT,
            contact_id=TITULAR,
            tipo=TIPO_ELIMINACAO,
            estado=ESTADO_CONCLUIDO,
            papel_kamba=PAPEL_POR_OMISSAO,
            recebido_at=RECEBIDO,
            prazo_dias=PRAZO_INTERNO_DIAS,
            prazo_interno_at=prazo_interno(RECEBIDO),
            concluido_at=RECEBIDO + timedelta(days=45),
        )
        self.assertFalse(concluido.em_atraso(RECEBIDO + timedelta(days=90)))
        self.assertFalse(concluido.alerta_devido(RECEBIDO + timedelta(days=90)))


class TestAReaplicacaoAposRestauro(unittest.TestCase):
    """Criterio 6, e a fronteira e a mesma que a *fixture* do KAM-079 declara."""

    def ledger(self) -> tuple[SujeitoApagado, ...]:
        return (
            SujeitoApagado("antes", RECEBIDO - timedelta(days=5)),
            SujeitoApagado("na-fronteira", RECEBIDO),
            SujeitoApagado("duas-horas-depois", RECEBIDO + timedelta(hours=2)),
            SujeitoApagado("um-dia-depois", RECEBIDO + timedelta(days=1)),
        )

    def test_so_os_apagados_depois_da_copia_se_reaplicam(self) -> None:
        saida = sujeitos_a_reaplicar(self.ledger(), RECEBIDO)
        self.assertEqual(
            [s.contact_id for s in saida], ["duas-horas-depois", "um-dia-depois"]
        )

    def test_a_fronteira_nao_se_reaplica(self) -> None:
        """`T' == T`: quem foi apagado no instante da copia nao esta nela."""
        saida = sujeitos_a_reaplicar(self.ledger(), RECEBIDO)
        self.assertNotIn("na-fronteira", [s.contact_id for s in saida])

    def test_nao_devolve_o_ledger_inteiro(self) -> None:
        """Reaplicar tudo fazia `DELETE` sobre linhas inexistentes."""
        self.assertLess(len(sujeitos_a_reaplicar(self.ledger(), RECEBIDO)), 4)

    def test_a_ordem_e_cronologica(self) -> None:
        saida = sujeitos_a_reaplicar(self.ledger(), RECEBIDO - timedelta(days=10))
        self.assertEqual([s.erased_at for s in saida], sorted(s.erased_at for s in saida))

    def test_e_idempotente(self) -> None:
        ledger = self.ledger()
        self.assertEqual(
            sujeitos_a_reaplicar(ledger, RECEBIDO),
            sujeitos_a_reaplicar(ledger, RECEBIDO),
        )


class TestOsDominiosNaoDivergemDaRevisao(unittest.TestCase):
    """Os dominios estao escritos em **tres** sitios, e nenhum portao os compara.

    A revisao `0037` escreve cada dominio duas vezes — a tupla e a cadeia de
    literais do `CHECK` —, porque o *gate* 3b le a revisao sem a correr e um
    `", ".join(...)` deixa o SQL ilegivel para ele (e a razao que a `0006` ja
    escreveu). E este modulo escreve-os uma terceira vez, porque um modulo que
    importasse constantes de uma revisao de Alembic passava a depender de
    `alembic` para correr.

    Tres superficies com o mesmo significado, e **nenhuma ferramenta deste
    repositorio as compara**: o `canon_lint` ve nomes, o `lint_arch` ve
    dependencias, o `lint_bloco` ve blocos. E a classe de defeito que a revisao
    adversarial do KAM-069 nomeou — duas leitoras da mesma coisa divergem sem
    dar erro em sitio nenhum. Este ensaio e a comparacao que falta, e corre **sem
    PostgreSQL**: le a revisao como texto.

    O que ele apanha, concretamente: acrescentar um escopo ao `ESCOPOS` deste
    modulo e esquecer o `CHECK` da base. Nesse estado o fecho do criterio 3
    exigia sete escopos e a base recusava o setimo — um pedido que nunca
    fechava, sem nenhum ensaio vermelho.
    """

    @classmethod
    def setUpClass(cls) -> None:
        import pathlib

        raiz = pathlib.Path(__file__).resolve().parents[3]
        cls.revisao = (
            raiz / "db" / "migrations" / "versions" / "0037_direitos_do_titular.py"
        ).read_text(encoding="utf-8")

    def exigir(self, constante: str, valores: tuple[str, ...]) -> None:
        esperado = ", ".join(f"'{valor}'" for valor in valores)
        self.assertIn(
            f'{constante} = "{esperado}"',
            self.revisao,
            f"o {constante} da revisao 0037 divergiu deste modulo",
        )

    def test_os_tipos_sao_os_mesmos(self) -> None:
        from kamba_core.direitos import TIPOS

        self.exigir("LITERAIS_DE_TIPO", TIPOS)

    def test_os_escopos_sao_os_mesmos(self) -> None:
        self.exigir("LITERAIS_DE_ESCOPO", ESCOPOS)

    def test_os_estados_sao_os_mesmos(self) -> None:
        from kamba_core.direitos import ESTADOS

        self.exigir("LITERAIS_DE_ESTADO", ESTADOS)

    def test_os_papeis_sao_os_mesmos(self) -> None:
        from kamba_core.direitos import PAPEIS_DA_KAMBA

        self.exigir("LITERAIS_DE_PAPEL", PAPEIS_DA_KAMBA)

    def test_as_accoes_de_auditoria_entram_no_dominio_da_revisao(self) -> None:
        """As duas accoes novas tem de estar no `CHECK` que a revisao repoe.

        Sem isto, escrever a recusa do criterio 1 levantava `23514` **em
        producao** e em nenhum ensaio sem PostgreSQL.
        """
        from kamba_core.direitos import ACCOES_DE_DSAR

        for accao in ACCOES_DE_DSAR:
            with self.subTest(accao=accao):
                self.assertIn(f"'{accao}'", self.revisao)

    def test_canario_um_dominio_alterado_reprova(self) -> None:
        """A prova de que a comparacao morde, e nao so de que corre."""
        with self.assertRaises(AssertionError):
            self.exigir("LITERAIS_DE_ESCOPO", ESCOPOS + ("inventado",))


class TestAsFontesDaExportacao(unittest.TestCase):
    def test_a_exportacao_le_so_as_quatro_fontes_declaradas(self) -> None:
        """Uma quinta fonte entra pelo mapa, e tem de entrar tambem no duplo.

        Sem isto, uma coleccao nova respondia pelo ramo de erro do duplo — ou,
        pior, por um ramo que devolve linhas sem o filtro do contacto.
        """
        for nome, sql in EXPORTACAO.items():
            with self.subTest(coleccao=nome):
                self.assertTrue(
                    any(
                        fonte in sql
                        for fonte in BaseQueLeAInstrucao.FONTES_DA_EXPORTACAO
                    ),
                    "a consulta le uma tabela que o duplo nao conhece",
                )


if __name__ == "__main__":
    unittest.main()
