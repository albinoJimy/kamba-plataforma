/**
 * A tabela de transições dos modos da conversa (KAM-018, critério 1).
 *
 * Pura: não toca na base, não lê o relógio (recebe-o), não registra nada. É
 * `docs/tecnica/01` §10.2 em código, e a bateria
 * `tests/modos.transicoes.test.ts` afirma sobre as **trinta e duas** células —
 * quatro modos × oito gatilhos —, uma a uma, e não sobre uma amostra. Uma
 * amostra prova que as células que se escolheram estão certas; o que o critério
 * 1 pede é «qualquer outra transição é rejeitada», e isso só se prova
 * enumerando.
 *
 * ## A tabela é a fonte, e a fonte discorda de si mesma em dois sítios
 *
 * A §10.2 tem **um diagrama** e **uma tabela**, e os dois não dizem o mesmo:
 *
 * 1. o diagrama tem `dono → humano` («dono abre conversa no Chatwoot»); a
 *    tabela de quatro linhas **não** a tem, e o critério 1 também não a nomeia;
 * 2. a tabela tem `qualquer → pausada`; o diagrama só tem `bot → pausada` e
 *    `humano → pausada`.
 *
 * O segundo resolve-se a favor da tabela e do critério, que são explícitos
 * («qualquer→`pausada` por opt-out»). O primeiro resolve-se a favor do
 * **diagrama**, e a razão é de consequência e não de hierarquia: o dono abre a
 * conversa no Chatwoot de facto, e uma máquina que rejeitasse essa transição
 * deixava a conversa em `dono` enquanto um agente responde pelo Chatwoot — o
 * modo passava a mentir sobre quem tem a palavra, e o `PreSendGuard` continuava
 * a proteger a conversa pelo motivo errado. As duas divergências ficam
 * registadas em `docs/dividas-documentais.md`, e a decisão sobre a §10.2
 * devolve-se a quem a escreveu.
 *
 * ## E uma célula vem de fora da §10.2
 *
 * `pausada + handoff_pedido → humano`. Nem o diagrama nem a tabela a têm, e o
 * critério 1 não a nomeia — mas o **Contexto do próprio KAM-018** cita
 * `evidencia/E1` §4 como CONFIRMADO: «a Messaging Policy exige caminho de
 * escalonamento a humano em **todas** as conversas». Uma conversa `pausada` é
 * uma conversa de um cliente que disse «PARAR» ou que ficou 24 h sem resposta
 * humana; se esse cliente escrever a pedir uma pessoa, recusar a transição era
 * negar-lhe o caminho que a política exige. Está declarada aqui, na secção de
 * verificação do ticket, e tem um teste com o seu nome.
 *
 * ## Porque é que a tabela é um objecto e não um `switch`
 *
 * Porque o teste exaustivo precisa de a **percorrer**, e um `switch` não se
 * percorre. Com a tabela como dado, `tests/modos.transicoes.test.ts` afirma
 * duas coisas que um `switch` não deixaria afirmar: que as 32 células existem
 * (nenhum par fica sem decisão escrita) e que o conjunto das que `transita`
 * é **exactamente** o do §10.2 mais as duas declaradas acima.
 */

import {
  type EstadoDaConversa,
  GATILHOS,
  type Gatilho,
  MODOS,
  type Modo,
  type Resposta,
  SILENCIO_DO_DONO_MS,
} from "./contrato.ts";

/**
 * Uma célula da tabela: o que acontece, e **de onde vem**.
 *
 * A `fonte` não é decoração: é o que permite ao teste exaustivo distinguir as
 * células do §10.2 das três que vêm de outro lado, e ao `docs/modos-conversa.md`
 * citar a tabela sem a copiar. `condicao` marca a única célula cuja resposta
 * depende do tempo.
 */
export interface Celula {
  /** O modo de destino, ou `null` quando a célula não transita. */
  readonly para: Modo | null;
  /** `rejeitada` quando o gatilho não faz sentido neste modo. */
  readonly rejeitada: boolean;
  /** Só na célula `dono + cliente_escreveu`. Ver `silencioExpirou`. */
  readonly condicao?: "silencio_do_dono";
  /** Onde está escrita. Lista fechada, porque é o que o teste confere. */
  readonly fonte: "01§10.2 tabela" | "01§10.2 diagrama" | "E1§4" | "invariante";
}

/**
 * A tabela. Modo → gatilho → célula, e **todas as 32 estão escritas**.
 *
 * Uma célula em falta é um `TypeError` em compilação (os dois `Record` são
 * completos sobre `Modo` e `Gatilho`), e é por isso que não há caso por omissão
 * nenhum: um `?? rejeitada` aqui deixava um par novo passar em silêncio quando
 * alguém acrescentasse um gatilho, que é exactamente o que esta tabela existe
 * para não deixar acontecer.
 *
 * As células `invariante` são as que nenhuma fonte escreve porque não há nada a
 * escrever: são o «não acontece nada» do tráfego normal, e estão aqui porque o
 * critério 1 obriga a decidir **todos** os pares, e porque chamar-lhes
 * «rejeitada» fazia o contador de rejeições medir tráfego.
 */
export const TABELA: Readonly<Record<Modo, Readonly<Record<Gatilho, Celula>>>> = {
  // ------------------------------------------------------------------- bot
  bot: {
    // A transição central do ticket, e a única cuja **detecção** não está
    // entregue: precisa de `smb_message_echoes` (KAM-017). A célula está aqui
    // porque a tabela do §10.2 a tem e o teste exaustivo não pode mentir sobre
    // o seu conteúdo; quem a dispara é quem detectar o *echo*.
    echo_do_dono: { para: "dono", rejeitada: false, fonte: "01§10.2 tabela" },
    // Tráfego normal: o cliente escreve e o bot responde.
    cliente_escreveu: { para: null, rejeitada: false, fonte: "invariante" },
    // O dono manda `/bot` numa conversa que já está no bot. Não é defeito.
    comando_bot: { para: null, rejeitada: false, fonte: "invariante" },
    handoff_pedido: { para: "humano", rejeitada: false, fonte: "01§10.2 tabela" },
    // Não há *handoff* aberto: nada para resolver.
    handoff_resolvido: { para: null, rejeitada: true, fonte: "invariante" },
    opt_out: { para: "pausada", rejeitada: false, fonte: "01§10.2 tabela" },
    // As 24 h contam-se sobre um *handoff*, e em `bot` não há nenhum.
    sem_humano_24h: { para: null, rejeitada: true, fonte: "invariante" },
    // Reactivar só se aplica a quem está pausado.
    cliente_reactivou: { para: null, rejeitada: true, fonte: "invariante" },
  },
  // ------------------------------------------------------------------ dono
  dono: {
    // O dono continua a falar. Não muda o modo — mas **actualiza a actividade
    // humana**, e é isso que adia o silêncio e alimenta o guarda.
    echo_do_dono: { para: null, rejeitada: false, fonte: "invariante" },
    // A única célula condicional da tabela: devolve a palavra ao bot **se** o
    // dono esteve calado `silencio_dono_min`. Ver `silencioExpirou`.
    cliente_escreveu: {
      para: "bot",
      rejeitada: false,
      condicao: "silencio_do_dono",
      fonte: "01§10.2 tabela",
    },
    comando_bot: { para: "bot", rejeitada: false, fonte: "01§10.2 tabela" },
    // Do diagrama e não da tabela de quatro linhas. Ver a nota do módulo.
    handoff_pedido: { para: "humano", rejeitada: false, fonte: "01§10.2 diagrama" },
    // O `resolved` do Chatwoot sobre uma conversa que nunca lá entrou.
    handoff_resolvido: { para: null, rejeitada: true, fonte: "invariante" },
    opt_out: { para: "pausada", rejeitada: false, fonte: "01§10.2 tabela" },
    sem_humano_24h: { para: null, rejeitada: true, fonte: "invariante" },
    cliente_reactivou: { para: null, rejeitada: true, fonte: "invariante" },
  },
  // ---------------------------------------------------------------- humano
  humano: {
    // Um agente pode ser o dono, e o dono pode responder pelos dois sítios. O
    // modo não muda; a actividade humana é actualizada.
    echo_do_dono: { para: null, rejeitada: false, fonte: "invariante" },
    // Vai ao humano e não ao AGR (`chr.ts`, critério 7 do KAM-014). O modo não
    // muda, e **não** é actividade humana: escreveu o cliente.
    cliente_escreveu: { para: null, rejeitada: false, fonte: "invariante" },
    // **Rejeitada de propósito.** Quem devolve a palavra ao bot em `humano` é o
    // `conversation_status_changed=resolved` do Chatwoot, não um `/bot` escrito
    // na app: se um atendimento está aberto, fechá-lo pela app deixava a
    // conversa do Chatwoot aberta e o bot a falar por cima dela.
    comando_bot: { para: null, rejeitada: true, fonte: "invariante" },
    // Já está em atendimento humano. Pedir outra vez não é defeito.
    handoff_pedido: { para: null, rejeitada: false, fonte: "invariante" },
    handoff_resolvido: { para: "bot", rejeitada: false, fonte: "01§10.2 tabela" },
    opt_out: { para: "pausada", rejeitada: false, fonte: "01§10.2 tabela" },
    sem_humano_24h: { para: "pausada", rejeitada: false, fonte: "01§10.2 tabela" },
    cliente_reactivou: { para: null, rejeitada: true, fonte: "invariante" },
  },
  // --------------------------------------------------------------- pausada
  pausada: {
    // O dono responder a um cliente que pediu para parar é assunto do dono, e
    // não liga o bot. O modo fica.
    echo_do_dono: { para: null, rejeitada: false, fonte: "invariante" },
    // **Não é a reactivação.** O §10.2 diz «o cliente escreve de novo **após
    // aviso**», e o aviso é KAM-022: uma mensagem qualquer de um cliente que
    // pediu para parar não desfaz o opt-out. O bot continua calado.
    cliente_escreveu: { para: null, rejeitada: false, fonte: "invariante" },
    comando_bot: { para: null, rejeitada: true, fonte: "invariante" },
    // De `E1` §4 (CONFIRMADO), citado no Contexto do ticket. Ver a nota do
    // módulo: negar esta célula era negar o escalonamento a humano que a
    // Messaging Policy exige em todas as conversas.
    handoff_pedido: { para: "humano", rejeitada: false, fonte: "E1§4" },
    handoff_resolvido: { para: null, rejeitada: true, fonte: "invariante" },
    // Já está pausada. Repetir o «PARAR» não é defeito nem transição — e é o
    // que torna o `onOptOut` idempotente sem chave nenhuma.
    opt_out: { para: null, rejeitada: false, fonte: "01§10.2 tabela" },
    sem_humano_24h: { para: null, rejeitada: true, fonte: "invariante" },
    cliente_reactivou: { para: "bot", rejeitada: false, fonte: "01§10.2 tabela" },
  },
};

/**
 * `true` quando o dono esteve calado o suficiente para o cliente devolver a
 * palavra ao bot.
 *
 * **Sem actividade humana registada, o silêncio conta como expirado.** Uma
 * conversa em `dono` sem `last_human_activity_at` só pode vir de uma escrita que
 * não passou por esta máquina (a máquina escreve-o sempre que põe `dono`), e
 * nesse caso não há instante a partir do qual contar. Expirar é a leitura que
 * devolve a palavra ao assistente em vez de a deixar presa para sempre num modo
 * que ninguém sabe quando começou — e o pior que acontece é o bot voltar a
 * responder a um cliente que escreveu, que é o estado normal.
 */
export function silencioExpirou(estado: EstadoDaConversa, agora: Date): boolean {
  if (estado.ultimaActividadeHumana === null) return true;
  return agora.getTime() - estado.ultimaActividadeHumana.getTime() >= SILENCIO_DO_DONO_MS;
}

/**
 * O que a tabela responde a um gatilho sobre uma conversa, neste instante.
 *
 * Nunca lança: um gatilho que não faça sentido é `rejeitada`, não um erro. Quem
 * dispara gatilhos é um *webhook* ou um *job*, e um erro aqui transformava uma
 * mensagem normal numa falha de processamento que o BullMQ repetiria sete dias
 * sobre um corpo que nunca vai melhorar — a lição que o `MOTIVOS_DO_CHR` do
 * KAM-014 já escreveu.
 */
export function transitar(
  estado: EstadoDaConversa,
  gatilho: Gatilho,
  agora: Date,
): Resposta {
  const celula = TABELA[estado.mode][gatilho];
  if (celula.rejeitada) return { tipo: "rejeitada" };
  if (celula.para === null) return { tipo: "sem_efeito" };
  if (celula.condicao === "silencio_do_dono" && !silencioExpirou(estado, agora)) {
    // O dono falou há pouco: a conversa continua dele. Não é rejeição — o
    // gatilho é legítimo, só não é a hora.
    return { tipo: "sem_efeito" };
  }
  // **Não há aqui um `if (celula.para === estado.mode)`, e a ausência é
  // deliberada.** A tentação é obvia — «uma célula que aponte para o modo em
  // que já se está é sem efeito e não uma transição» — e a primeira versão
  // tinha-a. Mas **nenhuma célula da tabela aponta para o próprio modo**: o
  // «não acontece nada» escreve-se `para: null`, e o `opt_out` repetido é
  // idempotente por a célula `pausada + opt_out` ser `para: null`, não por uma
  // comparação aqui. O ramo era inalcançável, e a prova por mutação mostrou-o:
  // apagá-lo não fazia nenhum teste falhar.
  //
  // O invariante não desapareceu — passou a ser **afirmado** em vez de
  // defendido: `tests/modos.transicoes.test.ts` tem «nenhuma celula aponta para
  // o proprio modo», e é esse teste que impede uma célula assim de entrar. Uma
  // guarda inalcançável dá a ilusão de proteger e não protege nada; o teste
  // falha no PR que a introduzir.
  return { tipo: "transita", para: celula.para };
}

/**
 * Os modos de onde esta transição pode sair, para o predicado do `UPDATE`.
 *
 * É o espelho exacto do `#deOndeSePodeSair` do `outbound/adapter.ts`, e existe
 * pela mesma razão que lá: **a exclusão mútua é da base e não deste código**. O
 * `UPDATE` leva `AND mode = ANY($4)` com o que esta função devolve, e dois
 * processos a disparar o mesmo gatilho ao mesmo tempo resolvem-se pelo «zero
 * linhas» de quem perde — não por quem leu primeiro.
 *
 * **Não é «todos os modos menos o destino».** Só os modos cuja célula para este
 * gatilho aponta para `para`: um `opt_out` concorrente com um `handoff_pedido`
 * não deve poder aplicar-se sobre o resultado do outro, e com uma lista larga
 * aplicava-se.
 *
 * A condição do silêncio **não** entra no predicado, e isso fica dito: ela
 * compara-se com o `last_human_activity_at` que a leitura trouxe, e repeti-la em
 * SQL era uma segunda implementação da mesma regra. A consequência é a janela
 * entre a leitura e a escrita, que o *lock* da conversa fecha — e é por isso que
 * o *lock* não é decoração nesta função.
 */
export function origensDe(gatilho: Gatilho, para: Modo): readonly Modo[] {
  // **Sem `de !== para`**, e pela mesma razão do ramo que saiu do `transitar`:
  // nenhuma célula aponta para o próprio modo, pelo que o filtro era
  // inalcançável — a prova por mutação apagou-o e nenhum teste falhou. O
  // invariante é afirmado por «nenhuma celula aponta para o proprio modo».
  return MODOS.filter((de) => TABELA[de][gatilho].para === para);
}

/** Os pares (modo, gatilho) que transitam, para o teste e para a documentação. */
export function celulasQueTransitam(): readonly {
  readonly de: Modo;
  readonly gatilho: Gatilho;
  readonly para: Modo;
  readonly fonte: Celula["fonte"];
}[] {
  const saida: { de: Modo; gatilho: Gatilho; para: Modo; fonte: Celula["fonte"] }[] = [];
  for (const de of MODOS) {
    for (const gatilho of GATILHOS) {
      const celula = TABELA[de][gatilho];
      if (celula.para !== null && celula.para !== de && !celula.rejeitada) {
        saida.push({ de, gatilho, para: celula.para, fonte: celula.fonte });
      }
    }
  }
  return saida;
}
