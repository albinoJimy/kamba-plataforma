"""As regras do gate do Piloto, transcritas das fontes e não interpretadas.

Quatro regras, cada uma com a fonte ao lado:

    estado efectivo   bloco KAM-110, critério A e «Detalhes Técnicos»
    matriz            `14` §6, e o critério C do bloco para o que §6 não cobre
    paragem total     `14` §6, a última frase
    Carta §5          a Definition-of-Done do Piloto, item a item

Nenhuma delas produz uma decisão. A matriz devolve **a linha de `14` §6 que uma
falha acciona**, que é o que o critério C pede que se aplique; escolher entre
CONTINUAR, PIVÔ e PARAR é do fundador.
"""

from __future__ import annotations

import re
from dataclasses import dataclass
from pathlib import Path

from .entradas import Resumo
from .registo import HIPOTESES, POR_MEDIR, Linha

#: Amostras mínimas que as fontes escrevem por extenso. **Só estas duas**: onde
#: a fonte não escreve um mínimo, o gerador não o inventa.
AMOSTRA_MINIMA = {
    "H6": (500, "conversas reais (Carta §5; KAM-109, critério H6)"),
    "H9": (8, "PMEs com 60 dias de exposição (KAM-109, critério H9)"),
}


@dataclass(frozen=True)
class Estado:
    h: str
    declarado: str
    efectivo: str
    razoes: tuple[str, ...]


def _amostra(celula: str) -> int | None:
    """O número à cabeça da célula: «512 conversas» dá 512, «—» dá nada."""
    achado = re.fullmatch(r"(\d+)(\s.*)?", celula.strip())
    return int(achado.group(1)) if achado else None


#: As quatro que o KAM-109 mede. O *handoff* dele: «Não declares nenhuma hipótese
#: confirmada sem dados exportados e congelados» — e o gate não as aceita sem a
#: exportação congelada nomeada no resumo, com o seu *hash*.
DO_KAM_109 = ("H1", "H6", "H8", "H9")


def estado_efectivo(linha: Linha, congelada: bool = False) -> Estado:
    """`confirmada` e `refutada` só sobrevivem com dados; o resto é `inconclusiva`.

    Critério A: «uma hipótese sem dados é `inconclusiva`, nunca `confirmada`».
    Aplica-se também a `refutada`: uma refutação sobre amostra zero é uma
    conclusão tirada da falta de dados, e accionava um pivô por nada.
    """
    razoes: list[str] = []
    if linha.h in DO_KAM_109 and not congelada:
        razoes.append("sem exportação congelada do KAM-109 no resumo")
    n = _amostra(linha.amostra)
    if not n:
        razoes.append("amostra n vazia ou zero")
    if not linha.resultado or linha.resultado.upper() == POR_MEDIR:
        razoes.append("resultado não medido")
    if not linha.fonte:
        razoes.append("sem ficheiro de evidência na coluna fonte")
    if n and linha.h in AMOSTRA_MINIMA:
        minimo, de_que = AMOSTRA_MINIMA[linha.h]
        if n < minimo:
            razoes.append(f"amostra {n} < {minimo} {de_que}")
    if not linha.estado:
        razoes.append("estado por decidir")

    efectivo = linha.estado if linha.estado and not razoes else "inconclusiva"
    return Estado(linha.h, linha.estado, efectivo, tuple(razoes))


def estados(linhas: dict[str, Linha], resumo: Resumo) -> dict[str, Estado]:
    congelada = resumo.exportacao_sha256 is not None
    return {h: estado_efectivo(linhas[h], congelada) for h in HIPOTESES}


# --- a matriz de `14` §6 ---------------------------------------------------

#: A coluna «Então…» de `14` §6, palavra a palavra. As chaves agrupam o que a
#: fonte agrupa: «H4 ou H3 falham» é uma linha só.
LINHAS_14_6 = {
    "H1": "Voltar às entrevistas: mudar segmento ou produto (candidato: Factura AI isolada)",
    "H3/H4": "Mudar de canal: BSP parceiro, outro número, ou produto sem automação no WhatsApp da PME",
    "H5": "Manter camadas 1–2; vender atendimento/agenda sem cobrança integrada",
    "H2": "Reposicionar: atendimento e disponibilidade, não comparação de preço",
    "H6": "Subir preço, reduzir modelo/voz, ou limitar volume por plano",
    "canal": "Antes de construir mais, resolver distribuição: parceiro de banco, associação ou contratar comercial",
}

#: H7, H8 e H9 não têm linha em `14` §6. O critério C manda o gate decidir e
#: registar a acção; escrever aqui uma acção plausível era inventá-la.
SEM_LINHA = "Sem linha em `14` §6: o gate decide e regista a acção (critério C)"

_CHAVE_DA_MATRIZ = {
    "H1": "H1", "H2": "H2", "H3": "H3/H4", "H4": "H3/H4", "H5": "H5", "H6": "H6",
}


@dataclass(frozen=True)
class Accionada:
    gatilho: str  # «H1», «H3, H4», «canal»
    linha: str


def matriz(efectivos: dict[str, Estado], resumo: Resumo) -> list[Accionada]:
    """As linhas de `14` §6 que as falhas accionam, pela ordem da tabela da fonte."""
    por_chave: dict[str, list[str]] = {}
    sem_linha: list[str] = []
    for h in HIPOTESES:
        if efectivos[h].efectivo != "refutada":
            continue
        chave = _CHAVE_DA_MATRIZ.get(h)
        if chave is None:
            sem_linha.append(h)
        else:
            por_chave.setdefault(chave, []).append(h)
    if resumo.canais_de_acesso_mantidos == 0:
        por_chave["canal"] = ["nenhum canal de acesso mantido (KAM-106)"]
    accionadas = [
        Accionada(", ".join(por_chave[chave]), texto)
        for chave, texto in LINHAS_14_6.items()
        if chave in por_chave
    ]
    accionadas.extend(Accionada(h, SEM_LINHA) for h in sem_linha)
    return accionadas


# --- a paragem total ---------------------------------------------------------

PARAGEM = (
    "ao fim de 12 semanas não houver ≥ 3 pagantes recorrentes "
    "e nenhum canal comercial repetível"
)


def paragem_total(resumo: Resumo) -> tuple[str, str]:
    """`verificada`, `nao_verificada` ou `nao_avaliavel`, e porquê.

    Nunca `nao_verificada` por falta de um dado: a ausência de um número não é a
    prova de que a condição não se cumpre.
    """
    faltam = [
        nome
        for nome, valor in (
            ("semana_do_gate", resumo.semana_do_gate),
            ("pagantes_recorrentes", resumo.pagantes_recorrentes),
            ("canal_comercial_repetivel", resumo.canal_comercial_repetivel),
        )
        if valor is None
    ]
    if faltam:
        return "nao_avaliavel", f"falta {', '.join(faltam)}"
    if resumo.semana_do_gate < 12:
        return "nao_avaliavel", f"semana {resumo.semana_do_gate} de 12"
    if resumo.pagantes_recorrentes < 3 and not resumo.canal_comercial_repetivel:
        return "verificada", (
            f"{resumo.pagantes_recorrentes} pagantes recorrentes e nenhum canal "
            "comercial repetível"
        )
    return "nao_verificada", (
        f"{resumo.pagantes_recorrentes} pagantes recorrentes; canal comercial "
        f"repetível: {'sim' if resumo.canal_comercial_repetivel else 'não'}"
    )


# --- a Definition-of-Done do Piloto (Carta §5) --------------------------------


@dataclass(frozen=True)
class ItemCarta:
    id: str
    texto: str
    credor: str
    hipoteses: tuple[str, ...] = ()


#: A Carta §5, item a item, pela ordem da Carta. Os que nomeiam hipóteses
#: derivam do Registo; os outros declaram-se por evidência no resumo. Os três N
#: são a lista «Não conta como *done*», escrita pela positiva.
CARTA_5 = (
    ItemCarta("P1", "Fluxo A em produção com ≥ 10 PMEs activas, onboardadas por self-service automático; ≥ 80% das activações sem intervenção humana (ADR-019)", "KAM-109"),
    ItemCarta("P2", "H1: ≥ 5 PMEs convertem a pago no fim do piloto gratuito de 30 dias. H9: ≥ 70% activas ao dia 60, das PMEs activadas até à semana 4", "KAM-109", ("H1", "H9")),
    ItemCarta("P3", "H6: custo de IA por conversa ≤ 15% da mensalidade, medido em ≥ 500 conversas reais. H8: ≥ 60% de catálogos correctos em auditoria", "KAM-109", ("H6", "H8")),
    ItemCarta("F1", "Esqueleto andante provado: uma conversa real cria um pedido, o evento de pagamento é consumido pela outra vertical, sem excepções no core", "KAM-108"),
    ItemCarta("F2", "0 fugas entre tenants ou contactos, 0 pedidos duplicados e 0 números divergentes no conjunto adversarial", "KAM-073"),
    ItemCarta("F3", "H7 ≥ 85% de handoff correcto", "KAM-040", ("H7",)),
    ItemCarta("F4", "100% das confirmações de pagamento por evento autenticado (facilitador ou `ManualProvider` auditado e limitado)", "KAM-103, KAM-109"),
    ItemCarta("F5", "Gates de CI fail-closed verdes e revisão de segurança independente concluída", "KAM-074"),
    ItemCarta("C1", "Procedimento APD concluído para todos os destinos de dados pessoais em produção (D1, D9)", "KAM-105, KAM-069"),
    ItemCarta("C2", "DPA aceite em 100% dos tenants activos", "KAM-090, KAM-109"),
    ItemCarta("C3", "Parecer jurídico recebido sobre D8", "KAM-104"),
    ItemCarta("C4", "Resposta escrita da Meta (ou decisão registada de operar sem ela) sobre D2", "KAM-101"),
    ItemCarta("C5", "Tech Provider activo (D5)", "KAM-102"),
    ItemCarta("C6", "Backups com restauro testado e RTO/RPO medidos", "KAM-085"),
    ItemCarta("C7", "Runbooks e SLOs em vigor, com o relatório de SLO de 30 dias", "KAM-082, KAM-083"),
    ItemCarta("N1", "Nenhuma PME do piloto onboardada à mão pela equipa", "KAM-109"),
    ItemCarta("N2", "Nenhum pagamento confirmado por comprovativo em imagem", "KAM-109"),
    ItemCarta("N3", "Nenhum dado pessoal enviado a subprocessador fora de Angola sem registo", "KAM-069, KAM-105"),
)


@dataclass(frozen=True)
class Avaliacao:
    item: ItemCarta
    estado: str  # satisfeito | nao_satisfeito | por_verificar
    evidencia: str
    nota: str


def carta(efectivos: dict[str, Estado], resumo: Resumo, raiz: Path) -> list[Avaliacao]:
    avaliacoes = []
    for item in CARTA_5:
        if item.hipoteses:
            valores = [efectivos[h].efectivo for h in item.hipoteses]
            if "refutada" in valores:
                estado = "nao_satisfeito"
            elif all(v == "confirmada" for v in valores):
                estado = "satisfeito"
            else:
                estado = "por_verificar"
            nota = "; ".join(f"{h} {v}" for h, v in zip(item.hipoteses, valores))
            avaliacoes.append(Avaliacao(item, estado, "§1 deste pacote", nota))
            continue
        declarado = resumo.carta5.get(item.id)
        if declarado is None:
            avaliacoes.append(Avaliacao(item, "por_verificar", "", "não declarado"))
            continue
        evidencia = declarado.evidencia or ""
        if declarado.estado == "satisfeito":
            if not evidencia:
                avaliacoes.append(Avaliacao(item, "por_verificar", "", "declarado satisfeito sem evidência"))
                continue
            if not (raiz / evidencia).is_file():
                avaliacoes.append(Avaliacao(item, "por_verificar", evidencia, "a evidência não existe na árvore"))
                continue
        avaliacoes.append(Avaliacao(item, declarado.estado, evidencia, ""))
    return avaliacoes
