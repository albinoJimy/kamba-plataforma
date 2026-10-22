/**
 * `POST /internal/channels` — a rota interna do Embedded Signup v4 (KAM-016).
 *
 * ## Vai na app **interna** e não na pública, e isso é a decisão deste ficheiro
 *
 * Os *Detalhes Técnicos* do bloco dizem «GWY (rotas internas)», e o nome é
 * literal. A `createApp` do `app.ts` serve o `/wa/webhook`, que é por definição
 * alcançável da Internet (ADR-001); a `criarAppDeMetricas` serve numa porta
 * interna, e o `docstring` dela explica porquê — a revisão adversarial do
 * KAM-013 tirou o `/metrics` da porta pública porque qualquer pessoa que lhe
 * chegasse lia a profundidade da fila.
 *
 * Esta rota **cria canais**. Numa porta pública, quem lhe chegasse podia ligar um
 * número a um tenant à escolha: o `tenant_id` vem no corpo, como o critério 1
 * manda, e não há aqui autenticação de tenant nenhuma — não a há porque a rota é
 * de **plataforma** e não de loja. É a mesma diferença que o `docstring` da
 * `criarAppDeMetricas` escreve: «não é defesa suficiente por si — a porta interna
 * também é uma porta —, mas é a diferença entre "exposto a quem alcança a
 * Internet" e "exposto a quem alcança a rede interna", e é a que está nas mãos
 * deste ticket. Fechar a rede é KAM-077.»
 *
 * **E o `tenant_id` do corpo não contradiz a regra do ADR-010.** «`tenant_id` vem
 * sempre do contexto e nunca do texto do utilizador» — e este corpo não é texto
 * de utilizador: é o resultado de um *popup* que a **nossa** página abriu
 * (KAM-093), com o `tenant_id` que essa página já tinha em contexto. O que nunca
 * entra por aqui é uma afirmação de um cliente final.
 *
 * ## O 409, e porque é que a transacção importa
 *
 * O critério 4 pede «409, não altera nada e deixa registo de auditoria». As três
 * metades resolvem-se com a forma da transacção, e não com três mecanismos:
 *
 * * o **409** é a `tenant_channels_phone_number_id_uq` da revisão `0001` a
 *   levantar `23505`, traduzida em `NumeroJaUsadoError` pelo módulo;
 * * o **«não altera nada»** é essa transacção a reverter — o `ROLLBACK` do
 *   `catch` leva com ele a linha do canal e a da tentativa;
 * * o **registo** escreve-se **depois**, numa transacção própria, e é por isso
 *   que o `registarRecusa` é chamado aqui e não dentro do `ligar()`: a ligação
 *   que o `ligar()` tem é a que acabou de abortar.
 *
 * ## Os códigos de resposta, e o que cada um diz a quem chama
 *
 *     201  o canal foi criado nesta chamada
 *     200  a tentativa já existia; devolve-se a que está lá (critério 2)
 *     400  o `session_info` não é de v4 (critério 1), ou o corpo não tem a forma
 *     409  o `phone_number_id` é de outro tenant (critério 4)
 *     429  o tecto de dez clientes por sete dias está gasto (critério 8)
 *     502  a Meta recusou ou não respondeu
 *
 * O **200 e não 201** na repetição não é cosmética: é a diferença que diz a quem
 * chamou se a chamada dele fez alguma coisa, e é a forma de o critério 2 se
 * verificar de fora — duas chamadas, um 201 e um 200, um canal.
 *
 * O **429 e não 403** no tecto: é um limite de ritmo, e a lista de espera que o
 * resolve é KAM-095. Um 403 dizia «nunca», e a resposta certa é «ainda não».
 */

import type { Hono } from "hono";
import {
  EsNaoEV4Error,
  LimiteDeOnboardingsError,
  NumeroJaUsadoError,
  type Onboarding,
  type ResultadoDoEs,
  type Tentativa,
} from "@kamba/core-ts/onboarding";
import type { Logger } from "@kamba/core-ts/logger";

/** O caminho, numa constante: é o que o critério 1 nomeia. */
export const CAMINHO_DOS_CANAIS = "/internal/channels";

/**
 * Como esta rota obtém uma transacção.
 *
 * Uma função e não um `Pool`, e a razão é a porta 1 do `onboarding/contrato.ts`:
 * o módulo precisa da ligação **dentro** da transacção de quem chama, porque a
 * linha do canal e o `channel_id` da tentativa têm de ser atómicos. Quem liga
 * esta rota decide o que é uma transacção (um `pg.PoolClient` com `BEGIN`, o
 * `comConsumo` do KAM-006); esta rota só precisa de poder abrir duas.
 *
 * A segunda é a do registo de auditoria, que corre **depois** de a primeira
 * reverter. Sem duas, o registo do critério 4 ia pelo `ROLLBACK` abaixo com o
 * resto.
 */
export type ComTransaccao = <T>(corpo: (servico: Onboarding) => Promise<T>) => Promise<T>;

/** As dependências da rota. */
export interface DependenciasDosCanais {
  /** Abre uma transacção e dá o serviço ligado a ela. */
  readonly comTransaccao: ComTransaccao;
}

/** Os cinco campos do critério 1, já validados. */
function lerCorpo(bruto: unknown): ResultadoDoEs {
  if (typeof bruto !== "object" || bruto === null) {
    throw new EsNaoEV4Error("o corpo não é um objecto");
  }
  const c = bruto as Record<string, unknown>;
  for (const campo of ["tenant_id", "code", "waba_id", "phone_number_id"]) {
    const valor = c[campo];
    if (typeof valor !== "string" || valor.trim() === "") {
      // **O valor não entra na mensagem**, e o campo entra. Um deles é o `code`,
      // que é trocável por um *token* de cliente: repetir o que se recusou punha
      // um segredo na resposta e no log de quem a registar. É a mesma regra do
      // `IdentificadorInvalidoError` do KAM-008.
      throw new EsNaoEV4Error(`o campo ${campo} falta ou não é uma cadeia`);
    }
  }
  const sessao = c.session_info;
  if (typeof sessao !== "object" || sessao === null) {
    throw new EsNaoEV4Error("o session_info falta ou não é um objecto");
  }
  return {
    tenant_id: (c.tenant_id as string).trim(),
    code: c.code as string,
    waba_id: (c.waba_id as string).trim(),
    phone_number_id: (c.phone_number_id as string).trim(),
    session_info: sessao as Record<string, unknown>,
  };
}

/**
 * O corpo da resposta.
 *
 * **Não leva o `token_ref` nem o `pin_ref`**, e isso é escolha: são referências
 * opacas a segredos, e quem chamou esta rota é a página do KAM-093 — que não
 * precisa de nenhuma das duas e não tem o que fazer com elas. O que ela precisa é
 * de saber que canal nasceu e em que fase está.
 */
function corpoDaResposta(t: Tentativa): Record<string, unknown> {
  return {
    onboarding_id: t.id,
    channel_id: t.channel_id,
    waba_id: t.waba_id,
    waac_id: t.waac_id,
    phone_number_id: t.phone_number_id,
    fase: t.fase,
    recursos_criados: t.recursos_criados.map((r) => r.recurso),
  };
}

/** Monta a rota na app dada. Chamada pela `criarAppInterna` do `app.ts`. */
export function montarCanais(
  app: Hono,
  dependencias: DependenciasDosCanais,
  log?: Logger,
): void {
  app.post(CAMINHO_DOS_CANAIS, async (c) => {
    let entrada: ResultadoDoEs;
    try {
      entrada = lerCorpo(await c.req.json());
    } catch (erro) {
      // Um corpo que não é JSON e um corpo sem os campos dão a mesma resposta: os
      // dois são «quem chamou não sabe o que esta rota recebe», e distingui-los
      // na resposta não ajuda ninguém e diz mais do que é preciso.
      log?.warn({ outcome: "canal_corpo_invalido" });
      return c.json(
        { error: erro instanceof EsNaoEV4Error ? erro.motivo : "corpo invalido" },
        400,
      );
    }

    try {
      const { tentativa, novo } = await dependencias.comTransaccao((servico) =>
        servico.ligar(entrada),
      );
      return c.json(corpoDaResposta(tentativa), novo ? 201 : 200);
    } catch (erro) {
      if (erro instanceof NumeroJaUsadoError) {
        // O registo de auditoria do critério 4, **numa transacção própria**: a
        // anterior reverteu, e com ela tudo o que tinha escrito.
        //
        // **E numa tentativa que não pode levar o 409 consigo.** O
        // `SQL_REGISTAR_RECUSA` nomeia uma das duas unicidades no `ON CONFLICT`,
        // e a outra existe: um *tenant* que já tenha gasto este `code` noutro
        // WABA faz esta escrita levantar `23505`. Sem o `try`, essa excepção
        // escapava e o `onError` do Hono respondia **500** — quem tentou ligar
        // um número de outro *tenant* ficava sem saber porquê, e o 409 que o
        // critério promete nunca saía. O registo é importante; a resposta certa
        // é mais.
        try {
          await dependencias.comTransaccao((servico) =>
            servico.registarRecusa(entrada, "phone_number_id de outro tenant"),
          );
        } catch (falha) {
          log?.excepcao(falha, "canal_recusa_sem_registo", {
            tenant_id: entrada.tenant_id,
            outcome: "canal_numero_de_outro_tenant",
          });
        }
        log?.warn({ outcome: "canal_numero_de_outro_tenant", tenant_id: entrada.tenant_id });
        // **A resposta não diz de quem é o número.** Quem recebe o 409 é o tenant
        // que tentou, e nomear o dono era um canal de leitura entre tenants por
        // mensagem de erro.
        return c.json({ error: "phone_number_id ja ligado a outro tenant" }, 409);
      }
      if (erro instanceof LimiteDeOnboardingsError) {
        log?.warn({ outcome: "canal_limite_7d" });
        return c.json(
          { error: "tecto de onboardings na janela de 7 dias", contagem: erro.contagem },
          429,
        );
      }
      if (erro instanceof EsNaoEV4Error) {
        log?.warn({ outcome: "canal_es_nao_e_v4", tenant_id: entrada.tenant_id });
        return c.json({ error: erro.motivo }, 400);
      }
      // O que sobra é a Meta ou a base. **A classe sai pelo `error_code` e a
      // mensagem não sai**: um erro da Graph pode repetir o parâmetro que
      // recusou, e o parâmetro recusado pode ser o `code`.
      log?.excepcao(erro, "canal_falhou", { tenant_id: entrada.tenant_id });
      return c.json({ error: "onboarding falhou" }, 502);
    }
  });
}
