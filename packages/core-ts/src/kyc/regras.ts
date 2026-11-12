/**
 * As regras do K1 e o *score* (KAM-087, critérios 4 e 5).
 *
 * Funções puras sobre campos já validados. Nenhuma lê texto do documento,
 * nenhuma lê relógio (o `hoje` vem de fora) e nenhuma rejeita: o pior que uma
 * regra faz é mandar o caso à fila.
 *
 *     duras       nif_divergente, alvara_expirado, imagem_reutilizada,
 *                 software_de_edicao, iban_invalido           => sempre fila
 *     ponderadas  nome_titular_divergente +40, confianca_baixa +25,
 *                 actividade_incoerente +30                     (propostas)
 *     decisão     score < 20 e sem dura => k1_ok; senão fila
 */

import { Nif } from "../inscricao/identificadores.ts";

import {
  CAMPOS_EXIGIDOS,
  REGRAS_DURAS,
  TIPOS_DE_DOCUMENTO,
  type Campos,
  type Limiares,
  type Marca,
  type NomeDoCampo,
  type Recomendacao,
  type Resultado,
  type TipoDeDocumento,
} from "./contrato.ts";
import { normalizarNome } from "./extracao.ts";

/** O IBAN passa o mod-97 da ISO 13616? Espera a forma já sem espaços. */
export function ibanValido(iban: string): boolean {
  if (!/^[A-Z]{2}[0-9]{2}[A-Z0-9]{11,30}$/.test(iban)) return false;
  const rodado = iban.slice(4) + iban.slice(0, 4);
  let resto = 0;
  for (const c of rodado) {
    const v = c >= "A" ? String(c.charCodeAt(0) - 55) : c;
    for (const d of v) resto = (resto * 10 + Number(d)) % 97;
  }
  return resto === 1;
}

/** Jaro-Winkler clássico, em `[0, 1]`. */
export function jaroWinkler(a: string, b: string): number {
  if (a === b) return 1;
  if (a.length === 0 || b.length === 0) return 0;
  const janela = Math.max(0, Math.floor(Math.max(a.length, b.length) / 2) - 1);
  const ma = new Array<boolean>(a.length).fill(false);
  const mb = new Array<boolean>(b.length).fill(false);
  let iguais = 0;
  for (let i = 0; i < a.length; i++) {
    const de = Math.max(0, i - janela);
    const ate = Math.min(b.length - 1, i + janela);
    for (let j = de; j <= ate; j++) {
      if (!mb[j] && a[i] === b[j]) {
        ma[i] = mb[j] = true;
        iguais++;
        break;
      }
    }
  }
  if (iguais === 0) return 0;
  let k = 0;
  let trocas = 0;
  for (let i = 0; i < a.length; i++) {
    if (!ma[i]) continue;
    while (!mb[k]) k++;
    if (a[i] !== b[k]) trocas++;
    k++;
  }
  const jaro = (iguais / a.length + iguais / b.length + (iguais - trocas / 2) / iguais) / 3;
  let prefixo = 0;
  while (prefixo < 4 && a[prefixo] === b[prefixo]) prefixo++;
  return jaro + prefixo * 0.1 * (1 - jaro);
}

/**
 * A similaridade de dois nomes de pessoa: o máximo do Jaro-Winkler sobre o
 * nome normalizado e sobre as palavras ordenadas. A segunda forma existe
 * porque «Pedro Manuel» e «Manuel Pedro» são a mesma pessoa escrita por duas
 * repartições, e o Jaro-Winkler sozinho dá-lhes menos de 0,85.
 */
export function similaridadeDeNomes(a: string, b: string): number {
  const na = normalizarNome(a);
  const nb = normalizarNome(b);
  const ordenar = (s: string): string => s.split(" ").sort().join(" ");
  return Math.max(jaroWinkler(na, nb), jaroWinkler(ordenar(na), ordenar(nb)));
}

/**
 * As famílias de categoria e as palavras de actividade que lhes são coerentes.
 * ***Proposta***, e sem calibração: o domínio de `categoria_declarada` é texto
 * livre (KAM-086) e a lista de categorias é do KAM-088. A família `geral` é a
 * actividade que serve a qualquer categoria de comércio.
 */
export const FAMILIAS: Readonly<Record<string, { readonly categoria: readonly string[]; readonly actividade: readonly string[] }>> = {
  moda: {
    categoria: ["MODA", "ROUPA", "VESTUARIO", "CALCADO", "ACESSORIOS"],
    actividade: ["VESTUARIO", "ROUPA", "CALCADO", "MODA", "CONFECCAO", "TEXTIL", "ACESSORIOS"],
  },
  mercearia: {
    categoria: ["MERCEARIA", "ALIMENTACAO", "SUPERMERCADO", "CONGELADOS"],
    actividade: ["MERCEARIA", "ALIMENTAR", "ALIMENTACAO", "GENEROS ALIMENTICIOS", "CONGELADOS"],
  },
  restauracao: {
    categoria: ["RESTAURANTE", "RESTAURACAO", "COMIDA", "PASTELARIA", "PADARIA"],
    actividade: ["RESTAURACAO", "RESTAURANTE", "PASTELARIA", "PADARIA", "SERVICO DE REFEICOES"],
  },
  beleza: {
    categoria: ["BELEZA", "CABELEIREIRO", "ESTETICA", "SALAO", "COSMETICA"],
    actividade: ["CABELEIREIRO", "ESTETICA", "BELEZA", "COSMETICA", "SALAO"],
  },
  electronica: {
    categoria: ["ELECTRONICA", "ELETRONICA", "TELEMOVEIS", "INFORMATICA", "ELECTRODOMESTICOS"],
    actividade: ["ELECTRONICA", "ELETRONICA", "TELEMOVEIS", "INFORMATICA", "ELECTRODOMESTICOS", "TELECOMUNICACOES"],
  },
  geral: {
    categoria: [],
    actividade: ["COMERCIO GERAL", "COMERCIO A GROSSO E A RETALHO"],
  },
};

/**
 * A actividade do alvará é coerente com a categoria declarada?
 *
 * `null` quando a categoria não cai em família nenhuma: **não se avalia**, e
 * isso não soma nada. A alternativa — contar uma categoria desconhecida como
 * incoerente — mandava à fila todo o negócio cuja categoria a lista ainda não
 * tem, e a fila não é sítio para corrigir uma lista.
 */
export function actividadeCoerente(categoria: string, actividade: string): boolean | null {
  const c = normalizarNome(categoria);
  const a = normalizarNome(actividade);
  if (FAMILIAS["geral"]!.actividade.some((p) => a.includes(p))) return true;
  const familias = Object.values(FAMILIAS).filter((f) => f.categoria.some((p) => c.includes(p)));
  if (familias.length === 0) return null;
  return familias.some((f) => f.actividade.some((p) => a.includes(p)));
}

/** O que as regras recebem, por documento. */
export interface DocumentoLido {
  readonly campos: Campos;
  readonly invalidos: readonly NomeDoCampo[];
  /** As marcas que se decidiram sobre o ficheiro: `imagem_reutilizada`, `software_de_edicao`, … */
  readonly marcas: readonly Marca[];
}

export interface EntradaDasRegras {
  readonly documentos: Readonly<Record<TipoDeDocumento, DocumentoLido>>;
  /** O `nif_hmac` do caso: o NIF declarado nunca se lê em claro aqui. */
  readonly nifHmacDeclarado: string;
  /** O anel de chaves do HMAC do NIF, a actual primeiro. */
  readonly anelDoNif: readonly (Uint8Array | null)[];
  readonly categoriaDeclarada: string;
  /** A data de hoje em `Africa/Luanda`, `aaaa-mm-dd`. */
  readonly hoje: string;
  readonly limiares: Limiares;
}

export interface Avaliacao {
  readonly marcas: readonly Marca[];
  readonly score: number;
  readonly resultado: Extract<Resultado, "k1_ok" | "fila">;
  readonly recomendacao: Recomendacao;
}

/** O NIF lido corresponde ao declarado? Pelos HMAC do anel, sem decifrar nada. */
function nifCorresponde(valor: string, entrada: EntradaDasRegras): boolean {
  try {
    return new Nif(valor, entrada.anelDoNif).hmacs.includes(entrada.nifHmacDeclarado);
  } catch {
    return false;
  }
}

/** Aplica as regras. Ver a nota do módulo. */
export function avaliar(entrada: EntradaDasRegras): Avaliacao {
  const { documentos: d, limiares: l } = entrada;
  const marcas = new Set<Marca>();
  for (const tipo of TIPOS_DE_DOCUMENTO) for (const m of d[tipo].marcas) marcas.add(m);

  // nif_divergente: o do cartão e, se o alvará o trouxer, o do alvará.
  const nifs = [d.nif.campos.nif, d.alvara.campos.nif].filter((c) => c !== undefined);
  if (d.nif.invalidos.includes("nif") || nifs.some((c) => !nifCorresponde(c.valor, entrada))) {
    marcas.add("nif_divergente");
  }

  const validade = d.alvara.campos.validade_alvara;
  if (validade !== undefined && validade.valor < entrada.hoje) marcas.add("alvara_expirado");

  const iban = d.banco.campos.iban;
  if (d.banco.invalidos.includes("iban") || (iban !== undefined && !ibanValido(iban.valor))) {
    marcas.add("iban_invalido");
  }

  let score = 0;
  const referencia = d.bi.campos.nome_titular?.valor;
  const outros = [d.alvara.campos.nome_titular?.valor, d.banco.campos.nome_titular?.valor];
  if (
    referencia !== undefined &&
    outros.some((n) => n !== undefined && similaridadeDeNomes(referencia, n) < l.similaridadeMinima)
  ) {
    marcas.add("nome_titular_divergente");
    score += l.pesoNome;
  }

  const confiancas: number[] = [];
  let invalido = false;
  for (const tipo of TIPOS_DE_DOCUMENTO) {
    for (const c of CAMPOS_EXIGIDOS[tipo]) {
      const campo = d[tipo].campos[c];
      if (campo !== undefined) confiancas.push(campo.conf);
    }
    if (d[tipo].invalidos.length > 0) invalido = true;
  }
  if (invalido || Math.min(...confiancas) < l.confiancaMinima) {
    marcas.add("confianca_baixa");
    score += l.pesoConfianca;
  }

  const actividade = d.alvara.campos.actividade;
  if (actividade !== undefined && actividadeCoerente(entrada.categoriaDeclarada, actividade.valor) === false) {
    marcas.add("actividade_incoerente");
    score += l.pesoActividade;
  }

  const lista = [...marcas].sort();
  const dura = lista.some((m) => (REGRAS_DURAS as readonly string[]).includes(m));
  const fila =
    dura || score >= l.scoreDaFila || marcas.has("visao_recusada") || marcas.has("orcamento_excedido");
  return { marcas: lista, score, resultado: fila ? "fila" : "k1_ok", recomendacao: recomendar(lista, fila) };
}

/**
 * As marcas que pedem investigação e não documentos novos. A `actividade_incoerente`
 * está aqui: é o vector «declarar moda e vender álcool» do KAM-088, e um
 * «aprovar» como recomendação dela era o T&S a ler o contrário do risco.
 */
const SINAIS_DE_FRAUDE: readonly Marca[] = [
  "nif_divergente",
  "imagem_reutilizada",
  "software_de_edicao",
  "nome_titular_divergente",
  "actividade_incoerente",
];

function recomendar(marcas: readonly Marca[], fila: boolean): Recomendacao {
  if (!fila) return "aprovar";
  if (marcas.some((m) => SINAIS_DE_FRAUDE.includes(m))) return "investigar";
  if (marcas.some((m) => m === "alvara_expirado" || m === "iban_invalido" || m === "confianca_baixa")) {
    return "pedir_documentos";
  }
  return "aprovar";
}

/**
 * Os motivos que se mostram ao dono (critério 7). Lista fechada.
 *
 * Só o **corrigível** é específico: o ilegível e o expirado. Tudo o que é
 * sinal de fraude sai como `nao_foi_possivel_validar`, e o motivo interno fica
 * só para o T&S — dizer «o NIF não bate» a quem falsificou o documento é
 * ensinar-lhe o que corrigir na próxima tentativa.
 */
export const MOTIVOS_PUBLICOS = ["ilegivel", "alvara_expirado", "nao_foi_possivel_validar"] as const;

export type MotivoPublico = (typeof MOTIVOS_PUBLICOS)[number];

export const TEXTO_DO_MOTIVO: Readonly<Record<MotivoPublico, string>> = {
  ilegivel:
    "Não conseguimos ler o documento. Envie uma fotografia nítida, com o documento inteiro e boa luz.",
  alvara_expirado: "O alvará enviado está fora da validade. Envie o alvará em vigor.",
  nao_foi_possivel_validar:
    "Não foi possível validar os documentos. A nossa equipa vai analisar o pedido.",
};

/**
 * O motivo público de uma fila. **O específico só sai quando é o único**: um
 * alvará expirado com uma imagem reutilizada dá o genérico, senão o dono
 * corrigia a data e voltava com a mesma imagem.
 */
export function motivoPublico(marcas: readonly Marca[]): MotivoPublico {
  const so = (permitidas: readonly Marca[]): boolean =>
    marcas.length > 0 && marcas.every((m) => permitidas.includes(m));
  if (so(["ilegivel"])) return "ilegivel";
  if (so(["alvara_expirado"])) return "alvara_expirado";
  return "nao_foi_possivel_validar";
}
