"""O nome da loja da apresentacao, contra o PostgreSQL (KAM-235, criterio 2).

A `PortaDeGrafos.do_turno` le o `tenants.nome` antes do turno, pelo
`leitor_da_loja` do `conversa.py`, e a apresentacao do vendedor nomeia a loja com
ele. O duplo do `services/agr/tests/test_grafos.py` prova a frase; o que so a
base diz:

| Propriedade | Porque precisa da base |
|---|---|
| o SQL do leitor **corre** com o `kamba_app` | o `SELECT` na `tenants` pela ligacao de leitura |
| le o nome deste tenant, com digitos | a coluna e a do observador do teste (`SQL_FACTOS_DO_TESTE`) |
| com o contexto de outro tenant, nao le nada | a RLS da `tenants` |

O SQL e o `SQL_NOME_DA_LOJA` de `kamba_agr.consultas`, chamado pelas funcoes do
`conversa.py` — nao uma copia.
"""

from __future__ import annotations

import asyncio

import ligacao
from tests_agr.base import ComAgr

# O `tests_agr.base` poe o `services/agr/src` no caminho, e por isso vem antes.
from kamba_agr import conversa  # noqa: E402
from kamba_core import tenant_guard  # noqa: E402


class TestNomeDaLoja(ComAgr):
    def setUp(self) -> None:
        super().setUp()
        self.tenant = self.criar_conversa().tenant_id
        self.semente.execute(
            "UPDATE platform.tenants SET nome = 'Kero 24' WHERE id = %s", (self.tenant,)
        )

    def test_o_leitor_le_o_nome_deste_tenant_pela_aplicacao(self) -> None:
        self.assertEqual(conversa.nome_da_loja_sincrono(self.ligar("app"), self.tenant), "Kero 24")

    def test_um_nome_mudado_le_se_no_turno_seguinte(self) -> None:
        self.semente.execute(
            "UPDATE platform.tenants SET nome = 'Casa Bela' WHERE id = %s", (self.tenant,)
        )
        self.assertEqual(conversa.nome_da_loja_sincrono(self.ligar("app"), self.tenant), "Casa Bela")

    def test_o_leitor_assincrono_abre_e_fecha_uma_ligacao_de_aplicacao(self) -> None:
        abertas: list = []

        def abrir():
            ligacao_app = ligacao.ligar("app")
            abertas.append(ligacao_app)
            return ligacao_app

        ler = conversa.leitor_da_loja(abrir)
        self.assertEqual(asyncio.run(ler(self.tenant)), "Kero 24")
        self.assertEqual(len(abertas), 1)

    def test_o_nome_de_outro_tenant_nao_se_le(self) -> None:
        """O `tenant_id` do predicado e o do contexto sao o mesmo: zero linhas da
        RLS da `tenants` para um tenant que nao e o do contexto."""
        outro = self.criar_conversa().tenant_id
        with tenant_guard.tx(self.ligar("app"), outro) as cursor:
            cursor.execute(conversa.SQL_NOME_DA_LOJA, (self.tenant,))
            self.assertIsNone(cursor.fetchone())
