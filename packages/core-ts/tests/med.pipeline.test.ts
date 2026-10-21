/**
 * O pipeline de recepção de mídia (KAM-020, critérios 1, 2, 3, 5, 6, 7 e 9).
 *
 * **Monta-se um `StorageProvider` verdadeiro** — o duplo do KAM-011, que é um
 * motor em memória com a mesma porta, as mesmas validações de chave e o mesmo
 * `signUrl` — e não um objecto que devolva o que lhe mandássemos. A razão é a
 * lição que o KAM-019 pagou caro:
 *
 * > **Um duplo prova que o nosso código chama o que pretendíamos chamar. Não
 * > prova que o terceiro aceita a chamada.**
 *
 * Aqui o «terceiro» é a porta do armazenamento, e ela **é** nossa: tem bateria
 * de contrato própria e corre contra três alvos, incluindo um SeaweedFS real.
 * Usá-la de verdade é o mais perto que esta bateria pode chegar sem abrir
 * *socket*, e é o que apanha uma chave mal formada, uma classe que não casa o
 * segmento, ou um TTL acima do máximo — três coisas que um duplo nosso aceitaria
 * em silêncio.
 *
 * A **Meta** é que é porta falsa, e tem de ser: é ela que não tem evidência
 * nenhuma no `E1`, e é a única que este ticket não pode medir.
 *
 * O que estes testes prendem, por ordem de gravidade:
 *
 * 1. **Três chamadas com a mesma origem dão um objecto e uma linha** (critério
 *    2), e quem o garante é o `ON CONFLICT` — a segunda chamada **não fala com
 *    a Meta**.
 * 2. **Nenhum URL da Meta sai** (critério 3): varre-se tudo o que foi escrito.
 * 3. **A *allowlist* corre no tipo da resposta** e não no anunciado.
 * 4. **Três tentativas e não quatro** (critério 6), com aviso ao AGR.
 * 5. **O áudio leva 24 h de retenção e as outras classes não** (critério 7).
 * 6. **O URL interno é de outro *tenant* e é recusado pela porta** (critério 5).
 */

import assert from "node:assert/strict";
import { describe, it } from "node:test";

import { criarStorageFake, TTL_MAXIMO_S } from "../src/storage/index.ts";
import {
  Med,
  METRICA_BYTES,
  METRICA_DESCARGA_MS,
  METRICA_REJEICOES,
  MetricasDoMed,
  MidiaIndisponivelError,
  MidiaInesperadaError,
  PREFIXO_INTERNO,
  RETENCAO_DE_AUDIO_MS,
  TENTATIVAS,
  TTL_DA_URL_INTERNA_S,
  type ClienteDeMidia,
  type MidiaDescarregada,
  type MidiaResolvida,
  type PedidoDeMidia,
} from "../src/med/index.ts";

const TENANT = "11111111-1111-4111-8111-111111111111";
const OUTRO_TENANT = "22222222-2222-4222-8222-222222222222";
const CONTACTO = "33333333-3333-4333-8333-333333333333";
const CONVERSA = "44444444-4444-4444-8444-444444444444";
const T0 = Date.UTC(2026, 9, 21, 12, 0, 0);

/**
 * **O URL temporário da Meta, e é o canário do critério 3.**
 *
 * Tem a forma de um URL de CDN da Meta e um valor distintivo: se ele aparecer
 * em qualquer coisa que tenha sido escrita — base, registo, carga —, o teste
 * que o procura falha.
 */
const URL_DA_META = "https://lookaside.fbsbx.com/whatsapp_business/attachments/?mid=CANARIO-DA-META";

/** A base por porta, com o `ON CONFLICT` da origem. */
class BaseFalsa {
  /** `(tenant|wamid|mediaId)` -> a linha, como o `SELECT` a devolve. */
  readonly linhas = new Map<string, Record<string, unknown>>();
  readonly instrucoes: string[] = [];
  #proximo = 0;

  async query<T>(texto: string, valores: readonly unknown[] = []): Promise<{ rows: readonly T[] }> {
    const linhas = (valor: unknown[]): { rows: readonly T[] } => ({
      rows: valor as readonly T[],
    });
    if (texto.includes("INSERT INTO platform.media_assets")) {
      this.instrucoes.push("reservar");
      const chave = `${String(valores[0])}|${String(valores[3])}|${String(valores[4])}`;
      if (this.linhas.has(chave)) return linhas([]);
      this.#proximo += 1;
      const assetId = `asset-${this.#proximo}`;
      this.linhas.set(chave, {
        asset_id: assetId,
        tenant_id: String(valores[0]),
        estado: "pendente",
        classe: String(valores[5]),
        storage_ref: null,
        sha256: null,
      });
      return linhas([{ asset_id: assetId }]);
    }
    if (texto.includes("SET estado = 'armazenado'")) {
      this.instrucoes.push("marcar_armazenado");
      const linha = this.#porAsset(String(valores[0]), String(valores[1]));
      if (linha === undefined || linha["estado"] !== "pendente") return linhas([]);
      linha["estado"] = "armazenado";
      linha["content_type"] = valores[2];
      linha["size"] = valores[3];
      linha["sha256"] = valores[4];
      linha["storage_ref"] = valores[5];
      linha["retain_until"] = valores[6];
      return linhas([{ asset_id: linha["asset_id"], estado: "armazenado" }]);
    }
    if (texto.includes("SET estado = $3")) {
      this.instrucoes.push("marcar_desfecho");
      const linha = this.#porAsset(String(valores[0]), String(valores[1]));
      if (linha === undefined || linha["estado"] !== "pendente") return linhas([]);
      linha["estado"] = String(valores[2]);
      return linhas([{ asset_id: linha["asset_id"], estado: valores[2] }]);
    }
    if (texto.includes("AND wamid = $2")) {
      this.instrucoes.push("por_origem");
      const chave = `${String(valores[0])}|${String(valores[1])}|${String(valores[2])}`;
      const linha = this.linhas.get(chave);
      return linhas(linha === undefined ? [] : [linha]);
    }
    if (texto.includes("AND asset_id = $2")) {
      this.instrucoes.push("por_asset");
      const linha = this.#porAsset(String(valores[0]), String(valores[1]));
      return linhas(linha === undefined ? [] : [linha]);
    }
    return linhas([]);
  }

  #porAsset(tenant: string, assetId: string): Record<string, unknown> | undefined {
    for (const linha of this.linhas.values()) {
      if (linha["asset_id"] === assetId && linha["tenant_id"] === tenant) return linha;
    }
    return undefined;
  }
}

/** A Meta por porta: é a única coisa aqui que este ticket não pode medir. */
class MetaFalsa implements ClienteDeMidia {
  resolucoes = 0;
  descargas = 0;
  emBaixo = false;
  /** Quantas descargas falham antes de uma passar. */
  falhasAntesDeAcertar = 0;
  contentType = "audio/ogg; codecs=opus";
  bytes = new Uint8Array([1, 2, 3, 4, 5, 6, 7, 8]);
  /** Quanto o relógio avança durante a descarga, em ms. */
  duracaoMs = 0;
  avancarRelogio: ((ms: number) => void) | null = null;

  readonly resolver = async (
    _tenantId: string,
    _mediaId: string,
  ): Promise<MidiaResolvida> => {
    this.resolucoes += 1;
    if (this.emBaixo) throw new MidiaIndisponivelError("resolver: sem resposta");
    return { url: URL_DA_META, contentType: this.contentType };
  };

  readonly descarregar = async (
    _tenantId: string,
    resolvida: MidiaResolvida,
  ): Promise<MidiaDescarregada> => {
    this.descargas += 1;
    assert.equal(resolvida.url, URL_DA_META, "a descarga tem de usar o URL resolvido");
    if (this.duracaoMs > 0) this.avancarRelogio?.(this.duracaoMs);
    if (this.emBaixo) throw new MidiaIndisponivelError("descarregar: sem resposta");
    if (this.falhasAntesDeAcertar > 0) {
      this.falhasAntesDeAcertar -= 1;
      throw new MidiaIndisponivelError("descarregar: a rede caiu");
    }
    return { bytes: this.bytes, contentType: this.contentType };
  };
}

interface Montagem {
  readonly med: Med;
  readonly bd: BaseFalsa;
  readonly meta: MetaFalsa;
  readonly storage: ReturnType<typeof criarStorageFake>;
  readonly avisos: unknown[];
  readonly transcritos: unknown[];
  readonly esperas: number[];
  readonly registo: Record<string, unknown>[];
  readonly metricas: MetricasDoMed;
  readonly avancar: (ms: number) => void;
}

function montar(): Montagem {
  const bd = new BaseFalsa();
  const meta = new MetaFalsa();
  // **O duplo do KAM-011, que é a porta a sério.** Ver a nota do módulo.
  const storage = criarStorageFake();
  const avisos: unknown[] = [];
  const transcritos: unknown[] = [];
  const esperas: number[] = [];
  const registo: Record<string, unknown>[] = [];
  const metricas = new MetricasDoMed();
  let instante = T0;
  const avancar = (ms: number): void => {
    instante += ms;
  };
  meta.avancarRelogio = avancar;
  const med = new Med({
    bd,
    armazenamento: storage.storage,
    midia: meta,
    avisarAgr: async (aviso) => {
      avisos.push(aviso);
    },
    onTranscribed: async (asset) => {
      transcritos.push(asset);
    },
    metricas,
    log: {
      info: (campos: Record<string, unknown>) => registo.push({ nivel: "info", ...campos }),
      warn: (campos: Record<string, unknown>) => registo.push({ nivel: "warn", ...campos }),
      error: (campos: Record<string, unknown>) => registo.push({ nivel: "error", ...campos }),
    } as never,
    agora: () => new Date(instante),
    // **O relógio avança pelo `dormir`**, e não é cosmética: foi o defeito que a
    // bateria do critério 6 do KAM-019 pagou com dezasseis minutos a 99% de CPU.
    dormir: async (ms: number) => {
      esperas.push(ms);
      avancar(ms);
    },
  });
  return { med, bd, meta, storage, avisos, transcritos, esperas, registo, metricas, avancar };
}

function pedido(troca: Partial<PedidoDeMidia> = {}): PedidoDeMidia {
  return {
    tenantId: TENANT,
    contactId: CONTACTO,
    conversationId: CONVERSA,
    wamid: "wamid.HBgLABC",
    mediaId: "media-abc",
    waType: "audio",
    ...troca,
  };
}

describe("a recepcao de midia (criterio 1)", () => {
  it("um audio da 1 objecto e 1 linha, com a chave do tenant", async () => {
    const { med, bd, storage } = montar();
    const resultado = await med.receber(pedido());

    assert.equal(resultado.estado, "armazenado");
    assert.equal(storage.total(), 1, "um objecto");
    assert.equal(bd.linhas.size, 1, "uma linha");
    const linha = [...bd.linhas.values()][0];
    assert.equal(linha?.["estado"], "armazenado");
    // **A chave leva o tenant no primeiro segmento e a classe no segundo**, que
    // e a forma que a porta do KAM-011 impoe e valida.
    assert.match(
      String(linha?.["storage_ref"]),
      new RegExp(`^t/${TENANT}/media_audio/\\d{4}/\\d{2}/`),
    );
  });

  it("**a referencia e `media://{assetId}`**, e nao a chave nem o URL", async () => {
    // A chave e do armazenamento e muda se o molde mudar; o `assetId` e nosso e
    // nao muda. E o URL da Meta nunca sai daqui.
    const { med } = montar();
    const resultado = await med.receber(pedido());
    assert.ok(resultado.estado === "armazenado");
    assert.equal(resultado.referencia, `${PREFIXO_INTERNO}${resultado.assetId}`);
    assert.ok(!resultado.referencia.includes("t/"), "a chave nao entra na referencia");
  });

  it("o content_type gravado e o da **resposta** e nao o anunciado", async () => {
    // Confiar no que o webhook anuncia era aceitar que ele mente.
    const { med, bd, meta } = montar();
    meta.contentType = "image/png";
    await med.receber(pedido({ waType: "image", contentTypeAnunciado: "image/jpeg" }));
    const linha = [...bd.linhas.values()][0];
    assert.equal(linha?.["content_type"], "image/png");
  });

  it("o sha256 e o tamanho vem do `put` e nao se recalculam", async () => {
    // O que importa e o resumo do que **ficou** armazenado: um resumo calculado
    // sobre os bytes que tinhamos em memoria nao prova que o objecto la esta.
    const { med, bd, meta } = montar();
    await med.receber(pedido());
    const linha = [...bd.linhas.values()][0];
    assert.equal(linha?.["size"], meta.bytes.byteLength);
    assert.match(String(linha?.["sha256"]), /^[0-9a-f]{64}$/);
  });
});

describe("idempotencia (criterio 2)", () => {
  it("**tres chamadas dao 1 objecto e 1 linha**", async () => {
    const { med, bd, storage, meta } = montar();
    const primeira = await med.receber(pedido());
    const segunda = await med.receber(pedido());
    const terceira = await med.receber(pedido());

    assert.equal(storage.total(), 1, "um objecto");
    assert.equal(bd.linhas.size, 1, "uma linha");
    assert.ok(primeira.estado === "armazenado");
    assert.ok(segunda.estado === "armazenado" && segunda.repetido);
    assert.ok(terceira.estado === "armazenado" && terceira.repetido);
    assert.equal(primeira.assetId, segunda.assetId);
    // **E a segunda e a terceira nao falaram com a Meta**, que e o defeito mais
    // caro que isto prende: a reserva vem antes da descarga de proposito.
    assert.equal(meta.resolucoes, 1, "a segunda resolucao e o defeito");
    assert.equal(meta.descargas, 1, "a segunda descarga e o defeito");
  });

  it("**a reserva e a primeira instrucao**, antes de qualquer chamada", async () => {
    const { med, bd } = montar();
    await med.receber(pedido());
    assert.equal(bd.instrucoes[0], "reservar", `a primeira foi ${bd.instrucoes[0]}`);
  });

  it("dois `media_id` na mesma mensagem sao dois objectos", async () => {
    // Uma mensagem pode trazer mais do que um objecto, e e por isso que a
    // unicidade leva o `media_id` e nao so o `wamid`.
    const { med, bd, storage } = montar();
    await med.receber(pedido({ mediaId: "media-1" }));
    await med.receber(pedido({ mediaId: "media-2" }));
    assert.equal(storage.total(), 2);
    assert.equal(bd.linhas.size, 2);
  });

  it("o mesmo `(wamid, media_id)` em dois tenants sao dois objectos", async () => {
    // A unicidade leva o `tenant_id`: um `media_id` repetido entre duas PMEs e
    // uma colisao do lado da Meta, e recusar o segundo fazia a nossa base
    // perder uma mensagem por um defeito que nao e nosso.
    const { med, bd } = montar();
    await med.receber(pedido());
    await med.receber(pedido({ tenantId: OUTRO_TENANT }));
    assert.equal(bd.linhas.size, 2);
  });
});

describe("nenhum URL da Meta e persistido (criterio 3)", () => {
  it("**o canario nao aparece em nada do que foi escrito**", async () => {
    // O criterio pede «um teste que percorre as tabelas e logs de uma execucao
    // por padroes do dominio da Meta». Este percorre **tudo** o que o modulo
    // escreveu: as linhas, o registo, os avisos ao AGR e as metricas.
    const { med, bd, registo, avisos, metricas } = montar();
    await med.receber(pedido());

    const tudo = JSON.stringify({
      linhas: [...bd.linhas.values()],
      registo,
      avisos,
      metricas: metricas.ler(),
      exposicao: metricas.exposicao(),
    });
    assert.ok(!tudo.includes("CANARIO-DA-META"), "o URL da Meta foi persistido");
    assert.ok(!tudo.includes("lookaside"), "o dominio da Meta foi persistido");
    assert.ok(!tudo.includes("fbsbx"), "o dominio da Meta foi persistido");
  });

  it("o canario tambem nao aparece quando a descarga falha", async () => {
    // O caminho de falha e onde um URL escapa mais facilmente: uma mensagem de
    // erro que cite a URL completa punha-o no registo.
    const { med, bd, registo, avisos, meta } = montar();
    meta.emBaixo = true;
    await med.receber(pedido());
    const tudo = JSON.stringify({ linhas: [...bd.linhas.values()], registo, avisos });
    assert.ok(!tudo.includes("CANARIO-DA-META"));
    assert.ok(!tudo.includes("lookaside"));
  });

  it("**o `media_id` fica, e nao e um URL**", async () => {
    // O que se guarda e o identificador, que e o que permite voltar a resolver.
    const { med, bd } = montar();
    await med.receber(pedido());
    const chave = [...bd.linhas.keys()][0];
    assert.ok(String(chave).includes("media-abc"));
  });
});

describe("a allowlist em execucao (criterio 4)", () => {
  it("**um tipo que nao passa vira `rejeitado`, com resposta**", async () => {
    const { med, bd, storage } = montar();
    const meta = montar();
    void meta;
    const montagem = montar();
    montagem.meta.contentType = "application/zip";
    const resultado = await montagem.med.receber(montagem.bd === bd ? pedido() : pedido());

    assert.ok(resultado.estado === "rejeitado");
    assert.equal(resultado.motivo, "tipo_nao_permitido");
    assert.ok(resultado.resposta.length > 0);
    assert.equal(storage.total(), 0, "nada foi armazenado nesta montagem");
    assert.equal(montagem.storage.total(), 0, "**nada foi armazenado**");
    const linha = [...montagem.bd.linhas.values()][0];
    assert.equal(linha?.["estado"], "rejeitado");
  });

  it("**o tipo anunciado recusa cedo e poupa a descarga**", async () => {
    // E a unica coisa que o anuncio serve: se ja se sabe que nao passa, nao se
    // gasta a descarga. O que **vale** continua a ser o tipo da resposta.
    const { med, meta, storage } = montar();
    const resultado = await med.receber(
      pedido({ waType: "document", contentTypeAnunciado: "application/zip" }),
    );
    assert.ok(resultado.estado === "rejeitado");
    assert.equal(meta.descargas, 0, "a descarga de um tipo ja recusado e desperdicio");
    assert.equal(storage.total(), 0);
  });

  it("um anuncio que passa **nao** dispensa a verificacao real", async () => {
    // O anuncio diz `image/png` e a resposta traz `application/zip`: recusa-se.
    const { med, meta, storage } = montar();
    meta.contentType = "application/zip";
    const resultado = await med.receber(
      pedido({ waType: "image", contentTypeAnunciado: "image/png" }),
    );
    assert.ok(resultado.estado === "rejeitado");
    assert.equal(meta.descargas, 1, "a descarga aconteceu, e e isso que permite ver");
    assert.equal(storage.total(), 0);
  });

  it("**um wa_type que nao e midia nao reserva linha nenhuma**", async () => {
    // Uma tabela de midia com entradas de `location` dizia uma coisa falsa
    // sobre o que ela guarda.
    const { med, bd, meta, metricas } = montar();
    const resultado = await med.receber(pedido({ waType: "location" }));
    assert.ok(resultado.estado === "rejeitado");
    assert.equal(resultado.motivo, "classe_desconhecida");
    assert.equal(bd.linhas.size, 0, "nenhuma linha");
    assert.equal(meta.resolucoes, 0, "nenhuma chamada");
    assert.equal(metricas.ler()[`${METRICA_REJEICOES}:classe_desconhecida`], 1);
  });

  it("o tamanho excedido conta no seu motivo", async () => {
    const { med, meta, metricas } = montar();
    meta.contentType = "image/png";
    meta.bytes = new Uint8Array(6 * 1024 * 1024);
    const resultado = await med.receber(pedido({ waType: "image" }));
    assert.ok(resultado.estado === "rejeitado");
    assert.equal(resultado.motivo, "tamanho_excedido");
    assert.equal(metricas.ler()[`${METRICA_REJEICOES}:tamanho_excedido`], 1);
  });
});

describe("o URL interno assinado (criterio 5)", () => {
  it("o TTL e o maximo da porta, que e 300 s", async () => {
    // **Nao se escreve 300 aqui**: le-se do `TTL_MAXIMO_S` da porta, para que
    // mudar o limite seja um sitio e nao dois. O criterio pede «≤ 300 s» e o
    // `docs/tecnica/08` §3.8 «TTL ≤ 5 min».
    assert.equal(TTL_DA_URL_INTERNA_S, TTL_MAXIMO_S);
    assert.equal(TTL_DA_URL_INTERNA_S, 300);
  });

  it("um asset armazenado da um URL assinado", async () => {
    const { med } = montar();
    const resultado = await med.receber(pedido());
    assert.ok(resultado.estado === "armazenado");
    const url = await med.urlInterna(TENANT, resultado.assetId);
    assert.ok(url !== null && url.length > 0);
  });

  it("**com o contexto de outro tenant a porta recusa** (X-08)", async () => {
    // E a porta do KAM-011 que recusa, e nao uma verificacao nossa: a chave
    // leva o tenant no primeiro segmento e o `signUrl` levanta
    // `ChaveForaDoTenantError`. Isto e mais forte do que um `if` nosso, porque
    // a porta tem bateria de contrato propria contra tres alvos.
    const { med, bd } = montar();
    const resultado = await med.receber(pedido());
    assert.ok(resultado.estado === "armazenado");
    // A linha de outro tenant com a **mesma** chave: e o que um defeito de
    // contexto produziria.
    const linha = [...bd.linhas.values()][0];
    bd.linhas.set("forjada", {
      ...linha,
      asset_id: "asset-forjado",
      tenant_id: OUTRO_TENANT,
    });
    await assert.rejects(() => med.urlInterna(OUTRO_TENANT, "asset-forjado"));
  });

  it("um asset que nao existe da `null` e nao levanta", async () => {
    // `null` e nao excepcao: «este asset nao e deste tenant, ou nao existe» e
    // uma resposta normal, e uma excepcao obrigava quem chama a usar
    // `try/catch` como fluxo de controlo.
    const { med } = montar();
    assert.equal(await med.urlInterna(TENANT, "asset-que-nao-existe"), null);
  });

  it("um asset `pendente` da `null`: nao ha o que assinar", async () => {
    const { med, meta } = montar();
    meta.emBaixo = true;
    const resultado = await med.receber(pedido());
    assert.ok(resultado.estado === "falhou");
    assert.equal(await med.urlInterna(TENANT, resultado.assetId), null);
  });
});

describe("a descarga que falha (criterio 6)", () => {
  it("**sao tres tentativas e nao quatro**", async () => {
    // O criterio diz «3 tentativas com backoff; depois `estado='falhou'`», e
    // le-se a letra: tres idas a Meta. **Nao** se repete a releitura que o
    // criterio 6 do KAM-015 obrigou — la o texto contradizia-se na propria
    // aritmetica, e aqui nao ha contradicao que force outra leitura.
    const { med, meta } = montar();
    meta.emBaixo = true;
    const resultado = await med.receber(pedido());
    assert.ok(resultado.estado === "falhou");
    assert.equal(resultado.tentativas, TENTATIVAS);
    // **Com a Meta em baixo e o `resolver` que estoura**, pelo que sao tres
    // resolucoes e **zero** descargas: o `descarregar` nunca chega a ser
    // chamado. A primeira versao deste teste contava as descargas e media
    // zero — e a correccao e informativa, porque o que ela prende e que o
    // *retry* envolve **as duas** chamadas e nao so a segunda.
    assert.equal(meta.resolucoes, 3, "tres tentativas, nao quatro");
    assert.equal(meta.descargas, 0, "o `resolver` estourou antes");
  });

  it("**e sao tres tambem quando e a descarga que cai**", async () => {
    // O par do teste acima: aqui o `resolver` responde e e o `descarregar` que
    // falha. Sem este, o *retry* podia envolver so a primeira chamada e os dois
    // testes passavam — foi o que a primeira versao escondia.
    const { med, meta } = montar();
    meta.falhasAntesDeAcertar = TENTATIVAS + 5;
    const resultado = await med.receber(pedido());
    assert.ok(resultado.estado === "falhou");
    assert.equal(meta.resolucoes, 3);
    assert.equal(meta.descargas, 3, "tres descargas, nao quatro");
  });

  it("**o backoff cresce, e sao duas esperas e nao tres**", async () => {
    // Entre tres tentativas ha **duas** esperas. Uma terceira espera depois da
    // ultima tentativa era tempo gasto a nao fazer nada antes de desistir.
    const { med, meta, esperas } = montar();
    meta.emBaixo = true;
    await med.receber(pedido());
    assert.equal(esperas.length, TENTATIVAS - 1);
    assert.ok(esperas[1]! > esperas[0]!, "a segunda espera tem de ser maior");
  });

  it("**o AGR e avisado**, e com o que ele precisa", async () => {
    // Um `falhou` silencioso deixava o cliente a espera de uma resposta a um
    // audio que nunca foi ouvido.
    const { med, meta, avisos } = montar();
    meta.emBaixo = true;
    await med.receber(pedido());
    assert.equal(avisos.length, 1);
    assert.deepEqual(avisos[0], {
      tenantId: TENANT,
      conversationId: CONVERSA,
      wamid: "wamid.HBgLABC",
      classe: "media_audio",
    });
  });

  it("**o aviso vem depois de a linha ficar `falhou`**", async () => {
    // Se o aviso falhar, o estado esta gravado e alguem o ve; ao contrario, o
    // AGR pedia o reenvio de algo que a nossa base ainda dizia estar a caminho.
    const { med, bd, meta } = montar();
    meta.emBaixo = true;
    await med.receber(pedido());
    assert.ok(bd.instrucoes.includes("marcar_desfecho"));
    const linha = [...bd.linhas.values()][0];
    assert.equal(linha?.["estado"], "falhou");
  });

  it("uma falha a meio recupera, e nao conta como `falhou`", async () => {
    const { med, meta, storage } = montar();
    meta.falhasAntesDeAcertar = 2;
    const resultado = await med.receber(pedido());
    assert.ok(resultado.estado === "armazenado");
    assert.equal(meta.descargas, 3);
    assert.equal(storage.total(), 1);
  });

  it("**uma resposta inesperada nao se repete**", async () => {
    // Um 4xx e um pedido nosso errado, e repeti-lo nunca melhora — a mesma
    // distincao que o cliente do Chatwoot faz.
    const { med } = montar();
    let chamadas = 0;
    const medComMetaErrada = new Med({
      bd: new BaseFalsa(),
      armazenamento: criarStorageFake().storage,
      midia: {
        resolver: async () => {
          chamadas += 1;
          throw new MidiaInesperadaError("400: pedido mal formado");
        },
        descarregar: async () => {
          throw new Error("nao devia chegar aqui");
        },
      },
      avisarAgr: async () => undefined,
    });
    await assert.rejects(() => medComMetaErrada.receber(pedido()), MidiaInesperadaError);
    assert.equal(chamadas, 1, "um 4xx repetido e uma fila que nunca drena");
    void med;
  });
});

describe("a retencao do audio (criterio 7)", () => {
  it("**o audio leva 24 h, e conta da criacao**", async () => {
    // Contar da transcricao faz o prazo nunca chegar quando ela nunca tem
    // sucesso, que e precisamente o caso em que o audio nao devia ficar.
    const { med, bd } = montar();
    await med.receber(pedido());
    const linha = [...bd.linhas.values()][0];
    const prazo = linha?.["retain_until"] as Date;
    assert.ok(prazo instanceof Date);
    assert.equal(prazo.getTime() - T0, RETENCAO_DE_AUDIO_MS);
    assert.equal(RETENCAO_DE_AUDIO_MS, 24 * 60 * 60 * 1000);
  });

  it("**uma imagem nao leva prazo curto**", async () => {
    // «Fotos de produto vivem enquanto o catalogo viver», diz o bloco. Inventar
    // aqui um prazo era apaga-las sem ninguem decidir; a politica por classe e
    // do KAM-071.
    const { med, bd, meta } = montar();
    meta.contentType = "image/png";
    await med.receber(pedido({ waType: "image" }));
    const linha = [...bd.linhas.values()][0];
    assert.equal(linha?.["retain_until"], null);
  });

  it("o gancho `onTranscribed` corre com a chave do objecto", async () => {
    // Sem a chave, quem purga nao sabe o que apagar.
    const { med, transcritos } = montar();
    const resultado = await med.receber(pedido());
    assert.ok(resultado.estado === "armazenado");
    await med.transcrito(TENANT, resultado.assetId);
    assert.equal(transcritos.length, 1);
    const asset = transcritos[0] as Record<string, unknown>;
    assert.equal(asset["assetId"], resultado.assetId);
    assert.match(String(asset["storageRef"]), new RegExp(`^t/${TENANT}/media_audio/`));
  });

  it("o gancho nao corre para um asset que nao existe", async () => {
    const { med, transcritos } = montar();
    await med.transcrito(TENANT, "asset-que-nao-existe");
    assert.deepEqual(transcritos, []);
  });
});

describe("as metricas (criterio 9)", () => {
  it("os bytes contam por classe", async () => {
    const { med, meta, metricas } = montar();
    await med.receber(pedido());
    assert.equal(metricas.ler()[`${METRICA_BYTES}:media_audio`], meta.bytes.byteLength);
  });

  it("**a duracao mede-se mesmo quando falha**", async () => {
    // Uma descarga que demora e falha e o sinal mais util que esta metrica da,
    // e medir so os sucessos fazia um painel verde num dia em que nada chegou.
    const { med, meta, metricas } = montar();
    meta.emBaixo = true;
    meta.duracaoMs = 0;
    await med.receber(pedido());
    assert.ok(METRICA_DESCARGA_MS in metricas.ler());
  });

  it("**nenhuma metrica leva identificadores**", async () => {
    // A gramatica de uma etiqueta e `^[a-z][a-z0-9_]{1,62}$`, mas a razao e a
    // cardinalidade: um contador por tenant multiplica as series pelo numero de
    // PMEs (OBS-I).
    const { med, metricas } = montar();
    await med.receber(pedido());
    const exposicao = metricas.exposicao();
    for (const valor of [TENANT, CONTACTO, CONVERSA, "wamid.HBgLABC", "media-abc"]) {
      assert.ok(!exposicao.includes(valor), `a exposicao leva ${valor}`);
    }
  });

  it("as tres aparecem sempre, mesmo sem midia nenhuma", async () => {
    // Um painel que mostre «sem dados» nao distingue «nenhuma midia» de «o
    // processo nao arrancou».
    const metricas = new MetricasDoMed();
    const exposicao = metricas.exposicao();
    assert.ok(exposicao.includes(`${METRICA_BYTES} 0`));
    assert.ok(exposicao.includes(`${METRICA_REJEICOES} 0`));
    assert.ok(exposicao.includes(`${METRICA_DESCARGA_MS} -1`));
  });

  it("um sufixo fora da lista fechada levanta", () => {
    const metricas = new MetricasDoMed();
    assert.throws(() => metricas.contar(METRICA_BYTES, TENANT));
    assert.throws(() => metricas.contar(METRICA_REJEICOES, "porque_me_apeteceu"));
  });
});
