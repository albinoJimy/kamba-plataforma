/**
 * A lista de espera do limite de onboarding da Meta: o serviço (KAM-095).
 *
 * Implementa o `CapacityGate` do KAM-093 **à letra** — `reserve` e `release` —
 * e substitui o `CapacidadeEmMemoria` dele. O que acrescenta é a fila, a
 * posição, os convites e a promoção:
 *
 *     reserve           a vaga, se o caso é a cabeça ou tem convite vivo; senão
 *                       entra na fila (critérios 1, 2, 4, 9)
 *     release           o popup fechou: a vaga **fica** com o caso até sair da
 *                       janela (a Meta pode já o ter contado)
 *     promover          vaga livre ⇒ convite à cabeça, por SMS/e-mail (critério 4)
 *     validarConvite    o convite da ligação ainda vale? Só lê
 *     recusar           o convite, com a sessão do próprio caso
 *     expirarVencidos   convite vencido ⇒ fim da fila uma vez; à segunda,
 *                       `abandonado` (critério 5). Um convite **por entregar**
 *                       vai para o fim sem gastar tentativa (KAM-254)
 *     desistir          liberta a posição de imediato (critério 7)
 *     posicao           a posição e a estimativa rotulada (critério 6)
 *
 * ## Porque cada escrita corre com a fila trancada
 *
 * A vaga é uma conta sobre **toda** a fila (limite − concluídos − convites), e
 * duas transacções que a façam ao mesmo tempo vêem as duas a mesma vaga. Por
 * isso o repositório tranca a fila para escrita no início de cada transacção
 * (`./sql.ts`, `SQL_TRANCAR`), e o critério 9 — dois pedidos para a última
 * vaga, um concedido — é verdade pela base e não por sorte.
 *
 * ## O aviso vai depois do `COMMIT`, e desfaz-se se falhar
 *
 * Mandar o SMS dentro da transacção era segurar a fila trancada à espera de um
 * fornecedor. Mandá-lo depois tem uma janela: o convite existe e o aviso
 * falhou. Fecha-se devolvendo o caso a `aguardando` **no fim da fila e sem
 * gastar tentativa**: no mesmo lugar, uma cabeça com o telefone avariado
 * parava a fila inteira e levava um SMS por minuto (achado da revisão
 * adversarial); gastando tentativa, uma avaria nossa abandonava o caso do
 * dono à segunda. E um convite só se manda na transição
 * `aguardando → convidado`: uma promoção repetida (redelivery) encontra o caso
 * já `convidado` e não manda segundo SMS (adversarial d).
 */

import { createHash, randomBytes } from "node:crypto";

import { JANELA_DE_ONBOARDINGS_DIAS } from "../onboarding/contrato.ts";
import type { CapacityGate } from "../guia/contrato.ts";
import type { Logger } from "../logger/index.ts";
import {
  type AvisoDaLista,
  type Entrada,
  type Estimativa,
  EXPIRACOES_ATE_ABANDONO,
  ListaRecusadaError,
  type OperacoesDaLista,
  type Posicao,
  type RepositorioDaLista,
  VALIDADE_DO_CONVITE_H,
  VALIDADE_DO_KYC_DIAS,
} from "./contrato.ts";
import type { MetricasDaLista } from "./metricas.ts";

const DIA_MS = 86_400_000;
const HORA_MS = 3_600_000;

/** O SHA-256 de um convite, em hexadecimais. É o que a base guarda. */
export function hashDoConvite(convite: string): string {
  return createHash("sha256").update(convite, "utf8").digest("hex");
}

/** As dependências do serviço. */
export interface DependenciasDaLista {
  readonly repositorio: RepositorioDaLista;
  readonly aviso: AvisoDaLista;
  /** A origem pública do `onboarding-web`, para a ligação do convite. */
  readonly origem: string;
  readonly metricas?: MetricasDaLista;
  /** Por omissão, `VALIDADE_DO_KYC_DIAS`. */
  readonly validadeDoKycDias?: number;
  readonly relogio?: () => Date;
  readonly log?: Logger;
}

/**
 * A estimativa de espera da posição `posicao` (1 é a cabeça).
 *
 * Simula a fila sobre a **nossa** janela: cada vaga ocupada liberta-se sete
 * dias depois de ocupada, e quem a apanha volta a ocupá-la por sete dias. O
 * mínimo supõe que cada um à frente aceita no instante; o máximo junta, por
 * cada volta da janela que a posição precisa, as duas expirações de 48 h que um
 * caso à frente pode gastar antes de passar a vez. **É uma estimativa, e diz
 * que é**: não conhece a «Access Verification» nem nenhum prazo da Meta
 * (critério 6). ***Proposta***, a calibrar com o tempo de espera medido.
 *
 * `ocupacoes` são os instantes em que as vagas hoje ocupadas o foram: os
 * concluídos da janela e, para cada convite vivo, `agora`.
 */
export function estimar(posicao: number, maximo: number, ocupacoes: readonly Date[], agora: Date): Estimativa {
  const janelaMs = JANELA_DE_ONBOARDINGS_DIAS * DIA_MS;
  const libertacoes = ocupacoes.map((d) => Math.max(d.getTime() + janelaMs, agora.getTime())).sort((a, b) => a - b);
  let livres = maximo - ocupacoes.length;
  let instante = agora.getTime();
  for (let i = 0; i < posicao; i += 1) {
    while (livres <= 0) {
      const proxima = libertacoes.shift();
      if (proxima === undefined) break;
      instante = Math.max(instante, proxima);
      livres += 1;
    }
    if (livres <= 0) {
      // Limite a zero: não há estimativa possível, e dizê-lo é o honesto.
      return { rotulo: "estimativa", minimoDias: Number.POSITIVE_INFINITY, maximoDias: Number.POSITIVE_INFINITY };
    }
    livres -= 1;
    // Quem apanha esta vaga ocupa-a por uma janela inteira.
    const solta = instante + janelaMs;
    const onde = libertacoes.findIndex((t) => t > solta);
    libertacoes.splice(onde === -1 ? libertacoes.length : onde, 0, solta);
  }
  const minimoMs = instante - agora.getTime();
  const voltas = Math.ceil(posicao / Math.max(maximo, 1));
  const folgaMs = voltas * EXPIRACOES_ATE_ABANDONO * VALIDADE_DO_CONVITE_H * HORA_MS;
  const minimoDias = Math.floor(minimoMs / DIA_MS);
  return { rotulo: "estimativa", minimoDias, maximoDias: Math.max(minimoDias, Math.ceil((minimoMs + folgaMs) / DIA_MS)) };
}

/** Um convite acabado de criar, à espera de aviso. */
interface ConviteNovo {
  readonly onboardingId: string;
  readonly convite: string;
  readonly hash: string;
  readonly expiraEm: Date;
}

/** O serviço. */
export class ListaDeEspera implements CapacityGate {
  readonly #d: DependenciasDaLista;
  readonly #agora: () => Date;
  readonly #kycMs: number;

  constructor(dependencias: DependenciasDaLista) {
    this.#d = dependencias;
    this.#agora = dependencias.relogio ?? ((): Date => new Date());
    this.#kycMs = (dependencias.validadeDoKycDias ?? VALIDADE_DO_KYC_DIAS) * DIA_MS;
  }

  #desde(agora: Date): Date {
    return new Date(agora.getTime() - JANELA_DE_ONBOARDINGS_DIAS * DIA_MS);
  }

  /** O aviso chega ao dono? Ver o `AvisoDaLista.entrega`. */
  get #entrega(): boolean {
    return this.#d.aviso.entrega !== false;
  }

  /**
   * Um convite vencido ou recusado. À primeira, o caso vai para o **fim** da
   * fila; à `EXPIRACOES_ATE_ABANDONO`-ésima, a entrada fica `expirado` e o caso
   * `abandonado` (critério 5). Devolve o estado em que ficou.
   *
   * **Um convite que não chegou ao dono não gasta tentativa** (KAM-254, decisão
   * do fundador de 2026-11-24, A): vence às mesmas 48 h e o caso vai para o fim
   * da fila, como o aviso que falha a sair — e nunca é abandonado por ele. Quem
   * chama diz se gasta: a recusa e a desistência são do dono, que viu o convite.
   */
  async #expirar(op: OperacoesDaLista, e: Entrada, agora: Date, gasta = true): Promise<"aguardando" | "expirado"> {
    const tentativas = gasta ? e.tentativas + 1 : e.tentativas;
    if (tentativas >= EXPIRACOES_ATE_ABANDONO) {
      await op.transitar(e.onboardingId, "convidado", "expirado", {
        tentativas,
        conviteHash: null,
        conviteExpiraEm: null,
      });
      await op.abandonarCaso(e.onboardingId);
      this.#d.log?.info({ outcome: "lista_espera_abandonado" });
      return "expirado";
    }
    await op.transitar(e.onboardingId, "convidado", "aguardando", {
      tentativas,
      naFilaDesde: agora,
      conviteHash: null,
      conviteExpiraEm: null,
    });
    return "aguardando";
  }

  /**
   * A vaga. **Os critérios 1, 2, 4 e 9.**
   *
   * Um caso que nunca esteve na fila entra pelo `aprovado_em` que o
   * repositório lê do caso — quem chama não o escolhe (adversarial c). A vaga
   * só se dá à cabeça (ninguém `aguardando` à frente) ou a quem tem convite
   * vivo; a repetição de um caso que já tem a vaga não gasta outra.
   */
  async reserve(onboardingId: string): Promise<"granted" | "lista_espera"> {
    const agora = this.#agora();
    const desde = this.#desde(agora);
    const resultado = await this.#d.repositorio.emTransaccao(async (op) => {
      const limite = await op.limite();
      let e = await op.entrada(onboardingId);
      if (e === null) {
        e = await op.inserir(onboardingId);
        if (e === null) throw new ListaRecusadaError("nao_elegivel");
      }
      switch (e.estado) {
        case "concluido":
          if (e.concluidoEm !== null && e.concluidoEm > desde) return "granted";
          // A vaga saiu da janela sem o ES acabar (uma reconexão semanas
          // depois): é um onboarding novo para a Meta, e vai para o fim.
          await op.transitar(onboardingId, "concluido", "aguardando", { naFilaDesde: agora, concluidoEm: null });
          break;
        case "convidado":
          if (e.conviteExpiraEm !== null && e.conviteExpiraEm > agora) {
            // **O convite gasta-se aqui**, quando o popup vai abrir, e não ao
            // abrir a ligação: aceitá-lo antes deixava a vaga presa sete dias a
            // quem a página depois recusasse (achado da revisão adversarial).
            await op.transitar(onboardingId, "convidado", "concluido", {
              concluidoEm: agora,
              conviteHash: null,
              conviteExpiraEm: null,
            });
            return "aceite";
          }
          // A recusa lança-se **depois** do `COMMIT`: lançada aqui, desfazia a
          // expiração e o abandono que acabaram de se escrever.
          if ((await this.#expirar(op, e, agora, this.#entrega)) === "expirado") return "expirou";
          break;
        case "desistiu":
          // **Novo pedido, sem refazer o KYC enquanto ele valer** (critério 7).
          if (agora.getTime() - e.aprovadoEm.getTime() > this.#kycMs) throw new ListaRecusadaError("kyc_caducado");
          await op.transitar(onboardingId, "desistiu", "aguardando", { naFilaDesde: agora });
          break;
        case "expirado":
          throw new ListaRecusadaError("fora_da_lista");
        case "aguardando":
          break;
      }
      const vaga = limite.maximo - (await op.ocupadas(desde, agora));
      if (vaga > 0 && (await op.aFrente(onboardingId)) === 0) {
        await op.transitar(onboardingId, "aguardando", "concluido", { concluidoEm: agora });
        return "granted";
      }
      return "lista_espera";
    });
    if (resultado === "expirou") {
      this.#d.metricas?.convite("expirado");
      throw new ListaRecusadaError("fora_da_lista");
    }
    if (resultado === "aceite") {
      this.#d.metricas?.convite("aceite");
      return "granted";
    }
    if (resultado === "lista_espera") {
      this.#d.log?.info({ outcome: "lista_espera_entrou" });
      // Pode haver vaga para quem está à frente: convida-se já, e não no
      // próximo minuto do temporizador.
      await this.promover();
    }
    return resultado;
  }

  /**
   * O popup fechou sem `FINISH`, ou a ligação falhou depois dele. **A vaga não
   * volta à fila**, e é achado da revisão adversarial: a Meta pode já ter
   * contado este onboarding — se um popup fechado conta é NÃO VERIFICADO —, e
   * a regra do `es_onboardings_7d` (§3.21) é contar de mais, porque contar de
   * menos custa um cliente recusado. Devolvê-la tinha dois efeitos: convidava
   * outro caso para o mesmo tecto, e mandava um SMS de convite a quem acabou
   * de fechar o popup — um por volta de «Ligar → fechar». O caso guarda a vaga
   * até ela sair da janela, e a retoma pela mesma ligação volta a dá-la sem
   * gastar outra (o `reserve` de um `concluido` na janela).
   */
  async release(_onboardingId: string): Promise<void> {
    this.#d.log?.info({ outcome: "lista_espera_vaga_mantida" });
  }

  /**
   * Convida a cabeça enquanto houver vaga. **O critério 4.** Devolve quantos
   * convites saíram com aviso entregue: com uma porta sem via, nenhum — o
   * convite fica, e conta-se `por_entregar` (KAM-254).
   */
  async promover(): Promise<number> {
    const agora = this.#agora();
    const desde = this.#desde(agora);
    const novos = await this.#d.repositorio.emTransaccao(async (op) => {
      const limite = await op.limite();
      let vaga = limite.maximo - (await op.ocupadas(desde, agora));
      const criados: ConviteNovo[] = [];
      while (vaga > 0) {
        const cabeca = await op.cabeca();
        if (cabeca === null) break;
        if (!(await op.elegivel(cabeca.onboardingId))) {
          // O caso saiu das fases da fila enquanto esperava (a revisão
          // rejeitou-o ou pediu informação): sai da fila sem convite, como uma
          // desistência — um pedido novo volta a pô-lo nela, pelo fim.
          await op.transitar(cabeca.onboardingId, "aguardando", "desistiu", {});
          this.#d.log?.info({ outcome: "lista_espera_fora_de_fase" });
          continue;
        }
        const convite = randomBytes(32).toString("base64url");
        const hash = hashDoConvite(convite);
        const expiraEm = new Date(agora.getTime() + VALIDADE_DO_CONVITE_H * HORA_MS);
        const passou = await op.transitar(cabeca.onboardingId, "aguardando", "convidado", {
          conviteHash: hash,
          convidadoEm: agora,
          conviteExpiraEm: expiraEm,
        });
        if (!passou) break;
        criados.push({ onboardingId: cabeca.onboardingId, convite, hash, expiraEm });
        vaga -= 1;
      }
      return criados;
    });
    let avisados = 0;
    for (const n of novos) {
      // A página do guia, que já exige a sessão; o convite só se gasta quando
      // o dono carrega em «Ligar», e não ao abrir a ligação.
      const ligacao = `${this.#d.origem}/ligar?convite=${n.convite}`;
      try {
        await this.#d.aviso.convidar(n.onboardingId, ligacao, n.expiraEm);
        if (this.#entrega) {
          this.#d.metricas?.convite("enviado");
          avisados += 1;
        } else {
          this.#d.metricas?.convite("por_entregar");
        }
      } catch (erro) {
        this.#d.metricas?.convite("por_entregar");
        // Ver a nota do módulo: o convite desfaz-se, o caso vai para o fim, e
        // não gasta tentativa.
        await this.#d.repositorio.emTransaccao(async (op) => {
          const e = await op.porConvite(n.hash);
          if (e !== null) {
            await op.transitar(e.onboardingId, "convidado", "aguardando", {
              naFilaDesde: this.#agora(),
              conviteHash: null,
              conviteExpiraEm: null,
            });
          }
        });
        this.#d.log?.warn({ outcome: "lista_espera_aviso_falhou", error_code: erro instanceof Error ? erro.name : "desconhecido" });
      }
    }
    return avisados;
  }

  /** Lê o convite **do caso da sessão**; outro caso, usado ou vencido ⇒ recusa. */
  async #conviteVivo(op: OperacoesDaLista, onboardingId: string, convite: unknown, agora: Date): Promise<Entrada> {
    if (typeof convite !== "string" || convite.length === 0 || convite.length > 128) {
      throw new ListaRecusadaError("convite_invalido");
    }
    const e = await op.porConvite(hashDoConvite(convite));
    if (
      e === null ||
      e.onboardingId !== onboardingId ||
      e.estado !== "convidado" ||
      e.conviteExpiraEm === null ||
      e.conviteExpiraEm <= agora
    ) {
      throw new ListaRecusadaError("convite_invalido");
    }
    return e;
  }

  /**
   * O convite da ligação ainda vale para **o caso da sessão**? Só lê. Devolve o
   * prazo; outro caso, forjado, usado ou vencido dão `convite_invalido`
   * (adversarial b).
   *
   * **Uso único** quer dizer isto: o convite gasta-se quando a vaga se dá — no
   * `reserve` do guia, ao abrir o popup —, o *hash* apaga-se, e a mesma ligação
   * deixa de valer. Não se gasta aqui, e é achado da revisão adversarial:
   * gastá-lo antes de a página abrir o popup deixava a vaga presa sete dias a
   * quem o `iniciar` depois recusasse.
   */
  async validarConvite(onboardingId: string, convite: unknown): Promise<{ readonly expiraEm: Date }> {
    const agora = this.#agora();
    const e = await this.#d.repositorio.emTransaccao((op) => this.#conviteVivo(op, onboardingId, convite, agora));
    return { expiraEm: e.conviteExpiraEm ?? agora };
  }

  /** O dono recusa o convite: conta como uma expiração (critério 5). */
  async recusar(onboardingId: string, convite: unknown): Promise<void> {
    const agora = this.#agora();
    await this.#d.repositorio.emTransaccao(async (op) => {
      const e = await this.#conviteVivo(op, onboardingId, convite, agora);
      await this.#expirar(op, e, agora);
    });
    this.#d.metricas?.convite("recusado");
    await this.promover();
  }

  /** Os convites vencidos. **O critério 5.** Devolve quantos. */
  async expirarVencidos(): Promise<number> {
    const agora = this.#agora();
    const n = await this.#d.repositorio.emTransaccao(async (op) => {
      let feitos = 0;
      for (const id of await op.vencidos(agora)) {
        const e = await op.entrada(id);
        if (e === null || e.estado !== "convidado") continue;
        await this.#expirar(op, e, agora, this.#entrega);
        feitos += 1;
      }
      return feitos;
    });
    for (let i = 0; i < n; i += 1) this.#d.metricas?.convite("expirado");
    if (n > 0) await this.promover();
    return n;
  }

  /**
   * O dono desiste. **O critério 7**: a posição liberta-se já, e um convite
   * vivo também. Idempotente.
   */
  async desistir(onboardingId: string): Promise<void> {
    const libertou = await this.#d.repositorio.emTransaccao(async (op) => {
      const e = await op.entrada(onboardingId);
      if (e === null) throw new ListaRecusadaError("fora_da_lista");
      if (e.estado !== "aguardando" && e.estado !== "convidado") return false;
      // **Desistir com um convite na mão gasta-o como uma recusa** (achado da
      // revisão adversarial): sem isto, desistir e voltar a entrar era a forma
      // de nunca chegar às duas expirações, segurando 48 h de vaga por volta.
      const tentativas =
        e.estado === "convidado" ? Math.min(e.tentativas + 1, EXPIRACOES_ATE_ABANDONO) : e.tentativas;
      return op.transitar(onboardingId, e.estado, "desistiu", { tentativas, conviteHash: null, conviteExpiraEm: null });
    });
    if (libertou) await this.promover();
  }

  /**
   * A posição do caso e a estimativa. **O critério 6.** `null` se o caso nunca
   * entrou na fila. Só se pergunta pelo caso da sessão: a porta não aceita
   * outro identificador.
   */
  async posicao(onboardingId: string): Promise<Posicao | null> {
    const agora = this.#agora();
    const desde = this.#desde(agora);
    const lida = await this.#d.repositorio.emTransaccao(async (op) => {
      const e = await op.entrada(onboardingId);
      if (e === null) return null;
      return { e, aFrente: e.estado === "aguardando" ? await op.aFrente(onboardingId) : 0 };
    });
    if (lida === null) return null;
    const { e, aFrente } = lida;
    // A base prende o prazo ao estado (`waitlist_entry_convite_ck`): um
    // `convidado` tem sempre `convite_expira_em`.
    if (e.estado === "convidado") return { estado: "convidado", expiraEm: e.conviteExpiraEm ?? agora };
    if (e.estado !== "aguardando") return { estado: e.estado };
    const f = await this.#d.repositorio.fotografia(desde);
    const ocupacoes = [...f.concluidosNaJanela, ...Array.from({ length: f.porEstado.convidado }, () => agora)];
    return { estado: "aguardando", posicao: aFrente + 1, estimativa: estimar(aFrente + 1, f.limite.maximo, ocupacoes, agora) };
  }

  /** Recalcula os *gauges* das métricas. Chamado pelo temporizador. */
  async medir(): Promise<void> {
    if (this.#d.metricas === undefined) return;
    this.#d.metricas.actualizar(await this.#d.repositorio.fotografia(this.#desde(this.#agora())));
  }
}
