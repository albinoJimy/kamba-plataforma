"""A quinta via, as vistas e o elo: o que a revisao adversarial mediu.

Este ficheiro existe porque tres afirmacoes deste ticket estavam **erradas**, e
nenhuma delas erradas por falta de cuidado: erradas por o ensaio que as apoiava
medir outra coisa. Fica separado dos outros para que se leia como o que e — a
lista do que a revisao apanhou — em vez de se diluir nas classes existentes.

    quinta via   o `kamba_app` tem `INSERT` na `payment_charges`, e o `estado`
                 tinha dominio mas nao tinha valor inicial imposto: um `INSERT`
                 com `estado = 'paga'` passava e deixava uma cobranca **paga
                 com zero eventos no ledger**. A caixa do DoD estava marcada, e
                 o `TestNaoHaSegundaPorta` tentava quatro vias — nao esta
    vistas       nenhuma das duas tinha `GRANT`: `42501 permission denied for
                 view`. A ancora externa do §8 falhava na primeira execucao
                 real, e o `kamba_audit` nao conseguia abrir a vista que existe
                 para ele
    elo          **nove** das vinte e tres colunas ficavam fora da cadeia, o
                 `actor_id` e o `tenant_id` entre elas. O ensaio que a caixa
                 nomeava varria as posicoes de argumento da funcao — isto e,
                 por construcao, so os campos que ja estavam dentro

As tres tem aqui o ensaio que nao existia.
"""

from __future__ import annotations

import datetime
import hashlib
import uuid

from tests.base import PRIVILEGIO_INSUFICIENTE, VIOLACAO_DE_CHECK
from tests_pagamentos.base import VALOR, ComLedger

#: Os papeis que podem inserir numa cobranca. O `kamba_batch` entra porque tem
#: `BYPASSRLS`: se a barreira fosse a politica, ele contornava-a.
PAPEIS_QUE_INSEREM = ("app", "batch")

#: Os dez estados do §6.2. O ensaio da quinta via tenta **todos** menos o
#: inicial: a primeira versao da revisao aceitava os dez.
ESTADOS_QUE_NAO_SAO_O_INICIAL = (
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


class TestAQuintaVia(ComLedger):
    """`INSERT` directo com o estado a escolha: a via que faltava tentar."""

    def setUp(self) -> None:
        super().setUp()
        self.tenant = self.criar_tenant()
        self.conta = self.criar_conta(self.tenant)
        # **Uma encomenda que existe**, desde a revisao `0035` (KAM-055): a
        # `payment_charges_encomenda_do_mesmo_tenant_fk` e composta com o
        # `tenant_id`, pelo que o `uuid` aleatorio que estava no `sql()` passou
        # a dar `23503` — e este ficheiro ataca o `estado`, nao a FK.
        self.encomenda = self.criar_encomenda(self.tenant)

    def sql(self, **campos):
        valores = {
            "tenant_id": self.tenant,
            "order_id": self.encomenda,
            "account_id": self.conta,
            "provider": "fakeprovider",
            "metodo": "referencia",
            "referencia": f"REF{uuid.uuid4().hex[:12]}",
            "amount_minor": VALOR,
            "valid_until": datetime.datetime.now(datetime.timezone.utc)
            + datetime.timedelta(hours=24),
        }
        valores.update(campos)
        colunas = ", ".join(valores)
        marcas = ", ".join(["%s"] * len(valores))
        return (
            f"INSERT INTO platform.payment_charges ({colunas}) VALUES ({marcas})",
            tuple(valores.values()),
        )

    def test_nenhum_papel_insere_uma_cobranca_ja_paga(self) -> None:
        """**O defeito, medido.** Antes do *trigger*, isto passava.

        Passava para os dois papeis, com o contexto do proprio tenant, e
        deixava uma cobranca `paga` com **zero** eventos no ledger — e o *job*
        do §8 nao a detectava, porque so compara cobrancas **com** eventos.
        """
        for identidade in PAPEIS_QUE_INSEREM:
            with self.subTest(papel=identidade):
                cursor = self.cursor_papel(identidade, self.tenant)
                sql, args = self.sql(estado="paga")
                self.assertErroSql(VIOLACAO_DE_CHECK, cursor, sql, args)

    def test_nenhum_dos_nove_estados_nao_iniciais_entra(self) -> None:
        """Os nove, e nao so o `paga`.

        O `reembolso_pendente` conta duas vezes: a revisao declara-o
        **inalcancavel** pelo ledger (nenhum evento o atinge), e sem o *trigger*
        um `INSERT` chegava la directamente — isto e, a afirmacao da
        inalcancabilidade era falsa pela mesma via.
        """
        cursor = self.cursor_papel("app", self.tenant)
        for estado in ESTADOS_QUE_NAO_SAO_O_INICIAL:
            with self.subTest(estado=estado):
                sql, args = self.sql(estado=estado)
                self.assertErroSql(VIOLACAO_DE_CHECK, cursor, sql, args)

    def test_o_estado_inicial_entra(self) -> None:
        """A sonda positiva. **Sem ela, os dois casos acima nao dizem nada.**

        Um *trigger* escrito ao contrario recusava **toda** a cobranca, e os
        nove casos acima ficavam verdes sobre uma tabela onde nao se consegue
        criar nada — o que nao e «o ledger esta seguro», e «o pagamento nao
        funciona».
        """
        cursor = self.cursor_papel("app", self.tenant)
        sql, args = self.sql()
        cursor.execute(sql, args)
        self.confirmar(cursor, self.tenant)

    def test_a_omissao_tambem_entra(self) -> None:
        """Sem a coluna `estado`: o `DEFAULT 'iniciada'` e o *trigger* concordam."""
        cursor = self.cursor_papel("app", self.tenant)
        sql, args = self.sql()
        cursor.execute(sql, args)
        cursor.execute(
            "SELECT estado FROM platform.payment_charges WHERE tenant_id = %s",
            (self.tenant,),
        )
        self.assertEqual([e for (e,) in cursor.fetchall()], ["iniciada"])
        self.confirmar(cursor, self.tenant)

    def test_nem_motivo_falha_nem_requer_humano_nascem_preenchidos(self) -> None:
        """As duas colunas sao resultado de uma decisao que ainda nao houve.

        Nascerem preenchidas era a mesma falsificacao por outra coluna: um
        painel de ops a mostrar uma cobranca que exige humano sem nada no ledger
        a justifica-lo.
        """
        cursor = self.cursor_papel("app", self.tenant)
        for extra in ({"motivo_falha": "valor_divergente"}, {"requer_humano": True}):
            with self.subTest(**extra):
                sql, args = self.sql(**extra)
                self.assertErroSql(VIOLACAO_DE_CHECK, cursor, sql, args)

    def test_a_porta_continua_a_mover_o_estado(self) -> None:
        """**A razao de ser um *trigger* e nao um `CHECK`.**

        Um `CHECK (estado = 'iniciada')` e avaliado em toda a versao da linha,
        incluindo a que a projeccao escreve — isto e, impedia a cobranca de sair
        de `iniciada` e o ledger deixava de servir para nada. Este ensaio e o
        que distingue as duas formas: a cobranca nasce `iniciada` **e** chega a
        `paga` pela porta.
        """
        cursor = self.cursor_papel("app", self.tenant)
        cobranca = str(uuid.uuid4())
        sql, args = self.sql(id=cobranca)
        cursor.execute(sql, args)
        self.confirmar(cursor, self.tenant)

        self.appendar(
            cursor, cobranca, self.conta, "referencia_emitida",
            p_decisao="informativo", p_authn_method="sistema",
        )
        linha = self.appendar(
            cursor, cobranca, self.conta, "pagamento_confirmado"
        )
        self.confirmar(cursor, self.tenant)
        self.assertEqual(linha[3], "paga")
        self.assertEqual(self.estado_da_cobranca(cobranca), "paga")

    def test_o_trigger_do_nascimento_e_always(self) -> None:
        """`ALWAYS`, pela razao dos dois do ledger.

        Um `session_replication_role = replica` salta os *triggers* de omissao,
        e com ele a quinta via voltava a abrir.
        """
        self.semente.execute(
            "SELECT t.tgname::text, t.tgenabled::text FROM pg_trigger t "
            "  JOIN pg_class c ON c.oid = t.tgrelid "
            "  JOIN pg_namespace n ON n.oid = c.relnamespace "
            " WHERE n.nspname = 'platform' AND c.relname = 'payment_charges' "
            "   AND NOT t.tgisinternal ORDER BY t.tgname"
        )
        self.assertEqual(
            [(str(a), str(b)) for a, b in self.semente.fetchall()],
            [
                ("payment_charges_beneficiario", "O"),
                ("payment_charges_nasce_iniciada", "A"),
            ],
            "o do nascimento e ALWAYS; o do beneficiario e da 0027 e fica como "
            "ela o ligou",
        )


class TestPrivilegiosDasVistas(ComLedger):
    """As duas vistas, lidas **como papel** — que e a unica forma de o medir.

    Nenhum ensaio o fazia: os de catalogo inspeccionam como administrador, o
    `db/tests/test_privilegios.py` nao tem matriz para vistas, e o ensaio do
    `ledger.ts` usa uma porta falsa. Resultado: as duas vistas ficaram **sem
    `GRANT`**, e a revisao adversarial mediu `42501 permission denied for view`
    — isto e, a ancora externa do §8 falhava na primeira execucao real e o
    `kamba_audit` nao conseguia abrir a vista que existe para ele.
    """

    #: Quem le cada vista, e quem **nao** le. A segunda metade conta tanto como
    #: a primeira: o `kamba_app` nao tem razao para ver a cabeca da cadeia de
    #: cobranca nenhuma.
    ESPERADO = {
        "v_payment_events_audit": {"app": True, "batch": True, "audit": True},
        "v_payment_ledger_heads": {"app": False, "batch": True, "audit": True},
    }

    def setUp(self) -> None:
        super().setUp()
        self.tenant = self.criar_tenant()
        self.conta = self.criar_conta(self.tenant)
        self.cobranca = self.criar_cobranca(self.tenant, self.conta)
        cursor = self.cursor_papel("app", self.tenant)
        self.appendar(
            cursor, self.cobranca, self.conta, "pagamento_recebido",
            p_decisao="informativo",
        )
        self.confirmar(cursor, self.tenant)

    def test_cada_papel_le_ou_nao_le_o_que_a_matriz_diz(self) -> None:
        for vista, por_papel in self.ESPERADO.items():
            for identidade, pode in por_papel.items():
                with self.subTest(vista=vista, papel=identidade):
                    cursor = self.cursor_papel(identidade, self.tenant)
                    if pode:
                        cursor.execute(f"SELECT count(*) FROM platform.{vista}")
                        self.assertGreaterEqual(int(cursor.fetchone()[0]), 0)
                    else:
                        self.assertErroSql(
                            PRIVILEGIO_INSUFICIENTE,
                            cursor,
                            f"SELECT count(*) FROM platform.{vista}",
                        )

    def test_o_security_invoker_deixa_a_rls_decidir_as_linhas(self) -> None:
        """O `GRANT` da acesso a vista; a RLS continua a decidir que linhas.

        E a razao de o `security_invoker = true` nao ser opcional: sem ele a
        vista corria com os privilegios do dono e o `GRANT` passava a dar
        **todas** as linhas de **todos** os tenants.
        """
        outro = self.criar_tenant()
        cursor = self.cursor_papel("app", self.tenant)
        cursor.execute("SELECT count(*) FROM platform.v_payment_events_audit")
        self.assertGreaterEqual(int(cursor.fetchone()[0]), 1)

        cursor_outro = self.cursor_papel("app", outro)
        cursor_outro.execute("SELECT count(*) FROM platform.v_payment_events_audit")
        self.assertEqual(int(cursor_outro.fetchone()[0]), 0)

    def test_a_cabeca_da_cadeia_le_se_como_lote(self) -> None:
        """O caminho do *job* diario, com o papel com que ele corre.

        O `kamba_batch` tem `BYPASSRLS`, pelo que ve a cabeca de **todas** as
        cobrancas — que e o que a ancora precisa de exportar.
        """
        cursor = self.cursor_papel("batch", None)
        cursor.execute(
            "SELECT charge_id, row_hash FROM platform.v_payment_ledger_heads "
            " WHERE charge_id = %s",
            (self.cobranca,),
        )
        linhas = cursor.fetchall()
        self.assertEqual(len(linhas), 1)
        self.assertEqual(len(linhas[0][1]), 32)


class TestOEloCobreAsColunas(ComLedger):
    """O elo contra o **catalogo**, e nao contra a assinatura da funcao.

    O ensaio anterior varria as catorze posicoes de argumento da
    `payment_event_row_hash` — isto e, por construcao, so os campos que ja
    estavam dentro do elo. Era tautologico quanto a pergunta que a caixa do
    critério 6 faz («um campo que nao entra no elo e um campo que se pode
    adulterar»), e deixou **nove** colunas de fora sem ninguem dar por isso.
    """

    #: O que a revisao `0029` declara como fora do elo, com a razao. Lido do
    #: proprio ficheiro da revisao: uma lista aqui divergia dela em silencio.
    @staticmethod
    def fora_do_elo() -> set[str]:
        import importlib.util
        import pathlib

        caminho = (
            pathlib.Path(__file__).resolve().parents[1]
            / "migrations"
            / "versions"
            / "0029_ledger_de_pagamentos.py"
        )
        fonte = caminho.read_text(encoding="utf-8")
        # Le-se por AST e nao por `import`: a revisao importa o `alembic.op`,
        # que fora de uma migracao nao tem contexto.
        import ast

        arvore = ast.parse(fonte)
        for no in arvore.body:
            if isinstance(no, ast.Assign) and any(
                isinstance(alvo, ast.Name) and alvo.id == "FORA_DO_ROW_HASH"
                for alvo in no.targets
            ):
                return set(ast.literal_eval(no.value))
        raise AssertionError("FORA_DO_ROW_HASH nao esta na revisao 0029")

    @staticmethod
    def campos_do_elo() -> list[str]:
        import ast
        import pathlib

        caminho = (
            pathlib.Path(__file__).resolve().parents[1]
            / "migrations"
            / "versions"
            / "0029_ledger_de_pagamentos.py"
        )
        arvore = ast.parse(caminho.read_text(encoding="utf-8"))
        for no in arvore.body:
            if isinstance(no, ast.Assign) and any(
                isinstance(alvo, ast.Name) and alvo.id == "CAMPOS_DO_ROW_HASH"
                for alvo in no.targets
            ):
                return list(ast.literal_eval(no.value))
        raise AssertionError("CAMPOS_DO_ROW_HASH nao esta na revisao 0029")

    def test_toda_a_coluna_esta_no_elo_ou_declarada_fora(self) -> None:
        """Nos dois sentidos, e e o que o torna nao-tautologico.

        Uma coluna nova na tabela que ninguem ponha no elo nem declare fora dele
        **falha** — e e exactamente o caso que deixou o `actor_id` e o
        `tenant_id` sem proteccao.
        """
        self.semente.execute(
            "SELECT column_name::text FROM information_schema.columns "
            " WHERE table_schema = 'platform' AND table_name = 'payment_events'"
        )
        colunas = {str(c) for (c,) in self.semente.fetchall()}
        no_elo = set(self.campos_do_elo())
        fora = self.fora_do_elo()

        self.assertEqual(
            colunas - no_elo - fora,
            set(),
            "ha coluna(s) do ledger que nao entram no elo nem estao declaradas "
            "em FORA_DO_ROW_HASH com a razao",
        )
        self.assertEqual(
            (no_elo | fora) - colunas,
            set(),
            "ha nome(s) no elo ou no FORA_DO_ROW_HASH que nao sao colunas",
        )
        # E as declaradas fora sao **poucas** e com razao: se alguem comecar a
        # declarar metade da tabela, isto deixa de ser uma excepcao.
        self.assertLessEqual(len(fora), 4, f"demasiadas colunas fora do elo: {fora}")

    def test_as_colunas_de_atribuicao_entram_no_elo(self) -> None:
        """Os nomes que a revisao adversarial mediu como adulteraveis.

        Cada um com a razao de contar: o `actor_id` e a atribuicao do acto
        humano (a «confirmacao humana **auditada**» do §7.1), o `tenant_id` e a
        quem o evento pertence, o `motivo` e o que ops le, e o `ocorrido_at` e
        quando o facilitador diz que aconteceu.
        """
        no_elo = set(self.campos_do_elo())
        for coluna in (
            "tenant_id",
            "order_id",
            "billing_cycle_id",
            "motivo",
            "actor_kind",
            "actor_id",
            "ocorrido_at",
            "recebido_at",
        ):
            with self.subTest(coluna=coluna):
                self.assertIn(coluna, no_elo)


class TestAFormulaRecalculaEmPython(ComLedger):
    """A formula recalculada **fora** do PostgreSQL, como a `0006` faz.

    Sem isto, a formula so e comparada consigo propria: o `verify_ledger_chain`
    chama a mesma funcao que a escreveu, pelo que um erro na formula — um
    separador a menos, um campo pela ordem errada — e consistente com ele
    proprio e invisivel. O `db/tests/test_auditoria_verificador.py` tem o
    equivalente para o ledger de auditoria, e a revisao adversarial notou que
    aqui faltava (`grep -rn hashlib db/tests_pagamentos/` dava vazio).
    """

    #: O separador de unidades do §6.2. Escrito aqui a mao, de proposito: lê-lo
    #: da revisao fazia o ensaio concordar com o que quer que ela diga.
    SEPARADOR = "\x1f"

    def setUp(self) -> None:
        super().setUp()
        self.tenant = self.criar_tenant()
        self.conta = self.criar_conta(self.tenant)
        self.cobranca = self.criar_cobranca(self.tenant, self.conta)

    def test_o_row_hash_recalcula_se_em_python(self) -> None:
        cursor = self.cursor_papel("app", self.tenant)
        self.appendar(
            cursor, self.cobranca, self.conta, "pagamento_recebido",
            p_decisao="informativo", p_motivo=None,
        )
        self.appendar(
            cursor, self.cobranca, self.conta, "pagamento_confirmado",
            p_actor_kind="ops", p_actor_id=str(uuid.uuid4()),
        )
        self.confirmar(cursor, self.tenant)

        self.semente.execute(
            "SELECT prev_hash, tenant_id, charge_id, order_id, billing_cycle_id, "
            "       provider, account_id, referencia, tipo_evento, sequencia, "
            "       provider_event_id, valor_minor, currency, authn_method, "
            "       authn_ok, decisao, motivo, actor_kind, actor_id, "
            "       payload_hash, "
            "       platform.payment_instante(ocorrido_at), "
            "       platform.payment_instante(recebido_at), row_hash "
            "  FROM platform.payment_events WHERE charge_id = %s ORDER BY id",
            (self.cobranca,),
        )
        linhas = [tuple(linha) for linha in self.semente.fetchall()]
        # Tres: o `referencia_emitida` da semente (a cobranca nasce `iniciada` e
        # chega a `emitida` pela porta) e os dois deste ensaio. **Verificam-se
        # todos**, e e isso que importa: cada um com um `motivo` e um `actor_id`
        # diferentes, incluindo nulos, que e onde os `coalesce` da formula
        # contam.
        self.assertEqual(len(linhas), 3)

        for linha in linhas:
            *campos, row_hash = linha
            partes = [
                campos[0].hex(),
                *[self._texto(c) for c in campos[1:19]],
                campos[19].hex(),
                self._texto(campos[20]),
                self._texto(campos[21]),
            ]
            esperado = hashlib.sha256(
                self.SEPARADOR.join(partes).encode("utf-8")
            ).digest()
            self.assertEqual(
                row_hash,
                esperado,
                "o row_hash da base nao e o que a formula do §6.2 da em Python",
            )

    @staticmethod
    def _texto(valor) -> str:
        if valor is None:
            return ""
        if isinstance(valor, bool):
            return "true" if valor else "false"
        return str(valor)

    def test_um_separador_a_menos_da_um_elo_diferente(self) -> None:
        """A sonda negativa do ensaio acima.

        Sem ela, uma concatenacao **sem** separador nenhum dava o mesmo valor
        nos dois lados e o ensaio ficava verde sobre uma formula ambigua — duas
        linhas diferentes com o mesmo elo.
        """
        self.semente.execute(
            "SELECT platform.payment_event_row_hash("
            "  %s, %s, %s, NULL, NULL, 'p', %s, 'a', 'pagamento_recebido', 1, "
            "  '', 1, 'AOA', 'hmac', true, 'informativo', NULL, 'provider', "
            "  NULL, %s, NULL, now())",
            (bytes(32), self.tenant, self.cobranca, self.conta, bytes(32)),
        )
        da_base = self.semente.fetchone()[0]
        sem_separador = hashlib.sha256(
            ("".join(["00" * 32, self.tenant, self.cobranca])).encode("utf-8")
        ).digest()
        self.assertNotEqual(da_base, sem_separador)


class TestOG2ComContaNula(ComLedger):
    """`p_account_id => NULL` saltava o G2 em silencio.

    `NULL <> x` avalia a `NULL`, o `IF` nao disparava, e o `INSERT` gravava o
    `account_id` **da cobranca** — pelo que nao havia `NOT NULL` que o apanhasse
    depois, ao contrario do `p_valor_minor` e do `p_authn_ok`, que as colunas
    apanham. Isto e: a unica recusa da porta que nenhum `CHECK` pode fazer era
    contornavel com um nulo.

    E o nulo nao e hipotetico: o recibo `token_desconhecido` do `hooks.ts` grava
    `accountId: null`, e um *worker* que o passasse adiante chegava aqui.
    """

    def setUp(self) -> None:
        super().setUp()
        self.tenant = self.criar_tenant()
        self.conta = self.criar_conta(self.tenant)
        self.cobranca = self.criar_cobranca(self.tenant, self.conta)

    def test_uma_conta_nula_e_recusada(self) -> None:
        cursor = self.cursor_papel("app", self.tenant)
        for tipo, decisao in (
            ("pagamento_confirmado", "aceite"),
            ("pagamento_recebido", "informativo"),
        ):
            with self.subTest(tipo=tipo):
                sql, args = self.sql_da_porta(
                    p_charge_id=self.cobranca,
                    p_tipo_evento=tipo,
                    p_account_id=None,
                    p_decisao=decisao,
                )
                self.assertErroSql(VIOLACAO_DE_CHECK, cursor, sql, args)
        self.confirmar(cursor, self.tenant)
        self.assertEqual(self.eventos_do_ensaio(self.cobranca), [])
        self.assertEqual(self.estado_da_cobranca(self.cobranca), "emitida")
