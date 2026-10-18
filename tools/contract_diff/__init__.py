"""O gate 7: os contratos de evento, e o que os impede de quebrar (KAM-007).

Cinco verificacoes, uma por modulo, e a razao de viverem no mesmo pacote e que
sao a mesma pergunta vista de cinco lados — «este contrato ainda e o que os
consumidores assinaram?»:

    diff         comparar com o ramo principal e classificar cada diferenca em
                 *aditivo-opcional* ou *quebrante* (`docs/tecnica/06` §6.6)
    pii          nenhum nome de campo de PII, e nenhuma fixture com telefone
    exemplos     um exemplo valido por versao, validado contra o seu schema
    subscricoes  a `versao_max` de cada subscricao existe nos contratos
    dominios     os `enum` dos contratos e os dominios do dicionario dizem o
                 mesmo, nos dois sentidos (KAM-159)

A quinta nasceu de um defeito que esteve dois tickets de pe sem nenhum gate o
dizer: o dicionario e os contratos nomeavam listas de finalidades de
consentimento que se cruzavam **numa so**, e duas finalidades do canon eram
impossiveis de emitir. Cada gate verificava o seu lado; ninguem verificava a
costura.

O nome do pacote e o do bloco do KAM-007 (`tools/contract_diff/`). Nasceu para
o classificador e ficou com as outras tres porque correm sempre juntas: o gate
7 e uma coisa so, e separa-las dava quatro alvos de Makefile que ninguem corre
isoladamente.
"""
