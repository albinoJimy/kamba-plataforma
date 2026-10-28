"""Concorrencia: ISO-51..56, e as tempestades que o AC-3 e o AC-4 pedem.

**Uma nota sobre «1.000 tentativas paralelas» (AC-3).** Mil ligacoes
verdadeiramente simultaneas a um PostgreSQL exigem `max_connections >= 1000`, o
que nesta maquina nao cabe (cada *backend* e um processo). O que se corre e:

    1.000 tentativas, em vagas de `SIMULTANEAS`, cada vaga sincronizada por uma
    barreira para que os *threads* cheguem ao `UPDATE` no mesmo instante.

O numero de simultaneas vai no resultado, e o relatorio escreve-o. Dizer «1.000
paralelas» sem dizer quantas correram ao mesmo tempo era dar ao criterio uma
folga que ele nao da: a propriedade medida (zero reservas acima do stock) so
vale com contencao real, e a barreira e o que a garante.

A leitura divergente da letra esta registada no relatorio e devolvida a quem
escreveu o criterio, como o metodo manda — nao se marca a caixa por ela.
"""

from __future__ import annotations

import threading
from concurrent.futures import ThreadPoolExecutor

import ligacao
import registo as registo_mod
import sementes as sem
from iso import FALHA, NAO_VERIFICADO, PASSA, Caso
from registo import Ctx, Linha

#: Quantas tentativas chegam ao `UPDATE` no mesmo instante, por vaga.
#: `max_connections=400` no contentor (ver `contentor.py`); 250 deixa folga para
#: as ligacoes do proprio harness.
SIMULTANEAS = 250
#: O total que o AC-3 pede.
TENTATIVAS_AC3 = 1000
#: O total que o AC-4 pede.
TENTATIVAS_AC4 = 50


def tempestade(total: int, simultaneas: int, trabalho, aquecer=None) -> list:
    """Corre `trabalho(indice)` `total` vezes, em vagas sincronizadas.

    Devolve a lista de resultados, pela ordem de submissao. Cada elemento e
    `("ok", valor)`, `("erro", texto)` ou `("barreira_partida", texto)`: uma
    recusa e um resultado, nao uma excepcao que interrompe a medicao.

    `aquecer(indice)` corre **antes** da barreira, e existe por uma razao
    concreta: sem ele, o que a barreira sincronizava era a *abertura da
    ligacao* — TCP, autenticacao SCRAM, `set_config`, um `SELECT` — e nao o
    ponto critico. Com 250 ligacoes a abrir no mesmo instante, a dispersao de
    chegada ao `UPDATE` era de centenas de milissegundos contra um `UPDATE`
    sub-milissegundo, e a contencao que o AC-3 quer medir simplesmente nao
    acontecia. `aquecer` paga esse custo antes de todos se alinharem.
    """
    resultados: list = [None] * total
    for inicio in range(0, total, simultaneas):
        lote = list(range(inicio, min(inicio + simultaneas, total)))
        barreira = threading.Barrier(len(lote))

        def correr(indice: int):
            if aquecer is not None:
                try:
                    aquecer(indice)
                except Exception:  # noqa: BLE001 — aquecer e melhoria, nao requisito
                    pass
            try:
                barreira.wait(timeout=120)
            except threading.BrokenBarrierError:
                # **Isto nao e uma recusa, e a diferenca importa.** Se a
                # barreira parte (um thread morreu antes de chegar, ou passou o
                # tempo), os restantes nunca concorreram — e contar isso como
                # «o UPDATE recusou» era transformar uma falha do instrumento
                # em prova de que o isolamento funciona. Devolve-se um terceiro
                # estado, e quem le os resultados trata-o como nao medido.
                return ("barreira_partida", f"indice {indice}")
            try:
                return ("ok", trabalho(indice))
            except Exception as erro:  # noqa: BLE001 — recusar e um resultado
                return ("erro", f"{type(erro).__name__}: {erro}")

        with ThreadPoolExecutor(max_workers=len(lote)) as piscina:
            for indice, resultado in zip(lote, piscina.map(correr, lote)):
                resultados[indice] = resultado
    return resultados


# ---------------------------------------------------------------- ISO-51..56


def iso(porta: registo_mod.Registo, ambiente: dict, tenants: dict) -> list[Caso]:
    """A e B a competir pelo mesmo SKU global: contagens independentes."""
    a, b = tenants["A"], tenants["B"]
    ctx_a, ctx_b = Ctx(tenant_id=a.tenant_id), Ctx(tenant_id=b.tenant_id)
    casos: list[Caso] = []

    # Stock igual nos dois, e pequeno: 5 cada. Trinta tentativas de cada lado.
    sem.repor_stock(ambiente, a, sem.SKU_COLISAO, 5)
    sem.repor_stock(ambiente, b, sem.SKU_COLISAO, 5)

    def tentar(indice: int):
        tenant, ctx = (a, ctx_a) if indice % 2 == 0 else (b, ctx_b)
        chave = registo_mod.intent_key(ctx, tenant.contact_id, f"iso51-{indice}", 1)
        pedido = porta.create_order(
            ctx, tenant.contact_id, [Linha(sem.SKU_COLISAO, 1)], chave
        )["order_id"]
        porta.reserve_stock(ctx, str(pedido), 3600)
        return tenant.rotulo

    resultados = tempestade(60, 60, tentar)
    sucessos_a = sum(1 for e, v in resultados if e == "ok" and v == "A")
    sucessos_b = sum(1 for e, v in resultados if e == "ok" and v == "B")
    stock_a = _stock(ambiente, a.tenant_id, sem.SKU_COLISAO)
    stock_b = _stock(ambiente, b.tenant_id, sem.SKU_COLISAO)

    # **As assercoes exigem que a disputa tenha acontecido.** `sucessos <= 5`
    # e verdadeiro com zero sucessos: se as 60 tentativas falhassem todas (um
    # `repor_stock` que nao correu, ligacoes esgotadas), os quatro casos
    # seguintes davam verde a medir nada. Exige-se que cada tenant tenha
    # esgotado o seu stock — 5 sucessos de 30 tentativas — que e o resultado
    # certo quando ha contencao e contagens independentes.
    houve_disputa = sucessos_a == 5 and sucessos_b == 5
    if not houve_disputa:
        casos.append(Caso(
            "ISO-51", "Concorrencia",
            "30 tentativas de A e 30 de B ao mesmo SKU global, em simultaneo",
            "contagens independentes: cada tenant esgota o **seu** stock de 5",
            NAO_VERIFICADO,
            f"A: {sucessos_a} sucesso(s), B: {sucessos_b} — esperavam-se 5 e 5",
            f"nao houve a disputa que o caso mede; stock A={stock_a}, B={stock_b}"))
    else:
        casos.append(Caso(
            "ISO-51", "Concorrencia",
            "30 tentativas de A e 30 de B ao mesmo SKU global, em simultaneo",
            "contagens independentes: cada tenant esgota o **seu** stock de 5",
            PASSA,
            f"A: {sucessos_a}/5; B: {sucessos_b}/5 — cada um esgotou o seu",
            f"stock A={stock_a}, B={stock_b}"))

    casos.append(Caso(
        "ISO-52", "Concorrencia", "a reserva de A nao consome o stock de B",
        "reservada de B <= 5 e igual aos sucessos de B",
        PASSA if (houve_disputa and stock_b["reservada"] == sucessos_b) else (FALHA if houve_disputa else NAO_VERIFICADO),
        f"B reservada={stock_b['reservada']}, sucessos de B={sucessos_b}", ""))

    casos.append(Caso(
        "ISO-53", "Concorrencia", "a reserva de B nao consome o stock de A",
        "reservada de A <= 5 e igual aos sucessos de A",
        PASSA if (houve_disputa and stock_a["reservada"] == sucessos_a) else (FALHA if houve_disputa else NAO_VERIFICADO),
        f"A reservada={stock_a['reservada']}, sucessos de A={sucessos_a}", ""))

    casos.append(Caso(
        "ISO-54", "Concorrencia", "nenhum dos dois passa do proprio stock",
        "reservada <= quantidade nos dois",
        (PASSA if (stock_a["reservada"] <= stock_a["quantidade"]
                   and stock_b["reservada"] <= stock_b["quantidade"])
         else FALHA) if houve_disputa else NAO_VERIFICADO,
        f"A {stock_a['reservada']}/{stock_a['quantidade']}, "
        f"B {stock_b['reservada']}/{stock_b['quantidade']}",
        "o CHECK (reservada <= quantidade) e a ultima barreira"))

    # ISO-55: nenhuma reserva de A aponta para um SKU que nao e de A.
    cruzadas = _reservas_cruzadas(ambiente, a.tenant_id)
    casos.append(Caso(
        "ISO-55", "Concorrencia",
        "alguma reserva de A refere um SKU que nao existe em A",
        "0 reservas cruzadas", PASSA if cruzadas == 0 else FALHA,
        f"{cruzadas} reserva(s) cruzada(s)", ""))

    # ISO-56: A esgotado nao impede B de reservar.
    sem.repor_stock(ambiente, a, sem.SKU_COLISAO, 0)
    sem.repor_stock(ambiente, b, sem.SKU_COLISAO, 3)
    chave = registo_mod.intent_key(ctx_b, b.contact_id, "iso56", 1)
    try:
        pedido = porta.create_order(
            ctx_b, b.contact_id, [Linha(sem.SKU_COLISAO, 1)], chave)["order_id"]
        porta.reserve_stock(ctx_b, str(pedido), 3600)
        casos.append(Caso(
            "ISO-56", "Concorrencia",
            "A com stock 0 do SKU partilhado; B reserva 1 de 3",
            "B reserva sem ser afectado por A", PASSA, "B reservou", ""))
    except Exception as erro:  # noqa: BLE001
        casos.append(Caso(
            "ISO-56", "Concorrencia",
            "A com stock 0 do SKU partilhado; B reserva 1 de 3",
            "B reserva sem ser afectado por A", FALHA,
            "B foi recusado", f"{type(erro).__name__}: {erro}"))
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


def _reservas_cruzadas(ambiente, tenant_id: str) -> int:
    conexao = ligacao.ligar("batch", ambiente)
    try:
        cursor = conexao.cursor()
        cursor.execute(
            "SELECT count(*) FROM platform.stock_reservations r "
            " WHERE r.tenant_id = %s AND NOT EXISTS ("
            "   SELECT 1 FROM platform.spike_stock_levels s "
            "    WHERE s.tenant_id = r.tenant_id AND s.sku = r.sku)",
            (tenant_id,))
        return cursor.fetchone()[0]
    finally:
        conexao.close()


# ------------------------------------------------------------------- AC-3

def sobrevenda(porta: registo_mod.Registo, ambiente: dict, tenant,
               motor: str) -> dict:
    """1.000 tentativas sobre stock 10 em stock `garantido`. Devolve a contagem.

    Tres coisas que esta funcao aprendeu a medir, e que a primeira versao nao
    media:

    1. **Houve contencao?** `sucessos > 0 and recusas > 0` nao prova nada: mil
       tentativas estritamente **sequenciais** sobre stock 10 dao exactamente
       10 sucessos e 990 recusas, os mesmos numeros. Mede-se agora a
       **sobreposicao efectiva** — a maior quantidade de tentativas em voo ao
       mesmo tempo, contada por um contador que cada tentativa incrementa a
       entrada e decrementa a saida. Sem sobreposicao > 1, o zero nao significa
       nada e o resultado e `nao_verificado`.
    2. **Por que razao foram recusadas?** `tempestade` converte qualquer
       excepcao em recusa. Com 250 ligacoes a abrir ao mesmo tempo, um
       `FATAL: sorry, too many clients already` contava como «recusado por
       falta de stock». Agora as recusas sao classificadas, e as que nao sao
       por stock aparecem a parte.
    3. **Onde e que a contencao esteve?** A vaga 1 consome os 10 de stock; as
       vagas seguintes encontram `quantidade - reservada = 0` e sao recusadas
       sem disputar nada. O resultado e reportado **por vaga**, para nao se
       sugerir que mil tentativas disputaram dez unidades.

    E a ligacao abre-se **antes** da barreira: a barreira sincronizava a
    abertura da ligacao (TCP + SCRAM + `set_config` + um `SELECT`), nao o
    `UPDATE`, e a dispersao de chegada ao ponto critico era de centenas de ms
    contra um `UPDATE` sub-milissegundo.
    """
    sku = "SKU-AC3-SOBREVENDA"
    _criar_sku_proprio(ambiente, tenant, sku, 10)
    ctx = Ctx(tenant_id=tenant.tenant_id)

    # As encomendas criam-se **antes** da tempestade: o que o AC-3 mede e a
    # atomicidade da reserva, nao a da criacao da encomenda (isso e o AC-4).
    pedidos = []
    for indice in range(TENTATIVAS_AC3):
        chave = registo_mod.intent_key(ctx, tenant.contact_id, f"ac3-{motor}-{indice}", 1)
        pedidos.append(str(porta.create_order(
            ctx, tenant.contact_id, [Linha(sku, 1)], chave)["order_id"]))

    # Contador de sobreposicao: quantas tentativas estao em voo neste instante,
    # e qual foi o maximo. E a quantidade que o AC-3 existe para ter.
    em_voo = {"actual": 0, "maximo": 0}
    trinco = threading.Lock()

    def tentar(indice: int):
        with trinco:
            em_voo["actual"] += 1
            em_voo["maximo"] = max(em_voo["maximo"], em_voo["actual"])
        try:
            porta.reserve_stock(ctx, pedidos[indice], 3600, motor=motor)
            return indice
        finally:
            with trinco:
                em_voo["actual"] -= 1

    resultados = tempestade(TENTATIVAS_AC3, SIMULTANEAS, tentar,
                            aquecer=lambda _i: porta.aquecer(ctx))
    sucessos = sum(1 for estado, _ in resultados if estado == "ok")
    erros = [valor for estado, valor in resultados if estado == "erro"]
    barreiras_partidas = sum(1 for estado, _ in resultados
                             if estado == "barreira_partida")
    # «Sem stock» e a recusa legitima; qualquer outra coisa nao e uma recusa por
    # stock e nao pode ser contada como tal.
    por_stock = [e for e in erros if "sem stock" in e]
    outras = [e for e in erros if "sem stock" not in e]

    stock = _stock(ambiente, tenant.tenant_id, sku)
    reservas = _reservas_de(ambiente, tenant.tenant_id, sku)
    por_vaga = []
    for inicio in range(0, TENTATIVAS_AC3, SIMULTANEAS):
        lote = resultados[inicio:inicio + SIMULTANEAS]
        por_vaga.append({
            "vaga": inicio // SIMULTANEAS + 1,
            "sucessos": sum(1 for e, _ in lote if e == "ok"),
            "recusas": sum(1 for e, _ in lote if e == "erro"),
        })
    return {
        "motor": motor,
        "tentativas": TENTATIVAS_AC3,
        "por_vaga_de": SIMULTANEAS,
        "sobreposicao_maxima_observada": em_voo["maximo"],
        "stock_inicial": 10,
        "sucessos": sucessos,
        "recusas_por_falta_de_stock": len(por_stock),
        "recusas_por_outra_razao": len(outras),
        "primeiras_outras_recusas": outras[:3],
        "barreiras_partidas": barreiras_partidas,
        "reservada": stock.get("reservada"),
        "quantidade": stock.get("quantidade"),
        "linhas_de_reserva_activas": reservas,
        "acima_do_stock": max(0, reservas - 10),
        "por_vaga": por_vaga,
    }


def _criar_sku_proprio(ambiente: dict, tenant, sku: str, quantidade: int) -> None:
    """Um SKU so para este criterio, para nao herdar reservas de outro."""
    conexao = ligacao.ligar("batch", ambiente)
    conexao.autocommit = True
    cursor = conexao.cursor()
    try:
        cursor.execute(
            "INSERT INTO platform.offer_terms "
            "  (tenant_id, sku, preco_tipo, preco_minor, currency, stock_modo, "
            "   estado, preco_atualizado_at) "
            "VALUES (%s, %s, 'fixo', 1000, 'AOA', 'garantido', 'publicado', now()) "
            "ON CONFLICT (tenant_id, sku) DO UPDATE SET estado = 'publicado'",
            (tenant.tenant_id, sku))
        cursor.execute(
            "UPDATE platform.stock_reservations SET estado = 'libertada' "
            " WHERE tenant_id = %s AND sku = %s AND estado = 'ativa'",
            (tenant.tenant_id, sku))
        cursor.execute(
            "INSERT INTO platform.spike_stock_levels (tenant_id, sku, quantidade) "
            "VALUES (%s, %s, %s) "
            "ON CONFLICT (tenant_id, sku) DO UPDATE "
            "  SET quantidade = EXCLUDED.quantidade, reservada = 0",
            (tenant.tenant_id, sku, quantidade))
    finally:
        conexao.close()


def _reservas_de(ambiente, tenant_id: str, sku: str) -> int:
    conexao = ligacao.ligar("batch", ambiente)
    try:
        cursor = conexao.cursor()
        cursor.execute(
            "SELECT coalesce(sum(qty), 0) FROM platform.stock_reservations "
            " WHERE tenant_id = %s AND sku = %s AND estado = 'ativa'",
            (tenant_id, sku))
        return int(cursor.fetchone()[0])
    finally:
        conexao.close()


# ------------------------------------------------------------------- AC-4

def idempotencia(porta: registo_mod.Registo, ambiente: dict, tenant) -> dict:
    """50 repeticoes **concorrentes** de `create_order` com a mesma `intent_key`.

    Concorrentes e nao sequenciais: o `ON CONFLICT DO NOTHING` do §6.3 e trivial
    em serie. A barreira poe as cinquenta no `INSERT` ao mesmo tempo, que e onde
    a unicidade `(tenant_id, intent_key)` tem de decidir.
    """
    sem.repor_stock(ambiente, tenant, sem.SKU_COLISAO, 1000)
    ctx = Ctx(tenant_id=tenant.tenant_id)
    chave = registo_mod.intent_key(ctx, tenant.contact_id, "ac4-duplo-toque", 1)
    linhas = [Linha(sem.SKU_COLISAO, 1)]

    def tentar(_indice: int):
        return porta.create_order(ctx, tenant.contact_id, linhas, chave)

    resultados = tempestade(TENTATIVAS_AC4, TENTATIVAS_AC4, tentar)
    sucessos = [valor for estado, valor in resultados if estado == "ok"]
    erros = [valor for estado, valor in resultados if estado == "erro"]
    barreiras_partidas = sum(1 for estado, _ in resultados
                             if estado == "barreira_partida")
    criadas = sum(1 for valor in sucessos if valor.get("criada_agora"))
    ids = {str(valor.get("order_id")) for valor in sucessos if valor.get("order_id")}

    conexao = ligacao.ligar("batch", ambiente)
    try:
        cursor = conexao.cursor()
        cursor.execute(
            "SELECT count(*) FROM platform.orders_mirror "
            " WHERE tenant_id = %s AND intent_key = %s",
            (tenant.tenant_id, chave))
        na_base = cursor.fetchone()[0]
    finally:
        conexao.close()

    return {
        "tentativas": TENTATIVAS_AC4,
        "simultaneas": TENTATIVAS_AC4,
        "respostas_ok": len(sucessos),
        "respostas_com_erro": len(erros),
        "barreiras_partidas": barreiras_partidas,
        "criada_agora": criadas,
        "ids_distintos": len(ids),
        "encomendas_na_base": na_base,
        "primeiros_erros": erros[:3],
    }
