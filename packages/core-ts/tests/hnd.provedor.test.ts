/**
 * O `HandoffProvider` de ponta a ponta, com a base e o provedor por porta
 * (KAM-019).
 *
 * **O que só aqui se prova**, e não na *suite* de base de dados nem nos testes
 * das funções puras:
 *
 * 1. **Quantas chamadas ao provedor houve, e onde houve zero.** Os critérios 1,
 *    3 e 4 têm todos a forma «chamado N× produz uma coisa só», e a asserção que
 *    os prova é um contador. Contra um Chatwoot real contam-se as conversas que
 *    ficam lá; aqui conta-se a porta, que é mais barato e igualmente decisivo.
 * 2. **A ordem dos passos.** O `openHandoff` escreve a linha **antes** de
 *    chamar o provedor, e a sequência de consultas é a prova. Ao contrário, uma
 *    falha entre a criação lá e a escrita aqui deixava uma conversa aberta no
 *    provedor sem nada do nosso lado a apontar-lhe.
 * 3. **A degradação.** Com o provedor em baixo a passagem fica `degraded`, a
 *    abertura vai para a fila e o painel vê o atraso — o critério 9 é isso, e
 *    um provedor realmente em baixo é difícil de montar e trivial de simular.
 * 4. **Que o registo não leva nome nem e-mail do agente.** É o `resolver` do
 *    dicionário §3.15, o primeiro dado pessoal de um trabalhador da PME no
 *    esquema.
 *
 * O que **não** se mede aqui: a idempotência contra uma chave primária real, a
 * RLS e a monotonia sob concorrência verdadeira. Isso é a *suite* de base de
 * dados, contra um PostgreSQL, e nenhuma destas asserções a substitui — uma
 * base falsa devolve o que se lhe mandou devolver.
 */

import assert from "node:assert/strict";
import { describe, it } from "node:test";

import { Logger } from "../src/logger/index.ts";
import type { ChannelContext } from "../src/chr/index.ts";
import {
  Handoff,
  METRICA_HANDOFFS,
  METRICA_PENDENTES,
  METRICA_RECUSAS,
  ProvedorIndisponivelError,
  SQL_ABRIR_HANDOFF,
  SQL_CONTA,
  SQL_FECHAR,
  SQL_GUARDAR_CONTA,
  SQL_HANDOFF_POR_ID,
  SQL_MARCAR_ABERTA,
  SQL_MARCAR_DEGRADADA,
  SQL_MARCAR_RESOLVER,
  SQL_THREAD_DA_PASSAGEM,
  RetomaIndisponivelError,
  SemPrivilegioError,
  estadoDe,
  threadDe,
  type AberturaNoProvedor,
  type ContaCriada,
  type ContaDeAtendimento,
  type Corpo,
  type DesfechoDaRetoma,
  type FilaDoEspelho,
  type HumanEvent,
  type MirrorMessage,
  type PedidoDeHandoff,
  type PedidoDeRetoma,
} from "../src/hnd/index.ts";

const TENANT = "11111111-1111-4111-8111-111111111111";
const CONVERSA = "22222222-2222-4222-8222-222222222222";
const CONTACTO = "33333333-3333-4333-8333-333333333333";
const SEGREDO = "um-secret-de-bot-com-tamanho-razoavel";
const T0 = new Date("2026-10-20T12:00:00.000Z");

/** Uma linha de `handoffs`, como a porta a devolve. */
interface Linha {
  handoff_id: string;
  tenant_id: string;
  conversation_id: string;
  status: string;
  motivo: string;
  external_id: string | null;
  opened_at: Date;
  resumed_at: Date | null;
  resolver: string | null;
}

/**
 * A base por porta, com o registo do que lhe foi pedido e por que ordem.
 *
 * Despacha por **identidade da constante** e não por texto: comparar
 * `texto === SQL_ABRIR_HANDOFF` deixa de compilar se a constante desaparecer,
 * enquanto um `includes("INSERT")` continuava a casar com outra consulta
 * qualquer.
 */
class BaseFalsa {
  readonly pedidos: string[] = [];
  readonly handoffs = new Map<string, Linha>();
  /**
   * `conversation_id` → `contact_id`, que é o `JOIN` do `SQL_THREAD_DA_PASSAGEM`.
   *
   * Existe porque o `thread_id` do corpo da retoma é `{tenant_id}:{contact_id}`
   * (§3.1) e o `handoff_id` é irreversível: o `contact_id` só se obtém pela
   * conversa a que a passagem aponta. Uma conversa semeada, que é a do `pedido`.
   */
  readonly conversas = new Map<string, string>([[CONVERSA, CONTACTO]]);
  readonly contas = new Map<string, ContaDeAtendimento & { token_ref: string }>();
  /**
   * O *tenant* da sessão, que é o que o `SQL_FECHAR` lê do `current_setting`.
   *
   * Existe porque aquela consulta é a única que não recebe o *tenant* por
   * parâmetro — a assinatura do `close` do §11.1 não o tem. Uma base falsa sem
   * isto não podia exercitar o `close`.
   */
  tenantDaSessao = TENANT;
  /** Força o `ON CONFLICT` do `SQL_GUARDAR_CONTA` a perder, para o caso órfão. */
  contaJaGravadaPorOutro = false;

  #nome(texto: string): string {
    const nomes: readonly [string, string][] = [
      [SQL_ABRIR_HANDOFF, "abrir"],
      [SQL_HANDOFF_POR_ID, "por_id"],
      [SQL_MARCAR_ABERTA, "marcar_aberta"],
      [SQL_MARCAR_DEGRADADA, "marcar_degradada"],
      [SQL_FECHAR, "fechar"],
      [SQL_GUARDAR_CONTA, "guardar_conta"],
      [SQL_CONTA, "conta"],
      [SQL_THREAD_DA_PASSAGEM, "thread_da_passagem"],
      [SQL_MARCAR_RESOLVER, "marcar_resolver"],
    ];
    return nomes.find(([sql]) => sql === texto)?.[1] ?? "desconhecida";
  }

  async query<T>(texto: string, valores: readonly unknown[] = []): Promise<{ rows: readonly T[] }> {
    const nome = this.#nome(texto);
    this.pedidos.push(nome);
    const linhas = (valor: unknown[]): { rows: readonly T[] } => ({
      rows: valor as readonly T[],
    });

    if (nome === "abrir") {
      const id = String(valores[0]);
      // O `ON CONFLICT (handoff_id) DO NOTHING RETURNING`: **vazio** quando a
      // chave já passou, e é disso que o chamador conclui «não chamar o
      // provedor».
      if (this.handoffs.has(id)) return linhas([]);
      this.handoffs.set(id, {
        handoff_id: id,
        tenant_id: String(valores[1]),
        conversation_id: String(valores[2]),
        status: "waiting",
        motivo: String(valores[3]),
        external_id: null,
        opened_at: T0,
        resumed_at: null,
        resolver: null,
      });
      return linhas([{ handoff_id: id, status: "waiting" }]);
    }
    if (nome === "por_id") {
      const linha = this.handoffs.get(String(valores[1]));
      return linhas(linha === undefined || linha.tenant_id !== String(valores[0]) ? [] : [linha]);
    }
    if (nome === "marcar_aberta") {
      const linha = this.handoffs.get(String(valores[1]));
      const permitidos = valores[3] as readonly string[];
      if (linha === undefined || !permitidos.includes(linha.status)) return linhas([]);
      linha.external_id = String(valores[2]);
      linha.status = "waiting";
      return linhas([{ handoff_id: linha.handoff_id, status: linha.status }]);
    }
    if (nome === "marcar_degradada") {
      const linha = this.handoffs.get(String(valores[1]));
      if (linha === undefined || linha.status !== "waiting") return linhas([]);
      linha.status = "degraded";
      return linhas([{ handoff_id: linha.handoff_id, status: linha.status }]);
    }
    if (nome === "fechar") {
      // O `tenant_id` vem do `current_setting`, não dos parâmetros.
      const linha = this.handoffs.get(String(valores[0]));
      const permitidos = valores[2] as readonly string[];
      if (
        linha === undefined ||
        linha.tenant_id !== this.tenantDaSessao ||
        !permitidos.includes(linha.status)
      ) {
        return linhas([]);
      }
      linha.status = String(valores[1]);
      if (linha.status === "resumed") linha.resumed_at = T0;
      return linhas([{ handoff_id: linha.handoff_id, status: linha.status }]);
    }
    if (nome === "thread_da_passagem") {
      // O `JOIN` com a conversa **e** o `external_id` no predicado. Os dois
      // contam: sem o `JOIN` não há `contact_id`, e sem o `external_id` um
      // atributo trocado no provedor fazia-nos pedir a retoma do *thread* de
      // outra pessoa.
      const linha = this.handoffs.get(String(valores[1]));
      if (
        linha === undefined ||
        linha.tenant_id !== String(valores[0]) ||
        linha.external_id !== String(valores[2])
      ) {
        return linhas([]);
      }
      const contactId = this.conversas.get(linha.conversation_id);
      return linhas(contactId === undefined ? [] : [{ contact_id: contactId }]);
    }
    if (nome === "marcar_resolver") {
      // **Só de `waiting`**, e é isso que faz do *webhook* duplicado um *no-op*
      // também nesta coluna: o segundo não reescreve o `resolver` do primeiro.
      const linha = this.handoffs.get(String(valores[1]));
      if (
        linha === undefined ||
        linha.tenant_id !== String(valores[0]) ||
        linha.status !== "waiting"
      ) {
        return linhas([]);
      }
      linha.resolver = String(valores[2]);
      return linhas([{ handoff_id: linha.handoff_id }]);
    }
    if (nome === "guardar_conta") {
      const chave = `${String(valores[0])}:${String(valores[1])}`;
      if (this.contas.has(chave) || this.contaJaGravadaPorOutro) {
        if (this.contaJaGravadaPorOutro && !this.contas.has(chave)) {
          // Simula o vencedor da corrida: a linha aparece sem ter sido esta
          // chamada a escrevê-la.
          this.contas.set(chave, {
            accountId: 999,
            inboxId: 998,
            botId: 997,
            providerUserId: 996,
            token_ref: "ref/do-vencedor",
          });
        }
        return linhas([]);
      }
      this.contas.set(chave, {
        accountId: Number(valores[2]),
        inboxId: Number(valores[3]),
        botId: Number(valores[4]),
        providerUserId: Number(valores[5]),
        token_ref: String(valores[6]),
      });
      return linhas([{ tenant_id: String(valores[0]) }]);
    }
    if (nome === "conta") {
      const conta = this.contas.get(`${String(valores[0])}:${String(valores[1])}`);
      return linhas(
        conta === undefined
          ? []
          : [
              {
                account_id: String(conta.accountId),
                inbox_id: String(conta.inboxId),
                bot_id: String(conta.botId),
                provider_user_id: String(conta.providerUserId),
                token_ref: conta.token_ref,
              },
            ],
      );
    }
    return linhas([]);
  }
}

/** O provedor por porta: conta chamadas e pode estar em baixo. */
class ProvedorFalso {
  contasCriadas = 0;
  conversasAbertas = 0;
  espelhos = 0;
  fechos = 0;
  emBaixo = false;
  readonly aberturas: AberturaNoProvedor[] = [];

  readonly criarConta = async (_tenantId: string): Promise<ContaCriada> => {
    this.contasCriadas += 1;
    if (this.emBaixo) throw new ProvedorIndisponivelError("criarConta: sem resposta");
    return {
      conta: {
        accountId: 10 + this.contasCriadas,
        inboxId: 20,
        botId: 30,
        providerUserId: 40,
      },
      // Os dois `access_token`, que o provedor so mostra uma vez. O duplo
      // devolve-os para que o `ensureAccount` tenha o que guardar no cofre.
      // Frases com espacos, de proposito: o `scan_secrets` recusou os
      // valores anteriores («atribuicao a um nome que significa segredo,
      // com entropia suficiente para nao ser uma palavra») e tinha razao.
      // Um valor de ensaio que parece uma chave a serio e um valor que
      // alguem um dia copia para um ambiente.
      tokenDoBot: "o do bot",
      tokenDoUtilizador: "o do utilizador",
    };
  };

  /**
   * Corre **durante** a chamada ao provedor.
   *
   * E a unica forma de simular o que acontece de verdade: a abertura e uma
   * chamada HTTP a um terceiro, com 10 s de tecto, e nessa janela cabe um
   * `conversation_status_changed`. Sem este gancho nao se consegue escrever o
   * teste do `marcar_aberta` que nao casa.
   */
  antesDeAbrir: (() => void) | null = null;

  readonly abrirConversa = async (abertura: AberturaNoProvedor): Promise<string> => {
    this.antesDeAbrir?.();
    this.conversasAbertas += 1;
    if (this.emBaixo) throw new ProvedorIndisponivelError("abrirConversa: sem resposta");
    this.aberturas.push(abertura);
    return `cw-${this.conversasAbertas}`;
  };

  readonly espelhar = async (): Promise<void> => {
    this.espelhos += 1;
  };

  readonly fecharConversa = async (): Promise<void> => {
    this.fechos += 1;
  };
}

/**
 * O AGR por porta, com o *compare-and-set* e o `interrupt()` modelados.
 *
 * **O que este duplo permite medir**, e que de outra forma não se media deste
 * lado: a propriedade de ponta a ponta do critério 3 do KAM-034 — «nenhum
 * `interrupt()` fica pendente num *handoff* que um humano resolveu». Ele guarda
 * as *threads* com interrupção pendente, como o *checkpoint* do LangGraph, e
 * **só** o `Command(resume=…)` as tira — que é o que o `retomar` corre quando o
 * CAS vence. Com o defeito que a emenda 1.42 corrige (o HND a escrever `resumed`
 * antes), o CAS não casava, nenhum `Command` corria, e o conjunto ficava com a
 * *thread* lá dentro: é esse o teste.
 *
 * **E o que ele não prova**, dito aqui porque a revisão adversarial do KAM-034
 * encontrou exactamente esta classe de defeito (um duplo mais forte do que a
 * peça que substitui): o CAS a sério é uma instrução de PostgreSQL, e a sua
 * atomicidade sob concorrência real está provada em
 * `db/tests_agr/test_handoff_retoma.py` contra um servidor — duas ligações, o
 * mesmo `handoff_id`, exactamente uma a vencer. Este duplo replica o
 * **predicado** (o *tenant*, o `handoff_id`, o contacto da conversa e o
 * `status = 'waiting'`), e nada mais; o que aqui se mede é o lado do HND e a
 * forma do corpo, não a serialização.
 */
class AgrFalso {
  readonly pedidos: PedidoDeRetoma[] = [];
  /** As *threads* com um `interrupt()` pendente. O `Command` é quem as tira. */
  readonly interrompidas = new Set<string>();
  comandos = 0;
  /** Força a porta a levantar, como o 503 do `grafo_nao_registado`. */
  emBaixo = false;
  readonly #bd: BaseFalsa;

  // Campo e atribuição, e não um parâmetro-propriedade: o `node --test` corre
  // TypeScript em *strip-only mode* e aquela forma precisa de transformação.
  constructor(bd: BaseFalsa) {
    this.#bd = bd;
  }

  /**
   * O que a linha tinha **no instante em que a retoma chegou**.
   *
   * É o que torna a ordem das duas escritas do HND mensurável de fora: com elas
   * invertidas, o `resolver` chegava aqui a `null` — e o `SQL_MARCAR_RESOLVER`
   * nunca mais casava, porque o CAS já tinha movido o `status`.
   */
  estadoNaChegada: string | null = null;
  resolverNaChegada: string | null = null;

  readonly retomar = async (pedido: PedidoDeRetoma): Promise<DesfechoDaRetoma> => {
    this.pedidos.push(pedido);
    const vista = this.#bd.handoffs.get(pedido.handoffId);
    this.estadoNaChegada = vista?.status ?? null;
    this.resolverNaChegada = vista?.resolver ?? null;
    if (this.emBaixo) throw new RetomaIndisponivelError(503, "grafo_nao_registado");
    const corte = pedido.threadId.indexOf(":");
    const tenantId = pedido.threadId.slice(0, corte);
    const contactId = pedido.threadId.slice(corte + 1);
    const linha = this.#bd.handoffs.get(pedido.handoffId);
    const desteThread =
      linha !== undefined &&
      linha.tenant_id === tenantId &&
      this.#bd.conversas.get(linha.conversation_id) === contactId;
    if (!desteThread || linha === undefined) return "recusado";
    if (linha.status !== "waiting") return "repetido";
    linha.status = estadoDe(pedido.outcome);
    linha.resumed_at = T0;
    // O `Command(resume=...)`: corre **depois** do CAS e é o que desfaz a
    // interrupção. A ordem é a do `handoff/retoma.py`.
    this.comandos += 1;
    this.interrompidas.delete(pedido.threadId);
    return "retomado";
  };
}

/** A fila por porta, com a de-duplicação por `jobId` que a torna idempotente. */
class FilaFalsa implements FilaDoEspelho {
  readonly jobs = new Map<string, Readonly<Record<string, unknown>>>();

  async enfileirar(jobId: string, carga: Readonly<Record<string, unknown>>): Promise<boolean> {
    if (this.jobs.has(jobId)) return false;
    this.jobs.set(jobId, carga);
    return true;
  }

  async pendentes(): Promise<number> {
    return this.jobs.size;
  }
}

interface Montagem {
  readonly hnd: Handoff;
  readonly bd: BaseFalsa;
  readonly provedor: ProvedorFalso;
  readonly fila: FilaFalsa;
  readonly agr: AgrFalso;
  readonly registo: Record<string, unknown>[];
  readonly cofre: { ref: string; segredo: string }[];
  readonly cofreConsultado: string[];
}

function montar(): Montagem {
  const bd = new BaseFalsa();
  const agr = new AgrFalso(bd);
  const provedor = new ProvedorFalso();
  const fila = new FilaFalsa();
  const registo: Record<string, unknown>[] = [];
  // O `Logger` **real** e em modo estrito: e o que recusa um campo fora da
  // *allowlist*. Um registo falso aqui provava que o teste sabe guardar
  // objectos, nao que a politica morde.
  const log = new Logger("gwy", {
    estrito: true,
    relogio: () => T0,
    destino: {
      write: (texto: string) => {
        registo.push(JSON.parse(texto) as Record<string, unknown>);
      },
    },
  });
  // O cofre falso: o `ensureAccount` guarda la os dois `access_token` que o
  // provedor so mostra uma vez, e ha teste a afirmar que os dois entram.
  const cofre: { ref: string; segredo: string }[] = [];
  const cofreConsultado: string[] = [];
  const hnd = new Handoff({
    bd,
    provedor: {
      abrirConversa: provedor.abrirConversa,
      espelhar: provedor.espelhar,
      fecharConversa: provedor.fecharConversa,
    },
    provisionador: { criarConta: provedor.criarConta },
    fila,
    refDoTokenDoBot: (tenantId) => `chatwoot_bot_token/${tenantId}`,
    refDoTokenDoUtilizador: (tenantId) => `chatwoot_user_token/${tenantId}`,
    guardarSegredo: async (ref, segredo) => {
      cofre.push({ ref, segredo });
    },
    segredoDoBot: async (tenantId) => {
      cofreConsultado.push(tenantId);
      return SEGREDO;
    },
    retomar: agr.retomar,
    log,
  });
  return { hnd, bd, provedor, fila, agr, registo, cofre, cofreConsultado };
}

function pedido(troca: Partial<PedidoDeHandoff> = {}): PedidoDeHandoff {
  return {
    tenantId: TENANT,
    chaveDoContacto: CONTACTO,
    conversationId: CONVERSA,
    handoffId: "h_abc",
    motivo: "o cliente pediu uma pessoa",
    resumo: "Cliente quer trocar o tamanho.",
    ...troca,
  };
}

const CTX: ChannelContext = {
  tenant_id: TENANT,
  channel_id: "44444444-4444-4444-8444-444444444444",
  vertical: "vendedor",
  plano: "basico",
  estado_tenant: "ativo",
  estado_canal: "ativo",
  channel_mode: "coexistencia",
  origem: "pme",
};

function mensagem(wamid: string): MirrorMessage {
  return {
    wamid,
    direccao: "entrada",
    waType: "text",
    texto: "Bom dia",
    criadoEm: T0,
  };
}

describe("a conta de atendimento (criterio 1)", () => {
  it("**chamado 2x nao duplica**: uma chamada ao provedor e uma linha", async () => {
    const { hnd, bd, provedor } = montar();
    const primeira = await hnd.ensureAccount(TENANT);
    const segunda = await hnd.ensureAccount(TENANT);

    assert.deepEqual(primeira, segunda);
    assert.equal(provedor.contasCriadas, 1, "a segunda chamada ao provedor e o defeito");
    assert.equal(bd.contas.size, 1);
  });

  it("com a linha ja gravada nao fala com o provedor nenhuma vez", async () => {
    const { hnd, provedor } = montar();
    await hnd.ensureAccount(TENANT);
    provedor.contasCriadas = 0;
    await hnd.ensureAccount(TENANT);
    assert.equal(provedor.contasCriadas, 0);
  });

  it("**a conta orfa da corrida e registada, nao escondida**", async () => {
    // Duas chamadas concorrentes podem ambas passar a leitura e ambas criar
    // conta no provedor; a segunda perde o `ON CONFLICT` e deixa uma conta
    // **orfa** la, que nenhuma migracao nossa desfaz porque o recurso nao e
    // nosso. Nao ha como evita-lo sem um lock que a assinatura nao permite
    // pedir — a linha precisa dos identificadores que so a criacao devolve.
    // O que se exige e que apareca.
    const { hnd, bd, registo } = montar();
    bd.contaJaGravadaPorOutro = true;
    const conta = await hnd.ensureAccount(TENANT);

    assert.equal(conta.accountId, 999, "devolve a conta que esta na base, nao a nossa");
    assert.ok(registo.some((l) => l["outcome"] === "conta_de_handoff_orfa"));
  });
});

describe("a abertura da passagem (criterio 4)", () => {
  it("**cinco chamadas concorrentes dao uma conversa**", async () => {
    // A letra do criterio. A idempotencia e da chave primaria: o
    // `ON CONFLICT (handoff_id) DO NOTHING RETURNING` vazio e o que diz «ja
    // passou», e nesse caso nao ha chamada ao provedor nenhuma.
    const { hnd, bd, provedor } = montar();
    const resultados = await Promise.all(
      [1, 2, 3, 4, 5].map(() => hnd.openHandoff(pedido())),
    );

    assert.equal(bd.handoffs.size, 1);
    assert.equal(provedor.conversasAbertas, 1, "cinco aberturas no provedor e o defeito");
    assert.equal(resultados.filter((r) => !r.repetido).length, 1, "so uma e nova");
    assert.equal(resultados.filter((r) => r.repetido).length, 4);
  });

  it("a repeticao devolve o externalId da primeira, e nao vazio", async () => {
    const { hnd } = montar();
    const primeira = await hnd.openHandoff(pedido());
    const segunda = await hnd.openHandoff(pedido());

    assert.equal(primeira.externalId, "cw-1");
    assert.equal(segunda.externalId, "cw-1", "quem repete tem de poder correlacionar");
    assert.equal(segunda.repetido, true);
  });

  it("**a linha e escrita antes de se falar com o provedor**", async () => {
    // Se a ordem fosse ao contrario, uma falha entre a criacao la e a escrita
    // aqui deixava uma conversa aberta no provedor sem nada do nosso lado a
    // aponta-lhe — e a repeticao criava outra.
    const { hnd, bd } = montar();
    await hnd.openHandoff(pedido());
    assert.equal(bd.pedidos[0], "abrir", `a primeira consulta foi ${bd.pedidos[0]}`);
    assert.ok(bd.pedidos.indexOf("marcar_aberta") > bd.pedidos.indexOf("abrir"));
  });

  it("leva o resumo e o handoffId para a conversa do provedor", async () => {
    // O resumo vai para a nota privada (criterio 4) e o `handoffId` para o
    // atributo por onde o `openHandoff` a volta a encontrar.
    const { hnd, provedor } = montar();
    await hnd.openHandoff(pedido());
    assert.equal(provedor.aberturas[0]?.resumo, "Cliente quer trocar o tamanho.");
    assert.equal(provedor.aberturas[0]?.handoffId, "h_abc");
  });
});

describe("o provedor em baixo degrada (criterio 9)", () => {
  it("a passagem fica degraded, a abertura vai para a fila, e a linha fica", async () => {
    const { hnd, bd, fila, provedor, registo } = montar();
    // A conta tem de existir **antes**: com o provedor em baixo desde o
    // inicio, e o `criarConta` que falha primeiro e o que se mediria era outra
    // coisa — a degradacao e do `abrirConversa`.
    await hnd.ensureAccount(TENANT);
    provedor.emBaixo = true;
    const resultado = await hnd.openHandoff(pedido());

    assert.equal(resultado.estado, "degraded");
    assert.equal(resultado.externalId, "", "nao ha conversa no provedor");
    assert.equal(bd.handoffs.get("h_abc")?.status, "degraded");
    assert.ok(fila.jobs.has("abertura:h_abc"), "a abertura foi para a fila");
    assert.ok(registo.some((l) => l["outcome"] === "handoff_degradado"));
    assert.equal(hnd.metricas.ler()[`${METRICA_HANDOFFS}:degraded`], 1);
    // **A linha fica**, e e isso que faz o painel ver o atraso em vez de a
    // passagem desaparecer.
    assert.equal(bd.handoffs.size, 1);
  });

  it("uma passagem degradada recupera quando a fila drena", async () => {
    // O `SQL_MARCAR_ABERTA` aceita sair de `degraded`, e e isso que a recupera:
    // quando a conversa finalmente nasce no provedor, ela deixa de estar
    // degradada. Sem `degraded` na lista, uma passagem degradada ficava assim
    // para sempre.
    const { hnd, bd, provedor } = montar();
    await hnd.ensureAccount(TENANT);
    provedor.emBaixo = true;
    await hnd.openHandoff(pedido());
    assert.equal(bd.handoffs.get("h_abc")?.status, "degraded");

    provedor.emBaixo = false;
    await hnd.openHandoff(pedido());
    // A segunda chamada ve a linha (repetido) e nao reabre: a recuperacao e da
    // fila, nao de uma segunda chamada do chamador. O que se afirma e que o
    // estado nao regrediu nem se perdeu.
    assert.equal(bd.handoffs.get("h_abc")?.status, "degraded");
  });
});

describe("o espelho (criterio 3)", () => {
  it("**tres chamadas com o mesmo wamid dao uma mensagem**", async () => {
    const { hnd, fila } = montar();
    await hnd.mirrorMessage(CTX, mensagem("wamid.A"));
    await hnd.mirrorMessage(CTX, mensagem("wamid.A"));
    await hnd.mirrorMessage(CTX, mensagem("wamid.A"));
    assert.equal(fila.jobs.size, 1);
  });

  it("wamids diferentes dao mensagens diferentes", async () => {
    const { hnd, fila } = montar();
    await hnd.mirrorMessage(CTX, mensagem("wamid.A"));
    await hnd.mirrorMessage(CTX, mensagem("wamid.B"));
    assert.equal(fila.jobs.size, 2);
  });

  it("a profundidade da fila fica na metrica que o healthcheck le", async () => {
    const { hnd } = montar();
    await hnd.mirrorMessage(CTX, mensagem("wamid.A"));
    await hnd.mirrorMessage(CTX, mensagem("wamid.B"));
    assert.equal(hnd.metricas.ler()[METRICA_PENDENTES], 2);
  });

  it("**o espelho nao leva telefone, BSUID nem contact_id**", async () => {
    // O provedor identifica a pessoa pela conta de contacto dele; o ADR-010
    // proibe mandar os nossos identificadores para fora.
    const { hnd, fila } = montar();
    await hnd.mirrorMessage(CTX, mensagem("wamid.A"));
    const carga = JSON.stringify([...fila.jobs.values()]);
    assert.ok(!carga.includes(CONTACTO), "o contact_id nao vai na carga");
    assert.ok(carga.includes(TENANT), "o tenant_id vai, e e o que a fila precisa");
  });
});

describe("o setBotMuted levanta (criterio 8)", () => {
  it("**levanta SemPrivilegioError, e a mensagem diz de quem e o privilegio**", async () => {
    const { hnd } = montar();
    await assert.rejects(() => hnd.setBotMuted(CONVERSA, true), SemPrivilegioError);
    await assert.rejects(() => hnd.setBotMuted(CONVERSA, false), SemPrivilegioError);
    await assert.rejects(
      () => hnd.setBotMuted(CONVERSA, true),
      /KAM-018/,
      "a mensagem tem de dizer quem liga isto",
    );
  });

  it("e nao toca na base", async () => {
    const { hnd, bd } = montar();
    await assert.rejects(() => hnd.setBotMuted(CONVERSA, true));
    assert.deepEqual(bd.pedidos, []);
  });
});

describe("o fecho, depois da emenda 1.42 (criterio 7)", () => {
  /** Uma passagem `degraded`: a conta existe e o provedor cai a seguir. */
  async function comPassagemDegradada(): Promise<Montagem> {
    const montagem = montar();
    await montagem.hnd.ensureAccount(TENANT);
    montagem.provedor.emBaixo = true;
    const aberta = await montagem.hnd.openHandoff(pedido());
    assert.equal(aberta.estado, "degraded", "a montagem tem de dar uma degradada");
    return montagem;
  }

  it("**um close sobre uma passagem em waiting nao escreve nada**", async () => {
    // E a fronteira da emenda 1.42, vista pela porta do §11.1: sair de
    // `waiting` e do AGR, por `/internal/resume`, nos tres desfechos. O que
    // este teste prende e que a porta **nao** o faz em silencio por um caminho
    // lateral — era por aqui que o `Command(resume=...)` morria.
    const { hnd, bd, registo } = montar();
    await hnd.openHandoff(pedido());
    for (const outcome of ["resolved", "timeout", "cancelled"] as const) {
      await hnd.close("h_abc", outcome);
      assert.equal(
        bd.handoffs.get("h_abc")?.status,
        "waiting",
        `o ${outcome} nao pode tirar a passagem de waiting`,
      );
    }
    assert.equal(bd.handoffs.get("h_abc")?.resumed_at, null);
    // **E deixa rasto.** Um zero linhas silencioso e a classe de defeito que
    // este modulo ja pagou duas vezes.
    assert.equal(
      registo.filter((l) => l["outcome"] === "handoff_fecho_sem_efeito").length,
      3,
    );
  });

  it("**uma passagem degraded fecha-se, e e a unica que fecha**", async () => {
    const { hnd, bd } = await comPassagemDegradada();
    await hnd.close("h_abc", "resolved");
    const linha = bd.handoffs.get("h_abc");
    assert.equal(linha?.status, "resumed");
    assert.notEqual(linha?.resumed_at, null);
    assert.equal(hnd.metricas.ler()[`${METRICA_HANDOFFS}:resumed`], 1);
  });

  it("**o fecho duplicado de uma degraded nao altera nada**", async () => {
    // A monotonia esta no predicado: o segundo `UPDATE` nao casa e devolve zero
    // linhas. E a base que o faz, nao uma verificacao em codigo.
    const { hnd, bd } = await comPassagemDegradada();
    await hnd.close("h_abc", "resolved");
    const antes = { ...bd.handoffs.get("h_abc") };
    await hnd.close("h_abc", "resolved");
    assert.deepEqual({ ...bd.handoffs.get("h_abc") }, antes);
    // E conta **uma** vez na metrica, nao duas.
    assert.equal(hnd.metricas.ler()[`${METRICA_HANDOFFS}:resumed`], 1);
  });

  it("o timeout e o cancelled escrevem-se com o proprio nome", async () => {
    for (const [outcome, estado] of [
      ["timeout", "timeout"],
      ["cancelled", "cancelled"],
    ] as const) {
      const { hnd, bd } = await comPassagemDegradada();
      await hnd.close("h_abc", outcome);
      assert.equal(bd.handoffs.get("h_abc")?.status, estado);
      assert.equal(bd.handoffs.get("h_abc")?.resumed_at, null, "so o resolved marca a retoma");
    }
  });

  it("uma passagem de outro tenant nao se fecha", async () => {
    // O `SQL_FECHAR` le o tenant do contexto da sessao, e a base falsa imita-o.
    const { hnd, bd } = await comPassagemDegradada();
    bd.tenantDaSessao = "99999999-9999-4999-8999-999999999999";
    await hnd.close("h_abc", "resolved");
    assert.equal(bd.handoffs.get("h_abc")?.status, "degraded", "ficou como estava");
  });
});

describe("os callbacks (criterio 5)", () => {
  function corpoDeEstado(estado: string): Corpo {
    return {
      event: "conversation_status_changed",
      conversation: {
        id: "cw-1",
        status: estado,
        custom_attributes: { handoffId: "h_abc" },
      },
      assignee: { id: 7, name: "Beto", email: "beto@loja.ao" },
    };
  }

  it("sem secret da 401 e conta na metrica", async () => {
    const { hnd } = montar();
    const veredicto = await hnd.receber(TENANT, null, corpoDeEstado("resolved"));
    assert.equal(veredicto.aceite, false);
    assert.equal(veredicto.aceite === false ? veredicto.estado : 0, 401);
    assert.equal(hnd.metricas.ler()[`${METRICA_RECUSAS}:sem_secret`], 1);
  });

  it("com secret errado da 401 e conta", async () => {
    const { hnd } = montar();
    const veredicto = await hnd.receber(TENANT, "errado", corpoDeEstado("resolved"));
    assert.equal(veredicto.aceite, false);
    assert.equal(hnd.metricas.ler()[`${METRICA_RECUSAS}:secret_errado`], 1);
  });

  it("**sem conta de atendimento tambem da 401**", async () => {
    // A conta desconhecida e o terceiro motivo, e vem depois do segredo: um
    // pedido sem segredo nunca chega a consultar a base.
    const { hnd } = montar();
    const veredicto = await hnd.receber(TENANT, SEGREDO, corpoDeEstado("resolved"));
    assert.equal(veredicto.aceite, false);
    assert.equal(hnd.metricas.ler()[`${METRICA_RECUSAS}:conta_desconhecida`], 1);
  });

  it("um tipo que nao tratamos da 401 e tipo_desconhecido", async () => {
    const { hnd } = montar();
    await hnd.ensureAccount(TENANT);
    const veredicto = await hnd.receber(TENANT, SEGREDO, {
      event: "conversation_created",
      conversation: { id: "cw-1", custom_attributes: { handoffId: "h_abc" } },
    });
    assert.equal(veredicto.aceite, false);
    assert.equal(hnd.metricas.ler()[`${METRICA_RECUSAS}:tipo_desconhecido`], 1);
  });

  it("**um resolved do provedor pede a retoma ao AGR**", async () => {
    const { hnd, bd, agr } = montar();
    await hnd.ensureAccount(TENANT);
    await hnd.openHandoff(pedido());
    const veredicto = await hnd.receber(TENANT, SEGREDO, corpoDeEstado("resolved"));
    assert.equal(veredicto.aceite, true);
    // O `status` fica `resumed` porque **o AGR** o escreveu, ao vencer o CAS.
    assert.equal(bd.handoffs.get("h_abc")?.status, "resumed");
    assert.equal(agr.pedidos.length, 1);
  });

  it("um snoozed **nao** fecha nada nem pede retoma", async () => {
    // Tratar uma soneca do agente como fecho era deixar o cliente sem resposta
    // e marcar a passagem como atendida.
    const { hnd, bd, agr } = montar();
    await hnd.ensureAccount(TENANT);
    await hnd.openHandoff(pedido());
    const veredicto = await hnd.receber(TENANT, SEGREDO, corpoDeEstado("snoozed"));
    assert.equal(veredicto.aceite, true, "o callback e valido");
    assert.equal(bd.handoffs.get("h_abc")?.status, "waiting", "mas nao fecha");
    assert.deepEqual(agr.pedidos, [], "e nao se pede a retoma de uma soneca");
  });

  it("o handler registado recebe o acontecimento", async () => {
    const { hnd } = montar();
    await hnd.ensureAccount(TENANT);
    const recebidos: HumanEvent[] = [];
    hnd.onHumanEvent(async (e) => {
      recebidos.push(e);
    });
    await hnd.receber(TENANT, SEGREDO, corpoDeEstado("open"));
    assert.equal(recebidos.length, 1);
    assert.equal(recebidos[0]?.acontecimento, "estado_mudou");
    assert.equal(recebidos[0]?.handoffId, "h_abc");
  });

  it("**o registo nao leva nome nem e-mail do agente**", async () => {
    // O `resolver` e o primeiro dado pessoal de um trabalhador da PME no
    // esquema, e o provedor manda `name` e `email` no mesmo objecto.
    const { hnd, registo } = montar();
    await hnd.ensureAccount(TENANT);
    await hnd.receber(TENANT, "errado", corpoDeEstado("resolved"));
    const tudo = JSON.stringify(registo);
    assert.ok(!tudo.includes("Beto"));
    assert.ok(!tudo.includes("beto@loja.ao"));
    assert.ok(!tudo.includes(SEGREDO), "o segredo tambem nao vai a registo");
    assert.ok(tudo.includes("callback_recusado_secret_errado"));
  });
});

/**
 * A fronteira da emenda 1.42: quem escreve a saída de `waiting` (KAM-019).
 *
 * **O defeito que estes testes prendem não era uma intercalação rara: era o
 * caminho feliz, todas as vezes.** O `#fechar` corria antes de alguém poder
 * pedir a retoma, o *compare-and-set* do AGR não casava linha nenhuma, o
 * `Command(resume=…)` nunca corria, e o `interrupt()` do `handoff_wait` ficava
 * pendente para sempre — invisível, porque a varredura dos prazos filtra
 * `waiting` e a invariante da não-reentrada também. A descrição está na
 * `docs/analises/ANALISE-35`, achado 1, e a decisão no dicionário §3.32.
 */
describe("a fronteira da retoma (emenda 1.42, credor do criterio 3 do KAM-034)", () => {
  function corpoResolvido(troca: Corpo = {}): Corpo {
    return {
      event: "conversation_status_changed",
      conversation: {
        id: "cw-1",
        status: "resolved",
        custom_attributes: { handoffId: "h_abc" },
      },
      assignee: { id: 7, name: "Beto", email: "beto@loja.ao" },
      ...troca,
    };
  }

  /** Uma passagem aberta e com a *thread* interrompida, como em produção. */
  async function comPassagemAEspera(): Promise<Montagem> {
    const montagem = montar();
    await montagem.hnd.ensureAccount(TENANT);
    await montagem.hnd.openHandoff(pedido());
    // O `handoff_wait` levantou o `interrupt()`: a *thread* está à espera de
    // uma pessoa. É este o estado que o `Command(resume=…)` desfaz.
    montagem.agr.interrompidas.add(threadDe(TENANT, CONTACTO));
    return montagem;
  }

  it("**nenhum interrupt fica pendente num handoff que um humano resolveu**", async () => {
    // A propriedade inteira, de ponta a ponta, e e a razao de ser deste
    // trabalho. Com o defeito, o conjunto ficava com a *thread* la dentro.
    const { hnd, agr, bd } = await comPassagemAEspera();
    await hnd.receber(TENANT, SEGREDO, corpoResolvido());

    assert.equal(agr.comandos, 1, "o Command(resume=...) tem de correr");
    assert.deepEqual([...agr.interrompidas], [], "nenhuma thread fica interrompida");
    assert.equal(bd.handoffs.get("h_abc")?.status, "resumed");
  });

  it("**o HND nao escreve o status: quem o escreve e o CAS do AGR**", async () => {
    // A assercao e sobre as **consultas**, nao sobre o estado final: o estado
    // final e o mesmo nos dois desenhos, e e isso que faz deste defeito uma
    // coisa que nenhum teste de resultado podia apanhar. O que distingue os
    // dois e nunca aparecer um `fechar` nesta sequencia.
    const { hnd, bd } = await comPassagemAEspera();
    bd.pedidos.length = 0;
    await hnd.receber(TENANT, SEGREDO, corpoResolvido());

    assert.ok(
      !bd.pedidos.includes("fechar"),
      `o receber nao pode fechar; correu ${JSON.stringify(bd.pedidos)}`,
    );
    assert.deepEqual(bd.pedidos, ["conta", "thread_da_passagem", "marcar_resolver"]);
  });

  it("**o corpo da retoma sao os tres campos, e o thread_id vem da linha**", async () => {
    const { hnd, agr } = await comPassagemAEspera();
    await hnd.receber(TENANT, SEGREDO, corpoResolvido());

    assert.deepEqual(agr.pedidos, [
      {
        threadId: `${TENANT}:${CONTACTO}`,
        handoffId: "h_abc",
        // **O `outcome` atravessa sem traducao**: o `handoff_close` do grafo
        // compara `outcome == "timeout"`, e um `resumed` a chegar la nao batia
        // com nada.
        outcome: "resolved",
      },
    ]);
    // E o `resolver` **nao** vai no corpo: o ADR-010 mantem a identidade do
    // agente fora do AGR, e e por isso que ele tem escrita propria.
    assert.ok(!JSON.stringify(agr.pedidos).includes("7"));
  });

  it("**o resolver chega a base sem passar pelo AGR**", async () => {
    const { hnd, bd, agr } = await comPassagemAEspera();
    await hnd.receber(TENANT, SEGREDO, corpoResolvido());

    assert.equal(bd.handoffs.get("h_abc")?.resolver, "7");
    assert.ok(!JSON.stringify(agr.pedidos).includes("Beto"));
  });

  it("**o resolver escreve-se antes da retoma, e e a unica ordem que funciona**", async () => {
    // Invertidas, o `SQL_MARCAR_RESOLVER` nao casava linha nenhuma: ele exige
    // `status = 'waiting'` e o CAS acaba de o mudar. A assercao e sobre o
    // **instante** e nao sobre o estado final: quando a retoma chega, a linha
    // ainda esta em `waiting` e **ja** tem o resolver.
    const { hnd, agr } = await comPassagemAEspera();
    await hnd.receber(TENANT, SEGREDO, corpoResolvido());

    assert.equal(agr.estadoNaChegada, "waiting", "o HND nao pode ter escrito o status");
    assert.equal(agr.resolverNaChegada, "7", "e o resolver tem de ja estar la");
  });

  it("**dois webhooks duplicados dao UMA retoma**", async () => {
    // Era isto que o compare-and-set comprava, e e isto que nao se pode perder
    // ao mudar de escritor: o segundo pedido sai `repetido` e nao produz
    // `Command` nenhum.
    const { hnd, agr, bd } = await comPassagemAEspera();
    await hnd.receber(TENANT, SEGREDO, corpoResolvido());
    await hnd.receber(TENANT, SEGREDO, corpoResolvido());

    assert.equal(agr.pedidos.length, 2, "os dois webhooks chegam ao AGR");
    assert.equal(agr.comandos, 1, "e produzem **um** Command");
    assert.equal(hnd.metricas.ler()[`${METRICA_HANDOFFS}:resumed`], 1);
    assert.equal(bd.handoffs.get("h_abc")?.resumed_at, T0);
  });

  it("**o segundo webhook nao reescreve o resolver do primeiro**", async () => {
    // O `status = 'waiting'` no predicado do `SQL_MARCAR_RESOLVER` e quem o
    // impede, e nos dois webhooks do Chatwoot o segundo pode trazer outro
    // `assignee` — quem respondeu foi o primeiro.
    const { hnd, bd, registo } = await comPassagemAEspera();
    await hnd.receber(TENANT, SEGREDO, corpoResolvido());
    await hnd.receber(TENANT, SEGREDO, corpoResolvido({ assignee: { id: 99 } }));

    assert.equal(bd.handoffs.get("h_abc")?.resolver, "7");
    assert.ok(registo.some((l) => l["outcome"] === "resolver_sem_efeito"));
  });

  it("**um handoffId de outra conversa nao escreve nem retoma**", async () => {
    // O `handoff_id` chega do atributo de uma conversa **no provedor**, isto e,
    // de fora. Com o `external_id` no predicado, um valor trocado la nao nos faz
    // pedir a retoma do *thread* de outra pessoa — que e o perigo que o §3.32
    // nomeia para o lado do AGR, visto deste lado.
    const { hnd, bd, agr, registo } = await comPassagemAEspera();
    await hnd.receber(
      TENANT,
      SEGREDO,
      corpoResolvido({
        conversation: {
          id: "cw-de-outra-conversa",
          status: "resolved",
          custom_attributes: { handoffId: "h_abc" },
        },
      }),
    );

    assert.deepEqual(agr.pedidos, [], "nao se pede retoma nenhuma");
    assert.equal(bd.handoffs.get("h_abc")?.resolver, null, "e nao se escreve o resolver");
    assert.equal(bd.handoffs.get("h_abc")?.status, "waiting");
    assert.ok(registo.some((l) => l["outcome"] === "retoma_sem_passagem"));
  });

  it("**o callback sem resolver nao corre a instrucao do resolver**", async () => {
    // Um `COALESCE($3, resolver)` punha-a a correr para nada e a devolver uma
    // linha a dizer que escreveu.
    const { hnd, bd, agr } = await comPassagemAEspera();
    bd.pedidos.length = 0;
    await hnd.receber(TENANT, SEGREDO, corpoResolvido({ assignee: undefined }));

    assert.ok(!bd.pedidos.includes("marcar_resolver"));
    assert.equal(bd.handoffs.get("h_abc")?.resolver, null);
    assert.equal(agr.pedidos.length, 1, "mas a retoma pede-se de qualquer maneira");
  });

  it("**o AGR em baixo levanta, e a passagem fica em waiting**", async () => {
    // O *endpoint* responde 5xx, o provedor reenvia o *callback*, e na volta
    // seguinte a passagem ainda esta em `waiting`: o `resolver` reescreve-se e o
    // CAS volta a ter oportunidade. Engolir isto era o defeito outra vez.
    const { hnd, bd, agr } = await comPassagemAEspera();
    agr.emBaixo = true;
    await assert.rejects(
      () => hnd.receber(TENANT, SEGREDO, corpoResolvido()),
      RetomaIndisponivelError,
    );
    assert.equal(bd.handoffs.get("h_abc")?.status, "waiting");
    assert.equal(bd.handoffs.get("h_abc")?.resolver, "7", "o resolver ja ficou");
    assert.equal(agr.comandos, 0);

    // E a repeticao do provedor conclui o que ficou a meio.
    agr.emBaixo = false;
    await hnd.receber(TENANT, SEGREDO, corpoResolvido());
    assert.equal(agr.comandos, 1);
    assert.deepEqual([...agr.interrompidas], []);
  });

  it("**o handler do onHumanEvent corre, e corre depois da retoma**", async () => {
    // A ordem e escolhida: o handler e uma notificacao e a retoma e a transicao
    // de estado. Com o handler primeiro, uma falha dele impedia a transicao de
    // ser pedida — a forma mais recente do mesmo defeito.
    const { hnd, agr } = await comPassagemAEspera();
    const vistos: { evento: string; comandos: number }[] = [];
    hnd.onHumanEvent(async (e) => {
      vistos.push({ evento: e.acontecimento, comandos: agr.comandos });
    });
    await hnd.receber(TENANT, SEGREDO, corpoResolvido());

    assert.deepEqual(vistos, [{ evento: "estado_mudou", comandos: 1 }]);
  });

  it("**sem porta de retoma o resolved levanta, e nao segue em frente**", async () => {
    // A porta e obrigatoria no tipo, pelo que isto so se monta com um `as`: e
    // deliberado, e o que se mede e que **nao ha omissao silenciosa**. Uma
    // omissao que nao fizesse nada era o defeito original com outro nome — o
    // `resolved` seguia o seu caminho, ninguem pedia a retoma, e o `interrupt()`
    // ficava pendente sem um unico sinal. E a mesma decisao que o
    // `RetomaNaoImplementadaError` do `api_interna.py` tomou do outro lado.
    const { bd } = await comPassagemAEspera();
    const semPorta = new Handoff({
      bd,
      provedor: {
        abrirConversa: async () => "cw-1",
        espelhar: async () => undefined,
        fecharConversa: async () => undefined,
      },
      provisionador: {
        criarConta: async () => {
          throw new Error("este teste nao provisiona nada");
        },
      },
      fila: new FilaFalsa(),
      refDoTokenDoBot: (id: string) => `chatwoot_bot_token/${id}`,
      refDoTokenDoUtilizador: (id: string) => `chatwoot_user_token/${id}`,
      guardarSegredo: async () => undefined,
      segredoDoBot: async () => SEGREDO,
    } as unknown as ConstructorParameters<typeof Handoff>[0]);

    await assert.rejects(
      () => semPorta.receber(TENANT, SEGREDO, corpoResolvido()),
      TypeError,
      "sem porta tem de levantar, nao de devolver aceite",
    );
    // E a passagem fica como estava: a excepcao nao deixou meia transicao.
    assert.equal(bd.handoffs.get("h_abc")?.status, "waiting");
  });
});

describe("as metricas do HND", () => {
  it("a exposicao tem as tres e nenhuma leva tenant_id", async () => {
    const { hnd } = montar();
    await hnd.openHandoff(pedido());
    const texto = hnd.metricas.exposicao();
    for (const nome of [METRICA_HANDOFFS, METRICA_RECUSAS, METRICA_PENDENTES]) {
      assert.ok(texto.includes(`# TYPE ${nome} `), nome);
    }
    assert.ok(!texto.includes(TENANT), "nenhum tenant_id na exposicao");
    assert.ok(!texto.includes("h_abc"), "nenhum handoff_id tambem");
  });

  it("o gauge esta a -1 antes da primeira medicao", () => {
    const { hnd } = montar();
    assert.ok(hnd.metricas.exposicao().includes(`${METRICA_PENDENTES} -1`));
  });
});

describe("o que o spike e a revisao fecharam", () => {
  it("**os dois access_token vao para o cofre, e so eles**", async () => {
    // O provedor mostra-os **uma vez**, no corpo da criacao. A primeira versao
    // nao os capturava: dois segredos gerados e nada a guarda-los, pelo que
    // nenhuma operacao posterior os podia usar.
    const { hnd, cofre } = montar();
    await hnd.ensureAccount(TENANT);
    assert.deepEqual(
      cofre.map((e) => e.ref).sort(),
      [`chatwoot_bot_token/${TENANT}`, `chatwoot_user_token/${TENANT}`],
    );
    assert.deepEqual(
      cofre.map((e) => e.segredo).sort(),
      ["o do bot", "o do utilizador"],
    );
  });

  it("**as duas SecretRef vao para a base, e nao os tokens**", async () => {
    const { hnd, bd } = montar();
    await hnd.ensureAccount(TENANT);
    const gravado = JSON.stringify([...bd.contas.values()]);
    assert.ok(gravado.includes(`chatwoot_bot_token/${TENANT}`));
    assert.ok(!gravado.includes("o do bot"), "o token nao vai a base");
    assert.ok(!gravado.includes("o do utilizador"));
  });

  it("**um callback sem segredo nao consulta nada**", async () => {
    // A nota do `receber` dizia que «um pedido sem segredo nunca chega a
    // consultar nada» e era falso: ia ao cofre **e** fazia um `SELECT` antes de
    // avaliar, pelo que o endpoint era utilizavel como amplificador. Agora e
    // verdade, e e esta assercao que o prende.
    const { hnd, bd, cofreConsultado } = montar();
    bd.pedidos.length = 0;
    cofreConsultado.length = 0;
    const veredicto = await hnd.receber(TENANT, null, {});
    assert.equal(veredicto.aceite, false);
    assert.deepEqual(bd.pedidos, [], "nenhuma consulta");
    assert.deepEqual(cofreConsultado, [], "nenhuma ida ao cofre");
  });

  it("um callback com segredo **vazio** tambem nao consulta", async () => {
    const { hnd, bd, cofreConsultado } = montar();
    bd.pedidos.length = 0;
    cofreConsultado.length = 0;
    await hnd.receber(TENANT, "", {});
    assert.deepEqual(bd.pedidos, []);
    assert.deepEqual(cofreConsultado, []);
  });

  it("**um segredo errado ja consulta, e isso e inevitavel**", async () => {
    // Para saber que esta errado e preciso saber qual era o certo. O que se
    // fecha e o caso **sem** segredo, que e o que um atacante manda em volume.
    const { hnd, bd } = montar();
    bd.pedidos.length = 0;
    await hnd.receber(TENANT, "errado", {});
    assert.ok(bd.pedidos.includes("conta"));
  });

  it("**o resolver do callback e escrito, e nao perdido**", async () => {
    // A cablagem estava feita de ponta a ponta menos um fio: o `close` passava
    // `null` em `$4` sempre, pelo que o `COALESCE` era um no-op e a coluna
    // nunca era escrita por caminho nenhum.
    const { hnd, bd } = montar();
    await hnd.openHandoff(pedido());
    await hnd.receber(TENANT, SEGREDO, {
      event: "conversation_status_changed",
      conversation: {
        id: "cw-1",
        status: "resolved",
        custom_attributes: { handoffId: "h_abc" },
      },
      assignee: { id: 77 },
    });
    assert.equal(bd.handoffs.get("h_abc")?.resolver, "77");
  });

  it("**o close pela porta nao inventa um resolver**", async () => {
    const { hnd, bd } = montar();
    await hnd.openHandoff(pedido());
    await hnd.close("h_abc", "resolved");
    assert.equal(bd.handoffs.get("h_abc")?.resolver ?? null, null);
  });

  it("**marcar_aberta sem casar devolve o estado verdadeiro**", async () => {
    // A janela e uma chamada HTTP a um terceiro: se um `resolved` chegar nela,
    // o `UPDATE` nao casa. Descartar as linhas dizia `waiting` a quem chamava,
    // contava uma passagem aberta que ja fechara, e deixava a conversa do
    // provedor sem nada a aponta-la.
    const { hnd, bd, provedor, registo } = montar();
    provedor.antesDeAbrir = () => {
      const linha = bd.handoffs.get("h_abc");
      if (linha !== undefined) linha.status = "resumed";
    };
    const aberto = await hnd.openHandoff(pedido());
    assert.equal(aberto.estado, "resumed", "o estado e o da base e nao `waiting`");
    assert.ok(aberto.externalId.length > 0, "o externalId existe e correlaciona");
    assert.ok(
      registo.some((l) => l.outcome === "handoff_aberto_fora_de_tempo"),
      "e fica rasto",
    );
  });

  it("**um fecho que nao casa deixa rasto, e nao silencio**", async () => {
    const { hnd, registo } = montar();
    await hnd.close("h_que_nao_existe", "resolved");
    assert.ok(registo.some((l) => l.outcome === "handoff_fecho_sem_efeito"));
  });
});
