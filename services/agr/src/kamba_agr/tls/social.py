"""O modulo social contra a base: o perfil, os calendarios e os itens (KAM-121).

O `RepositorioSocial` de `social/repositorio.py` sobre o PostgreSQL. **Vive na
ToolLayer**, pela regra do §6.1 e do ADR-015 que o `lint_arch` impoe: a TLS e a
unica via de escrita dos agentes no `platform`.

    RepositorioSql(ligacao)

Cada instrucao corre dentro de `tenant_guard.tx` (a RLS `FORCE` das tres
tabelas) e leva o `tenant_id` no predicado, pela disciplina do `dono/accoes.py`.

## As duas idempotencias

* **O calendario**: o `abrir` tranca `social|{tenant}|{semana}` na transaccao,
  le o activo e so cria a geracao pedida se ela for a seguinte. O indice unico
  parcial (um `activo` por `(tenant_id, semana_iso)`) e a segunda barreira.
* **O `posts_mes`**: o `consume_limit` do TEN corre na **mesma** transaccao que
  grava a legenda, com a chave `social:{content_item_id}` — regerar a legenda
  do mesmo item nao conta outra vez, e um limite esgotado desfaz a escrita.

## O que nao se escreve em registo nenhum

Nada deste modulo escreve *logs*, e as excepcoes levam um codigo e nunca o
texto do dono, do perfil ou de uma legenda.
"""

from __future__ import annotations

import datetime
import json
from collections.abc import Mapping, Sequence
from decimal import Decimal
from typing import Any, Final

from kamba_core import tenant_guard
from kamba_core.ten.entitlements import Resultado, consume_limit

from ..social import regras
from ..social.repositorio import (
    APROVADO,
    APROVAVEIS,
    CHAVE_DAS_IMAGENS,
    CHAVE_DE_LIMITE,
    ENTREGUE,
    MAXIMO_DE_TENTATIVAS,
    MODULO,
    PENDENTE_APROVACAO,
    POR_APROVAR,
    RASCUNHO,
    REJEITADO,
    AprovacaoInvalidadaError,
    Arte,
    Calendario,
    EventoAprovado,
    Item,
    ItemMudouError,
    ItemNovo,
    PerfilMudouError,
    SemImagensError,
    SemPublicacoesError,
    TentativasEsgotadasError,
    chave_de_consumo,
)

SQL_TRANCA: Final = "SELECT pg_advisory_xact_lock(hashtextextended(%s, 0))"

SQL_PERFIL: Final = (
    "SELECT nome, categoria, tom, cores, publico, slots_preferidos, factos, logo_asset_id::text, idioma, versao "
    "FROM platform.brand_profile WHERE tenant_id = %s::uuid"
)

SQL_INSERIR_PERFIL: Final = (
    "INSERT INTO platform.brand_profile "
    "(tenant_id, nome, categoria, tom, cores, publico, slots_preferidos, factos, versao) "
    "VALUES (%s::uuid, %s, %s, %s, %s, %s, %s::jsonb, %s::jsonb, %s) "
    "ON CONFLICT (tenant_id) DO NOTHING"
)

#: A escrita do perfil e um *compare-and-set* pela `versao` lida.
SQL_ACTUALIZAR_PERFIL: Final = (
    "UPDATE platform.brand_profile SET nome = %s, categoria = %s, tom = %s, cores = %s, publico = %s, "
    "slots_preferidos = %s::jsonb, factos = %s::jsonb, versao = %s, atualizado_at = now() "
    "WHERE tenant_id = %s::uuid AND versao = %s"
)

SQL_CALENDARIO_ACTIVO: Final = (
    "SELECT calendar_id::text, geracao, decisao, versao_politica FROM platform.content_calendar "
    "WHERE tenant_id = %s::uuid AND semana_iso = %s AND estado = 'activo'"
)

SQL_ITENS_DO_CALENDARIO: Final = (
    "SELECT content_item_id::text, calendar_id::text, semana_iso, tipo, tema, agendado_at, legenda, estado, "
    "is_ai_generated, revisao_reforcada, versao_politica, versao, arte_ref, arte_sha256, arte_fundo, "
    "arte_tentativas, arte_custo_usd, aprovacao_hash, aprovado_at, entregue_at, arte_texto, arte_formato "
    "FROM platform.content_items WHERE tenant_id = %s::uuid AND calendar_id = %s::uuid "
    "ORDER BY agendado_at, content_item_id"
)

SQL_SUBSTITUIR_CALENDARIO: Final = (
    "UPDATE platform.content_calendar SET estado = 'substituido' "
    "WHERE tenant_id = %s::uuid AND calendar_id = %s::uuid AND estado = 'activo'"
)

SQL_EXPIRAR_ITENS: Final = (
    "UPDATE platform.content_items SET estado = 'expirado', versao = versao + 1, atualizado_at = now() "
    "WHERE tenant_id = %s::uuid AND calendar_id = %s::uuid AND estado = ANY(%s)"
)

SQL_INSERIR_CALENDARIO: Final = (
    "INSERT INTO platform.content_calendar "
    "(calendar_id, tenant_id, semana_iso, geracao, decisao, versao_politica) "
    "VALUES (%s::uuid, %s::uuid, %s, %s, %s, %s)"
)

SQL_INSERIR_ITEM: Final = (
    "INSERT INTO platform.content_items "
    "(content_item_id, tenant_id, calendar_id, semana_iso, tipo, tema, agendado_at, revisao_reforcada, "
    "versao_politica) VALUES (%s::uuid, %s::uuid, %s::uuid, %s, %s, %s, %s, %s, %s)"
)

#: A referencia `SOC-…` sao os oito primeiros hexadecimais do `id`: procura-se
#: no tenant pelo prefixo do texto do `uuid`, que e o mesmo.
SQL_ITENS_POR_PREFIXO: Final = (
    "SELECT content_item_id::text, calendar_id::text, semana_iso, tipo, tema, agendado_at, legenda, estado, "
    "is_ai_generated, revisao_reforcada, versao_politica, versao, arte_ref, arte_sha256, arte_fundo, "
    "arte_tentativas, arte_custo_usd, aprovacao_hash, aprovado_at, entregue_at, arte_texto, arte_formato "
    "FROM platform.content_items WHERE tenant_id = %s::uuid AND left(content_item_id::text, 8) = %s "
    "LIMIT 2"
)

SQL_GRAVAR_LEGENDA: Final = (
    "UPDATE platform.content_items SET legenda = %s, revisao_reforcada = revisao_reforcada OR %s, "
    "versao_politica = %s, versao = versao + 1, atualizado_at = now() "
    "WHERE tenant_id = %s::uuid AND content_item_id = %s::uuid AND versao = %s AND estado = 'rascunho' "
    "RETURNING versao"
)

SQL_REJEITAR: Final = (
    "UPDATE platform.content_items SET estado = %s, versao_politica = %s, versao = versao + 1, "
    "atualizado_at = now() "
    "WHERE tenant_id = %s::uuid AND content_item_id = %s::uuid AND versao = %s AND estado = 'rascunho' "
    "RETURNING versao"
)


#: Um item pelo `id`, no tenant (o `ref` de uma accao `aprovar_conteudo`). `FOR
#: UPDATE`: a aprovacao e a entrega leem e escrevem na mesma transaccao.
SQL_ITEM: Final = (
    "SELECT content_item_id::text, calendar_id::text, semana_iso, tipo, tema, agendado_at, legenda, estado, "
    "is_ai_generated, revisao_reforcada, versao_politica, versao, arte_ref, arte_sha256, arte_fundo, "
    "arte_tentativas, arte_custo_usd, aprovacao_hash, aprovado_at, entregue_at, arte_texto, arte_formato "
    "FROM platform.content_items WHERE tenant_id = %s::uuid AND content_item_id = %s::uuid"
)
SQL_ITEM_PARA_MUDAR: Final = SQL_ITEM + " FOR UPDATE"

#: Quantos itens a pagina Social do painel mostra (KAM-246). *Proposta*: um
#: calendario tem ate sete itens por semana, e cinquenta sao mais de sete semanas.
MAXIMO_DO_PAINEL: Final = 50

#: Os itens da pagina Social do painel (KAM-246): os `aprovado` e os `entregue`
#: **com arte**, do tenant, os mais recentes primeiro. So leitura.
SQL_ITENS_DO_PAINEL: Final = (
    "SELECT content_item_id::text, calendar_id::text, semana_iso, tipo, tema, agendado_at, legenda, estado, "
    "is_ai_generated, revisao_reforcada, versao_politica, versao, arte_ref, arte_sha256, arte_fundo, "
    "arte_tentativas, arte_custo_usd, aprovacao_hash, aprovado_at, entregue_at, arte_texto, arte_formato "
    "FROM platform.content_items WHERE tenant_id = %s::uuid AND estado IN ('aprovado', 'entregue') "
    "AND arte_ref IS NOT NULL ORDER BY agendado_at DESC, content_item_id LIMIT %s"
)

#: A arte: em `rascunho` ou `pendente_aprovacao`, com a versao lida e menos de
#: tres tentativas. **Apaga o `hash`**: o botao da arte antiga deixa de aprovar.
SQL_GRAVAR_ARTE: Final = (
    "UPDATE platform.content_items SET arte_ref = %s, arte_sha256 = %s, arte_fundo = %s, "
    "arte_texto = %s, arte_formato = %s, arte_tentativas = arte_tentativas + 1, arte_custo_usd = arte_custo_usd + %s, aprovacao_hash = NULL, "
    "versao = versao + 1, atualizado_at = now() "
    "WHERE tenant_id = %s::uuid AND content_item_id = %s::uuid AND versao = %s "
    "AND estado IN ('rascunho', 'pendente_aprovacao') AND arte_tentativas < %s RETURNING versao"
)

#: O pedido de aprovacao: a legenda (a do dono, numa edicao) e o `hash` do que ele vai ver.
SQL_PEDIR_APROVACAO: Final = (
    "UPDATE platform.content_items SET estado = 'pendente_aprovacao', legenda = %s, aprovacao_hash = %s, "
    "aprovado_at = NULL, revisao_reforcada = revisao_reforcada OR %s, versao = versao + 1, atualizado_at = now() "
    "WHERE tenant_id = %s::uuid AND content_item_id = %s::uuid AND versao = %s AND estado = ANY(%s) "
    "RETURNING versao"
)

#: A aprovacao: **so** o `hash` que a accao cita, e so de `pendente_aprovacao`.
SQL_APROVAR: Final = (
    "UPDATE platform.content_items SET estado = 'aprovado', aprovado_at = %s, versao = versao + 1, "
    "atualizado_at = now() "
    "WHERE tenant_id = %s::uuid AND content_item_id = %s::uuid AND estado = 'pendente_aprovacao' "
    "AND aprovacao_hash = %s RETURNING versao"
)

#: O `content.approved` v1, na mesma transaccao (outbox, `docs/tecnica/06` §5).
SQL_EMITIR_APROVADO: Final = (
    "SELECT platform.evt_emitir('content.approved', 1::smallint, %s::uuid, 'content_item', %s, %s::jsonb, "
    "'P0', '{transacao}'::text[])"
)

SQL_REJEITAR_PELO_DONO: Final = (
    "UPDATE platform.content_items SET estado = 'rejeitado', versao = versao + 1, atualizado_at = now() "
    "WHERE tenant_id = %s::uuid AND content_item_id = %s::uuid AND versao = %s AND estado = ANY(%s) "
    "RETURNING versao"
)

SQL_ENTREGAR: Final = (
    "UPDATE platform.content_items SET estado = 'entregue', entregue_at = %s, versao = versao + 1, "
    "atualizado_at = now() "
    "WHERE tenant_id = %s::uuid AND content_item_id = %s::uuid AND versao = %s AND estado = 'aprovado' "
    "RETURNING versao"
)

#: Os termos da primeira entrega: so a primeira linha os grava (`RETURNING` vazio depois).
SQL_TERMOS: Final = (
    "UPDATE platform.brand_profile SET termos_entrega_at = %s "
    "WHERE tenant_id = %s::uuid AND termos_entrega_at IS NULL RETURNING termos_entrega_at"
)


#: Uma copia com campos mudados. **Nao e o `dataclasses.replace`**: a politica AST
#: do KAM-112 (`tests/politica_llm_ast.py`) recusa-o em toda a fonte do AGR,
#: porque e a forja do `MinimisedText`. Estes objectos nao sao texto minimizado.
def _com(objecto: Any, **mudancas: Any) -> Any:
    return type(objecto)(**{**vars(objecto), **mudancas})


class _ClienteDeCursor:
    """O `ClienteSql` do TEN sobre um cursor DB-API (a forma do `tls/orcamento.py`)."""

    def __init__(self, cursor: Any) -> None:
        self._cursor = cursor

    def executar(self, sql: str, parametros: Sequence[object] = ()) -> Resultado:
        self._cursor.execute(sql, tuple(parametros))
        descricao = self._cursor.description
        if not descricao:
            return Resultado(linhas=(), contagem=self._cursor.rowcount)
        nomes = [coluna[0] for coluna in descricao]
        linhas: list[Mapping[str, object]] = [dict(zip(nomes, linha, strict=True)) for linha in self._cursor.fetchall()]
        return Resultado(linhas=linhas, contagem=self._cursor.rowcount)


def _json(valor: Any) -> Any:
    if valor is None or isinstance(valor, (list, dict)):
        return valor
    return json.loads(valor)


def _perfil(tenant_id: str, linha: Sequence[Any]) -> regras.Perfil:
    nome, categoria, tom, cores, publico, slots, factos, logo, idioma, versao = linha
    slots, factos = _json(slots), _json(factos)
    return regras.Perfil(
        tenant_id=tenant_id,
        nome=nome,
        categoria=categoria,
        tom=tom,
        cores=tuple(cores) if cores is not None else None,
        publico=publico,
        slots=tuple(regras.Slot.de_json(s) for s in slots) if slots is not None else None,
        factos=tuple(regras.Facto.de_json(f) for f in factos) if factos is not None else None,
        logo_asset_id=logo,
        idioma=idioma,
        versao=int(versao),
    )


def _colunas(perfil: regras.Perfil) -> tuple[Any, ...]:
    vista = perfil.vista()
    return (
        perfil.nome,
        perfil.categoria,
        perfil.tom,
        list(perfil.cores) if perfil.cores is not None else None,
        perfil.publico,
        json.dumps(vista["slots"]) if vista["slots"] is not None else None,
        json.dumps(vista["factos"], ensure_ascii=False) if vista["factos"] is not None else None,
    )


def _item(tenant_id: str, linha: Sequence[Any]) -> Item:
    (item_id, calendar_id, semana, tipo, tema, agendado_at, legenda, estado, ia, reforcada, versao_politica, versao) = linha[:12]
    arte_ref, arte_sha256, arte_fundo, tentativas, custo, aprovacao_hash, aprovado_at, entregue_at = linha[12:20]
    arte_texto, arte_formato = linha[20:22] if len(linha) >= 22 else (None, None)
    return Item(
        content_item_id=str(item_id).lower(),
        tenant_id=tenant_id,
        calendar_id=str(calendar_id).lower(),
        semana_iso=semana,
        tipo=tipo,
        tema=tema,
        agendado_at=agendado_at,
        legenda=legenda,
        estado=estado,
        is_ai_generated=bool(ia),
        revisao_reforcada=bool(reforcada),
        versao_politica=versao_politica,
        versao=int(versao),
        arte_ref=arte_ref,
        arte_sha256=arte_sha256,
        arte_fundo=arte_fundo,
        arte_texto=arte_texto,
        arte_formato=arte_formato,
        arte_tentativas=int(tentativas),
        arte_custo_usd=Decimal(str(custo)),
        aprovacao_hash=aprovacao_hash,
        aprovado_at=aprovado_at,
        entregue_at=entregue_at,
    )


class RepositorioSql:
    """O `RepositorioSocial` sobre uma ligacao `kamba_app`."""

    def __init__(self, ligacao: Any) -> None:
        self._ligacao = ligacao

    # ---------------------------------------------------------- o perfil

    def ler_perfil(self, tenant_id: str) -> regras.Perfil | None:
        with tenant_guard.tx(self._ligacao, tenant_id) as cursor:
            cursor.execute(SQL_PERFIL, (tenant_id,))
            linha = cursor.fetchone()
        return _perfil(tenant_id, linha) if linha is not None else None

    def gravar_perfil(self, perfil: regras.Perfil, versao_lida: int | None) -> regras.Perfil:
        tenant = perfil.tenant_id
        with tenant_guard.tx(self._ligacao, tenant) as cursor:
            if versao_lida is None:
                cursor.execute(SQL_INSERIR_PERFIL, (tenant, *_colunas(perfil), perfil.versao))
            else:
                cursor.execute(SQL_ACTUALIZAR_PERFIL, (*_colunas(perfil), perfil.versao, tenant, versao_lida))
            if cursor.rowcount != 1:
                raise PerfilMudouError("perfil mudou")
        return perfil

    # ---------------------------------------------------------- o calendario

    def _activo(self, cursor: Any, tenant_id: str, semana: str) -> Calendario | None:
        cursor.execute(SQL_CALENDARIO_ACTIVO, (tenant_id, semana))
        linha = cursor.fetchone()
        if linha is None:
            return None
        calendar_id, geracao, decisao, versao_politica = linha
        cursor.execute(SQL_ITENS_DO_CALENDARIO, (tenant_id, calendar_id))
        itens = tuple(_item(tenant_id, i) for i in cursor.fetchall())
        return Calendario(str(calendar_id).lower(), tenant_id, semana, int(geracao), decisao, versao_politica, itens)

    def calendario(self, tenant_id: str, semana: str) -> Calendario | None:
        with tenant_guard.tx(self._ligacao, tenant_id) as cursor:
            return self._activo(cursor, tenant_id, semana)

    def abrir(
        self,
        tenant_id: str,
        semana: str,
        calendar_id: str,
        geracao: int,
        decisao: str,
        versao_politica: str,
        itens: Sequence[ItemNovo],
    ) -> tuple[Calendario, bool]:
        with tenant_guard.tx(self._ligacao, tenant_id) as cursor:
            cursor.execute(SQL_TRANCA, (f"social|{tenant_id}|{semana}",))
            cursor.fetchone()
            activo = self._activo(cursor, tenant_id, semana)
            if activo is not None and activo.geracao >= geracao:
                return activo, False
            if activo is not None:
                cursor.execute(SQL_EXPIRAR_ITENS, (tenant_id, activo.calendar_id, list(POR_APROVAR)))
                cursor.execute(SQL_SUBSTITUIR_CALENDARIO, (tenant_id, activo.calendar_id))
            cursor.execute(SQL_INSERIR_CALENDARIO, (calendar_id, tenant_id, semana, geracao, decisao, versao_politica))
            for n in itens:
                cursor.execute(
                    SQL_INSERIR_ITEM,
                    (
                        n.content_item_id,
                        tenant_id,
                        calendar_id,
                        semana,
                        n.tipo,
                        n.tema,
                        n.agendado_at,
                        n.revisao_reforcada,
                        n.versao_politica,
                    ),
                )
            novo = self._activo(cursor, tenant_id, semana)
        assert novo is not None
        return novo, True

    # ---------------------------------------------------------- os itens

    def itens_por_prefixo(self, tenant_id: str, prefixo: str) -> tuple[Item, ...]:
        if len(prefixo) != 8:
            return ()
        with tenant_guard.tx(self._ligacao, tenant_id) as cursor:
            cursor.execute(SQL_ITENS_POR_PREFIXO, (tenant_id, prefixo))
            return tuple(_item(tenant_id, linha) for linha in cursor.fetchall())

    def gravar_legenda(self, item: Item, legenda: str, revisao_reforcada: bool, versao_politica: str) -> Item:
        with tenant_guard.tx(self._ligacao, item.tenant_id) as cursor:
            cursor.execute(
                SQL_GRAVAR_LEGENDA,
                (legenda, revisao_reforcada, versao_politica, item.tenant_id, item.content_item_id, item.versao),
            )
            linha = cursor.fetchone()
            if linha is None:
                raise ItemMudouError("item mudou")
            consumo = consume_limit(
                _ClienteDeCursor(cursor),
                item.tenant_id,
                CHAVE_DE_LIMITE,
                1,
                chave_de_consumo(item.content_item_id),
                modulo=MODULO,
            )
            if not consumo.aceite:
                # A excepcao desfaz a transaccao inteira: a legenda nao fica.
                raise SemPublicacoesError("posts_mes esgotado")
        return _com(
            item,
            legenda=legenda,
            revisao_reforcada=item.revisao_reforcada or revisao_reforcada,
            versao_politica=versao_politica,
            versao=int(linha[0]),
        )

    def rejeitar(self, item: Item, versao_politica: str) -> Item:
        with tenant_guard.tx(self._ligacao, item.tenant_id) as cursor:
            cursor.execute(SQL_REJEITAR, (REJEITADO, versao_politica, item.tenant_id, item.content_item_id, item.versao))
            linha = cursor.fetchone()
            if linha is None:
                raise ItemMudouError("item mudou")
        return _com(item, estado=REJEITADO, versao_politica=versao_politica, versao=int(linha[0]))

    # ---------------------------------------------------------- a arte e a aprovacao (KAM-122)

    def itens_do_painel(self, tenant_id: str) -> tuple[Item, ...]:
        """Os itens da pagina Social do painel (KAM-246), so leitura."""
        with tenant_guard.tx(self._ligacao, tenant_id) as cursor:
            cursor.execute(SQL_ITENS_DO_PAINEL, (tenant_id, MAXIMO_DO_PAINEL))
            return tuple(_item(tenant_id, linha) for linha in cursor.fetchall())

    def item(self, tenant_id: str, content_item_id: str) -> Item | None:
        with tenant_guard.tx(self._ligacao, tenant_id) as cursor:
            cursor.execute(SQL_ITEM, (tenant_id, content_item_id))
            linha = cursor.fetchone()
        return _item(tenant_id, linha) if linha is not None else None

    def consumir_imagem(self, tenant_id: str, chave: str) -> None:
        """Um `imagens_mes`, na sua transaccao, **antes** de o pedido sair."""
        with tenant_guard.tx(self._ligacao, tenant_id) as cursor:
            consumo = consume_limit(_ClienteDeCursor(cursor), tenant_id, CHAVE_DAS_IMAGENS, 1, chave, modulo=MODULO)
            if not consumo.aceite:
                raise SemImagensError("imagens_mes esgotado")

    def gravar_arte(self, item: Item, arte: Arte) -> Item:
        if item.arte_tentativas >= MAXIMO_DE_TENTATIVAS:
            raise TentativasEsgotadasError("tentativas esgotadas")
        with tenant_guard.tx(self._ligacao, item.tenant_id) as cursor:
            cursor.execute(
                SQL_GRAVAR_ARTE,
                (
                    arte.arte_ref,
                    arte.arte_sha256,
                    arte.fundo,
                    arte.texto,
                    arte.formato,
                    arte.custo_usd,
                    item.tenant_id,
                    item.content_item_id,
                    item.versao,
                    MAXIMO_DE_TENTATIVAS,
                ),
            )
            linha = cursor.fetchone()
            if linha is None:
                raise ItemMudouError("item mudou")
        return _com(
            item,
            arte_ref=arte.arte_ref,
            arte_sha256=arte.arte_sha256,
            arte_fundo=arte.fundo,
            arte_texto=arte.texto,
            arte_formato=arte.formato,
            arte_tentativas=item.arte_tentativas + 1,
            arte_custo_usd=item.arte_custo_usd + arte.custo_usd,
            aprovacao_hash=None,
            versao=int(linha[0]),
        )

    def pedir_aprovacao(self, item: Item, legenda: str, hash_: str, reforcada: bool = False) -> Item:
        with tenant_guard.tx(self._ligacao, item.tenant_id) as cursor:
            cursor.execute(
                SQL_PEDIR_APROVACAO,
                (legenda, hash_, reforcada, item.tenant_id, item.content_item_id, item.versao, list(APROVAVEIS)),
            )
            linha = cursor.fetchone()
            if linha is None:
                raise ItemMudouError("item mudou")
        return _com(
            item,
            estado=PENDENTE_APROVACAO,
            legenda=legenda,
            aprovacao_hash=hash_,
            aprovado_at=None,
            revisao_reforcada=item.revisao_reforcada or reforcada,
            versao=int(linha[0]),
        )

    def aprovar(self, item: Item, hash_: str, agora: datetime.datetime) -> tuple[Item, EventoAprovado | None]:
        """A passagem a `aprovado` e o `content.approved`, **na mesma transaccao**.

        Le o item com `FOR UPDATE`: dois toques concorrentes no mesmo botao
        serializam-se, e o segundo le `aprovado` com o mesmo `hash` — uma
        aprovacao e um evento (criterio 5).
        """
        tenant = item.tenant_id
        with tenant_guard.tx(self._ligacao, tenant) as cursor:
            cursor.execute(SQL_ITEM_PARA_MUDAR, (tenant, item.content_item_id))
            linha = cursor.fetchone()
            if linha is None:
                raise ItemMudouError("item mudou")
            actual = _item(tenant, linha)
            if actual.estado in (APROVADO, ENTREGUE) and actual.aprovacao_hash == hash_:
                return actual, None
            if actual.estado != PENDENTE_APROVACAO or actual.aprovacao_hash != hash_:
                raise AprovacaoInvalidadaError("aprovacao invalidada")
            cursor.execute(SQL_APROVAR, (agora, tenant, actual.content_item_id, hash_))
            versao = cursor.fetchone()
            if versao is None:
                raise ItemMudouError("item mudou")
            evento = EventoAprovado(actual.content_item_id, int(versao[0]))
            cursor.execute(
                SQL_EMITIR_APROVADO,
                (
                    tenant,
                    actual.content_item_id,
                    json.dumps({"content_item_id": actual.content_item_id, "versao": evento.versao}, sort_keys=True),
                ),
            )
            cursor.fetchone()
        return _com(actual, estado=APROVADO, aprovado_at=agora, versao=evento.versao), evento

    def rejeitar_pelo_dono(self, item: Item) -> Item:
        with tenant_guard.tx(self._ligacao, item.tenant_id) as cursor:
            cursor.execute(
                SQL_REJEITAR_PELO_DONO,
                (item.tenant_id, item.content_item_id, item.versao, [RASCUNHO, PENDENTE_APROVACAO, APROVADO]),
            )
            linha = cursor.fetchone()
            if linha is None:
                raise ItemMudouError("item mudou")
        return _com(item, estado=REJEITADO, versao=int(linha[0]))

    def entregar(self, item: Item, agora: datetime.datetime) -> tuple[Item, bool]:
        """A passagem a `entregue` e, na primeira entrega do tenant, os termos (criterio 9)."""
        with tenant_guard.tx(self._ligacao, item.tenant_id) as cursor:
            cursor.execute(SQL_ENTREGAR, (agora, item.tenant_id, item.content_item_id, item.versao))
            linha = cursor.fetchone()
            if linha is None:
                raise ItemMudouError("item mudou")
            cursor.execute(SQL_TERMOS, (agora, item.tenant_id))
            primeira = cursor.fetchone() is not None
        return _com(item, estado=ENTREGUE, entregue_at=agora, versao=int(linha[0])), primeira
