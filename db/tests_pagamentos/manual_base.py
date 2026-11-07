"""Base da confirmacao manual: confirmadores, limites e as cinco funcoes (KAM-054).

Estende o `ComLedger` em vez de o alterar: a suite do ledger (KAM-053) nao
precisa de nada disto, e acrescentar-lhe sementes de confirmadores fazia cada um
dos seus 103 ensaios pagar o custo delas.

## O que so aqui se prova, e nenhuma base falsa pode

    payment_confirmers    a aplicacao **le** e nao escreve: um `INSERT` como
                          `kamba_app` falha por **privilegio** (`42501`) antes
                          de chegar a politica. Uma base falsa nao tem papeis
    manual_confirmations  idem, e com uma consequencia que se mede: a funcao
                          descobre quem e o cliente lendo a fase
                          `declaracao_cliente`, e nao ha por onde a escrever
    G8                    um `pagamento_confirmado` com `authn_method='manual'`
                          recusado **ao superutilizador** por falta de fase. O
                          *trigger* tem `ENABLE ALWAYS`, e nenhum duplo de teste
                          imita isso
    concorrencia          duas confirmacoes simultaneas da mesma cobranca em
                          ligacoes proprias, que e o que os «Testes Requeridos»
                          pedem. Em serie, a segunda nem chega a disputar a
                          tranca
    RLS                   a confirmacao de A invisivel no contexto de B, com as
                          funcoes a correr `SECURITY DEFINER` — isto e, a prova
                          de que o `DEFINER` **nao** contorna o `FORCE`

## As sementes sao confirmadas, pela razao do `tests_pagamentos/base.py`

Uma ligacao nao ve o que outra ainda nao confirmou, e os ensaios de concorrencia
correm em ligacoes proprias. Um confirmador semeado dentro de uma transaccao
aberta era **invisivel** para elas — com a suite verde e nada provado.
"""

from __future__ import annotations

import datetime
import json
import uuid

from tests import factories
from tests_pagamentos.base import VALOR, ComLedger

#: 50 000 Kz em unidade menor. A **proposta** do M-2, e entra aqui como semente
#: e nao como constante de producao: o que o codigo le e o `entitlements`.
TECTO_MANUAL = 5_000_000

#: 20 000 Kz em unidade menor. A proposta do M-5.
TECTO_DA_DUPLA = 2_000_000

#: Tectos de janela largos, para os ensaios que nao os medem. Quem os mede
#: passa-os apertados.
TECTO_DIARIO = 100_000_000
TECTO_POR_CONTACTO = 10

#: Os limites de um tenant em que **tudo passa**, para cada ensaio mudar um.
LIMITES = {
    "manual_max_minor": TECTO_MANUAL,
    "manual_dupla_acima_minor": TECTO_DA_DUPLA,
    "manual_daily_max_minor": TECTO_DIARIO,
    "manual_max_por_contacto_24h": TECTO_POR_CONTACTO,
}


class ComConfirmacaoManual(ComLedger):
    """Um tenant com conta, cobranca `emitida`, limites e contactos semeados."""

    def setUp(self) -> None:
        super().setUp()
        self.tenant = self.criar_tenant()
        self.conta = self.criar_conta(self.tenant, provider="manual")
        # A encomenda **explicita**, desde a revisao `0035` (KAM-055): o
        # `inserir_evento_humano` escreve um `payment_events` directo, e a
        # `payment_events_encomenda_do_mesmo_tenant_fk` recusa um `order_id` que
        # nao exista. E tem de ser **a da cobranca**: um evento nao aponta para
        # um sujeito diferente do da cobranca a que pertence.
        self.encomenda = self.criar_encomenda(self.tenant)
        self.cobranca = self.criar_cobranca(
            self.tenant,
            self.conta,
            provider="manual",
            metodo="manual",
            order_id=self.encomenda,
        )
        self.dar_limites(self.tenant)
        self.cliente = self.criar_contacto(self.tenant)
        self.dono = self.criar_contacto(self.tenant)
        self.segundo = self.criar_contacto(self.tenant)
        self.criar_confirmador(self.tenant, self.dono, papel="dono")
        self.criar_confirmador(
            self.tenant, self.segundo, papel="funcionario", segunda=True
        )
        self.cursor = self.cursor_papel("app", self.tenant)
        # **Os contactos apagam-se aqui e nao no `ComLedger`**, e a razao
        # mediu-se: o `_limpar` da base do ledger apaga o tenant, e a
        # `contacts_tenant_fk` nao o deixa sair enquanto houver contactos. O
        # `addCleanup` corre em ordem inversa ao registo, pelo que este — o
        # ultimo a registar-se — corre **antes** do `_limpar`, que e a ordem
        # certa das FK.
        self.addCleanup(self._limpar_confirmacoes)

    def _limpar_confirmacoes(self) -> None:
        """Apaga pela ordem inversa das FK, e os contactos **depois das fases**.

        A ordem nao e estilo: custou um erro que nao parecia ser da limpeza. A
        primeira versao apagava os contactos com um `NOT IN (SELECT
        actor_contact_id FROM manual_confirmations)`, e deixava la o contacto de
        quem **tentou** confirmar — porque a tentativa recusada escreve uma fase
        `rejeicao` com o `actor_contact_id` dela. O `_limpar` do `ComLedger`
        chegava depois e levava `23503` da `contacts_tenant_fk` ao apagar o
        tenant, o que se le como um defeito do isolamento e e um defeito desta
        funcao.

        **As fases apagam-se**, e podem: a `manual_confirmations` nao tem
        *trigger* de imutabilidade, ao contrario da `payment_events` e do
        `order_state_log` — a barreira dela e de privilegio (nenhum papel de
        aplicacao escreve) e nao de *trigger*, o que foi escolha escrita na
        revisao `0032`, precisamente para que uma suite possa limpar. O que fica
        sao as **cobrancas com eventos**, que a FK do ledger nao deixa sair, e
        por isso os tenants delas tambem ficam; a base do *gate* 8 e descartavel
        e cada ensaio cria o seu tenant, pelo que o que fica nao e visto por mais
        ninguem.

        E e um `DELETE` por tenant e nao uma subconsulta sobre a tabela inteira:
        a forma anterior varria a `manual_confirmations` uma vez por tenant e por
        ensaio, e com 77 ensaios isso cresce em quadrado.
        """
        for tenant in self._tenants:
            for tabela in (
                "fraud_signals",
                "refund_cases",
                "payment_confirmers",
                "manual_confirmations",
            ):
                self.semente.execute(
                    f"DELETE FROM platform.{tabela} WHERE tenant_id = %s", (tenant,)
                )
            # Os contactos **que a encomenda nao prende**.
            #
            # O `DELETE` era sem condicao, e deixou de poder ser: desde a
            # revisao `0035` (KAM-055) o `criar_cobranca` semeia uma encomenda,
            # e a `orders_mirror_contacto_do_mesmo_tenant_fk` recusa apagar o
            # contacto dela. A encomenda, por sua vez, fica quando o ledger a
            # referencia — e a `base.py` deste directorio explica porque.
            #
            # E a condicao e **so** a da encomenda: as outras quatro tabelas
            # que referenciam `contacts` saem no laco de cima, pelo que quando
            # esta linha corre ja nenhuma as prende.
            self.semente.execute(
                "DELETE FROM platform.contacts WHERE tenant_id = %s "
                "  AND contact_id NOT IN (SELECT contact_id "
                "                           FROM platform.orders_mirror "
                "                          WHERE tenant_id = %s)",
                (tenant, tenant),
            )

    # --------------------------------------------------------------- sementes

    def criar_contacto(self, tenant: str) -> str:
        return factories.contacto(self.semente, tenant)

    def criar_confirmador(
        self,
        tenant: str,
        contacto: str,
        papel: str = "dono",
        segunda: bool = False,
        ativo: bool = True,
    ) -> None:
        self.semente.execute(
            "INSERT INTO platform.payment_confirmers "
            "(tenant_id, contact_id, papel, pode_segunda_aprovacao, ativo) "
            "VALUES (%s, %s, %s, %s, %s)",
            (tenant, contacto, papel, segunda, ativo),
        )

    def dar_limites(self, tenant: str, **mudancas) -> None:
        """Um entitlement activo com os quatro limites. `None` **remove** a chave.

        A remocao existe porque «sem tecto» e um caso de teste e nao uma
        omissao: a `ten_tecto` devolve `NULL` quando nenhum modulo activo declara
        a chave, e a leitura fechada disso e negar. Passar `0` nao serve — zero e
        um tecto, e um tecto de zero recusa por outra razao.
        """
        limites = dict(LIMITES)
        limites.update(mudancas)
        limites = {chave: valor for chave, valor in limites.items() if valor is not None}
        # **Apaga antes de inserir**, e nao e zelo: o `setUp` ja chamou este
        # metodo, e um ensaio que mude um limite chama-o outra vez. A
        # `entitlements_pk` e `(tenant_id, modulo)` e a segunda chamada levava
        # `23505` — nove ensaios de uma vez, todos a falhar por uma chave
        # duplicada numa semente e nao pela regra que mediam.
        self.semente.execute(
            "DELETE FROM platform.entitlements WHERE tenant_id = %s "
            "  AND modulo = 'pagamentos'",
            (tenant,),
        )
        factories.entitlement(
            self.semente, tenant, modulo="pagamentos", limites=limites, ativo=True
        )

    def cobranca_paga(self, cursor=None) -> str:
        """Uma cobranca **paga pelo caminho humano inteiro**. Devolve o `id`.

        Nao se semeia um `estado='paga'`: nao ha como. O `estado` so muda pela
        projeccao da `append_payment_event`, e o caminho humano so passa o G8 com
        a fase escrita pela `manual_confirmar`. Isto e, esta semente **e** o
        caminho felizdos criterios 2 a 5, e por isso os ensaios da reversao
        (criterio 8) correm sobre uma cobranca que chegou a `paga` como em
        producao.
        """
        cursor = cursor or self.cursor
        self.declarar(self.cobranca, self.cliente, f"d:{uuid.uuid4().hex}", cursor=cursor)
        veredicto = self.confirmar_manual(
            self.cobranca, self.dono, f"c:{uuid.uuid4().hex}", VALOR, cursor=cursor
        )
        assert veredicto[3] == "confirma", veredicto
        assert veredicto[2] == "paga", veredicto
        return self.cobranca

    # ---------------------------------------------------------- as cinco portas

    def declarar(
        self,
        cobranca: str,
        actor: str,
        msg: str,
        evidencia: str | None = None,
        cursor=None,
    ):
        cursor = cursor or self.cursor
        cursor.execute(
            "SELECT confirmacao_id, event_id, estado_novo, repetida "
            "  FROM platform.manual_declarar("
            "    p_charge_id => %s, p_actor_contact_id => %s, "
            "    p_canal_msg_id => %s, p_evidencia_ref => %s)",
            (cobranca, actor, msg, evidencia),
        )
        return cursor.fetchone()

    def confirmar_manual(
        self, cobranca: str, actor: str, msg: str, valor: int, cursor=None
    ):
        """`manual_confirmar`. **Nao** se chama `confirmar`: esse e o `COMMIT`.

        O `ComLedger.confirmar` faz `COMMIT` e repoe o contexto, e um nome
        repetido aqui tornava impossivel ver qual dos dois um ensaio queria.
        """
        cursor = cursor or self.cursor
        cursor.execute(
            "SELECT confirmacao_id, event_id, estado_novo, decisao, motivo, "
            "       valor_bate, sinal_id, repetida "
            "  FROM platform.manual_confirmar("
            "    p_charge_id => %s, p_actor_contact_id => %s, "
            "    p_canal_msg_id => %s, p_valor_declarado_minor => %s)",
            (cobranca, actor, msg, valor),
        )
        return cursor.fetchone()

    def expirar(self, cobranca: str, horas: int = 24, cursor=None):
        cursor = cursor or self.cursor
        cursor.execute(
            "SELECT confirmacao_id, event_id, estado_novo "
            "  FROM platform.manual_expirar_confirmacao("
            "    p_charge_id => %s, p_janela_horas => %s)",
            (cobranca, horas),
        )
        # `list` e nao o que o `fetchall` devolve: o `pg8000` devolve uma tupla
        # de tuplas, e `() != []` fez dois ensaios falharem com uma mensagem que
        # nao dizia nada sobre a regra que eles mediam.
        return [tuple(linha) for linha in cursor.fetchall()]

    def reverter(self, cobranca: str, actor: str, msg: str, motivo: str, cursor=None):
        cursor = cursor or self.cursor
        cursor.execute(
            "SELECT confirmacao_id, event_id, estado_novo, refund_case_id "
            "  FROM platform.manual_reverter("
            "    p_charge_id => %s, p_actor_contact_id => %s, "
            "    p_canal_msg_id => %s, p_motivo => %s)",
            (cobranca, actor, msg, motivo),
        )
        return cursor.fetchone()

    def janela(self, tenant: str, contacto: str, agora=None, cursor=None):
        cursor = cursor or self.cursor
        cursor.execute(
            "SELECT soma_do_dia_minor, tecto_diario_minor, "
            "       confirmacoes_do_contacto, tecto_do_contacto "
            "  FROM platform.manual_janela("
            "    p_tenant_id => %s, p_contact_id => %s, p_agora => %s)",
            (tenant, contacto, agora or datetime.datetime.now(datetime.timezone.utc)),
        )
        return cursor.fetchone()

    # ------------------------------------------------------------- leituras

    def fases(self, cobranca: str) -> list[tuple]:
        self.semente.execute(
            "SELECT fase, valor_bate, motivo, valor_declarado_minor "
            "  FROM platform.manual_confirmations WHERE charge_id = %s "
            " ORDER BY criado_at, id",
            (cobranca,),
        )
        return [tuple(linha) for linha in self.semente.fetchall()]

    def sinais(self, cobranca: str) -> list[tuple]:
        self.semente.execute(
            "SELECT regra, severidade, accao FROM platform.fraud_signals "
            " WHERE charge_id = %s ORDER BY id",
            (cobranca,),
        )
        return [tuple(linha) for linha in self.semente.fetchall()]

    def casos_de_reembolso(self, cobranca: str) -> list[tuple]:
        self.semente.execute(
            "SELECT estado, valor_minor, motivo FROM platform.refund_cases "
            " WHERE charge_id = %s ORDER BY criado_at, id",
            (cobranca,),
        )
        return [tuple(linha) for linha in self.semente.fetchall()]

    def quantos_eventos(self, cobranca: str) -> int:
        self.semente.execute(
            "SELECT count(*) FROM platform.payment_events WHERE charge_id = %s",
            (cobranca,),
        )
        return int(self.semente.fetchone()[0])

    def inserir_evento_humano(self, cobranca: str, actor: str, cursor) -> tuple:
        """O SQL de um `INSERT` directo de `pagamento_confirmado` humano.

        Para o ensaio do G8 — e **so** pelo superutilizador, que e o unico com
        `INSERT` nesta tabela. E a mesma via do `TestOsCheckMordemSozinhos`, e
        pela mesma razao: e o que os `REVOKE` nao prendem.
        """
        return (
            "INSERT INTO platform.payment_events "
            "(tenant_id, charge_id, order_id, provider, account_id, referencia, "
            " tipo_evento, sequencia, valor_minor, authn_method, authn_ok, "
            " decisao, actor_kind, actor_id, payload_hash, prev_hash, row_hash) "
            "VALUES (%s, %s, %s, 'manual', %s, %s, 'pagamento_confirmado', 99, "
            f" %s, 'manual', true, 'aceite', 'dono', %s, sha256('{{}}'::bytea), "
            f" '\\x{'00' * 32}'::bytea, sha256('x'::bytea))",
            (
                self.tenant,
                cobranca,
                self.encomenda,
                self.conta,
                f"REF{uuid.uuid4().hex[:12]}",
                VALOR,
                actor,
            ),
        )


__all__ = [
    "LIMITES",
    "TECTO_DA_DUPLA",
    "TECTO_DIARIO",
    "TECTO_MANUAL",
    "TECTO_POR_CONTACTO",
    "ComConfirmacaoManual",
    "json",
]
