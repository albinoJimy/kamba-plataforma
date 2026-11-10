/**
 * O `screen` e o `assertPublishable` (KAM-088, critérios 2 e 4).
 *
 * A ordem dos Detalhes Técnicos, à letra: normalizar → regras (negar vence) →
 * se `permitida` e confiança baixa → classificador → `maxRestricao(regras,
 * tecto(classificador))` → gravar. Uma `bloqueada` das regras é final: não há
 * chamada ao classificador. Uma `condicional` também não o chama, e não por
 * poupança: o classificador não passa de `condicional` (`tecto`), pelo que a
 * resposta dele não mudaria nada.
 *
 * **Cada decisão grava-se, e o `screen` só devolve depois de gravar.** Uma
 * decisão que não ficou na `screening_decision` não existe para o
 * `assertPublishable`, que falha fechado sem ela — por isso um erro do escritor
 * sobe, em vez de devolver uma decisão que ninguém pode provar.
 */

import { createHash } from "node:crypto";

import {
  type ClassificadorDeCategorias,
  lerVeredicto,
  prepararPedido,
  tecto,
  type VeredictoDoClassificador,
} from "./classificador.ts";
import { avaliarRegras, LIMIAR_DE_CONFIANCA, maxRestricao, type PoliticaCompilada } from "./regras.ts";
import type { Decisao, EntradaDoScreen, Origem, ResultadoDoScreen, SujeitoTipo } from "./tipos.ts";

/** A regra que diz que o classificador falhou e a decisão ficou `condicional`. */
export const REGRA_CLASSIFICADOR_INDISPONIVEL = "classificador_indisponivel";
/** A regra que diz que o classificador subiu a decisão das regras. */
export const REGRA_CLASSIFICADOR = "classificador";

/** Uma linha de `platform.screening_decision`, na forma do escritor. */
export interface LinhaDeDecisao {
  readonly tenantId: string;
  readonly onboardingId: string | null;
  readonly sujeitoTipo: SujeitoTipo;
  readonly sujeitoRef: string;
  readonly decisao: Decisao;
  readonly regras: readonly string[];
  readonly versaoPolitica: string;
  readonly origem: Origem;
  /** sha256 da entrada canónica: a decisão vale para **este** conteúdo. */
  readonly conteudoSha256: Uint8Array;
}

/** Grava uma decisão. *Append-only*: não há método de alterar nem de apagar. */
export interface EscritorDeDecisoes {
  gravar(linha: LinhaDeDecisao): Promise<void>;
}

/** As decisões gravadas para uma chave, pela ordem em que foram gravadas. */
export interface LeitorDeDecisoes {
  decisoes(chave: ChaveDaDecisao): Promise<readonly { readonly decisao: Decisao; readonly origem: Origem }[]>;
}

export interface ChaveDaDecisao {
  readonly tenantId: string;
  readonly sujeitoTipo: SujeitoTipo;
  readonly sujeitoRef: string;
  readonly versaoPolitica: string;
  readonly conteudoSha256: Uint8Array;
}

export interface Sujeito {
  readonly tenantId: string;
  readonly onboardingId?: string | null;
  readonly sujeitoTipo: SujeitoTipo;
  readonly sujeitoRef: string;
}

export interface DependenciasDoScreen {
  readonly politica: PoliticaCompilada;
  /** `null` quando o alias não está ligado: conta como indisponível. */
  readonly classificador: ClassificadorDeCategorias | null;
  readonly escritor: EscritorDeDecisoes;
}

/**
 * O sha256 da entrada, em JSON canónico. É o texto **cru**, e não o
 * normalizado: mudar um acento muda o conteúdo publicado, e a decisão tem de
 * ser sobre o que o cliente vai ler.
 */
export function conteudoSha256(entrada: EntradaDoScreen): Uint8Array {
  const canonico = JSON.stringify([entrada.categoria_declarada, [...entrada.textos]]);
  return new Uint8Array(createHash("sha256").update(canonico, "utf8").digest());
}

async function consultar(
  classificador: ClassificadorDeCategorias | null,
  entrada: EntradaDoScreen,
): Promise<VeredictoDoClassificador | null> {
  if (classificador === null) return null;
  try {
    // O veredicto lê-se aqui outra vez, venha de que adaptador vier: a porta é
    // um contrato de tipos, e um adaptador que devolva `{decisao: "x"}` não
    // pode chegar ao `maxRestricao` (o `grau` de uma decisão desconhecida é -1,
    // e passava por `permitida`).
    return lerVeredicto(
      await classificador.classificar(prepararPedido(entrada.categoria_declarada, entrada.textos)),
    );
  } catch {
    // Qualquer falha — rede, tempo, resposta fora do esquema — é «sem
    // veredicto», e sem veredicto a decisão não fica `permitida`.
    return null;
  }
}

export async function screen(
  sujeito: Sujeito,
  entrada: EntradaDoScreen,
  dependencias: DependenciasDoScreen,
): Promise<ResultadoDoScreen> {
  const regras = avaliarRegras(dependencias.politica, entrada.categoria_declarada, entrada.textos);
  let decisao = regras.decisao;
  let lista = [...regras.regras];
  let confianca = regras.confianca;
  let origem: Origem = "regra";

  if (decisao === "permitida" && confianca < LIMIAR_DE_CONFIANCA) {
    const veredicto = await consultar(dependencias.classificador, entrada);
    if (veredicto === null) {
      decisao = "condicional";
      lista = [...lista, REGRA_CLASSIFICADOR_INDISPONIVEL];
      confianca = 0;
    } else {
      const final = maxRestricao(decisao, tecto(veredicto.decisao));
      if (final !== decisao) {
        decisao = final;
        lista = [...lista, REGRA_CLASSIFICADOR];
        origem = "llm";
      }
      confianca = veredicto.confianca;
    }
  }

  await dependencias.escritor.gravar({
    tenantId: sujeito.tenantId,
    onboardingId: sujeito.onboardingId ?? null,
    sujeitoTipo: sujeito.sujeitoTipo,
    sujeitoRef: sujeito.sujeitoRef,
    decisao,
    regras: lista,
    versaoPolitica: dependencias.politica.versao,
    origem,
    conteudoSha256: conteudoSha256(entrada),
  });
  return { decisao, regras: lista, versao_politica: dependencias.politica.versao, confianca };
}

/** O produto não pode ser publicado. `motivo` é um identificador fechado, sem texto do produto. */
export class NaoPublicavelError extends Error {
  readonly motivo: "sem_decisao" | "bloqueada" | "por_rever";

  constructor(motivo: NaoPublicavelError["motivo"]) {
    super(`produto nao publicavel: ${motivo}`);
    this.name = "NaoPublicavelError";
    this.motivo = motivo;
  }
}

export interface ProdutoAPublicar {
  readonly tenantId: string;
  /** O `sku` do `offer_terms`. */
  readonly ref: string;
  readonly entrada: EntradaDoScreen;
}

/**
 * Falha fechado se o produto não tiver decisão `permitida` válida para a
 * versão corrente da política **e** para o conteúdo que vai ser publicado.
 *
 * Três recusas, e a ordem importa: sem decisão nenhuma; uma `bloqueada` em
 * qualquer linha da chave — final, nem uma revisão humana posterior a desce;
 * a última linha não `permitida` — uma `condicional` espera pela revisão
 * (KAM-089), que grava `origem = 'humano'`. Um erro do leitor sobe: não ter
 * conseguido ler não é ter lido «pode».
 */
export async function assertPublishable(
  produto: ProdutoAPublicar,
  dependencias: { readonly politica: PoliticaCompilada; readonly leitor: LeitorDeDecisoes },
): Promise<void> {
  const linhas = await dependencias.leitor.decisoes({
    tenantId: produto.tenantId,
    sujeitoTipo: "produto",
    sujeitoRef: produto.ref,
    versaoPolitica: dependencias.politica.versao,
    conteudoSha256: conteudoSha256(produto.entrada),
  });
  if (linhas.length === 0) throw new NaoPublicavelError("sem_decisao");
  if (linhas.some((l) => l.decisao === "bloqueada")) throw new NaoPublicavelError("bloqueada");
  if (linhas[linhas.length - 1]!.decisao !== "permitida") throw new NaoPublicavelError("por_rever");
}
