# Cadeia de abastecimento — o que se verifica no repositório

| Campo | Valor |
|---|---|
| Ticket | KAM-067 — Supply chain: SBOM, digests, cosign, lockfiles e bloqueio de licenças |
| Fonte normativa | [`specs/EPIC-07_Seguranca_Conformidade.md`](../specs/EPIC-07_Seguranca_Conformidade.md) (bloco KAM-067); [`docs/tecnica/08_Seguranca_Conformidade.md`](tecnica/08_Seguranca_Conformidade.md) §4.8 |
| Evidência | [`docs/tecnica/evidencia/E4_Stack_Licencas.md`](tecnica/evidencia/E4_Stack_Licencas.md) §1, §2.7 e §5 |
| Onde corre | Dentro do gate 11: `make ci-11` chama `make supply-chain` ([`docs/ci.md`](ci.md) §3) |
| Código | [`tools/supply_chain/`](../tools/supply_chain/) — só biblioteca padrão |
| Política e registos | [`ci/supply-chain/imagens.yaml`](../ci/supply-chain/imagens.yaml), [`ci/supply-chain/licencas.yaml`](../ci/supply-chain/licencas.yaml), `services/*/egress.yaml`, `infra/egress/*.yaml` |
| Estado | 4 dos 9 critérios de aceitação com evidência (1, 5, 6 e 9); 5 por cumprir ou por decidir, com a razão em [§9](#9-o-que-não-está-feito-e-porquê) |

> **Nada está ratificado.** A quarentena de 7 dias, os estados do inventário e
> os estados do registo de licenças são *proposta*. Onde este documento diz
> «NÃO VERIFICADO», é porque ninguém o verificou — incluindo quem o escreveu.

---

## 1. O que este ticket é, e o que não repete

O KAM-001 e o KAM-002 já tinham entregue metade do que o título do KAM-067
promete, e o ticket manda reutilizar. A divisão ficou assim:

| Coisa | Quem a faz | Onde |
|---|---|---|
| Lista de bloqueio de pacotes e imagens | KAM-001 | `tools/lint_arch`, `tools/blocklist.yaml` |
| SBOM CycloneDX por serviço, em cada PR | KAM-002 | `tools/sbom` |
| *Allowlist* de licenças SPDX, por expressão | KAM-002 | `tools/sbom/spdx.py`, `ci/licenses.yaml` |
| Vulnerabilidades críticas (OSV) | KAM-002 | `tools/sbom/vulns.py` |
| *Lockfiles* com *hash* | KAM-001 | `tools/pip_lock.py`, `pnpm-lock.yaml` |
| Segredos | KAM-002 | `tools/scan_secrets` (gate 9) |
| **Imagens por *digest*, com inventário** | **KAM-067** | `tools/supply_chain/imagens.py` |
| **Sem instalação em *runtime*; só de leitura** | **KAM-067** | `tools/supply_chain/runtime.py` |
| **Lista de saídas por serviço** | **KAM-067** | `tools/supply_chain/egress.py` |
| **Registo de licenças por versão** | **KAM-067** | `tools/supply_chain/licencas.py` |
| **Excepção de licença proibida só por ADR** | **KAM-067** | `tools/sbom/cli.py` (uma condição) |
| **Quarentena do Renovate e CI sem chaves, a falhar** | **KAM-067** | `tools/supply_chain/renovate.py`, `ci_chaves.py` |
| **Prova por mutação, no gate** | **KAM-067** | `tools/supply_chain/canario.py` |

A tabela critério a critério — o que já existia, com ficheiro e teste, e o que
faltava — está em
[`ANALISE-10`](analises/ANALISE-10-KAM-067-supply-chain.md) §1.

**Onde está o código, e porque não é onde o ticket diz.** Os «Detalhes
Técnicos» do ticket pedem `ci/supply-chain/{lint_images,verify_cosign,sbom,licenses,blocklist}.sh|py`
e `renovate.json`. O código está em `tools/supply_chain/`, como todas as outras
ferramentas de verificação (com suite descoberta pelo `make` e medida pelo gate
4); em `ci/supply-chain/` ficaram os dois ficheiros de dados; `sbom`, `licenses`
e `blocklist` não se reescreveram, porque já existem em `tools/sbom` e
`tools/lint_arch`; e o ficheiro do Renovate é o `renovate.json5` que o KAM-001
criou. É um desvio à letra dos «Detalhes Técnicos», escolhido para não duplicar.

**Porque corre dentro do gate 11 e não num gate próprio.** O `specs/01` §4
atribui «*digest* fixado; assinatura cosign» ao gate 14, que bloqueia a
**publicação da imagem**, e o gate 18 ao **release**. Os dois são do KAM-078,
que é quem constrói e publica imagens. O que aqui está é anterior a isso: corre
em cada PR, sobre o que está escrito no repositório, antes de existir imagem
nenhuma — exactamente a relação que o varrimento da OSV do gate 11 tem com o
gate 14 (`docs/ci.md` §3). Quando o KAM-078 ligar o gate 14, chama os mesmos
módulos.

---

## 2. As regras

`make supply-chain` são dois passos: `check` e `canario`. O `check` corre seis
verificações; cada achado traz a regra entre parêntesis rectos, o ficheiro e a
linha.

| Verificação | Regra | Falha quando |
|---|---|---|
| `imagens` | `imagem-sem-digest` | uma referência não traz `@sha256:` com 64 hexadecimais |
| | `imagem-nao-resolvida` | a imagem depende de uma variável sem omissão, ou de um `build:` cujo Dockerfile não se encontra |
| | `imagem-fora-do-inventario` | o *digest* (ou a etiqueta para esse *digest*) não é o do inventário |
| | `inventario-entrada-morta` | uma linha do inventário que nada referencia |
| | `lancador-nao-declarado` | código que chama o Docker sem declarar com que imagem |
| | `cosign-obrigatorio` | uma imagem com assinatura publicada (LiteLLM) sem `cosign: verificar` |
| | `cosign-sem-binario`, `cosign-falhou` | há imagens a verificar e o `cosign` não existe, ou devolve erro |
| | `ficheiro-ilegivel` | um compose, um workflow ou um Dockerfile que o leitor não consegue seguir — incluindo qualquer ficheiro que fale de `services:` e não se leia como compose em blocos |
| `runtime` | `instalacao-em-runtime` | um ponto de arranque instala (`pip install`, `npm i`, `npx`…) |
| | `arranque-nao-verificavel` | um ponto de arranque executa um ficheiro que não se encontra no repositório |
| | `instalacao-fora-do-lockfile` | uma instalação de *build* sem `--require-hashes`, ou sem `--frozen-lockfile --ignore-scripts`; um `pnpm rebuild` |
| | `fs-so-de-leitura` | um serviço de compose sem `read_only: true` |
| `egress` | `egress-em-falta` | um serviço sem lista de saídas |
| | `egress-invalido` | `por_omissao` ≠ `negar`, ou um destino sem nome (`*`, IP, CIDR) |
| | `egress-orfao` | uma lista de saídas para um serviço que não existe |
| `licencas` | `licenca-estado-incoerente` | o estado registado não é o que a política dá para aquela licença |
| | `licenca-sem-excepcao` | `excepcao` sem nota, ou com um ADR que não existe |
| | `componente-obrigatorio-em-falta` | o registo perdeu uma linha que tem de ter (Redis, Valkey, os de edição *Enterprise*…) |
| | `nao-adoptado-sem-ligacoes` | um `nao_adoptado` que não diz como apareceria no repositório |
| | `licenca-versao-diferente` | a versão em uso não é a versão para a qual a licença foi lida |
| | `componente-presente-sem-aprovacao` | um `nao_adoptado` ou `bloqueado` que está no repositório |
| | `bloqueado-fora-da-lista` | um `bloqueado` que `tools/blocklist.yaml` não bloqueia |
| | `ee-sem-registo` | um componente com edição *Enterprise* sem o campo `ee` |
| | `componente-sem-licenca` | uma imagem declara um componente sem linha no registo |
| `renovate` | `quarentena-desligada` | `minimumReleaseAge` < 7 dias, no topo ou numa regra |
| | `automerge-ligado` | `automerge` diferente de `false`, em qualquer profundidade ou por *preset* |
| | `configuracao-sombra` | um segundo ficheiro de configuração do Renovate, ou um `dependabot.yml` |
| | `excepcao-de-seguranca-sem-revisao` | a excepção de segurança sem revisores, etiquetas ou `automerge: false` |
| `ci` | `chave-estatica-no-ci` | uma referência ao cofre de segredos do GitHub num workflow |

Códigos de saída: `0` conforme, `1` achados, `2` erro de configuração. Um
ficheiro de política em falta, mal formado ou com uma chave que nenhum código lê
é **erro**, não «conforme» — é a lição da lacuna 12 de `docs/ci.md` §7.

---

## 3. Imagens por *digest*

### 3.1 Onde se procura uma imagem

| Sítio | O que se lê |
|---|---|
| Compose: qualquer `.yml`, `.yaml` ou `.json` com nome de compose **ou** que fale de `services:` | `image:`, com a omissão de `${VAR:-…}`; os `build.args` que alimentam um `FROM`. O que não se lê em blocos é achado; `dockerfile_inline`, `additional_contexts` e `include:` também |
| `Dockerfile`, `dockerfile`, `Dockerfile.*`, `Dockerfile-*`, `*.Dockerfile`, `Containerfile` | `FROM` (com os `ARG` resolvidos), `COPY --from=`, `RUN --mount=…from=`, `ONBUILD`, a directiva `# syntax=` |
| `.github/workflows/*`, `.github/actions/**` | `image:`, `container:`, `uses: docker://…`, e as linhas `docker run` |
| Qualquer outro YAML que fale de `image:` (um manifesto de Kubernetes) | `image:`, em qualquer profundidade |
| `.env`, `.env.*`, `*.env` | as variáveis que um compose usa como imagem |
| Constantes Python declaradas no inventário | hoje, `IMAGEM` em `db/gate_bd.py` |

**O `.env` conta, e não é pormenor.** O compose escreve
`${KAMBA_QUEUE_IMAGE:-valkey/valkey:…@sha256:…}`, e o `.env.example` — que o
`make bootstrap` copia para `.env` — define `KAMBA_QUEUE_IMAGE`. A variável
**substitui** a omissão: com o *digest* só no compose, a pilha de toda a gente
correria pela etiqueta e o lint passaria. Um `.env` local desactualizado falha o
`make supply-chain` na máquina de quem o tem, e está certo: é essa a imagem que
lá corre.

### 3.2 O inventário

[`ci/supply-chain/imagens.yaml`](../ci/supply-chain/imagens.yaml) regista, por
imagem: nome, etiqueta, *digest*, quando e de onde se leu, os componentes que
traz e o estado da assinatura. Hoje são quatro:

| Imagem | Onde é usada | cosign |
|---|---|---|
| `pgvector/pgvector:0.8.7-pg18` | compose; `db/gate_bd.py` (gates 6 e 8) | por apurar |
| `valkey/valkey:9.1.2-trixie` | compose (omissão da D12); `.env.example` | por apurar |
| `node:24.21.0-trixie-slim` | os quatro Dockerfile Node | por apurar |
| `python:3.12-slim-trixie` | o Dockerfile do AGR | por apurar |

Os quatro *digests* foram lidos a 2026-10-12 com
`docker buildx imagetools inspect`, e são os do **índice** multi-arquitectura.
O do `pgvector` coincide com o observado a 2026-10-10
([`docs/evidencia/KAM-001-node.md`](evidencia/KAM-001-node.md) §3).

### 3.3 Trocar ou acrescentar uma imagem

Sempre por esta ordem — o gate recusa as outras:

1. Ler o *digest* **da fonte**: `docker buildx imagetools inspect <imagem>:<etiqueta>`.
2. Escrevê-lo no inventário, com `lido_em` e `lido_de`, e os `componentes`.
3. Se trouxer um componente novo, dar-lhe linha em `licencas.yaml` (§6).
4. Só depois, escrever `nome:etiqueta@sha256:…` na referência.

### 3.4 cosign: três estados, e porque não dois

O critério 2 do ticket admite dois: verificar onde há assinatura publicada,
`cosign: n/a` com compensação onde não há. O inventário tem um terceiro,
`por_apurar`, e as quatro imagens estão nele.

`n/a` afirma que **não existe** assinatura publicada. Ninguém o verificou para
estas quatro: não há `cosign` nesta máquina nem no *runner*. Escrever `n/a`
seria promover «não sei» a «não há» — o defeito que a escala de verificação
deste repositório existe para impedir. `por_apurar` não é estado final: o gate
conta-as em voz alta em cada execução (`4 com assinatura POR APURAR`).

A compensação que o critério pede — *digest*, SBOM e varrimento — está feita a
um terço: o *digest* está fixado; o SBOM por imagem e o varrimento das camadas
dependem de um pipeline que construa e publique imagens (KAM-078).

O que se apurou sem instalar nada, e o que isso vale: a 2026-10-12 a etiqueta
`sha256-<digest>.sig` — onde o cosign guarda assinaturas no esquema antigo — dá
`not found` no Docker Hub para as quatro. É **INDÍCIO** de ausência, não prova:
não cobre a API de *referrers* nem assinaturas por plataforma. Não chega para
escrever `n/a`.

**O LiteLLM é a excepção, e está no código.** A assinatura está publicada desde
a v1.83.0 (E4 §2.7, CONFIRMADO). Uma imagem cujo repositório contenha `litellm`
como palavra (`litellm`, `litellm-database`, `litellm-non_root`) com `cosign`
diferente de `verificar` falha, e essa regra vive em
`tools/supply_chain/imagens.py` — não no YAML, onde se apagava com uma linha.

---

## 4. Sem instalação em *runtime*

Três regras, por ordem de gravidade.

**Um ponto de arranque não instala.** São pontos de arranque: `CMD`,
`ENTRYPOINT` e `HEALTHCHECK` de um Dockerfile; `command:`, `entrypoint:` e
`healthcheck.test` de um compose; os `scripts` `start`/`serve` de um
`package.json`; qualquer *script* de *shell* que um destes chame; e qualquer
ficheiro chamado `entrypoint*.sh`, `docker-entrypoint*.sh`, `start*.sh`,
`arranque*.sh`, `run*.sh`, `boot*.sh` ou `init*.sh` (com ou sem extensão).
Seguem-se as cadeias: um `entrypoint` que faça `. prepara.sh` leva à leitura do
`prepara.sh`, e um `CMD pnpm run arranque` à do `scripts.arranque`. Um ponto de
arranque que execute um ficheiro que não está no repositório é achado.

Instalar é `pip install`, `python -m pip install`, `uv`, `poetry`, `pipx`, `npm
i|install|ci|exec|rebuild`, `npx`, `pnpm install|add|dlx|rebuild`, `yarn`, `bun`.
Reconhece-se pelo **nome-base** do programa e pelo subcomando em qualquer
posição, depois de retirados os invólucros: `/usr/local/bin/pip --no-cache-dir
install`, `python -u -m pip install`, `sh -e -c '…'`, `if x; then npm i; fi`,
`timeout 300 pip install` e `… | xargs pip install` contam todos. A primeira
versão ancorava um padrão no início do comando, e nenhuma destas formas contava.

**Uma instalação de *build* vem do *lockfile*.** Num `RUN`, numa receita do
`Makefile` ou num passo de workflow: `pip` com `--require-hashes`; `pnpm
install` com `--frozen-lockfile` **e** `--ignore-scripts`; `npm ci` com
`--ignore-scripts`. `npm install`, `pnpm add` e `yarn add` resolvem de novo e
não passam; `pnpm rebuild` e `npm rebuild` correm os *scripts* que
`--ignore-scripts` proibia, e também não.

> **Esta regra apanhou uma linha do próprio `Makefile`.** O `bootstrap` fazia
> `pip install --upgrade pip` — a única instalação do repositório que ia ao PyPI
> sem *hash*, a actualizar precisamente a ferramenta que impõe os *hashes*.
> Saiu. O `pip` que o `venv` traz chega para `--require-hashes`.

**Cada serviço de compose corre com `read_only: true`.** O que precisa de
escrever declara-o. O `postgres` e a `queue` não o tinham; passaram a ter, com
os sítios de escrita declarados (`volumes:` e `tmpfs:`), e foi verificado por
execução a 2026-10-12: os quatro contentores levantados (`postgres`, `queue`,
`gwy`, `agr`) deram `ReadonlyRootfs=true` e `healthy`; um `touch` na raiz falhou
com «Read-only file system»; uma tabela criada e uma chave escrita sobreviveram
a um `restart`.

O critério 4 fala dos «contentores», e os de produção ainda não existem: o
compose de produção é o KAM-076, que tem o mesmo critério (CA4) e herda esta
verificação sem mexer nela — ela lê todos os compose do repositório.

---

## 5. Lista de saídas por serviço

Cada serviço declara para onde pode sair. Negado por omissão.

```yaml
version: 1
servico: gwy
por_omissao: negar
destinos: []
```

Um destino tem `fqdn`, `porta`, `protocolo`, `razao` e `ticket`. O `fqdn` é um
nome em minúsculas: sem `*`, sem endereço IP, sem CIDR. Os serviços do monorepo
declaram em `services/<nome>/egress.yaml`; os de terceiros que só existem num
compose (`postgres`, `queue`), em `infra/egress/<nome>.yaml`; e qualquer outra
pasta com um Dockerfile, ao lado dele. Um `egress.yml` com outra extensão, ou
num sítio que não é o de nenhum serviço, é achado: seria lido por quem aplicar a
rede e não por este verificador.

Hoje as sete listas estão vazias, e é verdade: os cinco serviços são o esqueleto
do KAM-001 (`/healthz`), e a base e a fila estão numa rede `internal: true`.
Cada destino entra com o ticket que o introduz.

**O que isto é e não é.** É o contrato, e a prova de que existe para todos.
**Não é** a aplicação na rede: nada aqui impede um contentor de abrir uma
ligação. Isso é o proxy de saída do KAM-076 (CA3), que deve ler estes ficheiros.

---

## 6. Registo de licenças por versão, e guia de excepções

### 6.1 Política e registo são duas coisas

| | `ci/licenses.yaml` (KAM-002) | `ci/supply-chain/licencas.yaml` (KAM-067) |
|---|---|---|
| Diz | que licenças entram | que versão foi lida, com que licença, quando e de onde |
| Sobre | todas as dependências instaladas | os componentes com risco de licença nomeado no E4, e os das imagens |
| Lido por | `tools/sbom`, em cada PR, do disco | `tools/supply_chain/licencas.py` |

O registo é a mitigação que o E4 §5 pede para o risco «a licença desliza para
*open-core* mais restritivo»: *fixar versão MIT conhecida; manter registo de
licenças por versão*. São vinte componentes. As linhas que citam o E4 herdam a
data de consulta (2026-10-08) e o estado de verificação dele.

### 6.2 Os cinco estados

| Estado | Quando | O que o gate exige |
|---|---|---|
| `permitido` | a licença passa a política | — |
| `pendente_de_decisao` | travado por uma decisão aberta | `decisao: D#`, a que a política nomeia |
| `bloqueado` | está na lista de bloqueio | que `tools/blocklist.yaml` o bloqueie de facto |
| `excepcao` | licença negada, admitida por ADR | `excepcao_adr` com um ADR **que exista** (`docs/tecnica/00` §8 ou `docs/adr/`) e `nota` com a leitura |
| `nao_adoptado` | não está no repositório | `ligacoes`, e que não esteja mesmo: nem manifesto, nem imagem |

**Redis e Valkey estão `pendente_de_decisao`, com `decisao: D12`.** O Valkey é
`BSD-3-Clause`, que está na *allowlist*, e mesmo assim não pode registar-se como
`permitido`: a escolha entre os dois *é* a D12, e aprovar um pela licença
fechava-a pela porta de trás. O Valkey é a omissão do compose de
desenvolvimento, não uma escolha. A travagem é pelo nome do componente **e pelo
que ele liga**: rebaptizar o Redis e manter `imagem:redis` não o destrava, e
apagar a linha também não — os dois são componentes obrigatórios do registo.

### 6.3 Subir de versão obriga a reler a licença

Onde o registo tem `ligacoes` (`npm:hono`, `imagem:node`…), a versão fixada no
repositório tem de ser a `versao` do registo. Um PR do Renovate que suba o Hono
falha com `licenca-versao-diferente` até alguém reler a licença dessa versão e
actualizar `versao` e `data_verificacao`. É atrito de propósito, e só para os
componentes que estão no registo — as outras dependências são lidas do disco,
uma a uma, pelo gate 11.

### 6.4 Guia de excepções

**Uma dependência com licença proibida** (AGPL, BUSL, Elastic, SSPL, FSL, SUL,
GPL, LGPL, CC-BY-NC, CC-BY-SA — a lista é a de `ci/licenses.yaml`):

1. Escreve-se, ou emenda-se, um ADR que diga porque é aceitável e em que
   condições (como corre, o que não se modifica, o que não se distribui).
2. Entrada em [`ci/waivers.yaml`](../ci/waivers.yaml): `gate: 11`, `alvo` igual
   ao `purl`, `adr_ou_aprovacao: ADR-NNN`, razão e prazo (≤ 30 dias).
3. Se for um componente do registo, a linha passa a `estado: excepcao`, com
   `excepcao_adr` e `nota`.

> **Uma aprovação datada não chega para uma licença proibida.** O esquema dos
> *waivers* aceita `aprovacao:<quem>@<data>`, e até este ticket isso deixava uma
> BUSL entrar com a assinatura de uma pessoa. O critério 6 pede «excepção
> registada em ADR», e o gate 11 passou a recusar o resto — incluindo um
> ADR com o número 999, que tem a forma de um ADR e não é um
> (`tools/sbom/tests/test_excepcao_em_adr.py`). Para uma licença **por
> determinar** a aprovação continua a servir: resolve-se lendo-a, e quem a leu
> assina.

**Uma licença pendente de decisão** não se dispensa: fecha-se a decisão.

**Uma imagem sem *digest*** não tem excepção. Lê-se o *digest* e regista-se.

**Uma instalação fora do *lockfile*** não tem excepção. Passa a vir do
*lockfile*.

---

## 7. Quarentena e CI sem chaves

O `renovate.json5` já trazia, desde o KAM-001, `minimumReleaseAge: "7 days"`,
`automerge: false` e a excepção de `vulnerabilityAlerts` com revisores. O que
não havia era nada que falhasse se alguém os retirasse; agora há — no topo, em
qualquer bloco aninhado (`patch`, `npm`, `lockFileMaintenance`, `packageRules`)
e por *preset* (`:automergeAll`).

O Renovate lê **um** ficheiro de configuração. Um `renovate.json` posto ao lado
do `renovate.json5` pode ser o que ele lê (a documentação dele dá-lhe
precedência — INDÍCIO, lido pela revisão adversarial a 2026-10-12), pelo que
qualquer segundo ficheiro de configuração falha, tal como um `dependabot.yml`,
que é um segundo actualizador sem quarentena nenhuma.

**O que continua por provar: que o Renovate está a correr.** A configuração está
certa e protegida, e nenhum PR deste repositório foi aberto pelo Renovate
(os vinte primeiros são todos do mesmo autor). Sem um PR dele não se observa a
quarentena aplicada. Também é NÃO VERIFICADO que, com esta configuração, o
Renovate **retenha** o PR durante a quarentena em vez de o abrir com uma
verificação pendente: depende de `internalChecksFilter`, cujo valor por omissão
não foi lido da documentação na versão em uso.

O CI autentica-se por OIDC. `docs/ci.md` §6 dizia que «um grep por referências
ao cofre de segredos devolve zero»; a verificação `ci` é esse grep, a falhar,
sobre workflows e acções compostas, comentários incluídos, sem distinguir
maiúsculas e em qualquer uso do contexto (`toJSON(secrets)` conta).

**«Por OIDC» é hoje uma declaração, não um uso.** Os *jobs* pedem `id-token:
write` e nenhum passo se autentica em lado nenhum: não há registo, nem nuvem,
nem *deploy*. Retirar a permissão não falha nada, e não devia — o que o critério
proíbe são chaves estáticas, e essas é que se verificam.

---

## 8. O canário

`make supply-chain` não acaba no `check`. O segundo passo copia o repositório
para fora, confirma que a cópia está conforme, e aplica **59 defeitos, um de
cada vez** — retirar um *digest*, pôr `image: litellm:latest`, ligar o
`automerge`, apagar uma lista de saídas. Cada um tem de:

1. **aplicar-se**: se o texto que a mutação troca já não existe, o canário
   falha. Uma prova que deixou de se aplicar deixou de existir;
2. dar vermelho **pelas regras esperadas, e só por essas**: ser apanhado por
   outra regra é sorte, não cobertura.

A lista é código (`tools/supply_chain/canario.py`), não configuração, e
`MINIMO_POR_REGRA` prende quantas mutações cada regra tem de ter: uma lista
vazia falha com 27 erros, e não com «0 sobreviventes».

Só duas regras não têm mutação: `cosign-sem-binario` e `cosign-falhou`, que
dependem de existir ou não um binário no *runner*. Estão cobertas pela suite,
com executor injectado.

**A primeira versão do canário tinha 33 mutações, todas vermelhas, e não provava
o que parecia.** A revisão adversarial fez 86 mutações suas ao repositório e 78
passaram: as do autor cobriam as formas em que o autor tinha pensado. As 26 que
entraram depois são as formas equivalentes que a revisão encontrou
([`ANALISE-10`](analises/ANALISE-10-KAM-067-supply-chain.md) §2). Um canário
vale o que valerem as suas mutações, e quem escreveu o verificador é o pior
autor possível delas — a lição do gate 8, outra vez.

O caso semeado que o critério 1 nomeia — `image: litellm:latest` — é a primeira
mutação. Como PR real, deliberadamente vermelho, está em
[`ANALISE-10`](analises/ANALISE-10-KAM-067-supply-chain.md) §5.

---

## 9. O que não está feito, e porquê

| Critério | O que falta | Porque não se fez | Quem o pode fechar |
|---|---|---|---|
| 2 — cosign | `cosign verify` a correr contra uma imagem assinada e uma adulterada | Não há registo de contentores, nem imagem com assinatura publicada no repositório, nem `cosign` no *runner*. O módulo existe e **nunca correu contra o `cosign` real** | KAM-030 (LiteLLM), KAM-078 (gate 14) |
| 3 — SBOM por imagem | SBOM das camadas, guardado com o *release* e referido no manifesto da *tag* | Não há pipeline que construa nem publique imagens, nem *release* | KAM-078 (gates 14 e 18) |
| 7 — *flags* *Enterprise* | Teste de configuração para Medusa, Chatwoot e Meilisearch | Nenhum dos três está instalado, e os nomes das variáveis que activam as *flags* são NÃO VERIFICADOS. Um teste contra uma configuração que não existe, com nomes inventados, seria decoração | KAM-042, KAM-076 (CA8) |
| 8 — Renovate | Observar a quarentena aplicada | O Renovate não abriu nenhum PR neste repositório | Instalar a aplicação; depois, um PR dele |
| 4 — *lockfiles* e *runtime* | Uma decisão, não trabalho | As quatro cláusulas verificam-se (§4). Mas a letra diz «`npm ci --ignore-scripts`» e o repositório usa `pnpm install --frozen-lockfile --ignore-scripts`, que é o equivalente para um `pnpm-lock`; e «os contentores» de produção ainda não existem. A caixa fica por marcar até quem escreveu o critério dizer se a leitura serve | Quem ratifica o ticket; KAM-076 para os contentores de produção |

O que os outros critérios deixam de fora, e convém não ler como coberto:

- **Os contentores de produção.** O `read_only` está verificado no compose de
  desenvolvimento; o de produção é o KAM-076.
- **A aplicação do egress.** §5.
- **O alerta de CVE crítico** e **o relatório de imagens por *release*** (DoD):
  não há *release*, nem canal de alerta.

---

## 10. O que estas verificações não vêem

Fica escrito porque um gate que se julga completo é pior do que um que se sabe
parcial.

1. **A linha de comandos.** Um `docker build --build-arg NODE_IMAGE=…` ou um
   `KAMBA_QUEUE_IMAGE=… docker compose up` escritos à mão não estão em ficheiro
   nenhum.
2. **As acções do GitHub.** `actions/checkout@v5` é uma etiqueta que o dono do
   repositório pode mover. O critério 1 fala de `image:` e `FROM`; fixar acções
   por SHA de *commit* é o mesmo problema noutra forma, e **não está feito**.
3. **O conteúdo da imagem.** Um *digest* fixa os bytes; não diz o que está lá
   dentro. Os pacotes Debian das imagens de base não estão em registo nenhum.
4. **Imagens lançadas por código.** Um `docker run` (ou `podman`, `nerdctl`)
   num *script*, num `Makefile` ou num workflow tem de trazer um *digest* do
   inventário na própria linha; uma linha partida em várias, uma imagem numa
   variável, um `$(DOCKER) run` ou o SDK `docker` de Python escapam. Num
   ficheiro Python já declarado, um **segundo** `docker run` com outra imagem
   também: a declaração é por ficheiro.
5. **Instaladores que a lista não conhece.** `apt-get install`, `apk add`,
   `curl … | sh`, `go install`, `cargo install` e `gem install` não estão em
   `_INSTALADORES`. A lista cobre Python e Node, que é o que o repositório usa e
   o que o critério nomeia.
6. **Um ponto de arranque escrito noutra linguagem.** Um `entrypoint.py` que
   chame `subprocess.run(["pip", "install", …])` não é lido.
7. **O que o compose inclui de fora.** `extends:`, `include:`,
   `dockerfile_inline` e `additional_contexts` não são seguidos — são **achado**,
   e não silêncio. Um `include:` de um ficheiro que não seja YAML nem fale de
   `services:` não é visto.
7a. **Onde um serviço escreve.** `read_only: true` verifica-se; que o `tmpfs`
   ou o volume não estejam montados por cima de `/app` ou de `/usr/local`, não.
7b. **O registo de licenças contra o disco.** A licença escrita no registo não
   é comparada com a que o gate 11 lê do pacote instalado, e o texto do campo
   `ee` não é interpretado: só se exige que exista.
7c. **A rede.** `internal: true` na rede `data` é o que sustenta as duas listas
   vazias de `infra/egress/`; nada aqui falha se deixar de o ser.
8. **A idade do registo.** `data_verificacao` não pode ser futura, e nada a
   obriga a ser recente. Um limiar de validade seria um número inventado.
9. **O que o Renovate faz**, por oposição ao que o ficheiro lhe pede (§7).

---

## 11. Correr à mão

```bash
make supply-chain                        # check + canário
cd tools
python -m supply_chain check             # as seis verificações
python -m supply_chain imagens           # uma só
python -m supply_chain canario           # a prova por mutação
```

Precisa de `tools/` no `PYTHONPATH`, como as outras ferramentas. Não precisa de
`make bootstrap`: é só biblioteca padrão.

---

## 12. Controlo de versões

| Versão | Data | Alteração | Autor |
|---|---|---|---|
| 1.0 | Outubro 2026 | Emissão (KAM-067): imagens por *digest* com inventário, sem instalação em *runtime*, serviços só de leitura, lista de saídas por serviço, registo de licenças por versão, excepção de licença proibida só por ADR, quarentena e CI sem chaves a falhar, e canário de 33 mutações no gate 11. Quatro critérios por cumprir, nomeados. | Equipa KAMBÁ |
| 1.1 | Outubro 2026 | Depois da revisão adversarial ([`ANALISE-10`](analises/ANALISE-10-KAM-067-supply-chain.md)): o compose reconhece-se por falar de `services:` e o que não se lê é achado; leitor de Dockerfile corrigido (*here-document* falso, `ONBUILD`, nomes); instaladores reconhecidos pelo nome-base e não por padrão ancorado; cadeias de *scripts* e `scripts` do `package.json` seguidos; ADR da excepção tem de existir; componentes obrigatórios no registo; ficheiros-sombra do Renovate; canário de 59 mutações. Critério 4 passa a «por decidir». | Equipa KAMBÁ |
