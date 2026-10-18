# TEN — entitlements, limites e a matriz de estados

| Campo | Valor |
|---|---|
| Documento | `docs/ten.md` |
| Ticket | KAM-009 — TEN: entitlements e limites aplicados por *middleware* |
| Estado | **Parcial.** Esta versão cobre as **duas bibliotecas** (`packages/core-ts/src/ten/` e `libs/py-core/src/kamba_core/ten/`) e a revisão `0007`, que lhes serve de fonte. O registo de chaves (`registry/entitlement_keys.schema.json`, `registry/plans.yaml`) e a *suite* do gate 8 são trabalho paralelo do mesmo ticket e acrescentam aqui as suas secções |
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
periodo          ──► platform.ten_periodo    o mês fecha em Africa/Luanda, num sítio só
tenantGate       ──► tabela, em memória      a matriz do `01` §7.2 (ver §4: tem um problema)
```

## 2. O que existe, e onde

| Ficheiro | O quê |
|---|---|
| `packages/core-ts/src/ten/consultas.ts` | As três consultas. O SQL, sem o código à volta |
| `packages/core-ts/src/ten/entitlements.ts` | `checkEntitlement`, `consumeLimit`, `periodo`, `CacheDeEntitlements`, os códigos de erro |
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
encerrado > suspenso > desligado > pendente > restrito > ativo
```

| Degrau | Fundamento |
|---|---|
| `encerrado` primeiro | É o único terminal nas duas máquinas de estado, e a linha é «Registar e descartar». De um estado do qual não se sai não se passa por um do qual se saia |
| `suspenso` a seguir | A nota é «Decisão T&S ou falta de pagamento»: a única linha de causa externa. Passar-lhe à frente por o outro domínio estar `ativo` seria continuar a servir quem a Meta ou a cobrança mandaram parar |
| `desligado` antes de `pendente` | «Nenhuma entrada chega (coexistência removida)»: não há caminho técnico para o público. Um tenant `ativo` sobre canal `desligado` não fica a meio, fica sem canal |
| `pendente` antes de `restrito` | `pendente` permite registar e a mensagem de teste («não responder ao público»); `restrito` permite conversar dentro da janela |
| `restrito` antes de `ativo` | A única relação de ordem que a tabela torna óbvia |

> **A ordem é uma PROPOSTA deste ticket.** Não há documento que a escreva, nem
> sequer que admita que os dois domínios se cruzam. **A decisão devolve-se ao
> dono do `docs/tecnica/01` §7.2.** O que aqui se faz é não deixar o cruzamento
> por resolver em silêncio, que é o que um gate de um parâmetro faria.

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

Nos dois, a **ordem** é entitlement primeiro e consumo depois — consumir
primeiro gastava o tecto de quem nem sequer podia entrar —, e há um teste de
paridade que o confirma lendo as duas fontes.

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

As bibliotecas mantêm os **dois** nomes do entitlement, cada um no seu caminho,
e há um teste que falha se alguém os unificar. **A decisão de os unificar
devolve-se ao dono do `docs/tecnica/02` §6.5**: escolher um dos dois aqui, em
silêncio, era fechar por omissão uma divergência entre um ticket e um documento.

Um pedido que precise de consumir e não traga chave de idempotência **levanta**
em vez de virar um código novo: acrescentar um `400 IDEMPOTENCY_KEY_REQUIRED`
ao vocabulário do §6.5 sem documento nenhum é outra decisão de quem o detém.

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
| Medido | **100% de linhas em todos os doze** (1 703/1 703) |
| Efeito no estrato | `critico` sobe de **95%** para **96%** — o padrão traz cobertura, não a baixa |
| Dois revisores | O cabeçalho do `ci/thresholds.yaml` exige-os para qualquer alteração ao ficheiro. **A caixa não está marcada** |

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

## 11. O que **não** está verificado

| # | Afirmação | Porquê não está verificada |
|---|---|---|
| 1 | Os critérios 3, 4 e 5 (concorrência, idempotência, fronteira de mês) | São propriedades do SQL. As baterias de unidade correm sobre uma base **falsa** e não os provam; quem os prova é o gate 8, com a *suite* da outra parte deste ticket |
| 2 | «Não existe evento `entitlement.*` no catálogo» | Verificado por leitura do catálogo e das subscrições de `registry/*.yaml` em `docs/tecnica/02` §5.1. Não há gate que o imponha: se alguém acrescentar o evento, nada aqui dá por isso |
| 3 | O comportamento da RLS perante um contexto de outro tenant | A biblioteca trata zero linhas como negado; **que a RLS devolva zero linhas** é da `0002` e prova-se no gate 8 |
| 4 | O `critico` agregado a 96% | Medido com **dois** relatórios LCOV (`packages/core-ts` e `libs/py-core`), não com a corrida completa do `make ci-4`. O número dos doze ficheiros de `ten` (100%) não depende disso; o agregado do estrato pode mover-se com os outros relatórios |
| 5 | Os nomes das chaves de limite (`msgs_ai_mes`, `valor_max_pedido_minor`, …) | São do critério 1, marcados «nomes em proposta» pelo próprio ticket. Esta biblioteca **não** os conhece: aceita qualquer chave que case a gramática, e quem fecha a lista é o registo |
| 6 | Valores de limite por plano | Fora de âmbito desta parte e **sem fonte** (H6 por validar). Nenhum valor, nenhum preço, é escrito em lado nenhum deste módulo |

## 12. Controlo de versões

| Versão | Data | Alteração | Autor |
|---|---|---|---|
| 1.0 | Outubro 2026 | Emissão parcial (KAM-009): as duas bibliotecas sobre a revisão `0007`. Regista o achado de §4 — a matriz do `01` §7.2 funde dois domínios de estado e não tem célula para um tenant `ativo` sobre um canal `desligado` —, a regra de precedência proposta, e as quatro decisões devolvidas aos donos do `01` e do `02`. | Equipa KAMBÁ |
