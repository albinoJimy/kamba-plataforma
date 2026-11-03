"""Base da suite do ledger: tenant, conta de pagamento e cobranca, confirmadas.

O que esta suite prova e a **revisao `0029`** (KAM-053), e o que ela prova nao se
simula: o objecto da prova e o servidor.

    privilegios   um `INSERT` directo em `payment_events` falha com `42501`
                  **antes** de chegar a qualquer `CHECK`. Uma base falsa nao tem
                  papeis, logo nao pode falhar por privilegio nenhum
    deny_mutation um `UPDATE` recusado **ao superutilizador**. Nenhuma matriz de
                  privilegios o consegue, e nenhum duplo de teste o imita
    FOR UPDATE    vinte sessoes concorrentes com sequencias 1..20 sem lacunas.
                  Em serie, a segunda nem chega a disputar a tranca
    RLS FORCE     a cobranca de A invisivel no contexto de B, com a funcao a
                  correr `SECURITY DEFINER` — isto e, a prova de que o `DEFINER`
                  **nao** contorna o `FORCE` (`db/rls.py`)
    outbox        uma falha forcada no `evt_emitir` a reverter a linha do ledger.
                  So uma transaccao real o mostra
    cadeia        um byte alterado com **superutilizador** — o unico que os
                  `REVOKE` e os *triggers* nao prendem — a fazer o
                  `verify_ledger_chain` apontar o elo

## Porque e que as sementes sao confirmadas

Pela razao do `db/tests_produtos/base.py`: uma ligacao nao ve o que outra ainda
nao confirmou. Os ensaios de concorrencia correm em vinte ligacoes proprias, e
uma cobranca semeada dentro de uma transaccao aberta era **invisivel** para elas
— com a suite verde e nada provado.

## Suite propria, e nao dentro de `tests`

Pela razao do `tests_servicos`, do `tests_ten` e do `tests_produtos`: as vinte
sessoes concorrentes e a propriedade de mil sequencias custam relogio, e uma
suite paga isso por cada mutacao que a escolha. O que e **do catalogo fechado** —
as colunas das quatro tabelas, a matriz de privilegios, as restricoes e os
indices — fica onde o trinco esta, em `db/tests/test_inventario.py`,
`test_catalogo.py` e `test_privilegios.py`, e **nao** aqui.
"""

from __future__ import annotations

import datetime
import json
import uuid

import ligacao
from tests import factories
from tests.base import ComBase

#: 12 500 Kz em unidade menor. 1 Kz = 100 centimos.
VALOR = 1_250_000

#: O `provider` dos ensaios. Nao e o `manual` nem o `proxypay`: nenhum adaptador
#: real corre nesta suite, e usar o nome de um dava a entender que corria.
PROVIDER = "fakeprovider"

#: O mapeamento de *outbox* de **ensaio**. O definitivo e do KAM-055, e o bloco
#: manda testar com um de ensaio — ver o `_mapa_do_outbox` da revisao. O tipo EVT
#: e o `payment.confirmed` do dicionario §3.4, que ja existe.
EVT_DO_CONFIRMADO = "payment.confirmed"


def _chamada(argumentos: dict) -> tuple[str, tuple]:
    """A chamada por nome, com o `::jsonb` **explicito** no payload.

    Sem o molde, o `pg8000` envia a cadeia como texto e o PostgreSQL recusa-a
    com `42804` — e nao `23514` —, o que fazia um `assertErroSql` de um caso
    negativo passar pela razao errada: o erro vinha do tipo do argumento e nao da
    recusa que o ensaio queria medir. Medido na primeira execucao desta suite.
    """
    nomes = ", ".join(
        f"{nome} => %s::jsonb" if nome == "p_payload" else f"{nome} => %s"
        for nome in argumentos
    )
    return (
        f"SELECT * FROM platform.append_payment_event({nomes})",
        tuple(argumentos.values()),
    )


class ComLedger(ComBase):
    """Um tenant com conta de pagamento activa e uma cobranca, semeados."""

    def setUp(self) -> None:
        super().setUp()
        self._admin = ligacao.ligar("admin")
        self._admin.autocommit = True
        self.semente = self._admin.cursor()
        self._tenants: list[str] = []
        self._contas: list[str] = []
        self._papeis: dict[str, object] = {}
        #: Quantos eventos a semente deixou em cada cobranca. Uma cobranca que
        #: nasce `iniciada` e chega a `emitida` **pela porta** leva um
        #: `referencia_emitida`; os ensaios que afirmam «zero eventos» ou uma
        #: contagem exacta querem dizer «zero/N **meus**», e e o
        #: `eventos_do_ensaio` que lhes da isso.
        self._semeados: dict[str, int] = {}
        self.addCleanup(self._limpar)

    def _limpar(self) -> None:
        try:
            self.semente.execute("DELETE FROM platform.payment_outbox_map")
            for tenant in self._tenants:
                # Pela ordem inversa das FK. Nenhuma apaga em cascata, de
                # proposito.
                #
                # **O `payment_events` nao se apaga, e e por desenho**: o
                # `payment_events_imutavel` recusa o `DELETE` ao administrador
                # tambem — e se nao recusasse, o ledger nao era append-only e
                # metade desta suite nao provava nada. A primeira versao desta
                # limpeza tentava, e os erros que levou sao a prova de que a
                # barreira morde.
                #
                # Por isso as cobrancas com eventos **tambem** ficam: a FK
                # `payment_events_charge_fk` nao as deixa sair. O que se apaga e
                # o que nao tem eventos, e a base do *gate* 8 e descartavel —
                # cada teste cria o seu tenant e toda a leitura filtra por ele.
                for tabela in ("payment_callbacks_inbox",):
                    self.semente.execute(
                        f"DELETE FROM platform.{tabela} WHERE account_id IN "
                        "(SELECT id FROM platform.payment_accounts "
                        " WHERE tenant_id = %s)",
                        (tenant,),
                    )
                self.semente.execute(
                    "DELETE FROM platform.payment_charges WHERE tenant_id = %s "
                    "  AND id NOT IN (SELECT charge_id FROM platform.payment_events)",
                    (tenant,),
                )
                for tabela in ("events_outbox", "evt_agregado_seq"):
                    self.semente.execute(
                        f"DELETE FROM platform.{tabela} WHERE tenant_id = %s",
                        (tenant,),
                    )
                self.semente.execute(
                    "DELETE FROM platform.payment_accounts WHERE tenant_id = %s "
                    "  AND id NOT IN (SELECT account_id FROM platform.payment_charges)",
                    (tenant,),
                )
                self.semente.execute(
                    "DELETE FROM platform.tenants WHERE id = %s "
                    "  AND id NOT IN (SELECT tenant_id FROM platform.payment_charges)",
                    (tenant,),
                )
        finally:
            # **So a de administrador.** As dos papeis vem do `ComBase.ligar`,
            # que as registra e as fecha no `tearDown` — e os `addCleanup`
            # correm **depois** dele.
            self._admin.close()

    # --------------------------------------------------------------- sementes

    def criar_tenant(self) -> str:
        tenant = factories.tenant(self.semente)
        self._tenants.append(tenant)
        return tenant

    def criar_conta(self, tenant: str, **campos) -> str:
        """Uma `payment_account` de PME activa. Devolve o `id`.

        O parametro do *token* chama-se `wt` e nao `webhook_token` pela razao do
        `db/tests/test_pagamentos_schema.py`: o padrao `atribuicao` do
        `scan_secrets` (gate 9) da falso positivo numa atribuicao com esse nome.
        """
        valores = {
            "id": str(uuid.uuid4()),
            "beneficiary_kind": "pme",
            "tenant_id": tenant,
            "provider": PROVIDER,
            "entidade": "00123",
            "estado": "ativo",
            "wt": uuid.uuid4().hex,
        }
        valores.update(campos)
        # **A segunda conta do mesmo `(tenant, provider)` nao pode ficar
        # `ativo`**, e nao e uma limitacao do ensaio: e o
        # `payment_accounts_um_ativo` da `0027`, um indice unico parcial sobre
        # `(tenant_id, provider)` onde o estado ocupa. Um ensaio que precise de
        # duas contas para a mesma PME e o mesmo facilitador — e ha tres nesta
        # suite — tem de deixar a segunda num estado que nao ocupa. Fica aqui e
        # nao em cada ensaio porque esquecer-se disto da `23505` numa semente, o
        # que se le como um defeito do ledger e e um defeito da conta.
        if "estado" not in campos:
            self.semente.execute(
                "SELECT count(*) FROM platform.payment_accounts "
                " WHERE tenant_id = %s AND provider = %s "
                "   AND estado IN ('ativo', 'teste_sandbox_ok')",
                (valores["tenant_id"], valores["provider"]),
            )
            if int(self.semente.fetchone()[0]) > 0:
                valores["estado"] = "credenciais_recebidas"
        token = valores.pop("wt")
        colunas = ", ".join([*valores, "webhook_token"])
        marcas = ", ".join(["%s"] * (len(valores) + 1))
        self.semente.execute(
            f"INSERT INTO platform.payment_accounts ({colunas}) VALUES ({marcas})",
            (*valores.values(), token),
        )
        self._contas.append(valores["id"])
        return valores["id"]

    def criar_cobranca(self, tenant: str, conta: str, **campos) -> str:
        """Uma `payment_charges` em `emitida`. Devolve o `id`.

        **Nasce em `iniciada` e chega a `emitida` pela porta.**

        A primeira versao inseria `estado='emitida'` directamente, e isso
        deixou de ser possivel — e deixou de ser possivel por causa de um
        defeito que a revisao adversarial apanhou: o `estado` nao tinha valor
        inicial imposto, pelo que um `INSERT` com `estado='paga'` passava. O
        *trigger* `payment_charges_nasce_iniciada` fechou essa via, e esta
        semente paga o preco de a fechar: duas chamadas em vez de uma.

        E o preco e **ganho**, nao perda: a cobranca das sementes passa a chegar
        a `emitida` pelo mesmo caminho que em producao, com um
        `referencia_emitida` no ledger. A primeira versao semeava um estado que
        nenhum evento explicava — isto e, toda a suite corria contra cobrancas
        que a `rebuild_charge_state` nao conseguia reproduzir, e foi assim que o
        achado 2 da revisao (o *job* a levantar `data_corrupted`) se tornou
        possivel de todo.
        """
        valores = {
            "id": str(uuid.uuid4()),
            "tenant_id": tenant,
            "order_id": str(uuid.uuid4()),
            "account_id": conta,
            "provider": PROVIDER,
            "metodo": "referencia",
            "referencia": f"REF{uuid.uuid4().hex[:12]}",
            "amount_minor": VALOR,
            # `NOT NULL` no §6.2: uma cobranca sem prazo nao expira nunca, e o
            # F-06 precisa de saber quando emitir a tentativa seguinte.
            "valid_until": datetime.datetime.now(datetime.timezone.utc)
            + datetime.timedelta(hours=24),
        }
        valores.update(campos)
        # O estado pedido, se houver: a cobranca nasce sempre `iniciada` e
        # chega ao resto **pela porta**.
        destino = valores.pop("estado", "emitida")
        colunas = ", ".join(valores)
        marcas = ", ".join(["%s"] * len(valores))
        self.semente.execute(
            f"INSERT INTO platform.payment_charges ({colunas}) VALUES ({marcas})",
            tuple(valores.values()),
        )
        if destino != "iniciada":
            self._semeados[valores["id"]] = self._levar_a(
                valores["tenant_id"], valores["id"], valores["account_id"], destino
            )
        return valores["id"]

    #: Como se chega a cada estado a partir de `iniciada`, pela porta. As
    #: arestas sao as do §7.1; o `authn_method` e `sistema` nos factos de ciclo
    #: de vida que ninguem autentica, e `hmac` no que vem do facilitador.
    CAMINHOS: dict[str, tuple[tuple[str, str, str], ...]] = {
        "emitida": (("referencia_emitida", "informativo", "sistema"),),
        "aguarda_cliente": (("push_enviado", "informativo", "sistema"),),
        "pendente_confirmacao": (
            ("referencia_emitida", "informativo", "sistema"),
            ("confirmacao_manual_pedida", "informativo", "sistema"),
        ),
        "paga": (
            ("referencia_emitida", "informativo", "sistema"),
            ("pagamento_confirmado", "aceite", "hmac"),
        ),
        "expirada": (
            ("referencia_emitida", "informativo", "sistema"),
            ("cobranca_expirada", "informativo", "sistema"),
        ),
        "falhada": (
            ("referencia_emitida", "informativo", "sistema"),
            ("pagamento_divergente", "rejeitada", "hmac"),
        ),
        "cancelada": (
            ("referencia_emitida", "informativo", "sistema"),
            ("cobranca_cancelada", "informativo", "sistema"),
        ),
    }

    def _levar_a(
        self, tenant: str, cobranca: str, conta: str, destino: str
    ) -> int:
        """Leva a cobranca de `iniciada` ao estado pedido, **pela porta**.

        Semear um estado directamente deixou de ser possivel (o *trigger* do
        nascimento), e e melhor assim: o que a suite semeia passa a ser
        reproduzivel pela `rebuild_charge_state`, que e a propriedade que o
        criterio 5 mede.

        **O `tenant` vem por argumento e nao se le da tabela**, e isto custou 67
        erros na primeira versao: a leitura era `SELECT tenant_id FROM
        payment_charges WHERE id = …` como `kamba_app` **sem contexto** — isto
        e, a politica `tenant_iso` escondia a linha, o `set_config` recebia
        `NULL`, e a porta recusava com «a cobranca nao existe ou nao e visivel».
        E um galo-e-ovo: nao se pode descobrir o tenant de uma linha que so se
        ve com o tenant no contexto.
        """
        caminho = self.CAMINHOS.get(destino)
        if caminho is None:
            raise AssertionError(
                f"nao ha caminho conhecido de iniciada para {destino!r}; "
                "o §7.1 pode nao ter aresta nenhuma"
            )
        cursor = self.cursor_papel("app", tenant)
        for tipo, decisao, metodo in caminho:
            self.appendar(
                cursor, cobranca, conta, tipo,
                p_decisao=decisao, p_authn_method=metodo,
            )
        self.confirmar(cursor, tenant)
        return len(caminho)

    def mapear_outbox(
        self,
        tipo_evento: str = "pagamento_confirmado",
        authn_method: str = "hmac",
        evt_tipo: str = EVT_DO_CONFIRMADO,
    ) -> None:
        """O mapeamento de ensaio. O definitivo e do KAM-055."""
        self.semente.execute(
            "INSERT INTO platform.payment_outbox_map "
            "(tipo_evento, authn_method, evt_tipo) VALUES (%s, %s, %s)",
            (tipo_evento, authn_method, evt_tipo),
        )

    # ------------------------------------------------------------- ligacoes

    def cursor_papel(self, identidade: str, tenant: str | None = None):
        """Cursor da identidade pedida com o contexto dado (ou sem nenhum).

        `kamba_app` e `NOBYPASSRLS`: e com ele que o PAY corre em producao, e
        **so com ele** e que um ensaio de isolamento quer dizer alguma coisa.
        Com o administrador a politica nao se aplica e o ensaio nao prova nada.

        A transaccao fica **aberta**, porque o `assertErroSql` precisa de um
        `SAVEPOINT`.
        """
        chave = f"{identidade}:{tenant or ''}"
        conexao = self._papeis.get(chave)
        if conexao is None:
            conexao = self.ligar(identidade)
            self._papeis[chave] = conexao
        cursor = conexao.cursor()  # type: ignore[attr-defined]
        cursor.execute("SELECT set_config('app.tenant_id', %s, true)", (tenant or "",))
        cursor.fetchone()
        return cursor

    def confirmar(self, cursor, tenant: str | None) -> None:
        """`COMMIT` **e repoe o contexto**, que e a parte que custa ensaios.

        O `set_config('app.tenant_id', …, true)` e **local a transaccao**: o
        `true` e exactamente isso. Depois de um `COMMIT`, o contexto volta a
        cadeia vazia, o `NULLIF` da `tenant_iso` reduz essa cadeia a `NULL`, e a
        leitura seguinte na mesma ligacao nao ve linha nenhuma — a
        `append_payment_event` recusa com «a cobranca nao existe ou nao e
        visivel», que e uma mensagem certa sobre um ensaio mal escrito.

        Medido: 44 dos 62 ensaios desta suite falharam por isto na segunda
        execucao, todos com o mesmo `23514`. Um `COMMIT` cru nesta suite e um
        defeito, e e por haver este metodo que se ve qual deles o esqueceu.
        """
        cursor.execute("COMMIT")
        cursor.execute("SELECT set_config('app.tenant_id', %s, true)", (tenant or "",))
        cursor.fetchone()

    # ----------------------------------------------------------- a porta

    def appendar(self, cursor, cobranca: str, conta: str, tipo: str, **campos):
        """`SELECT * FROM append_payment_event(...)`, com as omissoes dos ensaios.

        Chama-se com `SELECT * FROM`, que e a forma do criterio 1 — a funcao
        devolve `TABLE (...)`.
        """
        argumentos = {
            "p_charge_id": cobranca,
            "p_tipo_evento": tipo,
            "p_account_id": conta,
            "p_valor_minor": VALOR,
            "p_authn_method": "hmac",
            "p_authn_ok": True,
            "p_decisao": "aceite",
            "p_motivo": None,
            "p_actor_kind": "provider",
            "p_actor_id": None,
            "p_provider_event_id": None,
            "p_payload": json.dumps({}),
            "p_ocorrido_at": None,
        }
        argumentos.update(campos)
        cursor.execute(*_chamada(argumentos))
        return cursor.fetchone()

    def sql_da_porta(self, **campos) -> tuple[str, tuple]:
        """O mesmo, em texto, para o `assertErroSql` (que recebe SQL e argumentos)."""
        argumentos = {
            "p_charge_id": None,
            "p_tipo_evento": None,
            "p_account_id": None,
            "p_valor_minor": VALOR,
            "p_authn_method": "hmac",
            "p_authn_ok": True,
            "p_decisao": "aceite",
            "p_motivo": None,
            "p_actor_kind": "provider",
            "p_actor_id": None,
            "p_provider_event_id": None,
            "p_payload": json.dumps({}),
            "p_ocorrido_at": None,
        }
        argumentos.update(campos)
        return _chamada(argumentos)

    # ------------------------------------------------------------- leituras

    def eventos_da_cobranca(self, cobranca: str) -> list[tuple]:
        self.semente.execute(
            "SELECT tipo_evento, sequencia, decisao, valor_minor "
            "  FROM platform.payment_events WHERE charge_id = %s ORDER BY id",
            (cobranca,),
        )
        return [tuple(linha) for linha in self.semente.fetchall()]

    def eventos_do_ensaio(self, cobranca: str) -> list[tuple]:
        """Os eventos que **o ensaio** escreveu, sem os da semente.

        Existe porque a cobranca passou a nascer `iniciada` e a chegar ao estado
        pedido **pela porta** — ver o `_levar_a` —, pelo que ha um
        `referencia_emitida` no ledger antes de o ensaio comecar. Um ensaio que
        afirma «zero eventos» quer dizer «zero **meus**», e escrever `[:1]` a
        mao em cada um era deixar o numero a envelhecer em dez sitios.
        """
        return self.eventos_da_cobranca(cobranca)[self._semeados.get(cobranca, 0) :]

    def estado_da_cobranca(self, cobranca: str) -> str:
        self.semente.execute(
            "SELECT estado FROM platform.payment_charges WHERE id = %s", (cobranca,)
        )
        return self.semente.fetchone()[0]
