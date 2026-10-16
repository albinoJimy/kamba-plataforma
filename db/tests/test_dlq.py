"""Gate 8: a ferramenta de operacao da DLQ (KAM-006), contra um PostgreSQL real.

O criterio 6 do KAM-006 — «reprocessar uma entrada e idempotente; **descartar**
uma entrada `payment.*` exige 2 aprovadores distintos (a CLI recusa o 1.º)» —
nao se prova com uma base falsa. A regra dos dois aprovadores **e** a chave
primaria `(dlq_id, aprovador)` de `platform.evt_dlq_aprovacoes`, e a
idempotencia do fecho **e** o `events_dlq_resolucao_ck` mais a linha trancada:
uma base de mentira que aceitasse tudo deixava os dois criterios verdes com a
ferramenta errada.

Duas areas, e a divisao e deliberada:

    _ComEntradas          as regras, como administrador da instancia e numa
                          transaccao que nunca se confirma. O administrador
                          contorna a RLS (`events_dlq` tem `FORCE`) e os
                          privilegios, pelo que o que falha aqui falha **pela
                          ferramenta** e nao por um `GRANT` em falta.
    TestComOPapelBatch    a mesma ferramenta pela linha de comandos, ligada
                          como `kamba_batch` com a sua palavra-passe, com os
                          codigos de saida. Semeia **confirmado**, porque e a
                          unica forma de outra transaccao (a da CLI) ver a
                          linha — e e tambem a unica forma de provar o que mais
                          importa: que a recusa da primeira aprovacao **nao a
                          reverte**, e que a segunda chamada, noutra
                          transaccao, encontra-a la.

As linhas confirmadas apagam-se todas antes de a classe sair, e isso nao e
higiene: o `downgrade` da revisao 0005 **recusa-se a correr** com linhas na DLQ,
e `test_migracao`, que corre depois deste ficheiro por ordem alfabetica, faz
`downgrade base`.
"""

from __future__ import annotations

import contextlib
import io
import json
import os
import unittest.mock
import uuid

import dlq
import ligacao
from tests.base import ComBase

#: Prefixo de todos os `consumer` que esta suite escreve. Serve para duas
#: coisas: apagar o que se semeou confirmado, e tornar a listagem hermetica (ver
#: `_ComEntradas.setUp`).
PREFIXO = "dlq-teste-"

#: O erro tipico de uma entrada do criterio 2 do KAM-006 (`fora_de_ordem`).
ERRO_TIPICO = "fora_de_ordem: pre-condicao nunca verificada em 6 tentativas"

SQL_INSERIR = (
    "INSERT INTO platform.events_dlq "
    "  (consumer, event_id, tipo, versao, tenant_id, envelope, erro, tentativas, "
    "   criado_at) "
    "VALUES (%s, %s, %s, %s::smallint, %s, %s::jsonb, %s, %s, "
    "        now() - make_interval(hours => %s)) "
    "RETURNING id"
)


def _consumer() -> str:
    return f"{PREFIXO}{uuid.uuid4().hex[:8]}"


def _inserir(
    cursor,
    tenant: str,
    tipo: str = "order.created",
    *,
    tentativas: int = 6,
    erro: str = ERRO_TIPICO,
    idade_horas: int = 0,
    consumer: str | None = None,
) -> int:
    """Uma entrada **aberta** da DLQ. Devolve o `id` que a identidade gerou.

    O envelope e obviamente sintetico e sem P2: a DLQ guarda P0/P1 apenas
    (`docs/tecnica/06` §6.4), e nada aqui e um telefone nem um nome de pessoa.
    """
    event_id = str(uuid.uuid4())
    envelope = {
        "event_id": event_id,
        "tipo": tipo,
        "versao": 1,
        "tenant_id": tenant,
        "agregado": {"tipo": "order", "id": f"agg-{uuid.uuid4().hex[:8]}", "seq": 7},
    }
    cursor.execute(
        SQL_INSERIR,
        (
            consumer or _consumer(),
            event_id,
            tipo,
            1,
            tenant,
            json.dumps(envelope),
            erro,
            tentativas,
            idade_horas,
        ),
    )
    return int(cursor.fetchone()[0])


class _ComEntradas(ComBase):
    """Entradas da DLQ numa transaccao que nunca se confirma."""

    def setUp(self) -> None:
        super().setUp()
        self.conexao = self.ligar("admin")
        self.cursor = self.conexao.cursor()
        self.tenant = str(uuid.uuid4())
        # Dentro desta transaccao, e so dentro dela: assim `dlq.listar` ve
        # exactamente o que este teste semear, mesmo que `TestComOPapelBatch`
        # (que semeia confirmado, por ter de correr a CLI noutra transaccao)
        # tenha deixado alguma linha para tras. O `rollback` do `tearDown`
        # devolve-as.
        self.cursor.execute(
            "DELETE FROM platform.events_dlq WHERE starts_with(consumer, %s)",
            (PREFIXO,),
        )

    def entrada(self, tipo: str = "order.created", **campos) -> int:
        return _inserir(self.cursor, self.tenant, tipo, **campos)

    def estado(self, dlq_id: int) -> tuple:
        """`(estado, resolvido_at is not null, resolvido_por)` da entrada."""
        self.cursor.execute(
            "SELECT estado, resolvido_at IS NOT NULL, resolvido_por "
            "  FROM platform.events_dlq WHERE id = %s",
            (dlq_id,),
        )
        return tuple(self.cursor.fetchone())

    def aprovadores(self, dlq_id: int) -> list[str]:
        return dlq.aprovacoes(self.cursor, dlq_id)


class TestListar(_ComEntradas):
    """O comando `listar`: o que mostra, por que ordem, e o que nao mostra."""

    def test_sem_entradas_abertas_a_listagem_e_vazia(self) -> None:
        self.assertEqual(dlq.listar(self.cursor), [])

    def test_a_listagem_vazia_diz_que_a_dlq_esta_limpa(self) -> None:
        texto = "\n".join(dlq.formatar_listagem([]))
        self.assertIn("nao tem entradas abertas", texto)

    def test_a_listagem_traz_as_colunas_que_o_operador_precisa(self) -> None:
        consumer = _consumer()
        dlq_id = self.entrada(
            "order.created", consumer=consumer, tentativas=6, erro=ERRO_TIPICO
        )
        (entrada,) = dlq.listar(self.cursor)
        self.assertEqual(
            (
                entrada.id,
                entrada.consumer,
                entrada.tipo,
                entrada.tenant_id,
                entrada.tentativas,
                entrada.erro,
            ),
            (dlq_id, consumer, "order.created", self.tenant, 6, ERRO_TIPICO),
        )

    def test_a_idade_vem_de_criado_at(self) -> None:
        self.entrada("order.created", idade_horas=3)
        (entrada,) = dlq.listar(self.cursor)
        # Tres horas inteiras, e menos de quatro: `now()` e o inicio desta
        # transaccao, pelo que a margem nao depende de a suite ser lenta.
        self.assertGreaterEqual(entrada.idade_segundos, 3 * 3600)
        self.assertLess(entrada.idade_segundos, 4 * 3600)
        self.assertEqual(dlq.formatar_idade(entrada.idade_segundos), "3h00m")

    def test_payment_e_order_paid_sao_sev1_e_order_created_nao(self) -> None:
        self.entrada("payment.confirmed")
        self.entrada("order.paid")
        self.entrada("order.created")
        por_tipo = {entrada.tipo: entrada.sev1 for entrada in dlq.listar(self.cursor)}
        self.assertEqual(
            por_tipo,
            {"payment.confirmed": True, "order.paid": True, "order.created": False},
        )

    def test_as_sev1_vem_primeiro_ainda_que_sejam_as_mais_novas(self) -> None:
        self.entrada("order.created", idade_horas=48)
        self.entrada("payment.confirmed", idade_horas=0)
        self.assertEqual(
            [entrada.tipo for entrada in dlq.listar(self.cursor)],
            ["payment.confirmed", "order.created"],
        )

    def test_a_listagem_marca_as_sev1_e_conta_as_abertas(self) -> None:
        self.entrada("payment.confirmed")
        self.entrada("order.created")
        texto = "\n".join(dlq.formatar_listagem(dlq.listar(self.cursor)))
        self.assertIn("SEV1", texto)
        self.assertIn("2 entrada(s) aberta(s), 1 Sev1", texto)

    def test_o_erro_cabe_numa_linha_na_apresentacao(self) -> None:
        self.entrada("order.created", erro="primeira linha\nsegunda linha")
        (entrada,) = dlq.listar(self.cursor)
        # O valor inteiro fica na `Entrada`; so a apresentacao e que colapsa.
        self.assertEqual(entrada.erro, "primeira linha\nsegunda linha")
        linhas = dlq.formatar_listagem([entrada])
        self.assertEqual(len(linhas), 3, linhas)
        self.assertIn("primeira linha segunda linha", linhas[1])

    def test_uma_entrada_fechada_deixa_de_aparecer(self) -> None:
        dlq_id = self.entrada("order.created")
        self.assertEqual([entrada.id for entrada in dlq.listar(self.cursor)], [dlq_id])
        dlq.reprocessar(self.cursor, dlq_id, "ana")
        self.assertEqual(dlq.listar(self.cursor), [])


class TestReprocessar(_ComEntradas):
    """O comando `reprocessar`: fecha a entrada uma vez, e recusa a segunda."""

    def test_reprocessar_fecha_a_entrada_com_quem_a_resolveu(self) -> None:
        dlq_id = self.entrada("order.created")
        mensagem = dlq.reprocessar(self.cursor, dlq_id, "ana")
        self.assertEqual(self.estado(dlq_id), ("reprocessada", True, "ana"))
        self.assertIn(str(dlq_id), mensagem)

    def test_a_mensagem_diz_que_nao_re_enfileira_o_evento(self) -> None:
        dlq_id = self.entrada("order.created")
        mensagem = dlq.reprocessar(self.cursor, dlq_id, "ana")
        self.assertIn("reconciliador", mensagem)

    def test_reprocessar_duas_vezes_recusa_a_segunda(self) -> None:
        dlq_id = self.entrada("order.created")
        dlq.reprocessar(self.cursor, dlq_id, "ana")
        with self.assertRaises(dlq.Recusa) as capturado:
            dlq.reprocessar(self.cursor, dlq_id, "bruno")
        # A recusa nomeia o estado e quem resolveu: um sucesso silencioso aqui
        # era o segundo operador a achar que tinha feito o que o primeiro fez.
        self.assertIn("reprocessada", str(capturado.exception))
        self.assertIn("ana", str(capturado.exception))
        # E nao mexeu na linha: continua a dizer que foi a Ana.
        self.assertEqual(self.estado(dlq_id), ("reprocessada", True, "ana"))

    def test_reprocessar_uma_entrada_descartada_recusa(self) -> None:
        dlq_id = self.entrada("order.created")
        dlq.descartar(self.cursor, dlq_id, "ana")
        with self.assertRaises(dlq.Recusa):
            dlq.reprocessar(self.cursor, dlq_id, "bruno")
        self.assertEqual(self.estado(dlq_id), ("descartada", True, "ana"))

    def test_reprocessar_uma_entrada_inexistente_recusa(self) -> None:
        self.cursor.execute(
            "SELECT coalesce(max(id), 0) + 1000 FROM platform.events_dlq"
        )
        inexistente = int(self.cursor.fetchone()[0])
        with self.assertRaises(dlq.Recusa) as capturado:
            dlq.reprocessar(self.cursor, inexistente, "ana")
        self.assertIn(str(inexistente), str(capturado.exception))

    def test_reprocessar_sem_nome_de_operador_e_erro_de_uso(self) -> None:
        dlq_id = self.entrada("order.created")
        # `resolvido_por` em branco era uma resolucao sem autor; recusa-se em
        # Python para dar uma mensagem de uso em vez de uma linha anonima.
        with self.assertRaises(dlq.ErroDeUso):
            dlq.reprocessar(self.cursor, dlq_id, "   ")
        self.assertEqual(self.estado(dlq_id), ("aberta", False, None))


class TestDescartar(_ComEntradas):
    """O comando `descartar`: um aprovador basta, excepto em `payment.*`."""

    def test_payment_com_um_aprovador_recusa_e_registra_a_aprovacao(self) -> None:
        dlq_id = self.entrada("payment.confirmed")
        with self.assertRaises(dlq.Recusa) as capturado:
            dlq.descartar(self.cursor, dlq_id, "ana")
        mensagem = str(capturado.exception)
        # A recusa tem de dizer o que falta **e** quem ja aprovou.
        self.assertIn("ana", mensagem)
        self.assertIn("segundo aprovador", mensagem)
        # A entrada continua aberta, e a aprovacao ficou registada: e ela que
        # torna a segunda chamada possivel.
        self.assertEqual(self.estado(dlq_id), ("aberta", False, None))
        self.assertEqual(self.aprovadores(dlq_id), ["ana"])

    def test_payment_com_dois_aprovadores_distintos_descarta(self) -> None:
        dlq_id = self.entrada("payment.confirmed")
        with self.assertRaises(dlq.Recusa):
            dlq.descartar(self.cursor, dlq_id, "ana")
        mensagem = dlq.descartar(self.cursor, dlq_id, "bruno")
        estado, resolvida, resolvido_por = self.estado(dlq_id)
        self.assertEqual((estado, resolvida), ("descartada", True))
        # `resolvido_por` leva os dois nomes: quem le a linha da DLQ ve as duas
        # pessoas sem uma segunda consulta.
        self.assertEqual(resolvido_por, "ana, bruno")
        self.assertEqual(self.aprovadores(dlq_id), ["ana", "bruno"])
        self.assertIn("descartada", mensagem)

    def test_o_mesmo_aprovador_duas_vezes_nao_descarta(self) -> None:
        dlq_id = self.entrada("payment.confirmed")
        with self.assertRaises(dlq.Recusa):
            dlq.descartar(self.cursor, dlq_id, "ana")
        with self.assertRaises(dlq.Recusa) as capturado:
            dlq.descartar(self.cursor, dlq_id, "ana")
        mensagem = str(capturado.exception)
        # Mensagem clara, e **nao** uma violacao de chave primaria na cara de
        # quem opera: a chave `(dlq_id, aprovador)` continua a ser o que torna
        # a repeticao impossivel, mas quem a provoca le portugues.
        self.assertIn("ja tinha aprovado", mensagem)
        self.assertIn("nao conta duas vezes", mensagem)
        self.assertEqual(self.estado(dlq_id), ("aberta", False, None))
        self.assertEqual(self.aprovadores(dlq_id), ["ana"])

    def test_o_mesmo_aprovador_com_espacos_tambem_nao_conta_duas_vezes(self) -> None:
        dlq_id = self.entrada("payment.confirmed")
        with self.assertRaises(dlq.Recusa):
            dlq.descartar(self.cursor, dlq_id, "ana")
        with self.assertRaises(dlq.Recusa):
            dlq.descartar(self.cursor, dlq_id, "  ana  ")
        self.assertEqual(self.aprovadores(dlq_id), ["ana"])
        self.assertEqual(self.estado(dlq_id), ("aberta", False, None))

    def test_um_tipo_que_nao_e_payment_basta_um_aprovador(self) -> None:
        dlq_id = self.entrada("order.created")
        dlq.descartar(self.cursor, dlq_id, "ana")
        self.assertEqual(self.estado(dlq_id), ("descartada", True, "ana"))

    def test_order_paid_e_sev1_mas_basta_um_aprovador(self) -> None:
        # As duas perguntas nao sao a mesma: `order.paid` e Sev1 no alerta
        # (§6.4) e **nao** e `payment.*`, e o criterio 6 pede os dois
        # aprovadores so para `payment.*`.
        dlq_id = self.entrada("order.paid")
        self.assertTrue(dlq.e_sev1("order.paid"))
        self.assertEqual(dlq.aprovadores_necessarios("order.paid"), 1)
        dlq.descartar(self.cursor, dlq_id, "ana")
        self.assertEqual(self.estado(dlq_id), ("descartada", True, "ana"))

    def test_qualquer_payment_exige_dois_aprovadores(self) -> None:
        for tipo in ("payment.confirmed", "payment.failed", "payment.refunded"):
            with self.subTest(tipo=tipo):
                self.assertEqual(dlq.aprovadores_necessarios(tipo), 2)
                dlq_id = self.entrada(tipo)
                with self.assertRaises(dlq.Recusa):
                    dlq.descartar(self.cursor, dlq_id, "ana")
                self.assertEqual(self.estado(dlq_id)[0], "aberta")

    def test_descartar_uma_entrada_ja_reprocessada_recusa(self) -> None:
        dlq_id = self.entrada("payment.confirmed")
        dlq.reprocessar(self.cursor, dlq_id, "ana")
        with self.assertRaises(dlq.Recusa) as capturado:
            dlq.descartar(self.cursor, dlq_id, "bruno")
        self.assertIn("reprocessada", str(capturado.exception))
        # E nao registou aprovacao nenhuma numa entrada fechada.
        self.assertEqual(self.aprovadores(dlq_id), [])

    def test_descartar_duas_vezes_recusa_a_segunda(self) -> None:
        dlq_id = self.entrada("order.created")
        dlq.descartar(self.cursor, dlq_id, "ana")
        with self.assertRaises(dlq.Recusa):
            dlq.descartar(self.cursor, dlq_id, "bruno")
        self.assertEqual(self.estado(dlq_id), ("descartada", True, "ana"))

    def test_descartar_uma_entrada_inexistente_recusa(self) -> None:
        self.cursor.execute(
            "SELECT coalesce(max(id), 0) + 1000 FROM platform.events_dlq"
        )
        inexistente = int(self.cursor.fetchone()[0])
        with self.assertRaises(dlq.Recusa) as capturado:
            dlq.descartar(self.cursor, inexistente, "ana")
        self.assertIn(str(inexistente), str(capturado.exception))

    def test_aprovador_vazio_e_erro_de_uso_e_nao_uma_violacao_de_check(self) -> None:
        dlq_id = self.entrada("payment.confirmed")
        # `evt_dlq_aprovacoes_aprovador_ck` recusa a cadeia vazia; a ferramenta
        # recusa-a antes, para a mensagem ser de uso e nao um SQLSTATE 23514.
        with self.assertRaises(dlq.ErroDeUso):
            dlq.descartar(self.cursor, dlq_id, "   ")
        self.assertEqual(self.aprovadores(dlq_id), [])
        self.assertEqual(self.estado(dlq_id), ("aberta", False, None))


class TestComOPapelBatch(ComBase):
    """A CLI, ligada como `kamba_batch`, e os codigos de saida.

    Semeia **confirmado**: a CLI abre a sua propria ligacao, e uma linha nao
    confirmada seria invisivel para ela. E e isso que torna esta classe a unica
    que prova a propriedade mais subtil da ferramenta — a recusa do primeiro
    aprovador **confirma** a aprovacao, e a segunda chamada, noutra
    transaccao, encontra-a.
    """

    @classmethod
    def setUpClass(cls) -> None:
        super().setUpClass()
        cls._semeador = ligacao.ligar("admin")
        cls._semeador.autocommit = True

    @classmethod
    def tearDownClass(cls) -> None:
        cls._semeador.close()
        super().tearDownClass()

    def setUp(self) -> None:
        super().setUp()
        self.tenant = str(uuid.uuid4())
        self.addCleanup(self._apagar)

    def _apagar(self) -> None:
        """Apaga pelo prefixo do `consumer`, e apaga sempre.

        O `downgrade` da 0005 recusa-se a correr com linhas na DLQ, e
        `test_migracao` faz `downgrade base` depois deste ficheiro: uma linha
        esquecida aqui faz falhar seis testes noutro ficheiro.

        **As aprovacoes primeiro.** A chave estrangeira **nao** tem
        `ON DELETE CASCADE` (o gate 8 recusa cascatas, e com razao: uma cascata
        esconde perda de dados), pelo que apagar a entrada antes da aprovacao
        viola a restricao. E a mesma ordem que a funcao de retencao
        `evt_limpar_dlq` usa.
        """
        cursor = self._semeador.cursor()
        cursor.execute(
            "DELETE FROM platform.evt_dlq_aprovacoes a USING platform.events_dlq d "
            "WHERE a.dlq_id = d.id AND starts_with(d.consumer, %s)",
            (PREFIXO,),
        )
        cursor.execute(
            "DELETE FROM platform.events_dlq WHERE starts_with(consumer, %s)",
            (PREFIXO,),
        )

    def semear(self, tipo: str = "order.created") -> int:
        return _inserir(self._semeador.cursor(), self.tenant, tipo)

    def correr(self, *argv: str) -> tuple[int, str, str]:
        """`dlq.main` com a saida capturada. Devolve `(codigo, stdout, stderr)`."""
        saida, erros = io.StringIO(), io.StringIO()
        with contextlib.redirect_stdout(saida), contextlib.redirect_stderr(erros):
            codigo = dlq.main(list(argv))
        return codigo, saida.getvalue(), erros.getvalue()

    def linha(self, dlq_id: int) -> tuple:
        cursor = self._semeador.cursor()
        cursor.execute(
            "SELECT estado, resolvido_por FROM platform.events_dlq WHERE id = %s",
            (dlq_id,),
        )
        return tuple(cursor.fetchone())

    # ------------------------------------------------------------------ listar

    def test_listar_sai_com_zero_e_mostra_a_entrada(self) -> None:
        dlq_id = self.semear("payment.confirmed")
        codigo, saida, _ = self.correr("listar")
        self.assertEqual(codigo, dlq.SAIDA_OK)
        self.assertIn(str(dlq_id), saida)
        self.assertIn("SEV1", saida)

    # ------------------------------------------------------------- reprocessar

    def test_reprocessar_sai_com_zero_e_a_segunda_vez_com_um(self) -> None:
        dlq_id = self.semear("order.created")
        codigo, saida, _ = self.correr("reprocessar", str(dlq_id), "--operador", "ana")
        self.assertEqual(codigo, dlq.SAIDA_OK)
        self.assertIn("reprocessada", saida)
        # Confirmou: outra transaccao ve o fecho.
        self.assertEqual(self.linha(dlq_id), ("reprocessada", "ana"))

        codigo, _, erros = self.correr(
            "reprocessar", str(dlq_id), "--operador", "bruno"
        )
        self.assertEqual(codigo, dlq.SAIDA_RECUSA)
        self.assertIn("ja esta reprocessada", erros)
        self.assertEqual(self.linha(dlq_id), ("reprocessada", "ana"))

    # --------------------------------------------------------------- descartar

    def test_descartar_payment_recusa_o_primeiro_aprovador_e_guarda_a_aprovacao(
        self,
    ) -> None:
        dlq_id = self.semear("payment.confirmed")

        codigo, _, erros = self.correr("descartar", str(dlq_id), "--aprovador", "ana")
        self.assertEqual(codigo, dlq.SAIDA_RECUSA)
        self.assertIn("segundo aprovador", erros)
        self.assertEqual(self.linha(dlq_id), ("aberta", None))

        # O que esta classe existe para provar: a recusa **confirmou** a
        # aprovacao, e esta segunda chamada e outra transaccao, noutra ligacao.
        codigo, saida, _ = self.correr(
            "descartar", str(dlq_id), "--aprovador", "bruno"
        )
        self.assertEqual(codigo, dlq.SAIDA_OK)
        self.assertIn("descartada", saida)
        self.assertEqual(self.linha(dlq_id), ("descartada", "ana, bruno"))

    def test_o_mesmo_aprovador_duas_vezes_sai_com_um_das_duas(self) -> None:
        dlq_id = self.semear("payment.confirmed")
        self.assertEqual(
            self.correr("descartar", str(dlq_id), "--aprovador", "ana")[0],
            dlq.SAIDA_RECUSA,
        )
        codigo, _, erros = self.correr("descartar", str(dlq_id), "--aprovador", "ana")
        self.assertEqual(codigo, dlq.SAIDA_RECUSA)
        self.assertIn("ja tinha aprovado", erros)
        self.assertEqual(self.linha(dlq_id), ("aberta", None))

    def test_descartar_um_tipo_que_nao_e_payment_sai_com_zero_a_primeira(self) -> None:
        dlq_id = self.semear("order.paid")
        codigo, saida, _ = self.correr("descartar", str(dlq_id), "--aprovador", "ana")
        self.assertEqual(codigo, dlq.SAIDA_OK)
        self.assertEqual(self.linha(dlq_id), ("descartada", "ana"))

    # ------------------------------------------------------- recusa e erro de uso

    def test_uma_entrada_inexistente_sai_com_um(self) -> None:
        cursor = self._semeador.cursor()
        cursor.execute("SELECT coalesce(max(id), 0) + 1000 FROM platform.events_dlq")
        inexistente = int(cursor.fetchone()[0])
        for comando in (
            ("reprocessar", str(inexistente), "--operador", "ana"),
            ("descartar", str(inexistente), "--aprovador", "ana"),
        ):
            with self.subTest(comando=comando[0]):
                codigo, _, erros = self.correr(*comando)
                self.assertEqual(codigo, dlq.SAIDA_RECUSA)
                self.assertIn("nao existe entrada", erros)

    def test_aprovador_vazio_sai_com_dois(self) -> None:
        dlq_id = self.semear("payment.confirmed")
        codigo, _, erros = self.correr("descartar", str(dlq_id), "--aprovador", "  ")
        self.assertEqual(codigo, dlq.SAIDA_ERRO)
        self.assertIn("nao pode ser vazio", erros)
        self.assertEqual(self.linha(dlq_id), ("aberta", None))

    def test_operador_dado_e_vazio_sai_com_dois(self) -> None:
        dlq_id = self.semear("order.created")
        # Um `--operador` dado e vazio **nao** cai para `KAMBA_OPERADOR` nem
        # para o utilizador da sessao: quem o escreveu queria nomear alguem e
        # nao nomeou, e registar outro nome era falsear a auditoria.
        codigo, _, erros = self.correr("reprocessar", str(dlq_id), "--operador", " ")
        self.assertEqual(codigo, dlq.SAIDA_ERRO)
        self.assertIn("nao pode ser vazio", erros)
        self.assertEqual(self.linha(dlq_id), ("aberta", None))

    def test_sem_operador_o_nome_vem_do_ambiente(self) -> None:
        dlq_id = self.semear("order.created")
        with unittest.mock.patch.dict(
            os.environ, {dlq.VARIAVEL_DO_OPERADOR: "job-de-teste"}
        ):
            codigo, _, _ = self.correr("reprocessar", str(dlq_id))
        self.assertEqual(codigo, dlq.SAIDA_OK)
        self.assertEqual(self.linha(dlq_id), ("reprocessada", "job-de-teste"))

    def test_um_subcomando_desconhecido_sai_com_dois(self) -> None:
        with self.assertRaises(SystemExit) as capturado:
            self.correr("reprocessar-tudo")
        self.assertEqual(capturado.exception.code, dlq.SAIDA_ERRO)

    def test_sem_subcomando_sai_com_dois(self) -> None:
        with self.assertRaises(SystemExit) as capturado:
            self.correr()
        self.assertEqual(capturado.exception.code, dlq.SAIDA_ERRO)

    def test_um_id_que_nao_e_numero_sai_com_dois(self) -> None:
        with self.assertRaises(SystemExit) as capturado:
            self.correr("reprocessar", "nao-e-um-id")
        self.assertEqual(capturado.exception.code, dlq.SAIDA_ERRO)
