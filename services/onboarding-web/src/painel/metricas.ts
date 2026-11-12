/**
 * As métricas do painel do dono (KAM-099, DoD: «métricas de uso do painel e
 * erros nascem com o código», ADR-018).
 *
 * ```text
 * painel_pedidos_total{rota}         counter  pedidos que chegaram a uma rota
 * painel_erros_total{rota,motivo}    counter  pedidos que não acabaram em 2xx/3xx
 * ```
 *
 * **Duas etiquetas, os dois domínios fechados**, e nenhuma leva tenant, `sku`,
 * `orderId` ou contacto (`OBS-I`): `rota` tem sete valores e `motivo` seis, pelo
 * que o tecto é de 7 + 42 séries. As séries aparecem sempre, mesmo a zero — um
 * painel que mostre «sem dados» não distingue «ninguém errou» de «o processo
 * não arrancou».
 *
 * **Declaradas e não servidas**: o `onboarding-web` não tem rota `/metrics`, e
 * abri-la é uma superfície HTTP nova com o seu caso no *gate* 6. A exposição
 * está pronta (`exposicao()`) para o ticket que lha der — o mesmo estado em que
 * o KAM-042 deixou as do repo-base do COM, até o KAM-178 as servir.
 *
 * shortcut: as séries vivem em memória e nenhum endpoint as lê; revê-se quando
 * o onboarding-web ganhar a rota /metrics (credor no bloco do KAM-099).
 */

export const METRICA_PEDIDOS = "painel_pedidos_total";
export const METRICA_ERROS = "painel_erros_total";

/** As rotas do painel, como etiqueta. Lista fechada. */
export const ROTAS_DO_PAINEL = ["entrar", "produtos", "gravar", "encomendas", "encomenda", "canal", "sair"] as const;
export type RotaDoPainel = (typeof ROTAS_DO_PAINEL)[number];

/** Os motivos de erro, como etiqueta. Lista fechada. */
export const MOTIVOS_DE_ERRO = ["sem_sessao", "nao_encontrado", "invalido", "conflito", "confirmacao", "indisponivel"] as const;
export type MotivoDeErro = (typeof MOTIVOS_DE_ERRO)[number];

/** O `Content-Type` do formato de exposição. */
export const TIPO_DE_CONTEUDO = "text/plain; version=0.0.4; charset=utf-8";

const AJUDA: Readonly<Record<string, readonly [string, string]>> = {
  painel_pedidos_total: ["counter", "Pedidos que chegaram a uma rota do painel do dono."],
  painel_erros_total: ["counter", "Pedidos do painel do dono que nao acabaram em sucesso, por motivo."],
};

export class MetricasDoPainel {
  readonly #pedidos = new Map<RotaDoPainel, number>(ROTAS_DO_PAINEL.map((r) => [r, 0]));
  readonly #erros = new Map<string, number>();

  constructor() {
    for (const r of ROTAS_DO_PAINEL) for (const m of MOTIVOS_DE_ERRO) this.#erros.set(`${r}|${m}`, 0);
  }

  pedido(rota: RotaDoPainel): void {
    this.#pedidos.set(rota, (this.#pedidos.get(rota) ?? 0) + 1);
  }

  erro(rota: RotaDoPainel, motivo: MotivoDeErro): void {
    const chave = `${rota}|${motivo}`;
    this.#erros.set(chave, (this.#erros.get(chave) ?? 0) + 1);
  }

  /** O valor de uma série. Para as baterias. */
  valor(rota: RotaDoPainel, motivo?: MotivoDeErro): number {
    return motivo === undefined ? (this.#pedidos.get(rota) ?? 0) : (this.#erros.get(`${rota}|${motivo}`) ?? 0);
  }

  /** O formato de exposição do Prometheus. */
  exposicao(): string {
    const linhas: string[] = [];
    for (const [nome, [tipo, ajuda]] of Object.entries(AJUDA)) {
      linhas.push(`# HELP ${nome} ${ajuda}`, `# TYPE ${nome} ${tipo}`);
      if (nome === METRICA_PEDIDOS) {
        for (const [rota, n] of this.#pedidos) linhas.push(`${nome}{rota="${rota}"} ${n}`);
      } else {
        for (const [chave, n] of this.#erros) {
          const [rota, motivo] = chave.split("|");
          linhas.push(`${nome}{rota="${rota}",motivo="${motivo}"} ${n}`);
        }
      }
    }
    return `${linhas.join("\n")}\n`;
  }
}
