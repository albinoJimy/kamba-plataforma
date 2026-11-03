# ANALISE-48 — KAM-053: o ledger `payment_events`, e as cinco caixas que estavam marcadas em falso

| Campo | Valor |
|---|---|
| Ticket | KAM-053 — Ledger `payment_events` *append-only* (INSERT por função) e unicidade |
| Ramo | `feature/KAM-053-ledger-payment-events` |
| Base | `refs/remotes/publico/main` em `70f9bf7` (depois de integrar o KAM-075) |
| PR | `albinoJimy/kamba-plataforma#104` |
| Método | Revisão adversarial por um subagente `general-purpose` que recebeu **o diff, os requisitos e o conjunto documental**, e **não** o raciocínio de quem escreveu o ramo. Lançada com o ramo já empurrado |
| Achados | 12 levantados — **11 CONFIRMADO por medição**, 1 confirmado por leitura das fontes, **0 PLAUSÍVEL**, **0 MORTO** |
| Gravidade | 3 *must fix*, 6 *should fix*, 3 *nice to have* |
| Veredicto | **REPROVO para fundir.** Os doze estão corrigidos, cada um com ensaio próprio |
| Estado | Vivo |

| Aprovação | Nome | Data |
|---|---|---|
| Fundador | *(por ratificar)* | — |

---

## 1. A medição que importa mais

**O CI estava verde, as 69 asserções da suite nova passavam, e cinco caixas
estavam marcadas sobre ensaios que mediam outra coisa.** É a frase inteira desta
análise, e é o modo de falha que a `software-factory` nomeia como o dominante
desta casa — não escrever a coisa errada, mas declarar-se pronto cedo demais.

O que a torna útil é que **nenhuma das cinco era desleixo**. Cada uma tinha um
ensaio nomeado, escrito de propósito, a correr contra um PostgreSQL real. O
defeito estava no que o ensaio olhava:

| A caixa dizia | O ensaio media | O que faltava |
|---|---|---|
| «não existe caminho de código que escreva `paga` fora de `append_payment_event`» | quatro vias de escrita, todas recusadas | a **quinta**: o `INSERT` da própria cobrança, que podia nascer `paga` |
| «`row_hash = sha256(prev_hash ‖ campos canónicos)`», com um ensaio que varre «cada campo» | cada **posição de argumento** da função do elo | as **nove colunas** que não eram argumento nenhum |
| «a cabeça da cadeia é exportada diariamente via `StorageProvider`» | o *job* contra uma porta **falsa** | que a vista real não tinha `GRANT` para papel nenhum |
| «o `payload` é redigido sem PII» | *(nada — a guarda não existia)* | a guarda do `evt_emitir` não vê o `payload` do ledger |
| «os dois *triggers* são `ENABLE ALWAYS`» | o `tgenabled` **vivo**, no fim da suite | que um ensaio vizinho o escrevia antes de ser lido |

As duas últimas foram apanhadas pela instrumentação do próprio ticket — uma por
um ensaio que falhou a dizer «DatabaseError not raised», outra por uma **mutação
que sobreviveu**. As três primeiras só a revisão independente as viu.

## 2. Os três *must fix*

### 2.1 A quinta via: uma cobrança podia nascer `paga`

`db/migrations/versions/0029_ledger_de_pagamentos.py`, a `payment_charges` contra
o `GRANT SELECT, INSERT … TO kamba_app`.

O `estado` tinha domínio fechado (`CHECK … IN (…)`) e **nenhuma restrição sobre
o valor inicial**. Com `INSERT` concedido — e concedido com razão, porque uma
cobrança nasce num turno de conversa —, um

```sql
INSERT INTO platform.payment_charges (…, estado, …) VALUES (…, 'paga', …)
```

passava com o contexto do próprio tenant e deixava uma cobrança **paga com zero
eventos no ledger**. Qualquer um dos dez estados entrava, incluindo o
`reembolso_pendente` que o ramo declara inalcançável.

**A conflação que o causou, escrita por extenso porque é o que se transfere:**
«ninguém tem `UPDATE` em `payment_charges`» e «não há caminho para escrever
`paga`» não são a mesma afirmação. A primeira estava verdadeira e provada; a
segunda não decorre dela. Quando um estado é *projecção* de outra coisa, o
`INSERT` é tão caminho de escrita como o `UPDATE`.

**E o agravante é a parte mais instrutiva:** o único detector possível era o
*job* de integridade do §8, e ele exclui esta forma **por construção** — compara
a projecção com a reconstrução só para cobranças **com** eventos
(`WHERE EXISTS (SELECT 1 FROM payment_events …)`), e uma cobrança forjada não tem
nenhum. Vale perguntar de qualquer detector: *que forma do defeito é que ele não
vê?*

**Correcção:** *trigger* `payment_charges_nasce_iniciada`, `BEFORE INSERT`,
`ENABLE ALWAYS`. Não um `CHECK` — um `CHECK (estado = 'iniciada')` é avaliado em
toda a versão da linha e impediria a própria projecção de mover o estado, que é
a razão de o ledger existir. Ensaio: `TestAQuintaVia`, com os nove estados
não-iniciais, as duas colunas de resultado que também nasciam preenchíveis, a
sonda positiva, e o caso que mostra que a porta **continua** a mover o estado.

### 2.2 As duas vistas sem `GRANT`, e o *job* a lançar

As vistas `v_payment_events_audit` e `v_payment_ledger_heads` foram criadas com
`security_invoker = true` e **sem `GRANT SELECT` para papel nenhum**. Medido:
`42501 permission denied for view` para o `kamba_app`, o `kamba_batch` e o
`kamba_audit`. Isto é, a âncora externa do §8 — a metade que torna a cadeia uma
prova contra quem tem a base — **falhava na primeira execução real**.

**Porque é que nada o apanhou**, e é um ponto cego desta suite que vale
registar:

* `db/tests/test_inventario.py` e `test_catalogo.py` inspeccionam o catálogo
  **como administrador**;
* `db/tests/test_privilegios.py` **não tem matriz para vistas**, só para tabelas;
* o ensaio do módulo em TypeScript usa uma porta falsa.

**Segunda metade do mesmo achado:** o `verificarLedgerDiariamente` prometia, na
sua própria docstring, «devolve o relatório; **não lança**», e lançava. O
`rebuild_charge_state` levanta `data_corrupted` num ledger que não reproduz — que
é o alarme certo e a razão de ela levantar —, mas isso abortava a consulta
inteira e **deixava a âncora por escrever**, porque ela se escreve depois. O
alarme de uma cadeia apagava a prova de todas as outras.

**Correcção:** `GRANT SELECT` nas duas, com `TestPrivilegiosDasVistas` a lê-las
**como papel** — e com a metade negativa, porque o `kamba_app` não tem razão para
ver a cabeça da cadeia de cobrança nenhuma. E cada leitura do *job* dentro do seu
`try`, com o alerta novo `pay_ledger_leitura_falhou`: *uma leitura que falhou não
é uma verificação que passou.*

### 2.3 Nove das vinte e três colunas fora da cadeia de *hashes*

`CAMPOS_DO_ROW_HASH` tinha catorze entradas. Ficavam fora o `tenant_id`, o
`order_id`, o `billing_cycle_id`, o `motivo`, o `actor_kind`, o `actor_id`, o
`ocorrido_at` e o `recebido_at` — e o `payload`, esse coberto pelo
`payload_hash`.

Medido: desligando o *trigger* de imutabilidade como dono (a única via de
adulteração que existe, a mesma que o ensaio do ramo usa) e alterando qualquer um
desses campos, o `verify_ledger_chain` devolve **zero** elos partidos. O
`actor_id` é a atribuição do acto humano — a «confirmação humana **auditada**» do
§7.1 — e reescrevia-se sem rasto; o `tenant_id` fora do elo significa que um
evento se reatribui silenciosamente a outro tenant.

**Porque é que o ensaio não o via, e é o padrão que se transfere:** o
`test_cada_campo_canonico_muda_o_elo` varria as catorze **posições de argumento**
da `payment_event_row_hash`. Por construção, só os campos que já estavam dentro
do elo. A docstring dizia «varre-se **cada** posição» e a caixa citava-o como «um
campo que não entra no elo é um campo que se pode adulterar» — o ensaio era
tautológico quanto à pergunta que a frase faz.

**Correcção, em duas partes:**

1. o elo cobre **vinte e duas** colunas, e as quatro de fora têm razão escrita no
   `FORA_DO_ROW_HASH`. O ensaio que conta é o
   `test_toda_a_coluna_esta_no_elo_ou_declarada_fora`, que compara a lista com o
   **catálogo** nos dois sentidos — uma coluna nova que ninguém ponha no elo nem
   declare fora dele falha;
2. `TestAFormulaRecalculaEmPython`, que recalcula o `sha256` **fora** do
   PostgreSQL. Sem ele a fórmula era comparada consigo própria: o verificador
   chama a mesma função que a escreveu, pelo que um erro nela é consistente com
   ele mesmo. O ledger de auditoria da `0006` já tinha este ensaio
   (`test_o_row_hash_recalcula_se_em_python`), e eu não o copiei.

Consequências: o `STRICT` saiu da função do elo — com vinte e dois argumentos,
metade anuláveis **por desenho**, ele anulava o elo de todo o evento — e as datas
entram por `platform.payment_instante`, em UTC, porque a saída de `::text` de um
`timestamptz` depende do `TimeZone` e do `DateStyle` da sessão, e um elo que
dependesse da sessão de quem o verifica não é um elo.

## 3. O achado que precisou de três versões

O `webhook_token` enumerável. É *should fix* na gravidade e o mais instrutivo de
todos, porque as duas primeiras tentativas falharam **por razões opostas**.

O problema: o papel `kamba_pay_hooks` tem de resolver `webhook_token → conta`
**antes de existir contexto de tenant** (`docs/tecnica/04` §5.1), numa tabela com
RLS `FORCE`.

| | Desenho | Resultado |
|---|---|---|
| 1.ª | `SECURITY DEFINER` sozinho | **Não funciona.** Corre como o dono (`kamba_migrator`, `NOBYPASSRLS`) e o `FORCE` prende-o: zero linhas. É a lição que o `db/rls.py` escreve e que **nomeia este ticket como credor** |
| 2.ª | `INVOKER` + política `USING (true)` + `GRANT SELECT` com o `webhook_token` | **Funciona e abre um buraco.** Sob `INVOKER`, quem chama precisa de `SELECT` em toda a coluna que a consulta referencia — e `SELECT` nessa coluna **é** a enumeração. Medido: 36 linhas e 36 *tokens* sem contexto de tenant |
| 3.ª | a política carrega o predicado | `USING (webhook_token = NULLIF(current_setting('app.webhook_token', true), ''))`. A expressão de uma política é definida pelo **dono** e os privilégios de coluna conferem-se contra as colunas da **consulta**: o papel compara a coluna do segredo **sem ter `SELECT` nela** |

O comentário da 2.ª versão afirmava, por extenso, que ela era «mais estreita do
que a função que substitui». **Estava errado na dimensão que conta:** mais
estreita em colunas e mais larga em linhas, e o segredo está nas linhas. Uma
função com o predicado dentro devolve no máximo uma linha; uma política
`USING (true)` entrega o predicado todo a quem pergunta.

Para os facilitadores sem assinatura (OPG, EMIS, MoMenu) o *token* é a **única**
credencial do callback (§5), pelo que a enumeração não era um risco teórico.

A 3.ª versão resolve as duas coisas **e** deixa o `ci/secdef_allowlist.yaml` com
uma entrada, que é o que o DoD do bloco pede. O padrão é o do `app.tenant_id` da
`tenant_iso`: uma variável de sessão que o chamador põe e a política lê.

## 4. Os restantes

| # | Classe | Achado | Correcção |
|---|---|---|---|
| 5 | segurança | `p_account_id => NULL` saltava o G2 **em silêncio**: `NULL <> x` avalia a `NULL`, o `IF` não disparava, e o `INSERT` gravava o `account_id` da própria cobrança — pelo que nenhum `NOT NULL` o apanhava depois | `IS NULL OR IS DISTINCT FROM`, com `TestOG2ComContaNula`. O nulo não era hipotético: o recibo `token_desconhecido` do `hooks.ts` grava `accountId: null` |
| 6 | correcção | O `pagamento_orfao` é prescrito pelo §5/F-03 e é **impossível de escrever**: um órfão não tem cobrança, e `payment_events.charge_id` é `NOT NULL` com FK. E o veredicto `divergente` fora de `emitida` fazia a porta reverter a transacção **inteira**, incluindo o facto que a precede | o `escritasDoVeredicto` deixa de prescrever o órfão (o registo passa a ser o recibo `ignorado` e o alerta do §8) e só emite a decisão onde o §7.1 desenha a aresta. Dívida **169** |
| 7 | documental | O §3.42 do dicionário descrevia a `resolve_webhook_token` como `SECURITY DEFINER`, e ela é `INVOKER` — a fonte 4 a contradizer o código, e a sugerir que a lista aprovada estava incompleta | emenda **1.55** |
| 8 | segurança | a enumeração do `webhook_token` — ver §3 | — |
| 9 | segurança | o `hooks.ts` afirmava que o 404 é uniforme **no tempo** e nada no módulo igualava os caminhos; e o `verifyCallback` corria **sem prazo** | corrigiu-se a **afirmação** em vez de se inventar a medição; e um prazo de 300 ms (*proposta*), com a entrega em `erro` e resposta 200 |
| 10 | documental | a célula do §3.4 dizia, no mesmo parágrafo, que o quarto valor de `authn_method` está decidido **e** que fica por decidir — texto novo acrescentado sem retirar o antigo | emenda **1.55** |
| 11 | documental | o `confirmacao_manual_revertida` é recusado em **todo** o produto `(estado × tipo × decisão)` e não estava nomeado; e o código `413` não estava declarado | dívida **166** alargada; o 413 declarado |
| 12 | escopo | o ramo alarga em três entradas o `EM_UNIDADE_MENOR` cuja ratificação é o objecto do PR #102 | **sem colisão de ficheiros**, e o #102 prevê este ramo por escrito. Fica dito que recusar a *allowlist* põe em falso quatro tickets em vez de um |

## 5. A mutação que sobreviveu, e o que ela mostrou

As barreiras da `0029` ganharam **catorze** mutações em `db/mutacoes.py`. Na
primeira execução, oito apanhadas e **uma sobreviveu**: «os *triggers* do ledger
deixam de ser `ALWAYS`» — a revisão passava a criá-los sem o `ALTER`, e a suite
inteira continuava verde.

A causa não era a mutação. Era **um ensaio a escrever o estado que outro ensaio
afirma**: o `TestCadeiaEscritaPelaPorta` tem de desligar o
`payment_events_imutavel` para adulterar um byte, e repunha-o com `ENABLE
ALWAYS` *fixo*; o `TestTriggersSaoAlways`, que corre depois no mesmo ficheiro,
lia um `A` escrito por esse vizinho.

Medido numa cópia da árvore, com a mutação aplicada: a suite deu código de saída
**0**, e um diagnóstico impresso no próprio ensaio mostrou
`[('payment_events_imutavel', 'A'), ('payment_events_sem_truncate', 'A')]` numa
base onde o `ALTER` nunca correu.

**Duas regras saem disto:**

* um ensaio que altera estado partilhado repõe **o que estava** — lê o valor
  antes e repõe esse —, e não «o que devia estar»;
* uma afirmação sobre o que a **migração** escreve mede-se onde nenhum vizinho
  lhe chega: numa classe que reaplica a revisão ela própria
  (`TestDowngradeDa0029`).

E a razão de as mutações existirem, dita de uma vez: os ensaios estavam verdes,
o `ENABLE ALWAYS` estava no diff, e a leitura do código não distinguia este caso
do caso bom. O que o distinguiu foi **tirar a barreira e exigir que alguém desse
por isso**. Hoje as catorze são apanhadas.

## 6. Classes que a revisão procurou e não encontrou

Registam-se porque uma revisão que não diz o que procurou não distingue «limpo»
de «não olhou»:

concorrência (o passo de canário do `test_concorrencia.py` foi lido como genuíno
e a tranca na cobrança como suficiente — nenhum *interleaving* com duas
sequências iguais, nenhum `prev_hash` repetido, nenhum caminho de *deadlock*);
injecção e `search_path` nas sete funções; o `DEFINER` contra o `FORCE` (a
afirmação do `db/rls.py` é verdadeira **neste** código, e o `TestADefinerSobRls`
mede-a); `ALTER DEFAULT PRIVILEGES` (não existe no repositório); políticas
permissivas a somar por OU; vistas actualizáveis como porta de escrita; o
`downgrade`; a máquina de estados aresta a aresta (quinze implementadas, nenhuma
a mais, a que falta declarada); o *outbox* na mesma transacção; a guarda de PII;
a idempotência G7; e a substituição declarada do `kamba_ops`, lida como honesta.

## 7. Portão: o que isto devia virar

Pela regra da `software-factory` — «um escape que um portão podia ter apanhado
vira portão» —, três destes são candidatos. Nenhum se abre neste ticket, porque
**entrar num gate existente é alteração de regra de bloqueio**:

1. **Matriz de privilégios para vistas** em `db/tests/test_privilegios.py`, do
   mesmo tipo que a das tabelas. Fecharia o §2.2 por construção para toda a vista
   futura, e não só para as duas deste ticket.
2. **Um teste de catálogo que exija, de toda a tabela com uma coluna de *hash* de
   encadeamento, que a lista de campos do elo cubra as colunas da tabela.** Hoje
   isso é um ensaio por ticket; devia ser um X-NN do *gate* 6.
3. **Um `CHECK` do `--aplicaveis` que exija pelo menos uma mutação por barreira
   nova de uma revisão.** É o que teria obrigado as catorze a existir antes de o
   PR abrir, em vez de depois da revisão.

Os três ficam escritos aqui e não implementados. O primeiro é o mais barato e o
que fecha o achado mais embaraçoso.

## 8. Calibração desta revisão

| Indicador | Valor |
|---|---|
| Achados levantados | 12 |
| CONFIRMADO | 12 (11 por medição própria, 1 por leitura das três fontes) |
| PLAUSÍVEL | 0 |
| MORTO | 0 |
| Calibração (confirmados / levantados) | **12/12** |

Uma calibração de 12/12 é notável e merece a ressalva: a revisão correu sondas
contra um PostgreSQL próprio em vez de inferir, e **recusou promover** o que não
conseguiu medir — o único achado não medido por sonda (o §3.42 contra o código)
é verificável por leitura das fontes e está marcado como tal. É o contrário do
modo de falha que a `software-factory` avisa («um revisor instruído a encontrar
problemas encontra problemas, haja-os ou não»), e a diferença parece estar em
duas coisas do contrato: o guião mandou **medir antes de reportar**, e mandou
dizer o que procurou e **não** encontrou.
