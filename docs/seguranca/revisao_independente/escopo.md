# Revisão de segurança independente — âmbito e pacote do revisor

| Campo | Valor |
|---|---|
| Ticket | KAM-074 |
| Relatório | [`relatorio.md`](relatorio.md) |
| Re-teste | [`reteste.md`](reteste.md) |
| Decisão | [`decisao.md`](decisao.md) |
| Medido sobre | `publico/main` em `ee545cc9`, a 2026-11-25 |
| **Estado** | **Preparado sem o mundo real** (lote 24). Não há revisor, não há `staging` alojado, e nada aqui foi acordado com um revisor. Quem conduzir a revisão revê este âmbito com ele e regista a versão acordada. |

Este é o pacote que o revisor recebe: o que se revê (§2), o que entra (§3), que acesso tem e como
se fecha (§4), o que fica de fora (§5) e o que tem de existir no mundo real antes de começar
(§6).

## 1. Regras que não se negociam

Vêm do bloco e do *handoff* do KAM-074 em
[`../../../specs/EPIC-07_Seguranca_Conformidade.md`](../../../specs/EPIC-07_Seguranca_Conformidade.md).

- **Independência:** o revisor não é autor do código do âmbito. Uma revisão cruzada por um
  engenheiro não-autor só substitui com risco aceite por escrito pelo Responsável de Produto e
  pelo Responsável de Segurança ([`decisao.md`](decisao.md) §3).
- **Nunca `prod`, nunca segredos de `prod`.** A revisão corre em `staging`, com dados sintéticos
  e canários.
- **Acesso mínimo, com prazo e com registo**, revogado no fim e registado ([`decisao.md`](decisao.md) §5).
- **Não se corrigem achados dentro do KAM-074:** cada um vira `fix` com DoR e DoD próprios, pelo
  procedimento de [`relatorio.md`](relatorio.md) §7.
- **Sem custos nem prazos de revisor inventados.** Esta preparação não escolhe fornecedor, não
  estima custo e não fixa data.

## 2. As áreas do âmbito

O primeiro critério do bloco enumera o mínimo; cada linha abaixo é uma dessas áreas, com a
evidência automatizada que já existe para o revisor partir dela, e o que o bloco do ticket dono
**já declara publicamente** como não medido. Esta coluna não acrescenta lacunas: cita-as. Uma
lacuna que ainda não esteja escrita num bloco público não entra aqui (ver §7).

A coluna «Gate» usa a numeração do [`../../ci.md`](../../ci.md).

| # | Área | Evidência automatizada que já existe | Gate | Ticket | Declarado como não medido, no bloco dono |
|---|---|---|---|---|---|
| 1 | Isolamento entre *tenants* e entre contactos (suite do KAM-066 e testes manuais), incluindo URLs assinadas de storage | [`../../../tools/isolamento/README.md`](../../../tools/isolamento/README.md) (o *harness* e os casos registados); [`../../../db/tests_isolamento/test_x03_x04_isolamento.py`](../../../db/tests_isolamento/test_x03_x04_isolamento.py); storage em [`../../../packages/core-ts/tests/storage.isolamento.test.ts`](../../../packages/core-ts/tests/storage.isolamento.test.ts) e [`../../../packages/core-ts/tests_bd/media.bd.test.ts`](../../../packages/core-ts/tests_bd/media.bd.test.ts) | 6, 4, 8 | KAM-066, KAM-011, KAM-020 | o bloco do KAM-066 tem critérios parciais (mutação do eixo de contacto, *traces*); os X-08, X-09 e X-10 não estão registados no *harness* (o README dele diz quais) |
| 2 | `tenant_id` do estado, RLS `FORCE` e `SECURITY DEFINER` | [`../../../db/tests_isolamento/test_x05_catalogo.py`](../../../db/tests_isolamento/test_x05_catalogo.py) (catálogo RLS e a lista de `SECURITY DEFINER`, contra [`../../../ci/secdef_allowlist.yaml`](../../../ci/secdef_allowlist.yaml)); [`../../../ci/rls_exceptions.yaml`](../../../ci/rls_exceptions.yaml); o `tenant_id` proibido nos argumentos das tools em [`../../../tools/lint_arch/tool_schema.py`](../../../tools/lint_arch/tool_schema.py) | 6, 2 | KAM-004, KAM-028, KAM-066 | — |
| 3 | *Callbacks* de pagamento forjados: HMAC, *replay*, valor e referência | [`../../../packages/core-ts/tests/pagamentos.proxypay.rps.test.ts`](../../../packages/core-ts/tests/pagamentos.proxypay.rps.test.ts); o *ledger* em [`../../../db/tests_pagamentos/`](../../../db/tests_pagamentos/) | 4, 8 | KAM-053, KAM-056, KAM-060 | tudo contra um servidor do facilitador falso; a *sandbox* é de outro ticket, e o bloco do KAM-056 di-lo |
| 4 | *Webhook* da Meta: assinatura sobre o corpo bruto e SSRF no download de media | [`../../../services/gwy/tests/webhook.test.ts`](../../../services/gwy/tests/webhook.test.ts); a lista fechada de anfitriões em [`../../../packages/core-ts/src/med/graph.ts`](../../../packages/core-ts/src/med/graph.ts), com [`../../../packages/core-ts/tests/med.graph.test.ts`](../../../packages/core-ts/tests/med.graph.test.ts) | 4, 7, 8 | KAM-013, KAM-020, KAM-024, KAM-231 | o anfitrião da media é NÃO VERIFICADO no registo de decisões do bloco do KAM-231 (e no próprio código) |
| 5 | Confirmação manual abusada, e comprovativo como prova | [`../../../db/tests_pagamentos/test_confirmacao_manual.py`](../../../db/tests_pagamentos/test_confirmacao_manual.py); [`../../../packages/core-ts/tests/pagamentos.manual.test.ts`](../../../packages/core-ts/tests/pagamentos.manual.test.ts) | 8, 4 | KAM-054, KAM-020 | no bloco do KAM-054, os limites M-3 nomeados mas não quantificados, e o segundo revisor por nomear |
| 6 | Segredos e rotação; segredos no ambiente dos contentores | [`../../../packages/core-ts/tests/keyring.test.ts`](../../../packages/core-ts/tests/keyring.test.ts); [`../../../db/tests/test_rotacao_de_chaves.py`](../../../db/tests/test_rotacao_de_chaves.py); o varrimento do gate 9 ([`../../../tools/scan_secrets/`](../../../tools/scan_secrets/)); a forma de injecção em [`../../adr/ADR-L002-injeccao-de-segredos.md`](../../adr/ADR-L002-injeccao-de-segredos.md) | 4, 8, 9 | KAM-010, KAM-072, KAM-205, KAM-260 | o bloco do KAM-072 dá os runbooks de rotação como não ensaiados em `staging` |
| 7 | Imagens e cadeia de abastecimento | [`../../../tools/supply_chain/`](../../../tools/supply_chain/) com [`../../../ci/supply-chain/imagens.yaml`](../../../ci/supply-chain/imagens.yaml) e [`../../../ci/supply-chain/licencas.yaml`](../../../ci/supply-chain/licencas.yaml); o SBOM do gate 11 (§3) | 11 | KAM-002, KAM-030, KAM-067 | o bloco do KAM-067: o `cosign` não correu nesse ticket (a verificação da imagem do LiteLLM é do KAM-030), e não há SBOM por imagem nem por *release* |
| 8 | Chatwoot: *bot* global com `account_id` nulo, Platform API | [`../../../packages/core-ts/tests_bd/handoff.bd.test.ts`](../../../packages/core-ts/tests_bd/handoff.bd.test.ts); o *compose* com a *flag* de licença verificada por `compose_prod` | 4, 8, 2 | KAM-019, KAM-076 | o bloco do KAM-019 deixa o X-10 fora do *harness* |
| 9 | Medusa: admin exposto, *flags* EE | [`../../../tools/lint_arch/medusa.py`](../../../tools/lint_arch/medusa.py) (as *flags* EE) | 2, 11 | KAM-041, KAM-042 | o Medusa **não está no *compose***: [`../../../infra/compose/conjunto-reduzido.yaml`](../../../infra/compose/conjunto-reduzido.yaml) dá-o como `pendente`. Sem serviço não há admin a rever; a área fica `não testado` até ele existir |
| 10 | *Egress* | as declarações em [`../../../infra/egress/`](../../../infra/egress/), o lint em [`../../../tools/supply_chain/egress.py`](../../../tools/supply_chain/egress.py) e o ensaio contra o *proxy* de saída (`compose_prod egress-dez`) | 11, 6 | KAM-067, KAM-076 | o bloco do KAM-076: a *allowlist* do *proxy* não é por serviço |
| 11 | Backups | [`../../../infra/backup/cobertura.yaml`](../../../infra/backup/cobertura.yaml) e [`../../../tools/backup_lint/`](../../../tools/backup_lint/); o simulacro em [`../../evidencia/KAM-085.md`](../../evidencia/KAM-085.md) | 4 | KAM-079, KAM-085, KAM-070 | o bloco do KAM-079 não tem critérios satisfeitos; o do KAM-085 dá as verificações pós-restauro como parciais, com a reaplicação do *erasure ledger* entre as não medidas |
| 12 | Logs | `make x11` com [`../../../tools/log_policy/`](../../../tools/log_policy/); `make log-lint` | 6, 2 | KAM-068 | o bloco do KAM-068 devolve dois critérios ao Responsável de Segurança e não tem a amostragem semanal em `prod` |
| 13 | Injecção e exfiltração pelo AGR (entrada, não área do primeiro critério) | o relatório do red-team, [`../redteam/relatorio.md`](../redteam/relatorio.md), e a bateria [`../../../services/agr/tests/test_redteam.py`](../../../services/agr/tests/test_redteam.py) | 4 | KAM-073, KAM-189 | o próprio relatório, §5: sem `staging`, sem a parte manual, sem assinatura |
| 14 | Rede de entrada: o que está exposto no exterior, acesso administrativo por VPN, borda, TLS e WAF (o objectivo do bloco diz «rede»; o primeiro critério só nomeia o *egress*) | a do bloco do KAM-076 (critério 5: só 443 e a porta do WireGuard no exterior, admin do Medusa e Grafana só por VPN) | 2 | KAM-076, KAM-077 | o critério 5 do KAM-076 está parcial; o *scan* externo, a borda, o TLS e o WAF são do KAM-077, aberto |

**Os seis testes de exploração** que o bloco exige no mínimo, e um sétimo de privacidade que a
DoD pede, estão em [`relatorio.md`](relatorio.md) §4, cada um ligado a uma área desta tabela.

## 3. O que o revisor recebe

| Entrada | Onde está | Como chega ao revisor |
|---|---|---|
| Código, testes, *gates* e desenho | este repositório, que é público | sem acesso nenhum |
| Matriz de conformidade do KAM-065 | **fora deste repositório** — [`../matriz_conformidade.csv`](../matriz_conformidade.csv) é o esboço que o diz | entregue pelo fundador, fora do repositório público |
| Modelo de ameaças STRIDE e registo de riscos residuais do KAM-065 | **fora deste repositório** ([`../ameacas_stride.md`](../ameacas_stride.md) e [`../riscos_residuais.md`](../riscos_residuais.md) são esboços) | idem |
| Suite de isolamento do KAM-066 | §2, área 1 | no repositório |
| Relatório do red-team do KAM-073 | [`../redteam/relatorio.md`](../redteam/relatorio.md); a explicação dos achados abertos vive fora do repositório | a parte pública no repositório; a outra pelo fundador |
| SBOM | gerado pelo gate 11 e guardado como artefacto do CI (`ci/sbom/`, fora do `git`); gera-se também com `python -m sbom generate --root ..`, de dentro de `tools/` (o destino por omissão é `ci/sbom/` na raiz; um `--out` relativo resolve-se contra a raiz, e não contra o directório corrente) | o artefacto do CI do *commit* em revisão, identificado pelo SHA |
| Inventário de imagens e licenças do KAM-067 | [`../../../ci/supply-chain/imagens.yaml`](../../../ci/supply-chain/imagens.yaml), [`../../../ci/supply-chain/licencas.yaml`](../../../ci/supply-chain/licencas.yaml) | no repositório |
| Inventário de subprocessadores do KAM-069 | [`../../../gov/subprocessadores.yaml`](../../../gov/subprocessadores.yaml) | no repositório |
| O *commit* e os *digests* em revisão | o SHA da `main` e o *digest* de cada imagem em `staging` | registados no cabeçalho do [`relatorio.md`](relatorio.md) |

## 4. Acesso mínimo a `staging`

Descrito por papel e por prazo, **sem credenciais**: nenhuma credencial, *token*, endereço de
máquina ou nome de conta entra neste repositório. Os papéis são *proposta* desta preparação; o
Responsável de Segurança fixa os que o revisor recebe.

| # | Acesso | Para que área | Notas |
|---|---|---|---|
| A1 | A superfície externa de `staging` (o *webhook* e as rotas públicas), como qualquer cliente da internet | 1, 3, 4 | sem conta |
| A2 | Uma identidade autenticada num *tenant* sintético A, com um *tenant* sintético B ao lado, os dois semeados com canários pela semente do *harness* ([`../../../tools/isolamento/semente.py`](../../../tools/isolamento/semente.py)) | 1, 5, E1, E5 | nunca um *tenant* com dados reais |
| A3 | Uma sessão na base com o papel da aplicação e o contexto de A, sem superutilizador | 2, E2 | só se o Responsável de Segurança a aprovar |
| A4 | Um corpo de *callback* válido do *sandbox* do facilitador, entregue **sem** a chave | 3, E3 | o ensaio é forjar ou repetir sem a chave; a chave nunca se entrega |
| A5 | Uma *shell* num contentor sem privilégios, a simular o compromisso de um serviço | 6, E6 | só se o Responsável de Segurança a aprovar; os segredos de `staging` rodam-se no fim (*proposta*, [`decisao.md`](decisao.md) §5) |

**Prazo e registo.** O acesso abre numa data e fecha noutra, as duas escritas em
[`relatorio.md`](relatorio.md) §2. O acesso do revisor a um *host* de `staging` entra pela conta
`breakglass` do *host*, como qualquer acesso de excepção em `staging` e em `prod`
([`../../../infra/ENVIRONMENTS.md`](../../../infra/ENVIRONMENTS.md) §2.0, KAM-259): cada sessão
pede um prazo de no máximo sete dias e uma razão, escreve `breakglass.open` no `audit_log` antes
de a *shell* abrir e `breakglass.close` quando ela fecha, e responde com o identificador da
sessão, que fica no [`relatorio.md`](relatorio.md) §2 com as datas. As duas linhas do revisor
mostram-se com a impressão digital da chave dele:

```
python db/auditoria.py breakglass --actor 'SHA256:<impressão da chave do revisor>'
```

O comando lê com o `kamba_batch`, que é quem vê as linhas sem tenant; o `acesso.modo` de
`staging` continua `equipa`, que é o acesso da equipa.

**Dados em `staging`.** Só sintéticos (`dados.classe: synthetic`). A matriz de ambientes prevê
números reais em `staging` durante o *spike* de coexistência, e regista a tensão sem a resolver
([`../../../infra/ENVIRONMENTS.md`](../../../infra/ENVIRONMENTS.md) §5.1). *Proposta:* a revisão
não corre enquanto houver um número real em `staging`.

## 5. Fora do âmbito, e o que este ticket não substitui

- **Decisões abertas que dependem de terceiros**, explícitas como fora do âmbito, como o bloco
  pede: D3 (Mercur e isolamento nativo do Medusa), D1 (alojamento e transferência), D9 (papel
  da KAMBÁ perante a APD).
- **O gate de go-live de transferência** (KAM-069 e KAM-105) e **o parecer jurídico** (KAM-104):
  o KAM-074 não os substitui, e nenhuma decisão de [`decisao.md`](decisao.md) os dispensa.
- **O pentest recorrente, o SOC e o WORM**: Clusters
  ([`../../tecnica/08_Seguranca_Conformidade.md`](../../tecnica/08_Seguranca_Conformidade.md) §16).
  Esta revisão é pontual, pré-Piloto.

## 6. O que tem de existir antes de a revisão começar

Tudo isto é mundo real, e nada está feito.

| Pré-condição | Estado | Onde se acompanha |
|---|---|---|
| `staging` alojado e a correr as imagens de `prod` | não existe: há a definição em [`../../../infra/compose/docker-compose.staging.yml`](../../../infra/compose/docker-compose.staging.yml), não há máquina | KAM-077 |
| Revisor independente, ou o risco aceite da substituição | não existe | [`relatorio.md`](relatorio.md) §2 e [`decisao.md`](decisao.md) §3 |
| Registo no `audit_log` do acesso do revisor a `staging` | o caminho existe e está ensaiado contra PostgreSQL (§4); falta o *host*, e a chave do revisor na lista `chaves_ssh_de_breakglass` de `staging` | KAM-259, KAM-077 |
| Matriz, STRIDE e riscos residuais entregues ao revisor fora do repositório público | não feito | o fundador |
| Medusa no *compose* (área 9) | pendente | KAM-042 |

## 7. Estado das afirmações deste documento

- **CONFIRMADO, medido nesta árvore a 2026-11-25:** que os ficheiros citados existem (o
  [`../validar.py`](../validar.py) confere cada caminho desta pasta); que a lista de
  `SECURITY DEFINER` tem 18 entradas; que o anfitrião da media está marcado NÃO VERIFICADO no
  código; que o `env.yaml` de `staging` tem `acesso.modo: equipa`; que o Medusa está `pendente`
  no conjunto reduzido; que o SBOM é artefacto do CI com retenção de 90 dias.
- **INDÍCIO:** a coluna «Declarado como não medido» resume blocos de outros tickets, lidos por
  um subagente e conferidos por amostragem; o bloco de cada ticket é a fonte.
- **NÃO VERIFICADO:** tudo o que só se mede em `staging` — o que os seis testes de exploração
  do bloco e o de privacidade ([`relatorio.md`](relatorio.md) §4) vão medir.
- **Uma pergunta para a coordenação, e não uma decisão:** este documento junta numa só tabela o
  que vários blocos públicos já dizem não estar medido. Cada linha já é pública; a lista junta
  não existia. Se essa junção deve viver fora do repositório, como a matriz, é decisão do
  fundador.

## Controlo de versões

| Versão | Data | Alteração | Autor |
|---|---|---|---|
| 0.1 | 2026-11-25 | Pacote preparado sem o mundo real (KAM-074, lote 24): regras, as catorze áreas com a evidência automatizada e o que os blocos donos declaram por medir, entradas, acesso mínimo sem credenciais, fora do âmbito e pré-condições. Nada acordado com um revisor. | Coordenação do lote 24 |
| 0.2 | 2026-11-25 | Os credores do KAM-074 abertos pela coordenação do lote 24: o KAM-259 para o registo do acesso (§4 e §6) e o KAM-260 na área 6. | Coordenação do lote 24 |
| 0.3 | 2026-11-27 | KAM-259: o acesso do revisor a `staging` entra pela conta `breakglass` e fica no `audit_log`, com o comando que mostra as duas linhas dele (§4); a pré-condição do §6 passa a depender só do *host*. | Equipa KAMBÁ |
