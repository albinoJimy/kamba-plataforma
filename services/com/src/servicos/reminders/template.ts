/**
 * O corpo do lembrete e os seus parâmetros (KAM-048, critérios 3 e 7).
 *
 * **Este módulo é o critério 7, e a propriedade que ele tem de ter é
 * estrutural e não uma convenção.** O critério pede «os parâmetros do
 * *template* vêm só de *facts* da marcação; teste prova que nenhum valor é
 * composto pelo LLM». A maneira errada de o cumprir é pedir a quem escrever
 * daqui para a frente que só use factos; a maneira certa é não haver por onde
 * outra coisa entre:
 *
 * ```text
 * parametrosDoLembrete(factos: FactosDaMarcacao) -> [p1, p2, p3]
 * ```
 *
 * Uma entrada, e ela tem **dois campos** (`CAMPOS_DE_FACTO`), os dois lidos da
 * base na transacção do *tenant*. Não há porta de modelo, não há argumento de
 * texto, não há omissão que se preencha com prosa. **E não há importação
 * nenhuma a não ser do `./contrato.ts`** — o que o ensaio estrutural prende,
 * para que um dia em que alguém alcance um gerador de texto se veja na lista de
 * importações e não na saída.
 *
 * ## Como é que o ensaio mede a proveniência em vez da forma
 *
 * Esta é a parte que custou a um ticket de ontem: um ensaio que verifica **nomes
 * de campo** fica verde com um valor inventado lá dentro, porque o nome do campo
 * não diz de onde veio o valor. Três medições, e cada uma apanha uma coisa que
 * as outras não apanham (ver `servicos.reminders.template.test.ts`):
 *
 * 1. **que campos foram lidos.** Os factos entram embrulhados num `Proxy` que
 *    registra cada acesso, e o ensaio exige que o conjunto lido seja
 *    **exactamente** o da `PROVENIENCIA`. Um parâmetro constante não lê campo
 *    nenhum e cai aqui;
 * 2. **o que muda quando o facto muda.** Para cada parâmetro, varia-se **só** o
 *    campo que a `PROVENIENCIA` lhe atribui: o parâmetro tem de mudar, e os que
 *    vêm de outro campo têm de ficar iguais. Um parâmetro declarado como vindo
 *    do `inicioAt` mas na verdade fixo cai aqui;
 * 3. **o que não entra.** Põe-se um campo a mais no objecto dos factos, com
 *    texto da forma que um modelo escreveria, e exige-se que nenhum parâmetro o
 *    contenha. É a forma literal de «nenhum valor é composto pelo LLM».
 *
 * As três juntas não se satisfazem com um valor inventado, e nenhuma delas olha
 * para o **nome** de coisa nenhuma.
 *
 * ## A data e a hora são dois parâmetros, e o fuso é o de Luanda
 *
 * O corpo *proposta* do bloco é «Lembrete: tem marcação de {{1}} no dia {{2}} às
 * {{3}}. Para remarcar ou cancelar, responda a esta mensagem.», pelo que a Meta
 * numera três posições. A data e a hora saem do **mesmo** facto (`inicioAt`) e
 * de duas formatações diferentes — o contrário não era possível, porque um
 * `timestamptz` não tem duas colunas.
 *
 * `dateStyle: "long"` e **não** `medium`, e a razão é medida e não estética: o
 * `avisos/avisos.ts` do KAM-115 mediu as três formas e `09/11/2026` são oito
 * dígitos separados por barras, que a régua de forma de telefone apanha. O mês
 * por extenso não tem corrida de dígitos nenhuma que chegue a sete.
 */

import {
  CAMPOS_DE_FACTO,
  FUSO_DE_APRESENTACAO,
  PARAMETROS_DO_LEMBRETE,
  PROVENIENCIA,
  type FactosDaMarcacao,
} from "./contrato.ts";

/**
 * A língua da formatação. `pt-PT`, que é a do conjunto e a do `horaDeLuanda`.
 *
 * **Não é o mesmo que o `IDIOMA_DO_LEMBRETE`**, e os dois não se confundem: o
 * `pt_PT` com sublinhado é o código de idioma do *template* junto da Meta, e o
 * `pt-PT` com hífen é a etiqueta BCP-47 que o `Intl` entende. Escrever um no
 * lugar do outro dá, num caso, um *template* que a Meta não encontra e, no
 * outro, uma formatação que o `Intl` ignora em silêncio caindo na omissão do
 * sistema — que é o pior dos dois, porque não levanta.
 */
export const LINGUA_DA_FORMATACAO = "pt-PT";

/**
 * A data como o cliente a lê, no fuso de Luanda.
 *
 * O ensaio de fuso do bloco — «marcação às 00:30 em `Africa/Luanda`» — é o que
 * esta função existe para passar: `Africa/Luanda` é UTC+1 sem horário de verão,
 * pelo que um `inicio_at` de `23:30Z` é `00:30` do **dia seguinte** em Luanda.
 * Uma formatação em UTC dava o dia anterior, e o cliente aparecia um dia antes.
 */
export function dataDeLuanda(instante: Date): string {
  return new Intl.DateTimeFormat(LINGUA_DA_FORMATACAO, {
    timeZone: FUSO_DE_APRESENTACAO,
    dateStyle: "long",
  }).format(instante);
}

/** A hora como o cliente a lê, no fuso de Luanda. Ver `dataDeLuanda`. */
export function horaDeLuanda(instante: Date): string {
  return new Intl.DateTimeFormat(LINGUA_DA_FORMATACAO, {
    timeZone: FUSO_DE_APRESENTACAO,
    timeStyle: "short",
  }).format(instante);
}

/** O `inicio_at` da base não é uma data que se possa formatar. */
export class InicioInvalidoError extends Error {
  override readonly name = "InicioInvalidoError";
  constructor() {
    super(
      "o inicio_at da marcacao nao e uma data: um lembrete com a data em " +
        "branco ou em NaN e pior do que nenhum lembrete, porque e um template " +
        "utility pago a dizer uma coisa errada (KAM-048, criterio 3)",
    );
  }
}

/**
 * **Os parâmetros do *template*, e só de factos.** Ver a nota do módulo.
 *
 * A ordem é a da `PROVENIENCIA`, que é a das posições `{{1}}`, `{{2}}` e
 * `{{3}}` do corpo aprovado. Devolve um `readonly string[]` de comprimento
 * `PARAMETROS_DO_LEMBRETE`, e a asserção desse comprimento está no fim — não
 * por desconfiança do código acima, mas porque é a única coisa que liga esta
 * função ao corpo que a Meta aprovou: um parâmetro a mais ou a menos é um
 * `132000` da Graph API, e descobri-lo aqui custa um ensaio em vez de uma
 * mensagem paga.
 *
 * **Lança para um `inicio_at` inválido**, ao contrário do `instanteDoLembrete`
 * do `schedule.ts`, que devolve `null`. A assimetria é deliberada e as duas
 * escolhas são a certa no sítio onde estão: lá a pergunta é «agendo?», e um
 * `null` responde-lhe; aqui já se decidiu enviar, e devolver um parâmetro vazio
 * era mandar um *template* pago com um espaço no lugar da data.
 */
export function parametrosDoLembrete(
  factos: FactosDaMarcacao,
): readonly string[] {
  const nome = factos.nomeDoServico;
  const instante = new Date(factos.inicioAt);
  if (Number.isNaN(instante.getTime())) throw new InicioInvalidoError();

  const parametros = [nome, dataDeLuanda(instante), horaDeLuanda(instante)];
  if (parametros.length !== PARAMETROS_DO_LEMBRETE) {
    throw new Error(
      `o corpo aprovado de lembrete_marcacao tem ${PARAMETROS_DO_LEMBRETE} ` +
        `parametros e esta funcao devolveu ${parametros.length}`,
    );
  }
  return parametros;
}

/**
 * O corpo *proposta* do *template*, com as posições da Meta.
 *
 * **É *proposta* e a aprovação não é garantida** — o bloco di-lo, e a submissão
 * do conjunto padrão por *tenant* é do EPIC-02 (KAM-091). O que vive aqui é o
 * **texto**, que é o que este ticket define; quem o submete e quem acompanha o
 * `message_template_status_update` é de lá, e este módulo só **consome** o
 * estado — pela porta do Outbound, que lê a `message_templates`.
 *
 * Fica em constante e não interpolado no sítio do envio porque é a mesma cadeia
 * que a mensagem livre usa: ver `textoDoLembrete`.
 */
export const CORPO_DO_TEMPLATE =
  "Lembrete: tem marcação de {{1}} no dia {{2}} às {{3}}. " +
  "Para remarcar ou cancelar, responda a esta mensagem.";

/**
 * O texto da **mensagem livre**, para a janela aberta (critério 3).
 *
 * É o `CORPO_DO_TEMPLATE` com as posições preenchidas pelos mesmos parâmetros,
 * e não um segundo texto escrito ao lado. Duas razões, e a segunda é a que
 * importa:
 *
 * * um segundo texto divergia do aprovado no primeiro dia em que alguém
 *   corrigisse uma vírgula num só dos dois, e o cliente passava a receber
 *   mensagens diferentes conforme a janela — que é a diferença que ele não tem
 *   como perceber nem razão para perceber;
 * * **a propriedade do critério 7 vale nos dois caminhos.** O DoD escreve
 *   «números só de tools: data e hora vêm de *facts* da marcação (ADR-007)», e
 *   isso não é uma regra do caminho do *template*: é uma regra do lembrete. Com
 *   um texto livre escrito à parte, a mensagem livre ficava fora da prova — e é
 *   ela que sai quando a janela está aberta, isto é, no caminho mais barato e
 *   mais frequente de um cliente activo.
 *
 * A substituição é posicional e literal, sem expressões regulares construídas
 * em tempo de execução: as posições são `{{1}}`..`{{n}}` e `n` é
 * `PARAMETROS_DO_LEMBRETE`.
 */
export function textoDoLembrete(factos: FactosDaMarcacao): string {
  const parametros = parametrosDoLembrete(factos);
  let texto = CORPO_DO_TEMPLATE;
  for (let i = 0; i < parametros.length; i += 1) {
    texto = texto.split(`{{${i + 1}}}`).join(parametros[i] as string);
  }
  return texto;
}

/**
 * Os campos de facto que o construtor **declara** ler, como lista.
 *
 * Exportado para o ensaio de proveniência, e derivado da `PROVENIENCIA` e não
 * escrito ao lado — pela razão do `AO_CLIENTE` do `handlers.py` do KAM-038: uma
 * lista escrita ao lado de outra que a devia gerar é duas fontes para o mesmo
 * facto, e divergem na primeira alteração.
 */
export const CAMPOS_LIDOS: readonly string[] = [...new Set(PROVENIENCIA)];

/**
 * `true` quando todos os campos declarados são campos de facto conhecidos.
 *
 * Uma asserção de sanidade sobre o próprio vocabulário, e não sobre os dados: se
 * a `PROVENIENCIA` nomear um campo que não está em `CAMPOS_DE_FACTO`, o ensaio
 * de proveniência comparava dois conjuntos ambos errados e ficava verde.
 */
export function provenienciaCoerente(): boolean {
  const conhecidos = new Set<string>(CAMPOS_DE_FACTO);
  return CAMPOS_LIDOS.every((campo) => conhecidos.has(campo));
}
