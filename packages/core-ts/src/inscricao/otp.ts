/**
 * O OTP de posse do telefone, e o disjuntor do orçamento de SMS (KAM-086,
 * critérios 5 e 6).
 *
 * «OTP de 6 dígitos, TTL 5 min, ≤ 5 tentativas por código, ≤ 3 envios/hora/
 * telefone, intervalo de 60 s (*propostas*); guardado só como HMAC; comparação
 * em tempo constante.»
 *
 * «Só prefixo `+244` no Piloto; orçamento diário de SMS (*proposta*) com
 * disjuntor: ao esgotar, os envios pausam e há alerta, sem perder casos já
 * abertos.»
 *
 * ## Todos os números deste ficheiro são ***propostas***
 *
 * Os seis — dígitos, TTL, tentativas, envios por hora, intervalo e orçamento
 * diário — estão escritos como *propostas* no próprio critério, e nenhum sai de
 * medição nenhuma: não há Piloto a correr e não há cotação de agregador
 * (`../../../../docs/evidencia/KAM-116.md`, critério 1). Entram como valores por
 * omissão de `OpcoesDeOtp`, configuráveis por quem monta o serviço, que é o que
 * o *Handoff* do bloco manda por extenso («limiares OTP/limites são propostas a
 * calibrar (configuráveis)»).
 *
 * **O orçamento diário é o que menos se pode fixar.** Ele é dinheiro: o preço
 * por SMS é **NÃO VERIFICADO** porque não há agregador escolhido, pelo que
 * «quinhentos envios» não é um valor em kwanzas que alguém aprovou — é um tecto
 * de volume que impede uma noite de abuso de gastar o mês. O número sai da
 * configuração no dia em que a cotação existir.
 *
 * ## Três coisas que o critério 5 pede e que são a mesma coisa dita a três níveis
 *
 *     ≤ 3 envios/hora/telefone   impede o telefone de ser usado como campainha
 *     intervalo de 60 s          impede a rajada dentro da mesma hora
 *     orçamento diário           impede a soma de todos os telefones
 *
 * As três são a mesma pergunta — quantas ocorrências desta chave nesta janela —
 * e por isso correm todas sobre a porta `Contadores` do `./contrato.ts`, com
 * chaves e janelas diferentes. A alternativa era três contadores, três
 * implementações e três maneiras de errar a janela.
 *
 * ## O código nunca é uma `string` que ande por aí
 *
 * É gerado aqui, embrulhado num `CodigoOtp` do `../sms/codigo.ts` — que mascara
 * em todas as conversões para texto — e entregue à porta `OtpProvider`. O que
 * fica guardado é o **HMAC**, e o HMAC leva o `onboarding_id` dentro: sem ele, o
 * código de um caso verificava noutro, o que é exactamente a falha de
 * isolamento que o DoD pede que se meça.
 *
 * ## O disjuntor alerta **uma vez por janela**, e o contador é que o garante
 *
 * Um alerta por envio recusado é um alerta por minuto durante um dia, e um
 * alerta que chega mil vezes é um alerta que ninguém lê. A idempotência não vem
 * de um `boolean` neste objecto — que morria com o processo e voltava a alertar
 * no arranque seguinte — mas de uma chave no `Contadores`, com a mesma janela do
 * orçamento. É o mesmo mecanismo a responder às duas perguntas.
 */

import { randomInt, timingSafeEqual } from "node:crypto";

import { CodigoOtp } from "../sms/codigo.ts";

import type {
  Alerta,
  Contadores,
  OtpProvider,
  RepositorioDeOtp,
  Relogio,
} from "./contrato.ts";
import { DOMINIOS, hmacDe } from "./identificadores.ts";
import type { Telefone } from "./identificadores.ts";

/** Dígitos do código. *Proposta* do critério 5. */
export const DIGITOS = 6;

/** Validade do código, em minutos. *Proposta* do critério 5. */
export const TTL_MINUTOS = 5;

/** Tentativas por código. *Proposta* do critério 5: bloqueia **na** quinta. */
export const TENTATIVAS_MAXIMAS = 5;

/** Envios por hora e por telefone. *Proposta* do critério 5. */
export const ENVIOS_POR_JANELA = 3;

/** A janela dos envios por telefone, em milissegundos. Uma hora. */
export const JANELA_DE_ENVIOS_MS = 3_600_000;

/** Intervalo mínimo entre dois envios ao mesmo telefone, em segundos. *Proposta*. */
export const INTERVALO_SEGUNDOS = 60;

/** Envios por dia, somados todos os telefones. *Proposta* — ver a nota do módulo. */
export const ORCAMENTO_DIARIO = 500;

/** A janela do orçamento, em milissegundos. Vinte e quatro horas. */
export const JANELA_DO_ORCAMENTO_MS = 86_400_000;

/** As chaves de contagem deste módulo. Prefixadas para não colidirem com o `./antiabuso.ts`. */
export const CHAVES = {
  envios: (telefoneHmac: string): string => `otp:envios:${telefoneHmac}`,
  orcamento: "otp:orcamento",
  alerta: "otp:orcamento:alerta",
} as const;

/** Porque é que um envio foi recusado. Lista fechada; nenhum valor é um dado. */
export const RECUSAS_DE_ENVIO = ["intervalo", "frequencia", "orcamento"] as const;

export type RecusaDeEnvio = (typeof RECUSAS_DE_ENVIO)[number];

/** O que um envio devolve. */
export type ResultadoDeEnvio =
  | { readonly enviado: true; readonly expiraEm: Date }
  | { readonly enviado: false; readonly recusa: RecusaDeEnvio };

/**
 * O veredicto de uma verificação.
 *
 *     acertou       o código é o do desafio, dentro da validade
 *     errou         não é, e ainda há tentativas
 *     expirado      havia desafio e já passou o TTL
 *     sem_desafio   não há desafio para este caso (ou já foi gasto)
 *     tentativas    esgotaram-se, e o desafio foi destruído
 */
export const VEREDICTOS = ["acertou", "errou", "expirado", "sem_desafio", "tentativas"] as const;

export type Veredicto = (typeof VEREDICTOS)[number];

/** Opções do OTP. Todos os limiares são ***propostas*** — ver a nota do módulo. */
export interface OpcoesDeOtp {
  readonly repositorio: RepositorioDeOtp;
  readonly contadores: Contadores;
  readonly provedor: OtpProvider;
  /** A chave **actual** do anel do `pepper_onboarding_ident`. */
  readonly chave: Uint8Array;
  readonly relogio?: Relogio;
  readonly alerta?: Alerta;
  readonly digitos?: number;
  readonly ttlMinutos?: number;
  readonly tentativasMaximas?: number;
  readonly enviosPorJanela?: number;
  readonly intervaloSegundos?: number;
  readonly orcamentoDiario?: number;
}

/**
 * A chave de idempotência do envio, derivada do caso e da validade do desafio.
 *
 * Determinística e única por desafio: dois pedidos para o **mesmo** desafio dão
 * a mesma chave e o `../sms/` manda **um** SMS (é a caixa de «idempotência do
 * envio de OTP com teste de repetição» do DoD), e um desafio novo dá chave nova,
 * porque um segundo código com a chave do primeiro nunca saía.
 *
 * **Não leva o código nem o seu HMAC.** A chave viaja para o agregador, que é um
 * terceiro; mandar-lhe um valor derivado do código era dar-lhe material sobre um
 * segredo que ele não tem de ter. Leva o `onboarding_id`, que é um UUID aleatório
 * e não um dado pessoal, e o instante de expiração.
 */
export function chaveDoEnvio(onboardingId: string, expiraEm: Date): string {
  return `otp-${onboardingId}-${expiraEm.getTime()}`;
}

/** O HMAC de um código, **preso ao caso**. Ver a nota do módulo. */
export function hmacDoCodigo(chave: Uint8Array, onboardingId: string, codigo: string): string {
  return hmacDe(chave, DOMINIOS.otp, `${onboardingId}\u0000${codigo}`).toString("hex");
}

/**
 * O OTP de posse do telefone.
 *
 * Não sabe o que é um caso: recebe o `onboarding_id` e o `Telefone`, e quem os
 * junta é o `./registo.ts`. É deliberado — assim a bateria de OTP não precisa de
 * um repositório de casos, e o isolamento entre os dois módulos é o que impede
 * que um limite do OTP dependa da fase de um caso.
 */
export class Otp {
  readonly #repositorio: RepositorioDeOtp;
  readonly #contadores: Contadores;
  readonly #provedor: OtpProvider;
  readonly #chave: Uint8Array;
  readonly #relogio: Relogio;
  readonly #alerta: Alerta;
  readonly digitos: number;
  readonly ttlMinutos: number;
  readonly tentativasMaximas: number;
  readonly enviosPorJanela: number;
  readonly intervaloSegundos: number;
  readonly orcamentoDiario: number;

  constructor(opcoes: OpcoesDeOtp) {
    this.#repositorio = opcoes.repositorio;
    this.#contadores = opcoes.contadores;
    this.#provedor = opcoes.provedor;
    this.#chave = opcoes.chave;
    this.#relogio = opcoes.relogio ?? ((): Date => new Date());
    this.#alerta = opcoes.alerta ?? ((): void => {});
    this.digitos = opcoes.digitos ?? DIGITOS;
    this.ttlMinutos = opcoes.ttlMinutos ?? TTL_MINUTOS;
    this.tentativasMaximas = opcoes.tentativasMaximas ?? TENTATIVAS_MAXIMAS;
    this.enviosPorJanela = opcoes.enviosPorJanela ?? ENVIOS_POR_JANELA;
    this.intervaloSegundos = opcoes.intervaloSegundos ?? INTERVALO_SEGUNDOS;
    this.orcamentoDiario = opcoes.orcamentoDiario ?? ORCAMENTO_DIARIO;
  }

  /**
   * Gera, guarda e envia um código.
   *
   * A ordem é: barreiras primeiro, efeito depois. Um código gerado antes de se
   * saber que o envio é permitido substituía o desafio anterior **e** não saía —
   * e o dono ficava com um código que lhe nunca chegou a ser mandado, que é um
   * modo de falha pior do que a recusa.
   *
   * O orçamento consome-se **antes** do envio e não depois: entre a decisão e a
   * resposta do agregador há tempo, e um `await` nessa janela deixava passar
   * tantos envios quantos pedidos concorrentes houvesse. Com o consumo à
   * frente, o tecto é um tecto.
   */
  /**
   * As duas barreiras por destino — o intervalo e a frequência — **sem as
   * consumir**.
   *
   * Existe por causa do critério 9, e a razão está no cabeçalho do
   * `./registo.ts`: as duas barreiras são por **telefone de destino**, e o
   * destino difere entre o caminho de criação e o de recuperação. Perguntá-las
   * **antes** de se saber o caminho, sobre o telefone que o cliente submeteu,
   * é o que faz as duas respostas serem a mesma.
   */
  async podeEnviar(telefone: Telefone): Promise<RecusaDeEnvio | null> {
    const agora = this.#relogio();
    const chave = CHAVES.envios(telefone.hmac);
    const ultimo = await this.#contadores.ultimo(chave);
    if (ultimo !== null && agora.getTime() - ultimo.getTime() < this.intervaloSegundos * 1000) {
      return "intervalo";
    }
    const naJanela = await this.#contadores.contar(chave, agora, JANELA_DE_ENVIOS_MS);
    return naJanela >= this.enviosPorJanela ? "frequencia" : null;
  }

  async enviar(onboardingId: string, telefone: Telefone): Promise<ResultadoDeEnvio> {
    const agora = this.#relogio();
    const chaveDoTelefone = CHAVES.envios(telefone.hmac);

    const recusa = await this.podeEnviar(telefone);
    if (recusa !== null) return { enviado: false, recusa };

    // **Conta-se antes de anotar, e a ordem inversa era um defeito grave.** A
    // primeira versão anotava e só depois comparava, pelo que cada pedido
    // **recusado** deixava um instante na janela — e a janela é deslizante.
    // Com tráfego contínuo depois de esgotar o tecto, cada recusa estendia a
    // pausa 24 h a contar **dela**, e o disjuntor nunca reabria; o custo do
    // atacante era zero, porque nenhum SMS saía. Achado da revisão adversarial.
    //
    // O preço desta ordem, dito: entre o `contar` e o `anotar` há um `await`,
    // pelo que N pedidos concorrentes podem passar do tecto em até N. É um
    // excesso **limitado pela concorrência**, contra um disjuntor que não
    // fechava — e o segundo é estritamente pior.
    const gastos = await this.#contadores.contar(
      CHAVES.orcamento,
      agora,
      JANELA_DO_ORCAMENTO_MS,
    );
    if (gastos >= this.orcamentoDiario) {
      await this.#alertarUmaVez(agora, onboardingId);
      return { enviado: false, recusa: "orcamento" };
    }
    await this.#contadores.anotar(CHAVES.orcamento, agora, JANELA_DO_ORCAMENTO_MS);

    const codigo = this.#gerar();
    const expiraEm = new Date(agora.getTime() + this.ttlMinutos * 60_000);
    await this.#repositorio.guardar({
      onboardingId,
      // **O `revelar()` do código é chamado UMA vez neste módulo, e é aqui**:
      // para o HMAC que fica guardado. O que vai para a porta é o `CodigoOtp`
      // inteiro, que é opaco, e não o seu valor. Um segundo sítio de chamada é
      // um achado de revisão, como o `../sms/codigo.ts` escreve. (A primeira
      // versão deste comentário dizia «duas vezes» e desdizia-se na linha
      // seguinte; apanhou-o a revisão adversarial, a contar.)
      codigoHmac: hmacDoCodigo(this.#chave, onboardingId, codigo.revelar()),
      expiraEm,
      tentativas: 0,
    });
    await this.#contadores.anotar(chaveDoTelefone, agora, JANELA_DE_ENVIOS_MS);
    try {
      await this.#provedor.enviar(
        telefone,
        codigo,
        this.ttlMinutos,
        chaveDoEnvio(onboardingId, expiraEm),
      );
    } catch (erro) {
      // **O desafio apaga-se quando o envio falha**, e não apagá-lo era um
      // defeito: ele ficava guardado cinco minutos, e a repetição do pedido
      // encontrava-o vivo e respondia «enviámos um código» sem SMS nenhum ter
      // saído. É o modo de falha que o parágrafo acima diz evitar — o dono com
      // um código que nunca lhe foi mandado — e a primeira versão tinha-o do
      // outro lado. Achado da revisão adversarial.
      //
      // A quota do telefone **fica** gasta, e isso é deliberado: ela mede
      // tentativas de envio, não entregas, e compensá-la dava a quem fizesse o
      // agregador falhar uma maneira de pedir SMS sem limite.
      await this.#repositorio.apagar(onboardingId);
      throw erro;
    }
    return { enviado: true, expiraEm };
  }

  /**
   * Confere um código.
   *
   * A comparação é em **tempo constante** sobre o HMAC — não sobre o código — e
   * é por isso que ela é constante de verdade: dois HMAC têm sempre 32 octetos,
   * ao passo que dois códigos de comprimentos diferentes faziam o
   * `timingSafeEqual` levantar e obrigavam a um `length` antes, que é o ramo que
   * vaza.
   *
   * A tentativa conta-se **antes** da comparação. Pela ordem inversa, um
   * atacante que fechasse a ligação a seguir ao pedido tinha tentativas de
   * graça — o contador só subia depois de a resposta ser calculada.
   */
  async verificar(onboardingId: string, codigo: unknown): Promise<Veredicto> {
    const desafio = await this.#repositorio.actual(onboardingId);
    if (desafio === null) return "sem_desafio";
    const agora = this.#relogio();
    if (desafio.expiraEm.getTime() <= agora.getTime()) {
      await this.#repositorio.apagar(onboardingId);
      return "expirado";
    }
    const tentativas = await this.#repositorio.somarTentativa(onboardingId);
    if (tentativas === null) return "sem_desafio";

    const texto = typeof codigo === "string" ? codigo : "";
    // A forma do HMAC **guardado** verifica-se antes de o comparar: o
    // `timingSafeEqual` **levanta** com dois buffers de comprimentos
    // diferentes, pelo que um adaptador que guardasse outra coisa na coluna
    // fazia uma verificação de código sair 500 em vez de um veredicto.
    if (!/^[0-9a-f]{64}$/.test(desafio.codigoHmac)) {
      await this.#repositorio.apagar(onboardingId);
      return "sem_desafio";
    }
    const esperado = Buffer.from(desafio.codigoHmac, "hex");
    const recebido = hmacDe(this.#chave, DOMINIOS.otp, `${onboardingId}\u0000${texto}`);
    const acertou = timingSafeEqual(esperado, recebido);

    if (acertou) {
      await this.#repositorio.apagar(onboardingId);
      return "acertou";
    }
    if (tentativas >= this.tentativasMaximas) {
      await this.#repositorio.apagar(onboardingId);
      return "tentativas";
    }
    return "errou";
  }

  /**
   * O fim da validade do desafio vivo deste caso, ou `null`.
   *
   * Existe por causa do critério 2, e o `./registo.ts` explica porquê: o segundo
   * `POST` com a mesma chave de idempotência tem de devolver o mesmo caso **sem
   * pedir um segundo SMS**, que o intervalo de 60 s recusaria. Um desafio
   * expirado conta como `null` — a validade é a pergunta, não a existência da
   * linha.
   */
  async validade(onboardingId: string): Promise<Date | null> {
    const desafio = await this.#repositorio.actual(onboardingId);
    if (desafio === null) return null;
    return desafio.expiraEm.getTime() > this.#relogio().getTime() ? desafio.expiraEm : null;
  }

  /**
   * O disjuntor está aberto?
   *
   * Exposto para a sonda do serviço: um `/healthz` que não diga que os envios
   * estão pausados deixa a pausa invisível até alguém se queixar. **Não** é por
   * aqui que o `enviar` decide — ele consome e compara, que é a única forma de
   * um tecto não ser ultrapassado por pedidos concorrentes.
   */
  async disjuntorAberto(): Promise<boolean> {
    const gastos = await this.#contadores.contar(
      CHAVES.orcamento,
      this.#relogio(),
      JANELA_DO_ORCAMENTO_MS,
    );
    return gastos >= this.orcamentoDiario;
  }

  /** Um código de `digitos` algarismos, do gerador do sistema, uniforme. */
  #gerar(): CodigoOtp {
    const tecto = 10 ** this.digitos;
    // `randomInt` e não `Math.random`: o segundo é previsível a partir de umas
    // dezenas de saídas, e um OTP previsível é um OTP que não prova posse.
    return new CodigoOtp(String(randomInt(0, tecto)).padStart(this.digitos, "0"));
  }

  /** O alerta do disjuntor, uma vez por janela. Ver a nota do módulo. */
  async #alertarUmaVez(agora: Date, onboardingId: string): Promise<void> {
    const jaAlertou = await this.#contadores.contar(
      CHAVES.alerta,
      agora,
      JANELA_DO_ORCAMENTO_MS,
    );
    if (jaAlertou > 0) return;
    await this.#contadores.anotar(CHAVES.alerta, agora, JANELA_DO_ORCAMENTO_MS);
    // O `onboardingId` **não** vai no alerta: ele não é campo da *allowlist* do
    // `../logger/politica.ts`, e o orçamento é global — nomear o caso que
    // calhou ser o primeiro a bater no tecto dizia menos do que parece.
    void onboardingId;
    this.#alerta("orcamento_de_sms_esgotado", {});
  }
}
