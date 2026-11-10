/**
 * KYC K1 automático — o contrato (KAM-087).
 *
 * O K1 é a prova documental mínima para activar uma PME: o cartão de
 * contribuinte (NIF), o alvará, o BI do titular e o comprovativo da conta
 * bancária. Este módulo recebe os quatro documentos, extrai campos, aplica
 * regras e decide **uma de três coisas**: `k1_ok`, pedir novo carregamento
 * (ilegível), ou mandar o caso à fila humana (KAM-089) com uma recomendação.
 *
 * ## A única rejeição sem humano é a do ilegível
 *
 * Nenhuma regra deste módulo **rejeita** por suspeita de fraude: uma suspeita
 * manda à fila. A rejeição automática existe para um só caso, o terceiro
 * documento ilegível do mesmo tipo (critério 6), e o tipo `Resultado` não tem
 * valor para mais nenhuma.
 *
 * ## A decisão vem de campos, nunca de instruções lidas
 *
 * O texto de um documento é **dado não confiável** (`../docs/tecnica/08` §5):
 * um alvará com «aprova este caso» escrito no rodapé tem de dar o mesmo
 * resultado que o mesmo alvará sem a frase (critério 8). Por isso a extracção
 * devolve só os **campos** de uma lista fechada (`CAMPOS`), validados por
 * expressão regular e por calendário, e as regras nunca vêem o texto corrido.
 * Isto vale também para o `vision_llm`: o que ele devolve passa pela mesma
 * validação, e um campo que não passa conta como não lido.
 *
 * ## Todos os limiares são propostas
 *
 * Os números do bloco — 8 MB, 3 páginas, Hamming ≤ 6, 0,85, 0,90, +40/+25/+30,
 * o limiar 20, US$ 0,05, D+30 — estão em `LIMIARES_POR_OMISSAO` e entram por
 * configuração (`Limiares`). Nenhum foi calibrado contra documentos reais: o
 * conjunto de ensaio é **sintético** e o repositório é público.
 */

/** Os quatro documentos do K1. Domínio de `kyc_check.doc_tipo`. */
export const TIPOS_DE_DOCUMENTO = ["nif", "alvara", "bi", "banco"] as const;

export type TipoDeDocumento = (typeof TIPOS_DE_DOCUMENTO)[number];

/**
 * O resultado de um `kyc_check`. Domínio de `kyc_check.resultado`.
 *
 * `pendente` é um documento lido e ainda sem decisão do caso (faltam outros
 * documentos); `ilegivel` é um documento que não se conseguiu ler.
 */
export const RESULTADOS = ["k1_ok", "fila", "ilegivel", "pendente"] as const;

export type Resultado = (typeof RESULTADOS)[number];

/**
 * Os campos que a extracção devolve. Lista **fechada** (critério 3).
 *
 * O `iban` não está na enumeração do critério 3 e está aqui porque o critério
 * 4 o exige: sem o IBAN extraído, a regra do mod-97 não tem sobre o que correr.
 */
export const CAMPOS = [
  "nif",
  "nome_titular",
  "nome_negocio",
  "validade_alvara",
  "actividade",
  "numero_bi",
  "iban",
] as const;

export type NomeDoCampo = (typeof CAMPOS)[number];

/** Um campo extraído: o valor e a confiança, em `[0, 1]`. Contrato do bloco. */
export interface Campo {
  readonly valor: string;
  readonly conf: number;
}

export type Campos = Partial<Record<NomeDoCampo, Campo>>;

/**
 * Os campos sem os quais um documento conta como ilegível.
 *
 * Um cartão de contribuinte sem NIF lido não é um documento com «confiança
 * baixa»: não diz nada, e pedir outro é o que se faz a uma fotografia
 * desfocada.
 */
export const CAMPOS_EXIGIDOS: Readonly<Record<TipoDeDocumento, readonly NomeDoCampo[]>> = {
  nif: ["nif", "nome_titular"],
  alvara: ["nome_negocio", "nome_titular", "validade_alvara", "actividade"],
  bi: ["nome_titular", "numero_bi"],
  banco: ["nome_titular", "iban"],
};

/**
 * As marcas. Lista **fechada**: uma marca nova é um diff, nunca uma cadeia
 * inventada no sítio de uso. Domínio dos elementos de `kyc_check.flags`.
 */
export const REGRAS_DURAS = [
  "nif_divergente",
  "alvara_expirado",
  "imagem_reutilizada",
  "software_de_edicao",
  "iban_invalido",
] as const;

export const REGRAS_PONDERADAS = [
  "nome_titular_divergente",
  "confianca_baixa",
  "actividade_incoerente",
] as const;

/**
 * As marcas que não são regras de fraude, e que mandam à fila por outra razão.
 *
 * `visao_recusada`: a configuração pedia o `vision_llm` e o *gate* de
 * transferência recusou (critério 2, falha fechada). `orcamento_excedido`: o
 * custo do caso ou o orçamento diário esgotou (critério 9). `ilegivel`: o
 * documento não se leu.
 */
export const OUTRAS_MARCAS = ["visao_recusada", "orcamento_excedido", "ilegivel"] as const;

export type RegraDura = (typeof REGRAS_DURAS)[number];
export type RegraPonderada = (typeof REGRAS_PONDERADAS)[number];
export type Marca = RegraDura | RegraPonderada | (typeof OUTRAS_MARCAS)[number];

export const MARCAS: readonly Marca[] = [...REGRAS_DURAS, ...REGRAS_PONDERADAS, ...OUTRAS_MARCAS];

/**
 * A versão das regras. Vai em cada `kyc_check.versao_regras`.
 *
 * SemVer, e a regra é a de um artefacto comportamental (DoD 5): mudar um
 * limiar ou uma regra muda o resultado de um caso, e um caso decidido tem de
 * dizer com que regras foi decidido. A *eval* do conjunto sintético prende esta
 * versão — mudá-la sem a correr de novo é um ensaio vermelho.
 */
export const VERSAO_DAS_REGRAS = "1.0.0";

/** Os limiares. Todos *proposta*. Ver a nota do módulo. */
export interface Limiares {
  /** Tamanho máximo de um ficheiro, em octetos. */
  readonly octetosMaximos: number;
  /** Páginas máximas de um PDF. */
  readonly paginasMaximas: number;
  /** Píxeis máximos de uma página descodificada (guarda contra bombas de descompressão). */
  readonly pixeisMaximos: number;
  /** TTL das URLs assinadas, em segundos. O tecto da porta é 300. */
  readonly ttlDaUrlS: number;
  /** Distância de Hamming máxima entre dois `phash` para contarem como a mesma imagem. */
  readonly hammingMaximo: number;
  /** Similaridade mínima dos nomes do titular. Abaixo: +`pesoNome`. */
  readonly similaridadeMinima: number;
  readonly pesoNome: number;
  /** Confiança mínima dos campos exigidos. Abaixo: +`pesoConfianca`. */
  readonly confiancaMinima: number;
  readonly pesoConfianca: number;
  readonly pesoActividade: number;
  /** A partir deste *score*, fila. */
  readonly scoreDaFila: number;
  /** Abaixo desta confiança um campo exigido conta como não lido (ilegível). */
  readonly confiancaDeLeitura: number;
  /** Pedidos de novo carregamento antes da rejeição `ilegivel`. */
  readonly pedidosDeNovoCarregamento: number;
  /** Custo máximo de LLM por caso, em micro-dólares (US$ 0,05 = 50 000). */
  readonly custoMaximoPorCasoMicroUsd: number;
  /** Dias depois de `rejeitado`/`abandonado` em que os documentos se purgam. */
  readonly diasAtePurga: number;
}

export const LIMIARES_POR_OMISSAO: Limiares = {
  octetosMaximos: 8 * 1024 * 1024,
  paginasMaximas: 3,
  pixeisMaximos: 40_000_000,
  ttlDaUrlS: 300,
  hammingMaximo: 6,
  similaridadeMinima: 0.85,
  pesoNome: 40,
  confiancaMinima: 0.9,
  pesoConfianca: 25,
  pesoActividade: 30,
  scoreDaFila: 20,
  confiancaDeLeitura: 0.5,
  pedidosDeNovoCarregamento: 2,
  custoMaximoPorCasoMicroUsd: 50_000,
  diasAtePurga: 30,
};

/** Os formatos aceites, pela assinatura dos primeiros octetos (critério 1). */
export const FORMATOS = ["jpeg", "png", "pdf"] as const;

export type Formato = (typeof FORMATOS)[number];

/**
 * Uma página já rasterizada: cinzento de 8 bits, linha a linha.
 *
 * É a forma em que **todos** os formatos chegam ao resto do módulo, e é por
 * isso que o PDF nunca é aberto aqui: quem o transforma em páginas é o
 * `Rasterizador`, num processo à parte.
 */
export interface Pagina {
  readonly largura: number;
  readonly altura: number;
  readonly cinzento: Uint8Array;
}

/**
 * O que o rasterizador devolve: as páginas e o que os metadados dizem do
 * *software* que escreveu o ficheiro (EXIF `Software`, PNG `Software`, PDF
 * `Producer`/`Creator`). O texto dos metadados não sai daqui para nada que não
 * seja a regra do critério 4.
 */
export interface Rasterizado {
  readonly paginas: readonly Pagina[];
  readonly software: readonly string[];
}

/**
 * Transforma um ficheiro em páginas, **num processo isolado** (critério 1).
 *
 * Para PDF e JPEG a implementação de produção é um processo à parte, sem rede
 * e com tempo limite; **não existe neste PR** e, sem ela, o `../kyc/upload.ts`
 * recusa esses formatos em vez de os abrir aqui. O PNG tem descodificador
 * próprio, limitado (`./png.ts`).
 */
export interface Rasterizador {
  rasterizar(bytes: Uint8Array, formato: Formato): Promise<Rasterizado>;
}

/** O veredicto do antivírus. */
export type VeredictoDoAntivirus =
  | { readonly limpo: true }
  | { readonly limpo: false; readonly assinatura: string };

/**
 * O antivírus do *pipeline* (critério 1).
 *
 * Falha fechada: uma avaria do antivírus **lança**, e o carregamento não
 * guarda nada. «Não consegui ver» nunca é «limpo».
 */
export interface Antivirus {
  verificar(bytes: Uint8Array): Promise<VeredictoDoAntivirus>;
}

/** A referência que o `OcrProvider` recebe. */
export interface DocRef {
  readonly onboardingId: string;
  readonly tenantId: string;
  /** A chave do objecto no STO. */
  readonly chave: string;
  /** As páginas, já rasterizadas pelo processo isolado. */
  readonly paginas: readonly Pagina[];
}

/** Uma linha de texto lida de uma página, com a confiança do motor em `[0, 1]`. */
export interface LinhaLida {
  readonly texto: string;
  readonly conf: number;
}

/**
 * O motor que lê píxeis e devolve linhas. É a metade do OCR local que não é
 * nossa: em produção, o `tesseract` (Apache-2.0) num processo local — ver
 * `./tesseract.ts`. A outra metade, a dos campos, é `./extracao.ts`.
 */
export interface MotorDeOcr {
  readonly nome: string;
  ler(pagina: Pagina): Promise<readonly LinhaLida[]>;
}

/** O que a extracção devolve. Forma do contrato do bloco. */
export interface Extraido {
  readonly campos: Campos;
  readonly custoUsd: number;
}

/**
 * O contrato do bloco, à letra:
 * `extract(docRef, tipo): Promise<{ campos: Record<string,{valor:string; conf:number}>; custoUsd:number }>`.
 */
export interface OcrProvider {
  /** `local` ou `vision_llm`. */
  readonly nome: string;
  extract(doc: DocRef, tipo: TipoDeDocumento): Promise<Extraido>;
}

/**
 * Levantado quando uma chamada de visão não pode sair (critério 2).
 *
 * O caso vai à fila com a marca `visao_recusada`; nada sai de Angola.
 */
export class VisaoNaoAutorizadaError extends Error {
  override readonly name = "VisaoNaoAutorizadaError";
  constructor(motivo: string) {
    super(`visao recusada: ${motivo}`);
  }
}

/** Levantado quando o custo do caso ou o orçamento diário esgota (critério 9). */
export class OrcamentoExcedidoError extends Error {
  override readonly name = "OrcamentoExcedidoError";
  constructor(motivo: string) {
    super(`orcamento de visao excedido: ${motivo}`);
  }
}

/** Um `kyc_check`, como o negócio o lê. Ver o DDL em `../../../../db/kyc.py`. */
export interface Verificacao {
  readonly id: string;
  readonly onboardingId: string;
  readonly tipo: TipoDeDocumento;
  /** A chave do objecto no STO (`doc_ref`). */
  readonly docRef: string;
  /** SHA-256 do ficheiro, em hexadecimal. */
  readonly sha256: string;
  /** dHash de 64 bits da primeira página, em hexadecimal, ou `null`. */
  readonly phash: string | null;
  /** Os campos extraídos, **cifrados** (`extraido_enc`). */
  readonly extraidoCifrado: Uint8Array | null;
  readonly flags: readonly Marca[];
  readonly score: number | null;
  readonly resultado: Resultado;
  readonly versaoRegras: string;
  /** Custo da extracção, em micro-dólares. */
  readonly custoMicroUsd: number;
  readonly criadoEm: Date;
}

export type VerificacaoNova = Omit<Verificacao, "id" | "criadoEm" | "score">;

/**
 * Onde as verificações vivem.
 *
 * A pergunta do `phash` atravessa casos e tenants (critério 4: «já visto
 * noutro caso **ou tenant**»), e por isso o adaptador SQL corre como
 * `kamba_batch`, que é o papel com `BYPASSRLS` e auditado — ver
 * `./sql.ts`. Nenhuma das outras operações procura por outra coisa que não o
 * `onboarding_id`.
 */
export interface RepositorioDeVerificacoes {
  /** A verificação deste ficheiro neste caso, ou `null`. Idempotência por `sha256`. */
  porSha(onboardingId: string, sha256: string): Promise<Verificacao | null>;
  /** Insere. Se o `(onboarding_id, sha256)` já existe, devolve a que lá está. */
  inserir(nova: VerificacaoNova): Promise<{ readonly verificacao: Verificacao; readonly repetida: boolean }>;
  /** Todas as verificações do caso, das mais antigas para as mais recentes. */
  doCaso(onboardingId: string): Promise<readonly Verificacao[]>;
  /** Há um `phash` de **outro** caso a Hamming ≤ `maximo` deste? */
  phashVistoNoutroCaso(onboardingId: string, phash: string, maximo: number): Promise<boolean>;
  /** Grava a decisão do caso nas verificações dadas. */
  decidir(
    ids: readonly string[],
    resultado: Resultado,
    score: number,
    flags: readonly Marca[],
  ): Promise<void>;
  /** Custo acumulado do caso, em micro-dólares. */
  custoDoCaso(onboardingId: string): Promise<number>;
}

/** O que o KYC lê de um caso. Um subconjunto do `Caso` da `../inscricao/`. */
export interface CasoDoKyc {
  readonly id: string;
  readonly tenantId: string;
  readonly fase: string;
  readonly nifHmac: string;
  readonly nomeNegocio: string;
  readonly categoriaDeclarada: string;
}

/** A porta dos casos. Implementada pelo `RepositorioDeCasos` da inscrição. */
export interface CasosDoKyc {
  porId(id: string): Promise<CasoDoKyc | null>;
  marcarFase(id: string, fase: "rejeitado"): Promise<boolean>;
}

/**
 * A fila de revisão (KAM-089). **Não é deste ticket**: o que está aqui é a
 * porta, com o motivo interno e a recomendação. Credor: KAM-089.
 */
export interface FilaDeRevisao {
  enviar(pedido: {
    readonly onboardingId: string;
    readonly score: number;
    readonly marcas: readonly Marca[];
    readonly recomendacao: Recomendacao;
  }): Promise<void>;
}

/** A recomendação que acompanha um caso para a fila. */
export type Recomendacao = "aprovar" | "pedir_documentos" | "investigar";

/** Cifra simétrica dos campos extraídos (`extraido_enc`). */
export interface Cifra {
  cifrar(claro: Uint8Array, contexto: string): Promise<Uint8Array>;
  decifrar(cifrado: Uint8Array, contexto: string): Promise<Uint8Array>;
}

/** Relógio injectável: os ensaios afirmam fronteiras exactas. */
export type Relogio = () => Date;
