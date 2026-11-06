"""A maquina de estados e a reconstrucao: criterio 5 do bloco KAM-053.

Duas afirmacoes diferentes, e nenhuma substitui a outra:

    cobertura     o `next_state` tem **exactamente** as arestas do
                  `docs/tecnica/04` §7.1, e recusa as restantes
    propriedade   para mil sequencias validas aleatorias, o
                  `rebuild_charge_state` da o mesmo que a projeccao em
                  `payment_charges.estado`

A primeira le-se do documento e compara-se com a base. A segunda e a unica que
apanha uma divergencia **entre** a projeccao do passo (6) da
`append_payment_event` e a dobra do `rebuild_charge_state` — as duas usam o
`next_state`, mas por caminhos diferentes, e um erro de ordem num deles nao
aparece na tabela de arestas.
"""

from __future__ import annotations

import random
import uuid

from tests.base import VIOLACAO_DE_CHECK
from tests_pagamentos.base import ComLedger

#: Os dez estados do §6.2.
ESTADOS = (
    "iniciada",
    "emitida",
    "aguarda_cliente",
    "pendente_confirmacao",
    "paga",
    "expirada",
    "falhada",
    "cancelada",
    "reembolso_pendente",
    "reembolsada",
)

#: Os dezassete tipos de evento do §6.2.
TIPOS = (
    "cobranca_criada",
    "referencia_emitida",
    "push_enviado",
    "pagamento_recebido",
    "pagamento_confirmado",
    "pagamento_divergente",
    "pagamento_orfao",
    "pagamento_duplicado",
    "pagamento_rejeitado_provider",
    "cobranca_expirada",
    "cobranca_cancelada",
    "confirmacao_manual_pedida",
    "confirmacao_manual_registada",
    "confirmacao_manual_rejeitada",
    "confirmacao_manual_revertida",
    "reembolso_manual_registado",
    "ajuste_reconciliacao",
)

#: Os seis tipos que registam um facto e **nao** movem o estado. Lida do §5.1
#: («o `pagamento_recebido` escreve-se antes da decisao»), do §7.2 (F-01 e F-08:
#: «200, sem efeito») e do §8 (o ajuste e compensatorio).
SEM_TRANSICAO = (
    "cobranca_criada",
    "pagamento_recebido",
    "pagamento_orfao",
    "pagamento_duplicado",
    "confirmacao_manual_registada",
    "ajuste_reconciliacao",
)

#: As arestas do diagrama do §7.1, lidas do documento uma a uma:
#: `(estado, tipo_evento, decisao) -> estado`.
#:
#: **Tres** arestas do diagrama nao estao aqui, e nenhuma por esquecimento. A
#: primeira muda de forma com o KAM-054 e **nao desaparece** — ver a nota ao
#: lado do `("paga", "confirmacao_manual_revertida")` na tabela:
#:
#:     paga -> reembolso_pendente: «disputa»
#:         o KAM-054 deu a esta cobranca um caminho de `paga` para
#:         `reembolso_pendente`, mas pelo `confirmacao_manual_revertida`, que e a
#:         **reversao** do M-8 — engano ou fraude descoberta. A aresta que o
#:         diagrama desenha e uma **disputa do cliente**, e para essa continua a
#:         nao haver tipo de evento nos dezassete do §6.2. A condicao que a
#:         `0029` escreveu — «sem evento, nao ha aresta» — continua verdadeira
#:         para a disputa, e apagar esta nota deixava-a sem sitio onde estar
#:         escrita (apanhado pela revisao adversarial do KAM-054)
#:     pendente_confirmacao -> paga: «confirmacao humana auditada»
#:         esta aqui, mas por `pagamento_confirmado` — «confirmacao humana
#:         auditada» e um `authn_method` (`manual`, com `actor_id`) e nao um tipo
#:         de evento. Ver o `_next_state` da revisao: um segundo caminho para
#:         `paga` nao passaria pelo `confirmar_exige_autenticacao`
#:
#: E duas que o §7.1 nao desenha e que o G4 pode exigir — a divergencia a partir
#: de `aguarda_cliente` e de `pendente_confirmacao` — ficam **recusadas**, porque
#: o criterio manda seguir o §7.1 a letra. Estao em `docs/dividas-documentais.md`.
ARESTAS = {
    ("iniciada", "referencia_emitida"): "emitida",
    ("iniciada", "push_enviado"): "aguarda_cliente",
    ("iniciada", "pagamento_rejeitado_provider"): "falhada",
    ("emitida", "confirmacao_manual_pedida"): "pendente_confirmacao",
    ("emitida", "pagamento_confirmado"): "paga",
    ("emitida", "pagamento_divergente"): "falhada",
    ("emitida", "cobranca_expirada"): "expirada",
    ("emitida", "cobranca_cancelada"): "cancelada",
    ("aguarda_cliente", "pagamento_confirmado"): "paga",
    ("aguarda_cliente", "cobranca_expirada"): "expirada",
    ("aguarda_cliente", "pagamento_rejeitado_provider"): "falhada",
    ("pendente_confirmacao", "pagamento_confirmado"): "paga",
    ("pendente_confirmacao", "confirmacao_manual_rejeitada"): "emitida",
    ("expirada", "pagamento_confirmado"): "paga",
    ("falhada", "pagamento_confirmado"): "paga",
    # A quinta aresta, pela revisao `0032` (KAM-054). A `0029` deixou-a de fora
    # e nomeou a condicao: «sem evento, nao ha aresta — e inventar um tipo era
    # alargar o escopo.» Com a `refund_cases` a existir, o evento que faltava
    # **ja estava** nos dezassete: e o `confirmacao_manual_revertida` do M-8. A
    # condicao cumpriu-se sem se inventar tipo nenhum.
    #
    # **E nao e a aresta da «disputa» do diagrama**, que e outra coisa: esta e a
    # reversao do M-8, por engano ou por fraude descoberta, e a do diagrama e
    # uma disputa do cliente — para a qual continua a nao haver tipo de evento.
    # A distincao esta na nota do `ARESTAS`, e saiu da revisao adversarial do
    # KAM-054, que notou que a primeira versao desta linha a apagou.
    ("paga", "confirmacao_manual_revertida"): "reembolso_pendente",
    ("reembolso_pendente", "reembolso_manual_registado"): "reembolsada",
}

#: A **unica** aresta em que a `decisao` decide, e a razao de o `next_state`
#: receber tres argumentos e nao dois.
#:
#: Nas restantes, o §7.1 nao escreve `decisao` nenhuma — um `cobranca_expirada`
#: expira a cobranca, e nao ha nada para aceitar ou rejeitar. Keyear a tabela
#: por `(estado, tipo, decisao)` era inventar quinze guardas que o documento nao
#: tem; a primeira versao deste ficheiro fazia-o e deu dezoito falhas, todas
#: sobre arestas que a funcao percorre bem.
DECISAO_EXIGIDA = {"pagamento_confirmado": "aceite"}



class TestNextState(ComLedger):
    """A funcao pura, chamada directamente. Sem cobranca nenhuma."""

    def next_state(self, estado: str, tipo: str, decisao: str = "informativo"):
        self.semente.execute(
            "SELECT platform.next_state(%s, %s, %s)", (estado, tipo, decisao)
        )
        return self.semente.fetchone()[0]

    def test_as_arestas_do_diagrama_estao_todas(self) -> None:
        for (estado, tipo), esperado in sorted(ARESTAS.items()):
            decisao = DECISAO_EXIGIDA.get(tipo, "informativo")
            with self.subTest(aresta=f"{estado}+{tipo}"):
                self.assertEqual(self.next_state(estado, tipo, decisao), esperado)

    def test_a_decisao_exigida_e_a_unica_que_percorre_a_aresta(self) -> None:
        """A guarda da `decisao`, e so onde o §7.1 a tem.

        Para o `pagamento_confirmado` a `decisao` decide; para as outras
        quinze arestas ela nao e lida, e **isso tambem se afirma** — senao
        ninguem notava o dia em que alguem lhe acrescentasse uma guarda que o
        documento nao pede e um `cobranca_expirada` deixasse de expirar.
        """
        for (estado, tipo), esperado in sorted(ARESTAS.items()):
            exigida = DECISAO_EXIGIDA.get(tipo)
            for decisao in ("aceite", "rejeitada", "informativo"):
                with self.subTest(aresta=f"{estado}+{tipo}", decisao=decisao):
                    obtido = self.next_state(estado, tipo, decisao)
                    if exigida is None or decisao == exigida:
                        self.assertEqual(obtido, esperado)
                    else:
                        self.assertIsNone(
                            obtido,
                            "um pagamento_confirmado sem decisao aceite nao "
                            "pode mover a cobranca: e o CHECK "
                            "confirmar_exige_autenticacao do outro lado",
                        )

    def test_os_factos_sem_transicao_devolvem_o_mesmo_estado(self) -> None:
        """A terceira resposta, e a razao de a funcao nao ter duas.

        Sem ela, um `pagamento_recebido` era «transicao recusada» e o §5.1 ficava
        impossivel de implementar: ele manda escrever esse facto **antes** de
        haver decisao.
        """
        for estado in ESTADOS:
            for tipo in SEM_TRANSICAO:
                with self.subTest(estado=estado, tipo=tipo):
                    self.assertEqual(self.next_state(estado, tipo), estado)

    def test_tudo_o_que_nao_e_aresta_nem_facto_e_recusado(self) -> None:
        """«E rejeita as restantes»: os 170 pares, menos as arestas e os factos.

        E a metade do criterio que uma tabela de arestas sozinha nunca prova. Uma
        maquina que devolvesse o estado de entrada por omissao passava o primeiro
        ensaio deste ficheiro e deixava um `cobranca_cancelada` sobre uma
        cobranca `paga` entrar no ledger sem dizer nada.
        """
        recusados = 0
        for estado in ESTADOS:
            for tipo in TIPOS:
                if tipo in SEM_TRANSICAO:
                    continue
                if (estado, tipo) in ARESTAS:
                    continue
                for decisao in ("aceite", "rejeitada", "informativo"):
                    with self.subTest(estado=estado, tipo=tipo, decisao=decisao):
                        self.assertIsNone(
                            self.next_state(estado, tipo, decisao),
                            "um par que o §7.1 nao desenha tem de dar NULL",
                        )
                    recusados += 1
        self.assertGreater(
            recusados, 100, "o ensaio tem de varrer o produto inteiro"
        )

    def test_para_paga_ha_um_caminho_so(self) -> None:
        """A afirmacao do ticket, medida sobre o produto inteiro.

        Nenhum tipo de evento **alem** do `pagamento_confirmado`, e nenhuma
        `decisao` alem de `aceite`, da `paga` a partir de estado nenhum.
        """
        for estado in ESTADOS:
            for tipo in TIPOS:
                for decisao in ("aceite", "rejeitada", "informativo"):
                    if estado == "paga" and tipo in SEM_TRANSICAO:
                        continue  # fica `paga` porque ja era, e nao por transitar
                    if self.next_state(estado, tipo, decisao) != "paga":
                        continue
                    self.assertEqual(
                        (tipo, decisao),
                        ("pagamento_confirmado", "aceite"),
                        f"ha um segundo caminho para paga: {estado}+{tipo}+{decisao}",
                    )

    def test_um_argumento_nulo_da_nulo_e_nao_uma_transicao(self) -> None:
        """`STRICT`: um estado ou um tipo em falta nao se adivinha."""
        for argumentos in (
            (None, "pagamento_confirmado", "aceite"),
            ("emitida", None, "aceite"),
            ("emitida", "pagamento_confirmado", None),
        ):
            with self.subTest(argumentos=argumentos):
                self.semente.execute(
                    "SELECT platform.next_state(%s, %s, %s)", argumentos
                )
                self.assertIsNone(self.semente.fetchone()[0])


class TestReconstrucao(ComLedger):
    """Criterio 5, segunda metade: a propriedade, com mil sequencias."""

    #: Mil, como o criterio pede. Cada uma e uma cobranca com os seus eventos,
    #: numa transaccao: nao e um ensaio de carga, e a prova de uma propriedade.
    SEQUENCIAS = 1000

    #: Comprimento de cada sequencia. Curto de proposito: o que se mede e a
    #: concordancia entre a dobra e a projeccao, e sequencias longas so repetem
    #: as mesmas arestas.
    PASSOS = 6

    def setUp(self) -> None:
        super().setUp()
        self.tenant = self.criar_tenant()
        self.conta = self.criar_conta(self.tenant)

    def _passo_valido(self, estado: str, aleatorio: random.Random):
        """Um evento que o §7.1 aceita a partir de `estado`, ou `None`.

        Devolve `(tipo, decisao, estado_seguinte)`. Os factos sem transicao
        entram na escolha: eles **sao** eventos validos, e deixa-los de fora
        fazia a propriedade medir so as arestas.
        """
        opcoes = [
            (tipo, DECISAO_EXIGIDA.get(tipo, "informativo"), seguinte)
            for (de, tipo), seguinte in ARESTAS.items()
            if de == estado
        ]
        opcoes += [(tipo, "informativo", estado) for tipo in SEM_TRANSICAO]
        return aleatorio.choice(opcoes) if opcoes else None

    def test_mil_sequencias_validas_reconstroem_o_estado_projectado(self) -> None:
        aleatorio = random.Random(20261102)
        cursor = self.cursor_papel("app", self.tenant)
        comparadas = 0
        estados_vistos: set[str] = set()

        for n in range(self.SEQUENCIAS):
            cobranca = self.criar_cobranca(
                self.tenant, self.conta, estado="iniciada"
            )
            estado = "iniciada"
            for _ in range(self.PASSOS):
                passo = self._passo_valido(estado, aleatorio)
                if passo is None:
                    break  # estado terminal: o §7.1 nao tem saida
                tipo, decisao, seguinte = passo
                self.appendar(
                    cursor, cobranca, self.conta, tipo,
                    p_decisao=decisao,
                    p_provider_event_id=(
                        f"ev-{uuid.uuid4().hex[:12]}"
                        if tipo == "pagamento_recebido"
                        else None
                    ),
                    # **O `pagamento_divergente` passa a trazer motivo**, desde
                    # a revisao `0035` (KAM-055). Ele e um dos sete pares que o
                    # mapa do *outbox* mapeia — para `payment.failed` —, e
                    # aquele contrato exige o campo `motivo`; a
                    # `payment_evt_payload` recusa um nulo em vez de publicar um
                    # envelope que o esquema rejeita. O valor e um dos tres que
                    # o secao 5 da a uma divergencia (`entidade`, `valor`,
                    # `referencia`), e o gerador escrevia `None` — que e um
                    # evento de falha sem razao, e isso o secao 5 nunca produz.
                    #
                    # **E o valor e `valor_divergente` e nao `valor`.** O
                    # `p_motivo` viaja para o `motivo_falha` da cobranca no
                    # passo (6b), e o `payment_charges_motivo_falha_ck` fecha
                    # essa coluna nos **nove** `MOTIVOS_DE_FALHA` da `0029` —
                    # que usam a forma longa. A forma curta do secao 5 da
                    # `23514`, e foi assim que se mediu: o secao 5 e o DDL nao
                    # escrevem o mesmo vocabulario, e quem manda na coluna e o
                    # DDL.
                    p_motivo=(
                        "valor_divergente"
                        if tipo == "pagamento_divergente"
                        else None
                    ),
                )
                estado = seguinte
            self.confirmar(cursor, self.tenant)

            self.semente.execute(
                "SELECT platform.rebuild_charge_state(%s), "
                "       (SELECT estado FROM platform.payment_charges WHERE id = %s)",
                (cobranca, cobranca),
            )
            reconstruido, projectado = tuple(self.semente.fetchone())
            with self.subTest(sequencia=n):
                self.assertEqual(
                    reconstruido,
                    projectado,
                    "a dobra do ledger e a projeccao divergiram",
                )
                self.assertEqual(
                    projectado, estado, "e nenhuma das duas e o que o §7.1 diz"
                )
            estados_vistos.add(projectado)
            comparadas += 1

        self.assertEqual(comparadas, self.SEQUENCIAS)
        # **Sem isto a propriedade podia estar verde sobre nada.** Mil cobrancas
        # que nunca saiam de `iniciada` concordam sempre: a dobra e a projeccao
        # davam as duas o estado inicial, e o ensaio nao media transicao
        # nenhuma.
        self.assertGreaterEqual(
            len(estados_vistos),
            5,
            f"as mil sequencias tem de chegar a varios estados: {estados_vistos}",
        )
        self.assertIn("paga", estados_vistos, "e uma delas tem de chegar a paga")


class TestARecusaDaTransicao(ComLedger):
    """A porta recusa uma transicao fora do §7.1, e **nao escreve** o evento.

    A ordem do passo (6a) e o que isto mede: a projeccao calcula-se **antes** do
    `INSERT`, para que uma transicao recusada nao deixe uma linha no ledger. Um
    ledger nao se corrige — a linha ficava la para sempre.
    """

    def setUp(self) -> None:
        super().setUp()
        self.tenant = self.criar_tenant()
        self.conta = self.criar_conta(self.tenant)
        self.cobranca = self.criar_cobranca(self.tenant, self.conta)

    def test_uma_transicao_recusada_nao_deixa_linha_no_ledger(self) -> None:
        cursor = self.cursor_papel("app", self.tenant)
        # `push_enviado` so parte de `iniciada`, e a cobranca esta em `emitida`.
        sql, args = self.sql_da_porta(
            p_charge_id=self.cobranca,
            p_tipo_evento="push_enviado",
            p_account_id=self.conta,
            p_decisao="informativo",
        )
        self.assertErroSql(VIOLACAO_DE_CHECK, cursor, sql, args)
        self.confirmar(cursor, self.tenant)
        self.assertEqual(self.eventos_do_ensaio(self.cobranca), [])
        self.assertEqual(self.estado_da_cobranca(self.cobranca), "emitida")

    def test_depois_de_paga_uma_segunda_confirmacao_e_recusada(self) -> None:
        """O F-08: o segundo pagamento autenticado nao reconfirma.

        O §7.1 nao desenha `paga -> paga`, e o que o §7.2 manda registar e um
        `pagamento_duplicado` — que **nao** move o estado. As duas metades
        medem-se aqui: a recusa e o caminho que resta.
        """
        cursor = self.cursor_papel("app", self.tenant)
        self.appendar(cursor, self.cobranca, self.conta, "pagamento_confirmado")
        self.confirmar(cursor, self.tenant)
        self.assertEqual(self.estado_da_cobranca(self.cobranca), "paga")

        sql, args = self.sql_da_porta(
            p_charge_id=self.cobranca,
            p_tipo_evento="pagamento_confirmado",
            p_account_id=self.conta,
        )
        self.assertErroSql(VIOLACAO_DE_CHECK, cursor, sql, args)

        linha = self.appendar(
            cursor, self.cobranca, self.conta, "pagamento_duplicado",
            p_decisao="informativo",
        )
        self.confirmar(cursor, self.tenant)
        self.assertEqual(linha[3], "paga", "o duplicado registra-se e nao move")
        self.assertEqual(self.estado_da_cobranca(self.cobranca), "paga")
