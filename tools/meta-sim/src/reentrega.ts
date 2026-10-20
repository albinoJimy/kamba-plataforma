/**
 * O modo de re-entrega: sete dias de *backoff* em menos de um minuto
 * (KAM-024, critério 6).
 *
 * O critério pede «reenvia o mesmo webhook com *backoff* exponencial comprimido
 * (7 dias simulados em ≤ 1 min) para provar idempotência». As duas metades
 * importam pela mesma razão:
 *
 * - **o mesmo webhook**, byte a byte — se os bytes mudassem, o `jobId` do GWY
 *   (que é o `sha256` do corpo bruto) mudava com eles, e o teste provava que
 *   duas coisas diferentes dão dois *jobs*, que é o contrário do que se quer;
 * - **sete dias**, porque é esse o horizonte de repetição da Meta, e uma
 *   idempotência que só é verdadeira na primeira hora não serve: a quinta
 *   tentativa chega num dia em que a janela de 24 h já fechou e a conversa já
 *   foi fundida.
 *
 * ## O que é NÃO VERIFICADO, e portanto é parâmetro
 *
 * **O calendário exacto de repetições da Meta não está confirmado.** O `E1` §5
 * confirma que a Meta repete «até sete dias»; as páginas lidas **não** dão os
 * intervalos. Este módulo **não os inventa**: gera um *backoff* exponencial
 * declarado — base, factor e tecto, todos explícitos — que **cobre** sete dias,
 * e diz que é uma aproximação. Quem obtiver o calendário real substitui
 * `CALENDARIO_PROPOSTO` e os testes de idempotência continuam a valer, porque o
 * que eles medem é «N entregas do mesmo corpo dão 1 efeito», e isso não depende
 * dos intervalos.
 *
 * O mesmo vale para o *timeout* do webhook: o ticket diz-o por extenso («o
 * *timeout* exacto do webhook e o *pair rate limit* são NÃO VERIFICADOS (L2); o
 * simulador não os inventa e expõe-nos como parâmetros configuráveis»), e é o
 * que `Opcoes.esperaMaxima` é.
 *
 * ## A compressão, e porque é que não é um `sleep` escalado
 *
 * O ingénuo seria dormir `atraso / escala`. Com sete dias e um minuto, a escala
 * é 10 080, e as primeiras esperas dão fracções de milissegundo — que o
 * `setTimeout` arredonda para 1 ms cada, de modo que o tempo real deixa de ser
 * proporcional e passa a ser «uma tentativa por milissegundo». Pior: o teste
 * media o `setTimeout` e não a idempotência.
 *
 * Por isso o tempo simulado é **explícito** e o real é **mínimo**: cada
 * tentativa leva o seu instante simulado no resultado, e a espera real é a que
 * o chamador pedir (por omissão, nenhuma). O critério «7 dias em ≤ 1 min» passa
 * a ser uma afirmação sobre o que foi simulado e sobre o relógio de parede, e
 * as duas medem-se à parte — que é o que `Relatorio` traz.
 */

/**
 * O calendário **proposto** de repetições, em segundos desde a primeira entrega.
 *
 * Exponencial de base 60 s e factor 4, truncado em 24 h, até passar os sete
 * dias. Dá doze tentativas: 0, 1 min, 5 min, 21 min, 1 h 25, 5 h 41, 24 h, e
 * depois de 24 em 24 h até 7 dias. É **proposta** — ver a nota do módulo.
 */
export const CALENDARIO_PROPOSTO: readonly number[] = (() => {
  const SETE_DIAS = 7 * 24 * 60 * 60;
  const TECTO = 24 * 60 * 60;
  const instantes: number[] = [0];
  let atraso = 60;
  let instante = 0;
  while (instante < SETE_DIAS) {
    instante += Math.min(atraso, TECTO);
    instantes.push(Math.min(instante, SETE_DIAS));
    atraso *= 4;
  }
  return instantes;
})();

/** Uma tentativa: a sua ordem, o instante simulado, e o que o destino respondeu. */
export interface Tentativa {
  readonly numero: number;
  /** Segundos desde a primeira entrega, no tempo **simulado**. */
  readonly instanteSimulado: number;
  readonly estado: number;
  /** Milissegundos de relógio de parede que esta tentativa levou. */
  readonly duracaoMs: number;
}

/** O relatório de uma re-entrega. As duas grandezas do critério, separadas. */
export interface Relatorio {
  readonly tentativas: readonly Tentativa[];
  /** O horizonte simulado, em segundos. Tem de chegar aos sete dias. */
  readonly horizonteSimuladoS: number;
  /** O tempo real que a execução levou, em milissegundos. Tem de caber no minuto. */
  readonly duracaoRealMs: number;
  /** Quantas tentativas o destino aceitou com 200. */
  readonly aceites: number;
}

/** Sete dias em segundos. O horizonte que o critério nomeia. */
export const SETE_DIAS_S = 7 * 24 * 60 * 60;

/** O tecto de tempo real do critério, em milissegundos. */
export const MINUTO_MS = 60_000;

/** O que fazer a cada tentativa. Devolve o estado HTTP do destino. */
export type Entregar = (tentativa: number, instanteSimulado: number) => Promise<number>;

export interface Opcoes {
  /** O calendário simulado, em segundos. Por omissão, o proposto. */
  readonly calendario?: readonly number[];
  /**
   * Milissegundos de espera real **entre** tentativas. Por omissão, 0.
   *
   * Existe porque um destino assíncrono (uma fila a drenar) pode precisar de um
   * instante para acompanhar; não existe para «simular» o tempo, que é o que o
   * `instanteSimulado` faz.
   */
  readonly esperaMs?: number;
  /**
   * O *timeout* por tentativa, em milissegundos. **NÃO VERIFICADO** do lado da
   * Meta: é parâmetro, e o simulador não escolhe um valor por ela.
   */
  readonly esperaMaxima?: number;
}

function dormir(ms: number): Promise<void> {
  return new Promise((resolver) => {
    setTimeout(resolver, ms);
  });
}

/**
 * Reentrega o mesmo webhook por todo o calendário e devolve o relatório.
 *
 * Quem chama passa `entregar`, que faz o POST — contra o GWY em memória, nos
 * testes, ou contra um `staging`, na *suite* online. O que esta função garante é
 * que **o corpo não muda**: ela nunca o toca, e por isso a idempotência que o
 * teste medir é a do destino.
 */
export async function reentregar(entregar: Entregar, opcoes: Opcoes = {}): Promise<Relatorio> {
  const calendario = opcoes.calendario ?? CALENDARIO_PROPOSTO;
  const esperaMs = opcoes.esperaMs ?? 0;
  const tentativas: Tentativa[] = [];
  const inicio = performance.now();

  for (let i = 0; i < calendario.length; i += 1) {
    const instanteSimulado = calendario[i] ?? 0;
    const antes = performance.now();
    const estado = await entregar(i + 1, instanteSimulado);
    tentativas.push({
      numero: i + 1,
      instanteSimulado,
      estado,
      duracaoMs: performance.now() - antes,
    });
    if (esperaMs > 0 && i + 1 < calendario.length) await dormir(esperaMs);
  }

  const ultimo = calendario[calendario.length - 1] ?? 0;
  return {
    tentativas,
    horizonteSimuladoS: ultimo,
    duracaoRealMs: performance.now() - inicio,
    aceites: tentativas.filter((t) => t.estado === 200).length,
  };
}

/**
 * O relatório cumpre o critério 6?
 *
 * Duas condições, e as duas têm de ser verdade: o horizonte simulado chega aos
 * sete dias, e o tempo real cabe no minuto. Devolve as razões em vez de um
 * booleano para que a *suite* possa escrever na evidência **qual** das duas
 * falhou — «o teste passou» e «o teste passou pelas duas razões» não são a
 * mesma afirmação.
 */
export function razoesDeFalha(relatorio: Relatorio): readonly string[] {
  const razoes: string[] = [];
  if (relatorio.horizonteSimuladoS < SETE_DIAS_S) {
    razoes.push(
      `o horizonte simulado e ${relatorio.horizonteSimuladoS}s e o criterio pede ${SETE_DIAS_S}s`,
    );
  }
  if (relatorio.duracaoRealMs > MINUTO_MS) {
    razoes.push(
      `a execucao levou ${Math.round(relatorio.duracaoRealMs)}ms e o criterio pede <= ${MINUTO_MS}ms`,
    );
  }
  return razoes;
}
