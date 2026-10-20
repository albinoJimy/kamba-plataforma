/**
 * Guarda do Fluxo B: só o Fluxo A em produção no Piloto (ADR-011, KAM-014).
 *
 * É o **espelho TypeScript** de `libs/py-core/src/kamba_core/fluxo_piloto.py`
 * (KAM-004). As duas implementações têm de recusar as mesmas coisas pela mesma
 * ordem, e há um teste que lhes compara as constantes e os resultados contra a
 * mesma base — a mesma disciplina que o `tenant_guard` e o `logger` já têm nas
 * duas linguagens.
 *
 * Existe porque o critério 5 do KAM-014 pede **duas** coisas, e o espelho
 * Python só dá uma: «um canal `origem='plataforma'` ou `vertical='assistente'`
 * é recusado (0 *jobs*, alerta)» é em **execução**, por mensagem, dentro do
 * CHR — e o CHR é Node. «o arranque falha se existir tal linha em produção» é
 * no arranque, e o espelho Python serve o AGR mas não serve o
 * `services/worker-canal`, que não tem Python.
 *
 * ## As três formas de falhar fechado, as mesmas do espelho
 *
 * **A variável.** `piloto` é o único valor que o canon define. Ausente, vazia
 * ou com outro valor, a guarda levanta — não se desliga. O valor que um dia a
 * desligar é consequência de a decisão D2 fechar; inventá-lo aqui seria
 * fechá-la por omissão.
 *
 * **A visibilidade.** A guarda conta linhas, e uma contagem só vale se quem
 * conta vir todas. Antes de contar, prova que vê tudo (`SQL_VISIBILIDADE`). Com
 * `kamba_app`, levanta `GuardaCegaError` — que é o comportamento certo, e não um
 * defeito a contornar.
 *
 * **A leitura.** Só lê. Não confirma nem desfaz nada.
 *
 * ## A recusa em execução não lê a base
 *
 * `recusaDoFluxoB` é uma função pura sobre o contexto que o resolvedor já
 * trouxe. Ir à base por mensagem para perguntar o que a resolução acabou de
 * responder era uma ida a mais por mensagem, e a *cache* de 60 s guarda
 * exactamente estes campos.
 */

import type { ProcessEnv } from "../index.ts";
import { SQL_GUARDA_FLUXO_B, SQL_VISIBILIDADE } from "./consultas.ts";
import {
  type ChannelContext,
  type ClienteDoChr,
  FASE_PILOTO,
  ORIGEM_DE_PLATAFORMA,
  TIPO_DE_PLATAFORMA,
  VARIAVEL_DA_FASE,
  VERTICAIS_DO_PILOTO,
} from "./contrato.ts";

/** `KAMBA_FASE` está ausente ou tem um valor que o canon não define. */
export class FaseNaoDefinidaError extends Error {
  constructor(encontrado: string) {
    super(
      `${VARIAVEL_DA_FASE} tem de ser '${FASE_PILOTO}' (encontrado: ` +
        `${JSON.stringify(encontrado)}). E o unico valor que o canon define; um ` +
        "valor ausente ou desconhecido nao desliga a guarda do ADR-011.",
    );
    this.name = "FaseNaoDefinidaError";
  }
}

/** O papel desta ligação pode não ver todas as linhas: a contagem não vale. */
export class GuardaCegaError extends Error {
  constructor() {
    super(
      "a guarda do ADR-011 nao consegue provar que ve todas as linhas: ha " +
        "row-level security activa em `platform.tenants` ou em " +
        "`platform.tenant_channels` e o papel desta ligacao nao a contorna nem " +
        "tem politica de leitura total. Uma contagem de zero aqui nao significa " +
        "que nao ha Fluxo B. A guarda corre como `kamba_resolver`, nao como " +
        "`kamba_app`.",
    );
    this.name = "GuardaCegaError";
  }
}

/** Há dados de Fluxo B numa base que corre em fase de Piloto. */
export class FluxoBNoPilotoError extends Error {
  constructor(encontrados: readonly string[]) {
    super(
      `o arranque foi recusado: ha dados de Fluxo B e a fase e '${FASE_PILOTO}' ` +
        `(ADR-011: so o Fluxo A em producao no Piloto). ${encontrados.join("; ")}.`,
    );
    this.name = "FluxoBNoPilotoError";
  }
}

/** A fase declarada, ou lança. */
export function exigirFaseDoPiloto(ambiente: ProcessEnv): void {
  const fase = ambiente[VARIAVEL_DA_FASE] ?? "";
  if (fase !== FASE_PILOTO) throw new FaseNaoDefinidaError(fase);
}

/**
 * Porque é que este canal é Fluxo B, ou `null` se não é.
 *
 * Função pura sobre o `ChannelContext` e o `tipo` do tenant. A terceira
 * verificação é **mais larga** do que o critério, que nomeia
 * `vertical = 'assistente'`: lista de permitidas, como no espelho Python, para
 * que `assistente_v2` também não passe.
 */
export function recusaDoFluxoB(
  contexto: ChannelContext,
  tipoTenant: string,
): string | null {
  if (tipoTenant === TIPO_DE_PLATAFORMA) {
    return `platform.tenants.tipo = '${TIPO_DE_PLATAFORMA}'`;
  }
  if (contexto.origem === ORIGEM_DE_PLATAFORMA) {
    return `platform.tenant_channels.origem = '${ORIGEM_DE_PLATAFORMA}'`;
  }
  const permitidas: readonly string[] = VERTICAIS_DO_PILOTO;
  if (!permitidas.includes(contexto.vertical)) {
    return (
      "platform.tenant_channels.vertical fora de " +
      `{${VERTICAIS_DO_PILOTO.join(", ")}} (inclui 'assistente')`
    );
  }
  return null;
}

/** O que a guarda de arranque contou. */
export interface ContagemDoFluxoB {
  readonly tenantsPlataforma: number;
  readonly canaisPlataforma: number;
  readonly verticaisFora: number;
}

function inteiro(valor: unknown): number {
  if (typeof valor === "number" && Number.isInteger(valor)) return valor;
  // O `pg` devolve `count(*)` como texto (é `bigint`), e o `pg8000` como
  // inteiro. Os dois passam por aqui, e um `NaN` silencioso dava uma contagem
  // de zero — que é precisamente a resposta que esta guarda não pode inventar.
  if (typeof valor === "string" && /^[0-9]+$/.test(valor)) return Number(valor);
  throw new GuardaCegaError();
}

/**
 * Levanta se o serviço não pode arrancar. Não devolve nada quando pode.
 *
 * @param cliente ligação de `kamba_resolver`, **sem** contexto de tenant.
 * @throws {FaseNaoDefinidaError} se `KAMBA_FASE` não for `piloto`.
 * @throws {GuardaCegaError} se o papel não provar que vê todas as linhas.
 * @throws {FluxoBNoPilotoError} se houver linhas de Fluxo B.
 */
export async function verificarArranque(
  cliente: ClienteDoChr,
  ambiente: ProcessEnv,
): Promise<ContagemDoFluxoB> {
  exigirFaseDoPiloto(ambiente);

  const visivel = await cliente.query(SQL_VISIBILIDADE, []);
  if (visivel.rows[0]?.ve_tudo !== true) throw new GuardaCegaError();

  const contado = await cliente.query(SQL_GUARDA_FLUXO_B, [
    TIPO_DE_PLATAFORMA,
    ORIGEM_DE_PLATAFORMA,
    [...VERTICAIS_DO_PILOTO],
  ]);
  const linha = contado.rows[0] ?? {};
  const contagem: ContagemDoFluxoB = {
    tenantsPlataforma: inteiro(linha.tenants_plataforma),
    canaisPlataforma: inteiro(linha.canais_plataforma),
    verticaisFora: inteiro(linha.verticais_fora),
  };

  const encontrados: string[] = [];
  if (contagem.tenantsPlataforma > 0) {
    encontrados.push(
      `${contagem.tenantsPlataforma} linha(s) com platform.tenants.tipo = ` +
        `'${TIPO_DE_PLATAFORMA}'`,
    );
  }
  if (contagem.canaisPlataforma > 0) {
    encontrados.push(
      `${contagem.canaisPlataforma} linha(s) com ` +
        `platform.tenant_channels.origem = '${ORIGEM_DE_PLATAFORMA}'`,
    );
  }
  if (contagem.verticaisFora > 0) {
    encontrados.push(
      `${contagem.verticaisFora} linha(s) com ` +
        "platform.tenant_channels.vertical fora de " +
        `{${VERTICAIS_DO_PILOTO.join(", ")}} (inclui 'assistente')`,
    );
  }
  if (encontrados.length > 0) throw new FluxoBNoPilotoError(encontrados);
  return contagem;
}
