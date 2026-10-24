/**
 * O vocabulário do *shim* da fila do AGR (KAM-025).
 *
 * O *shim* é a casca que tira um *job* da `agr-inbound` e chama
 * `POST /internal/turn` no AGR. A decisão de ser isto, e não um consumidor
 * Python do BullMQ, está em `docs/adr/ADR-L004-fila-e-tranca-do-agr.md`
 * (Decisão 1), com as duas opções e o que cada uma custa.
 *
 * ## O que este módulo **não** decide
 *
 * A fila (`FILA_AGR`), o nome do *job* (`JOB_AGR`) e o contrato
 * (`AgentInvocation`) são do **CHR** (KAM-014) e vivem em `../chr/contrato.ts`:
 * quem publica define o que publica. O que aqui está é o lado de quem consome —
 * para onde se chama, com que credencial, e quanto tempo se espera.
 *
 * ## Os dois números que se pagam por esta escolha, ditos onde estão
 *
 * O `ADR-L004` escreve que o *shim* **espera** pela resposta: o *job* fica
 * aberto durante o turno, de propósito, porque é isso que faz o critério 4
 * (retoma depois de um `SIGKILL`) funcionar. Isso põe dois números em jogo:
 *
 * - **`TRANCA_DO_JOB_MS`** — o `lockDuration` do BullMQ. Decide se um *job* é
 *   declarado `stalled` com o *worker* vivo. Curto demais não perde o *job*:
 *   **duplica-o**, e é por isso que o AGR é idempotente por `turn_id`.
 * - **`ESPERA_MAXIMA_MS`** — o tempo que o `fetch` espera. Tem de ser **menor**
 *   do que o `lockDuration`, senão o BullMQ declara o *job* `stalled` enquanto
 *   este *worker* ainda está à espera da resposta, e o turno corre duas vezes
 *   em dois processos — contra a mesma tranca, em série, mas duas vezes.
 *
 * Os dois são *proposta* e calibram-se em KAM-084, com o perfil de carga real.
 */

/** O cabeçalho que leva a credencial interna. Dicionário §3.24. */
export const CABECALHO_INTERNO = "x-kamba-interno";

/** O caminho da rota que corre um turno. */
export const CAMINHO_DO_TURNO = "/internal/turn";

/**
 * Quanto tempo o `fetch` ao AGR espera, em ms. *Proposta*.
 *
 * O orçamento de latência de um turno de texto é 3–7 s (`docs/tecnica/02`
 * §15.1) e o alvo p95 é 4–8 s. Trinta segundos dá folga de quatro vezes sobre
 * o alvo e continua muito abaixo do `lockDuration`.
 */
export const ESPERA_MAXIMA_MS = 30_000;

/**
 * O `lockDuration` do *job*, em ms. *Proposta*.
 *
 * Quatro vezes a `ESPERA_MAXIMA_MS`. A margem não é generosidade: o tempo que
 * um *job* fica aberto é a espera do `fetch` **mais** o tempo que a mensagem
 * passa na admissão do AGR (fila por conversa, tecto do *tenant*), e esse
 * segundo pedaço não tem tecto fixo — depende de quantas mensagens da mesma
 * conversa estão à frente.
 */
export const TRANCA_DO_JOB_MS = 120_000;

/**
 * Quantos *jobs* um *worker* trata ao mesmo tempo.
 *
 * **Quatro, e não um** — é a única vez neste repositório, e a razão está no
 * cabeçalho de `shim.ts`: os outros dois *workers* da casa têm concorrência 1
 * porque o trabalho deles é uma transacção numa ligação à base, e aqui não há
 * ligação nenhuma: há um `fetch`. Um *worker* a esperar 3–7 s por turno
 * processava uns dez turnos por minuto.
 *
 * O comentário dizia «um *job* de cada vez por *worker*» ao lado do valor 4,
 * contradizendo o valor e o próprio `shim.ts`. Achado da revisão adversarial.
 */
export const CONCORRENCIA = 4;

/**
 * Quantas vezes se tenta um *job* antes de ele ficar em `failed`.
 *
 * Seis (1 + 5), que é a escada do consumidor de eventos (`docs/tecnica/06`
 * §6.4) e a única escada do repositório. O que se retenta aqui é da mesma
 * natureza: o AGR em baixo, a base em baixo, um 503 de contrapressão.
 */
export const TENTATIVAS = 6;

/**
 * O mesmo número, com o nome que o **produtor** usa.
 *
 * O `chr/fila.ts` põe-no em `attempts` no `fila.add`, porque o `attempts` é
 * opção do *job* e não do *worker*: sem ele o BullMQ dá **uma** tentativa e
 * manda o *job* para `failed`, e todo o caminho de contrapressão do AGR — «503
 * e o *job* volta à fila com atraso» — era falso. Um alias e não um segundo
 * número, para que não possam divergir; o nome é explícito porque quem lê o
 * produtor não tem contexto do *shim*.
 */
export const TENTATIVAS_DO_AGR = TENTATIVAS;

/** A variável com a URL base do AGR na rede interna. Dicionário §3.24. */
export const VARIAVEL_DO_AGR = "KAMBA_AGR_URL";

/**
 * O que o AGR responde, na forma que o *shim* lê.
 *
 * Só o `outcome` interessa ao *shim*, e nem esse para decidir: o que decide se
 * o *job* se repete é o **estado HTTP** (tabela em
 * `services/agr/src/kamba_agr/api_interna.py`). O `outcome` serve para o
 * registo, e é por isso que é uma lista fechada: entra em métrica.
 */
export const DESFECHOS_DO_AGR = [
  "executado",
  "entregue_ao_hnd",
  "sem_conversa",
  "descartado",
  "tecto_do_tenant",
  "grafo_nao_registado",
  "invocacao_invalida",
  "nao_autorizado",
] as const;
export type DesfechoDoAgr = (typeof DESFECHOS_DO_AGR)[number];

/** O desfecho de uma resposta do AGR, ou `desconhecido` se não for um dos oito. */
export function desfechoDe(corpo: unknown): DesfechoDoAgr | "desconhecido" {
  if (typeof corpo !== "object" || corpo === null) return "desconhecido";
  const valor = (corpo as Record<string, unknown>).outcome;
  return (DESFECHOS_DO_AGR as readonly string[]).includes(valor as string)
    ? (valor as DesfechoDoAgr)
    : "desconhecido";
}
