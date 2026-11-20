/**
 * O caso de onboarding avança até `es_concluido` em produção (KAM-215,
 * critério 1): o emissor do `tenant.provisioned`.
 *
 * ## Quem chama o `advance_case`, e porque é um varrimento
 *
 * A `platform.advance_case` da revisão `0058` emite o `tenant.provisioned` no
 * `es_concluido`, e até ao KAM-215 **nenhum serviço a chamava para lá de
 * `aprovado`**. Três eventos levam o caso de `aprovado` a `aguarda_catalogo`, e
 * cada um tem um facto que o prova, já escrito por quem o produz:
 *
 *     aprovado       --saga_iniciada-->   provisionando   a saga abriu um passo
 *     provisionando  --saga_concluida-->  aguarda_es      os cinco passos que não
 *                                                         esperam estão concluídos
 *     aguarda_es     --es_concluido-->    aguarda_catalogo  um canal vivo, e só um
 *
 * O varrimento lê os factos e chama a porta; **não** os escreve. É a forma do
 * `varrerAprovacoes` do KAM-201 (`../revisao/entradas.ts`): corre no ciclo do
 * processo de lote do onboarding, como `kamba_batch` — que vê os casos de todos
 * os tenants (`BYPASSRLS`, auditado) e é o papel com que a porta corre —, e cada
 * caso numa transacção sua, sob o `app.tenant_id` do caso, que a função exige
 * (`42501` sem ele).
 *
 * **O predicado do canal é o da função**, letra a letra: um canal que não esteja
 * `desligado` nem `encerrado`, e exactamente um. Um predicado mais largo aqui
 * chamava a porta para ela recusar com `55000` em cada volta; um mais estreito
 * deixava um caso pronto por avançar.
 *
 * ## Uma vez por caso, e porque não é deste ficheiro
 *
 * A idempotência é da porta: o `SELECT … FOR UPDATE` sobre o caso põe a segunda
 * chamada à espera da primeira, e a segunda vê o caso já no destino e devolve sem
 * escrever nem emitir. Duas réplicas do processo, ou a mesma volta repetida,
 * dão **um** `tenant.provisioned` — medido contra a base.
 *
 * ## O que este ficheiro não faz
 *
 * Não corre a saga, nem liga o Embedded Signup: os factos de que depende são da
 * saga do KAM-091 (o `provisioning_step`) e do canal ligado (o
 * `tenant_channels`), e é por isso que, sem eles, nenhum caso avança — que é o
 * certo, porque um `tenant.provisioned` sem canal anunciava um número que não
 * existe.
 */

import { comTenant, type ClienteSql } from "../tenant_guard/index.ts";

import { PASSOS, PASSOS_DE_ESPERA } from "./contrato.ts";

/** O `actor` que a porta recebe. Diz quem avançou, e não é identificador de pessoa. */
export const ACTOR_DO_AVANCO = "lote:provisionamento";

/** Quantas passagens por volta: os três eventos de `aprovado` a `aguarda_catalogo`. */
export const PASSAGENS_POR_VOLTA = 3;

/** Os passos que a saga conclui antes de esperar pelo Embedded Signup. */
export const PASSOS_ANTES_DO_ES: readonly string[] = PASSOS.filter(
  (p) => !(PASSOS_DE_ESPERA as readonly string[]).includes(p),
);

/**
 * Os casos que um facto já deixa avançar, com o evento. `kamba_batch`, sem
 * contexto: atravessa tenants. `$1` são os passos antes do ES, `$2` o limite.
 */
export const SQL_CASOS_POR_AVANCAR = `
SELECT c.id::text AS onboarding_id, c.tenant_id::text AS tenant_id, c.fase, e.evento
  FROM platform.onboarding_case c
 CROSS JOIN LATERAL (
   SELECT CASE
     WHEN c.fase = 'aprovado'
      AND EXISTS (SELECT 1 FROM platform.provisioning_step p WHERE p.onboarding_id = c.id)
       THEN 'saga_iniciada'
     WHEN c.fase = 'provisionando'
      AND (SELECT count(DISTINCT p.step) FROM platform.provisioning_step p
            WHERE p.onboarding_id = c.id AND p.status = 'concluido'
              AND p.step = ANY ($1::text[])) = cardinality($1::text[])
       THEN 'saga_concluida'
     WHEN c.fase = 'aguarda_es'
      AND (SELECT count(*) FROM platform.tenant_channels ch
            WHERE ch.tenant_id = c.tenant_id
              AND ch.estado NOT IN ('desligado', 'encerrado')) = 1
       THEN 'es_concluido'
   END AS evento) e
 WHERE c.fase IN ('aprovado', 'provisionando', 'aguarda_es')
   AND e.evento IS NOT NULL
 ORDER BY c.fase_at, c.id
 LIMIT $2`;

/**
 * Tranca o caso e relê a fase, **dentro** da transacção do avanço e antes da
 * porta, pela mesma ordem que ela tranca. Ver a nota do `varrerProvisionamentos`.
 */
export const SQL_TRANCAR_CASO = "SELECT fase FROM platform.onboarding_case WHERE id = $1 FOR UPDATE";

/** A porta da `0058`. Emite o `tenant.provisioned` no `es_concluido`. */
export const SQL_AVANCAR_CASO = "SELECT platform.advance_case($1, $2, $3) AS fase";

/** Um conjunto de ligações do `kamba_batch`: a forma do `pg.Pool`. */
export interface ConjuntoDoLote extends ClienteSql {
  connect(): Promise<ClienteSql & { release(erro?: Error | boolean): void }>;
}

/** Um ou mais casos não avançaram nesta volta. Os outros avançaram. */
export class AvancoComFalhasError extends Error {
  override readonly name = "AvancoComFalhasError";
  readonly avancados: number;
  readonly falhados: number;

  constructor(avancados: number, falhados: number) {
    // Contagens, e nenhum caso nem tenant: quem quer saber qual lê a base.
    super(`o avanco do provisionamento falhou em ${falhados} caso(s); ${avancados} avancaram`);
    this.avancados = avancados;
    this.falhados = falhados;
  }
}

interface Candidato {
  readonly onboarding_id: string;
  readonly tenant_id: string;
  readonly fase: string;
  readonly evento: string;
}

/**
 * Uma volta: avança cada caso que um facto já deixa avançar, até três passagens
 * (um caso com a saga feita e o canal ligado vai de `aprovado` a
 * `aguarda_catalogo` na mesma volta). Devolve quantos avanços fez; com alguma
 * falha, avança os outros e lança `AvancoComFalhasError` no fim.
 *
 * **Um candidato pode estar velho quando chega a vez dele**: outra réplica do
 * processo (ou uma volta que se sobrepôs) avançou o caso entre a leitura e a
 * transacção. A porta reconhece a repetição do **mesmo** evento, mas não a de
 * um evento anterior — um `saga_iniciada` sobre um caso já em `aguarda_es` é
 * recusado com `23514`. Por isso a transacção tranca o caso e relê a fase antes
 * de chamar a porta, e um caso que já não está onde foi lido salta-se: não é
 * falha, é trabalho que outro fez.
 */
export async function varrerProvisionamentos(o: { readonly lote: ConjuntoDoLote; readonly limite: number }): Promise<number> {
  let avancados = 0;
  let falhados = 0;
  // Um caso que falhou não se tenta outra vez na mesma volta: falharia igual, e
  // a volta seguinte repete.
  const falhou = new Set<string>();
  for (let passagem = 0; passagem < PASSAGENS_POR_VOLTA; passagem++) {
    const resposta = (await o.lote.query(SQL_CASOS_POR_AVANCAR, [PASSOS_ANTES_DO_ES, o.limite])) as {
      readonly rows: readonly Candidato[];
    };
    const candidatos = resposta.rows.filter((c) => !falhou.has(c.onboarding_id));
    if (candidatos.length === 0) break;
    for (const c of candidatos) {
      const ligacao = await o.lote.connect();
      let estragada = false;
      try {
        const avancou = await comTenant(ligacao, c.tenant_id, async (tx) => {
          const lida = (await tx.query(SQL_TRANCAR_CASO, [c.onboarding_id])) as { readonly rows: readonly { fase?: unknown }[] };
          if (lida.rows[0]?.fase !== c.fase) return false;
          await tx.query(SQL_AVANCAR_CASO, [c.onboarding_id, c.evento, ACTOR_DO_AVANCO]);
          return true;
        });
        if (avancou) avancados++;
      } catch {
        estragada = true;
        falhados++;
        falhou.add(c.onboarding_id);
      } finally {
        ligacao.release(estragada);
      }
    }
  }
  if (falhados > 0) throw new AvancoComFalhasError(avancados, falhados);
  return avancados;
}
