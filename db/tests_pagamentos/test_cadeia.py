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

    #: Os vinte e dois argumentos da formula, por omissao, pela ordem da
    #: assinatura. Escritos uma vez: os tres ensaios desta classe partem deles.
    ARGUMENTOS = (
        bytes(32),  # 0  prev_hash
        "00000000-0000-0000-0000-000000000001",  # 1  tenant_id
        "00000000-0000-0000-0000-000000000002",  # 2  charge_id
        "00000000-0000-0000-0000-000000000003",  # 3  order_id
        None,  # 4  billing_cycle_id (exclusivo do order_id)
        "fakeprovider",  # 5  provider
        "00000000-0000-0000-0000-000000000004",  # 6  account_id
        "REF1",  # 7  referencia
        "pagamento_recebido",  # 8  tipo_evento
        1,  # 9  sequencia
        "ev-1",  # 10 provider_event_id
        1_250_000,  # 11 valor_minor
        "AOA",  # 12 currency
        "hmac",  # 13 authn_method
        True,  # 14 authn_ok
        "informativo",  # 15 decisao
        "um motivo",  # 16 motivo
        "provider",  # 17 actor_kind
        "00000000-0000-0000-0000-000000000005",  # 18 actor_id
        bytes(32),  # 19 payload_hash
        "2026-11-02T10:00:00.000000+00",  # 20 ocorrido_at
        "2026-11-02T11:00:00.000000+00",  # 21 recebido_at
    )

    def test_o_elo_e_determinista_e_de_32_octetos(self) -> None:
        argumentos = self.ARGUMENTOS
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
        base = list(self.ARGUMENTOS)
        alteracoes = [
            bytes([1] + [0] * 31),
            "00000000-0000-0000-0000-0000000000aa",  # tenant_id
            "00000000-0000-0000-0000-0000000000ab",  # charge_id
            "00000000-0000-0000-0000-0000000000ac",  # order_id
            "00000000-0000-0000-0000-0000000000ad",  # billing_cycle_id
            "outroprovider",
            "00000000-0000-0000-0000-0000000000ae",  # account_id
            "REF2",
            "pagamento_confirmado",
            2,
            "ev-2",
            1_250_001,
            "AOA",  # a moeda e fechada em AOA: nao ha segundo valor para testar
            "consulta",
            False,
            "aceite",
            "outro motivo",
            "ops",
            "00000000-0000-0000-0000-0000000000af",  # actor_id
            bytes([1] + [0] * 31),
            "2026-11-03T10:00:00.000000+00",
            "2026-11-03T11:00:00.000000+00",
        ]
        self.assertEqual(
            len(alteracoes), len(base), "uma alteracao por argumento, sem excepcao"
        )
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

    def test_os_argumentos_anulaveis_por_desenho_nao_dao_nulo(self) -> None:
        """**A funcao deixou de ser `STRICT`, e isto e o que mudou.**

        O elo passou a cobrir vinte e duas colunas, e metade das que entraram
        sao anulaveis **por desenho**: o `order_id` e o `billing_cycle_id` sao
        exclusivos (exactamente um e nulo, sempre), o `motivo` so existe numa
        divergencia, o `actor_id` so numa confirmacao humana, e o `ocorrido_at`
        so quando o facilitador o da. Com `STRICT`, o elo de **todo** o evento
        era nulo — e e por isso que o `STRICT` saiu e os `coalesce` do corpo
        passaram a ser a defesa.

        Este ensaio e o que o fixa: cada um desses argumentos a nulo, um a um, e
        o elo continua a ser um `sha256`.
        """
        anulaveis = {
            3: "order_id",
            4: "billing_cycle_id",
            10: "provider_event_id",
            16: "motivo",
            18: "actor_id",
            20: "ocorrido_at",
        }
        marcas = ", ".join(["%s"] * len(self.ARGUMENTOS))
        for posicao, nome in anulaveis.items():
            with self.subTest(argumento=nome):
                argumentos = list(self.ARGUMENTOS)
                argumentos[posicao] = None
                self.semente.execute(
                    f"SELECT platform.payment_event_row_hash({marcas})",
                    tuple(argumentos),
                )
                elo = self.semente.fetchone()[0]
                self.assertIsNotNone(elo, f"o {nome} nulo nao pode anular o elo")
                self.assertEqual(len(elo), 32)

    def test_um_prev_hash_nulo_da_nulo(self) -> None:
        """O `prev_hash` **continua** a dar nulo, e isso e deliberado.

        Nao e um argumento anulavel por desenho: toda a linha do ledger tem
        `prev_hash` (a genese sao trinta e dois zeros, nao `NULL`). Um nulo aqui
        e um chamador a passar o que nao existe, e o elo tem de ser nulo para o
        `NOT NULL` da coluna o recusar.
        """
        argumentos = list(self.ARGUMENTOS)
        argumentos[0] = None  # o `prev_hash`
        marcas = ", ".join(["%s"] * len(argumentos))
        self.semente.execute(
            f"SELECT platform.payment_event_row_hash({marcas})", tuple(argumentos)
        )
        self.assertIsNone(
            self.semente.fetchone()[0],
            "um `prev_hash` nulo nao e uma cadeia com um buraco: e nenhuma "
            "cadeia, e o elo tem de ser nulo",
        )


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
        # Tres: o `referencia_emitida` da semente (a cobranca nasce `iniciada` e
        # chega a `emitida` pela porta) e os dois deste ensaio.
        self.assertEqual(len(elos), 3)
        self.assertEqual(elos[0][0], bytes(32), "o primeiro parte da genese")
        for anterior, seguinte in zip(elos, elos[1:]):
            self.assertEqual(
                seguinte[0],
                anterior[1],
                "cada elo parte do row_hash do anterior",
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

        estado_do_trigger = self._desligar_trigger()
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
            self._repor_trigger(estado_do_trigger)

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
        # O **penultimo**: remover um elo do meio e o que a formula sozinha nao
        # veria, e o `terceiro` acima garante que ha um depois dele.
        self.semente.execute(
            "SELECT id FROM platform.payment_events WHERE charge_id = %s "
            " ORDER BY id DESC OFFSET 1 LIMIT 1",
            (self.cobranca,),
        )
        meio = self.semente.fetchone()[0]

        estado_do_trigger = self._desligar_trigger()
        try:
            self.semente.execute(
                "DELETE FROM platform.payment_events WHERE id = %s", (meio,)
            )
            partidos = [tuple(linha) for linha in self._verificar()]
        finally:
            self._repor_trigger(estado_do_trigger)
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

    def _desligar_trigger(self) -> str:
        """Desliga o `payment_events_imutavel` e **devolve o que ele era**.

        Devolver o estado anterior nao e zelo: e o que impede este ensaio de
        contaminar o `TestTriggersSaoAlways`. Ver o `_repor_trigger`.
        """
        self.semente.execute(
            "SELECT t.tgenabled FROM pg_trigger t "
            "  JOIN pg_class c ON c.oid = t.tgrelid "
            "  JOIN pg_namespace n ON n.oid = c.relnamespace "
            " WHERE n.nspname = 'platform' AND c.relname = 'payment_events' "
            "   AND t.tgname = 'payment_events_imutavel'"
        )
        anterior = str(self.semente.fetchone()[0])
        self.semente.execute(
            "ALTER TABLE platform.payment_events "
            "DISABLE TRIGGER payment_events_imutavel"
        )
        return anterior

    def _repor_trigger(self, anterior: str) -> None:
        """Repoe **o que estava**, e nao o que devia estar.

        ## Porque e que isto nao e `ENABLE ALWAYS` fixo

        Era, e foi um defeito — apanhado por uma mutacao que **sobreviveu**: a
        que tira o `ENABLE ALWAYS` da revisao `0029`. Com o restauro fixo em
        `ENABLE ALWAYS`, estes ensaios **punham** o *trigger* em `A` a seguir a
        cada caso, e o `TestTriggersSaoAlways` — que corre depois, no mesmo
        ficheiro — lia um `A` que tinha sido escrito por **eles** e nao pela
        migracao. Isto e, a asercao passava com a revisao a criar o *trigger*
        sem `ALWAYS`: um ensaio a passar pela razao errada, e sobre a barreira
        que o `session_replication_role = replica` existe para contornar.

        Medido: a mutacao «os triggers do ledger deixam de ser ALWAYS»
        sobreviveu a suite inteira, e o diagnostico imprimiu
        `[('payment_events_imutavel', 'A'), …]` numa base onde a migracao nunca
        correu o `ALTER`.

        Com o restauro a repor o valor anterior, estes ensaios deixam de
        escrever o estado que outro ensaio afirma. E a mesma disciplina do passo
        de canario do `test_concorrencia.py`, que repoe a restricao que largou.
        """
        if anterior == "A":
            instrucao = "ENABLE ALWAYS TRIGGER"
        elif anterior == "R":
            instrucao = "ENABLE REPLICA TRIGGER"
        elif anterior == "D":
            instrucao = "DISABLE TRIGGER"
        else:
            instrucao = "ENABLE TRIGGER"
        self.semente.execute(
            f"ALTER TABLE platform.payment_events {instrucao} payment_events_imutavel"
        )

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

    ## O que este ensaio mede, e o que **nao** mede

    Mede o estado **vivo** do catalogo, no fim da suite. Nao mede que a
    **migracao** o escreveu, e a diferenca nao e academica: enquanto o restauro
    do `TestCadeiaEscritaPelaPorta` punha o *trigger* em `ENABLE ALWAYS` a
    seguir a cada caso, este ensaio passava mesmo com a revisao a criar o
    *trigger* sem `ALWAYS` — lia o que o vizinho tinha escrito. Esta corrigido
    (ver o `_repor_trigger`), e a prova de que a **migracao** o escreve esta
    onde nenhum vizinho lhe chega: no
    `TestDowngradeDa0029.test_depois_de_voltar_a_subir_tudo_volta`, que reaplica
    a revisao ele proprio.

    Os dois ficam, porque medem coisas diferentes — este apanha quem desligue
    um *trigger* e se esqueca de o repor, e o outro apanha quem lhe tire o
    `ALWAYS` na revisao.
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
