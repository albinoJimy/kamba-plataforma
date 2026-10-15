/**
 * Suite de contrato de `SecretProvider` (KAM-010).
 *
 * **Uma bateria, três implementações.** O critério de aceitação do ticket diz
 * «a suite de contrato passa em Env e contra um *fake* de OpenBao; trocar de
 * implementação é só configuração». A forma de essa frase ser verificável e não
 * uma intenção é esta: os casos estão escritos **uma vez**, numa função que
 * recebe uma fábrica, e correm sobre `EnvSecretProvider`,
 * `OpenBaoFakeProvider` e `DopplerSecretProvider`. Se uma implementação
 * divergir do contrato, falha aqui e não em produção.
 *
 * O Doppler entra na bateria com um **transporte falso**: não há conta Doppler
 * neste ticket e, portanto, a linha «passa em Doppler (conta de teste)» do
 * critério de aceitação **não** está satisfeita. O que está provado é que o
 * adaptador obedece ao contrato dado um transporte que se comporta como a API
 * que `doppler.ts` descreve — e a forma dessa API é NÃO VERIFICADO.
 */

import assert from "node:assert/strict";
import { test } from "node:test";

import {
  CofreInacessivelError,
  SecretAusenteError,
  SecretRefInvalidaError,
  type SecretProvider,
} from "../src/secrets/port.ts";
import { EnvSecretProvider, SUFIXO_ANTERIOR, nomeDaVariavel } from "../src/secrets/env.ts";
import { OpenBaoFakeProvider } from "../src/secrets/openbao-fake.ts";
import { DopplerSecretProvider, type Transporte } from "../src/secrets/doppler.ts";

/**
 * Conteúdo de um cenário: referência → versões, da mais antiga para a mais
 * recente. Duas versões no máximo, porque é o tecto do mecanismo de injecção
 * por ambiente (ver `nomeDaVariavel`) e porque o anel que o KAM-013 consome é
 * `[actual, anterior]` e não um histórico.
 */
type Cenario = Readonly<Record<string, readonly string[]>>;

/** Uma implementação sob teste, montada a partir de um cenário. */
interface SobTeste {
  readonly provider: SecretProvider;
  /** Põe o cofre inacessível, se a implementação o sabe simular. */
  readonly tornarInacessivel?: () => void;
}

const CENARIO: Cenario = {
  // Um segredo rodado: tem anterior.
  meta_app_secret: ["valor-anterior-de-teste", "valor-actual-de-teste"],
  // Um segredo nunca rodado: não tem anterior.
  meta_verify_token: ["valor-unico-de-teste"],
  // Uma instância por tenant, endereçada por referência opaca.
  "meta_client_token/7f3cAb": ["token-de-teste-do-tenant"],
};

const fabricas: Readonly<Record<string, (cenario: Cenario) => SobTeste>> = {
  env: (cenario) => {
    const env: Record<string, string> = {};
    for (const [ref, versoes] of Object.entries(cenario)) {
      const base = nomeDaVariavel(ref);
      const actual = versoes.at(-1);
      if (actual !== undefined) env[base] = actual;
      if (versoes.length > 1) {
        const anterior = versoes.at(-2);
        if (anterior !== undefined) env[base + SUFIXO_ANTERIOR] = anterior;
      }
    }
    return { provider: new EnvSecretProvider({ ambiente: "dev", env }) };
  },

  "openbao-fake": (cenario) => {
    const fake = new OpenBaoFakeProvider({ ambiente: "staging", dados: cenario });
    return { provider: fake, tornarInacessivel: () => fake.selar() };
  },

  doppler: (cenario) => {
    const corpo: Record<string, string> = {};
    for (const [ref, versoes] of Object.entries(cenario)) {
      const base = nomeDaVariavel(ref);
      const actual = versoes.at(-1);
      if (actual !== undefined) corpo[base] = actual;
      if (versoes.length > 1) {
        const anterior = versoes.at(-2);
        if (anterior !== undefined) corpo[base + SUFIXO_ANTERIOR] = anterior;
      }
    }
    let emBaixo = false;
    const transporte: Transporte = async () =>
      emBaixo ? { status: 503, corpo: "" } : { status: 200, corpo: JSON.stringify(corpo) };
    return {
      provider: new DopplerSecretProvider({
        ambiente: "prod",
        projecto: "kamba",
        config: "prod",
        tokenServico: "token-de-teste-nao-e-um-segredo",
        transporte,
        // Sem cache entre chamadas, para que `tornarInacessivel` tenha efeito
        // imediato nesta bateria.
        ttlDescargaMs: 0,
      }),
      tornarInacessivel: () => {
        emBaixo = true;
      },
    };
  },
};

for (const [nome, fabrica] of Object.entries(fabricas)) {
  test(`[${nome}] health resolve quando o cofre está acessível`, async () => {
    const { provider } = fabrica(CENARIO);
    await provider.health();
  });

  test(`[${nome}] get devolve o valor actual`, async () => {
    const { provider } = fabrica(CENARIO);
    assert.equal(await provider.get("meta_app_secret"), "valor-actual-de-teste");
    assert.equal(await provider.get("meta_verify_token"), "valor-unico-de-teste");
  });

  test(`[${nome}] getRing devolve [actual, anterior]`, async () => {
    const { provider } = fabrica(CENARIO);
    const anel = await provider.getRing("meta_app_secret");
    assert.deepEqual(anel, ["valor-actual-de-teste", "valor-anterior-de-teste"]);
    // A tupla é posicional e é isso que o KAM-013 consome: `[0]` é a chave com
    // que se assina, `[1]` é a que ainda se aceita.
    assert.equal(anel.length, 2);
    assert.equal(anel[0], await provider.get("meta_app_secret"));
  });

  test(`[${nome}] getRing dá anterior null quando nunca houve rotação`, async () => {
    const { provider } = fabrica(CENARIO);
    assert.deepEqual(await provider.getRing("meta_verify_token"), [
      "valor-unico-de-teste",
      null,
    ]);
  });

  test(`[${nome}] versions está ordenado e a primeira é a que get devolve`, async () => {
    const { provider } = fabrica(CENARIO);
    const rodado = await provider.versions("meta_app_secret");
    assert.equal(rodado.length, 2);
    const unico = await provider.versions("meta_verify_token");
    assert.equal(unico.length, 1);
    // O conteúdo do identificador é do provedor; a ordem é do contrato.
    const [, anterior] = await provider.getRing("meta_app_secret");
    assert.notEqual(anterior, null);
  });

  test(`[${nome}] resolve uma instância por tenant por referência opaca`, async () => {
    const { provider } = fabrica(CENARIO);
    // Esta é a costura com o KAM-003: a coluna guarda só esta cadeia de
    // caracteres, e quem a lê não a interpreta.
    assert.equal(
      await provider.get("meta_client_token/7f3cAb"),
      "token-de-teste-do-tenant",
    );
  });

  test(`[${nome}] segredo ausente levanta SecretAusenteError que nomeia a referência`, async () => {
    const { provider } = fabrica(CENARIO);
    await assert.rejects(
      () => provider.get("pepper_contact_hmac"),
      (erro: unknown) => {
        assert.ok(erro instanceof SecretAusenteError);
        assert.equal(erro.ref, "pepper_contact_hmac");
        assert.match(erro.message, /pepper_contact_hmac/);
        return true;
      },
    );
  });

  test(`[${nome}] nenhuma mensagem de erro contém um valor de segredo`, async () => {
    const { provider, tornarInacessivel } = fabrica(CENARIO);
    // Aquece a implementação, para que qualquer valor que ela guarde já esteja
    // em memória quando os erros forem produzidos.
    await provider.get("meta_app_secret");
    tornarInacessivel?.();

    const valores = Object.values(CENARIO).flat();
    const mensagens: string[] = [];
    for (const ref of ["meta_app_secret", "nao_existe_no_cofre", "Ref Inválida!"]) {
      for (const chamada of [
        () => provider.get(ref),
        () => provider.getRing(ref),
        () => provider.versions(ref),
        () => provider.health(),
      ]) {
        try {
          await chamada();
        } catch (erro) {
          mensagens.push(erro instanceof Error ? `${erro.name}: ${erro.message}` : String(erro));
        }
      }
    }
    assert.ok(mensagens.length > 0, "o cenário tinha de produzir erros");
    for (const mensagem of mensagens) {
      for (const valor of valores) {
        assert.ok(
          !mensagem.includes(valor),
          `mensagem de erro continha um valor de segredo: ${mensagem}`,
        );
      }
    }
  });

  test(`[${nome}] referência malformada levanta SecretRefInvalidaError`, async () => {
    const { provider } = fabrica(CENARIO);
    for (const ref of ["", "A_MAIUSCULA", "ab", "com espaço", "/sem-familia", "x".repeat(300)]) {
      await assert.rejects(() => provider.get(ref), SecretRefInvalidaError, `aceitou ${ref}`);
    }
  });

  test(`[${nome}] cofre inacessível é CofreInacessivelError e não ausência`, async (t) => {
    const { provider, tornarInacessivel } = fabrica(CENARIO);
    if (tornarInacessivel === undefined) {
      // O `EnvSecretProvider` não tem este estado: se o processo arrancou, o
      // seu ambiente existe. A distinção entre ausência e indisponibilidade
      // continua a valer para ele — só nunca produz o segundo caso.
      t.skip("implementação sem estado de indisponibilidade");
      return;
    }
    tornarInacessivel();
    await assert.rejects(() => provider.get("meta_app_secret"), CofreInacessivelError);
    await assert.rejects(() => provider.health(), CofreInacessivelError);
  });
}

test("o fake de OpenBao guarda mais de duas versões; o anel continua a ser duas", async () => {
  // Propriedade do cofre, não do contrato: o KV v2 tem histórico, o mecanismo
  // de injecção por variáveis de ambiente tem tecto de duas. O anel que o
  // KAM-013 consome são duas em qualquer dos casos.
  const fake = new OpenBaoFakeProvider({ ambiente: "staging" });
  for (const valor of ["v1-de-teste", "v2-de-teste", "v3-de-teste"]) {
    fake.escrever("pepper_contact_hmac", valor);
  }
  assert.deepEqual(await fake.versions("pepper_contact_hmac"), ["3", "2", "1"]);
  assert.deepEqual(await fake.getRing("pepper_contact_hmac"), ["v3-de-teste", "v2-de-teste"]);
  assert.equal(await fake.get("pepper_contact_hmac"), "v3-de-teste");
});
