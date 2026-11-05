/**
 * O guarda da compensação: o WABA e o número do cliente nunca se apagam
 * (KAM-091, critério 7; evidência E1).
 *
 * ## Porque é que isto é código e não um comentário
 *
 * O critério 7 diz «a compensação **nunca** apaga o WABA nem o número do
 * cliente (são dele; E1): só cancela a subscrição de webhooks e remove a rota».
 * Isso é uma **propriedade de negócio**: a PME autenticou-se na Meta, o WABA e o
 * número ficam dela, e se a saga falhar a meio ela não pode perder o seu número
 * por causa de uma limpeza nossa.
 *
 * Uma propriedade de negócio não se guarda com uma convenção. Três formas de a
 * guardar, e porque só a terceira serve:
 *
 * 1. **Um comentário** a dizer «não apagar o número». Não falha nada.
 * 2. **O tipo**: uma porta sem `apagarNumero`. Falha em compilação — mas só até
 *    alguém acrescentar o método, ou chamar outra porta, ou usar um `fetch`
 *    directo. E o ticket pede um ensaio que *fique vermelho* se alguém puser lá
 *    um `DELETE`: um método que não existe não se pode escrever, logo o ensaio
 *    nunca vê o erro que devia apanhar.
 * 3. **Um guarda em execução** sobre uma declaração. A compensação **declara**
 *    `{tipo, recurso, ref}` e este módulo avalia a declaração antes de a
 *    executar. Um `{tipo: "apagar", recurso: "phone_number"}` escrito hoje ou
 *    num ticket de 2027 levanta `RecursoDoClienteError`.
 *
 * É a 3 que está aqui, e a `CanalDoCliente` tem de propósito os métodos
 * destrutivos (`apagarWaba`, `apagarNumero`) **para que o erro seja
 * escrevível** — sem eles o ensaio do critério 7 provava só que não se pode
 * chamar o que não existe.
 *
 * ## O canário tem o caminho legítimo ao lado
 *
 * Um ensaio que só mostre a recusa não prova nada: uma função que recusasse
 * **tudo** passava-o. Por isso o `executar` abaixo é o mesmo caminho para os
 * dois casos, e o `tests/provisioning.cliente.test.ts` mede os dois lados na
 * mesma montagem — a compensação do passo 6 faz as suas duas acções
 * legítimas **e** uma acção proibida é recusada, com o contador do duplo a
 * confirmar que `apagarNumero` teve zero chamadas em ambos.
 */

import {
  RECURSOS_DO_CLIENTE,
  RecursoDoClienteError,
  TIPOS_DESTRUTIVOS,
  type AccaoDeCompensacao,
  type CanalDoCliente,
  type Passo,
} from "./contrato.ts";

/**
 * A acção é permitida? Pura, para poder ser medida sozinha.
 *
 * Proibida é a conjunção de duas coisas: o recurso é do cliente **e** o tipo é
 * destrutivo. Nenhuma das duas sozinha decide — `cancelar_subscricao` sobre o
 * `waba` é permitido (é o que o critério manda fazer) e `revogar` sobre a
 * `chave_llm` também (a chave é nossa).
 */
export function permitida(accao: AccaoDeCompensacao): boolean {
  const doCliente = RECURSOS_DO_CLIENTE.includes(accao.recurso);
  const destrutiva = TIPOS_DESTRUTIVOS.includes(accao.tipo);
  return !(doCliente && destrutiva);
}

/**
 * Avalia e levanta. O ponto por onde **toda** a compensação passa.
 *
 * @throws {RecursoDoClienteError}
 */
export function verificar(accao: AccaoDeCompensacao, passo: Passo): void {
  if (!permitida(accao)) throw new RecursoDoClienteError(accao, passo);
}

/**
 * As duas acções legítimas da compensação do passo 6, pela ordem do critério 7.
 *
 * Está aqui e não no `passos.ts` para que o ensaio do critério 7 possa afirmar
 * sobre a **lista** — «são estas duas e mais nenhuma» — sem montar a saga
 * inteira. Uma terceira acção acrescentada a esta lista tem de ser deliberada.
 */
export function accoesDoCanalDoCliente(
  wabaId: string,
  phoneNumberId: string,
): readonly AccaoDeCompensacao[] {
  return [
    { tipo: "cancelar_subscricao", recurso: "waba", ref: wabaId },
    { tipo: "remover_rota", recurso: "phone_number", ref: phoneNumberId },
  ];
}

/**
 * Executa uma acção sobre o canal do cliente, depois de a verificar.
 *
 * O `switch` é exaustivo sobre os tipos que o canal do cliente aceita, e os
 * destrutivos **caem no `default` que levanta** — e não por omissão: eles já
 * foram recusados pelo `verificar` acima, e este `default` é a segunda
 * fechadura, para o caso de alguém mudar o `TIPOS_DESTRUTIVOS` e não este
 * ficheiro. Duas fechaduras numa propriedade que não tem segunda chance.
 */
export async function executarNoCanalDoCliente(
  canal: CanalDoCliente,
  accao: AccaoDeCompensacao,
  passo: Passo,
): Promise<void> {
  verificar(accao, passo);
  switch (accao.tipo) {
    case "cancelar_subscricao":
      await canal.cancelarSubscricao(accao.ref);
      return;
    case "remover_rota":
      await canal.removerRota(accao.ref);
      return;
    default:
      throw new RecursoDoClienteError(accao, passo);
  }
}
