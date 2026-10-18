// Corre `mermaid.parse` sobre cada bloco mermaid da entrada padrao.
//
// O `mermaid.parse` sanitiza os rotulos com o DOMPurify, que precisa de um DOM.
// Sem ele todos os diagramas falham com «DOMPurify.addHook is not a function» —
// um erro de ambiente que se le como erro de diagrama, que e exactamente o
// falso vermelho que esta verificacao existe para nao produzir. Dai o jsdom,
// montado nos globais ANTES de o mermaid ser importado.
import { JSDOM } from 'jsdom';

const dom = new JSDOM('<!doctype html><html><body></body></html>');
globalThis.window = dom.window;
globalThis.document = dom.window.document;
// No Node 24 o `navigator` e um getter do global: atribuir-lhe deita abaixo.
Object.defineProperty(globalThis, 'navigator', {
  value: dom.window.navigator,
  configurable: true,
});

const mermaid = (await import('mermaid')).default;

const blocos = JSON.parse(
  await new Promise((resolver) => {
    let texto = '';
    process.stdin.on('data', (pedaco) => (texto += pedaco));
    process.stdin.on('end', () => resolver(texto));
  }),
);

mermaid.initialize({ startOnLoad: false, securityLevel: 'strict' });

let maus = 0;
for (const bloco of blocos) {
  const primeira = bloco.texto.split('\n')[0];
  try {
    await mermaid.parse(bloco.texto);
    console.log(`ok     ${bloco.ficheiro}:${bloco.linha}  ${primeira}`);
  } catch (erro) {
    maus += 1;
    const msg = erro && erro.message ? erro.message : String(erro);
    console.log(`FALHA  ${bloco.ficheiro}:${bloco.linha}  ${primeira}  -> ${msg}`);
  }
}
console.log(`\n${blocos.length} bloco(s), ${maus} com erro`);
process.exit(maus === 0 ? 0 : 1);
