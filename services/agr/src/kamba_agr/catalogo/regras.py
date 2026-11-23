"""As regras da conversa do catalogo com o dono (KAM-119). Puras: sem base nem rede.

## O preco sai so do dono, e so depois do eco

O texto do dono le-se pelo *parser* deterministico do Orcamento expresso
(`orcamento.regras.ler_valor_do_dono`, KAM-123), que **recusa** o que nao e um
valor so: «45 ou 50 mil», «a partir de 45 mil», uma conta, uma moeda
estrangeira, «1.5». A unica forma que este modulo acrescenta e o «k» de milhar
(«45k», «1,5k»), que aquele recusa por nao ser de orcamento e que o criterio 3
do bloco nomeia. **O valor lido nao se grava**: volta ao dono como eco
(«45.000 Kz?») com dois botoes, e so o toque em `preco:{ingestao}:{centimos}`
leva o valor a ingestao. Um texto nao tem por onde gravar um preco.

O valor que o botao leva passa a ingestao pelo `interpretar` do KAM-049, que le
com o `ler_preco` do indice. Por isso o botao nao leva o texto do dono, mas a
forma canonica `«N kz»` do valor ja lido, e `texto_canonico` confere que o
`ler_preco` a le de volta ao mesmo valor — ou levanta, e nada se grava.

## A referencia `PRD-…`

Oito letras derivadas do `id` da ingestao, pela razao do `ORC-…`: sem digitos
(um digito no texto e um numero que o validador quer ver sustentado), e trinta e
dois bits chegam para distinguir os rascunhos abertos de uma loja. Com mais de
um rascunho a espera de resposta, o dono escreve a referencia; com um so, nao
precisa.

## A resposta reparte-se por linhas

Uma mensagem pode levar ate tres perguntas leves (`completude.MAXIMO_POR_MENSAGEM`).
A resposta reparte-se **por linhas, pela ordem das perguntas**, e so quando o
numero de linhas e o numero de perguntas; senao pede-se uma por linha. Nao ha
modelo a adivinhar que pedaco de texto e a cor e qual e o tamanho: era um modelo
a escrever campos do produto. As criticas (preco e stock) vem sozinhas.
"""

from __future__ import annotations

import re
import uuid
from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from typing import Final

from kamba_core.catalogo import completude
from kamba_core.catalogo.extraccao import Campo
from kamba_core.catalogo.normalizacao import ler_preco

from ..orcamento.regras import ValorRecusadoError, ler_valor_do_dono
from ..validador.normalizacao import kz_display

#: O prefixo da referencia de um produto em preparacao.
PREFIXO_DA_REFERENCIA: Final = "PRD-"

#: As dezasseis letras, sem `I` nem `O`: as mesmas do `ORC-…`.
_LETRAS: Final = "ABCDEFGHJKLMNPQR"

#: Uma referencia `PRD-…` no texto do dono, sem distinguir maiusculas.
REFERENCIA_NO_TEXTO: Final = re.compile(r"\bPRD-([A-HJ-NP-R]{8})\b", re.IGNORECASE)

_UUID: Final = re.compile(r"[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}")

#: Os botoes da conversa do catalogo. O `id` leva a ingestao (e o valor, no do
#: preco): e um identificador que **nos** emitimos, e so chega ao AGR num turno
#: `interactive` (KAM-211). O titulo de cada um esta em `saida.TITULOS_POR_PREFIXO`.
PREFIXO_DO_PRECO: Final = "preco:"
PREFIXO_DE_CORRIGIR_PRECO: Final = "preco_corrigir:"
PREFIXO_DO_STOCK: Final = "stock:"
PREFIXO_DE_CORRIGIR_STOCK: Final = "stock_corrigir:"
PREFIXO_DO_MESMO_PRODUTO: Final = "mesmo_produto:"
PREFIXO_DE_OUTRO_PRODUTO: Final = "outro_produto:"

_BOTAO_DO_PRECO: Final = re.compile(rf"preco:({_UUID.pattern}):([1-9][0-9]{{0,14}})")
_BOTAO_DO_STOCK: Final = re.compile(rf"stock:({_UUID.pattern}):(0|[1-9][0-9]{{0,6}})")
_BOTAO_DE_INGESTAO: Final = re.compile(
    rf"(preco_corrigir|stock_corrigir|mesmo_produto|outro_produto):({_UUID.pattern})"
)

#: O stock que o dono escreve: um inteiro so, com a unidade facultativa. **Sem
#: separador de milhares nem multiplicador**: «1.500», «2 mil», «12k» voltam a
#: perguntar, porque o `interpretar` do KAM-049 leria «50 mil» como 50 (achado 6
#: da revisao adversarial).
_STOCK_DO_DONO: Final = re.compile(
    r"^\s*(\d{1,7})\s*(?:unidades?|unid\.?|un\.?|pecas|peças|pcs)?\s*\.?\s*$", re.IGNORECASE
)

#: O tecto do stock, o mesmo do `_ler_inteiro` do KAM-049.
STOCK_MAXIMO: Final = 1_000_000

#: O que nao e resposta a uma pergunta do rascunho, mesmo com um a espera
#: (achado 3 da revisao adversarial): cumprimentos, agradecimentos e acordos
#: soltos. Sem acentos e em minusculas.
_SOCIAIS: Final = frozenset(
    "bom dia|boa tarde|boa noite|ola|oi|ola bom dia|ola boa tarde|ola boa noite|obrigado|obrigada|"
    "muito obrigado|muito obrigada|ok|okay|ta bem|esta bem|tudo bem|certo|sim|nao|pronto|beleza|"
    "valeu|bom|ate logo|adeus|tchau".split("|")
)
_COMECOS_SOCIAIS: Final = ("bom dia", "boa tarde", "boa noite", "ola", "oi ")


class StockRecusado(ValueError):
    """O texto nao e um stock sem duvidas: volta a perguntar."""

#: A numeracao que o dono pode por a frente de cada linha: «1) azul», «2. M e L».
_NUMERACAO: Final = re.compile(r"^\(?\d{1,2}[).]\s+")


# ----------------------------------------------------------------- a referencia


def referencia_do_produto(ingestao_id: object) -> str:
    """`PRD-` e oito letras derivadas do `id` da ingestao."""
    return PREFIXO_DA_REFERENCIA + "".join(
        _LETRAS[int(c, 16)] for c in uuid.UUID(str(ingestao_id)).hex[:8]
    )


def prefixo_da_referencia(referencia: object) -> str | None:
    """Os oito hexadecimais de onde uma referencia `PRD-…` veio, ou `None`."""
    if not isinstance(referencia, str):
        return None
    casado = re.fullmatch(r"PRD-([A-HJ-NP-R]{8})", referencia.strip().upper())
    if casado is None:
        return None
    return "".join(f"{_LETRAS.index(c):x}" for c in casado.group(1))


def referencia_no_texto(texto: str) -> tuple[str | None, str]:
    """`(referencia, resto)`: a referencia tirada do texto, e o texto sem ela."""
    achada = REFERENCIA_NO_TEXTO.search(texto)
    referencia = f"PRD-{achada.group(1).upper()}" if achada else None
    resto = REFERENCIA_NO_TEXTO.sub(" ", texto)
    linhas = [" ".join(linha.split()).strip(" :;,-") for linha in resto.splitlines()]
    return referencia, "\n".join(linha for linha in linhas if linha)


# ----------------------------------------------------------------- as perguntas


@dataclass(frozen=True)
class PerguntaEmAberto:
    """Uma pergunta ao dono, com a sugestao ja legivel (a da etiqueta, em Kz)."""

    campo: str
    texto: str
    sugestao: str | None = None


def perguntas_em_aberto(
    campos: Mapping[str, Campo], perguntas_feitas: int, preco_sugerido: str | None = None
) -> tuple[PerguntaEmAberto, ...]:
    """As perguntas a que o dono esta a responder, recalculadas da ingestao.

    Sao as da proxima mensagem do KAM-049 (`completude.proximas_perguntas`): um
    critico sozinho, ou ate tres leves. Recalculam-se em vez de se guardarem,
    porque dependem so dos campos — a ingestao que as fez e a mesma que diz o
    que falta. **Com o tecto das doze esgotado nao ha perguntas em aberto**: e o
    caso que o KAM-049 manda para o painel.
    """
    if perguntas_feitas >= completude.MAXIMO_DE_PERGUNTAS:
        return ()
    perfil = completude.perfil_dos_campos(campos)
    sugestao = kz_display(int(preco_sugerido)) if preco_sugerido and preco_sugerido.isdigit() else None
    return tuple(
        PerguntaEmAberto(
            campo=p.campo,
            texto=p.texto,
            sugestao=sugestao if p.campo == "preco" else p.sugestao,
        )
        for p in completude.proximas_perguntas(campos, perfil, 0, preco_sugerido=None)
    )


def repartir_respostas(texto: str, perguntas: Sequence[PerguntaEmAberto]) -> dict[str, str] | None:
    """A resposta do dono por campo, ou `None` se nao der para saber.

    Uma pergunta: o texto inteiro. Varias: uma linha por pergunta, pela ordem.
    **O preco e o stock nunca saem daqui** — sao do eco (`ler_preco_do_dono`,
    `ler_stock_do_dono` e os botoes).
    """
    campos = [p.campo for p in perguntas]
    if not campos or "preco" in campos or "stock" in campos:
        return None
    linhas = [_NUMERACAO.sub("", linha.strip()) for linha in texto.splitlines() if linha.strip()]
    linhas = [linha for linha in linhas if linha]
    if not linhas:
        return None
    if len(campos) == 1:
        return {campos[0]: " ".join(linhas)}
    if len(linhas) != len(campos):
        return None
    return dict(zip(campos, linhas, strict=True))


# ----------------------------------------------------------------- o preco


def ler_preco_do_dono(texto: str) -> int:
    """O preco que o dono escreveu, em centimos. Levanta `ValorRecusadoError` se nao for um.

    O *parser* do KAM-123, que le o «k» de milhar desde o KAM-237. Ver o cabecalho.
    """
    return ler_valor_do_dono(texto)


def texto_canonico(centimos: int) -> str:
    """A forma que o botao leva a ingestao: `«N kz»`, que o `ler_preco` le de volta.

    Levanta `ValueError` se o `ler_preco` do KAM-049 nao a ler ao mesmo valor:
    nesse caso o valor gravado seria outro que nao o do eco, e nao se grava.
    """
    if centimos <= 0 or centimos % 100:
        raise ValueError("so valores inteiros em Kz")
    canonico = f"{centimos // 100} kz"
    lido = ler_preco(canonico)
    if lido is None or lido.minor != centimos:
        raise ValueError("a forma canonica nao se le de volta ao mesmo valor")
    return canonico


def eco_do_preco(centimos: int) -> str:
    """«45.000 Kz?» — o valor que o *parser* leu, na forma da letra do criterio 3.

    **O ponto de milhares e o da letra**, e nao o espaco do `precoDisplay`
    (`kz_display`) que o resumo usa: o criterio escreve o eco por extenso. Os
    dois leem-se pelo mesmo *parser*. So valores inteiros em Kz chegam aqui (o
    `ler_valor_do_dono` recusa centimos).
    """
    return f"{centimos // 100:,}".replace(",", ".") + " Kz?"


# ----------------------------------------------------------------- o stock


def ler_stock_do_dono(texto: str) -> int:
    """As unidades que o dono escreveu. Levanta `StockRecusado` se nao for um inteiro so."""
    casado = _STOCK_DO_DONO.fullmatch(texto or "")
    if casado is None:
        raise StockRecusado("stock_ambiguo")
    valor = int(casado.group(1))
    if valor > STOCK_MAXIMO:
        raise StockRecusado("stock_fora_do_intervalo")
    return valor


def eco_do_stock(unidades: int) -> str:
    """«50 unidades?» — o valor que o *parser* leu, antes de se gravar."""
    return f"{unidades} unidade?" if unidades == 1 else f"{unidades} unidades?"


# ----------------------------------------------------------------- as respostas


def _sem_acentos(texto: str) -> str:
    import unicodedata

    decomposto = unicodedata.normalize("NFKD", texto.lower())
    return "".join(c for c in decomposto if not unicodedata.combining(c))


def parece_resposta(texto: str) -> bool:
    """Se um texto sem palavra do catalogo pode ser a resposta a uma pergunta do rascunho.

    **Nao** e: uma pergunta (acaba em «?»), um cumprimento, um agradecimento ou
    um acordo solto. «bom dia» gravado na `entrega`, ou «quanto vendi hoje?» no
    `nome`, era texto do dono a ir parar ao produto sem ser resposta.
    """
    limpo = " ".join(_sem_acentos(texto).replace("!", " ").replace(".", " ").replace(",", " ").split())
    if not limpo or texto.strip().endswith("?"):
        return False
    if limpo in _SOCIAIS:
        return False
    return not (any(limpo.startswith(c) for c in _COMECOS_SOCIAIS) and len(limpo.split()) <= 5)


# ----------------------------------------------------------------- os botoes


def botao_do_preco(ingestao_id: str, centimos: int) -> str:
    return f"{PREFIXO_DO_PRECO}{ingestao_id}:{centimos}"


def botao_de_corrigir_preco(ingestao_id: str) -> str:
    return f"{PREFIXO_DE_CORRIGIR_PRECO}{ingestao_id}"


def botao_do_stock(ingestao_id: str, unidades: int) -> str:
    return f"{PREFIXO_DO_STOCK}{ingestao_id}:{unidades}"


def botao_de_corrigir_stock(ingestao_id: str) -> str:
    return f"{PREFIXO_DE_CORRIGIR_STOCK}{ingestao_id}"


def botao_do_mesmo_produto(ingestao_id: str) -> str:
    return f"{PREFIXO_DO_MESMO_PRODUTO}{ingestao_id}"


def botao_de_outro_produto(ingestao_id: str) -> str:
    return f"{PREFIXO_DE_OUTRO_PRODUTO}{ingestao_id}"


@dataclass(frozen=True)
class BotaoDoCatalogo:
    """Um toque num botao do catalogo: o que pede, a ingestao, e o valor (centimos ou unidades)."""

    accao: str
    ingestao: str
    valor: int | None = None


def ler_botao(botao: object) -> BotaoDoCatalogo | None:
    """O botao do catalogo deste turno, ou `None` se nao for um. Por forma, e exacta."""
    if not isinstance(botao, str):
        return None
    preco = _BOTAO_DO_PRECO.fullmatch(botao)
    if preco is not None:
        return BotaoDoCatalogo("preco", preco.group(1), int(preco.group(2)))
    stock = _BOTAO_DO_STOCK.fullmatch(botao)
    if stock is not None:
        return BotaoDoCatalogo("stock", stock.group(1), int(stock.group(2)))
    outro = _BOTAO_DE_INGESTAO.fullmatch(botao)
    if outro is not None:
        return BotaoDoCatalogo(outro.group(1), outro.group(2))
    return None


__all__ = [
    "BotaoDoCatalogo",
    "PerguntaEmAberto",
    "StockRecusado",
    "ValorRecusadoError",
    "botao_de_corrigir_stock",
    "botao_do_stock",
    "eco_do_stock",
    "ler_stock_do_dono",
    "parece_resposta",
    "botao_de_corrigir_preco",
    "botao_de_outro_produto",
    "botao_do_mesmo_produto",
    "botao_do_preco",
    "eco_do_preco",
    "ler_botao",
    "ler_preco_do_dono",
    "perguntas_em_aberto",
    "prefixo_da_referencia",
    "referencia_do_produto",
    "referencia_no_texto",
    "repartir_respostas",
    "texto_canonico",
]
