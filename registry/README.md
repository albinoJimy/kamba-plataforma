# AgentRegistry

Directório reservado pelo **KAM-001**; o conteúdo é do **EPIC-03**.

Aqui vivem os ficheiros `registry/*.yaml` do **AgentRegistry**: o registo de
verticais e dos módulos de entrada, versionado em **SemVer** (`specs/01` §5).

Duas regras que já valem, antes de existir o primeiro ficheiro:

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
