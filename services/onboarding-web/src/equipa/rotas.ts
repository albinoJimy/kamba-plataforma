/**
 * A consola da fila de revisão (KAM-196, critério 3): as rotas `/equipa` sobre o
 * `ServicoDeRevisao` do KAM-089.
 *
 *     GET  /equipa/entrar                             o regresso do IdP: troca a
 *                                                     prova pela sessão; 401 sem
 *                                                     prova válida, 403 sem MFA
 *     POST /equipa/sair                               revoga a sessão
 *     GET  /equipa/casos                              uma página, sem dados pessoais
 *     GET  /equipa/casos/:id                          o caso, mascarado
 *     POST /equipa/casos/:id/revelar                  um campo em claro, registado
 *     GET  /equipa/casos/:id/documentos/:verificacao  303 para a URL de ≤ 300 s
 *     POST /equipa/casos/:id/decisao                  aprovar, rejeitar, pedir_info, escalar
 *     POST /equipa/casos/:id/recurso                  regista o recurso do dono
 *     POST /equipa/casos/:id/recurso/decisao          aprovar ou rejeitar o recurso
 *
 * **Não há rota de exportação**, e a lista devolve uma página de cada vez com o
 * tecto do serviço (`paginaMaxima`, 50): um `limite` na consulta não existe.
 *
 * ## Nenhuma rota responde sem identidade com MFA
 *
 * Todas as rotas menos as duas da sessão passam pelo `comRevisor`, que é a
 * barreira inteira, **antes** de o serviço ser chamado:
 *
 * ```text
 * sem cookie da equipa, sessão forjada, expirada,
 * revogada, ou conta que o IdP já não tem          401   (nada no audit_log: não
 *                                                         há a quem o atribuir)
 * sessão sem MFA                                   403   review.recusa sem_mfa
 * conta sem ts_revisor nem ts_lider                403   review.recusa sem_papel
 * ```
 *
 * Uma sessão do dono — a do painel (`kamba_painel`) ou a do registo
 * (`kamba_onboarding`) — não é um cookie da equipa, e o valor dela posto no
 * cookie da equipa não verifica (outro separador de domínio). As duas dão 401.
 *
 * O serviço volta a exigir o papel e a MFA (o `#exigirIdentidade` dele), e é ele
 * que recusa o resto — o `escalado` só ao líder, quem é parte no caso, o mesmo
 * revisor duas vezes. Uma recusa dele responde o `estadoHttp` do erro (403 ou
 * 409) e já ficou no `audit_log`.
 *
 * ## CSRF
 *
 * **Todos** os `POST` — o `sair` e o `recurso` também, que não têm corpo útil —
 * exigem `application/json`, que um formulário de outra origem não manda sem
 * *preflight*; sem ele, 415. E o cookie é `SameSite=Lax` (ver `./sessao.ts`).
 * A primeira versão só exigia JSON às rotas com corpo, e um formulário abria um
 * recurso (achado 5 da revisão adversarial).
 *
 * ## O motivo público é o do caso
 *
 * A consola **não aceita** um `motivo_publico` na decisão. O serviço sabe usá-lo
 * no aviso dessa decisão, mas não o guarda (o `review_decision_log` não tem a
 * coluna): o recurso e a reaplicação de um efeito voltavam ao motivo do caso, e
 * o dono lia dois motivos diferentes para a mesma recusa (achado 4). Com o motivo
 * fixado na abertura, todos os avisos do caso dizem o mesmo.
 *
 * ## Uma decisão registada cujo efeito falhou
 *
 * A decisão fica registada **antes** dos efeitos (a fase do onboarding, o
 * screening, o aviso ao dono). Se um deles falha, o serviço levanta
 * `EfeitoPorAplicarError`; a rota marca o caso no *job* da fila
 * (`efeitoFalhou`), que o reaplica na volta seguinte, e responde **202**: a
 * decisão está feita, e repeti-la dava 409. Qualquer outro erro é um 500 e não
 * marca nada — um erro antes de a decisão existir não tem efeito a reaplicar.
 */

import { Hono, type Context } from "hono";

import {
  CAMPOS_PESSOAIS,
  CasoInexistenteError,
  DECISOES,
  ESTADOS,
  EfeitoPorAplicarError,
  PAPEIS,
  RevisaoRecusadaError,
  TIPOS_DE_CASO,
  type Auditoria,
  type CampoPessoal,
  type Decisao,
  type EstadoDoCaso,
  type MotivoDeRecusa,
  type Revisor,
  type ServicoDeRevisao,
  type TipoDeCaso,
} from "@kamba/core-ts/revisao";
import type { Logger } from "@kamba/core-ts/logger";

import {
  cabecalhoDaSessaoDaEquipa,
  cabecalhoQueApagaASessaoDaEquipa,
  cookieDaEquipa,
  cunharSessaoDaEquipa,
  lerSessaoDaEquipa,
  novaSessaoDaEquipa,
  type IdentidadeDaEquipa,
  type RevogacoesDaEquipa,
} from "./sessao.ts";

/** O que a consola usa do serviço da fila. */
export type ServicoDaConsola = Pick<
  ServicoDeRevisao,
  "listar" | "ver" | "revelar" | "urlDoDocumento" | "decidir" | "registarRecurso" | "decidirRecurso"
>;

export interface OpcoesDaEquipa {
  readonly identidade: IdentidadeDaEquipa;
  readonly servico: ServicoDaConsola;
  /** O mesmo `audit_log` do serviço: as recusas da barreira vão para lá. */
  readonly auditoria: Auditoria;
  readonly revogacoes: RevogacoesDaEquipa;
  /** O anel da `segredo_onboarding_assinatura`, com o separador da equipa. */
  readonly anelDaAssinatura: readonly (Uint8Array | null)[];
  /** O *job* da fila: o caso cujo efeito falhou fica para reaplicar. */
  readonly efeitoFalhou?: ((casoId: string) => Promise<void>) | undefined;
  readonly relogio?: (() => Date) | undefined;
  readonly log?: Logger | undefined;
}

/** O tecto do corpo de um `POST`, em octetos. A nota do revisor é o campo maior. */
export const CORPO_MAXIMO_DA_EQUIPA = 8 * 1024;

/** O tecto da nota do revisor, em caracteres. Vai cifrada e nunca ao dono. */
export const NOTA_MAXIMA = 2000;

/** O tecto da página pedida. Acima, é um varrimento, e não uma consulta. */
export const PAGINA_MAXIMA_PEDIDA = 10_000;

const UUID = /^[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}$/;
const REGRA = /^[a-z0-9_.:-]{1,64}$/;

const CABECALHOS = {
  "content-type": "application/json; charset=utf-8",
  "cache-control": "no-store",
  "referrer-policy": "no-referrer",
  "x-content-type-options": "nosniff",
} as const;

function json(corpo: unknown, estado: number, extra: Record<string, string> = {}): Response {
  return new Response(JSON.stringify(corpo), { status: estado, headers: { ...CABECALHOS, ...extra } });
}

/** O pedido diz `application/json`? É a barreira de CSRF de todos os `POST`. */
function eJson(c: Context): boolean {
  return (c.req.header("content-type") ?? "").toLowerCase().startsWith("application/json");
}

/** O resultado da barreira: o revisor, ou a resposta que o recusa. */
type Barreira = { readonly revisor: Revisor } | { readonly resposta: Response };

/** Monta as rotas da consola. */
export function rotasDaEquipa(opcoes: OpcoesDaEquipa): Hono {
  const app = new Hono();
  const relogio = opcoes.relogio ?? ((): Date => new Date());
  const { servico, log } = opcoes;

  async function recusarNaBarreira(actorId: string, motivo: MotivoDeRecusa): Promise<Response> {
    await opcoes.auditoria.gravar({
      accao: "review.recusa",
      tenantId: null,
      actorId,
      entidade: "review_case",
      entidadeId: "consola",
      detalhe: motivo,
    });
    log?.info({ outcome: "equipa_recusada", error_code: motivo });
    return json({ erro: motivo }, 403);
  }

  /** A barreira inteira: sessão, revogação, conta, MFA e papel. Ver a nota do módulo. */
  async function barreira(c: Context): Promise<Barreira> {
    const s = lerSessaoDaEquipa(cookieDaEquipa(c.req.header("cookie")), opcoes.anelDaAssinatura, relogio());
    const conta = s === null || (await opcoes.revogacoes.revogada(s.sid)) ? null : await opcoes.identidade.conta(s.conta);
    if (s === null || conta === null || conta.id.toLowerCase() !== s.conta) {
      log?.info({ outcome: "equipa_recusada", error_code: "sem_sessao" });
      return { resposta: json({ erro: "sessao" }, 401) };
    }
    if (!s.mfa) return { resposta: await recusarNaBarreira(s.conta, "sem_mfa") };
    if (!conta.papeis.some((p) => (PAPEIS as readonly string[]).includes(p))) {
      return { resposta: await recusarNaBarreira(s.conta, "sem_papel") };
    }
    return { revisor: { ...conta, id: s.conta, mfa: true } };
  }

  /** O corpo JSON de um `POST`, ou `null` se não tem forma. O tipo já foi exigido pelo `comRevisor`. */
  async function corpoDe(c: Context): Promise<Record<string, unknown> | null> {
    const bruto = await c.req.text();
    if (Buffer.byteLength(bruto, "utf8") > CORPO_MAXIMO_DA_EQUIPA) return null;
    try {
      const lido: unknown = JSON.parse(bruto);
      return typeof lido === "object" && lido !== null && !Array.isArray(lido) ? (lido as Record<string, unknown>) : null;
    } catch {
      return null;
    }
  }

  /**
   * As opções de uma decisão, validadas. `null` se alguma não tem forma — e um
   * `motivo_publico` não tem: o motivo é o do caso (ver a nota do módulo).
   */
  function opcoesDaDecisao(corpo: Record<string, unknown>): { regra: string | null; nota: string | null } | null {
    const { regra, nota } = corpo;
    if ("motivo_publico" in corpo) return null;
    if (regra !== undefined && regra !== null && (typeof regra !== "string" || !REGRA.test(regra))) return null;
    if (nota !== undefined && nota !== null && (typeof nota !== "string" || nota.length > NOTA_MAXIMA)) return null;
    return { regra: typeof regra === "string" ? regra : null, nota: typeof nota === "string" ? nota : null };
  }

  /** Corre uma operação do serviço com a barreira à frente e as recusas traduzidas. */
  async function comRevisor(c: Context, operacao: (revisor: Revisor, casoId: string) => Promise<Response>): Promise<Response> {
    const b = await barreira(c);
    if ("resposta" in b) return b.resposta;
    if (c.req.method === "POST" && !eJson(c)) return json({ erro: "tipo_de_conteudo" }, 415);
    const casoId = c.req.param("id") ?? "";
    if (casoId !== "" && !UUID.test(casoId)) return json({ erro: "caso" }, 404);
    try {
      return await operacao(b.revisor, casoId);
    } catch (erro) {
      if (erro instanceof RevisaoRecusadaError) {
        log?.info({ outcome: "equipa_recusada", error_code: erro.motivo });
        return json({ erro: erro.motivo }, erro.estadoHttp);
      }
      if (erro instanceof CasoInexistenteError) return json({ erro: "caso" }, 404);
      if (erro instanceof EfeitoPorAplicarError) {
        await opcoes.efeitoFalhou?.(erro.casoId);
        log?.info({ outcome: "equipa_efeito_por_aplicar" });
        return json({ estado: "efeito_por_aplicar", caso: { id: erro.casoId } }, 202);
      }
      throw erro;
    }
  }

  app.get("/equipa/entrar", async (c) => {
    const prova = c.req.query("prova") ?? "";
    const a = prova.length === 0 || prova.length > 2048 ? null : await opcoes.identidade.autenticar(prova);
    const chave = opcoes.anelDaAssinatura[0];
    if (a === null || !UUID.test(a.id.toLowerCase()) || !(chave instanceof Uint8Array)) {
      log?.info({ outcome: "equipa_recusada", error_code: "sem_sessao" });
      return json({ erro: "sessao" }, 401);
    }
    if (!a.mfa) return recusarNaBarreira(a.id.toLowerCase(), "sem_mfa");
    const conta = await opcoes.identidade.conta(a.id);
    if (conta === null || conta.id.toLowerCase() !== a.id.toLowerCase()) return json({ erro: "sessao" }, 401);
    if (!conta.papeis.some((p) => (PAPEIS as readonly string[]).includes(p))) {
      return recusarNaBarreira(a.id.toLowerCase(), "sem_papel");
    }
    const s = novaSessaoDaEquipa(a, relogio());
    log?.info({ outcome: "equipa_sessao_aberta" });
    return new Response(null, {
      status: 303,
      headers: { location: "/equipa/casos", "cache-control": "no-store", "set-cookie": cabecalhoDaSessaoDaEquipa(cunharSessaoDaEquipa(s, chave)) },
    });
  });

  app.post("/equipa/sair", async (c) => {
    if (!eJson(c)) return json({ erro: "tipo_de_conteudo" }, 415);
    // Só a sessão **verificada** se revoga: um `sid` alheio num valor forjado
    // não desliga outra pessoa.
    const s = lerSessaoDaEquipa(cookieDaEquipa(c.req.header("cookie")), opcoes.anelDaAssinatura, relogio());
    if (s !== null) await opcoes.revogacoes.revogar(s.sid);
    log?.info({ outcome: "equipa_sessao_revogada" });
    return json({ ok: true }, 200, { "set-cookie": cabecalhoQueApagaASessaoDaEquipa() });
  });

  app.get("/equipa/casos", (c) =>
    comRevisor(c, async (revisor) => {
      const tipo = c.req.query("tipo");
      const estado = c.req.query("estado");
      const paginaT = c.req.query("pagina") ?? "0";
      if (tipo !== undefined && !(TIPOS_DE_CASO as readonly string[]).includes(tipo)) return json({ erro: "tipo" }, 400);
      if (estado !== undefined && !(ESTADOS as readonly string[]).includes(estado)) return json({ erro: "estado" }, 400);
      if (!/^[0-9]{1,5}$/.test(paginaT) || Number(paginaT) > PAGINA_MAXIMA_PEDIDA) return json({ erro: "pagina" }, 400);
      const filtro = {
        ...(tipo === undefined ? {} : { tipo: tipo as TipoDeCaso }),
        ...(estado === undefined ? {} : { estado: estado as EstadoDoCaso }),
      };
      const casos = await servico.listar(revisor, filtro, Number(paginaT));
      return json({ pagina: Number(paginaT), casos }, 200);
    }),
  );

  app.get("/equipa/casos/:id", (c) => comRevisor(c, async (revisor, id) => json(await servico.ver(revisor, id), 200)));

  app.post("/equipa/casos/:id/revelar", (c) =>
    comRevisor(c, async (revisor, id) => {
      const corpo = await corpoDe(c);
      const campo = corpo?.["campo"];
      if (!(CAMPOS_PESSOAIS as readonly unknown[]).includes(campo)) return json({ erro: "campo" }, 400);
      return json({ campo, valor: await servico.revelar(revisor, id, campo as CampoPessoal) }, 200);
    }),
  );

  app.get("/equipa/casos/:id/documentos/:verificacao", (c) =>
    comRevisor(c, async (revisor, id) => {
      const verificacao = c.req.param("verificacao") ?? "";
      if (!UUID.test(verificacao)) return json({ erro: "documento" }, 404);
      const url = await servico.urlDoDocumento(revisor, id, verificacao);
      // A URL vale ≤ 300 s e não fica em lado nenhum: nem em cache, nem no
      // `Referer` do pedido seguinte.
      return new Response(null, {
        status: 303,
        headers: { location: url, "cache-control": "no-store", "referrer-policy": "no-referrer" },
      });
    }),
  );

  app.post("/equipa/casos/:id/decisao", (c) =>
    comRevisor(c, async (revisor, id) => {
      const corpo = await corpoDe(c);
      const decisao = corpo?.["decisao"];
      const extra = corpo === null ? null : opcoesDaDecisao(corpo);
      if (!(DECISOES as readonly unknown[]).includes(decisao) || extra === null) return json({ erro: "corpo" }, 400);
      const r = await servico.decidir(revisor, id, decisao as Decisao, extra);
      return json({ estado: r.estado, caso: { id: r.caso.id, estado: r.caso.estado } }, 200);
    }),
  );

  app.post("/equipa/casos/:id/recurso", (c) =>
    comRevisor(c, async (revisor, id) => {
      const caso = await servico.registarRecurso(revisor, id);
      return json({ caso: { id: caso.id, estado: caso.estado, slaDueAt: caso.slaDueAt } }, 200);
    }),
  );

  app.post("/equipa/casos/:id/recurso/decisao", (c) =>
    comRevisor(c, async (revisor, id) => {
      const corpo = await corpoDe(c);
      const decisao = corpo?.["decisao"];
      const extra = corpo === null ? null : opcoesDaDecisao(corpo);
      if ((decisao !== "aprovar" && decisao !== "rejeitar") || extra === null) return json({ erro: "corpo" }, 400);
      const r = await servico.decidirRecurso(revisor, id, decisao, extra);
      return json({ estado: r.estado, caso: { id: r.caso.id, estado: r.caso.estado } }, 200);
    }),
  );

  return app;
}
