/**
 * O caso de uso do K1 (KAM-087): receber um documento, decidir o caso,
 * entregar um documento ao T&S e purgar os casos mortos.
 *
 *     receber   assinatura → tamanho → sha256 (idempotência) → antivírus
 *               → rasterizar (PNG aqui; PDF/JPEG só por processo isolado)
 *               → páginas → STO → forense → OCR → validação → kyc_check
 *     decidir   o último documento legível de cada tipo → regras → score
 *               → k1_ok | fila (KAM-089), com motivo público e recomendação
 *
 * O ilegível decide-se no `receber`, documento a documento: o terceiro
 * ilegível do mesmo tipo rejeita o caso (critério 6), e é a única rejeição sem
 * humano deste módulo.
 */

import { createHash } from "node:crypto";

import { novaChave, type StorageProvider } from "../storage/index.ts";

import { detectarFormato, dhash, softwareDeEdicao, softwareDoJpeg } from "./forense.ts";
import { validarCampos, type Formas, FORMAS_POR_OMISSAO } from "./extracao.ts";
import { descodificarPng, FicheiroInvalidoError } from "./png.ts";
import { avaliar, motivoPublico, type Avaliacao, type DocumentoLido, type MotivoPublico } from "./regras.ts";
import {
  CAMPOS_EXIGIDOS,
  LIMIARES_POR_OMISSAO,
  OrcamentoExcedidoError,
  TIPOS_DE_DOCUMENTO,
  VERSAO_DAS_REGRAS,
  VisaoNaoAutorizadaError,
  type Antivirus,
  type Campos,
  type CasosDoKyc,
  type Cifra,
  type FilaDeRevisao,
  type Formato,
  type Limiares,
  type Marca,
  type NomeDoCampo,
  type OcrProvider,
  type Rasterizado,
  type Rasterizador,
  type Relogio,
  type RepositorioDeVerificacoes,
  type TipoDeDocumento,
  type Verificacao,
} from "./contrato.ts";

/** A classe de retenção dos documentos no STO. */
export const CLASSE_DO_DOCUMENTO = "kyc_documento";

/**
 * O `retain_until` que o STO exige a cada objecto (KAM-011).
 *
 * shortcut: dez anos é um tecto e não a retenção. A retenção de um caso vivo é
 * a do tenant (KAM-071/098) e a de um morto são os D+30 de `purgar`, e nenhuma
 * das duas se sabe no carregamento — o metadado não se reescreve. Revê-se
 * quando a política do KAM-071 der uma classe a estes documentos.
 */
export const DIAS_DO_TECTO_NO_STO = 3650;

/** As fases do caso em que se aceitam documentos. */
export const FASES_QUE_RECEBEM: readonly string[] = ["kyc_pendente"];

/** As fases mortas cujos documentos se purgam (critério 10). */
export const FASES_PURGAVEIS: readonly string[] = ["rejeitado", "abandonado"];

/** Porque é que um carregamento foi recusado antes de ser lido. */
export type MotivoDaRecusa = "caso" | "formato" | "tamanho" | "paginas" | "antivirus";

export type Recebido =
  | { readonly estado: "recusado"; readonly motivo: MotivoDaRecusa }
  | { readonly estado: "lido"; readonly verificacao: Verificacao; readonly repetido: boolean }
  | {
      readonly estado: "novo_carregamento";
      readonly verificacao: Verificacao;
      readonly restantes: number;
      readonly motivoPublico: "ilegivel";
    }
  | { readonly estado: "rejeitado"; readonly verificacao: Verificacao; readonly motivoPublico: "ilegivel" };

export type Decidido =
  | { readonly estado: "incompleto"; readonly faltam: readonly TipoDeDocumento[] }
  /** O caso já não está em `kyc_pendente`: a decisão é de quem o tem agora. */
  | { readonly estado: "fora_de_fase"; readonly fase: string }
  | {
      readonly estado: "decidido";
      readonly avaliacao: Avaliacao;
      /** `null` quando `k1_ok`. */
      readonly motivoPublico: MotivoPublico | null;
    };

/** Quem abre um documento na revisão. Ver `urlParaRevisao`. */
export interface AuditoriaDeAcesso {
  anotarAcesso(acesso: {
    readonly revisor: string;
    readonly onboardingId: string;
    readonly verificacaoId: string;
    readonly em: Date;
  }): Promise<void>;
}

/** Os casos mortos há mais de D+30. Implementada sobre `onboarding_case.fase_at`. */
export interface CasosMortos {
  mortosAte(limite: Date): Promise<readonly { readonly onboardingId: string; readonly tenantId: string }[]>;
  /** Esquece os campos e marca a verificação como purgada. */
  esquecer(verificacaoIds: readonly string[]): Promise<void>;
}

/**
 * Rasteriza PNG neste processo e delega o resto. **Sem delegado, PDF e JPEG
 * são recusados**: o critério 1 manda o PDF a um processo isolado, e o que
 * não tem para onde ir não se abre aqui.
 */
export class RasterizadorLocal implements Rasterizador {
  readonly #isolado: Rasterizador | null;
  readonly #pixeis: number;

  constructor(isolado: Rasterizador | null, pixeisMaximos = LIMIARES_POR_OMISSAO.pixeisMaximos) {
    this.#isolado = isolado;
    this.#pixeis = pixeisMaximos;
  }

  async rasterizar(bytes: Uint8Array, formato: Formato): Promise<Rasterizado> {
    if (formato === "png") {
      const lido = descodificarPng(bytes, this.#pixeis);
      return { paginas: [lido.pagina], software: lido.software };
    }
    if (this.#isolado === null) throw new FicheiroInvalidoError(`sem processo isolado para ${formato}`);
    const r = await this.#isolado.rasterizar(bytes, formato);
    // Os metadados de um JPEG lêem-se aqui também: o processo isolado pode não
    // os devolver, e lê-los não descodifica a imagem.
    return formato === "jpeg" ? { ...r, software: [...r.software, ...softwareDoJpeg(bytes)] } : r;
  }
}

export interface DependenciasDoKyc {
  readonly verificacoes: RepositorioDeVerificacoes;
  readonly casos: CasosDoKyc;
  readonly armazem: StorageProvider;
  readonly antivirus: Antivirus;
  readonly rasterizador: Rasterizador;
  readonly ocr: OcrProvider;
  readonly cifra: Cifra;
  readonly fila: FilaDeRevisao;
  /** O anel do HMAC do NIF da inscrição (KAM-086), a chave actual primeiro. */
  readonly anelDoNif: readonly (Uint8Array | null)[];
  readonly relogio?: Relogio;
  readonly limiares?: Limiares;
  readonly formas?: Formas;
}

/** A data em `Africa/Luanda`, `aaaa-mm-dd`. */
export function dataEmLuanda(instante: Date): string {
  return new Intl.DateTimeFormat("en-CA", {
    timeZone: "Africa/Luanda",
    year: "numeric",
    month: "2-digit",
    day: "2-digit",
  }).format(instante);
}

interface Conteudo {
  readonly campos: Campos;
  readonly invalidos: readonly NomeDoCampo[];
}

export class ServicoKyc {
  readonly #d: DependenciasDoKyc;
  readonly #l: Limiares;
  readonly #agora: Relogio;

  constructor(d: DependenciasDoKyc) {
    this.#d = d;
    this.#l = d.limiares ?? LIMIARES_POR_OMISSAO;
    this.#agora = d.relogio ?? (() => new Date());
  }

  /** Recebe um documento. Ver a nota do módulo. */
  async receber(onboardingId: string, tipo: TipoDeDocumento, bytes: Uint8Array): Promise<Recebido> {
    const d = this.#d;
    const caso = await d.casos.porId(onboardingId);
    if (caso === null || !FASES_QUE_RECEBEM.includes(caso.fase)) return { estado: "recusado", motivo: "caso" };
    const formato = detectarFormato(bytes);
    if (formato === null) return { estado: "recusado", motivo: "formato" };
    if (bytes.length > this.#l.octetosMaximos) return { estado: "recusado", motivo: "tamanho" };

    const sha256 = createHash("sha256").update(bytes).digest("hex");
    const ja = await d.verificacoes.porSha(onboardingId, sha256);
    if (ja !== null && ja.resultado === "ilegivel") {
      // O mesmo ficheiro ilegível outra vez: não conta, e também não é «lido»
      // — dizer «lido» ao dono era sucesso sobre um documento que não se leu
      // (achado A10).
      return {
        estado: "novo_carregamento",
        verificacao: ja,
        restantes: this.#l.pedidosDeNovoCarregamento + 1 - (await this.#ilegiveis(onboardingId, tipo)),
        motivoPublico: "ilegivel",
      };
    }
    if (ja !== null) return { estado: "lido", verificacao: ja, repetido: true };

    const av = await d.antivirus.verificar(bytes);
    if (!av.limpo) return { estado: "recusado", motivo: "antivirus" };

    let r: Rasterizado;
    try {
      r = await d.rasterizador.rasterizar(bytes, formato);
    } catch (e) {
      if (e instanceof FicheiroInvalidoError) return { estado: "recusado", motivo: "formato" };
      throw e;
    }
    if (r.paginas.length === 0) return { estado: "recusado", motivo: "formato" };
    if (r.paginas.length > this.#l.paginasMaximas) return { estado: "recusado", motivo: "paginas" };

    const agora = this.#agora();
    const ctx = { tenantId: caso.tenantId };
    const chave = novaChave(ctx, CLASSE_DO_DOCUMENTO, agora);
    await d.armazem.put(ctx, chave, bytes, {
      contentType: formato === "pdf" ? "application/pdf" : `image/${formato}`,
      classe: CLASSE_DO_DOCUMENTO,
      retainUntil: new Date(agora.getTime() + DIAS_DO_TECTO_NO_STO * 86_400_000),
    });

    const marcas: Marca[] = [];
    const phash = dhash(r.paginas[0]!);
    if (await d.verificacoes.phashVistoNoutroCaso(onboardingId, phash, this.#l.hammingMaximo)) {
      marcas.push("imagem_reutilizada");
    }
    if (softwareDeEdicao(r.software)) marcas.push("software_de_edicao");

    let conteudo: Conteudo = { campos: {}, invalidos: [] };
    let custoMicroUsd = 0;
    try {
      const extraido = await d.ocr.extract(
        { onboardingId, tenantId: caso.tenantId, chave, paginas: r.paginas },
        tipo,
      );
      custoMicroUsd = Math.max(0, Math.round(extraido.custoUsd * 1e6));
      conteudo = validarCampos(extraido.campos, d.formas ?? FORMAS_POR_OMISSAO);
      const total = (await d.verificacoes.custoDoCaso(onboardingId)) + custoMicroUsd;
      if (total > this.#l.custoMaximoPorCasoMicroUsd) marcas.push("orcamento_excedido");
    } catch (e) {
      if (e instanceof VisaoNaoAutorizadaError) marcas.push("visao_recusada");
      else if (e instanceof OrcamentoExcedidoError) marcas.push("orcamento_excedido");
      else {
        // Uma avaria do motor não deixa o documento no STO sem linha que o
        // refira: a purga só vê objectos com linha, e um órfão ficava os dez
        // anos do tecto (achado A5). O erro que sobe é o original.
        await d.armazem.delete(ctx, { key: chave, tamanho: bytes.length, sha256 }).catch(() => undefined);
        throw e;
      }
    }

    // Ilegível: um campo exigido que não veio, ou veio e não se lê. Um campo
    // que veio **inválido** não é ilegível — é um valor que não passa, e conta
    // como confiança zero nas regras (uma data de 30 de Fevereiro vai à fila,
    // não pede outra fotografia). E um documento que não se leu por recusa do
    // gate não é ilegível: não houve leitura.
    const desviado = marcas.includes("visao_recusada") || marcas.includes("orcamento_excedido");
    const ilegivel =
      !desviado &&
      CAMPOS_EXIGIDOS[tipo].some((c) => {
        if (conteudo.invalidos.includes(c)) return false;
        const campo = conteudo.campos[c];
        return campo === undefined || campo.conf < this.#l.confiancaDeLeitura;
      });
    if (ilegivel) marcas.push("ilegivel");

    const claro = new TextEncoder().encode(JSON.stringify(conteudo));
    const { verificacao, repetida } = await d.verificacoes.inserir({
      onboardingId,
      tipo,
      docRef: chave,
      sha256,
      phash,
      extraidoCifrado: await d.cifra.cifrar(claro, `${onboardingId}:${tipo}`),
      flags: marcas,
      resultado: ilegivel ? "ilegivel" : "pendente",
      versaoRegras: VERSAO_DAS_REGRAS,
      custoMicroUsd,
    });
    if (repetida) {
      // Corrida de dois carregamentos do mesmo ficheiro: o segundo objecto no
      // STO não tem linha que o refira, e apaga-se.
      await d.armazem.delete(ctx, { key: chave, tamanho: bytes.length, sha256 });
      return { estado: "lido", verificacao, repetido: true };
    }
    if (!ilegivel) return { estado: "lido", verificacao, repetido: false };

    const ilegiveis = await this.#ilegiveis(onboardingId, tipo);
    if (ilegiveis > this.#l.pedidosDeNovoCarregamento) {
      await d.casos.marcarFase(onboardingId, "rejeitado");
      return { estado: "rejeitado", verificacao, motivoPublico: "ilegivel" };
    }
    return {
      estado: "novo_carregamento",
      verificacao,
      restantes: this.#l.pedidosDeNovoCarregamento - ilegiveis + 1,
      motivoPublico: "ilegivel",
    };
  }

  /** Decide o caso, se os quatro documentos estiverem lidos. Ver a nota do módulo. */
  async decidir(onboardingId: string): Promise<Decidido> {
    const d = this.#d;
    const caso = await d.casos.porId(onboardingId);
    if (caso === null) throw new Error("caso inexistente");
    // Só um caso em `kyc_pendente` se decide. Depois de uma fila, o caso está em
    // `em_revisao` e a decisão é do T&S: decidir outra vez, sobre documentos
    // recarregados, aprovava sem humano um caso que uma regra dura mandou à
    // fila (achado A2).
    if (caso.fase !== "kyc_pendente") return { estado: "fora_de_fase", fase: caso.fase };
    const todas = await d.verificacoes.doCaso(onboardingId);
    const ultimas = new Map<TipoDeDocumento, Verificacao>();
    for (const v of todas) {
      if (v.resultado !== "ilegivel") ultimas.set(v.tipo, v);
    }
    const faltam = TIPOS_DE_DOCUMENTO.filter((t) => !ultimas.has(t));
    if (faltam.length > 0) return { estado: "incompleto", faltam };

    const documentos = {} as Record<TipoDeDocumento, DocumentoLido>;
    for (const [tipo, v] of ultimas) {
      const c = v.extraidoCifrado === null ? null : await this.#ler(v, onboardingId);
      // As marcas do **ficheiro** de todos os documentos deste tipo, os
      // ilegíveis incluídos: uma imagem reutilizada que também não se lia
      // continua a ser um sinal sobre quem a enviou.
      const doFicheiro = todas
        .filter((x) => x.tipo === tipo && x.id !== v.id && x.resultado === "ilegivel")
        .flatMap((x) => x.flags.filter((m) => m === "imagem_reutilizada" || m === "software_de_edicao"));
      documentos[tipo] = {
        campos: c?.campos ?? {},
        invalidos: c?.invalidos ?? [],
        marcas: [...new Set([...v.flags.filter((m) => m !== "ilegivel"), ...doFicheiro])],
      };
    }
    const avaliacao = avaliar({
      documentos,
      nifHmacDeclarado: caso.nifHmac,
      anelDoNif: d.anelDoNif,
      categoriaDeclarada: caso.categoriaDeclarada,
      hoje: dataEmLuanda(this.#agora()),
      limiares: this.#l,
    });
    const verificacoes = [...ultimas.values()];
    const igual = verificacoes.every(
      (v) => v.resultado === avaliacao.resultado && v.score === avaliacao.score,
    );
    if (!igual) {
      await d.verificacoes.decidir(
        verificacoes.map((v) => v.id),
        avaliacao.resultado,
        avaliacao.score,
      );
      if (avaliacao.resultado === "fila") {
        await d.fila.enviar({
          onboardingId,
          score: avaliacao.score,
          marcas: avaliacao.marcas,
          recomendacao: avaliacao.recomendacao,
        });
        await d.casos.marcarFase(onboardingId, "em_revisao");
      }
    }
    return {
      estado: "decidido",
      avaliacao,
      motivoPublico: avaliacao.resultado === "fila" ? motivoPublico(avaliacao.marcas) : null,
    };
  }

  /**
   * Uma URL de leitura de um documento para o T&S, com o TTL dos limiares
   * (≤ 300 s, que é também o tecto da porta do STO) e o acesso anotado
   * **antes** de a URL existir: uma auditoria que falha não deixa sair URL.
   */
  async urlParaRevisao(
    revisor: string,
    onboardingId: string,
    verificacaoId: string,
    auditoria: AuditoriaDeAcesso,
  ): Promise<string> {
    const d = this.#d;
    const caso = await d.casos.porId(onboardingId);
    const v = (await d.verificacoes.doCaso(onboardingId)).find((x) => x.id === verificacaoId);
    if (caso === null || v === undefined) throw new Error("documento inexistente neste caso");
    await auditoria.anotarAcesso({ revisor, onboardingId, verificacaoId, em: this.#agora() });
    return d.armazem.signUrl(
      { tenantId: caso.tenantId },
      { key: v.docRef, tamanho: 0, sha256: v.sha256 },
      { ttlSeconds: Math.min(this.#l.ttlDaUrlS, 300) },
    );
  }

  /** Apaga os documentos e esquece os campos dos casos mortos há mais de D+30. */
  async purgar(mortos: CasosMortos): Promise<number> {
    const d = this.#d;
    const limite = new Date(this.#agora().getTime() - this.#l.diasAtePurga * 86_400_000);
    let apagados = 0;
    for (const m of await mortos.mortosAte(limite)) {
      const vs = (await d.verificacoes.doCaso(m.onboardingId)).filter((v) => v.extraidoCifrado !== null);
      for (const v of vs) {
        await d.armazem.delete({ tenantId: m.tenantId }, { key: v.docRef, tamanho: 0, sha256: v.sha256 });
        apagados++;
      }
      if (vs.length > 0) await mortos.esquecer(vs.map((v) => v.id));
    }
    return apagados;
  }

  async #ilegiveis(onboardingId: string, tipo: TipoDeDocumento): Promise<number> {
    return (await this.#d.verificacoes.doCaso(onboardingId)).filter(
      (v) => v.tipo === tipo && v.resultado === "ilegivel",
    ).length;
  }

  async #ler(v: Verificacao, onboardingId: string): Promise<Conteudo> {
    const claro = await this.#d.cifra.decifrar(v.extraidoCifrado!, `${onboardingId}:${v.tipo}`);
    return JSON.parse(new TextDecoder().decode(claro)) as Conteudo;
  }
}
