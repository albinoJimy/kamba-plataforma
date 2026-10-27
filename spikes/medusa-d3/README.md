# `spikes/medusa-d3` — repositorio de testes do KAM-041

Instrumento de medicao do spike **KAM-041 — Spike Medusa v2: isolamento entre
vendedores e reservas com TTL**. O relatorio, com o resultado de cada criterio e
a recomendacao sobre a decisao aberta **D3**, esta em
[`docs/spikes/KAM-041-medusa.md`](../../docs/spikes/KAM-041-medusa.md).

**Isto nao e codigo de producao e nao e um gate.** A porta `CommerceRegistry`
definitiva e o adaptador sao o **KAM-042**; o que esta aqui e o minimo que torna
os dez criterios do §4.3 de
[`docs/tecnica/03_Core_Comercio_Medusa.md`](../../docs/tecnica/03_Core_Comercio_Medusa.md)
mensuraveis. Se a D3 fechar na opcao B, a suite ISO entra na *pipeline* pela mao
do KAM-042, e e la que ganha um alvo `make ci-<n>`.

## Como se corre

Precisa de **Docker** e do ambiente Python do repositorio (`make bootstrap`, ou
o `.venv` ja existente). Nao precisa de `node` nem de `pnpm` no anfitriao —
nesta maquina nao existem, e o spike corre o Medusa num contentor Node fixado
por digest.

```bash
# tudo: PostgreSQL + Medusa + os dez criterios
python spikes/medusa-d3/harness.py

# so o que nao depende do Medusa (os restantes ficam NAO VERIFICADO)
python spikes/medusa-d3/harness.py --sem-medusa

# AC-7 isolado: sem Docker, sem rede, sem base de dados
python spikes/medusa-d3/ee.py
```

Codigos de saida, e a distincao que da sentido ao spike:

| Codigo | Significado |
|---|---|
| `0` | todos os criterios bloqueantes **medidos** e verdes |
| `1` | algum criterio bloqueante medido e **vermelho** |
| `2` | **nao se conseguiu medir** (Docker fora de alcance, Medusa nao arrancou, npm sem rede) |

O `2` e o codigo que o `db/gate_bd.py` ja usa para «nao se conseguiu
verificar», e aqui vale a mesma regra: **nao verificado nunca e verde**. Um
spike que confundisse «zero sobrevendas» com «o teste nao chegou a correr» dava
uma licenca de arquitectura assinada por um teste que nunca concorreu.

A primeira execucao completa instala a arvore do Medusa (`npm ci`, ~1.100
pacotes) para o volume nomeado `kamba-spike041-node-modules`, que sobrevive
entre execucoes. **Nesta maquina a resolucao do fecho levou 28 minutos**; a
instalacao a partir do fecho e mais rapida, e o numero medido esta no relatorio.

## O que ha aqui

| Ficheiro | O que faz |
|---|---|
| `harness.py` | orquestra: levanta a base, prepara o schema, arranca o Medusa, chama o `medir` |
| `contentor.py` | **o unico** ficheiro que fala com o Docker (ver abaixo) |
| `medir.py` | corre os dez criterios e escreve `resultados/resultados.json` |
| `criterios.py` | AC-1 a AC-10, um por funcao; cada uma devolve numeros |
| `iso.py` | a matriz ISO-01..60 do §4.4 |
| `registo.py` | a `CommerceRegistry` minima, na forma da opcao B |
| `sementes.py` | tres tenants ficticios, com o SKU que colide entre eles |
| `concorrencia.py` | ISO-51..56 e as tempestades do AC-3 e do AC-4 |
| `media.py` + `media_iso.mjs` | ISO-47..50, contra a porta de armazenamento do KAM-011 |
| `medusa.py` | cliente da Store/Admin API e do *query graph*; ISO-11..32 |
| `ee.py` | AC-7, isolado e sem dependencias: serve de gate |
| `ddl/` | as tabelas do ciclo de vida da encomenda, a RLS e o grafo de estados |
| `medusa/` | o projecto Medusa v2 minimo (versao fixada, modulo `merchant`, link) |
| `resultados/` | o que cada execucao mediu. **Nao e versionado** |

### Porque e que so o `contentor.py` chama o Docker

O gate 11 (`tools/supply_chain/imagens.py`, `_lancadores`) exige que todo o
ficheiro Python que lance um contentor esteja declarado em `fontes_adicionais` de
`ci/supply-chain/imagens.yaml`. Concentrar as chamadas num ficheiro faz do spike
**uma** entrada nesse inventario em vez de cinco.

E **nao traz digests novos**. As duas imagens vem das constantes que o
inventario ja verifica:

| Imagem | Constante | Ficheiro |
|---|---|---|
| PostgreSQL 18.6 + pgvector | `IMAGEM` | `db/gate_bd.py` |
| Node 24.21.0 | `IMAGEM_NODE` | `db/tests_identidade/node.py` |

Nao entra Redis/Valkey: o Medusa tem provider in-memory por omissao para cache,
event bus, locking e workflow engine, e o bus canonico da KAMBA e o EVT
(ADR-009), nao o do Medusa. **Mas o provider de locking in-memory e exactamente
o que decide o AC-3** — ver o §4 do relatorio.

## O que o `ddl/` e, e o que nao e

**Nao e uma migracao.** As tabelas canonicas que o ciclo de vida da encomenda
precisa — `orders_mirror`, `order_intents`, `order_state_log`,
`stock_reservations`, `offer_terms`, `events_outbox` — **ainda nao existem** em
`db/migrations/versions/`: a revisao mais recente e a `0003` (identidade de
contacto), e as tabelas de encomenda sao do **KAM-044** e do **KAM-045**.

O harness aplica as revisoes `0001`-`0003` pelo **Alembic de verdade** e poe o
DDL do spike por cima, na base descartavel. Quem escrever o KAM-044 parte do
§5.4 do `docs/tecnica/03` e nao daqui: isto e o instrumento de medicao, nao o
desenho. Cada desvio face ao §5.4 esta comentado no proprio SQL.

Duas notas de nome:

- a politica RLS chama-se **`tenant_iso`** (o nome de `db/rls.py` e do
  dicionario §3.2, emenda 1.5), e nao `tenant_isolamento` como o
  `docs/tecnica/03` §5.5 lhe chama;
- `platform.spike_stock_levels` tem o prefixo `spike_` de proposito: e o
  **comparador** do AC-3 (o `UPDATE ... WHERE quantidade - reservada >= :q` do
  §6.4) contra o Inventory Module do Medusa, e nao um nome candidato a entrar no
  dicionario.

## Dados

Dados **sinteticos**, tres tenants ficticios, nenhum dado real — como o bloco do
ticket exige. Os contactos nao tem telefone (`phone_hmac` fica nulo): o ADR-010
diz que o telefone nao e chave, e o spike nao precisa de nenhum.
