"""As tres listas fechadas da subscricao de eventos (KAM-038, dicionario §3.33).

Num modulo so, e **sem importar mais nada deste pacote**, por uma razao que o
`metricas.py` ja pagou duas vezes: os valores destas listas sao etiquetas, o
`metricas.py` deriva-as a primeira chamada, e um modulo que importasse o
despacho ou a notificacao fechava o triangulo
`metricas -> eventos.X -> metricas` e dava `partially initialized module` a quem
importasse pela ordem errada. Aqui so ha tuplos de texto.
"""

from __future__ import annotations

from typing import Final

#: O que aconteceu a uma entrega. Lista **fechada**: e etiqueta de
#: `agr_evt_consumidos_total`.
#:
#: `aplicado`          consumiu-se e o efeito correu
#: `duplicado`         ja havia linha em `events_consumed`: *no-op* (criterio 2)
#: `adiado`            a pre-condicao ainda nao se verifica; tenta-se outra vez
#: `para_dlq`          abriu-se entrada na DLQ e nao se volta a tentar
#: `entregue_ao_hnd`   a conversa esta com um humano; o evento **consome-se** e
#:                     o HND e notificado (criterio 5). Consome-se, e nao se
#:                     adia: repeti-lo seis vezes para dizer sempre o mesmo nao
#:                     e tentar outra vez — e a mesma leitura que o
#:                     `entregue_ao_hnd` do `DESFECHOS` do KAM-025 faz do turno
#:
#: Os dois primeiros sao os `DESFECHOS_DO_CONSUMO` de `kamba_core.eventos` e
#: **nao se renomeiam**: a transaccao e a mesma, e dar outro nome ao que ela
#: devolve era obrigar quem le um painel a saber que sao a mesma coisa.
#: `sem_entitlement`   nenhuma vertical que subscreve este tipo esta activa
#:                     para este *tenant*. **Nao e defeito do evento** e nao vai
#:                     a DLQ: o publicador entrega a configuracao de entrega, que
#:                     e global (`evt_subscricoes`, por *consumer* e nao por
#:                     *tenant*), e so o AGR sabe que modulos este *tenant* tem.
#:                     O nome e o `motivo` que o §3.26 ja deu ao
#:                     `agr_registry_denied_total`, e nao se inventa um segundo
#: `sem_accao`         o consumidor esta registado e a accao **desta vertical
#:                     para este tipo** nao esta escrita. O evento consome-se
#:                     (uma linha, para que o reconciliador pare) e o desfecho
#:                     diz, com credor nomeado, que ninguem foi notificado. Nao
#:                     e silencio: e um desfecho contado e registado, e e o que
#:                     impede a alternativa — um *handler* agnostico a vertical
#:                     a mandar a **mesma** mensagem duas vezes ao mesmo cliente
DESFECHOS_DO_EVENTO: Final = (
    "aplicado",
    "duplicado",
    "adiado",
    "para_dlq",
    "entregue_ao_hnd",
    "sem_entitlement",
    "sem_accao",
)

#: Porque e que uma entrada foi aberta na DLQ. Lista **fechada**: e etiqueta de
#: `agr_evt_dlq_total` **e** o valor que vai para `platform.events_dlq.erro`.
#:
#: `envelope_invalido`     o envelope nao se le (14 campos, formas, P2)
#: `tipo_desconhecido`     nenhuma vertical subscreve este tipo
#: `versao_desconhecida`   subscreve-se o tipo, nao esta versao (criterio 3)
#: `sem_template`          janela fechada e sem *template utility* aprovado
#: `tentativas_esgotadas`  as seis do §6.4 (1 + 5) acabaram
#:
#: **Quatro dos cinco nao esperam pelas seis tentativas**, e isso e desenho: um
#: envelope que nao se le, um tipo sem contrato, uma versao que nao existe e um
#: *template* que nao esta aprovado nao mudam entre tentativas, e gastar a
#: escada do §6.4 com eles adiava o alerta por treze minutos.
#:
#: **O `sem_template` e entrada na DLQ e nao um `aplicado`**, e isso e uma
#: correccao da revisao adversarial. A primeira versao contava-o e seguia: o
#: evento ficava marcado em `events_consumed` **sem** mensagem nenhuma, e no dia
#: em que o KAM-024 aprovasse os *templates* as re-entregas davam `duplicado` e
#: o cliente **nunca** era avisado. Com a entrada na DLQ, o que nao se enviou
#: fica visivel e **reprocessavel** — que e o unico desfecho honesto de «nao
#: envia e alerta» (criterio 6) sobre uma mensagem que ainda tem de sair.
#:
#: **O `fora_de_ordem` do KAM-006 NAO esta aqui, e nao e esquecimento.** Ele e
#: levantado pelo `consumir` quando o evento vem atrasado **e** a transicao nao
#: e valida — isto e, dentro da pre-condicao de estado, que este consumidor nao
#: corre: o AGR nao aplica transicao nenhuma (`aplica_transicao=False`,
#: dicionario §3.33). Declara-lo era uma etiqueta **sempre a zero**, que e a
#: licao que o `echo_latency_ms` do KAM-018 escreveu e que o `metricas.py` deste
#: servico repete: «uma metrica declarada e sempre a zero e pior do que uma
#: metrica ausente». No dia em que um consumidor do AGR aplique uma transicao,
#: o valor entra aqui **e** no dicionario, por emenda.
MOTIVOS_DA_DLQ: Final = (
    "envelope_invalido",
    "tipo_desconhecido",
    "versao_desconhecida",
    "sem_template",
    "tentativas_esgotadas",
)

#: Os cinco por nome, para que quem os usa nao escreva a cadeia a mao: uma
#: cadeia escrita duas vezes vai para uma coluna e para uma etiqueta, e divergem
#: no dia em que uma delas se corrija.
MOTIVO_ENVELOPE_INVALIDO: Final = "envelope_invalido"
MOTIVO_TIPO_DESCONHECIDO: Final = "tipo_desconhecido"
MOTIVO_VERSAO_DESCONHECIDA: Final = "versao_desconhecida"
MOTIVO_SEM_TEMPLATE: Final = "sem_template"
#: O unico motivo que, por definicao, **vem depois** das retentativas.
#:
#: **Nao ha uma lista dos outros, e isso e uma correccao.** A primeira versao
#: declarava um `MOTIVOS_SEM_RETENTATIVA` e um `e_definitivo()` para responder
#: «este motivo dispensa a escada?», e a revisao adversarial mediu que **nenhum
#: codigo de producao os consultava**: a propriedade e imposta pela estrutura
#: dos pontos de chamada — os quatro deterministicos sao escritos **so** de
#: caminhos que nao recuam, e o `tentativas_esgotadas` **so** de caminhos que
#: contaram as tentativas. Uma funcao que ninguem consulta a decidir uma coisa
#: que a estrutura ja decide era uma segunda fonte para a mesma regra, e a
#: mutacao que a apagava nao mudava comportamento nenhum.
MOTIVO_COM_RETENTATIVA: Final = "tentativas_esgotadas"

#: Os cinco nomes e a lista fechada **sao o mesmo conjunto**, e confronta-se no
#: carregamento do modulo. `raise` e nao `assert`: um `assert` desaparece com
#: `python -O`, e o que esta linha impede e um motivo declarado por nome que nao
#: esta na lista — isto e, uma coluna escrita com um valor que a metrica recusa.
if set(MOTIVOS_DA_DLQ) != {
    MOTIVO_ENVELOPE_INVALIDO,
    MOTIVO_TIPO_DESCONHECIDO,
    MOTIVO_VERSAO_DESCONHECIDA,
    MOTIVO_SEM_TEMPLATE,
    MOTIVO_COM_RETENTATIVA,
}:  # pragma: no cover — defeito de edicao deste ficheiro
    raise RuntimeError(
        "os cinco motivos por nome e `MOTIVOS_DA_DLQ` divergiram: um deles vai "
        "para `events_dlq.erro` e o outro e etiqueta de metrica"
    )


#: O desfecho de uma notificacao. Lista **fechada**: e etiqueta de
#: `agr_evt_notificacoes_total`.
#:
#: `livre`         janela aberta: mensagem livre (`service`)
#: `template`      janela fechada: *template utility* **aprovado**
#: `sem_template`  janela fechada e sem *template* aprovado: **nao se envia**, e
#:                 alerta-se (criterio 6). E um desfecho e nao um erro: e o
#:                 estado do sistema hoje, porque o catalogo de *templates* e o
#:                 KAM-024
#: `dono`          a notificacao foi ao **lado do negocio** — o dono (criterio 7)
#:                 ou o agente humano que tem a conversa (criterio 5) — e foi
#:                 pelo HND. Um valor para os dois, e nao dois, porque o que esta
#:                 metrica responde e «por onde saiu»: os dois saem pelo painel
#:                 ou pelo e-mail do Chatwoot e **nenhum** passa pelo Outbound,
#:                 que e a propriedade do criterio 7. Quem precisa de distinguir
#:                 o dono do agente le o `agr_evt_consumidos_total`, onde o
#:                 segundo caso e `entregue_ao_hnd`
#:
#: A decisao entre os tres primeiros e do **Outbound** (KAM-015, `01` §8.2) e
#: nao deste codigo: o que e daqui e nao haver caminho nenhum que mande texto
#: livre com a janela fechada.
DESFECHOS_DA_NOTIFICACAO: Final = ("livre", "template", "sem_template", "dono")

#: O desfecho que obriga a alerta. **Um e nao uma lista**, para que acrescentar
#: outro seja uma decisao e nao uma linha.
DESFECHO_QUE_ALERTA: Final = "sem_template"
