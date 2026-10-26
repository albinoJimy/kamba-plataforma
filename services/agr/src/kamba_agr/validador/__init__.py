"""O validador de citacao do AGR (`docs/tecnica/02` §9, ADR-007, KAM-032).

| Modulo | O que tem |
|---|---|
| `normalizacao.py` | os nove formatos monetarios PT-AO -> `value_minor` em centimos, e o `kz_display` |
| `extraccao.py` | o extractor: dinheiro, percentagens, datas/horas, quantidades, `sku` e numeros por extenso |
| `render.py` | a **camada 1**: os cinco blocos, preenchidos com *facts* (proposta 02-A) |
| `veredicto.py` | a **camada 2**: os sete veredictos, o vinculo `sku`<->preco, e as cinco metricas |

O ADR-007 manda que cada numero citado exista no *output* real de uma tool. A
garantia vem da camada 1 — o modelo devolve blocos e nao escreve numeros —, e a
camada 2 e a rede de seguranca sobre o texto final e sobre qualquer prosa livre.
O §8.4 diz o que o grafo faz com o veredicto: «retry -> handoff».

## Vive no AGR e nao em `libs/py-core`, e a pasta chama-se `validador/`

O bloco do ticket propoe `kamba/validator/{extract,normalize,facts,verdict,render}.py`.
Fica aqui pela regra que o KAM-025 escreveu por extenso no `estado.py` —
«`libs/py-core` e o que **todos** os servicos Python precisam de fazer da mesma
maneira» — e que o KAM-026, o KAM-027 e o KAM-028 seguiram: o AGR e o unico
processo que compoe e valida uma resposta.

**O nome da pasta nao e so traducao: e o que liga este modulo ao *gate* 4.** O
`ci/thresholds.yaml` tem `*/validador/*` e `*/citacao/*` no estrato `critico`,
com `minimo_linhas: 90`, e escreveu na sua propria nota que «continua a nao
existir codigo de dinheiro nem de validador no repositorio: os padroes desses
dois estao escritos para os tickets que os vao criar […] e o gate comeca a morder
neles no dia em que o primeiro ficheiro bater num padrao». Este e esse dia: com a
pasta chamada `validador/`, o criterio 7 («cobertura >= 90%») passa a ser imposto
por maquina em vez de afirmado num relatorio. Uma pasta chamada `validacao/` ou
`citation/` deixava o estrato vazio e a caixa sem gate que a sustentasse.

(A divida **33** nota que esses dois padroes estao atribuidos ao KAM-007, que e o
catalogo de eventos. O ticket certo e este; a linha da divida e textual e
emenda-se onde ela vive.)

## Os nomes dos ficheiros estao em portugues, e os do contrato em ingles

E a convencao do pacote (`estado.py`, `contexto.py`, `trancas.py`, `registo/`,
`tls/`). O que fica em ingles sao os nomes **do contrato**, porque sao canon
citado do §9.1 e do §3.30 do dicionario: `Verdict`, `Policy`, `Oferta.sku`,
`allowed_literals`, os cinco `blocks[].type` e os sete veredictos.

Sao **quatro** ficheiros e o bloco propoe cinco: o `facts.py` nao existe porque
nao ha nada nele. A procura de um *fact* sao duas compreensoes de lista, e
vivem ao lado de quem decide com elas — como o KAM-028 juntou o `pipeline` ao
`layer` no `camada.py`, e pela mesma razao: o que se ganhava era um nome, o que
se perdia era ler a regra ao lado do numero que ela julga.

## O SemVer, e o que ele serve

O DoD pede «o validador e artefacto comportamental; SemVer atribuido». O numero
esta no `VERSAO` abaixo, e vale dizer o que ele **nao** faz hoje: nada o le. Quem
o vai ler e o *gate* 13 do KAM-040, que fixa o conjunto adversarial no *golden* —
e e por isso que o numero existe antes do gate, e nao depois: um conjunto
comportamental sem versao nao se consegue fixar.

A regra de incremento, para quem cá voltar: **maior** quando um veredicto entra
ou sai da lista fechada, ou quando um bloco entra ou sai; **menor** quando uma
regra passa a recusar o que aceitava (um `kind` novo da divida 105, por exemplo);
**correccao** quando o extractor passa a ler um formato que nao lia.

## Este ficheiro nao importa nenhum modulo do pacote

So o `typing`, para o `VERSAO`. E a forma do `tls/__init__.py`, mas **a razao e
mais fraca e vale dize-lo**: ali
havia um ciclo medido, aqui nao ha. O `metricas.py` deriva a etiqueta `vertical`
do `contexto.py` e nao deste modulo, pelo que o triangulo que o KAM-028
descreveu nao se fecha — um `from .veredicto import validar` aqui importaria
hoje sem erro.

Fica vazio por duas razoes mais pequenas, e nenhuma delas e «ha um ciclo»: o
`veredicto.py` importa o `metricas.py`, pelo que um `__init__` que o reexportasse
punha a biblioteca de metricas no caminho de quem so quer normalizar um valor; e
o KAM-031 e o KAM-035 vao abrir estes ficheiros um a um, como abriram os do
`tls/`. Quem quer o validador importa `kamba_agr.validador.veredicto`.
"""

from typing import Final

#: O SemVer do artefacto comportamental (DoD «Eval-gate»). Ver a nota acima: quem
#: o le e o *gate* 13 do KAM-040, e a regra de incremento esta la escrita.
VERSAO: Final = "1.0.0"
