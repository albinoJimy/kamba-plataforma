/**
 * O canal do dono (KAM-118): persona, canal, proactivas, troca de telefone e o
 * dono que nasce do provisionamento.
 *
 * O que corre no AGR — as acções sensíveis com botão, o bloqueio de 24 h depois
 * de uma troca e o tecto de mensagens por hora — está em `kamba_agr/dono/`.
 */

export * from "./contrato.ts";
export * from "./persona.ts";
export * from "./proactivas.ts";
export * from "./provisionamento.ts";
export * from "./troca.ts";
export * from "./sql.ts";
export * from "./conversa.ts";
export * from "./conversa_sql.ts";
