# Matriz de ambientes

| Campo | Valor |
|---|---|
| Documento | Infraestrutura — matriz de ambientes `dev` / `staging` / `prod` |
| Versão | 1.0 |
| Data | Novembro de 2026 |
| Classificação | Documento de Referência — Interno; **verificado por máquina** |
| Ticket | KAM-075 (EPIC-08) |
| Documento-fonte | `../docs/tecnica/09_Topologia_Operacao_Escala.md` §6 (a matriz), §4.4 (as formas de *compute*), §5.3 (portabilidade) |
| Relacionados | [`PORTABILIDADE.md`](PORTABILIDADE.md), [`README.md`](README.md), [`../docs/adr/ADR-L007-ferramenta-de-iac.md`](../docs/adr/ADR-L007-ferramenta-de-iac.md) |

> **Este documento não é uma cópia do doc 09 §6: é a sua forma verificável.**
> Cada linha abaixo tem uma **chave**, e a chave aponta para um campo de
> `envs/<ambiente>/env.yaml`. O `tools/env_lint`, dentro do gate 2, lê as duas
> superfícies e **falha quando discordam**. Uma divergência entre a tabela e a
> configuração deixou de ser possível por descuido — que é a única coisa que
> uma matriz escrita à mão não garantia.

---

## 1. Como se lê

Cada célula começa pelo **token canónico** em código inline. É esse token, e só
esse, que o `env_lint` compara com o YAML; a prosa a seguir é para quem lê.

```text
| Dados | `dados.classe` | `synthetic` | `synthetic` | `synthetic` (`real` só após D1 e APD) |
                                                        ^^^^^^^^^ comparado
                                                                   ^^^^^^^^^^^^^^^^^^ prosa
```

O token é minúsculo, sem espaços e sem acentos, de propósito: um valor que se
compara byte a byte não pode depender de como alguém escreveu «não-root».

---

## 2. As sete linhas do doc 09 §6

| Aspecto | Chave | `dev` | `staging` | `prod` |
|---|---|---|---|---|
| Dados | `dados.classe` | `synthetic` | `synthetic` — **nunca** cópia de `prod` | `synthetic` — passa a `real` só com D1 **e** `apd_ref` (§5) |
| Compute | `compute.forma` | `compose-local` | `4vcpu-16gb` — a pedido | `8vcpu-32gb` — NVMe ≥ 200 GB (doc 09 §4.4) |
| Meta | `meta.modo` | `mock` — *webhook* com corpo assinado por segredo de teste | `numero-de-teste` — WABA de teste da app Meta de *staging* | `producao` — números dos clientes via Embedded Signup v4 |
| Facilitador | `facilitador.modo` | `mock` | `sandbox` — ProxyPay em `api.sandbox.proxypay.co.ao` (§4) | `producao` — por PME |
| LLM | `llm.modo` | `chave-de-teste` — *budget* mínimo | `chave-propria` — *budget* baixo | `chaves-virtuais-por-tenant` |
| Segredos | `segredos.projecto` | `local` — não reutilizáveis, sem projecto remoto | `staging` — projecto Doppler | `prod` — projecto Doppler |
| Acesso | `acesso.modo` | `equipa` | `equipa` | `break-glass-auditado` — registo em `audit_log` |

**As sete chaves são as sete que o critério 1 do KAM-075 nomeia** — dados,
compute, Meta, facilitador, LLM, segredos, acesso — e são as sete que o
`env_lint` verifica contra `envs/*/env.yaml`.

### 2.1 Uma divergência de contagem, registada em vez de corrigida em silêncio

O critério 1 diz «as **7** linhas do doc 09 §6». A tabela do doc 09 §6 tem
**oito** linhas: as sete acima mais **Factura AGT**. As duas leituras possíveis
são (a) o critério conta mal, (b) o critério escolhe deliberadamente sete das
oito, e a lista entre parênteses — que nomeia exactamente estas sete — favorece
(b).

Seguiu-se a **letra do critério**: as sete nomeadas são as verificadas. A oitava
está em §3, fora do conjunto verificado, com a razão. **Não se corrigiu o
critério**: alterar um critério de aceitação não é acto de quem o executa.

---

## 3. A oitava linha do doc 09 §6, e porque não é verificada aqui

| Aspecto | `dev` | `staging` | `prod` | Porque fica fora |
|---|---|---|---|---|
| Factura AGT | Mock | Sandbox do parceiro (Vero: sandbox que não submete à AGT, **INDÍCIO**) | Produção | Não tem superfície de configuração neste ticket. O parceiro de factura e a data da fase 2 são **INDÍCIO / NÃO VERIFICADO** no doc 09 §19, ligados à **D7**; a facturação é de outro epic. Verificar um campo cujo valor depende de uma decisão aberta seria fixar a decisão |

O estado **INDÍCIO** da sandbox Vero é herdado do doc 09 §6 e não foi promovido.

---

## 4. Factos de terceiros citados nesta matriz, com o seu estado

| Afirmação | Estado | Fonte |
|---|---|---|
| Sandbox ProxyPay em `api.sandbox.proxypay.co.ao`; OPG `900000000` aceita, `900002004` dá *timeout*, `900003000` recusa | **CONFIRMADO** | doc 09 §6; bloco do KAM-075 |
| Sandbox AppyPay existe | **INDÍCIO** | doc 09 §6. Não promovido: `facilitador.sandbox_appypay` fica `indicio` no YAML, e é por isso que o `env_lint` não exige um *endpoint* para ela |
| Número de teste da Meta não prova coexistência nem Embedded Signup reais | **INDÍCIO** (confirmação escrita pendente, **D5**) | doc 09 §6, nota final |
| Preços e cotações de alojamento | **NÃO VERIFICADO** | doc 09 §19. É o que impede o critério 7 — ver §6 |

---

## 5. `kamba_data_class`: como `prod` deixa de ser sintético

O campo `dados.classe` é o `kamba_data_class` do critério 4. Tem dois valores,
`synthetic` e `real`, e a passagem de um ao outro **não é uma edição de uma
linha**: o `env_lint` recusa `real` sem as duas referências.

```yaml
dados:
  classe: real
  decisao_d1: "<referência da decisão D1: documento, data e assinatura>"
  apd_refs: ["<n.º de protocolo da APD>"]
```

Falta uma das duas, ou está vazia, e o gate 2 falha com `real-sem-d1` ou
`real-sem-apd-ref`. **Hoje os três ambientes estão em `synthetic`** e as duas
referências estão a `null` e `[]`, porque:

- a **D1** está `em branco` em `../docs/tecnica/evidencia/validacao/GoLive_Gate.md`
  linha A1, e depende de ≥ 3 cotações das quais nenhuma foi pedida;
- existem **0 de 14** destinos com `apd_ref`, pela linha B2 do mesmo documento.

Isto não é um atraso deste ticket: é o estado correcto. O que este ticket
acrescenta é que passar a `real` por distracção deixou de ser possível.

> **O que este mecanismo não é.** A lógica do gate de transferência **por
> destino** é do KAM-069 e a tabela `tenant_destinations` não existe (linha D1t
> do `GoLive_Gate.md`). Aqui recusa-se o **ambiente**; lá recusa-se o
> **destino**. Marcar a linha D1t com este trabalho seria promover uma coisa a
> outra.

---

## 6. O que esta matriz **não** diz, e porquê

| O que falta | Porque falta | Onde se resolve |
|---|---|---|
| Fornecedor e região | **D1 em branco** — acto do fundador | D1; cotações em KAM-105 |
| Custo mensal por ambiente, a partir de cotação real | O critério 7 exige-o «não do doc 09». **Não existe nenhuma cotação**: `Alojamento_Cotacoes.md` registra «Nenhuma pedida». As *etiquetas* de custo estão definidas (§7); o número não | D1; KAM-105 |
| Tempo real de um *host* novo | **Nunca se aplicou nada.** Sem conta e sem fornecedor não há `apply` nem cronómetro — ver `README.md` §5 | D1, e depois este procedimento |
| Onde fica o estado do OpenTofu | É alojamento, logo ADR-008 e D1 | D1 |

---

## 7. O que este ticket acrescenta à matriz

Estas linhas não estão no doc 09 §6. Vêm dos Detalhes Técnicos do KAM-075 e são
verificadas pelo `env_lint` como as outras.

| Aspecto | Chave | `dev` | `staging` | `prod` | Estado |
|---|---|---|---|---|---|
| TTL do DNS | `dns.ttl_segundos` | `300` | `300` | `300` | ***Proposta*** do bloco do KAM-075. Entra no passo «DNS» dos 15 min do orçamento de RTO (doc 09 §8.2). **Não foi medida nenhuma propagação** — medir é do KAM-085 |
| Etiqueta de ambiente | `custo.etiquetas.kamba_env` | `dev` | `staging` | `prod` | Etiqueta de custo por ambiente (ADR-018). Aplica-se a todo o recurso que a costura do fornecedor criar |
| Etiqueta de classe de dados | `custo.etiquetas.kamba_data_class` | `synthetic` | `synthetic` | `synthetic` | Segue `dados.classe`; o `env_lint` exige que sejam iguais, senão a etiqueta mente sobre o que o recurso guarda |
| Custo mensal | `custo.mensal_usd` | `null` | `null` | `null` | **NÃO VERIFICADO** — ver §6 |
| Restauro aceite de | `dados.restauro_de` | `[]` | `[]` | `[]` | O controlo do critério 3: `staging` com `prod` nesta lista faz o gate falhar com `restauro-de-prod` |

---

## 8. Controlo de versões

| Versão | Data | Alteração | Autor |
|---|---|---|---|
| 1.0 | Novembro de 2026 | Emissão inicial, KAM-075. As sete linhas nomeadas pelo critério 1, com chave por linha e token canónico por célula, comparadas com `envs/*/env.yaml` pelo `tools/env_lint` no gate 2. A oitava linha do doc 09 §6 (Factura AGT) registada em §3 fora do conjunto verificado, com a razão e a divergência de contagem do critério declarada em §2.1. O `kamba_data_class` e as duas referências que a passagem a `real` exige em §5; o que a matriz não diz, e a razão (D1), em §6. | Equipa KAMBÁ |
