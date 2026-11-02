/**
 * PAY — a interface `PaymentProvider`, as contas e as guardas de dinheiro
 * (KAM-052).
 *
 * E o `pay-core` que o Objectivo do bloco nomeia. **Mora aqui e nao em
 * `services/pay/`**, e a razao mediu-se e nao se preferiu:
 *
 * * os «Detalhes Tecnicos» do bloco escrevem
 *   `services/pay/src/provider/{types,registry,capabilities}.ts`, e
 *   `services/pay/` **nao existe** nesta arvore — os cinco servicos sao `agr`,
 *   `com`, `gwy`, `onboarding-web` e `worker-canal`;
 * * a convencao desta arvore para um modulo partilhado e um directorio de
 *   `packages/core-ts/src/` com export por subcaminho, e e assim que vivem o
 *   `ten` (KAM-009), o `chr` (KAM-014), os `modos` (KAM-018) e o `identity`
 *   (KAM-008) — todos eles, como este, codigo de estrato `critico`;
 * * o `ci/thresholds.yaml` **ja** tem o padrao `pagamentos` (na forma
 *   `<asterisco>/pagamentos/<asterisco>`, que nao se escreve aqui a letra porque
 *   fecharia este comentario) no estrato `critico` a
 *   90%, com a anotacao «Pagamentos e liquidacao (KAM-052 em diante)» e a nota
 *   de que «o gate comeca a morder neles no dia em que o primeiro ficheiro bater
 *   num padrao». Este directorio e esse dia, e o limiar do DoD («cobertura do
 *   modulo de dinheiro >= 90%») fica imposto sem se acrescentar padrao nenhum.
 *
 * A discrepancia do caminho e **residuo textual** e esta na divida documental
 * 148. Quem escrever o KAM-056 importa daqui, por
 * `@kamba/core-ts/pagamentos`.
 *
 * ## O que este modulo entrega, e o que fica para os tickets que ele bloqueia
 *
 *     tipos         o contrato dos 8 metodos, `Minor = bigint`, as capacidades
 *     dinheiro      `Minor` <-> `decimal2`/`inteiro_kz`, sem virgula flutuante
 *     registo       as duas recusas do §3.1 e a regra de activacao
 *     estados       a maquina de `payment_accounts.estado` (§10.2), pura
 *     contas        G-1 do lado da aplicacao, `credenciais_ref`, `webhook_token`
 *     arranque      G-2 e G-4, que recusam o arranque
 *     conformidade  os dez casos do §3.5, parametrizaveis por adaptador
 *     fake          o adaptador de referencia que os passa
 *
 * E, desde o **KAM-053**, as duas pecas de aplicacao do ledger — o resto dele
 * vive na revisao `0029`, porque um ledger cuja imutabilidade dependesse de
 * codigo de aplicacao nao era imutavel:
 *
 *     hooks         o *handler* `POST /hooks/pay/{provider}/{webhook_token}`,
 *                   com a ordem do §5.1 (`inbox.insert -> verifyCallback ->
 *                   2xx`) e as cadeias de SQL que a suite de base de dados le
 *                   deste ficheiro em vez de uma copia
 *     ledger        a verificacao diaria da cadeia e a ancora externa no
 *                   `StorageProvider` (§8)
 *     gates         G2-G7, a parte **avaliar** do *worker* do §5.1, pura. A
 *                   orquestracao — ler o *inbox*, abrir transacção, chamar a
 *                   porta — e I/O e vive no servico `pay`, que nao existe
 *
 * O ledger `payment_events` e o KAM-053; o `ManualProvider` e o KAM-054; a
 * `payment_charges` e as FK para `orders_mirror` sao o KAM-055; o ProxyPay e o
 * KAM-056; o billing e o KAM-059. **Nenhum deles esta aqui**, e o `refund` e o
 * `payout` devolvem `NOT_SUPPORTED` por ADR-004 e nao por estarem por fazer.
 *
 * ## `beneficiary_kind` e `pme`, e **nao** `tenant`
 *
 * E a unica divergencia deste modulo face ao DDL que o criterio 4 manda seguir,
 * e resolve-se pela ordem das fontes e nao por gosto. O
 * `specs/02_Dicionario_de_Dados_Canonico.md` §3.4 — fonte 4 — fixa
 * `beneficiary_kind ∈ {pme, plataforma_receita_propria}`; o
 * `docs/tecnica/04` §6.2 — fonte 9 — escreve `('tenant','plataforma_receita_propria')`,
 * e o §10.4 e o criterio 6 do bloco repetem o `tenant`.
 *
 * O dicionario prevalece, e nao e so pela ordem: o dominio esta **fechado** em
 * `canon/dicionario.yaml` e o gate 3b recusa um `CHECK` com um valor fora dele —
 * isto e, uma migracao copiada a letra do §6.2 fica **vermelha**. Medido, nao
 * inferido. A divergencia esta na divida documental 149, com o §6.2, o §10.4 e
 * o criterio 6 nomeados, e a secao de verificacao do bloco di-lo tambem.
 *
 * ## `balance`, `wallet` e `escrow` nao existem aqui (G-3, ADR-004)
 *
 * Nao e uma omissao a notar: e uma propriedade verificada. O
 * `db/tests/test_catalogo.py::test_nao_ha_colunas_de_dinheiro_nem_saldos` recusa
 * qualquer coluna `%saldo%`, `%balance%`, `%_minor` ou `%_kz` em `platform`, e o
 * `tools/money_lint` recusa os tres nomes neste directorio. Os «relatorios a
 * receber pela PME» do §10.4 G-3 sao informativos e rotulados, e nao existem
 * neste ticket.
 */

export {
  CONTA_DE_PME_COM_ENTIDADE_DA_KAMBA,
  ENTIDADES_DA_KAMBA,
  FLAGS_OMISSAO,
  PAYOUTS_SEM_PSP_LICENCIADO,
  ArranqueRecusado,
  type ContaParaGuarda,
  type EntidadesDaKamba,
  type FlagsDeDinheiro,
  verificarArranque,
  verificarG2,
  verificarG4,
} from "./arranque.ts";

export {
  CASOS,
  type BancoDeEnsaio,
  type Caso,
  type FalhaProgramada,
  type ResultadoDoCaso,
  type Veredicto,
  correr,
  relatorio,
} from "./conformidade.ts";

export {
  BENEFICIARIO_INCOERENTE,
  BENEFICIARY_KINDS,
  COMPRIMENTO_DO_WEBHOOK_TOKEN,
  CONTA_DA_PLATAFORMA_EM_ENCOMENDA,
  CONTA_DE_OUTRO_TENANT,
  CONTA_DE_PME_EM_BILLING,
  CredenciaisRefInvalida,
  LIQUIDACAO_DESTINOS,
  OCTETOS_DO_WEBHOOK_TOKEN,
  type BeneficiaryKind,
  type CodigoDeBeneficiario,
  type ContaDePagamento,
  type LiquidacaoDestino,
  type VeredictoDeBeneficiario,
  gerarWebhookToken,
  validarCredenciaisRef,
  verificarBeneficiario,
} from "./contas.ts";

export {
  ESTADOS_QUE_ACEITAM,
  ESTADO_TARDIO,
  GATES_DO_WORKER,
  type CobrancaParaGates,
  type ContaParaGates,
  type DestinoDoEvento,
  type EntradaDosGates,
  type GateDoWorker,
  type MotivoDeDivergencia,
  type VeredictoDosGates,
  avaliarGates,
  escritasDoVeredicto,
  reciboDoVeredicto,
} from "./gates.ts";

export {
  ALERTA_HMAC,
  CABECALHOS_GUARDADOS,
  CADEIAS_EXERCITADAS,
  CAMINHO_DO_HOOK,
  CORPO_DO_404,
  EVENTOS_DO_WORKER,
  METRICA_ACK,
  METRICA_EVENTOS,
  SQL_APPEND_PAYMENT_EVENT,
  SQL_INBOX_INSERT,
  SQL_INBOX_MARK,
  SQL_OUTBOX_MAP,
  SQL_RESOLVE_WEBHOOK_TOKEN,
  TECTO_DO_CORPO,
  type AdaptadorDoHook,
  type ContaDoToken,
  type DependenciasDoHook,
  type EstadoDaEntrega,
  type Inbox,
  type PedidoDoHook,
  type RespostaDoHook,
  type TrabalhoDoWorker,
  type VeredictoDoWorker,
  atenderCallback,
  redigir,
} from "./hooks.ts";

export {
  ALERTA_DA_CADEIA,
  ALERTA_DA_PROJECCAO,
  CADEIAS_DO_JOB,
  PREFIXO_DA_ANCORA,
  SQL_CABECAS,
  SQL_ELOS_PARTIDOS,
  SQL_PROJECCOES_DIVERGENTES,
  type CabecaDaCadeia,
  type DependenciasDoJob,
  type EloPartido,
  type EscritaDaAncora,
  type LeituraDoLedger,
  type ProjeccaoDivergente,
  type RelatorioDoLedger,
  chaveDaAncora,
  serializarAncora,
  verificarLedgerDiariamente,
} from "./ledger.ts";

export {
  CASAS_DO_DECIMAL2,
  MINOR_POR_KZ,
  ValorDeDinheiroInvalido,
  minorDeDecimal2,
  minorDeFormato,
  minorDeInteiroKz,
  minorParaDecimal2,
  minorParaFormato,
  minorParaInteiroKz,
} from "./dinheiro.ts";

export {
  ESTADOS_DA_CONTA,
  ESTADOS_QUE_OCUPAM,
  GATILHOS,
  SINAL_EM_FALTA,
  TRANSICAO_INEXISTENTE,
  type EstadoDaConta,
  type Gatilho,
  type RecusaDeTransicao,
  type ResultadoDeTransicao,
  type Sinais,
  estaActiva,
  podeCobrar,
  transitar,
} from "./estados.ts";

export {
  CABECALHO_DA_ASSINATURA,
  CAPACIDADES_DO_FAKE,
  FakeProvider,
  type OpcoesDoFake,
  type ResolverChave,
} from "./fake.ts";

export {
  ADAPTADORES_COM_LICENCA_BNA,
  ADAPTADORES_DE_CONFIRMACAO_HUMANA,
  ADAPTER_CANNOT_CONFIRM,
  CONFORMANCE_REQUIRED,
  CONFORMIDADE_VAZIA,
  ETIQUETA_NAO_RECONHECIDA,
  HUMAN_ONLY_INCOERENTE,
  AdapterCannotConfirm,
  ConformanceRequired,
  EtiquetaNaoReconhecida,
  HumanOnlyIncoerente,
  POLITICA_DE_PRODUCAO,
  RegistoDeProviders,
  type CodigoDeRecusa,
  type Conformidade,
  type PoliticaDeActivacao,
  activar,
  podeConfirmar,
  suporta,
} from "./registo.ts";

export {
  METODOS_DO_CONTRATO,
  AuthError,
  ProviderError,
  type AccountSecrets,
  type AmountFormat,
  type CallbackAuth,
  type ChargeResult,
  type CreateChargeReq,
  type Instant,
  type Metodo,
  type MetodoDoContrato,
  type Minor,
  type Moeda,
  type PaymentProvider,
  type PayoutReq,
  type PayoutResult,
  type ProviderCapabilities,
  type ProviderErr,
  type ProviderPaymentPage,
  type ProviderRef,
  type ProviderStatus,
  type RawHttpCallback,
  type RecusaNaoSuportada,
  type RefundReq,
  type RefundResult,
  type Uuid,
  type VerifiedEvent,
} from "./tipos.ts";
