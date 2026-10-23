/**
 * O vocabulário do aviso ao dono: tipos, portas e listas fechadas (KAM-115).
 *
 * Os nomes são os do §3.23 do dicionário (emenda 1.32) e os domínios são os
 * mesmos que a revisão `0019` impõe por `CHECK`. Quando um valor aparece nos
 * dois sítios é porque tem de aparecer: o `CHECK` é a última barreira e esta
 * lista é a primeira, e um teste compara as duas — a `0008` e a `0009` pagaram
 * a lição de as deixar divergir, e o KAM-021 repetiu-a.
 *
 * ## O gatilho é a **situação** e não o tipo do evento
 *
 * O critério 1 enumera cinco situações, e duas delas chegam pelo mesmo tipo de
 * evento: o `channel.updated` traz o `desligado` com um dos seis motivos de
 * `PARTNER_REMOVED`, e o `restrito` por qualidade também é uma actualização de
 * canal. Se o gatilho fosse o tipo, os dois casos tinham o mesmo texto — e o
 * «cada um com texto próprio e o passo seguinte» do critério ficava sem sujeito.
 *
 * **Os seis motivos de desligamento são um gatilho só**, e isto é decisão: o
 * critério escreve «(cada um dos 6 motivos de `PARTNER_REMOVED`)», e o que ele
 * pede é que os seis **gerem** aviso, não que gerem seis textos. O passo
 * seguinte é o mesmo nos seis — reconectar pelo painel —, e seis modelos iguais
 * eram seis sítios para a mesma frase divergir. O motivo entra no `episodio`,
 * que é o que faz um `change_number` depois de um `primary_inactivity` ser um
 * episódio novo e não uma repetição.
 *
 * ## Em minúsculas e sem acentos, e a razão foi medida
 *
 * Estes valores são também `outcome` de linha de registo, e o `IDENTIFICADOR`
 * do `../logger/politica.ts` aceita **palavras de letras minúsculas** com até
 * três dígitos no fim. **Em modo estrito, que é o do CI, o `Logger` levanta** um
 * valor que a gramática recuse — e um aviso perfeitamente normal passava a
 * excepção não tratada no caminho de quem trata o *webhook*. É a mesma classe de
 * defeito que o `sem_humano_24h` do KAM-018 pagou e que a `0018` repetiu para os
 * motivos de desligamento; aqui o que isso proíbe é um `painel_indisponível` com
 * acento.
 *
 * ## Nunca pelo WhatsApp, e o critério pede um teste de configuração
 *
 * O ticket chama-se «por canal alternativo» porque **avisar o dono pelo canal
 * que falhou é inútil**. O critério 8 pede «nenhum adaptador de envio WhatsApp
 * neste módulo (teste de configuração)», e a forma de o garantir não é uma
 * promessa no comentário: os `CANAIS` são dois, o `Notificador` só se registra
 * para um deles, e há um teste que lê os `import` deste directório e recusa
 * qualquer um que venha do `../outbound` — que é onde vive o cliente da Meta.
 *
 * ## O SMS **não** está pré-declarado
 *
 * O ticket diz «o SMS fica atrás da interface `SmsProvider` de KAM-116 e só se
 * activa quando esse contrato existir». Portanto não há `"sms"` nos `CANAIS`,
 * nem tipo `SmsNotifier`, nem coluna, nem valor de `CHECK`: um nome sem
 * superfície é o que o *gate* 3b recusa, e o `ARRAY_DOS_ECHOES` do KAM-017
 * mostrou o que custa pré-declarar. O que existe é o **lugar** — o
 * `Notificador` é uma interface com o canal dentro, e o KAM-116 acrescenta uma
 * implementação e uma linha ao domínio.
 *
 * ## As seis portas
 *
 * O módulo não abre ligação nenhuma que não precise e não implementa nada que
 * seja de outro ticket:
 *
 * 1. **`ClienteSql`** — a ligação de `kamba_app`, com contexto de tenant e
 *    dentro da transacção de quem chama. É o papel que a `0019` autoriza a
 *    escrever `owner_notices` e `owner_contacts`. A transacção não é detalhe,
 *    pela razão que o `qualidade/contrato.ts` escreveu: os passos de um aviso
 *    são decidir, registar e entregar, e com cada um na sua transacção um
 *    processo que caia pelo meio deixa um aviso registado que nunca sai — ou,
 *    pior, entrega um aviso cujo registo se perdeu e volta a entregá-lo.
 * 2. **`Notificador`** — quem entrega. Um por canal, e é a porta do
 *    `OwnerNotifier` dos *Detalhes Técnicos*. Porta e não chamada directa porque
 *    o fornecedor de e-mail é um subprocessador (KAM-069) e a sua escolha
 *    bloqueia `prod` por ADR-008: o módulo tem de funcionar inteiro contra um
 *    fornecedor falso, que é o que o critério 3 manda medir.
 * 3. **`Decifrar`** — de `(tenant, cifra)` para o endereço. Porta porque a KEK
 *    vive no cofre e este módulo não o conhece; e porque é ela que mantém o
 *    endereço em claro **fora** do estado deste módulo — ele existe entre a
 *    decifra e a entrega, e em mais nenhum sítio.
 * 4. **`AbrirTarefa`** — a fila humana do T2. Porta porque não existe mecanismo
 *    de *ticket* neste repositório (dívida **73**, escrita pelo KAM-021), e
 *    inventar um a partir de um critério deste ticket era alargar o escopo em
 *    silêncio. O que o módulo garante é que **chama**, e o teste verifica a
 *    chamada.
 * 5. **`Relogio`** — `() => Date`. **Nenhuma função deste módulo chama
 *    `Date.now()`**, e é isso que torna os critérios 3 e 4 mensuráveis: «medida
 *    com relógio acelerado», «lembretes às 24 h e 72 h». Com o relógio por
 *    dentro, um teste das 72 h media o `setTimeout` da máquina. É a escolha do
 *    `limites.ts` do KAM-015, do `modos.ts` do KAM-018 e do KAM-017.
 * 6. **`NovoToken`** — `() => Uint8Array`, o segredo da ligação de confirmação.
 *    Porta por uma razão de teste e não de desenho: com o gerador por dentro, o
 *    teste da confirmação não pode saber o *token* que foi emitido, e o que
 *    ficava provado era que a função não falha — não que a ligação funciona.
 *
 * ## Não há agendador, e isso é o precedente da casa
 *
 * Os lembretes das 24 h e das 72 h não têm agendador: não existe nenhum neste
 * repositório — nem `repeat:`, nem `delay:`, nem `cron` — e nasce com o
 * KAM-071/KAM-078. O que existe é o padrão que o `abandonarVencidas` do KAM-016,
 * o `pausarPorInactividade` do KAM-018 e as varreduras do KAM-017 escreveram:
 * **uma função idempotente por predicado SQL, com o relógio por parâmetro,
 * testável agora e chamável depois**. É o que este módulo entrega, e está dito
 * na secção de verificação.
 */

/**
 * O cliente de SQL que este módulo precisa.
 *
 * `readonly rows` como o `ClienteSql` do KAM-015, do KAM-021 e do KAM-017, e
 * pela mesma razão: este módulo nunca altera o que lê, e um tipo com `rows`
 * mutável obrigava quem o liga a provar que não o altera.
 */
export interface ClienteSql {
  query<T = Record<string, unknown>>(
    texto: string,
    valores?: readonly unknown[],
  ): Promise<{ readonly rows: readonly T[] }>;
}

/**
 * Os cinco gatilhos do critério 1.
 *
 * O mesmo domínio que o `owner_notices_gatilho_ck` da revisão `0019` impõe, e
 * **há um teste que compara os dois** contra o `pg_get_constraintdef`.
 *
 * `painel_indisponivel` é ***proposta***: o critério escreve «HND indisponível
 * > 5 min (*proposta*)», e o número está no `LIMIAR_DO_PAINEL_MS`. Os outros
 * quatro vêm de emissores que existem — KAM-017 (`desligado` e
 * `channel.inactivity_warning`), KAM-021 (`restrito` por qualidade RED) e
 * KAM-023 (`motivo_restricao='payment_method'`).
 */
export const GATILHOS = [
  "canal_desligado",
  "inactividade",
  "qualidade_restrita",
  "sem_pagamento",
  "painel_indisponivel",
] as const;
export type Gatilho = (typeof GATILHOS)[number];

/**
 * Os canais por onde um aviso sai. **O WhatsApp não é um deles.**
 *
 * Ver a nota do módulo: é o ticket inteiro, e o critério 8 pede um teste de
 * configuração a prová-lo.
 */
export const CANAIS = ["email", "painel"] as const;
export type Canal = (typeof CANAIS)[number];

/**
 * Os canais que têm **endereço** — isto é, que precisam de um `owner_contacts`.
 *
 * Hoje um só. O painel é um canal por onde o aviso sai e **não tem endereço**:
 * quem o lê é o dono quando entra, e a notificação identifica-se pelo
 * `tenant_id` que a RLS já impõe. É por isso que o
 * `owner_contacts_canal_ck` da `0019` tem um valor e o `owner_notices_canal_ck`
 * tem dois — dois domínios da mesma palavra, qualificados pela coluna, pela
 * regra da emenda 1.14.
 */
export const CANAIS_COM_ENDERECO: readonly Canal[] = ["email"];

/** Os três estados de um aviso. Ver a `0019`: **não há `suprimido`**. */
export const ESTADOS = ["pendente", "entregue", "falhado"] as const;
export type Estado = (typeof ESTADOS)[number];

/**
 * Porque é que um aviso falhou.
 *
 * Quatro e não três: um `sem_contacto` tratado como `bounce` marcava como
 * inválido um endereço que não existe — e o critério 7 manda marcar o contacto,
 * não inventá-lo.
 */
export const MOTIVOS_DE_FALHA = [
  "bounce",
  "rejeitado",
  "sem_contacto",
  "indisponivel",
] as const;
export type MotivoDeFalha = (typeof MOTIVOS_DE_FALHA)[number];

/**
 * Os motivos que condenam o endereço, dos quatro acima.
 *
 * **Dois e não quatro**, e a diferença é o critério 7: um `bounce` ou uma
 * rejeição dizem que *aquele endereço* não serve; um fornecedor em baixo
 * (`indisponivel`) não diz nada sobre o endereço, e marcar o contacto por isso
 * era deixar o dono sem canal por uma avaria nossa. O `sem_contacto` não condena
 * nada porque não há nada a condenar.
 */
export const MOTIVOS_DE_INVALIDEZ: readonly MotivoDeFalha[] = ["bounce", "rejeitado"];

/**
 * Porque é que um aviso **não** saiu, quando não saiu por decisão nossa.
 *
 * Isto não é um domínio da base: um aviso recusado não escreve linha (ver a
 * `0019`). É a etiqueta de `owner_notice_suppressed_total`, e existe porque
 * recusar sem contar é recusar em silêncio — a razão que a
 * `outbound_rate_limited_total` da emenda 1.21 escreveu.
 */
export const MOTIVOS_DE_SUPRESSAO = [
  "gatilho_desconhecido",
  "janela_do_gatilho",
  "tecto_diario",
  "lembretes_esgotados",
  "ja_avisado",
] as const;
export type MotivoDeSupressao = (typeof MOTIVOS_DE_SUPRESSAO)[number];

/**
 * As ordens de lembrete: `0` o aviso, `1` as 24 h, `2` as 72 h.
 *
 * O `owner_notices_lembrete_ck` da `0019` impõe o mesmo intervalo, e é o «depois
 * pára» do critério 4 na base.
 */
export const LEMBRETES = [0, 1, 2] as const;
export type Lembrete = (typeof LEMBRETES)[number];

/** O último lembrete que existe. Depois dele abre-se tarefa a T2. */
export const LEMBRETE_MAXIMO = 2;

/**
 * Quando sai cada lembrete, a contar do aviso próprio.
 *
 * **24 h e 72 h, e são do critério 4 e não derivadas uma da outra.** 72 não é
 * 24 × 3 por acaso aritmético: o critério escreve os dois números, e escrevê-los
 * como `[24, 72]` em vez de `[24, 24 * 3]` é dizer que são dois valores de
 * produto e não uma progressão — se o Piloto mudar o segundo, não arrasta o
 * primeiro.
 */
export const ATRASO_DO_LEMBRETE_MS: readonly number[] = [
  24 * 60 * 60 * 1_000,
  72 * 60 * 60 * 1_000,
];

/**
 * A janela em que um gatilho só avisa uma vez: **24 h** (critério 4,
 * ***proposta***).
 *
 * É o «≤ 1 aviso por (tenant, gatilho) em 24 h». Mede-se do `criado_at` do
 * último aviso **desse gatilho** e não do episódio: dois episódios diferentes do
 * mesmo gatilho dentro de 24 h dão **um** aviso, e é isso que faz o «500
 * eventos/hora de um só tenant enviam ≤ 3» ser verdade mesmo quando os 500
 * trazem episódios todos diferentes.
 */
export const JANELA_DO_GATILHO_MS = 24 * 60 * 60 * 1_000;

/**
 * Quantos avisos um tenant leva por dia: **3** (critério 4, ***proposta***).
 *
 * Cinco gatilhos e um tecto de três: um dono com o canal desligado, a qualidade
 * em RED e o pagamento em falta leva três avisos e não cinco, e o que ele
 * precisa de saber é que tem de entrar no painel. O dia é o **dia corrido de 24
 * h** e não o dia civil, pela razão de sempre: um dia civil faz o tecto
 * reiniciar à meia-noite e um dono avisado três vezes às 23 h leva outros três
 * uma hora depois.
 */
export const TECTO_DIARIO = 3;

/** A janela do tecto diário: **24 h corridas**. Ver o `TECTO_DIARIO`. */
export const JANELA_DIARIA_MS = 24 * 60 * 60 * 1_000;

/**
 * O alvo de latência do evento ao aviso entregue: **5 min p95** (critério 3,
 * ***proposta***).
 *
 * Não é um prazo que o módulo imponha — é o alvo que a métrica
 * `owner_notice_latency_s` existe para medir. O que o módulo garante é que o
 * caminho é síncrono dentro da transacção de quem chama, pelo que a latência é a
 * do fornecedor e não a de uma fila nossa.
 */
export const LATENCIA_ALVO_MS = 5 * 60 * 1_000;

/**
 * Quanto tempo o painel tem de estar em baixo para avisar: **5 min**
 * (***proposta***).
 *
 * O critério 1 escreve «HND indisponível > 5 min (*proposta*)». Quem mede a
 * indisponibilidade é a sonda do KAM-002 e não este módulo; o que está aqui é o
 * limiar que o gatilho pressupõe, para que o número viva num sítio só.
 */
export const LIMIAR_DO_PAINEL_MS = 5 * 60 * 1_000;

/**
 * Quanto vale uma ligação de confirmação: **7 dias** (***proposta***).
 *
 * O critério 6 pede a ligação e não lhe dá prazo. Sete dias é escolha nossa, e
 * escolhe-se longa de propósito: a ligação é a única coisa que separa um dono de
 * poder ser avisado, e um prazo curto faz o dono que abriu o e-mail na
 * segunda-feira seguinte ficar sem canal alternativo. A calibrar no Piloto.
 */
export const PRAZO_DA_CONFIRMACAO_MS = 7 * 24 * 60 * 60 * 1_000;

/** Octetos do *token* da ligação de confirmação. */
export const OCTETOS_DO_TOKEN = 32;

/** Octetos de um `sha256`, e o comprimento de `owner_contacts.confirmacao_hash`. */
export const OCTETOS_DE_RESUMO = 32;

/** O que um `Notificador` devolve. */
export interface ResultadoDaEntrega {
  readonly entregue: boolean;
  /** `null` quando entregou. Um dos quatro motivos quando não. */
  readonly motivo: MotivoDeFalha | null;
}

/**
 * Quem entrega um aviso por um canal.
 *
 * É o `OwnerNotifier` dos *Detalhes Técnicos*, e o `canal` está **dentro** da
 * interface e não ao lado: com ele fora, nada impedia registar o notificador de
 * e-mail no lugar do painel, e o aviso saía pelo canal errado sem que nada o
 * dissesse. O KAM-116 acrescenta uma implementação com `canal = "sms"` e uma
 * linha ao domínio da `0019`.
 *
 * O `destino` é `null` para os canais sem endereço. Não é opcional: um parâmetro
 * opcional deixava esquecê-lo, e o que se esquecia era o endereço de quem
 * precisa de ser avisado.
 */
export interface Notificador {
  readonly canal: Canal;
  entregar(
    destino: string | null,
    aviso: AvisoRenderizado,
  ): Promise<ResultadoDaEntrega>;
}

/**
 * O aviso, já em texto. **Sem nada que não esteja na lista do critério 5.**
 *
 * Quem o constrói é o `modelos.ts`, que recusa um parâmetro fora da lista.
 */
export interface AvisoRenderizado {
  readonly gatilho: Gatilho;
  readonly assunto: string;
  readonly corpo: string;
  /** O passo seguinte, em texto: reconectar, abrir a app, adicionar cartão. */
  readonly passo: string;
  /** A ligação ao painel, **sem *token* e sem identificador pessoal**. */
  readonly painel: string;
}

/** De `(tenant, cifra)` para o endereço em claro. Ver a nota das portas. */
export type Decifrar = (tenantId: string, cifra: Uint8Array) => string;

/** A fila humana do T2. Ver a nota das portas e a dívida **73**. */
export type AbrirTarefa = (pedido: {
  readonly tenantId: string;
  readonly gatilho: Gatilho | null;
  readonly assunto: string;
}) => Promise<void>;

/** O relógio. Ver a nota do módulo: nenhuma função aqui chama `Date.now()`. */
export type Relogio = () => Date;

/** O gerador do *token* da ligação de confirmação. */
export type NovoToken = () => Uint8Array;

/** O contacto alternativo do dono, como as consultas deste módulo o lêem. */
export interface Contacto {
  readonly id: string;
  readonly tenantId: string;
  readonly canal: Canal;
  /** **Cifrado.** O claro existe entre a `Decifrar` e a entrega, e em mais nenhum sítio. */
  readonly enderecoEnc: Uint8Array;
  readonly verificadoAt: Date | null;
  readonly invalidoAt: Date | null;
  readonly motivoInvalido: MotivoDeFalha | null;
}

/** A linha de `owner_notices`, como as consultas deste módulo a lêem. */
export interface Aviso {
  readonly id: string;
  readonly tenantId: string;
  readonly gatilho: Gatilho;
  readonly episodio: string;
  readonly lembrete: number;
  readonly canal: Canal;
  readonly estado: Estado;
  readonly tentativas: number;
  readonly falhaMotivo: MotivoDeFalha | null;
  readonly criadoAt: Date;
  readonly entregueAt: Date | null;
}

/**
 * O que um pedido de aviso produziu.
 *
 * `avisos` são as linhas escritas — uma por canal —, e `suprimido` é o motivo
 * quando não se escreveu nenhuma. **Os dois campos não são exclusivos**: um
 * aviso pode sair pelo painel e ser suprimido no e-mail porque o endereço é
 * inválido, e devolver só um deles obrigava quem chama a adivinhar.
 */
export interface ResultadoDoAviso {
  readonly avisos: readonly Aviso[];
  readonly suprimido: MotivoDeSupressao | null;
  /** `true` quando se abriu tarefa a T2 — por falha de entrega ou por falta de contacto. */
  readonly tarefaAberta: boolean;
}

/** Um episódio cujo lembrete está devido. */
export interface LembreteDevido {
  readonly tenantId: string;
  readonly gatilho: Gatilho;
  readonly episodio: string;
  /** `1` para as 24 h, `2` para as 72 h. */
  readonly lembrete: number;
}

/**
 * O que uma varredura de lembretes fez.
 *
 * **Os `lembretes` são episódios e não `id` de linhas**, e a primeira versão
 * desta interface dizia o contrário («os `id` dos avisos de lembrete
 * escritos»). A varredura **não escreve nada**: ela diz quais os episódios em
 * que, se o estado persistir, está na hora — e quem escreve é o `notificar`,
 * depois de quem chama confirmar que o estado persiste. Devolver `id` de linhas
 * que ninguém escreveu era prometer uma escrita que não acontece. Achado da
 * revisão adversarial deste ticket.
 */
export interface ResultadoDaVarredura {
  readonly lembretes: readonly LembreteDevido[];
  /** Os tenants cujos lembretes se esgotaram e foram para a fila do T2. */
  readonly esgotados: readonly string[];
}
