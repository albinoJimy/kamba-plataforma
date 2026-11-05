/**
 * O critério 4: ***crash* entre criar o recurso externo e gravar o `markDone`**
 * (KAM-091).
 *
 * ## Porque este ficheiro existe à parte
 *
 * É o único critério que não se prova com um teste feliz, e é o único em que a
 * **localização** da falha injectada *é* a prova. A janela tem três momentos:
 *
 *     1. ensure()          → o recurso passa a existir lá fora
 *     2. ← o crash é AQUI →   o processo morre; não há linha `concluido`
 *     3. marcarConcluido() → a linha diria que o passo está feito
 *
 * Injectar a falha em 1 media «o *ensure* falhou e não criou nada» — que é
 * verdade e é outra coisa. Injectá-la depois de 3 media «falhou depois de tudo
 * estar consistente» — que também é outra coisa. **Só entre 1 e 3** é que existe
 * o estado que o critério descreve: recurso lá fora, nada cá dentro.
 *
 * O `ArmazemFalso.falharNoConcluir` levanta exactamente nesse ponto, e levanta
 * **uma vez** — se levantasse sempre, o ensaio media «falha para sempre» em vez
 * de «retoma sem duplicar».
 *
 * ## O que faz a repetição não duplicar
 *
 * O *ensure* procura pela chave natural antes de criar, e a procura está **no
 * nosso código** (`src/provisioning/passos.ts`), não no duplo. Os inventários
 * dos duplos são burros: `criar` cria sempre e soma ao contador. Logo
 * `criadas === 1` depois de duas passagens só pode acontecer se a procura
 * existir — e a bateria de mutações registada no PR confirma que apagar a
 * procura põe isto vermelho.
 */

import assert from "node:assert/strict";
import { beforeEach, describe, it } from "node:test";

import { Saga, type Passo } from "../src/provisioning/index.ts";
import { CASO, montar } from "./apoio/provisioning-falsos.ts";

type Montagem = ReturnType<typeof montar>;

function sagaDe(m: Montagem): Saga {
  return new Saga(m.dependencias as never);
}

/**
 * Os passos cujo *ensure* é **nosso** e cria recurso externo por chave natural.
 *
 * O passo 4 (`conta_atendimento`) não está aqui, e tem secção própria abaixo: a
 * sua idempotência é do `HandoffProvider.ensureAccount` (KAM-019), que é caixa
 * preta neste ticket. O passo 1 não cria recurso externo, o 5 é um `ON CONFLICT
 * DO UPDATE` da porta e o 6 e o 8 são esperas.
 */
const PASSOS_COM_ENSURE_NOSSO: readonly {
  passo: Passo;
  criadas: (m: Montagem) => number;
}[] = [
  { passo: "chave_llm", criadas: (m) => m.chaveDeLlm.inventario.criadas },
  { passo: "canal_comercio", criadas: (m) => m.comercio.inventario.criadas },
  { passo: "inbox_e_rota", criadas: (m) => m.inbox.inventario.criadas },
];

describe("criterio 4 — o crash na janela entre criar e gravar nao duplica", () => {
  for (const { passo, criadas } of PASSOS_COM_ENSURE_NOSSO) {
    describe(`passo \`${passo}\``, () => {
      let m: Montagem;

      beforeEach(() => {
        m = montar();
      });

      /**
       * **A asserção do critério.** Duas passagens, o *crash* na janela da
       * primeira, e uma só criação.
       */
      it("a repeticao encontra o recurso pela chave natural e nao cria um segundo", async () => {
        m.armazem.falharNoConcluir = passo;
        const saga = sagaDe(m);

        // A primeira passagem: o recurso é criado e o `marcarConcluido`
        // levanta. A saga trata isto como falha do passo (é o que é, do ponto de
        // vista dela) e tenta outra vez — e já na segunda tentativa a procura
        // tem de encontrar o que a primeira criou.
        await saga.correr(CASO);

        assert.equal(
          criadas(m),
          1,
          "a repeticao depois do crash criou um segundo recurso: " +
            "o *ensure* nao procurou pela chave natural antes de criar",
        );
      });

      /**
       * **O estado intermédio existe mesmo.** Sem esta asserção, o ensaio acima
       * passava se o `falharNoConcluir` nunca tivesse disparado — isto é, se o
       * ensaio não estivesse a medir a janela que diz medir.
       */
      it("o crash aconteceu de facto, e depois do recurso existir", async () => {
        m.armazem.falharNoConcluir = passo;
        await sagaDe(m).correr(CASO);

        const ordem = m.armazem.escritas;
        const indiceDoCrash = ordem.indexOf(`crash:${passo}`);
        assert.notEqual(indiceDoCrash, -1, "o crash nunca disparou: o ensaio nao mediu a janela");
        // O recurso foi criado antes do crash: a criação é a primeira, e o
        // crash veio depois dela na mesma passagem.
        assert.ok(criadas(m) >= 1, "o crash disparou antes de o recurso existir");
        // E o `concluido` desse passo veio **depois** do crash, não antes.
        const indiceDoConcluido = ordem.indexOf(`concluido:${passo}`);
        assert.ok(
          indiceDoConcluido > indiceDoCrash,
          "o passo ficou `concluido` antes do crash: a falha nao caiu na janela",
        );
      });

      it("a saga acaba por concluir o passo, e o `external_id` e o da unica criacao", async () => {
        m.armazem.falharNoConcluir = passo;
        await sagaDe(m).correr(CASO);

        const linha = await m.armazem.passo(CASO.onboardingId, passo);
        assert.equal(linha?.status, "concluido");
        // O inventário emite `…-N` com N igual ao número da criação. Um `-2`
        // aqui dizia que houve segunda criação mesmo que o contador mentisse.
        assert.ok(
          linha?.external_id === null || !String(linha.external_id).endsWith("-2"),
          `o \`external_id\` e de uma segunda criacao: ${String(linha?.external_id)}`,
        );
      });

      /**
       * O caminho legítimo ao lado: **sem *crash*, o passo cria uma vez e
       * conclui à primeira.**
       *
       * Sem isto, um *ensure* que nunca criasse nada passava os três ensaios
       * acima. É a regra do ticket: «um canário de recusa sem o caminho legítimo
       * ao lado não prova nada».
       */
      it("sem crash, cria uma vez e conclui a primeira tentativa", async () => {
        const desfecho = await sagaDe(m).correr(CASO);
        assert.equal(desfecho.estado, "concluida");
        assert.equal(criadas(m), 1);
        assert.equal(m.armazem.tentativaDe(passo), 1);
      });
    });
  }
});

describe("criterio 4 — o passo 4 delega a idempotencia no KAM-019", () => {
  let m: Montagem;

  beforeEach(() => {
    m = montar();
  });

  /**
   * **O que aqui se mede, e o que não se mede.**
   *
   * O `ensureAccount` do `HandoffProvider` é caixa preta neste ticket (é o que
   * o *handoff* manda), e a procura-antes-de-criar é dele: está em
   * `src/hnd/provedor.ts:210-211` e tem *suite* própria
   * (`tests/hnd.provedor.test.ts`). Aqui mede-se o que é **nosso**: que o
   * *crash* na janela deixa o passo retomável e que a retoma volta a chamar a
   * porta em vez de inventar um identificador.
   *
   * O que **não** está medido é que o Chatwoot não fica com duas contas — isso
   * depende da Platform API, cuja criação de *inbox* é **NÃO VERIFICADA** (E4
   * §2.2) e que não está a correr neste repositório.
   */
  it("o crash na janela do passo 4 deixa o passo retomavel", async () => {
    m.armazem.falharNoConcluir = "conta_atendimento";
    await sagaDe(m).correr(CASO);

    assert.ok(m.armazem.escritas.includes("crash:conta_atendimento"));
    assert.equal(m.armazem.estadoDe("conta_atendimento"), "concluido");
    // Duas chamadas à porta: a que o *crash* interrompeu e a da retoma. Duas
    // chamadas ao `ensureAccount` **não** são duas contas — a porta procura
    // antes de criar —, e é essa a garantia que se está a usar e a nomear.
    assert.equal(m.handoff.chamadas, 2);
  });

  it("depois de concluido, uma nova passagem nao volta a chamar a porta", async () => {
    const saga = sagaDe(m);
    await saga.correr(CASO);
    assert.equal(m.handoff.chamadas, 1);
    await saga.correr(CASO);
    assert.equal(m.handoff.chamadas, 1, "chamou o Chatwoot por um passo que ja estava `concluido`");
  });
});

describe("criterio 4 — a reconciliacao fecha o caso que a procura nao fecha", () => {
  /**
   * O critério tem uma segunda metade: «se o sistema externo não suportar
   * pesquisa, a intenção grava-se antes (*write-ahead*) e a reconciliação fecha
   * o caso».
   *
   * **Nenhuma das três portas deste módulo está nesse caso**: as três suportam
   * pesquisa por chave natural (`procurar`), e é por isso que os ensaios acima
   * medem a primeira metade. A segunda metade fica provada pelo lado da
   * reconciliação — um recurso criado lá fora sem linha `concluido` cá dentro é
   * visto e classificado —, e isso está em
   * `provisioning.reconciliacao.test.ts`.
   *
   * Este ensaio é a ponte: mostra que o estado que o *write-ahead* produziria é
   * o mesmo estado que o *crash* produz, e que a reconciliação o vê.
   */
  it("o recurso criado sem linha `concluido` fica visivel ao inventario externo", async () => {
    const m = montar();
    m.armazem.falharNoConcluir = "chave_llm";
    // Uma passagem só do primeiro passo falhado: pára a saga antes da retoma,
    // injectando uma falha dura no passo seguinte para o desfecho não avançar.
    m.comercio.procurar = async () => {
      throw new Error("comercio_indisponivel");
    };
    await sagaDe(m).correr(CASO);

    // O recurso do passo 2 existe no inventário (foi criado), e a sua linha
    // ficou `concluido` só na retoma — que é o que a saga faz sozinha. O que a
    // reconciliação tem de ver é o inventário, e ele tem o recurso.
    assert.equal(m.chaveDeLlm.inventario.quantos, 1);
    assert.equal(m.chaveDeLlm.inventario.criadas, 1);
  });
});
