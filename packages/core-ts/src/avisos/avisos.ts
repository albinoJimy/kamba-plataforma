/**
 * O aviso ao dono por canal alternativo (KAM-115).
 *
 * É o `OwnerNotifier.notify(tenant_id, gatilho, episodio, params)` dos
 * *Detalhes Técnicos*, com os adaptadores por porta. O que esta classe faz, por
 * ordem: decide, registra, entrega, e conta o que aconteceu — nos dois sentidos,
 * porque o critério 7 diz que nenhum aviso se perde em silêncio.
 *
 * ## Registar antes de entregar, e não o contrário
 *
 * A ordem é deliberada e é a do `outbound` do KAM-015. Se o processo cair entre
 * as duas:
 *
 * * **registado e não entregue** descobre-se na varredura dos pendentes e
 *   reenvia-se — o `owner_notices_pendentes_idx` existe para isso;
 * * **entregue e não registado** não se descobre de maneira nenhuma, e o dono
 *   recebe o aviso outra vez na próxima tentativa.
 *
 * Entre perder tempo e repetir um aviso a quem já está a lidar com uma avaria,
 * escolhe-se perder tempo.
 *
 * ## O aviso sai pelos **dois** canais, e o painel não é só reserva
 *
 * O objectivo do ticket é «enviar ao dono um aviso idempotente **por e-mail e
 * por notificação do painel**». Os dois, sempre — e é isso que faz o «tenta o
 * painel» do critério 7 não precisar de um segundo caminho: quando o e-mail
 * falha, a notificação do painel já saiu. O que o critério 7 acrescenta é a
 * tarefa a T2 e a marca de inválido no contacto, e essas são escritas e não
 * entregas.
 *
 * As duas linhas contam como **um** aviso para o tecto diário. Contar duas fazia
 * o tecto de três valer um e meio, e um dono com um problema levava um aviso em
 * vez de três problemas distintos.
 *
 * ## O endereço em claro vive entre a decifra e a entrega
 *
 * Não há campo nesta classe que o guarde, não entra em nenhum erro, e não entra
 * em nenhuma métrica. É o DoD «Privacidade»: «endereço do dono só em cifra e
 * nunca em logs». A `Decifrar` é porta precisamente para que a KEK fique fora
 * deste módulo e o claro não tenha onde ficar.
 *
 * ## Nenhum `import` daqui vem do `../outbound`
 *
 * O critério 8 pede «nenhum adaptador de envio WhatsApp neste módulo (teste de
 * configuração)». O teste lê os `import` deste directório e recusa qualquer um
 * que venha do `../outbound` — que é onde vive o cliente da Meta — ou do
 * `../entrada`. É um teste e não uma promessa, porque uma promessa num comentário
 * não impede ninguém de escrever o `import`.
 */

import { randomBytes } from "node:crypto";

import {
  CANAIS,
  JANELA_DIARIA_MS,
  LEMBRETE_MAXIMO,
  OCTETOS_DO_TOKEN,
  PRAZO_DA_CONFIRMACAO_MS,
  type AbrirTarefa,
  type Aviso,
  type Canal,
  type ClienteSql,
  type Contacto,
  type Decifrar,
  type Gatilho,
  type LembreteDevido,
  type MotivoDeFalha,
  type NovoToken,
  type Notificador,
  type Relogio,
  type ResultadoDaVarredura,
  type ResultadoDoAviso,
} from "./contrato.ts";
import {
  SQL_CONFIRMAR,
  SQL_CONTACTO,
  SQL_EMITIR_CONFIRMACAO,
  SQL_ENTREGUE,
  SQL_EPISODIOS_PARA_LEMBRETE,
  SQL_FALHOU,
  SQL_HISTORICO,
  SQL_INVALIDAR,
  SQL_NOME_DA_LOJA,
  SQL_REGISTAR,
  SQL_TENANTS_ATIVOS,
  SQL_TENANTS_SEM_CONTACTO,
} from "./consultas.ts";
import {
  chaveDoEpisodio,
  condenaOEndereco,
  contactoUtilizavel,
  decidir,
  lembreteDevido,
  lembretesEsgotados,
  precisaDeEndereco,
  resumoDoToken,
} from "./decisao.ts";
import { construir } from "./modelos.ts";
import {
  METRICA_ENVIADOS,
  METRICA_FALHADOS,
  METRICA_SUPRIMIDOS,
  MetricasDoAviso,
  METRICAS_DO_AVISO,
} from "./metricas.ts";

/**
 * Os estados que podem entrar no texto de um aviso.
 *
 * Lista fechada, e é o critério 5 outra vez: o `{estado}` é um parâmetro de
 * modelo, e um parâmetro de texto livre era por onde a PII entrava. Estes são os
 * valores do `CHECK` da `0001` em `tenant_channels.estado` que fazem sentido num
 * aviso — um dono não precisa de saber que o canal está `a_verificar`.
 */
export const ESTADOS_NO_TEXTO = ["restrito", "desligado", "suspenso"] as const;
export type EstadoNoTexto = (typeof ESTADOS_NO_TEXTO)[number];

/**
 * O fuso em que a hora do aviso se escreve.
 *
 * `Africa/Luanda`, e não é escolha deste ticket: é a omissão de
 * `tenants.fuso_horario` (revisão `0007`) e é o fuso que o
 * `metering/consultas.ts` do KAM-023 usa para fechar o mês. Um aviso com a hora
 * em UTC dizia a um dono de Luanda que o canal caiu uma hora antes do que caiu.
 */
const FUSO = "Africa/Luanda";

/**
 * A hora como o dono a lê.
 *
 * `dateStyle: "long"`, e as três formas mediram-se antes de escolher — porque a
 * primeira versão desta nota dizia uma coisa falsa sobre a curta:
 *
 *     short    "09/11/26, 10:00"                 seis dígitos na data
 *     medium   "09/11/2026, 10:00"               **oito**, e a régua apanha-a
 *     long     "9 de novembro de 2026 às 10:00"  nenhuma corrida chega a sete
 *
 * Duas razões, e cada uma exclui uma das outras formas. A **`medium` está fora
 * por medição**: `09/11/2026` são oito dígitos separados por barras, e a régua do
 * `modelos.ts` que apanha telefones escritos à mão apanharia a data também — com
 * ela, o varrimento do critério 5 precisaria de uma excepção, e um varrimento com
 * excepções é mais fraco do que um sem. A **`short` está fora por legibilidade**:
 * `09/11/26` dá o ano em dois dígitos, e num aviso de avaria que o dono pode ler
 * dias depois a data tem de ser inequívoca. O mês por extenso é o que o teste
 * prende.
 */
export function horaDeLuanda(agora: Date): string {
  return new Intl.DateTimeFormat("pt-PT", {
    timeZone: FUSO,
    dateStyle: "long",
    timeStyle: "short",
  }).format(agora);
}

/** O estado que sai no texto quando quem chama não diz nenhum. */
const ESTADO_POR_OMISSAO: EstadoNoTexto = "restrito";

/** O que um pedido de aviso leva. */
export interface PedidoDeAviso {
  readonly tenantId: string;
  readonly gatilho: Gatilho;
  /** O que distingue este episódio do seguinte. Ver a `0019`. */
  readonly episodio: string;
  /** `0` o aviso próprio, `1` as 24 h, `2` as 72 h. */
  readonly lembrete?: number;
  /** Quando o evento aconteceu. É daqui que sai a latência do critério 3. */
  readonly ocorridoEm?: Date;
  /** O estado do canal, para o texto. De uma lista fechada. */
  readonly estado?: EstadoNoTexto;
}

interface Opcoes {
  readonly notificadores: readonly Notificador[];
  readonly decifrar: Decifrar;
  readonly abrirTarefa: AbrirTarefa;
  readonly relogio: Relogio;
  readonly novoToken?: NovoToken;
  /** A raiz do painel. **Sem *token* e sem identificador** (critério 5). */
  readonly painel: string;
  readonly metricas?: MetricasDoAviso;
}

/** Um notificador registado para um canal que não existe. */
export class CanalDesconhecidoError extends Error {
  override readonly name = "CanalDesconhecidoError";

  constructor(canal: string) {
    super(
      `notificador para canal desconhecido: ${JSON.stringify(canal)}. ` +
        `Os canais sao ${CANAIS.join(", ")} — e o WhatsApp nao e um deles ` +
        "(KAM-115, criterio 8)",
    );
  }
}

/** Dois notificadores para o mesmo canal. */
export class CanalDuplicadoError extends Error {
  override readonly name = "CanalDuplicadoError";

  constructor(canal: string) {
    super(`ha dois notificadores para o canal ${JSON.stringify(canal)}`);
  }
}

/** A ligação ao painel com algo que o critério 5 proíbe. */
export class PainelInvalidoError extends Error {
  override readonly name = "PainelInvalidoError";

  constructor(razao: string) {
    super(
      `a ligacao ao painel ${razao}. O criterio 5 pede «ligacao ao painel sem ` +
        "token nem identificador pessoal no URL»: um URL vai para a caixa de " +
        "correio do dono e para o historico do navegador, e um token num URL e " +
        "um token publicado",
    );
  }
}

/** Um `estado` fora da lista fechada do texto. */
export class EstadoInvalidoError extends Error {
  override readonly name = "EstadoInvalidoError";

  constructor(estado: string) {
    super(
      `estado ${JSON.stringify(estado)} nao esta na lista do texto ` +
        `(${ESTADOS_NO_TEXTO.join(", ")})`,
    );
  }
}

/**
 * Valida a raiz do painel.
 *
 * Recusa `?`, `#` e `=`: é a forma de um URL carregar um *token* ou um
 * identificador. Não se tenta ler o que vem depois nem decidir se é pessoal —
 * recusa-se a **forma**, porque uma lista de parâmetros proibidos era uma lista
 * que alguém havia de esquecer de actualizar.
 */
function validarPainel(painel: string): string {
  const limpo = painel.trim();
  if (limpo === "") throw new PainelInvalidoError("esta vazia");
  if (!/^https:\/\//.test(limpo)) throw new PainelInvalidoError("nao e https");
  if (/[?#=]/.test(limpo)) {
    throw new PainelInvalidoError("leva parametros de consulta ou fragmento");
  }
  return limpo;
}

/** A linha de `owner_notices` como a base a devolve. */
interface LinhaDeAviso {
  readonly id: string;
  readonly tenant_id: string;
  readonly gatilho: Gatilho;
  readonly episodio: string;
  readonly lembrete: number;
  readonly canal: Canal;
  readonly estado: Aviso["estado"];
  readonly tentativas: number;
  readonly falha_motivo: MotivoDeFalha | null;
  readonly criado_at: Date;
  readonly entregue_at: Date | null;
}

function paraAviso(linha: LinhaDeAviso): Aviso {
  return {
    id: linha.id,
    tenantId: linha.tenant_id,
    gatilho: linha.gatilho,
    episodio: linha.episodio,
    // `Number(...)` e nao o valor cru: o `smallint` chega como numero no `pg`,
    // mas chega como **cadeia** em alguns condutores (o `pg8000` da bateria
    // Python devolve listas e o `pg` devolve `bigint` em texto), e um `lembrete`
    // em texto fazia `anterior.lembrete !== lembrete` ser sempre verdade — a
    // idempotencia do criterio 2 passava a nao apanhar nada, em silencio.
    lembrete: Number(linha.lembrete),
    canal: linha.canal,
    estado: linha.estado,
    tentativas: Number(linha.tentativas),
    falhaMotivo: linha.falha_motivo,
    criadoAt: linha.criado_at,
    entregueAt: linha.entregue_at,
  };
}

/** A linha de `owner_contacts` como a base a devolve. */
interface LinhaDeContacto {
  readonly id: string;
  readonly tenant_id: string;
  readonly canal: Canal;
  readonly endereco_enc: Uint8Array;
  readonly verificado_at: Date | null;
  readonly invalido_at: Date | null;
  readonly motivo_invalido: MotivoDeFalha | null;
}

function paraContacto(linha: LinhaDeContacto): Contacto {
  return {
    id: linha.id,
    tenantId: linha.tenant_id,
    canal: linha.canal,
    enderecoEnc: linha.endereco_enc,
    verificadoAt: linha.verificado_at,
    invalidoAt: linha.invalido_at,
    motivoInvalido: linha.motivo_invalido,
  };
}

/** O aviso ao dono por canal alternativo. */
export class AvisoAoDono {
  readonly #porCanal = new Map<Canal, Notificador>();
  readonly #decifrar: Decifrar;
  readonly #abrirTarefa: AbrirTarefa;
  readonly #relogio: Relogio;
  readonly #novoToken: NovoToken;
  readonly #painel: string;
  readonly #metricas: MetricasDoAviso;

  constructor(opcoes: Opcoes) {
    for (const notificador of opcoes.notificadores) {
      if (!(CANAIS as readonly string[]).includes(notificador.canal)) {
        throw new CanalDesconhecidoError(notificador.canal);
      }
      if (this.#porCanal.has(notificador.canal)) {
        throw new CanalDuplicadoError(notificador.canal);
      }
      this.#porCanal.set(notificador.canal, notificador);
    }
    this.#decifrar = opcoes.decifrar;
    this.#abrirTarefa = opcoes.abrirTarefa;
    this.#relogio = opcoes.relogio;
    this.#novoToken = opcoes.novoToken ?? (() => randomBytes(OCTETOS_DO_TOKEN));
    this.#painel = validarPainel(opcoes.painel);
    this.#metricas = opcoes.metricas ?? METRICAS_DO_AVISO;
  }

  /**
   * Avisa o dono, se as regras o deixarem.
   *
   * Corre **dentro da transacção de quem chama**: o `cliente` é a ligação dele.
   * Ver a nota das portas do `contrato.ts` — com cada passo na sua transacção,
   * um processo que caia pelo meio deixa um aviso registado que nunca sai.
   */
  async notificar(cliente: ClienteSql, pedido: PedidoDeAviso): Promise<ResultadoDoAviso> {
    const agora = this.#relogio();
    const lembrete = pedido.lembrete ?? 0;
    const historico = await this.#historico(cliente, pedido.tenantId, agora);

    const decisao = decidir(agora, pedido.gatilho, pedido.episodio, lembrete, historico);
    if (!decisao.avisar) {
      const motivo = decisao.motivo ?? "ja_avisado";
      // O gatilho desconhecido conta com a etiqueta `nenhum`, porque por
      // definicao ele nao e um dos cinco. Ver a nota do `metricas.ts`.
      const etiqueta = motivo === "gatilho_desconhecido" ? "nenhum" : pedido.gatilho;
      this.#metricas.contar(METRICA_SUPRIMIDOS, [etiqueta, motivo]);
      return { avisos: [], suprimido: motivo, tarefaAberta: false };
    }

    const estado = pedido.estado ?? ESTADO_POR_OMISSAO;
    if (!(ESTADOS_NO_TEXTO as readonly string[]).includes(estado)) {
      throw new EstadoInvalidoError(estado);
    }

    const loja = await this.#nomeDaLoja(cliente, pedido.tenantId);
    const texto = construir(pedido.gatilho, {
      loja,
      estado,
      hora: horaDeLuanda(agora),
      painel: this.#painel,
    });
    const renderizado = { gatilho: pedido.gatilho, painel: this.#painel, ...texto };
    const chave = chaveDoEpisodio(pedido.tenantId, pedido.gatilho, pedido.episodio);

    const escritos: Aviso[] = [];
    let tarefaAberta = false;

    for (const canal of CANAIS) {
      const notificador = this.#porCanal.get(canal);
      if (notificador === undefined) continue;

      const registado = await this.#registar(
        cliente,
        pedido,
        chave,
        lembrete,
        canal,
        agora,
      );
      if (registado === null) {
        // Outra transaccao escreveu esta mesma linha. E a idempotencia do
        // criterio 2 a funcionar sob concorrencia, e nao um erro: nao se entrega
        // nada, porque quem escreveu a linha e quem entrega.
        continue;
      }

      const destino = await this.#destino(cliente, pedido.tenantId, canal);
      if (precisaDeEndereco(canal) && destino === null) {
        // O criterio 6: tenant sem contacto verificado. **Nao se marca o
        // contacto invalido** — nao ha contacto a marcar —, e e por isso que o
        // `sem_contacto` nao esta nos `MOTIVOS_DE_INVALIDEZ`.
        // **A linha entra nos `avisos` como qualquer outra**, e a primeira
        // versao descartava-a: ela **foi escrita**, e o campo esta documentado
        // como «as linhas escritas». Quem chama precisa de a ver para saber que
        // o aviso existe e falhou — sem ela, o resultado dizia que nada se
        // escreveu num caminho que escreve. Achado da revisao adversarial.
        const semContacto = await this.#falhar(
          cliente, pedido.tenantId, registado.id, "sem_contacto", agora,
        );
        if (semContacto !== null) escritos.push(semContacto);
        this.#metricas.contar(METRICA_FALHADOS, [canal, "sem_contacto"]);
        await this.#abrirTarefa({
          tenantId: pedido.tenantId,
          gatilho: pedido.gatilho,
          assunto: "tenant sem contacto alternativo verificado",
        });
        tarefaAberta = true;
        continue;
      }

      const resultado = await notificador.entregar(destino, renderizado);
      if (resultado.entregue) {
        const entregue = await this.#entregue(cliente, pedido.tenantId, registado.id, agora);
        if (entregue !== null) escritos.push(entregue);
        this.#metricas.contar(METRICA_ENVIADOS, [pedido.gatilho, canal]);
        if (pedido.ocorridoEm !== undefined) {
          this.#metricas.observarLatencia(
            (agora.getTime() - pedido.ocorridoEm.getTime()) / 1_000,
          );
        }
        continue;
      }

      const motivo = resultado.motivo ?? "indisponivel";
      const falhado = await this.#falhar(cliente, pedido.tenantId, registado.id, motivo, agora);
      if (falhado !== null) escritos.push(falhado);
      this.#metricas.contar(METRICA_FALHADOS, [canal, motivo]);
      if (condenaOEndereco(motivo)) {
        await cliente.query(SQL_INVALIDAR, [pedido.tenantId, canal, motivo, agora]);
      }
      await this.#abrirTarefa({
        tenantId: pedido.tenantId,
        gatilho: pedido.gatilho,
        assunto: `aviso nao entregue por ${canal}: ${motivo}`,
      });
      tarefaAberta = true;
    }

    return { avisos: escritos, suprimido: null, tarefaAberta };
  }

  /**
   * Emite a ligação de confirmação de um contacto (critério 6).
   *
   * Devolve o *token* **em bruto**, uma vez só: é quem chama que o põe no URL, e
   * a base só guarda o resumo. Quem entrega a ligação é o KAM-086, que é quem
   * capta o e-mail — este ticket emite, guarda e confirma.
   */
  async emitirConfirmacao(
    cliente: ClienteSql,
    tenantId: string,
    canal: Canal = "email",
  ): Promise<{ readonly token: Uint8Array; readonly expiraEm: Date }> {
    const agora = this.#relogio();
    const token = this.#novoToken();
    const expiraEm = new Date(agora.getTime() + PRAZO_DA_CONFIRMACAO_MS);
    await cliente.query(SQL_EMITIR_CONFIRMACAO, [
      tenantId,
      canal,
      resumoDoToken(token),
      expiraEm,
      agora,
    ]);
    return { token, expiraEm };
  }

  /**
   * Confirma o contacto com o *token* da ligação.
   *
   * `true` se confirmou. A comparação e o prazo estão **na instrução** e não
   * aqui: ver a nota do `SQL_CONFIRMAR`.
   */
  async confirmar(
    cliente: ClienteSql,
    tenantId: string,
    token: Uint8Array,
    canal: Canal = "email",
  ): Promise<boolean> {
    const agora = this.#relogio();
    const { rows } = await cliente.query(SQL_CONFIRMAR, [
      tenantId,
      canal,
      resumoDoToken(token),
      agora,
    ]);
    return rows.length === 1;
  }

  /**
   * Varre os episódios cujo lembrete está devido (critério 4).
   *
   * Corre como `kamba_batch`, sem contexto de tenant: um lembrete que venceu não
   * é problema de uma loja. Ver a nota do `consultas.ts` e as concessões da
   * `0019`.
   *
   * **Não decide se o estado persiste**, e isso é de quem chama: o módulo não
   * sabe se um canal continua desligado, e inventar essa leitura era duplicar o
   * que o KAM-017 e o KAM-021 já sabem. O que devolve são os episódios em que,
   * **se o estado persistir**, está na hora.
   */
  async varrerLembretes(cliente: ClienteSql): Promise<ResultadoDaVarredura> {
    const agora = this.#relogio();
    const desde = new Date(agora.getTime() - 4 * JANELA_DIARIA_MS);
    const { rows } = await cliente.query<{
      readonly tenant_id: string;
      readonly gatilho: Gatilho;
      readonly episodio: string;
      readonly primeiro_em: Date;
      readonly ultimo_lembrete: number;
    }>(SQL_EPISODIOS_PARA_LEMBRETE, [desde, LEMBRETE_MAXIMO]);

    const lembretes: LembreteDevido[] = [];
    const esgotados: string[] = [];
    for (const linha of rows) {
      const enviado = Number(linha.ultimo_lembrete);
      // **Primeiro o esgotamento, e e o `lembretesEsgotados` que o diz.** A
      // primeira versao tinha aqui um `if (devido > LEMBRETE_MAXIMO)` que
      // **nunca podia ser verdade** — o `lembreteDevido` nao devolve mais do
      // que o numero de atrasos —, pelo que o «depois para e abre tarefa a T2»
      // do criterio 4 era codigo morto. E a mesma classe de achado que o
      // KAM-018 escreveu: «uma guarda inalcancavel da a ilusao de proteger». O
      // `lembretesEsgotados` existia, estava testado e **nao era chamado por
      // ninguem**; e esta a pergunta que ele responde.
      if (lembretesEsgotados(agora, linha.primeiro_em, enviado)) {
        esgotados.push(linha.tenant_id);
        await this.#abrirTarefa({
          tenantId: linha.tenant_id,
          gatilho: linha.gatilho,
          assunto: "lembretes esgotados e o estado persiste",
        });
        continue;
      }
      const devido = lembreteDevido(agora, linha.primeiro_em);
      if (devido === null || devido <= enviado) continue;
      lembretes.push({
        tenantId: linha.tenant_id,
        gatilho: linha.gatilho,
        episodio: linha.episodio,
        lembrete: devido,
      });
    }
    return { lembretes, esgotados };
  }

  /**
   * Conta os tenants `ativo` sem contacto alternativo verificado (critério 6).
   *
   * Devolve os `id` **e** publica os dois números na métrica. Os `id` não entram
   * na métrica: um `tenant_id` é um UUID com hífenes e **levanta** na validação
   * de etiquetas (OBS-I). Quem precisa dos `id` é a tarefa a T2, que é uma
   * chamada e não uma série.
   */
  async varrerContactos(cliente: ClienteSql): Promise<readonly string[]> {
    const { rows } = await cliente.query<{ readonly id: string }>(SQL_TENANTS_SEM_CONTACTO);
    const { rows: totais } = await cliente.query<{ readonly quantos: number }>(
      SQL_TENANTS_ATIVOS,
    );
    const sem = rows.length;
    // **Duas consultas e nao uma com `count(*) FILTER`**: a primeira devolve os
    // `id`, que a tarefa a T2 precisa, e a segunda devolve o denominador, que a
    // metrica precisa. Uma consulta so que fizesse as duas coisas obrigava a
    // trazer todos os tenants `ativo` para contar os que tem contacto — e o
    // numerador e, por construcao, a parte pequena.
    const total = Number(totais[0]?.quantos ?? sem);
    this.#metricas.observarContactos(sem, Math.max(total - sem, 0));
    return rows.map((linha) => linha.id);
  }

  async #historico(
    cliente: ClienteSql,
    tenantId: string,
    agora: Date,
  ): Promise<readonly Aviso[]> {
    const desde = new Date(agora.getTime() - JANELA_DIARIA_MS);
    const { rows } = await cliente.query<LinhaDeAviso>(SQL_HISTORICO, [tenantId, desde]);
    return rows.map(paraAviso);
  }

  async #nomeDaLoja(cliente: ClienteSql, tenantId: string): Promise<string> {
    const { rows } = await cliente.query<{ readonly nome: string }>(SQL_NOME_DA_LOJA, [
      tenantId,
    ]);
    // `?? "a sua loja"` e nao um erro: um aviso sem nome de loja continua a ser
    // um aviso util, e recusar o aviso porque a leitura do nome nao devolveu
    // linha era deixar o dono sem saber que o canal caiu por uma razao que nada
    // tem a ver com o canal.
    return rows[0]?.nome ?? "a sua loja";
  }

  async #registar(
    cliente: ClienteSql,
    pedido: PedidoDeAviso,
    chave: Buffer,
    lembrete: number,
    canal: Canal,
    agora: Date,
  ): Promise<Aviso | null> {
    const { rows } = await cliente.query<LinhaDeAviso>(SQL_REGISTAR, [
      pedido.tenantId,
      pedido.gatilho,
      pedido.episodio,
      chave,
      lembrete,
      canal,
      agora,
    ]);
    const linha = rows[0];
    return linha === undefined ? null : paraAviso(linha);
  }

  async #destino(
    cliente: ClienteSql,
    tenantId: string,
    canal: Canal,
  ): Promise<string | null> {
    if (!precisaDeEndereco(canal)) return null;
    const { rows } = await cliente.query<LinhaDeContacto>(SQL_CONTACTO, [tenantId, canal]);
    const linha = rows[0];
    const contacto = linha === undefined ? null : paraContacto(linha);
    if (!contactoUtilizavel(contacto) || contacto === null) return null;
    return this.#decifrar(tenantId, contacto.enderecoEnc);
  }

  async #entregue(
    cliente: ClienteSql,
    tenantId: string,
    id: string,
    agora: Date,
  ): Promise<Aviso | null> {
    const { rows } = await cliente.query<LinhaDeAviso>(SQL_ENTREGUE, [tenantId, id, agora]);
    const linha = rows[0];
    return linha === undefined ? null : paraAviso(linha);
  }

  async #falhar(
    cliente: ClienteSql,
    tenantId: string,
    id: string,
    motivo: MotivoDeFalha,
    agora: Date,
  ): Promise<Aviso | null> {
    const { rows } = await cliente.query<LinhaDeAviso>(SQL_FALHOU, [
      tenantId,
      id,
      motivo,
      agora,
    ]);
    const linha = rows[0];
    return linha === undefined ? null : paraAviso(linha);
  }
}
