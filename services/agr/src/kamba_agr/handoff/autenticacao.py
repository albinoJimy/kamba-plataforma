"""A autenticacao de `/internal/resume` pelo `secret` do *agent bot* (criterio 4).

«Origem autenticada pelo `secret` do *agent bot* do HND; `secret` invalido
devolve 401 e incrementa metrica.»

## Duas credenciais na mesma rota, e provam coisas diferentes

A rota ja tinha uma: o `x-kamba-interno` do KAM-025, que prova «este pedido vem
de dentro da rede». Esta acrescenta a segunda, que prova «este pedido vem do
*agent bot* **deste tenant**». Nao sao redundantes e a diferenca mede-se: com
so a primeira, qualquer componente interno — o COM, o GWY, um *script* de
operacao — podia retomar o *handoff* de qualquer *tenant*; com so a segunda, o
segredo de um bot passava a valer de fora da rede. Pedem-se as duas, e a ordem
e a do custo: o `x-kamba-interno` nao precisa de saber de que *tenant* e o
pedido, e por isso decide-se primeiro.

**O segredo e por bot, logo por *tenant***, e e isso que obriga a resolve-lo
depois de se ler o corpo: o `tenant_id` sai do prefixo do `thread_id`
(`{tenant_id}:{contact_id}`, §3.1) e e ele que escolhe de quem e o segredo
esperado. E a mesma razao que o `hnd/assinatura.ts` escreveu para nao por esta
verificacao no GWY — «o GWY e o unico ponto que nao tem contexto de *tenant*
antes de resolver o canal».

## O que este modulo copia do `hnd/assinatura.ts`, e porque nao o importa

Copia tres decisoes, porque sao as mesmas e ja estao justificadas la: a
comparacao em tempo constante, o esperado vazio a devolver **falso** (uma
configuracao sem segredo nao se torna uma porta aberta), e os motivos de recusa
como lista fechada para servirem de etiqueta. Nao o importa porque e
TypeScript e isto e Python — a travessia nao existe. O que impede as duas de
divergirem e o nome dos motivos: `sem_secret` e `secret_errado` sao os mesmos
dois do §3.15, e ha um ensaio que o afirma contra o ficheiro do outro lado.

**E fica dito, como la: a propriedade de tempo constante nao tem ensaio.** Com
dois valores do mesmo comprimento, `compare_digest(a, b)` e `a == b` dao o
**mesmo** resultado para toda a entrada; a diferenca e o tempo, e o tempo nao e
observavel num teste de unidade. A mutacao que troca os dois sobreviveria a
tudo, e por isso nao se escreve uma a fingir que prova isto. O que o sustenta e
esta nota e a revisao.
"""

from __future__ import annotations

import hmac
from collections.abc import Callable
from typing import Final

#: O cabecalho que leva o `secret` do *agent bot*. Dicionario §3.32.
#:
#: Nome proprio e nao o `Authorization`: o `x-kamba-interno` ja ocupa o papel de
#: credencial de rede, e dois valores no mesmo cabecalho obrigavam a um esquema
#: de prefixos para os separar — mais superficie para o mesmo efeito.
CABECALHO_DO_BOT: Final = "x-kamba-hnd-bot"

#: Porque e que a retoma foi recusada. Lista **fechada**: e etiqueta de metrica,
#: e sao os dois primeiros `MOTIVOS_DE_RECUSA` do `hnd/assinatura.ts` (§3.15).
#:
#: Os outros dois de la — `tipo_desconhecido` e `conta_desconhecida` — **nao**
#: entram, e nao e por simetria incompleta: o `tipo` e do *callback* do Chatwoot,
#: que nunca chega a esta rota, e a conta e resolvida pelo HND antes de ele nos
#: chamar. Inventar aqui dois valores que nenhum caminho produz era declarar
#: etiquetas sempre a zero, que e o que o `metricas.py` recusa por escrito.
MOTIVOS_DE_RECUSA: Final = ("sem_secret", "secret_errado")


def tenant_do_thread(thread_id: str) -> str | None:
    """O `tenant_id` de um `thread_id`, ou `None` se ele nao tem a forma.

    O `thread_id` e `{tenant_id}:{contact_id}` (§3.1) e e **essa** a unica fonte
    do *tenant* nesta rota — o corpo nao tem campo de *tenant* e nao vai ter um,
    porque um `tenant_id` escrito por quem chama e um `tenant_id` que alguem
    pode trocar.

    Corta no **primeiro** `:` e nao faz `split(":")` com desempacotamento: um
    `thread_id` com tres partes levantava `ValueError` em vez de recusar, e o que
    a rota precisa e de uma recusa. Um prefixo vazio devolve `None` pela mesma
    razao — `":x"` nao e um *tenant*.
    """
    tenant, separador, _resto = thread_id.partition(":")
    if not separador or not tenant:
        return None
    return tenant


def avaliar(recebido: str | None, esperado: str) -> str | None:
    """`None` se o segredo confere; senao o motivo da recusa.

    `esperado` vazio recusa **sempre**, com `secret_errado`: se o cofre nao
    devolveu nada para este *tenant*, nenhum pedido passa. Falha fechada, que e
    a regra do `PreSendGuard` do KAM-015 e do `segredoConfere` do HND.

    A ordem e a do custo, como no `avaliar` do HND: o segredo em falta decide-se
    sem olhar ao esperado, pelo que um pedido sem cabecalho nunca chega a pedir
    nada ao cofre.
    """
    if not recebido:
        return "sem_secret"
    if not esperado:
        return "secret_errado"
    # O comprimento vaza, e e o unico facto que vaza: um segredo de outro
    # tamanho nao e «mais ou menos certo», e de outro bot. O `compare_digest`
    # trata-o por dentro, sem levantar como o `timingSafeEqual` do Node.
    if not hmac.compare_digest(recebido.encode("utf-8"), esperado.encode("utf-8")):
        return "secret_errado"
    return None


def verificador(
    segredo_do_bot: Callable[[str], str],
) -> Callable[[str | None, str], str | None]:
    """Fecha a porta do cofre num verificador `(recebido, thread_id) -> motivo`.

    `segredo_do_bot` e uma **funcao** e nao um dicionario, pela razao da
    `credencial` do `api_interna.py`: o segredo roda
    (`ops/secrets-inventory.yaml`, `chatwoot_bot_secret`, `rotacao_dias: 182`) e
    um valor lido uma vez no arranque ficava a recusar pedidos legitimos depois
    da rotacao. Quem a liga ao cofre e o `__main__.py`.

    **Uma falha do cofre e uma recusa e nao um 500.** Se a referencia nao existe
    — um *tenant* sem conta de atendimento provisionada — o `get` levanta, e o
    que se quer e `secret_errado`: a rota responde 401, o HND nao repete, e a
    metrica mostra-o. Um 500 punha o *webhook* a repetir contra um *tenant* que
    nunca vai ter segredo.
    """

    def verificar(recebido: str | None, thread_id: str) -> str | None:
        if not recebido:
            return "sem_secret"
        tenant = tenant_do_thread(thread_id)
        if tenant is None:
            return "secret_errado"
        try:
            esperado = segredo_do_bot(tenant)
        except Exception:  # noqa: BLE001 — ver docstring: recusa, nao 500
            return "secret_errado"
        return avaliar(recebido, esperado)

    return verificar
