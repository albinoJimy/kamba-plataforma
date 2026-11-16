/**
 * A rotação da KEK dos *tokens* de cliente (KAM-072, critério 4).
 *
 * O critério pede: «rodar a KEK re-cifra as DEK sem tocar nos *tokens* e a
 * leitura mantém-se». O KAM-016 entregou a cifra (`onboarding/cifra.ts`) com
 * uma decisão que muda a forma deste critério: **a DEK por tenant é derivada**
 * da KEK por HKDF e não guardada. Não há DEK embrulhada para re-cifrar — rodar a
 * KEK muda a DEK.
 *
 * O que se mantém, e é o que este ficheiro prova:
 *
 * * **a leitura mantém-se durante a janela** sem fazer nada: o `kid` vai dentro
 *   do criptograma e o `decifrarToken` escolhe a versão da KEK pelo anel;
 * * **o *token* não muda**: a re-cifra abre com a versão antiga e fecha com a
 *   actual, e o texto que sai é o mesmo que entrou. O que muda é o
 *   **criptograma** guardado no cofre — e é essa a diferença face à letra do
 *   critério, que fica declarada no bloco em vez de corrigida em silêncio;
 * * **depois de a anterior ser revogada a leitura continua**, desde que a
 *   re-cifra tenha corrido sobre todos os criptogramas antes.
 *
 * A re-cifra é **idempotente**: um criptograma que já está na versão actual
 * devolve-se tal como veio, pelo que repetir o *job* não cifra outra vez.
 */

import { cifrarToken, decifrarToken, kidDoCriptograma } from "../onboarding/cifra.ts";

import type { Anel } from "./anel.ts";

/** O anel na forma `{kid: valor}` que o `decifrarToken` recebe. */
export function anelPorKid(anel: Anel): Readonly<Record<string, string>> {
  const mapa: Record<string, string> = { [anel.actual.kid]: anel.actual.valor };
  if (anel.anterior !== null) mapa[anel.anterior.kid] = anel.anterior.valor;
  return mapa;
}

/** O resultado de uma re-cifra: o criptograma e se mudou. */
export interface Recifra {
  readonly criptograma: string;
  readonly mudou: boolean;
}

/**
 * Re-cifra um criptograma com a versão actual da KEK, sem mudar o *token*.
 *
 * Levanta `TokenCifradoInvalidoError` (do `cifra.ts`) se a versão que o cifrou
 * já não estiver no anel — é o sinal de que a anterior foi revogada antes de a
 * re-cifra acabar, e o *token* só volta com o dono a repetir o Embedded Signup.
 */
export function recifrarToken(anel: Anel, tenantId: string, criptograma: string): Recifra {
  if (kidDoCriptograma(criptograma) === anel.actual.kid) {
    // Abre-se na mesma: um criptograma com o `kid` certo e o conteúdo errado
    // não pode passar por re-cifrado só porque o cabeçalho diz a versão certa.
    decifrarToken(anelPorKid(anel), tenantId, criptograma);
    return { criptograma, mudou: false };
  }
  const token = decifrarToken(anelPorKid(anel), tenantId, criptograma);
  return {
    criptograma: cifrarToken(anel.actual.valor, anel.actual.kid, tenantId, token),
    mudou: true,
  };
}
