/**
 * O aviso ao dono sobre a decisão da fila (KAM-196, critério 5).
 *
 * Os telefones destes ensaios são **nacionais a começar por zero**, que um
 * telemóvel angolano nunca é, e vão escritos com espaços: o número de ninguém.
 */

import assert from "node:assert/strict";
import { randomBytes, randomUUID } from "node:crypto";
import { describe, it } from "node:test";

import {
  AVISOS,
  AvisoAoDonoPorVia,
  AvisoSemDestinoError,
  CAUSA_DO_MOTIVO_PUBLICO,
  MOTIVOS_PUBLICOS,
  TEXTO_DO_MOTIVO_PUBLICO,
  mensagemDoAviso,
  type Aviso,
  type MotivoPublico,
} from "../src/revisao/index.ts";
import {
  CodigoOtp,
  FakeSmsProvider,
  MODELOS,
  NOMES_DE_MODELO,
  ParametroInvalidoError,
  comprimentoNoPiorCaso,
  construir,
  cunharDestino,
} from "../src/sms/index.ts";

import { SEXTA, montarRevisao, revisor } from "./apoio/revisao.ts";

/** O telefone registado do dono, e o da loja. Nacionais a começar por zero. */
const REGISTADO = "+244 000 000 101";
const DA_LOJA = "+244 000 000 202";

/** Todas as combinações que o serviço pode mandar. */
function combinacoes(): { aviso: Aviso; motivo: MotivoPublico | null }[] {
  const todas: { aviso: Aviso; motivo: MotivoPublico | null }[] = [{ aviso: "aprovado", motivo: null }];
  for (const motivo of MOTIVOS_PUBLICOS) {
    todas.push({ aviso: "rejeitado", motivo }, { aviso: "pedir_info", motivo }, { aviso: "recurso_decidido", motivo });
  }
  todas.push({ aviso: "recurso_decidido", motivo: null });
  return todas;
}

describe("avisos: os modelos de SMS (criterio 5)", () => {
  it("os cinco modelos da fila sao avisos de servico, ASCII, e cabem num segmento no pior caso", () => {
    const daFila = NOMES_DE_MODELO.filter((n) => n.startsWith("revisao_"));
    assert.equal(daFila.length, 5);
    for (const nome of daFila) {
      assert.equal(MODELOS[nome].finalidade, "aviso_de_servico");
      assert.ok(/^[\x20-\x7e]*$/.test(MODELOS[nome].corpo), nome);
      assert.ok(comprimentoNoPiorCaso(nome) <= 160, `${nome}: ${comprimentoNoPiorCaso(nome)}`);
    }
  });

  it("cada combinacao rende um SMS ASCII de um segmento, com o texto fixo do motivo", () => {
    for (const { aviso, motivo } of combinacoes()) {
      const m = mensagemDoAviso(aviso, motivo);
      const corpo = construir(m.sms.modelo, m.sms.parametros);
      assert.ok(/^KAMBA: [\x20-\x7e]*$/.test(corpo), `${aviso}/${motivo}`);
      assert.ok(corpo.length <= 160, `${aviso}/${motivo}: ${corpo.length}`);
      if (motivo === null) continue;
      if (aviso === "recurso_decidido") {
        assert.ok(corpo.includes(CAUSA_DO_MOTIVO_PUBLICO[motivo]), `${aviso}/${motivo}`);
        assert.ok(!/recorrer/i.test(corpo), "depois do recurso, o SMS nao oferece outro");
      } else {
        assert.ok(corpo.includes(TEXTO_DO_MOTIVO_PUBLICO[motivo]), `${aviso}/${motivo}`);
      }
    }
  });

  it("cada causa e o comeco exacto do seu texto", () => {
    for (const m of MOTIVOS_PUBLICOS) {
      assert.ok(TEXTO_DO_MOTIVO_PUBLICO[m].startsWith(CAUSA_DO_MOTIVO_PUBLICO[m]), m);
      assert.ok(CAUSA_DO_MOTIVO_PUBLICO[m].endsWith("."), m);
    }
  });

  it("o recurso aceite nao diz que o pedido foi aprovado: pode haver outro caso pendente", () => {
    const m = mensagemDoAviso("recurso_decidido", null);
    const corpo = construir(m.sms.modelo, m.sms.parametros);
    assert.match(corpo, /recurso foi aceite/);
    assert.doesNotMatch(corpo, /aprovad/);
    assert.doesNotMatch(m.email.corpo, /aprovad/);
  });

  it("um modelo da fila recusa texto livre e parametros que nao declara", () => {
    assert.throws(() => construir("revisao_rejeitado", { motivo: "o seu NIF e falso" as MotivoPublico }), ParametroInvalidoError);
    assert.throws(() => construir("revisao_rejeitado", {}), ParametroInvalidoError);
    const naoDeclarado = (f: () => unknown, nome: string) =>
      assert.throws(f, (e: unknown) => e instanceof ParametroInvalidoError && e.parametro === nome);
    naoDeclarado(() => construir("revisao_aprovado", { motivo: "documento_expirado" }), "motivo");
    naoDeclarado(() => construir("revisao_rejeitado", { motivo: "documento_expirado", causa: "documento_expirado" }), "causa");
    // E o OTP continua fechado: um motivo a mais no envio do codigo levanta.
    naoDeclarado(
      () => construir("otp_posse_telefone", { codigo: new CodigoOtp("123456"), validade_min: 5, motivo: "documento_expirado" }),
      "motivo",
    );
  });

  it("rejeitado e pedir_info sem motivo, ou fora das listas, recusam em vez de inventar", () => {
    assert.throws(() => mensagemDoAviso("rejeitado", null), RangeError);
    assert.throws(() => mensagemDoAviso("pedir_info", null), RangeError);
    assert.throws(() => mensagemDoAviso("parabens" as Aviso, null), RangeError);
    assert.throws(() => mensagemDoAviso("rejeitado", "outro" as MotivoPublico), RangeError);
  });

  it("os e-mails cobrem os quatro avisos e levam o texto fixo, sem nada do caso", () => {
    const vistos = new Set<Aviso>();
    for (const { aviso, motivo } of combinacoes()) {
      const { email } = mensagemDoAviso(aviso, motivo);
      vistos.add(aviso);
      assert.ok(email.assunto.startsWith("KAMBÁ: "), aviso);
      assert.ok(email.corpo.length > 0 && email.corpo.length < 1000);
      if (motivo !== null && aviso !== "recurso_decidido") assert.ok(email.corpo.includes(TEXTO_DO_MOTIVO_PUBLICO[motivo]));
      if (motivo !== null && aviso === "recurso_decidido") {
        assert.ok(email.corpo.includes(CAUSA_DO_MOTIVO_PUBLICO[motivo]));
        assert.ok(!/recorrer/i.test(email.corpo));
      }
      assert.doesNotMatch(email.corpo, /\d{3}/, "nenhum numero no texto");
    }
    assert.deepEqual([...vistos].sort(), [...AVISOS].sort());
  });
});

describe("avisos: a via (criterio 5, «nunca o numero da loja»)", () => {
  const pepper = randomBytes(32);

  it("o SMS vai para o telefone registado no onboarding, pelo modelo, e nunca para o da loja", async () => {
    const sms = new FakeSmsProvider();
    const pedidos: { onboardingId: string; campo: string }[] = [];
    const onboardingId = randomUUID();
    const aviso = new AvisoAoDonoPorVia({
      sms,
      pepperDoDestino: pepper,
      dados: {
        async ler(id, campo) {
          pedidos.push({ onboardingId: id, campo });
          return campo === "telefone" && id === onboardingId ? REGISTADO : null;
        },
      },
    });
    await aviso.avisar({ onboardingId, via: "sms", aviso: "rejeitado", motivoPublico: "documento_expirado" });
    assert.deepEqual(pedidos, [{ onboardingId, campo: "telefone" }]);
    assert.equal(sms.enviados.length, 1);
    const enviado = sms.enviados[0]!;
    assert.equal(enviado.modelo, "revisao_rejeitado");
    assert.equal(enviado.destinoHmac, cunharDestino(REGISTADO, pepper).hmac);
    assert.notEqual(enviado.destinoHmac, cunharDestino(DA_LOJA, pepper).hmac);
    assert.ok(enviado.corpo.includes(TEXTO_DO_MOTIVO_PUBLICO.documento_expirado));
  });

  it("sem telefone registado, o SMS levanta: o efeito fica por aplicar e nao vai para outro sitio", async () => {
    const sms = new FakeSmsProvider();
    const aviso = new AvisoAoDonoPorVia({ sms, pepperDoDestino: pepper, dados: { ler: async () => null } });
    await assert.rejects(
      aviso.avisar({ onboardingId: randomUUID(), via: "sms", aviso: "aprovado", motivoPublico: null }),
      (e: unknown) => e instanceof AvisoSemDestinoError && e.via === "sms",
    );
    assert.equal(sms.enviados.length, 0);
  });

  it("o e-mail vai pela porta do correio, que resolve o endereco; sem ela, levanta", async () => {
    const correio: { onboardingId: string; assunto: string; corpo: string; chave: string }[] = [];
    const onboardingId = randomUUID();
    const comCorreio = new AvisoAoDonoPorVia({
      sms: new FakeSmsProvider(),
      pepperDoDestino: pepper,
      dados: { ler: async () => REGISTADO },
      correio: { enviar: async (p) => void correio.push({ ...p }) },
    });
    await comCorreio.avisar({ onboardingId, via: "email", aviso: "pedir_info", motivoPublico: "informacao_em_falta" });
    assert.equal(correio.length, 1);
    assert.equal(correio[0]!.onboardingId, onboardingId);
    assert.ok(correio[0]!.corpo.includes(TEXTO_DO_MOTIVO_PUBLICO.informacao_em_falta));
    const semCorreio = new AvisoAoDonoPorVia({ sms: new FakeSmsProvider(), pepperDoDestino: pepper, dados: { ler: async () => REGISTADO } });
    await assert.rejects(
      semCorreio.avisar({ onboardingId, via: "email", aviso: "aprovado", motivoPublico: null }),
      AvisoSemDestinoError,
    );
  });

  it("dois avisos ao mesmo onboarding saem os dois: a chave e uma por chamada", async () => {
    const sms = new FakeSmsProvider();
    const aviso = new AvisoAoDonoPorVia({ sms, pepperDoDestino: pepper, dados: { ler: async () => REGISTADO } });
    const id = randomUUID();
    await aviso.avisar({ onboardingId: id, via: "sms", aviso: "pedir_info", motivoPublico: "informacao_em_falta" });
    await aviso.avisar({ onboardingId: id, via: "sms", aviso: "pedir_info", motivoPublico: "informacao_em_falta" });
    assert.equal(sms.enviados.length, 2);
    assert.notEqual(sms.enviados[0]!.chave, sms.enviados[1]!.chave);
  });

  it("ligado ao servico: uma rejeicao de primeira instancia chega ao dono pelo telefone registado", async () => {
    const sms = new FakeSmsProvider();
    const m = montarRevisao({ agora: SEXTA });
    const o = m.onboarding();
    m.dados.set(o.id, { telefone: REGISTADO });
    // O servico do apoio regista os avisos num array; aqui liga-se o adaptador
    // verdadeiro por cima da mesma porta `dados` que o servico usa.
    const adaptador = new AvisoAoDonoPorVia({
      sms,
      pepperDoDestino: pepper,
      dados: { ler: async (id, campo) => m.dados.get(id)?.[campo] ?? null },
    });
    const aberto = await m.abrir(o);
    assert.ok(aberto.estado === "aberto");
    await m.servico.decidir(revisor(), aberto.caso.id, "rejeitar", { motivoPublico: "categoria_nao_permitida" });
    assert.equal(m.avisos.length, 1);
    await adaptador.avisar(m.avisos[0]!);
    assert.equal(sms.enviados[0]!.destinoHmac, cunharDestino(REGISTADO, pepper).hmac);
    assert.ok(sms.enviados[0]!.corpo.includes(TEXTO_DO_MOTIVO_PUBLICO.categoria_nao_permitida));
  });
});
