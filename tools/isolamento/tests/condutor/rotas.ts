/**
 * O condutor das rotas Hono: ataca-as **em processo** e escreve um relatorio
 * que o lado Python le (KAM-066, criterio 3 e criterio 6).
 *
 *     node tools/isolamento/tests/condutor/rotas.ts <grupo> <ficheiro-de-saida.json>
 *
 * ## Porque e que isto e um guiao de `node` e nao um caso de Python
 *
 * As vinte e seis rotas de TypeScript sao Hono, e uma aplicacao Hono responde pelo
 * `app.request()` sem nenhum servidor levantado — e a forma que os testes do GWY
 * ja usam. Nenhuma porta, nenhum `fetch` sobre `localhost`, nenhuma espera: o
 * ataque e deterministico e o `fn` do caso em `tools/isolamento/baterias/`
 * limita-se a ler o JSON. A fronteira entre as duas linguagens e este ficheiro,
 * e e de proposito que ela e um ficheiro e nao uma convencao: o Python nao
 * importa Hono e este guiao nao decide se ha achado.
 *
 * ## O que este guiao **nao** decide
 *
 * Nao decide se houve fuga, nem se as recusas foram uniformes. Reporta o que
 * mediu — estado, corpo, cabecalhos — e o oraculo de `tools/isolamento/`
 * procura nele os canarios de B. Por isso o processo **sai com 0 sempre que
 * conseguiu escrever o relatorio**, mesmo que todas as rotas tenham respondido
 * o pior possivel: um codigo de saida diferente de zero aqui era este guiao a
 * dar um veredicto que nao e dele. Sai com 1 **so** quando nao conseguiu
 * escrever — porque entao o lado Python nao tem nada para julgar, e um caso sem
 * medicao e um caso vermelho.
 *
 * ## O ambiente
 *
 *     KAMBA_X01_CANARIOS   JSON `{rotulo: valor}` com as cadeias proibidas (B)
 *     KAMBA_X01_TENANT_A   UUID do tenant que ataca
 *     KAMBA_X01_TENANT_B   UUID do tenant atacado
 *     KAMBA_X01_PG         JSON `{host, port, user, password, database, lote}`
 *     KAMBA_X01_CONTACTOS  JSON `{x: {id, canarios}, y: {id, canarios}}`
 *
 * Os dois ultimos so fazem falta aos grupos `canais`, `contacto` e `guia`; a
 * chave `lote` do `KAMBA_X01_PG` (`{user, password}` do `kamba_batch`) so ao
 * `guia`, que monta o processo de lote real (KAM-254). Sem eles as
 * entradas saem com `executado: false` e a nota a dizer o que faltou — nunca a
 * faltar, porque uma entrada em falta e, para o lado Python, uma rota enumerada
 * sem caso, que e precisamente o que o criterio 2 existe para apanhar.
 *
 * ## Os `node_modules` e a razao de o `cwd` ser a raiz do repositorio
 *
 * O `pnpm` instala por pacote: a raiz do *workspace* tem o `typescript` e o
 * `commitlint` e mais nada. Este guiao **nao** importa `hono` nem
 * `@kamba/core-ts` por especificador nu — nao resolveriam daqui —; importa os
 * ficheiros de `services/*` e de `packages/*` por caminho relativo, e e a
 * resolucao a partir **deles** que encontra o `hono` e o `@kamba/core-ts` de
 * cada servico. O `pg`, que nenhum ficheiro de `services/*` reexporta, vem pelo
 * `createRequire` ancorado em `packages/core-ts`, que o tem.
 *
 * E por isso tambem que o `dist` dos `packages` tem de estar construido: eles
 * chegam aos servicos por `node_modules`, e o Node recusa apagar
 * tipos de ficheiros sob `node_modules` (`docs/adr/ADR-L001-toolchain.md` §9).
 * Sem `pnpm run build` antes, o primeiro `import` de uma sonda falha — e falha
 * com `executado: false` e a nota, nao com uma excepcao sem relatorio.
 */

import { createHash, createHmac, randomUUID } from "node:crypto";
import { mkdirSync, writeFileSync, writeSync } from "node:fs";
import { createRequire } from "node:module";
import { dirname, join, resolve } from "node:path";
import { fileURLToPath, pathToFileURL } from "node:url";

const AQUI = dirname(fileURLToPath(import.meta.url));
/** A raiz do repositorio: `tools/isolamento/tests/condutor/` esta quatro niveis abaixo. */
const RAIZ = resolve(AQUI, "..", "..", "..", "..");

// ------------------------------------------------------------------- relatorio

/** Uma resposta medida. Uma entrada por **ataque**, nao por rota. */
interface EntradaDeRota {
  /** O identificador enumerado. O mesmo `item` repete-se por ataque. */
  item: string;
  metodo: string;
  caminho: string;
  estado: number;
  corpo: string;
  cabecalhos: Record<string, string>;
  executado: boolean;
  /** A razao, quando `executado` e falso. **Nunca leva um canario.** */
  nota: string;
}

/** Uma leitura por contacto, feita com o contacto `x` ou com o `y`. */
interface EntradaDeContacto {
  leitura: "encomendas" | "cotacoes" | "consentimentos";
  contacto: "x" | "y";
  executado: boolean;
  corpo: string;
  nota: string;
}

interface Relatorio {
  rotas: EntradaDeRota[];
  contacto: EntradaDeContacto[];
}

/**
 * `JSON.stringify` com `bigint`.
 *
 * O `getValidQuote` devolve `precoTotalMinor` e o `pedidoPorPagar` devolve
 * `totalMinor` como `bigint` — e o `JSON.stringify` **lanca** sobre um. Sem este
 * substituto, a leitura corria, media o que queria medir, e o relatorio morria
 * na serializacao.
 */
function serializar(valor: unknown): string {
  return JSON.stringify(valor, (_chave, item) =>
    typeof item === "bigint" ? `${item}` : item,
  );
}

/**
 * Diagnostico para o `stderr`, **sincrono**.
 *
 * `process.stderr.write` e assincrono quando o descritor e um *pipe* — e e um
 * *pipe* quando o guiao corre dentro de um contentor ou pelo `subprocess` do
 * `ponte.py`. Como este processo termina com `process.exit()` (ver o fim do
 * ficheiro), uma escrita assincrona pendente perdia-se: o guiao falhava sem
 * dizer porque. O `writeSync(2, …)` nao tem esse buraco.
 */
function diagnostico(texto: string): void {
  try {
    writeSync(2, texto);
  } catch {
    // Um `stderr` fechado nao e razao para perder o relatorio.
  }
}

/** A mensagem de um erro, sem a pilha e sem o valor que o causou. */
function razao(erro: unknown): string {
  if (erro instanceof Error) return `${erro.name}: ${erro.message}`;
  return String(erro);
}

// --------------------------------------------------------------------- ambiente

function ambiente(nome: string): string {
  return process.env[nome] ?? "";
}

function jsonDoAmbiente(nome: string): Record<string, unknown> | null {
  const bruto = ambiente(nome);
  if (bruto === "") return null;
  try {
    const valor: unknown = JSON.parse(bruto);
    if (typeof valor !== "object" || valor === null) return null;
    return valor as Record<string, unknown>;
  } catch {
    return null;
  }
}

/** Os canarios de B, pela ordem em que o *seed* os deu. */
function canarios(): string[] {
  const mapa = jsonDoAmbiente("KAMBA_X01_CANARIOS") ?? {};
  return Object.values(mapa).map((valor) => String(valor));
}

/**
 * Um canario para levar no ataque, ou um substituto reconhecivel.
 *
 * Sem canarios no ambiente o ataque continua a fazer-se — o que se perde e a
 * sonda positiva, e isso diz-se na nota em vez de se calar. O substituto nao
 * tem a forma de canario (`oraculo.FORMA_DO_CANARIO`), pelo que nao se confunde
 * com um achado.
 */
function canarioOuSubstituto(): string {
  return canarios()[0] ?? "sem-canario-no-ambiente";
}

// ------------------------------------------------------------- medir o pedido

type AppHono = {
  request(
    caminho: string,
    init?: { method?: string; body?: BodyInit; headers?: Record<string, string> },
  ): Promise<Response>;
};

/** Faz o pedido e mede-o. Qualquer falha vira `executado: false` com a nota. */
async function medir(
  item: string,
  metodo: string,
  caminho: string,
  app: AppHono,
  init?: { method?: string; body?: BodyInit; headers?: Record<string, string> },
): Promise<EntradaDeRota> {
  const vazia: EntradaDeRota = {
    item,
    metodo,
    caminho,
    estado: 0,
    corpo: "",
    cabecalhos: {},
    executado: false,
    nota: "",
  };
  try {
    const resposta = await app.request(caminho, init);
    return {
      ...vazia,
      estado: resposta.status,
      corpo: await resposta.text(),
      cabecalhos: Object.fromEntries(resposta.headers.entries()),
      executado: true,
    };
  } catch (erro) {
    return { ...vazia, nota: `o pedido lancou: ${razao(erro)}` };
  }
}

/** Importa um ficheiro do repositorio por caminho, nao por especificador nu. */
async function importarDoRepo(relativo: string): Promise<Record<string, unknown>> {
  const url = pathToFileURL(join(RAIZ, relativo)).href;
  return (await import(url)) as Record<string, unknown>;
}

// ------------------------------------------------------------------ as sondas
//
// A lista e **literal** e a ordem e a do caso em `baterias/x01_rotas.py`. Um
// filtro — «todas as fabricas de app do repositorio» — fazia a cobertura passar
// para sempre e uma rota nova nascia coberta, que e o «sem teste silencioso»
// que o criterio 2 fecha. Os `item` sao copiados do caso, nao derivados dele.

interface Sonda {
  readonly item: string;
  readonly modulo: string;
  readonly fabrica: string;
  readonly caminho: string;
}

const SONDAS: readonly Sonda[] = [
  {
    item: "rota:com:app:createApp:GET:/healthz",
    modulo: "services/com/src/app.ts",
    fabrica: "createApp",
    caminho: "/healthz",
  },
  // As duas do consumidor de pagamentos (KAM-055). A `criarApp` serve as duas
  // da **mesma** instancia, como a `criarAppDeMetricas` do GWY — o `/metrics`
  // concatena a exposicao do consumo (KAM-006) com o histograma do atraso
  // deste ticket, e so uma app as tem as duas.
  {
    item: "rota:com:payments/arranque:criarApp:GET:/healthz",
    modulo: "services/com/src/payments/arranque.ts",
    fabrica: "criarApp",
    caminho: "/healthz",
  },
  {
    item: "rota:com:payments/arranque:criarApp:GET:/metrics",
    modulo: "services/com/src/payments/arranque.ts",
    fabrica: "criarApp",
    caminho: "/metrics",
  },
  {
    item: "rota:gwy:app:createApp:GET:/healthz",
    modulo: "services/gwy/src/app.ts",
    fabrica: "createApp",
    caminho: "/healthz",
  },
  {
    item: "rota:gwy:app:criarAppDeMetricas:GET:/healthz",
    modulo: "services/gwy/src/app.ts",
    fabrica: "criarAppDeMetricas",
    caminho: "/healthz",
  },
  {
    item: "rota:gwy:app:criarAppDeMetricas:GET:/metrics",
    modulo: "services/gwy/src/app.ts",
    fabrica: "criarAppDeMetricas",
    caminho: "/metrics",
  },
  {
    item: "rota:onboarding-web:app:createApp:GET:/healthz",
    modulo: "services/onboarding-web/src/app.ts",
    fabrica: "createApp",
    caminho: "/healthz",
  },
  // KAM-190: as series do painel do dono, de dominios fechados e sem tenant.
  {
    item: "rota:onboarding-web:app:createApp:GET:/metrics",
    modulo: "services/onboarding-web/src/app.ts",
    fabrica: "createApp",
    caminho: "/metrics",
  },
  // KAM-215: o consumidor `dono`. A `criarApp` constroi-se sem argumentos e
  // nao abre a base nem a fila.
  {
    item: "rota:onboarding-web:provisionamento/processo:criarApp:GET:/healthz",
    modulo: "services/onboarding-web/src/provisionamento/processo.ts",
    fabrica: "criarApp",
    caminho: "/healthz",
  },
  {
    item: "rota:onboarding-web:provisionamento/processo:criarApp:GET:/metrics",
    modulo: "services/onboarding-web/src/provisionamento/processo.ts",
    fabrica: "criarApp",
    caminho: "/metrics",
  },
  {
    item: "rota:worker-canal:agr_shim:criarApp:GET:/healthz",
    modulo: "services/worker-canal/src/agr_shim.ts",
    fabrica: "criarApp",
    caminho: "/healthz",
  },
  {
    item: "rota:worker-canal:agr_shim:criarApp:GET:/metrics",
    modulo: "services/worker-canal/src/agr_shim.ts",
    fabrica: "criarApp",
    caminho: "/metrics",
  },
  // KAM-194. A `criarApp` da ponte aceita o *logger* como opcional e
  // constroi-se sem argumentos, como a do `agr_shim.ts`: nao abre a fila.
  {
    item: "rota:worker-canal:ponte:criarApp:GET:/healthz",
    modulo: "services/worker-canal/src/ponte.ts",
    fabrica: "criarApp",
    caminho: "/healthz",
  },
  {
    item: "rota:worker-canal:ponte:criarApp:GET:/metrics",
    modulo: "services/worker-canal/src/ponte.ts",
    fabrica: "criarApp",
    caminho: "/metrics",
  },
  {
    item: "rota:worker-canal:app:createApp:GET:/healthz",
    modulo: "services/worker-canal/src/app.ts",
    fabrica: "createApp",
    caminho: "/healthz",
  },
  {
    item: "rota:worker-canal:consumidor:criarApp:GET:/healthz",
    modulo: "services/worker-canal/src/consumidor.ts",
    fabrica: "criarApp",
    caminho: "/healthz",
  },
  {
    item: "rota:worker-canal:consumidor:criarApp:GET:/metrics",
    modulo: "services/worker-canal/src/consumidor.ts",
    fabrica: "criarApp",
    caminho: "/metrics",
  },
  {
    item: "rota:worker-canal:entrada:criarApp:GET:/healthz",
    modulo: "services/worker-canal/src/entrada.ts",
    fabrica: "criarApp",
    caminho: "/healthz",
  },
  {
    item: "rota:worker-canal:entrada:criarApp:GET:/metrics",
    modulo: "services/worker-canal/src/entrada.ts",
    fabrica: "criarApp",
    caminho: "/metrics",
  },
  {
    item: "rota:worker-canal:publicador:criarApp:GET:/healthz",
    modulo: "services/worker-canal/src/publicador.ts",
    fabrica: "criarApp",
    caminho: "/healthz",
  },
  {
    item: "rota:worker-canal:publicador:criarApp:GET:/metrics",
    modulo: "services/worker-canal/src/publicador.ts",
    fabrica: "criarApp",
    caminho: "/metrics",
  },
] as const;

/**
 * Cada sonda, uma vez, sem argumentos na fabrica.
 *
 * **Sem argumentos e a escolha certa e nao comodidade.** As fabricas do GWY
 * tomam as dependencias como opcionais precisamente para que a sonda se possa
 * provar sem fila e sem segredos, e o `docstring` do `createApp` escreve que sem
 * elas o webhook **nao e montado**. Passar-lhes duplos aqui montava rotas que
 * este grupo nao enumera, e o grupo `webhook` e o que as monta de proposito.
 *
 * As dezoito sondas nao recebem identificador nenhum, pelo que nao ha IDOR a
 * fazer: o que se prova e que elas **respondem** — uma rota que nao responde nao
 * foi atacada — e que o que respondem atravessa o oraculo como qualquer outra.
 */
async function grupoDasSondas(relatorio: Relatorio): Promise<void> {
  // Uma app por `(modulo, fabrica)`: a `criarAppDeMetricas` serve `/healthz` e
  // `/metrics` da mesma instancia, como em producao.
  const apps = new Map<string, AppHono | string>();

  for (const sonda of SONDAS) {
    const chave = `${sonda.modulo}#${sonda.fabrica}`;
    if (!apps.has(chave)) {
      try {
        const modulo = await importarDoRepo(sonda.modulo);
        const fabrica = modulo[sonda.fabrica];
        if (typeof fabrica !== "function") {
          apps.set(
            chave,
            `${sonda.modulo} nao exporta ${sonda.fabrica} como funcao. ` +
              "A enumeracao nomeia uma fabrica que o ficheiro nao tem.",
          );
        } else {
          apps.set(chave, (fabrica as () => AppHono)());
        }
      } catch (erro) {
        apps.set(chave, `nao se conseguiu importar ${sonda.modulo}: ${razao(erro)}`);
      }
    }

    const app = apps.get(chave);
    if (typeof app === "string" || app === undefined) {
      relatorio.rotas.push({
        item: sonda.item,
        metodo: "GET",
        caminho: sonda.caminho,
        estado: 0,
        corpo: "",
        cabecalhos: {},
        executado: false,
        nota: app ?? "a app nao foi construida",
      });
      continue;
    }
    relatorio.rotas.push(await medir(sonda.item, "GET", sonda.caminho, app));
  }
}

// ------------------------------------------------------------------ o webhook

const ITEM_DO_WEBHOOK_GET = "rota:gwy:webhook:montarWebhook:GET:/wa/webhook";
const ITEM_DO_WEBHOOK_POST = "rota:gwy:webhook:montarWebhook:POST:/wa/webhook";
const CAMINHO_DO_WEBHOOK = "/wa/webhook";

// Os valores dos duplos. Obviamente falsos e de baixa entropia, pela razao que
// `services/gwy/tests/webhook.test.ts` escreve ao lado do seu: um valor com
// forma de segredo atribuido a um nome que **significa** segredo dispara o
// *gate* 9, e tem razao em disparar. Os nomes aqui nao significam segredo.
const ANEL_ACTUAL = "ensaio-x01-actual";
const ANEL_ANTERIOR = "ensaio-x01-anterior";
/**
 * A chave que **o atacante** tem.
 *
 * E o centro da leitura que este grupo faz de «com e sem assinatura valida». O
 * App Secret da Meta e um segredo **da plataforma**, partilhado entre a nossa
 * app e a Meta; um tenant nunca o tem. Logo a assinatura que o tenant A
 * consegue produzir e valida *na forma* — prefixo certo, HMAC-SHA256 certo sobre
 * o corpo, comprimento certo — e nao bate com o anel. E esse o ataque: assinar
 * com o anel era modelar «a Meta mandou um corpo que nomeia B», que e trafego
 * legitimo e nao um IDOR.
 */
const CHAVE_DE_A = "ensaio-x01-de-quem-ataca";
const VERIFICACAO = "verificacao-de-ensaio-do-x01";

/** O `x-hub-signature-256` de um corpo com uma chave dada. */
function assinar(corpo: Uint8Array, chave: string, prefixo: string): string {
  return `${prefixo}${createHmac("sha256", chave).update(corpo).digest("hex")}`;
}

/**
 * O GWY com o webhook montado, e os duplos no padrao do teste do KAM-013.
 *
 * `FilasEmMemoria` do KAM-005 e um anel de dois textos: sem Redis e sem
 * Postgres, porque nada do caminho do `POST` vai a base ou ao cofre (ver o
 * `docstring` de `webhook.ts`). A `profundidade` devolve `null`, que **nao** e
 * saturacao — e o que mantem o caminho medido igual ao de producao em repouso.
 */
async function montarGwyComWebhook(): Promise<AppHono> {
  const app = await importarDoRepo("services/gwy/src/app.ts");
  const filas = await importarDoRepo("packages/core-ts/src/eventos/filas.ts");
  const FilasEmMemoria = filas["FilasEmMemoria"] as new () => unknown;
  const createApp = app["createApp"] as (
    log: undefined,
    dependencias: Record<string, unknown>,
  ) => AppHono;
  return createApp(undefined, {
    anel: () => [ANEL_ACTUAL, ANEL_ANTERIOR],
    verifyToken: () => VERIFICACAO,
    filas: new FilasEmMemoria(),
    profundidade: () => null,
  });
}

/**
 * O webhook, atacado com identificadores de B e com o canario de B.
 *
 * No `GET` os tres `hub.*` vao na *query string*, e o `hub.verify_token` que se
 * oferece e **sempre** de B ou o canario, nunca o do duplo: o ataque e «A tenta
 * verificar-se com o que sabe de B». Um ataque que oferecesse o token certo
 * recebia 200 com o `hub.challenge` ecoado byte a byte — e se o desafio levasse
 * o canario, o canario voltava. Isso nao seria uma fuga: seria o condutor a
 * mandar o canario e a receber o seu proprio eco, que e um achado inventado.
 *
 * No `POST` o corpo leva `phone_number_id` e `waba_id` com o canario e com o
 * UUID de B, e os pedidos repetem-se sem assinatura, com uma assinatura
 * malformada e com uma assinatura bem formada feita com a chave de A (ver
 * `CHAVE_DE_A`).
 */
async function grupoDoWebhook(relatorio: Relatorio): Promise<void> {
  const canario = canarioOuSubstituto();
  const tenantB = ambiente("KAMBA_X01_TENANT_B");
  const nota = canarios().length === 0 ? "KAMBA_X01_CANARIOS nao veio no ambiente" : "";

  let app: AppHono;
  try {
    app = await montarGwyComWebhook();
  } catch (erro) {
    for (const [item, metodo] of [
      [ITEM_DO_WEBHOOK_GET, "GET"],
      [ITEM_DO_WEBHOOK_POST, "POST"],
    ] as const) {
      relatorio.rotas.push({
        item,
        metodo,
        caminho: CAMINHO_DO_WEBHOOK,
        estado: 0,
        corpo: "",
        cabecalhos: {},
        executado: false,
        nota: `nao se conseguiu montar o GWY com o webhook: ${razao(erro)}`,
      });
    }
    return;
  }

  // --- o GET de verificacao ------------------------------------------------
  const consultas = [
    // O token de B, e o desafio leva o canario: se o eco acontecesse, o canario
    // saia no corpo.
    `hub.mode=subscribe&hub.verify_token=${encodeURIComponent(tenantB)}` +
      `&hub.challenge=${encodeURIComponent(canario)}`,
    // O canario como token, e o UUID de B como desafio.
    `hub.mode=subscribe&hub.verify_token=${encodeURIComponent(canario)}` +
      `&hub.challenge=${encodeURIComponent(tenantB)}`,
    // Sem `hub.mode`: o pedido malformado nao se distingue do token errado na
    // resposta, e e isso que o criterio 3 chama uniformidade.
    `hub.verify_token=${encodeURIComponent(canario)}&hub.challenge=${encodeURIComponent(canario)}`,
    // Os tres parametros de B de uma vez.
    `hub.mode=subscribe&hub.verify_token=${encodeURIComponent(`${tenantB}:${canario}`)}` +
      `&hub.challenge=${encodeURIComponent(canario)}`,
  ];
  for (const consulta of consultas) {
    const medida = await medir(
      ITEM_DO_WEBHOOK_GET,
      "GET",
      `${CAMINHO_DO_WEBHOOK}?${consulta}`,
      app,
    );
    relatorio.rotas.push({ ...medida, caminho: CAMINHO_DO_WEBHOOK, nota: medida.nota || nota });
  }

  // --- o POST --------------------------------------------------------------
  const assinatura = await importarDoRepo("packages/core-ts/src/entrada/assinatura.ts");
  const cabecalhoDaAssinatura = String(assinatura["CABECALHO_DA_ASSINATURA"]);
  const prefixo = String(assinatura["PREFIXO_DA_ASSINATURA"]);

  /** Um corpo de webhook com os identificadores que se quer atacar. */
  function corpoDeAtaque(waba: string, pnid: string): Uint8Array {
    return new Uint8Array(
      Buffer.from(
        JSON.stringify({
          object: "whatsapp_business_account",
          entry: [
            {
              id: waba,
              changes: [
                {
                  field: "messages",
                  value: {
                    messaging_product: "whatsapp",
                    metadata: { display_phone_number: "999100000001", phone_number_id: pnid },
                    statuses: [{ id: "wamid.X01", status: "delivered", recipient_id: pnid }],
                  },
                },
              ],
            },
          ],
        }),
        "utf8",
      ),
    );
  }

  const ataques: { readonly corpo: Uint8Array; readonly assinatura: string | null }[] = [
    // O canario nos dois identificadores, sem assinatura nenhuma.
    { corpo: corpoDeAtaque(canario, canario), assinatura: null },
    // O UUID de B, com uma assinatura bem formada feita com a chave de A.
    { corpo: corpoDeAtaque(tenantB, `${tenantB}:${canario}`), assinatura: "de-a" },
    // O canario, com uma assinatura malformada (sem o prefixo que a Meta usa).
    { corpo: corpoDeAtaque(`${canario}`, tenantB), assinatura: "malformada" },
    // Os dois juntos, com a assinatura de A sobre **outro** corpo: a assinatura
    // e sobre o corpo bruto, e um corpo re-serializado com a mesma assinatura e
    // o que o criterio 2 do KAM-013 exige que seja recusado.
    { corpo: corpoDeAtaque(`${tenantB}:${canario}`, canario), assinatura: "de-outro-corpo" },
  ];

  for (const ataque of ataques) {
    const cabecalhos: Record<string, string> = { "content-type": "application/json" };
    if (ataque.assinatura === "de-a") {
      cabecalhos[cabecalhoDaAssinatura] = assinar(ataque.corpo, CHAVE_DE_A, prefixo);
    } else if (ataque.assinatura === "malformada") {
      cabecalhos[cabecalhoDaAssinatura] = assinar(ataque.corpo, CHAVE_DE_A, "");
    } else if (ataque.assinatura === "de-outro-corpo") {
      cabecalhos[cabecalhoDaAssinatura] = assinar(
        corpoDeAtaque("outro", "outro"),
        CHAVE_DE_A,
        prefixo,
      );
    }
    const medida = await medir(ITEM_DO_WEBHOOK_POST, "POST", CAMINHO_DO_WEBHOOK, app, {
      method: "POST",
      body: ataque.corpo,
      headers: cabecalhos,
    });
    relatorio.rotas.push({ ...medida, nota: medida.nota || nota });
  }
}

// -------------------------------------------------------------------- o `pg`
//
// O `pg` nao se importa por especificador nu daqui (ver o `docstring` do
// modulo): vem pelo `createRequire` ancorado em `packages/core-ts`, que o
// declara em `devDependencies` e e de onde a casa liga nos testes de base.

interface ClienteDePg {
  connect(): Promise<void>;
  query(
    sql: string,
    parametros?: readonly unknown[],
  ): Promise<{ rows: Record<string, unknown>[] }>;
  end(): Promise<void>;
}

interface LigacaoPg {
  readonly host: string;
  readonly port: number;
  readonly user: string;
  readonly password: string;
  readonly database: string;
}

function configuracaoDoPg(): LigacaoPg | null {
  const bruto = jsonDoAmbiente("KAMBA_X01_PG");
  if (bruto === null) return null;
  return {
    host: String(bruto["host"] ?? "127.0.0.1"),
    port: Number(bruto["port"] ?? 5432),
    user: String(bruto["user"] ?? ""),
    password: String(bruto["password"] ?? ""),
    database: String(bruto["database"] ?? ""),
  };
}

/**
 * Uma ligacao, nao um *pool*.
 *
 * O `comTenant` **recusa** um *pool* (`PoolRecusadoError`), e tem razao: o
 * `BEGIN` numa ligacao, o `set_config` noutra e a consulta numa terceira correm
 * sem contexto nenhum e devolvem zero linhas — que e a forma de uma bateria de
 * isolamento ficar verde sem medir nada.
 */
async function ligar(configuracao: LigacaoPg): Promise<ClienteDePg> {
  const exigir = createRequire(join(RAIZ, "packages", "core-ts", "package.json"));
  const pg = exigir("pg") as { Client: new (opcoes: unknown) => ClienteDePg };
  const cliente = new pg.Client({
    ...configuracao,
    application_name: "kamba-x01-condutor",
  });
  await cliente.connect();
  return cliente;
}

// ------------------------------------------------------------------- os canais

const ITEM_DOS_CANAIS = "rota:gwy:canais:montarCanais:POST:/internal/channels";
const CAMINHO_DOS_CANAIS = "/internal/channels";
/** A vertical do canal. Configuracao (ADR-012), com `CHECK` de forma na `0001`. */
const VERTICAL = "vendedor";

/** Os corpos do ataque. Os cinco campos do criterio 1 em todos. */
function ataquesAosCanais(
  tenantA: string,
  tenantB: string,
  canario: string,
  sessionInfo: Record<string, unknown>,
): Record<string, unknown>[] {
  return [
    // 1. O `tenant_id` de B, identificadores comuns. O IDOR mais directo: A
    //    chama a rota e escreve no tenant de B.
    {
      tenant_id: tenantB,
      code: "codigo-de-ensaio-x01-um",
      waba_id: "waba-de-ensaio-x01",
      phone_number_id: "pnid-de-ensaio-x01",
      session_info: sessionInfo,
    },
    // 2. O `tenant_id` de B **e** o canario de B nos dois identificadores.
    {
      tenant_id: tenantB,
      code: "codigo-de-ensaio-x01-dois",
      waba_id: canario,
      phone_number_id: canario,
      session_info: sessionInfo,
    },
    // 3. O `tenant_id` de A com o canario de B: «A pergunta pelo numero de B».
    //    E o caso em que a resposta diria, se dissesse, de quem e o numero — e o
    //    `docstring` do `canais.ts` escreve que nao diz.
    {
      tenant_id: tenantA,
      code: "codigo-de-ensaio-x01-tres",
      waba_id: canario,
      phone_number_id: canario,
      session_info: sessionInfo,
    },
    // 4. O `tenant_id` de B com o canario so no `phone_number_id`, que e a
    //    coluna com unicidade **global** e por isso o alvo do 409.
    {
      tenant_id: tenantB,
      code: "codigo-de-ensaio-x01-quatro",
      waba_id: "waba-de-ensaio-x01",
      phone_number_id: canario,
      session_info: sessionInfo,
    },
  ];
}

async function grupoDosCanais(relatorio: Relatorio): Promise<void> {
  const tenantA = ambiente("KAMBA_X01_TENANT_A");
  const tenantB = ambiente("KAMBA_X01_TENANT_B");
  const canario = canarioOuSubstituto();

  const contrato = await importarDoRepo("packages/core-ts/src/onboarding/contrato.ts").catch(
    () => null,
  );
  // O `session_info` e **o mesmo em todos os ataques**, e valido de v4, e isso e
  // escolha: um `session_info` malformado dava 400 em uns ataques e nao noutros,
  // e a diferenca de estados que o criterio 3 proibe passava a ser culpa da
  // forma do corpo em vez do identificador. Aqui o que varia e so o que se
  // ataca.
  const sessionInfo: Record<string, unknown> = {
    sessionInfoVersion: String(contrato?.["SESSION_INFO_VERSION"] ?? "3"),
    extras: {
      featureType: String(
        contrato?.["FEATURE_TYPE_DE_COEXISTENCIA"] ?? "whatsapp_business_app_onboarding",
      ),
    },
  };
  const ataques = ataquesAosCanais(tenantA, tenantB, canario, sessionInfo);

  function semExecucao(nota: string): void {
    for (const _ataque of ataques) {
      relatorio.rotas.push({
        item: ITEM_DOS_CANAIS,
        metodo: "POST",
        caminho: CAMINHO_DOS_CANAIS,
        estado: 0,
        corpo: "",
        cabecalhos: {},
        executado: false,
        nota,
      });
    }
  }

  const configuracao = configuracaoDoPg();
  if (configuracao === null) {
    // A rota escreve no esquema dentro de uma transaccao, e um duplo de
    // transaccao provava que o duplo funciona. Sem base, nao se mede.
    semExecucao(
      "KAMBA_X01_PG nao veio no ambiente: a rota POST /internal/channels abre " +
        "uma transaccao real, e sem ligacao a base nao ha ataque a fazer. " +
        "`db/gate_bd.py` e quem levanta a base do gate.",
    );
    return;
  }

  let cliente: ClienteDePg;
  try {
    cliente = await ligar(configuracao);
  } catch (erro) {
    semExecucao(`nao se conseguiu ligar a base com KAMBA_X01_PG: ${razao(erro)}`);
    return;
  }

  try {
    const app = await importarDoRepo("services/gwy/src/app.ts");
    const guarda = await importarDoRepo("packages/core-ts/src/tenant_guard/index.ts");
    const onboarding = await importarDoRepo("packages/core-ts/src/onboarding/index.ts");
    const comTenant = guarda["comTenant"] as <T>(
      cliente: unknown,
      tenant: unknown,
      trabalho: (c: unknown) => Promise<T>,
    ) => Promise<T>;
    const Onboarding = onboarding["Onboarding"] as new (d: Record<string, unknown>) => unknown;

    /**
     * A Graph e o cofre **recusam**, e isso e desenho e nao atalho.
     *
     * Este condutor nao fala com a Meta: um ataque de isolamento que chamasse a
     * Graph de verdade era trafego para fora a partir de um *gate*. Se o
     * `ligar()` chegar aqui, o ataque **ja passou** a barreira que interessa — o
     * `INSERT` com o `tenant_id` de B sob o contexto de A —, e isso ve-se no
     * estado que a rota devolver.
     */
    const recusar = (passo: string) => () => {
      throw new Error(`o condutor do X-01 nao chama ${passo}`);
    };
    const graph = {
      trocarCode: recusar("a Graph (trocarCode)"),
      subscrever: recusar("a Graph (subscrever)"),
      lerSubscricoes: recusar("a Graph (lerSubscricoes)"),
      anularSubscricao: recusar("a Graph (anularSubscricao)"),
    };
    const cofre = {
      get: recusar("o cofre (get)"),
      getRing: recusar("o cofre (getRing)"),
      versions: recusar("o cofre (versions)"),
      cunhar: recusar("o cofre (cunhar)"),
      revogar: recusar("o cofre (revogar)"),
    };

    // O contexto e o de **A**, que e quem ataca, e vai por `set_config(..., true)`
    // dentro da transaccao. Nunca um `SET` de sessao: o valor morre com a
    // transaccao, e ha um *lint* deste ticket a recusar o contrario.
    const comTransaccao = async <T>(corpo: (servico: unknown) => Promise<T>): Promise<T> =>
      comTenant(cliente, tenantA, async (dentro) =>
        corpo(new Onboarding({ sql: dentro, graph, cofre, vertical: VERTICAL })),
      );

    const criarAppDeMetricas = app["criarAppDeMetricas"] as (
      log: undefined,
      canais: Record<string, unknown>,
    ) => AppHono;
    const interna = criarAppDeMetricas(undefined, { comTransaccao });

    for (const ataque of ataques) {
      relatorio.rotas.push(
        await medir(ITEM_DOS_CANAIS, "POST", CAMINHO_DOS_CANAIS, interna, {
          method: "POST",
          body: JSON.stringify(ataque),
          headers: { "content-type": "application/json" },
        }),
      );
    }
  } catch (erro) {
    semExecucao(`nao se conseguiu montar a app interna do GWY: ${razao(erro)}`);
  } finally {
    await cliente.end().catch(() => undefined);
  }
}

// ----------------------------------------------------------------- o contacto
//
// Criterio 6: «o contacto X, com o estado de X, nao le encomendas,
// consentimentos nem `price_quotes` de Y (0 linhas, 3 tools de leitura
// testadas)». Os dois contactos estao no **mesmo** tenant, pelo que a RLS por
// `tenant_id` nao defende nada aqui: o que defende, ou nao, e o predicado que o
// repositorio escreve.
//
// Cada leitura faz-se **duas vezes**: com X (que nao pode trazer nada de Y) e
// com Y (a sonda positiva — se a leitura de Y nao trouxer o canario de Y, a
// primeira afirmacao e verde sem ter medido nada).

const LEITURAS = ["encomendas", "cotacoes", "consentimentos"] as const;
type Leitura = (typeof LEITURAS)[number];

interface Contacto {
  readonly id: string;
  readonly canarios: Record<string, string>;
}

function contactos(): { x: Contacto; y: Contacto } | null {
  const bruto = jsonDoAmbiente("KAMBA_X01_CONTACTOS");
  if (bruto === null) return null;
  const ler = (chave: string): Contacto | null => {
    const valor = bruto[chave];
    if (typeof valor !== "object" || valor === null) return null;
    const registo = valor as Record<string, unknown>;
    const id = String(registo["id"] ?? "");
    if (id === "") return null;
    const mapa = (registo["canarios"] ?? {}) as Record<string, unknown>;
    return {
      id,
      canarios: Object.fromEntries(
        Object.entries(mapa).map(([tabela, item]) => [tabela, String(item)]),
      ),
    };
  };
  const x = ler("x");
  const y = ler("y");
  if (x === null || y === null) return null;
  return { x, y };
}

async function grupoDoContacto(relatorio: Relatorio): Promise<void> {
  const tenantA = ambiente("KAMBA_X01_TENANT_A");

  function semExecucao(nota: string): void {
    for (const leitura of LEITURAS) {
      for (const quem of ["x", "y"] as const) {
        relatorio.contacto.push({
          leitura,
          contacto: quem,
          executado: false,
          corpo: "",
          nota,
        });
      }
    }
  }

  const pares = contactos();
  if (pares === null) {
    semExecucao(
      "KAMBA_X01_CONTACTOS nao veio no ambiente (ou nao tem `x.id` e `y.id`): " +
        "sem os dois contactos do mesmo tenant nao ha eixo de contacto a medir.",
    );
    return;
  }

  const configuracao = configuracaoDoPg();
  if (configuracao === null) {
    semExecucao(
      "KAMBA_X01_PG nao veio no ambiente: as tres leituras por contacto correm " +
        "contra `platform.orders_mirror`, `platform.price_quotes` e " +
        "`platform.consent_event`, e sem ligacao a base nao se mede nenhuma.",
    );
    return;
  }

  let cliente: ClienteDePg;
  try {
    cliente = await ligar(configuracao);
  } catch (erro) {
    semExecucao(`nao se conseguiu ligar a base com KAMBA_X01_PG: ${razao(erro)}`);
    return;
  }

  try {
    const guarda = await importarDoRepo("packages/core-ts/src/tenant_guard/index.ts");
    const comTenant = guarda["comTenant"] as <T>(
      cliente: unknown,
      tenant: unknown,
      trabalho: (c: unknown) => Promise<T>,
    ) => Promise<T>;

    // **Uma transaccao para as seis leituras.** O contexto de tenant vai por
    // `set_config(..., true)`, e e o mesmo nas seis: o eixo que se mede e o do
    // contacto, nao o do tenant.
    const entradas = await comTenant(cliente, tenantA, async (dentro) =>
      lerPorContacto(dentro as ClienteDePg, tenantA, pares.x, pares.y),
    );
    relatorio.contacto.push(...entradas);
  } catch (erro) {
    semExecucao(`a transaccao do eixo de contacto falhou: ${razao(erro)}`);
  } finally {
    await cliente.end().catch(() => undefined);
  }
}

/**
 * O repo-base do COM, ligado a esta transaccao.
 *
 * `merchantId` e um sentinela e nao um identificador do Registo: as tres
 * leituras usam **so** o `noTenant`, e o `merchantId` do repo-base e lido apenas
 * pelo `noMerchant` e pelo `inserirNoMerchant`. Resolve-lo por
 * `SQL_MERCHANT_DO_TENANT` era ir a base buscar um valor que nada nesta
 * transaccao chega a usar. O que **nao** se faz e passa-lo vazio: o repo-base
 * recusa-o (`MerchantEmFaltaError`), e com razao.
 */
async function repoDoTenant(
  dentro: ClienteDePg,
  tenantA: string,
): Promise<Record<string, unknown>> {
  const base = await importarDoRepo("services/com/src/repo-base/index.ts");
  const repoBase = base["repoBase"] as (
    cliente: unknown,
    tenantId: string,
    merchantId: string,
  ) => Record<string, unknown>;
  return repoBase(dentro, tenantA, "x01-merchant-nao-usado");
}

/**
 * Os parametros de uma leitura, descobertos no *seed* para **um** contacto.
 *
 * ## Porque e que a descoberta existe, e porque e que nao e a leitura
 *
 * As tres leituras do criterio 6 nao recebem «o contacto» e mais nada: o
 * `SQL_PEDIDO_POR_PAGAR` quer um `draft_hash` e uma janela de trinta minutos, o
 * `SQL_COTACAO_VALIDA` quer um `(sku, qty)` e um instante, o `SQL_ESTADO` quer
 * uma finalidade. Esses argumentos sao dados do *seed*, e inventa-los dava zero
 * linhas a todos os contactos — que e a forma de «X nao ve Y» ficar verde por
 * ausencia, exactamente o que o `C-01/base` existe para apanhar.
 *
 * Por isso ha uma consulta de descoberta por leitura e por contacto. **Ela nao
 * e a afirmacao**: localiza os argumentos, e a leitura sob ensaio continua a
 * ser a funcao do repositorio, com o predicado que ela escreve. E e por contacto
 * e nao de Y para os dois, porque a bateria exige as **duas** sondas positivas —
 * a leitura de X traz o canario de X, a de Y traz o de Y — e so depois a
 * ausencia: a de X nao traz o de Y.
 */
interface ParametrosDescobertos {
  readonly valores: Record<string, unknown> | null;
  readonly nota: string;
}

/**
 * Corre `corpo` dentro de um ponto de salvaguarda.
 *
 * **Uma leitura que falhe nao leva as outras cinco consigo.** As seis leituras
 * partilham uma transaccao — e no PostgreSQL uma instrucao que levanta **aborta
 * a transaccao inteira**: tudo o que vinha depois falhava com `25P02`, as seis
 * entradas saiam com a mesma nota, e quem lesse o relatorio nao sabia qual das
 * tres tabelas e que faltava. Com o ponto, a falha fica na entrada a que
 * pertence. E a mesma tecnica, e a mesma razao, do `SQL_PONTO_DE_SALVAGUARDA`
 * do `onboarding`.
 */
async function comPonto<T>(dentro: ClienteDePg, corpo: () => Promise<T>): Promise<T> {
  await dentro.query("SAVEPOINT x01_leitura");
  try {
    const resultado = await corpo();
    await dentro.query("RELEASE SAVEPOINT x01_leitura");
    return resultado;
  } catch (erro) {
    await dentro.query("ROLLBACK TO SAVEPOINT x01_leitura");
    throw erro;
  }
}

/** A primeira linha de uma descoberta, ou `null`. */
async function descobrir(
  dentro: ClienteDePg,
  sql: string,
  parametros: readonly unknown[],
  queFalta: string,
): Promise<ParametrosDescobertos> {
  try {
    const { rows } = await comPonto(dentro, () => dentro.query(sql, parametros));
    const linha = rows[0];
    return linha === undefined ? { valores: null, nota: queFalta } : { valores: linha, nota: "" };
  } catch (erro) {
    return { valores: null, nota: `a consulta de descoberta falhou: ${razao(erro)}` };
  }
}

/** Um valor de tempo do PostgreSQL, como `Date`. */
function instante(valor: unknown): Date {
  return valor instanceof Date ? valor : new Date(String(valor));
}

async function lerPorContacto(
  dentro: ClienteDePg,
  tenantA: string,
  x: Contacto,
  y: Contacto,
): Promise<EntradaDeContacto[]> {
  const entradas: EntradaDeContacto[] = [];
  const repo = await repoDoTenant(dentro, tenantA);

  const encomendas = await importarDoRepo("services/com/src/orders/create_order.ts");
  const pedidoPorPagar = encomendas["pedidoPorPagar"] as (
    e: Record<string, unknown>,
    contactId: string,
    hash: unknown,
    chaveActual: string,
    agora: Date,
  ) => Promise<unknown>;

  const produtos = await importarDoRepo("services/com/src/produtos/produtos.ts");
  // **Cinco argumentos, e o `contactId` e o segundo.** O KAM-179 acrescentou-o
  // por decisao do fundador de 2026-11-04: a cotacao e por contacto.
  //
  // O `as` e uma afirmacao ao verificador de tipos e **nao** uma verificacao: o
  // modulo entra por `importarDoRepo`, em execucao, e um `as` errado nao da erro
  // de compilacao nenhum — da um argumento no sitio errado. Medido, e custou
  // tres voltas de CI: enquanto este tipo dizia quatro argumentos e a funcao ja
  // tinha cinco, a chamada punha a `Date` no parametro `qty`, o
  // `Number.isInteger(qty)` dava falso e a leitura devolvia `VALIDATION_ERROR`.
  // **E so no CI**, porque o *runner* testa o PR fundido com a `main` e esta
  // maquina testava o ramo sozinho.
  const getValidQuote = produtos["getValidQuote"] as (
    r: Record<string, unknown>,
    contactId: string,
    sku: string,
    qty: number,
    agora: Date,
  ) => Promise<unknown>;

  const consultasDoConsentimento = await importarDoRepo(
    "packages/core-ts/src/consentimento/consultas.ts",
  );
  const sqlDoEstado = String(consultasDoConsentimento["SQL_ESTADO"]);
  const decisao = await importarDoRepo("packages/core-ts/src/consentimento/decisao.ts");
  const estadoDoConsentimento = decisao["estadoDoConsentimento"] as (
    linha: unknown,
    versaoVigente: string,
  ) => string;
  // A finalidade por omissao vem do contrato e nao de um literal: e o
  // `FINALIDADE_DO_AVISO` que o `ConsentGate.estado()` usa quando quem chama
  // nao a diz, e repeti-la aqui era uma segunda fonte para a mesma regra.
  const contratoDoConsentimento = await importarDoRepo(
    "packages/core-ts/src/consentimento/contrato.ts",
  );
  const FINALIDADE_DO_CONSENTIMENTO = String(
    contratoDoConsentimento["FINALIDADE_DO_AVISO"] ?? "transacao",
  );

  /** Uma entrada por `(leitura, contacto)`, mesmo quando a leitura falhou. */
  async function registar(
    leitura: Leitura,
    quem: "x" | "y",
    nota: string,
    corpo: () => Promise<unknown>,
  ): Promise<void> {
    try {
      entradas.push({
        leitura,
        contacto: quem,
        executado: true,
        corpo: serializar(await comPonto(dentro, corpo)),
        // A nota acompanha uma leitura **executada** quando ha algo a dizer
        // sobre o que ela consegue devolver. A bateria so le a nota quando
        // `executado` e falso; esta e para quem ler o relatorio.
        nota,
      });
    } catch (erro) {
      entradas.push({
        leitura,
        contacto: quem,
        executado: false,
        corpo: "",
        nota: `a leitura lancou: ${razao(erro)}`,
      });
    }
  }

  for (const [quem, contacto] of [
    ["x", x],
    ["y", y],
  ] as const) {
    // --- encomendas: `pedidoPorPagar`, que corre o `SQL_PEDIDO_POR_PAGAR` ---
    //
    // E a **unica** leitura de `platform.orders_mirror` deste modulo que filtra
    // por contacto (`AND m.contact_id = $3`); o `SQL_LER` filtra por
    // `(tenant_id, id)`, e o `id` de uma encomenda nao e um identificador de
    // contacto.
    //
    // **E a projeccao dela nao inclui o `intent_key`**, que e a coluna onde o
    // `semente.py` poe o canario desta tabela. O condutor executa a leitura e
    // reporta o que ela devolveu; quem le o relatorio precisa de saber que o
    // canario nao cabe nesta resposta, e e o que a nota diz.
    const doRecibo = await descobrir(
      dentro,
      `SELECT i.draft_hash, i.intent_key, m.criado_at
         FROM platform.order_intents i
         JOIN platform.orders_mirror m
           ON m.tenant_id = i.tenant_id AND m.id = i.order_id
        WHERE i.tenant_id = $1
          AND i.estado = 'concluida'
          AND m.contact_id = $2
          AND m.estado IN ('criada', 'aguarda_pagamento', 'pendente_confirmacao')
          AND m.deleted_at IS NULL
        ORDER BY m.criado_at DESC
        LIMIT 1`,
      [tenantA, contacto.id],
      "o *seed* nao tem, para este contacto, uma encomenda por pagar com " +
        "recibo `concluida`: o `SQL_PEDIDO_POR_PAGAR` junta " +
        "`platform.order_intents` por `order_id` e por `draft_hash`, e a " +
        "receita de `orders_mirror` nao escreve recibo nenhum. A leitura corre " +
        "e devolve `null` — nao por isolamento, por ausencia.",
    );
    const notaDaEncomenda =
      doRecibo.nota ||
      "a projeccao do `SQL_PEDIDO_POR_PAGAR` e " +
        "`(id, numero_publico, estado, total_minor, currency, criado_at)` e " +
        "**nao** inclui o `intent_key`, que e a coluna do canario desta tabela.";
    // Sem linha descoberta, os argumentos saem do canario do proprio contacto:
    // deterministico, e deixa a chamada acontecer em vez de a saltar.
    const hash =
      doRecibo.valores?.["draft_hash"] ??
      createHash("sha256")
        .update(contacto.canarios["platform.orders_mirror"] ?? contacto.id, "utf8")
        .digest();
    const criadoEm = doRecibo.valores?.["criado_at"];
    // A janela do predicado e `m.criado_at > agora - 30 min`. Um minuto depois
    // da linha poe a fronteira dentro da janela sem depender da hora a que o
    // *gate* corre — a mesma razao por que o SQL recebe o instante como
    // argumento em vez de chamar `now()`.
    const agoraDaEncomenda =
      criadoEm === undefined ? new Date() : new Date(instante(criadoEm).getTime() + 60_000);
    // O `$5` do predicado exclui o recibo da propria chamada: passa-se uma
    // chave que **nao** e a da linha, para que a linha nao seja excluida por ele.
    const chaveActual = `x01-chave-que-nao-e-a-da-linha-${quem}`;
    await registar("encomendas", quem, notaDaEncomenda, () =>
      pedidoPorPagar(
        { ctx: { tenantId: tenantA, contactId: contacto.id }, repo, emitir: dentro },
        contacto.id,
        hash,
        chaveActual,
        agoraDaEncomenda,
      ),
    );

    // --- cotacoes: `getValidQuote`, que corre o `SQL_COTACAO_VALIDA` --------
    //
    // **Este predicado nao filtra por contacto**, e nao e omissao do condutor:
    // `platform.price_quotes` tem `contact_id uuid NOT NULL` (revisao `0028`) e
    // o `SQL_COTACAO_VALIDA` filtra `(tenant_id, sku, qty, estado, valida_ate)`
    // e mais nada. A leitura «como X» e por isso a leitura **pelo `sku` de X** —
    // e como o canario desta tabela e o proprio `sku`, pedir o de X devolve o
    // de X. A nota di-lo, porque a bateria compara canarios e nao predicados.
    const daCotacao = await descobrir(
      dentro,
      `SELECT sku, qty, valida_ate
         FROM platform.price_quotes
        WHERE tenant_id = $1 AND contact_id = $2 AND estado = 'emitida'
        ORDER BY criado_at DESC
        LIMIT 1`,
      [tenantA, contacto.id],
      "o *seed* nao tem, para este contacto, uma cotacao `emitida` em " +
        "`platform.price_quotes`: a leitura corre e devolve `null` por ausencia.",
    );
    const notaDaCotacao =
      daCotacao.nota ||
      "o `SQL_COTACAO_VALIDA` filtra `(tenant_id, contact_id, sku, qty, " +
        "estado, valida_ate)` desde o KAM-179. X e Y tem o **mesmo** " +
        "`(sku, qty)` por desenho da semente, pelo que o que separa as duas " +
        "linhas e o predicado do contacto e nada mais — e e isso que esta " +
        "leitura mede.";
    const sku = String(
      daCotacao.valores?.["sku"] ?? contacto.canarios["platform.price_quotes"] ?? "",
    );
    const qty = Number(daCotacao.valores?.["qty"] ?? 1);
    const validaAte = daCotacao.valores?.["valida_ate"];
    // `valida_ate > $4`: um segundo antes do limite poe a cotacao dentro da
    // validade sem depender da hora do *gate*.
    const agoraDaCotacao =
      validaAte === undefined ? new Date() : new Date(instante(validaAte).getTime() - 1_000);
    // **Os tres argumentos resolvidos vao na `nota`.** O `getValidQuote` devolve
    // `VALIDATION_ERROR` por uma unica razao — `qty` nao inteiro positivo — e
    // quando isso apareceu no CI (verde na maquina de quem escreve, vermelho no
    // *runner*) nao havia como saber de onde o `qty` tinha vindo. O tipo vai com
    // o valor porque `Number("1")` e `Number(1)` dao o mesmo numero e nao o
    // mesmo diagnostico.
    const argumentosDaCotacao =
      ` [argumentos: sku=${JSON.stringify(sku)}` +
      ` qty=${JSON.stringify(qty)} (${typeof (daCotacao.valores?.["qty"])}` +
      `=${JSON.stringify(daCotacao.valores?.["qty"] ?? null)})` +
      ` agora=${agoraDaCotacao.toISOString()}]`;
    await registar("cotacoes", quem, notaDaCotacao + argumentosDaCotacao, () =>
      getValidQuote(
        {
          repo,
          emitir: dentro,
          ids: {},
          ctx: {
            tenantId: tenantA,
            contactId: contacto.id,
            actor: "cliente",
            traceId: "x01",
          },
        },
        // O `contactId` e o segundo argumento desde o KAM-179, e e **ele** que
        // esta leitura mede: X e Y tem o mesmo `(sku, qty)`.
        contacto.id,
        sku,
        qty,
        agoraDaCotacao,
      ),
    );

    // --- consentimentos: o `SQL_ESTADO`, como o `ConsentGate.estado` o corre -
    //
    // Corre-se a **constante** e nao so o metodo, e a razao e medida: o
    // `ConsentGate.estado()` passa a linha pelo `estadoDoConsentimento`, que
    // devolve `"ausente" | "valido" | "desactualizado"` e **deixa cair o
    // `text_version`** — que e exactamente a coluna onde o `semente.py` poe o
    // canario desta tabela. Pelo metodo sozinho a sonda positiva era cega: o
    // canario nunca podia aparecer, e «X nao ve Y» ficava verde por construcao.
    // Reporta-se o que o SQL devolveu **e** o veredicto do metodo, para que os
    // dois se leiam no mesmo relatorio.
    const doConsentimento = await descobrir(
      dentro,
      `SELECT purpose, text_version
         FROM platform.consent_actual
        WHERE tenant_id = $1 AND contact_id = $2
        LIMIT 1`,
      [tenantA, contacto.id],
      "o *seed* nao tem, para este contacto, uma linha em " +
        "`platform.consent_actual` (a vista sobre `platform.consent_event`): a " +
        "leitura corre e devolve zero linhas por ausencia.",
    );
    const finalidade = String(doConsentimento.valores?.["purpose"] ?? FINALIDADE_DO_CONSENTIMENTO);
    const versaoVigente = String(doConsentimento.valores?.["text_version"] ?? "");
    const notaDoConsentimento =
      doConsentimento.nota ||
      "o `SQL_ESTADO` devolve `(accepted, text_version)`; o " +
        "`ConsentGate.estado()` colapsa as duas num veredicto e deixa cair o " +
        "`text_version`, que e a coluna do canario. O `corpo` leva as duas " +
        "coisas: as linhas do SQL e o veredicto do metodo.";
    await registar("consentimentos", quem, notaDoConsentimento, async () => {
      // Os mesmos tres argumentos, pela mesma ordem, que o
      // `ConsentGate.estado(tenantId, contactId, versaoVigente, finalidade)`
      // passa ao `bd.query`.
      const { rows } = await dentro.query(sqlDoEstado, [tenantA, contacto.id, finalidade]);
      return {
        linhas: rows,
        // O veredicto que o `ConsentGate.estado` devolveria a quem o chamasse.
        estadoDoGate: estadoDoConsentimento(rows[0] ?? null, versaoVigente),
      };
    });
  }

  return entradas;
}

// ------------------------------------------------------ a API interna do COM
//
// As dezassete superficies da API interna do COM: as quinze rotas
// `POST /internal/*` (sete do KAM-178, as duas do painel do dono do KAM-099, as
// duas leituras do KAM-190, o `screen` do KAM-222, as duas do Catalogo AI do
// KAM-119 e o contacto da encomenda do KAM-206), o `GET /metrics` e o
// `ALL /internal/*` da app construida **sem** a API montada.
//
// ## A propriedade que este grupo mede, e a que ele **nao** mede
//
// Nao mede «a RLS filtra»: com um duplo da porta nao ha base de dados nenhuma.
// Mede esta, que e a da camada que o ticket acrescentou:
//
//     o `ctx` que a porta recebe tem o tenant do cabecalho `x-kamba-tenant`
//     e mais nada
//
// Um corpo que nomeie o tenant B, um contacto de B ou identificadores de B nao
// desloca o `ctx` para B, e nada de B volta na resposta. O `ctxDoPedido` do
// `api/interna.ts` le o tenant **so** do cabecalho; esta e a afirmacao que o
// torna falsificavel, e por isso o duplo da porta **registra o `ctx` de cada
// chamada** e o relatorio leva essa medicao numa `nota` por entrada — e o lado
// Python que a acusa.
//
// Que o Registo real recuse o `order_id` de B e **outra** afirmacao, do
// adaptador e da RLS: corre no X-03 e no X-05, com base. Fica dito em vez de
// ficar por dizer.
//
// ## Os duplos nao ecoam o pedido, e e isso que impede um achado inventado
//
// Um duplo que devolvesse o `sku` ou o `order_id` que recebeu punha o canario
// de B na resposta **por o condutor o ter mandado** — a mesma armadilha que o
// grupo do webhook descreve ao nao assinar com o anel da Meta. Os valores
// destes duplos sao fixos e de A: nenhum depende do corpo do ataque.
//
// ## O duplo recusa, como o `graph` e o `cofre` do grupo dos canais
//
// Em `modo: "recusa"` a porta devolve `NOT_FOUND` a **todas** as chamadas. E
// escolha com razao: o criterio 3 pede estados **uniformes** nas tres
// tentativas de cada rota, e um duplo que servisse o corpo legitimo de A com
// 200 e recusasse os de B com 404 media a decisao do duplo e nao a da rota. O
// 404 uniforme deixa medir o que esta bateria quer — o `ctx` que chegou a
// porta, e a ausencia de B na resposta — sem que o estado diga nada sobre B.
//
// A metade positiva corre num **segundo** app, em `modo: "sonda"`, e nao entra
// nas entradas do relatorio: se entrasse, o 200 dela quebrava a uniformidade
// que o criterio pede. O que dela vai para o relatorio e o veredicto, na
// `nota`.

/**
 * As quinze rotas, pela ordem de `services/com/src/api/interna.ts`: as sete do
 * KAM-178, as duas do painel do KAM-099, as duas leituras do KAM-190, o
 * `screen` do KAM-222, as duas do Catalogo AI do KAM-119 (o rascunho e a
 * publicacao) e o contacto da encomenda do KAM-206.
 */
const ROTAS_DO_COM = [
  "/internal/offer-view",
  "/internal/propose-cart",
  "/internal/create-order",
  "/internal/get-order",
  "/internal/list-orders",
  "/internal/transition",
  "/internal/request-owner-confirmation",
  "/internal/list-offers",
  "/internal/update-offer",
  "/internal/get-offer",
  "/internal/channel-view",
  "/internal/screen",
  "/internal/upsert-product-draft",
  "/internal/publish-product",
  "/internal/order-contact",
] as const;

/** O `item` enumerado de uma das quinze. Copiado do caso, nao derivado dele. */
function itemDoCom(rota: string): string {
  return `rota:com:api/interna:apiInterna:POST:${rota}`;
}

const ITEM_DAS_METRICAS_DO_COM = "rota:com:api/interna:rotaDasMetricas:GET:/metrics";
const ITEM_SEM_API_DO_COM = "rota:com:app:createApp:ALL:/internal/*";

/**
 * A rota por onde se ataca o `ALL /internal/*`.
 *
 * O item enumerado e um padrao, e um padrao nao se pede: pede-se um caminho que
 * ele apanhe. Esta e uma das nove, para que o ataque seja o mesmo que as outras
 * entradas levam — a diferenca medida e so a app nao ter a API montada.
 */
const ROTA_DE_AMOSTRA_DO_COM = "/internal/get-order";

/**
 * A credencial interna do duplo.
 *
 * Obviamente falsa e de baixa entropia, pela razao que
 * `services/gwy/tests/webhook.test.ts` escreve ao lado do seu: um valor com
 * forma de segredo atribuido a um nome que significa segredo dispara o *gate* 9,
 * e tem razao em disparar.
 */
const INTERNO_DE_ENSAIO = "ensaio-x01-interno-do-com";

/** Os valores de A. Fixos: nenhum duplo devolve o que o ataque mandou. */
const SKU_DE_A = "arroz-5kg-de-a";
const ORDER_DE_A = "0000000a-0000-4000-8000-00000000000a";
const CONTACTO_DE_A = "0000000c-0000-4000-8000-00000000000c";
const CARRINHO_DE_A = "C7H3Q9ABCDEFGHJKMNPQRSTVWX";
/** A versao optimista de uma oferta de A (KAM-099): o `atualizado_at` com microssegundos. */
const VERSAO_DE_A = "2026-11-05T10:00:00.000001Z";

/**
 * O contacto de B quando o `KAMBA_X01_TENANT_B` nao tem forma de UUID.
 *
 * O `rascunhoDoCorpo` exige `eUuid(contact_id)`: um valor sem essa forma dava
 * **400** onde os outros ataques dao 404, e a falta de uniformidade passava a
 * ser culpa da forma do corpo em vez do identificador — que e exactamente o que
 * o grupo dos canais evita ao usar o mesmo `session_info` em todos os ataques.
 * Qual dos dois se usou vai na `nota` (`ids-de-b=`), porque um substituto quer
 * dizer que o identificador real de B nunca entrou nos campos de dominio.
 */
const CONTACTO_DE_B_SUBSTITUTO = "0000000b-0000-4000-8000-00000000000b";

/** O `ctx` que o corpo transporta: o `actor` e o `trace_id` do turno (§3.39). */
const CTX_DO_CORPO_DO_COM = {
  actor: { kind: "agente", id: "grafo-vendedor" },
  trace_id: "x01-com-interna",
};

/** Uma chamada que chegou ao duplo da porta, e o `ctx` com que chegou. */
interface ChamadaDaPorta {
  readonly metodo: string;
  readonly tenantId: string;
}

type ModoDoDuplo = "recusa" | "sonda";

/**
 * As operacoes do COM, em duplo, com o registo do `ctx` de cada chamada.
 *
 * A forma e a de `services/com/tests/api.interna.test.ts` — a porta mais o
 * `proposeCart` e o `createOrder` das operacoes — e nao se reinventa. As nove
 * rotas chamam **nove** operacoes (o `despachar` chama cinco da porta e quatro
 * das operacoes: as duas da saga e as duas do painel do KAM-099); os restantes
 * metodos da porta nao se duplicam, porque um duplo que nada chama e codigo que
 * ninguem mede.
 *
 * O `registo` e a medicao central deste grupo: a afirmacao «o `ctx` tem o
 * tenant do cabecalho e mais nada» le-se nele, e nao na resposta.
 *
 * **Os valores de `modo: "sonda"` nao sao as formas do Registo real.** Levam o
 * canario de A para que a sonda positiva possa seguir o caminho porta →
 * resposta; o que eles tem de ser e **fixos**, e sao.
 */
function operacoesDeEnsaioDoCom(
  modo: ModoDoDuplo,
  canarioDeA: string,
  ok: (valor: unknown) => unknown,
  erro: (codigo: string) => unknown,
): { operacoes: Record<string, unknown>; registo: ChamadaDaPorta[] } {
  const registo: ChamadaDaPorta[] = [];

  /**
   * O canario de A em `linhas[0].sku`, e nao num campo inventado.
   *
   * E uma razao de caminho: o `POST /internal/propose-cart` reescreve a resposta
   * campo a campo (`cart_id`, `total_minor`, `currency`,
   * `exige_confirmacao_do_dono`, `linhas`) e deixa cair tudo o mais — um canario
   * noutro sitio nunca chegava a resposta daquela rota, e a sonda positiva dela
   * ficava cega por construcao.
   */
  const valorDeA = (extra: Record<string, unknown>): Record<string, unknown> => ({
    linhas: [{ sku: canarioDeA, qty: 1 }],
    ...extra,
  });

  /** Registra a chamada e devolve o que o `modo` manda. */
  const servir = (metodo: string, ctx: unknown, valor: Record<string, unknown>) => {
    registo.push({
      metodo,
      tenantId: String((ctx as { tenantId?: unknown } | null)?.tenantId ?? ""),
    });
    return modo === "sonda" ? ok(valor) : erro("NOT_FOUND");
  };

  const porta = {
    async getOfferView(ctx: unknown) {
      return servir(
        "getOfferView",
        ctx,
        valorDeA({
          sku: SKU_DE_A,
          precoTipo: "fixo",
          precoDisplay: canarioDeA,
          stockModo: "garantido",
          disponibilidade: "disponivel",
          atualizadoAt: "2026-11-05T10:00:00.000Z",
        }),
      );
    },
    async getOrder(ctx: unknown) {
      return servir(
        "getOrder",
        ctx,
        valorDeA({
          orderId: ORDER_DE_A,
          numeroPublico: "K7H3Q1",
          estado: "criada",
          version: 1,
          contactId: CONTACTO_DE_A,
          totalMinor: 2_500_000n,
          currency: "AOA",
          criadoAt: "2026-11-05T10:00:00.000Z",
        }),
      );
    },
    async listOrders(ctx: unknown) {
      return servir("listOrders", ctx, {
        itens: [
          valorDeA({
            orderId: ORDER_DE_A,
            numeroPublico: "K7H3Q1",
            estado: "criada",
          }),
        ],
        proximo: null,
      });
    },
    async transition(ctx: unknown) {
      return servir(
        "transition",
        ctx,
        valorDeA({
          orderId: ORDER_DE_A,
          numeroPublico: "K7H3Q1",
          estado: "paga",
          version: 2,
        }),
      );
    },
    async requestOwnerConfirmation(ctx: unknown) {
      return servir("requestOwnerConfirmation", ctx, valorDeA({ estado: "pedida" }));
    },
    // KAM-119: o rascunho de produto. A rota reescreve a resposta (`sku`,
    // `registo_id`) e deixa cair o resto, e por isso o canario de A vai no
    // `registoId`, que e o campo que ela leva.
    async upsertProductDraft(ctx: unknown) {
      return servir("upsertProductDraft", ctx, valorDeA({ sku: SKU_DE_A, registoId: canarioDeA }));
    },
  };

  const operacoes: Record<string, unknown> = {
    porta,
    async proposeCart(ctx: unknown) {
      return servir(
        "proposeCart",
        ctx,
        valorDeA({
          cartId: CARRINHO_DE_A,
          totalMinor: 2_500_000n,
          currency: "AOA",
          exigeConfirmacaoDoDono: false,
          // O `draftHash` **nao sai** da rota (o `api/interna.ts` deixa-o cair);
          // esta aqui porque o campo existe no valor que o modulo devolve.
          draftHash: Buffer.alloc(32, 1),
        }),
      );
    },
    async createOrder(ctx: unknown) {
      return servir(
        "createOrderDaSaga",
        ctx,
        valorDeA({
          orderId: ORDER_DE_A,
          numeroPublico: "K7H3Q1",
          estado: "criada",
          version: 1,
          totalMinor: 2_500_000n,
          currency: "AOA",
          confirmacaoDono: "nao_aplicavel",
          repeticao: false,
          pedidoPorPagar: null,
        }),
      );
    },
    async listarOfertas(ctx: unknown) {
      return servir("listarOfertas", ctx, valorDeA({ itens: [], truncada: false }));
    },
    // KAM-190: as duas leituras do painel. O canario de A vai no `nome` da
    // oferta e num aviso do canal, que sao campos que a resposta leva.
    async obterOferta(ctx: unknown) {
      return servir(
        "obterOferta",
        ctx,
        valorDeA({ sku: SKU_DE_A, nome: canarioDeA, precoTipo: "fixo", precoMinor: 1_000_000n, versao: VERSAO_DE_A }),
      );
    },
    async vistaDoCanal(ctx: unknown) {
      return servir(
        "vistaDoCanal",
        ctx,
        valorDeA({ estado: "ativo", restrito: false, nivel: 1, tectoPedidoMinor: 5_000_000n, avisos: [canarioDeA] }),
      );
    },
    // KAM-119: a publicacao conferida. A real devolve `void`; a rota passa o
    // valor tal como vem, e o canario de A vai nas `linhas` do `valorDeA`.
    async publicarProduto(ctx: unknown) {
      return servir("publicarProduto", ctx, valorDeA({ estado: "publicado" }));
    },
    // KAM-222: o `screen`. O canario de A vai numa regra, que a resposta leva.
    async screen(ctx: unknown) {
      return servir(
        "screen",
        ctx,
        valorDeA({ decisao: "permitida", regras: [canarioDeA], versao_politica: "2026.11.0", confianca: 0.95 }),
      );
    },
    // KAM-206: o contacto da encomenda. O canario de A vai na mascara, que e o
    // campo que a resposta leva; o real nunca devolve o telefone em claro.
    async contactoDaEncomenda(ctx: unknown) {
      return servir("contactoDaEncomenda", ctx, valorDeA({ orderId: ORDER_DE_A, telefoneMascarado: canarioDeA }));
    },
    async alterarOferta(ctx: unknown) {
      return servir(
        "alterarOferta",
        ctx,
        valorDeA({
          sku: SKU_DE_A,
          nome: canarioDeA,
          precoTipo: "fixo",
          precoMinor: 1_000_000n,
          versao: VERSAO_DE_A,
        }),
      );
    },
  };

  return { operacoes, registo };
}

async function grupoDaApiInternaDoCom(relatorio: Relatorio): Promise<void> {
  const tenantA = ambiente("KAMBA_X01_TENANT_A").toLowerCase();
  const tenantB = ambiente("KAMBA_X01_TENANT_B");
  const canario = canarioOuSubstituto();
  // O canario de **A**, que o ambiente nao traz: a ponte passa so os de B (e o
  // oraculo so proibe esses). Este e deterministico a partir do tenant e tem a
  // forma do `oraculo.FORMA_DO_CANARIO`, para que se leia como o que e — o valor
  // que tem de **chegar** a resposta, e nao o que nao pode chegar.
  const canarioDeA = `canario_a_${createHash("sha256")
    .update(`x01-com-interna:${tenantA}`, "utf8")
    .digest("hex")
    .slice(0, 32)}`;

  /** As entradas que este grupo tem de deixar, mesmo quando nao mede nada. */
  const previstas: { item: string; metodo: string; caminho: string; vezes: number }[] = [
    ...ROTAS_DO_COM.map((rota) => ({
      item: itemDoCom(rota),
      metodo: "POST",
      caminho: rota,
      vezes: 3,
    })),
    {
      item: ITEM_DAS_METRICAS_DO_COM,
      metodo: "GET",
      caminho: "/metrics",
      vezes: 1,
    },
    {
      item: ITEM_SEM_API_DO_COM,
      metodo: "POST",
      caminho: ROTA_DE_AMOSTRA_DO_COM,
      vezes: 3,
    },
  ];

  function semExecucao(nota: string): void {
    for (const prevista of previstas) {
      for (let vez = 0; vez < prevista.vezes; vez += 1) {
        relatorio.rotas.push({
          item: prevista.item,
          metodo: prevista.metodo,
          caminho: prevista.caminho,
          estado: 0,
          corpo: "",
          cabecalhos: {},
          executado: false,
          nota,
        });
      }
    }
  }

  let createApp: (log: undefined, api?: Record<string, unknown>) => AppHono;
  let cabecalhoInterno: string;
  let cabecalhoTenant: string;
  let ok: (valor: unknown) => unknown;
  let erro: (codigo: string) => unknown;
  let eUuid: (valor: unknown) => boolean;
  try {
    const app = await importarDoRepo("services/com/src/app.ts");
    const interna = await importarDoRepo("services/com/src/api/interna.ts");
    const port = await importarDoRepo("services/com/src/port/index.ts");
    createApp = app["createApp"] as typeof createApp;
    cabecalhoInterno = String(interna["CABECALHO_INTERNO"]);
    cabecalhoTenant = String(interna["CABECALHO_TENANT"]);
    ok = port["ok"] as typeof ok;
    erro = port["erro"] as typeof erro;
    eUuid = port["eUuid"] as typeof eUuid;
  } catch (falha) {
    semExecucao(`nao se conseguiu importar o COM: ${razao(falha)}`);
    return;
  }

  // O identificador de B que entra nos campos de dominio que exigem UUID. Ver
  // o `CONTACTO_DE_B_SUBSTITUTO`.
  const bTemUuid = eUuid(tenantB);
  const contactoDeB = bTemUuid ? tenantB : CONTACTO_DE_B_SUBSTITUTO;
  const marcaDosIds = bTemUuid ? "ids-de-b=tenant-b" : "ids-de-b=substituto";
  // Sem `KAMBA_X01_CANARIOS` o `canarioOuSubstituto` devolve um substituto, e os
  // ataques passam a levar uma cadeia que nao e de B nenhum: «nada de B saiu»
  // ficava verde por B nunca ter entrado. Diz-se numa marca em vez de se calar.
  const marcaDoCanario =
    canarios().length === 0 ? "canario-de-b=ausente" : "canario-de-b=presente";

  /** O corpo legitimo de cada rota. Identificadores de A, e so de A. */
  function corpoDeA(rota: string): Record<string, unknown> {
    const rascunho = {
      contact_id: CONTACTO_DE_A,
      draft_id: "rascunho-de-a",
      draft_version: 1,
      entrega_modo: "levantamento",
      linhas: [{ sku: SKU_DE_A, qty: 1 }],
    };
    if (rota === "/internal/offer-view") return { sku: SKU_DE_A };
    if (rota === "/internal/get-offer") return { sku: SKU_DE_A };
    if (rota === "/internal/list-offers" || rota === "/internal/channel-view") return {};
    if (rota === "/internal/update-offer") {
      return { sku: SKU_DE_A, preco_tipo: "fixo", preco_minor: "1000000", versao: VERSAO_DE_A };
    }
    if (rota === "/internal/screen") {
      // KAM-230: a finalidade (a das condicoes, que a operacao confere com o
      // sujeito) e o prazo sao obrigatorios; sem eles a rota recusa antes da porta.
      return {
        sujeito_tipo: "condicoes",
        sujeito_ref: ORDER_DE_A,
        textos: ["entrega de A"],
        finalidade: "classificacao_de_condicoes",
        prazo_ms: 6_000,
      };
    }
    if (rota === "/internal/upsert-product-draft") {
      return { sku: SKU_DE_A, nome: "arroz de A", preco_tipo: "fixo", preco_minor: "1000000" };
    }
    if (rota === "/internal/publish-product") {
      return { sku: SKU_DE_A, confirmacao: { actor_id: "mensagem-de-a", em: "2026-11-05T10:00:00.000Z" } };
    }
    if (rota === "/internal/propose-cart") return rascunho;
    if (rota === "/internal/create-order") {
      return { ...rascunho, total_esperado_minor: "2500000", cart_id: CARRINHO_DE_A };
    }
    if (rota === "/internal/list-orders") {
      return { estado: "criada", contact_id: CONTACTO_DE_A, limite: 5 };
    }
    if (rota === "/internal/transition") {
      return {
        order_id: ORDER_DE_A,
        para: "paga",
        expected_version: 1,
        causa: "payment.confirmed",
        evento_id: "evento-de-a",
      };
    }
    return { order_id: ORDER_DE_A };
  }

  /**
   * O mesmo corpo, com os identificadores de **dominio** de B.
   *
   * O canario de B e o identificador mais forte de B que este condutor tem — e
   * a cadeia que o *seed* pos numa linha dele —, e por isso e ele que vai no
   * `sku`, no `order_id`, no `cart_id` e no `draft_id`. O `contact_id` tem de
   * ter forma de UUID (`rascunhoDoCorpo`), e e o `contactoDeB`.
   */
  function corpoDeB(rota: string): Record<string, unknown> {
    const rascunho = {
      contact_id: contactoDeB,
      draft_id: `rascunho-${canario}`,
      draft_version: 1,
      entrega_modo: "levantamento",
      linhas: [{ sku: canario, qty: 1 }],
    };
    if (rota === "/internal/offer-view") return { sku: canario };
    if (rota === "/internal/get-offer") return { sku: canario };
    // A lista do painel e o estado do canal nao recebem identificador de dominio
    // nenhum: o de B que levam sao so os campos extra do `camposDeB`.
    if (rota === "/internal/list-offers" || rota === "/internal/channel-view") return {};
    if (rota === "/internal/update-offer") {
      return { sku: canario, preco_tipo: "fixo", preco_minor: "1", versao: VERSAO_DE_A, stock: 1 };
    }
    if (rota === "/internal/screen") {
      return {
        sujeito_tipo: "condicoes",
        sujeito_ref: canario,
        categoria_declarada: canario,
        textos: [canario],
        finalidade: "classificacao_de_condicoes",
        prazo_ms: 6_000,
      };
    }
    if (rota === "/internal/upsert-product-draft") {
      return { sku: canario, nome: canario, preco_tipo: "fixo", preco_minor: "1" };
    }
    if (rota === "/internal/publish-product") {
      return { sku: canario, confirmacao: { actor_id: canario, em: "2026-11-05T10:00:00.000Z" } };
    }
    if (rota === "/internal/propose-cart") return rascunho;
    if (rota === "/internal/create-order") {
      return { ...rascunho, total_esperado_minor: "999", cart_id: canario };
    }
    if (rota === "/internal/list-orders") {
      return { estado: "criada", contact_id: contactoDeB, limite: 5 };
    }
    if (rota === "/internal/transition") {
      return {
        order_id: canario,
        para: "paga",
        expected_version: 1,
        causa: "payment.confirmed",
        evento_id: `evento-${canario}`,
      };
    }
    return { order_id: canario };
  }

  /**
   * Os campos extra que **nomeiam B** e que nenhuma rota le.
   *
   * O `ctxDoPedido` constroi o `ctx` com o tenant do cabecalho e o `actor` e o
   * `trace_id` do corpo; nao ha caminho nenhum no `api/interna.ts` que leia um
   * tenant do corpo. Estes quatro campos sao a afirmacao disso: um corpo que
   * diga `tenant_id`, `tenant` e `merchant_id` de B, e que leve o canario de B
   * num campo livre, nao desloca o `ctx`.
   */
  const camposDeB: Record<string, unknown> = {
    tenant_id: tenantB,
    tenant: tenantB,
    merchant_id: tenantB,
    nota_livre: canario,
  };

  /** Os tres ataques do criterio, por rota. */
  function ataquesAoCom(rota: string): Record<string, unknown>[] {
    return [
      // 1. Corpo valido de A, com os campos extra que nomeiam B.
      { ...CTX_DO_CORPO_DO_COM, ...corpoDeA(rota), ...camposDeB },
      // 2. Corpo valido cujos identificadores de dominio sao de B.
      { ...CTX_DO_CORPO_DO_COM, ...corpoDeB(rota) },
      // 3. Os dois ao mesmo tempo.
      { ...CTX_DO_CORPO_DO_COM, ...corpoDeB(rota), ...camposDeB },
    ];
  }

  const cabecalhosDeA: Record<string, string> = {
    "content-type": "application/json",
    [cabecalhoInterno]: INTERNO_DE_ENSAIO,
    [cabecalhoTenant]: tenantA,
  };

  let appDeRecusa: AppHono;
  let registoDeRecusa: ChamadaDaPorta[];
  let appDaSonda: AppHono;
  let registoDaSonda: ChamadaDaPorta[];
  let appSemApi: AppHono;
  try {
    const recusa = operacoesDeEnsaioDoCom("recusa", canarioDeA, ok, erro);
    registoDeRecusa = recusa.registo;
    appDeRecusa = createApp(undefined, {
      operacoes: recusa.operacoes,
      credencial: INTERNO_DE_ENSAIO,
    });
    const sonda = operacoesDeEnsaioDoCom("sonda", canarioDeA, ok, erro);
    registoDaSonda = sonda.registo;
    appDaSonda = createApp(undefined, {
      operacoes: sonda.operacoes,
      credencial: INTERNO_DE_ENSAIO,
    });
    // **Sem `api`**, que e o caminho do `ALL /internal/*`.
    appSemApi = createApp(undefined);
  } catch (falha) {
    semExecucao(`nao se conseguiu montar o COM com os duplos: ${razao(falha)}`);
    return;
  }

  /** O `ctx` de todas as chamadas que chegaram a porta, em uma marca. */
  function marcaDoCtx(chamadas: ChamadaDaPorta[]): string {
    if (chamadas.length === 0) return "ctx=nenhuma-chamada";
    return chamadas.every((chamada) => chamada.tenantId === tenantA)
      ? "ctx=a"
      : "ctx=outro-tenant";
  }

  for (const rota of ROTAS_DO_COM) {
    const item = itemDoCom(rota);
    const corpoLegitimo = JSON.stringify({ ...CTX_DO_CORPO_DO_COM, ...corpoDeA(rota) });

    // --- a sonda positiva ---------------------------------------------------
    //
    // «Zero canarios de B» e verde quando nada chega ao sitio. Esta medida diz
    // que o caminho esta vivo: a porta foi chamada com o `ctx` de A, devolveu um
    // valor com o canario de A, e esse canario **chegou a resposta**.
    registoDaSonda.length = 0;
    const sonda = await medir(item, "POST", rota, appDaSonda, {
      method: "POST",
      body: corpoLegitimo,
      headers: cabecalhosDeA,
    });
    const marcaDaSonda = !sonda.executado
      ? "sonda=lancou"
      : registoDaSonda.length === 0
        ? "sonda=sem-chamada"
        : marcaDoCtx(registoDaSonda) !== "ctx=a"
          ? "sonda=ctx-nao-e-de-a"
          : sonda.estado !== 200
            ? `sonda=estado-${sonda.estado}`
            : sonda.corpo.includes(canarioDeA)
              ? "sonda=viva"
              : "sonda=sem-canario-de-a";

    // --- as duas portas do *fail-closed* ------------------------------------
    //
    // Se nao dispararem, os duplos estao mal montados — e entao as afirmacoes
    // de cima medem outra coisa que nao a rota.
    const semCredencial = await medir(item, "POST", rota, appDeRecusa, {
      method: "POST",
      body: corpoLegitimo,
      headers: { "content-type": "application/json", [cabecalhoTenant]: tenantA },
    });
    const semTenant = await medir(item, "POST", rota, appDeRecusa, {
      method: "POST",
      body: corpoLegitimo,
      headers: {
        "content-type": "application/json",
        [cabecalhoInterno]: INTERNO_DE_ENSAIO,
      },
    });
    const comuns = [
      marcaDaSonda,
      `fecho-sem-credencial=${semCredencial.estado}`,
      `fecho-sem-tenant=${semTenant.estado}`,
      marcaDosIds,
      marcaDoCanario,
    ].join(" ");

    // --- os tres ataques ----------------------------------------------------
    for (const corpo of ataquesAoCom(rota)) {
      registoDeRecusa.length = 0;
      const medida = await medir(item, "POST", rota, appDeRecusa, {
        method: "POST",
        body: JSON.stringify(corpo),
        headers: cabecalhosDeA,
      });
      relatorio.rotas.push({
        ...medida,
        nota: medida.executado
          ? `${marcaDoCtx(registoDeRecusa)} ${comuns}`
          : medida.nota,
      });
    }
  }

  // --- o `GET /metrics` -----------------------------------------------------
  //
  // **Os contadores sobem primeiro, pelo caminho real**, e a razao e a que a
  // revisao adversarial do KAM-178 escreveu no teste daquela rota: sobre uma
  // populacao vazia, «nao ha rotulo por tenant» passava mesmo que a exposicao
  // ganhasse um, porque nao havia serie nenhuma com valor. Uma consulta sem
  // filtro e recusada pelo `repoBase` e incrementa o
  // `com_repo_filtro_em_falta_total`; uma com filtro incrementa o
  // `com_repo_consultas_total`. O que se mede e que **o que o repo-base conta e
  // o que a rota serve**, e nao o contador chamado a mao.
  let marcaDosContadores = "contadores=subidos";
  try {
    const base = await importarDoRepo("services/com/src/repo-base/index.ts");
    const repoBase = base["repoBase"] as (
      cliente: unknown,
      tenantId: string,
      merchantId: string,
    ) => unknown;
    const repo = repoBase(
      {
        async query() {
          return { rows: [] };
        },
      },
      tenantA,
      "x01-merchant-nao-usado",
    ) as { noTenant(sql: string, parametros: unknown[]): Promise<unknown> };
    await repo.noTenant("SELECT 1", []).catch(() => undefined);
    await repo.noTenant("SELECT 1 WHERE tenant_id = $1", []);
  } catch (falha) {
    // Nao e erro fatal: a leitura do `/metrics` faz-se de qualquer modo, e a
    // marca diz ao lado Python que a afirmacao correu sobre populacao vazia. O
    // `razao` vai para o `stderr` e **nao** para a `nota`, que nao leva texto
    // livre: o lado Python le marcas.
    diagnostico(`nao se conseguiram subir os contadores do COM: ${razao(falha)}\n`);
    marcaDosContadores = "contadores=nao-subidos";
  }

  const metricas = await medir(
    ITEM_DAS_METRICAS_DO_COM,
    "GET",
    "/metrics",
    appDeRecusa,
  );
  // Um **rotulo** por tenant, e nao a palavra «tenant»: a exposicao do COM tem
  // `com_repo_consultas_total{filtro="tenant"}`, onde `tenant` e o *valor* do
  // rotulo `filtro` e nao um identificador. O que o `OBS-I` proibe e um rotulo
  // chamado `tenant`, `tenant_id`, `merchant_id`, `contact_id` ou `sku`.
  const temRotuloPorTenant = /[{,]\s*(tenant|tenant_id|merchant_id|contact_id|sku)\s*=/.test(
    metricas.corpo,
  );
  const achadoDaSerie = /com_repo_consultas_total\{filtro="tenant"\} (\d+)/.exec(
    metricas.corpo,
  );
  const marcaDaSerie =
    achadoDaSerie === null
      ? "series=sem-a-serie"
      : Number(achadoDaSerie[1]) > 0
        ? "series=com-valor"
        : "series=a-zero";
  const marcaDasMetricas = temRotuloPorTenant
    ? "metricas=rotulo-por-tenant"
    : tenantA !== "" && metricas.corpo.includes(tenantA)
      ? "metricas=tenant-a-no-corpo"
      : "metricas=limpa";
  relatorio.rotas.push({
    ...metricas,
    nota: metricas.executado
      ? `${marcaDasMetricas} ${marcaDaSerie} ${marcaDosContadores}`
      : metricas.nota,
  });

  // --- o `ALL /internal/*`, na app construida **sem** `api` -----------------
  //
  // Os mesmos tres ataques a uma das nove rotas. A afirmacao e 503 uniforme e
  // **sem corpo que distinga tenants** — e isso mede-se comparando os tres
  // corpos entre si, que e a unica forma de o dizer sem inspeccionar o que a
  // app devolveu a procura de uma lista de valores proibidos.
  const semApi: EntradaDeRota[] = [];
  for (const corpo of ataquesAoCom(ROTA_DE_AMOSTRA_DO_COM)) {
    semApi.push(
      await medir(
        ITEM_SEM_API_DO_COM,
        "POST",
        ROTA_DE_AMOSTRA_DO_COM,
        appSemApi,
        {
          method: "POST",
          body: JSON.stringify(corpo),
          headers: cabecalhosDeA,
        },
      ),
    );
  }
  const corposDistintos = new Set(
    semApi.filter((entrada) => entrada.executado).map((entrada) => entrada.corpo),
  );
  const marcaSemApi =
    corposDistintos.size === 1
      ? "sem-api=corpo-igual"
      : `sem-api=corpos-distintos-${corposDistintos.size}`;
  for (const entrada of semApi) {
    relatorio.rotas.push({
      ...entrada,
      nota: entrada.executado ? marcaSemApi : entrada.nota,
    });
  }
}

// --------------------------------------------------------------- a inscricao
//
// As cinco rotas do `onboarding-web` (KAM-086). A lista e **literal** e a ordem
// e a do caso em `baterias/x01_rotas.py`, pela razao escrita nas sondas: um
// filtro fazia uma rota nova nascer coberta.
//
// ## O que se ataca aqui NAO e um `tenant_id`, e isso muda o ataque
//
// Estas rotas correm **antes de existir tenant**: o que elas isolam e o
// `onboarding_id` de um caso, e o `tenant_id` dele e pre-alocado e nunca sai
// numa resposta. Por isso o papel de «B» e um **caso** e nao um tenant, e o
// canario de B vai no nome do negocio do caso de B — que e o campo que uma fuga
// faria aparecer numa resposta.
//
// ## As cinco atacam-se de maneiras diferentes, e duas delas merecem nota
//
//   POST /api/registo       ataca-se com o **NIF de B** e com um NIF que nao
//                           existe, e exige-se o MESMO estado. E o criterio 9
//                           do bloco posto na bateria: um 200 num e um 409 no
//                           outro era a enumeracao de NIF que o criterio proibe.
//                           O oraculo e que verifica que nada de B sai no corpo
//   POST /api/actividade    ataca-se com a sessao de A a levar o `onboarding_id`
//                           de B — a troca que o teste cruzado do DoD nomeia.
//                           A referencia e um HMAC sobre o id, pelo que a troca
//                           quebra a assinatura e nao ha parametro ao lado que
//                           a possa dizer
//
// As outras tres recusam um bilhete forjado e um id nu, e o que se exige e que
// recusem **igual**.

const ITENS_DA_INSCRICAO = [
  "rota:onboarding-web:rotas:ligacao:GET:/entrar",
  "rota:onboarding-web:rotas:ligacao:POST:/api/registo",
  "rota:onboarding-web:rotas:ligacao:POST:/api/otp/reenviar",
  "rota:onboarding-web:rotas:ligacao:POST:/api/otp/verificar",
  "rota:onboarding-web:rotas:ligacao:POST:/api/actividade",
] as const;

/**
 * As chaves dos duplos. Baixa entropia e nomes que **nao** significam segredo,
 * pela razao escrita ao lado das do webhook: um valor com forma de segredo
 * atribuido a um nome que significa segredo dispara o *gate* 9, e tem razao.
 */
const OCTETO_DE_A = 0x5a;
const OCTETO_DE_ASSINATURA = 0x3c;
const OCTETO_DO_DESTINO = 0x71;

/** O NIF de B, e um que nao existe. Nenhum e um NIF real: ver o `destino.ts`. */
const NIF_DE_B = "5410000123AB";
const NIF_INEXISTENTE = "5410000999CD";
const TELEFONE_DE_B = "+244000000001";
const TELEFONE_DE_A = "+244000000002";

/**
 * Monta o `onboarding-web` com duplos, cria o caso de B com o canario dentro, e
 * ataca as cinco rotas.
 *
 * **Os modulos vem do `dist` e nao do `src`**, e isso nao e detalhe: o
 * `services/onboarding-web/src/rotas.ts` importa `@kamba/core-ts/inscricao`, que
 * resolve para `packages/core-ts/dist/inscricao/index.js`. Construir o `Registo`
 * a partir do `src` dava **duas** instancias do mesmo modulo, e o
 * `erro instanceof RegistoRecusado` da rota passava a comparar classes
 * diferentes: toda a recusa saia 500 em vez de 400, e a bateria media um defeito
 * que nao existe.
 */
async function grupoDaInscricao(relatorio: Relatorio): Promise<void> {
  const falhar = (nota: string): void => {
    for (const item of ITENS_DA_INSCRICAO) {
      relatorio.rotas.push({
        item,
        metodo: item.includes("GET") ? "GET" : "POST",
        caminho: item.split(":").slice(-1)[0] ?? "",
        estado: 0,
        corpo: "",
        cabecalhos: {},
        executado: false,
        nota,
      });
    }
  };

  let insc: Record<string, unknown>;
  let sms: Record<string, unknown>;
  let appModulo: Record<string, unknown>;
  try {
    insc = await importarDoRepo("packages/core-ts/dist/inscricao/index.js");
    sms = await importarDoRepo("packages/core-ts/dist/sms/index.js");
    appModulo = await importarDoRepo("services/onboarding-web/src/app.ts");
  } catch (erro) {
    falhar(`nao se conseguiu importar o onboarding-web: ${razao(erro)}`);
    return;
  }

  type Construtor = new (...argumentos: never[]) => unknown;
  const obter = <T>(modulo: Record<string, unknown>, nome: string): T => {
    const valor = modulo[nome];
    if (valor === undefined) throw new Error(`o modulo nao exporta ${nome}`);
    return valor as T;
  };

  try {
    const Casos = obter<Construtor>(insc, "CasosEmMemoria");
    const Contadores = obter<Construtor>(insc, "ContadoresEmMemoria");
    const OtpMem = obter<Construtor>(insc, "OtpEmMemoria");
    const Otp = obter<Construtor>(insc, "Otp");
    const SmsLocal = obter<Construtor>(insc, "OtpPorSmsLocal");
    const AntiAbuso = obter<Construtor>(insc, "AntiAbuso");
    const Registo = obter<Construtor>(insc, "Registo");
    const Actividade = obter<Construtor>(insc, "Actividade");
    const Fake = obter<Construtor>(sms, "FakeSmsProvider");
    const cunharToken = obter<(...a: never[]) => string>(insc, "cunharToken");
    const cunharReferencia = obter<(...a: never[]) => string>(insc, "cunharReferencia");
    const resolverDesafio = obter<(...a: never[]) => string>(insc, "resolverDesafio");
    const SEGUNDOS = obter<number>(insc, "SEGUNDOS_MINIMOS");
    const criarApp = obter<(...a: never[]) => AppHono>(appModulo, "createApp");

    const pepper = Buffer.alloc(32, OCTETO_DE_A);
    const assinatura = Buffer.alloc(32, OCTETO_DE_ASSINATURA);
    const destino = Buffer.alloc(32, OCTETO_DO_DESTINO);

    // Um relogio proprio: o tempo minimo de preenchimento sao tres segundos, e
    // uma bateria que os esperasse de verdade levava tres segundos por ataque.
    let agora = Date.parse("2026-11-08T10:00:00.000Z");
    const relogio = (): Date => new Date(agora);

    const casos = new (Casos as new (r: () => Date) => unknown)(relogio) as {
      todos: readonly { id: string; nomeNegocio: string }[];
    };
    const contadores = new (Contadores as new () => unknown)() as object;
    const antiabuso = new (AntiAbuso as new (o: unknown) => unknown)({
      contadores,
      chave: pepper,
      relogio,
      dificuldadeBase: 4,
    }) as object;
    const otp = new (Otp as new (o: unknown) => unknown)({
      repositorio: new (OtpMem as new () => unknown)(),
      contadores,
      provedor: new (SmsLocal as new (o: unknown) => unknown)({
        sms: new (Fake as new (o: unknown) => unknown)({ relogio }),
        pepperDoDestino: destino,
      }),
      chave: pepper,
      relogio,
    }) as object;
    const registo = new (Registo as new (o: unknown) => unknown)({
      repositorio: casos,
      antiabuso,
      otp,
      anelDoPepper: [pepper, null],
      anelDoToken: [assinatura, null],
      anelDaSessao: [assinatura, null],
      relogio,
    }) as { desafioPara(ip: unknown): Promise<{ desafio: string; dificuldade: number }> };
    const actividade = new (Actividade as new (o: unknown) => unknown)({
      repositorio: casos,
      contadores,
      relogio,
    }) as object;

    const app = criarApp(undefined, {
      registo,
      otp,
      actividade,
      antiabuso,
      anelDaAssinatura: [assinatura, null],
      anelDoToken: [assinatura, null],
      relogio,
      proxiesDeConfianca: 0,
    } as never);

    const convite = cunharToken(
      "convite" as never,
      new Date(agora + 86_400_000) as never,
      assinatura as never,
      relogio as never,
    );

    /** Submete um registo valido, resolvendo a prova de trabalho. */
    const submeter = async (
      nif: string,
      telefone: string,
      nome: string,
      chave: string,
    ): Promise<Response> => {
      const emitido = await registo.desafioPara(null);
      agora += SEGUNDOS * 1000;
      return app.request("/api/registo", {
        method: "POST",
        headers: { "content-type": "application/json", "idempotency-key": chave },
        body: JSON.stringify({
          token: convite,
          nome_negocio: nome,
          categoria: "mercearia",
          nif,
          telefone,
          desafio: emitido.desafio,
          solucao: resolverDesafio(emitido.desafio as never, emitido.dificuldade as never),
        }),
      });
    };

    // **O caso de B nasce com o canario no nome do negocio.** Sem ele, o zero do
    // oraculo nao dizia nada: provava que o varrimento nao encontra o que nunca
    // la esteve. E a licao do `sms.privacidade.test.ts` e do alvo `x11`.
    const canario = canarioOuSubstituto();
    const criadoB = await submeter(NIF_DE_B, TELEFONE_DE_B, canario, "chave-x01-de-b-001");
    const corpoB = (await criadoB.json().catch(() => ({}))) as Record<string, unknown>;
    const idDeB = casos.todos[0]?.id ?? "";
    const temCanario = casos.todos[0]?.nomeNegocio === canario;

    // Uma hora, para o intervalo de 60 s e os tres envios por hora nao
    // mascararem o que se esta a medir nos ataques.
    agora += 3_600_001;

    // ---- GET /entrar: dois convites forjados, e exige-se o mesmo estado.
    const forjado = cunharToken(
      "convite" as never,
      new Date(agora + 86_400_000) as never,
      Buffer.alloc(32, 0x11) as never,
      relogio as never,
    );
    for (const c of [forjado, "lixo-de-ensaio"]) {
      relatorio.rotas.push({
        ...(await medir(
          ITENS_DA_INSCRICAO[0],
          "GET",
          `/entrar?c=${encodeURIComponent(c)}`,
          app,
        )),
        nota: temCanario ? "canario-no-caso-de-b" : "sem-canario-no-caso-de-b",
      });
    }

    // ---- POST /api/registo: o NIF de B contra um NIF que nao existe.
    for (const [i, nif] of [NIF_DE_B, NIF_INEXISTENTE].entries()) {
      const emitido = await registo.desafioPara(null);
      agora += SEGUNDOS * 1000;
      relatorio.rotas.push({
        ...(await medir(ITENS_DA_INSCRICAO[1], "POST", "/api/registo", app, {
          method: "POST",
          headers: {
            "content-type": "application/json",
            "idempotency-key": `chave-x01-ataque-${i}`,
          },
          body: JSON.stringify({
            token: convite,
            nome_negocio: "Loja de quem ataca",
            categoria: "mercearia",
            nif,
            telefone: TELEFONE_DE_A,
            desafio: emitido.desafio,
            solucao: resolverDesafio(emitido.desafio as never, emitido.dificuldade as never),
          }),
        })),
        nota: `ataque-com-nif-${i === 0 ? "de-b" : "inexistente"}`,
      });
      agora += 3_600_001;
    }

    // ---- As duas rotas de OTP: bilhete forjado, e o id de B nu.
    const bilheteForjado = cunharReferencia(
      "ticket" as never,
      idDeB as never,
      Buffer.alloc(32, 0x11) as never,
      relogio as never,
    );
    const ataquesDeOtp: readonly (readonly [string, Record<string, unknown>])[] = [
      ["bilhete-forjado", { referencia: bilheteForjado }],
      ["id-de-b-nu", { referencia: idDeB }],
    ];
    for (const [caminho, item] of [
      ["/api/otp/reenviar", ITENS_DA_INSCRICAO[2]],
      ["/api/otp/verificar", ITENS_DA_INSCRICAO[3]],
    ] as const) {
      for (const [rotulo, corpo] of ataquesDeOtp) {
        relatorio.rotas.push({
          ...(await medir(item, "POST", caminho, app, {
            method: "POST",
            headers: { "content-type": "application/json" },
            body: JSON.stringify({ ...corpo, codigo: "000000" }),
          })),
          nota: rotulo,
        });
      }
    }

    // ---- POST /api/actividade: a sessao de A a levar o id de B.
    const sessaoDeA = cunharReferencia(
      "sessao" as never,
      // Um id que nao e o de B: o caso de A, se existir, ou um inventado.
      (casos.todos[1]?.id ?? "00000000-0000-4000-8000-000000000099") as never,
      assinatura as never,
      relogio as never,
    );
    const partesDaSessao = sessaoDeA.split(".");
    const trocada = `${idDeB}.${partesDaSessao[1] ?? ""}.${partesDaSessao[2] ?? ""}`;
    for (const [rotulo, cookie, corpo] of [
      ["sessao-de-a-com-id-de-b", `kamba_onboarding=${trocada}`, {}],
      ["sessao-forjada", `kamba_onboarding=${bilheteForjado}`, {}],
    ] as const) {
      relatorio.rotas.push({
        ...(await medir(ITENS_DA_INSCRICAO[4], "POST", "/api/actividade", app, {
          method: "POST",
          headers: cookie === ""
            ? { "content-type": "application/json" }
            : { "content-type": "application/json", cookie },
          body: JSON.stringify(corpo),
        })),
        nota: rotulo,
      });
    }

    // O corpo do registo de B **nao** entra no relatorio como entrada de rota —
    // ele e a montagem e nao um ataque —, mas o seu estado diz se a montagem
    // valeu: sem caso de B nao houve ataque nenhum. Vai na nota do primeiro item.
    if (criadoB.status !== 200 || idDeB === "" || !("referencia" in corpoB)) {
      falhar(
        `a montagem nao criou o caso de B (estado ${criadoB.status}); ` +
          "sem caso de B os ataques nao atacam nada",
      );
    }
  } catch (erro) {
    falhar(`a montagem do onboarding-web levantou: ${razao(erro)}`);
  }
}

// ------------------------------------------------------------------- o guia
//
// As doze rotas do passo guiado do Embedded Signup — as oito do KAM-093 e as
// quatro da lista de espera do KAM-095 —, no mesmo
// `onboarding-web`. A lista e **literal** e a ordem e a do `ROTAS_DO_GUIA` do
// caso. **Sobre a base desde o KAM-254**: o estado do guia na `onboarding_guia`, e
// a lista, os *gates* e a fila pela rota interna do processo de lote.
//
// ## O caso sai so da sessao, e e isso que se ataca
//
// Nenhuma destas rotas aceita um `onboarding_id` no corpo nem na consulta: o
// caso sai do cookie `sessao`, que e um HMAC sobre o id. Os ataques sao por isso
// tres, e exige-se o mesmo 403 a todos:
//
//   sessao-de-a-com-id-de-b    a sessao valida de A com o id de B trocado
//   bilhete-como-sessao        um bilhete (que nao autentica) posto no cookie
//   id-de-b-no-corpo           a sessao forjada, com o id de B no corpo e na
//                              consulta — um parametro que nenhuma rota le
//
// O `GET /ligar` leva um quarto: a ligacao de retoma de B com a sessao de A, que
// e o «link de retoma forjado» do bloco na forma que mais se parece com a
// legitima. O `POST /api/es/retoma` corre **sem** sessao, por desenho, e
// ataca-se com a retoma de B assinada por outra chave e com o id de B nu.

const ITENS_DO_GUIA = [
  "rota:onboarding-web:guia:comSessao:GET:/ligar",
  "rota:onboarding-web:guia:comSessao:GET:/api/es/estado",
  "rota:onboarding-web:guia:comSessao:POST:/api/es/preflight",
  "rota:onboarding-web:guia:comSessao:POST:/api/es/iniciar",
  "rota:onboarding-web:guia:comSessao:POST:/api/es/cancelar",
  "rota:onboarding-web:guia:comSessao:POST:/api/es/concluir",
  "rota:onboarding-web:guia:comSessao:POST:/api/es/pagamento",
  "rota:onboarding-web:guia:comSessao:POST:/api/es/retoma",
  "rota:onboarding-web:guia:comSessao:GET:/api/lista/posicao",
  "rota:onboarding-web:guia:comSessao:POST:/api/lista/convite",
  "rota:onboarding-web:guia:comSessao:POST:/api/lista/recusar",
  "rota:onboarding-web:guia:comSessao:POST:/api/lista/desistir",
] as const;

/** Um *pool* do `pg`, como o grupo do guia o usa: o `PoolDaInscricao` e o `ConjuntoSql`. */
interface PoolDePg {
  query(sql: string, parametros?: readonly unknown[]): Promise<{ rows: Record<string, unknown>[] }>;
  connect(): Promise<unknown>;
  end(): Promise<void>;
}

/**
 * Os dois *pools* do guia (KAM-254): o `kamba_app` do `onboarding-web`, que e o
 * papel das rotas atacadas, e o `kamba_batch` do processo de lote, que serve a
 * lista, os *gates* e a fila pela rota interna. O segundo vem na chave `lote` do
 * `KAMBA_X01_PG`, e so este grupo o le.
 */
function poolsDoGuia(): { readonly app: PoolDePg; readonly lote: PoolDePg } | string {
  const configuracao = configuracaoDoPg();
  if (configuracao === null) {
    return (
      "KAMBA_X01_PG nao veio no ambiente: o guia corre sobre a base (KAM-254), " +
      "com o estado na onboarding_guia e a lista, os gates e a fila pelo lote. " +
      "`db/gate_bd.py` e quem levanta a base do gate."
    );
  }
  const lote = jsonDoAmbiente("KAMBA_X01_PG")?.["lote"] as Record<string, unknown> | undefined;
  if (typeof lote?.["user"] !== "string" || typeof lote["password"] !== "string") {
    return (
      "KAMBA_X01_PG sem a chave `lote`: o processo de lote corre como kamba_batch, " +
      "e sem essa credencial a lista, os gates e a fila do guia nao se montam."
    );
  }
  const exigir = createRequire(join(RAIZ, "packages", "core-ts", "package.json"));
  const pg = exigir("pg") as { Pool: new (opcoes: unknown) => PoolDePg };
  return {
    app: new pg.Pool({ ...configuracao, max: 4, application_name: "kamba-x01-guia:app" }),
    lote: new pg.Pool({
      ...configuracao,
      user: lote["user"],
      password: lote["password"],
      max: 4,
      application_name: "kamba-x01-guia:lote",
    }),
  };
}

/** Algarismos aleatorios, para que duas corridas na mesma base nao colidam no NIF nem na chave. */
function algarismos(n: number): string {
  let s = "";
  for (let i = 0; i < n; i += 1) s += String(Math.floor(Math.random() * 10));
  return s;
}

/**
 * Monta o `onboarding-web` com o guia **sobre a base** (KAM-254): os casos e o
 * estado do guia pelo `kamba_app` (`casosNaBase`, `guiaNaBase`), e a lista, os
 * *gates* e a fila pela rota interna do processo de lote **real** (`arrancar`),
 * como `kamba_batch` — a montagem de `prod`. Cria os casos de A e de B em
 * `aguarda_es` na base — o de B com o canario no nome do negocio — e ataca as
 * doze.
 *
 * **Do `dist`, pela razao do grupo da inscricao**: o `src/guia.ts` do servico
 * importa `@kamba/core-ts/guia`, e um `PassoGuiado` do `src` era outra classe —
 * o `instanceof GuiaRecusadoError` da rota deixava de casar.
 *
 * A rota interna responde pelo `app.request()`, sem porta: o `ClienteDoLote` do
 * servico recebe um `fetch` que a chama. O que se ataca sao as rotas do dono; a
 * rota interna tem o seu grupo (`guia-interno`).
 */
async function grupoDoGuia(relatorio: Relatorio): Promise<void> {
  const falhar = (nota: string): void => {
    for (const item of ITENS_DO_GUIA) {
      relatorio.rotas.push({
        item,
        metodo: item.includes(":GET:") ? "GET" : "POST",
        caminho: item.split(":").slice(-1)[0] ?? "",
        estado: 0,
        corpo: "",
        cabecalhos: {},
        executado: false,
        nota,
      });
    }
  };

  const pools = poolsDoGuia();
  if (typeof pools === "string") {
    falhar(pools);
    return;
  }

  try {
    let insc: Record<string, unknown>;
    let sms: Record<string, unknown>;
    let guiaModulo: Record<string, unknown>;
    let appModulo: Record<string, unknown>;
    let loteModulo: Record<string, unknown>;
    let clienteModulo: Record<string, unknown>;
    try {
      insc = await importarDoRepo("packages/core-ts/dist/inscricao/index.js");
      sms = await importarDoRepo("packages/core-ts/dist/sms/index.js");
      guiaModulo = await importarDoRepo("packages/core-ts/dist/guia/index.js");
      appModulo = await importarDoRepo("services/onboarding-web/src/app.ts");
      loteModulo = await importarDoRepo("services/onboarding-web/src/lote/processo.ts");
      clienteModulo = await importarDoRepo("services/onboarding-web/src/guia_pelo_lote.ts");
    } catch (erro) {
      falhar(`nao se conseguiu importar o onboarding-web: ${razao(erro)}`);
      return;
    }

    const obter = <T>(modulo: Record<string, unknown>, nome: string): T => {
      const valor = modulo[nome];
      if (valor === undefined) throw new Error(`o modulo nao exporta ${nome}`);
      return valor as T;
    };
    type Novo = new (...argumentos: never[]) => unknown;
    const novo = <T>(modulo: Record<string, unknown>, nome: string, ...args: unknown[]): T =>
      new (obter<Novo>(modulo, nome) as new (...a: unknown[]) => unknown)(...args) as T;

    try {
      const pepper = Buffer.alloc(32, OCTETO_DE_A);
      const assinatura = Buffer.alloc(32, OCTETO_DE_ASSINATURA);
      const destino = Buffer.alloc(32, OCTETO_DO_DESTINO);
      const outra = Buffer.alloc(32, 0x11);
      const credencialDoLote = "x01-guia-credencial-do-lote";
      const origem = "https://onboarding.exemplo.test";
      const cunharReferencia = obter<(...a: never[]) => string>(insc, "cunharReferencia");
      const criarApp = obter<(...a: never[]) => AppHono>(appModulo, "createApp");

      // ---- O lado do lote: o processo real, como kamba_batch, e a rota interna dele.
      const arrancar = obter<(o: unknown) => Promise<{ interna: AppHono | null }>>(loteModulo, "arrancar");
      const { interna } = await arrancar({
        lote: pools.lote,
        app: pools.app,
        log: { warn: () => {} },
        inicioDaAmostragem: null,
        guia: { origem, credencial: credencialDoLote },
      });
      if (interna === null) throw new Error("o lote nao montou a rota interna do guia");
      const cliente = novo<object>(clienteModulo, "ClienteDoLote", {
        base: "http://lote.invalid",
        credencial: async () => credencialDoLote,
        buscar: async (url: string, init?: RequestInit) =>
          interna.request(new URL(String(url)).pathname, init as never),
      });
      const portas = obter<(o: unknown) => { lista: object; gates: object; revisao: object }>(
        clienteModulo,
        "portasDoGuia",
      )({
        ambiente: "prod",
        lote: cliente,
        emMemoria: () => {
          throw new Error("nada em memoria: o guia do X-01 corre sobre a base");
        },
      });

      // ---- O lado do onboarding-web: os casos e o guia na base, como kamba_app.
      const chaveDe = (octeto: number): string => `x01-1:${Buffer.alloc(32, octeto).toString("base64")}`;
      const cifra = obter<(...a: unknown[]) => unknown>(insc, "cifraDoCaso")(
        obter<(...a: unknown[]) => unknown>(insc, "anelDoTelefone")([chaveDe(0x21), null]),
        obter<(...a: unknown[]) => unknown>(insc, "anelDosDados")("kek_dados_do_caso", [chaveDe(0x22), null]),
      );
      const casos = obter<(o: unknown) => {
        criar(n: unknown, chave: string): Promise<{ caso: { id: string } }>;
        marcarFase(id: string, fase: string): Promise<boolean>;
      }>(insc, "casosNaBase")({ pool: pools.app, cifra, anelDoPepper: [pepper, null] });
      const contadores = novo<object>(insc, "ContadoresEmMemoria");
      const antiabuso = novo<object>(insc, "AntiAbuso", { contadores, chave: pepper });
      const otp = novo<object>(insc, "Otp", {
        repositorio: novo<object>(insc, "OtpEmMemoria"),
        contadores,
        provedor: novo<object>(insc, "OtpPorSmsLocal", {
          sms: novo<object>(sms, "FakeSmsProvider", {}),
          pepperDoDestino: destino,
        }),
        chave: pepper,
      });
      const registo = novo<object>(insc, "Registo", {
        repositorio: casos,
        antiabuso,
        otp,
        anelDoPepper: [pepper, null],
        anelDoToken: [assinatura, null],
        anelDaSessao: [assinatura, null],
      });
      const guia = novo<object>(guiaModulo, "PassoGuiado", {
        casos,
        repositorio: obter<(o: unknown) => object>(guiaModulo, "guiaNaBase")({ pool: pools.app }),
        capacidade: portas.lista,
        ligador: { ligar: async () => ({ desfecho: "criado", tentativaId: null }) },
        gates: portas.gates,
        revisao: portas.revisao,
        pagamento: { verificar: async () => "desconhecido" },
        aviso: novo<object>(guiaModulo, "AvisosEmMemoria"),
        anelDoPepper: [pepper, null],
        chaveDaAssinatura: assinatura,
        origem,
        configId: "config-de-ensaio",
      });

      const app = criarApp(
        undefined,
        {
          registo,
          otp,
          actividade: novo<object>(insc, "Actividade", { repositorio: casos, contadores }),
          antiabuso,
          anelDaAssinatura: [assinatura, null],
          anelDoToken: [assinatura, null],
          proxiesDeConfianca: 0,
        } as never,
        {
          guia,
          lista: portas.lista,
          registo,
          otp,
          anelDaAssinatura: [assinatura, null],
          appIdDaMeta: "app-de-ensaio",
          versaoDaGraph: "v21.0",
        } as never,
      );

      const criar = async (nome: string, telefone: string): Promise<string> => {
        const { caso } = await casos.criar(
          {
            tenantId: randomUUID(),
            origem: "anuncio",
            nomeNegocio: nome,
            categoriaDeclarada: "mercearia",
            nif: novo<object>(insc, "Nif", `541${algarismos(7)}AB`, pepper),
            telefone: novo<object>(insc, "Telefone", telefone, pepper),
            email: novo<object>(insc, "Email", "dono@exemplo.test"),
            dispositivoHmac: null,
            redeHmac: null,
            flags: [],
          },
          `chave-x01-guia-${algarismos(12)}`,
        );
        if (!(await casos.marcarFase(caso.id, "aguarda_es"))) throw new Error("o caso nao passou a aguarda_es");
        return caso.id;
      };

      const canario = canarioOuSubstituto();
      const idDeB = await criar(canario, `+2440000${algarismos(5)}`);
      const idDeA = await criar("Loja de quem ataca", `+2440000${algarismos(5)}`);
      // B tem estado de guia na base, com pre-voo gravado: e o que uma fuga mostraria.
      await (guia as { preflight(id: string, a: unknown): Promise<unknown> }).preflight(idDeB, {});
      // **E B fica a espera na lista, com posicao** — a forma mais hostil, e a do
      // limite a zero da montagem em memoria. A base do gate tem as vagas da
      // `onboarding_capacity`, que este condutor nao muda: enchem-se com casos de
      // ensaio pela mesma rota interna ate um deles ficar na lista, e so entao B
      // pede (achado 6 da revisao adversarial do KAM-254). Uma fuga da posicao,
      // do convite ou da desistencia seria dela.
      const reservar = (id: string): Promise<string> =>
        (portas.lista as { reserve(id: string): Promise<string> }).reserve(id);
      let cheia = false;
      for (let n = 0; n < 64 && !cheia; n += 1) {
        cheia = (await reservar(await criar(`Loja de enchimento ${n}`, `+2440000${algarismos(5)}`))) === "lista_espera";
      }
      if (!cheia) throw new Error("a lista nao encheu: B nao ficaria a espera");
      if ((await reservar(idDeB)) !== "lista_espera") throw new Error("B nao ficou na lista de espera");
      const temCanario = canario !== "" && canario !== "sem-canario-no-ambiente";

      const sessaoDeA = cunharReferencia("sessao" as never, idDeA as never, assinatura as never);
      const [, segundos, assinaturaDeA] = sessaoDeA.split(".");
      const trocada = `${idDeB}.${segundos ?? ""}.${assinaturaDeA ?? ""}`;
      const bilheteDeB = cunharReferencia("ticket" as never, idDeB as never, assinatura as never);
      const ataques: readonly (readonly [string, string])[] = [
        ["sessao-de-a-com-id-de-b", `kamba_onboarding=${trocada}`],
        ["bilhete-como-sessao", `kamba_onboarding=${bilheteDeB}`],
        ["id-de-b-no-corpo", `kamba_onboarding=${idDeB}`],
      ];
      const corpoComB = JSON.stringify({
        onboarding_id: idDeB,
        code: "c",
        waba_id: "w",
        phone_number_id: "p",
        c: "convite-de-b",
      });

      // ---- GET /ligar: os tres, mais a retoma de B com a sessao valida de A.
      const retomaDeB = encodeURIComponent(cunharReferencia("retoma" as never, idDeB as never, assinatura as never));
      for (const [, cookie] of [
        ...ataques,
        ["retoma-de-b-com-sessao-de-a", `kamba_onboarding=${sessaoDeA}`] as const,
      ]) {
        const caminho = cookie.endsWith(sessaoDeA) ? `/ligar?r=${retomaDeB}` : `/ligar?onboarding_id=${idDeB}`;
        relatorio.rotas.push({
          ...(await medir(ITENS_DO_GUIA[0], "GET", caminho, app, { headers: { cookie } })),
          nota: temCanario ? "canario-no-caso-de-b" : "sem-canario-no-caso-de-b",
        });
      }

      // ---- As dez rotas de sessao: os tres ataques a cada uma.
      const deSessao = [
        ["GET", "/api/es/estado", ITENS_DO_GUIA[1]],
        ["POST", "/api/es/preflight", ITENS_DO_GUIA[2]],
        ["POST", "/api/es/iniciar", ITENS_DO_GUIA[3]],
        ["POST", "/api/es/cancelar", ITENS_DO_GUIA[4]],
        ["POST", "/api/es/concluir", ITENS_DO_GUIA[5]],
        ["POST", "/api/es/pagamento", ITENS_DO_GUIA[6]],
        ["GET", "/api/lista/posicao", ITENS_DO_GUIA[8]],
        ["POST", "/api/lista/convite", ITENS_DO_GUIA[9]],
        ["POST", "/api/lista/recusar", ITENS_DO_GUIA[10]],
        ["POST", "/api/lista/desistir", ITENS_DO_GUIA[11]],
      ] as const;
      for (const [verbo, caminho, item] of deSessao) {
        for (const [rotulo, cookie] of ataques) {
          relatorio.rotas.push({
            ...(await medir(item, verbo, `${caminho}?onboarding_id=${idDeB}`, app, {
              method: verbo,
              headers: { "content-type": "application/json", cookie },
              ...(verbo === "POST" ? { body: corpoComB } : {}),
            })),
            nota: rotulo,
          });
        }
      }

      // ---- POST /api/es/retoma: sem sessao, por desenho.
      const retomaForjada = cunharReferencia("retoma" as never, idDeB as never, outra as never);
      for (const [rotulo, r] of [
        ["retoma-de-b-de-outra-chave", retomaForjada],
        ["id-de-b-nu", idDeB],
      ] as const) {
        relatorio.rotas.push({
          ...(await medir(ITENS_DO_GUIA[7], "POST", "/api/es/retoma", app, {
            method: "POST",
            headers: { "content-type": "application/json" },
            body: JSON.stringify({ r }),
          })),
          nota: rotulo,
        });
      }
    } catch (erro) {
      falhar(`a montagem do guia levantou: ${razao(erro)}`);
    }
  } finally {
    // **Sem `await`**: o `end()` de um *pool* espera pelos clientes emprestados,
    // e o processo de lote real pode segurar um. Esperar aqui pendurava o grupo
    // ate ao tecto da ponte, sem relatorio; o condutor sai pelo `process.exit()`.
    void pools.app.end().catch(() => undefined);
    void pools.lote.end().catch(() => undefined);
  }
}

// --------------------------------------------------- o painel do dono (KAM-099)
//
// As sete rotas do `services/onboarding-web/src/painel/rotas.ts`. Isolam o
// **tenant**, e o tenant sai so da sessao do painel, que o assina. O duplo do COM
// (`ComercioEmMemoria`) guarda as ofertas e as encomendas num mapa por tenant e
// so le do mapa que recebe: uma rota que tirasse o tenant de outro sitio que nao
// a sessao punha os dados de B na resposta, e o oraculo apanhava o canario.
//
// Os ataques, e o estado que se exige a cada um, estao na nota do caso em
// `baterias/x01_rotas.py`. As marcas da `nota` sao tres e nenhuma leva canario:
//
//   canario-de-b=presente   os dados de B levam o canario do ambiente
//   sonda=viva              a resposta com a sessao de A trouxe os dados de A
//   b=intacto               depois dos tres PATCH, a oferta de B nao mudou
//   sessao-de-b=viva        depois dos tres «sair» forjados, B continua dentro
//   caso=a                  (KAM-190) o /painel/ligar, com o tenant e o caso de B
//                           no pedido, manda o codigo so ao caso de A, o bilhete
//                           da pagina abre-se no caso de A, e nenhuma sessao do
//                           registo sai sem o codigo. **KAM-207:** duas das tres
//                           vezes sao a religacao do caso activo de A, com o
//                           canal de A desligado e o de B tambem: o painel so
//                           pergunta ao COM pelo canal de A
//   uniforme=sim            (KAM-190) o /painel/codigo responde a mesma forma ao
//                           telefone de B e a um que nao existe, nenhum bilhete
//                           leva o caso de B, e os dois de B sao diferentes
//   envio=so-b              (KAM-190) o codigo do telefone de B foi para o caso
//                           de B, e o telefone sem painel nao mandou nada
//   sessao=nenhuma          (KAM-190) nenhum ataque ao /painel/verificar cunhou
//                           sessao, e so o bilhete do painel chegou ao OTP (o
//                           `ticket` do registo e o id nu ficam a porta). **KAM-207:**
//                           os ataques pedem a ligacao, o caso de B e activo com
//                           o canal desligado, e nenhum religa nada — uma guarda
//                           contra regressao, e nao uma medicao: os ataques nao
//                           tem o codigo de B, e o religar so corre depois dele.
//                           O que mede a religacao e o caso=a do /painel/ligar
//   pedido=a                (KAM-211) os tres pedidos de troca do /painel/telefone,
//                           com o tenant de B no corpo, na consulta e no
//                           cabecalho, ficaram no tenant e na sessao de A
//   troca=nenhuma           (KAM-211) o codigo certo do pedido de B, com a sessao
//                           de A, nao trocou o dono: a verificacao chegou a troca
//                           so com o pedido e o tenant de A
//   estado=a                (KAM-223) o GET /painel/telefone, com o tenant de B na
//                           consulta e no cabecalho, so perguntou pela troca de A,
//                           e a resposta trouxe o prazo de A (a sonda)
//   concluir=a              (KAM-223) o /painel/telefone/concluir so tentou a
//                           troca de A, e a troca pendente de B continua pendente
//   cancelar=a              (KAM-223) o /painel/telefone/cancelar so cancelou a de
//                           A, e a troca pendente de B continua pendente
//   conversa=a              (KAM-223) as tres mensagens do POST /painel/conversa,
//                           com o tenant e o thread de B no pedido, gravaram-se e
//                           invocaram o AGR no tenant e no thread de A, sem botao
//   sonda=viva (conversa)   (KAM-223) o GET /painel/conversa: tres cursores de B
//                           dao 404, e uma leitura legitima de A, fora das
//                           entradas, traz o marcador de A
//   dono=a                  (KAM-216) os tres ataques ao /painel/canal, com o
//                           tenant de B na consulta e no cabecalho, so
//                           perguntaram ao COM pelo canal de A, e a pagina mostra
//                           o canal do dono de A: o WhatsApp, guardado em A com o
//                           canal activo. O de B e o painel, com o canal
//                           desligado, pelo que uma leitura de B mostrava o painel
//   foto=a                  (KAM-243) as tres fotos do POST /painel/foto, com o
//                           tenant de B na consulta e no cabecalho, foram ao MED e
//                           ao AGR no tenant e no thread de A, com o `type`
//                           `image`, a persona `dono`, o `asset_id` de A e o
//                           `wamid` `painel.{asset_id}.{envio}`, sem `message_id`
//   sonda=viva (foto)       (KAM-243) a resposta das tres trouxe o `asset_id` de A

const ITENS_DO_PAINEL = [
  "rota:onboarding-web:painel/rotas:actor:GET:/painel/entrar",
  "rota:onboarding-web:painel/rotas:actor:POST:/painel/sair",
  "rota:onboarding-web:painel/rotas:actor:GET:/painel/produtos",
  "rota:onboarding-web:painel/rotas:actor:PATCH:/painel/produtos/:id",
  "rota:onboarding-web:painel/rotas:actor:GET:/painel/encomendas",
  "rota:onboarding-web:painel/rotas:actor:GET:/painel/encomendas/:id",
  "rota:onboarding-web:painel/rotas:actor:GET:/painel/canal",
  "rota:onboarding-web:painel/rotas:actor:GET:/painel/ligar",
  "rota:onboarding-web:painel/rotas:actor:POST:/painel/codigo",
  "rota:onboarding-web:painel/rotas:actor:POST:/painel/verificar",
  // KAM-211: a troca de telefone do dono.
  "rota:onboarding-web:painel/rotas:actor:POST:/painel/telefone",
  "rota:onboarding-web:painel/rotas:actor:POST:/painel/telefone/verificar",
  // KAM-223: a troca com prova de posse e a conversa do dono.
  "rota:onboarding-web:painel/rotas:actor:GET:/painel/telefone",
  "rota:onboarding-web:painel/rotas:actor:POST:/painel/telefone/concluir",
  "rota:onboarding-web:painel/rotas:actor:POST:/painel/telefone/cancelar",
  "rota:onboarding-web:painel/rotas:actor:GET:/painel/conversa",
  "rota:onboarding-web:painel/rotas:actor:POST:/painel/conversa",
  // KAM-202: o inicio do teste ponta a ponta.
  "rota:onboarding-web:painel/rotas:actor:POST:/painel/teste",
  // KAM-206: a pagina de um produto, com o formulario que saiu da lista.
  "rota:onboarding-web:painel/rotas:actor:GET:/painel/produtos/:id",
  // KAM-206: o contacto do cliente de uma encomenda, mascarado, pelo botao.
  "rota:onboarding-web:painel/rotas:actor:POST:/painel/encomendas/:id/contacto",
  // KAM-243: a foto do dono para o catalogo.
  "rota:onboarding-web:painel/rotas:actor:POST:/painel/foto",
  // KAM-246: a pagina Social e a ligacao de descarga, pedidas ao AGR.
  "rota:onboarding-web:painel/rotas:actor:GET:/painel/social",
  "rota:onboarding-web:painel/rotas:actor:GET:/painel/social/descarga",
] as const;

/** Os telefones da reentrada (KAM-190). Ficticios, com 999. */
const TELEFONE_DE_A_NO_PAINEL = "+244 999 000 101";
const TELEFONE_DE_B_NO_PAINEL = "+244 999 000 202";
const TELEFONE_SEM_PAINEL = "+244 999 000 303";

/** Os dois tenants do painel. UUID, porque a sessao assina a forma canonica. */
const TENANT_DE_A_NO_PAINEL = "0000000a-0000-4000-8000-0000000000a1";
const TENANT_DE_B_NO_PAINEL = "0000000b-0000-4000-8000-0000000000b1";
const CASO_DE_A_NO_PAINEL = "0000000a-0000-4000-8000-0000000000c1";
const CASO_DE_B_NO_PAINEL = "0000000b-0000-4000-8000-0000000000c1";
/** O caso `activo` de A: a troca de telefone (KAM-211) so abre nessa fase. */
const CASO_ACTIVO_DE_A_NO_PAINEL = "0000000a-0000-4000-8000-0000000000c2";
/** O caso de A em `aguarda_teste`: o teste ponta a ponta (KAM-202) so abre nessa fase. */
const CASO_EM_TESTE_DE_A_NO_PAINEL = "0000000a-0000-4000-8000-0000000000c3";
const ORDEM_DE_A_NO_PAINEL = "0000000a-0000-4000-8000-0000000000d1";
const ORDEM_DE_B_NO_PAINEL = "0000000b-0000-4000-8000-0000000000d1";
/** KAM-206: uma encomenda **paga** de cada tenant, no estado em que o contacto se mostra. */
const ORDEM_PAGA_DE_A_NO_PAINEL = "0000000a-0000-4000-8000-0000000000d2";
const ORDEM_PAGA_DE_B_NO_PAINEL = "0000000b-0000-4000-8000-0000000000d2";

/** O marcador de A: o que tem de **chegar** a resposta das listas. */
const MARCADOR_DE_A = "marcador-de-a-no-painel";

async function grupoDoPainel(relatorio: Relatorio): Promise<void> {
  const falhar = (nota: string): void => {
    for (const item of ITENS_DO_PAINEL) {
      const partes = item.split(":");
      for (let vez = 0; vez < 3; vez += 1) {
        relatorio.rotas.push({
          item,
          metodo: partes[3] ?? "",
          caminho: partes.slice(4).join(":"),
          estado: 0,
          corpo: "",
          cabecalhos: {},
          executado: false,
          nota,
        });
      }
    }
  };

  let insc: Record<string, unknown>;
  let rotas: Record<string, unknown>;
  let comercioModulo: Record<string, unknown>;
  let canalModulo: Record<string, unknown>;
  let sessaoModulo: Record<string, unknown>;
  let donoModulo: Record<string, unknown>;
  try {
    insc = await importarDoRepo("packages/core-ts/dist/inscricao/index.js");
    rotas = await importarDoRepo("services/onboarding-web/src/painel/rotas.ts");
    comercioModulo = await importarDoRepo("services/onboarding-web/src/painel/comercio.ts");
    canalModulo = await importarDoRepo("services/onboarding-web/src/painel/canal.ts");
    sessaoModulo = await importarDoRepo("services/onboarding-web/src/painel/sessao.ts");
    donoModulo = await importarDoRepo("packages/core-ts/dist/dono/index.js");
  } catch (erro) {
    falhar(`nao se conseguiu importar o painel: ${razao(erro)}`);
    return;
  }

  try {
    const chave = Buffer.alloc(32, OCTETO_DE_ASSINATURA);
    const outra = Buffer.alloc(32, 0x11);
    const agora = new Date("2026-11-10T10:00:00.000Z");
    const relogio = (): Date => agora;
    const canario = canarioOuSubstituto();
    const marcaDoCanario = canarios().length === 0 ? "canario-de-b=ausente" : "canario-de-b=presente";

    type Oferta = Record<string, unknown>;
    const oferta = (sku: string, nome: string): Oferta => ({
      sku,
      nome,
      precoTipo: "fixo",
      precoMinor: 1_000_000n,
      currency: "AOA",
      stockModo: "indicativo",
      stockQuantidade: 3,
      stockReservada: 0,
      estado: "publicado",
      versao: "2026-11-10T09:00:00.000001Z",
    });
    const encomenda = (orderId: string, numero: string): Record<string, unknown> => ({
      orderId,
      numeroPublico: numero,
      estado: "aguarda_pagamento",
      totalMinor: 2_500_000n,
      currency: "AOA",
      criadoAt: "2026-11-09T10:00:00.000Z",
      contactId: "0000000c-0000-4000-8000-0000000000c9",
    });

    const comercio = new (comercioModulo["ComercioEmMemoria"] as new () => {
      semear(t: string, o: readonly Oferta[], e?: readonly Record<string, unknown>[]): void;
      ofertas: Map<string, Map<string, Oferta>>;
      gravacoes: unknown[];
    })();
    comercio.semear(TENANT_DE_A_NO_PAINEL, [oferta("arroz-de-a", MARCADOR_DE_A)], [
      encomenda(ORDEM_DE_A_NO_PAINEL, MARCADOR_DE_A),
      { ...encomenda(ORDEM_PAGA_DE_A_NO_PAINEL, MARCADOR_DE_A), estado: "paga" },
    ]);
    comercio.semear(TENANT_DE_B_NO_PAINEL, [oferta(canario, canario)], [
      encomenda(ORDEM_DE_B_NO_PAINEL, canario),
      { ...encomenda(ORDEM_PAGA_DE_B_NO_PAINEL, canario), estado: "paga" },
    ]);
    // KAM-206: a mascara de B leva o canario. Um contacto de B servido a A
    // punha-o na resposta, e o oraculo apanhava-o.
    const mascaras = (comercio as unknown as { mascaras: Map<string, string> }).mascaras;
    mascaras.set(ORDEM_PAGA_DE_A_NO_PAINEL, "••• ••• 101");
    mascaras.set(ORDEM_PAGA_DE_B_NO_PAINEL, canario);

    const canal = new (canalModulo["CanalEmMemoria"] as new () => { vistas: Map<string, unknown> })();
    const vazia = { restrito: false, escalao: null, nivel: 1, tectoPedidoMinor: 5_000_000n };
    // KAM-216: o canal do dono guardado, WhatsApp em A e painel em B.
    canal.vistas.set(TENANT_DE_A_NO_PAINEL, { ...vazia, estado: "ativo", qualidade: MARCADOR_DE_A, avisos: [], ownerChannelWa: true });
    canal.vistas.set(TENANT_DE_B_NO_PAINEL, { ...vazia, estado: "desligado", qualidade: canario, avisos: [canario], ownerChannelWa: false });

    // A reentrada (KAM-190): um OTP de duplo que regista quem verificou, e os
    // casos por HMAC de telefone. O de B acerta com o codigo de B — e nenhum
    // ataque o tem.
    const pepper = Buffer.alloc(32, 0x22);
    const Telefone = insc["Telefone"] as new (b: unknown, a: readonly (Uint8Array | null)[]) => { hmacs: readonly string[] };
    const hmacsDe = (t: string): readonly string[] => new Telefone(t, [pepper, null]).hmacs;
    const porHmac = new Map<string, { id: string; fase: string }>();
    for (const h of hmacsDe(TELEFONE_DE_A_NO_PAINEL)) porHmac.set(h, { id: CASO_DE_A_NO_PAINEL, fase: "activo" });
    for (const h of hmacsDe(TELEFONE_DE_B_NO_PAINEL)) porHmac.set(h, { id: CASO_DE_B_NO_PAINEL, fase: "activo" });
    const verificados: string[] = [];
    const enviados: string[] = [];
    const reentrada = {
      // Os dois casos de A tem o telefone de A: o activo e o da religacao (KAM-207).
      telefoneDoCaso: async (id: string) =>
        id === CASO_DE_A_NO_PAINEL || id === CASO_ACTIVO_DE_A_NO_PAINEL
          ? new Telefone(TELEFONE_DE_A_NO_PAINEL, [pepper, null])
          : null,
      otp: {
        async enviar(id: string) {
          enviados.push(id);
          return { enviado: true, expiraEm: new Date(agora.getTime() + 300_000) };
        },
        async verificar(id: string, codigo: unknown) {
          verificados.push(id);
          return id === CASO_DE_B_NO_PAINEL && codigo === "424242" ? "acertou" : "errou";
        },
      },
      casosPorTelefone: async (h: string) => {
        const c = porHmac.get(h);
        return c === undefined ? [] : [c];
      },
      anelDoPepper: [pepper, null],
      contadores: { anotar: async () => 1 },
      // KAM-207: a porta do guia, que conta quem religou.
      religar: async (id: string) => {
        religados.push(id);
        return "desligado";
      },
    };
    const religados: string[] = [];
    // KAM-207: o COM de duplo que conta de que tenant lhe perguntam o canal.
    const perguntados: string[] = [];
    const canalEspiao = {
      ler: async (tenantId: string, a: unknown) => {
        perguntados.push(tenantId);
        return (canal as unknown as { ler(t: string, a: unknown): Promise<unknown> }).ler(tenantId, a);
      },
    };

    const revogacoes = new (sessaoModulo["RevogacoesEmMemoria"] as new () => {
      revogada(s: unknown): Promise<boolean>;
    })();
    const casos = new Map([
      // `aguarda_es` (uma das `FASES_COM_PAINEL`): e o unico passo em que a
      // ligacao do KAM-190 abre, e o resto do painel serve-o igual.
      [CASO_DE_A_NO_PAINEL, { tenantId: TENANT_DE_A_NO_PAINEL, fase: "aguarda_es" }],
      [CASO_DE_B_NO_PAINEL, { tenantId: TENANT_DE_B_NO_PAINEL, fase: "activo" }],
      [CASO_ACTIVO_DE_A_NO_PAINEL, { tenantId: TENANT_DE_A_NO_PAINEL, fase: "activo" }],
      [CASO_EM_TESTE_DE_A_NO_PAINEL, { tenantId: TENANT_DE_A_NO_PAINEL, fase: "aguarda_teste" }],
    ]);
    const novaSessao = sessaoModulo["novaSessao"] as (t: string, d: string, a: Date) => Record<string, unknown>;
    const cunharSessao = sessaoModulo["cunharSessao"] as (s: unknown, c: Uint8Array) => string;
    const cunharReferencia = insc["cunharReferencia"] as (...a: unknown[]) => string;
    const sessaoDeA = novaSessao(TENANT_DE_A_NO_PAINEL, CASO_DE_A_NO_PAINEL, agora);
    const sessaoDeB = novaSessao(TENANT_DE_B_NO_PAINEL, CASO_DE_B_NO_PAINEL, agora);

    // A troca de telefone (KAM-211): uma `TrocaDeTelefone` de duplo que regista o
    // pedido e o tenant de cada chamada. O pedido de B acerta com o codigo de B,
    // e e esse o codigo que os ataques levam — com a sessao de A.
    const pedidoDaTroca = rotas["pedidoDaTroca"] as (s: unknown) => string;
    // A sessao de A da troca e a do caso `activo` de A: a do caso em
    // `aguarda_es` recebe 409 antes de chegar a troca.
    const sessaoActivaDeA = novaSessao(TENANT_DE_A_NO_PAINEL, CASO_ACTIVO_DE_A_NO_PAINEL, agora);
    const pedidoDeA = pedidoDaTroca(sessaoActivaDeA);
    const pedidoDeB = pedidoDaTroca(sessaoDeB);
    const pedidosDaTroca: { pedido: string; tenant: string }[] = [];
    const verificacoesDaTroca: { pedido: string; tenant: string }[] = [];
    let trocasFeitas = 0;
    // KAM-223: a troca de B esta pendente, e a de A tambem, com um prazo que e
    // a sonda do GET. Quem pergunta, conclui e cancela fica registado.
    const PRAZO_DE_A = new Date("2031-01-01T00:00:00.000Z");
    const pendentes = new Set([TENANT_DE_A_NO_PAINEL, TENANT_DE_B_NO_PAINEL]);
    const estadosPedidos: string[] = [];
    const conclusoes: string[] = [];
    const cancelamentos: string[] = [];
    const troca = {
      troca: {
        async pedir(pedido: string, tenant: string) {
          pedidosDaTroca.push({ pedido, tenant });
          return { enviado: true, expiraEm: new Date(agora.getTime() + 300_000) };
        },
        async verificar(pedido: string, tenant: string, _telefone: unknown, codigo: string) {
          verificacoesDaTroca.push({ pedido, tenant });
          if (pedido === pedidoDeB && tenant === TENANT_DE_B_NO_PAINEL && codigo === "424242") {
            trocasFeitas += 1;
            return { estado: "feita", contactId: "0000000b-0000-4000-8000-0000000000e1", anterior: null };
          }
          return { estado: "recusada", veredicto: "sem_pedido" };
        },
        async estado(tenant: string) {
          estadosPedidos.push(tenant);
          return pendentes.has(tenant) ? { estado: "pendente", prazo: tenant === TENANT_DE_A_NO_PAINEL ? PRAZO_DE_A : agora } : null;
        },
        async concluir(tenant: string) {
          conclusoes.push(tenant);
          return { estado: "recusada", veredicto: "cedo" };
        },
        async cancelar(tenant: string) {
          cancelamentos.push(tenant);
          // A de A fica viva, para os tres ataques medirem o mesmo; a de B so
          // sai se um ataque chegar a ela, e e isso que a marca le.
          return tenant === TENANT_DE_A_NO_PAINEL || pendentes.delete(tenant);
        },
      },
      anelDoPepper: [pepper, null],
      contadores: { anotar: async () => 1 },
    };

    // KAM-223: a conversa do dono, com uma entrada de A e uma de B. A de B leva
    // o canario; o cursor dos ataques e o `id` dela.
    const ENTRADA_DE_A = "0000000a-0000-4000-8000-0000000000f1";
    const ENTRADA_DE_B = "0000000b-0000-4000-8000-0000000000f1";
    const entradasDaConversa = new Map<string, { id: string; autor: string; texto: string; botoes: never[]; em: Date }[]>([
      [TENANT_DE_A_NO_PAINEL, [{ id: ENTRADA_DE_A, autor: "assistente", texto: MARCADOR_DE_A, botoes: [], em: agora }]],
      [TENANT_DE_B_NO_PAINEL, [{ id: ENTRADA_DE_B, autor: "assistente", texto: canario, botoes: [], em: agora }]],
    ]);
    // A `ConversaDoDono` **real**, sobre portas de duplo: a invocacao que se
    // mede e a que o codigo do painel monta, e nao uma que o duplo inventa.
    const mensagensGravadas: string[] = [];
    const invocacoesDoAgr: Record<string, unknown>[] = [];
    const ConversaDoDono = donoModulo["ConversaDoDono"] as new (p: unknown) => unknown;
    const conversa = {
      conversa: new ConversaDoDono({
        contexto: async (tenant: string) => ({
          contactId: `${tenant.slice(0, 8)}-0000-4000-8000-0000000000c9`,
          conversationId: `${tenant.slice(0, 8)}-0000-4000-8000-0000000000ca`,
          channelId: `${tenant.slice(0, 8)}-0000-4000-8000-0000000000cb`,
          vertical: "vendedor",
          modo: "bot",
        }),
        gravar: async ({ tenantId }: { tenantId: string }) => {
          mensagensGravadas.push(tenantId);
          return `${tenantId.slice(0, 8)}-0000-4000-8000-0000000000f2`;
        },
        invocar: async (invocacao: Record<string, unknown>) => {
          invocacoesDoAgr.push(invocacao);
          return { estado: 200, desfecho: "executado" };
        },
        ler: async ({ tenantId, depois }: { tenantId: string; depois: string | null }) => {
          const todas = entradasDaConversa.get(tenantId) ?? [];
          if (depois === null) return todas;
          const i = todas.findIndex((e) => e.id === depois);
          return i < 0 ? null : todas.slice(i + 1);
        },
      }),
    };

    // O teste ponta a ponta (KAM-202): um `TesteDoPainel` de duplo que regista o
    // caso e o tenant de cada inicio.
    const iniciados: { onboardingId: string; tenantId: string }[] = [];
    const teste = {
      async iniciar(onboardingId: string, tenantId: string) {
        iniciados.push({ onboardingId, tenantId });
        return { instrucoes: "envie a palavra", expiraEm: new Date(agora.getTime() + 60_000) };
      },
    };

    // KAM-246: a pagina Social, com o AGR de duplo. O item de A leva o marcador
    // e o de B o canario; a ligacao de B so abre com o tenant de B. O duplo
    // regista o tenant de cada pedido, e e isso que a marca `tenant=a` le.
    const LIGACAO_DE_A = "bGlnYWNhby1kZS1h.YXNzaW5hdHVyYS1kZS1h";
    const LIGACAO_DE_B = "bGlnYWNhby1kZS1i.YXNzaW5hdHVyYS1kZS1i";
    const tenantsDoSocial: string[] = [];
    const itemDoSocial = (tenant: string, legenda: string, ligacao: string) => ({
      referencia: tenant === TENANT_DE_A_NO_PAINEL ? "SOC-ABCDEFGH" : "SOC-HGFEDCBA",
      estado: "aprovado",
      tema: legenda,
      legenda,
      nota: null,
      imagem: `https://sto.ensaio.invalid/${tenant}/arte.jpg`,
      ligacao,
    });
    const social = {
      async itens(tenant: string) {
        tenantsDoSocial.push(tenant);
        const valor =
          tenant === TENANT_DE_A_NO_PAINEL
            ? [itemDoSocial(tenant, MARCADOR_DE_A, LIGACAO_DE_A)]
            : tenant === TENANT_DE_B_NO_PAINEL
              ? [itemDoSocial(tenant, canario, LIGACAO_DE_B)]
              : [];
        return { tipo: "ok", valor };
      },
      async abrir(tenant: string, ligacao: string) {
        tenantsDoSocial.push(tenant);
        const de = ligacao === LIGACAO_DE_A ? TENANT_DE_A_NO_PAINEL : ligacao === LIGACAO_DE_B ? TENANT_DE_B_NO_PAINEL : null;
        return de !== null && de === tenant
          ? { tipo: "ok", valor: `https://sto.ensaio.invalid/${tenant}/arte.jpg?${encodeURIComponent(MARCADOR_DE_A)}` }
          : { tipo: "recusada" };
      },
    };

    // KAM-243: a foto do dono, com a `FotoDoDono` **real** sobre portas de duplo.
    // O MED de duplo guarda por tenant, e o `asset_id` de B leva o canario: uma
    // rota que tirasse o tenant de outro sitio que nao a sessao devolvia-o.
    const ASSET_DE_A_NO_PAINEL = `${MARCADOR_DE_A}-asset`;
    const pedidosAoMed: string[] = [];
    const invocacoesDaFoto: Record<string, unknown>[] = [];
    const FotoDoDono = donoModulo["FotoDoDono"] as new (p: unknown) => unknown;
    const foto = {
      foto: new FotoDoDono({
        contexto: async (tenant: string) => ({
          contactId: `${tenant.slice(0, 8)}-0000-4000-8000-0000000000c9`,
          conversationId: `${tenant.slice(0, 8)}-0000-4000-8000-0000000000ca`,
          channelId: `${tenant.slice(0, 8)}-0000-4000-8000-0000000000cb`,
          vertical: "vendedor",
          modo: "bot",
        }),
        receber: async (pedido: { tenantId: string }) => {
          pedidosAoMed.push(pedido.tenantId);
          const assetId = pedido.tenantId === TENANT_DE_A_NO_PAINEL ? ASSET_DE_A_NO_PAINEL : canario;
          return { estado: "armazenado", assetId, referencia: `media://${assetId}`, repetido: false };
        },
        invocar: async (invocacao: Record<string, unknown>) => {
          invocacoesDaFoto.push(invocacao);
          return { estado: 200, desfecho: "executado" };
        },
      }),
    };

    const app = (rotas["rotasDoPainel"] as (o: unknown) => AppHono)({
      comercio,
      canal: canalEspiao,
      revogacoes,
      casos: { porId: async (id: string) => casos.get(id) ?? null },
      anelDaAssinatura: [chave, null],
      relogio,
      reentrada,
      troca,
      conversa,
      foto,
      teste,
      social,
    });
    const cookieDeA = `kamba_painel=${cunharSessao(sessaoDeA, chave)}`;

    const empurrar = async (
      item: string,
      metodo: string,
      caminho: string,
      init: { method?: string; body?: BodyInit; headers?: Record<string, string> },
      marcas: (corpo: string) => string,
    ): Promise<void> => {
      const entrada = await medir(item, metodo, caminho, app, init);
      relatorio.rotas.push({ ...entrada, nota: `${marcaDoCanario} ${marcas(entrada.corpo)}`.trim() });
    };
    const sonda = (corpo: string): string => (corpo.includes(MARCADOR_DE_A) ? "sonda=viva" : "sonda=morta");

    // ---- GET /painel/entrar: tres sessoes do registo que nao sao de ninguem.
    const doRegistoDeA = cunharReferencia("sessao", CASO_DE_A_NO_PAINEL, chave, relogio);
    const [, segundos, assinaturaDeA] = doRegistoDeA.split(".");
    for (const cookie of [
      `kamba_onboarding=${CASO_DE_B_NO_PAINEL}.${segundos ?? ""}.${assinaturaDeA ?? ""}`,
      `kamba_onboarding=${cunharReferencia("ticket", CASO_DE_B_NO_PAINEL, chave, relogio)}`,
      `kamba_onboarding=${CASO_DE_B_NO_PAINEL}`,
    ]) {
      await empurrar(ITENS_DO_PAINEL[0], "GET", "/painel/entrar", { headers: { cookie } }, () => "");
    }

    // ---- POST /painel/sair: tres sessoes forjadas com o `sid` e o tenant de B.
    const textoDeA = cunharSessao(sessaoDeA, chave);
    const forjadas = [
      textoDeA.replace(String(sessaoDeA["sid"]), String(sessaoDeB["sid"])),
      cunharSessao(sessaoDeB, outra),
      String(sessaoDeB["sid"]),
    ];
    for (const valor of forjadas) {
      await empurrar(ITENS_DO_PAINEL[1], "POST", "/painel/sair", { method: "POST", headers: { cookie: `kamba_painel=${valor}` } }, () => "");
    }
    const bViva = !(await revogacoes.revogada(sessaoDeB));
    for (const entrada of relatorio.rotas) {
      if (entrada.item === ITENS_DO_PAINEL[1]) entrada.nota += bViva ? " sessao-de-b=viva" : " sessao-de-b=revogada";
    }

    // ---- As listas: a sessao de A com o tenant de B no pedido.
    const comTenantDeB = (
      caminho: string,
      vez: number,
      cookie: string = cookieDeA,
    ): [string, Record<string, string>] => {
      const sep = caminho.includes("?") ? "&" : "?";
      const naConsulta = `${caminho}${sep}tenant_id=${TENANT_DE_B_NO_PAINEL}`;
      if (vez === 0) return [naConsulta, { cookie }];
      if (vez === 1) return [caminho, { cookie, "x-kamba-tenant": TENANT_DE_B_NO_PAINEL }];
      return [naConsulta, { cookie, "x-kamba-tenant": TENANT_DE_B_NO_PAINEL }];
    };
    const cookieDaTroca = `kamba_painel=${cunharSessao(sessaoActivaDeA, chave)}`;
    for (const [item, caminho] of [
      [ITENS_DO_PAINEL[2], "/painel/produtos"],
      [ITENS_DO_PAINEL[4], "/painel/encomendas?estado=aguarda_pagamento"],
      [ITENS_DO_PAINEL[6], "/painel/canal"],
    ] as const) {
      for (let vez = 0; vez < 3; vez += 1) {
        const [c, headers] = comTenantDeB(caminho, vez);
        perguntados.length = 0;
        // KAM-216: no canal, a marca do dono vai ao lado da sonda.
        const marcas =
          caminho === "/painel/canal"
            ? (corpo: string): string => {
                const so = perguntados.length > 0 && perguntados.every((t) => t === TENANT_DE_A_NO_PAINEL);
                const deA = corpo.includes('data-canal-do-dono="whatsapp"');
                return `${sonda(corpo)} dono=${so && deA ? "a" : "alheio"}`;
              }
            : sonda;
        await empurrar(item, "GET", c, { headers }, marcas);
      }
    }

    // ---- KAM-246: a pagina Social, a sessao de A com o tenant de B no pedido
    // (na consulta, no cabecalho, e nos dois). A marca `tenant=sessao` diz que o
    // AGR so ouviu o tenant da sessao do pedido.
    for (let vez = 0; vez < 3; vez += 1) {
      const [c, headers] = comTenantDeB("/painel/social", vez);
      tenantsDoSocial.length = 0;
      await empurrar(ITENS_DO_PAINEL[21], "GET", c, { headers }, (corpo) => {
        const so = tenantsDoSocial.length > 0 && tenantsDoSocial.every((x) => x === TENANT_DE_A_NO_PAINEL);
        return `${sonda(corpo)} tenant=${so ? "sessao" : "alheio"}`;
      });
    }

    // ---- KAM-246: a ligacao de descarga. Tres ataques: a ligacao de B com a
    // sessao de A; a mesma, com o tenant de B no pedido (consulta e cabecalho);
    // e a ligacao de A com a **sessao de B** (a sessao de outro tenant). A sonda
    // positiva (a ligacao de A abre na sessao de A) vai fora das entradas,
    // porque o 302 dela quebrava a uniformidade dos tres 404.
    const cookieDeB = `kamba_painel=${cunharSessao(sessaoDeB, chave)}`;
    const ataquesDaDescarga: [string, Record<string, string>, string][] = [
      [`/painel/social/descarga?l=${encodeURIComponent(LIGACAO_DE_B)}`, { cookie: cookieDeA }, TENANT_DE_A_NO_PAINEL],
      [
        `/painel/social/descarga?l=${encodeURIComponent(LIGACAO_DE_B)}&tenant_id=${TENANT_DE_B_NO_PAINEL}`,
        { cookie: cookieDeA, "x-kamba-tenant": TENANT_DE_B_NO_PAINEL },
        TENANT_DE_A_NO_PAINEL,
      ],
      [`/painel/social/descarga?l=${encodeURIComponent(LIGACAO_DE_A)}`, { cookie: cookieDeB }, TENANT_DE_B_NO_PAINEL],
    ];
    for (const [c, headers, daSessao] of ataquesDaDescarga) {
      tenantsDoSocial.length = 0;
      await empurrar(ITENS_DO_PAINEL[22], "GET", c, { headers }, () => {
        const so = tenantsDoSocial.length > 0 && tenantsDoSocial.every((x) => x === daSessao);
        return `tenant=${so ? "sessao" : "alheio"}`;
      });
    }
    const propriaDescarga = await app.request(`/painel/social/descarga?l=${encodeURIComponent(LIGACAO_DE_A)}`, {
      headers: { cookie: cookieDeA },
    });
    const sondaDaDescarga =
      propriaDescarga.status === 302 && (propriaDescarga.headers.get("location") ?? "").includes(encodeURIComponent(MARCADOR_DE_A))
        ? "sonda=viva"
        : "sonda=morta";
    for (const entrada of relatorio.rotas) {
      if (entrada.item === ITENS_DO_PAINEL[22]) entrada.nota += ` ${sondaDaDescarga}`;
    }

    // ---- PATCH /painel/produtos/:id: o `sku` de B, com a sessao de A.
    const corpos = [
      { preco_tipo: "fixo", preco_minor: "100", versao: "2026-11-10T09:00:00.000001Z" },
      { preco_tipo: "fixo", preco_minor: "100", versao: "2026-11-10T09:00:00.000001Z", tenant_id: TENANT_DE_B_NO_PAINEL },
      { preco_tipo: "fixo", preco_minor: "100", versao: "2026-11-10T09:00:00.000001Z", tenant_id: TENANT_DE_B_NO_PAINEL },
    ];
    for (const [vez, corpo] of corpos.entries()) {
      const [c, headers] = comTenantDeB(`/painel/produtos/${encodeURIComponent(canario)}`, vez);
      await empurrar(
        ITENS_DO_PAINEL[3],
        "PATCH",
        c,
        {
          method: "PATCH",
          headers: {
            ...headers,
            "content-type": "application/json",
            "idempotency-key": `chave-x01-painel-${vez}-0000`,
          },
          body: JSON.stringify(corpo),
        },
        () => "",
      );
    }
    const deB = comercio.ofertas.get(TENANT_DE_B_NO_PAINEL)?.get(canario);
    const intacto = comercio.gravacoes.length === 0 && deB !== undefined && deB["precoMinor"] === 1_000_000n;
    // A sonda positiva do PATCH: o `sku` de A, com a sessao de A, grava. Fora
    // das entradas, porque o 200 dela quebrava a uniformidade dos tres 404.
    const legitimo = await app.request("/painel/produtos/arroz-de-a", {
      method: "PATCH",
      headers: { cookie: cookieDeA, "content-type": "application/json", "idempotency-key": "chave-x01-painel-sonda-0000" },
      body: JSON.stringify({ preco_tipo: "fixo", preco_minor: "1100000", versao: "2026-11-10T09:00:00.000001Z" }),
    });
    const sondaDoPatch = legitimo.status === 200 ? "sonda=viva" : "sonda=morta";
    for (const entrada of relatorio.rotas) {
      if (entrada.item === ITENS_DO_PAINEL[3]) entrada.nota += ` ${intacto ? "b=intacto" : "b=alterado"} ${sondaDoPatch}`;
    }

    // ---- GET /painel/encomendas/:id: a encomenda de B, com a sessao de A.
    const propria = await app.request(`/painel/encomendas/${ORDEM_DE_A_NO_PAINEL}`, { headers: { cookie: cookieDeA } });
    const sondaDoDetalhe = propria.status === 200 && (await propria.text()).includes(MARCADOR_DE_A) ? "sonda=viva" : "sonda=morta";
    for (let vez = 0; vez < 3; vez += 1) {
      const [c, headers] = comTenantDeB(`/painel/encomendas/${ORDEM_DE_B_NO_PAINEL}`, vez);
      await empurrar(ITENS_DO_PAINEL[5], "GET", c, { headers }, () => sondaDoDetalhe);
    }

    // ---- GET /painel/ligar (KAM-190): a sessao de A com o tenant **e o caso** de B
    // no pedido. O codigo vai ao caso da sessao, e a sessao do registo so sai
    // depois dele — nunca daqui.
    //
    // **KAM-207:** a primeira vez e a do caso de A em `aguarda_es`; as outras
    // duas sao a religacao do caso `activo` de A, com o canal de A desligado — e
    // o de B tambem, para que um painel que perguntasse pelo canal de B o
    // encontrasse caido. O codigo vai ao caso da sessao daquela vez, e o COM so
    // e perguntado pelo canal de A.
    const lerBilhete = sessaoModulo["lerBilhete"] as (b: unknown, a: readonly (Uint8Array | null)[], d: Date) => string | null;
    const vistaDeA = canal.vistas.get(TENANT_DE_A_NO_PAINEL) as Record<string, unknown>;
    canal.vistas.set(TENANT_DE_A_NO_PAINEL, { ...vistaDeA, estado: "desligado" });
    const cookieActivoDeA = `kamba_painel=${cunharSessao(sessaoActivaDeA, chave)}`;
    const casosDoLigar = [CASO_DE_A_NO_PAINEL, CASO_ACTIVO_DE_A_NO_PAINEL, CASO_ACTIVO_DE_A_NO_PAINEL];
    enviados.length = 0;
    perguntados.length = 0;
    for (let vez = 0; vez < 3; vez += 1) {
      const [c, headers] = comTenantDeB(`/painel/ligar?caso=${CASO_DE_B_NO_PAINEL}&onboarding_id=${CASO_DE_B_NO_PAINEL}`, vez);
      const comSessao = vez === 0 ? headers : { ...headers, cookie: cookieActivoDeA };
      await empurrar(ITENS_DO_PAINEL[7], "GET", c, { headers: comSessao }, () => "");
    }
    await new Promise((resolver) => setImmediate(resolver));
    canal.vistas.set(TENANT_DE_A_NO_PAINEL, vistaDeA);
    const entradasDoLigar = relatorio.rotas.filter((e) => e.item === ITENS_DO_PAINEL[7]);
    const bilhetesDoLigar = entradasDoLigar.map((e) => lerBilhete(/data-bilhete="([^"]+)"/.exec(e.corpo)?.[1], [chave, null], agora));
    const semRegisto = entradasDoLigar.every((e) => !String(e.cabecalhos["set-cookie"] ?? "").includes("kamba_onboarding="));
    const doCasoDeA =
      bilhetesDoLigar.length === 3 &&
      bilhetesDoLigar.every((id, i) => id === casosDoLigar[i]) &&
      enviados.length === 3 &&
      enviados.every((id, i) => id === casosDoLigar[i]) &&
      perguntados.length === 2 &&
      perguntados.every((t) => t === TENANT_DE_A_NO_PAINEL);
    const marcaDoLigar = doCasoDeA && semRegisto ? "caso=a" : "caso=outro";
    for (const entrada of entradasDoLigar) {
      entrada.nota += ` ${marcaDoLigar} sonda=${bilhetesDoLigar.every((id, i) => id === casosDoLigar[i]) ? "viva" : "morta"}`;
    }

    // ---- POST /painel/codigo (KAM-190): o telefone de B, com e sem o tenant de
    // B no corpo, e um telefone sem painel. A resposta nao pode distinguir.
    const comoJson = (corpo: unknown): { method: string; headers: Record<string, string>; body: string } => ({
      method: "POST",
      headers: { "content-type": "application/json" },
      body: JSON.stringify(corpo),
    });
    enviados.length = 0;
    for (const corpo of [
      { telefone: TELEFONE_DE_B_NO_PAINEL },
      { telefone: TELEFONE_DE_B_NO_PAINEL, tenant_id: TENANT_DE_B_NO_PAINEL, nota: canario },
      { telefone: TELEFONE_SEM_PAINEL },
    ]) {
      await empurrar(ITENS_DO_PAINEL[8], "POST", "/painel/codigo", comoJson(corpo), () => "");
    }
    await new Promise((resolver) => setImmediate(resolver));
    const entradasDoCodigo = relatorio.rotas.filter((e) => e.item === ITENS_DO_PAINEL[8]);
    const formas = new Set(
      entradasDoCodigo.map((e) => {
        try {
          return `${e.estado}:${Object.keys(JSON.parse(e.corpo) as object).sort().join(",")}`;
        } catch {
          return `${e.estado}:?`;
        }
      }),
    );
    // **A forma nao chega** (achado 1 da revisao adversarial do KAM-190): o
    // bilhete de um telefone com painel levava o caso em claro, e o mesmo a cada
    // pedido. Exige-se tambem que nenhum corpo leve o caso de B e que os dois
    // bilhetes do telefone de B sejam diferentes.
    const referencias = entradasDoCodigo.map((e) => {
      try {
        return String((JSON.parse(e.corpo) as { referencia?: unknown }).referencia ?? "");
      } catch {
        return "";
      }
    });
    const opacos =
      entradasDoCodigo.every((e) => !e.corpo.includes(CASO_DE_B_NO_PAINEL)) &&
      referencias.length === 3 &&
      referencias[0] !== referencias[1];
    const marcaDoEnvio = enviados.length === 2 && enviados.every((id) => id === CASO_DE_B_NO_PAINEL) ? "envio=so-b" : "envio=outro";
    for (const entrada of entradasDoCodigo) {
      entrada.nota += `${formas.size === 1 && opacos ? " uniforme=sim" : " uniforme=nao"} ${marcaDoEnvio}`;
    }

    // ---- POST /painel/verificar (KAM-190): o bilhete do caso de B com um codigo
    // que nao e o dele, o `ticket` do registo de B, e o id de B nu.
    const cunharBilhete = sessaoModulo["cunharBilhete"] as (c: string, k: Uint8Array, a: Date) => string;
    for (const referencia of [
      cunharBilhete(CASO_DE_B_NO_PAINEL, chave, agora),
      cunharReferencia("ticket", CASO_DE_B_NO_PAINEL, chave, relogio),
      CASO_DE_B_NO_PAINEL,
    ]) {
      await empurrar(
        ITENS_DO_PAINEL[9],
        "POST",
        "/painel/verificar",
        comoJson({ referencia, codigo: "000000", tenant_id: TENANT_DE_B_NO_PAINEL, destino: "ligar" }),
        () => "",
      );
    }
    const semSessao = relatorio.rotas
      .filter((e) => e.item === ITENS_DO_PAINEL[9])
      .every((e) => !String(e.cabecalhos["set-cookie"] ?? "").includes("kamba_painel="));
    // So o bilhete do painel chega ao OTP (uma verificacao, do caso de B, com o
    // codigo errado); o `ticket` do registo e o id nu ficam a porta.
    const soOBilhete = verificados.length === 1 && verificados[0] === CASO_DE_B_NO_PAINEL;
    // KAM-207: o caso de B e activo e o canal dele caiu, e nenhum ataque o religa.
    const semReligacao = religados.length === 0;
    for (const entrada of relatorio.rotas) {
      if (entrada.item === ITENS_DO_PAINEL[9]) {
        entrada.nota += semSessao && soOBilhete && semReligacao ? " sessao=nenhuma" : " sessao=cunhada-ou-otp-alheio";
      }
    }

    // ---- POST /painel/telefone (KAM-211): a sessao de A com o tenant de B no
    // corpo, na consulta e no cabecalho. O pedido fica no tenant e na sessao de A.
    for (let vez = 0; vez < 3; vez += 1) {
      const [c, headers] = comTenantDeB("/painel/telefone", vez, cookieDaTroca);
      await empurrar(
        ITENS_DO_PAINEL[10],
        "POST",
        c,
        {
          method: "POST",
          headers: { ...headers, "content-type": "application/json" },
          body: JSON.stringify({ telefone: TELEFONE_DE_B_NO_PAINEL, tenant_id: TENANT_DE_B_NO_PAINEL, pedido: pedidoDeB }),
        },
        () => "",
      );
    }
    const soDeA =
      pedidosDaTroca.length === 3 &&
      pedidosDaTroca.every((p) => p.pedido === pedidoDeA && p.tenant === TENANT_DE_A_NO_PAINEL);
    for (const entrada of relatorio.rotas) {
      if (entrada.item === ITENS_DO_PAINEL[10]) entrada.nota += soDeA ? " pedido=a" : " pedido=alheio";
    }

    // ---- POST /painel/telefone/verificar (KAM-211): o codigo certo do pedido de
    // B, com o pedido e o tenant de B no corpo, com a sessao de A.
    for (let vez = 0; vez < 3; vez += 1) {
      const [c, headers] = comTenantDeB("/painel/telefone/verificar", vez, cookieDaTroca);
      await empurrar(
        ITENS_DO_PAINEL[11],
        "POST",
        c,
        {
          method: "POST",
          headers: { ...headers, "content-type": "application/json" },
          body: JSON.stringify({
            telefone: TELEFONE_DE_B_NO_PAINEL,
            codigo: "424242",
            tenant_id: TENANT_DE_B_NO_PAINEL,
            pedido: pedidoDeB,
          }),
        },
        () => "",
      );
    }
    const semTroca =
      trocasFeitas === 0 &&
      verificacoesDaTroca.length === 3 &&
      verificacoesDaTroca.every((v) => v.pedido === pedidoDeA && v.tenant === TENANT_DE_A_NO_PAINEL);
    for (const entrada of relatorio.rotas) {
      if (entrada.item === ITENS_DO_PAINEL[11]) entrada.nota += semTroca ? " troca=nenhuma" : " troca=alheia";
    }

    // ---- GET /painel/telefone (KAM-223): a sessao de A com o tenant de B na
    // consulta, no cabecalho e nos dois. So a troca de A, e o prazo de A chega.
    const marcarEm = (indice: number, marca: string): void => {
      for (const entrada of relatorio.rotas) {
        if (entrada.item === ITENS_DO_PAINEL[indice]) entrada.nota += ` ${marca}`;
      }
    };
    for (let vez = 0; vez < 3; vez += 1) {
      const [c, headers] = comTenantDeB("/painel/telefone", vez, cookieDaTroca);
      await empurrar(ITENS_DO_PAINEL[12], "GET", c, { headers }, (corpo) =>
        corpo.includes(PRAZO_DE_A.toISOString()) ? "sonda=viva" : "sonda=morta",
      );
    }
    marcarEm(12, estadosPedidos.length === 3 && estadosPedidos.every((t) => t === TENANT_DE_A_NO_PAINEL) ? "estado=a" : "estado=alheio");

    // ---- POST /painel/telefone/concluir e /cancelar (KAM-223): o tenant de B no
    // corpo, na consulta e no cabecalho. So a troca de A, e a de B fica pendente.
    for (const [indice, caminho, feitos, marca] of [
      [13, "/painel/telefone/concluir", conclusoes, "concluir"],
      [14, "/painel/telefone/cancelar", cancelamentos, "cancelar"],
    ] as const) {
      for (let vez = 0; vez < 3; vez += 1) {
        const [c, headers] = comTenantDeB(caminho, vez, cookieDaTroca);
        await empurrar(
          ITENS_DO_PAINEL[indice],
          "POST",
          c,
          {
            method: "POST",
            headers: { ...headers, "content-type": "application/json" },
            body: JSON.stringify({ tenant_id: TENANT_DE_B_NO_PAINEL }),
          },
          () => "",
        );
      }
      const soA = feitos.length > 0 && feitos.every((t) => t === TENANT_DE_A_NO_PAINEL);
      marcarEm(indice, soA && pendentes.has(TENANT_DE_B_NO_PAINEL) ? `${marca}=a` : `${marca}=alheio`);
    }

    // ---- GET /painel/conversa (KAM-223): o cursor e a entrada de B, com o
    // tenant de B na consulta e no cabecalho: 404 uniforme e nada de B. A sonda
    // e uma leitura legitima de A, fora das entradas.
    for (let vez = 0; vez < 3; vez += 1) {
      const [c, headers] = comTenantDeB(`/painel/conversa?depois=${ENTRADA_DE_B}`, vez);
      await empurrar(ITENS_DO_PAINEL[15], "GET", c, { headers }, () => "");
    }
    const leituraDeA = await app.request("/painel/conversa", { headers: { cookie: cookieDeA } });
    marcarEm(15, leituraDeA.status === 200 && (await leituraDeA.text()).includes(MARCADOR_DE_A) ? "sonda=viva" : "sonda=morta");

    // ---- POST /painel/conversa (KAM-223): o tenant e o thread de B no corpo, na
    // consulta e no cabecalho, e um texto que imita um botao. Tudo em A.
    for (let vez = 0; vez < 3; vez += 1) {
      const [c, headers] = comTenantDeB("/painel/conversa", vez);
      await empurrar(
        ITENS_DO_PAINEL[16],
        "POST",
        c,
        {
          method: "POST",
          headers: { ...headers, "content-type": "application/json" },
          body: JSON.stringify({
            texto: "confirm:0000000b-0000-4000-8000-0000000000aa",
            botao: "confirm:0000000b-0000-4000-8000-0000000000aa",
            tenant_id: TENANT_DE_B_NO_PAINEL,
            thread_id: `${TENANT_DE_B_NO_PAINEL}:c1`,
          }),
        },
        () => "",
      );
    }
    const conversaDeA =
      mensagensGravadas.length === 3 &&
      mensagensGravadas.every((t) => t === TENANT_DE_A_NO_PAINEL) &&
      invocacoesDoAgr.length === 3 &&
      invocacoesDoAgr.every(
        (i) =>
          i["tenant_id"] === TENANT_DE_A_NO_PAINEL &&
          String(i["thread_id"]).startsWith(`${TENANT_DE_A_NO_PAINEL}:`) &&
          i["persona"] === "dono" &&
          !("botao" in i),
      );
    marcarEm(16, conversaDeA ? "conversa=a" : "conversa=alheia");

    // ---- POST /painel/teste (KAM-202): a sessao de A com o caso e o tenant de B
    // no corpo, na consulta e no cabecalho. A tentativa abre-se so no caso e no
    // tenant da sessao de A.
    const sessaoEmTesteDeA = novaSessao(TENANT_DE_A_NO_PAINEL, CASO_EM_TESTE_DE_A_NO_PAINEL, agora);
    const cookieDoTeste = `kamba_painel=${cunharSessao(sessaoEmTesteDeA, chave)}`;
    for (let vez = 0; vez < 3; vez += 1) {
      const [c, headers] = comTenantDeB("/painel/teste", vez, cookieDoTeste);
      await empurrar(
        ITENS_DO_PAINEL[17],
        "POST",
        c,
        {
          method: "POST",
          headers: { ...headers, "content-type": "application/json" },
          body: JSON.stringify({ onboarding_id: CASO_DE_B_NO_PAINEL, tenant_id: TENANT_DE_B_NO_PAINEL }),
        },
        () => "",
      );
    }
    const soOCasoDeA =
      iniciados.length === 3 &&
      iniciados.every((i) => i.onboardingId === CASO_EM_TESTE_DE_A_NO_PAINEL && i.tenantId === TENANT_DE_A_NO_PAINEL);
    for (const entrada of relatorio.rotas) {
      if (entrada.item === ITENS_DO_PAINEL[17]) entrada.nota += soOCasoDeA ? " teste=a" : " teste=alheio";
    }

    // ---- GET /painel/produtos/:id (KAM-206): o `sku` de B, com a sessao de A e
    // o tenant de B na consulta e no cabecalho: 404 uniforme e nada de B. A
    // sonda e a pagina do `sku` de A, fora das entradas.
    for (let vez = 0; vez < 3; vez += 1) {
      const [c, headers] = comTenantDeB(`/painel/produtos/${encodeURIComponent(canario)}`, vez);
      await empurrar(ITENS_DO_PAINEL[18], "GET", c, { headers }, () => "");
    }
    const produtoDeA = await app.request("/painel/produtos/arroz-de-a", { headers: { cookie: cookieDeA } });
    marcarEm(18, produtoDeA.status === 200 && (await produtoDeA.text()).includes(MARCADOR_DE_A) ? "sonda=viva" : "sonda=morta");

    // ---- POST /painel/encomendas/:id/contacto (KAM-206): a encomenda **paga** de
    // B (no estado em que o contacto se mostra, e com o canario na mascara), com
    // a sessao de A e o tenant de B na consulta e no cabecalho: 404 uniforme e
    // nada de B. A sonda e o contacto da encomenda paga de A, fora das entradas.
    for (let vez = 0; vez < 3; vez += 1) {
      const [c, headers] = comTenantDeB(`/painel/encomendas/${ORDEM_PAGA_DE_B_NO_PAINEL}/contacto`, vez);
      await empurrar(ITENS_DO_PAINEL[19], "POST", c, { method: "POST", headers }, () => "");
    }
    const contactoDeA = await app.request(`/painel/encomendas/${ORDEM_PAGA_DE_A_NO_PAINEL}/contacto`, {
      method: "POST",
      headers: { cookie: cookieDeA },
    });
    const corpoDoContactoDeA = await contactoDeA.text();
    marcarEm(
      19,
      contactoDeA.status === 200 && corpoDoContactoDeA.includes(MARCADOR_DE_A) && corpoDoContactoDeA.includes("••• ••• 101")
        ? "sonda=viva"
        : "sonda=morta",
    );

    // ---- POST /painel/foto (KAM-243): a sessao de A com o tenant de B na
    // consulta e no cabecalho, e uma foto sintetica (so a assinatura de um JPEG).
    // O MED e o AGR so veem A, e a resposta traz o `asset_id` de A (a sonda).
    const fotoSintetica = new Uint8Array(64).fill(1);
    fotoSintetica.set([0xff, 0xd8, 0xff, 0xe0]);
    for (let vez = 0; vez < 3; vez += 1) {
      const [c, headers] = comTenantDeB("/painel/foto", vez);
      await empurrar(
        ITENS_DO_PAINEL[20],
        "POST",
        c,
        { method: "POST", headers: { ...headers, "content-type": "image/jpeg" }, body: fotoSintetica },
        sonda,
      );
    }
    const fotoDeA =
      pedidosAoMed.length === 3 &&
      pedidosAoMed.every((t) => t === TENANT_DE_A_NO_PAINEL) &&
      invocacoesDaFoto.length === 3 &&
      invocacoesDaFoto.every(
        (i) =>
          i["tenant_id"] === TENANT_DE_A_NO_PAINEL &&
          String(i["thread_id"]).startsWith(`${TENANT_DE_A_NO_PAINEL}:`) &&
          i["type"] === "image" &&
          i["persona"] === "dono" &&
          i["asset_id"] === ASSET_DE_A_NO_PAINEL &&
          String(i["wamid"]).startsWith(`painel.${ASSET_DE_A_NO_PAINEL}.`) &&
          !("message_id" in i) &&
          !("botao" in i),
      );
    marcarEm(20, fotoDeA ? "foto=a" : "foto=alheia");
  } catch (erro) {
    falhar(`a montagem do painel levantou: ${razao(erro)}`);
  }
}

// ------------------------------------- a consola da fila de revisao (KAM-196)
//
// As nove rotas do `services/onboarding-web/src/equipa/rotas.ts`. A fila corre
// sobre os duplos em memoria do `@kamba/core-ts/revisao`, e o IdP e um falso
// **deste guiao**: o servico nao tem nenhum. O «B» e um caso de outro tenant cujo
// motivo interno e NIF levam o canario do ambiente; os ataques sao de quem chega
// sem identidade da equipa, e o que se exige a cada um esta no caso em
// `baterias/x01_rotas.py`. As marcas da `nota`, nenhuma com canario:
//
//   canario-de-b=presente   o caso de B leva o canario do ambiente
//   sem-papel=403           uma sessao de equipa sem papel, contra o caso de B
//   sem-mfa=403             uma sessao de equipa sem MFA, contra o caso de B
//   sonda=viva              uma sessao de equipa com papel e MFA deu o seu 2xx
//   b=intacto               o caso de B nao mudou nem ganhou decisao
//   sessao-viva=sim         os tres «sair» forjados nao revogaram a sessao alvo
//
// No `entrar`, o `sem-mfa` e a `sonda` sao de uma prova **valida**: sem MFA da
// 403 sem cookie, e com MFA e papel cunha a sessao.

const ITENS_DA_EQUIPA = [
  "rota:onboarding-web:equipa/rotas:comRevisor:GET:/equipa/entrar",
  "rota:onboarding-web:equipa/rotas:comRevisor:POST:/equipa/sair",
  "rota:onboarding-web:equipa/rotas:comRevisor:GET:/equipa/casos",
  "rota:onboarding-web:equipa/rotas:comRevisor:GET:/equipa/casos/:id",
  "rota:onboarding-web:equipa/rotas:comRevisor:POST:/equipa/casos/:id/revelar",
  "rota:onboarding-web:equipa/rotas:comRevisor:GET:/equipa/casos/:id/documentos/:verificacao",
  "rota:onboarding-web:equipa/rotas:comRevisor:POST:/equipa/casos/:id/decisao",
  "rota:onboarding-web:equipa/rotas:comRevisor:POST:/equipa/casos/:id/recurso",
  "rota:onboarding-web:equipa/rotas:comRevisor:POST:/equipa/casos/:id/recurso/decisao",
] as const;

/** O marcador de A: o que tem de chegar as respostas legitimas. */
const MARCADOR_DA_EQUIPA = "marcador-de-a-na-consola";

async function grupoDaEquipa(relatorio: Relatorio): Promise<void> {
  const falhar = (nota: string): void => {
    for (const item of ITENS_DA_EQUIPA) {
      const partes = item.split(":");
      for (let vez = 0; vez < 3; vez += 1) {
        relatorio.rotas.push({
          item,
          metodo: partes[3] ?? "",
          caminho: partes.slice(4).join(":"),
          estado: 0,
          corpo: "",
          cabecalhos: {},
          executado: false,
          nota,
        });
      }
    }
  };

  let revisao: Record<string, unknown>;
  let insc: Record<string, unknown>;
  let rotas: Record<string, unknown>;
  let sessaoDaEquipa: Record<string, unknown>;
  let sessaoDoPainel: Record<string, unknown>;
  try {
    revisao = await importarDoRepo("packages/core-ts/dist/revisao/index.js");
    insc = await importarDoRepo("packages/core-ts/dist/inscricao/index.js");
    rotas = await importarDoRepo("services/onboarding-web/src/equipa/rotas.ts");
    sessaoDaEquipa = await importarDoRepo("services/onboarding-web/src/equipa/sessao.ts");
    sessaoDoPainel = await importarDoRepo("services/onboarding-web/src/painel/sessao.ts");
  } catch (erro) {
    falhar(`nao se conseguiu importar a consola: ${razao(erro)}`);
    return;
  }

  try {
    const chave = Buffer.alloc(32, OCTETO_DE_ASSINATURA);
    const agora = new Date("2026-11-13T09:00:00.000Z");
    const relogio = (): Date => agora;
    const canario = canarioOuSubstituto();
    const marcaDoCanario = canarios().length === 0 ? "canario-de-b=ausente" : "canario-de-b=presente";

    type Onb = { id: string; tenantId: string; fase: string; redeHmac: string | null; dispositivoHmac: string | null; nifHmac: string; telefoneHmac: string };
    type Caso = { id: string; estado: string; onboardingId: string | null };
    const onboardings = new (revisao["OnboardingsEmMemoria"] as new () => { casos: Map<string, Onb> })();
    const repositorio = new (revisao["FilaDeRevisaoEmMemoria"] as new (o: unknown, r: () => Date) => {
      casos: Map<string, Caso>;
      registo: { casoId: string }[];
    })(() => null, relogio);
    const auditoria = new (revisao["AuditoriaEmMemoria"] as new () => { linhas: unknown[] })();
    const dados = new Map<string, Record<string, string>>();
    const Servico = revisao["ServicoDeRevisao"] as new (d: unknown) => {
      abrir(p: unknown): Promise<{ estado: string; caso: Caso }>;
    };
    const servico = new Servico({
      repositorio,
      onboardings,
      auditoria,
      aviso: { avisar: async () => {} },
      alerta: () => {},
      cifra: { cifrar: async (b: Uint8Array) => b, decifrar: async (b: Uint8Array) => b },
      dados: { ler: async (id: string, campo: string) => dados.get(id)?.[campo] ?? null },
      documentos: {
        async url(rev: string, onb: string, verificacaoId: string, aud: { anotarAcesso(a: unknown): Promise<void> }) {
          await aud.anotarAcesso({ revisor: rev, onboardingId: onb, verificacaoId, em: agora });
          return `https://sto.invalid/${verificacaoId}`;
        },
      },
      screening: { gravar: async () => {} },
      relogio,
    });

    const verificacao = "0000000e-0000-4000-8000-0000000000e1";
    let seq = 0;
    async function abrirCaso(tenant: string, marca: string): Promise<Caso> {
      seq += 1;
      const o: Onb = {
        id: `0000000e-0000-4000-8000-${String(seq).padStart(12, "0")}`,
        tenantId: tenant,
        fase: "em_revisao",
        redeHmac: `rede-${seq}`,
        dispositivoHmac: null,
        nifHmac: `nif-${seq}`,
        telefoneHmac: `tel-${seq}`,
      };
      onboardings.casos.set(o.id, o);
      dados.set(o.id, { nif: marca, numero_bi: marca, telefone: marca });
      const r = await servico.abrir({
        tipo: "kyc",
        tenantId: tenant,
        onboardingId: o.id,
        motivoCodigo: "kyc_k1",
        motivoInterno: marca,
        motivoPublico: "nao_foi_possivel_validar",
        evidencias: [{ tipo: "kyc_check", ref: verificacao }],
        recomendacao: "investigar",
        prioridade: 5,
      });
      return r.caso;
    }
    const casoDeB = await abrirCaso("0000000b-0000-4000-8000-0000000000b1", canario);
    const casoDeA = await abrirCaso("0000000a-0000-4000-8000-0000000000a1", MARCADOR_DA_EQUIPA);
    const outroDeA = await abrirCaso("0000000a-0000-4000-8000-0000000000a1", MARCADOR_DA_EQUIPA);

    // O IdP falso: contas e provas de uso unico.
    type Conta = { id: string; papeis: string[]; nifHmac: null; telefoneHmac: null };
    const contas = new Map<string, Conta>();
    const provas = new Map<string, { id: string; mfa: boolean }>();
    function novaConta(id: string, papeis: string[]): Conta {
      const c = { id, papeis, nifHmac: null, telefoneHmac: null };
      contas.set(id, c);
      return c;
    }
    const r1 = novaConta("0000000f-0000-4000-8000-0000000000f1", ["ts_revisor"]);
    const r2 = novaConta("0000000f-0000-4000-8000-0000000000f2", ["ts_revisor"]);
    const semPapel = novaConta("0000000f-0000-4000-8000-0000000000f3", ["suporte"]);
    const semMfa = novaConta("0000000f-0000-4000-8000-0000000000f4", ["ts_lider"]);
    const usada = "prova-ja-usada-0001";
    provas.set(usada, { id: r1.id, mfa: true });

    const revogacoes = new (sessaoDaEquipa["RevogacoesDaEquipaEmMemoria"] as new () => {
      revogada(sid: string): Promise<boolean>;
    })();
    const app = (rotas["rotasDaEquipa"] as (o: unknown) => AppHono)({
      identidade: {
        async autenticar(prova: string) {
          const a = provas.get(prova) ?? null;
          provas.delete(prova);
          return a;
        },
        conta: async (id: string) => contas.get(id) ?? null,
      },
      servico,
      auditoria,
      revogacoes,
      anelDaAssinatura: [chave, null],
      relogio,
    });
    // Gasta-se a prova antes dos ataques: o terceiro ataque ao `entrar` e reusa-la.
    await app.request(`/equipa/entrar?prova=${usada}`);

    const novaDaEquipa = sessaoDaEquipa["novaSessaoDaEquipa"] as (a: unknown, d: Date) => { sid: string };
    const cunharDaEquipa = sessaoDaEquipa["cunharSessaoDaEquipa"] as (s: unknown, c: Uint8Array) => string;
    const cookieDe = (c: Conta, mfa: boolean): string => `kamba_equipa=${cunharDaEquipa(novaDaEquipa({ id: c.id, mfa }, agora), chave)}`;
    const cunharDoPainel = sessaoDoPainel["cunharSessao"] as (s: unknown, c: Uint8Array) => string;
    const novaDoPainel = sessaoDoPainel["novaSessao"] as (t: string, d: string, a: Date) => unknown;
    const doPainel = cunharDoPainel(novaDoPainel("0000000b-0000-4000-8000-0000000000b1", casoDeB.onboardingId ?? "", agora), chave);
    const cunharReferencia = insc["cunharReferencia"] as (...a: unknown[]) => string;
    const doRegisto = cunharReferencia("sessao", casoDeB.onboardingId, chave, relogio);
    const cookiesDoDono = [`kamba_painel=${doPainel}`, `kamba_onboarding=${doRegisto}`, `kamba_equipa=${doPainel}`];

    const pedir = (caminho: string, metodo: string, cookie: string, corpo?: unknown): Promise<Response> =>
      app.request(caminho, {
        method: metodo,
        headers: { cookie, ...(corpo === undefined ? {} : { "content-type": "application/json" }) },
        ...(corpo === undefined ? {} : { body: JSON.stringify(corpo) }),
      });
    const empurrar = async (item: string, metodo: string, caminho: string, init: Parameters<AppHono["request"]>[1], marcas: string): Promise<void> => {
      const entrada = await medir(item, metodo, caminho, app, init);
      relatorio.rotas.push({ ...entrada, nota: `${marcaDoCanario} ${marcas}`.trim() });
    };

    // ---- GET /equipa/entrar: tres provas que nao sao do IdP.
    for (const prova of [doPainel, doRegisto, usada]) {
      await empurrar(ITENS_DA_EQUIPA[0], "GET", `/equipa/entrar?prova=${encodeURIComponent(prova)}`, {}, "");
    }
    // E a rota, e nao so o IdP falso: uma prova **valida** sem MFA tem de dar
    // 403 sem cookie, e uma valida com MFA e papel tem de cunhar a sessao. Sem
    // estas duas marcas, um `entrar` que ignorasse a MFA, ou que respondesse
    // sempre 401, passava (achado 6 da revisao adversarial).
    provas.set("prova-sem-mfa-0001", { id: r1.id, mfa: false });
    provas.set("prova-com-mfa-0001", { id: r1.id, mfa: true });
    const semMfaNaEntrada = await app.request("/equipa/entrar?prova=prova-sem-mfa-0001");
    const comMfaNaEntrada = await app.request("/equipa/entrar?prova=prova-com-mfa-0001");
    const marcasDoEntrar = [
      `sem-mfa=${semMfaNaEntrada.status === 403 && semMfaNaEntrada.headers.get("set-cookie") === null ? "403" : String(semMfaNaEntrada.status)}`,
      comMfaNaEntrada.status === 303 && (comMfaNaEntrada.headers.get("set-cookie") ?? "").startsWith("kamba_equipa=v1.")
        ? "sonda=viva"
        : "sonda=morta",
    ].join(" ");
    for (const entrada of relatorio.rotas) {
      if (entrada.item === ITENS_DA_EQUIPA[0]) entrada.nota += ` ${marcasDoEntrar}`;
    }

    // ---- POST /equipa/sair: tres valores forjados com o `sid` de uma sessao viva.
    const alvo = novaDaEquipa({ id: r2.id, mfa: true }, agora);
    const textoDoAlvo = cunharDaEquipa(alvo, chave);
    const deR1 = cunharDaEquipa(novaDaEquipa({ id: r1.id, mfa: true }, agora), chave);
    const forjadas = [
      deR1.replace(deR1.split(".")[1] ?? "", alvo.sid),
      cunharDaEquipa(alvo, Buffer.alloc(32, 0x11)),
      alvo.sid,
    ];
    for (const valor of forjadas) {
      await empurrar(
        ITENS_DA_EQUIPA[1],
        "POST",
        "/equipa/sair",
        { method: "POST", headers: { cookie: `kamba_equipa=${valor}`, "content-type": "application/json" }, body: "{}" },
        "",
      );
    }
    const viva =
      !(await revogacoes.revogada(alvo.sid)) && (await pedir("/equipa/casos", "GET", `kamba_equipa=${textoDoAlvo}`)).status === 200;
    for (const entrada of relatorio.rotas) {
      if (entrada.item === ITENS_DA_EQUIPA[1]) entrada.nota += viva ? " sessao-viva=sim" : " sessao-viva=nao";
    }

    // ---- As sete rotas do caso: tres sessoes de dono contra o caso de B.
    const doCaso: [string, string, (id: string) => string, unknown][] = [
      [ITENS_DA_EQUIPA[2], "GET", () => "/equipa/casos", undefined],
      [ITENS_DA_EQUIPA[3], "GET", (id) => `/equipa/casos/${id}`, undefined],
      [ITENS_DA_EQUIPA[4], "POST", (id) => `/equipa/casos/${id}/revelar`, { campo: "nif" }],
      [ITENS_DA_EQUIPA[5], "GET", (id) => `/equipa/casos/${id}/documentos/${verificacao}`, undefined],
      [ITENS_DA_EQUIPA[6], "POST", (id) => `/equipa/casos/${id}/decisao`, { decisao: "rejeitar" }],
      [ITENS_DA_EQUIPA[7], "POST", (id) => `/equipa/casos/${id}/recurso`, {}],
      [ITENS_DA_EQUIPA[8], "POST", (id) => `/equipa/casos/${id}/recurso/decisao`, { decisao: "aprovar" }],
    ];
    const marcas = new Map<string, string[]>();
    for (const [item, metodo, caminho, corpo] of doCaso) {
      for (const cookie of cookiesDoDono) {
        await empurrar(
          item,
          metodo,
          caminho(casoDeB.id),
          {
            method: metodo,
            headers: { cookie, ...(corpo === undefined ? {} : { "content-type": "application/json" }) },
            ...(corpo === undefined ? {} : { body: JSON.stringify(corpo) }),
          },
          "",
        );
      }
      // As duas sessoes de equipa sem direito, fora das entradas: 403, e sem o canario.
      const m: string[] = [];
      for (const [nome, cookie] of [
        ["sem-papel", cookieDe(semPapel, true)],
        ["sem-mfa", cookieDe(semMfa, false)],
      ] as const) {
        const r = await pedir(caminho(casoDeB.id), metodo, cookie, corpo);
        const texto = await r.text();
        m.push(`${nome}=${r.status === 403 && !texto.includes(canario) ? "403" : String(r.status)}`);
      }
      marcas.set(item, m);
    }
    const intacto =
      repositorio.casos.get(casoDeB.id)?.estado === "aberto" && !repositorio.registo.some((d) => d.casoId === casoDeB.id);

    // ---- As sondas: uma sessao com papel e MFA, sobre os casos de A.
    const deR1Cookie = cookieDe(r1, true);
    const deR2Cookie = cookieDe(r2, true);
    const sondas: [string, boolean][] = [];
    const lista = await pedir("/equipa/casos", "GET", deR1Cookie);
    sondas.push([ITENS_DA_EQUIPA[2], lista.status === 200 && (await lista.text()).includes(casoDeA.id)]);
    const ver = await pedir(`/equipa/casos/${casoDeA.id}`, "GET", deR1Cookie);
    sondas.push([ITENS_DA_EQUIPA[3], ver.status === 200 && (await ver.text()).includes(MARCADOR_DA_EQUIPA)]);
    const revelar = await pedir(`/equipa/casos/${casoDeA.id}/revelar`, "POST", deR1Cookie, { campo: "nif" });
    sondas.push([ITENS_DA_EQUIPA[4], revelar.status === 200 && (await revelar.text()).includes(MARCADOR_DA_EQUIPA)]);
    const doc = await pedir(`/equipa/casos/${casoDeA.id}/documentos/${verificacao}`, "GET", deR1Cookie);
    sondas.push([ITENS_DA_EQUIPA[5], doc.status === 303]);
    const decisao = await pedir(`/equipa/casos/${outroDeA.id}/decisao`, "POST", deR1Cookie, { decisao: "rejeitar" });
    sondas.push([ITENS_DA_EQUIPA[6], decisao.status === 200]);
    const recurso = await pedir(`/equipa/casos/${outroDeA.id}/recurso`, "POST", deR1Cookie, {});
    sondas.push([ITENS_DA_EQUIPA[7], recurso.status === 200]);
    const final = await pedir(`/equipa/casos/${outroDeA.id}/recurso/decisao`, "POST", deR2Cookie, { decisao: "aprovar" });
    sondas.push([ITENS_DA_EQUIPA[8], final.status === 200]);

    const escrevem = new Set<string>([ITENS_DA_EQUIPA[6], ITENS_DA_EQUIPA[7], ITENS_DA_EQUIPA[8]]);
    for (const [item, viva] of sondas) {
      const extra = [...(marcas.get(item) ?? []), viva ? "sonda=viva" : "sonda=morta"];
      if (escrevem.has(item)) extra.push(intacto ? "b=intacto" : "b=alterado");
      for (const entrada of relatorio.rotas) {
        if (entrada.item === item) entrada.nota += ` ${extra.join(" ")}`;
      }
    }
  } catch (erro) {
    falhar(`a montagem da consola levantou: ${razao(erro)}`);
  }
}

// -------------------------------------- o processo de lote do onboarding (KAM-198)
//
// A lista e **literal** e a ordem e a do caso em `baterias/x01_rotas.py`.
const ITENS_DO_LOTE = [
  "rota:onboarding-web:lote/processo:criarApp:GET:/healthz",
  "rota:onboarding-web:lote/processo:criarApp:GET:/metrics",
] as const;

/**
 * As duas rotas do processo de lote, servidas das metricas de uma volta **real**
 * do `CicloDaFila`.
 *
 * O ciclo corre com um servico que nao drena nem alerta (nao ha base) e um
 * leitor em memoria com dois casos `kyc` abertos: um de A e um de B, e o de B
 * com o canario no `motivo_codigo` — que o `SQL_CONTADORES` devolve pela familia
 * e que as metricas **nao** podem pôr em etiqueta — e o `tenant_id` de B. A
 * `criarApp` recebe as metricas dessa volta, como o `lote.ts` lhe passa as do
 * ciclo em producao. O que o oraculo varre e o que um Prometheus raspava.
 */
async function grupoDoLote(relatorio: Relatorio): Promise<void> {
  const falhar = (nota: string): void => {
    for (const item of ITENS_DO_LOTE) {
      const partes = item.split(":");
      relatorio.rotas.push({
        item,
        // `rota:<servico>:<ficheiro>:<funcao>:<METODO>:<caminho>`: o metodo e o
        // quinto campo, e o caminho o resto (que pode levar `:`).
        metodo: partes[4] ?? "",
        caminho: partes.slice(5).join(":"),
        estado: 0,
        corpo: "",
        cabecalhos: {},
        executado: false,
        nota,
      });
    }
  };

  let revisao: Record<string, unknown>;
  let processo: Record<string, unknown>;
  try {
    revisao = await importarDoRepo("packages/core-ts/dist/revisao/index.js");
    processo = await importarDoRepo("services/onboarding-web/src/lote/processo.ts");
  } catch (erro) {
    falhar(`nao se conseguiu importar o processo de lote: ${razao(erro)}`);
    return;
  }

  try {
    const canario = canarioOuSubstituto();
    const marcaDoCanario = canarios().length === 0 ? "canario-de-b=ausente" : "canario-de-b=presente";
    const tenantA = ambiente("KAMBA_X01_TENANT_A") || "00000000-0000-4000-8000-00000000000a";
    const tenantB = ambiente("KAMBA_X01_TENANT_B") || "00000000-0000-4000-8000-00000000000b";
    const filaEm = new Date("2026-11-13T09:00:00.000Z");
    const casos = [
      { tenantId: tenantA, motivoCodigo: "k1:regra_dura" },
      { tenantId: tenantB, motivoCodigo: `${canario}:${tenantB}` },
    ];
    const leitor = {
      vista: async () => casos.map(() => ({ tipo: "kyc", estado: "aberto", filaEm, primeiraDecisaoEm: null })),
      contadores: async () =>
        casos.map((c) => ({ tipo: "kyc", motivo: c.motivoCodigo.split(":")[0], decisao: null, n: 1 })),
    };
    const servico = {
      drenarTriagem: async () => 0,
      alertarSla: async () => 0,
      reaplicarEfeitos: async () => {},
      amostrar: async () => null,
    };
    const Ciclo = revisao["CicloDaFila"] as new (o: unknown) => {
      metricas: unknown;
      correr(): Promise<{ falhas: readonly string[] }>;
    };
    const ciclo = new Ciclo({ servico, leitor });
    const volta = await ciclo.correr();
    if (volta.falhas.length > 0) {
      falhar(`a volta do ciclo falhou nos passos ${volta.falhas.join(",")}`);
      return;
    }
    const criarApp = processo["criarApp"];
    if (typeof criarApp !== "function") {
      falhar("services/onboarding-web/src/lote/processo.ts nao exporta criarApp como funcao");
      return;
    }
    const app = (criarApp as (m: unknown) => AppHono)(ciclo.metricas);
    for (const item of ITENS_DO_LOTE) {
      const caminho = item.split(":").slice(5).join(":");
      const entrada = await medir(item, "GET", caminho, app);
      if (item.endsWith("GET:/metrics")) {
        const nomes = [
          "review_first_decision_p90_segundos",
          "review_casos",
          "review_decisoes",
          "review_falsos_aprovados_ratio",
        ];
        const series = nomes.filter((n) => new RegExp(`^# TYPE ${n} gauge$`, "m").test(entrada.corpo)).length;
        const contados = /^review_casos\{tipo="kyc",estado="aberto"\} 2$/m.test(entrada.corpo);
        entrada.nota = `${marcaDoCanario} casos=${contados ? "contados" : "por-contar"} series=${series}`;
      }
      relatorio.rotas.push(entrada);
    }
  } catch (erro) {
    falhar(`a montagem do processo de lote levantou: ${razao(erro)}`);
  }
}

// ------------------------------------- a rota interna do guia no lote (KAM-239)
//
// A lista e **literal** e a ordem e a do caso em `baterias/x01_rotas.py`.
const ITENS_DO_GUIA_INTERNO = [
  "rota:onboarding-web:lote/interno:criarAppInterna:POST:/interno/guia/reservar",
  "rota:onboarding-web:lote/interno:criarAppInterna:POST:/interno/guia/libertar",
  "rota:onboarding-web:lote/interno:criarAppInterna:POST:/interno/guia/posicao",
  "rota:onboarding-web:lote/interno:criarAppInterna:POST:/interno/guia/convite",
  "rota:onboarding-web:lote/interno:criarAppInterna:POST:/interno/guia/recusar",
  "rota:onboarding-web:lote/interno:criarAppInterna:POST:/interno/guia/desistir",
  "rota:onboarding-web:lote/interno:criarAppInterna:POST:/interno/guia/gate",
  "rota:onboarding-web:lote/interno:criarAppInterna:POST:/interno/guia/revisao",
] as const;

/** Obviamente falsa e de baixa entropia, pela razao do `INTERNO_DE_ENSAIO` do COM. */
const CREDENCIAL_DO_GUIA_INTERNO = "ensaio-x01-credencial-do-lote";

/**
 * As oito operacoes da rota interna do guia (`services/onboarding-web/src/lote/interno.ts`),
 * atacadas como as do COM: o ataque leva o `onboarding_id` de B, o `tenant_id` de
 * B e o canario de B no corpo, **sem** a credencial, com uma errada do mesmo
 * comprimento, e com a certa no cabecalho errado. As quatro tem de dar o mesmo
 * 401, e nenhuma pode chegar as portas (`portas=0`).
 *
 * A metade positiva corre na mesma app, **antes** dos ataques, e nao entra no
 * relatorio, pela razao do COM: o 200 dela quebrava a uniformidade. Leva o caso
 * de A e o `tenant_id` de B no corpo, e o que se mede e que a porta recebe o caso
 * de A e nada de B (`tenant-do-corpo=ignorado`): nenhuma operacao le um tenant do
 * pedido. O veredicto vai na `nota` de cada entrada.
 */
async function grupoDoGuiaInterno(relatorio: Relatorio): Promise<void> {
  const falhar = (nota: string): void => {
    for (const item of ITENS_DO_GUIA_INTERNO) {
      const partes = item.split(":");
      relatorio.rotas.push({
        item,
        metodo: partes[4] ?? "",
        caminho: partes.slice(5).join(":"),
        estado: 0,
        corpo: "",
        cabecalhos: {},
        executado: false,
        nota,
      });
    }
  };

  let interno: Record<string, unknown>;
  try {
    interno = await importarDoRepo("services/onboarding-web/src/lote/interno.ts");
  } catch (erro) {
    falhar(`nao se conseguiu importar a rota interna do guia: ${razao(erro)}`);
    return;
  }
  const criar = interno["criarAppInterna"];
  if (typeof criar !== "function") {
    falhar("services/onboarding-web/src/lote/interno.ts nao exporta criarAppInterna como funcao");
    return;
  }

  try {
    const canario = canarioOuSubstituto();
    const marcaDoCanario = canarios().length === 0 ? "canario-de-b=ausente" : "canario-de-b=presente";
    const tenantB = ambiente("KAMBA_X01_TENANT_B") || "00000000-0000-4000-8000-00000000000b";
    const casoDeA = "0000000a-0000-4000-8000-00000000000a";
    const casoDeB = "0000000b-0000-4000-8000-0000000000b0";
    const chamadas: unknown[][] = [];
    const registar = (...argumentos: unknown[]): void => {
      chamadas.push(argumentos);
    };
    const lista = {
      reserve: async (id: string) => (registar("reserve", id), "granted"),
      release: async (id: string) => registar("release", id),
      posicao: async (id: string) => (registar("posicao", id), { estado: "concluido" }),
      validarConvite: async (id: string, convite: unknown) => (
        registar("validarConvite", id, convite), { expiraEm: new Date("2026-11-24T10:00:00.000Z") }
      ),
      recusar: async (id: string, convite: unknown) => registar("recusar", id, convite),
      desistir: async (id: string) => registar("desistir", id),
    };
    const gates = { marcar: async (...a: unknown[]) => registar("marcar", ...a) };
    const revisao = { abrir: async (...a: unknown[]) => registar("abrir", ...a) };
    const app = (criar as (o: unknown) => AppHono)({ lista, gates, revisao, credencial: CREDENCIAL_DO_GUIA_INTERNO });
    const corpo = (caso: string, convite: string) =>
      JSON.stringify({
        onboarding_id: caso,
        tenant_id: tenantB,
        convite,
        gate: "meta_es",
        verde: true,
        motivo: "numero_divergente",
      });
    const errada = "x".repeat(CREDENCIAL_DO_GUIA_INTERNO.length);
    for (const item of ITENS_DO_GUIA_INTERNO) {
      const caminho = item.split(":").slice(5).join(":");
      // A metade positiva: o caso de A com o tenant de B no corpo.
      const antes = chamadas.length;
      const sonda = await app.request(caminho, {
        method: "POST",
        headers: { "content-type": "application/json", "x-kamba-interno": CREDENCIAL_DO_GUIA_INTERNO },
        body: corpo(casoDeA, "convite-de-a"),
      });
      const recebido = JSON.stringify(chamadas.slice(antes));
      const ignorado = chamadas.length === antes + 1 && recebido.includes(casoDeA) && !recebido.includes(tenantB);
      const ataques: { readonly headers: Record<string, string> }[] = [
        { headers: { "content-type": "application/json" } },
        { headers: { "content-type": "application/json", "x-kamba-interno": errada } },
        { headers: { "content-type": "application/json", authorization: `Bearer ${CREDENCIAL_DO_GUIA_INTERNO}` } },
        // Um sufixo visivel, e nao um espaco: o `Headers` apara o espaco no fim, e o
        // pedido chegava autenticado (achado 1 da revisao adversarial do KAM-239).
        { headers: { "content-type": "application/json", "x-kamba-interno": `${CREDENCIAL_DO_GUIA_INTERNO}-x` } },
      ];
      const antesDosAtaques = chamadas.length;
      const entradas: EntradaDeRota[] = [];
      for (const ataque of ataques) {
        entradas.push(
          await medir(item, "POST", caminho, app, { method: "POST", headers: ataque.headers, body: corpo(casoDeB, canario) }),
        );
      }
      const portas = chamadas.length - antesDosAtaques;
      for (const entrada of entradas) {
        entrada.nota =
          `${marcaDoCanario} portas=${portas} sonda=${sonda.status} ` +
          `tenant-do-corpo=${ignorado ? "ignorado" : "lido"}`;
        relatorio.rotas.push(entrada);
      }
    }
  } catch (erro) {
    falhar(`a montagem da rota interna do guia levantou: ${razao(erro)}`);
  }
}

// ---------------------------------------------------------------------- o main

const GRUPOS: Record<string, (relatorio: Relatorio) => Promise<void>> = {
  sondas: grupoDasSondas,
  webhook: grupoDoWebhook,
  canais: grupoDosCanais,
  contacto: grupoDoContacto,
  // O nome tem de ser o mesmo do `GRUPOS` do `condutor/ponte.py`: um grupo que
  // so exista num dos lados e um caso que nunca corre.
  "com-interna": grupoDaApiInternaDoCom,
  inscricao: grupoDaInscricao,
  guia: grupoDoGuia,
  painel: grupoDoPainel,
  equipa: grupoDaEquipa,
  lote: grupoDoLote,
  "guia-interno": grupoDoGuiaInterno,
};

async function main(): Promise<number> {
  const [grupo, saida] = process.argv.slice(2);
  if (grupo === undefined || saida === undefined) {
    diagnostico(
      "uso: node tools/isolamento/tests/condutor/rotas.ts <grupo> <saida.json>\n" +
        `grupos: ${Object.keys(GRUPOS).join(", ")}\n`,
    );
    return 1;
  }
  const condutor = GRUPOS[grupo];
  if (condutor === undefined) {
    diagnostico(
      `grupo desconhecido: ${grupo} (ha ${Object.keys(GRUPOS).join(", ")})\n`,
    );
    return 1;
  }

  const relatorio: Relatorio = { rotas: [], contacto: [] };
  try {
    await condutor(relatorio);
  } catch (erro) {
    // **O relatorio sai mesmo assim.** Um grupo que rebenta a meio deixa as
    // entradas que conseguiu medir e uma nota que diz o que faltou; sem isto, o
    // lado Python via um ficheiro que nao existe e nao sabia distinguir «nao
    // correu» de «correu e nao houve rotas».
    diagnostico(`o grupo ${grupo} rebentou: ${razao(erro)}\n`);
    if (relatorio.rotas.length === 0 && relatorio.contacto.length === 0) {
      relatorio.rotas.push({
        item: `grupo:${grupo}`,
        metodo: "",
        caminho: "",
        estado: 0,
        corpo: "",
        cabecalhos: {},
        executado: false,
        nota: `o grupo rebentou antes de medir nada: ${razao(erro)}`,
      });
    }
  }

  try {
    mkdirSync(dirname(resolve(saida)), { recursive: true });
    writeFileSync(resolve(saida), `${JSON.stringify(relatorio, null, 2)}\n`, "utf8");
  } catch (erro) {
    diagnostico(`nao se conseguiu escrever ${saida}: ${razao(erro)}\n`);
    return 1;
  }
  return 0;
}

/**
 * **`process.exit()` e nao `process.exitCode`, e foi medido.**
 *
 * Importar o webhook do GWY importa `@kamba/core-ts/entrada`, que reexporta o
 * `trabalhador.ts`, que importa o `bullmq` — e **importar o `bullmq` deixa um
 * descritor vivo** no ciclo de eventos, sem se ligar a Redis nenhum. Com
 * `process.exitCode`, o guiao fazia o trabalho todo, escrevia o relatorio e
 * **nunca terminava**: o `ponte.py` batia no `timeout` e o caso ficava vermelho
 * por um motivo que nao tinha nada a ver com isolamento.
 *
 * O risco de `exit()` — matar o processo com escritas pendentes — esta fechado
 * dos dois lados: o relatorio escreve-se com `writeFileSync` e o diagnostico
 * com `writeSync(2, …)`. Nao ha nada por escrever quando esta linha corre.
 */
process.exit(await main());
