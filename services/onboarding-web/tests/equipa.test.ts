/**
 * A consola da fila de revisão (KAM-196): a porta da identidade da equipa, as
 * rotas `/equipa` sobre o serviço com duplos, e os ataques do bloco.
 *
 * **O IdP falso só existe neste ficheiro** (DoD do bloco). Os telefones são
 * nacionais a começar por zero, escritos com espaços: o número de ninguém.
 */

import assert from "node:assert/strict";
import { createHmac, randomBytes, randomUUID } from "node:crypto";
import { describe, it } from "node:test";

import { cunharReferencia, NOME_DO_COOKIE } from "@kamba/core-ts/inscricao";
import {
  AuditoriaEmMemoria,
  AvisoAoDonoPorVia,
  CicloDaFila,
  FilaDeRevisaoEmMemoria,
  OnboardingsEmMemoria,
  ServicoDeRevisao,
  TEXTO_DO_MOTIVO_PUBLICO,
  type CampoPessoal,
  type OnboardingDaRevisao,
} from "@kamba/core-ts/revisao";
import { FakeSmsProvider, cunharDestino } from "@kamba/core-ts/sms";

import { createApp } from "../src/app.ts";
import {
  DOMINIO_DA_SESSAO_DA_EQUIPA,
  RevogacoesDaEquipaEmMemoria,
  cunharSessaoDaEquipa,
  lerSessaoDaEquipa,
  novaSessaoDaEquipa,
  type Autenticacao,
  type ContaDaEquipa,
  type IdentidadeDaEquipa,
} from "../src/equipa/sessao.ts";
import { cunharSessao, lerSessao, novaSessao } from "../src/painel/sessao.ts";

const AGORA = new Date("2026-11-13T09:00:00Z");
const REGISTADO = "+244 000 000 101";

/** O IdP falso: provas de uso único, contas com papéis, e a MFA de cada prova. */
class IdpFalso implements IdentidadeDaEquipa {
  readonly contas = new Map<string, ContaDaEquipa>();
  readonly provas = new Map<string, Autenticacao>();

  conta_(papeis: string[], o: Partial<ContaDaEquipa> = {}): ContaDaEquipa {
    const c: ContaDaEquipa = { id: randomUUID(), papeis, nifHmac: null, telefoneHmac: null, ...o };
    this.contas.set(c.id, c);
    return c;
  }

  prova(id: string, mfa: boolean): string {
    const p = randomBytes(16).toString("hex");
    this.provas.set(p, { id, mfa });
    return p;
  }

  async autenticar(prova: string): Promise<Autenticacao | null> {
    const a = this.provas.get(prova) ?? null;
    this.provas.delete(prova);
    return a;
  }

  async conta(id: string): Promise<ContaDaEquipa | null> {
    return this.contas.get(id) ?? null;
  }
}

function montar(o: { avisoFalha?: boolean } = {}) {
  const chave = randomBytes(32);
  const agora = AGORA;
  const relogio = () => agora;
  const onboardings = new OnboardingsEmMemoria();
  const repositorio = new FilaDeRevisaoEmMemoria(() => null, relogio);
  const auditoria = new AuditoriaEmMemoria();
  const dados = new Map<string, Partial<Record<CampoPessoal, string>>>();
  const sms = new FakeSmsProvider();
  const pepper = randomBytes(32);
  const lerDados = async (id: string, campo: CampoPessoal) => dados.get(id)?.[campo] ?? null;
  const adaptador = new AvisoAoDonoPorVia({ sms, pepperDoDestino: pepper, dados: { ler: lerDados } });
  let falhar = o.avisoFalha ?? false;
  const servico = new ServicoDeRevisao({
    repositorio,
    onboardings,
    auditoria,
    aviso: {
      async avisar(p) {
        if (falhar) throw new Error("agregador em baixo");
        await adaptador.avisar(p);
      },
    },
    alerta: () => {},
    cifra: { cifrar: async (b) => b, decifrar: async (b) => b },
    dados: { ler: lerDados },
    documentos: {
      async url(_rev, _onb, verificacaoId, aud) {
        await aud.anotarAcesso({ revisor: _rev, onboardingId: _onb, verificacaoId, em: relogio() });
        return `https://sto.invalid/${verificacaoId}?ttl=300`;
      },
    },
    screening: { gravar: async () => {} },
    relogio,
  });
  const ciclo = new CicloDaFila({ servico, leitor: { vista: async () => [], contadores: async () => [] } });
  const idp = new IdpFalso();
  const revogacoes = new RevogacoesDaEquipaEmMemoria();
  const app = createApp(undefined, undefined, undefined, undefined, {
    identidade: idp,
    servico,
    auditoria,
    revogacoes,
    anelDaAssinatura: [chave, null],
    efeitoFalhou: (id) => ciclo.efeitoFalhou(id),
    relogio,
  });

  const onboarding = (c: Partial<OnboardingDaRevisao> = {}): OnboardingDaRevisao => {
    const x: OnboardingDaRevisao = {
      id: randomUUID(),
      tenantId: randomUUID(),
      fase: "em_revisao",
      redeHmac: randomBytes(32).toString("hex"),
      dispositivoHmac: null,
      nifHmac: randomBytes(32).toString("hex"),
      telefoneHmac: randomBytes(32).toString("hex"),
      ...c,
    };
    onboardings.casos.set(x.id, x);
    dados.set(x.id, { nif: "NIF-SINTETICO-0001", numero_bi: "BI-SINTETICO-0001", telefone: REGISTADO });
    return x;
  };
  const verificacao = randomUUID();
  const abrir = async (x: OnboardingDaRevisao, prioridade = 5) => {
    const r = await servico.abrir({
      tipo: "kyc",
      tenantId: x.tenantId,
      onboardingId: x.id,
      motivoCodigo: "kyc_k1",
      motivoInterno: "motivo-interno-do-caso",
      motivoPublico: "nao_foi_possivel_validar",
      evidencias: [{ tipo: "kyc_check", ref: verificacao }],
      recomendacao: "investigar",
      prioridade,
    });
    assert.ok(r.estado === "aberto");
    return r.caso;
  };

  /** Entra pelo IdP e devolve o cookie. */
  const entrar = async (papeis: string[] = ["ts_revisor"], extra: Partial<ContaDaEquipa> = {}) => {
    const conta = idp.conta_(papeis, extra);
    const r = await app.request(`/equipa/entrar?prova=${idp.prova(conta.id, true)}`);
    assert.equal(r.status, 303);
    const cookie = (r.headers.get("set-cookie") ?? "").split(";")[0]!;
    assert.match(cookie, /^kamba_equipa=v1\./);
    return { conta, cookie };
  };

  /** Uma sessão cunhada à mão (para a sem MFA, que o `entrar` nunca cunha). */
  const sessao = (conta: ContaDaEquipa, mfa: boolean) =>
    `kamba_equipa=${cunharSessaoDaEquipa(novaSessaoDaEquipa({ id: conta.id, mfa }, agora), chave)}`;

  const pedir = (caminho: string, cookie: string | null, corpo?: unknown, metodo?: string) =>
    app.request(caminho, {
      method: metodo ?? (corpo === undefined ? "GET" : "POST"),
      headers: {
        ...(cookie === null ? {} : { cookie }),
        ...(corpo === undefined ? {} : { "content-type": "application/json" }),
      },
      ...(corpo === undefined ? {} : { body: JSON.stringify(corpo) }),
    });

  return {
    app, chave, idp, servico, repositorio, onboardings, auditoria, sms, pepper, ciclo, revogacoes,
    onboarding, abrir, entrar, sessao, pedir, verificacao, agora,
    falhar: (v: boolean) => (falhar = v),
  };
}

/** As sete rotas da consola que leem ou escrevem um caso. */
function rotasDoCaso(id: string, verificacao: string): [string, string, unknown?][] {
  return [
    ["GET", "/equipa/casos"],
    ["GET", `/equipa/casos/${id}`],
    ["POST", `/equipa/casos/${id}/revelar`, { campo: "nif" }],
    ["GET", `/equipa/casos/${id}/documentos/${verificacao}`],
    ["POST", `/equipa/casos/${id}/decisao`, { decisao: "aprovar" }],
    ["POST", `/equipa/casos/${id}/recurso`, {}],
    ["POST", `/equipa/casos/${id}/recurso/decisao`, { decisao: "aprovar" }],
  ];
}

// ------------------------------------------------------------ a porta e a sessao

describe("equipa: a porta da identidade (criterio 2)", () => {
  it("entrar com uma prova do IdP com MFA e papel cunha a sessao e vai para a lista", async () => {
    const m = montar();
    const { conta, cookie } = await m.entrar();
    const s = lerSessaoDaEquipa(cookie.slice("kamba_equipa=".length), [m.chave], m.agora);
    assert.equal(s?.conta, conta.id);
    assert.equal(s?.mfa, true);
  });

  it("sem prova, com prova falsa, ou com a mesma prova duas vezes: 401", async () => {
    const m = montar();
    const conta = m.idp.conta_(["ts_revisor"]);
    const prova = m.idp.prova(conta.id, true);
    assert.equal((await m.app.request("/equipa/entrar")).status, 401);
    assert.equal((await m.app.request("/equipa/entrar?prova=inventada")).status, 401);
    assert.equal((await m.app.request(`/equipa/entrar?prova=${prova}`)).status, 303);
    assert.equal((await m.app.request(`/equipa/entrar?prova=${prova}`)).status, 401);
  });

  it("sem MFA ou sem papel: 403, sem sessao, e a recusa fica no audit_log", async () => {
    const m = montar();
    const comPapel = m.idp.conta_(["ts_revisor"]);
    const semPapel = m.idp.conta_(["suporte"]);
    const r1 = await m.app.request(`/equipa/entrar?prova=${m.idp.prova(comPapel.id, false)}`);
    const r2 = await m.app.request(`/equipa/entrar?prova=${m.idp.prova(semPapel.id, true)}`);
    assert.equal(r1.status, 403);
    assert.equal(r2.status, 403);
    assert.equal(r1.headers.get("set-cookie"), null);
    assert.equal(r2.headers.get("set-cookie"), null);
    assert.deepEqual(
      m.auditoria.linhas.map((l) => [l.accao, l.actorId, l.detalhe]),
      [
        ["review.recusa", comPapel.id, "sem_mfa"],
        ["review.recusa", semPapel.id, "sem_papel"],
      ],
    );
  });

  it("a sessao da equipa e a do painel nao se aceitam uma a outra: separador de dominio proprio", () => {
    const chave = randomBytes(32);
    const conta = randomUUID();
    const daEquipa = cunharSessaoDaEquipa(novaSessaoDaEquipa({ id: conta, mfa: true }, AGORA), chave);
    const doPainel = cunharSessao(novaSessao(randomUUID(), conta, AGORA), chave);
    assert.equal(lerSessao(daEquipa, [chave], AGORA), null);
    assert.equal(lerSessaoDaEquipa(doPainel, [chave], AGORA), null);
    assert.equal(DOMINIO_DA_SESSAO_DA_EQUIPA, "kamba/equipa/sessao/v1");
  });

  it("a sessao expira as 8 h, e outra chave nao a verifica", () => {
    const chave = randomBytes(32);
    const s = cunharSessaoDaEquipa(novaSessaoDaEquipa({ id: randomUUID(), mfa: true }, AGORA), chave);
    assert.notEqual(lerSessaoDaEquipa(s, [chave], new Date(AGORA.getTime() + 8 * 3600_000)), null);
    assert.equal(lerSessaoDaEquipa(s, [chave], new Date(AGORA.getTime() + 8 * 3600_000 + 1000)), null);
    assert.equal(lerSessaoDaEquipa(s, [randomBytes(32)], AGORA), null);
  });

  it("o papel le-se a cada pedido: tirar o papel ou desactivar a conta fecha a consola logo", async () => {
    const m = montar();
    const { conta, cookie } = await m.entrar();
    assert.equal((await m.pedir("/equipa/casos", cookie)).status, 200);
    m.idp.contas.set(conta.id, { ...conta, papeis: [] });
    assert.equal((await m.pedir("/equipa/casos", cookie)).status, 403);
    m.idp.contas.delete(conta.id);
    assert.equal((await m.pedir("/equipa/casos", cookie)).status, 401);
  });

  it("o HMAC leva o separador: um texto com a forma da equipa assinado sob o do painel nao verifica", () => {
    const chave = randomBytes(32);
    const s = novaSessaoDaEquipa({ id: randomUUID(), mfa: true }, AGORA);
    const texto = `v1.${s.sid}.${s.conta}.1.${s.emitida}`;
    const comOutro = createHmac("sha256", chave).update("kamba/painel/sessao/v1").update("\u0000").update(texto).digest("base64url");
    const semNenhum = createHmac("sha256", chave).update(texto).digest("base64url");
    const comOProprio = createHmac("sha256", chave).update(DOMINIO_DA_SESSAO_DA_EQUIPA).update("\u0000").update(texto).digest("base64url");
    assert.equal(lerSessaoDaEquipa(`${texto}.${comOutro}`, [chave], AGORA), null);
    assert.equal(lerSessaoDaEquipa(`${texto}.${semNenhum}`, [chave], AGORA), null);
    assert.notEqual(lerSessaoDaEquipa(`${texto}.${comOProprio}`, [chave], AGORA), null, "o controlo: com o separador certo verifica");
  });

  it("uma conta que o IdP devolve com outro id nao entra, nem a entrada nem a sessao", async () => {
    const m = montar();
    const { conta, cookie } = await m.entrar();
    const outra = m.idp.conta_(["ts_lider"]);
    m.idp.contas.set(conta.id, outra);
    assert.equal((await m.pedir("/equipa/casos", cookie)).status, 401);
    const nova = m.idp.conta_(["ts_revisor"]);
    m.idp.contas.set(nova.id, outra);
    assert.equal((await m.app.request(`/equipa/entrar?prova=${m.idp.prova(nova.id, true)}`)).status, 401);
  });

  it("sair revoga so a sessao verificada: um sid alheio forjado nao desliga ninguem", async () => {
    const m = montar();
    const a = await m.entrar();
    const b = await m.entrar();
    const sidDeB = b.cookie.split(".")[1]!;
    const forjada = a.cookie.replace(a.cookie.split(".")[1]!, sidDeB);
    assert.equal((await m.pedir("/equipa/sair", forjada, {})).status, 200);
    assert.equal((await m.pedir("/equipa/casos", b.cookie)).status, 200, "B continua dentro");
    const r = await m.pedir("/equipa/sair", a.cookie, {});
    assert.match(r.headers.get("set-cookie") ?? "", /Max-Age=0/);
    assert.equal((await m.pedir("/equipa/casos", a.cookie)).status, 401);
  });
});

// ------------------------------------------------------------ os ataques do bloco

describe("equipa: nenhuma rota responde sem identidade com MFA (adversarial)", () => {
  it("sem cookie, com a sessao do dono (painel e registo) ou com ela no cookie da equipa: 401 em todas", async () => {
    const m = montar();
    const caso = await m.abrir(m.onboarding());
    const chaveDoDono = m.chave;
    const doPainel = cunharSessao(novaSessao(randomUUID(), randomUUID(), m.agora), chaveDoDono);
    const doRegisto = cunharReferencia("sessao", caso.onboardingId!, chaveDoDono, () => m.agora);
    for (const cookie of [null, `kamba_painel=${doPainel}`, `${NOME_DO_COOKIE}=${doRegisto}`, `kamba_equipa=${doPainel}`, `kamba_equipa=${doRegisto}`]) {
      for (const [metodo, caminho, corpo] of rotasDoCaso(caso.id, m.verificacao)) {
        const r = await m.pedir(caminho, cookie, corpo, metodo);
        assert.equal(r.status, 401, `${metodo} ${caminho} com ${cookie?.split("=")[0]}`);
        assert.ok(!(await r.text()).includes("motivo-interno"), caminho);
      }
    }
    assert.equal(m.repositorio.registo.length, 0, "nenhuma decisao passou");
    assert.equal(m.repositorio.casos.get(caso.id)!.estado, "aberto", "ninguem abriu o caso");
  });

  it("uma sessao de equipa sem papel, e uma sem MFA: 403 em todas, sem nada do caso, e cada uma no audit_log", async () => {
    const m = montar();
    const caso = await m.abrir(m.onboarding());
    const semPapel = m.idp.conta_(["suporte"]);
    const semMfa = m.idp.conta_(["ts_lider"]);
    const rotas = rotasDoCaso(caso.id, m.verificacao);
    for (const [cookie, motivo, conta] of [
      [m.sessao(semPapel, true), "sem_papel", semPapel],
      [m.sessao(semMfa, false), "sem_mfa", semMfa],
    ] as const) {
      const antes = m.auditoria.linhas.length;
      for (const [metodo, caminho, corpo] of rotas) {
        const r = await m.pedir(caminho, cookie, corpo, metodo);
        assert.equal(r.status, 403, `${motivo} ${metodo} ${caminho}`);
        const texto = await r.text();
        assert.ok(!texto.includes("motivo-interno") && !texto.includes("SINTETICO"), caminho);
      }
      const novas = m.auditoria.linhas.slice(antes);
      assert.equal(novas.length, rotas.length);
      // `barreira`: a recusa e da barreira, antes do servico. Sem a barreira o
      // servico tambem recusava com 403, mas com o caso no registo.
      assert.ok(novas.every((l) => l.accao === "review.recusa" && l.detalhe === motivo && l.actorId === conta.id && l.entidadeId === "barreira"));
    }
    assert.equal(m.repositorio.casos.get(caso.id)!.estado, "aberto");
  });

  it("um formulario de outra origem nao escreve: todos os POST exigem JSON (415)", async () => {
    const m = montar();
    const caso = await m.abrir(m.onboarding());
    const { cookie } = await m.entrar();
    for (const caminho of [
      "/equipa/sair",
      `/equipa/casos/${caso.id}/revelar`,
      `/equipa/casos/${caso.id}/decisao`,
      `/equipa/casos/${caso.id}/recurso`,
      `/equipa/casos/${caso.id}/recurso/decisao`,
    ]) {
      const r = await m.app.request(caminho, {
        method: "POST",
        headers: { cookie, "content-type": "application/x-www-form-urlencoded" },
        body: "decisao=rejeitar&campo=nif",
      });
      assert.equal(r.status, 415, caminho);
    }
    assert.equal(m.repositorio.casos.get(caso.id)!.estado, "aberto");
    assert.equal((await m.pedir("/equipa/casos", cookie)).status, 200, "o sair por formulario nao revogou");
  });

  it("a lista nao exporta mais de uma pagina, e nao ha rota de exportacao", async () => {
    const m = montar();
    for (let i = 0; i < 120; i++) await m.abrir(m.onboarding());
    const { cookie } = await m.entrar();
    const p0 = (await (await m.pedir("/equipa/casos?limite=1000&pagina=0", cookie)).json()) as { casos: unknown[] };
    const p2 = (await (await m.pedir("/equipa/casos?pagina=2", cookie)).json()) as { casos: unknown[] };
    assert.equal(p0.casos.length, 50);
    assert.equal(p2.casos.length, 20);
    for (const caminho of ["/equipa/exportar", "/equipa/casos.csv", "/equipa/casos/exportar"]) {
      assert.equal((await m.pedir(caminho, cookie)).status, 404, caminho);
    }
    assert.equal((await m.pedir("/equipa/casos?pagina=99999", cookie)).status, 400);
    assert.equal((await m.pedir("/equipa/casos?tipo=fraude", cookie)).status, 400);
  });

  it("a lista nao leva dados pessoais nem o motivo interno", async () => {
    const m = montar();
    await m.abrir(m.onboarding());
    const { cookie } = await m.entrar();
    const texto = await (await m.pedir("/equipa/casos", cookie)).text();
    assert.ok(!texto.includes("SINTETICO") && !texto.includes("motivo-interno") && !texto.includes("000 000"));
    assert.ok(!/onboardingId|tenantId|evidencias/.test(texto));
  });
});

// ------------------------------------------------------------ ponta a ponta

describe("equipa: as rotas sobre o servico, ponta a ponta (criterio 3)", () => {
  it("ver, revelar, documento, rejeitar, recurso e decisao do recurso, com o audit_log de cada visualizacao", async () => {
    const m = montar();
    const o = m.onboarding();
    const caso = await m.abrir(o);
    const a = await m.entrar();

    const vista = await m.pedir(`/equipa/casos/${caso.id}`, a.cookie);
    assert.equal(vista.status, 200);
    const v = (await vista.json()) as { dados: Record<string, string>; motivoInterno: string; estado: string };
    assert.equal(v.dados["telefone"], `${"*".repeat(10)}101`, "o mascarar tira os espacos");
    assert.equal(v.dados["nif"], `${"*".repeat(15)}001`);
    assert.equal(v.estado, "em_analise");

    const revelado = await m.pedir(`/equipa/casos/${caso.id}/revelar`, a.cookie, { campo: "nif" });
    assert.deepEqual(await revelado.json(), { campo: "nif", valor: "NIF-SINTETICO-0001" });
    assert.equal((await m.pedir(`/equipa/casos/${caso.id}/revelar`, a.cookie, { campo: "morada" })).status, 400);

    const doc = await m.pedir(`/equipa/casos/${caso.id}/documentos/${m.verificacao}`, a.cookie);
    assert.equal(doc.status, 303);
    assert.equal(doc.headers.get("location"), `https://sto.invalid/${m.verificacao}?ttl=300`);
    assert.equal(doc.headers.get("referrer-policy"), "no-referrer");
    const alheio = await m.pedir(`/equipa/casos/${caso.id}/documentos/${randomUUID()}`, a.cookie);
    assert.equal(alheio.status, 403);

    assert.deepEqual(
      m.auditoria.linhas.map((l) => [l.accao, l.entidade, l.detalhe]),
      [
        ["review.acesso", "review_case", "ver"],
        ["review.acesso", "onboarding_case", "revelar:nif"],
        ["review.acesso", "kyc_check", "documento"],
        ["review.recusa", "review_case", "evidencia_alheia"],
      ],
    );

    const rejeitar = await m.pedir(`/equipa/casos/${caso.id}/decisao`, a.cookie, {
      decisao: "rejeitar",
      regra: "k1.nif_divergente",
      nota: "nota do revisor",
    });
    assert.equal(rejeitar.status, 200);
    assert.deepEqual(await rejeitar.json(), { estado: "decidido", caso: { id: caso.id, estado: "decidido" } });
    assert.equal(m.onboardings.casos.get(o.id)!.fase, "rejeitado");
    // O aviso saiu pelo telefone registado, com o texto fixo do motivo.
    assert.equal(m.sms.enviados.length, 1);
    assert.equal(m.sms.enviados[0]!.modelo, "revisao_rejeitado");
    assert.equal(m.sms.enviados[0]!.destinoHmac, cunharDestino(REGISTADO, m.pepper).hmac);
    assert.ok(m.sms.enviados[0]!.corpo.includes(TEXTO_DO_MOTIVO_PUBLICO.nao_foi_possivel_validar));
    assert.ok(!m.sms.enviados[0]!.corpo.includes("nota do revisor"));

    // Decidir outra vez o mesmo caso: 409.
    assert.equal((await m.pedir(`/equipa/casos/${caso.id}/decisao`, a.cookie, { decisao: "aprovar" })).status, 409);

    // O recurso: regista-se, e quem decidiu a primeira nao o decide.
    const recurso = await m.pedir(`/equipa/casos/${caso.id}/recurso`, a.cookie, {});
    assert.equal(recurso.status, 200);
    assert.equal((await m.pedir(`/equipa/casos/${caso.id}/recurso`, a.cookie, {})).status, 409, "um recurso por decisao");
    const mesmo = await m.pedir(`/equipa/casos/${caso.id}/recurso/decisao`, a.cookie, { decisao: "aprovar" });
    assert.equal(mesmo.status, 403);
    assert.deepEqual(await mesmo.json(), { erro: "revisor_da_primeira_instancia" });
    const b = await m.entrar();
    const final = await m.pedir(`/equipa/casos/${caso.id}/recurso/decisao`, b.cookie, { decisao: "aprovar" });
    assert.equal(final.status, 200);
    assert.deepEqual(await final.json(), { estado: "decidido", caso: { id: caso.id, estado: "decidido_final" } });
    assert.equal(m.sms.enviados.at(-1)!.modelo, "revisao_recurso_aprovado");
    // O motivo do recurso mantido seria o mesmo do primeiro aviso: e o do caso.
    const detalhes = m.auditoria.linhas.map((l) => l.detalhe);
    assert.ok(detalhes.includes("recurso:abrir") && detalhes.includes("revisor_da_primeira_instancia"));
  });

  it("um caso escalado so o lider decide: 403 so_lider ao revisor, 200 ao lider", async () => {
    const m = montar();
    const caso = await m.abrir(m.onboarding());
    const a = await m.entrar(["ts_revisor"]);
    assert.equal((await m.pedir(`/equipa/casos/${caso.id}/decisao`, a.cookie, { decisao: "escalar" })).status, 200);
    const r = await m.pedir(`/equipa/casos/${caso.id}/decisao`, a.cookie, { decisao: "aprovar" });
    assert.equal(r.status, 403);
    assert.deepEqual(await r.json(), { erro: "so_lider" });
    const lider = await m.entrar(["ts_lider"]);
    assert.equal((await m.pedir(`/equipa/casos/${caso.id}/decisao`, lider.cookie, { decisao: "aprovar" })).status, 200);
  });

  it("quem e parte no caso nao o le: 403 parte_no_caso", async () => {
    const m = montar();
    const o = m.onboarding();
    const caso = await m.abrir(o);
    const a = await m.entrar(["ts_revisor"], { telefoneHmac: o.telefoneHmac });
    const r = await m.pedir(`/equipa/casos/${caso.id}`, a.cookie);
    assert.equal(r.status, 403);
    assert.deepEqual(await r.json(), { erro: "parte_no_caso" });
  });

  it("corpos sem forma: 400 ou 415, e o caso fica onde estava", async () => {
    const m = montar();
    const caso = await m.abrir(m.onboarding());
    const { cookie } = await m.entrar();
    const url = `/equipa/casos/${caso.id}/decisao`;
    for (const corpo of [{ decisao: "aprovar_tudo" }, { decisao: "rejeitar", motivo_publico: "o seu NIF e falso" }, { decisao: "rejeitar", motivo_publico: "documento_expirado" }, { decisao: "aprovar", nota: "x".repeat(2001) }, { decisao: "aprovar", regra: "Regra Livre" }]) {
      assert.equal((await m.pedir(url, cookie, corpo)).status, 400, JSON.stringify(corpo).slice(0, 60));
    }
    const formulario = await m.app.request(url, { method: "POST", headers: { cookie, "content-type": "application/x-www-form-urlencoded" }, body: "decisao=aprovar" });
    assert.equal(formulario.status, 415);
    assert.equal((await m.pedir(`/equipa/casos/nao-e-uuid`, cookie)).status, 404);
    assert.equal((await m.pedir(`/equipa/casos/${randomUUID()}`, cookie)).status, 404);
    assert.equal(m.repositorio.casos.get(caso.id)!.estado, "aberto");
  });

  it("um efeito que falha depois de o caso fechar vai para o job, e a volta seguinte reaplica-o", async () => {
    const m = montar({ avisoFalha: true });
    const o = m.onboarding();
    const caso = await m.abrir(o);
    const { cookie } = await m.entrar();
    const r = await m.pedir(`/equipa/casos/${caso.id}/decisao`, cookie, { decisao: "aprovar" });
    assert.equal(r.status, 202, "a decisao esta feita; repeti-la dava 409");
    assert.deepEqual(await r.json(), { estado: "efeito_por_aplicar", caso: { id: caso.id } });
    assert.equal(m.repositorio.casos.get(caso.id)!.estado, "decidido");
    assert.equal(m.onboardings.casos.get(o.id)!.fase, "aprovado");
    assert.deepEqual(await m.ciclo.efeitos.pendentes(10), [caso.id]);
    assert.equal(m.sms.enviados.length, 0);
    m.falhar(false);
    const volta = await m.ciclo.correr();
    assert.equal(volta.reaplicados, 1);
    assert.equal(m.sms.enviados.length, 1);
    assert.equal(m.sms.enviados[0]!.modelo, "revisao_aprovado");
  });
});
