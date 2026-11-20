"""A conversa do modulo social no grafo do dono (KAM-121): perfil, ideias e legendas.

Corre no no `confirm` do dono, como a do catalogo (aresta 38, intencao
`social`): **deterministica, sem modelo**, e com o texto pronto
(`_resposta_estatica`). Cada passo vai a ToolLayer pelos oito passos do §6.1 —
o entitlement `social` no passo 2, a `tool_audit` no 7 —, e nenhum argumento de
tool sai de um modelo de linguagem.

## O que decide o que este turno e

| Entrada | Accao |
|---|---|
| botao `tom:{tom}` | grava o tom do perfil |
| botao `social:ideias`, ou «ideias», «calendario» | o calendario da semana (`generate_calendar`); sem perfil completo, a proxima pergunta |
| botao `social:nova`, ou «NOVA» sozinho | outro calendario para a mesma semana |
| botao `legenda:SOC-…`, ou uma referencia `SOC-…` no texto | a legenda do item; o resto do texto e a instrucao do dono |
| «publica no Instagram», e afins | diz que nao publica, e o que faz |
| «perfil», «marca» | o perfil, e a proxima pergunta se faltar alguma |
| texto, com o perfil a meio | a resposta a pergunta em aberto |

## Os numeros do texto sao os da tool

As horas do calendario e a legenda levam digitos e nao passam pelo validador
(aresta 34). **Cada digito vem do resultado da tool deste turno**: as horas sao
calculadas por codigo (`regras.agenda`), e os numeros de uma legenda passaram a
guarda de numeros contra os factos do dono. Os textos fixos deste modulo nao
tem digitos (ensaio).
"""

from __future__ import annotations

import datetime
from collections.abc import Mapping
from typing import Any, Final

from ...social import regras
from ...tls.erros import ENTITLEMENT_DENIED, LIMIT_EXCEEDED, NOT_FOUND, TOOL_NOT_ALLOWED, UPSTREAM_DOWN, VALIDATION_ERROR
from ..vendedor.nos import Dependencias, _invocar, _resposta_estatica, _texto_do_cliente

#: As palavras que fazem o turno ser deste modulo. Sem acentos, e **antes** das
#: do catalogo no `classify`: «publica no instagram» nao e um produto.
PALAVRAS_DO_SOCIAL: Final = (
    "ideias",
    "calendario",
    "legenda",
    "perfil de marca",
    "perfil da marca",
    "redes sociais",
    "instagram",
    "facebook",
    "tiktok",
    "publicacoes",
)

#: As que pedem uma publicacao que o modulo nao faz (criterio 7, D13).
PALAVRAS_DE_PUBLICAR: Final = ("publica", "publique", "posta ", "postar", "partilha", "agenda no", "envia para")

#: As que pedem o calendario.
PALAVRAS_DO_CALENDARIO: Final = ("ideias", "calendario")


def _botao(estado: Mapping[str, Any]) -> str:
    if estado.get("input_kind") != "interactive":
        return ""
    botao = estado.get("botao")
    return botao if isinstance(botao, str) else ""


def e_do_social(estado: Mapping[str, Any], texto: str) -> bool:
    """Se o turno e do social **sem ler a base**: um botao dele, um `SOC-…`, «NOVA», ou as palavras."""
    if regras.ler_botao(_botao(estado)) is not None:
        return True
    if regras.REFERENCIA_NO_TEXTO.search(texto):
        return True
    limpo = regras.sem_acentos(texto).strip(" .!")
    if limpo == "nova":
        return True
    return any(p in limpo for p in PALAVRAS_DO_SOCIAL)


async def perfil_a_meio(deps: Dependencias, estado: Mapping[str, Any]) -> bool:
    """Se o dono esta a meio do perfil: existe e falta-lhe alguma resposta.

    Uma tool que falha, ou um tenant sem o modulo, diz que nao.
    """
    try:
        lido = await _invocar(deps, estado, "get_brand_profile", {})
    except Exception:  # noqa: BLE001 — uma leitura que falha nao rebenta o turno
        return False
    return bool(getattr(lido, "ok", False) and lido.data.get("existe") and not lido.data.get("completo"))


# ------------------------------------------------------------------ o no


async def tratar(deps: Dependencias, estado: Mapping[str, Any]) -> dict[str, Any]:
    """O turno do social. Devolve sempre uma resposta pronta."""
    toque = regras.ler_botao(_botao(estado))
    if toque is not None:
        if toque.accao == "tom":
            return await _responder(deps, estado, "tom", toque.valor)
        if toque.accao == "legenda":
            return await _legenda(deps, estado, toque.valor, None)
        return await _calendario(deps, estado, nova=toque.accao == "nova")
    texto = _texto_do_cliente(estado)
    referencia, resto = regras.referencia_no_texto(texto)
    if referencia is not None:
        return await _legenda(deps, estado, referencia, resto or None)
    limpo = regras.sem_acentos(texto).strip(" .!")
    if limpo == "nova":
        return await _calendario(deps, estado, nova=True)
    if any(p in limpo for p in PALAVRAS_DE_PUBLICAR):
        resposta = _resposta_estatica(MSG_NAO_PUBLICO)
        resposta["draft"]["botoes"] = (regras.BOTAO_IDEIAS,)
        return resposta
    if any(p in limpo for p in PALAVRAS_DO_CALENDARIO):
        return await _calendario(deps, estado, nova=False)
    lido = await _invocar(deps, estado, "get_brand_profile", {})
    if not lido.ok:
        return _resposta_estatica(_frase_do_erro(lido.error))
    proxima = lido.data.get("proxima")
    if any(p in limpo for p in PALAVRAS_DO_SOCIAL) or not lido.data.get("existe"):
        # Um pedido sobre o perfil ou as redes, sem resposta a dar: o perfil
        # (comecado, se nao existia) e a proxima pergunta, ou o convite.
        if proxima is None:
            resposta = _resposta_estatica(MSG_PERFIL_COMPLETO)
            resposta["draft"]["botoes"] = (regras.BOTAO_IDEIAS,)
            return resposta
        return await _comecar(deps, estado)
    if proxima is None:
        resposta = _resposta_estatica(MSG_PERFIL_COMPLETO)
        resposta["draft"]["botoes"] = (regras.BOTAO_IDEIAS,)
        return resposta
    return await _responder(deps, estado, str(proxima["campo"]), texto)


async def _comecar(deps: Dependencias, estado: Mapping[str, Any], *, antes: str = "") -> dict[str, Any]:
    """Comeca (ou retoma) o perfil e faz a proxima pergunta."""
    comecado = await _invocar(deps, estado, "update_brand_profile", {})
    if not comecado.ok:
        return _resposta_estatica(_frase_do_erro(comecado.error))
    return _pergunta(comecado.data, antes or MSG_COMECAR)


def _pergunta(dados: Mapping[str, Any], antes: str | None = None) -> dict[str, Any]:
    proxima = dados.get("proxima")
    if proxima is None:
        resposta = _resposta_estatica("\n".join(x for x in (antes, MSG_PERFIL_COMPLETO) if x))
        resposta["draft"]["botoes"] = (regras.BOTAO_IDEIAS,)
        return resposta
    resposta = _resposta_estatica("\n".join(x for x in (antes, str(proxima["texto"])) if x))
    botoes = tuple(proxima.get("botoes") or ())
    if botoes:
        resposta["draft"]["botoes"] = botoes
    return resposta


async def _responder(deps: Dependencias, estado: Mapping[str, Any], campo: str, texto: str) -> dict[str, Any]:
    gravado = await _invocar(deps, estado, "update_brand_profile", {"campo": campo, "resposta": texto[:1500]})
    if not gravado.ok:
        erro = gravado.error
        if getattr(erro, "codigo", "") == VALIDATION_ERROR:
            # A resposta nao tinha a forma: a mesma pergunta, com a razao.
            lido = await _invocar(deps, estado, "get_brand_profile", {})
            razao = FRASE_DA_RECUSA.get(getattr(erro, "detalhe", ""), MSG_RESPOSTA_RECUSADA)
            if lido.ok:
                return _pergunta(lido.data, razao)
            return _resposta_estatica(razao)
        return _resposta_estatica(_frase_do_erro(erro))
    return _pergunta(gravado.data, MSG_GUARDADO)


async def _calendario(deps: Dependencias, estado: Mapping[str, Any], *, nova: bool) -> dict[str, Any]:
    gerado = await _invocar(deps, estado, "generate_calendar", {"nova": nova})
    if not gerado.ok:
        erro = gerado.error
        if getattr(erro, "detalhe", "") == "perfil_incompleto":
            return await _comecar(deps, estado, antes=MSG_PERFIL_PRIMEIRO)
        return _resposta_estatica(_frase_do_erro(erro))
    dados = gerado.data
    itens = list(dados.get("itens") or ())
    if not itens:
        return _resposta_estatica(MSG_SEM_IDEIAS)
    linhas = [MSG_IDEIAS]
    for item in itens:
        instante = datetime.datetime.fromisoformat(str(item["agendado_at"]))
        linha = f"{item['referencia']} — {regras.quando(instante)} — {TITULO_DO_TIPO.get(item['tipo'], '')}: {item['tema']}"
        if item.get("revisao_reforcada"):
            linha += f" ({MSG_REVISAO_REFORCADA})"
        linhas.append(linha)
    linhas.append(MSG_COMO_LEGENDAR)
    resposta = _resposta_estatica("\n".join(linhas))
    resposta["draft"]["botoes"] = (
        *(regras.botao_da_legenda(str(i["referencia"])) for i in itens[:2]),
        regras.BOTAO_NOVA,
    )
    return resposta


async def _legenda(deps: Dependencias, estado: Mapping[str, Any], referencia: str, instrucao: str | None) -> dict[str, Any]:
    argumentos: dict[str, Any] = {"referencia": referencia}
    if instrucao:
        argumentos["instrucao"] = instrucao[:300]
    gerada = await _invocar(deps, estado, "generate_caption", argumentos)
    if not gerada.ok:
        return _resposta_estatica(_frase_do_erro(gerada.error))
    dados = gerada.data
    linhas = [MSG_LEGENDA, str(dados["legenda"]), MSG_LEGENDA_RASCUNHO]
    if dados.get("revisao_reforcada"):
        linhas.append(MSG_REVISAO_REFORCADA_LONGA)
    return _resposta_estatica("\n".join(linhas))


def _frase_do_erro(erro: Any) -> str:
    codigo, detalhe = getattr(erro, "codigo", ""), getattr(erro, "detalhe", "")
    if codigo in (TOOL_NOT_ALLOWED, ENTITLEMENT_DENIED):
        return MSG_SOCIAL_INACTIVO
    if codigo == NOT_FOUND:
        return MSG_REFERENCIA_DESCONHECIDA
    if codigo == LIMIT_EXCEEDED:
        return MSG_SEM_PUBLICACOES
    if codigo == UPSTREAM_DOWN and detalhe == "legendas_por_ligar":
        return MSG_LEGENDAS_POR_LIGAR
    return FRASE_DA_RECUSA.get(detalhe, MSG_NAO_CONSEGUI)


# ------------------------------------------------------------------ as frases
# **Sem digitos**, todas: vao ao `send` sem passar pelo validador (aresta 34).

MSG_COMECAR: Final = "Vamos conhecer a sua marca. Sao poucas perguntas, uma de cada vez."
MSG_PERFIL_PRIMEIRO: Final = "Antes das ideias, preciso de conhecer a sua marca."
MSG_GUARDADO: Final = "Guardado."
MSG_PERFIL_COMPLETO: Final = (
    "O perfil da marca esta completo. Escreva IDEIAS para receber as ideias da proxima semana."
)
MSG_RESPOSTA_RECUSADA: Final = "Nao percebi a resposta."
MSG_IDEIAS: Final = "Ideias para a proxima semana (sao rascunhos; o senhor publica quando quiser):"
MSG_COMO_LEGENDAR: Final = (
    "Para a legenda de uma ideia, toque no botao ou escreva a referencia SOC. Para outras ideias, escreva NOVA."
)
MSG_SEM_IDEIAS: Final = (
    "Nao posso preparar conteudo para esta loja. Se achar que e engano, fale com a nossa equipa."
)
MSG_REVISAO_REFORCADA: Final = "revisao reforcada"
MSG_REVISAO_REFORCADA_LONGA: Final = (
    "Este conteudo fica em revisao reforcada: antes de o usar, vai precisar de uma confirmacao a mais."
)
MSG_LEGENDA: Final = "Proposta de legenda:"
MSG_LEGENDA_RASCUNHO: Final = (
    "E um rascunho gerado por inteligencia artificial. Eu nao publico nada: reveja e publique o senhor."
)
MSG_NAO_PUBLICO: Final = (
    "Eu nao publico nas redes sociais: preparo ideias e legendas em rascunho, e o senhor publica. "
    "Quer ver as ideias da proxima semana?"
)
MSG_SOCIAL_INACTIVO: Final = "O modulo das redes sociais nao esta activo para a sua loja."
MSG_REFERENCIA_DESCONHECIDA: Final = "Nao encontrei essa ideia. Confira a referencia SOC."
MSG_SEM_PUBLICACOES: Final = "A loja ja usou as legendas do plano deste mes."
MSG_LEGENDAS_POR_LIGAR: Final = (
    "As legendas ainda nao estao disponiveis por aqui. As ideias da semana ja estao, e pode escrever "
    "a legenda a partir do tema."
)
MSG_NAO_CONSEGUI: Final = "Nao consegui tratar esse pedido das redes sociais agora. Tente outra vez daqui a pouco."

#: O tipo de um item, no texto ao dono.
TITULO_DO_TIPO: Final = {
    "produto": "Produto",
    "dica": "Dica",
    "bastidores": "Bastidores",
    "promocao": "Promocao",
}

#: Os codigos de recusa das tools -> a frase. Sem digitos.
FRASE_DA_RECUSA: Final = {
    "nome_fora_da_forma": "O nome da marca deve ter entre duas e sessenta letras.",
    "categoria_fora_da_forma": "Diga o que vende em poucas palavras.",
    "publico_fora_da_forma": "Diga para quem sao as publicacoes em poucas palavras.",
    "tom_fora_da_lista": "Escolha um dos tres tons nos botoes.",
    "cores_fora_da_forma": "Escreva as cores em codigo hexadecimal, como #FFAACC, ou escreva nenhuma.",
    "cores_a_mais": "Sao no maximo tres cores.",
    "slots_vazios": "Diga pelo menos um dia e uma hora.",
    "slot_sem_dia": "Cada hora precisa do dia da semana.",
    "slot_sem_hora": "Falta a hora.",
    "slots_a_mais": "Sao no maximo sete dias e horas por semana.",
    "factos_vazios": "Escreva um facto por linha, ou nenhum.",
    "factos_a_mais": "Sao no maximo dez factos.",
    "facto_fora_da_forma": "Cada facto deve ser uma frase curta.",
    "promocao_sem_validade": (
        "Uma promocao precisa da data em que acaba, por exemplo: desconto ate ao fim do mes, com a data."
    ),
    "perfil_incompleto": MSG_PERFIL_PRIMEIRO,
    "item_fechado": "Essa ideia ja nao esta em rascunho.",
    "faltam_factos": (
        "Para por precos, descontos, datas ou contactos na legenda, escreva-os primeiro como factos do "
        "perfil, com a data em que a promocao acaba. Nao invento valores."
    ),
    "alegacao": (
        "Nao posso escrever essa legenda: tinha uma promessa que a loja nao pode garantir (cura, "
        "garantia total, o melhor de todos, comparacoes ou selos que nao me deu)."
    ),
    "pt_br": "Nao consegui uma legenda em portugues de Angola desta vez. Peca outra vez.",
    "fora_da_forma": "Nao consegui uma legenda com o tamanho certo. Peca outra vez.",
    "categoria_bloqueada": "Nao posso preparar essa legenda para esta loja. Se achar que e engano, fale com a nossa equipa.",
    "screening_indisponivel": MSG_NAO_CONSEGUI,
    "politica_indisponivel": MSG_NAO_CONSEGUI,
    "gerador_indisponivel": MSG_NAO_CONSEGUI,
    "perfil_mudou": MSG_NAO_CONSEGUI,
    "item_mudou": MSG_NAO_CONSEGUI,
}
