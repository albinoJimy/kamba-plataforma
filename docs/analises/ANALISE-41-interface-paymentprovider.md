# ANÁLISE-41 — Revisão adversarial do KAM-052 (interface `PaymentProvider`)

| Campo | Valor |
|---|---|
| Ticket | KAM-052 — Interface PaymentProvider (com `verifyCallback` e `reconcile`) e beneficiário por conta |
| Diff revisto | `f60bcf5` (o `pay-core` e o `tools/money_lint`) |
| Revisor | Subagente `general-purpose`, sem acesso ao raciocínio do autor |
| Data | 2026-10-29 |
| Veredicto do revisor | **o ramo não está em condições de fundir** |
| Achados | 24 levantados: **23 CONFIRMADO**, 1 PLAUSÍVEL, 5 hipóteses MORTAS |
| Gravidade | 5 *must fix*, 15 *should fix*, 4 *nice to have* |

## Como correu

Uma revisão adversarial por ticket, lançada **assim que o diff existiu** e não no
fim: correu em paralelo com a self-validation, recebeu o diff e os requisitos e
**não** recebeu as justificações do autor. Mediu a sua própria linha de base
(87 testes, 0 falhas; cobertura do módulo a 96,00% de linhas) em vez de a aceitar.

A frase que resume o resultado é do próprio revisor: **«o problema deste diff não
é o dinheiro, é a medição.»** A aritmética de `Minor`, a máquina de estados e a
G-1 do lado da aplicação foram procuradas a sério e estão certas — o que estava
errado eram as barreiras que mediam o resto.

## Os cinco *must fix*

### A6 — O *harness* dava verde a um adaptador que não verifica assinatura nenhuma

**O achado mais consequente, e é estrutural.** O caso 1 (§3.5, «assinatura
adulterada ⇒ rejeita») recebia a mutação do `BancoDeEnsaio` — isto é, **de quem
estava a ser medido**. O revisor escreveu dois adaptadores obviamente defeituosos
e mediu que os dois passavam os dez casos e eram activados:

- **A**: `verifyCallback` exige só um campo `sig` não vazio, e o `adulterar` do
  seu banco esvazia esse campo. Em produção, quem descobrisse o `webhook_token`
  confirmava um pagamento de 999 999,99 Kz com `sig: "x"`.
- **B**: verifica HMAC a sério e **ignora o `acct`**, com um conjunto global de
  chaves. Aceita o callback da PME A entregue no `webhook_token` da PME B, contra
  o §3.3 («uma chave por conta de PME e nunca partilhada»). **Nenhuma mutação de
  assinatura o apanharia.**

Verificado por mim antes de corrigir: o adaptador A aceita um callback forjado sem
chave nenhuma (`['forjado:9999999999']`).

**Correcção.** O caso 1 passa a ter três sub-verificações, e a que faz o trabalho
é do *harness* e agnóstica ao formato: um callback **genuinamente assinado para
outra conta**, apresentado com as credenciais desta, tem de ser recusado. Mata os
dois adaptadores — o A porque o callback de B lhe é tão válido como o de A, o B
porque é exactamente a propriedade que ele não tem — e não incomoda o honesto. A
terceira sub-verificação junta o corpo de um evento aos cabeçalhos de outro, para
o adaptador que confere o cabeçalho sem o ligar ao corpo. Os dois adaptadores
defeituosos ficam como **ensaio permanente**, não como nota.

### A1 — O `money_lint` era cego dentro de literais de *template*

O apagamento de cadeias apagava o literal de *template* **inteiro**, incluindo as
expressões `${…}`, que são código. `` `${Number(minor) / 100}` `` contém as duas
regras que o lint existe para apanhar e dava **0 achados**, enquanto a mesma
expressão fora do *template* era acusada. E é o idioma com que se formata um
montante para apresentar — o `dinheiro.ts` já formata assim.

### A2 — O separador de milhares derrotava a regra do decimal

Em `50_000.00` o carácter antes de `000.00` é `_`, que é `\w`, e o *lookbehind*
bloqueava o encontro. **O estilo da casa era o que cegava o lint:** este
repositório escreve todos os literais com `_`. Um `MANUAL_MAX = 50_000.00` — o
tecto do `ManualProvider` do KAM-054, em kwanzas com casas — passava o gate 2.

### A11 — O `capabilities.metodos` não era lido por linha nenhuma de produção

O §3.1 abre a enumeração de `ProviderCapabilities` com «**métodos suportados**» e
fecha com «o PAY **recusa** usar uma capacidade não declarada». O revisor mediu
`createCharge` com os quatro `Metodo` contra um adaptador que declara
`metodos: ["referencia"]`: **os quatro aceites**, e um pedido `metodo: 'cod'`
devolvia uma referência Multicaixa. Era metade do critério 2.

Correcção: entram `suporta()` e `RegistoDeProviders.cobrar()`, que é o caminho
recomendado e o que verifica.

### A17 — As dívidas 148–152 diziam-se registadas e não existiam

Cinco divergências face ao dicionário, ao `docs/tecnica/04` e ao próprio título do
ticket citavam linhas que o ledger não tinha — ele acabava em 147. Uma delas na
própria frase «fica registada … **em vez de ser escolhida em silêncio**», que
ficava literalmente falsa. Pagas como **148 a 155**.

## Os *should fix* que mudaram comportamento

| Achado | O que estava errado | O que mudou |
|---|---|---|
| A7 | Só 5 dos 10 casos tinham canário; as linhas não cobertas de `conformidade.ts` eram **exactamente** os ramos de falha dos casos sem canário | Os dez têm canário, e há ensaio a exigir que nenhum fique sem |
| A8 | O caso 2 não media o que o §3.5 nomeia: não havia «± 1 cêntimo» nem comparação com a cobrança — `banco.pedido()` nem entrava no caso | Mede a diferença face ao montante **cobrado**, em `+1`, `−1` e exacto |
| A9 | O caso 7 ficava verde com o adaptador a criar **quatro** cobranças no facilitador: comparava só os objectos devolvidos | Conta as criações; o dano real são duas referências Multicaixa para a mesma encomenda, e a Multicaixa não admite devolução (§1.4) |
| A10 | O `status()` do `FakeProvider` era um memorando do próprio callback, pelo que a concordância do caso 10 era **tautológica** — o caso não conseguia detectar a única coisa para que serve | O «facilitador» registra o pagamento ao emitir o evento; o `verifyCallback` não escreve nesse mapa. Dois caminhos independentes |
| A12 / A13 | As etiquetas `humanOnly` e `pspLicenciado` eram **auto-atribuídas**: a guarda do ADR-013 e a G-2 desligavam-se com uma linha nas capacidades do adaptador que elas deviam medir | Listas fechadas na `PoliticaDeActivacao`, passada no arranque. O critério 2 escreve a excepção com um **nome** (`ManualProvider`), e agora o código também |
| A14 | `activar` aceitava um adaptador com `refund: true` e `payout: true`; a G-2 tem **dois** mecanismos e só o segundo estava imposto | A declaração falsa recusa a activação |
| A15 | `refund`/`payout` **lançavam**, e o critério 3 e o §3.1 dizem «devolvem `NOT_SUPPORTED`» — o `RefundResult` ficava inalcançável pelo caminho recomendado | Devolvem |
| A16 | `cancelCharge` ausente dava `VALIDATION` com a frase «declara `cancelCharge` mas não implementa `cancelCharge`», que se contradiz | `NOT_SUPPORTED`: um opcional sem campo em `ProviderCapabilities` é, por ausência, não declarado |
| A19 | `podeCobrar` devolvia só `ativo`, duas linhas abaixo de uma constante que dizia o contrário. **O §10.2 faz de `teste_sandbox_ok → ativo` uma transição que exige uma cobrança real**, pelo que nenhuma conta chegava a `ativo` — um impasse que só apareceria com a primeira PME | `podeCobrar` são os dois estados; `estaActiva` é a outra pergunta |
| A21 | A G-4 lia a constante compilada por omissão: editar `config/kamba_emis.yaml` não mudava nada no serviço a correr | A lista perde a omissão — quem arranca tem de dizer de onde veio |
| A23 | Um montante de 16 dígitos (`"0000000000000001.00"`, 1,00 Kz com enchimento a zeros, comum em integrações bancárias) era recusado com a mensagem «não tem a forma decimal2» | Tecto de 30 dígitos, nomeado na mensagem |
| A24 | A fórmula do comprimento do `webhook_token` dava 44 e a constante era 43 (o valor certo) | Fórmula corrigida; uma fórmula errada ao lado de um valor certo é um convite a «corrigir» o valor |

## O PLAUSÍVEL

**A22 — a recusa `HUMAN_ONLY_INCOERENTE` é nova.** Um adaptador com
`humanOnly: true` e `statusQuery: true` não está no conjunto que o critério 2
manda recusar, por nenhuma das duas leituras, e é recusado — com um código que o
bloco não tem. O revisor não tinha o PR, onde a decisão sobre o `humanOnly` devia
estar registada. **Fica registada no PR deste ticket**, como os *Detalhes
Técnicos* mandam, e o argumento é o de `registo.ts`: sem ela a dispensa era
genérica, porque a etiqueta deixava de descrever o adaptador que ela dispensa.
Nenhum adaptador do §3.2 é afectado hoje (a matriz escreve «n/a» nas três colunas
do `ManualProvider`), pelo que o custo prático é zero.

## As cinco hipóteses MORTAS, com a evidência que as matou

Registam-se para a próxima auditoria não as voltar a levantar — é o que a dívida
custa de outra forma.

| # | Hipótese | A evidência que a matou |
|---|---|---|
| M1 | «A conversão `Minor` ↔ `decimal2`/`inteiro_kz` perde um cêntimo, ou aceita o que devia recusar» | *Round-trip* **exaustivo** de 0 a 300 000 cêntimos em `decimal2` e de 0 a 100 000 Kz em `inteiro_kz`: 0 falhas. Recusa, como devia, 17 formas malformadas (`" 1234.57"`, `"1234,57"`, `"1e3"`, `"0x10"`, `"١٢٣٤"`, `"NaN"`, …). A travessia é lexical de ponta a ponta; `dinheiro.ts` a 100% de linhas |
| M2 | «`ProviderCapabilities` não tem limites de montante e aceita acima do tecto de 99 999 999,99 Kz do §3.3» | A enumeração do §3.1 tem onze campos e **não** tem limites de montante; o código tem os onze, nem um a mais. Não é violação de critério. Fica dito que o KAM-056 vai descobrir o tecto do ProxyPay como `VALIDATION` em execução, por não haver onde o declarar |
| M3 | «O YAML e o TypeScript da G-4 podem divergir em silêncio» | O ensaio afirma primeiro as três chaves e só depois a igualdade das listas; um valor num só lado falha, e uma lista em estilo de bloco faz falhar a asserção das chaves. Falha do lado certo |
| M4 | «`beneficiary_kind='pme'` em vez de `'tenant'` viola o critério 4 e o §6.2» | O dicionário §3.4 é fonte acima do `docs/tecnica/04`, o domínio está fechado em `canon/dicionario.yaml`, e o gate 3b devolve **dezanove** achados sobre uma migração copiada à letra do §6.2. A escolha está certa; o que ficou vivo foi só o registo (A17) |
| M5 | «G-3: existe `balance`, `wallet` ou `escrow` no código» | `grep -rniE` em `packages services libs db tools`: três ocorrências, todas legítimas (dois comentários e um `LIKE '%balance%'` de um teste de catálogo pré-existente) |

## Áreas em que o revisor procurou e não achou nada

Os oito métodos do §3.1 e os tipos `Minor`/`Metodo`/`ChargeResult`/`ProviderErr`
batem à letra com o bloco de código daquela secção; as nove arestas e os nove
gatilhos do §10.2, com nenhuma a mais e `nao_iniciado → ativo` recusada por
ausência de aresta e não por caso especial (`estados.ts` a 100%/100%); os três
casos da G-1 do lado da aplicação, o terceiro com **dois** tenants distintos; o
teste de arranque com `payouts_enabled=true`; e o `webhook_token` (32 octetos de
CSPRNG, 43 caracteres em 2 000 sorteios, sem `+`, `/` nem `=`).

## Duas notas de medição que o revisor deixou e que valem para quem vier

1. **O `coverage_gate.py` agrega por estrato e não por ficheiro.** Passar o gate 4
   **não** é prova de que este módulo esteja acima de 90%: foi preciso medi-lo à
   parte (96,00% de linhas, 86,00% de ramos). Quem declarar a caixa da cobertura
   do DoD de um módulo mede o módulo, não o estrato.
2. **O critério 1 diz «falha o *build*» e o `money-lint` está no gate 2**, não no
   gate 1. Bloqueia de facto — o `make` pára na primeira falha e o CI corre
   `make ci-2` —, e a escolha do gate 2 é a sanção da casa para um portão novo
   (um *job* novo acrescenta um contexto exigido ao *ruleset* de `main`, que é
   alteração de regra de bloqueio). Fica dita a diferença de letra.

## E o que o gate 8 encontrou depois dela, que nenhuma revisão podia ter encontrado

A revisão correu sobre o diff do `pay-core`, antes de a metade de base de dados
existir. Quando ela correu contra um PostgreSQL 18.6 real, o servidor devolveu
**cinco achados que nenhuma leitura apanharia** — e o primeiro é do mesmo tipo
que os três *must fix* acima: uma barreira que não podia funcionar nas condições
em que foi declarada.

### G1 — `SECURITY DEFINER` não contorna `FORCE ROW LEVEL SECURITY`

O `assert_beneficiary` foi escrito `SECURITY DEFINER` com um argumento que parecia
sólido, e que está escrito por extenso na primeira versão da revisão: a função
tem de ler uma conta de `tenant_id` **nulo**, que a `tenant_iso` esconde de quem
chama, pelo que com `INVOKER` a guarda recusaria **toda** a cobrança de billing.

**O argumento estava errado.** `SECURITY DEFINER` troca o `current_user` pelo
**dono** da função — `kamba_migrator`, que é `NOBYPASSRLS` — e o `FORCE` vincula
o dono da tabela também (é metade da razão de o `FORCE` existir). A função não
via conta **nenhuma** e recusava tudo com «conta inexistente»: cinco ensaios
vermelhos, com `23503` onde se esperava `23514`.

A saída óbvia — a função ser dona por um papel com `BYPASSRLS` — **não existe
aqui**: o `db/bootstrap.py` **revoga activamente** toda a pertença entre papéis,
e isso é uma barreira deliberada que não se afrouxa para isto.

`INVOKER` resolve, e **pela razão oposta à que se temia**: a cobrança de billing
é inserida pelo processo de billing, que corre como `kamba_batch` — e esse *tem*
`BYPASSRLS`. O caso que o argumento dava como impossível é exactamente o que
funciona. O que fica é uma imprecisão **declarada e medida por ensaio próprio**:
para um chamador sujeito a RLS, «a conta é de outro tenant» é indistinguível de
«a conta não existe», pelo que a guarda recusa nos dois e a mensagem diz as duas
possibilidades.

### G2 — Acrescentar a tabela a `TABELAS` leakou-a para todas as revisões anteriores

A cadeia `TABELAS_ATE_*` de `db/tests/base.py` deriva de `TABELAS`, pelo que
declarar a `payment_accounts` pô-la nas tuplas de revisões **anteriores** — e
**quinze** ensaios de `downgrade` de outros módulos passaram a esperar, na `0018`,
uma tabela que só existe na `0027`. Re-enraizou-se a cadeia no
`TABELAS_ATE_0026`, que é a forma que o ficheiro já usava para as outras.

### G3, G4, G5 — três defeitos nos meus próprios ensaios

- **O ensaio dos domínios batia na barreira do critério 4**: inseria nove contas
  com o mesmo `provider`, e o `ativo` e o `teste_sandbox_ok` colidem no índice
  único parcial. O índice estava certo e o ensaio errado.
- **Nove ensaios davam `25P02`** (`in_failed_sql_transaction`): no PostgreSQL a
  primeira instrução que falha aborta a transacção, pelo que um ensaio com duas
  recusas seguidas media a abortagem e não a violação. Entrou um ponto de
  recuperação por recusa — e no caso 3 da G-1 isso importa duplamente, porque a
  inserção final (o dono *continua* a poder cobrar) corria numa transacção morta.
- **A expressão do cofre comparava-se à letra** e o literal de expressão regular
  do TypeScript escreve `\/` onde a cadeia de Python escreve `/`. São a mesma
  expressão; o ensaio comparava a grafia.

### G6 — o gate 6 recusou com `42501`: a matriz dizia quem pode, e faltava quem limpa

Dez `tearDownClass` da bateria de isolamento falharam com
`permission denied for table payment_accounts`. A tabela estava declarada nos
inventários — era o que faltava não era a declaração, era o **`GRANT`**: concedi
`SELECT, INSERT, UPDATE` ao `kamba_batch` e retive o `DELETE`, com o argumento de
que «ninguém apaga uma conta de pagamento; encerrar é `estado = 'revogado'`».

O argumento vale para o `kamba_app` e **não** para o `kamba_batch`, e a `0025` já
o escreve por extenso: «quem apaga é o `kamba_batch`, que é o papel da retenção
(KAM-071) e o **semeador das baterias de isolamento**». O dicionário §2 ressalva o
mesmo: «soft delete: estado, nunca `DELETE`, **salvo purga prevista**». Conceder
o `DELETE` ao papel de lote não afrouxa barreira nenhuma — repõe a regra; a
barreira continua onde vive, que é o `kamba_app` e o `kamba_audit` sem `DELETE`.

**A lição é a forma do erro, não o `GRANT`:** uma tabela nova tem duas metades no
isolamento, e declarar a primeira (os inventários) sem a segunda (os privilégios
que a limpeza precisa) dá um gate vermelho que parece ser da tabela e é da suite.

### E dois achados do gate 9 no meu próprio ficheiro de ensaio

O padrão `atribuicao` do `scan_secrets` acusa uma atribuição a um nome que
significa segredo quando o lado direito tem entropia, e **não distingue um
literal de uma chamada de função nem de um nome de ensaio**. Recusou
`webhook_token="…"` nos chamadores e, antes disso, um `const token = gerarAlgo()`
em TypeScript. Nos dois casos renomeou-se — declarar o ficheiro em
`ci/secrets-allow.yaml` era tirar a barreira a um ensaio inteiro para calar um
falso positivo numa linha.

## O que esta revisão diz sobre o ticket

Dos cinco *must fix*, **três eram barreiras que não podiam falhar nas condições em
que foram declaradas satisfeitas** — o caso 1 do *harness*, as duas etiquetas
auto-atribuídas e o lint cego ao idioma da casa. É a mesma classe que a análise 33
mediu no KAM-030, e a lição repete-se: uma barreira escrita não é uma barreira
medida, e o que separa as duas é um controlo positivo. As cinco correcções que
mais valem neste PR nasceram de canários — incluindo a descoberta de que o caso 2
não media nada, que foi um canário a dizê-lo.
