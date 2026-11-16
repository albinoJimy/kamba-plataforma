# Módulos de entrada — planos de teste, orçamento e custo por módulo

| Campo | Valor |
|---|---|
| Documento | `docs/modulos-entrada.md` |
| Ticket | KAM-124 — Planos, entitlements e metering de custo dos módulos de entrada |
| Estado | **Proposta.** Os preços de teste são `hipotese_nao_validada`; o *ledger*, as vistas, a guarda de orçamento e o `h12-export` estão medidos em `db/tests/test_modulos_custo_schema.py`, `db/tests_ten/test_modulos_de_entrada.py` e `libs/py-core/tests/test_modulos.py`. A reconciliação em *staging* com 7 dias de tráfego sintético **não foi feita** |
| Âmbito | Como se vende um módulo de entrada em teste (catálogo, foto, redes sociais, orçamentos), quanto custa servi-lo, e como se trava o custo antes de ele passar o preço. Não a assinatura real, que é do KAM-059 |
| Fontes | `specs/EPIC-11_Modulos_Entrada.md` (KAM-124); `specs/02` §3.7, §3.53 e §3.68; `docs/tecnica/09` §21.2; `docs/tecnica/evidencia/E5_Modulos_Entrada.md` (B12); ADR-018, ADR-020 |

| Aprovação | Nome | Data |
|---|---|---|
| Fundador | *(por ratificar)* | — |

## 1. Os planos de teste

O `registry/plans.yaml` tem cinco planos de entrada — `entrada_catalogo`, `entrada_foto`,
`entrada_social`, `entrada_orcamento` e `entrada_completo` — **sem atendimento**: nenhum traz
o módulo `vendedor`. Cada entitlement leva:

| Campo | O que é | Origem |
|---|---|---|
| `preco_teste_minor` | o preço de teste do módulo, em cêntimos de Kz | o limite de baixo de cada intervalo do bloco: 15 000 Kz (catálogo e foto), 60 000 Kz (redes), 100 000 Kz/mês (orçamentos). **Hipótese** |
| `imagens_mes`, `posts_mes`, `orcamentos_mes` | o contador do módulo | 40, 12 e 4: a hipótese de volume do `docs/tecnica/09` §21.2 |
| `custo_max_mes_micro_usd` | o orçamento mensal de **custo** do módulo, em micro-dólares | 30% do preço de teste ao câmbio 913, ao dólar de baixo: o limiar crítico do alerta |

Um plano com preço de teste só pode estar em `hipotese_nao_validada`, e o gate 3b recusa
outro estado. O mesmo gate recusa o preço escrito em Kz num texto que chegue ao cliente
(`CORPUS_AO_CLIENTE` em `tools/canon_lint/registo.py`): um preço que se mostra deixa de ser
hipótese e passa a ser oferta.

**Mudar um preço não precisa de deploy.** Edita-se o `registry/plans.yaml` e corre-se:

```bash
python db/h12_export.py carregar-precos
```

que substitui a `platform.module_test_prices` pelo que o ficheiro diz. Nenhuma cobrança lê
essa tabela: é o denominador da H12, não um preçário.

## 2. O custo de cada módulo

O `platform.module_cost_ledger` tem uma linha por facto de custo, só de acrescentar, escrita
pelo *job* `ops_h12_export`:

```bash
python db/h12_export.py consolidar        # de 5 em 5 minutos
```

| Rubrica | De onde vem | O que fica de fora |
|---|---|---|
| `imagem` | `platform.image_jobs` em estado final (`concluido`, `falhado`) | o trabalho ainda vivo, que pode vir a custar mais |
| `llm` | `dat.llm_call_log` cuja `vertical` é um módulo de entrada | as recusas de destino; **o orçamento expresso**, que corre dentro do Vendedor e não se separa pela `vertical` |
| `mensagem` | `platform.outbound_messages` entregues e cobráveis cujo *template* está em `config/templates_por_modulo.yaml` | todo o *template* que o mapa não conhece — **e o mapa está vazio** até os módulos criarem os seus |

Consolidar duas vezes não duplica: a chave de idempotência sai da linha de origem. O mês é o
de Africa/Luanda, o mesmo em que os contadores do TEN fecham.

As duas vistas (`platform.v_module_cost_month`, `platform.v_h12`) leem o *ledger* e convertem
ao câmbio da sessão (`app.fx_aoa_per_usd`, omissão 913). A `v_h12` preça cada mês pelo plano
**actual** do tenant: um tenant que mudou de plano vê os meses passados ao preço novo. Para a
sensibilidade de +7,4%:

```sql
SELECT set_config('app.fx_aoa_per_usd', '981', true);
SELECT * FROM platform.v_h12 WHERE mes = '2026-11-01';
```

## 3. O orçamento

**Imagem.** Antes de nascer um trabalho, a guarda (`kamba_core.foto.orcamento.QuotaComOrcamento`)
soma o custo do módulo `foto` no mês — a imagem ao vivo da `image_jobs`, o resto do *ledger* — e
compara-o com o `custo_max_mes_micro_usd` da linha `foto` do tenant. Acima, ou sem a chave, o
pedido é recusado sem consumir `imagens_mes` e sem trabalho.

**Texto.** É o orçamento do LiteLLM, que é configuração do *gateway* e não deste repositório
(KAM-030). O valor a usar é o mesmo `custo_max_mes_micro_usd`.

**O que o dono vê.** Uma mensagem **estática** (`kamba_core.modulos.mensagem_orcamento_esgotado`)
com os números do `get_usage`: a percentagem do orçamento, o uso e o limite do mês, e o dia em
que reabre. Nunca o preço de teste.

## 4. Alertas, exportação e reconciliação

```bash
python db/h12_export.py alertas                                    # JSON; código 1 com alertas
KAMBA_H12_PSEUDONIMO_CHAVE=... python db/h12_export.py exportar --mes 2026-11 --saida h12.csv
python db/h12_export.py reconciliar --mes 2026-11 --litellm spend.json --painel-imagem painel.json
```

| Alerta | Quando | Limiar (*proposta*) |
|---|---|---|
| `custo_acima_do_preco` | custo do módulo no mês acima do preço de teste | 15% aviso, 30% crítico |
| `custo_diario_anomalo` | custo do dia acima da mediana dos dias anteriores do tenant | 3 vezes, com 7 dias de história em 28 |
| `imagem_sem_custo` | trabalhos de imagem concluídos a custo zero, por fornecedor, no último dia | qualquer |
| `mensagem_sem_tarifa` | mensagens cobráveis de *template* mapeado e categoria sem tarifa | qualquer |

O CSV é o do KAM-127: o tenant sai como pseudónimo (HMAC com a chave do ambiente), sem nome e
sem `tenant_id`. A reconciliação compara o *ledger* com as suas fontes (deve dar zero) e, quando
dados, com o LiteLLM (≤ 2%), o painel do fornecedor de imagem (≤ 5%) e a factura da Meta (≤ 5%).
**Correr isto em *staging* com 7 dias de tráfego sintético é o que fecha o critério 5, e não
foi feito**: precisa da pilha de *staging* e do painel de um fornecedor contratado.

## 5. O que este documento não decide

Os preços, que são do fundador e do Responsável de Produto depois do KAM-127. O fornecedor de
imagem, que sai do *bake-off* do KAM-120. A assinatura dos módulos, que é do KAM-059: este
documento só lhe dá o consumo.

## Controlo de versões

| Versão | Data | Alteração | Autor |
|---|---|---|---|
| 1.0 | Novembro 2026 | Versão inicial (KAM-124). | Equipa KAMBÁ |
