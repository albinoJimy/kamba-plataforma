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
| `albinoJimy/kamba-plataforma` | **público, e é onde os PR são abertos e o CI corre** | **por criar** — decisão do fundador de 2026-10-18, cópia do privado |

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
Enquanto o *ruleset* do `albinoJimy/kamba-plataforma` não existir, a
verificação é **vermelha de propósito**, com `repositorio-sem-ruleset` — e essa
é a única forma honesta de o dizer.

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
   ficheiro**: `https://github.com/albinoJimy/kamba/rules/24879081`, repor o
   campo que a saída nomeia, e correr `make ruleset` outra vez até sair 0.
   Quem repõe é quem tem administração do repositório; hoje, o fundador.
3. **`repositorio-sem-ruleset` ou `ruleset-ausente`** — não é nenhum dos dois
   casos acima: é um repositório onde a política nunca foi aplicada. Cria-se lá
   o *ruleset*, com o conteúdo do espelho, e escreve-se o `id` que a saída
   imprime em [`ci/ruleset.yaml`](../../ci/ruleset.yaml). **Nunca se tira o
   alvo da lista para calar o vermelho** — tirá-lo é decidir que aquele
   repositório não precisa de protecção, e isso é governação, não manutenção.

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

A mesma coisa, sem decorar o `id` nem a reformatação — e é esta a forma a usar
quando o alvo é o `albinoJimy/kamba-plataforma`, cujo `id` ainda não existe:

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
| `required_status_checks` | Os seis *gates* activos **e** o `gates do KAM-002` |
| `pull_request` | Sem *merge* directo: tudo entra por PR. **Aprovações exigidas: 0** — ver a nota abaixo |
| `deletion` | `main` não se apaga |
| `non_fast_forward` | `main` não se reescreve |

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
