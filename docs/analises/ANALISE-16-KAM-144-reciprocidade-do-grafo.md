# ANÁLISE-16 — Revisão adversarial do KAM-144 (reciprocidade `Dependências`↔`Bloqueia`)

| Campo | Valor |
|---|---|
| Ticket | KAM-144 — Reciprocidade `Dependências`↔`Bloqueia`: os oito tickets que o KAM-002 não declara bloquear |
| Ramo | `fix/KAM-144-reciprocidade-bloqueia` (PR `albinoJimy/kamba#44`) |
| *Baseline* revista | `355b887`, sobre `main` em `f4c7e3d` |
| Data | Outubro 2026 |
| Método | Revisão independente por agente que recebeu os requisitos e o diff e **não** as justificações do executor; *parser* próprio do grafo, escrito de zero, sem reutilizar o *script* do executor; medição em `main` e no ramo, e em duas árvores com mutações hipotéticas |
| Veredicto da revisão | **Aprovado com reservas** — 2 maiores (bloqueadores de *merge*), 9 menores, 3 suspeitas |
| Estado | Os 2 maiores e os 9 menores **corrigidos**; das 3 suspeitas, **uma foi acolhida e mudou o ticket** (a dependência saiu do grafo), as outras duas ficam declaradas aqui sem alteração |

A revisão recebeu os requisitos, as restrições de âmbito e o diff — nunca o
raciocínio de quem o escreveu. Quando começou, a correcção de dados estava
feita, o PR #44 estava aberto, e as oito falhas de reciprocidade estavam a zero.

> **O que esta revisão ensina, em uma frase:** **o ticket cometeu o seu próprio
> defeito.** A sua tese é «exige-se o número, não a leitura» — e publicou um
> número (`10 580` referências) que não reproduz em *commit* nenhum, por ter
> sido colhido a meio do trabalho e nunca remedido. A correcção de dados, que
> é o que o ticket entrega, reproduziu-se inteira e sem uma divergência.

---

## 1. O que reproduziu

A revisão escreveu um *parser* independente e mediu em `main` (`f4c7e3d`) e no
ramo (`355b887`). **Toda a medição do grafo bateu**, incluindo os números que
mais facilmente se escrevem de memória:

| | `main` | ramo | afirmado | |
|---|---|---|---|---|
| Blocos `## KAM-NNN — ` nos 11 epics, únicos | 143 | 144 | 143 / 144 | ✔ |
| Linhas do §4, únicas, nenhuma só num lado | 143 | 144 | 143 / 144 | ✔ |
| Arestas em `Dependências` | 379 | 379 | 379 / 379 | ✔ |
| Arestas em `Bloqueia` | 371 | 379 | 371 / 379 | ✔ |
| Total de arestas conferidas | 750 | 758 | 758 | ✔ |
| **G5 sentido 1** (A dep B, B não bloqueia A) | **8** | **0** | 8 → 0 | ✔ |
| **G5 sentido 2** (B bloqueia A, A não dep B) | 0 | 0 | 0 | ✔ |
| S1 sincronia mestre↔epics (cinco campos) | 0 | 0 | 0 | ✔ |
| S2 ciclos / S3 prioridade invertida / S4 fase invertida | 0 | 0 | 0 | ✔ |
| S6 `KAM-NNN` citado sem bloco | 0 | 0 | 0 | ✔ |
| S7 §3.1: onze linhas, soma = TOTAL = blocos | 143 | 144 | 144 | ✔ |

E as três verificações que o executor não podia fazer a si mesmo:

- **As oito falhas de `main` são exactamente as nomeadas.** Não há nona, nem em
  `main` nem no ramo. **Corrigir o KAM-002 não expôs aresta encoberta** —
  confirmado por medição independente, que é o requisito 3 do pedido.
- **`Bloqueia` do KAM-002, 7 → 15, em ordem crescente.** A diferença simétrica
  entre «os blocos que declaram `dep KAM-002`» e «o conteúdo do campo» é
  **vazia**; `lista == sorted(lista)` → `True`; as 15 linhas do §4 com
  `dep KAM-002` dão o mesmo conjunto. Nenhum ID estranho entrou e **nenhum
  campo `Dependências` foi tocado**.
- **Sem alteração acidental.** Diff inteiro lido (167 linhas, 2 ficheiros):
  nenhuma linha de evidência dos KAM-001, KAM-128 ou KAM-129 foi tocada — no
  bloco do KAM-129 mudou exactamente um campo. Os *blobs* commitados são LF
  puro (`git cat-file -p HEAD:… | grep -c $'\r'` → 0 nos dois).

---

## 2. Achados maiores

### M1 — um número publicado que não reproduz em *commit* nenhum

A linha de DoD «referências» afirmava `lint_refs` → «conforme — **10 580**
referências em 552 ficheiros», e o corpo do PR repetia-o. A revisão correu o
comando em clones limpos de dois estados:

```text
HEAD 355b887   conforme — 10895 referencias em 552 ficheiros (KAM 8128, ...); KAM: 144
origin/main    conforme — 10486 referencias em 552 ficheiros (KAM 7719, ...); KAM: 143
```

`10 580` não é nenhum dos dois — erro de **315**. O «552 ficheiros» e o
«KAM: 144 (KAM-001–KAM-144)» batiam, o que torna o número isolado mais
suspeito: foi colhido a meio do trabalho, antes de a própria secção de
verificação entrar no bloco, e nunca remedido. A citação omitia também que o
comando emite **30 avisos** de *tokens* `D#` fora do intervalo canónico,
pré-existentes em `main`.

**É o padrão «número proposto endurecido em requisito» num ticket cujo
critério 2 diz «exige-se o número, não a leitura».** Corrigido, com a nota do
erro escrita onde ele esteve.

**E tem uma lição de método que ficou no ticket:** o total do `lint_refs` conta
as referências `KAM-NNN` do próprio texto, pelo que **cada edição ao bloco move
o número que o bloco publica**. Ao corrigir, 10 895 passou a 10 914. A única
forma de o número ser verdadeiro é medi-lo **depois** de o texto estar fechado e
escrevê-lo como última alteração — que não acrescenta referência nenhuma e é,
por isso, um ponto fixo.

### M2 — uma afirmação falsa a servir de fundamento a uma decisão devolvida

A recomendação de subir o KAM-138 a P1/Fase 0 sustentava-se, em parte, nisto:
«É também o único dos oito tickets dependentes do KAM-002 cuja ausência
**esconde** defeitos em vez de os deixar à vista: os outros sete corrigem
coisas que já se vêem.» Os blocos vizinhos refutam-no pelas próprias palavras.
Contagem de linguagem de falha silenciosa por bloco:

```text
KAM-131  1    KAM-132  3    KAM-133  2    KAM-134  0
KAM-135  0    KAM-136  7    KAM-137  1    KAM-138  0  <- o proprio nao usa nenhuma
```

O KAM-136 intitula-se «Dois erros de leitura **silenciosos**»; o KAM-134 faz
recusar chave hoje aceite em silêncio; o KAM-133 põe no SBOM pacotes que não
apareciam. **Pelo menos seis dos outros sete** escondem defeitos. E, agravante
que o executor não mediu, **três dos oito já estão fundidos** (KAM-131,
KAM-132, KAM-136 — `vagas.py` → «144 tickets, 19 fechados»), pelo que falar da
sua «ausência» já não se aplica.

Isto é grave por onde ia: era fundamento de uma decisão a entregar ao
Arquitecto de Plataforma. Reformulado para o que se defende — «o único cuja
ausência esconde defeitos **no próprio backlog**, a fonte que decide ordem e
paralelismo» — com o erro da primeira versão escrito.

**A outra metade do fundamento confirmou-se:** com o KAM-138 a P1/Fase 0 nos
dois lados (*patch* hipotético numa cópia), S3 e S4 continuam a **0**. A subida
não cria inversão.

---

## 3. Achados menores, e o que se fez

| # | Achado | Disposição |
|---|---|---|
| m1 | O *placeholder* `albinoJimy/kamba#PR` ficou no *commit* `355b887`; nenhum *gate* o apanha | Corrigido para `#44`; o *commit* foi emendado antes do *merge* |
| m2 | «a igualdade dos dois totais é ela própria a simetria do grafo» é inferência falsa. Contra-exemplo construído: trocar um ID dentro do `Bloqueia` mantém os dois totais iguais e dá **2** falhas | Reformulado: a igualdade é **necessária e não suficiente**; a prova é a contagem nos dois sentidos. A conclusão do ticket não muda — os dois sentidos *foram* contados |
| m3 | A caixa «defeitos fora do âmbito» estava marcada por uma posse que o teste citado nega: o alvo da busca H4 do KAM-130 diz «0 **fora de** `specs/INDICE.md` **e `README.md`**», isto é **isenta** o `README.md`; e o inventário C1–C5 nomeia só `ADR-L001` e `PR-KAM-001.md`. `grep -n README docs/dividas-documentais.md` → vazio | Corrigido pela via que o DoD permite: **linha 19** de `docs/dividas-documentais.md`. A dívida não tinha dono, ao contrário do que o bloco dizia |
| m4 | Convenção de separador quebrada duas vezes: sem `---` antes do cabeçalho do KAM-144 (os KAM-139 a KAM-143 têm), e um `---` duplicado no fim (linhas 3562 e 3564) | Corrigidos os dois |
| m5 | A bala «Fora de âmbito» saiu de `### Detalhes Técnicos`: o `#### A causa não é corrigida aqui` entrou entre as balas, pelo que ela passava a ler-se como parte da recomendação | Bala reposta antes do `####`, com remissão explícita para a secção seguinte |
| m6 | Grafia PT-BR: «**registra**» duas vezes no bloco novo (170 ocorrências de «regista» no conjunto) | Corrigido |
| m7 | «regrediu **uma vez** de 0 para 8» são dois eventos (1.5: 0 → 7; 1.6: 7 → 8), e «o custo já se pagou mais do que uma vez» não se sustenta: o §4 tem **um** ticket de reciprocidade | Reescrito com os dois eventos, que são **melhor** argumento (não foi lapso, é o comportamento por omissão), e o custo contado à letra |
| m8 | «segunda passagem a 0 alterações» é vácuo para um verificador *read-only*: a regra do SKILL §7 existe para *scripts* que corrigem e verificam na mesma passagem | Aceite sem alteração ao texto. Fica aqui: é honesto apresentá-la como estabilidade, não como evidência de correcção |
| m9 | P1 não estava justificado face ao KAM-130 (`fix` documental do mesmo epic, mesmo responsável, **P2**) | Justificação escrita: o grafo é lido por `vagas.py` para decidir paralelismo; uma contagem errada engana um leitor, um `Bloqueia` incompleto faz decidir execução com o grafo errado |

---

## 4. Suspeitas — e a que mudou o ticket

### S-A (acolhida) — `Dependências | KAM-129` era proveniência, não ordem técnica

A revisão não a classificou como achado («é juízo editorial, e a convenção do
repositório não o escreve em sítio nenhum»), mas mediu o precedente e ele **não
sustentava** o que o ticket dizia que sustentava: KAM-130 `dep` KAM-128 porque
os caminhos tinham de aterrar; KAM-139 a KAM-141 `dep` KAM-111 porque precisam
da saída do gate 3b; KAM-143 `dep` KAM-142 porque precisa do `--fatia`. Todas
são ordem técnica. **Nada da entrega do KAM-129 é necessário para acrescentar
oito IDs a um campo `Bloqueia`** — e o DoR de `specs/01` §2 só a salvava pela
cláusula «ou são paralelizáveis», que é dizer que não é dependência.

**Foi acolhida e o ticket mudou:** `Dependências` passou a `—`, o `Bloqueia` do
KAM-129 voltou a `—`, e a proveniência ficou em prosa. A razão é a própria tese
do ticket: uma aresta falsa no grafo que ele existe para tornar verdadeiro é
uma contradição interna, e fazia o KAM-129 «bloquear» algo que não bloqueia.
Efeito colateral útil: o diff deixa de tocar o bloco do KAM-129 além do campo
que a primeira versão lá pôs, reduzindo a superfície de conflito com o PR #43.

### S-B (sem alteração) — o PR cumpre o §7

`gh pr list` devolveu o **#44, OPEN**, com todas as secções do modelo de
`specs/01` §7. Requisito 5 cumprido. A revisão não pôde verificar o estado do CI.

### S-C (sem alteração) — nenhuma lacuna nova em `docs/ci.md` §7

Os KAM-131, KAM-132 e KAM-136 registaram lacunas novas ao fechar; o KAM-144
descobriu um facto do mesmo tipo («o CI de `main` está verde com as oito
falhas») e não registou nada. **Decisão: não se registou, e fica dito aqui
porquê** — o KAM-138 já é o dono declarado dessa lacuna, e inscrevê-la outra
vez em `docs/ci.md` §7 duplicaria um dono em vez de acrescentar informação.

---

## 5. O que a revisão não reviu

Estado do CI no PR #44; a prosa dos 11 epics linha a linha (reviu estrutura,
grafo, unicidade, sincronia e contagens); se os 30 avisos de `D#` do `lint_refs`
escondem algo, sendo pré-existentes em `main`; `docs/tecnica/`,
`docs/exploracao/` e os ADRs.

---

## Controlo de versões

| Versão | Data | Descrição | Autor |
|---|---|---|---|
| 1.1 | Outubro 2026 | Contagens de arestas corrigidas de 380/380 (760) para **379/379 (758)**: a tabela do §1 e o contra-exemplo do m2 traziam a medição feita antes de a suspeita S-A retirar a aresta `KAM-144`→`KAM-129`. Corrigido depois do *merge* do PR #44, no `main` em `148567c`. | Equipa KAMBÁ |
| 1.0 | Outubro 2026 | Emissão: revisão adversarial do KAM-144, 2 maiores, 9 menores e 3 suspeitas, com a disposição de cada um. A suspeita S-A foi acolhida e retirou a dependência do grafo. | Equipa KAMBÁ |
