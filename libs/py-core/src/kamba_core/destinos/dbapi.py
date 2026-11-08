"""Os leitores de `tenant_destinations` contra uma ligacao DB-API (KAM-069).

E o unico ficheiro deste modulo que sabe que ha uma base de dados. A decisao
vive no `porta.py` e e pura; o *gate* de go-live vive no `golive.py` e tambem; o
que esta aqui e a disciplina de ligacao, e ela e **a mesma que o KAM-030 ja
escolheu** para o registo de chamadas:

    uma ligacao por chamada, aberta, usada dentro de `tenant_guard.tx` e fechada

O `registo.py` do AGR diz porque, e vale aqui pela mesma razao: o
`tenant_guard.tx` e exclusivo por ligacao e o AGR corre turnos em paralelo, pelo
que uma ligacao guardada era uma ligacao disputada — e uma ligacao guardada no
arranque era tambem uma que o servidor pode ter fechado entretanto.

**O custo esta medido e e pequeno:** a *cache* da porta tem TTL de 60 s, pelo que
uma ligacao so se abre quando a decisao nao esta la. Sem *cache* seria uma
ligacao por chamada ao modelo; com ela, uma por par (tenant, fornecedor,
finalidade) por minuto.

## O contexto de RLS nao e opcional, e e por isso que estes leitores existem

A `0036` tem **duas** politicas permissivas: a `tenant_iso`, que exige
`app.tenant_id`, e a `destinos_globais`, que nao. Uma leitura **sem** contexto
devolve as linhas globais e nenhuma das especificas — e a porta, que da
precedencia as especificas, concluiria que o tenant nao tem decisao propria. Um
tenant com um destino `negado` por decisao sua passava pela linha global
`autorizado`.

O `tenant_guard.tx` poe o `app.tenant_id` e e o que fecha esse buraco. Nao se
chama `SET LOCAL` a mao aqui: ha um sitio onde isso se escreve e e aquele.
"""

from __future__ import annotations

from collections.abc import Callable, Mapping, Sequence
from typing import Any

from .. import tenant_guard
from .consultas import SQL_DESTINOS, SQL_DESTINOS_DO_TENANT

#: Quem abre uma ligacao DB-API. No AGR e o `ligar_para_llm` do `ligacao.py`.
AbrirLigacao = Callable[[], Any]


def _linhas(cursor: Any) -> tuple[Mapping[str, object], ...]:
    """As linhas como mapas, da `cursor.description`.

    **Nao assume um `row_factory`.** A ligacao do AGR pode devolver tuplos, e um
    `linha["status"]` sobre um tuplo levanta `TypeError` — que o `decidir`
    apanharia e traduziria para «nao se conseguiu ler», escondendo um erro de
    configuracao atras de uma recusa. Com a `description`, o leitor funciona nas
    duas formas.
    """
    colunas = [descricao[0] for descricao in cursor.description]
    return tuple(dict(zip(colunas, linha, strict=True)) for linha in cursor.fetchall())


def leitor(abrir_ligacao: AbrirLigacao) -> Callable[..., Sequence[Mapping[str, object]]]:
    """Um `LeitorDeDestinos` sobre uma ligacao por chamada.

    Devolve as linhas cruas: a decisao nao se toma aqui. **Nao apanha
    excepcoes** — quem o faz e o `decidir` da porta, que as traduz para
    `TransferenciaNegada` com a classe do erro e sem o texto dele. Apanha-las
    aqui dava duas traducoes do mesmo erro, e a segunda perdia a informacao da
    primeira.
    """

    def ler(
        tenant: str, fornecedor: str, finalidade: str
    ) -> Sequence[Mapping[str, object]]:
        ligacao = abrir_ligacao()
        try:
            with tenant_guard.tx(ligacao, tenant) as cursor:
                cursor.execute(SQL_DESTINOS, (tenant, fornecedor, finalidade))
                return _linhas(cursor)
        finally:
            ligacao.close()

    return ler


def ler_destinos_do_tenant(
    abrir_ligacao: AbrirLigacao, tenant_id: str
) -> tuple[Mapping[str, object], ...]:
    """As linhas de todos os destinos do tenant, para o *gate* de go-live.

    Mesma disciplina de ligacao, mesma ausencia de `try`: quem traduz e o
    `destinos_do_tenant` do `golive.py`.
    """
    ligacao = abrir_ligacao()
    try:
        with tenant_guard.tx(ligacao, tenant_id) as cursor:
            cursor.execute(SQL_DESTINOS_DO_TENANT, (tenant_id,))
            return _linhas(cursor)
    finally:
        ligacao.close()
