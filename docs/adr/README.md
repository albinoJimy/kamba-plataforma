# ADRs locais

Este directório guarda **ADRs locais**: decisões de implementação tomadas no
âmbito de um ticket, em formato MADR.

## Porque é que não são `ADR-021`, `ADR-022`…

`specs/01_Engineering_Standards_e_Handoff.md` §5 diz:

> **ADRs em formato MADR.** Novos ADRs numeram-se após o último canónico
> (`../tecnica/00` §8; actualmente ADR-019).

Essa frase está desactualizada: `../tecnica/00` §8 contém **vinte** ADRs canónicos,
`ADR-001` a `ADR-020` — o `ADR-020` (módulos de entrada) foi acrescentado por
decisão do fundador a 2026-10-09 e está marcado FIXA em `specs/00_KAMBA_Carta.md`
§4.2. Numerar um ADR local como `ADR-020` colidiria com ele.

A segunda razão é mais importante do que a colisão: **um ADR local não é um ADR
canónico**, e dar-lhe um número da mesma sequência faz parecer que é. Os ADRs
canónicos vivem num só sítio (`../tecnica/00` §8) e governam o produto todo; estes
governam uma escolha de implementação dentro de um ticket e podem ser
substituídos por quem fizer o ticket seguinte.

Por isso usa-se um espaço de numeração separado:

```
docs/adr/ADR-L<NNN>-<slug>.md
```

`L` de local, numerado a partir de `001`, independente da sequência canónica.

## Quando é que uma decisão sobe de local a canónica

Quando passa a governar mais do que o seu ticket — porque outro subsistema
depende dela, ou porque contradiz um ADR em vigor. Nesse caso entra em
`../tecnica/00` §8 com o número canónico seguinte, a contagem em `../tecnica/INDICE.md`
§5 é actualizada, e o ADR local passa a apontar para ele.

## Índice

| ADR | Decisão | Ticket | Estado |
|---|---|---|---|
| [ADR-L001](ADR-L001-toolchain.md) | Toolchain do monorepo: `make` como fachada, `node --test`, TypeScript 5.x, Starlette no AGR | KAM-001 | Aceite |
| [ADR-L002](ADR-L002-injeccao-de-segredos.md) | Injecção de segredos por variáveis de ambiente no arranque do contentor, e não por ficheiros em `tmpfs` | KAM-010 | Aceite |
| [ADR-L003](ADR-L003-verificacao-do-ruleset.md) | O *ruleset* de `main` verifica-se com um *token* de **leitura** (`administration: read`), que compara e nunca aplica, fora do CI deste repositório | KAM-137 | Aceite |

## Emenda pedida ao canon

`specs/01` §5 deve passar a dizer «actualmente ADR-020» e a nomear este espaço de
numeração para ADRs locais. A emenda está pedida no PR do KAM-001; até ser feita,
este ficheiro é a referência.
