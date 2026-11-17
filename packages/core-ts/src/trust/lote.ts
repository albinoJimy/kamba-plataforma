/**
 * As varreduras de Trust & Safety agendadas no processo de lote (KAM-200,
 * critério 2).
 *
 * ```text
 * nao_entrega     varrerNaoEntregas    pedidos pagos sem entrega há mais de N dias
 * fotos           varrerFotos          o mesmo phash noutro tenant (informativo)
 * encerramentos   fecharEncerramentos  o encerrado de quem não recorreu no prazo
 * ```
 *
 * ## Uma corrida, uma linha no `audit_log`
 *
 * Cada varredura corre como `kamba_batch` (o papel auditado que atravessa
 * tenants) e deixa **uma** linha `batch.run` na cadeia da plataforma: o
 * `tenant_id` é nulo (`docs/auditoria.md`: o `batch.run` não tem tenant), o
 * `entity` é `ts_varredura`, o `entity_id` é o nome da varredura, e o
 * `payload_hash` é o SHA-256 de `<nome>:<sinais ou tenants>`. As duas
 * primeiras correm **na mesma transacção** que a linha de auditoria: uma
 * corrida que não ficou registada não gravou sinais, e vice-versa. O
 * `fecharEncerramentos` não pode: cada encerramento é uma transição pela porta
 * do KAM-092, numa transacção sob o tenant dele, e a linha de auditoria vem
 * depois, com quantos fechou.
 *
 * ## Uma que falha não pára as outras
 *
 * Como no `CicloDaFila` (`../revisao/ciclo.ts`): cada varredura tem o seu
 * `try`, e o resultado diz quais falharam, **pelo nome**, nunca pela mensagem.
 */

import { comBatch } from "../tenant_guard/index.ts";
import type { ClienteSql } from "../eventos/publicador.ts";
import type { ConjuntoSql } from "../revisao/sql.ts";
import { varrerFotos, varrerNaoEntregas } from "./efeito.ts";
import type { MetricasDoTrust, Varredura } from "./metricas.ts";
import { POLITICA_DE_RISCO, type PoliticaDeRisco } from "./regras.ts";
import type { ServicoDeTrust } from "./servico.ts";
import { RepositorioDeTrustSql } from "./sql.ts";

/** O actor das linhas de auditoria das varreduras: o processo, e não uma pessoa. */
export const ACTOR_DAS_VARREDURAS = "onboarding-lote";

/** A corrida de uma varredura no `audit_log`, na cadeia da plataforma. */
export const SQL_AUDITAR_VARREDURA = `
  SELECT platform.audit_append(
           NULL, 'system', $1, 'batch.run', 'ts_varredura', $2, NULL,
           sha256(convert_to($3, 'UTF8')))
`;

/** Uma volta a cada hora: o prazo mais curto que estas regras medem é de dias (*proposta*). */
export const INTERVALO_DO_TRUST_POR_OMISSAO_MS = 3_600_000;

export interface ResultadoDoCicloDoTrust {
  /** Quantos sinais (ou encerramentos) cada varredura que correu produziu. */
  readonly feitas: Readonly<Partial<Record<Varredura, number>>>;
  /** As que falharam, pelo nome. */
  readonly falhas: readonly Varredura[];
}

export interface OpcoesDoCicloDoTrust {
  /** O conjunto de ligações do `kamba_batch`. */
  readonly lote: ConjuntoSql;
  /** O serviço do lado do lote: com o estado dos tenants, para fechar encerramentos. */
  readonly servico: ServicoDeTrust;
  readonly metricas: MetricasDoTrust;
  readonly politica?: PoliticaDeRisco;
  readonly relogio?: () => Date;
}

export class CicloDoTrust {
  readonly #o: OpcoesDoCicloDoTrust;
  #aCorrer: Promise<ResultadoDoCicloDoTrust> | null = null;

  constructor(o: OpcoesDoCicloDoTrust) {
    this.#o = o;
  }

  /** Uma volta. Duas pedidas ao mesmo tempo são uma. */
  correr(): Promise<ResultadoDoCicloDoTrust> {
    if (this.#aCorrer !== null) return this.#aCorrer;
    this.#aCorrer = this.#volta().finally(() => {
      this.#aCorrer = null;
    });
    return this.#aCorrer;
  }

  agendar(intervaloMs: number, aoTerminar: (r: ResultadoDoCicloDoTrust) => void): () => void {
    if (!Number.isInteger(intervaloMs) || intervaloMs < 1_000) throw new RangeError("intervalo do ciclo abaixo de 1 s");
    const t = setInterval(() => {
      void this.correr().then(aoTerminar);
    }, intervaloMs);
    t.unref();
    return () => clearInterval(t);
  }

  async #volta(): Promise<ResultadoDoCicloDoTrust> {
    const feitas: Partial<Record<Varredura, number>> = {};
    const falhas: Varredura[] = [];
    const opcoes = {
      politica: this.#o.politica ?? POLITICA_DE_RISCO,
      contadores: this.#o.metricas,
      ...(this.#o.relogio === undefined ? {} : { relogio: this.#o.relogio }),
    };
    const passos: readonly (readonly [Varredura, () => Promise<number>])[] = [
      ["nao_entrega", () => this.#numaTransaccao("nao_entrega", (bd) => varrerNaoEntregas(bd, opcoes))],
      ["fotos", () => this.#numaTransaccao("fotos", (bd) => varrerFotos(bd, opcoes))],
      ["encerramentos", () => this.#encerramentos()],
    ];
    for (const [nome, passo] of passos) {
      try {
        feitas[nome] = await passo();
        this.#o.metricas.varredura(nome, "concluida");
      } catch {
        falhas.push(nome);
        this.#o.metricas.varredura(nome, "falhou");
      }
    }
    return { feitas, falhas };
  }

  /** A varredura e a sua linha de auditoria, na mesma transacção, numa ligação dedicada. */
  async #numaTransaccao(nome: Varredura, varrer: (bd: ClienteSql) => Promise<number>): Promise<number> {
    const ligacao = await this.#o.lote.connect();
    let estragada: Error | undefined;
    try {
      return await comBatch(ligacao, `ts_varredura_${nome}`, async () => {
        const n = await varrer(ligacao);
        await ligacao.query(SQL_AUDITAR_VARREDURA, [ACTOR_DAS_VARREDURAS, nome, `${nome}:${n}`]);
        return n;
      });
    } catch (erro) {
      estragada = erro instanceof Error ? erro : new Error("varredura de trust falhou");
      throw erro;
    } finally {
      ligacao.release(estragada);
    }
  }

  async #encerramentos(): Promise<number> {
    const repositorio = new RepositorioDeTrustSql(this.#o.lote, "lote");
    const n = await this.#o.servico.fecharEncerramentos((ate) => repositorio.encerramentosPorFechar(ate));
    await this.#o.lote.query(SQL_AUDITAR_VARREDURA, [ACTOR_DAS_VARREDURAS, "encerramentos", `encerramentos:${n}`]);
    return n;
  }
}
