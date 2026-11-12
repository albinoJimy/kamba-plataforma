/**
 * O caso de uso da fila de revisão (KAM-089). Ver `./contrato.ts` para o desenho.
 *
 * ```text
 * abrir      porta de entrada: elegibilidade, quota, idempotência, SLA
 * decidir    aprovar | rejeitar | pedir_info | escalar, com as regras de quem
 * recorrer   um recurso por decisão; decide-o quem não decidiu a primeira
 * consultar  listar (sem PII, paginado), ver (mascarado), revelar, documento
 * lote       drenar a triagem, dar os alertas dos 80%, amostrar aprovações
 * ```
 *
 * ## O que uma decisão faz ao onboarding
 *
 * Só os tipos `kyc`, `categoria` e `duplicado` **bloqueiam** o onboarding. Um
 * deles rejeitado põe o onboarding em `rejeitado`. Aprovado, o onboarding passa
 * a `aprovado` **se** estiver em `em_revisao` **e** não houver outro caso
 * pendente que o bloqueie: um K1 aprovado não aprova uma categoria condicional
 * ainda por decidir. Um `pedir_info` num caso `kyc` devolve o onboarding a
 * `kyc_pendente`, para o dono poder carregar documentos — e o caso **continua
 * aberto**: o KYC volta a decidir, e um `k1_ok` não fecha o caso, que é o que
 * impede um documento limpo carregado depois de uma regra dura de aprovar sem
 * humano (o achado A2 do KAM-087, visto do outro lado).
 */

import { createHash } from "node:crypto";

import type {
  AvisoAoDono,
  Aviso,
  Alerta,
  Auditoria,
  CampoPessoal,
  CasoDeRevisao,
  ChaveDeScreening,
  Cifra,
  DadosPessoais,
  Decisao,
  DecisaoHumanaDeScreening,
  DecisaoRegistada,
  DocumentosDaRevisao,
  EstadoDoCaso,
  Evidencia,
  FiltroDaFila,
  Instancia,
  Limiares,
  MotivoDeRecusa,
  MotivoPublico,
  OnboardingsDaRevisao,
  Recomendacao,
  Relogio,
  RepositorioDeRevisao,
  Revisor,
  TipoDeCaso,
} from "./contrato.ts";
import {
  CasoInexistenteError,
  ESTADOS_PENDENTES,
  LIMIARES_POR_OMISSAO,
  MOTIVOS_PUBLICOS,
  PAPEIS,
  PRIORIDADES,
  RevisaoRecusadaError,
  TEXTO_DO_MOTIVO_PUBLICO,
  TIPOS_DE_CASO,
} from "./contrato.ts";
import { FERIADOS_POR_OMISSAO, calcularSla, inicioDoDiaEmLuanda, type Feriados } from "./sla.ts";

/**
 * As fases do onboarding em que um caso pode entrar na fila: depois do OTP. O
 * OTP só se pede depois do desafio anti-bot do registo (KAM-086), pelo que
 * «OTP validado» implica «anti-bot passado». As fases mortas também ficam fora:
 * o terceiro ilegível já rejeitou o caso sem humano (KAM-087, critério 6).
 */
export const FASES_ELEGIVEIS: readonly string[] = [
  "kyc_pendente",
  "em_revisao",
  "aprovado",
  "provisionando",
  "aguarda_es",
  "lista_espera",
  "aguarda_catalogo",
  "aguarda_teste",
  "activo",
];

/** Os tipos que bloqueiam o onboarding até serem decididos. */
export const TIPOS_QUE_BLOQUEIAM: readonly TipoDeCaso[] = ["kyc", "categoria", "duplicado"];

/** Os tipos cuja decisão é uma decisão humana de screening. */
const TIPOS_DE_SCREENING: readonly TipoDeCaso[] = ["categoria", "catalogo"];

export interface DependenciasDaRevisao {
  readonly repositorio: RepositorioDeRevisao;
  readonly onboardings: OnboardingsDaRevisao;
  readonly auditoria: Auditoria;
  readonly aviso: AvisoAoDono;
  readonly alerta: Alerta;
  readonly cifra: Cifra;
  readonly dados: DadosPessoais;
  readonly documentos: DocumentosDaRevisao;
  readonly screening: DecisaoHumanaDeScreening;
  readonly relogio?: Relogio;
  readonly limiares?: Limiares;
  readonly feriados?: Feriados;
  /** O dia em que a amostragem começou (o arranque do Piloto). Sem ele, não se amostra. */
  readonly inicioDaAmostragem?: Date | null;
}

/** O pedido de abertura. */
export interface PedidoDeAbertura {
  readonly tipo: TipoDeCaso;
  readonly tenantId: string;
  readonly onboardingId: string | null;
  readonly motivoCodigo: string;
  readonly motivoInterno: string;
  readonly motivoPublico: MotivoPublico;
  readonly evidencias: readonly Evidencia[];
  readonly recomendacao: Recomendacao | null;
  readonly prioridade: number;
}

export type ResultadoDaAbertura =
  | { readonly estado: "aberto" | "em_triagem_automatica"; readonly caso: CasoDeRevisao; readonly repetido: boolean }
  | { readonly estado: "nao_elegivel"; readonly fase: string | null };

export type ResultadoDaDecisao =
  | { readonly estado: "decidido"; readonly decisao: Decisao; readonly caso: CasoDeRevisao }
  | { readonly estado: "aguarda_segundo_revisor"; readonly caso: CasoDeRevisao }
  | { readonly estado: "em_analise" | "escalado"; readonly caso: CasoDeRevisao };

/** O que a consola mostra de um caso na lista. **Sem dados pessoais.** */
export interface ResumoDoCaso {
  readonly id: string;
  readonly tipo: TipoDeCaso;
  readonly estado: EstadoDoCaso;
  readonly prioridade: number;
  readonly motivoCodigo: string;
  readonly slaDueAt: Date;
}

/** O que a consola mostra de um caso aberto. Dados pessoais **mascarados**. */
export interface VistaDoCaso extends ResumoDoCaso {
  readonly motivoInterno: string;
  readonly motivoPublico: MotivoPublico;
  readonly recomendacao: Recomendacao | null;
  readonly evidencias: readonly Evidencia[];
  readonly onboardingId: string | null;
  readonly dados: Readonly<Record<CampoPessoal, string | null>>;
  readonly decisoes: readonly { readonly revisorId: string; readonly decisao: Decisao; readonly instancia: Instancia; readonly regra: string | null; readonly em: Date }[];
}

/**
 * Mascara um identificador: mostra os três últimos caracteres e tapa o resto.
 * Um valor de três ou menos caracteres tapa-se inteiro — os três últimos de um
 * valor curto são o valor.
 */
export function mascarar(valor: string): string {
  const limpo = valor.replace(/\s+/g, "");
  if (limpo.length <= 3) return "*".repeat(limpo.length);
  return `${"*".repeat(limpo.length - 3)}${limpo.slice(-3)}`;
}

/** O balde da amostragem de um onboarding, em `[0, 1)`. Determinístico: reentregar não muda a escolha. */
export function baldeDaAmostra(onboardingId: string): number {
  // Os quatro primeiros octetos do SHA-256 do identificador. Não é segredo: é
  // para que a mesma aprovação dê sempre a mesma resposta, e para que a
  // fracção seja a pedida mesmo com identificadores pouco aleatórios — um
  // FNV-1a deu 17% em vez de 20% sobre identificadores sequenciais.
  return createHash("sha256").update(onboardingId.toLowerCase(), "utf8").digest().readUInt32BE(0) / 0x1_0000_0000;
}

export class ServicoDeRevisao {
  readonly #d: DependenciasDaRevisao;
  readonly #l: Limiares;
  readonly #f: Feriados;
  readonly #agora: Relogio;

  constructor(d: DependenciasDaRevisao) {
    this.#d = d;
    this.#l = d.limiares ?? LIMIARES_POR_OMISSAO;
    this.#f = d.feriados ?? FERIADOS_POR_OMISSAO;
    this.#agora = d.relogio ?? (() => new Date());
  }

  // ------------------------------------------------------------------ abrir

  /**
   * Abre um caso, ou devolve o que já existe para a mesma chave.
   *
   * A ordem importa: a idempotência vem **antes** da quota, senão reentregar o
   * mesmo evento contava duas vezes contra a origem.
   */
  async abrir(p: PedidoDeAbertura): Promise<ResultadoDaAbertura> {
    if (!TIPOS_DE_CASO.includes(p.tipo)) throw new RangeError("tipo de caso desconhecido");
    if (!MOTIVOS_PUBLICOS.includes(p.motivoPublico)) throw new RangeError("motivo publico fora da lista");
    if (!Number.isInteger(p.prioridade) || p.prioridade < 1 || p.prioridade > 9) {
      throw new RangeError("prioridade fora de 1..9");
    }
    let origem: string | null = null;
    let interno = false;
    if (p.onboardingId !== null) {
      const o = await this.#d.onboardings.porId(p.onboardingId);
      if (o === null || o.tenantId !== p.tenantId) return { estado: "nao_elegivel", fase: null };
      if (!FASES_ELEGIVEIS.includes(o.fase)) return { estado: "nao_elegivel", fase: o.fase };
      origem = o.redeHmac ?? o.dispositivoHmac;
    } else {
      // Sem onboarding, o caso vem de dentro (T&S, saga, amostragem): não há
      // origem que um atacante controle, e a quota não se aplica.
      interno = true;
    }
    const agora = this.#agora();
    const naQuota =
      interno ||
      p.tipo === "auditoria" ||
      (await this.#d.repositorio.contarNaFilaDesde(origem, inicioDoDiaEmLuanda(agora))) <
        this.#l.quotaPorOrigemPorDia;
    const sla = calcularSla(agora, this.#f, this.#l.diasUteisDoSla, this.#l.fracaoDoAlerta);
    const { caso, repetido } = await this.#d.repositorio.abrir({
      tipo: p.tipo,
      onboardingId: p.onboardingId,
      tenantId: p.tenantId,
      motivoCodigo: p.motivoCodigo,
      motivoInterno: p.motivoInterno,
      motivoPublico: p.motivoPublico,
      evidencias: p.evidencias,
      recomendacao: p.recomendacao,
      estado: naQuota ? "aberto" : "em_triagem_automatica",
      prioridade: p.prioridade,
      filaEm: agora,
      ...sla,
    });
    if (!repetido && caso.estado === "em_triagem_automatica") {
      this.#d.alerta("quota_da_origem", { casoId: caso.id, tipo: caso.tipo });
    }
    return {
      estado: caso.estado === "em_triagem_automatica" ? "em_triagem_automatica" : "aberto",
      caso,
      repetido,
    };
  }

  // ---------------------------------------------------------------- decidir

  /**
   * Uma decisão de primeira instância.
   *
   * `regra` é o código da regra ou do motivo que o revisor invoca; `nota` é
   * texto livre do revisor, que vai **cifrado** e nunca para o dono.
   */
  async decidir(
    revisor: Revisor,
    casoId: string,
    decisao: Decisao,
    opcoes: { readonly regra?: string | null; readonly nota?: string | null; readonly motivoPublico?: MotivoPublico } = {},
  ): Promise<ResultadoDaDecisao> {
    const caso = await this.#autorizar(revisor, casoId);
    if (!["aberto", "em_analise", "escalado"].includes(caso.estado)) {
      return this.#recusar(revisor, caso, "estado_invalido");
    }
    if (caso.estado === "escalado" && !revisor.papeis.includes("ts_lider")) {
      return this.#recusar(revisor, caso, "so_lider");
    }
    if (decisao === "escalar" && caso.estado === "escalado") {
      return this.#recusar(revisor, caso, "estado_invalido");
    }
    if (opcoes.motivoPublico !== undefined && !MOTIVOS_PUBLICOS.includes(opcoes.motivoPublico)) {
      return this.#recusar(revisor, caso, "decisao_invalida");
    }
    const anteriores = await this.#d.repositorio.decisoes(casoId);
    const desta = anteriores.filter((x) => x.instancia === "primeira");

    if (decisao === "aprovar" && caso.prioridade <= this.#l.prioridadeDeRiscoAlto) {
      const aprovadores = this.#aprovadoresDesde(desta);
      if (aprovadores.has(revisor.id)) return this.#recusar(revisor, caso, "mesmo_revisor");
      if (aprovadores.size === 0) {
        await this.#registar(revisor, caso, decisao, "primeira", opcoes);
        const actual = caso.estado === "aberto" ? await this.#transitar(caso, "em_analise") : caso;
        return { estado: "aguarda_segundo_revisor", caso: actual };
      }
    }

    if (decisao === "escalar") {
      await this.#registar(revisor, caso, decisao, "primeira", opcoes);
      return { estado: "escalado", caso: await this.#transitar(caso, "escalado") };
    }
    if (decisao === "pedir_info") {
      await this.#registar(revisor, caso, decisao, "primeira", opcoes);
      const actual = caso.estado === "aberto" ? await this.#transitar(caso, "em_analise") : caso;
      if (caso.onboardingId !== null) {
        if (caso.tipo === "kyc") await this.#d.onboardings.marcarFase(caso.onboardingId, "kyc_pendente");
        await this.#avisar(caso, "pedir_info", "informacao_em_falta");
      }
      return { estado: "em_analise", caso: actual };
    }

    // aprovar (com o segundo revisor, se era preciso) ou rejeitar: fecha.
    await this.#registar(revisor, caso, decisao, "primeira", opcoes);
    const fechado = await this.#transitar(caso, "decidido");
    const publico = opcoes.motivoPublico ?? caso.motivoPublico;
    await this.#efeitos(fechado, decisao, revisor, publico, "primeira");
    return { estado: "decidido", decisao, caso: fechado };
  }

  /**
   * Abre o recurso de um caso decidido. **Um** por decisão: um caso
   * `decidido_final`, ou com uma decisão de recurso no registo, recusa.
   *
   * Quem pede o recurso é o dono, por um canal que não é desta fila (a rota do
   * dono não existe); a fila recebe o pedido já autenticado.
   */
  async abrirRecurso(casoId: string): Promise<CasoDeRevisao> {
    const caso = await this.#d.repositorio.porId(casoId);
    if (caso === null) throw new CasoInexistenteError();
    if (caso.estado !== "decidido") throw new RevisaoRecusadaError(
      caso.estado === "recurso_aberto" || caso.estado === "decidido_final" ? "recurso_ja_usado" : "estado_invalido",
    );
    const agora = this.#agora();
    const sla = calcularSla(agora, this.#f, this.#l.diasUteisDoSla, this.#l.fracaoDoAlerta);
    const ok = await this.#d.repositorio.transitar(caso.id, "decidido", "recurso_aberto", { ...sla, filaEm: agora });
    if (!ok) throw new RevisaoRecusadaError("recurso_ja_usado");
    return (await this.#d.repositorio.porId(caso.id))!;
  }

  /** Decide o recurso. Só `aprovar` ou `rejeitar`, e nunca por quem decidiu a primeira instância. */
  async decidirRecurso(
    revisor: Revisor,
    casoId: string,
    decisao: Decisao,
    opcoes: { readonly regra?: string | null; readonly nota?: string | null } = {},
  ): Promise<ResultadoDaDecisao> {
    const caso = await this.#autorizar(revisor, casoId);
    if (caso.estado !== "recurso_aberto") return this.#recusar(revisor, caso, "estado_invalido");
    if (decisao !== "aprovar" && decisao !== "rejeitar") return this.#recusar(revisor, caso, "decisao_invalida");
    const anteriores = await this.#d.repositorio.decisoes(casoId);
    if (anteriores.some((x) => x.instancia === "primeira" && x.revisorId === revisor.id)) {
      return this.#recusar(revisor, caso, "revisor_da_primeira_instancia");
    }
    const doRecurso = anteriores.filter((x) => x.instancia === "recurso");
    if (decisao === "aprovar" && caso.prioridade <= this.#l.prioridadeDeRiscoAlto) {
      const aprovadores = this.#aprovadoresDesde(doRecurso);
      if (aprovadores.has(revisor.id)) return this.#recusar(revisor, caso, "mesmo_revisor");
      if (aprovadores.size === 0) {
        await this.#registar(revisor, caso, decisao, "recurso", opcoes);
        return { estado: "aguarda_segundo_revisor", caso };
      }
    }
    await this.#registar(revisor, caso, decisao, "recurso", opcoes);
    const fechado = await this.#transitar(caso, "decidido_final");
    await this.#efeitos(fechado, decisao, revisor, caso.motivoPublico, "recurso");
    return { estado: "decidido", decisao, caso: fechado };
  }

  // -------------------------------------------------------------- consultar

  /** Uma página da fila. Sem dados pessoais, e com página máxima: não há exportação. */
  async listar(revisor: Revisor, filtro: FiltroDaFila = {}, pagina = 0): Promise<readonly ResumoDoCaso[]> {
    await this.#exigirIdentidade(revisor, null);
    const n = Math.max(0, Math.floor(pagina));
    const casos = await this.#d.repositorio.pagina(filtro, this.#l.paginaMaxima, n * this.#l.paginaMaxima);
    return casos.slice(0, this.#l.paginaMaxima).map(resumo);
  }

  /**
   * O caso, para decidir: motivo interno, evidências por referência, histórico
   * de decisões e os dados pessoais **mascarados**. Abrir um caso `aberto` passa-o
   * a `em_analise`.
   */
  async ver(revisor: Revisor, casoId: string): Promise<VistaDoCaso> {
    let caso = await this.#autorizar(revisor, casoId);
    if (caso.estado === "aberto") caso = await this.#transitar(caso, "em_analise");
    const dados = {} as Record<CampoPessoal, string | null>;
    for (const campo of ["nif", "numero_bi", "telefone"] as const) {
      const v = caso.onboardingId === null ? null : await this.#d.dados.ler(caso.onboardingId, campo);
      dados[campo] = v === null ? null : mascarar(v);
    }
    const decisoes = (await this.#d.repositorio.decisoes(casoId)).map((x) => ({
      revisorId: x.revisorId,
      decisao: x.decisao,
      instancia: x.instancia,
      regra: x.regra,
      em: x.em,
    }));
    return {
      ...resumo(caso),
      motivoInterno: caso.motivoInterno,
      motivoPublico: caso.motivoPublico,
      recomendacao: caso.recomendacao,
      evidencias: caso.evidencias,
      onboardingId: caso.onboardingId,
      dados,
      decisoes,
    };
  }

  /** Revela **um** campo em claro. O acesso fica no `audit_log` antes de o valor sair. */
  async revelar(revisor: Revisor, casoId: string, campo: CampoPessoal): Promise<string | null> {
    const caso = await this.#autorizar(revisor, casoId);
    if (caso.onboardingId === null) return null;
    await this.#d.auditoria.registar({
      accao: "review.acesso",
      tenantId: caso.tenantId,
      actorId: revisor.id,
      entidade: "onboarding_case",
      entidadeId: caso.onboardingId,
      detalhe: `revelar:${campo}`,
    });
    return this.#d.dados.ler(caso.onboardingId, campo);
  }

  /**
   * A URL de um documento de KYC do caso. O documento tem de ser uma evidência
   * **deste** caso: um revisor com o caso A aberto não pede o documento do caso
   * B pelo identificador. O acesso fica no `audit_log` antes de a URL existir,
   * e a URL vale ≤ 300 s (o KYC prende o TTL).
   */
  async urlDoDocumento(revisor: Revisor, casoId: string, verificacaoId: string): Promise<string> {
    const caso = await this.#autorizar(revisor, casoId);
    const deste = caso.evidencias.some((e) => e.tipo === "kyc_check" && e.ref === verificacaoId);
    if (!deste || caso.onboardingId === null) return this.#recusar(revisor, caso, "evidencia_alheia");
    const tenantId = caso.tenantId;
    const auditoria = this.#d.auditoria;
    return this.#d.documentos.url(revisor.id, caso.onboardingId, verificacaoId, {
      async anotarAcesso(a) {
        await auditoria.registar({
          accao: "review.acesso",
          tenantId,
          actorId: a.revisor,
          entidade: "kyc_check",
          entidadeId: a.verificacaoId,
          detalhe: "documento",
        });
      },
    });
  }

  // ------------------------------------------------------------------- lote

  /**
   * Passa casos da triagem para a vista humana, pela ordem de chegada, até a
   * quota do dia de cada origem. Corre num *job* (o excesso de ontem entra
   * hoje). O SLA conta a partir da entrada, não da criação.
   */
  async drenarTriagem(limite = 500): Promise<number> {
    const agora = this.#agora();
    const desde = inicioDoDiaEmLuanda(agora);
    let entraram = 0;
    for (const caso of await this.#d.repositorio.emTriagem(limite)) {
      const o = caso.onboardingId === null ? null : await this.#d.onboardings.porId(caso.onboardingId);
      const origem = o === null ? null : (o.redeHmac ?? o.dispositivoHmac);
      if ((await this.#d.repositorio.contarNaFilaDesde(origem, desde)) >= this.#l.quotaPorOrigemPorDia) continue;
      const sla = calcularSla(agora, this.#f, this.#l.diasUteisDoSla, this.#l.fracaoDoAlerta);
      if (await this.#d.repositorio.transitar(caso.id, "em_triagem_automatica", "aberto", { ...sla, filaEm: agora })) {
        entraram++;
      }
    }
    return entraram;
  }

  /** Dá o alerta dos 80% a cada caso pendente que o passou, uma vez. */
  async alertarSla(): Promise<number> {
    const agora = this.#agora();
    let n = 0;
    for (const caso of await this.#d.repositorio.alertasDevidos(agora)) {
      if (!ESTADOS_PENDENTES.includes(caso.estado)) continue;
      this.#d.alerta("sla_80", { casoId: caso.id, tipo: caso.tipo });
      await this.#d.repositorio.marcarAlertado(caso.id, agora);
      n++;
    }
    return n;
  }

  /**
   * Amostra uma aprovação **automática**: nas primeiras semanas (8, *proposta*)
   * desde o início da amostragem, 20% (*proposta*) geram um caso `auditoria`
   * de prioridade baixa. O resultado desses casos é a taxa de falsos aprovados.
   * Sem `inicioDaAmostragem`, não se amostra.
   */
  async amostrar(onboardingId: string, tenantId: string): Promise<ResultadoDaAbertura | null> {
    const inicio = this.#d.inicioDaAmostragem ?? null;
    if (inicio === null) return null;
    const agora = this.#agora();
    const fim = inicio.getTime() + this.#l.semanasDeAmostragem * 7 * 86_400_000;
    if (agora.getTime() < inicio.getTime() || agora.getTime() >= fim) return null;
    if (baldeDaAmostra(onboardingId) >= this.#l.fracaoDaAmostra) return null;
    return this.abrir({
      tipo: "auditoria",
      tenantId,
      onboardingId: null,
      motivoCodigo: `amostra:${onboardingId}`,
      motivoInterno: "amostra de aprovacao automatica",
      motivoPublico: "nao_foi_possivel_validar",
      evidencias: [{ tipo: "onboarding_case", ref: onboardingId }],
      recomendacao: "aprovar",
      prioridade: PRIORIDADES.auditoria,
    });
  }

  // ---------------------------------------------------------------- privado

  /** Identidade e papel; MFA. Uma recusa aqui também fica no `audit_log`. */
  async #exigirIdentidade(revisor: Revisor, caso: CasoDeRevisao | null): Promise<void> {
    const papel = revisor.papeis.some((p) => (PAPEIS as readonly string[]).includes(p));
    const motivo: MotivoDeRecusa | null = !papel ? "sem_papel" : !revisor.mfa ? "sem_mfa" : null;
    if (motivo === null) return;
    if (caso !== null) await this.#recusar(revisor, caso, motivo);
    throw new RevisaoRecusadaError(motivo);
  }

  /** Lê o caso, exige identidade e recusa quem é parte nele. */
  async #autorizar(revisor: Revisor, casoId: string): Promise<CasoDeRevisao> {
    const caso = await this.#d.repositorio.porId(casoId);
    if (caso === null) {
      await this.#exigirIdentidade(revisor, null);
      throw new CasoInexistenteError();
    }
    await this.#exigirIdentidade(revisor, caso);
    if (caso.onboardingId !== null) {
      const o = await this.#d.onboardings.porId(caso.onboardingId);
      const parte =
        o !== null &&
        ((revisor.nifHmac !== null && revisor.nifHmac === o.nifHmac) ||
          (revisor.telefoneHmac !== null && revisor.telefoneHmac === o.telefoneHmac));
      if (parte) return this.#recusar(revisor, caso, "parte_no_caso");
    }
    return caso;
  }

  async #recusar(revisor: Revisor, caso: CasoDeRevisao, motivo: MotivoDeRecusa): Promise<never> {
    await this.#d.auditoria.registar({
      accao: "review.recusa",
      tenantId: caso.tenantId,
      actorId: revisor.id === "" ? "desconhecido" : revisor.id,
      entidade: "review_case",
      entidadeId: caso.id,
      detalhe: motivo,
    });
    throw new RevisaoRecusadaError(motivo);
  }

  /**
   * Quem aprovou nesta instância **depois** da última decisão que não foi
   * aprovação. Um `pedir_info` entre duas aprovações recomeça a contagem: a
   * segunda aprovação tem de ser sobre o mesmo processo que a primeira viu.
   */
  #aprovadoresDesde(linhas: readonly DecisaoRegistada[]): Set<string> {
    const s = new Set<string>();
    for (const x of linhas) {
      if (x.decisao === "aprovar") s.add(x.revisorId);
      else s.clear();
    }
    return s;
  }

  async #registar(
    revisor: Revisor,
    caso: CasoDeRevisao,
    decisao: Decisao,
    instancia: Instancia,
    opcoes: { readonly regra?: string | null; readonly nota?: string | null },
  ): Promise<void> {
    const nota =
      opcoes.nota === undefined || opcoes.nota === null || opcoes.nota === ""
        ? null
        : await this.#d.cifra.cifrar(new TextEncoder().encode(opcoes.nota), `review_case:${caso.id}`);
    await this.#d.repositorio.registarDecisao({
      casoId: caso.id,
      revisorId: revisor.id,
      decisao,
      instancia,
      regra: opcoes.regra ?? null,
      notaCifrada: nota,
    });
  }

  async #transitar(caso: CasoDeRevisao, para: EstadoDoCaso): Promise<CasoDeRevisao> {
    if (!(await this.#d.repositorio.transitar(caso.id, caso.estado, para))) {
      // Outra decisão chegou primeiro. A desta já está no registo, e o
      // registo é a verdade sobre quem decidiu o quê; o estado é de quem ganhou.
      throw new RevisaoRecusadaError("estado_invalido");
    }
    return (await this.#d.repositorio.porId(caso.id))!;
  }

  /** O que a decisão final faz ao onboarding, ao screening e ao dono. Ver a nota do módulo. */
  async #efeitos(
    caso: CasoDeRevisao,
    decisao: Decisao,
    revisor: Revisor,
    motivoPublico: MotivoPublico,
    instancia: Instancia,
  ): Promise<void> {
    if (TIPOS_DE_SCREENING.includes(caso.tipo)) {
      for (const chave of chavesDeScreening(caso.evidencias)) {
        await this.#d.screening.gravar({
          tenantId: caso.tenantId,
          onboardingId: caso.onboardingId,
          chave,
          decisao: decisao === "aprovar" ? "permitida" : "bloqueada",
          revisorId: revisor.id,
        });
      }
    }
    if (caso.onboardingId === null || !TIPOS_QUE_BLOQUEIAM.includes(caso.tipo)) return;
    const aviso: Aviso = instancia === "recurso" ? "recurso_decidido" : decisao === "aprovar" ? "aprovado" : "rejeitado";
    if (decisao === "rejeitar") {
      await this.#d.onboardings.marcarFase(caso.onboardingId, "rejeitado");
      await this.#avisar(caso, aviso, motivoPublico);
      return;
    }
    const o = await this.#d.onboardings.porId(caso.onboardingId);
    const outros = (await this.#d.repositorio.pendentesDoOnboarding(caso.onboardingId)).filter(
      (x) => x.id !== caso.id && TIPOS_QUE_BLOQUEIAM.includes(x.tipo),
    );
    const fase = o?.fase;
    // `kyc_pendente` só conta para o próprio caso `kyc`: é onde um `pedir_info`
    // o deixou. Uma categoria aprovada com o K1 ainda por decidir não aprova o
    // onboarding — o KYC não tem caso pendente a bloquear, e passava.
    const desbloqueavel =
      fase === "em_revisao" ||
      (caso.tipo === "kyc" && fase === "kyc_pendente") ||
      (instancia === "recurso" && fase === "rejeitado");
    if (outros.length === 0 && desbloqueavel) {
      await this.#d.onboardings.marcarFase(caso.onboardingId, "aprovado");
    }
    await this.#avisar(caso, aviso, null);
  }

  async #avisar(caso: CasoDeRevisao, aviso: Aviso, motivo: MotivoPublico | null): Promise<void> {
    if (caso.onboardingId === null) return;
    // Por omissão o SMS ao telefone registado. Nunca o número da loja.
    await this.#d.aviso.avisar({ onboardingId: caso.onboardingId, via: "sms", aviso, motivoPublico: motivo });
  }
}

function resumo(c: CasoDeRevisao): ResumoDoCaso {
  return {
    id: c.id,
    tipo: c.tipo,
    estado: c.estado,
    prioridade: c.prioridade,
    motivoCodigo: c.motivoCodigo,
    slaDueAt: c.slaDueAt,
  };
}

/** As chaves de screening guardadas como evidência (`tipo = 'screening_decision'`, `ref` em JSON). */
export function chavesDeScreening(evidencias: readonly Evidencia[]): ChaveDeScreening[] {
  const chaves: ChaveDeScreening[] = [];
  for (const e of evidencias) {
    if (e.tipo !== "screening_decision") continue;
    const c = JSON.parse(e.ref) as Partial<ChaveDeScreening>;
    if (
      (c.sujeitoTipo === "categoria" || c.sujeitoTipo === "produto") &&
      typeof c.sujeitoRef === "string" &&
      typeof c.versaoPolitica === "string" &&
      typeof c.conteudoSha256 === "string" &&
      /^[0-9a-f]{64}$/.test(c.conteudoSha256)
    ) {
      chaves.push({
        sujeitoTipo: c.sujeitoTipo,
        sujeitoRef: c.sujeitoRef,
        versaoPolitica: c.versaoPolitica,
        conteudoSha256: c.conteudoSha256,
      });
    }
  }
  return chaves;
}

/** O texto que o dono lê para um motivo público. */
export function textoParaODono(motivo: MotivoPublico): string {
  return TEXTO_DO_MOTIVO_PUBLICO[motivo];
}
