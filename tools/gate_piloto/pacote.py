"""O `Gate_Piloto.md`, escrito a partir do Registo, do resumo e das regras.

O pacote é **determinista**: a mesma entrada dá o mesmo texto, byte a byte, e é
isso que deixa o `--check` do `cli.py` dizer se o ficheiro versionado ainda é o
que o gerador escreve. Não há data do relógio no texto; a data é um argumento.
"""

from __future__ import annotations

from .entradas import Resumo
from .registo import HIPOTESES, Linha
from .regras import (
    PARAGEM,
    Avaliacao,
    Accionada,
    Estado,
)

#: As estimativas que o critério D manda comparar, transcritas com a fonte. Não
#: são números do executor: são do `09` §14.4 e §14.5, com o estado que lá têm.
ESTIMATIVA_POR_PME = "49 – 80 USD por PME e por mês, no Piloto (≈ 10 PMEs)"
ESTIMATIVA_EQUILIBRIO = "≈ 8 a 28 PMEs"

_ROTULO = {
    "satisfeito": "satisfeito",
    "nao_satisfeito": "**não satisfeito**",
    "por_verificar": "por verificar",
}


def _celula(texto: str) -> str:
    return texto.replace("|", "\\|").replace("\n", " ") or "—"


def _ligacao(evidencia: str) -> str:
    """Um caminho relativo à raiz, ligado a partir de `docs/tecnica/evidencia/validacao/`."""
    if not evidencia or evidencia.startswith("§"):
        return _celula(evidencia)
    return f"[`{evidencia}`](../../../../{evidencia})"


def _dinheiro(minor: int, moeda: str) -> str:
    """Unidade menor inteira para apresentação. Assume dois decimais (USD, AOA)."""
    return f"{minor // 100},{minor % 100:02d} {moeda}"


def escrever(
    linhas: dict[str, Linha],
    efectivos: dict[str, Estado],
    avaliacoes: list[Avaliacao],
    accionadas: list[Accionada],
    paragem: tuple[str, str],
    resumo: Resumo | None,
    origem_registo: str,
    origem_resumo: str | None,
    data: str,
    hash_conferido: bool = False,
) -> str:
    r = resumo
    saida: list[str] = []
    add = saida.append

    add("# Gate do Piloto — pacote de evidência")
    add("")
    add("| Campo | Valor |")
    add("|---|---|")
    add("| Produto | KAMBÁ (nome de trabalho) — plataforma WhatsApp-native de comércio conversacional para Angola |")
    add("| Documento | Validação — pacote de evidência do gate do Piloto (checklist) |")
    add("| Versão | 1.1 |")
    add(f"| Data | {data} |")
    add("| Estado | NÃO VERIFICADO — pacote gerado; a verificação cruzada e a decisão são humanas |")
    add("| Fonte | `../../../exploracao/14-tese-minima-e-plano-de-validacao.md` §2 e §6; `../../../../specs/00_KAMBA_Carta.md` §5; `../../../../specs/EPIC-10_Spikes_Validacao_Gates.md` (bloco KAM-110) |")
    add("| Dono | Fundador, com o Arquitecto de Plataforma, o Responsável de Segurança e o de Produto |")
    add("| Ticket | KAM-110 (EPIC-10) |")
    add("| Gerado por | `tools/gate_piloto` — não se edita à mão; regenera-se |")
    add("| Relacionados | [`Gate_Piloto_Decisao.md`](Gate_Piloto_Decisao.md), [`Registo_Hipoteses.md`](Registo_Hipoteses.md) |")
    add("")
    if r is None:
        add("> **Pré-visualização sem resumo do piloto.** Gerado só sobre o Registo de")
        add("> Hipóteses; os itens da Carta §5 que se declaram por evidência ficam todos")
        add("> `por verificar`, e a paragem total não é avaliável. O pacote do gate")
        add("> gera-se no dia do gate, sobre o manifesto congelado do KAM-109.")
        add("")
    elif r.sintetico:
        add("> **SINTÉTICO — não é evidência.** O resumo que alimentou este pacote está")
        add("> marcado `sintetico: true`. Nenhuma linha deste ficheiro sustenta uma decisão.")
        add("")
    add("> **Este pacote não decide.** Aplica as regras do bloco KAM-110 e mostra o")
    add("> que elas dão; a decisão — `CONTINUAR`, `PIVÔ` ou `PARAR` — escreve-se no")
    add("> [`Gate_Piloto_Decisao.md`](Gate_Piloto_Decisao.md), pelo fundador e pelos")
    add("> três papéis.")
    add("")
    add("---")
    add("")

    # §1 — hipóteses
    add("## 1. Hipóteses H1–H9 (critério A)")
    add("")
    add("O **estado efectivo** é o declarado no Registo **só** se a linha tiver dados:")
    add("amostra n positiva, um resultado com número, uma coluna fonte que nomeie um")
    add("ficheiro que exista na árvore — ou, em H1, H6, H8 e H9, o SHA-256 do manifesto")
    add("congelado do KAM-109 —, a amostra mínima que um critério escreve (H6 e H9) e,")
    add("nessas quatro, o manifesto nomeado no resumo e conferido na árvore. Sem isso é")
    add("`inconclusiva` — também quando o declarado é `refutada`, porque uma refutação")
    add("sem dados accionava um pivô por nada.")
    add("")
    add("**O gerador não confronta o resultado com o limiar.** O resultado é texto no")
    add("Registo, com unidades que variam por hipótese; que cada `confirmada` cumpre o")
    add("seu limiar confere-o a verificação cruzada do memorando (§9).")
    add("")
    add("| H | limiar | amostra n | resultado | declarado | **efectivo** | evidência | porque difere |")
    add("|---|---|---|---|---|---|---|---|")
    for h in HIPOTESES:
        l, e = linhas[h], efectivos[h]
        porque = "; ".join(e.razoes) if e.efectivo != e.declarado else ""
        add(
            f"| {h} | {_celula(l.limiar)} | {_celula(l.amostra)} | {_celula(l.resultado)} "
            f"| {_celula(e.declarado)} | **{e.efectivo}** | {_celula(l.fonte)} | {_celula(porque)} |"
        )
    add("")
    contagem = {k: sum(1 for e in efectivos.values() if e.efectivo == k) for k in ("confirmada", "refutada", "inconclusiva")}
    rebaixadas = sum(1 for e in efectivos.values() if e.declarado and e.declarado != e.efectivo)
    add("| Contagem | |")
    add("|---|---|")
    add(f"| `confirmada` | {contagem['confirmada']} |")
    add(f"| `refutada` | {contagem['refutada']} |")
    add(f"| `inconclusiva` | {contagem['inconclusiva']} |")
    add(f"| Declaradas no Registo e rebaixadas aqui | {rebaixadas} |")
    add("")
    add("### 1.1 Inconclusivas, e o plano datado que cada uma exige")
    add("")
    add("«Uma hipótese inconclusiva não permite `CONTINUAR` sem um plano datado para a")
    add("fechar» (bloco KAM-110, «Detalhes Técnicos»). O plano e a data preenchem-se no")
    add("memorando, à mão.")
    add("")
    inconclusivas = [h for h in HIPOTESES if efectivos[h].efectivo == "inconclusiva"]
    if inconclusivas:
        add(f"Inconclusivas: {', '.join(inconclusivas)}.")
    else:
        add("Nenhuma.")
    add("")

    # §2 — Carta §5
    add("## 2. Definition-of-Done do Piloto, item a item (critério B)")
    add("")
    add("P2, P3 e F3 **derivam do §1** e não se declaram: só ficam `satisfeito` com")
    add("todas as hipóteses deles `confirmada`. Os outros declaram-se no resumo, e")
    add("`satisfeito` exige um ficheiro de evidência que exista na árvore.")
    add("")
    add("| # | Item (Carta §5) | Credor | Estado | Evidência | Nota |")
    add("|---|---|---|---|---|---|")
    for a in avaliacoes:
        add(
            f"| {a.item.id} | {_celula(a.item.texto)} | {a.item.credor} | {_ROTULO[a.estado]} "
            f"| {_ligacao(a.evidencia)} | {_celula(a.nota)} |"
        )
    add("")
    satisfeitos = sum(1 for a in avaliacoes if a.estado == "satisfeito")
    add(f"**{satisfeitos} de {len(avaliacoes)} satisfeitos.** O Piloto está *feito* só com")
    add("todos (Carta §5: «Nenhum item é substituível por documentação»). H10–H12, dos")
    add("módulos de entrada, **não bloqueiam** o gate (Carta §5; ADR-020) e ficam fora")
    add("desta tabela.")
    add("")

    # §3 — matriz e paragem
    add("## 3. Matriz de `14` §6 (critério C)")
    add("")
    if accionadas:
        add("| Gatilho | Linha de `14` §6 que acciona |")
        add("|---|---|")
        for a in accionadas:
            add(f"| {a.gatilho} | {_celula(a.linha)} |")
    else:
        add("Nenhuma hipótese está `refutada` no estado efectivo, e nenhum canal está")
        add("medido como não repetível: a matriz **não acciona** linha nenhuma. Isto")
        add("**não é** um verde — as inconclusivas do §1.1 continuam por fechar.")
    add("")
    canal = "por medir" if r is None or r.canal_comercial_repetivel is None else ("sim" if r.canal_comercial_repetivel else "não")
    add(f"Há canal repetível (KAM-106, «≥ 6 PMEs-alvo em ≥ 2 rondas»): {canal}.")
    add("")
    estado_paragem, porque_paragem = paragem
    rotulo_paragem = {
        "verificada": "**VERIFICADA**",
        "nao_verificada": "não verificada",
        "nao_avaliavel": "não avaliável",
    }[estado_paragem]
    add(f"**Paragem total** — «se {PARAGEM}» (`14` §6): {rotulo_paragem} ({porque_paragem}).")
    add("")

    # §4 — economia
    add("## 4. Economia real (critério D)")
    add("")
    custo = "por medir (KAM-081)"
    if r is not None and r.custo_por_pme_minor is not None:
        custo = _dinheiro(r.custo_por_pme_minor, r.moeda or "")
    add("| Campo | Valor | Fonte |")
    add("|---|---|---|")
    add(f"| Custo por PME, medido | {custo} | KAM-081 (`h6-export`) |")
    add(f"| Custo por PME, estimado | {ESTIMATIVA_POR_PME} — ESTIMATIVA | `../../09_Topologia_Operacao_Escala.md` §14.4 |")
    add(f"| Ponto de equilíbrio, hipótese | {ESTIMATIVA_EQUILIBRIO} | `../../09_Topologia_Operacao_Escala.md` §14.5 |")
    add("| Ponto de equilíbrio, actualizado | *por preencher no memorando* | |")
    add("| Meses de pista restantes | *por preencher pelo fundador* | `14` §5 |")
    add("| Ponto em que se pára ou se muda | *por preencher pelo fundador* | `14` §5 |")
    add("")
    add("**Os números de pista não passam por este gerador.** O resumo tem esquema")
    add("fechado e recusa qualquer chave que não conheça; a pista escreve-se no")
    add("memorando, pelo fundador, e nunca é estimada pelo executor (critério D).")
    add("")

    # §5 — origem
    add("## 5. Origem")
    add("")
    add("| Campo | Valor |")
    add("|---|---|")
    add(f"| Registo de Hipóteses | `{origem_registo}` |")
    add(f"| Resumo do piloto | {'`' + origem_resumo + '`' if origem_resumo else 'nenhum'} |")
    if r is not None and r.manifesto:
        add(f"| Manifesto congelado do KAM-109 | `{r.manifesto}` |")
        add(f"| SHA-256 do manifesto | `{r.manifesto_sha256}` |")
        add(f"| SHA-256 conferido contra o ficheiro | {'sim' if hash_conferido else '**não** — o manifesto não está na árvore, e H1, H6, H8 e H9 ficam `inconclusiva`'} |")
    else:
        add("| Manifesto congelado do KAM-109 | nenhum — sem ele nenhuma hipótese do KAM-109 se dá por medida |")
    add(f"| Resumo sintético | {'sim' if r is not None and r.sintetico else 'não'} |")
    add("")
    add("---")
    add("")
    add("## Controlo de versões")
    add("")
    add("| Versão | Data | Descrição | Autor |")
    add("|---|---|---|---|")
    add("| 1.0 | Novembro de 2026 | Forma do pacote, KAM-110 (preparação): hipóteses com estado efectivo, Carta §5 item a item, matriz de `14` §6, paragem total, economia sem números de pista, e origem. O texto é do gerador `tools/gate_piloto`; uma alteração de forma é uma alteração do gerador e acrescenta linha aqui. | Equipa KAMBÁ |")
    add("| 1.1 | Novembro de 2026 | KAM-110, interface com o KAM-109 fundido: o resumo nomeia o manifesto `piloto_congelado.json` em vez da exportação, e a coluna fonte de H1, H6, H8 e H9 aceita o SHA-256 dele, como manda o protocolo do Piloto (§10), só com o manifesto conferido na árvore; fora dela, essas quatro ficam `inconclusiva`. | Equipa KAMBÁ |")
    add("")
    return "\n".join(saida)
