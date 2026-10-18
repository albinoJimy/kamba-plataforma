# Auditoria — `audit_log`, cadeia de hash e âncora

| Campo | Valor |
|---|---|
| Âmbito | A tabela `platform.audit_log`, a cadeia de hash por tenant, a função `audit_append`, o verificador e a âncora diária |
| Entregue por | KAM-012 (revisão `0006`) |
| Fontes | `docs/tecnica/08_Seguranca_Conformidade.md` §6 e §3.3, `docs/tecnica/06_Dados_Eventos_Analytics.md` §7.1 e §7.6, ADR-013, ADR-015, `specs/02_Dicionario_de_Dados_Canonico.md` §3.2 (emenda 1.14) |
| Estado | *proposta* — como tudo o que ainda não correu em produção |

| Aprovação | Nome | Data |
|---|---|---|
| Responsável de Segurança | | |

---

## 1. A tese, e o que ela não cobre

**Uma linha escrita no `audit_log` não se altera, não desaparece, e se alguém
a mexer por fora isso descobre-se** — e o que a protege não é um privilégio,
porque o dono da tabela tem-nos todos.

A revisão adversarial mostrou que a primeira versão desta frase era falsa em
três sítios, e os três estão fechados: o papel da aplicação forjava uma linha
encadeada (§4.1), apagar e reinserir com outra data passava despercebido (§3),
e uma cadeia **inteira** apagada não produzia achado nenhum. O último fecha-se
com a âncora, e não com o verificador sozinho: quem percorre o que existe não
vê o que deixou de existir. É por isso que o `verificar --ancora` existe, e é
por isso que a âncora não é um ficheiro decorativo.

## 2. O que entra, e o que nunca entra

Entra o que o `docs/tecnica/08` §6 nomeia: dinheiro, stock, preço, acessos
privilegiados e alterações de configuração de tenant.

**Não entra conteúdo.** O que seria conteúdo entra em `payload_hash`, que é
SHA-256 de 32 bytes — e um `CHECK` garante-o. O `actor_id` identifica quem
agiu, que é o ponto de uma auditoria, mas é uma **referência**: `contact_id`,
utilizador de *staff* ou nome de *job*; nunca telefone nem nome.

A razão não é só o §7.1. É o §7.6 do `docs/tecnica/06`: um registo imutável só
sobrevive ao direito de apagamento se não tiver nada para apagar. Uma tabela
*append-only* com dado pessoal lá dentro é uma tabela que a lei obriga a
alterar — e aí deixa de ser *append-only*.

## 3. As três camadas da imutabilidade, e porque são três

Cada uma prende o que a anterior deixa passar. **Todas medidas** contra o
PostgreSQL 18.6 fixado por *digest*, numa base descartável:

| Camada | Prende | Deixa passar |
|---|---|---|
| `REVOKE UPDATE, DELETE, TRUNCATE ... FROM PUBLIC` | quem tem o privilégio por omissão | **o dono da tabela**, que o tem sempre |
| *trigger* `BEFORE UPDATE OR DELETE` e `BEFORE TRUNCATE` | o dono | **quem pode `SET session_replication_role = replica`** |
| `ENABLE ALWAYS TRIGGER` | também esse | quem desliga o *trigger* com `ALTER TABLE`, que exige ser dono e é um acto que não se faz por engano |

A segunda linha é a que importa para quem leu o bloco do ticket: ele propõe
adulterar uma linha no ambiente de teste **com** `session_replication_role`, e
a medição mostrou que isso atravessa um *trigger* normal sem resistência. Com
`ALWAYS`, não atravessa — e o teste de adulteração passou a usar
`ALTER TABLE ... DISABLE TRIGGER`. É um desvio ao critério 5, declarado, e o
que se ganha é que o caminho que o critério nomeava deixou de existir.

## 4. A cadeia

```
row_hash = SHA-256( prev_hash ‖ tenant_id ‖ actor_type ‖ actor_id ‖ action
                    ‖ entity ‖ entity_id ‖ turn_id ‖ payload_hash )
```

Nove campos, por **ordem fixa**, separados por `chr(31)` — o separador não é
cosmético: sem ele, `('ab','c')` e `('a','bc')` dão o mesmo hash. Os `bytea`
entram em hexadecimal; os dois anuláveis chegam já normalizados a texto vazio.

**O `criado_at` entra; o `id` não.** Na primeira versão nenhum dos dois
entrava, com o argumento de que a cadeia não devia depender de valores que a
base atribui. A revisão adversarial mostrou o preço: apagar a última linha e
reinseri-la com o mesmo conteúdo e outra data deixava a cadeia «intacta» — a
sequência era à prova de adulteração e a **cronologia** não era de todo. Para
um registo cujo valor probatório é «quem fez o quê *e quando*», isso é uma
lacuna de fundo. O `id` continua de fora, e esse argumento mantém-se: um `id`
reatribuído numa restauração partia a cadeia inteira sem nada estar errado.

O `criado_at` entra em **ISO 8601 UTC com microssegundos**, e não como o
`timestamptz` que é: um `timestamptz` renderizado no fuso da sessão daria
hashes diferentes conforme quem verifica.

Uma cadeia por tenant, mais **uma para as acções de plataforma**
(`batch.run`, `breakglass.open`), que não têm tenant. A primeira linha de cada
cadeia parte da génese — trinta e dois zeros, e não `NULL`: com `NULL`, o
`prev_hash NOT NULL` tornava a primeira linha impossível, e a verificação
tinha de tratar o primeiro elo como caso especial.

### 4.1 Quem pode escrever a cabeça da cadeia, e porquê só o trigger

**A primeira versão errou aqui, e o erro é instrutivo.** Pôs a cadeia dentro
de `audit_append`, com `SECURITY INVOKER`, e justificou-o assim: o
`RETURNING old./new.` serializa o tenant sem privilégio elevado, logo não é
preciso `SECURITY DEFINER` e a lista continua vazia.

O raciocínio provava a coisa errada. **Serializar é uma propriedade; ser o
escritor exclusivo é outra.** Com `SECURITY INVOKER`, para a função funcionar
o chamador tem de ter `INSERT` em `audit_log` e `SELECT`/`UPDATE` em
`audit_heads` — e quem os tem pode dispensar a função. A revisão adversarial
demonstrou-o: o `kamba_app` lia a cabeça, escrevia uma linha correctamente
encadeada com `criado_at` à escolha, avançava a cabeça, e o verificador dizia
«cadeia intacta».

Hoje a cadeia vive num **trigger `BEFORE INSERT`** que recalcula `criado_at`,
`prev_hash` e `row_hash` e ignora o que o chamador enviar nessas três colunas.
O `INSERT` do `kamba_app` é **por coluna** e não as inclui; nenhum papel de
aplicação escreve em `audit_heads`. Escrever directamente na tabela deixou de
ser um ataque: dá exactamente o mesmo resultado.

A função do trigger é que é `SECURITY DEFINER`, com `search_path` fixo, e é a
**primeira entrada** de `ci/secdef_allowlist.yaml`. A excepção é estreita: ela
não escreve a linha — escreve a cabeça da cadeia, que é precisamente o que
quem escreve a linha não pode poder fazer.

A serialização continua a vir do mesmo sítio, e essa parte do raciocínio
aguenta. Medido: **o PostgreSQL 18 aceita `old.` e `new.` no `RETURNING`**, e
com isso uma única instrução dá as duas pontas:

```sql
INSERT INTO platform.audit_heads AS h (tenant_id, last_hash)
VALUES (p_tenant, platform.audit_row_hash(GENESE, …))
ON CONFLICT (chave) DO UPDATE SET last_hash = platform.audit_row_hash(h.last_hash, …)
RETURNING coalesce(old.last_hash, GENESE), new.last_hash
```

O `ON CONFLICT DO UPDATE` bloqueia a linha da cabeça até ao `COMMIT`, e é isso
que serializa o tenant. Dentro de um *trigger* a sintaxe tem de renomear os
dois registos — `RETURNING WITH (OLD AS …, NEW AS …)` —, porque o `OLD` e o
`NEW` da função **ensombram** os do `RETURNING`: medido,
`record "old" has no field "last_hash"`.

**E exige `READ COMMITTED`**, que é a omissão. Medido: sob `REPEATABLE READ`,
duas escritas concorrentes na mesma cadeia dão `40001` e a segunda perde-se —
e como esta função é para ser chamada dentro da transacção de negócio
(KAM-028, KAM-054), um chamador nesse nível aborta o negócio por causa da
auditoria. Está dito no `COMMENT` da função.

Um `SELECT ... FOR UPDATE` antes não servia, e vale a pena dizer porquê: numa
cadeia que ainda não existe **não há linha para bloquear**, e duas primeiras
inserções concorrentes partiam ambas da génese.

### 4.2 A chave gerada

Uma chave primária recusa `NULL`, e a cadeia de plataforma precisa de uma
linha com `tenant_id` nulo. A chave de `audit_heads` é por isso uma coluna
**gerada** — `coalesce(tenant_id, '000…0')` — e é ela o alvo do `ON CONFLICT`.
O `tenant_id` continua a dizer a verdade, incluindo que não há nenhum.

## 5. O que foi medido, e o que a medição desmentiu

Contra `pgvector/pgvector:0.8.7-pg18` (o *digest* de `ci/supply-chain/imagens.yaml`),
**antes** de a revisão ser escrita, e outra vez depois:

| # | Pergunta | Resposta medida |
|---|---|---|
| M1 | `old.`/`new.` no `RETURNING` de um `ON CONFLICT DO UPDATE`? | **Sim.** `old` é `NULL` na inserção e o valor anterior no conflito |
| M4 | `tenant_id uuid PRIMARY KEY` aceita `NULL`? | **Não** — daí a coluna gerada |
| M6 | O `REVOKE` prende o dono? | **Não.** `UPDATE`, `DELETE` e `TRUNCATE` passavam |
| M7 | `session_replication_role = replica` contorna um *trigger* normal? | **Sim.** A linha ficou adulterada |
| M8 | E um `ENABLE ALWAYS`? | **Não.** O `UPDATE` falhou e a linha ficou intacta |

E quatro coisas que a execução da própria revisão apanhou:

1. **A cadeia de plataforma era impossível de escrever.** A função de hash é
   `STRICT`, e com o `tenant_id` como `uuid` um valor nulo fazia-a devolver
   `NULL`; o `NOT NULL` da cabeça recusava a linha. O parâmetro passou a
   `text`, normalizado pelo chamador.
2. **O `kamba_batch` não conseguia escrever** a cadeia de plataforma — é o
   único que pode, por ter `BYPASSRLS` — porque só tinha `SELECT` na tabela
   das cabeças.
3. **Dois ensaios passavam por razão errada**, dando verde por falta de
   `GRANT USAGE` no *schema* e não pela regra que mediam.
4. **Três instruções eram ilegíveis para o *gate* 3b**, que lê a revisão sem a
   correr: um `CHECK` construído por `join` é um domínio que ele não verifica.
   Escreveram-se por extenso, com a bateria a confrontar as duas formas.

## 6. Verificar e ancorar

```bash
python db/auditoria.py verificar                 # a cadeia inteira
python db/auditoria.py verificar --tenant <uuid> # só uma
python db/auditoria.py ancorar                   # a âncora do dia
```

**O verificador reimplementa a fórmula em Python**, e não chama
`platform.audit_row_hash`. Verificar uma cadeia com a função que a escreveu
não verifica nada: um defeito **nela** aparece dos dois lados e a verificação
dá sempre certo.

**Percorre a cadeia pelo `prev_hash`, e não pelo `id`.** O `id` sai da
sequência quando a instrução começa e o lugar na cadeia decide-se depois,
quando o *trigger* bloqueia a cabeça: com mil inserções concorrentes as duas
ordens divergem, e um verificador que percorresse por `id` via elos partidos
que não existem. A cadeia diz a sua própria ordem.

Distingue quatro achados, porque a resposta operacional é diferente:

| Achado | O que aconteceu |
|---|---|
| **fora da cadeia** | o `prev_hash` de uma linha não é o `row_hash` de nenhuma outra e ela não parte da génese — alguém apagou uma linha do meio, ou inseriu uma forjada |
| **hash errado** | o `row_hash` não bate com as colunas — alguém alterou uma coluna, ou reescreveu a data |
| **cabeça errada** | a cadeia está inteira e a cabeça não aponta para o fim — alguém apagou linhas **do fim** |
| **desapareceu inteira** | a âncora de um dia anterior tem uma cadeia que já não existe — só este achado precisa da âncora, e é o único que o verificador sozinho não pode dar |

O terceiro é o que justifica a tabela de cabeças existir para além do
desempenho: sem ela, apagar as últimas N linhas de uma cadeia deixava-a
**consistente consigo própria**.

A âncora é o último `row_hash` por cadeia, num ficheiro JSON do dia,
**reproduzível a partir da base**: as mesmas linhas dão o mesmo ficheiro, byte
a byte, **em qualquer fuso**. A última parte custou uma correcção: a fronteira
do dia era `criado_at < (dia + 1)`, que promove o `date` com o `TimeZone` da
sessão, e com `Africa/Luanda` — que é a omissão de `tenants.fuso_horario` — a
mesma base no mesmo dia dava outra âncora. É em UTC, e há um teste que corre o
`ancorar` duas vezes com fusos diferentes e exige o mesmo ficheiro.

## 7. Quem escreve, quem lê

| Papel | `audit_log` | `audit_heads` |
|---|---|---|
| `kamba_app` | `INSERT` **por coluna** — sem `criado_at`, sem os hashes — e **não `SELECT`** | **nada** |
| `kamba_batch` | `SELECT`, `INSERT` por coluna | `SELECT` |
| `kamba_audit` | `SELECT` | `SELECT` |
| `kamba_migrator` (dono) | tudo, e mesmo assim não altera nem apaga — o *trigger* recusa | idem |

**Quem escreve não lê**, que é o critério 9 — e quem insere **não escolhe** a
data nem os hashes, que é o que fecha o achado crítico. O `INSERT` por coluna
não é redundante com o *trigger*: uma coluna que nenhum chamador pode escrever
é uma coluna que nenhum chamador tenta escrever.

O papel de auditoria **lê** a tabela de cabeças, ao contrário do que a primeira
versão decidiu: verificar a cadeia exige-a, porque sem ela apagar as últimas N
linhas deixa-a consistente consigo própria. Negá-la tornava o verificador
impossível de correr com o papel estreito — as duas decisões eram
incompatíveis, e a revisão adversarial apanhou-o.

E as funções nascem com `EXECUTE` para `PUBLIC`, que é a omissão do
PostgreSQL: sem um `REVOKE` explícito, o `kamba_resolver` podia chamá-las e os
`GRANT` nominais eram decorativos.

**Ninguém tem `DELETE` nem `UPDATE`**, nem o `kamba_batch`. A retenção do
`audit_log` é «≥ prazo fiscal» (`docs/tecnica/08` §11) e o prazo fiscal está
**NÃO VERIFICADO** (dicionário §4, KAM-071): uma função de limpeza escrita
contra um prazo que ninguém confirmou apaga prova que a lei pode exigir.

## 8. O que fica por fazer, e onde

| # | O quê | Onde |
|---|---|---|
| 1 | O *job* nocturno que corre o verificador, e o encaminhamento do alerta Sev1 | KAM-078. Hoje o verificador sai com código 2 e uma linha por achado no `stderr` |
| 2 | A métrica `audit_chain_verify_failed_total` | Nasce com o encaminhamento (ADR-018) |
| 3 | A âncora exportada para fora do *host* | KAM-079. Até lá, ficheiro local |
| 4 | WORM real | Clusters, se o `StorageProvider` o suportar — **NÃO VERIFICADO** para SeaweedFS |
| 5 | Instrumentar as *tools* de dinheiro, stock e preço | KAM-028 |
| 6 | Instrumentar o `ManualProvider` | KAM-054 |
| 7 | A retenção, quando o prazo fiscal estiver confirmado | KAM-071 |
| 8 | **Nada chama `audit_append` em produção** | É a consequência de 5 e 6: a função existe, está testada contra a base real, e nenhum código de produção a usa |
| 9 | **O p95 ≤ 5 ms do critério 8 não foi medido** | Não há teste, não há número, e esta linha existe porque a revisão adversarial notou que a tabela acima se apresentava como o inventário do que falta e não o incluía — um leitor concluía que estava feito. O KAM-005 fechou o seu p95 com execução; este fica por fechar |
| 10 | **A leitura do registo não se regista** | O critério 9 pede «leitura só por papel de auditoria **com registo da própria leitura**». A acção `audit.read` entrou no domínio para isso e **nada a escreve**: o `kamba_audit` não tem `INSERT`. Fica por fazer, e o valor de domínio é uma promessa registada no dicionário até lá |

## 9. Controlo de versões

| Versão | Data | Alteração | Autor |
|---|---|---|---|
| 1.0 | Outubro 2026 | Emissão (KAM-012): a revisão `0006`, a cadeia, o verificador e a âncora. As cinco medições contra o PostgreSQL 18.6 e os quatro desvios que elas obrigaram. | Equipa KAMBÁ |
| 1.1 | Outubro 2026 | **O que a revisão adversarial mudou (KAM-012).** Deu REPROVADO, e o crítico era de desenho: com a cadeia dentro de uma função `SECURITY INVOKER`, o papel da aplicação forjava uma linha encadeada com a data à escolha. A cadeia passou para um *trigger* `BEFORE INSERT`; o `INSERT` é por coluna; o `criado_at` entrou no hash; o índice único passou a ser por tenant (era um oráculo que atravessava a RLS); as funções deixaram de ter `EXECUTE` para `PUBLIC`; as colunas de texto ganharam tecto; e o verificador passou a seguir o `prev_hash` em vez do `id` — que com mil inserções concorrentes não é a mesma ordem. | Equipa KAMBÁ |
