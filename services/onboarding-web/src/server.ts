/**
 * Arranque do onboarding-web.
 *
 * Escuta em `127.0.0.1` por omissão. Dentro de um contentor é preciso escutar em
 * `0.0.0.0` para que a rede do compose chegue ao processo, e é por isso que o
 * `Dockerfile` define `HOST=0.0.0.0` — mas nunca o faz o código por si, para que
 * correr o serviço à mão na máquina de alguém não abra uma porta na rede local
 * (`specs/01` §6, princípio 7, e o DoD do KAM-001: nada além de localhost).
 *
 * ## Em `prod` este processo **recusa arrancar**, e é a decisão mais importante
 * ## deste ficheiro
 *
 * O KAM-086 entrega o registo, o OTP e o anti-abuso, e entrega-os sobre o
 * `RepositorioDeCasos` do `@kamba/core-ts/inscricao`. **O adaptador SQL desse
 * repositório não existe**: a tabela `platform.onboarding_case` não tem
 * migração — a vaga de revisão de base de dados deste lote é de outro ticket, e
 * a `onboarding_case.fase` do dicionário §3.2 tem seis valores onde o bloco
 * escreve catorze (emenda 1.64, com o KAM-086/087 nomeado como credor).
 *
 * O que existe é o `CasosEmMemoria`. Um registo em memória **perde-se no
 * reinício**: um dono angolano que preencheu o formulário, recebeu o SMS e
 * voltou dois minutos depois encontrava o caso desaparecido, e o `nif_hmac` que
 * devia bloquear o duplicado desaparecia com ele. Servir isso em produção é
 * pior do que não servir — por isso o arranque **aborta** em `prod`, com o
 * credor nomeado na mensagem.
 *
 * Em `dev` e `staging` arranca, e é o que torna o fluxo exercitável ponta a
 * ponta com o `FakeSmsProvider` (critério 8 do KAM-116: «CI e `staging` usam o
 * *fake*»). Isto não é um atalho escondido: é uma recusa escrita, com o sítio
 * onde ela cai no dia em que o adaptador existir.
 *
 * ## O que ele lê do cofre, e o que faz se não estiver lá
 *
 * Os dois segredos do `inscricao/refs.ts`, com anel. São **obrigatórios**: sem
 * eles não há como assinar um convite nem cunhar um `nif_hmac`, e um serviço de
 * registo sem isso não serve pedidos — que é exactamente a regra 1 do
 * `Secrets.arrancar`.
 */

import { serve } from "@hono/node-server";
import { port } from "@kamba/core-ts";
import {
  Actividade,
  AntiAbuso,
  CasosEmMemoria,
  ContadoresEmMemoria,
  Otp,
  OtpEmMemoria,
  OtpPorSmsLocal,
  REFERENCIAS,
  Registo,
  anelDaAssinatura,
  anelDoPepper,
} from "@kamba/core-ts/inscricao";
import { instalar } from "@kamba/core-ts/logger";
import { EnvSecretProvider, Secrets, isAmbiente } from "@kamba/core-ts/secrets";
import {
  FakeSmsProvider,
  REF_PEPPER as REF_PEPPER_DO_SMS,
  anelDoPepper as anelDoPepperDoSms,
} from "@kamba/core-ts/sms";

import { createApp } from "./app.ts";
import { exigirComunicacaoLimpa } from "./comunicacao.ts";
import { DEFAULT_PORT, SERVICE } from "./meta.ts";
import { paginaDeRegisto } from "./pagina.ts";

// Antes de tudo o resto: a partir daqui, um erro por tratar sai como uma linha
// sem conteúdo, e não como a pilha com a mensagem no `stderr` (KAM-068).
const log = instalar(SERVICE);

const VARIAVEL_DO_AMBIENTE = "KAMBA_AMBIENTE";
const VARIAVEL_DOS_PROXIES = "ONBOARDING_PROXIES_DE_CONFIANCA";

/** Levantado quando falta o adaptador SQL do repositório. Ver a nota do módulo. */
export class RepositorioEmMemoriaEmProducaoError extends Error {
  override readonly name = "RepositorioEmMemoriaEmProducaoError";

  constructor() {
    super(
      "o onboarding-web nao arranca em prod: o RepositorioDeCasos so tem a " +
        "implementacao em memoria, e um registo que se perde no reinicio perde " +
        "o nif_hmac que bloqueia o duplicado. Falta o adaptador SQL de " +
        "platform.onboarding_case (credor: KAM-086/087, e a emenda 1.64 do " +
        "dicionario para a fase do caso)",
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
if (env === "prod") throw new RepositorioEmMemoriaEmProducaoError();

const provider = new EnvSecretProvider({ ambiente: env });
const secrets = await Secrets.arrancar({
  servico: SERVICE,
  provider,
  // Os dois da inscricao **e** o *pepper* do destino do SMS: este processo e o
  // que liga a porta do KAM-116 ao `OtpProvider` (`sms_local`), e sem o *pepper*
  // nao ha como cunhar um `Destino` — isto e, nao ha OTP. O inventario declara-o
  // com `obrigatorio_em: []` porque nenhum **outro** servico o pede; a lista de
  // arranque de quem o usa e que o torna obrigatorio aqui.
  obrigatorios: [...REFERENCIAS, REF_PEPPER_DO_SMS],
});

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

const casos = new CasosEmMemoria();
const contadores = new ContadoresEmMemoria();
const antiabuso = new AntiAbuso({ contadores, chave: pepper });
const otp = new Otp({
  repositorio: new OtpEmMemoria(),
  contadores,
  // O `FakeSmsProvider` é o que `staging` usa, por decisão do critério 8 do
  // KAM-116: **não há agregador escolhido** e escrever um adaptador para um
  // agregador hipotético era inventar a API dele.
  provedor: new OtpPorSmsLocal({ sms: new FakeSmsProvider(), pepperDoDestino }),
  chave: pepper,
  alerta: (motivo) => log.error({ outcome: motivo, error_code: motivo }),
});
const registo = new Registo({
  repositorio: casos,
  contadores,
  antiabuso,
  otp,
  // O anel inteiro: a actual escreve, as duas procuram. Ver `hmacsDoAnel`.
  anelDoPepper: [pepper, pepperAnterior],
  anelDoToken: [assinatura, assinaturaAnterior],
  anelDaSessao: [assinatura, assinaturaAnterior],
});
const actividade = new Actividade({ repositorio: casos, contadores });

// **A política de comunicação verifica-se no arranque**, e não só por resposta:
// um serviço que suba com o texto errado mostra-o a um dono antes de alguém
// notar. Falha fechado — ver `./comunicacao.ts`.
exigirComunicacaoLimpa(
  paginaDeRegisto({ desafio: "x.1.1.y", dificuldade: 1, nonce: "0".repeat(24), chave: "0".repeat(24), token: "" }),
);

const hostname = process.env.HOST?.trim() || "127.0.0.1";
const listenPort = port(DEFAULT_PORT);

const app = createApp(log, {
  registo,
  otp,
  actividade,
  antiabuso,
  anelDaAssinatura: [assinatura, assinaturaAnterior],
  anelDoToken: [assinatura, assinaturaAnterior],
  proxiesDeConfianca: proxiesDeConfianca(),
});

serve({ fetch: app.fetch, hostname, port: listenPort }, () => {
  // O anfitrião e a porta não estão na *allowlist* de `docs/tecnica/08` §7.3,
  // e por isso não saem: quem os quer saber lê a configuração do contentor.
  log.info({ outcome: "service_started" });
});
