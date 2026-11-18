/**
 * `resolve(phone_number_id)` e a *cache* de 60 s (KAM-014, critérios 1 e 8).
 *
 * O que aqui se prova é **lógica de *cache*** — o TTL, a invalidação, o tecto,
 * o que não se guarda — com o relógio injectado e uma base falsa. O que se
 * prova contra um PostgreSQL real vive em `db/tests_chr/`: que o
 * `phone_number_id` de A não devolve o contexto de B (propriedade da
 * `tenant_channels_phone_number_id_uq`), que o `kamba_resolver` consegue
 * responder **sem** contexto de tenant, e que não lê mais nada.
 */

import assert from "node:assert/strict";
import { describe, it } from "node:test";

import {
  CanalIlegivelError,
  ResolvedorDeCanal,
  SQL_CANAL,
  TIPO_DA_ACTIVACAO,
  TTL_MS,
  VersaoDaActivacaoError,
  canalDaLinha,
  efeitoDaActivacao,
} from "../src/chr/index.ts";
import type { Envelope } from "../src/eventos/envelope.ts";
import { BaseFalsa, linhaDeCanal } from "./apoio/chr-base-falsa.ts";

/** Um relógio que avança quando se lhe manda. */
function relogio(inicio = 1_000_000) {
  let agora = inicio;
  return {
    agora: () => agora,
    avancar: (ms: number) => {
      agora += ms;
    },
  };
}

describe("canalDaLinha", () => {
  it("devolve os oito campos do ChannelContext e o tipo do tenant", () => {
    const { contexto, tipoTenant } = canalDaLinha(linhaDeCanal());
    assert.deepEqual(Object.keys(contexto).sort(), [
      "channel_id",
      "channel_mode",
      "estado_canal",
      "estado_tenant",
      "origem",
      "plano",
      "tenant_id",
      "vertical",
    ]);
    assert.equal(tipoTenant, "pme");
  });

  it("nao devolve o `persona` do docs/tecnica/01 §7.2", () => {
    // O §7.2 poe `persona` no `ChannelContext`; o criterio 1 do ticket nao, e
    // `contacts.papel` — de onde a persona viria — nao existe em revisao
    // nenhuma. Esta a afirmacao de que a divergencia e deliberada.
    const { contexto } = canalDaLinha(linhaDeCanal());
    assert.ok(!("persona" in contexto));
  });

  it("um estado que o codigo nao conhece para a resolucao", () => {
    // Segunda barreira ao `CHECK` da `0001`: um estado novo na base nao pode
    // chegar ao `tenantGate`, que lancaria mais tarde — depois de a conversa
    // ja estar aberta.
    assert.throws(
      () => canalDaLinha(linhaDeCanal({ estado_canal: "hibernado" })),
      CanalIlegivelError,
    );
    assert.throws(
      () => canalDaLinha(linhaDeCanal({ estado_tenant: "quase_ativo" })),
      CanalIlegivelError,
    );
  });

  it("uma coluna em falta ou vazia lanca, e nao devolve contexto a metade", () => {
    for (const coluna of [
      "tenant_id",
      "channel_id",
      "vertical",
      "plano",
      "channel_mode",
      "origem",
      "tipo_tenant",
    ]) {
      assert.throws(
        () => canalDaLinha(linhaDeCanal({ [coluna]: "" })),
        CanalIlegivelError,
        coluna,
      );
      assert.throws(
        () => canalDaLinha(linhaDeCanal({ [coluna]: null })),
        CanalIlegivelError,
        coluna,
      );
    }
  });
});

describe("ResolvedorDeCanal", () => {
  it("a primeira resolucao vai a base, com o `phone_number_id` ligado", async () => {
    const bd = new BaseFalsa().responde("tenant_channels", { rows: [linhaDeCanal()] });
    const resolvedor = new ResolvedorDeCanal(bd);

    const leitura = await resolvedor.resolver("pnid-1");

    assert.equal(leitura.daCache, false);
    assert.equal(leitura.resolvido?.contexto.tenant_id, linhaDeCanal().tenant_id);
    assert.equal(bd.instrucoes.length, 1);
    assert.equal(bd.instrucoes[0]?.sql, SQL_CANAL);
    assert.deepEqual(bd.instrucoes[0]?.parametros, ["pnid-1"]);
  });

  it("a segunda resolucao dentro de 60 s nao vai a base", async () => {
    const bd = new BaseFalsa().responde("tenant_channels", { rows: [linhaDeCanal()] });
    const r = relogio();
    const resolvedor = new ResolvedorDeCanal(bd, { agora: r.agora });

    await resolvedor.resolver("pnid-1");
    r.avancar(TTL_MS - 1);
    const segunda = await resolvedor.resolver("pnid-1");

    assert.equal(segunda.daCache, true);
    assert.equal(bd.instrucoes.length, 1);
  });

  it("aos 60 s exactos a entrada expirou — o TTL e um limite e nao uma margem", async () => {
    const bd = new BaseFalsa().responde("tenant_channels", { rows: [linhaDeCanal()] });
    const r = relogio();
    const resolvedor = new ResolvedorDeCanal(bd, { agora: r.agora });

    await resolvedor.resolver("pnid-1");
    r.avancar(TTL_MS);
    const segunda = await resolvedor.resolver("pnid-1");

    assert.equal(segunda.daCache, false);
    assert.equal(bd.instrucoes.length, 2);
  });

  it("um canal desconhecido **nao** entra na cache", async () => {
    // Sem isto, quem conseguisse assinar corpos enchia a memoria com chaves
    // que nunca resolvem. O custo e uma ida a base por mensagem de um canal
    // desconhecido, que e precisamente o caso que o criterio 2 manda alertar.
    const bd = new BaseFalsa().responde("tenant_channels", { rows: [] });
    const resolvedor = new ResolvedorDeCanal(bd);

    assert.equal((await resolvedor.resolver("pnid-x")).resolvido, null);
    assert.equal((await resolvedor.resolver("pnid-x")).resolvido, null);

    assert.equal(bd.instrucoes.length, 2);
    assert.equal(resolvedor.tamanho, 0);
  });

  it("`invalidar` manda a resolucao seguinte a base", async () => {
    const bd = new BaseFalsa().responde("tenant_channels", { rows: [linhaDeCanal()] });
    const resolvedor = new ResolvedorDeCanal(bd);

    await resolvedor.resolver("pnid-1");
    assert.equal(resolvedor.invalidar("pnid-1"), true);
    assert.equal(resolvedor.invalidar("pnid-1"), false);
    await resolvedor.resolver("pnid-1");

    assert.equal(bd.instrucoes.length, 2);
  });

  it("`invalidarCanal` esquece pelo `channel_id`, que e o que o evento traz", async () => {
    // O `channel.updated` traz o identificador do canal e **nao** o
    // `phone_number_id`, que e a chave da cache. E o indice inverso que liga
    // os dois, e sem ele a invalidacao por evento era impossivel.
    const bd = new BaseFalsa().responde("tenant_channels", { rows: [linhaDeCanal()] });
    const resolvedor = new ResolvedorDeCanal(bd);

    await resolvedor.resolver("pnid-1");
    assert.equal(resolvedor.invalidarCanal(String(linhaDeCanal().channel_id)), true);
    await resolvedor.resolver("pnid-1");

    assert.equal(bd.instrucoes.length, 2);
  });

  it("`invalidarCanal` de um canal que nunca foi resolvido devolve false", async () => {
    // O consumidor de `channel.updated` (KAM-006) e idempotente e trata o
    // `false` como sucesso: um canal que este processo nunca viu nao esta em
    // cache nenhuma, e nao ha nada a invalidar.
    const resolvedor = new ResolvedorDeCanal(new BaseFalsa());
    assert.equal(resolvedor.invalidarCanal("33333333-3333-4333-8333-333333333333"), false);
  });

  it("`invalidarTenant` esquece os canais do tenant e só esses (KAM-092)", async () => {
    // O `tenant.activated` traz o `tenant_id` no envelope e nenhum
    // `phone_number_id`. Dois canais de A e um de B em cache: a activacao de A
    // esquece os dois de A, e o de B continua a responder da cache.
    const A = "11111111-1111-4111-8111-111111111111";
    const B = "55555555-5555-4555-8555-555555555555";
    const linhas: Record<string, Readonly<Record<string, unknown>>> = {
      "pnid-a1": linhaDeCanal({ tenant_id: A, channel_id: "a1a1a1a1-2222-4222-8222-222222222222" }),
      "pnid-a2": linhaDeCanal({ tenant_id: A, channel_id: "a2a2a2a2-2222-4222-8222-222222222222" }),
      "pnid-b1": linhaDeCanal({ tenant_id: B, channel_id: "b1b1b1b1-2222-4222-8222-222222222222" }),
    };
    let idas = 0;
    const resolvedor = new ResolvedorDeCanal({
      async query(_sql: string, parametros: readonly unknown[] = []) {
        idas += 1;
        return { rows: [linhas[String(parametros[0])]!] };
      },
    });
    for (const p of Object.keys(linhas)) await resolvedor.resolver(p);
    assert.equal(idas, 3);

    assert.equal(resolvedor.invalidarTenant(A), 2);
    assert.equal(resolvedor.tamanho, 1);
    assert.equal((await resolvedor.resolver("pnid-b1")).daCache, true, "o tenant B nao foi tocado");
    assert.equal((await resolvedor.resolver("pnid-a1")).daCache, false, "o tenant A volta a base");
    assert.equal(idas, 4);
    // O indice inverso tambem esqueceu: o `channel.updated` de um canal de A ja nao encontra nada.
    assert.equal(resolvedor.invalidarCanal("a2a2a2a2-2222-4222-8222-222222222222"), false);
    assert.equal(resolvedor.invalidarTenant("99999999-9999-4999-8999-999999999999"), 0);
  });

  it("o efeito esquece o tenant na activacao, na suspensao e no encerramento, e uma versao ou tipo desconhecido lanca", async () => {
    const pedidos: string[] = [];
    const efeito = efeitoDaActivacao({ invalidarTenant: (t) => (pedidos.push(t), 3) });
    const envelope = (tipo: string, versao: number) =>
      ({ tipo, versao, tenant_id: "11111111-1111-4111-8111-111111111111" }) as unknown as Envelope;
    let consultas = 0;
    const bd = { query: async () => (consultas++, { rows: [], rowCount: 0 }) };
    await efeito(bd, envelope(TIPO_DA_ACTIVACAO, 1));
    assert.equal(consultas, 0, "o efeito nao toca na base");
    assert.deepEqual(pedidos, ["11111111-1111-4111-8111-111111111111"]);
    // Uma versao nova engolida era uma activacao que o CHR nunca via: lanca, e o
    // `consumir` leva-a pela escada ate a DLQ.
    await assert.rejects(efeito(bd, envelope(TIPO_DA_ACTIVACAO, 2)), VersaoDaActivacaoError);
    assert.equal(pedidos.length, 1);
    // A suspensao (KAM-058) e o encerramento (KAM-098) esquecem da mesma forma;
    // a reactivacao e um tipo que este consumidor nao subscreve, e lanca.
    await efeito(bd, envelope("tenant.suspended", 1));
    await efeito(bd, envelope("tenant.closed", 1));
    assert.equal(pedidos.length, 3);
    await assert.rejects(efeito(bd, envelope("tenant.suspended", 2)), VersaoDaActivacaoError);
    await assert.rejects(efeito(bd, envelope("tenant.reactivated", 1)), VersaoDaActivacaoError);
    assert.equal(pedidos.length, 3);
  });

  it("o tecto de entradas expulsa a mais antiga", async () => {
    const bd = new BaseFalsa();
    let n = 0;
    const resolvedor = new ResolvedorDeCanal(
      {
        async query() {
          n += 1;
          return {
            rows: [
              linhaDeCanal({
                channel_id: `4${String(n).padStart(7, "0")}-3333-4333-8333-333333333333`,
              }),
            ],
          };
        },
      },
      { maximo: 2 },
    );

    await resolvedor.resolver("a");
    await resolvedor.resolver("b");
    await resolvedor.resolver("c");

    assert.equal(resolvedor.tamanho, 2);
    // O `a` foi expulso: a resolucao seguinte volta a base (n sobe para 4).
    await resolvedor.resolver("a");
    assert.equal(n, 4);
    assert.equal(bd.instrucoes.length, 0);
  });

  it("uma falha da base **nao** deixa a entrada expirada a servir de resposta", async () => {
    const bd = new BaseFalsa().responde(
      "tenant_channels",
      { rows: [linhaDeCanal()] },
      new Error("ligacao perdida"),
    );
    const r = relogio();
    const resolvedor = new ResolvedorDeCanal(bd, { agora: r.agora });

    await resolvedor.resolver("pnid-1");
    r.avancar(TTL_MS);
    await assert.rejects(() => resolvedor.resolver("pnid-1"), /ligacao perdida/);
    assert.equal(resolvedor.tamanho, 0);
  });

  it("dois `phone_number_id` sao duas entradas, e nao se confundem", async () => {
    // A propriedade que **importa** — o `phone_number_id` de A nunca devolve o
    // contexto de B — vem da `tenant_channels_phone_number_id_uq` e prova-se
    // contra a base. O que aqui se prova e que a cache nao a estraga.
    const resolvedor = new ResolvedorDeCanal({
      async query(_sql, parametros) {
        const pnid = String((parametros ?? [])[0]);
        return {
          rows: [
            linhaDeCanal({
              tenant_id:
                pnid === "pnid-a"
                  ? "aaaaaaaa-aaaa-4aaa-8aaa-aaaaaaaaaaaa"
                  : "bbbbbbbb-bbbb-4bbb-8bbb-bbbbbbbbbbbb",
              channel_id:
                pnid === "pnid-a"
                  ? "cccccccc-cccc-4ccc-8ccc-cccccccccccc"
                  : "dddddddd-dddd-4ddd-8ddd-dddddddddddd",
            }),
          ],
        };
      },
    });

    const a = await resolvedor.resolver("pnid-a");
    const b = await resolvedor.resolver("pnid-b");
    const aOutraVez = await resolvedor.resolver("pnid-a");

    assert.equal(a.resolvido?.contexto.tenant_id, "aaaaaaaa-aaaa-4aaa-8aaa-aaaaaaaaaaaa");
    assert.equal(b.resolvido?.contexto.tenant_id, "bbbbbbbb-bbbb-4bbb-8bbb-bbbbbbbbbbbb");
    assert.equal(aOutraVez.daCache, true);
    assert.equal(aOutraVez.resolvido?.contexto.tenant_id, a.resolvido?.contexto.tenant_id);
  });

  it("`esquecerTudo` esvazia os dois indices", async () => {
    const bd = new BaseFalsa().responde("tenant_channels", { rows: [linhaDeCanal()] });
    const resolvedor = new ResolvedorDeCanal(bd);
    await resolvedor.resolver("pnid-1");
    resolvedor.esquecerTudo();
    assert.equal(resolvedor.tamanho, 0);
    assert.equal(resolvedor.invalidarCanal(String(linhaDeCanal().channel_id)), false);
  });
});
