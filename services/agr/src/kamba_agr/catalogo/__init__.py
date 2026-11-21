"""A vertical `catalogo` do Assistente do Dono (KAM-119, `docs/tecnica/02` §21.3, ADR-020).

A **camada conversacional** sobre o pipeline foto -> rascunho do KAM-049
(`kamba_core.catalogo`): o dono manda a foto, responde as perguntas de
completude, confirma o preco no eco e publica no botao. O pipeline nao se
reescreve aqui; monta-se.

| Modulo | O que tem |
|---|---|
| `regras.py` | a referencia `PRD-…`, as perguntas em aberto de uma ingestao, a reparticao de uma resposta por elas, o preco do dono com o eco e os botoes |
| `montagem.py` | o `ServicoDeIngestao` sobre a ligacao da ToolLayer, as portas por ligar (fonte, descodificador, visao) e a porta da foto (`ImageEnhancePort`) com o adaptador nulo |
| `../tls/catalogo_tools.py` | as quatro tools do §21.3 na ToolLayer |
| `../tls/registo_com.py` | a `PortaDoRegisto` sobre a API interna do COM |

Este ficheiro nao importa nenhum deles, pela razao do `orcamento/__init__.py`:
quem quer as regras nao precisa de trazer o *driver* da base.
"""
