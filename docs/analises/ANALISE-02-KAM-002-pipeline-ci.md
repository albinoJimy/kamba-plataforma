# ANÁLISE-02 — Revisão adversarial do KAM-002 (pipeline de CI)

| Campo | Valor |
|---|---|
| Ticket | KAM-002 — Pipeline de CI base: *gates* fail-closed |
| Ramo | `feature/KAM-002-pipeline-ci-gates` |
| *Baseline* revista | `654ab06` |
| Data | Outubro 2026 |
| Método | Execução, não leitura: cada achado foi reproduzido com um comando |
| Veredicto da revisão | **Não aprovado** — 4 bloqueantes, 8 maiores, 12 menores |
| Estado | 4 bloqueantes corrigidos; 6 maiores corrigidos e 2 registados; 12 menores triados; **1 achado não se confirmou** |
| Verificação final | Os sete *required checks* verdes no PR #4 depois das correcções |

A revisão foi conduzida por um agente independente, que recebeu os requisitos e
o código e **não** as justificações de quem o escreveu. Produziu 24 achados.
Este documento registra todos, com o que se fez a cada um — incluindo os que se
decidiu **não** corrigir, e porquê.

> **A lição central, e vale mais do que a lista:** os quatro bloqueantes foram
> todos encontrados a **correr** coisas, nenhum a ler. Três deles eram *gates*
> satisfeitos pela razão errada — passavam, e não por o repositório estar bem.
> O quarto era metade de um *gate* que não existia e não estava declarada.

---

## 1. Bloqueantes

### B1 — O *gate* 4 nunca olhou para o resultado dos testes

`Makefile:coverage-node`, `Makefile:coverage-python`

Cada *suite* terminava em `|| true` (Python) ou `|| echo "aviso"` (Node), com
`>/dev/null 2>&1` por cima. O *gate* chama-se «unit e cobertura» e media só a
segunda metade. **A *suite* do `lint_refs` esteve vermelha desde o *commit* que
criou o alvo (`3dc1e5b`) e o *gate* passou verde em sete PRs** — incluindo nos
seis que existiam para provar que os *gates* bloqueiam.

A causa do teste vermelho fecha o círculo: o `docs/ci.md` passou a citar
`D14`…`D29` ao explicar o problema dos intervalos de prazos, e o teste
`test_os_avisos_sao_so_prazos` fixava o conjunto `{D0, D30, D60}`. O *commit*
que escreveu a documentação quebrou o teste que o *commit* anterior escrevera.

**Corrigido.** Os dois alvos correm todas as *suites*, guardam o registo de cada
uma em `ci/coverage/*.log`, escrevem o LCOV e **depois** falham se alguma foi
vermelha. O `make test-py` passou a correr as quatro *suites* de `tools/` (antes
corria só `lint_arch`: as três do KAM-002 não eram corridas por nenhum alvo que
pudesse falhar). O teste frágil passou a verificar a propriedade — que nenhum
token avisado foi inventado por expansão, lendo a linha de origem — em vez de
congelar uma lista. Quatro guardas novos em `test_makefile.py` recusam o
`|| true` sobre `node --test` e `unittest discover`; verificados contra o
`Makefile` anterior, três dos quatro ficam vermelhos.

### B2 — Metade do *gate* 11 não existia, e não estava declarada

`tools/sbom/`, `docs/ci.md` §3

O critério de aceitação diz, por escrito, que o *gate* 11 «falha com
vulnerabilidade crítica sem excepção registada». Não havia varrimento nenhum:
nem `pnpm audit`, nem `pip-audit`, nem consulta a OSV/GHSA. Pior do que faltar,
nada o dizia — a palavra «vulnerabilidade» não aparecia no `docs/ci.md`, e o
`ci/waivers.yaml` dizia ao leitor que `alvo` podia ser «uma CVE», afirmando uma
capacidade inexistente.

**Corrigido.** `tools/sbom/vulns.py` consulta a OSV por `purl` — uma fonte para
os dois ecossistemas, sem credenciais, o que encaixa no «sem chaves estáticas».
Falha com `CRITICAL` sem *waiver* que nomeie o `purl` ou o identificador.
**Fail-closed inclui a rede:** se a OSV não responder, o *gate* falha; para
trabalho local existe `KAMBA_SEM_REDE=1`, que salta o varrimento dizendo-o em
voz alta e que o CI nunca define.

Verificado a correr, e não por inspecção: `lodash@4.17.11` e `django@3.0.0`
devolvem 48 vulnerabilidades, 5 `CRITICAL`, entre as quais a
`GHSA-jf85-cpcp-j695`. Sobre os 76 componentes instalados do repositório: zero.

### B3 — O *gate* 9 não via a forma mais comum de segredo que existe

`tools/scan_secrets/patterns.py`

O padrão `atribuicao` usava `\b(?:…|token|password|…)\b`. O `_` é caractere de
palavra, pelo que **não há fronteira `\b` entre `_` e a palavra**:
`POSTGRES_PASSWORD=`, `META_ACCESS_TOKEN=` e `AWS_SECRET_ACCESS_KEY=` não batiam
em nada. É a forma dominante de variável de ambiente.

E o `.env.example` deste repositório tem exactamente `POSTGRES_PASSWORD=`. A
área permitida para esse ficheiro e o *placeholder* `mude-me-localmente` **nunca
foram exercidos**: o *gate* passava nesse ficheiro por não o saber ler, não por o
permitir. Um comentário no canário documentava a limitação como se fosse
aceitável.

**Corrigido.** A fronteira passa a ser o início de linha ou um caractere fora do
identificador, com prefixo e sufixo opcionais. Seis casos novos no canário,
incluindo os três acima. O comentário que normalizava o defeito foi reescrito —
e continha, ele próprio, um caractere de *backspace* literal, resíduo de um
*script* que colapsou uma barra invertida; varrido o resto do repositório, era o
único.

### B4 — Uma linha com mais de 4096 caracteres saltava o *gate* 9 inteiro

`tools/scan_secrets/scanner.py`

`if len(linha) > 4096: continue`, com um comentário a dizer «não se varre, **e
diz-se**». Não se dizia nada: nem aviso, nem contador. Era a evasão mais barata
que havia — acrescentar espaços — e não era só adversarial: um ficheiro gerado ou
um `.env` mal formatado chega aos 4096 caracteres por acidente e deixava de ser
varrido.

**Corrigido.** As linhas longas varrem-se em janelas de 4096 com 512 de
sobreposição (maior do que o maior segredo procurado, para um valor partido ao
meio não escapar às duas), com deduplicação. Três testes: segredo depois de 4596
caracteres, segredo a cavalo da fronteira, e não-duplicação.

---

## 2. Maiores

| # | Achado | Estado |
|---|---|---|
| M1 | **O *gate* 11 ficava verde sem nada instalado.** A guarda era `if not recolher(raiz)`, e `recolher` inclui os 9 pacotes do monorepo, que vêm dos `package.json` versionados: a lista nunca estava vazia e o *gate* dava verde com **zero** terceiros examinados. O subcomando `licenses` — o que o `make ci-11` usa — não tinha guarda nenhuma. | **Corrigido.** `declaradas_e_nao_instaladas()` compara contra o que está declarado (directas de cada importador do *lockfile* + *pins* dos `.in`), e corre para os três subcomandos. Detectou, ao ser escrita, que o `.venv` desta máquina estava vazio. |
| M2 | **Os SBOM não validavam contra o esquema CycloneDX 1.6:** 13 componentes com `license.id: "UNLICENSED"`, que não é identificador SPDX. | **Corrigido.** Uma cadeia fora da enumeração vai em `license.name`. Não se vendoriza a enumeração inteira (826 entradas, e o *gate* corre *offline*): falha-se para o lado da validade. Dois testes, um deles sobre os SBOM reais. |
| M3 | **Os *placeholders* do *gate* 9 comparavam-se por *substring*.** `sk-proj-…redacted` (prefixo publicado da OpenAI, 50 caracteres) era dispensado por acabar em `redacted`; `unknown` dispensava qualquer valor que o contivesse. | **Corrigido.** Igualdade, depois de retirar delimitadores. E as classes `chave_api`/`chave_privada` não consultam a lista: o prefixo é a prova. |
| M4 | **Três das quatro áreas de `ci/secrets-allow.yaml` declaravam classes inexistentes** (`placeholders`, `exemplos`) e por isso não permitiam nada. O ficheiro dizia que a documentação podia mostrar formas de chave; não podia. | **Corrigido.** `Permissoes.ler` recusa uma classe fora de `CLASSES`; as três áreas passaram às classes reais. **O teste que devia ter apanhado isto existia** — e a sua lista de aceitáveis tinha sido alargada com `{"placeholders", "exemplos"}` para o fazer passar, abençoando exactamente os nomes que existia para recusar. |
| M5 | **O *job* que apanha um *gate* `skipped` não era *required check*,** logo não podia bloquear nada — e o GitHub dá um *required check* por satisfeito quando o *job* é saltado. A lógica era negativa (excluía três resultados), pelo que um `result` novo passaria. | **Corrigido.** `gates do KAM-002` acrescentado aos *required checks* (sete agora). Lógica positiva: exige `success` em todos **e** conta seis, para um *gate* que desapareça do `needs` não desaparecer da verificação. O `cancel-in-progress` passou a aplicar-se só a PRs. |
| M6 | **Cinco formas de citar um `KAM-NNN` inexistente sem o *gate* 3 dar por isso:** extensão fora da lista (21 dos 231 ficheiros nunca varridos, incluindo os *hooks* que já citam `KAM-002`), bloco de código, **cerca aberta e nunca fechada** (cega o resto do ficheiro), ficheiro sem extensão, e `KAM‑999` com hífen tipográfico ou `KAM-0999` com quatro dígitos. | **Corrigido, menos um.** A lista de extensões passou a lista de **exclusão** (varre-se tudo o que o git segue e descodifique; 210 → 236 ficheiros, 7028 referências, 0 inválidas, medido no CI). Cercas desequilibradas desligam a dispensa em vez do varrimento. Hífen U+2011/U+2013 e quatro dígitos entram no padrão. **Não corrigido:** `kam-999` em minúsculas — apanhá-lo produziria falsos positivos em identificadores de código; fica como limite escrito. |
| M7 | **O SBOM por serviço omite os pacotes do *workspace* que o serviço carrega** e nunca atravessa um `link:`. O `services/gwy` declara `@kamba/core-ts`, os testes carregam-no, e não aparece no seu SBOM. No dia em que `core-ts` tomar uma dependência de terceiros, ela não aparecerá no SBOM de nenhum dos quatro serviços. | **Registado, não corrigido.** É trabalho real na travessia do *lockfile*. Ficha em `docs/ci.md` §7 e ticket próprio. Não afecta o veredicto de licenças nem de vulnerabilidades, que correm sobre o fecho completo (`kamba.cdx.json`). |
| M8 | **O *gate* 9 varre a árvore, não o que o PR acrescenta à história.** Um segredo posto no *commit* A e retirado no B passa, e entra no `main` com o *merge*. É o cenário que o próprio `docs/ci.md` usa para justificar o *pre-commit*. | **Registado, não corrigido.** Precisa de uma segunda passagem sobre os *blobs* novos (`git rev-list base..head`) e de plumbing no *workflow*. Ficha em `docs/ci.md` §7 e ticket próprio. |

---

## 3. Menores — triagem

**Corrigidos:**

- A *allowlist* de licenças tinha `MIT-0`, `Unlicense` e `CC0-1.0` acrescentadas
  sem razão escrita e sem uso (medido: nenhuma dependência as usa). Toda a
  entrada é uma regra de bloqueio, e o DoD pede dois revisores para as alterar.
  Removidas; a `CC0-1.0` não é sequer uma licença, é uma renúncia de domínio
  público. A *allowlist* desceu de 13 para 10.
- `ci_gate_reservado` ignorava o `alvo` do *waiver*: um *waiver* cujo alvo era um
  pacote npm dispensava o *gate* 5 inteiro. Agora só `alvo: pipeline` (ou o nome
  do *gate*) dispensa um *gate* reservado.
- `python -m sbom --out ci/sbom` — o exemplo do próprio *docstring* — rebentava
  com `ValueError: not in the subpath`. Resolvido contra a raiz.
- `ci/coverage/` não estava no `.gitignore`, ao contrário de `ci/sbom/`.
- Duas afirmações sem suporte, corrigidas: a classe `canario` que nunca existiu
  (README do canário) e «os nove pacotes» contra «os sete `package.json`» (dois
  documentos a discordar).
- **A terceira não se confirmou, e o erro foi da revisão.** O achado dizia que
  «99 componentes, 90 permitidas» no `docs/ci.md` §8 não reproduzia, por ter
  medido 92/83. Num `pnpm install --frozen-lockfile` limpo — o que o CI faz — são
  99 e 90, verificado no *run* do PR. Os 92 eram de uma árvore de trabalho com
  instalações parciais por cima. Fica registado porque **um revisor também
  produz achados errados**, e aceitar este sem medir teria substituído um número
  certo por um errado. A §8 passou a dizer que os números são os do CI, e
  porquê.
- O *ruleset* era configuração sem espelho no repositório. Exportado para
  `.github/rulesets/main.json`, com um README que diz o que o ficheiro **não**
  faz: é espelho, não fonte.

**Registados e não corrigidos** — em `docs/ci.md` §7, cada um com a razão:

- **Cobertura Node só mede ficheiros carregados.** Do lado Python,
  `coverage run --source=.` mede o que não é importado; do lado Node,
  `--experimental-test-coverage` não. **Nenhuma** quantidade de TypeScript sem
  testes move o número, porque o denominador não cresce. `--test-coverage-include`
  resolve e muda o valor medido, pelo que entra com medição própria.
- **Sete chaves de configuração que nenhum código lê** (`arredondamento`,
  `desconhecidas.politica`, `expressoes.and/or/with`, `prazos_conhecidos`,
  `regra`). Um ficheiro que descreve regras que o código não lê é pior do que não
  as descrever: alguém vai editá-lo a pensar que alterou a política.
- ***Waivers* que passam e não deviam:** data de aprovação impossível
  (`@9999-99-99`) aceita, prazo de 30 dias contado de hoje e não da criação (não
  há `criado_em`, pelo que um *waiver* renova-se para sempre), chaves
  desconhecidas aceitas em silêncio. E `GATES_COM_WAIVER` não inclui os *gates*
  14 e 18, que a §5 diz que consomem este esquema.
- **`kamba_yaml` tem dois erros de leitura silenciosos:** um `>-` como primeira
  chave de item de lista engole as chaves seguintes; um item de lista não citado
  com `:` torna-se um mapa. O módulo argumenta que a recusa larga é o que o torna
  confiável — e estes dois casos são exactamente o contrário.
- **O critério de *flags* de edição *enterprise*** que o `docs/tecnica/09` §7
  atribui ao *gate* das licenças (`rbac`/`auth-oidc` Medusa, `enterprise/`
  Chatwoot, `ee/` Langfuse) não está implementado — e é dessa linha que o
  `docs/ci.md` herda o dono do *gate* 11. Fica para o ticket que instalar esses
  componentes: hoje não há o que verificar.
- **`footerTokens` alterou uma regra do KAM-001 só de um lado.** O
  `commitlint.config.cjs` continua com o detector largo do
  `conventional-commits-parser`; o Python passou a uma lista fechada de 16
  tokens. A mensagem de *commit* afirmava que as duas vias se aproximavam, sobre
  o comportamento de uma biblioteca de terceiros, sem demonstração. A afirmação
  é retirada; a divergência fica registada.
- **O canário satisfazia a letra do CA ao contrário** — e isto passou a
  corrigido. O critério diz que um canário numa *fixture* **falha** o PR, e a
  implementação permite-o exactamente aí. A leitura escolhida é defensável («nem
  as *fixtures* são passe livre»), mas a prova de que o *gate* apanha o canário
  vinha de um teste unitário que durante sete PRs não era corrido por nada que
  pudesse falhar. O `make ci-9` passou a copiar o canário para fora da área e a
  exigir nove achados ou mais; dá 17. A leitura fica escrita em `docs/ci.md` §3.
- **`cancel-in-progress`, `strict_required_status_checks_policy: false`,
  comparação de `pendentes_de_decisao` por *substring*, `proprios` por nome
  exacto em qualquer ecossistema, e `fnmatch` sensível à caixa em Linux e não em
  Windows** — notas sem acção, todas de falha fechada ou sem consequência hoje.

---

## 3b. Um achado que não foi da revisão

A verificação local de `make check` + `make ci` num contentor limpo — redundante,
porque o CI já tinha corrido — encontrou uma coisa que nem a revisão nem o CI
podiam encontrar: **sem `make bootstrap`, os alvos que usam `pnpm` morriam com
`pnpm: command not found` e código 127.** O `pnpm` vem do Corepack, que o
`bootstrap` activa; no CI o `bootstrap` corre sempre, e por isso o caminho de
erro nunca era exercido.

Não é um defeito de *gate*, é uma mensagem que não diz o que fazer num ficheiro
que em todos os outros sítios diz — o `coverage-python` já tinha a guarda certa
para o `.venv`. Entra um alvo `exige-pnpm` como pré-requisito de `build`,
`test-ts` e `typecheck`, verificado num contentor com o Corepack fora do `PATH`.

Fica aqui porque é a terceira vez nesta sessão que a mesma coisa acontece: **o
que se corre encontra o que a leitura não encontra**, e cada ambiente novo
encontra o que o anterior não podia.

---

## 4. Categorias sem achados

Registadas porque a ausência também é informação:

- **Escopo invadido: nada.** Sem *deploy*, sem `cosign`, sem *digests* de
  imagem, sem quarentena, sem SAST, sem *eval golden*. As alterações a ficheiros
  do KAM-001 são colaterais justificadas, com uma excepção registada acima
  (`footerTokens`).
- **Erros que impedem o código de correr: nada nos *gates*.** As quatro *suites*
  correm, os alvos estão todos em `.PHONY`, as continuações dentro de aspas
  simples estão corrigidas, e `${…}` está escapado onde é do *shell*.
- **O *gate* 3 lê os conjuntos das fontes canónicas** e levanta em vez de
  devolver vazio quando a fonte falta.
- **O *gate* 4 recusa, de facto, um ficheiro medido que nenhum estrato
  classifique.** O que escapa é o que nunca chega a ser medido — ver acima.

---

## 5. Controlo de versões

| Versão | Data | Alteração | Autor |
|---|---|---|---|
| 1.0 | Outubro 2026 | Emissão: 24 achados da revisão adversarial do KAM-002, com disposição de cada um. | Equipa KAMBÁ |
| 1.1 | Outubro 2026 | Renumerada de 01 para 02 e movida de `analises/` (raiz) para `docs/analises/`: o sítio canónico é este desde o KAM-128, e já lá existia uma `ANALISE-01`. O epic citava um caminho que não existia. | Equipa KAMBÁ |
