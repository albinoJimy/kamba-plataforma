/**
 * O registo: criar o caso, ou recuperar a sessão de quem já tem um (KAM-086,
 * critérios 2, 3, 8 e 9).
 *
 * É o caso de uso, e é o único sítio do módulo que junta as cinco peças —
 * *token*, identificadores, anti-abuso, OTP e repositório. Os outros ficheiros
 * não se conhecem uns aos outros de propósito: é o que permite medir cada um
 * sozinho e é o que impede um limite de OTP de passar a depender da fase de um
 * caso.
 *
 * ## As duas respostas são a **mesma** resposta, e é o critério 9
 *
 * «Respostas a "NIF já registado" e "NIF novo" são indistinguíveis em corpo e
 * tempo (diferença < 20 ms): sem enumeração de NIF ou telefone.»
 *
 * Os dois caminhos devolvem um `Aceite` com os mesmos três campos e nenhum
 * campo a mais, e a `referencia` é um HMAC opaco que não diz se o caso é novo.
 * Três coisas foram escritas por causa deste critério e não por elegância:
 *
 * 1. **A referência é um bilhete e não uma sessão.** No caminho de recuperação
 *    ela aponta para o caso **de outra pessoa** — é isso que a torna
 *    indistinguível —, e é por isso que ela não autentica nada: o `./sessao.ts`
 *    usa separadores de domínio diferentes para o bilhete e para o cookie, e o
 *    cookie só é cunhado depois de o OTP acertar. Ver a nota desse ficheiro.
 * 2. **O OTP do caminho de recuperação vai ao telefone registado**, e não ao
 *    telefone submetido. Quem submeteu o formulário recebe um bilhete que só
 *    serve com um código que lhe não chega. O critério 8 pede isto por extenso,
 *    e é o que faz o caminho ser seguro apesar de ser indistinguível.
 * 3. **O caminho de recuperação também escreve.** Conta a tentativa de
 *    recuperação deste `nif_hmac` numa janela de 24 h. Não é maquilhagem de
 *    tempo: é o número que a fila de revisão precisa para ver um NIF a ser
 *    sondado, e é também o que faz os dois caminhos terem uma leitura e uma
 *    escrita cada. Sem ele, o caminho sem criação era mensuravelmente mais
 *    rápido — e um caminho mais rápido é a enumeração que o critério proíbe.
 *
 * ## O oráculo que o critério 9 tinha, e o que fechou — e o que NÃO fecha
 *
 * A primeira versão deste ficheiro tinha um oráculo de enumeração de NIF que
 * se lia num **estado HTTP**, e a revisão adversarial mediu-o passo a passo. As
 * duas barreiras por destino — o intervalo de 60 s e os três envios por hora —
 * são por **telefone de destino**, e o destino difere entre os dois caminhos: o
 * de criação manda ao telefone **submetido**, o de recuperação ao **registado**.
 * Bastava esgotar os três envios do **seu próprio** telefone e depois submeter
 * sempre esse telefone: um NIF novo dava 429 (o envio era para o telefone
 * esgotado) e um NIF registado dava 200 (o envio era para outro). Um pedido por
 * candidato, sem receber SMS nenhum, sem esperar.
 *
 * **Fecha-se fazendo o `POST /api/registo` nunca falhar por causa do ritmo dos
 * SMS.** O `#garantirDesafio` engole o `intervalo` e a `frequencia` nos **dois**
 * caminhos: não há código novo, e o cliente não o sabe — que é a resposta certa,
 * porque o dono já tem um código vivo ou acabou de receber três. O orçamento
 * diário continua visível, e pode: ele é **global**, pelo que recusa os dois
 * caminhos ao mesmo tempo e não distingue nada.
 *
 * **A primeira correcção foi outra e estava errada**, e vale a pena ficar
 * escrito porque é o tipo de engano que volta: perguntar as duas barreiras
 * **antes** do ramo, sobre o telefone submetido. Fechava o oráculo e partia o
 * critério 2 — a segunda chamada com a mesma chave de idempotência caía no
 * intervalo de 60 s do primeiro envio e devolvia 429 em vez do mesmo
 * `onboarding_id`. O que a bateria do critério 2 apanhou, e o `Otp.podeEnviar`
 * ficou como a barreira interna do `enviar` que sempre foi.
 *
 * O preço do silêncio, dito: um dono que esgote os três envios por hora recebe
 * um 200 sem código novo. A honestidade mora no `POST /api/otp/reenviar`, que
 * **devolve 429** — e pode, porque exige um bilhete, e quem tem o bilhete já
 * sabe de que caso ele é.
 *
 * **O que NÃO fecha, e fica dito em vez de disfarçado:** o critério 8 manda o
 * código ao telefone **registado**, logo quem submete o seu próprio telefone
 * sabe, por o SMS chegar ou não chegar, se o NIF já estava registado. Esse
 * oráculo é **inerente ao critério 8** e vive fora da resposta; nenhuma linha
 * deste ficheiro o pode fechar sem desfazer a recuperação. O critério 9, como
 * está escrito, vale sobre a **resposta** — corpo, estado e tempo — e é isso
 * que está medido.
 *
 * E a igualdade de **tempo** é medida contra o `./memoria.ts`. Contra o
 * adaptador SQL, que não existe (ver `./contrato.ts`), um `INSERT` e um
 * `SELECT` não custam o mesmo, e a diferença sob RLS `FORCE` é **NÃO
 * VERIFICADA**. Quem escrever o adaptador mede-a.
 *
 * ## Sem NIF não há caso, e o ecrã é a outra metade do critério 3
 *
 * Aqui recusa-se: um `nif` que não passe a forma do `./identificadores.ts`
 * levanta antes de qualquer escrita. A metade do «o ecrã diz que o serviço
 * implica NIF e registo de vendas» é texto de página, vive no
 * `services/onboarding-web` e tem bateria própria lá — porque é lá que ela pode
 * errar.
 */

import { randomUUID } from "node:crypto";

import { SmsError, validarChave } from "../sms/contrato.ts";

import type { Alerta, Caso, Flag, Origem, RepositorioDeCasos, Relogio } from "./contrato.ts";
import { CasoDuplicadoError, ChaveReutilizadaError } from "./contrato.ts";
import { AbusoError, AntiAbuso, JANELA_DO_DISPOSITIVO_MS, type DesafioEmitido } from "./antiabuso.ts";
import {
  DOMINIOS,
  Email,
  IdentificadorInvalidoError,
  Nif,
  Telefone,
  hmacDe,
  normalizarTexto,
  prefixoDeIp,
} from "./identificadores.ts";
import type { Otp } from "./otp.ts";
import { cunharReferencia } from "./sessao.ts";
import { TokenInvalidoError, verificarToken } from "./token.ts";

// **Este caso de uso não tem chaves de contagem próprias, e tinha uma.**
//
// Era a `registo:recuperacao:<nifHmac>`, com a justificação de que «é o número
// que a fila de revisão precisa para ver um NIF a ser sondado». A revisão
// adversarial procurou o leitor e não há nenhum, em todo o repositório: era
// maquinaria sem consumidor, que é desenho especulativo pela regra desta casa.
// E o segundo papel que ela tinha — igualar as escritas dos dois caminhos, para
// o critério 9 — passou a ser do `AntiAbuso.consumir`, que a recuperação agora
// também chama (ver `#recuperar`). Quando o KAM-089 escrever a fila, é ele que
// decide o que ela precisa de contar.

/**
 * Porque é que um registo foi recusado, e com que estado HTTP.
 *
 * A lista é fechada e o mapa para HTTP vive ao lado dela, não no serviço: um
 * `switch` no serviço esquecia-se do código novo em silêncio, e um `Record`
 * tipado é um erro de compilação.
 */
export const CODIGOS = ["token", "campo", "abuso", "limite", "indisponivel"] as const;

export type Codigo = (typeof CODIGOS)[number];

/** O estado HTTP de cada recusa. */
export const ESTADO_HTTP: Readonly<Record<Codigo, 400 | 403 | 429 | 503>> = {
  token: 403,
  campo: 400,
  abuso: 400,
  limite: 429,
  indisponivel: 503,
};

/**
 * Levantado quando o registo não avança.
 *
 * **A mensagem não leva o valor que falhou**, e o `detalhe` é um identificador
 * de uma lista fechada de outro módulo (`MotivoDaRecusa`, `Recusa`,
 * `RecusaDeEnvio`), nunca texto de quem chamou. É a regra do
 * `../secrets/port.ts` aplicada à superfície que o público vê.
 */
export class RegistoRecusado extends Error {
  override readonly name = "RegistoRecusado";
  readonly codigo: Codigo;
  readonly detalhe: string;
  readonly estadoHttp: 400 | 403 | 429 | 503;

  constructor(codigo: Codigo, detalhe: string) {
    super(`registo recusado: ${codigo} (${detalhe})`);
    this.codigo = codigo;
    this.detalhe = detalhe;
    this.estadoHttp = ESTADO_HTTP[codigo];
  }
}

/** O que o formulário submete. Tudo `unknown`: vem da rede. */
export interface PedidoDeRegisto {
  readonly token: unknown;
  readonly nomeNegocio: unknown;
  readonly categoria: unknown;
  readonly nif: unknown;
  readonly telefone: unknown;
  readonly email?: unknown;
  readonly chaveDeIdempotencia: unknown;
  readonly desafio: unknown;
  readonly solucao: unknown;
  readonly honeypot?: unknown;
  readonly ip?: unknown;
  /** Identificador grosseiro do dispositivo, composto pelo cliente. */
  readonly dispositivo?: unknown;
}

/**
 * O que o registo devolve, nos **dois** caminhos.
 *
 * Três campos e nem um a mais. Acrescentar aqui um `novo: boolean`, um
 * `onboarding_id` nu ou uma mensagem diferente por caminho é desfazer o critério
 * 9 — e é o achado que uma revisão adversarial deve procurar primeiro.
 */
export interface Aceite {
  /** O bilhete para submeter o código. Opaco. Ver `./sessao.ts`. */
  readonly referencia: string;
  /**
   * Quantos segundos o código vale. **A constante do módulo, não um instante.**
   *
   * Era um `expiraEm`, e o `expiraEm` era um oráculo: no caminho de criação ele
   * é sempre `agora + TTL`, e no de recuperação, quando a vítima já tem um
   * desafio vivo, é **menos** do que isso — pelo que um `expira_em` abaixo de
   * `agora + 300 s` dizia «este NIF já está registado e com OTP em curso».
   * Achado da revisão adversarial. O cliente precisa de saber quanto tempo o
   * código dura, não o instante exacto em que morre, e a duração é a mesma nos
   * dois caminhos porque é uma constante.
   */
  readonly validadeSegundos: number;
  readonly digitos: number;
}

/** Opções do registo. */
export interface OpcoesDeRegisto {
  readonly repositorio: RepositorioDeCasos;
  readonly antiabuso: AntiAbuso;
  readonly otp: Otp;
  /**
   * O anel do `pepper_onboarding_ident`: a **actual** primeiro.
   *
   * O anel inteiro e nao so a actual, e a razao e de correccao: quem escreve um
   * `nif_hmac` usa a actual, mas quem **procura** um duplicado tem de procurar
   * tambem com a anterior — senao a primeira rotacao do *pepper* fazia o indice
   * unico deixar de ver os casos escritos antes dela. Ver `hmacsDoAnel`.
   */
  readonly anelDoPepper: readonly (Uint8Array | null)[];
  /** O anel do `segredo_token_entrar`: actual primeiro. */
  readonly anelDoToken: readonly (Uint8Array | null)[];
  /** O anel da chave que assina bilhetes e sessões. */
  readonly anelDaSessao: readonly (Uint8Array | null)[];
  readonly relogio?: Relogio;
  readonly alerta?: Alerta;
}

/** O registo. */
export class Registo {
  readonly #repositorio: RepositorioDeCasos;
  readonly #antiabuso: AntiAbuso;
  readonly #otp: Otp;
  readonly #anelDoPepper: readonly (Uint8Array | null)[];
  readonly #chave: Uint8Array;
  readonly #anelDoToken: readonly (Uint8Array | null)[];
  readonly #anelDaSessao: readonly (Uint8Array | null)[];
  readonly #relogio: Relogio;

  constructor(opcoes: OpcoesDeRegisto) {
    this.#repositorio = opcoes.repositorio;
    this.#antiabuso = opcoes.antiabuso;
    this.#otp = opcoes.otp;
    this.#anelDoPepper = opcoes.anelDoPepper;
    const actual = opcoes.anelDoPepper[0];
    if (!(actual instanceof Uint8Array)) {
      // Em voz alta e no arranque: um anel sem chave actual fazia cada pedido
      // falhar com um erro que nao diz que a configuracao esta errada.
      throw new TypeError("o anel do pepper_onboarding_ident nao tem chave actual");
    }
    this.#chave = actual;
    this.#anelDoToken = opcoes.anelDoToken;
    this.#anelDaSessao = opcoes.anelDaSessao;
    this.#relogio = opcoes.relogio ?? ((): Date => new Date());
  }

  /** O desafio anti-bot que a página precisa, para esta rede. */
  async desafioPara(ip: unknown): Promise<DesafioEmitido> {
    return this.#antiabuso.emitir(this.#redeHmac(ip));
  }

  /**
   * O telefone registado de um caso, para um reenvio de código.
   *
   * Passa pelo caso de uso e não pelo repositório directamente, e isso é a
   * fronteira que importa: o `telefoneDe` é a única operação da porta que
   * devolve um dado pessoal, e ter **um** caminho até ele é o que torna
   * auditável quem o chama. Quem o chamar de outro sítio é um achado de revisão.
   */
  async telefoneDoCaso(id: string): Promise<Telefone | null> {
    return this.#repositorio.telefoneDe(id);
  }

  /**
   * Marca a posse do telefone como provada.
   *
   * `kyc_pendente` é a fase seguinte do dicionário §3.2, e é onde este ticket
   * acaba: o K1 é do KAM-087. Devolve `false` se o caso não existe, que é o 404
   * do teste de isolamento.
   *
   * **Só avança, e nunca faz recuar.** O OTP também se pede **depois** do
   * registo: a ligação de retoma do Embedded Signup (KAM-093) volta a provar a
   * posse do telefone dias mais tarde, com o caso já em `aguarda_es`. Marcar
   * `kyc_pendente` sem olhar para a fase fazia esse caso recuar para antes do
   * KYC, e a página que a retoma devia abrir passava a responder 409. Achado
   * da revisão adversarial do KAM-093. Num caso que já passou o OTP, acertar
   * outra vez é só a prova de posse que a sessão precisa.
   */
  async concluirOtp(id: string): Promise<boolean> {
    const caso = await this.#repositorio.porId(id);
    if (caso === null) return false;
    if (caso.fase !== "registo" && caso.fase !== "otp_pendente") return true;
    return this.#repositorio.marcarFase(id, "kyc_pendente");
  }

  /**
   * Inscreve, ou recupera a sessão de quem já tem caso.
   *
   * Chama-se `inscrever` e não `registar` pela razão do `anotar` do
   * `./contrato.ts`: o `tools/log_policy` recusa `.registar(...)` em código de
   * serviço, e o `services/onboarding-web/src/rotas.ts` chamava-o assim.
   *
   * @throws {RegistoRecusado}
   */
  async inscrever(pedido: PedidoDeRegisto): Promise<Aceite> {
    const origem = this.#origem(pedido.token);
    const campos = this.#campos(pedido);
    const redeHmac = this.#redeHmac(pedido.ip);
    const dispositivoHmac = this.#dispositivoHmac(pedido.dispositivo);

    try {
      await this.#antiabuso.verificar({
        // Os dois coagem-se aqui e não dentro do anti-abuso: o `Submissao` é um
        // tipo de domínio e um domínio com campos `unknown` obriga cada
        // chamador a repetir a verificação. Um valor que não é cadeia vira a
        // cadeia vazia, que o `#lerDesafio` recusa como `desafio_invalido`.
        desafio: typeof pedido.desafio === "string" ? pedido.desafio : "",
        solucao: typeof pedido.solucao === "string" ? pedido.solucao : "",
        honeypot: typeof pedido.honeypot === "string" ? pedido.honeypot : undefined,
        redeHmac,
        dispositivoHmac,
      });
    } catch (erro) {
      if (!(erro instanceof AbusoError)) throw erro;
      const codigo: Codigo = erro.recusa === "limite_de_rede" ? "limite" : "abuso";
      throw new RegistoRecusado(codigo, erro.recusa);
    }

    const existente = await this.#casoComEsteNif(campos.nif);
    return existente === null
      ? this.#criar(origem, campos, redeHmac, dispositivoHmac)
      : this.#recuperar(existente, campos.chave, redeHmac, dispositivoHmac);
  }

  /** O caminho de NIF novo. */
  async #criar(
    origem: Origem,
    campos: Campos,
    redeHmac: string | null,
    dispositivoHmac: string | null,
  ): Promise<Aceite> {
    const agora = this.#relogio();
    const flags: Flag[] = [];

    // Critério 8, primeira metade: telefone repetido com NIF diferente. O
    // `porTelefoneHmac` devolve só casos **vivos**, e o `porNifHmac` acabou de
    // devolver `null` para o nosso NIF — logo qualquer caso vivo que partilhe
    // este telefone tem, por força, outro `nif_hmac`. A comparação explícita
    // era uma condição sempre verdadeira, e uma condição sempre verdadeira num
    // caminho de segurança é pior do que a sua ausência: parece medida e não é.
    const comOTelefone = await this.#casosComEsteTelefone(campos.telefone);
    if (comOTelefone.length > 0) flags.push("duplicado_ambiguo");

    // Critério 8, segunda metade: três ou mais casos em 24 h do mesmo
    // dispositivo. Lê-se **antes** de criar, porque é o caso a criar que leva a
    // marca; o `consumir` do anti-abuso é que a escreve na contagem, depois.
    if (dispositivoHmac !== null) {
      const desde = new Date(agora.getTime() - JANELA_DO_DISPOSITIVO_MS);
      const noDispositivo = await this.#repositorio.contarPorDispositivo(dispositivoHmac, desde);
      if (noDispositivo >= this.#antiabuso.casosPorDispositivo && !flags.includes("duplicado_ambiguo")) {
        flags.push("duplicado_ambiguo");
      }
    }

    let criado: { readonly caso: Caso; readonly repetido: boolean };
    try {
      criado = await this.#repositorio.criar(
      {
        // O `tenant_id` é **pré-alocado** aqui e a linha de `platform.tenants`
        // **não** é criada: ela é do passo 1 da saga do KAM-091. A razão é o
        // `events_outbox.tenant_id NOT NULL` — ver o Contexto do bloco.
        tenantId: randomUUID(),
        origem,
        nomeNegocio: campos.nomeNegocio,
        categoriaDeclarada: campos.categoria,
        nif: campos.nif,
        telefone: campos.telefone,
        email: campos.email,
        dispositivoHmac,
        redeHmac,
        flags,
      },
        campos.chave,
      );
    } catch (erro) {
      // Uma chave de idempotência com **outro** corpo não é uma repetição: é um
      // conflito. Ver `ChaveReutilizadaError` no `./memoria.ts`.
      if (erro instanceof ChaveReutilizadaError) {
        throw new RegistoRecusado("campo", "chave_reutilizada");
      }
      // **A corrida de dois pedidos com o mesmo NIF novo.** Os dois passam pelo
      // `#casoComEsteNif` antes de qualquer escrita, e o segundo bate na
      // unicidade. A primeira versão deixava este erro subir até ao `onError` do
      // Hono — um **500**, e um terceiro estado HTTP que dizia «este NIF está a
      // ser registado agora mesmo». Achado da revisão adversarial. A resposta
      // certa é a mesma que o caso já registado teria: recuperar.
      if (!(erro instanceof CasoDuplicadoError)) throw erro;
      const entretanto = await this.#casoComEsteNif(campos.nif);
      if (entretanto === null) throw erro;
      return this.#recuperar(entretanto, campos.chave, redeHmac, dispositivoHmac);
    }
    const { caso, repetido } = criado;

    // A quota consome-se **uma vez por caso** e não por pedido: com a mesma
    // chave de idempotência, o segundo pedido não criou caso nenhum e não pode
    // gastar a quota da rede. Sem este `if`, dois cliques num botão gastavam
    // dois dos cinco casos por hora de um bairro.
    if (!repetido) await this.#antiabuso.consumir(redeHmac, dispositivoHmac);

    // **O destino é o do CASO e não o do pedido**, e a diferença era um defeito.
    // Com a mesma chave de idempotência e outro telefone, a primeira versão
    // mandava o código para o telefone **novo** enquanto o caso guardava o
    // `phone_hmac` do primeiro: a posse provada era de um número que o caso não
    // tinha, e isso esvazia a garantia do critério 5. Achado da revisão
    // adversarial. (O `ChaveReutilizadaError` acima já recusa o caso em que o
    // NIF difere; este fecha o caso em que só o telefone difere.)
    const destino = repetido
      ? ((await this.#repositorio.telefoneDe(caso.id)) ?? campos.telefone)
      : campos.telefone;

    try {
      await this.#garantirDesafio(caso.id, destino);
    } catch (erro) {
      // **Um caso que não consegue receber código é abandonado**, e não o ser era
      // um sequestro de NIF: a linha ficava viva, prendia o `nif_hmac`, e quando o
      // dono real se registasse caía na recuperação — com o código a ir para o
      // telefone de quem queimou o NIF. Achado da revisão adversarial.
      //
      // O `abandonado` está fora do índice único do bloco, pelo que o NIF fica
      // livre de imediato e uma segunda tentativa cria um caso novo. **E isto não
      // contradiz o «sem perder casos já abertos» do critério 6:** um caso criado
      // no pedido que não conseguiu mandar o código não é um caso já aberto.
      if (!repetido) await this.#repositorio.marcarFase(caso.id, "abandonado");
      throw erro;
    }
    if (caso.fase === "registo") await this.#repositorio.marcarFase(caso.id, "otp_pendente");
    return this.#aceite(caso.id);
  }

  /** O caminho de NIF já registado. Ver as notas do módulo. */
  async #recuperar(
    existente: Caso,
    chave: string,
    redeHmac: string | null,
    dispositivoHmac: string | null,
  ): Promise<Aceite> {
    // **A recuperação também consome a quota da rede e do dispositivo**, e não
    // consumir era um achado: o limite de cinco casos por hora e por prefixo é
    // verificado antes do ramo mas só era **escrito** pelo caminho de criação,
    // pelo que quem conhecesse NIF vivos gerava SMS para os donos deles sem
    // nunca gastar a quota do seu prefixo. Achado da revisão adversarial.
    //
    // E é também o que iguala as escritas dos dois caminhos, que é o papel que a
    // chave de recuperação tinha e não devia ter tido (ver a nota no topo).
    //
    // **Mas uma vez por chave de idempotência, e não uma vez por pedido.** A
    // regra é a mesma do `#criar`, e a primeira versão desta linha não a tinha:
    // depois do primeiro registo o NIF passa a estar vivo, pelo que a segunda
    // chamada com a **mesma** chave cai aqui e não no `repetido` do `#criar` — e
    // gastava uma segunda vaga das cinco por hora de um bairro. Apanhou-o a
    // bateria do critério 2, ao medir a contagem em vez da dificuldade.
    const repetido = (await this.#repositorio.porChave(chave))?.id === existente.id;
    if (!repetido) await this.#antiabuso.consumir(redeHmac, dispositivoHmac);
    const registado = await this.#repositorio.telefoneDe(existente.id);
    if (registado === null) {
      // O caso existe e o telefone não se consegue ler: um `phone_enc` que não
      // abre é uma avaria nossa — chave errada ou rotação a meio — e não um
      // pedido inválido. Daí o 503 e não o 400: dizer «dados inválidos» a quem
      // submeteu um formulário correcto manda-o corrigir o que está certo.
      throw new RegistoRecusado("indisponivel", "telefone_ilegivel");
    }
    await this.#garantirDesafio(existente.id, registado);
    return this.#aceite(existente.id);
  }

  /**
   * O desafio de OTP vivo deste caso, ou um novo.
   *
   * Reutilizar o desafio vivo é o que faz o critério 2 funcionar: o segundo
   * `POST` com a mesma chave de idempotência não cria caso **e não pede um
   * segundo SMS**, que o intervalo de 60 s recusaria — e uma recusa ali fazia o
   * segundo pedido devolver erro em vez do mesmo `onboarding_id`.
   *
   * **Não devolve nada**, e devolvia o instante de expiração: ver o campo
   * `validadeSegundos` do `Aceite`.
   */
  async #garantirDesafio(id: string, destino: Telefone): Promise<void> {
    const vivo = await this.#otp.validade(id);
    if (vivo !== null) return;
    let resultado;
    try {
      resultado = await this.#otp.enviar(id, destino);
    } catch (erro) {
      // Um `SmsError` nao e uma recusa de politica: e o agregador. A traducao
      // segue o `REPETIVEIS` do `../sms/contrato.ts` em vez de o reinventar — um
      // numero que o agregador recusa nao melhora com o tempo e e um 400; os
      // outros dois sao nossos e sao um 503. **O caso ja esta criado e fica**,
      // que e o «sem perder casos ja abertos» do criterio 6.
      if (!(erro instanceof SmsError)) throw erro;
      throw erro.codigo === "INVALID_DESTINATION"
        ? new RegistoRecusado("campo", "telefone_recusado")
        : new RegistoRecusado("indisponivel", erro.codigo.toLowerCase());
    }
    if (resultado.enviado) return;
    // **Só o orçamento sobe ao cliente.** O `intervalo` e a `frequencia` são do
    // telefone de destino, e o destino difere entre os dois caminhos: devolvê-los
    // era o oráculo de enumeração do critério 9, pela porta do lado. Eles já
    // foram perguntados **antes** do ramo, sobre o telefone que o cliente
    // submeteu (`Otp.podeEnviar`); o que chega aqui é do telefone registado, isto
    // é, de outra pessoa. Sem código novo, e o cliente não o sabe — o que é a
    // resposta certa, porque o dono já tem um código ou acabou de receber três.
    //
    // O orçamento **pode** subir: ele é global e recusa os dois caminhos ao mesmo
    // tempo, pelo que não distingue nada.
    if (resultado.recusa === "orcamento") {
      throw new RegistoRecusado("limite", resultado.recusa);
    }
  }

  #aceite(id: string): Aceite {
    const chave = this.#anelDaSessao[0];
    if (!(chave instanceof Uint8Array)) throw new RegistoRecusado("indisponivel", "sem_chave");
    return {
      referencia: cunharReferencia("ticket", id, chave, this.#relogio),
      validadeSegundos: this.#otp.ttlMinutos * 60,
      digitos: this.#otp.digitos,
    };
  }

  /**
   * O caso vivo com este NIF, procurado com **todas** as chaves do anel.
   *
   * A actual primeiro, que e o caso normal e o que corre numa consulta so. A
   * anterior e o que impede uma rotacao do *pepper* de abrir uma janela em que
   * um duplicado passa.
   */
  async #casoComEsteNif(nif: Nif): Promise<Caso | null> {
    for (const hmac of nif.hmacs) {
      const caso = await this.#repositorio.porNifHmac(hmac);
      if (caso !== null) return caso;
    }
    return null;
  }

  /** Os casos vivos com este telefone, pela mesma razao do `#casoComEsteNif`. */
  async #casosComEsteTelefone(telefone: Telefone): Promise<readonly Caso[]> {
    const saida: Caso[] = [];
    for (const hmac of telefone.hmacs) {
      saida.push(...(await this.#repositorio.porTelefoneHmac(hmac)));
    }
    return saida;
  }

  #origem(token: unknown): Origem {
    try {
      return verificarToken(token, this.#anelDoToken, this.#relogio).origem;
    } catch (erro) {
      if (erro instanceof TokenInvalidoError) throw new RegistoRecusado("token", erro.recusa);
      throw erro;
    }
  }

  #campos(pedido: PedidoDeRegisto): Campos {
    try {
      const temEmail = typeof pedido.email === "string" && pedido.email.trim() !== "";
      return {
        nomeNegocio: normalizarTexto(pedido.nomeNegocio, "nome_negocio"),
        categoria: normalizarTexto(pedido.categoria, "categoria"),
        // O **anel inteiro** e nao so a chave actual: o `hmacs` do
        // `./identificadores.ts` e o que faz a procura de duplicados sobreviver
        // a uma rotacao do *pepper*. O `hmac` que se escreve continua a ser o
        // da actual.
        nif: new Nif(pedido.nif, this.#anelDoPepper),
        telefone: new Telefone(pedido.telefone, this.#anelDoPepper),
        email: temEmail ? new Email(pedido.email) : null,
        chave: validarChave(typeof pedido.chaveDeIdempotencia === "string" ? pedido.chaveDeIdempotencia : ""),
      };
    } catch (erro) {
      if (erro instanceof IdentificadorInvalidoError) {
        throw new RegistoRecusado("campo", `${erro.campo}_${erro.motivo}`);
      }
      // A chave de idempotência mal formada é um `ChaveInvalidaError` do
      // `../sms/contrato.ts`, e a mensagem dele leva o **comprimento** e nunca
      // o conteúdo — que é a razão por que se reusa aquele validador em vez de
      // escrever um segundo.
      if (erro instanceof Error && erro.name === "ChaveInvalidaError") {
        throw new RegistoRecusado("campo", "chave_forma");
      }
      throw erro;
    }
  }

  #redeHmac(ip: unknown): string | null {
    const prefixo = prefixoDeIp(ip);
    return prefixo === null ? null : hmacDe(this.#chave, DOMINIOS.rede, prefixo).toString("hex");
  }

  #dispositivoHmac(dispositivo: unknown): string | null {
    if (typeof dispositivo !== "string" || dispositivo.trim() === "") return null;
    const limpo = dispositivo.trim().slice(0, 256);
    return hmacDe(this.#chave, DOMINIOS.dispositivo, limpo).toString("hex");
  }
}

/** Os campos do formulário, já normalizados. Interno. */
interface Campos {
  readonly nomeNegocio: string;
  readonly categoria: string;
  readonly nif: Nif;
  readonly telefone: Telefone;
  readonly email: Email | null;
  readonly chave: string;
}
