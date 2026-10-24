/**
 * `@kamba/core-ts/agr` — o *shim* da fila do runtime de agentes (KAM-025).
 *
 * O AGR é um processo **Python** (`services/agr`), e é lá que vive tudo o que
 * decide: a tranca por conversa, a coalescência, os tectos de concorrência e
 * quem tem a palavra. O que está deste lado é a casca que tira um *job* da
 * `agr-inbound` — a fila que o CHR enche (`../chr/fila.ts`) — e o entrega ao
 * AGR por `POST /internal/turn`.
 *
 * A escolha entre isto e um consumidor Python do BullMQ está em
 * `docs/adr/ADR-L004-fila-e-tranca-do-agr.md` (Decisão 1).
 *
 * ```ts
 * import { criarShimDoAgr } from "@kamba/core-ts/agr";
 *
 * const shim = criarShimDoAgr({
 *   url: process.env.KAMBA_REDIS_URL!,
 *   agr: process.env.KAMBA_AGR_URL!,          // http://agr:8000, rede interna
 *   credencial: () => secrets.get("agr_internal_token"),
 *   aoTratar: (desfecho) => log.info({ outcome: desfecho }),
 *   aoFalhar: (erro) => log.excepcao(erro, "agr_shim"),
 * });
 * ```
 *
 * **A credencial é uma função, e não uma cadeia.** O `agr_internal_token` roda
 * (`ops/secrets-inventory.yaml`, 90 dias), e um valor lido uma vez no arranque
 * ficava a levar 401 depois da rotação.
 */

export {
  CABECALHO_INTERNO,
  CAMINHO_DO_TURNO,
  CONCORRENCIA,
  DESFECHOS_DO_AGR,
  ESPERA_MAXIMA_MS,
  TENTATIVAS,
  TENTATIVAS_DO_AGR,
  TRANCA_DO_JOB_MS,
  VARIAVEL_DO_AGR,
  desfechoDe,
  type DesfechoDoAgr,
} from "./contrato.ts";

export {
  CONTADORES,
  DESFECHOS,
  METRICA_FALHAS,
  METRICA_JOBS,
  METRICAS_DO_SHIM,
  MetricaDesconhecidaError,
  MetricasDoShim,
  SufixoInvalidoError,
} from "./metricas.ts";

export {
  AJUSTES_DO_SHIM,
  AgrIndisponivelError,
  CredencialRecusadaError,
  chamarOTurno,
  type OpcoesDoShim,
} from "./shim.ts";

export { criarShimDoAgr, type ShimDoAgr } from "./trabalhador.ts";
