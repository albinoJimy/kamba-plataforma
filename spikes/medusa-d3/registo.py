"""`CommerceRegistry` minima do spike — a porta do §3.2, so o que se mede.

O contrato completo tem onze metodos e e o KAM-042. O spike implementa os que
os criterios do KAM-041 interrogam, e implementa-os **na forma da opcao B**:
um unico Registo, com `tenant_id`/`merchant_id` injectado em toda a leitura e
escrita pelo adaptador, e nunca pelo chamador.

As quatro regras da porta (§3.2) estao aqui porque sao exactamente o que a
matriz ISO ataca:

1. toda a chamada recebe `ctx`; **sem `ctx.tenant_id` falha fechada** (ISO-09);
2. `create_order` e idempotente por `(tenant_id, intent_key)` (AC-4);
3. `transition` usa concorrencia optimista por `version` e so aceita as
   transicoes do §6.2 (o gatilho do `03_grafo.sql` e a segunda barreira);
4. **nenhuma operacao aceita um preco do chamador**: o preco vem de
   `offer_terms` (ISO-57..60 ataca exactamente isto).

O que o spike **nao** implementa, e diz: o ciclo completo da saga com PAY, o
`price_quote` do dono, e a projeccao para o Medusa de tudo o que nao seja a
encomenda. Nada disso e medido por um AC do KAM-041.
"""

from __future__ import annotations

import base64
import dataclasses
import hashlib
import hmac
import json
import secrets
import time
import uuid

import ligacao

#: Segredo das `intent_key`. Gerado por execucao: a chave e
#: `HMAC(segredo, tenant || contact || draft_id || draft_version)` (§6.3), e o
#: segredo nao e dado nenhum que valha a pena guardar entre medicoes.
_SEGREDO_INTENTS = secrets.token_bytes(32)

#: Base32 sem ambiguos para o `numero_publico` (§5.4: «curto, base32 sem
#: ambiguos»). Sem `I`, `L`, `O`, `U`, `0` e `1`.
_ALFABETO_PUBLICO = "23456789ABCDEFGHJKMNPQRSTVWXYZ"


class PoliticaRecusada(Exception):
    """A porta recusou: contexto em falta, id de outro tenant, estado errado.

    Uma unica excepcao para todas as recusas, de proposito: a matriz ISO
    pergunta «devolveu dados?», e qualquer recusa e a resposta certa. Distinguir
    404 de 403 e informacao que se da ao chamador legitimo, nao ao teste.
    """


class IntentReutilizadaComOutroConteudo(Exception):
    """§6.3 passo 2: a mesma `intent_key` com outro `draft_hash`."""


class ConflitoDeVersao(Exception):
    """CAS falhou. §6.2: «reler e reavaliar (nunca forcar)»."""


class PagamentoEncontradoNaConsultaFinal(Exception):
    """§6.5: ha pagamento no PAY, logo a reserva **nao** se liberta.

    Nao e um erro: e a guarda a funcionar. Separa-se de `PoliticaRecusada`
    para que quem mede o AC-6 possa distinguir «a porta recusou libertar
    porque a encomenda esta paga» de «a porta recusou por outra razao».
    """


@dataclasses.dataclass(frozen=True)
class Ctx:
    """`ctx` do §3.2. **Vem sempre do estado da sessao, nunca do texto.**"""

    tenant_id: str | None
    actor_kind: str = "agente"
    actor_id: str = "spike"
    trace_id: str = "spike-kam-041"


@dataclasses.dataclass(frozen=True)
class Linha:
    sku: str
    qty: int


def intent_key(ctx: Ctx, contact_id: str, draft_id: str, draft_version: int) -> str:
    """§6.3: `base32(HMAC-SHA256(segredo, tenant || contact || draft || versao))[:26]`."""
    mensagem = f"{ctx.tenant_id}|{contact_id}|{draft_id}|{draft_version}".encode()
    assinatura = hmac.new(_SEGREDO_INTENTS, mensagem, hashlib.sha256).digest()
    return base64.b32encode(assinatura).decode("ascii")[:26]


def draft_hash(linhas: list[Linha], entrega_modo: str) -> bytes:
    """§6.3: `SHA-256(linhas canonicalizadas || entrega_modo)`."""
    canonico = json.dumps(
        [{"sku": l.sku, "qty": l.qty} for l in sorted(linhas, key=lambda l: l.sku)],
        separators=(",", ":"), sort_keys=True,
    )
    return hashlib.sha256((canonico + "|" + entrega_modo).encode()).digest()


class Registo:
    """A porta. Uma instancia por medicao; abre uma ligacao por operacao.

    Uma ligacao por operacao e de proposito: `SET LOCAL app.tenant_id` vive numa
    transaccao, e uma porta que reutilizasse ligacoes podia deixar o contexto de
    um tenant a valer para a chamada seguinte — que e precisamente o defeito que
    o ISO-09 procura.
    """

    def __init__(self, ambiente: dict[str, str], medusa=None,
                 consultar_pay=None) -> None:
        self._ambiente = ambiente
        self.medusa = medusa
        #: `(ctx, order_id) -> bool`: o PAY tem pagamento para esta encomenda?
        #: O PAY e o EPIC-05 e nao existe aqui; o spike injecta um que responde
        #: por uma lista conhecida. O que importa e que a **guarda** do §6.5
        #: esteja na porta, e nao em quem a chama.
        self.consultar_pay = consultar_pay

    def aquecer(self, ctx: Ctx) -> None:
        """Paga o custo de abrir e autenticar uma ligacao, e fecha-a.

        Serve a `concorrencia.tempestade`: corre antes da barreira para que o
        que se sincroniza seja o ponto critico e nao o `connect`. Nao guarda a
        ligacao — a porta abre uma por operacao de proposito (ver `_abrir`) —
        mas deixa quente o que e caro do lado do servidor (processo do
        *backend*, cache de autenticacao) e do lado do cliente (resolucao,
        importacao do `pg8000`).
        """
        try:
            conexao, _ = self._abrir(ctx)
            conexao.close()
        except Exception:  # noqa: BLE001 — aquecer e melhoria, nao requisito
            pass

    # ------------------------------------------------------------- contexto

    def _abrir(self, ctx: Ctx, identidade: str = "app"):
        """Ligacao com o contexto posto. Regra 1: sem `tenant_id`, falha fechada.

        A guarda e **da porta**, antes de a base ser tocada. A RLS e a segunda
        barreira (§5.5) e o ISO-39..42 mede-a a parte, precisamente para que um
        verde aqui nao se confunda com um verde da base.
        """
        if not ctx.tenant_id:
            raise PoliticaRecusada("ctx sem tenant_id: a porta falha fechada (§3.2)")
        try:
            uuid.UUID(str(ctx.tenant_id))
        except (ValueError, AttributeError, TypeError):
            raise PoliticaRecusada(f"ctx.tenant_id nao e um uuid: {ctx.tenant_id!r}")
        conexao = ligacao.ligar(identidade, self._ambiente)
        cursor = conexao.cursor()
        cursor.execute("SELECT set_config('app.tenant_id', %s, true)", (str(ctx.tenant_id),))
        cursor.fetchone()
        return conexao, cursor

    # -------------------------------------------------------------- catalogo

    def get_offer_view(self, ctx: Ctx, sku: str) -> dict:
        """§3.2: `{precoTipo, precoDisplay, stockModo, disponibilidade, atualizadoAt}`.

        Nunca devolve o numero do stock: o §7.3 e o ADR-007 querem
        *disponibilidade*, nao quantidade. Devolver a quantidade era dar ao
        agente um numero que ele depois cita.
        """
        conexao, cursor = self._abrir(ctx)
        try:
            cursor.execute(
                "SELECT preco_tipo, preco_minor, currency, stock_modo, estado, "
                "       preco_atualizado_at "
                "  FROM platform.offer_terms "
                " WHERE tenant_id = %s AND sku = %s AND deleted_at IS NULL",
                (str(ctx.tenant_id), sku),
            )
            linha = cursor.fetchone()
            if linha is None:
                raise PoliticaRecusada(f"sku {sku!r} nao existe neste tenant")
            modo, minor, moeda, stock_modo, estado, atualizado = linha
            if estado != "publicado":
                raise PoliticaRecusada(f"sku {sku!r} nao esta publicado ({estado})")
            cursor.execute(
                "SELECT quantidade - reservada FROM platform.spike_stock_levels "
                " WHERE tenant_id = %s AND sku = %s",
                (str(ctx.tenant_id), sku),
            )
            disponivel = cursor.fetchone()
            return {
                "sku": sku,
                "precoTipo": modo,
                "precoDisplay": None if minor is None else f"{minor} {moeda}",
                "stockModo": stock_modo,
                "disponibilidade": bool(disponivel and disponivel[0] > 0),
                "atualizadoAt": atualizado.isoformat() if atualizado else None,
            }
        finally:
            conexao.close()

    def publish_product(self, ctx: Ctx, sku: str, confirmacao_do_dono: bool) -> None:
        """§3.2: «exige confirmacao do dono». Sem ela, recusa."""
        if not confirmacao_do_dono:
            raise PoliticaRecusada("publish_product exige OwnerConfirmation")
        conexao, cursor = self._abrir(ctx)
        try:
            cursor.execute(
                "UPDATE platform.offer_terms SET estado = 'publicado' "
                " WHERE tenant_id = %s AND sku = %s AND deleted_at IS NULL",
                (str(ctx.tenant_id), sku),
            )
            if cursor.rowcount == 0:
                raise PoliticaRecusada(f"sku {sku!r} nao existe neste tenant")
            conexao.commit()
        finally:
            conexao.close()

    # ------------------------------------------------------------ encomendas

    def create_order(
        self, ctx: Ctx, contact_id: str, linhas: list[Linha],
        chave: str, entrega_modo: str = "levantamento",
    ) -> dict:
        """§6.3, pelos quatro passos, e nenhum deles opcional.

        **O preco nao entra como argumento.** Resolve-se de `offer_terms` dentro
        desta transaccao; um chamador que queira ditar o total nao tem por onde.
        """
        esperado = draft_hash(linhas, entrega_modo)
        conexao, cursor = self._abrir(ctx)
        try:
            # Passo 1: recibo de idempotencia.
            cursor.execute(
                "INSERT INTO platform.order_intents (tenant_id, intent_key, draft_hash) "
                "VALUES (%s, %s, %s) ON CONFLICT (tenant_id, intent_key) DO NOTHING "
                "RETURNING intent_key",
                (str(ctx.tenant_id), chave, esperado),
            )
            inseriu = cursor.fetchone() is not None

            if not inseriu:
                # Passo 2: ja existe. **Mesma resposta para N toques** — e e por
                # isso que ha espera. O §6.3 diz «devolver a encomenda existente
                # (`concluida`) ou aguardar `em_curso` (poll <= 3 s)»: sem a
                # espera, as 49 repeticoes concorrentes do AC-4 que perdem a
                # corrida liam `em_curso` com `order_id` NULL e devolviam uma
                # resposta diferente da do vencedor — que e exactamente o
                # defeito que a idempotencia existe para nao ter.
                conexao.commit()  # larga a transaccao: o vencedor tem de poder confirmar
                limite = time.monotonic() + 3.0
                while True:
                    # **O contexto repoe-se a cada volta, e nao e zelo.**
                    # `set_config(..., true)` e `SET LOCAL`: vive na
                    # transaccao. O `commit` acima fecha-a e leva o contexto
                    # com ela; sem isto, o `SELECT` seguinte corre sem
                    # `app.tenant_id`, a politica `tenant_iso` devolve zero
                    # linhas, e o `fetchone()` devolve `None` — a RLS a falhar
                    # fechada, exactamente como o §5.5 promete, sobre a nossa
                    # propria consulta.
                    cursor.execute(
                        "SELECT set_config('app.tenant_id', %s, true)",
                        (str(ctx.tenant_id),),
                    )
                    cursor.fetchone()
                    cursor.execute(
                        "SELECT draft_hash, estado, order_id "
                        "  FROM platform.order_intents "
                        " WHERE tenant_id = %s AND intent_key = %s",
                        (str(ctx.tenant_id), chave),
                    )
                    linha = cursor.fetchone()
                    if linha is None:
                        # A intencao existia no `ON CONFLICT` e agora nao se ve:
                        # ou a reconciliacao a apagou (§6.3 passo 4), ou o
                        # contexto nao esta posto. Nao se inventa resposta.
                        conexao.commit()
                        raise PoliticaRecusada(
                            f"a intencao {chave} deixou de ser visivel neste "
                            "contexto a meio da espera"
                        )
                    guardado, estado, order_id = linha
                    conexao.commit()
                    if bytes(guardado) != esperado:
                        raise IntentReutilizadaComOutroConteudo(
                            "INTENT_REUSED_WITH_DIFFERENT_CONTENT"
                        )
                    if estado == "concluida" and order_id is not None:
                        return {"order_id": order_id, "intent_key": chave,
                                "criada_agora": False}
                    if estado == "falhada":
                        raise PoliticaRecusada(
                            f"a intencao {chave} esta `falhada`; a reconciliacao "
                            "do §10.3 retoma-a"
                        )
                    if time.monotonic() >= limite:
                        # Nao se inventa uma resposta. O §6.3 da 3 s; passados
                        # os 3 s quem chama tem de voltar a perguntar.
                        raise PoliticaRecusada(
                            f"a intencao {chave} continua `em_curso` depois de 3 s"
                        )
                    time.sleep(0.02)

            # Passo 3: a saga, numa transaccao — espelho, log e outbox juntos.
            total = 0
            instantaneo = []
            for linha in linhas:
                cursor.execute(
                    "SELECT preco_tipo, preco_minor, currency, estado "
                    "  FROM platform.offer_terms "
                    " WHERE tenant_id = %s AND sku = %s AND deleted_at IS NULL",
                    (str(ctx.tenant_id), linha.sku),
                )
                oferta = cursor.fetchone()
                if oferta is None or oferta[3] != "publicado":
                    raise PoliticaRecusada(
                        f"sku {linha.sku!r} nao existe ou nao esta publicado neste tenant"
                    )
                modo, minor, moeda, _ = oferta
                if modo == "sob_consulta":
                    raise PoliticaRecusada(
                        f"sku {linha.sku!r} e `sob_consulta`: exige `price_quote` do dono (§7.2)"
                    )
                total += int(minor) * linha.qty
                instantaneo.append(
                    {"sku": linha.sku, "qty": linha.qty, "preco_minor": int(minor),
                     "preco_tipo": modo, "origem_preco": "offer_terms"}
                )

            publico = "".join(secrets.choice(_ALFABETO_PUBLICO) for _ in range(6))
            cursor.execute(
                "INSERT INTO platform.orders_mirror "
                "  (tenant_id, contact_id, origem, numero_publico, intent_key, "
                "   estado, total_minor, currency, lines_snapshot, entrega_modo) "
                "VALUES (%s, %s, 'plataforma', %s, %s, 'criada', %s, 'AOA', %s, %s) "
                "RETURNING id",
                (str(ctx.tenant_id), contact_id, publico, chave, total,
                 json.dumps(instantaneo), entrega_modo),
            )
            order_id = cursor.fetchone()[0]

            cursor.execute(
                "INSERT INTO platform.order_state_log "
                "  (tenant_id, order_id, de, para, causa, actor_kind, actor_id) "
                "VALUES (%s, %s, '', 'criada', 'create_order', %s, %s)",
                (str(ctx.tenant_id), order_id, ctx.actor_kind, ctx.actor_id),
            )
            self._emitir(cursor, ctx, "order.created", "order", str(order_id),
                         {"order_id": str(order_id), "total_minor": total,
                          "currency": "AOA", "numero_publico": publico})
            cursor.execute(
                "UPDATE platform.order_intents SET estado = 'concluida', order_id = %s "
                " WHERE tenant_id = %s AND intent_key = %s",
                (order_id, str(ctx.tenant_id), chave),
            )
            conexao.commit()
            return {"order_id": order_id, "intent_key": chave, "criada_agora": True,
                    "total_minor": total, "numero_publico": publico}
        except Exception:
            conexao.rollback()
            raise
        finally:
            conexao.close()

    def _emitir(self, cursor, ctx: Ctx, tipo: str, agregado: str, agregado_id: str,
                payload: dict) -> str:
        """`events_outbox` na **mesma transaccao** (§6.2, ADR-009).

        Pela funcao `evt_emitir` e **nao** por `INSERT`: o `kamba_app` nao tem
        `INSERT` nesta tabela (ver `ddl/04_outbox.sql`). Quem emite da o payload;
        o envelope e montado pela funcao. A primeira execucao do spike fazia o
        `INSERT` directo, e o ISO-46 apanhou o que isso permitia — um envelope a
        dizer um tenant e a coluna a dizer outro.
        """
        cursor.execute(
            "SELECT platform.evt_emitir(%s, 1::smallint, %s, %s, %s, %s::jsonb, %s)",
            (tipo, str(ctx.tenant_id), agregado, agregado_id,
             json.dumps(payload), ctx.trace_id),
        )
        return str(cursor.fetchone()[0])

    def get_order(self, ctx: Ctx, order_id: str) -> dict:
        conexao, cursor = self._abrir(ctx)
        try:
            cursor.execute(
                "SELECT id, estado, total_minor, currency, numero_publico, version, "
                "       lines_snapshot "
                "  FROM platform.orders_mirror "
                " WHERE tenant_id = %s AND id = %s AND deleted_at IS NULL",
                (str(ctx.tenant_id), order_id),
            )
            linha = cursor.fetchone()
            if linha is None:
                raise PoliticaRecusada(f"encomenda {order_id} nao existe neste tenant")
            return {
                "id": str(linha[0]), "estado": linha[1], "total_minor": linha[2],
                "currency": linha[3], "numero_publico": linha[4], "version": linha[5],
                "lines_snapshot": linha[6],
            }
        finally:
            conexao.close()

    def list_orders(self, ctx: Ctx, estado: str | None = None,
                    filtro_bruto: str | None = None) -> list[dict]:
        """`filtro_bruto` existe para o ISO-10: um filtro vindo do chamador.

        Vai como **parametro**, nunca concatenado. O ISO-10 tenta `' OR 1=1 --`
        e um cursor forjado; a resposta certa e «so linhas de A», e e o uso de
        parametro que a da.
        """
        conexao, cursor = self._abrir(ctx)
        try:
            sql = ("SELECT id, estado, total_minor FROM platform.orders_mirror "
                   " WHERE tenant_id = %s AND deleted_at IS NULL")
            parametros: list = [str(ctx.tenant_id)]
            if estado is not None:
                sql += " AND estado = %s"
                parametros.append(estado)
            if filtro_bruto is not None:
                sql += " AND numero_publico = %s"
                parametros.append(filtro_bruto)
            sql += " ORDER BY criado_at DESC"
            cursor.execute(sql, tuple(parametros))
            return [{"id": str(l[0]), "estado": l[1], "total_minor": l[2]}
                    for l in cursor.fetchall()]
        finally:
            conexao.close()

    def transition(self, ctx: Ctx, order_id: str, para: str, versao_esperada: int,
                   causa: str, evento_id: str | None = None,
                   paga_via: str | None = None) -> dict:
        """§6.2: `UPDATE ... WHERE id=$1 AND version=$2 AND estado=$de`, CAS.

        O estado de partida nao vem do chamador: le-se na mesma transaccao. Um
        chamador que o pudesse dizer podia pedir uma transicao que o grafo
        permite a partir de um estado em que a encomenda nao esta.
        """
        conexao, cursor = self._abrir(ctx)
        try:
            cursor.execute(
                "SELECT estado FROM platform.orders_mirror "
                " WHERE tenant_id = %s AND id = %s AND deleted_at IS NULL",
                (str(ctx.tenant_id), order_id),
            )
            actual = cursor.fetchone()
            if actual is None:
                raise PoliticaRecusada(f"encomenda {order_id} nao existe neste tenant")
            de = actual[0]
            if para == "paga" and not paga_via:
                raise PoliticaRecusada(
                    "transicao para `paga` exige `paga_via` (evento autenticado "
                    "ou confirmacao manual auditada)"
                )
            cursor.execute(
                "UPDATE platform.orders_mirror "
                "   SET estado = %s, version = version + 1, atualizado_at = now(), "
                "       paga_via = coalesce(%s, paga_via), "
                "       paga_at = CASE WHEN %s = 'paga' THEN now() ELSE paga_at END "
                " WHERE tenant_id = %s AND id = %s AND version = %s AND estado = %s "
                "RETURNING version",
                (para, paga_via, para, str(ctx.tenant_id), order_id, versao_esperada, de),
            )
            devolvido = cursor.fetchone()
            if devolvido is None:
                conexao.rollback()
                raise ConflitoDeVersao(
                    f"CAS falhou em {order_id}: versao esperada {versao_esperada}"
                )
            cursor.execute(
                "INSERT INTO platform.order_state_log "
                "  (tenant_id, order_id, de, para, causa, evento_id, actor_kind, actor_id) "
                "VALUES (%s, %s, %s, %s, %s, %s, %s, %s)",
                (str(ctx.tenant_id), order_id, de, para, causa, evento_id,
                 ctx.actor_kind, ctx.actor_id),
            )
            conexao.commit()
            return {"id": order_id, "de": de, "para": para, "version": devolvido[0]}
        except Exception:
            conexao.rollback()
            raise
        finally:
            conexao.close()

    # --------------------------------------------------------------- reservas

    def reserve_stock(self, ctx: Ctx, order_id: str, ttl_segundos: int,
                      motor: str = "sql") -> list[dict]:
        """Tudo-ou-nada por encomenda (§6.4).

        `motor` escolhe quem guarda o stock, e e o comparador do AC-3:

            'sql'     `UPDATE ... WHERE quantidade - reservada >= :q` (§6.4)
            'medusa'  o Inventory Module, pelo cliente HTTP

        Medir os dois e o que distingue «o Medusa e atomico» de «o teste nao
        concorreu»: se o `sql` der 0 sobrevendas e o `medusa` der 0 com o mesmo
        numero de tentativas e a mesma contencao, o zero significa algo.
        """
        conexao, cursor = self._abrir(ctx)
        try:
            cursor.execute(
                "SELECT estado, lines_snapshot FROM platform.orders_mirror "
                " WHERE tenant_id = %s AND id = %s AND deleted_at IS NULL",
                (str(ctx.tenant_id), order_id),
            )
            linha = cursor.fetchone()
            if linha is None:
                raise PoliticaRecusada(f"encomenda {order_id} nao existe neste tenant")
            estado, instantaneo = linha
            if estado != "criada":
                raise PoliticaRecusada(
                    f"reserve_stock so em `criada`; a encomenda esta em {estado!r}"
                )
            itens = instantaneo if isinstance(instantaneo, list) else json.loads(instantaneo)

            reservas = []
            for numero, item in enumerate(itens, start=1):
                if motor == "sql":
                    cursor.execute(
                        "UPDATE platform.spike_stock_levels "
                        "   SET reservada = reservada + %s "
                        " WHERE tenant_id = %s AND sku = %s "
                        "   AND quantidade - reservada >= %s",
                        (item["qty"], str(ctx.tenant_id), item["sku"], item["qty"]),
                    )
                    if cursor.rowcount == 0:
                        raise PoliticaRecusada(
                            f"sem stock para {item['sku']!r} (pedido {item['qty']})"
                        )
                    medusa_id = None
                elif motor == "medusa":
                    if self.medusa is None:
                        raise PoliticaRecusada("motor 'medusa' pedido sem cliente Medusa")
                    medusa_id = self.medusa.reservar(
                        ctx, item["sku"], item["qty"]
                    )
                else:
                    raise ValueError(f"motor desconhecido: {motor!r}")

                cursor.execute(
                    "INSERT INTO platform.stock_reservations "
                    "  (tenant_id, order_id, line_no, sku, qty, estado, expira_at, "
                    "   medusa_reservation_id) "
                    "VALUES (%s, %s, %s, %s, %s, 'ativa', now() + make_interval(secs => %s), %s) "
                    "RETURNING id",
                    (str(ctx.tenant_id), order_id, numero, item["sku"], item["qty"],
                     ttl_segundos, medusa_id),
                )
                reservas.append({"id": str(cursor.fetchone()[0]), "sku": item["sku"],
                                 "qty": item["qty"]})

            cursor.execute(
                "UPDATE platform.orders_mirror "
                "   SET expira_at = now() + make_interval(secs => %s) "
                " WHERE tenant_id = %s AND id = %s",
                (ttl_segundos, str(ctx.tenant_id), order_id),
            )
            self._emitir(cursor, ctx, "stock.reserved", "order", str(order_id),
                         {"order_id": str(order_id), "reservas": len(reservas)})
            conexao.commit()
            return reservas
        except Exception:
            conexao.rollback()
            raise
        finally:
            conexao.close()

    def release_reservation(self, ctx: Ctx, order_id: str, motivo: str) -> int:
        """§3.2: motivo em `expirada|cancelada|recusada_dono`.

        **A consulta final a PAY vive aqui, e nao em quem chama.** O §6.5 diz
        que «a expiracao **nunca** liberta stock sem a consulta final a PAY
        (evita libertar stock de uma encomenda ja paga cujo callback se
        atrasou)». Na primeira versao do spike essa propriedade era garantida
        pelo varredor do teste, que saltava as encomendas que sabia pagas — ou
        seja, a prova de que o stock de uma encomenda paga nao se liberta era
        uma asserção contra o `continue` do proprio teste. Nao media nada.

        Agora a guarda e da porta: `self.consultar_pay` e injectado (o PAY nao
        existe no spike), e um `motivo='expirada'` sobre uma encomenda que o PAY
        declara paga e **recusado** pela porta. Quem mede so tem de perguntar
        se a reserva continua activa.
        """
        if motivo not in ("expirada", "cancelada", "recusada_dono"):
            raise PoliticaRecusada(f"motivo invalido: {motivo!r}")
        if motivo == "expirada" and self.consultar_pay is not None:
            if self.consultar_pay(ctx, order_id):
                raise PagamentoEncontradoNaConsultaFinal(
                    f"a encomenda {order_id} tem pagamento no PAY: a reserva "
                    "nao se liberta (§6.5)"
                )
        estado_novo = "expirada" if motivo == "expirada" else "libertada"
        conexao, cursor = self._abrir(ctx)
        try:
            cursor.execute(
                "SELECT 1 FROM platform.orders_mirror "
                " WHERE tenant_id = %s AND id = %s AND deleted_at IS NULL",
                (str(ctx.tenant_id), order_id),
            )
            if cursor.fetchone() is None:
                raise PoliticaRecusada(f"encomenda {order_id} nao existe neste tenant")
            cursor.execute(
                "SELECT id, sku, qty FROM platform.stock_reservations "
                " WHERE tenant_id = %s AND order_id = %s AND estado = 'ativa' "
                " FOR UPDATE",
                (str(ctx.tenant_id), order_id),
            )
            activas = cursor.fetchall()
            for _, sku, qty in activas:
                cursor.execute(
                    "UPDATE platform.spike_stock_levels "
                    "   SET reservada = reservada - %s "
                    " WHERE tenant_id = %s AND sku = %s",
                    (qty, str(ctx.tenant_id), sku),
                )
            cursor.execute(
                "UPDATE platform.stock_reservations SET estado = %s "
                " WHERE tenant_id = %s AND order_id = %s AND estado = 'ativa'",
                (estado_novo, str(ctx.tenant_id), order_id),
            )
            libertadas = cursor.rowcount
            if libertadas:
                self._emitir(cursor, ctx, "stock.released", "order", str(order_id),
                             {"order_id": str(order_id), "motivo": motivo})
            conexao.commit()
            return libertadas
        except Exception:
            conexao.rollback()
            raise
        finally:
            conexao.close()

    def commit_reservation(self, ctx: Ctx, order_id: str) -> int:
        """Chamada pelo consumidor de `payment.confirmed` (§3.2)."""
        conexao, cursor = self._abrir(ctx)
        try:
            cursor.execute(
                "SELECT 1 FROM platform.orders_mirror "
                " WHERE tenant_id = %s AND id = %s AND deleted_at IS NULL",
                (str(ctx.tenant_id), order_id),
            )
            if cursor.fetchone() is None:
                raise PoliticaRecusada(f"encomenda {order_id} nao existe neste tenant")
            cursor.execute(
                "SELECT sku, qty FROM platform.stock_reservations "
                " WHERE tenant_id = %s AND order_id = %s AND estado = 'ativa' FOR UPDATE",
                (str(ctx.tenant_id), order_id),
            )
            for sku, qty in cursor.fetchall():
                cursor.execute(
                    "UPDATE platform.spike_stock_levels "
                    "   SET quantidade = quantidade - %s, reservada = reservada - %s "
                    " WHERE tenant_id = %s AND sku = %s",
                    (qty, qty, str(ctx.tenant_id), sku),
                )
            cursor.execute(
                "UPDATE platform.stock_reservations SET estado = 'consumida' "
                " WHERE tenant_id = %s AND order_id = %s AND estado = 'ativa'",
                (str(ctx.tenant_id), order_id),
            )
            consumidas = cursor.rowcount
            conexao.commit()
            return consumidas
        except Exception:
            conexao.rollback()
            raise
        finally:
            conexao.close()

    def extend_reservation(self, ctx: Ctx, order_id: str, segundos: int) -> int:
        """§6.4: so enquanto `aguarda_pagamento`, e no maximo ao limite de 72 h."""
        conexao, cursor = self._abrir(ctx)
        try:
            cursor.execute(
                "SELECT estado FROM platform.orders_mirror "
                " WHERE tenant_id = %s AND id = %s AND deleted_at IS NULL",
                (str(ctx.tenant_id), order_id),
            )
            linha = cursor.fetchone()
            if linha is None:
                raise PoliticaRecusada(f"encomenda {order_id} nao existe neste tenant")
            if linha[0] != "aguarda_pagamento":
                raise PoliticaRecusada(
                    f"extend_reservation so em `aguarda_pagamento` (esta em {linha[0]!r})"
                )
            cursor.execute(
                "UPDATE platform.stock_reservations "
                "   SET expira_at = least(now() + make_interval(secs => %s), "
                "                          criado_at + interval '72 hours') "
                " WHERE tenant_id = %s AND order_id = %s AND estado = 'ativa'",
                (segundos, str(ctx.tenant_id), order_id),
            )
            tocadas = cursor.rowcount
            conexao.commit()
            return tocadas
        finally:
            conexao.close()

    def request_owner_confirmation(self, ctx: Ctx, order_id: str) -> None:
        conexao, cursor = self._abrir(ctx)
        try:
            cursor.execute(
                "UPDATE platform.orders_mirror SET confirmacao_dono = 'pendente' "
                " WHERE tenant_id = %s AND id = %s AND deleted_at IS NULL",
                (str(ctx.tenant_id), order_id),
            )
            if cursor.rowcount == 0:
                raise PoliticaRecusada(f"encomenda {order_id} nao existe neste tenant")
            conexao.commit()
        finally:
            conexao.close()
