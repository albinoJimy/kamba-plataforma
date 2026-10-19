/**
 * Os `id` dos dois segredos que o GWY lê. **Só isto, e é de propósito.**
 *
 * `ops/secrets-inventory.yaml`: o App Secret com `anel: true` e o
 * `verify_token` com `anel: false`. Os nomes são os do dicionário §3.9.
 *
 * ## Porque é que isto é um ficheiro só para duas linhas
 *
 * O *gate* 9 apanha, com razão, uma atribuição a um nome que **significa**
 * segredo com um valor de entropia suficiente: é a forma de um segredo
 * embutido no código. E uma referência ao `verify_token` tem, por força, essa
 * forma — o nome do campo é canónico e o valor é canónico, e não há maneira de
 * escrever um ao lado do outro sem o scanner disparar. Tentou-se: duas
 * constantes soltas no `server.ts` (apanhadas), a mesma coisa dentro de um
 * objecto (apanhada), e um comentário a explicar a forma (apanhado também, e
 * isso está certo — o scanner lê bytes, não intenções).
 *
 * A saída é declarar a área em `ci/secrets-allow.yaml`, e a decisão é **onde**.
 * Declarar o `server.ts` permitia a classe `atribuicao` no ficheiro de arranque
 * do GWY, que é o último sítio do repositório onde isso convém: é lá que o
 * cofre se lê. Este ficheiro existe para que a área seja tão estreita quanto
 * possível — duas cadeias que são nomes, nenhuma lógica, nenhum valor — e para
 * que o `server.ts` continue inteiramente varrido.
 *
 * **Nada aqui é um segredo.** Se um dia for, o gate 9 deixa de o apanhar neste
 * ficheiro, e é por isso que ele não leva mais nada.
 */

/** O `id` do App Secret no cofre. Tem anel `[actual, anterior]`. */
export const REF_DO_APP_SECRET = "meta_app_secret";

/** O `id` do `verify_token` do `GET` de verificação. Sem anel. */
export const REF_DO_VERIFY_TOKEN = "meta_verify_token";
