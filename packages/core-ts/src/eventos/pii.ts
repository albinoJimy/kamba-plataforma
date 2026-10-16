/**
 * Guarda de PII do envelope — o espelho em TypeScript do guarda de `evt_emitir`.
 *
 * `platform.evt_emitir` recusa, com `check_violation`, um `payload` que contenha
 * um padrão de telefone (`docs/tecnica/06` §6.1):
 *
 *     p_payload::text ~ '\+?244 ?9[0-9]{8}'   OR   p_payload::text ~ '"\+[0-9]{9,15}"'
 *
 * Este módulo repete os dois padrões, **com a mesma semântica e pela mesma
 * ordem**, e serve dois sítios que o SQL não cobre:
 *
 * 1. **O publicador, antes de pôr o envelope na fila.** Um `INSERT` directo no
 *    `events_outbox` — por `kamba_batch`, por uma migração, por um *replay*
 *    operacional — não passa por `evt_emitir`. O publicador é o último ponto
 *    antes de o envelope sair da base, e falha fechada.
 * 2. **O produtor, antes de chamar a base**, quando quiser recusar mais cedo.
 *
 * Não é o *lint* de nomes de campo do §7.3 — esse corre sobre os **schemas** de
 * evento e é o KAM-007. E não é uma defesa completa: apanha telefones
 * **explícitos**, como o próprio §6.1 diz. A defesa principal é o schema
 * fechado (`additionalProperties: false`) e o nome de campo proibido.
 *
 * **Paridade com o SQL.** Há um teste no gate 8
 * (`db/tests/test_eventos_schema.TestParidadeDoGuardaDePii`) que corre as mesmas
 * cadeias contra o PostgreSQL e contra este módulo e exige o mesmo veredicto em
 * todas. Duas implementações do mesmo predicado só se mantêm honestas se
 * houver uma máquina a confrontá-las.
 */

/**
 * Número móvel angolano, com ou sem indicativo e com ou sem espaço.
 *
 * É `\+?244 ?9[0-9]{8}` tal e qual. Sem âncoras: procura em qualquer posição,
 * como o `~` do PostgreSQL. Sem fronteira de palavra, também como o SQL — o que
 * quer dizer que `12449123456789` dá positivo. É um falso positivo possível, e
 * é o lado certo para errar.
 */
export const TELEFONE_AO = /\+?244 ?9[0-9]{8}/;

/**
 * Qualquer número em formato E.164 **entre aspas** — isto é, um valor de string
 * JSON que é só um número internacional.
 *
 * É `"\+[0-9]{9,15}"` tal e qual: as aspas fazem parte do padrão, e é por isso
 * que o predicado se aplica ao **texto** do JSON e não aos valores já
 * desserializados. Sem as aspas, um `"referencia": "+244..."` de um facilitador
 * passava.
 */
export const E164_ENTRE_ASPAS = /"\+[0-9]{9,15}"/;

/** Os dois padrões, pela ordem em que o `evt_emitir` os avalia. */
export const PADROES_DE_TELEFONE = [TELEFONE_AO, E164_ENTRE_ASPAS] as const;

/** Um valor com padrão de telefone chegou onde não devia. */
export class PadraoDeTelefoneError extends Error {
  /** Qual dos dois padrões disparou. Nunca o valor: ele é PII P2. */
  readonly padrao: string;

  constructor(onde: string, padrao: RegExp) {
    super(
      `${onde} contem padrao de telefone (PII P2): o valor nao e registado. ` +
        "So contact_id entra em eventos (ADR-010)",
    );
    this.name = "PadraoDeTelefoneError";
    this.padrao = padrao.source;
  }
}

/**
 * O texto contém um padrão de telefone?
 *
 * Recebe **texto**: quem tiver um objecto passa-lhe `JSON.stringify`, que é o
 * equivalente do `::text` do SQL. Devolve o padrão que disparou, ou `null`.
 */
export function padraoDeTelefoneEm(texto: string): RegExp | null {
  for (const padrao of PADROES_DE_TELEFONE) {
    if (padrao.test(texto)) return padrao;
  }
  return null;
}

/**
 * Recusa um valor com padrão de telefone.
 *
 * `onde` é um rótulo para a mensagem (`payload`, `envelope`), nunca o valor:
 * a mensagem de erro vai para o *logger*, e o DoD proíbe telefone em *logs*.
 */
export function exigirSemTelefone(valor: unknown, onde: string): void {
  const texto = typeof valor === "string" ? valor : JSON.stringify(valor) ?? "";
  const padrao = padraoDeTelefoneEm(texto);
  if (padrao !== null) throw new PadraoDeTelefoneError(onde, padrao);
}
