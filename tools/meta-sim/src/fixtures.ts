/**
 * As *fixtures*: uma por item de cobertura, cada uma com a sua própria semente
 * (KAM-024, critérios 1 e 2).
 *
 * ## Uma semente por *fixture*, derivada do nome
 *
 * O ingénuo seria gerar as vinte e sete com um gerador só, pela ordem da lista.
 * Funciona, e cria uma dependência escondida: acrescentar uma *fixture* no meio
 * muda os bytes de **todas** as que vêm depois, e um diff que devia ter uma
 * linha passa a ter vinte e sete ficheiros. Pior, um teste que afirme os bytes
 * de `tipo:sticker` passa a falhar por causa de um `tipo:video` que alguém
 * acrescentou acima, e a mensagem de falha não diz isso.
 *
 * Por isso cada *fixture* tem a sua: `semente/<marca>`. O determinismo que o
 * critério 1 pede («a partir de uma semente, *payloads* byte-idênticos») fica
 * mais forte, não mais fraco — é por *fixture* e não por lista.
 *
 * ## O canal e o interlocutor são os mesmos em todas
 *
 * Saem de uma semente própria (`semente/canal`), e por isso são estáveis e
 * iguais em todas as *fixtures*. É deliberado: um teste de contrato que insira
 * o canal em `tenant_channels` uma vez pode correr todas as *fixtures* contra
 * ele, e as *fixtures* descrevem um negócio a conversar com um cliente — que é
 * o que o tráfego é — em vez de vinte e sete negócios a trocar uma mensagem cada.
 */

import { CAMPOS, type Campo, type Opcoes as OpcoesDeCampo } from "./campos.ts";
import { assinar } from "./assinatura.ts";
import { corpo, serializar, type Corpo } from "./corpo.ts";
import { ESTADOS, type Estado } from "./estados.ts";
import { canalDe, interlocutorDe, type Canal, type Interlocutor } from "./identificadores.ts";
import { ITENS, type Item } from "./cobertura.ts";
import { TIPOS, VARIANTES_INTERACTIVAS, type Tipo } from "./mensagens.ts";
import { Gerador } from "./semente.ts";

/** Uma *fixture* pronta a enviar. */
export interface Fixture {
  /** O item de cobertura que esta *fixture* cobre. */
  readonly item: Item;
  /** O nome do ficheiro, sem extensão. */
  readonly nome: string;
  readonly corpo: Corpo;
  readonly bytes: Uint8Array;
  /** O valor do cabeçalho `x-hub-signature-256`. */
  readonly assinatura: string;
}

/** O cenário comum: o canal e quem fala. */
export interface Cenario {
  readonly canal: Canal;
  readonly quem: Interlocutor;
}

/** O canal e o interlocutor de uma semente. Estáveis, e iguais em toda a suite. */
export function cenarioDe(semente: string): Cenario {
  const g = new Gerador(`${semente}/canal`);
  return { canal: canalDe(g), quem: interlocutorDe(g) };
}

/** O nome de ficheiro de uma marca: `tipo:statuses:read` → `tipo-statuses-read`. */
export function nomeDaMarca(marca: string): string {
  return marca.replace(/:/g, "-");
}

/**
 * As opções de campo que cobrem um item da dimensão «tipo».
 *
 * Devolve `null` para `history`, que é o único item que está nas **duas**
 * dimensões — o critério 1 nomeia-o como tipo e o critério 2 como campo — e
 * cuja *fixture* é a do campo. Duplicá-la dava duas *fixtures* com os mesmos
 * bytes e duas linhas na tabela a dizer a mesma coisa.
 */
function pedidoDoTipo(nome: string, cenario: Cenario): { campo: Campo; opcoes: OpcoesDeCampo } | null {
  const { canal, quem } = cenario;
  if (nome === "history") return null;

  if (nome.startsWith("statuses:")) {
    const estado = nome.slice("statuses:".length) as Estado;
    return { campo: "messages", opcoes: { canal, quem, tipos: [], estados: [estado] } };
  }
  if (nome.startsWith("interactive:")) {
    // A variante vai explícita: sem ela o construtor dá sempre `button_reply`,
    // e a *fixture* de `list_reply` era uma cópia da outra com outro nome — um
    // 100% na tabela de cobertura sem nada por baixo.
    const variante = nome.slice("interactive:".length) as "button_reply" | "list_reply";
    return {
      campo: "messages",
      opcoes: {
        canal,
        quem,
        tipos: ["interactive"],
        variante,
        texto: variante === "list_reply" ? "Linha escolhida" : "Confirmar",
      },
    };
  }
  return { campo: "messages", opcoes: { canal, quem, tipos: [nome as Tipo] } };
}

/** As opções de campo que cobrem um item da dimensão «campo». */
function pedidoDoCampo(campo: Campo, cenario: Cenario): { campo: Campo; opcoes: OpcoesDeCampo } {
  const { canal, quem } = cenario;
  if (campo === "messages") {
    // O campo `messages` cobre-se com **tudo** o que ele pode trazer ao mesmo
    // tempo: as dez formas de item mais os quatro estados. É o caso que prova
    // que `messages` e `statuses` no mesmo `value` dão dois destinos diferentes
    // (`chr` e `outbound`), que é a regra que o KAM-013 mais pode quebrar.
    return { campo, opcoes: { canal, quem, tipos: TIPOS, estados: ESTADOS } };
  }
  if (campo === "account_update") {
    return { campo, opcoes: { canal, quem, motivo: "PRIMARY_INACTIVITY" } };
  }
  return { campo, opcoes: { canal, quem } };
}

/** A *fixture* de um item. */
export function fixtureDe(item: Item, semente: string, segredo: string): Fixture | null {
  const cenario = cenarioDe(semente);
  const pedido =
    item.dimensao === "tipo"
      ? pedidoDoTipo(item.nome, cenario)
      : pedidoDoCampo(item.nome as Campo, cenario);
  if (pedido === null) return null;

  const g = new Gerador(`${semente}/${item.marca}`);
  const montado = corpo(g, { canal: cenario.canal, mudancas: [pedido] });
  const bytes = serializar(montado);
  return {
    item,
    nome: nomeDaMarca(item.marca),
    corpo: montado,
    bytes,
    assinatura: assinar(bytes, segredo),
  };
}

/**
 * Todas as *fixtures* de todos os itens.
 *
 * O `history` como tipo não tem *fixture* própria — a do campo cobre-o — e por
 * isso a contagem de *fixtures* desse item vem da do campo. É o que
 * `contagemPorItem` faz, e está escrito lá porque é a única excepção.
 */
export function todasAsFixtures(semente: string, segredo: string): readonly Fixture[] {
  const saida: Fixture[] = [];
  for (const item of ITENS) {
    const fixture = fixtureDe(item, semente, segredo);
    if (fixture !== null) saida.push(fixture);
  }
  return saida;
}

/**
 * Quantas *fixtures* cobrem cada marca.
 *
 * O `tipo:history` conta a *fixture* de `campo:history`: é o mesmo corpo, e
 * contá-lo como zero dizia que falta uma *fixture* que existe. A excepção está
 * aqui, nomeada, em vez de dentro do gerador — onde ficava escondida.
 */
export function contagemPorItem(fixtures: readonly Fixture[]): Readonly<Record<string, number>> {
  const contagem: Record<string, number> = {};
  for (const fixture of fixtures) {
    contagem[fixture.item.marca] = (contagem[fixture.item.marca] ?? 0) + 1;
  }
  if ((contagem["campo:history"] ?? 0) > 0) {
    contagem["tipo:history"] = contagem["campo:history"] ?? 0;
  }
  return contagem;
}

/** Os onze campos, para quem queira iterar sem passar pela cobertura. */
export const CAMPOS_DAS_FIXTURES = CAMPOS;

/** As duas variantes interactivas, idem. */
export const VARIANTES_DAS_FIXTURES = VARIANTES_INTERACTIVAS;
