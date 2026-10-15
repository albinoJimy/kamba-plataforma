# *Rulesets* de `main` — o que o GitHub aplica, em ficheiro

O `main.json` é a exportação do *ruleset* `main: gates fail-closed do KAM-002`,
que é a peça de que toda a propriedade *fail-closed* depende: sem ele, os seis
*gates* correm e reportam, e nada impede o *merge*.

**Porque está aqui.** O *ruleset* é configuração, não código: vive na API do
GitHub, altera-se sem PR, e nada no repositório o descrevia. Quem quisesse saber
quais são os *required checks* tinha de ter acesso de administração e saber o
`id`. Exportado, lê-se num *diff* como qualquer outra regra de bloqueio — e uma
alteração feita na interface aparece como divergência face a este ficheiro.

**O que não faz.** Isto é um espelho, não a fonte: o ficheiro **não** é aplicado
por nada. Editá-lo não altera o GitHub, e alterar o GitHub não o actualiza.
Fechar essa volta — aplicar o ficheiro, ou um *gate* que compare os dois —
precisa de um *token* com `administration: write`, que o KAM-002 não tem e não
devia ter (o CA diz «sem chaves estáticas»). Fica como lacuna registada em
[`docs/ci.md`](../../docs/ci.md) §7.

## Como se reproduz a exportação

```bash
gh api repos/albinoJimy/kamba/rulesets/24879081 --jq '{name,target,enforcement,conditions,rules,bypass_actors}'
```

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
