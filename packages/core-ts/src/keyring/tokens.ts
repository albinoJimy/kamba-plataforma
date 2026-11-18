/**
 * A rotação da KEK dos *tokens* de cliente (KAM-072, critério 4).
 *
 * O critério pede: «rodar a KEK re-cifra as DEK sem tocar nos *tokens* e a
 * leitura mantém-se». O KAM-016 entregou a cifra (`onboarding/cifra.ts`) com
 * uma decisão que muda a forma deste critério: **a DEK por tenant é derivada**
 * da KEK por HKDF e não guardada. Não há DEK embrulhada para re-cifrar — rodar a
 * KEK muda a DEK.
 *
 * O que se mantém **quando o `kid` é um identificador de versão estável** —
 * os inteiros do OpenBao KV v2, ou os `kid` deste módulo —, e é o que este
 * ficheiro prova:
 *
 * * **a leitura mantém-se durante a janela** sem fazer nada: o `kid` vai dentro
 *   do criptograma e o `decifrarToken` escolhe a versão da KEK pelo anel;
 * * **o *token* não muda**: a re-cifra abre com a versão antiga e fecha com a
 *   actual, e o texto que sai é o mesmo que entrou. O que muda é o
 *   **criptograma** — e é essa a diferença face à letra do critério, que fica
 *   declarada na secção de verificação do bloco;
 * * **depois de a anterior ser revogada a leitura continua**, desde que a
 *   re-cifra tenha corrido sobre todos os criptogramas antes.
 *
 * ## O `kid` estável, e os criptogramas de antes dele (KAM-205)
 *
 * A revisão adversarial do KAM-072 mediu que, no Piloto, o `kid` **não era
 * estável**: o `EnvSecretProvider` dava os rótulos posicionais `actual` e
 * `anterior`, e rodar a `kek_token_cliente` partia todos os *tokens* guardados.
 * O KAM-205 fecha-o em três sítios:
 *
 * * o provedor lê o `kid` do valor, `<kid>:<base64>` (`secrets/kid.ts`), e esse
 *   `kid` vai com a versão quando ela passa a anterior;
 * * o `onboarding` recusa cifrar com um rótulo posicional (`kekParaCifrar`);
 * * os criptogramas gravados antes, com `kid` `actual`, abrem pela versão **sem**
 *   `kid` no valor (`KID_LEGADO`, no `onboarding/cifra.ts`), em qualquer
 *   posição — é essa regra que deixa rodar uma vez para um `kid` estável e
 *   re-cifrar o que ficou para trás.
 *
 * O `recifrarTokensGuardados`, no fim deste ficheiro, é o *job* que faz a
 * re-cifra sobre a `tenant_channels`. A ordem está no RB-K07 §3.7: rodar,
 * re-cifrar, revogar.
 *
 * A re-cifra é **idempotente**: um criptograma que já está na versão actual
 * devolve-se tal como veio, pelo que repetir o *job* não cifra outra vez.
 */

import {
  KID_LEGADO,
  KekSemKidEstavelError,
  TokenCifradoInvalidoError,
  anelDaKek,
  cifrarToken,
  decifrarToken,
  kekParaCifrar,
  kidDoCriptograma,
} from "../onboarding/cifra.ts";
import type { ClienteSql, Cofre } from "../onboarding/contrato.ts";
// Os `id` de segredo vêm do ficheiro estreito que o *gate* 9 dispensa.
import { FAMILIA_DO_TOKEN, REF_DA_KEK } from "../onboarding/segredos.ts";
import { rotuloPosicional } from "../secrets/kid.ts";
import { SecretAusenteError, SecretRefInvalidaError } from "../secrets/port.ts";

import type { Anel, ChaveDoAnel } from "./anel.ts";

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

// --- A re-cifra dos tokens guardados (KAM-205) ----------------------------------

/**
 * O anel da `kek_token_cliente` tal como o cofre o dá, na forma do `keyring`.
 *
 * A actual tem de trazer `kid` estável — re-cifrar para um rótulo posicional era
 * recriar o defeito, e o `kekParaCifrar` recusa-o. A anterior pode ser a versão
 * sem `kid` de antes do KAM-205, e então responde por `KID_LEGADO`.
 */
export async function anelDaKekNoCofre(cofre: Pick<Cofre, "getRing" | "versions">): Promise<Anel> {
  const valores = await cofre.getRing(REF_DA_KEK);
  const kids = await cofre.versions(REF_DA_KEK);
  const [kidActual, kidAnterior] = kids;
  if (kidActual === undefined) throw new KekSemKidEstavelError();
  const actual = kekParaCifrar(kidActual, valores[0]);
  const porKid = anelDaKek(valores, kids);
  let anterior: ChaveDoAnel | null = null;
  if (valores[1] !== null && kidAnterior !== undefined) {
    const kid = rotuloPosicional(kidAnterior) ? KID_LEGADO : kidAnterior;
    const valor = porKid[kid];
    if (valor !== undefined) anterior = { kid, valor };
  }
  return { actual: { kid: actual.kid, valor: actual.chave }, anterior, anteriorAte: null };
}

/**
 * Pergunta se o papel da ligação atravessa a RLS.
 *
 * A `tenant_channels` tem RLS por *tenant*. Com o `kamba_app` e sem tenant na
 * sessão a leitura devolve **zero linhas sem erro**, e a re-cifra acabava com
 * «0 por re-cifrar» — o sinal exacto que o RB-K07 §3.7 manda esperar antes de
 * revogar a anterior. Revogar a seguir perdia todos os *tokens*. Só o
 * `kamba_batch` tem `BYPASSRLS` (`db/rls.py`).
 */
export const SQL_PAPEL_ATRAVESSA_TENANTS = `
  SELECT rolbypassrls AS atravessa
    FROM pg_roles
   WHERE rolname = current_user
`;

/** Os canais por re-cifrar, por páginas de chave: retoma onde a última parou. */
export const SQL_CANAIS_A_RECIFRAR = `
  SELECT id::text AS id, tenant_id::text AS tenant_id, token_ref
    FROM platform.tenant_channels
   WHERE id > $1::uuid
   ORDER BY id
   LIMIT $2
`;

/**
 * Troca a referência, **só se ainda for a que se leu**.
 *
 * O `AND token_ref = $2` é o que torna seguras duas re-cifras ao mesmo tempo, ou
 * uma re-cifra e qualquer outro escritor da `token_ref`: quem perde não escreve,
 * e revoga a referência que acabou de cunhar.
 */
export const SQL_TROCAR_TOKEN_REF = `
  UPDATE platform.tenant_channels
     SET token_ref = $3
   WHERE id = $1::uuid
     AND token_ref = $2
  RETURNING id::text AS id
`;

/** Linhas por página. */
export const LOTE_DA_RECIFRA = 100;

/** O primeiro `id` de todos, para a primeira página. */
const ANTES_DO_PRIMEIRO = "00000000-0000-0000-0000-000000000000";

/** A ligação não atravessa a RLS: a re-cifra veria zero canais e diria que acabou. */
export class RecifraSemPapelDeLoteError extends Error {
  override readonly name = "RecifraSemPapelDeLoteError";

  constructor() {
    super(
      "a re-cifra dos tokens de cliente corre como kamba_batch (BYPASSRLS); " +
        "com outro papel a tenant_channels lê-se vazia e a re-cifra parecia acabada",
    );
  }
}

/** O que uma passagem fez. Os `falhados` são `tenant_channels.id`, nunca valores. */
export interface ResultadoDaRecifra {
  readonly vistos: number;
  readonly recifrados: number;
  readonly jaNaActual: number;
  readonly concorrentes: number;
  readonly falhados: readonly string[];
}

/** As portas do *job*: o cofre de leitura e escrita, e uma ligação `kamba_batch`. */
export interface DependenciasDaRecifra {
  readonly cofre: Cofre;
  readonly sql: ClienteSql;
  readonly lote?: number;
}

/**
 * Re-cifra todos os *tokens* de cliente guardados com a versão actual da KEK.
 *
 * Para cada canal: lê o criptograma, re-cifra-o (`recifrarToken`), cunha uma
 * referência nova com o criptograma novo, troca a `token_ref` se ainda for a
 * lida, e só então revoga a antiga. **Sem esquema**: a coluna é a que já existe.
 *
 * * **Idempotente.** Um criptograma que já está no `kid` actual não se toca: a
 *   segunda passagem dá `recifrados: 0`.
 * * **Retomável.** Cair a meio deixa cada canal ou na referência antiga ou na
 *   nova, nunca sem nenhuma; a passagem seguinte faz o que faltou. O que pode
 *   ficar é uma referência **órfã** no cofre — a nova, se a queda foi entre o
 *   `cunhar` e o `UPDATE`; a antiga, se foi entre o `UPDATE` e o `revogar`. Não
 *   dá o *token* a ninguém sem a KEK, e a antiga deixa de abrir quando a anterior
 *   for revogada.
 * * **Não pára num canal que não abre.** Regista-o em `falhados` e segue: o
 *   RB-K07 §3.7 só deixa revogar a anterior com `falhados` vazio.
 *
 * Um cofre em baixo propaga: não é um *token* perdido, é uma passagem por
 * repetir.
 *
 * **A ligação tem de estar em *autocommit*.** A antiga revoga-se logo a seguir
 * ao `UPDATE`, e isso só é seguro se o `UPDATE` já estiver confirmado: dentro de
 * um `BEGIN … COMMIT`, uma queda a meio reverte as trocas e deixa os canais a
 * apontar para referências já revogadas — *tokens* perdidos. Por isso cada canal
 * é uma instrução própria, e o *job* não abre transacção.
 *
 * **Um limite que não é alcançável hoje:** a `channel_onboarding.recursos_criados`
 * guarda a referência que o onboarding cunhou, e a re-cifra não a acompanha. Uma
 * compensação posterior leria uma referência revogada. Hoje a compensação só
 * corre dentro da transacção do `ligar`, cuja linha o *job* não vê antes do
 * `COMMIT`; se um dia correr fora dela, este passo tem de passar a actualizar a
 * lista.
 */
export async function recifrarTokensGuardados(d: DependenciasDaRecifra): Promise<ResultadoDaRecifra> {
  const { rows: papel } = await d.sql.query<{ atravessa: boolean }>(SQL_PAPEL_ATRAVESSA_TENANTS);
  if (papel[0]?.atravessa !== true) throw new RecifraSemPapelDeLoteError();
  const anel = await anelDaKekNoCofre(d.cofre);
  const lote = d.lote ?? LOTE_DA_RECIFRA;
  let vistos = 0;
  let recifrados = 0;
  let jaNaActual = 0;
  let concorrentes = 0;
  const falhados: string[] = [];
  let ultimo = ANTES_DO_PRIMEIRO;
  for (;;) {
    const { rows } = await d.sql.query<{ id: string; tenant_id: string; token_ref: string }>(
      SQL_CANAIS_A_RECIFRAR,
      [ultimo, lote],
    );
    for (const canal of rows) {
      vistos += 1;
      let recifra: Recifra;
      try {
        recifra = recifrarToken(anel, canal.tenant_id, await d.cofre.get(canal.token_ref));
      } catch (erro) {
        // Um canal que não abre — versão fora do anel, criptograma alterado,
        // referência sem segredo ou mal formada — é deste canal, e não da
        // passagem: regista-se e segue.
        if (
          erro instanceof TokenCifradoInvalidoError ||
          erro instanceof SecretAusenteError ||
          erro instanceof SecretRefInvalidaError
        ) {
          falhados.push(canal.id);
          continue;
        }
        throw erro;
      }
      if (!recifra.mudou) {
        jaNaActual += 1;
        continue;
      }
      const novo = await d.cofre.cunhar(FAMILIA_DO_TOKEN, recifra.criptograma);
      let trocadas: readonly { id: string }[];
      try {
        ({ rows: trocadas } = await d.sql.query<{ id: string }>(SQL_TROCAR_TOKEN_REF, [
          canal.id,
          canal.token_ref,
          novo,
        ]));
      } catch (erro) {
        await d.cofre.revogar(novo);
        throw erro;
      }
      if (trocadas.length === 1) {
        await d.cofre.revogar(canal.token_ref);
        recifrados += 1;
      } else {
        await d.cofre.revogar(novo);
        concorrentes += 1;
      }
    }
    const fim = rows.at(-1);
    if (rows.length < lote || fim === undefined) break;
    ultimo = fim.id;
  }
  return { vistos, recifrados, jaNaActual, concorrentes, falhados };
}
