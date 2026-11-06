/**
 * O disparo do lembrete: os portões e o envio (KAM-048, critérios 2–6).
 *
 * ## O que isto prova e o que não prova
 *
 * **Não prova nenhuma das barreiras da base.** A unicidade de
 * `(tenant_id, idempotency_key)` é da revisão `0010`, o isolamento é da RLS, e a
 * decisão de janela e o portão do *template* são código do KAM-015 medido na
 * *suite* dele. O que se prova aqui é a **tradução e a ordem**: que a chave que
 * as cinco entregas levam é a mesma, que ela tem a forma que o critério 2
 * escreve, que o corpo muda com a janela e não com mais nada, que cada portão
 * recusa com o seu motivo e pela ordem certa, e que uma recusa de *template*
 * avisa o dono.
 *
 * O duplo de saída **modela a idempotência da base** — um `Set` de
 * `(tenant, chave)`, com a segunda passagem a devolver `repetido: true` sem
 * registar envio. É esse duplo que torna «cinco entregas, uma mensagem» uma
 * asserção sobre **a chave**, que é a parte que este módulo possui; a parte que
 * a base possui está em `db/tests/test_saida_schema.py`.
 *
 * O cliente de ensaio **registra as consultas por ordem**, o que torna «a ordem
 * dos portões» uma asserção e não uma leitura do código — a mesma escolha que o
 * `servicos.modulo.test.ts` do KAM-047 fez.
 */

import assert from "node:assert/strict";
import { test } from "node:test";

import {
  SQL_ESTADO as SQL_ESTADO_DO_CONSENTIMENTO,
  SQL_TEXTO_VIGENTE,
} from "@kamba/core-ts/consentimento";

import { SQL_MARCACAO, SQL_SERVICO } from "../src/servicos/consultas.ts";
import {
  IDIOMA_DO_LEMBRETE,
  PARAMETROS_DO_LEMBRETE,
  SQL_DESTINO,
  TEMPLATE_DO_LEMBRETE,
  chaveDoLembrete,
  entregarLembrete,
  MetricasDoLembrete,
  METRICA_ENVIADOS,
  METRICA_TRAVADOS,
  type AvisoDeTemplateBloqueado,
  type PortaDeSaida,
} from "../src/servicos/reminders/index.ts";

const TENANT = "11111111-1111-4111-8111-111111111111";
const CONTACTO = "22222222-2222-4222-8222-222222222222";
const SERVICO = "33333333-3333-4333-8333-333333333333";
const RECURSO = "44444444-4444-4444-8444-444444444444";
const BOOKING = "55555555-5555-4555-8555-555555555555";
const CONVERSA = "77777777-7777-4777-8777-777777777777";
const CANAL = "88888888-8888-4888-8888-888888888888";

/** Um identificador opaco da Meta. **Não é um telefone** — ver o `meta-sim`. */
const PNID = "pnid-de-ensaio";

const INICIO = "2026-11-10T09:00:00.000Z";
/** O instante do disparo: 24 h antes do início. */
const AGORA = new Date("2026-11-09T09:00:00.000Z");

const EVENTO = { booking_id: BOOKING, inicio_at: INICIO };

/** Uma linha de `bookings` como a base a devolve. */
function linhaDaMarcacao(sobrepor: Record<string, unknown> = {}) {
  return {
    booking_id: BOOKING,
    hold_id: "66666666-6666-4666-8666-666666666666",
    contact_id: CONTACTO,
    service_id: SERVICO,
    resource_id: RECURSO,
    slot_id: "slot-de-ensaio",
    inicio_at: INICIO,
    fim_at: "2026-11-10T09:30:00.000Z",
    estado: "confirmada",
    hold_expires_at: null,
    version: 1,
    ...sobrepor,
  };
}

interface Opcoes {
  /** A linha de `bookings`, ou `null` para «não existe». */
  readonly marcacao?: Record<string, unknown> | null;
  /** `null` fecha a janela; um `Date` abre-a até ele. */
  readonly janelaExpiraEm?: string | null;
  /** `null` para «o contacto não tem conversa». */
  readonly destino?: boolean;
  /** `null` para «a `consent_texts` está vazia». */
  readonly versaoVigente?: string | null;
  /** A linha de `consent_actual`, ou `null` para «nunca consentiu». */
  readonly consentimento?: { accepted: boolean; text_version: string } | null;
  /** O que o Outbound responde: `null` aceita, uma cadeia recusa com ela. */
  readonly recusa?: string | null;
}

interface Ensaio {
  readonly sqls: string[];
  readonly enviadas: Array<Record<string, unknown>>;
  readonly avisos: AvisoDeTemplateBloqueado[];
  readonly metricas: MetricasDoLembrete;
  readonly deps: Parameters<typeof entregarLembrete>[0];
}

/**
 * Monta o disparo com um cliente que responde por consulta.
 *
 * A saída é um duplo que **modela a `UNIQUE` da revisão `0010`**: guarda as
 * chaves que já passaram e devolve `repetido: true` para a segunda, sem registar
 * envio. É o que faz a asserção de «uma mensagem» ser sobre a chave.
 */
function ensaio(opcoes: Opcoes = {}): Ensaio {
  const sqls: string[] = [];
  const enviadas: Array<Record<string, unknown>> = [];
  const avisos: AvisoDeTemplateBloqueado[] = [];
  const metricas = new MetricasDoLembrete();
  const chavesUsadas = new Set<string>();

  const marcacao =
    opcoes.marcacao === undefined ? linhaDaMarcacao() : opcoes.marcacao;
  const versaoVigente =
    opcoes.versaoVigente === undefined ? "v1" : opcoes.versaoVigente;
  const consentimento =
    opcoes.consentimento === undefined
      ? { accepted: true, text_version: "v1" }
      : opcoes.consentimento;
  const temDestino = opcoes.destino ?? true;

  const cliente = {
    async query(sql: string) {
      sqls.push(sql);
      if (sql === SQL_MARCACAO) {
        return { rows: marcacao === null ? [] : [marcacao] };
      }
      if (sql === SQL_TEXTO_VIGENTE) {
        return {
          rows:
            versaoVigente === null
              ? []
              : [{ version: versaoVigente, texto: "aviso de ensaio" }],
        };
      }
      if (sql === SQL_ESTADO_DO_CONSENTIMENTO) {
        return { rows: consentimento === null ? [] : [consentimento] };
      }
      if (sql === SQL_DESTINO) {
        if (!temDestino) return { rows: [] };
        return {
          rows: [
            {
              conversation_id: CONVERSA,
              channel_id: CANAL,
              phone_number_id: PNID,
              window_expires_at:
                opcoes.janelaExpiraEm === undefined ? null : opcoes.janelaExpiraEm,
            },
          ],
        };
      }
      if (sql === SQL_SERVICO) {
        return { rows: [{ nome: "Corte de cabelo" }] };
      }
      throw new Error(`consulta inesperada no ensaio: ${sql.slice(0, 60)}`);
    },
  };

  const saida: PortaDeSaida = {
    async enviar(pedido) {
      const chave = `${pedido.tenantId}|${pedido.idempotencyKey}`;
      if (opcoes.recusa !== undefined && opcoes.recusa !== null) {
        // **A recusa nao gasta a chave**, e e a ordem do `adapter.ts` do
        // KAM-015: a decisao corre antes da linha em `outbound_messages`. Um
        // duplo que marcasse a chave aqui escondia a propriedade que faz um
        // lembrete recusado por template poder sair no dia da aprovacao.
        return { ok: false, motivo: opcoes.recusa, codigo: null };
      }
      if (chavesUsadas.has(chave)) {
        return { ok: true, id: "ja-existia", wamid: null, kind: "service", repetido: true };
      }
      chavesUsadas.add(chave);
      enviadas.push({ ...pedido });
      return {
        ok: true,
        id: `linha-${enviadas.length}`,
        wamid: `wamid-${enviadas.length}`,
        kind: pedido.corpo.tipo === "template" ? "utility" : "service",
        repetido: false,
      };
    },
  };

  return {
    sqls,
    enviadas,
    avisos,
    metricas,
    deps: {
      comTenant: async (tenantId, trabalho) => {
        assert.equal(tenantId, TENANT, "a transaccao abriu com outro tenant");
        return trabalho(cliente);
      },
      saida,
      avisarDono: async (aviso) => {
        avisos.push(aviso);
      },
      metricas,
      agora: () => AGORA,
    },
  };
}

// --------------------------------------------------------------- critério 2

test("a chave e a do criterio 2, literalmente", () => {
  assert.equal(chaveDoLembrete(BOOKING), `${BOOKING}:reminder:T-24h`);
  // **Sem relogio e sem o evento**: duas chamadas separadas no tempo dao a
  // mesma cadeia. Uma chave com o `event_id` dentro dava cinco chaves para as
  // cinco entregas que o EVT faz por desenho.
  assert.equal(chaveDoLembrete(BOOKING), chaveDoLembrete(BOOKING));
});

test("o mesmo evento entregue 5 vezes produz 1 mensagem", async () => {
  const e = ensaio({ janelaExpiraEm: "2026-11-09T18:00:00.000Z" });
  const desfechos = [];
  for (let i = 0; i < 5; i += 1) {
    desfechos.push(await entregarLembrete(e.deps, TENANT, EVENTO));
  }

  // **Cinco e nao duas**: o criterio escreve cinco, e duas entregas nao
  // distinguem «deduplica» de «deduplica a primeira repeticao e esquece».
  assert.equal(e.enviadas.length, 1, `sairam ${e.enviadas.length} mensagens`);
  assert.equal(desfechos.length, 5);
  for (const desfecho of desfechos) {
    assert.equal(desfecho.enviado, true);
  }
  const repetidos = desfechos.filter((d) => d.enviado && d.repetido).length;
  assert.equal(repetidos, 4);
  // E as cinco pediram **a mesma chave**, que e a propriedade deste modulo.
  assert.equal(e.enviadas[0]?.["idempotencyKey"], `${BOOKING}:reminder:T-24h`);
  assert.equal(e.metricas.ler(METRICA_ENVIADOS, "service"), 5);
});

// --------------------------------------------------------------- critério 3

test("com a janela aberta vai mensagem livre, e nunca template", async () => {
  const e = ensaio({ janelaExpiraEm: "2026-11-09T18:00:00.000Z" });
  const desfecho = await entregarLembrete(e.deps, TENANT, EVENTO);

  assert.equal(desfecho.enviado, true);
  assert.equal(desfecho.enviado === true ? desfecho.canal : null, "service");
  const corpo = e.enviadas[0]?.["corpo"] as { tipo: string; texto: string };
  assert.equal(corpo.tipo, "texto");
  assert.doesNotMatch(corpo.texto, /\{\{\d+\}\}/);
  // A data e a hora vem de **factos**: o nome do servico e a hora de Luanda.
  assert.ok(corpo.texto.includes("Corte de cabelo"));
  assert.ok(corpo.texto.includes("10:00"), `o texto foi: ${corpo.texto}`);
});

test("com a janela fechada vai o template utility em pt_PT", async () => {
  const e = ensaio({ janelaExpiraEm: null });
  const desfecho = await entregarLembrete(e.deps, TENANT, EVENTO);

  assert.equal(desfecho.enviado, true);
  assert.equal(desfecho.enviado === true ? desfecho.canal : null, "utility");
  const corpo = e.enviadas[0]?.["corpo"] as {
    tipo: string;
    nome: string;
    idioma: string;
    parametros: readonly string[];
  };
  assert.equal(corpo.tipo, "template");
  assert.equal(corpo.nome, TEMPLATE_DO_LEMBRETE);
  assert.equal(corpo.idioma, IDIOMA_DO_LEMBRETE);
  assert.equal(corpo.idioma, "pt_PT");
  assert.equal(corpo.parametros.length, PARAMETROS_DO_LEMBRETE);
  assert.equal(e.metricas.ler(METRICA_ENVIADOS, "utility"), 1);
});

test("uma janela que expira exactamente agora esta fechada", async () => {
  // O limite e **estrito**, e e o `janelaAberta` do KAM-015 a decidi-lo. A
  // leitura conservadora e a certa: a alternativa era texto livre no instante em
  // que a Meta o passa a recusar, e descobri-lo por um `131047`.
  const e = ensaio({ janelaExpiraEm: AGORA.toISOString() });
  await entregarLembrete(e.deps, TENANT, EVENTO);
  const corpo = e.enviadas[0]?.["corpo"] as { tipo: string };
  assert.equal(corpo.tipo, "template");
});

// --------------------------------------------------------------- critério 4

test("uma marcacao cancelada antes do disparo nao gera lembrete", async () => {
  for (const estado of ["cancelada", "expirada", "hold"]) {
    const e = ensaio({ marcacao: linhaDaMarcacao({ estado }) });
    const desfecho = await entregarLembrete(e.deps, TENANT, EVENTO);

    assert.equal(desfecho.enviado, false, `o estado ${estado} enviou`);
    assert.equal(
      desfecho.enviado === false ? desfecho.motivo : null,
      "MARCACAO_NAO_CONFIRMADA",
    );
    assert.equal(e.enviadas.length, 0);
    assert.equal(e.metricas.ler(METRICA_TRAVADOS, "MARCACAO_NAO_CONFIRMADA"), 1);
    // **O portao corre antes do consentimento**: o `SQL_ESTADO` nem e tocado.
    assert.ok(!e.sqls.includes(SQL_TEXTO_VIGENTE));
  }
});

test("uma marcacao remarcada antes do disparo nao gera lembrete", async () => {
  // O *job* antigo dispara com o `inicio_at` do agendamento; a base ja tem
  // outro. **E esta comparacao que o mata**, e nao a fila — ver o
  // `servicos.reminders.schedule.test.ts` para a outra metade.
  const e = ensaio({
    marcacao: linhaDaMarcacao({ inicio_at: "2026-11-12T15:00:00.000Z" }),
  });
  const desfecho = await entregarLembrete(e.deps, TENANT, EVENTO);

  assert.equal(desfecho.enviado, false);
  assert.equal(desfecho.enviado === false ? desfecho.motivo : null, "MARCACAO_REMARCADA");
  assert.equal(e.enviadas.length, 0);
});

test("o job da remarcacao dispara, e e o antigo que nao envia", async () => {
  // O par completo do criterio 4: a base diz `2026-11-12T15:00Z`, o *job* novo
  // traz esse instante e **envia**; o antigo traz o de `INICIO` e **nao envia**.
  const novoInicio = "2026-11-12T15:00:00.000Z";
  const e = ensaio({
    marcacao: linhaDaMarcacao({ inicio_at: novoInicio }),
    janelaExpiraEm: "2026-11-09T18:00:00.000Z",
  });

  const antigo = await entregarLembrete(e.deps, TENANT, EVENTO);
  const novo = await entregarLembrete(e.deps, TENANT, {
    booking_id: BOOKING,
    inicio_at: novoInicio,
  });

  assert.equal(antigo.enviado, false);
  assert.equal(novo.enviado, true);
  assert.equal(e.enviadas.length, 1, "1 lembrete activo por marcacao");
});

test("um timestamptz como Date compara igual ao ISO do payload", async () => {
  // O `pg` devolve `Date` para `timestamptz`; o duplo devolve texto. Sem a
  // normalizacao, **nenhum** lembrete saia contra uma base real e o motivo
  // `MARCACAO_REMARCADA` mentia sobre a causa — a classe de defeito que passa
  // todos os ensaios com duplos.
  const e = ensaio({
    marcacao: linhaDaMarcacao({ inicio_at: new Date(INICIO) }),
    janelaExpiraEm: "2026-11-09T18:00:00.000Z",
  });
  const desfecho = await entregarLembrete(e.deps, TENANT, EVENTO);
  assert.equal(desfecho.enviado, true);
});

test("uma marcacao que nao existe nao envia nada", async () => {
  const e = ensaio({ marcacao: null });
  const desfecho = await entregarLembrete(e.deps, TENANT, EVENTO);
  assert.equal(desfecho.enviado, false);
  assert.equal(
    desfecho.enviado === false ? desfecho.motivo : null,
    "MARCACAO_INEXISTENTE",
  );
  assert.deepEqual(e.sqls, [SQL_MARCACAO]);
});

// --------------------------------------------------------------- critério 5

test("um template nao aprovado bloqueia, avisa o dono e registra o motivo", async () => {
  for (const motivo of ["TEMPLATE_NOT_APPROVED", "TEMPLATE_BLOCKED", "MARKETING_NOT_ALLOWED"]) {
    const e = ensaio({ janelaExpiraEm: null, recusa: motivo });
    const desfecho = await entregarLembrete(e.deps, TENANT, EVENTO);

    assert.equal(desfecho.enviado, false);
    assert.equal(desfecho.enviado === false ? desfecho.motivo : null, motivo);
    assert.equal(desfecho.enviado === false ? desfecho.donoAvisado : null, true);
    assert.equal(e.avisos.length, 1);
    assert.equal(e.avisos[0]?.motivo, motivo);
    assert.equal(e.avisos[0]?.template, TEMPLATE_DO_LEMBRETE);
    assert.equal(e.avisos[0]?.bookingId, BOOKING);
    assert.equal(e.metricas.ler(METRICA_TRAVADOS, motivo), 1);
  }
});

test("sem porta de aviso o lembrete continua travado, e diz que nao avisou", async () => {
  // A escolha do `freeTier: null` do KAM-015 e **nao** a do `PreSendGuard`: um
  // aviso que falte nao deixa passar nada. O que muda e o `donoAvisado`.
  const e = ensaio({ janelaExpiraEm: null, recusa: "TEMPLATE_NOT_APPROVED" });
  const desfecho = await entregarLembrete(
    { ...e.deps, avisarDono: null },
    TENANT,
    EVENTO,
  );
  assert.equal(desfecho.enviado, false);
  assert.equal(desfecho.enviado === false ? desfecho.donoAvisado : null, false);
  assert.equal(e.avisos.length, 0);
  assert.equal(e.metricas.ler(METRICA_TRAVADOS, "TEMPLATE_NOT_APPROVED"), 1);
});

test("uma recusa que nao e de template nao avisa o dono", async () => {
  // O `STATE_REFUSED` e o canal restrito pela matriz do KAM-009, e o dono ja e
  // avisado disso pelo KAM-115. Avisa-lo outra vez por este caminho era dois
  // avisos para o mesmo facto.
  const e = ensaio({ janelaExpiraEm: null, recusa: "STATE_REFUSED" });
  const desfecho = await entregarLembrete(e.deps, TENANT, EVENTO);
  assert.equal(desfecho.enviado, false);
  assert.equal(desfecho.enviado === false ? desfecho.donoAvisado : null, false);
  assert.equal(e.avisos.length, 0);
});

// --------------------------------------------------------------- critério 6

test("sem opt-in valido o lembrete nao e enviado e o motivo e auditado", async () => {
  type Linha = { accepted: boolean; text_version: string } | null;
  const casos: Array<[Linha, string]> = [
    [null, "nunca consentiu"],
    [{ accepted: false, text_version: "v1" }, "revogou"],
    [{ accepted: true, text_version: "v0" }, "consentiu uma versao anterior"],
  ];
  for (const [consentimento, porque] of casos) {
    const e = ensaio({ consentimento, janelaExpiraEm: "2026-11-09T18:00:00.000Z" });
    const desfecho = await entregarLembrete(e.deps, TENANT, EVENTO);

    assert.equal(desfecho.enviado, false, `enviou a quem ${porque}`);
    assert.equal(desfecho.enviado === false ? desfecho.motivo : null, "SEM_OPT_IN");
    assert.equal(e.enviadas.length, 0);
    assert.equal(e.metricas.ler(METRICA_TRAVADOS, "SEM_OPT_IN"), 1);
    // **O portao corre antes do destino e do corpo**: nada mais foi lido.
    assert.ok(!e.sqls.includes(SQL_DESTINO));
    assert.ok(!e.sqls.includes(SQL_SERVICO));
  }
});

test("sem texto vigente na consent_texts falha fechada", async () => {
  // A `consent_texts` nasce **vazia** (revisao `0015`, KAM-104). E este o
  // motivo que sai hoje em qualquer base recem-migrada, e e o estado correcto:
  // sem aviso mostrado nao ha consentimento registado.
  const e = ensaio({ versaoVigente: null });
  const desfecho = await entregarLembrete(e.deps, TENANT, EVENTO);
  assert.equal(desfecho.enviado, false);
  assert.equal(desfecho.enviado === false ? desfecho.motivo : null, "SEM_TEXTO_VIGENTE");
  assert.equal(e.enviadas.length, 0);
  // E nao se chegou a perguntar pelo estado do contacto.
  assert.ok(!e.sqls.includes(SQL_ESTADO_DO_CONSENTIMENTO));
});

// --------------------------------------------------------------- o destino

test("um contacto sem conversa nao tem canal, logo nao ha lembrete", async () => {
  const e = ensaio({ destino: false });
  const desfecho = await entregarLembrete(e.deps, TENANT, EVENTO);
  assert.equal(desfecho.enviado, false);
  assert.equal(desfecho.enviado === false ? desfecho.motivo : null, "SEM_CONVERSA");
  assert.equal(e.enviadas.length, 0);
});

test("a ordem dos portoes e a do desenho", async () => {
  // A ordem e uma assercao e nao uma leitura do codigo. Marcacao, texto do
  // consentimento, estado do consentimento, destino, servico: cada posicao tem
  // a razao escrita na nota do `deliver.ts`.
  const e = ensaio({ janelaExpiraEm: "2026-11-09T18:00:00.000Z" });
  await entregarLembrete(e.deps, TENANT, EVENTO);
  assert.deepEqual(e.sqls, [
    SQL_MARCACAO,
    SQL_TEXTO_VIGENTE,
    SQL_ESTADO_DO_CONSENTIMENTO,
    SQL_DESTINO,
    SQL_SERVICO,
  ]);
});

test("o envio e do bot, logo passa pelo guarda do KAM-018", async () => {
  // `doBot: true` e deliberado: um lembrete e o assistente a falar por
  // iniciativa propria, que e o caso que o `PreSendGuard` existe para travar
  // quando uma pessoa esta a atender a conversa.
  const e = ensaio({ janelaExpiraEm: "2026-11-09T18:00:00.000Z" });
  await entregarLembrete(e.deps, TENANT, EVENTO);
  assert.equal(e.enviadas[0]?.["doBot"], true);
});

test("o pedido nao leva telefone nenhum", async () => {
  // DoD «Privacidade»: o destinatario entra por `contact_id`, e a resolucao
  // dele para um numero e do Outbound. Nada aqui tem forma de telefone.
  const e = ensaio({ janelaExpiraEm: "2026-11-09T18:00:00.000Z" });
  await entregarLembrete(e.deps, TENANT, EVENTO);
  const pedido = JSON.stringify(e.enviadas[0]);
  assert.doesNotMatch(pedido, /\+244/);
  assert.doesNotMatch(pedido, /\b9\d{8}\b/);
  assert.equal(e.enviadas[0]?.["contactId"], CONTACTO);
});
