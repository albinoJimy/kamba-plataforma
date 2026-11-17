/**
 * A régua de cobrança da assinatura: D+3 lembrete, D+7 aviso, D+10 suspensão,
 * e a regularização de volta a `ativo` (KAM-058; `docs/tecnica/04` §11.2).
 *
 * Como o `billing.ts`, o módulo é o SQL que a base corre e a composição dele;
 * as suites de base de dados leem as cadeias daqui (`ConsultaDoTypeScript`), e
 * o que se prova contra o PostgreSQL é o que este módulo envia.
 *
 * ## As quatro propriedades, e de onde vem cada uma
 *
 *     um passo por ciclo         `billing_dunning_steps_passo_uq`, `UNIQUE
 *                                (billing_cycle_id, passo)`, mais o trinco por
 *                                ciclo e a pergunta «já existe?» antes do efeito
 *     uma suspensão              o `transition_tenant` do KAM-092: repetir a
 *                                transição devolve `false`, e o evento só sai
 *                                com `true`, na mesma transacção
 *     o grafo dos estados        **não está aqui**: é o `tenant_transicoes()` da
 *                                `0058`, e este módulo só pede `suspenso` e
 *                                `ativo`
 *     números só da cobrança     o *template* recebe o valor, a referência e o
 *                                prazo da cobrança no *ledger*, e o ensaio
 *                                recusa qualquer outro dígito no texto
 *
 * ## Corre como `kamba_batch`
 *
 * É o único papel com `UPDATE` em `tenants.estado` (`0007`) e com `EXECUTE` no
 * `transition_tenant` e no `evt_emitir` (`0058`), e tem `BYPASSRLS`, pelo que
 * lê os ciclos de todos os tenants sem política nova. O `transition_tenant`
 * exige o `app.tenant_id` do próprio tenant, e cada passo corre com ele.
 *
 * ## O que este módulo **não** faz
 *
 * * **Não manda mensagem nenhuma.** O canal por onde a KAMBÁ fala com o dono é
 *   a decisão aberta **D10**, e a categoria Meta de um aviso de cobrança é NÃO
 *   VERIFICADA (D2, KAM-101). Até lá o notificador por omissão é o de ops: o
 *   passo gravado **é** a tarefa, e a `listaDeOps` é a lista diária.
 * * **Não cria cobranças nem ciclos** (KAM-059), e **não cobra comissão**
 *   (ADR-017): só lê a assinatura.
 * * **Não apaga nada.** Suspender é mudar `tenants.estado`; os dados, a
 *   exportação do titular e o estado `restrito` da Meta ficam como estão.
 */

import type { ClienteSql } from "../eventos/publicador.ts";
import { SQL_BILLING_CONTEXTO, dataEmLuanda, type DataCivil } from "./billing.ts";
import { minorParaDecimal2 } from "./dinheiro.ts";
import type { OwnerNotifier } from "./manual.ts";
import type { Minor, Uuid } from "./tipos.ts";

// --------------------------------------------------------------------------
// A configuração versionada (critério 4).
// --------------------------------------------------------------------------

/** Os três passos, pela ordem. Os nomes não levam o dia: o dia é configuração. */
export const PASSOS_DA_REGUA = ["lembrete", "aviso", "suspensao"] as const;
export type PassoDaRegua = (typeof PASSOS_DA_REGUA)[number];

/** `billing_dunning_steps.resultado`. */
export const RESULTADOS_DO_PASSO = [
  "notificado",
  "saltado",
  "cancelado",
  "suspenso",
  "sem_transicao",
] as const;
export type ResultadoDoPasso = (typeof RESULTADOS_DO_PASSO)[number];

/** `billing_dunning_steps.canal`: por onde saiu o aviso do passo, quando saiu. */
export const CANAIS_DA_REGUA = ["ops", "dono"] as const;
export type CanalDaRegua = (typeof CANAIS_DA_REGUA)[number];

/** Os placeholders de um texto. Uma lista fechada: nada mais entra. */
export const CAMPOS_DO_TEXTO = ["valor", "referencia", "prazo"] as const;

/**
 * O aviso anti-*phishing*, **fixo** e igual em todas as versões: sai no fim de
 * cada mensagem. Não leva número nenhum, e o ensaio confere-o.
 */
export const AVISO_ANTI_PHISHING =
  "A KAMBÁ nunca lhe pede senhas, códigos nem pagamentos para outra conta. " +
  "Pague só pelo painel ou pela forma de pagamento indicada nesta mensagem.";

/** Uma versão da régua. Os dias contam-se em dias civis de Luanda desde D+0. */
export type VersaoDaRegua = {
  /** O identificador gravado em cada passo (`config_versao`). */
  readonly versao: string;
  /** Vale para os ciclos que **abrem** neste dia ou depois. */
  readonly validaDe: DataCivil;
  readonly dias: Readonly<Record<PassoDaRegua, number>>;
  readonly textos: Readonly<Record<PassoDaRegua, string>>;
};

/**
 * As versões da régua, por ordem de `validaDe`.
 *
 * **Os dias (3, 7, 10) são proposta** a calibrar no Piloto (o bloco), e o
 * prazo de aviso prévio que a lei pede para suspender um serviço pago é
 * INDÍCIO (Art. 16.º da Lei 15/03, `docs/tecnica/evidencia/E3`; a confirmar
 * por parecer). Por isso uma mudança **não edita** uma versão: acrescenta outra
 * com `validaDe` posterior, e os ciclos já abertos ficam na deles.
 *
 * Os textos não levam dígitos: os números entram pelos três campos, que vêm da
 * cobrança, e por mais nenhum sítio.
 */
export const VERSOES_DA_REGUA: readonly VersaoDaRegua[] = [
  {
    versao: "2026-11-16.1",
    validaDe: "2026-11-16",
    dias: { lembrete: 3, aviso: 7, suspensao: 10 },
    textos: {
      lembrete:
        "KAMBÁ: a mensalidade de {valor} da sua loja está por pagar. " +
        "Pagamento: {referencia}. Pague até {prazo} para a loja não ser suspensa.",
      aviso:
        "KAMBÁ: sem o pagamento da mensalidade de {valor} até {prazo}, a loja é " +
        "suspensa. Pagamento: {referencia}.",
      suspensao:
        "KAMBÁ: a loja foi suspensa por falta de pagamento da mensalidade de " +
        "{valor}. Os dados da loja mantêm-se e pode exportá-los. Pagamento para " +
        "a reabrir: {referencia}.",
    },
  },
];

export class ConfiguracaoDaReguaInvalida extends Error {
  override readonly name = "ConfiguracaoDaReguaInvalida";
}

const DATA_CIVIL = /^\d{4}-\d{2}-\d{2}$/;
const PLACEHOLDER = /\{([a-z_]+)\}/g;
const DIGITO = /\d/;

/**
 * Recusa uma configuração que a régua não pode cumprir: dias fora de ordem,
 * versões fora de ordem, um texto com dígitos ou com um campo desconhecido.
 * Corre ao carregar o módulo e outra vez em quem receber versões por argumento.
 */
export function validarVersoes(versoes: readonly VersaoDaRegua[]): void {
  if (versoes.length === 0) throw new ConfiguracaoDaReguaInvalida("sem versoes");
  const vistas = new Set<string>();
  let anterior: DataCivil | null = null;
  for (const v of versoes) {
    if (vistas.has(v.versao)) throw new ConfiguracaoDaReguaInvalida(`versao repetida ${v.versao}`);
    vistas.add(v.versao);
    if (!DATA_CIVIL.test(v.validaDe)) {
      throw new ConfiguracaoDaReguaInvalida(`${v.versao}: validaDe nao e AAAA-MM-DD`);
    }
    if (anterior !== null && v.validaDe <= anterior) {
      throw new ConfiguracaoDaReguaInvalida(`${v.versao}: validaDe fora de ordem`);
    }
    anterior = v.validaDe;
    let dia = 0;
    for (const passo of PASSOS_DA_REGUA) {
      const d = v.dias[passo];
      if (!Number.isInteger(d) || d <= dia) {
        throw new ConfiguracaoDaReguaInvalida(
          `${v.versao}: o dia do ${passo} tem de ser inteiro e maior do que o do passo anterior`,
        );
      }
      dia = d;
      const texto = v.textos[passo];
      if (DIGITO.test(texto)) {
        throw new ConfiguracaoDaReguaInvalida(
          `${v.versao}: o texto do ${passo} tem um digito — os numeros so entram pelos campos`,
        );
      }
      for (const [, campo] of texto.matchAll(PLACEHOLDER)) {
        if (!(CAMPOS_DO_TEXTO as readonly string[]).includes(campo ?? "")) {
          throw new ConfiguracaoDaReguaInvalida(`${v.versao}: campo desconhecido {${campo}}`);
        }
      }
    }
  }
  if (DIGITO.test(AVISO_ANTI_PHISHING)) {
    throw new ConfiguracaoDaReguaInvalida("o aviso anti-phishing tem um digito");
  }
}

validarVersoes(VERSOES_DA_REGUA);

/**
 * A versão de um ciclo: a mais recente com `validaDe` não posterior a D+0.
 *
 * **D+0, e não o dia em que o motor corre**, que é o critério 4: mudar um valor
 * aplica-se só aos ciclos que abrem depois. Um ciclo anterior à primeira versão
 * fica com a primeira — antes dela não havia régua, e não há o que preservar.
 */
export function versaoDoCiclo(
  versoes: readonly VersaoDaRegua[],
  diaZero: DataCivil,
): VersaoDaRegua {
  let escolhida = versoes[0];
  if (escolhida === undefined) throw new ConfiguracaoDaReguaInvalida("sem versoes");
  for (const v of versoes) if (v.validaDe <= diaZero) escolhida = v;
  return escolhida;
}

const MS_POR_DIA = 86_400_000;

function diaUtc(data: DataCivil): number {
  return Date.parse(`${data}T00:00:00Z`);
}

/** Dias civis de `de` a `ate`. As duas meias-noites UTC dão um inteiro exacto. */
export function diasEntre(de: DataCivil, ate: DataCivil): number {
  return (diaUtc(ate) - diaUtc(de)) / MS_POR_DIA;
}

function somarDias(data: DataCivil, dias: number): DataCivil {
  return new Date(diaUtc(data) + dias * MS_POR_DIA).toISOString().slice(0, 10);
}

/**
 * Os dias entre o aviso e a suspensão: o aviso prévio que a versão promete. Um
 * motor que volta atrasado executa o aviso e espera estes dias outra vez antes
 * de suspender (achado 2 da revisão adversarial: sem isto, um ciclo aberto
 * tarde, ou um motor em baixo do D+2 ao D+10, suspendia sem aviso nenhum).
 */
export function diasDeAvisoPrevio(versao: VersaoDaRegua): number {
  return versao.dias.suspensao - versao.dias.aviso;
}

/** O que o motor faz a um passo de um ciclo, hoje. */
export type AccaoDaRegua = { readonly passo: PassoDaRegua; readonly accao: "executar" | "saltar" | "cancelar" };

/**
 * Os passos de um ciclo que ainda não foram gravados, e o que fazer a cada um.
 *
 * * Ciclo em dívida: os passos devidos (dia ≤ hoje). **Só o último executa**;
 *   os anteriores ficam `saltado`. É a lição do `ATRASO_DO_LEMBRETE_MS` do
 *   KAM-021: um motor que esteve em baixo não manda o lembrete e o aviso de
 *   seguida ao voltar.
 * * **A suspensão nunca salta o aviso**: só é devida com o aviso `notificado`
 *   há pelo menos `diasDeAvisoPrevio` dias (`diasDesdeOAviso`, `null` sem
 *   aviso notificado). Sem isso, o aviso executa e a suspensão espera.
 * * Ciclo `paga` ou `anulado`: os passos em falta ficam `cancelado` — é o
 *   «pagamento no D+9 cancela os passos pendentes» do critério 3.
 */
export function accoesDoCiclo(
  estado: string,
  gravados: readonly string[],
  versao: VersaoDaRegua,
  dia: number,
  diasDesdeOAviso: number | null = null,
): AccaoDaRegua[] {
  const emFalta = PASSOS_DA_REGUA.filter((p) => !gravados.includes(p));
  if (estado === "paga" || estado === "anulado") {
    return emFalta.map((passo) => ({ passo, accao: "cancelar" }));
  }
  const avisado = diasDesdeOAviso !== null && diasDesdeOAviso >= diasDeAvisoPrevio(versao);
  const devidos = emFalta.filter(
    (p) => versao.dias[p] <= dia && (p !== "suspensao" || avisado),
  );
  return devidos.map((passo, i) => ({
    passo,
    accao: i === devidos.length - 1 ? "executar" : "saltar",
  }));
}

// --------------------------------------------------------------------------
// O template (critério 5).
// --------------------------------------------------------------------------

/** A cobrança mais recente do ciclo, como o *ledger* a tem. */
export type CobrancaDoCiclo = {
  readonly metodo: string;
  readonly referencia: string | null;
  readonly valorMinor: Minor;
  readonly currency: string;
  readonly validaAte: Date;
};

/** O que sai no `{referencia}` sem referência emitida: a transferência manual. */
export const SEM_REFERENCIA = "transferência, com as instruções do painel";
/** O que sai no `{referencia}` quando a referência da cobrança já expirou. */
export const REFERENCIA_EXPIRADA = "a referência anterior expirou; peça uma nova no painel";

/** `DD/MM/AAAA`. */
function dataLegivel(data: DataCivil): string {
  return `${data.slice(8, 10)}/${data.slice(5, 7)}/${data.slice(0, 4)}`;
}

/** Os três campos, já escritos, todos da cobrança e da versão do ciclo. */
export function camposDaCobranca(
  cobranca: CobrancaDoCiclo,
  versao: VersaoDaRegua,
  diaZero: DataCivil,
  agora: Date,
): Readonly<Record<(typeof CAMPOS_DO_TEXTO)[number], string>> {
  let referencia = SEM_REFERENCIA;
  if (cobranca.metodo === "referencia" && cobranca.referencia !== null) {
    referencia =
      cobranca.validaAte.getTime() > agora.getTime()
        ? `referência ${cobranca.referencia}`
        : REFERENCIA_EXPIRADA;
  }
  return {
    valor: `${minorParaDecimal2(cobranca.valorMinor)} ${cobranca.currency === "AOA" ? "Kz" : cobranca.currency}`,
    referencia,
    prazo: dataLegivel(somarDias(diaZero, versao.dias.suspensao)),
  };
}

/** A mensagem de um passo: o texto da versão, os campos, e o aviso fixo. */
export function mensagemDoPasso(
  passo: PassoDaRegua,
  versao: VersaoDaRegua,
  campos: Readonly<Record<string, string>>,
): string {
  const corpo = versao.textos[passo].replace(PLACEHOLDER, (_t, campo: string) => {
    const valor = campos[campo];
    if (valor === undefined) throw new ConfiguracaoDaReguaInvalida(`campo em falta {${campo}}`);
    return valor;
  });
  return `${corpo}\n\n${AVISO_ANTI_PHISHING}`;
}

/**
 * Os dígitos de um texto que **não** vêm dos campos. Vazio quer dizer conforme.
 * Tira-se cada campo do texto e procura-se o que sobra: um número que não seja
 * um campo da cobrança é um número inventado (critério 5).
 */
export function numerosForaDosCampos(
  texto: string,
  campos: Readonly<Record<string, string>>,
): string[] {
  let resto = texto;
  for (const valor of Object.values(campos)) resto = resto.split(valor).join(" ");
  return resto.match(/\d+/g) ?? [];
}

// --------------------------------------------------------------------------
// O canal (critério 6). Uma porta: a decisão D10 está aberta.
// --------------------------------------------------------------------------

/** O que o motor pede ao canal. Sem telefone: o contacto resolve-o o adaptador. */
export type PedidoDaRegua = {
  readonly tenantId: Uuid;
  readonly billingCycleId: Uuid;
  readonly passo: PassoDaRegua;
  readonly mensagem: string;
  /** `regua:<ciclo>:<passo>`: a chave de idempotência de um envio. */
  readonly chave: string;
};

/** O canal da régua. Devolve por onde o aviso saiu de facto. */
export interface NotificadorDaRegua {
  entregar(pedido: PedidoDaRegua): Promise<CanalDaRegua>;
}

/**
 * O notificador por omissão: **a tarefa de ops é o passo gravado**, com
 * `canal = 'ops'`, e a lista diária lê-se pela `listaDeOps`. Não sai mensagem
 * nenhuma — é o *fallback* manual do critério 6 até D10 fechar.
 */
export const notificadorDeOps: NotificadorDaRegua = {
  entregar: async () => "ops",
};

export class CanalD10Fechado extends Error {
  override readonly name = "CanalD10Fechado";
}

/**
 * O caminho pelo `OwnerNotifier` (`contactId`, nunca telefone; ADR-010).
 *
 * **Exige a referência escrita da decisão D10**, como o `verificarComissao`
 * exige o parecer D8: o Fluxo A fala pelo número da PME, e uma cobrança da
 * KAMBÁ por esse número era o número de um tenant a falar de um assunto que
 * não é o dele. Sem a decisão, não se constrói. Sem contacto do dono, o passo
 * fica tarefa de ops — não se perde.
 */
export function notificadorPeloDono(
  owner: OwnerNotifier,
  contactoDoDono: (tenantId: Uuid) => Promise<Uuid | null>,
  decisaoD10Ref: string | null,
): NotificadorDaRegua {
  if (decisaoD10Ref === null || decisaoD10Ref.trim() === "") {
    throw new CanalD10Fechado(
      "o canal da KAMBA com o dono e a decisao aberta D10: sem a referencia " +
        "escrita dela, a regua so cria tarefas de ops",
    );
  }
  return {
    entregar: async (pedido) => {
      const contacto = await contactoDoDono(pedido.tenantId);
      if (contacto === null) return "ops";
      await owner.avisar(contacto, pedido.mensagem);
      return "dono";
    },
  };
}

// --------------------------------------------------------------------------
// As métricas (DoD). Uma porta, como o `payment_events_total` do `hooks.ts`.
// --------------------------------------------------------------------------

/** `dunning_step_total{passo,resultado}`. */
export const METRICA_PASSOS = "dunning_step_total";
/** `tenants_suspended_by_dunning_total`. */
export const METRICA_SUSPENSOES = "tenants_suspended_by_dunning_total";

/**
 * O limiar do alerta «> N suspensões por dia». **Proposta**: o bloco escreve
 * «N proposta» e não há base para outro número antes do Piloto.
 */
export const LIMIAR_DE_SUSPENSOES_POR_DIA = 5;

export type MetricasDaRegua = {
  contar(nome: string, etiquetas: Readonly<Record<string, string>>): void;
};

const SEM_METRICAS: MetricasDaRegua = { contar: () => {} };

// --------------------------------------------------------------------------
// O SQL. Todas as instruções correm como `kamba_batch`.
// --------------------------------------------------------------------------

/** O motivo e o actor que a régua escreve no `tenant_state_log`. */
export const MOTIVO_DA_SUSPENSAO = "regua_de_cobranca";
export const MOTIVO_DA_REPOSICAO = "regua_de_cobranca_regularizada";
export const ACTOR_DA_REGUA = "regua_de_cobranca";
/** O `payload.motivo` do `tenant.suspended`: o «falta de pagamento» do doc 00 §6.2. */
export const MOTIVO_NO_EVENTO = "falta_de_pagamento";

/**
 * Os ciclos que a régua tem de olhar: os que se cobram, e os pagos ou anulados
 * que ainda têm passos por cancelar. `$1` é a lista dos passos.
 *
 * **O D+0 é a emissão da primeira cobrança do ciclo**, em Luanda (o bloco: «D+0
 * referência»), e não o início do período: um ciclo aberto tarde contava o
 * atraso desde um dia em que ainda não havia nada para pagar. Sem cobrança, o
 * início do período. O `aviso_em` é o dia do aviso notificado.
 */
export const SQL_REGUA_CICLOS = `
  SELECT c.id, c.tenant_id, c.subscription_id, c.estado,
         coalesce(
           (SELECT (min(x.criado_at) AT TIME ZONE 'Africa/Luanda')::date
              FROM platform.payment_charges x
             WHERE x.billing_cycle_id = c.id AND x.tenant_id = c.tenant_id),
           lower(c.periodo))::text AS inicio,
         (SELECT (a.executado_at AT TIME ZONE 'Africa/Luanda')::date::text
            FROM platform.billing_dunning_steps a
           WHERE a.billing_cycle_id = c.id AND a.passo = 'aviso'
             AND a.resultado = 'notificado') AS aviso_em,
         coalesce(array_agg(d.passo) FILTER (WHERE d.passo IS NOT NULL), '{}') AS passos
    FROM platform.billing_cycles c
    LEFT JOIN platform.billing_dunning_steps d
           ON d.billing_cycle_id = c.id AND d.tenant_id = c.tenant_id
   WHERE c.estado IN ('cobranca_emitida', 'em_atraso')
      OR (c.estado IN ('paga', 'anulado')
          AND EXISTS (SELECT 1 FROM platform.billing_dunning_steps x
                       WHERE x.billing_cycle_id = c.id))
   GROUP BY c.id
  HAVING c.estado IN ('cobranca_emitida', 'em_atraso')
      OR NOT (coalesce(array_agg(d.passo) FILTER (WHERE d.passo IS NOT NULL), '{}')
              @> $1::text[])
   ORDER BY c.tenant_id, c.id
`;

/** Um trinco por ciclo, até ao fim da transacção. */
export const SQL_REGUA_TRANCAR = `
  SELECT pg_advisory_xact_lock(hashtextextended($1::text, 0))
`;

/**
 * O estado do ciclo, relido **sob o trinco**: um pagamento que entrou entre a
 * leitura dos ciclos e o passo transforma-o em cancelamento (achado 5 da
 * revisão adversarial — sem isto suspendia-se quem acabara de pagar).
 */
export const SQL_REGUA_ESTADO_DO_CICLO = `
  SELECT estado FROM platform.billing_cycles WHERE id = $1 AND tenant_id = $2
`;

/** Já há este passo? Pergunta-se **depois** do trinco e antes do efeito. */
export const SQL_REGUA_PASSO_GRAVADO = `
  SELECT 1 AS existe FROM platform.billing_dunning_steps
   WHERE billing_cycle_id = $1 AND passo = $2
`;

/** A cobrança mais recente do ciclo: é dela que saem os números da mensagem. */
export const SQL_REGUA_COBRANCA = `
  SELECT metodo, referencia, amount_minor, currency, valid_until
    FROM platform.payment_charges
   WHERE billing_cycle_id = $1 AND tenant_id = $2
   ORDER BY tentativa DESC
   LIMIT 1
`;

/** `ativa -> em_atraso`, no lembrete. Um tenant em atraso mantém os limites. */
export const SQL_REGUA_EM_ATRASO = `
  UPDATE platform.subscriptions SET estado = 'em_atraso'
   WHERE id = $1 AND estado = 'ativa'
`;

/**
 * O estado do tenant, **sem trinco**: quem tranca é o `transition_tenant`, pela
 * ordem dele (o caso e depois o tenant), e trancar o tenant aqui antes invertia
 * essa ordem (achado 9 da revisão adversarial). A janela entre esta leitura e a
 * transição fecha-a o `SQL_REGUA_DE_ONDE_VEIO`.
 */
export const SQL_REGUA_ESTADO_DO_TENANT = `
  SELECT estado FROM platform.tenants WHERE id = $1
`;

/**
 * De onde a transição acabou de vir: a última linha do registo do tenant. Se
 * não foi de `ativo` — um `restrito` que chegou entre a leitura e a transição —,
 * o passo reverte e repete-se na volta seguinte.
 */
export const SQL_REGUA_DE_ONDE_VEIO = `
  SELECT de FROM platform.tenant_state_log
   WHERE tenant_id = $1 ORDER BY em DESC LIMIT 1
`;

export class TransicaoDeOutroEstado extends Error {
  override readonly name = "TransicaoDeOutroEstado";
}

/** A porta do KAM-092. O grafo é dela. */
export const SQL_REGUA_TRANSITAR = `
  SELECT platform.transition_tenant($1::uuid, $2, $3, $4) AS mudou
`;

/** O evento, na transacção da transição. A forma do `SQL_EMITIR_CHANNEL_UPDATED`. */
export const SQL_REGUA_EMITIR = `
  SELECT platform.evt_emitir(
    $1, $2::smallint, $3::uuid, $4, $5, $6::jsonb
  ) AS event_id
`;

/** O actor da régua no `audit_log`, na forma do `kamba_batch:retencao` do KAM-071. */
export const ACTOR_NO_AUDIT_LOG = "kamba_batch:regua_de_cobranca";

/**
 * A transição no `audit_log` (critério 2: «com `audit_log`»), pela porta
 * `platform.audit_append` da `0006`, na transacção da transição. A acção é a
 * `batch.run` do domínio fechado — a régua é um lote — sobre a entidade
 * `tenant`; o `payload_hash` é o SHA-256 de `de>para:motivo`, sem nada do dono.
 * `$1` o tenant, `$2` o actor, `$3` o texto que se resume.
 */
export const SQL_REGUA_AUDITAR = `
  SELECT platform.audit_append(
           $1::uuid, 'system', $2, 'batch.run', 'tenant', $1::text, NULL,
           sha256(convert_to($3, 'UTF8')))
`;

/** A subscrição de um tenant suspenso pela régua. */
export const SQL_REGUA_SUSPENSA = `
  UPDATE platform.subscriptions SET estado = 'suspensa'
   WHERE id = $1 AND estado IN ('ativa', 'em_atraso')
`;

/**
 * O passo, gravado no fim. O `ON CONFLICT` é a segunda barreira: a primeira é o
 * trinco. `executado_at` é do relógio de quem chama (a lição do
 * `owner_notices.criado_at`: com o `now()` do servidor, o relógio do ensaio
 * media uma coisa e a base registava outra).
 */
export const SQL_REGUA_GRAVAR_PASSO = `
  INSERT INTO platform.billing_dunning_steps (
      tenant_id, billing_cycle_id, passo, executado_at, resultado, canal, config_versao)
  VALUES ($1, $2, $3, $4, $5, $6, $7)
  ON CONFLICT ON CONSTRAINT billing_dunning_steps_passo_uq DO NOTHING
  RETURNING id
`;

/**
 * Os tenants que a régua suspendeu e que já não devem nada que a suspensão
 * tenha apanhado. **Só os que ela suspendeu**: a última transição registada do
 * tenant tem de ser a dela. **E nenhuma sanção de T&S de suspensão ou
 * encerramento depois dela, sem recurso provido**: o Trust (KAM-097) suspende
 * por um `UPDATE` que não passa pelo registo, e sobre um tenant já suspenso
 * não muda nada — sem esta pergunta, pagar a assinatura levantava a sanção
 * (achado 1 da revisão adversarial). `$1` é o motivo da suspensão; `$2` um
 * tenant, ou `NULL` para todos.
 */
export const SQL_REGUA_POR_REPOR = `
  SELECT t.id AS tenant_id
    FROM platform.tenants t
   WHERE t.estado = 'suspenso'
     AND ($2::uuid IS NULL OR t.id = $2::uuid)
     AND (SELECT l.motivo FROM platform.tenant_state_log l
           WHERE l.tenant_id = t.id AND l.para = 'suspenso'
           ORDER BY l.em DESC LIMIT 1) = $1
     AND (SELECT l.para FROM platform.tenant_state_log l
           WHERE l.tenant_id = t.id ORDER BY l.em DESC LIMIT 1) = 'suspenso'
     AND NOT EXISTS (
           SELECT 1 FROM platform.billing_cycles c
             JOIN platform.billing_dunning_steps d
               ON d.billing_cycle_id = c.id AND d.passo = 'suspensao'
            WHERE c.tenant_id = t.id AND c.estado IN ('cobranca_emitida', 'em_atraso'))
     AND NOT EXISTS (
           SELECT 1 FROM platform.ts_sanction s
            WHERE s.tenant_id = t.id AND s.recurso_de IS NULL
              AND s.passo IN ('suspensao', 'encerramento')
              AND s.em >= (SELECT max(l.em) FROM platform.tenant_state_log l
                            WHERE l.tenant_id = t.id AND l.para = 'suspenso')
              AND NOT EXISTS (
                    SELECT 1 FROM platform.ts_sanction r
                     WHERE r.tenant_id = t.id AND r.recurso_de = s.id
                       AND r.recurso_estado = 'provido'))
   ORDER BY t.id
`;

/** As subscrições de um tenant reposto voltam a `ativa`. */
export const SQL_REGUA_SUBSCRICAO_REPOSTA = `
  UPDATE platform.subscriptions SET estado = 'ativa'
   WHERE tenant_id = $1 AND estado IN ('em_atraso', 'suspensa')
`;

/**
 * `em_atraso -> ativa` para quem pagou antes da suspensão: nenhum ciclo em
 * dívida com passo gravado. Uma instrução, sem contexto: `kamba_batch`.
 */
export const SQL_REGUA_SUBSCRICOES_EM_DIA = `
  UPDATE platform.subscriptions s SET estado = 'ativa'
   WHERE s.estado = 'em_atraso'
     AND NOT EXISTS (
           SELECT 1 FROM platform.billing_cycles c
             JOIN platform.billing_dunning_steps d ON d.billing_cycle_id = c.id
            WHERE c.subscription_id = s.id
              AND c.estado IN ('cobranca_emitida', 'em_atraso'))
  RETURNING s.id
`;

/** As suspensões da régua num intervalo `[$1, $2)`: a contagem do alerta. */
export const SQL_REGUA_SUSPENSOES_NO_DIA = `
  SELECT count(*)::int AS n FROM platform.billing_dunning_steps
   WHERE passo = 'suspensao' AND resultado = 'suspenso'
     AND executado_at >= $1 AND executado_at < $2
`;

/**
 * A lista diária de ops (critério 6): os passos com `canal = 'ops'` do dia,
 * com a cobrança mais recente de cada ciclo para refazer a mensagem. A
 * mensagem não se guarda: refaz-se do *ledger*, que é a fonte dos números.
 */
export const SQL_REGUA_LISTA_DE_OPS = `
  SELECT d.tenant_id, d.billing_cycle_id, d.passo, d.config_versao,
         coalesce(
             (SELECT (min(x.criado_at) AT TIME ZONE 'Africa/Luanda')::date
                FROM platform.payment_charges x
               WHERE x.billing_cycle_id = c.id AND x.tenant_id = c.tenant_id),
             lower(c.periodo))::text AS inicio,
         p.metodo, p.referencia, p.amount_minor, p.currency, p.valid_until
    FROM platform.billing_dunning_steps d
    JOIN platform.billing_cycles c
      ON c.id = d.billing_cycle_id AND c.tenant_id = d.tenant_id
    JOIN LATERAL (
         SELECT x.metodo, x.referencia, x.amount_minor, x.currency, x.valid_until
           FROM platform.payment_charges x
          WHERE x.billing_cycle_id = c.id AND x.tenant_id = c.tenant_id
          ORDER BY x.tentativa DESC LIMIT 1) p ON true
   WHERE d.canal = 'ops' AND d.executado_at >= $1 AND d.executado_at < $2
   ORDER BY d.executado_at, d.tenant_id
`;

// --------------------------------------------------------------------------
// O motor.
// --------------------------------------------------------------------------

export type OpcoesDaRegua = {
  /** O relógio, por argumento: o motor não chama `Date.now()` (critério 8). */
  readonly agora: Date;
  readonly notificador?: NotificadorDaRegua;
  readonly metricas?: MetricasDaRegua;
  readonly versoes?: readonly VersaoDaRegua[];
};

export type PassoFeito = {
  readonly billingCycleId: Uuid;
  readonly tenantId: Uuid;
  readonly passo: PassoDaRegua;
  readonly resultado: ResultadoDoPasso;
  readonly canal: CanalDaRegua | null;
};

export type RelatorioDaRegua = {
  readonly passos: readonly PassoFeito[];
  /** Os ciclos cuja suspensão esperou: o tenant estava `restrito` ou `suspenso`. */
  readonly suspensoesAdiadas: readonly Uuid[];
  readonly repostos: readonly Uuid[];
  readonly subscricoesEmDia: number;
  readonly suspensoesHoje: number;
  /** `true` acima do `LIMIAR_DE_SUSPENSOES_POR_DIA`: o alerta do DoD. */
  readonly alertaDeSuspensoes: boolean;
  readonly falhas: readonly { readonly billingCycleId: Uuid | null; readonly tenantId: Uuid; readonly erro: string }[];
};

function texto(valor: unknown): string {
  return String(valor);
}

function lista(valor: unknown): string[] {
  if (Array.isArray(valor)) return valor.map(texto);
  if (typeof valor === "string") {
    // `text[]` em texto (`{a,b}`), de condutores que não o convertem.
    const corpo = valor.replace(/^\{|\}$/g, "");
    return corpo === "" ? [] : corpo.split(",");
  }
  return [];
}

function cobrancaDe(linha: Record<string, unknown>): CobrancaDoCiclo {
  return {
    metodo: texto(linha.metodo),
    referencia: linha.referencia === null || linha.referencia === undefined ? null : texto(linha.referencia),
    valorMinor: BigInt(texto(linha.amount_minor)),
    currency: texto(linha.currency),
    validaAte: linha.valid_until instanceof Date ? linha.valid_until : new Date(texto(linha.valid_until)),
  };
}

function emitir(bd: ClienteSql, tipo: string, tenantId: Uuid, payload: object) {
  return bd.query(SQL_REGUA_EMITIR, [tipo, 1, tenantId, "tenant", tenantId, JSON.stringify(payload)]);
}

/**
 * Um passo, numa transacção: o contexto, o trinco, a pergunta, o efeito e a
 * linha. Uma falha reverte tudo e o passo corre na volta seguinte — é o
 * «*crash* a meio de um passo» dos testes requeridos.
 */
async function correrPasso(
  bd: ClienteSql,
  ciclo: { id: Uuid; tenantId: Uuid; subscriptionId: Uuid; diaZero: DataCivil },
  accao: AccaoDaRegua,
  versao: VersaoDaRegua,
  agora: Date,
  notificador: NotificadorDaRegua,
): Promise<PassoFeito | "adiado" | null> {
  await bd.query("BEGIN");
  try {
    await bd.query(SQL_BILLING_CONTEXTO, [ciclo.tenantId]);
    await bd.query(SQL_REGUA_TRANCAR, [ciclo.id]);
    const ja = await bd.query(SQL_REGUA_PASSO_GRAVADO, [ciclo.id, accao.passo]);
    if (ja.rows.length > 0) {
      await bd.query("COMMIT");
      return null;
    }
    const estadoDoCiclo = texto((await bd.query(SQL_REGUA_ESTADO_DO_CICLO, [ciclo.id, ciclo.tenantId])).rows[0]?.estado);
    if (estadoDoCiclo === "paga" || estadoDoCiclo === "anulado") {
      accao = { passo: accao.passo, accao: "cancelar" };
    }

    let resultado: ResultadoDoPasso = accao.accao === "saltar" ? "saltado" : "cancelado";
    let canal: CanalDaRegua | null = null;
    if (accao.accao === "executar") {
      resultado = "notificado";
      let avisar = true;
      // **Em qualquer passo executado, e não só no lembrete**: um motor que
      // volta no D+8 salta o lembrete e executa o aviso, e a subscrição tem de
      // ficar `em_atraso` na mesma. O `WHERE estado = 'ativa'` torna-o
      // idempotente.
      await bd.query(SQL_REGUA_EM_ATRASO, [ciclo.subscriptionId]);
      if (accao.passo === "suspensao") {
        const estado = texto((await bd.query(SQL_REGUA_ESTADO_DO_TENANT, [ciclo.tenantId])).rows[0]?.estado);
        // **Só de `ativo`.** O grafo da `0058` deixa `restrito -> suspenso`, e
        // a régua não a usa: `restrito` é da Meta, e uma suspensão por cima
        // dele seguida de uma reposição a `ativo` apagava a restrição
        // (critério 7). **`restrito` e `suspenso` adiam** — nada se grava, e o
        // passo volta a perguntar na volta seguinte: quando a restrição ou a
        // outra suspensão se levantar com a dívida por pagar, a régua suspende
        // (achado 7). `onboarding` e `encerrado` ficam `sem_transicao`.
        if (estado === "restrito" || estado === "suspenso") {
          await bd.query("COMMIT");
          return "adiado";
        }
        resultado = "sem_transicao";
        avisar = false;
        if (estado === "ativo") {
          const t = await bd.query(SQL_REGUA_TRANSITAR, [
            ciclo.tenantId,
            "suspenso",
            MOTIVO_DA_SUSPENSAO,
            ACTOR_DA_REGUA,
          ]);
          if (t.rows[0]?.mudou === true) {
            const de = texto((await bd.query(SQL_REGUA_DE_ONDE_VEIO, [ciclo.tenantId])).rows[0]?.de);
            if (de !== "ativo") throw new TransicaoDeOutroEstado(`o tenant passou a suspenso de ${de}`);
            await emitir(bd, "tenant.suspended", ciclo.tenantId, { motivo: MOTIVO_NO_EVENTO });
            await bd.query(SQL_REGUA_AUDITAR, [
              ciclo.tenantId,
              ACTOR_NO_AUDIT_LOG,
              `ativo>suspenso:${MOTIVO_DA_SUSPENSAO}`,
            ]);
            await bd.query(SQL_REGUA_SUSPENSA, [ciclo.subscriptionId]);
            resultado = "suspenso";
            avisar = true;
          }
        }
      }
      if (avisar) {
        const linha = (await bd.query(SQL_REGUA_COBRANCA, [ciclo.id, ciclo.tenantId])).rows[0];
        if (linha === undefined) throw new Error(`o ciclo ${ciclo.id} nao tem cobranca`);
        const campos = camposDaCobranca(cobrancaDe(linha), versao, ciclo.diaZero, agora);
        canal = await notificador.entregar({
          tenantId: ciclo.tenantId,
          billingCycleId: ciclo.id,
          passo: accao.passo,
          mensagem: mensagemDoPasso(accao.passo, versao, campos),
          chave: `regua:${ciclo.id}:${accao.passo}`,
        });
      }
    }

    await bd.query(SQL_REGUA_GRAVAR_PASSO, [
      ciclo.tenantId,
      ciclo.id,
      accao.passo,
      agora.toISOString(),
      resultado,
      canal,
      versao.versao,
    ]);
    await bd.query("COMMIT");
    return { billingCycleId: ciclo.id, tenantId: ciclo.tenantId, passo: accao.passo, resultado, canal };
  } catch (erro) {
    await bd.query("ROLLBACK");
    throw erro;
  }
}

/**
 * A reposição de um tenant, numa transacção, com a pergunta repetida. Quem
 * tranca é o `transition_tenant`; repetir a transição devolve `false`.
 */
async function repor(bd: ClienteSql, tenantId: Uuid): Promise<boolean> {
  await bd.query("BEGIN");
  try {
    await bd.query(SQL_BILLING_CONTEXTO, [tenantId]);
    const ainda = await bd.query(SQL_REGUA_POR_REPOR, [MOTIVO_DA_SUSPENSAO, tenantId]);
    if (ainda.rows.length === 0) {
      await bd.query("COMMIT");
      return false;
    }
    const t = await bd.query(SQL_REGUA_TRANSITAR, [tenantId, "ativo", MOTIVO_DA_REPOSICAO, ACTOR_DA_REGUA]);
    const mudou = t.rows[0]?.mudou === true;
    if (mudou) {
      await emitir(bd, "tenant.reactivated", tenantId, {});
      await bd.query(SQL_REGUA_AUDITAR, [tenantId, ACTOR_NO_AUDIT_LOG, `suspenso>ativo:${MOTIVO_DA_REPOSICAO}`]);
      await bd.query(SQL_REGUA_SUBSCRICAO_REPOSTA, [tenantId]);
    }
    await bd.query("COMMIT");
    return mudou;
  } catch (erro) {
    await bd.query("ROLLBACK");
    throw erro;
  }
}

/** O início e o fim, em UTC, do dia civil de Luanda que contém `agora`. */
function diaDeLuanda(agora: Date): { inicio: Date; fim: Date } {
  const hoje = dataEmLuanda(agora);
  const inicio = new Date(diaUtc(hoje) - MS_POR_DIA / 24);
  return { inicio, fim: new Date(inicio.getTime() + MS_POR_DIA) };
}

/**
 * Uma volta da régua. Corre-se a cada poucos segundos (`INTERVALO_DA_REGUA_MS`):
 * os passos são diários e idempotentes, e a reposição é o que pede a volta
 * curta — o p95 de 60 s do critério 3 é o intervalo mais a volta.
 *
 * Pela ordem: os passos (cada um na sua transacção), as reposições, e as
 * subscrições que ficaram em dia. Os passos vêm antes das reposições: um ciclo
 * que chegou hoje ao dia da suspensão grava o passo antes de a reposição
 * perguntar se o tenant ainda deve.
 */
export async function correrRegua(bd: ClienteSql, opcoes: OpcoesDaRegua): Promise<RelatorioDaRegua> {
  const versoes = opcoes.versoes ?? VERSOES_DA_REGUA;
  validarVersoes(versoes);
  const notificador = opcoes.notificador ?? notificadorDeOps;
  const metricas = opcoes.metricas ?? SEM_METRICAS;
  const hoje = dataEmLuanda(opcoes.agora);
  const passos: PassoFeito[] = [];
  const adiados: Uuid[] = [];
  const falhas: { billingCycleId: Uuid | null; tenantId: Uuid; erro: string }[] = [];

  const { rows: ciclos } = await bd.query(SQL_REGUA_CICLOS, [[...PASSOS_DA_REGUA]]);
  for (const linha of ciclos) {
    const ciclo = {
      id: texto(linha.id),
      tenantId: texto(linha.tenant_id),
      subscriptionId: texto(linha.subscription_id),
      diaZero: texto(linha.inicio),
    };
    const versao = versaoDoCiclo(versoes, ciclo.diaZero);
    const accoes = accoesDoCiclo(
      texto(linha.estado),
      lista(linha.passos),
      versao,
      diasEntre(ciclo.diaZero, hoje),
      linha.aviso_em === null || linha.aviso_em === undefined ? null : diasEntre(texto(linha.aviso_em), hoje),
    );
    try {
      for (const accao of accoes) {
        const feito = await correrPasso(bd, ciclo, accao, versao, opcoes.agora, notificador);
        if (feito === "adiado") {
          adiados.push(ciclo.id);
          continue;
        }
        if (feito === null) continue;
        passos.push(feito);
        metricas.contar(METRICA_PASSOS, { passo: feito.passo, resultado: feito.resultado });
        if (feito.resultado === "suspenso") metricas.contar(METRICA_SUSPENSOES, {});
      }
    } catch (erro) {
      falhas.push({
        billingCycleId: ciclo.id,
        tenantId: ciclo.tenantId,
        erro: erro instanceof Error ? erro.message : String(erro),
      });
    }
  }

  const repostos: Uuid[] = [];
  const { rows: porRepor } = await bd.query(SQL_REGUA_POR_REPOR, [MOTIVO_DA_SUSPENSAO, null]);
  for (const linha of porRepor) {
    const tenantId = texto(linha.tenant_id);
    try {
      if (await repor(bd, tenantId)) repostos.push(tenantId);
    } catch (erro) {
      falhas.push({ billingCycleId: null, tenantId, erro: erro instanceof Error ? erro.message : String(erro) });
    }
  }

  const emDia = await bd.query(SQL_REGUA_SUBSCRICOES_EM_DIA);
  const dia = diaDeLuanda(opcoes.agora);
  const contagem = await bd.query(SQL_REGUA_SUSPENSOES_NO_DIA, [dia.inicio.toISOString(), dia.fim.toISOString()]);
  const n = contagem.rows[0]?.n;
  const suspensoesHoje = typeof n === "number" ? n : 0;
  return {
    passos,
    suspensoesAdiadas: adiados,
    repostos,
    subscricoesEmDia: emDia.rows.length,
    suspensoesHoje,
    alertaDeSuspensoes: suspensoesHoje > LIMIAR_DE_SUSPENSOES_POR_DIA,
    falhas,
  };
}

/** Uma tarefa da lista diária de ops, com a mensagem refeita do *ledger*. */
export type TarefaDeOps = {
  readonly tenantId: Uuid;
  readonly billingCycleId: Uuid;
  readonly passo: PassoDaRegua;
  readonly mensagem: string;
};

/**
 * A lista diária de ops do dia de Luanda que contém `agora` (critério 6). A
 * mensagem é a que o dono receberia, refeita da cobrança e da versão gravada no
 * passo; o contacto do dono não sai daqui, e ops resolve-o na consola.
 */
export async function listaDeOps(
  bd: ClienteSql,
  agora: Date,
  versoes: readonly VersaoDaRegua[] = VERSOES_DA_REGUA,
): Promise<TarefaDeOps[]> {
  const dia = diaDeLuanda(agora);
  const { rows } = await bd.query(SQL_REGUA_LISTA_DE_OPS, [dia.inicio.toISOString(), dia.fim.toISOString()]);
  return rows.map((r) => {
    const passo = texto(r.passo) as PassoDaRegua;
    const diaZero = texto(r.inicio);
    const versao = versoes.find((v) => v.versao === texto(r.config_versao)) ?? versaoDoCiclo(versoes, diaZero);
    return {
      tenantId: texto(r.tenant_id),
      billingCycleId: texto(r.billing_cycle_id),
      passo,
      mensagem: mensagemDoPasso(passo, versao, camposDaCobranca(cobrancaDe(r), versao, diaZero, agora)),
    };
  });
}
