# ANÁLISE-05 — Revisão adversarial do KAM-111 (dicionário canónico e gate 3b)

| Campo | Valor |
|---|---|
| Ticket | KAM-111 — Dicionário de dados canónico e reconciliação de `docs/tecnica/` |
| Ramo | `feature/KAM-111-dicionario-canonico-e-lint` (PR `albinoJimy/kamba#17`) |
| *Baseline* revista | `f77236e` |
| Data | Outubro 2026 |
| Método | Execução, não leitura: evasões escritas e corridas em cópias fora do repositório; 47 mutações ao código do lint |
| Veredicto da revisão | **Não aprovado** — 3 bloqueantes, 9 maiores, 9 menores, 4 notas |
| Estado | B1 corrigido; B2 e B3 **não se cumprem à letra e as caixas ficam vazias**; 8 maiores corrigidos e 1 (M2) corrigido em parte, com o resto medido; 5 menores corrigidos e 4 registados; **3 tickets `fix` abertos** (KAM-139 a KAM-141) |
| Verificação final | Os oito *gates* e o resumo verdes no PR #17 depois das correcções; segunda prova por mutação: 68 mutações válidas, 67 apanhadas, 1 equivalente |

A revisão foi conduzida por um agente independente, que recebeu os requisitos e
o código e **não** as justificações de quem o escreveu. O PR estava verde nos
oito *gates* — incluindo o que este ticket entrega — e a revisão não aprovou.

> **A lição desta revisão é que eu sabia os três modos de falha e cometi os
> três.** As `ANALISE-02` e `-03` estavam na lista de leitura obrigatória deste
> ticket, com a frase «vais cometer os mesmos erros se não as leres». Li-as. O
> canário que eu próprio desenhei para provar que as superfícies vazias mordem
> **lia do YAML de *fixtures* quantos casos tinha de correr** — um manifesto
> vazio dava verde; o `docs/ci.md` afirmava «SQL que não é literal falha» e
> havia nove formas de o fazer passar; e a prova de que o domínio fechado
> funciona era um teste com `estado IN (…)`, quando a forma que o `pg_dump`
> escreve é `estado::text IN (…)`. Ler a descrição de um defeito não impede de
> o reproduzir: o que impede é alguém a tentar parti-lo.

---

## 1. Bloqueantes

### B1 — O canário podia ser esvaziado com o *gate* e os testes verdes

`tools/canon_lint/cli.py` (`canario`); `tools/canon_lint/tests/test_repositorio.py`

Com `casos: []` no manifesto e as dez divergências movidas para
`sem_forma_de_nome`, o `canario` saía com 0 e «0 negativas vermelhas… 12
divergências sem forma de nome», e o teste que o cobria passava: só exigia
`negativas == positivas` e `negativas + sem_forma == 12`. Com o `espera` de
todos os casos reduzido a uma crase, também passava — o canário só procurava
uma *substring*.

O passo existe para provar que `eventos` e `registo` mordem enquanto estão
vazias no repositório. Essa prova desaparecia com uma edição a um ficheiro de
*fixtures*.

**Corrigido.** O que o canário prova passou para o código: as doze
divergências, as duas que podem não ter *fixture* (`SEM_FORMA_DE_NOME`) e o
mínimo de uma negativa por superfície. Cada negativa tem de dar **exactamente
um** achado cuja mensagem **começa** pelo `espera`, e o `espera` tem de ter a
forma «`variante` → `canónico`, dicionário §3.x». Nove testes novos sobre o
próprio canário (`TestCanario`): manifesto vazio, caso movido, caso duplicado,
`espera` trivial, `espera` errado, negativa que passou a estar certa, negativa
com segundo achado, positiva que deixou de passar. As mutações M24 e M25, que
sobreviviam, são agora apanhadas.

### B2 — «12 negativas e 12 positivas»: há 10 + 10

**Não corrigido — devolvido.** D-07 (quem reage a `tenant.activated`) e D-09 (a
retenção de `assistant_queries`) não têm forma de nome em nenhuma das três
superfícies. Não se inventaram *fixtures*. **A caixa do critério 6 fica vazia**,
e a decisão é de quem escreveu o critério: KAM-141, linha 8.

**O agravante confirma-se e fica registado.** A positiva do D-03 não tem
`currency`, porque o gate recusa a forma canónica do próprio D-03: o ticket
dá `valor_minor` + `currency` «(§3.4)», e o §3 do dicionário não lista
`currency` — só o §2. Não se contornou com uma extensão: é uma contradição do
canon (KAM-141, linha 2), e está dita no manifesto.

### B3 — Parte (a): os critérios 1 e 2 não se cumprem à letra

**Não corrigido — as duas caixas ficam vazias.**

- **Tamanho.** `git diff --shortstat origin/main...HEAD -- docs/tecnica`:
  **87 inserções, 72 remoções** em 10 documentos (eram 84/69 na *baseline*
  revista; as três linhas a mais são os resíduos corrigidos abaixo). O critério
  diz «≤ 80 linhas alteradas (*proposta*)». Só passa contando remoções, ou
  inserções sem as dez linhas de controlo de versões (77).
- **Variantes vivas.** As 18 ocorrências em dívida são usos vivos, não citações.
  O critério 1 só admite «notas "substitui X"» e tabelas de correcção. São
  variantes de outras linhas do §3, fora das doze — e por isso o ticket não as
  podia corrigir («as 12 e só essas»). Os dois critérios chocam: o 1 pede zero,
  o 2 proíbe tocar-lhes.
- **Tickets `fix`.** Não havia nenhum. **Abertos agora:** KAM-139 (as 18
  variantes vivas), KAM-140 (as divergências que não são de nome) e KAM-141 (as
  contradições do dicionário), com bloco no EPIC-01 e linha no backlog mestre.
- **Linhas fora da coluna «Onde emendar».** Doze, todas atribuíveis a uma das
  doze divergências (a pesquisa não dava zero sem elas, ou as FK partiam).
  Nenhuma órfã.

Três resíduos da parte (a) que a revisão encontrou **foram corrigidos**, por
pertencerem às doze: `06` §7.2 dizia «retenção (13 meses)» dois parágrafos acima
da linha emendada pelo D-09, e `06` §7.2 e §7.6 ainda usavam `lookup_hmac`
depois de o D-01 o ter trocado por `bsuid_hmac`.

---

## 2. Maiores

| # | Achado | Estado |
|---|---|---|
| M1 | **O domínio fechado (D-08) contornava-se com a forma que o `pg_dump` escreve.** `estado::text IN (…)`, `((estado)::text = ANY ((ARRAY[…])::text[]))`, `estado = 'a' OR estado = 'b'`, um ENUM, ou a coluna sem `CHECK` nenhum: `tenants.estado` sem `restrito` passava. Com `::text` a coluna era lida como `text` e o domínio não se encontrava. | **Corrigido.** Casts e parênteses normalizados na coluna; cadeia de `OR` sobre a mesma coluna é domínio fechado; um ENUM é o domínio da coluna que o usa; uma coluna com domínio num `CHECK` ilegível (`SIMILAR TO`, `~`) falha; uma coluna com domínio qualificado sem `CHECK` fechado falha. **Fica:** `estado IN (…) AND true` é lido como comparação solta (limite escrito). |
| M2 | **O nível 2 aceitava qualquer nome «conhecido» em qualquer posição.** 295 nomes sem tipo, incluindo `a`, `z0`, `_`, `boolean`, `uuid`, `SELECT`, e as metades dos eventos. De 77 nomes plausivelmente errados, **51 (66%) passavam** como tabela, coluna, evento, *tool* ou campo. | **Corrigido em parte, e o resto medido.** Só minúsculas; palavras de tipo SQL fora; três caracteres ou um *span* inteiro; eventos, *tools*, papéis e esquemas com conjunto próprio. Remedido com os mesmos 77: **37 (48%) como coluna, 0 como evento, *tool* ou papel**. Tabelas, colunas, valores, campos e parâmetros continuam a partilhar 211 nomes: o §3 não diz o tipo de cada um. KAM-141, linha 9. |
| M3 | **Uma variante dentro de uma cadeia SQL não era vista.** `'{"valor_max_pedido_kz": 5000000}'`, `jsonb_build_object('valor_max_pedido_kz', …)`, `limites ? 'valor_max_pedido_kz'`: zero achados. É uma chave de `jsonb` — em SQL **só** existe como cadeia. Era uma das duas dívidas do KAM-003, e o gate não a via no único sítio onde uma migração a escreveria. | **Corrigido.** Nível 1 dentro de cadeias, com fronteira de palavra, e dentro dos blocos `$$`. Um `COMMENT ON … IS 'substitui consent_log'` passa a falhar; está dito. |
| M4 | **SQL não literal que passava em silêncio**, contra o que o `docs/ci.md` afirmava: `sa.Table(…).create(bind)`, `meta.create_all()`, `from alembic import op as o`, `alembic.op.create_table`, constante de módulo sombreada ou reatribuída, `run = op.execute`, `getattr(op, "execute")`. | **Corrigido, por reescrita.** O extractor passou a avaliador estático (`revisao.py`): segue os *alias* pelos imports, recusa constantes ligadas mais de uma vez, metadados do SQLAlchemy, o objecto `op` fora de uma chamada directa, imports não declarados e revisões sem instrução lida. Ver §4. |
| M5 | **DDL que introduz nomes sem os mostrar:** `DO $$ … CREATE ROLE … $$`, `SELECT … INTO`, `CREATE SCHEMA x CREATE TABLE …`, `CREATE TYPE … AS (…)`, `CREATE DOMAIN`, `ALTER TYPE … ADD VALUE`, `CREATE SCHEMA AUTHORIZATION`. | **Corrigido.** Um bloco `$$` com `CREATE`/`ALTER` (ou `EXECUTE 'CREATE…'`) falha; `SELECT … INTO` e `CREATE SCHEMA` com elementos são desconhecidos; tipos, domínios e atributos de tipo composto têm nível 2. **Fica:** as colunas de uma vista. |
| M6 | **As sentinelas não cobriam caminhos que os próprios documentos nomeiam.** `migrations/0002_idx_schema.sql` — o caminho que o EPIC-06 manda usar — dava «conforme» com uma variante lá dentro. A superfície `registo` não tinha sentinela nenhuma. | **Corrigido.** `migrations/*`, `*/versions/*.py`, `*.sql`, `registry/*`, `*/registry/*`, `*/events/*`, `docs/tecnica/*.md`; comparação em minúsculas (`x.YAML`, `0002.PY`). 19 caminhos num teste. **Decisão sobre o TypeScript do Medusa:** o gate não lê TypeScript; `*/migrations/*` apanha essas migrações, o gate falha, e quem as declarar fora de âmbito escreve nesse momento porquê — em vez de ficarem de fora por omissão. **Fica:** um *schema* com outro nome fora de uma pasta `eventos/`. |
| M7 | **Schemas de evento:** `$ref` interno, `required` sem `properties`, `propertyNames`, `patternProperties`, `dependentRequired`, `prefixItems`, chave repetida, `versao: {const: true}`, e ficheiros `V1.schema.json` ou `payment.confirmed.v1.schema.json` que dispensavam `tipo` e `versao` fixos. | **Corrigido.** Nível 1 sobre **todo** o documento; `$ref` interno seguido; `required`, `dependentRequired` e `propertyNames` contam como nomes; `patternProperties` no *payload* é ilegível; chave repetida é ilegível; `type(v) is int`; todo o ficheiro da superfície chama-se `v<N>.schema.json` ou está em `eventos_partilhados`. |
| M8 | **Registo:** `subscricoes:` ou `ferramentas:` de topo passavam o ficheiro ao lado das verificações; `confirm:{{cart_id}}` não batia no padrão e passava; `catalogo` aceitava `confirm:{cart_id}`. | **Corrigido.** Listas fechadas de chaves (topo, `entitlements`, subscrição, *tool*); qualquer `confirm:…` que não seja o da vertical falha; as três verticais de entrada mapeadas para `confirm:{item_id}` (*leitura*, marcada *proposta*). **Fica:** `id: servicos` com `modulo: vendedor`. |
| M9 | **As excepções alargavam-se em silêncio:** dívida com `criado_em: 2031-01-01` passava; uma «histórica» trocada por uso vivo com a mesma contagem passava; extensão com data futura passava; `sentinelas: []` na política desligava a protecção. | **Corrigido.** `criado_em ≤ hoje`; data de extensão não futura; dez sentinelas mínimas no código; históricas com **âncora** (o excerto que prova que é citação). **Fica:** a revisão «pelo Arquitecto de Plataforma» não é imposta — o *ruleset* tem zero aprovações (`docs/ci.md` §7, lacuna 16). Uma extensão com um ticket que não existe no backlog é apanhada pelo gate 3, que lê `canon/extensoes.yaml` como qualquer outro ficheiro — e apanhou esta mesma frase quando citava o identificador inexistente que a revisão usou. |

---

## 3. Menores e notas

| Achado | Estado |
|---|---|
| m1 — `E'a\'b'` fechava a cadeia a meio e engolia o DDL seguinte | **Corrigido** — o prefixo `E` é reconhecido |
| m2 — identificador entre aspas com maiúsculas escapava ao nível 1 | **Corrigido** para o nome exacto (`"Valor_Kz"`). Um nome que **contém** a variante (`"IX_Valor_Kz"`) não é a variante, pela mesma fronteira de palavra que deixa passar `max_preco_kz` |
| m3 — evasões da unicidade do D-06 (`WHERE true`, `lower(referencia)`, `EXCLUDE`) | **Registado** — limite escrito em `docs/nomes-canonicos.md` §1 |
| m4 — formas partidas nos documentos (`valor\_kz`, `Valor_KZ`); `max_preco_kz` e afins existem em `05` | **Registado** — os derivados com `_kz` entram no KAM-139 |
| m5 — a exportação ignorava em silêncio uma tabela indentada; uma variante canónica noutra linha era descartada sem aviso; só oito das treze variantes tinham teste | **Corrigido** — tabela indentada é erro; contradição registada; o conjunto das treze está fixado num teste. **Fica**, por não ter solução mecânica: variante sem crases ou em prosa fora de tabela |
| m6 — `ci/canon-allow.yaml` dizia que o vencimento «está dito no bloco do KAM-111», e não estava | **Corrigido** — está agora, e o comentário cita o KAM-139 |
| m7 — a 2026-11-11 `main` fica vermelho, sem dono nem ticket | **Tem dono:** KAM-139. Continua deliberado |
| m8 — «0,9 s (Python 3.13)» contra um CI em 3.12 | **Corrigido** — o `docs/ci.md` dá os dois números: 7 s no *runner* (3.12), 0,9 s no contentor local (3.13) |
| m9 — contradições novas da parte (a) | Os três resíduos das doze **corrigidos** (§1, B3). As restantes — `07` sem `restrito`, `payment.confirmed` como único evento em `03` e `04`, as duas formas de `contacts`, a tabela de `10` §15.1 — **não são das doze**: KAM-140 |
| n1 — o gate 3b bloqueia só pelo *job* de resumo | **Demonstrado**, e não só lido: §6 |
| n2 — `entitlements.modulo`: domínio no §3.7, `CHECK` de forma no §3.2 | **Registado** — a política declara que o domínio só vale no registo; KAM-141, linha 6 |
| n3 — `distinguem_o_caminho: [servicos]` em fluxo dava erro | **Corrigido** — a política mostra a forma em bloco |
| n4 — o `dict_export` não reconfigurava o *stdout* para UTF-8 | **Corrigido** |

---

## 4. A integração com o KAM-004, que a correcção do M4 tornou urgente

A revisão `0002_rls_por_tenant.py` do KAM-004 — que entra em `main` antes deste
ticket — usa `op.execute` com *f-strings* dentro de um ciclo e chama
`db/rls.py`, que monta `ALTER TABLE … ENABLE ROW LEVEL SECURITY` e
`CREATE POLICY` também com *f-strings*. Com a regra «SQL não literal falha», o
gate 3b ficava vermelho no dia do *merge*.

Havia duas saídas fáceis, e as duas enfraqueciam a falha fechada: declarar
`db/rls.py` fora de âmbito, ou deixar passar *f-strings*. **Não se fez nenhuma.**
O leitor de revisões passou a **seguir** o que é determinável sem executar:

- *f-strings* sobre constantes de módulo e `", ".join(…)`;
- ciclos `for … in CONSTANTE.items()`, desdobrados iteração a iteração;
- chamadas a um módulo auxiliar **declarado** em `ci/canon-lint.yaml`
  (`auxiliares_de_migracao`): o lint abre o ficheiro, liga os argumentos da
  chamada aos parâmetros, e segue o corpo — incluindo a variável local
  `alvo = f"{schema}.{tabela}"` e a função pura `predicado(coluna)`.

O SQL que sai é o que a revisão executaria, e é verificado como qualquer outro.
Um módulo declarado **não é dispensado de leitura**: se o corpo tiver algo que o
lint não segue, a chamada falha; e uma variante passada como argumento
(`rls.enable_tenant_rls("consent_log")`) chega ao SQL lido e é apanhada.

**Medido contra os ficheiros reais** do ramo `feature/KAM-004-rls-force-e-isolamento`
(`git show`, numa cópia): **28 instruções lidas, 18 delas vindas de `db/rls.py`,
zero ilegíveis, zero achados**; com a `0001`, 49 instruções em 2 ficheiros. O
ficheiro `db/rls.py` não foi tocado. A entrada da política existe já neste PR;
enquanto o ficheiro não existir em `main`, nenhuma revisão o importa e a entrada
não é exercida — os testes exercem-na com uma cópia da sua forma.

O que isto **não** é: um interpretador de Python. Segue chamadas directas, com
argumentos literais. O que não segue, recusa.

---

## 5. A prova por mutação, refeita

A revisão fez 47 mutações ao código; **8 sobreviviam**, e as que importavam eram
M24 e M25 (o canário não era testado), M31 (papéis), M34 (valores de `CHECK` sem
domínio) e M11 (contagem para menos).

Depois das correcções: **68 mutações**, uma de cada vez, em cinco cópias fora do
repositório, com as duas *suites* a correr em cada uma e **linha de base verde**
(`scratchpad/mutar.py`; cerca de 50 minutos).

| Grupo | Mutações | Apanhadas |
|---|---|---|
| As sobreviventes da revisão (M11, M24, M25, M31, M34, M40 ×2, M43) | 8 | 8 |
| Canário (B1): conjunto, sem-forma, mínimo por superfície, forma do `espera`, achado único | 5 | 5 |
| Domínios (M1): casts, cadeia de `OR`, ENUM, `CHECK` ilegível, sem `CHECK` | 5 | 5 |
| Nomes conhecidos (M2): minúsculas, tipos SQL, comprimento, conjuntos próprios, metades de evento | 5 | 5 |
| Cadeias (M3): procura em cadeias, fronteira de palavra | 2 | 2 |
| Leitor de revisões (M4): usos indevidos, constantes, locais, revisão vazia, imports, *alias*, API, `text()` solto, auxiliar | 10 | 10 |
| SQL (M5, m1): bloco `$$`, `SELECT INTO`, `CREATE SCHEMA`, tipos, prefixo `E` | 5 | 5 |
| Sentinelas e datas (M6, M9): minúsculas, mínimas, `criado_em`, data de extensão, âncoras ×2 | 6 | 6 |
| Eventos (M7): `$ref`, `required`, chave repetida, nome do ficheiro, `bool`, nível 1 em tudo, `patternProperties` | 7 | 7 |
| Registo (M8): chaves de topo, de `entitlements`, de subscrição e de *tool*; padrão de confirmação | 5 | 5 |
| Exportador: tabela indentada, contradição, referências | 3 | 3 |
| Linha de base da primeira versão, por amostra | 6 | 6 |
| **Total válido** | **67** | **67** |

Duas notas sobre a contagem:

- **X3 — equivalente, e é a 68.ª.** Deixava de tratar `preco_kz` como canónico;
  `preco_kz` não é canónico em lado nenhum, pelo que a mutação não altera
  comportamento. Foi mal escolhida por mim.
- **M8c, à primeira, era inválida.** Apagava a única linha de um `if` e produzia
  um erro de sintaxe: «apanhada» pela razão errada. Refeita com `pass` e
  apanhada por `test_chave_de_topo_desconhecida_falha`; é essa que conta.

**Duas sobreviveram à primeira passagem e têm agora teste próprio:** M2a (o
filtro de minúsculas — nenhum teste usava um nome com maiúsculas) e M4h (o
`text(…)` solto — o teste que o cobria era também apanhado pela regra da revisão
sem instruções, que escondia a mutação). Reexecutadas depois dos testes novos:
apanhadas.

**O limite desta prova é o das anteriores**, e a `ANALISE-03` já o disse: são as
mutações de que alguém se lembrou. Metade vem de quem não escreveu os testes —
mas a segunda volta foi escrita por quem escreveu as correcções.

---

## 6. A demonstração do bloqueio

O critério 7 pede o gate 3b «como *job* bloqueante de merge». Lido na
configuração, bloqueia pelo *job* de resumo, que é *required check*. Como o
KAM-002 fez para os seus seis *gates*, mediu-se com um PR deliberadamente
vermelho: o PR #19 repunha `llm_calls` em `docs/tecnica/09`.

| *Check* | Resultado |
|---|---|
| gate 3b — nomes canonicos | **fail** — «`llm_calls` → `llm_call_log`, dicionário §3.6», linha 565 |
| gate 4 — unit e cobertura | **fail**, por arrasto: a *suite* do `canon_lint` verifica o repositório real |
| gates do KAM-002 (resumo) | **fail** |
| gates 1, 2, 3, 8, 9, 11 | pass |
| `mergeStateStatus` | **BLOCKED** |

*Run* 38175423832. O PR foi fechado sem fundir e o ramo apagado.

O arrasto do gate 4 é consequência de um teste que corre o lint sobre o
repositório — o mesmo padrão do PR #9 do KAM-002, em que o gate 1 arrastava
três. Não é imprecisão: uma variante no repositório é um teste vermelho.

---

## 7. O que não se reproduziu, e o que se leu de outra maneira

- **Nenhum achado da revisão deixou de se reproduzir.** Reexecutei os 175
  ficheiros de evasão do revisor contra o código corrigido: 152 passam a ter
  achados; os 23 que continuam sem achados são casos legítimos (uma revisão
  vazia, uma unicidade correcta com `account_id`, `versao: {enum: [1]}`) ou os
  limites escritos acima (m3, vistas, `$ref` externo, `modulo` cruzado).
- **Um caso li de outra maneira.** `CREATE INDEX "IX_Valor_Kz"` (m2) não passou
  a falhar: o nome contém a variante, não é a variante. Fazer falhar por
  *substring* punha `max_preco_kz` a falhar também, e essa fronteira é uma
  decisão do desenho.
- **A leitura do critério 1 pela revisão é mais dura do que a minha, e é a dela
  que vale.** Eu lia «cada variante substituída» como as das doze divergências —
  e essas estão a zero, salvo citações. A revisão leu que 18 usos vivos de
  variantes do §3 ficam nos documentos. A caixa fica vazia.

---

## 8. Categorias sem achados

Registadas porque a ausência também é informação — são da revisão, não minhas:

- **As 13 variantes exportadas** são todas as da coluna «Substitui» entre crases
  que são nomes; conferidas à mão, linha a linha. Nenhum nome canónico
  classificado como variante.
- **As *fixtures***: negativa e positiva diferem só no que devem (salvo o D-03);
  nenhuma negativa falha por razão diferente da declarada.
- **As 12 históricas** são citações genuínas; nenhuma divergência real escondida.
- **As 20 extensões** correspondem exactamente às colunas da `0001` que nada
  mais cobre. Das 38 colunas: 10 pela assinatura da tabela, 6 por outra linha do
  §3, **2 só por um *token* de «Nota»** (`tenants.plano`, `tenants.verificado_at`
  — vêm de uma nota que diz que está «por decidir» quem as altera), 20 por
  extensão.
- **FK para `contacts`**: todas apontam para `contact_id`.
- **O exemplo de evento de `06` §4**: 24500000 de unidade menor é coerente com
  245000 Kz.
- **Integração**: `Makefile` e *workflow* coerentes; `esperados` igual ao número
  de `needs`; as duas *suites* nos dois ciclos; nenhuma construção exclusiva de
  Python ≥ 3.13 (confirmado depois pelo *runner*, em 3.12).

---

## 9. O que fica, e de quem é

| O quê | Onde |
|---|---|
| As 18 variantes vivas em `docs/tecnica/`, com prazo a 2026-11-10 | **KAM-139** |
| As nove divergências de `docs/tecnica/` que não são de nome | **KAM-140** |
| As nove contradições do dicionário, incluindo o critério das 12 *fixtures* e o nível 2 por tipo | **KAM-141** |
| A revisão das extensões pelo Arquitecto de Plataforma, e a do PR por um humano | critério 5 e DoD do KAM-111: caixas vazias |
| O *ruleset* sem o contexto do gate 3b | `docs/ci.md` §7, lacuna 17; KAM-137 |

---

## 10. Depois de integrar `main` (KAM-004 e KAM-065)

Os números das secções acima são os da revisão e das correcções, antes de o
KAM-004 fundir. A integração mudou quatro coisas, e nenhuma muda uma disposição:

- **A `0002` real é lida.** Sobre `main` integrado: 2 revisões, 49 instruções
  (21 + 28), 18 delas vindas do `db/rls.py` real, **zero achados e zero
  ilegíveis**. O que o §4 mediu numa cópia é agora o que o gate faz em cada
  execução, e está fixado num teste
  (`test_le_a_revisao_0002_real_pelo_auxiliar_real`).
  `canon/extensoes.yaml` não precisou de entradas novas.
- **O dicionário passou a 1.5** (66 entradas). A emenda do KAM-004 pôs dois
  *spans* na coluna «Substitui», e a exportação tratou-os de maneira diferente:
  - **`tenant_isolamento` é variante** (a 14.ª). `docs/tecnica/03` §5.5 usa-a:
    uma dívida nova, a 19.ª ocorrência, no KAM-139.
  - **`SET` não é.** «`SET` de sessão» é uma palavra-chave SQL; exportada como
    nome proibido, reprovava 19 ocorrências em cinco documentos (`SET LOCAL`,
    `UPDATE … SET`). A exportação passou a não tratar como variante um *span*
    todo em maiúsculas — a mesma regra que o M2 aplicou aos nomes conhecidos. O
    que essa linha substitui é uma prática, e o lint de nomes não a vê.
- **A linha «Papel do resolvedor»** escreve `tenants(id, tipo, estado)` — as
  colunas que o papel pode ler — e isso tem a forma de uma assinatura de
  tabela. O lint passou a ficar com a **primeira** assinatura de cada tabela, que
  é a que a define.
- **`esperados=9`** no *job* de resumo: os oito de antes e o gate 6.

---

## 11. Controlo de versões

| Versão | Data | Alteração | Autor |
|---|---|---|---|
| 1.0 | Outubro 2026 | Emissão: 25 achados da revisão adversarial do KAM-111, com a disposição de cada um, a integração com o KAM-004, a segunda prova por mutação e a demonstração do bloqueio. | Equipa KAMBÁ |
| 1.1 | Outubro 2026 | §10: o que mudou depois de integrar `main` (KAM-004, KAM-065) — a revisão `0002` real lida sem achados, dicionário 1.5, `tenant_isolamento` como 14.ª variante e 19.ª dívida, `SET` fora das variantes. | Equipa KAMBÁ |
