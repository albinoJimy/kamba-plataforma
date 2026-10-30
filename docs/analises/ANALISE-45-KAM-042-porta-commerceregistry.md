# ANÁLISE 45 — KAM-042: porta `CommerceRegistry`, repo-base e adaptador da opção B

| Campo | Valor |
|---|---|
| Ticket | KAM-042 — Porta `CommerceRegistry` e adaptador |
| Diff revisto | `030058f` contra `fd0a32d` (nove ficheiros em `services/com/`) |
| Árvore que fundiu | `5cb6b54` e seguintes — **mudou desde o lançamento**, ver §1 |
| Revisor | subagente `general-purpose`, read-only, sem acesso ao raciocínio de quem escreveu |
| Instrumentos | leitura contra o canon, os 41 testes em contentor, **e uma sonda própria que atacou a barreira por execução** |
| Saldo | **17 `CONFIRMADO`** (5 bloqueantes, 12 relevantes), 4 cosméticos, **12 `MORTO`** com evidência |

---

## 1. O que esta revisão fez de diferente, e porque isso importa

A revisão lançou-se **assim que o diff existiu**, não no fim: o commit `030058f`
foi empurrado e o subagente arrancou enquanto a *self-validation* corria. Correu
20 minutos de relógio sobrepostos a trabalho em vez de somados a ele.

**E ela não leu: executou.** Para atacar a barreira do repo-base escreveu uma
sonda própria que importa o `repoBase` real e lhe passa SQL construído, e
imprimiu `EXECUTOU` ou `RECUSOU` por caso. É a diferença entre «esta regex
parece frágil» e isto:

```text
EXECUTOU | noMerchant | UPDATE product SET merchant_id = $1 WHERE sku = $2
EXECUTOU | noMerchant | UPDATE product SET merchant_id = $1
RECUSOU  | noTenant   | INSERT INTO platform.offer_terms (tenant_id, sku) VALUES ($1, $2)
EXECUTOU | noTenant   | INSERT INTO platform.offer_terms (tenant_id, sku) VALUES ($1, $2) -- tenant_id = $1
EXECUTOU | noMerchant | SELECT * FROM product WHERE merchant_id = $1 UNION ALL SELECT * FROM product
EXECUTOU | noMerchant | SELECT * FROM product WHERE nome = 'merchant_id = $1'
```

**A árvore mudou entre o lançamento e a resposta**, e por isso cada achado foi
reverificado contra a árvore que funde. **Dois dos cinco bloqueantes estavam
mortos quando ela respondeu:** o B-4 («`docs/com/port-coverage.md` não existe,
e três sítios afirmam que existe») e o B-5 («`lint_arch medusa` não existe; a
afirmação "é verificado por máquina" é falsa») — os dois nasceram no `cc0f16b` e
no commit da documentação, depois do `030058f` que ela viu. **Mas nenhum morreu
inteiro**, e é essa a parte que vale: o B-5 trazia uma segunda metade que
sobreviveu e virou correcção, abaixo (achado 6).

---

## 2. Os achados `CONFIRMADO`, e o que cada um custava

### Os dois que eram escrita cruzada, não leitura

**B-1 — o predicado no `SET` dava a consulta por filtrada.**
`UPDATE product SET merchant_id = $1 WHERE sku = $2` executou: a regex encontrou
`merchant_id = $1` na cláusula `SET` e deu-a por satisfeita. O efeito é que
**todas as linhas com aquele SKU, de qualquer merchant, passavam a ser do tenant
que chamou** — e `UPDATE product SET merchant_id = $1`, sem `WHERE` nenhum,
também executou. No Registo da opção B não há RLS atrás desta barreira, pelo que
não há segunda rede. Era o defeito mais grave do diff, e nenhum teste da primeira
versão o apanhava, porque todos exercitavam `SELECT`.

**B-2 — o `INSERT` legítimo era recusado, e o contorno passava.**
`INSERT INTO platform.offer_terms (tenant_id, sku) VALUES ($1, $2)` foi recusado
— e a interface prometia, por escrito, «`SELECT`/`INSERT`/`UPDATE` no
`platform`». A saída de menor resistência para quem batesse nisto no primeiro
`INSERT` do KAM-043 era acrescentar `-- tenant_id = $1` ao fim, o que **esvaziava
a barreira**. Uma barreira que recusa o uso correcto e aceita o contorno é pior
do que nenhuma: ensina o contorno, e quem o aprende leva-o para o ficheiro
seguinte.

**A correcção dos dois é a mesma mudança de desenho**, e mudou o que a barreira
*afirma*. Cinco regras em vez de uma: literais e comentários apagam-se antes de
procurar o predicado; o predicado tem de estar **depois** do primeiro `WHERE`; a
coluna do filtro nunca aparece num `SET`; `UNION`, `INTERSECT` e `EXCEPT` são
recusados; e **um `INSERT` não se verifica, constrói-se** — o
`inserirNoTenant`/`inserirNoMerchant` escreve a coluna do filtro ele mesmo e
**recusa** recebê-la nos valores.

> **E a regra do `SET` nasceu com defeito próprio.** A primeira versão dela era
> um `set` seguido de um `[\s\S]*?` não-guloso até à coluna, que atravessava o
> `WHERE` e casava com o predicado legítimo que está lá: o
> `UPDATE product SET nome = $2 WHERE merchant_id = $1` passou a ser recusado.
> Quem o apanhou, no primeiro minuto, foi **o teste do caminho legítimo** — os
> canários da recusa passavam todos. É a segunda vez neste ticket que um caso
> que afirma o uso correcto encontra o defeito, e a lição está no ficheiro:
> **uma barreira precisa de canários nos dois sentidos**, e os do «não morde
> onde não deve» são os que custam mais a escrever e os que a salvam de ser
> apagada por quem ela irrita.

### Os outros três que a sonda e a leitura trouxeram

**R-10 — a perna de fora de um `UNION`.**
`SELECT * FROM product WHERE merchant_id = $1 UNION ALL SELECT * FROM product`
executou. É o pior caso de todos, porque a primeira perna está certa e o
resultado parece plausível. Recusam-se as três operações de conjunto: o filtro
tem de estar em **cada** perna e nenhuma verificação por texto o consegue
afirmar. Quem precisar de uma faz duas chamadas e junta em JavaScript — custa
uma consulta e compra a propriedade.

**C-4 — o predicado dentro de um literal.**
`WHERE nome = 'merchant_id = $1'` passava. Caso construído e não de
esquecimento, mas uma barreira que conta texto dentro de literais conta a coisa
errada; a limpeza de literais e comentários resolve-o e resolve o B-2 ao mesmo
tempo.

**B-3 — o `ClienteSql` cru no `Registo`.**
O `comRegisto` entregava, ao lado do `repo` que filtra, o cliente SQL em bruto.
O KAM-043 escreveria `r.cliente.query("SELECT * FROM product")` — sem filtro, sem
recusa, sem contador —, e a frase do ficheiro, «não há caminho por onde uma
implementação futura chegue à base sem passar por aqui», passava a ser a única
barreira. **Uma barreira que é uma frase não é uma barreira.** O campo saiu, e há
um teste que afirma que saiu (`"cliente" in r` → `false`).

### Os seis nomes e domínios

**R-1 — o `ORDER_STATES` tinha nove estados e o canon fixa doze.**
O comentário citava o `../docs/tecnica/03` §6.1, que diz de si mesmo «canónica:
documento 00 §6.1» — e o `docs/tecnica/00` §6.1 tem doze, com
`entrega_falhada`, `em_disputa` e `reembolsada`. O dicionário §3.3 escreve a
lista canónica com os doze e marca aquela máquina como **«Máquina incompleta»**.
A consequência não é cosmética: com nove, o **KAM-050** («pagamento tardio,
disputa, entrega falhada, reembolso») não conseguia chamar
`transition(ctx, id, "em_disputa", …)` sem alterar o tipo da porta — isto é, **a
costura do PA-03-1 partia-se num ticket que depende do KAM-044 e não numa troca
de Registo**, que é exactamente o contrário do que ela existe para garantir.

**R-7 — `PRECO_MODOS`/`precoModo` reintroduzia um nome substituído.**
O `../docs/tecnica/03` §3.2 escreve `precoModo` no retorno do `getOfferView` e o
critério 2 do KAM-043 repete-o; o dicionário §3.3 fixa `preco_tipo` e põe
`preco_modo` na coluna «Substitui» desde a emenda 1.12. É divergência
spec↔dicionário e **resolve-se a favor do dicionário** (fonte 4 contra fonte 9),
como a emenda 1.45 já decidiu para o bloco KAM-047, que escrevia o mesmo erro. O
`servicos/contrato.ts` ao lado já usava `precoTipo`. **O gate 3b não apanha
isto**: as superfícies do `canon_lint` são `migracoes`, `eventos`, `registo` e
`documentos`, e TypeScript não é nenhuma delas — o defeito era real e nenhuma
máquina o via.

**R-8 — dinheiro em `number`.**
`OrderView.totalMinor: number` contra o `type Minor = bigint` de
`packages/core-ts/src/pagamentos/tipos.ts`. O `money_lint` que o KAM-052 escreveu
para isto **não morde aqui**, porque as `RAIZES` dele são
`packages/core-ts/src/pagamentos` e o `services/com` está fora. Passou a
`bigint`.

**R-3 — o `NOT_IMPLEMENTED` fora do dicionário.** O comentário dizia «entra no
dicionário §3.39», em presente, e o §3.39 não existia. Entrou, como *proposta*.

**R-4 — a correcção da contagem anunciada e não feita.** O comentário dizia «a
contagem errada corrige-se nos dois sítios no PR deste ticket» e o diff não
tocava em `specs/`. Está feita: no objectivo do bloco e na linha da
`PortaDeCatalogo` do §3.38.

**C-2 — tenant inexistente e tenant não provisionado saíam com o mesmo erro**,
embora o critério 1 os nomeie à parte. `TenantDesconhecidoError` novo.

### Os dois do provisionamento

**R-11 — o erro da corrida perdida mentia.** O `RETURNING` vazio significa que
outra corrida já escreveu os ids, e o código lançava `MerchantEmFaltaError`, cuja
mensagem diz «o tenant X **não tem** `medusa_merchant_id`» — o oposto do que
acabara de acontecer. O comentário imediatamente acima dizia «não é erro»; o
código devolvia erro, e o erro mentia a quem opera o *script* da Fase 0.
`CorridaPerdidaError` novo, com a mensagem a dizer o que é.

**R-12 — um estado que nunca se conseguia provisionar.** A guarda do `UPDATE`
exigia `medusa_merchant_id IS NULL AND medusa_sales_channel_id IS NULL`. Com o
canal escrito e o `merchant_id` a `NULL` — estado alcançável com um único
`UPDATE`, porque o `kamba_app` tem `GRANT UPDATE` nas duas colunas desde a
revisão `0001` —, o comando criava `merchant`, canal e localização no Registo,
não casava linha nenhuma, e falhava. **Para sempre, a cada repetição.** A guarda
passou a ser só sobre o `merchant_id`: é ele que o repo-base usa para filtrar, e
um tenant sem ele não está a operar.

### As três afirmações falsas em comentário

Estas são a classe que esta *skill* existe para fechar, e valem por si:

**R-6 — o ADR-003 nomeia a opção B como *fallback*, não a C.** O cabeçalho do
adaptador dizia «o ADR-003 continua a nomear a opção C como fallback», e o texto
do ADR é «Medusa v2 como registo de comércio, condicionado a spike (...);
**fallback Medusa puro + `merchant_id`**». O *fallback* do ADR **é** a opção B, a
que este adaptador implementa; a opção C é o «Fallback 2» do §4.5 e não aparece
no ADR. **A conclusão não mudou** — o ficheiro não contradiz nem substitui o
ADR-003 —, mas a razão era falsa, e uma razão falsa a sustentar uma conclusão
certa é um defeito, porque o próximo leitor confia nela.

**R-5 — o ISO-58 citado para o que ele não mediu.** O comentário atribuía-lhe
«com o `merchant_id` a vir do chamador, a porta aceitava o do tenant B com o
`ctx` de A». O que o ISO-58 mediu é a **FK do `contact_id`**, que a chave
primária de `contacts` satisfaz sem o tenant. É a mesma *classe* de defeito
noutra coluna, e é de lá que vem a lição — mas não é a medição desta. Reescrito
para dizer isso.

**R-2 — o teste que não afirmava o que o nome promete.** O caso «os dominios
fechados sao os do dicionario» comparava `ORDER_STATES` por `length === 9` e
`includes("reembolso_pendente")`, sem comparar nome nenhum — ao contrário do que
fazia para os outros três domínios — e **por isso não podia dar pelo R-1**. O
comentário citava ainda «a lista é a mesma do `CHECK` de `orders_mirror`», tabela
que **não existe** (é do KAM-044). Passou a `deepEqual` contra os doze nomes.

**Achado 6 (a metade viva do B-5) — o *lint* não impõe o que a frase dizia.** A
frase era «**Não importa o SDK do Medusa**, e é verificado por máquina». O
`lint_arch medusa` recusa `@medusajs/*` **fora** de `services/com/` — logo o dia
em que o adaptador importe o SDK, nenhum *gate* o impede, porque é ele o dono.
A ausência de hoje é uma **escolha**, não uma propriedade imposta, e passou a
dizê-lo.

**R-9 — métricas que ninguém pode ver.** O comentário era «uma barreira que
ninguém vê disparar não se opera», e os dois contadores vivem num `Map` em
memória que nenhum *endpoint* lê: o COM não serve métricas. Não se resolveu
inventando uma superfície de métricas — isso é outro ticket —, resolveu-se
**dizendo o que são**: os nomes entram no dicionário §3.39 para que nasçam certos
no dia em que o COM as servir, quem os lê hoje são os testes, e a lacuna leva
comentário `shortcut:` com o gatilho de revisão.

---

## 3. Os `MORTO`, e porque se registam

Doze, e registam-se com a evidência que os matou — senão voltam na próxima
auditoria e pagam-se outra vez.

| # | Suspeita | Evidência que a matou |
|---|---|---|
| M-1 | O `UPDATE` do provisionamento sobrescreve o `merchant_id` de um tenant a operar | Não: `medusa_merchant_id IS NULL` e `deleted_at IS NULL` no `WHERE`, presos por asserção, e o caminho «já provisionado» sai antes de tocar no Registo |
| M-2 | O `kamba_app` não pode escrever as colunas `medusa_*` | Pode, desde a `0001`: o `GRANT UPDATE` nomeia-as. A afirmação do ficheiro é exacta |
| M-3 | As colunas e a tabela que o SQL nomeia não existem | Existem todas em `0001_schema_platform.py`. Nenhum outro objecto de base é nomeado pelo `src/` |
| M-4 | A citação da D3 está adornada | Verbatim, `docs/tecnica/00` §13.3 linha 476. O bloco HIPÓTESE está certo no estado e nos números do harness |
| M-5 | A citação do RR-01 é invenção | Verbatim em `../tecnica/03` §5.4 e no relatório do KAM-041 |
| M-6 | «doze métodos no §3.2» é a contagem errada | Doze é certo; o «onze» está no objectivo do bloco e no §3.38, tal como o comentário dizia |
| M-7 | A citação dos *links* do Medusa e do canal como «segunda barreira» | CONFIRMADO na fonte (§3.3), com ISO-11..18 e ISO-27..32 |
| M-8 | «não há Medusa em `infra/compose/`» | Verdade: o único artefacto é o `CREATE DATABASE kamba_medusa` do `initdb` |
| M-9 | O `ComTenant` e o `comBatch` citados não existem com essa forma | Existem em `packages/core-ts/src/tenant_guard/index.ts` |
| M-10 | O teste do ISO-09 passa sem provar que não se toca na base | Prova: o `assert.rejects` discrimina a classe, e o cliente proibido lança `Error` simples, que falharia a asserção |
| M-11 | Há um caminho em que uma das doze chega à base sem `ctx` validado | Não encontrado. As doze chamam `exigirCtx` como primeira instrução; o `comRegisto` valida **fora** do `comTenant` |
| M-12 | A resolução do `merchant_id` aceita um valor do chamador | No caminho actual, não: lê-se de `platform.tenants`. O risco era o B-3, e fechou com ele |

---

## 4. Calibração, e o que ela diz desta revisão

| Indicador | Valor | Leitura |
|---|---|---|
| Achados levantados | 33 (5 bloqueantes, 12 relevantes, 4 cosméticos, 12 mortos) | — |
| `CONFIRMADO` | **17 de 21 não-mortos** | Taxa alta, e a razão é o instrumento: a sonda por execução não devolve opiniões |
| Mortos na resposta por a árvore ter mudado | 2 de 5 bloqueantes | **E nenhum morreu inteiro**: o B-5 trouxe uma correcção que sobreviveu |
| Achados que um *gate* devia ter apanhado | 2 (R-7 e R-8) | Ver §5 |
| Defeitos que só a execução apanhou | 4 (B-1, B-2, R-10, C-4) | Nenhum sairia de uma leitura do código |

**Estes números são `INDÍCIO` e não `CONFIRMADO`**, pela razão que o §3 da
*skill* escreve: a calibração não se lê de artefacto nenhum que este repositório
produza — lê-se desta análise contra o PR, à mão.

---

## 5. Três escapes, e o que fazer com eles

> **Um escape que um portão podia ter apanhado vira portão.** Não vira aviso e
> não vira nota de rodapé.

**Escape 1 — um nome substituído reentrou pelo TypeScript, e o gate 3b não o
vê.** As superfícies do `canon_lint` são `migracoes`, `eventos`, `registo` e
`documentos`; o código TypeScript não é nenhuma delas. O R-7 (`preco_modo`) é
exactamente o defeito que o gate 3b existe para apanhar, num sítio onde ele não
olha — e a emenda 1.45 já tinha pagado o mesmo nome noutro ticket. **Alargar uma
superfície do `canon_lint` é alterar o critério de um gate**, e isso é regra de
bloqueio: fica **devolvido ao fundador** com a medição, não implementado aqui.
O que este ticket entrega é o achado e o número: um nome do dicionário reentrou
em código sem nenhuma máquina o ver.

**Escape 2 — o `money_lint` não cobre `services/`.** O R-8 (`number` em vez de
`bigint`) estava dentro do que o KAM-052 escreveu um *lint* inteiro para impedir,
e escapou porque as `RAIZES` dele são `packages/core-ts/src/pagamentos`. Alargar
as raízes é a mesma classe de alteração, e vai pelo mesmo caminho: **medição
entregue, decisão devolvida**.

**Escape 3 — o número desta análise colidiu, e isso já tinha acontecido sem
ninguém dar por ele.** Esta análise nasceu `ANALISE-43` e é a **45**. O número
mediu-se contra `docs/analises/` do worktree, que estava na base `fd0a32d`; o
PR #93 fundiu depois e levou o 43 (`ANALISE-43-KAM-104-pacote-parecer-juridico`),
e o PR #94 reclama o 44 sem ter fundido. Os nomes diferem no *slug*, pelo que
**não há conflito de ficheiro e nenhum gate o apanha** — e a colisão sobrevive à
fusão. Foi um par a medi-la, não um portão.

É a mesma corrida que queimou quatro identificadores de ticket esta semana, com
uma diferença que a torna pior: **um ticket tem três instrumentos a apanhar a
colisão e uma análise não tem nenhum.** A numeração do §4 do backlog é contígua
e o `lint_backlog` e o `lint_refs` recusam o buraco; um número de análise
repetido passa por todos os portões.

**E não é hipotético — já escapou.** Medido no `publico/main` de hoje:

```bash
git ls-tree --name-only refs/remotes/publico/main docs/analises/ \
  | grep -oE 'ANALISE-[0-9]+' | sort -t- -k2 -n | uniq -c
#       2 ANALISE-39
docs/analises/ANALISE-39-KAM-047-servicos.md
docs/analises/ANALISE-39-kam-037-modo-deterministico.md
```

**Duas análises com o número 39 estão em `main` neste momento**, de dois tickets
diferentes, e nenhum gate as viu entrar. A memória das revisões deste conjunto
já tem um «39» ambíguo.

A medição vai entregue e a implementação **não**, pela mesma razão dos outros
dois: pôr a unicidade de `docs/analises/` num *lint* é acrescentar
verificação a um gate, e o critério de um gate é regra de bloqueio. A forma
barata existe e fica nomeada — o `lint_refs` já varre a árvore inteira à procura
de citações e já conta ficheiros, pelo que um passo que recuse dois ficheiros com
o mesmo `ANALISE-NN` entra num gate que já corre, sem *job* novo. **Decide o
fundador**, e a dívida do «39» duplicado tem de ser paga por quem o fizer, senão
o passo nasce vermelho.

---

## 6. A lição que este ticket deixa escrita

**Uma barreira construída sobre uma verificação de texto tem de ser atacada por
execução, e os canários do «não morde onde não deve» são metade do valor.**

A primeira versão da barreira tinha testes e todos passavam. O que faltava não
era rigor: eram **casos que ninguém pensa em escrever para o próprio código**,
porque quem o escreveu sabe o que ele quis dizer. Quatro dos cinco defeitos
graves deste diff saíram de um agente que não viu o raciocínio de quem o
escreveu, a mandar SQL que ninguém ali tinha imaginado.

E a segunda metade da lição custou menos e vale o mesmo: **duas vezes neste
ticket foi o teste do caminho legítimo que encontrou o defeito** — na regra do
`SET`, e no ramo «predicado antes do `WHERE`» que a cobertura mostrou a
descoberto e que se revelou uma evasão real (`SELECT (merchant_id = $1) AS meu
FROM product WHERE sku = $2` devolve as linhas de todos os merchants com uma
coluna a dizer quais são deste). Uma barreira que só tem canários de recusa
acaba recusada por quem ela irrita.

---

## 7. Controlo de versões

| Versão | Data | Alteração | Autor |
|---|---|---|---|
| 1.0 | Outubro 2026 | Primeira versão. Revisão adversarial do KAM-042: 17 `CONFIRMADO` corrigidos, 12 `MORTO` registados com evidência, **três** escapes de portão devolvidos ao fundador com a medição — e o terceiro é o número desta própria análise, que colidiu e cuja classe de colisão já estava em `main` sem nenhum gate a ter visto (duas `ANALISE-39`). | Equipa KAMBÁ |
