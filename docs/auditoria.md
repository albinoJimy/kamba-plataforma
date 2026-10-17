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

## 1. A tese, numa frase

**Uma linha escrita no `audit_log` não se altera, não desaparece, e se alguém
a mexer por fora isso descobre-se** — e o que a protege não é um privilégio,
porque o dono da tabela tem-nos todos.

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

**O `id` e o `criado_at` não entram**, e a razão é a verificação: relê-los
obrigaria a cadeia a depender de valores que a base atribui, e um `id`
reatribuído numa restauração partia a cadeia inteira. O que distingue duas
linhas é o `prev_hash`, que é único por construção.

Uma cadeia por tenant, mais **uma para as acções de plataforma**
(`batch.run`, `breakglass.open`), que não têm tenant. A primeira linha de cada
cadeia parte da génese — trinta e dois zeros, e não `NULL`: com `NULL`, o
`prev_hash NOT NULL` tornava a primeira linha impossível, e a verificação
tinha de tratar o primeiro elo como caso especial.

### 4.1 Porque é que a função não é `SECURITY DEFINER`

O bloco do ticket manda que seja, com entrada em `ci/secdef_allowlist.yaml`.
Essa lista está vazia desde que existe, o `docs/tecnica/08` §3.3 proíbe
`SECURITY DEFINER` «excepto lista aprovada», e as duas revisões anteriores que
criaram funções recusaram-na por escrito.

A necessidade que a justificaria era ler a cabeça anterior e escrever a nova
sem deixar duas transacções bifurcarem a cadeia. Medido: **o PostgreSQL 18
aceita `old.` e `new.` no `RETURNING`**, e com isso uma única instrução dá as
duas pontas:

```sql
INSERT INTO platform.audit_heads AS h (tenant_id, last_hash)
VALUES (p_tenant, platform.audit_row_hash(GENESE, …))
ON CONFLICT (chave) DO UPDATE SET last_hash = platform.audit_row_hash(h.last_hash, …)
RETURNING coalesce(old.last_hash, GENESE), new.last_hash
```

O `ON CONFLICT DO UPDATE` bloqueia a linha da cabeça até ao `COMMIT`, e é isso
que serializa o tenant — sem privilégio elevado. É o mesmo padrão com que o
`evt_emitir` do KAM-005 recusou a `SECURITY DEFINER`.

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

Distingue três achados, porque a resposta operacional é diferente:

| Achado | O que aconteceu |
|---|---|
| **elo partido** | o `prev_hash` de uma linha não é o `row_hash` da anterior — alguém apagou ou inseriu no meio |
| **hash errado** | o `row_hash` não bate com as colunas — alguém alterou uma coluna |
| **cabeça errada** | a cadeia está inteira e a cabeça não aponta para o fim — alguém apagou linhas **do fim** |

O terceiro é o que justifica a tabela de cabeças existir para além do
desempenho: sem ela, apagar as últimas N linhas de uma cadeia deixava-a
**consistente consigo própria**.

A âncora é o último `row_hash` por cadeia, num ficheiro JSON do dia,
**reproduzível a partir da base**: as mesmas linhas dão o mesmo ficheiro, byte
a byte. É isso que a torna útil — duas cópias que divirjam dizem que uma das
bases mudou.

## 7. Quem escreve, quem lê

| Papel | `audit_log` | `audit_heads` |
|---|---|---|
| `kamba_app` | `INSERT` — **e não `SELECT`** | `SELECT`, `INSERT`, `UPDATE (last_hash)` |
| `kamba_batch` | `SELECT`, `INSERT` | idem |
| `kamba_audit` | `SELECT` | **nada** |
| `kamba_migrator` (dono) | tudo, e mesmo assim não altera nem apaga — o *trigger* recusa | idem |

**Quem escreve não lê**, que é o critério 8. E o papel de auditoria não toca na
tabela de cabeças: quem audita recalcula a cadeia a partir do `audit_log`, e
uma cabeça que o auditor leia é um valor em que ele poderia passar a confiar.

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

## 9. Controlo de versões

| Versão | Data | Alteração | Autor |
|---|---|---|---|
| 1.0 | Outubro 2026 | Emissão (KAM-012): a revisão `0006`, a cadeia, o verificador e a âncora. As cinco medições contra o PostgreSQL 18.6 e os quatro desvios que elas obrigaram. | Equipa KAMBÁ |
