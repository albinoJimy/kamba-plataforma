/**
 * O vocabulário do onboarding de canal: fases, transições, campos e portas (KAM-016).
 *
 * Nenhuma lógica aqui, e nenhum efeito: constantes, tipos e as portas que o
 * módulo precisa. É a forma que o `qualidade/contrato.ts` e o
 * `consentimento/contrato.ts` já usam, e a razão é a mesma — um domínio escrito
 * ao lado de quem o consome divergia do da base no primeiro dia em que alguém
 * mudasse um dos dois.
 *
 * ## Só v4, e o código não refere v2 nem v3
 *
 * CONFIRMADO (`E1` §3): o Embedded Signup v2 e v3 **deixam de funcionar a
 * 2026-10-15**, incluindo *previews*. O critério 1 é explícito — «o código não
 * referencia v2/v3» —, e há um teste que varre `src/onboarding/` à procura das
 * duas cadeias. Não há ramo de compatibilidade, nem constante de versão do ES:
 * uma versão em configuração convidava alguém a voltar atrás.
 *
 * O que **é** configuração é a versão da **Graph API**, e isso é outra coisa:
 * os *Detalhes Técnicos* do bloco mandam-no por extenso («fixar a versão da
 * Graph API em configuração»), porque os pontos finais e os parâmetros exactos
 * não constam do `E1` — as páginas de referência de API não foram lidas. Ver
 * `VERSAO_DA_GRAPH_POR_OMISSAO`.
 *
 * ## As quatro portas
 *
 * 1. **`ClienteSql`** — a ligação **dentro** da transacção de quem chama, como
 *    no KAM-021. A saga tem passos que têm de ser atómicos dois a dois (a linha
 *    do canal e o `channel_id` desta tabela), e uma ligação própria não os
 *    conseguiria juntar.
 * 2. **`Graph`** — o que fala com a Meta. É uma porta e não um `fetch` porque o
 *    `GraphFalso` do KAM-024 é o que os testes usam, e porque nenhum dos
 *    caminhos da API está CONFIRMADO: a fronteira onde eles se escrevem tem de
 *    ser um sítio só.
 * 3. **`Cofre`** — ler, cunhar e revogar. A leitura é a `SecretProvider` do
 *    KAM-010; a escrita é a `SecretWriter` que este ticket acrescenta, e a
 *    lacuna estava declarada no `ADR-L002` §6 precisamente para este dia.
 * 4. **`Logger`** — opcional, e sujeito à lista branca de campos do KAM-068.
 */

import type { SecretRef } from "../secrets/port.ts";

/**
 * O cliente de SQL que este módulo precisa.
 *
 * `readonly rows` como o `ClienteSql` do KAM-015, o do KAM-021 e o
 * `ClienteDoChr` do KAM-014, e pela mesma razão: este módulo nunca altera o que
 * lê, e um tipo com `rows` mutável obrigava quem o liga a provar que não o
 * altera.
 */
export interface ClienteSql {
  query<T = Record<string, unknown>>(
    texto: string,
    valores?: readonly unknown[],
  ): Promise<{ readonly rows: readonly T[] }>;
}

/**
 * As nove fases do critério 6, pela ordem do `../../../docs/tecnica/01` §13.1.
 *
 * **O `desligado` do diagrama não está aqui**, e é decisão e não esquecimento:
 * é valor de `tenant_channels.estado` desde a revisão `0001` (dicionário §3.2)
 * e quem o escreve é o tratador do `account_update`, que é KAM-017. O diagrama
 * mistura as duas máquinas de estados num desenho; o critério deste ticket
 * enumera nove e desfaz a mistura.
 *
 * É o mesmo domínio que o `channel_onboarding_fase_ck` da revisão `0016` impõe,
 * e **há um teste que compara as duas listas**: duas cópias de um domínio
 * divergem no dia em que uma delas mudar.
 */
export const FASES = [
  "iniciado",
  "es_concluido",
  "subscrito",
  "a_sincronizar",
  "verificado",
  "pronto",
  "ativo",
  "falhado",
  "abandonado",
] as const;
export type Fase = (typeof FASES)[number];

/**
 * A matriz de transições: de cada fase, as fases a que se pode ir.
 *
 * Escrita célula a célula e não derivada de uma ordem, pela razão do
 * `outbound/estados.ts`: dar um número a cada fase e comparar daria «`falhado`
 * é depois de `pronto`», que é verdade por acidente, e «`abandonado` é depois
 * de `falhado`», que não é verdade nenhuma.
 *
 * **Dezesseis arestas, e o diagrama do `01` §13.1 desenha onze.** A diferença é
 * uma regra só: de qualquer fase não terminal vai-se a `falhado`. O diagrama só
 * desenha `a_sincronizar --> falhado` (o prazo de 24 h), mas o critério 7 pede
 * uma falha injectada no **passo 4** — a subscrição, que corre em
 * `es_concluido`. Uma saga cuja compensação não tem onde se registar é uma saga
 * que não compensa: sem esta regra, o caminho que o critério 7 manda exercitar
 * não é representável na tabela que o critério 6 define.
 *
 * **O `abandonado` fica só de `iniciado`**, como o diagrama o desenha. O
 * critério diz «sem conclusão em 30 min», e o diagrama diz de que conclusão
 * fala: `iniciado --> abandonado: popup fechado ou timeout 30 min`. Uma
 * tentativa que já trocou o *code* e subscreveu campos não se «abandona» — ou
 * acaba, ou falha com compensação, e o que distingue as duas é haver recursos a
 * desfazer.
 *
 * **O `ativo` é terminal**: a saga acaba ali. Desligar um canal activo é
 * `tenant_channels.estado`, e a reconexão volta a esta tabela por `iniciado`.
 */
export const TRANSICOES: Readonly<Record<Fase, readonly Fase[]>> = {
  iniciado: ["es_concluido", "abandonado", "falhado"],
  es_concluido: ["subscrito", "falhado"],
  subscrito: ["a_sincronizar", "verificado", "falhado"],
  a_sincronizar: ["verificado", "falhado"],
  verificado: ["pronto", "falhado"],
  pronto: ["ativo", "falhado"],
  ativo: [],
  falhado: ["iniciado"],
  abandonado: ["iniciado"],
};

/** `true` se a transição é uma das dezesseis. Uma fase para si mesma **não** é. */
export function transicaoValida(de: Fase, para: Fase): boolean {
  return TRANSICOES[de].includes(para);
}

/**
 * Os **onze** campos de webhook do critério 5, pela ordem em que ele os escreve.
 *
 * São os do `../../../docs/tecnica/01` §4.4, todos CONFIRMADOS no `E1` §2–§3. A
 * ordem é a do critério e não alfabética, para que a comparação com o texto do
 * bloco se faça a olho; **a verificação é por igualdade de conjuntos** e não de
 * listas, porque a Meta devolve `subscribed_fields` sem ordem garantida.
 *
 * Os quatro últimos são de templates e os três do meio são de qualidade: os
 * consumidores são o KAM-021 e o KAM-015, e é por isso que este ticket os
 * subscreve sem os tratar. Subscrever menos do que onze era deixar um webhook
 * que outro ticket espera a nunca chegar, e isso não se descobre num teste do
 * ticket que o trata.
 */
export const CAMPOS_DE_WEBHOOK = [
  "messages",
  "smb_message_echoes",
  "history",
  "smb_app_state_sync",
  "account_update",
  "phone_number_quality_update",
  "business_capability_update",
  "account_alerts",
  "message_template_status_update",
  "template_category_update",
  "message_template_quality_update",
] as const;
export type CampoDeWebhook = (typeof CAMPOS_DE_WEBHOOK)[number];

/**
 * A configuração do *popup* v4, na forma que o critério 1 fixa.
 *
 * CONFIRMADO (`E1` §3, `01` §4.3): a coexistência usa
 * `extras.featureType = "whatsapp_business_app_onboarding"` e
 * `sessionInfoVersion: "3"`; o evento final é
 * `FINISH_WHATSAPP_BUSINESS_APP_ONBOARDING` e **não há registo do número**.
 *
 * Está aqui como constante e não como literal espalhado porque o critério pede
 * que a forma seja v4 — e uma forma que se escreve num sítio é uma forma que se
 * pode afirmar num teste.
 */
export const FEATURE_TYPE_DE_COEXISTENCIA = "whatsapp_business_app_onboarding";
/** A versão do `session_info`, **cadeia e não número**, como o `E1` a escreve. */
export const SESSION_INFO_VERSION = "3";
/** O evento com que o *popup* fecha em coexistência (`E1` §3). */
export const EVENTO_FINAL_DE_COEXISTENCIA = "FINISH_WHATSAPP_BUSINESS_APP_ONBOARDING";

/**
 * A versão da Graph API, **em configuração** e com omissão declarada.
 *
 * Os *Detalhes Técnicos* do bloco mandam fixá-la em configuração, e a razão
 * está lá: «Os pontos finais e parâmetros exactos da Graph API **não** constam
 * de E1 (páginas de referência de API não lidas)». O `GraphFalso` do KAM-024
 * aceita **qualquer** `/v<maior>.<menor>/` e registra a que o cliente usou, e
 * diz porquê no seu próprio ficheiro: «inventar uma ("v23.0") era afirmar o que
 * não se sabe».
 *
 * Este valor é por isso ***proposta***, e o que um teste afirma é que o cliente
 * usa **a que a configuração diz** — não que esta esteja certa. A variável de
 * ambiente é a porta para a corrigir sem recompilar no dia em que alguém leia a
 * documentação vigente.
 */
export const VARIAVEL_DA_VERSAO_DA_GRAPH = "KAMBA_META_GRAPH_VERSION";
/** A omissão. *Proposta*: ver `VARIAVEL_DA_VERSAO_DA_GRAPH`. */
export const VERSAO_DA_GRAPH_POR_OMISSAO = "v21.0";

/** `v<maior>.<menor>`, a única forma que a Graph aceita num caminho. */
const VERSAO = /^v\d+\.\d+$/;

/** Levantada quando a versão configurada da Graph não tem a forma `vNN.N`. */
export class VersaoDaGraphInvalidaError extends Error {
  override readonly name = "VersaoDaGraphInvalidaError";
  readonly valor: string;

  constructor(valor: string) {
    super(
      `versão da Graph API inválida: ${JSON.stringify(valor)}; ` +
        `esperava a forma v<maior>.<menor> (${VARIAVEL_DA_VERSAO_DA_GRAPH})`,
    );
    this.valor = valor;
  }
}

/**
 * A versão da Graph a usar, do ambiente ou da omissão.
 *
 * Falha **fechada** numa forma inválida, e não cai para a omissão: um caminho
 * com um segmento de versão que a Meta não reconhece dá 404 em produção, e
 * descobri-lo no arranque é melhor do que no primeiro onboarding real.
 */
export function versaoDaGraph(
  ambiente: Readonly<Record<string, string | undefined>> = process.env,
): string {
  const bruto = (ambiente[VARIAVEL_DA_VERSAO_DA_GRAPH] ?? "").trim();
  if (bruto === "") return VERSAO_DA_GRAPH_POR_OMISSAO;
  if (!VERSAO.test(bruto)) throw new VersaoDaGraphInvalidaError(bruto);
  return bruto;
}

/**
 * Os quatro tipos de recurso que a saga cria, e que a compensação desfaz.
 *
 * Um por passo com efeito fora desta transacção, e é isso que decide a lista: o
 * `01` §13.2 dá a compensação de cada passo («Revogar token», «Repetir;
 * alerta»), e um passo sem recurso não tem o que compensar.
 *
 *     token        o *token* de cliente no cofre (passo 3)
 *     pin          o PIN 2FA no cofre (passo 3, só em `cloud_only`)
 *     canal        a linha de `tenant_channels` (passo 3, depois do *token*)
 *     subscricao   a subscrição dos onze campos no WABA (passo 4)
 *
 * **A ordem desta lista é a ordem em que se criam**, e a compensação percorre
 * `recursos_criados` ao contrário — não esta constante. A constante é o domínio;
 * a ordem real está na coluna, porque em `cloud_only` o `pin` existe e em
 * coexistência não.
 */
export const RECURSOS = ["token", "pin", "canal", "subscricao"] as const;
export type Recurso = (typeof RECURSOS)[number];

/** Um recurso criado por um passo, como fica em `recursos_criados`. */
export interface RecursoCriado {
  readonly recurso: Recurso;
  /**
   * O que a compensação precisa para o desfazer, e **nunca um valor de
   * segredo**: uma `SecretRef` para o `token` e o `pin`, o `channel_id` para o
   * `canal`, o `waba_id` para a `subscricao`.
   */
  readonly ref: string;
}

/** Os dois modos de canal, o domínio de `tenant_channels.channel_mode` da `0001`. */
export const MODOS = ["coexistencia", "cloud_only"] as const;
export type Modo = (typeof MODOS)[number];

/**
 * O que o Embedded Signup devolve, e é o corpo do `POST /internal/channels`.
 *
 * Os quatro primeiros campos são os do critério 1. O `session_info` é o que o
 * *popup* devolve com `sessionInfoVersion: "3"`, e entra **inteiro e opaco**: a
 * sua forma exacta não está CONFIRMADA em sítio nenhum deste repositório, e
 * inventar-lhe campos era afirmar o que não se sabe. O que se lê dele é o
 * `extras.featureType`, que o critério nomeia.
 */
export interface ResultadoDoEs {
  readonly tenant_id: string;
  readonly code: string;
  readonly waba_id: string;
  readonly phone_number_id: string;
  readonly session_info: Readonly<Record<string, unknown>>;
}

/** Os campos que o módulo lê do `session_info`, e mais nenhum. */
export interface SessionInfo {
  readonly sessionInfoVersion?: unknown;
  readonly extras?: { readonly featureType?: unknown };
}

/**
 * A porta da Graph API.
 *
 * Três operações, e as três têm compensação ou são idempotentes por natureza.
 * **Não há aqui registo do número**: em coexistência não se faz (CONFIRMADO,
 * `E1` §3), e em `cloud_only` é o passo 5′ do `01` §13.2, que é KAM-093 — este
 * ticket guarda o PIN que ele vai usar e mais nada.
 */
export interface Graph {
  /** Troca o *code* por um *token* de cliente. Devolve o *token* em claro. */
  trocarCode(code: string): Promise<string>;
  /** Subscreve a app ao WABA nos campos dados. */
  subscrever(wabaId: string, campos: readonly string[], token: string): Promise<void>;
  /** Lê os campos subscritos, para a confirmação por igualdade de conjuntos. */
  lerSubscricoes(wabaId: string, token: string): Promise<readonly string[]>;
  /** Anula a subscrição do WABA. A compensação do passo 4. */
  anularSubscricao(wabaId: string, token: string): Promise<void>;
}

/**
 * A porta do cofre: ler, cunhar e revogar.
 *
 * `cunhar` e `revogar` são o que o `ADR-L002` §6 declarou em falta — «Cunhar
 * uma referência nova … é o que o **KAM-016** vai precisar na troca do *code* do
 * Embedded Signup v4 … O KAM-016 acrescenta-a». A porta de leitura continua a
 * ser a `SecretProvider` do KAM-010, e esta estende-a em vez de a substituir.
 */
export interface Cofre {
  /** O valor actual de uma referência. */
  get(ref: SecretRef): Promise<string>;
  /** `[actual, anterior]`, para o `kid` versionado da KEK. */
  getRing(ref: SecretRef): Promise<readonly [string, string | null]>;
  /** As versões vivas, da mais recente para a mais antiga. `versions()[0]` casa com `get()`. */
  versions(ref: SecretRef): Promise<readonly string[]>;
  /** Escreve um segredo numa família e devolve a referência que a base guarda. */
  cunhar(familia: string, valor: string): Promise<SecretRef>;
  /** Apaga o segredo de uma referência. A compensação dos passos do cofre. */
  revogar(ref: SecretRef): Promise<void>;
}

/*
 * **Os três `id` de segredo vivem em `segredos.ts`**, e não aqui.
 *
 * Não é organização: é a área que o *gate* 9 dispensa. Um `id` do
 * `ops/secrets-inventory.yaml` atribuído a um nome que contém «TOKEN» faz a
 * classe `atribuicao` do scanner disparar — e correctamente, porque a heurística
 * não pode distinguir um `id` de um valor (medido: `"meta_client_token"` tem
 * entropia de Shannon 3,293 contra o mínimo de 3,2). Com eles num ficheiro de
 * três constantes, **este** continua inteiramente varrido. É o desenho e a razão
 * do `services/gwy/src/segredos.ts` (KAM-013).
 */
export { FAMILIA_DO_PIN, FAMILIA_DO_TOKEN, REF_DA_KEK } from "./segredos.ts";

/** Dígitos de um PIN 2FA. A Meta pede seis (`01` §13.2, passo 3). */
export const DIGITOS_DO_PIN = 6;

/** Quanto tempo uma tentativa pode ficar em `iniciado` antes de ser abandonada. */
export const PRAZO_DE_ABANDONO_MIN = 30;

/** A janela do contador do critério 8, em dias. CONFIRMADO (`E1` §3). */
export const JANELA_DE_ONBOARDINGS_DIAS = 7;
/** O tecto de clientes novos na janela, antes de verificação completa. CONFIRMADO. */
export const LIMITE_DE_ONBOARDINGS = 10;

/** A linha de `channel_onboarding`, na forma em que o módulo a lê. */
export interface Tentativa {
  readonly id: string;
  readonly tenant_id: string;
  readonly channel_id: string | null;
  readonly waba_id: string;
  readonly waac_id: string | null;
  readonly phone_number_id: string;
  readonly fase: Fase;
  readonly recursos_criados: readonly RecursoCriado[];
  readonly pin_ref: string | null;
  readonly motivo: string | null;
}

/** Levantada quando o `session_info` não é o de v4. */
export class EsNaoEV4Error extends Error {
  override readonly name = "EsNaoEV4Error";
  readonly motivo: string;

  constructor(motivo: string) {
    super(`o resultado do Embedded Signup não é v4: ${motivo}`);
    this.motivo = motivo;
  }
}

/**
 * Levantada quando o `phone_number_id` já é de outro tenant. **É o 409.**
 *
 * Não leva o `tenant_id` do dono — quem recebe o 409 é o tenant que tentou, e
 * dizer-lhe de quem é o número era um canal de leitura entre tenants por
 * mensagem de erro.
 */
export class NumeroJaUsadoError extends Error {
  override readonly name = "NumeroJaUsadoError";
  readonly phoneNumberId: string;

  constructor(phoneNumberId: string) {
    super(`o phone_number_id ${phoneNumberId} já está ligado a outro tenant`);
    this.phoneNumberId = phoneNumberId;
  }
}

/** Levantada quando a transição pedida não é uma das dezesseis. */
export class TransicaoInvalidaError extends Error {
  override readonly name = "TransicaoInvalidaError";
  readonly de: Fase;
  readonly para: Fase;

  constructor(de: Fase, para: Fase) {
    super(`transição inválida: ${de} → ${para}`);
    this.de = de;
    this.para = para;
  }
}

/**
 * Levantada quando a leitura de confirmação não devolve o conjunto subscrito.
 *
 * Leva as duas diferenças e não só «falhou»: um campo que a Meta não aceitou e
 * um campo que ela já tinha são defeitos diferentes, e a mensagem é o único
 * sítio onde a diferença aparece.
 */
export class SubscricaoIncompletaError extends Error {
  override readonly name = "SubscricaoIncompletaError";
  readonly falta: readonly string[];
  readonly aMais: readonly string[];

  constructor(falta: readonly string[], aMais: readonly string[]) {
    super(
      "a leitura de confirmação não devolve os campos subscritos" +
        (falta.length > 0 ? `; falta: ${falta.join(", ")}` : "") +
        (aMais.length > 0 ? `; a mais: ${aMais.join(", ")}` : ""),
    );
    this.falta = falta;
    this.aMais = aMais;
  }
}

/** Levantada quando o tecto de dez clientes por sete dias já está gasto. */
export class LimiteDeOnboardingsError extends Error {
  override readonly name = "LimiteDeOnboardingsError";
  readonly contagem: number;

  constructor(contagem: number) {
    super(
      `o tecto de ${LIMITE_DE_ONBOARDINGS} clientes novos por ` +
        `${JANELA_DE_ONBOARDINGS_DIAS} dias está gasto (${contagem}); ` +
        "a lista de espera é KAM-095",
    );
    this.contagem = contagem;
  }
}
