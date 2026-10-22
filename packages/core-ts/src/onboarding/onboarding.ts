/**
 * O serviço de onboarding de canal: passos idempotentes e compensáveis (KAM-016).
 *
 * ## Isto não é o orquestrador, e a diferença importa
 *
 * Os *Detalhes Técnicos* do bloco são explícitos: «O orquestrador (saga) é
 * KAM-091; este ticket entrega **passos idempotentes**.» O que está aqui é o
 * conjunto de passos, cada um com o seu recurso registado e a sua compensação, e
 * um `ligar()` que os corre pela ordem — não uma máquina de saga com persistência
 * de *jobs*, retomas e políticas de retentativa. Essa é do KAM-091, e o que ela
 * vai precisar é que cada passo possa ser chamado duas vezes sem fazer duas
 * coisas. É isso que o critério 2 mede.
 *
 * ## A ordem dos passos, e as duas que não são óbvias
 *
 * 1. **o tecto** — `es_onboardings_7d < 10`, e recusa antes de tocar em nada;
 * 2. **a forma do ES** — v4 ou recusa (critério 1);
 * 3. **abrir a tentativa** — `INSERT ... ON CONFLICT DO NOTHING`. Se não abriu, a
 *    tentativa já existia: devolve-se a que está lá e **não se faz mais nada**.
 *    É a idempotência do critério 2, e é da base;
 * 4. **trocar o *code*** — e cifrar, e cunhar a referência (critério 3);
 * 5. **o PIN**, só em `cloud_only`;
 * 6. **criar o canal** — e é aqui que o 409 do critério 4 nasce, da unicidade
 *    global da `0001`;
 * 7. **subscrever os onze campos** e **confirmar por leitura** (critério 5).
 *
 * **O 4 vem antes do 6, e isso é consequência de uma coluna.** O `token_ref` de
 * `tenant_channels` é `NOT NULL` desde a `0001`, pelo que não há linha de canal a
 * criar antes de haver *token*. A primeira leitura disto é um defeito — gasta-se
 * o *code* num onboarding que vai dar 409 —, e a segunda é que torna o critério 4
 * e o critério 7 **a mesma maquinaria**: o conflito compensa o passo do *token*
 * pelo mesmo caminho que uma falha na subscrição, e há um teste só para isso.
 *
 * A alternativa era um `SELECT` em `tenant_channels` antes do passo 4. Não se
 * faz, e a razão está no `docstring` da revisão `0017`: seria uma segunda verdade
 * a reconciliar com a unicidade, e perderia a corrida — entre o `SELECT` e o
 * `INSERT` cabe outro processo. O briefing deste ticket di-lo do mesmo modo: o
 * 409 é «a unicidade global a morder, não uma verificação em código».
 *
 * **O 1 vem antes do 3**, e não é indiferente: contar depois de abrir a tentativa
 * fazia a própria tentativa entrar na contagem, e o tecto de dez passava a nove.
 *
 * ## A compensação percorre a lista ao contrário, e lê-a da base
 *
 * `recursos_criados` é a lista, pela ordem em que os passos a escreveram, e a
 * compensação lê-a **da base** e não de uma variável deste processo. É o que
 * torna a compensação retomável: um processo que caia depois do passo 6 deixa o
 * canal e o *token* registados na coluna, e quem retomar sabe o que desfazer sem
 * ter estado presente.
 *
 * Depois de desfazer tudo, a lista fica `[]` e a fase fica `falhado`. **É aí que
 * se leem os «0 recursos órfãos» do critério 7**, ao lado de «0 linhas em
 * `tenant_channels`» e «0 subscrições no WABA» — e as três medem-se, porque uma
 * lista vazia só prova que a lista está vazia.
 *
 * ## O que este módulo **não** faz, e é escopo e não esquecimento
 *
 * * **Não registra o número.** Em coexistência não se faz (CONFIRMADO, `E1` §3:
 *   «não se faz registo do número (já registado)»), e em `cloud_only` é o passo
 *   5′ do `01` §13.2 — verificação por SMS ou voz, com a entrega em Angola
 *   **NÃO VERIFICADA**. Este ticket guarda o PIN que esse passo vai usar.
 * * **Não sincroniza nada.** O `a_sincronizar` existe no domínio e nenhuma
 *   transição deste módulo o produz: a sincronização de contactos e histórico é
 *   KAM-017, e o `subscrito → a_sincronizar` é a porta por onde ele entra.
 * * **Não activa canal nenhum.** O canal nasce `pendente` e fica. «Nenhum cliente
 *   é contactado até ao passo 10 passar» (`01` §13.2), e o *gate* de activação é
 *   KAM-093.
 * * **Não cria conta no Chatwoot** (KAM-019/091), **não submete templates**
 *   (KAM-015) e **não trata o `account_update`** (KAM-021 para a qualidade,
 *   KAM-017 para o `PARTNER_REMOVED`).
 * * **Não tem lista de espera.** O tecto recusa com `LimiteDeOnboardingsError`; a
 *   fila é KAM-095, e o critério 8 di-lo.
 */

import { createHash, randomBytes } from "node:crypto";

import type { Logger } from "../logger/index.ts";
import {
  CAMPOS_DE_WEBHOOK,
  type ClienteSql,
  type Cofre,
  DIGITOS_DO_PIN,
  EsNaoEV4Error,
  FEATURE_TYPE_DE_COEXISTENCIA,
  type Fase,
  type Graph,
  JANELA_DE_ONBOARDINGS_DIAS,
  LIMITE_DE_ONBOARDINGS,
  LimiteDeOnboardingsError,
  type Modo,
  NumeroJaUsadoError,
  PRAZO_DE_ABANDONO_MIN,
  type RecursoCriado,
  type ResultadoDoEs,
  SESSION_INFO_VERSION,
  type SessionInfo,
  SubscricaoIncompletaError,
  type Tentativa,
  TransicaoInvalidaError,
  transicaoValida,
} from "./contrato.ts";
import { cifrarToken, decifrarToken } from "./cifra.ts";
// Os três `id` de segredo vêm do ficheiro estreito que o *gate* 9 dispensa; ver
// a nota do `contrato.ts`.
import { FAMILIA_DO_PIN, FAMILIA_DO_TOKEN, REF_DA_KEK } from "./segredos.ts";
import {
  SQL_ABANDONAR,
  SQL_ABRIR,
  SQL_APAGAR_CANAL,
  SQL_CONTAR_JANELA,
  SQL_CRIAR_CANAL,
  SQL_FASE,
  SQL_GUARDAR_PIN,
  SQL_LIGAR_CANAL,
  SQL_LARGAR_O_PONTO,
  SQL_LIMPAR_RECURSOS,
  SQL_PONTO_DE_SALVAGUARDA,
  SQL_RECURSOS,
  SQL_REGISTAR_RECURSO,
  SQL_REGISTAR_RECUSA,
  SQL_SOLTAR_CANAL,
  SQL_TENTATIVA,
  SQL_TRANSITAR,
  SQL_VOLTAR_AO_PONTO,
} from "./consultas.ts";
import { compararCampos } from "./graph.ts";
import { METRICAS, type Metricas, type MotivoDeRecusa } from "./metricas.ts";

/** O código SQLSTATE de violação de unicidade. */
const UNICIDADE_VIOLADA = "23505";
/** A unicidade que faz o 409 do critério 4. */
const RESTRICAO_DO_NUMERO = "tenant_channels_phone_number_id_uq";

/** As dependências do serviço. */
export interface Dependencias {
  /** A ligação **dentro** da transacção de quem chama. Ver a porta 1 do contrato. */
  readonly sql: ClienteSql;
  readonly graph: Graph;
  readonly cofre: Cofre;
  /** A vertical do canal. Configuração (ADR-012), com `CHECK` de forma na `0001`. */
  readonly vertical: string;
  readonly log?: Logger;
  readonly metricas?: Metricas;
}

/** O que o `ligar()` devolve. */
export interface Resultado {
  readonly tentativa: Tentativa;
  /** `true` quando esta chamada fez o trabalho; `false` quando repetiu. */
  readonly novo: boolean;
}

/**
 * O resumo do *code*, para a coluna `code_hash`.
 *
 * `sha256` sem sal e sem HMAC, e a razão está no `COMMENT` da coluna na `0017`: o
 * *code* tem entropia de segredo, pelo que o resumo dele não é enumerável — ao
 * contrário de um telefone, que é o que obriga o `pepper_contact_hmac` da `0003`
 * a existir.
 */
export function resumoDoCode(code: string): Buffer {
  return createHash("sha256").update(code, "utf8").digest();
}

/**
 * Verifica que o resultado do Embedded Signup é de v4. **O critério 1.**
 *
 * Duas afirmações, e as duas vêm do `E1` §3 (CONFIRMADO): o
 * `extras.featureType` é `whatsapp_business_app_onboarding` e o
 * `sessionInfoVersion` é a **cadeia** `"3"`.
 *
 * O `sessionInfoVersion` aceita-se também como número `3`, e isso é tolerância
 * de fronteira e não relaxamento: o `E1` escreve-o entre aspas, e um *popup*
 * que o mande como número é um `JSON.parse` a fazer o seu trabalho — recusar o
 * onboarding de um cliente real por causa de um par de aspas era o lado errado
 * de falhar. O que **não** se tolera é a ausência, nem outro valor: `"2"` é v2, e
 * v2 deixou de funcionar a 2026-10-15.
 *
 * O `featureType` é exigido **sem tolerância**: ele é o que distingue um
 * onboarding de coexistência de um `cloud_only`, e adivinhá-lo pela ausência era
 * decidir o modo do canal por omissão.
 */
export function modoDoSessionInfo(bruto: Readonly<Record<string, unknown>>): Modo {
  const info = bruto as SessionInfo;
  const versao = info.sessionInfoVersion;
  const normalizada = typeof versao === "number" ? String(versao) : versao;
  if (normalizada !== SESSION_INFO_VERSION) {
    throw new EsNaoEV4Error(
      `sessionInfoVersion é ${JSON.stringify(versao)} e v4 exige ` +
        `${JSON.stringify(SESSION_INFO_VERSION)}`,
    );
  }
  const featureType = info.extras?.featureType;
  if (featureType === FEATURE_TYPE_DE_COEXISTENCIA) return "coexistencia";
  if (featureType === undefined) {
    throw new EsNaoEV4Error(
      "extras.featureType não vem no session_info; sem ele o modo do canal " +
        "seria decidido por omissão",
    );
  }
  // Um `featureType` que não é o da coexistência é um ES v4 de `cloud_only`: o
  // `E1` §3 só nomeia o da coexistência, e não enumera os outros. Aceita-se, e o
  // modo é o outro — mas o valor fica no log, porque um `featureType` que
  // ninguém reconhece é a primeira coisa a saber no dia em que a Meta
  // acrescentar um.
  return "cloud_only";
}

/**
 * Um PIN 2FA de seis dígitos, do gerador do sistema.
 *
 * `randomBytes` e um módulo por dígito. O módulo introduz um viés — 256 não é
 * múltiplo de 10, pelo que os dígitos 0 a 5 saem com probabilidade 26/256 e os 6
 * a 9 com 25/256 — e **aceita-se, com a razão escrita**: o PIN tem seis dígitos,
 * logo um milhão de valores, e o viés não muda a ordem de grandeza do que custa
 * adivinhá-lo. O que o protege não é a uniformidade perfeita: é a Meta limitar as
 * tentativas, e o PIN estar no cofre com «acesso minimo: so o provisionamento o
 * le» (`ops/secrets-inventory.yaml`). Eliminar o viés com rejeição de amostras
 * era corrigir a parte que não é a barreira.
 */
function novoPin(): string {
  const bruto = randomBytes(DIGITOS_DO_PIN);
  let pin = "";
  for (let i = 0; i < DIGITOS_DO_PIN; i += 1) pin += String((bruto[i] ?? 0) % 10);
  return pin;
}

function codigoDoErro(erro: unknown): string | null {
  if (typeof erro !== "object" || erro === null) return null;
  const codigo = (erro as { code?: unknown }).code;
  return typeof codigo === "string" ? codigo : null;
}

function restricaoDoErro(erro: unknown): string | null {
  if (typeof erro !== "object" || erro === null) return null;
  const nome = (erro as { constraint?: unknown }).constraint;
  return typeof nome === "string" ? nome : null;
}

/** O serviço. */
export class Onboarding {
  readonly #d: Dependencias;
  readonly #m: Metricas;

  constructor(dependencias: Dependencias) {
    this.#d = dependencias;
    this.#m = dependencias.metricas ?? METRICAS;
  }

  /**
   * Quantos onboardings entraram na janela de sete dias, e espelha o *gauge*.
   *
   * **Atravessa tenants**: ver a nota do `SQL_CONTAR_JANELA`. Corre com
   * `BYPASSRLS` (o `kamba_batch`), e com a política `tenant_iso` daria sempre o
   * número de uma loja — o que é pior do que não contar, porque parece certo.
   */
  async contarJanela(): Promise<number> {
    const { rows } = await this.#d.sql.query<{ contagem: string | number }>(
      SQL_CONTAR_JANELA,
      [JANELA_DE_ONBOARDINGS_DIAS],
    );
    const contagem = Number(rows[0]?.contagem ?? 0);
    this.#m.medir("es_onboardings_7d", contagem);
    return contagem;
  }

  /**
   * Corre o onboarding. Idempotente por `(tenant_id, code)` e por
   * `(tenant_id, waba_id)`.
   *
   * Devolve `novo: false` quando a tentativa já existia — e nesse caso **não
   * fala com a Meta**: o critério 2 pede «1 *token* e 0 subscrições duplicadas»,
   * e trocar o *code* outra vez criava um segundo *token* no cofre antes de
   * descobrir que havia um.
   */
  async ligar(entrada: ResultadoDoEs): Promise<Resultado> {
    // ---------------------------------------------------- 1. o tecto da Meta
    const janela = await this.contarJanela();
    if (janela >= LIMITE_DE_ONBOARDINGS) {
      this.#recusar("limite_7d");
      throw new LimiteDeOnboardingsError(janela);
    }

    // ------------------------------------------------- 2. a forma do ES (v4)
    let modo: Modo;
    try {
      modo = modoDoSessionInfo(entrada.session_info);
    } catch (erro) {
      this.#recusar("es_nao_e_v4");
      throw erro;
    }

    // --------------------------------------------------- 3. abrir, ou repetir
    const resumo = resumoDoCode(entrada.code);
    const abertas = await this.#d.sql.query<Tentativa>(SQL_ABRIR, [
      entrada.tenant_id,
      entrada.waba_id,
      null,
      entrada.phone_number_id,
      resumo,
    ]);
    const aberta = abertas.rows[0];
    if (aberta === undefined) {
      // A tentativa já existia: devolve-se o que está lá. **Nada mais corre** —
      // nem a Meta, nem o cofre, nem a base. É a idempotência do critério 2, e
      // quem a garante é a unicidade e não este `if`: duas chamadas concorrentes
      // não podem ter as duas uma linha, logo uma das duas cai aqui.
      const { rows } = await this.#d.sql.query<Tentativa>(SQL_TENTATIVA, [
        entrada.tenant_id,
        entrada.waba_id,
      ]);
      const existente = rows[0];
      if (existente === undefined) {
        // O `ON CONFLICT` disparou e a linha não está lá: só pode ser o conflito
        // da **outra** chave — o mesmo `code` noutro WABA. Não se inventa uma
        // resposta: quem repete um `code` já gasto sobre outro WABA está a pedir
        // uma coisa que a Meta também não faria.
        throw new EsNaoEV4Error(
          "o code já foi usado noutro onboarding deste tenant; " +
            "um code do Embedded Signup serve uma vez",
        );
      }
      this.#d.log?.info({ outcome: "onboarding_repetido", tenant_id: entrada.tenant_id });
      return { tentativa: existente, novo: false };
    }

    // Daqui para a frente há uma linha nossa, e tudo o que correr mal passa pela
    // compensação. O `try` é largo de propósito: um passo novo que alguém
    // acrescente fica coberto sem ter de se lembrar disso.
    try {
      const token = await this.#trocarEGuardar(aberta, entrada.code);
      const pinRef = modo === "cloud_only" ? await this.#guardarPin(aberta) : null;
      const channelId = await this.#criarCanal(aberta, entrada, modo, token.ref);
      await this.#subscrever(aberta, entrada.waba_id, token.claro);
      const tentativa: Tentativa = {
        ...aberta,
        channel_id: channelId,
        fase: "subscrito",
        pin_ref: pinRef,
        recursos_criados: await this.#recursos(aberta),
      };
      this.#d.log?.info({ outcome: "onboarding_subscrito", tenant_id: entrada.tenant_id });
      return { tentativa, novo: true };
    } catch (erro) {
      await this.compensar(aberta.id, aberta.tenant_id, this.#motivoDe(erro));
      if (erro instanceof NumeroJaUsadoError) {
        // O registo de auditoria do critério 4 vive numa transacção própria,
        // porque a que levantou o `23505` **reverte** — ver o `docstring` da
        // `0017`. Quem chama corre o `registarRecusa` fora da transacção; aqui
        // conta-se, que é o que esta camada pode fazer sem abrir ligação.
        this.#recusar("numero_de_outro_tenant");
      }
      throw erro;
    }
  }

  /** Passo 3: troca o *code*, cifra o *token*, cunha a referência. **O critério 3.** */
  async #trocarEGuardar(
    t: Tentativa,
    code: string,
  ): Promise<{ readonly ref: string; readonly claro: string }> {
    const claro = await this.#d.graph.trocarCode(code);
    // O `kid` é a versão **actual** da KEK, e sai do `versions()[0]`: a porta
    // garante que `versions()[0]` corresponde ao que `get()` devolve, e é essa
    // garantia que faz o par (chave, kid) ser coerente. Ler o `getRing` aqui
    // dava o valor sem o identificador, e o identificador é o que torna a
    // rotação possível (ver o `cifra.ts`).
    const [kid] = await this.#d.cofre.versions(REF_DA_KEK);
    const kek = await this.#d.cofre.get(REF_DA_KEK);
    if (kid === undefined) {
      throw new EsNaoEV4Error("a KEK do token de cliente não tem versão viva");
    }
    const criptograma = cifrarToken(kek, kid, t.tenant_id, claro);
    const ref = await this.#d.cofre.cunhar(FAMILIA_DO_TOKEN, criptograma);
    await this.#registar(t, { recurso: "token", ref });
    return { ref, claro };
  }

  /** Passo 3, só em `cloud_only`: o PIN 2FA de seis dígitos no cofre. */
  async #guardarPin(t: Tentativa): Promise<string> {
    const ref = await this.#d.cofre.cunhar(FAMILIA_DO_PIN, novoPin());
    await this.#registar(t, { recurso: "pin", ref });
    await this.#d.sql.query(SQL_GUARDAR_PIN, [t.id, t.tenant_id, ref]);
    return ref;
  }

  /**
   * Passo 3, a seguir ao *token*: a linha de `tenant_channels`.
   *
   * **O 409 do critério 4 nasce aqui**, e é a `tenant_channels_phone_number_id_uq`
   * da `0001` a levantar `23505`. Ramifica-se pelo **nome da restrição** e não
   * pelo código sozinho: a tabela tem uma unicidade só hoje, mas um `23505`
   * tratado como «número de outro tenant» transformaria qualquer unicidade
   * futura num 409 enganador.
   */
  async #criarCanal(
    t: Tentativa,
    entrada: ResultadoDoEs,
    modo: Modo,
    tokenRef: string,
  ): Promise<string> {
    let channelId: string;
    // **O ponto de salvaguarda não é higiene**: sem ele, o `23505` aborta a
    // transacção e a compensação não consegue revogar o *token* que o passo
    // anterior cunhou — ver o `docstring` do `SQL_PONTO_DE_SALVAGUARDA`.
    await this.#d.sql.query(SQL_PONTO_DE_SALVAGUARDA);
    try {
      const { rows } = await this.#d.sql.query<{ id: string }>(SQL_CRIAR_CANAL, [
        entrada.tenant_id,
        entrada.waba_id,
        null,
        entrada.phone_number_id,
        modo,
        this.#d.vertical,
        tokenRef,
      ]);
      const criado = rows[0];
      if (criado === undefined) throw new Error("o INSERT do canal não devolveu id");
      channelId = criado.id;
      await this.#d.sql.query(SQL_LARGAR_O_PONTO);
    } catch (erro) {
      await this.#d.sql.query(SQL_VOLTAR_AO_PONTO);
      if (
        codigoDoErro(erro) === UNICIDADE_VIOLADA &&
        restricaoDoErro(erro) === RESTRICAO_DO_NUMERO
      ) {
        throw new NumeroJaUsadoError(entrada.phone_number_id);
      }
      throw erro;
    }
    await this.#registar(t, { recurso: "canal", ref: channelId });
    await this.#d.sql.query(SQL_LIGAR_CANAL, [t.id, t.tenant_id, channelId]);
    return channelId;
  }

  /**
   * Passo 4: subscrever os onze campos e **confirmar por leitura**. **O critério 5.**
   *
   * A leitura de confirmação não é zelo: um `POST` a `subscribed_apps` responde
   * `{"success": true}` sem dizer **quais** campos ficaram, e o critério pede
   * igualdade de conjuntos. Sem ela, um campo que a Meta recusasse em silêncio
   * era um webhook que outro ticket espera e que nunca chega — e isso não se
   * descobre num teste do ticket que o trata.
   */
  async #subscrever(t: Tentativa, wabaId: string, token: string): Promise<void> {
    await this.#d.graph.subscrever(wabaId, CAMPOS_DE_WEBHOOK, token);
    await this.#registar(t, { recurso: "subscricao", ref: wabaId });
    const obtidos = await this.#d.graph.lerSubscricoes(wabaId, token);
    const { falta, aMais } = compararCampos(obtidos);
    if (falta.length > 0 || aMais.length > 0) {
      throw new SubscricaoIncompletaError(falta, aMais);
    }
    await this.transitar(t.id, t.tenant_id, "es_concluido", "subscrito");
  }

  /** Acrescenta um recurso à lista da compensação. */
  async #registar(t: Tentativa, recurso: RecursoCriado): Promise<void> {
    await this.#d.sql.query(SQL_REGISTAR_RECURSO, [
      t.id,
      t.tenant_id,
      JSON.stringify([recurso]),
    ]);
  }

  /** A lista de recursos como está na base. */
  async #recursos(t: Tentativa): Promise<readonly RecursoCriado[]> {
    const { rows } = await this.#d.sql.query<Tentativa>(SQL_TENTATIVA, [
      t.tenant_id,
      t.waba_id,
    ]);
    return rows[0]?.recursos_criados ?? [];
  }

  /**
   * A transição, pela matriz e por *compare-and-set*. **O critério 6.**
   *
   * Duas barreiras, e as duas são precisas:
   *
   * * o `transicaoValida` recusa um par que a matriz não tem, **antes** de tocar
   *   na base — e é isso que torna «transições inválidas são rejeitadas» uma
   *   afirmação sobre a máquina e não sobre o que a base calhou aceitar;
   * * o `WHERE fase = <esperada>` do SQL recusa uma transição a partir de uma
   *   fase que já mudou. Devolve zero linhas, e zero linhas é `false`.
   *
   * A primeira **levanta** e a segunda devolve `false`, e a assimetria é
   * deliberada: um par inválido é um defeito de quem chama e tem de ser ruidoso;
   * uma corrida perdida é um facto do mundo, e quem perdeu a corrida tem de poder
   * decidir o que faz a seguir.
   */
  async transitar(
    id: string,
    tenantId: string,
    de: Fase,
    para: Fase,
    motivo: string | null = null,
  ): Promise<boolean> {
    if (!transicaoValida(de, para)) throw new TransicaoInvalidaError(de, para);
    const { rows } = await this.#d.sql.query(SQL_TRANSITAR, [
      id,
      tenantId,
      de,
      para,
      motivo,
    ]);
    return rows.length === 1;
  }

  /**
   * Desfaz os recursos pela ordem inversa e deixa a tentativa em `falhado`.
   * **O critério 7.**
   *
   * Lê a lista **da base** e não de uma variável: um processo que caia a meio
   * deixa a lista escrita, e quem retomar desfaz o que ficou sem ter estado
   * presente. É o que faz desta compensação uma operação retomável e não uma
   * limpeza de memória.
   *
   * **Cada passo da compensação é tolerante à ausência.** Revogar um segredo que
   * já não existe resolve (o contrato da `SecretWriter` exige-o); apagar um canal
   * que já não está lá devolve zero linhas; anular uma subscrição de um WABA que
   * já não tem nenhuma é um `DELETE` idempotente. Uma compensação que falhasse na
   * segunda passagem deixava a saga sem forma de acabar — que é o oposto do que o
   * critério pede.
   *
   * O `anularSubscricao` precisa do *token* **em claro**, e o *token* já está
   * cifrado no cofre quando a compensação corre. Por isso a subscrição desfaz-se
   * com o *token* decifrado a partir da referência que a própria lista guarda —
   * e se a revogação do *token* corresse primeiro, não haveria com que a
   * desfazer. É a razão concreta de a ordem ser **inversa** e não arbitrária: o
   * `token` é o primeiro recurso da lista, logo o último a ser desfeito.
   */
  async compensar(id: string, tenantId: string, motivo: string): Promise<void> {
    const { rows } = await this.#d.sql.query<{
      recursos_criados: readonly RecursoCriado[];
    }>(SQL_RECURSOS, [id, tenantId]);
    const lista = rows[0]?.recursos_criados ?? [];
    let tokenRef: string | null = null;
    for (const { recurso, ref } of lista) if (recurso === "token") tokenRef = ref;

    // **Os dois pré-requisitos da base, antes de desfazer recurso nenhum.**
    //
    // A `channel_onboarding_channel_fk` não tem `ON DELETE CASCADE`: enquanto
    // esta linha apontar para o canal, apagá-lo levanta `23503`. E largar o
    // `channel_id` exige que a fase já esteja em `falhado`, porque o
    // `channel_onboarding_canal_ck` recusa o nulo nas seis fases do meio. São
    // três restrições em cadeia, e a ordem das três é toda da base — ver o
    // `docstring` do `SQL_SOLTAR_CANAL`.
    //
    // Corre **só quando há canal na lista**: sem ele não há FK a largar, e a
    // transição para `falhado` acontece no fim como em qualquer outra falha.
    if (lista.some(({ recurso }) => recurso === "canal")) {
      await this.#transitarParaFalhado(id, tenantId, motivo);
      await this.#d.sql.query(SQL_SOLTAR_CANAL, [id, tenantId]);
    }

    for (const { recurso, ref } of [...lista].reverse()) {
      try {
        if (recurso === "subscricao" && tokenRef !== null) {
          await this.#d.graph.anularSubscricao(ref, await this.#tokenEmClaro(tenantId, tokenRef));
        } else if (recurso === "canal") {
          await this.#d.sql.query(SQL_APAGAR_CANAL, [ref, tenantId]);
        } else if (recurso === "token" || recurso === "pin") {
          await this.#d.cofre.revogar(ref);
        }
        this.#m.contar("es_onboarding_compensado_total", recurso);
      } catch (erro) {
        // **Uma compensação que falha pára as seguintes**, e a razão é a ordem:
        // a lista desfaz-se ao contrário, e o `token` é o **último**. Se a
        // anulação da subscrição falhar e nós revogássemos o *token* a seguir,
        // ficávamos sem a única credencial com que a subscrição se pode anular —
        // um recurso órfão **impossível de desfazer**, em vez de um que fica à
        // espera da próxima passagem.
        //
        // A lista **não** se esvazia, e é isso que torna a compensação
        // retomável: quem voltar lê o que ficou. Um comentário anterior aqui
        // dizia o contrário — «não pára as outras» —, e era o comentário que
        // estava errado e não o código; a revisão adversarial separou os dois.
        //
        // O `error_code` leva a classe do erro e o recurso que ficou pendurado, e
        // mais nada: uma `SecretRef` ou um `channel_id` numa linha de log era
        // um identificador fora da lista branca do `docs/tecnica/08` §7.3.
        this.#d.log?.excepcao(erro, `compensacao_falhou_${recurso}`, {
          tenant_id: tenantId,
          outcome: "compensacao_falhou",
        });
        return;
      }
    }
    // **A fase vai a `falhado` ANTES de a lista se esvaziar**, e a ordem é uma
    // restrição da base e não uma preferência: o `SQL_LIMPAR_RECURSOS` põe o
    // `channel_id` a `NULL`, e o `channel_onboarding_canal_ck` recusa-o nas seis
    // fases do meio. A primeira versão limpava primeiro e levantava `23514` no
    // último passo da compensação — depois de ter desfeito tudo o que havia a
    // desfazer. Apanhado pela revisão adversarial.
    //
    // A transição corre outra vez porque pode não ter corrido acima: ela só
    // acontece lá quando há canal na lista. É idempotente — o
    // `#transitarParaFalhado` lê a fase e não faz nada se já estiver lá.
    await this.#transitarParaFalhado(id, tenantId, motivo);
    await this.#d.sql.query(SQL_LIMPAR_RECURSOS, [id, tenantId]);
  }

  /**
   * Põe a tentativa em `falhado`, de onde ela estiver. Idempotente.
   *
   * Lê a fase em vez de a assumir: a compensação pode correr a partir de
   * qualquer passo, e é para isso que as arestas para `falhado` existem na
   * matriz (ver o `TRANSICOES`). Se já estiver em `falhado`, não faz nada — e
   * **tem** de ser assim, porque a compensação chama isto duas vezes: uma antes
   * de largar o canal (a base exige-o) e outra no fim.
   */
  async #transitarParaFalhado(
    id: string,
    tenantId: string,
    motivo: string,
  ): Promise<void> {
    const { rows } = await this.#d.sql.query<{ fase: Fase }>(SQL_FASE, [id, tenantId]);
    const fase = rows[0]?.fase;
    if (fase !== undefined && fase !== "falhado") {
      await this.transitar(id, tenantId, fase, "falhado", motivo);
    }
  }

  /** O *token* em claro, do cofre e da KEK. Nunca sai deste objecto. */
  async #tokenEmClaro(tenantId: string, ref: string): Promise<string> {
    const criptograma = await this.#d.cofre.get(ref);
    const [actual, anterior] = await this.#d.cofre.getRing(REF_DA_KEK);
    const versoes = await this.#d.cofre.versions(REF_DA_KEK);
    const anel: Record<string, string> = {};
    // O anel liga `kid → chave` pela ordem que a porta garante: `versions()[0]`
    // é a actual. Com uma versão só, `anterior` é `null` e o anel tem uma
    // entrada — é o caso de um cofre que nunca rodou, e o KAM-013 já trata esse
    // `null` da mesma maneira.
    if (versoes[0] !== undefined) anel[versoes[0]] = actual;
    if (versoes[1] !== undefined && anterior !== null) anel[versoes[1]] = anterior;
    return decifrarToken(anel, tenantId, criptograma);
  }

  /**
   * Escreve o registo de auditoria da recusa. **Numa transacção própria.**
   *
   * Corre **depois** de a transacção do 409 reverter, e por isso tem de ser
   * chamado por quem controla a transacção — o `ligar()` não o faz, porque a
   * ligação que ele tem é a que acabou de abortar. Ver o `docstring` da `0017`
   * para porque este registo não é o `platform.audit_log`.
   */
  async registarRecusa(entrada: ResultadoDoEs, motivo: string): Promise<void> {
    await this.#d.sql.query(SQL_REGISTAR_RECUSA, [
      entrada.tenant_id,
      entrada.waba_id,
      null,
      entrada.phone_number_id,
      resumoDoCode(entrada.code),
      motivo,
    ]);
  }

  /**
   * Passa a `abandonado` as tentativas paradas em `iniciado` há mais de 30 min.
   * **A segunda metade do critério 6.**
   *
   * Devolve quantas. O prazo entra por parâmetro para que um teste possa medir a
   * fronteira sem esperar meia hora — e o valor por omissão é o do contrato.
   */
  async abandonarVencidas(prazoMin: number = PRAZO_DE_ABANDONO_MIN): Promise<number> {
    const { rows } = await this.#d.sql.query<{ id: string }>(SQL_ABANDONAR, [prazoMin]);
    if (rows.length > 0) {
      this.#d.log?.warn({ outcome: "onboardings_abandonados" });
    }
    return rows.length;
  }

  #recusar(motivo: MotivoDeRecusa): void {
    this.#m.contar("es_onboarding_recusado_total", motivo);
  }

  #motivoDe(erro: unknown): string {
    if (erro instanceof NumeroJaUsadoError) return "phone_number_id de outro tenant";
    if (erro instanceof SubscricaoIncompletaError) return "subscricao incompleta";
    if (erro instanceof Error) return erro.name;
    return "falha desconhecida";
  }
}
