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
 */

import { cabecalhos } from "../pagina.ts";
import type { VistaDoCanal } from "./canal.ts";
import { ESTADOS_DA_ENCOMENDA, type Encomenda, type Oferta } from "./comercio.ts";

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
  "    if (tipo !== 'sob_consulta') {",
  "      if (!/^[0-9]+$/.test(kz)) { saida.textContent = 'Escreva o preco em Kz, so com algarismos.'; return; }",
  "      corpo.preco_minor = kz.replace(/^0+(?=.)/, '') + '00';",
  "    }",
  "    var stock = f.elements.stock.value.trim();",
  "    if (stock !== '') corpo.stock = Number(stock);",
  "    var resumo = tipo === 'sob_consulta' ? 'preco sob consulta' : kz + ' Kz';",
  "    if (!window.confirm('Gravar ' + resumo + (stock !== '' ? ' e stock ' + stock : '') + '?')) return;",
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

/** A lista de produtos, com o formulário de cada um (critério 2). */
export function paginaDeProdutos(nonce: string, ofertas: readonly Oferta[], truncada: boolean): string {
  const cartoes = ofertas
    .map((o) => {
      const kzActual = o.precoMinor === null ? "" : (o.precoMinor / 100n).toString();
      const stock =
        o.stockQuantidade === null
          ? `stock ${escapar(o.stockModo)}, sem quantidade declarada`
          : `${o.stockQuantidade} em stock (${o.stockReservada} reservadas)`;
      return `<form class="oferta cartao" data-sku="${escapar(o.sku)}" data-versao="${escapar(o.versao)}">
<h2>${escapar(o.nome)}</h2><p>${escapar(precoLegivel(o))} · ${stock}</p>
<label>Modo do preço <select name="preco_tipo">${opcoesDoModo(o.precoTipo)}</select></label>
<label>Preço em Kz <input name="preco_kz" inputmode="numeric" pattern="[0-9]*" value="${escapar(kzActual)}"></label>
<label>Stock <input name="stock" inputmode="numeric" pattern="[0-9]*" placeholder="sem alteração"></label>
<button type="submit">Gravar</button> <span class="saida" role="status"></span></form>`;
    })
    .join("\n");
  const vazia = ofertas.length === 0 ? "<p>Ainda não há produtos no catálogo.</p>" : "";
  const aviso = truncada ? '<p class="aviso">A lista mostra os primeiros 200 produtos.</p>' : "";
  return moldura(nonce, "Produtos", `${aviso}${vazia}${cartoes}`, `<script nonce="${escapar(nonce)}">${GUIAO_DOS_PRODUTOS}</script>`);
}

/** Os filtros da lista de encomendas, já validados. */
export interface FiltroDasEncomendas {
  readonly estado: string;
  readonly desde: string | null;
  readonly ate: string | null;
}

/** A lista de encomendas, só leitura (critério 6). Nenhum telefone. */
export function paginaDeEncomendas(nonce: string, f: FiltroDasEncomendas, itens: readonly Encomenda[]): string {
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
<td>${escapar(NOMES_DOS_ESTADOS[e.estado] ?? e.estado)}</td><td>${escapar(kz(e.totalMinor))}</td><td>${escapar(e.criadoAt.slice(0, 10))}</td></tr>`,
    )
    .join("\n");
  const tabela =
    itens.length === 0
      ? "<p>Não há encomendas com este filtro.</p>"
      : `<table><thead><tr><th>Referência</th><th>Estado</th><th>Valor</th><th>Data</th></tr></thead><tbody>${linhas}</tbody></table>`;
  return moldura(nonce, "Encomendas", `${filtro}${tabela}`);
}

/** Uma encomenda. O contacto **não** aparece: ver a verificação do bloco. */
export function paginaDaEncomenda(nonce: string, e: Encomenda): string {
  return moldura(
    nonce,
    `Encomenda ${e.numeroPublico}`,
    `<div class="cartao"><p>Estado: ${escapar(NOMES_DOS_ESTADOS[e.estado] ?? e.estado)}</p>
<p>Valor: ${escapar(kz(e.totalMinor))}</p><p>Data: ${escapar(e.criadoAt.slice(0, 10))}</p></div>`,
  );
}

/** O estado do canal (critério 7). */
export function paginaDoCanal(nonce: string, v: VistaDoCanal): string {
  const religar =
    v.estado === "desligado" || v.estado === "sem_canal"
      ? '<p><a href="/ligar">Ligar o número de WhatsApp</a></p>'
      : "";
  const avisos =
    v.avisos.length === 0
      ? "<p>Sem avisos em vigor.</p>"
      : `<ul>${v.avisos.map((a) => `<li class="aviso">${escapar(a)}</li>`).join("")}</ul>`;
  return moldura(
    nonce,
    "Canal",
    `<div class="cartao"><p>Estado: ${escapar(NOMES_DO_CANAL[v.estado] ?? v.estado)}</p>
<p>Nível de confiança: ${escapar(v.nivel ?? "—")}</p>
<p>Tecto diário de conversas: ${v.tecto === null ? "—" : escapar(String(v.tecto))}</p>${religar}</div>
<h2>Avisos</h2>${avisos}`,
  );
}

/** A página de quem não tem sessão. Não diz se a sessão existiu. */
export function paginaSemSessao(nonce: string): string {
  return `<!doctype html><html lang="pt-AO"><head><meta charset="utf-8">
<meta name="viewport" content="width=device-width,initial-scale=1"><title>Entrar — KAMBÁ</title>${estilo(nonce)}</head>
<body><h1>Entrar no painel</h1><p>A sua sessão terminou ou não existe. Entre outra vez com o código que recebe por SMS.</p></body></html>`;
}

/** A página de um recurso que não existe — ou que não é deste dono. A mesma. */
export function paginaNaoEncontrada(nonce: string): string {
  return moldura(nonce, "Não encontrado", "<p>Não encontrámos o que procura.</p>");
}
