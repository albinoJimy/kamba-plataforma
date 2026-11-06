# Relatório mensal de SLO — modelo

| Campo | Valor |
|---|---|
| Ticket | KAM-082 (DoD 3: «relatório mensal de SLO com modelo») |
| Estado | **Modelo.** Não é um relatório: não há 30 dias de operação para relatar |
| Definição dos SLI | [`slo.md`](slo.md) |
| Periodicidade | mensal, sobre a janela de **30 dias** que fecha no último dia do mês |

> **Como se usa.** Copia-se para `ops/relatorios/slo-AAAA-MM.md`, preenche-se, e
> **cada número leva o comando que o produziu**. Um número sem comando é
> `INDÍCIO`, não `CONFIRMADO` — e um relatório de fiabilidade feito de memória é
> o artefacto que ensina a confiar no que não se mediu.

---

## 1. Período

| Campo | Valor |
|---|---|
| Janela | `<AAAA-MM-DD>` a `<AAAA-MM-DD>` (30 dias) |
| Instante da leitura | `<AAAA-MM-DD HH:MM>` UTC |
| Instrumento | consulta ao Prometheus, série por série (§2) |

## 2. O orçamento de erro

| Medida | Valor | Consulta |
|---|---|---|
| Disponibilidade a 30 dias | `<…>` % | `slo_caminho_de_venda_ratio_30d` |
| Orçamento consumido | `<…>` % de 216 min | `slo_caminho_de_venda_orcamento_consumido` |
| Orçamento restante | `<…>` min | `slo_caminho_de_venda_orcamento_restante_minutos` |
| Estado da política (§6 do `slo.md`) | `normal` / `congelado` / `só fiabilidade` | leitura da tabela do §6.1 |

**Se o restante for negativo**, escreve-se o excesso e não zero: o excesso é o
número que a política dos 100% usa.

## 3. Alertas de *burn rate* no período

| Alerta | Disparos | Tempo total em disparo | Causa raiz (por `runbook`) |
|---|---|---|---|
| `orcamento_de_erro_burn_rapido` (P2) | `<n>` | `<…>` | `<RB-K…>` |
| `orcamento_de_erro_burn_lento` (P3) | `<n>` | `<…>` | `<RB-K…>` |

Um *burn* sem causa raiz nomeada é um item em aberto, não uma linha preenchida.

## 4. Janelas de manutenção

| Janela | Início–fim (UTC) | Fora de 06:00–22:00 UTC? | Afectou mensagens? | Contou para o orçamento? |
|---|---|---|---|---|
| `<1>` | `<…>` | sim / não | sim / não | sim / não |

As três colunas do meio são as três condições do critério 6. Qualquer «não» na
primeira ou «sim» na segunda faz a última ser «sim».

## 5. Os sete SLI que não se mediram

Não é uma secção de desculpas: é a lista de o que **continua** sem instrumento, e
ela deve **encurtar** de mês para mês. A tabela do §2.2 de [`slo.md`](slo.md) é a
fonte; aqui registam-se só as mudanças.

| SLI | Estado no mês anterior | Estado agora | Credor |
|---|---|---|---|
| `<…>` | `<…>` | `<…>` | `<KAM-NNN / papel>` |

## 6. Alvos auxiliares do doc 09 §17

| Alvo | Valor | Medido? |
|---|---|---|
| Tempo para fechar um alerta P1 | ≤ **2 h** | `<…>` |
| Alertas sem *runbook* | **0** | `make obs-lint` → regras `alerta_sem_runbook` e `runbook_inexistente` |
| Memória em hora de ponta | ≤ **65%** | **não medido** — não há *exporter* de contentores em nenhum compose |

## 7. Decisões que este relatório pede

| Decisão | Quem decide | Prazo |
|---|---|---|
| `<…>` | `<…>` | `<…>` |

Os limiares de *burn rate* (2% em 1 h, 5% em 6 h) são **proposta**, a calibrar
nos primeiros 30 dias: o primeiro relatório com tráfego real é o sítio onde essa
calibração se propõe.

---

## 8. Controlo de versões

| Versão | Data | Alteração | Autor |
|---|---|---|---|
| 1.0 | Novembro 2026 | Modelo criado pelo **KAM-082**, DoD 3. Oito secções, cada número com a consulta que o produz, e a lista dos sete SLI sem instrumento como secção que deve encurtar. | Equipa KAMBÁ |
