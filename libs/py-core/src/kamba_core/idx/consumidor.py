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
  mede; o efeito e a transaccao sim, e estao medidos contra um PostgreSQL.
* `marca_canon`, `categoria_canon` e `descr_norm`: o `platform.offer_terms` so
  tem `nome`, e o lexico de marcas e o KAM-062. Ficam nulos e vazio.
* O embedding (KAM-063). O documento nasce sem ele, que e o modo lexical.
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

from .texto import normalizar

#: O nome do consumidor em `platform.events_consumed`. A chave de idempotencia e
#: `(consumer, event_id)`: mudar este nome reprocessa tudo.
CONSUMIDOR: Final = "idx"

#: A versao do dicionario PT-AO aplicada ao `nome_norm`. **1** enquanto nao
#: houver dicionario (KAM-062): e so o passo 1 do §5.1.
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

#: Escreve ou reescreve o documento. O `visivel` junta o tenant `ativo` ao
#: `publicado` da oferta; o `SELECT` sobre `platform.tenants` le **so** o tenant
#: do contexto (RLS por `id`), e sem ele nao escreve nada.
SQL_ESCREVER_DOCUMENTO: Final = """
  INSERT INTO idx.search_doc (tenant_id, product_ref, norm_versao, nome_norm, visivel)
  SELECT t.id, %s, %s, %s, (%s AND t.estado = 'ativo')
    FROM platform.tenants t
   WHERE t.id = NULLIF(current_setting('app.tenant_id', true), '')::uuid
  ON CONFLICT (tenant_id, product_ref) DO UPDATE
     SET norm_versao   = EXCLUDED.norm_versao,
         nome_norm     = EXCLUDED.nome_norm,
         visivel       = EXCLUDED.visivel,
         atualizado_at = now()
"""

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


def efeito_do_produto(bd: ClienteSql, envelope: Mapping[str, object]) -> None:
    """`catalog.product_changed`: escreve o documento a partir da oferta viva."""
    sku = _sku(envelope)
    oferta = bd.executar(SQL_LER_OFERTA, (sku,)).linhas
    if not oferta:
        bd.executar(SQL_ESCONDER_DOCUMENTO, (sku,))
        return
    linha = oferta[0]
    bd.executar(
        SQL_ESCREVER_DOCUMENTO,
        (sku, NORM_VERSAO, normalizar(str(linha["nome"])), bool(linha["publicado"])),
    )


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
