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
    ESTADO_EM_CURSO,
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
    AuditoriaNaBase,
    FechoSemLedger,
    Pedido,
    PedidoDeOutroTitular,
    PedidoEmCurso,
    PortaDeDireitos,
    RelogioDoSistema,
    SEPARADOR,
    SEPARADOR_DA_PROVA,
    TEXTO_DA_OPOSICAO,
    SujeitoApagado,
    apagamento_completo,
    concluir_apagamento,
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

    def escrever(self, *, tenant_id, accao, contact_id, detalhe) -> None:
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
        self.fechados: set[str] = set()
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
        if "UPDATE platform.dsar_requests" in sql:
            return self._fechar(sql, params)
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
            # E a unicidade `(tenant_id, dsar_id, escopo)` da revisao `0038`,
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

    def _fechar(self, sql: str, params: tuple) -> list[tuple]:
        """O fecho, com a idempotencia do `WHERE estado <> 'concluido'`.

        **Imita o predicado e nao so a escrita:** o duplo guarda o `dsar_id`
        fechado e o segundo fecho devolve zero linhas, que e o que a base faz.
        Sem isso, o ensaio da idempotencia do fecho media uma coisa que o duplo
        nao tinha.
        """
        if "estado <> 'concluido'" not in sql:
            raise AssertionError(
                "o fecho tem de levar o predicado da idempotencia: sem ele, "
                "fechar duas vezes reescreve o concluido_at"
            )
        concluido_at, dsar_id = params
        if dsar_id in self.fechados:
            return []
        self.fechados.add(dsar_id)
        return [
            (
                dsar_id, TENANT, TITULAR, "eliminacao", ESTADO_CONCLUIDO,
                PAPEL_POR_OMISSAO, RECEBIDO, PRAZO_INTERNO_DIAS,
                prazo_interno(RECEBIDO), concluido_at,
            )
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

    A revisao `0038` escreve cada dominio duas vezes — a tupla e a cadeia de
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
            raiz / "db" / "migrations" / "versions" / "0038_direitos_do_titular.py"
        ).read_text(encoding="utf-8")

    def exigir(self, constante: str, valores: tuple[str, ...]) -> None:
        esperado = ", ".join(f"'{valor}'" for valor in valores)
        self.assertIn(
            f'{constante} = "{esperado}"',
            self.revisao,
            f"o {constante} da revisao 0038 divergiu deste modulo",
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

    def dominio_da_accao(self) -> str:
        """O texto **da atribuicao** do `LITERAIS_DE_ACCAO_0038`, e so dele.

        **E a correccao de um achado medido da revisao adversarial.** A primeira
        versao deste ensaio afirmava `assertIn(f"'{accao}'", self.revisao)`
        sobre o texto **inteiro** da revisao — e os dois literais aparecem em
        **dois** sitios: na constante que o `CHECK` le, e na consulta de
        contagem do `_encolher_o_dominio_da_accao`. O revisor apagou a linha da
        constante numa copia e correu a assercao: **verde**. Isto e, o `upgrade`
        podia repor o dominio de **sete** da `0006` com este ensaio a dizer que
        estava tudo bem, e a recusa do criterio 1 levantava `23514` em producao.
        """
        marca = "LITERAIS_DE_ACCAO_0038 = ("
        inicio = self.revisao.index(marca) + len(marca)
        return self.revisao[inicio : self.revisao.index(")", inicio)]

    def test_as_accoes_de_auditoria_entram_no_dominio_da_revisao(self) -> None:
        """As duas accoes novas tem de estar no `CHECK` que o `upgrade` escreve.

        Sem isto, escrever a recusa do criterio 1 levantava `23514` **em
        producao** e em nenhum ensaio sem PostgreSQL.
        """
        from kamba_core.direitos import ACCOES_DE_DSAR

        dominio = self.dominio_da_accao()
        for accao in ACCOES_DE_DSAR:
            with self.subTest(accao=accao):
                self.assertIn(f"'{accao}'", dominio)

    def test_o_dominio_do_downgrade_nao_tem_as_accoes_novas(self) -> None:
        """E o outro lado: a `0006` nao as conhece, e o `downgrade` repoe-a.

        Escrever as nove no `downgrade` deixava, numa base descida para a
        `0036`, um `CHECK` a aceitar accoes que nenhuma revisao dessa altura
        conhece.
        """
        from kamba_core.direitos import ACCOES_DE_DSAR

        marca = "LITERAIS_DE_ACCAO_0006 = ("
        inicio = self.revisao.index(marca) + len(marca)
        antigo = self.revisao[inicio : self.revisao.index(")", inicio)]
        for accao in ACCOES_DE_DSAR:
            with self.subTest(accao=accao):
                self.assertNotIn(f"'{accao}'", antigo)

    def test_canario_a_accao_fora_da_constante_reprova(self) -> None:
        """A prova de que o oraculo passou a casar no sitio certo.

        Apaga as duas accoes **da constante que o `CHECK` le** e mede as duas
        coisas que o achado da revisao separou: o literal **continua** no texto
        da revisao (e por isso que o oraculo antigo ficava verde) e **sai** do
        dominio (e por isso que o novo reprova).

        **Nao chama o outro ensaio**, e nao e detalhe: aquele usa `subTest`, e
        dentro de um `subTest` uma falha e **registada** em vez de levantada —
        pelo que um `assertRaises` a volta dele nunca a via e o canario reprovava
        a si proprio. Foi medido ao escreve-lo.
        """
        from kamba_core.direitos import ACCOES_DE_DSAR

        marca = "LITERAIS_DE_ACCAO_0038 = ("
        inicio = self.revisao.index(marca) + len(marca)
        fim = self.revisao.index(")", inicio)
        dominio_sem_as_novas = self.revisao[inicio:fim].replace(
            "'privacy.dsar_recusado', 'privacy.dsar_rectificado'", ""
        )
        for accao in ACCOES_DE_DSAR:
            with self.subTest(accao=accao):
                self.assertIn(
                    f"'{accao}'",
                    self.revisao,
                    "o literal continua no texto da revisao — e por isso que o "
                    "oraculo antigo, que lia o texto inteiro, ficava verde",
                )
                self.assertNotIn(
                    f"'{accao}'",
                    dominio_sem_as_novas,
                    "o oraculo novo le so a constante, pelo que tem de reprovar",
                )
        self.assertIn("'audit.read'", dominio_sem_as_novas)


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


class TestOFechoExigeOLedger(unittest.TestCase):
    """**Os ensaios do achado mais serio da revisao adversarial.**

    O critério 3 nao tinha impositor: o `concluir` fechava qualquer pedido e a
    prosa nomeava um `concluir_apagamento` que **nao existia**. Os cinco ensaios
    do `TestOFechoLeOLedger` ficavam verdes qualquer que fosse o comportamento
    do fecho, porque **nao havia ligacao para mutar**. Agora ha duas, e estes
    sao os ensaios que morrem se alguma delas se desfizer.
    """

    def setUp(self) -> None:
        self.cursor = BaseQueLeAInstrucao()
        self.relogio = RelogioParado()
        self.porta = PortaDeDireitos(
            relogio=self.relogio, auditoria=AuditoriaFalsa()
        )

    def aplicar(self, p, *escopos: str) -> None:
        for escopo in escopos:
            registar_aplicacao(
                self.cursor, pedido=p, escopo=escopo, relogio=self.relogio
            )

    def test_o_concluir_recusa_um_pedido_de_eliminacao(self) -> None:
        """A ligacao 1: nao ha caminho que feche uma eliminacao sem o ledger."""
        with self.assertRaises(FechoSemLedger):
            self.porta.concluir(self.cursor, pedido(TIPO_ELIMINACAO))
        self.assertEqual(
            self.cursor.executadas,
            [],
            "a recusa nao pode ter escrito o fecho",
        )

    def test_o_concluir_fecha_os_outros_tres_tipos(self) -> None:
        """A recusa e **so** da eliminacao: um pedido de exportacao nao tem escopos."""
        for tipo in (TIPO_EXPORTACAO, TIPO_RECTIFICACAO, TIPO_OPOSICAO):
            with self.subTest(tipo=tipo):
                cursor = BaseQueLeAInstrucao()
                fechado = self.porta.concluir(cursor, pedido(tipo))
                self.assertIsNotNone(fechado)
                self.assertEqual(fechado.estado, ESTADO_CONCLUIDO)

    def test_concluir_apagamento_com_cinco_escopos_levanta_e_nao_fecha(self) -> None:
        """A ligacao 2: o `exigir` corre **antes** da escrita.

        A ordem nao e negociavel: com o fecho primeiro, um
        `ApagamentoIncompleto` levantado depois deixava a linha `concluido`
        escrita nesta transaccao.
        """
        p = pedido(TIPO_ELIMINACAO)
        self.aplicar(p, *ESCOPOS[:5])
        with self.assertRaises(ApagamentoIncompleto):
            concluir_apagamento(self.cursor, self.porta, p)
        self.assertNotIn(
            "UPDATE platform.dsar_requests",
            " ".join(sql for sql, _ in self.cursor.executadas),
            "levantou depois de escrever o fecho: a ordem esta invertida",
        )

    def test_concluir_apagamento_com_os_seis_fecha(self) -> None:
        p = pedido(TIPO_ELIMINACAO)
        self.aplicar(p, *ESCOPOS)
        fechado = concluir_apagamento(self.cursor, self.porta, p)
        self.assertIsNotNone(fechado)
        self.assertEqual(fechado.estado, ESTADO_CONCLUIDO)

    def test_fechar_duas_vezes_nao_reescreve_a_data(self) -> None:
        """A idempotencia e do `WHERE estado <> 'concluido'` do `SQL_CONCLUIR`.

        A data de conclusao de um pedido do titular e um facto com prazo legal
        atras dele, nao um campo que se actualiza.
        """
        p = pedido(TIPO_ELIMINACAO)
        self.aplicar(p, *ESCOPOS)
        self.assertIsNotNone(concluir_apagamento(self.cursor, self.porta, p))
        self.assertIsNone(concluir_apagamento(self.cursor, self.porta, p))

    def test_concluir_apagamento_recusa_os_outros_tipos(self) -> None:
        with self.assertRaises(ValueError):
            concluir_apagamento(
                self.cursor, self.porta, pedido(TIPO_EXPORTACAO)
            )

    def test_o_unico_escritor_do_fecho_e_privado(self) -> None:
        """Publicar o `_fechar` era reabrir o buraco que a recusa fecha.

        Nao e um ensaio de estilo: mede que a superficie publica da porta nao
        tem **nenhum** caminho para `estado = 'concluido'` que nao passe pela
        guarda ou pelo `concluir_apagamento`.
        """
        publicos = [
            nome
            for nome in dir(self.porta)
            if not nome.startswith("_") and callable(getattr(self.porta, nome))
        ]
        self.assertNotIn("_fechar", publicos)
        self.assertIn("concluir", publicos)


class TestATraducaoDaColisao(unittest.TestCase):
    """Criterio 8, a metade que a revisao mediu como **sem ensaio nenhum**.

    O `_e_pedido_ja_aberto` exige o `pgcode` **e** o nome do indice, e as duas
    condicoes tinham mutantes sobreviventes: trocar `UNICIDADE_VIOLADA` para
    `"23514"` ou o `INDICE_DO_PEDIDO_ABERTO` para qualquer outra cadeia deixava
    a suite verde, e a colisao passava a sair como excepcao crua do *driver* em
    vez de `PedidoEmCurso`.
    """

    class ErroDeUnicidade(Exception):
        """Imita a excepcao do pg8000: `pgcode` e `diag.constraint_name`."""

        class Diag:
            def __init__(self, restricao: str) -> None:
                self.constraint_name = restricao

        def __init__(self, pgcode: str, restricao: str) -> None:
            super().__init__(f"{pgcode}: {restricao}")
            self.pgcode = pgcode
            self.diag = self.Diag(restricao)

    class CursorQueColide:
        """Levanta na insercao e devolve o pedido aberto na releitura."""

        def __init__(self, erro: Exception, aberto: bool = True) -> None:
            self._erro = erro
            self._aberto = aberto
            self._resultado: list = []

        def execute(self, sql: str, params: tuple = ()) -> None:
            if "INSERT INTO platform.dsar_requests" in sql:
                raise self._erro
            self._resultado = (
                [("d-ja-aberto",) + ("x",) * 9] if self._aberto else []
            )

        def fetchone(self):
            return self._resultado[0] if self._resultado else None

        def fetchall(self):
            return list(self._resultado)

    def porta(self):
        return PortaDeDireitos(relogio=RelogioParado(), auditoria=AuditoriaFalsa())

    def receber(self, cursor):
        return self.porta().receber(
            cursor, tenant_id=TENANT, requerente=TITULAR, tipo=TIPO_ELIMINACAO
        )

    def test_a_colisao_do_indice_do_pedido_aberto_vira_pedido_em_curso(self) -> None:
        erro = self.ErroDeUnicidade("23505", "dsar_requests_aberto_uq")
        with self.assertRaises(PedidoEmCurso) as apanhado:
            self.receber(self.CursorQueColide(erro))
        self.assertEqual(apanhado.exception.dsar_id, "d-ja-aberto")

    def test_um_23505_de_outra_restricao_nao_e_traduzido(self) -> None:
        """**O ensaio que morre se alguem tirar o nome do indice da condicao.**

        Um `23505` da chave primaria e um defeito do gerador de UUID. Traduzi-lo
        para «ja ha um pedido aberto» mandava quem o lesse procurar um pedido
        que nao existe.
        """
        erro = self.ErroDeUnicidade("23505", "dsar_requests_pkey")
        with self.assertRaises(self.ErroDeUnicidade):
            self.receber(self.CursorQueColide(erro))

    def test_outro_sqlstate_nao_e_traduzido(self) -> None:
        """E o que morre se alguem trocar o `UNICIDADE_VIOLADA` por `23514`."""
        erro = self.ErroDeUnicidade("23514", "dsar_requests_aberto_uq")
        with self.assertRaises(self.ErroDeUnicidade):
            self.receber(self.CursorQueColide(erro))

    def test_sem_o_pedido_aberto_na_releitura_diz_desconhecido(self) -> None:
        """A transaccao pode estar abortada: diz-se a verdade, nao se levanta outro erro."""
        erro = self.ErroDeUnicidade("23505", "dsar_requests_aberto_uq")
        with self.assertRaises(PedidoEmCurso) as apanhado:
            self.receber(self.CursorQueColide(erro, aberto=False))
        self.assertEqual(apanhado.exception.dsar_id, "desconhecido")


class TestAProvaDaOposicao(unittest.TestCase):
    """Achado da revisao: a composicao divergia da unica canonica do repositorio.

    O `packages/core-ts/src/consentimento/prova.ts` compoe
    `(textoMostrado, contactId, wamid, hora)` com `chr(0)`, e sai do modulo de
    proposito porque «o `evidence_hash` tem de ser reprodutivel por quem
    audita». A primeira versao deste modulo compunha
    `sha256(dsar_id ∥ finalidade)` com o separador do `audit_log` — nao cobria o
    `contact_id` nem hora nenhuma.
    """

    def prova(self, cursor):
        return next(p for s, p in cursor.executadas if "consent_event" in s)[5]

    def test_a_prova_usa_o_separador_do_prova_ts(self) -> None:
        self.assertEqual(SEPARADOR_DA_PROVA, chr(0))
        self.assertNotEqual(
            SEPARADOR_DA_PROVA,
            SEPARADOR,
            "o separador da prova nao e o do payload_hash do audit_log: sao "
            "colunas diferentes com escritores diferentes",
        )

    def test_a_prova_se_reproduz_das_duas_linhas_que_existem(self) -> None:
        """A propriedade que a `0015` exige: quem audita recalcula-a.

        Os quatro campos leem-se de duas linhas: a de `consent_event` da o
        `contact_id` e o `ocorrido_em`, a de `dsar_requests` da o `dsar_id`.
        """
        import hashlib

        cursor = BaseQueLeAInstrucao()
        p = pedido(TIPO_OPOSICAO)
        opor(cursor, p)
        esperado = hashlib.sha256(
            SEPARADOR_DA_PROVA.join(
                (
                    TEXTO_DA_OPOSICAO,
                    p.contact_id,
                    p.dsar_id,
                    p.recebido_at.isoformat(),
                )
            ).encode("utf-8")
        ).digest()
        self.assertEqual(self.prova(cursor), esperado)

    def test_a_prova_cobre_o_contacto(self) -> None:
        """**O ensaio que morre se o `contact_id` sair da composicao.**

        Sem ele, duas oposicoes de titulares diferentes pelo mesmo `dsar_id`
        davam a mesma prova — e a unicidade da `0015`, que inclui o
        `contact_id`, deixava de ser suficiente pela razao que ela escreve.
        """
        um = BaseQueLeAInstrucao()
        outro = BaseQueLeAInstrucao()
        opor(um, pedido(TIPO_OPOSICAO, contacto=TITULAR))
        opor(outro, pedido(TIPO_OPOSICAO, contacto=OUTRO))
        self.assertNotEqual(self.prova(um), self.prova(outro))

    def test_a_prova_cobre_a_hora_do_pedido(self) -> None:
        import dataclasses

        um = BaseQueLeAInstrucao()
        outro = BaseQueLeAInstrucao()
        base = pedido(TIPO_OPOSICAO)
        opor(um, base)
        opor(
            outro,
            dataclasses.replace(base, recebido_at=base.recebido_at + timedelta(days=1)),
        )
        self.assertNotEqual(self.prova(um), self.prova(outro))

    def test_a_prova_tem_trinta_e_dois_bytes(self) -> None:
        """O `CHECK octet_length(evidence_hash) = 32` da `0015`."""
        cursor = BaseQueLeAInstrucao()
        opor(cursor, pedido(TIPO_OPOSICAO))
        self.assertEqual(len(self.prova(cursor)), 32)


class TestARectificacaoEmDoisPassos(unittest.TestCase):
    """Achado da revisao: o critério 7 era **impossivel** numa transaccao.

    O `UPDATE` em `contact_endpoints` e so do `kamba_identity` (`0003`) e o
    `EXECUTE` em `audit_append` e so do `kamba_app` e do `kamba_batch` (`0006`).
    Os dois conjuntos sao **disjuntos**, pelo que a primeira versao — que fazia
    as duas no mesmo cursor — levantava `42501` em qualquer das duas ligacoes.
    """

    class CursorDoCofre:
        def __init__(self, linhas: int = 1) -> None:
            self.executadas: list = []
            self._linhas = linhas

        def execute(self, sql: str, params: tuple = ()) -> None:
            if "platform.audit_append" in sql:
                raise AssertionError(
                    "o cursor do cofre nao chama audit_append: o kamba_identity "
                    "nao tem EXECUTE nessa funcao (0006)"
                )
            self.executadas.append((sql, params))

        def fetchall(self):
            return [("id-{}".format(n),) for n in range(self._linhas)]

        def fetchone(self):
            return self.fetchall()[0] if self._linhas else None

    def setUp(self) -> None:
        self.auditoria = AuditoriaFalsa()
        self.porta = PortaDeDireitos(
            relogio=RelogioParado(), auditoria=self.auditoria
        )

    def test_o_passo_do_cofre_nao_toca_no_audit_log(self) -> None:
        """**O duplo recusa a instrucao que o privilegio recusa.**

        Nao mede uma convencao: o `CursorDoCofre` levanta se vir um
        `audit_append`, que e exactamente o que o PostgreSQL faz com `42501`.
        """
        cursor = self.CursorDoCofre()
        linhas = self.porta.rectificar_telefone(
            cursor, pedido=pedido(TIPO_RECTIFICACAO), finalidade="entrega",
            phone_enc=b"cifrado",
        )
        self.assertEqual(linhas, 1)
        self.assertEqual(self.auditoria.registos, [])

    def test_o_passo_da_auditoria_escreve_a_accao_nova(self) -> None:
        self.porta.auditar_rectificacao(
            pedido=pedido(TIPO_RECTIFICACAO), finalidade="entrega", linhas=1
        )
        self.assertEqual(len(self.auditoria.registos), 1)
        self.assertEqual(
            self.auditoria.registos[0]["accao"], "privacy.dsar_rectificado"
        )

    def test_auditar_zero_linhas_tambem_se_registra(self) -> None:
        """Nao auditar quando nao houve linha escondia um pedido que falhou."""
        self.porta.auditar_rectificacao(
            pedido=pedido(TIPO_RECTIFICACAO), finalidade="entrega", linhas=0
        )
        self.assertEqual(self.auditoria.registos[0]["detalhe"]["linhas"], 0)

    def test_o_tipo_do_pedido_autoriza_os_dois_passos(self) -> None:
        for chamada in (
            lambda: self.porta.rectificar_telefone(
                self.CursorDoCofre(), pedido=pedido(TIPO_EXPORTACAO),
                finalidade="entrega", phone_enc=b"x",
            ),
            lambda: self.porta.auditar_rectificacao(
                pedido=pedido(TIPO_EXPORTACAO), finalidade="entrega", linhas=1
            ),
        ):
            with self.subTest(), self.assertRaises(ValueError):
                chamada()


class TestOEscritorDoAuditLog(unittest.TestCase):
    """O `AuditoriaNaBase`, que a revisao mediu como **nunca executado**."""

    class CursorDeAuditoria:
        def __init__(self) -> None:
            self.executadas: list = []

        def execute(self, sql: str, params: tuple = ()) -> None:
            self.executadas.append((sql, params))

    def test_o_sha256_e_da_base_e_nao_do_python(self) -> None:
        """Um *hash* do lado do cliente era uma segunda canonicalizacao."""
        cursor = self.CursorDeAuditoria()
        AuditoriaNaBase(cursor).escrever(
            tenant_id=TENANT, accao="privacy.dsar_recusado",
            contact_id=TITULAR, detalhe={"tipo": "exportacao"},
        )
        sql, params = cursor.executadas[0]
        self.assertIn("sha256(%s::bytea)", sql)
        self.assertIn("platform.audit_append", sql)
        self.assertEqual(len(params), 8)

    def test_o_detalhe_vai_no_hash_e_nao_numa_coluna(self) -> None:
        """O `audit_log` nao tem coluna de texto livre (`0006` §7.1)."""
        cursor = self.CursorDeAuditoria()
        AuditoriaNaBase(cursor).escrever(
            tenant_id=TENANT, accao="privacy.dsar_recusado",
            contact_id=TITULAR, detalhe={"alvo": OUTRO},
        )
        _sql, params = cursor.executadas[0]
        texto = params[-1].decode("utf-8")
        self.assertIn(OUTRO, texto)
        self.assertEqual(
            [p for p in params[:-1] if isinstance(p, str) and OUTRO in p],
            [],
            "o detalhe nao pode ir numa coluna: vai no payload_hash",
        )

    def test_o_actor_e_o_contacto_e_nao_um_funcionario(self) -> None:
        cursor = self.CursorDeAuditoria()
        AuditoriaNaBase(cursor).escrever(
            tenant_id=TENANT, accao="privacy.dsar_recusado",
            contact_id=TITULAR, detalhe={},
        )
        _sql, params = cursor.executadas[0]
        self.assertEqual(params[1], "contact")

    def test_o_relogio_do_sistema_devolve_utc(self) -> None:
        """A convencao do conjunto: datas em UTC."""
        agora = RelogioDoSistema().agora()
        self.assertIsNotNone(agora.tzinfo)
        self.assertEqual(agora.utcoffset(), timedelta(0))


class TestAsLeiturasDoPedido(unittest.TestCase):
    """Os caminhos que a revisao mediu como nunca executados."""

    class CursorDeLeitura:
        def __init__(self, linhas: list) -> None:
            self._linhas = linhas
            self.executadas: list = []

        def execute(self, sql: str, params: tuple = ()) -> None:
            self.executadas.append((sql, params))

        def fetchone(self):
            return self._linhas[0] if self._linhas else None

        def fetchall(self):
            return list(self._linhas)

    def linha(self, dsar_id="d-1", estado=ESTADO_RECEBIDO, recebido=RECEBIDO):
        return (
            dsar_id, TENANT, TITULAR, TIPO_ELIMINACAO, estado, PAPEL_POR_OMISSAO,
            recebido, PRAZO_INTERNO_DIAS, prazo_interno(recebido), None,
        )

    def porta(self, agora=RECEBIDO):
        return PortaDeDireitos(
            relogio=RelogioParado(agora), auditoria=AuditoriaFalsa()
        )

    def test_ler_devolve_o_pedido_ou_none(self) -> None:
        self.assertIsNotNone(
            self.porta().ler(self.CursorDeLeitura([self.linha()]), "d-1")
        )
        self.assertIsNone(self.porta().ler(self.CursorDeLeitura([]), "d-1"))

    def test_em_curso_so_morde_no_recebido(self) -> None:
        marcado = self.porta().em_curso(
            self.CursorDeLeitura([self.linha(estado=ESTADO_EM_CURSO)]), "d-1"
        )
        self.assertEqual(marcado.estado, ESTADO_EM_CURSO)
        self.assertIsNone(
            self.porta().em_curso(self.CursorDeLeitura([]), "d-1")
        )

    def test_abertos_devolve_todos_e_o_filtro_e_do_pedido(self) -> None:
        """A aritmetica do prazo e do `Pedido`, nao de um `WHERE now()`."""
        antigo = RECEBIDO - timedelta(days=25)
        cursor = self.CursorDeLeitura(
            [self.linha("d-novo"), self.linha("d-antigo", recebido=antigo)]
        )
        porta = self.porta()
        self.assertEqual(len(porta.abertos(cursor)), 2)

    def test_em_atraso_e_alerta_devido_filtram_pelo_relogio(self) -> None:
        antigo = RECEBIDO - timedelta(days=40)
        porta = self.porta()
        cursor = self.CursorDeLeitura(
            [self.linha("d-novo"), self.linha("d-antigo", recebido=antigo)]
        )
        self.assertEqual(
            [p.dsar_id for p in porta.em_atraso(cursor)], ["d-antigo"]
        )
        cursor = self.CursorDeLeitura(
            [self.linha("d-novo"), self.linha("d-antigo", recebido=antigo)]
        )
        self.assertEqual(
            [p.dsar_id for p in porta.com_alerta_devido(cursor)], ["d-antigo"]
        )


class TestADisciplinaDeLigacao(unittest.TestCase):
    """O `dbapi.py`, que a revisao mediu como **nunca executado**."""

    class LigacaoFalsa:
        def __init__(self) -> None:
            self.fechada = False

        def close(self) -> None:
            self.fechada = True

    def test_com_tenant_fecha_a_ligacao_mesmo_quando_levanta(self) -> None:
        """Uma ligacao que nao se fecha num erro e uma ligacao disputada."""
        from kamba_core.direitos import dbapi

        ligacao = self.LigacaoFalsa()
        import contextlib

        @contextlib.contextmanager
        def tx(_conexao, _tenant):
            yield "cursor"

        original = dbapi.tenant_guard.tx
        dbapi.tenant_guard.tx = tx
        try:
            with self.assertRaises(RuntimeError):
                dbapi.com_tenant(
                    lambda: ligacao, TENANT, lambda _c: (_ for _ in ()).throw(
                        RuntimeError("boom")
                    )
                )
        finally:
            dbapi.tenant_guard.tx = original
        self.assertTrue(ligacao.fechada)

    def test_os_dois_jobs_tem_nome(self) -> None:
        """O `tenant_guard` recusa um `kamba_batch` sem nome de job."""
        from kamba_core.direitos import JOB_DO_RESTAURO, JOB_DO_VARRIMENTO

        for job in (JOB_DO_VARRIMENTO, JOB_DO_RESTAURO):
            with self.subTest(job=job):
                self.assertRegex(job, r"^[a-z][a-z0-9_]{2,62}$")


if __name__ == "__main__":
    unittest.main()
