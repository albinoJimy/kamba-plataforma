/**
 * A correspondência entre os desfechos do `close` e os estados da tabela.
 *
 * **Existe porque dois documentos usam vocabulários diferentes para a mesma
 * coisa, e ninguém os tinha ligado.** A assinatura do `docs/tecnica/01` §11.1
 * dá ao `close` um `outcome ∈ {resolved, timeout, cancelled}`; a tabela que o
 * bloco do KAM-019 manda criar tem `status ∈ {waiting, resumed, timeout,
 * cancelled, degraded}`. O `resolved` não é um estado e o `resumed` não é um
 * desfecho, e sem este ficheiro o `close('resolved')` não sabia o que gravar.
 *
 * A emenda 1.22 do dicionário fixou o mapeamento; aqui está em código, e o
 * teste confronta os dois sentidos para que não divirjam.
 */

import {
  ESTADOS,
  OUTCOMES,
  type EstadoDeHandoff,
  type Outcome,
} from "./contrato.ts";

/**
 * Desfecho → estado que fica na linha.
 *
 * `resolved` dá `resumed`, e é a única das três que muda de nome: as outras
 * duas chamam-se igual nos dois vocabulários. É precisamente por serem duas
 * iguais e uma diferente que a tradução tinha de ser explícita — um `as`
 * funcionava em dois casos e mentia no terceiro.
 */
export const ESTADO_POR_OUTCOME: Readonly<Record<Outcome, EstadoDeHandoff>> = {
  resolved: "resumed",
  timeout: "timeout",
  cancelled: "cancelled",
};

/**
 * Os estados que **não** são desfecho de um `close`.
 *
 * `waiting` é onde uma passagem nasce e `degraded` é onde fica quando o
 * provedor não respondeu: nenhum dos dois é uma conclusão, e por isso nenhum
 * `close` os pode escrever. Está aqui como lista para que o teste possa
 * afirmar a partição — os cinco estados são exactamente estes dois mais os
 * três do mapeamento, e um estado novo que apareça obriga a decidir de que
 * lado fica.
 */
export const ESTADOS_SEM_OUTCOME: readonly EstadoDeHandoff[] = [
  "waiting",
  "degraded",
];

/**
 * Os estados de que um `close` **deste lado** pode sair. Um só: `degraded`.
 *
 * **Era `["waiting", "degraded"]`, e essa lista matava uma conversa por
 * passagem resolvida.** O `waiting` sai pela emenda **1.42** do dicionário
 * (§3.32), que decide a fronteira que a 1.41 deixou aberta, e a razão não é de
 * arrumação — está medida na `docs/analises/ANALISE-35`, achado 1:
 *
 * a `platform.handoffs` tinha **dois** escritores para a saída de `waiting`, e
 * o deste lado corria primeiro. Um colega marcava a conversa como resolvida, o
 * `#fechar` escrevia `resumed`, e o *compare-and-set* do AGR — que é o gatilho
 * do `Command(resume=…)` — não casava linha nenhuma e respondia 200 `repetido`,
 * o *no-op* do §11.5 aplicado ao **pedido legítimo**. O `interrupt()` do
 * `handoff_wait` ficava pendente para sempre, a varredura dos prazos não o
 * encontrava (filtra `waiting`) e a invariante da não-reentrada abria-se. Não
 * era uma intercalação rara: era o caminho feliz, todas as vezes.
 *
 * **E tira-se `waiting` para as três saídas e não só para o `resolved`.** As
 * três retomam o grafo — a rota de retoma com `resolved` e `cancelled`, a
 * varredura dos prazos com `timeout` —, pelo que sair de `waiting` por qualquer
 * delas matava um `Command` da mesma maneira. O que fica é uma partição que se
 * pode dizer em duas frases e confrontar com o código: **o HND nunca tira uma
 * passagem de `waiting`; o AGR nunca tira uma de `degraded`.** Uma passagem
 * `degraded` nem chegou ao provedor, pelo que não tem resposta humana para
 * retomar, e o predicado do CAS (`AND h.status = 'waiting'`) recusa-a.
 *
 * O predicado continua a ir no `WHERE status = ANY(...)` do `SQL_FECHAR`, e a
 * técnica é a mesma de antes — quem decide é a base, porque dois *webhooks*
 * duplicados chegam a dois processos. O que mudou é **qual** a transição que
 * este lado reclama.
 */
export const ESTADOS_QUE_FECHAM: readonly EstadoDeHandoff[] = ["degraded"];

/** O estado que um desfecho escreve. */
export function estadoDe(outcome: Outcome): EstadoDeHandoff {
  return ESTADO_POR_OUTCOME[outcome];
}

/**
 * `true` quando o estado é uma conclusão.
 *
 * Usa-se para não voltar a chamar o provedor por uma passagem já fechada.
 */
export function concluido(estado: string): boolean {
  return (
    estado !== "waiting" && estado !== "degraded" && (ESTADOS as readonly string[]).includes(estado)
  );
}

/**
 * O estado do provedor traduzido para desfecho, ou `null`.
 *
 * O provedor tem o seu próprio vocabulário de estados de conversa
 * (`open|resolved|pending|snoozed`, `docs/tecnica/01` §11.3) e só um deles é
 * uma conclusão para nós. Os outros três **não** são desfechos e devolvem
 * `null`: um `snoozed` no provedor não fecha a passagem, e tratá-lo como
 * fecho era deixar o cliente sem resposta por uma soneca do agente.
 */
export function outcomeDoProvedor(estado: string): Outcome | null {
  return estado === "resolved" ? "resolved" : null;
}

/** Os desfechos, para quem precise de iterar sem importar o contrato. */
export { OUTCOMES };
