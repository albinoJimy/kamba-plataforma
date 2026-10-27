# O ponytail nas estações da fábrica

Lê este ficheiro quando fores usar as skills do plugin `ponytail` dentro de uma linha — e
sobretudo antes de aceitar um achado de «cortar».

- [As quatro estações](#as-quatro-estações)
- [Os níveis](#os-níveis)
- [Onde divergem, ganha o repositório](#onde-divergem-ganha-o-repositório)
- [Duas listas de dívida que não são a mesma](#duas-listas-de-dívida-que-não-são-a-mesma)
- [O que fica de fora](#o-que-fica-de-fora)

---

## As quatro estações

O ponytail traz um eixo que esta fábrica não tinha: **o que não devia existir**. Os portões
deste repositório medem se o conjunto é coerente, se os nomes são canónicos, se o código compila
e está coberto; nenhum pergunta se ele era preciso. Entra em quatro estações, e em nenhuma delas
substitui o que já lá estava.

| Estação | Skill | Para quê |
|---|---|---|
| **1.1** Discovery | `ponytail:ponytail-audit` | riscos e hipóteses de código que não conheces |
| **1.4** Produção | `ponytail:ponytail` (`full`) | a mudança mais pequena que fecha a tarefa inteira |
| **1.6** Revisão adversarial | `ponytail:ponytail-review` | defeitos no diff **e** no código ligado, e o que cortar |
| **1.8** Encerramento | `ponytail:ponytail-debt` | o livro da dívida antes de fechar |

### 1.1 — na Discovery

Quando o alvo é código que ninguém da sessão conhece, ou a pergunta é «o que está mal aqui?»,
junta a auditoria à varredura. É read-only, o que a torna compatível com a proibição do
Explorer, e devolve achados ordenados por gravidade.

```
Skill(skill: "ponytail:ponytail-audit", args: "services/<nome>")
```

O que sai de lá entra como **riscos e hipóteses** da discovery — nunca como trabalho a fazer. É
exactamente a classe de achado que a §1.6 obriga a verificar antes de gerar trabalho.

**A auditoria do repositório inteiro, sem argumento, é de outra cadência:** corre-se ao fechar um
epic, ou a pedido do fundador, e **não entra no PR de um ticket** — entrar lá fazia dela um
gate, e o que ela procura (carga real, lógica arriscada sem teste, código que não devia existir)
só se vê depois de vários tickets assentarem. O relatório vai para
`docs/analises/ANALISE-NN-<slug>.md`, como qualquer memória de revisão.

### 1.4 — na Produção

Activa-o **ao entrar na estação**, antes da primeira linha, e vale até ao fim da escrita.

```
Skill(skill: "ponytail:ponytail", args: "full")
```

Dá a ordem de escolha que este repositório já quer: não construir o que ninguém pediu, reutilizar
o que já existe, depois a biblioteca padrão, depois uma dependência já instalada, e só por fim
código novo — o mais curto que fecha a tarefa **inteira**, incluindo chamadores, testes e
fixtures que a mudança parte.

Não acrescenta estação nenhuma ao ciclo: **substitui** o hábito de desenhar a abstracção antes do
caso de uso, e reforça pelo outro lado a regra do escopo da §1.4 — ali é o escopo que não se
alarga, aqui é o código.

### 1.6 — na Revisão adversarial

Ao lado do `code-review`, **na mesma passagem**, não em vez dele e não depois dele.

```
Skill(skill: "ponytail:ponytail-review")
```

O `code-review` procura o defeito no diff. O `ponytail-review` lê o **código ligado** — quem
chama a função que mudou, o que ela chama, os testes, o que o repositório diz da carga esperada —
e faz as perguntas que o primeiro não faz: aguenta a carga real, a lógica arriscada tem um teste
que falha quando ela quebrar, e cada linha é precisa. Exige um caso concreto por achado, que é a
mesma exigência de evidência que esta fábrica faz ao resto.

**Não é uma segunda revisão.** A decisão do fundador de Outubro de 2026 é «sem segundas leituras
nem gates novos», e a razão dela não foi a revisão — essa encontrou defeitos reais em todas as
primeiras entregas — foi **repeti-la**. Na prática:

- **Uma passagem, uma lista, uma volta de correcções.** Os achados dos dois instrumentos juntam-se
  numa lista só, corrigem-se de uma vez, e o PR funde. Não se pede ao `ponytail-review` para
  reler as correcções, mesmo quando a correcção inclui um redesenho.
- **Corre-o o revisor, não o autor.** O revisor recebe o diff e os requisitos, nunca as
  justificações de quem escreveu.
- **Os achados das duas passam pela mesma verificação** (`CONFIRMADO` / `PLAUSÍVEL` / `MORTO`):
  um achado de «cortar» não é mais verdadeiro por vir de uma skill de simplicidade.
- **Achado menor segue o destino que já tem.** Um *Nice to have*, ou um *Lean* fora do âmbito,
  não volta ao autor: resíduo textual vai para `docs/dividas-documentais.md`, o que pede código
  abre ticket.
- **Não é gate.** `Verdict: fix 1 and 3 first.` é parecer para quem corrige, não bloqueio de CI.
  Nenhum relatório do ponytail passa a ser condição de merge.
- **O que não se corta são defeitos.** O grupo *Must fix* — defeito, segurança, perda de dados,
  quebra na carga esperada — corrige-se antes do merge.
- **Em trabalho documental não entra.** Lê código, e a maior parte do que se faz aqui é desenho
  e backlog; para isso o guião é [`revisao-adversarial.md`](revisao-adversarial.md), inteiro e
  sem acrescento.

O `ponytail-review` **substitui** a pergunta da simplicidade no fim do guião: o
`Skill(skill: "simplify")` deixa de se invocar no ciclo de um ticket.

### 1.8 — no Encerramento

Antes de fechar, faz o livro da dívida:

```
Skill(skill: "ponytail:ponytail-debt")
```

Lê os comentários `shortcut:` do repositório e devolve-os com o tecto que cada um nomeia e o
gatilho de revisão. Um atalho que saia `no-trigger` — sem gatilho escrito — **emenda-se no
próprio comentário, no mesmo PR**: é a forma de dívida que apodrece em silêncio.

Corre-o também **quando um ticket vai afirmar um limite** (um p95, um tecto de carga, uma
capacidade): um atalho declarado por baixo dessa afirmação é a razão mais provável para ela ser
verdade por acidente, que é o defeito que a §1.6 persegue.

---

## Os níveis

**`full` é a omissão, e é sempre a mesma.** O nível é sobre a forma do diff, não sobre quanto se
verifica — o rigor por ticket não se gradua, e nenhum dos níveis mexe no que esta fábrica exige.

- **`lite` não se usa.** Pára para o utilizador escolher entre duas opções, e aqui não se pára à
  espera.
- **`ultra` só fora de um ticket.** Questiona o próprio pedido, e isso é precisamente o trabalho
  ao redigir um ticket, um ADR ou um critério de aceitação. Dentro de um `KAM-NNN` o critério de
  aceitação é o contrato: cumpre-se à letra, não se discute a meio.

---

## Onde divergem, ganha o repositório

Três regras, e a primeira não tem excepção:

**1. «Mínimo» nunca é retirar uma barreira.** Uma política RLS, um `fail-closed`, um passo de
canário, uma verificação de assinatura ou de idempotência não são «código a mais» — são o
produto. Um achado de «cortar» que remova uma barreira de governação **rejeita-se**, e o
veredicto é `MORTO` com a razão escrita.

Nos dois sentidos — alargar e encolher — a pergunta é a mesma: **o que é que esta barreira
impedia?** Um gate reservado que passasse em silêncio, um canário que não morde, uma *allowlist*
escrita à mão: todos parecem simplificações e todos são o defeito que o portão existia para
tornar impossível.

**2. O marcador `shortcut:` é o daqui — usa-o.** Ao contrário de outros repositórios da casa,
esta é a convenção registada: um atalho deliberado leva `shortcut: <o limite>, <quando se
revê>`, com a palavra-chave em inglês (é por ela que o `ponytail-debt` procura) e o limite e o
gatilho em português. **Um atalho sem limite escrito é defeito, não atalho.**

**3. A resposta curta não substitui o relatório.** O ponytail optimiza para uma resposta que um
humano ocupado lê de uma vez. O encerramento desta fábrica exige evidência nomeada por afirmação
([`encerramento.md`](encerramento.md)), as caixas do ticket marcadas uma a uma e a secção
`### Verificação dos Critérios de Aceitação`. As duas coexistem: a resposta curta é para o
utilizador, o relatório é o que fica. A frase final do ponytail — o que saltou e o risco que
fica — é útil e **não** é evidência nomeada.

---

## Duas listas de dívida que não são a mesma

| | `docs/dividas-documentais.md` | `ponytail-debt` |
|---|---|---|
| O que regista | resíduo **textual**: frase desactualizada, nome antigo, contagem errada | limite **de código** aceite de propósito, com o seu tecto |
| Onde vive | ficheiro do repositório, mantido à mão | no comentário `shortcut:`, ao lado da linha que explica; a lista gera-se quando se pede |
| Quem acrescenta | uma revisão que encontrou algo fora do âmbito | quem escreveu o atalho, no mesmo diff |
| Como se fecha | quem emenda o documento risca a linha | o gatilho chega e abre-se ticket, porque pede código |

Daí duas regras: um `shortcut:` **não** se copia para `docs/dividas-documentais.md` — ficava a
mesma dívida em dois sítios, e um deles a desactualizar-se; e um resíduo textual **não** leva
comentário `shortcut:`, porque não há código onde o pôr.

---

## O que fica de fora

**`ponytail:ponytail-gain`** mostra poupanças medidas noutro repositório, e a própria skill
proíbe derivar delas um número para o repositório onde corre. Aqui isso seria uma afirmação sobre
o mundo sem evidência local — **NÃO VERIFICADO** à letra da escala de verificação — e um relatório
de ticket não a pode citar.

**`ponytail:ponytail-help`** é o cartão de referência dos níveis e comandos. Usa-o quem precisar;
não tem sítio no fluxo.

Nenhuma das duas produz evidência de nada, e invocá-las a meio de uma linha não acrescenta
estação.
