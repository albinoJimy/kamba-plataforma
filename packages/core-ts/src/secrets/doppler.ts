/**
 * `DopplerSecretProvider` — o adaptador do cofre do Piloto (KAM-010).
 *
 * ## Estado desta implementação, dito em voz alta
 *
 * Está **escrita e testada contra um *fake* de transporte, sem credenciais e
 * sem nunca ter falado com a Doppler**. Não existe conta Doppler neste ticket
 * (ver `specs/EPIC-01_Fundacoes_Dados.md`, bloco KAM-010, secção
 * «Verificação dos Critérios de Aceitação»), pelo que:
 *
 * - O caminho, os parâmetros e a **forma exacta da resposta** da API são
 *   **NÃO VERIFICADO**. Confirmam-se na referência da API em
 *   `docs.doppler.com` antes do primeiro uso real, e o sítio exacto onde se
 *   confirma cada um está na constante `A_CONFIRMAR` em baixo.
 * - Tudo o que depende da forma da resposta está atrás de **uma só função**
 *   (`interpretar`), injectável. Quando a forma real se confirmar, muda-se essa
 *   função e mais nada; se a suposição estiver errada, o custo é uma função e
 *   não um adaptador.
 * - O que **não** é suposição é o modelo de autenticação e de isolamento que o
 *   `E4` §2.14 confirma em resumo: projectos separados e *service tokens* por
 *   configuração. É sobre isso que a guarda de ambiente deste adaptador assenta.
 *
 * O preço (Developer grátis até 3 utilizadores, $8/utilizador acima; 10
 * projectos, 50 *service tokens*, logs de 3 dias) é CONFIRMADO **em resumo** no
 * `E4` §2.14 e herda esse estado: não o promovas a CONFIRMADO por aparecer aqui.
 */

import {
  AmbienteErradoError,
  type Ambiente,
  CofreInacessivelError,
  SecretAusenteError,
  type SecretProvider,
  type SecretRef,
  type SecretRingTuple,
  validarRef,
} from "./port.ts";
import { SUFIXO_ANTERIOR, nomeDaVariavel } from "./env.ts";

/**
 * O que falta confirmar, e onde.
 *
 * Fica no código e não só num documento de propósito: quem for ligar isto a uma
 * conta real tropeça nesta constante antes de tropeçar numa resposta 404.
 */
export const A_CONFIRMAR = {
  caminho:
    "caminho e parâmetros do pedido de leitura de segredos — docs.doppler.com, referência da API (secrets / download)",
  resposta:
    "forma do JSON de resposta; `interpretarDescargaPlana` assume um objecto plano NOME→valor — docs.doppler.com, referência da API",
  cabecalhoAuth:
    "forma do cabeçalho de autenticação com um service token (Bearer vs Basic) — docs.doppler.com, referência de autenticação",
  identificacaoDaConfig:
    "se a resposta identifica o projecto/config servidos; se identificar, ligar `configDaResposta` e a guarda deixa de ser só do lado do cliente",
} as const;

/** Resposta HTTP, reduzida ao que este adaptador usa. */
export interface RespostaHttp {
  readonly status: number;
  readonly corpo: string;
}

/** Pedido HTTP, reduzido ao que este adaptador faz. */
export interface PedidoHttp {
  readonly url: string;
  readonly cabecalhos: Readonly<Record<string, string>>;
}

/**
 * Transporte injectado.
 *
 * O adaptador não chama `fetch` directamente para que a suite de contrato possa
 * correr sem rede e sem credenciais — e para que o dia em que o egresso dos
 * contentores ficar restrito (`docs/tecnica/08` §4.8) não seja o dia em que se
 * descobre que os testes dependiam de rede.
 */
export type Transporte = (pedido: PedidoHttp) => Promise<RespostaHttp>;

/** Interpreta o corpo da resposta num mapa NOME→valor. */
export type Interpretar = (corpo: string) => Readonly<Record<string, string>>;

/**
 * Interpretação por omissão: objecto JSON plano, `NOME → valor`.
 *
 * **NÃO VERIFICADO** (`A_CONFIRMAR.resposta`). É a forma que uma descarga em
 * JSON tipicamente tem, e é a que mantém este adaptador legível enquanto não há
 * conta; não é a forma confirmada da API.
 */
export const interpretarDescargaPlana: Interpretar = (corpo) => {
  let cru: unknown;
  try {
    cru = JSON.parse(corpo);
  } catch {
    // Sem o corpo na mensagem: um corpo de 200 contém segredos.
    throw new CofreInacessivelError("doppler", "resposta não é JSON");
  }
  if (typeof cru !== "object" || cru === null || Array.isArray(cru)) {
    throw new CofreInacessivelError("doppler", "resposta não é um objecto JSON");
  }
  const mapa: Record<string, string> = {};
  for (const [nome, valor] of Object.entries(cru as Record<string, unknown>)) {
    if (typeof valor === "string") mapa[nome] = valor;
  }
  return mapa;
};

/** Opções de construção. */
export interface DopplerOpcoes {
  /** Ambiente em que o processo corre; tem de bater com `config`. */
  readonly ambiente: Ambiente;
  /** Nome do projecto Doppler. */
  readonly projecto: string;
  /**
   * Nome da configuração Doppler.
   *
   * Tem de ser igual a `ambiente`. Os três projectos do Piloto chamam-se
   * `dev`, `staging` e `prod` (`docs/tecnica/09` §6) e as configurações herdam o
   * nome: assim a guarda em baixo é uma comparação de texto e não uma tabela de
   * tradução que alguém mantém mal.
   */
  readonly config: string;
  /** *Service token*. Nunca aparece em mensagem de erro nem em log. */
  readonly tokenServico: string;
  readonly transporte: Transporte;
  /** Por omissão, `https://api.doppler.com`. */
  readonly baseUrl?: string;
  /** Por omissão, `interpretarDescargaPlana`. */
  readonly interpretar?: Interpretar;
  /**
   * Extrai da resposta a configuração que o cofre realmente servidor.
   *
   * Quando é fornecida, a guarda de ambiente deixa de ser só do lado do cliente:
   * um token de `staging` que devolvesse a configuração `staging` contra um
   * processo de `prod` é recusado aqui mesmo. Fica opcional porque saber se a
   * resposta traz essa informação é `A_CONFIRMAR.identificacaoDaConfig`.
   */
  readonly configDaResposta?: (corpo: string) => string | null;
  /** Milissegundos de validade da descarga em memória. Por omissão 60 000. */
  readonly ttlDescargaMs?: number;
  /** Relógio injectável, para os testes. */
  readonly agora?: () => number;
}

/**
 * Adaptador Doppler.
 *
 * Lê a configuração inteira de uma vez e serve os segredos a partir dela. Não é
 * optimização: o modelo do Doppler é «uma configuração = um conjunto de
 * variáveis», e um pedido por segredo multiplicaria por vinte os acessos a um
 * SaaS que o `E4` §5 marca como risco de dependência.
 *
 * O nome de cada variável é o mesmo que o `EnvSecretProvider` usa
 * (`KAMBA_SECRET_…`), e isto é deliberado: é o que faz `doppler run -- …`
 * (ADR-L002) e este adaptador servirem os mesmos nomes, de modo que trocar um
 * pelo outro não muda o inventário nem o código dos serviços.
 */
export class DopplerSecretProvider implements SecretProvider {
  readonly nome = "doppler";
  readonly ambiente: Ambiente;
  readonly projecto: string;
  readonly config: string;

  readonly #token: string;
  readonly #transporte: Transporte;
  readonly #baseUrl: string;
  readonly #interpretar: Interpretar;
  readonly #configDaResposta: ((corpo: string) => string | null) | undefined;
  readonly #ttl: number;
  readonly #agora: () => number;

  #cache: { mapa: Readonly<Record<string, string>>; em: number } | null = null;

  constructor(opcoes: DopplerOpcoes) {
    // A guarda que o critério de aceitação do KAM-010 pede do lado do servidor
    // (um token de `staging` recusado contra `prod`) **não se pode provar sem
    // conta**. Esta é a metade que se pode ter sem conta, e vale por si: um
    // processo de `prod` configurado com a configuração de `staging` recusa-se a
    // existir, em vez de servir pedidos reais com chaves de teste.
    if (opcoes.config !== opcoes.ambiente) {
      throw new AmbienteErradoError("doppler", opcoes.ambiente, opcoes.config);
    }
    if (opcoes.tokenServico.trim() === "") {
      throw new CofreInacessivelError("doppler", "service token não configurado");
    }
    this.ambiente = opcoes.ambiente;
    this.projecto = opcoes.projecto;
    this.config = opcoes.config;
    this.#token = opcoes.tokenServico;
    this.#transporte = opcoes.transporte;
    this.#baseUrl = opcoes.baseUrl ?? "https://api.doppler.com";
    this.#interpretar = opcoes.interpretar ?? interpretarDescargaPlana;
    this.#configDaResposta = opcoes.configDaResposta;
    this.#ttl = opcoes.ttlDescargaMs ?? 60_000;
    this.#agora = opcoes.agora ?? Date.now;
  }

  async health(): Promise<void> {
    await this.#descarregar();
  }

  async get(ref: SecretRef): Promise<string> {
    const mapa = await this.#descarregar();
    const nome = nomeDaVariavel(ref);
    const valor = mapa[nome];
    if (valor === undefined || valor.trim() === "") {
      throw new SecretAusenteError(validarRef(ref), this.nome);
    }
    return valor;
  }

  async getRing(ref: SecretRef): Promise<SecretRingTuple> {
    const mapa = await this.#descarregar();
    const nome = nomeDaVariavel(ref);
    const actual = mapa[nome];
    if (actual === undefined || actual.trim() === "") {
      throw new SecretAusenteError(validarRef(ref), this.nome);
    }
    const anterior = mapa[nome + SUFIXO_ANTERIOR];
    return [actual, anterior === undefined || anterior.trim() === "" ? null : anterior];
  }

  async versions(ref: SecretRef): Promise<readonly string[]> {
    const [, anterior] = await this.getRing(ref);
    return anterior === null ? ["actual"] : ["actual", "anterior"];
  }

  async #descarregar(): Promise<Readonly<Record<string, string>>> {
    const cache = this.#cache;
    if (cache !== null && this.#agora() - cache.em < this.#ttl) return cache.mapa;

    // `A_CONFIRMAR.caminho` e `A_CONFIRMAR.cabecalhoAuth`.
    const url =
      `${this.#baseUrl}/v3/configs/config/secrets/download` +
      `?project=${encodeURIComponent(this.projecto)}` +
      `&config=${encodeURIComponent(this.config)}&format=json`;

    let resposta: RespostaHttp;
    try {
      resposta = await this.#transporte({
        url,
        cabecalhos: {
          authorization: `Bearer ${this.#token}`,
          accept: "application/json",
        },
      });
    } catch (erro) {
      throw new CofreInacessivelError(
        this.nome,
        `transporte falhou: ${erro instanceof Error ? erro.name : "erro desconhecido"}`,
      );
    }

    if (resposta.status === 401 || resposta.status === 403) {
      // Credencial recusada. Não se sabe se foi o token errado, o projecto
      // errado ou a configuração errada — e não se adivinha: diz-se o estado.
      throw new CofreInacessivelError(
        this.nome,
        `credencial recusada (HTTP ${resposta.status}) para ${this.projecto}/${this.config}`,
      );
    }
    if (resposta.status !== 200) {
      // Sem o corpo: pode conter segredos num 200 e detalhes de conta nos outros.
      throw new CofreInacessivelError(this.nome, `HTTP ${resposta.status}`);
    }

    const servida = this.#configDaResposta?.(resposta.corpo) ?? null;
    if (servida !== null && servida !== this.config) {
      throw new AmbienteErradoError(this.nome, this.ambiente, servida);
    }

    const mapa = this.#interpretar(resposta.corpo);
    this.#cache = { mapa, em: this.#agora() };
    return mapa;
  }
}
