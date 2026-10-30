/**
 * A porta `CommerceRegistry` do COM (KAM-042).
 *
 *     contrato.ts   o vocabulário: os doze métodos, o `ctx`, os erros, os
 *                   domínios fechados e o `exigirCtx` que falha fechado
 *
 * A superfície é a `CommerceRegistry`, consumida pela TLS através da API
 * interna do COM. **Nada aqui sabe que Registo está activo** — é essa
 * ignorância que faz do PA-03-1 uma costura e não um desenho: trocar de Registo
 * não altera agentes, PAY nem EVT.
 *
 * Quem implementa está em `../adapters/`; quem impede uma consulta sem filtro
 * está em `../repo-base/`.
 */

export {
  ACTOR_KINDS,
  CtxEmFaltaError,
  ERROS,
  METODOS_DA_PORTA,
  MOTIVOS_DE_LIBERTACAO,
  ORDER_STATES,
  PRECO_TIPOS,
  STOCK_MODOS,
  eUuid,
  erro,
  exigirCtx,
  naoImplementado,
  ok,
  type Actor,
  type ActorKind,
  type Cause,
  type ClienteSql,
  type CommerceRegistry,
  type ComTenant,
  type Ctx,
  type Duration,
  type Erro,
  type MetodoDaPorta,
  type MotivoDeLibertacao,
  type OfferView,
  type OrderFilter,
  type OrderIntent,
  type OrderRef,
  type OrderState,
  type OrderView,
  type OwnerConfirmation,
  type Page,
  type PrecoTipo,
  type ProductDraft,
  type ProductRef,
  type Reservation,
  type Resultado,
  type StockModo,
} from "./contrato.ts";
