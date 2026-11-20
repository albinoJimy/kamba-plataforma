/**
 * O observador de produção do teste ponta a ponta (KAM-202, critério 1).
 *
 * Lê os quatro factos do `SmokeProbe` das tabelas que já existem, e de um sinal
 * novo que o `worker-canal` emite: o instante `conversations.teste_recebido_at`,
 * que o CHR grava quando a mensagem que chegou é a palavra do teste
 * (`EventoDeEntrada.eTeste`). **Nenhum texto do dono e nenhum telefone se
 * guardam**: o sinal é um instante, e a conversa é a que o CHR já tinha.
 *
 * ```text
 * inbound        a conversa do tenant do caso com teste_recebido_at na janela,
 *                se for **uma so**; e e ela que se marca is_test
 * resposta       uma agent_replies dessa conversa, depois do teste e ate ao
 *                fim da janela, cujo texto nomeia o assistente e a loja
 * entregue       um outbound_messages dessa conversa com delivered_at nesse
 *                intervalo
 * consentimento  um consent_event aceite do contacto dessa conversa, ate ao fim
 *                da janela
 * ```
 *
 * ## Duas conversas com o «teste» na janela: nenhuma
 *
 * O sinal não sabe quem é o dono: qualquer contacto que escreva a palavra o dá.
 * Se mais de uma conversa do tenant o tiver na janela, o observador não escolhe —
 * não há inbound, o teste falha com `sem_inbound` e **nenhuma conversa se marca**
 * `is_test`. Escolher a mais recente marcava a conversa de um cliente que escreveu
 * «teste» no mesmo minuto, e ela saía para sempre das queixas do `risco_ts`, do
 * churn e da golden (achado 6 da revisão adversarial). O dono repete.
 *
 * ## O consentimento pode ser de antes
 *
 * O aviso de 1.º contacto sai uma vez por contacto: numa segunda tentativa do mesmo
 * telefone não há `consent_event` novo. Conta o do contacto registado até ao fim da
 * janela (achado 11).
 *
 * ## Falha fechado, e é o que se quer
 *
 * Em produção, hoje, dois dos factos não têm quem os escreva: nenhum serviço
 * chama o `Saida.ingerir`, pelo que os `statuses` não escrevem o `delivered_at`;
 * e o `ConsentGate` não está montado, pelo que nada grava o `consent_event` do
 * aviso de 1.º contacto. O observador não os inventa: o teste dá `sem_entrega`
 * ou `sem_consentimento` até eles se ligarem, e nenhuma loja fica activa sem eles
 * (decisão do fundador, 2026-11-20, bloco do KAM-202). E a apresentação do
 * vendedor não nomeia a loja enquanto a persona não tiver o nome dela
 * (`registry/vendedor.yaml`, a frase cai para «desta loja»): até lá, a resposta
 * não identifica a loja, e o teste dá `sem_resposta`.
 *
 * ## Pela ligação da aplicação
 *
 * A `agent_replies` só a lê o `kamba_app` (revisão `0073`), e as outras quatro
 * tabelas também. Quem monta dá um cliente da aplicação com o `app.tenant_id` do
 * caso; o `tenant_id` do caso vai também em cada predicado, que é a barreira que
 * não depende do papel.
 *
 * ## Quem é o assistente
 *
 * A persona do vendedor não tem nome próprio: identifica-se como «assistente
 * automatico» (`registry/vendedor.yaml`, `apresentacao`). É essa a expressão que
 * a resposta tem de ter, e o ensaio confere-a contra o registo, para que mudar a
 * frase de um lado sem o outro fique vermelho. A loja é o `tenants.nome`.
 */

import type { ClienteSql } from "../screening/sql.ts";
import type { FactosDoTeste, ObservadorDoTeste } from "./contrato.ts";
import { identificaAssistenteELoja } from "./smoke.ts";

/** Como a persona do vendedor se identifica (`registry/vendedor.yaml`, `apresentacao`). */
export const ASSISTENTE_DO_TESTE = "assistente automatico";

/**
 * Os factos de uma janela, numa consulta. Zero linhas quando não houve «teste»
 * na janela. `$1` o caso, `$2` e `$3` a janela.
 */
export const SQL_FACTOS_DO_TESTE = `
WITH caso AS (
  SELECT c.tenant_id FROM platform.onboarding_case c WHERE c.id = $1
), sinais AS (
  SELECT v.tenant_id, v.id, v.contact_id, v.teste_recebido_at
    FROM platform.conversations v JOIN caso ON v.tenant_id = caso.tenant_id
   WHERE v.teste_recebido_at >= $2 AND v.teste_recebido_at <= $3
), conversa AS (
  SELECT s.* FROM sinais s WHERE (SELECT count(*) FROM sinais) = 1
)
SELECT k.id::text AS conversation_id,
       (SELECT t.nome FROM platform.tenants t WHERE t.id = k.tenant_id) AS loja,
       ARRAY(SELECT r.texto FROM platform.agent_replies r
              WHERE r.tenant_id = k.tenant_id AND r.conversation_id = k.id
                AND r.criado_at >= k.teste_recebido_at AND r.criado_at <= $3
              ORDER BY r.criado_at) AS respostas,
       EXISTS (SELECT 1 FROM platform.outbound_messages o
                WHERE o.tenant_id = k.tenant_id AND o.conversation_id = k.id
                  AND o.delivered_at >= k.teste_recebido_at AND o.delivered_at <= $3) AS entregue,
       EXISTS (SELECT 1 FROM platform.consent_event e
                WHERE e.tenant_id = k.tenant_id AND e.contact_id = k.contact_id AND e.accepted
                  AND e.registado_em <= $3) AS consentimento
  FROM conversa k`;

export class ObservadorSql implements ObservadorDoTeste {
  readonly #cliente: ClienteSql;
  readonly #assistente: string;

  constructor(cliente: ClienteSql, assistente: string = ASSISTENTE_DO_TESTE) {
    this.#cliente = cliente;
    this.#assistente = assistente;
  }

  async factos(onboardingId: string, desde: Date, ate: Date): Promise<FactosDoTeste> {
    const { rows } = await this.#cliente.query<{
      conversation_id: string;
      loja: string | null;
      respostas: readonly string[] | null;
      entregue: boolean;
      consentimento: boolean;
    }>(SQL_FACTOS_DO_TESTE, [onboardingId, desde, ate]);
    const l = rows[0];
    if (l === undefined) {
      return { inbound: false, resposta: false, entregue: false, consentimento: false, conversationId: null };
    }
    const loja = l.loja ?? "";
    // O texto compara-se aqui e não sai: nem para o registo, nem para o resultado.
    const resposta = (l.respostas ?? []).some((texto) => identificaAssistenteELoja(texto, this.#assistente, loja));
    return {
      inbound: true,
      resposta,
      entregue: l.entregue === true,
      consentimento: l.consentimento === true,
      conversationId: l.conversation_id,
    };
  }
}
