# ANÁLISE-17 — Revisão adversarial do KAM-150 (`CODEOWNERS` no prefixo removido)

| Campo | Valor |
|---|---|
| Ticket | KAM-150 — Regras de `CODEOWNERS` penduradas no prefixo que o KAM-128 removeu |
| Ramo | `fix/KAM-150-codeowners-no-prefixo-removido` |
| *Baseline* revista | `fbf7bce`, sobre `f10bde8`; a revisão corre antes da integração de `origin/main` (`f4c7e3d`) |
| Data | Outubro 2026 |
| Revisão | Um subagente independente, com os requisitos e o *diff* e **sem** as justificações de quem escreveu a alteração |

> **Nota sobre a numeração — e é o próprio defeito desta revisão.** O ticket
> nasceu com o identificador **145** e esta análise com o **16**. A revisão mediu que **os dois
> números estavam tomados**: o 145 por `feature/…145…-lacunas-documentais-do-kam-128`
> (que reclama também 146 e 147) e a `ANALISE-16` por
> `feature/KAM-005-outbox-e-publicador`. Renumerou-se para **KAM-150** e
> **ANALISE-17**, os primeiros livres medidos sobre `refs/heads`, `refs/remotes`
> e os nomes de ramo. Se uma vaga paralela levar o 149 primeiro, renumera-se na
> integração, como as linhas de versão.

---

## 1. O que esta revisão procurou

O ticket é pequeno — três caminhos num `CODEOWNERS` — e é precisamente por isso
que vale a pena ser duro com ele. A premissa que o justifica é: **um caminho que
não resolve não cumpre a função do ficheiro, e falha em silêncio**. Um ticket com
essa premissa que entregue caminhos que não resolvem falha pela sua própria
medida.

Por isso a revisão não perguntou «os três caminhos estão certos?». Perguntou:

- O ID é mesmo livre, ou o ticket reproduz a colisão que diz evitar?
- Que caixa marcada pode estar satisfeita **pela razão errada**?
- Que afirmação do changeset não reproduz quando se corre o comando que ela cita?
- Que documento do conjunto fica a contradizer-se **depois** da correcção?
- A emenda a `seguranca/` baixou algum risco, estado ou nível que não devia baixar?
- Há outro caminho funcional da mesma classe, que este ticket devia ter apanhado?

## 2. Veredicto da revisão independente

```
REPROVADO — 3 achados P0, 3 P1, 5 P2
```

O juízo central da revisão, citado: a correcção material do `CODEOWNERS` está
certa e bem medida, e **o ticket falhava no mesmo tipo de defeito que existe para
corrigir** — o seu ID não estava livre, e ele próprio introduzia os únicos
caminhos quebrados do repositório, com a caixa «Referências» marcada. O gate 3
estava **vermelho** no ramo e verde em `main`.

## 3. Achados, e o que se fez com cada um

| # | Sev. | Achado | Disposição |
|---|---|---|---|
| A1 | **P0** | **O ID não estava livre.** O 145 estava reclamado por `feature/…145…-lacunas-documentais-do-kam-128` (em *worktree* activo, e que reclama também 146 e 147). O §5.1 da evidência afirmava, com o comando nomeado, que «o máximo é 144 e 145 não aparece em lado nenhum» — **as duas metades falsas**. E o 144 tem quatro reclamantes, não dois | **Aceite.** Renumerado para **KAM-150**, o primeiro livre medido sobre todas as refs **e** os nomes de ramo (144 a 148 reclamados). §5.1 reescrito com a medição certa; o §1 e a linha 1.10 de `specs/INDICE.md` deixam de guardar estado de PRs, que muda sozinho (ver A8) |
| A2 | **P0** | **O gate 3 estava vermelho: 7 referências inválidas**, e a caixa de DoD «Referências» estava marcada com a evidência «gate 3 conforme». Cinco intervalos nus o intervalo contínuo até 145 sobreviveram no bloco do epic e no ficheiro de evidência, mais duas citações do identificador 144 como *token* | **Aceite, e é o achado mais instrutivo.** A causa raiz: o gate correu **antes** de o bloco do ticket e o ficheiro de evidência serem escritos, e a conformidade foi afirmada de memória sobre ficheiros que ainda não existiam. O §5.2 da evidência explicava este padrão exacto e repetiu-o. Corrigido; a verificação passou a correr **depois** de toda a redacção |
| A3 | **P0** | **Quatro ligações para a análise adversarial, que não existia** — as únicas ligações markdown quebradas que o changeset acrescentava ao conjunto, com a caixa dos caminhos marcada. E o número `ANALISE-16` estava tomado | **Aceite.** Este ficheiro é a resposta: existe, com o número livre **17**, e as quatro ligações passam a resolver |
| A4 | **P1** | **O CA 4 estava satisfeito pela razão errada.** A busca que o provava (`grep … docs/`) não cobria `specs/`, e duas linhas vivas do bloco do KAM-128 — na **mesma secção** que o âmbito nomeia — continuavam a afirmar o defeito no presente | **Aceite.** As duas emendadas: a linha do DoD passa a dizer que tinha **duas** causas, que esta fechou e que **a caixa continua vazia** pelas 7 referências nuas; a citação de fecho passa a dizer que as três regras foram corrigidas depois |
| A5 | **P1** | **Colisão de número de versão:** o ramo acrescentava `1.16` ao EPIC-01 e `main` já tinha `1.16` (KAM-132, PR #41) | **Aceite.** `origin/main` integrado por *merge*; a linha de `main` fica intacta e a deste ticket passa a **1.17** |
| A6 | **P1** | **O ramo não estava «um commit à frente»: estava 1 à frente e 7 atrás**, e `main` tinha tocado dois dos ficheiros do changeset | **Aceite.** `origin/main` integrado; cabeçalhos corrigidos |
| A7 | P2 | «A organização `kamba` não existe», sustentado por um 404 — **indício promovido a facto**: sem *scope* `admin:org`, o 404 é indistinguível de «existe e não a vejo» | **Aceite.** A linha passa a «não é visível a este *token*», marcada **INDÍCIO**, e diz que a conclusão não depende dela: o facto decisivo é `isInOrganization: false` |
| A8 | P2 | O §1 do backlog mestre passou a conter **estado efémero de PRs**, que muda sozinho e já era falso | **Aceite.** Substituído pelo facto permanente (144 a 148 reclamados em voo); o detalhe de quem reclama o quê vive na evidência, não no canon |
| A9 | P2 | A linha «Backlog sincronizado e contagens» do KAM-128 dizia «hoje dizem 130» — meia-verdade antes, inteiramente falsa depois de o `README.md` ir a 144 | **Aceite.** Emendada, com o atraso de 13 nomeado |
| A10 | P2 | **`db/gate8.py`** é um caminho funcional pendurado da **mesma classe** (o ficheiro é `db/gate_bd.py`), em `seguranca/matriz_conformidade.csv`, em `ameacas_stride.md` e em `db/tests/base.py`. O `docs/seguranca/validar.py` apanha-o quando se relaxa o `assert` da contagem | **Registado, não corrigido.** A parte documental já é a linha 6 de `dividas-documentais.md`; a de `db/tests/base.py` é código e fica para ticket próprio. Fora do âmbito deste `fix`, que é o prefixo `/tecnica/` |
| A11 | P2 | O parágrafo novo do `CODEOWNERS` repetia o aviso que já estava; a informação nova eram três factos | **Aceite.** Reduzido de 6 linhas a 5, só com os três factos medidos; o aviso original fica intacto |

### 3.1 O que a revisão mudou, em números

| Medida | Antes da revisão | Depois |
|---|---|---|
| Gate 3 | **7 referências inválidas** | conforme |
| Ligações markdown novas quebradas | **4** | 0 |
| ID do ticket | 145 (**reclamado** por outro ramo) | KAM-150 (livre em todas as refs) |
| Número da análise | ANALISE-16 (**reclamado**) | ANALISE-17 |
| Linha de versão do EPIC-01 | 1.16 (**colide** com `main`) | 1.17 |
| Posição face a `origin/main` | 1 à frente, **7 atrás** | integrado |
| Afirmações que não reproduziam | **4** | 0 |
| Linhas do conjunto a contradizer o changeset | **2** (bloco do KAM-128) | 0 |

## 4. O que a revisão confirmou

Vale dizê-lo, porque é a parte do ticket que estava bem e foi medida de novo,
por comando, por quem não a escreveu:

- **18** regras não-comentário, antes e depois; **3** penduradas em `main`, **0**
  no ramo; os mapas padrão→donos idênticos nos dois lados; **6** equipas
  distintas, nenhuma alterada.
- **A ordem das regras preservada** — e isto importa: em `CODEOWNERS` vence a
  **última** regra que casa, pelo que `/docs/tecnica/08_Seguranca_Conformidade.md`
  tem de vir depois de `/docs/tecnica/` para não ser engolida. Vem (linhas 32, 33,
  34). A revisão verificou-o; o ticket não o tinha afirmado.
- **0** regras com curingas, com a ressalva do método escrita — a equivalência
  «padrão resolve ↔ caminho existe» vale hoje e está medida, não assumida.
- `isInOrganization: false`, e o *ruleset* **vivo** (não só o espelho em
  `.github/rulesets/main.json`) com `require_code_owner_review: false` e 0
  aprovações: a revisão consultou `gh api repos/albinoJimy/kamba/rulesets/…` e os
  dois concordam.
- **144/144** linhas e blocos na base revista (`fbf7bce`; hoje **145/145**, depois
  de o PR #44 pôr o 144 em `main`), 0 órfãos, 0 duplicados, 0 divergências de
  sincronia, 0 ciclos, 0 inversões de prioridade ou de fase, reciprocidade com o
  `Bloqueia` do KAM-128 fechada; todas as contagens coerentes entre si.
- **Nenhum risco, estado ou nível baixou** em `seguranca/`: RR-05 continua
  Alta/Médio/Alto e «por decidir»; GOV-T continua `ET + NE + EN`; L-19 continua
  aberta, com o remédio de três partes reduzido a duas.
- O âmbito excluído ficou **intacto**: as caixas das referências nuas e das
  linhas de versão do KAM-128 continuam vazias, nenhum dos 11 documentos sem
  linha de versão foi tocado, e nada em `.github/`, `tools/`, `ci/` ou `db/`.
- Os resíduos de prosa `tecnica/NN` são exactamente os três ficheiros da raiz que
  a dívida 19 nomeia (7 ocorrências), e **nenhum** é caminho funcional.

## 5. O padrão que este ticket repetiu, e que vale registar

Três dos achados (A2, A3, e metade do A1) são **a mesma falha de método**:
afirmar por memória o resultado de uma verificação que correu num momento
anterior, sobre uma árvore que mudou depois.

- O gate 3 correu quando `specs/INDICE.md` estava escrito e o bloco do epic e o
  ficheiro de evidência **ainda não existiam**. Foram esses dois que o puseram
  vermelho.
- A varredura de IDs correu antes de o ramo vizinho ter commit, e a conclusão
  («145 não aparece em lado nenhum») foi escrita como se fosse permanente.
- A ligação para a análise foi escrita antes de a análise existir, e a caixa dos
  caminhos foi marcada ao mesmo tempo.

A regra que isto sustenta, e que a *skill* já diz noutras palavras: **a
verificação corre depois da última linha escrita, e o número que vai para o
documento é o dessa passagem.** Uma verificação a meio da redacção é um ensaio,
não evidência. É o mesmo princípio que a *skill* escreve para a sincronia
(«corre até estabilizar») aplicado ao próprio changeset.

## 6. O que **não** foi verificado

- **Os gates que exigem rede, Docker ou `pnpm`:** 1 (build), 2 (lint e tipos), 4
  (cobertura), 8 (base de dados), 9 (segredos), 11 (SCA/SBOM). Correram-se os de
  biblioteca padrão: gate 3 e `lint_arch all`. **O CI do PR é a medição que
  falta.**
- **O gate 3b** (nomes canónicos) não foi corrido pela revisão.
- **Se algum dos ramos que reclamam 144 a 148 desiste do seu ID.** A colisão é um
  facto medido; qual ticket fica com qual número é de quem integra, não de uma
  medição. Daí a decisão estar escrita em vez de herdada.
- **A revisão não leu linha a linha** os 267 do ficheiro de evidência nem os 222
  novos do epic: verificou estrutura, números, caixas, ligações, contagens e cada
  afirmação verificável por comando.
- `require_extra_approval_for_unattributed_changes: true` existe no *ruleset*
  vivo e nenhum documento do conjunto o menciona. Não afecta as afirmações deste
  ticket. **NÃO VERIFICADO** o que faz na prática.

## 7. Controlo de versões

| Versão | Data | Alteração | Autor |
|---|---|---|---|
| 1.0 | Outubro 2026 | Emissão: revisão adversarial independente do KAM-150 (nascido com o número 145), com 3 achados P0, 3 P1 e 5 P2, a disposição de cada um, e o padrão de método que três deles partilham. | Equipa KAMBÁ |
