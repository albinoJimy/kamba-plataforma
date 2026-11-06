# ANÁLISE-52 — revisão adversarial do KAM-100 (spike H3: coexistência em +244)

| Campo | Valor |
|---|---|
| Produto | KAMBÁ (nome de trabalho) — plataforma WhatsApp-native de comércio conversacional para Angola |
| Documento | Análise — revisão adversarial do KAM-100, e o que ela mediu |
| Versão | 1.0 |
| Data | Novembro de 2026 |
| Classificação | Documento de Referência — Interno |
| Ticket | KAM-100 (EPIC-10) |
| Estado | CONFIRMADO — os dezesseis achados foram verificados contra a árvore, um a um |
| Fonte | Revisão adversarial sobre o ramo `feature/KAM-100-spike-h3-coexistencia`, no commit `bb85568` |
| Dono | Equipa KAMBÁ |
| Documento-fonte | `../../specs/EPIC-10_Spikes_Validacao_Gates.md`, bloco KAM-100 |

Uma passagem, *read-only*, sobre o ramo **depois de empurrado** e **sem ver o
raciocínio do autor**. Devolveu **16 achados**, e a verificação contra a árvore
confirmou **os 16** — nenhum morto, nenhum apenas plausível. Isso é, em si, um
resultado sobre o método: a revisão correu com os requisitos e o código, e não
com as justificações de quem o escreveu.

---

## 1. O que ela mediu, e que nenhuma outra coisa neste PR mediu

Dois achados valem mais do que os outros catorze, porque os dois atacam
**exactamente a garantia que o ticket diz entregar**.

### 1.1 A excepção à «regra do zero» era ela própria o defeito que a regra fecha

O ticket pede uma tabela que não confunda «zero eventos» com «não aconteceu». O
executor escreveu essa regra, e abriu-lhe **uma** excepção: a coluna «uma
mensagem enviada pela API gera *echo*», com o argumento de que «houve *echoes* e
nenhum é nosso» é prova de ausência.

Não é. Só o seria se tivéssemos enviado ≥ 1 mensagem pela API — e **nada nos
JSON-lines diz que enviámos**. Com o `nossos.txt` esquecido, ou acrescentado
depois de o receptor arrancar (o receptor lê-o uma vez, e a folha do operador
di-lo), todos os *echoes* saem marcados como não-nossos e a célula afirmava
`N (0 de 10)` — «uma mensagem da API **não** gera *echo*» — sobre zero envios.

Pior: o `direccao: "saida"` está na *allowlist* do registo e **nenhum caminho do
código o emite**, pelo que a tabela nunca podia distinguir os dois casos. E o
item é um dos dois NÃO VERIFICADOS de `../tecnica/evidencia/E1_Meta_WhatsApp.md`
§2 que a DoD 5 declara ter passado a ter instrumento.

**A regra do zero violada no único sítio onde se lhe abriu excepção.** A
correcção foi fechar a excepção: a coluna escreve `S` quando se viu e
`NÃO MEDIDO` no resto, e o `N` fecha-se cruzando com o passo 4.2 da folha do
operador — duas metades, e não uma.

### 1.2 A única chave do registo que admitia dígitos admitia um telefone

A *allowlist* de `spikes/h3/registo.py` é declarada, no próprio ficheiro, como «a
segunda metade, e a que importa»: cada chave diz a **forma exacta** do valor, e
«nenhuma admite um espaço, nenhuma admite 50 caracteres; um texto livre não casa
nenhuma».

Era falso para uma: `fase`, com a forma `[a-z][a-z0-9_]{0,31}`, aceita 31
caracteres de `[a-z0-9_]` — o que inclui um móvel angolano na forma local **e**
um E.164 sem `+`. E o `extrair._fase` **fabricava-o**: convertia qualquer inteiro
do `metadata.phase` em `fase_<numero>`. A revisão escreveu três casos no disco —
um `fase_` com um móvel na forma local, outro com um E.164 sem o `+`, e um com
texto livre.

> Os literais ficam **nos ensaios** e não nesta prosa. Um número de forma real
> num documento custa uma entrada no inventário do gate 7 e não testa nada — e
> foi um erro cometido duas vezes neste PR, uma no comentário do `inventario.ts`
> e outra aqui, as duas apanhadas ao re-medir a árvore.

O caminho é o `metadata.phase` do `history` e do `smb_app_state_sync`, cuja forma
interna o próprio extractor declara **INDÍCIO** — ou seja, o sítio onde vir outra
coisa é um resultado esperado do spike. E a caixa de DoD 4 estava marcada sobre
esta garantia.

**O detector do ensaio de privacidade teria apanhado o valor**; o defeito era de
cobertura, não do detector. A correcção limita a fase a `fase_<0-99>` ou a um
nome em letras **sem dígitos**, e os ensaios passam a exercitar o caminho.

---

## 2. Os dezesseis achados, e o que se fez a cada um

| # | O que | Gravidade | Resolução |
|---|---|---|---|
| 1 | `_eco_da_api` dá `N` medido sobre zero envios pela API | bloqueia a fusão | **Corrigido.** A excepção à regra do zero foi fechada; o `N` passa a exigir o cruzamento com a folha |
| 2 | `verificar_registo` nunca compara o nº de células com as doze colunas: uma linha truncada passa o `--completo` | bloqueia a fusão | **Corrigido.** O denominador passa a ser o esquema; a mensagem distingue «em falta» de «vazia» |
| 3 | `NÃO MEDIDO` conta como preenchido: 108 células assim passavam o `--completo` | corrige antes de fundir | **Corrigido.** No `--completo`, `estado` tem de ser um dos três estados de hipótese. O `resultado` continua a aceitar `NÃO MEDIDO`, pela regra do §2 do registo |
| 4 | A forma de `fase` admite um telefone, e o `_fase` fabrica-o | corrige antes de fundir | **Corrigido** (ver §1.2) |
| 5 | O `do_POST` só apanha `AssinaturaInvalida`: um cabeçalho não-ASCII e um `ConteudoRecusado` derrubam a ligação sem resposta, com escrita parcial e duplicação a cada reentrega | corrige antes de fundir | **Corrigido.** O cabeçalho não-ASCII passa a ser `AssinaturaInvalida`; a escrita é tudo-ou-nada; e o `handle_one_request` responde **sempre**, com 500 em último recurso |
| 6 | O laço sobre `errors[]` sobrescreve, e só o **último** código sobrevive: o 2593109 desaparece se não for o último | corrige antes de fundir | **Corrigido.** O 2593109 ganha precedência; sem ele fica o primeiro |
| 7 | `declaracoes` aceita qualquer linha de duas células de qualquer tabela: um glossário dá falso positivo | corrige antes de fundir | **Corrigido.** A forma de tabela lê-se só na tabela de cabeçalho, achada pelo marcador `\| Campo \| Valor \|` e não pela posição |
| 8 | O `Estado` é verificado por subcadeia: `NÃO CONFIRMADO` passa | corrige antes de fundir | **Corrigido.** Igualdade, tolerando ênfase e a cauda depois de um separador |
| 9 | A tabela do §2 do ficheiro de resultado e o gerador divergem: a linha da **entrega do SMS** só existe no documento, e o operador perdia-a ao regenerar | corrige antes de fundir | **Corrigido.** A coluna entra no gerador, as duas listas são presas por ensaio, e a prosa passa a «oito das catorze… seis à mão» |
| 10 | Um zero vindo de uma forma de corpo não reconhecida apresenta-se como valor medido, nas duas colunas onde a forma é INDÍCIO | corrige antes de fundir | **Corrigido.** As contagens só entram se a chave estiver presente; uma lista **vazia** continua a ser um zero medido |
| 11 | Uma sincronização entregue antes do `FINISH` dá segundos negativos e marca o prazo da Meta como cumprido | corrige antes de fundir | **Corrigido.** Guarda de sinal, e a célula diz que a ordem veio invertida |
| 12 | A *allowlist* tem 18 chaves e quatro sítios dizem 17 | nota | **Corrigido** nos quatro, e a contagem passa a ser presa por ensaio |
| 13 | O `smoke.py` corre sete verificações e imprime «6 de 6», com o número à mão | nota | **Corrigido.** Conta-se; e passou a dez casos com os dois novos do achado 5 |
| 14 | `verificar` aceita uma chave explicitamente vazia | nota | **Corrigido.** Levanta `SegredoEmFalta` |
| 15 | A guarda do `opaco` só retira espaços: um telefone com hífenes é **resumido** em vez de descartado | nota | **Corrigido.** Retiram-se todos os separadores |
| 16 | O validador é entregue sem um único ensaio, e o item devolvido mede só `spikes/` | corrige antes de fundir | **Corrigido.** **27 ensaios**, quatro deles de regressão dos achados 2, 3, 7 e 8; e o item 7 passa a medir e devolver também o `scripts/` |

---

## 3. O que a revisão deu por limpo, e com que instrumento

Isto vale tanto como os achados, e é o que uma revisão que só procura defeitos
não produz.

| Área | Como foi verificada |
|---|---|
| A validação sobre o **corpo bruto** | Ataque ao cabeçalho com: ausente, vazio, sem prefixo, `sha1=`, `SHA256=`, hex em maiúsculas, com espaço, duplicado na forma que um *proxy* junta, e um bit trocado — **todos recusados**. Não há caminho que aceite uma árvore já descodificada: `verificar` e `calcular` exigem `bytes`, e o `json.loads` corre **depois** |
| O **desenho** do ensaio do corpo bruto | Os cinco pares são bytes diferentes com a mesma árvore, e as duas metades que raramente aparecem estão lá: o ensaio que prova que cada par **é** um par válido, e o que escreve a implementação errada ao lado e mostra que ela os aceita. Não foi encontrado caso trivialmente verdadeiro |
| O extractor **não lê** telefone, nome nem texto | Ramo a ramo: nenhum lê `display_phone_number`, `wa_id`, `from`, `to`, `recipient_id` nem `phone_number`. O único caminho de fuga encontrado foi o `fase` (achado 4) |
| Os detectores de privacidade | Sem falsos negativos nas três grafias de telefone e sem falsos positivos nos valores legítimos do registo. Os dois padrões canónicos são **importados** de `../../tools/contract_diff/pii.py` e não recopiados |
| O **escopo** | Nada fora de `spikes/`, `scripts/`, `specs/EPIC-10`, `validacao/` e `tools/meta-sim/`. Nada em `.github/`, `ci/` ou `Makefile`; nenhuma regra de bloqueio, nenhum critério de portão |
| Segredos e números reais | Nenhum segredo no diff; o receptor recusa arrancar sem os dois; a página do ES recebe os identificadores pela *query string* e verifica a `origin` do `postMessage` |
| A contagem do **gate 7** | Reimplementada independentemente — os dois padrões, a excepção do intervalo fictício, a lista de ignorados e o critério de binário — e varrida a árvore: **34 ficheiros, 120 ocorrências, 0 divergências**, e exactamente **5** no ficheiro declarado |
| Os **estados** herdados de E1 | As afirmações da fonte foram confrontadas uma a uma. Nenhuma está promovida acima do estado que E1 lhe dá; os dois NÃO VERIFICADOS e o INDÍCIO das fontes secundárias são herdados |
| As **duas divergências** devolvidas ao fundador | Confirmadas na fonte: o `../exploracao/14-tese-minima-e-plano-de-validacao.md` §2 tem **H1–H12**, e o §6 tem **seis** linhas, sem pivô para H7, H8 nem H9 |
| As **caixas** | Exactamente duas passam a marcadas, e as duas têm a evidência que dizem ter. Nenhuma caixa vazia tinha evidência. Todos os itens devolvidos têm credor que **sobrevive à fusão** |

---

## 4. O que ficou por verificar, e porquê

Fica escrito para não ser lido como verde.

1. **O gate 7 na forma em que corre.** Não há `node` nem `pnpm` nesta máquina. A
   medição é uma reimplementação a concordar com uma declaração, em três
   quantidades independentes — não é o portão a dar verde.
2. **Os gates 1, 2, 4, 6, 8 e 11.** Não correram: precisam de
   `node`/`pnpm`/Docker.
3. **O comportamento real da Meta.** Nada do que o spike mede foi medido — é o
   que o spike existe para fazer. Os achados 4, 10 e 11 são defeitos de código
   independentemente da resposta, porque o código apresentava como medido o que
   não podia distinguir.
4. **A página de ES v4 contra o SDK real.** Lida por inteiro; não aberta num
   navegador. Se o `sessionInfoVersion` duplicado — dentro e fora do `extras` — é
   aceito pelo SDK é leitura de documentação e não medição.

---

## 5. A lição, e o que dela pode virar portão

Três, e as duas primeiras são da mesma família.

**Uma excepção a uma regra que se acabou de escrever merece a mesma prova que a
regra.** Os achados 1 e 12 nascem no mesmo sítio: o executor escreveu a regra do
zero, abriu-lhe uma excepção, e a excepção não tinha a prova que a regra exigia.
Não há portão mecânico para isto; há a pergunta, que fica escrita: *o que é que
esta excepção afirma, e onde está o dado que a sustenta?*

**Um instrumento de verificação sem ensaio é uma afirmação, não um
instrumento.** O achado 16 é o que mais custa a longo prazo: o
`validar_evidencia.py` ia ser citado como prova por quatro tickets, e tinha
quatro modos de dar verde sobre um ficheiro que não cumpre. Os quatro achados
estavam **todos** nele, e nenhum dos outros doze teria aparecido se o ficheiro
tivesse ensaios.

**Candidato a portão, e por isso fica nomeado em vez de implementado:** um
`scripts/` e um `spikes/` que não entram em portão nenhum são uma classe
inteira de código sem medição — e a decisão de os ligar é regra de bloqueio, logo
do fundador. Está devolvida no §6, item 7, do
`../tecnica/evidencia/validacao/H3_Coexistencia_244.md`, com a diferença entre os
dois escrita: um é descartável, o outro é permanente.

---

## Controlo de versões

| Versão | Data | Descrição | Autor |
|---|---|---|---|
| 1.0 | Novembro de 2026 | Emissão inicial, KAM-100. A revisão adversarial correu numa passagem, *read-only*, sobre o ramo **depois de empurrado** e sem ver o raciocínio do autor, e devolveu **16 achados** — **todos os 16 confirmados** contra a árvore, nenhum morto. Dois atacam a garantia que o ticket diz entregar: a **excepção à regra do zero** afirmava `N` medido sobre zero envios pela API, e a chave `fase` — a única da *allowlist* que admitia dígitos — **admitia um telefone**, que o extractor fabricava a partir de qualquer inteiro do `metadata.phase`. Os dezesseis estão corrigidos, com ensaio de regressão em cada um; o *harness* passa de 83 para **106** ensaios, o `smoke` de 6 para **10** casos, e o validador ganha os **27** que não tinha. O §3 registra o que a revisão deu por limpo e com que instrumento, e o §4 o que ficou por verificar — entre isso, o gate 7 na forma em que corre, porque não há `node` nesta máquina. | Equipa KAMBÁ |
