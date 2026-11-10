/**
 * A inscrição self-service: registo, OTP e anti-abuso (KAM-086).
 *
 * O que um serviço importa daqui são cinco peças montáveis — `Registo`, `Otp`,
 * `AntiAbuso`, `Actividade` e `OtpPorSmsLocal` — mais os três duplos em memória
 * que CI e `dev` usam. Quem as monta é o `services/onboarding-web`.
 *
 * ## Isto **não** é o `../onboarding/`
 *
 * O `../onboarding/` é o Embedded Signup v4 da Meta (KAM-016): ligar o número de
 * WhatsApp de um tenant que já existe. Este módulo é o passo anterior, o do
 * `../../../../docs/tecnica/10` §4.1 passos 1 e 2 — o dono entra por `/entrar`,
 * declara o negócio, prova a posse do telefone, e sai com um `onboarding_case`
 * pronto para o KYC. Ainda não há tenant: o `tenant_id` é **pré-alocado**.
 *
 * ## Duas metades deste ticket não estão aqui, e nenhuma linha de código as substitui
 *
 * * **A tabela `platform.onboarding_case`.** O DDL está no bloco e a migração
 *   **não** está escrita. Duas razões, as duas medidas: a vaga de revisão de
 *   base de dados deste lote é **de outro ticket** (o bloco não nomeia qual), e
 *   a `onboarding_case.fase` do dicionário §3.2 diverge do bloco em **nove
 *   valores e num nome** — contados no `./contrato.ts`, ao lado das `FASES`. A
 *   emenda 1.64 do dicionário já nomeia o KAM-086/087 como credor. O que está entregue é a fronteira que o adaptador vai
 *   preencher: o `RepositorioDeCasos` do `./contrato.ts`, com o
 *   `./memoria.ts` como duplo. O precedente é do ticket ao lado — o KAM-091
 *   fundiu os domínios da saga «que viviam só no contrato em TypeScript», e a
 *   revisão `0034` veio depois.
 * * **A cifra de aplicação** (`nif_enc`, `phone_enc`, `email_enc`) é do mesmo
 *   adaptador, e a porta foi desenhada para isso: o `CasoNovo` leva valores
 *   **opacos** e o `Caso` só leva HMAC.
 *
 * E uma terceira, que é de fora: a **série Prometheus e a regra de alerta** do
 * orçamento de SMS. O que está entregue é a porta `Alerta` do `./contrato.ts`,
 * ligada ao *logger*; a métrica fica com credor nomeado (KAM-080/KAM-060).
 *
 * ## O que **não** se mede aqui, e onde se mede
 *
 * O isolamento por RLS `FORCE` sobre `app.onboarding_id`. Um `Map` não filtra
 * nada: o que este módulo garante é que **nenhuma consulta procura por outra
 * coisa que não um id ou um HMAC**, e que o id sai sempre de dentro de uma
 * referência assinada (`./sessao.ts`). Que a base recusa o resto é a caixa que
 * fica por marcar, com o adaptador como credor.
 */

export {
  Actividade,
  CHAVES as CHAVES_DE_ACTIVIDADE,
  INTERVALO_MAXIMO_SEGUNDOS,
  PERIODO_SEGUNDOS,
  type Batida,
  type OpcoesDeActividade,
} from "./actividade.ts";

export {
  AbusoError,
  AntiAbuso,
  CASOS_POR_DISPOSITIVO,
  CASOS_POR_REDE,
  CHAVES as CHAVES_DE_ABUSO,
  DIFICULDADE_BASE,
  DIFICULDADE_MAXIMA,
  DOMINIO_DA_PROVA,
  DOMINIO_DO_DESAFIO,
  JANELA_DA_REDE_MS,
  JANELA_DO_DISPOSITIVO_MS,
  NOME_DO_HONEYPOT,
  RECUSAS as RECUSAS_DE_ABUSO,
  SEGUNDOS_MINIMOS,
  VALIDADE_DO_DESAFIO_S,
  resolverDesafio,
  resumoDaProva,
  zerosACabeca,
  type DesafioEmitido,
  type OpcoesDeAntiAbuso,
  type Recusa as RecusaDeAbuso,
  type Submissao,
} from "./antiabuso.ts";

export {
  CANAIS_ACTIVOS,
  CANAIS_DE_OTP,
  CanalDesactivadoError,
  CasoDuplicadoError,
  ChaveReutilizadaError,
  FASES,
  FASES_MORTAS,
  FLAGS,
  MOTIVOS_DE_ALERTA,
  ORIGENS,
  faseViva,
  type Alerta,
  type CanalDeOtp,
  type Caso,
  type CasoNovo,
  type Contadores,
  type DesafioGuardado,
  type Fase,
  type Flag,
  type MotivoDeAlerta,
  type Origem,
  type OtpProvider,
  type Relogio,
  type RepositorioDeCasos,
  type RepositorioDeOtp,
} from "./contrato.ts";

export {
  ALGARISMOS_MINIMOS_DO_NIF,
  CARACTERES_DE_TEXTO,
  CARACTERES_DO_PREFIXO,
  ChaveDeHmacInvalidaError,
  DOMINIOS,
  Email,
  FORMA_DE_NIF,
  IdentificadorInvalidoError,
  MOTIVOS,
  Nif,
  OCTETOS_DE_HMAC,
  Telefone,
  ZEROS_DE_BLOCO,
  dobrarAlgarismos,
  hmacCorresponde,
  hmacDe,
  hmacsDoAnel,
  linhaDe,
  normalizarEmail,
  normalizarNif,
  normalizarTelefone,
  normalizarTexto,
  prefixoDeIp,
  type Dominio,
  type Linha,
  type MotivoDaRecusa,
} from "./identificadores.ts";

export {
  CasosEmMemoria,
  ContadoresEmMemoria,
  INSTANTES_POR_CHAVE,
  OtpEmMemoria,
  idSequencial,
} from "./memoria.ts";

export {
  CHAVES as CHAVES_DE_OTP,
  DIGITOS,
  ENVIOS_POR_JANELA,
  INTERVALO_SEGUNDOS,
  JANELA_DE_ENVIOS_MS,
  JANELA_DO_ORCAMENTO_MS,
  ORCAMENTO_DIARIO,
  Otp,
  RECUSAS_DE_ENVIO,
  TENTATIVAS_MAXIMAS,
  TTL_MINUTOS,
  VEREDICTOS,
  chaveDoEnvio,
  hmacDoCodigo,
  type OpcoesDeOtp,
  type RecusaDeEnvio,
  type ResultadoDeEnvio,
  type Veredicto,
} from "./otp.ts";

export { OtpPorSmsLocal, OtpPorWhatsApp, type OpcoesDeSmsLocal } from "./provedores.ts";

export { REFERENCIAS, REF_ASSINATURA, REF_PEPPER } from "./refs.ts";

export {
  CODIGOS,
  ESTADO_HTTP,
  Registo,
  RegistoRecusado,
  type Aceite,
  type Codigo,
  type OpcoesDeRegisto,
  type PedidoDeRegisto,
} from "./registo.ts";

export {
  ChaveMalFormadaError,
  anelDaAssinatura,
  anelDoPepper,
  type Anel,
  type LeitorDeAnel,
} from "./segredos.ts";

export {
  ATRIBUTOS_DO_COOKIE,
  DOMINIOS_DE_REFERENCIA,
  FINS,
  NOME_DO_COOKIE,
  VALIDADES,
  VALIDADE_DA_RETOMA_S,
  VALIDADE_DA_SESSAO_S,
  VALIDADE_DO_BILHETE_S,
  ReferenciaInvalidaError,
  cabecalhoDoCookie,
  cabecalhoQueApaga,
  cookieDoCabecalho,
  cunharReferencia,
  lerReferencia,
  type Fim,
} from "./sessao.ts";

export {
  CARACTERES_MAXIMOS,
  DOMINIO_DO_CONVITE,
  OCTETOS_DA_ASSINATURA,
  OCTETOS_DE_NONCE,
  RECUSAS as RECUSAS_DE_TOKEN,
  TokenInvalidoError,
  VALIDADE_MAXIMA_DIAS,
  cunharToken,
  verificarToken,
  type Convite,
  type Recusa as RecusaDeToken,
} from "./token.ts";
