"""As regras puras do Orcamento expresso (KAM-123): sem base, sem relogio proprio.

| Regra | O que decide |
|---|---|
| `ESTADOS` e `TRANSICOES` | os seis estados de `quote_requests.estado` e por onde se anda |
| `ler_valor_do_dono` | o valor **digitado pelo dono** -> centimos, ou recusa por ambiguidade |
| `validade_por_omissao` | a data de validade quando o dono nao a da (sete dias, *proposta*) |
| `conferir_condicoes` | o texto livre do dono: tamanho, guarda de entrada e **sem numeros** |
| `referencia_interna` | a referencia `ORC-…`, derivada do `quote_id` e sem numeracao fiscal |
| `modelo_da_proposta`, `preencher` | o texto que vai ao cliente, com os numeros por referencia e preenchidos **so** pelos *facts* |

## O bot nunca calcula, e e por construcao

Nenhuma funcao deste modulo multiplica, soma ou aplica uma percentagem. O valor
de uma proposta e **o** valor que o `ler_valor_do_dono` leu do texto do dono, e
a `quantidade` do pedido e informacao para o dono, que nunca entra numa conta:
nao ha `valor_minor * quantidade` em lado nenhum. O ensaio dos cem pedidos com
quantidades diferentes mede-o a partir da saida, e nao a partir desta nota.

## O valor do dono: um so numero, e sem adivinhar

O parser e o `para_centimos` do validador (os nove formatos PT-AO do KAM-032),
com tres recusas a mais, porque aqui quem escreve e o dono a fixar um preco e
nao o modelo a citar um:

* **mais de um numero** («120 a 150 mil», «120 mil cada, 3 unidades») recusa: o
  sistema nao escolhe entre dois valores, nem os combina;
* **a virgula com tres digitos e sem multiplicador** («1,500») recusa: o
  `para_centimos` le-a como milhares por escolha do KAM-032, e num preco essa
  escolha e o factor de mil entre 1500 Kz e 1,5 Kz. O dono reescreve;
* **centimos diferentes de zero** recusam: nao ha moeda em Angola com centimos a
  circular, e um «12.500,50» e mais provavelmente um engano do que um preco.

Um valor lido volta ao dono **em eco** (`kz_display`) com o botao de envio: e o
eco que apanha o «12.000» que devia ser «120.000», e nao o parser.
"""

from __future__ import annotations

import datetime
import re
import uuid
from typing import Any, Final

from ..guardas.regras import veredicto_por_regras
from ..validador.normalizacao import (
    CENTIMOS_POR_KZ,
    MoedaEstrangeiraError,
    NaoEDinheiroError,
    kz_display,
    para_centimos,
)
from ..validador.render import LUANDA, em_luanda

# ------------------------------------------------------------------ estados

PEDIDO: Final = "pedido"
RESPONDIDO: Final = "respondido"
ENVIADO: Final = "enviado"
AGUARDA_JANELA: Final = "aguarda_janela"
EXPIRADO: Final = "expirado"
CANCELADO: Final = "cancelado"

#: Os seis estados do criterio 2, iguais ao `CHECK` `quote_requests_estado_ck`.
ESTADOS: Final = (PEDIDO, RESPONDIDO, ENVIADO, AGUARDA_JANELA, EXPIRADO, CANCELADO)

#: Os estados em que o pedido ainda espera alguem: o dono (`pedido`), o botao do
#: dono (`respondido`) ou a janela do cliente (`aguarda_janela`). Sao os que o
#: painel e a primeira mensagem do dono mostram, e os unicos que expiram.
ABERTOS: Final = (PEDIDO, RESPONDIDO, AGUARDA_JANELA)

#: Os estados finais: nenhum sai deles, e nenhum se aceita (criterio 9).
FINAIS: Final = (ENVIADO, EXPIRADO, CANCELADO)

#: As transicoes. **Igual ao gatilho `quote_requests_transicao` da revisao**, e
#: ha ensaio que confronta as duas: a base e quem impoe, isto e o que o codigo
#: pergunta antes de lhe bater.
TRANSICOES: Final = frozenset(
    {
        (PEDIDO, RESPONDIDO),
        # O dono corrige o valor antes de carregar no botao: um `submit_quote`
        # novo sobre um `respondido` substitui o valor e pede botao novo.
        (RESPONDIDO, RESPONDIDO),
        (RESPONDIDO, ENVIADO),
        (RESPONDIDO, AGUARDA_JANELA),
        (AGUARDA_JANELA, ENVIADO),
        (PEDIDO, EXPIRADO),
        (RESPONDIDO, EXPIRADO),
        (AGUARDA_JANELA, EXPIRADO),
        (PEDIDO, CANCELADO),
        (RESPONDIDO, CANCELADO),
        (AGUARDA_JANELA, CANCELADO),
    }
)


def pode_passar(de: str, para: str) -> bool:
    """Se a transicao existe. Um estado fora dos seis nunca passa."""
    return (de, para) in TRANSICOES


# ------------------------------------------------------------------ tempos

#: A janela em que o mesmo cliente a pedir o mesmo `sku` recebe o **mesmo**
#: `quote_id` (criterio 1, *proposta*).
JANELA_DE_REPETICAO: Final = datetime.timedelta(minutes=10)

#: A validade de uma proposta quando o dono nao a da (criterio 4, *proposta*).
VALIDADE_POR_OMISSAO: Final = datetime.timedelta(days=7)

#: Quanto tempo um pedido espera o dono antes da mensagem neutra ao cliente e
#: da oferta de humano (criterio 9, *proposta*).
ESPERA_DO_DONO: Final = datetime.timedelta(hours=24)


def hoje_em_luanda(agora: datetime.datetime) -> datetime.date:
    """O dia civil de `Africa/Luanda` de um instante UTC (convencao do conjunto)."""
    if agora.tzinfo is None:
        raise ValueError("um instante sem fuso nao diz que dia e em Luanda")
    return agora.astimezone(LUANDA).date()


def validade_por_omissao(agora: datetime.datetime) -> datetime.date:
    """Hoje em Luanda mais sete dias. **Calculada por codigo**, e mostrada como data."""
    return hoje_em_luanda(agora) + VALIDADE_POR_OMISSAO


def data_display(dia: datetime.date) -> str:
    """«30/11/2026» — a forma em que a validade aparece ao dono e ao cliente."""
    return f"{dia:%d/%m/%Y}"


# ------------------------------------------------------------------ o valor

#: O maior valor que um orcamento leva: mil milhoes de Kz (*proposta*). Nao e
#: limite de negocio, e guarda contra um zero a mais que o eco nao apanhe.
VALOR_MAXIMO_MINOR: Final = 1_000_000_000 * CENTIMOS_POR_KZ

#: Os codigos de recusa do `ler_valor_do_dono`. Lista **fechada**: o grafo do
#: dono escolhe a frase pelo codigo, e nenhum leva o texto do dono.
VALOR_VAZIO: Final = "valor_vazio"
VALOR_AMBIGUO: Final = "valor_ambiguo"
VALOR_COM_VARIOS_NUMEROS: Final = "valor_com_varios_numeros"
VALOR_EM_MOEDA_ESTRANGEIRA: Final = "valor_em_moeda_estrangeira"
VALOR_FORA_DO_INTERVALO: Final = "valor_fora_do_intervalo"
RECUSAS_DO_VALOR: Final = (
    VALOR_VAZIO,
    VALOR_AMBIGUO,
    VALOR_COM_VARIOS_NUMEROS,
    VALOR_EM_MOEDA_ESTRANGEIRA,
    VALOR_FORA_DO_INTERVALO,
)

#: Um grupo de digitos com os separadores de milhares e decimais do PT-AO.
_GRUPO_NUMERICO: Final = re.compile(r"\d+(?:[ ., ]\d+)*")

#: A virgula com exactamente tres digitos atras, no fim do numero: «1,500».
_VIRGULA_DE_MILHARES: Final = re.compile(r"^\d{1,3},\d{3}$")

#: O que nunca aparece num preco unico: uma conta, uma percentagem, um
#: intervalo.
_SINAIS_DE_CONTA: Final = re.compile(r"[%+*/=x×]|\ba\b|\bcada\b|\bpor\b", re.IGNORECASE)


class ValorRecusadoError(ValueError):
    """O texto do dono nao da um valor. O `codigo` e um dos `RECUSAS_DO_VALOR`.

    **Nao leva o texto**: o que o dono escreveu pode ser qualquer coisa, e a
    mensagem de uma excepcao acaba num *traceback*.
    """

    def __init__(self, codigo: str) -> None:
        super().__init__(codigo)
        self.codigo = codigo


def ler_valor_do_dono(texto: object) -> int:
    """O valor final digitado pelo dono, em centimos de AOA. Levanta se nao for um.

    «120 mil», «120.000», «120 000 Kz», «Kz 120.000», «cento e vinte mil» dao
    todos 12_000_000. Ver o cabecalho para as recusas.
    """
    if not isinstance(texto, str) or not texto.strip():
        raise ValorRecusadoError(VALOR_VAZIO)
    limpo = " ".join(texto.replace(" ", " ").split())
    if _SINAIS_DE_CONTA.search(limpo):
        raise ValorRecusadoError(VALOR_COM_VARIOS_NUMEROS)
    grupos = _GRUPO_NUMERICO.findall(limpo)
    if len(grupos) > 1:
        raise ValorRecusadoError(VALOR_COM_VARIOS_NUMEROS)
    tem_multiplicador = bool(re.search(r"\b(mil|milh[oõ]es|milh[aã]o)\b", limpo, re.IGNORECASE))
    if grupos and not tem_multiplicador and _VIRGULA_DE_MILHARES.match(grupos[0]):
        raise ValorRecusadoError(VALOR_AMBIGUO)
    if grupos and not tem_multiplicador and re.fullmatch(r"\d+\.\d{1,2}", grupos[0]):
        # «12.5» sem multiplicador: o ponto so separa milhares em PT-AO, e com
        # um ou dois digitos atras nao e milhar nenhum.
        raise ValorRecusadoError(VALOR_AMBIGUO)
    try:
        centimos = para_centimos(limpo)
    except MoedaEstrangeiraError:
        raise ValorRecusadoError(VALOR_EM_MOEDA_ESTRANGEIRA) from None
    except (NaoEDinheiroError, ValueError):
        raise ValorRecusadoError(VALOR_AMBIGUO) from None
    if centimos % CENTIMOS_POR_KZ:
        raise ValorRecusadoError(VALOR_AMBIGUO)
    if centimos <= 0 or centimos > VALOR_MAXIMO_MINOR:
        raise ValorRecusadoError(VALOR_FORA_DO_INTERVALO)
    return centimos


def eco_do_valor(centimos: int) -> str:
    """O valor como o dono o vai ver no eco e o cliente na proposta."""
    return kz_display(centimos)


# ------------------------------------------------------------- as condicoes

#: O tamanho maximo das condicoes (criterio 4).
CONDICOES_MAX: Final = 200

CONDICOES_LONGAS: Final = "condicoes_longas"
CONDICOES_COM_NUMEROS: Final = "condicoes_com_numeros"
CONDICOES_RECUSADAS: Final = "condicoes_recusadas"
RECUSAS_DAS_CONDICOES: Final = (CONDICOES_LONGAS, CONDICOES_COM_NUMEROS, CONDICOES_RECUSADAS)

#: Os veredictos da guarda de entrada que as condicoes nao podem ter. O `ok`, o
#: `out_of_domain` e o `None` passam: «entrega ao domicilio» nao e assunto da
#: loja para as regras do cliente, e nao precisa de ser.
_VEREDICTOS_QUE_RECUSAM: Final = ("injection", "abuse", "card_data", "sensitive")


def conferir_condicoes(texto: object) -> str | None:
    """As condicoes limpas, `None` se nao houver, ou levanta `ValueError(codigo)`.

    **Sem numeros, nem por extenso**, e a razao e a do *renderer*: as condicoes
    vao ao cliente dentro da proposta, e um numero escrito pelo dono ali era um
    numero que nenhum *fact* sustenta — o validador recusava a proposta inteira.
    Recusa-se aqui, onde o dono ainda pode reescrever («entrega em tres dias»
    passa a «entrega combinada consigo»).

    A guarda e a de entrada do KAM-033 (`veredicto_por_regras`), as mesmas
    regras de injeccao que um cliente encontra: um texto do dono e dado nao
    fiavel quando chega a outra pessoa.
    """
    if texto is None:
        return None
    if not isinstance(texto, str):
        raise ValueError(CONDICOES_RECUSADAS)
    limpo = " ".join(texto.split())
    if not limpo:
        return None
    if len(limpo) > CONDICOES_MAX:
        raise ValueError(CONDICOES_LONGAS)
    from ..validador.extraccao import extrair

    if re.search(r"\d", limpo) or any(linha.numeros for linha in extrair(limpo)):
        raise ValueError(CONDICOES_COM_NUMEROS)
    if veredicto_por_regras(limpo) in _VEREDICTOS_QUE_RECUSAM:
        raise ValueError(CONDICOES_RECUSADAS)
    return limpo


# ------------------------------------------------------------ a referencia


#: Dezasseis letras para os dezasseis valores de um hexadecimal, sem `I` nem
#: `O` (que se leem `1` e `0`).
_LETRAS_DA_REFERENCIA: Final = "ABCDEFGHJKLMNPQR"


def referencia_interna(quote_id: object) -> str:
    """`ORC-` e oito letras derivadas do `quote_id`.

    **Nao e numeracao fiscal**, e e por isso que deriva do identificador e nao
    de uma sequencia: uma serie continua por tenant era a forma de uma factura,
    e a plataforma nao e software validado pela AGT (E5 B10).

    **So letras, e nao hexadecimal**, por duas razoes medidas nesta casa: um
    digito na proposta e um numero que o validador quer ver sustentado por um
    *fact* (`number_unbacked`), e um hexadecimal longo casa de vez em quando a
    guarda de telefone. Oito letras de dezasseis sao os mesmos trinta e dois
    bits dos oito primeiros hexadecimais.
    """
    return "ORC-" + "".join(
        _LETRAS_DA_REFERENCIA[int(c, 16)] for c in uuid.UUID(str(quote_id)).hex[:8]
    )


# ------------------------------------------------------------- a proposta

#: O rotulo fixo do criterio 7 (*a confirmar por parecer*, E5 Q8).
ROTULO: Final = "Orçamento — não é factura"

#: As duas referencias do modelo, `{{quote_price:<quote_id>}}` e
#: `{{validade:<quote_id>}}`. O `quote_id` e o `fact_id` do *fact*: um UUID da
#: base, e nunca texto de quem conversa.
_REFERENCIA: Final = re.compile(
    r"\{\{(quote_price|validade):([0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12})\}\}"
)


class ModeloInvalidoError(ValueError):
    """Uma referencia do modelo sem o *fact* que a preenche. Levanta, nao degrada."""


#: O nome da oferta com que a proposta passa no validador. **Nao aparece no
#: texto**: a linha do valor cita o produto pelo `sku`, que e o que prende o
#: valor ao produto na camada 2, e o nome do catalogo vive no COM. So existe
#: porque uma `Oferta` exige nome, e e um nome sem digitos nem moeda.
NOME_NEUTRO: Final = "Produto sob consulta"


def modelo_da_proposta(
    *,
    quote_id: str,
    sku: str,
    condicoes: str | None,
) -> str:
    """O modelo da mensagem ao cliente, **com os numeros por referencia**.

    O valor e a validade nao estao aqui: estao como `{{quote_price:…}}` e
    `{{validade:…}}`, e so o `preencher` os escreve, a partir dos *facts*. O
    `sku` vai na linha do valor, como num bloco `item`, porque e ele que prende
    o valor ao produto na camada 2.
    """
    qid = str(uuid.UUID(str(quote_id)))
    linhas = [
        ROTULO,
        f"Referencia: {referencia_interna(qid)}",
        f"Produto {sku}: {{{{quote_price:{qid}}}}}",
        f"Valido ate {{{{validade:{qid}}}}}",
    ]
    if condicoes:
        linhas.append(f"Condicoes: {condicoes}")
    return "\n".join(linhas)


def preencher(modelo: str, facts: tuple[Any, ...]) -> str:
    """O *renderer* por referencia da proposta: cada `{{…}}` pelo seu *fact*.

    `quote_price` le o *fact* `quote_price` com aquele `fact_id`; `validade` le
    o *fact* `datetime` com `fact_id` `<quote_id>:validade` e escreve so a data.
    Uma referencia sem *fact*, ou com um valor que nao e inteiro, **levanta**.
    """

    def trocar(achado: re.Match[str]) -> str:
        tipo, qid = achado.group(1), achado.group(2)
        if tipo == "quote_price":
            fact = next(
                (f for f in facts if f.kind == "quote_price" and f.fact_id == qid), None
            )
            valor = getattr(fact, "value", None)
            if not isinstance(valor, int) or isinstance(valor, bool):
                raise ModeloInvalidoError("sem fact quote_price para a referencia")
            return eco_do_valor(valor)
        fact = next(
            (f for f in facts if f.kind == "datetime" and f.fact_id == f"{qid}:validade"),
            None,
        )
        valor = getattr(fact, "value", None)
        if not isinstance(valor, str):
            raise ModeloInvalidoError("sem fact de validade para a referencia")
        return f"{em_luanda(valor):%d/%m/%Y}"

    return _REFERENCIA.sub(trocar, modelo)


def instante_da_validade(validade_ate: datetime.date) -> str:
    """O `value` do *fact* `datetime` da validade: o meio-dia de Luanda desse dia.

    O meio-dia, e nao a meia-noite, para que nenhum desvio de fuso mude o dia
    que o `formas_de_datahora` escreve.
    """
    meio_dia = datetime.datetime.combine(validade_ate, datetime.time(12), tzinfo=LUANDA)
    return meio_dia.astimezone(datetime.UTC).isoformat()


__all__ = [
    "ABERTOS",
    "AGUARDA_JANELA",
    "CANCELADO",
    "CONDICOES_MAX",
    "ENVIADO",
    "ESPERA_DO_DONO",
    "ESTADOS",
    "EXPIRADO",
    "FINAIS",
    "JANELA_DE_REPETICAO",
    "ModeloInvalidoError",
    "PEDIDO",
    "RECUSAS_DAS_CONDICOES",
    "RECUSAS_DO_VALOR",
    "RESPONDIDO",
    "ROTULO",
    "TRANSICOES",
    "VALIDADE_POR_OMISSAO",
    "ValorRecusadoError",
    "conferir_condicoes",
    "data_display",
    "eco_do_valor",
    "hoje_em_luanda",
    "instante_da_validade",
    "ler_valor_do_dono",
    "modelo_da_proposta",
    "pode_passar",
    "preencher",
    "referencia_interna",
    "validade_por_omissao",
]
