"""Base da suite do AGR: o que so um PostgreSQL real pode dizer (KAM-025).

O que esta suite prova, e nao se prova em lado nenhum senao aqui:

| Criterio | A propriedade, e porque e que precisa da base |
|---|---|
| 2 | `pg_advisory_lock` e exclusao mutua **entre sessoes**. Com uma ligacao nao ha forma de o medir: a segunda tomada do mesmo *lock* na mesma sessao e concedida de imediato, e um teste com uma ligacao so diz «passou» sem ter medido nada |
| 4 | A tranca larga quando a **ligacao morre**. E a propriedade que faz o SIGKILL funcionar sem temporizador nenhum, e nao ha duplo que a simule — e um comportamento do servidor |
| 6 | O `SQL_PALAVRA_DA_CONVERSA` **corre**. Uma base falsa compara SQL por texto e nunca o interpreta: um erro de sintaxe, uma coluna com outro nome, um `%s` fora de ordem — nada disso o *gate* 4 ve |
| DoD (isolamento) | A RLS esconde a conversa de A do contexto de B (X-02). A politica e da base; o codigo nao a pode provar |

A `PALAVRA` importa-se de `kamba_agr.consultas`, que e o que a aplicacao envia —
nao uma copia dela. E a licao do `tests_ten/base.py`, escrita la por extenso:
quando a suite escrevia o seu proprio SQL, o SQL da biblioteca **nunca corria
contra uma base** e tinha um defeito real que ninguem media.

O trinco e o mesmo das outras suites: a base tem de se chamar `kamba_gate8`.
"""

from __future__ import annotations

import sys
import uuid
from pathlib import Path

import ligacao
from tests import factories
from tests.base import ComBase

_RAIZ = Path(__file__).resolve().parents[2]
for _caminho in (
    _RAIZ / "libs" / "py-core" / "src",
    _RAIZ / "services" / "agr" / "src",
):
    if str(_caminho) not in sys.path:
        sys.path.insert(0, str(_caminho))

from kamba_agr.consultas import (  # noqa: E402
    SQL_DESTRANCAR_THREAD,
    SQL_HANDOFF_PARA_RETOMA,
    SQL_HANDOFFS_EXPIRADOS,
    SQL_PALAVRA_DA_CONVERSA,
    SQL_RETOMAR_HANDOFF,
    SQL_REVERTER_RETOMA,
    SQL_SLA_DE_RETOMA,
    SQL_TRANCAR_THREAD,
)
from kamba_agr.contexto import thread_id_de  # noqa: E402

__all__ = [
    "SQL_DESTRANCAR_THREAD",
    "SQL_HANDOFFS_EXPIRADOS",
    "SQL_HANDOFF_PARA_RETOMA",
    "SQL_PALAVRA_DA_CONVERSA",
    "SQL_RETOMAR_HANDOFF",
    "SQL_REVERTER_RETOMA",
    "SQL_SLA_DE_RETOMA",
    "SQL_TRANCAR_THREAD",
    "ComAgr",
    "Conversa",
    "thread_id_de",
]


class Conversa:
    """Os identificadores de uma conversa semeada, com o `thread_id` feito."""

    __slots__ = ("canal_id", "contact_id", "conversation_id", "tenant_id", "thread_id")

    def __init__(self, tenant_id, contact_id, canal_id, conversation_id) -> None:
        self.tenant_id = tenant_id
        self.contact_id = contact_id
        self.canal_id = canal_id
        self.conversation_id = conversation_id
        self.thread_id = thread_id_de(tenant_id, contact_id)


class ComAgr(ComBase):
    """Conversas semeadas e **confirmadas**; apagadas no fim.

    Confirmadas pela mesma razao que o `tests_ten/base.py` escreve: os testes da
    tranca usam ligacoes diferentes, e uma ligacao nao ve o que outra ainda nao
    confirmou. Uma conversa semeada numa transaccao aberta era invisivel a
    segunda ligacao, o `SQL_PALAVRA_DA_CONVERSA` devolvia zero linhas, e a suite
    ficava verde a afirmar sobre o nada.

    O administrador e nao o `kamba_batch`: as fabricas definem contexto, e o que
    se semeia aqui nao e o que se esta a provar.
    """

    def setUp(self) -> None:
        super().setUp()
        self._admin = ligacao.ligar("admin")
        self._admin.autocommit = True
        self.semente = self._admin.cursor()
        self._tenants: list[str] = []
        self.addCleanup(self._limpar)

    def _limpar(self) -> None:
        """Pela ordem inversa das chaves estrangeiras."""
        try:
            for tenant in self._tenants:
                for tabela in ("handoffs", "conversations", "contacts", "tenant_channels"):
                    self.semente.execute(
                        f"DELETE FROM platform.{tabela} WHERE tenant_id = %s", (tenant,)
                    )
                self.semente.execute(
                    "DELETE FROM platform.tenants WHERE id = %s", (tenant,)
                )
        finally:
            self._admin.close()

    # ------------------------------------------------------------- sementes

    def criar_conversa(self, *, modo: str = "bot") -> Conversa:
        """Um tenant, um canal, um contacto e uma conversa, tudo confirmado."""
        tenant = factories.tenant(self.semente)
        self._tenants.append(tenant)
        canal = factories.canal(self.semente, tenant)
        contacto = factories.contacto(self.semente, tenant)
        conversa = str(uuid.uuid4())
        # A janela nasce aberta: o `conversations_janela_ck` exige as duas
        # colunas ou nenhuma.
        self.semente.execute(
            "INSERT INTO platform.conversations "
            "(id, tenant_id, contact_id, channel_id, mode, "
            " last_inbound_at, window_expires_at) "
            "VALUES (%s, %s, %s, %s, %s, now(), now() + interval '24 hours')",
            (conversa, tenant, contacto, canal, modo),
        )
        factories.contexto(self.semente, None)
        return Conversa(tenant, contacto, canal, conversa)

    def abrir_handoff(
        self,
        conversa: Conversa,
        *,
        estado: str = "waiting",
        ha_horas: float = 0.0,
    ) -> str:
        """Um `handoffs` no estado dado. Devolve o `handoff_id`.

        `ha_horas` recua o `opened_at` — e o que permite ao ensaio das 24 h
        correr sem esperar um dia, e recua-se a **linha** e nao o relogio do
        servidor, porque o `limite` do `Prazos` ja vem de fora como parametro
        (KAM-034).
        """
        handoff_id = f"h-{uuid.uuid4().hex}"
        self.semente.execute(
            "INSERT INTO platform.handoffs "
            "(handoff_id, tenant_id, conversation_id, status, motivo, opened_at) "
            "VALUES (%s, %s, %s, %s, 'ensaio', now() - make_interval(secs => %s))",
            (
                handoff_id,
                conversa.tenant_id,
                conversa.conversation_id,
                estado,
                ha_horas * 3600.0,
            ),
        )
        return handoff_id

    def mudar_modo(self, conversa: Conversa, modo: str) -> None:
        self.semente.execute(
            "UPDATE platform.conversations SET mode = %s WHERE id = %s",
            (modo, conversa.conversation_id),
        )

    # --------------------------------------------------------------- portas

    def ligacao_de_tranca(self):
        """Uma ligacao de `kamba_app` em `autocommit`, para `pg_advisory_*`.

        `autocommit` porque e assim que o `kamba_agr.ligacao.ligar_para_tranca`
        a abre, e porque uma tranca de **sessao** tomada dentro de uma
        transacção aberta mantinha aberta exactamente a transacção que esta
        escolha existe para evitar (ADR-L004, Decisao 2).
        """
        conexao = self.ligar("app")
        conexao.autocommit = True
        return conexao

    def ler_palavra(self, conexao, conversa: Conversa, *, como: str | None = None):
        """O `SQL_PALAVRA_DA_CONVERSA` com contexto de `como` (ou do tenant).

        Devolve `(modo, handoff_a_espera)` ou `None`. Os quatro `%s` vao pela
        ordem do texto do SQL — o `EXISTS` aparece primeiro —, e e por isso que
        esta funcao existe: quem os passasse a mao em cada teste podia troca-los
        e ler a resposta de outra conversa sem erro nenhum.
        """
        tenant = conversa.tenant_id if como is None else como
        cursor = conexao.cursor()
        try:
            factories.contexto(cursor, tenant)
            cursor.execute(
                SQL_PALAVRA_DA_CONVERSA,
                (
                    conversa.tenant_id,
                    conversa.conversation_id,
                    conversa.tenant_id,
                    conversa.conversation_id,
                ),
            )
            linha = cursor.fetchone()
        finally:
            cursor.close()
        return None if linha is None else (str(linha[0]), bool(linha[1]))
