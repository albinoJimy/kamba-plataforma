/**
 * As métricas do SMS (KAM-116, critério 8).
 *
 *     sms_sent_total              counter    envios, por fornecedor e resultado
 *     sms_delivery_ratio          gauge      entregues / recibos, por operadora
 *     sms_latency_s               histogram  do envio ao recibo de entrega
 *     sms_cost_kz_total           counter    custo acumulado, em Kz
 *     sms_delivery_below_minimum  gauge      1 quando a janela está abaixo do mínimo
 *
 * As quatro primeiras são as que o critério nomeia. A quinta entra porque o
 * critério pede «**alerta** se a entrega cair abaixo do mínimo em 20 envios», e
 * uma condição de alerta que não é uma série não se alerta: a regra do
 * Prometheus precisa de ler um número, e calcular «os últimos 20» a partir de
 * um `ratio` acumulado não dá o mesmo resultado. A janela é deste módulo, que é
 * quem sabe a ordem dos recibos; a série diz apenas se ela está abaixo.
 *
 * ## Os dois números que este ticket NÃO pode afirmar
 *
 * O mínimo de entrega (**95%** por operadora) e a latência (**p95 ≤ 30 s**) são
 * ***propostas***, e o próprio bloco do ticket di-lo. A entrega de SMS para a
 * Unitel e a Africell é **NÃO VERIFICADA** (`../../../../docs/tecnica/01` L10;
 * `../../../../docs/tecnica/10` §6.3), e a amostra de ≥ 40 envios por operadora
 * que o critério 2 pede é **sinal e não prova** — também isso está escrito no
 * bloco.
 *
 * O que este ficheiro entrega é o **instrumento**: as constantes com os valores
 * propostos, o corte de 30 s no histograma para o p95 se ler sem interpolar, e
 * a janela de 20. Os números saem com tráfego real no Piloto. Uma métrica que
 * mede a proposta não torna a proposta num facto.
 *
 * ## A operadora é uma etiqueta e **não** se deriva do número
 *
 * `OPERADORAS` tem `desconhecida`, e ela é o valor por omissão. Derivar a
 * operadora dos primeiros algarismos exigia o plano de numeração de Angola, que
 * não tem fonte primária no conjunto (ver `destino.ts`) e que a portabilidade
 * torna errado de qualquer maneira. A operadora vem do **recibo**, quando o
 * agregador a diz; quando não diz, fica `desconhecida` e a `sms_delivery_ratio`
 * dessa série é o que há. Pôr lá um palpite dava um número preciso e errado, que
 * é pior do que um número ausente.
 *
 * ## O custo acumula em unidade menor inteira
 *
 * O §2 do dicionário manda «dinheiro em unidade menor inteira (`*_minor`) com
 * moeda explícita; nunca vírgula flutuante». O nome da métrica é do critério
 * (`sms_cost_kz_total`, em Kz), pelo que a acumulação é em `bigint` de unidade
 * menor e a exposição é um decimal **formatado do inteiro** — nunca uma divisão
 * em vírgula flutuante. É a mesma escolha do `../pagamentos/dinheiro.ts`, e a
 * razão é a que lá está: `Math.trunc(parseFloat("1024.09") * 100)` dá 102408.
 *
 * ## Nenhuma leva etiqueta de tenant
 *
 * Decisão escrita (`OBS-I` de `../../../../docs/seguranca/ameacas_stride.md`), e
 * aqui há mais: no passo 2 do onboarding **não há tenant** — o tenant nasce no
 * `tenant.approved`, depois do OTP. E nenhuma leva destino: um telefone, mesmo
 * em HMAC, é cardinalidade sem tecto.
 *
 * A forma é a do `../avisos/metricas.ts`: um `Map` de números, em memória, sem
 * dependências, com `exposicao()` no formato do Prometheus.
 */

import { OPERADORAS, type Operadora } from "./contrato.ts";

export const METRICA_ENVIADOS = "sms_sent_total";
export const METRICA_ENTREGA = "sms_delivery_ratio";
export const METRICA_LATENCIA = "sms_latency_s";
export const METRICA_CUSTO = "sms_cost_kz_total";
export const METRICA_ABAIXO = "sms_delivery_below_minimum";

/** Unidade menor por Kz, como no `../pagamentos/dinheiro.ts`. */
export const MINOR_POR_KZ = 100n;

/**
 * O resultado de um envio, para a etiqueta.
 *
 * `repetido` é um resultado e não um detalhe: é a prova, em produção, de que a
 * idempotência está a morder. Sem ele, uma chave repetida não se distinguia de
 * um envio que nunca chegou a ser pedido.
 */
export const RESULTADOS = [
  "aceite",
  "repetido",
  "RATE_LIMITED",
  "INVALID_DESTINATION",
  "PROVIDER_DOWN",
] as const;

export type Resultado = (typeof RESULTADOS)[number];

/**
 * A taxa mínima de entrega por operadora. ***Proposta*** — ver a nota do módulo.
 *
 * Em unidade menor inteira (pontos percentuais × 100) e não em vírgula
 * flutuante, pela mesma razão do custo: `0.95` não tem representação exacta em
 * binário, e um limiar que se compara com `>=` não pode depender disso.
 */
export const MINIMO_DE_ENTREGA_CENTESIMOS = 9_500n;

/** Quantos recibos a janela do alerta considera. Do critério 8: «em 20 envios». */
export const JANELA_DO_ALERTA = 20;

/**
 * Os cortes do histograma, em segundos.
 *
 * O **30** está lá por causa da latência proposta — «p95 ≤ 30 s» —, para que a
 * pergunta se leia do histograma sem interpolar entre dois cortes. É a mesma
 * escolha que o `../avisos/metricas.ts` fez com os 300 s. Os cortes abaixo
 * dizem o caminho normal (um SMS chega em segundos) e os de cima dizem o quanto
 * se passou do alvo quando se passa.
 */
export const CORTES_DA_LATENCIA: readonly number[] = [1, 3, 5, 10, 20, 30, 60, 120, 300];

/** O separador das etiquetas na chave interna. A razão é a do `../avisos/metricas.ts`. */
const JUNTA = "|";

/** Forma de um nome de fornecedor. A mesma do `../avisos/fornecedor.ts`. */
const FORNECEDOR = /^[a-z][a-z0-9_-]{1,62}$/;

/** Levantado quando uma etiqueta não está na lista fechada da sua métrica. */
export class EtiquetaInvalidaError extends Error {
  override readonly name = "EtiquetaInvalidaError";

  constructor(metrica: string, etiquetas: readonly string[]) {
    super(
      `${metrica}: etiquetas ${JSON.stringify(etiquetas)} nao estao na lista fechada. ` +
        "Identificadores (tenant_id, destino, HMAC de destino) nao entram em metricas " +
        "(docs/seguranca/ameacas_stride.md, OBS-I)",
    );
  }
}

const AJUDA: Readonly<Record<string, readonly [string, string]>> = {
  [METRICA_ENVIADOS]: [
    "counter",
    "Envios de SMS por fornecedor e resultado. O resultado repetido e a prova, em producao, de que a idempotencia morde.",
  ],
  [METRICA_ENTREGA]: [
    "gauge",
    "Recibos positivos sobre recibos recebidos, por fornecedor e operadora. O minimo de 0,95 e PROPOSTA: a entrega para Unitel e Africell e NAO VERIFICADA (docs/tecnica/01 L10).",
  ],
  [METRICA_LATENCIA]: [
    "histogram",
    "Segundos do envio ao recibo de entrega. O alvo de 30 s p95 e PROPOSTA, e o corte de 30 esta nos baldes para que o p95 se leia sem interpolar.",
  ],
  [METRICA_CUSTO]: [
    "counter",
    "Custo acumulado em Kz por fornecedor. Acumulado em unidade menor inteira e formatado do inteiro: nunca virgula flutuante (specs/02 §2).",
  ],
  [METRICA_ABAIXO]: [
    "gauge",
    "1 quando os ultimos 20 recibos de uma operadora estao abaixo do minimo proposto, 0 quando nao. A condicao do alerta do criterio 8.",
  ],
};

function exigirFornecedor(fornecedor: string, metrica: string): string {
  if (typeof fornecedor !== "string" || !FORNECEDOR.test(fornecedor)) {
    throw new EtiquetaInvalidaError(metrica, [String(fornecedor)]);
  }
  return fornecedor;
}

function exigirOperadora(operadora: string, metrica: string): Operadora {
  if (!(OPERADORAS as readonly string[]).includes(operadora)) {
    throw new EtiquetaInvalidaError(metrica, [operadora]);
  }
  return operadora as Operadora;
}

/** Formata uma quantia em unidade menor como decimal exacto, sem vírgula flutuante. */
export function kzDeMinor(minor: bigint): string {
  const negativo = minor < 0n;
  const absoluto = negativo ? -minor : minor;
  const inteiro = absoluto / MINOR_POR_KZ;
  const resto = absoluto % MINOR_POR_KZ;
  return `${negativo ? "-" : ""}${inteiro}.${resto.toString().padStart(2, "0")}`;
}

/**
 * Formata centésimos de ponto percentual como **razão**, com quatro decimais.
 *
 * O nome da métrica é `sms_delivery_ratio`: uma razão entre 0 e 1, e não uma
 * percentagem. 9 500 centésimos são 95,00% e **`0.9500`** — publicar `95.00`
 * numa série chamada `ratio` fazia qualquer regra de alerta escrita contra `<
 * 0.95` nunca disparar, porque 95 nunca é menor do que 0,95.
 *
 * Formatado do inteiro, como o custo, e pela mesma razão: uma divisão em
 * vírgula flutuante dava `0.9499999999999999` onde o limiar diz `0.95`.
 */
export function razaoDeCentesimos(centesimos: bigint): string {
  const inteiro = centesimos / 10_000n;
  const resto = centesimos % 10_000n;
  return `${inteiro}.${resto.toString().padStart(4, "0")}`;
}

/** As métricas do SMS, em memória. Só números. */
export class MetricasDeSms {
  readonly #enviados = new Map<string, number>();
  readonly #baldes = new Map<string, Map<number, number>>();
  readonly #somaDaLatencia = new Map<string, number>();
  readonly #contagemDaLatencia = new Map<string, number>();
  readonly #custoMinor = new Map<string, bigint>();
  /** Por `fornecedor|operadora`: recibos positivos e recibos recebidos. */
  readonly #entregues = new Map<string, number>();
  readonly #recibos = new Map<string, number>();
  /** Por `fornecedor|operadora`: os últimos `JANELA_DO_ALERTA` recibos. */
  readonly #janela = new Map<string, boolean[]>();

  /** Conta um envio. */
  contarEnvio(fornecedor: string, resultado: Resultado): void {
    const nome = exigirFornecedor(fornecedor, METRICA_ENVIADOS);
    if (!(RESULTADOS as readonly string[]).includes(resultado)) {
      throw new EtiquetaInvalidaError(METRICA_ENVIADOS, [nome, resultado]);
    }
    // A chave leva o **nome da metrica** a cabeca, como as outras: sem ele, o
    // `ler()` devolvia `fake|aceite`, que nao diz de que serie e, e duas
    // metricas com as mesmas etiquetas colidiam no mesmo `Map`.
    const chave = `${METRICA_ENVIADOS}${JUNTA}${nome}${JUNTA}${resultado}`;
    this.#enviados.set(chave, (this.#enviados.get(chave) ?? 0) + 1);
  }

  /**
   * Acumula o custo de um envio, em unidade menor.
   *
   * Um valor negativo **não entra**: um custo negativo num `counter` faz o
   * Prometheus ler a série como reiniciada, e a soma deixa de querer dizer
   * nada.
   */
  acumularCusto(fornecedor: string, minor: bigint): void {
    const nome = exigirFornecedor(fornecedor, METRICA_CUSTO);
    if (typeof minor !== "bigint" || minor < 0n) return;
    this.#custoMinor.set(nome, (this.#custoMinor.get(nome) ?? 0n) + minor);
  }

  /**
   * Observa a latência do envio ao recibo, em segundos.
   *
   * Um valor que não é finito não entra — um `NaN` no formato de exposição faz
   * o Prometheus descartar a recolha **toda** — e um negativo também não: uma
   * latência negativa é um relógio ao contrário. É a lição que o KAM-017
   * escreveu e que o `../avisos/metricas.ts` repete.
   */
  observarLatencia(fornecedor: string, segundos: number): void {
    const nome = exigirFornecedor(fornecedor, METRICA_LATENCIA);
    if (!Number.isFinite(segundos) || segundos < 0) return;
    this.#somaDaLatencia.set(nome, (this.#somaDaLatencia.get(nome) ?? 0) + segundos);
    this.#contagemDaLatencia.set(nome, (this.#contagemDaLatencia.get(nome) ?? 0) + 1);
    let baldes = this.#baldes.get(nome);
    if (baldes === undefined) {
      baldes = new Map();
      this.#baldes.set(nome, baldes);
    }
    for (const corte of CORTES_DA_LATENCIA) {
      if (segundos <= corte) baldes.set(corte, (baldes.get(corte) ?? 0) + 1);
    }
  }

  /**
   * Conta um recibo: positivo ou não, por operadora.
   *
   * **Os dois números, e não só a razão.** O critério 8 pede uma taxa, e uma
   * taxa precisa de denominador: com a razão sozinha, «90%» não distingue nove
   * de dez entregues de noventa de cem. Publicam-se os dois e a razão lê-se
   * deles — a mesma escolha do `owner_alt_contact_missing` do KAM-115.
   */
  contarRecibo(fornecedor: string, operadora: string, entregue: boolean): void {
    const nome = exigirFornecedor(fornecedor, METRICA_ENTREGA);
    const op = exigirOperadora(operadora, METRICA_ENTREGA);
    const chave = `${nome}${JUNTA}${op}`;
    this.#recibos.set(chave, (this.#recibos.get(chave) ?? 0) + 1);
    if (entregue) this.#entregues.set(chave, (this.#entregues.get(chave) ?? 0) + 1);
    const janela = this.#janela.get(chave) ?? [];
    janela.push(entregue);
    if (janela.length > JANELA_DO_ALERTA) janela.shift();
    this.#janela.set(chave, janela);
  }

  /**
   * A janela dos últimos `JANELA_DO_ALERTA` recibos está abaixo do mínimo?
   *
   * **`false` com a janela incompleta**, e isso é deliberado: o critério diz
   * «abaixo do mínimo **em 20 envios**», e com dezanove recibos não há vinte.
   * Alertar com três recibos, um deles falhado, dava 67% e um alerta sobre
   * nada — que é a maneira mais rápida de ensinar quem está de turno a ignorar
   * o alerta.
   */
  abaixoDoMinimo(fornecedor: string, operadora: string): boolean {
    const nome = exigirFornecedor(fornecedor, METRICA_ABAIXO);
    const op = exigirOperadora(operadora, METRICA_ABAIXO);
    const janela = this.#janela.get(`${nome}${JUNTA}${op}`) ?? [];
    if (janela.length < JANELA_DO_ALERTA) return false;
    const entregues = janela.filter(Boolean).length;
    // Inteiros dos dois lados: centesimos de ponto percentual contra o limiar.
    return BigInt(entregues) * 10_000n < MINIMO_DE_ENTREGA_CENTESIMOS * BigInt(janela.length);
  }

  /** A razão de entrega de uma série, em centésimos de ponto percentual. */
  entregaEmCentesimos(fornecedor: string, operadora: string): bigint | null {
    const chave = `${exigirFornecedor(fornecedor, METRICA_ENTREGA)}${JUNTA}${exigirOperadora(operadora, METRICA_ENTREGA)}`;
    const total = this.#recibos.get(chave) ?? 0;
    if (total === 0) return null;
    return (BigInt(this.#entregues.get(chave) ?? 0) * 10_000n) / BigInt(total);
  }

  ler(): Record<string, number | string> {
    const saida: Record<string, number | string> = {
      ...Object.fromEntries(this.#enviados),
    };
    for (const [chave, total] of this.#recibos) {
      saida[`${METRICA_ENTREGA}${JUNTA}${chave}_total`] = total;
      saida[`${METRICA_ENTREGA}${JUNTA}${chave}_entregues`] = this.#entregues.get(chave) ?? 0;
    }
    for (const [nome, minor] of this.#custoMinor) {
      saida[`${METRICA_CUSTO}${JUNTA}${nome}`] = kzDeMinor(minor);
    }
    for (const [nome, soma] of this.#somaDaLatencia) {
      saida[`${METRICA_LATENCIA}${JUNTA}${nome}_sum`] = soma;
      saida[`${METRICA_LATENCIA}${JUNTA}${nome}_count`] = this.#contagemDaLatencia.get(nome) ?? 0;
    }
    return saida;
  }

  exposicao(): string {
    const linhas: string[] = [];

    const enviados = AJUDA[METRICA_ENVIADOS];
    if (enviados !== undefined) {
      linhas.push(`# HELP ${METRICA_ENVIADOS} ${enviados[1]}`);
      linhas.push(`# TYPE ${METRICA_ENVIADOS} ${enviados[0]}`);
      for (const chave of [...this.#enviados.keys()].sort()) {
        const [, fornecedor, resultado] = chave.split(JUNTA);
        linhas.push(
          `${METRICA_ENVIADOS}{fornecedor="${fornecedor}",resultado="${resultado}"} ` +
            `${this.#enviados.get(chave) ?? 0}`,
        );
      }
    }

    for (const [metrica, serie] of [
      [METRICA_ENTREGA, this.#recibos],
      [METRICA_ABAIXO, this.#recibos],
    ] as const) {
      const descricao = AJUDA[metrica];
      if (descricao === undefined) continue;
      linhas.push(`# HELP ${metrica} ${descricao[1]}`);
      linhas.push(`# TYPE ${metrica} ${descricao[0]}`);
      for (const chave of [...serie.keys()].sort()) {
        const [fornecedor = "", operadora = ""] = chave.split(JUNTA);
        const etiquetas = `{fornecedor="${fornecedor}",operadora="${operadora}"}`;
        if (metrica === METRICA_ABAIXO) {
          linhas.push(`${metrica}${etiquetas} ${this.abaixoDoMinimo(fornecedor, operadora) ? 1 : 0}`);
          continue;
        }
        const centesimos = this.entregaEmCentesimos(fornecedor, operadora);
        // A razao sai como decimal formatado de um inteiro, pela razao do
        // custo: uma divisao em virgula flutuante aqui dava 0.9499999999999999
        // onde o limiar diz 0.95.
        linhas.push(`${metrica}${etiquetas} ${razaoDeCentesimos(centesimos ?? 0n)}`);
        linhas.push(`${metrica}_total${etiquetas} ${this.#recibos.get(chave) ?? 0}`);
        linhas.push(`${metrica}_delivered${etiquetas} ${this.#entregues.get(chave) ?? 0}`);
      }
    }

    const latencia = AJUDA[METRICA_LATENCIA];
    if (latencia !== undefined) {
      linhas.push(`# HELP ${METRICA_LATENCIA} ${latencia[1]}`);
      linhas.push(`# TYPE ${METRICA_LATENCIA} ${latencia[0]}`);
      for (const nome of [...this.#contagemDaLatencia.keys()].sort()) {
        const baldes = this.#baldes.get(nome) ?? new Map<number, number>();
        const contagem = this.#contagemDaLatencia.get(nome) ?? 0;
        for (const corte of CORTES_DA_LATENCIA) {
          linhas.push(
            `${METRICA_LATENCIA}_bucket{fornecedor="${nome}",le="${corte}"} ${baldes.get(corte) ?? 0}`,
          );
        }
        linhas.push(`${METRICA_LATENCIA}_bucket{fornecedor="${nome}",le="+Inf"} ${contagem}`);
        linhas.push(
          `${METRICA_LATENCIA}_sum{fornecedor="${nome}"} ${this.#somaDaLatencia.get(nome) ?? 0}`,
        );
        linhas.push(`${METRICA_LATENCIA}_count{fornecedor="${nome}"} ${contagem}`);
      }
    }

    const custo = AJUDA[METRICA_CUSTO];
    if (custo !== undefined) {
      linhas.push(`# HELP ${METRICA_CUSTO} ${custo[1]}`);
      linhas.push(`# TYPE ${METRICA_CUSTO} ${custo[0]}`);
      for (const nome of [...this.#custoMinor.keys()].sort()) {
        linhas.push(
          `${METRICA_CUSTO}{fornecedor="${nome}"} ${kzDeMinor(this.#custoMinor.get(nome) ?? 0n)}`,
        );
      }
    }

    return `${linhas.join("\n")}\n`;
  }
}

/** A instância do processo, como nos outros módulos desta casa. */
export const METRICAS_DE_SMS = new MetricasDeSms();
