"""O Orcamento expresso do Piloto (KAM-123, `docs/tecnica/02` §21.3, ADR-020).

Uma **forma do fluxo Vendedor**, e nao um motor de precos: quando um produto e
`sob_consulta`, o cliente pede (`request_quote`), o dono fixa o valor
(`submit_quote`, *fact* `quote_price`) e confirma o envio pelo botao do portao
do KAM-118 (`send_quote`). O bot nunca calcula o preco.

| Modulo | O que tem |
|---|---|
| `regras.py` | os estados e as transicoes, o parser do valor do dono, a validade, as condicoes, a referencia `ORC-…` e o modelo da proposta com os numeros por referencia |
| `../tls/orcamento.py` | o SQL contra a `platform.quote_requests`, os eventos `quote.requested` e `quote.sent`, o consumo de `orcamentos_mes` e o envio pelo Outbound |
| `porta.py` | a porta `orcamentos` do processo: o envio depois do botao e a libertacao da janela quando o cliente escreve (KAM-221) |
| `varredura.py` | os dois *jobs* sem agendador: a mensagem neutra das 24 h e a expiracao (KAM-221) |

Este ficheiro nao importa nenhum dos dois, pela razao do `validador/__init__.py`:
quem quer as regras nao precisa de trazer o *driver* da base.
"""
