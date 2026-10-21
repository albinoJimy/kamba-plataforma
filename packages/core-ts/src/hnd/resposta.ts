/**
 * A resposta humana que sai ao cliente pelo Outbound (KAM-019, critério 6).
 *
 * «A resposta humana é enviada ao cliente pelo Outbound (janela, template se
 * fechada, custo registado); com janela fechada o painel recebe aviso e
 * proposta de template *utility*.»
 *
 * ## Porque é que isto é um ficheiro e não uma linha no provedor
 *
 * Porque é a **costura entre dois módulos** que não se conhecem, e o sítio onde
 * ela vive decide o que cada um sabe do outro. O `provedor.ts` sabe de
 * passagens e de *callbacks*; o `outbound/adapter.ts` sabe de janelas, tarifas
 * e tectos. Nenhum dos dois precisa de saber do outro, e meter o `Saida` dentro
 * do `Handoff` tornava o HND dependente do módulo de saída para abrir uma
 * passagem — que é a operação que nada tem a ver com enviar.
 *
 * ## A resposta humana **não** passa pelo guarda
 *
 * `doBot: false`, e é o campo que o KAM-015 criou precisamente para isto: «um
 * envio do dono ou de um humano no Chatwoot **não** passa pelo guarda»
 * (`outbound/contrato.ts`). O `PreSendGuard` protege uma conversa em modo dono
 * ou humano de ser interrompida pelo **assistente**; recusar a resposta da
 * pessoa que o modo humano existe para servir era o contrário do que ele
 * protege.
 *
 * ## A janela fechada não é um erro, é uma decisão do painel
 *
 * O `ChannelAdapter` devolve `WINDOW_CLOSED` **sem chamada HTTP** e quem chama
 * decide (`docs/tecnica/01` §8.2, regra 3). Aqui a decisão é a do critério:
 * avisa-se o painel e **propõe-se** um template `utility`, em vez de se enviar
 * um por iniciativa própria. A razão é custo e é consentimento: um template
 * fora da janela é pago (`E1` §1) e é a PME que decide gastá-lo.
 */

import type { Logger } from "../logger/index.ts";
import type { Resultado, Saida } from "../outbound/index.ts";
import { WINDOW_CLOSED } from "../outbound/index.ts";
import type { HumanEvent } from "./contrato.ts";

/** A passagem a que a resposta pertence, com o que o envio precisa. */
export interface DestinoDaResposta {
  readonly tenantId: string;
  readonly channelId: string;
  readonly contactId: string;
  readonly conversationId: string;
  readonly phoneNumberId: string;
}

/** O que o painel recebe quando a janela está fechada. */
export interface AvisoDeJanelaFechada {
  readonly tenantId: string;
  readonly conversationId: string;
  readonly handoffId: string;
  /** O texto que o agente escreveu e que **não** saiu. */
  readonly textoNaoEnviado: string;
  /** O template que se propõe, da lista do Piloto. */
  readonly templateProposto: string;
}

/** Como se avisa o painel. Porta: quem o liga é o KAM-031. */
export type AvisarPainel = (aviso: AvisoDeJanelaFechada) => Promise<void>;

/**
 * O template que se propõe quando a janela fechou.
 *
 * É o do conjunto padrão do Piloto que serve este caso — «um humano vai
 * responder» —, e o conjunto é submetido por *tenant* no onboarding (KAM-091).
 * **Propõe-se e não se envia**: um template fora da janela é pago (`E1` §1) e é
 * a PME que decide gastá-lo. É *proposta*: o nome exacto do conjunto padrão
 * fixa-se no KAM-091.
 */
export const TEMPLATE_PROPOSTO = "passagem_a_humano";

/** O desfecho de uma tentativa de resposta humana. */
export type DesfechoDaResposta =
  | { readonly enviada: true; readonly wamid: string | null }
  | { readonly enviada: false; readonly motivo: string };

/**
 * Manda a resposta do agente ao cliente, pelo Outbound.
 *
 * A chave de idempotência deriva do **identificador da mensagem no provedor**,
 * e não do texto: dois *callbacks* do mesmo `message_created` — que o provedor
 * reenvia — dão a mesma chave e o Outbound não envia duas vezes. Derivá-la do
 * texto fazia duas mensagens iguais do agente («ok») serem uma só, que é pior
 * do que o problema que resolvia.
 *
 * Sem `mensagemId`, **não se envia**: uma chave inventada aqui tirava ao
 * Outbound a única coisa que o torna idempotente, e um reenvio do provedor
 * passava a ser uma segunda mensagem ao cliente.
 */
export async function responderAoCliente(
  acontecimento: HumanEvent,
  destino: DestinoDaResposta,
  saida: Saida,
  avisarPainel: AvisarPainel,
  log?: Logger,
): Promise<DesfechoDaResposta> {
  if (acontecimento.acontecimento !== "mensagem_de_agente") {
    return { enviada: false, motivo: "NAO_E_MENSAGEM" };
  }
  const texto = acontecimento.texto;
  if (texto === null || texto.length === 0) {
    return { enviada: false, motivo: "SEM_TEXTO" };
  }
  if (acontecimento.mensagemId === null) {
    // Ver a nota da função: sem identificador do provedor não há chave de
    // idempotência possível, e enviar sem ela é aceitar reenviar.
    log?.warn({ outcome: "resposta_sem_id_do_provedor", tenant_id: destino.tenantId });
    return { enviada: false, motivo: "SEM_ID_DA_MENSAGEM" };
  }

  const resultado: Resultado = await saida.enviar({
    tenantId: destino.tenantId,
    channelId: destino.channelId,
    contactId: destino.contactId,
    conversationId: destino.conversationId,
    phoneNumberId: destino.phoneNumberId,
    // Derivada do identificador da mensagem no provedor. O prefixo diz de onde
    // vem, para que uma chave de handoff nunca colida com uma de turno do bot.
    idempotencyKey: `hnd:${acontecimento.handoffId}:${acontecimento.mensagemId}`,
    corpo: { tipo: "texto", texto },
    // **Não passa pelo guarda.** Ver a nota do módulo.
    doBot: false,
  });

  if (resultado.ok) {
    log?.info({ outcome: "resposta_humana_enviada", tenant_id: destino.tenantId });
    return { enviada: true, wamid: resultado.wamid };
  }

  if (resultado.motivo === WINDOW_CLOSED) {
    // A janela fechou enquanto o agente escrevia. **Avisa-se e propõe-se**, em
    // vez de se enviar um template por iniciativa propria: e pago, e a decisao
    // e da PME.
    await avisarPainel({
      tenantId: destino.tenantId,
      conversationId: destino.conversationId,
      handoffId: acontecimento.handoffId,
      textoNaoEnviado: texto,
      templateProposto: TEMPLATE_PROPOSTO,
    });
    log?.info({ outcome: "resposta_humana_janela_fechada", tenant_id: destino.tenantId });
    return { enviada: false, motivo: WINDOW_CLOSED };
  }

  // Qualquer outra recusa do Outbound é dele e vai no `outcome`; o `motivo`
  // devolve-se a quem chamou para que o painel possa dizer porque é que a
  // resposta não saiu.
  log?.warn({
    outcome: `resposta_humana_recusada_${resultado.motivo.toLowerCase()}`,
    tenant_id: destino.tenantId,
  });
  return { enviada: false, motivo: resultado.motivo };
}
