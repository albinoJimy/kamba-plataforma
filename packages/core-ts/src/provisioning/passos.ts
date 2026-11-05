/**
 * Os oito passos da saga: chave natural, *ensure* e compensação (KAM-091).
 *
 * Cada passo é um objecto com quatro coisas, e as quatro são dados e não
 * código espalhado: o nome (que é o `provisioning_step.step`), a chave natural
 * de idempotência, o *ensure* e a lista **declarada** de acções de compensação.
 *
 * ## A procura-antes-de-criar está aqui, e é de propósito
 *
 * O critério 4 — «*crash* entre criar o recurso externo e gravar o `markDone`
 * não duplica na repetição» — só se prova se a procura estiver no nosso código.
 * As portas externas são inventários de `procurar`/`criar` (ver a nota do
 * `contrato.ts`), e é **esta** camada que os combina. Apagar um `procurar`
 * daqui faz o contador de criações do inventário ir a 2, e há um ensaio a
 * afirmar que é 1 — é o `tests/provisioning.mutacao.test.ts`.
 *
 * A única excepção é o passo 4: o Chatwoot entra por
 * `HandoffProvider.ensureAccount` **como caixa preta**, porque é o que o
 * *handoff* deste ticket manda, e essa porta já procura antes de criar
 * (`src/hnd/provedor.ts:210-211`) com *suite* própria.
 *
 * ## A compensação declara, não executa
 *
 * Nenhum `compensar` abaixo chama uma porta destrutiva directamente: devolve a
 * lista de `AccaoDeCompensacao` e o `saga.ts` passa-a pelo guarda do
 * `compensacao.ts` antes de a executar. É o que torna o critério 7
 * («nunca apaga o WABA nem o número») uma propriedade medida sobre dados em vez
 * de uma leitura de código.
 */

import {
  ESPERA_DO_PASSO,
  ETIQUETA_DA_SAGA,
  AguardaEntradaError,
  type AccaoDeCompensacao,
  type CanalDoCliente,
  type Caso,
  type ChaveDeLlm,
  type ClienteSql,
  type Entitlements,
  type InboxDeAtendimento,
  type Passo,
  type RegistoDeCanalDeComercio,
  type RegistoDoCaso,
  type TesteDeCanal,
} from "./contrato.ts";
import type { HandoffProvider } from "../hnd/contrato.ts";

/**
 * Garante a linha de `tenants` sem a reescrever se já existir.
 *
 * `ON CONFLICT DO NOTHING` seguido de um `SELECT` no `WITH`: o `RETURNING`
 * sozinho não devolve linha no conflito, e o passo precisa do `id` nas duas
 * passagens — a primeira e a repetição. O `tenant_id` vem **pré-alocado** no
 * caso (critério 2, passo 1) e não se gera aqui: gerá-lo no `INSERT` fazia a
 * segunda passagem criar um tenant novo, que é exactamente o que o critério 1
 * proíbe.
 */
export const SQL_GARANTIR_TENANT = `
  WITH novo AS (
    INSERT INTO platform.tenants (id, tipo, nome, plano, estado)
    VALUES ($1, 'pme', $2, $3, 'onboarding')
    ON CONFLICT (id) DO NOTHING
    RETURNING id
  )
  SELECT id FROM novo
  UNION ALL
  SELECT id FROM platform.tenants WHERE id = $1
  LIMIT 1
`;

/** Guarda o `external_id` de um passo na coluna de `tenants` que lhe corresponde. */
export const SQL_GUARDAR_CHAVE_LLM = `
  UPDATE platform.tenants SET litellm_key_id = $2 WHERE id = $1
`;
export const SQL_GUARDAR_CANAL_COMERCIO = `
  UPDATE platform.tenants SET medusa_sales_channel_id = $2 WHERE id = $1
`;
export const SQL_GUARDAR_CONTA_ATENDIMENTO = `
  UPDATE platform.tenants SET chatwoot_account_id = $2 WHERE id = $1
`;

/**
 * Grava a rota do CHR: `tenant_channels`, `phone_number_id` único.
 *
 * `ON CONFLICT (phone_number_id)` e não `(tenant_id, phone_number_id)`: o
 * critério 2 diz «`phone_number_id` único» sem qualificar por tenant, e com a
 * chave composta o mesmo número podia entrar por dois tenants — que é a
 * confusão de canais que o KAM-016 já pagou uma vez.
 */
export const SQL_GARANTIR_ROTA = `
  INSERT INTO platform.tenant_channels (tenant_id, phone_number_id, waba_id, vertical, estado)
  VALUES ($1, $2, $3, $4, 'onboarding')
  ON CONFLICT (phone_number_id) DO NOTHING
`;

/** O que um passo é. */
export interface DefinicaoDePasso {
  readonly nome: Passo;
  /** A chave natural de idempotência, derivada do caso. Só para registo e ensaio. */
  chaveDe(caso: Caso): string;
  /**
   * Cria **ou encontra** o recurso. Devolve o `external_id`, ou `null` quando o
   * passo não produz referência externa (os passos 1, 5 e 8).
   *
   * @throws {AguardaEntradaError} nos passos de espera, enquanto a entrada não chegar.
   */
  ensure(caso: Caso): Promise<string | null>;
  /** O que desfazer, **declarado**. Ver a nota do módulo. */
  compensar(caso: Caso, externalId: string | null): Promise<readonly AccaoDeCompensacao[]>;
}

/** As portas de que os oito passos precisam. */
export interface Dependencias {
  readonly sql: ClienteSql;
  readonly caso: RegistoDoCaso;
  readonly chaveDeLlm: ChaveDeLlm;
  readonly comercio: RegistoDeCanalDeComercio;
  readonly handoff: HandoffProvider;
  readonly entitlements: Entitlements;
  readonly canalDoCliente: CanalDoCliente;
  readonly inbox: InboxDeAtendimento;
  readonly teste: TesteDeCanal;
  /**
   * Apaga a conta de atendimento criada pela nossa chave da Platform API.
   *
   * **Não está no `HandoffProvider`, e isso é uma medição.** A porta do KAM-019
   * tem seis operações (`ensureAccount`, `mirrorMessage`, `openHandoff`,
   * `setBotMuted`, `onHumanEvent`, `close`) e **nenhuma apaga uma conta** — o
   * `docs/tecnica/01` §11.1 fixa-lhe esses seis nomes. A compensação do passo 4
   * precisa dessa operação («apagar a conta criada pela mesma chave da Platform
   * API», `docs/tecnica/10` §5.2), pelo que ela entra aqui como porta própria
   * em vez de se acrescentar um sétimo método a um contrato que outro ticket
   * fixou. Credor da implementação: **KAM-019** (e a criação de *inbox* pela
   * Platform API continua **NÃO VERIFICADA**, E4 §2.2).
   */
  apagarContaDeAtendimento(accountId: string): Promise<void>;
  /** O orçamento de IA do plano. Vem de fora: é a `FRACCAO_DO_ORCAMENTO` do `infra/llm/chaves.py`. */
  orcamentoDoPlano(plano: string): number;
  /** O `waba_id` do canal em onboarding. `null` enquanto o ES não tiver corrido. */
  wabaDoTenant(tenantId: string): Promise<string | null>;
}

/** O alias da chave virtual do tenant. A mesma regra do `infra/llm/chaves.py:96`. */
export function aliasDoTenant(tenantId: string): string {
  return `tenant-${tenantId}`;
}

/**
 * Monta os oito passos, pela ordem.
 *
 * Devolve um `ReadonlyMap` e **não** um array: o `saga.ts` percorre o `PASSOS`
 * do contrato, que é a única lista com a ordem, e procura aqui a definição. Com
 * duas listas ordenadas, a ordem da compensação e a ordem da execução podiam
 * divergir sem que nada o dissesse.
 */
export function montarPassos(d: Dependencias): ReadonlyMap<Passo, DefinicaoDePasso> {
  const passos: DefinicaoDePasso[] = [
    // ------------------------------------------------- 1. tenant e caso
    {
      nome: "tenant_e_caso",
      chaveDe: (caso) => caso.onboardingId,
      async ensure(caso) {
        await d.sql.query(SQL_GARANTIR_TENANT, [caso.tenantId, caso.vertical, caso.plano]);
        return null;
      },
      // **Marca `cancelado`; não apaga histórico** (`docs/tecnica/10` §5.2,
      // linha 1). O `tenants.estado` não tem `cancelado` — o canon fixa-lhe
      // cinco valores e nenhum é esse —, pelo que quem o marca é o registo do
      // caso. E o `apagar` não está aqui de propósito: um tenant apagado levava
      // consigo o `audit_log` do onboarding, e o critério 7 do KAM-098
      // (off-boarding) é que decide o que se purga e quando.
      compensar: async (caso) => [
        { tipo: "marcar_cancelado", recurso: "tenant", ref: caso.onboardingId },
      ],
    },

    // ------------------------------------------------- 2. chave virtual LiteLLM
    {
      nome: "chave_llm",
      chaveDe: (caso) => aliasDoTenant(caso.tenantId),
      async ensure(caso) {
        const alias = aliasDoTenant(caso.tenantId);
        const orcamento = d.orcamentoDoPlano(caso.plano);
        // **A procura é esta linha, e é o critério 4.** Sem ela, a repetição
        // depois de um `crash` na janela entre o `criar` e o `markDone` emitia
        // uma segunda chave com o mesmo alias.
        const existente = await d.chaveDeLlm.procurar({ alias, orcamento });
        const chave = existente ?? (await d.chaveDeLlm.criar({ alias, orcamento }));
        // **Guarda-se o `litellm_key_id`, nunca a chave** (detalhes técnicos do
        // ticket, e a DoD sobre segredos). O `external_id` que vai para o
        // `provisioning_step` é o mesmo identificador por referência.
        await d.sql.query(SQL_GUARDAR_CHAVE_LLM, [caso.tenantId, chave.id]);
        return chave.id;
      },
      compensar: async (_caso, externalId) =>
        externalId === null ? [] : [{ tipo: "revogar", recurso: "chave_llm", ref: externalId }],
    },

    // ------------------------------------------------- 3. canal e merchant
    {
      nome: "canal_comercio",
      chaveDe: (caso) => caso.tenantId,
      async ensure(caso) {
        const existente = await d.comercio.procurar({ tenantId: caso.tenantId });
        const canal = existente ?? (await d.comercio.criar({ tenantId: caso.tenantId }));
        await d.sql.query(SQL_GUARDAR_CANAL_COMERCIO, [caso.tenantId, canal.id]);
        return canal.id;
      },
      // **Arquiva; só apaga se vazio** (critério 7). As duas acções vão
      // declaradas e por esta ordem: arquivar primeiro torna o canal invisível
      // ao catálogo mesmo que o `apagarSeVazio` não possa correr.
      compensar: async (_caso, externalId) =>
        externalId === null
          ? []
          : [
              { tipo: "arquivar", recurso: "canal_comercio", ref: externalId },
              { tipo: "apagar", recurso: "canal_comercio", ref: externalId },
            ],
    },

    // ------------------------------------------------- 4. conta de atendimento
    {
      nome: "conta_atendimento",
      chaveDe: (caso) => caso.tenantId,
      async ensure(caso) {
        // **Caixa preta, e é o que o handoff manda.** O `ensureAccount` do
        // KAM-019 já procura antes de criar e trata a corrida perdida; a
        // garantia é dele e tem *suite* própria (`tests/hnd.provedor.test.ts`).
        // O que aqui se mede é que é chamado **uma vez por passagem**.
        const conta = await d.handoff.ensureAccount(caso.tenantId);
        await d.sql.query(SQL_GUARDAR_CONTA_ATENDIMENTO, [caso.tenantId, conta.accountId]);
        return String(conta.accountId);
      },
      // A conta do Chatwoot é **nossa** (criada pela nossa chave da Platform
      // API), e por isso `apagar` é legítimo aqui — ao contrário do WABA.
      compensar: async (_caso, externalId) =>
        externalId === null
          ? []
          : [{ tipo: "apagar", recurso: "conta_atendimento", ref: externalId }],
    },

    // ------------------------------------------------- 5. entitlements
    {
      nome: "entitlements",
      chaveDe: (caso) => `${caso.tenantId}:modulo`,
      async ensure(caso) {
        // Idempotente por `(tenant_id, modulo)`: é a porta que o garante, com
        // um `ON CONFLICT DO UPDATE`. Repetir deixa os mesmos limites.
        await d.entitlements.garantir(caso.tenantId, caso.plano);
        return null;
      },
      compensar: async (caso) => [
        { tipo: "desactivar", recurso: "entitlement", ref: caso.tenantId },
      ],
    },

    // ------------------------------------------------- 6. espera do ES v4
    {
      nome: "espera_es",
      chaveDe: (caso) => caso.tenantId,
      async ensure(caso) {
        // **Isto é uma espera, não uma falha** (critério 6). O dono tem de se
        // autenticar na Meta e confirmar na app (E1); enquanto não o fizer, o
        // passo fica `aguarda_es` e a saga **não** gasta tentativa nenhuma — se
        // gastasse, três noites sem o dono mexer escalavam o caso para
        // operações por uma coisa que ninguém podia ter feito.
        const numero = await d.canalDoCliente.numeroDoTenant(caso.tenantId);
        if (numero === null) {
          throw new AguardaEntradaError("espera_es", ESPERA_DO_PASSO.espera_es ?? "aguarda_es");
        }
        const waba = await d.wabaDoTenant(caso.tenantId);
        if (waba === null) {
          throw new AguardaEntradaError("espera_es", ESPERA_DO_PASSO.espera_es ?? "aguarda_es");
        }
        await d.canalDoCliente.subscreverWebhooks(waba);
        return numero;
      },
      // **As duas acções do critério 7, e mais nenhuma.** Cancelar a subscrição
      // (nossa) e remover a rota (nossa). O WABA e o número são do cliente e
      // não se apagam — o `compensacao.ts` recusa-o em execução, e não é só
      // esta lista que o impede.
      async compensar(caso, externalId) {
        if (externalId === null) return [];
        const waba = await d.wabaDoTenant(caso.tenantId);
        return [
          ...(waba === null
            ? []
            : ([{ tipo: "cancelar_subscricao", recurso: "waba", ref: waba }] as const)),
          { tipo: "remover_rota", recurso: "phone_number", ref: externalId },
        ];
      },
    },

    // ------------------------------------------------- 7. inbox e rota do CHR
    {
      nome: "inbox_e_rota",
      chaveDe: (caso) => caso.tenantId,
      async ensure(caso) {
        const numero = await d.canalDoCliente.numeroDoTenant(caso.tenantId);
        if (numero === null) {
          throw new AguardaEntradaError(
            "inbox_e_rota",
            ESPERA_DO_PASSO.inbox_e_rota ?? "aguarda_catalogo",
          );
        }
        const chave = { tenantId: caso.tenantId, phoneNumberId: numero };
        const existente = await d.inbox.procurar(chave);
        const inbox = existente ?? (await d.inbox.criar(chave));
        const waba = await d.wabaDoTenant(caso.tenantId);
        await d.sql.query(SQL_GARANTIR_ROTA, [caso.tenantId, numero, waba, caso.vertical]);
        return inbox.id;
      },
      // A *inbox* é nossa (desliga-se) e a rota é nossa (remove-se). O número
      // que a rota aponta continua do cliente, e é por isso que a acção é
      // `remover_rota` e não `apagar`.
      async compensar(caso, externalId) {
        const numero = await d.canalDoCliente.numeroDoTenant(caso.tenantId);
        return [
          ...(externalId === null
            ? []
            : ([{ tipo: "desactivar", recurso: "inbox", ref: externalId }] as const)),
          ...(numero === null
            ? []
            : ([{ tipo: "remover_rota", recurso: "rota_chr", ref: numero }] as const)),
        ];
      },
    },

    // ------------------------------------------------- 8. teste ponta a ponta
    {
      nome: "teste_ponta_a_ponta",
      chaveDe: (caso) => caso.onboardingId,
      async ensure(caso) {
        const resultado = await d.teste.resultado(caso.onboardingId);
        // `null` é espera (o teste ainda não correu); `false` é **falha** e
        // gasta tentativa. A distinção é a do critério 6: «os passos de ES e de
        // teste são esperas externas, não falhas» — mas um teste que correu e
        // deu errado é uma falha, e tratá-lo como espera deixava o caso
        // pendurado para sempre sem ninguém saber porquê.
        if (resultado === null) {
          throw new AguardaEntradaError(
            "teste_ponta_a_ponta",
            ESPERA_DO_PASSO.teste_ponta_a_ponta ?? "aguarda_teste",
          );
        }
        if (!resultado) throw new Error("teste_ponta_a_ponta_falhou");
        return caso.onboardingId;
      },
      // Sem compensação: o `docs/tecnica/10` §5.2 deixa a célula vazia. Um teste
      // que correu não deixa recurso para desfazer.
      compensar: async () => [],
    },
  ];

  return new Map(passos.map((p) => [p.nome, p]));
}

/** A etiqueta com que a saga marca tudo o que cria. Reexportada para quem monta as portas. */
export { ETIQUETA_DA_SAGA };
