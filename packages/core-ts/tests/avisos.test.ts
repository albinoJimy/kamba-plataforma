/**
 * O aviso ao dono por canal alternativo, contra uma base falsa (KAM-115).
 *
 * O que esta bateria prova, e é o que uma base falsa **pode** provar: as regras.
 * Os cinco gatilhos e a recusa do sexto (critério 1), a idempotência por
 * episódio (critério 2), a latência medida com relógio na mão (critério 3), os
 * dois limites de frequência e os lembretes (critério 4), a lista branca de
 * modelos e o varrimento de 200 avisos (critério 5), o alerta do tenant sem
 * contacto (critério 6), o *bounce* (critério 7) e a configuração sem WhatsApp
 * (critério 8).
 *
 * O que **não** se prova aqui e está no `tests_bd/avisos.bd.test.ts`: que o
 * `ON CONFLICT DO NOTHING` deduplica sob concorrência real, que o
 * `owner_notices_lembrete_ck` recusa o quarto lembrete, e que as três varreduras
 * correm sem contexto de tenant. Uma base falsa não lê o texto do SQL, e por
 * isso não pode provar nada do que o servidor decide — é a lição que o KAM-020 e
 * o KAM-018 escreveram.
 *
 * ## A base falsa é um `Map` e as instruções reconhecem-se pelo texto
 *
 * Não se interpreta SQL: compara-se cada consulta com a constante do
 * `src/avisos/consultas.ts` que ela devia ser, e **falha** numa que não conheça.
 * É a forma do `coexistencia.base_falsa.ts` do KAM-017, e a razão é a mesma: uma
 * base falsa que aceite qualquer cadeia deixa passar uma consulta trocada, e o
 * teste continua verde a provar o caminho errado.
 */

import assert from "node:assert/strict";
import { describe, it } from "node:test";

import {
  ATRASO_DO_LEMBRETE_MS,
  AvisoAoDono,
  CanalDesconhecidoError,
  CanalDuplicadoError,
  CANAIS,
  chaveDoEpisodio,
  condenaOEndereco,
  confirmacaoValida,
  contactoUtilizavel,
  construir,
  decidir,
  ESTADOS_NO_TEXTO,
  EstadoInvalidoError,
  GATILHOS,
  gatilhoConhecido,
  horaDeLuanda,
  gatilhosComModelo,
  JANELA_DIARIA_MS,
  JANELA_DO_GATILHO_MS,
  LATENCIA_ALVO_MS,
  LIMIAR_DO_PAINEL_MS,
  marcadoresDosModelos,
  lembreteDevido,
  lembretesEsgotados,
  LEMBRETE_MAXIMO,
  mascarar,
  MASCARA,
  MAXIMO_DA_LOJA,
  METRICA_ENVIADOS,
  METRICA_FALHADOS,
  METRICA_SUPRIMIDOS,
  MetricasDoAviso,
  MOTIVOS_DE_INVALIDEZ,
  OCTETOS_DE_RESUMO,
  OCTETOS_DO_TOKEN,
  PainelInvalidoError,
  PARAMETROS,
  ParametroInvalidoError,
  precisaDeEndereco,
  prepararLoja,
  PRAZO_DA_CONFIRMACAO_MS,
  resumoDoToken,
  SQL_CONFIRMAR,
  SQL_CONTACTO,
  SQL_EMITIR_CONFIRMACAO,
  SQL_ENTREGUE,
  SQL_FALHOU,
  SQL_HISTORICO,
  SQL_INVALIDAR,
  SQL_NOME_DA_LOJA,
  SQL_REGISTAR,
  SQL_TENANTS_ATIVOS,
  SQL_TENANTS_SEM_CONTACTO,
  TECTO_DIARIO,
  type Aviso,
  type Canal,
  type MotivoDeFalha,
  type Notificador,
  type ResultadoDaEntrega,
  AMBIENTE_BLOQUEANTE,
  DeclaracaoInvalidaError,
  FORNECEDOR_PENDENTE,
  fornecedorDeEmail,
  FornecedorSemApdRefError,
  PAIS_SEM_TRANSFERENCIA,
  VARIAVEIS,
} from "../src/avisos/index.ts";
import { DIGITOS_MAXIMOS } from "../src/logger/politica.ts";

const TENANT = "11111111-1111-4111-8111-111111111111";
const PAINEL = "https://painel.kamba.ao/canal";
const T0 = new Date("2026-11-09T09:00:00.000Z");
const CIFRA = new Uint8Array(40).fill(1);

/** O endereço que a `Decifrar` falsa devolve. Nunca sai daqui para a base. */
const ENDERECO = "dono@loja.co.ao";

interface LinhaDeAviso {
  /**
   * A chave, em texto. **Na base e uma coluna `bytea`**; aqui e o que a base
   * falsa compara, e e por isso que esta no tipo: um campo que o despachante
   * usa e o tipo nao declara e um campo que o compilador nao protege.
   */
  chaveHex: string;
  id: string;
  tenant_id: string;
  gatilho: string;
  episodio: string;
  lembrete: number;
  canal: string;
  estado: string;
  tentativas: number;
  falha_motivo: string | null;
  criado_at: Date;
  entregue_at: Date | null;
}

interface LinhaDeContacto {
  /**
   * O resumo da confirmacao, em texto. Na base e `confirmacao_hash`.
   *
   * `| undefined` explicito por causa do `exactOptionalPropertyTypes`: com ele
   * ligado, «a propriedade pode faltar» e «a propriedade pode valer
   * `undefined`» sao coisas diferentes, e a base falsa **escreve** `undefined`
   * ao gastar o *token*.
   */
  resumo?: string | undefined;
  /** O prazo da confirmacao. Na base e `confirmacao_expira_em`. Ver acima. */
  expira?: Date | undefined;
  id: string;
  tenant_id: string;
  canal: string;
  endereco_enc: Uint8Array;
  verificado_at: Date | null;
  invalido_at: Date | null;
  motivo_invalido: string | null;
}

/**
 * A base falsa: um `Map` de avisos e um de contactos.
 *
 * Reconhece as instruções **pelo texto** e levanta numa que não conheça. Ver a
 * nota do módulo.
 */
class BaseFalsa {
  readonly avisos: LinhaDeAviso[] = [];
  readonly contactos: LinhaDeContacto[] = [];
  readonly consultas: string[] = [];
  nome: string | null = "Loja do Zé";
  ativos = 1;

  #id = 0;

  async query<T = Record<string, unknown>>(
    texto: string,
    valores: readonly unknown[] = [],
  ): Promise<{ readonly rows: readonly T[] }> {
    this.consultas.push(texto);
    const rows = this.#despachar(texto, valores);
    return { rows: rows as readonly T[] };
  }

  #despachar(texto: string, v: readonly unknown[]): readonly unknown[] {
    if (texto === SQL_HISTORICO) {
      const desde = v[1] as Date;
      return this.avisos
        .filter((a) => a.tenant_id === v[0] && a.criado_at > desde)
        .sort((a, b) => b.criado_at.getTime() - a.criado_at.getTime());
    }
    if (texto === SQL_REGISTAR) {
      const chave = (v[3] as Uint8Array).toString();
      const existe = this.avisos.some(
        (a) =>
          a.tenant_id === v[0] &&
          a.lembrete === v[4] &&
          a.canal === v[5] &&
          a.chaveHex === chave,
      );
      // `ON CONFLICT DO NOTHING`: zero linhas na segunda passagem, e e assim que
      // quem chama sabe se escreveu — sem uma leitura anterior que uma corrida
      // podia invalidar entre a leitura e a escrita.
      if (existe || this.conflitoNoRegisto) return [];
      this.#id += 1;
      const linha: LinhaDeAviso = {
        chaveHex: chave,
        id: `aviso-${this.#id}`,
        tenant_id: v[0] as string,
        gatilho: v[1] as string,
        episodio: v[2] as string,
        lembrete: v[4] as number,
        canal: v[5] as string,
        estado: "pendente",
        tentativas: 0,
        falha_motivo: null,
        // **Do parametro e nao do `this.agora`**: o `criado_at` passou a vir de
        // quem chama (ver a nota do `SQL_REGISTAR`), e uma base falsa que o
        // continuasse a inventar escondia exactamente o defeito que o fez
        // mudar — a janela do criterio 4 a medir uma hora e a linha a ter
        // outra.
        criado_at: v[6] as Date,
        entregue_at: null,
      };
      this.avisos.push(linha);
      return [linha];
    }
    if (texto === SQL_ENTREGUE) {
      const linha = this.avisos.find((a) => a.id === v[1] && a.estado === "pendente");
      if (linha === undefined) return [];
      linha.estado = "entregue";
      linha.entregue_at = v[2] as Date;
      linha.tentativas += 1;
      return [linha];
    }
    if (texto === SQL_FALHOU) {
      const linha = this.avisos.find((a) => a.id === v[1] && a.estado !== "entregue");
      if (linha === undefined) return [];
      linha.estado = "falhado";
      linha.falha_motivo = v[2] as string;
      linha.tentativas += 1;
      return [linha];
    }
    if (texto === SQL_CONTACTO) {
      return this.contactos.filter((c) => c.tenant_id === v[0] && c.canal === v[1]);
    }
    if (texto === SQL_INVALIDAR) {
      const linha = this.contactos.find(
        (c) => c.tenant_id === v[0] && c.canal === v[1] && c.invalido_at === null,
      );
      if (linha === undefined) return [];
      linha.motivo_invalido = v[2] as string;
      linha.invalido_at = v[3] as Date;
      return [linha];
    }
    if (texto === SQL_EMITIR_CONFIRMACAO) {
      const linha = this.contactos.find((c) => c.tenant_id === v[0] && c.canal === v[1]);
      if (linha === undefined) return [];
      linha.resumo = (v[2] as Uint8Array).toString();
      linha.expira = v[3] as Date;
      linha.verificado_at = null;
      linha.invalido_at = null;
      linha.motivo_invalido = null;
      return [linha];
    }
    if (texto === SQL_CONFIRMAR) {
      const agora = v[3] as Date;
      const linha = this.contactos.find(
        (c) =>
          c.tenant_id === v[0] &&
          c.canal === v[1] &&
          c.resumo === (v[2] as Uint8Array).toString() &&
          c.expira !== undefined &&
          c.expira > agora,
      );
      if (linha === undefined) return [];
      linha.verificado_at = agora;
      linha.resumo = undefined;
      linha.expira = undefined;
      return [linha];
    }
    if (texto === SQL_NOME_DA_LOJA) {
      return this.nome === null ? [] : [{ nome: this.nome }];
    }
    if (texto === SQL_TENANTS_SEM_CONTACTO) {
      const comContacto = new Set(
        this.contactos
          .filter((c) => c.verificado_at !== null && c.invalido_at === null)
          .map((c) => c.tenant_id),
      );
      return comContacto.has(TENANT) ? [] : [{ id: TENANT }];
    }
    if (texto === SQL_TENANTS_ATIVOS) {
      return [{ quantos: this.ativos }];
    }
    throw new Error(`a base falsa nao conhece esta instrucao:\n${texto}`);
  }

  agora = T0;

  /**
   * Quando `true`, o `SQL_REGISTAR` devolve zero linhas **sem** o histórico as
   * mostrar.
   *
   * É a corrida real do critério 2, e é o único caminho por onde o
   * `registado === null` do módulo se alcança: duas transacções lêem «ainda não
   * avisei» as duas — logo o `decidir` autoriza as duas — e a unicidade deixa
   * passar **uma**. A prova por mutação mostrou que nenhum teste o exercitava: em
   * série o `decidir` tapa o caminho, porque na segunda chamada o histórico já
   * tem a linha e a recusa é `ja_avisado`.
   */
  conflitoNoRegisto = false;

  /** Semeia um contacto verificado e utilizável. */
  comContactoVerificado(): this {
    this.contactos.push({
      id: "contacto-1",
      tenant_id: TENANT,
      canal: "email",
      endereco_enc: CIFRA,
      verificado_at: new Date(T0.getTime() - 1_000),
      invalido_at: null,
      motivo_invalido: null,
    });
    return this;
  }

  /** Semeia um contacto que ninguém confirmou. */
  comContactoNaoVerificado(): this {
    this.contactos.push({
      id: "contacto-1",
      tenant_id: TENANT,
      canal: "email",
      endereco_enc: CIFRA,
      verificado_at: null,
      invalido_at: null,
      motivo_invalido: null,
    });
    return this;
  }
}

/** Um notificador que entrega sempre. */
class Entrega implements Notificador {
  readonly entregas: { destino: string | null; assunto: string; corpo: string }[] = [];

  readonly canal: Canal;

  constructor(canal: Canal) {
    this.canal = canal;
  }

  async entregar(destino: string | null, aviso: {
    readonly assunto: string;
    readonly corpo: string;
  }): Promise<ResultadoDaEntrega> {
    this.entregas.push({ destino, assunto: aviso.assunto, corpo: aviso.corpo });
    return { entregue: true, motivo: null };
  }
}

/** Um notificador que falha sempre, com o motivo que lhe derem. */
class Falha implements Notificador {
  tentativas = 0;
  readonly canal: Canal;
  readonly motivo: MotivoDeFalha;

  constructor(canal: Canal, motivo: MotivoDeFalha) {
    this.canal = canal;
    this.motivo = motivo;
  }

  async entregar(): Promise<ResultadoDaEntrega> {
    this.tentativas += 1;
    return { entregue: false, motivo: this.motivo };
  }
}

/**
 * O cenario de um teste.
 *
 * O `relogio` e **mutavel e o mesmo objecto** que a porta do relogio le. A
 * primeira versao devolvia uma copia (`{ ...montagem, aviso }`), e o resultado
 * era que mexer no `relogio` do objecto devolvido nao mexia no que a instancia
 * lia: os testes das 24 h e das 72 h mediam sempre o instante `T0` e passavam
 * por nao haver nada no historico. Um teste de relogio que nao mexe o relogio e
 * um teste que prova que a funcao nao falha.
 */
class Cenario {
  relogio = T0;
  readonly tarefas: { tenantId: string; assunto: string }[] = [];
  readonly metricas = new MetricasDoAviso();
  readonly aviso: AvisoAoDono;
  readonly base: BaseFalsa;
  readonly email: Notificador;
  readonly painel: Notificador;

  constructor(base: BaseFalsa, email: Notificador, painel: Notificador) {
    this.base = base;
    this.email = email;
    this.painel = painel;
    this.aviso = new AvisoAoDono({
      notificadores: [email, painel],
      decifrar: () => ENDERECO,
      abrirTarefa: async (pedido) => {
        this.tarefas.push({ tenantId: pedido.tenantId, assunto: pedido.assunto });
      },
      relogio: () => {
        this.base.agora = this.relogio;
        return this.relogio;
      },
      novoToken: () => new Uint8Array(OCTETOS_DO_TOKEN).fill(7),
      painel: PAINEL,
      metricas: this.metricas,
    });
  }
}

function montar(opcoes: {
  readonly base?: BaseFalsa;
  readonly email?: Notificador;
  readonly painel?: Notificador;
} = {}): Cenario {
  return new Cenario(
    opcoes.base ?? new BaseFalsa().comContactoVerificado(),
    opcoes.email ?? new Entrega("email"),
    opcoes.painel ?? new Entrega("painel"),
  );
}

/**
 * O gatilho na posição `i`, ciclicamente.
 *
 * Função e não `GATILHOS[i % GATILHOS.length]` directo por causa do
 * `noUncheckedIndexedAccess`: um índice num *array* devolve `T | undefined`, e
 * o tipo tem razão — o que não tem razão é espalhar `assert.ok` por cada uso.
 * Num sítio só, e com a falha a dizer o que falhou.
 */
function gatilhoDoIndice(i: number): (typeof GATILHOS)[number] {
  const gatilho = GATILHOS[i % GATILHOS.length];
  if (gatilho === undefined) throw new Error(`sem gatilho para ${i}`);
  return gatilho;
}

/** O atraso do lembrete `i`, pela mesma razão do `gatilhoDoIndice`. */
function atraso(i: number): number {
  const valor = ATRASO_DO_LEMBRETE_MS[i];
  if (valor === undefined) throw new Error(`sem atraso para o lembrete ${i}`);
  return valor;
}

/** O primeiro contacto semeado, pela mesma razão do `gatilhoDoIndice`. */
function contactoSemeado(base: BaseFalsa): LinhaDeContacto {
  const linha = base.contactos[0];
  if (linha === undefined) throw new Error("a base falsa nao tem contacto semeado");
  return linha;
}

/** O elemento `i` de uma lista de ensaio, pela mesma razão. */
function daLista<T>(lista: readonly T[], i: number): T {
  const valor = lista[i % lista.length];
  if (valor === undefined) throw new Error(`sem elemento para ${i}`);
  return valor;
}

function avisoAnterior(troca: Partial<Aviso> = {}): Aviso {
  return {
    id: "antigo",
    tenantId: TENANT,
    gatilho: "canal_desligado",
    episodio: "ep-1",
    lembrete: 0,
    canal: "email",
    estado: "entregue",
    tentativas: 1,
    falhaMotivo: null,
    criadoAt: T0,
    entregueAt: T0,
    ...troca,
  };
}

// ============================================================ critério 1

describe("os cinco gatilhos, e o sexto que não existe", () => {
  it("há cinco gatilhos e cinco modelos, um por gatilho", () => {
    assert.equal(GATILHOS.length, 5);
    assert.deepEqual([...gatilhosComModelo()].sort(), [...GATILHOS].sort());
  });

  it("**os seis motivos de PARTNER_REMOVED são um gatilho só, e episódios diferentes**", () => {
    // O criterio 1 escreve «(cada um dos 6 motivos de `PARTNER_REMOVED`)», e o
    // que ele pede e que os seis **gerem** aviso — nao que gerem seis textos. O
    // passo seguinte e o mesmo nos seis (reconectar pelo painel), e seis
    // modelos iguais eram seis sitios para a mesma frase divergir. O que
    // distingue um `change_number` de um `primary_inactivity` e o `episodio`,
    // e e isso que faz o segundo desligamento ser avisado.
    const motivos = [
      "primary_inactivity",
      "companion_inactivity",
      "business_downgrade",
      "change_number",
      "user_re_registered",
      "account_disconnected",
    ];
    const chaves = new Set(
      motivos.map((motivo) =>
        chaveDoEpisodio(TENANT, "canal_desligado", `canal-1:${motivo}`).toString("hex"),
      ),
    );
    assert.equal(chaves.size, 6);
  });

  it("um gatilho fora da lista não envia nada", async () => {
    const { aviso, base, metricas, email } = montar();
    const resultado = await aviso.notificar(base as never, {
      tenantId: TENANT,
      gatilho: "canal_lento" as never,
      episodio: "ep-1",
    });
    assert.equal(resultado.suprimido, "gatilho_desconhecido");
    assert.deepEqual(resultado.avisos, []);
    assert.equal(base.avisos.length, 0);
    assert.equal((email as Entrega).entregas.length, 0);
    // Conta com a etiqueta `nenhum`, porque por definicao o gatilho nao e um
    // dos cinco. Sem ela, a recusa que o criterio 1 manda era a unica que nao
    // se podia contar.
    assert.equal(
      metricas.ler()[`${METRICA_SUPRIMIDOS}|nenhum|gatilho_desconhecido`],
      1,
    );
  });

  it("o `gatilhoConhecido` recusa o que não é cadeia", () => {
    for (const mau of [null, undefined, 7, {}, [], "", "CANAL_DESLIGADO"]) {
      assert.equal(gatilhoConhecido(mau), false, JSON.stringify(mau));
    }
    for (const bom of GATILHOS) assert.equal(gatilhoConhecido(bom), true);
  });

  it("**os cinco gatilhos passam a gramática do `outcome`**", () => {
    // A licao que o `sem_humano_24h` do KAM-018 pagou e a `0018` repetiu: estes
    // valores sao tambem `outcome` de linha de registo, e **em modo estrito —
    // que e o do CI — o `Logger` levanta** um valor que a gramatica recuse. Um
    // `painel_indisponível` com acento era um aviso normal a virar excepcao nao
    // tratada no caminho de um webhook. Mede-se, nao se promete.
    for (const gatilho of GATILHOS) {
      assert.match(gatilho, /^[a-z]+(_[a-z]+)*$/, gatilho);
      assert.equal(/[^\x20-\x7e]/.test(gatilho), false, gatilho);
    }
  });

  it("os cinco gatilhos geram aviso, cada um com o seu texto e o seu passo", async () => {
    const vistos = new Set<string>();
    for (const gatilho of GATILHOS) {
      const { aviso, base, email } = montar();
      const resultado = await aviso.notificar(base as never, {
        tenantId: TENANT,
        gatilho,
        episodio: `ep-${gatilho}`,
      });
      assert.equal(resultado.suprimido, null);
      const entrega = (email as Entrega).entregas[0];
      assert.ok(entrega !== undefined, gatilho);
      vistos.add(entrega.assunto);
    }
    // Cinco assuntos **diferentes**: «cada um com texto proprio» (criterio 1).
    assert.equal(vistos.size, 5);
  });
});

// ============================================================ critério 2

describe("a idempotência por episódio", () => {
  it("o mesmo evento 3× produz 1 aviso por canal", async () => {
    const { aviso, base, email, painel } = montar();
    for (let i = 0; i < 3; i += 1) {
      await aviso.notificar(base as never, {
        tenantId: TENANT,
        gatilho: "canal_desligado",
        episodio: "ep-1",
      });
    }
    assert.equal(base.avisos.length, 2); // um por canal
    assert.equal((email as Entrega).entregas.length, 1);
    assert.equal((painel as Entrega).entregas.length, 1);
  });

  it("**a re-entrega pela DLQ não gasta o tecto diário**", async () => {
    // A ordem das recusas: o `ja_avisado` vem **antes** dos limites, e nao e
    // detalhe. Com os limites primeiro, tres entregas do mesmo evento
    // consumiam o dia todo do dono e os outros gatilhos calavam-se — um dono
    // com o canal desligado **e** o pagamento em falta sabia do primeiro tres
    // vezes e do segundo nunca.
    const historico = [avisoAnterior(), avisoAnterior({ canal: "painel" })];
    const decisao = decidir(T0, "canal_desligado", "ep-1", 0, historico);
    assert.deepEqual(decisao, { avisar: false, motivo: "ja_avisado" });
  });

  it("um episódio novo depois de resolvido produz outro aviso", () => {
    const historico = [avisoAnterior({ episodio: "ep-1" })];
    const decisao = decidir(
      new Date(T0.getTime() + JANELA_DO_GATILHO_MS + 1),
      "canal_desligado",
      "ep-2",
      0,
      historico,
    );
    assert.deepEqual(decisao, { avisar: true, motivo: null });
  });

  it("a chave leva o tenant dentro, e dois tenants não colidem", () => {
    const outro = "22222222-2222-4222-8222-222222222222";
    const a = chaveDoEpisodio(TENANT, "canal_desligado", "ep-1");
    const b = chaveDoEpisodio(outro, "canal_desligado", "ep-1");
    assert.equal(a.length, OCTETOS_DE_RESUMO);
    assert.notEqual(a.toString("hex"), b.toString("hex"));
  });

  it("**o separador é o octeto nulo, e não um ponto**", () => {
    // A licao do `prova.ts` do KAM-022: com um separador que possa aparecer nos
    // campos, dois trios diferentes davam a mesma cadeia. Aqui o `episodio` e o
    // unico campo livre, e um `episodio` com dois-pontos e o caso normal —
    // `canal-1:primary_inactivity`.
    const a = chaveDoEpisodio(TENANT, "canal_desligado", "x:y");
    const b = chaveDoEpisodio(TENANT, "canal_desligado", "x").toString("hex");
    assert.notEqual(a.toString("hex"), b);
    // E dois episodios que, colados ao gatilho, dariam a mesma cadeia com um
    // separador fraco, continuam a dar chaves diferentes.
    const c = chaveDoEpisodio(TENANT, "inactividade", "a");
    // O `"inactivid"` nao e um gatilho, e e de proposito: o que se mede e a
    // funcao de resumo e nao a lista fechada — um gatilho a mais no teste dava
    // uma chave que o `decidir` nunca produziria.
    const d = chaveDoEpisodio(TENANT, "inactivid" as never, "adea");
    assert.notEqual(c.toString("hex"), d.toString("hex"));
  });
});

// ============================================================ critério 3

describe("a latência do evento ao aviso", () => {
  it("mede-se com o relógio na mão, e entra no histograma", async () => {
    const montagem = montar();
    const ocorridoEm = new Date(T0.getTime() - 90_000);
    await montagem.aviso.notificar(montagem.base as never, {
      tenantId: TENANT,
      gatilho: "canal_desligado",
      episodio: "ep-1",
      ocorridoEm,
    });
    const lidas = montagem.metricas.ler();
    // Dois canais, duas observacoes, 90 s cada.
    assert.equal(lidas["owner_notice_latency_s_count"], 2);
    assert.equal(lidas["owner_notice_latency_s_sum"], 180);
  });

  it("**o corte dos 300 s existe para o p95 se ler sem interpolar**", () => {
    const metricas = new MetricasDoAviso();
    metricas.observarLatencia(299);
    metricas.observarLatencia(301);
    const linhas = metricas.exposicao();
    assert.match(linhas, /owner_notice_latency_s_bucket\{le="300"\} 1/);
    assert.match(linhas, /owner_notice_latency_s_bucket\{le="600"\} 2/);
  });

  it("uma latência negativa não entra — é um relógio ao contrário", () => {
    const metricas = new MetricasDoAviso();
    metricas.observarLatencia(-1);
    metricas.observarLatencia(Number.NaN);
    assert.equal(metricas.ler()["owner_notice_latency_s_count"], 0);
  });

  it("sem `ocorridoEm` não se inventa latência", async () => {
    const montagem = montar();
    await montagem.aviso.notificar(montagem.base as never, {
      tenantId: TENANT,
      gatilho: "canal_desligado",
      episodio: "ep-1",
    });
    assert.equal(montagem.metricas.ler()["owner_notice_latency_s_count"], 0);
  });
});

// ============================================================ critério 4

describe("os limites de frequência e os lembretes", () => {
  it("≤ 1 aviso por (tenant, gatilho) em 24 h", () => {
    const historico = [avisoAnterior({ episodio: "ep-1" })];
    const dentro = decidir(
      new Date(T0.getTime() + JANELA_DO_GATILHO_MS - 1),
      "canal_desligado",
      "ep-2",
      0,
      historico,
    );
    assert.equal(dentro.motivo, "janela_do_gatilho");
    const fora = decidir(
      new Date(T0.getTime() + JANELA_DO_GATILHO_MS),
      "canal_desligado",
      "ep-2",
      0,
      historico,
    );
    assert.equal(fora.avisar, true);
  });

  it("**a janela do gatilho vem antes do tecto diário, e a ordem é medida**", () => {
    // Com o tecto primeiro, um tenant com tres episodios do mesmo gatilho
    // gastava o dia todo num gatilho so, e os outros quatro ficavam sem voz
    // para as 24 h seguintes. Com a janela primeiro, o segundo episodio do
    // mesmo gatilho e recusado **sem gastar nada do tecto**.
    const historico = [avisoAnterior({ episodio: "ep-1" })];
    const segundo = decidir(T0, "canal_desligado", "ep-2", 0, historico);
    assert.equal(segundo.motivo, "janela_do_gatilho");
    // E o tecto continua inteiro: outro gatilho passa.
    const outro = decidir(T0, "sem_pagamento", "ep-9", 0, historico);
    assert.equal(outro.avisar, true);
  });

  it("≤ 3 avisos por tenant por dia", () => {
    const historico = [
      avisoAnterior({ gatilho: "canal_desligado", episodio: "a" }),
      avisoAnterior({ gatilho: "inactividade", episodio: "b" }),
      avisoAnterior({ gatilho: "qualidade_restrita", episodio: "c" }),
    ];
    const quarto = decidir(T0, "sem_pagamento", "d", 0, historico);
    assert.equal(quarto.motivo, "tecto_diario");
    assert.equal(TECTO_DIARIO, 3);
  });

  it("**o tecto conta avisos e não linhas**", () => {
    // Um aviso sai pelos dois canais e e **um** aviso. Contar duas linhas fazia
    // o tecto de tres valer um e meio, e um dono com tres problemas sabia de
    // um.
    const historico = [
      avisoAnterior({ gatilho: "canal_desligado", episodio: "a", canal: "email" }),
      avisoAnterior({ gatilho: "canal_desligado", episodio: "a", canal: "painel" }),
      avisoAnterior({ gatilho: "inactividade", episodio: "b", canal: "email" }),
      avisoAnterior({ gatilho: "inactividade", episodio: "b", canal: "painel" }),
    ];
    // Quatro linhas, dois avisos: o terceiro gatilho ainda passa.
    const terceiro = decidir(T0, "qualidade_restrita", "c", 0, historico);
    assert.equal(terceiro.avisar, true);
  });

  it("o dia é corrido e não civil", () => {
    const historico = [
      avisoAnterior({ gatilho: "canal_desligado", episodio: "a" }),
      avisoAnterior({ gatilho: "inactividade", episodio: "b" }),
      avisoAnterior({ gatilho: "qualidade_restrita", episodio: "c" }),
    ];
    // Um dia civil fazia o tecto reiniciar a meia-noite e um dono avisado tres
    // vezes as 23 h levava outros tres uma hora depois.
    const quase = decidir(
      new Date(T0.getTime() + JANELA_DIARIA_MS - 1),
      "sem_pagamento",
      "d",
      0,
      historico,
    );
    assert.equal(quase.motivo, "tecto_diario");
    const depois = decidir(
      new Date(T0.getTime() + JANELA_DIARIA_MS),
      "sem_pagamento",
      "d",
      0,
      historico,
    );
    assert.equal(depois.avisar, true);
  });

  it("500 eventos numa hora de um só tenant enviam ≤ 3 avisos", async () => {
    const montagem = montar();
    for (let i = 0; i < 500; i += 1) {
      montagem.relogio = new Date(T0.getTime() + i * 7_000);
      await montagem.aviso.notificar(montagem.base as never, {
        tenantId: TENANT,
        gatilho: gatilhoDoIndice(i),
        episodio: `ep-${i}`,
      });
    }
    const avisosDistintos = new Set(
      montagem.base.avisos.map((a) => `${a.gatilho}:${a.episodio}:${a.lembrete}`),
    );
    assert.ok(
      avisosDistintos.size <= TECTO_DIARIO,
      `sairam ${avisosDistintos.size} avisos distintos`,
    );
    // E o que se recusou **conta-se**: recusar sem contar e recusar em
    // silencio, e sem a serie um painel nao distingue a regra a funcionar do
    // canal alternativo quebrado.
    const suprimidos = Object.entries(montagem.metricas.ler())
      .filter(([nome]) => nome.startsWith(`${METRICA_SUPRIMIDOS}|`))
      .reduce((soma, [, valor]) => soma + valor, 0);
    assert.ok(suprimidos > 400, `contaram-se ${suprimidos} supressoes`);
  });

  it("**um lembrete não é recusado pela janela do gatilho**", () => {
    // Achado da revisao adversarial deste ticket. Um lembrete e, por
    // definicao, um segundo aviso do mesmo gatilho dentro das 24 h — e a
    // primeira versao filtrava os dois, pelo que os lembretes **nunca saiam**.
    // O teste que afirmava o contrario media o lembrete das 24 h num historico
    // vazio, onde a janela nao tem nada para recusar.
    const historico = [avisoAnterior({ episodio: "ep-1", lembrete: 0 })];
    const lembrete = decidir(
      new Date(T0.getTime() + atraso(0)),
      "canal_desligado",
      "ep-1",
      1,
      historico,
    );
    assert.equal(lembrete.avisar, true, JSON.stringify(lembrete));
    // E o aviso proprio, no mesmo instante e no mesmo episodio, **e** recusado.
    const proprio = decidir(
      new Date(T0.getTime() + atraso(0)),
      "canal_desligado",
      "ep-1",
      0,
      historico,
    );
    assert.equal(proprio.motivo, "ja_avisado");
  });

  it("o mesmo lembrete duas vezes é recusado", () => {
    const historico = [avisoAnterior({ episodio: "ep-1", lembrete: 1 })];
    const outra = decidir(T0, "canal_desligado", "ep-1", 1, historico);
    assert.equal(outra.motivo, "ja_avisado");
  });

  it("os lembretes são às 24 h e às 72 h, e depois param", () => {
    assert.deepEqual([...ATRASO_DO_LEMBRETE_MS], [86_400_000, 259_200_000]);
    assert.equal(lembreteDevido(T0, T0), null);
    assert.equal(lembreteDevido(new Date(T0.getTime() + 23 * 3_600_000), T0), null);
    assert.equal(lembreteDevido(new Date(T0.getTime() + 24 * 3_600_000), T0), 1);
    assert.equal(lembreteDevido(new Date(T0.getTime() + 71 * 3_600_000), T0), 1);
    assert.equal(lembreteDevido(new Date(T0.getTime() + 72 * 3_600_000), T0), 2);
    assert.equal(lembreteDevido(new Date(T0.getTime() + 500 * 3_600_000), T0), 2);
  });

  it("**devolve o lembrete mais alto devido, e não o seguinte ao enviado**", () => {
    // Um processo que esteve em baixo entre as 24 h e as 72 h nao deve mandar
    // os dois lembretes de seguida ao voltar. Quem ja foi enviado sabe-se da
    // base, e e la que a repeticao e recusada.
    assert.equal(lembreteDevido(new Date(T0.getTime() + 100 * 3_600_000), T0), 2);
  });

  it("«já acabou» e «ainda não é hora» não são a mesma resposta", () => {
    // Juntar os dois num `null` ambiguo fazia esperar e abrir tarefa a T2
    // terem o mesmo gatilho — e as duas coisas sao opostas.
    assert.equal(lembretesEsgotados(T0, T0, 0), false);
    assert.equal(lembretesEsgotados(T0, T0, LEMBRETE_MAXIMO), false);
    assert.equal(
      lembretesEsgotados(new Date(T0.getTime() + 72 * 3_600_000), T0, LEMBRETE_MAXIMO),
      true,
    );
    assert.equal(
      lembretesEsgotados(new Date(T0.getTime() + 72 * 3_600_000), T0, 1),
      false,
    );
  });

  it("um lembrete acima do máximo é recusado antes de chegar à base", () => {
    const decisao = decidir(T0, "canal_desligado", "ep-1", LEMBRETE_MAXIMO + 1, []);
    assert.equal(decisao.motivo, "lembretes_esgotados");
  });
});

// ============================================================ critério 5

describe("a lista branca de modelos e o conteúdo", () => {
  it("os quatro parâmetros são os do critério, e não há mais", () => {
    assert.deepEqual([...PARAMETROS], ["loja", "estado", "hora", "painel"]);
  });

  it("um parâmetro fora da lista levanta", () => {
    assert.throws(
      () =>
        construir("canal_desligado", {
          loja: "L",
          estado: "restrito",
          hora: "h",
          painel: PAINEL,
          telefone: "+244923456789",
        } as never),
      ParametroInvalidoError,
    );
  });

  it("**a recusa é antes de preencher, e não dentro**", () => {
    // Com a recusa so dentro do `preencher`, um parametro a mais que nenhum
    // modelo usasse passava sem ser visto — e o que entrava sem ser visto era o
    // que o criterio 5 proibe. O `inactividade` nao usa `{estado}`: e o modelo
    // onde isto se ve.
    assert.throws(
      () =>
        construir("inactividade", {
          loja: "L",
          estado: "restrito",
          hora: "h",
          painel: PAINEL,
          contact_id: "11111111-1111-4111-8111-111111111111",
        } as never),
      ParametroInvalidoError,
    );
  });

  it("o nome da loja mascara telefones em vez de recusar o aviso", () => {
    // Recusar fazia o dono nao saber que o canal caiu por causa de **como ele
    // escreveu o nome da loja** — castiga-lo por um defeito nosso.
    assert.equal(prepararLoja("Loja do Zé 923 456 789"), `Loja do Zé ${MASCARA}`);
    assert.equal(prepararLoja("Loja 923456789"), `Loja ${MASCARA}`);
    assert.equal(prepararLoja("Loja 923-456-789"), `Loja ${MASCARA}`);
  });

  it("**a fronteira é o `DIGITOS_MAXIMOS` da casa e não um número novo**", () => {
    assert.equal(DIGITOS_MAXIMOS, 6);
    // Seis digitos passam — e uma referencia de pagamento tem seis.
    assert.equal(mascarar("ref 123456"), "ref 123456");
    // Sete nao.
    assert.equal(mascarar("ref 1234567"), `ref ${MASCARA}`);
  });

  it("o nome da loja é truncado", () => {
    const longo = "a".repeat(MAXIMO_DA_LOJA + 50);
    assert.equal(prepararLoja(longo).length, MAXIMO_DA_LOJA);
  });

  it("a ligação ao painel não leva token nem identificador", () => {
    for (const mau of [
      `${PAINEL}?token=abc`,
      `${PAINEL}#t=abc`,
      `${PAINEL}?tenant=${TENANT}`,
      "http://painel.kamba.ao",
      "",
    ]) {
      assert.throws(
        () =>
          new AvisoAoDono({
            notificadores: [],
            decifrar: () => ENDERECO,
            abrirTarefa: async () => {},
            relogio: () => T0,
            painel: mau,
          }),
        PainelInvalidoError,
        mau,
      );
    }
  });

  it("o estado no texto vem de uma lista fechada", () => {
    assert.deepEqual([...ESTADOS_NO_TEXTO], ["restrito", "desligado", "suspenso"]);
  });

  it("um estado fora da lista levanta", async () => {
    const { aviso, base } = montar();
    await assert.rejects(
      aviso.notificar(base as never, {
        tenantId: TENANT,
        gatilho: "qualidade_restrita",
        episodio: "ep-1",
        estado: "a_verificar" as never,
      }),
      EstadoInvalidoError,
    );
  });

  it("**o varrimento de 200 avisos não encontra nada do que o critério proíbe**", async () => {
    // «0 telefones, `contact_id`, BSUID ou texto de clientes (varrimento X-11
    // sobre 200 avisos gerados)». Os 200 variam o gatilho, o estado, a hora e o
    // nome da loja — e os nomes de loja incluem telefones, NIF e IBAN escritos
    // de todas as maneiras em que uma pessoa os escreve.
    const nomes = [
      "Loja do Zé",
      "Loja do Zé 923456789",
      "Mercearia 923 456 789",
      "Padaria +244 923 456 789",
      "Boutique NIF 5417123456",
      "Café AO06 0040 0000 1234 5678 9017",
      "Farmácia 923-456-789",
      "Quiosque 923.456.789",
      "Oficina 24 Horas",
      "Loja 7",
    ];
    const gerados: string[] = [];
    for (let i = 0; i < 200; i += 1) {
      const texto = construir(gatilhoDoIndice(i), {
        loja: daLista(nomes, i),
        estado: daLista(ESTADOS_NO_TEXTO, i),
        // **A funcao do modulo e nao uma copia dela.** Com uma copia, este
        // varrimento provava o formato que o teste escolheu — e foi
        // exactamente isso que aconteceu: o modulo passou a hora para
        // `Africa/Luanda` e o teste continuou a gerar ISO, pelo que ele
        // falhou a dizer que o aviso levava uma corrida de digitos que o
        // aviso real nao leva.
        hora: horaDeLuanda(new Date(T0.getTime() + i * 61_000)),
        painel: PAINEL,
      });
      gerados.push(`${texto.assunto}\n${texto.corpo}`);
    }
    assert.equal(gerados.length, 200);
    for (const [indice, aviso] of gerados.entries()) {
      // Nenhuma corrida de sete ou mais digitos, em qualquer arrumacao: e a
      // mesma regua do `logger/politica.ts`, que apanha o telefone, o NIF e o
      // IBAN sem procurar o formato de cada um.
      //
      // **E varre-se o aviso inteiro, sem excepcao nenhuma.** A primeira versao
      // tinha de tirar a hora antes de varrer, porque ela saia em ISO
      // (`2026-11-09T09:00:00.000Z`) e os digitos dela disparavam a regua. A
      // hora passou a sair na forma longa de `Africa/Luanda` — «9 de novembro de
      // 2026 as 10:00» —, onde nenhuma corrida chega a sete, e a excepcao
      // desapareceu: um varrimento sem excepcoes e mais forte do que um com.
      assert.equal(
        /(?:\d[ .\-/]*){7,}/.test(aviso),
        false,
        `aviso ${indice}: ${aviso}`,
      );
      // Nenhum UUID — nem `tenant_id`, nem `contact_id`.
      assert.equal(
        /[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}/i.test(aviso),
        false,
        `aviso ${indice}`,
      );
      // Nenhum BSUID: a forma que a Meta documenta e `PT.` e mais alfanumericos.
      assert.equal(/\bPT\.[A-Za-z0-9]{8,}/.test(aviso), false, `aviso ${indice}`);
      // E nenhum marcador por preencher, que era um defeito nosso a sair em
      // texto para o cliente.
      assert.equal(/\{[a-z]+\}/.test(aviso), false, `aviso ${indice}`);
    }
  });

  it("todos os modelos dizem o passo seguinte", () => {
    for (const gatilho of GATILHOS) {
      const texto = construir(gatilho, {
        loja: "Loja",
        estado: "restrito",
        hora: "h",
        painel: PAINEL,
      });
      assert.ok(texto.passo.length > 10, gatilho);
      // E o corpo leva o passo dentro: um aviso que diz que algo esta mal e nao
      // diz o que fazer e um aviso que o dono nao pode usar.
      assert.ok(texto.corpo.includes(texto.passo), gatilho);
    }
  });
});

// ============================================================ critério 6

describe("o contacto alternativo verificado", () => {
  it("um contacto não verificado não recebe avisos", () => {
    assert.equal(contactoUtilizavel(null), false);
    assert.equal(
      contactoUtilizavel({
        id: "c",
        tenantId: TENANT,
        canal: "email",
        enderecoEnc: CIFRA,
        verificadoAt: null,
        invalidoAt: null,
        motivoInvalido: null,
      }),
      false,
    );
  });

  it("**um contacto verificado que deu *bounce* não serve**", () => {
    // As duas condicoes e nao uma: um endereco verificado que depois deu
    // *bounce* **esta** verificado e nao serve.
    assert.equal(
      contactoUtilizavel({
        id: "c",
        tenantId: TENANT,
        canal: "email",
        enderecoEnc: CIFRA,
        verificadoAt: T0,
        invalidoAt: T0,
        motivoInvalido: "bounce",
      }),
      false,
    );
  });

  it("um tenant sem contacto verificado abre tarefa a T2 e conta", async () => {
    const base = new BaseFalsa().comContactoNaoVerificado();
    const montagem = montar({ base });
    const resultado = await montagem.aviso.notificar(base as never, {
      tenantId: TENANT,
      gatilho: "canal_desligado",
      episodio: "ep-1",
    });
    assert.equal(resultado.tarefaAberta, true);
    assert.equal(montagem.tarefas.length, 1);
    assert.match(daLista(montagem.tarefas, 0).assunto, /sem contacto alternativo/);
    assert.equal(
      montagem.metricas.ler()[`${METRICA_FALHADOS}|email|sem_contacto`],
      1,
    );
    // **E o painel sai de qualquer maneira**: exigir contacto para o painel
    // fazia todos os tenants sem e-mail ficarem tambem sem a notificacao que o
    // criterio 7 manda usar como reserva.
    assert.equal((montagem.painel as Entrega).entregas.length, 1);
  });

  it("**o `sem_contacto` não marca o contacto como inválido**", () => {
    // Nao ha contacto a marcar, e e por isso que ele nao esta nos
    // `MOTIVOS_DE_INVALIDEZ`. Um `sem_contacto` tratado como `bounce` marcava
    // como invalido um endereco que nao existe.
    assert.deepEqual([...MOTIVOS_DE_INVALIDEZ], ["bounce", "rejeitado"]);
    assert.equal(condenaOEndereco("sem_contacto"), false);
    assert.equal(condenaOEndereco("indisponivel"), false);
    assert.equal(condenaOEndereco("bounce"), true);
    assert.equal(condenaOEndereco("rejeitado"), true);
  });

  it("a varredura publica o numerador **e** o denominador", async () => {
    const base = new BaseFalsa();
    base.ativos = 20;
    const montagem = montar({ base });
    const sem = await montagem.aviso.varrerContactos(base as never);
    assert.deepEqual(sem, [TENANT]);
    const lidas = montagem.metricas.ler();
    // Uma percentagem precisa de denominador: com o numerador sozinho, «doze
    // tenants sem contacto» nao se distingue de catastrofe nem de ruido.
    assert.equal(lidas["owner_alt_contact_missing"], 1);
    assert.equal(lidas["owner_alt_contact_missing_total"], 20);
  });

  it("o painel não precisa de endereço e o e-mail precisa", () => {
    assert.equal(precisaDeEndereco("email"), true);
    assert.equal(precisaDeEndereco("painel"), false);
  });

  it("a ligação de confirmação vale sete dias e confirma uma vez", async () => {
    const base = new BaseFalsa().comContactoNaoVerificado();
    const montagem = montar({ base });
    const { token, expiraEm } = await montagem.aviso.emitirConfirmacao(base as never, TENANT);
    assert.equal(token.length, OCTETOS_DO_TOKEN);
    assert.equal(expiraEm.getTime() - T0.getTime(), PRAZO_DA_CONFIRMACAO_MS);
    assert.equal(await montagem.aviso.confirmar(base as never, TENANT, token), true);
    assert.notEqual(contactoSemeado(base).verificado_at, null);
    // E o *token* usado nao se reutiliza: deixa-lo na coluna era deixar uma
    // ligacao eterna a espera de quem a encontrasse num e-mail antigo.
    assert.equal(await montagem.aviso.confirmar(base as never, TENANT, token), false);
  });

  it("um token errado não confirma", async () => {
    const base = new BaseFalsa().comContactoNaoVerificado();
    const montagem = montar({ base });
    await montagem.aviso.emitirConfirmacao(base as never, TENANT);
    const errado = new Uint8Array(OCTETOS_DO_TOKEN).fill(9);
    assert.equal(await montagem.aviso.confirmar(base as never, TENANT, errado), false);
    assert.equal(contactoSemeado(base).verificado_at, null);
  });

  it("uma ligação expirada não confirma", async () => {
    const base = new BaseFalsa().comContactoNaoVerificado();
    const montagem = montar({ base });
    const { token } = await montagem.aviso.emitirConfirmacao(base as never, TENANT);
    montagem.relogio = new Date(T0.getTime() + PRAZO_DA_CONFIRMACAO_MS + 1);
    assert.equal(await montagem.aviso.confirmar(base as never, TENANT, token), false);
  });

  it("**emitir uma confirmação nova repõe o `verificado_at` a nulo**", () => {
    // O ponto mais facil de errar: sem a reposicao, um endereco trocado herdava
    // a verificacao do anterior — e o criterio 6 passava a dizer que um e-mail
    // que ninguem confirmou esta confirmado.
    assert.match(SQL_EMITIR_CONFIRMACAO, /verificado_at = NULL/);
    assert.match(SQL_EMITIR_CONFIRMACAO, /invalido_at = NULL/);
  });

  it("o `confirmacaoValida` expira no instante exacto", () => {
    assert.equal(confirmacaoValida(T0, null), false);
    assert.equal(confirmacaoValida(T0, T0), false);
    assert.equal(confirmacaoValida(T0, new Date(T0.getTime() + 1)), true);
  });

  it("o resumo do token tem 32 octetos e não é o token", () => {
    const token = new Uint8Array(OCTETOS_DO_TOKEN).fill(7);
    const resumo = resumoDoToken(token);
    assert.equal(resumo.length, OCTETOS_DE_RESUMO);
    assert.notEqual(resumo.toString("hex"), Buffer.from(token).toString("hex"));
  });
});

// ============================================================ critério 7

describe("a falha de entrega", () => {
  it("um *bounce* marca o contacto como inválido e abre tarefa a T2", async () => {
    const base = new BaseFalsa().comContactoVerificado();
    const montagem = montar({ base, email: new Falha("email", "bounce") });
    const resultado = await montagem.aviso.notificar(base as never, {
      tenantId: TENANT,
      gatilho: "canal_desligado",
      episodio: "ep-1",
    });
    assert.equal(resultado.tarefaAberta, true);
    assert.equal(contactoSemeado(base).motivo_invalido, "bounce");
    assert.notEqual(contactoSemeado(base).invalido_at, null);
    assert.equal(
      montagem.metricas.ler()[`${METRICA_FALHADOS}|email|bounce`],
      1,
    );
  });

  it("**e o painel entrega, que é o «tenta o painel» do critério**", async () => {
    const base = new BaseFalsa().comContactoVerificado();
    const montagem = montar({ base, email: new Falha("email", "bounce") });
    await montagem.aviso.notificar(base as never, {
      tenantId: TENANT,
      gatilho: "canal_desligado",
      episodio: "ep-1",
    });
    assert.equal((montagem.painel as Entrega).entregas.length, 1);
    assert.equal(
      montagem.metricas.ler()[`${METRICA_ENVIADOS}|canal_desligado|painel`],
      1,
    );
  });

  it("um fornecedor em baixo **não** condena o endereço", async () => {
    const base = new BaseFalsa().comContactoVerificado();
    const montagem = montar({ base, email: new Falha("email", "indisponivel") });
    await montagem.aviso.notificar(base as never, {
      tenantId: TENANT,
      gatilho: "canal_desligado",
      episodio: "ep-1",
    });
    // Marcar o contacto por uma avaria nossa era deixar o dono sem canal
    // alternativo por uma razao que nada tem a ver com o endereco.
    assert.equal(contactoSemeado(base).invalido_at, null);
    // Mas abre tarefa: nenhum aviso se perde em silencio.
    assert.equal(montagem.tarefas.length, 1);
  });

  it("nenhum aviso se perde em silêncio: a falha fica registada na linha", async () => {
    const base = new BaseFalsa().comContactoVerificado();
    const montagem = montar({ base, email: new Falha("email", "rejeitado") });
    await montagem.aviso.notificar(base as never, {
      tenantId: TENANT,
      gatilho: "canal_desligado",
      episodio: "ep-1",
    });
    const doEmail = base.avisos.find((a) => a.canal === "email");
    assert.equal(doEmail?.estado, "falhado");
    assert.equal(doEmail?.falha_motivo, "rejeitado");
    assert.equal(doEmail?.tentativas, 1);
  });

  it("um aviso entregue não volta a mover o instante de entrega", () => {
    // Sem o `estado = 'pendente'` no predicado, uma segunda confirmacao do
    // fornecedor movia o `entregue_at` para a frente e a latencia do criterio 3
    // passava a medir a confirmacao mais recente em vez da primeira entrega.
    assert.match(SQL_ENTREGUE, /AND estado = 'pendente'/);
  });

  it("**um aviso `entregue` não passa a `falhado`, e um `falhado` pode voltar a falhar**", () => {
    // A assimetria com o `SQL_ENTREGUE` e de proposito: uma entrega pode falhar
    // depois de uma primeira falha — e o que a coluna `tentativas` conta.
    assert.match(SQL_FALHOU, /AND estado <> 'entregue'/);
    assert.equal(/estado = 'pendente'/.test(SQL_FALHOU), false);
  });

  it("a invalidação guarda o **primeiro** motivo", () => {
    // Sem o `invalido_at IS NULL`, um segundo *bounce* reescrevia a data e a
    // pergunta «desde quando e que este dono esta sem canal?» mudava de
    // resposta a cada tentativa.
    assert.match(SQL_INVALIDAR, /AND invalido_at IS NULL/);
  });
});

// ============================================================ critério 8

describe("a configuração: nunca pelo WhatsApp", () => {
  it("os canais são dois, e o WhatsApp não é um deles", () => {
    assert.deepEqual([...CANAIS], ["email", "painel"]);
    assert.equal((CANAIS as readonly string[]).includes("whatsapp"), false);
  });

  it("o SMS **não** está pré-declarado", () => {
    // «O SMS fica atras da interface `SmsProvider` de KAM-116 e so se activa
    // quando esse contrato existir.» Um nome sem superficie e o que o gate 3b
    // recusa, e o `ARRAY_DOS_ECHOES` do KAM-017 mostrou o que custa
    // pre-declarar.
    assert.equal((CANAIS as readonly string[]).includes("sms"), false);
  });

  it("um notificador de canal desconhecido é recusado na construção", () => {
    assert.throws(
      () =>
        new AvisoAoDono({
          notificadores: [new Entrega("whatsapp" as never)],
          decifrar: () => ENDERECO,
          abrirTarefa: async () => {},
          relogio: () => T0,
          painel: PAINEL,
        }),
      CanalDesconhecidoError,
    );
  });

  it("dois notificadores para o mesmo canal são recusados", () => {
    // Com o canal fora da interface, nada impedia registar o notificador de
    // e-mail no lugar do painel, e o aviso saia pelo canal errado sem que nada
    // o dissesse.
    assert.throws(
      () =>
        new AvisoAoDono({
          notificadores: [new Entrega("email"), new Entrega("email")],
          decifrar: () => ENDERECO,
          abrirTarefa: async () => {},
          relogio: () => T0,
          painel: PAINEL,
        }),
      CanalDuplicadoError,
    );
  });

  it("**nenhum `import` do módulo vem do `outbound` nem do `entrada`**", async () => {
    // Um teste e nao uma promessa: uma promessa num comentario nao impede
    // ninguem de escrever o `import`. Le-se o texto dos ficheiros, porque e o
    // texto que o compilador le.
    const { readdir, readFile } = await import("node:fs/promises");
    const { fileURLToPath } = await import("node:url");
    const directorio = fileURLToPath(new URL("../src/avisos/", import.meta.url));
    const ficheiros = await readdir(directorio);
    assert.ok(ficheiros.length >= 7, `so ha ${ficheiros.length} ficheiros`);
    for (const ficheiro of ficheiros) {
      const fonte = await readFile(`${directorio}${ficheiro}`, "utf8");
      for (const proibido of ["../outbound", "../entrada", "../med"]) {
        assert.equal(
          fonte.includes(`from "${proibido}`),
          false,
          `${ficheiro} importa de ${proibido}`,
        );
      }
      // E nao ha a palavra `whatsapp` em sitio nenhum do modulo que nao seja
      // uma negacao escrita — mede-se a ausencia de `wamid`, que e o que um
      // adaptador da Meta precisaria.
      assert.equal(fonte.includes("wamid"), false, `${ficheiro} fala de wamid`);
    }
  });
});

// ============================================================ as métricas

describe("as métricas", () => {
  it("uma métrica que não existe levanta", () => {
    const metricas = new MetricasDoAviso();
    assert.throws(() => metricas.contar("owner_notice_total", ["a", "b"]), /desconhecida/);
  });

  it("**um `tenant_id` numa etiqueta levanta**", () => {
    // Decisao escrita (OBS-I), e o KAM-015 e o KAM-023 pagaram-na nos DoD
    // deles: um UUID com hifenes nao passa a gramatica de etiquetas.
    const metricas = new MetricasDoAviso();
    assert.throws(
      () => metricas.contar(METRICA_ENVIADOS, [TENANT, "email"]),
      /lista fechada/,
    );
  });

  it("uma etiqueta a menos levanta", () => {
    // Aceitar uma so fazia `owner_notice_sent_total{gatilho="x"}` conviver com
    // `{gatilho="x",canal="email"}` na mesma recolha: o Prometheus trata-as
    // como series diferentes e a soma deixa de ser o numero de avisos.
    const metricas = new MetricasDoAviso();
    assert.throws(
      () => metricas.contar(METRICA_ENVIADOS, ["canal_desligado"]),
      /lista fechada/,
    );
  });

  it("a exposição leva as duas etiquetas", () => {
    const metricas = new MetricasDoAviso();
    metricas.contar(METRICA_ENVIADOS, ["canal_desligado", "email"]);
    assert.match(
      metricas.exposicao(),
      /owner_notice_sent_total\{gatilho="canal_desligado",canal="email"\} 1/,
    );
  });

  it("as contagens de contacto recusam valores que não são inteiros", () => {
    const metricas = new MetricasDoAviso();
    metricas.observarContactos(1.5, 2);
    metricas.observarContactos(-1, 2);
    assert.equal(metricas.ler()["owner_alt_contact_missing"], 0);
  });
});

// ============================================ critério 8 — o subprocessador

describe("o fornecedor de e-mail como subprocessador", () => {
  it("por omissão fica `pendente`, e `pendente` avisa fora de `prod`", () => {
    const { subprocessador, avisos } = fornecedorDeEmail({});
    assert.equal(subprocessador.provider, FORNECEDOR_PENDENTE);
    assert.equal(subprocessador.country, PAIS_SEM_TRANSFERENCIA);
    assert.equal(subprocessador.apdRef, null);
    // Fora de `prod` **avisa e nao impede o arranque**: um ambiente de
    // desenvolvimento tem de poder correr contra um fornecedor falso sem
    // papelada.
    assert.equal(avisos.length, 1);
    assert.match(avisos[0] ?? "", /sem KAMBA_AVISO_EMAIL_APD_REF/);
  });

  it("**em `prod`, sem `apd_ref`, o serviço não arranca**", () => {
    // A segunda metade do criterio 8: «ou fica `pendente` e bloqueia `prod`».
    // Levanta, e quem arranca o servico nao tem como continuar sem o resolver —
    // a mesma forma do `DestinoSemApdRefError` do KAM-011.
    assert.throws(
      () => fornecedorDeEmail({ [VARIAVEIS.ambiente]: "prod" }),
      FornecedorSemApdRefError,
    );
    assert.throws(
      () =>
        fornecedorDeEmail({
          [VARIAVEIS.ambiente]: "PROD",
          [VARIAVEIS.provider]: "um-fornecedor",
          [VARIAVEIS.country]: "IE",
        }),
      FornecedorSemApdRefError,
    );
  });

  it("em `prod`, com `apd_ref`, arranca e não avisa", () => {
    const { subprocessador, avisos } = fornecedorDeEmail({
      [VARIAVEIS.ambiente]: "prod",
      [VARIAVEIS.provider]: "um-fornecedor",
      [VARIAVEIS.country]: "ie",
      [VARIAVEIS.apdRef]: "APD/2026/0042",
    });
    assert.equal(subprocessador.country, "IE");
    assert.equal(subprocessador.apdRef, "APD/2026/0042");
    assert.deepEqual(avisos, []);
  });

  it("**um fornecedor escolhido em Angola não precisa de `apd_ref`**", () => {
    // O `gate` existe por causa da **transferencia**, e nao por cerimonia: um
    // fornecedor em Angola nao transfere nada para fora, e exigir-lhe
    // referencia da APD era exigir papelada por um envio que nao sai do pais.
    const { avisos } = fornecedorDeEmail({
      [VARIAVEIS.ambiente]: "prod",
      [VARIAVEIS.provider]: "um-fornecedor-ao",
      [VARIAVEIS.country]: "AO",
    });
    assert.deepEqual(avisos, []);
  });

  it("**mas `pendente` em Angola bloqueia, porque `pendente` não é um sítio**", () => {
    // O caso que o teste acima deixaria passar se o predicado fosse so o pais:
    // o valor por omissao do `country` e `AO`, pelo que um ambiente sem nada
    // declarado teria fornecedor em Angola — e nao tem fornecedor nenhum.
    assert.throws(
      () =>
        fornecedorDeEmail({
          [VARIAVEIS.ambiente]: "prod",
          [VARIAVEIS.country]: "AO",
        }),
      FornecedorSemApdRefError,
    );
  });

  it("uma declaração mal formada levanta e nomeia as variáveis", () => {
    for (const [ambiente, variavel] of [
      [{ [VARIAVEIS.country]: "Angola" }, VARIAVEIS.country],
      [{ [VARIAVEIS.provider]: "1fornecedor" }, VARIAVEIS.provider],
      [{ [VARIAVEIS.apdRef]: "tem espaço" }, VARIAVEIS.apdRef],
    ] as const) {
      assert.throws(
        () => fornecedorDeEmail(ambiente as never),
        (erro: DeclaracaoInvalidaError) => {
          assert.equal(erro.name, "DeclaracaoInvalidaError");
          // A mensagem nomeia a **variavel** e nunca o valor: a razao e a do
          // `storage/config.ts` — uma mensagem de arranque vai para o registo.
          assert.ok(erro.problemas.some((p) => p.includes(variavel)));
          assert.equal(erro.message.includes("Angola"), false);
          return true;
        },
      );
    }
  });

  it("as pontas limpam-se sem `trim()`", () => {
    // O `trim()` do JavaScript e o `strip()` do Python nao tiram os mesmos
    // caracteres, e uma declaracao que passa de um lado e falha do outro e pior
    // do que uma que falha nos dois.
    const { subprocessador } = fornecedorDeEmail({
      [VARIAVEIS.provider]: "  um-fornecedor \t",
      [VARIAVEIS.country]: "\nie\r",
    });
    assert.equal(subprocessador.provider, "um-fornecedor");
    assert.equal(subprocessador.country, "IE");
  });

  it("o ambiente bloqueante é `prod` e mais nenhum", () => {
    assert.equal(AMBIENTE_BLOQUEANTE, "prod");
    for (const ambiente of ["staging", "dev", "producao", "prod-canary"]) {
      const { avisos } = fornecedorDeEmail({ [VARIAVEIS.ambiente]: ambiente });
      assert.equal(avisos.length, 1, ambiente);
    }
  });
});

// =================================== os achados da revisão adversarial

describe("os achados da revisão adversarial", () => {
  it("**a linha de `sem_contacto` entra nos avisos devolvidos**", async () => {
    // Ela **foi escrita**, e o campo está documentado como «as linhas
    // escritas». A primeira versão descartava-a, e o resultado dizia que nada
    // se escreveu num caminho que escreve.
    const base = new BaseFalsa().comContactoNaoVerificado();
    const montagem = montar({ base });
    const resultado = await montagem.aviso.notificar(base as never, {
      tenantId: TENANT,
      gatilho: "canal_desligado",
      episodio: "ep-1",
    });
    const doEmail = resultado.avisos.find((a) => a.canal === "email");
    assert.ok(doEmail !== undefined, "a linha do e-mail nao veio no resultado");
    assert.equal(doEmail.estado, "falhado");
    assert.equal(doEmail.falhaMotivo, "sem_contacto");
    // E a do painel, que entregou, também.
    assert.equal(resultado.avisos.length, 2);
  });

  it("**a hora sai em `Africa/Luanda` e na forma longa**", () => {
    // Em UTC, o aviso dizia a um dono de Luanda que o canal caiu uma hora antes
    // do que caiu. E a forma **longa** e não a curta: `09/11/2026` são oito
    // dígitos separados por barras, e a régua que apanha telefones escritos à
    // mão apanharia a data.
    const texto = construir("canal_desligado", {
      loja: "Loja",
      estado: "desligado",
      hora: horaDeLuanda(T0),
      painel: PAINEL,
    });
    // `T0` é 09:00Z, e Luanda é UTC+1.
    assert.match(texto.corpo, /10:00/);
    assert.equal(/(?:\d[ .\-/]*){7,}/.test(texto.corpo), false, texto.corpo);
  });

  it("o `lembretesEsgotados` é a pergunta que a varredura faz", () => {
    // A primeira versão tinha na varredura um `devido > LEMBRETE_MAXIMO` que
    // **nunca podia ser verdade**, pelo que o «depois pára e abre tarefa a T2»
    // era código morto — e esta função, que existia e estava testada, não era
    // chamada por ninguém.
    const primeiro = T0;
    const setentaEDuas = new Date(T0.getTime() + 72 * 3_600_000);
    assert.equal(lembretesEsgotados(setentaEDuas, primeiro, 2), true);
    assert.equal(lembretesEsgotados(setentaEDuas, primeiro, 1), false);
    assert.equal(lembreteDevido(setentaEDuas, primeiro), 2);
    // E o `lembreteDevido` nunca passa do máximo: era por isso que a guarda
    // antiga era inalcançável.
    assert.equal(lembreteDevido(new Date(T0.getTime() + 1_000 * 3_600_000), primeiro), 2);
  });
});

// ================================= as lacunas que a prova por mutação mostrou

describe("as lacunas que a prova por mutação mostrou", () => {
  it("**a janela do gatilho não morde um lembrete, e a prova precisa de um vizinho**", () => {
    // O teste que afirmava isto media o lembrete das 24 h com o aviso próprio em
    // `T0` — e aí a janela **já tinha expirado** (ela é `[T0, T0+24h)`), pelo que
    // ele passava com o predicado `lembrete === 0` e sem ele. A mutação mostrou-o.
    //
    // O cenário em que a janela **morderia** é outro: o episódio A avisado em
    // `T0`, o lembrete 1 dele em `T0+24h`, um episódio **novo** do mesmo gatilho
    // avisado em `T0+50h` (permitido: a última linha do gatilho é de 26 h antes),
    // e o lembrete 2 de A em `T0+72h`. A linha de `T0+50h` está a 22 h —
    // **dentro** da janela —, pelo que sem o predicado o lembrete 2 era recusado.
    const h = 3_600_000;
    const historico = [
      avisoAnterior({ episodio: "A", lembrete: 0, criadoAt: T0 }),
      avisoAnterior({
        episodio: "A",
        lembrete: 1,
        criadoAt: new Date(T0.getTime() + 24 * h),
      }),
      avisoAnterior({
        episodio: "B",
        lembrete: 0,
        criadoAt: new Date(T0.getTime() + 50 * h),
      }),
    ];
    const agora = new Date(T0.getTime() + 72 * h);
    const lembrete = decidir(agora, "canal_desligado", "A", 2, historico);
    assert.equal(lembrete.avisar, true, JSON.stringify(lembrete));
    // E o controlo: um **aviso próprio** de um terceiro episódio, no mesmo
    // instante, **é** recusado pela janela — senão este teste provava que a
    // janela não existe.
    const proprio = decidir(agora, "canal_desligado", "C", 0, historico);
    assert.equal(proprio.motivo, "janela_do_gatilho");
  });

  it("**os números de produto afirmam-se pelo valor**", () => {
    // Os testes da janela usavam `JANELA_DO_GATILHO_MS` nas duas pontas da
    // fronteira, pelo que eram verdadeiros para **qualquer** valor da constante:
    // uma mutação que a pusesse em 1 h passava. Um número de produto afirma-se
    // pelo número, como o `ATRASO_DO_LEMBRETE_MS` já fazia.
    assert.equal(JANELA_DO_GATILHO_MS, 24 * 60 * 60 * 1_000);
    assert.equal(JANELA_DIARIA_MS, 24 * 60 * 60 * 1_000);
    assert.equal(TECTO_DIARIO, 3);
    assert.equal(LATENCIA_ALVO_MS, 5 * 60 * 1_000);
    assert.equal(LIMIAR_DO_PAINEL_MS, 5 * 60 * 1_000);
    assert.equal(PRAZO_DA_CONFIRMACAO_MS, 7 * 24 * 60 * 60 * 1_000);
  });

  it("**o separador nulo impede a colisão por deslocamento**", () => {
    // O teste anterior comparava `(inactividade, "a")` com `(inactivid, "adea")`,
    // que dão cadeias diferentes **com qualquer separador** — pelo que não
    // provava nada sobre o separador. A colisão real é o deslocamento de uma
    // fronteira: com um ponto, `(a, "b.c")` e `(a.b, "c")` dão a mesma cadeia.
    const esquerda = chaveDoEpisodio(TENANT, "inactividade" as never, "b.c");
    const direita = chaveDoEpisodio(TENANT, "inactividade.b" as never, "c");
    assert.notEqual(esquerda.toString("hex"), direita.toString("hex"));
    // E o mesmo com o separador que um `episodio` real traz, que são
    // dois-pontos: `canal-1:primary_inactivity`.
    const a = chaveDoEpisodio(TENANT, "canal_desligado", "x:y");
    const b = chaveDoEpisodio(TENANT, "canal_desligado:x" as never, "y");
    assert.notEqual(a.toString("hex"), b.toString("hex"));
  });

  it("**nenhum modelo leva um marcador que a lista fechada não tenha**", () => {
    // O invariante que a guarda inalcançável do `preencher` pretendia proteger, e
    // agora afirmado sobre os **cinco modelos** em vez de sobre a chamada que
    // alguém exercitasse. Um `{hroa}` mal escrito sairia literal no e-mail do
    // dono.
    const marcadores = marcadoresDosModelos();
    assert.ok(marcadores.length > 0, "nenhum modelo usa marcador nenhum?");
    for (const marcador of marcadores) {
      assert.ok(
        (PARAMETROS as readonly string[]).includes(marcador),
        `o marcador {${marcador}} nao esta em PARAMETROS`,
      );
    }
  });

  it("**a linha deduplicada por outra transacção não se entrega**", async () => {
    // O caminho do `registado === null`, que **nenhum teste alcançava**: em série
    // o `decidir` recusa primeiro, com `ja_avisado`, e o registo nem é chamado.
    // Aqui o histórico vem vazio — como vem às duas transacções de uma corrida —
    // e é a unicidade que decide.
    const base = new BaseFalsa().comContactoVerificado();
    base.conflitoNoRegisto = true;
    const montagem = montar({ base });
    const resultado = await montagem.aviso.notificar(base as never, {
      tenantId: TENANT,
      gatilho: "canal_desligado",
      episodio: "ep-1",
    });
    // Nada se entregou, por canal nenhum: quem escreveu a linha é quem entrega.
    assert.deepEqual(resultado.avisos, []);
    assert.equal(resultado.suprimido, null);
    assert.equal((montagem.email as Entrega).entregas.length, 0);
    assert.equal((montagem.painel as Entrega).entregas.length, 0);
    // E não se abriu tarefa a T2: não houve falha nenhuma — houve outra
    // transacção a fazer o trabalho.
    assert.equal(montagem.tarefas.length, 0);
  });

  it("**a hora leva o mês por extenso, e é o que exclui as outras duas formas**", () => {
    // A `medium` sai por medição (`09/11/2026` são oito dígitos e a régua
    // apanha-a) e a `short` por legibilidade (`09/11/26` dá o ano em dois
    // dígitos). O mês por extenso é o que distingue a `long` das duas.
    const hora = horaDeLuanda(T0);
    assert.match(hora, /novembro/);
    assert.equal(/\d{2}\/\d{2}\//.test(hora), false, hora);
    // E o ano inteiro: num aviso que o dono pode ler dias depois, a data tem de
    // ser inequívoca.
    assert.match(hora, /2026/);
  });
});
