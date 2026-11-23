/**
 * As varreduras de Trust & Safety agendadas no processo de lote (KAM-200,
 * critério 2).
 *
 * ```text
 * nao_entrega     varrerNaoEntregas    pedidos pagos sem entrega há mais de N dias
 * fotos           varrerFotos          o mesmo phash noutro tenant (informativo)
 * encerramentos   fecharEncerramentos  o encerrado de quem não recorreu no prazo
 * mudancas_de_conta                    o caso `trust` de cada mudança de conta ou NIF
 * compradores_do_dono  varrerCompradoresDoDono  o comprador noutro tenant do mesmo dono (KAM-208)
 * pseudonimos     purgarPseudonimos    a retenção do pseudónimo sem tenant (KAM-208)
 * ```
 *
 * ## O interruptor do KAM-208
 *
 * A `compradores_do_dono` só corre com `correlacao: "ligada"` — o
 * `estadoDaCorrelacao` de `../identity/correlacao.ts`, que em `prod` nunca a dá
 * (decisão do fundador de 2026-11-21, D1). Desligada, **não corre nem audita**:
 * não houve corrida. A `pseudonimos` corre sempre, porque apaga.
 *
 * ## Uma corrida, uma linha no `audit_log`
 *
 * Cada varredura corre como `kamba_batch` (o papel auditado que atravessa
 * tenants) e deixa **uma** linha `batch.run` na cadeia da plataforma: o
 * `tenant_id` é nulo (`docs/auditoria.md`: o `batch.run` não tem tenant), o
 * `entity` é `ts_varredura`, o `entity_id` é o nome da varredura, e o
 * `payload_hash` é o SHA-256 de `<nome>:<sinais ou tenants>`. As duas
 * primeiras correm **na mesma transacção** que a linha de auditoria: uma
 * corrida que não ficou registada não gravou sinais, e vice-versa. O
 * `fecharEncerramentos` não pode: cada encerramento é uma transição pela porta
 * do KAM-092, numa transacção sob o tenant dele, e a linha de auditoria vem
 * depois, com quantos fechou.
 *
 * ## Uma que falha não pára as outras
 *
 * Como no `CicloDaFila` (`../revisao/ciclo.ts`): cada varredura tem o seu
 * `try`, e o resultado diz quais falharam, **pelo nome**, nunca pela mensagem.
 */

import { comBatch } from "../tenant_guard/index.ts";
import type { ConjuntoSql } from "../revisao/sql.ts";
import type { EstadoDaCorrelacao } from "../identity/correlacao.ts";
import { purgarPseudonimos, varrerCompradoresDoDono, varrerFotos, varrerNaoEntregas } from "./efeito.ts";
import type { ContadoresDoTrust, MetricasDoTrust, Varredura } from "./metricas.ts";
import type { Origem } from "./contrato.ts";
import type { Passo, TipoDeSinal } from "./regras.ts";
import { POLITICA_DE_RISCO, type PoliticaDeRisco } from "./regras.ts";
import type { SinalGravado } from "./contrato.ts";
import type { ServicoDeTrust } from "./servico.ts";
import { RepositorioDeTrustSql, SQL_MUDANCAS_DE_CONTA_SEM_CASO, type ClienteSql } from "./sql.ts";

/** O actor das linhas de auditoria das varreduras: o processo, e não uma pessoa. */
export const ACTOR_DAS_VARREDURAS = "onboarding-lote";

/** A corrida de uma varredura no `audit_log`, na cadeia da plataforma. */
export const SQL_AUDITAR_VARREDURA = `
  SELECT platform.audit_append(
           NULL, 'system', $1, 'batch.run', 'ts_varredura', $2, NULL,
           sha256(convert_to($3, 'UTF8')))
`;

/** O motivo interno e a justificação da proposta de uma mudança de conta. Só para T&S. */
export const MOTIVO_DA_MUDANCA_DE_CONTA = "mudanca de conta de pagamento ou de NIF depois da activacao";
export const JUSTIFICACAO_DA_MUDANCA_DE_CONTA =
  "o destino do dinheiro de uma loja activa mudou; suspender ate a mudanca se confirmar e decisao do revisor";

/** Uma volta a cada hora: o prazo mais curto que estas regras medem é de dias (*proposta*). */
export const INTERVALO_DO_TRUST_POR_OMISSAO_MS = 3_600_000;

export interface ResultadoDoCicloDoTrust {
  /** Quantos sinais (ou encerramentos) cada varredura que correu produziu. */
  readonly feitas: Readonly<Partial<Record<Varredura, number>>>;
  /** As que falharam, pelo nome. */
  readonly falhas: readonly Varredura[];
}

export interface OpcoesDoCicloDoTrust {
  /** O conjunto de ligações do `kamba_batch`. */
  readonly lote: ConjuntoSql;
  /** O serviço do lado do lote: com o estado dos tenants, para fechar encerramentos. */
  readonly servico: ServicoDeTrust;
  readonly metricas: MetricasDoTrust;
  readonly politica?: PoliticaDeRisco;
  readonly relogio?: () => Date;
  /**
   * O interruptor da correlação entre tenants (KAM-208, D1). **Por omissão,
   * `desligada`**: quem monta o ciclo lê-o do ambiente com o
   * `estadoDaCorrelacao`, que em `prod` nunca dá `ligada`.
   */
  readonly correlacao?: EstadoDaCorrelacao;
}

/** Contadores que guardam e só contam quando a transacção confirma. */
class ContadoresAdiados implements ContadoresDoTrust {
  readonly #sinais: TipoDeSinal[] = [];
  readonly #sancoes: (readonly [Passo, Origem])[] = [];

  sinal(tipo: TipoDeSinal): void {
    this.#sinais.push(tipo);
  }

  sancao(passo: Passo, origem: Origem): void {
    this.#sancoes.push([passo, origem]);
  }

  despejar(em: ContadoresDoTrust): void {
    for (const t of this.#sinais) em.sinal(t);
    for (const [p, o] of this.#sancoes) em.sancao(p, o);
  }
}

export class CicloDoTrust {
  readonly #o: OpcoesDoCicloDoTrust;
  #aCorrer: Promise<ResultadoDoCicloDoTrust> | null = null;

  constructor(o: OpcoesDoCicloDoTrust) {
    this.#o = o;
  }

  /** Uma volta. Duas pedidas ao mesmo tempo são uma. */
  correr(): Promise<ResultadoDoCicloDoTrust> {
    if (this.#aCorrer !== null) return this.#aCorrer;
    this.#aCorrer = this.#volta().finally(() => {
      this.#aCorrer = null;
    });
    return this.#aCorrer;
  }

  agendar(intervaloMs: number, aoTerminar: (r: ResultadoDoCicloDoTrust) => void): () => void {
    if (!Number.isInteger(intervaloMs) || intervaloMs < 1_000) throw new RangeError("intervalo do ciclo abaixo de 1 s");
    const t = setInterval(() => {
      void this.correr().then(aoTerminar);
    }, intervaloMs);
    t.unref();
    return () => clearInterval(t);
  }

  async #volta(): Promise<ResultadoDoCicloDoTrust> {
    const feitas: Partial<Record<Varredura, number>> = {};
    const falhas: Varredura[] = [];
    const opcoes = (contadores: ContadoresDoTrust) => ({
      politica: this.#o.politica ?? POLITICA_DE_RISCO,
      contadores,
      ...(this.#o.relogio === undefined ? {} : { relogio: this.#o.relogio }),
    });
    const passos: readonly (readonly [Varredura, () => Promise<number>])[] = [
      ["nao_entrega", () => this.#numaTransaccao("nao_entrega", (bd, c) => varrerNaoEntregas(bd, opcoes(c)))],
      ["fotos", () => this.#numaTransaccao("fotos", (bd, c) => varrerFotos(bd, opcoes(c)))],
      ["encerramentos", () => this.#encerramentos()],
      ["mudancas_de_conta", () => this.#mudancasDeConta()],
      // KAM-208: a purga corre sempre; a comparação, só com o interruptor ligado.
      ["pseudonimos", () => this.#numaTransaccao("pseudonimos", (bd) => purgarPseudonimos(bd, opcoes(new ContadoresAdiados())))],
      ...(this.#o.correlacao === "ligada"
        ? [
            [
              "compradores_do_dono",
              () => this.#numaTransaccao("compradores_do_dono", (bd, c) => varrerCompradoresDoDono(bd, opcoes(c))),
            ] as const,
          ]
        : []),
    ];
    for (const [nome, passo] of passos) {
      try {
        feitas[nome] = await passo();
        this.#o.metricas.varredura(nome, "concluida");
      } catch {
        falhas.push(nome);
        this.#o.metricas.varredura(nome, "falhou");
      }
    }
    return { feitas, falhas };
  }

  /**
   * A varredura e a sua linha de auditoria, na mesma transacção, numa ligação
   * dedicada. **Os contadores só contam depois do `COMMIT`**: uma corrida
   * desfeita não grava os sinais, e contá-los era contá-los outra vez na volta
   * seguinte (achado 5 da revisão adversarial).
   */
  async #numaTransaccao(
    nome: Varredura,
    varrer: (bd: ClienteSql, contadores: ContadoresDoTrust) => Promise<number>,
  ): Promise<number> {
    const ligacao = await this.#o.lote.connect();
    const adiados = new ContadoresAdiados();
    let estragada: Error | undefined;
    try {
      const n = await comBatch(ligacao, `ts_varredura_${nome}`, async () => {
        const n = await varrer(ligacao, adiados);
        await ligacao.query(SQL_AUDITAR_VARREDURA, [ACTOR_DAS_VARREDURAS, nome, `${nome}:${n}`]);
        return n;
      });
      adiados.despejar(this.#o.metricas);
      return n;
    } catch (erro) {
      estragada = erro instanceof Error ? erro : new Error("varredura de trust falhou");
      throw erro;
    } finally {
      ligacao.release(estragada);
    }
  }

  /**
   * Um caso `trust` para cada `mudanca_de_conta` sem caso, e a escada
   * automática sobre o sinal (o *trigger* grava-o sem a correr). A proposta é a
   * `suspensao`, com a justificação do salto escrita: o dinheiro de uma loja
   * activa passou a ir para outro sítio, e a **suspensão** é de um revisor
   * (*proposta*). A escada automática corre sobre este sinal como sobre
   * qualquer outro, com os pesos da `POLITICA_DE_RISCO` do KAM-097: duas
   * mudanças (peso 30 cada) chegam à `limitacao` antes de o revisor ver o caso.
   * É a política, *proposta*, e calibra-se com ela.
   */
  async #mudancasDeConta(): Promise<number> {
    let n = 0;
    let primeiraFalha: unknown;
    for (const l of (await this.#o.lote.query(SQL_MUDANCAS_DE_CONTA_SEM_CASO)).rows) {
      // Um sinal que falha não tapa os seguintes (achado 6 da revisão
      // adversarial): a volta tenta-os todos, audita, e só depois se diz falhada.
      try {
        const sinal: SinalGravado = {
          id: String(l["id"]),
          tenantId: String(l["tenant_id"]),
          tipo: "mudanca_de_conta",
          severidade: "alta",
          refEvento: String(l["ref_evento"]),
          detalhe: {},
          ocorridoEm: l["ocorrido_em"] instanceof Date ? l["ocorrido_em"] : new Date(String(l["ocorrido_em"])),
        };
        await this.#o.servico.avaliarEscada(sinal.tenantId, sinal);
        const r = await this.#o.servico.proporSancao({
          tenantId: sinal.tenantId,
          passo: "suspensao",
          motivoInterno: MOTIVO_DA_MUDANCA_DE_CONTA,
          sinais: [sinal.id],
          justificacaoDoSalto: JUSTIFICACAO_DA_MUDANCA_DE_CONTA,
          chave: `conta.${sinal.id}`,
        });
        if (r.estado !== "nao_elegivel" && !r.repetido) {
          n++;
          // O sinal nasceu no *trigger*, fora do serviço: conta-se aqui, uma vez,
          // quando o caso dele abre (achado 6 da segunda revisão).
          this.#o.metricas.sinal("mudanca_de_conta");
        }
      } catch (erro) {
        primeiraFalha ??= erro;
      }
    }
    await this.#o.lote.query(SQL_AUDITAR_VARREDURA, [ACTOR_DAS_VARREDURAS, "mudancas_de_conta", `mudancas_de_conta:${n}`]);
    if (primeiraFalha !== undefined) throw primeiraFalha;
    return n;
  }

  async #encerramentos(): Promise<number> {
    const repositorio = new RepositorioDeTrustSql(this.#o.lote, "lote");
    const n = await this.#o.servico.fecharEncerramentos((ate) => repositorio.encerramentosPorFechar(ate));
    await this.#o.lote.query(SQL_AUDITAR_VARREDURA, [ACTOR_DAS_VARREDURAS, "encerramentos", `encerramentos:${n}`]);
    return n;
  }
}
