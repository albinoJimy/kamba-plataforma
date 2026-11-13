/**
 * O caso de uso de Trust & Safety (KAM-097). Ver `./contrato.ts` para o desenho.
 *
 * ```text
 * registar         um sinal (idempotente) e, se é novo, a escada automática
 * proporSancao     um passo humano: abre um caso `trust` na fila
 * pedirRecurso     o recurso do dono, uma vez por sanção
 * aplicarDecisao   o efeito de uma decisão da fila sobre um caso `trust` ou `recurso`
 * fecharEncerramentos   o `encerrado` de um encerramento cujo prazo de recurso passou
 * leituras         o passo em vigor, as restrições, os avisos do painel
 * ```
 */

import type { CasoDeRevisao, Decisao, Instancia } from "../revisao/contrato.ts";
import type { PedidoDeAbertura, ResultadoDaAbertura } from "../revisao/servico.ts";
import {
  CHAVES_DO_DETALHE,
  LIMIARES_DO_SERVICO,
  MOTIVO_DO_PASSO,
  TrustRecusadoError,
  autorDoSistema,
  type AvisoDeSancao,
  type ConfiguracaoDoTrust,
  type EstadoDosTenants,
  type LimiaresDoServico,
  type MotivoPublicoDaSancao,
  type RepositorioDeTrust,
  type RestricoesEmVigor,
  type SancaoGravada,
  type SinalGravado,
  type SinalNovo,
} from "./contrato.ts";
import {
  PASSOS,
  POLITICA_DE_RISCO,
  ordem,
  passoAutomatico,
  recusaDaSancao,
  risco,
  type Passo,
  type PoliticaDeRisco,
} from "./regras.ts";

/** A parte da fila de revisão de que T&S precisa. O `ServicoDeRevisao` cumpre-a. */
export interface FilaDoTrust {
  abrir(p: PedidoDeAbertura): Promise<ResultadoDaAbertura>;
  abrirRecurso(casoId: string): Promise<CasoDeRevisao>;
}

export interface DependenciasDoTrust extends ConfiguracaoDoTrust {
  readonly repositorio: RepositorioDeTrust;
  /** Só o lado do lote: a decisão grave muda o estado do tenant. */
  readonly tenants?: EstadoDosTenants;
  readonly aviso?: AvisoDeSancao;
  readonly fila?: FilaDoTrust;
}

/** O que uma decisão da fila entrega a T&S. É a forma do gancho do `ServicoDeRevisao`. */
export interface DecisaoParaTrust {
  readonly caso: CasoDeRevisao;
  readonly decisao: Decisao;
  readonly revisorId: string;
  readonly instancia: Instancia;
  readonly regra: string | null;
}

/** O gancho que a fila de revisão chama depois de uma decisão final num caso `trust` ou `recurso`. */
export interface EfeitosDeTrust {
  aplicarDecisao(d: DecisaoParaTrust): Promise<void>;
}

/** O prefixo do `motivo_codigo` de uma proposta (`sancao_<passo>:<chave>`) e de um recurso (`sancao:<id>`). */
const PROPOSTA = /^sancao_(aviso|limitacao|suspensao|encerramento):[0-9a-z_.-]{1,80}$/;
const RECURSO_AUTOMATICO = /^sancao:([0-9a-f-]{36})$/;
const CHAVE_DA_PROPOSTA = /^[0-9a-z_.-]{1,80}$/;

/** Os estados de que uma suspensão parte (`docs/tecnica/10` §15.1). */
const SUSPENDIVEIS = ["ativo", "restrito"] as const;

/**
 * As sanções em vigor: os passos sem um recurso **provido**. O passo em vigor é
 * o mais alto deles. Um recurso negado não muda nada.
 */
export function emVigor(sancoes: readonly SancaoGravada[]): { readonly passo: Passo | null; readonly sancoes: readonly SancaoGravada[] } {
  const providos = new Set(sancoes.filter((s) => s.recursoEstado === "provido").map((s) => s.recursoDe));
  const vivas = sancoes.filter((s) => s.recursoDe === null && !providos.has(s.id));
  let passo: Passo | null = null;
  for (const s of vivas) if (ordem(s.passo) > ordem(passo)) passo = s.passo;
  return { passo, sancoes: vivas };
}

export class ServicoDeTrust implements EfeitosDeTrust {
  readonly #d: DependenciasDoTrust;
  readonly #p: PoliticaDeRisco;
  readonly #l: LimiaresDoServico;
  readonly #agora: () => Date;

  constructor(d: DependenciasDoTrust) {
    this.#d = d;
    this.#p = d.politica ?? POLITICA_DE_RISCO;
    this.#l = d.limiares ?? LIMIARES_DO_SERVICO;
    this.#agora = d.relogio ?? (() => new Date());
  }

  // --------------------------------------------------------------- sinais

  /**
   * Grava um sinal e, **se é novo**, corre a escada automática. Um sinal
   * repetido (a mesma chave) não volta a correr a escada: a reentrega de um
   * evento dá um sinal e zero sanções a mais (ensaio adversarial (e)).
   */
  async registar(novo: SinalNovo): Promise<{ readonly sinal: SinalGravado; readonly repetido: boolean; readonly sancoes: readonly SancaoGravada[] }> {
    for (const chave of Object.keys(novo.detalhe)) {
      if (!(CHAVES_DO_DETALHE as readonly string[]).includes(chave)) throw new TrustRecusadoError("detalhe_invalido");
    }
    const g = await this.#d.repositorio.gravarSinal(novo);
    if (g.repetido) return { ...g, sancoes: [] };
    return { ...g, sancoes: await this.avaliarEscada(novo.tenantId, g.sinal) };
  }

  /**
   * A escada automática: enquanto o risco pedir um degrau acima do que está em
   * vigor, grava-o — um de cada vez, até à `limitacao`. A chave leva o sinal que
   * a disparou, pelo que a mesma avaliação repetida não grava duas vezes.
   */
  async avaliarEscada(tenantId: string, gatilho: SinalGravado): Promise<readonly SancaoGravada[]> {
    const r = risco(await this.#d.repositorio.sinaisDoTenant(tenantId), this.#agora(), this.#p);
    const novas: SancaoGravada[] = [];
    for (let i = 0; i < PASSOS.length; i++) {
      const vigor = emVigor(await this.#d.repositorio.sancoesDoTenant(tenantId)).passo;
      const passo = passoAutomatico(r, vigor, this.#p);
      if (passo === null) break;
      const g = await this.#d.repositorio.gravarSancao({
        tenantId,
        chave: `auto:${passo}:${gatilho.id}`,
        passo,
        origem: "automatica",
        motivoInterno: `risco=${r};limiar=${passo === "aviso" ? this.#p.limiarDoAviso : this.#p.limiarDaLimitacao};politica=${this.#p.versao}`,
        motivoPublico: MOTIVO_DO_PASSO[passo],
        autor: autorDoSistema(this.#p),
        regra: `risco_ts>=${passo === "aviso" ? this.#p.limiarDoAviso : this.#p.limiarDaLimitacao}`,
        sinais: [gatilho.id],
        casoId: null,
        justificacaoDoSalto: null,
        recursoDe: null,
        recursoEstado: null,
      });
      if (g.repetido) break;
      novas.push(g.sancao);
    }
    return novas;
  }

  // --------------------------------------------------------------- propostas

  /**
   * Propõe um passo humano. Valida antes de abrir o caso — motivo sempre, e
   * justificação escrita quando salta degraus —, e o caso `trust` vai à fila
   * com os sinais como evidência e a proposta (o passo e a justificação) como
   * evidência também. **Nada muda no tenant aqui**: muda quando um revisor
   * rejeitar o caso.
   */
  async proporSancao(p: {
    readonly tenantId: string;
    readonly passo: Passo;
    readonly motivoInterno: string;
    readonly sinais: readonly string[];
    readonly justificacaoDoSalto: string | null;
    /** A idempotência da proposta: a mesma chave é o mesmo caso. */
    readonly chave: string;
  }): Promise<ResultadoDaAbertura> {
    const fila = this.#exigirFila();
    if (!CHAVE_DA_PROPOSTA.test(p.chave)) throw new RangeError("chave da proposta fora da forma");
    const vigor = emVigor(await this.#d.repositorio.sancoesDoTenant(p.tenantId)).passo;
    const recusa = recusaDaSancao({ passo: p.passo, origem: "humana", motivoInterno: p.motivoInterno, justificacaoDoSalto: p.justificacaoDoSalto, emVigor: vigor });
    if (recusa !== null) throw new TrustRecusadoError(recusa);
    return fila.abrir({
      tipo: "trust",
      tenantId: p.tenantId,
      onboardingId: null,
      motivoCodigo: `sancao_${p.passo}:${p.chave}`,
      motivoInterno: p.motivoInterno,
      motivoPublico: "nao_foi_possivel_validar",
      evidencias: [
        ...p.sinais.map((ref) => ({ tipo: "ts_signal", ref })),
        { tipo: "ts_proposta", ref: JSON.stringify({ passo: p.passo, justificacao: p.justificacaoDoSalto }) },
      ],
      recomendacao: "rejeitar",
      prioridade: this.#l.prioridadeDaProposta,
    });
  }

  /**
   * O recurso do dono, **uma vez** por sanção. O de uma sanção humana é o
   * recurso do próprio caso (a fila decide-o por outro revisor e recusa o
   * segundo); o de uma automática é um caso `recurso` com a chave `sancao:<id>`,
   * que a chave da fila faz único.
   */
  async pedirRecurso(tenantId: string, sancaoId: string): Promise<CasoDeRevisao> {
    const fila = this.#exigirFila();
    const todas = await this.#d.repositorio.sancoesDoTenant(tenantId);
    const s = todas.find((x) => x.id === sancaoId && x.recursoDe === null);
    if (s === undefined) throw new TrustRecusadoError("sancao_inexistente");
    if (todas.some((x) => x.recursoDe === s.id)) throw new TrustRecusadoError("recurso_ja_usado");
    if (s.origem === "humana") return fila.abrirRecurso(s.casoId!);
    const r = await fila.abrir({
      tipo: "recurso",
      tenantId,
      onboardingId: null,
      motivoCodigo: `sancao:${s.id}`,
      motivoInterno: `recurso do passo automatico ${s.passo}`,
      motivoPublico: "nao_foi_possivel_validar",
      evidencias: [{ tipo: "ts_sanction", ref: s.id }],
      recomendacao: null,
      prioridade: 5,
    });
    if (r.estado === "nao_elegivel" || r.repetido) throw new TrustRecusadoError("recurso_ja_usado");
    return r.caso;
  }

  // --------------------------------------------------------------- decisões

  /**
   * O efeito de uma decisão final da fila. Idempotente: a linha da sanção tem
   * chave, e as transições do tenant são CAS. O aviso ao dono é o último efeito,
   * como na fila: se falhar, a fila guarda o caso para reaplicar.
   */
  async aplicarDecisao(d: DecisaoParaTrust): Promise<void> {
    if (d.decisao !== "aprovar" && d.decisao !== "rejeitar") return;
    if (d.caso.tipo === "trust") return this.#decisaoDeProposta(d);
    if (d.caso.tipo === "recurso") {
      const m = RECURSO_AUTOMATICO.exec(d.caso.motivoCodigo);
      if (m?.[1] !== undefined) return this.#decisaoDeRecurso(d, m[1]);
    }
  }

  async #decisaoDeProposta(d: DecisaoParaTrust): Promise<void> {
    const caso = d.caso;
    if (!PROPOSTA.test(caso.motivoCodigo)) return;
    if (d.instancia === "primeira") {
      if (d.decisao === "aprovar") return;
      const proposta = propostaDoCaso(caso);
      const g = await this.#d.repositorio.gravarSancao({
        tenantId: caso.tenantId,
        chave: `caso:${caso.id}`,
        passo: proposta.passo,
        origem: "humana",
        motivoInterno: caso.motivoInterno,
        motivoPublico: MOTIVO_DO_PASSO[proposta.passo],
        autor: d.revisorId,
        regra: d.regra,
        sinais: caso.evidencias.filter((e) => e.tipo === "ts_signal").map((e) => e.ref),
        casoId: caso.id,
        justificacaoDoSalto: proposta.justificacao,
        recursoDe: null,
        recursoEstado: null,
      });
      if (proposta.passo === "suspensao" || proposta.passo === "encerramento") {
        await this.#exigirTenants().transitar(caso.tenantId, SUSPENDIVEIS, "suspenso");
      }
      await this.#avisar(caso.tenantId, g.sancao.motivoPublico);
      return;
    }
    const sancao = (await this.#d.repositorio.sancoesDoTenant(caso.tenantId)).find((x) => x.chave === `caso:${caso.id}`);
    if (sancao === undefined) return;
    await this.#desfecho(d, sancao);
  }

  async #decisaoDeRecurso(d: DecisaoParaTrust, sancaoId: string): Promise<void> {
    const sancao = (await this.#d.repositorio.sancoesDoTenant(d.caso.tenantId)).find((x) => x.id === sancaoId && x.recursoDe === null);
    if (sancao === undefined) return;
    await this.#desfecho(d, sancao);
  }

  /** O desfecho de um recurso: uma linha nova, e o estado do tenant se a sanção o tinha mudado. */
  async #desfecho(d: DecisaoParaTrust, sancao: SancaoGravada): Promise<void> {
    const provido = d.decisao === "aprovar";
    const motivo: MotivoPublicoDaSancao = provido ? "recurso_aceite" : "recurso_mantido";
    await this.#d.repositorio.gravarSancao({
      tenantId: sancao.tenantId,
      chave: `recurso:${sancao.id}`,
      passo: sancao.passo,
      origem: "humana",
      motivoInterno: `recurso ${provido ? "provido" : "negado"} sobre ${sancao.passo}`,
      motivoPublico: motivo,
      autor: d.revisorId,
      regra: d.regra,
      sinais: sancao.sinais,
      casoId: d.caso.id,
      justificacaoDoSalto: null,
      recursoDe: sancao.id,
      recursoEstado: provido ? "provido" : "negado",
    });
    const grave = sancao.passo === "suspensao" || sancao.passo === "encerramento";
    if (grave && provido) {
      // Levanta a suspensão só se mais nada grave ficou em vigor.
      const vigor = emVigor(await this.#d.repositorio.sancoesDoTenant(sancao.tenantId)).passo;
      if (ordem(vigor) < ordem("suspensao")) await this.#exigirTenants().transitar(sancao.tenantId, ["suspenso"], "ativo");
    } else if (sancao.passo === "encerramento" && !provido) {
      await this.#exigirTenants().transitar(sancao.tenantId, ["suspenso"], "encerrado");
    }
    await this.#avisar(sancao.tenantId, motivo);
  }

  /**
   * O `encerrado` dos encerramentos cujo prazo de recurso passou sem recurso
   * pedido. `porFechar` lista-os (o adaptador SQL confirma também que o caso não
   * tem recurso aberto). Corre num *job*; devolve quantos fechou.
   */
  async fecharEncerramentos(porFechar: (ate: Date) => Promise<readonly SancaoGravada[]>): Promise<number> {
    const ate = new Date(this.#agora().getTime() - this.#l.diasDoRecurso * 86_400_000);
    let n = 0;
    for (const s of await porFechar(ate)) {
      if (s.passo !== "encerramento" || s.recursoDe !== null) continue;
      const vivas = emVigor(await this.#d.repositorio.sancoesDoTenant(s.tenantId)).sancoes;
      if (!vivas.some((x) => x.id === s.id)) continue;
      if (await this.#exigirTenants().transitar(s.tenantId, ["suspenso"], "encerrado")) n++;
    }
    return n;
  }

  // --------------------------------------------------------------- leituras

  async passoEmVigor(tenantId: string): Promise<Passo | null> {
    return emVigor(await this.#d.repositorio.sancoesDoTenant(tenantId)).passo;
  }

  async restricoes(tenantId: string): Promise<RestricoesEmVigor> {
    const passo = await this.passoEmVigor(tenantId);
    const limitado = ordem(passo) >= ordem("limitacao");
    return { passo, semNovosProdutos: limitado, tectoNoNivelZero: limitado };
  }

  /**
   * Os avisos do painel do dono (KAM-099, critério 7; o adaptador é do
   * KAM-190): os **códigos** públicos das sanções em vigor, do mais recente
   * para o mais antigo. Nunca o motivo interno.
   */
  async avisosDoPainel(tenantId: string): Promise<readonly MotivoPublicoDaSancao[]> {
    const vivas = [...emVigor(await this.#d.repositorio.sancoesDoTenant(tenantId)).sancoes];
    // Do mais recente para o mais antigo, e no mesmo instante o passo mais alto
    // primeiro: o aviso e a limitação da mesma avaliação nascem juntos.
    vivas.sort((a, b) => b.em.getTime() - a.em.getTime() || ordem(b.passo) - ordem(a.passo));
    return [...new Set(vivas.map((s) => s.motivoPublico))];
  }

  // --------------------------------------------------------------- privado

  #exigirFila(): FilaDoTrust {
    if (this.#d.fila === undefined) throw new Error("sem fila de revisao: so o lado do lote propoe sancoes");
    return this.#d.fila;
  }

  #exigirTenants(): EstadoDosTenants {
    if (this.#d.tenants === undefined) throw new Error("sem estado dos tenants: so o lado do lote muda o estado");
    return this.#d.tenants;
  }

  async #avisar(tenantId: string, motivo: MotivoPublicoDaSancao): Promise<void> {
    await this.#d.aviso?.avisar({ tenantId, motivo });
  }
}

/** A proposta guardada como evidência do caso. Sem ela, o caso não diz o passo. */
export function propostaDoCaso(caso: CasoDeRevisao): { readonly passo: Passo; readonly justificacao: string | null } {
  const e = caso.evidencias.find((x) => x.tipo === "ts_proposta");
  const m = /^sancao_(aviso|limitacao|suspensao|encerramento):/.exec(caso.motivoCodigo);
  if (e === undefined || m?.[1] === undefined) throw new TrustRecusadoError("passo_desconhecido");
  const p = JSON.parse(e.ref) as { passo?: unknown; justificacao?: unknown };
  // O passo do `motivo_codigo` é o da chave do caso; a evidência tem de dizer o mesmo.
  if (p.passo !== m[1]) throw new TrustRecusadoError("passo_desconhecido");
  const justificacao = typeof p.justificacao === "string" && p.justificacao.trim() !== "" ? p.justificacao : null;
  return { passo: m[1] as Passo, justificacao };
}
