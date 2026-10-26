"""Camada 2 — o validador pos-geracao (`docs/tecnica/02` §9.1).

Confronta o texto final com os *facts* e devolve um `Verdict`. E rede de
seguranca: a garantia vem da camada 1 (`render.py`), e esta apanha o que passar
por prosa livre. O §8.4 diz o que o grafo faz com o veredicto — «retry ->
handoff».

Os **sete** veredictos sao os do dicionario §3.30, lista fechada. Tres deles nao
tem hoje `fact` que os possa satisfazer, e isso **nao** e um defeito deste
modulo:

| Veredicto | O `kind` que precisava | Hoje |
|---|---|---|
| `qty_unbacked` | `qty` | cai em `stock`, que existe |
| `datetime_unbacked` | `datetime` + `expiry` | cai em `datetime`, que existe |
| `discount_unbacked` | `discount` | **nao existe**: toda a percentagem recusa |

O `KINDS` do KAM-028 esta fechado nos quatro do §6.2 e o credor dos que faltam e
o KAM-031, o ticket que produz os *facts* (divida 105, emenda 1.39). A
consequencia escreve-se por inteiro: para o `discount`, o lado **positivo** do
criterio 2 — uma percentagem **com** *fact* a ser aceite — e **inverificavel**
hoje. O que se prova e que ela recusa, que e o que o ADR-007 manda.

## Tolerancia zero em dinheiro, e o que isso quer dizer aqui

O §9.1 escreve «tolerancia zero» sobre o dinheiro. Em concreto, por cada valor
monetario do texto:

1. tem de existir um *fact* `price` ou `total` com **exactamente** aquele valor,
   senao `money_unbacked`. E isto que apanha o criterio 3 — um total somado
   correctamente pelo modelo mas que nao e *fact* falha, porque os totais vem so
   do `propose_cart`;
2. se o unico *fact* que o sustenta for um `price`, o `sku` daquele preco tem de
   estar **na mesma linha**, senao `sku_price_mismatch`. E o §6.3 do
   `docs/tecnica/05` («resposta com `sku` ausente e rejeitada») e e o que fecha o
   «produto errado com preco certo» que o ADR-007 assinala;
3. uma linha cujo `sku` esteja `sob_consulta` recusa **qualquer** valor
   monetario, mesmo um que coincida com um total (criterio 4);
4. um `sku` em `a_partir_de` exige o marcador «a partir de» na linha: citado
   como preco fixo, falha.

**A limitacao que fica medida, e e do §9.2:** se o valor coincidir com um *fact*
`total`, o passo 2 nao se aplica e o vinculo nao se verifica. E a «coincidencia
de valores (preco de A igual ao stock de B)» da tabela do §9.2, e esta no
conjunto adversarial entre os casos que **documentam** o limite. A mitigacao que
o §9.2 nomeia para ela e a camada 1, nao esta.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Final

from .extraccao import A_PARTIR_DE, Linha, extrair
from .. import metricas as metricas_mod
from .normalizacao import sem_acento
from .render import (
    PRECO_A_PARTIR_DE,
    PRECO_SOB_CONSULTA,
    Oferta,
    formas_de_datahora,
    inteiro_do_fact as _inteiro,
)

#: Os sete veredictos do dicionario §3.30. Lista **fechada**: o grafo decide
#: pelo codigo, e um codigo que ele nao conheca cai no caminho de omissao.
VEREDICTOS: Final = (
    "money_unbacked",
    "sku_price_mismatch",
    "name_sku_mismatch",
    "qty_unbacked",
    "datetime_unbacked",
    "discount_unbacked",
    "number_unbacked",
)

#: Os `kind` de *fact* que sustentam um valor monetario (`MONEY_KINDS` do §9.1).
MONEY_KINDS: Final = ("price", "total")


class VeredictoDesconhecidoError(ValueError):
    """Um codigo fora dos sete. Levanta, pela razao do `CodigoDesconhecidoError`."""


@dataclass(frozen=True, slots=True)
class Erro:
    """Um veredicto, com o minimo para o diagnosticar.

    **Nao leva texto, e o `valor` so vem quando saiu de um *fact*.** O que se
    valida e a resposta gerada, que pode estar a repetir texto do cliente, e a
    primeira versao disto punha o numero **nao sustentado** no erro: um
    `number_unbacked` e, por definicao, o numero que nao veio de tool nenhuma —
    isto e, exactamente onde um telefone, um numero de porta ou um NIF repetido
    pelo modelo aterra. A revisao adversarial mediu-o: `validar("o meu numero e
    923456789 e moro na Rua X")` devolvia
    `Erro(codigo='number_unbacked', valor=923456789)`.

    A regra passa a ser: o `valor` so se preenche quando o numero **casa** um
    *fact*, que e quando ele e dado da tool e nao do contacto. O
    `money_unbacked`, o `qty_unbacked`, o `discount_unbacked` e o
    `number_unbacked` vao **sem** valor — e nao se perde diagnostico nenhum que
    importe, porque o grafo decide pelo `codigo` e o numero citado esta na
    resposta, que nao vai para registo.

    E a mesma licao que o `fact_id` do KAM-028 pagou com canarios. O teste que a
    prende percorre **todos** os campos da *dataclass* por reflexao, e nao uma
    lista escrita a mao: a primeira versao olhava para o `codigo` e o `sku` e
    saltava precisamente o campo que quebrava a propriedade.
    """

    codigo: str
    #: Centimos quando o codigo e de dinheiro, o inteiro nas outras classes.
    #: **So se preenche quando o numero saiu de um *fact*** (ver acima).
    valor: int | None = None
    sku: str | None = None

    def __post_init__(self) -> None:
        if self.codigo not in VEREDICTOS:
            raise VeredictoDesconhecidoError(
                f"{self.codigo!r} nao e um dos sete veredictos de `specs/02` §3.30: "
                f"{list(VEREDICTOS)}"
            )


@dataclass(frozen=True, slots=True)
class Policy:
    """O que o texto pode levar sem ser *fact* (§9.1, `policy.allowed_literals`).

    Nasce **vazia** de proposito. O §9.1 da exemplos («24 horas», «1 minuto») e
    nao os pre-carrega aqui: cada literal que entra e um numero que o validador
    deixa de verificar, e quem sabe quais fazem sentido na resposta e o grafo
    (KAM-031), que os declara por turno. Uma omissao permissiva seria um buraco
    que ninguem escolheu.

    **O que isto nao cobre, e o §9.1 da como exemplo:** «horarios da loja». Um
    horario e extraido como `datahora` e nao como `outro`, e o `allowed_literals`
    so e consultado no ramo `outro` — declarar `8` e `18` nao salva «das 8h as
    18h». E deliberado e nao e lacuna: um horario de loja **e** um *fact*
    `datetime`, e e por ai que se sustenta. Medido pela revisao adversarial.
    """

    allowed_literals: tuple[int, ...] = ()


@dataclass(frozen=True, slots=True)
class Verdict:
    """O retorno do §9.1: `ok` e a lista de erros."""

    ok: bool
    errors: tuple[Erro, ...] = ()

    def __post_init__(self) -> None:
        if self.ok != (not self.errors):
            raise ValueError("um `ok` com erros, ou um `nao ok` sem erros, e ilegivel")

    @property
    def codigos(self) -> tuple[str, ...]:
        return tuple(e.codigo for e in self.errors)




def _skus_do_nome(nome: str, ofertas: tuple[Oferta, ...]) -> set[str]:
    """Os `sku` a que um nome de produto pertence (§9.1, `resolve_sku`).

    **Devolve um conjunto e nao um `sku`**, porque duas variantes podem ter o
    mesmo nome — e a primeira versao devolvia a primeira oferta da lista, o que
    fazia o *renderer* falhar o seu proprio validador: com `("SKU-100", "Camisa
    Azul")` e `("SKU-101", "Camisa Azul")` no catalogo, a linha correcta
    «SKU-101 - Camisa Azul - …» dava `name_sku_mismatch`. Medido pela revisao
    adversarial. Quando o nome nao desambigua, a pergunta certa e «o `sku` da
    linha esta entre os que este nome pode ser», e nao «e aquele».
    """
    alvo = nome.strip().lower()
    return {o.sku for o in ofertas if o.nome.strip().lower() == alvo}


def _tem_a_partir_de(linha: Linha, numero) -> bool:
    """Se o «a partir de» esta **imediatamente antes** deste valor.

    A primeira versao procurava a frase em qualquer sitio da linha, e a revisao
    adversarial mediu o que isso valia: «SKU-500 - Fato Completo - 5 000 Kz,
    entregamos a partir de amanha» passava — um preco publicado como minimo
    apresentado como final, com o marcador a falar de outra coisa.
    """
    return sem_acento(linha.texto[: numero.inicio]).rstrip().endswith(A_PARTIR_DE)


def _dinheiro(
    linha: Linha,
    facts: tuple[Any, ...],
    por_sku: dict[str, Oferta],
    erros: list[Erro],
) -> None:
    sob_consulta = [
        s for s in linha.skus
        if s in por_sku and por_sku[s].preco_tipo == PRECO_SOB_CONSULTA
    ]
    # Uma linha que fala de um produto, por `sku` ou por nome.
    fala_de_produto = bool(linha.skus or linha.nomes)
    for numero in linha.dinheiro:
        valor = numero.value_minor
        # Passo 3 antes do passo 1: `sob_consulta` recusa mesmo um valor que
        # exista nos *facts* (criterio 4, «com qualquer numero falha»).
        if sob_consulta:
            erros.append(Erro("sku_price_mismatch", sku=sob_consulta[0]))
            continue
        if valor is None:
            # Moeda estrangeira: nao ha `kind` de moeda onde a sustentar.
            erros.append(Erro("money_unbacked"))
            continue
        casam = [
            f for f in facts
            if f.kind in MONEY_KINDS and _inteiro(f.value) == valor
        ]
        if not casam:
            erros.append(Erro("money_unbacked"))
            continue
        if any(f.kind == "total" for f in casam) and not fala_de_produto:
            # **Um `total` dispensa o vinculo so numa linha que nao fala de
            # produto nenhum**, e a condicao foi apertada depois de a revisao
            # adversarial medir o que a versao anterior deixava passar: com um
            # carrinho de **um** item, o `total` *e* o preco desse item, pelo que
            # «SKU-100 - Camisa Azul - 9 000 Kz» era aceite com o preco da Calca.
            # Isso nao e a «coincidencia de valores» do §9.2 — e o «produto
            # errado com preco certo» do ADR-007 — e na carga mais comum da loja
            # acontecia sempre, nao por acidente.
            continue
        ligados = [f for f in casam if f.kind == "price" and f.sku and f.sku in linha.skus]
        if not ligados:
            erros.append(
                Erro(
                    "sku_price_mismatch",
                    valor=valor,
                    sku=linha.skus[0] if linha.skus else None,
                )
            )
            continue
        for fact in ligados:
            oferta = por_sku.get(fact.sku or "")
            if (
                oferta is not None
                and oferta.preco_tipo == PRECO_A_PARTIR_DE
                and not _tem_a_partir_de(linha, numero)
            ):
                erros.append(Erro("sku_price_mismatch", valor=valor, sku=fact.sku))


def _nomes(linha: Linha, ofertas: tuple[Oferta, ...], erros: list[Erro]) -> None:
    """O vinculo nome -> `sku`, **so em linhas que citam um numero de produto**.

    O §6.3 do `docs/tecnica/05` manda rejeitar uma resposta com `sku` ausente, e
    a primeira versao aplicava isso a **qualquer** linha com um nome — o que
    recusava um bloco `text` legitimo («Temos a Camisa Azul para si»), medido
    pela revisao adversarial. O risco que este veredicto fecha e «produto errado
    com preco certo», e esse precisa de um numero ligado ao produto: sem
    dinheiro nem quantidade na linha, um nome nao pode enganar sobre preco.
    """
    if not any(n.classe in ("dinheiro", "quantidade") for n in linha.numeros):
        return
    for nome in linha.nomes:
        possiveis = _skus_do_nome(nome, ofertas)
        if not possiveis or possiveis.isdisjoint(linha.skus):
            erros.append(
                Erro("name_sku_mismatch", sku=sorted(possiveis)[0] if possiveis else None)
            )


def validar(
    texto: str,
    facts: tuple[Any, ...] = (),
    policy: Policy | None = None,
    ofertas: tuple[Oferta, ...] = (),
) -> Verdict:
    """O `validate(text, facts, policy)` do §9.1, com as ofertas ao lado.

    **O quarto parametro nao esta no §9.1, e tem de estar.** O veredicto
    `name_sku_mismatch` precisa de resolver um nome de produto a um `sku`, e o
    §9.1 escreve que isso se faz «via `facts.name`» — um `kind` que o `KINDS` do
    KAM-028 nao tem e que este ticket nao acrescenta (divida 105). O nome vive no
    `nome` do contrato de saida do `docs/tecnica/05` §6.3, isto e, no
    `ToolResult.data` e nao num `Fact`; passa-se por isso a oferta, em vez de
    inventar um `kind` ou de ler uma descricao.
    """
    policy = policy or Policy()
    por_sku = {o.sku: o for o in ofertas}
    erros: list[Erro] = []

    stocks = tuple(f for f in facts if f.kind == "stock")
    datas = tuple(f for f in facts if f.kind == "datetime")
    #: As formas de cada *fact* **em separado**. Achatar tudo num conjunto so
    #: aceitava a data de um *slot* com a hora de outro: medido pela revisao
    #: adversarial com dois *facts* `datetime`, «14/11/2026 as 16h00» passava —
    #: o cliente a receber confirmacao de um instante que nenhuma tool devolveu.
    formas_por_fact = [
        frozenset(formas_de_datahora(f.value))
        for f in datas
        if isinstance(f.value, str)
    ]

    linhas = extrair(
        texto,
        skus=tuple(por_sku),
        nomes=tuple(o.nome for o in ofertas),
    )
    for linha in linhas:
        _dinheiro(linha, facts, por_sku, erros)
        _nomes(linha, ofertas, erros)

        # As datas/horas da linha tem de caber **todas no mesmo *fact***: uma
        # marcacao e um instante, e o *renderer* escreve um por linha.
        da_linha = [n for n in linha.numeros if n.classe == "datahora"]
        if da_linha:
            alvos = {n.bruto.strip() for n in da_linha}
            if not any(alvos <= formas for formas in formas_por_fact):
                for _ in da_linha:
                    erros.append(Erro("datetime_unbacked"))

        for numero in linha.numeros:
            if numero.classe == "quantidade":
                # A quantidade vincula-se ao `sku` da linha, como o preco. O
                # §9.1 escreve so `require_fact(q, kinds={"qty","stock"})`, e um
                # teste apanhou o que isso deixava passar: «SKU-100 - Camisa
                # Azul - 7 unidades» era **aceite** porque 7 era o stock do
                # SKU-500. E o mesmo «produto errado com numero certo» que o
                # ADR-007 assinala para o preco, e a mitigacao que o §9.2 nomeia
                # para ele e a mesma — «validacao por `kind` e por vinculo».
                #
                # Um stock tem sempre `sku` (e por produto), pelo que — ao
                # contrario do dinheiro, onde um `total` nao tem — nao ha aqui
                # caso legitimo sem vinculo.
                if not any(
                    _inteiro(f.value) == numero.valor
                    and f.sku
                    and f.sku in linha.skus
                    for f in stocks
                ):
                    erros.append(Erro("qty_unbacked"))
            elif numero.classe == "percentagem":
                # Sempre: nao ha `kind` `discount` onde sustentar uma
                # percentagem (divida 105). *Fail-closed*, e o lado positivo
                # deste veredicto e inverificavel ate o `kind` existir.
                erros.append(Erro("discount_unbacked"))
            elif numero.classe == "outro":
                if numero.valor is None or numero.valor not in policy.allowed_literals:
                    erros.append(Erro("number_unbacked"))

    return Verdict(ok=not erros, errors=tuple(erros))


def medir_validacao(
    metricas: Any,
    vertical: str,
    veredicto: Verdict,
    *,
    repetiu: bool = False,
    handoff: bool = False,
    so_blocos: bool = False,
) -> None:
    """As cinco metricas do §9.2, num sitio so (`metricas.py`, KAM-032).

    **Chama-se `medir_validacao` e nao `registar`**, e nao e preferencia: o
    `log_policy` *lint* do *gate* 2 marca qualquer `.registar(...)` em
    `services/**` como `registar_directo`, porque e a porta sem tipos do
    *logger*. O `tls/auditoria.py` do KAM-028 escreveu a licao por extenso ao
    escolher `escrever` em vez de `registar` — «um nome que colide com uma regra
    de lint por acidente custa um ciclo de CI a quem vier depois». Aqui custaria
    ao KAM-031, que e quem vai chamar isto de dentro de um no.

    **Quem conta e o no e nao o `validar`**: o `validar` e uma funcao pura, e so
    o grafo sabe se uma recusa deu repeticao ou esgotou o tecto
    (`citation_retries` do §5.3) e se a resposta saiu do *renderer* ou de prosa
    livre.

    O `vertical` tem de estar em `VERTICAIS`: a etiqueta e validada pela
    biblioteca, e um `tenant_id` passado aqui por engano **levanta**.
    """
    metricas.contar(metricas_mod.METRICA_VALIDATE, vertical)
    if not veredicto.ok:
        metricas.contar(metricas_mod.METRICA_VALIDATE_FALHAS, vertical)
    if repetiu:
        metricas.contar(metricas_mod.METRICA_VALIDATE_REPETICOES, vertical)
    if handoff:
        metricas.contar(metricas_mod.METRICA_VALIDATE_HANDOFF, vertical)
    if so_blocos:
        metricas.contar(metricas_mod.METRICA_RENDER_ONLY, vertical)
