/**
 * O `tools/meta-sim`: simulador de webhooks Meta e servidor Graph falso
 * (KAM-024).
 *
 * A superfície pública está toda aqui, e é esta que o KAM-015, o KAM-016, o
 * KAM-017 e o KAM-020 importam. O que **não** se exporta é tão deliberado como
 * o que se exporta: nada deste pacote entra em produção, e por isso nada em
 * `services/` nem em `packages/` o pode importar — é o que o `lint_arch`
 * verifica, e o que o `tools/` no caminho significa.
 *
 * Quem precisa de uma *fixture* chama `todasAsFixtures`; quem precisa de um
 * corpo feito à medida monta-o com `corpo` e os construtores de campo; quem
 * precisa do Graph chama `new GraphFalso(...)`. O `cli.ts` é só uma casca sobre
 * estas funções, e é por isso que tudo o que o CLI faz também se faz de dentro
 * de um teste sem lançar processo nenhum.
 */

export { assinar, assinarMal, confere, segredoDeEnsaio, exigirSegredoDeEnsaio, CABECALHO, PREFIXO, PREFIXO_DO_SEGREDO, SegredoDeVerdadeError } from "./assinatura.ts";
export { casosAdversos, corpoMexido, NOMES as NOMES_ADVERSOS, type CasoAdverso, type Pedido as PedidoAdverso } from "./adversos.ts";
export { CAMPOS, MOTIVOS_DE_REMOCAO, QUALIDADES, ESCALOES, ESTADOS_DE_TEMPLATE, CATEGORIAS_DE_TEMPLATE, kindsDe, valorDe, type Campo, type Opcoes as OpcoesDeCampo } from "./campos.ts";
export { CODIGOS_CONFIRMADOS, CODIGOS_PROPOSTOS, erroDoGraph, type ErroDoGraph } from "./codigos.ts";
export { CAMPOS_COBERTOS, DIMENSOES, ITENS, MARCA, TIPOS_COBERTOS, emMarkdown, marcasEm, relatorio, type Item, type Linha, type Relatorio as RelatorioDeCobertura } from "./cobertura.ts";
export { CapturaRecusadaError, sanear, varrer, type Achado, type Saneamento } from "./captura.ts";
export { INVENTARIO, confrontar, frase, totalDeclarado, type Divergencia, type Entrada as EntradaDoInventario, type Medicao } from "./inventario.ts";
export { MODOS, OBJECTO, corpo, corpoMisturado, mudanca, mudarUmByte, serializar, texto as textoDoCorpo, type Corpo, type Entrada, type Modo, type Mudanca, type OpcoesDoCorpo, type PedidoDeMudanca } from "./corpo.ts";
export { CATEGORIAS, ESTADOS, MODELO, PRECO_USD, escada, estado, type Categoria, type Estado } from "./estados.ts";
export { CAMPOS_DAS_FIXTURES, VARIANTES_DAS_FIXTURES, cenarioDe, contagemPorItem, fixtureDe, nomeDaMarca, todasAsFixtures, type Cenario, type Fixture } from "./fixtures.ts";
export { CAMINHO_DA_MIDIA, CENARIOS_DE_ENVIO, GraphFalso, type CenarioDeEnvio, type Pedido as PedidoDoGraph, type Plano, type Registo, type Resposta } from "./graph.ts";
export { bsuid, canalDe, interlocutorDe, nomeDeExibicao, phoneNumberId, telefone, wabaId, wamid, type Canal, type Interlocutor } from "./identificadores.ts";
export { BASE_DO_TEMPO, TIPOS, VARIANTES_INTERACTIVAS, contacto, instante, interactiva, mensagem, type Tipo, type VarianteInteractiva } from "./mensagens.ts";
export { ALGARISMOS, INDICATIVO_FICTICIO, INTERVALO, NumeroRealError, PADROES_DE_TELEFONE_REAL, eFicticio, exigirFicticios, telefonesReais, type Ocorrencia } from "./numeros.ts";
export { CALENDARIO_PROPOSTO, MINUTO_MS, SETE_DIAS_S, razoesDeFalha, reentregar, type Relatorio as RelatorioDeReentrega, type Tentativa } from "./reentrega.ts";
export { Gerador, estadoDe } from "./semente.ts";
