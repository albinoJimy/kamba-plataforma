# ADR-L009 — O *gate* 2 passa a ler as mensagens dos *commits* de um PR: autorizado

| Campo | Valor |
|---|---|
| Estado | Aceite |
| Data | 2026-11-03 |
| Ticket | KAM-174 — Nenhum portão lê as mensagens dos *commits*, e o `commitlint` não corre em sítio nenhum |
| Âmbito | Local (ver [`README.md`](README.md)): **ligar** a verificação da forma do assunto dos *commits* próprios de um PR dentro do *gate* 2, pelo alvo `lint-arch`, e **qual o intervalo** que ela varre. Não acrescenta contexto exigido ao *ruleset* de `main` (não há *job* novo), não emenda a regra do [`../../specs/01_Engineering_Standards_e_Handoff.md`](../../specs/01_Engineering_Standards_e_Handoff.md) §5 — que já era esta —, não toca nas `exemptHeaderPatterns` de [`../../tools/conventions.json`](../../tools/conventions.json), e **não** reescreve nenhum *commit* de `main` |
| Decisores | **O fundador, a 2026-11-03** |
| ADRs canónicos aplicáveis | Nenhum. A verificação é estática e vive no `lint_arch`, que só depende da biblioteca padrão |
| Documentos aplicáveis | [`../ci.md`](../ci.md) §2 e §3 (*gate* 2); [`../../specs/01_Engineering_Standards_e_Handoff.md`](../../specs/01_Engineering_Standards_e_Handoff.md) §5; [`../../tools/conventions.json`](../../tools/conventions.json); [`../../tools/lint_arch/commits.py`](../../tools/lint_arch/commits.py); [`../dividas-documentais.md`](../dividas-documentais.md) (linhas 170 e 173); [`ADR-L001`](ADR-L001-toolchain.md) §8 (não há *linter* de estilo) |
| Substitui | — |

## Contexto

Travar um *merge* é uma regra de bloqueio, e nesta casa uma regra de bloqueio é
decisão do fundador: o executor entrega a **medição**, não a implementação. Este
ADR existe porque a caixa de DoD do KAM-174 o exige por escrito — «sem isto, o
resto deste DoD não se começa» — e porque a pergunta foi **afinada três vezes**
antes de ser respondida. As três versões ficam aqui, porque a diferença entre
elas é a diferença entre autorizar uma regra grande e autorizar uma pequena.

**Primeira versão: «aceitas avermelhar 22 de 140 assuntos de `main`?»** Vinha da
revisão adversarial do PR #110, que mediu 22 dos últimos 140 assuntos de `main`
fora da forma, 18 deles sem tipo. Com essa leitura, ligar o portão avermelhava
trabalho legítimo que ninguém podia corrigir.

**Segunda versão: nenhum desses assuntos entra no intervalo.** Medido: o
intervalo que o critério 3 do ticket escolhe — do primeiro ao segundo pai do
*merge ref* — lê **só** os *commits* que o PR acrescenta. Os assuntos históricos
de `main` são todos alcançáveis da base, e o `git rev-list base..head` exclui o
alcançável da base por construção; quando o ramo traz a `main` para dentro, esses
*commits* passam a ser alcançáveis dos dois lados e continuam excluídos. A
pergunta deixou de ser sobre os 22 e passou a ser: «aceitas travar um PR cujos
próprios *commits* estejam fora da forma?»

**Terceira versão, e a que foi respondida: os *merges* de integração são
isentos.** A segunda versão tinha ainda um buraco, levantado e medido: dois dos
cinco *commits* do PR #110 eram *merges* de integração, e um *merge* que o PR faz
para trazer a `main` **é** do PR e **é** lido. Se avermelhasse, trazer a `main`
para dentro de um PR passava a exigir baptizar o *merge* à mão — uma regra
pequena a morder uma operação frequente, e há **12** *merges* de forma por
omissão nos últimos 300 *commits* de `main`. Medido depois, por execução, que
**não** avermelha: a isenção `^Merge ` de `exemptHeaderPatterns` corre em
`check_commit_message` **antes** de qualquer outra regra e devolve lista vazia.

```text
Merge branch 'main' into feature/KAM-174-x   -> CONFORME
Merge pull request #47 from x/y              -> CONFORME
Revert "feat(KAM-001): x"                    -> CONFORME
merge: traz a main                           -> recusado
arrumacoes                                   -> recusado
```

O `merge: traz a main` é o caso que tinha sustentado a objecção: foi recusado
pelo *hook* a uma sessão desta casa, mas está em minúscula e com dois pontos,
pelo que não casa `^Merge ` **nem** casa tipo nenhum, e falha pelas duas razões.
Uma recusa de um caso **escrito à mão** tinha sido lida como evidência sobre o
caso que o `git` escreve **por omissão**, e são coisas diferentes.

**E uma correcção de número, que fica registada porque é da mesma família.** A
contagem dos assuntos fora da forma nos últimos 140 é **22** por um predicado e
**30** por outro; a diferença é contar ou não os *merges* de forma por omissão.
O que se levou à decisão foi o raciocínio e não o número, precisamente por isso.

**Os três *commits* com `Merge` no nome, que foi o que confundiu as duas
leituras:**

| *commit* | entra no intervalo? | veredicto | porquê |
|---|---|---|---|
| o sintético do *merge ref* | não | — | fica fora por construção (pai 1..pai 2) |
| o *merge* real que o ramo faz | sim | conforme | isento por `^Merge ` |
| um `merge:` escrito à mão | sim | **recusado** | não é isento nem tem tipo |

## Decisão

**Autorizado.** O *gate* 2 passa a recusar um PR cujos próprios *commits*
não-*merge* estejam fora da forma `tipo(KAM-NNN): descrição no imperativo`, com o
intervalo do critério 3 do KAM-174 — do primeiro ao segundo pai do *merge ref* —
e com as quatro `exemptHeaderPatterns` intactas.

A pergunta e a resposta, textuais:

> **Pergunta ao fundador, a 2026-11-03:** «Autorizas o portão e implemento
> agora?», sobre a recomendação de autorizar com duas condições — que o reuso do
> `check_commit_message` seja obrigatório, porque é o que mantém os *merges*
> isentos, e que as quatro isenções fiquem intactas.
>
> **Resposta, a 2026-11-03:** «Sim, implementa»

**A pergunta do intervalo, que a caixa de DoD exige respondida**, está respondida
pela terceira versão acima: o intervalo é o dos *commits* próprios do PR, e **não**
o do *gate* 9. A razão não é preferência de desenho. A base do *gate* 9 é a ponta
de `main` no momento do evento, pelo que cresce enquanto o PR está aberto: um
assunto fora da forma que funde em `main` nesse intervalo de tempo avermelhava um
PR alheio, cujo autor não pode corrigir um *commit* de `main` (eles não se
reescrevem) nem dispensá-lo. Um portão que avermelha por acto de terceiro é um
portão que se aprende a ignorar. O caso que distingue os dois intervalos está
construído em
[`../../tools/lint_arch/tests/test_commits.py`](../../tools/lint_arch/tests/test_commits.py)
(`TestOsDoisIntervalos`), e não em prosa.

## Consequências

**Quanto trabalho legítimo fica vermelho.** Pelo que se mediu, nenhum que não
seja do próprio autor e reparável por ele:

- **Nenhum *commit* de `main`** entra no intervalo, sejam 22 ou 30 os que estão
  fora da forma.
- **Nenhum *merge* de integração**, pela isenção. Os 12 dos últimos 300 passam.
- **Nenhum PR recente**: corrido sobre `refs/pull/112/merge`, 4 *commits* no
  intervalo, conforme. O próprio PR #113 passa, com os *commits* que tiver — a
  contagem não se escreve aqui de propósito, porque sobe a cada *commit* novo e
  uma linha que a cite fica errada no *push* seguinte (a primeira versão desta
  linha dizia «1 *commit*» e tinha dois; achado A12 da revisão adversarial).
- O que fica vermelho é um *commit* não-*merge* do ramo de quem abriu o PR, que
  ele reescreve com `git rebase -i` ou `git commit --amend`. A ajuda impressa pelo
  portão diz o comando.

**O que a autorização não cobre**, e não se estica:

- Não autoriza *job* novo nem alteração ao *ruleset* de `main`. O `esperados` do
  resumo continua em **11** e os `needs:` do agregador não mudam — é a condição
  que torna esta decisão local e não uma alteração de regra de bloqueio do
  repositório.
- Não autoriza endurecer as `exemptHeaderPatterns`. Retirá-las, ou qualquer uma
  delas, é uma decisão nova e maior do que esta: sem a `^Merge `, trazer a `main`
  para dentro de um PR passa a exigir baptizar o *merge* à mão.
- Não autoriza reescrever `main`. A dívida 170 fica como está.
- Não decide ligar o `commitlint` a um portão. Essa é a decisão do critério 9 do
  ticket, tomada por quem implementou e escrita em [`../ci.md`](../ci.md) §3:
  fica como via local, porque o `@commitlint/config-conventional` traz o seu
  próprio *parser* e ligá-lo punha em CI uma segunda implementação da forma.

**O custo assumido.** Um portão a mais no caminho de cada PR, e um clone mais
profundo no *gate* 2: o `checkout` passa de 2 s a 4 s e o clone de 1 895 para
5 905 objectos (8,2 → 16,5 MiB de *pack*). Os dois passos novos custam ~0,14 s.
O detalhe da medição está em [`../ci.md`](../ci.md) §3.

**O que torna isto reversível.** Retirar as duas linhas `commit-range` do alvo
`lint-arch` no [`../../Makefile`](../../Makefile) desliga o portão num *commit*,
sem tocar no `ci.yaml` nem no *ruleset*. É a propriedade que entrar num *gate*
existente dá, e que um *job* novo não daria.
