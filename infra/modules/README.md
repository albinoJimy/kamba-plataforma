# `infra/modules/` — os módulos, e a costura do fornecedor

Dois módulos, e a razão de serem dois é a portabilidade do critério 6 do
KAM-075: **o que é específico de um fornecedor está num sítio só**, e o outro
não sabe que fornecedor existe.

| Módulo | O que faz | Sabe o fornecedor? |
|---|---|---|
| [`provider-pendente/`](provider-pendente/) | A **costura**: declara a interface que um fornecedor tem de implementar. Hoje **falha fechado** | É o único que saberia |
| [`host-base/`](host-base/) | O documento cloud-init do primeiro arranque: Docker, utilizador não-root, WireGuard, montagem do disco NVMe | Não |

**Não há módulo de DNS**, e isso é deliberado. O TTL é um parâmetro
(`dns.ttl_segundos` em `env.yaml`, *proposta* de 300 s) que atravessa a costura
como qualquer outro; um módulo próprio para passar um número não acrescentava
nada e dava a impressão de que a gestão de DNS está feita. Os registos
concretos são do KAM-077, que é quem tem o *edge*.

## A regra que o gate 2 verifica

```text
Nenhum ficheiro `.tf` fora de `infra/modules/provider-*/` declara um bloco
`resource`, `data` ou `provider`.
```

Quem a verifica é `tools/env_lint` (achado `recurso-fora-da-costura`), e há uma
*fixture* negativa a provar que morde. A regra é o que faz da portabilidade uma
propriedade medida em vez de uma intenção — ver
[`../../docs/adr/ADR-L007-ferramenta-de-iac.md`](../../docs/adr/ADR-L007-ferramenta-de-iac.md)
§2.

É também a razão pela qual `tofu init -backend=false` e `tofu validate` **correm
sem rede** nesta árvore: sem bloco `provider` não há nada para descarregar.

## Os candidatos da D1, e o que cada um teria de trazer

A D1 escolhe entre os candidatos que o bloco do KAM-077 e o doc 09 §5.2 nomeiam.
**Esta tabela não escolhe nem ordena**: diz o nome que o módulo teria e o que
falta saber para o escrever. **Sem preços**, porque não há nenhum: o KAM-105
pediu **0** cotações
([`../../docs/tecnica/evidencia/validacao/Alojamento_Cotacoes.md`](../../docs/tecnica/evidencia/validacao/Alojamento_Cotacoes.md)).

| Candidato | Região | Módulo que nasceria | *Provider* OpenTofu, API ou só consola? | Modelo |
|---|---|---|---|---|
| Raxio | Luanda | `provider-raxio/` | **NÃO VERIFICADO** | *Colocation* e IaaS (doc 09 §5.2) |
| Paratus | Luanda | `provider-paratus/` | **NÃO VERIFICADO** | *Colocation* e IaaS (doc 09 §5.2) |
| Angola Cables | Luanda | `provider-angola-cables/` | **NÃO VERIFICADO** | *Colocation* e IaaS (doc 09 §5.2) |
| Cloud Nacional | Luanda (Camama) | `provider-cloud-nacional/` | **NÃO VERIFICADO** | IaaS, serviços a privados (doc 09 §5.2) |
| Hiperescalador em JNB/CPT | Joanesburgo ou Cidade do Cabo | `provider-<nome>/` | Existe para os hiperescaladores — **INDÍCIO**, por versão e *hash* a fixar no dia | IaaS e serviços geridos |

**A coluna do meio é a pergunta que mais custa se ficar para o fim.** Um
fornecedor de Luanda sem API nem *provider* deixa a costura com um módulo que
não cria nada — o *host* faz-se à mão na consola, e a portabilidade passa a
ser do `host-base` (o cloud-init é o mesmo em qualquer *host*) e não do
`apply`. Não deixa de ser portável; deixa de ser automático. Pergunta-se no
pedido de cotação, e não depois do contrato.

**O que qualquer `provider-<nome>` tem de trazer além das saídas da interface**
(preparação do KAM-077): um grupo de segurança, se o fornecedor o tiver, com
**só** 443/tcp e a porta UDP do WireGuard (`porta_wireguard` do `host-base`) —
como **reforço** das regras `nftables` do `host-base`, nunca como a única
barreira (`../PORTABILIDADE.md` classe 3). É também ele que fecha a janela do
primeiro arranque, em que a porta 22 está como a imagem a deixou até o
cloud-init chegar ao `runcmd`.

## Quando a D1 fechar

1. Cria-se `infra/modules/provider-<nome>/` com as **mesmas** variáveis e as
   **mesmas** saídas que `provider-pendente/` declara.
2. Trocam-se duas linhas de `source` — em `envs/staging/main.tf` e em
   `envs/prod/main.tf`.
3. O `required_providers` e o `.terraform.lock.hcl` do módulo novo fixam o
   *provider* por versão **e** *hash* (DoD do KAM-075).

Os ambientes não mudam. É isso que «mudar de região não pode exigir reescrita»
quer dizer (`../../docs/tecnica/evidencia/E3_Regulatorio_Dados.md` requisito 24;
doc 09 §5.3 ponto 1).

**O que isto não prova:** que a troca é mesmo de duas linhas. Nunca se trocou,
porque nunca houve um segundo módulo de fornecedor. A afirmação é **NÃO
VERIFICADO** e verifica-se no dia em que o primeiro `provider-<nome>` existir.
