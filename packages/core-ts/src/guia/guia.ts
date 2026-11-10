/**
 * O passo guiado do Embedded Signup: o serviço (KAM-093).
 *
 * ## A ordem, e o que cada passo recusa
 *
 *     abrir        o caso existe e está em `aguarda_es` (critério 1); a sessão
 *                  é de quem chama, e verifica-a a rota
 *     preflight    os sete itens, gravados (critério 2)
 *     iniciar      pré-voo cumprido + `CapacityGate.reserve` (critério 8) e só
 *                  então a configuração do popup v4 (critério 1)
 *     cancelar     popup fechado ⇒ `abandonado` (critério 5)
 *     concluir     o `FINISH` do popup ⇒ `LigadorDeCanal` (KAM-016). Repetir
 *                  não liga outra vez: *compare-and-set* sobre o estado
 *     confirmarNumero   o `display_phone_number` do primeiro webhook contra o
 *                  HMAC do telefone do OTP (critério 4)
 *     sincronizacao     os sinais do KAM-017: lembrete às 12 h, falha às 24 h,
 *                  conclusão — com ou sem histórico (2593109) (critério 6)
 *     desligado    `PARTNER_REMOVED` ⇒ os passos de reconexão por SMS/e-mail,
 *                  com a ligação de retoma (critério 7; o alarme é do KAM-115)
 *     verificarPagamento   o gate `meta_pagamento`, repetível sem refazer o ES
 *                  (critério 3)
 *
 * ## O `tenant_id` sai do caso, nunca do corpo
 *
 * O popup devolve `code`, `waba_id` e `phone_number_id`. O `tenant_id` que vai
 * para o `POST /internal/channels` é o **pré-alocado no caso** que a sessão
 * prova — a regra do ADR-010 que o `canais.ts` do GWY cita ao dizer que este
 * corpo «não é texto de utilizador». Se viesse do corpo, a página era o sítio
 * onde um dono ligava um número a outra loja.
 *
 * ## O que «o canal não é encaminhado» quer dizer aqui
 *
 * O KAM-016 cria o canal `pendente`, e um canal pendente não recebe tráfego
 * até o KAM-092/094 o activar; activar exige o `meta_es` verde. Um número
 * divergente deixa o `meta_es` **vermelho**, abre o `review_case` e prende o
 * guia em `falhado` com um motivo que a página não desprende
 * (`MOTIVOS_QUE_PRENDEM`). Não se compensa o canal daqui: a compensação é do
 * KAM-016, e quem decide se o número volta a outra loja é a revisão.
 */

import type { Logger } from "../logger/index.ts";
import type { RepositorioDeCasos } from "../inscricao/contrato.ts";
import { cunharReferencia } from "../inscricao/sessao.ts";
import {
  EVENTO_FINAL_DE_COEXISTENCIA,
  FEATURE_TYPE_DE_COEXISTENCIA,
  PRAZO_DE_ABANDONO_MIN,
  SESSION_INFO_VERSION,
} from "../onboarding/contrato.ts";
import {
  type Atestados,
  type AvisoDoGuia,
  type CapacityGate,
  type DetectorDePagamento,
  type EstadoDoGuia,
  type EstadoDoPagamento,
  type EstadoGuardado,
  FEATURE_TYPE_CLOUD_ONLY,
  type FilaDeRevisao,
  type GatesDoOnboarding,
  GuiaRecusadoError,
  type LigadorDeCanal,
  type MensagemAoDono,
  type MotivoDeFalha,
  MOTIVOS_QUE_PRENDEM,
  type Preflight,
  type RepositorioDoGuia,
  type Rota,
  transicaoDoGuiaValida,
} from "./contrato.ts";
import { numeroCoincide } from "./numero.ts";
import { avaliarPreflight } from "./preflight.ts";

/** A configuração do popup v4, como a página a passa ao `FB.login`. */
export interface ConfiguracaoDoPopup {
  readonly config_id: string;
  readonly response_type: "code";
  readonly override_default_response_type: true;
  readonly extras: {
    readonly sessionInfoVersion: string;
    readonly featureType?: string;
  };
  /** O evento com que o popup fecha, para o *session logging* da página. */
  readonly evento_final: string;
}

/**
 * O que o popup devolve à página, e a página manda ao `concluir`.
 *
 * **Sem `session_info`**: compõe-o o guia (`sessionInfo`), e o que a página
 * mandasse era só o eco da configuração que o servidor lhe deu.
 */
export interface Finish {
  readonly code: unknown;
  readonly waba_id: unknown;
  readonly phone_number_id: unknown;
}

/** Os estados que a sincronização do KAM-017 comunica ao guia. */
export type SinalDeSincronizacao = "a_sincronizar" | "lembrete_12h" | "concluida" | "vencida_24h";

/** As dependências do serviço. */
export interface Dependencias {
  readonly casos: RepositorioDeCasos;
  readonly repositorio: RepositorioDoGuia;
  readonly capacidade: CapacityGate;
  readonly ligador: LigadorDeCanal;
  readonly gates: GatesDoOnboarding;
  readonly revisao: FilaDeRevisao;
  readonly pagamento: DetectorDePagamento;
  readonly aviso: AvisoDoGuia;
  /** O anel do *pepper* da inscrição: o mesmo que fez o `telefoneHmac` do caso. */
  readonly anelDoPepper: readonly (Uint8Array | null)[];
  /** A chave **actual** da assinatura: cunha a ligação de retoma. */
  readonly chaveDaAssinatura: Uint8Array;
  /** A origem pública do `onboarding-web`, para a ligação de retoma. */
  readonly origem: string;
  /** O `config_id` do ES v4. Identificador público da Meta, não segredo. */
  readonly configId: string;
  /** Os termos bloqueados do KAM-088, se houver. Ver o `Factos` do pré-voo. */
  readonly termosBloqueados?: readonly string[];
  readonly relogio?: () => Date;
  readonly log?: Logger;
}

/** O que o `iniciar` devolve. */
export type Inicio =
  | { readonly desfecho: "popup"; readonly configuracao: ConfiguracaoDoPopup; readonly rota: Rota }
  | { readonly desfecho: "lista_espera" };

/** O que o `concluir` devolve. */
export interface Conclusao {
  readonly estado: EstadoDoGuia;
  /** `false` quando este `FINISH` já tinha sido tratado. */
  readonly novo: boolean;
}

/** O que o `verificarPagamento` devolve. */
export interface VerificacaoDoPagamento {
  readonly estado: EstadoDoPagamento;
  readonly verde: boolean;
  /**
   * A alternativa quando não há cartão: as mensagens pagas por MPS (D5). É um
   * código que a página traduz em texto, e não texto: o canon da D5 ainda é
   * proposta, e a página é que a explica.
   */
  readonly alternativa: "mps" | null;
}

function textoCurto(valor: unknown): string | null {
  return typeof valor === "string" && valor.length > 0 && valor.length <= 512 ? valor : null;
}

/** O serviço. */
export class PassoGuiado {
  readonly #d: Dependencias;
  readonly #agora: () => Date;

  constructor(dependencias: Dependencias) {
    this.#d = dependencias;
    this.#agora = dependencias.relogio ?? ((): Date => new Date());
  }

  /** A página abre? **O critério 1**, na metade que não é a sessão. */
  async abrir(onboardingId: string): Promise<EstadoGuardado> {
    const caso = await this.#d.casos.porId(onboardingId);
    if (caso === null) throw new GuiaRecusadoError("sem_caso");
    if (caso.fase !== "aguarda_es") throw new GuiaRecusadoError("fase_errada");
    return this.#d.repositorio.abrir(onboardingId);
  }

  /** Avalia e grava o pré-voo. **O critério 2.** */
  async preflight(onboardingId: string, atestados: Atestados): Promise<Preflight> {
    await this.abrir(onboardingId);
    const caso = await this.#d.casos.porId(onboardingId);
    const telefone = await this.#d.casos.telefoneDe(onboardingId);
    const preflight = avaliarPreflight(
      atestados,
      {
        linha: telefone?.linha ?? "desconhecido",
        // **Um caso em `aguarda_es` já passou o *screening***: o `aprovado`
        // que o precede exige-o (KAM-092, o agregador de KYC + *screening* +
        // aceite). O item mostra-o; se a fase mentisse, o defeito era a fase.
        screening: "aprovada",
        displayName: caso?.nomeNegocio ?? "",
        termosBloqueados: this.#d.termosBloqueados ?? [],
      },
      this.#agora(),
    );
    await this.#d.repositorio.gravarPreflight(onboardingId, preflight);
    return preflight;
  }

  /**
   * Abre o popup, ou devolve `lista_espera`. **Os critérios 1, 5 e 8.**
   *
   * A reserva vem **antes** da transição, e não depois: reservar depois de
   * passar a `iniciado` deixava um caso em `iniciado` sem lugar, e a página
   * abria o popup a quem a Meta ia recusar.
   */
  async iniciar(onboardingId: string): Promise<Inicio> {
    const guia = await this.abrir(onboardingId);
    const preflight = guia.preflight;
    if (preflight === null) throw new GuiaRecusadoError("preflight_em_falta");
    if (!preflight.podeAbrir) throw new GuiaRecusadoError("preflight_por_cumprir");
    if (guia.estado === "falhado" && guia.motivo !== null && MOTIVOS_QUE_PRENDEM.includes(guia.motivo)) {
      throw new GuiaRecusadoError("preso_em_revisao");
    }
    if (guia.estado !== "iniciado" && !transicaoDoGuiaValida(guia.estado, "iniciado")) {
      throw new GuiaRecusadoError("estado_errado");
    }
    if ((await this.#d.capacidade.reserve(onboardingId)) === "lista_espera") {
      this.#d.log?.info({ outcome: "es_lista_espera" });
      return { desfecho: "lista_espera" };
    }
    if (guia.estado !== "iniciado") {
      // **Uma tentativa nova começa limpa.** Voltar de `falhado`, `desligado`
      // ou `abandonado` repõe os dois factos do `verificado` e esquece o
      // número da tentativa anterior: sem isto, uma reconexão com **outro**
      // número herdava o `numeroConfirmado` do antigo e chegava a `verificado`
      // sem nunca ser comparada. Achado da revisão adversarial.
      const passou = await this.#d.repositorio.transitar(onboardingId, guia.estado, "iniciado", {
        iniciadoEm: this.#agora(),
        motivo: null,
        tentativaId: null,
        phoneNumberId: null,
        wabaId: null,
        numeroConfirmado: false,
        sincronizado: false,
      });
      if (!passou) throw new GuiaRecusadoError("estado_errado");
    }
    return { desfecho: "popup", configuracao: this.configuracao(preflight.rota), rota: preflight.rota };
  }

  /**
   * A configuração do popup v4. Só v4: `sessionInfoVersion` "3" e, em
   * coexistência, o `featureType` do `E1` §3. Não há outra versão no código.
   */
  configuracao(rota: Rota): ConfiguracaoDoPopup {
    return {
      config_id: this.#d.configId,
      response_type: "code",
      override_default_response_type: true,
      extras:
        rota === "coexistencia"
          ? { sessionInfoVersion: SESSION_INFO_VERSION, featureType: FEATURE_TYPE_DE_COEXISTENCIA }
          : { sessionInfoVersion: SESSION_INFO_VERSION },
      evento_final: EVENTO_FINAL_DE_COEXISTENCIA,
    };
  }

  /** Popup fechado sem `FINISH`. **O critério 5.** Idempotente. */
  async cancelar(onboardingId: string): Promise<EstadoDoGuia> {
    await this.abrir(onboardingId);
    if (await this.#d.repositorio.transitar(onboardingId, "iniciado", "abandonado", {})) {
      await this.#d.capacidade.release(onboardingId);
    }
    return (await this.#d.repositorio.ler(onboardingId))?.estado ?? "pre_voo";
  }

  /**
   * Passa a `abandonado` os popups abertos há mais de 30 minutos. Devolve
   * quantos. O prazo entra por parâmetro, como no `abandonarVencidas` do
   * KAM-016, para um ensaio medir a fronteira sem esperar meia hora.
   */
  async abandonarVencidos(prazoMin: number = PRAZO_DE_ABANDONO_MIN): Promise<number> {
    const antes = new Date(this.#agora().getTime() - prazoMin * 60_000);
    let n = 0;
    for (const id of await this.#d.repositorio.iniciadosAntesDe(antes)) {
      if (await this.#d.repositorio.transitar(id, "iniciado", "abandonado", {})) {
        await this.#d.capacidade.release(id);
        n += 1;
      }
    }
    if (n > 0) this.#d.log?.info({ outcome: "es_popups_abandonados" });
    return n;
  }

  /**
   * O `FINISH` do popup. **Os critérios 1, 5 e o «FINISH 2× ⇒ 1 canal».**
   *
   * Duas barreiras contra a repetição, e são as duas precisas: o estado tem de
   * ser `iniciado` para se chamar o ligador — um segundo `FINISH` encontra
   * `subscrito` e devolve-o sem ligar —, e se dois chegarem ao mesmo tempo e
   * passarem os dois a leitura, o KAM-016 deduplica por `(tenant, waba)` e o
   * *compare-and-set* do `iniciado → es_concluido` deixa passar só um.
   */
  async concluir(onboardingId: string, finish: Finish): Promise<Conclusao> {
    const guia = await this.abrir(onboardingId);
    const caso = await this.#d.casos.porId(onboardingId);
    const code = textoCurto(finish.code);
    const wabaId = textoCurto(finish.waba_id);
    const phoneNumberId = textoCurto(finish.phone_number_id);
    if (caso === null || code === null || wabaId === null || phoneNumberId === null) {
      throw new GuiaRecusadoError("estado_errado");
    }
    if (guia.estado !== "iniciado") {
      // Já tratado: o mesmo número devolve o estado; outro número é recusado,
      // porque um segundo `FINISH` com outro `phone_number_id` não é repetição.
      if (guia.phoneNumberId === phoneNumberId) return { estado: guia.estado, novo: false };
      throw new GuiaRecusadoError("estado_errado");
    }
    // **O FINISH reclama-se ANTES de se ligar**, e é um achado da revisão
    // adversarial: com o *compare-and-set* depois do `ligar()`, o temporizador
    // dos 30 min podia passar o guia a `abandonado` enquanto a Meta respondia —
    // o canal nascia, a reserva era devolvida, e o guia ficava sem
    // `phone_number_id`, pelo que os webhooks desse número eram ignorados e o
    // número **nunca** era conferido. Reclamado aqui, o temporizador já não o
    // vê em `iniciado`, e um segundo `FINISH` concorrente perde antes de falar
    // com o GWY.
    const reclamou = await this.#d.repositorio.transitar(onboardingId, "iniciado", "es_concluido", {
      phoneNumberId,
      wabaId,
    });
    if (!reclamou) {
      const agora = await this.#d.repositorio.ler(onboardingId);
      return { estado: agora?.estado ?? "iniciado", novo: false };
    }
    const rota = guia.preflight?.rota ?? "coexistencia";
    const resultado = await this.#d.ligador.ligar({
      tenant_id: caso.tenantId,
      code,
      waba_id: wabaId,
      phone_number_id: phoneNumberId,
      session_info: this.sessionInfo(rota),
    });
    if (resultado.desfecho === "lista_espera" || resultado.desfecho === "recusado") {
      await this.#falhar(
        onboardingId,
        "es_concluido",
        resultado.desfecho === "lista_espera" ? "tecto_da_meta" : "ligacao_recusada",
      );
      await this.#d.capacidade.release(onboardingId);
      return { estado: "falhado", novo: true };
    }
    // O KAM-016 devolve a tentativa já em `subscrito`: a subscrição dos onze
    // campos e a leitura de confirmação correm dentro do `ligar()`.
    await this.#d.repositorio.transitar(onboardingId, "es_concluido", "subscrito", {
      tentativaId: resultado.tentativaId,
      // Em `cloud_only` não há histórico a sincronizar.
      ...(rota === "cloud_only" ? { sincronizado: true } : {}),
    });
    // Um webhook do número pode ter chegado enquanto a Meta respondia: o
    // número já confirmado, em `cloud_only`, basta para `verificado`.
    await this.#talvezVerificar(onboardingId);
    this.#d.log?.info({ outcome: "es_concluido" });
    const depois = await this.#d.repositorio.ler(onboardingId);
    return { estado: depois?.estado ?? "subscrito", novo: true };
  }

  /**
   * O `session_info` que segue para o KAM-016, **composto pelo guia**.
   *
   * Não se repassa o que a página manda: a página só pode ecoar a configuração
   * que o servidor lhe deu, e a forma do que o popup devolve é NÃO VERIFICADA.
   * Composto aqui, a partir da rota que o pré-voo gravou, diz o que o guia de
   * facto abriu — e a rota `cloud_only` leva a marca `FEATURE_TYPE_CLOUD_ONLY`,
   * sem a qual o `modoDoSessionInfo` a recusava.
   */
  sessionInfo(rota: Rota): Readonly<Record<string, unknown>> {
    return {
      sessionInfoVersion: SESSION_INFO_VERSION,
      extras: {
        featureType: rota === "coexistencia" ? FEATURE_TYPE_DE_COEXISTENCIA : FEATURE_TYPE_CLOUD_ONLY,
      },
    };
  }

  /**
   * O número ligado é o do OTP? **O critério 4.**
   *
   * Chamado com o `display_phone_number` do primeiro webhook que chega para
   * este `phone_number_id` (o `metadata` de todo o `value`, `E1` §2). Devolve
   * `null` quando o número não é de nenhum guia, `true` quando coincide e
   * `false` quando não coincide — e aí o guia já está preso.
   */
  async confirmarNumero(phoneNumberId: string, displayPhoneNumber: unknown): Promise<boolean | null> {
    const id = await this.#d.repositorio.porPhoneNumberId(phoneNumberId);
    if (id === null) return null;
    const caso = await this.#d.casos.porId(id);
    const guia = await this.#d.repositorio.ler(id);
    if (caso === null || guia === null) return null;
    // **Compara-se sempre, e não só a primeira vez.** O `numeroConfirmado`
    // repõe-se a cada volta a `iniciado` (ver o `iniciar`), mas a comparação
    // é barata e um `return true` por memória era o atalho que deixava uma
    // reconexão com outro número herdar a confirmação do antigo. Achado da
    // revisão adversarial.
    if (numeroCoincide(displayPhoneNumber, caso.telefoneHmac, this.#d.anelDoPepper)) {
      if (!guia.numeroConfirmado) await this.#d.repositorio.marcar(id, "numeroConfirmado");
      await this.#talvezVerificar(id);
      return true;
    }
    await this.#prender(id);
    await this.#d.revisao.abrir(id, "es_falhado", "numero_divergente");
    this.#d.log?.warn({ outcome: "es_numero_divergente" });
    return false;
  }

  /**
   * Põe o guia em `falhado` com `numero_divergente`, **de qualquer estado**.
   *
   * A prisão sobrepõe-se à matriz, e é um achado da revisão adversarial: com o
   * `#falhar`, um guia que já estivesse `falhado` por sincronização vencida
   * ficava com esse motivo — que a página desprende —, e o dono com o número
   * alheio voltava a abrir o popup com o `review_case` ainda aberto. O mesmo
   * para `desligado` e `abandonado`, de onde a matriz não leva a `falhado`.
   */
  async #prender(id: string): Promise<void> {
    for (let tentativa = 0; tentativa < 4; tentativa += 1) {
      const guia = await this.#d.repositorio.ler(id);
      if (guia === null) return;
      if (guia.estado === "falhado" && guia.motivo === "numero_divergente") break;
      if (await this.#d.repositorio.transitar(id, guia.estado, "falhado", { motivo: "numero_divergente" })) break;
    }
    await this.#d.gates.marcar(id, "meta_es", false, "numero_divergente");
  }

  /** Um sinal da sincronização do KAM-017. **O critério 6.** */
  async sincronizacao(phoneNumberId: string, sinal: SinalDeSincronizacao): Promise<EstadoDoGuia | null> {
    const id = await this.#d.repositorio.porPhoneNumberId(phoneNumberId);
    if (id === null) return null;
    const guia = await this.#d.repositorio.ler(id);
    if (guia === null) return null;
    switch (sinal) {
      case "a_sincronizar":
        await this.#d.repositorio.transitar(id, "subscrito", "a_sincronizar", {});
        break;
      case "lembrete_12h":
        await this.#avisar(id, "sincronizacao_lembrete");
        break;
      case "concluida":
        // Com ou sem histórico: o 2593109 é o KAM-017 a concluir **sem**
        // histórico, e chega aqui como uma conclusão igual às outras.
        await this.#d.repositorio.marcar(id, "sincronizado");
        await this.#talvezVerificar(id);
        break;
      case "vencida_24h":
        // O *offboard* é do KAM-017 (`varrerPrazos` devolve-o); o alerta a T2
        // é a métrica e o alerta dele. O que é deste guia é dizer ao dono que
        // repete o ES, e deixar a página pronta para isso.
        await this.#falhar(id, guia.estado, "sincronizacao_vencida");
        await this.#avisar(id, "sincronizacao_falhou");
        this.#d.log?.error({ outcome: "es_sincronizacao_vencida" });
        break;
    }
    return (await this.#d.repositorio.ler(id))?.estado ?? null;
  }

  /**
   * `PARTNER_REMOVED` ou ES desligado. **O critério 7.**
   *
   * Os passos de reconexão saem por SMS ou e-mail com a ligação de retoma, e
   * **nunca** pelo número da loja: é esse número que acabou de ser desligado,
   * e a porta `AvisoDoGuia` não tem como mandar por WhatsApp. O alarme «o seu
   * canal caiu» é do KAM-115, que já o manda por e-mail; esta mensagem é a que
   * diz como voltar. O ES refaz-se pela mesma página, sem registo novo:
   * `desligado → iniciado`.
   */
  async desligado(phoneNumberId: string): Promise<boolean> {
    const id = await this.#d.repositorio.porPhoneNumberId(phoneNumberId);
    if (id === null) return false;
    const guia = await this.#d.repositorio.ler(id);
    if (guia === null || !transicaoDoGuiaValida(guia.estado, "desligado")) return false;
    if (!(await this.#d.repositorio.transitar(id, guia.estado, "desligado", {}))) return false;
    await this.#d.gates.marcar(id, "meta_es", false, "desligado");
    await this.#avisar(id, "reconectar");
    this.#d.log?.warn({ outcome: "es_canal_desligado" });
    return true;
  }

  /**
   * O gate `meta_pagamento`. **O critério 3.** Repetível, e nunca toca no ES.
   *
   * Vermelho em tudo o que não é `detectado`: o critério diz «sem método de
   * pagamento **detectado**», e `desconhecido` não é detectado.
   */
  async verificarPagamento(onboardingId: string): Promise<VerificacaoDoPagamento> {
    const guia = await this.abrir(onboardingId);
    const estado: EstadoDoPagamento =
      guia.wabaId === null ? "desconhecido" : await this.#d.pagamento.verificar(guia.wabaId);
    const verde = estado === "detectado";
    await this.#d.gates.marcar(onboardingId, "meta_pagamento", verde, estado);
    if (verde) await this.#talvezPronto(onboardingId);
    return { estado, verde, alternativa: verde ? null : "mps" };
  }

  /** A ligação de retoma deste caso. Não autentica: a página exige a sessão. */
  ligacaoDeRetoma(onboardingId: string): string {
    const r = cunharReferencia("retoma", onboardingId, this.#d.chaveDaAssinatura, this.#agora);
    return `${this.#d.origem}/ligar?r=${encodeURIComponent(r)}`;
  }

  async #avisar(onboardingId: string, mensagem: MensagemAoDono): Promise<void> {
    await this.#d.aviso.avisar(onboardingId, mensagem, this.ligacaoDeRetoma(onboardingId));
  }

  async #falhar(onboardingId: string, de: EstadoDoGuia, motivo: MotivoDeFalha): Promise<void> {
    if (transicaoDoGuiaValida(de, "falhado")) {
      await this.#d.repositorio.transitar(onboardingId, de, "falhado", { motivo });
    }
    await this.#d.gates.marcar(onboardingId, "meta_es", false, motivo);
  }

  /** `verificado` quando os dois factos estão: número confirmado e sincronizado. */
  async #talvezVerificar(onboardingId: string): Promise<void> {
    const guia = await this.#d.repositorio.ler(onboardingId);
    if (guia === null || !guia.numeroConfirmado || !guia.sincronizado) return;
    if (guia.estado !== "subscrito" && guia.estado !== "a_sincronizar") return;
    if (await this.#d.repositorio.transitar(onboardingId, guia.estado, "verificado", {})) {
      await this.#d.gates.marcar(onboardingId, "meta_es", true, "sincronizado_e_verificado");
      await this.#talvezPronto(onboardingId);
    }
  }

  /** `pronto` quando o `meta_es` e o `meta_pagamento` estão verdes. */
  async #talvezPronto(onboardingId: string): Promise<void> {
    const guia = await this.#d.repositorio.ler(onboardingId);
    if (guia?.estado !== "verificado" || guia.wabaId === null) return;
    if ((await this.#d.pagamento.verificar(guia.wabaId)) !== "detectado") return;
    await this.#d.repositorio.transitar(onboardingId, "verificado", "pronto", {});
  }
}
