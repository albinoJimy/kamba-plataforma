/**
 * O pré-voo do Embedded Signup (KAM-093, critério 2).
 *
 * Função pura: recebe o que o dono atestou e o que já sabemos dele, devolve os
 * sete itens na forma `{ id, tipo, ok, detalhe }` e o veredicto. Quem grava é o
 * `./guia.ts`.
 *
 * ## Um atestado só vale `true` se for `true`
 *
 * Não `"sim"`, não `1`, não «presente». O corpo vem de um formulário, e um
 * campo que aceite qualquer valor verdadeiro em JavaScript aceita `"false"` —
 * que é uma cadeia não vazia. A recusa por omissão é a única forma de um
 * atestado em falta não passar por atestado.
 *
 * ## O que este pré-voo não exige, e é a letra do bloco
 *
 * * **«≥ 7 dias de actividade»** do número na app: NÃO VERIFICADO no `E1`, e o
 *   bloco diz que **não** se impõe. Não há item para ele.
 * * **A elegibilidade de Angola para coexistência** (H3, `ext:KAM-100`): NÃO
 *   VERIFICADA. Não se pergunta; a saída documentada, se falhar, é `cloud_only`
 *   com número novo, e é a rota que o fixo já toma.
 */

import type { Linha } from "../inscricao/identificadores.ts";
import {
  type Atestados,
  type Detalhe,
  ITENS_DO_PREFLIGHT,
  type ItemAvaliado,
  type ItemDoPreflight,
  type Preflight,
  type Screening,
  TIPO_DO_ITEM,
  VERSAO_MINIMA_DA_APP,
} from "./contrato.ts";

/** O que o pré-voo lê de fora do formulário. */
export interface Factos {
  /** O tipo de linha do telefone **provado por OTP**, e não de um campo novo. */
  readonly linha: Linha;
  readonly screening: Screening;
  /** O *display name* proposto. Por omissão, o nome do negócio do caso. */
  readonly displayName: string;
  /**
   * Os termos de categoria bloqueada, já normalizados.
   *
   * **Parâmetro e não constante**: a lista é a *policy-as-code* do KAM-088, e
   * uma cópia aqui divergia dela no primeiro dia em que alguém a mudasse. Sem o
   * KAM-088 fundido, quem chama passa a lista que tiver — e uma lista vazia
   * deixa este item a medir só o «válido».
   */
  readonly termosBloqueados: readonly string[];
}

/** Uma versão `a.b.c` em três inteiros, ou `null`. Aceita sufixos (`2.24.17.79`). */
export function lerVersao(bruto: unknown): readonly [number, number, number] | null {
  if (typeof bruto !== "string") return null;
  const m = /^\s*(\d{1,4})\.(\d{1,4})\.(\d{1,4})(?:\.\d{1,6})?\s*$/.exec(bruto);
  if (m === null) return null;
  return [Number(m[1]), Number(m[2]), Number(m[3])];
}

/** `true` se `a ≥ b`, componente a componente. */
export function versaoPeloMenos(
  a: readonly [number, number, number],
  b: readonly [number, number, number],
): boolean {
  for (let i = 0; i < 3; i += 1) {
    const x = a[i] ?? 0;
    const y = b[i] ?? 0;
    if (x !== y) return x > y;
  }
  return true;
}

const MINIMA = lerVersao(VERSAO_MINIMA_DA_APP) ?? [2, 24, 17];

/** Sem acentos, minúsculas, espaços colapsados. O `normalizar` do `onboarding-web`. */
export function normalizarNome(texto: string): string {
  return texto
    .normalize("NFKD")
    .replace(/[̀-ͯ]/g, "")
    .toLowerCase()
    .replace(/\s+/g, " ")
    .trim();
}

function item(id: ItemDoPreflight, ok: boolean, detalhe: Detalhe): ItemAvaliado {
  return { id, tipo: TIPO_DO_ITEM[id], ok, detalhe };
}

function avaliarItem(id: ItemDoPreflight, a: Atestados, f: Factos): ItemAvaliado {
  switch (id) {
    case "app_versao": {
      const versao = lerVersao(a.versaoDaApp);
      if (versao === null) return item(id, false, a.versaoDaApp === undefined ? "nao_atestado" : "versao_ilegivel");
      if (!versaoPeloMenos(versao, MINIMA)) return item(id, false, "versao_antiga");
      // As duas metades do critério: a versão **e** «aberta nos últimos dias».
      return a.appAbertaRecentemente === true ? item(id, true, "ok") : item(id, false, "nao_atestado");
    }
    case "numero_movel":
      if (f.linha === "movel") return item(id, true, "ok");
      if (f.linha === "fixo") return item(id, false, "fixo_rota_cloud_only");
      return item(id, false, "numero_ilegivel");
    case "whatsapp_pessoal":
      // A pergunta é «está em WhatsApp **pessoal**?». `false` é o que deixa
      // seguir; `true` pede a conversão para a app Business antes do popup.
      if (a.numeroEmWhatsAppPessoal === false) return item(id, true, "ok");
      if (a.numeroEmWhatsAppPessoal === true) return item(id, false, "converter_para_business");
      return item(id, false, "nao_atestado");
    case "cartao_internacional":
      if (a.cartaoInternacional === true) return item(id, true, "ok");
      return item(id, false, a.cartaoInternacional === false ? "sem_cartao_internacional" : "nao_atestado");
    case "categoria_aprovada":
      if (f.screening === "aprovada") return item(id, true, "ok");
      return item(id, false, f.screening === "recusada" ? "categoria_recusada" : "categoria_por_aprovar");
    case "display_name": {
      const nome = normalizarNome(f.displayName);
      if (nome === "") return item(id, false, "nome_vazio");
      for (const termo of f.termosBloqueados) {
        const t = normalizarNome(termo);
        if (t !== "" && nome.includes(t)) return item(id, false, "nome_com_termo_bloqueado");
      }
      return item(id, true, "ok");
    }
    case "dono_presente":
      return a.donoPresente === true ? item(id, true, "ok") : item(id, false, "nao_atestado");
  }
}

/**
 * O pré-voo inteiro.
 *
 * `podeAbrir` exige **todos** os itens `ok`, com uma excepção só: o
 * `numero_movel` em `fixo_rota_cloud_only`, que muda a rota em vez de
 * bloquear. Um `numero_ilegivel` bloqueia — um número que não sabemos ler não
 * tem rota.
 */
export function avaliarPreflight(atestados: Atestados, factos: Factos, agora: Date): Preflight {
  const itens = ITENS_DO_PREFLIGHT.map((id) => avaliarItem(id, atestados, factos));
  const fixo = factos.linha === "fixo";
  const podeAbrir = itens.every(
    (i) => i.ok || (i.id === "numero_movel" && i.detalhe === "fixo_rota_cloud_only"),
  );
  return { itens, podeAbrir, rota: fixo ? "cloud_only" : "coexistencia", avaliadoEm: agora };
}
