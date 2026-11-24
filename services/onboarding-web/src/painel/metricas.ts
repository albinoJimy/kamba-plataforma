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
 * `orderId`, telefone ou contacto (`OBS-I`): `rota` tem vinte e um valores e `motivo`
 * sete, pelo que o tecto é de 21 + 147 séries. As séries aparecem sempre, mesmo a
 * zero — um painel que mostre «sem dados» não distingue «ninguém errou» de «o
 * processo não arrancou».
 *
 * **Servidas pelo `GET /metrics` do `onboarding-web`** desde o KAM-190 (ver o
 * `../app.ts`), que o Prometheus raspa na 3003. As três rotas da reentrada e da
 * reconexão (`codigo`, `verificar`, `ligar`) e o motivo `limite` entram com elas.
 */

export const METRICA_PEDIDOS = "painel_pedidos_total";
export const METRICA_ERROS = "painel_erros_total";

/** As rotas do painel, como etiqueta. Lista fechada. */
export const ROTAS_DO_PAINEL = [
  "entrar",
  "produtos",
  "gravar",
  "encomendas",
  "encomenda",
  "canal",
  "sair",
  "codigo",
  "verificar",
  "ligar",
  // KAM-211: a troca de telefone do dono.
  "troca",
  "troca_verificar",
  // KAM-207: a ponte do `/painel/ligar` pedida por um caso activo cujo canal
  // caiu. Os pedidos dessa rota repartem-se entre `ligar` e `religar`.
  "religar",
  // KAM-223: a troca com prova de posse (o estado, a conclusão depois das
  // 72 h e o cancelamento) e a conversa do dono com o Assistente.
  "troca_estado",
  "troca_concluir",
  "troca_cancelar",
  "conversa",
  "conversa_enviar",
  // KAM-202: o início do teste ponta a ponta.
  "teste",
  // KAM-206: a página de um produto, com o formulário que saiu da lista, e o
  // pedido do contacto de uma encomenda.
  "produto",
  "contacto",
  // KAM-243: a foto do dono para o catálogo.
  "foto",
  // KAM-246: a página Social e a ligação de descarga.
  "social",
  "social_descarga",
] as const;
export type RotaDoPainel = (typeof ROTAS_DO_PAINEL)[number];

/** Os motivos de erro, como etiqueta. Lista fechada. */
export const MOTIVOS_DE_ERRO = [
  "sem_sessao",
  "nao_encontrado",
  "invalido",
  "conflito",
  "confirmacao",
  "indisponivel",
  "limite",
] as const;
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
