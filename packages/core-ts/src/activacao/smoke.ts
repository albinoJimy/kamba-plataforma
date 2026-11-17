/**
 * O teste ponta a ponta assistido pelo dono (KAM-094, critérios 4 e 5).
 *
 * `start` pede ao dono que mande «teste» de **outro** telefone para o número da
 * loja e abre uma janela de `PRAZO_DO_TESTE_S`. `verify` lê os quatro factos da
 * conversa, por esta ordem, e a primeira que faltar é a causa:
 *
 *     sem_inbound        a mensagem do dono não chegou ao número da loja
 *     sem_resposta       o bot não respondeu, ou respondeu sem dizer que é um
 *                        assistente e de que loja
 *     sem_entrega        a resposta não chegou a `delivered`
 *     sem_consentimento  o aviso de 1.º contacto não gravou `consent_event`
 *
 * ## Dentro da janela, «ainda não» não é falha
 *
 * Um `verify` antes de a janela fechar e sem os quatro factos devolve a causa e
 * **não** conta uma falha: o dono pode estar a escrever. Só a janela fechada
 * sem os quatro factos fecha a tentativa como falhada. Assim, repetir o clique
 * não gasta tentativas, e o dono vê a causa genérica enquanto espera.
 *
 * ## Três falhas seguidas vão à fila, e o caso fica onde está
 *
 * À terceira, abre-se um `review_case` — `es_falhado` quando a mensagem nem
 * chegou (o canal), `saga` nos outros três (o que o provisionamento montou) — e
 * a contagem recomeça: o dono pode repetir, sem custo, enquanto a T&S olha. O
 * caso **não** sai de `aguarda_teste`; quem o muda é o `advance_case`.
 *
 * ## A conversa de teste
 *
 * Marca-se `is_test` sempre que houve `inbound`, passe ou não o teste: uma
 * conversa de ensaio fora das métricas é a mesma coisa num teste falhado.
 */

import {
  CAUSAS_DO_TESTE,
  type CausaDoTeste,
  FALHAS_ATE_A_FILA,
  type FactosDoTeste,
  type FilaDoTeste,
  type GatesDaActivacao,
  type MaquinaDoCaso,
  type MarcadorDeTeste,
  MENSAGEM_DE_FALHA_AO_DONO,
  type ObservadorDoTeste,
  PALAVRA_DO_TESTE,
  PRAZO_DO_TESTE_S,
  type RegistoDoTeste,
  type RemetenteDoTeste,
  REMETENTES_DO_TESTE,
  RemetenteVedadoError,
  type SmokeProbe,
  ActivacaoRecusadaError,
  TesteNaoIniciadoError,
} from "./contrato.ts";

/** Minúsculas, sem acentos, espaços colapsados. Para comparar texto de pessoas. */
export function normalizarTexto(texto: string): string {
  return texto
    .normalize("NFD")
    .replace(/\p{M}/gu, "")
    .toLowerCase()
    .replace(/\s+/gu, " ")
    .trim();
}

/** A mensagem do dono é o «teste»? Sem pontuação à volta, sem caixa. */
export function eMensagemDeTeste(texto: unknown): boolean {
  if (typeof texto !== "string") return false;
  return normalizarTexto(texto).replace(/^[^\p{L}]+|[^\p{L}]+$/gu, "") === PALAVRA_DO_TESTE;
}

/**
 * A resposta identifica o assistente **e** a loja?
 *
 * O aviso de 1.º contacto (KAM-022) diz que quem responde é um assistente
 * automático de uma loja com nome. Aqui só se confere que os dois nomes estão
 * lá; a redacção é do KAM-022.
 */
export function identificaAssistenteELoja(texto: string, assistente: string, loja: string): boolean {
  const t = normalizarTexto(texto);
  const a = normalizarTexto(assistente);
  const l = normalizarTexto(loja);
  return a !== "" && l !== "" && t.includes(a) && t.includes(l);
}

/** A primeira causa que falta, ou `null` com os quatro factos. */
export function causaDosFactos(f: FactosDoTeste): CausaDoTeste | null {
  const falta: Record<CausaDoTeste, boolean> = {
    sem_inbound: !f.inbound,
    sem_resposta: !f.resposta,
    sem_entrega: !f.entregue,
    sem_consentimento: !f.consentimento,
  };
  return CAUSAS_DO_TESTE.find((c) => falta[c]) ?? null;
}

/** A fila de uma falha: o canal quando nada chegou, o provisionamento nos outros. */
export function tipoDaFila(causa: CausaDoTeste): "es_falhado" | "saga" {
  return causa === "sem_inbound" ? "es_falhado" : "saga";
}

/**
 * O remetente do teste, a partir da configuração. `owner_assisted` por omissão.
 *
 * shortcut: o `prober_number` recusa sempre — não há número operacional da
 * KAMBÁ (D10 aberto) nem implementação; revê-se quando o D10 fechar a favor de
 * um número da plataforma.
 */
export function remetenteDoTeste(pedido: unknown = undefined): RemetenteDoTeste {
  if (pedido === undefined || pedido === null || pedido === "" || pedido === "owner_assisted") {
    return "owner_assisted";
  }
  if (pedido === "prober_number") throw new RemetenteVedadoError();
  throw new RangeError(`remetente do teste desconhecido; esperado um de ${REMETENTES_DO_TESTE.join(", ")}`);
}

export interface DependenciasDoTeste {
  readonly maquina: MaquinaDoCaso;
  readonly registo: RegistoDoTeste;
  readonly observador: ObservadorDoTeste;
  readonly marcador: MarcadorDeTeste;
  readonly fila: FilaDoTeste;
  readonly gates: GatesDaActivacao;
  readonly relogio?: () => Date;
  /** `PRAZO_DO_TESTE_S` por omissão. */
  readonly prazoS?: number;
}

/** O `SmokeProbe` `owner_assisted`. */
export class SmokeOwnerAssisted implements SmokeProbe {
  readonly #d: DependenciasDoTeste;
  readonly #relogio: () => Date;
  readonly #prazoMs: number;

  constructor(dependencias: DependenciasDoTeste) {
    const prazo = dependencias.prazoS ?? PRAZO_DO_TESTE_S;
    if (!Number.isFinite(prazo) || prazo <= 0) throw new RangeError("o prazo do teste e positivo");
    this.#d = dependencias;
    this.#relogio = dependencias.relogio ?? (() => new Date());
    this.#prazoMs = prazo * 1000;
  }

  async #caso(onboardingId: string) {
    const caso = await this.#d.maquina.ler(onboardingId);
    if (caso === null) throw new ActivacaoRecusadaError("sem_caso");
    return caso;
  }

  async start(onboardingId: string): Promise<{ instrucoes: string; expiraEm: Date }> {
    const caso = await this.#caso(onboardingId);
    if (caso.fase !== "aguarda_teste") throw new ActivacaoRecusadaError("fase_errada");
    const agora = this.#relogio();
    const corrente = await this.#d.registo.corrente(onboardingId);
    // Um `start` repetido dentro da janela devolve a mesma janela: dois cliques
    // não são duas tentativas.
    const t =
      corrente !== null && corrente.resultado === "pendente" && corrente.expiraEm > agora
        ? corrente
        : await this.#d.registo.iniciar(onboardingId, agora, new Date(agora.getTime() + this.#prazoMs));
    const segundos = Math.round((t.expiraEm.getTime() - agora.getTime()) / 1000);
    return {
      instrucoes:
        `De outro telefone, envie a palavra «teste» para o número da sua loja no WhatsApp. ` +
        `Esperamos a resposta do assistente durante ${segundos} segundos.`,
      expiraEm: t.expiraEm,
    };
  }

  async verify(onboardingId: string): Promise<{ ok: boolean; causa?: CausaDoTeste }> {
    const caso = await this.#caso(onboardingId);
    const t = await this.#d.registo.corrente(onboardingId);
    if (t === null) throw new TesteNaoIniciadoError();
    if (t.resultado === "ok") return { ok: true };
    if (t.resultado === "falhou") return { ok: false, causa: t.causa ?? "sem_inbound" };

    const agora = this.#relogio();
    const ate = agora < t.expiraEm ? agora : t.expiraEm;
    const factos = await this.#d.observador.factos(onboardingId, t.iniciadaEm, ate);
    if (factos.conversationId !== null) await this.#d.marcador.marcar(caso.tenantId, factos.conversationId);

    const causa = causaDosFactos(factos);
    if (causa === null) {
      await this.#d.registo.fechar(onboardingId, "ok", null);
      await this.#d.gates.marcar(onboardingId, "e2e", true, "smoke:owner_assisted");
      return { ok: true };
    }
    if (agora < t.expiraEm) return { ok: false, causa };

    // **Só quem fechou segue.** Dois `verify` depois do prazo leem os dois a
    // pendente; o segundo `fechar` não afecta linha nenhuma e não abre outro
    // caso na fila (achado 11 da revisão adversarial).
    if (!(await this.#d.registo.fechar(onboardingId, "falhou", causa))) return { ok: false, causa };
    await this.#d.gates.marcar(onboardingId, "e2e", false, `smoke:${causa}`);
    if ((await this.#d.registo.falhasSeguidas(onboardingId, agora)) >= FALHAS_ATE_A_FILA) {
      await this.#d.fila.abrir(onboardingId, tipoDaFila(causa), causa);
      await this.#d.registo.zerar(onboardingId);
    }
    return { ok: false, causa };
  }
}

/** O texto que o dono lê depois de uma falha. Igual para as quatro causas. */
export function mensagemAoDono(_causa: CausaDoTeste): string {
  return MENSAGEM_DE_FALHA_AO_DONO;
}
