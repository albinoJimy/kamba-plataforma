"""A disciplina de ligacao dos direitos do titular (KAM-070).

E o unico ficheiro deste modulo que abre uma ligacao. O resto recebe um cursor e
nao sabe de onde ele veio — e e isso que permite que um duplo que **le o texto
da instrucao** entre no lugar dele.

## Duas ligacoes e nao uma, e a razao e um `GRANT`

Os direitos do titular atravessam dois papeis, e nao e escolha de desenho: e o
que a revisao `0003` concede.

    kamba_app        `dsar_requests`, `erasure_ledger`, `consent_event`, os
                     eventos, o `audit_log`, e as quatro consultas da
                     exportacao
    kamba_identity   `contact_endpoints` e `contact_deks` — e **so** ele: o
                     `kamba_app` nao tem `SELECT` nem `UPDATE` nem `DELETE`
                     nenhum nessas duas tabelas

Logo a rectificacao de um telefone (criterio 7) e o apagamento do cofre
(criterio 4) **nao correm na ligacao da aplicacao**. Um modulo que tentasse
levava `insufficient_privilege` — e e bom que leve: o dia em que o `kamba_app`
tiver `UPDATE` no cofre, a fronteira do ADR-010 deixou de existir e nenhum
portao deste repositorio o diz.

## Uma ligacao por chamada, dentro do `tenant_guard`

E a mesma disciplina do `destinos/dbapi.py` e do registo do AGR, e vale aqui
pela mesma razao: o `tenant_guard.tx` e exclusivo por ligacao, pelo que uma
ligacao guardada era uma ligacao disputada — e uma ligacao guardada no arranque
era tambem uma que o servidor pode ter fechado entretanto.

**O contexto de RLS nao e opcional.** Sem `app.tenant_id`, a politica
`tenant_iso` das duas tabelas da `0037` devolve **zero linhas** em vez de erro:
um pedido do titular lia-se como inexistente, o varrimento do prazo via a lista
vazia e o fecho do criterio 3 concluia que faltavam os seis escopos. Nao se
chama `SET LOCAL` a mao aqui — ha um sitio onde isso se escreve e e aquele.
"""

from __future__ import annotations

from collections.abc import Callable
from typing import Any, TypeVar

from .. import tenant_guard

#: Quem abre uma ligacao DB-API com um papel. Duas instancias por processo: uma
#: de `kamba_app`, outra de `kamba_identity`.
AbrirLigacao = Callable[[], Any]

T = TypeVar("T")


def com_tenant(
    abrir_ligacao: AbrirLigacao, tenant_id: str, trabalho: Callable[[Any], T]
) -> T:
    """Corre `trabalho(cursor)` numa transaccao com `app.tenant_id` definido.

    **Nao apanha excepcoes.** Quem as traduz e a porta, que sabe distinguir a
    colisao do pedido aberto de um `23505` qualquer; apanha-las aqui dava duas
    traducoes do mesmo erro, e a segunda perdia a informacao da primeira.

    O `tenant_guard.tx` confirma no fim e reverte no erro, pelo que o evento do
    *outbox* e a linha que o motivou ficam ou os dois ou nenhum — que e o
    *outbox* transaccional do ADR-009.
    """
    ligacao = abrir_ligacao()
    try:
        with tenant_guard.tx(ligacao, tenant_id) as cursor:
            return trabalho(cursor)
    finally:
        ligacao.close()


def como_lote(
    abrir_ligacao: AbrirLigacao, job: str, trabalho: Callable[[Any], T]
) -> T:
    """Corre `trabalho(cursor)` **sem** contexto de tenant, como `kamba_batch`.

    E o caminho do varrimento do prazo (criterio 8) e da leitura do ledger para
    o restauro (criterio 6): as duas atravessam tenants, porque um restauro e da
    base e nao de um tenant, e um alerta de prazo que corresse tenant a tenant
    precisava da lista de tenants antes de a ter.

    O `job` e obrigatorio e tem nome: e ele que fica no registo de usos de
    `kamba_batch`. O `tenant_guard` recusa um job sem nome, e isso nao e
    burocracia — um uso de `kamba_batch` sem nome e um uso que ninguem consegue
    contar nem atribuir, e `kamba_batch` e o papel que **contorna a RLS**.
    """
    ligacao = abrir_ligacao()
    try:
        with tenant_guard.tx_batch(ligacao, job) as cursor:
            return trabalho(cursor)
    finally:
        ligacao.close()


#: O nome do job do varrimento de prazos (criterio 8).
JOB_DO_VARRIMENTO = "dsar_prazos"

#: O nome do job que le o ledger para a reaplicacao apos restauro (criterio 6).
JOB_DO_RESTAURO = "dsar_reaplicacao"


__all__ = [
    "JOB_DO_RESTAURO",
    "JOB_DO_VARRIMENTO",
    "AbrirLigacao",
    "como_lote",
    "com_tenant",
]
