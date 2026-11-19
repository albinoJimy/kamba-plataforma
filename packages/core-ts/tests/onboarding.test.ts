/**
 * O onboarding de canal: a forma v4, a matriz, a cifra e a saga (KAM-016).
 *
 * ## O que esta bateria prova, e o que não pode provar
 *
 * As partes puras provam-se aqui por inteiro: a verificação da forma de v4
 * (critério 1), a matriz de transições nos **81** pares ordenados (critério 6), a
 * igualdade de conjuntos dos onze campos (critério 5) e a cifra com DEK por
 * tenant e `kid` versionado (critério 3). Nenhuma precisa de base, e medi-las
 * contra uma base era pagar um contentor para confirmar uma tabela de decisão.
 *
 * A `Onboarding` precisa de base, e aqui a base é **falsa**. Isso tem um limite
 * que vale a pena dizer antes de alguém ler as asserções e concluir mais do que
 * elas dizem:
 *
 * > **Um duplo prova que o nosso código chama o que pretendíamos chamar; não
 * > prova que o PostgreSQL faz o que pensamos.** As duas unicidades que dão a
 * > idempotência do critério 2, a `tenant_channels_phone_number_id_uq` **global**
 * > que dá o 409 do critério 4, o `WHERE fase = <esperada>` que serializa a
 * > transição e a RLS **não existem** numa base falsa. Existem numa real, e é lá
 * > que são provados: `tests_bd/onboarding.bd.test.ts`, no *gate* 8.
 *
 * O que esta montagem mede, e que a base verdadeira mede pior: **a ordem dos
 * passos** — que o tecto se conta antes de abrir a tentativa, que a forma de v4
 * se verifica antes de falar com a Meta, que a repetição **não** fala com a Meta,
 * e que a compensação desfaz os recursos pela ordem inversa. O despacho é por
 * **identidade da constante** e não por texto, como no KAM-015, no KAM-021 e no
 * KAM-023: comparar `texto === SQL_ABRIR` falha a compilar se a constante
 * desaparecer.
 */

import assert from "node:assert/strict";
import { readFileSync, readdirSync } from "node:fs";
import { createHash, randomUUID } from "node:crypto";
import { describe, it } from "node:test";

import {
  CAMINHO_DA_TROCA,
  CAMPOS_DE_WEBHOOK,
  DIGITOS_DO_PIN,
  EsNaoEV4Error,
  FAMILIA_DO_PIN,
  FAMILIA_DO_TOKEN,
  FASES,
  FEATURE_TYPE_DE_COEXISTENCIA,
  JANELA_DE_ONBOARDINGS_DIAS,
  LIMITE_DE_ONBOARDINGS,
  LimiteDeOnboardingsError,
  MOTIVOS_DE_RECUSA,
  Metricas,
  NumeroJaUsadoError,
  Onboarding,
  PRAZO_DE_ABANDONO_MIN,
  RECURSOS,
  REF_DA_KEK,
  SESSION_INFO_VERSION,
  SQL_ABANDONAR,
  SQL_ABRIR,
  SQL_APAGAR_CANAL,
  SQL_CANAL_A_RELIGAR,
  SQL_CONTAR_JANELA,
  SQL_CRIAR_CANAL,
  SQL_FASE,
  SQL_GUARDAR_PIN,
  SQL_LARGAR_O_PONTO,
  SQL_LIGAR_CANAL,
  SQL_LIMPAR_RECURSOS,
  SQL_PONTO_DE_SALVAGUARDA,
  SQL_REABRIR,
  SQL_RECURSOS,
  SQL_REGISTAR_RECURSO,
  SQL_REGISTAR_RECUSA,
  SQL_RELIGAR_CANAL,
  SQL_SOLTAR_CANAL,
  SQL_TENTATIVA,
  SQL_TRANSITAR,
  SQL_VOLTAR_AO_PONTO,
  SubscricaoIncompletaError,
  TRANSICOES,
  KekSemKidEstavelError,
  TokenCifradoInvalidoError,
  TransicaoInvalidaError,
  VARIAVEL_DA_VERSAO_DA_GRAPH,
  VERSAO_DA_GRAPH_POR_OMISSAO,
  VersaoDaGraphInvalidaError,
  cifrarToken,
  compararCampos,
  contextoDaCifra,
  decifrarToken,
  dekDoTenant,
  kidDoCriptograma,
  modoDoSessionInfo,
  resumoDoCode,
  transicaoValida,
  versaoDaGraph,
} from "../src/onboarding/index.ts";
import type {
  ClienteSql,
  Cofre,
  Fase,
  Graph,
  RecursoCriado,
  ResultadoDoEs,
  Tentativa,
} from "../src/onboarding/index.ts";
import { EnvSecretProvider } from "../src/secrets/env.ts";
import { cunharRef } from "../src/secrets/escrita.ts";

/** Uma KEK de ensaio: 32 octetos em base64, a forma que o `cifra.ts` exige. */
const KEK = Buffer.alloc(32, 7).toString("base64");
const KEK_NOVA = Buffer.alloc(32, 9).toString("base64");

const TENANT = "11111111-1111-4111-8111-111111111111";
const OUTRO_TENANT = "22222222-2222-4222-8222-222222222222";

function sessionInfoDeV4(
  featureType: unknown = FEATURE_TYPE_DE_COEXISTENCIA,
  versao: unknown = SESSION_INFO_VERSION,
): Record<string, unknown> {
  return { sessionInfoVersion: versao, extras: { featureType } };
}

function entradaDeEnsaio(parcial: Partial<ResultadoDoEs> = {}): ResultadoDoEs {
  return {
    tenant_id: TENANT,
    code: "AQB-code-de-ensaio",
    waba_id: "102290129340398",
    phone_number_id: "106540352242922",
    session_info: sessionInfoDeV4(),
    ...parcial,
  };
}

// --------------------------------------------------------------------- duplos

/**
 * A base falsa: responde por **identidade da constante** de SQL.
 *
 * Não interpreta SQL — compara a cadeia com a constante importada. É a forma do
 * `ClienteEspiao` do KAM-021 e do KAM-023, e a razão está no `docstring` deste
 * ficheiro: comparar por texto deixava um teste verde quando a constante mudasse
 * de nome.
 */
class BaseFalsa implements ClienteSql {
  readonly chamadas: string[] = [];
  /**
   * **Modela o aborto da transacção**, e é o que prova a correcção da revisão
   * adversarial.
   *
   * Um `23505` aborta a transacção inteira no PostgreSQL: todas as instruções
   * seguintes respondem `25P02` até alguém voltar a um ponto de salvaguarda. O
   * duplo passa a fazer o mesmo — e sem isto a bateria dava verde sobre um
   * defeito real, porque a compensação parecia correr quando na base de verdade
   * nenhuma das suas instruções passava. Era exactamente o limite que o
   * `docstring` deste ficheiro avisa.
   */
  abortada = false;
  pontos = 0;
  /**
   * **O `channel_id` que a linha aponta, e a FK que o protege.**
   *
   * A `channel_onboarding_channel_fk` não tem `ON DELETE CASCADE`, como todas as
   * deste esquema: enquanto a tentativa apontar para o canal, apagá-lo levanta
   * `23503`. O duplo passou a fazer o mesmo, e foi assim que a revisão
   * adversarial ficou medida em vez de corrigida às cegas — a compensação
   * apagava o canal **antes** de a linha o largar, e o `23503` abortava a
   * transacção no último passo.
   *
   * É a terceira coisa que este duplo aprendeu a modelar, e as três são a mesma
   * lição: o que a base impõe e o duplo não impõe é um defeito que fica verde.
   */
  canalApontado: string | null = null;
  readonly linhas = new Map<string, Tentativa>();
  recursos: RecursoCriado[] = [];
  fase: Fase = "iniciado";
  janela = 0;
  /** Quando `true`, o `SQL_ABRIR` devolve zero linhas (a tentativa já existia). */
  jaExistia = false;
  /** Quando `true`, o `SQL_CRIAR_CANAL` levanta o `23505` do número. */
  numeroDeOutroTenant = false;
  /** O que o `SQL_ABRIR` devolveu, para os testes olharem. */
  aberta: Tentativa | null = null;
  canaisApagados = 0;
  pinRef: string | null = null;
  recusas = 0;
  limpou = 0;
  /**
   * Um canal que caiu (KAM-207): de que tenant, com que número, e em que estado.
   * O duplo responde ao `SQL_CANAL_A_RELIGAR` pelos dois argumentos; o predicado
   * em si mede-se contra a base em `db/tests/test_religacao_do_canal.py`.
   */
  caido: { id: string; tenant: string; pnid: string; tokenRef: string; estado: string; waba: string } | null = null;
  /** O `SQL_REABRIR` reabre? Falso quando o *code* é o mesmo (a base recusa-o). */
  reabre = true;

  async query<T = Record<string, unknown>>(
    texto: string,
    valores: readonly unknown[] = [],
  ): Promise<{ readonly rows: readonly T[] }> {
    this.chamadas.push(texto);
    if (texto === SQL_PONTO_DE_SALVAGUARDA) {
      this.pontos += 1;
      return { rows: [] };
    }
    if (texto === SQL_VOLTAR_AO_PONTO) {
      // É isto que torna a ligação utilizável outra vez, e é a única forma de
      // o conseguir depois de um `23505`.
      this.abortada = false;
      return { rows: [] };
    }
    if (texto === SQL_LARGAR_O_PONTO) return { rows: [] };
    if (this.abortada) {
      const erro = new Error(
        "current transaction is aborted, commands ignored until end of transaction block",
      ) as Error & { code: string };
      erro.code = "25P02";
      throw erro;
    }
    if (texto === SQL_CONTAR_JANELA) {
      assert.equal(valores[0], JANELA_DE_ONBOARDINGS_DIAS);
      return { rows: [{ contagem: this.janela }] as T[] };
    }
    if (texto === SQL_ABRIR) {
      if (this.jaExistia) return { rows: [] };
      this.aberta = {
        id: randomUUID(),
        tenant_id: String(valores[0]),
        channel_id: null,
        waba_id: String(valores[1]),
        waac_id: null,
        phone_number_id: String(valores[3]),
        fase: "iniciado",
        recursos_criados: [],
        pin_ref: null,
        motivo: null,
      };
      this.linhas.set(this.aberta.waba_id, this.aberta);
      return { rows: [this.aberta] as T[] };
    }
    if (texto === SQL_TENTATIVA) {
      const linha = this.linhas.get(String(valores[1]));
      if (linha === undefined) return { rows: [] };
      return {
        rows: [{ ...linha, fase: this.fase, recursos_criados: [...this.recursos] }] as T[],
      };
    }
    if (texto === SQL_RECURSOS) {
      return { rows: [{ recursos_criados: [...this.recursos] }] as T[] };
    }
    if (texto === SQL_FASE) return { rows: [{ fase: this.fase }] as T[] };
    if (texto === SQL_REGISTAR_RECURSO) {
      this.recursos.push(...(JSON.parse(String(valores[2])) as RecursoCriado[]));
      return { rows: [{ recursos_criados: [...this.recursos] }] as T[] };
    }
    if (texto === SQL_LIMPAR_RECURSOS) {
      this.recursos = [];
      this.limpou += 1;
      return { rows: [{ recursos_criados: [] }] as T[] };
    }
    if (texto === SQL_CRIAR_CANAL) {
      if (this.numeroDeOutroTenant) {
        const erro = new Error("duplicate key value violates unique constraint") as Error & {
          code: string;
          constraint: string;
        };
        erro.code = "23505";
        erro.constraint = "tenant_channels_phone_number_id_uq";
        // **E a transacção fica abortada**, como numa base de verdade.
        this.abortada = true;
        throw erro;
      }
      return { rows: [{ id: randomUUID() }] as T[] };
    }
    if (texto === SQL_LIGAR_CANAL) {
      this.fase = "es_concluido";
      this.canalApontado = String(valores[2]);
      return { rows: [{ fase: this.fase }] as T[] };
    }
    if (texto === SQL_SOLTAR_CANAL) {
      // O `channel_onboarding_canal_ck` recusa o nulo nas seis fases do meio.
      if (this.fase !== "iniciado" && this.fase !== "falhado" && this.fase !== "abandonado") {
        const erro = new Error(
          'new row for relation "channel_onboarding" violates check constraint ' +
            '"channel_onboarding_canal_ck"',
        ) as Error & { code: string; constraint: string };
        erro.code = "23514";
        erro.constraint = "channel_onboarding_canal_ck";
        this.abortada = true;
        throw erro;
      }
      this.canalApontado = null;
      this.pinRef = null;
      return { rows: [{ channel_id: null }] as T[] };
    }
    if (texto === SQL_GUARDAR_PIN) {
      this.pinRef = String(valores[2]);
      return { rows: [{ pin_ref: this.pinRef }] as T[] };
    }
    if (texto === SQL_APAGAR_CANAL) {
      if (this.canalApontado === String(valores[0])) {
        const erro = new Error(
          'update or delete on table "tenant_channels" violates foreign key ' +
            'constraint "channel_onboarding_channel_fk" on table "channel_onboarding"',
        ) as Error & { code: string; constraint: string };
        erro.code = "23503";
        erro.constraint = "channel_onboarding_channel_fk";
        this.abortada = true;
        throw erro;
      }
      this.canaisApagados += 1;
      return { rows: [{ id: String(valores[0]) }] as T[] };
    }
    if (texto === SQL_TRANSITAR) {
      this.fase = String(valores[3]) as Fase;
      return { rows: [{ fase: this.fase }] as T[] };
    }
    if (texto === SQL_REGISTAR_RECUSA) {
      this.recusas += 1;
      return { rows: [{ id: randomUUID() }] as T[] };
    }
    if (texto === SQL_ABANDONAR) return { rows: [] };
    if (texto === SQL_CANAL_A_RELIGAR) {
      const c = this.caido;
      if (c === null || c.tenant !== valores[0] || c.pnid !== valores[1] || c.estado !== "desligado") return { rows: [] };
      return { rows: [{ id: c.id, token_ref: c.tokenRef }] as T[] };
    }
    if (texto === SQL_REABRIR) {
      const linha = this.linhas.get(String(valores[1]));
      if (linha === undefined || !this.reabre || (this.fase !== "falhado" && this.fase !== "abandonado")) return { rows: [] };
      this.fase = "iniciado";
      this.recursos = [];
      return { rows: [{ ...linha, fase: "iniciado", recursos_criados: [] }] as T[] };
    }
    if (texto === SQL_RELIGAR_CANAL) {
      const c = this.caido;
      if (c === null || c.id !== valores[3] || c.tenant !== valores[4] || c.estado !== "desligado") return { rows: [] };
      this.caido = { ...c, waba: String(valores[0]), tokenRef: String(valores[2]), estado: "ativo" };
      return { rows: [{ id: c.id }] as T[] };
    }
    throw new Error(`SQL que o duplo não conhece: ${texto.slice(0, 60)}`);
  }
}

/** A Graph falsa, com falha injectável por passo. */
class GraphFalsa implements Graph {
  readonly chamadas: string[] = [];
  subscritos: string[] = [];
  /** Quando `true`, o `subscrever` levanta. É a falha injectada no passo 4. */
  falharNaSubscricao = false;
  /** Campos que a leitura de confirmação devolve. `null` = os subscritos. */
  confirmacao: string[] | null = null;
  anulacoes = 0;
  token = "ensaio-token-0123456789abcdef";

  async trocarCode(code: string): Promise<string> {
    this.chamadas.push("trocarCode");
    assert.ok(code.length > 0);
    return this.token;
  }

  async subscrever(_waba: string, campos: readonly string[]): Promise<void> {
    this.chamadas.push("subscrever");
    if (this.falharNaSubscricao) throw new Error("a Meta recusou a subscrição");
    this.subscritos = [...campos];
  }

  async lerSubscricoes(): Promise<readonly string[]> {
    this.chamadas.push("lerSubscricoes");
    return this.confirmacao ?? this.subscritos;
  }

  async anularSubscricao(): Promise<void> {
    this.chamadas.push("anularSubscricao");
    this.anulacoes += 1;
    this.subscritos = [];
  }
}

/** O cofre falso: cunha, lê e revoga, e conta tudo. */
class CofreFalso implements Cofre {
  readonly segredos = new Map<string, string>();
  readonly cunhados: string[] = [];
  readonly revogados: string[] = [];
  anel: readonly [string, string | null] = [KEK, null];
  versoes: readonly string[] = ["1"];

  async get(ref: string): Promise<string> {
    if (ref === REF_DA_KEK) return this.anel[0];
    const valor = this.segredos.get(ref);
    if (valor === undefined) throw new Error(`segredo ausente: ${ref}`);
    return valor;
  }

  async getRing(): Promise<readonly [string, string | null]> {
    return this.anel;
  }

  async versions(): Promise<readonly string[]> {
    return this.versoes;
  }

  async cunhar(familia: string, valor: string): Promise<string> {
    const ref = cunharRef(familia);
    this.segredos.set(ref, valor);
    this.cunhados.push(ref);
    return ref;
  }

  async revogar(ref: string): Promise<void> {
    this.revogados.push(ref);
    this.segredos.delete(ref);
  }
}

function montar(): {
  servico: Onboarding;
  sql: BaseFalsa;
  graph: GraphFalsa;
  cofre: CofreFalso;
  metricas: Metricas;
} {
  const sql = new BaseFalsa();
  const graph = new GraphFalsa();
  const cofre = new CofreFalso();
  const metricas = new Metricas();
  const servico = new Onboarding({ sql, graph, cofre, vertical: "vendedor", metricas });
  return { servico, sql, graph, cofre, metricas };
}

// ------------------------------------------------------------------ critério 1

describe("a forma de v4, e só v4 (criterio 1)", () => {
  it("aceita o featureType da coexistencia e devolve o modo", () => {
    assert.equal(modoDoSessionInfo(sessionInfoDeV4()), "coexistencia");
  });

  it("outro featureType e um ES v4 de cloud_only", () => {
    assert.equal(modoDoSessionInfo(sessionInfoDeV4("whatsapp_business_onboarding")), "cloud_only");
  });

  it("recusa a ausencia do featureType, porque o modo nao se adivinha", () => {
    assert.throws(
      () => modoDoSessionInfo({ sessionInfoVersion: SESSION_INFO_VERSION, extras: {} }),
      EsNaoEV4Error,
    );
    assert.throws(
      () => modoDoSessionInfo({ sessionInfoVersion: SESSION_INFO_VERSION }),
      EsNaoEV4Error,
    );
  });

  it("recusa a versao 2 e a 3: elas deixaram de funcionar a 2026-10-15", () => {
    // Os valores entram num objecto montado à mão e **não** pelo
    // `sessionInfoDeV4`: aquele tem omissão para a versão, e passar-lhe
    // `undefined` dava-lhe o `"3"` — o teste passava a medir a omissão.
    for (const versao of ["2", "3 ", 2, "", "03", null]) {
      assert.throws(
        () =>
          modoDoSessionInfo({
            sessionInfoVersion: versao,
            extras: { featureType: FEATURE_TYPE_DE_COEXISTENCIA },
          }),
        EsNaoEV4Error,
        `devia recusar ${JSON.stringify(versao)}`,
      );
    }
    // E a ausência da chave é recusa também, pela mesma razão: v4 declara-a.
    assert.throws(
      () => modoDoSessionInfo({ extras: { featureType: FEATURE_TYPE_DE_COEXISTENCIA } }),
      EsNaoEV4Error,
    );
  });

  it("tolera o 3 como numero, porque um JSON.parse o faz", () => {
    assert.equal(modoDoSessionInfo(sessionInfoDeV4(FEATURE_TYPE_DE_COEXISTENCIA, 3)), "coexistencia");
  });

  /**
   * **O critério pede isto por extenso**, e é a única afirmação desta bateria
   * que se faz sobre o texto dos ficheiros e não sobre o comportamento.
   *
   * A procura é por `v2`/`v3` como **palavra** e por `sessionInfoVersion` com
   * outro valor: uma procura pela cadeia `"v2"` nua apanhava `v21.0`, que é a
   * versão da Graph e não do ES — o que tornaria o teste impossível de passar
   * por uma razão que não tem nada a ver com o critério.
   */
  it("o codigo nao referencia v2 nem v3 do Embedded Signup", () => {
    const pasta = new URL("../src/onboarding/", import.meta.url);
    const achados: string[] = [];
    for (const nome of readdirSync(pasta)) {
      if (!nome.endsWith(".ts")) continue;
      const texto = readFileSync(new URL(nome, pasta), "utf8");
      for (const [n, linha] of texto.split("\n").entries()) {
        // Um `sessionInfoVersion` com um valor que não é o `"3"` é v2 ou v3 a
        // entrar por configuração. **Captura-se o valor e compara-se**, em vez
        // de uma classe negada: a primeira versão deste teste escrevia
        // `["']?[^3"']` e dava achado em `sessionInfoVersion: "3"` — o `["']?`
        // casava vazio e o `[^3"']` casava a própria aspa. Ficou vermelho na
        // primeira execução, a medir a ortografia do próprio canon.
        const valor = /sessionInfoVersion\s*[:=]\s*["']?([^"',;\s)}]*)/.exec(linha);
        if (valor !== null && valor[1] !== SESSION_INFO_VERSION) {
          achados.push(`${nome}:${n + 1}`);
        }
        // Um ramo de código pela versão do ES: `es_v2`, `esV3`, `ES v2`.
        if (/\bes[_\s-]?v[23]\b/i.test(linha)) achados.push(`${nome}:${n + 1}`);
      }
    }
    assert.deepEqual(achados, []);
  });

  it("a versao do ES nao e configuravel: nao ha variavel para ela", () => {
    // A única variável de ambiente deste módulo é a da **Graph**, e o seu nome
    // di-lo. Uma variável para a versão do ES convidava alguém a voltar atrás.
    assert.equal(VARIAVEL_DA_VERSAO_DA_GRAPH, "KAMBA_META_GRAPH_VERSION");
    assert.ok(!VARIAVEL_DA_VERSAO_DA_GRAPH.includes("SIGNUP"));
  });

  it("a versao da Graph vem do ambiente e falha fechada numa forma invalida", () => {
    assert.equal(versaoDaGraph({}), VERSAO_DA_GRAPH_POR_OMISSAO);
    assert.equal(versaoDaGraph({ [VARIAVEL_DA_VERSAO_DA_GRAPH]: "v25.3" }), "v25.3");
    assert.equal(versaoDaGraph({ [VARIAVEL_DA_VERSAO_DA_GRAPH]: "  " }), VERSAO_DA_GRAPH_POR_OMISSAO);
    // **Não cai para a omissão** numa forma inválida: um segmento que a Meta não
    // reconhece dá 404 em produção, e descobri-lo no arranque é melhor.
    assert.throws(
      () => versaoDaGraph({ [VARIAVEL_DA_VERSAO_DA_GRAPH]: "21.0" }),
      VersaoDaGraphInvalidaError,
    );
  });

  it("o caminho da troca de code e o que o GraphFalso do KAM-024 encaminha", () => {
    assert.equal(CAMINHO_DA_TROCA, "oauth/access_token");
  });
});

// ------------------------------------------------------------------ critério 6

describe("a matriz de transicoes: os 81 pares ordenados (criterio 6)", () => {
  it("as nove fases, e o desligado nao e uma delas", () => {
    assert.equal(FASES.length, 9);
    assert.deepEqual(
      [...FASES],
      [
        "iniciado",
        "es_concluido",
        "subscrito",
        "a_sincronizar",
        "verificado",
        "pronto",
        "ativo",
        "falhado",
        "abandonado",
      ],
    );
    // O `desligado` do diagrama do `01` §13.1 é estado de `tenant_channels` e
    // não fase de onboarding: quem o escreve é o KAM-017.
    assert.ok(!(FASES as readonly string[]).includes("desligado"));
  });

  /**
   * **Os 81 pares, um a um.** Não é uma amostra: a matriz tem 9 × 9 pares
   * ordenados e o critério diz «transições inválidas são rejeitadas» — uma
   * amostra provava que algumas são rejeitadas.
   */
  it("exactamente dezesseis pares passam, e os outros 65 nao", () => {
    const aceites: string[] = [];
    for (const de of FASES) {
      for (const para of FASES) {
        if (transicaoValida(de, para)) aceites.push(`${de}->${para}`);
      }
    }
    assert.equal(aceites.length, 16, aceites.join(", "));
    assert.deepEqual(aceites.sort(), [
      "a_sincronizar->falhado",
      "a_sincronizar->verificado",
      "abandonado->iniciado",
      "es_concluido->falhado",
      "es_concluido->subscrito",
      "falhado->iniciado",
      "iniciado->abandonado",
      "iniciado->es_concluido",
      "iniciado->falhado",
      "pronto->ativo",
      "pronto->falhado",
      "subscrito->a_sincronizar",
      "subscrito->falhado",
      "subscrito->verificado",
      "verificado->falhado",
      "verificado->pronto",
    ]);
  });

  it("uma fase para si mesma nao e transicao", () => {
    for (const fase of FASES) assert.equal(transicaoValida(fase, fase), false);
  });

  it("o ativo e terminal: nao se sai dele", () => {
    assert.deepEqual([...TRANSICOES.ativo], []);
  });

  it("de qualquer fase nao terminal vai-se a falhado (o que o criterio 7 precisa)", () => {
    for (const fase of FASES) {
      if (fase === "ativo" || fase === "falhado" || fase === "abandonado") continue;
      assert.ok(transicaoValida(fase, "falhado"), `${fase} -> falhado`);
    }
  });

  it("o abandonado so sai de iniciado, como o diagrama o desenha", () => {
    for (const fase of FASES) {
      assert.equal(transicaoValida(fase, "abandonado"), fase === "iniciado");
    }
  });

  it("o falhado e o abandonado voltam a iniciado, e nao a outra fase", () => {
    assert.deepEqual([...TRANSICOES.falhado], ["iniciado"]);
    assert.deepEqual([...TRANSICOES.abandonado], ["iniciado"]);
  });

  it("transitar levanta num par invalido, antes de tocar na base", async () => {
    const { servico, sql } = montar();
    await assert.rejects(
      () => servico.transitar(randomUUID(), TENANT, "ativo", "iniciado"),
      TransicaoInvalidaError,
    );
    // **Nenhuma chamada à base**: a recusa é da matriz, e é isso que torna «as
    // transições inválidas são rejeitadas» uma afirmação sobre a máquina.
    assert.deepEqual(sql.chamadas, []);
  });

  it("o prazo do abandono e de 30 minutos", () => {
    assert.equal(PRAZO_DE_ABANDONO_MIN, 30);
  });
});

// ------------------------------------------------------------------ critério 5

describe("os onze campos e a igualdade de conjuntos (criterio 5)", () => {
  it("sao exactamente onze, e os do criterio", () => {
    assert.equal(CAMPOS_DE_WEBHOOK.length, 11);
    assert.deepEqual(
      [...CAMPOS_DE_WEBHOOK],
      [
        "messages",
        "smb_message_echoes",
        "history",
        "smb_app_state_sync",
        "account_update",
        "phone_number_quality_update",
        "business_capability_update",
        "account_alerts",
        "message_template_status_update",
        "template_category_update",
        "message_template_quality_update",
      ],
    );
    assert.equal(new Set(CAMPOS_DE_WEBHOOK).size, 11);
  });

  it("a comparacao e de conjuntos: a ordem nao conta", () => {
    const trocados = [...CAMPOS_DE_WEBHOOK].reverse();
    assert.deepEqual(compararCampos(trocados), { falta: [], aMais: [] });
  });

  it("um campo a menos aparece em falta, e so ele", () => {
    const menos = CAMPOS_DE_WEBHOOK.filter((c) => c !== "history");
    assert.deepEqual(compararCampos(menos), { falta: ["history"], aMais: [] });
  });

  it("um campo a mais aparece a mais, e nao como falta", () => {
    assert.deepEqual(compararCampos([...CAMPOS_DE_WEBHOOK, "flows"]), {
      falta: [],
      aMais: ["flows"],
    });
  });

  it("duplicados na resposta da Meta nao contam como campo a mais", () => {
    // A resposta vem sem ordem garantida e podia vir com repetições; comparar
    // conjuntos é o que torna isso irrelevante.
    assert.deepEqual(compararCampos([...CAMPOS_DE_WEBHOOK, "messages"]), {
      falta: [],
      aMais: [],
    });
  });
});

// ------------------------------------------------------------------ critério 3

describe("a cifra do token: AES-256-GCM, DEK por tenant, kid versionado (criterio 3)", () => {
  it("cifra e decifra, e o criptograma nao contem o token", () => {
    const token = "EAAG-token-de-cliente-de-ensaio";
    const criptograma = cifrarToken(KEK, "1", TENANT, token);
    assert.ok(!criptograma.includes(token));
    // E nem em base64 descodificado: a procura é nos octetos, que é onde um
    // *dump grep* procuraria.
    assert.ok(!Buffer.from(criptograma, "base64").toString("latin1").includes(token));
    assert.equal(decifrarToken({ "1": KEK }, TENANT, criptograma), token);
  });

  it("dois tenants nunca partilham DEK", () => {
    assert.notDeepEqual(dekDoTenant(KEK, TENANT), dekDoTenant(KEK, OUTRO_TENANT));
  });

  it("a DEK e deterministica para o mesmo par (KEK, tenant)", () => {
    assert.deepEqual(dekDoTenant(KEK, TENANT), dekDoTenant(KEK, TENANT));
  });

  it("duas cifras do mesmo token dao criptogramas diferentes (IV novo)", () => {
    const a = cifrarToken(KEK, "1", TENANT, "igual");
    const b = cifrarToken(KEK, "1", TENANT, "igual");
    assert.notEqual(a, b);
  });

  /**
   * **O contexto autenticado prende a cifra ao tenant**, e isto é o que impede
   * o furo concreto: o `token_ref` é uma coluna que o `GRANT UPDATE` da `0001`
   * concede a `kamba_app`, pelo que mover a referência de A para a linha de B é
   * uma escrita que a base aceita. Sem o AAD, B abria o *token* de A.
   */
  it("um criptograma copiado para outro tenant nao abre", () => {
    const criptograma = cifrarToken(KEK, "1", TENANT, "token-de-A");
    assert.throws(
      () => decifrarToken({ "1": KEK }, OUTRO_TENANT, criptograma),
      TokenCifradoInvalidoError,
    );
  });

  /**
   * **O AAD é o único observável desta propriedade, e ninguém o observava.**
   *
   * O teste de cima — «um criptograma copiado para outro tenant nao abre» —
   * passa com e sem o tenant no contexto autenticado, porque a **chave** já é
   * por tenant: a DEK de B não é a de A (`dekDoTenant`, com `info = domínio ‖
   * tenant`) e o GCM rejeita na chave, sem nunca chegar ao AAD. O tenant está
   * ligado duas vezes, e a outra ligação é mais forte — pelo que arrancar esta
   * não quebrava teste nenhum, e a mutação `onboarding: o contexto autenticado
   * deixa de levar o tenant` sobreviveu à noite de 2026-10-26.
   *
   * O `contextoDaCifra` é exportado no `index.ts` de propósito, e tinha **zero**
   * testes. É aqui que a defesa em profundidade se afirma: ela existe para o
   * dia em que a DEK deixar de ser por tenant, e é nesse dia que uma guarda que
   * ninguém mede já não está lá.
   */
  it("o contexto autenticado leva o tenant, e o kid", () => {
    const contexto = contextoDaCifra(TENANT, "1");
    assert.ok(
      contexto.toString("utf8").includes(TENANT),
      "o AAD nao leva o tenant: um criptograma de A abre no contexto de B",
    );
    assert.notDeepEqual(contexto, contextoDaCifra(OUTRO_TENANT, "1"));
    assert.notDeepEqual(contexto, contextoDaCifra(TENANT, "2"));
  });

  it("o kid vai dentro do criptograma e le-se sem o abrir", () => {
    assert.equal(kidDoCriptograma(cifrarToken(KEK, "7", TENANT, "x")), "7");
  });

  /** Sem o `kid`, uma rotação da KEK tornava todos os *tokens* indecifráveis. */
  it("a rotacao da KEK nao perde os tokens antigos", () => {
    const antigo = cifrarToken(KEK, "1", TENANT, "token-antigo");
    const novo = cifrarToken(KEK_NOVA, "2", TENANT, "token-novo");
    const anel = { "1": KEK, "2": KEK_NOVA };
    assert.equal(decifrarToken(anel, TENANT, antigo), "token-antigo");
    assert.equal(decifrarToken(anel, TENANT, novo), "token-novo");
  });

  it("um kid que saiu do anel diz qual, e nao «nao abre»", () => {
    const criptograma = cifrarToken(KEK, "1", TENANT, "x");
    assert.throws(
      () => decifrarToken({ "2": KEK_NOVA }, TENANT, criptograma),
      (erro: unknown) =>
        erro instanceof TokenCifradoInvalidoError && erro.motivo.includes("versão 1"),
    );
  });

  it("um criptograma alterado nao abre: GCM autentica", () => {
    const octetos = Buffer.from(cifrarToken(KEK, "1", TENANT, "token"), "base64");
    // `writeUInt8` e nao `octetos[n] ^= …`: com `noUncheckedIndexedAccess` o
    // acesso por indice e `number | undefined` e o `^=` nao compila.
    octetos.writeUInt8((octetos.at(-1) ?? 0) ^ 0xff, octetos.length - 1);
    assert.throws(
      () => decifrarToken({ "1": KEK }, TENANT, octetos.toString("base64")),
      TokenCifradoInvalidoError,
    );
  });

  it("uma KEK que nao tem 32 octetos e recusada, e nao truncada", () => {
    assert.throws(
      () => cifrarToken(Buffer.alloc(16).toString("base64"), "1", TENANT, "x"),
      TokenCifradoInvalidoError,
    );
  });

  it("um tenant_id que nao e UUID e recusado", () => {
    assert.throws(() => cifrarToken(KEK, "1", "nao-sou-uuid", "x"), TokenCifradoInvalidoError);
  });

  it("nenhum erro da cifra repete o token que recusou", () => {
    const token = "EAAG-segredo-que-nao-deve-aparecer";
    try {
      cifrarToken(KEK, "", TENANT, token);
      assert.fail("devia ter levantado");
    } catch (erro) {
      assert.ok(erro instanceof Error);
      assert.ok(!erro.message.includes(token));
    }
  });

  it("o resumo do code tem 32 octetos e e o sha256 dele", () => {
    const code = "AQB-code";
    assert.equal(resumoDoCode(code).byteLength, 32);
    assert.deepEqual(resumoDoCode(code), createHash("sha256").update(code, "utf8").digest());
  });

  it("as familias sao as do inventario de segredos", () => {
    assert.equal(FAMILIA_DO_TOKEN, "meta_client_token");
    assert.equal(FAMILIA_DO_PIN, "meta_pin_2fa");
    assert.equal(REF_DA_KEK, "kek_token_cliente");
  });

  // --- KAM-205: o `kid` estável, pelo serviço e não só pelas funções ----------
  //
  // Os dois casos passam pelo `Onboarding` com a KEK lida de um
  // `EnvSecretProvider`, que é o provedor do Piloto: é a **ligação** que se
  // prova, e não só o `kekParaCifrar` e o `anelDaKek` — um `#trocarEGuardar` ou
  // um `#tokenEmClaro` que voltasse a montar o anel à mão ficava vermelho aqui.

  /** O cofre falso com a KEK de um `EnvSecretProvider`, e os valores cunhados guardados. */
  class CofreDeAmbiente extends CofreFalso {
    env: EnvSecretProvider;
    readonly valoresCunhados: string[] = [];

    constructor(env: EnvSecretProvider) {
      super();
      this.env = env;
    }

    override async get(ref: string): Promise<string> {
      return ref === REF_DA_KEK ? this.env.get(ref) : super.get(ref);
    }

    override async getRing(): Promise<readonly [string, string | null]> {
      return this.env.getRing(REF_DA_KEK);
    }

    override async versions(): Promise<readonly string[]> {
      return this.env.versions(REF_DA_KEK);
    }

    /** Troca o que se guarda: é como se simula um *token* gravado antes do KAM-205. */
    substituir: (valor: string) => string = (valor) => valor;

    override async cunhar(familia: string, valor: string): Promise<string> {
      this.valoresCunhados.push(valor);
      return super.cunhar(familia, this.substituir(valor));
    }
  }

  /** A Graph falsa que roda a KEK ao ler as subscrições, e guarda o *token* da anulação. */
  class GraphQueRoda extends GraphFalsa {
    aoLer: () => void = () => undefined;
    readonly tokensDaAnulacao: string[] = [];

    override async lerSubscricoes(): Promise<readonly string[]> {
      this.aoLer();
      return super.lerSubscricoes();
    }

    override async anularSubscricao(_waba?: string, token?: string): Promise<void> {
      this.tokensDaAnulacao.push(token ?? "");
      return super.anularSubscricao();
    }
  }

  function ambienteDaKek(actual: string, anterior?: string): EnvSecretProvider {
    const env: Record<string, string> = { KAMBA_SECRET_KEK_TOKEN_CLIENTE: actual };
    if (anterior !== undefined) env.KAMBA_SECRET_KEK_TOKEN_CLIENTE_ANTERIOR = anterior;
    return new EnvSecretProvider({ ambiente: "staging", env });
  }

  it("KAM-205: com a KEK sem kid no valor, o servico recusa cifrar e nao cunha o token", async () => {
    const cofre = new CofreDeAmbiente(ambienteDaKek(KEK));
    const servico = new Onboarding({
      sql: new BaseFalsa(),
      graph: new GraphFalsa(),
      cofre,
      vertical: "vendedor",
      metricas: new Metricas(),
    });
    await assert.rejects(() => servico.ligar(entradaDeEnsaio()), KekSemKidEstavelError);
    assert.equal(cofre.cunhados.length, 0, "um rotulo posicional nunca chega a um criptograma");
  });

  it("KAM-205: o criptograma leva o kid do valor, e uma rotacao a meio da saga nao parte a compensacao", async () => {
    const k1 = `k1:${KEK}`;
    const cofre = new CofreDeAmbiente(ambienteDaKek(k1));
    const graph = new GraphQueRoda();
    // A confirmação incompleta obriga a compensar, e a compensação abre o
    // *token* para anular a subscrição — **depois** da rotação.
    graph.confirmacao = CAMPOS_DE_WEBHOOK.filter((c) => c !== "history");
    graph.aoLer = () => {
      cofre.env = ambienteDaKek(`k2:${KEK_NOVA}`, k1);
    };
    const servico = new Onboarding({
      sql: new BaseFalsa(),
      graph,
      cofre,
      vertical: "vendedor",
      metricas: new Metricas(),
    });
    await assert.rejects(() => servico.ligar(entradaDeEnsaio()), SubscricaoIncompletaError);
    assert.equal(cofre.valoresCunhados.length, 1);
    assert.equal(kidDoCriptograma(cofre.valoresCunhados[0] ?? ""), "k1");
    assert.deepEqual(graph.tokensDaAnulacao, [graph.token], "o token abriu com o k1 em anterior");
  });

  it("KAM-205: um token gravado antes da correcao (kid actual) abre pelo servico depois da rotacao", async () => {
    // A KEK legada nao tem `kid` no valor; o criptograma guardado diz `actual`,
    // como o codigo do KAM-016 o gravava. A rotacao poe a legada em anterior, e
    // o `#tokenEmClaro` tem de a encontrar pelo `KID_LEGADO` — um anel montado a
    // mao com o rotulo `anterior` nao a encontrava.
    const legada = KEK;
    const cofre = new CofreDeAmbiente(ambienteDaKek(`k1:${KEK_NOVA}`));
    const graph = new GraphQueRoda();
    cofre.substituir = () => cifrarToken(legada, "actual", TENANT, graph.token);
    graph.confirmacao = CAMPOS_DE_WEBHOOK.filter((c) => c !== "history");
    graph.aoLer = () => {
      cofre.env = ambienteDaKek(`k2:${Buffer.alloc(32, 5).toString("base64")}`, legada);
    };
    const servico = new Onboarding({
      sql: new BaseFalsa(),
      graph,
      cofre,
      vertical: "vendedor",
      metricas: new Metricas(),
    });
    await assert.rejects(() => servico.ligar(entradaDeEnsaio()), SubscricaoIncompletaError);
    assert.deepEqual(graph.tokensDaAnulacao, [graph.token], "o token legado abriu pela versao sem kid");
  });
});

// ------------------------------------------------------- a saga: 1, 2, 4, 7, 8

describe("a saga: ordem dos passos e idempotencia (criterios 2, 4, 7, 8)", () => {
  it("o caminho completo em coexistencia: 1 token, 1 canal, 1 subscricao", async () => {
    const { servico, sql, graph, cofre } = montar();
    const { tentativa, novo } = await servico.ligar(entradaDeEnsaio());
    assert.equal(novo, true);
    assert.equal(tentativa.fase, "subscrito");
    assert.equal(cofre.cunhados.length, 1);
    assert.deepEqual([...graph.subscritos].sort(), [...CAMPOS_DE_WEBHOOK].sort());
    assert.deepEqual(
      tentativa.recursos_criados.map((r) => r.recurso),
      ["token", "canal", "subscricao"],
    );
    // **Sem PIN em coexistência**: o número já está registado (`E1` §3).
    assert.equal(tentativa.pin_ref, null);
    assert.equal(sql.pinRef, null);
  });

  it("em cloud_only ha PIN de seis digitos, e vai para o cofre", async () => {
    const { servico, cofre, sql } = montar();
    const { tentativa } = await servico.ligar(
      entradaDeEnsaio({ session_info: sessionInfoDeV4("whatsapp_business_onboarding") }),
    );
    assert.equal(cofre.cunhados.length, 2);
    assert.ok(tentativa.pin_ref !== null);
    assert.equal(sql.pinRef, tentativa.pin_ref);
    const pin = cofre.segredos.get(cofre.cunhados[1] ?? "");
    assert.match(pin ?? "", new RegExp(`^\\d{${DIGITOS_DO_PIN}}$`));
    assert.deepEqual(
      tentativa.recursos_criados.map((r) => r.recurso),
      ["token", "pin", "canal", "subscricao"],
    );
  });

  /**
   * **A idempotência do critério 2.** A repetição devolve a tentativa que lá
   * estava e **não fala com a Meta**: trocar o *code* outra vez criava um
   * segundo *token* no cofre antes de descobrir que havia um.
   */
  it("a repeticao devolve o que ja havia e nao chama a Meta nem o cofre", async () => {
    const { servico, sql, graph, cofre } = montar();
    const entrada = entradaDeEnsaio();
    await servico.ligar(entrada);
    const chamadasDaMeta = graph.chamadas.length;
    const cunhados = cofre.cunhados.length;
    sql.jaExistia = true;
    const segunda = await servico.ligar(entrada);
    assert.equal(segunda.novo, false);
    assert.equal(graph.chamadas.length, chamadasDaMeta);
    assert.equal(cofre.cunhados.length, cunhados);
    assert.equal(cunhados, 1);
  });

  it("um code repetido noutro WABA nao inventa resposta: levanta", async () => {
    const { servico, sql } = montar();
    sql.jaExistia = true;
    // O `ON CONFLICT` disparou e a linha do WABA não está lá: só pode ser o
    // conflito da outra chave.
    await assert.rejects(() => servico.ligar(entradaDeEnsaio()), EsNaoEV4Error);
  });

  it("o tecto conta-se antes de abrir a tentativa, e recusa com 10 (criterio 8)", async () => {
    const { servico, sql, metricas, graph } = montar();
    sql.janela = LIMITE_DE_ONBOARDINGS;
    await assert.rejects(() => servico.ligar(entradaDeEnsaio()), LimiteDeOnboardingsError);
    // **Nada foi aberto e nada foi à Meta**: a primeira chamada é a contagem.
    assert.deepEqual(sql.chamadas, [SQL_CONTAR_JANELA]);
    assert.deepEqual(graph.chamadas, []);
    assert.equal(metricas.valor('es_onboarding_recusado_total{motivo="limite_7d"}'), 1);
  });

  it("com nove na janela ainda passa: o tecto e dez, nao nove", async () => {
    const { servico, sql } = montar();
    sql.janela = LIMITE_DE_ONBOARDINGS - 1;
    const { novo } = await servico.ligar(entradaDeEnsaio());
    assert.equal(novo, true);
  });

  it("a contagem espelha o gauge es_onboardings_7d", async () => {
    const { servico, sql, metricas } = montar();
    sql.janela = 4;
    assert.equal(await servico.contarJanela(), 4);
    assert.equal(metricas.valor("es_onboardings_7d"), 4);
  });

  it("a forma de v4 verifica-se antes de abrir e antes da Meta (criterio 1)", async () => {
    const { servico, sql, graph, metricas } = montar();
    await assert.rejects(
      () => servico.ligar(entradaDeEnsaio({ session_info: { sessionInfoVersion: "2" } })),
      EsNaoEV4Error,
    );
    assert.deepEqual(sql.chamadas, [SQL_CONTAR_JANELA]);
    assert.deepEqual(graph.chamadas, []);
    assert.equal(metricas.valor('es_onboarding_recusado_total{motivo="es_nao_e_v4"}'), 1);
  });

  /**
   * **O 409 do critério 4.** O duplo levanta o `23505` com o nome da restrição,
   * que é o que uma base real levanta; o módulo traduz em `NumeroJaUsadoError`.
   */
  /**
   * **O `23505` aborta a transacção, e sem um ponto de salvaguarda a
   * compensação não corre.** Foi o achado mais grave da revisão adversarial: o
   * `ROLLBACK` da rota apaga a linha do canal e a da tentativa, mas **o cofre
   * não é transaccional** — o *token* ficava lá, sem nada a apontar para ele.
   *
   * O que esta bateria afirma é que a compensação **correu mesmo** depois do
   * conflito: o segredo foi revogado e o cofre ficou vazio. Com o duplo a
   * modelar o `25P02` e sem o ponto de salvaguarda, isto fica vermelho.
   */
  it("o numero de outro tenant da NumeroJaUsadoError, e compensa o token", async () => {
    const { servico, sql, cofre, metricas } = montar();
    sql.numeroDeOutroTenant = true;
    await assert.rejects(() => servico.ligar(entradaDeEnsaio()), NumeroJaUsadoError);
    // O ponto de salvaguarda abriu-se uma vez, e foi ele que deixou a ligação
    // utilizável para a compensação.
    assert.equal(sql.pontos, 1);
    assert.equal(sql.abortada, false);
    // O *token* foi cunhado (o passo vem antes, porque `token_ref` é `NOT NULL`)
    // e foi **revogado** pela compensação: 0 recursos órfãos.
    assert.equal(cofre.cunhados.length, 1);
    assert.deepEqual(cofre.revogados, cofre.cunhados);
    assert.equal(cofre.segredos.size, 0);
    assert.deepEqual(sql.recursos, []);
    assert.equal(sql.fase, "falhado");
    assert.equal(
      metricas.valor('es_onboarding_recusado_total{motivo="numero_de_outro_tenant"}'),
      1,
    );
  });

  it("a mensagem do 409 nao diz de quem e o numero", async () => {
    const erro = new NumeroJaUsadoError("106540352242922");
    assert.ok(!erro.message.includes("tenant_id"));
    assert.ok(erro.message.includes("106540352242922"));
  });

  it("um 23505 de outra restricao nao se disfarca de 409", async () => {
    const { servico, sql } = montar();
    const original = sql.query.bind(sql);
    sql.query = async (texto: string, valores?: readonly unknown[]) => {
      if (texto === SQL_CRIAR_CANAL) {
        const erro = new Error("duplicate key") as Error & { code: string; constraint: string };
        erro.code = "23505";
        erro.constraint = "tenant_channels_alguma_outra_uq";
        throw erro;
      }
      return original(texto, valores);
    };
    await assert.rejects(
      () => servico.ligar(entradaDeEnsaio()),
      (erro: unknown) => erro instanceof Error && !(erro instanceof NumeroJaUsadoError),
    );
  });

  /**
   * **A falha injectada no passo 4 do `01` §13.2 — a subscrição —, e os 0
   * recursos órfãos do critério 7.**
   */
  it("a falha no passo 4 deixa 0 recursos orfaos", async () => {
    const { servico, sql, graph, cofre, metricas } = montar();
    graph.falharNaSubscricao = true;
    await assert.rejects(() => servico.ligar(entradaDeEnsaio()), /recusou a subscrição/);
    assert.deepEqual(sql.recursos, []);
    assert.equal(sql.canaisApagados, 1);
    assert.deepEqual(cofre.revogados.length, 1);
    assert.equal(cofre.segredos.size, 0);
    assert.equal(sql.fase, "falhado");
    assert.equal(sql.limpou, 1);
    assert.equal(metricas.valor('es_onboarding_compensado_total{recurso="token"}'), 1);
    assert.equal(metricas.valor('es_onboarding_compensado_total{recurso="canal"}'), 1);
  });

  it("a confirmacao incompleta falha e compensa, incluindo a subscricao", async () => {
    const { servico, sql, graph, cofre } = montar();
    graph.confirmacao = CAMPOS_DE_WEBHOOK.filter((c) => c !== "smb_message_echoes");
    await assert.rejects(() => servico.ligar(entradaDeEnsaio()), SubscricaoIncompletaError);
    assert.equal(graph.anulacoes, 1);
    assert.deepEqual(graph.subscritos, []);
    assert.equal(sql.canaisApagados, 1);
    assert.equal(cofre.segredos.size, 0);
    assert.deepEqual(sql.recursos, []);
  });

  /**
   * **A igualdade é de conjuntos, e não de cardinalidade** — e os três testes de
   * confirmação que havia não distinguiam as duas, porque todos usavam conjuntos
   * de tamanho **diferente** de onze (dez campos, ou nenhum). Trocar o portão
   * por uma contagem (`obtidos.length !== CAMPOS_DE_WEBHOOK.length`) levantava
   * nos três, e a mutação `onboarding: a confirmacao passa a comparar so o
   * tamanho` sobreviveu à noite de 2026-10-26.
   *
   * A igualdade de conjuntos **está** provada, mas na altitude errada: o
   * `describe("os onze campos e a igualdade de conjuntos (criterio 5)")` chama o
   * `compararCampos` **directamente**, e a mutação não lhe toca — ela tira a
   * decisão de lá e põe-na numa contagem no chamador. Por isso estes dois casos
   * passam pelo **serviço**.
   *
   * Os dois desfechos que divergem, um em cada sentido.
   */
  it("uma troca de igual cardinalidade na confirmacao falha e compensa", async () => {
    const { servico, graph, cofre } = montar();
    graph.confirmacao = [...CAMPOS_DE_WEBHOOK.filter((c) => c !== "history"), "flows"];
    assert.equal(
      graph.confirmacao.length,
      CAMPOS_DE_WEBHOOK.length,
      "a fixture tem de ter a mesma cardinalidade, senao o caso nao distingue nada",
    );
    await assert.rejects(() => servico.ligar(entradaDeEnsaio()), SubscricaoIncompletaError);
    assert.equal(graph.anulacoes, 1);
    assert.equal(cofre.segredos.size, 0);
  });

  it("um duplicado na confirmacao nao compensa um onboarding sao", async () => {
    const { servico, graph } = montar();
    graph.confirmacao = [...CAMPOS_DE_WEBHOOK, CAMPOS_DE_WEBHOOK[0]];
    // Não levanta: o conjunto é o mesmo, e um duplicado na resposta da Meta não
    // é um campo a mais. Com a contagem, levantava — e compensava um
    // onboarding são, que é o lado mais caro de errar.
    await servico.ligar(entradaDeEnsaio());
    assert.equal(graph.anulacoes, 0);
  });

  /**
   * **A ordem inversa não é arbitrária.** O `anularSubscricao` precisa do *token*
   * em claro, e o *token* está cifrado no cofre; se a revogação dele corresse
   * primeiro, não haveria com que desfazer a subscrição.
   */
  it("a compensacao desfaz pela ordem inversa: a subscricao antes do token", async () => {
    const { servico, sql, graph, cofre } = montar();
    graph.confirmacao = [];
    await assert.rejects(() => servico.ligar(entradaDeEnsaio()), SubscricaoIncompletaError);
    const anular = graph.chamadas.lastIndexOf("anularSubscricao");
    assert.ok(anular >= 0);
    // A subscrição desfez-se **e** o *token* foi revogado depois — o que prova a
    // ordem é a subscrição ter sido anulada com sucesso: ela precisa do *token*,
    // que ainda existia.
    assert.equal(graph.anulacoes, 1);
    assert.equal(cofre.revogados.length, 1);
  });

  it("uma compensacao que falha nao esvazia a lista nem apaga o resto", async () => {
    const { servico, sql, graph, cofre } = montar();
    graph.confirmacao = [];
    graph.anularSubscricao = async () => {
      throw new Error("a Meta nao respondeu ao DELETE");
    };
    await assert.rejects(() => servico.ligar(entradaDeEnsaio()), SubscricaoIncompletaError);
    // A lista **fica**, para quem retomar saber o que falta desfazer. E o *token*
    // não foi revogado: desfazer o resto sem a subscrição deixava-a pendurada
    // sem forma de a anular.
    assert.deepEqual(
      sql.recursos.map((r) => r.recurso),
      ["token", "canal", "subscricao"],
    );
    assert.equal(sql.limpou, 0);
    assert.deepEqual(cofre.revogados, []);
  });

  it("revogar duas vezes resolve: a compensacao e retomavel", async () => {
    const { servico, sql, cofre } = montar();
    await servico.ligar(entradaDeEnsaio());
    const id = sql.aberta?.id ?? "";
    sql.fase = "subscrito";
    await servico.compensar(id, TENANT, "primeira passagem");
    const revogados = cofre.revogados.length;
    // Segunda passagem: a lista já está vazia, e nada rebenta.
    await servico.compensar(id, TENANT, "segunda passagem");
    assert.equal(cofre.revogados.length, revogados);
  });

  /**
   * **A fase vai a `falhado` antes de a lista se esvaziar**, e a ordem é uma
   * restrição da base: o `SQL_LIMPAR_RECURSOS` põe o `channel_id` a `NULL`, e o
   * `channel_onboarding_canal_ck` recusa-o nas seis fases do meio. A primeira
   * versão limpava primeiro e levantava `23514` no **último** passo da
   * compensação — depois de ter desfeito tudo o que havia a desfazer.
   */
  it("a compensacao transita antes de limpar, e a ordem e da base", async () => {
    const { servico, sql, graph } = montar();
    graph.falharNaSubscricao = true;
    await assert.rejects(() => servico.ligar(entradaDeEnsaio()), /recusou a subscrição/);
    const transicao = sql.chamadas.lastIndexOf(SQL_TRANSITAR);
    const limpeza = sql.chamadas.lastIndexOf(SQL_LIMPAR_RECURSOS);
    assert.ok(transicao >= 0, "a transicao para falhado devia ter corrido");
    assert.ok(limpeza >= 0, "a limpeza devia ter corrido");
    assert.ok(transicao < limpeza, "a transicao tem de vir antes da limpeza");
  });

  /**
   * **A cadeia das três restrições da base**, e a ordem das três é toda dela:
   *
   *     1. fase → `falhado`      (o `canal_ck` passa a admitir o nulo)
   *     2. `channel_id` → NULL   (a FK larga o canal)
   *     3. `DELETE` do canal     (deixa de haver quem o aponte)
   *
   * A primeira versão da compensação fazia só o 3, e o `23503` abortava a
   * transacção **no último passo** — depois de a subscrição já estar anulada. O
   * comentário de `db/tests/test_inventario.py` tinha previsto isto por escrito
   * antes de o código existir: a análise estava certa e o código não a seguia.
   */
  it("a compensacao larga o canal antes de o apagar, na ordem que a base impoe", async () => {
    const { servico, sql, graph } = montar();
    graph.falharNaSubscricao = true;
    await assert.rejects(() => servico.ligar(entradaDeEnsaio()), /recusou a subscrição/);
    // **A transacção não ficou abortada**: nem o `canal_ck` nem a FK mordem.
    assert.equal(sql.abortada, false);
    assert.equal(sql.canaisApagados, 1);
    assert.equal(sql.canalApontado, null);
    const soltar = sql.chamadas.indexOf(SQL_SOLTAR_CANAL);
    const apagar = sql.chamadas.indexOf(SQL_APAGAR_CANAL);
    const transitar = sql.chamadas.indexOf(SQL_TRANSITAR);
    assert.ok(transitar >= 0 && transitar < soltar, "a transicao vem antes de largar");
    assert.ok(soltar >= 0 && soltar < apagar, "largar vem antes de apagar");
  });

  it("os quatro recursos sao os quatro passos com efeito fora da transaccao", () => {
    assert.deepEqual([...RECURSOS], ["token", "pin", "canal", "subscricao"]);
  });

  it("os tres motivos de recusa sao os tres que recusam antes de criar recursos", () => {
    assert.deepEqual([...MOTIVOS_DE_RECUSA], [
      "es_nao_e_v4",
      "numero_de_outro_tenant",
      "limite_7d",
    ]);
  });

  it("a varredura dos abandonados chama o SQL com o prazo em minutos", async () => {
    const { servico, sql } = montar();
    assert.equal(await servico.abandonarVencidas(), 0);
    assert.ok(sql.chamadas.includes(SQL_ABANDONAR));
  });

  it("o registo da recusa e uma escrita propria, fora da transaccao do 409", async () => {
    const { servico, sql } = montar();
    await servico.registarRecusa(entradaDeEnsaio(), "phone_number_id de outro tenant");
    assert.equal(sql.recusas, 1);
  });
});

// ------------------------------------------------------------------- métricas

describe("as metricas do onboarding", () => {
  it("o gauge da janela nao leva etiqueta e vale -1 antes da primeira medicao", () => {
    const m = new Metricas();
    assert.equal(m.valor("es_onboardings_7d"), -1);
    m.medir("es_onboardings_7d", 3);
    assert.equal(m.valor("es_onboardings_7d"), 3);
  });

  it("a exposicao cala-se enquanto nao houver medicao", () => {
    assert.equal(new Metricas().exposicao(), "");
  });

  it("a exposicao nao expoe o -1: um gauge de clientes negativo mentia", () => {
    const m = new Metricas();
    m.contar("es_onboarding_recusado_total", "limite_7d");
    const texto = m.exposicao();
    assert.ok(!texto.includes("-1"));
    assert.ok(texto.includes('es_onboarding_recusado_total{motivo="limite_7d"} 1'));
    assert.ok(texto.includes("# TYPE es_onboarding_recusado_total counter"));
  });

  it("medirPorFase reescreve as nove series, incluindo as que ficam a zero", () => {
    const m = new Metricas();
    m.medirPorFase({ iniciado: 2, falhado: 1 });
    assert.equal(m.valor('es_onboarding_fase{fase="iniciado"}'), 2);
    assert.equal(m.valor('es_onboarding_fase{fase="ativo"}'), 0);
    for (const fase of FASES) {
      assert.notEqual(m.valor(`es_onboarding_fase{fase="${fase}"}`), -1);
    }
  });

  it("uma etiqueta fora do dominio levanta, e nao cria serie", () => {
    const m = new Metricas();
    assert.throws(() => m.contar("es_onboarding_recusado_total", "inventado"));
    assert.equal(m.exposicao(), "");
  });

  it("o gauge da janela nao aceita etiqueta por medirPorFase", () => {
    const m = new Metricas();
    assert.throws(() => m.medir("es_onboarding_fase", 1));
  });

  it("nenhuma metrica leva etiqueta de tenant", () => {
    const m = new Metricas();
    m.medir("es_onboardings_7d", 1);
    m.medirPorFase({ iniciado: 1 });
    m.contar("es_onboarding_compensado_total", "token");
    m.contar("es_onboarding_recusado_total", "limite_7d");
    // O `OBS-I` de `docs/seguranca/ameacas_stride.md` recusa identificadores em
    // etiquetas, e um UUID com hífenes **levanta** nas bibliotecas da casa.
    assert.ok(!m.exposicao().includes("tenant"));
  });
});

// ------------------------------------------------------- KAM-207: a religação

/** Um canal de `TENANT` que caiu, com o número da entrada de ensaio e um *token* antigo no cofre. */
async function comCanalCaido(m: ReturnType<typeof montar>, tenant = TENANT) {
  const tokenRef = await m.cofre.cunhar(FAMILIA_DO_TOKEN, "criptograma-antigo");
  m.cofre.cunhados.length = 0;
  const id = randomUUID();
  m.sql.caido = { id, tenant, pnid: entradaDeEnsaio().phone_number_id, tokenRef, estado: "desligado", waba: entradaDeEnsaio().waba_id };
  return { id, tokenRef };
}

/** A tentativa original do `(TENANT, waba)`, já subscrita, a apontar para o canal. */
function tentativaOriginal(m: ReturnType<typeof montar>, canalId: string, fase: Fase = "subscrito") {
  const e = entradaDeEnsaio();
  m.sql.jaExistia = true;
  m.sql.fase = fase;
  m.sql.linhas.set(e.waba_id, {
    id: randomUUID(),
    tenant_id: TENANT,
    channel_id: canalId,
    waba_id: e.waba_id,
    waac_id: null,
    phone_number_id: e.phone_number_id,
    fase,
    recursos_criados: [],
    pin_ref: null,
    motivo: null,
  });
}

describe("KAM-207: religar o numero de um canal que caiu", () => {
  it("integracao: o mesmo numero no mesmo WABA volta por iniciado e o canal volta a ativo", async () => {
    const m = montar();
    const caido = await comCanalCaido(m);
    tentativaOriginal(m, caido.id);
    const { tentativa, novo } = await m.servico.ligar(entradaDeEnsaio({ code: "AQB-code-da-religacao" }));
    assert.equal(novo, true);
    assert.equal(tentativa.fase, "subscrito");
    assert.equal(tentativa.channel_id, caido.id);
    // A matriz: `subscrito → falhado → iniciado`, e nunca um salto por cima dela.
    const fases = m.sql.chamadas.filter((t) => t === SQL_TRANSITAR || t === SQL_REABRIR);
    assert.deepEqual(fases.slice(0, 2), [SQL_TRANSITAR, SQL_REABRIR]);
    // **Nenhum canal novo**: o `SQL_CRIAR_CANAL` daria o 409 contra a linha do proprio tenant.
    assert.ok(!m.sql.chamadas.includes(SQL_CRIAR_CANAL));
    assert.equal(m.sql.canalApontado, caido.id);
    assert.equal(m.sql.caido?.estado, "ativo");
    assert.equal(m.sql.caido?.tokenRef, m.cofre.cunhados[0]);
    assert.deepEqual(m.graph.subscritos.slice().sort(), [...CAMPOS_DE_WEBHOOK].sort());
    // O canal nao entra na lista: nao foi esta tentativa que o criou.
    assert.deepEqual(m.sql.recursos.map((r) => r.recurso), ["token", "subscricao"]);
    // E o token antigo revoga-se depois de o canal mudar de referencia.
    assert.deepEqual(m.cofre.revogados, [caido.tokenRef]);
  });

  it("integracao: o mesmo numero noutro WABA abre uma tentativa nova e leva o WABA ao canal", async () => {
    const m = montar();
    const caido = await comCanalCaido(m);
    const { novo } = await m.servico.ligar(entradaDeEnsaio({ code: "AQB-code-da-religacao", waba_id: "waba-novo-de-ensaio" }));
    assert.equal(novo, true);
    assert.ok(!m.sql.chamadas.includes(SQL_REABRIR));
    assert.ok(!m.sql.chamadas.includes(SQL_CRIAR_CANAL));
    assert.equal(m.sql.caido?.estado, "ativo");
    assert.equal(m.sql.caido?.waba, "waba-novo-de-ensaio");
    assert.equal(m.sql.canalApontado, caido.id);
  });

  it("adversarial: uma falha na subscricao compensa o que a religacao criou e deixa o canal como caiu", async () => {
    const m = montar();
    const caido = await comCanalCaido(m);
    tentativaOriginal(m, caido.id);
    m.graph.falharNaSubscricao = true;
    await assert.rejects(m.servico.ligar(entradaDeEnsaio({ code: "AQB-code-da-religacao" })));
    assert.equal(m.sql.caido?.estado, "desligado");
    assert.equal(m.sql.caido?.tokenRef, caido.tokenRef);
    // O token novo e revogado; o antigo nao; e o canal **nunca** e apagado.
    assert.deepEqual(m.cofre.revogados, [m.cofre.cunhados[0]]);
    assert.equal(m.sql.canaisApagados, 0);
    assert.ok(!m.sql.chamadas.includes(SQL_APAGAR_CANAL));
    assert.equal(m.sql.fase, "falhado");
  });

  it("adversarial: o numero de outro tenant nao religa, e da o 409 sem tocar no canal dele", async () => {
    const m = montar();
    await comCanalCaido(m, OUTRO_TENANT);
    m.sql.numeroDeOutroTenant = true;
    await assert.rejects(m.servico.ligar(entradaDeEnsaio({ code: "AQB-code-da-religacao" })), NumeroJaUsadoError);
    assert.equal(m.sql.caido?.estado, "desligado");
    assert.equal(m.sql.caido?.tenant, OUTRO_TENANT);
    assert.ok(!m.sql.chamadas.includes(SQL_RELIGAR_CANAL));
  });

  it("adversarial: o mesmo code outra vez nao reabre, e nao fala com a Meta", async () => {
    const m = montar();
    const caido = await comCanalCaido(m);
    tentativaOriginal(m, caido.id, "falhado");
    m.sql.reabre = false;
    await assert.rejects(m.servico.ligar(entradaDeEnsaio()), EsNaoEV4Error);
    assert.ok(!m.graph.chamadas.includes("trocarCode"));
    assert.equal(m.sql.caido?.estado, "desligado");
  });

  it("adversarial: uma tentativa em ativo e terminal, e a religacao nao passa por cima da matriz", async () => {
    const m = montar();
    const caido = await comCanalCaido(m);
    tentativaOriginal(m, caido.id, "ativo");
    await assert.rejects(m.servico.ligar(entradaDeEnsaio({ code: "AQB-code-da-religacao" })), TransicaoInvalidaError);
    assert.ok(!m.graph.chamadas.includes("trocarCode"));
    assert.ok(!m.sql.chamadas.includes(SQL_REABRIR));
  });

  it("um canal que ja nao esta desligado segue o caminho de sempre e devolve a repeticao", async () => {
    const m = montar();
    const caido = await comCanalCaido(m);
    tentativaOriginal(m, caido.id);
    if (m.sql.caido !== null) m.sql.caido = { ...m.sql.caido, estado: "ativo" };
    const { novo } = await m.servico.ligar(entradaDeEnsaio({ code: "AQB-code-da-religacao" }));
    assert.equal(novo, false);
    assert.ok(!m.graph.chamadas.includes("trocarCode"));
  });
});
