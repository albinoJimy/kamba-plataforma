/**
 * Arranque do onboarding-web.
 *
 * Escuta em `127.0.0.1` por omissão. Dentro de um contentor é preciso escutar em
 * `0.0.0.0` para que a rede do compose chegue ao processo, e é por isso que o
 * `Dockerfile` define `HOST=0.0.0.0` — mas nunca o faz o código por si, para que
 * correr o serviço à mão na máquina de alguém não abra uma porta na rede local
 * (`specs/01` §6, princípio 7, e o DoD do KAM-001: nada além de localhost).
 *
 * ## Em `prod` corre sobre a base, e só sobre ela (KAM-236) — e ainda recusa pelo SMS
 *
 * Até ao KAM-236 este processo **recusava** `prod`: o caso, o desafio do OTP,
 * os contadores do anti-abuso e as sessões revogadas do painel viviam em
 * memória, e um reinício perdia-os — um dono que preencheu o formulário e
 * voltou dois minutos depois encontrava o caso desaparecido, e o `nif_hmac` que
 * devia bloquear o duplicado desaparecia com ele.
 *
 * Agora vivem na base (revisão `0084`), pela ligação **`kamba_app`**
 * (`ONBOARDING_APP_DB_URL`), e em `prod` essa ligação é **obrigatória**: sem
 * ela o arranque recusa (`BaseEmFaltaEmProducaoError`), em vez de servir o
 * registo sobre memória. As buscas do registo que atravessam tenants passam
 * pelas funções `SECURITY DEFINER` da `0084`, que só devolvem o caso e o tenant
 * (decisão do fundador de 2026-11-21, D1-A); o resto lê-se pela RLS do tenant
 * do caso. Os contadores e as revogações são tabelas (D3-A), e a
 * `Idempotency-Key` do `PATCH /painel/produtos/:id` também (KAM-240), num *pool*
 * só seu (`IdempotenciaNaBase`).
 *
 * **O guia do ES corre sobre a base e sobre o lote** (KAM-239). O estado dele
 * vive na `onboarding_guia` (revisão do guia na base), pela mesma ligação
 * `kamba_app`. A reserva da lista de espera, as quatro da lista, os dois *gates* e
 * a abertura na fila de revisão correm como `kamba_batch` **no processo de lote**,
 * que este processo chama pela rota interna dele (`ONBOARDING_LOTE_INTERNO_URL`,
 * com a credencial `onboarding_lote_token`; decisão do fundador de 2026-11-22,
 * A). Este processo continua sem ligação `kamba_batch` (D2-A do KAM-236). A volta
 * dos 30 minutos e a da lista também passaram ao lote. Em `prod`, com o guia
 * configurado e sem a rota interna, o arranque recusa (`LoteEmFaltaEmProducaoError`).
 *
 * **E o arranque em `prod` continua a recusar**, agora por outra razão
 * (`SmsFalsoEmProducaoError`): o SMS do OTP é o `FakeSmsProvider` em todos os
 * ambientes, porque não há adaptador de agregador real. Os repositórios já não
 * são o motivo; o fornecedor de SMS é. Fica assim até ao agregador (KAM-116),
 * por decisão da coordenação de 2026-11-22 (C1, no bloco do KAM-236).
 *
 * Em `dev` e `staging` sem a ligação, arranca sobre memória, e é o que torna o
 * fluxo exercitável ponta a ponta com o `FakeSmsProvider` (critério 8 do
 * KAM-116). Com a ligação, usa a base como em `prod`.
 *
 * ## O que ele lê do cofre, e o que faz se não estiver lá
 *
 * Os dois segredos do `inscricao/refs.ts`, com anel. São **obrigatórios**: sem
 * eles não há como assinar um convite nem cunhar um `nif_hmac`, e um serviço de
 * registo sem isso não serve pedidos — que é exactamente a regra 1 do
 * `Secrets.arrancar`.
 */

import { serve } from "@hono/node-server";
import pg from "pg";
import { port } from "@kamba/core-ts";
import {
  ConversaDoDono,
  conversaPeloPool,
  FotoDoDono,
  invocadorPorHttp,
  recepcaoDoPainel,
  trocaPeloPool,
  type DestinoDoAviso,
  type MomentoDoAviso,
} from "@kamba/core-ts/dono";
import { EnvKeyProvider, Identidade } from "@kamba/core-ts/identity";
import { AvisosDaListaEmMemoria, ListaDeEspera, ListaEmMemoria, MetricasDaLista } from "@kamba/core-ts/capacidade";
import {
  AvisosEmMemoria,
  GatesEmMemoria,
  GuiaEmMemoria,
  PassoGuiado,
  RevisaoEmMemoria,
  guiaNaBase,
  type RepositorioDoGuia,
} from "@kamba/core-ts/guia";
import {
  Actividade,
  AntiAbuso,
  CasosEmMemoria,
  ContadoresEmMemoria,
  Otp,
  OtpEmMemoria,
  OtpPorSmsLocal,
  REFERENCIAS,
  REF_KEK_DO_TELEFONE,
  Registo,
  anelDaAssinatura,
  anelDoPepper,
  anelDosDados,
  casosNaBase,
  cifraDoCaso,
  contadoresNaBase,
  lerAnelDoTelefone,
  otpNaBase,
  type Contadores,
  type RepositorioDeCasos,
  type RepositorioDeOtp,
} from "@kamba/core-ts/inscricao";
import { instalar } from "@kamba/core-ts/logger";
import { versaoDaGraph } from "@kamba/core-ts/onboarding";
import { ArranqueAbortadoError, EnvSecretProvider, Secrets, isAmbiente } from "@kamba/core-ts/secrets";
import {
  criarStorageS3,
  lerConfig as lerConfigDoStorage,
  type StorageConfig,
  type StorageProvider,
} from "@kamba/core-ts/storage";
import {
  FakeSmsProvider,
  REF_PEPPER as REF_PEPPER_DO_SMS,
  anelDoPepper as anelDoPepperDoSms,
} from "@kamba/core-ts/sms";

import { createApp } from "./app.ts";
import { exigirComunicacaoLimpa } from "./comunicacao.ts";
import type { OpcoesDoGuia } from "./guia.ts";
import { ClienteDoLote, portasDoGuia } from "./guia_pelo_lote.ts";
import { REF_DA_CREDENCIAL_DO_LOTE } from "./lote/interno.ts";
import { LigadorPorHttp } from "./ligador.ts";
import { CanalPeloCom } from "./painel/canal.ts";
import { ComercioPorHttp } from "./painel/comercio.ts";
import type {
  OpcoesDaConversa,
  OpcoesDaFoto,
  OpcoesDaTroca,
  OpcoesDoPainel,
  TesteDoPainel,
} from "./painel/rotas.ts";
import { IdempotenciaNaBase } from "./painel/idempotencia_sql.ts";
import { RevogacoesNaBase } from "./painel/revogacoes_sql.ts";
import { RevogacoesEmMemoria, type Revogacoes } from "./painel/sessao.ts";
import { testeDaActivacao } from "./painel/teste.ts";
import { precoMaximoKz } from "./painel/validacao.ts";
import { DEFAULT_PORT, SERVICE } from "./meta.ts";
import { paginaDeRegisto } from "./pagina.ts";

// Antes de tudo o resto: a partir daqui, um erro por tratar sai como uma linha
// sem conteúdo, e não como a pilha com a mensagem no `stderr` (KAM-068).
const log = instalar(SERVICE);

const VARIAVEL_DO_AMBIENTE = "KAMBA_AMBIENTE";

/**
 * A ligação à base do `kamba_identity` (KAM-217). **Opcional, como a do COM**:
 * sem ela, as duas rotas da troca de telefone respondem 503 e o resto do painel
 * serve igual. Com ela, a troca monta sobre os adaptadores do KAM-211, e as duas
 * chaves do contacto passam a obrigatórias no arranque (ver `obrigatorios`).
 */
const VARIAVEL_DA_IDENTIDADE = "ONBOARDING_IDENTITY_DB_URL";
const URL_DA_IDENTIDADE = (process.env[VARIAVEL_DA_IDENTIDADE] ?? "").trim();

/**
 * As chaves do contacto que o `resolveContact` usa: o *pepper* do HMAC e a KEK
 * das DEK. **Obrigatórias só com a troca ligada**, e verificadas no arranque:
 * o `Identidade.arrancar` confere o `KAMBA_ENV` e não lê chave nenhuma, pelo que
 * sem isto o processo subia e o primeiro dono a acertar o código gastava-o e
 * recebia um 500 (achado 5 da revisão adversarial do KAM-217).
 */
const CHAVES_DA_TROCA = ["pepper_contact_hmac", "kek_contact_dek"] as const;

/**
 * A conversa do dono com o Assistente (KAM-223): a ligação `kamba_app` e o AGR.
 * **Opcionais, e só as duas juntas a montam**: sem elas, as duas rotas da
 * conversa respondem 503 e o resto do painel serve igual. Com elas, a
 * credencial `agr_painel_token` é obrigatória no arranque.
 *
 * A ligação é a segunda deste processo, e é de outro papel: o `kamba_identity`
 * não lê `tenants` nem `tenant_channels` (invariante do KAM-008), e a conversa
 * precisa do `owner_contact_id` e do canal (decisão 1 do fundador, bloco do
 * KAM-217).
 */
const VARIAVEL_DA_APP = "ONBOARDING_APP_DB_URL";
const URL_DA_APP = (process.env[VARIAVEL_DA_APP] ?? "").trim();
const URL_DO_AGR = (process.env["KAMBA_AGR_URL"] ?? "").trim();

/**
 * O COM interno do painel (KAM-099). **Sem ele o painel não monta**, e com ele
 * nem a troca nem a conversa: as chaves que só elas usam não se exigem no
 * arranque. Até ao KAM-223 a troca exigia as chaves do contacto com a cadeia do
 * `kamba_identity` só, e em `dev` a cadeia está sempre definida — pelo que o
 * serviço do compose não subia sem uma KEK que nenhuma rota montada usava.
 */
const URL_DO_COM = (process.env["ONBOARDING_COM_INTERNO_URL"] ?? "").trim();
const TROCA_MONTA = URL_DO_COM !== "" && URL_DA_IDENTIDADE !== "";
const CONVERSA_MONTA = URL_DO_COM !== "" && URL_DA_APP !== "" && URL_DO_AGR !== "";

/**
 * A credencial **do painel** no AGR, e não a do *shim*: quem tem o
 * `agr_internal_token` corre o turno de qualquer contacto, e o AGR só aceita
 * esta num turno do dono com `message_id`. Uma credencial por chamador.
 */
const SEGREDO_DO_AGR = "agr_painel_token";
const VARIAVEL_DOS_PROXIES = "ONBOARDING_PROXIES_DE_CONFIANCA";

/**
 * As duas chaves do STO, para a foto do dono pelo painel (KAM-243). Pela forma
 * da decisão do fundador de 2026-11-21 para o `worker-canal-entrada` e o AGR
 * (P4, opção A): o processo recebe só os segredos de que precisa, e em
 * `staging` e `prod` **não arranca** sem eles nem sem a configuração do STO
 * (`KAMBA_STORAGE_*`). Em `dev`, sem eles, a foto fica desligada (503) e o
 * arranque di-lo numa linha. Quem as tem lê e escreve os objectos de todos os
 * tenants: o isolamento é o prefixo do tenant na porta (`ArmazenamentoPorTenant`).
 */
const SEGREDOS_DO_STO = ["storage_access_key_id", "storage_secret_access_key"] as const;

/**
 * As quatro variáveis do passo guiado do ES (KAM-093). **Nenhuma é segredo**: o
 * `appId` e o `config_id` são identificadores públicos que a página entrega ao
 * SDK da Meta, a origem é o endereço público deste serviço, e o GWY interno é
 * um endereço da rede do compose.
 */
const VARIAVEIS_DO_GUIA = {
  appId: "KAMBA_META_APP_ID",
  configId: "KAMBA_META_ES_CONFIG_ID",
  origem: "ONBOARDING_ORIGEM",
  gwy: "ONBOARDING_GWY_INTERNO_URL",
} as const;

/**
 * A rota interna do processo de lote (KAM-239): a lista, os *gates* e a fila do
 * guia, como `kamba_batch`. **Opcional fora de `prod`**: sem ela, o guia corre
 * sobre os duplos em memória, como antes. Com ela, o estado do guia vai para a
 * base, e a credencial do lote passa a obrigatória no arranque.
 */
const VARIAVEL_DO_LOTE = "ONBOARDING_LOTE_INTERNO_URL";
const URL_DO_LOTE = (process.env[VARIAVEL_DO_LOTE] ?? "").trim().replace(/\/+$/, "");
const GUIA_PELO_LOTE = URL_DO_LOTE !== "";

/**
 * A KEK do NIF e do e-mail do caso (`nif_enc`, `email_enc`). Ver o
 * `@kamba/core-ts/inscricao` (`dados_do_caso.ts`).
 */
const REF_KEK_DOS_DADOS = "kek_dados_do_caso";

/** As duas KEK do caso, obrigatórias quando o registo corre sobre a base. */
const CHAVES_DO_CASO = [REF_KEK_DO_TELEFONE, REF_KEK_DOS_DADOS] as const;

/**
 * Quantas ligações do `kamba_app` o registo, o OTP, os contadores e as
 * revogações abrem, no máximo. ***Proposta***: cada operação usa uma, por
 * pouco tempo, e o tráfego do Piloto é de dezenas de registos por dia.
 * Calibra-se com a carga real (KAM-084).
 */
const LIGACOES_DA_INSCRICAO = 6;

/**
 * Quantas ligações do `kamba_app` a idempotência do painel abre, no máximo
 * (KAM-240). **À parte da inscrição**: cada uma fica presa durante o PATCH ao
 * COM, que lê as revogações pelo *pool* da inscrição (ver `IdempotenciaNaBase`).
 * ***Proposta***: quatro PATCH em curso ao mesmo tempo; o quinto espera pela
 * ligação até ao `connectionTimeoutMillis`. Calibra-se com a carga real (KAM-084).
 */
const LIGACOES_DA_IDEMPOTENCIA = 4;

/**
 * Levantado em `prod` enquanto o SMS for o `FakeSmsProvider` (KAM-236, achado 1
 * da revisão adversarial). **Não há adaptador de agregador real** (KAM-116: «não
 * há agregador escolhido»), e o `../../packages/core-ts/src/sms/fake.ts` promete
 * que o falso nunca corre em `prod`. Com o registo na base, `prod` arrancava:
 * o `Otp.enviar` dizia «enviado», nenhum SMS saía, os códigos ficavam em claro
 * na memória do processo e cada caso parava em `otp_pendente`. Falha fechado até
 * haver um fornecedor real ligado aqui.
 */
export class SmsFalsoEmProducaoError extends Error {
  override readonly name = "SmsFalsoEmProducaoError";

  constructor() {
    super(
      "o onboarding-web nao arranca em prod com o FakeSmsProvider: nao ha adaptador de " +
        "agregador de SMS real, e o OTP do registo e da reentrada nao chegava a ninguem",
    );
  }
}

/** Levantado em `prod` sem a ligação da aplicação. Ver a nota do módulo. */
export class BaseEmFaltaEmProducaoError extends Error {
  override readonly name = "BaseEmFaltaEmProducaoError";

  constructor() {
    super(
      `o onboarding-web nao arranca em prod sem a ${VARIAVEL_DA_APP}: o registo, o OTP, os ` +
        "contadores e as revogacoes do painel vivem na base, e em memoria perdiam-se no reinicio",
    );
  }
}

function exigir(nome: string): string {
  const valor = process.env[nome];
  if (valor === undefined || valor.trim() === "") {
    throw new Error(`falta a variavel de ambiente ${nome}`);
  }
  return valor;
}

/** O ambiente do cofre. Sem omissão silenciosa para `dev`: ver `secrets/port.ts`. */
function ambiente(): "dev" | "staging" | "prod" {
  const bruto = exigir(VARIAVEL_DO_AMBIENTE).trim();
  if (!isAmbiente(bruto)) throw new Error(`${VARIAVEL_DO_AMBIENTE} invalida`);
  return bruto;
}

/**
 * Quantos *proxies* de confiança há à frente. **Zero por omissão.**
 *
 * Ver a nota do `./rotas.ts`: ler o `X-Forwarded-For` sem saber quantos saltos
 * de confiança existem é deixar o atacante escolher o seu próprio balde de
 * limite. A omissão é a leitura segura, e quem põe o serviço atrás de um
 * balanceador declara o número.
 */
function proxiesDeConfianca(): number {
  const bruto = (process.env[VARIAVEL_DOS_PROXIES] ?? "").trim();
  if (bruto === "") return 0;
  const valor = Number(bruto);
  if (!Number.isInteger(valor) || valor < 0 || valor > 8) {
    throw new Error(`${VARIAVEL_DOS_PROXIES} invalida`);
  }
  return valor;
}

const env = ambiente();
/** O registo corre sobre a base: sempre em `prod`, e em `dev` e `staging` com a ligação. */
const NA_BASE = URL_DA_APP !== "";
if (env === "prod" && !NA_BASE) throw new BaseEmFaltaEmProducaoError();
// O guia pelo lote tem o estado na base: sem a ligação da aplicação, não há onde.
if (GUIA_PELO_LOTE && !NA_BASE) {
  throw new Error(`a ${VARIAVEL_DO_LOTE} pede a ${VARIAVEL_DA_APP}: o estado do guia vive na base`);
}
// O SMS é o falso em qualquer ambiente (ver o erro): em `prod`, recusa.
if (env === "prod") throw new SmsFalsoEmProducaoError();

/** O STO é obrigatório fora de `dev` (KAM-243). Ver `SEGREDOS_DO_STO`. */
const STO_OBRIGATORIO = env !== "dev";

const provider = new EnvSecretProvider({ ambiente: env });
const secrets = await Secrets.arrancar({
  servico: SERVICE,
  provider,
  // Os dois da inscricao **e** o *pepper* do destino do SMS: este processo e o
  // que liga a porta do KAM-116 ao `OtpProvider` (`sms_local`), e sem o *pepper*
  // nao ha como cunhar um `Destino` — isto e, nao ha OTP. O inventario declara-o
  // com `obrigatorio_em: []` porque nenhum **outro** servico o pede; a lista de
  // arranque de quem o usa e que o torna obrigatorio aqui.
  obrigatorios: [
    ...REFERENCIAS,
    REF_PEPPER_DO_SMS,
    ...(TROCA_MONTA ? CHAVES_DA_TROCA : []),
    ...(CONVERSA_MONTA ? [SEGREDO_DO_AGR] : []),
    ...(NA_BASE ? CHAVES_DO_CASO : []),
    ...(GUIA_PELO_LOTE ? [REF_DA_CREDENCIAL_DO_LOTE] : []),
    ...(STO_OBRIGATORIO ? SEGREDOS_DO_STO : []),
  ],
});

/**
 * O STO da foto do dono (KAM-243), ou `undefined` em `dev` sem ele. Em `staging`
 * e `prod`, a configuração em falta **aborta** o arranque — as chaves já
 * abortaram no `Secrets.arrancar` acima. A mensagem do `lerConfig` nomeia as
 * variáveis e nunca os valores.
 */
async function montarArmazenamento(): Promise<StorageProvider | undefined> {
  let config: StorageConfig;
  try {
    config = lerConfigDoStorage({ ambiente: env, env: process.env });
  } catch (erro) {
    if (STO_OBRIGATORIO) {
      const motivo = erro instanceof Error ? erro.message : "configuracao ilegivel";
      throw new ArranqueAbortadoError(SERVICE, `armazenamento da foto do painel: ${motivo}`);
    }
    log.info({ outcome: "painel_foto_desligada" });
    return undefined;
  }
  if (!STO_OBRIGATORIO) {
    // Em `dev` nada disto é obrigatório no arranque, e por isso pergunta-se aqui:
    // um processo que montasse a foto sem as chaves falhava a primeira foto do
    // dono em vez de arrancar sem ela.
    // Os nomes em literal, e não pelo `SEGREDOS_DO_STO`: o inventário (gate 9)
    // lê os pedidos de segredo pelo nome escrito.
    const presentes = await Promise.all(
      [secrets.getRing("storage_access_key_id"), secrets.getRing("storage_secret_access_key")].map((leitura) =>
        leitura.then(() => true, () => false),
      ),
    );
    if (presentes.includes(false)) {
      log.info({ outcome: "painel_foto_desligada" });
      return undefined;
    }
  }
  return criarStorageS3({ config, secrets });
}

const armazenamento = await montarArmazenamento();

const [pepper, pepperAnterior] = await anelDoPepper(secrets);
const [assinatura, assinaturaAnterior] = await anelDaAssinatura(secrets);
// O *pepper* do destino do SMS é do KAM-116 e é **outro**: ele cunha o endereço
// dentro do agregador, e o da inscrição cunha a pessoa dentro do onboarding. O
// argumento está no cabeçalho do `sms/destino.ts`.
// **Pelo `provider` e não pelo `secrets`**, e a assimetria é do KAM-116 e não
// deste ficheiro: o `anelDoPepper` do módulo `sms/` recebe uma `SecretProvider`
// inteira, e o `Secrets` não é uma (tem `get` e `getRing`, não tem `nome` nem
// `health`). A leitura é a mesma fonte, e o `Secrets.arrancar` acima já provou
// que este segredo existe — está na lista de obrigatórios.
const [pepperDoDestino] = await anelDoPepperDoSms(provider);

/**
 * O *pool* do registo: o caso, o desafio do OTP, os contadores e as revogações,
 * como `kamba_app`. Só com a ligação; ver a nota do módulo.
 */
const poolDaInscricao = NA_BASE ? poolDe(URL_DA_APP, "inscricao", LIGACOES_DA_INSCRICAO) : null;

const casos: RepositorioDeCasos =
  poolDaInscricao === null
    ? new CasosEmMemoria()
    : casosNaBase({
        pool: poolDaInscricao,
        cifra: cifraDoCaso(
          await lerAnelDoTelefone(secrets),
          anelDosDados(REF_KEK_DOS_DADOS, await secrets.getRing(REF_KEK_DOS_DADOS)),
        ),
        anelDoPepper: [pepper, pepperAnterior],
      });
const contadores: Contadores = poolDaInscricao === null ? new ContadoresEmMemoria() : contadoresNaBase(poolDaInscricao);
const repositorioDoOtp: RepositorioDeOtp = poolDaInscricao === null ? new OtpEmMemoria() : otpNaBase(poolDaInscricao);
const revogacoes: Revogacoes =
  poolDaInscricao === null ? new RevogacoesEmMemoria() : new RevogacoesNaBase(poolDaInscricao);
log.info({ outcome: NA_BASE ? "registo_na_base" : "registo_em_memoria" });
const antiabuso = new AntiAbuso({ contadores, chave: pepper });
// O `FakeSmsProvider` é o que `staging` usa, por decisão do critério 8 do
// KAM-116: **não há agregador escolhido** e escrever um adaptador para um
// agregador hipotético era inventar a API dele.
const provedorDoOtp = new OtpPorSmsLocal({ sms: new FakeSmsProvider(), pepperDoDestino });
const alertaDoOtp = (motivo: string): void => log.error({ outcome: motivo, error_code: motivo });
const otp = new Otp({
  repositorio: repositorioDoOtp,
  contadores,
  provedor: provedorDoOtp,
  chave: pepper,
  alerta: alertaDoOtp,
});
const registo = new Registo({
  repositorio: casos,
  // **Sem `contadores`**: o `Registo` nao os toca. As duas quotas que ele
  // consome — rede e dispositivo — passam pelo `AntiAbuso`, e as do OTP pelo
  // `Otp`; cada um deles ja recebeu os seus acima. Passar o mapa aqui era uma
  // terceira via para o mesmo estado, e o `OpcoesDeRegisto` recusa-a.
  antiabuso,
  otp,
  // O anel inteiro: a actual escreve, as duas procuram. Ver `hmacsDoAnel`.
  anelDoPepper: [pepper, pepperAnterior],
  anelDoToken: [assinatura, assinaturaAnterior],
  anelDaSessao: [assinatura, assinaturaAnterior],
});
const actividade = new Actividade({ repositorio: casos, contadores });

/**
 * O passo guiado do ES, **só se as quatro variáveis estiverem**.
 *
 * Sem uma app da Meta não há popup a abrir, e o `dev` da maioria das máquinas
 * não tem uma. Montar a página sem ela era servir um botão que falha no
 * navegador; não a montar é a página dar 404, e o arranque di-lo numa linha.
 * Com a rota interna do lote, o estado vive na base e a lista, os *gates* e a
 * fila correm no lote (KAM-239); sem ela, fora de `prod`, em memória. O aviso
 * ao dono continua em memória (o canal é do KAM-115), e o detector de pagamento
 * responde `desconhecido`, que deixa o `meta_pagamento` vermelho: **não há fonte
 * CONFIRMADA** de que a Graph diga se o WABA tem cartão antes do primeiro envio
 * (credor: KAM-023 / ext:KAM-102).
 */
/**
 * O estado do guia, partilhado com a troca de telefone (KAM-216): o
 * `numeroConfirmado` é o que diz que o número da loja é o telefone do caso. **Na
 * base com o lote** (KAM-239), pela ligação do registo; em memória sem ele.
 */
const repositorioDoGuia: RepositorioDoGuia =
  GUIA_PELO_LOTE && poolDaInscricao !== null ? guiaNaBase({ pool: poolDaInscricao }) : new GuiaEmMemoria();

/** O cliente da rota interna do lote, só com ela. A credencial lê-se a cada pedido: roda. */
const clienteDoLote = GUIA_PELO_LOTE
  ? new ClienteDoLote({ base: URL_DO_LOTE, credencial: () => secrets.get(REF_DA_CREDENCIAL_DO_LOTE) })
  : null;

function montarGuia(): OpcoesDoGuia | undefined {
  const valores = Object.fromEntries(
    Object.entries(VARIAVEIS_DO_GUIA).map(([chave, nome]) => [chave, (process.env[nome] ?? "").trim()]),
  ) as Record<keyof typeof VARIAVEIS_DO_GUIA, string>;
  if (Object.values(valores).some((v) => v === "")) {
    log.info({ outcome: "es_guia_desligado" });
    return undefined;
  }
  // **A lista (KAM-095), os dois *gates* e a fila** correm como `kamba_batch`
  // no processo de lote, pela rota interna dele (KAM-239). Sem a rota, em `dev`
  // e `staging`, em memória: o limite em memória é o 10 CONFIRMADO, e a origem
  // dele está na `onboarding_capacity` da base. Em `prod`, sem a rota, recusa.
  const portas = portasDoGuia({
    ambiente: env,
    lote: clienteDoLote,
    emMemoria: () => ({
      lista: new ListaDeEspera({
        repositorio: new ListaEmMemoria(casos),
        aviso: new AvisosDaListaEmMemoria(),
        origem: valores.origem,
        metricas: new MetricasDaLista(),
        log,
      }),
      gates: new GatesEmMemoria(),
      revisao: new RevisaoEmMemoria(),
    }),
  });
  const lista = portas.lista;
  log.info({ outcome: portas.voltaNoProcesso ? "es_guia_em_memoria" : "es_guia_pelo_lote" });
  const guia = new PassoGuiado({
    casos,
    repositorio: repositorioDoGuia,
    capacidade: lista,
    ligador: new LigadorPorHttp(valores.gwy),
    gates: portas.gates,
    revisao: portas.revisao,
    pagamento: { verificar: async () => "desconhecido" },
    aviso: new AvisosEmMemoria(),
    anelDoPepper: [pepper, pepperAnterior],
    chaveDaAssinatura: assinatura,
    origem: valores.origem,
    configId: valores.configId,
    log,
  });
  // O temporizador dos 30 min (critério 5), **só com as portas em memória**:
  // pelo lote, a volta corre no `onboarding-lote`, uma vez e não uma por réplica
  // (`CicloDoGuia`, KAM-239). Um por minuto basta: o prazo é de meia hora.
  const listaDaVolta = portas.lista instanceof ListaDeEspera ? portas.lista : undefined;
  if (portas.voltaNoProcesso && listaDaVolta !== undefined) {
    setInterval(() => {
      guia.abandonarVencidos().catch((erro: unknown) => log.excepcao(erro, "abandono_falhou"));
      // Os convites vencidos e a promocao (criterios 4 e 5). Um minuto de erro
      // num prazo de 48 h.
      listaDaVolta
        .expirarVencidos()
        .then(() => listaDaVolta.promover())
        .then(() => listaDaVolta.medir())
        .catch((erro: unknown) => log.excepcao(erro, "lista_espera_falhou"));
    }, 60_000).unref();
  }
  return {
    guia,
    lista,
    registo,
    otp,
    anelDaAssinatura: [assinatura, assinaturaAnterior],
    appIdDaMeta: valores.appId,
    versaoDaGraph: versaoDaGraph(),
  };
}

/**
 * Quantas ligações do `kamba_identity` o processo abre, no máximo. ***Proposta***:
 * uma troca usa duas, uma de cada vez (o contacto e a porta), e o painel é de
 * donos, que são poucos. Calibra-se com a carga real (KAM-084).
 */
const LIGACOES_DA_IDENTIDADE = 4;

/** As ligações do teste do painel (KAM-202): um clique por dono, e curto. *Proposta*. */
const LIGACOES_DO_TESTE = 2;

/**
 * O registo de um aviso da troca (ganchos `DESTINOS_DO_AVISO` do KAM-118). **Não
 * entrega nada**: o aviso ao número antigo e ao e-mail é do KAM-115, que ainda
 * não tem canal. Fica uma linha por destino, sem tenant nem número, para que um
 * aviso por entregar se veja, em vez de se perder em silêncio.
 */
const AVISO_POR_ENTREGAR: Record<DestinoDoAviso, string> = {
  numero_antigo: "painel_troca_aviso_numero_antigo_por_entregar",
  email: "painel_troca_aviso_email_por_entregar",
};

/**
 * O momento do aviso vai no `error_code`, que a *allowlist* aceita como
 * identificador: `pendente` (a espera das 72 h abriu), `feita` ou `cancelada`.
 */
const MOMENTO_DO_AVISO: Record<MomentoDoAviso, string> = {
  pendente: "troca_pendente",
  feita: "troca_feita",
  cancelada: "troca_cancelada",
};

/** Um *pool* `pg` com os dois ouvintes de `error` (ver o `montarTroca`). */
function poolDe(url: string, nome: string, ligacoes: number): pg.Pool {
  const pool = new pg.Pool({
    connectionString: url,
    max: ligacoes,
    // ***Proposta***: uma base que não responde dá erro ao fim de 5 s, e o
    // pedido recebe-o, em vez de ficar pendurado à espera de ligação.
    connectionTimeoutMillis: 5_000,
    application_name: `onboarding-web:${nome}`,
  });
  // Uma ligação que cai não pode derrubar o processo, e há dois sítios onde
  // ela cai. **Inactiva**: o `pg` emite `error` no *pool*. **Emprestada**: o
  // *pool* tira o seu ouvinte enquanto a empresta, e o `error` sai do cliente;
  // sem ouvinte, é uma excepção por tratar e o processo sai — e com ele os pedidos
  // em curso. O ouvinte de cada cliente põe-se quando ele nasce (achado 7 da
  // revisão adversarial do KAM-217); a instrução em curso falha na mesma.
  pool.on("error", (erro) => log.excepcao(erro, `${nome}_bd_falhou`));
  pool.on("connect", (cliente) => {
    cliente.on("error", (erro) => log.excepcao(erro, `${nome}_bd_falhou`));
  });
  return pool;
}

/**
 * A troca de telefone do dono (KAM-211), **só se a ligação do `kamba_identity`
 * estiver configurada**.
 *
 * O contacto do número novo resolve-se pelo `resolveContact` do KAM-008, e o
 * papel move-se pela `platform.definir_dono`, os dois como `kamba_identity` e
 * com uma ligação do *pool* por operação (`trocaPeloPool`): o servidor atende
 * pedidos concorrentes, e sobre uma ligação partilhada o `tenant_guard` recusava
 * a segunda troca enquanto a primeira corria. As chaves do contacto são as do
 * `EnvKeyProvider`, como no CHR,
 * e o `Identidade.arrancar` recusa-as se o `KAMBA_ENV` não for este ambiente.
 *
 * **O estado da troca vive na base** (KAM-223, revisão `0077`): a troca, o
 * prazo das 72 h e o desafio do OTP de cada número, na `owner_phone_changes`.
 * O `Otp` de cada operação é montado sobre o desafio dessa troca, com os
 * contadores, o fornecedor e a chave deste processo — os limites por destino e o
 * orçamento diário são os mesmos do registo. Com o registo na base (KAM-236),
 * os contadores também lá estão, e duas réplicas partilham o orçamento; sem a
 * ligação da aplicação, ficam em memória por processo.
 */
async function montarTroca(guiaMontado: boolean): Promise<OpcoesDaTroca | undefined> {
  if (URL_DA_IDENTIDADE === "") {
    log.info({ outcome: "painel_troca_desligada" });
    return undefined;
  }
  const identidade = await Identidade.arrancar({ chaves: new EnvKeyProvider({ ambiente: env }) });
  const pool = poolDe(URL_DA_IDENTIDADE, "identidade", LIGACOES_DA_IDENTIDADE);
  return {
    troca: trocaPeloPool({
      pool,
      identidade,
      otp: (repositorio) =>
        new Otp({ repositorio, contadores, provedor: provedorDoOtp, chave: pepper, alerta: alertaDoOtp }),
      // **Não entrega nada** (KAM-115 sem canal): a espera das 72 h não avisa
      // ninguém até lá, e o bloco do KAM-223 di-lo.
      avisar: async ({ destino, momento }) => {
        log.info({ outcome: AVISO_POR_ENTREGAR[destino], error_code: MOMENTO_DO_AVISO[momento] });
      },
    }),
    anelDoPepper: [pepper, pepperAnterior],
    contadores,
    proxiesDeConfianca: proxiesDeConfianca(),
    // Sem o guia montado, nenhum número da loja foi confirmado: a troca guarda o
    // painel (KAM-216).
    numeroDaLojaConfirmado: guiaMontado
      ? async (casoId) => (await repositorioDoGuia.ler(casoId))?.numeroConfirmado === true
      : undefined,
  };
}

/** Quantas ligações do `kamba_app` a conversa abre. ***Proposta***, pela razão da identidade. */
const LIGACOES_DA_APP = 4;

/**
 * A conversa do dono com o Assistente (KAM-223), **só com a ligação `kamba_app`
 * e o endereço do AGR**. A credencial lê-se a cada pedido, porque roda.
 */
async function montarConversa(): Promise<{ conversa?: OpcoesDaConversa; foto?: OpcoesDaFoto }> {
  if (URL_DA_APP === "" || URL_DO_AGR === "") {
    log.info({ outcome: "painel_conversa_desligada" });
    return {};
  }
  const pool = poolDe(URL_DA_APP, "app", LIGACOES_DA_APP);
  const portas = conversaPeloPool(pool);
  const invocar = invocadorPorHttp({ agr: URL_DO_AGR, credencial: () => secrets.get("agr_painel_token") });
  // KAM-243: a foto do dono vai pelo mesmo *pool*, o mesmo contexto do dono e a
  // mesma credencial do AGR, e precisa do STO. Sem ele (só em `dev`), a rota da
  // foto responde 503 e a conversa serve igual.
  const foto: OpcoesDaFoto | undefined =
    armazenamento === undefined
      ? undefined
      : {
          foto: new FotoDoDono({
            contexto: portas.contexto,
            receber: recepcaoDoPainel({ pool, armazenamento, log }),
            invocar,
          }),
        };
  return {
    conversa: { conversa: new ConversaDoDono({ ...portas, invocar }) },
    ...(foto === undefined ? {} : { foto }),
  };
}

/**
 * O painel do dono (KAM-099), **só se o COM interno estiver configurado**.
 *
 * Sem o endereço da API interna do COM não há onde ler nem gravar o catálogo, e
 * montar o painel era servir uma página que falha no primeiro pedido. Com ele,
 * a credencial `com_internal_token` é obrigatória: sem ela o arranque **falha**
 * (o `get` do cofre lança), em vez de subir um painel que responde 503 a tudo.
 *
 * O estado do canal vem do COM (`CanalPeloCom`, KAM-190), pela mesma credencial:
 * as ligações deste processo à base são duas, cada uma só para a sua rota: a do
 * `kamba_identity` para a troca de telefone (`montarTroca`, KAM-217) e a do
 * `kamba_app` para a conversa do dono (`montarConversa`, KAM-223). O canal do dono
 * que a troca guarda (KAM-216) volta pelo `channel-view`, na linha do canal. A reentrada por código usa o
 * mesmo `Otp`, os mesmos casos e os mesmos contadores do registo — um telefone
 * esgotado no registo está esgotado aqui.
 *
 * A religação de um caso activo (KAM-207) é a do guia montado: sem o guia, o
 * painel não a oferece e o caso activo tem o 409 de antes.
 */
async function montarPainel(guia: PassoGuiado | undefined): Promise<OpcoesDoPainel | undefined> {
  const com = URL_DO_COM;
  if (com === "") {
    log.info({ outcome: "painel_desligado" });
    return undefined;
  }
  const comercio = new ComercioPorHttp(com, await secrets.get("com_internal_token"));
  const { conversa, foto } = await montarConversa();
  return {
    comercio,
    canal: new CanalPeloCom(comercio),
    revogacoes,
    casos,
    anelDaAssinatura: [assinatura, assinaturaAnterior],
    // Sem base, a das rotas, em memória: só em `dev` e `staging` (em `prod` a
    // base é obrigatória). Ver a nota do módulo.
    idempotencia: NA_BASE ? new IdempotenciaNaBase(poolDe(URL_DA_APP, "idempotencia", LIGACOES_DA_IDEMPOTENCIA)) : undefined,
    precoMaximoKz: precoMaximoKz(process.env["PAINEL_PRECO_MAXIMO_KZ"]),
    reentrada: {
      otp,
      telefoneDoCaso: (id) => registo.telefoneDoCaso(id),
      casosPorTelefone: (hmac) => casos.porTelefoneHmac(hmac),
      anelDoPepper: [pepper, pepperAnterior],
      contadores,
      proxiesDeConfianca: proxiesDeConfianca(),
      religar: guia === undefined ? undefined : (id) => guia.religar(id),
    },
    troca: await montarTroca(guia !== undefined),
    conversa,
    foto,
    teste: montarTeste(),
  };
}

/**
 * O teste ponta a ponta do painel (KAM-202, critério 2), **só com a ligação
 * `kamba_app`** (a `ONBOARDING_APP_DB_URL` da conversa do KAM-223), num conjunto
 * próprio e pequeno: a página do dono abre a tentativa por ela. Sem ela, o
 * `POST /painel/teste` responde 503 e o resto do painel serve igual. Em `prod` a
 * ligação é obrigatória (KAM-236), e o caso que a sessão do painel lê está na
 * base: um reinício não perde a tentativa aberta nem o caso. A rota fica provada
 * contra a base em `packages/core-ts/tests_bd/activacao.bd.test.ts`, e o
 * reinício em `packages/core-ts/tests_bd/inscricao.bd.test.ts`.
 */
function montarTeste(): TesteDoPainel | undefined {
  if (URL_DA_APP === "") {
    log.info({ outcome: "painel_teste_desligado" });
    return undefined;
  }
  return testeDaActivacao(poolDe(URL_DA_APP, "teste", LIGACOES_DO_TESTE));
}

// **A política de comunicação verifica-se no arranque**, e não só por resposta:
// um serviço que suba com o texto errado mostra-o a um dono antes de alguém
// notar. Falha fechado — ver `./comunicacao.ts`.
exigirComunicacaoLimpa(
  paginaDeRegisto({ desafio: "x.1.1.y", dificuldade: 1, nonce: "0".repeat(24), chave: "0".repeat(24), token: "" }),
);

const hostname = process.env.HOST?.trim() || "127.0.0.1";
const listenPort = port(DEFAULT_PORT);

// **A consola da fila de revisão (KAM-196) não se monta aqui**, e não é
// esquecimento: ela só existe atrás da identidade da equipa com MFA, e o IdP
// que a serve não está escolhido — a escolha e as contas de staff são do
// fundador (critério 1 do bloco). O único IdP que existe é o falso dos ensaios,
// que não entra num processo. Montá-la sem ele era uma porta para os dados de
// todos os onboardings; o arranque di-lo numa linha.
log.info({ outcome: "equipa_desligada" });

const opcoesDoGuia = montarGuia();
const app = createApp(log, {
  registo,
  otp,
  actividade,
  antiabuso,
  anelDaAssinatura: [assinatura, assinaturaAnterior],
  anelDoToken: [assinatura, assinaturaAnterior],
  proxiesDeConfianca: proxiesDeConfianca(),
}, opcoesDoGuia, await montarPainel(opcoesDoGuia?.guia));

serve({ fetch: app.fetch, hostname, port: listenPort }, () => {
  // O anfitrião e a porta não estão na *allowlist* de `docs/tecnica/08` §7.3,
  // e por isso não saem: quem os quer saber lê a configuração do contentor.
  log.info({ outcome: "service_started" });
});
