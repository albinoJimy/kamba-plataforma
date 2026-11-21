/**
 * O destinatário de produção da resposta do AGR (KAM-227, critério 2).
 *
 * O `Saida` do KAM-015 pede o destinatário por uma porta (`ObterDestinatario`),
 * e até ao KAM-227 ela só tinha implementação nos ensaios. Esta é a de produção:
 * os endpoints do contacto pelo `lerEndpoints` do KAM-008, numa ligação
 * **`kamba_identity`** — o único papel de serviço com `SELECT` na
 * `contact_endpoints` e na `contact_deks` (revisão `0003`). O `kamba_app` do
 * consumo não os vê, e não deve.
 *
 * ## O BSUID quando existe, e o telefone só sem ele
 *
 * É a ordem do critério 9 e do DoD «Privacidade» do KAM-015, a mesma do
 * `corpoDaMeta` do `outbound/cliente.ts`: com BSUID, o telefone nem se escolhe.
 * Sem BSUID, vale um telefone guardado **para contactar o cliente sobre o pedido
 * dele** (`finalidade = 'contacto_pedido'`) **e ainda dentro do prazo**
 * (`expira_at`). Um telefone guardado para o pagamento expresso ou para a
 * entrega não se usa para responder: a finalidade é a razão por que se guardou,
 * e responder no WhatsApp é a do `contacto_pedido`, se de alguma for — leitura
 * deste ticket, *(a confirmar por parecer)*. Um telefone fora do prazo é um dado
 * que já não se devia ter, e também não se usa.
 *
 * **O que isto não muda:** o CHR resolve o contacto com o telefone do *webhook*
 * mas **sem** `guardarTelefone` (`chr/chr.ts`), pelo que do telefone de uma
 * mensagem recebida fica só o HMAC, que reconhece o número e não o lê. Um
 * contacto que escreveu sem BSUID não tem, hoje, telefone legível — e a resposta
 * sai `NO_RECIPIENT`. Guardar o telefone do *inbound* para responder é uma
 * finalidade nova (`contact_endpoints.finalidade`), e não é deste ticket.
 *
 * ## O sítio onde o telefone sai em claro, e fica dito
 *
 * É o `escolherDestinatario`, e só ele: o `lerEndpoints` decifra em memória
 * (`docs/tecnica/01` §6.3, ponto 5), e o telefone vai daqui para o
 * `Destinatario` do Outbound, que o põe no `to` do corpo da Meta e em mais lado
 * nenhum. **Não é um `revelar()`**: o tipo do `Destinatario` do KAM-015 é uma
 * cadeia, e o `lerEndpoints` já a devolve decifrada. A conta dos sítios de
 * chamada do `revelar()` está no `inscricao/identificadores.ts`, e este fica
 * escrito lá como o que é.
 *
 * ## Um contacto apagado não tem destinatário
 *
 * `ContactoApagadoError` e `DekDestruidaError` são o apagamento do KAM-008: o
 * endereço deixou de existir de propósito, e a resposta não sai
 * (`NO_RECIPIENT`). Qualquer outro erro — a base de identidade em baixo — sobe,
 * e o efeito trata-o pela escada do consumo.
 */

import {
  ContactoApagadoError,
  DekDestruidaError,
  type ClienteDeIdentidade,
  type EndpointsDoContacto,
  type Finalidade,
} from "../identity/index.ts";
import type { Destinatario, ObterDestinatario } from "../outbound/contrato.ts";

/** A finalidade do telefone com que se responde. Ver a nota do módulo. */
export const FINALIDADE_DA_RESPOSTA: Finalidade = "contacto_pedido";

/** Sem endereço: o `Saida` recusa com `NO_RECIPIENT`. */
export const SEM_DESTINATARIO: Destinatario = Object.freeze({ bsuid: null, telefone: null });

/** O que o destinatário pede ao módulo de identidade: só a leitura dos endpoints. */
export interface LeitorDeEndpoints {
  lerEndpoints(
    cliente: ClienteDeIdentidade,
    tenantId: string,
    contactId: string,
  ): Promise<EndpointsDoContacto>;
}

export interface OpcoesDoDestinatario {
  readonly identidade: LeitorDeEndpoints;
  /** Toma uma ligação `kamba_identity` para esta leitura. */
  readonly tomar: () => Promise<ClienteDeIdentidade>;
  /** Devolve-a. Com `erro`, a ligação falhou e não deve voltar a servir. */
  readonly devolver: (ligacao: ClienteDeIdentidade, erro?: unknown) => Promise<void> | void;
  readonly agora?: () => Date;
}

/**
 * O endereço de um contacto: o BSUID, ou o telefone dentro do prazo, ou nada.
 *
 * **O sítio onde o telefone sai em claro** (nota do módulo). Os BSUID vêm pela
 * ordem da leitura, e um contacto fundido pode ter mais do que um: vale o
 * primeiro, porque qualquer um endereça a mesma pessoa.
 */
export function escolherDestinatario(endpoints: EndpointsDoContacto, agora: Date): Destinatario {
  const bsuid = endpoints.bsuids[0];
  if (bsuid !== undefined) return { bsuid, telefone: null };
  const vivo = endpoints.telefones.find(
    (t) => t.finalidade === FINALIDADE_DA_RESPOSTA && t.expiraAt.getTime() > agora.getTime(),
  );
  return vivo === undefined ? SEM_DESTINATARIO : { bsuid: null, telefone: vivo.telefone };
}

/** O `ObterDestinatario` de produção, pela identidade do KAM-008. */
export function destinatarioPelaIdentidade(o: OpcoesDoDestinatario): ObterDestinatario {
  const agora = o.agora ?? ((): Date => new Date());
  return async (tenantId, contactId) => {
    const ligacao = await o.tomar();
    let falha: unknown;
    try {
      let endpoints: EndpointsDoContacto;
      try {
        endpoints = await o.identidade.lerEndpoints(ligacao, tenantId, contactId);
      } catch (erro) {
        if (erro instanceof ContactoApagadoError || erro instanceof DekDestruidaError) {
          return SEM_DESTINATARIO;
        }
        throw erro;
      }
      return escolherDestinatario(endpoints, agora());
    } catch (erro) {
      falha = erro;
      throw erro;
    } finally {
      await o.devolver(ligacao, falha);
    }
  };
}
