/**
 * A `Idempotency-Key` do `PATCH /painel/produtos/:id` na base (KAM-240): a
 * `platform.painel_idempotencia`, como `kamba_app` e sob a RLS do tenant **da
 * sessão**. A mesma promessa da versão em memória (`./idempotencia.ts`), mas
 * entre processos: sobrevive a um reinício e vale entre réplicas.
 *
 * ## A tranca é a própria linha, e não um prazo
 *
 * Numa transacção, o `INSERT … ON CONFLICT` **reserva** a chave antes de o PATCH
 * correr; o pedido corre com a transacção aberta, e a resposta grava-se na mesma
 * linha antes do `COMMIT`. Um segundo pedido com a mesma chave, noutro processo,
 * **espera no índice único** pela transacção do primeiro:
 *
 * ```text
 * o primeiro confirma   o segundo lê a linha confirmada: a mesma impressão dá
 *                       a resposta guardada, outra dá «reutilizada» (422)
 * o primeiro desfaz     a linha nunca existiu, e o segundo reserva-a e corre
 * o processo morre      a ligação cai, a base desfaz, e a tranca solta-se
 * ```
 *
 * Não há estado «em curso» com prazo: um prazo é uma janela, porque um PATCH
 * mais lento do que ele deixava o segundo correr ao mesmo tempo. Aqui não há
 * nada que um pedido lento ultrapasse. Uma linha confirmada tem sempre a
 * resposta, porque a reserva e a resposta vão no mesmo `COMMIT`.
 *
 * **O que a tranca não cobre: a ligação que cai com o processo vivo.** Se a
 * ligação de quem reservou cai a meio (o processo morre, a rede corta, a base
 * termina o *backend*), a base desfaz e solta a tranca, e um segundo pedido
 * reserva e corre o seu PATCH — mas o primeiro, se o processo continua vivo,
 * **não é cancelado** e chega na mesma ao COM. O que impede a segunda gravação
 * é então a versão do pedido (obrigatória): o COM aceita a primeira que chegar
 * e recusa a outra com `409`. E a chave pode ficar com esse `409`, se for o
 * segundo a confirmar. É o mesmo desfecho de quando o processo morre depois de
 * o COM gravar e antes do `COMMIT`: a repetição corre outra vez e recebe `409`.
 * **O COM nunca grava duas vezes**; o PATCH pode correr duas, só nestes casos.
 *
 * ## O que não se guarda desfaz-se
 *
 * Uma resposta 5xx ou com `guardar: false` (a sessão revogada) não responde ao
 * pedido. O `kamba_app` não apaga linhas (dicionário §2), pelo que a reserva
 * sai pelo `ROLLBACK`, e a repetição pode tentar outra vez. Uma chave vencida
 * ainda por purgar **reaproveita-se** pelo `DO UPDATE … WHERE expira_at <=
 * now()`; a purga é do executor da retenção, como `kamba_batch`.
 *
 * ## Um *pool* só seu
 *
 * A transacção fica aberta durante as chamadas ao COM, e o `fazer` lê as
 * revogações pelo *pool* da inscrição. No mesmo *pool*, tantos PATCH em curso
 * quantas as ligações esgotavam-no, e cada um esperava por uma ligação que só
 * ele soltava. O `server.ts` dá-lhe um *pool* próprio.
 *
 * **Um limite partilhado entre tenants.** Cada PATCH em curso, e cada pedido
 * repetido à espera da tranca, prende uma ligação desse *pool* durante as
 * chamadas ao COM (até `TECTO_DO_COM_MS` cada). Com as ligações todas presas, o
 * pedido seguinte de qualquer tenant espera pelo `connectionTimeoutMillis` e
 * falha. Em memória não havia recurso partilhado.
 * shortcut: um *pool* de `LIGACOES_DA_IDEMPOTENCIA` por réplica, sem limite por
 * tenant; revê-se com a carga real do painel (KAM-084), ou à primeira recusa
 * por ligação esgotada nas métricas.
 *
 * Guarda-se o SHA-256 da impressão, e não o corpo do pedido. O corpo da
 * resposta guarda-se em `json`, e não `jsonb`: a repetição devolve o texto tal
 * como saiu, com as chaves na mesma ordem.
 */

import { createHash } from "node:crypto";

import { linhasDaInscricao, numaLigacaoDaInscricao, type PoolDaInscricao } from "@kamba/core-ts/inscricao";
import { comTenant } from "@kamba/core-ts/tenant_guard";

import { VALIDADE_DA_CHAVE_MS, type Deduplicacao, type Desfecho, type Guardada } from "./idempotencia.ts";

/**
 * Reserva a chave, ou reaproveita uma vencida. Devolve uma linha só a quem
 * reservou; a quem encontrou uma viva não devolve nada, e fica com ela trancada
 * até ao fim da sua transacção.
 */
export const SQL_RESERVAR_CHAVE = `
  INSERT INTO platform.painel_idempotencia AS i (tenant_id, chave, impressao, criado_at, expira_at)
  VALUES ($1, $2, $3, now(), now() + make_interval(secs => $4))
  ON CONFLICT (tenant_id, chave) DO UPDATE
     SET impressao = EXCLUDED.impressao, criado_at = EXCLUDED.criado_at, expira_at = EXCLUDED.expira_at,
         estado = NULL, corpo = NULL
   WHERE i.expira_at <= now()
  RETURNING true AS reservada`;

/** A resposta, na linha que esta transacção reservou. */
export const SQL_GUARDAR_RESPOSTA = `
  UPDATE platform.painel_idempotencia SET estado = $3, corpo = $4::json
   WHERE tenant_id = $1 AND chave = $2`;

/** A linha viva que outro pedido confirmou. O tenant é o do contexto. */
export const SQL_LER_CHAVE = `
  SELECT impressao, estado, corpo FROM platform.painel_idempotencia
   WHERE tenant_id = $1 AND chave = $2`;

/** Levantado dentro da transacção para a desfazer sem guardar. */
class NaoGuardar extends Error {
  readonly resposta: Guardada;

  constructor(resposta: Guardada) {
    super("resposta por guardar");
    this.resposta = resposta;
  }
}

/** Levantado quando a linha que o índice mostrou não tem resposta: não devia acontecer. */
export class ChaveSemRespostaError extends Error {
  constructor() {
    super("a chave de idempotencia confirmada nao tem resposta");
    this.name = "ChaveSemRespostaError";
  }
}

export class IdempotenciaNaBase implements Deduplicacao {
  readonly #pool: PoolDaInscricao;

  constructor(pool: PoolDaInscricao) {
    this.#pool = pool;
  }

  async uma(tenantId: string, chave: string, impressao: string, fazer: () => Promise<Guardada>): Promise<Desfecho> {
    const digest = createHash("sha256").update(impressao, "utf8").digest();
    return numaLigacaoDaInscricao(this.#pool, async (bd) => {
      try {
        return await comTenant(bd, tenantId, async (tx): Promise<Desfecho> => {
          const reservada = await linhasDaInscricao(tx, SQL_RESERVAR_CHAVE, [
            tenantId,
            chave,
            digest,
            VALIDADE_DA_CHAVE_MS / 1000,
          ]);
          if (reservada.length === 1) {
            const r = await fazer();
            // Uma resposta 5xx não é resposta ao pedido; a sessão revogada também não.
            if (r.estado >= 500 || r.guardar === false) throw new NaoGuardar(r);
            await tx.query(SQL_GUARDAR_RESPOSTA, [tenantId, chave, r.estado, JSON.stringify(r.corpo ?? null)]);
            return { tipo: "nova", resposta: r };
          }
          const [viva] = await linhasDaInscricao(tx, SQL_LER_CHAVE, [tenantId, chave]);
          // A reserva falhou porque há linha, e esta transacção tranca-a: tem de estar aqui.
          if (viva === undefined) throw new ChaveSemRespostaError();
          const guardada = viva["impressao"];
          if (!(guardada instanceof Uint8Array) || !Buffer.from(guardada).equals(digest)) return { tipo: "reutilizada" };
          const estado = viva["estado"];
          if (typeof estado !== "number") throw new ChaveSemRespostaError();
          return { tipo: "repetida", resposta: { estado, corpo: viva["corpo"] } };
        });
      } catch (erro) {
        // O `comTenant` já desfez: a ligação está sã e volta ao *pool* (uma
        // excepção que saísse daqui destruía-a, e o COM em baixo abria uma
        // ligação nova por pedido).
        if (erro instanceof NaoGuardar) return { tipo: "nova", resposta: erro.resposta };
        throw erro;
      }
    });
  }
}
