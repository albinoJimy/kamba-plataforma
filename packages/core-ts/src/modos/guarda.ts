/**
 * O `PreSendGuard` (KAM-018, critério 2).
 *
 * O KAM-015 abriu a porta e deixou-a a falhar fechada: o `outbound/adapter.ts`
 * chama-a no passo 3, **só** quando `pedido.doBot`, e sem guarda instalada o
 * envio do bot levanta `SemGuardaError` em `KAMBA_ENV=ci`. O que falta a essa
 * porta — e o que este ficheiro entrega — é o corpo, e o corpo é
 * quatro passos dentro de uma transacção:
 *
 * 1. **o *lock* da conversa** — `pg_advisory_xact_lock(hash(tenant_id,
 *    contact_id))`, o **mesmo** `SQL_TRANCAR_CONVERSA` que a `MaquinaDeModos`
 *    toma. É isto que o critério 8 do KAM-015 deu por não cumprido («**Não há
 *    *lock***») e que este ticket fecha;
 * 2. **ler** o modo e a última actividade humana;
 * 3. **decidir**: descarta se `mode ≠ bot` **ou** se `last_human_activity_at`
 *    for posterior ao início do turno;
 * 4. **registar** a supressão em `outbound_messages` com
 *    `state = 'suppressed_by_human'`, e devolver `false` — que é o sinal de
 *    cancelamento que o adapter transforma em `GUARD_REFUSED` para quem pediu o
 *    envio (o AGR).
 *
 * ## Porque é que a linha é escrita aqui e não pelo adapter
 *
 * Por causa da ordem dos sete passos do `adapter.ts`: o guarda é o passo 3 e o
 * `SQL_ENFILEIRAR` é o passo 4. Quando o guarda recusa, o adapter devolve
 * `GUARD_REFUSED` e **nunca** enfileira — não há linha nenhuma para marcar como
 * `suppressed_by_human`. Quem tem de a escrever é quem sabe que suprimiu, e a
 * escrita vai na **mesma** transacção do *lock*: uma supressão registada fora
 * dela podia confirmar sem o modo que a justificou.
 *
 * ## O sinal de cancelamento, e o que ele **não** é
 *
 * O critério 2 diz «devolve ao AGR o sinal de cancelamento». O sinal é o
 * `false`, que o adapter converte em `{ok: false, motivo: "GUARD_REFUSED"}` —
 * um dos onze `MOTIVOS_DE_RECUSA` do dicionário §3.14, que já existia e que
 * nada devolvia por este caminho. **Não há aqui nenhuma chamada ao AGR**, nem
 * fila, nem evento: quem pediu o envio recebe a recusa no valor de retorno, e
 * interromper o turno com ela é do AGR (KAM-025) e da retoma (KAM-034).
 *
 * ## A janela residual, que fica declarada
 *
 * O guarda larga o *lock* no `COMMIT` da sua transacção, e o adapter só depois
 * enfileira e chama a Meta. Um *echo* que chegue nesse intervalo **não** é
 * apanhado: é a «janela residual de corrida = latência do *echo*» que o
 * `docs/tecnica/01` §10.3 declara, e é NÃO MEDIDA (R6/L6, critério de saída em
 * KAM-100). Fechá-la exigia manter o *lock* da conversa aberto durante a chamada
 * HTTP à Meta — uma transacção de base de dados a durar o tempo de uma chamada
 * de rede, por conversa, que é a troca que ninguém quer fazer. O que o desenho
 * garante é o que o critério 3 pede: **0 mensagens do bot depois de o *echo*
 * estar registado**.
 */

import { Logger } from "../logger/index.ts";
import type { Pedido, PreSendGuard } from "../outbound/contrato.ts";
import { MODO_POR_OMISSAO, type ComTenant, type ClienteSql } from "./contrato.ts";
import { SQL_CONVERSA_PARA_MODO, SQL_SUPRIMIR_ENVIO, SQL_TRANCAR_CONVERSA } from "./consultas.ts";
import {
  METRICA_SUPRIMIDAS,
  MetricasDosModos,
  type MotivoDeSupressao,
} from "./metricas.ts";

/** O que a guarda precisa para funcionar. */
export interface DependenciasDaGuarda {
  readonly comTenant: ComTenant;
  readonly metricas?: MetricasDosModos;
  readonly log?: Logger;
}

/**
 * O que a guarda decidiu, para quem quiser ver mais do que o `boolean`.
 *
 * O `PreSendGuard` do KAM-015 devolve `Promise<boolean>` e não se muda: o
 * `avaliar` existe para a bateria poder afirmar **porquê** sem ler métricas, e é
 * ele que o `criarGuarda` embrulha.
 */
export interface DecisaoDaGuarda {
  readonly passa: boolean;
  /** `null` quando passou. */
  readonly motivo: MotivoDeSupressao | null;
  /** O `id` da linha de supressão, ou `null`. Vazio numa repetição. */
  readonly suprimida: string | null;
}

/**
 * A categoria e o template com que uma supressão é registada.
 *
 * **Não se lê a linha do template para confirmar a categoria**, e isso é
 * deliberado: um corpo de template fica como `utility`, que é o que o
 * `categoriaDe` do KAM-015 devolve quando não encontra o template. Ir à base
 * buscar a categoria exacta de uma mensagem que **não** vai sair era uma leitura
 * para nada, e a categoria que a Meta cobraria por uma mensagem que nunca
 * enviou não é um facto. O `template_name` acompanha-a porque a
 * `outbound_messages_template_ck` exige o par — `service` sem template, o resto
 * com.
 */
export function registoDaSupressao(pedido: Pedido): {
  readonly kind: string;
  readonly templateName: string | null;
} {
  if (pedido.corpo.tipo !== "template") return { kind: "service", templateName: null };
  return { kind: "utility", templateName: pedido.corpo.nome };
}

/**
 * A guarda, em forma de porta do KAM-015.
 *
 * Devolve `true` para deixar passar. Não lança: uma conversa que não exista
 * **recusa** o envio em vez de rebentar — um envio do bot para uma conversa que
 * a RLS não vê é um defeito de quem chama, e recusar é o lado seguro (nenhuma
 * mensagem sai) enquanto uma excepção no passo 3 de sete deixava o turno sem
 * resposta e sem registo.
 */
export function criarGuarda(dependencias: DependenciasDaGuarda): PreSendGuard {
  return async (pedido: Pedido) => (await avaliar(dependencias, pedido)).passa;
}

/** A guarda, com o motivo à vista. Ver `DecisaoDaGuarda`. */
export async function avaliar(
  dependencias: DependenciasDaGuarda,
  pedido: Pedido,
): Promise<DecisaoDaGuarda> {
  const metricas = dependencias.metricas ?? new MetricasDosModos();
  return dependencias.comTenant(pedido.tenantId, async (cliente) => {
    // O `contact_id` vem no `Pedido` (o KAM-015 põe-no lá), pelo que a chave do
    // *lock* não precisa de leitura nenhuma: trancar é a **primeira** coisa que
    // acontece, e tudo o que se lê a seguir é lido dentro da secção crítica.
    await cliente.query(SQL_TRANCAR_CONVERSA, [pedido.tenantId, pedido.contactId]);
    const lido = await cliente.query(SQL_CONVERSA_PARA_MODO, [
      pedido.tenantId,
      pedido.conversationId,
    ]);
    const linha = lido.rows[0];
    if (linha === undefined) {
      // **Zero linhas: recusa, e sem escrever linha nenhuma.**
      //
      // A conversa não é deste tenant ou não existe, e as duas tratam-se da
      // mesma maneira. O que **não** se faz é registar a supressão: a
      // `outbound_messages_conversation_fk` é composta com o `tenant_id`
      // (revisão `0010`), pelo que um `INSERT` que aponte para uma conversa que
      // este tenant não tem morre com `23503` — e um `throw` no passo 3 de sete
      // deixava o turno sem resposta **e** sem registo, que é pior do que a
      // recusa. Medido: a primeira versão desta função escrevia a linha, e o
      // ensaio de isolamento do X-03 apanhou a violação de chave estrangeira.
      //
      // E não é perda de informação: uma supressão só se audita contra a
      // conversa que a motivou, e aqui não há nenhuma. O contador continua a
      // contar, que é onde isto fica visível.
      metricas.contar(METRICA_SUPRIMIDAS, "modo");
      dependencias.log?.warn({ outcome: "suprimido_sem_conversa", tenant_id: pedido.tenantId });
      return { passa: false, motivo: "modo", suprimida: null };
    }
    const modo = linha.mode;
    if (modo !== MODO_POR_OMISSAO) {
      // Primeiro teste, e é o do invariante: «o bot nunca interrompe uma
      // conversa em modo dono/humano» (`docs/tecnica/01` §10.2). Um modo que o
      // código não conheça cai aqui também, e isso é o lado certo — não se
      // adivinha um modo para deixar passar um envio.
      return suprimir(cliente, metricas, dependencias.log, pedido, "modo");
    }
    if (pedido.turnoIniciadoEm === undefined) {
      // **Falha fechada, e é um defeito de ligação e não tráfego.** Sem o
      // instante em que o turno começou não há com o que comparar a actividade
      // humana, e as duas alternativas eram piores: deixar passar desligava
      // metade do critério 2 em silêncio, e tratar qualquer actividade humana
      // como posterior ao turno calava o bot para sempre em qualquer conversa
      // que já tivesse tido um *handoff* resolvido. Conta-se em
      // `reply_suppressed_total{motivo="sem_turno"}`, que é um contador que
      // **deve** ficar a zero.
      return suprimir(cliente, metricas, dependencias.log, pedido, "sem_turno");
    }
    const instante = instanteDaLinha(linha.last_human_activity_at);
    if (instante === ILEGIVEL) {
      // **Um instante que não se consegue ler suprime, e não passa.** O `pg`
      // devolve um `timestamptz` como `Date` e esta via não se atinge com ele;
      // atinge-se com outro cliente, e aí a alternativa era pior do que parece:
      // um `new Date("lixo").getTime()` é `NaN`, e `NaN > x` é **false** —
      // deixava passar o envio por causa de um valor que ninguém percebeu. Não
      // se adivinha um instante para deixar o assistente falar; conta-se como
      // actividade humana, que é o lado seguro.
      return suprimir(cliente, metricas, dependencias.log, pedido, "actividade_humana");
    }
    if (instante !== null && instante.getTime() > pedido.turnoIniciadoEm.getTime()) {
      // A corrida do §10.3: o turno começou, uma pessoa falou, e a resposta do
      // bot só agora está pronta. **Estritamente posterior**: uma actividade
      // humana no mesmo milissegundo do início do turno é do turno anterior
      // para todos os efeitos, e recusar aí fazia a primeira resposta de cada
      // conversa retomada do Chatwoot ser suprimida.
      return suprimir(cliente, metricas, dependencias.log, pedido, "actividade_humana");
    }
    return { passa: true, motivo: null, suprimida: null };
  });
}

/** O que a coluna devolve quando não se consegue ler como instante. */
const ILEGIVEL = Symbol("last_human_activity_at ilegivel");

/**
 * O `last_human_activity_at` como `Date`, `null` (não houve) ou `ILEGIVEL`.
 *
 * Três respostas e não duas, e a terceira é a que fecha um fail-open: um
 * `new Date("lixo")` dá um `Date` cujo `getTime()` é `NaN`, e **qualquer**
 * comparação com `NaN` é falsa — um valor ilegível deixava passar o envio em vez
 * de o suprimir. Separado em função para ter nome e teste.
 */
function instanteDaLinha(valor: unknown): Date | null | typeof ILEGIVEL {
  if (valor === null || valor === undefined) return null;
  if (valor instanceof Date) return Number.isNaN(valor.getTime()) ? ILEGIVEL : valor;
  if (typeof valor === "string") {
    const data = new Date(valor);
    return Number.isNaN(data.getTime()) ? ILEGIVEL : data;
  }
  return ILEGIVEL;
}

async function suprimir(
  cliente: ClienteSql,
  metricas: MetricasDosModos,
  log: Logger | undefined,
  pedido: Pedido,
  motivo: MotivoDeSupressao,
): Promise<DecisaoDaGuarda> {
  const { kind, templateName } = registoDaSupressao(pedido);
  const escrito = await cliente.query(SQL_SUPRIMIR_ENVIO, [
    pedido.tenantId,
    pedido.channelId,
    pedido.contactId,
    pedido.conversationId,
    pedido.idempotencyKey,
    kind,
    templateName,
  ]);
  metricas.contar(METRICA_SUPRIMIDAS, motivo);
  // O `tenant_id` pode ir ao registo (está na *allowlist* do
  // `logger/politica.ts`); o `contact_id`, o `conversation_id` e a
  // `idempotency_key` **não**, e por isso não vão. O motivo vai no `outcome`,
  // como o `#recusar` do `outbound/adapter.ts` faz — a *allowlist* não tem
  // campo `motivo` e está certa em não ter: o motivo **é** o desfecho.
  log?.info({ outcome: `suprimido_${motivo}`, tenant_id: pedido.tenantId });
  // O `RETURNING` vazio é a repetição: esta chave já tinha linha. A supressão
  // continua a ser uma supressão — o que não há é uma segunda linha.
  const id = escrito.rows[0]?.id;
  return { passa: false, motivo, suprimida: typeof id === "string" ? id : null };
}
