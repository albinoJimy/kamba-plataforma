/**
 * Cálculo de disponibilidade (KAM-047, critério 2).
 *
 * «Disponibilidade = `availability_rules` do recurso menos marcações activas; o
 * modelo nunca calcula horas livres» (bloco, Detalhes Técnicos; ADR-007).
 *
 * O corte em slots é **uma função pura** destes dois conjuntos, e está separado
 * do SQL de propósito: é a parte que mais regras tem e a que mais barato é
 * provar sem levantar um PostgreSQL. A junção com o fuso, essa, fica em SQL
 * (`SQL_GRELHA`), porque é o `tzdata` do servidor que sabe fusos.
 *
 * ## A grelha é alinhada à abertura, e não à hora redonda
 *
 * Um recurso que abre às 9h05 com serviços de 30 minutos oferece 9h05, 9h35,
 * 10h05 — e não 9h30, 10h00. A alternativa (alinhar ao relógio) descartava os
 * primeiros 25 minutos de cada janela sem o dizer a ninguém, e para um serviço
 * de 90 minutos descartava mais de uma hora por dia.
 *
 * ## O que é descartado, e porquê cada coisa
 *
 * - **Um slot que não cabe inteiro na janela.** Uma janela das 9 às 10 com um
 *   serviço de 45 minutos dá **um** slot (9h00–9h45) e não dois: o segundo
 *   acabava às 10h30, depois de o recurso fechar.
 * - **Um slot que toca uma marcação activa.** A sobreposição é a mesma que a
 *   restrição de exclusão mede, e com a mesma semântica `[)`: adjacente não é
 *   sobreposto, pelo que o slot que começa quando uma marcação acaba **é**
 *   oferecido.
 * - **Um slot no passado.** Um slot que já começou não se marca, e oferecê-lo
 *   gastava uma das dez linhas da lista para uma opção que a base aceitaria e
 *   que o cliente não pode cumprir.
 *
 * ## Dez, e porque é que o corte é no fim
 *
 * `MAXIMO_DE_OPCOES` é o limite de linhas de uma lista interactiva da Meta
 * (CONFIRMADO, E1 §7). O corte faz-se **depois** de ordenar por instante, e não
 * durante a varredura por recurso: cortar a meio devolvia as dez primeiras do
 * primeiro recurso e deixava o cliente sem a opção das 9h de um recurso que a
 * varredura só visitasse depois. O que o cliente quer são as dez **mais
 * próximas**, venham de onde vierem.
 */

import { MAXIMO_DE_OPCOES, type Opcao } from "./contrato.ts";
import { derivarSlotId, type Slot } from "./slots.ts";

/** Uma janela de abertura de um recurso, já resolvida em instantes. */
export interface Janela {
  readonly resourceId: string;
  readonly abreAt: Date;
  readonly fechaAt: Date;
}

/** Um intervalo já ocupado por uma marcação activa. */
export interface Ocupacao {
  readonly resourceId: string;
  readonly inicioAt: Date;
  readonly fimAt: Date;
}

/** `[a1, a2)` e `[b1, b2)` sobrepõem-se? Adjacente não sobrepõe. */
function sobrepoe(a1: number, a2: number, b1: number, b2: number): boolean {
  return a1 < b2 && b1 < a2;
}

/**
 * Os slots livres, ordenados por instante e cortados em `MAXIMO_DE_OPCOES`.
 *
 * `agora` entra como argumento e não se lê do relógio aqui: é o que permite a
 * uma bateria afirmar o que acontece numa fronteira sem esperar por ela.
 */
export function slotsLivres(
  janelas: readonly Janela[],
  ocupado: readonly Ocupacao[],
  duracaoMin: number,
  agora: Date,
  ate?: Date,
): readonly Slot[] {
  if (!Number.isSafeInteger(duracaoMin) || duracaoMin <= 0) {
    throw new RangeError(
      `duracao_min tem de ser um inteiro positivo (recebido: ${duracaoMin})`,
    );
  }
  const duracaoMs = duracaoMin * 60 * 1000;
  const limiteInferior = agora.getTime();
  // **O limite superior faltava**, e a revisão adversarial mediu o efeito: o
  // `ateAt` pedido só servia para gerar dias na `SQL_GRELHA`, e aqui nada
  // cortava — quem pedisse «esta manhã» recebia a grelha do dia inteiro, com a
  // tarde a gastar as dez linhas. `Infinity` quando ninguém pede, para que o
  // caminho sem intervalo continue a ser o mesmo código.
  const limiteSuperior = ate === undefined ? Infinity : ate.getTime();

  // Por recurso, para não comparar um slot de um recurso com a ocupação de
  // outro — que foi o defeito que uma primeira versão deste ficheiro tinha e
  // que escondia metade das horas de uma PME com dois profissionais.
  const porRecurso = new Map<string, Ocupacao[]>();
  for (const o of ocupado) {
    const lista = porRecurso.get(o.resourceId);
    if (lista === undefined) porRecurso.set(o.resourceId, [o]);
    else lista.push(o);
  }

  const encontrados: { inicio: number; fim: number; resourceId: string }[] = [];
  for (const janela of janelas) {
    const abre = janela.abreAt.getTime();
    const fecha = janela.fechaAt.getTime();
    const ocupacoes = porRecurso.get(janela.resourceId) ?? [];
    for (let inicio = abre; inicio + duracaoMs <= fecha; inicio += duracaoMs) {
      const fim = inicio + duracaoMs;
      if (inicio < limiteInferior) continue;
      // O slot tem de **caber** dentro do intervalo pedido, não só começar
      // dentro: um slot que começa às 09h55 e acaba às 10h25 não é «esta
      // manhã» se a manhã acaba às 10h.
      if (fim > limiteSuperior) continue;
      let livre = true;
      for (const o of ocupacoes) {
        if (sobrepoe(inicio, fim, o.inicioAt.getTime(), o.fimAt.getTime())) {
          livre = false;
          break;
        }
      }
      if (livre) encontrados.push({ inicio, fim, resourceId: janela.resourceId });
    }
  }

  // Por instante, e o `resourceId` desempata: sem o segundo critério, dois
  // recursos livres à mesma hora saíam numa ordem que depende da varredura, e a
  // lista de dez opções deixava de ser determinística para os mesmos dados — o
  // que torna um teste de contrato impossível de escrever.
  encontrados.sort((a, b) =>
    a.inicio !== b.inicio
      ? a.inicio - b.inicio
      : a.resourceId < b.resourceId
        ? -1
        : a.resourceId > b.resourceId
          ? 1
          : 0,
  );

  return encontrados.slice(0, MAXIMO_DE_OPCOES).map((s) => ({
    serviceId: "",
    resourceId: s.resourceId,
    inicioAt: new Date(s.inicio).toISOString(),
    fimAt: new Date(s.fim).toISOString(),
  }));
}

/**
 * As opções com o `slot_id` assinado, prontas a sair como *facts* `datetime`.
 *
 * O `serviceId` entra aqui e não em `slotsLivres` porque é ele que faz parte do
 * token assinado: dois serviços de igual duração no mesmo recurso e à mesma
 * hora produzem o **mesmo** intervalo e `slot_id` **diferentes**, e sem o
 * serviço no corpo do token a confirmação de um marcava o outro.
 */
export function opcoesComSlotId(
  segredo: Buffer,
  tenantId: string,
  serviceId: string,
  slots: readonly Slot[],
): readonly Opcao[] {
  return slots.map((s) => {
    const slot: Slot = { ...s, serviceId };
    return {
      slotId: derivarSlotId(segredo, tenantId, slot),
      serviceId,
      resourceId: slot.resourceId,
      inicioAt: slot.inicioAt,
      fimAt: slot.fimAt,
    };
  });
}
