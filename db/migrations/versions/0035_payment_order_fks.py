"""FK de order_id para orders_mirror, o mapa do outbox e o evento por encomenda (KAM-055).

A primeira linha e **sem acentos**, como as trinta e quatro revisoes anteriores:
e a mensagem que o `alembic history` imprime, e o
`test_no_processo_e_pela_linha_de_comandos_o_alembic_diz_o_mesmo` compara a
saida no processo com a do executavel. Com acentos, as duas divergem na
codificacao.

## O que esta revisao faz, e porque sao tres coisas e nao uma

O criterio 8 do KAM-055 pede **uma** coisa — as FK de `order_id` para a
`orders_mirror`, reversiveis. As outras duas estao aqui porque sem elas o
criterio 2 do mesmo bloco nao se consegue cumprir, e isso mede-se:

1. **As FK.** A `0029` deixou `payment_charges.order_id` e
   `payment_events.order_id` sem FK, com a razao escrita e este ticket nomeado;
   a `0032` fez o mesmo a `refund_cases.order_id`, e escreveu porque: «por a FK
   so num dos dois lados deixava o par incoerente».
2. **O conteudo da `payment_outbox_map`**, que a `0029` criou **vazia** e
   nomeou este ticket como credor: «o conteudo definitivo e do KAM-055, e um
   tipo sem mapeamento nao produz evento de dominio».
3. **O passo (7) da `append_payment_event`**, que passa a emitir o evento de
   dominio agregado pela **encomenda** e com o `payload` do contrato publicado.

## Porque o passo (7) tinha de mudar, e nao e preferencia

Encher o mapa sozinho emitia um envelope que **viola o contrato que o proprio
ticket entrega**. Medido nos ficheiros, nao suposto:

* `contratos/eventos/payment.confirmed/v1.schema.json` declara `agregado.tipo`
  com `const: "order"` — e os cinco `payment.*` e o `order.paid` declaram o
  mesmo. O passo (7) da `0029` chamava o `evt_emitir` com `'payment_charge'` e
  o `p_charge_id`.
* O `payload` do contrato e fechado (`additionalProperties: false`) e exige
  `order_id`; o do passo (7) da `0029` era uma projeccao da cobranca com
  `charge_id`, `tipo_evento`, `sequencia`, `estado` e `decisao` — **nenhum** dos
  quais o contrato aceita, e sem o campo que ele exige.

E as duas metades batiam no consumidor, nao so no `lint`: o `ESTADO_PRETENDIDO`
de `packages/core-ts/src/eventos/estados.ts` mapeia os dois eventos de pagamento
para `paga`, e a `MaquinaNaBase` devolve `null` para um agregado que nao seja
`order`. Um `payment.confirmed` agregado pela cobranca **adiava sempre** e
acabava na DLQ por tentativas esgotadas — isto e, o criterio 3 e o criterio 4
eram inalcancaveis com o produtor como estava.

Nao ha transformacao entre o `events_outbox` e o consumidor: o publicador do
KAM-005 entrega o envelope como ele esta. O que a porta escreve e o que o
consumidor le.

## O corpo da porta escreve-se **uma vez**, e o passo (7) e o argumento

A `append_payment_event` tem cerca de duzentas linhas de SQL e o PostgreSQL nao
substitui funcoes por partes: um `CREATE OR REPLACE` leva o corpo inteiro, e um
`downgrade` reversivel leva-o **outra vez**. Escrever as duas versoes por
extenso punha quatrocentas linhas no ficheiro das quais uma duzia difere, e
pedia a quem revisse que as diferenciasse a olho — que e exactamente o modo de
falha que esta casa nomeia.

Por isso o corpo esta no `_porta(passo_sete, coda)`, e o que esta escrito duas
vezes sao os dois fragmentos do passo (7) — o novo e o da `0029` — mais a frase
que o `COMMENT` leva a mais. A propriedade que isto da e util e nao cosmetica —
as duas versoes da funcao sao **identicas por construcao** em tudo o que nao e o
passo (7), e nenhuma edicao futura pode desviar uma da outra por descuido.

**O `COMMENT` e o segundo argumento por uma razao medida, e nao por simetria.**
A primeira versao deste ficheiro emitia-o sempre igual, com a frase do KAM-055
no fim — tambem quando era o `downgrade` a chamar o `_porta`. Isto e: depois de
`alembic downgrade 0034`, o corpo voltava a agregar pela cobranca e o catalogo
continuava a afirmar que agrega pela encomenda. Nao havia como ver: o
`pg_get_functiondef` nao traz o `COMMENT`, e o ciclo `upgrade -> downgrade ->
upgrade` passava porque o `upgrade` seguinte reescrevia a frase certa. E a
mesma classe que esta suite diz estar a fechar — medir o `downgrade` **por
objecto** — a faltar um objecto: o `obj_description`, que o
`test_o_downgrade_repoe_o_comentario_da_0029` passou a afirmar.

O resto do corpo e copia literal da `0029` (`_append()`, linhas 1299-1522), e e
a suite de pagamentos inteira que o prende: mais de cem ensaios chamam esta
funcao por todos os caminhos do §7.1, mais a cadeia de *hashes* e a
`rebuild_charge_state`. Uma copia errada nao passa calada.

## As FK sao **compostas**, e isso nao e enfeite

`(tenant_id, order_id) -> orders_mirror (tenant_id, id)`, contra a
`orders_mirror_tenant_id_uq`, que a `0030` criou para este fim. E a forma que a
`0033` usou para a reserva de stock
(`stock_reservations_encomenda_do_mesmo_tenant_fk`) e que a `0030` usou para o
registo de estado, e a razao e a mesma: uma FK so sobre `order_id` deixava a
cobranca do tenant A apontar para a encomenda do tenant B, e e a RLS que fica a
valer sozinha num sitio onde a integridade referencial podia valer tambem.

**`MATCH SIMPLE`, que e a omissao, e e o que faz a coluna anulavel continuar a
servir.** Com uma coluna nula no par, a restricao esta satisfeita: uma cobranca
de ciclo de billing (`order_id IS NULL`, que o `payment_charges_um_sujeito`
impoe ser exactamente um dos dois) passa sem FK a avaliar. Com `MATCH FULL` a
mesma linha era recusada, e a facturacao da propria KAMBA do §11.2 ficava sem
caminho de escrita.

**Nao sao `DEFERRABLE`**, e isso e uma lista fechada e nao uma preferencia: o
`test_a_fk_do_dono_e_a_unica_diferida` de `db/tests/test_inventario.py` afirma
que a `tenants_owner_fk` e a **unica** FK diferida do esquema. `NO ACTION` nos
dois sentidos, pela mesma razao: o `test_as_fk_nao_apagam_em_cascata` exige
`confdeltype` e `confupdtype` a `'a'` em **todas**.

## O preco que a FK cobra, e quem o paga

Uma FK de `payment_events` para a `orders_mirror` torna uma encomenda com
eventos no ledger **impossivel de apagar** — porque o ledger e *append-only* e
o `payment_events_imutavel` recusa o `DELETE` ao administrador tambem. Em
producao e o que se quer: uma encomenda nao se apaga, marca-se (`deleted_at`).
Nas suites obriga a limpeza a apagar so o que nao esta referenciado, que e
**exactamente** o que a suite de encomendas ja faz desde o KAM-044, com a razao
escrita: «o `order_state_log` **nao** se apaga, pelo que as encomendas que
transitaram ficam — e com elas o tenant, cuja FK as recusa apagar. Nao acumula
lixo que conte: a base e descartavel e cada teste tem o seu tenant.» A limpeza
de `db/tests_pagamentos/base.py` passa a seguir a mesma forma.

E obriga a semente a escrever uma encomenda: o `criar_cobranca` daquela suite
punha um `order_id` aleatorio sem linha na `orders_mirror`, o que com a FK e um
`23503`. Passa a semear a encomenda, que e o que producao tem.

## A guarda do `payload`, e porque ela e a barreira do criterio 2

O criterio 2 acaba com «nunca existe um emitido sem o `authn_ok=true`
correspondente no ledger». Isso pode ser uma convencao de quem escreve o mapa ou
pode ser uma barreira; aqui e uma barreira, e vive na `payment_evt_payload`:
para `payment.confirmed` e `payment.manual_confirmed` ela **levanta** se o
`authn_ok` nao for verdadeiro, e levanta tambem se lhe pedirem um `evt_tipo`
para o qual nao sabe construir o `payload` do contrato. Um mapa que aponte para
um evento desconhecido nao emite um envelope mal formado: recusa.

A funcao e `SECURITY INVOKER` (a omissao) e nao toca tabela nenhuma, pelo que
nao entra no `ci/secdef_allowlist.yaml` nem no X-05 do *gate* 6. E **`STABLE` e
nao `IMMUTABLE`**: converte um `timestamptz` para texto no `expira_at`, e isso
depende do `TimeZone` da sessao — uma funcao marcada imutavel que nao o e deixa
o planeador dobrar constantes com o fuso errado.

**A `referencia` do evento e a do ledger, com o mesmo `coalesce`.** Um
`express_push` nao tem referencia (a coluna e anulavel) e tres dos cinco
contratos exigem o campo; a `0029` ja resolve isto para dentro do ledger, com
`coalesce(referencia, id || '#' || tentativa)`, e o evento usa **a mesma**
expressao. A alternativa — levantar — tornava uma confirmacao legitima de OPG
impossivel de registar, o que e pior do que um campo que diz a identidade da
cobranca em vez de uma referencia Multicaixa. Fica dito aqui e no comentario da
funcao.

**O `motivo` do `payment.failed` levanta se for nulo**, e nao se inventa um
valor por omissao. O contrato exige o campo e um `pagamento_divergente` traz
sempre um: um evento de falha sem razao nao e publicavel, e um texto de
enchimento no lugar dela era pior do que a recusa — ia para o HND dizer
«falhou» sem dizer o que.

**E o vocabulario do motivo e o do DDL e nao o da prosa**, o que se mede. O
§5 escreve a forma curta (`motivo='valor'`, `'entidade'`, `'referencia'`) e os
nove `MOTIVOS_DE_FALHA` da `0029` — que o `payment_charges_motivo_falha_ck`
fecha — usam a forma longa (`valor_divergente`, `entidade_divergente`,
`referencia_divergente`). O `p_motivo` viaja para aquela coluna no passo (6b),
pelo que a forma curta da `23514`; apanhou-se assim, e nao por leitura. Os dois
documentos nao escrevem o mesmo, e quem manda na coluna e o DDL.

**E isto muda o que a porta aceita, o que se declara em vez de se esconder.**
Antes desta revisao, `append_payment_event('pagamento_divergente', …,
p_motivo => NULL)` escrevia a linha; agora recusa com `check_violation`.
Nenhum criterio do KAM-055 pede esta mudanca — ela e a consequencia de o
`pagamento_divergente` passar a ter mapeamento para um contrato que exige o
campo, e as tres alternativas eram piores: inventar um motivo (dados falsos no
ledger), nao emitir (perder um sinal Sev1 que o §6.4 manda levar ao HND), ou
emitir um envelope que o esquema do `payment.failed` rejeita.

**Nao ha hoje produtor nenhum a quebrar, e isso e uma ressalva e nao um
argumento.** O §5.1 descreve o *worker* que traria o motivo; medido, o unico
sitio do repositorio com esta chamada e a constante
`SQL_APPEND_PAYMENT_EVENT` do `packages/core-ts/src/pagamentos/hooks.ts`, que
nenhum servico usa. Isto e: a obrigacao de passar `motivo` fica registada na
barreira (que e o sitio certo) e nesta prosa, e quem escrever o *worker*
encontra-a como `23514` em ensaio e nao como decisao escrita. Credor da
ligacao: **KAM-071**, dono do §5.1.

**Um ensaio existente escrevia-o nulo** — o gerador das mil sequencias do
`db/tests_pagamentos/test_maquina.py` — e passou a trazer `'valor_divergente'`,
com a razao escrita na chamada. **A forma longa e nao a curta**: e a que o
`payment_charges_motivo_falha_ck` fecha, pela divergencia de vocabulario que o
paragrafo acima declara.

## A ordem dos quatro passos, e o que o `ADD CONSTRAINT` valida

`_fks()` -> `_payload()` -> `_porta()` -> `_mapa()`, e dois pontos importam:

* **o mapa e o ultimo.** Com o mapa cheio e a porta antiga, qualquer
  `pagamento_confirmado` que caisse entre os dois `op.execute` emitia um
  envelope agregado pela cobranca — isto e, esta ordem e a diferenca entre
  nunca publicar um envelope invalido e publicar os que caibam na janela;
* **o `ADD CONSTRAINT` valida as linhas que ja existem**, e e isso que se
  quer: numa base com uma cobranca cujo `order_id` nao esteja na
  `orders_mirror`, esta revisao **falha** em vez de aceitar a incoerencia.
  Pela medicao que o KAM-175 fez e deixou escrita, nao existe ambiente onde
  isso possa acontecer — o *gate* 8 cria e destroi a sua base, nenhum alvo do
  `Makefile` nem *script* de `initdb` corre `alembic` contra a base do
  `../infra/compose/` (a rede e interna e nao publica portas), e os
  `../infra/envs/{staging,prod}` apontam para `provider-pendente` sem `tfstate`.
  Quem aplicar isto a uma base com dados le esta nota primeiro.

## O que esta revisao **nao** faz

* **Nao cria tabela nenhuma**, pelo que nao ha `TABELAS_0035` em
  `db/tests/base.py` nem elo `TABELAS_ATE_0034`: o precedente e a `0031`, que
  alarga um *trigger* e nao tem tupla nem elo proprios.
* **Nao acrescenta coluna de dinheiro** a `platform`, pelo que o
  `EM_UNIDADE_MENOR` de `db/tests/test_catalogo.py` nao se mexe — a
  `payment_charges` e a `payment_events` chegaram com o KAM-053 e as entradas
  delas estao escritas (ADR-L008, KAM-172).
* **Nao toca na RLS nem nos privilegios.** O mapa e configuracao global sem
  `tenant_id`, e a matriz de `db/tests/test_privilegios.py` ja o declara com
  `kamba_app={SELECT}` e `kamba_batch={SELECT, INSERT, DELETE}`, com a nota a
  dizer que se declara igual estando vazia. Encher a tabela nao muda quem a le.
* **Nao implementa o pagamento tardio** (`expirada -> paga`): e o KAM-050. A
  aresta existe no `next_state` desde a `0029` e no §6.1; o que este ticket faz
  e recusa-la no consumidor com `estado_incompativel`, e isso e TypeScript e
  nao SQL.
"""

from __future__ import annotations

from alembic import op

#: Literais e nao f-strings sobre outras constantes, pela razao da `0034`: o
#: *gate* 3b le o AST da revisao sem a executar e resolve `f"..."` sobre
#: constantes de modulo, mas nao sobre constantes que sejam elas proprias
#: f-strings.
COBRANCAS = "platform.payment_charges"
EVENTOS = "platform.payment_events"
REEMBOLSOS = "platform.refund_cases"
ENCOMENDAS = "platform.orders_mirror"
MAPA = "platform.payment_outbox_map"

revision = "0035"
#: **Encaixa na `0034`, e confirmou-se na integracao.**
#:
#: A cabeca da cadeia era a `0034` (KAM-091) no dia desta revisao, medido com
#: `git ls-tree --name-only refs/remotes/publico/main db/migrations/versions/`,
#: e nenhum outro ticket a correr pedia migracao. Renumerar **na integracao** e
#: nao antes e a regra da casa: um ramo verde nao reserva um numero para outro,
#: e deixar a `down_revision` numa revisao que outra ja ocupa da **duas
#: cabecas**, que o `test_ha_uma_so_cabeca` de `db/tests/test_migracao.py`
#: recusa.
down_revision = "0034"
branch_labels = None
depends_on = None

#: O `prev_hash` da primeira linha de uma cadeia. Copia da `0029`, porque o
#: corpo da porta o cita e o corpo e o mesmo.
GENESE = "\\x0000000000000000000000000000000000000000000000000000000000000000"

#: A assinatura da porta, para o `COMMENT`. Copia da `0029`: um
#: `CREATE OR REPLACE` que mudasse a assinatura criava uma **segunda** funcao em
#: vez de substituir a primeira, e as duas ficavam no catalogo.
ARGUMENTOS_DE_APPEND = (
    "uuid, text, uuid, bigint, text, boolean, text, text, text, uuid, text, "
    "jsonb, timestamptz"
)

#: A assinatura da funcao do `payload`, para o `COMMENT`, o `REVOKE` e o `DROP`.
ARGUMENTOS_DO_PAYLOAD = (
    "text, uuid, text, text, bigint, text, text, boolean, text, text, "
    "timestamptz"
)

#: As tres FK que esta revisao acrescenta: `(tabela, restricao)`.
#:
#: As duas primeiras sao o criterio 8. A terceira — a `refund_cases` — **nao
#: esta no criterio**, e esta aqui porque o repositorio nomeia este ticket como
#: credor dela em quatro sitios independentes (a nota da `0032`, o comentario da
#: `0029`, o `test_as_fk_nao_apagam_em_cascata` e o
#: `test_nao_ha_fk_para_fora_de_platform`), todos com a mesma razao escrita: por
#: a FK de `order_id` so num dos lados deixava o par incoerente. Fica declarada
#: como alteracao fora dos criterios no corpo do PR.
FK_DAS_COBRANCAS = "payment_charges_encomenda_do_mesmo_tenant_fk"
FK_DOS_EVENTOS = "payment_events_encomenda_do_mesmo_tenant_fk"
FK_DOS_REEMBOLSOS = "refund_cases_encomenda_do_mesmo_tenant_fk"

#: As tres, para quem as queira ler em conjunto. **O `upgrade` e o `downgrade`
#: nao iteram isto**, e a razao e medida: o *gate* 3b le o AST da revisao sem a
#: executar, e um `op.execute` cujo SQL depende de uma variavel de laco
#: («`tabela` e atribuido mais de uma vez») sai como `[ilegivel]`. Deu dois
#: achados na primeira versao deste ficheiro. As instrucoes vao por extenso.
FKS = (
    (COBRANCAS, FK_DAS_COBRANCAS),
    (EVENTOS, FK_DOS_EVENTOS),
    (REEMBOLSOS, FK_DOS_REEMBOLSOS),
)

#: **Uma ressalva do passo (7), registada como divida 200.** O passo tira da
#: cobranca o `tenant_id`, o `provider`, a `referencia` e a `currency` — o que o
#: passo (5) chama «da cobranca e nao do chamador» —, mas o `valor_minor` do
#: `payload` vem do `p_valor_minor`, que a porta so confronta com o
#: `amount_minor` no passo (3b) e **so para `pagamento_confirmado`**. Um
#: `referencia_emitida` com o valor errado publica um `payment.reference_issued`
#: que discorda da cobranca, e o contrato aceita-o. Fechar isso e uma decisao
#: (confrontar nos sete pares, ou tirar o valor da cobranca como os outros
#: quatro campos) e nao uma emenda: credor **KAM-071**, dono do §5.1.

#: A frase que o `COMMENT` da porta leva **a mais** desde esta revisao.
#:
#: Literais, como os dois fragmentos do passo (7) e pela mesma razao: o texto
#: comum do `COMMENT` escreve-se **uma vez** no `_porta`, pelo que a descricao
#: que fica numa base em `0034` e identica a da `0029` **por construcao** — e
#: nao por alguem ter copiado a frase certa para o `downgrade`.
CODA_DO_0035 = (
    " O passo (7) agrega por encomenda e usa o payload do contrato desde o "
    "KAM-055."
)

#: E a da `0029` e vazia: o comentario dela acaba em `(FORCE).`, medido no
#: `_append()` daquela revisao.
CODA_DA_0029 = ""

#: O conteudo da `payment_outbox_map`: `(tipo_evento, authn_method)` -> evento
#: de dominio, na versao **1**.
#:
#: Sete linhas, e a escolha de cada uma esta escrita abaixo. Os nomes da
#: esquerda sao tres dos dezassete `TIPOS_DE_EVENTO` da `0029` e tres dos quatro
#: valores de `authn_method` do dicionario §3.4; os da direita sao os cinco
#: contratos que o criterio 1 nomeia, e `versao 1` porque e a que o criterio
#: escreve e a que as subscricoes de `registry/vendedor.yaml` e
#: `registry/servicos.yaml` declaram.
#:
#: **A traducao dos tres nomes do criterio 2 ja estava decidida**, e em tres
#: superficies independentes: o criterio escreve `hmac_sha256`, `status_pull` e
#: `humano_auditado`, e o dominio da base e `hmac`, `consulta`, `manual` e
#: `sistema` (`payment_events_authn_method_ck`, `0029`, por decisao do KAM-053 e
#: emenda 1.13 do KAM-141). Os contratos publicados confirmam-no sem
#: ambiguidade: `payment.confirmed` tem `authn_method` com
#: `enum: [hmac, consulta]` e `payment.manual_confirmed` com `enum: [manual]`. A
#: divergencia da letra e a divida 180 de `docs/dividas-documentais.md`, com
#: credor; aqui segue-se o dominio, porque a base recusa o resto.
#:
#: **O `sistema` nao confirma nada**, e nao e omissao: o
#: `confirmar_exige_autenticacao` da `0029` nao o inclui e a base recusa um
#: `pagamento_confirmado` com ele (medido pelo KAM-053). Logo nao ha linha de
#: `(pagamento_confirmado, sistema)`.
#:
#: **O que fica de fora fica de fora de proposito.** Um tipo sem linha nao
#: produz evento de dominio e o ledger grava na mesma — e a propriedade que a
#: `0029` escreveu e que o
#: `test_sem_mapeamento_nao_ha_evento_de_dominio_e_o_ledger_grava` mede. Os
#: catorze tipos restantes sao factos internos do ledger (`pagamento_recebido`,
#: que o §5.1 escreve **antes** da decisao; `pagamento_orfao`, que o G3 manda
#: nao reconhecer; `pagamento_duplicado`, que o G7 responde com 200 sem efeito)
#: ou pedem eventos que nao sao destes cinco contratos
#: (`confirmacao_manual_pedida` -> `order.manual_confirmation_requested` do
#: §6.2, que nao tem ficheiro em `contratos/eventos/` e por isso nao se mapeia).
MAPEAMENTO = (
    # Os dois caminhos autenticados do facilitador do G1: HMAC sobre o corpo
    # cru, ou `status()` autenticado quando o facilitador nao assina (§5).
    ("pagamento_confirmado", "hmac", "payment.confirmed", 1),
    ("pagamento_confirmado", "consulta", "payment.confirmed", 1),
    # A confirmacao humana auditada. **Evento distinto e nao o mesmo**, e a
    # razao esta no `docs/tecnica/06` §5: misturar os dois sob
    # `payment.confirmed` escondia a diferenca de autenticacao. O G8 da `0032`
    # garante que ela tem confirmador, desafio de valor e limites.
    ("pagamento_confirmado", "manual", "payment.manual_confirmed", 1),
    # `sistema` porque ninguem autentica a emissao de uma referencia: e um facto
    # de ciclo de vida da cobranca, e e esse o dominio do quarto valor.
    ("referencia_emitida", "sistema", "payment.reference_issued", 1),
    # O valor ou a referencia divergentes do G4/G5, pelos dois caminhos
    # autenticados. O `payment.failed` alimenta o HND (humano) e o COM.
    ("pagamento_divergente", "hmac", "payment.failed", 1),
    ("pagamento_divergente", "consulta", "payment.failed", 1),
    # O TTL da cobranca. Tambem `sistema`: e o relogio e nao o facilitador.
    ("cobranca_expirada", "sistema", "payment.expired", 1),
)

#: O passo (7) que esta revisao instala: agregado `order` e `payload` do
#: contrato. Ver a nota do modulo para as duas medicoes que o obrigam.
PASSO_SETE_DO_0035 = """
          -- (7) O *outbox*, na mesma transaccao (ADR-009). O agregado e a
          -- **encomenda** e o `payload` e o do contrato publicado.
          SELECT m.evt_tipo, m.evt_versao INTO v_evt_tipo, v_evt_versao
            FROM platform.payment_outbox_map m
            WHERE m.tipo_evento = p_tipo_evento
              AND m.authn_method = p_authn_method;
          -- Um tipo sem mapeamento nao produz evento de dominio, e o ledger
          -- grava na mesma: a propriedade que a `0029` escreveu, e que fica.
          --
          -- **E uma cobranca de billing tambem nao**, e isso e novo: os cinco
          -- contratos agregam por `order` e exigem `order_id`, e uma cobranca
          -- de ciclo (`order_id IS NULL`, exclusividade imposta pelo
          -- `payment_charges_um_sujeito`) nao tem encomenda para agregar. O
          -- evento de billing e do KAM-059 e do KAM-060 e tera contrato
          -- proprio; emitir um `payment.confirmed` sem `order_id` era publicar
          -- um envelope que o seu esquema recusa.
          IF v_evt_tipo IS NOT NULL AND v_charge.order_id IS NOT NULL THEN
            v_evt_id := platform.evt_emitir(
              v_evt_tipo, v_evt_versao, v_charge.tenant_id, 'order',
              v_charge.order_id::text,
              platform.payment_evt_payload(
                v_evt_tipo, v_charge.order_id, v_charge.provider,
                coalesce(v_charge.referencia,
                  v_charge.id::text || '#' || v_charge.tentativa::text),
                p_valor_minor, v_charge.currency, p_authn_method, p_authn_ok,
                p_provider_event_id, p_motivo, v_charge.valid_until));
          END IF;
"""

#: O passo (7) da `0029`, literal. E o que o `downgrade` repoe.
#:
#: Fica aqui e nao se le da `0029`: uma revisao que importasse o texto de outra
#: deixava o `downgrade` desta a depender de um ficheiro que ninguem revia ao
#: mesmo tempo que este.
PASSO_SETE_DO_0029 = """
          -- (7) O *outbox*, na mesma transaccao (ADR-009). Um tipo sem
          -- mapeamento nao produz evento de dominio: o mapa e do KAM-055, e e
          -- o que deixa esta revisao fundir antes dele.
          SELECT m.evt_tipo, m.evt_versao INTO v_evt_tipo, v_evt_versao
            FROM platform.payment_outbox_map m
            WHERE m.tipo_evento = p_tipo_evento
              AND m.authn_method = p_authn_method;
          IF v_evt_tipo IS NOT NULL THEN
            v_evt_id := platform.evt_emitir(
              v_evt_tipo, v_evt_versao, v_charge.tenant_id, 'payment_charge',
              p_charge_id::text,
              jsonb_build_object(
                'charge_id', p_charge_id, 'tipo_evento', p_tipo_evento,
                'sequencia', v_seq, 'estado', v_estado,
                'valor_minor', p_valor_minor, 'currency', v_charge.currency,
                'authn_method', p_authn_method, 'decisao', p_decisao,
                'motivo', p_motivo));
          END IF;
"""


def upgrade() -> None:
    _fks()
    _payload()
    _porta(PASSO_SETE_DO_0035, CODA_DO_0035)
    _mapa()


def _fks() -> None:
    """As tres FK compostas. Ver a nota do modulo para a forma e o preco.

    **Por extenso e nao em laco**, pela razao escrita na nota do `FKS`: o *gate*
    3b nao resolve um `op.execute` cujo SQL vem de uma variavel de laco.
    """
    op.execute(
        f"ALTER TABLE {COBRANCAS} "
        f"  ADD CONSTRAINT {FK_DAS_COBRANCAS} "
        f"  FOREIGN KEY (tenant_id, order_id) "
        f"  REFERENCES {ENCOMENDAS} (tenant_id, id)"
    )
    op.execute(
        f"ALTER TABLE {EVENTOS} "
        f"  ADD CONSTRAINT {FK_DOS_EVENTOS} "
        f"  FOREIGN KEY (tenant_id, order_id) "
        f"  REFERENCES {ENCOMENDAS} (tenant_id, id)"
    )
    op.execute(
        f"ALTER TABLE {REEMBOLSOS} "
        f"  ADD CONSTRAINT {FK_DOS_REEMBOLSOS} "
        f"  FOREIGN KEY (tenant_id, order_id) "
        f"  REFERENCES {ENCOMENDAS} (tenant_id, id)"
    )
    op.execute(
        f"COMMENT ON CONSTRAINT {FK_DAS_COBRANCAS} "
        f"ON {COBRANCAS} IS "
        "'A FK que a 0029 deixou para o KAM-055. Composta com o tenant_id "
        "contra a orders_mirror_tenant_id_uq: so sobre order_id, a cobranca de "
        "um tenant podia apontar para a encomenda de outro. MATCH SIMPLE, pelo "
        "que uma cobranca de ciclo de billing (order_id nulo) passa.'"
    )
    op.execute(
        f"COMMENT ON CONSTRAINT {FK_DOS_EVENTOS} "
        f"ON {EVENTOS} IS "
        "'Idem, para o ledger. O ledger e append-only, pelo que esta FK torna "
        "uma encomenda com eventos impossivel de apagar — que e o que se quer "
        "em producao e o que a limpeza das suites tem de respeitar.'"
    )
    op.execute(
        f"COMMENT ON CONSTRAINT {FK_DOS_REEMBOLSOS} "
        f"ON {REEMBOLSOS} IS "
        "'A FK que a 0032 deixou para o KAM-055, com a da payment_charges e "
        "pela razao dela: por a FK de order_id so num dos lados deixava o par "
        "incoerente. Fora do criterio 8, declarada no PR.'"
    )


def _payload() -> None:
    """`payment_evt_payload`: o `payload` de cada um dos cinco contratos.

    Esta funcao e a barreira do criterio 2 e nao um formatador. Tres recusas,
    e cada uma fecha um caminho pelo qual um envelope invalido ou nao
    autenticado chegaria aos consumidores:

        authn_ok falso          num `payment.confirmed` ou
                                `payment.manual_confirmed` — «nunca existe um
                                emitido sem o authn_ok=true correspondente»
        motivo nulo             num `payment.failed`, que o contrato exige
        evt_tipo desconhecido   um mapa que aponte para um evento cujo payload
                                esta funcao nao sabe construir **recusa**, em
                                vez de emitir um objecto que o esquema do
                                evento rejeita

    **`STABLE` e nao `IMMUTABLE`**: o `expira_at` converte um `timestamptz` para
    texto, e isso le o `TimeZone` da sessao.

    O `jsonb_strip_nulls` aplica-se **so** a `autenticacao`, e e por causa do
    `provider_event_id`: e opcional no contrato, e um
    `jsonb_build_object` com valor nulo escreve `"provider_event_id": null`, que
    um `{"type": "string"}` recusa. Nos campos obrigatorios nao se aplica —
    ali um nulo e um defeito, e e para isso que estao as duas primeiras recusas.
    """
    op.execute(
        """
        CREATE FUNCTION platform.payment_evt_payload(
          p_evt_tipo text, p_order_id uuid, p_provider text, p_referencia text,
          p_valor_minor bigint, p_currency text, p_authn_method text,
          p_authn_ok boolean, p_provider_event_id text, p_motivo text,
          p_expira_at timestamptz)
        RETURNS jsonb LANGUAGE plpgsql STABLE AS $pay$
        DECLARE v_autenticacao jsonb;
        BEGIN
          -- Os cinco contratos exigem `order_id`, e um `jsonb_build_object`
          -- com valor nulo escreve `"order_id": null` — que o `format: uuid`
          -- recusa. O passo (7) da porta ja nao chama esta funcao para uma
          -- cobranca de billing; isto fecha a funcao para quem a chame de
          -- outro sitio, e e o que a torna total: cada caminho devolve um
          -- payload valido ou levanta.
          IF p_order_id IS NULL THEN
            RAISE EXCEPTION
              'payment_evt_payload: os cinco contratos payment.* exigem '
              'order_id, e um % de uma cobranca sem encomenda nao e '
              'publicavel (o evento de billing e do KAM-059)', p_evt_tipo
              USING ERRCODE = 'check_violation';
          END IF;

          IF p_evt_tipo IN ('payment.confirmed', 'payment.manual_confirmed') THEN
            IF p_authn_ok IS NOT TRUE THEN
              RAISE EXCEPTION
                'payment_evt_payload: nao se emite % com authn_ok=% (ADR-013, '
                'criterio 2 do KAM-055)', p_evt_tipo, p_authn_ok
                USING ERRCODE = 'check_violation';
            END IF;
            v_autenticacao := jsonb_strip_nulls(jsonb_build_object(
              'authn_method', p_authn_method,
              'authn_ok', p_authn_ok,
              'provider_event_id', p_provider_event_id));
          END IF;

          IF p_evt_tipo = 'payment.confirmed' THEN
            RETURN jsonb_build_object(
              'order_id', p_order_id, 'provider', p_provider,
              'referencia', p_referencia, 'valor_minor', p_valor_minor,
              'currency', p_currency, 'autenticacao', v_autenticacao);
          ELSIF p_evt_tipo = 'payment.manual_confirmed' THEN
            RETURN jsonb_build_object(
              'order_id', p_order_id, 'valor_minor', p_valor_minor,
              'currency', p_currency, 'autenticacao', v_autenticacao);
          ELSIF p_evt_tipo = 'payment.reference_issued' THEN
            RETURN jsonb_build_object(
              'order_id', p_order_id, 'provider', p_provider,
              'referencia', p_referencia, 'valor_minor', p_valor_minor,
              'currency', p_currency, 'expira_at', p_expira_at);
          ELSIF p_evt_tipo = 'payment.failed' THEN
            IF p_motivo IS NULL THEN
              RAISE EXCEPTION
                'payment_evt_payload: um payment.failed sem motivo nao e '
                'publicavel (o contrato exige-o; os valores sao os nove '
                'MOTIVOS_DE_FALHA da 0029, na forma longa)'
                USING ERRCODE = 'check_violation';
            END IF;
            RETURN jsonb_build_object(
              'order_id', p_order_id, 'provider', p_provider,
              'referencia', p_referencia, 'motivo', p_motivo);
          ELSIF p_evt_tipo = 'payment.expired' THEN
            RETURN jsonb_build_object(
              'order_id', p_order_id, 'provider', p_provider,
              'referencia', p_referencia, 'expira_at', p_expira_at);
          END IF;

          RAISE EXCEPTION
            'payment_evt_payload: nao sei construir o payload de % — um '
            'mapeamento para um evento sem payload conhecido recusa, em vez de '
            'emitir um envelope que o esquema dele rejeita', p_evt_tipo
            USING ERRCODE = 'check_violation';
        END $pay$
        """
    )
    op.execute(
        f"COMMENT ON FUNCTION platform.payment_evt_payload({ARGUMENTOS_DO_PAYLOAD}) IS "
        "'O payload de cada um dos cinco contratos payment.* (KAM-055). "
        "SECURITY INVOKER e sem acesso a tabela nenhuma. Tres recusas: "
        "authn_ok falso num confirmado, motivo nulo num failed, e evt_tipo "
        "desconhecido. STABLE porque o expira_at le o TimeZone da sessao.'"
    )
    op.execute(
        f"REVOKE ALL ON FUNCTION platform.payment_evt_payload({ARGUMENTOS_DO_PAYLOAD}) "
        "FROM PUBLIC"
    )


def _mapa() -> None:
    """As sete linhas do mapa. O conteudo que a `0029` deixou a este ticket.

    Depois da porta, e nao antes: com o mapa cheio e a porta antiga, qualquer
    `pagamento_confirmado` emitia um envelope agregado pela cobranca — isto e, a
    ordem destes dois passos e a diferenca entre nunca publicar um envelope
    invalido e publicar os que caibam entre os dois `op.execute`.
    """
    for tipo_evento, authn_method, evt_tipo, evt_versao in MAPEAMENTO:
        op.execute(
            f"INSERT INTO {MAPA} (tipo_evento, authn_method, evt_tipo, evt_versao) "
            f"VALUES ('{tipo_evento}', '{authn_method}', '{evt_tipo}', {evt_versao})"
        )


def _porta(passo_sete: str, coda: str) -> None:
    """`append_payment_event`, com o passo (7) que lhe derem.

    O corpo e copia literal da `0029` (`_append()`), e so o passo (7) e
    parametro. Ver a nota do modulo: e o que torna as duas versoes identicas por
    construcao em tudo o resto.
    """
    op.execute(
        rf"""
        CREATE OR REPLACE FUNCTION platform.append_payment_event(
          p_charge_id uuid,
          p_tipo_evento text,
          p_account_id uuid,
          p_valor_minor bigint,
          p_authn_method text,
          p_authn_ok boolean,
          p_decisao text,
          p_motivo text DEFAULT NULL,
          p_actor_kind text DEFAULT 'provider',
          p_actor_id uuid DEFAULT NULL,
          p_provider_event_id text DEFAULT NULL,
          p_payload jsonb DEFAULT '{{}}',
          p_ocorrido_at timestamptz DEFAULT NULL)
        RETURNS TABLE (
          event_id bigint, sequencia integer, row_hash bytea,
          estado_novo text, outbox_event_id uuid)
        LANGUAGE plpgsql SECURITY DEFINER
        SET search_path = pg_catalog, platform AS $func$
        DECLARE
          v_charge      platform.payment_charges;
          v_seq         integer;
          v_prev        bytea;
          v_hash        bytea;
          v_payload     bytea;
          v_agora       timestamptz;
          v_estado      text;
          v_id          bigint;
          v_evt_tipo    text;
          v_evt_versao  smallint;
          v_evt_id      uuid;
        BEGIN
          -- (1) Serializa. A tranca e na cobranca: e ela que a sequencia, o
          -- `prev_hash` e a projeccao tem de ver na mesma versao.
          SELECT * INTO v_charge FROM platform.payment_charges
            WHERE id = p_charge_id FOR UPDATE;
          IF NOT FOUND THEN
            -- Duas leituras que esta funcao nao distingue, pela razao do
            -- `assert_beneficiary` da `0027`: sob RLS, a cobranca de outro
            -- tenant e indistinguivel de uma que nao existe. Recusa nos dois.
            RAISE EXCEPTION
              'append_payment_event: a cobranca % nao existe ou nao e visivel '
              'no contexto desta transaccao (RLS)', p_charge_id
              USING ERRCODE = 'check_violation';
          END IF;

          -- (3a) G2 do §5, e para **todos** os tipos: um evento de uma conta
          -- que nao e a da cobranca nao e um evento desta cobranca.
          --
          -- **`IS DISTINCT FROM` e nao `<>`**, e a revisao adversarial mediu
          -- porque: `NULL <> x` avalia a `NULL`, o `IF` nao disparava, e o
          -- `INSERT` gravava o `account_id` **da cobranca** — pelo que nao
          -- havia `NOT NULL` que o apanhasse depois, ao contrario do
          -- `p_valor_minor` e do `p_authn_ok`, que as colunas apanham. Isto e,
          -- `p_account_id => NULL` saltava o G2 **em silencio** e confirmava o
          -- pagamento. E o nulo nao e hipotetico: o recibo
          -- `token_desconhecido` do `hooks.ts` grava `accountId: null`.
          IF p_account_id IS NULL
             OR p_account_id IS DISTINCT FROM v_charge.account_id THEN
            RAISE EXCEPTION
              'append_payment_event: o evento e da conta % e a cobranca % e da '
              'conta % (G2)', p_account_id, p_charge_id, v_charge.account_id
              USING ERRCODE = 'check_violation';
          END IF;

          -- (0) A guarda de privacidade, antes de tudo o resto.
          --
          -- O §6.2 escreve «payload redigido: sem PII» e o DoD do bloco faz
          -- disso uma caixa. Uma caixa que se marca por convencao de quem
          -- escreve o codigo nao e uma barreira: o ledger e **append-only**,
          -- pelo que um telefone que entre aqui nao sai mais — nem com um
          -- `UPDATE`, que o `deny_mutation` recusa.
          --
          -- Os dois padroes sao **os mesmos** do `evt_emitir` da `0004`, e e
          -- deliberado que sejam os mesmos e nao melhores: o que esta guarda
          -- apanha e o que essa apanha, e um ledger que fosse mais permissivo
          -- do que o *outbox* deixava passar o que o evento de dominio recusa.
          -- O que nenhuma das duas apanha e um telefone escrito de outra forma;
          -- isso diz-se, e e a razao de a redaccao continuar a ser
          -- responsabilidade de quem constroi o payload.
          --
          -- O `motivo` entra na verificacao: ele viaja para o *outbox* no
          -- passo (7), pelo que um telefone ali era PII num evento de dominio.
          -- As chaves do quantificador vao **duplicadas**: este SQL esta numa
          -- f-string, e `{{8}}` simples era um campo de substituicao — o *gate*
          -- 3b recusou-o com «f-string com um valor que nao e texto», que e a
          -- mesma leitura que o Python faz. A cadeia e `rf` pela razao da
          -- `0004`: `\+` nao e sequencia de escape de Python, e numa cadeia
          -- normal escrevia-se `\+` — o ficheiro deixava de se poder ler
          -- contra o `docs/tecnica/06` §6.1 a olho.
          IF p_payload::text ~ '\+?244 ?9[0-9]{{8}}'
             OR p_payload::text ~ '"\+[0-9]{{9,15}}"'
             OR coalesce(p_motivo, '') ~ '\+?244 ?9[0-9]{{8}}' THEN
            RAISE EXCEPTION
              'append_payment_event: o payload ou o motivo do evento % contem '
              'padrao de telefone (PII P2, ADR-010); o ledger e append-only e '
              'nao se corrige', p_tipo_evento
              USING ERRCODE = 'check_violation';
          END IF;

          -- (3b) As tres recusas do contrato do §6.2, sobre o CHECK e nao em
          -- vez dele. O `CHECK` nao pode fazer esta: nao ve a cobranca.
          IF p_tipo_evento = 'pagamento_confirmado' THEN
            IF p_valor_minor <> v_charge.amount_minor THEN
              RAISE EXCEPTION
                'append_payment_event: nao se confirma % com valor % quando a '
                'cobranca e de % (G4); o evento e pagamento_divergente',
                p_charge_id, p_valor_minor, v_charge.amount_minor
                USING ERRCODE = 'check_violation';
            END IF;
            IF NOT p_authn_ok THEN
              RAISE EXCEPTION
                'append_payment_event: nao se confirma % sem autenticacao (G1)',
                p_charge_id
                USING ERRCODE = 'check_violation';
            END IF;
          END IF;

          -- (6a) A projeccao calcula-se **antes** do INSERT, para que uma
          -- transicao recusada nao deixe o evento escrito. O ledger nao se
          -- corrige: uma linha a mais ficava la para sempre.
          v_estado := platform.next_state(
            v_charge.estado, p_tipo_evento, p_decisao);
          IF v_estado IS NULL THEN
            RAISE EXCEPTION
              'append_payment_event: a cobranca % esta em % e % nao e uma '
              'transicao do docs/tecnica/04 secao 7.1', p_charge_id,
              v_charge.estado, p_tipo_evento
              USING ERRCODE = 'check_violation';
          END IF;

          -- (2) A sequencia, sob a tranca de (1).
          SELECT 1 + count(*) INTO v_seq FROM platform.payment_events
            WHERE provider = v_charge.provider
              AND account_id = v_charge.account_id
              AND referencia = coalesce(v_charge.referencia,
                    v_charge.id::text || '#' || v_charge.tentativa::text)
              AND tipo_evento = p_tipo_evento;

          -- (4) O elo. O `prev_hash` e o da ultima linha **desta cobranca**: a
          -- cadeia e por cobranca (§6.2).
          SELECT e.row_hash INTO v_prev FROM platform.payment_events e
            WHERE e.charge_id = p_charge_id ORDER BY e.id DESC LIMIT 1;
          v_prev := coalesce(v_prev, '{GENESE}'::bytea);
          v_payload := sha256(convert_to(p_payload::text, 'UTF8'));
          -- O `recebido_at` fixa-se **aqui** e nao pelo `DEFAULT now()` da
          -- coluna, porque passou a entrar no elo: um campo que a coluna
          -- preenchesse depois do calculo nao podia ser recalculado pelo
          -- verificador. Dentro de uma transaccao o `now()` e estavel, pelo
          -- que o valor e o mesmo — o que muda e haver **um** sitio a fixa-lo.
          v_agora := now();
          v_hash := platform.payment_event_row_hash(
            v_prev, v_charge.tenant_id, p_charge_id, v_charge.order_id,
            v_charge.billing_cycle_id, v_charge.provider, v_charge.account_id,
            coalesce(v_charge.referencia,
              v_charge.id::text || '#' || v_charge.tentativa::text),
            p_tipo_evento, v_seq, coalesce(p_provider_event_id, ''),
            p_valor_minor, v_charge.currency, p_authn_method, p_authn_ok,
            p_decisao, p_motivo, p_actor_kind, p_actor_id, v_payload,
            p_ocorrido_at, v_agora);

          -- (5) O INSERT. O `tenant_id`, o sujeito, o `provider` e a
          -- `referencia` vem da cobranca e nao do chamador.
          INSERT INTO platform.payment_events (
              tenant_id, charge_id, order_id, billing_cycle_id, provider,
              account_id, referencia, tipo_evento, sequencia, provider_event_id,
              valor_minor, currency, authn_method, authn_ok, decisao, motivo,
              actor_kind, actor_id, payload_hash, payload, ocorrido_at,
              recebido_at, prev_hash, row_hash)
            VALUES (
              v_charge.tenant_id, p_charge_id, v_charge.order_id,
              v_charge.billing_cycle_id, v_charge.provider, v_charge.account_id,
              coalesce(v_charge.referencia,
                v_charge.id::text || '#' || v_charge.tentativa::text),
              p_tipo_evento, v_seq, p_provider_event_id, p_valor_minor,
              v_charge.currency, p_authn_method, p_authn_ok, p_decisao, p_motivo,
              p_actor_kind, p_actor_id, v_payload, p_payload, p_ocorrido_at,
              v_agora, v_prev, v_hash)
            RETURNING id INTO v_id;

          -- (6b) Projecta. O `atualizado_at` e o `motivo_falha` acompanham: uma
          -- cobranca `falhada` sem motivo nao diz nada a ops.
          IF v_estado <> v_charge.estado THEN
            UPDATE platform.payment_charges SET
                estado = v_estado,
                atualizado_at = now(),
                requer_humano = CASE
                  WHEN p_tipo_evento = 'pagamento_divergente' THEN true
                  ELSE requer_humano END,
                motivo_falha = CASE
                  WHEN v_estado = 'falhada' THEN coalesce(p_motivo, motivo_falha)
                  ELSE motivo_falha END
              WHERE id = p_charge_id;
          END IF;
{passo_sete}
          RETURN QUERY SELECT v_id, v_seq, v_hash, v_estado, v_evt_id;
        END $func$
        """
    )
    op.execute(
        f"COMMENT ON FUNCTION platform.append_payment_event({ARGUMENTOS_DE_APPEND}) IS "
        "'A unica porta de escrita do ledger (KAM-053): FOR UPDATE na cobranca, "
        "sequencia sem lacunas, cadeia de hashes, projeccao do estado por "
        "next_state e evt_emitir na mesma transaccao. SECURITY DEFINER porque "
        "nenhum papel de aplicacao tem INSERT em payment_events; o isolamento "
        "continua a ser da RLS, que prende tambem o dono (FORCE)."
        f"{coda}'"
    )


def downgrade() -> None:
    # Sem `CASCADE`, como todas as revisoes desde a `0001`: se houver um objecto
    # pendurado que esta revisao nao criou, o `downgrade` **falha** em vez de o
    # apagar em silencio.
    #
    # Pela ordem inversa do `upgrade`, e a ordem importa num ponto: a porta
    # volta ao passo (7) da `0029` **antes** de a `payment_evt_payload` cair.
    # Um corpo plpgsql nao e seguido pelo catalogo de dependencias — o `DROP`
    # passava com a porta ainda a cita-la —, e o que se ganha e que em nenhum
    # instante do `downgrade` existe uma porta que chame uma funcao ausente.
    _porta(PASSO_SETE_DO_0029, CODA_DA_0029)
    op.execute(
        f"DROP FUNCTION platform.payment_evt_payload({ARGUMENTOS_DO_PAYLOAD})"
    )
    # As **sete** linhas desta revisao, e nao a tabela toda: a `0029` deixou-a
    # vazia, e e para la que isto volta. Apagar tudo levava tambem uma linha que
    # outra revisao ou um ensaio tenha posto, o que nao e o inverso deste
    # `upgrade`.
    for tipo_evento, authn_method, _evt_tipo, _evt_versao in MAPEAMENTO:
        op.execute(
            f"DELETE FROM {MAPA} "
            f" WHERE tipo_evento = '{tipo_evento}' "
            f"   AND authn_method = '{authn_method}'"
        )
    # Por extenso, pela razao da nota do `FKS`: em laco, o *gate* 3b le estas
    # tres instrucoes como `[ilegivel]`.
    op.execute(f"ALTER TABLE {REEMBOLSOS} DROP CONSTRAINT {FK_DOS_REEMBOLSOS}")
    op.execute(f"ALTER TABLE {EVENTOS} DROP CONSTRAINT {FK_DOS_EVENTOS}")
    op.execute(f"ALTER TABLE {COBRANCAS} DROP CONSTRAINT {FK_DAS_COBRANCAS}")
