/**
 * O início do teste ponta a ponta pela página do dono (KAM-202, critério 2).
 *
 * A página abre a tentativa **pela ligação da aplicação**: o `kamba_app` tem
 * `INSERT` em quatro colunas da `platform.onboarding_smoke` (o caso, o tenant e a
 * janela) e o `resultado` nasce `pendente`; quem a fecha é o processo de lote, como
 * `kamba_batch` (`CicloDaActivacao`). Uma transacção, com o `app.tenant_id` do caso
 * da sessão.
 *
 * O `start` do `SmokeOwnerAssisted` só lê o caso e as tentativas, e só escreve a
 * tentativa: as outras portas do teste (observador, marcador, fila e gates) são do
 * lote, e aqui recusam se alguém as chamar.
 */

import {
  MaquinaSql,
  RegistoDoTesteSql,
  SmokeOwnerAssisted,
  type FilaDoTeste,
  type GatesDaActivacao,
  type MarcadorDeTeste,
  type ObservadorDoTeste,
} from "@kamba/core-ts/activacao";
import type { ConjuntoSql } from "@kamba/core-ts/revisao";
import { comTenant } from "@kamba/core-ts/tenant_guard";

import type { TesteDoPainel } from "./rotas.ts";

function soDoLote(porta: string): () => Promise<never> {
  return async () => {
    throw new Error(`a porta ${porta} do teste e do processo de lote`);
  };
}

const OBSERVADOR: ObservadorDoTeste = { factos: soDoLote("observador") };
const MARCADOR: MarcadorDeTeste = { marcar: soDoLote("marcador") };
const FILA: FilaDoTeste = { abrir: soDoLote("fila") };
const GATES: GatesDaActivacao = { marcar: soDoLote("gates"), emFalta: soDoLote("gates") };

/** O teste do painel sobre o conjunto de ligações do `kamba_app`. */
export function testeDaActivacao(app: ConjuntoSql, relogio?: () => Date): TesteDoPainel {
  return {
    async iniciar(onboardingId, tenantId) {
      const ligacao = await app.connect();
      let estragada: Error | undefined;
      try {
        return await comTenant(ligacao, tenantId, () =>
          new SmokeOwnerAssisted({
            maquina: new MaquinaSql(ligacao),
            registo: new RegistoDoTesteSql(ligacao),
            observador: OBSERVADOR,
            marcador: MARCADOR,
            fila: FILA,
            gates: GATES,
            ...(relogio === undefined ? {} : { relogio }),
          }).start(onboardingId),
        );
      } catch (erro) {
        estragada = erro instanceof Error ? erro : new Error("inicio do teste falhou");
        throw erro;
      } finally {
        ligacao.release(estragada);
      }
    },
  };
}
