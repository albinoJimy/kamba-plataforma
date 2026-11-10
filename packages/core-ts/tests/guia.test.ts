/**
 * O passo guiado do Embedded Signup (KAM-093).
 *
 * Os *Testes Requeridos* do bloco, pela ordem em que ele os escreve:
 *
 *     unit          normalização e comparação de telefones; lógica do pré-voo;
 *                   temporizadores de 12 h, 24 h e 30 min
 *     integração    simulador de webhooks (KAM-024) com `history`,
 *                   `smb_app_state_sync` e `account_update`; popup abandonado
 *                   e retomado; sincronização > 24 h; divergência de número
 *     contrato      ES v4 só — sem v2/v3 no código
 *     adversarial   número alheio ⇒ bloqueado; `FINISH` 2× ⇒ 1 canal
 *
 * O «link de retoma forjado ⇒ 403» e o isolamento entre sessões são da
 * superfície HTTP e vivem no `services/onboarding-web/tests/guia.test.ts`.
 *
 * ## Os números
 *
 * O repositório é público. Os móveis de ensaio são `+244 9` seguidos de zeros —
 * um bloco que nenhum operador angolano usa, **INDÍCIO** — porque o pré-voo tem
 * de os ler como móveis; o fixo é `+244 2` seguido de zeros. Todos estão no
 * inventário do *gate* 7 com a contagem medida.
 */

import assert from "node:assert/strict";
import { readFileSync, readdirSync } from "node:fs";
import { join } from "node:path";
import { describe, it } from "node:test";

import { Gerador, canalDe, valorDe, interlocutorDe } from "@kamba/meta-sim";

import {
  AvisosEmMemoria,
  CapacidadeEmMemoria,
  GatesEmMemoria,
  GuiaEmMemoria,
  GuiaRecusadoError,
  ITENS_DO_PREFLIGHT,
  LIMITE_DE_ONBOARDINGS,
  MENSAGENS_AO_DONO,
  PassoGuiado,
  RevisaoEmMemoria,
  TRANSICOES_DO_GUIA,
  aplicarWebhook,
  avaliarPreflight,
  lerVersao,
  numeroCoincide,
  sinaisDoWebhook,
  versaoPeloMenos,
  type Atestados,
  type EstadoDoPagamento,
  type LigadorDeCanal,
  type ResultadoDaLigacao,
} from "../src/guia/index.ts";
import {
  CasosEmMemoria,
  Email,
  Nif,
  Telefone,
  lerReferencia,
  linhaDe,
} from "../src/inscricao/index.ts";
import type { ResultadoDoEs } from "../src/onboarding/contrato.ts";
import { modoDoSessionInfo } from "../src/onboarding/onboarding.ts";

const PEPPER = Buffer.alloc(32, 0x5a);
const ANTERIOR = Buffer.alloc(32, 0x2b);
const ASSINATURA = Buffer.alloc(32, 0x3c);

const MOVEL = "+244900000001";
const OUTRO_MOVEL = "+244900000002";
const FIXO = "+244200000001";
const DE_ENSAIO = "+244000000001";

const TUDO_ATESTADO: Atestados = {
  versaoDaApp: "2.24.17",
  appAbertaRecentemente: true,
  numeroEmWhatsAppPessoal: false,
  cartaoInternacional: true,
  donoPresente: true,
};

function relogioFalso(inicio = "2026-11-10T10:00:00.000Z") {
  let agora = new Date(inicio).getTime();
  return {
    agora: (): Date => new Date(agora),
    avancar: (ms: number): void => {
      agora += ms;
    },
  };
}

/**
 * O duplo do KAM-016. **Deduplica por `(tenant, waba)` como a base**, e conta
 * os canais criados: é essa contagem que o «FINISH 2× ⇒ 1 canal» lê, e não o
 * número de chamadas.
 */
class LigadorFalso implements LigadorDeCanal {
  readonly chamadas: ResultadoDoEs[] = [];
  readonly canais = new Set<string>();
  desfecho: ResultadoDaLigacao["desfecho"] = "criado";
  /** Cede o turno antes de responder: é o que deixa dois `FINISH` cruzarem-se. */
  async ligar(entrada: ResultadoDoEs): Promise<ResultadoDaLigacao> {
    this.chamadas.push(entrada);
    await new Promise((r) => setImmediate(r));
    if (this.desfecho !== "criado") return { desfecho: this.desfecho, tentativaId: null };
    const chave = `${entrada.tenant_id}:${entrada.waba_id}`;
    const novo = !this.canais.has(chave);
    this.canais.add(chave);
    return { desfecho: novo ? "criado" : "repetido", tentativaId: `t-${chave}` };
  }
}

class PagamentoFalso {
  estado: EstadoDoPagamento = "desconhecido";
  chamadas = 0;
  async verificar(): Promise<EstadoDoPagamento> {
    this.chamadas += 1;
    return this.estado;
  }
}

async function montar(opcoes: { telefone?: string; maximo?: number } = {}) {
  const relogio = relogioFalso();
  const casos = new CasosEmMemoria(relogio.agora);
  const repositorio = new GuiaEmMemoria(relogio.agora);
  const capacidade = new CapacidadeEmMemoria({
    relogio: relogio.agora,
    ...(opcoes.maximo === undefined ? {} : { maximo: opcoes.maximo }),
  });
  const ligador = new LigadorFalso();
  const gates = new GatesEmMemoria();
  const revisao = new RevisaoEmMemoria();
  const pagamento = new PagamentoFalso();
  const aviso = new AvisosEmMemoria();
  const guia = new PassoGuiado({
    casos,
    repositorio,
    capacidade,
    ligador,
    gates,
    revisao,
    pagamento,
    aviso,
    anelDoPepper: [PEPPER, null],
    chaveDaAssinatura: ASSINATURA,
    origem: "https://onboarding.exemplo.test",
    configId: "config-de-ensaio",
    relogio: relogio.agora,
  });
  let n = 0;
  async function caso(telefone = opcoes.telefone ?? MOVEL, fase: "aguarda_es" | "kyc_pendente" = "aguarda_es") {
    n += 1;
    const { caso: c } = await casos.criar(
      {
        tenantId: `00000000-0000-4000-8000-${String(n).padStart(12, "0")}`,
        origem: "anuncio",
        nomeNegocio: "Loja da Esquina",
        categoriaDeclarada: "mercearia",
        nif: new Nif(`5${String(n).padStart(9, "0")}`, PEPPER),
        telefone: new Telefone(telefone, PEPPER),
        email: new Email("dono@exemplo.test"),
        dispositivoHmac: null,
        redeHmac: null,
        flags: [],
      },
      `chave-${n}`,
    );
    await casos.marcarFase(c.id, fase);
    return c;
  }
  return { relogio, casos, repositorio, capacidade, ligador, gates, revisao, pagamento, aviso, guia, caso };
}

type Montagem = Awaited<ReturnType<typeof montar>>;

function finish(waba = "waba-1", pnid = "pnid-1") {
  return { code: "code-de-ensaio", waba_id: waba, phone_number_id: pnid };
}

/** Leva um caso até `subscrito`. */
async function ateSubscrito(m: Montagem, telefone = MOVEL, pnid = "pnid-1") {
  const c = await m.caso(telefone);
  await m.guia.preflight(c.id, TUDO_ATESTADO);
  const inicio = await m.guia.iniciar(c.id);
  assert.equal(inicio.desfecho, "popup");
  const fim = await m.guia.concluir(c.id, finish(`waba-${c.id}`, pnid));
  assert.equal(fim.estado, "subscrito");
  return c;
}

// ---------------------------------------------------------------- unit

describe("KAM-093 unit: telefones", () => {
  it("linhaDe: 9 movel, 2 fixo, o resto desconhecido", () => {
    assert.equal(linhaDe(MOVEL), "movel");
    assert.equal(linhaDe(FIXO), "fixo");
    assert.equal(linhaDe(DE_ENSAIO), "desconhecido");
    assert.equal(new Telefone("900 000 001", PEPPER).linha, "movel");
  });

  it("o display_phone_number formatado coincide com o telefone do OTP", () => {
    const hmac = new Telefone(MOVEL, PEPPER).hmac;
    for (const forma of ["+244 900 000 001", "244 900 000 001", "+244-900-000-001", "900000001"]) {
      assert.equal(numeroCoincide(forma, hmac, [PEPPER, null]), true, forma);
    }
  });

  it("outro numero, outro indicativo, vazio ou lixo NAO coincide, e nao lanca", () => {
    const hmac = new Telefone(MOVEL, PEPPER).hmac;
    for (const forma of [OUTRO_MOVEL, "+351 900 000 001", "", null, 900000001, "abc"]) {
      assert.equal(numeroCoincide(forma, hmac, [PEPPER, null]), false, String(forma));
    }
  });

  it("uma rotacao do pepper entre o OTP e o ES nao faz o numero legitimo parecer alheio", () => {
    const hmacAntigo = new Telefone(MOVEL, ANTERIOR).hmac;
    assert.equal(numeroCoincide("+244 900 000 001", hmacAntigo, [PEPPER, ANTERIOR]), true);
    assert.equal(numeroCoincide("+244 900 000 001", hmacAntigo, [PEPPER, null]), false);
  });
});

describe("KAM-093 unit: pre-voo", () => {
  const factos = {
    linha: "movel" as const,
    screening: "aprovada" as const,
    displayName: "Loja da Esquina",
    termosBloqueados: [],
  };
  const agora = new Date("2026-11-10T10:00:00Z");

  it("sete itens, na forma { id, tipo, ok, detalhe }, e todos ok abre", () => {
    const p = avaliarPreflight(TUDO_ATESTADO, factos, agora);
    assert.deepEqual(p.itens.map((i) => i.id), [...ITENS_DO_PREFLIGHT]);
    assert.ok(p.itens.every((i) => i.ok && i.detalhe === "ok"));
    assert.equal(p.podeAbrir, true);
    assert.equal(p.rota, "coexistencia");
    assert.deepEqual(
      p.itens.map((i) => i.tipo),
      ["atestado", "auto", "atestado", "atestado", "auto", "auto", "atestado"],
    );
  });

  it("a versao compara-se componente a componente, e 2.24.9 e antiga", () => {
    assert.deepEqual(lerVersao("2.24.17"), [2, 24, 17]);
    assert.deepEqual(lerVersao(" 2.25.1.79 "), [2, 25, 1]);
    assert.equal(lerVersao("2.24"), null);
    assert.equal(versaoPeloMenos([2, 24, 9], [2, 24, 17]), false);
    assert.equal(versaoPeloMenos([2, 24, 17], [2, 24, 17]), true);
    assert.equal(versaoPeloMenos([3, 0, 0], [2, 24, 17]), true);
    const antiga = avaliarPreflight({ ...TUDO_ATESTADO, versaoDaApp: "2.24.9" }, factos, agora);
    assert.equal(antiga.itens[0]?.detalhe, "versao_antiga");
    assert.equal(antiga.podeAbrir, false);
  });

  it("um atestado so vale se for true: 'true', 1 e 'sim' nao valem", () => {
    for (const falso of ["true", 1, "sim", undefined]) {
      const p = avaliarPreflight({ ...TUDO_ATESTADO, donoPresente: falso }, factos, agora);
      assert.equal(p.podeAbrir, false, String(falso));
    }
  });

  it("app sem abertura recente nao passa, mesmo com versao boa", () => {
    const p = avaliarPreflight({ ...TUDO_ATESTADO, appAbertaRecentemente: false }, factos, agora);
    assert.equal(p.itens[0]?.ok, false);
  });

  it("fixo NAO bloqueia: muda a rota para cloud_only", () => {
    const p = avaliarPreflight(TUDO_ATESTADO, { ...factos, linha: "fixo" }, agora);
    assert.equal(p.itens[1]?.detalhe, "fixo_rota_cloud_only");
    assert.equal(p.podeAbrir, true);
    assert.equal(p.rota, "cloud_only");
  });

  it("numero que nao se le bloqueia", () => {
    const p = avaliarPreflight(TUDO_ATESTADO, { ...factos, linha: "desconhecido" }, agora);
    assert.equal(p.podeAbrir, false);
  });

  it("WhatsApp pessoal pede conversao; sem cartao pede cartao; categoria e nome", () => {
    const pessoal = avaliarPreflight({ ...TUDO_ATESTADO, numeroEmWhatsAppPessoal: true }, factos, agora);
    assert.equal(pessoal.itens[2]?.detalhe, "converter_para_business");
    const semCartao = avaliarPreflight({ ...TUDO_ATESTADO, cartaoInternacional: false }, factos, agora);
    assert.equal(semCartao.itens[3]?.detalhe, "sem_cartao_internacional");
    const recusada = avaliarPreflight(TUDO_ATESTADO, { ...factos, screening: "recusada" }, agora);
    assert.equal(recusada.itens[4]?.detalhe, "categoria_recusada");
    const bloqueado = avaliarPreflight(
      TUDO_ATESTADO,
      { ...factos, displayName: "Farmácia Barata", termosBloqueados: ["farmacia"] },
      agora,
    );
    assert.equal(bloqueado.itens[5]?.detalhe, "nome_com_termo_bloqueado");
    const vazio = avaliarPreflight(TUDO_ATESTADO, { ...factos, displayName: "   " }, agora);
    assert.equal(vazio.itens[5]?.detalhe, "nome_vazio");
  });

  it("nao ha item para os NAO VERIFICADOS (H3 e '>= 7 dias')", () => {
    assert.equal(ITENS_DO_PREFLIGHT.length, 7);
    assert.ok(!ITENS_DO_PREFLIGHT.some((i) => /dias|elegib|h3/i.test(i)));
  });
});

// ---------------------------------------------------------------- guia

describe("KAM-093: a pagina so abre com caso aguarda_es (criterio 1)", () => {
  it("sem caso, ou noutra fase, recusa", async () => {
    const m = await montar();
    await assert.rejects(m.guia.abrir("00000000-0000-4000-8000-999999999999"), GuiaRecusadoError);
    const c = await m.caso(MOVEL, "kyc_pendente");
    await assert.rejects(m.guia.abrir(c.id), (e: unknown) => e instanceof GuiaRecusadoError && e.motivo === "fase_errada");
  });

  it("o popup e v4: sessionInfoVersion '3' e o featureType de coexistencia; cloud_only sem featureType", async () => {
    const m = await montar();
    const c = await m.caso();
    await m.guia.preflight(c.id, TUDO_ATESTADO);
    const inicio = await m.guia.iniciar(c.id);
    assert.equal(inicio.desfecho, "popup");
    if (inicio.desfecho !== "popup") return;
    assert.equal(inicio.configuracao.config_id, "config-de-ensaio");
    assert.deepEqual(inicio.configuracao.extras, {
      sessionInfoVersion: "3",
      featureType: "whatsapp_business_app_onboarding",
    });
    assert.deepEqual(m.guia.configuracao("cloud_only").extras, { sessionInfoVersion: "3" });
  });

  it("sem pre-voo, ou com pre-voo por cumprir, nao abre o popup", async () => {
    const m = await montar();
    const c = await m.caso();
    await assert.rejects(m.guia.iniciar(c.id), (e: unknown) => e instanceof GuiaRecusadoError && e.motivo === "preflight_em_falta");
    await m.guia.preflight(c.id, { ...TUDO_ATESTADO, donoPresente: false });
    await assert.rejects(m.guia.iniciar(c.id), (e: unknown) => e instanceof GuiaRecusadoError && e.motivo === "preflight_por_cumprir");
    assert.equal(m.capacidade.vivas(), 0);
  });

  it("o pre-voo fica gravado, e le o tipo de linha do telefone do OTP", async () => {
    const m = await montar();
    const c = await m.caso(FIXO);
    await m.guia.preflight(c.id, TUDO_ATESTADO);
    const guardado = await m.repositorio.ler(c.id);
    assert.equal(guardado?.preflight?.rota, "cloud_only");
    assert.equal(guardado?.preflight?.itens.length, 7);
  });
});

describe("KAM-093: capacidade (criterio 8)", () => {
  it(`dez concedidos em sete dias, o decimo primeiro vai para lista_espera`, async () => {
    const m = await montar();
    const casos = [];
    for (let i = 0; i < LIMITE_DE_ONBOARDINGS + 1; i += 1) {
      const c = await m.caso();
      await m.guia.preflight(c.id, TUDO_ATESTADO);
      casos.push(c);
    }
    for (let i = 0; i < LIMITE_DE_ONBOARDINGS; i += 1) {
      assert.equal((await m.guia.iniciar(casos[i]!.id)).desfecho, "popup");
    }
    const ultimo = casos[LIMITE_DE_ONBOARDINGS]!;
    assert.equal((await m.guia.iniciar(ultimo.id)).desfecho, "lista_espera");
    // E o caso nao passou a `iniciado`: nao ha popup sem lugar.
    assert.equal((await m.repositorio.ler(ultimo.id))?.estado, "pre_voo");
    // Ao fim da janela, o lugar volta.
    m.relogio.avancar(7 * 86_400_000 + 1);
    assert.equal((await m.guia.iniciar(ultimo.id)).desfecho, "popup");
  });

  it("repetir o iniciar do mesmo caso nao gasta outro lugar", async () => {
    const m = await montar({ maximo: 1 });
    const c = await m.caso();
    await m.guia.preflight(c.id, TUDO_ATESTADO);
    await m.guia.iniciar(c.id);
    await m.guia.iniciar(c.id);
    assert.equal(m.capacidade.vivas(), 1);
  });
});

describe("KAM-093: abandono e retoma (criterio 5)", () => {
  it("popup fechado => abandonado, e o lugar devolve-se", async () => {
    const m = await montar();
    const c = await m.caso();
    await m.guia.preflight(c.id, TUDO_ATESTADO);
    await m.guia.iniciar(c.id);
    assert.equal(await m.guia.cancelar(c.id), "abandonado");
    assert.equal(m.capacidade.vivas(), 0);
  });

  it("30 min sem FINISH => abandonado; 29 min ainda nao", async () => {
    const m = await montar();
    const c = await m.caso();
    await m.guia.preflight(c.id, TUDO_ATESTADO);
    await m.guia.iniciar(c.id);
    m.relogio.avancar(29 * 60_000);
    assert.equal(await m.guia.abandonarVencidos(), 0);
    m.relogio.avancar(2 * 60_000);
    assert.equal(await m.guia.abandonarVencidos(), 1);
    assert.equal((await m.repositorio.ler(c.id))?.estado, "abandonado");
  });

  it("retoma-se pelo mesmo caso, sem criar um segundo", async () => {
    const m = await montar();
    const c = await m.caso();
    await m.guia.preflight(c.id, TUDO_ATESTADO);
    await m.guia.iniciar(c.id);
    await m.guia.cancelar(c.id);
    const antes = (await m.casos.porTelefoneHmac(c.telefoneHmac)).length;
    assert.equal((await m.guia.iniciar(c.id)).desfecho, "popup");
    assert.equal((await m.repositorio.ler(c.id))?.estado, "iniciado");
    assert.equal((await m.casos.porTelefoneHmac(c.telefoneHmac)).length, antes);
    const fim = await m.guia.concluir(c.id, finish());
    assert.equal(fim.estado, "subscrito");
  });

  it("a ligacao de retoma e uma referencia 'retoma' do mesmo caso", async () => {
    const m = await montar();
    const c = await m.caso();
    const url = new URL(m.guia.ligacaoDeRetoma(c.id));
    assert.equal(url.pathname, "/ligar");
    assert.equal(lerReferencia("retoma", url.searchParams.get("r"), [ASSINATURA, null], m.relogio.agora), c.id);
  });
});

describe("KAM-093: FINISH e a ligacao (criterios 1 e 9)", () => {
  it("o tenant_id vai do CASO, e nao do corpo do popup", async () => {
    const m = await montar();
    const c = await m.caso();
    await m.guia.preflight(c.id, TUDO_ATESTADO);
    await m.guia.iniciar(c.id);
    await m.guia.concluir(c.id, { ...finish(), tenant_id: "00000000-0000-4000-8000-0000000000ff" } as never);
    assert.equal(m.ligador.chamadas[0]?.tenant_id, c.tenantId);
  });

  it("ADVERSARIAL: FINISH repetido 2x => 1 canal e 1 chamada a Meta", async () => {
    const m = await montar();
    const c = await m.caso();
    await m.guia.preflight(c.id, TUDO_ATESTADO);
    await m.guia.iniciar(c.id);
    const a = await m.guia.concluir(c.id, finish());
    const b = await m.guia.concluir(c.id, finish());
    assert.equal(a.novo, true);
    assert.equal(b.novo, false);
    assert.equal(m.ligador.chamadas.length, 1);
    assert.equal(m.ligador.canais.size, 1);
  });

  it("ADVERSARIAL: dois FINISH concorrentes => 1 canal, e um so passa a es_concluido", async () => {
    const m = await montar();
    const c = await m.caso();
    await m.guia.preflight(c.id, TUDO_ATESTADO);
    await m.guia.iniciar(c.id);
    const [a, b] = await Promise.all([m.guia.concluir(c.id, finish()), m.guia.concluir(c.id, finish())]);
    assert.equal(m.ligador.canais.size, 1);
    assert.equal([a.novo, b.novo].filter(Boolean).length, 1);
    assert.equal((await m.repositorio.ler(c.id))?.estado, "subscrito");
  });

  it("um segundo FINISH com OUTRO numero e recusado, nao e repeticao", async () => {
    const m = await montar();
    const c = await ateSubscrito(m);
    await assert.rejects(m.guia.concluir(c.id, finish("waba-x", "pnid-outro")), GuiaRecusadoError);
    assert.equal(m.ligador.chamadas.length, 1);
  });

  it("FINISH sem iniciar nao liga nada", async () => {
    const m = await montar();
    const c = await m.caso();
    await m.guia.preflight(c.id, TUDO_ATESTADO);
    await assert.rejects(m.guia.concluir(c.id, finish()), GuiaRecusadoError);
    assert.equal(m.ligador.chamadas.length, 0);
  });

  it("o corpo do FINISH nunca leva token nem PIN: so code, waba, numero e session_info", async () => {
    const m = await montar();
    await ateSubscrito(m);
    assert.deepEqual(Object.keys(m.ligador.chamadas[0] ?? {}).sort(), [
      "code",
      "phone_number_id",
      "session_info",
      "tenant_id",
      "waba_id",
    ]);
  });
});

describe("KAM-093: o numero ligado e o do OTP (criterio 4)", () => {
  it("coincide => numeroConfirmado, e o guia segue", async () => {
    const m = await montar();
    const c = await ateSubscrito(m);
    assert.equal(await m.guia.confirmarNumero("pnid-1", "+244 900 000 001"), true);
    assert.equal((await m.repositorio.ler(c.id))?.numeroConfirmado, true);
    assert.equal(m.revisao.abertos.size, 0);
  });

  it("ADVERSARIAL: numero alheio => falhado, review_case es_falhado, meta_es vermelho, e preso", async () => {
    const m = await montar();
    const c = await ateSubscrito(m);
    assert.equal(await m.guia.confirmarNumero("pnid-1", "+244 900 000 002"), false);
    const guardado = await m.repositorio.ler(c.id);
    assert.equal(guardado?.estado, "falhado");
    assert.equal(guardado?.motivo, "numero_divergente");
    assert.equal(m.revisao.abertos.get(`${c.id}:es_falhado`), "numero_divergente");
    assert.deepEqual(m.gates.de(c.id, "meta_es"), { verde: false, motivo: "numero_divergente" });
    // Preso: a pagina nao o desprende, e a sincronizacao que chegue depois
    // nao o leva a `verificado`.
    await assert.rejects(m.guia.iniciar(c.id), (e: unknown) => e instanceof GuiaRecusadoError && e.motivo === "preso_em_revisao");
    await m.guia.sincronizacao("pnid-1", "concluida");
    assert.equal((await m.repositorio.ler(c.id))?.estado, "falhado");
  });
});

describe("KAM-093: sincronizacao e gates (criterios 3 e 6)", () => {
  it("a_sincronizar -> concluida -> verificado -> (pagamento) pronto, com meta_es verde", async () => {
    const m = await montar();
    const c = await ateSubscrito(m);
    await m.guia.confirmarNumero("pnid-1", "+244 900 000 001");
    assert.equal(await m.guia.sincronizacao("pnid-1", "a_sincronizar"), "a_sincronizar");
    assert.equal(await m.guia.sincronizacao("pnid-1", "concluida"), "verificado");
    assert.deepEqual(m.gates.de(c.id, "meta_es"), { verde: true, motivo: "sincronizado_e_verificado" });
    m.pagamento.estado = "detectado";
    const v = await m.guia.verificarPagamento(c.id);
    assert.equal(v.verde, true);
    assert.equal((await m.repositorio.ler(c.id))?.estado, "pronto");
  });

  it("sem numero confirmado, a sincronizacao concluida NAO chega a verificado", async () => {
    const m = await montar();
    const c = await ateSubscrito(m);
    await m.guia.sincronizacao("pnid-1", "a_sincronizar");
    await m.guia.sincronizacao("pnid-1", "concluida");
    assert.equal((await m.repositorio.ler(c.id))?.estado, "a_sincronizar");
  });

  it("12 h => lembrete ao dono; 24 h => falhado, aviso, meta_es vermelho e repeticao do ES sem novo registo", async () => {
    const m = await montar();
    const c = await ateSubscrito(m);
    await m.guia.confirmarNumero("pnid-1", "+244 900 000 001");
    await m.guia.sincronizacao("pnid-1", "a_sincronizar");
    await m.guia.sincronizacao("pnid-1", "lembrete_12h");
    assert.equal(m.aviso.enviados.at(-1)?.mensagem, "sincronizacao_lembrete");
    assert.equal(await m.guia.sincronizacao("pnid-1", "vencida_24h"), "falhado");
    assert.equal(m.aviso.enviados.at(-1)?.mensagem, "sincronizacao_falhou");
    assert.deepEqual(m.gates.de(c.id, "meta_es"), { verde: false, motivo: "sincronizacao_vencida" });
    assert.equal((await m.guia.iniciar(c.id)).desfecho, "popup");
  });

  it("2593109 (sem historico) chega como conclusao normal", async () => {
    // O KAM-017 conclui sem historico e emite o mesmo sinal; aqui nao ha ramo
    // de erro para ele.
    const m = await montar();
    await ateSubscrito(m);
    await m.guia.confirmarNumero("pnid-1", "+244 900 000 001");
    await m.guia.sincronizacao("pnid-1", "a_sincronizar");
    assert.equal(await m.guia.sincronizacao("pnid-1", "concluida"), "verificado");
  });

  it("cloud_only nao sincroniza: o numero confirmado basta para verificado", async () => {
    const m = await montar();
    await ateSubscrito(m, FIXO);
    await m.guia.confirmarNumero("pnid-1", "+244 200 000 001");
    assert.equal((await m.repositorio.ler((await m.repositorio.porPhoneNumberId("pnid-1"))!))?.estado, "verificado");
  });

  it("sem pagamento detectado: meta_pagamento vermelho, alternativa MPS, e repete-se sem refazer o ES", async () => {
    const m = await montar();
    const c = await ateSubscrito(m);
    for (const estado of ["desconhecido", "ausente"] as const) {
      m.pagamento.estado = estado;
      const v = await m.guia.verificarPagamento(c.id);
      assert.deepEqual(v, { estado, verde: false, alternativa: "mps" });
      assert.deepEqual(m.gates.de(c.id, "meta_pagamento"), { verde: false, motivo: estado });
    }
    m.pagamento.estado = "detectado";
    assert.equal((await m.guia.verificarPagamento(c.id)).verde, true);
    assert.equal(m.ligador.chamadas.length, 1);
  });

  it("sem pagamento, um guia verificado nao passa a pronto", async () => {
    const m = await montar();
    const c = await ateSubscrito(m);
    await m.guia.confirmarNumero("pnid-1", "+244 900 000 001");
    await m.guia.sincronizacao("pnid-1", "a_sincronizar");
    await m.guia.sincronizacao("pnid-1", "concluida");
    await m.guia.verificarPagamento(c.id);
    assert.equal((await m.repositorio.ler(c.id))?.estado, "verificado");
  });
});

describe("KAM-093: desligado e reconexao (criterio 7)", () => {
  it("PARTNER_REMOVED => desligado, aviso por SMS com a ligacao de retoma, e o ES refaz-se", async () => {
    const m = await montar();
    const c = await ateSubscrito(m);
    await m.guia.confirmarNumero("pnid-1", "+244 900 000 001");
    assert.equal(await m.guia.desligado("pnid-1"), true);
    const aviso = m.aviso.enviados.at(-1);
    assert.equal(aviso?.mensagem, "reconectar");
    assert.equal(aviso?.via, "sms");
    assert.match(aviso?.ligacao ?? "", /\/ligar\?r=/);
    assert.equal(await m.guia.desligado("pnid-1"), false, "o segundo PARTNER_REMOVED nao transita");
    assert.equal((await m.guia.iniciar(c.id)).desfecho, "popup");
  });

  it("o alarme de desligado e o de inactividade sao do KAM-115: o guia nao os repete", () => {
    assert.deepEqual([...MENSAGENS_AO_DONO], ["reconectar", "sincronizacao_falhou", "sincronizacao_lembrete"]);
  });
});

describe("KAM-093 integracao: o simulador de webhooks do KAM-024", () => {
  const g = new Gerador("kam093/simulador");
  const quem = interlocutorDe(g);

  function corpo(campo: "history" | "smb_app_state_sync" | "account_update", display: string, pnid = "pnid-1") {
    const canal = { ...canalDe(g), phoneNumberId: pnid, displayPhoneNumber: display };
    return {
      object: "whatsapp_business_account",
      entry: [
        {
          id: canal.wabaId,
          changes: [
            {
              field: campo,
              value: valorDe(g, campo, {
                canal,
                quem,
                ...(campo === "account_update" ? { motivo: "PRIMARY_INACTIVITY" as const } : {}),
              }),
            },
          ],
        },
      ],
    };
  }

  it("o metadata de cada campo da o numero e o phone_number_id", () => {
    for (const campo of ["history", "smb_app_state_sync", "account_update"] as const) {
      const sinais = sinaisDoWebhook(corpo(campo, "+244 900 000 001"));
      assert.equal(sinais.length, 1, campo);
      assert.equal(sinais[0]?.phoneNumberId, "pnid-1");
      assert.equal(sinais[0]?.displayPhoneNumber, "+244 900 000 001");
    }
  });

  it("history do numero certo confirma e poe a sincronizar; account_update PARTNER_REMOVED desliga", async () => {
    const m = await montar();
    const c = await ateSubscrito(m);
    assert.deepEqual(await aplicarWebhook(m.guia, corpo("history", "+244 900 000 001")), { divergentes: 0, desligados: 0 });
    assert.equal((await m.repositorio.ler(c.id))?.estado, "a_sincronizar");
    await aplicarWebhook(m.guia, corpo("smb_app_state_sync", "+244 900 000 001"));
    await m.guia.sincronizacao("pnid-1", "concluida");
    assert.equal((await m.repositorio.ler(c.id))?.estado, "verificado");
    const r = await aplicarWebhook(m.guia, corpo("account_update", "+244 900 000 001"));
    assert.equal(r.desligados, 1);
    assert.equal((await m.repositorio.ler(c.id))?.estado, "desligado");
  });

  it("ADVERSARIAL: o primeiro history de um numero alheio prende o guia ANTES de o pôr a sincronizar", async () => {
    const m = await montar();
    const c = await ateSubscrito(m);
    const r = await aplicarWebhook(m.guia, corpo("history", "+244 900 000 002"));
    assert.equal(r.divergentes, 1);
    assert.equal((await m.repositorio.ler(c.id))?.estado, "falhado");
  });

  it("o numero do simulador (999...) nunca coincide com um telefone do OTP", async () => {
    const m = await montar();
    await ateSubscrito(m);
    const canal = canalDe(new Gerador("kam093/ficticio"));
    assert.equal(await m.guia.confirmarNumero("pnid-1", canal.displayPhoneNumber), false);
  });
});

describe("KAM-093 revisao adversarial: os achados, cada um com o seu ensaio", () => {
  it("achado 1: uma reconexao com OUTRO numero nao herda a confirmacao do antigo", async () => {
    const m = await montar();
    const c = await ateSubscrito(m);
    await m.guia.confirmarNumero("pnid-1", "+244 900 000 001");
    await m.guia.sincronizacao("pnid-1", "a_sincronizar");
    await m.guia.sincronizacao("pnid-1", "concluida");
    assert.equal(await m.guia.desligado("pnid-1"), true);
    assert.equal((await m.guia.iniciar(c.id)).desfecho, "popup");
    const limpo = await m.repositorio.ler(c.id);
    assert.equal(limpo?.numeroConfirmado, false);
    assert.equal(limpo?.sincronizado, false);
    assert.equal(limpo?.phoneNumberId, null);
    await m.guia.concluir(c.id, finish(`waba-${c.id}`, "pnid-2"));
    assert.equal(await m.guia.confirmarNumero("pnid-2", "+244 900 000 002"), false);
    await m.guia.sincronizacao("pnid-2", "concluida");
    assert.equal((await m.repositorio.ler(c.id))?.estado, "falhado");
    assert.deepEqual(m.gates.de(c.id, "meta_es"), { verde: false, motivo: "numero_divergente" });
  });

  it("achado 1: o mesmo, a voltar por sincronizacao vencida", async () => {
    const m = await montar();
    const c = await ateSubscrito(m);
    await m.guia.confirmarNumero("pnid-1", "+244 900 000 001");
    await m.guia.sincronizacao("pnid-1", "vencida_24h");
    await m.guia.iniciar(c.id);
    await m.guia.concluir(c.id, finish(`waba-${c.id}`, "pnid-2"));
    assert.equal(await m.guia.confirmarNumero("pnid-2", "+244 900 000 002"), false);
  });

  it("achado 3: o session_info de cada rota passa o modoDoSessionInfo do KAM-016, e diz a rota certa", async () => {
    const m = await montar();
    assert.equal(modoDoSessionInfo(m.guia.sessionInfo("coexistencia")), "coexistencia");
    assert.equal(modoDoSessionInfo(m.guia.sessionInfo("cloud_only")), "cloud_only");
    // E e esse o que segue para o GWY, nao um eco da pagina.
    const fixo = await ateSubscrito(m, FIXO);
    void fixo;
    const enviado = m.ligador.chamadas.at(-1)?.session_info ?? {};
    assert.equal(modoDoSessionInfo(enviado), "cloud_only");
  });

  it("achado 4: a divergencia prende mesmo com o guia ja falhado por sincronizacao vencida", async () => {
    const m = await montar();
    const c = await ateSubscrito(m);
    await m.guia.sincronizacao("pnid-1", "vencida_24h");
    assert.equal((await m.repositorio.ler(c.id))?.motivo, "sincronizacao_vencida");
    assert.equal(await m.guia.confirmarNumero("pnid-1", "+244 900 000 002"), false);
    assert.equal((await m.repositorio.ler(c.id))?.motivo, "numero_divergente");
    await assert.rejects(m.guia.iniciar(c.id), (e: unknown) => e instanceof GuiaRecusadoError && e.motivo === "preso_em_revisao");
  });

  it("achado 4: e com o guia desligado, de onde a matriz nao leva a falhado", async () => {
    const m = await montar();
    const c = await ateSubscrito(m);
    await m.guia.desligado("pnid-1");
    assert.equal(await m.guia.confirmarNumero("pnid-1", "+244 900 000 002"), false);
    await assert.rejects(m.guia.iniciar(c.id), GuiaRecusadoError);
  });

  it("achado 5: o temporizador dos 30 min nao abandona um FINISH a meio da ligacao", async () => {
    const m = await montar();
    const c = await m.caso();
    await m.guia.preflight(c.id, TUDO_ATESTADO);
    await m.guia.iniciar(c.id);
    m.relogio.avancar(31 * 60_000);
    // O ligador cede o turno; o temporizador corre enquanto a Meta responde.
    const fim = m.guia.concluir(c.id, finish());
    await new Promise((r) => setImmediate(r));
    assert.equal(await m.guia.abandonarVencidos(), 0);
    assert.equal((await fim).estado, "subscrito");
    assert.equal(m.capacidade.vivas(), 1);
    assert.equal(await m.repositorio.porPhoneNumberId("pnid-1"), c.id);
  });

  it("achado 5: lista_espera do GWY e recusa do GWY passam a falhado e devolvem o lugar", async () => {
    for (const [desfecho, motivo] of [
      ["lista_espera", "tecto_da_meta"],
      ["recusado", "ligacao_recusada"],
    ] as const) {
      const m = await montar();
      m.ligador.desfecho = desfecho;
      const c = await m.caso();
      await m.guia.preflight(c.id, TUDO_ATESTADO);
      await m.guia.iniciar(c.id);
      assert.equal((await m.guia.concluir(c.id, finish())).estado, "falhado");
      assert.equal((await m.repositorio.ler(c.id))?.motivo, motivo);
      assert.equal(m.capacidade.vivas(), 0);
      assert.equal((await m.guia.iniciar(c.id)).desfecho, "popup", "e o ES repete-se");
    }
  });

  it("achado 6: uma reconexao cloud_only chega a verificado", async () => {
    const m = await montar();
    const c = await ateSubscrito(m, FIXO);
    await m.guia.confirmarNumero("pnid-1", "+244 200 000 001");
    assert.equal((await m.repositorio.ler(c.id))?.estado, "verificado");
    await m.guia.desligado("pnid-1");
    await m.guia.iniciar(c.id);
    await m.guia.concluir(c.id, finish(`waba-${c.id}`, "pnid-1"));
    await m.guia.confirmarNumero("pnid-1", "+244 200 000 001");
    assert.equal((await m.repositorio.ler(c.id))?.estado, "verificado");
  });

  it("achado 7: um history de numero alheio NUNCA passa o guia por a_sincronizar", async () => {
    const m = await montar();
    const c = await ateSubscrito(m);
    const passagens: string[] = [];
    const original = m.repositorio.transitar.bind(m.repositorio);
    m.repositorio.transitar = async (id, de, para, campos) => {
      passagens.push(para);
      return original(id, de, para, campos);
    };
    const g = new Gerador("kam093/ordem");
    const canal = { ...canalDe(g), phoneNumberId: "pnid-1", displayPhoneNumber: "+244 900 000 002" };
    await aplicarWebhook(m.guia, {
      entry: [{ changes: [{ field: "history", value: valorDe(g, "history", { canal, quem: interlocutorDe(g) }) }] }],
    });
    assert.deepEqual(passagens, ["falhado"]);
    assert.equal((await m.repositorio.ler(c.id))?.estado, "falhado");
  });
});

describe("KAM-093 contrato: so v4", () => {
  it("o modulo nao refere v2 nem v3 do Embedded Signup", () => {
    const pasta = join(import.meta.dirname, "..", "src", "guia");
    for (const ficheiro of readdirSync(pasta)) {
      const texto = readFileSync(join(pasta, ficheiro), "utf8");
      assert.doesNotMatch(texto, /embedded[ _-]?signup[ _-]?v[23]\b|\bES v[23]\b|sessionInfoVersion["']?\s*[:=]\s*["']?[12]\b/i, ficheiro);
    }
  });

  it("a matriz do guia: abandonado so sai de iniciado, e os terminais voltam a iniciado", () => {
    const deOnde = Object.entries(TRANSICOES_DO_GUIA)
      .filter(([, para]) => para.includes("abandonado"))
      .map(([de]) => de);
    assert.deepEqual(deOnde, ["iniciado"]);
    for (const terminal of ["abandonado", "falhado", "desligado"] as const) {
      assert.deepEqual(TRANSICOES_DO_GUIA[terminal], ["iniciado"]);
    }
  });
});
