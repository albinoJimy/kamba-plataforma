/**
 * Arranque do com.
 *
 * Escuta em `127.0.0.1` por omissão. Dentro de um contentor é preciso escutar em
 * `0.0.0.0` para que a rede do compose chegue ao processo, e é por isso que o
 * `Dockerfile` define `HOST=0.0.0.0` — mas nunca o faz o código por si, para que
 * correr o serviço à mão na máquina de alguém não abra uma porta na rede local
 * (`specs/01` §6, princípio 7, e o DoD do KAM-001: nada além de localhost).
 *
 * ## Os dois segredos são **obrigatórios**, e é isso que o critério 6 pede
 *
 * ```text
 * segredo_intents      o anel [actual, anterior] da intent_key e do cart_id (§3.44)
 * com_internal_token   a credencial da API interna                          (§3.24)
 * ```
 *
 * «Um arranque sem o segredo **não serve pedidos**» é a letra do critério, e o
 * que o cumpre é o `Secrets.arrancar` do KAM-010: um obrigatório ausente é
 * `ArranqueAbortadoError` e o processo sai com **2** antes de haver porta aberta.
 * Em `prod` o cofre inacessível também aborta; fora de `prod` avisa e segue, e o
 * passo seguinte aborta de qualquer modo — com uma mensagem melhor, porque nomeia
 * o segredo.
 *
 * O `segredo_intents` entra nos três ambientes no `ops/secrets-inventory.yaml`
 * por causa deste ficheiro: a entrada dizia `obrigatorio_em: []` com a razão
 * escrita — «o COM não serve a saga na Fase 0 (a API interna do COM não existe),
 * pelo que exigi-lo ao arranque travava um serviço que só tem `/healthz`; entra
 * nos três ambientes no ticket que ligar a porta». É este.
 *
 * ## A base lê-se na **primeira ligação** e não no arranque
 *
 * A mesma escolha que o compose escreve para o AGR, e pela mesma razão: o
 * `/healthz` tem de responder com a base em baixo, senão a sonda do *rolling
 * deploy* reprova um serviço que está vivo. Um `Pool` é preguiçoso por natureza,
 * pelo que não há nada a fazer para o conseguir — só não ir à base aqui.
 *
 * ## É um `Pool` e o resto da casa usa um `Client`, e a diferença é o tráfego
 *
 * O `services/worker-canal` abre **um** `Client` por processo e passa-o ao
 * `comTenant`, e isso basta-lhe porque trata um *job* de cada vez. O COM serve
 * HTTP: dois pedidos concorrentes no mesmo `Client` dão `LigacaoEmUsoError` — e
 * se não dessem seria pior, porque o `tenant_guard` escreve o que acontece sem
 * essa guarda («o segundo `BEGIN` é um aviso, o segundo `set_config` sobrepõe o
 * primeiro, e o pedido de um tenant lê as linhas de outro»).
 *
 * Por isso cada transacção **toma uma ligação do `Pool`** e devolve-a no fim. O
 * que se passa ao `comTenant` é a ligação tomada e nunca o `Pool`: ele recusa um
 * *pool* à entrada (`PoolRecusadoError`), e com razão — cada `query` podia ir a
 * uma ligação diferente, e o `BEGIN` ficava numa e a consulta noutra, **sem
 * contexto**.
 */

import { serve } from "@hono/node-server";
import { Pool } from "pg";
import { port } from "@kamba/core-ts";
import { instalar } from "@kamba/core-ts/logger";
import {
  EnvSecretProvider,
  Secrets,
  isAmbiente,
  type Ambiente,
} from "@kamba/core-ts/secrets";
import { comTenant } from "@kamba/core-ts/tenant_guard";

import { createApp } from "./app.ts";
import { DEFAULT_PORT, SERVICE } from "./meta.ts";
import { operacoesDoCom } from "./adapters/medusa/index.ts";
import { SEGREDO_DA_API } from "./api/interna.ts";
import { REF_SEGREDO_DE_INTENTS } from "./orders/index.ts";
import type { ClienteSql, ComTenant } from "./port/index.ts";

/** A variável com a cadeia de ligação. Lida na primeira ligação, não aqui. */
export const VARIAVEL_DA_BASE = "KAMBA_COM_DB_URL";

/** A variável que diz o ambiente. O domínio é o `AMBIENTES` do `secrets`. */
export const VARIAVEL_DO_AMBIENTE = "KAMBA_ENV";

/**
 * A bandeira da entrega, pelo nome que a revisão `0030` escreve na tabela.
 *
 * **O nome é o da base e não um inventado aqui**: o `order_state_graph` tem
 * `flag = 'COM_DELIVERY_ENABLED'` nas duas transições da entrega, e o
 * `transicaoPermitida` compara-o com esta lista. Um nome diferente dos dois
 * lados deixava a entrega desligada com a configuração ligada, em silêncio.
 *
 * E se as duas não concordarem, **ganha a base**: o `order_transicao_valida` lê
 * o `current_setting('app.com_delivery_enabled')` e é ele que recusa.
 */
export const BANDEIRA_DA_ENTREGA = "COM_DELIVERY_ENABLED";

/** As bandeiras ligadas, lidas do ambiente. Vazio no Piloto. */
function bandeirasDoAmbiente(): readonly string[] {
  return process.env[BANDEIRA_DA_ENTREGA]?.trim() === "1"
    ? [BANDEIRA_DA_ENTREGA]
    : [];
}

/** O ambiente, ou `dev`. Um valor desconhecido **levanta** em vez de assumir. */
function ambienteDoProcesso(): Ambiente {
  const bruto = process.env[VARIAVEL_DO_AMBIENTE]?.trim();
  if (bruto === undefined || bruto === "") return "dev";
  if (!isAmbiente(bruto)) {
    throw new Error(
      `${VARIAVEL_DO_AMBIENTE} tem um valor que nao e um ambiente. ` +
        "Assumir `dev` a partir de um valor desconhecido era servir em `prod` " +
        "com a tolerancia de `dev` (KAM-010)",
    );
  }
  return bruto;
}

// Antes de tudo o resto: a partir daqui, um erro por tratar — incluindo uma
// `PORT` inválida, mais abaixo — sai como uma linha sem conteúdo, e não como a
// pilha com a mensagem no `stderr` (KAM-068, `docs/logs.md`).
const log = instalar(SERVICE);

const ambiente = ambienteDoProcesso();

let anel: readonly [string, string | null];
let credencial: string;
try {
  const segredos = await Secrets.arrancar({
    servico: SERVICE,
    provider: new EnvSecretProvider({ ambiente }),
    obrigatorios: [REF_SEGREDO_DE_INTENTS, SEGREDO_DA_API],
    // O aviso do cofre não leva valores, por construção — ver o `arranque.ts`.
    aviso: () => log.warn({ outcome: "cofre_indisponivel_no_arranque" }),
  });
  // As duas referências são **constantes** e não literais, e o `tools/secrets_inventory`
  // pede o literal para poder ligar o uso à entrada do inventário. Aqui o
  // literal era a segunda cópia de um nome que já tem um dono em código — o
  // `REF_SEGREDO_DE_INTENTS` do `orders/intents.ts` existe por isso, e está
  // escrito lá: «escrito duas vezes, divergiu». Por isso as linhas levam o
  // marcador que a própria ferramenta prevê, com a razão.
  anel = await segredos.getRing(REF_SEGREDO_DE_INTENTS); // kamba:secrets-inventory dinamico a constante REF_SEGREDO_DE_INTENTS e o dono do nome em codigo
  credencial = await segredos.get(SEGREDO_DA_API); // kamba:secrets-inventory dinamico a constante SEGREDO_DA_API do api/interna.ts e o dono do nome em codigo
} catch (erro) {
  log.excepcao(erro, "cofre_indisponivel");
  // **Dois e não um**, que é o código que o AGR usa para a mesma falha: um
  // arranque sem segredos obrigatórios não é uma avaria genérica.
  process.exit(2);
}

/**
 * O `Pool`. Preguiçoso: nenhuma ligação se abre até ao primeiro pedido.
 *
 * A cadeia de ligação pode não estar definida, e isso **não** aborta o arranque:
 * o `/healthz` tem de responder com a base em baixo. O que falha é o primeiro
 * pedido a `/internal/*`, com 500 e sem corpo revelador — que é a falha certa,
 * porque é onde a base é mesmo necessária.
 */
const pool = new Pool({ connectionString: process.env[VARIAVEL_DA_BASE] });

/** Uma transacção com contexto de tenant, numa ligação tomada ao `Pool`. */
const transaccaoDeTenant: ComTenant = async (tenantId, trabalho) => {
  const cliente = await pool.connect();
  try {
    return await comTenant(cliente, tenantId, () =>
      trabalho(cliente as unknown as ClienteSql),
    );
  } finally {
    // **No `finally` e não no caminho de sucesso**: uma ligação não devolvida é
    // uma vaga perdida para sempre, e o `Pool` acaba a servir nenhuma.
    cliente.release();
  }
};

const operacoes = operacoesDoCom({
  comTenant: transaccaoDeTenant,
  anel,
  bandeiras: bandeirasDoAmbiente(),
});

const hostname = process.env.HOST?.trim() || "127.0.0.1";
const listenPort = port(DEFAULT_PORT);

serve(
  {
    fetch: createApp(log, { operacoes, credencial, log }).fetch,
    hostname,
    port: listenPort,
  },
  () => {
    // O anfitrião e a porta não estão na *allowlist* de `docs/tecnica/08` §7.3,
    // e por isso não saem: quem os quer saber lê a configuração do contentor.
    log.info({ outcome: "service_started" });
  },
);
