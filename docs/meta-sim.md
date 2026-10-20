# `meta-sim` — simulador de webhooks Meta e servidor Graph falso

> **Dono:** KAM-024 · **Consumidores:** KAM-015, KAM-016, KAM-017, KAM-020,
> KAM-078, KAM-084 · **Versão deste documento:** 1.0

O `tools/meta-sim` produz corpos de webhook da Meta assinados e
determinísticos, e levanta um servidor Graph falso com cenários programáveis.
Serve três coisas que não se conseguem de outra maneira:

1. **exercitar o GWY e o CHR sem a Meta** — o número de teste da app de
   *staging* não existe antes do KAM-102, e a coexistência nem com ele
   (`docs/tecnica/09` §6);
2. **ter *fixtures* que não envelhecem** — a mesma semente dá os mesmos bytes,
   e por isso um `git diff` de *fixtures* diz o que mudou em vez de dizer que
   tudo mudou;
3. **não deixar um telefone real no repositório** — a captura saneia, e o *scan*
   confronta o repositório inteiro com um inventário (§6).

Nada deste pacote vai para produção. Está na *workspace* do pnpm — ao contrário
do `tools/mermaid_lint` — porque **não acrescenta dependência nenhuma**: usa o
`node:crypto` e o `node:http` da biblioteca padrão e o vocabulário de
`@kamba/core-ts`. Dentro da *workspace*, os gates 2 e 4 cobrem-no sem alvo novo.

---

## 1. Gerar *fixtures*

```bash
pnpm --filter @kamba/meta-sim exec node src/cli.ts gerar --semente kamba-piloto --saida fixtures
```

Escreve, por item de cobertura, um `<marca>.json` com os bytes e um
`<marca>.sig` com o valor de `x-hub-signature-256`. **Os bytes gravados são os
bytes assinados**: o ficheiro não é reescrito com indentação, porque a
assinatura é sobre o corpo bruto e um par corpo-bonito/assinatura-do-compacto
não é aceite por nenhum GWY.

Vinte e seis *fixtures*, uma por item: dezasseis da dimensão «tipo» (os dez de
`messages[]`, as duas variantes de `interactive`, os quatro `statuses` e o
`history`) e onze da dimensão «campo». O `history` conta nas duas e tem uma
*fixture* só.

### De dentro de um teste

O CLI é uma casca. Tudo o que ele faz faz-se por chamada:

```ts
import { segredoDeEnsaio, todasAsFixtures } from "@kamba/meta-sim";

const segredo = segredoDeEnsaio("a-minha-semente");
for (const fixture of todasAsFixtures("a-minha-semente", segredo)) {
  // fixture.bytes, fixture.assinatura, fixture.corpo, fixture.item.marca
}
```

Para um corpo à medida, monta-se com os construtores:

```ts
import { Gerador, canalDe, corpo, interlocutorDe, serializar } from "@kamba/meta-sim";

const g = new Gerador("um-caso-meu");
const canal = canalDe(g);
const quem = interlocutorDe(g);
const bytes = serializar(
  corpo(g, {
    canal,
    mudancas: [{ campo: "messages", opcoes: { canal, quem, tipos: ["audio"], estados: ["read"] } }],
  }),
);
```

---

## 2. Determinismo

A semente de cada *fixture* é `<semente>/<marca>`, e não a posição na lista.
Isso compra uma propriedade que a semente única não dá: **acrescentar uma
*fixture* não muda os bytes das outras**. Sem ela, um item novo no meio da lista
fazia um diff de uma linha virar vinte e seis ficheiros, e um teste que afirme
os bytes de `tipo:sticker` passava a falhar por causa de um `tipo:video` que
alguém pôs acima — com uma mensagem de erro que mandava procurar no sítio
errado.

O `timestamp` e o `entry.time` vêm do gerador e **nunca** do relógio. A base é
`2026-10-01T00:00:00Z`, que é a data em que as *service messages* passaram a ser
pagas (`E1` §1): uma *fixture* datada antes disso descrevia um mundo com outro
preço.

---

## 3. Assinatura e ida e volta

`assinar(bytes, segredo)` devolve o valor de `x-hub-signature-256`. O módulo tem
**`createHmac` próprio** e não importa nada de `@kamba/core-ts/entrada`, de
propósito: quem valida no GWY é o `assinaturaValida` desse módulo, e se o
simulador assinasse com a mesma função a ida e volta provava que uma função é
consistente consigo própria — e ficava verde no dia em que o algoritmo estivesse
errado dos dois lados. É a mesma razão por que a *suite* `db/tests_entrada/`
calcula a assinatura em Python.

A prova do critério 4 está em
[`services/gwy/tests/kam024.ida-e-volta.test.ts`](../services/gwy/tests/kam024.ida-e-volta.test.ts),
e são três afirmações:

| O que se envia | Resposta | Porque importa |
|---|---|---|
| a *fixture* e a sua assinatura | 200, 1 *job* | a ida e volta funciona |
| a *fixture* com **1 byte** mudado | 401, 0 *jobs* | a assinatura é sobre os bytes |
| a *fixture* serializada com espaços | 401, 0 *jobs* | o GWY **não** normaliza antes de verificar |

A terceira é a que apanha o defeito que nenhuma *fixture* sozinha apanha: o
mesmo JSON com bytes diferentes. Um GWY que fizesse
`JSON.stringify(await c.req.json())` passava as duas primeiras e recusava
tráfego real.

### O segredo de ensaio

`segredoDeEnsaio(semente)` é determinístico, e começa sempre por `ensaio-`. É
seguro ser determinístico porque não protege nada, e
`exigirSegredoDeEnsaio(segredo)` recusa trabalhar se o segredo não tiver o
prefixo **ou** se coincidir com o valor de qualquer `KAMBA_SECRET_*` do
ambiente — que é a «verificação de configuração» que o critério 4 pede.

---

## 4. Casos adversos

Oito, com o nome do critério 3 e **com o desfecho esperado escrito ao lado dos
bytes**. A razão de o desfecho viver no caso é que a resposta certa não é óbvia
em metade deles:

| Caso | Resposta | A jusante |
|---|---|---|
| `assinatura_invalida` | 401 | 0 *jobs* |
| `json_invalido_assinado` | **200** | 1 *job*; o *parse* falha no *worker* |
| `corpo_duplicado` | 200, 200 | **1** *job* (o `jobId` é o `sha256` dos bytes) |
| `mesma_mensagem_em_dois_corpos` | 200, 200 | **2** *jobs*, **1** linha (a chave é o `wamid`) |
| `ordem_trocada` | 200 | 3 eventos; o estado final fica `read` |
| `lote_de_entries` | 200 | 1 *job*, 3 eventos, 2 `waba_id` |
| `wa_id_omitido` | 200 | o CHR resolve só pelo BSUID |
| `phone_number_id_desconhecido` | 200 | 1 linha em `unrouted_events` |

Um `json_invalido_assinado` dá **200** e não 400 porque a Meta repete sete dias
o que não receber 200, e repetir um corpo que nunca vai dar *parse* é tráfego
perdido duas vezes.

---

## 5. Servidor Graph falso

```bash
pnpm --filter @kamba/meta-sim exec node src/cli.ts graph --porta 4010
```

Duas formas de o usar, e as duas são necessárias:

- **`responder(pedido)`** é puro, sem socket. É o que os testes usam, porque um
  teste que precise de uma porta TCP livre falha em paralelo por razões que não
  têm a ver com o que se está a medir;
- **`ouvir(porta)`** levanta um `node:http`. É o que o KAM-015 e o KAM-020
  precisam quando o que querem exercitar é o **cliente HTTP** deles — `fetch`,
  *timeouts*, *retries*, o proxy de saída. Porta 0 por omissão: o SO escolhe.

Cenários, pelo `Plano`:

```ts
const graph = new GraphFalso(new Gerador("cenario"), {
  envio: { cenario: "debito_excedido", vezes: 3 },  // 130429 3× e depois 200
  template: { estado: "REJECTED" },
  code: "invalido",
  midia: { expirada: true },
});
```

| Cenário de envio | Resposta | Código |
|---|---|---|
| `ok` | 200 com `wamid` | — |
| `debito_excedido` | 429 com `Retry-After` | 130429 (CONFIRMADO) |
| `limite_por_utilizador` | 400 | 131049 (CONFIRMADO) |
| `erro_servidor` | 500 | — |
| `indisponivel` | 503 | — |

`vezes` ausente significa **sempre**, que é o cenário «Meta em baixo» de
`RB-K01`. As rotas servidas são `messages`, `message_templates` (POST e GET),
`oauth/access_token`, `subscribed_apps` (POST, GET, DELETE), a metainformação de
mídia e a sua descarga.

O servidor **aceita qualquer** `/v<maior>.<menor>/` e registra a que o cliente
usou. Nenhum documento do repositório fixa a versão da Graph API, e inventar uma
era afirmar o que não se sabe; quando o KAM-015 a fixar, um teste pode afirmar
que o cliente a usa — contra o registo.

---

## 6. Captura, saneamento e o *scan*

### Sanear uma captura

```bash
pnpm --filter @kamba/meta-sim exec node src/cli.ts sanear captura.json --saida fixtures/nova.json
```

Substitui telefones, BSUID, `wamid`, `waba_id`, `phone_number_id`, nomes de
perfil, **o texto das mensagens**, nomes de ficheiro e resumos. O texto não se
«limpa» — substitui-se por inteiro, porque uma limpeza parcial de texto livre é
uma aposta e é onde uma pessoa escreve o seu endereço.

Duas propriedades que fazem a ferramenta valer:

- **a substituição é consistente dentro da captura** — o mesmo valor real dá
  sempre o mesmo valor fictício, senão duas mensagens do mesmo contacto passavam
  a ser de dois contactos;
- **a verificação é sobre a saída** — e por isso uma chave que o saneador não
  conheça aparece como **recusa** (`CapturaRecusadaError`, que nomeia a chave)
  em vez de como um dado pessoal gravado para sempre no histórico do git.

O `wamid` novo leva o telefone **novo** lá dentro. Um `wamid` fictício construído
com o número real deixava o número na *fixture*, dentro de base64, onde o *scan*
de texto não o vê — que é o caminho que o `idOpaco` do KAM-068 existe para
fechar.

### O *scan*

```bash
pnpm --filter @kamba/meta-sim exec node src/cli.ts varrer .        # confronta o inventario
pnpm --filter @kamba/meta-sim exec node src/cli.ts varrer . --cru  # lista, sem confrontar
```

O *scan* percorre o repositório e conta números de **forma** real. O que decide
se isso é tolerável é o inventário de
[`src/inventario.ts`](../tools/meta-sim/src/inventario.ts), e a razão de existir
está lá escrita por extenso: o critério 7 lê-se de duas maneiras, e a leitura
«0 cadeias com a forma de um número angolano» é insatisfazível — um redactor de
PII testado só com números do `999` nunca prova que apanha um `+244 9…`, que é o
que ele existe para apanhar.

O inventário é um **raquete**, não uma isenção, e falha nos quatro sentidos:

| Sentido | O que falha | Uma pasta isenta |
|---|---|---|
| ficheiro com número e sem entrada | sim | não |
| um número **a mais** num ficheiro já declarado | sim | **não** |
| um número a menos (entrada envelhecida) | sim | não |
| entrada sem medição (ficheiro mudou ou desapareceu) | sim | não |

Cada entrada diz **quantas** e **porquê**, e uma razão com menos de trinta
caracteres é um defeito do inventário. Para medir a contagem de uma entrada nova
corre-se `varrer --cru`.

Códigos de saída: `0` conforme, `2` há divergências, `1` a ferramenta não
conseguiu correr (incluindo «0 ficheiros lidos», que não é «0 achados»).

---

## 7. Cobertura

```bash
pnpm --filter @kamba/meta-sim exec node src/cli.ts cobertura
```

Imprime uma tabela Markdown com, por item, quantas *fixtures* e quantos testes o
cobrem, e sai com `2` se houver faltas ou marcas desconhecidas.

A ligação entre um teste e o item que ele cobre é uma **marca no nome do
teste**: `it("[cobertura:tipo:audio] ...")`. É verificável nas duas direcções, e
é isso que a torna útil — um item sem marca é uma falta, e uma marca com um item
que não existe é um **erro**, porque um `[cobertura:txt]` mal escrito dava ao
mesmo tempo um teste que parece contar e um item descoberto.

As *fixtures* contam-se por construção; os testes contam-se lendo os **ficheiros
de teste**, e não por registo em memória: um registo contava o que correu nesta
execução, e um `--test-name-pattern` que filtrasse metade dava um relatório a
50% — ou, pior, a 100% construído por testes que nenhuma máquina voltou a
correr.

---

## 8. Re-entrega

```ts
const relatorio = await reentregar(async (numero, instanteSimulado) => {
  const resposta = await enviar(bytes, assinatura);  // o MESMO corpo, sempre
  return resposta.status;
});
assert.deepEqual(razoesDeFalha(relatorio), []);
```

Doze tentativas, do instante 0 aos sete dias, com *backoff* exponencial de base
60 s e factor 4 truncado em 24 h. O tempo simulado é **explícito** e o real é
mínimo: dormir `atraso / escala` com escala 10 080 dava fracções de milissegundo
que o `setTimeout` arredonda para 1 ms cada, e o teste passava a medir o
`setTimeout` em vez da idempotência.

**O calendário é uma *proposta*.** O `E1` §5 confirma que a Meta repete «até
sete dias»; as páginas lidas **não** dão os intervalos. Quem os obtiver substitui
o `CALENDARIO_PROPOSTO` e os testes continuam a valer, porque o que eles medem é
«N entregas do mesmo corpo dão 1 efeito» — e isso não depende dos intervalos.

O *timeout* do webhook e o *pair rate limit* ficam **NÃO VERIFICADOS** e são
parâmetros (`Opcoes.esperaMaxima`). O simulador não os inventa.

---

## 9. A *suite* online

**Não está feita, e a caixa do critério 8 está vazia por isso.** Depende de
`ext:KAM-102` (Meta Business Verification e Tech Provider) e do número de teste
da app de *staging*, que não existem. O que este ticket entrega é a *suite*
**offline**, que corre no gate 7, e os cenários contra os quais a online se vai
escrever.

Quando o número existir, a *suite* online corre uma vez por noite e produz um
relatório que compara a estrutura real com a das *fixtures*. Duas regras já
decididas, que estão no ticket:

- **não bloqueia PR**, mas é de *release* (gate 15, KAM-078);
- **falha da Meta ou das credenciais gera alerta, não falso verde** — uma *suite*
  que se desliga sozinha quando não encontra as credenciais nunca falha no dia
  em que alguém as configura mal.

---

## 10. Códigos de erro

Em [`src/codigos.ts`](../tools/meta-sim/src/codigos.ts), cada um com o seu estado
de verificação. Um simulador que invente códigos é pior do que um que não os
tenha: produz *fixtures* que ensinam o código a tratar um número que a Meta
nunca manda, e o tratamento certo nunca é escrito.

| Código | Significado | Estado |
|---|---|---|
| `130429` | débito excedido (80 mps; 20 fixos em coexistência) | CONFIRMADO |
| `131049` | limite de frequência por utilizador em *marketing* | CONFIRMADO |
| `2593109` | o cliente não partilhou histórico (**caso normal**) | CONFIRMADO |
| `131026` | mensagem não entregue | **NÃO VERIFICADO** |
| `131051` | tipo não suportado | **NÃO VERIFICADO** |

Os NÃO VERIFICADOS estão em `CODIGOS_PROPOSTOS` e não se tratam como sentinelas
em nenhum sítio: quem lê um `errors[]` trata-o pela **forma**.

---

## 11. Controlo de versões

| Versão | Data | Alteração |
|---|---|---|
| 1.0 | 2026-10-20 | Criado pelo KAM-024. |
