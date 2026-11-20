/**
 * O leitor de contactos do COM sobre a identidade do KAM-008 (KAM-206).
 *
 * **Decisão do fundador de 2026-11-20, opção A**: o COM passa a ser o terceiro
 * consumidor do `db_identity_password` e da `kek_contact_dek`, e decifra o
 * telefone de uma encomenda como `kamba_identity`. O papel só ganhou, para isso,
 * o `EXECUTE` no `audit_append` e o `INSERT` nas colunas dele (revisão `0082`):
 * a linha de auditoria escreve-se **na transacção da decifra**, pelo `antes` do
 * `lerEndpoints`, e uma falha de uma desfaz a outra.
 *
 * Uma ligação do *pool* por leitura, tomada e devolvida aqui: o `comTenant` do
 * `tenant_guard` recusa um *pool* e recusa uma ligação partilhada a meio de outra
 * transacção, e o COM atende pedidos concorrentes.
 *
 * O contacto apagado e a chave de dados destruída **não** são erros para o dono:
 * não há telefone a mostrar, e a transacção desfez-se com a linha de auditoria.
 * Devolvem `null`. Qualquer outra falha sobe, e a rota responde 500 sem corpo
 * revelador.
 */

import {
  ContactoApagadoError,
  DekDestruidaError,
  type ClienteDeIdentidade,
  type Identidade,
} from "@kamba/core-ts/identity";

import type { LeitorDeContactos, TelefoneDoContacto } from "./contacto.ts";

/** Uma ligação tomada a um *pool* do `pg`: o `query` e o `release`. */
export interface LigacaoDaIdentidade extends ClienteDeIdentidade {
  release(): void;
}

/** O *pool* do `kamba_identity`: só o `connect`. */
export interface PoolDaIdentidade {
  connect(): Promise<LigacaoDaIdentidade>;
}

export function leitorPelaIdentidade(opcoes: {
  readonly pool: PoolDaIdentidade;
  readonly identidade: Pick<Identidade, "lerEndpoints">;
}): LeitorDeContactos {
  return {
    async telefones(tenantId, contactId, antes): Promise<readonly TelefoneDoContacto[] | null> {
      const ligacao = await opcoes.pool.connect();
      try {
        const lidos = await opcoes.identidade.lerEndpoints(ligacao, tenantId, contactId, {
          soTelefones: true,
          antes: (cliente) => antes(cliente),
        });
        return lidos.telefones;
      } catch (erro) {
        if (erro instanceof ContactoApagadoError || erro instanceof DekDestruidaError) return null;
        throw erro;
      } finally {
        ligacao.release();
      }
    },
  };
}
