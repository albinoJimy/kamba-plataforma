"""As accoes sensiveis do dono contra o PostgreSQL (KAM-118, criterios 4 e 5).

O que o duplo de `services/agr/tests/test_dono.py` nao prova, e so a base diz:

| Propriedade | Porque precisa da base |
|---|---|
| duplo toque concorrente -> **1** confirmacao | e a tranca de linha do `UPDATE ... RETURNING`, entre duas sessoes |
| o SQL do `accoes.py` **corre** com o papel `kamba_app` | os privilegios por coluna da `0070` (`SELECT (papel, papel_mudou_at)`, `UPDATE (estado, confirmada_at)`) |
| um botao de outro tenant e `desconhecida` | a RLS `FORCE` da `owner_actions` esconde a linha |
| propor tres vezes da uma linha | a `UNIQUE (tenant_id, tipo, ref)` e o `ON CONFLICT ON CONSTRAINT` com o nome dela |

As instrucoes sao as de `kamba_agr.dono.accoes`, chamadas pelas funcoes do
modulo — nao uma copia do SQL.
"""

from __future__ import annotations

import datetime
import threading
import uuid

from tests import factories
from tests_agr.base import ComAgr

# O `tests_agr.base` poe o `services/agr/src` no caminho, e por isso vem antes.
from kamba_agr.dono import accoes  # noqa: E402


def _agora() -> datetime.datetime:
    return datetime.datetime.now(datetime.UTC)


class TestOwnerActions(ComAgr):
    def setUp(self) -> None:
        super().setUp()
        self.conversa = self.criar_conversa()
        self.tenant = self.conversa.tenant_id
        self.dono = self.conversa.contact_id
        self.semente.execute(
            "UPDATE platform.contacts SET papel = 'dono' WHERE tenant_id = %s AND contact_id = %s",
            (self.tenant, self.dono),
        )
        # As accoes apagam-se **antes** dos contactos (a FK), e a limpeza do
        # `ComAgr` foi registada primeiro, pelo que corre depois desta.
        self.addCleanup(self._limpar_accoes)
        # O `tearDown` do `ComBase` fecha as ligacoes que o `ligar` abriu.
        self.app = self.ligar("app")

    def _limpar_accoes(self) -> None:
        for tenant in self._tenants:
            self.semente.execute(
                "DELETE FROM platform.owner_actions WHERE tenant_id = %s", (tenant,)
            )

    def _linhas(self, tenant: str) -> list[tuple]:
        self.semente.execute(
            "SELECT action_id, estado, confirmada_at FROM platform.owner_actions "
            "WHERE tenant_id = %s",
            (tenant,),
        )
        return list(self.semente.fetchall())

    # ----------------------------------------------------------------- propor

    def test_propor_tres_vezes_da_uma_linha(self) -> None:
        agora = _agora()
        ids = {
            accoes.propor(self.app, self.tenant, self.dono, "aprovar_conteudo", "c-1", agora)
            for _ in range(3)
        }
        self.assertEqual(len(ids), 1)
        self.assertEqual(len(self._linhas(self.tenant)), 1)

    def test_um_cliente_nao_propoe(self) -> None:
        cliente = factories.contacto(self.semente, self.tenant)
        factories.contexto(self.semente, None)
        with self.assertRaises(accoes.AccaoRecusadaError):
            accoes.propor(self.app, self.tenant, cliente, "aprovar_conteudo", "c-1", _agora())
        self.assertEqual(self._linhas(self.tenant), [])

    # -------------------------------------------------------------- confirmar

    def test_duplo_toque_sequencial_da_uma_confirmacao(self) -> None:
        action_id = accoes.propor(
            self.app, self.tenant, self.dono, "preco_stock_em_massa", "lote-1", _agora()
        )
        desfechos = [
            accoes.confirmar(self.app, self.tenant, self.dono, f"confirm:{action_id}", _agora())
            for _ in range(2)
        ]
        self.assertEqual(desfechos, [accoes.CONFIRMADA, accoes.JA_CONFIRMADA])
        [(_, estado, confirmada_at)] = self._linhas(self.tenant)
        self.assertEqual(estado, "confirmada")
        self.assertIsNotNone(confirmada_at)

    def test_duplo_toque_concorrente_em_duas_sessoes_da_uma_confirmacao(self) -> None:
        action_id = accoes.propor(
            self.app, self.tenant, self.dono, "preco_stock_em_massa", "lote-2", _agora()
        )
        ligacoes = [self.ligar("app") for _ in range(2)]
        barreira = threading.Barrier(2)
        desfechos: list[str] = []
        trinco = threading.Lock()

        def tocar(ligacao) -> None:
            barreira.wait()
            desfecho = accoes.confirmar(
                ligacao, self.tenant, self.dono, f"confirm:{action_id}", _agora()
            )
            with trinco:
                desfechos.append(desfecho)

        fios = [threading.Thread(target=tocar, args=(ligacao,)) for ligacao in ligacoes]
        for fio in fios:
            fio.start()
        for fio in fios:
            fio.join(timeout=30)
        self.assertEqual(sorted(desfechos), sorted([accoes.CONFIRMADA, accoes.JA_CONFIRMADA]))

    def test_o_botao_fora_do_prazo_expira_e_a_linha_diz_expirada(self) -> None:
        ha_vinte_minutos = _agora() - datetime.timedelta(minutes=20)
        action_id = accoes.propor(
            self.app, self.tenant, self.dono, "enviar_proposta", "prop-1", ha_vinte_minutos
        )
        desfecho = accoes.confirmar(
            self.app, self.tenant, self.dono, f"confirm:{action_id}", _agora()
        )
        self.assertEqual(desfecho, accoes.EXPIRADA)
        [(_, estado, confirmada_at)] = self._linhas(self.tenant)
        self.assertEqual(estado, "expirada")
        self.assertIsNone(confirmada_at)

    def test_vinte_textos_nao_confirmam(self) -> None:
        action_id = accoes.propor(
            self.app, self.tenant, self.dono, "aprovar_conteudo", "c-2", _agora()
        )
        textos = (
            "sim", "ok", "confirmo", "sim confirmo", "pode publicar", "esta bem", "claro",
            "yes", "1", "SIM", "Ok", "confirmar", "podes", "ta bem", "isso",
            f"sim {action_id}", f"confirm: {action_id}", f"confirm:{action_id.upper()}",
            "confirm:", f"cancelar:{action_id}",
        )
        for texto in textos:
            with self.subTest(texto=texto):
                self.assertEqual(
                    accoes.confirmar(self.app, self.tenant, self.dono, texto, _agora()),
                    accoes.NAO_E_BOTAO,
                )
        [(_, estado, _)] = self._linhas(self.tenant)
        self.assertEqual(estado, "pendente")

    def test_o_botao_de_um_tenant_nao_existe_no_outro(self) -> None:
        """A RLS: a linha de A nao se ve com o contexto de B, nem com o `action_id`."""
        action_id = accoes.propor(
            self.app, self.tenant, self.dono, "aprovar_conteudo", "c-3", _agora()
        )
        outra = self.criar_conversa()
        self.semente.execute(
            "UPDATE platform.contacts SET papel = 'dono' WHERE tenant_id = %s AND contact_id = %s",
            (outra.tenant_id, outra.contact_id),
        )
        desfecho = accoes.confirmar(
            self.app, outra.tenant_id, outra.contact_id, f"confirm:{action_id}", _agora()
        )
        self.assertEqual(desfecho, accoes.DESCONHECIDA)
        [(_, estado, _)] = self._linhas(self.tenant)
        self.assertEqual(estado, "pendente")

    def test_depois_da_troca_ha_bloqueio(self) -> None:
        self.semente.execute(
            "UPDATE platform.contacts SET papel_mudou_at = now() - interval '1 hour' "
            "WHERE tenant_id = %s AND contact_id = %s",
            (self.tenant, self.dono),
        )
        action_id = accoes.propor(
            self.app, self.tenant, self.dono, "enviar_proposta", "prop-2", _agora()
        )
        self.assertEqual(
            accoes.confirmar(self.app, self.tenant, self.dono, f"confirm:{action_id}", _agora()),
            accoes.BLOQUEADA_PELA_TROCA,
        )

    def test_um_botao_inexistente_e_desconhecido(self) -> None:
        self.assertEqual(
            accoes.confirmar(
                self.app, self.tenant, self.dono, f"confirm:{uuid.uuid4()}", _agora()
            ),
            accoes.DESCONHECIDA,
        )
