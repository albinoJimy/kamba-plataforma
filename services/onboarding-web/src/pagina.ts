/**
 * O ecrã de registo: HTML, CSP estrita e o cliente da prova de trabalho
 * (KAM-086, critérios 3 e 7).
 *
 * ## Sem um único pedido a terceiros, e é verificável por leitura
 *
 * Não há `<script src>`, não há `<link>` para tipos de letra, não há imagem
 * remota. A folha de estilo e o guião vão **em linha**, com `nonce`, e a CSP diz
 * `default-src 'none'`. Três razões, e nenhuma é gosto: o bloco exige «CSP
 * estrita, sem scripts de terceiros»; um `<script>` de outro domínio manda o IP
 * e o `User-Agent` de cada dono angolano para fora (**D12**, *a confirmar por
 * parecer*); e a porta de entrada do produto não pode depender de um domínio que
 * pode estar bloqueado em Angola.
 *
 * ## O `nonce` é por resposta, e o guião é o mesmo
 *
 * Um `nonce` fixo não é um `nonce` — valia tanto como `'unsafe-inline'`. Um por
 * resposta é o que faz a CSP recusar um `<script>` injectado. O guião em si é
 * literal e não interpolado: **nada do que o cliente manda volta para dentro
 * dele**, e o único valor que a página leva de fora é o desafio, que vai num
 * atributo `data-` e é lido por `dataset` — nunca colado em código.
 *
 * ## O *honeypot* é escondido por CSS e não por `type="hidden"`
 *
 * Um `hidden` reconhece-se com uma linha de selector. Um campo com `position:
 * absolute` fora do ecrã parece-se, para quem só lê o DOM, com um campo a
 * sério. Leva `tabindex="-1"` e `aria-hidden="true"` para que um dono com leitor
 * de ecrã nunca chegue a ele: um *honeypot* que um leitor de ecrã anuncia é uma
 * armadilha para a pessoa errada, e é também a razão por que há **um** e não
 * três.
 *
 * ## A prova de trabalho corre no cliente, e o servidor não confia nele
 *
 * O guião procura a solução com o mesmo resumo que o
 * `@kamba/core-ts/inscricao` verifica — `sha256(dominio\0desafio\0solucao)`, com
 * os bits à cabeça a zero. Se o cliente mentir, o servidor recusa; se o cliente
 * não correr JavaScript, o registo não avança, e isso é uma limitação **dita**:
 * um dono com JavaScript desligado não se consegue registar sozinho, e o
 * caminho dele é o apoio humano. A alternativa era um CAPTCHA de terceiros, que
 * o critério 7 veda sem D12.
 */

import { DOMINIO_DA_PROVA, NOME_DO_HONEYPOT } from "@kamba/core-ts/inscricao";

import { exigirComunicacaoLimpa } from "./comunicacao.ts";

/** O que a página precisa de saber para se desenhar. */
export interface DadosDaPagina {
  /** O desafio assinado, opaco. Vai num `data-` e volta como vem. */
  readonly desafio: string;
  readonly dificuldade: number;
  /** O `nonce` da CSP desta resposta. Hexadecimais — ver `./rotas.ts`. */
  readonly nonce: string;
  /**
   * A chave de idempotência que esta página vai submeter.
   *
   * **Não é o `nonce`**, e a tentação de reusá-lo é um defeito com duas pontas:
   * a forma de `CHAVE` do `@kamba/core-ts/sms` recusa alguns alfabetos de
   * `nonce`, e um valor que serve de `nonce` de CSP e de chave de idempotência
   * passa a ter dois donos — mudar o alfabeto de um partia o outro.
   */
  readonly chave: string;
  /**
   * O *token* do convite, tal como veio em `?c=`.
   *
   * Volta no **corpo** do `POST` e não num parâmetro de URL, e a página manda
   * `Referrer-Policy: no-referrer` para que ele não saia num `Referer` de
   * nenhum pedido. É uma credencial de capacidade, e o sítio onde ela não pode
   * ficar é um registo de servidor de terceiro.
   */
  readonly token: string;
}

/**
 * A CSP da página.
 *
 * `default-src 'none'` e depois só o que faz falta. O `form-action 'self'`
 * impede que um `<form>` injectado submeta o NIF para fora; o
 * `frame-ancestors 'none'` impede *clickjacking* sobre o botão de registo.
 */
export function csp(nonce: string): string {
  return [
    "default-src 'none'",
    `style-src 'nonce-${nonce}'`,
    `script-src 'nonce-${nonce}'`,
    "connect-src 'self'",
    "form-action 'self'",
    "frame-ancestors 'none'",
    "base-uri 'none'",
  ].join("; ");
}

/**
 * Os cabeçalhos de segurança que acompanham a página.
 *
 * O `Referrer-Policy` é `no-referrer` e não `same-origin`: a ligação de entrada
 * leva o *token* do convite em `?c=`, e um `Referer` com ele para qualquer
 * destino era uma credencial num registo de servidor de terceiro.
 */
export function cabecalhos(nonce: string): Record<string, string> {
  return {
    "Content-Security-Policy": csp(nonce),
    "Referrer-Policy": "no-referrer",
    "X-Content-Type-Options": "nosniff",
    // O registo não é coisa para ficar em cache de intermediário: a página leva
    // um desafio assinado e de uso único por sessão de preenchimento.
    "Cache-Control": "no-store",
  };
}

function escapar(texto: string): string {
  return texto
    .replace(/&/g, "&amp;")
    .replace(/</g, "&lt;")
    .replace(/>/g, "&gt;")
    .replace(/"/g, "&quot;");
}

/**
 * O guião do cliente. **Literal, sem interpolação de nada que venha de fora.**
 *
 * O domínio da prova entra por `JSON.stringify` de uma constante do pacote — não
 * de um valor de pedido —, e é a única coisa que não é texto fixo. Ver a nota do
 * módulo.
 */
function guiao(): string {
  return `
const f = document.getElementById("registo");
const estado = document.getElementById("estado");
const DOMINIO = ${JSON.stringify(DOMINIO_DA_PROVA)};

function bits(octetos) {
  let n = 0;
  for (const o of octetos) {
    if (o === 0) { n += 8; continue; }
    n += Math.clz32(o) - 24;
    break;
  }
  return n;
}

async function resolver(desafio, dificuldade) {
  const cod = new TextEncoder();
  for (let i = 0; i < (1 << 26); i += 1) {
    const texto = DOMINIO + "\\u0000" + desafio + "\\u0000" + String(i);
    const resumo = new Uint8Array(await crypto.subtle.digest("SHA-256", cod.encode(texto)));
    if (bits(resumo) >= dificuldade) return String(i);
    if (i % 2048 === 0) await new Promise((r) => setTimeout(r, 0));
  }
  throw new Error("sem solucao");
}

let referencia = null;

f.addEventListener("submit", async (ev) => {
  ev.preventDefault();
  estado.textContent = "A confirmar que nao e um robot...";
  const desafio = f.dataset.desafio;
  const dificuldade = Number(f.dataset.dificuldade);
  let solucao;
  try {
    solucao = await resolver(desafio, dificuldade);
  } catch {
    estado.textContent = "Nao foi possivel concluir a verificacao. Tente novamente.";
    return;
  }
  const dados = new FormData(f);
  const corpo = {
    token: f.dataset.token,
    nome_negocio: dados.get("nome_negocio"),
    categoria: dados.get("categoria"),
    nif: dados.get("nif"),
    telefone: dados.get("telefone"),
    email: dados.get("email"),
    honeypot: dados.get(${JSON.stringify(NOME_DO_HONEYPOT)}),
    desafio: desafio,
    solucao: solucao,
  };
  const resposta = await fetch("/api/registo", {
    method: "POST",
    headers: { "content-type": "application/json", "idempotency-key": f.dataset.chave },
    body: JSON.stringify(corpo),
  });
  const json = await resposta.json().catch(() => ({}));
  if (!resposta.ok) {
    estado.textContent = "Nao foi possivel concluir o registo. Verifique os dados e tente novamente.";
    return;
  }
  referencia = json.referencia;
  estado.textContent = "Enviamos um codigo por SMS para o telefone indicado.";
  document.getElementById("passo-otp").hidden = false;
  baterCoracao();
});

const g = document.getElementById("otp");
g.addEventListener("submit", async (ev) => {
  ev.preventDefault();
  const resposta = await fetch("/api/otp/verificar", {
    method: "POST",
    headers: { "content-type": "application/json" },
    body: JSON.stringify({ referencia: referencia, codigo: new FormData(g).get("codigo") }),
  });
  const json = await resposta.json().catch(() => ({}));
  estado.textContent = json.veredicto === "acertou"
    ? "Telefone confirmado. Vamos pedir-lhe os documentos."
    : "O codigo nao confere. Tente outra vez.";
});

function baterCoracao() {
  setInterval(() => {
    if (referencia === null) return;
    void fetch("/api/actividade", {
      method: "POST",
      headers: { "content-type": "application/json" },
      body: JSON.stringify({ referencia: referencia }),
    });
  }, 30_000);
}
`.trim();
}

/**
 * A página de registo.
 *
 * Passa pelo `exigirComunicacaoLimpa` **antes** de sair: é a metade do critério
 * 3 que não é código de validação, e falha fechado. Ver `./comunicacao.ts`.
 */
export function paginaDeRegisto(dados: DadosDaPagina): string {
  const html = `<!doctype html>
<html lang="pt">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>KAMBA — registar o seu negocio</title>
<style nonce="${escapar(dados.nonce)}">
body { font-family: system-ui, sans-serif; margin: 0 auto; max-width: 34rem; padding: 1.5rem; line-height: 1.5; }
label { display: block; margin-top: 1rem; font-weight: 600; }
input { width: 100%; padding: 0.5rem; font-size: 1rem; box-sizing: border-box; }
button { margin-top: 1.5rem; padding: 0.75rem 1.25rem; font-size: 1rem; }
.aviso { background: #f6f3e8; border-left: 4px solid #8a6d1f; padding: 0.75rem 1rem; margin: 1rem 0; }
.ardil { position: absolute; left: -9999px; width: 1px; height: 1px; overflow: hidden; }
</style>
</head>
<body>
<h1>Registar o seu negocio na KAMBA</h1>

<p class="aviso">
A KAMBA e para negocios formais ou em formalizacao. O servico <strong>implica NIF e
registo de vendas</strong>: a plataforma guarda os pedidos e os pagamentos num registo
auditavel, e a factura emite-se com software certificado pela AGT. A partilha de dados
com autoridades esta a confirmar por parecer juridico.
</p>

<form id="registo" data-desafio="${escapar(dados.desafio)}" data-dificuldade="${dados.dificuldade}" data-chave="${escapar(dados.chave)}" data-token="${escapar(dados.token)}">
<label for="nome_negocio">Nome do negocio</label>
<input id="nome_negocio" name="nome_negocio" required maxlength="120" autocomplete="organization">

<label for="categoria">O que vende</label>
<input id="categoria" name="categoria" required maxlength="120">

<label for="nif">NIF</label>
<input id="nif" name="nif" required maxlength="32" inputmode="text" autocomplete="off">

<label for="telefone">Telefone do dono (+244)</label>
<input id="telefone" name="telefone" required maxlength="24" inputmode="tel" autocomplete="tel">

<label for="email">E-mail (opcional)</label>
<input id="email" name="email" type="email" maxlength="120" autocomplete="email">

<div class="ardil" aria-hidden="true">
<label for="${NOME_DO_HONEYPOT}">Empresa alternativa</label>
<input id="${NOME_DO_HONEYPOT}" name="${NOME_DO_HONEYPOT}" tabindex="-1" autocomplete="off">
</div>

<button type="submit">Continuar</button>
</form>

<section id="passo-otp" hidden>
<h2>Confirmar o telefone</h2>
<form id="otp">
<label for="codigo">Codigo recebido por SMS</label>
<input id="codigo" name="codigo" required inputmode="numeric" maxlength="8" autocomplete="one-time-code">
<button type="submit">Confirmar</button>
</form>
</section>

<p id="estado" role="status"></p>

<script nonce="${escapar(dados.nonce)}">
${guiao()}
</script>
</body>
</html>
`;
  exigirComunicacaoLimpa(html);
  return html;
}

/**
 * A página de recusa de um convite.
 *
 * **Diz o mesmo para um *token* forjado, expirado ou deformado**, e é o critério
 * 1 lido com cuidado: a recusa é um 403 e não um texto que explique qual das
 * três coisas aconteceu. Um texto que distinguisse «expirado» de «inválido»
 * dizia a quem forja que a chave esteve certa algum dia.
 */
export function paginaDeRecusa(): string {
  return `<!doctype html>
<html lang="pt">
<head><meta charset="utf-8"><title>KAMBA</title></head>
<body>
<h1>Esta ligacao nao esta valida</h1>
<p>Pergunte ao seu contacto da KAMBA por uma ligacao nova.</p>
</body>
</html>
`;
}
