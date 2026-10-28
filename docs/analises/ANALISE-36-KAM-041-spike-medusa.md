# ANÁLISE-36 — Revisão adversarial do KAM-041 (spike Medusa v2: isolamento e reservas com TTL)

| Campo | Valor |
|---|---|
| Ticket | KAM-041 — Spike Medusa v2: isolamento entre vendedores e reservas com TTL |
| Ramo | `feature/KAM-041-spike-medusa-isolamento-reservas` |
| Objecto | `../../spikes/medusa-d3/` (11 módulos Python, 1 `.mjs`, 4 `.sql`, o projecto Medusa) e `../spikes/KAM-041-medusa.md` |
| Data | 2026-10-27 |
| Método | Um agente independente, só de leitura. Recebeu **o código e os requisitos** — o bloco do ticket e as secções §3.2, §4.3, §4.4, §4.5, §5.4, §5.5, §6.2–6.5, §7.1 e §10.3 do `../tecnica/03` — e **não** as justificações de quem o escreveu. Pergunta central: «algum critério pode estar a passar pela razão errada?» |
| Veredicto | **Não estava pronto para fechar**: 14 achados de severidade alta, 19 de média, 8 de baixa |
| Estado | 14 altos: **12 corrigidos, 2 aceites como limite declarado**; 19 médios: 13 corrigidos, 6 declarados; 8 baixos: 3 corrigidos, 5 registados |

> **A lição desta revisão é que um instrumento de medição mente por omissão.**
> O harness tinha a disciplina certa onde ela é visível — `nao_verificado`
> nunca contava como verde, e a contagem do AC-1 não arredondava — e ainda
> assim **quatro critérios bloqueantes e cerca de quinze casos ISO podiam
> produzir verde sem medirem a propriedade que nomeiam**. Dois critérios não
> podiam falhar por construção; dois casos ISO não podiam passar por
> construção. Nada disto aparece num teste que corre e fica verde.
>
> E a mais caras das catorze não era um erro de lógica: era o **AC-2 a exigir o
> contrário do que o harness precisava para arrancar**. O critério manda que
> nada fora da rede alcance o Medusa, e a espera pelo arranque perguntava ao
> Medusa pelo anfitrião. As duas condições eram mutuamente exclusivas: ou o
> AC-2 passava, ou o harness arrancava. O arranque falhava sempre por *timeout*
> — e nunca pela razão verdadeira, pelo que o defeito escondia os outros.

---

## 0. O que as correcções revelaram

Vale registar antes da lista, porque é a razão pela qual uma revisão
adversarial se paga: **corrigir o instrumento mudou o resultado do spike em
três sítios.**

- **O A10 era o que impedia tudo.** Com a espera pelo arranque a perguntar ao
  Medusa pelo anfitrião — uma porta que o AC-2 exige que não exista —, o Medusa
  nunca chegou a estar de pé em nenhuma execução. Os 22 casos ISO das
  superfícies do Medusa ficavam NÃO VERIFICADOS, e o diagnóstico apontava para
  *timeout* em vez de para a contradição. Corrigido, o Medusa arrancou à
  primeira.
- **O A8/A14 descobriu uma fuga real.** Substituir as sondas de autenticação
  pelo que o §4.4 nomeia — encomendas, *carts*, stock, com um token de operador
  verdadeiro — fez aparecer o **ISO-15**: a API *Store* do Medusa devolve a
  encomenda de um tenant a uma chave publicável de outro. Com os oito casos a
  passarem por «401 sem credencial», essa fuga nunca teria sido vista.
- **O M17 estava a esconder a medição central.** Ler a sobrevenda do contador
  `reserved_quantity` dava «0 acima do stock» no momento exacto em que havia
  **92 reservas a mais**. O contador é a vítima do *lost update*, não a
  testemunha; contar as linhas de reserva é o que produziu o número que decide
  a D3.

---

## 1. Os achados de severidade alta

| # | Achado | Verificação | Acção |
|---|---|---|---|
| A1 | A guarda «houve contenção» do AC-3 (`sucessos > 0 and recusas > 0`) é satisfeita por execução **serial**: mil tentativas sequenciais sobre stock 10 dão exactamente 10 sucessos e 990 recusas, os mesmos números de uma tempestade | **CONFIRMADO** | Corrigido: mede-se a **sobreposição efectiva** (quantas tentativas em voo ao mesmo tempo, por contador) e exige-se ≥ 2, senão `nao_verificado` |
| A2 | 750 das 1.000 tentativas do AC-3 não têm contenção: a vaga 1 esgota o stock e as três seguintes são recusadas sem disputar nada | **CONFIRMADO** | Corrigido: resultado reportado **por vaga**, para não sugerir que mil tentativas disputaram dez unidades |
| A3 | A barreira sincronizava a **abertura da ligação** (TCP + SCRAM + `set_config` + `SELECT`), não o `UPDATE`; a dispersão de chegada ao ponto crítico era de centenas de ms contra um `UPDATE` sub-milissegundo | **CONFIRMADO** | Corrigido: `tempestade` aceita um `aquecer`, que paga o custo da ligação **antes** da barreira |
| A4 | «990 recusas» não era verificável como «recusado por falta de stock»: qualquer excepção contava, incluindo `too many clients already` | **CONFIRMADO** | Corrigido: recusas classificadas; as que não são por stock tornam o critério `nao_verificado` |
| A5 | O p99 do AC-6 é o período de *polling* do próprio harness (0,2 s), e `p99 ≤ 60 s` é verdadeiro por construção. O §6.5 tem um *job* de 60 s + *delayed job*, e nenhum está implementado | **CONFIRMADO** | **Aceite como limite declarado**: o AC-6 passa a `nao_verificado`, com o número e a razão. O que a medição estabelece — o custo de processamento da libertação — fica dito |
| A6 | «a reserva paga não foi libertada» era uma asserção contra o `continue` do próprio teste: `release_reservation` não tinha consulta a PAY nenhuma | **CONFIRMADO** | Corrigido: a consulta final a PAY passou para **dentro da porta** (`consultar_pay` injectado), e o varredor chama a porta como para as outras |
| A7 | ISO-30 e ISO-31 eram **estruturalmente não mediáveis**: o predicado de fuga procura `tenant_id`, e `product`/`inventory_item` não o têm. `medidos` ficava em 58 e o AC-1 nunca podia ficar verde | **CONFIRMADO** | Corrigido: as duas sondas atravessam o *link* (`merchant.*`, `variants.product.merchant.*`) e normalizam o `tenant_id` |
| A8 | Os oito casos ISO-19..26 passavam todos por «401 sem credencial» — verdade sobre qualquer rota `/admin/*`, e nada sobre isolamento. A metade «com acesso operador, auditado» do §4.4 não era medida | **CONFIRMADO** | Corrigido: o contentor cria um utilizador de operador (`medusa user`), o guião autentica-se em `/auth/user/emailpass`, e cinco casos medem o que o operador **vê** |
| A9 | ISO-26 não distinguia «a *flag* EE está desligada» de «não há credencial»: sem token, qualquer rota dá 401 | **CONFIRMADO** | Corrigido: a sonda vai **com** o token; um 401 passa a `nao_verificado` |
| A10 | O AC-2 exige que nada publique a porta do Medusa; a espera pelo arranque perguntava por `127.0.0.1:9000` **do anfitrião**. As duas condições são mutuamente exclusivas, e o Medusa nunca podia ser medido | **CONFIRMADO** | Corrigido: a sonda de *health* corre **dentro** da rede do contentor (`docker exec`), e os registos do `db:generate`/`db:migrate` passam a ser anexados ao diagnóstico |
| A11 | A sonda 2 do AC-2 passa quando o DNS falha: `host.docker.internal` não resolve fora do Docker Desktop, o `catch` dá «RECUSADO» e o critério fica verde. Sem controlo positivo | **CONFIRMADO** | Corrigido: a sonda ganha controlo positivo (alcançar a 5432, que **está** publicada) e distingue «recusado» de «não resolveu» |
| A12 | O p95 do AC-8 excluía a espera na fila (`t0` dentro do trabalhador) e a taxa alcançada era calculada, impressa e **não usada**: passou com 15,9/s de 20 oferecidos | **CONFIRMADO** | Corrigido: a latência conta-se desde a submissão, e a taxa alcançada entra na decisão (tolerância de 5%), tal como um limiar de erro |
| A13 | O AC-9 devolvia `PASSA` incondicionalmente: não tem ramo de falha, e a estimativa é uma *string* literal. O §4.5 ramifica nele | **CONFIRMADO** | Corrigido: passa a `nao_verificado` com a estimativa no texto — uma estimativa não é uma medição, e quem a lê decide |
| A14 | Três dos oito casos ISO-11..18 trocavam o que o §4.4 nomeia (carts, encomendas, stock) por sondas de autenticação; e os cenários divergiam entre `iso.py` e `spike.ts`, com **o do TypeScript a vencer em silêncio** | **CONFIRMADO** | Corrigido: cenários alinhados nos dois lados, carts e inventário sondados, encomenda declarada `nao_verificado` com razão, e `medusa._casos` **falha** se os dois lados divergirem |

### Os dois que ficaram como limite declarado, e não como correcção

- **A5 (AC-6).** Implementar a cadência do §6.5 — um *job* a cada 60 s — exigiria
  mais de 60 s de relógio por amostra, e o p99 pede ≥ 100 amostras. Em vez de
  medir a cadência, mede-se o que está em dúvida (o custo de processamento da
  libertação) e **declara-se** que o critério, à letra, não está verificado. É
  a regra do método: quando a leitura divergir da letra, escreve-se a leitura e
  não se marca a caixa.
- **A1, em parte.** O mecanismo que o AC-3 mede do lado do `platform` é um
  `UPDATE ... WHERE quantidade - reservada >= :q`, um único comando, que no
  PostgreSQL **não pode** sobrevender a nenhum grau de concorrência. Com a
  sobreposição agora medida, o verde significa «o mecanismo certo está no lugar
  certo» — não é uma descoberta sobre atomicidade. A medição que podia falhar é
  a do caminho do Medusa, e é a que decide a D3 (§4 do relatório).

---

## 2. Os achados de severidade média

Corrigidos: **M1** e **M2** (excepções largas que liam qualquer erro como
recusa — restringidas a `PoliticaRecusada` e a `SQLSTATE 42501`), **M3**
(o bloco da RLS não tinha controlo positivo — acrescentada uma sonda que
confirma que **com** contexto as linhas aparecem), **M4** (o AC-4 passava com
repetições a receber resposta diferente — passa a exigir as 50 respostas
iguais), **M6** (o AC-7 ficava verde sem ler a árvore instalada e sem olhar ao
**ambiente do contentor**, que é como as *flags* mais facilmente se ligam; e
dava falso vermelho num comentário de fim de linha e em qualquer chave chamada
`policies:`), **M8** (ISO-51..54 passavam com zero sucessos — passam a exigir
que a disputa tenha acontecido), **M9** (o AC-6 herdava reservas de outros
critérios — ganha um SKU próprio e o varredor filtra por ele), **M10** (o
gatilho do grafo cobria só `UPDATE`: um `INSERT ... estado='paga'` entrava em
qualquer estado, e a auto-transição `criada → criada` era aceite e incrementava
a `version`), **M11** (o DDL do spike não aplicava a si próprio a regra da FK
composta que o ISO-58 obrigou a escrever — corrigido nas quatro tabelas
filhas), **M13** (o AC-1 contava ids sem verificar o conjunto — passa a exigir
exactamente ISO-01..60), **M17** (no braço Medusa do AC-3, não conseguir ler a
quantidade produzia «0 acima do stock»), **M18** (o marcador
`DECISAO-PASSO3` — o nó que decide a D3 — nunca era preenchido, em silêncio) e
**M19** (`resultados/` estava versionado contra o que o próprio relatório dizia
— acrescentado ao `.gitignore`, e o relatório é regerado da execução final).

Declarados e não corrigidos, com a razão no relatório: **M5** (no AC-5, as
intenções marcadas `falhada` não contam como órfãs, e a duração medida é o tempo
de corrida da função e não a latência detecção→recuperação do §10.3 — o AC-5
acaba `nao_verificado` por outra razão, e o número reportado diz o que é),
**M7** (ISO-57 e ISO-59 medem «SKU inexistente» e um `CHECK`, não injecção, e
trocam o «ignorado» do §4.4 por «recusado» — fica dito no §6 do relatório que só
o ISO-60 mede o que a coluna pede), **M12** (`a_partir_de` é cobrado como preço
final; é o §7.1 e é do KAM-043, não deste ticket), **M14** (a sonda 3 do AC-2 lê
`registo.py`, que não fala com o Medusa — o cliente está noutro ficheiro),
**M15** (ISO-47..50 correm contra `criarStorageFake()`: a guarda de tenant é
código de produção e é medida, mas o caminho SigV4 do S3 não é exercitado) e
**M16** (a rota `/spike/query-graph` acrescenta superfície sem autenticação ao
sistema medido, e nenhum caso a sonda — **removida**, porque o `spike.ts`
resolve o `QUERY` directamente e não precisa dela).

---

## 3. Os achados de severidade baixa

Corrigidos: a fórmula de percentil estava enviesada para o optimista
(`int(n·p) - 1` em vez de `ceil(n·p) - 1`), o portão de amostras era
inconsistente entre o AC-6 (≥ 100) e o AC-8 (≥ 20) com o mesmo argumento a
aplicar-se aos dois, e as contagens de `resultados.json` misturavam a sonda
extra `ISO-48b` nos totais da matriz.

Registados sem acção, por serem fora do âmbito do KAM-041 e sem AC que os meça:
`transition` não escreve no `events_outbox` (§6.2 pede os dois na mesma
transacção), `extend_reservation` não exige «cobrança com validade
correspondente», `evt_emitir` calcula `agregado_seq` por `max()+1` sob um único
(a forma clássica de perder uma actualização, inalcançável pelos caminhos
actuais), e o `kamba_app` tem `UPDATE` livre sobre `lines_snapshot`, que o §5.4
declara imutável após `aguarda_pagamento` e que nada no esquema impõe. Os dois
últimos vão para o KAM-044 e o EPIC-07.

---

## 4. O que o revisor procurou e **não** encontrou

Vale registar, porque é informação e porque delimita o que esta revisão cobre:

- **Preço vindo do chamador** (regra 4 do §3.2): percorridos os onze métodos da
  porta. Não há caminho por onde um preço entre — `create_order` recebe só
  `(sku, qty)` e resolve o total de `offer_terms` dentro da transacção.
- **Perda de actualização no CAS do `transition`**: em `READ COMMITTED`, dois
  chamadores com a mesma versão esperada serializam no bloqueio da linha e o
  perdedor reavalia o `WHERE` contra a versão nova. Não há forma de perder uma
  actualização por aí.
- **Barreira que não sincroniza**: `ThreadPoolExecutor.map` submete tudo de
  imediato, os participantes existem de facto, e um `BrokenBarrierError`
  propaga-se em vez de ser lido como recusa. O defeito da `tempestade` era *o
  que* ela sincronizava (A3), não *se* sincronizava.
- **`nao_verificado` tratado como verde**: percorridos os três consumidores. Não
  há caminho. O problema era o simétrico — o A13, um critério que não podia
  ficar vermelho.
- **Fuga entre tenants pelos `GRANT`**: `FORCE ROW LEVEL SECURITY` está nas oito
  tabelas com `tenant_id`, `kamba_app` e `kamba_migrator` são `NOBYPASSRLS`, e o
  `INSERT` directo no *outbox* está revogado. Os caminhos encontrados são todos
  **dentro** do próprio tenant.

---

## 5. Controlo de versões

| Versão | Data | Alteração | Autor |
|---|---|---|---|
| 1.0 | 2026-10-27 | Emissão: uma ronda adversarial sobre o harness do KAM-041; 14 altos, 19 médios, 8 baixos, com o estado de cada um. | Equipa KAMBÁ |
