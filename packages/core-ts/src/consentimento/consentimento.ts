/**
 * O `ConsentGate`: a barreira anterior ao AGR (KAM-022).
 *
 * ## A ordem dos passos, e porque é esta
 *
 * 1. **lê a versão vigente do texto.** Se não houver, **pára e não autoriza** —
 *    ver «a falha fechada», abaixo;
 * 2. **lê o estado do consentimento** na vista `consent_actual`, contra essa
 *    versão;
 * 3. **conta os avisos já enviados** nesta conversa, e só quando a decisão
 *    pode depender disso (texto livre ou «outro» sem consentimento válido);
 * 4. **decide** pela matriz de `decisao.ts`;
 * 5. **registra a prova**, quando a acção o manda, e **antes** de autorizar o
 *    AGR;
 * 6. **envia a mensagem**, emite o evento e muda o modo da conversa.
 *
 * O passo 5 está antes do 6 de propósito, e é o critério 2 por extenso:
 * «"Continuar" grava 1 linha `consent_event` […] **e só então** o AGR é
 * invocado». Autorizar primeiro e gravar depois deixava uma janela em que o
 * assistente já está a tratar dados de quem ainda não consta como tendo
 * consentido — e é essa linha que um auditor vai pedir.
 *
 * ## A falha fechada, e porque ela é a decisão certa
 *
 * A `consent_texts` nasce **vazia**: o texto é jurídico e está «a confirmar por
 * parecer» (KAM-104). Sem versão vigente, o gate devolve `enviar_aviso` com
 * `invocaAgr: false` e **não envia nada** — porque não há nada para mostrar.
 *
 * O efeito prático é que **a loja fica muda até o texto existir**, e isso é
 * desconfortável e é o lado certo: a alternativa era deixar o assistente tratar
 * mensagens de clientes sem lhes ter mostrado o aviso, que é o que o ADR-010
 * proíbe e o que o `E3` req. 15 obriga a fazer. Um defeito que faz a loja ficar
 * calada vê-se no primeiro dia; um que trata dados sem base legal vê-se quando
 * chega a multa (`E3`: USD 505 mil, 2026-06-24).
 *
 * É por isso que a `consent_blocked_total{accao}` existe: ela é o que distingue
 * «os clientes estão todos a consentir» de «não há texto e eu estou a barrar
 * tudo».
 *
 * ## O que este módulo **não** faz, e é escopo e não esquecimento
 *
 * * **Não invoca o AGR.** Devolve `invocaAgr`, e quem monta o *job* é o
 *   encaminhador do KAM-013/KAM-014. A propriedade do critério 4 — «0 *jobs*
 *   sem consentimento válido anterior» — só é demonstrável se a decisão for a
 *   única porta, e é.
 * * **Não escreve `conversations.mode`.** O `UPDATE` que a `0009` concede a
 *   `kamba_app` é por coluna e **não inclui o `mode`**, por decisão do KAM-014:
 *   ele é de KAM-018. Este módulo diz que a conversa deve passar a `humano` ou
 *   a `pausada` (os campos `passaAHumano` e `pausaAConversa`) e chama a porta
 *   `MudarModo` quando ela está ligada.
 * * **Não publica texto.** A `0015` não dá `INSERT` em `consent_texts` a
 *   `kamba_app`: quem publica uma versão é operação.
 * * **Não trata os direitos do titular** (KAM-070) nem o ToS/DPA da PME
 *   (KAM-090).
 */

import type { Logger } from "../logger/index.ts";

import {
  FINALIDADE_DE_MARKETING,
  FINALIDADE_DO_AVISO,
  FINALIDADE_DO_HUMANO,
  PREFIXO_DO_AVISO,
  type ClienteSql,
  type CorpoDoAviso,
  type Decisao,
  type Dependencias,
  type DestinoDoAviso,
  type Emitir,
  type Entrada,
  type EnviarAviso,
  type EstadoDoConsentimento,
  type Finalidade,
  type MudarModo,
  type TextoVigente,
  BOTOES,
} from "./contrato.ts";
import {
  SQL_AVISOS_ENVIADOS,
  SQL_ESTADO,
  SQL_NOME_DA_LOJA,
  SQL_REGISTAR,
  SQL_TEXTO_VIGENTE,
} from "./consultas.ts";
import {
  accaoDoAviso,
  autorizaAgr,
  enviaMensagem,
  estadoDoConsentimento,
  linhaDaEntrada,
  registaProva,
} from "./decisao.ts";
import {
  METRICAS_DO_CONSENTIMENTO,
  METRICA_ACEITES,
  METRICA_AVISOS,
  METRICA_BARRADAS,
  METRICA_OPTOUT,
  MetricasDoConsentimento,
} from "./metricas.ts";
import { preencher, provaDeConsentimento } from "./prova.ts";

/** O que uma passagem pelo gate precisa de saber da mensagem que chegou. */
export interface Mensagem {
  readonly tenantId: string;
  readonly contactId: string;
  readonly conversationId: string;
  readonly channelId: string;
  readonly phoneNumberId: string;
  /** O `wamid` da mensagem que chegou, como a Meta o deu. */
  readonly wamid: string;
  /** A hora **da Meta**, em ISO-8601. É ela que entra na prova. */
  readonly hora: string;
  readonly entrada: Entrada;
}

/** O resultado completo: a decisão, e o que de facto aconteceu. */
export interface Resultado extends Decisao {
  /** `true` quando esta chamada escreveu uma linha nova de prova. */
  readonly registou: boolean;
  /** A versão vigente do texto, ou `null` quando não há nenhuma. */
  readonly versao: string | null;
  readonly estado: EstadoDoConsentimento;
}

export class ConsentGate {
  readonly #bd: ClienteSql;
  readonly #enviar: EnviarAviso;
  readonly #emitir: Emitir | null;
  readonly #modo: MudarModo | null;
  readonly #log: Logger | undefined;
  readonly #metricas: MetricasDoConsentimento;
  readonly #agora: (() => Date) | undefined;
  readonly #nomeDaLoja: ((tenantId: string) => Promise<string>) | undefined;

  constructor(dependencias: Dependencias & { metricas?: MetricasDoConsentimento }) {
    this.#bd = dependencias.bd;
    this.#enviar = dependencias.enviar;
    this.#emitir = dependencias.emitir ?? null;
    this.#modo = dependencias.modo ?? null;
    this.#log = dependencias.log;
    this.#metricas = dependencias.metricas ?? METRICAS_DO_CONSENTIMENTO;
    this.#agora = dependencias.agora;
    this.#nomeDaLoja = dependencias.nomeDaLoja;
  }

  /** O instante a passar à base, ou `null` para ela usar o `now()` dela. */
  #instante(): string | null {
    const agora = this.#agora?.();
    return agora === undefined ? null : agora.toISOString();
  }

  /** A versão vigente do aviso, ou `null` quando não há nenhuma publicada. */
  async textoVigente(finalidade: Finalidade = FINALIDADE_DO_AVISO): Promise<TextoVigente | null> {
    const linhas = await this.#bd.query<{ version: string; texto: string }>(
      SQL_TEXTO_VIGENTE,
      [finalidade, this.#instante()],
    );
    const linha = linhas.rows[0];
    if (linha === undefined) {
      // **Não é silêncio.** Uma loja muda é o pior desfecho possível e o mais
      // fácil de não notar, e o `outcome` é a única forma de o dizer dentro dos
      // nove campos que a política de registo permite.
      this.#log?.error({ outcome: "aviso_sem_versao_vigente" });
      return null;
    }
    return { version: linha.version, texto: linha.texto };
  }

  /** O estado do consentimento de um contacto, contra a versão dada. */
  async estado(
    tenantId: string,
    contactId: string,
    versaoVigente: string,
    finalidade: Finalidade = FINALIDADE_DO_AVISO,
  ): Promise<EstadoDoConsentimento> {
    const linhas = await this.#bd.query<{ accepted: boolean; text_version: string }>(
      SQL_ESTADO,
      [tenantId, contactId, finalidade],
    );
    return estadoDoConsentimento(linhas.rows[0] ?? null, versaoVigente);
  }

  /** Quantos avisos já saíram nesta conversa (critério 3). */
  async avisosEnviados(tenantId: string, conversationId: string): Promise<number> {
    const linhas = await this.#bd.query<{ avisos: number | string }>(
      SQL_AVISOS_ENVIADOS,
      [tenantId, conversationId, `${PREFIXO_DO_AVISO}:${conversationId}:%`],
    );
    return Number(linhas.rows[0]?.avisos ?? 0);
  }

  /** O nome da loja, para o marcador do texto. */
  async #loja(tenantId: string): Promise<string> {
    if (this.#nomeDaLoja !== undefined) return this.#nomeDaLoja(tenantId);
    const linhas = await this.#bd.query<{ nome: string }>(SQL_NOME_DA_LOJA, [tenantId]);
    return linhas.rows[0]?.nome ?? "";
  }

  /**
   * Registra uma prova, e diz se foi **esta** chamada a escrevê-la.
   *
   * `false` significa «esta prova já estava registada», e é a idempotência do
   * critério 2 — da base, pelo `ON CONFLICT ... DO NOTHING RETURNING` vazio.
   */
  async #registar(
    mensagem: Mensagem,
    finalidade: Finalidade,
    versao: string,
    aceitou: boolean,
    textoMostrado: string,
  ): Promise<boolean> {
    const prova = provaDeConsentimento({
      textoMostrado,
      contactId: mensagem.contactId,
      wamid: mensagem.wamid,
      hora: mensagem.hora,
    });
    const linhas = await this.#bd.query(SQL_REGISTAR, [
      mensagem.tenantId,
      mensagem.contactId,
      finalidade,
      versao,
      aceitou,
      "whatsapp",
      prova,
      mensagem.hora,
    ]);
    return linhas.rows.length > 0;
  }

  /** A chave de idempotência do n-ésimo aviso de uma conversa. */
  #chaveDoAviso(conversationId: string, n: number): string {
    return `${PREFIXO_DO_AVISO}:${conversationId}:${n}`;
  }

  /**
   * A passagem pelo gate. **É a única porta para o AGR.**
   *
   * Devolve sempre um resultado — nunca levanta por falta de texto, por falta de
   * consentimento ou por a mensagem não se compreender. O que levanta é um
   * defeito de programação (uma métrica que não existe, um sufixo fora da lista
   * fechada), e isso é deliberado: o caminho de uma mensagem de um cliente não
   * se interrompe por uma decisão de política, interrompe-se por um defeito.
   */
  async tratar(mensagem: Mensagem): Promise<Resultado> {
    const vigente = await this.textoVigente();
    if (vigente === null) {
      // **Falha fechada.** Sem aviso para mostrar não há consentimento a
      // registar, e o AGR não corre. Ver a nota do módulo.
      this.#metricas.contar(METRICA_BARRADAS, "enviar_aviso");
      return {
        accao: "enviar_aviso",
        invocaAgr: false,
        passaAHumano: false,
        pausaAConversa: false,
        mensagens: 0,
        registou: false,
        versao: null,
        estado: "ausente",
      };
    }

    const estado = await this.estado(mensagem.tenantId, mensagem.contactId, vigente.version);
    const linha = linhaDaEntrada(mensagem.entrada);
    // A contagem só se lê quando a decisão pode depender dela: um botão e um
    // «PARAR» decidem-se sem ela, e uma consulta por mensagem que não a usa era
    // uma leitura por cada mensagem de cada conversa da plataforma.
    const precisaDaContagem =
      (linha === "texto" || linha === "outro") && estado !== "valido";
    const avisos = precisaDaContagem
      ? await this.avisosEnviados(mensagem.tenantId, mensagem.conversationId)
      : 0;

    const accao = accaoDoAviso(mensagem.entrada, estado, avisos);

    // **O texto preenchido lê-se tarde, e isso foi um defeito medido — duas
    // vezes.** A primeira versão calculava-o aqui, sempre, incluindo no caso
    // comum (`seguir`): uma consulta ao nome da loja por **cada** mensagem de
    // cada conversa da plataforma, para um valor que aquele caminho não usa.
    //
    // E a **correcção** teve o seu próprio defeito, que vale mais do que o
    // primeiro: a condição era `enviaMensagem(accao) || accao ===
    // "passar_a_humano"`, e o `registar_e_seguir` — que é o «Continuar», o
    // caminho mais importante do ticket — **não envia mensagem**. Caiu fora, e a
    // prova do consentimento passava a ser calculada sobre uma cadeia vazia.
    // Quem a apanhava era «**a prova guardada e a que se recalcula**» do ensaio
    // contra a base, que recalcula o resumo e compara octeto a octeto; o
    // `enviaMensagem` sozinho não sabia dizer isto.
    //
    // As duas listas estão agora **nomeadas** em `decisao.ts` — quem envia e
    // quem registra prova —, e é isso que impede uma acção nova de cair em
    // silêncio por nenhuma das duas.
    const precisaDoTexto = enviaMensagem(accao) || registaProva(accao);
    const textoMostrado = precisaDoTexto
      ? preencher(vigente.texto, await this.#loja(mensagem.tenantId))
      : "";

    let registou = false;
    if (accao === "registar_e_seguir") {
      // **A prova escreve-se antes de o AGR ser autorizado** (critério 2).
      registou = await this.#registar(
        mensagem,
        FINALIDADE_DO_AVISO,
        vigente.version,
        true,
        textoMostrado,
      );
      if (registou) {
        this.#metricas.contar(METRICA_ACEITES);
        await this.#emitir?.(
          "consent.recorded",
          mensagem.tenantId,
          mensagem.contactId,
          FINALIDADE_DO_AVISO,
        );
      }
    } else if (accao === "registar_revogacao") {
      registou = await this.#registar(
        mensagem,
        FINALIDADE_DE_MARKETING,
        vigente.version,
        false,
        textoMostrado,
      );
      if (registou) {
        this.#metricas.contar(METRICA_OPTOUT);
        this.#log?.warn({ outcome: "consentimento_revogado" });
        await this.#emitir?.(
          "consent.withdrawn",
          mensagem.tenantId,
          mensagem.contactId,
          FINALIDADE_DE_MARKETING,
        );
      }
    } else if (accao === "passar_a_humano") {
      // «Falar com a loja» passa a conversa a uma pessoa **sem tratar dados por
      // IA** (critério 3), e isso registra-se: o aviso foi apresentado, e é a
      // `atendimento` que o diz. Não é um consentimento de *marketing* nem de
      // transacção — é o facto de a pessoa ter pedido para falar com a loja
      // depois de ver o aviso.
      registou = await this.#registar(
        mensagem,
        FINALIDADE_DO_HUMANO,
        vigente.version,
        true,
        textoMostrado,
      );
      if (registou) {
        await this.#emitir?.(
          "consent.recorded",
          mensagem.tenantId,
          mensagem.contactId,
          FINALIDADE_DO_HUMANO,
        );
      }
    }

    let mensagens = 0;
    if (enviaMensagem(accao)) {
      const chave =
        accao === "enviar_aviso"
          ? this.#chaveDoAviso(mensagem.conversationId, avisos + 1)
          : `${accao}:${mensagem.wamid}`;
      const destino: DestinoDoAviso = {
        tenantId: mensagem.tenantId,
        contactId: mensagem.contactId,
        conversationId: mensagem.conversationId,
        channelId: mensagem.channelId,
        phoneNumberId: mensagem.phoneNumberId,
        idempotencyKey: chave,
      };
      // **Os botões vão também no «Saber mais», e isso é o critério 3 a ser
      // cumprido em UMA mensagem.** Ele pede «envia o texto completo/ligação à
      // política **e repete o aviso**», que são duas coisas — e o critério 1
      // promete «exactamente 1 mensagem de saída». A primeira versão enviava o
      // texto **sem** botões e deixava o cliente sem acção nenhuma, que é pior
      // do que qualquer das duas leituras.
      //
      // O texto é **um** por versão e finalidade: a `consent_texts` não tem
      // «aviso curto» e «texto completo», e a distinção que o critério
      // pressupõe pedia uma coluna a mais ou uma segunda linha — uma decisão
      // para o parecer, porque o texto que foi revisto é este. Fica na dívida
      // 78. A confirmação do «PARAR» é a única sem botões: ela responde e não
      // pergunta.
      const corpo: CorpoDoAviso =
        accao === "registar_revogacao"
          ? { texto: textoMostrado, botoes: [] }
          : { texto: textoMostrado, botoes: [...BOTOES] };
      const wamid = await this.#enviar(destino, corpo);
      if (wamid === null) {
        // **Não é falha silenciosa.** Uma mensagem que não saiu é uma loja que
        // não respondeu, e o critério 1 promete «exactamente 1 mensagem de
        // saída».
        this.#log?.error({ outcome: "aviso_nao_saiu" });
      } else {
        mensagens = 1;
        if (accao === "enviar_aviso") this.#metricas.contar(METRICA_AVISOS);
      }
    }

    const invoca = autorizaAgr(accao) && (accao !== "registar_e_seguir" || registou);
    if (!invoca) this.#metricas.contar(METRICA_BARRADAS, accao);

    const passa = accao === "passar_a_humano";
    const pausa = accao === "registar_revogacao";
    if (passa || pausa) {
      await this.#modo?.(
        mensagem.tenantId,
        mensagem.conversationId,
        passa ? "humano" : "pausada",
      );
    }

    return {
      accao,
      invocaAgr: invoca,
      passaAHumano: passa,
      pausaAConversa: pausa,
      mensagens,
      registou,
      versao: vigente.version,
      estado,
    };
  }
}
