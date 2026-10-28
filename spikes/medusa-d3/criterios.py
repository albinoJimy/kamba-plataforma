"""AC-1..AC-10. Um criterio por funcao, e cada uma devolve numeros, nao opinioes.

Regra unica deste ficheiro: **o estado sai da medicao**. Nenhuma funcao devolve
`passa` por o codigo ter corrido; devolve `passa` porque um numero cumpriu um
limiar escrito no §4.3, e o numero vai no campo `medido` para o relatorio o
poder citar sem o reescrever.
"""

from __future__ import annotations

import json
import statistics
import time
import uuid
from pathlib import Path

import concorrencia
import contentor
import ee as ee_mod
import ligacao
import registo as registo_mod
import sementes as sem
from medir import FALHA, NAO_VERIFICADO, PASSA, Resultado
from registo import Ctx, Linha

#: Ids da matriz que contam para o AC-1: `ISO-NN`, dois digitos, e mais nada.
#: As sondas extra (por exemplo `ISO-48b`) medem-se e aparecem no relatorio,
#: mas **nao entram na contagem**: inflacionar os casos com linhas que o §4.4
#: nao nomeia era a forma mais barata de chegar a «>= 60».
import re

_ID_DA_MATRIZ = re.compile(r"^ISO-\d{2}$")

#: Periodo do varredor de expiracao do AC-6, em segundos.
#:
#: **Este numero e o p99 do AC-6, e e por isso que esta declarado.** O atraso
#: entre `expira_at` e a libertacao e dominado pelo periodo com que se varre;
#: escolher 0,2 s faz o `p99 <= 60 s` ser verdadeiro por construcao, e nao por
#: o mecanismo do §6.5 o garantir. O §6.5 tem um *job* repetivel a cada
#: **60 s** mais um *delayed job* por reserva — e nenhum dos dois esta
#: implementado aqui. O que o AC-6 mede e o **custo de processamento** da
#: libertacao (que e a parte em duvida), nao a cadencia; e o resultado diz isso.
PERIODO_DO_VARREDOR = 0.2

#: Amostras minimas para um percentil ter significado. O mesmo numero para o
#: AC-6 e para o AC-8: o argumento — «com 20 amostras, o p99 e o maximo com
#: outro nome» — vale para os dois, e estava aplicado so a um.
AMOSTRAS_MINIMAS = 100


def percentil(valores: list[float], fraccao: float) -> float | None:
    """O percentil pelo rank `ceil(n * fraccao)`, 1-indexado.

    A primeira versao usava `ordenados[int(n * fraccao) - 1]`, que so acerta
    quando `n * fraccao` e inteiro e que arredonda **para baixo** nos outros
    casos: para n=199 e p99 devolvia o 197.º de 199 em vez do 198.º. Um
    percentil enviesado para o optimista num criterio de aceitacao e um limiar
    mais frouxo do que o escrito.
    """
    if not valores:
        return None
    import math

    ordenados = sorted(valores)
    rank = max(1, math.ceil(len(ordenados) * fraccao))
    return ordenados[rank - 1]


def _criar_sku(ambiente: dict, tenant, sku: str, quantidade: int) -> None:
    """Cria (ou repoe) um SKU publicado so para um criterio.

    Existe para que um criterio nao herde reservas de outro: ver
    `_reservas_vencidas` e o comentario do AC-6.
    """
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
            "INSERT INTO platform.spike_stock_levels (tenant_id, sku, quantidade) "
            "VALUES (%s, %s, %s) "
            "ON CONFLICT (tenant_id, sku) DO UPDATE "
            "  SET quantidade = EXCLUDED.quantidade, reservada = 0",
            (tenant.tenant_id, sku, quantidade))
    finally:
        conexao.close()


# -------------------------------------------------------------------- AC-1

#: O conjunto que a matriz do §4.4 nomeia. **Exactamente** este.
ESPERADOS = frozenset(f"ISO-{numero:02d}" for numero in range(1, 61))


def ac1(casos: list) -> Resultado:
    da_matriz = [c for c in casos if _ID_DA_MATRIZ.match(c.id)]
    passes_indevidos = [c for c in da_matriz if c.estado == FALHA]
    nao_medidos = [c for c in da_matriz if c.estado == NAO_VERIFICADO]
    medidos = len(da_matriz) - len(nao_medidos)

    # **Confere o conjunto, e nao so a contagem.** Contar ids chegava a 60 com
    # um caso emitido duas vezes e outro em falta, e a cobertura da matriz
    # passava a depender de `iso.correr` emitir os blocos certos — sem nada que
    # o verificasse. O AC-1 e sobre «>= 60 casos» **da matriz do §4.4**, nao
    # sobre sessenta registos quaisquer.
    vistos = [c.id for c in da_matriz]
    duplicados = sorted({i for i in vistos if vistos.count(i) > 1})
    em_falta = sorted(ESPERADOS - set(vistos))
    intrusos = sorted(set(vistos) - ESPERADOS)

    detalhe = {
        "casos_da_matriz": len(da_matriz),
        "medidos": medidos,
        "passes_indevidos": len(passes_indevidos),
        "nao_medidos": [c.id for c in nao_medidos],
        "duplicados": duplicados,
        "em_falta": em_falta,
        "fora_da_matriz": intrusos,
        "falhas": [{"id": c.id, "cenario": c.cenario, "observado": c.observado,
                    "evidencia": c.evidencia} for c in passes_indevidos],
    }

    if duplicados or em_falta or intrusos:
        problemas = []
        if em_falta:
            problemas.append(f"{len(em_falta)} caso(s) em falta ({', '.join(em_falta)})")
        if duplicados:
            problemas.append(f"{len(duplicados)} duplicado(s) ({', '.join(duplicados)})")
        if intrusos:
            problemas.append(
                f"{len(intrusos)} id(s) que a matriz nao nomeia ({', '.join(intrusos)})")
        return Resultado(
            "AC-1", "Leituras/escritas cruzadas indevidas nos casos ISO (§4.4)",
            "0 passes indevidos em >= 60 casos", "Bloqueante", NAO_VERIFICADO,
            "a matriz emitida nao e a do §4.4: " + "; ".join(problemas),
            "spikes/medusa-d3/resultados/iso.json", detalhe)

    if passes_indevidos:
        estado = FALHA
        medido = (f"{len(passes_indevidos)} passe(s) indevido(s) em {medidos} "
                  f"caso(s) medido(s): {', '.join(c.id for c in passes_indevidos)}")
    elif medidos < 60:
        # A letra do criterio e «0 passes indevidos em >= 60 casos». Zero passes
        # indevidos em 56 casos medidos **nao** cumpre: sao 56. O estado fica
        # `falha` e nao `passa`, e a razao e nomeada.
        estado = FALHA
        medido = (f"0 passes indevidos, mas so {medidos} de 60 casos foram "
                  f"medidos ({len(nao_medidos)} nao verificados: "
                  f"{', '.join(c.id for c in nao_medidos)})")
    else:
        estado = PASSA
        medido = f"0 passes indevidos em {medidos} casos medidos"

    return Resultado(
        "AC-1", "Leituras/escritas cruzadas indevidas nos casos ISO (§4.4)",
        "0 passes indevidos em >= 60 casos", "Bloqueante", estado, medido,
        "spikes/medusa-d3/resultados/iso.json (um registo por caso, com a "
        "excepcao ou a contagem observada)", detalhe)


# -------------------------------------------------------------------- AC-2

def ac2(ambiente: dict, contentor_pg: str, contentor_medusa: str | None,
        saida: Path) -> Resultado:
    """Credenciais do admin Medusa fora da rede da aplicacao e dos tenants.

    Tres sondas, e as tres sao verificaveis sem opiniao:

    1. **Nenhuma porta do Medusa publicada no anfitriao.** O servidor corre com
       `--network container:<pg>`, e o unico contentor que publica porta e o do
       PostgreSQL (5432, so em 127.0.0.1). Se a 9000 estiver publicada, qualquer
       processo da maquina — e qualquer tenant com acesso a ela — alcanca o admin.
    2. **Um contentor noutra rede nao alcanca o Medusa.** E a sonda que o §4.4
       descreve no ISO-19 («token de operador usado a partir de rede de tenant»):
       aqui mede-se a rede, nao o token.
    3. **O codigo da porta nao tem credencial de admin.** O `docs/tecnica/08`
       §3.5 diz «nenhum agente nem tenant tem credenciais Store/Admin; COM usa
       conta de servico». Le-se o modulo da porta e o ambiente que ela recebe.
    """
    detalhe: dict = {}

    portas = contentor.docker("port", contentor_pg)
    publicadas_pg = [l for l in portas.stdout.strip().split("\n") if l.strip()]
    detalhe["portas_publicadas_pelo_postgres"] = publicadas_pg
    fuga_pg = [l for l in publicadas_pg if not l.startswith("5432/tcp")]

    if contentor_medusa:
        portas_medusa = contentor.docker("port", contentor_medusa)
        publicadas_medusa = [l for l in portas_medusa.stdout.strip().split("\n")
                             if l.strip()]
        detalhe["portas_publicadas_pelo_medusa"] = publicadas_medusa
    else:
        publicadas_medusa = []
        detalhe["portas_publicadas_pelo_medusa"] = "(Medusa nao esteve de pe)"

    # Sonda 2: um contentor **noutra rede** nao alcanca o Medusa.
    #
    # **Com controlo positivo, e e isso que a torna uma sonda.** A primeira
    # versao tentava `host.docker.internal:9000` e lia qualquer falha como
    # «recusado» — incluindo a falha de resolucao de nomes, que acontece fora do
    # Docker Desktop. O critico «nada de outra rede alcanca o Medusa» ficava
    # satisfeito por o DNS nao resolver, e a sonda nunca provava que **conseguia**
    # alcancar algo. Agora prova-se primeiro que a sonda funciona (a 5432 do
    # PostgreSQL **esta** publicada em 127.0.0.1 e tem de ser alcancavel do
    # anfitriao), e so depois se conclui algo do silencio da 9000.
    if contentor_medusa:
        porta_pg = contentor.docker("port", contentor_pg, "5432/tcp").stdout
        porta_pg = porta_pg.strip().rsplit(":", 1)[-1] if porta_pg.strip() else ""
        sonda = contentor.docker(
            "run", "--rm", "--network", "bridge",
            "--env", f"PORTA_PG={porta_pg}",
            contentor.IMAGEM_NODE, "sh", "-c",
            "node -e \""
            # Controlo positivo: um TCP cru a uma porta que **esta** publicada.
            "const net=require('node:net');"
            "const alvo=process.env.PORTA_PG;"
            "const liga=(p)=>new Promise(r=>{const s=net.connect("
            "{host:'host.docker.internal',port:p,timeout:5000});"
            "s.on('connect',()=>{s.destroy();r('ABRIU')});"
            "s.on('timeout',()=>{s.destroy();r('TIMEOUT')});"
            "s.on('error',e=>r('ERRO:'+e.code))});"
            "(async()=>{"
            "console.log('CONTROLO_5432 '+await liga(Number(alvo)));"
            "console.log('MEDUSA_9000 '+await liga(9000));"
            "})()\"",
            tempo=90,
        )
        resposta = (sonda.stdout + sonda.stderr).strip()
        detalhe["sonda_de_outra_rede"] = resposta[-400:]
        controlo_funciona = "CONTROLO_5432 ABRIU" in resposta
        alcancou = "MEDUSA_9000 ABRIU" in resposta
        detalhe["controlo_positivo_da_sonda"] = (
            "a sonda alcancou a 5432 publicada, logo sabe alcancar"
            if controlo_funciona
            else "a sonda **nao** alcancou a 5432, que esta publicada: a sonda "
                 "nao funciona, e o silencio da 9000 nao prova nada"
        )
    else:
        detalhe["sonda_de_outra_rede"] = "(Medusa nao esteve de pe)"
        detalhe["controlo_positivo_da_sonda"] = "(nao corrido)"
        controlo_funciona = False
        alcancou = False

    # Sonda 3: o modulo da porta e o ambiente que ela usa.
    fonte = (Path(__file__).resolve().parent / "registo.py").read_text(encoding="utf-8")
    suspeitas = [palavra for palavra in
                 ("MEDUSA_ADMIN_", "ADMIN_API_KEY", "admin_token", "x-medusa-access-token")
                 if palavra in fonte]
    detalhe["credenciais_de_admin_no_codigo_da_porta"] = suspeitas
    do_ambiente = sorted(k for k in ambiente if "MEDUSA" in k.upper())
    detalhe["variaveis_MEDUSA_no_ambiente_da_porta"] = do_ambiente

    (saida / "ac2-rede.json").write_text(
        json.dumps(detalhe, indent=2, ensure_ascii=False), encoding="utf-8")

    if not contentor_medusa:
        return Resultado(
            "AC-2", "Credenciais do admin Medusa fora da rede da aplicacao e dos tenants",
            "teste de rede verde", "Bloqueante", NAO_VERIFICADO,
            "nao medido: o Medusa nao esteve de pe, e a sonda de rede precisa de "
            "um alvo para falhar a alcancar",
            "spikes/medusa-d3/resultados/ac2-rede.json", detalhe)

    problemas = []
    if fuga_pg:
        problemas.append(f"o contentor da base publica {fuga_pg}")
    if publicadas_medusa:
        problemas.append(f"o Medusa publica {publicadas_medusa}")
    if alcancou:
        problemas.append("um contentor noutra rede alcancou a porta 9000 do Medusa")
    if suspeitas:
        problemas.append(f"o codigo da porta nomeia {suspeitas}")

    if problemas:
        estado = FALHA
    elif not controlo_funciona:
        # Sem controlo positivo, «ninguem alcancou» nao e um resultado: pode ser
        # a sonda a nao funcionar.
        return Resultado(
            "AC-2", "Credenciais do admin Medusa fora da rede da aplicacao e dos tenants",
            "teste de rede verde", "Bloqueante", NAO_VERIFICADO,
            "a sonda de outra rede nao alcancou nem a porta 5432, que **esta** "
            "publicada: nao se pode concluir nada do silencio da 9000",
            "spikes/medusa-d3/resultados/ac2-rede.json", detalhe)
    else:
        estado = PASSA
    medido = ("; ".join(problemas) if problemas else
              "0 portas do Medusa publicadas; sonda de outra rede recusada; "
              "0 credenciais de admin no codigo da porta")
    return Resultado(
        "AC-2", "Credenciais do admin Medusa fora da rede da aplicacao e dos tenants",
        "teste de rede verde", "Bloqueante", estado, medido,
        "spikes/medusa-d3/resultados/ac2-rede.json", detalhe)


# -------------------------------------------------------------------- AC-3

def ac3(ambiente: dict, tenants: dict, contentor_medusa: str | None) -> Resultado:
    """Sobrevenda em stock `garantido`: 1.000 tentativas, stock 10.

    Correm-se **dois motores** e comparam-se (ver `registo.reserve_stock`):
    o `UPDATE ... WHERE quantidade - reservada >= :q` do §6.4, e o Inventory
    Module do Medusa. Sem o comparador, um zero do Medusa nao se distingue de um
    zero por o teste nao ter concorrido.
    """
    porta = registo_mod.Registo(ambiente)
    tenant = tenants["A"]
    medicoes = {"sql": concorrencia.sobrevenda(porta, ambiente, tenant, "sql")}

    if contentor_medusa:
        try:
            import medusa as medusa_mod

            medicoes["medusa"] = medusa_mod.sobrevenda(tenants, contentor_medusa)
        except Exception as erro:  # noqa: BLE001
            medicoes["medusa"] = {"erro": f"{type(erro).__name__}: {erro}"}
    else:
        medicoes["medusa"] = {
            "erro": "o Medusa nao esteve de pe; a atomicidade da reserva do "
                    "Inventory Module continua NAO VERIFICADA (E4 §6)"
        }

    sql = medicoes["sql"]
    acima = sql["acima_do_stock"]
    sobreposicao = sql.get("sobreposicao_maxima_observada", 0)

    # **A guarda e a sobreposicao, e nao «houve sucessos e recusas».**
    #
    # Mil tentativas estritamente sequenciais sobre stock 10 dao exactamente 10
    # sucessos e 990 recusas — os mesmos numeros de uma tempestade. A guarda
    # antiga (`sucessos > 0 and recusas > 0`) nao distinguia as duas coisas, e
    # declarava verde sobre uma execucao que podia nao ter concorrido com nada.
    # O que se exige agora e a sobreposicao medida: quantas tentativas estiveram
    # em voo ao mesmo tempo. Sem sobreposicao, o zero nao significa nada.
    #
    # Fica dito, porque e um limite deste criterio e nao uma propriedade do
    # desenho: o mecanismo medido e um `UPDATE ... WHERE quantidade - reservada
    # >= :q`, **um unico comando**, que no PostgreSQL nao pode sobrevender a
    # nenhum grau de concorrencia. O AC-3 sobre este mecanismo confirma que o
    # mecanismo certo esta no lugar certo; nao e uma descoberta sobre atomicidade.
    # A medicao que podia falhar e a do caminho do Medusa, e e a que importa.
    minima_sobreposicao = 2
    if sql.get("barreiras_partidas"):
        estado = NAO_VERIFICADO
        medido = (f"motor sql: {sql['barreiras_partidas']} tentativa(s) com a "
                  "barreira partida — esse lote nao concorreu, e a medicao nao vale")
    elif sobreposicao < minima_sobreposicao:
        estado = NAO_VERIFICADO
        medido = (f"motor sql: sobreposicao maxima observada = {sobreposicao} "
                  "tentativa(s) em voo — nao houve contencao, e sem contencao "
                  "«0 reservas acima do stock» nao mede nada")
    elif sql.get("recusas_por_outra_razao"):
        estado = NAO_VERIFICADO
        medido = (f"motor sql: {sql['recusas_por_outra_razao']} recusa(s) por "
                  f"razao que nao e falta de stock "
                  f"({sql['primeiras_outras_recusas']}) — essas tentativas nao "
                  "disputaram stock, e a contagem nao e limpa")
    elif acima == 0:
        estado = PASSA
        medido = (f"motor sql: 0 reservas acima do stock "
                  f"({sql['sucessos']} sucessos, "
                  f"{sql['recusas_por_falta_de_stock']} recusas por falta de "
                  f"stock, reservada={sql['reservada']}/{sql['quantidade']}) em "
                  f"{sql['tentativas']} tentativas por vagas de "
                  f"{sql['por_vaga_de']}, com sobreposicao maxima medida de "
                  f"{sobreposicao} tentativas em voo")
    else:
        estado = FALHA
        medido = f"motor sql: {acima} reserva(s) acima do stock"

    # O lado Medusa **nao decide** o AC-3, e a razao esta escrita: o §6.4 poe a
    # autoridade da reserva no `platform` («sobrevenda impedida por
    # `UPDATE ... SET reservada = reservada + :q WHERE quantidade - reservada >= :q`»)
    # e deixa «ou *reservation items* do Medusa» como alternativa **a validar em
    # AC-3». E isso que se valida. Se o caminho do Medusa sobrevender, o AC-3
    # continua verde pelo mecanismo que o desenho usa — e a alternativa fica
    # reprovada, o que e um resultado do spike, nao uma falha do criterio.
    medusa = medicoes["medusa"]
    if "erro" in medusa:
        medido += ". O caminho do Medusa nao foi medido nesta execucao"
    else:
        partes = []
        for modo in ("modulo", "locking"):
            arm = medusa.get(modo)
            if isinstance(arm, dict) and "erro" not in arm:
                acima = arm.get("acima_do_stock")
                partes.append(
                    f"{modo}: {arm.get('sucessos')} reserva(s) aceita(s) sobre "
                    f"stock 10, {arm.get('linhas_de_reserva_criadas')} linha(s) "
                    f"de reserva criada(s), "
                    + (f"**{acima} acima do stock**" if acima
                       else "0 acima do stock")
                    + (f" — {arm['contador_divergente']}"
                       if arm.get("contador_divergente") else ""))
            elif isinstance(arm, dict):
                partes.append(f"{modo}: {arm['erro'][:80]}")
        if partes:
            medido += ". Caminho do Medusa — " + "; ".join(partes)

    return Resultado(
        "AC-3", "Sobrevenda em stock `garantido` (1.000 tentativas paralelas, stock 10)",
        "0 reservas acima do stock", "Bloqueante", estado, medido,
        "spikes/medusa-d3/resultados/resultados.json -> criterios[AC-3].detalhe; "
        "spikes/medusa-d3/resultados/medusa-ac3.json",
        medicoes)


# -------------------------------------------------------------------- AC-4

def ac4(ambiente: dict, tenants: dict) -> Resultado:
    porta = registo_mod.Registo(ambiente)
    medicao = concorrencia.idempotencia(porta, ambiente, tenants["B"])
    na_base = medicao["encomendas_na_base"]
    distintos = medicao["ids_distintos"]

    if medicao.get("barreiras_partidas"):
        estado = NAO_VERIFICADO
        medido = (f"{medicao['barreiras_partidas']} das {medicao['tentativas']} "
                  "repeticoes tiveram a barreira partida: nao foram concorrentes, "
                  "e o criterio pede **concorrentes**")
    elif (na_base == 1 and distintos == 1 and medicao["criada_agora"] == 1
          and medicao["respostas_com_erro"] == 0
          and medicao["respostas_ok"] == medicao["tentativas"]):
        # As quatro condicoes, e as duas ultimas nao estavam la. O §6.3 exige
        # «**mesma resposta** para N toques»: uma encomenda na base com dez
        # repeticoes a estourar o *poll* de 3 s nao e idempotencia cumprida — e
        # uma encomenda na base e dez clientes sem resposta.
        estado = PASSA
        medido = (f"1 encomenda na base, 1 id distinto devolvido as "
                  f"{medicao['respostas_ok']} respostas com sucesso "
                  f"({medicao['tentativas']} repeticoes concorrentes)")
    elif na_base == 1 and medicao["respostas_com_erro"]:
        estado = FALHA
        medido = (f"1 encomenda na base, mas {medicao['respostas_com_erro']} "
                  f"repeticao(oes) nao receberam a mesma resposta: "
                  f"{medicao['primeiros_erros']}")
    else:
        estado = FALHA
        medido = (f"{na_base} encomenda(s) na base, {distintos} id(s) distinto(s), "
                  f"{medicao['criada_agora']} criada(s) agora")

    return Resultado(
        "AC-4", "50 repeticoes concorrentes de `createOrder` com o mesmo `intent_key`",
        "1 encomenda", "Bloqueante", estado, medido,
        "spikes/medusa-d3/resultados/resultados.json -> criterios[AC-4].detalhe",
        medicao)


# -------------------------------------------------------------------- AC-5

def ac5(ambiente: dict, tenants: dict) -> Resultado:
    """Falha injectada entre criacao no Registo e escrita no `orders_mirror`.

    A saga do §6.3 passo 3 tem quatro escritas. A falha injecta-se **depois** do
    recibo de idempotencia (`order_intents`, `em_curso`) e **antes** do espelho:
    e o estado que o §6.3 passo 4 manda a reconciliacao resolver («intencoes
    `em_curso` > 2 min sao retomadas ou marcadas `falhada`») e o §10.3 item (1).

    Mede-se: quantos orfaos a reconciliacao deixou (tem de ser 0) e quanto tempo
    levou (tem de ser <= 5 min).
    """
    tenant = tenants["C"]
    ctx = Ctx(tenant_id=tenant.tenant_id)
    detalhe: dict = {}

    # Injecta a falha: recibo escrito, espelho nao. E o que uma saga interrompida
    # deixa atras de si.
    orfas = []
    conexao = ligacao.ligar("batch", ambiente)
    conexao.autocommit = True
    cursor = conexao.cursor()
    try:
        for indice in range(10):
            chave = registo_mod.intent_key(ctx, tenant.contact_id, f"ac5-{indice}", 1)
            cursor.execute(
                "INSERT INTO platform.order_intents "
                "  (tenant_id, intent_key, draft_hash, estado, criado_at) "
                "VALUES (%s, %s, %s, 'em_curso', now() - interval '3 minutes')",
                (tenant.tenant_id, chave,
                 registo_mod.draft_hash([Linha("SKU-C-UNICO", 1)], "levantamento")),
            )
            orfas.append(chave)
    finally:
        conexao.close()
    detalhe["intencoes_orfas_injectadas"] = len(orfas)

    inicio = time.monotonic()
    recuperadas, falhadas = _reconciliar(ambiente, tenant)
    duracao = time.monotonic() - inicio
    detalhe["segundos_da_reconciliacao"] = round(duracao, 3)
    detalhe["retomadas"] = recuperadas
    detalhe["marcadas_falhada"] = falhadas

    restantes = _orfas_abertas(ambiente, tenant.tenant_id)
    detalhe["orfas_abertas_depois"] = restantes
    divergencias = _divergencias_abertas(ambiente, tenant.tenant_id)
    detalhe["divergencias_abertas_mais_de_5_min"] = divergencias

    # A metade que precisa do Medusa: encomendas **no Registo** com `intent_key`
    # sem linha no espelho (§10.3 item 1 na direccao Registo -> espelho). Sem
    # Medusa, nao ha Registo onde injectar essa falha.
    detalhe["direccao_registo_para_espelho"] = (
        "NAO VERIFICADO: precisa de uma encomenda criada no Medusa sem espelho; "
        "o Medusa nao esteve de pe nesta execucao"
    )

    if restantes == 0 and divergencias == 0 and duracao <= 300:
        estado = PASSA
        medido = (f"{len(orfas)} intencoes orfas; reconciliacao em "
                  f"{duracao:.3f}s; 0 orfaos e 0 divergencias abertas depois")
    else:
        estado = FALHA
        medido = (f"{restantes} orfao(s) e {divergencias} divergencia(s) "
                  f"abertas depois de {duracao:.3f}s")

    if estado == PASSA:
        # Metade medida nao e o criterio inteiro. O §4.3 diz «falha injectada
        # **entre criacao no Registo** e escrita no `orders_mirror`»: a metade do
        # Registo nao correu, e por isso o criterio fica `parcial` — que neste
        # ficheiro se escreve `nao_verificado`, porque um bloqueante a meio nao
        # e um bloqueante verde.
        estado = NAO_VERIFICADO
        medido += (". Mas so a metade `platform` da saga foi medida: a falha "
                   "entre o **Registo** e o espelho precisa do Medusa de pe")

    return Resultado(
        "AC-5", "Falha injectada entre criacao no Registo e escrita no `orders_mirror`",
        "reconciliacao recupera <= 5 min, 0 orfaos", "Bloqueante", estado, medido,
        "spikes/medusa-d3/resultados/resultados.json -> criterios[AC-5].detalhe",
        detalhe)


def _reconciliar(ambiente: dict, tenant) -> tuple[int, int]:
    """O *job* do §10.3, na parte que o spike mede.

    Intencoes `em_curso` ha mais de 2 minutos: retoma-se (criando o espelho que
    faltou) ou marca-se `falhada`. Aqui retomam-se todas — e o caso em que o
    rascunho ainda e valido — e conta-se.
    """
    porta = registo_mod.Registo(ambiente)
    ctx = Ctx(tenant_id=tenant.tenant_id, actor_kind="sistema", actor_id="reconciliacao")
    conexao = ligacao.ligar("batch", ambiente)
    conexao.autocommit = True
    cursor = conexao.cursor()
    try:
        cursor.execute(
            "SELECT intent_key FROM platform.order_intents "
            " WHERE tenant_id = %s AND estado = 'em_curso' "
            "   AND criado_at < now() - interval '2 minutes'",
            (tenant.tenant_id,),
        )
        pendentes = [linha[0] for linha in cursor.fetchall()]
    finally:
        conexao.close()

    retomadas = falhadas = 0
    for chave in pendentes:
        try:
            # Apaga-se o recibo e volta-se a correr a saga pela porta: e a forma
            # de a retoma usar **o mesmo** caminho que a criacao, em vez de um
            # segundo caminho que podia divergir dele.
            conexao = ligacao.ligar("batch", ambiente)
            conexao.autocommit = True
            conexao.cursor().execute(
                "DELETE FROM platform.order_intents "
                " WHERE tenant_id = %s AND intent_key = %s",
                (tenant.tenant_id, chave))
            conexao.close()
            porta.create_order(ctx, tenant.contact_id,
                               [Linha("SKU-C-UNICO", 1)], chave)
            retomadas += 1
        except Exception:  # noqa: BLE001
            conexao = ligacao.ligar("batch", ambiente)
            conexao.autocommit = True
            conexao.cursor().execute(
                "UPDATE platform.order_intents SET estado = 'falhada' "
                " WHERE tenant_id = %s AND intent_key = %s",
                (tenant.tenant_id, chave))
            conexao.close()
            falhadas += 1
    return retomadas, falhadas


def _orfas_abertas(ambiente: dict, tenant_id: str) -> int:
    conexao = ligacao.ligar("batch", ambiente)
    try:
        cursor = conexao.cursor()
        cursor.execute(
            "SELECT count(*) FROM platform.order_intents i "
            " WHERE i.tenant_id = %s AND i.estado = 'em_curso' "
            "   AND i.criado_at < now() - interval '2 minutes'",
            (tenant_id,))
        return cursor.fetchone()[0]
    finally:
        conexao.close()


def _divergencias_abertas(ambiente: dict, tenant_id: str) -> int:
    conexao = ligacao.ligar("batch", ambiente)
    try:
        cursor = conexao.cursor()
        cursor.execute(
            "SELECT count(*) FROM platform.order_reconciliation_issues "
            " WHERE tenant_id = %s AND resolvido_at IS NULL "
            "   AND detectado_at < now() - interval '5 minutes'",
            (tenant_id,))
        return cursor.fetchone()[0]
    finally:
        conexao.close()


# -------------------------------------------------------------------- AC-6

def ac6(ambiente: dict, tenants: dict) -> Resultado:
    """Libertacao de reserva depois de `expira_at`: p99 <= 60 s.

    O mecanismo e o do §6.5: um varredor a cada segundo, com
    `FOR UPDATE SKIP LOCKED`, e **consulta final a PAY antes de libertar**. O
    PAY nao existe no spike; o varredor usa um PAY de teste que declara uma das
    reservas como paga, e o teste verifica que **essa nunca e libertada** — a
    propriedade do §6.5 que mais custa se falhar (libertar stock de uma
    encomenda ja paga).

    Para um p99 com significado medem-se 200 reservas. Com 20 amostras, o p99 e
    o maximo com outro nome.
    """
    tenant = tenants["A"]
    ctx = Ctx(tenant_id=tenant.tenant_id)
    total = 200
    # O SKU e **proprio deste criterio**. Com o `SKU_COLISAO`, o varredor
    # apanhava reservas que o AC-3 e a matriz ISO deixaram activas no mesmo
    # tenant: entravam na amostra com atrasos de minutos, envenenavam o p99, e
    # podiam encher `libertadas` antes de as 199 amostras reais existirem —
    # cortando a medicao. Um SKU proprio torna o criterio independente da ordem
    # em que `medir.correr` chama os outros.
    sku = "SKU-AC6-EXPIRACAO"
    _criar_sku(ambiente, tenant, sku, total + 10)

    # As encomendas pagas, declaradas **antes** de medir: o PAY de teste responde
    # por esta lista, e a porta consulta-o (ver `registo.release_reservation`).
    pagas: set[str] = set()
    porta = registo_mod.Registo(
        ambiente, consultar_pay=lambda _ctx, order_id: str(order_id) in pagas)

    pedidos = []
    for indice in range(total):
        chave = registo_mod.intent_key(ctx, tenant.contact_id, f"ac6-{indice}", 1)
        pedido = str(porta.create_order(
            ctx, tenant.contact_id, [Linha(sku, 1)], chave)["order_id"])
        # TTL curto para a medicao ser possivel; o TTL real e 24-72 h (§6.4). O
        # que se mede e o **atraso do varredor** depois de `expira_at`, e esse
        # nao depende do tamanho do TTL.
        #
        # **As expiracoes escalonam-se**, e nao e detalhe. Com as 200 reservas a
        # vencer no mesmo instante, o que se media era o tempo de drenar uma
        # avalanche — a primeira medicao deu mediana de 10,3 s e p99 de 19,7 s,
        # e esses numeros sao o comprimento da fila, nao a latencia do
        # mecanismo. O §6.5 tem um *job* repetivel por minuto **mais** um *job*
        # atrasado por reserva, precisamente para nao haver avalanche. Escalonar
        # mede o que o criterio quer: quanto tempo passa entre `expira_at` e a
        # libertacao.
        porta.reserve_stock(ctx, pedido, 2 + indice * 0.1)
        pedidos.append(pedido)

    # Uma das encomendas esta paga. O varredor **nao** a salta: chama a porta
    # como para as outras, e e a porta que recusa (consulta final a PAY, §6.5).
    paga = pedidos[0]
    pagas.add(paga)

    atrasos: list[float] = []
    libertadas: set[str] = set()
    recusadas_por_pagamento = 0
    outros_erros: list[str] = []
    # A ultima reserva vence a `2 + 199*0.1` = ~22 s; o limite da folga para o
    # varredor as apanhar todas sem cortar a amostra a meio.
    limite = time.monotonic() + 180
    while len(libertadas) < total - 1 and time.monotonic() < limite:
        vencidas = _reservas_vencidas(ambiente, tenant.tenant_id, sku)
        agora = time.time()
        for order_id, expira_at in vencidas:
            try:
                porta.release_reservation(ctx, order_id, "expirada")
            except registo_mod.PagamentoEncontradoNaConsultaFinal:
                recusadas_por_pagamento += 1
                continue
            except Exception as erro:  # noqa: BLE001
                outros_erros.append(f"{type(erro).__name__}: {erro}")
                continue
            atrasos.append(agora - expira_at.timestamp())
            libertadas.add(order_id)
        time.sleep(PERIODO_DO_VARREDOR)

    paga_libertada = _reservas_activas(ambiente, tenant.tenant_id, paga) == 0
    detalhe = {
        "reservas": total,
        "libertadas": len(libertadas),
        "periodo_do_varredor_s": PERIODO_DO_VARREDOR,
        "cadencia_do_paragrafo_6_5": "job repetivel a cada 60 s + delayed job por reserva",
        "poupada_por_estar_paga": paga,
        "recusadas_pela_consulta_a_pay": recusadas_por_pagamento,
        "outros_erros_do_varredor": outros_erros[:3],
        "a_paga_foi_libertada": paga_libertada,
        "atraso_min_s": round(min(atrasos), 3) if atrasos else None,
        "atraso_mediano_s": round(statistics.median(atrasos), 3) if atrasos else None,
        "atraso_p99_s": None,
        "atraso_max_s": round(max(atrasos), 3) if atrasos else None,
    }
    if len(atrasos) >= AMOSTRAS_MINIMAS:
        detalhe["atraso_p99_s"] = round(percentil(atrasos, 0.99), 3)

    if paga_libertada:
        return Resultado(
            "AC-6", "Libertacao de reserva apos `expira_at`", "p99 <= 60 s",
            "Bloqueante", FALHA,
            "a reserva de uma encomenda **paga** foi libertada: o §6.5 proibe-o "
            "(consulta final a PAY antes de libertar)",
            "spikes/medusa-d3/resultados/resultados.json -> criterios[AC-6].detalhe",
            detalhe)

    if detalhe["atraso_p99_s"] is None:
        return Resultado(
            "AC-6", "Libertacao de reserva apos `expira_at`", "p99 <= 60 s",
            "Bloqueante", NAO_VERIFICADO,
            f"so {len(atrasos)} amostra(s) de {total}: um p99 com menos de "
            f"{AMOSTRAS_MINIMAS} amostras e o maximo com outro nome",
            "spikes/medusa-d3/resultados/resultados.json -> criterios[AC-6].detalhe",
            detalhe)

    p99 = detalhe["atraso_p99_s"]
    if p99 > 60:
        return Resultado(
            "AC-6", "Libertacao de reserva apos `expira_at`", "p99 <= 60 s",
            "Bloqueante", FALHA,
            f"p99 = {p99}s em {len(atrasos)} amostras, acima do limiar, e com um "
            f"varredor de {PERIODO_DO_VARREDOR}s — ou seja o atraso nao vem da "
            "cadencia",
            "spikes/medusa-d3/resultados/resultados.json -> criterios[AC-6].detalhe",
            detalhe)

    # **O p99 cumpre o limiar, e isso nao basta para marcar a caixa.**
    #
    # O atraso medido e dominado pelo periodo do varredor do harness
    # (`PERIODO_DO_VARREDOR`), e esse e uma escolha deste teste, nao o
    # mecanismo do §6.5 — que tem um *job* repetivel a cada 60 s mais um
    # *delayed job* por reserva, e nenhum dos dois esta implementado aqui. Com
    # um varredor a 0,2 s, `p99 <= 60 s` seria verdadeiro qualquer que fosse o
    # desenho: mede-se o harness, nao o §6.5.
    #
    # O que a medicao **estabelece** e util e fica dito: o custo de
    # processamento da libertacao (ler as vencidas com `FOR UPDATE SKIP
    # LOCKED`, consultar o PAY, devolver o stock, marcar a reserva) e de
    # milissegundos, pelo que a cadencia pode ser escolhida livremente abaixo
    # de 60 s. Mas o criterio, a letra, nao esta verificado.
    return Resultado(
        "AC-6", "Libertacao de reserva apos `expira_at`", "p99 <= 60 s",
        "Bloqueante", NAO_VERIFICADO,
        f"p99 = {p99}s em {len(atrasos)} amostras (mediana "
        f"{detalhe['atraso_mediano_s']}s, max {detalhe['atraso_max_s']}s) — **mas "
        f"com um varredor a {PERIODO_DO_VARREDOR}s**, que e escolha do harness e "
        "nao o mecanismo do §6.5 (job de 60 s + delayed job por reserva, nenhum "
        "implementado). O numero mede o custo de processamento da libertacao, nao "
        f"a cadencia. A porta recusou libertar a encomenda paga "
        f"({recusadas_por_pagamento} recusa(s) pela consulta final a PAY), que e "
        "a propriedade do §6.5 que mais custa se falhar",
        "spikes/medusa-d3/resultados/resultados.json -> criterios[AC-6].detalhe",
        detalhe)


def _reservas_vencidas(ambiente: dict, tenant_id: str, sku: str):
    """`FOR UPDATE SKIP LOCKED` como o §6.5 manda, **restrito ao sku do AC-6**.

    O filtro por `sku` isola este criterio do estado que os outros deixam: sem
    ele, uma reserva que o AC-3 ou a matriz ISO deixaram activa no mesmo tenant
    entrava na amostra com um atraso de minutos.
    """
    conexao = ligacao.ligar("batch", ambiente)
    conexao.autocommit = False
    try:
        cursor = conexao.cursor()
        cursor.execute(
            "SELECT order_id, expira_at FROM platform.stock_reservations "
            " WHERE tenant_id = %s AND sku = %s AND estado = 'ativa' "
            "   AND expira_at <= now() "
            " FOR UPDATE SKIP LOCKED",
            (tenant_id, sku))
        linhas = [(str(l[0]), l[1]) for l in cursor.fetchall()]
        conexao.commit()
        return linhas
    finally:
        conexao.close()


def _reservas_activas(ambiente: dict, tenant_id: str, order_id: str) -> int:
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


# -------------------------------------------------------------------- AC-7

def ac7(pacote_medusa: dict | None, saida: Path,
        contentor_medusa: str | None = None) -> Resultado:
    projecto = Path(__file__).resolve().parent / "medusa"
    achados, resumo = ee_mod.verificar(projecto)
    resumo["achados"] = [str(a) for a in achados]

    # **O ambiente do contentor, e nao so os ficheiros.** As duas flags EE
    # ligam-se por variavel de ambiente (`MEDUSA_FF_RBAC`,
    # `MEDUSA_FF_RBAC_FILTER_FIELDS`), e `docker run --env` e exactamente como o
    # harness passa tudo o resto ao Medusa. Um verificador que lesse so
    # `medusa-config.ts` e `.env` dava verde com a flag ligada pela linha de
    # comandos — e era a forma mais natural de a ligar.
    if contentor_medusa:
        inspeccao = contentor.docker(
            "inspect", "--format", "{{range .Config.Env}}{{println .}}{{end}}",
            contentor_medusa)
        ambiente_do_contentor = [
            linha.strip() for linha in inspeccao.stdout.split("\n")
            if linha.strip().startswith("MEDUSA_FF_")
        ]
        resumo["flags_MEDUSA_FF_no_ambiente_do_contentor"] = ambiente_do_contentor
        for linha in ambiente_do_contentor:
            nome, _, valor = linha.partition("=")
            if valor.strip().lower() in ("true", "1", "yes", "on"):
                achados.append(ee_mod.Achado(
                    f"ambiente do contentor {contentor_medusa}", 0, nome,
                    "*feature flag* Enterprise ligada por variavel de ambiente"))
        resumo["achados"] = [str(a) for a in achados]
    else:
        resumo["flags_MEDUSA_FF_no_ambiente_do_contentor"] = (
            "(o Medusa nao esteve de pe; o ambiente do contentor nao foi lido)")
    if pacote_medusa:
        resumo["versao_instalada"] = pacote_medusa.get("versao")
        resumo["licenca_do_pacote"] = pacote_medusa.get("licenca")
        licenca = saida / "medusa-LICENSE.txt"
        if licenca.is_file():
            texto = licenca.read_text(encoding="utf-8", errors="replace")
            resumo["licenca_primeiras_linhas"] = texto[:1200]
            resumo["licenca_menciona_enterprise"] = "nterprise" in texto

    (saida / "ac7-ee.json").write_text(
        json.dumps(resumo, indent=2, ensure_ascii=False), encoding="utf-8")

    if achados:
        return Resultado(
            "AC-7", "Modulo ou *flag* Enterprise (`rbac`, `auth-oidc`, `policies`) activo",
            "0; teste de CI verde", "Bloqueante", FALHA,
            f"{len(achados)} achado(s): {'; '.join(str(a) for a in achados)}",
            "spikes/medusa-d3/resultados/ac7-ee.json; `python spikes/medusa-d3/ee.py`",
            resumo)

    # **O que o AC-7 exige para ser verde, e porque.** O criterio e «0 modulos
    # ou flags Enterprise activos; teste de CI verde». Tres superficies, e
    # nenhuma dispensavel:
    #
    #   configuracao   `medusa-config.ts`, `package.json`, `.env`  — sempre lida
    #   fecho          `package-lock.json` — diz **quem** arrasta cada pacote EE
    #   ambiente       as variaveis do contentor que corre o Medusa
    #
    # Verde sem o ambiente seria verde sem ter olhado para o caminho pelo qual
    # a flag mais facilmente se liga. A versao anterior dava `PASSA` com
    # `node_modules_lido=false` e sem olhar ao ambiente: o `medido` nomeava a
    # lacuna, mas o **estado** era verde, e e o estado que a arvore do §4.5 le.
    faltam = []
    if not resumo.get("fecho_lido"):
        faltam.append("o fecho (`package-lock.json`)")
    if contentor_medusa is None:
        faltam.append("o ambiente do contentor do Medusa")
    if faltam:
        return Resultado(
            "AC-7", "Modulo ou *flag* Enterprise (`rbac`, `auth-oidc`, `policies`) activo",
            "0; teste de CI verde", "Bloqueante", NAO_VERIFICADO,
            "a configuracao esta limpa, mas nao se leu " + " nem ".join(faltam)
            + " — e sem isso nao se pode dizer que nada EE esta activo",
            "spikes/medusa-d3/resultados/ac7-ee.json; "
            "`python spikes/medusa-d3/ee.py`", resumo)

    medido = ("0 modulos e 0 flags Enterprise activos: configuracao, fecho e "
              "ambiente do contentor lidos")
    na_arvore = resumo.get("ee_na_arvore") or []
    if na_arvore:
        medido += (f"; {len(na_arvore)} pacote(s) EE **na arvore** sem estarem "
                   "activos ("
                   + ", ".join(f"{r['pacote']}@{r['versao']}" for r in na_arvore)
                   + "), arrastados pelo `@medusajs/medusa` — a licenca "
                     "condiciona activar, nao possuir")
    if not resumo.get("node_modules_lido"):
        medido += ("; a arvore instalada nao esta nesta pasta (o `npm ci` "
                   "instala para um volume nomeado), pelo que a leitura do EE "
                   "foi pelo fecho")
    estado = PASSA
    return Resultado(
        "AC-7", "Modulo ou *flag* Enterprise (`rbac`, `auth-oidc`, `policies`) activo",
        "0; teste de CI verde", "Bloqueante", estado, medido,
        "spikes/medusa-d3/resultados/ac7-ee.json; `python spikes/medusa-d3/ee.py` "
        "(sai 0/1/2 e serve de gate)", resumo)


# -------------------------------------------------------------------- AC-8

def ac8(ambiente: dict, tenants: dict) -> Resultado:
    """`createOrder` (sem LLM) a 20 pedidos/s: p95 <= 800 ms (*proposta*).

    Taxa **oferecida** de 20/s durante 60 s = 1.200 amostras. Oferecida e nao
    alcancada: se o sistema nao acompanhar, o atraso aparece na latencia, que e
    o que se quer medir. Mede-se so a porta, sem LLM, como o criterio diz.
    """
    porta = registo_mod.Registo(ambiente)
    tenant = tenants["B"]
    ctx = Ctx(tenant_id=tenant.tenant_id)
    sem.repor_stock(ambiente, tenant, "SKU-B-UNICO", 100_000)

    duracao_alvo = 60.0
    taxa = 20.0
    total = int(duracao_alvo * taxa)
    latencias: list[float] = []
    erros: list[str] = []

    # **Os pedidos saem concorrentes, e nao em serie.**
    #
    # A primeira versao deste criterio emitia um pedido, esperava a resposta e
    # so depois emitia o seguinte. Com uma latencia mediana de ~58 ms, isso
    # limita a taxa a ~17/s por construcao: a medicao dizia «p95 = 87 ms a
    # 15,9/s alcancados», ou seja media uma fila de um, nao 20 pedidos/s. O
    # criterio diz **a 20 pedidos/s**, e a 20/s a porta tem de ter mais do que
    # um pedido em voo. Um emissor com relogio proprio oferece a taxa; os
    # pedidos correm numa piscina e a latencia inclui a espera, que e
    # exactamente o que um p95 a 20/s tem de apanhar.
    from concurrent.futures import ThreadPoolExecutor

    inicio = time.monotonic()

    def pedir(indice: int, submetido_em: float):
        """`submetido_em` e o instante em que o pedido **devia** ter saido.

        A latencia conta-se de la, e nao de quando o trabalhador pegou na
        tarefa. A primeira versao punha o `t0` dentro desta funcao: o tempo em
        fila ficava invisivel, e o p95 media o tempo de servico de uma porta
        que podia estar 15 s atrasada. A 20 pedidos/s o que interessa e a
        latencia que o cliente ve, que inclui a espera.
        """
        chave = registo_mod.intent_key(ctx, tenant.contact_id, f"ac8-{indice}", 1)
        try:
            porta.create_order(ctx, tenant.contact_id,
                               [Linha("SKU-B-UNICO", 1)], chave)
            return ("ok", (time.perf_counter() - submetido_em) * 1000)
        except Exception as erro:  # noqa: BLE001
            return ("erro", f"{type(erro).__name__}: {erro}")

    # 64 trabalhadores: folga sobre os 20/s desejados para que a taxa oferecida
    # nao seja limitada pela piscina. `max_connections=400` no contentor.
    with ThreadPoolExecutor(max_workers=64) as piscina:
        pendentes = []
        for indice in range(total):
            quando = inicio + indice / taxa
            atraso = quando - time.monotonic()
            if atraso > 0:
                time.sleep(atraso)
            pendentes.append(piscina.submit(pedir, indice, time.perf_counter()))
        for pendente in pendentes:
            estado, valor = pendente.result()
            if estado == "ok":
                latencias.append(valor)
            else:
                erros.append(valor)
    decorrido = time.monotonic() - inicio

    # **Quanto custa abrir uma ligacao, medido.** Sem este numero o p95 nao se
    # interpreta: a porta do spike abre **uma ligacao por operacao** (ver
    # `registo._abrir`, que o faz de proposito para o `SET LOCAL app.tenant_id`
    # nao sobreviver a uma chamada), e se o custo dominante for o `connect` +
    # SCRAM, o p95 esta a medir a ausencia de um *pool* e nao a porta. Quem ler
    # o AC-8 tem de poder separar as duas coisas.
    amostras_de_ligacao = []
    for _ in range(30):
        t0 = time.perf_counter()
        try:
            ligacao.ligar("app", ambiente).close()
            amostras_de_ligacao.append((time.perf_counter() - t0) * 1000)
        except Exception:  # noqa: BLE001
            break

    ordenadas = sorted(latencias)
    detalhe = {
        "custo_de_abrir_ligacao_mediano_ms": (
            round(statistics.median(amostras_de_ligacao), 1)
            if amostras_de_ligacao else None),
        "nota_sobre_o_pool": (
            "a porta abre uma ligacao por operacao, de proposito (o contexto de "
            "tenant e `SET LOCAL` e nao deve sobreviver a chamada). Um adaptador "
            "de producao usa um *pool* com o contexto reposto por transaccao; "
            "comparar o p95 com o custo de ligacao diz quanto do p95 e isso"),
        "amostras": len(latencias),
        "erros": len(erros),
        "primeiros_erros": erros[:3],
        "taxa_oferecida_por_s": taxa,
        "taxa_alcancada_por_s": round(len(latencias) / decorrido, 2) if decorrido else None,
        "segundos": round(decorrido, 1),
        "p50_ms": round(statistics.median(ordenadas), 1) if ordenadas else None,
        "p95_ms": (round(percentil(ordenadas, 0.95), 1)
                   if len(ordenadas) >= AMOSTRAS_MINIMAS else None),
        "p99_ms": (round(percentil(ordenadas, 0.99), 1)
                   if len(ordenadas) >= AMOSTRAS_MINIMAS else None),
        "max_ms": round(max(ordenadas), 1) if ordenadas else None,
    }
    if detalhe["p95_ms"] is None:
        return Resultado(
            "AC-8", "`createOrder` (sem LLM) a 20 pedidos/s", "p95 <= 800 ms (*proposta*)",
            "Alvo", NAO_VERIFICADO,
        f"so {len(latencias)} amostra(s); um p95 com menos de "
        f"{AMOSTRAS_MINIMAS} nao tem significado",
            "spikes/medusa-d3/resultados/resultados.json -> criterios[AC-8].detalhe",
            detalhe)
    p95 = detalhe["p95_ms"]
    alcancada = detalhe["taxa_alcancada_por_s"] or 0
    # **A taxa alcancada entra na decisao.** O limiar e «p95 <= 800 ms **a 20
    # pedidos/s**»: um p95 bonito a 5/s nao cumpre o criterio, cumpre outro. A
    # primeira versao calculava a taxa, imprimia-a, e nao a usava — e passou com
    # 15,9/s alcancados de 20 oferecidos.
    #
    # Tolera-se 5% abaixo dos 20/s: o emissor dorme com o relogio do sistema e
    # nao e um gerador de carga. Mais do que isso e o sistema a nao acompanhar,
    # que e precisamente o que o criterio quer saber.
    taxa_minima = taxa * 0.95
    if alcancada < taxa_minima:
        return Resultado(
            "AC-8", "`createOrder` (sem LLM) a 20 pedidos/s",
            "p95 <= 800 ms (*proposta*)", "Alvo", NAO_VERIFICADO,
            f"p95 = {p95} ms, mas so se alcancaram {alcancada}/s dos {taxa:.0f}/s "
            f"oferecidos ({len(erros)} erro(s)): o limiar e a 20 pedidos/s, e a "
            "carga nao foi sustentada — o numero nao responde ao criterio",
            "spikes/medusa-d3/resultados/resultados.json -> criterios[AC-8].detalhe",
            detalhe)
    if erros and len(erros) > total * 0.01:
        return Resultado(
            "AC-8", "`createOrder` (sem LLM) a 20 pedidos/s",
            "p95 <= 800 ms (*proposta*)", "Alvo", NAO_VERIFICADO,
            f"p95 = {p95} ms sobre {len(latencias)} amostras, mas {len(erros)} de "
            f"{total} pedidos falharam ({detalhe['primeiros_erros']}): um p95 que "
            "exclui os pedidos que falharam nao mede a latencia do servico",
            "spikes/medusa-d3/resultados/resultados.json -> criterios[AC-8].detalhe",
            detalhe)
    return Resultado(
        "AC-8", "`createOrder` (sem LLM) a 20 pedidos/s", "p95 <= 800 ms (*proposta*)",
        "Alvo", PASSA if p95 <= 800 else FALHA,
        f"p95 = {p95} ms em {len(latencias)} amostras a {alcancada}/s alcancados "
        f"de {taxa:.0f}/s oferecidos (p50 {detalhe['p50_ms']} ms, max "
        f"{detalhe['max_ms']} ms), latencia contada desde a submissao",
        "spikes/medusa-d3/resultados/resultados.json -> criterios[AC-8].detalhe",
        detalhe)


# -------------------------------------------------------------------- AC-9

def ac9() -> Resultado:
    """Esforco para impor o filtro de tenant em todos os repositorios do COM.

    **Isto e uma estimativa, nao uma medicao**, e por isso vai marcada como
    *proposta*. O que lhe da base e o que este spike custou de facto a escrever,
    contado por ficheiro, mais a contagem das superficies que o KAM-042 tem de
    cobrir. Uma estimativa sem base e um numero que alguem depois cita como
    requisito.
    """
    aqui = Path(__file__).resolve().parent
    porta = (aqui / "registo.py").read_text(encoding="utf-8")
    metodos_implementados = porta.count("\n    def ") - porta.count("\n    def _")
    # Os onze metodos do §3.2.
    metodos_do_contrato = 11
    tabelas_com_tenant = 8  # as do `02_rls.sql`

    detalhe = {
        "base_da_estimativa": (
            "o spike implementou a porta minima (`registo.py`) com o filtro de "
            "tenant imposto em todas as leituras e escritas, e a RLS por cima; "
            "o KAM-042 tem de cobrir os 11 metodos do §3.2, o repositorio base "
            "que injecta `merchant_id`/`tenant_id`, a pipeline de migracoes e a "
            "suite ISO ligada ao CI"
        ),
        "metodos_da_porta_implementados_no_spike": metodos_implementados,
        "metodos_do_contrato_do_paragrafo_3_2": metodos_do_contrato,
        "tabelas_com_tenant_id_sob_RLS_no_spike": tabelas_com_tenant,
        "o_que_a_estimativa_nao_cobre": [
            "o adaptador para o Medusa (produtos, inventario, pricing), que o "
            "spike so toca de raspao",
            "a projeccao `catalog.product_changed` por *subscriber* do Medusa",
            "o modulo `servicos` (KAM-047), que tem a sua propria estimativa",
        ],
        "estimativa_dias_pessoa": "2 a 3",
        "estado": "proposta",
        "onde_se_calibra": (
            "no KAM-042, que e o ticket que faz o trabalho: o seu tempo real "
            "substitui este numero"
        ),
    }
    # **Estado `nao_verificado`, e nao `passa`.** Um criterio que nao tem ramo
    # de falha nao e evidencia: devolvia verde qualquer que fosse a estimativa,
    # e a arvore do §4.5 ramifica em «AC-9 <= 3 dias?». O que existe e uma
    # estimativa com base declarada, e uma estimativa nao e uma medicao — quem
    # a le decide o que faz com ela, em vez de receber um verde que nada mediu.
    # O valor vai no `medido`, que e onde o relatorio o cita.
    return Resultado(
        "AC-9", "Esforco para impor o filtro de tenant em todos os repositorios do COM",
        "<= 3 dias-pessoa", "Alvo", NAO_VERIFICADO,
        "nao medido — **estimativa** de 2 a 3 dias-pessoa (*proposta*), que "
        "cumpre o limiar mas nao o mede: a porta minima com filtro em todas as "
        f"operacoes e RLS por cima saiu em {metodos_implementados} metodos neste "
        f"spike, contra {metodos_do_contrato} do contrato do §3.2. Calibra-se no "
        "KAM-042, que e o ticket que faz o trabalho",
        "spikes/medusa-d3/resultados/resultados.json -> criterios[AC-9].detalhe",
        detalhe)


# ------------------------------------------------------------------- AC-10

def ac10(ambiente: dict, contentor_medusa: str | None, saida: Path) -> Resultado:
    """Actualizacao minor (*dry-run*) sem perda de dados nem alteracao do contrato.

    Precisa de duas arvores instaladas (2.21.2 e 2.22.x) e de correr as
    migracoes da segunda contra o schema da primeira. Quando o Medusa nao esteve
    de pe, nao ha schema do Medusa para migrar — e o criterio fica NAO
    VERIFICADO, nomeado, com o que falta.
    """
    detalhe = {
        "versao_de_partida": "2.21.2 (a ultima 2.21.x publicada; ver o relatorio)",
        "versao_de_chegada": "2.22.1",
        "o_que_falta": None,
    }
    if contentor_medusa is None:
        detalhe["o_que_falta"] = (
            "o Medusa nao esteve de pe: sem `medusa db:migrate` da 2.21.2 nao ha "
            "schema de partida, e sem ele o *dry-run* da 2.22.1 nao mede nada"
        )
        return Resultado(
            "AC-10", "Actualizacao minor (*dry-run*) sem perda de dados nem "
                     "alteracao do contrato da porta",
            "sim", "Alvo", NAO_VERIFICADO,
            "nao medido: o Medusa nao esteve de pe nesta execucao",
            "—", detalhe)

    # Com o Medusa de pe: compara-se o contrato da porta (que e nosso e nao muda
    # com a versao do Medusa) e conta-se o schema antes e depois.
    antes = _contar_schema(ambiente, "public")
    detalhe["tabelas_do_medusa_antes"] = antes
    detalhe["o_que_falta"] = (
        "o *dry-run* da 2.22.1 exige uma segunda arvore `npm ci` (2.22.1) e "
        "correr as suas migracoes contra este schema; nesta execucao instalou-se "
        "so a 2.21.2"
    )
    detalhe["contrato_da_porta"] = (
        "inalterado por construcao: a porta `CommerceRegistry` e nossa (§3.2) e "
        "o Medusa esta atras dela. O que uma minor pode quebrar e o adaptador, "
        "nao o contrato — e e isso que o AC-10 tem de medir, no KAM-042"
    )
    return Resultado(
        "AC-10", "Actualizacao minor (*dry-run*) sem perda de dados nem "
                 "alteracao do contrato da porta",
        "sim", "Alvo", NAO_VERIFICADO,
        f"parcial: contaram-se {antes} tabela(s) do Medusa em `public` antes da "
        "actualizacao, mas o *dry-run* da 2.22.1 nao correu",
        "spikes/medusa-d3/resultados/resultados.json -> criterios[AC-10].detalhe",
        detalhe)


def _contar_schema(ambiente: dict, schema: str) -> int:
    conexao = ligacao.ligar("admin", ambiente)
    try:
        cursor = conexao.cursor()
        cursor.execute(
            "SELECT count(*) FROM information_schema.tables WHERE table_schema = %s",
            (schema,))
        return cursor.fetchone()[0]
    finally:
        conexao.close()
