# Fixtures do canario do `obs_lint`

Geradas por `scripts` da sessao e **versionadas**: o canario le o disco, nao
gera nada em execucao.

Cada pasta de `negativas/` chama-se `<regra>__<descricao>` e a regra antes do
primeiro `__` e a que **tem de ser a unica** a morder nessa raiz. Uma fixture
que morda duas regras falha o canario, porque entao o defeito nao esta isolado
e o teste nao diz qual das regras o apanhou.

## O par que prova o criterio 3

Duas destas fixtures leem-se juntas, e sao a resposta ao criterio 3 do KAM-080
(«`tenant_id` permitido como etiqueta; `contact_id`, telefone e BSUID
proibidos»):

| Fixture | O que prova |
|---|---|
| `positivas/tenant_id_passa_pelo_nome` | o **nome** `tenant_id` passa |
| `negativas/valor_fora_da_gramatica__uuid_no_dominio` | um **UUID** nao passa, mesmo com o nome permitido |
| `negativas/etiqueta_proibida__contact_id` | o `contact_id` recusa-se pelo nome |

A terceira linha vale tambem pelo telefone e pelo BSUID: estao na mesma lista
(`ETIQUETAS_PROIBIDAS`), e os testes exercitam-nos um a um — a fixture nomeia o
`contact_id` porque uma fixture por nome proibido seriam dezasseis raizes para
provar a mesma regra uma vez.
