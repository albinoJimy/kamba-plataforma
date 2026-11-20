"""Os contactos do tenant pelo cofre, na purga (KAM-218, criterio 6).

O KAM-098 deixou a porta (`purga.ApagarContactos`) e o KAM-210 deixou-a sem
adaptador: sem ela, as tres tabelas do cofre ficam `recusada`/`sem_caminho` no
`purge_log`. Este e o adaptador, e e o **apagamento do KAM-008** — o
`eraseContact` do `packages/core-ts/src/identity/contactos.ts` — feito para todos
os contactos do tenant de uma vez:

    contact_endpoints   apagados (os BSUID e os telefones cifrados)
    contact_deks        o embrulho destruido (`wrapped_dek = NULL`) e datado:
                        e o *crypto-shredding* — o que a base e as copias ainda
                        tiverem cifrado deixa de abrir
    contacts            o HMAC do telefone apagado e o `erased_at` datado; a
                        linha fica, porque as encomendas e o *ledger* a referem

## Corre como `kamba_identity`, e so como ele

As tres tabelas sao do cofre: o `kamba_batch` nao tem `DELETE` nelas (o
`test_os_caminhos_da_purga_sao_os_que_o_lote_pode_apagar` di-lo), e o
`kamba_identity` e o papel que as escreve, sob a RLS do tenant
(`tenant_guard.tx`). Por isso este adaptador recebe a **sua** fabrica de
ligacoes, e nao a do lote. O `kamba_identity` nao le a `tenants` (invariante do
KAM-008), e este modulo nao precisa dela.

## Nao decifra nada

O *crypto-shredding* destroi o embrulho da DEK; nao precisa da KEK nem de abrir
cifra nenhuma. E por isso que cabe no Python sem a porta do cofre de chaves
(`KeyProvider`), que vive no TypeScript: a decifra dos telefones para a
exportacao (criterio 5) e outra coisa, e continua por fazer.

## Idempotente

Repetir nao apaga nada de novo e devolve zero: os endpoints ja sairam, as DEK
destruidas nao se destroem outra vez (`destroyed_at IS NULL`), e um contacto
apagado nao se marca outra vez (`erased_at IS NULL`).
"""

from __future__ import annotations

from collections.abc import Callable
from typing import Any, Final

from .. import tenant_guard
from .purga import ApagarContactos

AbrirLigacao = Callable[[], Any]

#: O papel que este adaptador espera. Ver a nota do modulo.
PAPEL_DO_COFRE: Final = "kamba_identity"

#: As tres instrucoes do `eraseContact` (`identity/consultas.ts`:
#: `APAGAR_ENDPOINTS`, `DESTRUIR_DEKS`, `MARCAR_APAGADO`), sem o `contact_id`: o
#: tenant inteiro. **Cada uma filtra pelo tenant no texto**, alem da RLS.
SQL_APAGAR_ENDPOINTS: Final = "DELETE FROM platform.contact_endpoints WHERE tenant_id = %s"
SQL_DESTRUIR_DEKS: Final = (
    "UPDATE platform.contact_deks SET wrapped_dek = NULL, destroyed_at = now() "
    "WHERE tenant_id = %s AND destroyed_at IS NULL"
)
SQL_MARCAR_APAGADOS: Final = (
    "UPDATE platform.contacts SET phone_hmac = NULL, hmac_kid = NULL, erased_at = now() "
    "WHERE tenant_id = %s AND erased_at IS NULL"
)


def apagar_contactos_pelo_cofre(abrir_cofre: AbrirLigacao) -> ApagarContactos:
    """A porta da purga: apaga os contactos do tenant e devolve as linhas por tabela.

    As tres, e nao so os contactos: cada uma vai ao `purge_log`, e a das DEK e a
    prova do *crypto-shredding* que o certificado mostra.
    """

    def apagar(tenant_id: str) -> dict[str, int]:
        tenant = tenant_guard.normalizar_tenant(tenant_id)
        ligacao = abrir_cofre()
        linhas: dict[str, int] = {}
        try:
            with tenant_guard.tx(ligacao, tenant) as cursor:
                for tabela, sql in (
                    ("platform.contact_endpoints", SQL_APAGAR_ENDPOINTS),
                    ("platform.contact_deks", SQL_DESTRUIR_DEKS),
                    ("platform.contacts", SQL_MARCAR_APAGADOS),
                ):
                    cursor.execute(sql, (tenant,))
                    linhas[tabela] = max(int(cursor.rowcount or 0), 0)
            return linhas
        finally:
            ligacao.close()

    return apagar


__all__ = [
    "PAPEL_DO_COFRE",
    "SQL_APAGAR_ENDPOINTS",
    "SQL_DESTRUIR_DEKS",
    "SQL_MARCAR_APAGADOS",
    "apagar_contactos_pelo_cofre",
]
