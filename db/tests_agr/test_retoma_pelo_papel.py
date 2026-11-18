"""A retoma pelo papel de agora, contra o PostgreSQL (KAM-211, criterio «Retoma»).

A `PortaDeGrafos.da_thread` resolve o grafo de uma *thread* interrompida pelo
papel **actual** do contacto, lido pelo `leitor_de_papel` do `conversa.py`, e nao
pela persona do *checkpoint* (achado 4 da revisao do KAM-118). O duplo do
`services/agr/tests/test_dono.py` prova a escolha do grafo; o que so a base diz:

| Propriedade | Porque precisa da base |
|---|---|
| o SQL do leitor **corre** com o `kamba_app` | o `SELECT (papel, papel_mudou_at)` por coluna da `0070` |
| o leitor ve o papel que a porta escreveu | a troca e a `platform.definir_dono`, chamada como `kamba_identity` — o caminho de producao, sem superutilizador |
| depois da troca, o dono antigo le-se `cliente` | e o que faz o *handoff* dele retomar no grafo da vertical |
| um contacto apagado, ou de outro tenant, nao tem papel | o `erased_at` do predicado e a RLS `FORCE` da `contacts` |

O SQL e o de `kamba_agr.dono.accoes`, chamado pelas funcoes do `conversa.py` — nao
uma copia.
"""

from __future__ import annotations

import asyncio

import ligacao
from tests import factories
from tests_agr.base import ComAgr

# O `tests_agr.base` poe o `services/agr/src` no caminho, e por isso vem antes.
from kamba_agr import conversa  # noqa: E402

PORTA = "SELECT platform.definir_dono(%s, %s)"


class TestRetomaPeloPapel(ComAgr):
    def setUp(self) -> None:
        super().setUp()
        self.conversa = self.criar_conversa()
        self.tenant = self.conversa.tenant_id
        self.antigo = self.conversa.contact_id
        self.novo = factories.contacto(self.semente, self.tenant)
        factories.contexto(self.semente, None)
        # O `owner_contact_id` que a porta escreve prende os contactos: larga-se
        # antes da limpeza do `ComAgr`, que foi registada primeiro e corre depois.
        self.addCleanup(self._largar_o_dono)

    def _largar_o_dono(self) -> None:
        for tenant in self._tenants:
            self.semente.execute(
                "UPDATE platform.tenants SET owner_contact_id = NULL WHERE id = %s", (tenant,)
            )

    def _definir(self, contacto: str, origem: str) -> None:
        """A porta, como `kamba_identity` com o contexto do tenant, e confirmada."""
        identidade = ligacao.ligar("identity")
        try:
            cursor = identidade.cursor()
            cursor.execute("SELECT set_config('app.tenant_id', %s, true)", (self.tenant,))
            cursor.execute(PORTA, (contacto, origem))
            identidade.commit()
        finally:
            identidade.close()

    def _papel(self, contacto: str, tenant: str | None = None) -> str | None:
        return conversa.papel_do_contacto_sincrono(
            self.ligar("app"), tenant or self.tenant, contacto
        )

    def test_sem_porta_os_dois_sao_cliente(self) -> None:
        self.assertEqual(self._papel(self.antigo), "cliente")
        self.assertEqual(self._papel(self.novo), "cliente")

    def test_o_leitor_le_o_dono_que_o_provisionamento_escreveu(self) -> None:
        self._definir(self.antigo, "provisionamento")
        self.assertEqual(self._papel(self.antigo), "dono")
        self.assertEqual(self._papel(self.novo), "cliente")

    def test_depois_da_troca_o_dono_antigo_le_se_cliente(self) -> None:
        """O cenario do criterio: a troca de telefone despromove o antigo, e a
        retoma do *handoff* dele le `cliente` — o grafo da vertical."""
        self._definir(self.antigo, "provisionamento")
        self._definir(self.novo, "troca_de_telefone")
        self.assertEqual(self._papel(self.antigo), "cliente")
        self.assertEqual(self._papel(self.novo), "dono")

    def test_o_leitor_assincrono_abre_e_fecha_uma_ligacao_de_aplicacao(self) -> None:
        self._definir(self.antigo, "provisionamento")
        abertas: list = []

        def abrir():
            ligacao_app = ligacao.ligar("app")
            abertas.append(ligacao_app)
            return ligacao_app

        ler = conversa.leitor_de_papel(abrir)
        self.assertEqual(asyncio.run(ler(self.tenant, self.antigo)), "dono")
        self._definir(self.novo, "troca_de_telefone")
        self.assertEqual(asyncio.run(ler(self.tenant, self.antigo)), "cliente")
        self.assertEqual(len(abertas), 2)

    def test_um_dono_apagado_nao_tem_papel(self) -> None:
        self._definir(self.antigo, "provisionamento")
        self.semente.execute(
            "UPDATE platform.contacts SET erased_at = now() "
            "WHERE tenant_id = %s AND contact_id = %s",
            (self.tenant, self.antigo),
        )
        self.assertIsNone(self._papel(self.antigo))

    def test_o_dono_de_outro_tenant_nao_se_ve(self) -> None:
        """O par e o da *thread*: com o tenant de B, o contacto de A e zero
        linhas, e a retoma le `cliente`."""
        self._definir(self.antigo, "provisionamento")
        outro = self.criar_conversa()
        self.assertIsNone(self._papel(self.antigo, tenant=outro.tenant_id))
