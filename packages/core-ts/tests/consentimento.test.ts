/**
 * O consentimento no 1.º contacto, sem base de dados (KAM-022).
 *
 * O que **só** aqui se prova, e o que fica para o ensaio contra o PostgreSQL:
 *
 * * aqui: a **matriz** de seis entradas × três estados, célula a célula; a
 *   detecção do «PARAR» com as oito variantes; o `evidence_hash` e a sua
 *   reprodutibilidade; a propriedade do critério 4 (mil mensagens × cinquenta
 *   contactos, zero invocações do AGR sem consentimento); e que nenhuma métrica
 *   leva identificadores;
 * * lá (`tests_bd/consentimento.bd.test.ts`): o *append-only* pelo
 *   **privilégio** (`42501`), a vista `consent_actual` a respeitar a RLS de quem
 *   a consulta, a idempotência pela unicidade da prova sob concorrência, e a
 *   contagem de avisos pelo prefixo da chave contra um planeador.
 *
 * A base falsa daqui responde o que se lhe mandar responder, e é isso que a
 * torna boa para a matriz e inútil para a idempotência.
 */

import assert from "node:assert/strict";
import { describe, it } from "node:test";

import { Logger } from "../src/logger/index.ts";
import {
  ACCOES,
  AVISOS_ANTES_DO_HUMANO,
  BOTOES,
  ConsentGate,
  ESTADOS,
  FINALIDADES,
  LINHAS,
  MARCADOR_DA_LOJA,
  METRICA_ACEITES,
  METRICA_AVISOS,
  METRICA_BARRADAS,
  METRICA_OPTOUT,
  METRICA_RACIO,
  MetricaDesconhecidaError,
  MetricasDoConsentimento,
  PALAVRAS_DE_PARAR,
  SEPARADOR,
  SQL_AVISOS_ENVIADOS,
  SQL_ESTADO,
  SQL_REGISTAR,
  SQL_TEXTO_VIGENTE,
  SufixoInvalidoError,
  accaoDoAviso,
  autorizaAgr,
  enviaMensagem,
  eParar,
  estadoDoConsentimento,
  linhaDaEntrada,
  normalizar,
  preencher,
  provaDeConsentimento,
  registaProva,
  resumoDoTexto,
  type Accao,
  type CorpoDoAviso,
  type DestinoDoAviso,
  type Entrada,
  type EstadoDoConsentimento,
  type Finalidade,
} from "../src/consentimento/index.ts";

const TENANT = "11111111-1111-1111-1111-111111111111";
const CONTACTO = "22222222-2222-2222-2222-222222222222";
const CONVERSA = "33333333-3333-3333-3333-333333333333";
const CANAL = "44444444-4444-4444-4444-444444444444";
const PNID = "pnid-de-ensaio";
const WAMID = "wamid.ENSAIO000001";
const HORA = "2026-11-02T14:03:11.482Z";
const TEXTO = `A ${MARCADOR_DA_LOJA} responde-lhe por um assistente automatico.`;
const LOJA = "Loja de Ensaio";

/**
 * Uma base falsa: responde o guião e guarda as instruções.
 *
 * As provas guardam-se **em hexadecimal**, porque é assim que a unicidade da
 * base funciona (sobre os octetos) e é a única forma de duas chamadas com a
 * mesma prova se reconhecerem aqui.
 */
class BaseFalsa {
  readonly pedidos: string[] = [];
  readonly parametros: unknown[][] = [];
  /** `null` significa «não há versão vigente», que é o estado em que a `0015` nasce. */
  versao: { version: string; texto: string } | null = { version: "v1", texto: TEXTO };
  estado: { accepted: boolean; text_version: string } | null = null;
  avisos = 0;
  readonly provas = new Set<string>();

  async query<T>(texto: string, valores?: readonly unknown[]): Promise<{ rows: readonly T[] }> {
    this.pedidos.push(texto);
    this.parametros.push(valores === undefined ? [] : [...valores]);
    if (texto === SQL_TEXTO_VIGENTE) {
      return { rows: (this.versao === null ? [] : [this.versao]) as unknown as readonly T[] };
    }
    if (texto === SQL_ESTADO) {
      return { rows: (this.estado === null ? [] : [this.estado]) as unknown as readonly T[] };
    }
    if (texto === SQL_AVISOS_ENVIADOS) {
      return { rows: [{ avisos: this.avisos }] as unknown as readonly T[] };
    }
    if (texto === SQL_REGISTAR) {
      // A idempotencia **da base**, imitada: a mesma prova para o mesmo trio
      // nao produz linha. E imitacao e nao prova, e e por isso que o ensaio
      // contra o PostgreSQL existe.
      const prova = valores?.[6];
      const chave = [
        valores?.[0],
        valores?.[1],
        valores?.[2],
        Buffer.from(prova as Uint8Array).toString("hex"),
      ].join("|");
      if (this.provas.has(chave)) return { rows: [] as unknown as readonly T[] };
      this.provas.add(chave);
      return { rows: [{ id: "uma-linha" }] as unknown as readonly T[] };
    }
    // `SQL_NOME_DA_LOJA`
    return { rows: [{ nome: LOJA }] as unknown as readonly T[] };
  }
}

interface Montagem {
  readonly gate: ConsentGate;
  readonly bd: BaseFalsa;
  readonly metricas: MetricasDoConsentimento;
  readonly enviadas: { destino: DestinoDoAviso; corpo: CorpoDoAviso }[];
  readonly emitidos: string[];
  readonly modos: string[];
  readonly registo: Record<string, unknown>[];
}

function montar(
  troca: { readonly envia?: boolean } = {},
): Montagem {
  const bd = new BaseFalsa();
  const metricas = new MetricasDoConsentimento();
  const enviadas: { destino: DestinoDoAviso; corpo: CorpoDoAviso }[] = [];
  const emitidos: string[] = [];
  const modos: string[] = [];
  const registo: Record<string, unknown>[] = [];
  // O `Logger` **real** e em modo estrito: e o que recusa um campo fora da
  // lista branca de nove. Um registo falso aqui nao provava nada sobre a
  // politica — provava que o teste sabe guardar objectos.
  const log = new Logger("gwy", {
    estrito: true,
    relogio: () => new Date(HORA),
    destino: {
      write: (linha: string) => {
        registo.push(JSON.parse(linha) as Record<string, unknown>);
      },
    },
  });
  const gate = new ConsentGate({
    bd,
    metricas,
    log,
    enviar: async (destino, corpo) => {
      enviadas.push({ destino, corpo });
      return troca.envia === false ? null : "wamid.AVISO0001";
    },
    emitir: async (tipo, _t, _c, finalidade) => {
      emitidos.push(`${tipo}:${finalidade}`);
    },
    modo: async (_t, _c, modo) => {
      modos.push(modo);
    },
    agora: () => new Date(HORA),
  });
  return { gate, bd, metricas, enviadas, emitidos, modos, registo };
}

function mensagem(entrada: Entrada, troca: { readonly wamid?: string } = {}) {
  return {
    tenantId: TENANT,
    contactId: CONTACTO,
    conversationId: CONVERSA,
    channelId: CANAL,
    phoneNumberId: PNID,
    wamid: troca.wamid ?? WAMID,
    hora: HORA,
    entrada,
  };
}

const BOTAO = (id: (typeof BOTOES)[number]): Entrada => ({ tipo: "botao", id });
const LIVRE: Entrada = { tipo: "texto", texto: "bom dia, tem arroz?" };
const PARAR: Entrada = { tipo: "texto", texto: "PARAR" };
const OUTRO: Entrada = { tipo: "outro" };

// ------------------------------------------------ as listas fechadas

describe("os dominios do consentimento", () => {
  it("**as dez finalidades sao as do dicionario §3.1**", () => {
    // A uniao das duas listas que existiam (emenda 1.16, KAM-159): as cinco do
    // dicionario e as oito dos contratos, que se cruzavam numa so.
    assert.deepEqual([...FINALIDADES], [
      "transacao",
      "atendimento",
      "marketing",
      "analytics_agregado",
      "melhoria_servico",
      "sugestoes_patrocinadas",
      "partilha_loja",
      "partilha_parceiros",
      "partilha_estafeta",
      "notificacao_dono",
    ]);
    assert.equal(FINALIDADES.length, 10);
  });

  it("**os botoes sao tres, e o limite e da Meta**", () => {
    // Um `interactive` de botoes aceita no maximo tres (`E1`), e o
    // `MAXIMO_DE_BOTOES` do KAM-015 recusa um quarto antes de qualquer chamada.
    assert.equal(BOTOES.length, 3);
    assert.deepEqual([...BOTOES], ["continuar", "falar_com_a_loja", "saber_mais"]);
  });

  it("**as linhas da matriz sao seis e os estados tres**", () => {
    assert.equal(LINHAS.length, 6);
    assert.equal(ESTADOS.length, 3);
    assert.equal(ACCOES.length, 6);
  });
});

// ------------------------------------------------------- o «PARAR»

describe("a deteccao do PARAR (criterio 5)", () => {
  it("**as oito variantes dos Testes Requeridos**", () => {
    // Maiusculas, minusculas, acentos, espacos, pontuacao, e os sinonimos.
    for (const variante of [
      "PARAR",
      "parar",
      "Parar",
      "párar",
      "  PARAR  ",
      "parar!",
      "STOP",
      "Cancelar",
    ]) {
      assert.equal(eParar(variante), true, variante);
    }
  });

  it("**a palavra dentro de uma frase nao dispara**, e isso e escolha", () => {
    // Disparar numa frase dava revogacoes que o cliente nao pediu — ele estava
    // a conversar. A escolha e a conservadora para o **registo**, e esta
    // escrita no modulo.
    for (const frase of [
      "nao parar",
      "pode parar de me mandar isso?",
      "quero cancelar a encomenda",
      "stop motion",
    ]) {
      assert.equal(eParar(frase), false, frase);
    }
  });

  it("a normalizacao tira acentos, caixa e pontuacao", () => {
    assert.equal(normalizar("  PÁRAR!! "), "parar");
    assert.equal(normalizar("Olá,  mundo"), "ola mundo");
  });

  it("**as quatro palavras estao declaradas e nao escritas num `if`**", () => {
    assert.deepEqual([...PALAVRAS_DE_PARAR], ["parar", "stop", "sair", "cancelar"]);
  });
});

// ------------------------------------------- a matriz, celula a celula

describe("a matriz do aviso: 6 entradas x 3 estados", () => {
  /** A tabela esperada, escrita aqui outra vez e de propósito. */
  const ESPERADO: Record<string, Record<EstadoDoConsentimento, Accao>> = {
    continuar: {
      ausente: "registar_e_seguir",
      desactualizado: "registar_e_seguir",
      valido: "seguir",
    },
    falar_com_a_loja: {
      ausente: "passar_a_humano",
      desactualizado: "passar_a_humano",
      valido: "passar_a_humano",
    },
    saber_mais: {
      ausente: "enviar_politica",
      desactualizado: "enviar_politica",
      valido: "enviar_politica",
    },
    parar: {
      ausente: "registar_revogacao",
      desactualizado: "registar_revogacao",
      valido: "registar_revogacao",
    },
    texto: {
      ausente: "enviar_aviso",
      desactualizado: "enviar_aviso",
      valido: "seguir",
    },
    outro: {
      ausente: "enviar_aviso",
      desactualizado: "enviar_aviso",
      valido: "seguir",
    },
  };

  const ENTRADAS: Record<string, Entrada> = {
    continuar: BOTAO("continuar"),
    falar_com_a_loja: BOTAO("falar_com_a_loja"),
    saber_mais: BOTAO("saber_mais"),
    parar: PARAR,
    texto: LIVRE,
    outro: OUTRO,
  };

  it("**as dezoito celulas**, uma a uma", () => {
    for (const linha of LINHAS) {
      for (const estado of ESTADOS) {
        assert.equal(
          accaoDoAviso(ENTRADAS[linha] as Entrada, estado, 0),
          ESPERADO[linha]?.[estado],
          `${linha} x ${estado}`,
        );
      }
    }
  });

  it("**o `enviar_aviso` passa a `passar_a_humano` ao terceiro** (criterio 3)", () => {
    for (const linha of ["texto", "outro"] as const) {
      assert.equal(
        accaoDoAviso(ENTRADAS[linha] as Entrada, "ausente", AVISOS_ANTES_DO_HUMANO - 1),
        "enviar_aviso",
        `${linha}: o segundo aviso ainda sai`,
      );
      assert.equal(
        accaoDoAviso(ENTRADAS[linha] as Entrada, "ausente", AVISOS_ANTES_DO_HUMANO),
        "passar_a_humano",
        `${linha}: o terceiro passa a pessoa`,
      );
    }
  });

  it("**o tecto nao mexe nas outras quatro linhas**", () => {
    // Um botao e um «PARAR» decidem-se sem a contagem: o tecto so muda um
    // `enviar_aviso`.
    for (const linha of ["continuar", "falar_com_a_loja", "saber_mais", "parar"] as const) {
      assert.equal(
        accaoDoAviso(ENTRADAS[linha] as Entrada, "ausente", 99),
        ESPERADO[linha]?.ausente,
        linha,
      );
    }
  });

  it("**o PARAR e lido antes do texto livre**, e e «em qualquer ponto»", () => {
    assert.equal(linhaDaEntrada(PARAR), "parar");
    assert.equal(linhaDaEntrada(LIVRE), "texto");
  });

  it("**um botao com um id que nao conhecemos cai em `outro` e nao levanta**", () => {
    // O `reply.id` vem da Meta a devolver o que nos mandamos, mas um aviso
    // antigo no telefone de alguem pode trazer um `id` que ja nao existe.
    const entrada = { tipo: "botao", id: "inventado" } as unknown as Entrada;
    assert.equal(linhaDaEntrada(entrada), "outro");
    assert.equal(accaoDoAviso(entrada, "ausente", 0), "enviar_aviso");
  });
});

// ------------------------------------------ o que autoriza o AGR

describe("o que autoriza o AGR (criterio 4)", () => {
  it("**duas accoes das seis, e so duas**", () => {
    const autorizam = ACCOES.filter((a) => autorizaAgr(a));
    assert.deepEqual([...autorizam].sort(), ["registar_e_seguir", "seguir"]);
  });

  it("**o `enviar_politica` nao autoriza**: quem quer saber mais nao consentiu", () => {
    assert.equal(autorizaAgr("enviar_politica"), false);
  });

  it("**tres accoes registam prova, e sao outras tres**", () => {
    // **As duas listas sao diferentes e tem de ser nomeadas as duas.** O
    // `registar_e_seguir` registra prova e **nao** envia mensagem; o
    // `enviar_aviso` envia e **nao** registra. Foi por nao haver esta funcao
    // que a correccao do «ler o texto tarde» calculou a prova do «Continuar»
    // sobre uma cadeia vazia — ver a nota no `consentimento.ts`.
    const registam = ACCOES.filter((a) => registaProva(a));
    assert.deepEqual(
      [...registam].sort(),
      ["passar_a_humano", "registar_e_seguir", "registar_revogacao"],
    );
    // E a interseccao com as que enviam e **uma** so: o «PARAR», que registra a
    // revogacao e responde a confirmacao.
    const ambas = ACCOES.filter((a) => registaProva(a) && enviaMensagem(a));
    assert.deepEqual([...ambas], ["registar_revogacao"]);
  });

  it("**tres accoes produzem mensagem, e nunca mais do que uma**", () => {
    const enviam = ACCOES.filter((a) => enviaMensagem(a));
    assert.deepEqual(
      [...enviam].sort(),
      ["enviar_aviso", "enviar_politica", "registar_revogacao"],
    );
  });

  it("**nenhuma celula autoriza o AGR sem consentimento valido**", () => {
    // A leitura exaustiva da matriz, que e o que torna a propriedade do
    // criterio 4 demonstravel por esta funcao sozinha.
    const ENTRADAS: Entrada[] = [
      BOTAO("continuar"),
      BOTAO("falar_com_a_loja"),
      BOTAO("saber_mais"),
      PARAR,
      LIVRE,
      OUTRO,
    ];
    for (const entrada of ENTRADAS) {
      for (const estado of ESTADOS) {
        const accao = accaoDoAviso(entrada, estado, 0);
        if (!autorizaAgr(accao)) continue;
        const eBotaoContinuar = entrada.tipo === "botao" && entrada.id === "continuar";
        assert.ok(
          estado === "valido" || eBotaoContinuar,
          `${accao} autorizou com estado ${estado}`,
        );
      }
    }
  });
});

// -------------------------------------------------- o estado do consentimento

describe("o estado do consentimento (criterio 7)", () => {
  it("sem linha e `ausente`", () => {
    assert.equal(estadoDoConsentimento(null, "v2"), "ausente");
  });

  it("**um `accepted: false` e `ausente` e nao um quarto estado**", () => {
    // Quem recusou nao deu consentimento, e o que o gate faz a seguir e o
    // mesmo. O registo da recusa fica na tabela, que e onde ele tem de ficar.
    assert.equal(
      estadoDoConsentimento({ accepted: false, text_version: "v2" }, "v2"),
      "ausente",
    );
  });

  it("**uma versao anterior e `desactualizado`**, e e o re-aviso do criterio 7", () => {
    assert.equal(
      estadoDoConsentimento({ accepted: true, text_version: "v1" }, "v2"),
      "desactualizado",
    );
  });

  it("a versao vigente aceita e `valido`", () => {
    assert.equal(
      estadoDoConsentimento({ accepted: true, text_version: "v2" }, "v2"),
      "valido",
    );
  });
});

// -------------------------------------------------------------- a prova

describe("a prova reproduzivel (criterio 7)", () => {
  const CAMPOS = {
    textoMostrado: "A Loja responde por assistente.",
    contactId: CONTACTO,
    wamid: WAMID,
    hora: HORA,
  };

  it("**tem 32 octetos**, que e o que o CHECK da revisao aceita", () => {
    assert.equal(provaDeConsentimento(CAMPOS).length, 32);
    assert.equal(resumoDoTexto("qualquer coisa").length, 32);
  });

  it("**e deterministica**: duas chamadas dao o mesmo valor", () => {
    assert.deepEqual(provaDeConsentimento(CAMPOS), provaDeConsentimento(CAMPOS));
  });

  it("**cada um dos quatro campos muda o resumo**", () => {
    const base = Buffer.from(provaDeConsentimento(CAMPOS)).toString("hex");
    for (const [campo, valor] of [
      ["textoMostrado", "outro texto"],
      ["contactId", CANAL],
      ["wamid", "wamid.OUTRO"],
      ["hora", "2026-11-02T14:03:11.483Z"],
    ] as const) {
      const outro = Buffer.from(
        provaDeConsentimento({ ...CAMPOS, [campo]: valor }),
      ).toString("hex");
      assert.notEqual(outro, base, campo);
    }
  });

  it("**o separador impede a colisao por deslocamento**", () => {
    // Sem separador, `sha256("ab" || "c")` e `sha256("a" || "bc")` sao o mesmo
    // resumo — e duas provas diferentes com o mesmo hash e exactamente o que
    // uma prova nao pode fazer.
    const um = provaDeConsentimento({ ...CAMPOS, textoMostrado: "ab", contactId: "c" });
    const dois = provaDeConsentimento({ ...CAMPOS, textoMostrado: "a", contactId: "bc" });
    assert.notDeepEqual(um, dois);
    assert.equal(SEPARADOR, "\u0000");
  });

  it("**o texto que entra e o preenchido**, com o nome da loja", () => {
    assert.equal(
      preencher(TEXTO, LOJA),
      `A ${LOJA} responde-lhe por um assistente automatico.`,
    );
    // Substitui **todas** as ocorrencias: o aviso nomeia o responsavel mais de
    // uma vez.
    assert.equal(
      preencher(`${MARCADOR_DA_LOJA} e ${MARCADOR_DA_LOJA}`, "X"),
      "X e X",
    );
    // Um texto sem marcador passa sem mudar, e nao levanta.
    assert.equal(preencher("sem marcador", LOJA), "sem marcador");
  });
});

// --------------------------------------------------- o gate, de ponta a ponta

describe("o gate: o primeiro contacto (criterio 1)", () => {
  it("**exactamente 1 mensagem de saida e 0 invocacoes do AGR**", async () => {
    const { gate, enviadas, metricas } = montar();
    const r = await gate.tratar(mensagem(LIVRE));

    assert.equal(r.accao, "enviar_aviso");
    assert.equal(r.invocaAgr, false, "a letra do criterio 1");
    assert.equal(r.mensagens, 1);
    assert.equal(enviadas.length, 1);
    // **Com os tres botoes**, e com o texto preenchido.
    assert.deepEqual([...(enviadas[0]?.corpo.botoes ?? [])], [...BOTOES]);
    assert.ok(enviadas[0]?.corpo.texto.includes(LOJA));
    assert.ok(!enviadas[0]?.corpo.texto.includes(MARCADOR_DA_LOJA));
    assert.equal(metricas.ler()[METRICA_AVISOS], 1);
    assert.equal(metricas.ler()[`${METRICA_BARRADAS}:enviar_aviso`], 1);
  });

  it("**a chave do aviso leva a conversa e o numero do aviso**", async () => {
    const { gate, bd, enviadas } = montar();
    bd.avisos = 1;
    await gate.tratar(mensagem(LIVRE));
    assert.equal(enviadas[0]?.destino.idempotencyKey, `aviso:${CONVERSA}:2`);
  });

  it("**sem versao vigente nao envia nada e nao autoriza**", async () => {
    // A `0015` cria a `consent_texts` **vazia**: o texto esta a confirmar por
    // parecer. A loja fica muda, e e o lado certo — ver a nota do modulo.
    const { gate, bd, enviadas, metricas, registo } = montar();
    bd.versao = null;
    const r = await gate.tratar(mensagem(LIVRE));

    assert.equal(r.invocaAgr, false);
    assert.equal(r.versao, null);
    assert.equal(r.mensagens, 0);
    assert.deepEqual(enviadas, []);
    assert.equal(metricas.ler()[`${METRICA_BARRADAS}:enviar_aviso`], 1);
    // **E nao e silencio:** fica no registo, com um `outcome` da lista branca.
    assert.ok(registo.some((l) => l.outcome === "aviso_sem_versao_vigente"));
  });

  it("**um aviso que nao sai conta como zero mensagens e fica no registo**", async () => {
    const { gate, metricas, registo } = montar({ envia: false });
    const r = await gate.tratar(mensagem(LIVRE));
    assert.equal(r.mensagens, 0);
    assert.equal(metricas.ler()[METRICA_AVISOS], undefined);
    assert.ok(registo.some((l) => l.outcome === "aviso_nao_saiu"));
  });
});

describe("o gate: o «Continuar» (criterio 2)", () => {
  it("**grava 1 linha e so entao o AGR e invocado**", async () => {
    const { gate, bd, emitidos, metricas } = montar();
    const r = await gate.tratar(mensagem(BOTAO("continuar")));

    assert.equal(r.accao, "registar_e_seguir");
    assert.equal(r.registou, true);
    assert.equal(r.invocaAgr, true);
    // A ordem: o `SQL_REGISTAR` **antes** de a decisao autorizar.
    assert.ok(bd.pedidos.includes(SQL_REGISTAR));
    // A finalidade e a `transacao`, e o `accepted` e `true`.
    const parametros = bd.parametros[bd.pedidos.indexOf(SQL_REGISTAR)] ?? [];
    assert.equal(parametros[2], "transacao");
    assert.equal(parametros[4], true);
    assert.equal(parametros[5], "whatsapp");
    assert.deepEqual(emitidos, ["consent.recorded:transacao"]);
    assert.equal(metricas.ler()[METRICA_ACEITES], 1);
  });

  it("**o mesmo botao duas vezes produz 1 linha**", async () => {
    const { gate, emitidos, metricas } = montar();
    assert.equal((await gate.tratar(mensagem(BOTAO("continuar")))).registou, true);
    const segunda = await gate.tratar(mensagem(BOTAO("continuar")));

    assert.equal(segunda.registou, false, "a prova ja estava registada");
    // **E o AGR nao e autorizado pela segunda**, e isso precisa de ser dito: a
    // mensagem repetida nao e um consentimento novo. O estado passa a `valido`
    // na leitura seguinte, e e por ai que a conversa segue.
    assert.equal(segunda.invocaAgr, false);
    assert.equal(emitidos.length, 1, "um evento e nao dois");
    assert.equal(metricas.ler()[METRICA_ACEITES], 1);
  });

  it("**com consentimento valido, segue sem escrever nada**", async () => {
    const { gate, bd } = montar();
    bd.estado = { accepted: true, text_version: "v1" };
    const r = await gate.tratar(mensagem(LIVRE));

    assert.equal(r.accao, "seguir");
    assert.equal(r.invocaAgr, true);
    assert.equal(r.mensagens, 0);
    assert.ok(!bd.pedidos.includes(SQL_REGISTAR));
  });

  it("**uma versao anterior obriga a re-avisar** (criterio 7)", async () => {
    const { gate, bd } = montar();
    bd.estado = { accepted: true, text_version: "v0" };
    const r = await gate.tratar(mensagem(LIVRE));

    assert.equal(r.estado, "desactualizado");
    assert.equal(r.accao, "enviar_aviso");
    assert.equal(r.invocaAgr, false);
  });
});

describe("o gate: «Falar com a loja» e «Saber mais» (criterio 3)", () => {
  it("**«Falar com a loja» passa a humano e nao invoca o AGR**", async () => {
    const { gate, modos, emitidos } = montar();
    const r = await gate.tratar(mensagem(BOTAO("falar_com_a_loja")));

    assert.equal(r.accao, "passar_a_humano");
    assert.equal(r.passaAHumano, true);
    assert.equal(r.invocaAgr, false, "sem tratar dados por IA");
    assert.deepEqual(modos, ["humano"]);
    // Registra a `atendimento`: o aviso **foi apresentado**, e isso e um facto.
    assert.deepEqual(emitidos, ["consent.recorded:atendimento"]);
  });

  it("**«Falar com a loja» vale tambem com consentimento valido**", async () => {
    // A Messaging Policy exige um caminho para uma pessoa em qualquer ponto.
    const { gate, bd } = montar();
    bd.estado = { accepted: true, text_version: "v1" };
    const r = await gate.tratar(mensagem(BOTAO("falar_com_a_loja")));
    assert.equal(r.passaAHumano, true);
    assert.equal(r.invocaAgr, false);
  });

  it("**«Saber mais» envia o texto e repete o aviso**, sem autorizar", async () => {
    const { gate, enviadas } = montar();
    const r = await gate.tratar(mensagem(BOTAO("saber_mais")));

    assert.equal(r.accao, "enviar_politica");
    assert.equal(r.invocaAgr, false);
    assert.equal(r.mensagens, 1);
    assert.equal(enviadas.length, 1);
    // **Com os tres botoes**, e e assim que as duas metades do criterio 3 —
    // «envia o texto completo» **e** «repete o aviso» — se cumprem numa
    // mensagem so, que e o que o criterio 1 promete. A primeira versao enviava
    // o texto **sem** botoes e deixava o cliente sem accao nenhuma.
    assert.deepEqual([...(enviadas[0]?.corpo.botoes ?? [])], [...BOTOES]);
  });

  it("**a confirmacao do PARAR e a unica sem botoes**: ela responde e nao pergunta", async () => {
    const { gate, enviadas } = montar();
    await gate.tratar(mensagem(PARAR));
    assert.deepEqual([...(enviadas[0]?.corpo.botoes ?? [])], []);
  });

  it("**texto livre tres vezes acaba numa pessoa**", async () => {
    const { gate, bd, modos } = montar();
    bd.avisos = AVISOS_ANTES_DO_HUMANO;
    const r = await gate.tratar(mensagem(LIVRE));

    assert.equal(r.accao, "passar_a_humano");
    assert.equal(r.invocaAgr, false);
    assert.deepEqual(modos, ["humano"]);
  });
});

describe("o gate: o «PARAR» (criterio 5)", () => {
  it("**grava a revogacao de marketing, pausa e confirma**", async () => {
    const { gate, bd, modos, emitidos, enviadas, metricas } = montar();
    const r = await gate.tratar(mensagem(PARAR));

    assert.equal(r.accao, "registar_revogacao");
    assert.equal(r.registou, true);
    assert.equal(r.pausaAConversa, true);
    assert.equal(r.invocaAgr, false);
    const parametros = bd.parametros[bd.pedidos.indexOf(SQL_REGISTAR)] ?? [];
    assert.equal(parametros[2], "marketing");
    assert.equal(parametros[4], false, "accepted = false");
    assert.deepEqual(modos, ["pausada"]);
    assert.deepEqual(emitidos, ["consent.withdrawn:marketing"]);
    // «Responde 1 confirmacao»: uma mensagem, nao duas.
    assert.equal(r.mensagens, 1);
    assert.equal(enviadas.length, 1);
    assert.equal(metricas.ler()[METRICA_OPTOUT], 1);
  });

  it("**o PARAR vale com consentimento valido**, e e «em qualquer ponto»", async () => {
    const { gate, bd } = montar();
    bd.estado = { accepted: true, text_version: "v1" };
    const r = await gate.tratar(mensagem(PARAR));
    assert.equal(r.accao, "registar_revogacao");
    assert.equal(r.invocaAgr, false);
  });

  it("**nunca escreve `marketing` com `accepted = true`**", async () => {
    // O opt-in de marketing e separado e especifico (`E1` §4), e no Piloto nao
    // ha marketing. Escrever um `true` aqui era inventar um consentimento.
    const { gate, bd } = montar();
    for (const entrada of [PARAR, BOTAO("continuar"), BOTAO("falar_com_a_loja")]) {
      await gate.tratar(mensagem(entrada, { wamid: `wamid.${entrada.tipo}` }));
    }
    for (const [indice, texto] of bd.pedidos.entries()) {
      if (texto !== SQL_REGISTAR) continue;
      const parametros = bd.parametros[indice] ?? [];
      if (parametros[2] === "marketing") {
        assert.equal(parametros[4], false, "marketing com accepted true");
      }
    }
  });
});

// ----------------------------------------- a propriedade do criterio 4

describe("a propriedade: 1.000 mensagens x 50 contactos (criterio 4)", () => {
  it("**0 invocacoes do AGR sem consentimento valido anterior**", async () => {
    // **O aleatorio e determinista**: semente fixa, para o caso que falhar se
    // poder repetir. Um `Math.random()` dava um teste que falha uma vez por mes
    // e nunca se reproduz — a mesma regra do teste dos 50 eventos do KAM-021.
    let semente = 20261022;
    const proximo = (n: number): number => {
      semente = (semente * 1103515245 + 12345) & 0x7fffffff;
      return semente % n;
    };
    const ENTRADAS: Entrada[] = [
      BOTAO("continuar"),
      BOTAO("falar_com_a_loja"),
      BOTAO("saber_mais"),
      PARAR,
      LIVRE,
      OUTRO,
    ];

    /** O que a base «sabe» por contacto, como a vista o devolveria. */
    const consentidos = new Map<string, string>();
    let invocacoes = 0;
    let violacoes = 0;

    for (let n = 0; n < 1000; n += 1) {
      const contacto = `contacto-${proximo(50)}`;
      const entrada = ENTRADAS[proximo(ENTRADAS.length)] as Entrada;
      const { gate, bd } = montar();
      const versao = consentidos.get(contacto);
      bd.estado = versao === undefined ? null : { accepted: true, text_version: versao };
      const tinhaAntes = versao === "v1";

      const r = await gate.tratar({
        ...mensagem(entrada, { wamid: `wamid.${n}` }),
        contactId: contacto,
        conversationId: `conversa-${contacto}`,
      });

      if (r.invocaAgr) {
        invocacoes += 1;
        // **A propriedade:** ou já havia consentimento válido antes, ou **esta**
        // mensagem escreveu a linha — e nesse caso ela foi escrita antes de a
        // decisão autorizar.
        if (!tinhaAntes && !r.registou) violacoes += 1;
      }
      if (r.registou && r.accao === "registar_e_seguir") {
        consentidos.set(contacto, "v1");
      }
      if (r.accao === "registar_revogacao") {
        // Uma revogação de *marketing* **não** apaga o consentimento de
        // transacção, e é por isso que esta linha não mexe no mapa: são
        // finalidades diferentes, e confundi-las fazia um «PARAR» calar a loja
        // para sempre.
        assert.equal(r.invocaAgr, false);
      }
    }

    assert.equal(violacoes, 0, "o criterio 4 pede 0 violacoes");
    assert.ok(invocacoes > 0, "se nada invocou, o teste nao provou nada");
  });
});

// ------------------------------------------------------------ as metricas

describe("as metricas (DoD «Custo e observabilidade»)", () => {
  it("**as tres do DoD existem, com os nomes dele**", () => {
    const texto = new MetricasDoConsentimento().exposicao();
    for (const nome of [
      "consent_notice_sent_total",
      "consent_accepted_ratio",
      "consent_optout_total",
    ]) {
      assert.ok(texto.includes(`# TYPE ${nome} `), nome);
    }
  });

  it("**as cinco aparecem sempre, mesmo a zero**", () => {
    const texto = new MetricasDoConsentimento().exposicao();
    assert.equal((texto.match(/^# TYPE /gm) ?? []).length, 5);
    assert.ok(texto.includes("consent_accepted_ratio -1"), "o racio nasce em -1");
  });

  it("**o racio vale -1 antes do primeiro aviso**, e nao zero", () => {
    const m = new MetricasDoConsentimento();
    assert.equal(m.racio(), -1);
    m.contar(METRICA_AVISOS);
    assert.equal(m.racio(), 0, "com aviso e sem aceite, zero e a verdade");
    m.contar(METRICA_ACEITES);
    assert.equal(m.racio(), 1);
  });

  it("**o racio nao se limita a 1**, e isso e informacao", () => {
    const m = new MetricasDoConsentimento();
    m.contar(METRICA_AVISOS);
    m.contar(METRICA_ACEITES, undefined, 3);
    assert.equal(m.racio(), 3);
  });

  it("**uma metrica que nao existe levanta**", () => {
    assert.throws(
      () => new MetricasDoConsentimento().contar("consent_inventado"),
      MetricaDesconhecidaError,
    );
  });

  it("**um sufixo fora da lista fechada levanta**", () => {
    assert.throws(
      () => new MetricasDoConsentimento().contar(METRICA_BARRADAS, "inventada"),
      SufixoInvalidoError,
    );
  });

  it("**um `tenant_id` como sufixo levanta**", () => {
    // A mesma asserção do KAM-015, do KAM-023 e do KAM-021, e pela mesma razão:
    // as etiquetas têm de casar `^[a-z][a-z0-9_]{1,62}$` e um UUID com hífenes
    // não casa. `OBS-I` de `docs/seguranca/ameacas_stride.md`.
    assert.throws(
      () => new MetricasDoConsentimento().contar(METRICA_BARRADAS, TENANT),
      SufixoInvalidoError,
    );
  });

  it("**a exposicao nao leva identificadores**", () => {
    const m = new MetricasDoConsentimento();
    m.contar(METRICA_AVISOS);
    m.contar(METRICA_BARRADAS, "enviar_aviso");
    const texto = m.exposicao();
    for (const identificador of [TENANT, CONTACTO, CONVERSA, PNID, WAMID]) {
      assert.ok(!texto.includes(identificador), identificador);
    }
  });

  it("a etiqueta `accao` tem os seis valores fechados e mais nenhum", () => {
    const m = new MetricasDoConsentimento();
    for (const accao of ACCOES) m.contar(METRICA_BARRADAS, accao);
    assert.equal(
      (m.exposicao().match(/consent_blocked_total\{accao="/g) ?? []).length,
      ACCOES.length,
    );
  });

  it("o `METRICA_RACIO` esta na leitura e nao e um contador", () => {
    assert.ok(METRICA_RACIO in new MetricasDoConsentimento().ler());
  });
});

// ------------------------------------------------ o registo de linha

describe("o registo de linha nao leva texto nem telefone (DoD «Privacidade»)", () => {
  it("**nenhum `outcome` leva o texto do cliente nem o wamid**", async () => {
    const { gate, bd, registo } = montar({ envia: false });
    bd.versao = null;
    await gate.tratar(mensagem({ tipo: "texto", texto: "o meu numero e 923000000" }));
    const texto = JSON.stringify(registo);
    assert.ok(!texto.includes("923000000"), "o texto do cliente entrou no registo");
    assert.ok(!texto.includes(WAMID), "o wamid entrou no registo");
    assert.ok(!texto.includes(CONTACTO), "o contacto entrou no registo");
  });
});

// ------------------------------------------------------- as finalidades

describe("as tres finalidades que este modulo escreve", () => {
  it("**tres das dez, e as outras sete nao tem caminho aqui**", async () => {
    const escritas = new Set<Finalidade>();
    for (const entrada of [BOTAO("continuar"), BOTAO("falar_com_a_loja"), PARAR]) {
      const { gate, bd } = montar();
      await gate.tratar(mensagem(entrada));
      for (const [indice, texto] of bd.pedidos.entries()) {
        if (texto === SQL_REGISTAR) {
          escritas.add((bd.parametros[indice] ?? [])[2] as Finalidade);
        }
      }
    }
    assert.deepEqual([...escritas].sort(), ["atendimento", "marketing", "transacao"]);
  });
});
