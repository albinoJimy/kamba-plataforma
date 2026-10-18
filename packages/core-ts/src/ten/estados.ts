/**
 * A matriz de estados do CHR (KAM-009 criterio 6, `docs/tecnica/01` §7.2).
 *
 * ## O problema que esta matriz tem, e que este modulo resolve e declara
 *
 * A tabela do §7.2 tem uma coluna chamada «Estado do tenant/canal» e **funde
 * dois dominios**:
 *
 * * os estados do **tenant** sao cinco — `onboarding`, `ativo`, `restrito`,
 *   `suspenso`, `encerrado` (`01` §7.1 nao os tem; estao no DDL de
 *   `platform.tenants`, `docs/tecnica/03` §5.2, e na revisao `0001`);
 * * os estados do **canal** sao seis — `pendente`, `ativo`, `restrito`,
 *   `desligado`, `suspenso`, `encerrado` (`01` §7.1).
 *
 * A tabela tem seis linhas porque junta `onboarding` com `pendente` — que sao
 * de dominios diferentes — e acrescenta `desligado`, que **so** existe no
 * canal. E o `ChannelContext` que o mesmo §7.2 devolve carrega os **dois**
 * campos: `estado_tenant` e `estado_canal`.
 *
 * Consequencia directa: um `tenantGate(estado, accao)` de **um** parametro, que
 * e como o criterio 6 do bloco o escreve, nao exprime a matriz. Um tenant
 * `ativo` com um canal `desligado` nao tem celula nenhuma, e um tenant
 * `suspenso` com um canal `ativo` tem duas.
 *
 * ## A regra de precedencia — **PROPOSTA**, nao esta em documento nenhum
 *
 * Este modulo recebe os dois estados e reduz-os a um **regime**, que e a linha
 * da tabela do §7.2 que se aplica: decide o mais restritivo dos dois.
 *
 *     encerrado > suspenso > desligado > pendente > restrito > ativo
 *
 * O fundamento de cada degrau, porque a ordem nao vem de lado nenhum:
 *
 * * `encerrado` primeiro — e o unico terminal nas duas maquinas de estado, e a
 *   linha da tabela e «Registar e descartar». Um estado do qual nao se sai nao
 *   pode ser ultrapassado por nenhum do qual se saia.
 * * `suspenso` a seguir — a nota da tabela e «Decisao T&S ou falta de
 *   pagamento». E a unica linha cuja causa e externa a plataforma, e passar-lhe
 *   a frente por o outro dominio estar `ativo` seria continuar a servir quem a
 *   Meta ou a cobranca mandaram parar.
 * * `desligado` antes de `pendente` — a linha diz «Nenhuma entrada chega
 *   (coexistencia removida)». Nao ha caminho tecnico para o publico; um tenant
 *   `ativo` sobre um canal `desligado` nao fica a meio, fica sem canal.
 * * `pendente`/`onboarding` antes de `restrito` — `pendente` permite registar e
 *   a mensagem de teste, e mais nada («nao responder ao publico»); `restrito`
 *   permite conversar dentro da janela. `pendente` e o mais apertado dos dois.
 * * `restrito` antes de `ativo` — e o proprio sentido da palavra, e a unica
 *   relacao de ordem que a tabela torna obvia.
 *
 * **Esta ordem e uma proposta deste ticket e a decisao devolve-se ao dono do
 * `docs/tecnica/01`.** Nao ha documento que a escreva, nem sequer que admita
 * que os dois dominios se cruzam. O que aqui se faz e nao deixar o cruzamento
 * por resolver em silencio, que e o que um gate de um parametro faria.
 *
 * ## As accoes
 *
 * Sao as colunas «Entrada» e «Saida automatica» da tabela, abertas no que cada
 * celula distingue. Nao ha nenhuma que a tabela nao nomeie, e as decisoes das
 * celulas que a tabela **nao** escreve estao marcadas uma a uma no
 * `REGIMES_E_ACCOES`: todas negam, porque o principio do conjunto e falhar
 * fechado (`specs/01` §6).
 *
 * ## O que este modulo nao faz
 *
 * * **Nao limita a frequencia.** A celula de `suspenso` diz «uma vez por
 *   contacto/24 h»: isto responde «pode» e nao «quantas vezes». A contagem por
 *   contacto e de quem envia (`01` §8), e nao ha aqui estado nenhum.
 * * **Nao le a base.** E uma funcao pura sobre dois estados e uma accao; quem
 *   os obteve foi o CHR.
 * * **Nao regista nada.** Nem o tenant, nem a accao.
 */

/** Os cinco estados de `platform.tenants.estado` (revisao `0001`). */
export const ESTADOS_DO_TENANT = [
  "onboarding",
  "ativo",
  "restrito",
  "suspenso",
  "encerrado",
] as const;
export type EstadoDoTenant = (typeof ESTADOS_DO_TENANT)[number];

/** Os seis estados de `platform.tenant_channels.estado` (`01` §7.1). */
export const ESTADOS_DO_CANAL = [
  "pendente",
  "ativo",
  "restrito",
  "desligado",
  "suspenso",
  "encerrado",
] as const;
export type EstadoDoCanal = (typeof ESTADOS_DO_CANAL)[number];

/**
 * As seis linhas da tabela do §7.2, da mais restritiva para a menos.
 *
 * **A ordem do vector e a regra de precedencia**, e nao uma lista alfabetica: o
 * indice de cada regime e a sua posicao na ordem, e `maisRestritivo` compara
 * indices. Escrever a ordem como dado em vez de como cadeia de `if` e o que
 * permite ao teste de paridade confronta-la com a do Python como texto.
 */
export const REGIMES = [
  "encerrado",
  "suspenso",
  "desligado",
  "pendente",
  "restrito",
  "ativo",
] as const;
export type Regime = (typeof REGIMES)[number];

/** O regime de cada estado do tenant. `onboarding` e a linha `pendente`. */
export const REGIME_DO_TENANT: Readonly<Record<EstadoDoTenant, Regime>> = {
  onboarding: "pendente",
  ativo: "ativo",
  restrito: "restrito",
  suspenso: "suspenso",
  encerrado: "encerrado",
};

/** O regime de cada estado do canal. Um para um: as linhas sao as dele. */
export const REGIME_DO_CANAL: Readonly<Record<EstadoDoCanal, Regime>> = {
  pendente: "pendente",
  ativo: "ativo",
  restrito: "restrito",
  desligado: "desligado",
  suspenso: "suspenso",
  encerrado: "encerrado",
};

/**
 * As accoes que a matriz decide.
 *
 * `registar_entrada`            guardar a mensagem que chegou (coluna «Entrada»)
 * `processar_entrada`           correr o agente sobre ela
 * `responder_sessao`            responder dentro da janela de 24 h
 * `enviar_template_utilidade`   template de utilidade (fora da janela)
 * `enviar_template_marketing`   template de marketing
 * `mensagem_estatica`           a «Loja temporariamente indisponivel»
 * `mensagem_de_teste`           a mensagem de teste do onboarding
 */
export const ACCOES = [
  "registar_entrada",
  "processar_entrada",
  "responder_sessao",
  "enviar_template_utilidade",
  "enviar_template_marketing",
  "mensagem_estatica",
  "mensagem_de_teste",
] as const;
export type Accao = (typeof ACCOES)[number];

/**
 * A matriz: seis regimes por sete accoes, escrita por extenso.
 *
 * Por extenso, e nao derivada de regras, pela mesma razao que a lista de
 * colunas da `0007` e literal: quem vem ver o que um estado permite le uma
 * tabela e nao um algoritmo, e um teste pode compara-la celula a celula com a
 * do Python.
 *
 * Onde o §7.2 e explicito, a celula e a dele. Onde nao e, a celula nega e o
 * comentario diz que a tabela nao a escreve.
 */
export const REGIMES_E_ACCOES: Readonly<Record<Regime, Readonly<Record<Accao, boolean>>>> = {
  // «Registar; nao responder ao publico» / saida «Nenhuma» / «So mensagem de
  // teste do onboarding».
  pendente: {
    registar_entrada: true,
    processar_entrada: false,
    responder_sessao: false,
    enviar_template_utilidade: false,
    enviar_template_marketing: false,
    mensagem_estatica: false,
    mensagem_de_teste: true,
  },
  // «Normal» / «Normal».
  ativo: {
    registar_entrada: true,
    processar_entrada: true,
    responder_sessao: true,
    enviar_template_utilidade: true,
    enviar_template_marketing: true,
    mensagem_estatica: true,
    mensagem_de_teste: true,
  },
  // «Normal» / «So respostas dentro da janela; sem templates *marketing*».
  //
  // **Uma ambiguidade, e a leitura escolhida e a fechada.** «So respostas
  // dentro da janela» exclui qualquer template, porque um template e o que se
  // manda fora da janela; a segunda metade da frase — «sem templates
  // marketing» — fica entao a reforcar e nao a abrir uma excepcao. A leitura
  // contraria (templates de utilidade continuam a poder sair) tem um argumento
  // de negocio serio: um aviso de encomenda ou de pagamento e utilidade, e um
  // tenant apenas limitado por qualidade perde-o. **A decisao devolve-se ao
  // dono do `01` §7.2**; ate la nega, porque e o sentido em que falhar custa
  // menos.
  restrito: {
    registar_entrada: true,
    processar_entrada: true,
    responder_sessao: true,
    enviar_template_utilidade: false,
    enviar_template_marketing: false,
    // A tabela nao escreve esta celula. Permite porque a mensagem estatica e
    // uma resposta dentro da janela, e essas estao permitidas na linha.
    mensagem_estatica: true,
    // A tabela nao escreve esta celula. Nega: a mensagem de teste pertence ao
    // onboarding, e um canal `restrito` ja passou por ele.
    mensagem_de_teste: false,
  },
  // «Nenhuma entrada chega (coexistencia removida)» / «Nenhuma».
  //
  // `registar_entrada` nega, e e a unica linha em que nega. A tabela descreve
  // um **facto** — nao chega entrada — e nao uma permissao; se mesmo assim
  // chegar uma, chegou por um caminho que ja nao devia existir, e aceita-la
  // seria escrever numa conversa de um canal que a Meta removeu.
  desligado: {
    registar_entrada: false,
    processar_entrada: false,
    responder_sessao: false,
    enviar_template_utilidade: false,
    enviar_template_marketing: false,
    mensagem_estatica: false,
    mensagem_de_teste: false,
  },
  // «Registar» / «Mensagem estatica ("Loja temporariamente indisponivel") uma
  // vez por contacto/24 h». O «uma vez por 24 h» nao se decide aqui.
  suspenso: {
    registar_entrada: true,
    processar_entrada: false,
    responder_sessao: false,
    enviar_template_utilidade: false,
    enviar_template_marketing: false,
    mensagem_estatica: true,
    mensagem_de_teste: false,
  },
  // «Registar e descartar» / «Nenhuma». O descarte e o que resta de registar e
  // nao poder fazer mais nada; nao ha uma terceira decisao para ele.
  encerrado: {
    registar_entrada: true,
    processar_entrada: false,
    responder_sessao: false,
    enviar_template_utilidade: false,
    enviar_template_marketing: false,
    mensagem_estatica: false,
    mensagem_de_teste: false,
  },
};

/** Um estado ou uma accao que nao esta nas listas. Nao se adivinha: levanta. */
export class EstadoDesconhecidoError extends Error {
  constructor(campo: string, valor: unknown) {
    super(
      `${campo} desconhecido: ${JSON.stringify(valor)}. ` +
        "Um estado que nao esta na lista nao se trata como o mais parecido.",
    );
    this.name = "EstadoDesconhecidoError";
  }
}

/** O mais restritivo de dois regimes, pela ordem de `REGIMES`. */
export function maisRestritivo(a: Regime, b: Regime): Regime {
  return REGIMES.indexOf(a) <= REGIMES.indexOf(b) ? a : b;
}

/**
 * O regime que se aplica a um par (estado do tenant, estado do canal).
 *
 * E aqui que os dois dominios se cruzam, e e a unica funcao deste modulo que
 * depende da precedencia **proposta** da docstring.
 */
export function regimeDe(estadoTenant: unknown, estadoCanal: unknown): Regime {
  if (
    typeof estadoTenant !== "string" ||
    !(estadoTenant in REGIME_DO_TENANT)
  ) {
    throw new EstadoDesconhecidoError("estado_tenant", estadoTenant);
  }
  if (typeof estadoCanal !== "string" || !(estadoCanal in REGIME_DO_CANAL)) {
    throw new EstadoDesconhecidoError("estado_canal", estadoCanal);
  }
  return maisRestritivo(
    REGIME_DO_TENANT[estadoTenant as EstadoDoTenant],
    REGIME_DO_CANAL[estadoCanal as EstadoDoCanal],
  );
}

/** O que a matriz respondeu, e porque. */
export interface DecisaoDoGate {
  /** A accao e permitida? */
  readonly permitido: boolean;
  /** A linha da tabela do §7.2 que decidiu. */
  readonly regime: Regime;
  /** Qual dos dois dominios impos o regime: `tenant`, `canal` ou `ambos`. */
  readonly origem: "tenant" | "canal" | "ambos";
}

/**
 * A matriz do §7.2, com os **dois** estados do `ChannelContext`.
 *
 * Assinatura de tres argumentos, e nao a de dois do criterio 6: ver a docstring
 * do modulo. A `origem` existe para quem precisa de explicar a recusa sem
 * voltar a correr a precedencia — e, no caso `ambos`, de saber que nao ha um
 * unico culpado.
 */
export function tenantGate(
  estadoTenant: unknown,
  estadoCanal: unknown,
  accao: unknown,
): DecisaoDoGate {
  const regime = regimeDe(estadoTenant, estadoCanal);
  if (typeof accao !== "string" || !(accao in REGIMES_E_ACCOES[regime])) {
    throw new EstadoDesconhecidoError("accao", accao);
  }
  const doTenant = REGIME_DO_TENANT[estadoTenant as EstadoDoTenant];
  const doCanal = REGIME_DO_CANAL[estadoCanal as EstadoDoCanal];
  const origem =
    doTenant === doCanal ? "ambos" : regime === doTenant ? "tenant" : "canal";
  return {
    permitido: REGIMES_E_ACCOES[regime][accao as Accao],
    regime,
    origem,
  };
}
