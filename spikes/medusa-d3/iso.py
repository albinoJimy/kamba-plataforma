"""Matriz ISO-01..60 do §4.4. Sessenta casos, e nenhum conta por omissao.

A regra de leitura de cada caso e sempre a mesma, e e o que faz a matriz valer:

    o caso **passa** quando o acesso indevido **nao** produziu dados;
    o caso **falha** quando produziu;
    o caso fica **nao verificado** quando a superficie nao estava la para ser
    atacada — e nao verificado nunca e verde.

A terceira regra e a que este spike existe para respeitar. O §4.4 do
`docs/tecnica/03` diz que «falha de qualquer linha Bloqueante reprova a opcao»,
e o AC-1 pede «0 passes indevidos em **>= 60 casos**». Sessenta casos medidos
com zero passes indevidos cumprem o AC-1; cinquenta e seis medidos e quatro nao
medidos **nao** cumprem — sao cinquenta e seis. O `criterios.ac1` conta, e nao
arredonda.
"""

from __future__ import annotations

import dataclasses
import json
import uuid

import ligacao
import registo
from registo import Ctx, Linha, PoliticaRecusada

PASSA = "passa"
FALHA = "falha"
NAO_VERIFICADO = "nao_verificado"


def _erro_da_base():
    """A classe de erro do pg8000, para as excepcoes esperadas serem estreitas."""
    import pg8000.dbapi

    return pg8000.dbapi.DatabaseError


_ErroDaBase = _erro_da_base()


@dataclasses.dataclass
class Caso:
    id: str
    superficie: str
    cenario: str
    esperado: str
    estado: str
    observado: str
    evidencia: str = ""


def _recusou(caso: str, superficie: str, cenario: str, esperado: str, accao,
             excepcoes=(PoliticaRecusada,)) -> Caso:
    """Corre `accao` e espera uma recusa. Dados devolvidos sao uma falha.

    Uma excepcao **inesperada** tambem nao e um passe: e um caso que nao se
    conseguiu medir. Distinguir isto de uma recusa e o que impede um erro de
    programacao no proprio teste de se disfarcar de isolamento a funcionar — o
    defeito que o §6 da skill de metodo chama «o criterio satisfeito pela razao
    errada».
    """
    try:
        devolvido = accao()
    except excepcoes as recusa:
        return Caso(caso, superficie, cenario, esperado, PASSA,
                    "recusado", f"{type(recusa).__name__}: {recusa}")
    except Exception as erro:  # noqa: BLE001
        return Caso(caso, superficie, cenario, esperado, NAO_VERIFICADO,
                    "erro inesperado no proprio teste",
                    f"{type(erro).__name__}: {erro}")
    return Caso(caso, superficie, cenario, esperado, FALHA,
                "devolveu dados", f"devolvido: {devolvido!r}"[:400])


def _vazio(caso: str, superficie: str, cenario: str, esperado: str, accao,
           proibido: set[str]) -> Caso:
    """Corre `accao` e espera que nenhum id de `proibido` apareca."""
    try:
        devolvido = accao()
    except Exception as erro:  # noqa: BLE001
        return Caso(caso, superficie, cenario, esperado, NAO_VERIFICADO,
                    "erro inesperado no proprio teste",
                    f"{type(erro).__name__}: {erro}")
    vistos = {str(item.get("id")) for item in devolvido} if devolvido else set()
    fuga = vistos & proibido
    if fuga:
        return Caso(caso, superficie, cenario, esperado, FALHA,
                    f"{len(fuga)} id(s) de outro tenant", f"fuga: {sorted(fuga)}")
    return Caso(caso, superficie, cenario, esperado, PASSA,
                f"{len(vistos)} linha(s), nenhuma de outro tenant", "")


def _pendente(caso: str, superficie: str, cenario: str, esperado: str,
              razao: str) -> Caso:
    return Caso(caso, superficie, cenario, esperado, NAO_VERIFICADO,
                "nao medido", razao)


def correr(ambiente: dict[str, str], tenants: dict, com_medusa: bool,
           contentor_medusa: str | None = None) -> list[Caso]:
    porta = registo.Registo(ambiente)
    a, b, c = tenants["A"], tenants["B"], tenants["C"]
    ctx_a = Ctx(tenant_id=a.tenant_id)
    ctx_b = Ctx(tenant_id=b.tenant_id)

    # Uma encomenda por tenant, para haver ids reais de B que A possa sondar.
    encomendas = {}
    for rotulo, tenant in (("A", a), ("B", b), ("C", c)):
        ctx = Ctx(tenant_id=tenant.tenant_id)
        sku = f"SKU-{rotulo}-UNICO"
        chave = registo.intent_key(ctx, tenant.contact_id, f"draft-iso-{rotulo}", 1)
        encomendas[rotulo] = porta.create_order(
            ctx, tenant.contact_id, [Linha(sku, 1)], chave
        )["order_id"]
    pedido_b = str(encomendas["B"])
    porta.reserve_stock(ctx_b, pedido_b, 3600)

    casos: list[Caso] = []

    # ------------------------------------------- ISO-01..08: a porta, ctx de A
    casos.append(_recusou(
        "ISO-01", "CommerceRegistry", "get_offer_view com ctx de A sobre sku de B",
        "404/erro de politica; nunca dados",
        lambda: porta.get_offer_view(ctx_a, "SKU-B-UNICO")))
    casos.append(_recusou(
        "ISO-02", "CommerceRegistry", "get_order com ctx de A sobre encomenda de B",
        "404/erro de politica; nunca dados",
        lambda: porta.get_order(ctx_a, pedido_b)))
    casos.append(_vazio(
        "ISO-03", "CommerceRegistry", "list_orders com ctx de A",
        "so linhas de A",
        lambda: porta.list_orders(ctx_a),
        {str(encomendas["B"]), str(encomendas["C"])}))
    casos.append(_recusou(
        "ISO-04", "CommerceRegistry", "transition com ctx de A sobre encomenda de B",
        "404/erro de politica",
        lambda: porta.transition(ctx_a, pedido_b, "cancelada", 1, "iso-04")))
    casos.append(_recusou(
        "ISO-05", "CommerceRegistry",
        "release_reservation com ctx de A sobre encomenda de B", "404/erro de politica",
        lambda: porta.release_reservation(ctx_a, pedido_b, "cancelada")))
    casos.append(_recusou(
        "ISO-06", "CommerceRegistry", "publish_product com ctx de A sobre sku de B",
        "404/erro de politica",
        lambda: porta.publish_product(ctx_a, "SKU-B-UNICO", True)))
    casos.append(_recusou(
        "ISO-07", "CommerceRegistry",
        "request_owner_confirmation com ctx de A sobre encomenda de B",
        "404/erro de politica",
        lambda: porta.request_owner_confirmation(ctx_a, pedido_b)))
    casos.append(_recusou(
        "ISO-08", "CommerceRegistry",
        "commit_reservation com ctx de A sobre encomenda de B", "404/erro de politica",
        lambda: porta.commit_reservation(ctx_a, pedido_b)))

    # ------------------------------------------------------ ISO-09: falha fechada
    casos.append(_iso09(porta, encomendas))

    # ---------------------------------------------- ISO-10: filtros e paginacao
    casos.append(_iso10(porta, ctx_a, encomendas))

    # -------------------------------------------- ISO-11..18: API Store do Medusa
    casos.extend(_iso_medusa_store(ambiente, tenants, com_medusa, contentor_medusa))
    # -------------------------------------------- ISO-19..26: API Admin do Medusa
    casos.extend(_iso_medusa_admin(ambiente, tenants, com_medusa, contentor_medusa))
    # ------------------------------------------------- ISO-27..32: query graph
    casos.extend(_iso_query_graph(ambiente, tenants, com_medusa, contentor_medusa))

    # ----------------------------------- ISO-33..38: reservas e colisao de SKU
    casos.extend(_iso_reservas(porta, ambiente, tenants))
    # -------------------------------------------------- ISO-39..42: RLS directa
    casos.extend(_iso_rls(ambiente, tenants, encomendas))
    # ------------------------------------------------------ ISO-43..46: eventos
    casos.extend(_iso_eventos(ambiente, tenants))
    # ------------------------------------------- ISO-47..50: media e URLs
    casos.extend(_iso_media(ambiente, tenants))
    # -------------------------------------------------- ISO-51..56: concorrencia
    casos.extend(_iso_concorrencia(porta, ambiente, tenants))
    # ---------------------------------------------------- ISO-57..60: injeccao
    casos.extend(_iso_injeccao(porta, ambiente, tenants))

    return casos


def _iso09(porta: registo.Registo, encomendas: dict) -> Caso:
    """`ctx` sem `tenantId` ou com `tenantId` inexistente -> falha fechada."""
    pedido = str(encomendas["B"])
    for rotulo, ctx in (
        ("sem tenant_id", Ctx(tenant_id=None)),
        ("tenant_id vazio", Ctx(tenant_id="")),
        ("tenant_id inexistente", Ctx(tenant_id=str(uuid.uuid4()))),
        ("tenant_id que nao e uuid", Ctx(tenant_id="' OR 1=1 --")),
    ):
        caso = _recusou("ISO-09", "CommerceRegistry", rotulo, "falha fechada",
                        lambda c=ctx: porta.get_order(c, pedido))
        if caso.estado != PASSA:
            caso.cenario = f"ctx sem tenantId ou inexistente ({rotulo})"
            return caso
    return Caso("ISO-09", "CommerceRegistry",
                "ctx sem tenantId, vazio, inexistente e nao-uuid (4 sondas)",
                "falha fechada", PASSA, "as 4 sondas recusadas",
                "nenhuma devolveu dados")


def _iso10(porta: registo.Registo, ctx_a: Ctx, encomendas: dict) -> Caso:
    """Filtros vazios, cursor forjado, `OR` em filtro -> so linhas de A."""
    proibidos = {str(encomendas["B"]), str(encomendas["C"])}
    sondas = {
        "filtros vazios": lambda: porta.list_orders(ctx_a),
        "estado forjado": lambda: porta.list_orders(ctx_a, estado="' OR '1'='1"),
        "OR no filtro": lambda: porta.list_orders(ctx_a, filtro_bruto="' OR 1=1 --"),
        "cursor forjado": lambda: porta.list_orders(
            ctx_a, filtro_bruto="x' UNION SELECT id::text FROM platform.orders_mirror --"),
    }
    for rotulo, sonda in sondas.items():
        caso = _vazio("ISO-10", "list_orders", rotulo, "so linhas de A", sonda, proibidos)
        if caso.estado != PASSA:
            return caso
    return Caso("ISO-10", "list_orders",
                "filtros vazios, estado forjado, OR no filtro, cursor forjado (4 sondas)",
                "so linhas de A", PASSA, "as 4 sondas sem fuga", "")


def _razao_sem_medusa(superficie: str) -> str:
    return (
        f"o Medusa nao esteve de pe nesta execucao, pelo que {superficie} nao foi "
        "atacada. Correr `python spikes/medusa-d3/harness.py` sem `--sem-medusa`."
    )


def _iso_medusa_store(ambiente, tenants, com_medusa, contentor_medusa=None) -> list[Caso]:
    # Os cenarios seguem a coluna «Cenario» do §4.4: «produtos, carts,
    # encomendas, stock e precos de B por id e por pesquisa». Tem de coincidir
    # com `medusa/src/scripts/spike.ts`, que e quem os mede — e o
    # `_exigir_cenarios_iguais` abaixo falha se divergirem, porque uma
    # divergencia silenciosa trocava um caso da matriz por outro sem ninguem ver.
    cenarios = [
        ("ISO-11", "chave publicavel de A a pedir produto de B por id"),
        ("ISO-12", "chave publicavel de A a pesquisar produtos de B por titulo"),
        ("ISO-13", "chave publicavel de A a pedir variantes e precos de B"),
        ("ISO-14", "chave publicavel de A a pedir o cart de B por id"),
        ("ISO-15", "chave publicavel de A a pedir a encomenda de B por id"),
        ("ISO-16", "chave publicavel de A a pedir o stock/inventario de B"),
        ("ISO-17", "chave publicavel de A a listar produtos sem filtro"),
        ("ISO-18", "chave de A com o `sales_channel_id` de B no parametro"),
    ]
    if not com_medusa:
        return [_pendente(i, "API Store do Medusa", cenario, "negado ou vazio",
                          _razao_sem_medusa("a API Store do Medusa"))
                for i, cenario in cenarios]
    import medusa
    return medusa.iso_store(ambiente, tenants, cenarios, contentor_medusa)


def _iso_medusa_admin(ambiente, tenants, com_medusa, contentor_medusa=None) -> list[Caso]:
    cenarios = [
        ("ISO-19", "rota Admin de produtos sem credencial nenhuma"),
        ("ISO-20", "rota Admin com a chave publicavel de A em vez do token"),
        ("ISO-21", "operador a listar produtos sem filtro de merchant"),
        ("ISO-22", "operador a listar inventario sem filtro de merchant"),
        ("ISO-23", "operador a listar clientes sem filtro de merchant"),
        ("ISO-24", "operador a listar sales channels sem filtro"),
        ("ISO-25", "operador a pedir o produto de B por id"),
        ("ISO-26", "rota Admin de RBAC (material Enterprise), com token de operador"),
    ]
    if not com_medusa:
        return [_pendente(i, "API Admin do Medusa", cenario,
                          "inacessivel (AC-2); com acesso operador, auditado",
                          _razao_sem_medusa("a API Admin do Medusa"))
                for i, cenario in cenarios]
    import medusa
    return medusa.iso_admin(ambiente, tenants, cenarios, contentor_medusa)


def _iso_query_graph(ambiente, tenants, com_medusa, contentor_medusa=None) -> list[Caso]:
    cenarios = [
        ("ISO-27", "Query.graph de merchants **sem** filtro"),
        ("ISO-28", "Query.graph de merchants com o filtro que o COM injecta (A)"),
        ("ISO-29", "Query.graph pelo link merchant->product com o merchant de A"),
        ("ISO-30", "Query.graph de produtos **sem** filtro, atravessando o link "
                   "para o merchant"),
        ("ISO-31", "Query.graph de inventário **sem** filtro (itens marcados "
                   "por tenant no `sku`)"),
        ("ISO-32", "Query.graph com filtro de tenant forjado (tenant inexistente)"),
    ]
    if not com_medusa:
        return [_pendente(i, "query graph / modulos", cenario,
                          "filtro imposto pelo COM",
                          _razao_sem_medusa("o query graph do Medusa"))
                for i, cenario in cenarios]
    import medusa
    return medusa.iso_query_graph(ambiente, tenants, cenarios, contentor_medusa)


def _iso_reservas(porta: registo.Registo, ambiente, tenants) -> list[Caso]:
    """ISO-33..38: a colisao de SKU, que e o caso onde um filtro em falta engana."""
    import sementes as sem

    a, b = tenants["A"], tenants["B"]
    ctx_a, ctx_b = Ctx(tenant_id=a.tenant_id), Ctx(tenant_id=b.tenant_id)
    casos: list[Caso] = []

    # ISO-33: A reserva `SKU-COLISAO` e so o inventario de A se move.
    sem.repor_stock(ambiente, a, sem.SKU_COLISAO, 10)
    sem.repor_stock(ambiente, b, sem.SKU_COLISAO, 7)
    chave = registo.intent_key(ctx_a, a.contact_id, "draft-iso33", 1)
    pedido = porta.create_order(ctx_a, a.contact_id,
                               [Linha(sem.SKU_COLISAO, 2)], chave)["order_id"]
    porta.reserve_stock(ctx_a, str(pedido), 3600)
    reservado_a = _stock(ambiente, a.tenant_id, sem.SKU_COLISAO)
    reservado_b = _stock(ambiente, b.tenant_id, sem.SKU_COLISAO)
    if reservado_a["reservada"] == 2 and reservado_b["reservada"] == 0:
        casos.append(Caso("ISO-33", "Reservas",
                          "A reserva 2 de SKU-COLISAO (que existe em A, B e C)",
                          "reserva so no inventario de A", PASSA,
                          "A reservada=2, B reservada=0",
                          f"A={reservado_a}, B={reservado_b}"))
    else:
        casos.append(Caso("ISO-33", "Reservas",
                          "A reserva 2 de SKU-COLISAO", "reserva so no inventario de A",
                          FALHA, f"A reservada={reservado_a['reservada']}, "
                                 f"B reservada={reservado_b['reservada']}",
                          f"A={reservado_a}, B={reservado_b}"))

    # ISO-34: o preco veio de `offer_terms` de A, nao de B (B custa 990.000).
    encomenda = porta.get_order(ctx_a, str(pedido))
    esperado = a.skus[sem.SKU_COLISAO][0] * 2
    casos.append(Caso(
        "ISO-34", "Reservas",
        "total da encomenda de A sobre SKU-COLISAO (B tem outro preco para o mesmo sku)",
        f"total = {esperado} (preco de A), nunca o de B",
        PASSA if encomenda["total_minor"] == esperado else FALHA,
        f"total_minor={encomenda['total_minor']}",
        f"preco de A={a.skus[sem.SKU_COLISAO][0]}, de B={b.skus[sem.SKU_COLISAO][0]}"))

    # ISO-35: A nao liberta a reserva de B sobre o mesmo sku.
    chave_b = registo.intent_key(ctx_b, b.contact_id, "draft-iso35", 1)
    pedido_b = porta.create_order(ctx_b, b.contact_id,
                                  [Linha(sem.SKU_COLISAO, 1)], chave_b)["order_id"]
    porta.reserve_stock(ctx_b, str(pedido_b), 3600)
    casos.append(_recusou(
        "ISO-35", "Reservas", "A liberta a reserva de B sobre o mesmo sku",
        "404/erro de politica",
        lambda: porta.release_reservation(ctx_a, str(pedido_b), "cancelada")))

    # ISO-36: a reserva de B continua activa depois da tentativa de A.
    activas_b = _reservas_activas(ambiente, b.tenant_id, str(pedido_b))
    casos.append(Caso(
        "ISO-36", "Reservas", "a reserva de B sobrevive a tentativa de A a libertar",
        "reserva de B intacta", PASSA if activas_b == 1 else FALHA,
        f"{activas_b} reserva(s) activa(s) de B", ""))

    # ISO-37: A nao reserva sobre um sku que so existe em B.
    chave37 = registo.intent_key(ctx_a, a.contact_id, "draft-iso37", 1)
    casos.append(_recusou(
        "ISO-37", "Reservas", "A cria encomenda sobre SKU-B-UNICO",
        "404/erro de politica",
        lambda: porta.create_order(ctx_a, a.contact_id,
                                   [Linha("SKU-B-UNICO", 1)], chave37)))

    # ISO-38: o stock de A nao cobre a reserva de B e vice-versa.
    sem.repor_stock(ambiente, a, sem.SKU_COLISAO, 1)
    sem.repor_stock(ambiente, b, sem.SKU_COLISAO, 50)
    chave38 = registo.intent_key(ctx_a, a.contact_id, "draft-iso38", 1)
    pedido38 = porta.create_order(ctx_a, a.contact_id,
                                  [Linha(sem.SKU_COLISAO, 5)], chave38)["order_id"]
    casos.append(_recusou(
        "ISO-38", "Reservas",
        "A pede 5 de SKU-COLISAO com stock 1 em A e 50 em B",
        "recusado: o stock de B nao cobre A",
        lambda: porta.reserve_stock(ctx_a, str(pedido38), 3600)))
    return casos


def _stock(ambiente, tenant_id: str, sku: str) -> dict:
    conexao = ligacao.ligar("batch", ambiente)
    try:
        cursor = conexao.cursor()
        cursor.execute(
            "SELECT quantidade, reservada FROM platform.spike_stock_levels "
            " WHERE tenant_id = %s AND sku = %s", (tenant_id, sku))
        linha = cursor.fetchone()
        return {"quantidade": linha[0], "reservada": linha[1]} if linha else {}
    finally:
        conexao.close()


def _reservas_activas(ambiente, tenant_id: str, order_id: str) -> int:
    conexao = ligacao.ligar("batch", ambiente)
    try:
        cursor = conexao.cursor()
        cursor.execute(
            "SELECT count(*) FROM platform.stock_reservations "
            " WHERE tenant_id = %s AND order_id = %s AND estado = 'ativa'",
            (tenant_id, order_id))
        return cursor.fetchone()[0]
    finally:
        conexao.close()


def _iso_rls(ambiente, tenants, encomendas) -> list[Caso]:
    """ISO-39..42: a **segunda** barreira, medida com SQL directo e `kamba_app`.

    Isto nao passa pela porta de proposito. O §5.5 chama-lhe «defesa em
    profundidade»: a prova de que serve e um `SELECT` cru, com o contexto de A,
    a nao ver as linhas de B. Se este bloco fosse pela porta, media a porta duas
    vezes e a RLS nenhuma.
    """
    a, b = tenants["A"], tenants["B"]
    pedido_b = str(encomendas["B"])
    casos: list[Caso] = []

    def com_contexto(tenant_id: str | None, sql: str, parametros: tuple):
        """Devolve `('linhas', [...])`, `('rowcount', n)` ou `('recusa', texto)`.

        A terceira forma existe porque **ha duas barreiras e nao uma**, e
        confundi-las esconderia qual delas trabalhou. O `kamba_app` nao tem
        `DELETE` em `orders_mirror` — o §5.6 proibe o apagamento fisico, e a
        revisao nao da esse privilegio — pelo que um `DELETE` nao devolve «0
        linhas» pela RLS: morre antes, com `42501 permission denied`. As duas
        respostas satisfazem o criterio («0 linhas»), e o relatorio diz qual foi.
        """
        conexao = ligacao.ligar("app", ambiente)
        try:
            cursor = conexao.cursor()
            cursor.execute("SELECT set_config('app.tenant_id', %s, true)",
                           (tenant_id or "",))
            cursor.fetchone()
            try:
                cursor.execute(sql, parametros)
            except Exception as erro:  # noqa: BLE001
                # **So `42501` conta como recusa.** Qualquer outra excepcao —
                # uma tabela mal escrita, uma coluna que mudou de nome, a base
                # errada — nao e a barreira a funcionar: e o teste a nao correr,
                # e um teste que nao corre nao e um caso verde.
                estado = _sqlstate(erro)
                if "42501" in estado:
                    return ("recusa", f"{type(erro).__name__}: {estado}")
                return ("erro_do_teste", f"{type(erro).__name__}: {estado}")
            try:
                return ("linhas", cursor.fetchall())
            except Exception:  # noqa: BLE001 — um UPDATE/DELETE nao devolve linhas
                return ("rowcount", cursor.rowcount)
        finally:
            conexao.rollback()
            conexao.close()

    def avaliar(identificador: str, cenario: str, resultado) -> Caso:
        """«0 linhas» ou uma recusa; qualquer das duas satisfaz, e diz-se qual."""
        forma, valor = resultado
        if forma == "erro_do_teste":
            return Caso(identificador, "orders_mirror / RLS", cenario, "0 linhas",
                        NAO_VERIFICADO, "erro inesperado no proprio teste", valor)
        if forma == "recusa":
            return Caso(identificador, "orders_mirror / RLS", cenario, "0 linhas",
                        PASSA, "recusado antes da RLS (privilegio)",
                        f"{valor} — o §5.6 nao da este privilegio ao `kamba_app`; "
                        "a barreira foi o GRANT, nao a politica `tenant_iso`")
        if forma == "linhas":
            return Caso(identificador, "orders_mirror / RLS", cenario, "0 linhas",
                        PASSA if len(valor) == 0 else FALHA,
                        f"{len(valor)} linha(s)", "politica tenant_iso, FORCE")
        return Caso(identificador, "orders_mirror / RLS", cenario, "0 linhas",
                    PASSA if valor == 0 else FALHA, f"rowcount={valor}",
                    "politica tenant_iso, FORCE (USING e WITH CHECK)")

    casos.append(avaliar(
        "ISO-39", "sessao SQL com app.tenant_id de A: SELECT na linha de B",
        com_contexto(a.tenant_id,
                     "SELECT id FROM platform.orders_mirror WHERE id = %s",
                     (pedido_b,))))
    casos.append(avaliar(
        "ISO-40", "sessao SQL com app.tenant_id de A: UPDATE na linha de B",
        com_contexto(a.tenant_id,
                     "UPDATE platform.orders_mirror SET total_minor = 1 "
                     " WHERE id = %s", (pedido_b,))))
    casos.append(avaliar(
        "ISO-41", "sessao SQL com app.tenant_id de A: DELETE na linha de B",
        com_contexto(a.tenant_id,
                     "DELETE FROM platform.orders_mirror WHERE id = %s",
                     (pedido_b,))))
    casos.append(avaliar(
        "ISO-42", "sessao SQL **sem** app.tenant_id (falha fechada)",
        com_contexto(None, "SELECT id FROM platform.orders_mirror", ())))

    # **Controlo positivo, e nao e um caso da matriz.** Os quatro casos acima
    # passam com «0 linhas», e passariam igualmente com a tabela vazia, com a
    # ligacao na base errada, ou com `app.tenant_id` escrito com outro nome —
    # caso em que a RLS nao teria sido exercitada uma unica vez e os quatro
    # dariam verde. Esta sonda confirma que **com** o contexto de A o mesmo
    # `SELECT` devolve as linhas de A: sem isso, os quatro verdes nao valem.
    proprias = com_contexto(
        a.tenant_id, "SELECT id FROM platform.orders_mirror WHERE tenant_id = %s",
        (a.tenant_id,))
    forma, valor = proprias
    visiveis = len(valor) if forma == "linhas" else -1
    casos.append(Caso(
        "RLS-CONTROLO (sonda positiva, fora da contagem)", "orders_mirror / RLS",
        "sessao SQL com app.tenant_id de A: SELECT nas linhas **de A**",
        "as linhas de A sao visiveis (senao os ISO-39..42 passam por vazio)",
        PASSA if visiveis > 0 else FALHA,
        f"{visiveis} linha(s) de A visiveis",
        "se isto desse 0, os quatro casos da RLS estariam a medir uma tabela "
        "vazia e nao uma politica"))
    return casos


def _sqlstate(excepcao: BaseException) -> str:
    """O SQLSTATE e a mensagem de um erro do pg8000 (campos `C` e `M`)."""
    for argumento in excepcao.args:
        if isinstance(argumento, dict) and "C" in argumento:
            return f"SQLSTATE {argumento['C']}: {argumento.get('M', '')}"
    return str(excepcao)[:200]


def _iso_eventos(ambiente, tenants) -> list[Caso]:
    """ISO-43..46: `events_outbox` e o envelope."""
    a, b = tenants["A"], tenants["B"]
    casos: list[Caso] = []

    def com_contexto(tenant_id: str | None, sql: str, parametros: tuple = ()):
        conexao = ligacao.ligar("app", ambiente)
        try:
            cursor = conexao.cursor()
            cursor.execute("SELECT set_config('app.tenant_id', %s, true)",
                           (tenant_id or "",))
            cursor.fetchone()
            cursor.execute(sql, parametros)
            return cursor.fetchall()
        finally:
            conexao.rollback()
            conexao.close()

    linhas = com_contexto(a.tenant_id,
                          "SELECT event_id FROM platform.events_outbox WHERE tenant_id = %s",
                          (b.tenant_id,))
    casos.append(Caso(
        "ISO-43", "Eventos", "consumidor de A a ler o outbox de B",
        "rejeitado pela validacao do envelope / 0 linhas",
        PASSA if len(linhas) == 0 else FALHA, f"{len(linhas)} linha(s)", ""))

    todas = com_contexto(a.tenant_id,
                         "SELECT tenant_id FROM platform.events_outbox")
    alheios = [t for (t,) in todas if str(t) != a.tenant_id]
    casos.append(Caso(
        "ISO-44", "Eventos", "consumidor de A a varrer o outbox sem filtro",
        "so eventos de A", PASSA if not alheios else FALHA,
        f"{len(todas)} evento(s), {len(alheios)} de outro tenant", ""))

    # ISO-45: emitir com o `tenant_id` de B a partir do contexto de A. Vai pela
    # funcao `evt_emitir`, que e o unico caminho que o `kamba_app` tem (o
    # `04_outbox.sql` tirou-lhe o `INSERT`). A funcao e `SECURITY DEFINER`, mas
    # o `FORCE ROW LEVEL SECURITY` vincula tambem a dona: quem decide e o
    # `WITH CHECK` da politica contra o `app.tenant_id` da sessao.
    def forjar():
        conexao = ligacao.ligar("app", ambiente)
        try:
            cursor = conexao.cursor()
            cursor.execute("SELECT set_config('app.tenant_id', %s, true)", (a.tenant_id,))
            cursor.fetchone()
            cursor.execute(
                "SELECT platform.evt_emitir('order.created', 1::smallint, %s, "
                "                           'order', %s, '{}'::jsonb, NULL)",
                (b.tenant_id, str(uuid.uuid4())),
            )
            evento = cursor.fetchone()[0]
            conexao.commit()
            return f"emitiu o evento {evento} com o tenant_id de B"
        finally:
            conexao.close()

    casos.append(_recusou(
        "ISO-45", "Eventos",
        "ctx de A a emitir um evento com o tenant_id de B",
        "rejeitado (WITH CHECK da politica `tenant_iso`)", forjar,
        excepcoes=(_ErroDaBase,)))

    # ISO-46: a incoerencia entre a coluna e o envelope. **Nao e mais possivel
    # tenta-la**, e e esse o resultado: o `kamba_app` nao tem `INSERT` na tabela,
    # e a funcao nao aceita um envelope — constroi-o. Mede-se as duas metades:
    # que o `INSERT` directo e recusado, e que o envelope que a funcao escreveu
    # concorda com a coluna.
    def inserir_directo():
        conexao = ligacao.ligar("app", ambiente)
        try:
            cursor = conexao.cursor()
            cursor.execute("SELECT set_config('app.tenant_id', %s, true)", (a.tenant_id,))
            cursor.fetchone()
            cursor.execute(
                "INSERT INTO platform.events_outbox "
                "  (event_id, tipo, versao, tenant_id, agregado_tipo, agregado_id, "
                "   agregado_seq, particao, envelope) "
                "VALUES (%s, 'order.created', 1, %s, 'order', %s, 1, 0, %s)",
                (str(uuid.uuid4()), a.tenant_id, str(uuid.uuid4()),
                 json.dumps({"tenant_id": b.tenant_id})),
            )
            conexao.commit()
            return "o INSERT directo passou"
        finally:
            conexao.close()

    caso_directo = _recusou(
        "ISO-46", "Eventos",
        "ctx de A a inserir directamente um envelope que diz tenant B",
        "recusado: quem emite nao escreve o envelope", inserir_directo,
        excepcoes=(_ErroDaBase,))
    if caso_directo.estado == PASSA:
        # Segunda metade: o que a funcao escreveu concorda com a coluna?
        incoerentes = com_contexto(
            a.tenant_id,
            "SELECT count(*) FROM platform.events_outbox "
            " WHERE envelope->>'tenant_id' IS DISTINCT FROM tenant_id::text")
        numero = incoerentes[0][0] if incoerentes else -1
        if numero == 0:
            caso_directo.observado = (
                "INSERT directo recusado; 0 eventos com envelope e coluna "
                "em desacordo")
            caso_directo.evidencia = (
                f"{caso_directo.evidencia} | e a conferencia "
                "`envelope->>'tenant_id' <> tenant_id` deu 0 em todos os "
                "eventos que a funcao escreveu")
        else:
            caso_directo.estado = FALHA
            caso_directo.observado = f"{numero} evento(s) com envelope e coluna em desacordo"
    casos.append(caso_directo)
    return casos


def _iso_media(ambiente, tenants) -> list[Caso]:
    """ISO-47..50: media e URLs assinadas, contra a porta de armazenamento real.

    Nao e um *fake* escrito para este spike: e `packages/core-ts/dist/storage`,
    a porta do KAM-011, com `criarStorageFake()` — a mesma bateria que a suite de
    contrato desse ticket corre contra um S3 real. Isso importa: um teste de
    isolamento de media escrito aqui mediria o meu proprio teste.
    """
    import media

    cenarios = [
        ("ISO-47", "ctx de A a ler o objecto de B por referencia"),
        ("ISO-48", "URL assinada do objecto de B usada com contexto A"),
        ("ISO-49", "ctx de A a listar o prefixo do tenant B"),
        ("ISO-50", "ctx de A a escrever numa chave cunhada para B"),
    ]
    return media.correr(tenants, cenarios)


def _iso_concorrencia(porta: registo.Registo, ambiente, tenants) -> list[Caso]:
    """ISO-51..56: A e B ao mesmo SKU global, contagens independentes."""
    import concorrencia

    return concorrencia.iso(porta, ambiente, tenants)


def _iso_injeccao(porta: registo.Registo, ambiente, tenants) -> list[Caso]:
    """ISO-57..60: `tenant_id` no texto do cliente -> ignorado.

    O `ctx` e um argumento da porta e vem do estado da sessao. Estes quatro
    casos poem o `tenant_id` de B em sitios por onde o texto do cliente passa e
    verificam que a encomenda continua a ser de A. O que se mede e que **nao ha
    caminho** do texto para o `ctx` — e a unica forma de o medir e tentar.
    """
    a, b = tenants["A"], tenants["B"]
    ctx_a = Ctx(tenant_id=a.tenant_id)
    casos: list[Caso] = []

    # ISO-57: o `tenant_id` de B no nome do SKU pedido.
    chave = registo.intent_key(ctx_a, a.contact_id, "draft-iso57", 1)
    casos.append(_recusou(
        "ISO-57", "Injeccao",
        f"sku pedido = '{b.tenant_id}' (o tenant_id de B como nome de produto)",
        "ignorado; o tenant_id so vem do estado",
        lambda: porta.create_order(ctx_a, a.contact_id,
                                   [Linha(b.tenant_id, 1)], chave)))

    # ISO-58: `tenant_id` de B no `contact_id` — um contacto de outro tenant.
    chave58 = registo.intent_key(ctx_a, a.contact_id, "draft-iso58", 1)
    casos.append(_recusou(
        "ISO-58", "Injeccao",
        "ctx de A com o contact_id de B (FK e RLS a decidir)",
        "recusado", lambda: porta.create_order(
            ctx_a, b.contact_id, [Linha("SKU-A-UNICO", 1)], chave58),
        # A recusa legitima vem da FK composta (violacao de FK) ou da porta.
        # `Exception` desligava a distincao: um `TypeError` no proprio teste
        # passava por isolamento a funcionar.
        excepcoes=(PoliticaRecusada, _ErroDaBase)))

    # ISO-59: `tenant_id` de B no modo de entrega (campo de texto do pedido).
    chave59 = registo.intent_key(ctx_a, a.contact_id, "draft-iso59", 1)
    casos.append(_recusou(
        "ISO-59", "Injeccao",
        f"entrega_modo = 'levantamento; tenant_id={b.tenant_id}'",
        "recusado pelo CHECK; nunca interpretado como tenant",
        lambda: porta.create_order(
            ctx_a, a.contact_id, [Linha("SKU-A-UNICO", 1)], chave59,
            entrega_modo=f"levantamento; tenant_id={b.tenant_id}"),
        excepcoes=(PoliticaRecusada, _ErroDaBase)))

    # ISO-60: a encomenda criada com texto hostil continua a ser de A.
    chave60 = registo.intent_key(ctx_a, a.contact_id, "draft-iso60", 1)
    try:
        criada = porta.create_order(ctx_a, a.contact_id,
                                   [Linha("SKU-A-UNICO", 1)], chave60)
        conexao = ligacao.ligar("batch", ambiente)
        cursor = conexao.cursor()
        cursor.execute("SELECT tenant_id FROM platform.orders_mirror WHERE id = %s",
                       (criada["order_id"],))
        dono = str(cursor.fetchone()[0])
        conexao.close()
        casos.append(Caso(
            "ISO-60", "Injeccao",
            "encomenda criada com ctx de A: a quem pertence a linha",
            f"tenant_id = A ({a.tenant_id})",
            PASSA if dono == a.tenant_id else FALHA,
            f"tenant_id={dono}", "o ctx e a unica origem do tenant"))
    except Exception as erro:  # noqa: BLE001
        casos.append(Caso(
            "ISO-60", "Injeccao",
            "encomenda criada com ctx de A: a quem pertence a linha",
            f"tenant_id = A ({a.tenant_id})", NAO_VERIFICADO,
            "erro inesperado no proprio teste", f"{type(erro).__name__}: {erro}"))
    return casos
