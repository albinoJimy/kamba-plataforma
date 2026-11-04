/**
 * O condutor das rotas Hono: ataca-as **em processo** e escreve um relatorio
 * que o lado Python le (KAM-066, criterio 3 e criterio 6).
 *
 *     node security/isolation/condutor/rotas.ts <grupo> <ficheiro-de-saida.json>
 *
 * ## Porque e que isto e um guiao de `node` e nao um caso de Python
 *
 * As dezassete rotas de TypeScript sao Hono, e uma aplicacao Hono responde pelo
 * `app.request()` sem nenhum servidor levantado — e a forma que os testes do GWY
 * ja usam. Nenhuma porta, nenhum `fetch` sobre `localhost`, nenhuma espera: o
 * ataque e deterministico e o `fn` do caso em `security/isolation/baterias/`
 * limita-se a ler o JSON. A fronteira entre as duas linguagens e este ficheiro,
 * e e de proposito que ela e um ficheiro e nao uma convencao: o Python nao
 * importa Hono e este guiao nao decide se ha achado.
 *
 * ## O que este guiao **nao** decide
 *
 * Nao decide se houve fuga, nem se as recusas foram uniformes. Reporta o que
 * mediu — estado, corpo, cabecalhos — e o oraculo de `security/isolation/`
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
 *     KAMBA_X01_PG         JSON `{host, port, user, password, database}`
 *     KAMBA_X01_CONTACTOS  JSON `{x: {id, canarios}, y: {id, canarios}}`
 *
 * Os dois ultimos so fazem falta aos grupos `canais` e `contacto`. Sem eles as
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

import { createHash, createHmac } from "node:crypto";
import { mkdirSync, writeFileSync, writeSync } from "node:fs";
import { createRequire } from "node:module";
import { dirname, join, resolve } from "node:path";
import { fileURLToPath, pathToFileURL } from "node:url";

const AQUI = dirname(fileURLToPath(import.meta.url));
/** A raiz do repositorio: `security/isolation/condutor/` esta tres niveis abaixo. */
const RAIZ = resolve(AQUI, "..", "..", "..");

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
 * As quatorze sondas nao recebem identificador nenhum, pelo que nao ha IDOR a
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
  const getValidQuote = produtos["getValidQuote"] as (
    r: Record<string, unknown>,
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
      "o `SQL_COTACAO_VALIDA` filtra `(tenant_id, sku, qty, estado, " +
        "valida_ate)` e **nao** por `contact_id`, apesar de a tabela ter a " +
        "coluna. A separacao entre X e Y nesta leitura e o `sku` que se pede, " +
        "nao um predicado de contacto.";
    const sku = String(
      daCotacao.valores?.["sku"] ?? contacto.canarios["platform.price_quotes"] ?? "",
    );
    const qty = Number(daCotacao.valores?.["qty"] ?? 1);
    const validaAte = daCotacao.valores?.["valida_ate"];
    // `valida_ate > $4`: um segundo antes do limite poe a cotacao dentro da
    // validade sem depender da hora do *gate*.
    const agoraDaCotacao =
      validaAte === undefined ? new Date() : new Date(instante(validaAte).getTime() - 1_000);
    await registar("cotacoes", quem, notaDaCotacao, () =>
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

// ---------------------------------------------------------------------- o main

const GRUPOS: Record<string, (relatorio: Relatorio) => Promise<void>> = {
  sondas: grupoDasSondas,
  webhook: grupoDoWebhook,
  canais: grupoDosCanais,
  contacto: grupoDoContacto,
};

async function main(): Promise<number> {
  const [grupo, saida] = process.argv.slice(2);
  if (grupo === undefined || saida === undefined) {
    diagnostico(
      "uso: node security/isolation/condutor/rotas.ts <grupo> <saida.json>\n" +
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
