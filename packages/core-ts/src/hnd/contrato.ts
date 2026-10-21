/**
 * O contrato do HND: a porta `HandoffProvider` e os seus tipos (KAM-019).
 *
 * **Dois destes tipos nunca existiram.** O `docs/tecnica/01` §11.1 escreve a
 * assinatura de `mirrorMessage(ctx, m: MirrorMessage)` e de
 * `onHumanEvent(handler: (e: HumanEvent) => Promise<void>)` e **não diz os
 * campos de nenhum dos dois** — nem esse documento, nem o §11 do `02`, nem o
 * dicionário antes da emenda 1.22. Este ficheiro é a primeira vez que eles
 * têm forma, e a emenda fixou-a antes de o código existir.
 *
 * ## O que é porta e o que é implementação
 *
 * Tudo aqui é porta. O ADR-012 fixa a costura `HandoffProvider` e diz que o
 * Chatwoot é **substituível**; se este ficheiro mencionasse Chatwoot em algum
 * tipo, a substituição deixava de ser uma implementação nova e passava a ser
 * uma migração. Por isso o provedor é um valor de domínio
 * (`handoff_accounts.provedor`) e não um nome em TypeScript, e os
 * identificadores que ele devolve são `number` opacos — é o que a assinatura do
 * §11.1 diz, e não se lhes dá significado.
 *
 * ## O `setBotMuted` está aqui e **não é executável**
 *
 * É a única operação da interface que este ticket não pode cumprir, e a razão
 * não é esquecimento: silenciar o bot é escrever `conversations.mode`, e
 * `kamba_app` não tem `UPDATE (mode)` — a revisão `0009` recusou-o por escrito
 * («um privilégio concedido para quando for preciso é um privilégio que
 * ninguém volta a tirar») e as transições de modo são do KAM-018, que o próprio
 * critério 8 nomeia como implementador do guarda. A porta fica, com o tipo
 * certo, e levanta `SemPrivilegioError`. A alternativa era omiti-la da
 * interface e obrigar o KAM-018 a alargá-la — isto é, esconder hoje o que vai
 * ter de aparecer.
 */

import type { ChannelContext } from "../chr/index.ts";

/** O ciclo de vida de uma passagem. Dicionário §3.15; `docs/tecnica/02` §11. */
export const ESTADOS = [
  "waiting",
  "resumed",
  "timeout",
  "cancelled",
  "degraded",
] as const;

export type EstadoDeHandoff = (typeof ESTADOS)[number];

/**
 * Os desfechos que o `close` aceita. **Três, contra os cinco estados.**
 *
 * A assinatura do §11.1 usa este vocabulário e a tabela usa o outro, e a
 * correspondência está em `estados.ts`. Sem ela, o `close('resolved')` não
 * sabia o que gravar — e era a espécie de lacuna que só aparece quando alguém
 * escreve o `UPDATE`.
 */
export const OUTCOMES = ["resolved", "timeout", "cancelled"] as const;

export type Outcome = (typeof OUTCOMES)[number];

/** O provedor de atendimento. Um valor hoje; a coluna existe pelo ADR-012. */
export const PROVEDORES = ["chatwoot"] as const;

export type Provedor = (typeof PROVEDORES)[number];

/** O sentido de uma mensagem espelhada. Dicionário §3.15. */
export const DIRECCOES = ["entrada", "saida"] as const;

export type Direccao = (typeof DIRECCOES)[number];

/**
 * Os dois acontecimentos humanos que se aceitam.
 *
 * São **exactamente** os dois *callbacks* que o critério 5 nomeia
 * (`message_created` de agente e `conversation_status_changed`). Um terceiro
 * que o provedor mande é **recusado** e não ignorado: aceitar um acontecimento
 * que não se sabe tratar é deixá-lo passar sem efeito, e um dia alguém
 * pergunta porque é que o handoff não fechou.
 *
 * Chama-se `acontecimento` e não `tipo` por uma razão medida na emenda 1.22: um
 * domínio sobre o nome nu `tipo` passa a valer para **qualquer** coluna com
 * esse nome em qualquer tabela, e o *gate* 3b recusou o `CHECK` de
 * `evt_subscricoes.tipo` por causa disso.
 */
export const ACONTECIMENTOS = ["mensagem_de_agente", "estado_mudou"] as const;

export type Acontecimento = (typeof ACONTECIMENTOS)[number];

/**
 * Uma conta de atendimento, como o `ensureAccount` a devolve (§11.1).
 *
 * **Quatro identificadores e não três** (emenda 1.23), e o quarto vem de
 * medição: o spike do critério 8 mediu que os *endpoints* `/api/v1/accounts/…`
 * recusam o *token* da Platform API com 401 («not authorized for bots»), e que
 * o do *agent bot* recusa criar contactos com o mesmo 401. Existe um terceiro
 * ator — um **utilizador** criado pela Platform API e ligado à conta por
 * `account_users` — e é o `access_token` dele que abre *inboxes* e contactos.
 *
 * `providerUserId` e não `userId`: a KAMBÁ vai ter utilizadores seus (o painel,
 * KAM-091), e um nome genérico cai na regra da emenda 1.14 do dicionário. O
 * `accountId`, o `inboxId` e o `botId` são vocabulário do Chatwoot e não
 * colidem com nada nosso.
 */
export interface ContaDeAtendimento {
  readonly accountId: number;
  readonly inboxId: number;
  readonly botId: number;
  readonly providerUserId: number;
}

/**
 * O que a criação de uma conta devolve: os identificadores **e os dois
 * segredos**.
 *
 * Os *tokens* vêm em claro porque é a **única** vez que o provedor os mostra —
 * o `access_token` de um utilizador e de um bot saem no corpo da criação e não
 * se voltam a ler. Quem recebe isto guarda-os no cofre e **não** os deixa
 * passar para mais nenhum sítio: não vão para a base (lá ficam as `SecretRef`),
 * não vão para registo, e não vão numa mensagem de erro.
 *
 * A primeira versão deste módulo não os devolvia, e era um buraco silencioso:
 * o provedor gerava dois segredos e nada os capturava, pelo que nenhuma
 * operação posterior os podia usar.
 */
export interface ContaCriada {
  readonly conta: ContaDeAtendimento;
  readonly tokenDoBot: string;
  readonly tokenDoUtilizador: string;
}

/**
 * Uma mensagem espelhada no provedor.
 *
 * **O que não está nestes campos é o ponto.** Sem telefone, sem BSUID, sem
 * `contact_id`: o provedor identifica a pessoa pela sua própria conta de
 * contacto, criada no `ensureAccount`, e o ADR-010 proíbe mandar os nossos
 * identificadores para fora. O `texto` é o corpo que o cliente já leu ou vai
 * ler — não se acrescenta nada que ele não tenha visto.
 */
export interface MirrorMessage {
  /** Idempotência: três chamadas com o mesmo `wamid` dão uma mensagem. */
  readonly wamid: string;
  readonly direccao: Direccao;
  /** O `wa_type` do dicionário §3.12 (`text`, `image`, …). */
  readonly waType: string;
  readonly texto: string;
  readonly criadoEm: Date;
}

/** Um acontecimento humano recebido do provedor. */
export interface HumanEvent {
  readonly acontecimento: Acontecimento;
  /** O identificador da conversa no provedor. */
  readonly externalId: string;
  /** O `handoff_id` que o atributo da conversa no provedor devolve. */
  readonly handoffId: string;
  /** Presente no `mensagem_de_agente`. */
  readonly texto: string | null;
  /**
   * O identificador da **mensagem** no provedor. `null` no `estado_mudou`.
   *
   * Existe por uma razão só, e é de idempotência: e dele que a chave do envio
   * da resposta humana deriva (`resposta.ts`). Derivá-la do texto fazia duas
   * mensagens iguais do agente («ok») serem uma só, que é pior do que o
   * problema que resolvia.
   */
  readonly mensagemId: string | null;
  /** Presente no `estado_mudou`: o estado do provedor, em cru. */
  readonly estado: string | null;
  /** Identificador opaco do agente. Nunca nome, e-mail ou telefone. */
  readonly resolver: string | null;
}

/** O que o `openHandoff` recebe (§11.1). */
export interface PedidoDeHandoff {
  readonly tenantId: string;
  /**
   * Uma chave **opaca e estável** do contacto, derivada por quem chama.
   *
   * **Nunca o nosso `contact_id`**, e isto é a correcção de um defeito que
   * sobreviveu a quatro testes: a primeira versão trazia `contactId` e punha-o
   * no `source_id` da conversa, isto é, mandava um identificador nosso para
   * fora, contra o ADR-010 — no mesmo módulo que diz, na nota do
   * `MirrorMessage`, que isso não se faz. E o spike mostrou que nem funcionava:
   * o Chatwoot quer o `source_id` de um `contact_inbox` **que exista**, e um
   * valor que ele não emitiu responde 404.
   *
   * Quem deriva é o chamador, que tem o contexto para o fazer (o
   * `contact_hmac_prefix` do *logger* é a mesma família de ideia). O HND não
   * recebe o identificador e por isso não o pode deixar escapar.
   */
  readonly chaveDoContacto: string;
  readonly conversationId: string;
  /** `hash(thread_id, ordinal_do_handoff)`. Derivado, não gerado. */
  readonly handoffId: string;
  readonly motivo: string;
  /** O resumo que vai para a nota privada da conversa no provedor. */
  readonly resumo: string;
}

/** O que o `openHandoff` devolve (§11.1). */
export interface HandoffAberto {
  /** O identificador da conversa no provedor. Vazio numa passagem degradada. */
  readonly externalId: string;
  /** `true` quando a passagem já existia: não houve chamada ao provedor. */
  readonly repetido: boolean;
  /** `degraded` quando o provedor não respondeu e a abertura ficou em fila. */
  readonly estado: EstadoDeHandoff;
}

/**
 * A porta do provedor de atendimento.
 *
 * As seis operações são as do `docs/tecnica/01` §11.1, com os nomes que ele
 * fixa. O `ChannelContext` do `mirrorMessage` é o do CHR (KAM-014) e é o que
 * traz o *tenant*: o espelho não recebe `tenant_id` por argumento solto,
 * porque o `tenant_id` nasce no CHR e nenhum passo seguinte o recebe de fora.
 */
export interface HandoffProvider {
  ensureAccount(tenantId: string): Promise<ContaDeAtendimento>;
  /** Idempotente por `wamid`: três chamadas, uma mensagem. */
  mirrorMessage(ctx: ChannelContext, m: MirrorMessage): Promise<void>;
  /** Idempotente por `handoffId`. Ver `HandoffAberto`. */
  openHandoff(pedido: PedidoDeHandoff): Promise<HandoffAberto>;
  /** **Levanta.** Ver a nota do módulo. */
  setBotMuted(conversationId: string, muted: boolean): Promise<void>;
  onHumanEvent(handler: (e: HumanEvent) => Promise<void>): void;
  close(handoffId: string, outcome: Outcome): Promise<void>;
}

/** A linha de `handoffs`, como as consultas a devolvem. */
export interface LinhaDeHandoff {
  readonly handoff_id: string;
  readonly tenant_id: string;
  readonly conversation_id: string;
  readonly status: string;
  readonly motivo: string;
  readonly external_id: string | null;
  readonly opened_at: Date;
  readonly resumed_at: Date | null;
  readonly resolver: string | null;
}

/**
 * O cliente SQL, por porta.
 *
 * `readonly rows` como no `ClienteSql` do KAM-015, e pela mesma razão: quem
 * recebe o resultado não o altera, e o tipo di-lo em vez de o pedir por
 * convenção.
 */
export interface ClienteSql {
  query<T = Record<string, unknown>>(
    texto: string,
    valores?: readonly unknown[],
  ): Promise<{ readonly rows: readonly T[] }>;
}

/** O que o provedor precisa de saber de uma conversa para a abrir. */
export interface AberturaNoProvedor {
  readonly conta: ContaDeAtendimento;
  readonly handoffId: string;
  /** A chave opaca do contacto. Ver a nota do `PedidoDeHandoff`. */
  readonly chaveDoContacto: string;
  readonly resumo: string;
}

/**
 * A porta do provedor de atendimento propriamente dito (a API de terceiro).
 *
 * Separada do `HandoffProvider` de propósito: o `HandoffProvider` é a costura
 * que o resto da plataforma usa e inclui a persistência; **esta** é só a
 * conversa com o terceiro. É a divisão que permite provar a idempotência
 * contra a base real sem abrir *socket* nenhum, como o KAM-015 fez com o
 * `ClienteDaMeta`.
 */
export interface ClienteDoProvedor {
  /**
   * Cria a conversa e devolve o seu identificador no provedor.
   *
   * Cria também, antes dela, o **contacto** — o provedor quer o `source_id` de
   * um `contact_inbox` que ele próprio emitiu, e isso só se sabe depois de o
   * criar (medido: um valor inventado responde 404).
   */
  abrirConversa(abertura: AberturaNoProvedor): Promise<string>;
  /**
   * Espelha uma mensagem numa conversa que já existe.
   *
   * **O `externalId` é um argumento e não vem no `MirrorMessage`**, e é a
   * correcção de um defeito: a primeira versão punha o `wamid` no lugar do
   * identificador da conversa no URL, pelo que qualquer chamada real daria 404
   * — e o teste afirmava o corpo e nunca o `url`, o que é a razão de ter
   * passado. O `wamid` continua a ir no corpo, em `source_id`, que é onde o
   * provedor de-duplica.
   */
  espelhar(
    conta: ContaDeAtendimento,
    externalId: string,
    m: MirrorMessage,
  ): Promise<void>;
  /** Fecha a conversa no provedor. */
  fecharConversa(conta: ContaDeAtendimento, externalId: string): Promise<void>;
}

/**
 * A porta do **provisionamento**, separada da de execução.
 *
 * Separada porque o `../docs/tecnica/08` §3.6 exige que «o *token* da Platform
 * API (poderoso) só exista no serviço de *provisioning*, nunca no AGR», e a
 * primeira versão deste módulo punha-o como campo obrigatório do **mesmo**
 * objecto que abre conversas e espelha mensagens: qualquer processo que
 * precisasse de abrir uma conversa tinha de o ter em memória. Um parâmetro
 * distinto não é um processo distinto, e era só isso que estava garantido.
 */
export interface ProvisionadorDoProvedor {
  /** Cria conta, utilizador, *inbox* e bot do *tenant*, e devolve os segredos. */
  criarConta(tenantId: string): Promise<ContaCriada>;
}

/** Falta o privilégio que a operação exige. Ver a nota do módulo. */
export class SemPrivilegioError extends Error {
  constructor(operacao: string, detalhe: string) {
    super(
      `${operacao} nao e executavel pelo HND: ${detalhe}. A porta existe com o ` +
        "tipo certo para que o ticket que tiver o privilegio a ligue sem alterar " +
        "a interface; omiti-la era esconder hoje o que vai ter de aparecer.",
    );
    this.name = "SemPrivilegioError";
  }
}

/** O provedor não respondeu. A abertura fica em fila e a passagem `degraded`. */
export class ProvedorIndisponivelError extends Error {
  constructor(causa: string) {
    super(`provedor de atendimento indisponivel: ${causa}`);
    this.name = "ProvedorIndisponivelError";
  }
}
