# Experimento dos módulos de entrada — como se mede, como se decide, como se abate

| Campo | Valor |
|---|---|
| Documento | `docs/experimento-modulos.md` |
| Ticket | KAM-127 — Experimento dos módulos de entrada: hipóteses H10–H12, regra de escopo e critérios de abate |
| Estado | **Proposta.** Os limiares e a regra de escopo esperam a ratificação do fundador. A instrumentação está medida em `db/tests/test_experimento_modulos_schema.py`, `libs/py-core/tests/test_experimento_modulos.py`, `services/agr/tests/test_modulos_desligados.py` e `tools/canon_lint/tests/test_superficies_de_ficheiro.py`. **Nenhuma PME foi medida** |
| Âmbito | A operação do experimento: a coorte, a leitura, a reprodução, a decisão e o efeito de um abate. **Não** as hipóteses nem os limiares, que estão pré-registados em `docs/tecnica/evidencia/validacao/H10_H12_Modulos_Entrada.md` |
| Fontes | `specs/EPIC-11_Modulos_Entrada.md` (KAM-127); `docs/exploracao/14-tese-minima-e-plano-de-validacao.md` §2; ADR-020; `docs/modulos-entrada.md` (KAM-124) |

| Aprovação | Nome | Data |
|---|---|---|
| Fundador | *(por ratificar)* | — |

## 1. As peças

| Peça | O que faz |
|---|---|
| `registry/modulos_entrada.yaml` | os quatro módulos e o interruptor `activo` de cada um; o gate 3b recusa um quinto activo sem emenda ao ADR-020 e o `catalogo` desligado |
| `config/experimento_modulos.yaml` | os limiares e as janelas, todos *proposta*, lidos por `kamba_core.modulos.experimento` a falhar fechado |
| `platform.v_h10`, `platform.v_h11` | a H10 e a H11 por tenant, com `now()` e as janelas de 14 e 30 dias |
| `platform.v_h12` (KAM-124), `platform.v_h12_pagantes` | o custo e o racio da H12, e as PMEs que pagam por um módulo isolado |
| `platform.module_experiment_exclusions` | os tenants da equipa e de teste, fora da coorte |
| `platform.module_decisions` | as decisões manter/ajustar/abater, só de acrescentar |
| `db/experimento_modulos.py` | o instrumento: `ler`, `reproduzir`, `decidir`, `excluir` (*job* `ops_experimento_modulos`, papel `kamba_batch`) |

As vistas não levam `contact_id`, telefone, nome nem conteúdo: `tenant_id`,
módulos, instantes e booleanos.

## 2. Antes da primeira leitura: a coorte

Os tenants da equipa e os de teste saem da coorte **antes** de se medir:

```bash
python db/experimento_modulos.py excluir --tenant <uuid> --motivo equipa --por <identidade-de-staff>
```

A exclusão é só de acrescentar. Uma feita depois de uma leitura muda o N dessa
leitura em diante, e fica com o nome e o instante.

## 3. A leitura das semanas 8, 10 e 12

```bash
python db/experimento_modulos.py ler                       # JSON: n/N, Wilson 95%, censurados
python db/experimento_modulos.py reproduzir --amostra 5    # código 1 com qualquer diferença
```

O `ler` devolve, para cada hipótese, `n`, `total`, a proporção, o intervalo de
Wilson a 95% e se a proporção chega ao limiar; os censurados contam-se à parte.
O `reproduzir` recalcula a H10 e a H11 **em Python**, a partir das linhas cruas,
para os primeiros cinco tenants da coorte, e compara campo a campo com as funções
da base: é a «diferença 0 numa amostra de 5» do critério 3. Os números vão para
o §6 do pré-registo.

## 4. A decisão

Os incidentes de conteúdo contam-se à mão, a partir do golden e da auditoria do
KAM-125, num ficheiro com as quatro contagens:

```json
{"catalogo": {"alta": 0, "media": 1}, "foto": {"alta": 0, "media": 0},
 "social": {"alta": 0, "media": 2}, "orcamento": {"alta": 0, "media": 0}}
```

```bash
python db/experimento_modulos.py decidir --incidentes incidentes.json            # só propõe, os quatro
python db/experimento_modulos.py decidir --incidentes incidentes.json --registar \
    --modulo social --decisao ajustar \
    --responsavel <identidade-de-staff> --justificacao "<porquê>" --revisao-em 2027-02-15
```

Sem `--registar`, a regra só propõe, para os quatro. Com ele, escreve **uma** linha
— a do `--modulo` — em `platform.module_decisions`, com a decisão de quem decide
(`--decisao`, por omissão a proposta) e a proposta ao lado nas `metricas`. Recusa:
sem `--modulo`, sem responsável ou sem justificação; um módulo sem coorte e sem
`--decisao` explícita (o relatório regista «dados insuficientes»); e um «ajustar»
sem data de revisão. A base recusa «abater» o `catalogo`. O `responsavel` é a
identidade de *staff* de quem decide (a do IdP), e nunca um cliente.

**O `foto` regista-se como dados insuficientes enquanto não tiver caminho em
produção** (pré-registo §8): hoje nenhum processo escreve uma versão escolhida, e
a regra proporia abatê-lo por isso.

## 5. O efeito de um abate

Um abate é configuração, num só PR, e cabe em menos de um dia de trabalho:

1. **`registry/modulos_entrada.yaml`** — `activo: false` no módulo. No arranque
   seguinte o AGR recusa as tools desse módulo a **todos** os tenants, no passo 2
   da ToolLayer, com `ENTITLEMENT_DENIED`, antes de ler o entitlement; o grafo do
   dono responde com a frase estática que já tinha para «módulo não activo». As
   portas fora da ToolLayer obedecem também: o `foto` não tem tool, e o interruptor
   desliga a oferta de «melhorar foto» do catálogo; no `orcamento`, a
   `PortaDeOrcamento` deixa de oferecer o botão «Pedir orçamento» ao cliente, não
   envia uma proposta respondida antes do abate e não liberta as que esperavam pela
   janela. Os outros módulos não mudam; no atendimento, só desaparece o pedido de
   orçamento, que é do próprio módulo.
2. **`registry/plans.yaml`** — o módulo sai dos planos `entrada_*`, para que os
   planos novos não o tragam; `python db/h12_export.py carregar-precos` actualiza
   os preços de teste.
3. **Reiniciar o AGR** com o registo novo.

**O ensaio em *staging*, com os quatro módulos, não está feito**: precisa da
pilha de *staging* e é do Piloto (credor KAM-109). Os ensaios de unidade provam
o efeito de cada interruptor sem a pilha.

## 6. O que este documento não decide

Os limiares, a regra de escopo e a leitura de «paga por um módulo isolado» pelo
ciclo da assinatura (e não pelo `payment.*`), que são do fundador. Os preços de
teste, que são do KAM-124 e hipóteses. A decisão de cada módulo, que é de quem a
regista.

## Controlo de versões

| Versão | Data | Alteração | Autor |
|---|---|---|---|
| 1.0 | Novembro 2026 | Versão inicial (KAM-127). | Equipa KAMBÁ |
