"""Tres tenants ficticios, com canarios. Dados sinteticos; nenhum dado real.

O plano do §4.2 pede «3 tenants ficticios (canal + localizacao + `merchant_id`)».
Tres e nao dois, e a razao esta na matriz: o ISO-51..56 quer contagens
independentes entre tenants a competir pelo mesmo SKU, e com dois tenants um
teste que confunda «o de A» com «o que nao e de B» passa por acidente.

**O SKU `SKU-COLISAO` existe nos tres.** E o canario do ISO-33..38: a colisao de
SKU entre tenants e o caso em que um filtro por `sku` sem `tenant_id` parece
funcionar — devolve uma linha, com o preco errado e o stock de outra PME.
"""

from __future__ import annotations

import dataclasses
import uuid

import ligacao


@dataclasses.dataclass(frozen=True)
class TenantFicticio:
    rotulo: str
    tenant_id: str
    contact_id: str
    #: `sku -> (preco_minor, quantidade, stock_modo, preco_tipo)`
    skus: dict

    @property
    def sales_channel_id(self) -> str:
        """O que `tenants.medusa_sales_channel_id` guarda na opcao B."""
        return f"sc_spike_{self.rotulo.lower()}"

    @property
    def merchant_id(self) -> str:
        """O que `tenants.medusa_merchant_id` guarda na opcao B."""
        return f"merch_spike_{self.rotulo.lower()}"


#: O SKU que existe em todos os tenants, com **precos diferentes**: um preco
#: trocado e a prova visivel de que o filtro falhou.
SKU_COLISAO = "SKU-COLISAO"

_PLANO = {
    "A": {SKU_COLISAO: (150_000, 10, "garantido", "fixo"),
          "SKU-A-UNICO": (90_000, 25, "garantido", "fixo"),
          "SKU-A-SOBCONSULTA": (None, 5, "indicativo", "sob_consulta")},
    "B": {SKU_COLISAO: (990_000, 7, "garantido", "fixo"),
          "SKU-B-UNICO": (40_000, 12, "indicativo", "fixo")},
    "C": {SKU_COLISAO: (1_000, 3, "garantido", "fixo"),
          "SKU-C-UNICO": (10_000, 4, "garantido", "a_partir_de")},
}


def semear(ambiente: dict[str, str]) -> dict[str, TenantFicticio]:
    """Cria os tres tenants e devolve-os por rotulo. Confirma o que escreve.

    Semeia-se com `kamba_batch` (BYPASSRLS, auditado) e nao com `kamba_app`: a
    RLS do 0002 poe `tenants` sob politica por `id`, pelo que um contexto de
    tenant so cria o tenant cujo `id` e o do proprio contexto. Semear com o
    papel da aplicacao era semear com a barreira que o teste vai medir.
    """
    conexao = ligacao.ligar("batch", ambiente)
    conexao.autocommit = True
    cursor = conexao.cursor()
    # `contacts` e a excepcao: a revisao 0003 da `INSERT` so a
    # `kamba_identity`, que e NOBYPASSRLS. Semeia-se com ele e com o contexto
    # posto, porque a politica `tenant_iso` tem `WITH CHECK`.
    identidade = ligacao.ligar("identity", ambiente)
    identidade.autocommit = True
    cursor_identidade = identidade.cursor()
    tenants: dict[str, TenantFicticio] = {}
    try:
        for rotulo, skus in _PLANO.items():
            tenant_id = str(uuid.uuid4())
            cursor.execute(
                "INSERT INTO platform.tenants "
                "  (id, tipo, nome, estado, medusa_sales_channel_id, medusa_merchant_id) "
                "VALUES (%s, 'pme', %s, 'ativo', %s, %s)",
                (tenant_id, f"Spike KAM-041 tenant {rotulo}",
                 f"sc_spike_{rotulo.lower()}", f"merch_spike_{rotulo.lower()}"),
            )
            cursor_identidade.execute(
                "SELECT set_config('app.tenant_id', %s, false)", (tenant_id,)
            )
            cursor_identidade.fetchone()
            cursor_identidade.execute(
                "INSERT INTO platform.contacts (tenant_id) VALUES (%s) "
                "RETURNING contact_id",
                (tenant_id,),
            )
            contact_id = str(cursor_identidade.fetchone()[0])

            for sku, (preco, quantidade, stock_modo, preco_tipo) in skus.items():
                cursor.execute(
                    "INSERT INTO platform.offer_terms "
                    "  (tenant_id, sku, preco_tipo, preco_minor, currency, "
                    "   stock_modo, estado, preco_atualizado_at) "
                    "VALUES (%s, %s, %s, %s, 'AOA', %s, 'publicado', now())",
                    (tenant_id, sku, preco_tipo, preco, stock_modo),
                )
                cursor.execute(
                    "INSERT INTO platform.spike_stock_levels "
                    "  (tenant_id, sku, quantidade) VALUES (%s, %s, %s)",
                    (tenant_id, sku, quantidade),
                )
            tenants[rotulo] = TenantFicticio(rotulo, tenant_id, contact_id, skus)
        return tenants
    finally:
        identidade.close()
        conexao.close()


def repor_stock(ambiente: dict[str, str], tenant: TenantFicticio, sku: str,
                quantidade: int) -> None:
    """Poe o stock de um SKU num valor exacto e limpa as reservas desse SKU.

    O AC-3 corre varias vezes (um motor `sql`, um motor `medusa`) e cada
    execucao tem de partir de stock 10 exacto. Reutilizar o estado da execucao
    anterior era medir a segunda com a contencao da primeira.
    """
    conexao = ligacao.ligar("batch", ambiente)
    conexao.autocommit = True
    cursor = conexao.cursor()
    try:
        cursor.execute(
            "UPDATE platform.stock_reservations SET estado = 'libertada' "
            " WHERE tenant_id = %s AND sku = %s AND estado = 'ativa'",
            (tenant.tenant_id, sku),
        )
        cursor.execute(
            "UPDATE platform.spike_stock_levels SET quantidade = %s, reservada = 0 "
            " WHERE tenant_id = %s AND sku = %s",
            (quantidade, tenant.tenant_id, sku),
        )
    finally:
        conexao.close()
