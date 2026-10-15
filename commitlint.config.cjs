/**
 * commitlint — Conventional Commits com ID de ticket (specs/01 §5).
 *
 * As regras NAO estao escritas aqui: leem-se de `tools/conventions.json`, que e
 * tambem o que `tools/lint_arch/conventions.py` le.
 *
 * A promessa e "o hook nao pode aceitar o que o CI recusa", e cumpri-la exige
 * disciplina nas duas direccoes: **toda** a regra activa aqui tem de existir no
 * JSON e estar implementada no lado Python. Uma regra que so exista aqui e uma
 * divergencia — e foi assim que uma revisao encontrou tres (`subject-case`
 * `lower-case`, `body-leading-blank` e `footer-leading-blank` eram impostas pelo
 * commitlint e ignoradas pelo hook). As regras que o `@commitlint/config-conventional`
 * traz e que nao queremos sao desligadas explicitamente abaixo.
 */

const { readFileSync } = require("node:fs");
const { join } = require("node:path");

const conventions = JSON.parse(
  readFileSync(join(__dirname, "tools/conventions.json"), "utf8"),
);

const {
  types,
  scopePattern,
  subjectMinLength,
  subjectMaxLength,
  headerMaxLength,
  subjectEndsWithoutPeriod,
  bodyLeadingBlank,
  footerLeadingBlank,
} = conventions.commit;

const scope = new RegExp(scopePattern);
const ERRO = 2;
const DESLIGADA = 0;

module.exports = {
  extends: ["@commitlint/config-conventional"],
  rules: {
    "type-enum": [ERRO, "always", types],
    "type-case": [ERRO, "always", "lower-case"],
    "type-empty": [ERRO, "never"],

    // O ambito e obrigatorio e tem de ser o ticket.
    "scope-empty": [ERRO, "never"],
    "kamba-scope-is-ticket": [ERRO, "always"],
    // `KAM-001` tem maiusculas. O config-conventional nao impoe `scope-case`
    // hoje, mas desliga-se explicitamente para que uma versao futura que a
    // acrescente nao recuse de um dia para o outro o formato que o ticket manda.
    "scope-case": [DESLIGADA],

    "subject-empty": [ERRO, "never"],
    "subject-min-length": [ERRO, "always", subjectMinLength],
    "subject-max-length": [ERRO, "always", subjectMaxLength],
    "header-max-length": [ERRO, "always", headerMaxLength],
    // `never [...]` e o default do config-conventional: recusa a frase inteira
    // em maiusculas ou capitalizada, mas **permite siglas no meio**. O projecto
    // escreve RLS, HMAC, BSUID, Postgres, APD, AGT e BNA todos os dias.
    "subject-case": [
      ERRO,
      "never",
      ["sentence-case", "start-case", "pascal-case", "upper-case"],
    ],
    "subject-full-stop": subjectEndsWithoutPeriod
      ? [ERRO, "never", "."]
      : [DESLIGADA],

    "body-leading-blank": bodyLeadingBlank ? [ERRO, "always"] : [DESLIGADA],
    "footer-leading-blank": footerLeadingBlank ? [ERRO, "always"] : [DESLIGADA],
  },
  plugins: [
    {
      rules: {
        "kamba-scope-is-ticket": ({ scope: value }) => [
          value !== null && value !== undefined && scope.test(value),
          `o ambito tem de ser o ticket, no formato ${scopePattern} ` +
            "(ex.: chore(KAM-001): cria a arvore do monorepo)",
        ],
      },
    },
  ],
};
