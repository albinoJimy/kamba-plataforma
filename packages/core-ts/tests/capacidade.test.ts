/**
 * A lista de espera do limite de onboarding da Meta (KAM-095).
 *
 * Os *Testes Requeridos* do bloco, pela ordem em que ele os escreve:
 *
 *     unit          cálculo de vaga na janela deslizante; ordem FIFO;
 *                   expiração de convites
 *     integração    promoção automática ao libertar vaga; notificações com
 *                   fornecedor falso (o `CapacityGate` real com o guia vive no
 *                   `services/onboarding-web/tests/guia.test.ts`)
 *     concorrência  20 trabalhadores a pedir 1 vaga ⇒ 1 convite (aqui sobre o
 *                   duplo, que serializa como a base; contra o PostgreSQL em
 *                   `db/tests/test_lista_espera_schema.py`)
 *     adversarial   (a) bot com 1.000 registos; (b) convite expirado ou de
 *                   outro caso; (c) salto de fila; (d) redelivery
 *
 * Os casos são um duplo mínimo de `id` e `fase`: a fila não lê mais nada do
 * caso, e um `CasosEmMemoria` pedia telefones que o *gate* 7 inventaria.
 */

import assert from "node:assert/strict";
import { describe, it } from "node:test";

import {
  AvisosDaListaEmMemoria,
  ESTADOS_DA_ENTRADA,
  LIMITE_POR_OMISSAO,
  ListaDeEspera,
  ListaEmMemoria,
  ListaRecusadaError,
  MetricasDaLista,
  VALIDADE_DO_CONVITE_H,
  estimar,
  hashDoConvite,
} from "../src/capacidade/index.ts";
import type { Caso, Fase } from "../src/inscricao/contrato.ts";

const HORA = 3_600_000;
const DIA = 24 * HORA;
const T0 = Date.parse("2026-11-16T08:00:00.000Z");

/** O duplo dos casos: só a fase. */
class Casos {
  readonly fases = new Map<string, Fase>();

  async porId(id: string): Promise<Caso | null> {
    const fase = this.fases.get(id);
    return fase === undefined ? null : ({ id, fase } as unknown as Caso);
  }

  async marcarFase(id: string, fase: Fase): Promise<boolean> {
    if (!this.fases.has(id)) return false;
    this.fases.set(id, fase);
    return true;
  }
}

function id(n: number): string {
  return `00000000-0000-4000-8000-${String(n).padStart(12, "0")}`;
}

interface Montagem {
  readonly casos: Casos;
  readonly repo: ListaEmMemoria;
  readonly aviso: AvisosDaListaEmMemoria;
  readonly lista: ListaDeEspera;
  readonly metricas: MetricasDaLista;
  readonly relogio: { agora: number };
  avancar(ms: number): void;
}

function montar(maximo = 2): Montagem {
  const relogio = { agora: T0 };
  const agora = (): Date => new Date(relogio.agora);
  const casos = new Casos();
  const repo = new ListaEmMemoria(casos, agora, { ...LIMITE_POR_OMISSAO, maximo });
  const aviso = new AvisosDaListaEmMemoria();
  const metricas = new MetricasDaLista();
  const lista = new ListaDeEspera({ repositorio: repo, aviso, origem: "https://onboarding.exemplo.test", metricas, relogio: agora });
  return {
    casos,
    repo,
    aviso,
    lista,
    metricas,
    relogio,
    avancar: (ms) => {
      relogio.agora += ms;
    },
  };
}

/** Cria `n` casos em `aguarda_es`, um segundo de intervalo cada (a ordem FIFO). */
async function entrarNaFila(m: Montagem, ns: readonly number[]): Promise<("granted" | "lista_espera")[]> {
  const r: ("granted" | "lista_espera")[] = [];
  for (const n of ns) {
    m.casos.fases.set(id(n), "aguarda_es");
    r.push(await m.lista.reserve(id(n)));
    m.avancar(1000);
  }
  return r;
}

function conviteDe(m: Montagem, n: number): string {
  const enviado = [...m.aviso.enviados].reverse().find((e) => e.onboardingId === id(n));
  assert.ok(enviado !== undefined, `nenhum convite foi mandado ao caso ${n}`);
  const c = new URL(enviado.ligacao).searchParams.get("convite");
  assert.ok(c !== null && c.length > 0);
  return c;
}

async function recusa(promessa: Promise<unknown>, motivo: string): Promise<void> {
  await assert.rejects(promessa, (e: unknown) => e instanceof ListaRecusadaError && e.motivo === motivo);
}

describe("unit: vaga, FIFO e janela deslizante", () => {
  it("vaga = limite − concluídos: os dois primeiros têm vaga, o terceiro espera na posição 1", async () => {
    const m = montar(2);
    assert.deepEqual(await entrarNaFila(m, [1, 2, 3]), ["granted", "granted", "lista_espera"]);
    const p = await m.lista.posicao(id(3));
    assert.equal(p?.estado, "aguardando");
    assert.equal(p?.estado === "aguardando" ? p.posicao : 0, 1);
    assert.equal(m.aviso.enviados.length, 0, "sem vaga não há convite");
  });

  it("a ordem é FIFO pelo aprovado_em, e repetir o pedido não muda o lugar (adversarial c)", async () => {
    const m = montar(1);
    await entrarNaFila(m, [1, 2, 3, 4]);
    // O 4 insiste três vezes: continua atrás do 2 e do 3.
    for (let i = 0; i < 3; i += 1) assert.equal(await m.lista.reserve(id(4)), "lista_espera");
    const posicoes = await Promise.all([2, 3, 4].map(async (n) => {
      const p = await m.lista.posicao(id(n));
      return p?.estado === "aguardando" ? p.posicao : -1;
    }));
    assert.deepEqual(posicoes, [1, 2, 3]);
  });

  it("a vaga dada repete-se sem gastar outra: o mesmo caso pede duas vezes, ocupa uma", async () => {
    const m = montar(1);
    await entrarNaFila(m, [1]);
    assert.equal(await m.lista.reserve(id(1)), "granted");
    m.casos.fases.set(id(2), "aguarda_es");
    assert.equal(await m.lista.reserve(id(2)), "lista_espera");
  });

  it("a janela é deslizante: a vaga só volta quando a concluída faz 7 dias, e então convida-se a cabeça", async () => {
    const m = montar(1);
    await entrarNaFila(m, [1, 2]);
    m.relogio.agora = T0 + 7 * DIA - 1;
    assert.equal(await m.lista.promover(), 0, "ainda dentro da janela");
    m.relogio.agora = T0 + 7 * DIA + 1;
    assert.equal(await m.lista.promover(), 1);
    assert.equal(m.aviso.enviados.length, 1);
    assert.equal(m.aviso.enviados[0]?.onboardingId, id(2));
  });

  it("um convite vivo ocupa vaga: vaga = limite − concluídos − convites", async () => {
    const m = montar(2);
    await entrarNaFila(m, [1, 2, 3, 4]);
    m.relogio.agora = T0 + 8 * DIA;
    await m.lista.promover();
    // Duas vagas, dois convites (3 e 4): um quinto caso espera.
    m.casos.fases.set(id(5), "aguarda_es");
    assert.equal(await m.lista.reserve(id(5)), "lista_espera");
    assert.deepEqual(m.aviso.enviados.map((e) => e.onboardingId), [id(3), id(4)]);
  });

  it("a capacidade é configuração: subir o limite convida já, sem deploy", async () => {
    const m = montar(1);
    await entrarNaFila(m, [1, 2, 3]);
    m.repo.limite = { maximo: 3, origem: "confirmado", fundamento: "ensaio" };
    assert.equal(await m.lista.promover(), 2);
  });

  it("o limite a zero (linha em falta) fecha a fila: ninguém tem vaga", async () => {
    const m = montar(0);
    assert.deepEqual(await entrarNaFila(m, [1]), ["lista_espera"]);
  });
});

describe("unit: convites, expiração e desistência", () => {
  it("o convite guarda-se em hash; a ligação leva o convite em claro e o caso aceita-o uma vez", async () => {
    const m = montar(1);
    await entrarNaFila(m, [1, 2]);
    m.relogio.agora = T0 + 8 * DIA;
    await m.lista.promover();
    const c = conviteDe(m, 2);
    const linha = m.repo.linha(id(2));
    assert.equal(linha?.conviteHash, hashDoConvite(c));
    assert.notEqual(linha?.conviteHash, c);
    assert.equal(linha?.conviteExpiraEm?.getTime(), m.relogio.agora + VALIDADE_DO_CONVITE_H * HORA);
    // Conferir não gasta; a reserva gasta (é quando o popup abre).
    await m.lista.validarConvite(id(2), c);
    await m.lista.validarConvite(id(2), c);
    assert.equal(await m.lista.reserve(id(2)), "granted");
    assert.equal(m.metricas.convites("aceite"), 1);
    // Uso único: depois de dada a vaga, a ligação já não vale (adversarial b).
    await recusa(m.lista.validarConvite(id(2), c), "convite_invalido");
  });

  it("ADVERSARIAL b: o convite de outro caso, um forjado e um expirado dão o mesmo convite_invalido", async () => {
    const m = montar(1);
    await entrarNaFila(m, [1, 2, 3]);
    m.relogio.agora = T0 + 8 * DIA;
    await m.lista.promover();
    const c = conviteDe(m, 2);
    await recusa(m.lista.validarConvite(id(3), c), "convite_invalido");
    await recusa(m.lista.recusar(id(3), c), "convite_invalido");
    await recusa(m.lista.validarConvite(id(2), "forjado"), "convite_invalido");
    await recusa(m.lista.validarConvite(id(2), { c }), "convite_invalido");
    m.avancar(VALIDADE_DO_CONVITE_H * HORA);
    await recusa(m.lista.validarConvite(id(2), c), "convite_invalido");
  });

  it("convite expirado: passa a vaga ao seguinte e põe o caso no fim, uma vez; à segunda, abandonado", async () => {
    const m = montar(1);
    await entrarNaFila(m, [1, 2, 3]);
    m.relogio.agora = T0 + 8 * DIA;
    await m.lista.promover();
    m.avancar(VALIDADE_DO_CONVITE_H * HORA);
    assert.equal(await m.lista.expirarVencidos(), 1);
    assert.equal(m.repo.linha(id(2))?.estado, "aguardando");
    assert.equal(m.repo.linha(id(2))?.tentativas, 1);
    assert.equal(m.repo.linha(id(3))?.estado, "convidado", "a vaga passou ao seguinte");
    const p = await m.lista.posicao(id(2));
    assert.equal(p?.estado === "aguardando" ? p.posicao : -1, 1, "o 2 está no fim: atrás só do convidado");
    // O 3 também deixa expirar; o 2 é convidado de novo e deixa expirar outra vez.
    m.avancar(VALIDADE_DO_CONVITE_H * HORA);
    await m.lista.expirarVencidos();
    assert.equal(m.repo.linha(id(2))?.estado, "convidado");
    m.avancar(VALIDADE_DO_CONVITE_H * HORA);
    await m.lista.expirarVencidos();
    assert.equal(m.repo.linha(id(2))?.estado, "expirado");
    assert.equal(m.casos.fases.get(id(2)), "abandonado");
    await recusa(m.lista.reserve(id(2)), "fora_da_lista");
    assert.equal(m.metricas.convites("expirado"), 3);
  });

  it("recusar conta como uma expiração e convida o seguinte", async () => {
    const m = montar(1);
    await entrarNaFila(m, [1, 2, 3]);
    m.relogio.agora = T0 + 8 * DIA;
    await m.lista.promover();
    await m.lista.recusar(id(2), conviteDe(m, 2));
    assert.equal(m.repo.linha(id(2))?.tentativas, 1);
    assert.equal(m.repo.linha(id(3))?.estado, "convidado");
  });

  it("um convite vencido usado na reserva conta a expiração e não dá vaga", async () => {
    const m = montar(1);
    await entrarNaFila(m, [1, 2]);
    m.relogio.agora = T0 + 8 * DIA;
    await m.lista.promover();
    m.avancar(VALIDADE_DO_CONVITE_H * HORA + 1);
    // Sem mais ninguém, o 2 volta a ser a cabeça e há vaga: a reserva dá-a.
    assert.equal(await m.lista.reserve(id(2)), "granted");
    assert.equal(m.repo.linha(id(2))?.tentativas, 1);
  });

  it("a desistência liberta a posição já; a reentrada é um pedido novo, no fim, sem refazer o KYC", async () => {
    const m = montar(1);
    await entrarNaFila(m, [1, 2, 3, 4]);
    await m.lista.desistir(id(2));
    assert.equal(m.repo.linha(id(2))?.estado, "desistiu");
    const p3 = await m.lista.posicao(id(3));
    assert.equal(p3?.estado === "aguardando" ? p3.posicao : -1, 1);
    assert.equal(await m.lista.reserve(id(2)), "lista_espera");
    const p2 = await m.lista.posicao(id(2));
    assert.equal(p2?.estado === "aguardando" ? p2.posicao : -1, 3, "volta para o fim");
  });

  it("a desistência de um convidado liberta o convite para o seguinte", async () => {
    const m = montar(1);
    await entrarNaFila(m, [1, 2, 3]);
    m.relogio.agora = T0 + 8 * DIA;
    await m.lista.promover();
    await m.lista.desistir(id(2));
    assert.equal(m.repo.linha(id(3))?.estado, "convidado");
    assert.equal(m.repo.linha(id(2))?.conviteHash, null);
  });

  it("reentrar depois da validade do KYC é recusado com kyc_caducado", async () => {
    const m = montar(1);
    await entrarNaFila(m, [1, 2]);
    await m.lista.desistir(id(2));
    m.avancar(91 * DIA);
    await recusa(m.lista.reserve(id(2)), "kyc_caducado");
  });

  it("o popup fechado NÃO devolve a vaga: ninguém é convidado, e a retoma volta a tê-la sem gastar outra", async () => {
    const m = montar(1);
    await entrarNaFila(m, [1, 2]);
    for (let i = 0; i < 3; i += 1) {
      await m.lista.release(id(1));
      assert.equal(await m.lista.reserve(id(1)), "granted");
    }
    assert.equal(m.repo.linha(id(1))?.estado, "concluido");
    assert.equal(m.aviso.enviados.length, 0, "fechar o popup não manda SMS a ninguém");
    assert.equal(await m.lista.reserve(id(2)), "lista_espera", "a vaga continua contada");
  });

  it("um aviso que falha desfaz o convite, não gasta tentativa e põe o caso no fim: a fila não pára", async () => {
    const m = montar(1);
    await entrarNaFila(m, [1, 2, 3]);
    m.relogio.agora = T0 + 8 * DIA;
    m.aviso.falhar = true;
    assert.equal(await m.lista.promover(), 0);
    assert.equal(m.repo.linha(id(2))?.estado, "aguardando");
    assert.equal(m.repo.linha(id(2))?.tentativas, 0);
    assert.equal(await m.lista.promover(), 1);
    assert.equal(m.aviso.enviados[0]?.onboardingId, id(3), "o seguinte é convidado, e não a cabeça avariada outra vez");
  });

  it("um convite vencido usado na reserva, à segunda expiração, recusa — e a expiração fica escrita", async () => {
    const m = montar(1);
    await entrarNaFila(m, [1, 2]);
    m.relogio.agora = T0 + 8 * DIA;
    await m.lista.promover();
    m.avancar(VALIDADE_DO_CONVITE_H * HORA + 1);
    await m.lista.expirarVencidos();
    assert.equal(m.repo.linha(id(2))?.estado, "convidado", "sozinho na fila, é convidado outra vez");
    m.avancar(VALIDADE_DO_CONVITE_H * HORA + 1);
    await recusa(m.lista.reserve(id(2)), "fora_da_lista");
    assert.equal(m.repo.linha(id(2))?.estado, "expirado", "a recusa não desfez a expiração");
    assert.equal(m.casos.fases.get(id(2)), "abandonado");
  });

  it("um caso que saiu das fases da fila enquanto esperava não é convidado: sai da fila", async () => {
    const m = montar(1);
    await entrarNaFila(m, [1, 2, 3]);
    m.casos.fases.set(id(2), "kyc_pendente");
    m.relogio.agora = T0 + 8 * DIA;
    assert.equal(await m.lista.promover(), 1);
    assert.equal(m.repo.linha(id(2))?.estado, "desistiu");
    assert.equal(m.aviso.enviados[0]?.onboardingId, id(3));
  });

  it("desistir com um convite na mão gasta-o como uma recusa", async () => {
    const m = montar(1);
    await entrarNaFila(m, [1, 2]);
    m.relogio.agora = T0 + 8 * DIA;
    await m.lista.promover();
    await m.lista.desistir(id(2));
    assert.equal(m.repo.linha(id(2))?.tentativas, 1);
  });
});

describe("adversarial", () => {
  it("(a) 1.000 registos de bot sem KYC ⇒ 0 entradas", async () => {
    const m = montar(10);
    const fases: Fase[] = ["registo", "otp_pendente", "kyc_pendente", "em_revisao"];
    for (let n = 0; n < 1000; n += 1) {
      m.casos.fases.set(id(n), fases[n % fases.length] as Fase);
      await recusa(m.lista.reserve(id(n)), "nao_elegivel");
    }
    await recusa(m.lista.reserve(id(5000)), "nao_elegivel");
    assert.equal(m.repo.tamanho, 0);
  });

  it("(d) a promoção repetida (redelivery) manda um aviso só", async () => {
    const m = montar(1);
    await entrarNaFila(m, [1, 2]);
    m.relogio.agora = T0 + 8 * DIA;
    await Promise.all([m.lista.promover(), m.lista.promover(), m.lista.promover()]);
    assert.equal(m.aviso.enviados.length, 1);
  });
});

describe("concorrência", () => {
  it("20 trabalhadores a pedir 1 vaga ⇒ 1 convite", async () => {
    const m = montar(1);
    await entrarNaFila(m, Array.from({ length: 21 }, (_, i) => i + 1));
    m.relogio.agora = T0 + 8 * DIA;
    const r = await Promise.all(Array.from({ length: 20 }, () => m.lista.promover()));
    assert.equal(r.reduce((a, b) => a + b, 0), 1);
    assert.equal(m.aviso.enviados.length, 1);
    assert.equal(m.aviso.enviados[0]?.onboardingId, id(2), "à cabeça");
  });

  it("dois pedidos para a última vaga ⇒ um concedido; o outro mantém a posição", async () => {
    const m = montar(3);
    await entrarNaFila(m, [1, 2]);
    m.casos.fases.set(id(3), "aguarda_es");
    m.casos.fases.set(id(4), "aguarda_es");
    const r = await Promise.all([m.lista.reserve(id(3)), m.lista.reserve(id(4))]);
    assert.deepEqual([...r].sort(), ["granted", "lista_espera"]);
    const perdedor = r[0] === "granted" ? 4 : 3;
    const p = await m.lista.posicao(id(perdedor));
    assert.equal(p?.estado === "aguardando" ? p.posicao : -1, 1);
  });
});

describe("estimativa", () => {
  it("é um intervalo rotulado, a partir da nossa janela, e não uma promessa", () => {
    const agora = new Date(T0);
    // Duas vagas, ocupadas há 1 e 3 dias: a primeira solta-se daqui a 4 dias.
    const e = estimar(1, 2, [new Date(T0 - 3 * DIA), new Date(T0 - 1 * DIA)], agora);
    assert.equal(e.rotulo, "estimativa");
    assert.equal(e.minimoDias, 4);
    assert.ok(e.maximoDias > e.minimoDias);
    // A terceira posição precisa de uma volta inteira da janela.
    assert.equal(estimar(3, 2, [new Date(T0 - 3 * DIA), new Date(T0 - 1 * DIA)], agora).minimoDias, 11);
  });

  it("com vaga livre o mínimo é zero, e com limite zero não há estimativa", () => {
    assert.equal(estimar(1, 2, [], new Date(T0)).minimoDias, 0);
    assert.equal(estimar(1, 0, [], new Date(T0)).minimoDias, Number.POSITIVE_INFINITY);
  });

  it("a posição do dono traz a estimativa", async () => {
    const m = montar(1);
    await entrarNaFila(m, [1, 2]);
    const p = await m.lista.posicao(id(2));
    assert.equal(p?.estado, "aguardando");
    assert.equal(p?.estado === "aguardando" ? p.estimativa.rotulo : "", "estimativa");
    assert.equal(await m.lista.posicao(id(99)), null, "quem nunca entrou não tem posição");
  });
});

describe("métricas", () => {
  it("as etiquetas são domínios fechados e o limite desconhecido sai NaN", async () => {
    const m = montar(1);
    const antes = m.metricas.exposicao();
    assert.match(antes, /^es_limite_7d\{origem="confirmado"\} NaN$/m);
    await entrarNaFila(m, [1, 2, 3]);
    await m.lista.medir();
    const depois = m.metricas.exposicao();
    assert.match(depois, /^es_lista_espera_entradas\{estado="aguardando"\} 2$/m);
    assert.match(depois, /^es_vagas_concedidas_7d 1$/m);
    assert.match(depois, /^es_limite_7d\{origem="confirmado"\} 1$/m);
    assert.match(depois, /^es_limite_7d\{origem="nao_verificado"\} NaN$/m);
    for (const e of ESTADOS_DA_ENTRADA) assert.match(depois, new RegExp(`estado="${e}"`));
    assert.doesNotMatch(depois, /0000-4000/, "nenhum caso nas etiquetas");
  });
});
