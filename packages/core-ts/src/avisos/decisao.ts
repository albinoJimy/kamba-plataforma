/**
 * As decisões do aviso ao dono, sem base de dados e sem relógio de sistema
 * (KAM-115, critérios 1, 2, 4, 6 e 7).
 *
 * Funções puras. Recebem o instante, o histórico e o contacto, e devolvem o que
 * fazer. É aqui que vivem as regras que os critérios escrevem, e é por isso que
 * é aqui que as mutações batem: uma regra dentro de uma consulta SQL prova-se
 * contra uma base, uma regra numa função pura prova-se contra uma tabela de
 * casos — e as duas coisas fazem-se, porque a consulta também tem o seu ensaio.
 *
 * ## A chave da idempotência é um resumo, e leva o tenant dentro
 *
 * O critério 2 escreve `hash(tenant_id, gatilho, episódio)`. O `tenant_id` lá
 * dentro não é arrumação: sem ele, dois tenants com o mesmo `episodio` — e um
 * `episodio` é muitas vezes um `channel_id` ou uma `event_key` da Meta —
 * partilhavam a chave, e o segundo nunca era avisado. A unicidade da `0019` é
 * `(tenant_id, chave, …)` e teria apanhado a colisão com um `23505`; o que se
 * perderia era o aviso, porque a escrita é `ON CONFLICT DO NOTHING`.
 *
 * É `sha256` e **não** HMAC: não há segredo a proteger aqui. A chave não esconde
 * o episódio de ninguém — quem lê a base vê o `episodio` na coluna ao lado. O
 * que ela faz é dar comprimento fixo a um texto de comprimento arbitrário, que é
 * o que um índice de unicidade quer.
 *
 * ## Os dois limites medem-se dos avisos, não das tentativas
 *
 * O critério 4 pede «≤ 1 aviso por (tenant, gatilho) em 24 h e ≤ 3 por
 * tenant/dia». Os dois contam **linhas de `owner_notices`**, e isso é o que faz
 * o «500 eventos/hora de um só tenant enviam ≤ 3» sair de graça: as 500
 * tentativas não escrevem 500 linhas — escrevem até três, e as outras 497 são
 * recusadas por um dos dois limites. Contar tentativas em vez de avisos dava um
 * limite que se gastava com o que não saiu.
 *
 * **E a janela do gatilho vem antes do tecto diário.** A ordem importa e é
 * medida: com o tecto primeiro, um tenant com três episódios do mesmo gatilho
 * gastava o dia todo num gatilho só e os outros quatro ficavam sem voz para as 24
 * h seguintes. Com a janela primeiro, o segundo episódio do mesmo gatilho é
 * recusado por `janela_do_gatilho` **sem gastar nada do tecto**, que fica para os
 * gatilhos que ainda não falaram. É a diferença entre um dono que sabe que tem
 * três problemas e um dono que sabe três vezes o mesmo.
 *
 * ## O lembrete é devido pelo relógio e **persiste** pelo estado
 *
 * O critério 4 diz «lembretes às 24 h e 72 h **se o estado persiste**». As duas
 * metades são de sítios diferentes: o relógio é desta função, e a persistência é
 * de quem chama — o módulo não sabe se um canal continua desligado, e inventar
 * essa leitura era duplicar o que o KAM-017 e o KAM-021 já sabem. O que esta
 * função responde é «se o estado persistir, está na hora?».
 */

import { createHash } from "node:crypto";

import {
  ATRASO_DO_LEMBRETE_MS,
  CANAIS_COM_ENDERECO,
  GATILHOS,
  JANELA_DIARIA_MS,
  JANELA_DO_GATILHO_MS,
  LEMBRETE_MAXIMO,
  MOTIVOS_DE_INVALIDEZ,
  TECTO_DIARIO,
  type Aviso,
  type Canal,
  type Contacto,
  type Gatilho,
  type MotivoDeFalha,
  type MotivoDeSupressao,
} from "./contrato.ts";

/** O domínio do resumo, para que uma chave nossa não colida com outra de outro módulo. */
const DOMINIO = "kamba.avisos.v1";

/** O separador dos campos da chave. */
const SEPARADOR = "\u0000";

/**
 * A chave de idempotência de um episódio.
 *
 * `sha256(domínio ␀ tenant ␀ gatilho ␀ episódio)`, 32 octetos — o comprimento
 * que o `owner_notices_chave_ck` da `0019` impõe.
 *
 * **O separador é o octeto nulo** e não um ponto ou um hífen, pela razão que o
 * `prova.ts` do KAM-022 escreveu: um `episodio` que contenha o separador podia
 * fazer dois trios diferentes darem a mesma cadeia, e o octeto nulo não aparece
 * em nenhum dos três campos — o `gatilho` é de uma lista fechada, o `tenant_id`
 * é um UUID e o `episodio` vem de identificadores da Meta.
 */
export function chaveDoEpisodio(
  tenantId: string,
  gatilho: Gatilho,
  episodio: string,
): Buffer {
  const resumo = createHash("sha256");
  resumo.update([DOMINIO, tenantId, gatilho, episodio].join(SEPARADOR), "utf8");
  return resumo.digest();
}

/**
 * O resumo do *token* da ligação de confirmação.
 *
 * `sha256` do *token* em bruto, sem domínio e sem chave. Sem domínio porque não
 * há outro resumo de 32 octetos nesta tabela com que ele possa ser confundido; e
 * sem chave pela razão da `0019`: 32 octetos do gerador do sistema não se
 * enumeram.
 */
export function resumoDoToken(token: Uint8Array): Buffer {
  return createHash("sha256").update(token).digest();
}

/** `true` se o gatilho é um dos cinco do critério 1. */
export function gatilhoConhecido(valor: unknown): valor is Gatilho {
  return typeof valor === "string" && (GATILHOS as readonly string[]).includes(valor);
}

/**
 * `true` se este canal precisa de um `owner_contacts` para entregar.
 *
 * Função e não leitura directa do array, porque é ela que torna o critério 6
 * verificável: o «tenant `ativo` sem contacto verificado gera alerta» só se
 * aplica aos canais com endereço — exigir contacto para o painel fazia todos os
 * tenants sem e-mail ficarem também sem a notificação do painel, que é
 * exactamente o canal de reserva que o critério 7 manda usar quando o e-mail
 * falha.
 */
export function precisaDeEndereco(canal: Canal): boolean {
  return CANAIS_COM_ENDERECO.includes(canal);
}

/**
 * `true` se este contacto pode receber um aviso.
 *
 * Verificado **e** não inválido. As duas condições, e não uma: um endereço
 * verificado que depois deu *bounce* está verificado e não serve, e um endereço
 * novo que ninguém confirmou pode muito bem estar mal escrito — o critério 6
 * pede «verificado por ligação de confirmação» precisamente porque um e-mail que
 * o dono escreveu num formulário não prova que o dono o lê.
 */
export function contactoUtilizavel(contacto: Contacto | null): boolean {
  if (contacto === null) return false;
  return contacto.verificadoAt !== null && contacto.invalidoAt === null;
}

/**
 * `true` se este motivo de falha condena o endereço (critério 7).
 *
 * Função e não `includes` à mão, porque é o predicado que decide uma escrita
 * destrutiva: marcar um contacto inválido deixa o dono sem canal alternativo até
 * alguém o corrigir, e uma indisponibilidade do fornecedor não é razão para
 * isso.
 */
export function condenaOEndereco(motivo: MotivoDeFalha): boolean {
  return MOTIVOS_DE_INVALIDEZ.includes(motivo);
}

/** O que a decisão de avisar concluiu. */
export interface Decisao {
  readonly avisar: boolean;
  /** O motivo da recusa, ou `null` quando se avisa. */
  readonly motivo: MotivoDeSupressao | null;
}

const SIM: Decisao = { avisar: true, motivo: null };

function nao(motivo: MotivoDeSupressao): Decisao {
  return { avisar: false, motivo };
}

/**
 * Decide se um aviso sai, dado o histórico recente do tenant.
 *
 * `historico` são os avisos do tenant nas últimas 24 h — todos os gatilhos, que
 * é o que o tecto diário precisa de ver. A ordem das quatro recusas está na nota
 * do módulo, e a primeira é a que o critério 1 escreve: um gatilho fora da lista
 * não envia nada.
 */
export function decidir(
  agora: Date,
  gatilho: unknown,
  episodio: string,
  lembrete: number,
  historico: readonly Aviso[],
): Decisao {
  if (!gatilhoConhecido(gatilho)) return nao("gatilho_desconhecido");
  if (lembrete < 0 || lembrete > LEMBRETE_MAXIMO) return nao("lembretes_esgotados");

  const instante = agora.getTime();

  // A repeticao do **mesmo** episodio no mesmo lembrete. Vem antes dos limites
  // porque nao e um limite: e o criterio 2, e um evento re-entregue pela DLQ nao
  // deve gastar o tecto diario de ninguem. Sem esta ordem, tres entregas do
  // mesmo evento consumiam o dia todo do dono e os outros gatilhos calavam-se.
  //
  // Compara-se `(gatilho, episodio)` e **nao a chave**: o historico vem de um
  // tenant so — e a RLS que o garante —, pelo que o `tenant_id` que a
  // `chaveDoEpisodio` leva dentro e constante aqui e o resumo nao acrescentava
  // nada. A chave serve a unicidade da base, que e onde o tenant varia.
  for (const anterior of historico) {
    if (anterior.lembrete !== lembrete) continue;
    if (anterior.gatilho === gatilho && anterior.episodio === episodio) {
      return nao("ja_avisado");
    }
  }

  // A janela de 24 h por gatilho, e **so para o aviso proprio**. Um lembrete e,
  // por definicao, um segundo aviso do mesmo gatilho dentro da janela — era a
  // propria regra a recusar o que o criterio 4 manda enviar. Achado da revisao
  // adversarial deste ticket; a primeira versao filtrava os dois e os lembretes
  // nunca saiam, com o teste a passar porque media o lembrete das 24 h num
  // historico vazio.
  if (lembrete === 0) {
    for (const anterior of historico) {
      if (anterior.gatilho !== gatilho) continue;
      if (instante - anterior.criadoAt.getTime() < JANELA_DO_GATILHO_MS) {
        return nao("janela_do_gatilho");
      }
    }
  }

  // O tecto diario, e conta **avisos distintos** e nao linhas: um aviso que sai
  // pelo e-mail e pelo painel e um aviso, e contar duas linhas fazia o tecto de
  // tres valer um e meio.
  const distintos = new Set<string>();
  for (const anterior of historico) {
    if (instante - anterior.criadoAt.getTime() >= JANELA_DIARIA_MS) continue;
    distintos.add(`${anterior.gatilho}${SEPARADOR}${anterior.episodio}${SEPARADOR}${anterior.lembrete}`);
  }
  if (distintos.size >= TECTO_DIARIO) return nao("tecto_diario");

  return SIM;
}

/**
 * A ordem do lembrete devido a esta hora, ou `null` se nenhum.
 *
 * `primeiro` é o `criado_at` do aviso próprio do episódio. Devolve `1` às 24 h,
 * `2` às 72 h, e `null` antes das 24 h — e **também** depois das 72 h, porque
 * depois do último lembrete o critério 4 manda parar e abrir tarefa a T2, e
 * devolver `3` fazia a base recusar com um `23514` em vez de o módulo parar.
 *
 * **Devolve o lembrete mais alto que já é devido**, e não o seguinte ao já
 * enviado: um processo que esteve em baixo entre as 24 h e as 72 h não deve
 * mandar os dois lembretes de seguida ao voltar. Quem já foi enviado sabe-se da
 * base, e é lá que a repetição é recusada.
 */
export function lembreteDevido(agora: Date, primeiro: Date): number | null {
  const decorrido = agora.getTime() - primeiro.getTime();
  let devido: number | null = null;
  for (const [indice, atraso] of ATRASO_DO_LEMBRETE_MS.entries()) {
    if (decorrido >= atraso) devido = indice + 1;
  }
  return devido;
}

/**
 * `true` quando os lembretes de um episódio se esgotaram.
 *
 * É o «depois pára e abre tarefa a T2» do critério 4. Separado do
 * `lembreteDevido` de propósito: aquele responde «qual», este responde «já
 * acabou», e juntá-los num `null` ambíguo fazia «ainda não é hora» e «já não há
 * mais» terem a mesma resposta — e os dois casos levam a coisas opostas, esperar
 * e abrir tarefa.
 */
export function lembretesEsgotados(agora: Date, primeiro: Date, ultimoEnviado: number): boolean {
  if (ultimoEnviado < LEMBRETE_MAXIMO) return false;
  const ultimo = ATRASO_DO_LEMBRETE_MS[ATRASO_DO_LEMBRETE_MS.length - 1] ?? 0;
  return agora.getTime() - primeiro.getTime() >= ultimo;
}

/**
 * `true` se a ligação de confirmação ainda vale.
 *
 * Compara com `>=` e não com `>`: um *token* que expira exactamente neste
 * instante expirou. É a convenção do `limites.ts` do KAM-015, e vale a pena ser
 * a mesma em todo o repositório — a diferença de um milissegundo não importa, a
 * de duas convenções importa.
 */
export function confirmacaoValida(agora: Date, expiraEm: Date | null): boolean {
  if (expiraEm === null) return false;
  return agora.getTime() < expiraEm.getTime();
}
