/**
 * A matriz do aviso: seis entradas × três estados (KAM-022).
 *
 * Os Testes Requeridos pedem «máquina de estados do aviso (6 entradas × 3
 * estados)», e ela está aqui como **tabela** e não como uma cascata de `if`,
 * pela razão que o `tenantGate` do KAM-009 escreveu: uma tabela de dezoito
 * células lê-se de uma vez e um `if` encadeado não, e a célula que falta numa
 * tabela é visível.
 *
 * ## A tabela
 *
 * As colunas são o estado do consentimento **para a versão vigente do texto**;
 * as linhas são o que o contacto fez.
 *
 * | entrada | `ausente` | `desactualizado` | `valido` |
 * |---|---|---|---|
 * | botão `continuar` | `registar_e_seguir` | `registar_e_seguir` | `seguir` |
 * | botão `falar_com_a_loja` | `passar_a_humano` | `passar_a_humano` | `passar_a_humano` |
 * | botão `saber_mais` | `enviar_politica` | `enviar_politica` | `enviar_politica` |
 * | «PARAR» | `registar_revogacao` | `registar_revogacao` | `registar_revogacao` |
 * | texto livre | `enviar_aviso`¹ | `enviar_aviso`¹ | `seguir` |
 * | outro (áudio, imagem…) | `enviar_aviso`¹ | `enviar_aviso`¹ | `seguir` |
 *
 * ¹ depois de `AVISOS_ANTES_DO_HUMANO` avisos já enviados nesta conversa, passa
 * a `passar_a_humano` — é o «repete o aviso até 2 vezes e depois encaminha a
 * `humano`» do critério 3.
 *
 * ## As três linhas que não dependem do estado, e porquê
 *
 * O `falar_com_a_loja`, o `saber_mais` e o «PARAR» dão a mesma acção nas três
 * colunas, e isso é decisão e não preguiça:
 *
 * * **«Falar com a loja» vale sempre.** A Messaging Policy exige um caminho de
 *   escalonamento para uma pessoa (`E1` §4, CONFIRMADO) e o §9.2 põe «falar com
 *   humano» em todas as conversas. Condicioná-lo ao consentimento era pedir
 *   consentimento para falar com uma pessoa — que é o contrário do que ele é.
 * * **«Saber mais» vale sempre.** É o direito de informação, e quem já
 *   consentiu também o tem.
 * * **«PARAR» vale sempre**, e o critério di-lo por extenso: «em qualquer
 *   ponto».
 *
 * ## O que a matriz não decide
 *
 * Não decide **se há consentimento**: isso é uma leitura da base (a vista
 * `consent_actual` contra a versão vigente), e vem por parâmetro. Não decide
 * **o que se envia**: o texto é da `consent_texts`. E não decide o modo da
 * conversa, que é do KAM-018 — aqui diz-se que a conversa deve passar, e quem
 * tem o privilégio é que passa.
 */

import {
  AVISOS_ANTES_DO_HUMANO,
  type Accao,
  type BotaoDoAviso,
  type Entrada,
  type EstadoDoConsentimento,
} from "./contrato.ts";
import { eParar } from "./parar.ts";

/** A entrada, reduzida à linha da tabela. Seis valores. */
export const LINHAS = [
  "continuar",
  "falar_com_a_loja",
  "saber_mais",
  "parar",
  "texto",
  "outro",
] as const;
export type Linha = (typeof LINHAS)[number];

/**
 * Qual a linha da tabela que uma entrada ocupa.
 *
 * **O «PARAR» é lido antes do texto livre**, e a ordem é o critério 5: «em
 * qualquer ponto». Um texto que seja um opt-out não é texto livre, e tratá-lo
 * como tal fazia o gate repetir o aviso a quem pediu para parar.
 *
 * **Um botão com um `id` que não conhecemos cai em `outro`**, e não levanta: o
 * `reply.id` vem da Meta a devolver o que nós mandámos, mas nada garante que
 * uma mensagem antiga, de uma versão anterior do aviso, não traga um `id` que já
 * não existe. Levantar ali era transformar um aviso velho numa falha de
 * tratamento; cair em `outro` repete o aviso, que é o que se quer.
 */
export function linhaDaEntrada(entrada: Entrada): Linha {
  if (entrada.tipo === "botao") {
    return (LINHAS as readonly string[]).includes(entrada.id)
      ? (entrada.id as Linha)
      : "outro";
  }
  if (entrada.tipo === "texto") {
    return eParar(entrada.texto) ? "parar" : "texto";
  }
  return "outro";
}

/**
 * A tabela, inteira e explícita.
 *
 * Dezoito células escritas uma a uma. A alternativa — três linhas com a mesma
 * acção derivadas por uma regra — poupava seis linhas e tirava a propriedade
 * que importa: **uma célula em falta deixa de compilar**, porque o
 * `Record<Linha, Record<EstadoDoConsentimento, Accao>>` exige as dezoito.
 */
const TABELA: Readonly<Record<Linha, Readonly<Record<EstadoDoConsentimento, Accao>>>> = {
  continuar: {
    ausente: "registar_e_seguir",
    desactualizado: "registar_e_seguir",
    valido: "seguir",
  },
  falar_com_a_loja: {
    ausente: "passar_a_humano",
    desactualizado: "passar_a_humano",
    valido: "passar_a_humano",
  },
  saber_mais: {
    ausente: "enviar_politica",
    desactualizado: "enviar_politica",
    valido: "enviar_politica",
  },
  parar: {
    ausente: "registar_revogacao",
    desactualizado: "registar_revogacao",
    valido: "registar_revogacao",
  },
  texto: {
    ausente: "enviar_aviso",
    desactualizado: "enviar_aviso",
    valido: "seguir",
  },
  outro: {
    ausente: "enviar_aviso",
    desactualizado: "enviar_aviso",
    valido: "seguir",
  },
};

/**
 * A acção, dada a entrada, o estado e quantos avisos já saíram nesta conversa.
 *
 * O `avisosEnviados` só muda uma coisa: um `enviar_aviso` que seria o terceiro
 * passa a `passar_a_humano`. É o critério 3, e a contagem vem da base — ver o
 * `SQL_AVISOS_ENVIADOS` em `consultas.ts`.
 *
 * **A insistência não cria consentimento.** Nenhum caminho daqui devolve
 * `seguir` ou `registar_e_seguir` a partir de um estado que não seja `valido` ou
 * de um botão que não seja o `continuar`, e é isso que torna a propriedade do
 * critério 4 — «0 *jobs* do AGR sem `consent_event` válido anterior» —
 * demonstrável por esta função sozinha.
 */
export function accaoDoAviso(
  entrada: Entrada,
  estado: EstadoDoConsentimento,
  avisosEnviados: number,
): Accao {
  const linha = linhaDaEntrada(entrada);
  const accao = TABELA[linha][estado];
  if (accao === "enviar_aviso" && avisosEnviados >= AVISOS_ANTES_DO_HUMANO) {
    // «Repete o aviso até 2 vezes e depois encaminha a `humano`.» Com o tecto
    // ja atingido, a terceira entrada que nao e botao passa a pessoa.
    return "passar_a_humano";
  }
  return accao;
}

/**
 * `true` quando esta acção autoriza o AGR.
 *
 * **Duas, e só duas:** o `seguir` (já havia consentimento válido) e o
 * `registar_e_seguir` (passa a haver **nesta** mensagem, e a linha escreve-se
 * antes). Qualquer outra é `false`, incluindo o `enviar_politica` — quem pede
 * para saber mais não autorizou nada.
 *
 * Está como função e não como campo de um mapa de propósito: é a afirmação que
 * o critério 4 mede, e um teste exaustivo sobre as seis acções prende-a.
 */
export function autorizaAgr(accao: Accao): boolean {
  return accao === "seguir" || accao === "registar_e_seguir";
}

/**
 * `true` quando a acção escreve uma linha de prova.
 *
 * **Três**, e a lista existe porque o `evidence_hash` cobre o **texto
 * mostrado**: quem registra prova precisa do texto preenchido, mesmo quando não
 * envia mensagem nenhuma. Foi por não haver esta função que a primeira versão
 * do «ler o texto tarde» calculou a prova do «Continuar» sobre uma cadeia
 * **vazia** — o `registar_e_seguir` não envia mensagem e caiu fora da condição.
 * Com as duas listas nomeadas, uma acção nova não cai em silêncio por nenhuma
 * das duas.
 */
export function registaProva(accao: Accao): boolean {
  return (
    accao === "registar_e_seguir" ||
    accao === "registar_revogacao" ||
    accao === "passar_a_humano"
  );
}

/** `true` quando a acção produz uma mensagem de saída. Zero ou uma, nunca duas. */
export function enviaMensagem(accao: Accao): boolean {
  return (
    accao === "enviar_aviso" ||
    accao === "enviar_politica" ||
    accao === "registar_revogacao"
  );
}

/**
 * O estado do consentimento, dada a linha da vista e a versão vigente.
 *
 * `null` na linha significa «não há registo» → `ausente`. Um `accepted = false`
 * também dá `ausente`, e a razão está no `contrato.ts`: quem recusou não deu
 * consentimento, e o que o gate faz a seguir é o mesmo. O registo da recusa fica
 * na tabela, que é onde ele tem de ficar.
 */
export function estadoDoConsentimento(
  linha: { readonly accepted: boolean; readonly text_version: string } | null,
  versaoVigente: string,
): EstadoDoConsentimento {
  if (linha === null || !linha.accepted) return "ausente";
  return linha.text_version === versaoVigente ? "valido" : "desactualizado";
}

/** O botão que uma linha da tabela representa, quando é um botão. */
export function botaoDaLinha(linha: Linha): BotaoDoAviso | null {
  return linha === "continuar" || linha === "falar_com_a_loja" || linha === "saber_mais"
    ? linha
    : null;
}
