/**
 * O vocabulário do canal do dono (KAM-118), do lado TypeScript.
 *
 * Os nomes são os do dicionário §3.7: `contacts.papel` ∈ {`cliente`, `dono`} e a
 * persona `dono` (Assistente do Dono). A persona **não é uma vertical**: o
 * `tenant_channels.vertical` continua `vendedor` ou `servicos`, e o que decide a
 * persona é o papel de quem escreve (dicionário §3.2, linha «Vertical»).
 *
 * As acções sensíveis (`owner_actions`), o bloqueio depois da troca de telefone
 * e o tecto de mensagens por hora vivem no AGR (`kamba_agr/dono/`), porque é lá
 * que as tools correm e que o botão é lido. Aqui fica o que o CHR, o painel e a
 * política de proactivas precisam.
 *
 * ## Os limiares são *proposta*
 *
 * Os números abaixo vêm do bloco do KAM-118, que os escreve como *proposta*, e
 * ficam nomeados para se calibrarem num sítio só no fim do Piloto (Critérios de
 * Saída do EPIC-11).
 */

/** O papel de um contacto. É o `CHECK` de `contacts.papel` (revisão do KAM-118). */
export const PAPEIS = ["cliente", "dono"] as const;
export type Papel = (typeof PAPEIS)[number];

/**
 * A persona com que o AGR trata o turno.
 *
 * `cliente` é a persona da vertical do canal (Vendedor ou Rececionista); `dono`
 * é o Assistente do Dono. É a mesma lista que a dos papéis, e não por acaso: a
 * persona é função do papel e de mais nada.
 */
export const PERSONAS = PAPEIS;
export type Persona = Papel;

/** O papel com que um contacto nasce. É a omissão da coluna. */
export const PAPEL_POR_OMISSAO: Papel = "cliente";

/** Tecto de *push* ao dono por semana. ***Proposta***: 1. */
export const PUSH_POR_SEMANA = 1;

/** Tecto de *push* ao dono por mês. ***Proposta***: 4. */
export const PUSH_POR_MES = 4;
