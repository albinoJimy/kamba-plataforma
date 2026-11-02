"""A cadeia de *hashes*: criterio 6 do bloco KAM-053.

O criterio pede tres coisas, e sao tres:

    formula    `row_hash = sha256(prev_hash || campos canonicos)`
    deteccao   alterar **um byte** com superutilizador faz o
               `verify_ledger_chain` apontar o elo
    ancora     a cabeca da cadeia exportada diariamente via `StorageProvider`

A terceira mede-se onde o `StorageProvider` vive — em
`packages/core-ts/tests/pagamentos.ledger.test.ts`, com um armazenamento falso —,
porque e codigo de aplicacao e nao de base de dados. O que **aqui** se mede e a
vista que ele le: a `v_payment_ledger_heads`.

**O superutilizador e a unica via de adulteracao que existe.** O
`deny_mutation` recusa `UPDATE` a todos (ver o `test_porta.py`), pelo que o ensaio
de deteccao tem de o contornar com `session_replication_role = replica` — a unica
coisa que salta um *trigger*, e a razao de os dois *triggers* desta revisao serem
`ENABLE ALWAYS`. Que o `ALWAYS` esteja la mede-se tambem, porque sem ele esta
via era aberta a qualquer dono de sessao.
"""

from __future__ import annotations

from tests_pagamentos.base import ComLedger


class TestFormulaDoElo(ComLedger):
    """A formula, chamada directamente. Sem cobranca nenhuma."""

    GENESE = bytes(32)

    def test_o_elo_e_determinista_e_de_32_octetos(self) -> None:
        argumentos = (
            self.GENESE,
            "00000000-0000-0000-0000-000000000001",
            "fakeprovider",
            "00000000-0000-0000-0000-000000000002",
            "REF1",
            "pagamento_recebido",
            1,
            "ev-1",
            1_250_000,
            "AOA",
            "hmac",
            True,
            "informativo",
            bytes(32),
        )
        marcas = ", ".join(["%s"] * len(argumentos))
        self.semente.execute(
            f"SELECT platform.payment_event_row_hash({marcas}), "
            f"       platform.payment_event_row_hash({marcas})",
            argumentos + argumentos,
        )
        primeiro, segundo = tuple(self.semente.fetchone())
        self.assertEqual(primeiro, segundo, "IMMUTABLE: a mesma entrada, o mesmo elo")
        self.assertEqual(len(primeiro), 32)

    def test_cada_campo_canonico_muda_o_elo(self) -> None:
        """Um campo que nao entra no elo e um campo que se pode adulterar.

        E o ensaio que a `0006` ensinou a escrever: a mutacao «o `payload_hash`
        sai do `row_hash`» existe porque alguem o podia tirar e tudo continuava
        verde. Aqui varre-se **cada** posicao.
        """
        base = [
            self.GENESE,
            "00000000-0000-0000-0000-000000000001",
            "fakeprovider",
            "00000000-0000-0000-0000-000000000002",
            "REF1",
            "pagamento_recebido",
            1,
            "ev-1",
            1_250_000,
            "AOA",
            "hmac",
            True,
            "informativo",
            bytes(32),
        ]
        alteracoes = [
            bytes([1] + [0] * 31),
            "00000000-0000-0000-0000-00000000000f",
            "outroprovider",
            "00000000-0000-0000-0000-00000000000e",
            "REF2",
            "pagamento_confirmado",
            2,
            "ev-2",
            1_250_001,
            "AOA",  # a moeda e fechada em AOA: nao ha segundo valor para testar
            "consulta",
            False,
            "aceite",
            bytes([1] + [0] * 31),
        ]
        marcas = ", ".join(["%s"] * len(base))
        self.semente.execute(
            f"SELECT platform.payment_event_row_hash({marcas})", tuple(base)
        )
        original = self.semente.fetchone()[0]

        for posicao, novo in enumerate(alteracoes):
            if novo == base[posicao]:
                continue
            with self.subTest(posicao=posicao):
                mudado = list(base)
                mudado[posicao] = novo
                self.semente.execute(
                    f"SELECT platform.payment_event_row_hash({marcas})",
                    tuple(mudado),
                )
                self.assertNotEqual(
                    self.semente.fetchone()[0],
                    original,
                    f"o campo na posicao {posicao} nao entra no elo",
                )

    def test_um_argumento_nulo_da_nulo(self) -> None:
        """`STRICT`, e e o que torna o `coalesce` do `provider_event_id` uma
        decisao e nao um descuido: sem ele, um evento gerado pela plataforma
        tinha `row_hash` nulo e o `NOT NULL` recusava-o.
        """
        argumentos = [
            None,
            "00000000-0000-0000-0000-000000000001",
            "fakeprovider",
            "00000000-0000-0000-0000-000000000002",
            "REF1",
            "pagamento_recebido",
            1,
            "ev-1",
            1_250_000,
            "AOA",
            "hmac",
            True,
            "informativo",
            bytes(32),
        ]
        marcas = ", ".join(["%s"] * len(argumentos))
        self.semente.execute(
            f"SELECT platform.payment_event_row_hash({marcas})", tuple(argumentos)
        )
        self.assertIsNone(self.semente.fetchone()[0])


class TestCadeiaEscritaPelaPorta(ComLedger):
    """A cadeia que a porta constroi, e a sua verificacao."""

    def setUp(self) -> None:
        super().setUp()
        self.tenant = self.criar_tenant()
        self.conta = self.criar_conta(self.tenant)
        self.cobranca = self.criar_cobranca(self.tenant, self.conta)
        cursor = self.cursor_papel("app", self.tenant)
        for tipo, decisao in (
            ("pagamento_recebido", "informativo"),
            ("pagamento_confirmado", "aceite"),
        ):
            self.appendar(
                cursor, self.cobranca, self.conta, tipo, p_decisao=decisao
            )
        self.confirmar(cursor, self.tenant)

    def test_o_primeiro_elo_parte_da_genese_e_os_seguintes_encadeiam(self) -> None:
        self.semente.execute(
            "SELECT prev_hash, row_hash FROM platform.payment_events "
            " WHERE charge_id = %s ORDER BY id",
            (self.cobranca,),
        )
        elos = [tuple(linha) for linha in self.semente.fetchall()]
        self.assertEqual(len(elos), 2)
        self.assertEqual(elos[0][0], bytes(32), "o primeiro parte da genese")
        self.assertEqual(
            elos[1][0], elos[0][1], "o segundo parte do row_hash do primeiro"
        )

    def test_a_verificacao_de_uma_cadeia_intacta_devolve_zero_linhas(self) -> None:
        self.semente.execute(
            "SELECT count(*) FROM platform.verify_ledger_chain(%s)", (self.cobranca,)
        )
        self.assertEqual(int(self.semente.fetchone()[0]), 0)

    def test_um_byte_alterado_com_superutilizador_e_apanhado(self) -> None:
        """Criterio 6: a deteccao, pela unica via de adulteracao que existe.

        O `session_replication_role = replica` e o que salta os *triggers* de
        omissao; os desta revisao sao `ENABLE ALWAYS` e nao se saltam, pelo que
        esta via tem de passar pelo **dono** da tabela com os *triggers*
        desligados a mao. E e por isso que ela e exactamente a ameaca que a
        cadeia existe para apanhar: quem chega aqui tem a base toda, e a cadeia
        nao o impede — **mostra-o**.
        """
        self.semente.execute(
            "SELECT id, valor_minor FROM platform.payment_events "
            " WHERE charge_id = %s ORDER BY id LIMIT 1",
            (self.cobranca,),
        )
        alvo, valor = tuple(self.semente.fetchone())

        self.semente.execute(
            "ALTER TABLE platform.payment_events DISABLE TRIGGER payment_events_imutavel"
        )
        try:
            self.semente.execute(
                "UPDATE platform.payment_events SET valor_minor = %s WHERE id = %s",
                (valor + 1, alvo),
            )
            partidos = [
                tuple(linha)
                for linha in self._verificar()
            ]
        finally:
            self.semente.execute(
                "ALTER TABLE platform.payment_events "
                "ENABLE ALWAYS TRIGGER payment_events_imutavel"
            )

        self.assertEqual(
            [(str(c), e) for c, e, _, _ in partidos],
            [(self.cobranca, alvo)],
            "o elo adulterado, e so ele, tem de aparecer",
        )
        self.assertEqual(
            partidos[0][3], "row_hash nao corresponde aos campos canonicos"
        )

    def test_uma_linha_removida_no_meio_e_apanhada_pelo_encadeamento(self) -> None:
        """A segunda metade da verificacao, e a que a formula sozinha nao ve.

        Se a cadeia se verificasse so recalculando cada `row_hash`, apagar uma
        linha do meio deixava as restantes todas consistentes — cada uma
        continuava a corresponder aos seus campos. E o `prev_hash` do elo
        seguinte que denuncia o buraco.
        """
        terceiro = self._terceiro_evento()
        self.semente.execute(
            "SELECT id FROM platform.payment_events WHERE charge_id = %s "
            " ORDER BY id OFFSET 1 LIMIT 1",
            (self.cobranca,),
        )
        meio = self.semente.fetchone()[0]

        self.semente.execute(
            "ALTER TABLE platform.payment_events DISABLE TRIGGER payment_events_imutavel"
        )
        try:
            self.semente.execute(
                "DELETE FROM platform.payment_events WHERE id = %s", (meio,)
            )
            partidos = [tuple(linha) for linha in self._verificar()]
        finally:
            self.semente.execute(
                "ALTER TABLE platform.payment_events "
                "ENABLE ALWAYS TRIGGER payment_events_imutavel"
            )
        self.assertEqual(
            [(e, f) for _, e, _, f in partidos],
            [(terceiro, "prev_hash nao e o row_hash do elo anterior")],
        )

    def test_a_cabeca_da_cadeia_e_o_ultimo_elo(self) -> None:
        """A vista que o *job* diario exporta para STO (ancora externa, §8)."""
        self.semente.execute(
            "SELECT row_hash FROM platform.payment_events WHERE charge_id = %s "
            " ORDER BY id DESC LIMIT 1",
            (self.cobranca,),
        )
        ultimo = self.semente.fetchone()[0]
        self.semente.execute(
            "SELECT charge_id, sequencia, row_hash "
            "  FROM platform.v_payment_ledger_heads WHERE charge_id = %s",
            (self.cobranca,),
        )
        linhas = [tuple(linha) for linha in self.semente.fetchall()]
        self.assertEqual(len(linhas), 1, "uma linha por cobranca, nao uma por evento")
        self.assertEqual(linhas[0][2], ultimo)

    # ------------------------------------------------------------- auxiliares

    def _verificar(self):
        self.semente.execute(
            "SELECT charge_id, event_id, sequencia, falha "
            "  FROM platform.verify_ledger_chain(%s)",
            (self.cobranca,),
        )
        return self.semente.fetchall()

    def _terceiro_evento(self) -> int:
        """Um terceiro elo, para haver um «meio» a remover."""
        cursor = self.cursor_papel("app", self.tenant)
        self.appendar(
            cursor, self.cobranca, self.conta, "pagamento_duplicado",
            p_decisao="informativo",
        )
        self.confirmar(cursor, self.tenant)
        self.semente.execute(
            "SELECT id FROM platform.payment_events WHERE charge_id = %s "
            " ORDER BY id DESC LIMIT 1",
            (self.cobranca,),
        )
        return self.semente.fetchone()[0]


class TestTriggersSaoAlways(ComLedger):
    """O `ENABLE ALWAYS`, lido do catalogo.

    Sem ele, um `SET session_replication_role = replica` — que qualquer dono de
    sessao com privilegio pode fazer — saltava os dois *triggers*, e a
    imutabilidade do ledger passava a depender de ninguem o escrever. E a licao
    que a `0006` pagou, e aqui ha duas tabelas a herda-la.
    """

    def test_os_dois_triggers_do_ledger_sao_always(self) -> None:
        self.semente.execute(
            "SELECT t.tgname, t.tgenabled FROM pg_trigger t "
            "  JOIN pg_class c ON c.oid = t.tgrelid "
            "  JOIN pg_namespace n ON n.oid = c.relnamespace "
            " WHERE n.nspname = 'platform' AND c.relname = 'payment_events' "
            "   AND NOT t.tgisinternal ORDER BY t.tgname"
        )
        self.assertEqual(
            [tuple(linha) for linha in self.semente.fetchall()],
            [("payment_events_imutavel", "A"), ("payment_events_sem_truncate", "A")],
            "'A' e ENABLE ALWAYS; 'O' seria a omissao, que o replica salta",
        )
