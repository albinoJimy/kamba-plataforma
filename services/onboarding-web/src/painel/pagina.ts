/**
 * As páginas do painel do dono (KAM-099). Móvel primeiro, sem scripts de
 * terceiros, em português de Angola.
 *
 * ## Tudo o que vem de fora passa pelo `escapar`
 *
 * O nome de um produto é escrito pelo dono — ou pelo catálogo por foto do
 * KAM-049 — e é texto livre: um `<script>` no nome era código a correr na
 * sessão do dono. Cada valor interpolado vai pelo `escapar`, incluindo os que
 * hoje têm alfabeto fechado (o `sku` e a versão): a segurança não pode depender
 * de um alfabeto que outro ticket alarga.
 *
 * ## O guião é literal, e o único
 *
 * A página dos produtos leva um guião com o `nonce` da CSP, e é o único. Não
 * interpola nada: lê o `sku` e a versão de atributos `data-` (escapados) e
 * manda o `PATCH` com `fetch`. A CSP é a do registo (`../pagina.ts`):
 * `default-src 'none'`, `connect-src 'self'`.
 *
 * ## Confirmação antes de gravar (critério 2)
 *
 * O guião pede `confirm()` com o valor novo **antes** do primeiro `PATCH`. Se o
 * servidor responder que a variação passa de 50% (critério 5), pede uma segunda
 * confirmação e reenvia com `confirmar_variacao` — e com **outra** chave de
 * idempotência, porque é outro pedido.
 *
 * ## As datas são de Luanda (KAM-190)
 *
 * O `criadoAt` vem em UTC; a página mostra o dia de `Africa/Luanda` (§2), que é
 * o mesmo dia por que o filtro procura. Mostrar o dia UTC punha uma encomenda
 * das 23h30 de Luanda no dia seguinte da lista e no dia certo do filtro.
 */

import type { CanalDoDono } from "@kamba/core-ts/dono";

import { cabecalhos } from "../pagina.ts";
import type { VistaDoCanal } from "./canal.ts";
import {
  ESTADOS_COM_CONTACTO,
  ESTADOS_DA_ENCOMENDA,
  type ContactoDaEncomenda,
  type Encomenda,
  type Oferta,
} from "./comercio.ts";

export { cabecalhos };

export function escapar(texto: string): string {
  return texto
    .replace(/&/g, "&amp;")
    .replace(/</g, "&lt;")
    .replace(/>/g, "&gt;")
    .replace(/"/g, "&quot;")
    .replace(/'/g, "&#39;");
}

/** Um valor em unidade menor como «12 500 Kz». Sem vírgula flutuante. */
export function kz(minor: bigint): string {
  const negativo = minor < 0n;
  const inteiro = (negativo ? -minor : minor) / 100n;
  const centimos = (negativo ? -minor : minor) % 100n;
  const milhares = inteiro.toString().replace(/\B(?=(\d{3})+(?!\d))/g, " ");
  const resto = centimos === 0n ? "" : `,${centimos.toString().padStart(2, "0")}`;
  return `${negativo ? "-" : ""}${milhares}${resto} Kz`;
}

/** O preço como o dono o lê, com o modo. */
export function precoLegivel(o: Pick<Oferta, "precoTipo" | "precoMinor">): string {
  if (o.precoTipo === "sob_consulta" || o.precoMinor === null) return "preço sob consulta";
  return o.precoTipo === "a_partir_de" ? `a partir de ${kz(o.precoMinor)}` : kz(o.precoMinor);
}

const NOMES_DOS_ESTADOS: Readonly<Record<string, string>> = {
  criada: "Criada",
  aguarda_pagamento: "À espera de pagamento",
  pendente_confirmacao: "Por confirmar",
  paga: "Paga",
  expirada: "Expirada",
  em_entrega: "Em entrega",
  entrega_falhada: "Entrega falhada",
  entregue: "Entregue",
  em_disputa: "Em disputa",
  reembolso_pendente: "Reembolso pendente",
  reembolsada: "Reembolsada",
  cancelada: "Cancelada",
};

/** O dia de `Africa/Luanda` (UTC+1, sem hora de Verão) de um instante UTC. */
export function diaEmLuanda(iso: string): string {
  const ms = Date.parse(iso);
  return Number.isFinite(ms) ? new Date(ms + 3_600_000).toISOString().slice(0, 10) : iso.slice(0, 10);
}

/**
 * O texto de cada código público de T&S (dicionário §3.68). O código é o que o
 * COM devolve; o dono lê a frase. Um código fora da lista sai tal e qual,
 * escapado: é melhor do que esconder um aviso. Os dois de recurso não estão: o
 * `emVigor` do KAM-097 tira as linhas de recurso dos avisos, e não chegam aqui.
 */
const TEXTOS_DOS_AVISOS: Readonly<Record<string, string>> = {
  conduta_em_analise: "A actividade da loja está em análise.",
  actividade_limitada: "A actividade da loja está limitada.",
  loja_suspensa: "A loja está suspensa.",
  loja_encerrada: "A loja foi encerrada.",
};

const NOMES_DO_CANAL: Readonly<Record<string, string>> = {
  ativo: "Activo",
  a_sincronizar: "A sincronizar",
  desligado: "Desligado",
  sem_canal: "Ainda sem número de WhatsApp ligado",
};

function estilo(nonce: string): string {
  return `<style nonce="${escapar(nonce)}">
body{font-family:system-ui,sans-serif;margin:0;padding:0 12px 24px;max-width:640px;margin-inline:auto;color:#1a1a1a;background:#fff}
nav{display:flex;gap:12px;flex-wrap:wrap;padding:12px 0;border-bottom:1px solid #ddd}
nav a{color:#0b5;font-weight:600;text-decoration:none}
.cartao{border:1px solid #ddd;border-radius:8px;padding:12px;margin:12px 0}
label{display:block;margin-top:8px}
input,select,button{font-size:16px;padding:6px;max-width:100%}
.aviso{color:#a40}
table{width:100%;border-collapse:collapse}
td,th{text-align:left;padding:6px 4px;border-bottom:1px solid #eee}
</style>`;
}

function moldura(nonce: string, titulo: string, corpo: string, guiao = ""): string {
  return `<!doctype html>
<html lang="pt-AO"><head><meta charset="utf-8">
<meta name="viewport" content="width=device-width,initial-scale=1">
<title>${escapar(titulo)} — KAMBÁ</title>${estilo(nonce)}</head>
<body><nav><a href="/painel/produtos">Produtos</a><a href="/painel/encomendas">Encomendas</a><a href="/painel/canal">Canal</a>
<form method="post" action="/painel/sair"><button type="submit">Sair</button></form></nav>
<h1>${escapar(titulo)}</h1>
${corpo}${guiao}</body></html>`;
}

/**
 * O guião da página dos produtos. **Literal**: sem crases e sem interpolação,
 * pela razão da nota do módulo e pela do `node --test` (uma crase dentro de um
 * *template literal* parte o ficheiro em modo *strip-only*).
 */
const GUIAO_DOS_PRODUTOS = [
  "document.querySelectorAll('form.oferta').forEach(function (f) {",
  "  f.addEventListener('submit', async function (ev) {",
  "    ev.preventDefault();",
  "    var saida = f.querySelector('.saida');",
  "    var tipo = f.elements.preco_tipo.value;",
  "    var corpo = { preco_tipo: tipo, versao: f.dataset.versao };",
  "    var kz = f.elements.preco_kz.value.trim();",
  "    if (tipo === f.dataset.tipo && kz === f.dataset.kz) { saida.textContent = 'Sem alteracoes.'; return; }",
  "    if (tipo !== 'sob_consulta') {",
  "      if (!/^[0-9]+$/.test(kz)) { saida.textContent = 'Escreva o preco em Kz, so com algarismos.'; return; }",
  "      corpo.preco_minor = kz.replace(/^0+(?=.)/, '') + '00';",
  "    }",
  "    var resumo = tipo === 'sob_consulta' ? 'preco sob consulta' : kz + ' Kz';",
  "    if (!window.confirm('Gravar ' + resumo + '?')) return;",
  "    async function enviar(c) {",
  "      return fetch('/painel/produtos/' + encodeURIComponent(f.dataset.sku), {",
  "        method: 'PATCH', credentials: 'same-origin',",
  "        headers: { 'content-type': 'application/json', 'idempotency-key': crypto.randomUUID() },",
  "        body: JSON.stringify(c) });",
  "    }",
  "    var r = await enviar(corpo);",
  "    var j = await r.json().catch(function () { return {}; });",
  "    if (r.status === 422 && j.erro === 'confirmacao') {",
  "      if (!window.confirm('O preco muda mais de 50%. Confirma?')) return;",
  "      corpo.confirmar_variacao = true;",
  "      r = await enviar(corpo);",
  "      j = await r.json().catch(function () { return {}; });",
  "    }",
  "    if (r.ok) { f.dataset.versao = j.versao; saida.textContent = 'Gravado.'; return; }",
  "    if (r.status === 409) { saida.textContent = 'Outra alteracao chegou primeiro. Recarregue a pagina.'; return; }",
  "    if (r.status === 401) { saida.textContent = 'A sessao terminou. Entre outra vez.'; return; }",
  "    saida.textContent = 'Nao foi possivel gravar (' + (j.erro || r.status) + ').';",
  "  });",
  "});",
].join("\n");

function opcoesDoModo(actual: string): string {
  const nomes: Record<string, string> = { fixo: "Preço fixo", a_partir_de: "A partir de", sob_consulta: "Sob consulta" };
  return Object.entries(nomes)
    .map(([v, n]) => `<option value="${v}"${v === actual ? " selected" : ""}>${n}</option>`)
    .join("");
}

function stockLegivel(o: Oferta): string {
  return o.stockQuantidade === null
    ? `stock ${escapar(o.stockModo)}, sem quantidade declarada`
    : `${o.stockQuantidade} em stock (${o.stockReservada} reservadas)`;
}

/**
 * A lista de produtos (critério 2 do KAM-099), **sem formulários e sem guião**
 * (KAM-206).
 *
 * O KAM-190 mediu esta página em 3G simulado com 200 produtos e um formulário
 * por produto: 1,7 a 4,5 s até o DOM estar pronto, e o peso era de CPU e não de
 * rede (com gzip não melhorava). Uma linha de tabela por produto, com a ligação
 * para a página dele, é o que o telemóvel desenha sem montar 600 controlos; o
 * formulário e o guião vivem na página de **um** produto (`paginaDoProduto`).
 */
export function paginaDeProdutos(nonce: string, ofertas: readonly Oferta[], truncada: boolean): string {
  const linhas = ofertas
    .map(
      (o) =>
        `<tr><td><a href="/painel/produtos/${escapar(encodeURIComponent(o.sku))}">${escapar(o.nome)}</a></td><td>${escapar(precoLegivel(o))}</td><td>${stockLegivel(o)}</td></tr>`,
    )
    .join("\n");
  const tabela =
    ofertas.length === 0
      ? "<p>Ainda não há produtos no catálogo.</p>"
      : `<table><thead><tr><th>Produto</th><th>Preço</th><th>Stock</th></tr></thead><tbody>${linhas}</tbody></table>`;
  const aviso = truncada ? '<p class="aviso">A lista mostra os primeiros 200 produtos.</p>' : "";
  return moldura(nonce, "Produtos", `${aviso}${tabela}`);
}

/** Um produto, com o formulário do preço (critério 2 do KAM-099; KAM-206). */
export function paginaDoProduto(nonce: string, o: Oferta): string {
  // **Um preço com cêntimos não se pré-preenche.** O campo é em Kz inteiros
  // (critério 5), e pôr lá o valor arredondado fazia uma gravação qualquer
  // cortar os cêntimos sem o dono ver. Fica vazio, e o preço exacto está no
  // texto ao lado. Achado da revisão adversarial.
  const kzActual = o.precoMinor === null || o.precoMinor % 100n !== 0n ? "" : (o.precoMinor / 100n).toString();
  const formulario = `<form class="oferta cartao" data-sku="${escapar(o.sku)}" data-versao="${escapar(o.versao)}" data-tipo="${escapar(o.precoTipo)}" data-kz="${escapar(kzActual)}">
<p>${escapar(precoLegivel(o))} · ${stockLegivel(o)}</p>
<label>Modo do preço <select name="preco_tipo">${opcoesDoModo(o.precoTipo)}</select></label>
<label>Preço em Kz <input name="preco_kz" inputmode="numeric" pattern="[0-9]*" value="${escapar(kzActual)}"></label>
<button type="submit">Gravar</button> <span class="saida" role="status"></span></form>
<p><a href="/painel/produtos">Voltar aos produtos</a></p>`;
  return moldura(nonce, o.nome, formulario, `<script nonce="${escapar(nonce)}">${GUIAO_DOS_PRODUTOS}</script>`);
}

/** Os filtros da lista de encomendas, já validados. */
export interface FiltroDasEncomendas {
  readonly estado: string;
  readonly desde: string | null;
  readonly ate: string | null;
}

/** A lista de encomendas, só leitura (critério 6). Nenhum telefone. */
export function paginaDeEncomendas(
  nonce: string,
  f: FiltroDasEncomendas,
  itens: readonly Encomenda[],
  proximo: string | null = null,
): string {
  const opcoes = ESTADOS_DA_ENCOMENDA.map(
    (e) => `<option value="${e}"${e === f.estado ? " selected" : ""}>${escapar(NOMES_DOS_ESTADOS[e] ?? e)}</option>`,
  ).join("");
  const filtro = `<form method="get" action="/painel/encomendas" class="cartao">
<label>Estado <select name="estado">${opcoes}</select></label>
<label>Desde <input type="date" name="desde" value="${escapar(f.desde ?? "")}"></label>
<label>Até <input type="date" name="ate" value="${escapar(f.ate ?? "")}"></label>
<button type="submit">Filtrar</button></form>`;
  const linhas = itens
    .map(
      (e) => `<tr><td><a href="/painel/encomendas/${encodeURIComponent(e.orderId)}">${escapar(e.numeroPublico)}</a></td>
<td>${escapar(NOMES_DOS_ESTADOS[e.estado] ?? e.estado)}</td><td>${escapar(kz(e.totalMinor))}</td><td>${escapar(diaEmLuanda(e.criadoAt))}</td></tr>`,
    )
    .join("\n");
  const tabela =
    itens.length === 0
      ? "<p>Não há encomendas com este filtro.</p>"
      : `<table><thead><tr><th>Referência</th><th>Estado</th><th>Valor</th><th>Data</th></tr></thead><tbody>${linhas}</tbody></table>`;
  // A página seguinte leva o **mesmo** filtro: o COM prende o intervalo ao
  // cursor, e um cursor com outro intervalo é recusado (KAM-190).
  const consulta = new URLSearchParams({ estado: f.estado });
  if (f.desde !== null) consulta.set("desde", f.desde);
  if (f.ate !== null) consulta.set("ate", f.ate);
  if (proximo !== null) consulta.set("cursor", proximo);
  const seguinte = proximo === null ? "" : `<p><a href="/painel/encomendas?${escapar(consulta.toString())}">Mais antigas</a></p>`;
  return moldura(nonce, "Encomendas", `${filtro}${tabela}${seguinte}`);
}

/**
 * Uma encomenda. **O contacto não vem por omissão** (KAM-206): nos estados em
 * que o dono age, a página tem o botão que o pede, e só a resposta a esse pedido
 * — auditada no COM — traz o telefone, mascarado. O `contactId` nunca aparece.
 */
export function paginaDaEncomenda(
  nonce: string,
  e: Encomenda,
  contacto: ContactoDaEncomenda | null = null,
): string {
  const dados = `<div class="cartao"><p>Estado: ${escapar(NOMES_DOS_ESTADOS[e.estado] ?? e.estado)}</p>
<p>Valor: ${escapar(kz(e.totalMinor))}</p><p>Data: ${escapar(diaEmLuanda(e.criadoAt))}</p></div>`;
  let parteDoContacto = "";
  if (contacto !== null) {
    parteDoContacto =
      contacto.telefoneMascarado === null
        ? '<div class="cartao"><p>Esta encomenda não tem telefone do cliente para mostrar.</p></div>'
        : `<div class="cartao"><p>Telefone do cliente: <strong data-contacto>${escapar(contacto.telefoneMascarado)}</strong></p>
<p>Mostramos só os últimos três algarismos. Responda ao cliente pela conversa da loja.</p></div>`;
  } else if (ESTADOS_COM_CONTACTO.includes(e.estado)) {
    parteDoContacto = `<form method="post" action="/painel/encomendas/${escapar(encodeURIComponent(e.orderId))}/contacto" class="cartao">
<p>Precisa de reconhecer o cliente? O pedido fica registado.</p><button type="submit">Ver o contacto do cliente</button></form>`;
  }
  return moldura(nonce, `Encomenda ${e.numeroPublico}`, `${dados}${parteDoContacto}`);
}

/** O canal do dono por omissão: o painel, que funciona sempre (KAM-216). */
const PAINEL_DO_DONO: CanalDoDono = { owner_channel_wa: false, canal: "painel" };

/**
 * Onde o dono fala com o Assistente do Dono (KAM-216). **Literal e sem número**:
 * a página diz o canal, e não mostra o telefone da loja nem o do dono.
 */
const TEXTOS_DO_CANAL_DO_DONO: Readonly<Record<CanalDoDono["canal"], string>> = {
  whatsapp: "Fale com o assistente da loja pelo WhatsApp: escreva do seu telemóvel para o número da loja.",
  painel: "Fale com o assistente da loja aqui no painel.",
};

/**
 * O estado do canal (critério 7), e o canal do dono (KAM-216).
 *
 * **A ligação de reconexão é o `/painel/ligar`** (KAM-190), e não o `/ligar` do
 * KAM-093: este exige a sessão do registo, de 24 h, e um dono que só tinha a do
 * painel recebia 403. A rota do painel cunha a do registo e reencaminha.
 */
export function paginaDoCanal(nonce: string, v: VistaDoCanal, dono: CanalDoDono = PAINEL_DO_DONO): string {
  const religar =
    (v.estado === "desligado" || v.estado === "sem_canal") && !v.restrito
      ? '<p><a href="/painel/ligar">Ligar o número de WhatsApp</a></p>'
      : "";
  const avisos =
    v.avisos.length === 0
      ? "<p>Sem avisos em vigor.</p>"
      : `<ul>${v.avisos.map((a) => `<li class="aviso">${escapar(TEXTOS_DOS_AVISOS[a] ?? a)}</li>`).join("")}</ul>`;
  const restrito = !v.restrito
    ? ""
    : v.estado === "desligado"
      ? '<p class="aviso">O número está suspenso. Não o volte a ligar sem falar com a equipa KAMBÁ.</p>'
      : '<p class="aviso">O número está ligado, mas com envio limitado.</p>';
  return moldura(
    nonce,
    "Canal",
    `<div class="cartao"><p>Estado: ${escapar(NOMES_DO_CANAL[v.estado] ?? v.estado)}</p>${restrito}
<p>Qualidade do número: ${escapar(v.qualidade ?? "—")}</p>
<p>Escalão de conversas: ${escapar(v.escalao ?? "—")}</p>
<p>Nível de confiança: ${v.nivel === null ? "—" : escapar(String(v.nivel))}</p>
<p>Tecto por pedido: ${v.tectoPedidoMinor === null ? "—" : escapar(kz(v.tectoPedidoMinor))}</p>
<p data-canal-do-dono="${dono.canal}">${TEXTOS_DO_CANAL_DO_DONO[dono.canal]}</p>${religar}</div>
<h2>Avisos</h2>${avisos}`,
  );
}

/**
 * O guião da reentrada (KAM-190). **Literal**, pela razão do dos produtos: pede
 * o código, confere-o, e vai para os produtos. Não guarda nada no navegador além
 * do bilhete numa variável, que morre com a página.
 */
const GUIAO_DA_REENTRADA = [
  "var bilhete = null;",
  "var saida = document.getElementById('saida');",
  "async function enviar(rota, corpo) {",
  "  var r = await fetch(rota, { method: 'POST', credentials: 'same-origin',",
  "    headers: { 'content-type': 'application/json' }, body: JSON.stringify(corpo) });",
  "  var j = await r.json().catch(function () { return {}; });",
  "  return { r: r, j: j };",
  "}",
  "document.getElementById('pedir').addEventListener('submit', async function (ev) {",
  "  ev.preventDefault();",
  "  var x = await enviar('/painel/codigo', { telefone: ev.target.elements.telefone.value });",
  "  if (x.r.status === 429) { saida.textContent = 'Muitos pedidos desta rede. Tente daqui a uma hora.'; return; }",
  "  if (!x.r.ok) { saida.textContent = 'Verifique o numero de telefone.'; return; }",
  "  bilhete = x.j.referencia;",
  "  document.getElementById('conferir').hidden = false;",
  "  saida.textContent = 'Se o numero tiver painel, recebe um codigo por SMS.';",
  "});",
  "document.getElementById('conferir').addEventListener('submit', async function (ev) {",
  "  ev.preventDefault();",
  "  var x = await enviar('/painel/verificar', { referencia: bilhete, codigo: ev.target.elements.codigo.value });",
  "  if (x.r.ok) { window.location.assign('/painel/produtos'); return; }",
  "  saida.textContent = 'O codigo nao serve. Peca outro.';",
  "});",
].join("\n");

/**
 * A página de quem não tem sessão. Não diz se a sessão existiu.
 *
 * **Com a reentrada** (KAM-190): o telefone, e o código que chega por SMS. Não
 * depende da sessão do registo — ver a nota do `./rotas.ts`.
 */
export function paginaSemSessao(nonce: string): string {
  return `<!doctype html><html lang="pt-AO"><head><meta charset="utf-8">
<meta name="viewport" content="width=device-width,initial-scale=1"><title>Entrar — KAMBÁ</title>${estilo(nonce)}</head>
<body><h1>Entrar no painel</h1><p>A sua sessão terminou ou não existe. Entre outra vez com o código que recebe por SMS.</p>
<form id="pedir" class="cartao"><label>Telefone <input name="telefone" type="tel" inputmode="tel" autocomplete="tel" required></label>
<button type="submit">Receber código</button></form>
<form id="conferir" class="cartao" hidden><label>Código <input name="codigo" inputmode="numeric" pattern="[0-9]*" autocomplete="one-time-code" required></label>
<button type="submit">Entrar</button></form>
<p id="saida" role="status"></p>
<script nonce="${escapar(nonce)}">${GUIAO_DA_REENTRADA}</script></body></html>`;
}

/**
 * O guião do código da ligação (KAM-190). Literal, pela razão do dos produtos.
 * O bilhete vem num atributo `data-` (escapado), e o código certo leva ao
 * `/ligar` do KAM-093.
 */
const GUIAO_DA_LIGACAO = [
  "var f = document.getElementById('conferir');",
  "var saida = document.getElementById('saida');",
  "f.addEventListener('submit', async function (ev) {",
  "  ev.preventDefault();",
  "  var r = await fetch('/painel/verificar', { method: 'POST', credentials: 'same-origin',",
  "    headers: { 'content-type': 'application/json' },",
  "    body: JSON.stringify({ referencia: f.dataset.bilhete, codigo: f.elements.codigo.value, destino: 'ligar' }) });",
  "  var j = await r.json().catch(function () { return {}; });",
  "  if (r.ok && j.seguinte === '/ligar') { window.location.assign('/ligar'); return; }",
  "  saida.textContent = r.status === 429 ? 'Muitas tentativas desta rede. Tente daqui a uma hora.' : 'O codigo nao serve. Recarregue a pagina para receber outro.';",
  "});",
].join("\n");

/**
 * O passo do código antes da ligação (KAM-190). O código foi mandado ao telefone
 * registado no onboarding; a página não diz qual é.
 */
export function paginaDoCodigoDaLigacao(nonce: string, bilhete: string): string {
  return moldura(
    nonce,
    "Ligar o número",
    `<p>Mandámos um código por SMS para o telefone com que se registou. Escreva-o para continuar.</p>
<form id="conferir" class="cartao" data-bilhete="${escapar(bilhete)}"><label>Código <input name="codigo" inputmode="numeric" pattern="[0-9]*" autocomplete="one-time-code" required></label>
<button type="submit">Continuar</button></form><p id="saida" role="status"></p>`,
    `<script nonce="${escapar(nonce)}">${GUIAO_DA_LIGACAO}</script>`,
  );
}

/**
 * A ligação fechada: o caso já não está no passo do ES, que é o único em que o
 * `/ligar` do KAM-093 abre. **Não manda SMS nem mostra o formulário.**
 */
export function paginaDaLigacaoFechada(nonce: string): string {
  return moldura(
    nonce,
    "Ligar o número",
    "<p>O passo de ligação do número não está disponível para a sua loja neste momento. Contacte a equipa KAMBÁ.</p>",
  );
}

/** A página de um recurso que não existe — ou que não é deste dono. A mesma. */
export function paginaNaoEncontrada(nonce: string): string {
  return moldura(nonce, "Não encontrado", "<p>Não encontrámos o que procura.</p>");
}
