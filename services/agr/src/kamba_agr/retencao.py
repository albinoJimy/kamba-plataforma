"""A varredura de retencao do `lg` (KAM-026, criterio 8).

## O que apaga, e com que papel

*Threads* sem escrita nenhuma ha mais do que `DIAS_DE_INACTIVIDADE` dias. A
varredura e o `SQL_THREADS_INACTIVAS` para descobrir, e depois duas instrucoes
por *thread* — os checkpoints e as escritas orfas —, **todas na mesma ligacao**,
que e a do `kamba_batch`: o papel `BYPASSRLS` que a revisao `0020` autoriza a
`SELECT` e `DELETE` no `lg`, e **nao** a `INSERT`, porque quem limpa nao
escreve.

O apagamento **nao** passa pelo `adelete_thread` do checkpointer, e isso e
deliberado: aquele corre com o `kamba_agr`, e usa-lo aqui fazia do `GRANT` ao
`kamba_batch` privilegio morto — foi o que a primeira versao deste modulo fez,
e o que ela escreveu sobre si mesma era falso.

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


def varrer(
    ligacao: Any,
    agora: _dt.datetime,
    dias: int = DIAS_DE_INACTIVIDADE,
) -> list[str]:
    """Apaga as *threads* paradas ha mais de `dias` e devolve as que apagou.

    **Tudo corre na `ligacao`, que e a do `kamba_batch`** — a descoberta e o
    apagamento. A primeira versao descobria com o `kamba_batch` e apagava pelo
    `adelete_thread` do checkpointer, que corre com o `kamba_agr`: o `GRANT
    DELETE ... TO kamba_batch` da revisao `0020` era privilegio **morto**, e o
    que o modulo e o `docs/agr.md` diziam era falso. Achado da revisao
    adversarial.

    E sincrona porque nao ha nada de assincrono a fazer: e uma varredura de
    lote, nao um turno. Quem a chamar de dentro de um `event loop` envolve-a
    num `asyncio.to_thread`, como o resto da casa.

    Devolve a lista em vez de um numero: quem chama regista o que apagou, e uma
    varredura que diz «apaguei 4» nao se audita. **Uma falha a meio nao perde a
    lista**: o que ja foi apagado esta confirmado e vai na excepcao.
    """
    if dias < 0:
        raise ValueError("os dias de inactividade nao podem ser negativos")
    limite = agora - _dt.timedelta(days=dias)
    cursor = ligacao.cursor()
    try:
        cursor.execute(consultas.SQL_THREADS_INACTIVAS, (limite,))
        candidatas = [linha[0] for linha in cursor.fetchall()]
    finally:
        cursor.close()
    ligacao.commit()

    apagadas: list[str] = []
    for thread_id in candidatas:
        cursor = ligacao.cursor()
        try:
            # Os checkpoints primeiro, e **so se a *thread* continuar parada**:
            # entre o `SELECT` de cima e este `DELETE` pode ter chegado uma
            # mensagem, e apagar o estado a meio de um turno nao se desfaz.
            cursor.execute(
                consultas.SQL_APAGAR_THREAD_PARADA, (thread_id, thread_id, limite)
            )
            levou = cursor.rowcount
            # As escritas orfas que a instrucao de cima deixou. Se ela nao
            # apagou nada — a *thread* acordou —, esta tambem nao apaga.
            cursor.execute(consultas.SQL_APAGAR_ESCRITAS_ORFAS, (thread_id,))
        finally:
            cursor.close()
        ligacao.commit()
        if levou:
            apagadas.append(thread_id)
    return apagadas
