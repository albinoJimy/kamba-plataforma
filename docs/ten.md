# TEN — entitlements, limites e a matriz de estados

| Campo | Valor |
|---|---|
| Documento | `docs/ten.md` |
| Ticket | KAM-009 — TEN: entitlements e limites aplicados por *middleware* |
| Estado | **Parcial, e corrigido por revisão adversarial.** Cobre as duas bibliotecas (`packages/core-ts/src/ten/`, `libs/py-core/src/kamba_core/ten/`), a revisão `0007`, o registo de chaves (`registry/entitlement_keys.schema.json`, `registry/plans.yaml`) e a *suite* do gate 8 (`db/tests_ten/`). Os critérios 3, 4 e 5 **têm medição** (§11), feita contra a `0007` **anterior** à correcção; a `0007` está a ser alterada nesta mesma correcção e os números têm de voltar a correr sobre ela |
| Âmbito | O que decide **se** um tenant pode usar um módulo, **quanto** pode gastar numa chave de limite, e **o que o canal deixa passar**. Fora: facturação da assinatura (KAM-059), provisionamento de entitlements (KAM-091), aplicação em *tools* (KAM-028 usa esta biblioteca) |
| Fontes | `docs/tecnica/01` §7.1 e §7.2; `docs/tecnica/02` §5.2, §6.1, §6.3, §6.5; `docs/tecnica/03` §5.2; `docs/tecnica/04` §4.2; ADR-012, ADR-013, ADR-015, ADR-018; revisão `0007` |

| Aprovação | Nome | Data |
|---|---|---|
| Arquitecto de Plataforma | | |
| Responsável de Segurança | | |

---

## 1. A tese, numa frase

**A regra vive no SQL; as bibliotecas chamam-na.** A aritmética de limites está
inteira em `platform.ten_consumir` e o fuso do período em
`platform.ten_periodo` (revisão `0007`); o critério do entitlement está numa
consulta só, partilhada pelos dois idiomas. Nenhuma linha de TypeScript ou de
Python deste módulo soma, subtrai ou compara um limite.

O bloco do ticket pede «o Python chama a mesma regra SQL». Vale igualmente para
o TypeScript, e pela mesma razão que a revisão `0002` já tinha escrito sobre a
RLS: **duas implementações da mesma aritmética divergem**, e a divergência só
aparece quando o dinheiro já está errado.

```
checkEntitlement ──► SQL_ENTITLEMENT         coluna `permitido`, calculada na base
consumeLimit     ──► platform.ten_consumir   atómico e idempotente por construção
checkCeiling     ──► SQL_TECTO               «este valor cabe?» — e não escreve nada
periodo          ──► platform.ten_periodo    o mês fecha em Africa/Luanda, num sítio só
tenantGate       ──► tabela, em memória      a matriz do `01` §7.2 (ver §4: tem um problema)
```

### 1.1 O que a revisão adversarial mudou

Cinco correcções, e nenhuma é cosmética. O que se segue é o índice; cada uma
está na sua secção.

| # | O que estava errado | Onde se corrigiu |
|---|---|---|
| M3 | O `SQL_PERIODO` não tinha `coalesce`: sem instante devolvia `NULL`, e os dois idiomas tratavam-no de maneira diferente — `None` em silêncio no Python, excepção no TypeScript | §5.1 |
| M4 | A precedência punha `suspenso` à frente de `desligado`: um tenant `suspenso` num canal `desligado` **autorizava enviar** a mensagem estática, por um canal que o §7.2 diz removido | §4.1 |
| M5 | Nada lia o `x-kamba-consumivel` do registo e não havia `checkCeiling`: nada impedia consumir um tecto *por pedido* pela `ten_consumir`, e 6 das 10 chaves não tinham aplicação nenhuma | §5.2 |
| C1 | O *middleware* aceitava a `Idempotency-Key` do cabeçalho **tal como vinha**: era o cliente a escolher o âmbito da desduplicação | §7.3 |
| m6 | Este documento dizia «não verificado» sobre critérios que a *suite* do gate 8 verifica | §11 |

## 2. O que existe, e onde

| Ficheiro | O quê |
|---|---|
| `packages/core-ts/src/ten/consultas.ts` | As **quatro** consultas. O SQL, sem o código à volta |
| `packages/core-ts/src/ten/entitlements.ts` | `checkEntitlement`, `consumeLimit`, `checkCeiling`, `periodo`, `CacheDeEntitlements`, a tabela de espécies das chaves, a derivação da chave de idempotência, os códigos de erro |
| `packages/core-ts/src/ten/estados.ts` | `tenantGate`, os regimes e a matriz |
| `packages/core-ts/src/ten/metricas.ts` | `ten_limit_denied_total{key}`, `ten_entitlement_denied_total{modulo}` |
| `packages/core-ts/src/ten/middleware.ts` | `guardaHttp` — `403` e `429`, sem *framework* |
| `packages/core-ts/src/ten/index.ts` | A entrada. Importa-se por `@kamba/core-ts/ten` |
| `libs/py-core/src/kamba_core/ten/*.py` | O espelho, mais o `hook.py` para a ToolLayer |
| `db/migrations/versions/0007_ten_uso_e_limites.py` | `tenant_usage`, `usage_ledger`, `ten_consumir`, `ten_periodo`, RLS e privilégios |

O módulo **não** é re-exportado pelo `src/index.ts` da raiz nem pelo
`kamba_core/__init__.py`: esses levam só o que todos os serviços precisam.
Importa-se pelo caminho completo (`@kamba/core-ts/ten`,
`from kamba_core.ten import …`).

Nenhum dos dois lados importa um controlador de base de dados. O cliente é
injectado, como no `eventos/consumo`; o `pyproject.toml` do `py-core` continua
com `dependencies = []`.

## 3. Entitlement — a decisão está no SQL

```sql
  SELECT t.estado AS estado_tenant,
         (e.tenant_id IS NOT NULL) AS tem_linha,
         coalesce(e.ativo, false) AS ativo,
         (    t.estado <> ALL (ARRAY['onboarding', 'suspenso', 'encerrado'])
          AND coalesce(e.ativo, false)) AS permitido
    FROM (SELECT id, estado
            FROM platform.tenants
           WHERE id = $1 AND deleted_at IS NULL) AS t
    LEFT JOIN platform.entitlements AS e
           ON e.tenant_id = t.id AND e.modulo = $2
```

A coluna `permitido` **é** o critério 2 do bloco, escrito uma vez. As
bibliotecas lêem-na; não a recalculam. A lista dos três estados que negam não
existe em TypeScript nem em Python, e há um teste que falha se alguém a
escrever lá.

**Zero linhas nega, e é o caso que importa.** A política `tenant_iso` de
`platform.tenants` é `id = app.tenant_id`: com o contexto de outro tenant a
consulta devolve **vazio**, e não erro. Quem lê trata o vazio como negado.

Quatro motivos distinguíveis, para quem precisa de explicar a recusa:
`sem_tenant` (zero linhas), `sem_entitlement` (não há linha para o módulo),
`entitlement_inactivo` (`ativo = false`) e `estado_do_tenant`. O `tem_linha`
existe só para distinguir os dois do meio — sem ele, «falta provisionamento»
(KAM-091) e «alguém desligou o módulo» eram o mesmo `false`.

## 4. `tenantGate` — a matriz do `01` §7.2 tem um problema

**Isto é o achado mais importante deste documento.**

A tabela do §7.2 tem uma coluna chamada «Estado do tenant/canal» e funde dois
domínios:

| Domínio | Estados | Fonte |
|---|---|---|
| Tenant | `onboarding`, `ativo`, `restrito`, `suspenso`, `encerrado` (5) | `docs/tecnica/03` §5.2, revisão `0001` |
| Canal | `pendente`, `ativo`, `restrito`, `desligado`, `suspenso`, `encerrado` (6) | `docs/tecnica/01` §7.1 |

A tabela tem seis linhas porque **junta** `onboarding` com `pendente` — que são
de domínios diferentes — e acrescenta `desligado`, que **só** existe no canal. E
o `ChannelContext` que o mesmo §7.2 devolve carrega os dois campos:
`estado_tenant` **e** `estado_canal`.

Consequência: o `tenantGate(estado, acção)` de **um** parâmetro, como o critério
6 o escreve, não exprime a matriz. Um tenant `ativo` com um canal `desligado`
não tem célula nenhuma; um tenant `suspenso` com um canal `ativo` tem duas.

### 4.1 O que esta implementação faz

Recebe os **dois** estados e reduz-os a um **regime**, que é a linha da tabela
que se aplica: o mais restritivo dos dois.

```
desligado > encerrado > suspenso > pendente > restrito > ativo
```

A regra em duas frases, que decidem a ordem toda:

1. **`desligado` ganha de tudo, porque não é um estado de política: é uma
   afirmação sobre o TRANSPORTE.** As outras cinco linhas dizem o que a
   plataforma *autoriza*; esta diz que o caminho técnico até ao público **não
   existe**. Nenhum estado de política faz reaparecer um transporte removido.
2. **As outras cinco ordenam-se do mais restritivo para o menos.**

| Degrau | Fundamento |
|---|---|
| `desligado` primeiro | «Nenhuma entrada chega (coexistência removida)» / saída «Nenhuma». Não é uma permissão que se possa comparar com outra: é a ausência do canal |
| `encerrado` a seguir | É o único terminal nas duas máquinas de estado, e a linha é «Registar e descartar». De um estado do qual não se sai não se passa por um do qual se saia |
| `suspenso` depois | A nota é «Decisão T&S ou falta de pagamento»: a única das linhas de política com causa externa. Passar-lhe à frente por o outro domínio estar `ativo` seria continuar a servir quem a Meta ou a cobrança mandaram parar |
| `pendente` antes de `restrito` | `pendente` permite registar e a mensagem de teste («não responder ao público»); `restrito` permite conversar dentro da janela |
| `restrito` antes de `ativo` | A única relação de ordem que a tabela torna óbvia |

> **M4 — a ordem anterior estava errada, e mediu-se.** A primeira versão tinha
> `encerrado > suspenso > desligado > …`, com o argumento de que `suspenso` é
> de causa externa e não se lhe passa à frente. Consequência: tenant
> `suspenso` + canal `desligado` caía no regime `suspenso`, e o *gate*
> **autorizava** a `mensagem_estatica` — um envio por um canal que o §7.2 diz
> removido. O argumento comparava duas coisas que não se comparam: `suspenso`
> responde «a plataforma deixa?» e `desligado` responde «há por onde?».
>
> **Uma consequência aceite de olhos abertos:** com `desligado` à cabeça, um
> tenant `encerrado` sobre um canal `desligado` também **não** regista a
> entrada, embora a linha `encerrado` diga «Registar e descartar». É o certo
> pela mesma frase: se o canal está removido não chega entrada nenhuma, e a
> linha `desligado` já negava `registar_entrada` sozinha.

> **A ordem continua a ser uma PROPOSTA deste ticket.** Não há documento que a
> escreva, nem sequer que admita que os dois domínios se cruzam. **A decisão
> devolve-se ao dono do `docs/tecnica/01` §7.2.** O que aqui se faz é não
> deixar o cruzamento por resolver em silêncio, que é o que um *gate* de um
> parâmetro faria.

A matriz passou a estar coberta **inteira** nos dois idiomas: 5 estados de
tenant × 6 de canal × 7 acções = **210 casos**, cada um contra o regime do par
e a célula escritos à mão no teste (e não calculados com a mesma regra que
verificam). Mais a propriedade que a correcção garante, por extenso: *nenhum*
par com o canal `desligado` autoriza uma saída.

### 4.2 A matriz, seis regimes por sete acções

| Regime | `registar_entrada` | `processar_entrada` | `responder_sessao` | `tmpl_utilidade` | `tmpl_marketing` | `mensagem_estatica` | `mensagem_de_teste` |
|---|---|---|---|---|---|---|---|
| `pendente` | ✔ | ✘ | ✘ | ✘ | ✘ | ✘ | ✔ |
| `ativo` | ✔ | ✔ | ✔ | ✔ | ✔ | ✔ | ✔ |
| `restrito` | ✔ | ✔ | ✔ | ✘ | ✘ | ✔ | ✘ |
| `desligado` | ✘ | ✘ | ✘ | ✘ | ✘ | ✘ | ✘ |
| `suspenso` | ✔ | ✘ | ✘ | ✘ | ✘ | ✔ | ✘ |
| `encerrado` | ✔ | ✘ | ✘ | ✘ | ✘ | ✘ | ✘ |

Onde o §7.2 é explícito, a célula é a dele. Quatro células que ele **não**
escreve, e o que se fez com elas:

1. **`restrito` × `tmpl_utilidade` → nega.** «Só respostas dentro da janela; sem
   templates *marketing*» lê-se de duas maneiras. A escolhida é a fechada: um
   *template* é o que se manda fora da janela, pelo que «só respostas dentro da
   janela» exclui todos, e a segunda metade da frase reforça em vez de abrir uma
   excepção. **A leitura contrária tem um argumento de negócio sério** — um aviso
   de encomenda ou de pagamento é utilidade, e um tenant apenas limitado por
   qualidade perde-o. **Devolvida ao dono do `01` §7.2.**
2. **`desligado` × `registar_entrada` → nega.** A tabela descreve um *facto*
   («nenhuma entrada chega»), não uma permissão. Se mesmo assim chegar uma,
   chegou por um caminho que já não devia existir.
3. **`restrito` × `mensagem_estatica` → permite.** É uma resposta dentro da
   janela, e essas estão permitidas na linha.
4. **`restrito`/`suspenso`/`encerrado` × `mensagem_de_teste` → nega.** A mensagem
   de teste pertence ao *onboarding*.

O «uma vez por contacto/24 h» da célula de `suspenso` **não** se decide aqui:
esta função responde «pode», não «quantas vezes». A contagem é de quem envia
(`01` §8).

## 5. Consumo de limites — atómico porque a função o é

```
consumeLimit(bd, tenant, chave, n, idempotencyKey, {limite?, agora?, modulo?})
  → SELECT aceite, valor, repetido, limite
      FROM platform.ten_consumir($1, $2, $3, $4, $5, coalesce($6, now()))
```

Uma chamada, uma transacção, **sem leitura prévia**: entre um `SELECT` e um
`INSERT` cabe a chamada repetida inteira, e é por isso que a `0007` escreve a
chave de idempotência antes de contar. Os critérios 3 e 4 (1 000 paralelas
contra 100; dez repetições, uso = 1) são propriedades do `ON CONFLICT … WHERE
valor + n <= limite` e da chave única de `usage_ledger`, e provam-se contra um
PostgreSQL real no gate 8 — **não** nas baterias de unidade, que correm sobre
uma base falsa.

Três leituras do resultado que não são óbvias:

| Resposta da `0007` | Significado | O que a biblioteca faz |
|---|---|---|
| `aceite = true, repetido = true` | Repetição de um consumo já aceite | Aceita. Não consome, não conta |
| `aceite = false, limite` não nulo | O tecto não chega | Nega. `ten_limit_denied_total{key}` |
| `aceite = false, limite = NULL` | **Nenhum entitlement activo declara a chave** | Nega como *entitlement*, não como limite: `403`, não `429` — não há mês nenhum que crie o entitlement em falta |

O `limite` opcional é o tecto de quem chama e só **desce** (a `0007` faz
`least` com o do plano): serve um tecto de confiança (`EPIC-09`) mais apertado,
nunca um mais largo.

Os `bigint` chegam como texto do lado `pg` e como `int` do lado `pg8000`. Os
dois passam pela mesma regra, e o que não seja inteiro exacto **levanta** em vez
de ser arredondado: um tecto de dinheiro arredondado é dinheiro errado
(`specs/01` §6, princípio 4).

### 5.1 Os dois `coalesce`, e porque é que faltava um

O `SQL_CONSUMIR` sempre teve `coalesce($6, now())`; o `SQL_PERIODO` era
`platform.ten_periodo($1)` e **não tinha**. Consequência medida: `periodo(bd)`
sem instante mandava `NULL` à função e recebia `NULL` de volta — e aí os dois
idiomas divergiam em silêncio, o Python a devolver `None` e o TypeScript a
levantar. Dois módulos que declaravam **uma** divergência tinham uma segunda,
não declarada, e estavam **os dois errados**.

A razão do `coalesce` é a mesma nos dois: as funções da `0007` têm o instante
com `DEFAULT now()`, e **um argumento nomeado ausente não se exprime numa
chamada posicional**. Quem passa a lista toda tem de passar alguma coisa, e
`NULL` não é um instante. Agora os dois têm, e há teste nos dois idiomas para
os dois caminhos (com instante e sem).

### 5.2 Nem todas as chaves se consomem — e o registo já o dizia

**Este é o achado de desenho da revisão.** As dez chaves de
`registry/entitlement_keys.schema.json` são de três espécies, e o registo
declara-as em `x-kamba-categoria` e `x-kamba-consumivel`:

| Espécie | Chaves | Pergunta | Função |
|---|---|---|---|
| `contador_por_periodo` (5) | `msgs_ai_mes`, `marcacoes_mes`, `imagens_mes`, `posts_mes`, `orcamentos_mes` | «quanto já gastei?» | `consumeLimit` → `ten_consumir` |
| `tecto_por_pedido` (3) | `valor_max_pedido_minor`, `manual_max_minor`, `manual_dupla_acima_minor` | «este valor cabe?» | `checkCeiling` → `SQL_TECTO` |
| `tecto_por_janela` (2) | `manual_daily_max_minor`, `manual_max_por_contacto_24h` | «o agregado da janela cabe?» | **nenhuma** — ver §5.4 |

O `x-kamba-consumivel` existia e **nada o lia**. Nada impedia
`consumeLimit(tenant, "valor_max_pedido_minor", 5 000 000, …)`: cria linha em
`platform.tenant_usage` para um tecto que não tem contador e, com o plano
`free` (`valor_max_pedido_minor: 5000000`), o **primeiro** pedido de 50 000 Kz
gasta o tecto inteiro do mês. Foi medido.

O que mudou:

1. a espécie de cada chave é agora um **facto do registo** dentro das
   bibliotecas (`CHAVES_DE_LIMITE`), e há um teste em **cada** idioma que lê o
   `registry/entitlement_keys.schema.json` e confronta nome, categoria e
   `x-kamba-consumivel` chave a chave — mais um terceiro que confronta as duas
   tabelas entre si;
2. `consumeLimit` **levanta** para uma chave não consumível, e `checkCeiling`
   **levanta** para uma consumível. Nenhuma das duas escolhe o outro caminho em
   tempo de execução: um erro de programação resolve-se a recusar;
3. uma chave que não esteja no registo levanta nas duas. O registo tem
   `additionalProperties: false`, logo uma chave fora dele nunca poderá estar
   em `entitlements.limites` — consumi-la era criar uso contra um tecto que não
   pode existir.

> **Porque é que a tabela está no código e não se lê o ficheiro.** Nenhuma das
> duas bibliotecas faz IO nem importa controlador (`dependencies = []`), e as
> duas publicam-se sem a árvore do repositório ao lado. O que as mantém
> honestas não é uma promessa: são os três testes acima. É o mesmo padrão da
> matriz do §7.2 e do SQL — escrito por extenso, confrontado por uma máquina.

### 5.3 `checkCeiling` — a pergunta que faltava

```
checkCeiling(bd, tenant, chave, valor, {modulo?, metricas?})
  → WITH activos AS (SELECT limites FROM platform.entitlements
                      WHERE tenant_id = $1 AND ativo)
    SELECT min((limites ->> $2)::bigint) AS tecto FROM activos
```

| | |
|---|---|
| Tecto efectivo | O **mínimo** entre os entitlements activos que declaram a chave — a mesma regra que a `ten_consumir` usa, escrita do mesmo modo. Não há um `min()` em Python nem em JavaScript |
| Escreve | **Nada.** Sem `tenant_usage`, sem `usage_ledger`, sem chave de idempotência: não há nada para repetir porque nada muda |
| Sem linha activa que declare a chave | **Nega** (critério 2). O `min` de um conjunto vazio é `NULL`, e `NULL` não quer dizer «sem limite». A RLS de outro tenant dá o mesmo vazio, e lê-se como negado |
| `manual_dupla_acima_minor` | O único em que `cabe = false` **não** é uma recusa: o registo escreve-o, e acima do limiar o pedido exige o segundo confirmador (`04` §4.2 M-5). A função devolve o facto; quem chama decide |

O `WITH` não é estilo: com o `min(...)` no `SELECT` de topo o `$2` aparecia no
texto antes do `$1`, e o espelho em Python é posicional. E o `WHERE limites ?
$2` da `0007` não está cá de propósito — `min` ignora `NULL`, o resultado é o
mesmo, e sem ele cada marcador aparece **uma** vez (um `$2` repetido viraria
dois `%s` na DB-API, e as duas consultas deixariam de ter a mesma lista de
argumentos).

### 5.4 As duas chaves que ficam sem caminho de aplicação, e porquê

`manual_daily_max_minor` e `manual_max_por_contacto_24h` **não têm aplicação
neste ticket**, e as bibliotecas dizem-no a levantar em vez de responderem mal.

A pergunta delas é «a soma (ou a contagem) da janela **mais** este valor
cabe?», e o agregado da janela não está em `platform.tenant_usage`: a chave
dessa tabela é `(tenant_id, chave_limite, periodo)`, com `periodo` mensal por
`CHECK` e sem dimensão de contacto, e a janela das 24 h é móvel. O agregado
calcula-se de `manual_confirmations` (`docs/tecnica/04` §4.2 M-6), que este
ticket não constrói. Comparar um valor solto com um tecto diário daria «cabe» a
cada pedido até ao fim do dia — a mesma classe de defeito que o
`x-kamba-consumivel` existe para fechar.

**Ficam com caminho de aplicação 8 das 10 chaves**: as 5 consumíveis pela
`consumeLimit`, e as 3 de tecto por pedido pela `checkCeiling`.

## 6. Cache — e a razão por que a visibilidade é só o TTL

| | |
|---|---|
| Chave | `<uuid canónico>\0<modulo>` — o UUID passa pelo `normalizarTenant`, e nem um UUID nem um módulo podem conter `\0` |
| TTL | 60 000 ms (**proposta**; o critério 6 pede «≤ 60 s») |
| Relógio | Monotónico (`performance.now()` / `time.monotonic()`): um salto de NTP não prolonga uma entrada |
| O que **não** entra | O consumo. Um contador em cache é um contador errado |

**Não há evento `entitlement.*` no catálogo.** O `01` §7.2 invalida a cache do
CHR por evento `channel.updated`; aqui não há equivalente. Logo a única coisa
que torna uma alteração visível é a expiração, e **o limite superior do atraso é
exactamente o TTL**. Duas consequências que quem usa isto tem de saber:

1. um entitlement **retirado** continua a permitir até 60 s;
2. não há forma de o apressar a não ser chamar `invalidar(tenant)`.

Criar o evento `entitlement.updated` é trabalho do catálogo (KAM-007) e do
provisionamento (KAM-091). Fica **proposto aqui, não feito**.

O critério 6 exige ainda que a cache **nunca** devolva dados de outro tenant.
Há teste cruzado nos dois idiomas: guarda-se A, lê-se B, e B vai à base.

**Guarda-se também o que negou.** O caso a conhecer é o `sem_tenant`: zero
linhas tanto significa «este tenant não existe» como «este pedido correu com o
contexto de RLS de outro tenant», e no segundo caso a recusa guardada é
consequência de um defeito de quem chama e sobrevive-lhe até 60 s. Guarda-se na
mesma — o sentido do erro é o seguro (nega-se de mais, nunca de menos), e não
guardar deixava um tenant inexistente a bater na base a cada pedido.

## 7. *Middleware* HTTP e *hook* da ToolLayer

O TypeScript tem `guardaHttp`, que devolve `null` («siga») ou `{estado, corpo,
cabecalhos}`. Não depende de nenhuma *framework*: um núcleo partilhado que
importa Hono obriga a ele todos os serviços, incluindo os que não servem HTTP.

O Python tem `hook_de_tool`, que é o passo 2 do pipeline de `invoke` do `02`
§6.1 e devolve `None` ou um `ErroDeTool` do §6.5.

Nos dois, a **ordem** são agora três passos, e cada um protege o seguinte:

1. **`checkEntitlement`** — quem não tem o módulo activo recebe `403` e não
   consome nada. Consumir primeiro gastava o tecto de quem nem sequer podia
   entrar.
2. **`checkCeiling`** — um pedido que não cabe no tecto *por pedido* é recusado
   e **também** não consome nada. Esta ordem é a correcção do M5: a verificação
   do tecto não escreve, e descobrir que um pedido de 50 000 Kz não passa
   *depois* de já ter gasto o balde mensal é pagar duas vezes pelo mesmo erro.
3. **`consumeLimit`** — só aqui se escreve, e só para baldes por período.

Há um teste de paridade que confirma a ordem dos três lendo as duas fontes.
No HTTP o tecto entra por `tecto: {chave, valor}`; na ToolLayer por
`tecto_chave`/`tecto_valor`, e dar só um dos dois **levanta**.

### 7.1 O `tenant_id` vem do contexto (critério 7)

O `guardaHttp` recebe o `Pedido` e o `ContextoDoPedido` como argumentos
**separados**, e lê do pedido **uma** coisa: o cabeçalho de idempotência. O
tenant sai do contexto, que é montado pelo CHR («o único sítio onde o
`tenant_id` nasce», `01` §7.2) ou pela autenticação do serviço.

O `hook_de_tool` recebe o `ToolContext` e **nunca** os `args` da *tool* — «o
modelo nunca vê nem fornece `tenant_id`» (`02` §6.1), e o `02` §5.2 já o impõe
na validação de arranque.

Duas provas, nenhuma em prosa:

* um pedido hostil com `tenant_id` na *query*, em `x-tenant-id`, em
  `x-merchant-id` e no corpo — e o SQL corre com o tenant do contexto;
* um teste que **lê a fonte** do `middleware.ts` e exige que a única leitura de
  `pedido.` em todo o ficheiro seja a de `cabecalhos`.

### 7.2 Os códigos de erro — todos em proposta, de maneiras diferentes

| Código | Onde | Estado |
|---|---|---|
| `LIMIT_EXCEEDED` | `docs/tecnica/02` §6.5 (tabela de erros da ToolLayer) | **Escrito em documento técnico**, mas **sem estado HTTP associado**: o §6.5 é sobre erros de *tool*. O `429` é proposta do ticket |
| `ENTITLEMENT_DENIED` | `docs/tecnica/02` §6.5 | Escrito. É o nome que a ToolLayer usa, e é o que o `hook_de_tool` devolve |
| `ENTITLEMENT_DISABLED` | Critério 2 do KAM-009, marcado «em proposta» | **Não está em documento nenhum**, e **não é o mesmo nome que o §6.5 escreve para a mesma situação**. É o que o HTTP devolve, por ser o que o critério pede |
| `403` / `429` | — | Proposta deste ticket |
| `403 LIMIT_EXCEEDED` (tecto por pedido) | — | Proposta desta correcção. O **código** continua a ser o do §6.5 — não se inventa um quarto nome —, mas o estado é `403` e não `429`: um `429` diz «tente mais tarde», e um balde mensal reabre mesmo, no primeiro dia do mês. Um tecto *por pedido* não reabre nunca; o mesmo pedido com o mesmo valor será recusado em Janeiro como foi em Dezembro |

As bibliotecas mantêm os **dois** nomes do entitlement, cada um no seu caminho,
e há um teste que falha se alguém os unificar. **A decisão de os unificar
devolve-se ao dono do `docs/tecnica/02` §6.5**: escolher um dos dois aqui, em
silêncio, era fechar por omissão uma divergência entre um ticket e um documento.

Um pedido que precise de consumir e não traga chave de idempotência **levanta**
em vez de virar um código novo: acrescentar um `400 IDEMPOTENCY_KEY_REQUIRED`
ao vocabulário do §6.5 sem documento nenhum é outra decisão de quem o detém. O
mesmo vale para o **`KA002`** da `0007` — a mesma chave de idempotência com
outra quantidade: é um conflito do pedido e não uma resposta de negócio, e
sobe como `ConflitoDeIdempotencia` / `ConflitoDeIdempotenciaError` em vez de
virar um `409` que nenhum documento escreve.

### 7.3 A chave de idempotência é **derivada** (C1)

O `middleware.ts` aceitava a `Idempotency-Key` do cabeçalho **tal como vinha**.
A chave de idempotência decide o **âmbito da desduplicação**, e esse âmbito é
do servidor: aceitá-la assim era deixar o cliente escolher o que conta como «o
mesmo pedido» — um cliente que mandasse uma constante tornava os limites
ilimitados. A chave primária nova de `usage_ledger` (`(tenant_id,
chave_limite, idempotency_key)`) contém o estrago a uma chave de limite, mas
não muda quem escolhe.

Agora, nos dois idiomas:

```
chave efectiva = sha256("ten.v1" \0 tenant \0 modulo \0 chave_limite \0 a-do-cliente)
```

O que o cliente manda é **um componente**, o último. Os três primeiros vêm do
contexto do servidor: duas chamadas de módulos diferentes com o mesmo cabeçalho
deixam de ser a mesma chave, e um cliente deixa de poder construir a chave de
outro. No Python o componente final é a chave do `02` §6.3,
`sha256(tenant_id | contact_id | tool | cart_id)`, que quem chama já traz.

> **A quantidade NÃO entra na derivação, e é deliberado.** A `0007` levanta
> `KA002` quando a mesma `(tenant, chave_limite, idempotency_key)` volta com
> uma quantidade diferente: é a impressão digital que apanha o cliente que
> repete uma chave com outro corpo. Pondo a quantidade **dentro** da chave, o
> mesmo cabeçalho com outra quantidade passava a ser outra chave — um consumo
> novo, aceite em silêncio — e o `KA002` nunca disparava para quem usa esta
> derivação. Dos dois mecanismos, só um **denuncia** o defeito em vez de o
> absorver; esse fica, e a quantidade fica de fora para o deixar trabalhar.

A derivação é determinística e idêntica nos dois idiomas: há um vector fixo
(`sha256("ten.v1"\0<tenant A>\0vendedor\0msgs_ai_mes\0req-1")`) escrito nos
dois ficheiros de teste, e um teste de paridade que confirma que é o mesmo nos
dois — que é como se comparam dois *digests* sem correr os dois interpretadores
no mesmo processo.

## 8. Métricas

```
ten_limit_denied_total{key}            counter
ten_entitlement_denied_total{modulo}   counter
```

A forma é a do `eventos/metricas.ts` — um `Map` de números, sem dependências,
com `exposicao()` no formato do Prometheus. A biblioteca não abre portas.

**O `tenant_id` não entra em etiqueta nenhuma**, e a regra é imposta pela
**gramática** (`^[a-z][a-z0-9_]{1,62}$`) e não por uma lista de nomes proibidos:
um UUID canónico tem hífenes e não casa. Uma lista de proibidos protege contra
os nomes de que alguém se lembrou; a gramática protege contra a forma. O X-11 do
gate 6 varre os registos à procura de identificadores, e uma etiqueta é tão
legível como uma linha de registo.

As etiquetas **não** são lista fechada, ao contrário dos `DESFECHOS` do
`eventos/metricas.ts`: as chaves de limite crescem com o registo e os módulos
com as verticais. O que substitui a lista é o par gramática + **tecto** de
séries (`MAXIMO_DE_SERIES = 64`), que é o que o `medirPorTipo` já faz para o
`evt_dlq_open{tipo}`.

Uma recusa servida pela cache **conta na mesma**: o painel mostra quantos
acessos foram negados, não quantas vezes a base foi consultada.

## 9. Cobertura e o estrato `critico`

O DoD pede «≥ 90% no consumo de limites». Os ficheiros caíam no estrato
`restante` (`packages/*/src/**`, `libs/*/src/**`), a 75%, e o estrato `critico` é
o único mecanismo que impõe 90%. Acrescentou-se `*/ten/*` ao `critico`,
**acima** do bloco `restante` — a classificação é pelo primeiro padrão que bate,
na ordem escrita. O precedente explicado é o `*/logger/*` do KAM-068.

| | |
|---|---|
| Padrão | `*/ten/*` — forma `*/<pasta>/*`, que é a que funciona com `fnmatch` (o `*` atravessa barras) |
| Ficheiros que traz | 6 em TypeScript, 6 em Python |
| Medido (emissão 1.0) | **100% de linhas em todos os doze** (1 703/1 703) |
| Medido (1.1, só Python) | **100% de linhas e 100% de ramos** nos seis ficheiros de `kamba_core/ten/` — 389 instruções, 138 ramos, 0 por cobrir (`coverage run --branch`, suite completa do `py-core`) |
| Efeito no estrato | `critico` sobe de **95%** para **96%** — o padrão traz cobertura, não a baixa |
| Dois revisores | O cabeçalho do `ci/thresholds.yaml` exige-os para qualquer alteração ao ficheiro. **A caixa não está marcada** |

> **O lado TypeScript da 1.1 não foi medido**: não há `node` nem `pnpm` no
> ambiente em que esta correcção foi escrita, pelo que `pnpm test` e
> `pnpm typecheck` do `packages/core-ts` **não correram**. Os seis ficheiros de
> `src/ten/` ganharam código novo (`checkCeiling`, `CHAVES_DE_LIMITE`,
> `derivarChaveDeIdempotencia`, `sqlstateDe`, as três classes de erro) e a
> bateria ganhou os testes correspondentes, mas o número de cobertura do lado
> TypeScript tem de voltar a ser medido no CI antes de se repetir o «100% nos
> doze».

## 10. O que fica por decidir

| # | Decisão | Estado |
|---|---|---|
| 1 | **A ordem de precedência entre os dois domínios de estado** (§4.1) não está em documento nenhum | **Devolvida** ao dono do `docs/tecnica/01` §7.2. Proposta implementada e declarada |
| 2 | **`restrito` deixa sair *templates* de utilidade?** (§4.2, ponto 1) O §7.2 lê-se das duas maneiras | **Devolvida** ao dono do `01` §7.2. Até lá nega |
| 3 | **`ENTITLEMENT_DISABLED` ou `ENTITLEMENT_DENIED`** (§7.2): o ticket e o documento dão nomes diferentes à mesma situação | **Devolvida** ao dono do `docs/tecnica/02` §6.5 |
| 4 | **Os estados HTTP `403` e `429`** não estão em documento nenhum | Proposta do ticket, registada |
| 5 | **Não há evento `entitlement.*`** (§6): a visibilidade é só por TTL | Registada. Nasce no catálogo (KAM-007) com o provisionamento (KAM-091) |
| 6 | **A assinatura do critério 6 é de um parâmetro** e a implementada é de três | Declarada. É consequência directa de §4 |
| 7 | **Quem recolhe as métricas.** Existem em memória; não há Prometheus no repositório | Sem ticket próprio: é o KAM-080, como em `docs/eventos.md` §11 |
| 8 | **O limiar de 60 s do TTL** é proposta, como todos os limiares do conjunto | A calibrar no Piloto |
| 9 | **Quem altera `tenants.plano`** — a decisão herdada do KAM-003/KAM-004 | Resolvida na revisão `0007`, que retira o `UPDATE (plano)` e o `UPDATE (limites, ativo)` à `kamba_app`. Não é desta parte do ticket |
| 10 | **A regra do mínimo do tecto está escrita em dois sítios**: na `ten_consumir` (`min((e.limites ->> p_chave)::bigint)`) e no `SQL_TECTO` das bibliotecas | **Proposta ao dono da revisão**: uma função `platform.ten_tecto(p_tenant, p_chave)` na `0007`, chamada pela `ten_consumir` e pelo `SQL_TECTO`, punha a regra num sítio só — que é o princípio de todo este módulo. Não se fez aqui porque a `0007` é da outra metade desta correcção |
| 11 | **`manual_daily_max_minor` e `manual_max_por_contacto_24h` não têm caminho de aplicação** (§5.4) | Registada. Nascem com `manual_confirmations` (`docs/tecnica/04` §4.2 M-6), que não é deste ticket. Até lá as bibliotecas **levantam** em vez de responder mal |
| 12 | **O estado `403` para um tecto por pedido excedido** (§7.2) | Proposta desta correcção, registada. O código não muda (`LIMIT_EXCEEDED`); só o estado |

## 11. O estado da verificação, critério a critério

A versão 1.0 deste documento dizia «não verificados» sobre os critérios 3, 4 e
5. **Estava errado**: a *suite* `db/tests_ten/` verifica-os contra um
PostgreSQL real, e o *commit* `92eb2f4` traz os números. O que se segue separa
o que tem medição do que não tem, e diz de cada um **contra que revisão** foi
medido.

### 11.1 O que tem medição

| Critério | Medido | Onde |
|---|---|---|
| 3 — concorrência | **1 000 chamadas paralelas de 1 unidade contra um limite de 100: 100 aceites, 900 negadas, contador = 100, livro com 100 linhas, em 56,6 s** | `db/tests_ten/`, *commit* `92eb2f4` |
| 4 — idempotência | **Dez repetições da mesma chave: uso = 1** | idem |
| 5 — fronteira de mês | **`2026-11-30T23:59:59+01:00` → Novembro; `2026-12-01T00:00:00+01:00` → Dezembro; e `2026-11-30T23:30:00Z` → Dezembro em `Africa/Luanda` e Novembro em UTC** (que é o teste que distingue o fuso de uma coincidência) | idem |

> **A ressalva que faz destes números uma verificação honesta:** foram medidos
> contra a `0007` **como estava em `92eb2f4`**. Esta correcção altera a
> revisão — chave primária de `usage_ledger` passa a `(tenant_id,
> chave_limite, idempotency_key)`, `KA002` novo, guarda de `p_agora`, *trigger*
> `BEFORE UPDATE` *append-only* em `tenant_usage`, e `kamba_app` perde
> `INSERT` em `entitlements` e `UPDATE (estado)` em `tenants`. **Os três
> números têm de voltar a correr sobre a revisão corrigida** antes de os
> critérios se darem por fechados; é o gate 8 que o faz.

Também tem medição, e é desta metade:

| Afirmação | Medido |
|---|---|
| A matriz do §7.2, **completa** | 210 casos (5 × 6 × 7) em cada idioma, contra o regime e a célula escritos à mão no teste |
| O SQL das quatro consultas é o mesmo nos dois idiomas | Carácter a carácter, depois de reescrever `$n` → `%s` (`TestParidadeDoTypeScript`) |
| A espécie das dez chaves é a do registo | Um teste em cada idioma lê `registry/entitlement_keys.schema.json`; um terceiro confronta as duas tabelas entre si |
| A derivação da chave de idempotência é a mesma nos dois | Vector fixo escrito nos dois ficheiros de teste, confrontado por um teste de paridade |
| A tradução do `KA002` | Testada nos dois idiomas sem base de dados: o que se verifica é a leitura do `SQLSTATE` e o erro que sai |
| Cobertura do lado Python | 100% de linhas **e de ramos** nos seis ficheiros (§9) |

### 11.2 O que **continua NÃO VERIFICADO**

| # | Afirmação | Porquê, e como se validava |
|---|---|---|
| 1 | **Os critérios 3, 4 e 5 sobre a `0007` corrigida** | Ver a ressalva de §11.1. **Forma de validar:** correr `db/tests_ten/` no gate 8 contra a revisão depois da correcção, e repor aqui os números novos |
| 2 | **O lado TypeScript desta correcção** — `pnpm test` e `pnpm typecheck` | Não há `node` nem `pnpm` no ambiente em que foi escrita. O Python corre (133 testes de `test_ten.py`, 527 na suite do `py-core`) e os testes de paridade lêem a **fonte** do TypeScript, o que apanha divergências de texto mas **não** erros de tipos nem de execução. **Forma de validar:** `pnpm --filter @kamba/core-ts test` e `typecheck` no CI |
| 3 | «Não existe evento `entitlement.*` no catálogo» | Verificado por leitura do catálogo e das subscrições de `registry/*.yaml` em `docs/tecnica/02` §5.1. Não há *gate* que o imponha: se alguém acrescentar o evento, nada aqui dá por isso. **Forma de validar:** uma regra no gate 3b sobre o catálogo |
| 4 | O comportamento da RLS perante um contexto de outro tenant | A biblioteca trata zero linhas como negado; **que a RLS devolva zero linhas** é da `0002`. **Forma de validar:** gate 8, `db/tests_isolamento/` |
| 5 | O `critico` agregado a 96% | Medido com dois relatórios LCOV, não com a corrida completa do `make ci-4`, e o lado TypeScript mudou desde então. **Forma de validar:** `make ci-4` completo |
| 6 | Valores de limite por plano | Fora de âmbito e **sem fonte** (H6 por validar; `registry/plans.yaml` marca cada plano `hipotese_nao_validada`). Nenhum valor, nenhum preço, é escrito em lado nenhum deste módulo |
| 7 | A unidade de `manual_max_por_contacto_24h` | O próprio registo a marca `x-kamba-nao-verificado`: o `04` §4.2 M-3 não diz se é contagem ou dinheiro. **Forma de validar:** uma frase no `04`, ou o nome passa a acabar em `_minor` |

> **O que mudou face à 1.0:** o item 5 da lista antiga — «esta biblioteca não
> conhece os nomes das chaves» — **deixou de ser verdade e sai da lista**. As
> bibliotecas conhecem agora as dez, porque a espécie de cada uma decide qual
> das duas funções a serve (§5.2). Os nomes continuam a ser os do registo e do
> dicionário §3.2, e quem os fecha continua a ser o registo; o que mudou é que
> uma chave fora dele passa a ser recusada também na leitura.

## 12. Controlo de versões

| Versão | Data | Alteração | Autor |
|---|---|---|---|
| 1.0 | Outubro 2026 | Emissão parcial (KAM-009): as duas bibliotecas sobre a revisão `0007`. Regista o achado de §4 — a matriz do `01` §7.2 funde dois domínios de estado e não tem célula para um tenant `ativo` sobre um canal `desligado` —, a regra de precedência proposta, e as quatro decisões devolvidas aos donos do `01` e do `02`. | Equipa KAMBÁ |
| 1.1 | Outubro 2026 | Correcção da revisão adversarial, metade das bibliotecas (§1.1). **M3:** `coalesce` no `SQL_PERIODO`, e os dois caminhos testados nos dois idiomas (§5.1). **M4:** `desligado` passa a ganhar de tudo na precedência — é transporte e não política —, e a matriz passa a estar coberta inteira, 210 casos por idioma (§4.1). **M5:** a espécie de cada chave passa a ser lida do registo, nasce o `checkCeiling` sobre o `SQL_TECTO`, e cada função recusa a chave da outra espécie; duas das dez chaves ficam declaradamente sem caminho de aplicação (§5.2 a §5.4). **C1:** a chave de idempotência passa a ser derivada, com a do cliente como um componente, e o `KA002` ganha erro próprio (§7.3). **m6:** §11 passa a separar o que tem medição — com os números de `92eb2f4` — do que continua por verificar, e a dizer contra que revisão cada número foi medido. | Equipa KAMBÁ |
