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
  ACCOES_POR_RECURSO,
  AccaoIncoerenteError,
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
 * A acção declara um tipo que pertence ao recurso? Pura.
 *
 * Separada do `permitida` porque mede outra coisa: o `permitida` responde «esta
 * acção é admissível?» e isto responde «esta acção é **coerente**?». Um
 * `{tipo: "apagar", recurso: "inbox"}` é admissível (a *inbox* não é do
 * cliente) e **incoerente** (o que se faz a uma *inbox* é desactivá-la), e sem
 * esta pergunta o executor despachava pelo recurso e chamava `desligar`: a
 * compensação fazia uma coisa e declarava outra.
 */
export function coerente(accao: AccaoDeCompensacao): boolean {
  return (ACCOES_POR_RECURSO[accao.recurso] ?? []).includes(accao.tipo);
}

/**
 * Avalia e levanta. O ponto por onde **toda** a compensação passa.
 *
 * As duas perguntas por esta ordem: primeiro a propriedade de negócio (o
 * recurso é do cliente?), depois a coerência. A ordem importa para a mensagem
 * de erro — um `{apagar, phone_number}` é as duas coisas, e o que se quer ler é
 * «é um recurso do cliente», que é a razão que manda.
 *
 * @throws {RecursoDoClienteError} o recurso é do cliente e o tipo é destrutivo
 * @throws {AccaoIncoerenteError} o tipo não pertence ao recurso
 */
export function verificar(accao: AccaoDeCompensacao, passo: Passo): void {
  if (!permitida(accao)) throw new RecursoDoClienteError(accao, passo);
  if (!coerente(accao)) throw new AccaoIncoerenteError(accao, passo);
}

/**
 * **A única acção que a compensação faz sobre um recurso do cliente**: cancelar
 * a subscrição de webhooks do WABA.
 *
 * Eram duas, e a segunda estava errada. O critério 7 diz «só cancela a
 * subscrição de webhooks **e remove a rota**», e a rota é **nossa** — é a linha
 * de `platform.tenant_channels`, que o passo 7 desfaz como `rota_chr`. Declarar
 * `remover_rota` sobre o `phone_number` no passo 6, como a primeira versão
 * fazia, removia a rota **duas vezes** por dois nomes e contava-a a dobrar na
 * métrica. Medido pela revisão adversarial: `rotasRemovidas` saía com o número
 * repetido.
 *
 * Com uma só, o `phone_number` deixa de aparecer em acção nenhuma — e o
 * `ACCOES_POR_RECURSO` dá-lhe lista vazia, pelo que qualquer acção sobre o
 * número do cliente é incoerente **e** recusada. É a forma mais forte de dizer
 * o critério 7: não há operação legítima sobre o número.
 *
 * Está aqui e não no `passos.ts` para que o ensaio possa afirmar sobre a lista
 * sem montar a saga — e há um ensaio a confirmar que o passo 6 a **chama**, sem
 * o qual esta função era código morto com um ensaio a medi-lo.
 */
export function accoesDoCanalDoCliente(wabaId: string): readonly AccaoDeCompensacao[] {
  return [{ tipo: "cancelar_subscricao", recurso: "waba", ref: wabaId }];
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
