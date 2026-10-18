# ANÁLISE-26 — KAM-012: `audit_log` *append-only* e cadeia de hash por tenant

| Campo | Valor |
|---|---|
| Ticket | KAM-012 — `audit_log` *append-only* para dinheiro, stock e preço |
| Âmbito | A revisão `0006`, a emenda 1.14 do dicionário, o `db/auditoria.py`, as três baterias (`test_auditoria`, `test_auditoria_verificador`, `tests_auditoria_carga`), o papel `kamba_audit`, e o `docs/auditoria.md` |
| Método | Revisão adversarial **independente**: um subagente recebeu os requisitos e o código, e **nunca as justificações de quem o escreveu**. Correu contra um PostgreSQL 18.6 descartável, próprio |
| Resultado | 20 achados — 2 críticos, 10 maiores, 8 menores. **17 corrigidos**, 3 registados |
| Veredicto do revisor | **REPROVADO** |

| Aprovação | Nome | Data |
|---|---|---|
| Responsável de Segurança | | |
| Arquitecto de Plataforma | | |

---

## 1. O achado que justifica o veredicto

**O papel da aplicação forjava uma linha de auditoria válida, encadeada, com a
data à escolha — e o verificador respondia «cadeia intacta».**

O `kamba_app` tinha `INSERT` de tabela inteira em `audit_log` (incluindo
`criado_at`) e `SELECT` + `UPDATE (last_hash)` em `audit_heads`. Com isso lia a
cabeça, escrevia uma linha correctamente encadeada, avançava a cabeça, e saía
do outro lado indistinguível de uma escrita legítima. O revisor executou-o: uma
linha `payment.manual_confirm` por `actor_id='FORJADO'`, datada de 2020-01-01,
seis anos antes da anterior. É exactamente a classe de evento — dinheiro — para
que a tabela existe.

## 2. A causa, que é um erro de raciocínio e não de código

A revisão `0006` pôs a cadeia dentro de `audit_append`, com
`SECURITY INVOKER`, e justificou-o com uma medição real: o PostgreSQL 18 aceita
`old.` e `new.` no `RETURNING` de um `ON CONFLICT DO UPDATE`, e com isso uma só
instrução serializa o tenant sem privilégio elevado. A conclusão foi que a
`SECURITY DEFINER` não era precisa e que `ci/secdef_allowlist.yaml` continuava
vazia.

**A medição estava certa e a conclusão não.** Serializar é uma propriedade; ser
o **escritor exclusivo** é outra. Com `SECURITY INVOKER`, para a função
funcionar o chamador tem de ter os privilégios em bruto — e quem os tem pode
dispensar a função. Eram duas propriedades e foram tratadas como uma, porque a
primeira foi medida e a segunda nunca chegou a ser perguntada.

O revisor diz melhor do que eu: «a decisão de recusar `SECURITY DEFINER` é
defensável em si, mas retirou a única razão pela qual a função podia ser o
escritor exclusivo».

## 3. O desenho que fechou o C1

A cadeia passou para um ***trigger* `BEFORE INSERT`** que recalcula
`criado_at`, `prev_hash` e `row_hash` e **ignora** o que o chamador enviar
nessas três colunas. Com isso:

- o `INSERT` do `kamba_app` é **por coluna**, sem as três;
- nenhum papel de aplicação escreve em `audit_heads`;
- escrever directamente na tabela deixa de ser um ataque — dá o mesmo
  resultado —, e é por isso que o `audit_append` pode continuar `INVOKER`: já
  não guarda propriedade nenhuma.

A função do *trigger* é que é `SECURITY DEFINER`, e é a **primeira entrada** de
`ci/secdef_allowlist.yaml`. A excepção é estreita e diz-se numa frase: ela não
escreve a linha de auditoria, escreve **a cabeça da cadeia**, que é precisamente
o que quem escreve a linha não pode poder fazer.

O preço foi `audit_heads` deixar de ter RLS — o *trigger* corre como o dono, e
com `FORCE` o dono também está sujeito à política, o que tornava a cadeia de
plataforma impossível de registar. É a **primeira entrada** de
`ci/rls_exceptions.yaml`, com o ADR que a funda. A tabela guarda uma linha por
cadeia, com um hash opaco.

## 4. Os outros dezanove, em grupos

### O que estava errado na cadeia

| # | Achado | Disposição |
|---|---|---|
| M5 | **O `criado_at` estava fora do `row_hash`.** Apagar a última linha e reinseri-la com o mesmo conteúdo e outra data deixava a cadeia «intacta». A sequência era à prova de adulteração e a **cronologia** não era de todo | corrigido: entra no hash, em ISO 8601 UTC |
| M4 | **Uma cadeia apagada inteira não produzia achado nenhum.** O verificador percorre o que existe, e o que deixou de existir não está em lado nenhum para ser percorrido | corrigido: `verificar --ancora` compara com a âncora de um dia anterior |
| — | **A ordem do `id` não é a ordem da cadeia.** Não veio do relatório: apareceu quando a *suite* de carga passou a correr contra o desenho novo. O `id` sai da sequência quando a instrução começa e o lugar na cadeia decide-se depois, no *trigger* — com mil inserções concorrentes as duas divergem | corrigido: o verificador segue o `prev_hash` |

### O que estava errado nos privilégios

| # | Achado | Disposição |
|---|---|---|
| M7 | **O `UNIQUE (row_hash)` era um oráculo que atravessa a RLS.** Um índice único é global: quem tem `INSERT` e não tem `SELECT` confirmava palpites sobre linhas que não pode ler, incluindo as da cadeia de plataforma, cuja génese é constante conhecida | corrigido: `UNIQUE (tenant_id, row_hash)` |
| M7 | **As funções nasciam com `EXECUTE` para `PUBLIC`** — omissão do PostgreSQL —, pelo que o `kamba_resolver` as podia chamar e os `GRANT` nominais eram decorativos | corrigido: `REVOKE ALL ... FROM PUBLIC` nas quatro |
| C2 | **O critério 9 não está cumprido nem é cumprível** com os privilégios entregues: nada escreve `audit.read`, e o `kamba_audit` não a pode escrever | **registado**; a caixa fica vazia e o pendente está em `docs/auditoria.md` §8 |
| m2 | **O `kamba_audit` não lia a cabeça**, e verificar a cadeia exige-a — as duas decisões eram incompatíveis, e o `--papel` prometido no *docstring* não existia no `argparse` | corrigido |

### O que estava errado nos testes

| # | Achado | Disposição |
|---|---|---|
| M1 | **A limpeza reparava o esquema.** Cinco auxiliares corriam `ENABLE ALWAYS TRIGGER` e confirmavam — DDL confirmado, que repõe a propriedade **permanentemente** na base viva e esconde regressões de tudo o que corre depois | corrigido: lêem o estado e repõem o que leram |
| C2 | **`assertGreaterEqual(count, 0)`** — sempre verdadeiro, e passava exactamente com as zero linhas que o papel via na realidade | corrigido |
| Crit. 1 | **O teste do dono usava o superutilizador**, não o dono. Como dono real, o `UPDATE` e o `DELETE` devolvem zero linhas sem erro — a RLS esconde-as e um *trigger* `FOR EACH ROW` sobre zero linhas não dispara | corrigido |
| Crit. 7 | **Satisfeito pela coluna errada:** provava-se que `payload_hash` é `bytea(32)`, e o `entity_id` era `text` sem limite | corrigido: tecto de 256 nas quatro colunas de texto |

### O que ficou dito e não feito

| # | O quê | Onde |
|---|---|---|
| M9 | O **p95 ≤ 5 ms** do critério 8 não foi medido — e o `docs/auditoria.md` §8, que se apresenta como o inventário do que falta, **não o incluía** | `docs/auditoria.md` §8, linha 9 |
| C2 | O registo da própria leitura (`audit.read`) | `docs/auditoria.md` §8, linha 10 |
| M6 | O `audit_append` **exige `READ COMMITTED`**: sob `REPEATABLE READ` duas escritas concorrentes dão `40001` e a segunda perde-se | dito no `COMMENT` da função e em `docs/auditoria.md` §4.1 |

## 5. O que a revisão confirmou

- O `RETURNING old./new.` **serializa de facto**, incluindo o caso difícil:
  duas transacções a inserir a **primeira** linha da mesma cadeia dão duas
  linhas com `prev_hash` distintos.
- O `ENABLE ALWAYS` **resiste** ao `session_replication_role`; o revisor
  reproduziu a medição de raiz.
- A chave gerada `coalesce(tenant_id, zero)` resolve o problema que diz
  resolver, e a cadeia de plataforma isola-se: o `kamba_app` não a escreve nem
  vê que existe.
- O verificador apanha as formas que declara, incluindo apagar **do fim**, que
  só a cabeça apanha.
- Nenhuma coluna guarda texto de conversa, e o `downgrade` tem o guarda da
  cópia lógica.
- A correcção ao `_copiar` é real: a linha de base das mutações da *suite*
  `tests` estava de facto vermelha desde o KAM-158.

## 6. A anomalia que eu não resolvi, e que o revisor resolveu

Entreguei com uma nota escrita no próprio teste: a mutação que tira o
`ENABLE ALWAYS` era apanhada só por um teste de contabilidade, a medição
directa dizia que a propriedade mudava, e dentro da *suite* não mudava. Escrevi
«está medida e não está presa» e não apurei porquê.

**A resposta é o M1, e aponta para o lado contrário do que eu tinha escrito.**
Os dois testes prendem a propriedade — o revisor correu-os isolados contra a
revisão mutada e falham os dois. O que a desprendia era a **limpeza**: o
primeiro teste da classe, por ordem alfabética, corria `ENABLE ALWAYS TRIGGER`
no seu `addCleanup` e confirmava, e quando os testes que medem a propriedade
corriam, o *trigger* já tinha voltado a `'A'`.

A lição não é sobre *triggers*: **uma limpeza que corre DDL confirmado não
limpa, repara** — e repara na base viva, para todos os testes seguintes, para
sempre.

## 7. O que fica em aberto

| # | O quê | Onde |
|---|---|---|
| 1 | O p95 do critério 8 | `docs/auditoria.md` §8, linha 9; caixa vazia |
| 2 | O registo da própria leitura (`audit.read`) | `docs/auditoria.md` §8, linha 10; caixa vazia |
| 3 | O *job* nocturno e o encaminhamento do alerta Sev1 | KAM-078 |
| 4 | A âncora fora do *host* | KAM-079 |
| 5 | Nada chama `audit_append` em produção | KAM-028 e KAM-054 |
| 6 | A emenda 1.14 pôs nomes genéricos no canon (`chave`, `action`, `entity`), e o domínio de `action` fica preso a qualquer futura coluna com esse nome | `docs/dividas-documentais.md` |

## 8. Controlo de versões

| Versão | Data | Alteração | Autor |
|---|---|---|---|
| 1.0 | Outubro 2026 | Emissão. Revisão adversarial do KAM-012: 20 achados, 17 corrigidos, 3 registados. Veredicto REPROVADO, pelo C1. | Equipa KAMBÁ |
