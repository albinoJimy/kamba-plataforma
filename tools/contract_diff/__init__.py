"""O gate 7: os contratos de evento, e o que os impede de quebrar (KAM-007).

Quatro verificacoes, uma por modulo, e a razao de viverem no mesmo pacote e que
sao a mesma pergunta vista de quatro lados — «este contrato ainda e o que os
consumidores assinaram?»:

    diff         comparar com o ramo principal e classificar cada diferenca em
                 *aditivo-opcional* ou *quebrante* (`docs/tecnica/06` §6.6)
    pii          nenhum nome de campo de PII, e nenhuma fixture com telefone
    exemplos     um exemplo valido por tipo, validado contra o seu schema
    subscricoes  a `versao_max` de cada subscricao existe nos contratos

O nome do pacote e o do bloco do KAM-007 (`tools/contract_diff/`). Nasceu para
o classificador e ficou com as outras tres porque correm sempre juntas: o gate
7 e uma coisa so, e separa-las dava quatro alvos de Makefile que ninguem corre
isoladamente.
"""
