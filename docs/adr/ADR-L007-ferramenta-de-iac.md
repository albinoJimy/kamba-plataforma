# ADR-L007 — Ferramenta de infraestrutura como código

| Campo | Valor |
|---|---|
| Estado | Aceite |
| Data | 2026-11-02 |
| Ticket | KAM-075 — Ambientes dev/staging/prod e infraestrutura como código mínima |
| Âmbito | Local (ver [`README.md`](README.md)): **que ferramenta** descreve a infraestrutura, não **onde** ela corre |
| Decisores | Executor do KAM-075 (a ratificar por Plataforma/SRE) |
| ADRs canónicos aplicáveis | ADR-008 (dados pessoais fora de Angola), ADR-014 (licenças permitidas), ADR-018 (custo visível) |
| Decisões abertas que este ADR **não** toca | **D1** (alojamento: Luanda ou JNB/CPT) e **D6** (armazenamento de objectos) |
| Substitui | — |

## Contexto

O bloco do KAM-075 manda fixar a ferramenta aqui e dá-lhe uma *proposta* e dois
critérios:

> ferramenta a fixar em ADR local (*proposta*: OpenTofu + Ansible/cloud-init;
> critério: sem chave estática, sem módulo de fornecedor único).

A pergunta que este ADR responde é estreita de propósito. **Não decide o
fornecedor nem a região:** isso é a D1, é acto do fundador, e está **em branco**
— a linha `A1` de `../tecnica/evidencia/validacao/GoLive_Gate.md` di-lo, e
acrescenta que depende de ≥ 3 cotações das quais «nenhuma» foi pedida. Decidir
aqui o fornecedor seria usurpar essa decisão; é por isso que o critério do
ticket diz «agnóstica de fornecedor».

O que fica decidido é a **linguagem em que a infraestrutura se escreve** e a
**costura** por onde o fornecedor entra quando a D1 fechar.

## Decisão

Duas camadas, e cada uma faz uma coisa só:

```text
OpenTofu 1.10.6   descreve o que existe (recursos, dependências, estado)
cloud-init        inicializa cada host na primeira arranque (Docker, utilizador
                  não-root, WireGuard, montagem do disco NVMe)
```

**Ansible fica fora**, e a razão não é de gosto (§3).

## 1. Porque OpenTofu e não Terraform

A razão é a licença, e é mecânica neste repositório — não é preferência:

| Ferramenta | Licença | O que `ci/licenses.yaml` diz |
|---|---|---|
| **OpenTofu** | Mozilla Public License, version 2.0 | `permitidas` inclui `MPL-2.0` (linha 54) |
| Terraform | BUSL-1.1 | `negadas` tem `prefixo: BUSL`, com a razão «Não OSI até a Change License» (linhas 81–82) |

Estado das duas afirmações:

- **CONFIRMADO** — a licença do OpenTofu é «Mozilla Public License, version
  2.0», lida da fonte primária (`LICENSE` na raiz de `opentofu/opentofu`, ramo
  `main`, a 2026-11-02). O ficheiro não escreve o identificador SPDX; `MPL-2.0`
  é o identificador normalizado dessa licença.
- **CONFIRMADO** — o que `ci/licenses.yaml` permite e nega, lido do próprio
  ficheiro. A entrada que nega `BUSL` nomeia o HashiCorp Vault pela mesma razão,
  e o KAM-010 já excluiu o Vault por ela (`specs/tickets/KAM-010.md`).

Escolher Terraform exigiria uma dispensa em `ci/waivers.yaml` para a política de
licenças do gate 11. Não há razão técnica que a pague: a linguagem é a mesma e o
OpenTofu é o fork no ponto em que a licença mudou.

## 2. A costura do fornecedor, que é o que torna isto portátil

O critério «sem módulo de fornecedor único» não se cumpre com uma intenção
escrita. Cumpre-se com uma regra que uma máquina verifica, e é esta:

```text
Nenhum módulo de raiz (`infra/envs/*/`) declara um bloco `resource`,
`data` ou `provider`. Todo o recurso específico de um fornecedor vive
atrás de `infra/modules/provider-<nome>/`, que implementa uma interface fixa.
```

O que isto compra: mudar de fornecedor é escrever um `provider-<nome>/` novo e
trocar uma linha de `source` em três ficheiros. Não é reescrever os ambientes.
É o requisito 24 do `../tecnica/evidencia/E3_Regulatorio_Dados.md` e o ponto 1
do `../tecnica/09_Topologia_Operacao_Escala.md` §5.3 — «mudar de região não pode
exigir reescrita» — passado a verificação em vez de a promessa.

Hoje existe **um** módulo de fornecedor, `infra/modules/provider-pendente/`, que
**falha fechado**: qualquer tentativa de o aplicar pára com «a D1 não está
decidida». Não é um esboço à espera de ser preenchido — é a decisão em falta,
posta onde um `apply` tropeça nela em vez de a adivinhar.

Quem verifica a regra é `tools/env_lint` (`make env-lint`, dentro do gate 2),
que falha com `recurso-fora-da-costura` quando ela é violada — nas **duas** formas
nativas do OpenTofu, o `.tf` e o `.tf.json` —, e tem casos de canário a provar
que morde. (O canário desta ferramenta é **por mutação** e não por *fixtures*,
ao contrário do `log-lint` e do `money-lint`; a razão está em
`tools/env_lint/canario.py`.)

## 3. Porque cloud-init e não Ansible

O bloco do ticket propõe «Ansible/cloud-init» — as duas, com uma barra. Escolhe-se
o cloud-init, por duas razões de peso diferente.

A primeira é a mesma do §1, e é mecânica:

| | Ansible | cloud-init |
|---|---|---|
| Licença | GPL-3.0 | não entra no SBOM deste repositório (ver abaixo) |
| `ci/licenses.yaml` | `negadas` tem `prefixo: GPL-`, com a razão «Copyleft forte […] exige waiver com a leitura escrita, não silêncio» (linhas 89–90) | — |

O Ansible seria uma dependência Python nossa, instalada e corrida por nós: entra
no SBOM e no gate 11, e precisaria de dispensa escrita. O cloud-init não: já vem
na imagem do *host* do fornecedor, e o que nós versionamos é um **documento
YAML** que ele lê. Não é código nosso nem dependência nossa, e por isso não há
pergunta de licença a responder. **A licença do próprio cloud-init não foi
lida** e fica **NÃO VERIFICADO** — e fica assim porque é irrelevante para esta
decisão, não porque seja desconhecida de propósito: valeria a pena se algum dia
o instalássemos.

A segunda razão é de operação, e é a que importaria mesmo que as licenças fossem
iguais: o cloud-init corre **uma vez, no primeiro arranque, sem nada do lado de
fora**. O Ansible precisa de um canal SSH aberto de uma máquina de controlo até
ao *host* novo — que é exactamente a superfície que o
`../tecnica/08_Seguranca_Conformidade.md` §5 fecha («Sem SSH por palavra-passe»,
admin só por VPN WireGuard). Provisionar um *host* com o WireGuard por configurar
através de um canal que só existe depois do WireGuard é uma dependência circular;
o cloud-init não a tem, porque corre de dentro.

**O que se perde, e diz-se:** o cloud-init não é idempotente por desenho — corre
uma vez. A idempotência que o CA2 do ticket pede («um segundo `apply` não altera
nada») é propriedade do OpenTofu, não do cloud-init: o `apply` compara estado e
não re-executa o arranque. Um *host* que precise de ser reconfigurado depois do
primeiro arranque é um *host* novo, e isso é deliberado — é o mesmo pressuposto
do orçamento de RTO (`../tecnica/09` §8.2: «novo *host* por IaC em 30 min»).

## 4. Sem chave estática

O critério tem duas metades, porque há dois sítios onde uma chave estática
apareceria:

**(a) Autenticação ao fornecedor.** Nenhuma credencial de fornecedor em
ficheiro, em variável de ambiente de longa duração ou no estado. A via é
identidade federada: o CI troca o seu *token* OIDC por credenciais de curta
duração. Este repositório já o faz, e já o tem por escrito: o comentário da
linha 15 de `.github/workflows/ci.yaml` diz «Sem chaves estaticas. A
autenticacao e por OIDC (`id-token: write`)», e **seis** *jobs* desse ficheiro
pedem essa permissão. **O que não se pode verificar hoje:**
que o fornecedor escolhido suporta OIDC do GitHub. Isso depende da D1, e entra na
*checklist* de `infra/PORTABILIDADE.md` como condição de aceitação do fornecedor
— ou seja, é um critério que a D1 tem de satisfazer, não uma suposição sobre ela.

**(b) Estado do OpenTofu.** O estado guarda valores sensíveis, e o DoD do ticket
exige-o cifrado. O OpenTofu tem cifra de estado nativa (bloco `encryption`), com
a chave vinda do cofre — não de um ficheiro no repositório. A configuração está
em `infra/envs/*/estado.tf` e **não corre hoje**: o `backend` depende da D1 (onde
fica o estado é alojamento, e alojamento é ADR-008). Até lá o estado é local e
**nenhum ambiente foi aplicado**, pelo que não existe estado nenhum para cifrar.
Isto está escrito em `infra/README.md` §6 e é **NÃO VERIFICADO** — nunca houve um
`apply`.

## 5. Versões fixadas

| Componente | Versão | Onde está fixada | Estado |
|---|---|---|---|
| OpenTofu (o binário) | `1.10.6` | `required_version = "1.10.6"` em `infra/envs/*/versoes.tf` — versão **exacta**, não gama | **CONFIRMADO** — `tofu version` na imagem, 2026-11-02 |
| A imagem com que se verifica à mão | `@sha256:879a73a0…40b6e` | `infra/README.md` §7 e `docs/evidencia/KAM-075.md` §1.4 | **CONFIRMADO** — `docker inspect --format '{{index .RepoDigests 0}}'`, 2026-11-02. Entrou por *digest* depois de uma revisão notar que uma **etiqueta é mutável**, e que esta imagem é hoje o único artefacto de IaC que de facto se executa. **Não está em `ci/supply-chain/imagens.yaml`**: esse inventário é lido por um eixo que varre compose, Dockerfile, *workflow* e `.env*`, não `.md`, e acrescentar-lhe uma entrada é mexer em `ci/` — fica registado como dívida, credor **KAM-078** |
| Fornecedores (*providers*) | **nenhum** | `required_providers` está vazio | Por desenho: não há fornecedor até a D1 |

Não há *provider* fixado porque não há *provider*. É a consequência directa de
§2 e a razão pela qual `tofu init -backend=false` e `tofu validate` **correm
offline** nesta árvore: sem fornecedor não há descarga. Quando a D1 fechar, o
`provider-<nome>/` traz o seu `required_providers` com versão **e** `hash` do
*lockfile* (`.terraform.lock.hcl`), que é o que o DoD quer dizer com «fixadas por
versão/hash».

## 6. O que este ADR não decide

| Pergunta | Onde se decide |
|---|---|
| Fornecedor e região de alojamento | **D1** — fundador; cotações em KAM-105 |
| Onde fica o estado do OpenTofu | Depende da D1 (é alojamento, ADR-008) |
| Armazenamento de objectos | **D6** — KAM-011 |
| Proxy TLS, *edge*, WAF | KAM-077 |
| Compose de produção e redes isoladas | KAM-076 |
| Observabilidade | KAM-080 |
| Cópias de segurança e DR | KAM-079, KAM-085 |

## 7. Consequências

- **Positiva:** a infraestrutura escreve-se e verifica-se **antes** da D1. O
  gate 2 lê os três ambientes hoje, com o fornecedor em branco.
- **Positiva:** a política de licenças do gate 11 não precisa de dispensa
  nenhuma por causa deste ticket.
- **Negativa:** a costura custa uma indirecção. Um recurso específico de um
  fornecedor não se escreve onde é mais cómodo (no módulo de raiz) — tem de
  passar pela interface. É o preço da portabilidade, e é o que a regra de §2
  impõe mecanicamente para que não se erode com o tempo.
- **Negativa, e é a maior:** **nada disto foi aplicado.** Não há conta, não há
  fornecedor, não houve `apply`, e o CA2 do ticket — «≤ 30 min, mediana de 3
  execuções» — **não foi medido**. O que existe é a descrição e o procedimento;
  o número continua *proposta* do doc 09 §8.2. Ver `infra/README.md` §5.
