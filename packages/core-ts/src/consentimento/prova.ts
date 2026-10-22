/**
 * A prova reproduzível: o `evidence_hash` e o texto preenchido (KAM-022).
 *
 * «`evidence_hash = sha256(texto_versão ‖ contact_id ‖ wamid_do_botão ‖ hora)` é
 * **reprodutível**» — critério 7, e a palavra que o define é a última.
 *
 * ## O que entra no resumo, e porque é esta ordem
 *
 * Os quatro, pela ordem do critério, com um separador que **não pode aparecer
 * dentro de nenhum deles**. O separador é o `\u0000`: um UUID não o tem, um
 * `wamid` é base64 e não o tem, um instante em ISO não o tem, e o texto do
 * aviso é prosa que não o tem. Sem separador, `sha256("ab" ‖ "c")` e
 * `sha256("a" ‖ "bc")` são o mesmo resumo — e duas provas diferentes a dar o
 * mesmo *hash* é exactamente o que uma prova não pode fazer.
 *
 * ## O texto que entra é o **preenchido**, e isso é o centro
 *
 * A `consent_texts` guarda o aviso com um **marcador** no lugar do nome da loja:
 * ela é de plataforma e não tem `tenant_id` (ver a revisão `0015`). O que o
 * contacto vê é o texto com o nome da loja dele, e é **esse** que o resumo
 * cobre — senão a prova dizia «mostrámos-lhe um texto com um marcador», que não
 * é verdade.
 *
 * ## A hora é a da Meta, e é por isso que a prova é idempotente
 *
 * O `wamid_do_botão` e a `hora` vêm os dois da mensagem que a Meta entregou. Uma
 * reentrega do mesmo *webhook* traz o mesmo `wamid` e o mesmo `timestamp`, pelo
 * que produz o **mesmo** resumo — e a
 * `consent_event_prova_uq (tenant_id, contact_id, purpose, evidence_hash)`
 * recusa a segunda linha. É assim que «o mesmo botão repetido 2× produz 1
 * linha» (critério 2) é uma propriedade **da base** e não de uma leitura prévia.
 *
 * Com a **nossa** hora, duas entregas do mesmo botão davam dois resumos e duas
 * linhas, e o critério dizia o contrário. Está escrito aqui porque é a parte
 * fácil de trocar sem dar por isso.
 */

import { createHash } from "node:crypto";

/**
 * O separador dos quatro campos do resumo.
 *
 * `\u0000` e não `|` nem `:`: os dois últimos aparecem dentro de prosa e dentro
 * de um instante em ISO (`12:03`), e um separador que apareça num campo deixa de
 * separar. É o mesmo argumento — e o mesmo carácter — que o `ClienteEspiao` do
 * `tests_bd/apoio.ts` usa para juntar SQL e parâmetros sem os confundir.
 */
export const SEPARADOR = "\u0000";

/** O marcador que o texto da `consent_texts` leva no lugar do nome da loja. */
export const MARCADOR_DA_LOJA = "{loja}";

/**
 * O texto tal como o contacto o vê: o da versão, com o nome da loja no lugar do
 * marcador.
 *
 * Substitui **todas** as ocorrências, porque o aviso nomeia o responsável mais
 * de uma vez (quem é o responsável, e a quem pedir os direitos). Um texto sem
 * marcador passa por aqui sem mudar, e isso é aceitável: um aviso que não nomeie
 * a loja é um defeito de quem o escreveu, e quem o apanha é o parecer — não um
 * `throw` que impedia o aviso de sair e deixava o cliente sem resposta.
 */
export function preencher(texto: string, nomeDaLoja: string): string {
  return texto.split(MARCADOR_DA_LOJA).join(nomeDaLoja);
}

/** Os quatro campos da prova, pela ordem do critério 7. */
export interface CamposDaProva {
  /** O texto **preenchido**, como o contacto o viu. */
  readonly textoMostrado: string;
  readonly contactId: string;
  /** O `wamid` da mensagem do botão, como a Meta o deu. */
  readonly wamid: string;
  /** A hora **da Meta**, em ISO-8601 com fuso. */
  readonly hora: string;
}

/**
 * O resumo da prova: 32 octetos, que é o que o
 * `consent_event_evidence_ck` aceita.
 *
 * Determinístico por construção — não há relógio, não há aleatório e não há
 * ordem de mapa pelo meio —, e é isso que torna a palavra «reprodutível» do
 * critério uma propriedade e não uma intenção: dadas a linha e a versão do
 * texto, qualquer pessoa recalcula o mesmo valor.
 */
export function provaDeConsentimento(campos: CamposDaProva): Uint8Array {
  const resumo = createHash("sha256");
  resumo.update(
    [campos.textoMostrado, campos.contactId, campos.wamid, campos.hora].join(
      SEPARADOR,
    ),
    "utf8",
  );
  return new Uint8Array(resumo.digest());
}

/** O resumo de um texto de aviso, para a coluna `consent_texts.hash`. */
export function resumoDoTexto(texto: string): Uint8Array {
  return new Uint8Array(createHash("sha256").update(texto, "utf8").digest());
}
