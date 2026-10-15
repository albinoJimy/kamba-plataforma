/**
 * Configuração do armazenamento, e o destino dos dados (KAM-011).
 *
 * Dois assuntos num ficheiro, porque são a mesma pergunta feita no arranque:
 * **«para onde é que isto vai escrever?»**
 *
 * 1. Onde está o servidor — `endpoint`, `bucket`, `regiao`. É isto que deixa a
 *    decisão D6 aberta: trocar de SeaweedFS para um S3 gerido é trocar
 *    variáveis, não código.
 * 2. Em que **país** e com que **fornecedor** ficam os bytes — `destino.country`
 *    e `destino.provider`. Não são decoração: o ADR-008 diz que nenhum dado
 *    pessoal de produção sai de Angola sem o procedimento da APD, e o
 *    armazenamento guarda áudio, fotos e documentos de identificação. Um
 *    processo que não sabe dizer em que país escreve não arranca.
 *
 * O que este módulo **não** faz: não decide se um país é «adequado». Não há
 * lista pública (`docs/tecnica/08` §8.3.1, NÃO VERIFICADO), e o código nunca
 * infere adequação a partir do país. A regra é só a que o ticket escreve: em
 * `prod`, fora de `AO`, sem `apd_ref`, não arranca. O *gate* de transferência
 * por tenant (`tenant_destinations`, `assertDestinationAllowed`) é do KAM-069,
 * que lê o `destino` daqui.
 *
 * As credenciais **não** são configuração: vêm do `SecretProvider` (KAM-010),
 * pelas referências `storage_access_key_id` e `storage_secret_access_key` do
 * inventário (`ops/secrets-inventory.yaml`).
 */

import { AMBIENTES, type Ambiente, isAmbiente } from "../secrets/port.ts";
import { ArmazenamentoPorTenant } from "./guarda.ts";
import type { StorageProvider } from "./port.ts";
import { MotorS3, type Transporte } from "./s3.ts";

/** Subconjunto de `process.env` de que este módulo depende. */
export type ProcessEnv = Record<string, string | undefined>;

/** Nomes das variáveis de ambiente. Nenhuma delas é um segredo. */
export const VARIAVEIS = {
  endpoint: "KAMBA_STORAGE_ENDPOINT",
  bucket: "KAMBA_STORAGE_BUCKET",
  regiao: "KAMBA_STORAGE_REGION",
  country: "KAMBA_STORAGE_DESTINO_COUNTRY",
  provider: "KAMBA_STORAGE_DESTINO_PROVIDER",
  apdRef: "KAMBA_STORAGE_DESTINO_APD_REF",
} as const;

/** O país em que os dados podem ficar sem `apd_ref` (ADR-008). */
export const PAIS_SEM_TRANSFERENCIA = "AO";

/**
 * Para onde vão os dados.
 *
 * Os três campos têm os nomes de `tenant_destinations(provider, country,
 * apd_ref)` (`docs/tecnica/08` §8.3.1) porque é essa a tabela que o KAM-069 vai
 * confrontar com isto.
 */
export interface DestinoDeArmazenamento {
  /** ISO 3166-1 alfa-2, em maiúsculas: `AO`, `ZA`. */
  readonly country: string;
  /** Identificador do fornecedor, em minúsculas. */
  readonly provider: string;
  /** Referência do procedimento na APD; `null` se não há. */
  readonly apdRef: string | null;
}

export interface StorageConfig {
  readonly endpoint: string;
  readonly bucket: string;
  readonly regiao: string;
  readonly destino: DestinoDeArmazenamento;
  /**
   * Avisos que não impedem o arranque. Fora de `prod`, um destino fora de
   * Angola sem `apd_ref` aparece aqui — quem arranca o serviço decide onde os
   * escrever; este módulo não regista nada.
   */
  readonly avisos: readonly string[];
}

/** A configuração não serve. A mensagem nomeia as variáveis, nunca os valores. */
export class ConfigDeArmazenamentoError extends Error {
  override readonly name = "ConfigDeArmazenamentoError";
  /** Um problema por variável. */
  readonly problemas: readonly string[];
  constructor(problemas: readonly string[]) {
    super(`configuração de armazenamento inválida: ${problemas.join("; ")}`);
    this.problemas = problemas;
  }
}

/**
 * Em `prod`, o destino está fora de Angola e não há `apd_ref`.
 *
 * É o «aviso bloqueante no arranque» do critério de aceitação 7: lança, e quem
 * arranca o serviço não tem como continuar sem o resolver.
 */
export class DestinoSemApdRefError extends Error {
  override readonly name = "DestinoSemApdRefError";
  readonly country: string;
  readonly provider: string;
  constructor(country: string, provider: string) {
    super(
      `armazenamento em prod com destino ${country} (fornecedor ${provider}) e sem ` +
        `${VARIAVEIS.apdRef}: nenhum dado pessoal sai de Angola sem referência da APD ` +
        "(ADR-008); o serviço não arranca",
    );
    this.country = country;
    this.provider = provider;
  }
}

const PAIS = /^[A-Z]{2}$/;
const FORNECEDOR = /^[a-z][a-z0-9_-]{1,62}$/;
const BUCKET = /^[a-z0-9][a-z0-9.-]{1,61}[a-z0-9]$/;
const REGIAO = /^[a-z0-9][a-z0-9-]{0,62}$/;
const APD_REF = /^[A-Za-z0-9][A-Za-z0-9._/:-]{0,127}$/;

/**
 * O endpoint inteiro, numa só expressão e **sem** analisador de URL: o `URL` do
 * Node e o `urlsplit` do Python discordam em dezenas de casos de fronteira
 * (`http://h/?`, `http://0x7f.1`, `http:h`), e uma expressão igual dos dois
 * lados não discorda em nenhum. Esquema, anfitrião em minúsculas (nome, IPv4
 * ou IPv6 entre parênteses rectos), porta opcional, barra final opcional — e
 * mais nada.
 */
const ENDPOINT =
  /^(https?):\/\/([a-z0-9](?:[a-z0-9.-]{0,251}[a-z0-9])?|\[[0-9a-f:]{2,39}\])(?::([0-9]{1,5}))?\/?$/;

/**
 * O que se tira das pontas de um valor: espaço, tabulação e mudanças de linha,
 * e só isso. O `trim()` do JavaScript e o `strip()` do Python não tiram os
 * mesmos caracteres.
 */
const BRANCOS = /^[ \t\r\n]+|[ \t\r\n]+$/g;

function ler(env: ProcessEnv, nome: string): string | null {
  const valor = (env[nome] ?? "").replace(BRANCOS, "");
  return valor === "" ? null : valor;
}

/**
 * Lê e valida a configuração. Falha com **todos** os problemas de uma vez.
 *
 * @throws {ConfigDeArmazenamentoError} variável obrigatória ausente ou mal formada.
 * @throws {DestinoSemApdRefError} em `prod`, fora de `AO`, sem `apd_ref`.
 */
export function lerConfig(o: {
  readonly ambiente: Ambiente;
  readonly env?: ProcessEnv;
}): StorageConfig {
  const env = o.env ?? process.env;
  // Um ambiente fora do domínio não é «não é prod»: é não saber onde se está.
  // A regra do destino só bloqueia em `prod`, pelo que `PROD`, `production` ou
  // um valor vazio a desligavam em silêncio (`ANALISE-09`, A1).
  if (!isAmbiente(o.ambiente)) {
    throw new ConfigDeArmazenamentoError([
      `ambiente desconhecido (esperava ${AMBIENTES.join(", ")})`,
    ]);
  }
  const problemas: string[] = [];

  const exigir = (nome: string, forma: RegExp, descricao: string): string => {
    const valor = ler(env, nome);
    if (valor === null) {
      problemas.push(`${nome} em falta`);
      return "";
    }
    if (!forma.test(valor)) {
      problemas.push(`${nome} mal formada (${descricao})`);
      return "";
    }
    return valor;
  };

  let endpoint = ler(env, VARIAVEIS.endpoint) ?? "";
  if (endpoint === "") {
    problemas.push(`${VARIAVEIS.endpoint} em falta`);
  } else {
    const m = ENDPOINT.exec(endpoint);
    const porta = m === null || m[3] === undefined ? null : Number(m[3]);
    if (m === null || (porta !== null && (porta < 1 || porta > 65535))) {
      // Sem repetir o valor: um endpoint com credenciais embutidas é
      // precisamente um dos casos recusados.
      problemas.push(
        `${VARIAVEIS.endpoint} mal formada (esperava http(s)://anfitrião[:porta], sem caminho nem credenciais)`,
      );
      endpoint = "";
    } else {
      // A porta por omissão do esquema não fica: é a forma que o cabeçalho
      // `Host` leva, e a que é assinada.
      const omissa =
        porta === null || (m[1] === "http" && porta === 80) || (m[1] === "https" && porta === 443);
      endpoint = `${m[1]}://${m[2]}${omissa ? "" : `:${porta}`}`;
    }
  }

  const bucket = exigir(VARIAVEIS.bucket, BUCKET, "nome de bucket S3, em minúsculas");
  const regiao = exigir(VARIAVEIS.regiao, REGIAO, "identificador de região, em minúsculas");
  const country = exigir(VARIAVEIS.country, PAIS, "ISO 3166-1 alfa-2, em maiúsculas");
  const provider = exigir(VARIAVEIS.provider, FORNECEDOR, "identificador em minúsculas");

  let apdRef = ler(env, VARIAVEIS.apdRef);
  if (apdRef !== null && !APD_REF.test(apdRef)) {
    problemas.push(`${VARIAVEIS.apdRef} mal formada (até 128 caracteres, sem espaços)`);
    apdRef = null;
  }

  if (problemas.length > 0) throw new ConfigDeArmazenamentoError(problemas);

  const avisos: string[] = [];
  if (country !== PAIS_SEM_TRANSFERENCIA && apdRef === null) {
    if (o.ambiente === "prod") throw new DestinoSemApdRefError(country, provider);
    avisos.push(
      `destino de armazenamento ${country} sem ${VARIAVEIS.apdRef}: em prod isto impede o arranque`,
    );
  }

  return { endpoint, bucket, regiao, destino: { country, provider, apdRef }, avisos };
}

/** O mínimo da porta de segredos de que o armazenamento precisa. */
export interface CofreLeitor {
  get(ref: string): Promise<string>;
}

/**
 * Cria o armazenamento S3, já com a guarda de isolamento.
 *
 * ```ts
 * const config = lerConfig({ ambiente });
 * const storage = criarStorageS3({ config, secrets });
 * ```
 *
 * As credenciais são pedidas ao `secrets` **em cada pedido** e nunca guardadas
 * aqui: a cache, a janela de indisponibilidade e a rotação são do `Secrets` do
 * KAM-010, e duplicá-las aqui criava um segundo sítio onde uma chave revogada
 * continuava viva.
 */
export function criarStorageS3(o: {
  readonly config: StorageConfig;
  readonly secrets: CofreLeitor;
  readonly transporte?: Transporte;
  readonly agora?: () => Date;
  readonly tamanhoDaParte?: number;
}): StorageProvider {
  const secrets = o.secrets;
  return new ArmazenamentoPorTenant(
    new MotorS3({
      endpoint: o.config.endpoint,
      bucket: o.config.bucket,
      regiao: o.config.regiao,
      credenciais: async () => ({
        accessKeyId: await secrets.get("storage_access_key_id"),
        secretAccessKey: await secrets.get("storage_secret_access_key"),
      }),
      ...(o.transporte === undefined ? {} : { transporte: o.transporte }),
      ...(o.agora === undefined ? {} : { agora: o.agora }),
      ...(o.tamanhoDaParte === undefined ? {} : { tamanhoDaParte: o.tamanhoDaParte }),
    }),
  );
}
