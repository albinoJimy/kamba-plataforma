/**
 * O *token* de cliente cifrado: AES-256-GCM, DEK por tenant, KEK no cofre, `kid`
 * versionado (KAM-016, critério 3).
 *
 * ## Porque é que há cifra se o cofre já cifra
 *
 * O critério não deixa margem: «O token de cliente é guardado **cifrado**
 * (AES-256-GCM, DEK por tenant, KEK no cofre, `kid` versionado) com `token_ref`
 * em `tenant_channels`». As duas metades valem ao mesmo tempo — há uma cifra
 * nossa **e** há uma referência. O `ops/secrets-inventory.yaml` confirma-o de
 * outro lado: declara `kek_token_cliente` como entrada **separada** do
 * `meta_client_token`, com `anel: true`, `kid: true` e a descrição «chave que
 * encripta as DEK por tenant dos tokens de cliente (AES-256-GCM)». Uma KEK que
 * não cifrasse nada era uma entrada morta no inventário.
 *
 * O que se guarda no cofre, sob a referência cunhada, é portanto o
 * **criptograma** e não o *token*. É defesa em profundidade com um conteúdo
 * concreto: uma cópia do cofre — um `vault` exportado, um ficheiro de arranque,
 * uma variável de ambiente lida por engano — não dá o *token* a ninguém sem
 * também a KEK, que vive noutra família e tem dono diferente
 * (`owner: seguranca`, contra `owner: eng_canais` do *token*).
 *
 * ## A DEK por tenant é **derivada** e não guardada, e isso é decisão
 *
 * O KAM-008 guarda as DEK de contacto em `platform.contact_deks`, embrulhadas
 * pela KEK. Aqui **não há tabela de DEK**, e não se criou uma:
 *
 * * uma DEK guardada tem de ser lida antes de cada decifra, e isso põe uma ida à
 *   base no caminho de quem só queria falar com a Meta;
 * * a tabela do KAM-008 existe porque a DEK de um contacto tem de **sobreviver à
 *   rotação da KEK** sem re-cifrar os dados do contacto: re-embrulha-se a DEK.
 *   Aqui há um segredo por tenant e ele é **re-cunhável** — o `offboard_ou_expiracao`
 *   do inventário diz que a rotação do *token* é trocá-lo, não re-chaveá-lo;
 * * e uma tabela nova com `tenant_id` que a *suite* não saiba semear **falha o
 *   *gate* 6**, que é a razão que o KAM-023 escreveu para pôr
 *   `meta_error_codes_seen` numa coluna e não numa tabela.
 *
 * A DEK sai de `HKDF-SHA256(KEK_versão, info = domínio ‖ tenant_id)`. Duas
 * propriedades, e as duas são o que «DEK por tenant» quer dizer: dois tenants
 * nunca partilham chave, e saber a DEK de um não dá a de outro sem a KEK.
 *
 * ## O `kid` vai **dentro** do criptograma, e sem ele a rotação era um apagão
 *
 * A KEK tem anel (`getRing`) e versões (`versions`). Se o criptograma não
 * dissesse com que versão foi feito, o dia em que a KEK rodasse tornava
 * **todos** os *tokens* já guardados indecifráveis — e os *tokens* de cliente
 * não se podem regenerar sem o dono repetir o *popup* do Embedded Signup. O
 * formato leva o `kid` em claro, e isso não revela nada: é um identificador de
 * versão, não material de chave.
 *
 * O formato, e é o da `identity/cripto.ts` com um campo a mais:
 *
 *     versão(1) ‖ comprimento do kid(1) ‖ kid ‖ IV(12) ‖ etiqueta(16) ‖ cifra
 *
 * O comprimento do `kid` num octeto limita-o a 255 caracteres, que é muito mais
 * do que qualquer provedor usa (o OpenBao KV v2 usa inteiros; o `EnvSecretProvider`
 * usa rótulos). Um `kid` mais longo do que isso é recusado ao cifrar, e não
 * truncado: um `kid` truncado produz um criptograma que não abre e nada o diz.
 *
 * ## O contexto autenticado prende a cifra ao tenant
 *
 * `setAAD` com `domínio ‖ tenant_id ‖ kid`, pela mesma razão do `contextoDaCifra`
 * do KAM-008: um criptograma copiado para a linha de outro tenant **não abre**.
 * Sem ele, mover o `token_ref` de A para a linha de B dava a B o *token* de A — e
 * o `token_ref` é uma coluna que o `GRANT UPDATE` da `0001` concede a
 * `kamba_app`.
 *
 * **Nenhum erro deste ficheiro contém o valor que recusou**, como no
 * `identity/cripto.ts`.
 */

import { Buffer } from "node:buffer";
import { createCipheriv, createDecipheriv, hkdfSync, randomBytes } from "node:crypto";

/** Octetos de uma DEK e de uma KEK: AES-256. */
export const OCTETOS_DE_CHAVE = 32;
/** Octetos do IV de GCM: 96 bits, o tamanho para que o modo foi desenhado. */
export const OCTETOS_DE_IV = 12;
/** Octetos da etiqueta de autenticação de GCM. */
export const OCTETOS_DE_ETIQUETA = 16;
/** A versão do formato. Um octeto, e o primeiro do criptograma. */
export const VERSAO_DO_FORMATO = 1;
/** Tecto do `kid`: cabe num octeto de comprimento. */
export const MAXIMO_DO_KID = 255;
/**
 * Tecto do texto a cifrar.
 *
 * Um *token* de cliente da Meta não tem comprimento documentado em sítio nenhum
 * deste repositório (**NÃO VERIFICADO**); os que o `GraphFalso` cunha têm 45
 * caracteres. O tecto é generoso de propósito — recusar um *token* real por ser
 * comprido era perder um onboarding —, e existe só para que um valor
 * manifestamente errado (um corpo de resposta inteiro, um ficheiro) não entre.
 */
export const MAXIMO_DE_TEXTO = 4096;

const DOMINIO_DA_DEK = "kamba.onboarding.dek.v1";
const DOMINIO_DA_CIFRA = "kamba.onboarding.token.v1";

const UUID_CANONICO = /^[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}$/;

/** Levantada quando um criptograma não abre, ou quando o que se dá não cifra. */
export class TokenCifradoInvalidoError extends Error {
  override readonly name = "TokenCifradoInvalidoError";
  readonly motivo: string;

  constructor(motivo: string) {
    super(`o token cifrado não se consegue tratar: ${motivo}`);
    this.motivo = motivo;
  }
}

function exigirTenant(tenantId: string): string {
  const minusculas = typeof tenantId === "string" ? tenantId.toLowerCase() : "";
  if (!UUID_CANONICO.test(minusculas)) {
    throw new TokenCifradoInvalidoError("o tenant_id não é um UUID canónico");
  }
  return minusculas;
}

function exigirKek(kek: string): Buffer {
  // A KEK vem do cofre como cadeia. O `identity/chaves.ts` fixou a forma —
  // `gerarChaveVersionada` escreve-a em base64 — e lê-se da mesma maneira: uma
  // chave que não tenha 32 octetos depois de descodificada não é uma AES-256, e
  // isso falha aqui e não no primeiro `createCipheriv`.
  const octetos = Buffer.from(kek, "base64");
  if (octetos.byteLength !== OCTETOS_DE_CHAVE) {
    throw new TokenCifradoInvalidoError(
      `a KEK tem ${octetos.byteLength} octetos depois de base64 e precisa de ${OCTETOS_DE_CHAVE}`,
    );
  }
  return octetos;
}

/**
 * A DEK de um tenant, derivada da KEK. Determinística: a mesma KEK e o mesmo
 * tenant dão sempre a mesma chave.
 *
 * `hkdfSync` e não um `createHmac` à mão: o HKDF tem extracção e expansão, e a
 * extracção é o que torna uma KEK que não seja uniformemente aleatória
 * utilizável como material de chave. É a primitiva certa e está no `node:crypto`,
 * sem dependência nova.
 *
 * O `salt` é vazio de propósito. Um `salt` aqui teria de ser guardado em algum
 * sítio para a derivação ser repetível, e o sítio seria uma coluna nova — o que
 * esta decisão existe para evitar. A segurança do HKDF sem `salt` depende de a
 * KEK ter entropia de chave, e ela tem: é gerada por
 * `gerarChaveVersionada` com o gerador do sistema.
 */
export function dekDoTenant(kek: string, tenantId: string): Buffer {
  const chave = exigirKek(kek);
  const tenant = exigirTenant(tenantId);
  const info = Buffer.from(`${DOMINIO_DA_DEK}\0${tenant}`, "utf8");
  return Buffer.from(
    hkdfSync("sha256", chave, Buffer.alloc(0), info, OCTETOS_DE_CHAVE),
  );
}

/** O contexto autenticado: domínio, tenant e `kid`. */
export function contextoDaCifra(tenantId: string, kid: string): Buffer {
  return Buffer.from(`${DOMINIO_DA_CIFRA}\0${exigirTenant(tenantId)}\0${kid}`, "utf8");
}

/**
 * Cifra o *token* e devolve o criptograma em base64, pronto para o cofre.
 *
 * Cada chamada usa um IV novo: dois *tokens* iguais do mesmo tenant dão
 * criptogramas diferentes, que é o que impede quem veja o cofre de saber que dois
 * clientes têm o mesmo *token*.
 */
export function cifrarToken(
  kek: string,
  kid: string,
  tenantId: string,
  token: string,
): string {
  if (typeof kid !== "string" || kid.length === 0 || kid.length > MAXIMO_DO_KID) {
    throw new TokenCifradoInvalidoError(
      `o kid está vazio ou tem mais de ${MAXIMO_DO_KID} caracteres`,
    );
  }
  if (typeof token !== "string" || token.length === 0 || token.length > MAXIMO_DE_TEXTO) {
    throw new TokenCifradoInvalidoError(
      `o token está vazio ou tem mais de ${MAXIMO_DE_TEXTO} caracteres`,
    );
  }
  // O comprimento conta-se em **octetos de UTF-8** e não em caracteres: o
  // cabeçalho guarda octetos, e um `kid` de 200 caracteres acentuados tem mais
  // de 255 octetos. A verificação está antes de cifrar porque um `kid` que não
  // cabe no cabeçalho produziria um criptograma que nunca abre — e nada o diria.
  const octetosDoKid = Buffer.from(kid, "utf8");
  if (octetosDoKid.byteLength > MAXIMO_DO_KID) {
    throw new TokenCifradoInvalidoError(
      `o kid tem ${octetosDoKid.byteLength} octetos em UTF-8 e o comprimento cabe em um`,
    );
  }
  const dek = dekDoTenant(kek, tenantId);
  const iv = randomBytes(OCTETOS_DE_IV);
  const cifra = createCipheriv("aes-256-gcm", dek, iv);
  cifra.setAAD(contextoDaCifra(tenantId, kid));
  const corpo = Buffer.concat([cifra.update(token, "utf8"), cifra.final()]);
  return Buffer.concat([
    Buffer.from([VERSAO_DO_FORMATO, octetosDoKid.byteLength]),
    octetosDoKid,
    iv,
    cifra.getAuthTag(),
    corpo,
  ]).toString("base64");
}

/** O `kid` com que um criptograma foi feito, sem o abrir. Para escolher a versão da KEK. */
export function kidDoCriptograma(criptograma: string): string {
  const dados = Buffer.from(criptograma, "base64");
  if (dados.byteLength < 2 || dados[0] !== VERSAO_DO_FORMATO) {
    throw new TokenCifradoInvalidoError("formato desconhecido");
  }
  const comprimento = dados[1] ?? 0;
  if (comprimento === 0 || dados.byteLength < 2 + comprimento) {
    throw new TokenCifradoInvalidoError("o comprimento do kid não cabe no criptograma");
  }
  return dados.subarray(2, 2 + comprimento).toString("utf8");
}

/**
 * Abre o criptograma com a KEK da versão que ele próprio diz.
 *
 * Quem chama passa o **anel** e não uma chave: a KEK pode ter rodado desde que o
 * *token* foi guardado, e é o `kid` de dentro do criptograma que escolhe. Um
 * `kid` que não esteja no anel levanta — e levanta dizendo **qual** falta, porque
 * «o token não abre» e «a versão da KEK que o cifrou já não está no cofre» são
 * dois incidentes com reacções diferentes.
 */
export function decifrarToken(
  anel: Readonly<Record<string, string>>,
  tenantId: string,
  criptograma: string,
): string {
  const kid = kidDoCriptograma(criptograma);
  const kek = anel[kid];
  if (kek === undefined) {
    throw new TokenCifradoInvalidoError(
      `o criptograma foi cifrado com a versão ${kid} da KEK, que não está no anel`,
    );
  }
  const dados = Buffer.from(criptograma, "base64");
  const inicio = 2 + Buffer.from(kid, "utf8").byteLength;
  const cabecalho = inicio + OCTETOS_DE_IV + OCTETOS_DE_ETIQUETA;
  if (dados.byteLength <= cabecalho) {
    throw new TokenCifradoInvalidoError("o criptograma é mais curto do que o seu cabeçalho");
  }
  const decifra = createDecipheriv(
    "aes-256-gcm",
    dekDoTenant(kek, tenantId),
    dados.subarray(inicio, inicio + OCTETOS_DE_IV),
  );
  decifra.setAAD(contextoDaCifra(tenantId, kid));
  decifra.setAuthTag(dados.subarray(inicio + OCTETOS_DE_IV, cabecalho));
  try {
    return Buffer.concat([
      decifra.update(dados.subarray(cabecalho)),
      decifra.final(),
    ]).toString("utf8");
  } catch {
    // Sem o motivo do OpenSSL: ele é o mesmo para «DEK errada», «contexto
    // errado» e «conteúdo alterado», e repeti-lo sugeria uma distinção que não
    // existe. É a mesma escolha do `CifraInvalidaError` do KAM-008.
    throw new TokenCifradoInvalidoError("a autenticação falhou");
  }
}
