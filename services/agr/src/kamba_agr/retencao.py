"""A varredura de retencao do `lg` (KAM-026, criterio 8).

## O que apaga, e com que papel

*Threads* sem escrita nenhuma ha mais do que `DIAS_DE_INACTIVIDADE` dias. A
varredura e o `SQL_THREADS_INACTIVAS` seguido de um `adelete_thread` por
*thread*, e corre com o **`kamba_batch`** — o papel `BYPASSRLS` que a revisao
`0020` autoriza a `SELECT` e `DELETE` no `lg`, e **nao** a `INSERT`: quem limpa
nao escreve.

A ligacao vem de quem chama, de proposito. O AGR corre com o `kamba_app` e o
`kamba_agr`, e dar-lhe um terceiro papel com `BYPASSRLS` para uma varredura que
corre fora de qualquer pedido era alargar o que o servico pode fazer pelo resto
do tempo.

## Nao ha agendador, e isso esta escrito

Como no KAM-017, **nao ha agendador nesta fase** — o `ADR-L004` e o bloco do
KAM-025 dizem-no. Esta funcao e o corpo da varredura; quem a chama a horas e o
KAM-071 (retencao global) com o KAM-079. Entrega-se o que apaga e prova-se com
relogio simulado; agendar sem agendador era escrever um que ninguem pediu.

## O prazo tem dois valores no canon, e nenhum e decisao minha

| Fonte | Prazo |
|---|---|
| `docs/tecnica/02` §12 | *threads* inactivos **> 30 dias** |
| `docs/tecnica/08` §7.1 e §11 | conteudo de conversa **90 dias apos o fecho** |
| EPIC-07, KAM-071 | 90 dias, com `kamba_batch` |

E os dois nao sao o mesmo relogio: um conta inactividade, o outro conta a
partir do **fecho da conversa** — que **nao esta definido em documento nenhum**.
Fica o valor do §12 como *proposta*, porque e o que o bloco deste ticket cita,
e os dois prazos escritos; o §11 do `docs/tecnica/08` ja diz que «os prazos sao
**propostas** de engenharia» e o bloco manda confirmar por parecer. Quem fechar
o parecer escolhe um, e esta constante e o sitio onde se muda.
"""

from __future__ import annotations

import datetime as _dt
from typing import Any, Final

from . import consultas

#: Dias sem escrita ao fim dos quais uma *thread* se apaga. ***Proposta*** —
#: ver a nota do modulo sobre os dois prazos do canon.
DIAS_DE_INACTIVIDADE: Final = 30


async def varrer(
    checkpointer: Any,
    ligacao: Any,
    agora: _dt.datetime,
    dias: int = DIAS_DE_INACTIVIDADE,
) -> list[str]:
    """Apaga as *threads* paradas ha mais de `dias` e devolve as que apagou.

    O `checkpointer` e quem apaga — pelo `adelete_thread`, que e o metodo da
    interface e o unico sitio onde a ordem das duas tabelas esta escrita. A
    `ligacao` e so para **descobrir** quais, e e ela que traz o `kamba_batch`.

    Devolve a lista em vez de um numero: quem chama regista o que apagou, e uma
    varredura que diz «apaguei 4» nao se audita.
    """
    if dias < 0:
        raise ValueError("os dias de inactividade nao podem ser negativos")
    limite = agora - _dt.timedelta(days=dias)
    cursor = ligacao.cursor()
    try:
        cursor.execute(consultas.SQL_THREADS_INACTIVAS, (limite,))
        threads = [linha[0] for linha in cursor.fetchall()]
    finally:
        cursor.close()
    ligacao.commit()
    for thread_id in threads:
        await checkpointer.adelete_thread(thread_id)
    return threads
