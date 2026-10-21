/**
 * O vocabulário da monitorização do *free tier* e do método de pagamento
 * (KAM-023).
 *
 * Os nomes são os do §3.16 do dicionário (emenda 1.24). As duas colunas que
 * este módulo mantém — `tenant_channels.free_tier_used` e `free_tier_month` —
 * **existem desde a revisão `0001`** e já estão no `GRANT UPDATE` de
 * `kamba_app` (`0001`, a lista de treze colunas), pelo que este ticket não
 * cria DDL para elas. O `docstring` da revisão `0010` di-lo por extenso: «não
 * mantém o contador do *free tier* […] quem as mantém é o KAM-023».
 *
 * ## As quatro decisões de desenho, e porque é que são estas
 *
 * **1. Quem conta é a transição, não o `statuses`.** O critério 2 pede
 * idempotência por `wamid`: três repetições do mesmo estado somam **um**. Isso
 * não se consegue olhando para o estado que chegou — a Meta reenvia os
 * `statuses` sem ordem garantida e com entrega concorrente (CONFIRMADO, `E1`
 * §5). Quem sabe se **esta** chegada foi a que entregou a mensagem é o
 * `SQL_AVANCAR_ESTADO` do KAM-015, que decide sob `FOR UPDATE` e devolve o
 * `estado_antes`. Este módulo é accionado por esse facto (`entregou`) e nunca
 * relê o estado para o re-decidir: reler era abrir outra vez a corrida que o
 * KAM-015 fechou, e desta vez no contador em vez de no custo.
 *
 * **2. O mês vem da base, e o fuso vive num sítio.** O critério 3 pede
 * reinício «à meia-noite do fuso configurado do canal». A função
 * `platform.ten_periodo(timestamptz) RETURNS date` da revisão `0007` é
 * exactamente `date_trunc('month', p_agora AT TIME ZONE 'Africa/Luanda')`, é
 * `IMMUTABLE`, e está concedida a `kamba_app`. O comentário que a criou diz
 * porquê: «para que o fuso exista **num** sítio […] três cópias de
 * `'Africa/Luanda'` divergem no dia em que uma delas mudar». E há um teste em
 * `libs/py-core/tests/test_ten.py` que recusa o nome do fuso escrito no
 * código. Logo: não há aritmética de mês em TypeScript aqui, e o
 * `free_tier_month` é `date` precisamente porque é o que aquela função
 * devolve.
 *
 * **Divergência assumida, e está escrita na secção de verificação:** o
 * critério fala do fuso «do canal» e `tenant_channels` **não tem** coluna de
 * fuso — a única é `tenants.fuso_horario` (`0001`, omissão `'Africa/Luanda'`),
 * que é por *tenant*. Um *tenant* com dois números não pode hoje ter dois
 * fusos. Configurá-lo por canal é DDL, e DDL é a metade deste ticket que
 * espera pela revisão `0013`.
 *
 * **3. O aviso é um flanco, e o flanco sai do próprio `UPDATE`.** O critério 3
 * pede «1 aviso aos 800 e 1 aos 1.000, **sem repetição no mesmo mês**». A
 * tentação é guardar «já avisei» numa coluna — e isso era DDL. Não é
 * necessário: o `UPDATE` que incrementa devolve o valor **antes** e **depois**,
 * e o número 800 é atravessado por exactamente um incremento. Quem avisa é a
 * travessia, não o valor, e por isso não há estado a guardar nem repetição a
 * desduplicar. É correcto sob concorrência pela mesma razão que o custo do
 * KAM-015 o é: o `FOR UPDATE` serializa, e o segundo processo lê o que o
 * primeiro escreveu.
 *
 * **4. As métricas não levam etiqueta de *tenant*.** O critério 4 escreve
 * `meta_free_tier_used_ratio{tenant}` e `meta_cost_usd_estimate{tenant}`. Não
 * é implementável, e a caixa fica vazia com a razão escrita — é o **mesmo**
 * precedente que o KAM-015 já registou no §3.14 para a
 * `meta_cost_usd_total{tenant}`, e seria incoerente decidir de outra forma a
 * dois módulos de distância: as bibliotecas de métricas deste repositório
 * recusam por gramática uma etiqueta que não case `^[a-z][a-z0-9_]{1,62}$`, e
 * um `tenant_id` é um UUID com hífenes que muitas vezes começa por dígito — a
 * chamada **levanta**. A razão de fundo é o `OBS-I` de
 * `docs/seguranca/ameacas_stride.md` («identificadores em etiquetas explodem a
 * cardinalidade e re-identificam») e o X-11 do *gate* 6. O por-*tenant* sai de
 * consulta (`SQL_RECONCILIAR`), que é o caminho que o §16 do `docs/tecnica/01`
 * já aponta.
 */

/**
 * O cliente de SQL que este módulo precisa.
 *
 * `readonly rows` como o `ClienteSql` do KAM-015 e o `ClienteDoChr` do
 * KAM-014, e pela mesma razão: este módulo nunca altera o que lê, e um tipo
 * com `rows` mutável obrigava quem o liga a provar que não o altera.
 */
export interface ClienteSql {
  query<T = Record<string, unknown>>(
    texto: string,
    valores?: readonly unknown[],
  ): Promise<{ readonly rows: readonly T[] }>;
}

/**
 * O limiar de aviso: 80% do *free tier*.
 *
 * O número é 800 e o alvo é do `docs/tecnica/08` §3.7 e do `docs/tecnica/09`
 * (RB-K05). **Está escrito como fracção do tecto e não como `800` literal**
 * para que não possa divergir do `FREE_TIER_DE_SERVICE` do KAM-015: se o tecto
 * mudar — e muda por decisão da Meta, não nossa —, o aviso acompanha-o. Um
 * `800` constante era o número certo hoje e um defeito silencioso no dia da
 * mudança.
 *
 * **Nota de atribuição, e é uma divergência documental:** o bloco do ticket
 * escreve «Alvo do doc 00: alertas aos 80% (800)». O `docs/tecnica/00` §9 não
 * dá limiar nenhum — diz só «*service messages* > 1.000/mês a 0,004 USD». O
 * 80% vem do `docs/tecnica/08` §3.7 e do `docs/tecnica/09` §9. O valor não
 * está em causa (é unânime em dez afirmações); a atribuição está, e vai para
 * `docs/dividas-documentais.md`.
 */
export const FRACCAO_DE_AVISO = 0.8;

/**
 * Os dois níveis de alerta do *free tier*, em lista fechada.
 *
 * `aviso` é a travessia dos 80%; `esgotado` é a travessia do tecto. São
 * **minúsculas e sem acentos** porque entram como sufixo de métrica e o §2 do
 * dicionário manda-o — e porque um sufixo que não case
 * `^[a-z][a-z0-9_]{1,62}$` é recusado por gramática.
 */
export const NIVEIS = ["aviso", "esgotado"] as const;
export type Nivel = (typeof NIVEIS)[number];

/**
 * A janela de mensagens em que se mede a taxa de falhas, e quantas falhas
 * bastam (critério 5).
 *
 * **Proposta, e não CONFIRMADO.** O critério escreve «(proposta: 20% em 20
 * mensagens)» e a palavra é dele. O que é CONFIRMADO (`E1` §1) é o
 * comportamento: sem método de pagamento a Meta entrega as do *free tier* e
 * **deixa de entregar** depois. O que não existe em evidência nenhuma é o
 * **código de erro** com que ela o diz — o `E1` nomeia três códigos
 * (`2593109`, `130429`, `131049`) e nenhum é de pagamento. Por isso a
 * detecção é uma heurística sobre a **taxa** e não uma comparação com um
 * código, e por isso o critério manda guardar os códigos vistos: é a
 * calibração que permitirá, um dia, substituir a heurística pelo código certo.
 * A pergunta está em `specs/EPIC-02` (R9) para o pacote do KAM-101.
 */
export const JANELA_DE_FALHAS = 20;
export const FALHAS_PARA_SUSPEITA = 4;

/** O que o incremento do contador produziu. */
export interface Contagem {
  /** O contador **depois** deste incremento. */
  readonly usadas: number;
  /**
   * O contador **antes**, já normalizado pelo reinício.
   *
   * Quando o mês virou, é `0` e não o valor do mês anterior: é o flanco que
   * interessa, e 1.500 do mês passado não é o ponto de partida de um mês que
   * começa em 1.
   */
  readonly antes: number;
  /** O mês a que o contador passou a pertencer, em `YYYY-MM-DD`. */
  readonly mes: string;
  /** `true` quando este incremento foi o primeiro de um mês novo. */
  readonly reiniciou: boolean;
  /** O nível atravessado por **este** incremento, se algum. */
  readonly nivel: Nivel | null;
}

/**
 * O que a reconciliação do critério 7 mediu.
 *
 * O critério é de **saída** e não de PR: pede «ao fim de 1 mês real» e uma
 * divergência ≤ 2%. O que o código pode entregar hoje é o instrumento que o
 * torna medível — a consulta e a conta —, e a caixa fica vazia até haver um
 * mês de Piloto que a alimente. Entregar a caixa marcada com um ensaio
 * sintético era marcar um critério de saída com dados que não são do mundo.
 */
export interface Reconciliacao {
  /**
   * O nosso contador: `free_tier_used` do canal, **no mês corrente**.
   *
   * O mês é o corrente e não um à escolha, porque não há outro que se possa
   * reconciliar: o contador é uma coluna e não uma série, e quando o mês vira o
   * valor anterior desaparece. Ver a nota de `Metering.reconciliar`.
   */
  readonly contador: number;
  /** *Service* entregues que o `pricing` das linhas conta, no mesmo mês. */
  readonly entregues: number;
  /** Dessas, as que a Meta marcou `billable`. */
  readonly facturaveis: number;
  /** As que a nossa regra diria facturáveis: `max(0, contador − 1000)`. */
  readonly estimadasFacturaveis: number;
  /**
   * `|contador − entregues| / entregues`.
   *
   * É a pergunta fundamental: **contámos bem?** Compara o nosso contador com
   * as entregas que o `pricing` testemunha, que é a mesma grandeza.
   */
  readonly divergenciaDaContagem: number | null;
  /**
   * `|estimadasFacturaveis − facturaveis| / facturaveis`.
   *
   * É a pergunta do dinheiro: **a fronteira do *free tier* é onde pensamos?**
   *
   * **As duas existem porque o critério 7 é ambíguo e não se escolhe em
   * silêncio.** Ele diz «o contador interno vs `pricing.billable` agregado», e
   * o contador interno conta **todas** as *service* entregues (1.200) enquanto
   * o `billable` só marca as que estão acima do tecto (200). Comparar os dois
   * números directamente era comparar grandezas diferentes e obter 83% de
   * divergência num canal onde tudo está certo. Logo: a contagem compara-se
   * com a contagem, e o facturável com o facturável. Qual das duas é o «≤ 2%»
   * do critério é decisão de quem o escreveu — está na secção de verificação, e
   * as duas são medidas.
   */
  readonly divergenciaDoFacturavel: number | null;
  /** Micro-dólares que a nossa estimativa dá para o contador do período. */
  readonly microUsdEstimado: number;
}
