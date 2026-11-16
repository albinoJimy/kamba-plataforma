/**
 * Os duplos em memória da lista de espera (KAM-095).
 *
 * São o que CI e `dev` usam no `onboarding-web`, pela razão do
 * `../guia/memoria.ts`: o processo da página corre sobre repositórios em
 * memória e recusa `prod`. O adaptador SQL está em `./sql.ts` e é medido
 * contra o PostgreSQL em `db/tests/test_lista_espera_schema.py`.
 *
 * ## O duplo faz a pergunta difícil
 *
 * **A transacção é exclusiva de verdade**: uma cadeia de promessas serializa
 * as `emTransaccao`, como o `LOCK TABLE` serializa na base. Sem isto, o ensaio
 * «20 a pedir 1 vaga ⇒ 1 convite» passava pelo `await` entre a leitura da vaga
 * e a escrita — ou falhava por ele —, e mediria o duplo e não o serviço.
 *
 * **O `inserir` lê a fase do caso**, e não a aceita de quem chama: é a regra
 * que, na base, o *trigger* `waitlist_entry_do_caso` impõe.
 */

import type { Fase, RepositorioDeCasos } from "../inscricao/contrato.ts";
import {
  type AvisoDaLista,
  type Campos,
  type Entrada,
  ESTADOS_DA_ENTRADA,
  type EstadoDaEntrada,
  FASES_ELEGIVEIS,
  type Fotografia,
  LIMITE_SEM_CONFIRMACAO,
  type Limite,
  type OperacoesDaLista,
  type RepositorioDaLista,
} from "./contrato.ts";

type Relogio = () => Date;

/** A linha guardada: a `Entrada` mais o *hash* do convite. */
interface Linha extends Entrada {
  readonly conviteHash: string | null;
}

/** O limite por omissão: o 10 CONFIRMADO no `E1` §3. */
export const LIMITE_POR_OMISSAO: Limite = {
  maximo: LIMITE_SEM_CONFIRMACAO,
  origem: "confirmado",
  fundamento: "E1 §3: 10 clientes novos por 7 dias sem verificacao completa",
};

/** O repositório da lista, em memória. */
export class ListaEmMemoria implements RepositorioDaLista {
  readonly #linhas = new Map<string, Linha>();
  readonly #casos: Pick<RepositorioDeCasos, "porId" | "marcarFase">;
  readonly #relogio: Relogio;
  #fila: Promise<unknown> = Promise.resolve();
  /** O limite em vigor. Mudá-lo é o «sem *deploy*» do critério 3. */
  limite: Limite;

  constructor(casos: Pick<RepositorioDeCasos, "porId" | "marcarFase">, relogio: Relogio = () => new Date(), limite: Limite = LIMITE_POR_OMISSAO) {
    this.#casos = casos;
    this.#relogio = relogio;
    this.limite = limite;
  }

  /** Para os ensaios: a linha guardada, com o *hash*. */
  linha(onboardingId: string): Linha | null {
    return this.#linhas.get(onboardingId) ?? null;
  }

  /** Para os ensaios: quantas linhas há. */
  get tamanho(): number {
    return this.#linhas.size;
  }

  #operacoes(): OperacoesDaLista {
    const linhas = this.#linhas;
    const ordem = (a: Linha, b: Linha): number =>
      a.naFilaDesde.getTime() - b.naFilaDesde.getTime() || (a.onboardingId < b.onboardingId ? -1 : a.onboardingId > b.onboardingId ? 1 : 0);
    const aguardando = (): Linha[] => [...linhas.values()].filter((l) => l.estado === "aguardando").sort(ordem);
    const semHash = (l: Linha | undefined): Entrada | null => {
      if (l === undefined) return null;
      const { conviteHash: _, ...e } = l;
      return e;
    };
    return {
      limite: async () => this.limite,
      entrada: async (id) => semHash(linhas.get(id)),
      inserir: async (id) => {
        if (linhas.has(id)) return null;
        const caso = await this.#casos.porId(id);
        if (caso === null || !(FASES_ELEGIVEIS as readonly Fase[]).includes(caso.fase)) return null;
        const agora = this.#relogio();
        const nova: Linha = {
          onboardingId: id,
          estado: "aguardando",
          aprovadoEm: agora,
          naFilaDesde: agora,
          convidadoEm: null,
          conviteExpiraEm: null,
          tentativas: 0,
          concluidoEm: null,
          criadoEm: agora,
          conviteHash: null,
        };
        linhas.set(id, nova);
        return semHash(nova);
      },
      ocupadas: async (desde, agora) =>
        [...linhas.values()].filter(
          (l) =>
            (l.estado === "concluido" && l.concluidoEm !== null && l.concluidoEm > desde) ||
            (l.estado === "convidado" && l.conviteExpiraEm !== null && l.conviteExpiraEm > agora),
        ).length,
      elegivel: async (id) => {
        const caso = await this.#casos.porId(id);
        return caso !== null && (FASES_ELEGIVEIS as readonly Fase[]).includes(caso.fase);
      },
      aFrente: async (id) => {
        const eu = linhas.get(id);
        if (eu === undefined) return 0;
        return aguardando().filter((l) => ordem(l, eu) < 0).length;
      },
      cabeca: async () => semHash(aguardando()[0]),
      transitar: async (id, de, para, campos: Campos) => {
        const l = linhas.get(id);
        if (l === undefined || l.estado !== de) return false;
        // A mesma derivação do `SQL_TRANSITAR`: o convite só fica em
        // `convidado`, o `concluidoEm` só em `concluido`, e o resto mantém-se
        // quando não vem.
        linhas.set(id, {
          ...l,
          estado: para,
          naFilaDesde: campos.naFilaDesde ?? l.naFilaDesde,
          convidadoEm: campos.convidadoEm ?? l.convidadoEm,
          tentativas: campos.tentativas ?? l.tentativas,
          conviteHash: para === "convidado" ? (campos.conviteHash ?? null) : null,
          conviteExpiraEm: para === "convidado" ? (campos.conviteExpiraEm ?? null) : null,
          concluidoEm: para === "concluido" ? (campos.concluidoEm ?? null) : null,
        });
        return true;
      },
      porConvite: async (hash) => semHash([...linhas.values()].find((l) => l.conviteHash === hash)),
      vencidos: async (agora) =>
        [...linhas.values()]
          .filter((l) => l.estado === "convidado" && l.conviteExpiraEm !== null && l.conviteExpiraEm <= agora)
          .map((l) => l.onboardingId),
      abandonarCaso: async (id) => {
        const caso = await this.#casos.porId(id);
        if (caso !== null && (FASES_ELEGIVEIS as readonly Fase[]).includes(caso.fase)) {
          await this.#casos.marcarFase(id, "abandonado");
        }
      },
    };
  }

  async emTransaccao<T>(fazer: (operacoes: OperacoesDaLista) => Promise<T>): Promise<T> {
    // Uma cópia das linhas para desfazer: uma excepção a meio não deixa meia
    // transacção escrita, como na base.
    const executar = async (): Promise<T> => {
      const antes = new Map(this.#linhas);
      try {
        return await fazer(this.#operacoes());
      } catch (erro) {
        this.#linhas.clear();
        for (const [k, v] of antes) this.#linhas.set(k, v);
        throw erro;
      }
    };
    const vez = this.#fila.then(executar, executar);
    this.#fila = vez.catch(() => undefined);
    return vez;
  }

  async fotografia(desde: Date): Promise<Fotografia> {
    const porEstado = Object.fromEntries(ESTADOS_DA_ENTRADA.map((e) => [e, 0])) as Record<EstadoDaEntrada, number>;
    const concluidos: Linha[] = [];
    for (const l of this.#linhas.values()) {
      porEstado[l.estado] += 1;
      if (l.estado === "concluido" && l.concluidoEm !== null && l.concluidoEm > desde) concluidos.push(l);
    }
    concluidos.sort((a, b) => (a.concluidoEm?.getTime() ?? 0) - (b.concluidoEm?.getTime() ?? 0));
    const esperas = concluidos.map(
      (l) => ((l.concluidoEm?.getTime() ?? 0) - Math.max(l.criadoEm.getTime(), l.naFilaDesde.getTime())) / 1000,
    );
    return {
      porEstado,
      concluidosNaJanela: concluidos.map((l) => l.concluidoEm ?? desde),
      esperaMediaSegundos: esperas.length === 0 ? null : esperas.reduce((a, b) => a + b, 0) / esperas.length,
      limite: this.limite,
    };
  }
}

/**
 * O fornecedor falso dos avisos: guarda o que se mandou. Um `falhar` posto a
 * `true` faz o próximo aviso lançar, para medir a devolução do convite.
 */
export class AvisosDaListaEmMemoria implements AvisoDaLista {
  readonly enviados: { readonly onboardingId: string; readonly ligacao: string; readonly expiraEm: Date }[] = [];
  falhar = false;

  async convidar(onboardingId: string, ligacao: string, expiraEm: Date): Promise<void> {
    if (this.falhar) {
      this.falhar = false;
      throw new Error("fornecedor de SMS em baixo");
    }
    this.enviados.push({ onboardingId, ligacao, expiraEm });
  }
}
