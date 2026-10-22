/**
 * Os identificadores de segredo que o onboarding de canal lê e escreve (KAM-016).
 *
 * **Três nomes, e nada mais** — o ficheiro existe para que a área que o *gate* 9
 * dispensa seja tão estreita quanto possível. É o mesmo desenho e a mesma razão
 * do `services/gwy/src/segredos.ts` (KAM-013), e a razão está escrita lá:
 *
 * > Uma referência ao `verify_token` tem, por força, a forma que o gate apanha:
 * > o nome do campo é canónico (dicionário §3.9) e o valor é canónico, e não há
 * > maneira de escrever um ao lado do outro sem o scanner disparar.
 *
 * Aqui é igual. `FAMILIA_DO_TOKEN = "meta_client_token"` é um `id` do
 * `ops/secrets-inventory.yaml` atribuído a um nome que contém «TOKEN»: a classe
 * `atribuicao` do `tools/scan_secrets/patterns.py` dispara, e correctamente — a
 * heurística não pode distinguir um `id` de um valor. Medido: o `"meta_client_token"`
 * tem entropia de Shannon **3,293**, contra o mínimo de 3,2 do padrão.
 *
 * A alternativa era declarar `contrato.ts`, que é onde vive o vocabulário
 * inteiro do módulo e o último sítio do repositório onde a classe `atribuicao`
 * convém. Com estes três aqui, esse ficheiro continua **inteiramente varrido** —
 * e se um dia um valor a sério entrar neste ficheiro, o gate deixa de o apanhar.
 * É por isso que ele não leva mais nada: nem uma função, nem um tipo, nem um
 * quarto nome.
 *
 * **O que está aqui são `id` publicados**, em `ops/secrets-inventory.yaml`, com
 * dono, ambientes e rotação declarados. Nenhum é um valor.
 */

/**
 * A família do *token* de cliente do Embedded Signup.
 *
 * `instancias: tenant` no inventário — uma instância por canal onboardado —, e
 * a referência que o `cunhar` devolve é o que `tenant_channels.token_ref`
 * guarda. **A coluna nunca guarda o *token***, e o inventário di-lo na nota da
 * entrada.
 */
export const FAMILIA_DO_TOKEN = "meta_client_token";

/**
 * A família do PIN 2FA do número.
 *
 * `instancias: tenant`, e a nota do inventário fixa o acesso: «Acesso minimo:
 * so o provisionamento o le». É o que o passo 5′ do `../../../docs/tecnica/01`
 * §13.2 usa para registar o número em modo `cloud_only`, e a Meta está a
 * descontinuá-lo — é por isso que a entrada não tem período de rotação, só o
 * gatilho `descontinuacao_pela_meta`.
 */
export const FAMILIA_DO_PIN = "meta_pin_2fa";

/**
 * A KEK que embrulha as DEK por *tenant* dos *tokens* de cliente.
 *
 * `instancias: nenhuma`, `anel: true`, `kid: true` — e são essas duas últimas
 * que fazem a rotação possível: o `kid` vai **dentro** do criptograma (ver o
 * `cifra.ts`), pelo que o dia em que a KEK rodar não torna indecifráveis os
 * *tokens* já guardados. Tem `owner: seguranca`, contra o `owner: eng_canais`
 * da família do *token*, e é essa separação que dá conteúdo concreto à defesa em
 * profundidade: uma cópia do cofre não dá o *token* a quem não tenha também a
 * KEK.
 */
export const REF_DA_KEK = "kek_token_cliente";
