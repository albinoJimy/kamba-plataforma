"""O off-boarding de um tenant, do lado dos dados (KAM-098).

Tres das sete fases de `platform.offboarding_run`: a `exportacao` (o pacote ao
titular, com manifesto e *hash*, e a ligacao de 24 h), a `purga` (D30, com o
`purge_log` do KAM-071 e a retencao por disputa) e o `certificado` (D30, a lista
do que saiu e do que ficou, com fundamento). E a reaplicacao da purga depois de
um restauro de copia de seguranca.

As outras quatro fases — o pedido com a dupla confirmacao, os pendentes, o canal
e a revogacao — sao do `packages/core-ts/src/offboarding/`, porque usam as
portas e o guarda da saga de provisioning (KAM-091). Os dois lados leem-se pela
base: o prazo de cada fase escreve-o o pedido, e este modulo le o `prazo_at`.
"""

from .contrato import (
    FaseForaDeOrdem,
    LigacaoRecusada,
    ler_fases,
    subestado,
)
from .exportacao import (
    VERSAO_DO_MANIFESTO,
    abrir_ligacao,
    exportar,
    ligacao_assinada,
    montar_pacote,
)
from .purga import (
    CAMINHOS_DO_ENCERRAMENTO,
    TABELAS_DOS_CONTACTOS,
    purgar,
    reaplicar_apos_restauro,
    tenants_purgados,
)
from .certificado import VERSAO_DO_CERTIFICADO, emitir_certificado, verificar_certificado

__all__ = [
    "CAMINHOS_DO_ENCERRAMENTO",
    "FaseForaDeOrdem",
    "LigacaoRecusada",
    "TABELAS_DOS_CONTACTOS",
    "VERSAO_DO_CERTIFICADO",
    "VERSAO_DO_MANIFESTO",
    "abrir_ligacao",
    "emitir_certificado",
    "exportar",
    "ler_fases",
    "ligacao_assinada",
    "montar_pacote",
    "purgar",
    "reaplicar_apos_restauro",
    "subestado",
    "tenants_purgados",
    "verificar_certificado",
]
