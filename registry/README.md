# AgentRegistry

Directório reservado pelo **KAM-001**; o conteúdo é do **EPIC-03**.

Aqui vivem os ficheiros `registry/*.yaml` do **AgentRegistry**: o registo de
verticais e dos módulos de entrada, versionado em **SemVer** (`specs/01` §5).

## O que está aqui hoje

| Ficheiro | Forma | Ticket |
|---|---|---|
| `plans.yaml` | **planos** — chave de topo `plans`: `plano` → entitlements por omissão | KAM-009 |
| `entitlement_keys.schema.json` | o registo das **dez** chaves de `entitlements.limites` e a categoria de cada uma | KAM-009 |

Os ficheiros das **verticais** (`vendedor.yaml`, `servicos.yaml`, a forma de
`../docs/tecnica/02` §5.1) nascem com o EPIC-03.

**Duas formas, e só duas.** Um `registry/*.yaml` é uma vertical (chave de topo
`id`) ou os planos (chave de topo `plans`). O gate 3b distingue-as pela chave
de topo e **nunca** pelo nome do ficheiro, as chaves de topo de cada forma são
listas fechadas, e um ficheiro que não seja nenhuma das duas **falha**
(`tools/canon_lint/registo.py`).

**Os valores dos planos são hipóteses.** Nenhum documento tem a tabela de
planos — o `../docs/tecnica/10` pressupõe-a em quatro sítios e não a escreve, e
a mensalidade por plano não está definida. Por isso cada entrada de
`plans.yaml` leva `estado: hipotese_nao_validada`
(`specs/02_Dicionario_de_Dados_Canonico.md` §4, «Lista de planos e os seus
limites»; dono KAM-109), o gate exige essa marca, e **não se escrevem preços**.

## Duas regras que já valiam antes do primeiro ficheiro

1. **SemVer, e não "última versão".** Grafos, *prompts*, schemas de *tool*,
   schemas de evento e tabelas de política são artefactos comportamentais:
   *MAJOR* = quebra de contrato, *MINOR* = capacidade retro-compatível,
   *PATCH* = correcção. **Trocar o modelo por trás de um alias é um *release***
   e passa o gate golden (`specs/01` §5).
2. **Os `id` de vertical são os do dicionário canónico.**
   `specs/02_Dicionario_de_Dados_Canonico.md` §3 fixa
   `id ∈ {vendedor, servicos, catalogo, social, orcamento}`. Um `id` novo entra
   no dicionário — marcado como proposta — antes de entrar num ficheiro aqui.

O núcleo conversacional é **LangGraph como biblioteca MIT** (ADR-002). O
`langgraph-api` e o `langgraph-runtime-inmem` são Elastic-2.0 e estão na lista de
bloqueio (`tools/blocklist.yaml`): tentar adicioná-los faz `make check` falhar.
