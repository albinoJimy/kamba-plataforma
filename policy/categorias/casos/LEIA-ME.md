# Casos do screening de categorias (KAM-088)

Conjuntos *golden* do motor de screening de categorias. Cada linha de um
`.jsonl` é um caso: `id`, `conjunto`, `categoria_declarada`, `textos` (1 a 3
títulos ou descrições de produto), `esperado` (decisões aceites), `alvo` (id
da categoria da política, ou da categoria permitida) e `severidade`
(`alta` ou `normal`). O `permitido.jsonl` acrescenta `nota` nos casos
enganadores.

| Ficheiro | Objectivo | Esperado | Casos |
|---|---|---|---|
| `canonico.jsonl` | termos exactos da política, para cada uma das onze categorias bloqueadas, quase sempre sob uma categoria declarada inocente («moda», «loja geral», «electrónica») | `bloqueada` | 134 |
| `disfarcado.jsonl` | evasão em português de Angola e de Portugal: *leet*, letras separadas, *emojis* a dividir o termo, acentos tirados ou postos, letras repetidas, palavras partidas, eufemismos, saúde vestida de cosmética, injecção de instruções na descrição | `condicional` ou `bloqueada` | 125 (20 com `severidade: alta`, todos de armas ou medicamentos) |
| `permitido.jsonl` | produtos benignos das cinco categorias permitidas, incluindo casos enganadores mas inocentes («vestido cor de vinho», «armário de cozinha», «pistola de cola quente») | `permitida` | 116 (25 com `nota`) |

As contagens são de facto medidas, com o comando:

    wc -l policy/categorias/casos/*.jsonl

## Origem

Os casos foram escritos por um agente independente que **não leu o motor**
(não abriu nem procurou código em `packages/core-ts/src/screening/`). Leu apenas o bloco KAM-088 de `specs/EPIC-09_Onboarding_Governanca.md`,
`docs/tecnica/10_Onboarding_Governanca.md` §8.1, `docs/tecnica/evidencia/E1_Meta_WhatsApp.md`
§4 e `policy/categorias/politica.yaml`, este último só para os termos exactos
do conjunto canónico. O conjunto disfarçado foi escrito a partir do que um
vendedor a fugir ao filtro escreveria, não a partir dos termos da política.

Todos os casos são **sintéticos**: nenhum vem de um anúncio real, e não há
números de telefone, endereços de correio, URL, números de identificação,
nomes de pessoas reais nem moradas. Não substituem o *dataset* de ocorrências
reais do Piloto pedido pelo critério 3.

A avaliação destes conjuntos assume o pior LLM possível (responde sempre
`permitida`), pelo que medem só as regras. Os falsos `bloqueada` no
`permitido.jsonl` medem-se e reportam-se; não bloqueiam.

## Controlo de versões

| Versão | Data | Descrição | Autor |
|---|---|---|---|
| 1.0 | Novembro 2026 | Primeira versão: conjuntos canónico, disfarçado e permitido | Equipa KAMBÁ |
