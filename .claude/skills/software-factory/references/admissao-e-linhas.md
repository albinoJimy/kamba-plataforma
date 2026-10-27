# Admissão, linhas de produção e autoridade

Lê este ficheiro quando estiveres a classificar um pedido, a escolher a linha por onde ele
corre, ou a decidir se podes avançar sozinho.

- [Admissão](#admissão)
- [As seis linhas](#as-seis-linhas)
- [Tabela de autoridade](#tabela-de-autoridade)

---

## Admissão

A classe do pedido determina a linha; a linha determina os portões; os portões determinam o que
conta como feito. Classificar leva trinta segundos e evita os dois erros simétricos: correr
`make ci` inteiro para uma emenda de prosa, e tratar uma falha observada a correr uma suite
como se fosse um ticket por implementar.

```text
ADMISSÃO
Pedido (nas palavras do utilizador):
Classe:                 L1 … L6, ou «sem linha»
Eixo tocado:            documentos · backlog · dicionário · TypeScript · Python · db ·
                        contratos · dependências · CI · segredos
Artefacto de entrada:   o que já existe e serve de base
Artefacto de saída:     o que tem de existir no fim
Portões aplicáveis:
Autoridade:             eu, ou o fundador — e em que passo
Orçamento de relógio:   quanto tempo isto devia demorar
```

O **orçamento de relógio** não é promessa, é instrumento: quando o passares para o dobro sem
resultado, pára e reporta em vez de continuares a tentar. Duas tentativas falhadas da mesma
classe significam que a classificação está errada (ver
[`decomposicao.md`](decomposicao.md), «Recuperação de falhas»).

### Antes de arrancar: quem já está nisto

O repositório é trabalhado em vários worktrees ao mesmo tempo, e **ramos que não se fundiram
não se vêem**. Ao contrário de outros repositórios da casa, **aqui não há instrumento de
registo de sessões** — nada deteje que duas sessões reivindicaram o mesmo ticket ou o mesmo
ficheiro. É lacuna conhecida, e a receita manual está em [`isolamento.md`](isolamento.md).

O que há, e que se corre sempre antes de escolher trabalho:

```bash
python .claude/skills/software-factory/scripts/vagas.py
```

Lê o backlog mestre e os blocos já fechados, e devolve os tickets cujas dependências estão
satisfeitas. Um ticket conta como **fechado** quando o seu bloco tem a secção
`### Verificação dos Critérios de Aceitação`, que só se escreve no PR que o entrega. Só lê; não
altera nada. É uma lista de **candidatos** — a lista de paralelismo do SKILL.md §1.3 aplica-se
depois dela.

### Numeração de tickets

O `KAM-NNN` seguinte lê-se do backlog mestre, não se inventa:

```bash
grep -oE '^\| KAM-[0-9]+' specs/INDICE.md | grep -oE '[0-9]+' | sort -n | tail -1
```

**Os blocos vivem em dois sítios**, porque o repositório tem duas convenções em simultâneo
(KAM-155): um ficheiro por ticket em `specs/tickets/KAM-NNN.md` no EPIC-01, e dentro do
`specs/EPIC-XX_*.md` nos outros dez. Varrer só um dos dois responde errado com cara de certa.

Um ticket novo precisa das **três superfícies** ao mesmo tempo, ou o gate 3c avermelha: a linha
no `specs/INDICE.md` §4, o bloco `## KAM-NNN — `, e a linha na «Tabela Resumo de Tickets» do §3
do epic. A reciprocidade `Dependências`↔`Bloqueia` também é verificada, e o §4 não tem coluna
que a denuncie.

---

## As seis linhas

### L1 · achado → ticket

Converte hipóteses em trabalho real, ou mata-as com evidência.

```text
ENTRA   hipótese, suspeita, resultado de auditoria, defeito avistado de passagem
SAI     ticket KAM-NNN nas três superfícies, com critérios de aceitação
        OU descarte registado com a evidência que o matou
        OU linha em docs/dividas-documentais.md, se for resíduo textual
```

| | |
|---|---|
| **Estações** | Discovery → verificação contra o canon → redacção do ticket |
| **Revisão** | **é a estação de verificação** — nesta linha não há diff para rever |
| **Portões** | `ci-3` `ci-3c` (o ticket é documento) + `ci-3b` se introduzir nomes |
| **Autoridade** | eu |

**Modo de falha característico:** escrever o ticket antes de verificar. A hipótese pode já
estar decidida ao contrário num ADR em vigor, ou o trabalho pode já estar feito — e uma **caixa
por marcar não é trabalho por fazer**: pode ser trabalho feito cuja caixa ninguém marcou. O
EPIC-02 é o caso: os treze tickets estão fundidos desde 2026-10-23 e sete caixas continuam
vazias à espera de um terceiro. Confirma antes de abrir.

A separação de estações aqui não é um revisor separado: é o **Discovery levantar** e a
**verificação derrubar**. Quem levanta a hipótese não a confirma, e cada afirmação do ticket
leva ao lado o comando que a sustenta — é isso que torna o ticket revisível por quem o for
implementar, em vez de uma lista de alegações.

#### O que é ticket e o que é dívida documental

A fronteira é do `specs/01` §6, princípio 1, e não é de gosto:

| | Vai para |
|---|---|
| Frase desactualizada, nome antigo, contagem errada — sem código nem decisão | `docs/dividas-documentais.md`, uma linha |
| Qualquer coisa que peça código | ticket novo |
| Escolher entre duas fontes que discordam | ticket novo |
| O que o critério de aceitação de outro ticket mande abrir | ticket novo |

#### E verifica o achado no ramo onde o ticket vai viver

Um achado verificado na tua árvore está verificado contra o teu ramo. Se o ticket vai nascer
noutro, parte dele pode já estar fechada lá — e ninguém o vê daqui.

```bash
git grep -c -F '<a frase exacta que afirmas estar errada>' <ramo> -- <ficheiro>
git log -1 --format='%h %s' <ramo> -- <ficheiro>
```

Dois cuidados:

- **Usa `-F`.** Um padrão com `*`, `**` ou parênteses casa zero por erro de escapamento, e zero
  lê-se como «já corrigido». É o controlo negativo sobre um alvo que não existe.
- **Lê a correcção que já lá está, não só a sua existência.** Quem corrigiu primeiro pode ter
  fixado uma formulação mais precisa do que a tua, e o ticket tem de a seguir — senão troca uma
  afirmação absoluta errada por outra absoluta no sentido oposto.

O que sobreviver a isto é o ticket. O que não sobreviver entra nele como «o que já está feito»,
com o PR que o fez — é o que impede a próxima sessão de o redescobrir.

---

### L2 · ticket → PR

A linha principal. É aqui que o ciclo interno corre inteiro.

```text
ENTRA   KAM-NNN com critérios de aceitação, dependências fechadas
SAI     PR verde, com a secção `### Verificação dos Critérios de Aceitação` escrita
```

| | |
|---|---|
| **Estações** | o ciclo interno completo (SKILL.md §1) |
| **Portões** | os do eixo (ver [`portoes-e-velocidade.md`](portoes-e-velocidade.md)) |
| **Autoridade** | eu |

**Antes de arrancar:** confirma que as dependências estão fechadas. **«Em `main`» faz as vezes
de «`Done`»** — o DoR do `specs/01` pede dependências `Done`, e nenhum ticket fica `Done` à
letra enquanto a caixa dos revisores estiver vazia; enquanto o projecto não estiver em
produção, uma dependência conta como satisfeita quando o seu PR está fundido com as caixas
marcadas com evidência. Se bloquearem a sério, pára e reporta — não contornes.

**Modo de falha característico:** a alteração parcial. Funciona nos casos que testaste e falha
nos outros, e ninguém suspeita dela porque há evidência de que «está feito». Percorre os
critérios de aceitação um a um, com a evidência ao lado; um critério marcado sem evidência
nomeada não está marcado, está presumido.

**Tickets pequenos do mesmo tema podem partilhar um PR.** O ramo leva o ID do primeiro
(`feature/KAM-NNN-<slug>`); cada commit leva o ID do ticket a que pertence; o corpo do PR tem
uma secção por ticket; e cada ticket mantém o seu bloco, as suas caixas e a sua secção de
verificação. A revisão adversarial é uma só.

---

### L3 · PR → merge

```text
ENTRA   PR aberto
SAI     squash merge em main
```

| | |
|---|---|
| **Estações** | vigiar CI → classificar vermelho → corrigir → fundir |
| **Portões** | os *required checks* do *ruleset* de `main` — hoje sete contextos, com `gates do KAM-002` como agregador |
| **Autoridade** | eu, com CI verde |

**Merge com o CI verde, sem esperar revisão humana.** É decisão do fundador: o *ruleset* de
`main` exige 0 aprovações, e a caixa «revisto por N revisores» **continua vazia** em todos os
tickets, incluindo os que alteram regras de bloqueio. É um facto registado, não um bloqueio. O
DoD tem a linha «2 revisores se alterar regras de bloqueio ou limiares» e ela não está
satisfeita — **uma revisão adversarial é evidência, não é um revisor**, e dizê-lo é obrigatório
no relatório.

```bash
gh pr checks <n>
gh pr merge <n> --squash
```

**Três armadilhas desta linha:**

- **«no checks reported»** não é CI lenta — é o PR em conflito com a base.
- **Dois PRs em cadeia fundem-se pela ordem, não em paralelo.** Fundir a base por squash deixa
  o encadeado em `CONFLICTING`.
- **Um vermelho tem causa, não hipótese.** Lê o log antes de formular teorias. E repara no
  código de saída: há gates cujo `2` significa «não se conseguiu verificar», que nunca é verde.

Depois de fundir, **não perguntes ao `git` se fundiu** — há dois remotos sem antepassado comum
e o `merge-base` falha. A receita está em [`encerramento.md`](encerramento.md).

Para sincronizar com a base dentro de um worktree desta app, usa o `sync_with_base_branch` do
host: o merge local não consegue escrever os ficheiros protegidos pela sandbox.

---

### L4 · falha em execução → correcção

```text
ENTRA   sintoma observado a correr a pilha, um gate ou uma suite — com output REAL colado
SAI     correcção pela L2, e o gate ou teste que reproduz a falha
```

| | |
|---|---|
| **Estações** | recolher evidência → reproduzir → causa raiz → correcção pela L2 → portão |
| **Portões** | os do eixo, mais o que passou a cobrir a falha |
| **Autoridade** | eu |

**Esta linha não termina em produção, porque não há produção.** A KAMBÁ está em Piloto: não há
*release*, não há deploy, e os gates 14 e 18 do `specs/01` §4 (imagem, release) são do
**KAM-078** — com a parte de assinatura e SBOM que o KAM-067 já consome —, por fazer. A prova final de uma correcção é **o portão que a reproduz**, não um
*run* em produção — e é por isso que esta linha desagua sempre na realimentação do SKILL.md §3.

```bash
make up && make smoke     # a pilha de desenvolvimento e o /healthz de cada serviço
make logs                 # os logs da pilha
make ps
```

**«Feito» dito sem output colado é uma hipótese sobre o estado da máquina**, não uma observação
dela.

**Modo de falha característico:** confundir não-determinismo com determinismo. Uma corrida só
não distingue um defeito de um *flake* — repete antes de afirmar. E uma `PROVA INVALIDA` no
relatório das mutações **não é uma mutação apanhada**: é a suite a falhar por carga da máquina;
conta como sobrevivente e baixa-se o paralelismo.

---

### L5 · conhecimento → canon

```text
ENTRA   decisão de arquitectura, nome novo, contrato, evidência, risco, armadilha
SAI     o registo no sítio canónico, com as contagens e os índices actualizados
```

| | |
|---|---|
| **Estações** | escolher o destino → escrever → actualizar contagens e índices → portões documentais |
| **Portões** | `ci-3` `ci-3b` `ci-3c` |
| **Autoridade** | eu — excepto ratificar, que é do fundador |

| O que descobriste | Onde vive |
|---|---|
| Decisão de arquitectura canónica nova | `docs/tecnica/00_Arquitectura_Solucao.md` §8 (ADR-NNN), e a contagem **e o mapeamento** em `docs/tecnica/INDICE.md` §5 |
| Decisão de execução (toolchain, segredos, fila, verificação) | `docs/adr/ADR-L<NNN>-<slug>.md` — numeração própria; **não** é ADR canónico, e o `README` dessa pasta diz porquê |
| Medição, procedimento ou registo longo de um ticket | `docs/evidencia/KAM-NNN.md`, citado pela linha de evidência do critério |
| Decisão que depende de terceiro | `docs/tecnica/00` §13.3 (D#) e `specs/00_KAMBA_Carta.md` §4.2, com dono e escalada |
| Nome, estado, evento ou unidade | `specs/02_Dicionario_de_Dados_Canonico.md` §3, com emenda no §6, e `make dict-export` |
| Facto novo sobre Meta, pagamentos, lei, licenças | `docs/tecnica/evidencia/EN_*.md`, com URL, data e estado |
| Hipótese de negócio nova | `docs/exploracao/14-tese-minima-e-plano-de-validacao.md` §2 (H#), com limiar e prazo |
| Desenho de subsistema | `docs/tecnica/01`–`docs/tecnica/10`, na secção própria ou como adenda datada |
| Decisão sobre o pipeline | `docs/ci.md`, e a lacuna no §7 se ficou alguma |
| Achado de revisão | `docs/analises/ANALISE-NN-<slug>.md` |
| Resíduo textual fora do âmbito | `docs/dividas-documentais.md`, uma linha |
| **Defeito que escapou a um portão** | **um portão novo ou alargado** — ver [`metricas-e-realimentacao.md`](metricas-e-realimentacao.md) |

Não contradigas um ADR em vigor sem substituição explícita, e antes de reescrever conhecimento
existente confirma que a versão anterior deixou mesmo de ser verdade. Na maior parte das vezes
não deixou: ficou incompleta.

**Um nome novo no dicionário não é só uma linha.** O `canon/dicionario.yaml` deriva do §3 por
`make dict-export`; um YAML editado à mão, ou um Markdown alterado sem regenerar, falha o gate
3b. E o gate lê quatro superfícies — migrações, schemas de evento, registo e `docs/tecnica/` —
onde só entram nomes do dicionário ou de `canon/extensoes.yaml`.

---

### L6 · fecho → ratificação

```text
ENTRA   epic com todos os tickets fundidos, ou uma decisão que precisa de assinatura
SAI     ratificação registada, ou a lista do que a impede
```

| | |
|---|---|
| **Estações** | auditoria do epic → `ponytail-audit` → relatório → **pedir ao fundador** |
| **Portões** | `make ci` inteiro, sobre `main` |
| **Autoridade** | **o fundador** |

É aqui que esta linha difere de uma fábrica com produção: o que se entrega ao fim não é uma
versão, é uma **decisão**. O que só o fundador pode fazer:

- ratificar a Carta, o dicionário ou a classificação dos ADRs (hoje todos **proposta**);
- fechar uma decisão aberta `D#`;
- aprovar um limiar, uma regra de bloqueio ou um *waiver* além dos 30 dias;
- aceitar um parecer jurídico como resolvido;
- declarar um epic fechado.

Ao fechar um epic, corre a auditoria de repositório — **que não entra no PR de um ticket**,
porque entrar lá fazia dela um gate:

```
Skill(skill: "ponytail:ponytail-audit")
```

O relatório vai para `docs/analises/ANALISE-NN-<slug>.md`, e cada achado segue a regra que já
existe: defeito abre ticket, resíduo textual vai para `docs/dividas-documentais.md`. Acrescenta
uma vista que o ciclo de um ticket não tem, e **não substitui** a auditoria de completude do
SKILL.md §1.8, que compara o pedido com o entregue.

**A linha de release não existe ainda, e isso diz-se.** Quando os gates 14 e 18 nascerem
(KAM-078), esta linha ganha um segundo destino; até lá, qualquer passo que pareça um deploy é
trabalho sem linha, e pára aqui. O KAM-088 **não** é isso: é o screening de categorias, dono do
gate 12.

---

## Tabela de autoridade

Onde a fábrica pára e pede. Não é burocracia: é a fronteira entre o que é reversível e o que
não é.

| Acção | Quem |
|---|---|
| Editar documentos, código e testes no worktree | eu |
| Correr linters, gates, suites e a pilha de desenvolvimento | eu |
| Abrir ticket `KAM-NNN` nas três superfícies | eu |
| Abrir PR | eu |
| Fundir PR | eu, com CI verde (sem esperar revisão humana) |
| Acrescentar ADR, D#, nome do dicionário, evidência, hipótese | eu, como **proposta** |
| **Ratificar a Carta, o dicionário ou um ADR** | **o fundador** |
| **Fechar uma decisão aberta `D#`** | **o fundador** |
| **Alterar uma regra de bloqueio, um limiar ou o *ruleset* de `main`** | **o fundador** |
| **Declarar um epic fechado** | **o fundador** |
| **Aceitar uma leitura jurídica como definitiva** | **parecer**, nunca eu |
| Apagar, sobrescrever ou forçar push | perguntar primeiro, sempre |

Uma aprovação dada num contexto não se estende ao seguinte.
