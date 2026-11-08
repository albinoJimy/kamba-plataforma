/**
 * A política de comunicação do ecrã de registo, aplicada em vez de prometida
 * (KAM-086, critério 3).
 *
 * «Sem NIF não se cria caso; o ecrã diz que o serviço implica NIF e registo de
 * vendas (segmento A) e **nunca** promete "sem rasto".»
 *
 * ## As três frases são do canon e não deste ficheiro
 *
 * O `docs/tecnica/10` §12 escreve-as por extenso, na linha «Não prometer o que
 * assusta o B nem o que a KAMBÁ não pode cumprir»: **nunca** dizer que a
 * plataforma «não deixa rasto», «escapa à AGT» ou «não regista vendas». A mesma
 * secção fixa o que se diz a quem chega do segmento B — «é informado de que o
 * produto implica NIF e registo» — e o `PA-GOV-7` do mesmo documento chama-lhe
 * «política de comunicação com frases proibidas».
 *
 * ## Porque é que isto é um guarda e não um comentário
 *
 * O §12 dá à frase proibida uma consequência — «frase proibida ⇒ sanção» — e
 * põe o controlo em «auditoria de amostras». Uma auditoria por amostragem
 * encontra a frase **depois** de ela ter sido mostrada a donos reais. O texto
 * desta página é código, e código verifica-se antes de correr: o
 * `exigirComunicacaoLimpa` corre **no arranque** e na construção de cada
 * resposta, e falha fechado.
 *
 * O custo de falhar fechado é o serviço não arrancar. É o custo certo: a
 * alternativa é a porta de entrada do produto a prometer, a um dono angolano, uma
 * coisa que o §12 diz que a plataforma não pode cumprir.
 *
 * ## O que ele não apanha, e fica dito
 *
 * Compara **texto normalizado** — sem acentos, sem maiúsculas, com espaços
 * colapsados —, o que apanha «Não Deixa Rasto» e «nao  deixa   rasto». Não
 * apanha uma paráfrase («ninguém vai saber»), e não tem como: isso é leitura e
 * é o que a auditoria de amostras do §12 continua a ter de fazer. O que ele
 * garante é que **estas** três não voltam, e a classe de defeito que ele fecha é
 * a regressão — alguém a reescrever o texto da página meses depois, sem ter
 * lido o §12.
 */

/**
 * As frases que o `docs/tecnica/10` §12 proíbe, já normalizadas.
 *
 * Lista fechada. Acrescentar uma é uma alteração visível num diff; retirar uma
 * exige mudar o §12 primeiro, que é canon e não é deste ticket.
 */
export const FRASES_PROIBIDAS: readonly string[] = [
  "nao deixa rasto",
  "sem rasto",
  "escapa a agt",
  "nao registamos vendas",
  "nao regista vendas",
  "ninguem fica a saber",
];

/**
 * A frase que o ecrã **tem** de dizer, normalizada.
 *
 * É a metade positiva do critério 3, e verifica-se com o mesmo rigor: um ecrã
 * que só não minta mas também não avise não cumpre o «o ecrã diz que o serviço
 * implica NIF e registo de vendas».
 */
export const FRASE_OBRIGATORIA = "implica nif e registo de vendas";

/** Levantado quando o texto da página não cumpre a política. */
export class ComunicacaoInvalidaError extends Error {
  override readonly name = "ComunicacaoInvalidaError";
  readonly motivo: "frase_proibida" | "sem_aviso";
  /** A frase proibida que apareceu, **da lista fechada** e nunca o texto da página. */
  readonly frase: string;

  constructor(motivo: "frase_proibida" | "sem_aviso", frase: string) {
    super(
      motivo === "sem_aviso"
        ? `o ecra nao diz "${FRASE_OBRIGATORIA}" (docs/tecnica/10 secao 12)`
        : `o ecra diz uma frase proibida: "${frase}" (docs/tecnica/10 secao 12)`,
    );
    this.motivo = motivo;
    this.frase = frase;
  }
}

/**
 * Normaliza texto para comparação: sem acentos, minúsculas, espaços colapsados.
 *
 * É o `normalizar` do `tools/secrets_inventory/canon.py` em TypeScript, e pela
 * razão que lá está escrita: sem isto, «não deixa rasto» no texto e
 * `nao deixa rasto` na lista eram duas coisas, e a verificação falhava por um
 * acento — que é o tipo de falha que ensina a desligar a verificação.
 */
export function normalizar(texto: string): string {
  return texto
    .normalize("NFKD")
    .replace(/[̀-ͯ]/g, "")
    .toLowerCase()
    // Tira **etiquetas bem formadas** e nao qualquer `<...>`: o guiao da pagina
    // leva um `1 << 26`, e um `/<[^>]*>/` apanhava dali um troco de codigo e
    // apagava-o — o que fazia a verificacao medir um texto que nao e o que sai.
    // Medido ao escrever: a primeira versao desta linha comia o corpo do ciclo
    // da prova de trabalho.
    .replace(/<\/?[a-zA-Z][^>]*>/g, " ")
    .replace(/\s+/g, " ")
    .trim();
}

/**
 * Verifica o texto da página, ou lança.
 *
 * Chamado no arranque (`./app.ts`) **e** na construção de cada página: no
 * arranque para o serviço não subir com texto errado, e por resposta porque o
 * texto leva valores interpolados e um deles podia trazer a frase de fora.
 */
export function exigirComunicacaoLimpa(html: string): void {
  const limpo = normalizar(html);
  for (const frase of FRASES_PROIBIDAS) {
    if (limpo.includes(frase)) throw new ComunicacaoInvalidaError("frase_proibida", frase);
  }
  if (!limpo.includes(FRASE_OBRIGATORIA)) {
    throw new ComunicacaoInvalidaError("sem_aviso", FRASE_OBRIGATORIA);
  }
}
