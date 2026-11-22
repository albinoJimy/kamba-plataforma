/**
 * A rajada de `tenant.provisioned` do ensaio de memória do KAM-238.
 *
 * Não é um teste: é o programa que `db/ensaio_dono.py` corre num contentor da
 * imagem do `onboarding-web`, na rede da pilha, antes de ligar o publicador.
 * Deixa **N** eventos `tenant.provisioned` no *outbox*, cada um com um caso cujo
 * telefone o consumidor `dono` decifra e resolve, para que a rajada que se mede
 * seja a do caminho que cria dono — e não a de eventos que vão à DLQ.
 *
 * Pelo caminho do `provisionamento.bd.test.ts`: o caso escreve-se como
 * `kamba_app` com o `phone_enc` do escritor, o administrador semeia o que é de
 * outros tickets (o tenant, o KYC, o screening, o aceite, a saga e o canal), e o
 * caso avança pelo `varrerProvisionamentos` como `kamba_batch`. A versão activa
 * da chave de pesquisa do contacto regista-a este programa, com o `kid` que o
 * processo medido recebe: a tabela é global, e sem ela o `resolveContact` do
 * consumidor dava `ChaveDesconhecidaError` em todos os eventos.
 *
 *     KAMBA_DB_* e as senhas     as do `apoio.ts` (base `kamba_gate8`)
 *     KAMBA_ENV                  o ambiente do `EnvKeyProvider`
 *     KAMBA_SECRET_KEK_TELEFONE_DO_CASO, KAMBA_SECRET_PEPPER_CONTACT_HMAC,
 *     KAMBA_SECRET_KEK_CONTACT_DEK    as do processo medido, as mesmas
 *     KAMBA_RAJADA_CASOS         quantos casos (e eventos)
 *
 * Não escreve no `stdout` (o `log-lint`, como no `publicador_runner.ts`): quem o
 * corre conta os eventos pela base e sai pelo código de saída. Os números são
 * fictícios, com 999.
 */

import { randomBytes, randomUUID } from "node:crypto";

import { EnvKeyProvider, Identidade } from "../src/identity/index.ts";
import { Telefone, anelDoTelefone, colunasDoTelefone } from "../src/inscricao/index.ts";
import { PASSOS_ANTES_DO_ES, varrerProvisionamentos } from "../src/provisioning/index.ts";
import { isAmbiente } from "../src/secrets/index.ts";
import { comTenant } from "../src/tenant_guard/index.ts";
import { aceitarVigentes, criarCanal, ligar, poolDe } from "./apoio.ts";

function exigir(nome: string): string {
  const valor = (process.env[nome] ?? "").trim();
  if (valor === "") throw new Error(`${nome} em falta`);
  return valor;
}

const ambiente = exigir("KAMBA_ENV");
if (!isAmbiente(ambiente)) throw new Error("KAMBA_ENV invalido");
const casos = Number(exigir("KAMBA_RAJADA_CASOS"));
if (!Number.isInteger(casos) || casos < 1 || casos > 999_999) throw new Error("KAMBA_RAJADA_CASOS invalido");

const anel = anelDoTelefone([exigir("KAMBA_SECRET_KEK_TELEFONE_DO_CASO"), null]);
// O *pepper* da inscrição só cunha o `phone_hmac` do caso, que o consumidor não lê.
const pepperDaInscricao = randomBytes(32);
const kid = exigir("KAMBA_SECRET_PEPPER_CONTACT_HMAC").split(":", 1)[0] ?? "";

const admin = await ligar("admin");
const app = await ligar("app");
const batch = await ligar("batch");
const identidadeBd = await ligar("identity");
const lote = poolDe("batch", 4);

try {
  const identidade = await Identidade.arrancar({ chaves: new EnvKeyProvider({ ambiente }) });
  await identidade.iniciarRotacao(identidadeBd, kid);

  for (let i = 0; i < casos; i += 1) {
    const caso = randomUUID();
    const tenant = randomUUID();
    // Nove algarismos com 999 à cabeça: a forma nacional, fictícia.
    const telefone = new Telefone(`999${String(i).padStart(6, "0")}`, pepperDaInscricao);
    const colunas = colunasDoTelefone(anel, { tenantId: tenant, onboardingId: caso }, telefone);
    await comTenant(app, tenant, (tx) =>
      tx.query(
        `INSERT INTO platform.onboarding_case
           (id, tenant_id, fase, origem, nome_negocio, categoria_declarada, nif_enc, nif_hmac, phone_enc, phone_hmac)
         VALUES ($1, $2, 'kyc_pendente', 'convite', 'Loja de ensaio', 'alimentar', $3, $4, $5, $6)`,
        [caso, tenant, randomBytes(40), randomBytes(32), colunas.phoneEnc, colunas.phoneHmac],
      ),
    );
    await admin.query("INSERT INTO platform.tenants (id, tipo, nome) VALUES ($1, 'pme', $2)", [
      tenant,
      `Loja de ensaio rajada ${tenant.slice(0, 8)}`,
    ]);
    await admin.query(
      `INSERT INTO platform.kyc_check (onboarding_id, tenant_id, doc_tipo, doc_ref, sha256, resultado, versao_regras)
       VALUES ($1, $2, 'bi', $3, $4, 'k1_ok', '1.0.0')`,
      [caso, tenant, `t/${tenant}/kyc_documento/2026/11/${randomUUID()}`, randomBytes(32)],
    );
    await admin.query(
      `INSERT INTO platform.screening_decision (tenant_id, onboarding_id, sujeito_tipo, sujeito_ref, decisao,
         regras, versao_politica, origem, conteudo_sha256)
       VALUES ($1, $2, 'categoria', 'alimentar', 'permitida', ARRAY['alimentar'], '1.0.0+ensaio', 'regra', $3)`,
      [tenant, caso, randomBytes(32)],
    );
    await aceitarVigentes(admin, tenant);
    await comTenant(batch, tenant, (tx) => tx.query("SELECT platform.advance_case($1, 'aprovar', 'ensaio')", [caso]));
    for (const passo of PASSOS_ANTES_DO_ES) {
      await admin.query(
        `INSERT INTO platform.provisioning_step (onboarding_id, tenant_id, step, status, attempt)
         VALUES ($1, $2, $3, 'concluido', 1)`,
        [caso, tenant, passo],
      );
    }
    await criarCanal(admin, tenant);
  }

  // O caso avança uma fase por volta; as voltas repetem-se até haver N eventos.
  for (let volta = 0; volta < 10; volta += 1) {
    await varrerProvisionamentos({ lote, limite: casos });
    const { rows } = await admin.query<{ n: string }>(
      "SELECT count(*)::text AS n FROM platform.events_outbox WHERE tipo = 'tenant.provisioned'",
    );
    if (Number(rows[0]?.n ?? "0") >= casos) break;
  }
} finally {
  await Promise.allSettled([admin.end(), app.end(), batch.end(), identidadeBd.end(), lote.end()]);
}
