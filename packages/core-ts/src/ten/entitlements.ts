/**
 * TEN — entitlements e consumo de limites (KAM-009, criterios 2 a 5 e 7).
 *
 * **Tres** perguntas, e nenhuma das tres se responde aqui dentro:
 *
 *     checkEntitlement(bd, tenant, modulo)        este tenant pode usar o modulo?
 *     consumeLimit(bd, tenant, chave, n, chaveId) cabe mais n nesta chave?
 *     checkCeiling(bd, tenant, chave, valor)      este valor cabe no tecto?
 *
 * A primeira responde-se com o `SQL_ENTITLEMENT`, cuja coluna `permitido` ja e
 * a conjuncao do criterio 2 escrita em SQL. A segunda responde-se com
 * `platform.ten_consumir`, da revisao `0007`. A terceira com o `SQL_TECTO`,
 * que le o mesmo minimo que a `ten_consumir` leria e **nao escreve nada**.
 * **Nenhuma linha deste ficheiro soma, subtrai ou compara um limite**, e isso
 * e o desenho e nao um acaso: o bloco do ticket pede o lado Python «a chamar a
 * mesma regra SQL», e duas implementacoes da mesma aritmetica de limites
 * divergem — foi o que a `0002` ja escreveu sobre a RLS.
 *
 * ## As duas perguntas nao sao a mesma, e a diferenca esta no registo
 *
 * As dez chaves de `registry/entitlement_keys.schema.json` nao sao todas da
 * mesma especie, e o registo di-lo em `x-kamba-consumivel`:
 *
 * * **baldes por periodo** (`msgs_ai_mes`, `marcacoes_mes`, …) acumulam-se e
 *   consomem-se — `consumeLimit`;
 * * **tectos por pedido** (`valor_max_pedido_minor`, `manual_max_minor`, …)
 *   nao acumulam: compara-se **um** valor com o tecto — `checkCeiling`.
 *
 * Trocar as duas nao e um pormenor: consumir um tecto por pedido cria linha em
 * `platform.tenant_usage` e, com o plano `free`, o primeiro pedido de 50 000
 * Kz gasta o tecto inteiro. Por isso a especie e **um facto do registo** e nao
 * uma convencao: `CHAVES_DE_LIMITE` tem-na por extenso, um teste confronta-a
 * com o ficheiro do registo, e cada uma das duas funcoes **levanta** se lhe
 * derem uma chave da outra especie. Um erro de programacao nao se resolve em
 * tempo de execucao escolhendo o outro caminho.
 *
 * ## Atomico e idempotente porque a funcao o e
 *
 * O criterio 3 pede que 1 000 chamadas paralelas de 1 unidade contra um limite
 * de 100 aceitem exactamente 100, e o criterio 4 que repetir a mesma
 * `idempotencyKey` nao consuma duas vezes. Nada disso se consegue em
 * JavaScript: consegue-se no `ON CONFLICT ... WHERE valor + n <= limite` e na
 * chave unica de `usage_ledger`, que serializam no lock da linha. O que este
 * modulo acrescenta e **nao estragar**: uma chamada, uma transaccao, sem
 * leitura previa e sem cache nenhuma no caminho do consumo.
 *
 * **O consumo nunca passa pela cache.** A cache e so dos entitlements; um
 * contador em cache era um contador errado, e um tecto decidido sobre um
 * contador errado deixa passar o que devia negar.
 *
 * ## O `tenant_id` vem do contexto
 *
 * As funcoes recebem o tenant como argumento, mas quem o fornece e sempre o
 * contexto de quem chama — o `ChannelContext` do CHR (`01` §7.2) ou o
 * `ToolContext` da ToolLayer (`02` §6.1) —, nunca um parametro de um cliente.
 * No caminho HTTP isso e imposto pela forma do `middleware.ts`, que nao tem
 * acesso ao corpo nem a query do pedido. Aqui o que ha e a defesa em
 * profundidade: o `normalizarTenant` do `tenant_guard` recusa o que nao seja um
 * UUID canonico, e a RLS de `platform.tenants` (`id = app.tenant_id`) faz a
 * consulta devolver zero linhas quando o contexto da transaccao e de outro
 * tenant — que este modulo le como negado.
 *
 * ## O que este modulo nao faz
 *
 * * **Nao abre transaccoes.** Recebe um cliente; quem da contexto de tenant e
 *   o `tenant_guard` (`comTenant`). Chamar `consumeLimit` dentro desse bloco e
 *   o que poe o consumo na mesma transaccao do efeito que o motivou.
 * * **Nao regista nada.** Nem o tenant, nem a chave, nem o erro: o DoD proibe
 *   associar `tenant_id` a conteudo em registos. So conta (`metricas.ts`).
 * * **Nao sabe precos.** Um limite e um inteiro vindo de `entitlements.limites`
 *   e nada aqui o interpreta como dinheiro.
 */

import { createHash } from "node:crypto";

import { normalizarTenant } from "../tenant_guard/index.ts";

import { SQL_CONSUMIR, SQL_ENTITLEMENT, SQL_PERIODO, SQL_TECTO } from "./consultas.ts";
import {
  METRICA_ENTITLEMENT_NEGADO,
  METRICA_LIMITE_NEGADO,
  METRICAS,
  type MetricasDoTen,
} from "./metricas.ts";

/** O minimo de um cliente SQL. E a forma do `pg.Client`, como no `eventos/`. */
export interface ClienteSql {
  query(
    sql: string,
    parametros?: readonly unknown[],
  ): Promise<{ rows: Record<string, unknown>[]; rowCount: number | null }>;
}

/**
 * Os codigos de erro. **Os tres estao em proposta, e de maneiras diferentes.**
 *
 * `LIMIT_EXCEEDED` e o unico escrito num documento tecnico: `docs/tecnica/02`
 * §6.5, na tabela de erros tipados da ToolLayer. **Sem estado HTTP associado** —
 * o §6.5 e sobre erros de *tool*, nao sobre uma API —, pelo que o `429` deste
 * modulo e proposta do ticket e nada mais.
 *
 * `ENTITLEMENT_DENIED` tambem esta no §6.5, e e o nome que a ToolLayer usa.
 *
 * `ENTITLEMENT_DISABLED` **nao esta em documento nenhum**: vem do criterio 2 do
 * bloco do KAM-009, que o marca «em proposta». Note-se que nao e o mesmo nome
 * que o §6.5 escreve para a mesma situacao. Os dois ficam aqui, cada um no seu
 * caminho — `ENTITLEMENT_DISABLED` no HTTP, por ser o que o criterio pede, e
 * `ENTITLEMENT_DENIED` na ToolLayer, por ser o que o documento tem —, e **a
 * decisao de os unificar devolve-se ao dono do `docs/tecnica/02` §6.5**.
 * Escolher aqui um dos dois em silencio era fechar por omissao uma divergencia
 * entre um ticket e um documento.
 */
export const CODIGO_ENTITLEMENT_HTTP = "ENTITLEMENT_DISABLED";
/** O mesmo caso, no vocabulario da ToolLayer (`docs/tecnica/02` §6.5). */
export const CODIGO_ENTITLEMENT_TOOL = "ENTITLEMENT_DENIED";
/** `docs/tecnica/02` §6.5. O unico dos tres que um documento tecnico escreve. */
export const CODIGO_LIMITE = "LIMIT_EXCEEDED";

/** Estado HTTP de cada recusa. **Proposta**: o §6.5 nao associa nenhum. */
export const HTTP_ENTITLEMENT = 403;
/** Estado HTTP de cada recusa. **Proposta**: o §6.5 nao associa nenhum. */
export const HTTP_LIMITE = 429;
/**
 * Um tecto **por pedido** que nao chega. `403` e nao `429`, e tem razao.
 *
 * Um `429` diz «tente mais tarde», e um balde mensal reabre mesmo — no
 * primeiro dia do mes seguinte. Um tecto por pedido nao reabre nunca: o mesmo
 * pedido, com o mesmo valor, sera recusado em Janeiro como foi em Dezembro, e
 * convidar a repeti-lo era mentir ao cliente e fazer-lhe gastar tentativas. O
 * **codigo** continua a ser `LIMIT_EXCEEDED`, porque e um limite e porque
 * acrescentar um quarto nome ao vocabulario do `02` §6.5 e decisao de quem o
 * detem; muda o estado, que nenhum documento fixa. **Proposta**, como os
 * outros dois.
 */
export const HTTP_TECTO = 403;

/** A gramatica de um modulo e de uma chave de limite (`CHECK` da `0001`/`0007`). */
export const NOME_CANONICO = /^[a-z][a-z0-9_]{1,62}$/;

/**
 * O `SQLSTATE` que a `0007` levanta quando a mesma `(tenant, chave_limite,
 * idempotency_key)` volta com uma **quantidade diferente** da registada.
 *
 * Nao e uma recusa de limite: e um conflito do pedido. Quem repete uma chave
 * com outra quantidade ou mudou o corpo entre tentativas ou esta a reutilizar
 * a chave para outra coisa, e as duas sao defeitos de quem chama. Mapeia-se
 * para `ConflitoDeIdempotenciaError` e **nao** para o caminho do `429`.
 */
export const SQLSTATE_CONFLITO_DE_IDEMPOTENCIA = "KA002";

/**
 * O `SQLSTATE` da `platform.ten_tecto` quando um modulo **activo** declara a
 * chave com um valor que nao e um inteiro nao negativo.
 *
 * `22023` e `invalid_parameter_value`, e **nao e so desta causa**: a `0007`
 * usa o mesmo estado na guarda de `p_agora` da `ten_consumir`. E por isso que
 * a traducao nao pode ser igual nos dois caminhos — ver `conflitoOuTecto`.
 */
export const SQLSTATE_LIMITE_ILEGIVEL = "22023";

/**
 * O que distingue as duas causas do `22023`: a mensagem da `ten_tecto` comeca
 * por `ten_tecto: a chave % tem um limite que nao e um inteiro em
 * entitlements`, e a da guarda do instante nao a nomeia.
 *
 * Ler a mensagem e fragil e sabe-se — mas a alternativa era pior: ou nao
 * traduzir nada no caminho do consumo (e entao a mesma linha corrompida dava
 * erros diferentes consoante a funcao que a encontrasse), ou traduzir tudo (e
 * entao um `p_agora` absurdo saia como «limite ilegivel», que e falso). O
 * reconhecimento falha **para o lado seguro**: se a mensagem mudar, o erro
 * original sobe inalterado e ninguem fica a saber menos do que sabia.
 */
export const MARCA_DO_TECTO_ILEGIVEL = "ten_tecto";

/** As tres especies de chave do `registry/entitlement_keys.schema.json`. */
export const CATEGORIA_CONTADOR = "contador_por_periodo";
/** As tres especies de chave do `registry/entitlement_keys.schema.json`. */
export const CATEGORIA_TECTO_POR_PEDIDO = "tecto_por_pedido";
/** As tres especies de chave do `registry/entitlement_keys.schema.json`. */
export const CATEGORIA_TECTO_POR_JANELA = "tecto_por_janela";

export type CategoriaDaChave =
  | typeof CATEGORIA_CONTADOR
  | typeof CATEGORIA_TECTO_POR_PEDIDO
  | typeof CATEGORIA_TECTO_POR_JANELA;

/** A especie de uma chave de limite, **lida do registo**. */
export interface ChaveDeLimite {
  readonly nome: string;
  readonly categoria: CategoriaDaChave;
  /** O `x-kamba-consumivel` do registo. `true` so para os contadores. */
  readonly consumivel: boolean;
}

/**
 * As dez chaves do registo, com a especie de cada uma.
 *
 * ## Porque e que isto existe
 *
 * O registo ja dizia, em `x-kamba-consumivel`, quais das dez chaves se
 * consomem — e **nada lia esse campo**. A consequencia media-se: nada impedia
 * `consumeLimit(tenant, "valor_max_pedido_minor", 5_000_000, …)`, que cria
 * linha em `platform.tenant_usage` para um tecto que nao tem contador e, com o
 * plano `free`, gasta o tecto inteiro no primeiro pedido de 50 000 Kz. Um
 * tecto por pedido pergunta «este valor cabe?»; um balde pergunta «quanto ja
 * gastei». Sao duas perguntas, e so uma delas escreve.
 *
 * ## Porque e que e uma tabela aqui e nao uma leitura do ficheiro
 *
 * Nem este pacote nem o `kamba_core.ten` fazem IO: nao abrem ficheiros e nao
 * importam controladores. Uma biblioteca que fosse ler `registry/*.json` em
 * tempo de execucao passava a depender da arvore do repositorio estar montada
 * ao lado do processo — e este pacote publica so o `dist`.
 *
 * O que mantem esta tabela honesta nao e uma promessa: e o teste que **le** o
 * `registry/entitlement_keys.schema.json` e confronta chave a chave o nome, a
 * categoria e o `x-kamba-consumivel` (dos dois lados: aqui e em
 * `TestRegistoDeChaves`). Uma chave acrescentada ao registo e nao acrescentada
 * aqui faz o teste cair, e vice-versa. E o mesmo padrao da matriz do §7.2 e do
 * SQL: escrito por extenso, confrontado por uma maquina.
 */
export const CHAVES_DE_LIMITE: Readonly<Record<string, ChaveDeLimite>> = {
  msgs_ai_mes: { nome: "msgs_ai_mes", categoria: CATEGORIA_CONTADOR, consumivel: true },
  marcacoes_mes: {
    nome: "marcacoes_mes",
    categoria: CATEGORIA_CONTADOR,
    consumivel: true,
  },
  imagens_mes: { nome: "imagens_mes", categoria: CATEGORIA_CONTADOR, consumivel: true },
  posts_mes: { nome: "posts_mes", categoria: CATEGORIA_CONTADOR, consumivel: true },
  orcamentos_mes: {
    nome: "orcamentos_mes",
    categoria: CATEGORIA_CONTADOR,
    consumivel: true,
  },
  valor_max_pedido_minor: {
    nome: "valor_max_pedido_minor",
    categoria: CATEGORIA_TECTO_POR_PEDIDO,
    consumivel: false,
  },
  manual_max_minor: {
    nome: "manual_max_minor",
    categoria: CATEGORIA_TECTO_POR_PEDIDO,
    consumivel: false,
  },
  manual_dupla_acima_minor: {
    nome: "manual_dupla_acima_minor",
    categoria: CATEGORIA_TECTO_POR_PEDIDO,
    consumivel: false,
  },
  manual_daily_max_minor: {
    nome: "manual_daily_max_minor",
    categoria: CATEGORIA_TECTO_POR_JANELA,
    consumivel: false,
  },
  manual_max_por_contacto_24h: {
    nome: "manual_max_por_contacto_24h",
    categoria: CATEGORIA_TECTO_POR_JANELA,
    consumivel: false,
  },
};

/** Porque e que o entitlement negou. Nunca e `null` quando negou. */
export type MotivoDaRecusa =
  /** Zero linhas: tenant inexistente, apagado, ou contexto de RLS de outro. */
  | "sem_tenant"
  /** Ha tenant, nao ha linha de entitlement para o modulo (KAM-091 por correr). */
  | "sem_entitlement"
  /** Ha linha, `ativo = false`. */
  | "entitlement_inactivo"
  /** `onboarding`, `suspenso` ou `encerrado`. A lista vive no SQL. */
  | "estado_do_tenant";

/** O que a base respondeu sobre um entitlement. */
export interface Entitlement {
  readonly modulo: string;
  readonly permitido: boolean;
  /** `null` quando nao ha linha de tenant. */
  readonly estadoTenant: string | null;
  readonly ativo: boolean;
  /** `null` exactamente quando `permitido`. */
  readonly motivo: MotivoDaRecusa | null;
}

/** Um nome que nao casa a gramatica de `modulo` ou de `chave_limite`. */
export class NomeInvalidoError extends Error {
  constructor(campo: string, valor: unknown) {
    super(
      `${campo} tem de casar ^[a-z][a-z0-9_]{1,62}$ (recebido: ` +
        `${typeof valor} com ${typeof valor === "string" ? valor.length : 0} caracteres)`,
    );
    this.name = "NomeInvalidoError";
  }
}

/** A quantidade a consumir nao e um inteiro positivo. */
export class QuantidadeInvalidaError extends Error {
  constructor(valor: unknown) {
    super(
      `a quantidade tem de ser um inteiro positivo, veio ${JSON.stringify(valor)}. ` +
        "A mesma recusa existe em `platform.ten_consumir`; esta poupa a ida a base.",
    );
    this.name = "QuantidadeInvalidaError";
  }
}

/** A chave de idempotencia esta vazia ou nao e texto. */
export class ChaveDeIdempotenciaInvalidaError extends Error {
  constructor() {
    super(
      "a chave de idempotencia tem de ser texto nao vazio: e ela que torna a " +
        "repeticao segura (`usage_ledger`, criterio 4). A mensagem nao repete o valor.",
    );
    this.name = "ChaveDeIdempotenciaInvalidaError";
  }
}

/** A base devolveu uma coluna com uma forma que nao se consegue ler. */
export class RespostaIlegivelError extends Error {
  constructor(coluna: string, valor: unknown) {
    super(
      `a coluna ${coluna} veio como ${typeof valor} e nao se consegue ler como ` +
        "inteiro. Um limite mal lido e um tecto errado: recusa-se em vez de adivinhar.",
    );
    this.name = "RespostaIlegivelError";
  }
}

/** A chave nao esta no `registry/entitlement_keys.schema.json`. */
export class ChaveDesconhecidaError extends Error {
  constructor(nome: string) {
    super(
      `a chave ${JSON.stringify(nome)} nao esta no registo de chaves de limite ` +
        "(`registry/entitlement_keys.schema.json`, dez chaves). O registo recusa " +
        "chaves desconhecidas na escrita; esta recusa-as na leitura.",
    );
    this.name = "ChaveDesconhecidaError";
  }
}

/**
 * Pediu-se a uma chave a pergunta da outra especie.
 *
 * Consumir um tecto por pedido, ou perguntar «cabe?» a um balde mensal. Nao se
 * resolve em tempo de execucao escolhendo o outro caminho: quem escreveu a
 * chamada acreditava numa coisa que nao e verdade, e a chamada seguinte
 * acreditaria na mesma.
 */
export class ChaveDeEspecieErradaError extends Error {
  constructor(mensagem: string) {
    super(mensagem);
    this.name = "ChaveDeEspecieErradaError";
  }
}

/**
 * A mesma chave de idempotencia voltou com **outra** quantidade.
 *
 * E o `SQLSTATE` `KA002` da revisao `0007`, traduzido. Nao e um `429`: o
 * limite pode ate ter espaco de sobra. E um conflito do pedido — dois corpos
 * diferentes com a mesma chave —, e quem o recebe corrige a chamada em vez de
 * esperar pelo mes seguinte.
 */
export class ConflitoDeIdempotenciaError extends Error {
  constructor() {
    super(
      "a mesma chave de idempotencia ja foi usada nesta chave de limite com " +
        "outra quantidade (`KA002`, revisao `0007`). Nao e o tecto: e o mesmo " +
        "pedido a dizer duas coisas. A mensagem nao repete a chave nem a quantidade.",
    );
    this.name = "ConflitoDeIdempotenciaError";
  }
}

/**
 * Um modulo activo declara a chave com um limite que nao e um inteiro.
 *
 * E o `22023` da `platform.ten_tecto`, traduzido. **Nao e «nao cabe».** Uma
 * recusa de tecto diz ao tenant que o pedido dele e grande demais, e manda-o
 * mudar de plano; isto diz que o `entitlements.limites` tem um valor
 * corrompido, e manda corrigir o provisionamento (KAM-091). Responder
 * «negado» a um dado ilegivel era transformar um defeito de dados numa
 * resposta de negocio, e a resposta estaria errada.
 *
 * Levantar tambem **nao** afrouxa a falha fechada: nada passa. O que muda e
 * quem recebe a conta.
 *
 * Nao estende `RespostaIlegivelError` de proposito: aquela e sobre a **forma**
 * do que o controlador devolveu, esta e sobre o **conteudo** do que esta
 * guardado. Quem apanha uma nao quer necessariamente apanhar a outra.
 */
export class LimiteIlegivelError extends Error {
  constructor() {
    // A mensagem **nao** repete o valor guardado: um limite e um numero de
    // negocio e nao tem de aparecer em nada que possa ser registado
    // (`OBS-I`). Quem precisa dele le a causa, que vai em `cause`.
    super(
      "um modulo activo declara esta chave com um limite que nao e um inteiro " +
        "nao negativo (`22023`, `platform.ten_tecto`). Nao e «nao cabe»: e " +
        "`entitlements.limites` com um valor que nao se le, e o caminho e o " +
        "provisionamento (KAM-091) e nao o plano do tenant.",
    );
    this.name = "LimiteIlegivelError";
  }
}

/**
 * O erro desta biblioteca para um erro de controlador, ou `null`.
 *
 * `null` quer dizer «nao reconheco», e quem chama relanca o original. Os dois
 * estados que se traduzem sao o `KA002` (conflito de idempotencia) e o `22023`
 * **da `ten_tecto`** — este ultimo so quando a mensagem o nomeia, porque a
 * `0007` usa o mesmo `22023` na guarda de `p_agora` e essa nao e a mesma coisa
 * nem de longe.
 */
export function conflitoOuTecto(erro: unknown): Error | null {
  const estado = sqlstateDe(erro);
  if (estado === SQLSTATE_CONFLITO_DE_IDEMPOTENCIA) {
    return new ConflitoDeIdempotenciaError();
  }
  if (
    estado === SQLSTATE_LIMITE_ILEGIVEL &&
    String((erro as { message?: unknown } | null)?.message ?? "").includes(
      MARCA_DO_TECTO_ILEGIVEL,
    )
  ) {
    return new LimiteIlegivelError();
  }
  return null;
}

export function exigirNome(campo: string, valor: unknown): string {
  if (typeof valor !== "string" || !NOME_CANONICO.test(valor)) {
    throw new NomeInvalidoError(campo, valor);
  }
  return valor;
}

/**
 * A especie de uma chave de limite, ou `ChaveDesconhecidaError`.
 *
 * Uma chave que nao esta no registo nao se trata como a mais parecida nem se
 * deixa passar «porque casa a gramatica»: o registo tem
 * `additionalProperties: false`, logo uma chave fora dele nunca podera estar em
 * `entitlements.limites` — e um consumo contra ela criava linha de uso para um
 * tecto que nao pode existir. Falha fechada, e com o erro no sitio onde se
 * escreveu o nome.
 */
export function especieDaChave(chave: unknown): ChaveDeLimite {
  const nome = exigirNome("chave", chave);
  const especie = Object.hasOwn(CHAVES_DE_LIMITE, nome)
    ? CHAVES_DE_LIMITE[nome]
    : undefined;
  if (especie === undefined) throw new ChaveDesconhecidaError(nome);
  return especie;
}

/** A chave tem de ser um balde por periodo. Senao, levanta. */
export function exigirConsumivel(chave: unknown): string {
  const especie = especieDaChave(chave);
  if (!especie.consumivel) {
    throw new ChaveDeEspecieErradaError(
      `${especie.nome} e ${especie.categoria} e **nao** se consome: o registo ` +
        "marca-a `x-kamba-consumivel: false`. Consumi-la criava linha em " +
        "`platform.tenant_usage` e gastava num pedido um tecto que e por pedido. " +
        "A pergunta certa e `checkCeiling`.",
    );
  }
  return especie.nome;
}

/**
 * A chave tem de ser um tecto por pedido. Senao, levanta.
 *
 * `tecto_por_janela` tambem levanta, e nao por descuido: a pergunta dessas duas
 * chaves e «a soma (ou a contagem) da janela mais este valor cabe?», e o
 * agregado da janela **nao esta em `platform.tenant_usage`** — a chave dessa
 * tabela e `(tenant_id, chave_limite, periodo)` com `periodo` mensal por
 * `CHECK`, sem dimensao de contacto e sem janela movel. Calcula-se de
 * `manual_confirmations` (`docs/tecnica/04` §4.2 M-6), que este ticket nao
 * constroi. Comparar um valor solto com um tecto diario daria «cabe» a cada
 * pedido ate ao fim do dia: e a mesma classe de defeito que o
 * `x-kamba-consumivel` existe para fechar, e por isso recusa-se em vez de se
 * inventar um caminho.
 */
export function exigirTecto(chave: unknown): string {
  const especie = especieDaChave(chave);
  if (especie.categoria === CATEGORIA_TECTO_POR_PEDIDO) return especie.nome;
  if (especie.categoria === CATEGORIA_TECTO_POR_JANELA) {
    throw new ChaveDeEspecieErradaError(
      `${especie.nome} e ${especie.categoria}: o tecto compara-se com o agregado ` +
        "da janela, que vive em `manual_confirmations` (`docs/tecnica/04` §4.2 " +
        "M-6) e nao em `platform.tenant_usage`. Nao ha caminho de aplicacao para " +
        "esta chave no KAM-009.",
    );
  }
  throw new ChaveDeEspecieErradaError(
    `${especie.nome} e ${especie.categoria}: acumula-se dentro do periodo e a ` +
      "pergunta e «quanto ja gastei», nao «este valor cabe». A pergunta certa e " +
      "`consumeLimit`, que chama `platform.ten_consumir`.",
  );
}

/**
 * O `SQLSTATE` de um erro de controlador, se o conseguir ler.
 *
 * Cada controlador o guarda a sua maneira — `code` no `pg`, `sqlstate` no
 * `psycopg` do lado Python, e o `pg8000` entrega o dicionario de campos do
 * servidor, em que o `SQLSTATE` e o `C`. Este pacote **nao importa controlador
 * nenhum**, logo nao pode apanhar a classe de excepcao de cada um: le os
 * sitios conhecidos e, se nao reconhecer nada, devolve `null` e o erro
 * original sobe inalterado. Reconhecer de menos relanca o erro certo; inventar
 * um `SQLSTATE` era que seria grave.
 */
export function sqlstateDe(erro: unknown): string | null {
  if (typeof erro !== "object" || erro === null) return null;
  const candidatos = ["sqlstate", "pgcode", "code", "C"];
  for (const campo of candidatos) {
    const valor = (erro as Record<string, unknown>)[campo];
    if (typeof valor === "string" && /^[0-9A-Z]{5}$/.test(valor)) return valor;
  }
  return null;
}

/**
 * A chave efectiva: `sha256` dos componentes, separados por `\0`.
 *
 * ## Porque e que a do cliente nao pode ser a chave inteira
 *
 * A chave de idempotencia decide o **ambito da desduplicacao**, e esse ambito e
 * do servidor. Tomada tal como vem do cabecalho `Idempotency-Key`, quem escolhe
 * o ambito e quem manda o cabecalho — e e o cliente que ganha o direito de
 * dizer que dois pedidos diferentes sao o mesmo. Aqui o que o cliente manda
 * entra como **um** componente, atras do tenant, do modulo e da chave de
 * limite, que vem todos do contexto do servidor: duas chamadas de modulos
 * diferentes com o mesmo cabecalho deixam de ser a mesma chave, e um cliente
 * deixa de poder construir a chave de outro.
 *
 * ## A quantidade **nao** entra, e isso e deliberado
 *
 * Parece o contrario do que se quer, e nao e. A revisao `0007` levanta `KA002`
 * quando a mesma `(tenant, chave_limite, idempotency_key)` volta com uma
 * quantidade diferente: e a impressao digital que apanha o cliente que repete
 * uma chave com outro corpo. Pondo a quantidade **dentro** da chave, o mesmo
 * cabecalho com outra quantidade passava a ser outra chave — um consumo novo,
 * aceite em silencio — e o `KA002` nunca disparava para quem usa esta
 * derivacao. Dos dois mecanismos so um **denuncia** o defeito; esse fica, e a
 * quantidade fica de fora para o deixar trabalhar.
 *
 * O separador e `\0`, que nem um UUID nem um nome canonico podem conter — o
 * mesmo argumento da chave da cache.
 */
export function derivarChaveDeIdempotencia(...componentes: readonly unknown[]): string {
  const partes: string[] = [];
  for (const componente of componentes) {
    if (typeof componente !== "string" || componente.trim() === "") {
      throw new ChaveDeIdempotenciaInvalidaError();
    }
    partes.push(componente);
  }
  if (partes.length === 0) throw new ChaveDeIdempotenciaInvalidaError();
  return createHash("sha256").update(partes.join("\u0000"), "utf8").digest("hex");
}

/**
 * Um `bigint` do PostgreSQL como numero de JavaScript.
 *
 * O `pg` devolve `bigint` como **texto**, para nao perder precisao acima de
 * 2^53; o `pg8000` do lado Python devolve `int`. Os dois passam por aqui com a
 * mesma regra, e o que nao seja inteiro exacto levanta em vez de ser
 * arredondado em silencio — um tecto de dinheiro arredondado e dinheiro errado
 * (`specs/01` §6, principio 4).
 */
export function inteiro(coluna: string, valor: unknown): number {
  if (typeof valor === "number" && Number.isSafeInteger(valor)) return valor;
  if (typeof valor === "bigint") {
    if (valor > BigInt(Number.MAX_SAFE_INTEGER) || valor < BigInt(Number.MIN_SAFE_INTEGER)) {
      throw new RespostaIlegivelError(coluna, valor);
    }
    return Number(valor);
  }
  if (typeof valor === "string" && /^-?\d+$/.test(valor)) {
    const lido = Number(valor);
    if (!Number.isSafeInteger(lido)) throw new RespostaIlegivelError(coluna, valor);
    return lido;
  }
  throw new RespostaIlegivelError(coluna, valor);
}

/** Um booleano do PostgreSQL. Tudo o que nao seja `true` conta como falso. */
function booleano(valor: unknown): boolean {
  return valor === true || valor === "t" || valor === "true";
}

/**
 * O entitlement de um modulo para um tenant. **Falha fechada** (criterio 2).
 *
 * Nega quando nao ha linha, quando `ativo = false` e quando o tenant esta
 * `onboarding`, `suspenso` ou `encerrado` — e a lista dos tres estados vive no
 * `SQL_ENTITLEMENT`, nao aqui, para que o Python nao possa ter outra.
 *
 * A assinatura do criterio 6 e `checkEntitlement(tenant, modulo)`; esta tem o
 * cliente a frente, como todos os modulos deste pacote que falam com a base
 * (`eventos/consumo.ts`, `identity/contactos.ts`). Quem liga e quem chama.
 *
 * Conta `ten_entitlement_denied_total{modulo}` em **cada** recusa, incluindo as
 * que vem da cache: o que o painel mostra e quantos acessos foram negados, e
 * nao quantas vezes a base foi consultada.
 */
export async function checkEntitlement(
  bd: ClienteSql,
  tenant: unknown,
  modulo: unknown,
  opcoes: { readonly cache?: CacheDeEntitlements; readonly metricas?: MetricasDoTen } = {},
): Promise<Entitlement> {
  const canonico = normalizarTenant(tenant);
  const nome = exigirNome("modulo", modulo);
  const metricas = opcoes.metricas ?? METRICAS;

  const emCache = opcoes.cache?.ler(canonico, nome);
  if (emCache !== undefined) {
    if (!emCache.permitido) metricas.contar(METRICA_ENTITLEMENT_NEGADO, nome);
    return emCache;
  }

  const { rows } = await bd.query(SQL_ENTITLEMENT, [canonico, nome]);
  const linha = rows[0];
  const decisao: Entitlement =
    linha === undefined
      ? {
          modulo: nome,
          permitido: false,
          estadoTenant: null,
          ativo: false,
          motivo: "sem_tenant",
        }
      : montar(nome, linha);

  opcoes.cache?.guardar(canonico, nome, decisao);
  if (!decisao.permitido) metricas.contar(METRICA_ENTITLEMENT_NEGADO, nome);
  return decisao;
}

/**
 * A linha da base como decisao.
 *
 * O `permitido` **vem da coluna**, e nao se recalcula: recalcular era a segunda
 * implementacao da regra. O `motivo` deriva-se, e repare-se que a unica coisa
 * que a derivacao sabe sobre estados e que, se o entitlement esta activo e
 * mesmo assim negou, so pode ter sido o estado do tenant. A lista dos tres
 * estados continua a existir num sitio so.
 */
function montar(modulo: string, linha: Record<string, unknown>): Entitlement {
  const permitido = booleano(linha.permitido);
  const ativo = booleano(linha.ativo);
  const temLinha = booleano(linha.tem_linha);
  const estadoTenant = typeof linha.estado_tenant === "string" ? linha.estado_tenant : null;
  let motivo: MotivoDaRecusa | null = null;
  if (!permitido) {
    motivo = !temLinha
      ? "sem_entitlement"
      : !ativo
        ? "entitlement_inactivo"
        : "estado_do_tenant";
  }
  return { modulo, permitido, estadoTenant, ativo, motivo };
}

/** O desfecho de um consumo, tal como `platform.ten_consumir` o devolve. */
export interface Consumo {
  /** Aceite (ou repeticao de um consumo ja aceite). */
  readonly aceite: boolean;
  /** O uso no periodo depois desta chamada. */
  readonly valor: number;
  /** Esta chamada e a repeticao de uma anterior com a mesma chave. */
  readonly repetido: boolean;
  /**
   * O tecto efectivo. **`null` quando nenhum entitlement activo declara a
   * chave** — e `null` nega, pela `0007`: «sem tecto» nao quer dizer «sem
   * limite».
   */
  readonly limite: number | null;
  /** `null` quando aceite. Senao, qual das duas recusas foi. */
  readonly motivo: "sem_entitlement" | "limite_excedido" | null;
}

/**
 * Consome `quantidade` da chave, atomica e idempotentemente.
 *
 * Uma unica chamada a `platform.ten_consumir`. Sem leitura previa: entre um
 * `SELECT` e um `INSERT` cabe a chamada repetida inteira, e e por isso que a
 * `0007` escreve a chave de idempotencia **antes** de contar.
 *
 * O `limite` opcional e o tecto de quem chama, e so **desce**: a `0007` faz
 * `least` com o do plano. Serve um tecto de confianca (`EPIC-09`) mais
 * apertado, nunca um mais largo — passar um limite alto nao abre nada.
 *
 * O `agora` opcional existe para o criterio 5: com relogio fixo em
 * `2026-11-30T23:59:59+01:00` o consumo conta para Novembro e em
 * `2026-12-01T00:00:00+01:00` para Dezembro. Quem decide isso e
 * `platform.ten_periodo`, em `Africa/Luanda`; aqui so se passa o instante.
 *
 * **So consome chaves consumiveis.** `exigirConsumivel` levanta para um tecto
 * por pedido ou por janela, antes de tocar na base: o registo diz a especie de
 * cada chave e esta funcao e so a dos baldes. Era por aqui que
 * `valor_max_pedido_minor` entrava e gastava o tecto do mes num pedido.
 *
 * Conta `ten_limit_denied_total{key}` quando o tecto recusa. Uma recusa por
 * **falta** de entitlement conta em `ten_entitlement_denied_total{modulo}`
 * apenas se quem chama passar o modulo (`opcoes.modulo`): a funcao SQL nao o
 * sabe, porque o tecto e o minimo entre os modulos que declaram a chave.
 *
 * Um `KA002` da `0007` — a mesma chave de idempotencia com outra quantidade —
 * sobe como `ConflitoDeIdempotenciaError`, e nao como recusa de limite.
 */
export async function consumeLimit(
  bd: ClienteSql,
  tenant: unknown,
  chave: unknown,
  quantidade: unknown,
  idempotencyKey: unknown,
  opcoes: {
    readonly limite?: number | null;
    readonly agora?: Date | null;
    readonly modulo?: string;
    readonly metricas?: MetricasDoTen;
  } = {},
): Promise<Consumo> {
  const canonico = normalizarTenant(tenant);
  const nome = exigirConsumivel(chave);
  if (typeof quantidade !== "number" || !Number.isSafeInteger(quantidade) || quantidade <= 0) {
    throw new QuantidadeInvalidaError(quantidade);
  }
  if (typeof idempotencyKey !== "string" || idempotencyKey.trim() === "") {
    throw new ChaveDeIdempotenciaInvalidaError();
  }
  const tecto = opcoes.limite ?? null;
  if (tecto !== null && (!Number.isSafeInteger(tecto) || tecto < 0)) {
    throw new QuantidadeInvalidaError(tecto);
  }
  const metricas = opcoes.metricas ?? METRICAS;

  // Inicializado: um `rows` por atribuir e lido mais abaixo como zero linhas,
  // e zero linhas ja e erro («um consumo que nao se sabe se aconteceu nao se
  // aceita»). Nunca acontece — o `catch` termina sempre a levantar —, mas o
  // modo seguro de nunca acontecer e o que nao depende da analise de fluxo.
  let rows: Record<string, unknown>[] = [];
  try {
    ({ rows } = await bd.query(SQL_CONSUMIR, [
      canonico,
      nome,
      quantidade,
      idempotencyKey,
      tecto,
      opcoes.agora ?? null,
    ]));
  } catch (erro) {
    const traduzido = conflitoOuTecto(erro);
    if (traduzido !== null) throw traduzido;
    throw erro;
  }
  const linha = rows[0];
  if (linha === undefined) {
    // `ten_consumir` devolve sempre uma linha. Zero linhas significa que a
    // chamada nao chegou a funcao — e tratar isso como «aceite» seria consumir
    // sem contar.
    throw new RespostaIlegivelError("ten_consumir", rows);
  }
  const aceite = booleano(linha.aceite);
  const limite = linha.limite === null || linha.limite === undefined
    ? null
    : inteiro("limite", linha.limite);
  const consumo: Consumo = {
    aceite,
    valor: inteiro("valor", linha.valor),
    repetido: booleano(linha.repetido),
    limite,
    motivo: aceite ? null : limite === null ? "sem_entitlement" : "limite_excedido",
  };
  if (consumo.motivo === "limite_excedido") {
    metricas.contar(METRICA_LIMITE_NEGADO, nome);
  } else if (consumo.motivo === "sem_entitlement" && opcoes.modulo !== undefined) {
    metricas.contar(METRICA_ENTITLEMENT_NEGADO, exigirNome("modulo", opcoes.modulo));
  }
  return consumo;
}

/** O desfecho de um `checkCeiling`. **Nada disto escreveu nada.** */
export interface Tecto {
  /** A chave de limite perguntada. */
  readonly chave: string;
  /** O valor cabe no tecto? */
  readonly cabe: boolean;
  /** O valor que se perguntou, tal como veio. */
  readonly valor: number;
  /**
   * O tecto efectivo, o minimo entre os modulos activos que declaram a chave.
   * **`null` quando nenhum a declara** — e `null` nega.
   */
  readonly tecto: number | null;
  /** `null` quando cabe. Senao, qual das duas recusas foi. */
  readonly motivo: "sem_entitlement" | "tecto_excedido" | null;
}

/**
 * «Este valor cabe no tecto?» — **sem escrever nada** (criterio 2).
 *
 * A outra pergunta do TEN, e a que faltava. Um tecto por pedido
 * (`valor_max_pedido_minor`, `manual_max_minor`, `manual_dupla_acima_minor`)
 * nao tem contador e nao tem periodo: compara-se o valor de **um** pedido com
 * o tecto, e o pedido passa ou nao passa. Nao ha linha em
 * `platform.tenant_usage`, nao ha `usage_ledger`, nao ha chave de idempotencia
 * — nao ha nada para repetir, porque nada mudou.
 *
 * **O tecto e o mesmo que a `ten_consumir` usaria — a mesma funcao, e nao a
 * mesma regra copiada**: o `SQL_TECTO` chama `platform.ten_tecto`, que e quem
 * a `ten_consumir` tambem chama. Nao ha aqui um minimo em JavaScript nem um
 * `min(...)` repetido numa consulta.
 *
 * **Sem linha activa que declare a chave, nega** — falha fechada, criterio 2,
 * e exactamente como a `0007` faz com `limite = NULL`: «sem tecto» nao quer
 * dizer «sem limite». A RLS poe o mesmo a acontecer quando o contexto da
 * transaccao e de outro tenant, e zero linhas le-se como negado e nao como
 * «nao sei».
 *
 * **Um limite ilegivel levanta `LimiteIlegivelError`, e nao devolve «nao
 * cabe».** A `ten_tecto` recusa-se a adivinhar um `limites` que nao seja um
 * inteiro nao negativo, e levanta `22023` em vez de ignorar a linha —
 * ignora-la tirava um modulo do minimo, e o minimo de menos modulos e maior.
 * Deste lado, traduzir isso em `cabe = false` seria dizer ao tenant que o
 * pedido dele e grande demais quando o que ha e um dado corrompido: quem
 * recebe este erro corrige o provisionamento (KAM-091), nao o plano.
 *
 * **So serve tectos por pedido.** Um balde (`msgs_ai_mes`) levanta: a pergunta
 * dele e «quanto ja gastei», e responde-se com `consumeLimit`. As duas chaves
 * de janela tambem levantam — ver `exigirTecto`.
 *
 * `manual_dupla_acima_minor` e o unico caso em que `cabe = false` **nao e uma
 * recusa**: o registo escreve-o por extenso («o unico tecto por pedido cuja
 * comparacao NAO nega»), e acima do limiar o pedido exige o segundo
 * confirmador (`docs/tecnica/04` §4.2 M-5). A comparacao e a mesma; o que quem
 * chama faz com ela e que nao e. Esta funcao devolve o facto.
 *
 * Conta `ten_limit_denied_total{key}` quando o tecto nao chega, pela mesma
 * razao que o consumo o faz: o painel mostra acessos negados.
 */
export async function checkCeiling(
  bd: ClienteSql,
  tenant: unknown,
  chave: unknown,
  valor: unknown,
  opcoes: { readonly modulo?: string; readonly metricas?: MetricasDoTen } = {},
): Promise<Tecto> {
  const canonico = normalizarTenant(tenant);
  const nome = exigirTecto(chave);
  if (typeof valor !== "number" || !Number.isSafeInteger(valor) || valor < 0) {
    throw new QuantidadeInvalidaError(valor);
  }
  const metricas = opcoes.metricas ?? METRICAS;

  let rows: Record<string, unknown>[] = [];
  try {
    ({ rows } = await bd.query(SQL_TECTO, [canonico, nome]));
  } catch (erro) {
    // Aqui o `22023` **so** pode vir da `ten_tecto`: esta consulta nao passa
    // instante nenhum, logo a guarda de `p_agora` nao existe neste caminho.
    // Traduz-se sem olhar para a mensagem, e um limite ilegivel nunca se le
    // como «nao cabe».
    if (sqlstateDe(erro) === SQLSTATE_LIMITE_ILEGIVEL) {
      throw new LimiteIlegivelError();
    }
    throw erro;
  }
  // O `SQL_TECTO` e um `SELECT` de uma funcao: devolve **sempre** uma linha, e
  // a `ten_tecto` devolve `NULL` quando ninguem declara a chave. Zero linhas
  // quer dizer que a chamada nao chegou a base — e a leitura fechada disso e a
  // mesma do `SQL_ENTITLEMENT`: nega-se. Ao contrario do consumo, aqui nao ha
  // nada escrito por saber, logo negar chega e nao ha que levantar.
  const bruto = rows[0]?.tecto;
  const tecto = bruto === null || bruto === undefined ? null : inteiro("tecto", bruto);

  if (tecto === null) {
    if (opcoes.modulo !== undefined) {
      metricas.contar(METRICA_ENTITLEMENT_NEGADO, exigirNome("modulo", opcoes.modulo));
    }
    return { chave: nome, cabe: false, valor, tecto: null, motivo: "sem_entitlement" };
  }
  if (valor <= tecto) {
    return { chave: nome, cabe: true, valor, tecto, motivo: null };
  }
  metricas.contar(METRICA_LIMITE_NEGADO, nome);
  return { chave: nome, cabe: false, valor, tecto, motivo: "tecto_excedido" };
}

/**
 * O periodo de um instante, perguntado a base.
 *
 * Nao decide nada — a `ten_consumir` chama a mesma funcao la dentro. Existe
 * para quem precisa de **mostrar** o periodo e para os testes de fronteira de
 * mes poderem perguntar a base o que ela conta, em vez de o reescreverem.
 */
export async function periodo(bd: ClienteSql, agora?: Date | null): Promise<string> {
  const { rows } = await bd.query(SQL_PERIODO, [agora ?? null]);
  const valor = rows[0]?.periodo;
  if (valor instanceof Date) return valor.toISOString().slice(0, 10);
  if (typeof valor === "string") return valor;
  throw new RespostaIlegivelError("periodo", valor);
}

/** TTL da cache, em milissegundos. **Proposta**: o criterio 6 pede «<= 60 s». */
export const TTL_POR_OMISSAO_MS = 60_000;

/** Quantas entradas a cache guarda antes de deitar fora as mais velhas. */
export const MAXIMO_DE_ENTRADAS = 10_000;

interface Entrada {
  readonly decisao: Entitlement;
  readonly expiraEm: number;
}

/**
 * O relogio da cache, em milissegundos, **monotonico**.
 *
 * `performance.now()` e nao `Date.now()`: o relogio de parede anda para tras
 * quando o NTP o corrige, e uma entrada guardada com `expiraEm` calculado
 * antes de um salto de dez minutos ficava dez minutos a mais em cache — o
 * criterio 6 fala de 60 s e um salto de relogio nao e desculpa. O espelho em
 * Python usa `time.monotonic()` pela mesma razao. As duas epocas sao
 * diferentes e nao precisam de coincidir: cada processo so compara este
 * relogio consigo proprio.
 */
export function agoraMs(): number {
  return performance.now();
}

/**
 * Cache de entitlements com TTL. **Nunca devolve dados de outro tenant.**
 *
 * ## A visibilidade e so pelo TTL, e isso tem de ficar escrito
 *
 * O criterio 6 pede que uma alteracao de entitlement seja visivel em <= 60 s.
 * A forma habitual de o conseguir e invalidar por evento — e o que o `01` §7.2
 * faz com a cache do CHR, «invalidado por evento `channel.updated`». **Aqui nao
 * ha evento equivalente**: o catalogo de eventos nao tem nenhum `entitlement.*`
 * (verificado contra o catalogo; os tipos existentes sao de canal, encomenda,
 * pagamento, marcacao e stock). Logo a unica coisa que torna uma alteracao
 * visivel e a expiracao, e o limite superior do atraso e **exactamente** o TTL.
 *
 * Duas consequencias que quem usa isto tem de saber: um entitlement **retirado**
 * continua a permitir ate 60 s, e nao ha forma de o apressar a nao ser chamar
 * `invalidar`. Criar o evento `entitlement.updated` e trabalho do catalogo
 * (KAM-007) e do provisionamento (KAM-091), e fica **proposto aqui, nao feito**.
 *
 * ## Porque e que a chave nao pode misturar tenants
 *
 * A chave e `<uuid canonico>\0<modulo>`. O tenant passa pelo
 * `normalizarTenant`, que so aceita a forma canonica — duas escritas do mesmo
 * tenant seriam duas chaves, e uma escrita estranha podia ser construida para
 * colidir com outra. O separador e `\0`, que nem um UUID nem um modulo
 * (`^[a-z][a-z0-9_]*$`) podem conter: sem ele, um tenant que acabasse em `:` e
 * um modulo que comecasse por um digito dariam a mesma chave que outro par.
 *
 * O `invalidar(tenant)` apaga **so** as entradas desse tenant, pelo prefixo.
 *
 * ## Guarda-se tambem o que **negou**, e isso tem uma consequencia
 *
 * Uma recusa fica em cache como uma permissao fica. O caso a conhecer e o
 * `sem_tenant`: a consulta devolve zero linhas tanto para um tenant que nao
 * existe como para um pedido feito com o **contexto de RLS de outro tenant** —
 * e, nesse segundo caso, a recusa guardada e consequencia de um defeito de
 * quem chama e sobrevive-lhe ate 60 s. Guarda-se na mesma, por duas razoes: o
 * sentido do erro e o seguro (nega-se de mais, nunca de menos), e nao guardar
 * deixava um tenant inexistente a bater na base a cada pedido. Quem corrige o
 * contexto chama `invalidar`.
 */
export class CacheDeEntitlements {
  readonly #entradas = new Map<string, Entrada>();
  readonly ttlMs: number;
  readonly maximo: number;

  constructor(ttlMs: number = TTL_POR_OMISSAO_MS, maximo: number = MAXIMO_DE_ENTRADAS) {
    if (!Number.isFinite(ttlMs) || ttlMs <= 0) {
      throw new RangeError(`o TTL tem de ser positivo: ${ttlMs}`);
    }
    if (!Number.isInteger(maximo) || maximo <= 0) {
      throw new RangeError(`o maximo tem de ser um inteiro positivo: ${maximo}`);
    }
    this.ttlMs = ttlMs;
    this.maximo = maximo;
  }

  #chave(tenant: unknown, modulo: unknown): string {
    return `${normalizarTenant(tenant)}\u0000${exigirNome("modulo", modulo)}`;
  }

  /** A decisao guardada, ou `undefined` se nao ha ou ja expirou. */
  ler(tenant: unknown, modulo: unknown, agora: number = agoraMs()): Entitlement | undefined {
    const chave = this.#chave(tenant, modulo);
    const entrada = this.#entradas.get(chave);
    if (entrada === undefined) return undefined;
    if (entrada.expiraEm <= agora) {
      this.#entradas.delete(chave);
      return undefined;
    }
    return entrada.decisao;
  }

  guardar(
    tenant: unknown,
    modulo: unknown,
    decisao: Entitlement,
    agora: number = agoraMs(),
  ): void {
    const chave = this.#chave(tenant, modulo);
    // Primeiro as expiradas: numa cache de entitlements a maioria das entradas
    // velhas ja nao vale nada, e deitar fora uma viva para dar lugar a uma nova
    // enquanto ha mortas la dentro era pagar duas idas a base por uma.
    if (!this.#entradas.has(chave) && this.#entradas.size >= this.maximo) {
      for (const [existente, entrada] of this.#entradas) {
        if (entrada.expiraEm <= agora) this.#entradas.delete(existente);
      }
    }
    // Ainda cheia: sai a mais antiga a entrar, que e a primeira do `Map`.
    while (!this.#entradas.has(chave) && this.#entradas.size >= this.maximo) {
      const primeira = this.#entradas.keys().next();
      if (primeira.done === true) break;
      this.#entradas.delete(primeira.value);
    }
    this.#entradas.set(chave, { decisao, expiraEm: agora + this.ttlMs });
  }

  /** Esquece tudo o que e deste tenant, e so dele. */
  invalidar(tenant: unknown): void {
    const prefixo = `${normalizarTenant(tenant)}\u0000`;
    for (const chave of [...this.#entradas.keys()]) {
      if (chave.startsWith(prefixo)) this.#entradas.delete(chave);
    }
  }

  repor(): void {
    this.#entradas.clear();
  }

  get tamanho(): number {
    return this.#entradas.size;
  }
}
