"""O fornecedor de embeddings **falso** com que o modo hibrido se mede (KAM-064).

Nao ha modelo escolhido (`kamba-embed` esta `por_decidir`), nem chave, nem LLM
pago. O modo hibrido mede-se entao com um vector **local e deterministico**:
os trigramas de caracteres do texto, cada um num dos `DIMENSAO` baldes pelo
`crc32`, normalizado a norma 1. A distancia de cosseno entre dois destes
vectores e a sobreposicao de trigramas — e por isso que este fornecedor
**nao mede modelo nenhum**: o que o ramo `sem` acrescenta com ele e uma segunda
leitura do `pg_trgm`, e nao semantica. Serve para tres coisas, e so para elas:

* exercitar o caminho hibrido inteiro (o *worker* do catalogo, a porta, o
  `p_qvec`, o RRF com os tres ramos) sobre o *dataset*;
* dar ao *gate* uma linha de base do modo hibrido contra a qual uma troca de
  pesos ou de `idx.candidatos` se compara;
* deixar o formato do relatorio pronto para o dia em que o fornecedor for real.

O nome do modelo (`MODELO`) vai a linha de base: o `gate` recusa comparar um
hibrido medido com outro fornecedor.
"""

from __future__ import annotations

import math
import zlib
from typing import Final

#: O nome que o fornecedor diz ter respondido, e o que fica na linha de base.
MODELO: Final = "falso-trigramas-v1"

#: O destino que declara a porta: nenhum sai da maquina.
FORNECEDOR: Final = "falso-local"

DIMENSAO: Final = 1024


def trigramas(texto: str) -> list[str]:
    """Os trigramas de caracteres de cada palavra, com as margens (`  a`)."""
    saida: list[str] = []
    for palavra in texto.split():
        cercada = f"  {palavra} "
        saida.extend(cercada[i : i + 3] for i in range(len(cercada) - 2))
    return saida


def vector(texto: str, dimensao: int = DIMENSAO) -> tuple[float, ...]:
    """O vector de `texto`. Nunca nulo: um texto sem trigramas levanta."""
    baldes = [0.0] * dimensao
    for trigrama in trigramas(texto):
        baldes[zlib.crc32(trigrama.encode("utf-8")) % dimensao] += 1.0
    norma = math.sqrt(sum(x * x for x in baldes))
    if norma == 0:
        raise ValueError("texto sem trigramas nao tem vector")
    return tuple(x / norma for x in baldes)
