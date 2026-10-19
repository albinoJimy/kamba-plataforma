/**
 * O webhook da Meta: verificação, assinatura, deduplicação, 200 rápido e fila
 * (KAM-013).
 *
 * É o único endpoint de webhook da plataforma (ADR-001). O Chatwoot recebe um
 * espelho (KAM-019) e não fala com a Meta.
 *
 * ## O caminho de um `POST`, por ordem, e porque é esta a ordem
 *
 * 1. **Ler os bytes.** `c.req.arrayBuffer()`, nunca `c.req.text()` nem
 *    `c.req.json()`: a assinatura é sobre o corpo **bruto**, e o critério 2
 *    exige que um corpo re-serializado com a mesma assinatura seja recusado.
 * 2. **Verificar a assinatura.** Antes de qualquer `parse`. Falha → 401 e
 *    `gwy_sig_fail`. Nada do corpo é lido, interpretado ou registado antes
 *    disto: um corpo não assinado não é tráfego da Meta, e tratá-lo era dar a
 *    quem não tem o segredo uma via para a nossa fila.
 * 3. **Calcular o `jobId`.** `sha256` do corpo. É o primeiro dos dois níveis de
 *    deduplicação: apanha a re-entrega byte-a-byte, que é a forma comum da
 *    repetição de sete dias da Meta (`E1` §5).
 * 4. **Decidir o descarte**, só se a fila estiver saturada. Ver
 *    `TECTO_DA_FILA`.
 * 5. **Enfileirar, e só depois responder 200.** O `await` é o critério 5: um
 *    200 antes de o *job* estar na fila é uma mensagem perdida que a Meta já não
 *    repete. Falha → 503, que é o que faz a Meta repetir.
 *
 * ## O que não acontece neste caminho
 *
 * Nenhuma ida à base de dados. Nenhuma leitura de segredo ao cofre. Nenhum
 * `JSON.parse`, excepto no passo 4 e só quando a fila já está saturada. O
 * segredo e a profundidade da fila vêm de **cache em memória**, que outro
 * mecanismo refresca (`server.ts`): um `getRing` por pedido é um HTTP por
 * pedido com o provedor Doppler, e isso é precisamente o I/O que o alvo de
 * «200 em < 500 ms» não aguenta.
 */

import { timingSafeEqual } from "node:crypto";

import type { Context, Hono } from "hono";
import {
  CABECALHO_DA_ASSINATURA,
  CAMPO_DAS_MENSAGENS,
  FILA_ENTRADA,
  JOB_ENTRADA,
  METRICAS,
  METRICA_ASSINATURA_FALHOU,
  METRICA_DESCARTADOS,
  METRICA_ENFILEIRAMENTO_MS,
  METRICA_PEDIDOS,
  assinaturaValida,
  sha256Hex,
} from "@kamba/core-ts/entrada";
import type { Filas } from "@kamba/core-ts/eventos";
import type { Logger } from "@kamba/core-ts/logger";

/** O caminho do webhook. O mesmo no `GET` de verificação e no `POST`. */
export const CAMINHO = "/wa/webhook";

/**
 * Profundidade da fila acima da qual se descarta. *Proposta* do critério 7.
 *
 * Dez mil *jobs* por fazer com o *worker* a consumir é meia hora de atraso na
 * entrada; é o ponto em que valer mais perder um estado do que atrasar uma
 * mensagem. O número é do bloco do ticket e calibra-se em KAM-084.
 */
export const TECTO_DA_FILA = 10_000;

/**
 * Tamanho máximo de um corpo de webhook, em bytes. **Recusa-se antes de o ler.**
 *
 * Achado da revisão adversarial, e é o pior dos que ela encontrou: o
 * `arrayBuffer()` lia o corpo **inteiro** antes de a assinatura ser verificada,
 * sem tecto nenhum. Qualquer pessoa, sem segredo, fazia um `POST` de 200 MB e o
 * processo alocava os 200 MB antes de responder 401 — no único endpoint público
 * da plataforma, com duas réplicas e nada entre elas e a Internet (o *proxy* é
 * KAM-077 e não existe).
 *
 * 1 MiB é *proposta*, e é duas ordens de magnitude acima do que a Meta manda: um
 * corpo com uma mensagem tem centenas de bytes e um lote de estados tem
 * kilobytes. O `E1` §5 limita a **taxa** — 3× estados mais 1× entrada — e não
 * diz o tamanho máximo de um corpo; o número existe para haver tecto, e
 * calibra-se onde se mede (KAM-024, com o simulador, e KAM-084).
 *
 * Responde **413** e não 401: não é um problema de assinatura, e a Meta não
 * repete um 4xx indefinidamente. Um corpo legítimo que batesse neste tecto
 * apareceria como `gwy_sig_fail` se se respondesse 401, e isso mandava procurar
 * no sítio errado.
 */
export const CORPO_MAXIMO = 1_048_576;

/** O que o `GET` de verificação da Meta manda, e o que se responde. */
export const MODO_DE_SUBSCRICAO = "subscribe";

/** O que o webhook precisa de fora. Tudo síncrono, excepto a fila. */
export interface DependenciasDoWebhook {
  /**
   * `[actual, anterior]` do App Secret, **de cache**. Síncrono de propósito:
   * ver a docstring do módulo.
   */
  readonly anel: () => readonly (string | null)[];
  /** O `verify_token`, de cache. */
  readonly verifyToken: () => string;
  readonly filas: Filas;
  /**
   * A última profundidade conhecida da fila, ou `null` se não se conseguiu ler.
   *
   * `null` **não** é saturação: uma profundidade que não se consegue ler não é
   * uma fila cheia, e descartar por não saber era descartar por avaria no
   * sítio errado.
   */
  readonly profundidade: () => number | null;
  readonly fila?: string;
  readonly agora?: () => number;
}

/**
 * Comparação de dois textos em tempo constante, sem lançar.
 *
 * O `timingSafeEqual` do Node exige buffers do mesmo comprimento. Os
 * comprimentos comparam-se primeiro — e isso **revela** o comprimento do
 * `verify_token`, que é a única fuga possível aqui e é aceitável: o que o
 * atacante não consegue é descobrir o conteúdo byte a byte pelo tempo, que é o
 * ataque real contra uma comparação ingénua.
 */
function iguais(a: string, b: string): boolean {
  const esquerda = Buffer.from(a, "utf8");
  const direita = Buffer.from(b, "utf8");
  if (esquerda.length !== direita.length) return false;
  return timingSafeEqual(esquerda, direita);
}

/**
 * O corpo é só estados sem preço?
 *
 * É a condição do descarte do critério 7 — «são descartados estados não
 * facturáveis, nunca `messages`» — e é **conservadora de propósito**, por duas
 * razões que se somam:
 *
 * - **O campo que diz se um estado é facturável é NÃO VERIFICADO.** A
 *   `evidencia/E1` §5 não documenta a forma do `pricing` dentro de um
 *   `statuses[]`; o que se sabe é que há informação de preço lá (o `KAM-024`
 *   gera *fixtures* de `statuses` «com `pricing`»). Por isso a regra não é
 *   «`pricing.billable === false`» — seria desenho sobre um campo que ninguém
 *   confirmou. A regra é: **um estado que traga `pricing`, de qualquer forma,
 *   não se descarta.** O custo por mensagem é o KAM-015 e o *free tier* é o
 *   KAM-023; perder a linha que os alimenta é perder dinheiro contabilizado.
 * - **Uma mensagem nunca se descarta.** Basta um `messages[]` com um item em
 *   qualquer `change` de qualquer `entry` para o corpo inteiro ser enfileirado.
 *   Não se parte o corpo: o *job* é o corpo, e um corpo meio descartado é um
 *   `jobId` que já não corresponde ao que lá está.
 *
 * Um corpo que não se consegue interpretar devolve `false`: o que não se
 * classifica não se descarta — vai à fila e, se for lixo, à quarentena
 * (critério 6).
 */
export function soEstadosSemPreco(texto: string): boolean {
  let corpo: unknown;
  try {
    corpo = JSON.parse(texto);
  } catch {
    return false;
  }
  if (typeof corpo !== "object" || corpo === null) return false;
  const entradas = (corpo as Record<string, unknown>).entry;
  if (!Array.isArray(entradas) || entradas.length === 0) return false;

  let estados = 0;
  for (const entrada of entradas) {
    if (typeof entrada !== "object" || entrada === null) return false;
    const mudancas = (entrada as Record<string, unknown>).changes;
    if (!Array.isArray(mudancas) || mudancas.length === 0) return false;
    for (const mudanca of mudancas) {
      if (typeof mudanca !== "object" || mudanca === null) return false;
      // **O campo tem de ser `messages`.** Sem esta linha, um
      // `account_update` cujo `value` trouxesse um array chamado `statuses`
      // era descartado em silêncio — e um `account_update` perdido é um canal
      // que mudou de estado sem ninguém saber. Apanhado pelo teste «é falso
      // para tudo o que não seja isso», que é a razão de ele enumerar casos em
      // vez de confirmar o caso bom.
      if ((mudanca as Record<string, unknown>).field !== CAMPO_DAS_MENSAGENS) return false;
      const valor = (mudanca as Record<string, unknown>).value;
      if (typeof valor !== "object" || valor === null) return false;
      const registo = valor as Record<string, unknown>;
      // Qualquer coisa que não seja um array de estados torna o corpo
      // indescartável: um `messages`, um `errors`, um campo que não se conhece.
      for (const chave of Object.keys(registo)) {
        if (chave !== "statuses" && chave !== "metadata" && chave !== "messaging_product") {
          return false;
        }
      }
      const lista = registo.statuses;
      if (!Array.isArray(lista) || lista.length === 0) return false;
      for (const estado of lista) {
        if (typeof estado !== "object" || estado === null) return false;
        if ("pricing" in (estado as Record<string, unknown>)) return false;
        estados += 1;
      }
    }
  }
  return estados > 0;
}

/** Monta o `GET` de verificação e o `POST` do webhook em `app`. */
export function montarWebhook(
  app: Hono,
  dependencias: DependenciasDoWebhook,
  log?: Logger,
): void {
  const fila = dependencias.fila ?? FILA_ENTRADA;
  const agora = dependencias.agora ?? (() => Date.now());

  /**
   * `GET` de verificação (critério 1, CONFIRMADO `E1` §5).
   *
   * 403 com `verify_token` errado — o código é *proposta* do bloco do ticket. E
   * 403 também quando falta o `hub.mode` ou o `hub.challenge`: uma verificação
   * sem desafio não é uma verificação, e a Meta manda sempre os três. Não se
   * distingue «token errado» de «pedido malformado» na resposta, de propósito:
   * é um endpoint público e a diferença só interessa a quem está a sondar. A
   * diferença fica no registo, pelo `outcome`.
   */
  app.get(CAMINHO, (c: Context) => {
    const inicio = agora();
    METRICAS.contar(METRICA_PEDIDOS);
    const modo = c.req.query("hub.mode") ?? "";
    const token = c.req.query("hub.verify_token") ?? "";
    const desafio = c.req.query("hub.challenge") ?? "";

    if (modo !== MODO_DE_SUBSCRICAO || desafio === "") {
      log?.warn({ outcome: "verificacao_malformada", latency_ms: agora() - inicio });
      return c.text("forbidden", 403);
    }
    const esperado = dependencias.verifyToken();
    if (esperado === "" || !iguais(token, esperado)) {
      log?.warn({ outcome: "verificacao_recusada", latency_ms: agora() - inicio });
      return c.text("forbidden", 403);
    }
    log?.info({ outcome: "verificacao_aceita", latency_ms: agora() - inicio });
    // O corpo é **exactamente** o desafio: a Meta compara-o byte a byte.
    return c.text(desafio, 200);
  });

  app.post(CAMINHO, async (c: Context) => {
    const inicio = agora();
    METRICAS.contar(METRICA_PEDIDOS);

    // **O tecto confere-se antes de ler o corpo.** O `content-length` é de quem
    // chama e pode mentir, pelo que há duas guardas: esta, que evita alocar o
    // que já se sabe ser grande demais, e a de baixo, que mede o que chegou de
    // facto — um pedido com `transfer-encoding: chunked` não traz
    // `content-length` nenhum, e sem a segunda guarda passava por aqui.
    const declarado = Number(c.req.header("content-length") ?? "");
    if (Number.isFinite(declarado) && declarado > CORPO_MAXIMO) {
      log?.warn({ outcome: "corpo_grande_demais", latency_ms: agora() - inicio });
      return c.text("payload too large", 413);
    }

    const bruto = new Uint8Array(await c.req.arrayBuffer());
    if (bruto.byteLength > CORPO_MAXIMO) {
      log?.warn({ outcome: "corpo_grande_demais", latency_ms: agora() - inicio });
      return c.text("payload too large", 413);
    }
    if (!assinaturaValida(bruto, c.req.header(CABECALHO_DA_ASSINATURA), dependencias.anel())) {
      METRICAS.contar(METRICA_ASSINATURA_FALHOU);
      // Nada do corpo entra no registo: não foi assinado, e por isso não se sabe
      // de quem é nem o que leva.
      log?.warn({ outcome: "assinatura_invalida", latency_ms: agora() - inicio });
      return c.text("invalid signature", 401);
    }

    const jobId = sha256Hex(bruto);
    const corpo = Buffer.from(bruto).toString("base64");

    const profundidade = dependencias.profundidade();
    if (profundidade !== null && profundidade > TECTO_DA_FILA) {
      // `Buffer.toString('utf8')` e não o `bruto`: o `JSON.parse` precisa de
      // texto. Um corpo que não seja UTF-8 válido dá caracteres de substituição
      // e o `parse` falha — e um `parse` que falha não descarta nada.
      if (soEstadosSemPreco(Buffer.from(bruto).toString("utf8"))) {
        METRICAS.contar(METRICA_DESCARTADOS);
        log?.warn({
          outcome: "descartado_por_saturacao",
          latency_ms: agora() - inicio,
        });
        // 200, e não 503: 503 fazia a Meta repetir o que acabámos de decidir
        // não querer, e a repetição dura sete dias.
        return c.text("ok", 200);
      }
    }

    const antesDaFila = agora();
    try {
      // `addLote` com um trabalho e não um `add`: a porta das filas (KAM-005) só
      // tem o lote, e é ele que garante a idempotência por `jobId` — que é o que
      // o critério 4 pede. Um `add` próprio era uma segunda via para a mesma
      // fila, com outra configuração de retentativas.
      await dependencias.filas.addLote(fila, [
        { jobId, nome: JOB_ENTRADA, dados: { corpo, recebidoEm: antesDaFila } },
      ]);
    } catch (erro) {
      METRICAS.medir(METRICA_ENFILEIRAMENTO_MS, agora() - antesDaFila);
      // 503 e nunca 200: a Meta repete até sete dias, o que transforma a fila em
      // baixo num atraso recuperável em vez de mensagens perdidas (critério 5).
      log?.excepcao(erro, "fila_indisponivel", { latency_ms: agora() - inicio });
      return c.text("queue unavailable", 503);
    }
    METRICAS.medir(METRICA_ENFILEIRAMENTO_MS, agora() - antesDaFila);

    log?.info({ outcome: "webhook_enfileirado", latency_ms: agora() - inicio });
    return c.text("ok", 200);
  });
}
