/**
 * Configuracao do Medusa do spike KAM-041.
 *
 * Minimo deliberado, e cada ausencia tem razao:
 *
 * - **Nenhuma `featureFlags`.** O AC-7 exige zero material Enterprise activo. As
 *   duas flags EE (`rbac` -> `MEDUSA_FF_RBAC`, `rbac_filter_fields` ->
 *   `MEDUSA_FF_RBAC_FILTER_FIELDS`) tem `default_val: false`, pelo que nao estar
 *   aqui e nao estar ligada. `spikes/medusa-d3/ee.py` verifica-o e sai 1 se
 *   alguma aparecer ligada. Nomear as flags neste comentario nao as liga — o
 *   verificador salta linhas de comentario, de proposito, para que o controlo
 *   possa ser documentado.
 * - **Nenhum `redisUrl`.** Os quatro subsistemas que o pediriam (cache, event
 *   bus, locking, workflow engine) tem provider in-memory por omissao. O bus
 *   canonico da KAMBA e o EVT (ADR-009), nao o do Medusa.
 *
 *   **E isto nao e inocente, e e metade do resultado deste spike.** O provider
 *   de locking por omissao e in-memory, e a documentacao oficial diz que «is
 *   only intended for use in a single-instance environment». A reserva atomica
 *   do Medusa depende desse lock (ver `docs/spikes/KAM-041-medusa.md` §4): com
 *   o in-memory, um unico processo serializa e mais do que um processo **nao**.
 *   O harness mede os dois caminhos de proposito.
 * - **`admin: { disable: true }`.** O admin nao e servido. O `docs/tecnica/08`
 *   §3.5 quer o admin «so na VPN, so equipa»; num spike a forma mais barata de
 *   o garantir e nao o servir, e o AC-2 mede que nada o alcanca.
 *
 * O schema do Medusa fica em `public`; o da plataforma em `platform`. Nao se
 * cruzam, e e por isso que o §5.5 pode dizer que a RLS nao cobre o schema do
 * Medusa: sao dois esquemas na mesma base.
 */
import { defineConfig, loadEnv } from "@medusajs/framework/utils";

loadEnv(process.env.NODE_ENV || "development", process.cwd());

module.exports = defineConfig({
  projectConfig: {
    databaseUrl: process.env.DATABASE_URL,
    http: {
      storeCors: process.env.STORE_CORS!,
      adminCors: process.env.ADMIN_CORS!,
      authCors: process.env.AUTH_CORS!,
      jwtSecret: process.env.JWT_SECRET || "spike-sem-valor",
      cookieSecret: process.env.COOKIE_SECRET || "spike-sem-valor",
    },
  },
  admin: {
    disable: true,
  },
  modules: [
    {
      resolve: "./src/modules/merchant",
    },
  ],
});
