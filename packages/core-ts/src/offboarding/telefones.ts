/**
 * Os telefones dos clientes para a exportação do off-boarding (KAM-233,
 * critério 3).
 *
 * ## Duas decisões do fundador, e o que cada uma fixa
 *
 * **2026-11-21, Q2 = B:** a decifra é deste lado, em TypeScript, pelo
 * `lerEndpoints` do cofre de contactos (KAM-008) com o `antes`, como o KAM-206.
 * A linha de `audit_log` escreve-se **na transacção da decifra**: se a
 * auditoria falha, nada se decifra; se a decifra falha, a linha desfaz-se.
 *
 * **2026-11-22, Q2b = A:** o meio é o STO do tenant. No fecho da fase
 * `pendentes`, o processo de lote grava um objecto JSON com os campos
 * exportáveis — `contact_id`, `finalidade` e `telefone`, e mais nada — em
 * `t/<tenant>/dsar/…`, a mesma classe e o mesmo destino (ADR-008) do pacote, a
 * expirar no prazo da purga. A exportação Python lê-o para a colecção
 * `telefones` pela chave que a fase `pendentes` guardou, e exige-o. **O custo
 * aceite**: uma segunda cópia em claro no STO até à purga, igual à que o ZIP já
 * leva; a purga apaga as duas com os outros objectos do tenant.
 *
 * ## O que não se decifra
 *
 * Os BSUID (`soTelefones`): o titular recebe os telefones dos clientes dele, e
 * um BSUID é um identificador da Meta, não um dado dele. Os contactos apagados
 * e os fundidos não se lêem — a listagem só traz os vivos, e o `lerEndpoints`
 * de um fundido seguia a fusão e devolvia o telefone do outro outra vez. Um
 * contacto sem telefone não escreve auditoria (o `antes` só corre com linhas a
 * decifrar, KAM-206): dizia que se viu o que não se viu.
 *
 * ## Repetir
 *
 * Um *crash* entre o `put` e a gravação da fase deixa um objecto órfão sob o
 * tenant; a repetição grava outro, e a fase guarda a chave do segundo. O órfão
 * não entra no pacote (a exportação só lê a chave da fase, e salta a classe
 * `dsar` na listagem dos objectos) e sai na purga com o resto do STO do tenant.
 */

import {
  ContactoApagadoError,
  DekDestruidaError,
  type ClienteDeIdentidade,
  type Identidade,
} from "../identity/index.ts";
import { novaChave, type StorageProvider } from "../storage/index.ts";
import { comTenant } from "../tenant_guard/index.ts";

/** A acção de auditoria de cada contacto cujos telefones se exportaram (revisão `0086`). */
export const ACCAO_DOS_TELEFONES = "privacy.telefones_exportados";

/** A classe do objecto: a do pacote, e o mesmo destino ADR-008. */
export const CLASSE_DOS_TELEFONES = "dsar";

/** O nome da colecção, no objecto e no pacote. */
export const COLECCAO_DOS_TELEFONES = "telefones";

/** Os contactos vivos do tenant, como `kamba_identity`, sob a RLS do tenant e com o tenant no texto. */
export const SQL_CONTACTOS_DO_TENANT = `
  SELECT contact_id::text AS contact_id
    FROM platform.contacts
   WHERE tenant_id = $1 AND erased_at IS NULL AND merged_into IS NULL
   ORDER BY contact_id
`;

/**
 * A linha de auditoria, pelo `audit_append` (o `EXECUTE` que a `0082` deu ao
 * `kamba_identity`). `system` e o nome do processo como actor; o contacto em
 * `entity_id`; o `payload_hash` é o SHA-256 do texto canónico, **sem** os
 * telefones, nem resumidos.
 */
export const SQL_AUDITAR_TELEFONES = `
  SELECT platform.audit_append(
    $1::uuid, 'system', 'offboarding', 'privacy.telefones_exportados', 'contact', $2, NULL, sha256($3::bytea)
  )
`;

/**
 * O texto canónico do `payload_hash`: a acção e o contacto. Sem a contagem: o
 * `antes` corre antes da decifra e não a sabe, e um número escrito antes de
 * decifrar era uma afirmação sobre o que ainda não se tinha visto.
 */
export function textoDaAuditoria(contactId: string): string {
  return [ACCAO_DOS_TELEFONES, contactId].join("\x1f");
}

/** Uma linha da colecção. Os três campos exportáveis, e mais nenhum. */
export interface TelefoneExportavel {
  readonly contact_id: string;
  readonly finalidade: string;
  readonly telefone: string;
}

/** O que a fase `pendentes` guarda: a chave do objecto e as contagens. Nenhum telefone. */
export interface EntregaDosTelefones {
  readonly chave: string;
  readonly contactos: number;
  readonly telefones: number;
}

/** A porta: decifra, grava no STO e devolve a chave. */
export interface PortaDosTelefones {
  entregar(o: { readonly tenantId: string; readonly expiraAt: Date; readonly agora: Date }): Promise<EntregaDosTelefones>;
}

/** Uma ligação tomada a um *pool* do `pg` do `kamba_identity`. */
export interface LigacaoDaIdentidade extends ClienteDeIdentidade {
  release(erro?: Error | boolean): void;
}

/** O *pool* do `kamba_identity`: só o `connect`. */
export interface PoolDaIdentidade {
  connect(): Promise<LigacaoDaIdentidade>;
}

function linhas(r: unknown): readonly Record<string, unknown>[] {
  const rows = (r as { rows?: unknown } | null)?.rows;
  return Array.isArray(rows) ? (rows as Record<string, unknown>[]) : [];
}

/** As linhas, por contacto, finalidade e telefone: o mesmo conteúdo dá o mesmo documento. */
export function ordenar(linhas: readonly TelefoneExportavel[]): TelefoneExportavel[] {
  const chave = (l: TelefoneExportavel) => `${l.contact_id}\x1f${l.finalidade}\x1f${l.telefone}`;
  return [...linhas].sort((a, b) => (chave(a) < chave(b) ? -1 : chave(a) > chave(b) ? 1 : 0));
}

/** A porta pelo cofre de contactos e pelo STO do tenant. */
export function telefonesPeloCofre(o: {
  readonly pool: PoolDaIdentidade;
  readonly identidade: Pick<Identidade, "lerEndpoints">;
  readonly armazenamento: StorageProvider;
}): PortaDosTelefones {
  return {
    async entregar({ tenantId, expiraAt, agora }): Promise<EntregaDosTelefones> {
      const lidas: TelefoneExportavel[] = [];
      let contactos = 0;
      // Uma ligação, e uma transacção por contacto: o `comTenant` recusa uma
      // ligação a meio de outra transacção, e o `lerEndpoints` abre a sua.
      const ligacao = await o.pool.connect();
      let falha: Error | undefined;
      try {
        const ids = await comTenant(ligacao, tenantId, async (tx) =>
          linhas(await tx.query(SQL_CONTACTOS_DO_TENANT, [tenantId])).map((l) => String(l.contact_id)),
        );
        for (const contactId of ids) {
          let lidos;
          try {
            lidos = await o.identidade.lerEndpoints(ligacao, tenantId, contactId, {
              soTelefones: true,
              antes: async (cliente) => {
                // Em octetos, pela razão do KAM-206 (a entrada `escape` do PostgreSQL).
                await cliente.query(SQL_AUDITAR_TELEFONES, [
                  tenantId,
                  contactId,
                  Buffer.from(textoDaAuditoria(contactId), "utf8"),
                ]);
              },
            });
          } catch (erro) {
            // Apagado ou com a DEK destruída entre a listagem e a leitura: não há
            // telefone a exportar, e a transacção desfez a auditoria com ela.
            if (erro instanceof ContactoApagadoError || erro instanceof DekDestruidaError) continue;
            throw erro;
          }
          if (lidos.telefones.length === 0) continue;
          contactos += 1;
          for (const t of lidos.telefones) {
            lidas.push({ contact_id: contactId, finalidade: t.finalidade, telefone: t.telefone });
          }
        }
      } catch (erro) {
        falha = erro instanceof Error ? erro : new Error(String(erro));
        throw erro;
      } finally {
        // Com erro, o `pg` descarta a ligação em vez de a devolver ao *pool*.
        ligacao.release(falha ?? false);
      }

      const documento = { coleccao: COLECCAO_DOS_TELEFONES, tenant_id: tenantId, linhas: ordenar(lidas) };
      const ctx = { tenantId };
      const ref = await o.armazenamento.put(
        ctx,
        novaChave(ctx, CLASSE_DOS_TELEFONES, agora),
        new TextEncoder().encode(JSON.stringify(documento)),
        { contentType: "application/json", classe: CLASSE_DOS_TELEFONES, retainUntil: expiraAt },
      );
      return { chave: ref.key, contactos, telefones: lidas.length };
    },
  };
}
