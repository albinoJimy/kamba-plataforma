# *Rulesets* de `main` — o que o GitHub aplica, em ficheiro

O `main.json` é a exportação do *ruleset* `main: gates fail-closed do KAM-002`,
que é a peça de que toda a propriedade *fail-closed* depende: sem ele, os seis
*gates* correm e reportam, e nada impede o *merge*.

**Porque está aqui.** O *ruleset* é configuração, não código: vive na API do
GitHub, altera-se sem PR, e nada no repositório o descrevia. Quem quisesse saber
quais são os *required checks* tinha de ter acesso de administração e saber o
`id`. Exportado, lê-se num *diff* como qualquer outra regra de bloqueio — e uma
alteração feita na interface aparece como divergência face a este ficheiro.

## Esta árvore vive em dois repositórios, e a política tem de valer nos dois

| Repositório | O quê | *Ruleset* |
|---|---|---|
| `albinoJimy/kamba` | privado, a origem | existe, `id` **24879081** |
| `albinoJimy/kamba-plataforma` | **público, e é onde os PR são abertos e o CI corre** | existe, `id` **25359475** — criado a 2026-10-18, cópia do privado |

**Isto não é um detalhe de arrumação: foi um defeito a sério.** A primeira
versão da verificação nomeava um repositório só — o privado. O `main.json`
viaja na árvore que é empurrada para os dois, e corrida de um clone do
**público** a verificação ia ler o *ruleset* do **privado**, imprimia
«conforme» e saía 0, dentro de um repositório sem protecção nenhuma. É a frase
que está no bloco do ticket, virada do avesso: um ficheiro que parece ser a
fonte e não é engana melhor do que a ausência dele — e pior ainda com uma
máquina a dizer que está certo.

Por isso [`ci/ruleset.yaml`](../../ci/ruleset.yaml) tem uma **lista de alvos**,
e o `make ruleset` corre sobre todos. **Verde só quando todos estão conformes.**

**O *ruleset* do público existe desde 2026-10-18, e o `id` ficou escrito a
2026-11-07.** Até lá o alvo dava `repositorio-sem-ruleset`, vermelho de
propósito. Hoje dá vermelho por outra razão, e é uma razão melhor: a
verificação passou a comparar política em vez de a dar por ausente — e
encontrou uma divergência que ninguém encenou.

> **A divergência medida a 2026-11-07, e fechá-la é acto do fundador.**
> `rules.pull_request.require_extra_approval_for_unattributed_changes` está a
> `true` no espelho e no `albinoJimy/kamba` (`id` 24879081), e a **`false`** no
> `albinoJimy/kamba-plataforma` (`id` 25359475). **Os dois *rulesets* são iguais
> em tudo o resto**, parâmetro a parâmetro: os sete contextos, `bypass_actors`
> vazio, `enforcement: active`, `conditions`, `name`, `target` e as quatro
> regras.
>
> **O lado fraco está no repositório que importa** — o público é onde os PR são
> abertos e onde o CI corre. E `required_approving_review_count` está a **0** nos
> dois (ver a nota no fim deste ficheiro), pelo que este é hoje o único
> parâmetro do bloco `pull_request` em que os dois alvos não dizem o mesmo.
> *O efeito exacto deste campo com a contagem a 0 não foi medido por execução;
> o que está medido é o valor nos três sítios.*
>
> Resolve-se por **um** dos dois caminhos do §«Quando a verificação dá vermelho»,
> e **os dois são acto do fundador**: repor o GitHub, pondo o público a `true`
> (caso 2), ou — se o `false` foi deliberado — actualizar o espelho e escrever
> porquê no PR (caso 1). **O que não se faz é baixar o espelho para calar o
> vermelho**, pela mesma razão que vale para `bypass_actors`: o ficheiro não é
> autoridade para enfraquecer política. Quem executou o KAM-137 está impedido
> dos dois.

**O que a volta fechada faz, e o que continua a não fazer.** O ficheiro continua
a ser um espelho e não a fonte: editá-lo **não** altera o GitHub, e alterar o
GitHub **não** o actualiza. O que o KAM-137 acrescentou é a **detecção**: o
`make ruleset` lê o *ruleset* efectivo da API, compara-o com este ficheiro e
falha quando divergem — nos dois sentidos, e também quando não consegue ler.

O que isto **não** é, dito sem rodeios:

- **não é um *gate* de PR**, e não corre no CI deste repositório. A razão está
  medida em [`ADR-L003`](../../docs/adr/ADR-L003-verificacao-do-ruleset.md): a
  API dos *rulesets* exige a permissão `administration`, que o `GITHUB_TOKEN`
  das Actions não tem, e qualquer outro *token* obrigaria a uma referência
  `secrets.*` num *workflow* — que é exactamente o que a regra
  `chave-estatica-no-ci` do *gate* 11 recusa;
- **não repõe nada.** A credencial é de leitura (`administration: read`) e o
  módulo não tem nenhum caminho de escrita **dos que a guarda de
  `tools/ruleset_check/tests/test_guarda_de_escrita.py` reconhece** — verbos de
  escrita em literais, `--method`/`-X`, comandos do sistema, `subprocess` fora
  de `gh api`, e pedidos com corpo; o que essa guarda garante, e o que não
  garante, está escrito no topo dela. A reposição é manual, e está no
  §«Quando a verificação dá vermelho» abaixo;
- **só corre quando alguém a corre.** Entre execuções, o espelho pode envelhecer.
  É a troca que o ADR assume, e está escrita lá.

## Como se corre a verificação

```bash
make ruleset
```

Precisa de uma credencial com `administration: read` no porta-chaves do `gh`
(`gh auth login`). Onde não houver `gh` — o contexto fora destas Actions, se
vier a existir —, `make ruleset TRANSPORTE=http` com `KAMBA_RULESET_TOKEN` no
ambiente. **Onde ela vive, quem a pode usar, como se roda e o que acontece se
for comprometida está no
[`ADR-L003`](../../docs/adr/ADR-L003-verificacao-do-ruleset.md).**

Saída **0** = todos os alvos aplicam o que o ficheiro diz; **1** = pelo menos um
diverge, com cada divergência nomeada; **2** = não se conseguiu verificar (sem
`gh`, sem credencial, `403`, API em baixo). **O 2 é vermelho e não verde**: um
verificador que passa quando não consegue verificar é um verificador que mente —
a mesma regra que o *gate* 11 aplica à OSV.

Um repositório **sem *ruleset* nenhum** não é um 2: a leitura correu, e a
resposta foi que a política não está aplicada ali. Isso é **1**, com a regra
`repositorio-sem-ruleset`.

O que se compara está escrito, campo a campo, em
`tools/ruleset_check/comparador.py`: `enforcement`, `name`, `target`,
`conditions`, as quatro regras com os parâmetros de cada uma (os sete contextos
incluídos), e `bypass_actors` **vazio**. Os campos que a API devolve e que não
são política — `id`, `node_id`, `source`, `source_type`, `created_at`,
`updated_at`, `current_user_can_bypass`, `_links` — ficam de fora, cada um com a
razão escrita. Um campo de topo que a API passe a devolver e que não esteja em
nenhuma das duas listas **falha**.

Que *ruleset* se verifica e contra que ficheiro está em
[`ci/ruleset.yaml`](../../ci/ruleset.yaml).

## Quando a verificação dá vermelho

**Não se decide no momento.** São dois casos, e só dois:

1. **A alteração no GitHub foi deliberada** (mudou-se uma regra de propósito).
   Então o ficheiro é que está desactualizado: reproduz-se a exportação abaixo,
   escreve-se o resultado em `main.json`, e o PR que o leva explica porquê.
2. **A alteração no GitHub não foi deliberada** — e inclui-se aqui, sempre,
   qualquer entrada em `bypass_actors`. Então **repõe-se o GitHub e não o
   ficheiro**. A página é a do alvo que a saída nomeia — hoje há duas:
   `https://github.com/albinoJimy/kamba/rules/24879081` e
   `https://github.com/albinoJimy/kamba-plataforma/rules/25359475`. Repor o
   campo que a saída nomeia, e correr `make ruleset` outra vez até sair 0.
   Quem repõe é quem tem administração do repositório; hoje, o fundador.
3. **`repositorio-sem-ruleset` ou `ruleset-ausente`** — não é nenhum dos dois
   casos acima: é um repositório onde a política nunca foi aplicada. Cria-se lá
   o *ruleset*, com o conteúdo do espelho, e escreve-se o `id` que a saída
   imprime em [`ci/ruleset.yaml`](../../ci/ruleset.yaml). **Nunca se tira o
   alvo da lista para calar o vermelho** — tirá-lo é decidir que aquele
   repositório não precisa de protecção, e isso é governação, não manutenção.
   **Este caso correu, do princípio ao fim:** o `albinoJimy/kamba-plataforma`
   deu `repositorio-sem-ruleset` desde 2026-10-18, o *ruleset* foi criado nesse
   dia, e o `id` ficou escrito a 2026-11-07. Escrever o `id` não é arrumação: sem
   ele, um `delete`+`create` deste *ruleset* é invisível, porque o nome fica
   igual e só o `id` muda.

Um `bypass_actors` não vazio nunca se resolve actualizando o ficheiro: o
ficheiro não é autoridade para conceder *bypass*, e a verificação continua
vermelha enquanto o actor existir no GitHub, mesmo que alguém o acrescente
também aqui.

## Como se reproduz a exportação

```bash
gh api repos/albinoJimy/kamba/rulesets/24879081 --jq '{name,target,enforcement,conditions,rules,bypass_actors}'
```

O `24879081` é o `id` do *ruleset*, e é o mesmo número que está em
[`ci/ruleset.yaml`](../../ci/ruleset.yaml) — há um teste que confronta os dois,
para não ficarem duas cópias do mesmo número a divergir em silêncio.

O ficheiro é essa saída reformatada com chaves ordenadas, dois espaços de
indentação e uma linha em branco no fim, que é o que torna o *diff* legível:

```bash
gh api repos/albinoJimy/kamba/rulesets/24879081 \
  --jq '{name,target,enforcement,conditions,rules,bypass_actors}' \
  | python -c "import json,sys; print(json.dumps(json.load(sys.stdin), indent=2, ensure_ascii=False, sort_keys=True))" \
  > .github/rulesets/main.json
```

E para o `albinoJimy/kamba-plataforma`, cujo `id` é **25359475** desde
2026-10-18:

```bash
gh api repos/albinoJimy/kamba-plataforma/rulesets/25359475 --jq '{name,target,enforcement,conditions,rules,bypass_actors}'
```

Os dois `id` estão em [`ci/ruleset.yaml`](../../ci/ruleset.yaml), e o teste
`test_cada_id_declarado_esta_no_readme_do_ruleset` exige que os conjuntos
**coincidam**: um `id` escrito só num dos dois sítios põe o *gate* 4 vermelho.

A mesma coisa, sem decorar o `id` nem a reformatação, e é a forma a usar quando
se quer o espelho de um alvo sem o ir procurar:

```bash
python -m ruleset_check mostrar --root . --repositorio albinoJimy/kamba \
  > .github/rulesets/main.json
```

O `mostrar` resolve o *ruleset* pelo `name` do espelho e imprime **o formato
exacto do ficheiro**; há um teste que confronta a sua saída, byte a byte, com o
`main.json` no disco.

## O que o *ruleset* exige hoje

| Regra | Efeito |
|---|---|
| `required_status_checks` | **Sete** contextos: seis *gates* por nome próprio **e** o `gates do KAM-002` |
| `pull_request` | Sem *merge* directo: tudo entra por PR. **Aprovações exigidas: 0** — ver a nota abaixo |
| `deletion` | `main` não se apaga |
| `non_fast_forward` | `main` não se reescreve |

### «Contexto exigido» não é «o que bloqueia», e confundir os dois já custou

**São sete contextos exigidos e onze *gates* a bloquear**, e a diferença não é
um detalhe de contabilidade. Medido a 2026-11-07:

| | Quantos | Quais | O que o guarda |
|---|---|---|---|
| **Contextos exigidos** pelo *ruleset* | **7** | *gates* 1, 2, 3, 4, 9, 11 — e o `gates do KAM-002` | o `make ruleset` deste ficheiro, que **não é *gate*** (lacuna 28) |
| ***Gates* que bloqueiam** | **11** | os seis acima, mais **3b, 3c, 6, 7 e 8** | `esperados=11` no *job* agregador, em execução, **e** `TestSemJobNovo` em [`tools/lint_arch/tests/test_ci_gate2.py`](../../tools/lint_arch/tests/test_ci_gate2.py), no *gate* 4 |

Os cinco do meio — 3b, 3c, 6, 7 e 8 — **bloqueiam transitivamente**: estão nos
`needs:` do `gates-em-ambito` (cujo `name:` é `gates do KAM-002`), que é
*required check*. É por isso que um *gate* novo entra nos `needs:` do agregador
e **não** nesta lista: escrever no espelho um contexto que o *ruleset* não tem
torna o espelho falso, e acrescentá-lo no GitHub é alteração de regra de
bloqueio — acto do fundador. A razão está na lacuna 17 de
[`docs/ci.md`](../../docs/ci.md) §7.

**O que isto quer dizer para quem lê esta verificação:** o `make ruleset`
compara **a lista**, e é só isso que ele promete. Quem garante **a barreira** é
o *gate* 4, pela lista dos onze `needs:` escrita à mão, e o próprio agregador,
que conta os resultados e falha se não forem onze. Tirar um *gate* dos `needs:`
é vermelho no *gate* 4; tirar um contexto do *ruleset* é vermelho no
`make ruleset`; e **tirar o `gates do KAM-002` da lista de contextos** —
que é o que faria os cinco deixarem de bloquear de uma vez — é vermelho no
`make ruleset` também, porque ele é um dos sete.

Fora dos `needs:` do agregador há dois *jobs* que falham **por desenho** e não
bloqueiam nada: o `gate 5 — reservado (nao bloqueia)`, até o KAM-003 o ligar, e
a `vigia — prova nocturna (nao bloqueia)`. Um *job* vermelho que não impede
fusão nenhuma é o que a lacuna 30 descreve.

O `gates do KAM-002` entrou depois dos seis: é o *job* que recusa um *gate*
`skipped`, e enquanto não era *required check* não podia bloquear nada — o
GitHub dá um *required check* por satisfeito quando o *job* é saltado, pelo que
um `if:` ou um `paths:` acrescentado a um *gate* satisfazia os seis por omissão
e o único mecanismo escrito para o detectar não tinha autoridade para parar o
*merge*.

> **As aprovações exigidas estão a 0, e é uma cedência com prazo, não um desenho.**
> O *ruleset* nasceu a exigir uma aprovação. Com um só contribuidor essa regra
> não podia ser satisfeita por ninguém: o GitHub não deixa o autor aprovar o
> próprio PR, e o PR do KAM-002 ficou bloqueado com os sete *gates* verdes. O
> fundador baixou-a para 0 a 2026-10-11, na interface, para o fundir.
>
> O que isto custa, dito: **nenhum PR tem hoje revisão humana imposta por
> máquina.** O DoD continua a pedir um revisor (dois quando se alteram regras de
> bloqueio, limiares ou dados de tenant), e as caixas correspondentes ficam por
> marcar nos tickets — mas nada impede o *merge* sem ela. Os *required checks*,
> o PR obrigatório e a protecção contra apagar e reescrever `main` mantêm-se.
>
> **Volta a 1 no dia em que houver um segundo contribuidor.** É a primeira coisa
> a fazer quando ele entrar, e está registado como lacuna em `docs/ci.md` §7.

> `strict_required_status_checks_policy` está a `false`: um PR validado contra um
> `main` mais antigo pode entrar. É deliberado — exigir *rebase* a cada *merge*
> alheio custa mais do que vale num repositório com um contribuidor — e é uma
> decisão a rever quando a equipa crescer.
