/**
 * A assinatura dos corpos gerados — **uma segunda implementação** (KAM-024).
 *
 * O critério 4 pede que «a assinatura gerada é aceite pelo GWY de KAM-013 (ida
 * e volta) e rejeitada quando o corpo muda 1 byte». Isso só é uma prova se as
 * duas pontas forem implementações **independentes**.
 *
 * ## Por isso este ficheiro não importa nada de `@kamba/core-ts/entrada`
 *
 * O `assinaturaValida` do `core-ts` é quem **valida**, no GWY. Se o simulador
 * assinasse com o `sha256Hex` do mesmo módulo, a ida e volta provava que uma
 * função é consistente consigo própria — e passava a verde no dia em que o
 * algoritmo estivesse errado dos dois lados. É a mesma razão por que a *suite*
 * `db/tests_entrada/` calcula a assinatura em **Python**: mede-se
 * interoperabilidade, não auto-consistência.
 *
 * O que se reutiliza são as **constantes do protocolo** (o nome do cabeçalho, o
 * prefixo), porque essas não são um algoritmo: são o nome de uma coisa, e dois
 * nomes diferentes para o mesmo cabeçalho seria o defeito que o dicionário
 * existe para evitar. O cálculo é próprio.
 *
 * ## O facto, e o seu estado
 *
 * «`X-Hub-Signature-256: sha256=<HMAC-SHA256 do corpo bruto com o App Secret>`»
 * é **CONFIRMADO** em fonte primária (`docs/tecnica/evidencia/E1` §5,
 * `DOC/webhooks/create-webhook-endpoint`, 17 Jun 2026). O que **não** está
 * confirmado é o *timeout* exacto de resposta do webhook (NÃO VERIFICADO, L2):
 * este módulo não o inventa.
 */

import { createHmac, timingSafeEqual } from "node:crypto";

/** O cabeçalho que a Meta envia. Em minúsculas, como o Hono o entrega. */
export const CABECALHO = "x-hub-signature-256";

/** O prefixo do valor. A Meta escreve-o sempre. */
export const PREFIXO = "sha256=";

/** O valor do cabeçalho para um corpo e um segredo. */
export function assinar(corpo: Uint8Array, segredo: string): string {
  return (
    PREFIXO +
    createHmac("sha256", segredo).update(corpo).digest("hex")
  );
}

/**
 * O mesmo, com o resumo **alterado num bit**.
 *
 * Serve o caso negativo do critério 4 sem depender de o chamador saber mexer em
 * hexadecimal: o que se quer provar é que o GWY recusa, e um resumo válido com
 * um nibble trocado é o caso mais próximo de um ataque.
 */
export function assinarMal(corpo: Uint8Array, segredo: string): string {
  const certa = assinar(corpo, segredo);
  const resumo = certa.slice(PREFIXO.length);
  const primeiro = resumo[0] ?? "0";
  const trocado = primeiro === "0" ? "1" : "0";
  return PREFIXO + trocado + resumo.slice(1);
}

/**
 * Verifica uma assinatura. **Só para os testes do próprio simulador.**
 *
 * Quem valida em produção é o `assinaturaValida` do `core-ts`, no GWY. Isto
 * existe para o simulador poder afirmar coisas sobre o que ele mesmo gerou —
 * por exemplo, que `assinarMal` produz algo que não bate — sem importar o
 * módulo que está a ser testado do outro lado.
 */
export function confere(corpo: Uint8Array, cabecalho: string, segredo: string): boolean {
  if (!cabecalho.startsWith(PREFIXO)) return false;
  const esperado = Buffer.from(assinar(corpo, segredo).slice(PREFIXO.length), "hex");
  const recebido = Buffer.from(cabecalho.slice(PREFIXO.length), "hex");
  if (recebido.length !== esperado.length || esperado.length === 0) return false;
  return timingSafeEqual(recebido, esperado);
}

/**
 * Um segredo de ensaio, derivado de uma semente.
 *
 * **Determinístico de propósito**, e isso é seguro porque um segredo de ensaio
 * não protege nada: o critério 4 exige que «o segredo de teste nunca coincida
 * com um segredo de `staging`/`prod`», e é isso que `exigirSegredoDeEnsaio`
 * verifica. Um segredo aleatório por execução tornava as *fixtures* assinadas
 * não reproduzíveis, que é o contrário do critério 1.
 */
export function segredoDeEnsaio(semente: string): string {
  return `ensaio-${createHmac("sha256", "meta-sim").update(semente).digest("hex").slice(0, 32)}`;
}

/** O prefixo que marca um segredo como de ensaio. */
export const PREFIXO_DO_SEGREDO = "ensaio-";

/** Um segredo de ensaio foi confundido com um de verdade, ou o contrário. */
export class SegredoDeVerdadeError extends Error {
  constructor(motivo: string) {
    super(
      `o simulador recusa este segredo: ${motivo}. O criterio 4 do KAM-024 ` +
        "exige que o segredo de teste nunca coincida com um de staging ou de " +
        "prod — se coincidisse, uma fixture assinada no repositorio era uma " +
        "assinatura valida contra o ambiente real.",
    );
    this.name = "SegredoDeVerdadeError";
  }
}

/**
 * Lança se o segredo não tiver a forma de um segredo de ensaio.
 *
 * Duas verificações, e a segunda é a que importa: o segredo tem de **começar**
 * pelo prefixo de ensaio, e não pode ser igual a nenhum dos que o ambiente
 * oferece (`KAMBA_SECRET_META_APP_SECRET` e o seu anel). A primeira é forma; a
 * segunda é a que apanha alguém a passar o segredo de `staging` ao simulador
 * «só para experimentar».
 */
export function exigirSegredoDeEnsaio(
  segredo: string,
  ambiente: Readonly<Record<string, string | undefined>> = process.env,
): void {
  if (!segredo.startsWith(PREFIXO_DO_SEGREDO)) {
    throw new SegredoDeVerdadeError(
      `nao comeca por ${JSON.stringify(PREFIXO_DO_SEGREDO)}`,
    );
  }
  for (const [nome, valor] of Object.entries(ambiente)) {
    if (!nome.startsWith("KAMBA_SECRET_")) continue;
    if (valor !== undefined && valor !== "" && valor === segredo) {
      throw new SegredoDeVerdadeError(`e igual ao valor de ${nome}`);
    }
  }
}
