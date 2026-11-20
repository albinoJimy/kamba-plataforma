"""As regras puras do Orcamento expresso (KAM-123): sem base, sem relogio proprio.

| Regra | O que decide |
|---|---|
| `ESTADOS` e `TRANSICOES` | os seis estados de `quote_requests.estado` e por onde se anda |
| `ler_valor_do_dono` | o valor **digitado pelo dono** -> centimos, ou recusa por ambiguidade |
| `validade_por_omissao` | a data de validade quando o dono nao a da (sete dias, *proposta*) |
| `conferir_condicoes` | o texto livre do dono: tamanho, **sem numeros**, guarda de entrada e o `screen` do KAM-088 |
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

from kamba_core.catalogo.screening import DECISOES as DECISOES_DO_SCREEN
from kamba_core.catalogo.screening import (
    PERMITIDA,
    SCREENING_INDISPONIVEL,
    PortaDeScreening,
)

from ..guardas.regras import veredicto_por_regras
from ..saida import PREFIXO_DO_ACEITO
from ..validador.normalizacao import (
    CENTIMOS_POR_KZ,
    sem_acento,
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

#: Durante quanto tempo, passada a `ESPERA_DO_DONO`, a varredura ainda procura
#: um pedido para a mensagem neutra (KAM-221, *proposta*). A «uma mensagem» e a
#: chave do Outbound (`orcamento:{quote_id}:sem_resposta`), e nao uma coluna: o
#: horizonte so existe para que um pedido que o dono nunca responde nao seja
#: relido em todas as voltas para sempre. Uma varredura parada mais do que isto
#: perde a mensagem desse pedido; o pedido continua visivel ao dono.
HORIZONTE_DO_AVISO: Final = datetime.timedelta(hours=24)


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


#: As formas de um numero que se aceitam **sem** multiplicador: so digitos
#: («120000»), ou grupos de tres com **um** separador de milhares, espaco ou
#: ponto, e centimos opcionais depois da virgula («120 000», «120.000,00»).
_SEM_MULTIPLICADOR: Final = re.compile(r"\d+|\d{1,3}(?:( |\.)\d{3})(?:\1\d{3})*(?:,\d{2})?|\d+,\d{2}")

#: Com multiplicador: um numero pequeno, com uma casa decimal opcional
#: («120 mil», «1,5 milhoes»). «120.000 mil» e um factor de mil a mais.
_COM_MULTIPLICADOR: Final = re.compile(r"\d{1,3}(?:,\d{1,3})?")


def _bem_formado(grupo: str, tem_multiplicador: bool) -> bool:
    """Se o grupo de digitos tem uma das formas que nao deixam duvida.

    «120 50», «1 2 3», «12.000.00» e «1 200.000» recusam: o `para_centimos` le-os
    (milhares por espaco, ultimo separador decimal), mas nenhum e a forma de um
    preco escrito por quem o quis escrever, e o eco nao chega para apanhar um
    zero a menos.
    """
    forma = _COM_MULTIPLICADOR if tem_multiplicador else _SEM_MULTIPLICADOR
    return forma.fullmatch(grupo.replace("\u00a0", " ")) is not None


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
    if grupos and not _bem_formado(grupos[0], tem_multiplicador):
        raise ValorRecusadoError(VALOR_AMBIGUO)
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


class CondicoesRecusadasError(ValueError):
    """As condicoes recusadas pelo `screen`, com a regra que as recusou.

    O `str` e o codigo (`condicoes_recusadas`), como em toda a recusa das
    condicoes, para que quem trata o `ValueError` nao tenha de saber deste caso.
    A `regra` e o `id` da politica que decidiu (`alcool`, `armas`, ...), uma
    regra sintetica do motor (`nao_listada`, `classificador_indisponivel`) ou
    `screening_indisponivel` quando a porta nao respondeu. **Nunca leva o texto.**
    """

    def __init__(self, regra: str) -> None:
        super().__init__(CONDICOES_RECUSADAS)
        self.regra = regra

#: Os veredictos da guarda de entrada que as condicoes nao podem ter. O `ok`, o
#: `out_of_domain` e o `None` passam: «entrega ao domicilio» nao e assunto da
#: loja para as regras do cliente, e nao precisa de ser.
_VEREDICTOS_QUE_RECUSAM: Final = ("injection", "abuse", "card_data", "sensitive")


#: As palavras de numero que podem ser artigo: «uma entrega», «um sinal». So
#: estas passam; «tres dias», «dez por cento» e «meia duzia» recusam.
_ARTIGOS: Final = frozenset({"um", "uma"})

#: O que exprime uma quantidade ou uma percentagem sem ser palavra de numero.
_QUANTIFICADORES: Final = re.compile(r"\b(por ?cento|percent\w*|duzia|dezena|centena|meia|metade|dobro|triplo)\b")


def _tem_numero_por_extenso(texto: str) -> bool:
    """Uma palavra de numero (menos o artigo) ou um quantificador.

    **O extractor do validador nao chega**: le «dez mil kwanzas» por ter moeda,
    mas nao «tres dias» nem «dez por cento de sinal», e a proposta com isso
    passava a camada 2 (achado da revisao adversarial). Recusa-se pela lista de
    palavras do proprio `normalizacao.py`, que e a lista do parser.
    """
    from ..validador.normalizacao import PALAVRAS_DE_NUMERO

    normal = sem_acento(texto.lower())
    palavras = set(re.findall(r"[a-z]+", normal))
    if (palavras & PALAVRAS_DE_NUMERO) - _ARTIGOS - {"e"}:
        return True
    return _QUANTIFICADORES.search(normal) is not None


def conferir_condicoes(
    texto: object, *, screening: PortaDeScreening, tenant_id: str, quote_id: str
) -> str | None:
    """As condicoes limpas, `None` se nao houver, ou levanta `ValueError(codigo)`.

    **Sem numeros, nem por extenso**: as condicoes vao ao cliente dentro da
    proposta, e um numero escrito pelo dono ali era um numero que nenhum *fact*
    sustenta. Recusa-se aqui, onde o dono ainda pode reescrever («entrega em tres
    dias» passa a «entrega combinada consigo»), e **nao** se confia no validador:
    o extractor dele nao le percentagens nem quantidades por extenso.

    A guarda e a de entrada do KAM-033 (`veredicto_por_regras`), as mesmas
    regras de injeccao que um cliente encontra: um texto do dono e dado nao
    fiavel quando chega a outra pessoa. Fica como defesa em profundidade.

    **Depois, o `screen` do KAM-088** (KAM-222), pela `screening` com o
    `quote_id` como sujeito. So `permitida` deixa as condicoes seguir: a
    `condicional` e a `bloqueada` recusam, e uma porta que levanta tambem. As
    recusas levantam `CondicoesRecusadasError` com a regra. O `screen` corre
    **por ultimo** por duas razoes: as recusas locais nao custam uma chamada ao
    COM nem ao classificador, e um texto com numeros nunca sai do AGR.
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

    if (
        re.search(r"\d", limpo)
        or any(linha.numeros for linha in extrair(limpo))
        or _tem_numero_por_extenso(limpo)
    ):
        raise ValueError(CONDICOES_COM_NUMEROS)
    if veredicto_por_regras(limpo) in _VEREDICTOS_QUE_RECUSAM:
        raise ValueError(CONDICOES_RECUSADAS)
    try:
        resultado = screening.screen(tenant_id, quote_id, None, (limpo,))
    except Exception:  # noqa: BLE001 — uma porta que falha recusa
        raise CondicoesRecusadasError(SCREENING_INDISPONIVEL) from None
    if getattr(resultado, "decisao", None) != PERMITIDA:
        raise CondicoesRecusadasError(_regra_da_recusa(resultado))
    return limpo


def _regra_da_recusa(resultado: object) -> str:
    """A regra que recusou: a **ultima** da lista do `screen`.

    Nao e o `categoria_restrita` do Catalogo AI, e a diferenca importa. Numa
    `permitida` das regras que o classificador desceu, a lista do `screen` e a
    categoria permitida e depois a regra sintetica (`moda`,
    `classificador_indisponivel`), e o primeiro da lista com forma de categoria
    seria `moda`, que e a categoria que **passou**. A regra sintetica entra
    sempre no fim, e uma lista so de regras restritivas vem ordenada: a ultima e
    sempre uma razao da recusa.
    """
    if getattr(resultado, "decisao", None) not in DECISOES_DO_SCREEN:
        return SCREENING_INDISPONIVEL
    regras = getattr(resultado, "regras", ())
    if regras and isinstance(regras[-1], str) and regras[-1]:
        return regras[-1]
    return str(getattr(resultado, "decisao"))


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


def prefixo_da_referencia(referencia: object) -> str | None:
    """Os oito hexadecimais de onde uma referencia `ORC-…` veio, ou `None`."""
    if not isinstance(referencia, str):
        return None
    casado = re.fullmatch(r"ORC-([A-HJ-NP-R]{8})", referencia.strip().upper())
    if casado is None:
        return None
    return "".join(f"{_LETRAS_DA_REFERENCIA.index(c):x}" for c in casado.group(1))


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
        f"Valor final ({sku}): {{{{quote_price:{qid}}}}}",
        f"Valido ate {{{{validade:{qid}}}}}",
    ]
    if condicoes:
        linhas.append(f"Condicoes: {condicoes}")
    return "\n".join(linhas)


def texto_sem_resposta(quote_id: str) -> str:
    """A mensagem neutra ao cliente quando o dono nao respondeu (KAM-221).

    **Sem numero nenhum**, nem o prazo: «vinte e quatro horas» numa mensagem
    era um numero sem *fact*, e o que o cliente precisa de saber e que o pedido
    nao se perdeu e que pode falar com uma pessoa. A referencia e so letras.
    Nao promete valor nem prazo, porque nenhum dos dois e da plataforma.

    A palavra que se sugere e a `PALAVRA_DE_HUMANO`, e nao «pessoa»: e uma que
    o `classify` do Vendedor le como pedido de humano sozinha (o ensaio
    `test_a_palavra_sugerida_e_um_pedido_de_humano` liga as duas).
    """
    return "\n".join(
        (
            f"O seu pedido de orçamento {referencia_interna(quote_id)} ainda está à espera da loja.",
            f"Se preferir, responda «{PALAVRA_DE_HUMANO}» e alguém da loja fala consigo.",
        )
    )


#: A resposta que a mensagem neutra sugere para a oferta de humano.
PALAVRA_DE_HUMANO: Final = "atendente"


def botao_aceitar(quote_id: object) -> str:
    """O botao «Aceito» da proposta: `aceitar_orcamento:ORC-…` (KAM-226; dicionario §3.79).

    **A referencia vai no identificador** (decisao do fundador de 2026-11-20,
    opcao B do KAM-226): um botao esta preso a uma mensagem, e o toque aceita
    **aquela** proposta, e nao o ultimo pedido do cliente. Sem a referencia, o
    botao de uma proposta vencida aceitava a mais nova (achado 1 da revisao).
    A referencia e so letras, e e a que a proposta mostra; o `quote_id` nunca
    vai ao ecra. Vive aqui, e nao no grafo, porque a ToolLayer o poe na proposta
    e nao importa das verticais.
    """
    return f"{PREFIXO_DO_ACEITO}{referencia_interna(quote_id)}"


def referencia_do_aceito(botao: object) -> str | None:
    """A referencia `ORC-…` de um botao «Aceito», ou `None` se o botao nao for um."""
    if not isinstance(botao, str) or not botao.startswith(PREFIXO_DO_ACEITO):
        return None
    referencia = botao[len(PREFIXO_DO_ACEITO) :].strip().upper()
    return referencia if prefixo_da_referencia(referencia) is not None else None


def texto_do_aviso_ao_dono(quote_id: str) -> str:
    """O aviso proactivo ao dono de um pedido novo (KAM-226).

    **Sem numero nenhum**, nem o `sku` nem a quantidade: o aviso diz que ha um
    pedido e qual e a referencia, e a lista dos pendentes (o `orcamento` do grafo
    do dono, pela palavra «pendentes») mostra o resto pela forma que o validador
    deixa citar. A referencia e so letras. Sem acentos, como os textos do grafo
    do dono.
    """
    return "\n".join(
        (
            f"Tem um pedido de orcamento novo: {referencia_interna(quote_id)}.",
            "Escreva «pendentes» para ver os pedidos em aberto.",
        )
    )


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
    "HORIZONTE_DO_AVISO",
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
    "CondicoesRecusadasError",
    "data_display",
    "eco_do_valor",
    "hoje_em_luanda",
    "instante_da_validade",
    "ler_valor_do_dono",
    "modelo_da_proposta",
    "pode_passar",
    "preencher",
    "referencia_interna",
    "texto_sem_resposta",
    "validade_por_omissao",
]
