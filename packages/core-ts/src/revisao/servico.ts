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
 * a `aprovado` **se** estiver em `em_revisao` **e** nenhum outro caso que o
 * bloqueie estiver pendente ou rejeitado: um K1 aprovado não aprova uma
 * categoria condicional ainda por decidir. Um `pedir_info` num caso `kyc` devolve o onboarding a
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
  EfeitosPorReaplicar,
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
  DECISOES,
  EfeitoPorAplicarError,
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
  /**
   * Onde se marca um caso com efeitos por aplicar (KAM-198). Com ela, o serviço
   * marca **antes** de correr os efeitos e resolve **depois** de correrem todos:
   * um processo que morra a meio deixa a marca, e o ciclo reaplica-a. Sem ela,
   * só o `EfeitoPorAplicarError` diz a quem chamou que ficou um efeito por aplicar.
   */
  readonly efeitos?: EfeitosPorReaplicar;
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
  | {
      readonly estado: "aberto" | "em_triagem_automatica" | "ja_decidido";
      readonly caso: CasoDeRevisao;
      readonly repetido: boolean;
    }
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
  /** Um trinco por chave de quota: as aberturas da mesma origem correm em série. */
  readonly #trincos = new Map<string, Promise<void>>();

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
   * **A quota.** Um caso com onboarding conta contra a sua origem (o prefixo
   * de IP, ou o dispositivo); um caso sem onboarding conta contra o seu tenant,
   * porque o conteúdo de um produto é do tenant e uma `condicional` por produto
   * era a forma de inundar a fila sem passar pelo registo. Só a `auditoria`
   * (a amostragem, que é nossa) fica fora.
   *
   * **A contagem e a inserção correm em série por chave de quota**, neste
   * processo: duzentas aberturas em paralelo da mesma origem davam mais de
   * vinte casos abertos, porque contavam todas antes de alguma inserir. **E
   * entre processos** (KAM-198): com um repositório que tranca (`emTrinco`, o
   * `pg_advisory_xact_lock` do adaptador SQL), a contagem e a inserção correm
   * dentro do trinco da chave, na mesma transacção — o processo de lote e quem
   * mais abrir casos não passam os dois no limite.
   *
   * **Um envio repetido sobre um caso pendente reforça-o** (`reforcar`): o KYC
   * que volta a decidir depois de um `pedir_info` traz marcas e documentos
   * novos, e um caso que ficasse com a prioridade antiga deixava um só revisor
   * aprovar uma regra dura nova. Sobre um caso já decidido, o resultado é
   * `ja_decidido` — e não `aberto`, que mentia a quem chamou.
   */
  async abrir(p: PedidoDeAbertura): Promise<ResultadoDaAbertura> {
    if (!TIPOS_DE_CASO.includes(p.tipo)) throw new RangeError("tipo de caso desconhecido");
    if (!MOTIVOS_PUBLICOS.includes(p.motivoPublico)) throw new RangeError("motivo publico fora da lista");
    if (!Number.isInteger(p.prioridade) || p.prioridade < 1 || p.prioridade > 9) {
      throw new RangeError("prioridade fora de 1..9");
    }
    let quota: Quota | null;
    if (p.onboardingId !== null) {
      const o = await this.#d.onboardings.porId(p.onboardingId);
      if (o === null || o.tenantId !== p.tenantId) return { estado: "nao_elegivel", fase: null };
      if (!FASES_ELEGIVEIS.includes(o.fase)) return { estado: "nao_elegivel", fase: o.fase };
      quota = { tipo: "origem", origem: o.redeHmac ?? o.dispositivoHmac };
    } else {
      quota = p.tipo === "auditoria" ? null : { tipo: "tenant", tenantId: p.tenantId };
    }
    const chave = quota === null ? `sem_quota:${p.tenantId}` : quota.tipo === "origem" ? `o:${quota.origem}` : `t:${quota.tenantId}`;
    return this.#emSerie(chave, () => this.#trancado(chave, async (repositorio) => {
      const agora = this.#agora();
      const naQuota =
        quota === null || (await this.#contar(repositorio, quota, inicioDoDiaEmLuanda(agora))) < this.#l.quotaPorOrigemPorDia;
      const sla = calcularSla(agora, this.#f, this.#l.diasUteisDoSla, this.#l.fracaoDoAlerta);
      const aberto = await repositorio.abrir({
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
      let caso = aberto.caso;
      if (aberto.repetido) {
        if (caso.estado === "decidido" || caso.estado === "decidido_final") {
          return { estado: "ja_decidido", caso, repetido: true };
        }
        const evidencias = [...caso.evidencias];
        for (const e of p.evidencias) {
          if (!evidencias.some((x) => x.tipo === e.tipo && x.ref === e.ref)) evidencias.push(e);
        }
        await repositorio.reforcar(caso.id, {
          prioridade: Math.min(caso.prioridade, p.prioridade),
          motivoInterno: p.motivoInterno,
          evidencias,
          recomendacao: p.recomendacao,
        });
        caso = (await repositorio.porId(caso.id)) ?? caso;
      } else if (caso.estado === "em_triagem_automatica") {
        this.#d.alerta("quota_da_origem", { casoId: caso.id, tipo: caso.tipo });
      }
      return {
        estado: caso.estado === "em_triagem_automatica" ? "em_triagem_automatica" : "aberto",
        caso,
        repetido: aberto.repetido,
      };
    }));
  }

  // ---------------------------------------------------------------- decidir

  /**
   * Uma decisão de primeira instância.
   *
   * `regra` é o código da regra ou do motivo que o revisor invoca; `nota` é
   * texto livre do revisor, que vai **cifrado** e nunca para o dono;
   * `motivoPublico` é um dos quatro códigos fixos, e é o que o dono lê numa
   * rejeição.
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
    if (!DECISOES.includes(decisao)) return this.#recusar(revisor, caso, "decisao_invalida");
    if (opcoes.motivoPublico !== undefined && !MOTIVOS_PUBLICOS.includes(opcoes.motivoPublico)) {
      return this.#recusar(revisor, caso, "decisao_invalida");
    }

    if (decisao === "aprovar" && caso.prioridade <= this.#l.prioridadeDeRiscoAlto) {
      const espera = await this.#primeiroDeDois(revisor, caso, "primeira", opcoes);
      if (espera !== null) return espera;
    } else if (decisao === "escalar") {
      await this.#registar(revisor, caso, decisao, "primeira", opcoes);
      return { estado: "escalado", caso: await this.#mover(caso.id, ["aberto", "em_analise"], "escalado") };
    } else if (decisao === "pedir_info") {
      await this.#registar(revisor, caso, decisao, "primeira", opcoes);
      const actual = caso.estado === "aberto" ? await this.#mover(caso.id, ["aberto"], "em_analise") : caso;
      await this.#porAplicar(caso.id, () => this.#efeitosDoPedidoDeInformacao(caso));
      return { estado: "em_analise", caso: actual };
    } else {
      await this.#registar(revisor, caso, decisao, "primeira", opcoes);
    }

    // aprovar (com o segundo revisor, se era preciso) ou rejeitar: fecha.
    const fechado = await this.#mover(caso.id, ["aberto", "em_analise", "escalado"], "decidido");
    await this.#porAplicar(caso.id, () =>
      this.#efeitos(fechado, decisao, revisor, opcoes.motivoPublico ?? caso.motivoPublico, "primeira"),
    );
    return { estado: "decidido", decisao, caso: fechado };
  }

  /** Os efeitos de um `pedir_info`: o onboarding volta a `kyc_pendente` (num caso `kyc`) e o dono é avisado. */
  async #efeitosDoPedidoDeInformacao(caso: CasoDeRevisao, desde?: Date): Promise<void> {
    if (caso.onboardingId === null) return;
    if (caso.tipo === "kyc" && !(await this.#faseMudouDesde(caso.onboardingId, desde))) {
      await this.#d.onboardings.marcarFase(caso.onboardingId, "kyc_pendente");
    }
    await this.#avisar(caso, "pedir_info", "informacao_em_falta");
  }

  /**
   * Ao **reaplicar** (`desde` é o instante da decisão): a fase mudou depois
   * dela? Se mudou, ou o efeito já a aplicou ou outro passo a levou para a
   * frente — o KYC que volta a decidir depois de um `pedir_info` põe-na em
   * `em_revisao`, ou rejeita —, e reescrevê-la a cada volta do lote desfazia
   * esse passo (KAM-198, achado 2 da revisão adversarial). Fora de uma
   * reaplicação (`desde` indefinido), ou sem o instante da fase, responde que não.
   */
  async #faseMudouDesde(onboardingId: string, desde: Date | undefined): Promise<boolean> {
    if (desde === undefined) return false;
    const faseEm = (await this.#d.onboardings.porId(onboardingId))?.faseEm;
    return faseEm !== undefined && faseEm.getTime() >= desde.getTime();
  }

  /**
   * Corre os efeitos de uma decisão **já registada**, e embrulha a falha deles
   * num `EfeitoPorAplicarError` (KAM-196). É por este erro, e só por ele, que a
   * consola sabe que há um efeito para o *job* reaplicar: um erro antes de a
   * decisão ficar registada não é um efeito por aplicar, e reaplicá-lo mandava
   * ao dono o aviso de uma decisão que não aconteceu (achado 3 da revisão
   * adversarial).
   */
  async #porAplicar(casoId: string, efeitos: () => Promise<void>): Promise<void> {
    // A marca vai **antes** dos efeitos (KAM-198): se o processo morrer entre a
    // decisão e eles, o caso fica marcado e o ciclo reaplica-o. A janela que
    // sobra é a de uma instrução, entre a decisão gravada e esta marca. Uma
    // marca que falha conta como um efeito por aplicar — a consola di-lo.
    try {
      await this.#d.efeitos?.marcar(casoId);
      await efeitos();
    } catch (erro) {
      throw new EfeitoPorAplicarError(casoId, erro);
    }
    // Os efeitos correram. Uma marca que não se limpa **não** se diz a quem
    // decidiu: embrulhá-la num `EfeitoPorAplicarError` dizia que um efeito
    // falhou quando nenhum falhou, e deixá-la subir crua dava um 500 a uma
    // decisão que aconteceu (achado 10 da revisão adversarial). O custo, dito:
    // o lote reaplica-a depois da carência, e os efeitos são idempotentes
    // excepto o aviso, que volta a sair.
    try {
      await this.#d.efeitos?.resolver(casoId);
    } catch {
      // A marca fica; o ciclo trata dela.
    }
  }

  /**
   * Abre o recurso de um caso decidido. **Um** por decisão, e **só de uma
   * rejeição**: o recurso é do dono contra o «não», e uma aprovação recorrida
   * por ninguém acabava rejeitada sem ninguém o ter pedido.
   *
   * Quem pede o recurso é o dono, por um canal que não é desta fila (a rota do
   * dono não existe); a fila recebe o pedido já autenticado. A consola do
   * KAM-196 regista-o pelo `registarRecurso`.
   */
  async abrirRecurso(casoId: string): Promise<CasoDeRevisao> {
    const caso = await this.#d.repositorio.porId(casoId);
    if (caso === null) throw new CasoInexistenteError();
    if (caso.estado !== "decidido") {
      throw new RevisaoRecusadaError(
        caso.estado === "recurso_aberto" || caso.estado === "decidido_final" ? "recurso_ja_usado" : "estado_invalido",
      );
    }
    if ((await this.#decisaoFinal(caso)) !== "rejeitar") throw new RevisaoRecusadaError("recurso_sem_rejeicao");
    const sla = calcularSla(this.#agora(), this.#f, this.#l.diasUteisDoSla, this.#l.fracaoDoAlerta);
    const ok = await this.#d.repositorio.transitar(caso.id, "decidido", "recurso_aberto", sla);
    if (!ok) throw new RevisaoRecusadaError("recurso_ja_usado");
    return (await this.#d.repositorio.porId(caso.id))!;
  }

  /**
   * O recurso aberto **pela consola**, em nome do dono (KAM-196): a equipa
   * regista o pedido que o dono fez por outro canal. Passa pela mesma barreira
   * de todas as operações da consola — papel, MFA e «não é parte no caso» —, e
   * o registo fica no `audit_log` antes de o recurso abrir. Uma recusa do
   * `abrirRecurso` também fica lá, com o motivo.
   */
  async registarRecurso(revisor: Revisor, casoId: string): Promise<CasoDeRevisao> {
    const caso = await this.#autorizar(revisor, casoId);
    await this.#d.auditoria.gravar({
      accao: "review.acesso",
      tenantId: caso.tenantId,
      actorId: revisor.id,
      entidade: "review_case",
      entidadeId: caso.id,
      detalhe: "recurso:abrir",
    });
    try {
      return await this.abrirRecurso(casoId);
    } catch (erro) {
      if (erro instanceof RevisaoRecusadaError) return this.#recusar(revisor, caso, erro.motivo);
      throw erro;
    }
  }

  /**
   * Decide o recurso. Só `aprovar` ou `rejeitar`; nunca por quem decidiu a
   * primeira instância; e um caso que foi escalado na primeira só o decide o
   * `ts_lider` também no recurso — senão um revisor revertia por recurso o que
   * só um líder podia decidir.
   */
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
    const primeira = anteriores.filter((x) => x.instancia === "primeira");
    if (primeira.some((x) => x.revisorId === revisor.id)) {
      return this.#recusar(revisor, caso, "revisor_da_primeira_instancia");
    }
    if (primeira.some((x) => x.decisao === "escalar") && !revisor.papeis.includes("ts_lider")) {
      return this.#recusar(revisor, caso, "so_lider");
    }
    if (decisao === "aprovar" && caso.prioridade <= this.#l.prioridadeDeRiscoAlto) {
      const espera = await this.#primeiroDeDois(revisor, caso, "recurso", opcoes);
      if (espera !== null) return espera;
    } else {
      await this.#registar(revisor, caso, decisao, "recurso", opcoes);
    }
    const fechado = await this.#mover(caso.id, ["recurso_aberto"], "decidido_final");
    await this.#porAplicar(caso.id, () => this.#efeitos(fechado, decisao, revisor, caso.motivoPublico, "recurso"));
    return { estado: "decidido", decisao, caso: fechado };
  }

  /**
   * Volta a aplicar os efeitos de um caso decidido: a fase do onboarding, a
   * decisão humana de screening e o aviso ao dono. E os de um `pedir_info`
   * ainda em curso — a fase e o aviso —, que de outra forma se perdiam: o caso
   * continua pendente, e sem isto o *job* largava-o como «não fechou» e o dono
   * nunca sabia o que faltava (achado 1 da revisão adversarial do KAM-196).
   *
   * Existe porque a decisão e os efeitos não são uma transacção: o caso fecha
   * primeiro (é o que impede duas decisões), e um efeito que falhe — o aviso, o
   * screening — deixava o caso decidido e o onboarding parado, sem retoma. Os
   * efeitos são idempotentes **excepto o aviso**, que volta a sair (e a decisão
   * humana de screening, que é *append-only* e cuja idempotência é do escritor
   * de quem monta o serviço — o do processo de lote não repete a última linha).
   * Quem chama é o *job* da fila sobre os casos marcados: o serviço marca-os ele
   * próprio antes dos efeitos, com a porta `efeitos` (KAM-198).
   */
  async reaplicarEfeitos(casoId: string): Promise<void> {
    const caso = await this.#d.repositorio.porId(casoId);
    if (caso === null) throw new CasoInexistenteError();
    if (ESTADOS_PENDENTES.includes(caso.estado) && caso.estado !== "recurso_aberto") {
      const ultima = (await this.#d.repositorio.decisoes(casoId)).filter((x) => x.instancia === "primeira").at(-1);
      if (ultima?.decisao !== "pedir_info") throw new RevisaoRecusadaError("estado_invalido");
      await this.#efeitosDoPedidoDeInformacao(caso, ultima.em);
      return;
    }
    // Um recurso aberto ainda não decidiu nada: reaplicar a primeira instância
    // mandava ao dono «pode recorrer» com o recurso em curso.
    if (caso.estado === "recurso_aberto") throw new RevisaoRecusadaError("estado_invalido");
    const final = await this.#decisaoFinal(caso);
    if (final === null) throw new RevisaoRecusadaError("estado_invalido");
    const ultima = (await this.#d.repositorio.decisoes(casoId)).filter((x) => x.decisao === final).at(-1)!;
    await this.#efeitos(
      caso,
      final,
      { id: ultima.revisorId, papeis: [], mfa: true, nifHmac: null, telefoneHmac: null },
      caso.motivoPublico,
      caso.estado === "decidido_final" ? "recurso" : "primeira",
      true,
      ultima.em,
    );
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
   * a `em_analise`, e a leitura fica no `audit_log`: o motivo interno é o que
   * a fila tem de mais sensível depois dos documentos.
   */
  async ver(revisor: Revisor, casoId: string): Promise<VistaDoCaso> {
    let caso = await this.#autorizar(revisor, casoId);
    await this.#d.auditoria.gravar({
      accao: "review.acesso",
      tenantId: caso.tenantId,
      actorId: revisor.id,
      entidade: "review_case",
      entidadeId: caso.id,
      detalhe: "ver",
    });
    if (caso.estado === "aberto") caso = await this.#mover(caso.id, ["aberto"], "em_analise");
    const onboarding = await this.#onboardingDoCaso(caso);
    const dados = {} as Record<CampoPessoal, string | null>;
    for (const campo of ["nif", "numero_bi", "telefone"] as const) {
      const v = onboarding === null ? null : await this.#d.dados.ler(onboarding, campo);
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
      onboardingId: onboarding,
      dados,
      decisoes,
    };
  }

  /** Revela **um** campo em claro. O acesso fica no `audit_log` antes de o valor sair. */
  async revelar(revisor: Revisor, casoId: string, campo: CampoPessoal): Promise<string | null> {
    const caso = await this.#autorizar(revisor, casoId);
    const onboarding = await this.#onboardingDoCaso(caso);
    if (onboarding === null) return null;
    await this.#d.auditoria.gravar({
      accao: "review.acesso",
      tenantId: caso.tenantId,
      actorId: revisor.id,
      entidade: "onboarding_case",
      entidadeId: onboarding,
      detalhe: `revelar:${campo}`,
    });
    return this.#d.dados.ler(onboarding, campo);
  }

  /**
   * A URL de um documento de KYC do caso. O documento tem de ser deste caso:
   * uma evidência `kyc_check` dele, ou — num caso que aponta o onboarding
   * inteiro, como a auditoria — um documento **desse** onboarding, que o KYC
   * confere antes de assinar. Um revisor com o caso A aberto não pede o
   * documento do caso B. O acesso fica no `audit_log` antes de a URL existir,
   * e a URL vale ≤ 300 s (o KYC prende o TTL).
   */
  async urlDoDocumento(revisor: Revisor, casoId: string, verificacaoId: string): Promise<string> {
    const caso = await this.#autorizar(revisor, casoId);
    const onboarding = await this.#onboardingDoCaso(caso);
    const directo = caso.evidencias.some((e) => e.tipo === "kyc_check" && e.ref === verificacaoId);
    const doOnboarding = onboarding !== null && caso.evidencias.some((e) => e.tipo === "onboarding_case" && e.ref === onboarding);
    if (onboarding === null || (!directo && !doOnboarding)) return this.#recusar(revisor, caso, "evidencia_alheia");
    const tenantId = caso.tenantId;
    const auditoria = this.#d.auditoria;
    return this.#d.documentos.url(revisor.id, onboarding, verificacaoId, {
      async anotarAcesso(a) {
        await auditoria.gravar({
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
   * quota do dia de cada origem (ou do tenant, num caso sem onboarding). Corre
   * num *job* (o excesso de ontem entra hoje). O SLA conta a partir da entrada,
   * não da criação.
   */
  async drenarTriagem(limite = 500): Promise<number> {
    const agora = this.#agora();
    const desde = inicioDoDiaEmLuanda(agora);
    let entraram = 0;
    for (const caso of await this.#d.repositorio.emTriagem(limite)) {
      let quota: Quota;
      if (caso.onboardingId === null) quota = { tipo: "tenant", tenantId: caso.tenantId };
      else {
        const o = await this.#d.onboardings.porId(caso.onboardingId);
        quota = { tipo: "origem", origem: o === null ? null : (o.redeHmac ?? o.dispositivoHmac) };
      }
      // A mesma chave e o mesmo trinco da abertura: drenar um caso para a vista
      // humana conta contra a quota como abri-lo, e um processo a drenar
      // enquanto outro abre passavam os dois no limite (KAM-198).
      const chave = quota.tipo === "origem" ? `o:${quota.origem}` : `t:${quota.tenantId}`;
      const entrou = await this.#emSerie(chave, () =>
        this.#trancado(chave, async (repositorio) => {
          if ((await this.#contar(repositorio, quota, desde)) >= this.#l.quotaPorOrigemPorDia) return false;
          const sla = calcularSla(agora, this.#f, this.#l.diasUteisDoSla, this.#l.fracaoDoAlerta);
          return repositorio.transitar(caso.id, "em_triagem_automatica", "aberto", { ...sla, filaEm: agora });
        }),
      );
      if (entrou) entraram++;
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
   * Sem `inicioDaAmostragem`, não se amostra. **Ninguém a chama ainda**: quem
   * conhece a aprovação automática é o KAM-092; o gancho é o
   * `CicloDaFila.aprovacaoAutomatica` (KAM-196), servido pelo processo de lote do
   * onboarding (KAM-198, `aprovacaoAutomatica` do `ProcessoDeLote`).
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

  async #emSerie<T>(chave: string, f: () => Promise<T>): Promise<T> {
    const antes = this.#trincos.get(chave) ?? Promise.resolve();
    let soltar!: () => void;
    const minha = new Promise<void>((r) => (soltar = r));
    const cadeia = antes.then(() => minha);
    this.#trincos.set(chave, cadeia);
    await antes;
    try {
      return await f();
    } finally {
      soltar();
      if (this.#trincos.get(chave) === cadeia) this.#trincos.delete(chave);
    }
  }

  /**
   * Corre `f` dentro do trinco **entre processos** da chave, se o repositório o
   * tiver (`emTrinco`); senão com o próprio repositório, e o `#emSerie` que o
   * embrulha é o trinco que há.
   */
  #trancado<T>(chave: string, f: (repositorio: RepositorioDeRevisao) => Promise<T>): Promise<T> {
    const r = this.#d.repositorio;
    return r.emTrinco === undefined ? f(r) : r.emTrinco(chave, f);
  }

  #contar(repositorio: RepositorioDeRevisao, quota: Quota, desde: Date): Promise<number> {
    return quota.tipo === "origem"
      ? repositorio.contarNaFilaDesde(quota.origem, desde)
      : repositorio.contarNaFilaDoTenantDesde(quota.tenantId, desde);
  }

  /**
   * O onboarding de que o caso trata: o dele, ou o que a evidência aponta (a
   * auditoria aponta o onboarding amostrado), ou o do tenant (um produto do
   * catálogo). É dele que vêm os dados mascarados e é contra ele que se mede
   * quem é parte.
   */
  async #onboardingDoCaso(caso: CasoDeRevisao): Promise<string | null> {
    if (caso.onboardingId !== null) return caso.onboardingId;
    const ref = caso.evidencias.find((e) => e.tipo === "onboarding_case")?.ref;
    if (ref !== undefined) return ref;
    return (await this.#d.onboardings.porTenant(caso.tenantId))?.id ?? null;
  }

  /** Identidade e papel; MFA. Uma recusa aqui também fica no `audit_log`, com ou sem caso. */
  async #exigirIdentidade(revisor: Revisor, caso: CasoDeRevisao | null): Promise<void> {
    const papel = revisor.papeis.some((p) => (PAPEIS as readonly string[]).includes(p));
    const motivo: MotivoDeRecusa | null = !papel ? "sem_papel" : !revisor.mfa ? "sem_mfa" : null;
    if (motivo === null) return;
    if (caso !== null) await this.#recusar(revisor, caso, motivo);
    await this.#d.auditoria.gravar({
      accao: "review.recusa",
      tenantId: null,
      actorId: revisor.id === "" ? "desconhecido" : revisor.id,
      entidade: "review_case",
      entidadeId: "fila",
      detalhe: motivo,
    });
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
    const id = await this.#onboardingDoCaso(caso);
    const o = id === null ? null : await this.#d.onboardings.porId(id);
    const parte =
      o !== null &&
      ((revisor.nifHmac !== null && revisor.nifHmac === o.nifHmac) ||
        (revisor.telefoneHmac !== null && revisor.telefoneHmac === o.telefoneHmac));
    if (parte) return this.#recusar(revisor, caso, "parte_no_caso");
    return caso;
  }

  async #recusar(revisor: Revisor, caso: CasoDeRevisao, motivo: MotivoDeRecusa): Promise<never> {
    await this.#d.auditoria.gravar({
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

  /**
   * A aprovação de risco alto. Regista o voto; se, **relido o registo depois de
   * gravar**, já houver dois revisores distintos, devolve `null` e quem chamou
   * fecha. Relê-se porque duas aprovações concorrentes viam as duas «zero
   * aprovadores», gravavam as duas, e o caso ficava à espera de um terceiro com
   * dois votos válidos no registo.
   */
  async #primeiroDeDois(
    revisor: Revisor,
    caso: CasoDeRevisao,
    instancia: Instancia,
    opcoes: { readonly regra?: string | null; readonly nota?: string | null },
  ): Promise<ResultadoDaDecisao | null> {
    const desta = (await this.#d.repositorio.decisoes(caso.id)).filter((x) => x.instancia === instancia);
    if (this.#aprovadoresDesde(desta).has(revisor.id)) return this.#recusar(revisor, caso, "mesmo_revisor");
    await this.#registar(revisor, caso, "aprovar", instancia, opcoes);
    const depois = (await this.#d.repositorio.decisoes(caso.id)).filter((x) => x.instancia === instancia);
    if (this.#aprovadoresDesde(depois).size >= 2) return null;
    let actual = caso;
    if (caso.estado === "aberto") {
      await this.#d.repositorio.transitar(caso.id, "aberto", "em_analise");
      actual = (await this.#d.repositorio.porId(caso.id)) ?? caso;
    }
    return { estado: "aguarda_segundo_revisor", caso: actual };
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

  /**
   * Move o caso para `para` a partir do estado em que ele **está agora**, se for
   * um dos `de`. Relê antes de mover: um caso que outra decisão passou de
   * `aberto` a `em_analise` entretanto continua a poder fechar. Se outra decisão
   * o fechou, recusa — o voto desta já está no registo.
   */
  async #mover(id: string, de: readonly EstadoDoCaso[], para: EstadoDoCaso): Promise<CasoDeRevisao> {
    for (let tentativa = 0; tentativa < 2; tentativa++) {
      const agora = await this.#d.repositorio.porId(id);
      if (agora === null || !de.includes(agora.estado)) break;
      if (await this.#d.repositorio.transitar(id, agora.estado, para)) return (await this.#d.repositorio.porId(id))!;
    }
    throw new RevisaoRecusadaError("estado_invalido");
  }

  /** A decisão que fechou o caso (`aprovar` ou `rejeitar`), ou `null` se ainda não fechou. */
  async #decisaoFinal(caso: CasoDeRevisao): Promise<"aprovar" | "rejeitar" | null> {
    const ultima = await this.#ultimaFinal(caso);
    return ultima === undefined ? null : (ultima.decisao as "aprovar" | "rejeitar");
  }

  /** A linha da decisão que fechou o caso, ou `undefined`. */
  async #ultimaFinal(caso: CasoDeRevisao): Promise<DecisaoRegistada | undefined> {
    if (caso.estado !== "decidido" && caso.estado !== "decidido_final" && caso.estado !== "recurso_aberto") return undefined;
    const instancia: Instancia = caso.estado === "decidido_final" ? "recurso" : "primeira";
    return (await this.#d.repositorio.decisoes(caso.id))
      .filter((x) => x.instancia === instancia && (x.decisao === "aprovar" || x.decisao === "rejeitar"))
      .at(-1);
  }

  /**
   * O que a decisão final faz ao onboarding, ao screening e ao dono. Ver a nota
   * do módulo.
   *
   * **Um recurso aprovado só tira o onboarding de `rejeitado` se mais nada o
   * rejeitou**: todos os outros casos que bloqueiam têm de estar decididos a
   * aprovar, e tem de haver um caso `kyc` aprovado (este ou outro). Sem a
   * segunda condição, o recurso de uma categoria aprovava um onboarding que o
   * KYC rejeitou sozinho ao terceiro ilegível, sem caso nenhum na fila.
   *
   * O aviso ao dono diz o que **aconteceu**: «aprovado» só quando a fase passou
   * a `aprovado`; com outro caso ainda pendente, o dono não recebe nada.
   */
  async #efeitos(
    caso: CasoDeRevisao,
    decisao: Decisao,
    revisor: Revisor,
    motivoPublico: MotivoPublico,
    instancia: Instancia,
    reaplicar = false,
    desde?: Date,
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
    if (decisao === "rejeitar") {
      if (!(await this.#faseMudouDesde(caso.onboardingId, desde))) {
        await this.#d.onboardings.marcarFase(caso.onboardingId, "rejeitado");
      }
      await this.#avisar(caso, instancia === "recurso" ? "recurso_decidido" : "rejeitado", motivoPublico);
      return;
    }
    const outros = (await this.#d.repositorio.casosDoOnboarding(caso.onboardingId)).filter(
      (x) => x.id !== caso.id && TIPOS_QUE_BLOQUEIAM.includes(x.tipo),
    );
    const finais = await Promise.all(outros.map(async (x) => ({ caso: x, final: await this.#decisaoFinal(x) })));
    const pendente = outros.some((x) => x.estado === "em_triagem_automatica" || ESTADOS_PENDENTES.includes(x.estado));
    const rejeitadoPorOutro = finais.some((x) => x.final === "rejeitar" && x.caso.estado !== "recurso_aberto");
    const kycAprovado = caso.tipo === "kyc" || finais.some((x) => x.caso.tipo === "kyc" && x.final === "aprovar");
    const o = await this.#d.onboardings.porId(caso.onboardingId);
    const fase = o?.fase;
    // `kyc_pendente` só conta para o próprio caso `kyc`: é onde um `pedir_info`
    // o deixou. Uma categoria aprovada com o K1 ainda por decidir não aprova o
    // onboarding — o KYC não tem caso pendente a bloquear, e passava.
    // Ao **reaplicar**, `aprovado` também conta: a primeira passagem pode ter
    // marcado a fase e falhado no aviso, que é o último efeito. Sem isto, o
    // `reaplicarEfeitos` via a fase já em `aprovado`, não a contava, e o aviso
    // que tinha falhado nunca saía (KAM-196, achado do ensaio do *job*). **Mas
    // só se foi esta decisão a aprovar**: se outro caso do mesmo onboarding foi
    // decidido depois, foi ele que pôs a fase em `aprovado` e mandou o aviso, e
    // reaplicar este mandava um segundo (achado 2 da revisão adversarial).
    let aprovadoPorOutro = false;
    if (reaplicar && fase === "aprovado") {
      const minha = (await this.#ultimaFinal(caso))?.em.getTime() ?? 0;
      for (const x of outros) {
        const delas = await this.#ultimaFinal(x);
        if (delas !== undefined && delas.em.getTime() > minha) aprovadoPorOutro = true;
      }
    }
    const desbloqueavel =
      fase === "em_revisao" ||
      (caso.tipo === "kyc" && fase === "kyc_pendente") ||
      (instancia === "recurso" && fase === "rejeitado" && kycAprovado) ||
      (reaplicar && fase === "aprovado" && !aprovadoPorOutro);
    const aprovou = !pendente && !rejeitadoPorOutro && desbloqueavel;
    if (aprovou) await this.#d.onboardings.marcarFase(caso.onboardingId, "aprovado");
    if (instancia === "recurso") await this.#avisar(caso, "recurso_decidido", null);
    else if (aprovou) await this.#avisar(caso, "aprovado", null);
  }

  async #avisar(caso: CasoDeRevisao, aviso: Aviso, motivo: MotivoPublico | null): Promise<void> {
    if (caso.onboardingId === null) return;
    // Por omissão o SMS ao telefone registado. Nunca o número da loja.
    await this.#d.aviso.avisar({ onboardingId: caso.onboardingId, via: "sms", aviso, motivoPublico: motivo });
  }
}

/** A chave contra a qual um caso conta para a quota. */
type Quota = { readonly tipo: "origem"; readonly origem: string | null } | { readonly tipo: "tenant"; readonly tenantId: string };

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
