/**
 * `@kamba/core-ts/logger`: a *allowlist*, as formas e as recusas (KAM-068).
 *
 * É o espelho de `libs/py-core/tests/test_logger.py`, e as duas baterias leem
 * os **mesmos** vectores (`tests/fixtures/logger_paridade.json`): é essa tabela
 * que diz o que as duas linguagens têm de aceitar e recusar.
 *
 * O que só existe aqui é a metade de compilação do critério — «um campo fora
 * da lista é um erro de compilação em TypeScript». Prova-se com
 * `@ts-expect-error`: se uma dessas linhas passar a compilar, o `tsc` do gate 2
 * falha com «Unused '@ts-expect-error' directive».
 *
 * Este módulo está no estrato `critico` de `ci/thresholds.yaml` (90%).
 */

import assert from "node:assert/strict";
import { spawnSync } from "node:child_process";
import { readFileSync } from "node:fs";
import { fileURLToPath } from "node:url";
import { test } from "node:test";

import {
  CAMPOS,
  CAMPOS_DE_CHAMADA,
  CAMPOS_RESERVADOS,
  CODIGO_NAO_TRATADA,
  CONTADORES,
  CampoRejeitadoError,
  type CamposDeLog,
  Logger,
  METRICA_ESCRITA_FALHADA,
  METRICA_REJEITADOS,
  MOTIVOS,
  NIVEIS,
  OUTCOME_NAO_TRATADA,
  type ProcessoMinimo,
  ServicoInvalidoError,
  VARIAVEL_ESTRITO,
  idOpaco,
  instalar,
  mascararReferencia,
} from "../src/logger/index.ts";
import { codigoComClasse, nomeLegivel, validar, validarSvc } from "../src/logger/politica.ts";

interface Vectores {
  campos: string[];
  campos_reservados: string[];
  niveis: string[];
  motivos: string[];
  metrica_rejeitados: string;
  metrica_escrita_falhada: string;
  variavel_estrito: string;
  svc: { valor: unknown; aceite: boolean }[];
  validar: { campo: string; valor: unknown; saida: string | number | null }[];
  casos: {
    nome: string;
    nivel: unknown;
    posicionais: unknown[];
    campos: Record<string, unknown>;
    erro?: { classe: string; mensagem: string };
    codigo?: string;
    linha: string;
    rejeicoes: Record<string, number>;
  }[];
  id_opaco: { entrada: string; saida: string }[];
  mascarar_referencia: { entrada: unknown; saida: string }[];
}

const VECTORES = JSON.parse(
  readFileSync(new URL("./fixtures/logger_paridade.json", import.meta.url), "utf8"),
) as Vectores;

const PARADO = new Date("2026-01-01T00:00:00.000Z");
const TENANT = "0b6f1d2e-3c4a-4b5c-8d6e-7f8091a2b3c4";

/**
 * Canários: nenhum pode aparecer na saída, por nenhum caminho. Todos
 * inventados. O token é montado por partes para não ter, no repositório, a
 * forma de um.
 */
const CANARIOS: Readonly<Record<string, string>> = {
  telefone_internacional: "+244 923 456 789",
  telefone_colado: "+244923456789",
  telefone_sem_mais: "244 923 456 789",
  telefone_nacional: "923456789",
  telefone_com_pontos: "923.456.789",
  telefone_com_hifenes: "923-456-789",
  nif_colectivo: "5417123456",
  nif_singular: "004567890LA045",
  email: "joaquina.canario@exemplo.co.ao",
  texto: "Bom dia, queria encomendar duas pizzas para o Kilamba",
  transcricao: "mana, manda o comprovativo que o mano ja transferiu",
  nome: "Joaquina Canario dos Santos",
  morada: "Rua do Canario 12, Bairro Operario, Luanda",
  token: `EAA${"x9".repeat(30)}`,
  portador: `Bearer tk${"9z".repeat(14)}`,
  iban: "AO06004000001234567890123",
  iban_espacado: "AO06 0040 0000 1234 5678 9012 3",
  referencia: "00123 456 789 012",
  provider_event_id: `evt_${"3kQ9xZ2mP7aLw8Tn5VbR1cYd"}`,
  wamid: "wamid.HBgMMjQ0OTIzNDU2Nzg5FQIAEhgUM0FCQ0RFRjAxMjM0NTY3ODlBQkMA",
};
const DIGITOS = ["923456789", "5417123456", "004567890", "0040000012345"];

class Saida {
  texto = "";

  write(pedaco: string): void {
    this.texto += pedaco;
  }

  linhas(): Record<string, unknown>[] {
    return this.texto
      .split("\n")
      .filter((linha) => linha !== "")
      .map((linha) => JSON.parse(linha) as Record<string, unknown>);
  }
}

function novo(estrito = false, svc = "paridade"): [Logger, Saida] {
  const saida = new Saida();
  return [new Logger(svc, { destino: saida, relogio: () => PARADO, estrito }), saida];
}

function rejeicoes(): Record<string, number> {
  const prefixo = `${METRICA_REJEITADOS}:`;
  return Object.fromEntries(
    Object.entries(CONTADORES.ler())
      .filter(([nome]) => nome.startsWith(prefixo))
      .map(([nome, valor]) => [nome.slice(prefixo.length), valor]),
  );
}

/** Uma excepção cuja classe tem o nome dado (como o condutor do X-11). */
function erroComClasse(classe: string, mensagem: string): Error {
  const Classe = { [classe]: class extends Error {} }[classe] as new (m: string) => Error;
  return new Classe(mensagem);
}

function semCanarios(texto: string): void {
  for (const [nome, canario] of Object.entries(CANARIOS)) {
    assert.ok(!texto.includes(canario), nome);
  }
  for (const digitos of DIGITOS) {
    assert.ok(!texto.includes(digitos), digitos);
  }
}

/** A porta sem tipos: o que chega de JavaScript, ou atrás de um `as`. */
function semTipos(registo: Logger, nivel: unknown, campos: unknown, posicionais: unknown[] = []): void {
  registo.registar(nivel, posicionais, campos);
}

// --- A política ---------------------------------------------------------------

test("a allowlist e exactamente a de docs/tecnica/08 §7.3", () => {
  assert.deepEqual(
    [...CAMPOS],
    [
      "ts", "level", "svc", "tenant_id", "contact_hmac_prefix", "turn_id",
      "msg_id", "wa_type", "latency_ms", "tool", "outcome", "error_code",
    ],
  );
  const documento = readFileSync(
    new URL("../../../docs/tecnica/08_Seguranca_Conformidade.md", import.meta.url),
    "utf8",
  );
  const inicio = documento.indexOf("### 7.3 Logs sem conteúdo");
  const marcador = "*allowlist* de campos: `";
  const lista = documento.indexOf(marcador, inicio) + marcador.length;
  assert.ok(inicio > 0 && lista > inicio);
  const doDocumento = documento
    .slice(lista, documento.indexOf("`", lista))
    .split(",")
    .map((campo) => campo.trim());
  assert.deepEqual([...CAMPOS], doDocumento);
});

test("os vectores dizem a mesma politica", () => {
  assert.deepEqual([...CAMPOS], VECTORES.campos);
  assert.deepEqual([...CAMPOS_RESERVADOS], VECTORES.campos_reservados);
  assert.deepEqual([...NIVEIS], VECTORES.niveis);
  assert.deepEqual([...MOTIVOS], VECTORES.motivos);
  assert.equal(METRICA_REJEITADOS, VECTORES.metrica_rejeitados);
  assert.equal(METRICA_ESCRITA_FALHADA, VECTORES.metrica_escrita_falhada);
  assert.equal(VARIAVEL_ESTRITO, VECTORES.variavel_estrito);
  assert.deepEqual([...CAMPOS_RESERVADOS, ...CAMPOS_DE_CHAMADA], [...CAMPOS]);
});

// --- Os vectores de paridade ----------------------------------------------------

test("vectores: validar, campo a campo", () => {
  assert.ok(VECTORES.validar.length >= 100);
  for (const caso of VECTORES.validar) {
    assert.equal(
      validar(caso.campo, caso.valor),
      caso.saida,
      `${caso.campo} = ${JSON.stringify(caso.valor)}`,
    );
  }
});

test("vectores: nomes de servico", () => {
  for (const caso of VECTORES.svc) {
    const rotulo = JSON.stringify(caso.valor);
    assert.equal(validarSvc(caso.valor) !== null, caso.aceite, rotulo);
    if (caso.aceite) {
      assert.equal(new Logger(caso.valor as string, { destino: new Saida() }).svc, caso.valor);
    } else {
      assert.throws(
        () => new Logger(caso.valor as string, { destino: new Saida() }),
        ServicoInvalidoError,
        rotulo,
      );
    }
  }
});

test("vectores: casos, linha a linha", () => {
  assert.ok(VECTORES.casos.length >= 15);
  for (const caso of VECTORES.casos) {
    CONTADORES.repor();
    const [registo, saida] = novo();
    if (caso.erro !== undefined) {
      registo.excepcao(
        erroComClasse(caso.erro.classe, caso.erro.mensagem),
        caso.codigo as string,
        caso.campos as never,
      );
    } else {
      semTipos(registo, caso.nivel, caso.campos, caso.posicionais);
    }
    assert.equal(saida.texto, `${caso.linha}\n`, caso.nome);
    assert.deepEqual(rejeicoes(), caso.rejeicoes, caso.nome);
  }
});

test("vectores: idOpaco e mascararReferencia", () => {
  for (const caso of VECTORES.id_opaco) {
    assert.equal(idOpaco(caso.entrada), caso.saida);
    assert.equal(validar("msg_id", caso.saida), caso.saida);
  }
  for (const caso of VECTORES.mascarar_referencia) {
    assert.equal(mascararReferencia(caso.entrada), caso.saida, JSON.stringify(caso.entrada));
  }
});

// --- A linha --------------------------------------------------------------------

test("uma linha JSON por chamada, com os campos pela ordem da lista", () => {
  CONTADORES.repor();
  const [registo, saida] = novo();
  registo.info({ outcome: "ok", tenant_id: TENANT, latency_ms: 3 });
  registo.warn({ tool: "criar_pedido" });
  registo.debug();
  registo.error();
  assert.equal(saida.texto.split("\n").length - 1, 4);
  const linhas = saida.linhas();
  assert.deepEqual(Object.keys(linhas[0] ?? {}), [
    "ts", "level", "svc", "tenant_id", "latency_ms", "outcome",
  ]);
  assert.deepEqual(linhas.map((linha) => linha.level), ["info", "warn", "debug", "error"]);
  assert.deepEqual(linhas[2], { ts: "2026-01-01T00:00:00.000Z", level: "debug", svc: "paridade" });
  assert.deepEqual(CONTADORES.ler(), {});
});

test("o relogio por omissao e o de agora, em UTC com milissegundos", () => {
  const saida = new Saida();
  const antes = Date.now();
  new Logger("gwy", { destino: saida }).info();
  const ts = saida.linhas()[0]?.ts as string;
  assert.match(ts, /^\d{4}-\d\d-\d\dT\d\d:\d\d:\d\d\.\d{3}Z$/);
  assert.ok(Date.parse(ts) >= antes - 1 && Date.parse(ts) < antes + 30_000);
});

test("o destino por omissao e o process.stdout", (t) => {
  const escrito: string[] = [];
  t.mock.method(process.stdout, "write", (pedaco: string) => {
    escrito.push(pedaco);
    return true;
  });
  new Logger("gwy", { relogio: () => PARADO }).info({ outcome: "ok" });
  t.mock.restoreAll();
  assert.deepEqual(escrito, [
    '{"ts":"2026-01-01T00:00:00.000Z","level":"info","svc":"gwy","outcome":"ok"}\n',
  ]);
});

// --- Os canários ----------------------------------------------------------------

test("canarios: em cada campo da allowlist", () => {
  CONTADORES.repor();
  const [registo, saida] = novo();
  const canarios = Object.values(CANARIOS);
  for (const campo of CAMPOS_DE_CHAMADA) {
    for (const canario of canarios) {
      semTipos(registo, "info", { [campo]: canario, [campo === "outcome" ? "tool" : "outcome"]: "ok" });
    }
  }
  semCanarios(saida.texto);
  const esperadas = CAMPOS_DE_CHAMADA.length * canarios.length;
  assert.equal(saida.linhas().length, esperadas);
  assert.deepEqual(rejeicoes(), { valor_invalido: esperadas });
});

test("canarios: em campos que nao existem, e como nome do campo", () => {
  CONTADORES.repor();
  const [registo, saida] = novo();
  const proibidos = [
    "telefone", "nome", "morada", "texto", "transcricao", "email", "nif", "iban",
    "referencia", "provider_event_id", "extra", "contexto", "message",
  ];
  for (const canario of Object.values(CANARIOS)) {
    for (const campo of proibidos) {
      semTipos(registo, "info", { [campo]: canario });
    }
    semTipos(registo, "info", { [canario]: "ok", outcome: "ok" });
  }
  semCanarios(saida.texto);
  assert.deepEqual(Object.keys(rejeicoes()), ["campo_desconhecido"]);
});

test("canarios: aninhados em objectos e listas, a qualquer profundidade", () => {
  CONTADORES.repor();
  const [registo, saida] = novo();
  for (const canario of Object.values(CANARIOS)) {
    const fundo = { a: [{ b: { c: [canario, { telefone: canario }] } }] };
    semTipos(registo, "error", {
      tool: fundo,
      outcome: [canario],
      error_code: [[canario]],
      contexto: fundo,
      extra: { headers: { Authorization: canario } },
      wa_type: new Set([canario]),
      latency_ms: new Map([[canario, canario]]),
    });
  }
  semCanarios(saida.texto);
  for (const linha of saida.linhas()) {
    assert.deepEqual(Object.keys(linha), ["ts", "level", "svc"]);
  }
});

test("canarios: em posicionais e no lugar dos campos", () => {
  CONTADORES.repor();
  const [registo, saida] = novo();
  for (const canario of Object.values(CANARIOS)) {
    semTipos(registo, "info", undefined, [canario]);
    semTipos(registo, "error", { outcome: "erro" }, ["falhou para %s", canario, { telefone: canario }]);
    semTipos(registo, "info", canario);
    semTipos(registo, "info", [canario]);
    semTipos(registo, "info", 923456789);
  }
  semCanarios(saida.texto);
  assert.deepEqual(rejeicoes(), { mensagem_livre: 7 * Object.keys(CANARIOS).length });
});

test("canarios: na mensagem, na causa e nas propriedades de um erro", () => {
  CONTADORES.repor();
  const [registo, saida] = novo();
  for (const canario of Object.values(CANARIOS)) {
    const erro = new RangeError(`nao foi possivel entregar a ${canario}`, {
      cause: new Error(canario),
    });
    Object.assign(erro, { telefone: canario, name: canario, code: canario });
    erro.stack = `${canario}\n    at ${canario}`;
    registo.excepcao(erro, "entrega_falhada", { tenant_id: TENANT });
  }
  semCanarios(saida.texto);
  for (const linha of saida.linhas()) {
    assert.equal(linha.error_code, "entrega_falhada:RangeError");
    assert.equal(linha.level, "error");
  }
  assert.deepEqual(rejeicoes(), {});
});

test("canarios: no nome da classe e no codigo do erro", () => {
  const [registo, saida] = novo();
  for (const canario of Object.values(CANARIOS)) {
    const classe = `E${canario.replace(/[^A-Za-z0-9]/g, "")}`;
    registo.excepcao(erroComClasse(classe, "x"), "entrega_falhada");
    registo.excepcao(new Error("x"), canario);
    registo.excepcao(new Error("x"), { codigo: canario } as unknown as string);
  }
  semCanarios(saida.texto);
});

test("canarios: cabecalhos com segredo dao zero", () => {
  const segredo = ["canario", "de", "cabecalho"].join("-");
  const cabecalhos: Record<string, string> = {
    Authorization: `Bearer ${segredo}`,
    authorization: `Bearer ${segredo}`,
    "X-Signature": `sha256=${segredo}`,
    "X-Hub-Signature-256": `sha256=${segredo}`,
    Cookie: `sessao=${segredo}`,
    "Set-Cookie": `sessao=${segredo}`,
    webhook_token: segredo,
    "Content-Type": "application/json",
  };
  const [registo, saida] = novo();
  semTipos(registo, "info", cabecalhos);
  semTipos(registo, "info", { headers: cabecalhos, outcome: "ok" });
  semTipos(registo, "info", new Headers(cabecalhos));
  semTipos(registo, "info", { tool: cabecalhos, error_code: Object.values(cabecalhos) });
  for (const valor of Object.values(cabecalhos)) {
    semTipos(registo, "info", { outcome: valor, error_code: valor, tool: valor, wa_type: valor });
  }
  assert.ok(!saida.texto.includes(segredo));
  for (const nome of Object.keys(cabecalhos)) {
    assert.ok(!saida.texto.includes(nome), nome);
  }
  assert.ok(!saida.texto.includes("application/json"));
});

test("canarios: em campos reservados", () => {
  CONTADORES.repor();
  const [registo, saida] = novo();
  for (const canario of Object.values(CANARIOS)) {
    semTipos(registo, "info", { ts: canario, level: canario, svc: canario });
  }
  semCanarios(saida.texto);
  for (const linha of saida.linhas()) {
    assert.deepEqual(linha, { ts: "2026-01-01T00:00:00.000Z", level: "info", svc: "paridade" });
  }
  assert.deepEqual(rejeicoes(), { campo_reservado: 3 * Object.keys(CANARIOS).length });
});

test("canarios: embutidos num identificador com boa cara", () => {
  const [registo, saida] = novo();
  for (const embutido of [
    "ok_923456789", "ok_923_456_789", "erro.923.456.789", "nif_5417123456",
    "ok_ao06004000001234567890123", "E923456789", "x923456789x",
  ]) {
    registo.info({ outcome: embutido, tool: embutido, wa_type: embutido, error_code: embutido });
  }
  for (const digitos of ["923456789", "923_456_789", "923.456.789", "5417123456", "0040000012345"]) {
    assert.ok(!saida.texto.includes(digitos), digitos);
  }
});

test("canarios: como nome do servico, a mensagem nao o repete", () => {
  for (const canario of Object.values(CANARIOS)) {
    assert.throws(
      () => new Logger(canario, { destino: new Saida() }),
      (erro: unknown) => {
        assert.ok(erro instanceof ServicoInvalidoError);
        assert.equal(erro.name, "ServicoInvalidoError");
        assert.ok(!erro.message.includes(canario));
        return true;
      },
    );
  }
});

// --- Nunca lança ------------------------------------------------------------------

test("um valor armadilhado nao e convertido", () => {
  const tocado: string[] = [];
  const armadilha = {
    toString(): string {
      tocado.push("toString");
      throw new Error("efeito lateral de quem chamou");
    },
    valueOf(): number {
      tocado.push("valueOf");
      throw new Error("efeito lateral de quem chamou");
    },
    toJSON(): string {
      tocado.push("toJSON");
      throw new Error("efeito lateral de quem chamou");
    },
  };
  const [registo, saida] = novo();
  semTipos(registo, "info", {
    outcome: armadilha,
    tenant_id: armadilha,
    latency_ms: armadilha,
    telefone: armadilha,
  });
  semTipos(registo, armadilha, armadilha, [armadilha]);
  registo.excepcao(armadilha, armadilha as unknown as string);
  registo.excepcao(Object.create(null), "sem_prototipo");
  assert.deepEqual(tocado, []);
  assert.equal(saida.linhas().length, 4);
});

test("um getter que lanca, e um proxy que lanca, nao derrubam a chamada", () => {
  CONTADORES.repor();
  const [registo, saida] = novo();
  const comGetter = {
    outcome: "ok",
    get tool(): string {
      throw new Error("923456789");
    },
  };
  semTipos(registo, "info", comGetter);
  const proxy = new Proxy(
    {},
    {
      ownKeys(): never {
        throw new Error("923456789");
      },
      getPrototypeOf(): never {
        throw new Error("923456789");
      },
    },
  );
  semTipos(registo, "info", proxy);
  registo.excepcao(proxy, "com_proxy");
  registo.excepcao(new Error("x"), "com_campos_armadilhados", proxy as never);
  semCanarios(saida.texto);
  assert.deepEqual(
    saida.linhas().map((linha) => [linha.outcome, linha.error_code]),
    [
      ["ok", undefined],
      [undefined, undefined],
      [undefined, "com_proxy"],
      [undefined, "com_campos_armadilhados:Error"],
    ],
  );
  assert.deepEqual(rejeicoes(), { valor_invalido: 1, mensagem_livre: 1 });
});

test("um destino que falha conta e segue", () => {
  CONTADORES.repor();
  const partido = {
    write(): never {
      throw new Error("disco cheio");
    },
  };
  const registo = new Logger("gwy", { destino: partido, relogio: () => PARADO });
  registo.info({ outcome: "ok" });
  registo.error({ outcome: "erro" });
  assert.deepEqual(CONTADORES.ler(), { [METRICA_ESCRITA_FALHADA]: 2 });
});

test("um erro que nao e um objecto fica sem classe", () => {
  const [registo, saida] = novo();
  registo.excepcao(null, "sem_erro");
  registo.excepcao(undefined, "sem_erro");
  registo.excepcao("texto 923456789", "sem_erro");
  registo.excepcao({ message: "923456789" }, "sem_erro");
  assert.deepEqual(
    saida.linhas().map((linha) => linha.error_code),
    ["sem_erro", "sem_erro", "sem_erro", "sem_erro:Object"],
  );
  semCanarios(saida.texto);
});

// --- Modo estrito -----------------------------------------------------------------

test("estrito: um campo fora da lista lanca e nao escreve", () => {
  CONTADORES.repor();
  const [registo, saida] = novo(true);
  assert.throws(
    () => semTipos(registo, "info", { telefone: "923456789", outcome: "ok" }),
    (erro: unknown) => {
      assert.ok(erro instanceof CampoRejeitadoError);
      assert.equal(erro.name, "CampoRejeitadoError");
      assert.deepEqual(erro.rejeicoes, [["campo_desconhecido", "telefone"]]);
      return true;
    },
  );
  assert.equal(saida.texto, "");
  assert.deepEqual(CONTADORES.ler(), {});
});

test("estrito: cada motivo lanca", () => {
  const [registo, saida] = novo(true);
  const chamadas: Record<string, () => void> = {
    campo_desconhecido: () => semTipos(registo, "info", { nome: "x" }),
    campo_reservado: () => semTipos(registo, "info", { svc: "outro" }),
    valor_invalido: () => registo.info({ outcome: "Nao E Um Identificador" }),
    mensagem_livre: () => semTipos(registo, "info", "texto livre"),
  };
  assert.deepEqual(Object.keys(chamadas).sort(), [...MOTIVOS].sort());
  for (const [motivo, chamada] of Object.entries(chamadas)) {
    assert.throws(chamada, (erro: unknown) => {
      assert.ok(erro instanceof CampoRejeitadoError);
      assert.deepEqual(erro.rejeicoes.map(([m]) => m), [motivo]);
      return true;
    });
  }
  assert.throws(() => semTipos(registo, "verboso", {}), CampoRejeitadoError);
  assert.throws(() => registo.excepcao(new Error("x"), "codigo com espacos"), CampoRejeitadoError);
  assert.equal(saida.texto, "");
});

test("estrito: a mensagem diz o nome e nunca o valor", () => {
  const [registo] = novo(true);
  for (const canario of Object.values(CANARIOS)) {
    assert.throws(
      () =>
        semTipos(
          registo,
          "info",
          { telefone: canario, outcome: canario, svc: canario, ts: canario, [canario]: canario },
          [canario],
        ),
      (erro: unknown) => {
        assert.ok(erro instanceof CampoRejeitadoError);
        assert.ok(!erro.message.includes(canario));
        assert.ok(erro.message.includes("campo_desconhecido (telefone)"));
        assert.ok(erro.message.includes("valor_invalido (outcome)"));
        assert.ok(erro.message.includes("campo_reservado (svc)"));
        assert.ok(erro.message.includes("campo_desconhecido (<nome ilegivel>)"));
        assert.ok(erro.message.includes("mensagem_livre (<posicional>)"));
        assert.ok(!JSON.stringify(erro.rejeicoes).includes(canario));
        return true;
      },
    );
  }
});

test("estrito: uma chamada limpa escreve normalmente", () => {
  const [registo, saida] = novo(true);
  registo.info({ outcome: "ok", tenant_id: TENANT });
  registo.excepcao(new Error("x"), "entrega_falhada");
  assert.equal(saida.linhas().length, 2);
});

test("estrito: liga-se pela variavel de ambiente, e so com 1", () => {
  const antes = process.env[VARIAVEL_ESTRITO];
  try {
    for (const [valor, esperado] of [["1", true], ["0", false], ["", false], ["true", false]] as const) {
      process.env[VARIAVEL_ESTRITO] = valor;
      assert.equal(new Logger("gwy", { destino: new Saida() }).estrito, esperado, valor);
    }
    delete process.env[VARIAVEL_ESTRITO];
    assert.equal(new Logger("gwy", { destino: new Saida() }).estrito, false);
    process.env[VARIAVEL_ESTRITO] = "1";
    assert.equal(new Logger("gwy", { destino: new Saida(), estrito: false }).estrito, false);
  } finally {
    if (antes === undefined) {
      delete process.env[VARIAVEL_ESTRITO];
    } else {
      process.env[VARIAVEL_ESTRITO] = antes;
    }
  }
});

test("tolerante e o mesmo logger, fora do modo estrito", (t) => {
  const [registo, saida] = novo(true);
  const tolerante = registo.tolerante();
  assert.equal(tolerante.estrito, false);
  assert.equal(tolerante.svc, registo.svc);
  semTipos(tolerante, "info", { telefone: "923456789", outcome: "ok" });
  assert.deepEqual(saida.linhas(), [
    { ts: "2026-01-01T00:00:00.000Z", level: "info", svc: "paridade", outcome: "ok" },
  ]);
  // Sem destino próprio, o tolerante continua a escrever no `process.stdout`.
  const escrito: string[] = [];
  t.mock.method(process.stdout, "write", (pedaco: string) => {
    escrito.push(pedaco);
    return true;
  });
  new Logger("gwy", { estrito: true, relogio: () => PARADO }).tolerante().info({ outcome: "ok" });
  t.mock.restoreAll();
  assert.equal(escrito.length, 1);
});

// --- Excepções por tratar ---------------------------------------------------------

class ProcessoFalso implements ProcessoMinimo {
  readonly tratadores = new Map<string, (...argumentos: unknown[]) => void>();
  readonly saidas: (number | undefined)[] = [];

  readonly retirados: string[] = [];

  on(evento: string, tratador: (...argumentos: unknown[]) => void): this {
    this.tratadores.set(evento, tratador);
    return this;
  }

  removeAllListeners(evento: string): this {
    this.retirados.push(evento);
    return this;
  }

  exit(codigo?: number): void {
    this.saidas.push(codigo);
  }
}

test("instalar: devolve o logger e liga os dois ganchos do processo", () => {
  const processo = new ProcessoFalso();
  const saida = new Saida();
  const registo = instalar("gwy", { destino: saida, relogio: () => PARADO, processo, estrito: true });
  assert.ok(registo instanceof Logger);
  assert.equal(registo.svc, "gwy");
  assert.equal(registo.estrito, true);
  assert.deepEqual(
    [...processo.tratadores.keys()],
    ["uncaughtException", "unhandledRejection", "warning"],
  );
  // O ouvinte de origem do Node, que imprime o texto do aviso, é retirado.
  assert.deepEqual(processo.retirados, ["warning"]);
});

test("instalar: um aviso do processo sai pela classe, sem o texto", () => {
  const processo = new ProcessoFalso();
  const saida = new Saida();
  instalar("gwy", { destino: saida, relogio: () => PARADO, processo, estrito: true });
  class DeprecationWarning extends Error {}
  for (const canario of Object.values(CANARIOS)) {
    processo.tratadores.get("warning")?.(new DeprecationWarning(`cliente ${canario} excedeu`));
    processo.tratadores.get("warning")?.(canario);
  }
  semCanarios(saida.texto);
  assert.deepEqual(saida.linhas().slice(0, 2), [
    {
      ts: "2026-01-01T00:00:00.000Z",
      level: "warn",
      svc: "gwy",
      outcome: "aviso_do_processo",
      error_code: "aviso_do_processo:DeprecationWarning",
    },
    {
      ts: "2026-01-01T00:00:00.000Z",
      level: "warn",
      svc: "gwy",
      outcome: "aviso_do_processo",
      error_code: "aviso_do_processo",
    },
  ]);
  assert.deepEqual(processo.saidas, []);
});

test("instalar: a mensagem de um erro por tratar nao sai nem com cara de identificador", () => {
  const processo = new ProcessoFalso();
  const saida = new Saida();
  instalar("gwy", { destino: saida, relogio: () => PARADO, processo });
  processo.tratadores.get("uncaughtException")?.(new Error("pizza"));
  processo.tratadores.get("warning")?.(new Error("pizza"));
  const [registo] = [new Logger("gwy", { destino: saida, relogio: () => PARADO })];
  registo.excepcao(new Error("pizza"), "entrega_falhada");
  assert.ok(!saida.texto.includes("pizza"));
  assert.equal(saida.linhas().length, 3);
  for (const linha of saida.linhas()) {
    assert.ok(Object.keys(linha).every((campo) => ["ts", "level", "svc", "outcome", "error_code"].includes(campo)));
  }
});

test("um relogio que falha ou mente nao escreve nem lanca", () => {
  const relogios: (() => Date)[] = [
    () => {
      throw new Error("923456789");
    },
    () => null as unknown as Date,
    () => new Date(Number.NaN),
    () => ({ toISOString: () => "923456789" }) as unknown as Date,
    () => Object.assign(new Date(0), { toISOString: () => "923456789" }),
  ];
  for (const [indice, relogio] of relogios.entries()) {
    CONTADORES.repor();
    const saida = new Saida();
    new Logger("gwy", { destino: saida, relogio, estrito: true }).info({ outcome: "ok" });
    if (indice === 4) {
      // Um `Date` verdadeiro com o método trocado: usa-se o do protótipo.
      assert.equal(saida.linhas()[0]?.ts, "1970-01-01T00:00:00.000Z");
    } else {
      assert.equal(saida.texto, "", String(indice));
      assert.deepEqual(CONTADORES.ler(), { [METRICA_ESCRITA_FALHADA]: 1 });
    }
  }
});

test("excepcao sem codigo, e posicionais que nao sao uma lista, nao lancam", () => {
  CONTADORES.repor();
  const [registo, saida] = novo();
  registo.excepcao(new Error("923456789"));
  semTipos(registo, "info", { outcome: "ok" }, null as unknown as unknown[]);
  semTipos(registo, "info", { outcome: "ok" }, "pedido de 923456789" as unknown as unknown[]);
  semTipos(registo, "info", { outcome: "ok" }, 5 as unknown as unknown[]);
  assert.equal(saida.linhas().length, 4);
  assert.deepEqual(Object.keys(saida.linhas()[0] ?? {}), ["ts", "level", "svc"]);
  assert.deepEqual(rejeicoes(), { mensagem_livre: 2 });
  semCanarios(saida.texto);
});

test("instalar: um erro por tratar sai pela classe, sem mensagem nem pilha, e termina com 1", () => {
  const processo = new ProcessoFalso();
  const saida = new Saida();
  instalar("gwy", { destino: saida, relogio: () => PARADO, processo, estrito: true });
  for (const canario of Object.values(CANARIOS)) {
    processo.tratadores.get("uncaughtException")?.(new TypeError(`PORT invalida: ${canario}`));
    processo.tratadores.get("unhandledRejection")?.(new RangeError(canario), Promise.resolve());
    processo.tratadores.get("unhandledRejection")?.(canario);
    processo.tratadores.get("uncaughtException")?.(erroComClasse("E244923456789", canario));
  }
  semCanarios(saida.texto);
  assert.ok(!saida.texto.includes(" at "));
  const quantos = Object.keys(CANARIOS).length;
  assert.equal(saida.linhas().length, 4 * quantos);
  assert.deepEqual(saida.linhas().slice(0, 4), [
    {
      ts: "2026-01-01T00:00:00.000Z",
      level: "error",
      svc: "gwy",
      outcome: OUTCOME_NAO_TRATADA,
      error_code: `${CODIGO_NAO_TRATADA}:TypeError`,
    },
    {
      ts: "2026-01-01T00:00:00.000Z",
      level: "error",
      svc: "gwy",
      outcome: OUTCOME_NAO_TRATADA,
      error_code: `${CODIGO_NAO_TRATADA}:RangeError`,
    },
    {
      ts: "2026-01-01T00:00:00.000Z",
      level: "error",
      svc: "gwy",
      outcome: OUTCOME_NAO_TRATADA,
      error_code: CODIGO_NAO_TRATADA,
    },
    {
      ts: "2026-01-01T00:00:00.000Z",
      level: "error",
      svc: "gwy",
      outcome: OUTCOME_NAO_TRATADA,
      error_code: CODIGO_NAO_TRATADA,
    },
  ]);
  assert.deepEqual(processo.saidas, new Array(4 * quantos).fill(1));
});

test("instalar: num processo a serio, o stderr fica vazio e o stdout so tem a linha", () => {
  const guiao = fileURLToPath(new URL("./fixtures/processo_que_rebenta.ts", import.meta.url));
  const canario = "+244 923 456 789";
  const esperado: Record<string, [number, string, string]> = {
    excepcao: [1, "error", "excepcao_nao_tratada:TypeError"],
    rejeicao: [1, "error", "excepcao_nao_tratada:RangeError"],
    aviso: [0, "warn", "aviso_do_processo:Error"],
  };
  for (const [modo, [codigo, nivel, erro]] of Object.entries(esperado)) {
    const filho = spawnSync(process.execPath, [guiao, modo, canario], { encoding: "utf8" });
    assert.equal(filho.status, codigo, modo);
    // O que o Node escreveria por conta própria ia para aqui: a pilha, a
    // mensagem, o `(node:123) Warning: …`.
    assert.equal(filho.stderr, "", modo);
    const linhas = filho.stdout.split("\n").filter((linha) => linha !== "");
    assert.equal(linhas.length, 1, modo);
    const linha = JSON.parse(linhas[0] ?? "") as Record<string, unknown>;
    assert.deepEqual(
      [linha.level, linha.svc, linha.error_code, Object.keys(linha).length],
      [nivel, "gwy", erro, 5],
      modo,
    );
    // O relógio aqui é o verdadeiro — é um processo a sério, com `instalar` por
    // omissão. O `ts` traz três algarismos de milissegundos e, uma vez em mil,
    // calham em `923`: o fragmento do canário que a asserção varria no `stdout`
    // inteiro. Era esta a intermitência do gate 4, e não um aviso do Node no
    // `stderr` (esse continua provado acima, e tem de continuar a morder).
    //
    // A asserção não se relaxa, aperta-se: varrem-se **todos** os canários no
    // `stdout` inteiro, em vez de um fragmento de três algarismos; o `ts`
    // prova-se pela forma, pelo que o que não for um instante bem formado
    // falha aqui; e o fragmento continua a morder em todos os outros campos.
    // Nenhum dos 24 canários de `semCanarios` encaixa no molde de um instante
    // ISO, em desvio nenhum; só o fragmento de três algarismos encaixava, nos
    // milissegundos. É por isso que é só ele que tem de sair do varrimento.
    semCanarios(filho.stdout);
    assert.match(String(linha.ts), /^\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2}\.\d{3}Z$/, modo);
    // O fragmento varre-se duas vezes, e nenhuma delas é o que era: no texto
    // cru menos o instante — que já está provado acima — para apanhar o que
    // um `JSON.parse` deixa cair (uma chave repetida, como em `log_policy`
    // §x11); e no objecto reserializado, para apanhar o que vem escapado em
    // `\uXXXX`. O varrimento antigo, sobre o `stdout` cru inteiro, não
    // apanhava o segundo caso — e tropeçava nos milissegundos.
    const cru = filho.stdout.replace(`"${String(linha.ts)}"`, '"ts"');
    const semRelogio = { ...linha };
    delete semRelogio.ts;
    assert.ok(!cru.includes("923"), modo);
    assert.ok(!JSON.stringify(semRelogio).includes("923"), modo);
    assert.ok(!filho.stdout.includes(" at "), modo);
  }
});

test("instalar: os ganchos nao escrevem na consola", (t) => {
  const consola: unknown[][] = [];
  for (const metodo of ["error", "warn", "log", "info", "debug", "trace"] as const) {
    t.mock.method(console, metodo, (...argumentos: unknown[]) => {
      consola.push(argumentos);
    });
  }
  const processo = new ProcessoFalso();
  instalar("gwy", { destino: new Saida(), relogio: () => PARADO, processo });
  processo.tratadores.get("uncaughtException")?.(new Error("923456789"));
  processo.tratadores.get("unhandledRejection")?.(new Error("923456789"));
  processo.tratadores.get("warning")?.(new Error("923456789"));
  t.mock.restoreAll();
  assert.deepEqual(consola, []);
});

test("o que nao e um objecto simples no lugar dos campos conta como mensagem livre", () => {
  // Espelho de `test_o_que_nao_e_um_dicionario_no_lugar_dos_campos_conta`.
  CONTADORES.repor();
  const [registo, saida] = novo();
  class ComClasse {
    outcome = "ok";
  }
  const casos: unknown[] = [
    new RangeError("923456789"),
    new Map([["outcome", "ok"]]),
    new Set(["923456789"]),
    new ComClasse(),
    new Headers({ Authorization: "923456789" }),
  ];
  for (const campos of casos) {
    semTipos(registo, "info", campos);
  }
  assert.equal(saida.linhas().length, 5);
  for (const linha of saida.linhas()) {
    assert.deepEqual(Object.keys(linha), ["ts", "level", "svc"]);
  }
  assert.deepEqual(rejeicoes(), { mensagem_livre: 5 });
  // Um objecto sem protótipo continua a ser «os campos».
  CONTADORES.repor();
  semTipos(registo, "info", Object.assign(Object.create(null), { outcome: "ok" }));
  assert.equal(saida.linhas()[5]?.outcome, "ok");
  assert.deepEqual(rejeicoes(), {});
});

test("instalar: por omissao liga-se ao processo real, sem o terminar", (t) => {
  const ligados: string[] = [];
  const retirados: string[] = [];
  t.mock.method(process, "on", (evento: string) => {
    ligados.push(evento);
    return process;
  });
  t.mock.method(process, "removeAllListeners", (evento: string) => {
    retirados.push(evento);
    return process;
  });
  instalar("gwy", { destino: new Saida() });
  t.mock.restoreAll();
  assert.deepEqual(ligados, ["uncaughtException", "unhandledRejection", "warning"]);
  assert.deepEqual(retirados, ["warning"]);
});

// --- Auxiliares -------------------------------------------------------------------

test("idOpaco nao deixa ver o que resume, e recusa o que nao e texto", () => {
  const opaco = idOpaco(CANARIOS.wamid ?? "");
  assert.match(opaco, /^m_[0-9a-f]{32}$/);
  assert.ok(!opaco.includes("244923456789"));
  assert.equal(opaco, idOpaco(CANARIOS.wamid ?? ""));
  assert.notEqual(opaco, idOpaco(`${CANARIOS.wamid}x`));
  for (const valor of ["", null, 923456789, ["wamid"]]) {
    assert.throws(
      () => idOpaco(valor as string),
      (erro: unknown) => erro instanceof TypeError && !erro.message.includes("923456789"),
    );
  }
});

test("o que a mascara devolve nao cabe em campo nenhum", () => {
  const mascarada = mascararReferencia("123456789");
  assert.equal(mascarada, "***789");
  assert.equal(mascararReferencia("1".repeat(40)).length, 6);
  for (const campo of CAMPOS_DE_CHAMADA) {
    assert.equal(validar(campo, mascarada), null, campo);
  }
});

test("nomeLegivel e codigoComClasse", () => {
  for (const nome of ["telefone", "X-Signature", "webhook_token", "a".repeat(40)]) {
    assert.equal(nomeLegivel(nome), nome);
  }
  for (const nome of [
    "+244 923 456 789", "x923456789", "a".repeat(41), "", 5, null, "com espaco",
    "evt_3kQ9xZ2mP7aLw8Tn5VbR1cYd", "nif2", "_privado", "a__b",
  ]) {
    assert.equal(nomeLegivel(nome), "<nome ilegivel>");
  }
  assert.equal(codigoComClasse("c", "ValueError"), "c:ValueError");
  for (const classe of [null, 5, "", "com espaco", "E923456789", "A1b2C3d4", "E".repeat(65), "a:b"]) {
    assert.equal(codigoComClasse("c", classe), "c");
  }
  assert.equal(codigoComClasse(5, "ValueError"), 5);
});

// --- A metade de compilação do critério --------------------------------------------
//
// Nada disto corre: o que se prova é que **não compila**. Cada linha marcada tem
// de dar erro no `tsc`; se deixar de dar, a directiva fica por usar e o
// `typecheck` do gate 2 falha.

export function provaDeCompilacao(registo: Logger): void {
  // O que compila: só campos da lista, com o tipo de cada um.
  registo.info({ outcome: "ok", tenant_id: TENANT, latency_ms: 3 });
  const campos: CamposDeLog = { tool: "criar_pedido" };
  registo.warn(campos);
  registo.excepcao(new Error("x"), "codigo", { tenant_id: TENANT });

  // @ts-expect-error — `telefone` não está na allowlist (literal).
  registo.info({ telefone: "923456789" });
  // @ts-expect-error — nem ao lado de campos válidos.
  registo.info({ outcome: "ok", nome: "Joaquina" });
  // @ts-expect-error — texto de mensagem não é um campo.
  registo.error({ texto: "Bom dia", outcome: "ok" });
  // @ts-expect-error — `morada` e `transcricao` também não.
  registo.warn({ morada: "Rua da Missao", transcricao: "..." });
  // @ts-expect-error — cabeçalhos não são um campo.
  registo.info({ headers: { Authorization: "x" } });

  const guardado = { outcome: "ok", telefone: "923456789" };
  // @ts-expect-error — nem por uma variável, que escaparia à verificação de literais.
  registo.info(guardado);
  const semChaves: object = guardado;
  // @ts-expect-error — nem por um `object`, que não diz que chaves tem (revisão, A3).
  registo.info(semChaves);
  const vazio: {} = guardado;
  // @ts-expect-error — nem por um `{}`.
  registo.warn(vazio);
  // @ts-expect-error — nem em `excepcao`.
  registo.excepcao(new Error("x"), "codigo", semChaves);
  const espalhado = { ...guardado, tool: "criar_pedido" };
  // @ts-expect-error — nem por um objecto espalhado.
  registo.debug(espalhado);

  // @ts-expect-error — os campos reservados são do logger, não de quem chama.
  registo.info({ svc: "outro" });
  // @ts-expect-error — idem.
  registo.info({ ts: "2026-01-01T00:00:00.000Z" });
  // @ts-expect-error — idem.
  registo.info({ level: "info" });

  // @ts-expect-error — `latency_ms` é um número.
  registo.info({ latency_ms: "42" });
  // @ts-expect-error — `outcome` é texto.
  registo.info({ outcome: 1 });
  // @ts-expect-error — um valor aninhado não é texto.
  registo.info({ tool: { nome: "criar_pedido" } });

  // @ts-expect-error — não há mensagem livre.
  registo.info("pedido recebido");
  // @ts-expect-error — nem um número.
  registo.info(923456789);
  // @ts-expect-error — nem uma lista de textos.
  registo.info(["pedido recebido"]);
  // @ts-expect-error — nem um segundo argumento.
  registo.info({ outcome: "ok" }, "pedido recebido");
  // @ts-expect-error — o código de um erro é texto, não o erro.
  registo.excepcao(new Error("x"), new Error("y"));
  // @ts-expect-error — em `excepcao` o `error_code` é o segundo argumento.
  registo.excepcao(new Error("x"), "codigo", { error_code: "outro" });
  // @ts-expect-error — e os campos continuam a ser só os da lista.
  registo.excepcao(new Error("x"), "codigo", { mensagem: "falhou" });
}

test("a prova de compilacao existe e nao e chamada", () => {
  assert.equal(typeof provaDeCompilacao, "function");
});
