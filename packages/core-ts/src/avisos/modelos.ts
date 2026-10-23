/**
 * Os cinco modelos do aviso, e a lista branca dos parâmetros (KAM-115, critério 5).
 *
 * «Conteúdo por *allowlist* de modelos (1 por gatilho): nome da loja, estado,
 * hora, passos e ligação ao painel sem *token* nem identificador pessoal no URL;
 * 0 telefones, `contact_id`, BSUID ou texto de clientes.»
 *
 * O critério tem duas metades, e elas resolvem-se de formas diferentes:
 *
 * * **a lista de modelos** é um mapa de cinco entradas, uma por gatilho. Um
 *   gatilho fora da lista não tem modelo, e sem modelo não há aviso — é a mesma
 *   frase do critério 1 («um gatilho fora da lista não envia nada») vista deste
 *   lado;
 * * **a lista de parâmetros** é fechada e aplica-se na **construção** e não
 *   depois. Um varrimento a posteriori diz que um aviso leva um telefone; uma
 *   lista fechada na construção faz o telefone não ter por onde entrar. Fazem-se
 *   as duas: a lista aqui, e o varrimento do critério 5 sobre 200 avisos no
 *   ensaio.
 *
 * ## O nome da loja é texto livre, e é por aí que a PII entra
 *
 * Os quatro parâmetros são `loja`, `estado`, `hora` e `painel`. Três são nossos:
 * o `estado` vem de um domínio fechado, a `hora` de um `Date` e o `painel` de
 * uma constante com o `tenant_id` **fora** do URL. O `loja` é o que o dono
 * escreveu em `tenants.nome`, e um dono pode ter escrito lá um número de
 * telefone — «Loja do Zé 923 456 789» é um nome de loja plausível em Luanda.
 *
 * **Mascara-se, não se recusa**, e a escolha é deliberada: recusar o aviso fazia
 * o dono não saber que o canal caiu por causa de como ele escreveu o nome da
 * loja, o que é castigá-lo por um defeito nosso. O que sai é o nome com as
 * corridas de sete ou mais dígitos substituídas — sete, porque o
 * `DIGITOS_MAXIMOS` do `../logger/politica.ts` é **seis** e é essa a fronteira
 * que a casa já escolheu para distinguir um número de uma referência.
 *
 * A mesma régua apanha o NIF e o IBAN pela mesma razão que a política os apanha:
 * não se procura o formato de cada um, procura-se a corrida de dígitos em
 * qualquer arrumação — com espaços, com pontos ou sem nada.
 *
 * ## A ligação ao painel não leva *token* nem identificador
 *
 * O critério é explícito, e a razão é o canal: um URL vai para o e-mail, o
 * e-mail fica na caixa do dono e o histórico do navegador guarda-o. Um *token* no
 * URL é um *token* publicado. O que sai é a **raiz do painel** — o dono entra e
 * autentica-se, e o painel sabe quem ele é sem que nós lho digamos no caminho.
 *
 * Isto é diferente da ligação de **confirmação** do critério 6, que leva o
 * *token* por natureza — é o que ela é. Essa não sai deste módulo: quem a entrega
 * é o KAM-086, que é quem capta o e-mail.
 *
 * ## Os textos estão em português de Angola e não se traduzem aqui
 *
 * Não há i18n neste repositório, e inventá-la neste ticket era alargar o escopo.
 * O que há é um sítio só onde os cinco textos vivem, que é o que permite mudá-los
 * sem procurar por aspas no código.
 */

import { DIGITOS_MAXIMOS } from "../logger/politica.ts";
import { GATILHOS, type Gatilho } from "./contrato.ts";

/**
 * Os quatro parâmetros que um modelo pode receber. **Lista fechada.**
 *
 * Não há `telefone`, não há `contacto`, não há `cliente` e não há `mensagem`: o
 * critério 5 pede «0 telefones, `contact_id`, BSUID ou texto de clientes», e a
 * forma de o garantir é não haver parâmetro por onde isso entre. Um parâmetro
 * fora desta lista faz a construção **levantar**.
 */
export const PARAMETROS = ["loja", "estado", "hora", "painel"] as const;
export type Parametro = (typeof PARAMETROS)[number];

/** Os valores que um modelo recebe. */
export type Parametros = Readonly<Record<Parametro, string>>;

/** O marcador de um parâmetro dentro de um texto: `{loja}`. */
const MARCADOR = /\{([a-z]+)\}/g;

/**
 * Quantos dígitos seguidos se deixam passar no texto livre.
 *
 * **Reexportado do `../logger/politica.ts` e não redeclarado**: é lá que a casa
 * escolheu a fronteira entre um número e uma referência, e um segundo seis em
 * outro ficheiro divergia no dia em que um deles mudasse. É a mesma escolha que
 * o `MPS_POR_MODO` do KAM-017 fez ao reexportar do `outbound/limites.ts`.
 */
export { DIGITOS_MAXIMOS };

/** O que substitui uma corrida de dígitos longa demais. */
export const MASCARA = "[...]";

/** Tecto do nome da loja no aviso, em caracteres. */
export const MAXIMO_DA_LOJA = 120;

/** Um parâmetro que não está na lista fechada. */
export class ParametroInvalidoError extends Error {
  override readonly name = "ParametroInvalidoError";

  constructor(nome: string) {
    super(
      `parametro ${JSON.stringify(nome)} nao esta na lista fechada do critério 5 ` +
        `(${PARAMETROS.join(", ")}). Telefones, contact_id, BSUID e texto de ` +
        "clientes nao entram num aviso ao dono",
    );
  }
}

/** Um gatilho sem modelo. */
export class ModeloEmFaltaError extends Error {
  override readonly name = "ModeloEmFaltaError";

  constructor(gatilho: string) {
    super(`nao ha modelo para o gatilho ${JSON.stringify(gatilho)}`);
  }
}

interface Modelo {
  readonly assunto: string;
  readonly corpo: string;
  readonly passo: string;
}

/**
 * Os cinco modelos, um por gatilho.
 *
 * Cada um diz **o que aconteceu** e **o passo seguinte**, que é o que o critério
 * 1 pede: «cada um com texto próprio e o passo seguinte (reconectar, abrir a
 * app, adicionar cartão)». Os três passos que o critério nomeia estão aqui, e os
 * outros dois têm o seu — um aviso que diz que algo está mal e não diz o que
 * fazer é um aviso que o dono não pode usar.
 *
 * **O `canal_desligado` cobre os seis motivos de `PARTNER_REMOVED`** e não os
 * nomeia: o passo é o mesmo nos seis, e seis textos iguais eram seis sítios para
 * a mesma frase divergir. O motivo vive no `episodio`, que é o que faz o segundo
 * desligamento por outro motivo ser um episódio novo. Ver a nota do
 * `contrato.ts`.
 */
const MODELOS: Readonly<Record<Gatilho, Modelo>> = {
  canal_desligado: {
    assunto: "O WhatsApp da {loja} deixou de estar ligado",
    corpo:
      "A ligação do WhatsApp da {loja} à KAMBÁ caiu em {hora} e as mensagens " +
      "dos seus clientes não estão a ser atendidas.",
    passo: "Entre no painel em {painel} e volte a ligar o número.",
  },
  inactividade: {
    assunto: "Abra a app do WhatsApp da {loja} nos próximos dias",
    corpo:
      "Há dez dias que não vemos actividade sua no WhatsApp da {loja}. Se " +
      "passarem mais alguns dias sem abrir a app, a Meta desliga a ligação e as " +
      "mensagens dos seus clientes deixam de ser atendidas.",
    passo: "Abra a app do WhatsApp Business no telefone da loja.",
  },
  qualidade_restrita: {
    assunto: "O WhatsApp da {loja} ficou com envios limitados",
    corpo:
      "A Meta baixou a qualidade do número da {loja} em {hora} e o canal ficou " +
      "em {estado}: só respondemos a quem lhe escrever primeiro, e os envios que " +
      "partem de nós estão parados.",
    passo:
      "Veja no painel em {painel} quais as mensagens que os clientes marcaram " +
      "como indesejadas.",
  },
  sem_pagamento: {
    assunto: "Falta um cartão na conta WhatsApp da {loja}",
    corpo:
      "A Meta deixou de entregar as mensagens que a {loja} envia por falta de " +
      "método de pagamento na conta. Isto aconteceu em {hora} e afecta as " +
      "mensagens que partem de nós, não as respostas a quem lhe escreve.",
    passo: "Adicione um cartão à conta de WhatsApp Business, pelo painel em {painel}.",
  },
  painel_indisponivel: {
    assunto: "O painel da {loja} esteve em baixo",
    corpo:
      "O painel da KAMBÁ esteve inacessível a partir de {hora}. As mensagens " +
      "dos seus clientes continuaram a ser recebidas; o que esteve em baixo foi " +
      "o seu acesso para as ler.",
    passo: "Tente entrar outra vez em {painel}. Se continuar em baixo, estamos a tratar.",
  },
};

/**
 * Mascara as corridas de dígitos longas demais num texto livre.
 *
 * Sete ou mais dígitos **seguidos ou separados por espaços, pontos, hífenes e
 * barras**: é a arrumação em que um telefone angolano aparece escrito à mão
 * («923 456 789», «923-456-789»), e procurar só a corrida contígua deixava
 * passar exactamente o caso comum. Os separadores contam-se mas não se guardam —
 * o que sai é a máscara.
 */
export function mascarar(texto: string): string {
  // `(?:\d[ .\-/]*){7,}` e nao `\d{7,}`: ver a nota. O `[ .\-/]*` do fim tambem
  // entra na mascara, e e de proposito — deixa-lo fora dava «[...] » com um
  // espaco pendurado a mais.
  return texto.replace(/(?:\d[ .\-/]*){7,}/g, MASCARA);
}

/**
 * Prepara o nome da loja para entrar num aviso.
 *
 * Mascara e **trunca**. O truncamento não é estética: um `tenants.nome` é `text`
 * e não tem tecto na base, e um assunto de e-mail com 4 000 caracteres é
 * recusado por qualquer fornecedor — o aviso falhava por uma razão que nada
 * tinha a ver com o canal que caiu.
 */
export function prepararLoja(nome: string): string {
  const limpo = mascarar(nome.trim().replace(/\s+/g, " "));
  return limpo.length > MAXIMO_DA_LOJA ? `${limpo.slice(0, MAXIMO_DA_LOJA - 1)}…` : limpo;
}

/**
 * Preenche um texto com os parâmetros, e **levanta** num parâmetro desconhecido.
 *
 * Levanta nos dois sentidos, e isso é mais do que validar a entrada:
 *
 * * um valor cuja chave não está na lista fechada não entra — é o critério 5;
 * * e um marcador no texto do modelo que **não** tenha valor também levanta, em
 *   vez de ficar `{loja}` literal no e-mail do dono. Um modelo com um marcador
 *   mal escrito é um defeito nosso, e um defeito que sai em texto para o
 *   cliente é o pior sítio para o descobrir.
 */
function preencher(texto: string, valores: Parametros): string {
  return texto.replace(MARCADOR, (_todo, nome: string) => {
    if (!(PARAMETROS as readonly string[]).includes(nome)) {
      throw new ParametroInvalidoError(nome);
    }
    const valor = valores[nome as Parametro];
    if (valor === undefined) throw new ParametroInvalidoError(nome);
    return valor;
  });
}

/**
 * Constrói o aviso de um gatilho.
 *
 * Recusa um parâmetro fora da lista **antes** de preencher: com a recusa só
 * dentro do `preencher`, um parâmetro a mais que nenhum modelo usasse passava
 * sem ser visto, e o que entrava sem ser visto era o que o critério 5 proíbe.
 */
export function construir(
  gatilho: Gatilho,
  valores: Parametros,
): { readonly assunto: string; readonly corpo: string; readonly passo: string } {
  const modelo = MODELOS[gatilho];
  if (modelo === undefined || !GATILHOS.includes(gatilho)) {
    throw new ModeloEmFaltaError(gatilho);
  }
  for (const nome of Object.keys(valores)) {
    if (!(PARAMETROS as readonly string[]).includes(nome)) {
      throw new ParametroInvalidoError(nome);
    }
  }
  const loja = prepararLoja(valores.loja);
  const seguros: Parametros = { ...valores, loja };
  return {
    assunto: preencher(modelo.assunto, seguros),
    corpo: `${preencher(modelo.corpo, seguros)} ${preencher(modelo.passo, seguros)}`,
    passo: preencher(modelo.passo, seguros),
  };
}

/** Os gatilhos que têm modelo. É a lista do critério 1, vista deste lado. */
export function gatilhosComModelo(): readonly Gatilho[] {
  return Object.keys(MODELOS) as readonly Gatilho[];
}
