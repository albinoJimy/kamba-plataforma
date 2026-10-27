# Evidência e verificação

Lê este ficheiro quando fores afirmar um facto, atribuir-lhe estado, decidir se um valor é
proposta, ou verificar o conjunto por script.

- [A escala de três estados](#a-escala-de-três-estados)
- [Proposta não é facto](#proposta-não-é-facto)
- [Onde vive a evidência](#onde-vive-a-evidência)
- [Verificação por máquina](#verificação-por-máquina)
- [Como correr a verificação aqui](#como-correr-a-verificação-aqui)
- [O que ainda não existe](#o-que-ainda-não-existe)
- [Revalidação](#revalidação)

---

## A escala de três estados

Toda a afirmação sobre o mundo — preços, prazos, leis, licenças, capacidades de terceiros — leva
estado. Não é formalidade: é a diferença entre um desenho que se pode assinar e um que se tem de
refazer.

| Estado | Significa | Exige |
|---|---|---|
| **CONFIRMADO** | fonte primária lida directamente | URL ou documento, data, e a citação do que lá está |
| **INDÍCIO** | fonte secundária, inferência minha, ou leitura indirecta | o mesmo, mais a razão por que não é primária |
| **NÃO VERIFICADO** | não encontrei fonte, ou a fonte não respondeu | o que falta e como se obtém (spike, pergunta escrita, parecer) |

Regras que este repositório aprendeu a impor:

- **Herda o estado quando citas.** Se `docs/tecnica/evidencia/E1` diz INDÍCIO, o teu documento não
  pode dizer CONFIRMADO. Promover estado é o defeito mais comum aqui, e o mais difícil de ver
  depois.
- **Documentação de fornecedor é primária sobre o próprio produto; blogue de fornecedor não é.**
  A biblioteca exploratória afirmou «fontes primárias verificadas» assentando em blogues de
  vendedores de bots — é o exemplo-tipo.
- **Como leste conta.** Uma página lida por sumarizador automático é INDÍCIO, não CONFIRMADO,
  mesmo que a fonte seja oficial. Os preços da OpenAI e da Google neste conjunto estão nessa
  condição e têm de ser reconfirmados antes de fixar tarifas.
- **Jurídico nunca passa de INDÍCIO** sem parecer de advogado angolano. Marca
  `(a confirmar por parecer)` — aplica-se a APD, BNA, AGT, direitos do consumidor e Termos da
  Meta.
- **`NÃO VERIFICADO` é informação útil.** Diz ao leitor exactamente onde tem de olhar. Uma frase
  tranquilizadora sem evidência remove essa informação e não acrescenta nenhuma — é estritamente
  pior do que admitir a lacuna.

Substitui isto:

```text
"Provavelmente funciona."   "Deve estar correcto."   "Não parece haver problema."
```

Por isto:

```text
"CONFIRMADO em <fonte>, <data>."      ou      "NÃO VERIFICADO — falta <o quê>, obtém-se por <como>."
```

---

## Proposta não é facto

Um valor de desenho que ainda não foi calibrado não é uma afirmação sobre o mundo: é uma escolha
nossa, a validar. Marca-o **proposta** e diz onde se calibra.

```text
Tecto do ManualProvider: 50.000 Kz (*proposta*; calibra-se em KAM-096 com dados do Piloto)
```

Exemplos reais deste conjunto, todos propostas e nenhum facto: os tectos de valor por KYC, a
janela anti-fraude de 14 dias, a régua de cobrança D+3/7/10, os limiares das hipóteses H1–H12, a
banda cambial, os volumes por PME que sustentam o custo mensal, e as metas de latência.

O defeito a evitar é o **endurecimento silencioso**: um número que eu propus numa conversa
aparece, três documentos depois, como requisito com ar de medição. Se o número é meu, tem de o
dizer onde aparece.

---

## Onde vive a evidência

| Anexo | Tema |
|---|---|
| `docs/tecnica/evidencia/E1_Meta_WhatsApp.md` | Cloud API, preços, coexistência, Tech Provider, política, grupos, Embedded Signup |
| `docs/tecnica/evidencia/E2_Pagamentos_Angola.md` | facilitadores, rails, BNA, EMIS, e-factura AGT, câmbio, fraude |
| `docs/tecnica/evidencia/E3_Regulatorio_Dados.md` | Lei 22/11, transferências, APD, consumidor, categorias sensíveis, residência |
| `docs/tecnica/evidencia/E4_Stack_Licencas.md` | versões, licenças, maturidade, riscos de dependência, preços de LLM |
| `docs/tecnica/evidencia/E5_Modulos_Entrada.md` | fornecedores de imagem, publicação em redes, mensagens proactivas, direitos |

Formato de cada anexo: tabela por tema com **Afirmação | Estado | Fonte | Data | Implicação para
o desenho**, mais as secções de bloqueios e de perguntas a terceiros. Um facto novo entra aqui
antes de entrar num desenho; um desenho que depende de um facto cita o anexo e a secção.

As perguntas que só um terceiro pode responder (Meta, banco, facilitador, advogado, AGT) não são
lacunas de pesquisa: são **dependências externas**. Viram decisão aberta `D#` em `docs/tecnica/00`
§13.3 com dono e escalada, e ticket em `specs/EPIC-10`.

---

## Verificação por máquina

**A verificação é por máquina, não por leitura.** Nesta sessão, ler os relatórios de cinco
redactores não apanhou nenhuma das ~60 dependências em falta; um script apanhou todas, mais dois
ciclos e doze inversões de prioridade. O princípio: tudo o que é estrutura — referências,
grafos, contagens, sintaxe — verifica-se por execução.

O que compensa sempre verificar neste conjunto:

| Verificação | O que apanha |
|---|---|
| **Referências** | `KAM-NNN`, `ADR-NNN`, `D#`, `H#`, `E#` e caminhos citados que não existem |
| **Grafo do backlog** | ciclos, prioridade invertida (P0←P1), fase invertida (F0←F1), dependências inexistentes |
| **Unicidade** | cada ticket com exactamente um bloco `## KAM-NNN — ` em todo o conjunto |
| **Sincronia mestre↔epics** | tipo, estimativa, prioridade, fase, dependências e `Bloqueia` iguais nos dois lados |
| **Mermaid** | diagramas que não compilam (escrever sem acentos nos IDs não prova nada) |
| **Contagens** | «20 ADRs», «161 tickets», «11 epics», totais por epic, números nos índices |
| **Nomes canónicos** | tabelas, colunas, eventos e estados fora do dicionário — gate 3b activo: `make ci-3b`, ou `python -m canon_lint --root .. check` |

Duas disciplinas sobre os scripts:

- **Corre em modo de verificação antes de escrever.** Um script que corrige e verifica ao mesmo
  tempo esconde o que estava errado. Primeiro lista os erros; só depois aplica.
- **Repete até estabilizar.** Uma verificação que muda alguma coisa na segunda passagem não é
  uma verificação, é uma edição. A sincronia mestre↔epics tem de dar zero divergências à segunda.

Os scripts vivem no scratchpad da sessão enquanto são *ad-hoc*. Um que se mostre útil mais de uma
vez pertence ao repositório — é o que KAM-002 e KAM-111 prometem.

---

## Como correr a verificação aqui

**O `Makefile` é a fonte do que cada gate faz, e não a forma de o correr.** Ele pressupõe
`make`, `node` e `pnpm` no `PATH`, e na máquina de desenvolvimento deste projecto **não há
nenhum dos três** — nem no PowerShell nem no Git Bash, e a única «distro» WSL é a do Docker
Desktop. Um `make ci-2` responde `make: command not found` e isso **não** significa que o gate
passa: significa que não correu.

Medido a 2026-10-19, no KAM-013. As quatro vias, por ordem de quanto custam:

| O que verificar | Como se corre |
|---|---|
| Linters Python (gates 2, 3, 3b, 3c, 9, 11) | O Python do Windows, directamente: `python -c "import sys; sys.path.insert(0,'tools'); from <modulo> import cli; sys.exit(cli.main(['--root','.','check']))"`. Só biblioteca padrão, segundos |
| *Build*, tipos e testes Node (gates 1, 2, 4) | Em contentor, com a árvore montada: `docker run --rm -v <arvore>:/w -w /w node:24.21.0-alpine sh -c "corepack enable; pnpm install --frozen-lockfile --ignore-scripts; pnpm run build; pnpm -r run typecheck; pnpm -r run test"`. O `pnpm install` leva ~2 min e só se faz uma vez por árvore |
| Gates de base de dados (6 e 8) | `.venv/Scripts/python.exe db/gate_bd.py --suite <nome>`. O `gate_bd.py` levanta os seus próprios contentores de PostgreSQL e Valkey e apaga-os no fim |
| Cobertura (gate 4) | O LCOV produz-se em contentor; o `tools/coverage_gate.py` corre **fora** dele, com o Python do Windows |

Quatro armadilhas que custaram tempo, e todas na forma «passou» quando não passou:

1. **O código de saída tem de ser do comando, não do `tail`.** `python -c "..." 2>&1 | tail -5; echo $?`
   devolve o estado do `tail`, que é sempre 0. Três lints pareceram conformes assim, e um deles
   estava a sair com 2. Correr para um ficheiro e ler o `$?` **antes** do pipe.
2. **O `lint_contagens` não corre de dentro de um *worktree* sob `.claude/`.** Exclui qualquer
   ficheiro cujo caminho **absoluto** contenha `.claude`, e a árvore de trabalho vive lá: a
   varredura vê **zero** ficheiros e sai com 2. É a dívida 44 de `docs/dividas-documentais.md`.
   Mede-se chamando `varrer_arvore` com raiz **relativa**.
3. **O `coverage_gate.py` não arranca em Python 3.14** (uma cadeia de ajuda com `%o` que o
   `argparse` passou a validar). O contentor `node:24.21.0-alpine` traz 3.14; o CI usa 3.12 e não
   vê nada. Dívida 45.
4. **O `pathlib.write_text` em Windows escreve CRLF.** O `.gitattributes` normaliza no *commit*,
   mas o `git diff` do teu trabalho mente até lá. Normaliza para LF os ficheiros tocados antes de
   commitar, ou lês um diff que não é o teu.

E a disciplina que fecha a secção: **o `.venv` e o `node_modules` não existem numa árvore nova.**
Um *worktree* recém-criado precisa de `python -m venv .venv` com os três `pip install
--require-hashes` do alvo `$(VENV)/.stamp`, e de um `pnpm install` em contentor. São uns minutos,
pagam-se uma vez, e sem eles metade dos gates não arranca — o que é diferente de falhar.

---

## O que ainda não existe

Esta secção dizia, até 2026-10-19, que o repositório «não tem código nem CI». **Deixou de ser
verdade e contradizia o `SKILL.md` ao lado**, que já afirmava «CI desde o KAM-002» — é a classe de
defeito que esta *skill* existe para fechar, e estava dentro dela. Fica corrigida, e fica a nota de
que estava errada, porque apagar um erro sem o nomear é o mesmo defeito ao contrário.

O que é verdade hoje:

1. **O CI existe e bloqueia.** Dos 18 gates de `specs/01_Engineering_Standards_e_Handoff.md` §4
   correm os que `docs/ci.md` §3 lista, e **onze bloqueiam o merge** pela porta final «gates do
   KAM-002». Os restantes continuam a ser o alvo. **Dois pormenores que enganam:** o *gate* 5 está
   **reservado e falha de propósito** — tem `continue-on-error` e não está no `needs` da porta
   final —, pelo que um PR com o gate 5 vermelho e tudo o mais verde está pronto a fundir; e um
   gate novo que entre no `needs` tem de entrar também no `esperados=N` escrito à mão dessa porta,
   senão ela falha.
2. **A auditoria de changeset é obrigatória.** `git status --short` e `git diff --stat` comparam o
   que mudou com o que era suposto mudar. Uma edição em lote por script fecha com a leitura do
   diff, não com a confiança no script. O `.gitattributes` fixa LF para que um documento não
   apareça alterado por inteiro sem razão.
3. **O SQL já corre, e o que não corre diz-se.** As revisões de `db/migrations/` são aplicadas,
   revertidas e reaplicadas contra um PostgreSQL 18.6 descartável pelo *gate* 8, com inventário
   fechado de colunas e matriz de privilégios. O que continua a ser **proposta de esquema** é o
   DDL que vive em documento e nunca passou por uma revisão — e isso escreve-se onde aparece.

---

## Revalidação

Evidência tem prazo. O conjunto fixou revalidação trimestral (watch list em `docs/tecnica/09`), e os
itens com maior taxa de decaimento são:

- **rate cards e política da Meta** — mudaram em Outubro de 2026 e voltam a mudar;
- **Embedded Signup e modelo de contas** — versões com data de fim anunciada;
- **licenças e manutenção de dependências** — MinIO arquivou, remove.bg muda de dono, LiteLLM
  teve ataque de supply chain;
- **preços de LLM e de imagem** — incluindo promoções com data de fim;
- **legislação angolana** — projectos de lei de dados e de IA sem aprovação confirmada;
- **câmbio** — receita em Kz, custos em USD.

Antes de usar uma afirmação deste conjunto em contrato, preço ao cliente ou parecer,
**reconfirma-a na fonte primária**. A data está em cada anexo por essa razão.
