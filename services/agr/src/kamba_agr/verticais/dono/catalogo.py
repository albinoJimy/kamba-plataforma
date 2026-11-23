"""A conversa do catalogo no grafo do dono (KAM-119): respostas, eco do preco, estado e publicacao.

Corre no no `confirm` do dono, como a resposta a um orcamento do KAM-220 (aresta
37, intencao `catalogo`): **deterministica, sem modelo**, e com o texto pronto
(`_resposta_estatica`). Cada passo vai a ToolLayer pelos oito passos do §6.1 —
o entitlement `catalogo` no passo 2, a `tool_audit` no 7 —, e nenhum argumento
de tool sai de um modelo de linguagem.

## O que decide o que este turno e

| Entrada | Accao |
|---|---|
| botao `preco:{ingestao}:{centimos}` | grava o preco do eco (`create_product_draft`, `preco_confirmado`) |
| botao `preco_corrigir:{ingestao}` | pede o preco outra vez; nada se grava |
| botao `mesmo_produto:` / `outro_produto:` | a resposta a «e o mesmo produto?» |
| botao `retomar:` | o screening outra vez, numa ingestao que ele nao decidiu (KAM-244) |
| uma foto com `asset_id` | o rascunho pela foto (`create_product_draft`, `asset_id`), KAM-231 |
| uma foto sem `asset_id` | a foto nao chegou ao STO (o MED recusou, falhou ou nao esta montado): diz-se ao dono |
| texto, com rascunho a espera de resposta | a resposta as perguntas em aberto; o preco vai so ao eco |
| texto sobre o catalogo, sem resposta a dar | o estado do catalogo (`get_catalog_status`) |

## Os numeros do texto sao os da tool

As contagens do estado, o eco do preco e o resumo levam digitos, e nao passam
pelo validador (aresta 34). **Cada digito vem do resultado da tool deste
turno**: as contagens sao os *facts* `count` do `get_catalog_status`, o eco e o
valor que o *parser* leu e que o botao leva, o resumo e o do KAM-049. Nada
aqui faz contas, e os textos fixos deste modulo nao tem digitos (ensaio).

## A referencia `PRD-…`

Com um so rascunho a espera de resposta, o dono responde sem ela. Com mais de
um, pede-se a referencia: uma resposta que fosse ao rascunho errado era o preco
de um produto gravado noutro — e o criterio 4 pede dez fotos sem mistura.
"""

from __future__ import annotations

from collections.abc import Mapping
from typing import Any, Final

from kamba_core.catalogo.completude import CRITICOS

from ...catalogo import regras
from ...contexto import chave_de_envio
from ...tls.contexto import Confirmation
from ...tls.erros import ENTITLEMENT_DENIED, NOT_FOUND, TOOL_NOT_ALLOWED, UPSTREAM_TIMEOUT, VALIDATION_ERROR
from ..vendedor.nos import Dependencias, _invocar, _resposta_estatica, _texto_do_cliente

#: Quantos rascunhos a lista do estado mostra. *Proposta*: cabe numa mensagem.
LIMITE_DA_LISTA: Final = 5


def _botao(estado: Mapping[str, Any]) -> str:
    if estado.get("input_kind") != "interactive":
        return ""
    botao = estado.get("botao")
    return botao if isinstance(botao, str) else ""


def e_do_catalogo(estado: Mapping[str, Any], texto: str) -> bool:
    """Se o turno e do catalogo **sem ler a base**: um botao dele, uma foto, um `PRD-…`."""
    if regras.ler_botao(_botao(estado)) is not None:
        return True
    if estado.get("input_kind") == "image":
        return True
    return regras.REFERENCIA_NO_TEXTO.search(texto) is not None


async def estado_do_catalogo(deps: Dependencias, estado: Mapping[str, Any]) -> Any:
    """O `get_catalog_status` deste tenant, ou `None` se a tool recusou."""
    resultado = await _invocar(deps, estado, "get_catalog_status", {})
    return resultado if getattr(resultado, "ok", False) else None


def _a_perguntar(status: Any) -> list[Mapping[str, Any]]:
    if status is None:
        return []
    return [p for p in status.data.get("pendentes", ()) if p.get("estado") == "a_perguntar"]


async def ha_resposta_a_dar(deps: Dependencias, estado: Mapping[str, Any]) -> bool:
    """Se ha rascunhos a espera de resposta do dono. Uma tool que falha diz que nao."""
    try:
        return bool(_a_perguntar(await estado_do_catalogo(deps, estado)))
    except Exception:  # noqa: BLE001 — uma leitura que falha nao rebenta o turno
        return False


# ------------------------------------------------------------------ o no


async def tratar(deps: Dependencias, estado: Mapping[str, Any]) -> dict[str, Any]:
    """O turno do catalogo. Devolve sempre uma resposta pronta."""
    toque = regras.ler_botao(_botao(estado))
    if toque is not None:
        return await _do_botao(deps, estado, toque)
    if estado.get("input_kind") == "image":
        return await _da_foto(deps, estado)
    texto = _texto_do_cliente(estado)
    status = await estado_do_catalogo(deps, estado)
    if status is None:
        return _resposta_estatica(MSG_CATALOGO_INACTIVO)
    referencia, resto = regras.referencia_no_texto(texto)
    abertos = _a_perguntar(status)
    if referencia is not None:
        prefixo = regras.prefixo_da_referencia(referencia) or "-"
        alvo = [p for p in status.data.get("pendentes", ()) if str(p.get("ingestao", "")).replace("-", "").startswith(prefixo)]
        if len(alvo) != 1:
            return _resposta_estatica(MSG_REFERENCIA_DESCONHECIDA)
        return await _responder(deps, estado, str(alvo[0]["ingestao"]), resto)
    if len(abertos) == 1 and resto:
        # Um texto com palavras do catalogo («quantos produtos tenho?») so e
        # resposta se a pergunta em aberto for das criticas — o preco e o stock
        # escrevem-se com essas palavras. Senao e um pedido do estado.
        so_criticas = estado.get("intent") == "modulos"
        return await _responder(
            deps, estado, str(abertos[0]["ingestao"]), resto, senao=status if so_criticas else None
        )
    if len(abertos) > 1 and resto and estado.get("intent") != "modulos":
        return _resposta_estatica("\n".join((MSG_QUAL_RASCUNHO, *_referencias(abertos))))
    return _resposta_do_estado(status)


async def _da_foto(deps: Dependencias, estado: Mapping[str, Any]) -> dict[str, Any]:
    """Uma foto do dono vira rascunho (KAM-231).

    O `asset_id` vem do estado, que o tirou da invocacao: o CHR (pelo MED) ou o
    painel guardaram a foto no STO antes de invocar. **Nenhum argumento vem de
    um modelo**: o no constroi-o do estado, como os outros deste modulo. Sem
    `asset_id`, a foto nao chegou ao STO — o MED recusou-a, falhou, ou nao esta
    montado — e o dono e avisado, sem rascunho.
    """
    asset_id = estado.get("asset_id")
    if not isinstance(asset_id, str) or not asset_id:
        return _resposta_estatica(MSG_FOTO_POR_LIGAR)
    # Decisao do fundador de 2026-11-21 (P3, opcao A): o turno avisa **antes** da
    # tool, que tem tecto de 25 s, e o resumo sai depois pelo `send`. O aviso
    # tem chave propria do turno (`turn_id:1`), pelo que um turno repetido nao
    # o envia duas vezes; o resumo e o `turn_id:0` de sempre.
    await deps.saida.enfileirar(estado, MSG_A_PREPARAR, chave=chave_de_envio(str(estado["turn_id"]), SEQ_DO_AVISO))
    recebida = await _invocar(deps, estado, "create_product_draft", {"asset_id": asset_id})
    if not recebida.ok:
        if getattr(recebida.error, "codigo", "") == UPSTREAM_TIMEOUT:
            # KAM-244: a camada cortou, e o pipeline acaba na *thread* dele e
            # grava o estado. O dono ve-o no turno seguinte, pelo estado do
            # catalogo (as referencias `PRD-…` dos que esperam por ele).
            return _resposta_estatica(MSG_FOTO_EM_CURSO)
        return _resposta_estatica(_frase_do_erro(recebida.error))
    return _resposta_da_ingestao(recebida.data)


async def _responder(
    deps: Dependencias, estado: Mapping[str, Any], ingestao: str, texto: str, *, senao: Any = None
) -> dict[str, Any]:
    """A resposta do dono as perguntas em aberto de uma ingestao.

    Com `senao` (o estado do catalogo), so se responde a perguntas criticas; as
    outras dao o estado.
    """
    lida = await _invocar(deps, estado, "ask_missing_fields", {"ingestao": ingestao})
    if not lida.ok:
        return _resposta_estatica(_frase_do_erro(lida.error))
    perguntas = tuple(
        regras.PerguntaEmAberto(p["campo"], p["texto"], p.get("sugestao")) for p in lida.data.get("perguntas", ())
    )
    if senao is not None and not all(p.campo in CRITICOS for p in perguntas):
        return _resposta_do_estado(senao)
    if not perguntas:
        if lida.data.get("estado") == "rascunho":
            # O resumo outra vez, com um botao que serve: o anterior pode ter
            # expirado, ou ser do telefone antigo do dono (achado 2 da revisao).
            # Sem respostas, a ingestao nao muda; o executor propoe a accao.
            reaberto = await _invocar(deps, estado, "create_product_draft", {"ingestao": ingestao, "respostas": {}})
            if not reaberto.ok:
                return _resposta_estatica(_frase_do_erro(reaberto.error))
            return _resposta_da_ingestao(reaberto.data)
        return _resposta_da_ingestao(lida.data)
    if [p.campo for p in perguntas] == ["stock"]:
        # **O stock tambem nao se grava aqui** (achado 6 da revisao): le-se como
        # um inteiro so, e volta ao dono como eco com os dois botoes.
        try:
            unidades = regras.ler_stock_do_dono(texto)
        except regras.StockRecusado:
            return _resposta_estatica("\n".join((MSG_STOCK_POR_REESCREVER, *_linhas_das_perguntas(lida.data))))
        resposta = _resposta_estatica("\n".join((MSG_ECO_DO_STOCK, regras.eco_do_stock(unidades))))
        resposta["draft"]["botoes"] = (
            regras.botao_do_stock(ingestao, unidades),
            regras.botao_de_corrigir_stock(ingestao),
        )
        return resposta
    if [p.campo for p in perguntas] == ["preco"]:
        # **O preco nao se grava aqui**: le-se, e volta ao dono como eco.
        try:
            centimos = regras.ler_preco_do_dono(texto)
            regras.texto_canonico(centimos)
        except (regras.ValorRecusadoError, ValueError):
            return _resposta_estatica("\n".join((MSG_PRECO_POR_REESCREVER, *_linhas_das_perguntas(lida.data))))
        resposta = _resposta_estatica("\n".join((MSG_ECO_DO_PRECO, regras.eco_do_preco(centimos))))
        resposta["draft"]["botoes"] = (
            regras.botao_do_preco(ingestao, centimos),
            regras.botao_de_corrigir_preco(ingestao),
        )
        return resposta
    respostas = regras.repartir_respostas(texto, perguntas)
    if respostas is None:
        return _resposta_estatica("\n".join((MSG_UMA_POR_LINHA, *_linhas_das_perguntas(lida.data))))
    gravada = await _invocar(
        deps,
        estado,
        "create_product_draft",
        {"ingestao": ingestao, "respostas": respostas, "voz": estado.get("input_kind") == "audio"},
    )
    if not gravada.ok:
        return _resposta_estatica(_frase_do_erro(gravada.error))
    return _resposta_da_ingestao(gravada.data)


async def _do_botao(deps: Dependencias, estado: Mapping[str, Any], toque: regras.BotaoDoCatalogo) -> dict[str, Any]:
    if toque.accao in ("preco_corrigir", "stock_corrigir"):
        lida = await _invocar(deps, estado, "ask_missing_fields", {"ingestao": toque.ingestao})
        if not lida.ok:
            return _resposta_estatica(_frase_do_erro(lida.error))
        frase = MSG_PRECO_OUTRA_VEZ if toque.accao == "preco_corrigir" else MSG_STOCK_OUTRA_VEZ
        return _resposta_estatica("\n".join((frase, *_linhas_das_perguntas(lida.data))))
    if toque.accao == "preco":
        argumentos: dict[str, Any] = {"ingestao": toque.ingestao, "preco_confirmado": toque.valor}
    elif toque.accao == "stock":
        argumentos = {"ingestao": toque.ingestao, "stock_confirmado": toque.valor}
    elif toque.accao == "retomar":
        # KAM-244: «tentar outra vez» o screening que nao decidiu. Sem respostas,
        # o executor pergunta-lhe outra vez (`retomar` do KAM-049).
        argumentos = {"ingestao": toque.ingestao, "respostas": {}}
    else:
        argumentos = {"ingestao": toque.ingestao, "mesmo_produto": toque.accao == "mesmo_produto"}
    gravada = await _invocar(deps, estado, "create_product_draft", argumentos)
    if not gravada.ok:
        return _resposta_estatica(_frase_do_erro(gravada.error))
    return _resposta_da_ingestao(gravada.data)


async def publicar(deps: Dependencias, estado: Mapping[str, Any], botao: str, action_id: str) -> str | None:
    """A publicacao depois do botao `confirm:{action_id}`, ou `None` se a accao nao e de produto.

    Corre pelo `publish_product`, com a `Confirmation` deste turno: o passo 4
    confere que o botao cita o `action_id` dos argumentos e que e deste contacto.
    """
    resultado = await _invocar(
        deps,
        estado,
        "publish_product",
        {"action_id": action_id},
        confirmacao=Confirmation(botao=botao, contact_id=estado["contact_id"], turn_id=estado["turn_id"]),
        chave=f"publish_product:{action_id}",
    )
    if resultado.ok:
        return MSG_PUBLICADO
    erro = resultado.error
    codigo, detalhe = getattr(erro, "codigo", ""), getattr(erro, "detalhe", "")
    if codigo in (NOT_FOUND, TOOL_NOT_ALLOWED, ENTITLEMENT_DENIED) and detalhe != "ingestao_desconhecida":
        # Uma accao que nao e de um produto, ou um catalogo que nao esta ligado:
        # quem fala e a frase da confirmacao.
        return None
    if codigo == VALIDATION_ERROR and detalhe == "categoria_bloqueada":
        return MSG_CATEGORIA_RECUSADA
    if codigo == VALIDATION_ERROR and detalhe == "revisao_pendente":
        return MSG_EM_REVISAO
    if codigo == VALIDATION_ERROR and detalhe == "confirmacao_recusada":
        return MSG_RESUMO_DESACTUALIZADO
    if codigo == UPSTREAM_TIMEOUT:
        # O tecto da ToolLayer (8 s, §6.5) e mais curto do que o screening com o
        # classificador: a publicacao pode estar a acabar. O toque seguinte e
        # idempotente e diz o que aconteceu (achado 5 da revisao).
        return MSG_PUBLICACAO_EM_CURSO
    return MSG_PUBLICACAO_POR_ACABAR


# ------------------------------------------------------------------ as frases


def _referencias(pendentes: list[Mapping[str, Any]]) -> tuple[str, ...]:
    return tuple(str(p["referencia"]) for p in pendentes[:LIMITE_DA_LISTA])


def _linhas_das_perguntas(dados: Mapping[str, Any]) -> tuple[str, ...]:
    linhas = [str(dados.get("referencia", ""))]
    for p in dados.get("perguntas", ()):
        linha = str(p["texto"])
        if p.get("sugestao"):
            linha += f" ({MSG_NA_FOTO} {p['sugestao']})"
        linhas.append(linha)
    return tuple(linhas)


def _resposta_da_ingestao(dados: Mapping[str, Any]) -> dict[str, Any]:
    """A mensagem ao dono para o estado em que a ingestao ficou."""
    estado_da_ingestao = dados.get("estado")
    if dados.get("mesmo_produto_que"):
        resposta = _resposta_estatica(MSG_MESMO_PRODUTO)
        resposta["draft"]["botoes"] = (
            regras.botao_do_mesmo_produto(str(dados["ingestao"])),
            regras.botao_de_outro_produto(str(dados["ingestao"])),
        )
        return resposta
    if estado_da_ingestao == "a_perguntar":
        if not dados.get("perguntas"):
            return _resposta_estatica(MSG_PERGUNTAS_ESGOTADAS)
        return _resposta_estatica("\n".join(_linhas_das_perguntas(dados)))
    if estado_da_ingestao == "rascunho" and dados.get("resumo") and dados.get("action_id"):
        linhas = [MSG_RESUMO, str(dados["resumo"]), MSG_CONFIRMAR_PUBLICAR]
        if dados.get("melhorar_foto"):
            linhas.append(MSG_MELHORAR_FOTO)
        resposta = _resposta_estatica("\n".join(linhas))
        resposta["draft"]["botoes"] = (f"confirm:{dados['action_id']}",)
        return resposta
    if estado_da_ingestao == "bloqueada_categoria" and dados.get("retomavel"):
        # KAM-244: o screening nao chegou a decidir (sem tempo, ou em baixo). Nao
        # e «nao pode ser publicado»: o toque seguinte pergunta-lhe outra vez.
        resposta = _resposta_estatica(MSG_POR_VERIFICAR)
        resposta["draft"]["botoes"] = (regras.botao_de_retomar(str(dados["ingestao"])),)
        return resposta
    return _resposta_estatica(FRASE_DO_ESTADO.get(str(estado_da_ingestao), MSG_NAO_CONSEGUI))


def _resposta_do_estado(status: Any) -> dict[str, Any]:
    """As contagens e os rascunhos a espera. Os numeros sao os *facts* `count` da tool."""
    dados = status.data
    linhas = [
        f"{MSG_RASCUNHOS} {dados['rascunhos']}",
        f"{MSG_PUBLICADOS} {dados['publicados']}",
        f"{MSG_BLOQUEADOS} {dados['bloqueados']}",
    ]
    pendentes = [p for p in dados.get("pendentes", ())]
    if pendentes:
        linhas.append(MSG_A_ESPERA)
        linhas.extend(_referencias(pendentes))
    linhas.append(MSG_COMO_COMECAR)
    return _resposta_estatica("\n".join(linhas))


def _frase_do_erro(erro: Any) -> str:
    codigo, detalhe = getattr(erro, "codigo", ""), getattr(erro, "detalhe", "")
    if codigo in (TOOL_NOT_ALLOWED, ENTITLEMENT_DENIED):
        return MSG_CATALOGO_INACTIVO
    if codigo == NOT_FOUND:
        return MSG_REFERENCIA_DESCONHECIDA
    if detalhe == "loja_limitada":
        return MSG_LOJA_LIMITADA
    if detalhe == "foto_indisponivel":
        return MSG_FOTO_POR_LIGAR
    if detalhe == "botao_antigo":
        return MSG_BOTAO_ANTIGO
    return MSG_NAO_CONSEGUI


# **Sem digitos**, todos: vao ao `send` sem passar pelo validador (aresta 34).
MSG_CATALOGO_INACTIVO: Final = "O modulo do catalogo nao esta activo para a sua loja."
#: O aviso antes do `create_product_draft` de uma foto (KAM-231, P3). Sem
#: digitos, como os outros textos estaticos.
MSG_A_PREPARAR: Final = "Recebi a foto. Estou a preparar o produto, ja lhe digo o que vi."
#: O `seq` do aviso no turno: o resumo e o `0` do `send`.
SEQ_DO_AVISO: Final = 1
#: KAM-244: a camada cortou a tool da foto, que continua a preparar o produto.
MSG_FOTO_EM_CURSO: Final = (
    "Ainda estou a preparar este produto. Daqui a pouco escreva produtos para ver em que ficou."
)
#: KAM-244: o screening nao decidiu a categoria a tempo. Vai com o botao «Tentar outra vez».
MSG_POR_VERIFICAR: Final = (
    "Ainda nao consegui verificar a categoria deste produto. Toque no botao para eu tentar outra vez."
)
MSG_FOTO_POR_LIGAR: Final = (
    "Nao consegui receber esta foto. Envie-a outra vez, ou crie o produto pelo painel da loja."
)
MSG_REFERENCIA_DESCONHECIDA: Final = (
    "Nao encontrei esse produto em preparacao. Confira a referencia PRD."
)
MSG_QUAL_RASCUNHO: Final = (
    "Tem mais de um produto em preparacao. Responda com a referencia PRD do produto:"
)
MSG_UMA_POR_LINHA: Final = "Responda a cada pergunta numa linha, pela mesma ordem:"
MSG_PRECO_POR_REESCREVER: Final = (
    "Nao percebi o preco sem duvidas. Escreva so o valor final em kwanzas, sem contas."
)
MSG_PRECO_OUTRA_VEZ: Final = "Escreva o preco outra vez:"
MSG_STOCK_POR_REESCREVER: Final = (
    "Nao percebi o stock sem duvidas. Escreva so o numero de unidades, sem pontos nem «mil»."
)
MSG_STOCK_OUTRA_VEZ: Final = "Escreva o stock outra vez:"
MSG_ECO_DO_STOCK: Final = "O stock fica assim?"
MSG_BOTAO_ANTIGO: Final = "Esse botao ja nao vale: essa pergunta ja foi respondida."
MSG_EM_REVISAO: Final = (
    "Este produto ficou para revisao da nossa equipa antes de ser publicado. Avisamos quando estiver decidido."
)
MSG_PUBLICACAO_EM_CURSO: Final = (
    "Ainda estou a publicar. Toque outra vez no mesmo botao daqui a pouco para ver se ficou."
)
MSG_ECO_DO_PRECO: Final = "O preco fica assim?"
MSG_NA_FOTO: Final = "na foto vi"
MSG_MESMO_PRODUTO: Final = "Esta foto parece de um produto que ja mandou. E o mesmo produto?"
MSG_PERGUNTAS_ESGOTADAS: Final = (
    "Ja fiz todas as perguntas que podia por aqui. Termine este produto no painel da loja."
)
MSG_RESUMO: Final = "O produto fica assim:"
MSG_CONFIRMAR_PUBLICAR: Final = "Se estiver certo, confirme no botao para o publicar."
MSG_MELHORAR_FOTO: Final = "Tambem posso melhorar a foto do produto, quando quiser."
MSG_PUBLICADO: Final = "Produto publicado no catalogo."
MSG_CATEGORIA_RECUSADA: Final = (
    "Este produto nao pode ser publicado no catalogo. Se achar que e engano, fale com a nossa equipa."
)
MSG_RESUMO_DESACTUALIZADO: Final = (
    "Este botao era de uma versao anterior do produto. Use o botao do ultimo resumo."
)
MSG_PUBLICACAO_POR_ACABAR: Final = (
    "Nao consegui publicar agora. Toque outra vez no mesmo botao daqui a pouco."
)
MSG_LOJA_LIMITADA: Final = "A loja tem uma limitacao em vigor e nao pode publicar produtos novos."
MSG_NAO_CONSEGUI: Final = "Nao consegui tratar esse pedido do catalogo por aqui."
MSG_RASCUNHOS: Final = "Produtos em preparacao:"
MSG_PUBLICADOS: Final = "Produtos publicados por aqui:"
MSG_BLOQUEADOS: Final = "Produtos bloqueados:"
MSG_A_ESPERA: Final = "A espera da sua resposta:"
MSG_COMO_COMECAR: Final = "Para um produto novo, mande uma foto dele."
MSG_REJEITADA: Final = "Nao consegui ver bem o produto nesta foto. Mande outra, com mais luz e mais perto."
MSG_ANALISE_INDISPONIVEL: Final = (
    "Nao consigo analisar fotos neste momento. Tente outra vez mais tarde."
)
MSG_DESCARTADA: Final = "Pronto, nao criei outro produto com esta foto."

#: O estado em que a ingestao ficou -> a frase, para os que nao tem resumo nem perguntas.
FRASE_DO_ESTADO: Final = {
    "publicada": MSG_PUBLICADO,
    "bloqueada_categoria": MSG_CATEGORIA_RECUSADA,
    "rejeitada_qualidade": MSG_REJEITADA,
    "bloqueada_gate": MSG_ANALISE_INDISPONIVEL,
    "descartada": MSG_DESCARTADA,
}
