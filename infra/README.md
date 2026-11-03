# Infraestrutura

| Caminho | O que é | Ticket |
|---|---|---|
| [`ENVIRONMENTS.md`](ENVIRONMENTS.md) | A **matriz de ambientes** do doc 09 §6, com uma chave por linha, comparada por máquina com a configuração | KAM-075 |
| [`PORTABILIDADE.md`](PORTABILIDADE.md) | A *checklist* de portabilidade: oito classes de recurso, equivalente por classe, e a linha que não fecha | KAM-075 |
| `envs/{dev,staging,prod}/env.yaml` | A configuração de cada ambiente, em forma maquinável. É a **fonte**; a matriz é a sua forma legível | KAM-075 |
| `envs/{staging,prod}/*.tf` | Os módulos de raiz em OpenTofu. Não declaram recursos: chamam a costura | KAM-075 |
| [`modules/`](modules/) | `provider-pendente/` (a costura do fornecedor, a falhar fechado) e `host-base/` (o cloud-init do primeiro arranque) | KAM-075 |
| `compose/docker-compose.dev.yml` | Pilha de **desenvolvimento local**: Postgres 18.6 + pgvector, fila compatível com Redis (AOF), e os cinco serviços | KAM-001 |
| `compose/postgres/initdb/` | Bases e extensões do arranque local (sem tabelas) | KAM-001 |
| `egress/` | As saídas declaradas por serviço (`por_omissao: negar`) | KAM-067 |

A ferramenta está fixada em
[`../docs/adr/ADR-L007-ferramenta-de-iac.md`](../docs/adr/ADR-L007-ferramenta-de-iac.md):
**OpenTofu 1.10.6** mais **cloud-init**, com o fornecedor atrás de uma costura.

---

## 1. O que ainda não está aqui

| O que falta | Ticket |
|---|---|
| Compose de produção do conjunto reduzido, redes isoladas, proxy de saída | KAM-076 |
| Alojamento, proxy inverso com TLS, *edge* e WAF; *scan* externo de portas | KAM-077 |
| Prometheus, Alertmanager, Grafana, Loki, sonda sintética externa | KAM-076 |
| `pgBackRest`, RPO/RTO, teste de restauro | KAM-077 |
| SBOM por imagem, assinatura cosign e `release.lock` (as imagens já vêm por *digest*, e cada serviço declara as suas saídas em `infra/egress/` e `services/*/egress.yaml`: KAM-067, `../docs/supply-chain.md`) | KAM-078 |

A topologia-alvo está em `../docs/tecnica/09` §3; as regras de rede em §3.2. Duas
delas já são cumpridas pelo compose local: a rede `data` é `internal: true` (sem
rota de saída) e nenhuma porta é publicada fora de `127.0.0.1`.

---

## 2. A decisão que falta, e porque está escrita em todo o lado

A **D1** — alojamento em Luanda ou em JNB/CPT — é acto do fundador e está **em
branco**: linha A1 de `../docs/tecnica/evidencia/validacao/GoLive_Gate.md`,
dependente de ≥ 3 cotações das quais **nenhuma foi pedida** (KAM-105).

Tudo o que está em `infra/` foi escrito para ser verificável **sem** essa
decisão. A consequência é que um `tofu plan` **pára**, de propósito, com a
decisão em falta na mensagem. Não é um bloqueio a remover: é a decisão posta no
caminho de quem a tentar saltar.

---

## 3. Verificar os ambientes

```bash
cd tools && python -m env_lint --root .. lint
cd tools && python -m env_lint --root .. canario
```

Corre no gate 2 (`make env-lint`, chamado por `make ci-2`). O que verifica e o
que **não** verifica está em [`../tools/env_lint/README.md`](../tools/env_lint/README.md).

---

## 4. O mapeamento ambiente → projecto de segredos

| Ambiente | Projecto | Cofre | Fonte |
|---|---|---|---|
| `dev` | `local` — sem projecto remoto | nenhum | doc 09 §6: «Local, não reutilizáveis» |
| `staging` | `staging` | Doppler | doc 09 §6: «Projecto Doppler `staging`» |
| `prod` | `prod` | Doppler | doc 09 §6: «Projecto `prod`» |

**Os projectos são criados pelo KAM-010, que já está entregue.** Este ticket
define o mapeamento e **falha quando ele é violado**; não cria projectos e não
toca no cofre.

Uma referência de segredo tem a forma `<projecto>/<ID_EM_MAIÚSCULAS>`, onde o
`ID` é um `id` de `../ops/secrets-inventory.yaml`. Escrever
`prod/META_APP_SECRET` dentro de `envs/staging/` faz o gate 2 falhar com
`segredo-de-outro-ambiente` — que é o teste negativo do critério 5.

> **Uma divergência que este ticket teve de resolver para escrever a tabela.**
> O `../ops/runbooks/secrets-export.md` escreve `--project kamba --config staging`,
> isto é **um** projecto `kamba` com três configurações. O doc 09 §6 e o código
> (`../packages/core-ts/src/secrets/doppler.ts`, que recusa o arranque quando
> `config != ambiente`) dizem **três projectos** chamados `dev`, `staging` e
> `prod`. Seguiu-se o doc 09 e o código, porque o comando do runbook está
> marcado **NÃO VERIFICADO** nesse mesmo ficheiro. Registado em
> `../docs/dividas-documentais.md`; resolve-se com uma conta Doppler, que não existe.

---

## 5. *Host* novo em ≤ 30 min — o procedimento, e o que dele **não** foi medido

> **O NÚMERO NÃO FOI MEDIDO.** O critério 2 do KAM-075 pede «≤ 30 min, mediana
> de 3 execuções registada» numa conta vazia. **Não houve nenhuma execução**:
> não há conta, não há fornecedor (D1), e não há nada onde cronometrar. Os
> 30 min continuam a ser *proposta* do `../docs/tecnica/09` §8.2, onde entram no
> orçamento de RTO de 2 h — não uma medição deste ticket.
>
> A caixa do critério 2 fica **vazia**, e é esta secção a razão escrita.

O procedimento, para quando houver onde o correr (insumo do runbook RB-K08):

```bash
# 0. Pré-requisitos: a D1 decidida, uma conta no fornecedor escolhido, e
#    `infra/modules/provider-<nome>/` escrito (ver modules/README.md).
cd infra/envs/staging

# 1. Verificar antes de aplicar. Corre offline e sem conta.
tofu init -backend=false && tofu validate

# 2. Ver o que vai acontecer. Com a D1 em branco, PÁRA aqui — por desenho.
tofu plan

# 3. Aplicar, com o cronómetro a correr.
#    O relógio conta do `apply` até o host escrever /etc/kamba/arranque-concluido.
tofu apply

# 4. Idempotência: o segundo apply não altera nada.
tofu plan   # tem de dar «No changes»

# 5. Destruir, para a execução seguinte.
tofu destroy
```

**O que medir, e onde registar.** Três execuções, a mediana dos três tempos, e
o resultado em `../docs/evidencia/KAM-075.md`. O que o cronómetro tem de
abranger, para não medir menos do que o critério pede:

| Passo | Conta para os 30 min? |
|---|---|
| `tofu apply` até o fornecedor devolver o *host* | **Sim** |
| cloud-init: Docker, utilizador não-root, WireGuard, montagem do NVMe | **Sim** — até `/etc/kamba/arranque-concluido` existir |
| Compose de produção a subir | **Não** — é o KAM-076 |
| Restauro da base de dados | **Não** — é outro item do orçamento de RTO (doc 09 §8.2) |

**E o que falta ao procedimento, dito antes de alguém o seguir:** o passo 3 só
funciona com um módulo de fornecedor que não existe, e o passo que vai buscar a
chave do WireGuard ao cofre usa subcomandos do Doppler marcados **NÃO
VERIFICADO** em `../ops/runbooks/secrets-export.md` §7. Nenhum destes correu.

---

## 6. Estado do OpenTofu

**Não há estado**, porque nenhum ambiente foi aplicado. O DoD do KAM-075 exige
estado cifrado, e a configuração disso está escrita — **comentada** — em
`envs/*/estado.tf`, com a razão: *onde* fica o estado é alojamento, logo
ADR-008, logo D1.

O `.gitignore` já exclui `envs/*/.terraform/`, o estado e os planos. A chave da
cifra virá do cofre (KAM-010), nunca de um ficheiro no repositório — é a mesma
regra do «sem chave estática» do ADR-L007 §4, aplicada ao estado.

---

## 7. Verificar o HCL à mão

Não há gate de HCL: meter o OpenTofu num *job* de CI para verificar ficheiros
que ainda não criam nada era acrescentar uma ferramenta por antecipação. Quando
houver fornecedor, o `tofu validate` entra no gate 2 ao lado do `env-lint`.

Até lá, corre-se à mão, em contentor (nesta máquina não há `tofu` no `PATH`):

```bash
docker run --rm -v "$PWD:/w" -w /w/infra/envs/staging \
  --entrypoint /usr/local/bin/tofu ghcr.io/opentofu/opentofu@sha256:879a73a0ee45132abf1b26583e3ab3a1e5443157a13b460114578d13dbe40b6e \
  init -backend=false
docker run --rm -v "$PWD:/w" -w /w/infra/envs/staging \
  --entrypoint /usr/local/bin/tofu ghcr.io/opentofu/opentofu@sha256:879a73a0ee45132abf1b26583e3ab3a1e5443157a13b460114578d13dbe40b6e validate
docker run --rm -v "$PWD:/w" -w /w/infra \
  --entrypoint /usr/local/bin/tofu ghcr.io/opentofu/opentofu@sha256:879a73a0ee45132abf1b26583e3ab3a1e5443157a13b460114578d13dbe40b6e \
  fmt -check -recursive
```

A imagem vai por **`@sha256:`** e não por etiqueta: uma etiqueta é mutável, e esta
imagem é hoje o único artefacto de IaC que de facto se executa (ADR-L007 §5).

Corre **offline**: sem bloco `provider` não há nada para descarregar, que é uma
consequência útil da costura (`modules/README.md`).

O resultado medido a 2026-11-02 está em `../docs/evidencia/KAM-075.md`.
