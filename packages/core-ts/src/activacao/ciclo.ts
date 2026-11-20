/**
 * O ciclo da activação no processo de lote (KAM-202, critério 2).
 *
 * ```text
 * uma volta   lê os casos em `aguarda_catalogo` e em `aguarda_teste` com uma
 *             tentativa por fechar ou fechada `ok`, e corre cada um:
 *
 *               aguarda_catalogo   Activacao.fecharCatalogo: conta, grava o
 *                                  gate `catalogo_minimo` e, cumprido, avança
 *               aguarda_teste      SmokeOwnerAssisted.verify e, com o teste
 *                                  `ok`, Activacao.activar
 * ```
 *
 * ## Dois papéis, como o `./sql.ts` pede
 *
 * As leituras do catálogo, da categoria e das decisões de screening correm pela
 * ligação da aplicação, sob o `app.tenant_id` do caso: o `kamba_batch` não lê a
 * `catalog_ingestions`. Cada leitura é uma transacção curta, porque não escreve
 * nada e não precisa de ver as escritas do lote.
 *
 * Os gates, a máquina, o fecho da tentativa e a marca `is_test` correm como
 * `kamba_batch`, **numa transacção por caso** e sob o `app.tenant_id` dele (o
 * `advance_case` recusa fora do contexto do tenant do caso). Uma só, e não uma
 * por instrução, pela razão do `verify`: fechar a tentativa e gravar o gate
 * `e2e` são um facto. Fechada sem o gate, a tentativa já não estava pendente na
 * volta seguinte, o `verify` respondia `ok` sem o gravar, e o `activar` recusava
 * para sempre com `teste_por_fazer`.
 *
 * **A fila é a excepção, e é dita.** O `review_case` abre-o o serviço da fila do
 * KAM-089 (`filaDoTeste`), com as ligações dele. Se a transacção do caso falhar
 * depois de o caso estar aberto, a volta seguinte repete o `verify` e a
 * abertura: o `review_case_abertura_uq` desempata, e o `filaDoTeste` encadeia
 * sobre um caso já decidido.
 *
 * ## Um caso que falha não pára os outros
 *
 * Como no `CicloDoOffboarding`: cada caso tem o seu `try`, e o resultado diz o
 * que falhou **pelo passo**, nunca pelo caso nem pelo tenant (`OBS-I`). Uma
 * recusa da activação (`ActivacaoRecusadaError`: um gate de outro ticket ainda
 * vermelho) não é falha: conta-se à parte, e a volta seguinte tenta outra vez.
 *
 * ## O que este ciclo não faz
 *
 * Não escreve na oferta: publicar, retirar e renomear são do COM. O
 * `CatalogoMinimo` monta-se com um catálogo que só lê e um escritor de decisões
 * que recusa — a contagem não faz `screen` (ver o `contar`).
 */

import { politicaCorrente, LeitorSql, type PoliticaCompilada } from "../screening/index.ts";
import type { ConjuntoSql } from "../revisao/sql.ts";
import { comTenant } from "../tenant_guard/index.ts";
import { CatalogoMinimo } from "./catalogo_minimo.ts";
import {
  ActivacaoRecusadaError,
  type CatalogoDoTenant,
  type FilaDoTeste,
  type MaquinaDoCaso,
  type ObservadorDoTeste,
} from "./contrato.ts";
import { Activacao } from "./gates.ts";
import { SmokeOwnerAssisted } from "./smoke.ts";
import {
  CatalogoSql,
  CategoriaSql,
  GatesSql,
  MaquinaSql,
  MarcadorSql,
  RegistoDoTesteSql,
} from "./sql.ts";
import type { ClienteSql } from "../screening/sql.ts";

/** Uma volta por minuto: a janela do teste é de 60 s (*proposta*), e o dono espera pela resposta. */
export const INTERVALO_DA_ACTIVACAO_POR_OMISSAO_MS = 60_000;

/**
 * Os casos que esta volta corre. Em `aguarda_teste`, só os que têm uma tentativa
 * e cuja última não falhou: uma falhada espera que o dono recomece, e sem
 * tentativa não há nada a verificar. A última `ok` fica na lista até o caso sair
 * de `aguarda_teste`: é a que activa quando o último gate de outro ticket ficar
 * verde.
 *
 * **Como `kamba_batch`, sem contexto de tenant** (`comBatch`), que é a leitura
 * transversal que a política do lote dá. *shortcut:* sem `LIMIT`, como a
 * listagem do off-boarding — os casos nestas duas fases são os que estão a ser
 * activados agora, e uma volta corre-os todos; revê-se quando um piloto medir
 * mais de umas dezenas ao mesmo tempo.
 */
export const SQL_CASOS_DA_ACTIVACAO = `
SELECT c.id::text AS onboarding_id, c.tenant_id::text AS tenant_id, c.fase
  FROM platform.onboarding_case c
 WHERE c.fase = 'aguarda_catalogo'
    OR (c.fase = 'aguarda_teste'
        AND (SELECT s.resultado FROM platform.onboarding_smoke s
              WHERE s.onboarding_id = c.id
              ORDER BY s.iniciada_em DESC, s.id DESC LIMIT 1) IN ('pendente', 'ok'))
 ORDER BY c.id`;

/** Os passos de uma volta, pelo nome. São os valores do `falhas` do resultado. */
export const PASSOS_DA_ACTIVACAO = ["listagem", "catalogo", "teste", "activacao"] as const;
export type PassoDaActivacao = (typeof PASSOS_DA_ACTIVACAO)[number];

export interface OpcoesDoCicloDaActivacao {
  /** O conjunto de ligações do `kamba_batch`. */
  readonly lote: ConjuntoSql;
  /** O conjunto de ligações do `kamba_app`. */
  readonly app: ConjuntoSql;
  /** O observador do teste, sobre a ligação do lote do caso. */
  readonly observador: (lote: ClienteSql) => ObservadorDoTeste;
  /** A fila do teste falhado, com a máquina do caso: o `filaDoTeste` sobre o serviço da fila. */
  readonly fila: (maquina: MaquinaDoCaso) => FilaDoTeste;
  readonly politica?: PoliticaCompilada;
  readonly relogio?: () => Date;
  /** O catálogo mínimo. `CATALOGO_MINIMO` por omissão. */
  readonly minimo?: number;
}

export interface ResultadoDoCicloDaActivacao {
  /** Casos que saíram de `aguarda_catalogo` nesta volta. */
  readonly catalogos: number;
  /** Testes que fecharam `ok` nesta volta, ou que já estavam `ok`. */
  readonly testes: number;
  /** Casos activados nesta volta. */
  readonly activados: number;
  /** Activações recusadas por um gate em falta: não são falhas, e repetem-se. */
  readonly recusadas: number;
  /** Os passos que falharam, pelo nome, sem repetição. */
  readonly falhas: readonly PassoDaActivacao[];
}

/** O catálogo do lote: lê pela aplicação, e não escreve (as escritas são do COM). */
class CatalogoQueSoLe implements CatalogoDoTenant {
  readonly #sql: CatalogoSql;

  constructor(cliente: ClienteSql) {
    this.#sql = new CatalogoSql(cliente);
  }

  produtos(tenantId: string) {
    return this.#sql.produtos(tenantId);
  }

  async publicar(): Promise<boolean> {
    throw new Error("o lote nao publica ofertas: e do COM");
  }

  async retirar(): Promise<boolean> {
    throw new Error("o lote nao retira ofertas: e do COM");
  }

  async renomear(): Promise<boolean> {
    throw new Error("o lote nao renomeia ofertas: e do COM");
  }
}

/**
 * Um cliente que corre cada consulta numa transacção curta da aplicação, sob o
 * `app.tenant_id` dado. Só para leituras: duas consultas não se vêem uma à outra
 * dentro de uma transacção.
 */
function leituraDaApp(app: ConjuntoSql, tenantId: string): ClienteSql {
  return {
    async query<T = Record<string, unknown>>(texto: string, valores?: readonly unknown[]) {
      const ligacao = await app.connect();
      let estragada: Error | undefined;
      try {
        return await comTenant(ligacao, tenantId, () => ligacao.query<T>(texto, valores));
      } catch (erro) {
        estragada = erro instanceof Error ? erro : new Error("leitura da activacao falhou");
        throw erro;
      } finally {
        ligacao.release(estragada);
      }
    },
  };
}

export class CicloDaActivacao {
  readonly #o: OpcoesDoCicloDaActivacao;
  readonly #politica: PoliticaCompilada;
  #aCorrer: Promise<ResultadoDoCicloDaActivacao> | null = null;

  constructor(o: OpcoesDoCicloDaActivacao) {
    this.#o = o;
    this.#politica = o.politica ?? politicaCorrente();
  }

  /** Uma volta. Duas pedidas ao mesmo tempo são uma. */
  correr(): Promise<ResultadoDoCicloDaActivacao> {
    if (this.#aCorrer !== null) return this.#aCorrer;
    this.#aCorrer = this.#volta().finally(() => {
      this.#aCorrer = null;
    });
    return this.#aCorrer;
  }

  agendar(intervaloMs: number, aoTerminar: (r: ResultadoDoCicloDaActivacao) => void): () => void {
    if (!Number.isInteger(intervaloMs) || intervaloMs < 1_000) throw new RangeError("intervalo do ciclo abaixo de 1 s");
    const t = setInterval(() => {
      void this.correr().then(aoTerminar);
    }, intervaloMs);
    t.unref();
    return () => clearInterval(t);
  }

  async #volta(): Promise<ResultadoDoCicloDaActivacao> {
    const falhas = new Set<PassoDaActivacao>();
    const r = { catalogos: 0, testes: 0, activados: 0, recusadas: 0 };
    let casos: { onboardingId: string; tenantId: string; fase: string }[] = [];
    try {
      const { rows } = await this.#o.lote.query<{ onboarding_id: string; tenant_id: string; fase: string }>(
        SQL_CASOS_DA_ACTIVACAO,
      );
      casos = rows.map((l) => ({ onboardingId: l.onboarding_id, tenantId: l.tenant_id, fase: l.fase }));
    } catch {
      falhas.add("listagem");
    }
    for (const caso of casos) {
      let passo: PassoDaActivacao = caso.fase === "aguarda_catalogo" ? "catalogo" : "teste";
      // Os contadores só sobem depois de a transacção do caso confirmar.
      const doCaso = { catalogos: 0, testes: 0, activados: 0, recusadas: 0 };
      try {
        await this.#noCaso(caso.tenantId, async (lote) => {
          const activacao = this.#activacao(lote, caso.tenantId);
          if (caso.fase === "aguarda_catalogo") {
            const { fase } = await activacao.fecharCatalogo(caso.onboardingId);
            if (fase !== "aguarda_catalogo") doCaso.catalogos = 1;
            return;
          }
          const teste = await this.#teste(lote).verify(caso.onboardingId);
          if (!teste.ok) return;
          doCaso.testes = 1;
          passo = "activacao";
          try {
            if ((await activacao.activar(caso.onboardingId)) === "activo") doCaso.activados = 1;
          } catch (erro) {
            // Uma recusa não desfaz o teste: não se relança, para que a
            // transacção do caso confirme o que o `verify` gravou.
            if (!(erro instanceof ActivacaoRecusadaError)) throw erro;
            doCaso.recusadas = 1;
          }
        });
        r.catalogos += doCaso.catalogos;
        r.testes += doCaso.testes;
        r.activados += doCaso.activados;
        r.recusadas += doCaso.recusadas;
      } catch {
        falhas.add(passo);
      }
    }
    return { ...r, falhas: [...falhas] };
  }

  #activacao(lote: ClienteSql, tenantId: string): Activacao {
    const leitura = leituraDaApp(this.#o.app, tenantId);
    const catalogo = new CatalogoMinimo({
      catalogo: new CatalogoQueSoLe(leitura),
      categoria: new CategoriaSql(leitura),
      politica: this.#politica,
      classificador: null,
      // A contagem não grava decisões; publicar e renomear não correm aqui.
      escritor: {
        gravar: async () => {
          throw new Error("o lote nao grava decisoes de screening de produto");
        },
      },
      leitor: new LeitorSql(leitura),
      ...(this.#o.minimo === undefined ? {} : { minimo: this.#o.minimo }),
    });
    return new Activacao({ catalogo, gates: new GatesSql(lote), maquina: new MaquinaSql(lote) });
  }

  #teste(lote: ClienteSql): SmokeOwnerAssisted {
    const maquina = new MaquinaSql(lote);
    return new SmokeOwnerAssisted({
      maquina,
      registo: new RegistoDoTesteSql(lote),
      observador: this.#o.observador(lote),
      marcador: new MarcadorSql(lote),
      fila: this.#o.fila(maquina),
      gates: new GatesSql(lote),
      ...(this.#o.relogio === undefined ? {} : { relogio: this.#o.relogio }),
    });
  }

  /** Uma transacção do `kamba_batch` sob o `app.tenant_id` do caso, numa ligação dedicada. */
  async #noCaso<T>(tenantId: string, trabalho: (lote: ClienteSql) => Promise<T>): Promise<T> {
    const ligacao = await this.#o.lote.connect();
    let estragada: Error | undefined;
    try {
      return await comTenant(ligacao, tenantId, () => trabalho(ligacao));
    } catch (erro) {
      estragada = erro instanceof Error ? erro : new Error("caso da activacao falhou");
      throw erro;
    } finally {
      ligacao.release(estragada);
    }
  }
}
