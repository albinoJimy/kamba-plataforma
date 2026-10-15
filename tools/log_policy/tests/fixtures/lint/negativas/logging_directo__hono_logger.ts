// Negativa: o middleware do Hono escreve cada pedido na consola, com o caminho
// e a *query string* — que é onde vem o telefone de um `?telefone=…`.
import { Hono } from "hono";
import { logger } from "hono/logger";

export const app = new Hono();
app.use(logger());
