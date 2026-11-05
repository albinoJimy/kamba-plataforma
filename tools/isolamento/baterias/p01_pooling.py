"""P-01 — cem transaccoes intercaladas de A e B pelo *pool* nao cruzam linhas.

Criterio 7 do KAM-066, primeira metade. A segunda metade — o *lint* que recusa
um `SET app.tenant_id` de sessao — esta em `tools/isolamento/lints.py`, e corre
antes desta: um `SET` de sessao e um defeito que se ve na fonte, e nao vale
levantar um PostgreSQL para descobrir o que um `grep` com regra diz.

## O que estas cem transaccoes medem que as outras baterias nao medem

O X-03 e o X-04 provam a politica **numa** transaccao. O que um *pool* em modo
transaccao faz de diferente e **reusar a ligacao**: a que serviu um pedido de A
serve a seguir um pedido de B, sem nada entre elas a limpar o estado da sessao.
Se o contexto for de sessao, ele sobrevive; se for de transaccao, morre no
`COMMIT`. A diferenca nao da erro — da as linhas do tenant errado, com a RLS
ligada e a parecer que protege.

A suite da base ja tinha uma bateria de cinquenta (`TestConcorrencia`), de
cinco ligacoes a alternar de tenant. O criterio escreve **cem**, e cumpre-se a
letra: dez ligacoes de dez voltas. A letra importa aqui mais do que noutros
sitios porque o defeito e de corrida — e uma corrida que nao aparece em
cinquenta tentativas pode aparecer em cem.

## Cada transaccao afirma as duas metades

Ve o seu canario (senao «nao viu o do outro» e verde por nao ver nada) e nao ve
o do outro. Uma volta que veja zero linhas e um achado, nao um salto.
"""

from __future__ import annotations

import threading

from ..casos import registar_caso

#: Dez ligacoes, dez voltas: as cem do criterio 7, e nao «cerca de cem». Um
#: criterio que escreve um numero cumpre-se com esse numero.
LIGACOES = 10
VOLTAS_POR_LIGACAO = 10
TRANSACCOES = LIGACOES * VOLTAS_POR_LIGACAO

#: A tabela onde se mede. `tenant_channels` e lida por `kamba_app`, tem uma
#: linha por tenant e o canario esta numa coluna de texto (`waba_id`).
CHAVE = ("platform", "tenant_channels")
COLUNA = "waba_id"


def _pooling(ctx) -> list[str]:  # noqa: ANN001
    if ctx.ligar is None:
        return ["P-01: o contexto nao traz `ligar`. Num gate, saltar e falhar."]

    import sys  # noqa: PLC0415
    from pathlib import Path  # noqa: PLC0415

    raiz = Path(__file__).resolve().parents[3]
    for relativo in ("libs/py-core/src",):
        caminho = str(raiz / relativo)
        if caminho not in sys.path:
            sys.path.insert(0, caminho)
    from kamba_core import tenant_guard  # noqa: PLC0415

    achados: list[str] = []
    feitas: list[int] = []
    trinco = threading.Lock()
    # A barreira existe para que as dez ligacoes estejam vivas **antes** da
    # primeira transaccao: sem ela, a primeira ligacao faz as suas dez voltas
    # antes de a decima abrir, e o ensaio mede dez sequencias em serie em vez de
    # dez intercaladas.
    barreira = threading.Barrier(LIGACOES)

    def trabalhar(indice: int) -> None:
        conexao = ctx.ligar("app")
        try:
            barreira.wait(timeout=30)
            for volta in range(VOLTAS_POR_LIGACAO):
                meu, outro = (
                    (ctx.a, ctx.b) if (indice + volta) % 2 == 0 else (ctx.b, ctx.a)
                )
                with tenant_guard.tx(conexao, meu.id) as cursor:
                    cursor.execute(f"SELECT {COLUNA} FROM {CHAVE[0]}.{CHAVE[1]}")
                    vistos = [linha[0] for linha in cursor.fetchall()]
                with trinco:
                    feitas.append(1)
                    esperado = [meu.canarios[CHAVE]]
                    if vistos != esperado:
                        cruzou = outro.canarios[CHAVE] in vistos
                        achados.append(
                            f"P-01 ligacao {indice}, volta {volta}: viu "
                            f"{len(vistos)} linha(s); a do outro tenant "
                            f"presente: {cruzou}. "
                            + (
                                "Uma linha do outro tenant na mesma ligacao e o "
                                "contexto a sobreviver a transaccao."
                                if cruzou
                                else "Zero linhas e a transaccao a correr sem "
                                "contexto: a volta nao mediu o que queria medir."
                            )
                        )
        except Exception as erro:  # noqa: BLE001 — qualquer falha conta
            with trinco:
                achados.append(
                    f"P-01 ligacao {indice}: {type(erro).__name__}: {erro}"
                )
        finally:
            conexao.close()

    fios = [threading.Thread(target=trabalhar, args=(i,)) for i in range(LIGACOES)]
    for fio in fios:
        fio.start()
    for fio in fios:
        fio.join(timeout=180)

    if sum(feitas) != TRANSACCOES:
        achados.append(
            f"P-01: correram {sum(feitas)} transaccoes e o criterio 7 pede "
            f"{TRANSACCOES}. Um ensaio de corrida com menos voltas do que as "
            "pedidas nao e o ensaio pedido."
        )
    return achados


registar_caso(
    id="P-01/pooling",
    bateria="P-01",
    camada="pool",
    fn=_pooling,
    precisa="postgres",
    origens=("corpo",),
)
