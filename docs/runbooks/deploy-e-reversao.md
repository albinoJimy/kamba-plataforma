# Deploy por `release.lock`, *rolling* e reversão — procedimento de *release*

| Campo | Valor |
|---|---|
| Ticket | KAM-078 (`../../specs/EPIC-08_Topologia_Operacao.md`) |
| Âmbito | O caminho `merge → imagem assinada → staging → smoke → aprovação → produção rolling → verificação → tag`, e o que fazer quando a reversão automática não chega |
| Estado | **Proposta, nunca ensaiada contra um *host*.** As decisões de cada gate estão em `tools/release/` com ensaios; o *pipeline* de deploy que as chama não existe, porque não há *host* de *staging* nem de produção (D1, KAM-077), nem registo de contentores, nem número de teste da Meta |
| Fontes | `../tecnica/09_Topologia_Operacao_Escala.md` §6 e §7; `../../specs/01_Engineering_Standards_e_Handoff.md` §4 (gates 14 a 18) |
| Ferramenta | [`../../tools/release/`](../../tools/release/) — `python -m release <comando>` a partir de `tools/` |

> **Cada comando abaixo diz se correu, e contra quê.** «Correu na árvore» quer
> dizer que correu neste repositório, a 2026-11-25, sem *host*; nenhum correu
> contra um ambiente.

---

## 1. O caminho

| Passo | Gate | O que decide | Comando | Correu? |
|---|---|---|---|---|
| *Build* por *digest* | — | cada serviço `build:` do compose de produção tem um `@sha256` | o *pipeline* escreve `ci/release/construidos.json` | **não existe** |
| `release.lock` | — | o lock tem um *digest* por serviço, sem buracos | `make release-lock` | na árvore: **recusa**, 15 serviços `build:` sem *digest* |
| Imagem | 14 | *digest*, SBOM, `cosign verify`, crítica sem *waiver* | `make ci-14` | só nos ensaios |
| *Staging* + *smoke* | 15 | a guarda primeiro; depois 20 execuções, p95 ≤ 15 s; `paga` ≤ 60 s | `make smoke-guarda` | só nos ensaios |
| Aprovação | 16 | por cada PR da release, 2 revisores com escrita se é de dinheiro, segurança ou isolamento | `make ci-16 PR="<n> <m> ..."` | na árvore, contra o #275: **recusa**, 0 de 1 |
| *Rolling* | 17 | uma réplica de cada vez; reversão automática | sem alvo: falta o adaptador de *host* | só nos ensaios |
| Verificação | 18 | `/healthz`, taxa de erro, idade da fila < 2 min, sonda externa | entra no `tag` | só nos ensaios |
| *Tag* | 18 | SemVer, lock e SBOM arquivados, só com verificação verde | `python -m release tag ...` | só nos ensaios |
| *Lint* do *pipeline* | 18 | nenhum gate saltado sem ADR, aprovação ou *waiver* | `make ci-18` | na árvore: **1 achado**, §6.2 |

## 2. Antes do deploy: o lock

O `release.lock` é a lista de *digests* que se implanta, e gera-se **antes** do
deploy (o deploy é por *digest*). A *tag* SemVer só vem depois da verificação
pós-deploy — é a resolução do Contexto do bloco para a divergência entre o doc 09
§7 e o §4.

```sh
make release-lock KAMBA_COMMIT_SHA=<sha de 40> RELEASE_CONSTRUIDOS=ci/release/construidos.json
cd tools && python -m release --root .. lock diferencas ../ci/release/release.lock <lock anterior>
```

Ler o `diferencas` antes de avançar: é a lista exacta do que muda em produção. Um
serviço que muda e que ninguém esperava é para parar.

## 3. O *rolling*

Uma réplica de cada vez, por construção (`rolling.rolar`): **esvaziar →
implantar → esperar `/healthz` e métricas → retomar → a seguinte**. O GWY e os
*workers* têm duas réplicas; o prazo para ficar saudável é 60 s (*proposta*, o
mesmo da paragem graciosa). Só os serviços cuja imagem mudou entre os dois
locks são tocados.

**Durante o *rolling*, não se implanta à mão.** Uma segunda pessoa a mexer numa
réplica tira a garantia de «uma de cada vez», que é o que permite ao AGR
reexecutar nós sem efeito duplicado.

## 4. A reversão

### 4.1 Automática

Se uma réplica não fica saudável no prazo — ou se a plataforma rebenta a meio de
esvaziar, implantar ou retomar —, o `rolar` repõe a imagem do lock anterior nas
réplicas que já mudou, incluindo a que falhou, pela ordem inversa e uma de cada
vez. **Pára na primeira réplica que não volta**: continuar obrigava a esvaziar
réplicas que estão a servir, e com duas réplicas isso pode deixar o serviço a
zero. As que ficam por repor continuam na imagem nova **e a servir**. Mede quanto
demorou, desde que se esvaziou a réplica que falhou; o tecto do critério é
5 min (*proposta*). Três desfechos:

| Desfecho | O que quer dizer | O que fazer |
|---|---|---|
| `implantado` | todas as réplicas na imagem nova e saudáveis | seguir para a verificação pós-deploy (§1) |
| `revertido` | voltou ao lock anterior sem intervenção | **não** tentar outra vez a mesma release; abrir o achado com o registo do `rolar` |
| `reversao_falhou` | uma réplica não voltou saudável, ou um serviço novo não tinha para onde voltar; a reversão parou aí | §4.2, agora |

### 4.2 Quando a reversão automática não chega

É P1. **Não se volta a correr o `rolar`**: o estado é misto, e uma segunda passagem
calcula as diferenças contra um lock que já não descreve o que está a correr.

1. Ler o registo do `rolar` (`reposicao-falhou <réplica>`, `sem-anterior <réplica>`,
   `excepcao ...`). Ele diz que réplicas estão em que imagem, e onde a reversão parou:
   as que vêm **antes** dessa linha na ordem inversa ainda estão na imagem nova.
2. Para cada réplica listada, reimplantar à mão a imagem do lock anterior, **pelo
   *digest*** que está no ficheiro, e não por etiqueta. **Comando: não existe** —
   depende do *host* e do adaptador (§7).
3. Se a réplica não arranca nem com a imagem anterior, o problema não é a release:
   é o *host*, a base ou um segredo. RB-K08 para a base, RB-K07 para segredos.
4. Fechar com o *post-mortem*, e com o *lock* que ficou a correr escrito nele.

## 5. O *smoke* e a guarda

A guarda (`smoke.guardar`) corre **antes** de qualquer envio, e não há caminho do
*smoke* que envie sem passar por ela. Aborta quando:

- o ambiente alvo é `prod`, ou o `meta.modo` dele é `producao`, ou não está declarado
  em `infra/envs/<ambiente>/env.yaml`;
- o projecto de segredos é o de `prod` (lido do `infra/envs/prod/env.yaml`), ou não é
  o que o próprio ambiente declara — comparados sem maiúsculas nem espaços;
- o número (comparado pelos últimos nove algarismos, para que `+999…`, `00999…` e o
  formato nacional sejam o mesmo) ou o `phone_number_id` estão nas listas de produção;
- em `staging`: **falta alguma das duas listas de produção**, ou vem vazia ou
  malformada (sem elas não se prova que o alvo não é produção), ou o alvo não diz o
  seu `phone_number_id`;
- em `dev`: o número sai do intervalo fictício `999…` do `tools/meta-sim`, ou o
  anfitrião da base da Graph é da Meta.

A lista de produção vem do projecto `prod` do cofre, lida pelo *job* com um *token*
só de leitura, e passa por ficheiro (`SMOKE_PRODUCAO=`). **Nunca se escreve no
repositório**, que é público.

Falhas da Meta classificam-se `inconclusivo`, nunca `verde`; menos de 20 execuções
medidas também. Uma resposta errada é `vermelho` mesmo com a Meta em baixo nas
outras.

## 6. Proposta ao fundador: a ligação ao *pipeline*

**Nada disto está aplicado.** Os *workflows* e o *ruleset* são do fundador; o que
segue é o texto exacto que faltaria, e as decisões que o precedem.

### 6.1 Gate 18 no CI de PR

É o único dos cinco que não precisa de *host*, registo nem Meta. O *job* novo, ao
lado dos outros em `.github/workflows/ci.yaml`:

```yaml
  gate-18-pipeline:
    name: "gate 18 — lint do pipeline"
    runs-on: ubuntu-latest
    timeout-minutes: 5
    permissions:
      contents: read
    steps:
      - uses: actions/checkout@v5
      - uses: actions/setup-python@v6
        with:
          python-version: ${{ env.PYTHON_VERSION }}
      - run: make ci-18
```

e, no agregador `gates-em-ambito`, `gate-18-pipeline` no `needs` e o `esperados`
somado de um. Isto **acrescenta um contexto exigido** ao *ruleset* de `main`, se
for para bloquear. **Hoje fica vermelho** — §6.2 —, pelo que a ordem é: decidir o
§6.2, depois ligar.

### 6.2 O achado que o gate 18 dá hoje

```text
.github/workflows/ci.yaml:339: o gate 5 (job `gates-reservados`) tem
`continue-on-error: true` sem ADR, aprovacao nem waiver registado
```

O gate 5 reservado não bloqueia desde o KAM-002, e o comentário por cima dele
cita o `ci/waivers.yaml` como válvula — mas não há *waiver* nenhum, e a regra
transversal do §4 pede ADR ou aprovação registada. O gate 13 da pesquisa, que
também não bloqueia, passa: cita o ADR-L012. Duas saídas, e a escolha é sua:

| Opção | O que é | Custo |
|---|---|---|
| A | um ADR local que regista «os gates reservados correm sem bloquear até o ticket que os cria», citado no comentário do *job* | uma decisão escrita, uma vez |
| B | um *waiver* em `ci/waivers.yaml` (`gate: 5`, `alvo: gates-reservados`) | renova-se de 30 em 30 dias, com aprovação nova |

Uma `# aprovacao:<quem>@<data>` solta no comentário **não serve**: a primeira versão do *lint* aceitava-a, e a revisão adversarial mostrou que é mais fraca do que o *waiver* — sem prazo, sem autor validado, e para qualquer gate, os que não admitem dispensa incluídos. Uma aprovação regista-se no `ci/waivers.yaml`.

### 6.3 Gates 14, 16 e 17: um *workflow* de *release*

Não cabem no CI de PR: correm depois do *merge*, contra o *digest* construído.
O esqueleto, que **nunca correu** e depende do registo e do *host*:

1. em `push` para `main`: *build* de cada serviço `build:` do compose de produção,
   *push* por *digest*, `ci/release/construidos.json` escrito pelo passo;
2. `cosign sign` *keyless* com `permissions: id-token: write` (OIDC, sem chave
   estática — a regra `chave-estatica-no-ci` do gate 11 recusa um `secrets.*`);
   SBOM CycloneDX e varrimento CycloneDX por imagem em `ci/release/artefactos/`;
3. `make release-lock`, `make ci-14 COSIGN_IDENTIDADE=<o workflow que assinou>`;
4. deploy em *staging*, `make smoke-guarda`, o *smoke*;
5. `make ci-16 PR=<n>` (precisa de um *token* que leia as revisões do PR; que o
   `GITHUB_TOKEN` com `pull-requests: read` baste é **NÃO VERIFICADO**) e um
   `environment` do GitHub com revisores obrigatórios para `prod`;
6. o *rolling* (§3), a verificação pós-deploy, e o `tag`.

E três decisões que vêm antes do primeiro passo: o **registo** de contentores, o
***scanner*** de imagens (com licença a registar em `ci/licenses.yaml`), e as
**etiquetas** `dinheiro`, `seguranca` e `isolamento` no repositório — medido a
2026-11-25, não existe nenhuma. Sem elas o gate 16 decide só pelos caminhos do
estrato `critico` do `ci/thresholds.yaml`, que é a segunda fonte que o
`aprovacao.py` já lê.

## 7. O que não está feito, e porquê

| O quê | Porque | Credor |
|---|---|---|
| Adaptador de *host* do `rolar` (esvaziar, implantar, sondar uma réplica) | Não há *host*; um adaptador que nunca correu contra um seria uma afirmação sobre um sistema que ninguém viu | KAM-077 (D1, D12) |
| O ensaio de 1.500 mensagens a 5 msg/s sob *rolling* | A conta está feita (`rolling.reconciliar`, `make ci-17`); o tráfego é do simulador do KAM-024 contra o *host* | KAM-077 |
| O fio ponta a ponta contra o `meta-sim` | O `worker-canal` monta o cliente da Graph sem base configurável (`clienteDaGraphPorCanal({ cofre })`), pelo que uma resposta sai sempre para `graph.facebook.com`. Tornar a base configurável é uma porta de saída nova — eixo de segurança, decisão a tomar antes | coordenação / fundador |
| Gate 15 ao número real (≤ 15 s, p95 de 20) | Não há número de teste da app Meta de *staging* | KAM-102 |
| `paga` via sandbox ProxyPay | Credenciais do sandbox | KAM-056 |
| Alerta para `reversao_falhou` | Não há *pipeline* que o emita | quem ligar o §6.3 |

## 8. Controlo de versões

| Versão | Data | Alteração | Autor |
|---|---|---|---|
| 0.1 | Novembro 2026 | Primeira versão, na preparação do KAM-078 (lote 24): o caminho, o *rolling*, a reversão automática e a manual, a guarda do *smoke*, e a proposta de ligação ao fundador. Nunca ensaiado contra um *host* | Equipa KAMBÁ |
