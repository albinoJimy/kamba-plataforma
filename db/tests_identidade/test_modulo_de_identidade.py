"""O modulo de identidade (TypeScript) contra o PostgreSQL do gate — KAM-008.

O codigo vive em `packages/core-ts/src/identity/` e os seus testes de base de
dados em `packages/core-ts/tests_bd/`. Esta suite e o que os poe a correr contra
a base descartavel, com os papeis verdadeiros e as migracoes em `head`, e e ela
que mede o que so se mede **de fora** do processo que resolve contactos:

    o *dump*      `pg_dump` da base inteira, depois de semear 1 000 contactos
                  com BSUID e telefone canario: zero ocorrencias em claro.
    o registo     o que o servidor registou com `log_statement = 'all'`
                  durante esse ensaio — instrucoes **e parametros**.
    a saida       o que os testes escreveram para o terminal.
    a cobertura   de `src/identity/`, medida nesta execucao: o gate 4 nao tem
                  base de dados, e `contactos.ts` sem base nao corre.

Um canario procura-se em duas formas: tal como e, e em hexadecimal — que e como
o `pg_dump` e o registo escrevem um `bytea`. Um BSUID guardado em claro numa
coluna `bytea` nao aparecia como texto; aparecia como `\\x414f2e43…`.
"""

from __future__ import annotations

import json
import re
import shutil
import sys
import tempfile
import unittest
import uuid
from pathlib import Path

import ligacao
from tests.base import ComBase
from tests_identidade import node

sys.path.insert(0, str(node.RAIZ / "tools"))

from kamba_yaml import load_file  # noqa: E402

#: Os ficheiros de teste, pela ordem em que correm. Os tres primeiros nao
#: precisam de base (correm tambem no gate 4); o ultimo so corre aqui.
FICHEIROS = (
    "tests/identity.cripto.test.ts",
    "tests/identity.chaves.test.ts",
    "tests/identity.servico.test.ts",
    "tests_bd/identity.bd.test.ts",
)

#: Os grupos de `tests_bd/identity.bd.test.ts`: um por criterio de aceitacao que
#: so se prova contra a base. Se um desaparecer, a suite deixa de provar esse
#: criterio — e isso tem de falhar aqui, nao passar por haver menos testes.
GRUPOS = (
    "antes de haver chave",
    "critério 1 — só cifrado, e só em contact_endpoints",
    "critério 4 — ordem de resolução, completar e fundir",
    "isolamento de tenant — o teste cruzado",
    "critério 6 — eraseContact",
    "critério 2 — canários",
    "critérios 3 e 5 — idempotência e rotação",
)

#: Testes que **tem** de ter corrido e passado, pelo nome. Lista curta, com os
#: que dao a letra de cada criterio.
TESTES_OBRIGATORIOS = (
    "1000 contactos com BSUID e telefone canário: nada em claro no que vai para a base",
    "10000 BSUID aleatórios, resolvidos em paralelo: um contacto cada",
    "10000 chamadas repetidas devolvem o mesmo contact_id, e não criam nada",
    "dois contactos que se revelam o mesmo fundem-se no mais antigo e devolvem contact.merged",
    "fusão com falha a meio: rollback completo, e a seguir funde como se nada fosse",
    "rekeyLookup é retomável: interrompido a meio, continua de onde ficou",
    "no fim, 100% das linhas têm a versão nova — e o HMAC é o da chave nova",
    "ponta a ponta: endpoints apagados, DEK destruída, e o BSUID original é alguém novo",
    "com o papel da aplicação, o módulo não resolve nem lê",
)

#: Os cinco ficheiros do modulo. A cobertura mede-se em **cada um**.
FICHEIROS_DO_MODULO = ("chaves.ts", "consultas.ts", "contactos.ts", "cripto.ts", "index.ts")


def _cobertura(lcov: str) -> dict[str, tuple[int, int]]:
    """ficheiro de `src/identity/` -> (linhas cobertas, linhas encontradas)."""
    medidas: dict[str, tuple[int, int]] = {}
    actual = None
    cobertas = encontradas = 0
    for linha in lcov.splitlines():
        if linha.startswith("SF:"):
            actual = linha[3:].replace("\\", "/")
            cobertas = encontradas = 0
        elif linha.startswith("DA:") and actual is not None:
            _, execucoes = linha[3:].split(",")[:2]
            encontradas += 1
            cobertas += int(execucoes) > 0
        elif linha == "end_of_record" and actual is not None:
            if "/src/identity/" in f"/{actual}":
                medidas[actual.rsplit("/", 1)[-1]] = (cobertas, encontradas)
            actual = None
    return medidas


def _formas(canario: str) -> tuple[bytes, bytes]:
    """Um canario em claro, e como um `bytea` o mostraria (hexadecimal)."""
    return canario.encode("ascii"), canario.encode("ascii").hex().encode("ascii")


class TestModuloDeIdentidade(ComBase):
    """Corre os testes em Node **uma vez**, e depois olha para o que ficou."""

    @classmethod
    def setUpClass(cls) -> None:
        super().setUpClass()
        cls.saida = Path(tempfile.mkdtemp(prefix="kamba-identidade-"))
        cls.execucao = node.correr(
            [
                "--test",
                # Um ficheiro de cada vez: a tabela de versoes de chave e global.
                "--test-concurrency=1",
                "--experimental-test-coverage",
                "--test-reporter=tap",
                "--test-reporter-destination=stdout",
                "--test-reporter=lcov",
                "--test-reporter-destination={saida}/identidade.lcov",
                *FICHEIROS,
            ],
            cls.saida,
        )
        cls.tap = cls.execucao.stdout
        cls.escrito = cls.execucao.stdout + cls.execucao.stderr
        ficheiro = cls.saida / "canarios.json"
        cls.ensaio = (
            json.loads(ficheiro.read_text(encoding="utf-8")) if ficheiro.is_file() else None
        )
        # O controlo da procura: dois valores postos **em claro** de proposito,
        # um numa coluna `bytea` e outro numa de texto, e mandados ao servidor
        # como parametros com o registo ligado. Sao o que um canario seria se o
        # modulo o deixasse escapar — e a procura tem de os encontrar no *dump*
        # e no registo verdadeiros, e nao numa cadeia que o proprio teste montou.
        cls.controlos = cls._por_controlos() if cls.ensaio else None
        # Depois dos testes, e antes de qualquer limpeza: e isto que se procura.
        cls.dump = node.dump_completo()
        cls.registo = node.registo_do_servidor()

    @classmethod
    def _por_controlos(cls) -> dict[str, str]:
        em_bytea = f"AO.CONTROLOBYTEA{uuid.uuid4().hex}"
        em_texto = f"AO.CONTROLOTEXTO{uuid.uuid4().hex}"
        admin = ligacao.ligar("admin")
        admin.autocommit = True
        try:
            cursor = admin.cursor()
            tenant = cls.ensaio["tenant"]
            cursor.execute("SET log_statement = 'all'")
            cursor.execute(
                "INSERT INTO platform.contacts (tenant_id) VALUES (%s) RETURNING contact_id",
                (tenant,),
            )
            contacto = cursor.fetchone()[0]
            cursor.execute(
                "INSERT INTO platform.contact_deks (tenant_id, contact_id, wrapped_dek, kek_id) "
                "VALUES (%s, %s, %s, %s) RETURNING dek_id",
                (tenant, contacto, em_bytea.encode("ascii"), em_texto),
            )
            cursor.fetchone()
        finally:
            admin.close()
        return {"bytea": em_bytea, "texto": em_texto}

    @classmethod
    def tearDownClass(cls) -> None:
        try:
            if cls.ensaio:
                admin = ligacao.ligar("admin")
                admin.autocommit = True
                try:
                    cursor = admin.cursor()
                    for tabela in ("contact_endpoints", "contact_deks", "contacts"):
                        cursor.execute(
                            f"DELETE FROM platform.{tabela} WHERE tenant_id = %s",
                            (cls.ensaio["tenant"],),
                        )
                    cursor.execute(
                        "DELETE FROM platform.tenants WHERE id = %s", (cls.ensaio["tenant"],)
                    )
                    cursor.execute("DELETE FROM platform.hmac_key_versions")
                finally:
                    admin.close()
        finally:
            shutil.rmtree(cls.saida, ignore_errors=True)
            super().tearDownClass()

    def resumo(self, campo: str) -> int:
        encontro = re.search(rf"^# {campo} (\d+)$", self.tap, re.MULTILINE)
        self.assertIsNotNone(encontro, f"o resumo do Node nao tem `# {campo}`:\n{self.escrito[-3000:]}")
        return int(encontro.group(1))

    # ------------------------------------------------------------ os testes

    def test_os_testes_do_modulo_passam(self) -> None:
        self.assertEqual(
            self.execucao.returncode,
            0,
            "os testes de identidade falharam:\n"
            + "\n".join(
                linha for linha in self.escrito.splitlines()
                if re.match(r"\s*(not ok|# fail|\s+(error|message|code|stack):)", linha)
            )[:6000]
            + "\n...\n"
            + self.escrito[-2500:],
        )
        self.assertEqual(self.resumo("fail"), 0)
        self.assertEqual(self.resumo("cancelled"), 0)

    def test_nenhum_teste_foi_saltado_nem_ficou_por_fazer(self) -> None:
        """Num gate, saltar e falhar — tambem dentro do Node."""
        self.assertEqual(self.resumo("skipped"), 0)
        self.assertEqual(self.resumo("todo"), 0)
        self.assertEqual(self.resumo("pass"), self.resumo("tests"))

    def test_correram_os_grupos_e_os_testes_de_cada_criterio(self) -> None:
        for grupo in GRUPOS:
            with self.subTest(grupo=grupo):
                self.assertIn(f"# Subtest: {grupo}\n", self.tap)
        for nome in TESTES_OBRIGATORIOS:
            with self.subTest(teste=nome):
                self.assertRegex(self.tap, rf"(?m)^\s*ok \d+ - {re.escape(nome)}$")
        self.assertGreaterEqual(self.resumo("tests"), 100)

    def test_a_imagem_do_node_e_a_versao_do_repositorio(self) -> None:
        """A imagem de recurso (sem `node` no `PATH`) nao pode divergir de `.node-version`."""
        ficheiro = node.RAIZ / ".node-version"
        if ficheiro.is_file():  # a copia da prova por mutacao nao o leva
            versao = ficheiro.read_text(encoding="utf-8").strip()
            self.assertTrue(
                node.IMAGEM_NODE.startswith(f"node:{versao}-trixie-slim@sha256:"),
                node.IMAGEM_NODE,
            )

    # ---------------------------------------------------------- a cobertura

    def test_a_cobertura_do_codigo_de_identidade_e_de_90_por_ficheiro(self) -> None:
        """DoD: «cobertura >= 90% no codigo de identidade». Por ficheiro, sem media.

        O limiar e o do estrato `critico` de `ci/thresholds.yaml`, lido de la.
        """
        estratos = load_file(node.RAIZ / "ci" / "thresholds.yaml")["estratos"]
        minimo = next(e["minimo_linhas"] for e in estratos if e["nome"] == "critico")
        self.assertEqual(minimo, 90)

        lcov = (self.saida / "identidade.lcov").read_text(encoding="utf-8")
        medidas = _cobertura(lcov)
        self.assertEqual(sorted(medidas), sorted(FICHEIROS_DO_MODULO))
        for ficheiro, (cobertas, encontradas) in sorted(medidas.items()):
            with self.subTest(ficheiro=ficheiro):
                self.assertGreater(encontradas, 0)
                # Truncado, como o gate 4: 89,9% nao e 90%.
                percentagem = int(100 * cobertas / encontradas)
                print(
                    f"    cobertura de src/identity/{ficheiro}: {percentagem}% "
                    f"({cobertas}/{encontradas} linhas)",
                    file=sys.stderr,
                )
                self.assertGreaterEqual(
                    percentagem, minimo, f"{ficheiro}: {cobertas}/{encontradas} linhas"
                )

    # ----------------------------------------------------------- os canarios

    def canarios(self) -> list[str]:
        self.assertIsNotNone(self.ensaio, "o ensaio dos canarios nao deixou canarios.json")
        self.assertEqual(self.ensaio["contactos"], 1000)
        canarios = self.ensaio["canarios"]
        # 1 000 BSUID e 1 000 telefones, todos diferentes.
        self.assertEqual(len(canarios), 2000)
        self.assertEqual(len(set(canarios)), 2000)
        self.assertEqual(sum(c.startswith("AO.CANARIO") for c in canarios), 1000)
        self.assertEqual(sum(c.isdigit() and len(c) == 12 for c in canarios), 1000)
        return canarios

    def contem(self, onde: bytes, agulha: bytes, rotulo: str) -> None:
        """`assertIn` sem despejar megabytes de *dump* na mensagem de falha."""
        self.assertTrue(agulha in onde, f"{rotulo}: nao encontrei {agulha[:80]!r}")

    def procurar(self, onde: bytes, rotulo: str) -> None:
        achados = self.achados(onde, self.canarios())
        # Sem os valores na mensagem: um canario e sintetico, mas a forma da
        # falha e a mesma que teria um numero verdadeiro.
        self.assertEqual(
            len(achados), 0, f"{len(achados)} canario(s) em claro em {rotulo}"
        )

    def test_o_dump_completo_da_base_nao_tem_nenhum_canario(self) -> None:
        """Criterio 2: 0 ocorrencias, nas duas formas, no `pg_dump` da base inteira."""
        self.canarios()
        tenant = self.ensaio["tenant"].encode("ascii")
        # O *dump* e o que se pensa que e: tem as tres tabelas, as linhas do
        # tenant do ensaio, e o valor de controlo que **tem** de la estar.
        for tabela in (b"contacts", b"contact_endpoints", b"contact_deks"):
            self.contem(self.dump, b"COPY platform." + tabela + b" (", "dump")
        # 1 000 contactos + 2 000 endpoints + 1 000 DEK, cada linha com o tenant.
        self.assertGreaterEqual(self.dump.count(tenant), 4000)
        self.contem(self.dump, self.ensaio["controlo"].encode("ascii"), "dump (controlo)")
        self.procurar(self.dump, "no dump da base")

    def achados(self, onde: bytes, valores: list[str]) -> list[str]:
        return [v for v in valores if any(forma in onde for forma in _formas(v))]

    def test_a_procura_encontra_o_que_esta_em_claro_no_dump_e_no_registo(self) -> None:
        """A prova de que a procura morde, contra o *dump* e o registo verdadeiros.

        Os dois controlos foram postos em claro na base (um em `bytea`, outro em
        texto) e passaram pelo registo como parametros. A mesma procura dos
        canarios tem de encontrar **os dois, nos dois sitios**: se deixasse de
        procurar a forma em que o PostgreSQL escreve um `bytea`, ou a forma em
        texto, um dos quatro falhava.
        """
        self.assertIsNotNone(self.controlos, "o ensaio nao chegou a por os controlos")
        for sitio, onde in (("dump", self.dump), ("registo", self.registo)):
            for tipo, valor in self.controlos.items():
                with self.subTest(sitio=sitio, coluna=tipo):
                    self.assertEqual(self.achados(onde, [valor]), [valor])
        # E cada controlo esta la **so** na forma do seu tipo: o de `bytea` nao
        # aparece como texto no *dump* — e por isso que se procuram as duas.
        em_claro, em_hex = _formas(self.controlos["bytea"])
        self.assertNotIn(em_claro, self.dump)
        self.assertIn(em_hex, self.dump)

    def test_o_registo_do_servidor_nao_tem_nenhum_canario(self) -> None:
        """Com `log_statement = 'all'`: instrucoes e parametros, tudo registado."""
        self.canarios()
        # O registo e o que se pensa que e: tem as instrucoes do ensaio, com os
        # parametros — o valor de controlo foi para a base como parametro.
        self.contem(self.registo, b"INSERT INTO platform.contact_endpoints", "registo")
        # «Parameters: $1 = '<tenant>'…»: a caixa do P mudou entre versoes do servidor.
        self.contem(
            self.registo,
            b"arameters: $1 = '" + self.ensaio["tenant"].encode("ascii"),
            "registo (parametros)",
        )
        self.contem(
            self.registo, self.ensaio["controlo"].encode("ascii"), "registo (controlo)"
        )
        self.procurar(self.registo, "no registo do PostgreSQL")

    def test_o_servidor_voltou_a_nao_registar_instrucoes(self) -> None:
        """O ensaio liga `log_statement` e tem de o desligar, corra bem ou mal."""
        self.assertEqual(self.consultar("SHOW log_statement"), [("none",)])

    def test_a_saida_dos_testes_nao_tem_nenhum_canario(self) -> None:
        """O modulo nao regista nada; os testes tambem nao podem despejar o que semeiam."""
        self.procurar(self.escrito.encode("utf-8", "replace"), "na saida dos testes")


if __name__ == "__main__":
    unittest.main()
