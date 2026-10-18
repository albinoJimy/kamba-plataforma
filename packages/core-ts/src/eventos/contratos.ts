/**
 * A validação de um payload contra o seu contrato, antes de `evt_emitir`
 * (KAM-007, critério 6).
 *
 * ## O que isto verifica, e o que **não** verifica
 *
 * Verifica a forma que o contrato fecha: o tipo existe, a versão é a que o
 * contrato tem, não há campos a mais (`additionalProperties: false`) e não
 * falta nenhum obrigatório (`required`). É o que o catálogo gerado carrega, e
 * é o que apanha os três erros que um produtor comete: inventar um tipo,
 * escrever um nome de campo errado, e esquecer um campo.
 *
 * **Não** verifica tipos nem formatos — que um `valor_minor` é inteiro, que um
 * `order_id` é um UUID. Isso é JSON Schema completo, e um validador de JSON
 * Schema é uma dependência que este repositório não tem (e que o
 * `tools/contract_diff` evita pela mesma razão que o `kamba_yaml` evitou o
 * PyYAML). O que cobre essa metade é o compilador: o payload de um produtor em
 * TypeScript é um `PayloadOrderCreated`, e um `valor_minor: "24500000"` não
 * compila.
 *
 * As duas metades juntas são a validação; cada uma sozinha tem um buraco, e os
 * buracos não se sobrepõem. Fica dito aqui para que ninguém leia esta função
 * como «o payload está validado» sem a outra.
 *
 * ## Porque é que um tipo desconhecido é erro e não aviso
 *
 * O `docs/tecnica/06` §6.6 corrige explicitamente o documento 11, que mandava
 * «ignorar versões desconhecidas»: isso **perde dados em silêncio** quando o
 * produtor é actualizado primeiro. A mesma lógica vale para o tipo. Um
 * produtor que emita um tipo sem contrato está a publicar algo que nenhum
 * consumidor sabe ler, e a resposta certa é não deixar sair.
 */

import { CATALOGO } from '@kamba/contracts';

/** Um tipo de evento sem contrato em `contratos/eventos/`. */
export class TipoDesconhecidoError extends Error {
  readonly tipo: string;

  constructor(tipo: string) {
    super(
      `o tipo ${JSON.stringify(tipo)} não tem contrato. Um evento que nenhum ` +
        'consumidor sabe ler não se publica: o contrato nasce em ' +
        'contratos/eventos/<tipo>/v1.schema.json (KAM-007)',
    );
    this.name = 'TipoDesconhecidoError';
    this.tipo = tipo;
  }
}

/** Uma versão que o contrato deste tipo não tem. */
export class VersaoDesconhecidaError extends Error {
  readonly tipo: string;
  readonly versao: number;

  constructor(tipo: string, versao: number, publicadas: readonly number[]) {
    super(
      `${tipo} v${versao} não existe: as versões publicadas são ` +
        `${publicadas.map((v) => `v${v}`).join(', ')}. ` +
        'Uma versão nova é um ficheiro v<N+1>.schema.json, e os consumidores ' +
        'migram antes dos produtores (docs/tecnica/06 §6.6)',
    );
    this.name = 'VersaoDesconhecidaError';
    this.tipo = tipo;
    this.versao = versao;
  }
}

/** O payload não tem a forma que o contrato fecha. */
export class PayloadInvalidoError extends Error {
  readonly tipo: string;
  readonly aMais: readonly string[];
  readonly emFalta: readonly string[];

  constructor(tipo: string, aMais: readonly string[], emFalta: readonly string[]) {
    const partes: string[] = [];
    if (emFalta.length > 0) partes.push(`faltam ${emFalta.join(', ')}`);
    if (aMais.length > 0) partes.push(`sobram ${aMais.join(', ')}`);
    super(`o payload de ${tipo} não respeita o contrato: ${partes.join('; ')}`);
    this.name = 'PayloadInvalidoError';
    this.tipo = tipo;
    this.aMais = aMais;
    this.emFalta = emFalta;
  }
}

/** Os tipos que têm contrato. Lista fechada, gerada dos ficheiros. */
export function tiposComContrato(): readonly string[] {
  return Object.keys(CATALOGO);
}

/**
 * Lança se o payload não puder ser emitido como `tipo` v`versao`.
 *
 * Chama-se **antes** de `platform.evt_emitir`, e não depois: o `evt_emitir`
 * corre dentro da transacção de negócio do produtor, e um evento recusado lá
 * faz a transacção inteira falhar. Aqui, a recusa custa uma excepção antes de
 * se abrir seja o que for.
 */
export function validarPayload(tipo: string, versao: number, payload: unknown): void {
  const entrada = (CATALOGO as Record<string, { versoes: readonly number[];
    obrigatorios: readonly string[]; permitidos: readonly string[] } | undefined>)[tipo];
  if (entrada === undefined) throw new TipoDesconhecidoError(tipo);
  // `versoes` e nao `versao` desde o KAM-159: um tipo pode ter mais do que um
  // contrato publicado, e a v1 continua valida depois de a v2 nascer — e o que
  // o §6.6 quer dizer com «o v<N> fica como estava».
  if (!entrada.versoes.includes(versao)) {
    throw new VersaoDesconhecidaError(tipo, versao, entrada.versoes);
  }
  if (typeof payload !== 'object' || payload === null || Array.isArray(payload)) {
    throw new PayloadInvalidoError(tipo, [], ['(o payload tem de ser um objecto)']);
  }
  const presentes = Object.keys(payload as Record<string, unknown>);
  const aMais = presentes.filter((campo) => !entrada.permitidos.includes(campo));
  const emFalta = entrada.obrigatorios.filter((campo) => !presentes.includes(campo));
  if (aMais.length > 0 || emFalta.length > 0) {
    throw new PayloadInvalidoError(tipo, aMais, emFalta);
  }
}
