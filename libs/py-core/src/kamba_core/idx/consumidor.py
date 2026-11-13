"""O consumidor do indice: produtos e estado do tenant (KAM-061, §4.3).

Mantem o `idx.search_doc` a par do catalogo e do estado da loja, dentro da
transaccao do `kamba_core.eventos.consumo.consumir` (KAM-006): a marca em
`platform.events_consumed` e a escrita no indice caem na mesma transaccao, e um
duplicado entregue dez vezes escreve uma.

## O efeito le o estado, e nao o *payload*

O `catalog.product_changed` traz `{sku, estado}` e os eventos de tenant nao
trazem nada que sirva. O efeito **le o estado presente** — a
`platform.v_oferta_viva` do KAM-051 e a `platform.tenants` — e escreve o
documento a partir dele. Tres consequencias, e as tres sao o objectivo:

* **a ordem nao importa.** Um `product_changed` atrasado relido depois de um
  mais novo escreve o estado de **agora**, que e o certo; por isso a subscricao
  nao exige ordem (`exige_ordem = False`) e nenhum evento vai para a DLQ por
  chegar tarde;
* **a definicao de «publicavel» e uma so.** O `visivel` e a coluna `publicado`
  da vista (estado `publicado`, sem `deleted_at`, sem `categoria_restrita`) **e**
  o tenant `ativo` — o mesmo predicado que a resposta (§6.3) filtra, e nao uma
  segunda leitura do `payload.estado` que podia divergir dela;
* **a reparacao e o mesmo codigo.** Reprocessar um evento antigo da DLQ escreve
  o estado presente.

O `visivel` e a primeira de **duas** defesas (§4.3): a funcao `idx.candidatos`
junta `platform.tenants` com `estado = 'ativo'` em cada chamada. Se este
consumidor atrasar, a porta `tn` ja impede a fuga de um tenant suspenso.

## O que **nao** esta aqui

* O **processo** que subscreve a fila e chama `consumir_evento` (a entrada em
  `registry/` e o trabalhador). Sem ele, o p95 de frescura do criterio 9 nao se
  mede; o efeito e a transaccao sim, e estao medidos contra um PostgreSQL. O
  credor e o **KAM-194** (a ponte fila -> consumidor Python), e nao o KAM-193:
  o que falta e infraestrutura de eventos — a casca BullMQ -> HTTP, as linhas
  de `platform.evt_subscricoes` e uma forma do `registry/` para um consumidor
  que nao e vertical —, e serve tambem o `/internal/event` do AGR.
* `categoria_canon` e `descr_norm`: o `platform.offer_terms` so tem `nome`.
  Ficam nulo e vazio. A `marca_canon` sai do lexico (KAM-062).
* O embedding. O documento nasce sem ele, que e o modo lexical, e quem o
  escreve e o *worker* do `kamba_core.idx.embeddings` (KAM-063). Daqui so sai
  uma coisa sobre ele: reescrever o documento com **outro** texto anula o
  vector, e com o mesmo texto deixa-o (`COLUNAS_DO_TEXTO_ESCRITAS`).
"""

from __future__ import annotations

from collections.abc import Mapping
from typing import Final

from kamba_core.eventos.consumo import (
    ClienteSql,
    Metricas,
    OpcoesDoConsumo,
    ResultadoDoConsumo,
    consumir,
)

from .lexico import consultar, ler_lexico, ler_versoes
from .normalizacao import Lexico, normalizar_documento

#: O nome do consumidor em `platform.events_consumed`. A chave de idempotencia e
#: `(consumer, event_id)`: mudar este nome reprocessa tudo.
CONSUMIDOR: Final = "idx"

#: A versao com que o KAM-061 escreveu o indice: so o passo 1 do §5.1. Desde o
#: KAM-062 a versao e a do `idx.norm_versao` (`kamba_core.idx.lexico`), e esta e
#: a que ele devolve sem linhas.
NORM_VERSAO: Final = 1

#: O tipo do evento de produto.
PRODUTO_ALTERADO: Final = "catalog.product_changed"

#: Os eventos de estado do tenant. Os quatro escrevem o mesmo: o `visivel` de
#: todos os documentos do tenant, relido do estado presente.
EVENTOS_DO_TENANT: Final = (
    "tenant.suspended",
    "tenant.closed",
    "tenant.activated",
    "tenant.reactivated",
)

#: Os tipos que este consumidor aceita. Lista fechada.
TIPOS: Final = (PRODUTO_ALTERADO, *EVENTOS_DO_TENANT)

#: A oferta viva do produto: o nome e se e publicavel. Zero linhas = a oferta
#: deixou de existir (purga da retencao, KAM-071).
SQL_LER_OFERTA: Final = """
  SELECT v.nome, v.publicado
    FROM platform.v_oferta_viva v
   WHERE v.tenant_id = NULLIF(current_setting('app.tenant_id', true), '')::uuid
     AND v.product_ref = %s
"""

#: As ofertas vivas de um lote de documentos, numa so leitura (o *worker*).
SQL_LER_OFERTAS: Final = """
  SELECT v.product_ref, v.nome, v.publicado
    FROM platform.v_oferta_viva v
   WHERE v.tenant_id = NULLIF(current_setting('app.tenant_id', true), '')::uuid
     AND v.product_ref = ANY(%s::text[])
"""

#: As colunas do texto de embedding que a instrucao de escrita **escreve**
#: (KAM-063, criterio 5). Se o texto nao mudou, o vector fica; se mudou, fica
#: nulo e o *worker* reembebe-o. **O preco nao esta aqui, nem pode estar**: o
#: documento nao tem coluna de preco, e por isso mudar o preco reescreve o
#: documento com o mesmo texto e o vector sobrevive. A `categoria_canon` e a
#: `descr_norm` sao do texto de embedding mas **ninguem as escreve** (o
#: `platform.offer_terms` so tem `nome`): no dia em que a instrucao as escrever,
#: entram nesta tupla — e o `test_cada_coluna_do_texto_escrita_e_comparada`
#: recusa a instrucao que escreva uma coluna do texto sem a comparar.
COLUNAS_DO_TEXTO_ESCRITAS: Final = ("nome_norm", "marca_canon")

#: O texto de embedding nao mudou: as colunas antigas igualam as novas.
_TEXTO_IGUAL: Final = (
    "("
    + ", ".join(f"idx.search_doc.{c}" for c in COLUNAS_DO_TEXTO_ESCRITAS)
    + ") IS NOT DISTINCT FROM ("
    + ", ".join(f"EXCLUDED.{c}" for c in COLUNAS_DO_TEXTO_ESCRITAS)
    + ")"
)

#: Escreve ou reescreve documentos, um ou um lote, numa so instrucao. O
#: `visivel` junta o tenant `ativo` ao `publicado` da oferta; o `SELECT` sobre
#: `platform.tenants` le **so** o tenant do contexto (RLS por `id`), e sem ele
#: nao escreve nada. O `{linhas}` e uma `_LINHA_A_ESCREVER` por documento
#: (`sql_escrever_documentos`): o caminho do evento e o do *worker* escrevem
#: pela **mesma** instrucao, e a definicao de «visivel» e uma so. O vector e o
#: seu modelo so sobrevivem se o texto for o mesmo (`COLUNAS_DO_TEXTO_ESCRITAS`).
_SQL_ESCREVER_DOCUMENTOS: Final = """
  INSERT INTO idx.search_doc
         (tenant_id, product_ref, norm_versao, nome_norm, marca_canon, visivel)
  SELECT t.id, u.product_ref, %s, u.nome_norm, u.marca_canon,
         (u.publicado AND t.estado = 'ativo')
    FROM platform.tenants t
   CROSS JOIN (VALUES {linhas}) AS u(product_ref, nome_norm, marca_canon, publicado)
   WHERE t.id = NULLIF(current_setting('app.tenant_id', true), '')::uuid
  ON CONFLICT (tenant_id, product_ref) DO UPDATE
     SET norm_versao   = EXCLUDED.norm_versao,
         nome_norm     = EXCLUDED.nome_norm,
         marca_canon   = EXCLUDED.marca_canon,
         visivel       = EXCLUDED.visivel,
         embedding     = CASE WHEN {texto_igual} THEN idx.search_doc.embedding END,
         embedding_modelo
                       = CASE WHEN {texto_igual} THEN idx.search_doc.embedding_modelo END,
         atualizado_at = now()
""".replace("{texto_igual}", _TEXTO_IGUAL)

#: Um documento no `VALUES`, com os tipos escritos: uma `marca_canon` nula em
#: todas as linhas nao deixa o PostgreSQL adivinhar a coluna.
_LINHA_A_ESCREVER: Final = "(%s::text, %s::text, %s::text, %s::boolean)"


def sql_escrever_documentos(quantos: int) -> str:
    """A instrucao que escreve `quantos` documentos (parametros: versao e 4 por linha)."""
    if quantos < 1:
        raise ValueError("escrever zero documentos nao e uma instrucao")
    return _SQL_ESCREVER_DOCUMENTOS.replace(
        "{linhas}", ", ".join([_LINHA_A_ESCREVER] * quantos)
    )


#: A de um documento, que e a do caminho do evento.
SQL_ESCREVER_DOCUMENTO: Final = sql_escrever_documentos(1)

#: A oferta desapareceu: o documento fica, invisivel. Nao se apaga — o
#: `kamba_app` nao tem `DELETE` no indice, e a purga e da retencao.
SQL_ESCONDER_DOCUMENTO: Final = """
  UPDATE idx.search_doc
     SET visivel = false, atualizado_at = now()
   WHERE tenant_id = NULLIF(current_setting('app.tenant_id', true), '')::uuid
     AND product_ref = %s
"""

#: O `visivel` de todos os documentos do tenant, relido do estado presente.
SQL_RELER_TENANT: Final = """
  UPDATE idx.search_doc d
     SET visivel = COALESCE((SELECT t.estado = 'ativo'
                               FROM platform.tenants t
                              WHERE t.id = d.tenant_id), false)
               AND COALESCE((SELECT v.publicado
                               FROM platform.v_oferta_viva v
                              WHERE v.tenant_id = d.tenant_id
                                AND v.product_ref = d.product_ref), false),
         atualizado_at = now()
   WHERE d.tenant_id = NULLIF(current_setting('app.tenant_id', true), '')::uuid
"""


class TipoNaoSubscrito(ValueError):
    """Um evento que este consumidor nao trata. Vai para a DLQ, nao se ignora."""


def _sku(envelope: Mapping[str, object]) -> str:
    payload = envelope.get("payload")
    sku = payload.get("sku") if isinstance(payload, Mapping) else None
    if not isinstance(sku, str) or not sku.strip():
        raise ValueError("catalog.product_changed sem payload.sku")
    return sku


#: A oferta ainda por ler (o caminho do evento le-a; o *worker* ja a leu).
_POR_LER: Final = object()


def escrever_documento(
    bd: ClienteSql,
    tenant_id: object,
    sku: str,
    lexico: Lexico | None = None,
    oferta: object = _POR_LER,
) -> None:
    """Escreve o documento do `sku` a partir da oferta viva e do lexico de agora.

    O `nome_norm` e a `marca_canon` saem dos passos 1, 4 e 5 do §5.1 com o
    lexico do tenant (`normalizar_documento`), e a `norm_versao` gravada e a
    versao desse lexico: e o que o *worker* de reindexacao compara. Sem
    `lexico`, le-o da base, na transaccao do chamador; o *worker* passa-o, para
    nao o reler a cada documento de um lote, e a `oferta` ja lida (`None` se
    deixou de existir).
    """
    if oferta is _POR_LER:
        lidas = bd.executar(SQL_LER_OFERTA, (sku,)).linhas
        oferta = lidas[0] if lidas else None
    if oferta is None:
        bd.executar(SQL_ESCONDER_DOCUMENTO, (sku,))
        return
    if lexico is None:
        lexico = ler_lexico(bd, tenant_id, ler_versoes(bd).versao)
    bd.executar(
        SQL_ESCREVER_DOCUMENTO,
        (lexico.norm_versao, *_linha_do_documento(sku, oferta, lexico)),  # type: ignore[arg-type]
    )


def _linha_do_documento(
    sku: str, linha: Mapping[str, object], lexico: Lexico
) -> tuple[str, str, str | None, bool]:
    """`(product_ref, nome_norm, marca_canon, publicado)` de uma oferta viva."""
    documento = normalizar_documento(str(linha["nome"]), lexico)
    return (sku, documento.nome_norm, documento.marca_canon, bool(linha["publicado"]))


def efeito_do_produto(bd: ClienteSql, envelope: Mapping[str, object]) -> None:
    """`catalog.product_changed`: escreve o documento a partir da oferta viva."""
    escrever_documento(bd, envelope.get("tenant_id"), _sku(envelope))


#: Os documentos do tenant do contexto escritos antes da ultima alteracao do
#: lexico que afecta o indice (marca ou unidade), pela ordem do `doc_id`.
SQL_DESACTUALIZADOS: Final = """
  SELECT product_ref
    FROM idx.search_doc
   WHERE tenant_id = NULLIF(current_setting('app.tenant_id', true), '')::uuid
     AND visivel
     AND norm_versao < %s
   ORDER BY doc_id
   LIMIT %s
"""

#: Quantos documentos uma volta do *worker* reescreve. **Proposta**: uma
#: transaccao curta por lote, para nao segurar o indice do tenant.
LOTE_DE_REINDEXACAO: Final = 200


def reindexar(bd: ClienteSql, tenant_id: object, lote: int = LOTE_DE_REINDEXACAO) -> int:
    """Uma volta do *worker* (§4.4): reescreve ate `lote` documentos marcados.

    Marcado e o documento **visivel** com `norm_versao` abaixo da
    `versao_do_indice` — a ultima alteracao de marca ou unidade. Alterar um
    sinonimo nao sobe essa versao, e por isso nao marca nada (criterio 4). Um
    invisivel nao conta: nao aparece na pesquisa, e volta a ser escrito pelo
    `catalog.product_changed` que o publicar. E isso que faz a volta acabar —
    um documento cuja oferta desapareceu e escondido e deixa de ser marcado, em
    vez de voltar em cada volta. Corre na transaccao do
    chamador, com o contexto do tenant; devolve quantos reescreveu, e zero
    quer dizer que o tenant esta em dia. Quem a chama em ciclo, ate dar zero, e
    o processo de fundo.
    """
    versoes = ler_versoes(bd)
    marcados = consultar(bd, SQL_DESACTUALIZADOS, (versoes.versao_do_indice, int(lote)))
    if not marcados:
        return 0
    # Um lexico, uma leitura de ofertas e uma escrita por lote, na mesma
    # transaccao que as versoes — e lidos **depois** delas: um lexico que mude
    # entre as duas leituras grava uma versao abaixo do que aplicou, e o
    # documento volta a ser marcado (o lado seguro). Medido no *gate* 8: uma
    # instrucao por documento eram 472 s para 2 000 numa maquina carregada.
    lexico = ler_lexico(bd, tenant_id, versoes.versao)
    refs = [str(linha["product_ref"]) for linha in marcados]
    ofertas = {str(o["product_ref"]): o for o in consultar(bd, SQL_LER_OFERTAS, (refs,))}
    linhas: list[object] = []
    for ref in refs:
        oferta = ofertas.get(ref)
        if oferta is None:
            bd.executar(SQL_ESCONDER_DOCUMENTO, (ref,))
        else:
            linhas.extend(_linha_do_documento(ref, oferta, lexico))
    if linhas:
        bd.executar(
            sql_escrever_documentos(len(linhas) // 4), (lexico.norm_versao, *linhas)
        )
    return len(marcados)


def efeito_do_tenant(bd: ClienteSql, envelope: Mapping[str, object]) -> None:
    """`tenant.*`: rele o `visivel` de todos os documentos do tenant."""
    del envelope  # o tenant e o da transaccao; o resto do envelope nao serve
    bd.executar(SQL_RELER_TENANT)


def efeito(bd: ClienteSql, envelope: Mapping[str, object]) -> None:
    """O efeito pelo tipo do evento. Um tipo fora da lista levanta."""
    tipo = envelope.get("tipo")
    if tipo == PRODUTO_ALTERADO:
        efeito_do_produto(bd, envelope)
    elif tipo in EVENTOS_DO_TENANT:
        efeito_do_tenant(bd, envelope)
    else:
        raise TipoNaoSubscrito(f"o consumidor {CONSUMIDOR} nao subscreve {tipo!r}")


def consumir_evento(
    bd: ClienteSql,
    envelope: Mapping[str, object],
    metricas: Metricas | None = None,
) -> ResultadoDoConsumo:
    """Consome um evento uma so vez. Sem ordem exigida: ver a nota do modulo.

    `aplica_transicao = False` porque nenhum destes tipos esta no
    `ESTADO_PRETENDIDO`; fica escrito para que um tipo novo nessa tabela nao
    mude este consumidor em silencio.
    """
    if envelope.get("tipo") not in TIPOS:
        raise TipoNaoSubscrito(
            f"o consumidor {CONSUMIDOR} nao subscreve {envelope.get('tipo')!r}"
        )
    return consumir(
        OpcoesDoConsumo(
            bd=bd,
            consumer=CONSUMIDOR,
            envelope=envelope,
            exige_ordem=False,
            metricas=metricas,
            aplica_transicao=False,
        ),
        efeito,
    )
