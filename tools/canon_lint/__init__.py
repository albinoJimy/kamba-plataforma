"""canon_lint — gate 3b: lint de nomes canonicos (KAM-111).

Compara os nomes que o repositorio **usa** com os que o dicionario canonico
**fixa** (`specs/02_Dicionario_de_Dados_Canonico.md` §3, exportado para
`canon/dicionario.yaml` pelo `dict_export`).

## Dois niveis de falha

1. **Variante conhecida** — um nome da coluna «Substitui» do §3 (`valor_kz`,
   `sig_ok`, `consent_log`, `llm_calls`, …). Falha **sempre**, em qualquer
   superficie, e a mensagem diz o nome canonico e a seccao:
   «`valor_kz` → `valor_minor`, dicionario §3.4». Nao ha extensao que a salve.
2. **Nome fora do dicionario** — um nome de tabela, coluna, valor de `CHECK`,
   tipo de evento, campo ou *tool* que o §3 nao cobre. So passa se constar de
   `canon/extensoes.yaml`, com nome, tipo, ticket de origem e data.

## Quatro superficies

| Superficie | O que se le | Niveis |
|---|---|---|
| migracoes (`db/migrations/versions/*.py`) | tabelas, colunas, valores de `CHECK`, esquemas, unicidades | 1 e 2 |
| eventos (`contratos/eventos/**/*.schema.json`) | `tipo`, envelope, campos do payload, `versao` fixa | 1 e 2 |
| registo (`registry/*.yaml`) | `id`, modulo, limites, subscricoes, *tools* e parametros | 1 e 2 |
| documentos (`docs/tecnica/**/*.md`) | so as variantes conhecidas | 1 |

A quarta nao esta no criterio de aceitacao do ticket, que enumera tres. Existe
porque a parte (a) do mesmo ticket retira as variantes de `docs/tecnica/`, e sem
uma verificacao por maquina a primeira edicao seguinte repunha-as. As excepcoes
(`ci/canon-allow.yaml`) sao por ficheiro, variante e **numero de ocorrencias**.

## O que este lint nao faz

* Nao le SQL que nao seja literal: `op.execute(f"...")`, `op.create_table(...)`
  e o corpo de funcoes entre `$$` **falham** ou ficam de fora, e esta dito na
  saida. Um lint que saltasse o que nao percebe passava pela razao errada.
* Nao valida semantica: que o gatilho do provisioning e `tenant.approved` e nao
  `tenant.activated` (os dois sao nomes canonicos), ou que a retencao de
  `assistant_queries` e de 12 meses. Duas das doze divergencias do ticket
  (D-07 e D-09) nao tem forma de nome em nenhuma das superficies.
* Nao segue `$ref` externos nos schemas de evento.

Codigos de saida: 0 conforme, 1 achados, 2 erro de configuracao.
"""

__all__ = ["cli"]
