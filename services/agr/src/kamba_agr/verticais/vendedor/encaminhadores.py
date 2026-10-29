"""Os encaminhadores do §7.4 — e todos sao funcoes puras do estado.

**Sao treze entradas no `POR_NO` e doze funcoes**, porque o `r_upstream` serve
dois nos. O cabecalho dizia «os dez encaminhadores … e os dez sao funcoes puras»,
o que era verdade no KAM-031 e deixou de ser com o KAM-114 (o `r_send` e o
`r_draft`); a contagem fica agora na lista do fim, que e onde se pode medir, e
nao numa frase que ninguem confronta. Apanhado pela revisao adversarial (C12).

## Puras, e porque e que isso e a propriedade que importa

Um encaminhador que pergunte algo ao mundo pergunta-o **depois** de o no ja ter
perguntado, e o §7.3 nao tem sitio para duas respostas diferentes no mesmo
turno. Pior: a fonte do ritmo (o `aceita_o_ritmo` do KAM-025) **registra a
chegada** numa janela deslizante — perguntar-lhe duas vezes gastava duas vagas
das vinte por minuto e cortava o tecto a metade, sem nada no resultado o
denunciar. Por isso o no decide e escreve, e o encaminhador le.

A consequencia pratica e que a tabela de decisao de cada um se mede com um
`dict`, sem grafo, sem base e sem tools — e e o que o criterio «teste de cada
router (tabela de decisao)» pede.

## Todos caem para o lado seguro

Cada um tem um ramo de omissao, e nenhum deles e «segue em frente»:

* um `veredicto` de guarda que nao esteja nos seis vai a `safe_reply`;
* uma `intent` que nao esteja nas nove vai a `safe_reply` (chave `other`);
* uma `intent` que o modo deterministico nao serve vai ao menu, nunca em frente;
* um `stt` ilegivel vai a `ask_repeat`;
* um `validate` sem veredicto conta como falha.

E a mesma regra do `do_humano` do `turno.py`: lista de permitidos e nao de
proibidos, porque um valor novo no dominio fecha a porta por omissao.
"""

from __future__ import annotations

from typing import Any, Final

from ...concierge.maquina import DECISOES_QUE_ENVIAM
from ...tls.erros import UPSTREAM_DOWN, UPSTREAM_TIMEOUT
from .arestas import INTENCOES, STALE_CONFIRMATION, VEREDICTOS_DE_GUARDA
from .degradado import intencoes

#: Os codigos que mandam o turno ao *handoff* pelas arestas 22 e 26.
CODIGOS_DE_UPSTREAM: Final = (UPSTREAM_TIMEOUT, UPSTREAM_DOWN)

#: A chave do `path_map` de `classify` para cada uma das nove intencoes
#: (§7.3 linhas 11 a 17).
CHAVE_DA_INTENCAO: Final = {
    "produto": "search",
    "preco_stock": "search",
    "comprar": "buy",
    "confirmar": "confirm",
    "pagamento_estado": "status",
    "encomenda": "status",
    "info_loja": "info",
    "humano": "human",
    "outro": "other",
}

#: A chave do `path_map` de `guard_in` para cada veredicto (§7.3 linhas 8 a 10).
CHAVE_DO_VEREDICTO: Final = {
    "ok": "ok",
    "injection": "safe",
    "abuse": "safe",
    "out_of_domain": "safe",
    "card_data": "safe",
    "sensitive": "human",
}

#: O tecto de repeticoes de citacao (§7.3 linha 30; dicionario §3.31).
TECTO_DE_CITACAO: Final = 1

#: Os niveis de confianca do STT. **Proposta**, e o §10 di-lo por extenso —
#: «limiares iniciais herdados do Whisper de referencia (INDICIO), a calibrar com
#: audio PT-AO». Quem os calibra e o KAM-036; aqui estao para que o ramo exista e
#: se possa medir, e nao para fingir que estao decididos.
CONFIANCA_ALTA: Final = 0.7
CONFIANCA_MEDIA: Final = 0.4

#: A lingua que o §10 aceita sem *handoff*.
IDIOMA_SUPORTADO: Final = "pt"


def r_ingest(estado: dict[str, Any]) -> str:
    """Linhas 2, 3 e 4: audio, texto/botao/localizacao, ou fim silencioso."""
    if estado.get("admissao") is not None:
        return "end"
    return "stt" if estado.get("input_kind") == "audio" else "guard_in"


def r_stt(estado: dict[str, Any]) -> str:
    """Linhas 5, 6 e 7 — e a omissao e `repeat`, nao `ok`.

    O §14 escreve «STT indisponivel -> `ask_repeat` pedindo texto», e um `stt`
    ausente ou ilegivel e isso: nao se segue para o `guard_in` com um texto que
    ninguem transcreveu.
    """
    stt = estado.get("stt")
    if not isinstance(stt, dict):
        return "repeat"
    if stt.get("idioma") not in (None, IDIOMA_SUPORTADO):
        return "human"
    if stt.get("excedeu_duracao"):
        return "human"
    confianca = stt.get("confianca")
    if not isinstance(confianca, (int, float)):
        return "repeat"
    if confianca >= CONFIANCA_ALTA:
        return "ok"
    if confianca >= CONFIANCA_MEDIA:
        return "repeat"
    return "human"


def r_guard(estado: dict[str, Any]) -> str:
    """Linhas 8, 9 e 10, pelo veredicto da guarda de entrada."""
    guarda = estado.get("guard")
    veredicto = guarda.get("veredicto") if isinstance(guarda, dict) else None
    if veredicto not in VEREDICTOS_DE_GUARDA:
        # Um veredicto fora dos seis **nao** segue para o `classify`: e a regra
        # do `fail-closed` do §8.4, e o unico caminho que nao arrisca nada e o
        # texto estatico.
        return "safe"
    return CHAVE_DO_VEREDICTO[veredicto]


def r_intent(estado: dict[str, Any]) -> str:
    """Linhas 11 a 17 pelas nove intencoes, e a 44 em modo degradado (KAM-037).

    **A degradacao decide-se antes da intencao, e nao em vez dela.** Um turno
    degradado continua a ter intencao — e por ela que se sabe se ha no de
    trabalho — e o que muda e o destino de quem **nao** tem: em modo normal uma
    intencao de catalogo vai ao `retrieve`, e em modo degradado vai ao
    `degraded_menu`.

    As cinco intencoes que o modo serve (`intencoes.SERVIDAS`) tomam as linhas
    13 a 16 do §7.3 como qualquer outro turno — o `confirm_gate`, o
    `order_status`, o `tools_info` e o `handoff_prepare` nao sabem que estao a
    correr degradados, e nao precisam de saber. E o que «reutiliza o grafo
    normal» quer dizer na pratica.

    **A omissao continua a ser `other` e nao `menu`**, e a assimetria tem razao:
    um `intent` fora das nove e um estado que ninguem escreveu de proposito, e o
    `safe_reply` e o unico caminho que nao arrisca nada. Degradado ou nao, um
    valor desconhecido nao escolhe o caminho novo.
    """
    intencao = estado.get("intent")
    if intencao not in INTENCOES:
        return "other"
    if estado.get("degradado") and not intencoes.serve(intencao):
        return "menu"
    return CHAVE_DA_INTENCAO[intencao]


def r_hits(estado: dict[str, Any]) -> str:
    """Linhas 18 e 19: ha oferta acima do limiar, ou nao ha.

    **Le as `ofertas` e nao um `score`**, porque e o `retrieve` que compara com o
    limiar — e ele que tem o parametro. Uma oferta na lista significa «passou o
    limiar»; a lista vazia significa «nenhuma passou», que e o mesmo caminho de
    «a pesquisa nao devolveu nada».
    """
    return "hit" if estado.get("ofertas") else "miss"


def r_upstream(estado: dict[str, Any]) -> str:
    """Linhas 22 e 26, partilhado pelo `cart_build` e pelo `create_order`.

    E **um** encaminhador para os dois nos, como o §7.4 escreve: a condicao e a
    mesma (`UPSTREAM_*` apos retry) e duplica-la era deixar os dois divergirem.
    """
    avisos = estado.get("avisos") or ()
    return "down" if any(a in CODIGOS_DE_UPSTREAM for a in avisos) else "ok"


def r_confirm(estado: dict[str, Any]) -> str:
    """Linhas 23 e 24, pelo aviso que o `confirm_gate` escreveu.

    **Le o aviso e nao repete as tres perguntas do criterio 4.** Repeti-las aqui
    era avaliar o carrinho duas vezes contra um relogio que andou entre as duas,
    e com um `expira_at` a passar no meio das duas o grafo criava uma encomenda
    que o no tinha recusado.
    """
    avisos = estado.get("avisos") or ()
    return "stale" if STALE_CONFIRMATION in avisos else "go"


def r_cite(estado: dict[str, Any]) -> str:
    """Linhas 29, 30 e 31: ok, repetir uma vez, ou *handoff*.

    O `citation_retries` que se le **ja foi incrementado** pelo `validate`: na
    primeira falha vale 1, `1 <= 1` e verdade e repete-se; na segunda vale 2 e
    vai a *handoff*. O §7.3 escreve as condicoes em funcao do valor **antes** do
    incremento («falha e `citation_retries < 1`») e as duas leituras dao o mesmo
    ramo — esta e a que nao obriga o no a guardar o valor antigo.
    """
    rascunho = estado.get("draft")
    if isinstance(rascunho, dict) and rascunho.get("ok"):
        return "ok"
    repeticoes = estado.get("citation_retries") or 0
    return "retry" if repeticoes <= TECTO_DE_CITACAO else "human"


def r_out(estado: dict[str, Any]) -> str:
    """Linhas 32 e 33, pela guarda de saida escrita no rascunho."""
    rascunho = estado.get("draft")
    if not isinstance(rascunho, dict):
        return "safe"
    return "safe" if rascunho.get("violacao") else "ok"


def r_handoff(estado: dict[str, Any]) -> str:
    """Linhas 36 e 37: espera por humano, ou mensagem de degradacao.

    O estado `degraded` e o do §11 (`HandoffUnavailable`), e a omissao e
    `degraded` e nao `wait`: sem `handoff` no estado nao ha `handoff_id` para o
    `interrupt` citar, e um `interrupt` sem referencia e uma conversa que fica
    presa a espera de uma retoma que ninguem pode mandar.
    """
    handoff = estado.get("handoff")
    if not isinstance(handoff, dict):
        return "degraded"
    return "wait" if handoff.get("status") == "waiting" else "degraded"


def r_send(estado: dict[str, Any]) -> str:
    """Linhas 35 e 40: enviado, ou a caminho da aprovacao humana (KAM-114).

    **A omissao e `enviado` e nao `aprovar`**, e isso e deliberado: sem
    `concierge` no estado — que e o caso de todos os *tenants* fora do Piloto —
    o turno acaba como o KAM-031 o entregou. Encaminhar por omissao para a
    aprovacao punha **toda** a plataforma a espera de um operador que nao
    existe.

    A barreira do criterio 1 nao esta aqui: esta no `send`, que e quem decide
    nao enfileirar. Este encaminhador le o que ele decidiu — `a_aprovar` — e nao
    repete a leitura da politica, que e I/O e ja foi feita uma vez neste turno.
    """
    concierge = estado.get("concierge")
    if not isinstance(concierge, dict):
        return "enviado"
    return "aprovar" if concierge.get("estado") == "a_aprovar" else "enviado"


def r_draft(estado: dict[str, Any]) -> str:
    """Linhas 42 e 43: a decisao manda enviar, ou acaba o turno (KAM-114).

    **A omissao e `end`**, ao contrario do `r_send`, e e a direccao segura: uma
    retoma com um corpo que esta classe nao entende **nao** faz sair uma
    mensagem. E a barreira do criterio 1 outra vez, e aqui ela e a omissao.
    """
    concierge = estado.get("concierge")
    if not isinstance(concierge, dict):
        return "end"
    return "enviar" if concierge.get("decisao") in DECISOES_QUE_ENVIAM else "end"


#: Os encaminhadores pelo no que os usa. E o que o `grafo.py` percorre, e e
#: tambem o que torna «um no condicional sem encaminhador» impossivel de
#: escrever: o `build_graph` levanta se a tabela de arestas tiver um no
#: condicional que nao esteja aqui.
POR_NO: Final = {
    "ingest": r_ingest,
    "stt": r_stt,
    "guard_in": r_guard,
    "classify": r_intent,
    "retrieve": r_hits,
    "cart_build": r_upstream,
    "confirm_gate": r_confirm,
    "create_order": r_upstream,
    "validate": r_cite,
    "guard_out": r_out,
    "handoff_prepare": r_handoff,
    # KAM-114.
    "send": r_send,
    "draft_wait": r_draft,
}
