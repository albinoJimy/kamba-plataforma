"""O `ExtractorDeVisao` do KAM-049 pelo gateway: o alias `kamba-vision` (KAM-231).

Decisao do fundador de 2026-11-21 (P2, opcao A): a foto sai **so** pelo
`ClienteDeLlm.ver`, um metodo proprio do papel `vision` e da finalidade
`visao`, que so aceita uma `ImagemLimpa` e manda uma instrucao fixa. Recusadas:
o detector de PII na imagem (B) e deixar a visao por ligar (C).

## O caminho de uma foto ate ao modelo

```text
ServicoDeIngestao  etapa 1: limpar_metadados -> STO      (os bytes limpos)
                   etapa 3: o gate do KAM-069 para os fornecedores daqui
VisaoPeloGateway   ImagemLimpa.de(bytes)    -- limpa outra vez e sela
ClienteDeLlm.ver   o gate outra vez, a chave do tenant, a linha em dat.llm_call_log
```

O *gate* corre duas vezes de proposito: a do pipeline bloqueia a ingestao com
`sem_destino` antes de qualquer custo, e a do cliente e a que nenhum caminho
contorna. A segunda limpeza e idempotente (medida no ensaio): uns bytes ja
limpos saem iguais.

## O custo

O `custo_usd` da resposta e o da linha do `llm_call_log`, e e ele que o
pipeline soma na `custo_llm_usd` da ingestao (o criterio 5). Sem preco na
`llm/precos.yaml` (`modelo: por_decidir`), o cliente da custo nulo e conta
`agr_llm_sem_preco_total`; aqui isso e **zero**, porque o tipo do KAM-049 nao
tem nulo — e o painel le a metrica, nao a soma.
"""

from __future__ import annotations

import uuid
from dataclasses import dataclass, field
from decimal import Decimal

from kamba_core.catalogo.exif import FormatoNaoSuportado, ImagemComMetadados, ImagemInvalida, ImagemLimpa
from kamba_core.catalogo.pipeline import ErroDaVisao, RespostaDaVisao

from ..llm.cliente import PAPEL_DA_VISAO, ClienteDeLlm, ContextoDeChamada
from ..llm.erros import ErroDeLlm

#: O tecto da chamada a visao, em segundos (*proposta*). Cabe no tecto de 25 s
#: do `create_product_draft` de foto (P3), com o resto do pipeline.
TECTO_DA_VISAO_S = 18.0


@dataclass(frozen=True)
class VisaoPeloGateway:
    """A visao do pipeline sobre o `ClienteDeLlm.ver`."""

    cliente: ClienteDeLlm
    tecto_s: float = TECTO_DA_VISAO_S
    fornecedores: tuple[str, ...] = field(init=False)

    def __post_init__(self) -> None:
        object.__setattr__(self, "fornecedores", self.cliente.fornecedores_de(PAPEL_DA_VISAO))

    def extrair(self, tenant_id: str, imagem: bytes) -> RespostaDaVisao:
        try:
            limpa = ImagemLimpa.de(imagem)
        except (FormatoNaoSuportado, ImagemInvalida, ImagemComMetadados) as erro:
            raise ErroDaVisao(f"a imagem nao se limpa: {type(erro).__name__}") from None
        ctx = ContextoDeChamada(
            tenant_id=tenant_id,
            trace_id=uuid.uuid4().hex,
            vertical="dono",
            no_grafo="catalogo",
        )
        try:
            resposta = self.cliente.ver(limpa, ctx, tecto_s=self.tecto_s)
        except ErroDeLlm as erro:
            # A linha da falha ja ficou gravada pelo cliente, sem custo.
            raise ErroDaVisao(f"a visao falhou: {erro.resultado}") from None
        return RespostaDaVisao(texto=resposta.texto, custo_usd=resposta.custo_usd or Decimal(0))


__all__ = ["TECTO_DA_VISAO_S", "VisaoPeloGateway"]
