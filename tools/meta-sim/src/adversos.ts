/**
 * Os oito casos adversos, nomeados e com o desfecho que se espera de cada um
 * (KAM-024, critério 3).
 *
 * O critério enumera-os: «assinatura inválida, JSON inválido assinado, corpo
 * duplicado, mesma mensagem em dois corpos, ordem trocada, lote de várias
 * `entry`, `wa_id` omitido (apenas BSUID/`username`), `phone_number_id`
 * desconhecido». Cada um é um caso aqui, com o seu nome, e um teste por nome.
 *
 * ## Porque é que o desfecho esperado vive no caso e não no teste
 *
 * Um gerador de *fixtures* que só produza bytes deixa a parte difícil — «o que é
 * que isto devia dar?» — para quem escreve o teste, e aí cada *suite* responde
 * à sua maneira. Pior: a resposta certa não é óbvia em metade destes casos. Um
 * **JSON inválido mas bem assinado** dá **200**, não 400: a Meta repete durante
 * sete dias o que não receber 200, e repetir um corpo que nunca vai dar *parse*
 * é tráfego perdido duas vezes — o corpo entra na fila e é o *worker* que o
 * manda para a quarentena. Um **corpo duplicado** dá 200 **duas vezes** e **um**
 * *job*, porque o `jobId` é o `sha256` dos bytes. A **mesma mensagem em dois
 * corpos** dá **dois** *jobs* (os bytes diferem) e **uma** linha em
 * `inbound_events`, porque a chave de deduplicação é o `wamid`. São três
 * respostas diferentes para três casos que se parecem, e escrevê-las aqui, ao
 * lado dos bytes, é o que impede que um teste futuro afirme a errada.
 *
 * O campo `desfecho` é o `outcome` que o GWY registra, e `esperado` é a frase
 * que diz o que tem de acontecer a jusante. Os testes do critério 3 lêem os dois.
 */

import { assinar, assinarMal } from "./assinatura.ts";
import { corpo, corpoMisturado, mudarUmByte, serializar, type Corpo } from "./corpo.ts";
import { canalDe, interlocutorDe, type Canal, type Interlocutor } from "./identificadores.ts";
import { escada } from "./estados.ts";
import type { Gerador } from "./semente.ts";

/** Um POST: os bytes, o cabeçalho e o estado HTTP que o GWY tem de devolver. */
export interface Pedido {
  readonly bytes: Uint8Array;
  readonly assinatura: string;
  readonly estado: number;
  /** O `outcome` do registo do GWY. `null` quando o caso não o fixa. */
  readonly desfecho: string | null;
}

/** Um caso adverso: um ou dois POSTs e o que tem de acontecer a jusante. */
export interface CasoAdverso {
  readonly nome: string;
  /** Porque é que este caso existe — a frase do critério, ou o facto que o cria. */
  readonly porque: string;
  readonly pedidos: readonly Pedido[];
  /** O que tem de acontecer **depois** do 200: *jobs*, linhas, quarentena. */
  readonly esperado: string;
}

/** Os oito nomes, na ordem do critério. */
export const NOMES = [
  "assinatura_invalida",
  "json_invalido_assinado",
  "corpo_duplicado",
  "mesma_mensagem_em_dois_corpos",
  "ordem_trocada",
  "lote_de_entries",
  "wa_id_omitido",
  "phone_number_id_desconhecido",
] as const;
export type Nome = (typeof NOMES)[number];

/** O que o chamador tem de dar: o canal conhecido, quem fala, e o segredo. */
export interface Contexto {
  readonly canal: Canal;
  readonly quem: Interlocutor;
  readonly segredo: string;
}

function pedido(
  corpoOuBytes: Corpo | Uint8Array,
  segredo: string,
  estado: number,
  desfecho: string | null,
): Pedido {
  const bytes = corpoOuBytes instanceof Uint8Array ? corpoOuBytes : serializar(corpoOuBytes);
  return { bytes, assinatura: assinar(bytes, segredo), estado, desfecho };
}

/**
 * Os oito casos, para um contexto.
 *
 * A ordem das chamadas ao gerador é fixa, e por isso os bytes de cada caso são
 * estáveis para uma semente — o que faz destes casos *fixtures* e não só
 * geradores. Quem precisar de um só caso corre a função inteira e escolhe pelo
 * nome: pedir um caso de cada vez mudava a ordem das chamadas e com ela os bytes.
 */
export function casosAdversos(g: Gerador, ctx: Contexto): readonly CasoAdverso[] {
  const { canal, quem, segredo } = ctx;

  // 1. Assinatura inválida: corpo bom, resumo com um nibble trocado.
  const bom = serializar(
    corpo(g, { canal, mudancas: [{ campo: "messages", opcoes: { canal, quem } }] }),
  );
  const um: CasoAdverso = {
    nome: "assinatura_invalida",
    porque: "o criterio 3 pede-o, e o criterio 4 pede o 401 a 1 byte de diferenca",
    pedidos: [
      {
        bytes: bom,
        assinatura: assinarMal(bom, segredo),
        estado: 401,
        desfecho: "assinatura_invalida",
      },
    ],
    esperado: "0 jobs na fila; a metrica gwy_sig_fail incrementa; nada do corpo vai ao registo",
  };

  // 2. JSON inválido, **bem** assinado. Uma chave de abertura a mais no fim: os
  // bytes são assináveis, o `JSON.parse` falha, e o GWY não faz `parse` nenhum.
  const quebrado = new Uint8Array([...bom, 0x7b]);
  const dois: CasoAdverso = {
    nome: "json_invalido_assinado",
    porque: "a assinatura e sobre bytes, e o GWY nao faz parse antes de responder",
    pedidos: [pedido(quebrado, segredo, 200, "webhook_enfileirado")],
    esperado:
      "200 e 1 job: o parse falha no worker, que o manda para a quarentena. " +
      "Um 400 aqui fazia a Meta repetir sete dias",
  };

  // 3. Corpo duplicado: os **mesmos** bytes duas vezes.
  const tres: CasoAdverso = {
    nome: "corpo_duplicado",
    porque: "a Meta repete o mesmo POST quando nao recebe 200 a tempo",
    pedidos: [
      pedido(bom, segredo, 200, "webhook_enfileirado"),
      pedido(bom, segredo, 200, "webhook_enfileirado"),
    ],
    esperado:
      "2 respostas 200 e 1 job: o jobId e o sha256 dos bytes, e a fila e idempotente por jobId",
  };

  // 4. A mesma mensagem em **dois** corpos diferentes. Os bytes diferem (o
  // `entry.time` muda), logo são dois *jobs*; o `wamid` é o mesmo, logo é uma
  // linha. É o caso que separa a idempotência da fila da do evento.
  const semente = g.derivar("mesma-mensagem");
  const primeiro = corpo(semente, {
    canal,
    mudancas: [{ campo: "messages", opcoes: { canal, quem } }],
    tempo: 1_790_812_800,
  });
  const segundo: Corpo = {
    ...primeiro,
    entry: primeiro.entry.map((e) => ({ ...e, time: 1_790_812_801 })),
  };
  const quatro: CasoAdverso = {
    nome: "mesma_mensagem_em_dois_corpos",
    porque: "a Meta reenvia a mesma mensagem em corpos diferentes (E1 §5)",
    pedidos: [
      pedido(primeiro, segredo, 200, "webhook_enfileirado"),
      pedido(segundo, segredo, 200, "webhook_enfileirado"),
    ],
    esperado:
      "2 jobs (bytes diferentes) e 1 linha em inbound_events: a chave do evento e o wamid",
  };

  // 5. Ordem trocada: `read`, `delivered`, `sent` do mesmo `wamid`.
  const alvo = `wamid.${g.texto(32, "ABCDEFGHIJKLMNOPQRSTUVWXYZabcdefghijklmnopqrstuvwxyz0123456789")}`;
  const degraus = escada(g, {
    wamid: alvo,
    recipienteId: quem.waId,
    recipienteUserId: quem.userId,
  });
  const trocado: Corpo = {
    object: "whatsapp_business_account",
    entry: [
      {
        id: canal.wabaId,
        time: 1_790_812_800,
        changes: [
          {
            field: "messages",
            value: {
              messaging_product: "whatsapp",
              metadata: {
                display_phone_number: canal.displayPhoneNumber,
                phone_number_id: canal.phoneNumberId,
              },
              statuses: [...degraus].reverse(),
            },
          },
        ],
      },
    ],
  };
  const cinco: CasoAdverso = {
    nome: "ordem_trocada",
    porque: "os estados chegam sem ordem garantida (E1 §5, CONFIRMADO)",
    pedidos: [pedido(trocado, segredo, 200, "webhook_enfileirado")],
    esperado:
      "200 e 3 eventos statuses; o estado final da mensagem fica read e nao sent " +
      "— a monotonia e do KAM-015, e esta fixture e o que a prova",
  };

  // 6. Lote de várias `entry`, de WABAs diferentes no mesmo POST.
  const outroCanal = canalDe(g);
  const outroQuem = interlocutorDe(g);
  const lote = corpoMisturado(g, [
    { canal, mudancas: [{ campo: "messages", opcoes: { canal, quem } }] },
    {
      canal: outroCanal,
      mudancas: [{ campo: "messages", opcoes: { canal: outroCanal, quem: outroQuem } }],
    },
    {
      canal,
      mudancas: [{ campo: "account_update", opcoes: { canal, quem, motivo: "CHANGE_NUMBER" } }],
    },
  ]);
  const seis: CasoAdverso = {
    nome: "lote_de_entries",
    porque: "a Meta agrupa entries de WABAs diferentes num POST (E1 §5: multiplexar por entry.id)",
    pedidos: [pedido(lote, segredo, 200, "webhook_enfileirado")],
    esperado:
      "1 job e 3 eventos, cada um com o seu waba_id; um GWY que assuma um WABA " +
      "por pedido atribui os tres ao primeiro",
  };

  // 7. `wa_id` omitido: só BSUID. Confirmado no `E1` §3.
  const sete: CasoAdverso = {
    nome: "wa_id_omitido",
    porque: "o wa_id e omitido se o utilizador adoptou username e nao ha contacto recente (E1 §3)",
    pedidos: [
      pedido(
        corpo(g, {
          canal,
          mudancas: [{ campo: "messages", opcoes: { canal, quem, comWaId: false } }],
        }),
        segredo,
        200,
        "webhook_enfileirado",
      ),
    ],
    esperado:
      "200 e 1 evento; o CHR resolve o contacto so pelo BSUID, e nenhuma coluna " +
      "de telefone e escrita",
  };

  // 8. `phone_number_id` desconhecido: um canal que não está em
  // `tenant_channels`. Não é erro de protocolo — é um canal que ninguém
  // registou, e tem o seu motivo de quarentena próprio.
  const desconhecido = canalDe(g);
  const oito: CasoAdverso = {
    nome: "phone_number_id_desconhecido",
    porque: "um canal nao registado chega de verdade: um numero novo, ou um tenant removido",
    pedidos: [
      pedido(
        corpo(g, {
          canal: desconhecido,
          mudancas: [{ campo: "messages", opcoes: { canal: desconhecido, quem } }],
        }),
        segredo,
        200,
        "webhook_enfileirado",
      ),
    ],
    esperado:
      "200 e 1 linha em unrouted_events com motivo canal_desconhecido; 0 linhas " +
      "em conversations, e o alerta do KAM-014 dispara",
  };

  return [um, dois, tres, quatro, cinco, seis, sete, oito];
}

/**
 * Os bytes de um corpo com **um** alterado, mais a assinatura do **original**.
 *
 * É o caso negativo do critério 4 pelo lado do corpo. Fica aqui, e não no
 * `corpo.ts`, porque é um caso adverso e não uma primitiva de serialização;
 * `mudarUmByte` é a primitiva.
 */
export function corpoMexido(bytes: Uint8Array, segredo: string): Pedido {
  return {
    bytes: mudarUmByte(bytes),
    assinatura: assinar(bytes, segredo),
    estado: 401,
    desfecho: "assinatura_invalida",
  };
}
