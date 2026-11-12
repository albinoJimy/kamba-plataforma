/**
 * A saga de provisioning de um tenant: portas, domínios e tipos (KAM-091).
 *
 * A saga corre quando o `tenant.approved` chega (ADR-009, e o canon §3.5 fixa
 * **este** nome como «gatilho do provisioning», com o `tenant.activated` em
 * `nomes_nota`). São oito passos, pela ordem do `docs/tecnica/10` §5.2, e cada
 * um é um *ensure* idempotente com chave natural derivada do caso.
 *
 * ## Onde vive a idempotência, e porque isso decide o desenho todo
 *
 * O critério 4 é o único que não se prova com um teste feliz: **crash entre
 * criar o recurso externo e gravar o `markDone`**. Para o poder provar, a
 * procura-antes-de-criar tem de estar **no nosso código** e não dentro de um
 * duplo de teste. Por isso as portas externas deste módulo são **inventários**
 * de duas operações — `procurar(chave)` e `criar(…)` — e o `ensure` que as
 * combina é o `passos.ts`.
 *
 * A diferença não é de estilo. Uma porta `ensureX(tenantId)` que decidisse por
 * si punha a propriedade no duplo: apagar a procura do nosso lado deixava o
 * teste verde, porque o duplo continuava a devolver o mesmo. Com a porta
 * partida em duas, apagar a procura faz o contador de criações do inventário ir
 * a 2 — e há um ensaio a afirmar que é 1. A bateria de mutações que o
 * confirma corre fora do repositório — é um instrumento de medição, não um
 * portão; o PR registra as mutações e o seu veredicto.
 *
 * A excepção é o passo 4: o Chatwoot entra por `HandoffProvider.ensureAccount`
 * (KAM-019) **como caixa preta**, porque é isso que o *handoff* deste ticket
 * manda. Essa porta já procura antes de criar
 * (`src/hnd/provedor.ts:210`) e tem *suite* própria; aqui conta-se que ela foi
 * chamada uma vez por passagem e não se reimplementa a sua garantia.
 *
 * ## O que este módulo **não** tem, e com que credor
 *
 * - **Medusa.** Não há serviço `medusa` em compose nenhum (nem no
 *   `docker-compose.dev.yml`, nem no de produção do KAM-076), não há imagem
 *   publicada e não há `services/medusa/Dockerfile` — o
 *   `infra/compose/conjunto-reduzido.yaml` di-lo por escrito. E o
 *   `CommerceRegistry` (`services/com/src/port/contrato.ts:410`) tem doze
 *   métodos, **nenhum** dos quais cria *sales channel* ou *merchant*. O
 *   `RegistoDeCanalDeComercio` abaixo é a **forma de que a saga precisa**, não
 *   um adaptador: não há implementação real, e o que os ensaios provam é a
 *   máquina de estados, nunca o Medusa. Credor: **D3 / KAM-042**.
 * - **`onboarding_case`.** Não existe em revisão nenhuma (37 tabelas criadas em
 *   `db/migrations/versions/*.py`, e não é uma delas), mas **tem credor com DDL
 *   escrito**: o bloco do KAM-086 em `specs/EPIC-09_Onboarding_Governanca.md`
 *   traz o `CREATE TABLE platform.onboarding_case` inteiro. O `Caso` abaixo é
 *   lido por porta (`LeitorDeCasos`) e a saga chaveia pelo `onboarding_id`, que
 *   é o nome que essa tabela vai ter. Credor: **KAM-086**.
 * - **`review_case`.** Também não existe, e também tem credor: **KAM-089**. A
 *   escalada ao 3.º falhanço grava o estado terminal no `provisioning_step` e
 *   conta a métrica; não insere em tabela que não há.
 *
 * ## Uma divergência de canon que não é deste ticket, mas que se mediu
 *
 * O `canon/dicionario.yaml` §3.2 fixa `onboarding_case.fase` com **seis**
 * valores (`kyc_pendente`, `aprovado`, `provisionando`, `aguarda_es`,
 * `aguarda_catalogo`, `pronto`). O DDL do bloco do KAM-086 escreve
 * `onboarding_case.estado` com **catorze** — e inclui `aguarda_teste`,
 * `abandonado` e `cancelado`, que o canon não tem, e tem `activo` onde o canon
 * diz `pronto`. Divergem o nome da coluna (`fase` contra `estado`) e o domínio.
 *
 * Não se resolveu aqui: a tabela é do KAM-086 e alterar o canon é do fundador.
 * **Resolveu-a a emenda 1.80 (KAM-087, dicionário §3.57)**: a coluna chama-se
 * `fase` e leva os catorze valores, `aguarda_teste` e `abandonado` incluídos.
 */

/** O cliente de base de dados, como nos outros módulos. */
export interface ClienteSql {
  query<T = Record<string, unknown>>(
    texto: string,
    valores?: readonly unknown[],
  ): Promise<{ readonly rows: readonly T[] }>;
}

/**
 * Os oito passos, **pela ordem**, do `docs/tecnica/10` §5.2.
 *
 * A ordem não é decorativa: é ela que a compensação inverte, e o critério 3
 * mede-a. O `PASSOS.indexOf` é a única fonte de precedência no módulo — não há
 * segunda lista com a ordem repetida, porque duas listas divergem.
 *
 * Os nomes são os do passo e não os do recurso: `conta_atendimento` e não
 * `chatwoot`, `canal_comercio` e não `medusa`. O fornecedor por trás de cada um
 * é uma decisão aberta (D3 para o comércio) e um passo cujo nome traz o
 * fornecedor obrigava a renomear a coluna de uma tabela quando a decisão
 * mudasse.
 */
export const PASSOS = [
  "tenant_e_caso",
  "chave_llm",
  "canal_comercio",
  "conta_atendimento",
  "entitlements",
  "espera_es",
  "inbox_e_rota",
  "teste_ponta_a_ponta",
] as const;
export type Passo = (typeof PASSOS)[number];

/**
 * Os estados de um passo — o `provisioning_step.status`.
 *
 * `em_curso` → `concluido` é o caminho normal; `falhado` é retomável e
 * `escalado` não é (é o 3.º falhanho do critério 5, e é terminal até alguém
 * intervir). `compensado` é o que a compensação escreve, e existe como estado
 * próprio por uma razão de reconciliação: um passo que foi desfeito e um passo
 * que nunca correu produzem ambos «nada lá fora», e quem lê o
 * `provisioning_step` tem de poder distingui-los — senão a reconciliação
 * nocturna classifica um recurso compensado como `externo_em_falta` e volta a
 * criá-lo.
 */
export const ESTADOS_DE_PASSO = [
  "em_curso",
  "concluido",
  "falhado",
  "escalado",
  "compensado",
] as const;
export type EstadoDePasso = (typeof ESTADOS_DE_PASSO)[number];

/**
 * Os três estados de espera dos passos 6–8 (critério 6).
 *
 * **O `aguarda_teste` não está no canon, e isto é uma medição e não um
 * descuido.** O `canon/dicionario.yaml` §3.2 fixa
 * `onboarding_case.fase: kyc_pendente, aprovado, provisionando, aguarda_es,
 * aguarda_catalogo, pronto` — seis valores, sem `aguarda_teste` e sem
 * `abandonado`, que o critério 6 deste ticket nomeia os dois.
 *
 * Não se altera o canon aqui: estes valores são do
 * `provisioning_step.status_de_espera`, que é coluna **nova** e domínio deste
 * ticket, e entram pelo `canon/extensoes.yaml` qualificados. A falta de
 * `aguarda_teste` e de `abandonado` em `onboarding_case.fase` ficou registada
 * para quem escrevesse essa tabela, e a emenda 1.80 (KAM-087) pô-los lá.
 */
export const ESPERAS = ["aguarda_es", "aguarda_catalogo", "aguarda_teste"] as const;
export type Espera = (typeof ESPERAS)[number];

/** Os três passos que são estados de espera (critério 6). */
export const PASSOS_DE_ESPERA = [
  "espera_es",
  "inbox_e_rota",
  "teste_ponta_a_ponta",
] as const;
export type PassoDeEspera = (typeof PASSOS_DE_ESPERA)[number];

/**
 * Qual espera corresponde a cada passo de espera. Os outros cinco não têm.
 *
 * O tipo é `Record<PassoDeEspera, Espera>` e **não** `Partial<Record<Passo, …>>`:
 * com o `Partial`, cada leitura devolvia `Espera | undefined` e os sítios que a
 * leem traziam um `?? "aguarda_es"` que nunca podia correr — um ramo morto a
 * fingir-se de defesa, e que escondia o facto de o mapa estar completo.
 */
export const ESPERA_DO_PASSO: Readonly<Record<PassoDeEspera, Espera>> = {
  espera_es: "aguarda_es",
  inbox_e_rota: "aguarda_catalogo",
  teste_ponta_a_ponta: "aguarda_teste",
};

/**
 * Os recursos que a saga toca, para a etiqueta da métrica e para a
 * classificação de propriedade.
 *
 * O `waba` está na lista porque a compensação do passo 6 fala com ele —
 * cancela a subscrição de webhooks, que é **nossa**. O `phone_number` está na
 * lista **e nenhuma acção o toca**: o `ACCOES_POR_RECURSO` dá-lhe lista vazia,
 * pelo que qualquer acção sobre ele é incoerente. O que não se pode nomear não
 * se pode guardar.
 */
export const RECURSOS = [
  "tenant",
  "chave_llm",
  "canal_comercio",
  "conta_atendimento",
  "entitlement",
  "waba",
  "phone_number",
  "rota_chr",
  "inbox",
] as const;
export type Recurso = (typeof RECURSOS)[number];

/**
 * **Os recursos que são do cliente e que a compensação nunca apaga.** Critério
 * 7, evidência E1.
 *
 * O WABA e o número de telefone são propriedade da PME: ela autenticou-se na
 * Meta e eles continuam dela se nos despedir. A compensação cancela a
 * subscrição de webhooks (nossa) e remove a rota do CHR (nossa), e mais nada.
 *
 * Isto é uma **propriedade de negócio** e não uma convenção de código, e por
 * isso é imposta em execução pelo `compensacao.ts` e não só pelo tipo: um
 * `DELETE` do número posto em qualquer compensação, hoje ou num ticket futuro,
 * levanta `RecursoDoClienteError` e põe o ensaio vermelho. Um `readonly` no
 * tipo não fazia isso — bastava alguém escrever outra função.
 */
export const RECURSOS_DO_CLIENTE: readonly Recurso[] = ["waba", "phone_number"];

/** O que uma compensação pede para ser feito. Declarativo, para ser inspeccionável. */
export const TIPOS_DE_ACCAO = [
  "apagar",
  "arquivar",
  "revogar",
  "cancelar_subscricao",
  "remover_rota",
  "desactivar",
  "marcar_cancelado",
] as const;
export type TipoDeAccao = (typeof TIPOS_DE_ACCAO)[number];

/**
 * Os tipos de acção que destroem o recurso.
 *
 * `revogar` está aqui e `cancelar_subscricao` não, e a distinção é a do
 * critério 7: revogar uma chave virtual do LiteLLM destrói a chave (é nossa, e
 * é o que se quer); cancelar a subscrição de webhooks de um WABA deixa o WABA
 * intacto. `arquivar` não destrói — é o que o passo 3 faz ao canal, que só se
 * apaga se estiver vazio.
 */
export const TIPOS_DESTRUTIVOS: readonly TipoDeAccao[] = ["apagar", "revogar"];

/**
 * Que tipos de acção fazem sentido sobre cada recurso.
 *
 * Existe porque **a declaração tem de ser a verdade sobre o que aconteceu**, e
 * é essa a premissa do critério 7. Sem esta tabela, o executor despachava pelo
 * `recurso` e ignorava o `tipo` em seis dos nove casos: uma acção
 * `{tipo: "apagar", recurso: "inbox"}` passava o guarda (a *inbox* não é do
 * cliente) e chamava `desligar` — isto é, a compensação fazia uma coisa e
 * declarava outra, e a métrica, que conta pelo recurso, não distinguia as
 * duas. Um `tipo` decorativo tornava o critério 7 uma afirmação sobre um campo
 * que ninguém lia.
 *
 * Com a tabela, um `tipo` que não pertence ao recurso **levanta** antes de
 * qualquer efeito.
 */
export const ACCOES_POR_RECURSO: Readonly<Record<Recurso, readonly TipoDeAccao[]>> = {
  tenant: ["marcar_cancelado"],
  chave_llm: ["revogar"],
  canal_comercio: ["arquivar", "apagar"],
  conta_atendimento: ["apagar"],
  entitlement: ["desactivar"],
  // As duas únicas que o critério 7 permite sobre o que é do cliente. O
  // `TIPOS_DESTRUTIVOS` já as recusa; esta linha di-lo uma segunda vez, do
  // outro lado — e a segunda fechadura é deliberada numa propriedade que não
  // tem segunda chance.
  waba: ["cancelar_subscricao"],
  // **Nenhuma.** O número é do cliente e a compensação não lhe faz nada: o que
  // se remove é a **rota** (nossa, no `tenant_channels`), que é o `rota_chr`.
  // A primeira versão punha aqui `remover_rota` e o passo 6 declarava-o sobre o
  // número — a rota acabava removida **duas vezes**, por dois nomes
  // (`phone_number` no passo 6 e `rota_chr` no passo 7), e a
  // `saga_compensado_total` contava-a a dobrar. Encontrado pela revisão
  // adversarial. Com a lista vazia, qualquer acção sobre o número é incoerente
  // — que é a forma mais forte de dizer o critério 7.
  phone_number: [],
  rota_chr: ["remover_rota"],
  inbox: ["desactivar"],
};

/** A acção declara um tipo que não pertence ao recurso. Ver `ACCOES_POR_RECURSO`. */
export class AccaoIncoerenteError extends Error {
  readonly accao: AccaoDeCompensacao;
  readonly passo: Passo;

  constructor(accao: AccaoDeCompensacao, passo: Passo) {
    super(
      `a compensacao do passo ${passo} declarou \`${accao.tipo}\` sobre ` +
        `\`${accao.recurso}\`, e os tipos desse recurso sao ` +
        `${(ACCOES_POR_RECURSO[accao.recurso] ?? []).join(", ")}: a declaracao ` +
        "tem de ser a verdade sobre o que a compensacao faz",
    );
    this.name = "AccaoIncoerenteError";
    this.accao = accao;
    this.passo = passo;
  }
}

/**
 * Uma acção de compensação, declarada antes de ser corrida.
 *
 * A compensação **declara** o que vai fazer e um guarda avalia a declaração
 * antes de a executar. É o que permite ao critério 7 ser medido sobre o
 * conjunto de todas as acções da saga e não sobre a leitura de cada função.
 */
export interface AccaoDeCompensacao {
  readonly tipo: TipoDeAccao;
  readonly recurso: Recurso;
  /**
   * A referência do recurso lá fora. **Nunca um segredo**: é o `external_id`
   * que o `provisioning_step` guarda, e a DoD deste ticket proíbe chaves em
   * logs, *traces* e nessa tabela.
   */
  readonly ref: string;
}

/**
 * Um caso de provisioning.
 *
 * **Chaveia por `onboardingId` e não por `tenantId`**, e as três razões são de
 * desenho e não de gosto:
 *
 * 1. **O passo 1 é que cria a linha de `tenants`.** Uma chave com FK para
 *    `tenants.id` não podia guardar o registo desse passo antes de ele
 *    confirmar — ficávamos sem onde gravar o `markDone` do passo que cria o
 *    tenant.
 * 2. **O critério 2 nomeia a chave, e é o `onboarding_id`**: é a chave natural
 *    dos passos 1 e 8. E o identificador é da casa, não deste ticket — o bloco
 *    do KAM-087 declara `kyc_check.onboarding_id uuid NOT NULL REFERENCES
 *    platform.onboarding_case(id)`.
 * 3. Um `case_id` que referenciasse `tenants.id` era **um nome que mente**, e o
 *    *gate* 3b e o dicionário são estritos com nomes.
 *
 * O `tenantId` vem ao lado porque é **pré-alocado** (critério 2, passo 1: o
 * `onboarding_case.tenant_id` do bloco do KAM-086 é
 * `uuid NOT NULL UNIQUE DEFAULT gen_random_uuid()`), logo já se conhece no
 * passo 1 — e é ele que dá à tabela a RLS `FORCE` e a bateria de isolamento.
 */
export interface Caso {
  /** O `onboarding_id`: a chave da saga. `uuid`, pré-existente ao passo 1. */
  readonly onboardingId: string;
  /** O `tenant_id` **pré-alocado**. Vem do caso, nunca de texto. */
  readonly tenantId: string;
  readonly plano: string;
  readonly vertical: string;
  /**
   * O nome do negócio da PME, para `tenants.nome`.
   *
   * Está aqui porque a primeira versão do passo 1 passava a `vertical` para
   * aquela coluna: o tenant ficava com `nome = 'vendedor'`, passava o CHECK
   * `btrim(nome) <> ''` e nada acusava — a linha ficava silenciosamente errada,
   * e é a que o painel da PME mostra. É o `onboarding_case.nome_negocio` do
   * bloco do KAM-086, que a porta do caso devolve.
   */
  readonly nomeDoNegocio: string;
}

/**
 * Quem lê os casos. A porta que esconde a falta do `onboarding_case`.
 *
 * **Um método só, e é o que a reconciliação usa.** A primeira versão tinha
 * também `porId` e `vivos`, e nenhum era chamado: quem implementasse a porta
 * para produção escrevia três métodos para dois nunca serem invocados. O lado
 * nosso da reconciliação entra pelo `esperado()` das suas dependências, que é
 * quem sabe ler o `provisioning_step`.
 */
export interface LeitorDeCasos {
  /** Os casos `cancelado` há mais de `horas`. Para a reconciliação (critério 8). */
  canceladosHaMaisDe(horas: number): Promise<readonly Caso[]>;
}

/**
 * Quem escreve o estado do caso.
 *
 * **Não há implementação real desta porta**: a compensação do passo 1 marca o
 * caso `cancelado` sem apagar histórico, e a tabela onde esse `cancelado` vive
 * nasceu com a revisão `0043` (KAM-087) — falta o adaptador SQL que a escreva.
 * Credor nomeado, caixa vazia — e não um simulador apresentado como prova.
 */
export interface RegistoDoCaso {
  marcarCancelado(onboardingId: string): Promise<void>;
}

/** A linha de `provisioning_step`, como as consultas a devolvem. */
export interface LinhaDePasso {
  readonly onboarding_id: string;
  /** Pré-alocado, e é por ele que a RLS e o *gate* 6 agarram a tabela. */
  readonly tenant_id: string;
  readonly step: Passo;
  readonly status: EstadoDePasso;
  readonly attempt: number;
  readonly external_id: string | null;
  readonly error_code: string | null;
}

/**
 * O armazém do estado da saga: `provisioning_step`, `UNIQUE(onboarding_id, step)`.
 *
 * O `marcarConcluido` é separado do `abrir` **de propósito**, e é a janela do
 * critério 4: entre o `ensure` devolver e esta chamada gravar há um intervalo
 * em que o recurso existe lá fora e não existe aqui. A porta não esconde esse
 * intervalo porque é ele que se tem de medir.
 */
export interface ArmazemDePassos {
  /**
   * Abre (ou reabre) o passo em `em_curso` e **incrementa a tentativa**.
   * Devolve a linha depois do incremento — é o `attempt` que o critério 5 lê.
   */
  /**
   * Recebe o `Caso` inteiro e não só o `onboardingId` porque o `INSERT`
   * precisa do `tenant_id` — e o `tenant_id` **vem do caso, nunca de texto**
   * (regra do *handoff* deste ticket).
   */
  abrir(caso: Caso, passo: Passo): Promise<LinhaDePasso>;
  marcarConcluido(onboardingId: string, passo: Passo, externalId: string | null): Promise<void>;
  marcarFalhado(onboardingId: string, passo: Passo, codigoDeErro: string): Promise<void>;
  marcarEscalado(onboardingId: string, passo: Passo, codigoDeErro: string): Promise<void>;
  marcarCompensado(onboardingId: string, passo: Passo): Promise<void>;
  marcarEspera(onboardingId: string, passo: Passo, espera: Espera): Promise<void>;
  /**
   * **Todas** as linhas do caso, em qualquer ordem e em qualquer estado.
   *
   * Devolve tudo de propósito, e isto é a correcção de um defeito que um ensaio
   * de mutação encontrou. A primeira versão desta porta chamava-se
   * `passosConcluidos` e filtrava os `concluido` — o que punha o «só os `done`»
   * do critério 3 **dentro do duplo**: mutar o `saga.ts` não mudava nada,
   * porque era o armazém que filtrava, e o ensaio que dizia medir a propriedade
   * media o filtro do duplo. Agora quem filtra e quem ordena é o `compensar`, e
   * apagar lá o filtro põe o ensaio vermelho.
   */
  passosDoCaso(onboardingId: string): Promise<readonly LinhaDePasso[]>;
  passo(onboardingId: string, passo: Passo): Promise<LinhaDePasso | null>;
}

/**
 * Um inventário externo: duas operações, e nenhuma decide por si.
 *
 * Ver a nota do módulo: é esta forma que põe a procura-antes-de-criar no nosso
 * código, onde um ensaio de mutação a pode pôr vermelha.
 */
export interface Inventario<TChave, TRecurso> {
  procurar(chave: TChave): Promise<TRecurso | null>;
  criar(chave: TChave): Promise<TRecurso>;
}

/** Uma referência externa com etiqueta de origem. Ver `ETIQUETA_DA_SAGA`. */
export interface RefExterna {
  readonly id: string;
  /**
   * `true` quando o recurso traz a etiqueta desta saga.
   *
   * O critério 8 compensa automaticamente **apenas os recursos criados por esta
   * saga**, e é esta etiqueta que o decide. Sem ela, uma reconciliação que
   * limpasse «órfãos» apagava uma conta que a equipa criou à mão no Chatwoot.
   */
  readonly nosso: boolean;
}

/** A etiqueta que a saga põe em tudo o que cria, para a reconciliação a reconhecer. */
export const ETIQUETA_DA_SAGA = "kamba_provisioning";

/** A chave virtual do LiteLLM. Chave natural: o alias (critério 2, passo 2). */
export interface ChaveDeLlm extends Inventario<{ alias: string; orcamento: number }, RefExterna> {
  revogar(id: string): Promise<void>;
}

/**
 * O canal e o *merchant* de comércio.
 *
 * **Não há implementação disto.** Ver a nota do módulo: credor D3 / KAM-042. O
 * `arquivar` e não o `apagar` é o critério 7 («o canal Medusa é arquivado, e só
 * apagado se vazio»), e o `vazio` pergunta-se antes.
 */
export interface RegistoDeCanalDeComercio
  extends Inventario<{ tenantId: string }, RefExterna> {
  arquivar(id: string): Promise<void>;
  /**
   * Apaga **só se vazio**, e devolve se apagou.
   *
   * A pergunta é feita por dentro e não há `vazio()` separado: duas portas para
   * a mesma decisão deixavam quem chama escolher entre perguntar e agir, e a
   * resposta pode mudar entre as duas chamadas.
   */
  apagarSeVazio(id: string): Promise<boolean>;
}

/** Os entitlements, por `(tenant_id, modulo)` (critério 2, passo 5). */
export interface Entitlements {
  /** Idempotente por `(tenant_id, modulo)`: é um `ON CONFLICT DO UPDATE`. */
  garantir(tenantId: string, plano: string): Promise<readonly string[]>;
  desactivar(tenantId: string): Promise<void>;
}

/**
 * O canal do cliente na Meta: o WABA, o número, a subscrição e a rota.
 *
 * **Esta porta tem, de propósito, as operações destrutivas que a compensação
 * não pode usar** (`apagarWaba`, `apagarNumero`). Não é descuido: um duplo que
 * não as tivesse fazia o critério 7 passar por *impossibilidade de expressar* o
 * erro, e o ticket pede um ensaio que **falhe** se alguém lá puser um `DELETE`.
 * Com elas aqui, o erro é escrevível — e o `compensacao.ts` recusa-o em
 * execução.
 */
export interface CanalDoCliente {
  /** O `phone_number_id` do ES v4, ou `null` enquanto o dono não agir. */
  numeroDoTenant(tenantId: string): Promise<string | null>;
  subscreverWebhooks(wabaId: string): Promise<void>;
  cancelarSubscricao(wabaId: string): Promise<void>;
  removerRota(phoneNumberId: string): Promise<void>;
  /** **Nunca chamada pela compensação.** Existe para o ensaio a poder recusar. */
  apagarWaba(wabaId: string): Promise<void>;
  /** **Nunca chamada pela compensação.** Idem. */
  apagarNumero(phoneNumberId: string): Promise<void>;
}

/** A *inbox* de tipo API (critério 2, passo 7). */
export interface InboxDeAtendimento
  extends Inventario<{ tenantId: string; phoneNumberId: string }, RefExterna> {
  desligar(id: string): Promise<void>;
}

/**
 * A rota do CHR: a linha de `platform.tenant_channels`.
 *
 * **Isto era um `INSERT` neste módulo, e estava errado de três formas.** O
 * critério 2 escreve «*inbox* de tipo API + `tenant_channels` **(CHR)**», e o
 * «(CHR)» é quem a escreve — não a saga. A primeira versão fazia o `INSERT`
 * aqui e falhava sempre contra o esquema real da revisão `0001`:
 *
 * - `channel_mode text NOT NULL` **sem DEFAULT**, omitida → `23502`;
 * - `token_ref text NOT NULL` **sem DEFAULT**, omitida → `23502`;
 * - `estado` escrito como `'onboarding'`, que **não está** no
 *   `tenant_channels_estado_ck` (`pendente`, `ativo`, `restrito`, `desligado`,
 *   `suspenso`, `encerrado`) → `23514`.
 *
 * Nenhuma das quatro *suites* o apanhava: o duplo da base registra o texto da
 * consulta e devolve zero linhas, pelo que a consulta nunca é executada. Foi a
 * revisão adversarial deste ticket que o mediu, lendo o DDL.
 *
 * E o `token_ref` diz porque é que a linha não pode ser da saga: é a referência
 * do *token* do ES, que o **KAM-016** guarda no cofre. A saga não a tem para dar.
 * Credores da implementação: **KAM-014** (CHR) e **KAM-016** (o *token*).
 */
export interface RotaDoCanal {
  /**
   * Garante a rota do tenant. Idempotente por `phone_number_id`, que é único na
   * tabela inteira e não por tenant — o mesmo número por dois tenants é a
   * confusão de canais que o KAM-016 já pagou uma vez.
   */
  garantir(pedido: {
    readonly tenantId: string;
    readonly phoneNumberId: string;
    readonly wabaId: string;
    readonly vertical: string;
  }): Promise<void>;
  /** Remove a rota. **Não** toca no número, que é do cliente. */
  remover(phoneNumberId: string): Promise<void>;
}

/** O teste ponta a ponta do passo 8. Chave natural: o `onboarding_id`. */
export interface TesteDeCanal {
  /** `null` enquanto o teste não tiver corrido: é um estado de espera, não uma falha. */
  resultado(onboardingId: string): Promise<boolean | null>;
}

/** Um recurso do inventário externo, para a reconciliação. */
export interface RecursoInventariado {
  readonly recurso: Recurso;
  readonly ref: string;
  /** O tenant a que diz respeito, quando o recurso o sabe dizer. */
  readonly tenantId: string | null;
  readonly nosso: boolean;
}

/** Quem lista o que está lá fora, para a reconciliação nocturna (critério 8). */
export interface InventarioExterno {
  listar(): Promise<readonly RecursoInventariado[]>;
}

/**
 * As duas classes de divergência do critério 8.
 *
 * `orfao_externo`: está lá fora e não devia (nenhum tenant vivo o reclama).
 * `externo_em_falta`: um tenant vivo tem o passo `concluido` e lá fora não está.
 *
 * São duas e não uma porque a acção é oposta: um órfão compensa-se (se for
 * nosso e o caso estiver cancelado há mais de 24 h), um recurso em falta
 * **recria-se** correndo a saga outra vez. Confundi-las apagava o que faltava.
 */
export const CLASSES_DE_DIVERGENCIA = ["orfao_externo", "externo_em_falta"] as const;
export type ClasseDeDivergencia = (typeof CLASSES_DE_DIVERGENCIA)[number];

/** Uma divergência classificada. */
export interface Divergencia {
  readonly classe: ClasseDeDivergencia;
  readonly recurso: Recurso;
  readonly ref: string;
  readonly tenantId: string | null;
  /** `true` se a saga o criou (tem `ETIQUETA_DA_SAGA`). Decide a compensação automática. */
  readonly nosso: boolean;
  /** `true` quando a reconciliação o compensou nesta passagem. */
  readonly compensado: boolean;
}

/** O que a reconciliação nocturna devolve. */
export interface RelatorioDeReconciliacao {
  readonly divergencias: readonly Divergencia[];
  readonly orfaos: number;
  readonly emFalta: number;
  readonly compensados: number;
}

/**
 * Um passo de espera ainda não tem a entrada de que precisa. **Não é falha.**
 *
 * Os campos declaram-se e atribuem-se **à mão**, sem propriedade de parâmetro:
 * o `node --test` corre o TypeScript em `strip-only` e um `readonly` no
 * construtor é `ERR_UNSUPPORTED_TYPESCRIPT_SYNTAX`. É a mesma restrição em todo
 * o pacote — não há transpilação no caminho dos ensaios.
 *
 * **Não há `SagaEscaladaError`**, e houve: a escalada devolve um `Desfecho` com
 * `estado: "escalada"` e nunca levanta, pelo que a classe estava na superfície
 * pública do pacote para ninguém a poder apanhar num `catch`. Saiu.
 */
export class AguardaEntradaError extends Error {
  readonly passo: Passo;
  readonly espera: Espera;

  constructor(passo: Passo, espera: Espera) {
    super(`o passo ${passo} aguarda a entrada externa (${espera}): nao e falha`);
    this.name = "AguardaEntradaError";
    this.passo = passo;
    this.espera = espera;
  }
}

/**
 * A compensação tentou destruir um recurso do cliente. **Critério 7.**
 *
 * Levanta em vez de ignorar: uma compensação que silenciosamente saltasse a
 * acção proibida deixava quem a escreveu a acreditar que ela corria, e o
 * próximo a ler o código via um `apagarNumero` declarado e nenhum sinal de que
 * nunca acontece.
 */
export class RecursoDoClienteError extends Error {
  readonly accao: AccaoDeCompensacao;
  readonly passo: Passo;

  constructor(accao: AccaoDeCompensacao, passo: Passo) {
    super(
      `a compensacao do passo ${passo} pediu \`${accao.tipo}\` sobre ` +
        `\`${accao.recurso}\`, que e um recurso do cliente (E1): o WABA e o ` +
        "numero sao dele e a compensacao so cancela a subscricao de webhooks " +
        "e remove a rota",
    );
    this.name = "RecursoDoClienteError";
    this.accao = accao;
    this.passo = passo;
  }
}
