/**
 * Arranque do gwy.
 *
 * Escuta em `127.0.0.1` por omissão. Dentro de um contentor é preciso escutar em
 * `0.0.0.0` para que a rede do compose chegue ao processo, e é por isso que o
 * `Dockerfile` define `HOST=0.0.0.0` — mas nunca o faz o código por si, para que
 * correr o serviço à mão na máquina de alguém não abra uma porta na rede local
 * (`specs/01` §6, princípio 7, e o DoD do KAM-001: nada além de localhost).
 *
 * ## O que este processo monta, e porque é aqui
 *
 * O KAM-013 acrescentou duas coisas que o tratador do webhook **não** pode
 * fazer por pedido, e as duas são caches refrescadas por um laço:
 *
 * - **O anel do App Secret.** `Secrets.getRing` vai ao provedor; com o
 *   `EnvSecretProvider` é barato e com o Doppler é um HTTP. Um HTTP por webhook
 *   não cabe no alvo de «200 em < 500 ms», e a Meta manda 3× o tráfego de
 *   estados mais 1× o de entrada (`E1` §5). Refresca-se a cada
 *   `INTERVALO_DO_SEGREDO`; uma rotação demora no máximo isso a ser vista — e
 *   **não há janela de recusa**, porque o anel aceita o anterior enquanto ele
 *   existir (critério 3).
 * - **A profundidade da fila.** É uma ida ao Redis. Por pedido, a 200
 *   pedidos/s, seriam 200 idas por segundo para decidir um descarte que quase
 *   nunca acontece. Refresca-se a cada `INTERVALO_DA_PROFUNDIDADE` e serve
 *   também o *gauge* `inbound_queue_depth`.
 *
 * Um erro no laço **não derruba o processo**: a leitura falhada deixa a cache
 * como estava (o segredo) ou marca a profundidade como desconhecida — e
 * desconhecida não é saturada. O que derrubava o GWY era ficar sem conseguir
 * validar assinaturas, e para isso o `Secrets.arrancar` já aborta em `prod`.
 */

import { serve } from "@hono/node-server";
import { port } from "@kamba/core-ts";
import {
  FILA_ENTRADA,
  METRICAS,
  METRICA_PROFUNDIDADE,
} from "@kamba/core-ts/entrada";
import { FilasBullmq } from "@kamba/core-ts/eventos/filas_bullmq";
import { instalar } from "@kamba/core-ts/logger";
import { EnvSecretProvider, Secrets, isAmbiente } from "@kamba/core-ts/secrets";

import { createApp, criarAppDeMetricas } from "./app.ts";
import { DEFAULT_PORT, SERVICE } from "./meta.ts";
// Os dois `id` vivem num ficheiro proprio, e a razao esta lá: o *gate* 9
// apanha, com razao, uma atribuicao com a forma de um segredo embutido, e a
// area permitida tem de ser tao estreita quanto possivel — este ficheiro
// continua inteiramente varrido.
import { REF_DO_APP_SECRET, REF_DO_VERIFY_TOKEN } from "./segredos.ts";

// Antes de tudo o resto: a partir daqui, um erro por tratar — incluindo uma
// `PORT` inválida, duas linhas abaixo — sai como uma linha sem conteúdo, e não
// como a pilha com a mensagem no `stderr` (KAM-068, `docs/logs.md`).
const log = instalar(SERVICE);



/** De quanto em quanto se relê o anel do cofre. */
export const INTERVALO_DO_SEGREDO = 60_000;
/** De quanto em quanto se lê a profundidade da fila. */
export const INTERVALO_DA_PROFUNDIDADE = 1_000;

/**
 * A porta interna do `/metrics` e do `/healthz`.
 *
 * **Separada da pública, e a razão é a revisão adversarial.** O `/metrics`
 * esteve no mesmo servidor que o `/wa/webhook`, e isso punha a profundidade da
 * fila ao alcance de quem alcança a Internet. Os outros processos do conjunto
 * usam 3011, 3012 e 3013; esta é a 3010.
 */
export const PORTA_DAS_METRICAS = 3010;
const VARIAVEL_DA_PORTA_DAS_METRICAS = "GWY_METRICS_PORT";

const VARIAVEL_DA_FILA = "KAMBA_QUEUE_URL";
const VARIAVEL_DO_AMBIENTE = "KAMBA_AMBIENTE";

/** A porta interna das métricas. A mesma validação que o `port()` do núcleo. */
function portaDasMetricas(): number {
  const bruto = (process.env[VARIAVEL_DA_PORTA_DAS_METRICAS] ?? "").trim();
  if (bruto === "") return PORTA_DAS_METRICAS;
  const valor = Number(bruto);
  if (!Number.isInteger(valor) || valor < 1 || valor > 65_535) {
    throw new Error(`${VARIAVEL_DA_PORTA_DAS_METRICAS} inválida`);
  }
  return valor;
}

function exigir(nome: string): string {
  const valor = process.env[nome];
  if (valor === undefined || valor.trim() === "") {
    throw new Error(`falta a variável de ambiente ${nome}`);
  }
  return valor;
}

/** O ambiente do cofre. Sem omissão silenciosa para `dev`: ver `secrets/port.ts`. */
function ambiente(): "dev" | "staging" | "prod" {
  const bruto = exigir(VARIAVEL_DO_AMBIENTE).trim();
  if (!isAmbiente(bruto)) {
    throw new Error(`${VARIAVEL_DO_AMBIENTE} inválida: tem de ser dev, staging ou prod`);
  }
  return bruto;
}

async function principal(): Promise<void> {
  const urlDaFila = exigir(VARIAVEL_DA_FILA);

  // Em `prod`, um cofre inacessível **aborta o arranque**: um GWY a responder
  // 401 a tudo é uma avaria silenciosa, e a Meta re-entrega sete dias — o que
  // transforma um arranque recusado num atraso recuperável (`secrets/arranque.ts`).
  const secrets = await Secrets.arrancar({
    servico: SERVICE,
    provider: new EnvSecretProvider({ ambiente: ambiente() }),
    obrigatorios: [REF_DO_APP_SECRET, REF_DO_VERIFY_TOKEN],
    // O aviso do cofre não leva o nome do segredo para a linha de registo: a
    // *allowlist* não tem campo para ele, e o `outcome` diz o que aconteceu.
    aviso: () => log.warn({ outcome: "cofre_inacessivel_no_arranque" }),
  });

  // As caches. Nascem preenchidas — o `arrancar` já carregou os obrigatórios —,
  // e é isso que faz o primeiro pedido não esperar por um laço.
  let anel: readonly (string | null)[] = await secrets.getRing(REF_DO_APP_SECRET);
  let verifyToken = await secrets.get(REF_DO_VERIFY_TOKEN);
  let profundidade: number | null = null;

  const filas = new FilasBullmq({ url: urlDaFila });
  const paragem = new AbortController();
  for (const sinal of ["SIGTERM", "SIGINT"] as const) {
    process.on(sinal, () => paragem.abort());
  }

  // O servidor interno: `/healthz` e `/metrics`, na sua porta e em localhost.
  const metricas = serve({
    fetch: criarAppDeMetricas(log).fetch,
    hostname: process.env.HOST?.trim() || "127.0.0.1",
    port: portaDasMetricas(),
  });

  const servidor = serve({
    fetch: createApp(log, {
      anel: () => anel,
      verifyToken: () => verifyToken,
      filas,
      profundidade: () => profundidade,
    }).fetch,
    hostname: process.env.HOST?.trim() || "127.0.0.1",
    port: port(DEFAULT_PORT),
  });

  const segredos = setInterval(() => {
    void (async () => {
      try {
        anel = await secrets.getRing(REF_DO_APP_SECRET);
        verifyToken = await secrets.get(REF_DO_VERIFY_TOKEN);
      } catch (erro) {
        // A cache fica como estava. O anel aceita o anterior, pelo que um cofre
        // em baixo durante uma rotação continua a validar o tráfego antigo.
        log.excepcao(erro, "releitura_do_cofre_falhou");
      }
    })();
  }, INTERVALO_DO_SEGREDO);

  // **Uma leitura de cada vez, e registo só na transição.** As duas coisas são
  // achados da revisão adversarial. Sem o trinco, um Redis **lento** (2 s por
  // comando) fazia começar uma leitura nova a cada segundo sem a anterior ter
  // acabado, cada uma com o seu temporizador de 5 s do `comLimite`, e
  // acumulavam-se pedidos pendentes no processo que tem de responder em menos
  // de 500 ms. Sem a transição, um Redis em baixo escrevia uma linha por
  // segundo — 86 400 por dia — e a avaria afogava o registo que devia
  // sinalizá-la, e com ele as linhas de `assinatura_invalida` que importam.
  let aLer = false;
  let ilegivel = false;
  const fila = setInterval(() => {
    if (aLer) return;
    aLer = true;
    void (async () => {
      try {
        profundidade = await filas.profundidade(FILA_ENTRADA);
        METRICAS.medir(METRICA_PROFUNDIDADE, profundidade);
        if (ilegivel) {
          ilegivel = false;
          log.info({ outcome: "profundidade_legivel" });
        }
      } catch (erro) {
        // Desconhecida, e **não** saturada: o tratador não descarta nada com
        // `null`. O `-1` no *gauge* distingue «não se leu» de «fila vazia».
        profundidade = null;
        METRICAS.medir(METRICA_PROFUNDIDADE, -1);
        if (!ilegivel) {
          ilegivel = true;
          log.excepcao(erro, "profundidade_ilegivel");
        }
      } finally {
        aLer = false;
      }
    })();
  }, INTERVALO_DA_PROFUNDIDADE);

  // Os dois laços não seguram o processo: sem isto, um `SIGTERM` fechava o
  // servidor e o Node continuava vivo por causa dos temporizadores.
  segredos.unref();
  fila.unref();

  // O anfitrião e a porta não estão na *allowlist* de `docs/tecnica/08` §7.3,
  // e por isso não saem: quem os quer saber lê a configuração do contentor.
  log.info({ outcome: "service_started" });

  await new Promise<void>((resolver) => {
    paragem.signal.addEventListener("abort", () => resolver(), { once: true });
  });

  clearInterval(segredos);
  clearInterval(fila);
  servidor.close();
  metricas.close();
  await filas.fechar();
}

if (import.meta.main) {
  await principal();
}
