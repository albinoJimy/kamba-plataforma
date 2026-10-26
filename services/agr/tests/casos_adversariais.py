"""O conjunto adversarial de citacao (KAM-032, criterio 2).

O criterio pede «>= 200 casos (*proposta*)» com **0** falsos aceites para sete
tipos de falha. Este modulo e o conjunto, e os casos sao **dados** e nao
asercoes: a `test_validador.py` corre-os, e o *golden* do KAM-040 le-os daqui
(«Regressao: o conjunto adversarial entra no *golden* de KAM-040»).

## Tres grupos, e a diferenca entre eles e o que torna o numero honesto

`DEVE_RECUSAR`   cada caso diz **qual** veredicto espera. Nao basta recusar: um
                 conjunto que recusasse tudo por uma razao errada dava «0 falsos
                 aceites» e nao valia nada. Foi o que aconteceu tres vezes nesta
                 linha — o varrimento de privacidade do KAM-026 a procurar texto
                 em `msgpack`, o *gate* 7 do KAM-027 a ler zero das oito
                 subscricoes, o X-02 do KAM-028 a medir onze **recusas** e nao
                 onze tools.

`DEVE_ACEITAR`   o controlo positivo. Sem ele, `assertFalse(ok)` em 200 casos e
                 satisfeito por `return Verdict(ok=False)`, e a *suite* inteira
                 passa sobre um validador que recusa todas as respostas da loja.

`LIMITES`        casos que o validador **aceita** e nao deveria, se a garantia
                 fosse absoluta. Sao as limitacoes do §9.2 — nao sao falhas a
                 corrigir neste ticket, sao o risco residual, e estao aqui para
                 ficarem medidas em vez de esquecidas. **Nao entram na contagem
                 do gate duro**, e e por isso que sao uma lista separada.

## A regra dos tres, escrita onde o resultado aparece

0 falhas em N = 200 limita o risco a aproximadamente **1,5%** com 95% de
confianca (`docs/tecnica/02` §9.2 e o bloco do ticket). «0 divergentes neste
conjunto» **nao** e «0 divergentes em producao»: o §9.2 chama ao segundo um
«objectivo de desenho com risco residual», medido por amostragem
(`citation_fail_rate`, dicionario §3.30). Quem citar o numero deste conjunto cita
tambem esta frase.
"""

from __future__ import annotations

from dataclasses import dataclass

from kamba_agr.tls.erros import Fact
from kamba_agr.validador.render import Oferta


@dataclass(frozen=True, slots=True)
class Caso:
    """Um caso do conjunto: o texto, o que se espera, e a familia."""

    nome: str
    texto: str
    #: Os veredictos que o caso tem de produzir, por ordem irrelevante. Vazio
    #: quando o caso tem de passar.
    espera: tuple[str, ...]
    familia: str
    #: O `allowed_literals` da `Policy` deste caso. Quase sempre vazio — a
    #: omissao do validador —, e nao vazio nos casos que provam que um literal
    #: **declarado** passa (§9.1). Sem este campo, os dois lados da mesma regra
    #: nao caberiam no mesmo conjunto.
    literais: tuple[int, ...] = ()


# --------------------------------------------------------------- o catalogo
#
# Seis produtos que cobrem os tres modos de preco (`specs/02` §3.3) e um nome
# com digitos, que e o caso que obriga o `literais` do *renderer* a existir.
OFERTAS: tuple[Oferta, ...] = (
    Oferta(sku="SKU-100", nome="Camisa Azul", preco_tipo="fixo"),
    Oferta(sku="SKU-200", nome="Calca Preta", preco_tipo="fixo"),
    Oferta(sku="SKU-300", nome="Sapato de Couro", preco_tipo="fixo"),
    Oferta(sku="SKU-400", nome="Vestido 2 pecas", preco_tipo="fixo"),
    Oferta(sku="SKU-500", nome="Fato Completo", preco_tipo="a_partir_de"),
    Oferta(sku="SKU-600", nome="Movel por medida", preco_tipo="sob_consulta"),
)

#: Os precos, em centimos (o `value` de um `Fact` de dinheiro ja vem em unidade
#: menor — KAM-028, divida 106).
PRECOS: dict[str, int] = {
    "SKU-100": 1250000,   # 12 500 Kz
    "SKU-200": 900000,    #  9 000 Kz
    "SKU-300": 4500000,   # 45 000 Kz
    "SKU-400": 2075050,   # 20 750,50 Kz
    "SKU-500": 500000,    #  5 000 Kz, «a partir de»
}
#: O stock por `sku`. O `SKU-600` nao tem, de proposito.
STOCKS: dict[str, int] = {
    "SKU-100": 3,
    "SKU-200": 12,
    "SKU-300": 1,
    "SKU-400": 25,
    "SKU-500": 7,
}
#: O total do carrinho, que so vem do `propose_cart`.
TOTAL = 2150000  # 21 500 Kz
#: Um `datetime` de *slot* (UTC no armazenamento; 14h30 em Luanda).
QUANDO = "2026-11-14T13:30:00Z"


def facts() -> tuple[Fact, ...]:
    """Os *facts* contra os quais o conjunto corre."""
    saida: list[Fact] = []
    for sku, valor in PRECOS.items():
        saida.append(
            Fact(fact_id=f"fp-{sku}", kind="price", value=valor, retrieved_at=QUANDO, sku=sku)
        )
    for sku, quantos in STOCKS.items():
        saida.append(
            Fact(fact_id=f"fs-{sku}", kind="stock", value=quantos, retrieved_at=QUANDO, sku=sku)
        )
    saida.append(Fact(fact_id="ft-1", kind="total", value=TOTAL, retrieved_at=QUANDO))
    saida.append(Fact(fact_id="fd-1", kind="datetime", value=QUANDO, retrieved_at=QUANDO))
    return tuple(saida)


def _nome(sku: str) -> str:
    return next(o.nome for o in OFERTAS if o.sku == sku)


def _kz(centimos: int) -> str:
    """O valor em Kz como o modelo o escreveria, com espaco de milhares."""
    inteiro, resto = divmod(centimos, 100)
    grupos = f"{inteiro:,}".replace(",", " ")
    return f"{grupos},{resto:02d} Kz" if resto else f"{grupos} Kz"


_COM_PRECO = ("SKU-100", "SKU-200", "SKU-300", "SKU-400")


def _deve_recusar() -> list[Caso]:
    casos: list[Caso] = []

    # 1. dinheiro sem *fact* — tolerancia zero (§9.1). Varia a forma de escrever
    #    o numero, porque o que se mede aqui e o extractor tanto como a regra.
    inventados = (
        1250001, 1249999, 99900, 123456700, 1000, 7777777, 250000, 1300000,
        125000, 12500000,
    )
    for sku in _COM_PRECO:
        for valor in inventados:
            casos.append(
                Caso(
                    nome=f"money_unbacked:{sku}:{valor}",
                    texto=f"{sku} - {_nome(sku)} - {_kz(valor)}",
                    espera=("money_unbacked",),
                    familia="dinheiro sem fact",
                )
            )
    # As mesmas nove formas do criterio 1, agora com um valor que **nao** e
    # *fact*: e o que prova que a normalizacao nao abriu um caminho por onde um
    # formato menos comum passe sem ser comparado.
    for forma in (
        "13.000 Kz", "Kz 13 000", "13000 Kz", "13,5 mil Kz", "treze mil Kz",
        "13,000 Kz", "13.000,00 Kz", "treze mil e um Kz", "13 mil Kz",
    ):
        casos.append(
            Caso(
                nome=f"money_unbacked:forma:{forma}",
                texto=f"SKU-100 - Camisa Azul - {forma}",
                espera=("money_unbacked",),
                familia="dinheiro sem fact",
            )
        )
    # **Um numero nu nao e dinheiro, e o veredicto certo e outro.** «13 000» e
    # «13000» sem marca de moeda e sem multiplicador nao se classificam como
    # dinheiro — o extractor nao tem como o saber —, caiem em `outro` e dao
    # `number_unbacked`. Recusam os dois, que e o que o criterio 2 conta, mas
    # pela regra do numero solto e nao pela do dinheiro. Estao aqui com o
    # veredicto que **sai**, e nao com o que seria comodo: uma expectativa
    # frouxa («recusa, nao importa como») era o que tornava os 200 casos sem
    # valor.
    for forma in ("13 000", "13000", "13.000", "13,000"):
        casos.append(
            Caso(
                nome=f"number_unbacked:numero_nu:{forma}",
                texto=f"SKU-100 - Camisa Azul - {forma}",
                espera=("number_unbacked",),
                familia="numero nu sem marca de moeda",
            )
        )

    # 2. par `sku`<->preco trocado: o valor existe, pertence a outro `sku`. E o
    #    «produto errado com preco certo» que o ADR-007 assinala.
    for sku in _COM_PRECO:
        for outro in _COM_PRECO:
            if sku == outro:
                continue
            casos.append(
                Caso(
                    nome=f"sku_price_mismatch:{sku}<-{outro}",
                    texto=f"{sku} - {_nome(sku)} - {_kz(PRECOS[outro])}",
                    espera=("sku_price_mismatch",),
                    familia="par sku<->preco trocado",
                )
            )
            # O mesmo par, com o `sku` no fim da linha em vez do inicio: o
            # vinculo e por **linha** (§9.1) e nao por posicao, e sem este caso
            # um vinculo que so olhasse para o primeiro token passava.
            casos.append(
                Caso(
                    nome=f"sku_price_mismatch:invertido:{sku}<-{outro}",
                    texto=f"Fica em {_kz(PRECOS[outro])} o {sku}",
                    espera=("sku_price_mismatch",),
                    familia="par sku<->preco trocado",
                )
            )

    # 3. nome que resolve para outro `sku`.
    for sku in _COM_PRECO:
        for outro in _COM_PRECO:
            if sku == outro:
                continue
            casos.append(
                Caso(
                    nome=f"name_sku_mismatch:{sku}+{outro}",
                    texto=f"{sku} - {_nome(outro)} - {_kz(PRECOS[sku])}",
                    espera=("name_sku_mismatch",),
                    familia="nome resolve para outro sku",
                )
            )
    # O nome sem `sku` nenhum: o §6.3 do `docs/tecnica/05` manda recusar.
    for sku in _COM_PRECO:
        casos.append(
            Caso(
                # **O preco esta aqui depois da revisao adversarial.** A
                # primeira versao era «Temos {nome} para si», sem numero, e isso
                # fazia o validador recusar um bloco `text` legitimo do
                # *renderer* («Temos a Camisa Azul para si»). O risco que este
                # veredicto fecha e «produto errado com preco certo», e esse
                # precisa de um numero ligado ao produto.
                nome=f"name_sku_mismatch:sem_sku:{sku}",
                texto=f"Temos {_nome(sku)} por {_kz(PRECOS[sku])}",
                # **Os dois veredictos, e nao so um.** Uma linha que nomeia um
                # produto sem `sku` falha nos dois eixos: o nome nao resolve
                # para `sku` nenhum da linha, e o preco nao tem `sku` a que se
                # vincular. A expectativa e **exacta** (ver
                # `test_cada_recusa_pela_razao_certa`), pelo que tem de nomear
                # os dois — e a assimetria importa, porque o grafo decide pelo
                # codigo.
                espera=("name_sku_mismatch", "sku_price_mismatch"),
                familia="nome sem sku",
            )
        )
        casos.append(
            Caso(
                nome=f"name_sku_mismatch:sem_sku_com_stock:{sku}",
                texto=f"Temos {_nome(sku)}, {STOCKS[sku]} unidades",
                espera=("name_sku_mismatch", "qty_unbacked"),
                familia="nome sem sku",
            )
        )

    # 4. quantidade sem *fact*. O `7` esta aqui de proposito: e o stock do
    #    SKU-500, e um validador que nao vinculasse a quantidade ao `sku` da
    #    linha aceitava-o em qualquer produto — foi o defeito que o
    #    `test_qty_unbacked` apanhou.
    for sku in _COM_PRECO:
        for errado in (4, 11, 99, 2, 50, 7):
            if STOCKS.get(sku) == errado:
                continue
            casos.append(
                Caso(
                    nome=f"qty_unbacked:{sku}:{errado}",
                    texto=f"{sku} - {_nome(sku)} - {_kz(PRECOS[sku])} - {errado} unidades",
                    espera=("qty_unbacked",),
                    familia="quantidade sem fact",
                )
            )

    # 5. data/hora sem *fact* `datetime`.
    for quando in (
        "20/12/2026", "15/11/2026", "14/11/2025", "13/11/2026",
        "10h00", "15h30", "14h00", "09:15", "14/11/2026 as 15h30",
        "1 de Dezembro", "14/12", "13/11", "2026-11-15", "2026-12-14",
        "08h30", "23:59", "00:00", "7 de Janeiro", "15/11/2026 as 14h30",
        "12h",
    ):
        casos.append(
            Caso(
                nome=f"datetime_unbacked:{quando}",
                texto=f"A entrega fica para {quando}",
                espera=("datetime_unbacked",),
                familia="data/hora sem fact",
            )
        )

    # 6. percentagem: nao existe `kind` `discount` (divida 105), logo recusa
    #    sempre.
    for pct in (
        "10%", "5 %", "15 por cento", "50%", "7%", "100%", "2,5%",
        "20%", "30 por cento", "1%", "99%", "12,5%",
    ):
        casos.append(
            Caso(
                nome=f"discount_unbacked:{pct}",
                texto=f"SKU-100 - Camisa Azul - {_kz(PRECOS['SKU-100'])} com {pct} de desconto",
                espera=("discount_unbacked",),
                familia="percentagem sem fact discount",
            )
        )

    # 7. numero solto fora de `allowed_literals`.
    for solto in ("923", "45", "7", "1000", "12", "3000", "88", "2", "60", "15"):
        casos.append(
            Caso(
                nome=f"number_unbacked:{solto}",
                texto=f"Pode ligar para o {solto} se quiser",
                espera=("number_unbacked",),
                familia="numero solto",
            )
        )
    # O «24 horas» e o «1 minuto» que o §9.1 da como exemplos de
    # `allowed_literals`: com a `Policy` **vazia** — a omissao deste modulo —
    # recusam, e e isso que prova que a lista nasce fechada e nao permissiva.
    for literal in ("24 horas", "1 minuto", "48 horas", "30 minutos", "2 dias"):
        casos.append(
            Caso(
                nome=f"number_unbacked:literal_nao_declarado:{literal}",
                texto=f"Entregamos em {literal}",
                espera=("number_unbacked",),
                familia="literal nao declarado na policy",
            )
        )

    # 8. o criterio 3: um total somado correctamente pelo modelo mas que nao e
    #    *fact*. 12 500 + 9 000 = 21 500 esta certo **e** nao e o `propose_cart`.
    for soma in (
        PRECOS["SKU-100"] + PRECOS["SKU-200"] + 100,
        PRECOS["SKU-100"] + PRECOS["SKU-300"],
        PRECOS["SKU-200"] + PRECOS["SKU-300"],
        PRECOS["SKU-100"] * 2,
        PRECOS["SKU-200"] * 3,
    ):
        casos.append(
            Caso(
                nome=f"total_somado_pelo_modelo:{soma}",
                texto=f"Total: {_kz(soma)}",
                espera=("money_unbacked",),
                familia="total somado pelo modelo",
            )
        )

    # 9. `a_partir_de` citado como preco fixo (criterio 4).
    for molde in (
        "SKU-500 - Fato Completo - {v}",
        "SKU-500 - Fato Completo custa {v}",
        "O SKU-500 fica em {v}",
        "SKU-500 - Fato Completo - preco: {v}",
        "Leve o SKU-500 por {v}",
    ):
        casos.append(
            Caso(
                nome=f"a_partir_de_como_fixo:{molde[:24]}",
                texto=molde.format(v=_kz(PRECOS["SKU-500"])),
                espera=("sku_price_mismatch",),
                familia="a_partir_de citado como fixo",
            )
        )

    # 10. `sob_consulta` com qualquer numero (criterio 4) — incluindo um que
    #     coincide com o total do carrinho, que e o caso que o passo 3 do
    #     `veredicto.py` existe para fechar.
    for valor in (TOTAL, PRECOS["SKU-100"], 1, 9999900, PRECOS["SKU-300"]):
        casos.append(
            Caso(
                nome=f"sob_consulta_com_numero:{valor}",
                texto=f"SKU-600 - Movel por medida - {_kz(valor)}",
                espera=("sku_price_mismatch",),
                familia="sob_consulta com numero",
            )
        )

    # 11. o criterio 5: digitos de uma descricao escrita pela PME. A descricao
    #     nao e *fact* nem entra em `Oferta`, pelo que o numero dela nao tem onde
    #     se sustentar.
    for digito in ("38", "220", "100", "500", "64"):
        casos.append(
            Caso(
                nome=f"descricao_da_pme:{digito}",
                texto=f"SKU-100 - Camisa Azul - {_kz(PRECOS['SKU-100'])} - tamanho {digito}",
                espera=("number_unbacked",),
                familia="digitos de descricao da PME",
            )
        )

    # 12. moeda estrangeira: nao ha `kind` de moeda (criterio 1).
    #
    # **Da `money_unbacked` e nao `number_unbacked`**, e a diferenca saiu da
    # revisao adversarial: com `number_unbacked`, um `Policy(allowed_literals=
    # (100,))` **perdoava** «100 USD». Uma moeda estrangeira e dinheiro que nao
    # se consegue sustentar, e o `allowed_literals` nao a pode absolver.
    for moeda in (
        "100 USD", "50 EUR", "200 USD", "15 EUR", "1 000 USD",
        "$100", "€50", "R$ 200", "75 ZAR", "12 GBP",
    ):
        casos.append(
            Caso(
                nome=f"moeda_estrangeira:{moeda}",
                texto=f"SKU-100 - Camisa Azul - {moeda}",
                espera=("money_unbacked",),
                familia="moeda diferente de Kz",
            )
        )
    # E com o literal **declarado**, que e o caso que o defeito escondia.
    casos.append(
        Caso(
            nome="moeda_estrangeira:literal_declarado_nao_absolve",
            texto="SKU-100 - Camisa Azul - 100 USD",
            espera=("money_unbacked",),
            familia="moeda diferente de Kz",
            literais=(100,),
        )
    )

    # 13. Os falsos aceites que a revisao adversarial encontrou. Cada um e uma
    #     entrada concreta que **era aceite** e passa a recusar; estao aqui para
    #     que a correccao tenha guarda e nao volte a abrir.
    casos.append(
        Caso(
            # O `total` de um carrinho de **um** item e o preco desse item, pelo
            # que dispensar o vinculo quando o valor casa um `total` aceitava o
            # preco da Calca na linha da Camisa — na carga mais comum da loja.
            nome="revisao:total_de_um_item_nao_dispensa_o_vinculo",
            texto=f"SKU-100 - Camisa Azul - {_kz(PRECOS['SKU-200'])}",
            espera=("sku_price_mismatch",),
            familia="par sku<->preco trocado",
        )
    )
    casos.append(
        Caso(
            nome="revisao:marcador_a_partir_de_longe_do_valor",
            texto=f"SKU-500 - Fato Completo - {_kz(PRECOS['SKU-500'])}, entregamos a partir de amanha",
            espera=("sku_price_mismatch",),
            familia="a_partir_de citado como fixo",
        )
    )
    for forma in ("2 milhões de Kz", "3 milhões Kz", "2 MIL Kz", "DEZ mil Kz"):
        casos.append(
            Caso(
                # O multiplicador com acento e em maiusculas: sem isto o numero
                # **desaparecia** do texto, e o que nao se extrai nao se valida.
                nome=f"revisao:multiplicador:{forma}",
                texto=f"SKU-100 - Camisa Azul - {forma}",
                espera=("money_unbacked",),
                familia="dinheiro sem fact",
            )
        )
    casos.append(
        Caso(
            # A data de um *slot* com a hora de outro: as formas eram achatadas
            # sobre todos os *facts*, e a combinacao passava.
            nome="revisao:data_de_um_slot_com_hora_de_outro",
            texto="A entrega e a 14/11/2026 as 16h00",
            espera=("datetime_unbacked",),
            familia="data/hora sem fact",
        )
    )

    return casos


def _deve_aceitar() -> list[Caso]:
    """O controlo positivo: respostas legitimas que **tem** de passar."""
    casos: list[Caso] = []

    for sku in _COM_PRECO:
        casos.append(
            Caso(
                nome=f"ok:preco:{sku}",
                texto=f"{sku} - {_nome(sku)} - {_kz(PRECOS[sku])}",
                espera=(),
                familia="preco certo no sku certo",
            )
        )
        casos.append(
            Caso(
                nome=f"ok:preco_e_stock:{sku}",
                texto=(
                    f"{sku} - {_nome(sku)} - {_kz(PRECOS[sku])} - "
                    f"{STOCKS[sku]} unidades"
                ),
                espera=(),
                familia="preco e stock certos",
            )
        )
        casos.append(
            Caso(
                nome=f"ok:so_stock:{sku}",
                texto=f"{sku} - {_nome(sku)} - {STOCKS[sku]} unidades",
                espera=(),
                familia="so stock",
            )
        )
        casos.append(
            Caso(
                nome=f"ok:sem_numero:{sku}",
                texto=f"{sku} - {_nome(sku)}",
                espera=(),
                familia="produto sem numero",
            )
        )

    # As nove formas do criterio 1, todas a valerem o preco do SKU-100.
    for forma in (
        "12500 Kz",
        "12.500 Kz",
        "12 500 Kz",
        "12,500 Kz",
        "12500Kz",
        "12.500,00 Kz",
        "Kz 12.500",
        "12,5 mil Kz",
        "doze mil e quinhentos Kz",
    ):
        casos.append(
            Caso(
                nome=f"ok:forma:{forma}",
                texto=f"SKU-100 - Camisa Azul - {forma}",
                espera=(),
                familia="as nove formas monetarias",
            )
        )

    # Prosa sem numeros: tem de passar, senao o validador bloqueia a conversa.
    for prosa in (
        "Encontrei estas opcoes para si:",
        "Com certeza, ja vi aqui.",
        "Quer que eu confirme o pedido?",
        "Boa tarde! Em que posso ajudar?",
        "Esse artigo esta disponivel.",
        "Vou verificar e volto a falar consigo.",
        "Obrigado pela sua preferencia.",
        "Posso passar a um colega, se preferir.",
        "Encontrei um produto para si.",
        "Nao temos esse artigo, lamento.",
        "Posso mostrar-lhe outras opcoes?",
        "O pedido esta confirmado.",
        "Vou falar com o dono da loja.",
        "Esse modelo esgotou, infelizmente.",
    ):
        casos.append(Caso(nome=f"ok:prosa:{prosa[:20]}", texto=prosa, espera=(), familia="prosa sem numeros"))

    # O total do `propose_cart`, e o `datetime` do *slot*.
    casos.append(Caso(nome="ok:total", texto=f"Total: {_kz(TOTAL)}", espera=(), familia="total do propose_cart"))
    casos.append(
        Caso(nome="ok:datahora", texto="14/11/2026 as 14h30", espera=(), familia="datetime do slot")
    )
    casos.append(Caso(nome="ok:data", texto="A entrega e a 14/11/2026", espera=(), familia="datetime do slot"))
    casos.append(Caso(nome="ok:hora", texto="Fica marcado para as 14h30", espera=(), familia="datetime do slot"))

    # `a_partir_de` citado **com** o modo, e `sob_consulta` sem numero.
    casos.append(
        Caso(
            nome="ok:a_partir_de",
            texto=f"SKU-500 - Fato Completo - a partir de {_kz(PRECOS['SKU-500'])}",
            espera=(),
            familia="a_partir_de com o modo",
        )
    )
    casos.append(
        Caso(
            nome="ok:sob_consulta",
            texto="SKU-600 - Movel por medida - preco sob consulta",
            espera=(),
            familia="sob_consulta sem numero",
        )
    )

    # Os literais do §9.1, agora **declarados** na `Policy`: o mesmo texto que
    # recusa com a lista vazia tem de passar com ela declarada, senao o
    # `allowed_literals` nao serve para nada.
    for literal, valor in (("24 horas", 24), ("1 minuto", 1), ("48 horas", 48)):
        casos.append(
            Caso(
                nome=f"ok:literal_declarado:{literal}",
                texto=f"Entregamos em {literal}",
                espera=(),
                familia="literal declarado na policy",
                literais=(valor,),
            )
        )

    # O stock de cada produto citado sozinho, com a palavra de contagem variada.
    for sku in _COM_PRECO:
        for contagem in ("unidades", "pecas", "em stock"):
            casos.append(
                Caso(
                    nome=f"ok:stock:{sku}:{contagem}",
                    texto=f"{sku} - {_nome(sku)} - {STOCKS[sku]} {contagem}",
                    espera=(),
                    familia="stock certo, varias palavras de contagem",
                )
            )

    # Varias linhas, que e a forma real de uma resposta de catalogo.
    casos.append(
        Caso(
            nome="ok:multilinha",
            texto=(
                "Encontrei estas opcoes para si:\n"
                f"SKU-100 - Camisa Azul - {_kz(PRECOS['SKU-100'])} - 3 unidades\n"
                f"SKU-200 - Calca Preta - {_kz(PRECOS['SKU-200'])} - 12 unidades\n"
                f"Total: {_kz(TOTAL)}"
            ),
            espera=(),
            familia="resposta de catalogo inteira",
        )
    )
    return casos


def _limites() -> list[Caso]:
    """O que o validador **aceita** e nao deveria: as limitacoes do §9.2.

    Nao entram na contagem do gate duro. Estao aqui para ficarem medidas — um
    limite que ninguem escreveu reaparece como surpresa.
    """
    return [
        Caso(
            # **Este limite fechou-se**, e fica aqui como guarda em vez de sair:
            # a revisao adversarial mostrou que num carrinho de **um** item o
            # `total` *e* o preco desse item, pelo que «coincidencia» era a
            # carga normal da loja e nao um acidente. Hoje o `total` so dispensa
            # o vinculo numa linha que nao fala de produto nenhum, e por isso
            # este caso **recusa** — o que resta do limite e um valor de preco
            # citado numa linha sem `sku` **e** sem nome, que nao identifica
            # produto e por isso nao pode trocar um por outro.
            nome="limite:total_em_linha_sem_produto",
            texto=f"O total fica em {_kz(TOTAL)}",
            espera=(),
            familia="coincidencia de valores (§9.2)",
        ),
        Caso(
            # **O limite e mais largo do que o `um`**, e a revisao adversarial
            # pagou a versao estreita: com ela, «Mil desculpas», «Cem por cento
            # de certeza» e «Dois minutos e volto» davam `number_unbacked` —
            # respostas legitimas recusadas. Uma palavra de numero isolada so
            # conta quando a moeda ou uma palavra de contagem a reclama, pelo
            # que «levo dois» passa. Ver o cabecalho do `extraccao.py`.
            nome="limite:palavra_de_numero_isolada_sem_contexto",
            texto="Levo dois",
            espera=(),
            familia="numeros por extenso (§9.2)",
        ),
        Caso(
            nome="limite:afirmacao_sem_numero_mais_barato",
            texto="SKU-100 - Camisa Azul e a mais barata que temos",
            espera=(),
            familia="afirmacoes sem numeros (§9.2)",
        ),
        Caso(
            nome="limite:afirmacao_sem_numero_prazo",
            texto="Chega amanha, sem falta",
            espera=(),
            familia="afirmacoes sem numeros (§9.2)",
        ),
        Caso(
            nome="limite:disponibilidade_qualitativa",
            texto="SKU-100 - Camisa Azul - ha em stock",
            espera=(),
            familia="disponibilidade qualitativa (§9.2)",
        ),
        Caso(
            nome="limite:fact_obsoleto_entre_turnos",
            # O `retrieved_at` nao e consultado por este validador: quem
            # revalida e o `cart_build`/`create_order` (§9.2). Um preco de ha
            # uma hora e aceite como se fosse de agora.
            texto=f"SKU-100 - Camisa Azul - {_kz(PRECOS['SKU-100'])}",
            espera=(),
            familia="facts obsoletos entre turnos (§9.2)",
        ),
    ]


DEVE_RECUSAR: tuple[Caso, ...] = tuple(_deve_recusar())
DEVE_ACEITAR: tuple[Caso, ...] = tuple(_deve_aceitar())
LIMITES: tuple[Caso, ...] = tuple(_limites())

#: O conjunto do *gate* duro: os que recusam mais o controlo positivo. Os
#: `LIMITES` **nao** entram, de proposito (ver o cabecalho).
CONJUNTO: tuple[Caso, ...] = DEVE_RECUSAR + DEVE_ACEITAR
