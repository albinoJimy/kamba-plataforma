# ANÁLISE-27 — KAM-014: CHR, o sítio onde o `tenant_id` nasce

| Campo | Valor |
|---|---|
| Ticket | KAM-014 — CHR: ChannelResolver por `phone_number_id` com BSUID |
| Âmbito | A revisão `0009`, a emenda 1.20 do dicionário, o módulo `@kamba/core-ts/chr`, a ligação ao braço `chr` do `services/worker-canal/src/entrada.ts`, a *suite* `tests_chr`, o contrato `agent_invocation` e o `docs/chr.md` |
| Método | Revisão adversarial do *diff* (`Skill(code-review, high)`) sobre `main...HEAD`, com leitura do contexto em volta: o algoritmo do KAM-008, o contrato publicado do KAM-007, os privilégios da `0002` e a matriz do KAM-009. A verificação por máquina correu contra um PostgreSQL 18.6 descartável |
| Resultado | 10 achados — 1 crítico, 4 maiores, 5 menores. **7 corrigidos**, 3 declarados |
| Veredicto | **REPROVADO à primeira**: um critério de aceitação não estava cumprido de verdade |

| Aprovação | Nome | Data |
|---|---|---|
| Engenheiro de Canais | | |
| Arquitecto de Plataforma | | |

---

## 1. O achado que justifica o veredicto

**O critério 4 manda a fusão *emitir* `contact.merged`, e o CHR estava a
escrever uma linha de *log*.**

O `resolveContact` do KAM-008 **devolve** o evento e não o emite — «quem emite é
quem chama» (`../identidade.md` §4) —, e quem chama é o CHR. O código escrevia:

```ts
if (resolvido.evento !== null) {
  log.info({ outcome: "contact_merged" });
}
```

Nada chegava ao `events_outbox`. Nenhum consumidor do barramento via a fusão: os
*checkpoints* do AGR (KAM-026) e o espelho do Chatwoot (KAM-019) — os dois que o
`onContactMerge` existe para servir — ficavam presos ao `contact_id` absorvido
para sempre. E a caixa do critério teria sido marcada com a prova de que a
**fusão** acontece uma vez em dez, que é verdade e não é o que o critério pede.

É a classe de defeito que o princípio 2 da skill nomeia: produzir não é
concluir. O teste que havia media o `fundidos.length`, isto é, media o que o
código fazia — não o que o critério exigia.

**O que a correcção obrigou a descobrir.** Emitir não era passar o payload
adiante: o KAM-008 devolve
`{ contact_id: <o que fica>, merged_contact_id: <o absorvido> }` e o contrato
publicado (KAM-007) exige `{ contact_id, merged_into }` — dois nomes diferentes
**e** a leitura invertida, porque `contact_id` ali é o **absorvido**. Passá-lo
tal e qual dava `PayloadInvalidoError`; passá-lo sem validar publicava um campo
que nenhum consumidor conhece. E trocar os dois UUID publicava «B foi fundido em
A» onde aconteceu o contrário, **sem que nenhum esquema o apanhasse** — os dois
são UUID com o mesmo formato. A inversão vive agora numa função própria
(`payloadDaFusao`) com teste próprio, e o `chr/eventos.ts` escreve porquê.

---

## 2. O segundo achado, que o próprio ticket descobriu a provar-se

**O `downgrade` da `0009` contava as conversas como dono de uma tabela com
`FORCE ROW LEVEL SECURITY` — via zero linhas e apagava tudo em silêncio.**

A revisão tem trinta linhas a explicar que reverter perde a janela de 24 h e o
**modo** de cada conversa, e que por isso recusa sem `KAMBA_DOWNGRADE_0009_COPIA`.
O `count(*)` que decide essa recusa corria como `kamba_migrator`, numa migração
**sem** contexto de tenant: com `FORCE`, o dono está sujeito à política e a
contagem dá zero sobre uma tabela cheia. A guarda nunca disparava.

É a mesma armadilha que o `../isolamento.md` §6 já escreve para a validação de
uma FK nova — «a validação passa sem ter olhado para nada» —, aqui a contar em
vez de validar. **Quem a apanhou foi a bateria que o DoD pedia**
(`db/tests/test_conversas_schema.py`): três casos, e o do meio — com conversas e
sem a variável — falhou com `0 == 0`. A correcção é uma linha (a política sai
antes de se contar) e tem mutação própria.

A lição que fica para quem escrever a próxima revisão: **qualquer leitura que
uma migração faça de uma tabela com `FORCE` vê zero linhas.** Contar, validar,
comparar — tudo.

---

## 3. Os restantes achados

| # | Classe | Achado | Estado |
|---|---|---|---|
| A3 | maior | A *suite* `tests` do *gate* 8 estava **vermelha e lida como verde**: a revisão `0009` dá sete colunas com ACL ao `kamba_identity` e o `test_o_downgrade_desfaz_tudo_o_que_a_0003_fez` afirmava 17. O defeito ficou escondido porque a leitura do resultado usou `grep -c` numa cadeia de comandos cujo código de saída era o do `tail` — exactamente a armadilha 1 de «Como correr a verificação aqui» | **corrigido** (24, com a razão escrita) |
| A4 | maior | O *worker* de entrada **deixou de arrancar** na *suite* do KAM-013: o braço `chr` passou a montar o CHR, que exige duas ligações, `KAMBA_FASE` e as chaves do `EnvKeyProvider`. As 34 asserções nunca corriam | **corrigido** (a *suite* passa o ambiente) |
| A5 | maior | A cópia da prova por mutação não levava `packages/contracts`: a ligação de *workspace* do pnpm resolve `../../contracts` **dentro da cópia**, e os sete ficheiros de teste rebentavam com `ERR_MODULE_NOT_FOUND`. Nenhuma das 24 mutações novas se podia provar — «a cópia sem mutação NÃO corre verde» | **corrigido** (`packages/contracts` com `dist`, e `canon/`) |
| A6 | maior | A **composição** das duas FK da conversa não estava afirmada em sítio nenhum: o inventário lista as FK por **nome**, e trocar `FOREIGN KEY (tenant_id, channel_id)` por `FOREIGN KEY (channel_id)` deixava o nome igual e a lista verde. As duas mutações que o fazem eram «apanhadas» por um teste da própria lista de mutações, não pela propriedade | **corrigido** (`TestFkCompostas`, coluna a coluna) |
| m7 | menor | `lerConversa` e `SQL_LER_CONVERSA` eram código morto: exportados, testados e sem chamador. A docstring afirmava servir o caminho `desligado`, que não os chama | **corrigido** (saíram) |
| m8 | menor | Cada entrega ao dono escrevia **duas** linhas de registo, com `outcome` diferentes (`chr_ao_dono` e `chr_entregue_ao_dono`): um painel que conte por `outcome` conta a mesma entrega duas vezes | **corrigido** (quem registra é o CHR) |
| m9 | menor | `ResultadoDoChr.decisao` está documentado como a decisão sobre `processar_entrada`, e no caminho `desligado` carrega a de `registar_entrada`. Hoje coincidem em `permitido`; num regime futuro em que não coincidam, o campo mente | **declarado** (o campo diz agora o que traz, e como distinguir) |
| m10 | menor | Um *job* do AGR em `failed` **bloqueia** a reposição do mesmo `wamid`: o BullMQ recusa um `jobId` que já exista, incluindo em `failed`. O `inbound_events.processado_at` fecha a outra ponta, o que torna o caso difícil de ver quando acontecer | **declarado** (escrito no módulo) |
| m11 | menor | O `worker-canal` **deixa de arrancar em `KAMBA_ENV=prod`**, porque o CHR monta o módulo de identidade e o KAM-008 recusa um `KeyProvider` de ambiente em `prod` enquanto não houver um de cofre — que nenhum ticket constrói. Antes deste ticket o serviço arrancava | **declarado** (é a decisão 2 do KAM-008 a propagar-se) |

---

## 4. O que a revisão **não** encontrou, e procurou

Fica dito porque a ausência de achado só é informação se se souber onde se
procurou:

- **Corridas na *cache*.** O *worker* corre com `concurrency: 1` e um corpo
  explode em eventos tratados em série, pelo que não há dois `comTenant` na
  mesma ligação — que é o erro que o `tenant_guard` lança
  (`LigacaoEmUsoError`). Dois `resolver` do mesmo `phone_number_id` em paralelo
  escrevem a mesma entrada duas vezes, o que é correcto.
- **Crescimento sem tecto do índice inverso da *cache*.** `#porCanal` tem no
  máximo tantas entradas como `#cache`, que tem tecto; e a remoção condicional
  (só apaga se o apontador ainda for para aquela chave) está certa para o caso
  de um canal mudar de `phone_number_id`.
- **Fuga de PII pelos *logs*.** A *allowlist* do KAM-068 recusa `tenant_id`,
  `conversation_id` e `wamid` por **erro de compilação**; não há caminho que os
  escreva. Procurado por leitura de todos os `log.info` e `registar` do *diff*.
- **O `GREATEST` da fusão com nulos.** Em PostgreSQL, `GREATEST` ignora os
  nulos, e a prova de que o `conversations_janela_ck` continua satisfeito é
  aritmética: `max(w) ≥ w_i* > l_i* = max(l)`. Confirmado contra a base no caso
  de colisão.
- **Deadlock no `ON CONFLICT DO UPDATE`.** Linha única, e a concorrência é 1.

---

## 5. Veredicto

**Reprovado à primeira entrega**, por um critério de aceitação que parecia
cumprido e não estava. Depois das sete correcções, e com a verificação por
máquina a correr verde (393 asserções no *gate* 8, 78 no *gate* 6, 34 na entrada
de canal, 913 em Node, 24 mutações novas sem sobreviventes), o veredicto é
**aprovado com três reservas declaradas** — m9, m10 e m11 — e com **três
critérios que não se cumprem à letra** (3, 4 e 6), cujas caixas ficam vazias e
cuja decisão se devolve a quem os escreveu.

A observação que vale para fora deste ticket: **dos dois defeitos mais graves,
um foi encontrado pela revisão e o outro pelo teste que o DoD exigia**. O
segundo não teria aparecido se a caixa «`downgrade` de `conversations` testado»
tivesse sido marcada por memória do trabalho feito — e o `downgrade` tinha sido
escrito, com trinta linhas a explicar a guarda que não funcionava.

---

## 6. Controlo de versões

| Versão | Data | Descrição | Autor |
|---|---|---|---|
| 1.0 | Outubro 2026 | Emissão inicial: dez achados do KAM-014, sete corrigidos e três declarados; os dois graves e o que a revisão procurou e não encontrou. | Equipa KAMBÁ |
