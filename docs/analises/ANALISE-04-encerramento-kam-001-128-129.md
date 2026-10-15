# Análise Adversarial do Encerramento dos KAM-001, KAM-128 e KAM-129 (ANALISE-04)

| Campo | Valor |
|---|---|
| Objecto | A marcação das 48 caixas de Critérios de Aceitação e Definition of Done dos KAM-001, KAM-128 e KAM-129 em `../../specs/EPIC-01_Fundacoes_Dados.md`, e as três secções `### Verificação dos Critérios de Aceitação` acrescentadas. Changeset `1401cd3..1ef09e7`, ramo `feature/KAM-001-encerramento-com-evidencia` |
| Método | Três revisores independentes, em paralelo, com âmbitos disjuntos e sem acesso ao raciocínio de quem marcou: (A) as 13 caixas do KAM-001; (B) as 35 caixas do KAM-128 e do KAM-129; (C) o changeset como alteração documental (regressão, referências, forma, convenções). Cada revisor re-mediu com instrumentos próprios e foi instruído a tratar cada número das secções como **alegação a falsificar**. Achados classificados P0 (a marcação engana) / P1 (evidência insuficiente ou imprecisa) / P2 (dívida ou imprecisão menor) |
| Data | 2026-10-11 |
| Classificação | Interno — auditoria |

> **Nota de declaração, para o gate 3 (KAM-002).** Este documento cita, de propósito, **15
> caminhos distintos que não resolvem** (21 ocorrências), porque são o seu objecto: referências
> nuas a anexos de evidência, entregas futuras de outros tickets, e dois ficheiros de evidência
> que os DoD nomeiam e que não existem. Não se pode relatar uma referência quebrada sem a
> escrever. É a mesma excepção que o `../../specs/EPIC-01_Fundacoes_Dados.md` já usa para as suas
> tabelas de correcção histórica, e é nova em `../analises/`: a `ANALISE-01` tem zero. **Quando o
> gate 3 entrar, este ficheiro precisa de uma entrada própria em `ci/refs-allow.yaml`** — por
> caminho e com esta razão. Nenhuma das citações é uma ligação markdown: todas são *code-span*, e
> o resolvedor de ligações do KAM-128 dá 0 quebradas no conjunto.

---

## 1. Sumário executivo

**Veredicto: APROVADO APÓS REMEDIAÇÃO DOS P0. Quatro caixas tiveram de ser desmarcadas.**

A revisão confirmou a parte que mais importa: das **37** linhas eliminadas pelo changeset,
**37 casam carácter a carácter** com as inserções depois de trocar o marcador — **nenhum texto de
critério foi reescrito para o fazer bater**, que é o pior defeito possível neste trabalho e não
está presente. Dos cerca de 45 números que as três secções afirmam e que os revisores
conseguiram medir, **todos bateram**, incluindo os difíceis: 25/15/18/1, `+57 −51`, 51/51 mais 6,
7 linhas com 8 referências excedentes, 34 linhas `R100` e 0 `M`, 216 → 0, 3 → 0, 17/10/7, 15 e 2,
13 partes, 15/4/11, 130 blocos com 0 falhas de reciprocidade e 0 divergências de sincronia.

E confirmou que o erro estava onde o custo de o admitir era maior. **Quatro caixas estavam
marcadas sem o sustentar**, todas pelo mesmo mecanismo — a medição cobria uma população mais
estreita do que a que o critério nomeia:

| Caixa | Porque não se sustentava |
|---|---|
| KAM-001 CA1 | «arranca com `make up`» nunca foi executado, e o SHA que a prova mostra foi injectado à mão — o contrato aceita `unknown` |
| KAM-129 CA1 | G1 dá 0, mas G1 ancora no literal `evidencia/` e não vê três referências a anexo citadas sem prefixo nenhum |
| KAM-129 CA4 | «toda a referência de classe A resolve em disco» é falso: as mesmas três não resolvem |
| KAM-129 DoD «Referências» | «todo o caminho citado em `specs/` resolve» é falso: 61 caminhos distintos não resolvem |

**O padrão, dito sem atenuantes:** quem marcou foi severo consigo mesmo onde a severidade não
custava caixa (deixou a CA2 do KAM-001 vazia por «uma execução, não uma distribuição», e a DoD3
por 2 *commits* em 10) e indulgente nos quatro sítios onde custava. A régua que o próprio
documento invoca — cumprir à letra, não em espírito — foi aplicada de forma desigual. Esse é o
achado desta análise, mais do que qualquer um dos quatro casos.

Distribuição: **P0 ×4 · P1 ×8 · P2 ×12**. Os P0 foram remediados no mesmo ramo; os P1 de evidência
foram corrigidos no texto; os defeitos documentais que a revisão revelou e que estão **fora do
âmbito** deste encerramento ficaram inventariados no §5, para ticket próprio.

---

## 2. Achados P0 — a marcação enganava

### ADV-02-01 · KAM-001 CA1: dois dos três conjuntos não demonstrados

**Caixa:** «Existe a árvore …; cada serviço expõe `/healthz` (200 com versão e SHA do commit) **e
arranca com `make up`**.» Estava `[x]`.

**Evidência que a sustentava:** a pilha levantada pelo comando que o alvo `up` embrulha, e
«5 servico(s) conformes ao contrato».

**O que a revisão mediu.** O `Makefile` (alvo `up`) faz quatro coisas que o comando corrido não
faz: guarda de `docker`, guarda de `.env`, **derivação de `KAMBA_COMMIT_SHA` a partir de
`git rev-parse HEAD`**, e encadeamento de `$(MAKE) smoke`. E o contrato
`packages/contracts/schemas/healthz.response.v1.json` tem, para `commit`, o padrão
`^(?:[0-9a-f]{40}|[0-9a-f]{7,12}|unknown)$` — **aceita `unknown`**, com a descrição a dizer que
«exigir um SHA real nas imagens publicadas é do KAM-002». O `tools/healthz_check.py` valida o
corpo contra o esquema e confere o nome do serviço, e nada mais.

**Consequência.** O conjunto do SHA foi verificado por um contrato que o torna opcional, e o SHA
real apareceu porque o operador o injectou — que é exactamente o trabalho que `make up` automatiza
e que não foi testado. O risco não é teórico aqui: `../evidencia/KAM-001-node.md` §7.3 regista
dois defeitos de `Makefile` que «estiveram assim e nunca correram».

**Remediação:** caixa vazia, estado `parcial`, com os dois conjuntos em falta nomeados.

### ADV-02-02 · KAM-129 CA1: a busca não vê a classe que o critério nomeia

**Caixa:** «**Zero referências a evidência sem directório qualificador em `specs/`**: a busca G1 dá
0.» Estava `[x]`.

**O que a revisão mediu.** G1 reproduz-se perfeitamente: 59 em `6d30625`, `08426f3` e `bebe2ae`;
**0** hoje. Mas G1 ancora no literal `evidencia/`, pelo que uma referência a anexo **sem directório
nenhum** é estruturalmente invisível para ela. Em `specs/EPIC-10_Spikes_Validacao_Gates.md:11`, na
linha «Documentos relacionados», há **três**: `E2_Pagamentos_Angola.md`, `E3_Regulatorio_Dados.md`
e `E4_Stack_Licencas.md`, citadas nuas depois de uma quarta que traz o prefixo correcto. Não
resolvem nem de `specs/` nem da raiz. **Idênticas em `6d30625`** — defeito pré-existente, da mesma
família que o ticket diz fechar, no mesmo ficheiro que o ticket editou 27 vezes.

O ticket declara duas formas legítimas de citação (nome completo com prefixo; forma-código). Existe
uma terceira que nunca classificou: nome completo **sem** prefixo.

**Remediação:** caixa vazia, estado `parcial`. O defeito vai a ticket (§5).

### ADV-02-03 · KAM-129 CA4: população estreitada em silêncio

**Caixa:** «**Toda a referência de classe A resolve em disco** … 25 de 25.» Estava `[x]`.

**O que a revisão mediu.** As 25 com prefixo resolvem todas — confirmado. Mas «classe A» está
definida na tabela do Contexto como «anexo existente, `E1`–`E5`», e as três referências de
ADV-02-02 são referências a anexos existentes que **não** resolvem. O critério é verdadeiro para a
população que o ticket corrigiu e falso para a que o seu texto nomeia.

Acresce um erro de facto na linha de evidência: afirmava «os cinco nomes completos distintos, um
por anexo `E1`–`E5`». Dentro das 25 há **quatro**: `E1_Meta_WhatsApp.md` (11),
`E3_Regulatorio_Dados.md` (6), `E2_Pagamentos_Angola.md` (4), `E4_Stack_Licencas.md` (4).
`E5_Modulos_Entrada.md` tem **0** — as suas citações de nome completo em `specs/EPIC-11` já tinham
o prefixo certo e nunca entraram nas 59. É a confusão «E1–E4 contra E1–E5» que o KAM-130 C3 existe
para corrigir, reintroduzida dentro da evidência.

**Remediação:** caixa vazia, estado `parcial`, e a contagem de nomes distintos corrigida.

### ADV-02-04 · KAM-129 DoD «Referências»: alegação falsa como estava escrita

**Caixa:** «**Referências** — todo o caminho citado resolve ou consta da lista declarada de
artefactos futuros; nenhum `KAM-NNN`, `ADR-NNN`, `D#`, `H#` ou `E#` citado deixou de existir.»
Estava `[x]`, com a evidência «Todo o caminho citado em `specs/` resolve ou consta da lista
declarada de artefactos futuros».

**O que a revisão mediu.** Resolvedor sobre os 15 `specs/*.md` rastreados (excluído `EPIC-01`),
cada caminho `.md` em *code-span* resolvido relativo ao ficheiro **e** à raiz: **61 caminhos
distintos, 68 ocorrências, não resolvem**. Decompostos: **15** são a lista declarada de classe B
(os 13 alvos sob `validacao/` mais `Registo_Hipoteses.md` e `Carga_Dimensionamento.md`), **3** são
as de ADV-02-02, e os restantes **~43** são entregas futuras de outros tickets — `docs/gwy.md`,
`ops/runbooks/RB-K01..RB-K10.md`, `docs/seguranca/ameacas_stride.md`, `docs/evidencia/KAM-016.md`,
`Gate_Piloto_Decisao.md`, `Mapa_Tratamentos_v1.md` e outros.

Essa última categoria é legítima e pré-existente, mas **a redacção da caixa não a cobre**: a única
«lista declarada de artefactos futuros» do ticket é a de classe B, restrita a evidência. A segunda
metade da caixa (nenhum identificador deixou de existir) está satisfeita.

**A assimetria é o que torna isto P0:** a caixa gémea no bloco vizinho — KAM-128, DoD
«Referências» — foi deixada **por marcar** por um motivo mais fraco (três regras de `CODEOWNERS`).
A mesma linha de DoD, no mesmo ficheiro, lida à letra num bloco e por aproximação no outro.

**Remediação:** caixa vazia, com a leitura escrita e a decisão devolvida a quem redigiu o DoD.

---

## 3. Achados P1 — a evidência era insuficiente ou imprecisa

As caixas abaixo **sustentam-se**; as linhas de evidência foram corrigidas.

| # | Caixa | Defeito da evidência | Medição correcta |
|---|---|---|---|
| ADV-02-05 | KAM-001 DoD «Dependências» | Citava «`pnpm-lock.yaml` com `packageManager` fixado por `sha512`». O `packageManager` está no `package.json` e fixa **o pnpm**, não o fecho de dependências | `pnpm-lock.yaml`: **91** `resolution:` e **91** `integrity:`; locks Python: **14** e **138** `sha256:` |
| ADV-02-06 | KAM-001 CA2 | O ambiente de medição declarado (`node:24.21.0-trixie-slim`) não tem `make`, `python3` nem `git`: faltava declarar a instalação. E não citava os **52 s** que `../evidencia/KAM-001-node.md` §7.1 já regista para a mesma verificação | Os 575 s excluem a instalação e o clone (o cronómetro arranca depois); o anexo diz que os seus 52 s são «uma máquina com cache de rede quente» — são os dois extremos do mesmo intervalo, não uma contradição. O que **é** contradição: o §5 do anexo risca o critério como «Resolvido» |
| ADV-02-07 | KAM-001 CA6 | «sobe Postgres 18.6» apresentado como propriedade do compose | A *tag* `pgvector/pgvector:0.8.7-pg18` fixa o *major* 18 e o pgvector `0.8.7`; o `initdb` assere `18.x` e pgvector exactamente `0.8.7`. O `18.6` é observação datada, não garantia |
| ADV-02-08 | KAM-001 CA7 | Reportava as 3 regras de caminho morto e calava o essencial | **Nenhuma** das 15 regras atribui dono efectivo: todas apontam para `@kamba/*`, e o cabeçalho do próprio ficheiro declara que «o ficheiro nao tem efeito» enquanto a organização não existir. Explica o PR #1 ter sido fundido sem revisor |
| ADV-02-09 | KAM-128 DoD «sem segredos» | «`08426f3` toca apenas ficheiros `.md` e `docs/compilar-mestre.sh`» | `08426f3` toca **23** ficheiros, **todos `.md`**. O `docs/compilar-mestre.sh` foi criado por `53189a2` — e é o único dos três *commits* da cobertura retroactiva que acrescentou um *script* executável, precisamente o que não foi verificado |
| ADV-02-10 | KAM-128 CA6 | «`test-py` → 75 + 13 testes» omitia a suite do AGR e a dependência de `make bootstrap` | No contentor, `make check` correu as três suites verdes: **75 + 13 + 7**. No anfitrião só as duas primeiras são reproduzíveis, e `libs/py-core` só passa com `PYTHONPATH` explícito |
| ADV-02-11 | KAM-128 CA7 | O critério nomeia `docs/INDICE.md` **§2 e §6**; a evidência examinou o §2 e a linha de fecho, nunca o §6 | O §6 está conforme à árvore (a caixa sustenta-se), mas contém uma afirmação que este ticket falsificou — ver ADV-02-13 |
| ADV-02-12 | KAM-129 CA2 | «15 na forma-código (`E1`–`E5`)» | A forma-código ocorre em `E3`, `E4`, `E2` e `E1`; **nunca `E5`** |

---

## 4. Achados P2 — dívida e imprecisão menor

1. **Contagem errada na linha de versão 1.3 do epic.** Dizia «3 no KAM-001, 6 no KAM-128 e 2 no
   KAM-129»; eram 4, 5 e 2 à data em que foi escrita, e contradizia duas linhas inseridas pelo
   mesmo changeset. Nasceu de escrever a contagem em dois sítios e não os reconciliar. Corrigida.
2. **Grafia PT-BR: `regista` ×7**, introduzidas pelo changeset (0 antes). O conjunto tem 491
   `regista` contra 8 `regista`, 7 das quais nasciam aqui. Corrigido para `regista`.
3. **Base de contagem não declarada:** «`docs/tecnica/` (13)» conta 12 `.md` **mais** o
   subdirectório `evidencia/`, unidade que as outras cinco contagens do mesmo parêntesis não usam.
   Corrigido.
4. **Exclusão não declarada** na linha das referências nuas à biblioteca: a contagem «restam 7»
   aplica em silêncio a exclusão de `EPIC-01`, que hoje tem 2 ocorrências nuas introduzidas pelo
   texto do próprio critério. As linhas de G1/G2/G3 declaram a sua exclusão; esta não. Corrigido.
5. **A secção diz «acima» para caixas que estão abaixo**, e o título «Verificação dos Critérios de
   Aceitação» subdescreve uma tabela cujas linhas finais começam por `| DoD:`. Entre 6 e 7 linhas
   por bloco descrevem caixas 45 a 69 linhas **abaixo** da secção. **Não corrigido:** é herdado do
   formato que o KAM-002 estabeleceu e que foi mandado repetir; corrigir só aqui criava duas
   convenções. Decisão para quem redigiu o formato, e afecta os dois blocos.
6. **A escala de três estados não é aplicada** às afirmações sobre o mundo das tabelas novas
   (leituras de registo npm, versões lidas de contentores a correr, tempos). As tabelas usam
   `satisfeito / parcial / não satisfeito`, que mede satisfação de critério e não força de
   evidência. Os revisores não encontraram **nenhuma** afirmação promovida de estado. **Não
   corrigido:** também é do formato herdado.
7. **Redundância:** as três notas «O que isto custa, dito com clareza» reenunciam em prosa as
   linhas `parcial` e `não satisfeito` da tabela imediatamente acima, com os mesmos números. Não
   acrescentam medição; acrescentam uma segunda cópia a manter a par. Mantidas por fidelidade ao
   formato.
8. **Rastreabilidade ramo↔ticket 1:3.** O ramo é nomeado por um ticket e fecha três. Decisão
   declarada no relatório de execução.
9. **CA3 do KAM-001 mede `lint_arch deps`**, enquanto o critério diz «faz `make check` falhar». A
   inferência é sólida (`check` encadeia `lint-arch` primeiro, e `.SHELLFLAGS` aborta), mas é
   inferência; e `make lint-arch` invoca `lint_arch … all`, não `deps`.
10. **CA4 do KAM-001:** a excepção `main` de `tools/conventions.json` é exibida como conformidade.
    É deliberada e sensata, mas é uma excepção **ao critério**, que a régua à letra manda nomear.
11. **CA5 do KAM-001:** a presença do ficheiro em `REQUIRED_FILES` é um teste de **existência**
    citado para um requisito de **conteúdo**. O conteúdo foi verificado por leitura, não por
    máquina.
12. **CA2 do KAM-128:** os «Testes Requeridos» pedem um *script* que resolva as ligações markdown
    **e cada caminho `.md` em *code-span***. A segunda metade não passa (164 não resolvem no
    conjunto) e, como está redigida, nunca poderá passar. A caixa sobrevive porque o texto do CA é
    mais estreito («zero ligações markdown quebradas»). O defeito está nos Testes Requeridos e não
    tem ticket.

---

## 5. Defeitos revelados pela revisão e fora deste âmbito

Nenhum destes foi corrigido aqui. Pedem ticket `fix` próprio, como manda
`../../specs/01_Engineering_Standards_e_Handoff.md` §5.

| # | Defeito | Evidência |
|---|---|---|
| F1 | **Três referências a anexo de evidência citadas sem prefixo** em `specs/EPIC-10:11`. Pré-existentes, invisíveis às buscas G1 e G2 do KAM-129, e de uma terceira forma de citação que o ticket nunca classificou | `E2_Pagamentos_Angola.md`, `E3_Regulatorio_Dados.md`, `E4_Stack_Licencas.md`; 3 ocorrências em `6d30625` e 3 hoje |
| F2 | **`../INDICE.md` contradiz-se em três sítios sobre o documento mestre**: §2 (L52) «Compilação integral das partes 01–13» e «3.108» linhas, §4 (L160) «compilação 01–13», §6 (L193) «partes 01–13». O mestre tem **13 partes, 01–08 e 10–14, com a PARTE 14**, e **3360** linhas — que é o que o CA8 do KAM-128 afirma e a linha de versão 1.7 do mesmo ficheiro regista | Medido: 13 partes, 3360 linhas |
| F3 | **Intervalo da biblioteca desactualizado nos vizinhos.** `../tecnica/INDICE.md` §4 e §6 dizem `../exploracao/01`–`13`; a tabela de fontes de verdade de `.claude/skills/agentic-engineering/SKILL.md` §1 diz «Biblioteca exploratória `01`–`13`». A biblioteca é `01`–`14` | 14 ficheiros em `../exploracao/` |
| F4 | **`../evidencia/KAM-001-node.md` está atrasado face ao que mede:** §7.1 diz «67 em `lint_arch`» (medido: **75**; o total daria 108 e não 116) e o documento dá **três** contagens diferentes de pacotes npm (102, 91, 76; medido: 91 `resolution:`). E o §5 risca «`make bootstrap && make check` em ≤ 10 min» como «Resolvido», que é o critério que o encerramento declara não satisfeito | Medições do §3 e do §4 desta análise |
| F5 | **`CODEOWNERS` não atribui dono efectivo a nada.** As 15 regras apontam para equipas `@kamba/*` inexistentes, e as três de `/tecnica/` apontam ainda para um prefixo que a reorganização removeu. O mesmo vale para os `reviewers` do `renovate.json5` | Cabeçalho do próprio ficheiro; `gh pr view` dos PR #1–#3 com `reviews: []` |
| F6 | **Sete referências nuas à biblioteca** por converter em `specs/EPIC-10` e `specs/EPIC-11`, todas dentro de blocos de *handoff*; e a questão aberta da forma do caminho dentro desses blocos, que o KAM-129 declarou e ninguém decidiu | 17 em `df03076`, 10 corrigidas, 7 hoje |
| F7 | **Onze documentos formais** tocados pelo KAM-128 sem linha de «Controlo de versões», e `../evidencia/KAM-128.md` e `../evidencia/KAM-129.md` inexistentes apesar de os DoD os nomearem | 15 com tabela de versões, 4 com a emenda registada |
| F8 | **Colisão de numeração das análises:** este conjunto tem `ANALISE-01-validacao-adversarial-specs.md` em `main`, e o ramo `feature/KAM-002-pipeline-ci-gates` acrescenta um segundo `ANALISE-01`, ainda no caminho pré-KAM-128 (`analises/`, não `docs/analises/`). Tem de ser renumerado antes de fundir | `git ls-tree` dos dois ramos |

---

## 6. O que não foi revisto

A última secção é a que dá honestidade ao resto.

- **A adequação dos critérios, e não o seu cumprimento.** Nenhum revisor questionou se as caixas
  cobrem o objectivo dos tickets. Exemplo concreto do KAM-001: o utilizador não-root, o sistema de
  ficheiros só de leitura e a ausência de `.env` nas imagens estão verificados no anexo de
  evidência e **não têm critério nenhum** no bloco — nenhuma caixa os mede.
- **A régua a montante.** `../../specs/01_Engineering_Standards_e_Handoff.md` §3 e §5 e o §5 da
  *skill* foram tomados como válidos; não se procuraram defeitos neles.
- **A execução, de qualquer coisa que exija a pilha ou a *toolchain* Node.** Os três revisores
  foram proibidos de correr `make`, `docker compose up` e *builds*, para não colidirem entre si
  nem com outras sessões. Por isso **ninguém reproduziu de forma independente**: os tempos de
  `bootstrap` e `check`, a execução dos 116 testes (as **contagens** foram confirmadas), os 7
  contentores `healthy`, os cinco `/healthz` a 200, as versões lidas em execução, e a execução do
  `@commitlint/cli`. Os equivalentes estáticos foram todos verificados.
- **A idempotência do gerador do mestre** foi reproduzida por um revisor, mas numa cópia da árvore
  e não no *worktree*.
- **Os juízos de desenho** — por exemplo que carimbar isto no KAM-111 falsearia o critério do
  KAM-111, ou que as contagens herdadas pertencem ao KAM-130. São argumentos, não números, e não
  foram falsificados.
- **Nenhuma revisão humana.** Esta análise é produzida por agentes e **não conta como revisor**
  para efeitos do DoD, nos três tickets. Continua a faltar ≥ 1 revisor humano em cada.

---

## 7. Controlo de versões

| Versão | Data | Descrição | Autor |
|---|---|---|---|
| 1.0 | Outubro 2026 | Emissão inicial: revisão adversarial em três âmbitos disjuntos do encerramento dos KAM-001, KAM-128 e KAM-129. 4 achados P0 (quatro caixas desmarcadas), 8 P1 de evidência corrigidos no texto, 12 P2, e 8 defeitos inventariados para ticket próprio. | Equipa KAMBÁ |
