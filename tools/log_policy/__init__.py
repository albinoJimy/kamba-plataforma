"""log_policy — as verificacoes por maquina da politica de logs (KAM-068).

Quatro coisas, todas so com a biblioteca padrao:

| Comando | O que faz | Onde corre |
|---|---|---|
| `lint` | nenhum servico escreve fora do *logger* (`console.*`, `print`, `logging`, `stdout`) | gate 2 |
| `canario` | as *fixtures* negativas do `lint` **tem** de falhar, pela regra esperada | gate 2 |
| `x11` | varre ficheiros de *log* por telefone, NIF, e-mail, IBAN, segredos e canarios | gate 6 (`make x11`) |
| `amostra` | tira N linhas aleatorias por servico, varre-as e regista o resultado | a agendar em `prod` (KAM-080) |

Mais dois que servem o `x11`: `fixtures` gera as 1 000 chamadas com dados
pessoais em todos os sitios onde podem aparecer, e `conduzir` passa-as pelo
*logger* em Python (o espelho em TypeScript e
`packages/core-ts/tests/x11_conduzir.ts`).

**O varrimento e independente do *logger*.** `x11.py` nao importa
`kamba_core.logger`: um oraculo que usasse as formas de quem esta a verificar
concordava com ele por construcao. Partilham so a lista dos doze campos, que e
o contrato (`docs/tecnica/08` §7.3) e que um teste confere contra os dois.

**Nenhum relatorio repete o que encontrou.** Um achado diz o ficheiro, a linha,
o padrao e o campo. O valor nunca: um varrimento de dados pessoais que os
imprime copia-os para o registo do CI.

A politica, os limites e o processo estao em `docs/logs.md`.

Codigos de saida: 0 limpo, 1 achados, 2 erro de utilizacao ou de configuracao.
"""

__all__ = ["cli"]
