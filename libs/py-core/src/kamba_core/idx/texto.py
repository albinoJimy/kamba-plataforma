"""O texto que entra no indice e na consulta (KAM-061, `docs/tecnica/05` §4.2 e §5.1).

Duas coisas, e nenhuma delas e o pipeline PT-AO do §5.1 — esse e o **KAM-062**:

* **`normalizar`** e o passo 1 do §5.1 e mais nada: NFKC, minusculas, sem
  acentos, sem pontuacao, espacos colapsados. E a mesma funcao dos dois lados —
  o consumidor normaliza o `nome` antes de o escrever no `nome_norm`, e a camada
  de resposta normaliza a pergunta antes de a passar ao `idx.candidatos` — porque
  um indice e uma consulta normalizados por duas funcoes diferentes divergem no
  primeiro acento que uma delas trate e a outra nao.
* **`exigir_texto_de_embedding`** e a regra dura (b) do §4.2: o texto que gera um
  embedding nao leva preco nem stock, porque um preco dentro de um vector e um
  preco que ninguem consegue citar nem corrigir (ADR-007).

## O que **nao** esta aqui

Marcas, unidades, erros comuns, *stopwords* e sinonimos (passos 4 a 8 do §5.1)
leem o `idx.termo_canonico` e sao o KAM-062. Sem eles, a expansao `q_or` e so os
termos da propria pergunta separados por ` or ` — que e o que basta para o
defeito D7 (uma palavra sem correspondencia ja nao anula a pesquisa textual) e e
o que o KAM-062 alarga com os sinonimos.

**A normalizacao nao e a do `public.unaccent`.** O PostgreSQL tem a sua tabela de
acentos e esta funcao usa a decomposicao Unicode. Nao importa, e e por isso que a
mesma funcao corre dos dois lados: o `nome_norm` e a `p_q_norm` saem ambos
daqui. O `fts` e outra historia — a configuracao `idx.kamba_pt` passa os dois
pelo `unaccent` do PostgreSQL, tambem dos dois lados.
"""

from __future__ import annotations

import re
import unicodedata
from dataclasses import dataclass
from typing import Final

#: O separador da expansao, como o `websearch_to_tsquery` o le (§6.2, defeito D7).
SEPARADOR_OR: Final = " or "

#: Tudo o que nao e letra nem algarismo passa a espaco (passo 1 do §5.1).
_NAO_PALAVRA: Final = re.compile(r"[^0-9a-z]+")

#: Dinheiro: algarismos seguidos de `kz`, `akz` ou `$`, com ou sem espaco, e o
#: `$` antes de algarismos. Le-se sobre o texto **ja sem acentos e em
#: minusculas**, pelo que `500 KZ` e `500kz` sao o mesmo caso.
_DINHEIRO: Final = re.compile(r"\d[\d.,]*\s*(?:akz|kz|\$)|\$\s*\d")

#: As palavras proibidas da regra (b), **sem acento**: a comparacao e feita
#: sobre o texto normalizado, e assim «preço» e «preco» sao a mesma recusa.
PALAVRAS_PROIBIDAS: Final = ("stock", "disponivel", "preco")

_PALAVRA_PROIBIDA: Final = re.compile(
    r"\b(?:" + "|".join(PALAVRAS_PROIBIDAS) + r")\b"
)


def _sem_acentos(texto: str) -> str:
    decomposto = unicodedata.normalize("NFD", texto)
    return "".join(c for c in decomposto if unicodedata.category(c) != "Mn")


def normalizar(texto: str) -> str:
    """O passo 1 do §5.1: NFKC, minusculas, sem acentos, sem pontuacao.

    >>> normalizar("  Frigorífico LG, 250 L!  ")
    'frigorifico lg 250 l'
    """
    base = unicodedata.normalize("NFKC", texto).lower()
    return " ".join(_NAO_PALAVRA.sub(" ", _sem_acentos(base)).split())


@dataclass(frozen=True)
class Consulta:
    """A pergunta como o `idx.candidatos` a recebe: `p_q_norm` e `p_q_or`."""

    q_norm: str
    q_or: str


def consulta(texto: str) -> Consulta:
    """A pergunta normalizada e a sua expansao `or` (defeito D7).

    Os termos repetidos contam uma vez, pela ordem em que aparecem. **Um termo
    so de algarismos nao entra na expansao `or`**: e o passo 3 do §5.1 — os
    numeros sao restricoes (preco, quantidade) e «NAO vao ao indice». Com eles
    no `or`, «quero 2 bicicletas» encontrava o «Arroz 2 kg» pelo `2` e o
    `cart_build` propunha-o: medido no PostgreSQL da imagem do *gate*, o
    `portuguese` guarda o `2` como lexema. Ficam no `q_norm`, que e o que o
    trigrama compara com o nome inteiro (achado 3 da revisao adversarial).

    >>> consulta("Nike Air, nike 42")
    Consulta(q_norm='nike air nike 42', q_or='nike or air')
    """
    q_norm = normalizar(texto)
    termos = [t for t in dict.fromkeys(q_norm.split()) if not t.isdigit()]
    return Consulta(q_norm=q_norm, q_or=SEPARADOR_OR.join(termos))


class TextoDeEmbeddingProibido(ValueError):
    """O texto levava preco ou stock. A mensagem diz **o que**, nunca o texto."""

    def __init__(self, motivos: tuple[str, ...]) -> None:
        super().__init__(
            "texto de embedding recusado (docs/tecnica/05 secao 4.2, regra b): "
            + ", ".join(motivos)
        )
        self.motivos = motivos


def motivos_de_recusa(texto: str) -> tuple[str, ...]:
    """O que torna este texto improprio para embedding; vazio se nada.

    Os motivos sao **categorias**, nunca o excerto: o texto vem do catalogo da
    PME e a mensagem de um erro acaba num registo.
    """
    # O `normalizar` apaga o `$`; a verificacao do dinheiro le o texto em
    # minusculas e sem acentos mas **com** a pontuacao, que e onde o `$` esta.
    bruto = _sem_acentos(unicodedata.normalize("NFKC", texto).lower())
    motivos = ["dinheiro"] if _DINHEIRO.search(bruto) else []
    # Pela ordem de `PALAVRAS_PROIBIDAS` e nao pela do texto: a mesma recusa da
    # sempre os mesmos motivos, pela mesma ordem.
    encontradas = set(_PALAVRA_PROIBIDA.findall(normalizar(texto)))
    motivos.extend(p for p in PALAVRAS_PROIBIDAS if p in encontradas)
    return tuple(motivos)


def exigir_texto_de_embedding(texto: str) -> str:
    """Devolve o texto se puder gerar embedding; levanta se levar preco ou stock."""
    motivos = motivos_de_recusa(texto)
    if motivos:
        raise TextoDeEmbeddingProibido(motivos)
    return texto
