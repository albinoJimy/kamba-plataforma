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
| botao `arte:SOC-…`, ou «ARTE SOC-…» («OUTRA ARTE SOC-…» regera) | a arte e o pedido de aprovacao, com Aprovar, Editar e Rejeitar (KAM-122) |
| botao `editar:SOC-…` | diz como mandar a legenda nova; «EDITAR SOC-…: texto» e a edicao |
| botao `rejeitar:SOC-…`, ou «REJEITAR SOC-…» | rejeita o item |
| botao `enviar:SOC-…`, ou «ENVIAR SOC-…» | a entrega ao dono de um item aprovado |
| botao `legenda:SOC-…`, ou uma referencia `SOC-…` no texto | a legenda do item; o resto do texto e a instrucao do dono |
| «FACTOS: …», «DIAS: …», e os outros campos | grava esse campo, a qualquer altura |
| um verbo de publicar **e** uma rede («publica no Instagram») | diz que nao publica, e o que faz |
| botao `social:ideias`, ou so «IDEIAS» | o calendario da semana (`generate_calendar`); sem perfil completo, a proxima pergunta |
| botao `social:nova`, ou so «NOVA» | outro calendario para a mesma semana |
| texto, com o perfil a meio | a resposta a pergunta em aberto |
| «ideias», «calendario», as redes, sem perfil a meio | o calendario, o comeco do perfil, ou o convite |

## A aprovacao e o botao `confirm:{action_id}`

O Aprovar **nao** e um botao deste modulo: e o `confirm:{action_id}` da accao
`aprovar_conteudo` que o `request_approval` propoe (decisao D4 do fundador,
2026-11-21). Chega ao no `confirm` pela intencao `confirmar`, e o `aprovar`
deste modulo corre o `approve_content` com a `Confirmation` desse turno.

## Os numeros do texto sao os da tool

As horas do calendario e a legenda levam digitos e nao passam pelo validador
(aresta 34). **Cada digito vem do resultado da tool deste turno**: as horas sao
calculadas por codigo (`regras.agenda`), e os numeros de uma legenda passaram a
guarda de numeros contra os factos do dono. Os textos fixos deste modulo nao
tem digitos (ensaio).
"""

from __future__ import annotations

import datetime
import re
from collections.abc import Mapping
from typing import Any, Final

from ...social import regras
from ...tls.erros import (
    ENTITLEMENT_DENIED,
    LIMIT_EXCEEDED,
    NOT_FOUND,
    TOOL_NOT_ALLOWED,
    UPSTREAM_DOWN,
    UPSTREAM_TIMEOUT,
    VALIDATION_ERROR,
)
from ...tls.contexto import Confirmation
from ..vendedor.nos import Dependencias, _invocar, _resposta_estatica, _texto_do_cliente

#: As palavras das redes que levam um texto livre a este modulo, pelas regras do
#: `classify` (**depois** do humano, da informacao da loja e do orcamento, e
#: antes do catalogo: «publica no instagram» nao e um produto). Por palavra.
PALAVRAS_DO_SOCIAL: Final = re.compile(
    r"\b(?:ideias|calendario|legendas?|perfil d[ae] marca|redes sociais|instagram|facebook|tiktok)\b"
)

#: Um pedido de publicacao que o modulo nao faz (criterio 7, D13): o verbo **e**
#: a rede. So o verbo nao chega — «prefiro publicar segunda as 18h» e a resposta
#: a pergunta dos dias (achado I6 da revisao adversarial).
_VERBO_DE_PUBLICAR: Final = re.compile(r"\b(?:publica|publique|publicar|publicas|posta|postar|partilha|partilhar|agenda)\b")
_REDE: Final = re.compile(r"\b(?:instagram|facebook|tiktok|redes sociais|rede social|status|estado do whatsapp)\b")

#: Os comandos de um item (KAM-122): a palavra, a referencia e, no EDITAR, o texto.
_COMANDO_DO_ITEM: Final = re.compile(
    r"\A\s*(outra arte|arte|editar|enviar|rejeitar)\s+(SOC-[A-HJ-NP-R]{8})\b\s*:?\s*(.*)\Z",
    re.DOTALL | re.IGNORECASE,
)


def comando_do_item(texto: str) -> tuple[str, str, str] | None:
    """`(comando, referencia, resto)` de «ARTE SOC-…», «EDITAR SOC-…: texto», ou `None`."""
    casado = _COMANDO_DO_ITEM.match(texto) if texto else None
    if casado is None:
        return None
    comando = regras.sem_acentos(casado.group(1)).lower()
    return comando, casado.group(2).upper(), casado.group(3).strip()


#: Os comandos exactos do calendario: o texto todo, e nada mais.
COMANDOS_DO_CALENDARIO: Final = frozenset({"ideias", "calendario", "ideias da semana", "nova", "novas ideias"})

#: A edicao de um campo do perfil, a qualquer altura: «FACTOS: entregamos em
#: Luanda». E a saida que um perfil completo nao tinha (achado I5): as promocoes
#: expiram, e o dono tem de as poder trocar. O nome do campo e o do dono.
_EDICAO: Final = re.compile(
    r"\A\s*(nome|marca|categoria|tom|cores|publico|dias|factos)\s*:\s*(\S.*)\Z", re.DOTALL | re.IGNORECASE
)
CAMPO_DA_EDICAO: Final = {
    "nome": "nome",
    "marca": "nome",
    "categoria": "categoria",
    "tom": "tom",
    "cores": "cores",
    "publico": "publico",
    "dias": "slots",
    "factos": "factos",
}


def _botao(estado: Mapping[str, Any]) -> str:
    if estado.get("input_kind") != "interactive":
        return ""
    botao = estado.get("botao")
    return botao if isinstance(botao, str) else ""


def _limpo(texto: str) -> str:
    return " ".join(regras.sem_acentos(texto).strip(" .!").split())


def edicao(texto: str) -> tuple[str, str] | None:
    """`(campo, valor)` de um «CAMPO: valor», ou `None`. O valor e o do texto original."""
    casado = _EDICAO.match(regras.sem_acentos(texto)) if texto else None
    if casado is None:
        return None
    return CAMPO_DA_EDICAO[casado.group(1).lower()], texto.split(":", 1)[1].strip()


def pede_publicacao(texto: str) -> bool:
    limpo = _limpo(texto)
    return bool(_VERBO_DE_PUBLICAR.search(limpo) and _REDE.search(limpo))


def e_comando_social(estado: Mapping[str, Any], texto: str) -> bool:
    """Se o turno e do social **sem ler a base**, e sem ambiguidade.

    Um botao dele, uma referencia `SOC-…`, um comando exacto («IDEIAS», «NOVA»)
    ou a edicao de um campo. As palavras das redes **nao** estao aqui: vao pelas
    regras do `classify`, depois do orcamento e da informacao da loja (achado I6).
    """
    if regras.ler_botao(_botao(estado)) is not None:
        return True
    if regras.REFERENCIA_NO_TEXTO.search(texto):
        return True
    return _limpo(texto) in COMANDOS_DO_CALENDARIO or edicao(texto) is not None


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
    """O turno do social. Devolve sempre uma resposta pronta.

    A ordem e a dos comandos explicitos primeiro: o botao, a referencia, a
    edicao de um campo, o pedido de publicacao (que se recusa), os comandos
    exactos do calendario. **Com o perfil a meio, o resto e a resposta a pergunta
    em aberto** — «Ideias e Companhia» e um nome, e nao um pedido de ideias (achado
    I4) —; sem ele, as palavras das redes pedem o calendario ou o perfil.
    """
    toque = regras.ler_botao(_botao(estado))
    if toque is not None:
        if toque.accao == "tom":
            return await _responder(deps, estado, "tom", toque.valor)
        if toque.accao == "legenda":
            return await _legenda(deps, estado, toque.valor, None)
        if toque.accao in ("arte", "editar", "rejeitar", "enviar"):
            return await _do_item(deps, estado, toque.accao, toque.valor, "")
        return await _calendario(deps, estado, nova=toque.accao == "nova")
    texto = _texto_do_cliente(estado)
    comando = comando_do_item(texto)
    if comando is not None:
        return await _do_item(deps, estado, *comando)
    referencia, resto = regras.referencia_no_texto(texto)
    if referencia is not None:
        return await _legenda(deps, estado, referencia, resto or None)
    editado = edicao(texto)
    if editado is not None:
        return await _responder(deps, estado, editado[0], editado[1])
    if pede_publicacao(texto):
        resposta = _resposta_estatica(MSG_NAO_PUBLICO)
        resposta["draft"]["botoes"] = (regras.BOTAO_IDEIAS,)
        return resposta
    limpo = _limpo(texto)
    if limpo in COMANDOS_DO_CALENDARIO:
        return await _calendario(deps, estado, nova=limpo in ("nova", "novas ideias"))
    lido = await _invocar(deps, estado, "get_brand_profile", {})
    if not lido.ok:
        return _resposta_estatica(_frase_do_erro(lido.error))
    proxima = lido.data.get("proxima")
    if lido.data.get("existe") and proxima is not None:
        return await _responder(deps, estado, str(proxima["campo"]), texto)
    if re.search(r"\b(?:ideias|calendario)\b", limpo):
        return await _calendario(deps, estado, nova=False)
    if not lido.data.get("existe"):
        return await _comecar(deps, estado)
    resposta = _resposta_estatica(MSG_PERFIL_COMPLETO)
    resposta["draft"]["botoes"] = (regras.BOTAO_IDEIAS,)
    return resposta


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
    linhas.append(MSG_COMO_PEDIR_ARTE)
    resposta = _resposta_estatica("\n".join(linhas))
    resposta["draft"]["botoes"] = (regras.botao_do_item(regras.PREFIXO_DA_ARTE, str(dados["referencia"])),)
    return resposta


# ------------------------------------------------------------------ a arte, a aprovacao e a entrega (KAM-122)


async def _do_item(deps: Dependencias, estado: Mapping[str, Any], comando: str, referencia: str, resto: str) -> dict[str, Any]:
    if comando in ("arte", "outra arte"):
        return await _arte(deps, estado, referencia, nova=comando == "outra arte")
    if comando == "editar":
        if not resto:
            return _resposta_estatica(MSG_COMO_EDITAR.format(referencia=referencia))
        return await _pedir_aprovacao(deps, estado, referencia, legenda=resto[:1000])
    if comando == "rejeitar":
        rejeitado = await _invocar(deps, estado, "reject_content", {"referencia": referencia})
        if not rejeitado.ok:
            return _resposta_estatica(_frase_do_erro(rejeitado.error))
        return _resposta_estatica(MSG_REJEITADO)
    return await _entregar(deps, estado, referencia)


async def _arte(deps: Dependencias, estado: Mapping[str, Any], referencia: str, *, nova: bool) -> dict[str, Any]:
    gerada = await _invocar(deps, estado, "generate_art", {"referencia": referencia, "nova": nova})
    if not gerada.ok:
        return _resposta_estatica(_frase_do_erro(gerada.error))
    return await _pedir_aprovacao(deps, estado, referencia, arte=gerada.data)


async def _pedir_aprovacao(
    deps: Dependencias,
    estado: Mapping[str, Any],
    referencia: str,
    *,
    legenda: str | None = None,
    arte: Mapping[str, Any] | None = None,
) -> dict[str, Any]:
    argumentos: dict[str, Any] = {"referencia": referencia}
    if legenda is not None:
        argumentos["legenda"] = legenda
    pedido = await _invocar(deps, estado, "request_approval", argumentos)
    if not pedido.ok:
        return _resposta_estatica(_frase_do_erro(pedido.error))
    dados = pedido.data
    linhas = [MSG_PRE_VISUALIZACAO.format(referencia=referencia)]
    if arte is not None and arte.get("texto_da_arte"):
        linhas.append(MSG_TEXTO_DA_ARTE)
        linhas.extend(str(x) for x in arte["texto_da_arte"])
    linhas += [MSG_LEGENDA_PARA_APROVAR, str(dados.get("legenda") or ""), MSG_IMAGEM_POR_LIGAR, MSG_COMO_APROVAR]
    if arte is not None and arte.get("alerta_de_custo"):
        linhas.append(MSG_ALERTA_DE_CUSTO)
    resposta = _resposta_estatica("\n".join(linhas))
    resposta["draft"]["botoes"] = (
        f"confirm:{dados['action_id']}",
        regras.botao_do_item(regras.PREFIXO_DE_EDITAR, referencia),
        regras.botao_do_item(regras.PREFIXO_DE_REJEITAR, referencia),
    )
    return resposta


async def aprovar(deps: Dependencias, estado: Mapping[str, Any], botao: str, action_id: str) -> dict[str, Any] | None:
    """A aprovacao depois do botao `confirm:{action_id}`, ou `None` se a accao nao e de conteudo.

    Corre pelo `approve_content`, com a `Confirmation` deste turno: o passo 4
    confere que o botao cita o `action_id` dos argumentos e que e deste contacto.
    """
    resultado = await _invocar(
        deps,
        estado,
        "approve_content",
        {"action_id": action_id},
        confirmacao=Confirmation(botao=botao, contact_id=estado["contact_id"], turn_id=estado["turn_id"]),
        chave=f"approve_content:{action_id}",
    )
    if resultado.ok:
        dados = resultado.data
        # **Um botao repetido devolve o resultado guardado** (o passo 5 do §6.3),
        # e esse resultado e o do primeiro toque: depois de uma edicao, o item ja
        # nao esta aprovado. A frase nao o afirma.
        if dados.get("confirmacao_extra") and not getattr(resultado, "idempotent_replay", False):
            # A revisao reforcada: o primeiro botao pede o segundo.
            resposta = _resposta_estatica(MSG_CONFIRMACAO_EXTRA)
            resposta["draft"]["botoes"] = (f"confirm:{dados['action_id']}",)
            return resposta
        if getattr(resultado, "idempotent_replay", False):
            frase = MSG_BOTAO_JA_USADO
        else:
            frase = MSG_JA_APROVADO if dados.get("ja_aprovado") else MSG_APROVADO
        resposta = _resposta_estatica(frase)
        resposta["draft"]["botoes"] = (regras.botao_do_item(regras.PREFIXO_DE_ENVIAR, str(dados["referencia"])),)
        return resposta
    erro = resultado.error
    codigo, detalhe = getattr(erro, "codigo", ""), getattr(erro, "detalhe", "")
    if codigo in (NOT_FOUND, TOOL_NOT_ALLOWED, ENTITLEMENT_DENIED) and detalhe != "item_desconhecido":
        # Uma accao de outro modulo, ou o social desligado: fala a frase da confirmacao.
        return None
    return _resposta_estatica(_frase_do_erro(erro))


async def _entregar(deps: Dependencias, estado: Mapping[str, Any], referencia: str) -> dict[str, Any]:
    """A entrega ao dono (criterio 8): so quando ele pede, e a janela esta aberta por ele.

    O dono acabou de escrever, pelo que a janela de vinte e quatro horas da
    conversa dele esta aberta: a entrega vai como resposta. Fora dela nao ha
    entrega nenhuma — o item fica `aprovado` no painel.
    """
    entregue = await _invocar(deps, estado, "deliver_content", {"referencia": referencia})
    if not entregue.ok:
        return _resposta_estatica(_frase_do_erro(entregue.error))
    dados = entregue.data
    partes = dados["entrega"]
    abertura = MSG_JA_ENTREGUE if dados.get("ja_entregue") else MSG_ENTREGA
    linhas = [abertura.format(referencia=referencia), "", str(partes["legenda"]), ""]
    if partes.get("nota"):
        linhas.append(str(partes["nota"]))
    linhas.append(MSG_IMAGEM_POR_LIGAR)
    if partes.get("termos"):
        linhas.append(str(partes["termos"]))
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
    if codigo == LIMIT_EXCEEDED and detalhe == "tentativas_esgotadas":
        return MSG_TENTATIVAS_ESGOTADAS
    if codigo == UPSTREAM_TIMEOUT:
        return MSG_NAO_CONSEGUI
    return FRASE_DA_RECUSA.get(detalhe, MSG_NAO_CONSEGUI)


# ------------------------------------------------------------------ as frases
# **Sem digitos**, todas: vao ao `send` sem passar pelo validador (aresta 34).

MSG_COMECAR: Final = "Vamos conhecer a sua marca. Sao poucas perguntas, uma de cada vez."
MSG_PERFIL_PRIMEIRO: Final = "Antes das ideias, preciso de conhecer a sua marca."
MSG_GUARDADO: Final = "Guardado."
MSG_PERFIL_COMPLETO: Final = (
    "O perfil da marca esta completo. Escreva IDEIAS para receber as ideias da proxima semana. Para "
    "mudar um campo, escreva o nome dele e o valor novo, por exemplo FACTOS: seguido dos factos, um "
    "por linha."
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

# KAM-122: a arte, a aprovacao e a entrega. Sem digitos, como as outras.
MSG_COMO_PEDIR_ARTE: Final = "Quando a legenda estiver boa, toque em Arte para preparar a imagem e pedir a sua aprovacao."
MSG_PRE_VISUALIZACAO: Final = "Pre-visualizacao de {referencia}, para aprovar:"
MSG_TEXTO_DA_ARTE: Final = "Texto da arte:"
MSG_LEGENDA_PARA_APROVAR: Final = "Legenda:"
MSG_IMAGEM_POR_LIGAR: Final = (
    "A imagem da arte ainda nao segue por esta conversa; fica guardada com o item."
)
MSG_COMO_APROVAR: Final = (
    "Aprove, edite ou rejeite. Para editar a legenda, escreva EDITAR, a referencia, dois pontos e a "
    "legenda nova. Para outra arte, escreva OUTRA ARTE e a referencia."
)
MSG_ALERTA_DE_CUSTO: Final = (
    "Atencao: cada arte nova custa. Este item so tem mais uma tentativa de arte."
)
MSG_COMO_EDITAR: Final = "Escreva EDITAR {referencia}: e a seguir a legenda nova."
MSG_REJEITADO: Final = "Rejeitado. Esse conteudo nao sera usado."
MSG_APROVADO: Final = (
    "Aprovado. Quando quiser publicar, toque em Enviar e eu mando-lhe a legenda para copiar. "
    "Eu nao publico nada: publica o senhor."
)
MSG_JA_APROVADO: Final = "Esse conteudo ja estava aprovado. Toque em Enviar quando quiser publicar."
MSG_CONFIRMACAO_EXTRA: Final = (
    "Este conteudo esta em revisao reforcada: confirme outra vez que o quer aprovar, no botao abaixo."
)
MSG_BOTAO_JA_USADO: Final = (
    "Esse botao ja foi usado. Se mudou o conteudo depois, aprove-o no botao da pre-visualizacao mais recente."
)
MSG_ENTREGA: Final = "Aqui esta o conteudo {referencia} para publicar. A legenda vem a seguir, para copiar:"
MSG_JA_ENTREGUE: Final = "O conteudo {referencia} ja lhe foi entregue. A legenda vai outra vez, para copiar:"
MSG_TENTATIVAS_ESGOTADAS: Final = (
    "Este item ja teve as tentativas de arte do plano. Aprove uma das artes ou rejeite o item."
)

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
    "sem_arte": "Primeiro a arte: toque em Arte, ou escreva ARTE e a referencia.",
    "sem_legenda": "Primeiro a legenda: toque no botao da legenda dessa ideia.",
    "ja_aprovado": "Esse conteudo ja esta aprovado. Para mudar a legenda, escreva EDITAR, a referencia e o texto.",
    "aprovacao_invalidada": (
        "Esse botao e de uma versao anterior: o conteudo mudou depois dele. Use o botao da pre-visualizacao mais recente."
    ),
    "por_aprovar": "Esse conteudo ainda nao foi aprovado. Aprove-o primeiro no botao da pre-visualizacao.",
    "texto_nao_cabe": "O texto da arte nao cabe no modelo. Encurte o nome ou o facto e tente outra vez.",
    "arte_desactualizada": (
        "Os factos da loja mudaram depois desta arte, e ela tem um valor que ja nao vale. Escreva OUTRA ARTE e a referencia."
    ),
    "arte_por_ligar": "As artes ainda nao estao disponiveis por aqui.",
    "fontes_em_falta": "As artes ainda nao estao disponiveis por aqui.",
    "accao_por_confirmar": "Esse botao ainda nao foi confirmado.",
    "botoes_esgotados": MSG_NAO_CONSEGUI,
    "faltam_factos": (
        "Para por precos, descontos, datas ou contactos na legenda, escreva primeiro FACTOS: seguido "
        "dos factos da loja, um por linha, e em cada promocao a data em que acaba. Nao invento valores."
    ),
    "promocao_vencida": "Essa promocao ja acabou. Escreva a data em que a promocao nova acaba.",
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
