# Revisão de segurança independente — relatório

| Campo | Valor |
|---|---|
| Ticket | KAM-074 |
| Âmbito | [`escopo.md`](escopo.md) |
| Re-teste | [`reteste.md`](reteste.md) |
| Decisão | [`decisao.md`](decisao.md) |
| Revisor | **por registar** (ver §2) |
| Medido sobre | **por registar**: o *commit* da `main` e a imagem de cada serviço em `staging`, por *digest* |
| **Estado** | **Formato, sem conteúdo.** Preparado sem o mundo real (lote 24); nenhum achado, nenhuma revisão feita. |

Este ficheiro é o **sítio e o formato** onde o relatório do revisor fica registado. Hoje está
vazio de propósito: as tabelas abaixo têm só o cabeçalho, e quem as preenche é o revisor (as
secções 2 a 5) e o Responsável de Segurança (a secção 6).

## 1. O que é público e o que não é

O repositório é **público**. A regra que este relatório segue é a que o red-team do AGR já
seguiu ([`../redteam/relatorio.md`](../redteam/relatorio.md) §2):

- **Aqui fica** a classe de cada achado, a severidade, o componente, o controlo violado, o dono,
  o prazo, o ticket `fix` e o estado. É o que o critério de classificação do bloco pede, sem a
  receita.
- **Fora do repositório público** fica a **reprodução** de cada achado ainda aberto — os passos,
  o pedido, o *payload* —, num ficheiro de trabalho guardado com o fundador, até o fundador
  decidir se achados abertos de uma revisão podem ser públicos. A decisão está **aberta** desde o
  KAM-073 (critério 6 do bloco dele) e esta preparação não a toma.
- **Nunca** entram, nem aqui nem nos anexos: segredos (de `staging` ou de `prod`), *tokens*,
  URLs assinadas válidas, telefones (nem os fictícios: uma reprodução que precise de um fica
  fora do repositório), NIF, IBAN, nomes ou outros dados pessoais.
- **O que verifica isto, e o que não verifica.** O [`../validar.py`](../validar.py) procura
  padrões de telefone nos `.md` desta pasta, mas corre-se à mão — não está em nenhum *gate* — e
  não apanha um número escrito com espaços ou hífenes. Segredos varre-os o gate 9, na árvore e
  na história. O resto é leitura do Responsável de Segurança antes de cada versão.

## 2. O revisor

O critério de independência do bloco pede **identidade, qualificações e data** registadas. A
identidade e as qualificações são dados pessoais de um terceiro; **onde ficam é decisão em
aberto**, e a proposta desta preparação é a forma conservadora:

| Campo | Onde fica | Valor |
|---|---|---|
| Referência do revisor | aqui | `R1` (e `R2`… se houver mais do que um) |
| Identidade e qualificações | fora do repositório público, com o fundador (*proposta*) | — |
| Data de início e de fim | aqui | — |
| Declaração de independência (não é autor do código do âmbito) | aqui, com a verificação feita | — |
| Revisão cruzada por engenheiro não-autor, em substituição | aqui, com a ligação ao risco aceite em [`decisao.md`](decisao.md) §3 | — |

**Como se verifica a independência**, e não só se declara: o Responsável de Segurança confirma
que a identidade do revisor não aparece nos *commits* dos caminhos do âmbito — **nem como autor
nem como co-autor**, porque as fusões deste repositório põem quem escreveu no *trailer*
`Co-authored-by` e não no campo do autor:
`git log --format='%an %ae%n%(trailers:key=Co-authored-by,valueonly)' -- <caminhos>`. Regista aqui
**o resultado** («0 *commits* do revisor nos caminhos do âmbito, autor ou co-autor»), sem copiar
a lista de autores.

## 3. Achados

**Severidade.** O bloco pede quatro classes — crítico, alto, médio, baixo. A única
correspondência que a letra fixa é a das classes P1 do
[`../../tecnica/08_Seguranca_Conformidade.md`](../../tecnica/08_Seguranca_Conformidade.md) §10
(fuga cruzada, chave comprometida, confirmação de pagamento forjada): **um achado desse tipo é
crítico**. A correspondência das outras três classes (alto ↔ P2, médio ↔ P3, baixo ↔ P4) é
**proposta** desta preparação e não está decidida; até estar, o revisor classifica pelos seus
critérios e escreve-os na secção 5.

Uma linha por achado. O identificador é `RI-NN`, sequencial, e nunca se reutiliza.

| Achado | Sev. | Componente | Área do âmbito | Controlo violado (linha da matriz do KAM-065) | Classe (sem receita) | Reprodução | Dono | Prazo | Ticket `fix` | Estado |
|---|---|---|---|---|---|---|---|---|---|---|

Os valores fechados de cada coluna:

- **Sev.:** `crítico`, `alto`, `médio`, `baixo`.
- **Componente:** um código da tabela de componentes de
  [`../../tecnica/00_Arquitectura_Solucao.md`](../../tecnica/00_Arquitectura_Solucao.md) (os
  mesmos que a matriz usa).
- **Área do âmbito:** o número da área em [`escopo.md`](escopo.md) §2.
- **Controlo violado:** o `id` da linha da matriz de conformidade do KAM-065. A matriz não vive
  neste repositório ([`../matriz_conformidade.csv`](../matriz_conformidade.csv) é um esboço que o
  diz); o `id` cita-se, o conteúdo da linha não se copia. Um achado sem linha correspondente
  escreve `sem linha` — e isso é, por si, um achado sobre a matriz, que vai para a secção 6.
- **Reprodução:** onde ela está, nunca ela própria — `fora do repositório` com a referência do
  ficheiro de trabalho guardado com o fundador (sem caminho de máquina nem endereço). O critério
  de classificação do bloco pede reprodução para cada achado, e esta coluna é o que o demonstra
  a partir daqui.
- **Estado:** `aberto` (um médio só com plano, dono e data preenchidos), `registado` (baixo),
  `corrigido — por re-testar`, `fechado` (só depois de [`reteste.md`](reteste.md) o registar).
  O bloco não prevê aceitar um médio sem correcção, e esta tabela não lhe dá estado para isso.

## 4. Testes de exploração obrigatórios

O bloco exige os seis primeiros, no mínimo; o sétimo é proposta desta preparação. Cada um tem
resultado registado, **incluindo quando não
encontrou nada** — um «não testado» não se lê como «passou».

| # | Teste | Área do âmbito | Resultado (`sem achado` / `RI-NN` / `não testado`, com a razão) |
|---|---|---|---|
| E1 | *Cross-tenant* autenticado como A contra B | 1 | — |
| E2 | `SECURITY DEFINER` fora da lista | 2 | — |
| E3 | *Callback* com HMAC adulterado e *replay* de corpo válido | 3 | — |
| E4 | Imagem de comprovativo como prova de pagamento | 5 | — |
| E5 | URL assinada de media de outro *tenant* | 1 | — |
| E6 | Extracção de segredos do ambiente de contentores | 6 | — |
| E7 | Privacidade: os canários de dados pessoais do *tenant* B não aparecem em logs, *traces*, respostas de erro nem ficheiros de media acessíveis a A (*proposta*: a DoD do bloco pede a Privacidade confirmada por testes de exploração, e nenhum dos seis cobre a área 12) | 1, 12 | — |

## 5. Método e ferramentas

O revisor descreve aqui o método (manual, ferramentas, versões), o tempo gasto e o que ficou
fora do que ele conseguiu testar. Sem nomes de produtos escolhidos por esta preparação: a
escolha é do revisor.

## 6. Para o Responsável de Segurança

Preenche-se depois do relatório:

- o resumo por severidade (abertos, registados, corrigidos por re-testar, fechados);
- os achados sobre a própria matriz (linhas em falta, testes que não existem);
- a actualização do registo de riscos residuais do KAM-065, que vive fora deste repositório
  ([`../riscos_residuais.md`](../riscos_residuais.md) é um esboço): aqui regista-se **que** foi
  actualizado e em que data, não o conteúdo.

## 7. Dos achados aos tickets `fix`

O bloco não deixa corrigir achados dentro do KAM-074: **cada um vira `fix` com DoR e DoD
próprios**. O procedimento, por ordem:

1. **Confirmar sem filtrar** (*proposta*). Quem abre o `fix` reproduz o achado onde ele vive —
   no código da `main`, ou em `staging` se for de configuração ou de ambiente — para escrever o
   ticket com o que mediu. **Uma reprodução que falha não descarta o achado:** fica `aberto`,
   volta ao revisor, e só ele o retira. A equipa interna não filtra os achados da revisão
   independente.
2. **Um `fix` por achado.** O bloco diz que cada achado vira `fix`, e não que se encosta a um
   ticket aberto. Se um ticket aberto já toca no mesmo controlo, o `fix` cita-o no contexto.
3. **Número.** O menor número livre, medido nas três fontes: o maior `KAM-NNN` do §4 de
   [`../../../specs/INDICE.md`](../../../specs/INDICE.md) na `publico/main`, os títulos dos PRs
   abertos e os ramos empurrados. Quem funde com o número mais alto espera pelo mais baixo.
4. **As superfícies do ticket novo, num só PR:** a linha do §4 do INDICE, a gama do §1 e a da
   tabela §3.1, a linha da tabela-resumo do epic dono do componente e o bloco no epic, com
   `Tipo` = `fix`, a `Dependências` e o `Bloqueia` recíprocos, a contagem viva do backlog onde
   ela é citada (a nota do `assert` do EPIC-07, o README) e a linha de versão de cada documento
   tocado. Verde em `lint_backlog`, `lint_refs` e `lint_contagens` antes de empurrar: são eles
   que apanham a superfície que esta lista esqueça.
5. **A ligação ao KAM-074** (*proposta*, a confirmar pela coordenação):
   - **crítico e alto:** o `fix` é P0 e fase 1, e não depende do KAM-074 — a correcção tem de
     fundir **antes** de o KAM-074 fechar. O KAM-074 ganha o `fix` nas suas `Dependências`, para
     que o `vagas.py` e o gate do Piloto o vejam. **As dependências do próprio `fix`** só podem
     ser tickets fechados ou P0: o `lint_backlog` recusa um P0 a depender de um P1, e os tickets
     naturais de algumas áreas (pagamentos, rotação de chaves) são P1. E nenhuma delas pode
     depender, directa ou transitivamente, do KAM-074, senão é ciclo;
   - **médio e baixo:** o `fix` depende do KAM-074, como o KAM-189 depende do KAM-073; o KAM-074
     pode fechar com eles abertos, os médios com plano, dono e data.
6. **O que o bloco do `fix` diz e não diz.** O contexto descreve a classe e o controlo violado,
   com o identificador `RI-NN`; a reprodução de um achado aberto não entra no bloco público (§1).
   O critério de aceitação inclui um ensaio que falha no código de antes da correcção, e a
   ligação ao re-teste do revisor ([`reteste.md`](reteste.md)) para crítico e alto.
7. **Depois da fusão do `fix`,** a linha da secção 3 passa a `corrigido — por re-testar`, e só
   uma linha em [`reteste.md`](reteste.md) a passa a `fechado` — feita pelo revisor para crítico
   e alto, e pelo revisor ou pela equipa, dito qual, para médio e baixo (*proposta*: o bloco só
   exige o revisor nos críticos e altos).

## Controlo de versões

| Versão | Data | Alteração | Autor |
|---|---|---|---|
| 0.1 | 2026-11-25 | Formato preparado sem o mundo real (KAM-074, lote 24): o que é público, o registo do revisor, a tabela de achados, os seis testes de exploração do bloco e um de privacidade proposto, e o procedimento dos achados aos tickets `fix`. Nenhum conteúdo de revisão. | Coordenação do lote 24 |
