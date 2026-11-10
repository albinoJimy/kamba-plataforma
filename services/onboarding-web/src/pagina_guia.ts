/**
 * A página `/ligar`: o passo guiado do Embedded Signup v4 (KAM-093).
 *
 * ## A CSP abre uma porta, e é a da Meta
 *
 * A página de registo (`./pagina.ts`) não faz um único pedido a terceiros. Esta
 * **não pode**: o Embedded Signup corre no SDK JavaScript da Meta, num popup
 * em `facebook.com`, e é lá que o dono se autentica — **presente**, e sem
 * nunca nos dar a palavra-passe, o *token* ou o PIN (critério 9). Por isso a
 * CSP desta página admite `connect.facebook.net` para o guião e os domínios da
 * Meta para a ligação, e mais nada. O IP e o `User-Agent` do dono vão para a
 * Meta neste passo — que é o passo em que ele se autentica nela, e é a mesma
 * relação que o ADR-001 já assume. Os domínios exactos que o SDK usa são
 * **INDÍCIO** (documentação pública da Meta, não lida no `E1`).
 *
 * ## O que o guião envia, e o que não envia
 *
 * Ao servidor só vão o `code`, o `waba_id` e o `phone_number_id` (critério 1). O *token* nunca passa pelo navegador: o `code` é
 * trocado no GWY (KAM-016), e o *token* e o PIN vão de lá directamente ao
 * cofre. A página **não tem** campo para *token*, PIN ou código da Meta, e o
 * texto diz ao dono que nunca os peça a ninguém.
 *
 * ## A forma do `session_info` é NÃO VERIFICADA
 *
 * O evento de *session logging* do popup (`WA_EMBEDDED_SIGNUP`) traz o
 * `phone_number_id` e o `waba_id`; a forma exacta do resto não está no `E1`. Por
 * isso o guião **não** o manda: o `session_info` que o KAM-016 verifica é
 * composto no servidor a partir da rota que o pré-voo gravou (`sessionInfo` do
 * `PassoGuiado`), e diz o que a página abriu — não é uma afirmação
 * independente da Meta. Fica dito.
 */

/** O que a página precisa. */
export interface DadosDaLigacao {
  readonly nonce: string;
  readonly appId: string;
  /** A versão da Graph do `KAMBA_META_GRAPH_VERSION` (KAM-016): o SDK pede-a. */
  readonly versaoDaGraph: string;
}

/** A CSP da página. Ver a nota do módulo. */
export function cspDaLigacao(nonce: string): string {
  return [
    "default-src 'none'",
    `style-src 'nonce-${nonce}'`,
    `script-src 'nonce-${nonce}' https://connect.facebook.net`,
    "connect-src 'self' https://graph.facebook.com https://www.facebook.com",
    "frame-src https://www.facebook.com https://web.facebook.com https://staticxx.facebook.com",
    "img-src https://www.facebook.com",
    "form-action 'self'",
    "frame-ancestors 'none'",
    "base-uri 'none'",
  ].join("; ");
}

export function cabecalhosDaLigacao(nonce: string): Record<string, string> {
  return {
    "Content-Security-Policy": cspDaLigacao(nonce),
    // `no-referrer` pela razão do `./pagina.ts`: a ligação de retoma leva `?r=`.
    "Referrer-Policy": "no-referrer",
    "X-Content-Type-Options": "nosniff",
    "Cache-Control": "no-store",
  };
}

function escapar(texto: string): string {
  return texto
    .replace(/&/g, "&amp;")
    .replace(/</g, "&lt;")
    .replace(/>/g, "&gt;")
    .replace(/"/g, "&quot;")
    .replace(/'/g, "&#39;");
}

/**
 * O aviso do protocolo bot ↔ dono (KAM-018), que a *Copy* do bloco manda dar.
 * Exportado para o ensaio o procurar na página e não numa cópia.
 */
export const AVISO_DO_BOT = "Se responder a um cliente na app, o bot cala-se nessa conversa.";

/** O aviso do critério 9. */
export const AVISO_DO_TOKEN = "A KAMBÁ nunca lhe pede palavra-passe, PIN nem códigos da Meta.";

const ESTILO = `
body{font-family:system-ui,sans-serif;max-width:32rem;margin:0 auto;padding:1rem;line-height:1.4}
h1{font-size:1.3rem} ol{padding-left:1.2rem} li{margin:.4rem 0}
label{display:block;margin:.5rem 0} button{font-size:1rem;padding:.6rem 1rem;margin:.5rem 0}
.aviso{background:#fff6d6;padding:.6rem;border-radius:.3rem} .ko{color:#a00} .ok{color:#060}
`;

const GUIAO = `
(function(){
  var raiz=document.getElementById('estado');
  var lista=document.getElementById('itens');
  var appId=document.body.dataset.app;var versao=document.body.dataset.versao;
  var ids={};
  function api(caminho,corpo){
    return fetch(caminho,{method:corpo===undefined?'GET':'POST',credentials:'same-origin',
      headers:{'content-type':'application/json'},body:corpo===undefined?undefined:JSON.stringify(corpo)})
      .then(function(r){return r.json().then(function(j){return {estado:r.status,corpo:j};});});
  }
  function mostrar(texto){raiz.textContent=texto;}
  function desenharItens(itens){
    lista.textContent='';
    (itens||[]).forEach(function(i){
      var li=document.createElement('li');
      li.className=i.ok?'ok':'ko';
      li.textContent=i.id+': '+(i.ok?'ok':i.detalhe);
      lista.appendChild(li);
    });
  }
  function actualizar(){
    return api('/api/es/estado').then(function(r){
      if(r.estado!==200){mostrar('Sessão expirada. Entre outra vez com o código SMS.');return;}
      mostrar('Estado: '+r.corpo.estado);desenharItens(r.corpo.preflight);
    });
  }
  document.getElementById('preflight').addEventListener('submit',function(ev){
    ev.preventDefault();
    var f=ev.target;
    api('/api/es/preflight',{
      versao_da_app:f.versao.value,
      app_aberta_recentemente:f.aberta.checked,
      numero_em_whatsapp_pessoal:f.pessoal.checked,
      cartao_internacional:f.cartao.checked,
      dono_presente:f.presente.checked
    }).then(function(r){desenharItens(r.corpo.itens);});
  });
  function carregarSdk(depois){
    if(window.FB){depois();return;}
    window.fbAsyncInit=function(){FB.init({appId:appId,autoLogAppEvents:false,xfbml:false,version:versao});depois();};
    var s=document.createElement('script');
    s.src='https://connect.facebook.net/pt_PT/sdk.js';s.async=true;s.nonce=document.body.dataset.nonce;
    document.body.appendChild(s);
  }
  window.addEventListener('message',function(ev){
    if(!/^https:\\/\\/([a-z]+\\.)?facebook\\.com$/.test(ev.origin))return;
    var d;try{d=typeof ev.data==='string'?JSON.parse(ev.data):ev.data;}catch(e){return;}
    if(!d||d.type!=='WA_EMBEDDED_SIGNUP')return;
    if(d.event==='CANCEL'){api('/api/es/cancelar',{}).then(actualizar);return;}
    if(d.data){ids.phone_number_id=d.data.phone_number_id;ids.waba_id=d.data.waba_id;ids.evento=d.event;}
  });
  document.getElementById('ligar').addEventListener('click',function(){
    api('/api/es/iniciar',{}).then(function(r){
      if(r.estado!==200){mostrar('Ainda não pode ligar: '+(r.corpo.erro||''));return;}
      if(r.corpo.desfecho==='lista_espera'){mostrar('Lista de espera: avisamos por SMS quando houver vaga.');return;}
      var cfg=r.corpo.configuracao;
      carregarSdk(function(){
        FB.login(function(resposta){
          if(!resposta||!resposta.authResponse||!resposta.authResponse.code){
            api('/api/es/cancelar',{}).then(actualizar);return;
          }
          // O evento WA_EMBEDDED_SIGNUP pode chegar depois do callback: espera-se
          // por ele ate 5 s, em vez de mandar o code sem numero e o gastar.
          var codigo=resposta.authResponse.code,espera=0;
          (function mandar(){
            if(!ids.phone_number_id&&espera<20){espera+=1;setTimeout(mandar,250);return;}
            api('/api/es/concluir',{code:codigo,waba_id:ids.waba_id,
              phone_number_id:ids.phone_number_id}).then(actualizar);
          })();
        },{config_id:cfg.config_id,response_type:cfg.response_type,
           override_default_response_type:cfg.override_default_response_type,extras:cfg.extras});
      });
    });
  });
  document.getElementById('pagamento').addEventListener('click',function(){
    api('/api/es/pagamento',{}).then(function(r){
      mostrar(r.corpo.verde?'Pagamento confirmado.':'Sem cartão detectado. Pode adicionar um cartão no Billing Hub ou usar mensagens pré-pagas (MPS).');
    });
  });
  actualizar();
})();
`;

/** A página. Nada do que o cliente manda volta para dentro dela. */
export function paginaDaLigacao(dados: DadosDaLigacao): string {
  const nonce = escapar(dados.nonce);
  return `<!doctype html>
<html lang="pt-AO"><head><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1">
<title>Ligar o WhatsApp da loja</title><style nonce="${nonce}">${ESTILO}</style></head>
<body data-nonce="${nonce}" data-app="${escapar(dados.appId)}" data-versao="${escapar(dados.versaoDaGraph)}">
<h1>Ligar o WhatsApp da loja</h1>
<p class="aviso">Este passo é consigo, com o telemóvel na mão. ${AVISO_DO_TOKEN}</p>
<p id="estado">A carregar…</p>
<h2>Antes de começar</h2>
<form id="preflight">
<label>Versão da app WhatsApp Business (Definições → Ajuda): <input name="versao" inputmode="decimal" autocomplete="off"></label>
<label><input type="checkbox" name="aberta"> Abri a app nos últimos dias</label>
<label><input type="checkbox" name="pessoal"> Este número está hoje no WhatsApp pessoal (e não no Business)</label>
<label><input type="checkbox" name="cartao"> Tenho cartão que paga em moeda internacional</label>
<label><input type="checkbox" name="presente"> Estou presente, com o telemóvel</label>
<button type="submit">Verificar</button>
</form>
<ol id="itens"></ol>
<p>Se o número estiver no WhatsApp pessoal, passe-o primeiro para a app WhatsApp Business.</p>
<p>${AVISO_DO_BOT}</p>
<button id="ligar" type="button">Ligar o WhatsApp</button>
<button id="pagamento" type="button">Verificar o pagamento</button>
<script nonce="${nonce}">${GUIAO}</script>
</body></html>`;
}

/**
 * O caminho da retoma sem sessão: código SMS ao telefone **registado**, e a
 * página recarrega-se com a sessão nova. O guião lê o `r` do endereço, no
 * navegador, pelo que o **corpo** da recusa é o mesmo para uma ligação forjada,
 * alheia, expirada ou sem sessão — quem distingue é o servidor, no
 * `POST /api/es/retoma`, e responde 403 igual a todas as que não servem.
 */
const GUIAO_DA_RETOMA = `
(function(){
  var r=new URLSearchParams(location.search).get('r');
  var caixa=document.getElementById('retoma');
  if(!r){return;}
  caixa.hidden=false;
  var referencia=null;
  function post(caminho,corpo){
    return fetch(caminho,{method:'POST',credentials:'same-origin',headers:{'content-type':'application/json'},
      body:JSON.stringify(corpo)}).then(function(x){return x.json().then(function(j){return {estado:x.status,corpo:j};});});
  }
  document.getElementById('enviar').addEventListener('click',function(){
    post('/api/es/retoma',{r:r}).then(function(x){
      if(x.estado!==200){caixa.textContent='Esta ligação já não serve. Peça uma nova ao apoio.';return;}
      referencia=x.corpo.referencia;document.getElementById('codigo').hidden=false;
    });
  });
  document.getElementById('codigo').addEventListener('submit',function(ev){
    ev.preventDefault();
    post('/api/otp/verificar',{referencia:referencia,codigo:ev.target.c.value}).then(function(x){
      if(x.corpo.veredicto==='acertou'){location.reload();}
    });
  });
})();
`;

/** A página de recusa. Igual para forjado, alheio, expirado e sem sessão. */
export function paginaDeRecusaDaLigacao(nonce: string): string {
  const n = escapar(nonce);
  return `<!doctype html>
<html lang="pt-AO"><head><meta charset="utf-8"><title>Ligação inválida</title></head>
<body><h1>Esta ligação não abre</h1><p>Entre outra vez pela ligação que recebeu e confirme o código SMS.</p>
<div id="retoma" hidden><button id="enviar" type="button">Enviar código SMS</button>
<form id="codigo" hidden><label>Código: <input name="c" inputmode="numeric" autocomplete="one-time-code"></label><button type="submit">Confirmar</button></form></div>
<script nonce="${n}">${GUIAO_DA_RETOMA}</script></body></html>`;
}
