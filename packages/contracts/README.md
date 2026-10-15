# @kamba/contracts

Contratos em **JSON Schema** — fonte única para TypeScript e Python.

Um contrato definido aqui não é redefinido em nenhuma linguagem. Os tipos de TS
derivam do esquema e o lado Python valida contra o mesmo ficheiro: duas
definições do mesmo contrato divergem, e a divergência só aparece em produção.

## O que existe

| Esquema | Contrato | Consumidores |
|---|---|---|
| `schemas/healthz.response.v1.json` | Resposta de `/healthz` | `packages/core-ts` (TS), `libs/py-core` (Python), `tools/healthz_check.py` (validação em execução) |

## Versionamento

A versão está no nome do ficheiro (`*.v1.json`). Campos novos são **aditivos**;
uma quebra de contrato é um ficheiro `v2` e um *release* MAJOR (`specs/01` §5).
Consumidores falham de forma visível perante versões desconhecidas — não as
ignoram em silêncio.

## O que vem depois

Os envelopes de evento (KAM-005) e os schemas de *tool* (EPIC-03) vivem aqui. Os
nomes de campos vêm de `specs/02_Dicionario_de_Dados_Canonico.md`: dinheiro em
unidade menor inteira (`*_minor`) com moeda explícita, datas em UTC,
`contact_id` e nunca telefone.
