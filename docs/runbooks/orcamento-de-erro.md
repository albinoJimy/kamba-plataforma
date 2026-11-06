# Runbook — orçamento de erro a arder

**Esboço** (KAM-082, DoD 3: «cada alerta de SLO tem *runbook*»). **Não é
procedimento ratificado e não se executa a partir daqui.** O *runbook* completo —
passos executáveis por quem não esteve na conversa, ensaiados por outra pessoa
que não o autor — é o **KAM-083**.

**Não leva número RB-K**, e isso é deliberado: a série `RB-K01`–`RB-K10` é a lista
fechada do [`docs/tecnica/09`](../tecnica/09_Topologia_Operacao_Escala.md) §13, e
inventar um `RB-K11` aqui seria acrescentar uma linha a um canon que este ticket
não governa. Segue a forma do
[`degradacao-do-agr.md`](degradacao-do-agr.md), que é a que esta casa usa para
um *runbook* que nasce com o alerta e não com a lista.

| Campo | Valor |
|---|---|
| Cenário | O orçamento de erro de 30 dias está a ser consumido depressa |
| Severidade | **P2** (rápido) e **P3** (lento) |
| Alertas que apontam para aqui | `orcamento_de_erro_burn_rapido` (P2) e `orcamento_de_erro_burn_lento` (P3), em [`../../infra/compose/prometheus/regras/kamba-slo.yml`](../../infra/compose/prometheus/regras/kamba-slo.yml) |
| Linha canónica | [`docs/tecnica/09`](../tecnica/09_Topologia_Operacao_Escala.md) §10 (SLO e orçamento) e §17 (alvos mensuráveis) |
| Definição dos SLI | [`../../ops/slo.md`](../../ops/slo.md) |
| Estado | **Esboço.** Gatilho, severidade e leitura dos números fixados; procedimento por escrever (KAM-083) |

---

## 1. Gatilho

| Alerta | Condição | Severidade |
|---|---|---|
| `orcamento_de_erro_burn_rapido` | mais de **2%** do orçamento de 30 dias gasto na última **1 h** — ou seja mais de **4,32 min** de indisponibilidade numa hora | **P2** |
| `orcamento_de_erro_burn_lento` | mais de **5%** do orçamento gasto nas últimas **6 h** — mais de **10,8 min** em seis horas | **P3** |

Os dois limiares são **proposta** do próprio ticket, a calibrar nos primeiros 30
dias de operação real. Não são medições: são números escolhidos antes de haver
tráfego.

## 2. O primeiro número a ler, e não é o do alerta

```promql
slo_caminho_de_venda_orcamento_restante_minutos
```

Minutos que sobram dos **216** (0,5% de 30 dias, o orçamento de 99,5%). Fica
**negativo** quando o orçamento estoura, e o valor negativo é o excesso — é esse
que a política dos 100% usa.

Os dois alertas medem **velocidade**; este mede **quanto resta**. Um *burn*
rápido com 190 min no banco é um incidente a atender; o mesmo *burn* com 12 min
no banco é uma decisão de congelamento. São duas leituras diferentes do mesmo
alerta, e o painel
[`../../ops/paineis/orcamento-de-erro.json`](../../ops/paineis/orcamento-de-erro.json)
mostra as duas lado a lado de propósito.

## 3. Os três limites de que quem atende precisa de saber

São limites do **instrumento**, não do procedimento, e por isso ficam aqui e não
no KAM-083.

1. **O SLI não vê o que o cliente vê.** Mede se o Prometheus consegue raspar o
   GWY e o AGR de dentro da pilha. Internet, DNS, TLS e a Meta ficam fora. A
   sonda externa que fecharia isto é o critério 5 do KAM-080, que ficou **vazio**
   por não haver produção nem *host* externo (credores **D1/KAM-105** e
   **KAM-069**).
2. **Uma paragem do próprio Prometheus não aparece.** Sem avaliação não há
   amostra, e a média de 30 dias ignora o intervalo em falta: a pior avaria
   possível é a única que este SLI **subconta**. Se o alerta chegar depois de uma
   paragem do anfitrião, o orçamento mostrado está melhor do que a realidade.
3. **O `worker-canal` não está no numerador**, embora seja o «processar» do
   caminho receber → processar → responder. O `CMD` do `Dockerfile` dele corre o
   `server.ts`, que devolve **404** em `/metrics`, e o `prometheus.yml` não tem
   alvo para as quatro entradas que servem métricas. Uma falha só do *worker*
   não desce este SLI.

## 4. O que este *stub* não é

Não é o procedimento. Quem cair aqui durante um incidente tem de ir à causa — e a
causa de um *burn* é sempre outro alerta: `ingress_parado` (RB-K01),
`alvo_em_baixo` (RB-K01), as filas ou a latência (RB-K03). Este *runbook* explica
o orçamento; não substitui o diagnóstico de `docs/tecnica/09` §13.
