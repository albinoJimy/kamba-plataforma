# AgentRegistry

Directório reservado pelo **KAM-001**; o conteúdo é do **EPIC-03**.

Aqui vivem os ficheiros `registry/*.yaml` do **AgentRegistry**: o registo de
verticais e dos módulos de entrada, versionado em **SemVer** (`specs/01` §5).

## O que está aqui hoje

| Ficheiro | Forma | Ticket |
|---|---|---|
| `vendedor.yaml` | **vertical** — chave de topo `id`: o tuplo do ADR-012 | KAM-027 |
| `servicos.yaml` | **vertical** — a outra metade da regra de dois | KAM-027 |
| `gates.yaml` | **gates** — chave de topo `gates`: o **modo** de cada validação de arranque, com o ticket que a fecha | KAM-027 |
| `plans.yaml` | **planos** — chave de topo `plans`: `plano` → entitlements por omissão | KAM-009 |
| `entitlement_keys.schema.json` | o registo das **dez** chaves de `entitlements.limites` e a categoria de cada uma | KAM-009 |

**Três formas, e só três.** Um `registry/*.yaml` é uma vertical (chave de topo
`id`), os gates (chave de topo `gates`) ou os planos (chave de topo `plans`). O
gate 3b distingue-as pela chave de topo e **nunca** pelo nome do ficheiro, as
chaves de topo de cada forma são listas fechadas, e um ficheiro que não seja
nenhuma das três **falha** (`tools/canon_lint/registo.py`). O `load_all` do AGR
segue a mesma regra, e **salta** os planos: quem os lê é o provisionamento.

## O `gates.yaml`, e porque é que apagar uma linha é que fecha um gate

As seis validações de arranque de `../docs/tecnica/02` §5.2 correm sempre.
`bloqueio` é a **omissão**: uma validação que o `gates.yaml` não nomeie falha
fechada. Só o `aviso` se escreve, e só ele exige `credor` — um atalho sem o
ticket que o fecha não é atalho.

Três estão em `aviso` porque a fonte delas não existe no repositório: `tools`
(KAM-028), `grafo` (KAM-031 e KAM-035) e `golden` (KAM-040). **Fechar uma é
apagar a sua linha**, nunca acrescentar outra — não há interruptor nenhum no
código, e é isso que torna este ficheiro um registo em vez de uma configuração
que se esquece ligada.

## Dois nomes em que o desenho e o canon divergem

- **`valor_max_pedido_minor`**, e não o `valor_max_pedido_kz` do exemplo de
  `../docs/tecnica/02` §5.1: a emenda 1.13 do dicionário registou aquele nome
  como *variante*, e o gate 3b trata-o como achado de nível 1 — um ficheiro
  escrito à letra do §5.1 não passa. Resolvido pelo KAM-009, que fixou as
  unidades em *minor*.
- **Os dois eventos de pagamento** nas duas verticais. O §5.1 subscreve só
  `payment.confirmed`; o dicionário §3.5 («Evento do gate da Fase 0») já
  decidiu que quem não distingue os dois caminhos subscreve os dois, e o gate 3b
  impõe-no.

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
