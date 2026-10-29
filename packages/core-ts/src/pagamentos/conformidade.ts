/**
 * A suite de conformidade do `docs/tecnica/04` §3.5 (KAM-052, criterio 9).
 *
 * «Casos obrigatorios: assinatura adulterada ⇒ rejeita; valor ± 1 centimo ⇒
 * divergencia; referencia desconhecida ⇒ orfao; callback duplicado ×10 ⇒ 1
 * efeito; callback fora de ordem; pagamento depois de `valid_until`; *timeout*
 * na criacao com resposta perdida (idempotencia); rotacao de chave; 429;
 * `status()` concorda com o callback. Um adaptador sem a suite verde nao e
 * activavel em producao.»
 *
 * **Sao dez, contados.** O `CASOS` abaixo tem dez entradas e o
 * `test_sao_os_dez_casos_do_documento` conta-as — porque «os dez casos
 * obrigatorios» e uma afirmacao que se cumpre a letra ou nao se cumpre, e um
 * harness com nove passava com ar de completo.
 *
 * ## O que o harness mede, e o que **nao** mede
 *
 * Mede propriedades do **adaptador**: o que ele faz com bytes que chegam e com
 * chamadas que falham. Nao mede o ledger, a projeccao de estado nem a decisao
 * de confirmar — isso e o KAM-053 e a regra do §5, e um harness que as medisse
 * estaria a testar o PAY e nao o adaptador, com o efeito pratico de cada
 * adaptador novo ter de reimplementar o PAY para passar.
 *
 * A fronteira cai em dois sitios que vale nomear, porque e onde um leitor
 * esperaria mais:
 *
 * * **«valor ± 1 centimo ⇒ divergencia»** — quem decide que ha divergencia e o
 *   §5, comparando com a cobranca. O que o adaptador tem de garantir, e o que
 *   se mede aqui, e que o valor **sobrevive exacto** ao percurso: um centimo a
 *   mais chega como um centimo a mais. E precisamente isto que uma conversao
 *   por `number` perde — `amountFormat: 'decimal2'` obriga a ler `"1234.57"` e
 *   um `parseFloat` desse valor nao devolve 123457 centimos de forma fiavel.
 *   Sem esta propriedade a divergencia do §5 e indetectavel, e com ela a
 *   deteccao e aritmetica de inteiros.
 * * **«callback duplicado ×10 ⇒ 1 efeito»** — o efeito unico e da base
 *   (`UNIQUE` em `provider_event_id`, KAM-053). O que o adaptador tem de
 *   garantir e que as dez entregas do **mesmo** callback produzem o **mesmo**
 *   `provider_event_id`; sem isso a unicidade da base nao tem por onde morder.
 *   O harness deduplica por essa chave e exige **uma**.
 *
 * ## Porque e que o harness precisa de um banco de ensaio
 *
 * Nenhum destes dez casos se produz chamando so a interface: assinar um corpo
 * exige a chave, adulterar uma assinatura exige saber onde ela esta, e provocar
 * um 429 exige o lado do facilitador. Esse conhecimento e **por adaptador** — o
 * ProxyPay RPS assina em `X-Signature` com HMAC-SHA256 sobre o corpo cru (§3.3),
 * o AppyPay nao se sabe (§3.4) —, e por isso o harness toma um
 * `BancoDeEnsaio` que cada adaptador fornece. O harness fica com os casos; o
 * adaptador fica com a forma de os provocar.
 *
 * O KAM-054 (ManualProvider) e o KAM-056 (ProxyPay) importam o `correr` daqui.
 */

import {
  AuthError,
  type AccountSecrets,
  type CreateChargeReq,
  type Minor,
  type PaymentProvider,
  ProviderError,
  type ProviderRef,
  type RawHttpCallback,
  type VerifiedEvent,
} from "./tipos.ts";

/** Os dez casos do §3.5, pela ordem em que o documento os escreve. */
export const CASOS = [
  "assinatura_adulterada_rejeita",
  "valor_mais_um_centimo_sobrevive_exacto",
  "referencia_desconhecida_e_orfao",
  "callback_duplicado_dez_vezes_um_efeito",
  "callback_fora_de_ordem",
  "pagamento_depois_de_valid_until",
  "criacao_com_resposta_perdida_e_idempotente",
  "rotacao_de_chave",
  "rate_limit_429",
  "status_concorda_com_o_callback",
] as const;

export type Caso = (typeof CASOS)[number];

/** Qual a falha que o banco deve provocar na proxima chamada ao facilitador. */
export type FalhaProgramada = "rate_limit" | "resposta_perdida" | null;

/**
 * O que um adaptador tem de saber fazer para ser medido.
 *
 * Tudo o que esta aqui e conhecimento **do adaptador** sobre o seu facilitador.
 * O harness nao sabe assinar nada.
 */
export type BancoDeEnsaio = {
  readonly provider: PaymentProvider;
  /** As credenciais da conta de ensaio, com a referencia anterior preenchida. */
  readonly conta: AccountSecrets;
  /** Um pedido valido, para o caso da idempotencia. */
  pedido(): CreateChargeReq;
  /**
   * Um callback **genuino** para um evento, assinado com a chave indicada.
   *
   * `chave: 'anterior'` assina com a credencial anterior, que e o caso 8.
   */
  callback(
    evento: Pick<VerifiedEvent, "providerEventId" | "valor" | "ocorridoEm"> & {
      readonly referencia?: string;
    },
    chave?: "actual" | "anterior",
  ): Promise<RawHttpCallback>;
  /** O mesmo callback com a assinatura estragada, e **so** a assinatura. */
  adulterar(callback: RawHttpCallback): RawHttpCallback;
  /** Programa a proxima chamada ao facilitador para falhar assim. */
  programar(falha: FalhaProgramada): void;
  /** A referencia pela qual se consulta o estado de um callback. */
  refDe(evento: VerifiedEvent): ProviderRef;
  /** Uma referencia que o facilitador nao conhece. */
  refDesconhecida(): ProviderRef;
};

export type ResultadoDoCaso = {
  readonly caso: Caso;
  readonly ok: boolean;
  /** Vazio quando passou; a razao da falha quando nao. */
  readonly detalhe: string;
};

export type Veredicto = {
  readonly adaptador: string;
  readonly resultados: readonly ResultadoDoCaso[];
  readonly verde: boolean;
};

function ok(caso: Caso): ResultadoDoCaso {
  return { caso, ok: true, detalhe: "" };
}

function falha(caso: Caso, detalhe: string): ResultadoDoCaso {
  return { caso, ok: false, detalhe };
}

/** O instante de um evento, em UTC. */
function instante(deslocamentoMs: number): string {
  return new Date(Date.UTC(2026, 9, 29, 12, 0, 0) + deslocamentoMs).toISOString();
}

/** Caso 1: uma assinatura adulterada e recusada com `AuthError`. */
async function _caso1(banco: BancoDeEnsaio): Promise<ResultadoDoCaso> {
  const caso: Caso = "assinatura_adulterada_rejeita";
  const genuino = await banco.callback({
    providerEventId: "ev-1",
    valor: 123_457n,
    ocorridoEm: instante(0),
  });
  const adulterado = banco.adulterar(genuino);
  try {
    await banco.provider.verifyCallback(adulterado, banco.conta);
  } catch (erro) {
    if (erro instanceof AuthError) return ok(caso);
    return falha(caso, `recusou, mas com ${(erro as Error).name} e nao AuthError`);
  }
  return falha(
    caso,
    "aceitou um callback com a assinatura adulterada — um terceiro podia " +
      "confirmar pagamentos (ADR-013, docs/tecnica/04 §5)",
  );
}

/**
 * Caso 2: um centimo a mais sobrevive exacto.
 *
 * **O valor de ensaio e `102409n` — 1024,09 Kz — e foi escolhido por medicao.**
 *
 * A primeira versao deste caso usava `123457n` (1234,57 Kz), por o `.57`
 * parecer o tipo de fraccao que um `float` estraga. Nao estraga:
 * `parseFloat("1234.57") * 100` da **123457 exacto**, e o canario que tira a
 * barreira ao `FakeProvider` — `valorPorFloat` — passava este caso com a
 * barreira tirada. Isto e, o caso **nao media nada**, e foi o canario que o
 * disse.
 *
 * `1024.09` e o primeiro valor acima de 1.000 Kz em que
 * `Math.trunc(parseFloat(t) * 100)` perde um centimo (da 102408, varrimento de
 * todos os `kz.cc` ate 60.000, Node 24.21.0). Com ele, um adaptador que converta
 * por `number` **falha** este caso — que e o unico estado em que a caixa do
 * criterio 9 se pode marcar.
 */
async function _caso2(banco: BancoDeEnsaio): Promise<ResultadoDoCaso> {
  const caso: Caso = "valor_mais_um_centimo_sobrevive_exacto";
  const esperado: Minor = 102_409n;
  const cb = await banco.callback({
    providerEventId: "ev-2",
    valor: esperado,
    ocorridoEm: instante(0),
  });
  const eventos = await banco.provider.verifyCallback(cb, banco.conta);
  const primeiro = eventos[0];
  if (primeiro === undefined) return falha(caso, "o callback genuino nao produziu evento nenhum");
  if (typeof primeiro.valor !== "bigint") {
    return falha(caso, `o valor veio como ${typeof primeiro.valor} e nao bigint`);
  }
  if (primeiro.valor !== esperado) {
    return falha(
      caso,
      `o valor nao sobreviveu exacto: esperado ${esperado}, recebido ` +
        `${primeiro.valor}. Um centimo perdido aqui torna a divergencia do §5 ` +
        "indetectavel.",
    );
  }
  return ok(caso);
}

/** Caso 3: um callback autentico de uma referencia desconhecida e orfao, nao um erro. */
async function _caso3(banco: BancoDeEnsaio): Promise<ResultadoDoCaso> {
  const caso: Caso = "referencia_desconhecida_e_orfao";
  const cb = await banco.callback({
    providerEventId: "ev-3",
    valor: 50_000n,
    ocorridoEm: instante(0),
    referencia: "999999999",
  });
  let eventos: readonly VerifiedEvent[];
  try {
    eventos = await banco.provider.verifyCallback(cb, banco.conta);
  } catch (erro) {
    return falha(
      caso,
      `recusou um callback autentico de referencia desconhecida com ` +
        `${(erro as Error).name}: um orfao e para registar e investigar (§8), ` +
        "nao para descartar — descartar perde o pagamento de um cliente",
    );
  }
  if (eventos.length === 0) {
    return falha(caso, "verificou e devolveu zero eventos: o orfao desapareceu em silencio");
  }
  const estado = await banco.provider.status(banco.refDesconhecida());
  if (estado.estado !== "desconhecida") {
    return falha(
      caso,
      `status() de uma referencia desconhecida devolveu '${estado.estado}' e ` +
        "nao 'desconhecida'",
    );
  }
  return ok(caso);
}

/** Caso 4: dez entregas do mesmo callback dao o mesmo `provider_event_id`. */
async function _caso4(banco: BancoDeEnsaio): Promise<ResultadoDoCaso> {
  const caso: Caso = "callback_duplicado_dez_vezes_um_efeito";
  const cb = await banco.callback({
    providerEventId: "ev-4",
    valor: 75_000n,
    ocorridoEm: instante(0),
  });
  const chaves = new Set<string>();
  for (let n = 0; n < 10; n += 1) {
    const eventos = await banco.provider.verifyCallback(cb, banco.conta);
    for (const evento of eventos) chaves.add(evento.providerEventId);
  }
  if (chaves.size !== 1) {
    return falha(
      caso,
      `dez entregas do mesmo callback produziram ${chaves.size} chaves de ` +
        `deduplicacao (${[...chaves].join(", ")}): a unicidade por ` +
        "provider_event_id (KAM-053) nao tem por onde morder, e o mesmo " +
        "pagamento confirma-se mais de uma vez",
    );
  }
  return ok(caso);
}

/** Caso 5: a verificacao nao depende da ordem de chegada. */
async function _caso5(banco: BancoDeEnsaio): Promise<ResultadoDoCaso> {
  const caso: Caso = "callback_fora_de_ordem";
  const cedo = await banco.callback({
    providerEventId: "ev-5a",
    valor: 10_000n,
    ocorridoEm: instante(0),
  });
  const tarde = await banco.callback({
    providerEventId: "ev-5b",
    valor: 10_000n,
    ocorridoEm: instante(60_000),
  });
  const porOrdem = [
    ...(await banco.provider.verifyCallback(cedo, banco.conta)),
    ...(await banco.provider.verifyCallback(tarde, banco.conta)),
  ];
  const invertido = [
    ...(await banco.provider.verifyCallback(tarde, banco.conta)),
    ...(await banco.provider.verifyCallback(cedo, banco.conta)),
  ];
  const chave = (eventos: readonly VerifiedEvent[]): string =>
    [...eventos].map((e) => `${e.providerEventId}@${e.ocorridoEm}`).sort().join("|");
  if (chave(porOrdem) !== chave(invertido)) {
    return falha(
      caso,
      "a verificacao depende da ordem de chegada: " +
        `${chave(porOrdem)} contra ${chave(invertido)}. A ordem de um callback ` +
        "nao e garantida (§3.3: reentregas e duplicados possiveis), e o " +
        "instante tem de vir do evento e nao da chegada",
    );
  }
  return ok(caso);
}

/**
 * Caso 6: um pagamento depois do `valid_until` verifica-se e e reportado tarde.
 *
 * A propriedade e **nao descartar**: o cliente pagou, e o dinheiro esta na conta
 * da PME independentemente de a referencia ter expirado no nosso lado. O que o
 * §7.2 manda e tratar como divergencia e devolver/encaminhar, nunca ignorar —
 * e um adaptador que recusasse a autenticacao por causa da hora tornava esse
 * tratamento impossivel.
 */
async function _caso6(banco: BancoDeEnsaio): Promise<ResultadoDoCaso> {
  const caso: Caso = "pagamento_depois_de_valid_until";
  const pedido = banco.pedido();
  const depois = new Date(Date.parse(pedido.validUntil) + 3_600_000).toISOString();
  const cb = await banco.callback({
    providerEventId: "ev-6",
    valor: pedido.amount,
    ocorridoEm: depois,
  });
  let eventos: readonly VerifiedEvent[];
  try {
    eventos = await banco.provider.verifyCallback(cb, banco.conta);
  } catch (erro) {
    return falha(
      caso,
      `recusou um pagamento autentico recebido depois do valid_until com ` +
        `${(erro as Error).name}: o cliente pagou, e descartar o callback perde ` +
        "o pagamento em vez de o tratar como divergencia (§7.2)",
    );
  }
  const primeiro = eventos[0];
  if (primeiro === undefined) return falha(caso, "verificou e devolveu zero eventos");
  if (primeiro.ocorridoEm !== depois) {
    return falha(
      caso,
      `o instante reportado (${primeiro.ocorridoEm}) nao e o do evento ` +
        `(${depois}): sem ele ninguem pode comparar com o valid_until`,
    );
  }
  return ok(caso);
}

/** Caso 7: criar duas vezes com o mesmo `chargeId` da a mesma cobranca. */
async function _caso7(banco: BancoDeEnsaio): Promise<ResultadoDoCaso> {
  const caso: Caso = "criacao_com_resposta_perdida_e_idempotente";
  const pedido = banco.pedido();
  banco.programar("resposta_perdida");
  let primeiraFalhou = false;
  try {
    await banco.provider.createCharge(pedido);
  } catch (erro) {
    primeiraFalhou = true;
    if (!(erro instanceof ProviderError) || erro.codigo !== "TIMEOUT_UNKNOWN") {
      return falha(
        caso,
        `uma resposta perdida tem de dar TIMEOUT_UNKNOWN (§3.1) e deu ` +
          `${erro instanceof ProviderError ? erro.codigo : (erro as Error).name}: ` +
          "o PAY precisa de distinguir «nao sei» de «falhou» para nao criar " +
          "uma segunda cobranca sobre uma que talvez exista",
      );
    }
  }
  if (!primeiraFalhou) {
    return falha(caso, "a falha programada nao se manifestou: o banco de ensaio nao a aplicou");
  }
  const segunda = await banco.provider.createCharge(pedido);
  const terceira = await banco.provider.createCharge(pedido);
  if (JSON.stringify(segunda, _comBigint) !== JSON.stringify(terceira, _comBigint)) {
    return falha(
      caso,
      "duas criacoes com o mesmo chargeId deram cobrancas diferentes: o " +
        "chargeId e a chave de idempotencia (§3.1), e sem isto uma resposta " +
        "perdida produz duas referencias para a mesma encomenda",
    );
  }
  return ok(caso);
}

/** `JSON.stringify` nao sabe serializar `bigint`; e dinheiro, nao se converte a `number`. */
function _comBigint(_chave: string, valor: unknown): unknown {
  return typeof valor === "bigint" ? `${valor}n` : valor;
}

/** Caso 8: durante a janela de rotacao, a chave anterior ainda verifica. */
async function _caso8(banco: BancoDeEnsaio): Promise<ResultadoDoCaso> {
  const caso: Caso = "rotacao_de_chave";
  if (banco.conta.credenciaisRefAnterior === undefined) {
    return falha(
      caso,
      "a conta de ensaio nao tem credenciaisRefAnterior: sem a janela de duas " +
        "chaves do §3.3 a rotacao e uma interrupcao de servico",
    );
  }
  const comAnterior = await banco.callback(
    { providerEventId: "ev-8", valor: 20_000n, ocorridoEm: instante(0) },
    "anterior",
  );
  try {
    const eventos = await banco.provider.verifyCallback(comAnterior, banco.conta);
    if (eventos.length === 0) return falha(caso, "verificou e devolveu zero eventos");
  } catch (erro) {
    return falha(
      caso,
      `recusou um callback assinado com a chave anterior (${(erro as Error).name}): ` +
        "a rotacao exige aceitar as duas durante a janela (§3.3)",
    );
  }
  return ok(caso);
}

/** Caso 9: o limite de taxa e `RATE_LIMIT` e nao um erro generico. */
async function _caso9(banco: BancoDeEnsaio): Promise<ResultadoDoCaso> {
  const caso: Caso = "rate_limit_429";
  banco.programar("rate_limit");
  try {
    await banco.provider.createCharge(banco.pedido());
  } catch (erro) {
    if (erro instanceof ProviderError && erro.codigo === "RATE_LIMIT") return ok(caso);
    return falha(
      caso,
      `um 429 deu ${erro instanceof ProviderError ? erro.codigo : (erro as Error).name} ` +
        "e nao RATE_LIMIT: so com o codigo certo e que o chamador recua com " +
        "jitter em vez de tratar como indisponibilidade (§3.3)",
    );
  }
  return falha(caso, "o 429 programado nao se manifestou");
}

/** Caso 10: `status()` concorda com o callback. */
async function _caso10(banco: BancoDeEnsaio): Promise<ResultadoDoCaso> {
  const caso: Caso = "status_concorda_com_o_callback";
  const cb = await banco.callback({
    providerEventId: "ev-10",
    valor: 99_999n,
    ocorridoEm: instante(0),
  });
  const eventos = await banco.provider.verifyCallback(cb, banco.conta);
  const evento = eventos[0];
  if (evento === undefined) return falha(caso, "o callback genuino nao produziu evento nenhum");
  const estado = await banco.provider.status(banco.refDe(evento));
  if (estado.estado !== "paga") {
    return falha(
      caso,
      `o callback diz pago e status() diz '${estado.estado}': o §5 exige que a ` +
        "consulta concorde com o callback, e e a discordancia que denuncia um " +
        "callback forjado que passou a assinatura",
    );
  }
  if (estado.valor !== evento.valor) {
    return falha(
      caso,
      `o valor discorda: callback ${evento.valor}, status() ${estado.valor ?? "ausente"}`,
    );
  }
  return ok(caso);
}

const EXECUTORES: Readonly<Record<Caso, (banco: BancoDeEnsaio) => Promise<ResultadoDoCaso>>> = {
  assinatura_adulterada_rejeita: _caso1,
  valor_mais_um_centimo_sobrevive_exacto: _caso2,
  referencia_desconhecida_e_orfao: _caso3,
  callback_duplicado_dez_vezes_um_efeito: _caso4,
  callback_fora_de_ordem: _caso5,
  pagamento_depois_de_valid_until: _caso6,
  criacao_com_resposta_perdida_e_idempotente: _caso7,
  rotacao_de_chave: _caso8,
  rate_limit_429: _caso9,
  status_concorda_com_o_callback: _caso10,
};

/**
 * Corre os dez casos e devolve o veredicto.
 *
 * **Nao para no primeiro erro**, de propria decisao: quem esta a escrever um
 * adaptador quer a lista inteira de uma vez, e um harness que para no primeiro
 * transforma dez casos em dez execucoes.
 *
 * Um caso que **levanta** em vez de devolver conta como falha com o erro no
 * detalhe: um harness que deixasse a excepcao subir dava «a suite rebentou» em
 * vez de «o caso 7 falhou assim», e e a segunda que diz o que fazer.
 */
export async function correr(banco: BancoDeEnsaio): Promise<Veredicto> {
  const resultados: ResultadoDoCaso[] = [];
  for (const caso of CASOS) {
    banco.programar(null);
    try {
      resultados.push(await EXECUTORES[caso](banco));
    } catch (erro) {
      resultados.push(falha(caso, `levantou ${(erro as Error).name}: ${(erro as Error).message}`));
    }
  }
  return {
    adaptador: banco.provider.id,
    resultados,
    verde: resultados.every((r) => r.ok),
  };
}

/** As falhas de um veredicto, numa linha cada, para uma mensagem de teste. */
export function relatorio(veredicto: Veredicto): string {
  const falhas = veredicto.resultados.filter((r) => !r.ok);
  if (falhas.length === 0) return `${veredicto.adaptador}: os ${CASOS.length} casos passam`;
  return [
    `${veredicto.adaptador}: ${falhas.length} de ${CASOS.length} casos falham`,
    ...falhas.map((r) => `  ${r.caso}: ${r.detalhe}`),
  ].join("\n");
}
